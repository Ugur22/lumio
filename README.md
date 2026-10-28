# Lumio

A local chat UI for any OpenAI-compatible LLM. Built for writing: dialogue, actions and key moments stay styled as the model streams its reply.

<p>
  <img src="docs/screenshot-light.png" alt="Lumio in light mode" width="49%">
  <img src="docs/screenshot-dark.png" alt="Lumio in dark mode" width="49%">
</p>

## Features

- Streaming LLM replies from any OpenAI-compatible provider with Markdown, syntax highlighting and styled dialogue
- Image input: attach, paste or drop images and the model reads them (with a vision-capable model)
- Optional web search: add a Tavily key to turn on the Web toggle; links you paste are always read
- Your API keys live in the OS keychain, never in a file and never in the browser
- Saved chats with rename and delete, light and dark themes

Lumio still works with any OpenAI-compatible API: providers are profiles (name, base URL, model), switchable from the header.

## Setup

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cd frontend && npm install
```

## Run

```sh
make build   # build the frontend
make dev     # API + UI on http://localhost:8000
```

## Connect a provider

In Lumio, open **Providers**, pick a preset, paste your API key and save. Presets fill in the base URL and a default model, which you can change:

| Preset | Base URL |
| --- | --- |
| OpenAI | `https://api.openai.com/v1` |
| Anthropic | `https://api.anthropic.com/v1` |
| xAI (Grok) | `https://api.x.ai/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Groq | `https://api.groq.com/openai/v1` |
| Together | `https://api.together.xyz/v1` |
| Ollama (local, no key) | `http://localhost:11434/v1` |
| Custom | any OpenAI-compatible endpoint |

You can keep several profiles and switch between them from the header.

For hot reload, run `npm run dev` in `frontend/` as well and open http://localhost:5173.

## Develop

`make check` runs the offline checks: syntax lint, ESLint, pytest and tsc.

**Stack:** FastAPI, React, TypeScript, Tailwind, Vite.
