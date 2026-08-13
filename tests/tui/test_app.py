"""Pilot integration tests for `Agent86App` (TUI-01 shell, TUI-02 live footer, TUI-05 approval).

Builds a real `_Repl` around a real `Harness` with a fake provider (mirrors
`tests/integration/test_repl.py`), drives the app headlessly via `App.run_test()`, and asserts
the shell renders, streams turns on the worker thread with a live footer, and the approval modal
resolves the worker's blocked `threading.Event` on both the approve and deny/escape paths.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator

from textual.widgets import Input, RichLog

from agent86.cognitive.base import ModelProvider
from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.tui.app import Agent86App
from agent86.tui.screens.approval import ApprovalModal
from agent86.tui.screens.model_picker import ModelPickerModal
from agent86.tui.widgets.status_footer import StatusFooter
from agent86.types import ApprovalMode, Completion, CompletionDelta, CompletionRequest, ToolCall, Usage
from agent86.ui.repl import _Repl
from tests.support import ToolThenTextProvider, make_text_provider


class _SlowTextProvider(ModelProvider):
    """Like `make_text_provider`, but sleeps briefly before the final delta.

    Gives the main thread a reliable window to observe `status.working is True` before the
    worker thread posts `TurnDone` — the plain fake provider can complete faster than
    `pilot.press` returns control, making the "live" assertion racy.
    """

    name = "slowtext"

    def __init__(self, reply: str, delay: float = 0.15) -> None:
        self.model = "fake:slowtext"
        self._reply = reply
        self._delay = delay

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        time.sleep(self._delay)
        yield CompletionDelta(text=self._reply)
        yield CompletionDelta(
            done=True,
            completion=Completion(
                text=self._reply,
                usage=Usage(input_tokens=3, output_tokens=2),
                model=self.model,
            ),
        )


def _make_repl(tmp_path, provider, approval=ApprovalMode.AUTO):
    cfg = load_config()
    cfg.guardrails.approval = approval
    harness = Harness(cfg, provider=provider, memory=None, workspace=tmp_path)
    return _Repl(cfg, resume=None, harness=harness)


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("condition not met within timeout")


async def test_shell_has_transcript_input_footer(tmp_path):
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#transcript", RichLog) is not None
        assert app.query_one("#prompt", Input) is not None
        footer = app.query_one("#status", StatusFooter)
        assert footer is not None
        assert repl.harness.provider.model in str(footer.render())


async def test_turn_streams_and_footer_goes_live_then_idle(tmp_path):
    repl = _make_repl(tmp_path, _SlowTextProvider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.value = "hi there"
        await pilot.press("enter")

        # `_start_turn` sets `status.working = True` synchronously on the main thread before
        # the worker starts; the slow provider keeps it there long enough to observe.
        footer = app.query_one("#status", StatusFooter)
        assert repl.status.working is True
        working_text = str(footer.render())
        assert "…" in working_text or "thinking" in working_text

        await _wait_until(lambda: repl.status.working is False)
        await pilot.pause()

        transcript = app.query_one("#transcript", RichLog)
        lines = "\n".join(str(line) for line in transcript.lines)
        assert "hello world" in lines
        idle_text = str(footer.render())
        assert "ctx" in idle_text


async def _run_approval_case(tmp_path, approve: bool):
    call = ToolCall(id="c1", name="write_file", arguments={"path": "out.txt", "content": "hi"})
    provider = ToolThenTextProvider(call, reply="done")
    repl = _make_repl(tmp_path, provider, approval=ApprovalMode.ASK)
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.value = "write a file"
        await pilot.press("enter")
        await pilot.pause()

        await _wait_until(lambda: isinstance(app.screen, ApprovalModal))
        assert isinstance(app.screen, ApprovalModal)

        if approve:
            await pilot.click("#approve")
        else:
            await pilot.press("escape")

        await _wait_until(lambda: repl.status.working is False, timeout=5.0)
        await pilot.pause()

        transcript = app.query_one("#transcript", RichLog)
        lines = "\n".join(str(line) for line in transcript.lines)
        return lines, tmp_path


async def test_approval_modal_resolves_worker_on_approve(tmp_path):
    lines, path = await _run_approval_case(tmp_path, approve=True)
    assert "done" in lines
    assert (path / "out.txt").read_text() == "hi"


async def test_approval_modal_resolves_worker_on_deny(tmp_path):
    lines, path = await _run_approval_case(tmp_path, approve=False)
    assert "done" in lines
    assert not (path / "out.txt").exists()


def test_catalog_cache_starts_empty(tmp_path):
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    assert app._catalog_cache == {}


async def test_catalog_cache_fetches_once_per_provider(monkeypatch, tmp_path):
    import agent86.cognitive.catalog as catalog

    calls = {"n": 0}

    def fake_fetch_catalog(provider, pconf, api_key):
        calls["n"] += 1
        return [("gpt-4o", "gpt-4o")]

    monkeypatch.setattr(catalog, "fetch_catalog", fake_fetch_catalog)

    received = []
    original = Agent86App.on_catalog_ready

    def spy(self, message):
        received.append(message)
        original(self, message)

    monkeypatch.setattr(Agent86App, "on_catalog_ready", spy)

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._request_catalog("openai", "k", "manager")
        await _wait_until(lambda: len(received) == 1)
        await pilot.pause()
        # First fetch's CatalogReady chains into a CatalogPickerModal (Task 2 wiring) — dismiss
        # it before the second request so pushing a fresh screen doesn't race its mount.
        if len(app.screen_stack) > 1:
            app.pop_screen()
            await pilot.pause()
        app._request_catalog("openai", "k", "manager")
        await _wait_until(lambda: len(received) == 2)
    assert calls["n"] == 1


async def test_catalog_failure_yields_empty_entries_with_error(monkeypatch, tmp_path):
    import agent86.cognitive.catalog as catalog

    def fake_fetch_catalog(provider, pconf, api_key):
        raise catalog.CatalogUnavailable("nope")

    monkeypatch.setattr(catalog, "fetch_catalog", fake_fetch_catalog)

    received = []
    original = Agent86App.on_catalog_ready

    def spy(self, message):
        received.append(message)
        original(self, message)

    monkeypatch.setattr(Agent86App, "on_catalog_ready", spy)

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._request_catalog("openai", "k", "manager")
        await _wait_until(lambda: len(received) == 1)
    message = received[0]
    assert message.entries == []
    assert "nope" in message.error


async def test_escape_dismisses_catalog_picker_not_palette(monkeypatch, tmp_path):
    """Escape while a CatalogPickerModal is on top pops it, not the (hidden) palette.

    Regression for the same footgun 02-02/02-04 already fixed for `up`/`down`/`shift+tab`:
    `action_palette_dismiss` is a priority binding that must raise `SkipAction` when the
    palette itself is hidden, so Escape falls through to the modal's own `action_cancel`.
    """
    from agent86.tui.screens.provider_manager import CatalogPickerModal

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(CatalogPickerModal("openai", [("gpt-4o", "gpt-4o")]))
        await pilot.pause()
        assert isinstance(app.screen, CatalogPickerModal)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, CatalogPickerModal)


async def test_model_picker_uses_cached_catalog(monkeypatch, tmp_path):
    import agent86.cognitive.catalog as catalog
    from agent86.tui.commands import find_command

    calls = {"n": 0}

    def fake_fetch_catalog(provider, pconf, api_key):
        calls["n"] += 1
        return [("gpt-4o", "gpt-4o")]

    monkeypatch.setattr(catalog, "fetch_catalog", fake_fetch_catalog)

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._catalog_cache[repl.harness.provider.name] = [("cached:ref", "cached label")]
        app._run_or_chain(find_command("/model"))
        await pilot.pause()
        assert isinstance(app.screen, ModelPickerModal)
    assert calls["n"] == 0


async def test_model_picker_prefixes_cached_ollama_catalog_entry(tmp_path):
    """End-to-end regression for the reported bug: an Ollama id with its own colon must be
    dispatched as `ollama:<full-id>`, never the bare id (which ModelRef.parse would mis-split)."""
    from agent86.tui.commands import find_command

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    repl.harness.provider.name = "ollama"  # instance attr shadows TextProvider's class attr
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._catalog_cache["ollama"] = [
            ("nemotron-3.5-lightning:latest", "nemotron-3.5-lightning:latest")
        ]
        app._run_or_chain(find_command("/model"))
        await pilot.pause()
        assert isinstance(app.screen, ModelPickerModal)
        values = [value for _, value in app.screen._choices]
        assert "ollama:nemotron-3.5-lightning:latest" in values
        assert "nemotron-3.5-lightning:latest" not in values


async def test_model_picker_fetches_then_opens(monkeypatch, tmp_path):
    import agent86.cognitive.catalog as catalog
    from agent86.tui.commands import find_command

    def fake_fetch_catalog(provider, pconf, api_key):
        return [("gpt-4o", "gpt-4o")]

    monkeypatch.setattr(catalog, "fetch_catalog", fake_fetch_catalog)

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._run_or_chain(find_command("/model"))
        await _wait_until(lambda: isinstance(app.screen, ModelPickerModal))
        assert isinstance(app.screen, ModelPickerModal)


async def test_model_picker_opens_with_roles_when_catalog_fails(monkeypatch, tmp_path):
    import agent86.cognitive.catalog as catalog
    from agent86.tui.commands import find_command

    def fake_fetch_catalog(provider, pconf, api_key):
        raise catalog.CatalogUnavailable("nope")

    monkeypatch.setattr(catalog, "fetch_catalog", fake_fetch_catalog)

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._run_or_chain(find_command("/model"))
        await _wait_until(lambda: isinstance(app.screen, ModelPickerModal))
        assert isinstance(app.screen, ModelPickerModal)


async def test_shift_tab_cycles_approval_mode(tmp_path):
    """Regression for the shift+tab binding-interception footgun (260720-1rs).

    Textual's `App` ships a default `shift+tab` binding for focus traversal
    (`focus_previous`). Without `priority=True` on the app's `cycle_mode` binding, that default
    wins whenever the prompt `Input` is focused and `action_cycle_mode` never fires. This test
    presses the real key via `pilot.press` — calling `action_cycle_mode()` directly would not
    catch this regression, since that path always worked.
    """
    repl = _make_repl(tmp_path, make_text_provider("hello world"), approval=ApprovalMode.ASK)
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#prompt", Input).has_focus
        assert repl.harness.gate.mode.value == "ask"

        await pilot.press("shift+tab")
        await pilot.pause()
        assert repl.harness.gate.mode.value == "auto"

        await pilot.press("shift+tab")
        await pilot.pause()
        assert repl.harness.gate.mode.value == "deny"


# ---- 260813-atc: typed /model bare-ref catalog-validated fallback ----------- #


async def _dispatch_typed(pilot, app, line: str) -> None:
    prompt = app.query_one("#prompt", Input)
    prompt.value = line
    await pilot.press("enter")
    await pilot.pause()


def _transcript_lines(app) -> str:
    transcript = app.query_one("#transcript", RichLog)
    return "\n".join(str(line) for line in transcript.lines)


async def test_typed_bare_ref_warm_cache_hit_switches_and_echoes(tmp_path):
    """Case 1: a warm-cache catalog hit retries the typed bare ref and echoes the resolution."""
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    repl.harness.provider.name = "ollama"  # instance attr shadows TextProvider's class attr
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._catalog_cache["ollama"] = [
            ("nemotron-3.5-lightning:latest", "nemotron-3.5-lightning:latest")
        ]
        await _dispatch_typed(pilot, app, "/model nemotron-3.5-lightning:latest")

        assert repl.harness.provider.name == "ollama"
        assert repl.harness.provider.model == "nemotron-3.5-lightning:latest"
        assert "resolved to ollama:nemotron-3.5-lightning:latest" in _transcript_lines(app)


async def test_typed_bare_ref_warm_cache_typo_miss_keeps_strict_error(tmp_path):
    """Case 2: a typo NOT in the catalog surfaces the strict error, byte-unchanged, no fallback."""
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    repl.harness.provider.name = "ollama"
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._catalog_cache["ollama"] = [
            ("nemotron-3.5-lightning:latest", "nemotron-3.5-lightning:latest")
        ]
        before_model = repl.harness.provider.model
        await _dispatch_typed(pilot, app, "/model nemotron-3.5-lightnin:latest")

        lines = _transcript_lines(app)
        assert "Unknown provider 'nemotron-3.5-lightnin'" in lines
        assert "resolved to" not in lines
        assert repl.harness.provider.name == "ollama"
        assert repl.harness.provider.model == before_model


async def test_typed_colon_free_ref_miss_keeps_strict_error(tmp_path):
    """Case 3: a colon-free typed ref surfaces the existing strict 'must be provider:model'
    error."""
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    repl.harness.provider.name = "ollama"
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._catalog_cache["ollama"] = [
            ("nemotron-3.5-lightning:latest", "nemotron-3.5-lightning:latest")
        ]
        before_model = repl.harness.provider.model
        await _dispatch_typed(pilot, app, "/model gpt-4o")

        lines = _transcript_lines(app)
        assert "must be 'provider:model'" in lines
        assert "resolved to" not in lines
        assert repl.harness.provider.model == before_model


async def test_typed_valid_ref_switches_without_consulting_catalog(monkeypatch, tmp_path):
    """Case 4: an already-valid ref switches on the strict path and never touches the catalog."""
    import agent86.cognitive.catalog as catalog

    def fail_fetch(*_a, **_k):
        raise AssertionError("fetch_catalog must not be called for an already-valid ref")

    monkeypatch.setattr(catalog, "fetch_catalog", fail_fetch)

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    repl.harness.provider.name = "ollama"
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._catalog_cache == {}
        await _dispatch_typed(pilot, app, "/model ollama:llama3.1")

        assert repl.harness.provider.name == "ollama"
        assert repl.harness.provider.model == "llama3.1"
        assert "resolved to" not in _transcript_lines(app)
        assert app._catalog_cache == {}


async def test_typed_known_provider_failure_skips_catalog_fetch(monkeypatch, tmp_path):
    """Case 5 (checker warning 1): a known-provider build/auth failure must not fetch the
    unrelated active provider's catalog."""
    import agent86.cognitive.base as base
    import agent86.cognitive.catalog as catalog

    def fail_fetch(*_a, **_k):
        raise AssertionError("fetch_catalog must not be called for a known-provider failure")

    monkeypatch.setattr(catalog, "fetch_catalog", fail_fetch)

    def fake_provider_for_model(model, config):
        raise base.ProviderError("No Anthropic API key found ...")

    monkeypatch.setattr(base, "provider_for_model", fake_provider_for_model)

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    repl.harness.provider.name = "ollama"
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._catalog_cache == {}
        await _dispatch_typed(pilot, app, "/model anthropic:claude-opus-4-8")

        lines = _transcript_lines(app)
        assert "No Anthropic API key found" in lines
        assert "resolved to" not in lines
        assert "fetching" not in lines
        assert app._pending_model == []


