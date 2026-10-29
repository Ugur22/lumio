# Offline feedback loop for humans, hooks and agents. Never calls the real API.

PY ?= .venv/bin/python

.PHONY: check check-fast lint-backend lint-frontend test-backend typecheck-frontend build dev e2e-server e2e

check-fast: lint-backend lint-frontend

check: check-fast test-backend typecheck-frontend

# Syntax-only (ast.parse): no linter is configured and this writes no .pyc files.
lint-backend:
	@find . \( -path ./.venv -o -path ./frontend/node_modules -o -path ./data \) -prune -o -name '*.py' -print0 \
		| xargs -0 $(PY) -c "import ast, sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]"

lint-frontend:
	@cd frontend && npx eslint .

test-backend:
	@$(PY) -m pytest -q

typecheck-frontend:
	@cd frontend && npx tsc -b --noEmit

build:
	@cd frontend && npm run build

# API on :8000; run `npm run dev` in frontend/ for the hot-reloading UI on :5173.
dev:
	@$(PY) -m uvicorn server:app --reload --host 127.0.0.1 --port 8000

# Cypress target: stub upstream on :18765, app on :18766 in e2e mode with a throwaway data dir.
# Reads/writes no keychain, profiles.json or data/. Ctrl-C stops both and removes the temp dir.
E2E_STUB_PORT ?= 18765
E2E_APP_PORT ?= 18766
e2e-server:
	@d=$$(mktemp -d "$${TMPDIR:-/tmp}/lumio-e2e.XXXXXX"); trap 'kill 0; rm -rf "$$d"' EXIT INT TERM; \
	$(PY) -m tests.fake_upstream --port $(E2E_STUB_PORT) & \
	LUMIO_E2E_UPSTREAM=http://127.0.0.1:$(E2E_STUB_PORT)/v1 LUMIO_E2E_DATA_DIR=$$d \
	$(PY) -m uvicorn server:app --host 127.0.0.1 --port $(E2E_APP_PORT) --log-level warning

# Smoke journey in Cypress. Not part of `make check` (needs the Cypress binary and free ports).
# Builds dist/, starts the e2e server, waits for it, always stops it, and tails logs/app.jsonl on failure.
e2e: build
	@mkdir -p logs; : > logs/e2e-server.out; set -m; \
	$(MAKE) --no-print-directory e2e-server > logs/e2e-server.out 2>&1 & srv=$$!; \
	cleanup() { kill -TERM -- -$$srv 2>/dev/null; wait $$srv 2>/dev/null; true; }; \
	trap cleanup EXIT INT TERM; \
	up=0; for i in $$(seq 1 60); do \
		if curl -fsS -o /dev/null http://127.0.0.1:$(E2E_APP_PORT)/api/chats 2>/dev/null; then up=1; break; fi; sleep 0.5; done; \
	if [ $$up -ne 1 ]; then echo "e2e server did not come up:"; tail -n 40 logs/e2e-server.out; exit 1; fi; \
	(cd frontend && npx cypress run); rc=$$?; \
	if [ $$rc -ne 0 ]; then echo "--- last 40 lines of logs/app.jsonl ---"; tail -n 40 logs/app.jsonl 2>/dev/null; fi; \
	exit $$rc
