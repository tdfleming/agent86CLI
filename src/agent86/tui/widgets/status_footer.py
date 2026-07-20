"""A reactive footer widget that renders `format_status_line(StatusState)`.

Reuses `agent86.ui.status` as-is (CONTEXT.md lock) — this module only wires the existing
pure formatter into a Textual widget so the footer re-renders whenever `.status` is
(re)assigned during a turn.
"""

from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static

from agent86.ui.status import StatusState, format_status_line


class StatusFooter(Static):
    """Persistent bottom status line, live during turn processing."""

    # always_update=True: StatusState is a mutable dataclass mutated in place by the app;
    # without it, reassigning the same object would not re-fire watch_status (RESEARCH Pitfall 2).
    status: reactive[StatusState | None] = reactive(None, always_update=True)

    def watch_status(self, status: StatusState | None) -> None:
        if status is not None:
            self.update(format_status_line(status))


__all__ = ["StatusFooter"]
