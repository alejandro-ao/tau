from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from rich import box
from rich.console import Console
from rich.panel import Panel
from textual.containers import VerticalScroll
from textual.widgets import Input

from tau_agent import (
    AgentEndEvent,
    AgentEvent,
    AgentStartEvent,
    AssistantMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from tau_coding.commands import CommandResult
from tau_coding.provider_config import OpenAICompatibleProviderConfig, ProviderSettings
from tau_coding.session_manager import CodingSessionRecord
from tau_coding.skills import Skill
from tau_coding.system_prompt import ProjectContextFile
from tau_coding.tools import create_coding_tools
from tau_coding.tui import app as tui_app
from tau_coding.tui.app import CommandOutputScreen, LoginScreen, SessionPickerScreen, TauTuiApp
from tau_coding.tui.config import HIGH_CONTRAST_THEME, TuiKeybindings, TuiSettings
from tau_coding.tui.state import ChatItem
from tau_coding.tui.widgets import (
    render_chat_item,
    render_compact_session_info,
    render_session_sidebar,
)


class FakeSessionState:
    thinking_level = "medium"


class FakeSession:
    def __init__(self, messages=(), events=()) -> None:
        self.messages = tuple(messages)
        self.events = tuple(events)
        self.cwd = Path("/workspace/project")
        self.provider_name = "openai"
        self.model = "fake-model"
        self.available_models = ("fake-model",)
        self.available_providers = ("openai",)
        self.tools = tuple(create_coding_tools(cwd=self.cwd))
        self.skills = (Skill(name="review", path=self.cwd / "review.md", content="Review code"),)
        self.prompt_templates = ()
        self.context_files = (
            ProjectContextFile(path=str(self.cwd / "AGENTS.md"), content="Follow rules."),
        )
        self.context_token_estimate = 123
        self.auto_compact_token_threshold = 1000
        self.state = FakeSessionState()
        self.resource_diagnostics = ()
        self.session_manager = None
        self.compact_summaries: list[str] = []
        self.resumed_session_ids: list[str] = []
        self.reload_count = 0

    def handle_command(self, text: str) -> CommandResult:
        if text == "/help":
            return CommandResult(
                handled=True,
                message="Available commands:\n/help\tShow available slash commands.",
            )
        if text == "/clear":
            return CommandResult(handled=True, clear_requested=True, message="Transcript cleared.")
        if text.startswith("/compact "):
            return CommandResult(handled=True, compact_summary=text.removeprefix("/compact "))
        if text.startswith("/resume "):
            return CommandResult(handled=True, resume_session_id=text.removeprefix("/resume "))
        if text == "/login openai":
            return CommandResult(handled=True, login_provider="openai")
        return CommandResult(handled=False)

    def set_model(self, model: str) -> None:
        self.model = model

    def set_provider(self, provider_name: str) -> None:
        self.provider_name = provider_name

    def reload(self) -> None:
        self.reload_count += 1

    async def compact(self, summary: str) -> str:
        self.compact_summaries.append(summary)
        return "Compacted 2 context entries."

    async def resume(self, session_id: str) -> str:
        self.resumed_session_ids.append(session_id)
        self.messages = (UserMessage(content="Restored prompt"),)
        return f"Resumed session: {session_id}"

    async def prompt(self, text: str) -> AsyncIterator[AgentEvent]:
        for event in self.events:
            yield event


def test_session_sidebar_renders_session_metadata() -> None:
    console = Console(record=True, width=80)

    console.print(render_session_sidebar(FakeSession()))

    output = console.export_text()
    assert "████████" in output
    assert "τ = 2π" in output
    assert "session" in output
    assert "context" in output
    assert "12%" in output
    assert "fake-model" in output
    assert "thinking" in output
    assert "medium" in output
    assert "location" in output
    assert "/workspace/project" in output
    assert "branch" in output
    assert "tools" in output
    assert "read" in output
    assert "skills" in output
    assert "review" in output


def test_session_sidebar_uses_square_muted_panels() -> None:
    sidebar = render_session_sidebar(FakeSession())
    panels = [renderable for renderable in sidebar.renderables if isinstance(renderable, Panel)]

    assert len(panels) == 4
    assert all(renderable.box == box.SQUARE for renderable in panels)
    assert {str(renderable.border_style) for renderable in panels} == {"#141922"}


def test_compact_session_info_renders_sidebar_facts() -> None:
    console = Console(record=True, width=120)

    console.print(render_compact_session_info(FakeSession()))

    output = console.export_text()
    assert "context 12%" in output
    assert "model fake-model" in output
    assert "thinking medium" in output
    assert "location /workspace/project" in output
    assert "branch --" in output


def test_compact_session_info_wraps_to_available_width() -> None:
    console = Console(record=True, width=36)

    console.print(render_compact_session_info(FakeSession()))

    lines = console.export_text().splitlines()
    assert len(lines) > 1
    assert max(len(line) for line in lines) <= 36


def test_chat_items_render_as_unlabeled_blocks() -> None:
    console = Console(record=True, width=40)

    console.print(render_chat_item(ChatItem(role="user", text="Read the file")))
    output = console.export_text()

    assert "Read the file" in output
    assert "you:" not in output
    assert "assistant:" not in output
    assert "tool:" not in output
    assert "▌ Read the file" in output


def test_chat_items_use_left_accent_instead_of_box_border() -> None:
    console = Console(record=True, width=40)

    console.print(render_chat_item(ChatItem(role="assistant", text="Done.")))
    output = console.export_text()

    assert "▌ Done." in output
    assert "┌" not in output
    assert "└" not in output


def test_chat_items_have_bottom_padding() -> None:
    console = Console(record=True, width=40)

    console.print(render_chat_item(ChatItem(role="user", text="Read the file")))
    output = console.export_text().splitlines()

    assert output[-1].strip() == ""


def test_chat_items_fold_long_unbroken_text_to_console_width() -> None:
    console = Console(record=True, width=36)
    long_text = "supercalifragilisticexpialidocious" * 2

    console.print(render_chat_item(ChatItem(role="assistant", text=long_text)))
    output = console.export_text()

    assert max(len(line) for line in output.splitlines()) <= 36


def test_chat_items_use_configured_theme_accent() -> None:
    console = Console(record=True, width=40)

    console.print(
        render_chat_item(
            ChatItem(role="assistant", text="Done."),
            theme=HIGH_CONTRAST_THEME,
        )
    )
    output = console.export_text(styles=True)

    assert "Done." in output
    assert "38;2;0;255;102" in output


def test_chat_items_render_fenced_code_without_markers() -> None:
    console = Console(record=True, width=60)
    item = ChatItem(
        role="assistant",
        text='Here is code:\n\n```python\nprint("hi")\n```',
    )

    console.print(render_chat_item(item))
    output = console.export_text()

    assert 'print("hi")' in output
    assert "```" not in output
    assert "python" not in output


def test_assistant_chat_items_render_markdown_lists() -> None:
    console = Console(record=True, width=60)
    item = ChatItem(role="assistant", text="Plan:\n\n- inspect\n- patch")

    console.print(render_chat_item(item))
    output = console.export_text()

    assert "Plan:" in output
    assert "• inspect" in output
    assert "• patch" in output
    assert "- inspect" not in output


def test_user_chat_items_keep_markdown_literal() -> None:
    console = Console(record=True, width=60)
    item = ChatItem(role="user", text="- keep this literal")

    console.print(render_chat_item(item))
    output = console.export_text()

    assert "- keep this literal" in output
    assert "• keep this literal" not in output


def test_chat_items_preserve_malformed_fenced_code() -> None:
    console = Console(record=True, width=60)
    item = ChatItem(role="assistant", text='```python\nprint("hi")')

    console.print(render_chat_item(item))
    output = console.export_text()

    assert "```python" in output
    assert 'print("hi")' in output


@pytest.mark.anyio
async def test_tui_app_mounts_sidebar_and_transcript() -> None:
    app = TauTuiApp(FakeSession())

    async with app.run_test(size=(120, 30)):
        assert app.query_one("#sidebar") is not None
        transcript = app.query_one("#transcript")
        assert transcript is not None
        assert transcript.min_width == 1
        assert app.query_one("#prompt") is not None


@pytest.mark.anyio
async def test_tui_sidebar_is_visible_on_medium_windows() -> None:
    app = TauTuiApp(FakeSession())

    async with app.run_test(size=(120, 30)):
        sidebar = app.query_one("#sidebar")
        compact_info = app.query_one("#compact-session-info")
        assert sidebar.display is True
        assert compact_info.display is False
        assert not app.has_class("-hide-sidebar")


@pytest.mark.anyio
async def test_tui_sidebar_fills_workspace_height() -> None:
    app = TauTuiApp(FakeSession())

    async with app.run_test(size=(120, 30)):
        workspace = app.query_one("#workspace")
        sidebar = app.query_one("#sidebar")

        assert sidebar.region.height == workspace.region.height
        assert sidebar.outer_size.height == workspace.size.height


@pytest.mark.anyio
async def test_tui_sidebar_hides_on_narrow_windows() -> None:
    app = TauTuiApp(FakeSession())

    async with app.run_test(size=(80, 30)):
        sidebar = app.query_one("#sidebar")
        compact_info = app.query_one("#compact-session-info")
        assert sidebar.display is False
        assert compact_info.display is True
        assert app.has_class("-hide-sidebar")


@pytest.mark.anyio
async def test_tui_sidebar_hides_on_short_windows() -> None:
    app = TauTuiApp(FakeSession())

    async with app.run_test(size=(120, 18)):
        sidebar = app.query_one("#sidebar")
        compact_info = app.query_one("#compact-session-info")
        assert sidebar.display is False
        assert compact_info.display is True
        assert app.has_class("-hide-sidebar")


@pytest.mark.anyio
async def test_tui_sidebar_visibility_updates_on_resize() -> None:
    app = TauTuiApp(FakeSession())

    async with app.run_test(size=(120, 30)) as pilot:
        sidebar = app.query_one("#sidebar")
        compact_info = app.query_one("#compact-session-info")
        assert sidebar.display is True
        assert compact_info.display is False

        await pilot.resize_terminal(width=80, height=30)
        await pilot.pause()
        assert sidebar.display is False
        assert compact_info.display is True

        await pilot.resize_terminal(width=120, height=18)
        await pilot.pause()
        assert sidebar.display is False
        assert compact_info.display is True

        await pilot.resize_terminal(width=120, height=30)
        await pilot.pause()
        assert sidebar.display is True
        assert compact_info.display is False


@pytest.mark.anyio
async def test_tui_transcript_reflows_when_terminal_resizes() -> None:
    app = TauTuiApp(
        FakeSession(
            messages=[
                UserMessage(
                    content=(
                        "Please summarize this very long sentence that should wrap cleanly "
                        "inside the transcript when the terminal becomes narrower."
                    )
                )
            ]
        )
    )

    async with app.run_test(size=(120, 30)) as pilot:
        transcript = app.query_one("#transcript")
        assert transcript.virtual_size.width <= transcript.scrollable_content_region.width

        await pilot.resize_terminal(width=64, height=30)
        await pilot.pause()

        assert transcript.virtual_size.width <= transcript.scrollable_content_region.width
        assert transcript.scroll_offset.x == 0


def test_tui_app_uses_configured_theme_css_variables() -> None:
    app = TauTuiApp(FakeSession(), tui_settings=TuiSettings(theme="high-contrast"))

    variables = app.get_theme_variable_defaults()

    assert variables["tau-screen-background"] == "#000000"
    assert variables["tau-prompt-border"] == "#00ff66"


def test_tui_app_loads_restored_messages_into_display_state() -> None:
    app = TauTuiApp(
        FakeSession(
            messages=[
                UserMessage(content="Read the file"),
                AssistantMessage(
                    content="I'll inspect it.",
                    tool_calls=[
                        ToolCall(id="call-1", name="edit", arguments={"path": "README.md"})
                    ],
                ),
                ToolResultMessage(
                    tool_call_id="call-1",
                    name="edit",
                    content="Successfully replaced 1 block.",
                    ok=True,
                    data={"patch": "--- README.md\n+++ README.md\n@@\n-old\n+new"},
                ),
            ]
        )
    )

    assert [(item.role, item.text) for item in app.state.items] == [
        ("user", "Read the file"),
        ("assistant", "I'll inspect it."),
        ("tool", "→ edit {'path': 'README.md'}"),
        (
            "tool",
            "✓ edit\n"
            "Successfully replaced 1 block.\n"
            "\n"
            "Patch:\n"
            "--- README.md\n"
            "+++ README.md\n"
            "@@\n"
            "-old\n"
            "+new",
        ),
    ]


@pytest.mark.anyio
async def test_tui_app_clear_command_clears_visible_state() -> None:
    app = TauTuiApp(FakeSession(messages=[UserMessage(content="Earlier")]))

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt")
        prompt.value = "/clear"
        await pilot.press("enter")

        assert app.state.items == []


@pytest.mark.anyio
async def test_tui_app_compact_command_runs_session_compaction() -> None:
    session = FakeSession(messages=[UserMessage(content="Earlier")])
    app = TauTuiApp(session)

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt")
        prompt.value = "/compact Summary of earlier work."
        await pilot.press("enter")

        assert session.compact_summaries == ["Summary of earlier work."]
        assert [(item.role, item.text) for item in app.state.items] == [("user", "Earlier")]


@pytest.mark.anyio
async def test_tui_app_resume_command_reloads_visible_state() -> None:
    session = FakeSession(messages=[UserMessage(content="Earlier")])
    app = TauTuiApp(session)

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt")
        prompt.value = "/resume session-1"
        await pilot.press("enter")

        assert session.resumed_session_ids == ["session-1"]
        assert [(item.role, item.text) for item in app.state.items] == [
            ("user", "Restored prompt"),
        ]


@pytest.mark.anyio
async def test_tui_app_completes_registered_slash_command() -> None:
    app = TauTuiApp(FakeSession())

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt")
        prompt.value = "/st"
        app._completion_state = app._build_completion_state(prompt.value)
        app._refresh_completions()

        await pilot.press("tab")

        assert prompt.value == "/status"


@pytest.mark.anyio
async def test_tui_app_enter_accepts_completion_without_submitting() -> None:
    app = TauTuiApp(FakeSession())

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt")
        prompt.value = "/st"
        app._completion_state = app._build_completion_state(prompt.value)
        app._refresh_completions()

        await pilot.press("enter")

        assert prompt.value == "/status"
        assert app.state.items == []


@pytest.mark.anyio
async def test_tui_app_enter_accepts_arrow_selected_completion() -> None:
    app = TauTuiApp(FakeSession())

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt")
        prompt.value = "/s"
        app._completion_state = app._build_completion_state(prompt.value)
        app._refresh_completions()
        await pilot.press("down")
        selected = app._completion_state.selected
        assert selected is not None

        await pilot.press("enter")

        assert prompt.value == selected.replacement
        assert app.state.items == []


@pytest.mark.anyio
async def test_tui_app_completes_skill_name() -> None:
    app = TauTuiApp(FakeSession())

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt")
        prompt.value = "/skill:r"
        app._completion_state = app._build_completion_state(prompt.value)
        app._refresh_completions()

        await pilot.press("tab")

        assert prompt.value == "/skill:review"


@pytest.mark.anyio
async def test_tui_app_completes_model_argument() -> None:
    app = TauTuiApp(FakeSession())

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt")
        prompt.value = "/model fak"
        app._completion_state = app._build_completion_state(prompt.value)
        app._refresh_completions()

        await pilot.press("tab")

        assert prompt.value == "/model fake-model"


@pytest.mark.anyio
async def test_tui_app_completes_resume_session_argument() -> None:
    session = FakeSession()
    session.session_manager = _FakeSessionManager(
        [
            CodingSessionRecord(
                id="session-1",
                path=Path("/tmp/session-1.jsonl"),
                cwd=Path("/workspace/project"),
                model="fake-model",
                title="Session",
                created_at=1.0,
                updated_at=2.0,
            )
        ]
    )
    app = TauTuiApp(session)

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt")
        prompt.value = "/resume sess"
        app._completion_state = app._build_completion_state(prompt.value)
        app._refresh_completions()

        assert app._completion_state.selected is not None
        assert app._completion_state.selected.description == (
            "Session - fake-model - /workspace/project"
        )

        await pilot.press("tab")

        assert prompt.value == "/resume session-1"


@pytest.mark.anyio
async def test_tui_app_session_picker_resumes_selected_session() -> None:
    session = FakeSession(messages=[UserMessage(content="Earlier")])
    session.session_manager = _FakeSessionManager(
        [
            CodingSessionRecord(
                id="session-1",
                path=Path("/tmp/session-1.jsonl"),
                cwd=Path("/workspace/project"),
                model="fake-model",
                title="Session",
                created_at=1.0,
                updated_at=2.0,
            )
        ]
    )
    app = TauTuiApp(session)

    async with app.run_test() as pilot:
        await pilot.press("ctrl+r")
        assert isinstance(app.screen, SessionPickerScreen)

        await pilot.press("enter")
        await pilot.pause()

        assert session.resumed_session_ids == ["session-1"]
        assert [(item.role, item.text) for item in app.state.items] == [
            ("user", "Restored prompt"),
        ]


@pytest.mark.anyio
async def test_tui_app_cycles_completion_selection() -> None:
    app = TauTuiApp(FakeSession())

    async with app.run_test():
        prompt = app.query_one("#prompt")
        prompt.focus()
        prompt.value = "/s"
        app._completion_state = app._build_completion_state(prompt.value)
        app._refresh_completions()

        first = app._completion_state.selected.display if app._completion_state.selected else None
        prompt.action_scroll_down()
        second = app._completion_state.selected.display if app._completion_state.selected else None

        assert first != second


@pytest.mark.anyio
async def test_tui_app_opens_command_palette_from_keybinding() -> None:
    app = TauTuiApp(FakeSession())

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt")
        await pilot.press("ctrl+k")

        assert prompt.value == "/"
        assert app._completion_state.items
        assert any(item.display == "/help" for item in app._completion_state.items)
        assert app.query_one("#autocomplete").display is True


@pytest.mark.anyio
async def test_tui_app_help_uses_modal_instead_of_transcript() -> None:
    app = TauTuiApp(FakeSession())

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt")
        prompt.value = "/help"
        await pilot.press("enter")

        assert isinstance(app.screen, CommandOutputScreen)
        assert app.state.items == []
        assert "Available commands:" in app.screen.message
        assert app.screen.query_one("#command-output-scroll", VerticalScroll) is not None


@pytest.mark.anyio
async def test_tui_app_command_modal_renders_literal_markup_text() -> None:
    app = TauTuiApp(FakeSession())

    async with app.run_test() as pilot:
        app._show_command_message("/help", "Available [commands]\n/help")
        await pilot.pause()

        assert isinstance(app.screen, CommandOutputScreen)
        body = app.screen.query_one("#command-output-body")
        assert str(body.render()) == "Available [commands]\n/help"


@pytest.mark.anyio
async def test_tui_app_escape_without_running_does_not_append_transcript_status() -> None:
    app = TauTuiApp(FakeSession(messages=[UserMessage(content="Earlier")]))

    async with app.run_test() as pilot:
        await pilot.press("escape")

        assert [(item.role, item.text) for item in app.state.items] == [("user", "Earlier")]


@pytest.mark.anyio
async def test_tui_app_uses_configured_command_palette_keybinding() -> None:
    app = TauTuiApp(
        FakeSession(),
        tui_settings=TuiSettings(keybindings=TuiKeybindings(command_palette="ctrl+j")),
    )

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt")
        await pilot.press("ctrl+k")

        assert prompt.value == ""
        assert app._completion_state.items == ()

        await pilot.press("ctrl+j")

        assert prompt.value == "/"
        assert app._completion_state.items
        assert any(item.display == "/help" for item in app._completion_state.items)


@pytest.mark.anyio
async def test_tui_app_quits_from_focused_prompt_with_default_keybinding() -> None:
    app = TauTuiApp(FakeSession())

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt")
        visible_bindings = [
            binding
            for binding in prompt._bindings.get_bindings_for_key("ctrl+d")
            if binding.show
        ]

        assert any(
            binding.action == "quit" and binding.description == "Quit"
            for binding in visible_bindings
        )

        await pilot.press("ctrl+d")
        await pilot.pause()

        assert app._exit is True


@pytest.mark.anyio
async def test_tui_app_uses_configured_completion_keybinding() -> None:
    app = TauTuiApp(
        FakeSession(),
        tui_settings=TuiSettings(keybindings=TuiKeybindings(accept_completion="f2")),
    )

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt")
        prompt.value = "/st"
        app._completion_state = app._build_completion_state(prompt.value)
        app._refresh_completions()

        await pilot.press("tab")
        assert prompt.value == "/st"

        await pilot.press("f2")
        assert prompt.value == "/status"


@pytest.mark.anyio
async def test_tui_login_saves_provider_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    session = FakeSession()
    app = TauTuiApp(session)

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt")
        prompt.value = "/login openai"
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, LoginScreen)

        api_key_input = app.screen.query_one("#login-api-key", Input)
        api_key_input.value = "stored-openai-key"
        await pilot.press("enter")
        await pilot.pause()

    assert session.reload_count == 1
    assert session.provider_name == "openai"
    assert (tmp_path / ".tau" / "credentials.json").read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_tui_prompt_worker_refreshes_directly() -> None:
    app = TauTuiApp(FakeSession(events=[AgentStartEvent(), AgentEndEvent()]))
    refreshes = 0

    def fake_refresh() -> None:
        nonlocal refreshes
        refreshes += 1

    app._refresh = fake_refresh  # type: ignore[method-assign]

    await app._run_prompt("hello")

    assert refreshes == 2
    assert app.state.running is False


