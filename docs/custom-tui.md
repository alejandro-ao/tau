# Building a Custom TUI

Tau's Textual app is one frontend, not the agent architecture itself. A custom
TUI should plug into the same primitives that the built-in Textual frontend uses:

```text
CodingSession
  owns the coding-agent environment

AgentEvent stream
  describes assistant text, tool calls, tool results, and errors

Frontend state
  belongs to the UI implementation
```

The reusable `tau_agent` package must stay independent of terminal frameworks,
widgets, keybindings, local config paths, and slash-command UX.

## Recommended Boundary

Build custom frontends against `tau_coding.session.CodingSession`, not directly
against Textual widgets.

`CodingSession` provides the application environment:

- configured provider and model
- built-in coding tools
- session persistence
- skills and prompt templates
- project context files
- slash-command handling
- context compaction

The frontend provides the interface:

- prompt input
- transcript rendering
- command entry or command palette
- cancellation controls
- status indicators
- optional model/session pickers

## Minimal Event Loop

A custom TUI can run one user prompt by iterating the session event stream:

```python
async for event in session.prompt(user_text):
    render_event(event)
```

The event stream contains provider-neutral `AgentEvent` values from
`tau_agent.events`, including:

- `AgentStartEvent` and `AgentEndEvent`
- `MessageStartEvent`, `MessageDeltaEvent`, and `MessageEndEvent`
- `ToolExecutionStartEvent`, `ToolExecutionUpdateEvent`, and `ToolExecutionEndEvent`
- `ErrorEvent`

Do not render from provider-specific chunks. The provider layer translates model
output into Tau events so every frontend can share the same behavior.

## Restoring Visible State

When opening an existing session, initialize the visible transcript from:

```python
session.messages
```

The built-in Textual frontend uses `TuiState.load_messages()` as a reference
implementation. A custom frontend can use that class directly or implement its
own display state. Either way, restored messages should produce the same user,
assistant, tool-call, and tool-result blocks that live events produce.
`ToolResultMessage` preserves structured metadata such as edit patches, so a
custom frontend can render restored tool-result details without reading JSONL
session files directly.

## Handling Slash Commands

Slash commands are owned by `tau_coding`, not by `tau_agent`.

Before treating input as an agent prompt, call:

```python
result = session.handle_command(text)
```

If `result.handled` is true, the frontend should apply the requested UI effect
or show `result.message`. Existing result fields include:

- `exit_requested`
- `clear_requested`
- `compact_summary`
- `message`

If `result.compact_summary` is set, call:

```python
message = await session.compact(result.compact_summary)
```

Then render the returned status message.

The `/skill:<name> [request]` form is intentionally a prompt-expansion path, so
it is not consumed by normal command handling. Pass it through to
`session.prompt(...)`; `CodingSession` expands it before the agent run.

## Cancellation

Expose cancellation through:

```python
session.cancel()
```

Cancellation is a request to stop the active agent turn. The frontend should
still continue consuming events until the stream ends or reports an error, then
update its running state.

## Autocomplete and Pickers

The built-in Textual app uses:

```python
build_completion_state(
    text,
    command_registry=session.command_registry,
    skills=session.skills,
    prompt_templates=session.prompt_templates,
    model_names=session.available_models,
    provider_names=session.available_providers,
    session_ids=[record.id for record in session.session_manager.list_sessions()]
    if session.session_manager
    else (),
)
```

Custom TUIs can reuse this helper for Pi-style slash-command completion,
`/skill:` completion, and lightweight model/provider/session argument pickers.

A custom picker UI can also read the same data directly:

- `session.command_registry.list_commands()`
- `session.skills`
- `session.prompt_templates`
- `session.available_models`
- `session.available_providers`
- `session.session_manager`

## Keybindings

Keybindings and themes are frontend policy. The built-in Textual app reads optional
settings from `~/.tau/tui.json` through `tau_coding.tui.load_tui_settings()`,
but a custom TUI can ignore that file or map the same action names to its own
input and styling system.

The built-in configurable action names are:

- `cancel`
- `command_palette`
- `accept_completion`
- `completion_next`
- `completion_previous`
- `quit`

The built-in themes are `tau-dark` and `high-contrast`. They resolve to
`TuiTheme` objects used by the Textual app and widgets; custom frontends can
reuse those objects or define their own palette outside `tau_agent`.

## Session Switching

Session records are managed by `tau_coding.session_manager.SessionManager`.

For a custom session picker:

1. List records with `SessionManager.list_sessions()`.
2. Let the user choose a record id.
3. Create a new `CodingSessionConfig` with `storage=jsonl_session_storage(record.path)`.
4. Load the session with `await CodingSession.load(config)`.
5. Rebuild the visible transcript from `session.messages`.

If the frontend is already holding a `CodingSession`, it can also call:

```python
message = await session.resume(session_id)
```

Then clear and rebuild the visible transcript from `session.messages`.

Keep the picker in the frontend package. The reusable agent harness should not
know how sessions are displayed or selected.

## Reference Adapter

The built-in Textual frontend has a small adapter you can copy or reuse:

```python
state = TuiState()
state.load_messages(session.messages)
adapter = TuiEventAdapter(state)

async for event in session.prompt(user_text):
    adapter.apply(event)
    redraw(state)
```

`TuiEventAdapter` is deliberately small. It translates agent events into display
items but does not own widgets, layouts, colors, or terminal behavior.

## What Not To Depend On

Avoid custom UI dependencies on:

- private attributes of `CodingSession`
- provider-specific response chunks
- Textual widget internals unless you are extending the built-in Textual app
- JSONL session file structure when `SessionManager` or `CodingSession` can be used
- `tau_agent` internals that are not part of the event, message, tool, harness, or session primitives

## Verification Checklist

A custom TUI should prove these behaviors before it is considered compatible:

- `tau_agent` has no dependency on the frontend framework.
- Opening a session restores prior user, assistant, and tool blocks.
- Restored tool results use persisted metadata for details such as edit patches.
- Prompt submission streams assistant deltas and tool events live.
- Slash commands run through `session.handle_command()`.
- `/skill:<name>` prompts pass through to `session.prompt()`.
- Cancellation calls `session.cancel()`.
- Keybindings and themes are owned by the frontend and do not leak into `tau_agent`.
- Model/provider choices come from the session, not hardcoded UI lists.
- Session persistence is handled through `CodingSession` and `SessionManager`.
