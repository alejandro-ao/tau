"""Persistent coding-session wrapper built on AgentHarness."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from tau_agent import AgentEvent, AgentHarness, AgentHarnessConfig
from tau_agent.messages import AgentMessage
from tau_agent.session import (
    CompactionEntry,
    JsonlSessionStorage,
    LeafEntry,
    MessageEntry,
    ModelChangeEntry,
    SessionInfoEntry,
    SessionState,
    SessionStorage,
)
from tau_agent.tools import AgentTool
from tau_ai import ModelProvider
from tau_coding.commands import CommandRegistry, CommandResult, create_default_command_registry
from tau_coding.context import discover_project_context_with_diagnostics
from tau_coding.context_window import estimate_context_tokens, summarize_messages_for_compaction
from tau_coding.paths import TauPaths
from tau_coding.prompt_templates import (
    PromptTemplate,
    load_prompt_templates_with_diagnostics,
)
from tau_coding.provider_config import (
    ProviderConfigError,
    ProviderSettings,
    load_provider_settings,
)
from tau_coding.provider_runtime import ClosableModelProvider, create_model_provider
from tau_coding.resources import (
    ResourceDiagnostic,
    ResourceError,
    TauResourcePaths,
    resource_paths_with_cwd,
)
from tau_coding.session_manager import SessionManager
from tau_coding.skills import Skill, expand_skill_command, load_skills_with_diagnostics
from tau_coding.system_prompt import (
    BuildSystemPromptOptions,
    ProjectContextFile,
    build_system_prompt,
)
from tau_coding.tools import create_coding_tools


@dataclass(frozen=True, slots=True)
class SessionResources:
    """Tau-owned resources loaded around a coding session."""

    skills: tuple[Skill, ...]
    prompt_templates: tuple[PromptTemplate, ...]
    context_files: tuple[ProjectContextFile, ...]
    diagnostics: tuple[ResourceDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class CodingSessionConfig:
    """Configuration for a persistent coding session."""

    provider: ModelProvider
    model: str
    storage: SessionStorage
    cwd: Path
    system: str | None = None
    custom_system_prompt: str | None = None
    append_system_prompt: str | None = None
    context_files: tuple[ProjectContextFile, ...] = ()
    tools: list[AgentTool] | None = None
    resource_paths: TauResourcePaths | None = None
    session_id: str | None = None
    session_manager: SessionManager | None = None
    command_registry: CommandRegistry | None = None
    provider_name: str = "openai"
    provider_settings: ProviderSettings | None = None
    auto_compact_token_threshold: int | None = None


class CodingSession:
    """Tau's coding-agent environment wrapper.

    `AgentHarness` owns the in-memory agent brain. `CodingSession` owns the
    coding-session environment around it: durable session entries, default coding
    tools, and a small command seam for later phases.
    """

    def __init__(
        self,
        config: CodingSessionConfig,
        *,
        state: SessionState,
        harness: AgentHarness,
        last_parent_id: str | None,
        skills: tuple[Skill, ...] = (),
        prompt_templates: tuple[PromptTemplate, ...] = (),
        context_files: tuple[ProjectContextFile, ...] = (),
        resource_diagnostics: tuple[ResourceDiagnostic, ...] = (),
        command_registry: CommandRegistry | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._harness = harness
        self._last_parent_id = last_parent_id
        self._skills = skills
        self._prompt_templates = prompt_templates
        self._context_files = context_files
        self._resource_diagnostics = resource_diagnostics
        self._command_registry = command_registry or create_default_command_registry()
        self._provider_name = config.provider_name
        self._provider_settings = config.provider_settings
        self._resource_paths = resource_paths_with_cwd(config.resource_paths, config.cwd)
        self._auto_compact_token_threshold = config.auto_compact_token_threshold
        self._owned_providers: list[ClosableModelProvider] = []

    @classmethod
    async def load(cls, config: CodingSessionConfig) -> CodingSession:
        """Load a coding session from append-only storage."""
        entries = await config.storage.read_all()
        if not entries:
            info = SessionInfoEntry(cwd=str(config.cwd))
            model = ModelChangeEntry(parent_id=info.id, model=config.model)
            await config.storage.append(info)
            await config.storage.append(model)
            entries = [info, model]

        linear_state = SessionState.from_entries(entries)
        state = (
            SessionState.from_entries(entries, leaf_id=linear_state.active_leaf_id)
            if linear_state.active_leaf_id is not None
            else linear_state
        )
        tools = config.tools if config.tools is not None else create_coding_tools(cwd=config.cwd)
        resource_paths = resource_paths_with_cwd(config.resource_paths, config.cwd)
        resources = _load_session_resources(resource_paths, config.context_files)
        system = (
            config.system
            if config.system is not None
            else build_system_prompt(
                BuildSystemPromptOptions(
                    cwd=config.cwd,
                    tools=tools,
                    skills=resources.skills,
                    custom_prompt=config.custom_system_prompt,
                    append_system_prompt=config.append_system_prompt,
                    context_files=resources.context_files,
                )
            )
        )
        harness = AgentHarness(
            AgentHarnessConfig(
                provider=config.provider,
                model=state.model or config.model,
                system=system,
                tools=tools,
            ),
            messages=state.messages,
        )
        return cls(
            config,
            state=state,
            harness=harness,
            last_parent_id=_last_parent_id_from_state(state),
            skills=resources.skills,
            prompt_templates=resources.prompt_templates,
            context_files=resources.context_files,
            resource_diagnostics=resources.diagnostics,
            command_registry=config.command_registry,
        )

    @property
    def cwd(self) -> Path:
        """Return the session working directory."""
        return self._config.cwd

    @property
    def model(self) -> str:
        """Return the active model for this session."""
        return self._harness.config.model

    @property
    def provider_name(self) -> str:
        """Return the active provider name."""
        return self._provider_name

    @property
    def available_providers(self) -> tuple[str, ...]:
        """Return configured provider names."""
        if self._provider_settings is None:
            return (self._provider_name,)
        return tuple(provider.name for provider in self._provider_settings.providers)

    @property
    def available_models(self) -> tuple[str, ...]:
        """Return configured model names for the active provider."""
        if self._provider_settings is None:
            return (self.model,)
        try:
            provider = self._provider_settings.get_provider(self._provider_name)
        except ProviderConfigError:
            return (self.model,)
        return provider.models

    @property
    def tools(self) -> tuple[AgentTool, ...]:
        """Return the tools available to the agent."""
        return tuple(self._harness.config.tools)

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        """Return the restored/current transcript."""
        return self._harness.messages

    @property
    def state(self) -> SessionState:
        """Return the last replayed durable session state."""
        return self._state

    @property
    def storage(self) -> SessionStorage:
        """Return the backing session storage."""
        return self._config.storage

    @property
    def skills(self) -> tuple[Skill, ...]:
        """Return loaded skills."""
        return self._skills

    @property
    def prompt_templates(self) -> tuple[PromptTemplate, ...]:
        """Return loaded prompt templates."""
        return self._prompt_templates

    @property
    def context_files(self) -> tuple[ProjectContextFile, ...]:
        """Return active project context files."""
        return self._context_files

    @property
    def context_token_estimate(self) -> int:
        """Return a rough token estimate for the active provider context."""
        return estimate_context_tokens(
            system=self._harness.config.system,
            messages=self._harness.messages,
            tools=tuple(self._harness.config.tools),
        )

    @property
    def auto_compact_token_threshold(self) -> int | None:
        """Return the configured automatic compaction threshold, if any."""
        return self._auto_compact_token_threshold

    @property
    def command_registry(self) -> CommandRegistry:
        """Return the slash-command registry used by this session."""
        return self._command_registry

    @property
    def resource_diagnostics(self) -> tuple[ResourceDiagnostic, ...]:
        """Return non-fatal resource discovery diagnostics."""
        return self._resource_diagnostics

    @property
    def session_id(self) -> str | None:
        """Return this session's manager id, if indexed."""
        return self._config.session_id

    @property
    def session_manager(self) -> SessionManager | None:
        """Return the session manager, if available."""
        return self._config.session_manager

    def cancel(self) -> None:
        """Cancel the currently running agent turn, if any."""
        self._harness.cancel()

    def set_model(self, model: str) -> None:
        """Switch the active model for future turns in this process."""
        self._harness.config.model = model
        if self._config.session_id is not None and self._config.session_manager is not None:
            self._config.session_manager.touch_session(self._config.session_id, model=model)

    def set_provider(self, provider_name: str) -> None:
        """Switch the active provider and reset to that provider's default model."""
        if self._provider_settings is None:
            raise ProviderConfigError("Provider settings are not available for this session")

        provider_config = self._provider_settings.get_provider(provider_name)
        try:
            provider = create_model_provider(provider_config)
        except RuntimeError as exc:
            raise ProviderConfigError(str(exc)) from exc
        self._owned_providers.append(provider)
        self._harness.config.provider = provider
        self._provider_name = provider_config.name
        self.set_model(provider_config.default_model)

    def reload(self) -> None:
        """Reload Tau-owned resources and provider settings for future turns."""
        resources = _load_session_resources(self._resource_paths, self._config.context_files)
        self._skills = resources.skills
        self._prompt_templates = resources.prompt_templates
        self._context_files = resources.context_files
        self._resource_diagnostics = resources.diagnostics
        if self._provider_settings is not None:
            self._provider_settings = load_provider_settings()
        if self._config.system is None:
            self._harness.config.system = build_system_prompt(
                BuildSystemPromptOptions(
                    cwd=self._config.cwd,
                    tools=self._harness.config.tools,
                    skills=self._skills,
                    custom_prompt=self._config.custom_system_prompt,
                    append_system_prompt=self._config.append_system_prompt,
                    context_files=self._context_files,
                )
            )

    async def resume(self, session_id: str) -> str:
        """Replace this session's active state with another indexed session."""
        manager = self._config.session_manager
        if manager is None:
            raise ValueError("Session manager is not available")
        record = manager.get_session(session_id)
        if record is None:
            raise ValueError(f"Unknown session: {session_id}")

        replacement = await type(self).load(
            CodingSessionConfig(
                provider=self._harness.config.provider,
                model=record.model or self.model,
                cwd=record.cwd,
                storage=jsonl_session_storage(record.path),
                system=self._config.system,
                custom_system_prompt=self._config.custom_system_prompt,
                append_system_prompt=self._config.append_system_prompt,
                context_files=self._config.context_files,
                resource_paths=self._config.resource_paths,
                session_id=record.id,
                session_manager=manager,
                command_registry=self._command_registry,
                provider_name=self._provider_name,
                provider_settings=self._provider_settings,
                auto_compact_token_threshold=self._auto_compact_token_threshold,
            )
        )
        self._config = replacement._config
        self._state = replacement._state
        self._harness = replacement._harness
        self._last_parent_id = replacement._last_parent_id
        self._skills = replacement._skills
        self._prompt_templates = replacement._prompt_templates
        self._context_files = replacement._context_files
        self._resource_diagnostics = replacement._resource_diagnostics
        self._command_registry = replacement._command_registry
        self._provider_name = replacement._provider_name
        self._provider_settings = replacement._provider_settings
        self._resource_paths = replacement._resource_paths
        self._auto_compact_token_threshold = replacement._auto_compact_token_threshold
        return f"Resumed session: {record.id}"

    async def compact(self, summary: str) -> str:
        """Append a manual compaction summary and rebuild active context."""
        normalized_summary = summary.strip()
        if not normalized_summary:
            raise ValueError("Compaction summary cannot be empty")
        compaction = await self._append_compaction(normalized_summary)
        return f"Compacted {len(compaction.replaces_entry_ids)} context entries."

    async def aclose(self) -> None:
        """Close runtime providers created by this coding session."""
        for provider in self._owned_providers:
            await provider.aclose()
        self._owned_providers.clear()

    def handle_command(self, text: str) -> CommandResult:
        """Handle minimal coding-session slash commands.

        This is intentionally tiny. Later phases can replace it with a full Pi-like
        command registry without changing the persistence boundary.
        """
        return self._command_registry.execute(self, text)

    def expand_prompt_text(self, text: str) -> str:
        """Expand prompt text using loaded markdown resources."""
        expanded_skill = expand_skill_command(text, self._skills)
        return expanded_skill if expanded_skill is not None else text

    async def prompt(self, content: str) -> AsyncIterator[AgentEvent]:
        """Append a user prompt, run the agent, and persist new messages."""
        await self._maybe_auto_compact()
        try:
            expanded_content = self.expand_prompt_text(content)
        except ResourceError:
            raise
        before_count = len(self._harness.messages)
        async for event in self._harness.prompt(expanded_content):
            yield event
        await self._persist_new_messages(before_count)

    async def continue_(self) -> AsyncIterator[AgentEvent]:
        """Continue the agent from restored state and persist new messages."""
        before_count = len(self._harness.messages)
        async for event in self._harness.continue_():
            yield event
        await self._persist_new_messages(before_count)

    async def _persist_new_messages(self, before_count: int) -> None:
        new_messages = self._harness.messages[before_count:]
        last_message_entry_id: str | None = None
        for message in new_messages:
            entry = MessageEntry(parent_id=self._last_parent_id, message=message)
            await self._config.storage.append(entry)
            self._last_parent_id = entry.id
            last_message_entry_id = entry.id

        if last_message_entry_id is not None:
            leaf = LeafEntry(parent_id=last_message_entry_id, entry_id=last_message_entry_id)
            await self._config.storage.append(leaf)

        entries = await self._config.storage.read_all()
        self._state = SessionState.from_entries(entries)
        if self._config.session_id is not None and self._config.session_manager is not None:
            self._config.session_manager.touch_session(self._config.session_id, model=self.model)

    async def _maybe_auto_compact(self) -> None:
        threshold = self._auto_compact_token_threshold
        if threshold is None or threshold <= 0:
            return
        if len(self._state.context_entry_ids) < 2:
            return
        if self.context_token_estimate <= threshold:
            return
        summary = summarize_messages_for_compaction(self._state.messages)
        await self._append_compaction(summary)

    async def _append_compaction(self, summary: str) -> CompactionEntry:
        if not self._state.context_entry_ids:
            raise ValueError("No active context messages to compact")

        compaction = CompactionEntry(
            parent_id=self._last_parent_id,
            summary=summary,
            replaces_entry_ids=list(self._state.context_entry_ids),
        )
        await self._config.storage.append(compaction)
        leaf = LeafEntry(parent_id=compaction.id, entry_id=compaction.id)
        await self._config.storage.append(leaf)
        self._last_parent_id = compaction.id

        entries = await self._config.storage.read_all()
        self._state = SessionState.from_entries(entries, leaf_id=compaction.id)
        self._harness.replace_messages(self._state.messages)
        if self._config.session_id is not None and self._config.session_manager is not None:
            self._config.session_manager.touch_session(self._config.session_id, model=self.model)
        return compaction


