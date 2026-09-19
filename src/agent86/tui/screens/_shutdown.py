"""Tolerant widget lookup for modals that can be mounted while the app is shutting down.

Textual normally mounts everything `compose` yielded *before* it dispatches `Mount`, so a
`query_one` in `on_mount` is safe. That guarantee lapses in the shutdown window: once
`App._running` flips False, `App._register` deliberately returns no widgets ("prevent awaiting
of the widget tasks"), so `mount_all` stops awaiting the composed children and `Mount` reaches
the screen with an empty dialog. An unguarded `query_one` then raises `NoMatches` straight out
of `on_mount`, Textual routes it to `App._handle_exception`, and `run_test()` re-raises it from
whichever test's teardown happens to be in flight — the order-dependent flake fixed in 67a79ca.

Any modal that can be pushed from a worker result is exposed to this, because a worker's result
can land at any moment, the shutdown window included. The same applies to a worker-completion
callback that mutates widgets: by the time it runs on the main thread the screen may already be
gone.

Two rules follow, and they are all this module exists to make cheap:

* Look widgets up with :func:`maybe_one`, which yields None instead of raising.
* Return early from a worker-completion callback when ``self.is_running`` is False.

Mounting is all-or-nothing — either `mount_all` mounted the composed children or it mounted
none of them — so one sentinel lookup is enough to decide whether a whole `on_mount` body has
anything to work on.
"""

from __future__ import annotations

from typing import TypeVar

from textual.dom import DOMNode
from textual.widget import Widget

WidgetT = TypeVar("WidgetT", bound=Widget)


def maybe_one(node: DOMNode, selector: str, expect_type: type[WidgetT]) -> WidgetT | None:
    """`query_one`, but None rather than `NoMatches` when the widget is not mounted.

    A None here means "this screen has no children", which in practice means the app is being
    torn down — there is nothing to focus, fill, or update, and nothing to report.
    """
    found = node.query(selector)
    if not found:
        return None
    return found.first(expect_type)


__all__ = ["maybe_one"]