@pytest.mark.anyio
async def test_run_tui_app_creates_new_session_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    record = CodingSessionRecord(
        id="new-session",
        path=tmp_path / "new-session.jsonl",
        cwd=tmp_path,
        model="fake-model",
        title=None,
        created_at=1.0,
        updated_at=1.0,
    )

    class FakeProvider:
        async def aclose(self) -> None:
            calls.append("provider_closed")

    class FakeManager:
        def create_session(self, *, cwd: Path, model: str) -> CodingSessionRecord:
            calls.append(f"create:{cwd}:{model}")
            return record

        def get_session(self, session_id: str) -> CodingSessionRecord | None:
            calls.append(f"get:{session_id}")
            return None

        def get_or_create_default_session(self, *, cwd: Path, model: str) -> CodingSessionRecord:
            raise AssertionError("default session should not be opened implicitly")

    class FakeCodingSession:
        @classmethod
        async def load(cls, config: object) -> str:
            assert config.provider_name == "local"  # type: ignore[attr-defined]
            assert config.auto_compact_token_threshold == 1000  # type: ignore[attr-defined]
            calls.append("load")
            return "session"

    class FakeApp:
        def __init__(self, session: str, **kwargs: object) -> None:
            assert session == "session"
            assert isinstance(kwargs["tui_settings"], TuiSettings)

        async def run_async(self) -> None:
            calls.append("run")

    settings = ProviderSettings(
        default_provider="local",
        providers=(
            OpenAICompatibleProviderConfig(
                name="local",
                base_url="http://localhost:11434/v1",
                api_key_env="LOCAL_API_KEY",
                models=("local-model",),
                default_model="local-model",
            ),
        ),
    )
    monkeypatch.setattr(tui_app, "load_provider_settings", lambda: settings)
    monkeypatch.setattr(tui_app, "create_model_provider", lambda provider: FakeProvider())
    monkeypatch.setattr(tui_app, "CodingSession", FakeCodingSession)
    monkeypatch.setattr(tui_app, "TauTuiApp", FakeApp)

    await tui_app.run_tui_app(
        model=None,
        cwd=tmp_path,
        provider_name="local",
        auto_compact_token_threshold=1000,
        session_manager=FakeManager(),
    )

    assert calls == [f"create:{tmp_path}:local-model", "load", "run", "provider_closed"]


