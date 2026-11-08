#!/bin/bash
# Fails when a tracked .py/.ts/.tsx file (api.gen.ts excluded) is over LIMIT lines, or when a file listed in
# scripts/size-baseline.txt grows past its recorded size. The baseline only ratchets down: split the file, then
# run with --update to lower or drop its entry. Never raise an entry to get a check through.
set -eu

cd "$(dirname "$0")/.."
limit=600
baseline=scripts/size-baseline.txt

sizes=$(git ls-files '*.py' '*.ts' '*.tsx' | grep -v '^frontend/src/api.gen.ts$' | while read -r f; do
  [ -f "$f" ] && printf '%s %s\n' "$(wc -l < "$f" | tr -d ' ')" "$f"
done)

if [ "${1:-}" = "--update" ]; then
  # Only ever lowers or removes entries; a new offender must be split, not recorded.
  mkdir -p "${TMPDIR:-/tmp}" && tmp=$(mktemp "${TMPDIR:-/tmp}/size-baseline.XXXXXX")
  while read -r n f; do
    [ "$n" -le "$limit" ] && continue
    old=$(grep -F " $f" "$baseline" 2>/dev/null | awk -v f="$f" '$2==f{print $1}' || true)
    if [ -z "$old" ] && [ "${2:-}" != "--init" ]; then echo "$f is $n lines and not in the baseline; split it" >&2; exit 1; fi
    if [ -n "$old" ] && [ "$n" -gt "$old" ]; then echo "$f grew ($old -> $n); split it" >&2; exit 1; fi
    echo "$n $f" >> "$tmp"
  done <<< "$sizes"
  sort -rn "$tmp" > "$baseline"; rm -f "$tmp"
  echo "size baseline updated"
  exit 0
fi

fail=0
while read -r n f; do
  [ "$n" -le "$limit" ] && continue
  allowed=$(awk -v f="$f" '$2==f{print $1}' "$baseline" 2>/dev/null || true)
  if [ -z "$allowed" ]; then
    echo "$f: $n lines, limit $limit" >&2; fail=1
  elif [ "$n" -gt "$allowed" ]; then
    echo "$f: $n lines, grew past its baseline of $allowed" >&2; fail=1
  fi
done <<< "$sizes"
if [ "$fail" -eq 1 ]; then
  echo "split the file by responsibility (target: under 400 lines); see File size in CLAUDE.md" >&2
  exit 1
fi
