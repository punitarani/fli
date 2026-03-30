#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
KEYS_FILE="$SCRIPT_DIR/worker-env-keys.txt"

cmd=(npx wrangler deploy)

while IFS= read -r key || [ -n "$key" ]; do
  value="${!key:-}"
  if [ -n "$value" ]; then
    cmd+=(--var "${key}:${value}")
  fi
done < <(grep -v '^#' "$KEYS_FILE" | grep -v '^$')

cmd+=("$@")

(
  cd "$REPO_ROOT"
  "${cmd[@]}"
)
