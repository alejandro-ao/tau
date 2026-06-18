# Phase 20.2: Thinking Mode Controls

Phase 20.2 makes thinking mode an explicit Tau coding-session setting and adds
a TUI control for changing it.

## What Was Added

`tau_coding.thinking` defines Tau's supported thinking modes:

```text
off
minimal
low
medium
high
xhigh
```

The default is `medium`, matching Pi's default reasoning-depth preference. Tau
validates the visible controls against provider/model capabilities and passes
OpenAI-compatible `reasoning_effort` when a configured provider declares support.
Unsupported models show thinking controls as unavailable instead of presenting a
mode that Tau cannot safely send.

## Session Persistence

New sessions append an initial `thinking_level_change` entry after the initial
model entry. Explicit changes append another `thinking_level_change` entry and a
leaf pointer, so resume reconstructs the active thinking mode from the session
tree.

`CodingSession` exposes:

```python
session.thinking_level
session.available_thinking_levels
await session.set_thinking_level("high")
await session.cycle_thinking_level()
```

This keeps thinking state in `tau_coding`, while `tau_agent.session` remains the
portable replay layer that knows how to reconstruct `ThinkingLevelChangeEntry`
values.

## Commands And TUI

The shared command registry includes:

```text
/thinking
/thinking high
```

The Textual TUI binds thinking cycling to `Shift-Tab` by default. The key is
configurable in `~/.tau/tui.json`:

```json
{
  "keybindings": {
    "thinking_cycle": "f3"
  }
}
```

The sidebar and compact session line now read `session.thinking_level` directly,
with a fallback for simple custom session adapters. When the active provider or
model has no thinking capability metadata, the TUI shows the control as
unavailable.

## Provider Capabilities

Provider settings may declare thinking support with:

```json
{
  "thinking_levels": ["off", "low", "medium", "high"],
  "thinking_models": ["gpt-5.5"],
  "thinking_default": "medium",
  "thinking_parameter": "reasoning_effort"
}
```

`thinking_models` is optional. If it is omitted, the declared levels apply to
all models for that provider. Tau's built-in direct OpenAI provider declares
known GPT-5 reasoning models and sends `reasoning_effort` through the
OpenAI-compatible chat-completions adapter. OpenRouter and Hugging Face remain
disabled unless an OpenAI-compatible provider config explicitly opts in.
Anthropic and Codex-subscription thinking controls are rejected until their
adapters implement a provider-specific mapping.

## Boundary

Thinking controls remain outside `tau_agent` provider execution. This phase adds
OpenAI-compatible reasoning-effort payloads and model capability clamping in
`tau_ai`/`tau_coding`, but it does not render thinking traces or expose hidden
provider reasoning content in the transcript.

## Tests

The phase is covered by:

```text
tests/test_thinking.py
tests/test_commands.py
tests/test_coding_session.py
tests/test_tui_config.py
tests/test_tui_app.py
```