def _last_parent_id_from_state(state: SessionState) -> str | None:
    if state.active_leaf_id is not None:
        return state.active_leaf_id
    if state.entries:
        return state.entries[-1].id
    return None


def _load_session_resources(
    resource_paths: TauResourcePaths,
    explicit_context_files: tuple[ProjectContextFile, ...],
) -> SessionResources:
    loaded_skills, skill_diagnostics = load_skills_with_diagnostics(resource_paths)
    loaded_prompt_templates, prompt_diagnostics = load_prompt_templates_with_diagnostics(
        resource_paths
    )
    discovered_context, context_diagnostics = discover_project_context_with_diagnostics(
        resource_paths
    )
    return SessionResources(
        skills=tuple(loaded_skills),
        prompt_templates=tuple(loaded_prompt_templates),
        context_files=_merge_context_files(explicit_context_files, discovered_context),
        diagnostics=tuple([*skill_diagnostics, *prompt_diagnostics, *context_diagnostics]),
    )


def _merge_context_files(
    explicit: tuple[ProjectContextFile, ...],
    discovered: tuple[ProjectContextFile, ...],
) -> tuple[ProjectContextFile, ...]:
    merged: list[ProjectContextFile] = []
    seen: set[str] = set()
    for context_file in (*explicit, *discovered):
        if context_file.path in seen:
            continue
        seen.add(context_file.path)
        merged.append(context_file)
    return tuple(merged)


def default_session_path(cwd: Path) -> Path:
    """Return Tau's default user-home session path for a project cwd."""
    return TauPaths().default_session_path(cwd)


def jsonl_session_storage(path: str | Path) -> JsonlSessionStorage:
    """Convenience factory for local JSONL coding-session storage."""
    return JsonlSessionStorage(path)
