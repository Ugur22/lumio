#!/bin/bash
# Fails when fewer tests are collected than scripts/test-baseline.txt records, so removing tests cannot turn a run green.
# Intentional removals: run with --update and have the baseline change reviewed.
set -eu

cd "$(dirname "$0")/.."
baseline=scripts/test-baseline.txt
py="${PY:-.venv/bin/python}"

pytest_count=$("$py" -m pytest --collect-only -q 2>/dev/null | grep -oE '^[0-9]+ tests? collected' | grep -oE '^[0-9]+')
vitest_count=$(cd frontend && npx vitest list 2>/dev/null | grep -c ' > ')

if [ "${1:-}" = "--update" ]; then
  printf 'pytest=%s\nvitest=%s\n' "$pytest_count" "$vitest_count" > "$baseline"
  echo "baseline updated: pytest=$pytest_count vitest=$vitest_count"
  exit 0
fi

want_pytest=$(grep '^pytest=' "$baseline" | cut -d= -f2)
want_vitest=$(grep '^vitest=' "$baseline" | cut -d= -f2)

fail=0
if [ "$pytest_count" -lt "$want_pytest" ]; then echo "pytest: $pytest_count tests, baseline $want_pytest" >&2; fail=1; fi
if [ "$vitest_count" -lt "$want_vitest" ]; then echo "vitest: $vitest_count tests, baseline $want_vitest" >&2; fail=1; fi
if [ "$fail" -eq 1 ]; then
  echo "test count dropped below scripts/test-baseline.txt; if intentional, run scripts/check-test-count.sh --update" >&2
  exit 1
fi
