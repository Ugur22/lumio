# Lumio

A local chat UI for long-form writing with an OpenAI-compatible LLM: stories, roleplay and other collaborative fiction. Each chat can carry its own story bible, keyword-triggered lore and a running summary, and the UI shows how much of the model's context window they use. Dialogue, actions and key moments stay styled while a reply streams.

<p>
  <img src="docs/screenshot-light.png" alt="Lumio in light mode" width="49%">
  <img src="docs/screenshot-dark.png" alt="Lumio in dark mode" width="49%">
</p>

Lumio runs on your machine (or on a server you deploy yourself) and talks to the provider you configure. It has no accounts and no hosted service.

## Features

**Writing**
- **Streaming replies** from any provider that speaks the OpenAI chat-completions API, rendered as Markdown with syntax highlighting. `"Quoted speech"` and `*actions*` are styled, and the model is asked to use `[[key]]`, `[[note]]` and `[[warn]]` tags for emphasis. Chats store the raw text; styling is applied when rendering, and reply text is sanitized because it is untrusted.
- **Story bible**: free text canon for the chat (up to 20,000 characters), sent with every message.
- **Triggered lore**: named entries with trigger keys (up to 200 per chat). An enabled entry is sent only when one of its keys appears, as a whole word and ignoring case, in the last 6 messages or the message being sent.
- **Summaries**: the **Generate** button on the Summary tab asks the model to condense older messages. You edit the proposal and save it. Messages covered by the summary stay stored and visible but are no longer sent; the latest 6 messages are never summarized. Summaries are never created automatically.
- **Per-chat behavior**: a system prompt plus temperature, top-p, frequency penalty and max tokens, and an optional model override for the chat.
- **Context meter**: shows used tokens against the context window. The total is the prompt token count the provider reported on the last reply; before that it is an estimate (characters / 4). The breakdown by system prompt, bible, lore, summary and history is always an estimate. The window size is something you enter on the provider profile (it is prefilled when the provider's model list reports it, as OpenRouter's does), so the percentage only appears when a window is known.

**Media and tools**
- **Illustrations**: if the profile has an image model, an **Illustrate** toggle appears in the composer. The model is asked to place up to three `[[image: …]]` lines per reply, and each is sent to the provider's `/images/generations` endpoint (`b64_json` responses). A failed image is dropped and reported; the text stays. The xAI preset fills in an image model by default; for other providers you set one yourself.
- **Image input**: attach, paste or drop up to 4 images (5 MB each) when the profile is marked vision-capable.
- **Web search** (optional): with a Tavily key saved in **Providers**, the **Web** toggle searches for each message. Links you paste (up to 3) are fetched and read whether or not a key is set. Pages are added to the prompt as untrusted reference text and shown as sources under the reply.
- **Code execution**: fenced `python` and `javascript` blocks get a **Run** button. Code runs in your browser inside a hidden sandboxed iframe with no network access and a time limit. Python uses Pyodide, which is bundled with the app, so it works offline. `input()` and `prompt()` read from a stdin field. Other languages get no Run button. The repository's Cypress journey covers running a JavaScript block; the Python path has unit tests for the sandbox pieces but no end-to-end test.

**Providers and chats**
- **Provider profiles** (name, base URL, model, optional context window, vision flag, optional image model), switchable from the header, with a different provider and model selectable per chat.
- **Saved chats** with rename and delete, light and dark themes.
- **Terminal chat**: `main.py` is a minimal command-line chat that reuses the active profile and key (`python main.py`, `--new` starts fresh). It has none of the story features above.

## Quick start

Requires Python 3 and Node.js with npm. CI and the checks below were run with Python 3.13 and Node 22; other versions were not tried.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cd frontend && npm install && cd ..
make build   # builds frontend/dist
make dev     # API + built UI on http://localhost:8000 (binds 127.0.0.1)
```

Then open **Providers**, pick a preset, paste your API key and save. Presets only fill in a base URL and a default model you can change:

| Preset | Base URL |
| --- | --- |
| OpenAI | `https://api.openai.com/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Groq | `https://api.groq.com/openai/v1` |
| DeepSeek | `https://api.deepseek.com/v1` |
| xAI (Grok) | `https://api.x.ai/v1` |
| Together | `https://api.together.xyz/v1` |
| Anthropic (OpenAI-compatible) | `https://api.anthropic.com/v1` |
| Dolphin | `https://api.dolphinllm.com/v1` |
| Ollama (local, no key) | `http://localhost:11434/v1` |
| Custom | any OpenAI-compatible endpoint |

Presets are conveniences, not a compatibility guarantee. The only provider paths exercised by this repository's tests are a local stub server; I have not verified each preset against its live API, and providers differ in what they support (for example image generation, vision, streaming usage counts).

A key already in a `.env` file as `DOLPHINLLM_API_KEY` still works as a fallback for setups that predate profiles (it becomes the "Dolphin" profile).

### Hot reload

```sh
make dev                    # terminal 1: API on :8000
cd frontend && npm run dev  # terminal 2: Vite on http://localhost:5173, proxies /api to :8000
```