@pytest.mark.anyio
async def test_run_tui_app_opens_when_provider_login_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    record = CodingSessionRecord(
        id="new-session",
        path=tmp_path / "new-session.jsonl",
        cwd=tmp_path,
        model="fake-model",
        title=None,
        created_at=1.0,
        updated_at=1.0,
    )

    class FakeManager:
        def create_session(self, *, cwd: Path, model: str) -> CodingSessionRecord:
            calls.append(f"create:{cwd}:{model}")
            return record

        def get_session(self, session_id: str) -> CodingSessionRecord | None:
            return None

    class FakeCodingSession:
        @classmethod
        async def load(cls, config: object) -> str:
            calls.append(f"load:{type(config.provider).__name__}")  # type: ignore[attr-defined]
            return "session"

    class FakeApp:
        def __init__(self, session: str, **kwargs: object) -> None:
            assert session == "session"
            assert "Run /login openai" in str(kwargs["startup_message"])

        async def run_async(self) -> None:
            calls.append("run")

    monkeypatch.setattr(tui_app, "load_provider_settings", lambda: ProviderSettings())
    monkeypatch.setattr(
        tui_app,
        "create_model_provider",
        lambda provider: (_ for _ in ()).throw(RuntimeError("Missing provider API key.")),
    )
    monkeypatch.setattr(tui_app, "CodingSession", FakeCodingSession)
    monkeypatch.setattr(tui_app, "TauTuiApp", FakeApp)

    await tui_app.run_tui_app(cwd=tmp_path, model=None, session_manager=FakeManager())

    assert calls == [f"create:{tmp_path}:gpt-4.1-mini", "load:LoginRequiredProvider", "run"]


