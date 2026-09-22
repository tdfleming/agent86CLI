"""A reactive footer widget that renders the status line, fitted to the terminal width.

`agent86.ui.status` owns *what* the line says (`status_segments`); this module owns *how
much of it fits*. Measured at v0.8: the full idle line wraps onto a second row at 80 and
100 columns and only settles at one row from ~127 — and a two-row footer eats a transcript
row and jitters as the numbers change.

So under width pressure the footer sheds, in order:

1. the ``[Shift+Tab]`` key hint — discoverability, and it is also in ``/help``;
2. the token counts — the same numbers, exactly, are one ``/cost`` away;
3. the ctx gauge — the last thing to go, since a full context window is the failure this
   milestone exists to make visible.

The model name, the cost, the approval mode and the working/phase indicator are never shed:
they say what is running, what it is costing, and whether it can act without asking.

`format_status_line`/`_Repl.status_line` have no call site in the plain path — the plain loop
has no live status surface at all, only this widget consumes them. That gap is exactly why
`ui/repl.py`'s `banner(cfg, compact=False)` appends sandbox and approval for the plain loop
(quick task 260922-bnr): it is the only place a `--plain` user ever sees them. Giving the
plain loop its own live status line is a separate, out-of-scope change.
"""

from __future__ import annotations

from rich.cells import cell_len
from textual import events
from textual.reactive import reactive
from textual.widgets import Static

from agent86.ui.status import StatusState, join_segments, status_segments

#: Segment keys, in the order they are given up. Anything not named here is never shed.
SHED_ORDER: tuple[str, ...] = ("hint", "tok", "ctx")


def fit_status_line(status: StatusState, width: int) -> str:
    """Render ``status`` as one line no wider than ``width`` (0 / negative = unlimited).

    Sheds whole segments in :data:`SHED_ORDER` until the line fits, and stops shedding the
    moment it does — a narrow terminal loses the key hint, a very narrow one the tokens too.
    A width too small for even the protected segments returns them anyway: truncating the
    model name or the approval mode would be worse than a wrap.
    """
    segments = status_segments(status)
    line = join_segments(segments)
    if width <= 0 or cell_len(line) <= width:
        return line
    for key in SHED_ORDER:
        segments = [s for s in segments if s.key != key]
        line = join_segments(segments)
        if cell_len(line) <= width:
            break
    return line


class StatusFooter(Static):
    """Persistent bottom status line, live during turn processing."""

    # always_update=True: StatusState is a mutable dataclass mutated in place by the app;
    # without it, reassigning the same object would not re-fire watch_status (RESEARCH Pitfall 2).
    status: reactive[StatusState | None] = reactive(None, always_update=True)

    def watch_status(self, status: StatusState | None) -> None:
        if status is not None:
            self._render_line(self.size.width)

    def on_resize(self, event: events.Resize) -> None:
        # The width the line has to fit changed; re-fit it. `event.size` is the NEW size —
        # `self.size` is not guaranteed to have caught up yet.
        self._render_line(event.size.width)

    def _render_line(self, width: int) -> None:
        status = self.status
        if status is not None:
            self.update(fit_status_line(status, width))


__all__ = ["SHED_ORDER", "StatusFooter", "fit_status_line"]
