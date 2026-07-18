#!/usr/bin/env bash
set -euo pipefail

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

repo_root=$(cd "$(dirname "$0")/.." && pwd)
runner="$repo_root/scripts/chezmoi-compose"
fake_bin="$tmp/bin"
call_log="$tmp/chezmoi.calls"

fail() {
  printf 'test-compose: %s\n' "$1" >&2
  exit 1
}

if ! grep -Fqx 'PERSONAL_SOURCE="${CHEZMOI_PERSONAL_SOURCE:-$HOME/git/chezmoi-personal}"' "$runner"; then
  fail 'personal source default is not chezmoi-personal'
fi

run_compose() {
  export CHEZMOI_BASE_SOURCE="$tmp/base"
  export CHEZMOI_PERSONAL_SOURCE="${CHEZMOI_PERSONAL_SOURCE_OVERRIDE:-$tmp/personal}"
  export CHEZMOI_WORK_SOURCE="$tmp/work"
  export CHEZMOI_CONFIG_ROOT="$tmp/config"
  export CHEZMOI_STATE_ROOT="$tmp/state"
  export CHEZMOI_DESTINATION="$tmp/destination"
  export CHEZMOI_CALL_LOG="$call_log"

  PATH="$fake_bin:$PATH" "$runner" "$@"
}

assert_read_only_execution() {
  subcommand=$1
  role=$2
  overlay=$3
  expected_calls="$tmp/$subcommand-$role.expected"

  : > "$call_log"
  if ! run_compose "$subcommand" "$role"; then
    fail "$subcommand $role should succeed"
  fi

  cat > "$expected_calls" <<EOF
managed:$tmp/base
managed:$overlay
$subcommand:$tmp/base
$subcommand:$overlay
EOF
  if ! cmp -s "$expected_calls" "$call_log"; then
    fail "$subcommand $role should preflight first and run base-first"
  fi

  if [ -e "$tmp/destination" ]; then
    fail "$subcommand $role created the destination directory"
  fi
}

mkdir -p "$tmp/base" "$tmp/personal" "$tmp/work" "$tmp/config" "$fake_bin"
: > "$tmp/config/base.toml"
: > "$tmp/config/personal.toml"
: > "$tmp/config/work.toml"
printf 'shared\n' > "$tmp/base/dot_shared"
printf 'personal\n' > "$tmp/personal/dot_personal"
printf 'work\n' > "$tmp/work/dot_work"

cat > "$fake_bin/chezmoi" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

source=
destination=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --source)
      source=$2
      shift 2
      ;;
    --config|--persistent-state)
      shift 2
      ;;
    --destination)
      destination=$2
      shift 2
      ;;
    *)
      break
      ;;
  esac
done

if [ -z "$source" ] || [ -z "$destination" ] || [ "$#" -eq 0 ]; then
  printf 'invalid chezmoi invocation\n' >&2
  exit 70
fi

subcommand=$1
shift
printf '%s:%s\n' "$subcommand" "$source" >> "$CHEZMOI_CALL_LOG"

case "$subcommand" in
  managed)
    if [ "$#" -ne 4 ] || [ "$1" != '--include' ] || [ "$2" != 'files,symlinks' ] || [ "$3" != '--path-style' ] || [ "$4" != 'absolute' ]; then
      printf 'managed invocation did not request absolute files and symlinks\n' >&2
      exit 70
    fi

    for managed_path in "$source"/dot_* "$source"/symlink_*; do
      if [ ! -f "$managed_path" ] && [ ! -L "$managed_path" ]; then
        continue
      fi

      name=${managed_path##*/}
      case "$name" in
        dot_*) target=${name#dot_} ;;
        symlink_*) target=${name#symlink_} ;;
        *) continue ;;
      esac
      printf '%s/%s\n' "$destination" "$target"
    done
    ;;
  verify)
    if [ "$#" -ne 0 ]; then
      printf 'verify received unexpected arguments\n' >&2
      exit 70
    fi
    ;;
  diff)
    if [ "$#" -eq 0 ]; then
      :
    elif [ -f "$source/fake-diff.txt" ]; then
      cat "$source/fake-diff.txt"
    fi
    ;;
  status)
    if [ -f "$source/fake-status.txt" ]; then
      cat "$source/fake-status.txt"
    fi
    ;;
  apply)
    printf 'apply-args:%s:%s\n' "$source" "$*" >> "$CHEZMOI_CALL_LOG"
    ;;
  *)
    printf 'unexpected chezmoi subcommand: %s\n' "$subcommand" >&2
    exit 70
    ;;
