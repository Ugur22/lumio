# Lumio

Local chat UI for any OpenAI-compatible API. Providers are profiles (name, base URL, model) in git-ignored `profiles.json`; each profile's API key lives in the OS keychain (`secret_store.py`), never in that file. FastAPI backend (`server.py`, `models.py`) serves a React + Tailwind frontend (`frontend/`). `main.py` is the older terminal chat and must keep working.

## Run
- Setup: `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`, then `cd frontend && npm install`. Add a provider and key in the app's Providers dialog. `DOLPHINLLM_API_KEY` in `.env` still works as a fallback for a pre-profiles setup (it becomes the "Dolphin" profile).
- Production-like: `make build` then `make dev`, open http://localhost:8000.
- After changing a route or a model in `models.py`: `make types` regenerates `frontend/src/api.gen.ts`; commit it with the change.
- Hot reload: `make dev` plus `npm run dev` in `frontend/` (Vite on :5173 proxies `/api` to :8000).

## Rules
- No commits without explicit approval. Never read, print or edit `.env`, and never touch `data/` (saved chats); both are git-ignored.
- The API key stays server-side: never log it, return it, or put it in a served file.
- Chats store raw text. Styling (Markdown, highlight tags, dialogue) is applied at render time, and reply text is untrusted, so it is always sanitized.
- Anything non-trivial: plan first, then wait for approval.
- Do not edit `.claude/settings.json` or `scripts/hooks/` to loosen the checks.

## Verify
Run `make check` (about 20 seconds, offline: syntax lint, ESLint, pytest, Vitest, generated-types freshness, tsc, test-count baseline; Cypress stays in `make e2e`) before reporting a task done; a Stop hook enforces it. The real API is only ever called by hand.

## Pull requests
`main` only takes changes through a PR, and `gh` fails inside Claude's sandbox, so Claude never opens one. After every push of a branch, end the reply with a ready-to-run command for the user (to run with the `!` prefix), in this shape:

```
! gh pr create --base main --head <branch> --title "<imperative, under 70 characters>" --body "$(cat <<'EOF'
## What
- <the change, one bullet per point>

## Why
<the problem it solves, one or two sentences; omit for trivial changes>

## Check
<what was run and what it showed, plus anything not verified, such as the UI in a browser>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

The title matches the commit's first line. Mention API or behaviour changes under What, and anything the user has to do by hand (an install, a deploy) under Check.

## Agents
`.claude/agents/frontend-developer.md` (anything under `frontend/`) and `backend-developer.md` (`server.py`, `models.py`, `tests/`). Use them for scoped changes; use `bug-fixer`-style work (reproduce, root cause, smallest fix, regression test) for bugs.

Changes that span both stacks start with a written contract (route, request/response shape, the `models.py` and `types.ts` fields) agreed in the plan before delegating; `frontend/src/api.gen.ts` is generated from `models.py` and `server.py` (`make types`, and `make check` fails when it is stale), so the contract cannot drift. Only the SSE event payloads in `types.ts` are still written by hand. Run parallel agents with `isolation: "worktree"`, and finish with `.claude/agents/reviewer.md` (read-only) on the diff.
