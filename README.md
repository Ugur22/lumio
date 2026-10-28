# Lumio

A local chat UI for any OpenAI-compatible API. Built for writing: dialogue, actions and key moments stay styled as the model streams its reply.

<p>
  <img src="docs/screenshot-light.png" alt="Lumio in light mode" width="49%">
  <img src="docs/screenshot-dark.png" alt="Lumio in dark mode" width="49%">
</p>

## Features

- Streaming replies with Markdown, syntax highlighting and styled dialogue
- Multiple providers: each is a profile (name, base URL, model), switchable from the header
- API keys live in the OS keychain, never in a file and never in the browser
- Saved chats with rename and delete, light and dark themes

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

For hot reload, run `npm run dev` in `frontend/` as well and open http://localhost:5173. Add a provider and its key in the Providers dialog.

## Develop

`make check` runs the offline checks: syntax lint, ESLint, pytest and tsc.

**Stack:** FastAPI, React, TypeScript, Tailwind, Vite.
