# Phase 23: Advanced TUI and Product Polish

Phase 23 improves the Textual frontend while keeping the reusable agent harness
independent of UI concerns.

The boundary remains:

```text
CodingSession emits AgentEvent values
        ↓
TuiEventAdapter updates TuiState
        ↓
Textual widgets render the transcript and controls
```

## Current polish slices

Live tool results now render successful output in the transcript, matching
restored session history. This keeps tool-call blocks useful during an active
run instead of hiding successful command output until the session is reloaded.

The TUI also has a command-palette entry point. Pressing `Ctrl+K` focuses the
prompt, inserts `/`, and shows all slash-command completions using the existing
completion engine. Selection still uses the same `Tab`, `Up`, and `Down`
bindings as ordinary slash-command autocomplete.

The same completion engine now suggests available values for `/model` and
`/provider` arguments. This gives the prompt a lightweight picker for model and
provider switching without adding a separate modal UI.

The prompt also suggests indexed session ids for `/resume <session-id>`, giving
the TUI a lightweight session picker path through the same completion UI.
Submitting the command reloads the selected session through `CodingSession` and
rebuilds the visible transcript in place.

The frontend boundary is now documented in [Building a Custom TUI](../custom-tui.md).
That guide describes how another terminal UI can consume `CodingSession`,
`AgentEvent`, `TuiState`, and `TuiEventAdapter` without coupling to Textual
internals.

## Boundaries

These changes live in `tau_coding.tui`. The command registry still owns command
metadata, and `tau_agent` remains unaware of Textual, keybindings, slash
commands, and rendering.

## Still deferred

The larger Phase 23 roadmap still includes a richer modal session picker, a
diff viewer, configurable keybindings, and deeper theme polish. Those should
remain separate atomic slices.

## Tests

Coverage lives in:

```text
tests/test_tui_adapter.py
tests/test_tui_app.py
```
