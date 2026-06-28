---
title: Providers & models
description: Connect OpenAI, Anthropic, Codex, OpenRouter, Hugging Face, or a local model — and switch models any time.
---

A **provider** is the service hosting AI models; a **model** is the specific one
you talk to. Tau ships with several built-in providers and lets you add your own
OpenAI-compatible endpoints (including local models).

## The fastest setup: an API key

Set the provider's API key in your environment and you're ready:

```bash
export OPENAI_API_KEY="sk-..."          # OpenAI
export ANTHROPIC_API_KEY="sk-ant-..."   # Anthropic
```

Built-in providers include **OpenAI**, **Anthropic**, **OpenAI Codex**
(subscription), **OpenRouter**, and **Hugging Face**. Once the matching key is
present, the provider is usable.

Check what's configured and how each provider will authenticate:

```bash
tau providers
```

## Logging in from inside Tau

Instead of env vars you can store credentials with Tau:

```text
/login              # list built-in providers
/login openai       # save an API key
/login openai-codex # authenticate a Codex/ChatGPT subscription via OAuth
/logout [provider]  # remove a saved credential
```

Credentials saved this way live in `~/.tau/credentials.json` (private
permissions) and take precedence over environment variables. `/logout` only
edits saved credentials — it never touches your env vars or `providers.json`.

:::note[Codex subscription]
`/login openai-codex` opens the OpenAI OAuth flow, listens for the local
callback, and also accepts a pasted redirect URL or code. It refreshes expired
access tokens automatically. It's separate from the API-key `openai` provider.
:::

## Choosing and switching models

- **`/model`** — open the picker (lists models across configured providers;
  choosing one can switch the active provider too).
- **`tau -m <model>`** or **`tau --provider <name> -m <model>`** — choose at
  launch.
- **Ctrl+P** — cycle your *scoped* (favorite) models without opening the picker.
  Build the list with `/scoped-models`, or press `Space` on a model in the
  `/model` picker.

## Adding a custom / local provider

Any OpenAI-compatible endpoint works — including local servers like Ollama or
llama.cpp. Register one with `tau setup`:

```bash
tau --provider local \
  --base-url http://localhost:11434/v1 \
  --api-key-env LOCAL_API_KEY \
  --model qwen \
  setup
```

This writes an entry to `~/.tau/providers.json` and (by default) makes it the
default provider. Run it with:

```bash
tau --provider local
tau --provider local "summarize this project"   # TUI with an initial prompt
tau --provider local -p "summarize this project" # one-shot print mode
```

Provider entries support `headers`, `timeout_seconds`, `max_retries`, and
`max_retry_delay_seconds`. For the full JSON shape (and `thinking_levels` for
custom models), see [Configuration](../reference/configuration.md#providers).

:::tip[Org billing example]
Hugging Face organization billing is just a header on the provider entry:

```json
{ "headers": { "X-HF-Bill-To": "my-org" } }
```
:::

## How credentials are resolved

For a given provider, Tau uses, in order: a stored credential in
`~/.tau/credentials.json`, then the environment variable named by the provider's
`api_key_env`. Built-in providers added via `/login` read their saved credential;
custom/env providers read the env var.
