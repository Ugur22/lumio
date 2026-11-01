# Offline feedback loop for humans, hooks and agents. Never calls the real API.

PY ?= .venv/bin/python

.PHONY: check check-fast lint-backend lint-frontend test-backend test-frontend typecheck-frontend test-count types check-types build deploy rollback deploy-systemd dev e2e-server e2e

check-fast: lint-backend lint-frontend

check: check-fast test-backend test-frontend check-types typecheck-frontend test-count

# Syntax check (ast.parse, writes no .pyc files), then ruff for the bug-finding rules in ruff.toml.
lint-backend:
	@find . \( -path ./.venv -o -path ./frontend/node_modules -o -path ./data \) -prune -o -name '*.py' -print0 \
		| xargs -0 $(PY) -c "import ast, sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]"
	@$(PY) -m ruff check --no-cache .

# Fails when fewer tests exist than scripts/test-baseline.txt records, so deleting tests cannot go green.
test-count:
	@PY=$(PY) scripts/check-test-count.sh

# The frontend's API types are generated from the backend's OpenAPI schema; run this after changing a route or a model in models.py.
types:
	@PY=$(PY) scripts/gen-types.sh frontend/src/api.gen.ts

# Fails when the committed types no longer match the backend, so an API change cannot reach the frontend unnoticed.
check-types:
	@mkdir -p "$${TMPDIR:-/tmp}" && tmp=$$(mktemp "$${TMPDIR:-/tmp}/api-types.XXXXXX") && trap 'rm -f "$$tmp"' EXIT \
		&& PY=$(PY) scripts/gen-types.sh "$$tmp" \
		&& { cmp -s "$$tmp" frontend/src/api.gen.ts || { echo "frontend/src/api.gen.ts is out of date with the API. Run: make types"; exit 1; }; } \
		&& echo "api types match the backend"

lint-frontend:
	@cd frontend && npx eslint .

test-backend:
	@$(PY) -m pytest -q

# Vitest in run mode (npm test is `vitest run`), so it exits non-zero on a failure instead of watching.
test-frontend:
	@cd frontend && npm test --silent

typecheck-frontend:
	@cd frontend && npx tsc -b --noEmit

build:
	@cd frontend && npm run build

# Switches the EC2 box to the image the `image` workflow built for this commit (see deploy/README.md). Override with
# `make deploy DEPLOY_KEY=... DEPLOY_HOST=...`. Refuses to run off main so an unmerged branch cannot reach the live
# site, and runs the full check first so an API that has drifted from the frontend types stops the deploy early.
# Wait for the `image` workflow on main to finish: release.sh refuses a tag that has not been pushed yet.
DEPLOY_HOST ?= ubuntu@16-192-71-141.sslip.io
DEPLOY_KEY ?= $(HOME)/Downloads/lumio-keypair.pem
DEPLOY_DIR ?= /opt/lumio-compose
deploy: check
	@test "$$(git branch --show-current)" = main || { echo "deploy only from main"; exit 1; }
	@test -z "$$(git status --porcelain --untracked-files=no)" || { echo "uncommitted changes: deploy ships the commit CI built, so commit them through a PR first"; exit 1; }
	@test -f "$(DEPLOY_KEY)" || { echo "key not found: $(DEPLOY_KEY)"; exit 1; }
	scp -i "$(DEPLOY_KEY)" deploy/docker/docker-compose.yml deploy/docker/Caddyfile deploy/docker/release.sh $(DEPLOY_HOST):$(DEPLOY_DIR)/
	ssh -i "$(DEPLOY_KEY)" $(DEPLOY_HOST) 'cd $(DEPLOY_DIR) && chmod +x release.sh && sudo ./release.sh $(shell git rev-parse --short=12 HEAD)'

# Back to an earlier image: `make rollback` (the previous tag) or `make rollback TAG=<12-char commit>`. The database is not rolled back.
rollback:
	@test -f "$(DEPLOY_KEY)" || { echo "key not found: $(DEPLOY_KEY)"; exit 1; }
	ssh -i "$(DEPLOY_KEY)" $(DEPLOY_HOST) 'cd $(DEPLOY_DIR) && sudo ./release.sh $(or $(TAG),previous)'

# The pre-Docker deploy (rsync + systemd). Kept only as the way back until the Docker setup has proven itself.
deploy-systemd: check build
	@test "$$(git branch --show-current)" = main || { echo "deploy only from main"; exit 1; }
	@test -z "$$(git status --porcelain --untracked-files=no)" || { echo "uncommitted changes: deploy ships the working tree, so commit them through a PR first"; exit 1; }
	@test -f "$(DEPLOY_KEY)" || { echo "key not found: $(DEPLOY_KEY)"; exit 1; }
	rsync -a --delete -e "ssh -i $(DEPLOY_KEY)" --exclude .git --exclude .venv --exclude '.env*' --exclude '/data' --exclude logs \
		--exclude profiles.json --exclude .claude --exclude .agents --exclude __pycache__ --exclude /terraform \
		--exclude frontend/node_modules --exclude frontend/dist ./ $(DEPLOY_HOST):/opt/lumio/
	rsync -a --delete -e "ssh -i $(DEPLOY_KEY)" frontend/dist/ $(DEPLOY_HOST):/opt/lumio/frontend/dist/
	ssh -i "$(DEPLOY_KEY)" $(DEPLOY_HOST) 'cd /opt/lumio && .venv/bin/pip install -q -r requirements.txt && sudo systemctl restart lumio && systemctl is-active lumio'

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
# Bash on purpose: the teardown relies on `set -m` giving the server its own process group, and dash (/bin/sh on
# Ubuntu CI) silently ignores it without a terminal, so the kill misses and `wait` hangs until the job times out.
e2e: SHELL := /bin/bash
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
