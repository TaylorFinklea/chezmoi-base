#!/usr/bin/env bash
set -euo pipefail

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

repo_root=$(cd "$(dirname "$0")/.." && pwd)
fixtures="$repo_root/tests/fixtures/skills"
cli="$repo_root/private_dot_local/bin/executable_skillsync"
worktree_parent=$(cd "$repo_root/../../.." && pwd)
personal_overlay="${SKILLSYNC_PERSONAL_OVERLAY_ROOT:-$worktree_parent/chezmoi-personal/.worktrees/skill-ownership-context-reduction}"
work_overlay="${SKILLSYNC_WORK_OVERLAY_ROOT:-$worktree_parent/chezmoi-work/.worktrees/skill-ownership-context-reduction}"
work_sources="$fixtures/work"
source_base_root="$repo_root"
uv_cache="$tmp/uv-cache"

fail() {
  printf 'test-skill-composition: %s\n' "$1" >&2
  exit 1
}

for required in "$fixtures" "$cli" "$personal_overlay" "$work_overlay" "$work_sources"; do
  [ -e "$required" ] || fail "missing required fixture or worktree: $required"
done

# Warm the uv script dependency once so command assertions see only skillsync output.
HOME="$tmp/uv-home" UV_CACHE_DIR="$uv_cache" "$cli" --help > /dev/null 2>&1
run_python() {
  UV_CACHE_DIR="$uv_cache" uv run --no-project --python '>=3.11' - "$@"
}


run_skillsync() {
  profile=$1
  home=$2
  config=$3
  state=$4
  overlay=$5
  work_root=$6
  command=$7
  shift 7

  HOME="$home" \
    UV_CACHE_DIR="$uv_cache" \
    XDG_CONFIG_HOME="$config" \
    XDG_STATE_HOME="$state/xdg" \
    "$cli" "$command" \
      --profile "$profile" \
      --base-root "$source_base_root" \
      --overlay-root "$overlay" \
      --work-root "$work_root" \
      --home "$home" \
      --state-root "$state" \
      "$@"
}

copy_skill() {
  source_root=$1
  target_root=$2
  name=$3
  mkdir -p "$target_root"
  cp -R "$source_root/$name" "$target_root/$name"
  rm -f "$target_root/$name/.skillsync-owner.json"
}

copy_skill_if_missing() {
  source_root=$1
  target_root=$2
  name=$3
  [ -e "$target_root/$name" ] || copy_skill "$source_root" "$target_root" "$name"
}