esac
EOF
chmod +x "$fake_bin/chezmoi"

cat > "$fake_bin/git" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
repo=
if [ "${1:-}" = "-C" ]; then
  repo=$2
  shift 2
fi
sub=${1:-}
printf 'git-%s:%s\n' "$sub" "$repo" >> "$CHEZMOI_CALL_LOG"
case "$sub" in
  status) exit 0 ;;
  pull) if [ "${FAKE_GIT_PULL_FAIL:-0}" = "1" ]; then exit 1; fi ;;
esac
EOF
chmod +x "$fake_bin/git"

cat > "$fake_bin/osascript" <<'EOF'
#!/usr/bin/env bash
printf 'osascript-notify\n' >> "$CHEZMOI_CALL_LOG"
EOF
chmod +x "$fake_bin/osascript"

if ! run_compose preflight personal; then
  fail 'preflight personal should succeed for distinct base and personal targets'
fi

if ! run_compose preflight work; then
  fail 'preflight work should succeed for distinct base and work targets'
fi

printf 'base collision\n' > "$tmp/base/dot_collision"
printf 'personal collision\n' > "$tmp/personal/dot_collision"
collision_stderr="$tmp/file-collision.stderr"
if run_compose preflight personal > /dev/null 2> "$collision_stderr"; then
  fail 'preflight personal should fail for a file target ownership collision'
fi
if ! grep -Fq 'target ownership collision' "$collision_stderr"; then
  fail 'file collision error should be written to stderr'
fi
rm "$tmp/base/dot_collision" "$tmp/personal/dot_collision"

: > "$tmp/symlink-target"
ln -s "$tmp/symlink-target" "$tmp/base/symlink_collision"
ln -s "$tmp/symlink-target" "$tmp/personal/symlink_collision"
collision_stderr="$tmp/symlink-collision.stderr"
if run_compose preflight personal > /dev/null 2> "$collision_stderr"; then
  fail 'preflight personal should fail for a symlink target ownership collision'
fi
if ! grep -Fq 'target ownership collision' "$collision_stderr"; then
  fail 'symlink collision error should be written to stderr'
fi
rm "$tmp/base/symlink_collision" "$tmp/personal/symlink_collision"

assert_read_only_execution diff personal "$tmp/personal"
assert_read_only_execution verify work "$tmp/work"

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

# --- sync CLI plumbing ---
: > "$call_log"
if ! run_compose sync personal; then
  fail 'sync personal should succeed as a stub'
fi
if ! grep -Fqx "managed:$tmp/personal" "$call_log"; then
  fail 'sync personal should preflight the personal overlay'
fi

: > "$call_log"
if ! run_compose sync; then
  fail 'sync with no role should autodetect personal when personal source exists'
fi
if ! grep -Fqx "managed:$tmp/personal" "$call_log"; then
  fail 'sync autodetect should pick the personal overlay'
fi

: > "$call_log"
if ! CHEZMOI_PERSONAL_SOURCE_OVERRIDE="$tmp/nonexistent" run_compose sync; then
  fail 'sync autodetect should fall back to work when personal source is absent'
fi
if ! grep -Fqx "managed:$tmp/work" "$call_log"; then
  fail 'sync autodetect fallback should pick the work overlay'
fi

if run_compose sync --bogus-flag > /dev/null 2>&1; then
  fail 'sync should reject unknown flags'
fi

# --- targeted apply ---
: > "$call_log"
if ! run_compose apply personal "$tmp/destination/shared" "$tmp/destination/personal"; then
  fail 'targeted apply should succeed for owned targets'
fi
if ! grep -Fqx "apply-args:$tmp/base:-- $tmp/destination/shared" "$call_log"; then
  fail 'base-owned target should be applied through the base source'
fi
if ! grep -Fqx "apply-args:$tmp/personal:-- $tmp/destination/personal" "$call_log"; then
  fail 'overlay-owned target should be applied through the overlay source'
fi

if run_compose apply personal "$tmp/destination/unmanaged" > /dev/null 2>&1; then
  fail 'apply should reject an unmanaged target'
