#!/usr/bin/env bash
# Writes the TypeScript types generated from the backend's OpenAPI schema to the path given as $1.
set -euo pipefail
cd "$(dirname "$0")/.."
root=$PWD
case "$1" in /*) out=$1 ;; *) out=$root/$1 ;; esac
tmp=$(mktemp -d "${TMPDIR:-/tmp}/lumio-types.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
"${PY:-.venv/bin/python}" scripts/export_openapi.py > "$tmp/openapi.json"
# The local binary, not npx: npx may try to touch the npm cache.
(cd frontend && ./node_modules/.bin/openapi-typescript "$tmp/openapi.json" --default-non-nullable false -o "$out" > /dev/null)
