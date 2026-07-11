#!/usr/bin/env bash
set -euo pipefail

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

repo_root=$(cd "$(dirname "$0")/.." && pwd)
runner="$repo_root/scripts/chezmoi-compose"

fail() {
  printf 'test-compose: %s\n' "$1" >&2
  exit 1
}

run_compose() {
  export CHEZMOI_BASE_SOURCE="$tmp/base"
  export CHEZMOI_PERSONAL_SOURCE="$tmp/personal"
  export CHEZMOI_WORK_SOURCE="$tmp/work"
  export CHEZMOI_CONFIG_ROOT="$tmp/config"
  export CHEZMOI_STATE_ROOT="$tmp/state"
  export CHEZMOI_DESTINATION="$tmp/destination"

  "$runner" "$@"
}

mkdir -p "$tmp/base" "$tmp/personal" "$tmp/work" "$tmp/config"
: > "$tmp/config/base.toml"
: > "$tmp/config/personal.toml"
: > "$tmp/config/work.toml"
printf 'shared\n' > "$tmp/base/dot_shared"
printf 'personal\n' > "$tmp/personal/dot_personal"
printf 'work\n' > "$tmp/work/dot_work"

if ! run_compose preflight personal; then
  fail 'preflight personal should succeed for distinct base and personal targets'
fi

if ! run_compose preflight work; then
  fail 'preflight work should succeed for distinct base and work targets'
fi

printf 'base collision\n' > "$tmp/base/dot_collision"
printf 'personal collision\n' > "$tmp/personal/dot_collision"
collision_stderr="$tmp/collision.stderr"
if run_compose preflight personal > /dev/null 2> "$collision_stderr"; then
  fail 'preflight personal should fail for a target ownership collision'
fi
if ! grep -Fq 'target ownership collision' "$collision_stderr"; then
  fail 'collision error should be written to stderr'
fi

if run_compose apply personal > /dev/null 2>&1; then
  fail 'apply should not be a supported command'
else
  apply_status=$?
fi
if [ "$apply_status" -ne 64 ]; then
  fail "apply should exit 64, got $apply_status"
fi

if [ -e "$tmp/destination" ]; then
  fail 'runner created the destination directory'
fi

printf 'test-compose: all assertions passed\n'