async def test_typed_bare_ref_cold_cache_resolves_after_catalog_ready(monkeypatch, tmp_path):
    """Case 6: a cold catalog completes the resolution asynchronously without blocking the UI."""
    import agent86.cognitive.catalog as catalog

    def fake_fetch_catalog(provider, pconf, api_key):
        return [("nemotron-3.5-lightning:latest", "nemotron-3.5-lightning:latest")]

    monkeypatch.setattr(catalog, "fetch_catalog", fake_fetch_catalog)

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    repl.harness.provider.name = "ollama"
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._catalog_cache == {}
        await _dispatch_typed(pilot, app, "/model nemotron-3.5-lightning:latest")

        await _wait_until(lambda: repl.harness.provider.model == "nemotron-3.5-lightning:latest")
        await pilot.pause()

        assert "resolved to ollama:nemotron-3.5-lightning:latest" in _transcript_lines(app)
        assert app._pending_model == []
        assert app._model_fetch_inflight == set()


async def test_typed_bare_ref_cold_cache_fetch_fails_falls_through(monkeypatch, tmp_path):
    """Case 7: a failed cold-cache fetch falls through to the strict error, never a silent
    retry or drop."""
    import agent86.cognitive.catalog as catalog

    def fake_fetch_catalog(provider, pconf, api_key):
        raise catalog.CatalogUnavailable("nope")

    monkeypatch.setattr(catalog, "fetch_catalog", fake_fetch_catalog)

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    repl.harness.provider.name = "ollama"
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        before_model = repl.harness.provider.model
        await _dispatch_typed(pilot, app, "/model nemotron-3.5-lightning:latest")

        await _wait_until(
            lambda: app._pending_model == [] and app._model_fetch_inflight == set()
        )
        await pilot.pause()

        lines = _transcript_lines(app)
        assert "Unknown provider 'nemotron-3.5-lightning'" in lines
        assert "resolved to" not in lines
        assert repl.harness.provider.model == before_model


