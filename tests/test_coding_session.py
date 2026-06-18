from pathlib import Path

import pytest

from tau_agent import AssistantMessage, ToolCall, ToolResultMessage, UserMessage
from tau_agent.session import (
    CompactionEntry,
    JsonlSessionStorage,
    LeafEntry,
    MessageEntry,
    ModelChangeEntry,
    SessionInfoEntry,
)
from tau_ai import FakeProvider, ProviderResponseEndEvent, ProviderResponseStartEvent
from tau_coding import (
    CodingSession,
    CodingSessionConfig,
    OpenAICompatibleProviderConfig,
    ProviderSettings,
    SessionManager,
    TauPaths,
    TauResourcePaths,
)
from tau_coding import session as coding_session_module


async def _collect_session_events(session_stream: object) -> list[object]:
    return [event async for event in session_stream]  # type: ignore[attr-defined]


def _config(
    tmp_path: Path, provider: FakeProvider, storage: JsonlSessionStorage
) -> CodingSessionConfig:
    return CodingSessionConfig(
        provider=provider,
        model="fake",
        system="You are Tau.",
        storage=storage,
        cwd=tmp_path,
    )


class SwitchableFakeProvider:
    def __init__(self, config: object) -> None:
        self.config = config
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_load_empty_session_appends_metadata(tmp_path: Path) -> None:
    storage = JsonlSessionStorage(tmp_path / "session.jsonl")

    session = await CodingSession.load(_config(tmp_path, FakeProvider([]), storage))

    entries = await storage.read_all()
    assert isinstance(entries[0], SessionInfoEntry)
    assert entries[0].cwd == str(tmp_path)
    assert entries[1] == ModelChangeEntry(
        id=entries[1].id, parent_id=entries[0].id, model="fake", timestamp=entries[1].timestamp
    )
    assert session.messages == ()
    assert session.state.model == "fake"
    assert session.cwd == tmp_path
    assert session.model == "fake"
    assert [tool.name for tool in session.tools] == ["read", "write", "edit", "bash"]


@pytest.mark.anyio
async def test_prompt_persists_user_assistant_and_leaf_entries(tmp_path: Path) -> None:
    storage = JsonlSessionStorage(tmp_path / "session.jsonl")
    provider = FakeProvider(
        [
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderResponseEndEvent(message=AssistantMessage(content="Hi")),
            ]
        ]
    )
    session = await CodingSession.load(_config(tmp_path, provider, storage))

    _events = await _collect_session_events(session.prompt("Hello"))

    entries = await storage.read_all()
    message_entries = [entry for entry in entries if entry.type == "message"]
    assert [entry.message for entry in message_entries] == [
        UserMessage(content="Hello"),
        AssistantMessage(content="Hi"),
    ]
    assert entries[-1].type == "leaf"
    assert entries[-1].entry_id == message_entries[-1].id
    assert session.messages == (UserMessage(content="Hello"), AssistantMessage(content="Hi"))


@pytest.mark.anyio
async def test_load_restores_existing_transcript(tmp_path: Path) -> None:
    storage = JsonlSessionStorage(tmp_path / "session.jsonl")
    user_entry = MessageEntry(id="user", message=UserMessage(content="Earlier"))
    assistant_entry = MessageEntry(
        id="assistant",
        parent_id="user",
        message=AssistantMessage(content="Restored"),
    )
    await storage.append(user_entry)
    await storage.append(assistant_entry)

    session = await CodingSession.load(_config(tmp_path, FakeProvider([]), storage))

    assert session.messages == (
        UserMessage(content="Earlier"),
        AssistantMessage(content="Restored"),
    )


