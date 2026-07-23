#!/usr/bin/env bash
set -euo pipefail

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

repo_root=$(cd "$(dirname "$0")/.." && pwd)
worktree_parent=$(cd "$repo_root/../../.." && pwd)
personal_overlay="${OMP_PERSONAL_OVERLAY_ROOT:-$worktree_parent/chezmoi-personal/.worktrees/skill-ownership-context-reduction}"
work_overlay="${OMP_WORK_OVERLAY_ROOT:-$worktree_parent/chezmoi-work/.worktrees/skill-ownership-context-reduction}"
expected_skills="$tmp/skills.yml"

fail() {
  printf 'test-omp-composition: %s\n' "$1" >&2
  exit 1
}

for required in "$repo_root/.chezmoitemplates/omp/skills.yml" \
  "$personal_overlay/dot_omp/agent/config.yml.tmpl" \
  "$work_overlay/dot_omp/agent/config.yml.tmpl"; do
  [ -f "$required" ] || fail "missing required OMP source: $required"
done

cat > "$expected_skills" <<'EOF'
skills:
  enableClaudeUser: true
  enableAgentsUser: false
  enableCodexUser: false
  enablePiUser: false
EOF

render() {
  source=$1
  CHEZMOI_BASE_SOURCE="$repo_root" chezmoi execute-template \
    --source "$source" \
    --file "$source/dot_omp/agent/config.yml.tmpl"
}

personal_rendered="$tmp/personal.yml"
work_rendered="$tmp/work.yml"
render "$personal_overlay" > "$personal_rendered"
render "$work_overlay" > "$work_rendered"

if ! head -n 5 "$personal_rendered" | cmp -s "$expected_skills" -; then
  fail 'personal render does not begin with the exact shared skills toggles'
fi

if ! cmp -s "$expected_skills" "$work_rendered"; then
  diff -u "$expected_skills" "$work_rendered" >&2 || true
  fail 'work render must contain only the shared skills toggles'
fi

for setting in providers symbolPreset theme setupVersion modelRoles defaultThinkingLevel cycleOrder retry task; do
  if ! grep -Eq "^${setting}:" "$personal_rendered"; then
    fail "personal render lost ${setting}"
  fi
  if grep -Eq "^${setting}:" "$work_rendered"; then
    fail "work render leaked personal ${setting}"
  fi
done
