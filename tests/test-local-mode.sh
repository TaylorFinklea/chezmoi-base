#!/usr/bin/env bash
set -euo pipefail

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

repo_root=$(cd "$(dirname "$0")/.." && pwd)
target="$tmp/.local/bin/chezmoi-sync"

chezmoi --source "$repo_root" --destination "$tmp" apply --force --parent-dirs -- "$target"

mode=$(stat -f '%Lp' "$tmp/.local")
if [ "$mode" != 700 ]; then
  printf 'test-local-mode: expected .local mode 0700, got %s\n' "$mode" >&2
  exit 1
fi

if [ ! -x "$target" ]; then
  printf 'test-local-mode: expected chezmoi-sync target to be executable\n' >&2
  exit 1
fi
