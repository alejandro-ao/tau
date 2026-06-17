# Phase 15: Slash Command Registry

Phase 15 replaces Tau's hardcoded slash-command handling with a small registry in
`tau_coding`.

The implementation lives in:

```text
src/tau_coding/commands.py
```

## What was added

Tau now has a `CommandRegistry` that can:

- register slash commands with names, aliases, descriptions, and usage text
- list registered commands for generated help output
- parse slash-command input
- dispatch commands to handlers
- return structured command results to UI layers

The core command types are:

```python
SlashCommand
CommandContext
CommandResult
CommandRegistry
```

`CodingSession.handle_command()` now delegates to the registry instead of
hardcoding command behavior.

## Built-in commands

The default registry includes:

- `/help` — list registered commands
- `/exit` — request TUI exit
- `/clear` — clear the visible transcript only
- `/status` — show model, cwd, tools, skills, prompt templates, and session id
- `/skills` — list loaded skills
- `/skill` — explain `/skill:<name>` usage
- `/sessions` — list indexed sessions when a session manager is available
- `/resume` — request an indexed session resume
- `/model` — show the current model and note that switching is future work
- `/provider` — note that provider switching is future work

Aliases include `/q`, `/quit`, and `/?`.

## Why this belongs in `tau_coding`

Slash commands are coding-agent application behavior. They depend on resources,
sessions, skills, provider/model UX, and UI expectations.

The reusable `tau_agent` package remains independent of slash commands, Textual,
Typer, local config directories, and Tau-specific product behavior.

## TUI integration

The TUI still calls:

```python
session.handle_command(text)
```

but the returned `CommandResult` can now request more than exit behavior.

For example, `/clear` returns `clear_requested=True`. The TUI responds by clearing
only its visible display state. It does not delete durable JSONL session history.

## Skill command behavior

`/skill:<name> [request]` remains a prompt-expansion path, not a normal slash
command.

The registry intentionally returns `handled=False` for text beginning with
`/skill:` so `CodingSession.prompt()` can expand the skill before sending the
prompt to the model.

The plain `/skill` command exists only to show usage guidance.

## Future use

This registry is the foundation for later phases:

- TUI slash-command autocomplete can read command metadata from the registry.
- Extensions can eventually contribute commands.
- A future command palette can show the same command metadata.

## Tests

The phase is covered by:

```text
tests/test_commands.py
tests/test_coding_session.py
tests/test_tui_app.py
```

The tests verify:

- command parsing and dispatch
- generated help output
- exit and clear control flags
- status and skills output
- `/skill:<name>` passthrough behavior
- indexed session listing
- structured `/resume <session-id>` requests
- TUI handling for `/clear`
