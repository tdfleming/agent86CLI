"""Tool interface (Tier 4, Pillar 3).

A tool declares a Pydantic ``Args`` model; the harness derives the JSON Schema it
advertises to the model *and* validates the model's arguments against it before anything
runs. Invalid arguments come back as a structured ``ToolResult`` error the model can
self-correct from (the book's fuzzy->rigid translation pattern), never an exception that
crashes the loop.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from agent86.types import ToolCall, ToolResult, ToolSpec

#: Each tool binds this to its own ``Args`` model, so ``execute`` is type-checked against the
#: concrete argument type without violating the base-class contract (Liskov).
TArgs = TypeVar("TArgs", bound=BaseModel)

if TYPE_CHECKING:
    from agent86.config import Config
    from agent86.memory.semantic import SemanticMemory
    from agent86.skills.models import Skill
    from agent86.tools.sandbox.executor import Executor
    from agent86.tools.sandbox.policy import SandboxPolicy


@dataclass
class ToolContext:
    """Ambient state handed to every tool at execution time."""

    workspace: Path
    policy: SandboxPolicy
    config: Config
    memory: SemanticMemory | None = None
    skills: dict[str, Skill] = field(default_factory=dict)
    # Spawn a sub-agent: (role, task) -> final result text. Set when multi-agent is enabled.
    spawn: Callable[[str, str], str] | None = None
    # Execution backend (subprocess or docker); tools fall back to the default if unset.
    executor: Executor | None = None
    extra: dict[str, object] = field(default_factory=dict)

    def get_executor(self) -> Executor:
        from agent86.tools.sandbox.executor import get_default_executor

        return self.executor or get_default_executor()


class EmptyArgs(BaseModel):
    """Default argument model for tools that take no parameters."""


class Tool(ABC, Generic[TArgs]):
    """Base class for all tools (built-in, MCP-backed, or skill-provided).

    Generic over the tool's ``Args`` model. A tool binds it by subclassing
    ``Tool["MyTool.Args"]`` (or ``Tool[EmptyArgs]`` for a no-argument tool), which lets
    ``execute`` take the concrete argument type without breaking the base contract.
    """

    name: str = ""
    description: str = ""
    #: True if invoking the tool causes an external side effect (gated by the HITL gate).
    side_effecting: bool = False
    #: Pydantic model describing this tool's arguments (bound to the generic ``TArgs``).
    Args: type[TArgs]

    def spec(self) -> ToolSpec:
        """Advertise this tool to the model as a validated JSON-Schema function."""
        schema = self.Args.model_json_schema()
        # Anthropic/OpenAI want a plain object schema; drop the pydantic title noise.
        schema.pop("title", None)
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=schema,
            side_effecting=self.side_effecting,
        )

    @abstractmethod
    def execute(self, args: TArgs, ctx: ToolContext) -> ToolResult:
        """Run the tool with already-validated ``args``."""
        raise NotImplementedError

    def run(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        """Validate arguments, then execute — translating failures into ToolResults."""
        try:
            args = self.Args.model_validate(call.arguments)
        except ValidationError as exc:
            return ToolResult(
                call_id=call.id,
                name=self.name,
                ok=False,
                error=f"Invalid arguments for '{self.name}': {_format_validation(exc)}",
            )
        try:
            result = self.execute(args, ctx)
        except Exception as exc:  # tools must not crash the loop
            return ToolResult(
                call_id=call.id, name=self.name, ok=False, error=f"{type(exc).__name__}: {exc}"
            )
        # Ensure identity fields are populated even if a tool constructs a bare result.
        result.call_id = result.call_id or call.id
        result.name = result.name or self.name
        return result


def _format_validation(exc: ValidationError) -> str:
    bits = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        bits.append(f"{loc}: {err['msg']}")
    return "; ".join(bits)


__all__ = ["Tool", "ToolContext", "EmptyArgs"]
