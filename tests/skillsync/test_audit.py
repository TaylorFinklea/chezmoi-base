import json

from .conftest import make_base_repo, make_personal_repo


def test_classify_inventory_manual_only_is_clean(ss):
    report = ss.classify_inventory({"alpha": "base-managed"}, [])
    assert report["manual"] == [{"name": "alpha", "owner": "base-managed"}]
    assert report["collisions"] == []
    assert ss.audit_exit_code(report) == 0


def test_classify_inventory_manual_vs_enabled_plugin_is_hard_failure(ss):
    observed = [ss.ObservedSkill(name="alpha", origin="plugin", tree_hash_value="sha256:x", provider="acme")]
    report = ss.classify_inventory({"alpha": "base-managed"}, observed)
    collisions = report["collisions"]
    assert len(collisions) == 1
    assert collisions[0]["kind"] == "manual-vs-plugin"
    assert collisions[0]["severity"] == "failure"
    assert ss.audit_exit_code(report) == 2


def test_classify_inventory_manual_vs_disabled_plugin_is_not_a_collision(ss):
    observed = [ss.ObservedSkill(name="alpha", origin="plugin", tree_hash_value="sha256:x",
                                  provider="acme", enabled=False)]
    report = ss.classify_inventory({"alpha": "base-managed"}, observed)
    assert report["collisions"] == []
    assert ss.audit_exit_code(report) == 0


def test_classify_inventory_plugin_plugin_identical_is_info_not_failure(ss):
    observed = [
        ss.ObservedSkill(name="cloudflare", origin="plugin", tree_hash_value="sha256:same", provider="p1"),
        ss.ObservedSkill(name="cloudflare", origin="plugin", tree_hash_value="sha256:same", provider="p2"),
    ]
    report = ss.classify_inventory({}, observed)
    assert len(report["collisions"]) == 1
    assert report["collisions"][0]["kind"] == "plugin-plugin-identical"
    assert report["collisions"][0]["severity"] == "info"
    assert ss.audit_exit_code(report) == 0  # informational only, never a failure


def test_classify_inventory_plugin_plugin_divergent_is_hard_failure(ss):
    observed = [
        ss.ObservedSkill(name="cloudflare", origin="plugin", tree_hash_value="sha256:aaa", provider="p1"),
        ss.ObservedSkill(name="cloudflare", origin="system", tree_hash_value="sha256:bbb", provider="p2"),
    ]
    report = ss.classify_inventory({}, observed)
    assert len(report["collisions"]) == 1
    assert report["collisions"][0]["kind"] == "plugin-plugin-divergent"
    assert report["collisions"][0]["severity"] == "failure"
    assert ss.audit_exit_code(report) == 2


def test_classify_inventory_buckets_system_and_unmanaged(ss):
    observed = [
        ss.ObservedSkill(name="imagegen", origin="system", tree_hash_value="sha256:sys"),
        ss.ObservedSkill(name="strays", origin="unmanaged", tree_hash_value="sha256:u"),
    ]
    report = ss.classify_inventory({}, observed)
    assert [e["name"] for e in report["system"]] == ["imagegen"]
    assert [e["name"] for e in report["unmanaged"]] == ["strays"]
    assert report["collisions"] == []


def test_scan_unmanaged_finds_stray_directory_outside_catalog_and_ledger(ss, tmp_path):
    target_roots = {"native": tmp_path / "claude"}
    stray = target_roots["native"] / "not-in-catalog"
    stray.mkdir(parents=True)
    (stray / "SKILL.md").write_text("x")
    ledger = {"targets": {}}
    found = ss.scan_unmanaged(target_roots, {"alpha"}, ledger)
    assert found == [{"target": "native", "name": "not-in-catalog"}]


def test_scan_unmanaged_ignores_ledger_tracked_directory(ss, tmp_path):
    target_roots = {"native": tmp_path / "claude"}
    dest = target_roots["native"] / "alpha"
    dest.mkdir(parents=True)
    ledger = {"targets": {"native:alpha": {"owner": "base-managed"}}}
    found = ss.scan_unmanaged(target_roots, set(), ledger)
    assert found == []


def test_cmd_audit_json_reports_manual_and_metadata(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"], targets=["native"], description="a" * 40)
    personal = make_personal_repo(tmp_path, skill_names=["pskill"], targets=["native"])
    rc = ss.main([
        "audit", "--profile", "personal", "--base-root", str(base), "--overlay-root", str(personal),
        "--home", str(tmp_path / "home"), "--state-root", str(tmp_path / "state"), "--format", "json",
    ])
    assert rc == 0


def test_cmd_audit_markdown_format_smoke(ss, tmp_path, capsys):
    base = make_base_repo(tmp_path, skill_names=["alpha"], targets=["native"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"], targets=["native"])
    rc = ss.main([
        "audit", "--profile", "personal", "--base-root", str(base), "--overlay-root", str(personal),
        "--home", str(tmp_path / "home"), "--state-root", str(tmp_path / "state"), "--format", "markdown",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# skillsync audit" in out
    assert "alpha" in out
