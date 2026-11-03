#!/usr/bin/env bash
set -euo pipefail

if ! command -v bd >/dev/null 2>&1; then
  echo "SKIP: bd is not installed"
  exit 0
fi

fixture_root="$(mktemp -d "${TMPDIR:-/tmp}/beads-local-only-init.XXXXXX")"
trap 'rm -rf "$fixture_root"' EXIT

fixture_home="$fixture_root/home"
mkdir -p "$fixture_home/.config"

for override in BEADS_DIR BEADS_DB BEADS_DATABASE BD_HOME BD_DB BD_DIR; do
  if [[ "${!override+x}" == x ]]; then
    echo "SKIP: refusing to run with preexisting $override override"
    exit 0
  fi
done

run_bd() {
  env HOME="$fixture_home" XDG_CONFIG_HOME="$fixture_home/.config" "$@"
}

make_project() {
  local name="$1"
  mkdir -p "$fixture_root/$name"
  git -C "$fixture_root/$name" init -q
  git -C "$fixture_root/$name" remote add origin "https://example.invalid/$name"
}

make_project sandbox_only
(
  cd "$fixture_root/sandbox_only"
  env -u BD_DOLT_LOCAL_ONLY HOME="$fixture_home" XDG_CONFIG_HOME="$fixture_home/.config" bd init --skip-agents --skip-hooks --role contributor --non-interactive --sandbox >/dev/null
  remotes="$(run_bd bd --sandbox dolt remote list)"
  if [[ "$remotes" != *"origin"* ]]; then
    echo "FAIL: expected positive control to infer Git origin with --sandbox; got: $remotes" >&2
    exit 1
  fi
)

make_project local_only
(
  cd "$fixture_root/local_only"
  run_bd BD_DOLT_LOCAL_ONLY=true bd init --skip-agents --skip-hooks --role contributor --non-interactive --sandbox >/dev/null
  role="$(git config --local --get beads.role)"
  [[ "$role" == "contributor" ]] || {
    echo "FAIL: expected contributor role, got: $role" >&2
    exit 1
  }
  [[ -d .beads/embeddeddolt ]] || {
    echo "FAIL: expected a project-local embedded Dolt store" >&2
    exit 1
  }

  run_bd bd --sandbox config set dolt.local-only true >/dev/null
  local_only="$(run_bd bd --sandbox config get dolt.local-only)"
  [[ "$local_only" == "true" ]] || {
    echo "FAIL: expected persisted dolt.local-only=true, got: $local_only" >&2
    exit 1
  }

  remotes="$(run_bd bd --sandbox dolt remote list)"
  if [[ "$remotes" != *"No remotes configured"* ]]; then
    echo "FAIL: expected no Dolt remotes after local-only init, got: $remotes" >&2
    exit 1
  fi
)

echo "PASS: --sandbox alone inferred origin; BD_DOLT_LOCAL_ONLY=true prevented it, contributor role was retained, and local-only persisted."
