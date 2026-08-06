"""The `/config mcp` surface: list/add/edit/remove/enable MCP servers (MCP-01).

The row layer (`mcp_server_rows`) is pure config facts only — D-08: opening the manager must
never spawn a subprocess or open a transport. Live connectivity is what an explicit "test" action
is for, not something that happens just because the manager was opened.

All validation is delegated to `MCPServerConfig`'s own `model_validator` — this module never
re-derives or re-words a validation rule. Its message is caught and surfaced verbatim, inline
under the form (D-05), mirroring `SaveDiffModal`'s error-renders-and-disables-confirm pattern.
"""

from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass

from pydantic import ValidationError
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    OptionList,
    RadioButton,
    RadioSet,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option

from agent86.config import Config, MCPServerConfig

ADD_JSON_ID = "__add_json__"
ADD_MANUAL_ID = "__add_manual__"


def _first_validator_message(exc: ValidationError) -> str:
    """Pull the validator's own message out of pydantic's wrapper, verbatim (D-05)."""
    msg = exc.errors()[0]["msg"]
    prefix = "Value error, "
    if msg.startswith(prefix):
        msg = msg[len(prefix) :]
    return msg


@dataclass(frozen=True)
class MCPServerRow:
    """One row of the MCP server list — static config facts only (D-08)."""

    name: str
    transport: str
    endpoint: str
    enabled: bool

    @property
    def status(self) -> str:
        return "enabled" if self.enabled else "disabled"


def mcp_server_rows(cfg: Config) -> list[MCPServerRow]:
    """Describe every configured MCP server, in config order. Never connects to anything.

    ``endpoint`` matches the `agent86 mcp list` table exactly so the two surfaces cannot drift.
    """
    return [
        MCPServerRow(
            name=name,
            transport=srv.transport or "?",
            endpoint=srv.url or " ".join([srv.command or "", *srv.args]).strip(),
            enabled=srv.enabled,
        )
        for name, srv in cfg.mcp_servers.items()
    ]


@dataclass(frozen=True)
class MCPManagerAction:
    """What the user chose in the manager list. ``name`` is None for the two add paths."""

    kind: str  # "add_json" | "add_manual" | "edit" | "remove" | "toggle"
    name: str | None = None


@dataclass(frozen=True)
class MCPServerDraft:
    """A validated, not-yet-saved server. ``original_name`` is set when editing (D-07)."""

    name: str
    cfg: MCPServerConfig
    original_name: str | None = None


def parse_kv_list(text: str) -> dict[str, str]:
    """Parse "KEY=value, OTHER=${VAR}" into a dict. Empty text is an empty dict.

    Values may contain '=' (only the first is a separator) and are kept verbatim so a ${VAR}
    reference survives to config unresolved (D-17).
    """
    text = text.strip()
    if not text:
        return {}
    result: dict[str, str] = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"Expected KEY=value, got: {part!r}")
        key, _, value = part.partition("=")
        key = key.strip()
        if not key:
            raise ValueError(f"Expected KEY=value, got: {part!r}")
        result[key] = value.strip()
    return result


def _server_config_from_dict(data: dict) -> MCPServerConfig:
    """Build an MCPServerConfig from a raw dict, mapping README-shaped aliases.

    Unknown keys are dropped rather than raising, except "type" (mapped onto ``transport`` when
    it's one of stdio/sse/http) and "enabled"/"disabled" (mapped onto ``enabled``).
    """
    known_fields = {"command", "args", "env", "url", "headers", "transport", "enabled"}
    cleaned: dict = {}
    for key, value in data.items():
        if key in known_fields:
            cleaned[key] = value
        elif key == "type" and isinstance(value, str) and value.lower() in (
            "stdio",
            "sse",
            "http",
        ):
            cleaned["transport"] = value.lower()
        elif key == "disabled":
            cleaned["enabled"] = not bool(value)
    try:
        return MCPServerConfig(**cleaned)
    except ValidationError as exc:
        raise ValueError(_first_validator_message(exc)) from None