## Architecture

```
Browser (React + Tailwind, built by Vite)
   │  JSON + server-sent events
   ▼
FastAPI (server.py → app/ routes, models.py)
   ├── SQLite chats          data/chats/lumio.db
   ├── Chat images           data/chats/images/<chat id>/
   ├── Provider profiles     profiles.json (no keys)
   ├── API keys              OS keychain  (or a 0600 file on a server)
   └── outbound calls ──►  your LLM provider, Tavily (optional), pasted web links
```

- **Frontend** (`frontend/`): React 19, TypeScript, Tailwind, TanStack Query and Zustand. It renders Markdown with a sanitizing pipeline and runs code blocks in the sandbox described above. API types in `frontend/src/api.gen.ts` are generated from the backend (`make types`).
- **Backend**: `server.py` assembles the FastAPI app from `app/` (chat and profile routes, prompt building in `story.py`, streaming in `streaming.py`, provider access in `providers.py`). It uses the OpenAI Python SDK against each profile's base URL, streams replies to the browser as SSE, and serves `frontend/dist` when it exists.
- **Persistence**: chats are rows in SQLite (WAL mode). A reply takes a short per-chat lease, so a second send to a chat that is still replying gets `409` while other chats are unaffected. Images are files on disk.
- **Providers**: the backend calls the provider's base URL directly. The browser never talks to a provider and never sees a key.

## What stays local and what is sent out

**Stored locally** (git-ignored, on the machine running Lumio):

| What | Where |
| --- | --- |
| Chats, bible, lore, summaries, per-chat settings | `data/chats/lumio.db` (override with `DOLPHINLLM_DB_FILE`; `DOLPHINLLM_DATA_DIR` moves the whole directory) |
| Attached and generated images | `data/chats/images/`, deleted after 30 days (`DOLPHINLLM_IMAGE_RETENTION_DAYS`) or with their chat. Older messages then show a placeholder, and the model is told the image is gone |
| Provider profiles (name, URL, model, flags) | `profiles.json` |
| Provider and Tavily API keys | OS keychain; on a server, the file named by `DOLPHINLLM_SECRETS_FILE` |
| Logs | `logs/app.jsonl`: metadata only; keys and message/summary bodies are redacted |

**Sent to external services** whenever you use the matching feature:

| To | What |
| --- | --- |
| Your LLM provider | The system prompt and formatting notes, your chat instructions, the story bible, any triggered lore, the summary, all messages not covered by the summary, your new message, attached images (for vision profiles), and fetched web text. Summaries are generated by sending the older messages to the same provider. With Web on, a short query-rewrite call also sends your latest message and the last few messages (each cut to 300 characters) |
| Your provider's image endpoint | The one-sentence prompt for each illustration |
| Tavily (`api.tavily.com`) | The search query, only when the Web toggle is on and a key is saved |
| Web pages you link | A plain GET from the server. Only public addresses are fetched; localhost and private networks are refused, including after redirects |

Your API key is sent to the profile's base URL and nowhere else. Anything you put in a chat is subject to that provider's own retention and privacy terms, which Lumio does not control.

## Provider requirements and known limitations

- The provider must offer an OpenAI-compatible `/chat/completions` endpoint with streaming. `/models` is used by the Providers dialog to test a key and list models; a provider without it can still be used by typing the model name.
- Vision, the image model and the context window are set by you per profile. Lumio cannot detect them. Sending images to a profile not marked as vision is refused, and illustrating without an image model is refused.
- Base URLs must be `https`, except for localhost.
- The context meter's breakdown is an estimate, and the percentage needs a context window.
- Summaries are manual, and are not available until a chat has more than 6 messages beyond the last summary.
- At most 3 illustrations are made per reply; extras are dropped.
- Web pages that need JavaScript to render are not readable. Fetch limits: 1 MB per page, 10 s timeout, 6,000 characters kept per page.
- The code runner supports Python and JavaScript only, and has no network access.
- Chats are plain text in a local database and are not encrypted by Lumio.
- Locally there is no login, and state-changing key and profile routes only accept requests from the local origin. A deployed instance has invite-only accounts: each account has its own chats, providers and keys.
- Only one reply per chat can be generated at a time.
- Not verified for this README: the UI in a browser (I did not run `make dev` interactively), `make e2e` (needs the Cypress binary and free ports), `make deploy`, and any live provider.

## Develop and test

```sh
make check      # offline: syntax lint, ruff, ESLint, pytest, Vitest, generated-types freshness, tsc, test-count baseline
make e2e        # Cypress journey against a stub upstream (needs the Cypress binary; not part of make check)
make types      # regenerate frontend/src/api.gen.ts after changing a route or a model in models.py
```

`make check` makes no real provider calls. On the revision this README was written against, `make check` and `make build` both passed. CI runs `make check`, `make e2e` and a secret scan on every pull request.

## Deployment

A single-instance setup (Caddy with HTTPS in front of uvicorn on an EC2 box, SQLite and keys outside the release directory) is described in [deploy/README.md](deploy/README.md), including accounts and invites, backups and rollback. Releases go out with `make deploy`.
