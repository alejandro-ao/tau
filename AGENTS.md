# Tau Agent Instructions

Tau is a Python implementation of Pi's minimalist coding-agent harness architecture. The goal is to develop it incrementally, with each phase clearly documented and tested.

## Project Roadmap

The implementation roadmap is tracked in GitHub issue #1:

- https://github.com/alejandro-ao/tau/issues/1

Use that issue as the primary reference for phase ordering and architectural intent.

## Architecture Principles

Preserve Pi's core separation of concerns:

```text
AgentHarness = reusable agent brain
AgentSession = coding-agent environment
TUI = one possible frontend
```

Tau should be organized around these layers:

```text
tau_ai      provider/model streaming layer
tau_agent   portable agent harness, loop, tools, events, sessions
tau_coding  CLI app, resources, skills, extensions, commands, TUI integration
```

Keep the core agent package independent of CLI, Textual, Rich rendering, session file locations, and application-specific resource loading.

## TUI Direction

Use Textual for the full interactive TUI, but only behind an adapter boundary. The agent harness should emit events; UI layers should consume those events.

Early phases should prioritize:

1. print-mode CLI
2. Rich renderers
3. Textual interactive app

Do not let Textual become a dependency of the reusable agent harness.

## Development Workflow

- Work in small, documented phases.
- Keep changes aligned with the roadmap issue.
- Add or update docs when introducing architectural concepts.
- Add tests for behavior before expanding features.
- Run tests and Python commands through `uv` (for example, `uv run pytest` or `uv run python ...`) so they use the project environment.
- Prefer simple, explicit abstractions over framework-heavy designs.
- Keep commits atomic: one coherent feature, fix, docs update, refactor, or cleanup per commit.

## Python Guidelines

- Target the Python version declared in `pyproject.toml`.
- Prefer typed dataclasses or schema models for core messages, events, tools, and sessions.
- Keep async boundaries explicit.
- Use fake providers and fake tools for deterministic agent-loop tests.
- Avoid provider-specific assumptions in core agent code.

## Documentation Expectations

Each substantial phase should leave behind beginner-friendly notes under `dev-notes/` (build journals, design docs, ADRs), explaining:

- what was added
- why it exists
- how it maps to Pi's design
- how to test or use it

When a phase adds or changes user-facing behavior, also update the published docs
under `website/src/content/docs/` (the "Use Tau" guides and reference).

