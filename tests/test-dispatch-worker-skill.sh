#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
personal_root="${CHEZMOI_PERSONAL_ROOT:-$repo_root/../chezmoi-personal}"

new_skill="$repo_root/.skills-src/skills/dispatch-worker/SKILL.md"
old_skill="$repo_root/.skills-src/skills/dispatch-to-pi/SKILL.md"

[ -f "$new_skill" ] || { echo 'FAIL: dispatch-worker skill missing' >&2; exit 1; }
[ ! -e "$old_skill" ] || { echo 'FAIL: dispatch-to-pi skill still exists' >&2; exit 1; }
grep -q '^name: dispatch-worker$' "$new_skill"
grep -q 'omp --model <dispatch-id> --thinking <effort> --auto-approve --no-session' "$new_skill"
grep -q 'pi-liveness --model <dispatch-id> --thinking <effort> --approve' "$new_skill"
grep -q 'Musterroll' "$new_skill"
grep -q 'Afterfact' "$new_skill"

active_files=(
  "$repo_root/.skillcatalog.toml"
  "$repo_root/.skills-src/skills/delegate/SKILL.md"
  "$repo_root/.skills-src/skills/guildhall-orchestration/SKILL.md"
  "$repo_root/.skills-src/skills/loops/SKILL.md"
  "$personal_root/AGENTS.md"
  "$personal_root/dot_claude/templates/tiers.md"
  "$personal_root/dot_claude/create_model-scorecard.md"
)

if grep -nE 'dispatch-to-pi|pi-dispatch' "${active_files[@]}"; then
  echo 'FAIL: active guidance still references retired Pi dispatch names' >&2
  exit 1
fi

grep -q '^name = "dispatch-worker"$' "$repo_root/.skillcatalog.toml"
! grep -q '^name = "dispatch-to-pi"$' "$repo_root/.skillcatalog.toml"
[ ! -e "$personal_root/dot_claude/agents/pi-dispatch.md" ] || {
  echo 'FAIL: legacy pi-dispatch wrapper still exists' >&2
  exit 1
}

printf '%s\n' 'ok: harness-neutral dispatch-worker skill'
