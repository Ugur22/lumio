# Lumio

Local chat UI for any OpenAI-compatible API. Providers are profiles (name, base URL, model) in git-ignored `profiles.json`; each profile's API key lives in the OS keychain (`secret_store.py`), never in that file. FastAPI backend (`server.py`, `models.py`) serves a React + Tailwind frontend (`frontend/`). `main.py` is the older terminal chat and must keep working.

## Run
- Setup: `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`, then `cd frontend && npm install`. Add a provider and key in the app's Providers dialog. `DOLPHINLLM_API_KEY` in `.env` still works as a fallback for a pre-profiles setup (it becomes the "Dolphin" profile).
- Production-like: `make build` then `make dev`, open http://localhost:8000.
- Hot reload: `make dev` plus `npm run dev` in `frontend/` (Vite on :5173 proxies `/api` to :8000).

## Rules
- No commits without explicit approval. Never read, print or edit `.env`, and never touch `data/` (saved chats); both are git-ignored.
- The API key stays server-side: never log it, return it, or put it in a served file.
- Chats store raw text. Styling (Markdown, highlight tags, dialogue) is applied at render time, and reply text is untrusted, so it is always sanitized.
- Anything non-trivial: plan first, then wait for approval.
- Do not edit `.claude/settings.json` or `scripts/hooks/` to loosen the checks.

## Verify
Run `make check` (about 15 seconds, offline: syntax lint, ESLint, pytest, tsc) before reporting a task done; a Stop hook enforces it. The real API is only ever called by hand.

## Agents
`.claude/agents/frontend-developer.md` (anything under `frontend/`) and `backend-developer.md` (`server.py`, `models.py`, `tests/`). Use them for scoped changes; use `bug-fixer`-style work (reproduce, root cause, smallest fix, regression test) for bugs.
