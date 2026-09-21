"""The v0.9 coding-agent flow, end to end, through the plain loop.

One trajectory, no network and no Textual: the user mentions a file with `@`, the model
asks to edit it, the approval prompt shows the diff it would apply, the user says yes, the
file changes, the turn's cost line is printed — and the session it all happened in is
listed by `/sessions` under the title of that first prompt and reloaded by `/resume`.

Every piece of that has its own focused test elsewhere. This one exists because the pieces
are owned by different modules (`tui.mentions`, `guardrails.policy`, `tools.builtin.files`,
`memory.store`, `ui.repl`) and the wiring between them is exactly what a unit test cannot
see.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

from agent86.cognitive.base import ModelProvider
from agent86.config import load_config
from agent86.memory.embeddings import HashingEmbedder
from agent86.memory.episodic import EpisodicMemory
from agent86.memory.semantic import SemanticMemory
from agent86.memory.store import MemoryStore
from agent86.memory.system import MemorySystem
from agent86.orchestration.loop import Harness
from agent86.types import (
    ApprovalMode,
    Completion,
    CompletionDelta,
    CompletionRequest,
    ToolCall,
    Usage,
)
from agent86.ui.repl import _Repl

NOTES = "# Notes\n\nthe sandbox jial is fine\n"
EDIT = ToolCall(
    id="c1",
    name="edit_file",
    arguments={"path": "notes.md", "old_string": "jial", "new_string": "jail"},
)


class _EditThenExplain(ModelProvider):
    """Asks for the edit on the first call, explains itself on the second.

    Records every request, so the test can prove the `@notes.md` mention reached the model
    as inlined file content rather than as four characters of path.
    """

    name = "v09flow"

    def __init__(self) -> None:
        self.model = "fake:v09flow"
        self.requests: list[CompletionRequest] = []

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        self.requests.append(request)
        if len(self.requests) == 1:
            yield CompletionDelta(
                done=True,
                completion=Completion(
                    text="",
                    tool_calls=[EDIT],
                    usage=Usage(input_tokens=12, output_tokens=4),
                    model=self.model,
                    stop_reason="tool_use",
                ),
            )
            return
        reply = "Fixed the typo: jial -> jail."
        yield CompletionDelta(text=reply)
        yield CompletionDelta(
            done=True,
            completion=Completion(
                text=reply, usage=Usage(input_tokens=20, output_tokens=6), model=self.model
            ),
        )


def _memory(tmp_path) -> MemorySystem:
    store = MemoryStore(tmp_path / "mem.db", HashingEmbedder(64))
    return MemorySystem(store, EpisodicMemory(store), SemanticMemory(store))


def _repl(tmp_path, memory, provider=None):
    cfg = load_config()
    cfg.guardrails.approval = ApprovalMode.ASK
    cfg.ui.history_file = str(tmp_path / "history")
    harness = Harness(
        cfg,
        provider=provider if provider is not None else _EditThenExplain(),
        memory=memory,
        workspace=tmp_path,
    )
    return _Repl(cfg, resume=None, harness=harness), harness


def _drive(repl, monkeypatch, lines):
    """Run `plain_loop` over ``lines`` (the approval prompt reads from the same queue)."""
    pending = list(lines)

    def _fake_input(_prompt=""):
        if not pending:
            raise EOFError
        return pending.pop(0)

    monkeypatch.setattr("builtins.input", _fake_input)
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))
    repl.plain_loop()


def test_mention_edit_approve_and_resume(tmp_path, monkeypatch, capsys):
    (tmp_path / "notes.md").write_text(NOTES, encoding="utf-8")
    memory = _memory(tmp_path)
    repl, harness = _repl(tmp_path, memory)
    provider = harness.provider

    _drive(repl, monkeypatch, ["fix the typo in @notes.md", "y"])
    out = capsys.readouterr().out
    session_id = repl.state.session_id

    # 1. the mention was expanded before the model ever saw the line
    sent = repl.state.messages[0].content
    assert sent.startswith("fix the typo in @notes.md")
    assert "--- @notes.md (3 lines) ---" in sent and "the sandbox jial is fine" in sent
    assert "the sandbox jial is fine" in provider.requests[0].messages[-1].content

    # 2. the approval prompt showed the diff it was about to apply, then asked
    assert "-the sandbox jial is fine" in out
    assert "+the sandbox jail is fine" in out
    assert "approve edit_file?" in out

    # 3. approving actually changed the file
    assert (tmp_path / "notes.md").read_text(encoding="utf-8") == (
        "# Notes\n\nthe sandbox jail is fine\n"
    )

    # 4. and the turn closed with its cost line
    assert "2 steps" in out and "1 tool" in out

    # 5. the session is in the log, titled after the prompt that started it — the line the
    #    user TYPED, exactly, with none of the attached file block bleeding into it.
    title = memory.store.session_title(session_id)
    assert title == "fix the typo in @notes.md"

    # 6. a FRESH repl (new session, same log) lists it and resumes it by short id
    later, _ = _repl(tmp_path, memory, provider=_EditThenExplain())
    assert later.state.session_id != session_id
    _drive(later, monkeypatch, ["/sessions", f"/resume {session_id[:8]}"])
    out = capsys.readouterr().out

    assert "fix the typo in @notes.md" in out           # the /sessions table
    assert f"resumed session {session_id}" in out
    assert later.state.session_id == session_id
    assert "Fixed the typo" in later.state.messages[-1].content


def test_declining_the_edit_leaves_the_file_alone(tmp_path, monkeypatch, capsys):
    """The same trajectory, answered `n`: the model is told why, and nothing was written."""
    (tmp_path / "notes.md").write_text(NOTES, encoding="utf-8")
    repl, _ = _repl(tmp_path, _memory(tmp_path))

    _drive(repl, monkeypatch, ["fix the typo in @notes.md", "n"])
    out = capsys.readouterr().out

    assert (tmp_path / "notes.md").read_text(encoding="utf-8") == NOTES
    assert "declined by user" in out
    observation = next(m for m in repl.state.messages if m.name == "edit_file")
    assert "declined by user" in observation.content
