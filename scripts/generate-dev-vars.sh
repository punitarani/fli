#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTFILE="$REPO_ROOT/.dev.vars"
KEYS_FILE="$SCRIPT_DIR/worker-env-keys.txt"

: > "$OUTFILE"

while IFS= read -r key || [ -n "$key" ]; do
  value="${!key:-}"
  if [ -n "$value" ]; then
    printf '%s=%s\n' "$key" "$value" >> "$OUTFILE"
  fi
done < <(grep -v '^#' "$KEYS_FILE" | grep -v '^$')

echo "Generated $OUTFILE with $(wc -l < "$OUTFILE" | tr -d ' ') vars"
