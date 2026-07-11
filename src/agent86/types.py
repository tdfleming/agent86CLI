"""Shared vocabulary for the harness.

These types are the lingua franca that crosses tier boundaries: the Cognitive Tier
speaks ``Message`` / ``Completion``, the Tool Tier speaks ``ToolSpec`` / ``ToolCall`` /
``ToolResult``, and the Orchestration Tier records ``Step`` history in the ``AgentState``
finite state machine. Keeping them provider-agnostic is what lets one orchestrator drive
Anthropic, OpenAI, Ollama, and llama.cpp interchangeably.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Roles & phases
# --------------------------------------------------------------------------- #


class Role(StrEnum):
    """Message author, in the unified conversation format."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AgentPhase(StrEnum):
    """Finite-state-machine phases the orchestrator drives an agent through.

    The book's canonical lifecycle: Initialization -> Planning -> Execution ->
    Verification -> Completion, with an explicit ERROR sink for graceful halts.
    """

    INIT = "init"
    PLAN = "plan"
    EXECUTE = "execute"
    VERIFY = "verify"
    DONE = "done"
    ERROR = "error"


class ApprovalMode(StrEnum):
    """Human-in-the-loop posture for a side-effectful tool call."""

    AUTO = "auto"  # run without asking
    ASK = "ask"  # prompt the user before running
    DENY = "deny"  # never run


# --------------------------------------------------------------------------- #
# Model references
# --------------------------------------------------------------------------- #


class ModelRef(BaseModel):
    """A ``provider:model`` reference, e.g. ``anthropic:claude-opus-4-8``."""

    provider: str
    model: str

    @classmethod
    def parse(cls, ref: str) -> ModelRef:
        if ":" not in ref:
            raise ValueError(
                f"Model reference {ref!r} must be 'provider:model' "
                "(e.g. 'anthropic:claude-opus-4-8')."
            )
        provider, _, model = ref.partition(":")
        provider, model = provider.strip(), model.strip()
        if not provider or not model:
            raise ValueError(f"Model reference {ref!r} has an empty provider or model.")
        return cls(provider=provider, model=model)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.provider}:{self.model}"


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #


class ToolSpec(BaseModel):
    """Declarative description of a tool the model may call.

    ``parameters`` is a JSON Schema object; the harness both advertises it to the
    model and validates the model's arguments against it before execution.
    """

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    # Guardrail hint: does invoking this tool cause an external side effect?
    side_effecting: bool = False


class ToolCall(BaseModel):
    """The model's *intent* to invoke a tool — an untrusted request, not a command."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """The deterministic outcome of executing a ``ToolCall``."""

    call_id: str
    name: str
    ok: bool = True
    content: str = ""
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Messages & completions
# --------------------------------------------------------------------------- #


class Message(BaseModel):
    """A single turn in the unified conversation format."""

    role: Role
    content: str = ""
    # Present on assistant turns that request tools:
    tool_calls: list[ToolCall] = Field(default_factory=list)
    # Present on tool-result turns:
    tool_call_id: str | None = None
    name: str | None = None


class Usage(BaseModel):
    """Token accounting for a single model call."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )


class CompletionRequest(BaseModel):
    """What the Orchestration Tier hands to a ``ModelProvider``."""

    model: str
    messages: list[Message]
    tools: list[ToolSpec] = Field(default_factory=list)
    temperature: float = 0.0
    max_tokens: int | None = None
    stream: bool = False


class Completion(BaseModel):
    """A model's proposed next step: free text and/or tool calls."""

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    stop_reason: str | None = None
    model: str | None = None


class CompletionDelta(BaseModel):
    """One streamed chunk of a completion."""

    text: str = ""
    done: bool = False


# --------------------------------------------------------------------------- #
# Execution history
# --------------------------------------------------------------------------- #


class Step(BaseModel):
    """One iteration of the ReAct loop, recorded in the flight-data recorder."""

    index: int
    phase: AgentPhase
    thought: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    results: list[ToolResult] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)


__all__ = [
    "Role",
    "AgentPhase",
    "ApprovalMode",
    "ModelRef",
    "ToolSpec",
    "ToolCall",
    "ToolResult",
    "Message",
    "Usage",
    "CompletionRequest",
    "Completion",
    "CompletionDelta",
    "Step",
]