def parse_server_json(raw: str, name_hint: str = "") -> tuple[str, MCPServerConfig]:
    """Accept BOTH README JSON shapes (D-02) and return (name, validated config).

    - bare server object: ``{"command": "npx", "args": [...]}`` -> name comes from ``name_hint``
    - wrapped: ``{"mcpServers": {"github": {...}}}`` -> the wrapped key supplies the name and
      WINS over ``name_hint``; exactly one entry is required, more raises ValueError
    Also accepts the ``"servers"`` key as an alias for ``"mcpServers"`` (VS Code's spelling).
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Not valid JSON: {exc.msg} (line {exc.lineno} col {exc.colno})") from None

    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object.")

    wrapper_key = "mcpServers" if "mcpServers" in data else ("servers" if "servers" in data else None)
    if wrapper_key is not None:
        servers = data[wrapper_key]
        if not isinstance(servers, dict) or len(servers) != 1:
            raise ValueError(f'Expected exactly one server under "{wrapper_key}".')
        (name, server_obj), = servers.items()
        cfg = _server_config_from_dict(server_obj)
        return name, cfg

    if not name_hint:
        raise ValueError("Enter a name for this server.")
    cfg = _server_config_from_dict(data)
    return name_hint, cfg


def build_manual_config(
    command_line: str,
    url: str,
    env_text: str,
    headers_text: str,
    transport: str | None,
) -> MCPServerConfig:
    """Build a config from the manual form's five fields (D-03/D-06).

    ``command_line`` is split with shlex — a single shell-ish line is how commands are copied
    from a README, not a repeating arg-row widget. The first token is ``command``, the rest are
    ``args``. ``transport`` is only honoured when ``url`` is set (D-06: http/sse are
    indistinguishable from a URL alone); when ``command_line`` is set it is left None so the
    config validator infers "stdio".
    """
    command_line = command_line.strip()
    url = url.strip()
    env = parse_kv_list(env_text)
    headers = parse_kv_list(headers_text)

    command: str | None = None
    args: list[str] = []
    if command_line:
        tokens = shlex.split(command_line, posix=(os.name != "nt"))
        if tokens:
            command = tokens[0]
            args = tokens[1:]

    effective_transport = transport if url else None

    try:
        return MCPServerConfig(
            command=command,
            args=args,
            env=env,
            url=url or None,
            headers=headers,
            transport=effective_transport,
        )
    except ValidationError as exc:
        raise ValueError(_first_validator_message(exc)) from None


class MCPManagerModal(ModalScreen[MCPManagerAction | None]):
    """List configured MCP servers and pick an action. Dismisses with MCPManagerAction or None.

    D-08: this modal renders static config facts only — it never spawns a subprocess or opens a
    transport, so opening it is instant. Live status is what the explicit test action is for.
    D-01: "Add from JSON" and "Add manually" are two peer entries, neither a fallback.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("d", "remove", "Remove"),
        ("t", "toggle", "Enable/disable"),
    ]

    def __init__(self, rows: list[MCPServerRow]) -> None:
        super().__init__()
        self._rows = {row.name: row for row in rows}
        self._order = [row.name for row in rows]

    def compose(self) -> ComposeResult:
        with Container(id="mcp-manager-dialog"):
            yield Label("MCP servers — enter to edit, d to remove, t to enable/disable")
            if not self._order:
                yield Label("No MCP servers configured yet.", id="mcp-empty")
            options = [Option(self._label(self._rows[name]), id=name) for name in self._order]
            options.append(Option("+ Add from JSON (paste a server block)", id=ADD_JSON_ID))
            options.append(Option("+ Add manually (name, command or URL)", id=ADD_MANUAL_ID))
            yield OptionList(*options, id="mcp-server-list")

    @staticmethod
    def _label(row: MCPServerRow) -> str:
        return f"{row.name}  [dim]{row.transport}[/dim]  {row.endpoint}  ({row.status})"

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if option_id == ADD_JSON_ID:
            self.dismiss(MCPManagerAction("add_json"))
        elif option_id == ADD_MANUAL_ID:
            self.dismiss(MCPManagerAction("add_manual"))
        else:
            self.dismiss(MCPManagerAction("edit", option_id))

    def _highlighted_server_name(self) -> str | None:
        option_list = self.query_one("#mcp-server-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        option = option_list.get_option_at_index(highlighted)
        option_id = option.id
        if option_id in (ADD_JSON_ID, ADD_MANUAL_ID, None):
            return None
        return option_id

    def action_remove(self) -> None:
        name = self._highlighted_server_name()
        if name is None:
            return
        self.dismiss(MCPManagerAction("remove", name))

    def action_toggle(self) -> None:
        name = self._highlighted_server_name()
        if name is None:
            return
        self.dismiss(MCPManagerAction("toggle", name))

    def action_cancel(self) -> None:
        self.dismiss(None)


class MCPServerFormModal(ModalScreen[MCPServerDraft | None]):
    """Add or edit one MCP server. Dismisses with a validated MCPServerDraft, or None.

    One form serves both add paths and the edit path (D-01/D-07). Validation is delegated to
    `MCPServerConfig`'s own validator and rendered inline under the fields — Continue stays
    disabled until the whole object parses, and nothing the user typed is ever discarded (D-05),
    mirroring `SaveDiffModal`'s error-renders-and-disables-confirm behaviour.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        mode: str = "json",  # "json" | "manual"
        existing_names: set[str] | None = None,
        draft: MCPServerDraft | None = None,
    ) -> None:
        super().__init__()
        self._mode = mode
        self._existing = existing_names or set()
        self._original = draft.original_name if draft else None
        self._draft = draft
        self._current: MCPServerDraft | None = None

    def compose(self) -> ComposeResult:
        title = {
            "json": "Add MCP server — paste JSON",
            "manual": "Add MCP server — enter fields",
        }.get(self._mode, "Add MCP server")
        if self._draft is not None:
            title = "Edit MCP server"

        with Container(id="mcp-form-dialog"):
            yield Label(title)
            yield Input(id="mcp-name", placeholder="server name (required)")
            if self._mode == "json":
                yield TextArea(id="mcp-json")
            else:
                yield Input(id="mcp-command", placeholder="command (e.g. npx -y server-name)")
                yield Input(id="mcp-url", placeholder="url (for sse/http transports)")
                yield Input(id="mcp-env", placeholder="env: KEY=value, OTHER=${VAR}")
                yield Input(id="mcp-headers", placeholder="headers: KEY=value")
                with RadioSet(id="mcp-transport"):
                    yield RadioButton("http", value=True, id="transport-http")
                    yield RadioButton("sse", id="transport-sse")
            yield Static("", id="mcp-form-error")
            with Horizontal(id="mcp-form-buttons"):
                yield Button("Continue", id="mcp-form-continue", variant="primary")
                yield Button("Cancel", id="mcp-form-cancel")

    def on_mount(self) -> None:
        if self._draft is not None:
            self.query_one("#mcp-name", Input).value = self._draft.name
            cfg = self._draft.cfg
            if self._mode == "manual":
                self.query_one("#mcp-command", Input).value = " ".join(
                    [cfg.command or "", *cfg.args]
                ).strip()
                self.query_one("#mcp-url", Input).value = cfg.url or ""
                self.query_one("#mcp-env", Input).value = ", ".join(
                    f"{k}={v}" for k, v in cfg.env.items()
                )
                self.query_one("#mcp-headers", Input).value = ", ".join(
                    f"{k}={v}" for k, v in cfg.headers.items()
                )
                transport_widget = self.query_one("#mcp-transport", RadioSet)
                transport_widget.display = bool(cfg.url)
                if cfg.transport == "sse":
                    self.query_one("#transport-sse", RadioButton).value = True
                    self.query_one("#transport-http", RadioButton).value = False
            else:
                server_obj = {
                    "command": cfg.command,
                    "args": cfg.args,
                    "env": cfg.env,
                    "url": cfg.url,
                    "headers": cfg.headers,
                    "transport": cfg.transport,
                    "enabled": cfg.enabled,
                }
                server_obj = {k: v for k, v in server_obj.items() if v not in (None, [], {})}
                self.query_one("#mcp-json", TextArea).text = json.dumps(server_obj, indent=2)
        elif self._mode == "manual":
            self.query_one("#mcp-transport", RadioSet).display = False

        self.query_one("#mcp-name", Input).focus()
        self._revalidate()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "mcp-url":
            self.query_one("#mcp-transport", RadioSet).display = bool(event.value.strip())
        self._revalidate()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._revalidate()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        self._revalidate()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._revalidate()
        if self._current is not None:
            self.dismiss(self._current)

    def _revalidate(self) -> None:
        error_widget = self.query_one("#mcp-form-error", Static)
        confirm = self.query_one("#mcp-form-continue", Button)
        try:
            self._current = self._build_draft()
        except ValueError as exc:
            self._current = None
            confirm.disabled = True
            error_widget.update(str(exc))
            return
        confirm.disabled = False
        error_widget.update("")

    def _build_draft(self) -> MCPServerDraft:
        name = self.query_one("#mcp-name", Input).value.strip()
        if not name:
            raise ValueError("Enter a name for this server.")
        if name in self._existing and name != self._original:
            raise ValueError(f"A server named '{name}' already exists. Pick another name.")

        if self._mode == "json":
            raw = self.query_one("#mcp-json", TextArea).text
            result_name, cfg = parse_server_json(raw, name_hint=name)
            if result_name in self._existing and result_name != self._original:
                raise ValueError(
                    f"A server named '{result_name}' already exists. Pick another name."
                )
            return MCPServerDraft(name=result_name, cfg=cfg, original_name=self._original)

        command_line = self.query_one("#mcp-command", Input).value
        url = self.query_one("#mcp-url", Input).value
        env_text = self.query_one("#mcp-env", Input).value
        headers_text = self.query_one("#mcp-headers", Input).value
        transport_widget = self.query_one("#mcp-transport", RadioSet)
        transport: str | None = None
        if transport_widget.display:
            sse_button = self.query_one("#transport-sse", RadioButton)
            transport = "sse" if sse_button.value else "http"
        cfg = build_manual_config(command_line, url, env_text, headers_text, transport)
        return MCPServerDraft(name=name, cfg=cfg, original_name=self._original)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "mcp-form-continue" and self._current is not None:
            self.dismiss(self._current)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = [
    "MCPServerRow",
    "mcp_server_rows",
    "MCPManagerAction",
    "MCPServerDraft",
    "parse_kv_list",
    "parse_server_json",
    "build_manual_config",
    "ADD_JSON_ID",
    "ADD_MANUAL_ID",
    "MCPManagerModal",
    "MCPServerFormModal",
]