@pytest.mark.anyio
async def test_load_restores_active_leaf_branch(tmp_path: Path) -> None:
    storage = JsonlSessionStorage(tmp_path / "session.jsonl")
    root = MessageEntry(id="root", message=UserMessage(content="Root"))
    left = MessageEntry(
        id="left",
        parent_id="root",
        message=AssistantMessage(content="Inactive branch"),
    )
    right = MessageEntry(
        id="right",
        parent_id="root",
        message=AssistantMessage(content="Active branch"),
    )
    await storage.append(root)
    await storage.append(left)
    await storage.append(right)
    await storage.append(LeafEntry(entry_id="right"))

    session = await CodingSession.load(_config(tmp_path, FakeProvider([]), storage))

    assert session.messages == (
        UserMessage(content="Root"),
        AssistantMessage(content="Active branch"),
    )
    assert session.state.active_leaf_id == "right"


@pytest.mark.anyio
async def test_continue_persists_only_new_messages(tmp_path: Path) -> None:
    storage = JsonlSessionStorage(tmp_path / "session.jsonl")
    await storage.append(MessageEntry(id="user", message=UserMessage(content="Continue me")))
    provider = FakeProvider(
        [
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderResponseEndEvent(message=AssistantMessage(content="Continued")),
            ]
        ]
    )
    session = await CodingSession.load(_config(tmp_path, provider, storage))

    _events = await _collect_session_events(session.continue_())

    entries = await storage.read_all()
    message_entries = [entry for entry in entries if entry.type == "message"]
    assert [entry.message for entry in message_entries] == [
        UserMessage(content="Continue me"),
        AssistantMessage(content="Continued"),
    ]


@pytest.mark.anyio
async def test_tool_results_are_persisted(tmp_path: Path) -> None:
    storage = JsonlSessionStorage(tmp_path / "session.jsonl")
    tool_call = ToolCall(id="call-1", name="missing", arguments={})
    provider = FakeProvider(
        [
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderResponseEndEvent(
                    message=AssistantMessage(content="Using tool", tool_calls=[tool_call]),
                    finish_reason="tool_calls",
                ),
            ],
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderResponseEndEvent(message=AssistantMessage(content="Done")),
            ],
        ]
    )
    session = await CodingSession.load(_config(tmp_path, provider, storage))

    _events = await _collect_session_events(session.prompt("Use a tool"))

    messages = [entry.message for entry in await storage.read_all() if entry.type == "message"]
    assert any(isinstance(message, ToolResultMessage) for message in messages)


@pytest.mark.anyio
async def test_session_preserves_explicit_empty_system_prompt(tmp_path: Path) -> None:
    storage = JsonlSessionStorage(tmp_path / "session.jsonl")
    provider = FakeProvider(
        [
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderResponseEndEvent(message=AssistantMessage(content="Done")),
            ]
        ]
    )
    config = CodingSessionConfig(
        provider=provider,
        model="fake",
        system="",
        storage=storage,
        cwd=tmp_path,
    )
    session = await CodingSession.load(config)

    _events = await _collect_session_events(session.prompt("Hello"))

    assert provider.calls[0][1] == ""


@pytest.mark.anyio
async def test_session_builds_system_prompt_when_system_is_omitted(tmp_path: Path) -> None:
    resource_root = tmp_path / "resources"
    skills_dir = resource_root / "skills"
    skills_dir.mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("Follow project rules.", encoding="utf-8")
    (skills_dir / "testing.md").write_text(
        "---\ndescription: Test code\n---\n# Testing",
        encoding="utf-8",
    )
    storage = JsonlSessionStorage(tmp_path / "session.jsonl")
    provider = FakeProvider(
        [
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderResponseEndEvent(message=AssistantMessage(content="Done")),
            ]
        ]
    )
    config = CodingSessionConfig(
        provider=provider,
        model="fake",
        storage=storage,
        cwd=tmp_path,
        resource_paths=TauResourcePaths(root=resource_root, agents_root=None),
    )
    session = await CodingSession.load(config)

    _events = await _collect_session_events(session.prompt("Hello"))

    assert "Available tools:\n- read: Read file contents" in provider.calls[0][1]
    assert '<project_instructions path="' in provider.calls[0][1]
    assert "Follow project rules." in provider.calls[0][1]
    assert "<available_skills>" in provider.calls[0][1]
    assert "<name>testing</name>" in provider.calls[0][1]
    assert [Path(context_file.path).name for context_file in session.context_files] == ["AGENTS.md"]


