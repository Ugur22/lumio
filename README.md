# Lumio

A self-hosted, writing-focused chat interface with configurable LLM providers. Lumio is built for long-form collaborative fiction: each chat can carry its own story bible, keyword-triggered lore and a running summary, and the UI shows how much of the model's context window they use. Dialogue, actions and key moments stay styled while a reply streams.

<p>
  <img src="docs/screenshot-light.png" alt="Lumio in light mode" width="49%">
  <img src="docs/screenshot-dark.png" alt="Lumio in dark mode" width="49%">
</p>

## Features

- **Streaming replies** from any provider with an OpenAI-compatible chat-completions API, rendered as sanitized Markdown with styled dialogue and actions.
- **Story bible and triggered lore** per chat, sent with your messages when relevant.
- **Manual summaries** that condense older messages once you approve them.
- **Per-chat behavior**: system prompt, sampling settings and an optional model override.
- **Context meter** showing prompt tokens against the model's context window.
- **Illustrations, image input and web search** when the provider profile and keys support them.
- **Run buttons** for Python and JavaScript code blocks, executed in a sandboxed iframe in your browser.
- **Provider profiles**, switchable from the header and per chat, plus saved chats and light/dark themes.

Rules, limits and details for each are in [docs/features.md](docs/features.md).

## Run locally

Requires Python 3 and Node.js with npm. CI uses Python 3.13 and Node 22; other versions are untested.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cd frontend && npm install && cd ..
make build   # builds frontend/dist
make dev     # API and built UI on http://localhost:8000 (binds 127.0.0.1)
```

For hot reload, keep `make dev` running and start `npm run dev` in `frontend/`; Vite serves http://localhost:5173 and proxies `/api` to port 8000.

`python main.py` is a minimal terminal chat that reuses the active profile and key (`--new` starts fresh). It has none of the story features.

## Connect a provider

Open **Providers**, pick a preset (or **Custom**), paste your API key and save. A preset only fills in a base URL and a default model, both editable. Vision support, an image model and the context window are settings you choose per profile; Lumio cannot detect them. Base URLs must use `https`, except localhost. See [docs/providers.md](docs/providers.md) for presets and compatibility limits.

## Local and deployed modes

| | Local | Deployed |
| --- | --- | --- |
| Sign-in | None; the page on `localhost` is the only user | Invite-only accounts |
| Chats | One shared library | Private to each account |
| Providers and keys | One set, keys in the OS keychain | Per account; keys encrypted in a server-side file |
| Enabled by | Default | `DOLPHINLLM_PUBLIC_HOST` |

A deployed instance has no open signup: an admin creates the first account on the server, then issues single-use invite codes. Setup, backups and rollback are in [deploy/README.md](deploy/README.md).

## Privacy

Lumio has no hosted service of its own. Chats are plain text in a SQLite database on the machine running Lumio and are not encrypted by Lumio; attached and generated images are files next to it and are deleted after 30 days. Provider profiles (name, URL, model, flags) are stored without keys. Keys live in the OS keychain locally, or on a server in a file encrypted with a master key you supply.

Content leaves your machine only when you use it: your provider receives the prompt (system prompt, bible, triggered lore, summary, unsummarized messages, new message, attached images and fetched web text), your provider's image endpoint receives illustration prompts, Tavily receives search queries when Web is on, and pasted links are fetched from the server. Your API key is sent only to the profile's base URL. The browser never talks to a provider and never sees a key. Providers apply their own retention terms. The full list is in [docs/architecture.md](docs/architecture.md#data-and-privacy).

## Develop and test

```sh
make check   # offline: lint, ruff, ESLint, pytest, Vitest, generated-types freshness, tsc, test-count baseline
make e2e     # Cypress journey against a stub upstream; needs the Cypress binary and free ports
make types   # regenerate frontend/src/api.gen.ts after changing a route or a model in models.py
```

`make check` makes no real provider calls. CI runs `make check`, `make e2e` and a secret scan on every pull request. `main` only takes changes through a pull request.

## Documentation

- [docs/features.md](docs/features.md): feature rules and limits
- [docs/providers.md](docs/providers.md): presets, requirements and compatibility
- [docs/architecture.md](docs/architecture.md): components, storage and data sharing
- [deploy/README.md](deploy/README.md): single-EC2 deployment and operations
- [deploy/UPGRADING.md](deploy/UPGRADING.md): upgrading data from older releases
