#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# Keep the composition contract independent of private checkouts and retired
# worktrees. OMP configuration has its own test-omp-composition.sh suite.
uv run --system-certs --no-project --python '>=3.11' --with 'pyyaml>=6' python - "$repo_root" "$tmp" <<'PY'
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

repo, scratch = map(Path, sys.argv[1:])
cli = repo / "private_dot_local/bin/executable_skillsync"
fixtures = repo / "tests/fixtures/skills"
spec = importlib.util.spec_from_loader("skillsync_composition", loader=None)
ss = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ss
exec(compile(cli.read_text(), str(cli), "exec"), ss.__dict__)

descriptions = {
    "shared": "Shared fixture skill.",
    "pi-only": "Pi fixture skill.",
    "personal-only": "Personal fixture skill.",
    "work-only": "Work fixture skill.",
}


def make_catalog(name, owner, roles, records, disabled=()):
    root = scratch / "sources" / name
    source = root / ".skills-src/skills"
    lines = [
        "schema = 1", f"owner = {json.dumps(owner)}",
        f"roles = {json.dumps(roles)}", 'source_root = ".skills-src/skills"',
        f"disabled_targets = {json.dumps(list(disabled))}",
    ]
    for skill, targets in records:
        dest = source / skill
        dest.mkdir(parents=True)
        (dest / "SKILL.md").write_text(
            f"---\nname: {skill}\ndescription: {descriptions[skill]}\n---\nBody for {skill}.\n"
        )
        lines += [
            "", "[[skills]]", f"name = {json.dumps(skill)}",
            f"targets = {json.dumps(targets)}", 'activation = "automatic"',
            'upstream_ref = "fixture"', 'transform = "standard"',
        ]
    (root / ".skillcatalog.toml").write_text("\n".join(lines) + "\n")
    return root


base = make_catalog("base", "base-managed", ["personal", "work"], [
    ("shared", ["codex", "pi"]), ("pi-only", ["pi"]),
])
personal = make_catalog("personal", "personal-managed", ["personal"], [
    ("personal-only", ["codex", "hermes"]),
], disabled=("pi", "hermes"))
work = make_catalog("work", "work-managed", ["work"], [
    ("work-only", ["codex", "pi"]),
])
roots = {"codex": ".codex/skills", "pi": ".pi/agent/skills", "hermes": ".hermes/skills"}
personal_expected = {
    "codex": {"personal-only": "personal-managed", "shared": "base-managed"},
    "pi": {}, "hermes": {},
}
work_expected = {
    "codex": {"shared": "base-managed", "work-only": "work-managed"},
    "pi": {"pi-only": "base-managed", "shared": "base-managed", "work-only": "work-managed"},
    "hermes": {},
}


def run(profile, case, command, expected=0, out=None, err="", *extra):
    home, state = case / "home", case / "state"
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(case / "config"),
               XDG_STATE_HOME=str(case / "xdg"))
    result = subprocess.run([
        sys.executable, str(cli), command, "--profile", profile,
        "--base-root", str(base), "--overlay-root", str(personal if profile == "personal" else work),
        "--work-root", str(work), "--home", str(home), "--state-root", str(state),
        *extra,
    ], env=env, text=True, capture_output=True)
    assert result.returncode == expected, (command, result.returncode, result.stdout, result.stderr)
    if out is not None:
        assert result.stdout == out, (command, result.stdout, out)
    assert result.stderr == err, (command, result.stderr, err)
    return result.stdout


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def copy_skill(source, dest, stamped=False):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, dest)
    if not stamped:
        (dest / ".skillsync-owner.json").unlink(missing_ok=True)