async def test_overlapping_dispatches_same_provider_each_get_one_outcome(monkeypatch, tmp_path):
    """Case 8 (checker warning 2): two /model dispatches inside one cold-cache fetch window
    for the SAME provider must each produce exactly one outcome, with exactly one fetch."""
    import agent86.cognitive.catalog as catalog

    release = threading.Event()
    calls = {"n": 0}

    def fake_fetch_catalog(provider, pconf, api_key):
        calls["n"] += 1
        # Hard timeout: a routing bug that never releases must fail the suite, not hang it.
        if not release.wait(timeout=5.0):
            raise AssertionError("fake_fetch_catalog: release never set (deadlock?)")
        return [("nemotron-3.5-lightning:latest", "nemotron-3.5-lightning:latest")]

    monkeypatch.setattr(catalog, "fetch_catalog", fake_fetch_catalog)

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    repl.harness.provider.name = "ollama"
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _dispatch_typed(pilot, app, "/model nemotron-3.5-lightning:latest")
        await _dispatch_typed(pilot, app, "/model nemotron-3.5-lightnin:latest")

        await _wait_until(lambda: len(app._pending_model) == 2)
        assert len(app._pending_model) == 2

        release.set()
        await _wait_until(lambda: app._pending_model == [])
        await pilot.pause()

        lines = _transcript_lines(app)
        assert "resolved to ollama:nemotron-3.5-lightning:latest" in lines
        assert "Unknown provider 'nemotron-3.5-lightnin'" in lines
        assert calls["n"] == 1
        assert app._model_fetch_inflight == set()


