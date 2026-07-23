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

run_compose_tty() {
  export CHEZMOI_BASE_SOURCE="$tmp/base"
  export CHEZMOI_PERSONAL_SOURCE="${CHEZMOI_PERSONAL_SOURCE_OVERRIDE:-$tmp/personal}"
  export CHEZMOI_WORK_SOURCE="$tmp/work"
  export CHEZMOI_CONFIG_ROOT="$tmp/config"
  export CHEZMOI_STATE_ROOT="$tmp/state"
  export CHEZMOI_DESTINATION="$tmp/destination"
  export CHEZMOI_CALL_LOG="$call_log"

  PATH="$fake_bin:$PATH" /usr/bin/expect -f - -- "$runner" "$@" <<'EOF'
set timeout 10
set command [lindex $argv 0]
set arguments [lrange $argv 1 end]
spawn -noecho $command {*}$arguments
expect {
  -exact {[o]verwrite from source / [i]mport into source / [s]kip? } { send -- "o\r" }
  timeout { exit 72 }
}
expect eof
set result [wait]
exit [lindex $result 3]
EOF
}

assert_read_only_execution() {
  subcommand=$1
  role=$2
  overlay=$3
  expected_calls="$tmp/$subcommand-$role.expected"
  local skill_work expected_skill_check expected_skill_diff

  case "$role" in
    work) skill_work=$tmp/work ;;
    *) skill_work= ;;
  esac
  expected_skill_check="skillsync:check:profile=$role:base=$tmp/base:overlay=$overlay:work=$skill_work:home=$tmp/destination:state=$tmp/state/skillsync:require=0:non-interactive=0"
  expected_skill_diff="skillsync:diff:profile=$role:base=$tmp/base:overlay=$overlay:work=$skill_work:home=$tmp/destination:state=$tmp/state/skillsync:require=0:non-interactive=0"


  : > "$call_log"
  if ! run_compose "$subcommand" "$role"; then
    fail "$subcommand $role should succeed"
  fi

  {
    printf 'managed:%s\n' "$tmp/base"
    printf 'managed:%s\n' "$overlay"
    printf '%s\n' "$expected_skill_check"
    printf '%s:%s\n' "$subcommand" "$tmp/base"
    printf '%s:%s\n' "$subcommand" "$overlay"
    if [ "$subcommand" = diff ]; then
      printf '%s\n' "$expected_skill_diff"
    fi
  } > "$expected_calls"
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
      case "$target" in
        shared) target=base-target/shared ;;
        personal) target=overlay-target/personal ;;
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
  source-path)
    if [ "$#" -ne 2 ] || [ "$1" != '--' ]; then
      printf 'source-path received unexpected arguments\n' >&2
      exit 70
    fi
    printf '%s/dot_%s\n' "$source" "${2##*/}"
    ;;
  apply)
    original_args="$*"
    parent_dirs=0
    include_scripts=0
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --force) shift ;;
        --parent-dirs) parent_dirs=1; shift ;;
        --include)
          if [ "${2:-}" != scripts ]; then
            printf 'unexpected apply include: %s\n' "${2:-}" >&2
            exit 70
          fi
          include_scripts=1
          shift 2
          ;;
        --) shift; break ;;
        *) printf 'unexpected apply option: %s\n' "$1" >&2; exit 70 ;;
      esac
    done
    if [ "$include_scripts" -eq 1 ]; then
      if [ "$#" -ne 0 ]; then
        printf 'script-only apply received targets\n' >&2
        exit 70
      fi
      printf 'apply-scripts:%s:--include scripts\n' "$source" >> "$CHEZMOI_CALL_LOG"
      mkdir -p "$destination"
      : > "$destination/.script-applied-${source##*/}"
      exit 0
    fi
    if [ "$#" -eq 0 ]; then
      printf 'bare apply is forbidden\n' >&2
      exit 70
    fi
    if [ "${FAKE_CHEZMOI_APPLY_STATUS:-0}" -ne 0 ]; then
      exit "$FAKE_CHEZMOI_APPLY_STATUS"
    fi
    printf 'apply-args:%s:%s\n' "$source" "$original_args" >> "$CHEZMOI_CALL_LOG"
    for target in "$@"; do
      parent=${target%/*}
      if [ ! -d "$parent" ] && [ "$parent_dirs" -ne 1 ]; then
        printf 'missing parent without --parent-dirs: %s\n' "$parent" >&2
        exit 71
      fi
      mkdir -p "$parent"
      : > "$target"
    done
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
cat > "$fake_bin/skillsync" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

command=${1:-}
shift
profile=
base=
overlay=
work=
home=
state=
require=0
non_interactive=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --profile) profile=$2; shift 2 ;;
    --base-root) base=$2; shift 2 ;;
    --overlay-root) overlay=$2; shift 2 ;;
    --work-root) work=$2; shift 2 ;;
    --home) home=$2; shift 2 ;;
    --state-root) state=$2; shift 2 ;;
    --require-sources) require=1; shift ;;
    --non-interactive) non_interactive=1; shift ;;
    *) printf 'unexpected skillsync argument: %s\n' "$1" >&2; exit 70 ;;
  esac
done
if [ -z "$command" ] || [ -z "$profile" ] || [ -z "$base" ] || [ -z "$overlay" ] || [ -z "$home" ] || [ -z "$state" ]; then
  printf 'invalid skillsync invocation\n' >&2
  exit 70
fi
if [ "$command" = check ] && [ "$profile" = work ] && [ "${FAKE_SKILLSYNC_WORK_SOURCE_MISSING:-0}" = 1 ]; then
  exit 66
fi
printf 'skillsync:%s:profile=%s:base=%s:overlay=%s:work=%s:home=%s:state=%s:require=%s:non-interactive=%s\n' \
  "$command" "$profile" "$base" "$overlay" "$work" "$home" "$state" "$require" "$non_interactive" >> "$CHEZMOI_CALL_LOG"
case "$command" in
  check)
    exit "${FAKE_SKILLSYNC_CHECK_STATUS:-0}"
    ;;
  diff)
    exit "${FAKE_SKILLSYNC_DIFF_STATUS:-0}"
    ;;
  sync)
    exit "${FAKE_SKILLSYNC_SYNC_STATUS:-0}"
    ;;
  *)
    printf 'unexpected skillsync command: %s\n' "$command" >&2
    exit 70
    ;;
esac
EOF
chmod +x "$fake_bin/skillsync"

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
base_target="$tmp/destination/base-target/shared"
overlay_target="$tmp/destination/overlay-target/personal"
if ! run_compose apply personal "$base_target" "$overlay_target"; then
  fail 'targeted apply should succeed for owned targets'
fi
if ! grep -Fqx "apply-args:$tmp/base:--parent-dirs -- $base_target" "$call_log"; then
  fail 'base-owned target should apply its distinct missing parent through the base source'
fi
if ! grep -Fqx "apply-args:$tmp/personal:--parent-dirs -- $overlay_target" "$call_log"; then
  fail 'overlay-owned target should apply its distinct missing parent through the overlay source'
fi
if [ ! -f "$base_target" ] || [ ! -f "$overlay_target" ]; then
  fail 'targeted apply should materialize targets in distinct fresh parent trees'
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
printf ' M fresh/clean/.zshrc\nM  .stale-state\nMM .claude/settings.json\n' > "$tmp/personal/fake-status.txt"
: > "$call_log"
if ! run_compose sync personal --no-pull; then
  fail 'sync should succeed when drift is clean or skippable'
fi
if ! grep -Fqx "apply-args:$tmp/personal:--parent-dirs -- $tmp/destination/fresh/clean/.zshrc" "$call_log"; then
  fail 'source-moved file should auto-apply with managed parents'
fi
if grep -F "apply-args" "$call_log" | grep -Fq '.stale-state'; then
  fail 'stale-state-only file should not be applied'
fi
if grep -F "apply-args" "$call_log" | grep -Fq '.claude/settings.json'; then
  fail 'runtime skip-list file should never be applied'
fi

# cosmetic MM auto-applies with --force
printf 'MM fresh/force/.pi-settings\n' > "$tmp/personal/fake-status.txt"
printf -- '-line one\n+line one \n' > "$tmp/personal/fake-diff.txt"
: > "$call_log"
if ! run_compose sync personal --no-pull; then
  fail 'sync with only cosmetic MM drift should succeed'
fi
if ! grep -Fqx "apply-args:$tmp/personal:--force --parent-dirs -- $tmp/destination/fresh/force/.pi-settings" "$call_log"; then
  fail 'whitespace-only MM drift should force-apply with managed parents'
fi
rm "$tmp/personal/fake-status.txt" "$tmp/personal/fake-diff.txt"

# run-on-change scripts apply in isolation; unrelated source drift stays untouched
script_target='.chezmoiscripts/install-managed-update.sh'
unrelated_target='unrelated/missing-file'
printf ' R %s\nM  %s\n' "$script_target" "$unrelated_target" > "$tmp/personal/fake-status.txt"
rm -rf "$tmp/destination"
: > "$call_log"
if ! run_compose sync personal --no-pull --non-interactive > "$tmp/script-sync.out" 2>&1; then
  cat "$tmp/script-sync.out" >&2
  fail 'sync should apply pending scripts without entering the decision queue'
fi
if [ "$(grep -Fc "apply-scripts:$tmp/personal:--include scripts" "$call_log")" -ne 1 ]; then
  fail 'sync should invoke script-only apply exactly once for the source'
fi
if grep -Fq "$script_target" "$tmp/script-sync.out"; then
  fail 'script pseudo-target should not enter the decision queue'
fi
if grep -F "apply-scripts:" "$call_log" | grep -Fq -- '--force'; then
  fail 'script-only apply must not use --force'
fi
if [ ! -f "$tmp/destination/.script-applied-personal" ]; then
  fail 'script-only apply should create the fake execution marker'
fi
if [ -e "$tmp/destination/$unrelated_target" ]; then

  fail 'script-only apply should not materialize unrelated file drift'
fi
rm "$tmp/personal/fake-status.txt"

# --- decisions in non-interactive mode ---
printf 'MM fresh/decision/.tmux.conf\n' > "$tmp/personal/fake-status.txt"
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

: > "$call_log"
if ! run_compose_tty sync personal --no-pull > "$tmp/overwrite.out" 2>&1; then
  cat "$tmp/overwrite.out" >&2
  fail 'interactive overwrite should resolve the pending decision'
fi
if ! grep -Fqx "apply-args:$tmp/personal:--force --parent-dirs -- $tmp/destination/fresh/decision/.tmux.conf" "$call_log"; then
  fail 'interactive overwrite should force-apply its distinct missing parent'
fi
if [ ! -f "$tmp/destination/fresh/decision/.tmux.conf" ]; then
  fail 'interactive overwrite should materialize the selected target'
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

# --- Skillsync composition ordering and failure propagation ---
: > "$call_log"
if ! run_compose preflight work; then
  fail 'work preflight should validate the catalog without requiring skill sources'
fi
if ! grep -Fqx "skillsync:check:profile=work:base=$tmp/base:overlay=$tmp/work:work=$tmp/work:home=$tmp/destination:state=$tmp/state/skillsync:require=0:non-interactive=0" "$call_log"; then
  fail 'work preflight should check the work catalog without --require-sources'
fi

: > "$call_log"
if ! run_compose preflight work --require-sources; then
  fail 'work preflight should support explicit skill-source validation'
fi
if ! grep -Fqx "skillsync:check:profile=work:base=$tmp/base:overlay=$tmp/work:work=$tmp/work:home=$tmp/destination:state=$tmp/state/skillsync:require=1:non-interactive=0" "$call_log"; then
  fail 'explicit work preflight should require skill sources'
fi

: > "$call_log"
if FAKE_SKILLSYNC_CHECK_STATUS=23 run_compose diff personal > /dev/null 2>&1; then
  fail 'a failed skillsync check should fail diff'
else
  skillsync_check_status=$?
fi
if [ "$skillsync_check_status" -ne 23 ]; then
  fail "skillsync check failure should propagate exit 23, got $skillsync_check_status"
fi
if grep -Eq '^(diff:|skillsync:diff:)' "$call_log"; then
  fail 'diff must not continue after a failed skillsync preflight check'
fi

printf 'base collision\n' > "$tmp/base/dot_collision"
printf 'personal collision\n' > "$tmp/personal/dot_collision"
: > "$call_log"
if run_compose preflight personal > /dev/null 2>&1; then
  fail 'preflight collision should still fail before skillsync runs'
fi
if grep -q '^skillsync:' "$call_log"; then
  fail 'skillsync check must run only after successful ownership validation'
fi
rm "$tmp/base/dot_collision" "$tmp/personal/dot_collision"

: > "$call_log"
if FAKE_SKILLSYNC_DIFF_STATUS=24 run_compose diff personal > /dev/null 2>&1; then
  fail 'a failed skillsync diff should fail compose diff'
else
  skillsync_diff_status=$?
fi
if [ "$skillsync_diff_status" -ne 24 ]; then
  fail "skillsync diff failure should propagate exit 24, got $skillsync_diff_status"
fi
if ! grep -Fqx "skillsync:diff:profile=personal:base=$tmp/base:overlay=$tmp/personal:work=:home=$tmp/destination:state=$tmp/state/skillsync:require=0:non-interactive=0" "$call_log"; then
  fail 'personal diff should append a source-isolated skillsync diff'
fi
if grep -q '^apply-' "$call_log"; then
  fail 'compose diff must never apply managed targets'
fi

line_of() {
  grep -n -m 1 -Fx "$1" "$call_log" | cut -d: -f1
}

: > "$call_log"
if ! run_compose sync personal; then
  fail 'clean sync should complete Skills only after clean chezmoi composition'
fi
pull_line=$(line_of "git-pull:$tmp/base")
managed_line=$(line_of "managed:$tmp/base")
check_line=$(line_of "skillsync:check:profile=personal:base=$tmp/base:overlay=$tmp/personal:work=:home=$tmp/destination:state=$tmp/state/skillsync:require=1:non-interactive=0")
status_line=$(line_of "status:$tmp/base")
sync_line=$(line_of "skillsync:sync:profile=personal:base=$tmp/base:overlay=$tmp/personal:work=:home=$tmp/destination:state=$tmp/state/skillsync:require=0:non-interactive=1")
if [ "$pull_line" -ge "$managed_line" ] || [ "$managed_line" -ge "$check_line" ] || [ "$check_line" -ge "$status_line" ] || [ "$status_line" -ge "$sync_line" ]; then
  fail 'sync must pull, preflight/check, apply/check chezmoi, then skillsync in order'
fi
if grep -q '^apply-' "$call_log"; then
  fail 'clean sync must not issue a bare chezmoi apply'
fi

printf ' M blocked/by-check\n' > "$tmp/personal/fake-status.txt"
: > "$call_log"
if FAKE_SKILLSYNC_CHECK_STATUS=23 run_compose sync personal --no-pull > /dev/null 2>&1; then
  fail 'sync must stop when its source-required skillsync check fails'
else
  skillsync_sync_check_status=$?
fi
if [ "$skillsync_sync_check_status" -ne 23 ]; then
  fail "sync skillsync check failure should propagate exit 23, got $skillsync_sync_check_status"
fi
if grep -Eq '^(status:|apply-|skillsync:sync:)' "$call_log"; then
  fail 'no chezmoi apply or skillsync sync may follow a failed sync preflight'
fi
rm "$tmp/personal/fake-status.txt"

printf ' M blocked/missing-work-source\n' > "$tmp/work/fake-status.txt"
: > "$call_log"
if FAKE_SKILLSYNC_WORK_SOURCE_MISSING=1 run_compose sync work --no-pull > /dev/null 2>&1; then
  fail 'missing external work skill source should fail work sync'
else
  missing_work_status=$?
fi
if [ "$missing_work_status" -ne 66 ]; then
  fail "missing work skill source should exit 66, got $missing_work_status"
fi
if grep -Eq '^(status:|apply-|skillsync:sync:)' "$call_log"; then
  fail 'missing work skill source must abort before chezmoi applies anything'
fi
rm "$tmp/work/fake-status.txt"

printf ' M blocked/apply-failure\n' > "$tmp/personal/fake-status.txt"
: > "$call_log"
if FAKE_CHEZMOI_APPLY_STATUS=45 run_compose sync personal --no-pull > /dev/null 2>&1; then
  fail 'a failed chezmoi apply should fail sync'
else
  chezmoi_apply_status=$?
fi
if [ "$chezmoi_apply_status" -ne 45 ]; then
  fail "chezmoi apply failure should propagate exit 45, got $chezmoi_apply_status"
fi
if grep -q '^skillsync:sync:' "$call_log"; then
  fail 'skillsync sync must not follow a failed chezmoi apply'
fi
rm "$tmp/personal/fake-status.txt"

: > "$call_log"
if FAKE_SKILLSYNC_SYNC_STATUS=17 run_compose sync personal --no-pull > /dev/null 2>&1; then
  fail 'skillsync conflict should fail sync and remain non-interactive'
else
  skillsync_sync_status=$?
fi
if [ "$skillsync_sync_status" -ne 17 ]; then
  fail "skillsync sync failure should propagate exit 17, got $skillsync_sync_status"
fi
if ! grep -q '^osascript-notify$' "$call_log"; then
  fail 'skillsync conflicts should notify after reporting their failure'
fi

"$repo_root/tests/test-local-mode.sh"

printf 'test-compose: all assertions passed\n'
