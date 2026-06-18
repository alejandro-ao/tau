"""Minimal Textual app for Tau coding sessions."""

from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, ClassVar, Literal, Protocol, cast

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingsMap
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Key, Resize
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static
from textual.worker import Worker

from tau_agent.messages import AgentMessage
from tau_agent.tools import AgentTool
from tau_ai import ProviderErrorEvent, ProviderEvent
from tau_ai.provider import CancellationToken
from tau_coding.commands import CommandRegistry, create_default_command_registry
from tau_coding.credentials import FileCredentialStore
from tau_coding.provider_catalog import ProviderCatalogEntry, builtin_provider_entry
from tau_coding.provider_config import (
    load_provider_settings,
    provider_config_from_catalog_entry,
    resolve_provider_selection,
    save_provider_settings,
    upsert_provider,
)
from tau_coding.provider_runtime import create_model_provider
from tau_coding.session import CodingSession, CodingSessionConfig, jsonl_session_storage
from tau_coding.session_manager import SessionManager
from tau_coding.tui.adapter import TuiEventAdapter
from tau_coding.tui.autocomplete import CompletionOption, CompletionState, build_completion_state
from tau_coding.tui.config import TuiKeybindings, TuiSettings, TuiTheme, load_tui_settings
from tau_coding.tui.state import TuiState
from tau_coding.tui.widgets import (
    CompactSessionInfo,
    SessionSidebar,
    TranscriptView,
    render_completion_suggestions,
)

type BindingEntry = Binding | tuple[str, str] | tuple[str, str, str]
SIDEBAR_MIN_WIDTH = 96
SIDEBAR_MIN_HEIGHT = 24


