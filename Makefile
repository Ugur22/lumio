# Offline feedback loop for humans, hooks and agents. Never calls the real API.

PY ?= .venv/bin/python

.PHONY: check check-fast lint-backend lint-frontend test-backend typecheck-frontend build dev

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