@pytest.mark.anyio
async def test_run_tui_app_resumes_explicit_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    record = CodingSessionRecord(
        id="session-1",
        path=tmp_path / "session-1.jsonl",
        cwd=tmp_path,
        model="fake-model",
        title=None,
        created_at=1.0,
        updated_at=1.0,
    )

    class FakeProvider:
        async def aclose(self) -> None:
            calls.append("provider_closed")

    class FakeManager:
        def create_session(self, *, cwd: Path, model: str) -> CodingSessionRecord:
            raise AssertionError("explicit resume should not create a new session")

        def get_session(self, session_id: str) -> CodingSessionRecord | None:
            calls.append(f"get:{session_id}")
            return record

    class FakeCodingSession:
        @classmethod
        async def load(cls, config: object) -> str:
            calls.append("load")
            return "session"

    class FakeApp:
        def __init__(self, session: str, **kwargs: object) -> None:
            assert session == "session"
            assert isinstance(kwargs["tui_settings"], TuiSettings)

        async def run_async(self) -> None:
            calls.append("run")

    settings = ProviderSettings()
    monkeypatch.setattr(tui_app, "load_provider_settings", lambda: settings)
    monkeypatch.setattr(tui_app, "create_model_provider", lambda provider: FakeProvider())
    monkeypatch.setattr(tui_app, "CodingSession", FakeCodingSession)
    monkeypatch.setattr(tui_app, "TauTuiApp", FakeApp)

    await tui_app.run_tui_app(
        model="fake-model",
        cwd=tmp_path,
        session_id="session-1",
        session_manager=FakeManager(),
    )

    assert calls == ["get:session-1", "load", "run", "provider_closed"]


class _FakeSessionManager:
    def __init__(self, records: list[CodingSessionRecord]) -> None:
        self._records = records

    def list_sessions(self) -> list[CodingSessionRecord]:
        return self._records