count_skill_dirs() {
  root=$1
  count=0
  shopt -s nullglob
  for child in "$root"/*; do
    [ -d "$child" ] || continue
    count=$((count + 1))
  done
  printf '%s\n' "$count"
}

collect_names() {
  shopt -s nullglob
  for root in "$@"; do
    for child in "$root"/*; do
      [ -d "$child" ] || continue
      printf '%s\n' "$(basename "$child")"
    done
  done | LC_ALL=C sort -u
}

assert_empty_file() {
  file=$1
  label=$2
  [ ! -s "$file" ] || fail "$label should be empty: $(cat "$file")"
}

assert_exact_file() {
  expected=$1
  actual=$2
  label=$3
  if ! cmp -s "$expected" "$actual"; then
    diff -u "$expected" "$actual" >&2 || true
    fail "$label did not match"
  fi
}

assert_projection_contract() {
  profile=$1
  home=$2
  state=$3
  overlay=$4
  rejected_overlay=$5
  expected_native=$6
  expected_codex=$7
  expected_pi=$8
  expected_hermes=$9

  run_python "$profile" "$repo_root/.skillcatalog.toml" "$overlay/.skillcatalog.toml" \
    "$rejected_overlay/.skillcatalog.toml" "$home" "$state/ledger.json" \
    "$expected_native" "$expected_codex" "$expected_pi" "$expected_hermes" <<'PY'
import json
import sys
import tomllib
from pathlib import Path

(
    profile,
    base_catalog_path,
    overlay_catalog_path,
    rejected_catalog_path,
    home,
    ledger_path,
    *expected_counts,
) = sys.argv[1:]
home_path = Path(home)
target_paths = {
    "native": home_path / ".claude" / "skills",
    "codex": home_path / ".codex" / "skills",
    "pi": home_path / ".pi" / "agent" / "skills",
    "hermes": home_path / ".hermes" / "skills",
}

def catalog(path):
    return tomllib.loads(Path(path).read_text())

base = catalog(base_catalog_path)
overlay = catalog(overlay_catalog_path)
rejected = catalog(rejected_catalog_path)
expected = {target: {} for target in target_paths}
owners = {}
for source in (base, overlay):
    for skill in source["skills"]:
        owners[skill["name"]] = source["owner"]
        for target in skill["targets"]:
            expected[target][skill["name"]] = source["owner"]

ledger = json.loads(Path(ledger_path).read_text())
actual_union = set()
for target, root in target_paths.items():
    actual = {
        child.name
        for child in root.iterdir()
        if child.is_dir() and not child.name.startswith(".")
    } if root.exists() else set()
    tolerated_unmanaged = {"fixture-unmanaged"} if profile == "personal" and target == "native" else set()
    managed_actual = actual - tolerated_unmanaged
    if managed_actual != set(expected[target]):
        raise SystemExit(
            f"{profile} {target} names differ: expected={sorted(expected[target])}, actual={sorted(actual)}"
        )
    if len(managed_actual) != int(expected_counts[("native", "codex", "pi", "hermes").index(target)]):
        raise SystemExit(f"{profile} {target} count differs")
    for name in managed_actual:
        actual_union.add(name)
        key = f"{target}:{name}"
        entry = ledger["targets"].get(key)
        if entry is None:
            raise SystemExit(f"{profile} missing ledger entry for {key}")
        if entry.get("owner") != expected[target][name]:
            raise SystemExit(f"{profile} wrong ledger owner for {key}: {entry!r}")
        if str(home_path) in str(entry.get("source", "")):
            raise SystemExit(f"{profile} ledger leaked an absolute temporary path for {key}")
        stamp = json.loads((root / name / ".skillsync-owner.json").read_text())
        if stamp.get("owner") != expected[target][name]:
            raise SystemExit(f"{profile} wrong owner stamp for {key}: {stamp!r}")

if actual_union != set(owners):
    raise SystemExit(
        f"{profile} effective role set differs: expected={sorted(owners)}, actual={sorted(actual_union)}"
    )
leaked = actual_union & {skill["name"] for skill in rejected["skills"]}
if leaked:
    raise SystemExit(f"{profile} leaked names from excluded role: {sorted(leaked)}")
PY
}

assert_audit_contract() {
  profile=$1
  home=$2
  config=$3
  state=$4
  overlay=$5
  expected_manual=$6
  expected_unmanaged=$7
  audit_json="$tmp/$profile-audit.json"

  run_skillsync "$profile" "$home" "$config" "$state" "$overlay" "$work_sources" audit --format json > "$audit_json"
  run_python "$audit_json" "$expected_manual" "$expected_unmanaged" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1]))
manual = report["manual"]
unmanaged = report["unmanaged"]
if len(manual) != int(sys.argv[2]):
    raise SystemExit(f"unexpected manual count: {len(manual)}")
if len(unmanaged) != int(sys.argv[3]):
    raise SystemExit(f"unexpected unmanaged count: {unmanaged}")
if report["collisions"]:
    raise SystemExit(f"unexpected collisions: {report['collisions']}")
PY
}

write_migration_expected() {
  profile=$1
  home=$2
  overlay=$3
  conflict_name=$4
  verb=$5
  stdout_file=$6
  stderr_file=$7

  run_python "$repo_root/.skillcatalog.toml" "$overlay/.skillcatalog.toml" "$home" \
    "$conflict_name" "$verb" > "$stdout_file" 2> "$stderr_file" <<'PY'
import sys
import tomllib
from pathlib import Path

base_catalog, overlay_catalog, home, conflict, verb = sys.argv[1:]
home = Path(home)
roots = {
    "native": home / ".claude" / "skills",
    "codex": home / ".codex" / "skills",
    "pi": home / ".pi" / "agent" / "skills",
    "hermes": home / ".hermes" / "skills",
}
records = []
for path in (base_catalog, overlay_catalog):
    source = tomllib.loads(Path(path).read_text())
    records.extend(source["skills"])
for record in sorted(records, key=lambda item: item["name"]):
    for target in record["targets"]:
        if not (roots[target] / record["name"]).exists():
            continue
        if record["name"] == conflict and target == "native":
            print(
                f"skillsync: refuse adopt {target}/{record['name']} "
                "— on-disk content does not match catalog source",
                file=sys.stderr,
            )
        else:
            print(f"skillsync: {verb} {target}/{record['name']}")
prune_verb = "would prune" if verb == "would adopt" else "pruned"
for retired in ("migrate-slim-overlay", "purge-migrate-skills"):
    print(f"skillsync: {prune_verb} native/{retired} (retired, stamped)")
PY
}

metadata_characters_from_roots() {
  run_python "$@" <<'PY'
import json
import re
import sys
from pathlib import Path

descriptions = {}
for raw_root in sys.argv[1:]:
    root = Path(raw_root)
    if not root.exists():
        continue
    for child in sorted(root.iterdir()):
        skill_md = child / "SKILL.md"
        if not child.is_dir() or not skill_md.exists():
            continue
        frontmatter = skill_md.read_text().split("---\n", 2)[1]
        name_match = re.search(r"^name:\s*(\S+)\s*$", frontmatter, re.MULTILINE)
        description_match = re.search(r"^description:\s*(.+?)\s*$", frontmatter, re.MULTILINE)
        if name_match is None or description_match is None:
            raise SystemExit(f"missing single-line name or description: {skill_md}")
        name = name_match.group(1)
        if name == "fixture-unmanaged":
            continue
        raw_description = description_match.group(1)
        if raw_description.startswith('"'):
            description = json.loads(raw_description)
        elif raw_description.startswith("'"):
            description = raw_description[1:-1].replace("''", "'")
        else:
            description = raw_description
        descriptions.setdefault(name, description)
print(sum(len(description) for description in descriptions.values()))
PY
}

legacy_collision_count() {
  run_python "$@" <<'PY'
import sys
from collections import Counter
from pathlib import Path

counts = Counter()
for raw in sys.argv[1:]:
    root = Path(raw)
    if root.exists():
        counts.update(child.name for child in root.iterdir() if child.is_dir() and not child.name.startswith("."))
print(sum(count > 1 for count in counts.values()))
PY
}

base_render_home="$tmp/personal-render/home"
base_render_config="$tmp/personal-render/config"
base_render_state="$tmp/personal-render/state"
mkdir -p "$base_render_home" "$base_render_config" "$base_render_state"
if ! run_skillsync personal "$base_render_home" "$base_render_config" "$base_render_state" \
  "$personal_overlay" "$work_sources" sync > "$tmp/personal-render.out" 2> "$tmp/personal-render.err"; then
  fail 'initial personal render should succeed'
fi
assert_empty_file "$tmp/personal-render.err" 'initial personal render stderr'
assert_projection_contract personal "$base_render_home" "$base_render_state" "$personal_overlay" \
  "$work_overlay" 40 48 34 11

# Build a read-only, representative snapshot of every current manual root.
legacy_home="$tmp/legacy/home"
mkdir -p "$legacy_home"
legacy_native="$legacy_home/.claude/skills"
legacy_agents="$legacy_home/.agents/skills"
legacy_codex="$legacy_home/.codex/skills"
legacy_copilot="$legacy_home/.copilot/skills"
legacy_pi="$legacy_home/.pi/agent/skills"
legacy_opencode="$legacy_home/.config/opencode/skills"
legacy_hermes="$legacy_home/.hermes/skills"
render_native="$base_render_home/.claude/skills"
render_codex="$base_render_home/.codex/skills"
render_pi="$base_render_home/.pi/agent/skills"
render_hermes="$base_render_home/.hermes/skills"

shopt -s nullglob
for child in "$render_native"/*; do
  copy_skill "$render_native" "$legacy_native" "$(basename "$child")"
done
copy_skill "$fixtures/retired" "$legacy_native" migrate-slim-overlay
copy_skill "$fixtures/retired" "$legacy_native" purge-migrate-skills

pi_index=0
for child in "$render_pi"/*; do
  pi_index=$((pi_index + 1))
  name=$(basename "$child")
  if [ "$pi_index" -le 10 ]; then
    copy_skill "$render_pi" "$legacy_pi" "$name"
    copy_skill "$render_codex" "$legacy_codex" "$name"
  elif [ "$pi_index" -le 12 ]; then
    copy_skill "$render_codex" "$legacy_codex" "$name"
  elif [ "$pi_index" -le 23 ]; then
    copy_skill "$render_pi" "$legacy_agents" "$name"
    copy_skill "$render_codex" "$legacy_codex" "$name"
  else
    copy_skill "$render_pi" "$legacy_agents" "$name"
  fi
done
for child in "$render_codex"/*; do
  name=$(basename "$child")
  [ -e "$render_pi/$name" ] || copy_skill "$render_codex" "$legacy_codex" "$name"
done
native_index=0
for child in "$render_native"/*; do
  native_index=$((native_index + 1))
  name=$(basename "$child")
  [ "$native_index" -le 19 ] && copy_skill "$render_native" "$legacy_copilot" "$name"
  [ "$native_index" -le 11 ] && copy_skill "$render_native" "$legacy_opencode" "$name"
done
for child in "$render_hermes"/*; do
  copy_skill "$render_hermes" "$legacy_hermes" "$(basename "$child")"
done
copy_skill "$fixtures/system" "$legacy_agents" imagegen
copy_skill "$fixtures/system" "$legacy_agents" openai-docs
copy_skill "$fixtures/system" "$legacy_codex/.system" imagegen
copy_skill "$fixtures/system" "$legacy_codex/.system" openai-docs
copy_skill "$fixtures/plugins" "$legacy_home/.claude/plugins/fake-plugin/skills" fake-plugin

[ "$(count_skill_dirs "$legacy_native")" = 42 ] || fail 'legacy Claude fixture count should be 42'
[ "$(count_skill_dirs "$legacy_agents")" = 24 ] || fail 'legacy .agents fixture count should be 24'
[ "$(count_skill_dirs "$legacy_codex")" = 37 ] || fail 'legacy Codex fixture count should be 37'
[ "$(count_skill_dirs "$legacy_copilot")" = 19 ] || fail 'legacy Copilot fixture count should be 19'
[ "$(count_skill_dirs "$legacy_pi")" = 10 ] || fail 'legacy Pi fixture count should be 10'
[ "$(count_skill_dirs "$legacy_opencode")" = 11 ] || fail 'legacy OpenCode fixture count should be 11'
[ "$(count_skill_dirs "$legacy_hermes")" = 11 ] || fail 'legacy Hermes fixture count should be 11'

legacy_names="$tmp/legacy-names"
collect_names "$legacy_native" "$legacy_agents" "$legacy_codex" "$legacy_copilot" "$legacy_pi" \
  "$legacy_opencode" "$legacy_hermes" > "$legacy_names"
legacy_distinct=$(wc -l < "$legacy_names" | tr -d ' ')
legacy_physical=$((42 + 24 + 37 + 19 + 10 + 11 + 11))
legacy_collisions=$(legacy_collision_count "$legacy_native" "$legacy_agents" "$legacy_codex" \
  "$legacy_copilot" "$legacy_pi" "$legacy_opencode" "$legacy_hermes")
[ "$legacy_physical" = 154 ] || fail 'legacy physical projection count should be 154'
legacy_metadata=$(metadata_characters_from_roots "$legacy_native" "$legacy_agents" "$legacy_codex" \
  "$legacy_copilot" "$legacy_pi" "$legacy_opencode" "$legacy_hermes")
[ "$legacy_distinct" = 57 ] || fail "legacy distinct-name count should be 57, got $legacy_distinct"
[ "$legacy_collisions" -gt 0 ] || fail 'legacy snapshot should expose duplicated manual names'

# Seed migration targets only from legacy roots, retaining fake plugin/system trees untouched.
personal_home="$tmp/personal-migration/home"
personal_config="$tmp/personal-migration/config"
personal_state="$tmp/personal-migration/state"
mkdir -p "$personal_home" "$personal_config" "$personal_state"
personal_native="$personal_home/.claude/skills"
personal_codex="$personal_home/.codex/skills"
personal_pi="$personal_home/.pi/agent/skills"
personal_hermes="$personal_home/.hermes/skills"
for child in "$render_native"/*; do
  copy_skill "$legacy_native" "$personal_native" "$(basename "$child")"
done
for child in "$legacy_codex"/*; do
  copy_skill "$legacy_codex" "$personal_codex" "$(basename "$child")"
done
for child in "$legacy_pi"/*; do
  copy_skill "$legacy_pi" "$personal_pi" "$(basename "$child")"
done
for child in "$legacy_hermes"/*; do
  copy_skill "$legacy_hermes" "$personal_hermes" "$(basename "$child")"
done
copy_skill "$fixtures/unmanaged" "$personal_native" fixture-unmanaged
copy_skill "$fixtures/plugins" "$personal_home/.claude/plugins/fake-plugin/skills" fake-plugin
copy_skill "$fixtures/system" "$personal_codex/.system" imagegen
copy_skill "$fixtures/system" "$personal_codex/.system" openai-docs

retired_seed="$render_native/agentic-actions-auditor"
mkdir -p "$personal_native"
cp -R "$retired_seed" "$personal_native/migrate-slim-overlay"
cp -R "$retired_seed" "$personal_native/purge-migrate-skills"
run_python "$base_render_state/ledger.json" "$personal_state/ledger.json" <<'PY'
import json
import sys
from pathlib import Path

source = json.loads(Path(sys.argv[1]).read_text())
entry = source["targets"]["native:agentic-actions-auditor"]
Path(sys.argv[2]).write_text(json.dumps({
    "schema": 1,
    "targets": {
        "native:migrate-slim-overlay": entry,
        "native:purge-migrate-skills": entry,
    },
}, indent=2, sort_keys=True) + "\n")
PY

printf '\nhand-edited target fixture\n' >> "$personal_native/agentic-actions-auditor/SKILL.md"
plugin_before="$tmp/plugin-before"
system_imagegen_before="$tmp/system-imagegen-before"
system_docs_before="$tmp/system-docs-before"
cp "$personal_home/.claude/plugins/fake-plugin/skills/fake-plugin/SKILL.md" "$plugin_before"
cp "$personal_codex/.system/imagegen/SKILL.md" "$system_imagegen_before"
cp "$personal_codex/.system/openai-docs/SKILL.md" "$system_docs_before"
cp "$personal_state/ledger.json" "$tmp/migrate-dry-run-ledger-before.json"

dry_expected_out="$tmp/migrate-dry.expected.out"
dry_expected_err="$tmp/migrate-dry.expected.err"
write_migration_expected personal "$personal_home" "$personal_overlay" agentic-actions-auditor \
  'would adopt' "$dry_expected_out" "$dry_expected_err"
set +e
run_skillsync personal "$personal_home" "$personal_config" "$personal_state" \
  "$personal_overlay" "$work_sources" migrate > "$tmp/migrate-dry.out" 2> "$tmp/migrate-dry.err"
migrate_dry_status=$?
set -e
[ "$migrate_dry_status" -eq 1 ] || fail "personal migration dry-run should exit 1, got $migrate_dry_status"
assert_exact_file "$dry_expected_out" "$tmp/migrate-dry.out" 'personal migration dry-run adoption/removal list'
assert_exact_file "$dry_expected_err" "$tmp/migrate-dry.err" 'personal migration dry-run conflict list'
assert_exact_file "$tmp/migrate-dry-run-ledger-before.json" "$personal_state/ledger.json" 'migration dry-run ledger'
[ ! -e "$personal_native/agentic-actions-auditor/.skillsync-owner.json" ] || fail 'dry-run must not stamp adoption'

apply_expected_out="$tmp/migrate-apply.expected.out"
apply_expected_err="$tmp/migrate-apply.expected.err"
write_migration_expected personal "$personal_home" "$personal_overlay" agentic-actions-auditor \
  adopted "$apply_expected_out" "$apply_expected_err"
set +e
run_skillsync personal "$personal_home" "$personal_config" "$personal_state" \
  "$personal_overlay" "$work_sources" migrate --apply > "$tmp/migrate-apply.out" 2> "$tmp/migrate-apply.err"
migrate_apply_status=$?
set -e
[ "$migrate_apply_status" -eq 1 ] || fail "personal migration apply should exit 1 for the hand edit, got $migrate_apply_status"
assert_exact_file "$apply_expected_out" "$tmp/migrate-apply.out" 'personal migration apply adoption/removal list'
assert_exact_file "$apply_expected_err" "$tmp/migrate-apply.err" 'personal migration apply conflict list'
[ ! -d "$personal_native/migrate-slim-overlay" ] || fail 'stamped retired migration helper should be pruned'
[ ! -d "$personal_native/purge-migrate-skills" ] || fail 'stamped retired purge helper should be pruned'
grep -Fq 'hand-edited target fixture' "$personal_native/agentic-actions-auditor/SKILL.md" ||
  fail 'hand-edited catalog target must remain untouched'

rm -rf "$personal_native/agentic-actions-auditor"
copy_skill "$render_native" "$personal_native" agentic-actions-auditor
if ! run_skillsync personal "$personal_home" "$personal_config" "$personal_state" \
  "$personal_overlay" "$work_sources" migrate --apply > "$tmp/migrate-resolve.out" 2> "$tmp/migrate-resolve.err"; then
  fail 'migration should adopt the repaired exact target'
fi
printf 'skillsync: adopted native/agentic-actions-auditor\n' > "$tmp/migrate-resolve.expected.out"
assert_exact_file "$tmp/migrate-resolve.expected.out" "$tmp/migrate-resolve.out" 'repaired migration adoption list'
assert_empty_file "$tmp/migrate-resolve.err" 'repaired migration stderr'

if ! run_skillsync personal "$personal_home" "$personal_config" "$personal_state" \
  "$personal_overlay" "$work_sources" sync > "$tmp/personal-create.out" 2> "$tmp/personal-create.err"; then
  fail 'sync should create the unrepresented personal target projections'
fi
assert_empty_file "$tmp/personal-create.err" 'personal create stderr'
personal_create_count=$(grep -c '^skillsync: applied create ' "$tmp/personal-create.out")
[ "$personal_create_count" -eq 35 ] || fail "expected 35 personal create states, got $personal_create_count"
if ! run_skillsync personal "$personal_home" "$personal_config" "$personal_state" \
  "$personal_overlay" "$work_sources" migrate --apply > "$tmp/migrate-idempotent.out" 2> "$tmp/migrate-idempotent.err"; then
  fail 'second personal migration should be idempotent'
fi
assert_empty_file "$tmp/migrate-idempotent.out" 'second migration output'
assert_empty_file "$tmp/migrate-idempotent.err" 'second migration stderr'
if ! run_skillsync personal "$personal_home" "$personal_config" "$personal_state" \
  "$personal_overlay" "$work_sources" sync > "$tmp/personal-clean.out" 2> "$tmp/personal-clean.err"; then
  fail 'second personal sync should be clean'
fi
assert_empty_file "$tmp/personal-clean.out" 'second personal sync output'
assert_empty_file "$tmp/personal-clean.err" 'second personal sync stderr'

assert_projection_contract personal "$personal_home" "$personal_state" "$personal_overlay" \
  "$work_overlay" 40 48 34 11
assert_audit_contract personal "$personal_home" "$personal_config" "$personal_state" "$personal_overlay" 53 1
[ ! -e "$personal_home/.agents/skills" ] || fail 'personal topology must not retain .agents manual copies'
[ ! -e "$personal_home/.copilot/skills" ] || fail 'personal topology must not retain Copilot manual copies'
[ ! -e "$personal_home/.config/opencode/skills" ] || fail 'personal topology must not retain OpenCode manual copies'
assert_exact_file "$plugin_before" "$personal_home/.claude/plugins/fake-plugin/skills/fake-plugin/SKILL.md" 'plugin fixture'
assert_exact_file "$system_imagegen_before" "$personal_codex/.system/imagegen/SKILL.md" 'Codex imagegen system fixture'
assert_exact_file "$system_docs_before" "$personal_codex/.system/openai-docs/SKILL.md" 'Codex openai-docs system fixture'

after_names="$tmp/personal-after-names"
collect_names "$personal_native" "$personal_codex" "$personal_pi" "$personal_hermes" |
  grep -Fxv fixture-unmanaged > "$after_names"
after_distinct=$(wc -l < "$after_names" | tr -d ' ')
[ "$after_distinct" -eq 53 ] || fail "personal distinct-name count should be 53, got $after_distinct"
[ $((legacy_distinct - after_distinct)) -eq 4 ] ||
  fail "unique-name decrease should be exactly four, got $((legacy_distinct - after_distinct))"
after_physical=$((40 + 48 + 34 + 11))
[ "$after_physical" -eq 133 ] || fail 'personal physical projection count should be 133'
after_metadata=$(metadata_characters_from_roots "$personal_native" "$personal_codex" "$personal_pi" "$personal_hermes")
removed_metadata=$(metadata_characters_from_roots "$fixtures/retired" "$fixtures/system")
before_metadata=$legacy_metadata
[ "$before_metadata" -eq $((after_metadata + removed_metadata)) ] ||
  fail "legacy metadata does not equal retained plus four retired descriptions: before=$before_metadata after=$after_metadata removed=$removed_metadata"

# Change canonical source and target independently, exercising every sync state.
source_base_root="$tmp/source-drift/base"
mkdir -p "$source_base_root"
cp "$repo_root/.skillcatalog.toml" "$source_base_root/.skillcatalog.toml"
cp -R "$repo_root/.skills-src" "$source_base_root/.skills-src"
printf '\nsource-only drift fixture\n' >> "$source_base_root/.skills-src/skills/agentic-actions-auditor/SKILL.md"
if ! run_skillsync personal "$personal_home" "$personal_config" "$personal_state" \
  "$personal_overlay" "$work_sources" sync > "$tmp/source-update.out" 2> "$tmp/source-update.err"; then
  fail 'source-only drift should update matching generated targets'
fi
cat > "$tmp/source-update.expected.out" <<'EOF'
skillsync: applied update native/agentic-actions-auditor
skillsync: applied update codex/agentic-actions-auditor
skillsync: applied update pi/agentic-actions-auditor
EOF
assert_exact_file "$tmp/source-update.expected.out" "$tmp/source-update.out" 'source-only update list'
assert_empty_file "$tmp/source-update.err" 'source-only update stderr'
if ! run_skillsync personal "$personal_home" "$personal_config" "$personal_state" \
  "$personal_overlay" "$work_sources" sync > "$tmp/post-update-clean.out" 2> "$tmp/post-update-clean.err"; then
  fail 'updated source should become clean after one sync'
fi
assert_empty_file "$tmp/post-update-clean.out" 'post-update clean output'
assert_empty_file "$tmp/post-update-clean.err" 'post-update clean stderr'

printf '\ntarget-only drift fixture\n' >> "$personal_native/agentic-actions-auditor/SKILL.md"
set +e
run_skillsync personal "$personal_home" "$personal_config" "$personal_state" \
  "$personal_overlay" "$work_sources" sync > "$tmp/target-drift.out" 2> "$tmp/target-drift.err"
target_drift_status=$?
set -e
[ "$target_drift_status" -eq 1 ] || fail "target-only drift should exit 1, got $target_drift_status"
assert_empty_file "$tmp/target-drift.out" 'target-only drift stdout'
printf 'skillsync: conflict (conflict-target-drift) native/agentic-actions-auditor — left untouched\n' \
  > "$tmp/target-drift.expected.err"
assert_exact_file "$tmp/target-drift.expected.err" "$tmp/target-drift.err" 'target-only drift list'
grep -Fq 'target-only drift fixture' "$personal_native/agentic-actions-auditor/SKILL.md" ||
  fail 'target-only drift must remain untouched'

rm -rf "$personal_native/agentic-actions-auditor"
if ! run_skillsync personal "$personal_home" "$personal_config" "$personal_state" \
  "$personal_overlay" "$work_sources" sync > "$tmp/recreate.out" 2> "$tmp/recreate.err"; then
  fail 'missing target should be recreated'
fi
printf 'skillsync: applied recreate native/agentic-actions-auditor\n' > "$tmp/recreate.expected.out"
assert_exact_file "$tmp/recreate.expected.out" "$tmp/recreate.out" 'recreate list'
assert_empty_file "$tmp/recreate.err" 'recreate stderr'

printf '\ntwo-sided source drift fixture\n' >> "$source_base_root/.skills-src/skills/agentic-actions-auditor/SKILL.md"
printf '\ntwo-sided target drift fixture\n' >> "$personal_native/agentic-actions-auditor/SKILL.md"
set +e
run_skillsync personal "$personal_home" "$personal_config" "$personal_state" \
  "$personal_overlay" "$work_sources" sync > "$tmp/two-sided.out" 2> "$tmp/two-sided.err"
two_sided_status=$?
set -e
[ "$two_sided_status" -eq 1 ] || fail "two-sided drift should exit 1, got $two_sided_status"
cat > "$tmp/two-sided.expected.out" <<'EOF'
skillsync: applied update codex/agentic-actions-auditor
skillsync: applied update pi/agentic-actions-auditor
EOF
assert_exact_file "$tmp/two-sided.expected.out" "$tmp/two-sided.out" 'two-sided drift update list'
printf 'skillsync: conflict (conflict-two-sided) native/agentic-actions-auditor — left untouched\n' \
  > "$tmp/two-sided.expected.err"
assert_exact_file "$tmp/two-sided.expected.err" "$tmp/two-sided.err" 'two-sided drift list'
grep -Fq 'two-sided target drift fixture' "$personal_native/agentic-actions-auditor/SKILL.md" ||
  fail 'two-sided target drift must remain untouched'

rm -rf "$personal_native/agentic-actions-auditor"
if ! run_skillsync personal "$personal_home" "$personal_config" "$personal_state" \
  "$personal_overlay" "$work_sources" sync > "$tmp/final-recreate.out" 2> "$tmp/final-recreate.err"; then
  fail 'missing target should recover from two-sided drift'
fi
printf 'skillsync: applied recreate native/agentic-actions-auditor\n' > "$tmp/final-recreate.expected.out"
assert_exact_file "$tmp/final-recreate.expected.out" "$tmp/final-recreate.out" 'two-sided recovery list'
assert_empty_file "$tmp/final-recreate.err" 'two-sided recovery stderr'

# Restore the committed base source before proving the work composition.
source_base_root="$repo_root"
work_render_home="$tmp/work-render/home"
work_render_config="$tmp/work-render/config"
work_render_state="$tmp/work-render/state"
mkdir -p "$work_render_home" "$work_render_config" "$work_render_state"
if ! run_skillsync work "$work_render_home" "$work_render_config" "$work_render_state" \
  "$work_overlay" "$work_sources" sync > "$tmp/work-render.out" 2> "$tmp/work-render.err"; then
  fail 'initial work render should succeed'
fi
assert_empty_file "$tmp/work-render.err" 'initial work render stderr'
work_create_count=$(grep -c '^skillsync: applied create ' "$tmp/work-render.out")
[ "$work_create_count" -eq 100 ] || fail "expected 100 work create states, got $work_create_count"
assert_projection_contract work "$work_render_home" "$work_render_state" "$work_overlay" \
  "$personal_overlay" 36 32 32 0
assert_audit_contract work "$work_render_home" "$work_render_config" "$work_render_state" "$work_overlay" 36 0
[ ! -e "$work_render_home/.hermes/skills" ] || fail 'work topology must not materialize Hermes'

# A work profile adopts legacy native/Codex/Pi copies and remains clean afterward.
work_migration_home="$tmp/work-migration/home"
work_migration_config="$tmp/work-migration/config"
work_migration_state="$tmp/work-migration/state"
mkdir -p "$work_migration_home" "$work_migration_config" "$work_migration_state"
for target in native codex pi; do
  case "$target" in
    native) source_root="$work_render_home/.claude/skills"; target_root="$work_migration_home/.claude/skills" ;;
    codex) source_root="$work_render_home/.codex/skills"; target_root="$work_migration_home/.codex/skills" ;;
    pi) source_root="$work_render_home/.pi/agent/skills"; target_root="$work_migration_home/.pi/agent/skills" ;;
  esac
  copy_skill "$source_root" "$target_root" tn-ticket-intake
done
set +e
run_skillsync work "$work_migration_home" "$work_migration_config" "$work_migration_state" \
  "$work_overlay" "$work_sources" migrate > "$tmp/work-migrate-dry.out" 2> "$tmp/work-migrate-dry.err"
work_migrate_dry_status=$?
set -e
[ "$work_migrate_dry_status" -eq 1 ] || fail "work migration dry-run should exit 1, got $work_migrate_dry_status"
cat > "$tmp/work-migrate-dry.expected.out" <<'EOF'
skillsync: would adopt native/tn-ticket-intake
skillsync: would adopt codex/tn-ticket-intake
skillsync: would adopt pi/tn-ticket-intake
EOF
assert_exact_file "$tmp/work-migrate-dry.expected.out" "$tmp/work-migrate-dry.out" 'work migration dry-run list'
assert_empty_file "$tmp/work-migrate-dry.err" 'work migration dry-run stderr'
if ! run_skillsync work "$work_migration_home" "$work_migration_config" "$work_migration_state" \
  "$work_overlay" "$work_sources" migrate --apply > "$tmp/work-migrate-apply.out" 2> "$tmp/work-migrate-apply.err"; then
  fail 'work migration apply should adopt exact copies'
fi
sed 's/would adopt/adopted/' "$tmp/work-migrate-dry.expected.out" > "$tmp/work-migrate-apply.expected.out"
assert_exact_file "$tmp/work-migrate-apply.expected.out" "$tmp/work-migrate-apply.out" 'work migration apply list'
assert_empty_file "$tmp/work-migrate-apply.err" 'work migration apply stderr'
if ! run_skillsync work "$work_migration_home" "$work_migration_config" "$work_migration_state" \
  "$work_overlay" "$work_sources" sync > "$tmp/work-migration-sync.out" 2> "$tmp/work-migration-sync.err"; then
  fail 'work sync should fill remaining projections'
fi
assert_empty_file "$tmp/work-migration-sync.err" 'work migration sync stderr'
work_migration_create_count=$(grep -c '^skillsync: applied create ' "$tmp/work-migration-sync.out")
[ "$work_migration_create_count" -eq 97 ] || fail "expected 97 work migration create states, got $work_migration_create_count"
if ! run_skillsync work "$work_migration_home" "$work_migration_config" "$work_migration_state" \
  "$work_overlay" "$work_sources" migrate --apply > "$tmp/work-migrate-idempotent.out" 2> "$tmp/work-migrate-idempotent.err"; then
  fail 'second work migration should be idempotent'
fi
assert_empty_file "$tmp/work-migrate-idempotent.out" 'second work migration output'
assert_empty_file "$tmp/work-migrate-idempotent.err" 'second work migration stderr'
assert_projection_contract work "$work_migration_home" "$work_migration_state" "$work_overlay" \
  "$personal_overlay" 36 32 32 0

# Render role-owned OMP configuration into isolated paths. Generic Skill toggles
# come from the base partial; personal settings must never enter the work render.
omp_home="$tmp/omp-runtime-home"
omp_personal_config="$tmp/omp-personal-config.yml"
mkdir -p "$omp_home/.omp/agent" "$omp_home/.codex"
CHEZMOI_BASE_SOURCE="$repo_root" chezmoi --source "$work_overlay" --destination "$omp_home" execute-template \
  --file "$work_overlay/dot_omp/agent/config.yml.tmpl" > "$omp_home/.omp/agent/config.yml"
CHEZMOI_BASE_SOURCE="$repo_root" chezmoi --source "$personal_overlay" --destination "$omp_home" execute-template \
  --file "$personal_overlay/dot_omp/agent/config.yml.tmpl" > "$omp_personal_config"
HOME="$omp_home" XDG_CONFIG_HOME="$omp_home/.config" XDG_STATE_HOME="$omp_home/.state" \
  omp --version > "$tmp/omp-version.out"
HOME="$omp_home" XDG_CONFIG_HOME="$omp_home/.config" XDG_STATE_HOME="$omp_home/.state" \
  omp config list --json > "$tmp/omp-config.json"
run_python "$tmp/omp-config.json" "$omp_home/.omp/agent/config.yml" "$omp_personal_config" <<'PY'
import json
import re
import sys

config_path, work_config_path, personal_config_path = sys.argv[1:]
expected_skills = """\
skills:
  enableClaudeUser: true
  enableAgentsUser: false
  enableCodexUser: false
  enablePiUser: false
"""
work_config = open(work_config_path).read()
personal_config = open(personal_config_path).read()
if work_config != expected_skills:
    raise SystemExit(f"work OMP config must contain only exact generic toggles: {work_config!r}")
if not personal_config.startswith(expected_skills):
    raise SystemExit("personal OMP config must begin with exact generic toggles")
for setting in (
    "providers",
    "symbolPreset",
    "theme",
    "setupVersion",
    "modelRoles",
    "defaultThinkingLevel",
    "cycleOrder",
    "retry",
    "task",
):
    if not re.search(rf"^{setting}:", personal_config, re.MULTILINE):
        raise SystemExit(f"personal OMP config lost {setting}")
    if re.search(rf"^{setting}:", work_config, re.MULTILINE):
        raise SystemExit(f"work OMP config leaked personal {setting}")

config = json.loads(open(config_path).read())
expected = {
    "skills.enableClaudeUser": True,
    "skills.enableAgentsUser": False,
    "skills.enableCodexUser": False,
    "skills.enablePiUser": False,
}
actual = {key: config[key].get("value") for key in expected}
if actual != expected:
    raise SystemExit(f"unexpected OMP Skill provider settings: {actual!r}")
if config["skills.includeSkills"].get("value") != []:
    raise SystemExit("OMP includeSkills must remain unset")
PY
CHEZMOI_AI_PROFILE=personal chezmoi --source "$personal_overlay" --destination "$omp_home" execute-template \
  --file "$personal_overlay/.chezmoitemplates/codex/plugins.toml" > "$omp_home/.codex/config.toml"
if grep -Fq 'codex-forge@local-managed' "$omp_home/.codex/config.toml" ||
   grep -Fq '[marketplaces.local-managed]' "$omp_home/.codex/config.toml"; then
  fail 'isolated Codex config retained unresolved Forge marketplace'
fi
HOME="$omp_home" XDG_CONFIG_HOME="$omp_home/.config" XDG_STATE_HOME="$omp_home/.state" \
  codex plugin list > "$tmp/codex-plugin-list.out" 2> "$tmp/codex-plugin-list.err" ||
  fail 'isolated Codex plugin listing should succeed'

printf 'test-skill-composition: metrics legacy_projections=%s final_projections=%s legacy_names=%s final_names=%s metadata_before=%s metadata_after=%s legacy_collisions=%s final_collisions=0\n' \
  "$legacy_physical" "$after_physical" "$legacy_distinct" "$after_distinct" "$before_metadata" "$after_metadata" "$legacy_collisions"
printf 'test-skill-composition: all assertions passed\n'