class LoginRequiredProvider:
    """Placeholder provider used so the TUI can open before login."""

    def __init__(self, message: str) -> None:
        self.message = message

    async def aclose(self) -> None:
        """Close provider resources."""

    def stream_response(
        self,
        *,
        model: str,
        system: str,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        signal: CancellationToken | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        """Surface a login-needed provider error."""
        del model, system, messages, tools, signal

        async def iterator() -> AsyncIterator[ProviderEvent]:
            yield ProviderErrorEvent(message=self.message)

        return iterator()


class CompletionActionTarget(Protocol):
    """App actions used by the prompt input completion bindings."""

    def action_accept_completion(self) -> None: ...

    def action_completion_next(self) -> None: ...

    def action_completion_previous(self) -> None: ...

    def action_open_command_palette(self) -> None: ...

    def action_open_session_picker(self) -> None: ...


class SessionCompletionRecord(Protocol):
    """Session metadata needed to render resume picker completions."""

    id: str
    title: str | None
    model: str
    cwd: Path


class PromptInput(Input):
    """Prompt input with completion key bindings."""

    BINDINGS: ClassVar[list[BindingEntry]] = []

    def __init__(
        self,
        *,
        tui_keybindings: TuiKeybindings | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.tui_keybindings = tui_keybindings or TuiKeybindings()
        self._bindings = BindingsMap.merge(
            [self._bindings, BindingsMap(_prompt_bindings(self.tui_keybindings))]
        )

    def action_accept_completion(self) -> None:
        """Accept the selected app-level completion."""
        self._completion_target().action_accept_completion()

    def action_completion_next(self) -> None:
        """Select the next app-level completion."""
        self._completion_target().action_completion_next()

    def action_completion_previous(self) -> None:
        """Select the previous app-level completion."""
        self._completion_target().action_completion_previous()

    def action_open_command_palette(self) -> None:
        """Open the app-level command palette."""
        self._completion_target().action_open_command_palette()

    def action_open_session_picker(self) -> None:
        """Open the app-level session picker."""
        self._completion_target().action_open_session_picker()

    async def action_quit(self) -> None:
        """Quit the app through the app-level action."""
        await self.app.action_quit()

    def action_scroll_down(self) -> None:
        """Use down arrow for completion selection while focused."""
        self._completion_target().action_completion_next()

    def action_scroll_up(self) -> None:
        """Use up arrow for completion selection while focused."""
        self._completion_target().action_completion_previous()

    async def on_key(self, event: Key) -> None:
        """Route completion keys before default input handling."""
        keybindings = self.tui_keybindings
        if event.key == keybindings.accept_completion:
            event.stop()
            self._completion_target().action_accept_completion()
        elif event.key == keybindings.command_palette:
            event.stop()
            self._completion_target().action_open_command_palette()
        elif event.key == keybindings.session_picker:
            event.stop()
            self._completion_target().action_open_session_picker()
        elif event.key == keybindings.completion_next:
            event.stop()
            self._completion_target().action_completion_next()
        elif event.key == keybindings.completion_previous:
            event.stop()
            self._completion_target().action_completion_previous()
        elif event.key == keybindings.quit:
            event.stop()
            await self.action_quit()

    def _completion_target(self) -> CompletionActionTarget:
        return cast(CompletionActionTarget, self.app)


class SessionPickerScreen(ModalScreen[str | None]):
    """Minimal modal picker for indexed sessions."""

    BINDINGS: ClassVar[list[BindingEntry]] = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        records: Sequence[SessionCompletionRecord],
        *,
        theme: TuiTheme,
    ) -> None:
        super().__init__()
        self.records = tuple(records)
        self.theme = theme

    def compose(self) -> ComposeResult:
        """Compose the session picker."""
        with Vertical(id="session-picker"):
            yield Static("Sessions", id="session-picker-title")
            yield ListView(
                *[
                    ListItem(Label(_session_picker_label(record), markup=False))
                    for record in self.records
                ],
                id="session-picker-list",
            )
            yield Static("Enter resumes - Escape closes", id="session-picker-help")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Dismiss with the selected session id."""
        self.dismiss(self.records[event.index].id)

    def action_cancel(self) -> None:
        """Close the picker without selecting a session."""
        self.dismiss(None)


class CommandOutputScreen(ModalScreen[None]):
    """Dismissible modal for slash-command output."""

    BINDINGS: ClassVar[list[BindingEntry]] = [
        Binding("escape", "close", "Close"),
        Binding("enter", "close", "Close"),
    ]

    def __init__(self, title: str, message: str, *, theme: TuiTheme) -> None:
        super().__init__()
        self.title_text = title
        self.message = message
        self.theme = theme

    def compose(self) -> ComposeResult:
        """Compose command output."""
        with Vertical(id="command-output"):
            yield Static(self.title_text, id="command-output-title")
            with VerticalScroll(id="command-output-scroll"):
                yield Static(self.message, id="command-output-body", markup=False)
            yield Static("Enter or Escape closes", id="command-output-help")

    def action_close(self) -> None:
        """Close the command output modal."""
        self.dismiss(None)


class LoginScreen(ModalScreen[str | None]):
    """Password prompt for saving a provider API key."""

    BINDINGS: ClassVar[list[BindingEntry]] = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, provider: ProviderCatalogEntry, *, theme: TuiTheme) -> None:
        super().__init__()
        self.provider = provider
        self.theme = theme

    def compose(self) -> ComposeResult:
        """Compose the provider login prompt."""
        with Vertical(id="login-screen"):
            yield Static(f"Login: {self.provider.display_name}", id="login-title")
            yield Static(self.provider.api_key_env, id="login-help")
            yield Input(placeholder="Paste API key", password=True, id="login-api-key")
            yield Static("Enter saves - Escape closes", id="login-footer")

    def on_mount(self) -> None:
        """Focus the API key field."""
        self.query_one("#login-api-key", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Dismiss with the submitted API key."""
        if event.input.id != "login-api-key":
            return
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        """Close without saving."""
        self.dismiss(None)


class TauTuiApp(App[None]):
    """Interactive Textual frontend for a ``CodingSession``."""

    TITLE = "Tau"
    CSS = """
    Screen {
        layout: vertical;
        background: $tau-screen-background;
        color: $tau-screen-text;
    }

    Header {
        background: $tau-chrome-background;
        color: $tau-muted-text;
        dock: top;
    }

    Footer {
        background: $tau-chrome-background;
        color: $tau-muted-text;
    }

    #status {
        height: 1;
        padding: 0 1;
        background: $tau-screen-background;
        color: $tau-muted-text;
    }

    #workspace {
        height: 1fr;
    }

    #sidebar {
        width: 32;
        min-width: 28;
        height: 1fr;
        padding: 1 1 0 0;
        background: $tau-sidebar-background;
        border-right: tall $tau-border;
    }

    TauTuiApp.-hide-sidebar #sidebar {
        display: none;
    }

    TauTuiApp.-hide-sidebar #main-pane {
        padding-left: 1;
    }

    #main-pane {
        width: 1fr;
        padding: 1 1 0 1;
    }

    #transcript {
        height: 1fr;
        border: none;
        background: $tau-transcript-background;
        padding: 0 1 0 0;
    }

    #prompt {
        background: $tau-prompt-background;
        color: $tau-prompt-text;
        border: tall transparent;
        margin: 0 1 1 1;
        padding: 0 1;
    }

    #prompt:focus {
        border: tall $tau-prompt-border;
    }

    #compact-session-info {
        display: none;
        height: auto;
        max-height: 3;
        margin: 0 1 1 1;
        padding: 0 1;
        color: $tau-muted-text;
    }

    TauTuiApp.-hide-sidebar #compact-session-info {
        display: block;
    }

    #autocomplete {
        height: auto;
        max-height: 18;
        margin: 0 1 1 1;
        padding: 0 1;
        background: $tau-autocomplete-background;
        color: $tau-screen-text;
        border: tall $tau-border;
    }

    SessionPickerScreen {
        align: center middle;
    }

    #session-picker {
        width: 76;
        max-width: 90%;
        height: auto;
        max-height: 70%;
        padding: 1 2;
        background: $tau-chrome-background;
        border: tall $tau-border;
    }

    #session-picker-title {
        height: 1;
        color: $tau-chrome-text;
        text-style: bold;
        margin-bottom: 1;
    }

    #session-picker-list {
        height: auto;
        max-height: 16;
        background: $tau-transcript-background;
        border: tall $tau-border;
    }

    #session-picker-help {
        height: 1;
        margin-top: 1;
        color: $tau-muted-text;
    }

    #command-output {
        width: 82;
        max-width: 92%;
        height: 70%;
        max-height: 80%;
        padding: 1 2;
        background: $tau-chrome-background;
        border: tall $tau-border;
    }

    #command-output-title {
        height: 1;
        color: $tau-chrome-text;
        text-style: bold;
        margin-bottom: 1;
    }

    #command-output-scroll {
        height: 1fr;
        background: $tau-transcript-background;
        border: tall $tau-border;
    }

    #command-output-body {
        color: $tau-screen-text;
        padding: 1;
    }

    #command-output-help {
        height: 1;
        margin-top: 1;
        color: $tau-muted-text;
    }

    LoginScreen {
        align: center middle;
    }

    #login-screen {
        width: 72;
        max-width: 92%;
        height: auto;
        padding: 1 2;
        background: $tau-chrome-background;
        border: tall $tau-border;
    }

    #login-title {
        height: 1;
        color: $tau-chrome-text;
        text-style: bold;
        margin-bottom: 1;
    }

    #login-help {
        height: 1;
        color: $tau-muted-text;
        margin-bottom: 1;
    }

    #login-api-key {
        background: $tau-prompt-background;
        color: $tau-prompt-text;
        border: tall $tau-prompt-border;
        margin-bottom: 1;
    }

    #login-footer {
        height: 1;
        color: $tau-muted-text;
    }
    """
    BINDINGS: ClassVar[list[BindingEntry]] = []

    def __init__(
        self,
        session: CodingSession,
        *,
        tui_settings: TuiSettings | None = None,
        startup_message: str | None = None,
    ) -> None:
        self.tui_settings = tui_settings or TuiSettings()
        self.startup_message = startup_message
        super().__init__()
        self._bindings = BindingsMap(_app_bindings(self.tui_settings.keybindings))
        self.session = session
        self.state = TuiState()
        self.state.load_messages(session.messages)
        self.adapter = TuiEventAdapter(self.state)
        self._prompt_worker: Worker[None] | None = None
        self._completion_state = CompletionState()

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """Return Tau-specific CSS variables for the selected TUI theme."""
        variables = super().get_theme_variable_defaults()
        return {**variables, **_theme_css_variables(self.tui_settings.resolved_theme)}

    def compose(self) -> ComposeResult:
        """Compose the TUI widgets."""
        yield Header()
        yield Static("Ready", id="status")
        with Horizontal(id="workspace"):
            yield SessionSidebar(id="sidebar")
            with Vertical(id="main-pane"):
                yield TranscriptView(
                    id="transcript",
                    min_width=1,
                    wrap=True,
                    highlight=True,
                    markup=False,
                )
                yield PromptInput(
                    placeholder="Ask Tau…",
                    id="prompt",
                    tui_keybindings=self.tui_settings.keybindings,
                )
                yield CompactSessionInfo(id="compact-session-info")
                yield Static("", id="autocomplete")
        yield Footer()

    async def on_mount(self) -> None:
        """Focus the prompt when the app starts."""
        self.query_one(Input).focus()
        self._update_responsive_layout(self.size.width, self.size.height)
        self._refresh()
        self._refresh_completions()
        if self.startup_message:
            self._notify(self.startup_message, severity="warning")

    def on_resize(self, event: Resize) -> None:
        """Update responsive chrome when the terminal changes size."""
        self._update_responsive_layout(event.size.width, event.size.height)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update prompt autocomplete when the input value changes."""
        if event.input.id != "prompt":
            return
        self._completion_state = self._build_completion_state(event.value)
        self._refresh_completions()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle a submitted prompt or slash command."""
        raw_text = event.value
        applied_completion = self._apply_selected_completion(raw_text)
        if applied_completion is not None and applied_completion != raw_text:
            event.input.value = applied_completion
            event.input.cursor_position = len(applied_completion)
            self._completion_state = self._build_completion_state(applied_completion)
            self._refresh_completions()
            return

        text = raw_text.strip()
        event.input.value = ""
        self._completion_state = CompletionState()
        self._refresh_completions()
        if not text:
            return

        command = self.session.handle_command(text)
        if command.handled:
            if command.clear_requested:
                self.state.clear()
            if command.compact_summary is not None:
                try:
                    compact_message = await self.session.compact(command.compact_summary)
                    self._notify(compact_message)
                except Exception as exc:  # noqa: BLE001 - surface command failures in the TUI
                    self._notify(f"Error: {exc}", severity="error")
            if command.resume_session_id is not None:
                await self._resume_session(command.resume_session_id)
            if command.login_provider is not None:
                self._open_login(command.login_provider)
            if command.message:
                self._show_command_message(text, command.message)
            self._refresh()
            if command.exit_requested:
                self.exit()
            return

        if self.state.running:
            self._notify("Tau is already working. Press Escape to cancel.")
            return

        self.state.add_item("user", text)
        self._refresh()
        self._prompt_worker = self.run_worker(self._run_prompt(text), exclusive=True)

    async def _run_prompt(self, text: str) -> None:
        """Run one prompt and stream session events into the TUI state."""
        try:
            async for event in self.session.prompt(text):
                self.adapter.apply(event)
                self._refresh()
        except Exception as exc:  # noqa: BLE001 - surface unexpected worker errors in the TUI
            self.state.error = str(exc)
            self.state.add_item("error", f"Error: {exc}")
            self.state.running = False
            self._refresh()

    def action_cancel(self) -> None:
        """Cancel the active agent turn."""
        if self.state.running:
            self.session.cancel()
            self._notify("Cancellation requested.")
        else:
            self._notify("Nothing to cancel.")

    def action_accept_completion(self) -> None:
        """Accept the currently selected prompt completion."""
        prompt = self.query_one("#prompt", Input)
        applied = self._apply_selected_completion(prompt.value)
        if applied is None:
            return
        prompt.value = applied
        prompt.cursor_position = len(prompt.value)
        self._completion_state = self._build_completion_state(prompt.value)
        self._refresh_completions()

    def action_completion_next(self) -> None:
        """Select the next prompt completion."""
        if not self._completion_state.items:
            return
        self._completion_state = self._completion_state.select_next()
        self._refresh_completions()

    def action_completion_previous(self) -> None:
        """Select the previous prompt completion."""
        if not self._completion_state.items:
            return
        self._completion_state = self._completion_state.select_previous()
        self._refresh_completions()

    def action_open_command_palette(self) -> None:
        """Open the slash-command palette in the prompt."""
        prompt = self.query_one("#prompt", Input)
        prompt.focus()
        prompt.value = "/"
        prompt.cursor_position = len(prompt.value)
        self._completion_state = self._build_completion_state(prompt.value)
        self._refresh_completions()

    def action_open_session_picker(self) -> None:
        """Open the indexed session picker."""
        if self.state.running:
            self._notify("Tau is already working. Press Escape to cancel.")
            return
        records = _session_records(self.session)
        if not records:
            self._notify("No sessions found.")
            return
        self.push_screen(
            SessionPickerScreen(records, theme=self.tui_settings.resolved_theme),
            callback=self._handle_session_picker_result,
        )

    def _handle_session_picker_result(self, session_id: str | None) -> None:
        if session_id is None:
            return
        self.run_worker(self._resume_session(session_id), exclusive=False)

    async def _resume_session(self, session_id: str) -> None:
        try:
            resume_message = await self.session.resume(session_id)
            self.state.clear()
            self.state.load_messages(self.session.messages)
            self._notify(resume_message)
        except Exception as exc:  # noqa: BLE001 - surface command failures in the TUI
            self._notify(f"Error: {exc}", severity="error")
        self._refresh()

    def _apply_selected_completion(self, value: str) -> str | None:
        item = self._completion_state.selected
        if item is None:
            return None
        return item.apply(value)

    def _show_command_message(self, command_text: str, message: str) -> None:
        if "\n" in message:
            self.push_screen(
                CommandOutputScreen(
                    _command_output_title(command_text),
                    message,
                    theme=self.tui_settings.resolved_theme,
                )
            )
            return
        self._notify(message)

    def _open_login(self, provider_name: str) -> None:
        entry = builtin_provider_entry(provider_name)
        if entry is None:
            self._notify(f"Unknown provider: {provider_name}", severity="error")
            return
        self.push_screen(
            LoginScreen(entry, theme=self.tui_settings.resolved_theme),
            callback=lambda api_key: self._handle_login_result(entry, api_key),
        )

    def _handle_login_result(self, entry: ProviderCatalogEntry, api_key: str | None) -> None:
        if api_key is None:
            return
        try:
            FileCredentialStore().set(entry.credential_name, api_key)
            settings = load_provider_settings()
            provider = provider_config_from_catalog_entry(entry.name)
            save_provider_settings(upsert_provider(settings, provider, set_default=True))
            self.session.reload()
            self.session.set_provider(entry.name)
        except Exception as exc:  # noqa: BLE001 - surface login failures in the TUI
            self._notify(f"Could not save login: {exc}", severity="error")
            return
        self._notify(f"Saved login for {entry.display_name}.")
        self._refresh()

    def _notify(
        self,
        message: str,
        *,
        severity: Literal["information", "warning", "error"] = "information",
    ) -> None:
        self.notify(message, severity=severity)

    def _refresh(self) -> None:
        theme = self.tui_settings.resolved_theme
        sidebar = self.query_one("#sidebar", SessionSidebar)
        sidebar.update_from_session(self.session, theme=theme)
        compact_info = self.query_one("#compact-session-info", CompactSessionInfo)
        compact_info.update_from_session(self.session, theme=theme)
        transcript = self.query_one("#transcript", TranscriptView)
        transcript.update_from_state(self.state, theme=theme)
        status = self.query_one("#status", Static)
        status.update("Working…" if self.state.running else "Ready")

    def _refresh_completions(self) -> None:
        suggestions = self.query_one("#autocomplete", Static)
        suggestions.display = bool(self._completion_state.items)
        suggestions.update(
            render_completion_suggestions(
                self._completion_state,
                theme=self.tui_settings.resolved_theme,
            )
        )

    def _update_responsive_layout(self, width: int, height: int) -> None:
        show_sidebar = width >= SIDEBAR_MIN_WIDTH and height >= SIDEBAR_MIN_HEIGHT
        self.set_class(not show_sidebar, "-hide-sidebar")

    def _build_completion_state(self, text: str) -> CompletionState:
        registry = _session_command_registry(self.session)
        return build_completion_state(
            text,
            command_registry=registry,
            skills=self.session.skills,
            prompt_templates=self.session.prompt_templates,
            model_names=self.session.available_models,
            provider_names=self.session.available_providers,
            session_options=_session_options(self.session),
        )


def _session_command_registry(session: CodingSession) -> CommandRegistry:
    registry = getattr(session, "command_registry", None)
    if isinstance(registry, CommandRegistry):
        return registry
    return create_default_command_registry()


def _session_options(session: CodingSession) -> tuple[CompletionOption, ...]:
    return tuple(_session_option(record) for record in _session_records(session))


def _session_records(session: CodingSession) -> tuple[SessionCompletionRecord, ...]:
    manager = getattr(session, "session_manager", None)
    if manager is None:
        return ()
    return tuple(manager.list_sessions())


def _session_option(record: SessionCompletionRecord) -> CompletionOption:
    description_parts = [record.title if record.title else "Untitled session"]
    if record.model:
        description_parts.append(record.model)
    description_parts.append(_short_path(record.cwd))
    return CompletionOption(value=record.id, description=" - ".join(description_parts))


def _short_path(path: Path) -> str:
    home = Path.home()
    try:
        return f"~/{path.relative_to(home)}"
    except ValueError:
        return str(path)


def _session_picker_label(record: SessionCompletionRecord) -> str:
    return f"{record.id}\n  {_session_option(record).description}"


def _command_output_title(command_text: str) -> str:
    command_name = command_text.split(maxsplit=1)[0].removeprefix("/")
    return f"/{command_name or 'help'}"


def _theme_css_variables(theme: TuiTheme) -> dict[str, str]:
    return {
        "tau-screen-background": theme.screen_background,
        "tau-screen-text": theme.screen_text,
        "tau-chrome-background": theme.chrome_background,
        "tau-chrome-text": theme.chrome_text,
        "tau-muted-text": theme.muted_text,
        "tau-sidebar-background": theme.sidebar_background,
        "tau-border": theme.border,
        "tau-transcript-background": theme.transcript_background,
        "tau-prompt-background": theme.prompt_background,
        "tau-prompt-text": theme.prompt_text,
        "tau-prompt-border": theme.prompt_border,
        "tau-autocomplete-background": theme.autocomplete_background,
    }


def _app_bindings(keybindings: TuiKeybindings) -> list[Binding]:
    return [
        Binding(keybindings.cancel, "cancel", "Cancel"),
        Binding(keybindings.command_palette, "open_command_palette", "Commands"),
        Binding(keybindings.session_picker, "open_session_picker", "Sessions"),
        Binding(
            keybindings.accept_completion,
            "accept_completion",
            "Complete",
            priority=True,
        ),
        Binding(
            keybindings.completion_next,
            "completion_next",
            "Next completion",
            priority=True,
        ),
        Binding(
            keybindings.completion_previous,
            "completion_previous",
            "Previous completion",
            priority=True,
        ),
        Binding(keybindings.quit, "quit", "Quit"),
    ]


def _prompt_bindings(keybindings: TuiKeybindings) -> list[Binding]:
    return [
        Binding(keybindings.command_palette, "open_command_palette", show=False, priority=True),
        Binding(keybindings.session_picker, "open_session_picker", show=False, priority=True),
        Binding(keybindings.accept_completion, "accept_completion", show=False, priority=True),
        Binding(keybindings.completion_next, "completion_next", show=False, priority=True),
        Binding(keybindings.completion_previous, "completion_previous", show=False, priority=True),
        Binding(keybindings.quit, "quit", "Quit", priority=True),
    ]


async def run_tui_app(
    *,
    model: str | None,
    cwd: Path,
    session_id: str | None = None,
    new_session: bool = False,
    provider_name: str | None = None,
    auto_compact_token_threshold: int | None = None,
    session_manager: SessionManager | None = None,
) -> None:
    """Create the default provider/session and run the Textual app."""
    if new_session and session_id is not None:
        raise RuntimeError("--resume and --new-session cannot be used together")

    provider_settings = load_provider_settings()
    selection = resolve_provider_selection(
        provider_settings,
        provider_name=provider_name,
        model=model,
    )
    startup_message: str | None = None
    try:
        provider = create_model_provider(selection.provider)
    except RuntimeError as exc:
        startup_message = f"{exc} Run /login {selection.provider.name} to save an API key."
        provider = LoginRequiredProvider(startup_message)
    manager = session_manager or SessionManager()
    session: CodingSession | None = None
    try:
        if session_id is not None:
            existing_record = manager.get_session(session_id)
            if existing_record is None:
                raise RuntimeError(f"Unknown session: {session_id}")
            record = existing_record
        else:
            record = manager.create_session(cwd=cwd, model=selection.model)

        session = await CodingSession.load(
            CodingSessionConfig(
                provider=provider,
                model=record.model or selection.model,
                cwd=record.cwd,
                storage=jsonl_session_storage(record.path),
                session_id=record.id,
                session_manager=manager,
                provider_name=selection.provider.name,
                provider_settings=provider_settings,
                auto_compact_token_threshold=auto_compact_token_threshold,
            )
        )
        app = TauTuiApp(
            session,
            tui_settings=load_tui_settings(),
            startup_message=startup_message,
        )
        await app.run_async()
    finally:
        if session is not None:
            close_session = getattr(session, "aclose", None)
            if close_session is not None:
                await close_session()
        await provider.aclose()