@pytest.mark.anyio
async def test_session_touches_session_manager_after_persisting_messages(tmp_path: Path) -> None:
    storage = JsonlSessionStorage(tmp_path / "session.jsonl")
    manager = SessionManager(TauPaths(home=tmp_path / ".tau", agents_home=tmp_path / ".agents"))
    record = manager.create_session(cwd=tmp_path, model="fake")
    provider = FakeProvider(
        [
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderResponseEndEvent(message=AssistantMessage(content="Done")),
            ]
        ]
    )
    config = CodingSessionConfig(
        provider=provider,
        model="fake",
        system="You are Tau.",
        storage=storage,
        cwd=tmp_path,
        session_id=record.id,
        session_manager=manager,
        resource_paths=TauResourcePaths(root=tmp_path / "resources", agents_root=None),
    )
    session = await CodingSession.load(config)

    _events = await _collect_session_events(session.prompt("Hello"))

    updated = manager.get_session(record.id)
    assert updated is not None
    assert updated.updated_at >= record.updated_at


@pytest.mark.anyio
async def test_session_loads_and_expands_skills(tmp_path: Path) -> None:
    resource_root = tmp_path / "resources"
    skills_dir = resource_root / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "testing.md").write_text("# Testing\nRun pytest.", encoding="utf-8")
    storage = JsonlSessionStorage(tmp_path / "session.jsonl")
    provider = FakeProvider(
        [
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderResponseEndEvent(message=AssistantMessage(content="Done")),
            ]
        ]
    )
    config = CodingSessionConfig(
        provider=provider,
        model="fake",
        system="You are Tau.",
        storage=storage,
        cwd=tmp_path,
        resource_paths=TauResourcePaths(root=resource_root, agents_root=None),
    )
    session = await CodingSession.load(config)

    _events = await _collect_session_events(session.prompt("/skill:testing add tests"))

    assert [skill.name for skill in session.skills] == ["testing"]
    assert '<skill name="testing">' in provider.calls[0][2][0].content
    assert "User request:\nadd tests" in provider.calls[0][2][0].content
    assert session.handle_command("/skill:testing").handled is False


@pytest.mark.anyio
async def test_session_loads_with_resource_diagnostics_instead_of_failing(
    tmp_path: Path,
) -> None:
    resource_root = tmp_path / "resources"
    skills_dir = resource_root / "skills"
    (skills_dir / "dup").mkdir(parents=True)
    (skills_dir / "dup" / "SKILL.md").write_text("# Directory skill", encoding="utf-8")
    (skills_dir / "dup.md").write_text("# File skill", encoding="utf-8")
    storage = JsonlSessionStorage(tmp_path / "session.jsonl")
    config = CodingSessionConfig(
        provider=FakeProvider([]),
        model="fake",
        system="You are Tau.",
        storage=storage,
        cwd=tmp_path,
        resource_paths=TauResourcePaths(root=resource_root, agents_root=None),
    )

    session = await CodingSession.load(config)

    assert [skill.name for skill in session.skills] == ["dup"]
    assert len(session.resource_diagnostics) == 1
    assert "Duplicate skill name" in session.resource_diagnostics[0].message
    assert "Resource diagnostics: 1" in (session.handle_command("/status").message or "")


