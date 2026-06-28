<p align="center">
  <img src="docs/assets/tau-header.svg" alt="Tau — a Python coding-agent harness inspired by Pi" width="100%" />
</p>

<p align="center">
  <strong>A minimalist coding-agent harness in Python, inspired by Pi and built as a teaching project.</strong>
</p>

<p align="center">
  <a href="https://alejandro-ao.github.io/tau/">Documentation</a>
  ·
  <a href="docs/getting-started.md">Getting started</a>
  ·
  <a href="docs/architecture/index.md">Architecture notes</a>
  ·
  <a href="https://github.com/alejandro-ao/tau/issues/1">Roadmap</a>
</p>

---

## What is Tau?

Tau is a Python implementation of the minimalist coding-agent harness architecture
popularized by **Pi**. It is both:

1. a usable terminal coding agent, and
2. a readable, phase-by-phase reference implementation for learning how coding
   agents are assembled.

The project intentionally keeps the core pieces small and explicit: model
providers stream events, an agent loop turns those events into tool execution and
transcript updates, a reusable harness owns state, and the coding app adds local
files, shell tools, sessions, skills, commands, and terminal frontends.

```text
tau_ai       provider/model streaming layer
tau_agent    portable agent harness, loop, tools, events, sessions
tau_coding   CLI app, resources, skills, commands, sessions, UI integration
```

The central design boundary is:

```text
AgentHarness = reusable agent brain
AgentSession = coding-agent environment
TUI          = one possible frontend
```

Tau should make the architecture legible. If you want to understand how a coding
agent works without starting from a large production codebase, this repository is
for you.

## Why Tau exists

Tau is being built as an effort to teach how to create coding agents.

The philosophy is:

- **Small layers beat magic.** Each package has a clear job and can be explained
  independently.
- **Events are the contract.** The agent harness emits provider-neutral events;
  renderers and TUIs consume them.
- **The core stays portable.** `tau_agent` does not depend on Textual, Rich,
  shell config directories, slash commands, or application-specific resources.
- **Tools are ordinary typed functions.** File and shell capabilities are exposed
  through explicit schemas and deterministic result objects.
- **Sessions are durable and inspectable.** Tau stores append-only JSONL session
  transcripts under `~/.tau/sessions/`.
- **Documentation follows implementation.** The project is developed in small,
  documented phases so readers can trace how the system grows.

Pi is the design inspiration; Tau is the Python learning path.

## Current capabilities

Tau currently includes:

- an installable `tau` console command
- a Textual interactive TUI
- non-interactive print mode for one-shot prompts
- OpenAI-compatible, Anthropic, OpenAI Codex subscription, OpenRouter, and
  Hugging Face provider support through provider configuration
- provider retry/backoff events and thinking/reasoning deltas
- built-in local coding tools: `read`, `write`, `edit`, and `bash`
- durable per-project sessions and session resume
- session tree branching and HTML/JSONL export
- slash commands, model picker, theme picker, and autocomplete
- skills, prompt templates, and `AGENTS.md` project-context discovery
- context accounting, manual compaction, and optional automatic compaction
- Rich/plain/json/transcript rendering paths for print-mode output
- a deterministic fake provider used by tests

Tau is still evolving. Expect the command surface and internals to improve as the
roadmap progresses.

## Install