def projection_contract(case, expected, unmanaged=()):
    home = case / "home"
    ledger = json.loads((case / "state/ledger.json").read_text())["targets"]
    expected_keys = set()
    for target, names in expected.items():
        root = home / roots[target]
        actual = {p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")} if root.exists() else set()
        tolerated = set(unmanaged) if target == "codex" else set()
        assert actual == set(names) | tolerated, (target, actual, names)
        for name, owner in names.items():
            key = f"{target}:{name}"
            expected_keys.add(key)
            entry = ledger[key]
            stamp = json.loads((root / name / ".skillsync-owner.json").read_text())
            assert entry["owner"] == stamp["owner"] == owner
            assert entry["source"] == stamp["source"]
            assert str(scratch) not in entry["source"]
            assert entry["generated_hash"] == entry["target_hash"] == stamp["generated_hash"] == ss.tree_hash(root / name)
    assert set(ledger) == expected_keys, ledger
    return sum(map(len, expected.values()))


def audit_contract(profile, case, expected, unmanaged=()):
    report = json.loads(run(profile, case, "audit", 0, None, "", "--format", "json"))
    owners = {name: owner for names in expected.values() for name, owner in names.items()}
    assert report["manual"] == [{"name": name, "owner": owners[name]} for name in sorted(owners)]
    assert report["manual_meta"] == {
        name: {"chars": len(descriptions[name]), "estimated_tokens": round(len(descriptions[name]) / 4)}
        for name in owners
    }
    assert report["unmanaged"] == [
        {"name": name, "origin": "unmanaged", "target": "codex"} for name in unmanaged
    ], report["unmanaged"]
    assert report["collisions"] == []
    assert report["runtime_issues"] == []
    return len(owners), sum(len(descriptions[name]) for name in owners)


render = scratch / "personal-render"
run("personal", render, "sync", out=(
    "skillsync: applied create codex/personal-only\n"
    "skillsync: applied create codex/shared\n"
))
assert projection_contract(render, personal_expected) == 2
assert audit_contract("personal", render, personal_expected) == (2, 44)
assert not (render / "home/.claude").exists()

# Reconstruct old stamped copies only to test retirement. An active Codex copy
# is also hand edited so adoption and pruning must make independent decisions.
case = scratch / "personal-migration"
home, state = case / "home", case / "state"
codex = home / roots["codex"]
native = home / ".claude/skills"
copy_skill(render / "home/.codex/skills/shared", codex / "shared")
(codex / "shared/SKILL.md").write_text((codex / "shared/SKILL.md").read_text() + "hand edited\n")
copy_skill(fixtures / "unmanaged/fixture-unmanaged", codex / "fixture-unmanaged")
copy_skill(fixtures / "unmanaged/fixture-unmanaged", native / "fixture-unmanaged")
copy_skill(fixtures / "plugins/fake-plugin", home / ".codex/plugins/fixture/skills/fake-plugin")
for name in ("imagegen", "openai-docs"):
    copy_skill(fixtures / "system" / name, codex / ".system" / name)
copy_skill(render / "home/.codex/skills/shared", native / "shared", stamped=True)
copy_skill(fixtures / "retired/migrate-slim-overlay", native / "migrate-slim-overlay")
native_entries = {}
for name in ("migrate-slim-overlay", "shared"):
    dest = native / name
    source = f"base-managed:.skills-src/skills/{name}"
    digest = ss.tree_hash(dest)
    ss.write_owner_stamp(dest, owner="base-managed", source=source, generated_hash=digest, transform="standard")
    native_entries[f"native:{name}"] = {
        "owner": "base-managed", "source": source, "generated_hash": digest,
        "target_hash": digest, "transform": "standard",
    }
state.mkdir(parents=True)
ledger_path = state / "ledger.json"
ledger_path.write_text(json.dumps({"schema": 1, "targets": native_entries}, sort_keys=True) + "\n")
protected = {
    path: snapshot(path) for path in (
        native / "fixture-unmanaged", codex / "fixture-unmanaged",
        home / ".codex/plugins", codex / ".system",
    )
}
before_home, before_ledger = snapshot(home), ledger_path.read_bytes()
prunes = (
    "skillsync: would prune native/migrate-slim-overlay (retired, stamped)\n"
    "skillsync: would prune native/shared (retired, stamped)\n"
)
conflict = "skillsync: refuse adopt codex/shared — on-disk content does not match catalog source\n"
run("personal", case, "migrate", 1, prunes, conflict)
assert snapshot(home) == before_home
assert ledger_path.read_bytes() == before_ledger
run("personal", case, "migrate", 1, prunes.replace("would prune", "pruned"), conflict, "--apply")
assert not (native / "shared").exists()
assert not (native / "migrate-slim-overlay").exists()
assert "hand edited" in (codex / "shared/SKILL.md").read_text()
assert json.loads(ledger_path.read_text())["targets"] == {}
for path, expected in protected.items():
    assert snapshot(path) == expected, path
shutil.rmtree(codex / "shared")
copy_skill(render / "home/.codex/skills/shared", codex / "shared")
run("personal", case, "migrate", 0, "skillsync: adopted codex/shared\n", "", "--apply")
run("personal", case, "sync", out="skillsync: applied create codex/personal-only\n")
run("personal", case, "migrate", 0, "", "", "--apply")
run("personal", case, "sync", out="")
assert projection_contract(case, personal_expected, ("fixture-unmanaged",)) == 2
assert audit_contract("personal", case, personal_expected, ("fixture-unmanaged",)) == (2, 44)
for path, expected in protected.items():
    assert snapshot(path) == expected, path

# Exercise each drift state against an active personal target.
source = base / ".skills-src/skills/shared/SKILL.md"
target = codex / "shared/SKILL.md"
source.write_text(source.read_text() + "source drift\n")
run("personal", case, "sync", out="skillsync: applied update codex/shared\n")
run("personal", case, "sync", out="")
target.write_text(target.read_text() + "target drift\n")
run("personal", case, "sync", 1, "",
    "skillsync: conflict (conflict-target-drift) codex/shared — left untouched\n")
assert "target drift" in target.read_text()
shutil.rmtree(target.parent)
run("personal", case, "sync", out="skillsync: applied recreate codex/shared\n")
source.write_text(source.read_text() + "two-sided source drift\n")
target.write_text(target.read_text() + "two-sided target drift\n")
run("personal", case, "sync", 1, "",
    "skillsync: conflict (conflict-two-sided) codex/shared — left untouched\n")
assert "two-sided target drift" in target.read_text()
shutil.rmtree(target.parent)
run("personal", case, "sync", out="skillsync: applied recreate codex/shared\n")
assert projection_contract(case, personal_expected, ("fixture-unmanaged",)) == 2

work_render = scratch / "work-render"
run("work", work_render, "sync", out=(
    "skillsync: applied create pi/pi-only\n"
    "skillsync: applied create codex/shared\n"
    "skillsync: applied create pi/shared\n"
    "skillsync: applied create codex/work-only\n"
    "skillsync: applied create pi/work-only\n"
))
assert projection_contract(work_render, work_expected) == 5
assert audit_contract("work", work_render, work_expected) == (3, 57)
assert not (work_render / "home/.hermes/skills").exists()
assert not (work_render / "home/.claude").exists()

work_case = scratch / "work-migration"
for target_name in ("codex", "pi"):
    copy_skill(work_render / "home" / roots[target_name] / "work-only",
               work_case / "home" / roots[target_name] / "work-only")
adopts = "skillsync: would adopt codex/work-only\nskillsync: would adopt pi/work-only\n"
run("work", work_case, "migrate", 1, adopts)
assert not (work_case / "state/ledger.json").exists()
run("work", work_case, "migrate", 0, adopts.replace("would adopt", "adopted"), "", "--apply")
run("work", work_case, "sync", out=(
    "skillsync: applied create pi/pi-only\n"
    "skillsync: applied create codex/shared\n"
    "skillsync: applied create pi/shared\n"
))
run("work", work_case, "migrate", 0, "", "", "--apply")
run("work", work_case, "sync", out="")
assert projection_contract(work_case, work_expected) == 5
assert audit_contract("work", work_case, work_expected) == (3, 57)
print("test-skill-composition: personal=2 projections/2 names/44 metadata chars; work=5 projections/3 names/57 metadata chars")
print("test-skill-composition: all assertions passed")
PY