@pytest.mark.anyio
async def test_session_reload_refreshes_resources_and_system_prompt(tmp_path: Path) -> None:
    resource_root = tmp_path / "resources"
    storage = JsonlSessionStorage(tmp_path / "session.jsonl")
    provider = FakeProvider(
        [
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderResponseEndEvent(message=AssistantMessage(content="Done")),
            ]
        ]
    )
    session = await CodingSession.load(
        CodingSessionConfig(
            provider=provider,
            model="fake",
            storage=storage,
            cwd=tmp_path,
            resource_paths=TauResourcePaths(root=resource_root, agents_root=None),
        )
    )
    assert session.skills == ()
    assert session.context_files == ()

    skills_dir = resource_root / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "testing.md").write_text(
        "---\ndescription: Test code\n---\n# Testing\nRun pytest.",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text("Reloaded project rules.", encoding="utf-8")

    result = session.handle_command("/reload")
    _events = await _collect_session_events(session.prompt("Hello"))

    assert result.message is not None
    assert "Skills: 1" in result.message
    assert "Context files: 1" in result.message
    assert [skill.name for skill in session.skills] == ["testing"]
    assert [Path(context_file.path).name for context_file in session.context_files] == ["AGENTS.md"]
    assert "Reloaded project rules." in provider.calls[0][1]
    assert "<name>testing</name>" in provider.calls[0][1]


@pytest.mark.anyio
async def test_session_compact_persists_summary_and_rebuilds_context(tmp_path: Path) -> None:
    storage = JsonlSessionStorage(tmp_path / "session.jsonl")
    provider = FakeProvider(
        [
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderResponseEndEvent(message=AssistantMessage(content="Session answer")),
            ],
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderResponseEndEvent(message=AssistantMessage(content="Next answer")),
            ]
        ]
    )
    session = await CodingSession.load(_config(tmp_path, provider, storage))
    _events = await _collect_session_events(session.prompt("Explain sessions."))

    message_count_before = len(session.messages)
    message_entries_before = [
        entry.id for entry in await storage.read_all() if entry.type == "message"
    ]

    result = await session.compact("The user asked about sessions and got an explanation.")
    entries_after_compact = await storage.read_all()
    compactions = [entry for entry in entries_after_compact if entry.type == "compaction"]
    leaves = [entry for entry in entries_after_compact if entry.type == "leaf"]

    _next_events = await _collect_session_events(session.prompt("Continue."))

    assert result == f"Compacted {message_count_before} context entries."
    assert len(compactions) == 1
    assert isinstance(compactions[0], CompactionEntry)
    assert compactions[0].replaces_entry_ids == message_entries_before
    assert leaves[-1].entry_id == compactions[0].id
    assert provider.calls[1][2] == [
        UserMessage(
            content=(
                "Previous conversation summary:\n"
                "The user asked about sessions and got an explanation."
            )
        ),
        UserMessage(content="Continue."),
    ]


@pytest.mark.anyio
async def test_session_auto_compacts_before_prompt_when_threshold_is_exceeded(
    tmp_path: Path,
) -> None:
    storage = JsonlSessionStorage(tmp_path / "session.jsonl")
    provider = FakeProvider(
        [
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderResponseEndEvent(message=AssistantMessage(content="First answer")),
            ],
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderResponseEndEvent(message=AssistantMessage(content="Second answer")),
            ],
        ]
    )
    session = await CodingSession.load(
        CodingSessionConfig(
            provider=provider,
            model="fake",
            system="You are Tau.",
            storage=storage,
            cwd=tmp_path,
            auto_compact_token_threshold=1,
        )
    )
    _first_events = await _collect_session_events(session.prompt("Explain sessions."))

    _second_events = await _collect_session_events(session.prompt("Continue."))

    entries = await storage.read_all()
    compactions = [entry for entry in entries if entry.type == "compaction"]

    assert len(compactions) == 1
    assert "Automatically compacted 2 prior message(s)." in compactions[0].summary
    assert "user: Explain sessions." in compactions[0].summary
    assert "assistant: First answer" in compactions[0].summary
    assert provider.calls[1][2] == [
        UserMessage(content=f"Previous conversation summary:\n{compactions[0].summary}"),
        UserMessage(content="Continue."),
    ]


