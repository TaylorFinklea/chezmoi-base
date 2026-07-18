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
  diff|verify)
    if [ "$#" -ne 0 ]; then
      printf '%s received unexpected arguments\n' "$subcommand" >&2
      exit 70
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

printf 'test-compose: all assertions passed\n'
