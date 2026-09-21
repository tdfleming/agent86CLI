"""Tool interface (Tier 4, Pillar 3).

A tool declares a Pydantic ``Args`` model; the harness derives the JSON Schema it
advertises to the model *and* validates the model's arguments against it before anything
runs. Invalid arguments come back as a structured ``ToolResult`` error the model can
self-correct from (the book's fuzzy->rigid translation pattern), never an exception that
crashes the loop.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, TypeVar

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
    #: The skill the model loaded with ``use_skill``, if any. While it is set and declares
    #: ``allowed-tools``, the registry refuses every other tool (see ``ToolRegistry.dispatch``).
    #: Turn-scoped: the orchestrator clears it at the end of a turn.
    active_skill: Skill | None = None
    extra: dict[str, object] = field(default_factory=dict)

    def get_executor(self) -> Executor:
        from agent86.tools.sandbox.executor import get_default_executor

        return self.executor or get_default_executor()

    def activate_skill(self, skill: Skill) -> None:
        """Make ``skill`` the active one, replacing (never stacking on) any previous skill."""
        self.active_skill = skill

    def clear_skill(self) -> None:
        """Lift the active skill's tool restriction — called at the end of a turn."""
        self.active_skill = None

    def allowed_tool(self, name: str) -> bool:
        """Is ``name`` callable right now, given the active skill's ``allowed-tools``?"""
        skill = self.active_skill
        if skill is None or not skill.allowed_tools:
            return True
        # `use_skill` is always callable: it is how the model activates a *different* skill,
        # and a skill that forgot to list it would otherwise be a one-way door.
        return name == "use_skill" or name in skill.allowed_tools


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
    #: May this tool share a step with its siblings, running concurrently in a worker thread?
    #: Side-effecting tools never do regardless (the orchestrator runs those sequentially, in
    #: order, so their effects stay ordered); this is the extra opt-out for a *read-only* tool
    #: that still cannot be run twice at once — one that drives a shared session, or that can
    #: reach the approval prompt, where two concurrent asks would collide on one terminal.
    parallel_safe: bool = True
    #: Pydantic model describing this tool's arguments (bound to the generic ``TArgs``).
    Args: type[TArgs]
    #: Rich lexer name for whatever ``preview`` returns ("diff", "python", "bash", …), so the
    #: approval UI can highlight it without pattern-matching the text.
    preview_lexer: str | None = None

    def preview(self, arguments: Mapping[str, Any], ctx: ToolContext | None = None) -> str | None:
        """Human-readable detail for the approval prompt — what this call would actually do.

        Default ``None`` means "the argument summary says it all". Tools that mutate state
        override it (``write_file``/``edit_file`` return a unified diff; ``run_command`` and
        ``python_exec`` return the full command/code) so no side effect is ever approved
        sight-unseen behind a truncated JSON blob.

        Called with the **raw, unvalidated** arguments from the model — before ``Args``
        validation — and with the ``ToolContext`` only when the caller has one. It must never
        raise: return ``None`` when the arguments make no sense.
        """
        return None

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
