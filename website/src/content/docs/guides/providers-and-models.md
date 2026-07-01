---
title: Providers & models
description: Connect OpenAI, Anthropic, Codex, OpenRouter, Hugging Face, or a local model — and switch models any time.
---

A **provider** is the service hosting AI models; a **model** is the specific one
you talk to. Tau ships with several built-in providers and lets you add your own
OpenAI-compatible endpoints (including local models).

## The fastest setup: `/login`

Start Tau and use `/login` to connect a built-in provider:

```bash
tau
```

```text
/login              # choose a built-in provider
/login openai       # save an OpenAI API key
/login openai-codex # authenticate a Codex/ChatGPT subscription via OAuth
```

Built-in providers include **OpenAI**, **Anthropic**, **OpenAI Codex**
(subscription), **OpenRouter**, and **Hugging Face**. Credentials saved this way
live in `~/.tau/credentials.json` (private permissions).

Check what's configured and how each provider will authenticate:

```bash
tau providers
```

## Managing saved credentials

Use these slash commands inside Tau:

```text
/login [provider]   # add or refresh a saved credential
/logout [provider]  # remove a saved credential
```

Saved credentials take precedence over environment variables. `/logout` only
edits saved credentials — it never touches your environment or `providers.json`.

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

Any OpenAI-compatible endpoint works — including local servers like
[llama.cpp](https://github.com/ggml-org/llama.cpp) or Ollama. The most common
setup is **llama.cpp**'s `llama serve`, which speaks the OpenAI
chat-completions API directly:

```bash
llama serve -hf ggml-org/Qwen3.6-35B-A3B-GGUF:Q8_0
```

Then register it with `tau setup`. `llama serve` ignores the bearer token
unless you launched it with `--api-key`, so any value for `LLAMA_API_KEY` works:

```bash
export LLAMA_API_KEY=local   # any non-empty value; only enforced if you set --api-key
tau --provider local \
  --base-url http://localhost:8080/v1 \
  --api-key-env LLAMA_API_KEY \
  --model local \
  setup
```

This writes an entry to `~/.tau/providers.json` and (by default) makes it the
default provider. Run it with:

```bash
tau --provider local
tau --provider local "summarize this project"   # TUI with an initial prompt
tau --provider local -p "summarize this project" # one-shot print mode
```

Other OpenAI-compatible servers register the same way — point `--base-url` at
their endpoint (e.g. `http://localhost:11434/v1` for Ollama) and pass the
matching `--api-key-env` and `--model`.

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
`api_key_env`. Use `/login` for built-in providers. Custom/local providers
created with `tau setup` use their configured environment variable until Tau has
a custom-provider credential form.
