#!/usr/bin/env bash
# Inner-loop check: only what the changes since main can affect. Not a gate; `make check` still is.
# Frontend: Vitest follows the import graph from each changed file (`vitest related`), plus ESLint on those files and tsc.
# Backend: ruff on changed files, and pytest when any Python file changed (no import-graph tool for pytest here).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"

base=$(git merge-base main HEAD)
changed=$( { git diff --name-only --diff-filter=d "$base"; git ls-files --others --exclude-standard; } | sort -u)

fe=(); py=()
while IFS= read -r f; do
  [ -f "$f" ] || continue
  case "$f" in
    frontend/src/api.gen.ts) ;;
    frontend/src/*.ts|frontend/src/*.tsx) fe+=("$PWD/$f") ;;
    *.py) py+=("$f") ;;
  esac
done <<<"$changed"

echo "related: ${#fe[@]} frontend file(s), ${#py[@]} python file(s) changed since main"

if [ "${#fe[@]}" -gt 0 ]; then
  (cd frontend && npx eslint "${fe[@]}" && npx vitest related --run --passWithNoTests "${fe[@]}" && npx tsc -b --noEmit)
fi
if [ "${#py[@]}" -gt 0 ]; then
  "$PY" -m ruff check --no-cache "${py[@]}"
  "$PY" -m pytest -q
fi
echo "related checks passed. Skipped: file-size, generated types, test-count. Run \`make check\` before reporting done."