async def test_cross_provider_stranding_validates_against_own_captured_provider(
    monkeypatch, tmp_path
):
    """Case 9 (checker warning 3): the exact sequence from the plan's <decisions> — an entry
    queued under provider A must never be validated against provider B's catalog, even when an
    intervening successful /model switch changed the active provider mid-flight."""
    import agent86.cognitive.base as base
    import agent86.cognitive.catalog as catalog

    ollama_release = threading.Event()
    fetch_calls: list[str] = []

    def fake_fetch_catalog(provider, pconf, api_key):
        fetch_calls.append(provider)
        if provider == "ollama":
            # Hard timeout: a routing bug that never releases must fail, not hang, the suite.
            if not ollama_release.wait(timeout=5.0):
                raise AssertionError("fake_fetch_catalog: ollama release never set (deadlock?)")
            return [("nemotron-3.5-lightning:latest", "nemotron-3.5-lightning:latest")]
        if provider == "anthropic":
            return [("gpt-4o", "gpt-4o")]  # answered immediately -- proves no piggybacking
        return []

    monkeypatch.setattr(catalog, "fetch_catalog", fake_fetch_catalog)

    class _StubAnthropicProvider:
        name = "anthropic"

        def __init__(self, model: str) -> None:
            self.model = model

    real_provider_for_model = base.provider_for_model

    def fake_provider_for_model(model, config):
        if model.startswith("anthropic:"):
            return _StubAnthropicProvider(model.split(":", 1)[1])
        return real_provider_for_model(model, config)

    monkeypatch.setattr(base, "provider_for_model", fake_provider_for_model)

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    repl.harness.provider.name = "ollama"
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()

        # 1. /model nemotron-3.5-lightning:latest -- queued under ollama, ollama fetch blocks.
        await _dispatch_typed(pilot, app, "/model nemotron-3.5-lightning:latest")
        await _wait_until(lambda: "ollama" in app._model_fetch_inflight)

        # 2. /model anthropic:claude-opus-4-8 -- succeeds strictly; active provider is now
        #    anthropic. This returns early and never touches the queue.
        await _dispatch_typed(pilot, app, "/model anthropic:claude-opus-4-8")
        assert repl.harness.provider.name == "anthropic"

        # 3. /model gpt-4o -- fails, candidate, anthropic cold -> queued under anthropic.
        await _dispatch_typed(pilot, app, "/model gpt-4o")

        await _wait_until(lambda: "resolved to anthropic:gpt-4o" in _transcript_lines(app))

        # gpt-4o was answered against ANTHROPIC's catalog, never ollama's -- proven both by the
        # positive resolution above and by this negative assertion while ollama is still blocked.
        assert "resolved to ollama:gpt-4o" not in _transcript_lines(app)
        assert sorted(fetch_calls) == ["anthropic", "ollama"]
        # The ollama entry is still stranded, waiting on its own (still-blocked) fetch.
        assert len(app._pending_model) == 1
        assert app._pending_model[0][2] == "ollama"

        ollama_release.set()
        await _wait_until(lambda: app._pending_model == [])
        await pilot.pause()

        assert "resolved to ollama:nemotron-3.5-lightning:latest" in _transcript_lines(app)
        assert app._pending_model == []
        assert app._model_fetch_inflight == set()


async def test_typed_colon_free_ref_cold_cache_miss_falls_through(monkeypatch, tmp_path):
    """Case 10: a cold-cache fetch that does not vouch for a colon-free typed ref falls through
    to the strict 'must be provider:model' error exactly once."""
    import agent86.cognitive.catalog as catalog

    def fake_fetch_catalog(provider, pconf, api_key):
        return [("nemotron-3.5-lightning:latest", "nemotron-3.5-lightning:latest")]

    monkeypatch.setattr(catalog, "fetch_catalog", fake_fetch_catalog)

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    repl.harness.provider.name = "ollama"
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        before_model = repl.harness.provider.model
        await _dispatch_typed(pilot, app, "/model gpt-4o")

        await _wait_until(
            lambda: app._pending_model == [] and app._model_fetch_inflight == set()
        )
        await pilot.pause()

        lines = _transcript_lines(app)
        assert "must be 'provider:model'" in lines
        assert "resolved to" not in lines
        assert repl.harness.provider.model == before_model