Tau targets the Python version declared in `pyproject.toml` and uses
[`uv`](https://docs.astral.sh/uv/) for the recommended workflow.

Install from GitHub:

```bash
uv tool install git+https://github.com/alejandro-ao/tau.git
tau --version
```

Install from a local checkout:

```bash
git clone https://github.com/alejandro-ao/tau.git
cd tau
uv tool install --editable .
tau --version
```

For development:

```bash
uv sync --dev
uv run tau --version
```

## First run

Start the interactive terminal UI:

```bash
tau
```

Start the TUI and submit the first prompt immediately:

```bash
tau "explain this repository"
```

Run a one-shot non-interactive prompt:

```bash
tau -p "summarize the architecture"
```

Choose a configured provider/model:

```bash
tau --provider openai --model gpt-4.1 "review this codebase"
tau --provider local --model qwen -p "list the main modules"
```

Use another working directory for coding tools:

```bash
tau --cwd /path/to/project "find the CLI entry point"
```

## Configure a model provider

The easiest path is from inside the TUI:

```text
/login
/login openai
/login openai-codex
/logout
/logout openai
/model
```

`/login` can save API-key credentials for built-in providers or authenticate an
OpenAI Codex subscription account with OAuth. Credentials are stored in
`~/.tau/credentials.json` with private file permissions. Provider metadata lives
in `~/.tau/providers.json`. `/logout` removes only credentials saved in Tau's
`credentials.json`; environment variables and provider configuration are
unchanged.

You can also configure an OpenAI-compatible provider from the CLI:

```bash
tau --provider local \
  --base-url http://localhost:11434/v1 \
  --api-key-env LOCAL_API_KEY \
  --model qwen \
  setup
```

Then run:

```bash
export LOCAL_API_KEY="..."
tau --provider local
```

Useful provider commands:

```bash
tau providers
```

See [docs/providers.md](docs/providers.md) and
[docs/configuration.md](docs/configuration.md) for details.

## Working in the TUI

Common slash commands:

| Command | Purpose |
| --- | --- |
| `/login [provider]` | Save or refresh provider credentials. |
| `/logout [provider]` | Remove Tau-saved provider credentials. |
| `/model` | Choose the active provider/model. |
| `/scoped-models` | Pick models available for quick cycling. |
| `/session` | Show session and context information. |
| `/resume [session-id]` | Resume a previous session. |
| `/tree` | Branch from a previous session entry. |
| `/name <new name>` | Rename the current session. |
| `/compact <summary>` | Replace active context with a manual summary. |
| `/export [--format html\|jsonl] [destination]` | Export the current session. |
| `/reload` | Reload local resources and project context. |
| `/theme [name]` | Show or set the TUI theme. |
| `/hotkeys` | Show common keyboard shortcuts. |
| `/quit` | Exit the session. |

Important TUI behavior:

- Click anywhere in the main TUI to return keyboard focus to the prompt input.

Common shortcuts:

| Shortcut | Action |
| --- | --- |
| `Enter` | Submit prompt. |
| `Shift+Enter` | Insert newline. |
| `Alt+Enter` | Queue a follow-up while the agent is running. |
| `Esc` | Cancel active run. |
| `Ctrl+K` | Open slash-command completions. |
| `Ctrl+R` | Open session picker. |
| `Shift+Tab` | Cycle thinking mode. |
| `Ctrl+T` | Toggle thinking-token display. |
| `Ctrl+O` | Collapse or expand tool output. |
| `Ctrl+P` | Cycle scoped models. |
| `Ctrl+D` | Quit. |

## Sessions, resources, and files

Tau stores durable app state in your home directory:

```text
~/.tau/providers.json       provider metadata
~/.tau/credentials.json     saved API keys and OAuth credentials
~/.tau/tui.json             TUI theme/keybinding settings
~/.tau/sessions/            append-only JSONL session transcripts
~/.tau/skills/              user Tau skills
~/.tau/prompts/             user prompt templates
~/.tau/AGENTS.md            user Tau instructions
```

Tau also reads user-level `.agents` resources and project-local resources from
the active working directory, including `AGENTS.md`, `.tau/`, and `.agents/`
locations. This lets a project teach Tau how it should behave without changing
Tau's core harness.

## Use Tau as a library

Tau's reusable brain lives in `tau_agent`:

```python
from tau_agent import AgentHarness, AgentHarnessConfig

harness = AgentHarness(
    AgentHarnessConfig(
        provider=provider,
        model="my-model",
        system="You are a helpful coding agent.",
        tools=tools,
    )
)

async for event in harness.prompt("Explain this package"):
    print(event)
```

That harness is deliberately independent of the CLI/TUI. You can build another
frontend by consuming the same event stream.

## Development

Set up the repository:

```bash
uv sync --dev
```

Run checks:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

Run Tau locally:

```bash
uv run tau
uv run tau -p "explain this repo"
```

Run the documentation site (Astro Starlight, in `website/`):

```bash
cd website
bun install
bun run dev
```

Then open `http://localhost:4321/tau/`. Build the static site with `bun run build` (output in `website/dist/`).

## Documentation

The user-facing docs are published at <https://alejandro-ao.github.io/tau/>.
Their source lives in `website/src/content/docs/`:

- [What is Tau?](website/src/content/docs/what-is-tau.md)
- [Quickstart](website/src/content/docs/quickstart.md)
- [Core concepts](website/src/content/docs/concepts.md)
- Guides — [the TUI](website/src/content/docs/guides/tui.md),
  [sessions](website/src/content/docs/guides/sessions.md),
  [providers & models](website/src/content/docs/guides/providers-and-models.md),
  [skills & prompts](website/src/content/docs/guides/skills-and-prompts.md),
  [context](website/src/content/docs/guides/context.md)
- Reference — [CLI](website/src/content/docs/reference/cli.md),
  [slash commands](website/src/content/docs/reference/slash-commands.md),
  [keybindings](website/src/content/docs/reference/keybindings.md),
  [configuration](website/src/content/docs/reference/configuration.md),
  [tools](website/src/content/docs/reference/tools.md)
- How Tau works — [architecture](website/src/content/docs/internals/architecture.md),
  [the agent loop](website/src/content/docs/internals/agent-loop.md)

Contributor build journals (phase notes, design docs, ADRs) live in
[`dev-notes/`](dev-notes/README.md) and are intentionally not published.

## Project status

Tau is under active development. The implementation roadmap is tracked in
[GitHub issue #1](https://github.com/alejandro-ao/tau/issues/1), and the notes
under [`dev-notes/architecture/`](dev-notes/architecture/) record the completed phases.

The goal is not to hide complexity. The goal is to make each part of a coding
agent visible, testable, and understandable.
