import json
from pathlib import Path

import pytest

from .conftest import make_base_repo, make_personal_repo, write_catalog_toml


def _run(ss, cmd, base, personal, tmp_path, extra=()):
    return ss.main([
        cmd, "--profile", "personal", "--base-root", str(base), "--overlay-root", str(personal),
        "--home", str(tmp_path / "home"), "--state-root", str(tmp_path / "state"), *extra,
    ])


def _setup(tmp_path, disabled_targets=("pi",)):
    # "pionly" has only the disabled target; "alpha" mixes enabled and disabled.
    base = make_base_repo(tmp_path, skill_names=["alpha", "pionly"], targets=["native", "pi"])
    write_catalog_toml(base, owner="base-managed", roles=["personal", "work"], source_root=".skills-src/skills",
                       records=[{"name": "alpha", "targets": ["native", "pi"]}, {"name": "pionly", "targets": ["pi"]}])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"], targets=["native", "pi"],
                                  disabled_targets=list(disabled_targets) if disabled_targets is not None else None)
    return base, personal


def test_sync_skips_disabled_target_for_base_and_overlay_skills(ss, tmp_path):
    base, personal = _setup(tmp_path)
    assert _run(ss, "sync", base, personal, tmp_path) == 0
    home = tmp_path / "home"
    assert (home / ".claude" / "skills" / "alpha" / "SKILL.md").exists()
    assert (home / ".claude" / "skills" / "pskill" / "SKILL.md").exists()
    assert not (home / ".pi").exists()
    ledger = json.loads((tmp_path / "state" / "ledger.json").read_text())
    assert sorted(ledger["targets"]) == ["native:alpha", "native:pskill"]


def test_diff_ignores_disabled_target(ss, tmp_path):
    base, personal = _setup(tmp_path)
    assert _run(ss, "sync", base, personal, tmp_path) == 0
    assert _run(ss, "diff", base, personal, tmp_path) == 0


def test_check_is_clean_with_disabled_target_and_lock_is_profile_independent(ss, tmp_path):
    base, personal = _setup(tmp_path)
    assert _run(ss, "lock", base, personal, tmp_path, extra=("--all",)) == 0
    lock = json.loads((base / ".skillcatalog.lock.json").read_text())
    assert lock["skills"]["pionly"]["targets"] == ["pi"]
    assert lock["skills"]["alpha"]["targets"] == ["native", "pi"]
    assert _run(ss, "check", base, personal, tmp_path) == 0


def test_audit_unmanaged_scan_ignores_disabled_target_root(ss, tmp_path, capsys):
    base, personal = _setup(tmp_path)
    stray = tmp_path / "home" / ".pi" / "agent" / "skills" / "stray"
    stray.mkdir(parents=True)
    assert _run(ss, "audit", base, personal, tmp_path, extra=("--format", "json")) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["unmanaged"] == []


def test_migrate_never_prunes_ledger_entries_for_disabled_target(ss, tmp_path):
    base, personal = _setup(tmp_path, disabled_targets=None)
    assert _run(ss, "sync", base, personal, tmp_path) == 0
    pi_alpha = tmp_path / "home" / ".pi" / "agent" / "skills" / "alpha"
    assert pi_alpha.exists()
    _, personal = _setup(tmp_path / "again")
    assert _run(ss, "migrate", base, personal, tmp_path, extra=("--apply",)) == 0
    assert pi_alpha.exists()
    ledger = json.loads((tmp_path / "state" / "ledger.json").read_text())
    assert "pi:alpha" in ledger["targets"]


def test_without_key_behavior_is_unchanged(ss, tmp_path):
    base, personal = _setup(tmp_path, disabled_targets=None)
    assert _run(ss, "sync", base, personal, tmp_path) == 0
    pi_root = tmp_path / "home" / ".pi" / "agent" / "skills"
    assert sorted(p.name for p in pi_root.iterdir()) == ["alpha", "pionly", "pskill"]
    assert ss.load_catalog(personal / ".skillcatalog.toml").disabled_targets == frozenset()


@pytest.mark.parametrize("value", [["bogus"], "pi", [1], ["pi", "nope"]])
def test_invalid_disabled_targets_are_rejected(ss, tmp_path, value):
    base, personal = _setup(tmp_path, disabled_targets=None)
    catalog = personal / ".skillcatalog.toml"
    catalog.write_text(catalog.read_text().replace(
        'source_root = ', f"disabled_targets = {json.dumps(value)}\nsource_root = ", 1))
    with pytest.raises(ss.SkillError, match="disabled_targets"):
        ss.load_catalog(catalog)
    assert _run(ss, "check", base, personal, tmp_path) == 2
    assert _run(ss, "sync", base, personal, tmp_path) == 2
    assert not (tmp_path / "home").exists()


def test_base_catalog_may_not_declare_disabled_targets(ss, tmp_path):
    base, personal = _setup(tmp_path, disabled_targets=None)
    catalog = base / ".skillcatalog.toml"
    catalog.write_text(catalog.read_text().replace(
        'source_root = ', 'disabled_targets = ["pi"]\nsource_root = ', 1))
    assert _run(ss, "check", base, personal, tmp_path) == 2


def test_runtime_inventory_skips_adapter_for_disabled_target(ss):
    home = Path(__file__).resolve().parents[1] / "fixtures" / "runtime-audit" / "missing-runtime-package-specifiers" / "home"
    _, issues = ss.collect_runtime_inventory(home)
    assert any(i["adapter"] == "pi" for i in issues)
    _, issues = ss.collect_runtime_inventory(home, frozenset({"pi"}))
    assert [i["adapter"] for i in issues] == ["opencode"]


def test_audit_omits_skill_whose_targets_are_all_disabled(ss, tmp_path, capsys):
    base, personal = _setup(tmp_path)
    stray = tmp_path / "home" / ".claude" / "skills" / "pionly"
    stray.mkdir(parents=True)
    assert _run(ss, "audit", base, personal, tmp_path, extra=("--format", "json")) == 0
    report = json.loads(capsys.readouterr().out)
    assert sorted(e["name"] for e in report["manual"]) == ["alpha", "pskill"]
    assert report["unmanaged"] == [{"name": "pionly", "origin": "unmanaged", "target": "native"}]
