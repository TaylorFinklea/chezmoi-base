#!/usr/bin/env bash
set -euo pipefail

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

repo_root=$(cd "$(dirname "$0")/.." && pwd)
installer="$repo_root/run_onchange_after_20-install-herdr-ask.sh"
managed_config="$repo_root/private_Library/private_Application Support/herdr-ask/config.toml"
fake_bin="$tmp/bin"
state_dir="$tmp/state"
call_log="$tmp/calls.log"

fail() {
  printf 'test-herdr-ask-installer: %s\n' "$1" >&2
  exit 1
}

mkdir -p "$fake_bin" "$state_dir"

awk '
  /^\[backends\.omp\]$/ { capture = 1 }
  capture && /^\[/ && $0 != "[backends.omp]" { exit }
  capture { print }
' "$managed_config" > "$tmp/omp-config.actual"

cat > "$tmp/omp-config.expected" <<'EOF'
[backends.omp]
kind = "process"
command = [
  "omp",
  "--print",
  "--no-session",
  "--no-tools",
  "--no-lsp",
  "--no-pty",
  "--no-extensions",
  "--no-skills",
  "--no-rules",
  "--system-prompt",
  "{{system_prompt}}",
  "--model",
  "{{model}}",
]
prompt_transport = "stdin"
model = "auto"
timeout_seconds = 60
EOF

if ! cmp -s "$tmp/omp-config.expected" "$tmp/omp-config.actual"; then
  fail 'managed config does not contain the safe OMP backend'
fi

cat > "$fake_bin/brew" <<'EOF'
#!/bin/sh
set -eu
printf 'brew %s\n' "$*" >> "$HERDR_ASK_INSTALL_TEST_LOG"
case "$*" in
  'list --versions herdr-ask')
    if [ -f "$HERDR_ASK_INSTALL_TEST_STATE/formula-version" ]; then
      printf 'herdr-ask %s\n' "$(cat "$HERDR_ASK_INSTALL_TEST_STATE/formula-version")"
    else
      exit 1
    fi
    ;;
  'install taylorfinklea/tap/herdr-ask'|'upgrade taylorfinklea/tap/herdr-ask')
    printf '0.1.0\n' > "$HERDR_ASK_INSTALL_TEST_STATE/formula-version"
    ;;
  *) exit 64 ;;
esac
EOF

cat > "$fake_bin/herdr" <<'EOF'
#!/bin/sh
set -eu
printf 'herdr %s\n' "$*" >> "$HERDR_ASK_INSTALL_TEST_LOG"
case "$*" in
  'plugin list --plugin dev.herdr-ask --json')
    if [ -f "$HERDR_ASK_INSTALL_TEST_STATE/plugin-version" ]; then
      printf '{"id":"cli:plugin","result":{"plugins":[{"plugin_id":"dev.herdr-ask","version":"%s"}],"type":"plugin_list"}}\n' \
        "$(cat "$HERDR_ASK_INSTALL_TEST_STATE/plugin-version")"
    else
      printf '{"id":"cli:plugin","result":{"plugins":[],"type":"plugin_list"}}\n'
    fi
    ;;
  'plugin install TaylorFinklea/herdr-ask --ref v0.1.0 --yes')
    printf '0.1.0\n' > "$HERDR_ASK_INSTALL_TEST_STATE/plugin-version"
    ;;
  *) exit 64 ;;
esac
EOF

chmod +x "$fake_bin/brew" "$fake_bin/herdr"

if [ ! -f "$installer" ]; then
  fail 'managed installer is missing'
fi

sh -n "$installer"

export HERDR_ASK_INSTALL_TEST_LOG="$call_log"
export HERDR_ASK_INSTALL_TEST_STATE="$state_dir"

PATH="$fake_bin:/usr/bin:/bin" "$installer"

cat > "$tmp/first-run.expected" <<'EOF'
brew list --versions herdr-ask
brew install taylorfinklea/tap/herdr-ask
herdr plugin list --plugin dev.herdr-ask --json
herdr plugin install TaylorFinklea/herdr-ask --ref v0.1.0 --yes
EOF

if ! cmp -s "$tmp/first-run.expected" "$call_log"; then
  fail 'first run did not install both release channels'
fi

: > "$call_log"
PATH="$fake_bin:/usr/bin:/bin" "$installer"

cat > "$tmp/second-run.expected" <<'EOF'
brew list --versions herdr-ask
herdr plugin list --plugin dev.herdr-ask --json
EOF

if ! cmp -s "$tmp/second-run.expected" "$call_log"; then
  fail 'second run was not idempotent'
fi

printf '0.0.9\n' > "$state_dir/formula-version"
printf '0.0.9\n' > "$state_dir/plugin-version"
: > "$call_log"
PATH="$fake_bin:/usr/bin:/bin" "$installer"

cat > "$tmp/upgrade.expected" <<'EOF'
brew list --versions herdr-ask
brew upgrade taylorfinklea/tap/herdr-ask
herdr plugin list --plugin dev.herdr-ask --json
herdr plugin install TaylorFinklea/herdr-ask --ref v0.1.0 --yes
EOF

if ! cmp -s "$tmp/upgrade.expected" "$call_log"; then
  fail 'version change did not upgrade both release channels'
fi

printf 'test-herdr-ask-installer: all assertions passed\n'