@pytest.mark.anyio
async def test_session_switches_configured_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    created_providers: list[SwitchableFakeProvider] = []

    def create_provider(provider_config: object) -> SwitchableFakeProvider:
        provider = SwitchableFakeProvider(provider_config)
        created_providers.append(provider)
        return provider

    monkeypatch.setenv("LOCAL_API_KEY", "test-key")
    monkeypatch.setattr(coding_session_module, "create_model_provider", create_provider)
    storage = JsonlSessionStorage(tmp_path / "session.jsonl")
    settings = ProviderSettings(
        default_provider="openai",
        providers=(
            OpenAICompatibleProviderConfig(name="openai"),
            OpenAICompatibleProviderConfig(
                name="local",
                base_url="http://localhost:11434/v1",
                api_key_env="LOCAL_API_KEY",
                models=("qwen", "llama"),
                default_model="qwen",
            ),
        ),
    )
    session = await CodingSession.load(
        CodingSessionConfig(
            provider=FakeProvider([]),
            model="fake",
            system="You are Tau.",
            storage=storage,
            cwd=tmp_path,
            provider_name="openai",
            provider_settings=settings,
        )
    )

    result = session.handle_command("/provider local")

    assert result.message is not None
    assert "Current provider: local" in result.message
    assert "Current model: qwen" in result.message
    assert session.provider_name == "local"
    assert session.model == "qwen"
    assert session.available_models == ("qwen", "llama")
    assert len(created_providers) == 1

    result = session.handle_command("/provider local")

    assert result.message is not None
    assert "Current provider: local" in result.message
    assert len(created_providers) == 2

    await session.aclose()

    assert [provider.closed for provider in created_providers] == [True, True]


@pytest.mark.anyio
async def test_session_resumes_indexed_session(tmp_path: Path) -> None:
    manager = SessionManager(TauPaths(home=tmp_path / ".tau", agents_home=tmp_path / ".agents"))
    first_record = manager.create_session(cwd=tmp_path / "first", model="fake", title="First")
    second_cwd = tmp_path / "second"
    second_cwd.mkdir(parents=True)
    second_record = manager.create_session(cwd=second_cwd, model="fake", title="Second")
    first_storage = JsonlSessionStorage(first_record.path)
    second_storage = JsonlSessionStorage(second_record.path)
    provider = FakeProvider(
        [
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderResponseEndEvent(message=AssistantMessage(content="Second answer")),
            ]
        ]
    )
    session = await CodingSession.load(
        CodingSessionConfig(
            provider=provider,
            model="fake",
            system="You are Tau.",
            storage=first_storage,
            cwd=first_record.cwd,
            session_id=first_record.id,
            session_manager=manager,
        )
    )
    await second_storage.append(SessionInfoEntry(cwd=str(second_record.cwd)))
    await second_storage.append(ModelChangeEntry(model="fake"))
    await second_storage.append(MessageEntry(message=UserMessage(content="Earlier")))
    await second_storage.append(MessageEntry(message=AssistantMessage(content="Restored")))

    message = await session.resume(second_record.id)
    _events = await _collect_session_events(session.prompt("Continue."))

    assert message == f"Resumed session: {second_record.id}"
    assert session.session_id == second_record.id
    assert session.cwd == second_record.cwd
    assert [item.content for item in session.messages[:2]] == ["Earlier", "Restored"]
    assert provider.calls[0][2] == [
        UserMessage(content="Earlier"),
        AssistantMessage(content="Restored"),
        UserMessage(content="Continue."),
    ]


def test_minimal_commands_are_handled(tmp_path: Path) -> None:
    session = CodingSession(
        _config(tmp_path, FakeProvider([]), JsonlSessionStorage(tmp_path / "session.jsonl")),
        state=object(),  # type: ignore[arg-type]
        harness=object(),  # type: ignore[arg-type]
        last_parent_id=None,
    )

    assert session.handle_command("hello").handled is False
    assert session.handle_command("/help").message is not None
    assert "/help" in session.handle_command("/help").message
    assert session.handle_command("/clear").clear_requested is True
    assert session.handle_command("/exit").exit_requested is True
    assert session.handle_command("/unknown").message == "Unknown command: /unknown"