else
  unmanaged_status=$?
fi
if [ "$unmanaged_status" -ne 65 ]; then
  fail "unmanaged target should exit 65, got $unmanaged_status"
fi

# --- sync pull stage ---
mkdir -p "$tmp/base/.git" "$tmp/personal/.git" "$tmp/work/.git"
: > "$call_log"
if ! run_compose sync personal; then
  fail 'sync should succeed on clean state'
fi
if ! grep -Fqx "git-pull:$tmp/base" "$call_log"; then
  fail 'sync should ff-only pull the base repo'
fi
if ! grep -Fqx "git-pull:$tmp/personal" "$call_log"; then
  fail 'sync should ff-only pull the overlay repo'
fi
if ! head -1 "$call_log" | grep -q '^git-'; then
  fail 'sync should pull before any chezmoi call'
fi

: > "$call_log"
if ! run_compose sync personal --no-pull; then
  fail 'sync --no-pull should succeed'
fi
if grep -q '^git-' "$call_log"; then
  fail 'sync --no-pull should make no git calls'
fi

: > "$call_log"
export FAKE_GIT_PULL_FAIL=1
if ! run_compose sync personal; then
  fail 'sync should tolerate a failed pull and continue'
fi
unset FAKE_GIT_PULL_FAIL
if ! grep -Fqx "managed:$tmp/base" "$call_log"; then
  fail 'sync should still preflight after a failed pull'
fi

# --- sync classifier ---
printf ' M .zshrc\nM  .stale-state\nMM .claude/settings.json\n' > "$tmp/personal/fake-status.txt"
: > "$call_log"
if ! run_compose sync personal --no-pull; then
  fail 'sync should succeed when drift is clean or skippable'
fi
if ! grep -Fqx "apply-args:$tmp/personal:-- $tmp/destination/.zshrc" "$call_log"; then
  fail 'source-moved file should be auto-applied'
fi
if grep -F "apply-args" "$call_log" | grep -Fq '.stale-state'; then
  fail 'stale-state-only file should not be applied'
fi
if grep -F "apply-args" "$call_log" | grep -Fq '.claude/settings.json'; then
  fail 'runtime skip-list file should never be applied'
fi

# cosmetic MM auto-applies with --force
printf 'MM .pi-settings\n' > "$tmp/personal/fake-status.txt"
printf -- '-line one\n+line one \n' > "$tmp/personal/fake-diff.txt"
: > "$call_log"
if ! run_compose sync personal --no-pull; then
  fail 'sync with only cosmetic MM drift should succeed'
fi
if ! grep -Fqx "apply-args:$tmp/personal:--force -- $tmp/destination/.pi-settings" "$call_log"; then
  fail 'whitespace-only MM drift should force-apply'
fi
rm "$tmp/personal/fake-status.txt" "$tmp/personal/fake-diff.txt"

# --- decisions in non-interactive mode ---
printf 'MM .tmux.conf\n' > "$tmp/personal/fake-status.txt"
printf -- '-real old\n+real new\n' > "$tmp/personal/fake-diff.txt"
: > "$call_log"
decisions_out="$tmp/decisions.out"
if run_compose sync personal --no-pull --non-interactive > "$decisions_out" 2>&1; then
  fail 'sync with a real MM conflict should not exit 0'
else
  decisions_status=$?
fi
if [ "$decisions_status" -ne 2 ]; then
  fail "sync with pending decisions should exit 2, got $decisions_status"
fi
if grep -F "apply-args" "$call_log" | grep -Fq '.tmux.conf'; then
  fail 'a real MM conflict must not be applied non-interactively'
fi
if ! grep -Fq '.tmux.conf' "$decisions_out"; then
  fail 'pending decision should be listed in the report'
fi
if ! grep -Fqx 'osascript-notify' "$call_log"; then
  fail 'pending decisions should trigger a notification'
fi
rm "$tmp/personal/fake-status.txt" "$tmp/personal/fake-diff.txt"

# clean sync still exits 0 and prints a summary
: > "$call_log"
if ! run_compose sync personal --no-pull > "$tmp/clean.out" 2>&1; then
  fail 'clean sync should exit 0'
fi
if ! grep -Fq 'decisions pending: 0' "$tmp/clean.out"; then
  fail 'summary should report zero pending decisions'
fi

printf 'test-compose: all assertions passed\n'
