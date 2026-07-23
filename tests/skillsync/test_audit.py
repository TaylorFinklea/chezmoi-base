import json
import shutil


from .conftest import make_base_repo, make_personal_repo
from pathlib import Path


RUNTIME_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "runtime-audit"


def runtime_home(name: str) -> Path:
    return RUNTIME_FIXTURES / name / "home"


def test_runtime_inventory_marks_disabled_plugin_non_effective(ss):
    observed, issues = ss.collect_runtime_inventory(runtime_home("disabled-plugin"))
    plugin = next(item for item in observed if item.name == "disabled-skill")
    assert plugin.enabled is False
    assert plugin.state == "disabled"
    assert issues == []


def test_runtime_inventory_marks_unselected_cache_runtime_cache_only(ss):
    observed, issues = ss.collect_runtime_inventory(runtime_home("stale-cache"))
    active = next(item for item in observed if item.name == "active-skill")
    stale = next(item for item in observed if item.name == "stale-skill")
    assert active.enabled is True
    assert stale.enabled is False
    assert stale.state == "runtime-cache-only"
    assert issues == []


def test_runtime_inventory_reports_missing_enabled_install(ss):
    observed, issues = ss.collect_runtime_inventory(runtime_home("missing-active-install"))
    assert observed == []
    assert issues == [{
        "adapter": "codex",
        "provider": "missing@fixture",
        "state": "missing-active-install",
    }]


def test_runtime_inventory_uses_deterministic_precedence_for_identical_plugins(ss):
    observed, issues = ss.collect_runtime_inventory(runtime_home("identical-plugins"))
    report = ss.classify_inventory({}, observed)
    collision = report["collisions"][0]
    assert collision["kind"] == "plugin-plugin-identical"
    assert collision["winner"] == "alpha@fixture"
    assert issues == []


def test_runtime_inventory_fails_for_divergent_plugins(ss):
    observed, issues = ss.collect_runtime_inventory(runtime_home("divergent-plugins"))
    report = ss.classify_inventory({}, observed)
    assert report["collisions"][0]["kind"] == "plugin-plugin-divergent"
    assert ss.audit_exit_code(report) == 2
    assert issues == []


def test_runtime_inventory_fails_for_manual_plugin_collision(ss):
    observed, issues = ss.collect_runtime_inventory(runtime_home("manual-plugin-collision"))
    report = ss.classify_inventory({"manual-skill": "base-managed"}, observed)
    assert report["collisions"][0]["kind"] == "manual-vs-plugin"
    assert ss.audit_exit_code(report) == 2
    assert issues == []


def test_runtime_inventory_adapters_cover_all_runtime_sources_and_system_skills(ss):
    observed, issues = ss.collect_runtime_inventory(runtime_home("identical-plugins"))
    providers = {item.provider for item in observed}
    assert {"alpha@fixture", "beta@fixture", "opencode@fixture", "pi@fixture",
            "pi-extension@fixture", "omp@fixture", "copilot@fixture",
            "copilot-root@fixture"} <= providers
    systems = {item.name: item.owner for item in observed if item.origin == "system"}
    assert systems == {"imagegen": "harness-system", "openai-docs": "harness-system"}
    assert issues == []

def test_runtime_inventory_resolves_real_pi_and_opencode_specifiers(ss):
    observed, issues = ss.collect_runtime_inventory(runtime_home("runtime-package-specifiers"))
    providers = {item.provider for item in observed}
    assert {
        "git:github.com/obra/superpowers",
        "npm:pi-skillful",
        "../../git/computer-use-sidecar",
        "superpowers@git+https://github.com/obra/superpowers.git",
        "opencode-npm-plugin@1.2.3",
    } <= providers
    stale = next(item for item in observed if item.name == "opencode-stale-skill")
    assert stale.state == "runtime-cache-only"
    assert issues == []


def test_runtime_inventory_reports_missing_real_pi_and_opencode_specifiers(ss, tmp_path):
    observed, issues = ss.collect_runtime_inventory(runtime_home("missing-runtime-package-specifiers"))
    assert observed == []
    assert issues == [
        {"adapter": "opencode", "provider": "superpowers@git+https://github.com/obra/superpowers.git",
         "state": "missing-active-install"},
        {"adapter": "pi", "provider": "npm:pi-web-access", "state": "missing-active-install"},
    ]

    base = make_base_repo(tmp_path, skill_names=["alpha"], targets=["native"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"], targets=["native"])
    rc = ss.main([
        "audit", "--profile", "personal", "--base-root", str(base), "--overlay-root", str(personal),
        "--home", str(runtime_home("missing-runtime-package-specifiers")),
        "--state-root", str(tmp_path / "state"), "--strict-runtime", "--format", "json",
    ])
    assert rc == 2



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


def test_cmd_audit_strict_runtime_rejects_missing_enabled_install(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"], targets=["native"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"], targets=["native"])
    home = tmp_path / "home"
    shutil.copytree(runtime_home("missing-active-install"), home)
    rc = ss.main([
        "audit", "--profile", "personal", "--base-root", str(base), "--overlay-root", str(personal),
        "--home", str(home), "--state-root", str(tmp_path / "state"), "--strict-runtime", "--format", "json",
    ])
    assert rc == 2


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
