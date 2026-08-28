import json

import pytest

from .conftest import build_repo, make_base_repo, make_personal_repo, make_work_repo


def _lock_argv(base, overlay, *scope):
    return [
        "lock", "--profile", "personal", "--base-root", str(base),
        "--overlay-root", str(overlay), *scope,
    ]


def _write_current_lock(ss, repo):
    catalog = ss.load_catalog(repo / ".skillcatalog.toml")
    ss.atomic_write_json(repo / ".skillcatalog.lock.json", ss.build_lock(catalog))


def test_build_lock_records_tree_hash_and_provenance(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    catalog = ss.load_catalog(base / ".skillcatalog.toml")
    lock = ss.build_lock(catalog)
    entry = lock["skills"]["alpha"]
    assert entry["owner"] == "base-managed"
    assert entry["tree_hash"] == ss.tree_hash(base / ".skills-src" / "skills" / "alpha")
    assert entry["description"] == "does a thing"
    assert entry["transform"] == "standard"
    assert entry["targets"] == ["native", "codex", "pi"]


def test_build_lock_records_commit_hash_for_local_repo(ss, tmp_path, monkeypatch):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    monkeypatch.setattr(ss, "git_commit_hash", lambda root: "deadbeef")
    catalog = ss.load_catalog(base / ".skillcatalog.toml")
    lock = ss.build_lock(catalog)
    assert lock["skills"]["alpha"]["source_commit"] == "deadbeef"


def test_build_lock_omits_commit_hash_for_external_work_source(ss, tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "git_commit_hash", lambda root: "should-not-be-used")
    work_src = tmp_path / "work-src"
    work = make_work_repo(tmp_path, skill_names=["wskill"], external_source_dir=work_src)
    catalog = ss.load_catalog(work / ".skillcatalog.toml", work_root=work_src)
    lock = ss.build_lock(catalog)
    assert lock["skills"]["wskill"]["source_commit"] is None


def test_check_lock_freshness_detects_stale_source(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    catalog = ss.load_catalog(base / ".skillcatalog.toml")
    lock = ss.build_lock(catalog)
    # mutate source after locking
    skill_md = base / ".skills-src" / "skills" / "alpha" / "SKILL.md"
    skill_md.write_text(skill_md.read_text() + "changed\n")
    stale = ss.check_lock_freshness(catalog, lock)
    assert stale == ["alpha"]


def test_check_lock_freshness_clean_when_matching(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    catalog = ss.load_catalog(base / ".skillcatalog.toml")
    lock = ss.build_lock(catalog)
    assert ss.check_lock_freshness(catalog, lock) == []


def test_check_lock_freshness_all_stale_when_never_locked(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha", "beta"])
    catalog = ss.load_catalog(base / ".skillcatalog.toml")
    assert set(ss.check_lock_freshness(catalog, None)) == {"alpha", "beta"}


def test_lock_parser_rejects_bare_lock(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"])
    with pytest.raises(SystemExit) as exc:
        ss.build_arg_parser().parse_args(_lock_argv(base, personal))
    assert exc.value.code == 2


def test_lock_parser_accepts_targeted_and_explicit_all_modes(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"])
    parser = ss.build_arg_parser()

    targeted = parser.parse_args(_lock_argv(base, personal, "--skill", "pskill"))
    assert targeted.skill == "pskill"
    assert targeted.lock_all is False

    broad = parser.parse_args(_lock_argv(base, personal, "--all"))
    assert broad.skill is None
    assert broad.lock_all is True


def test_targeted_overlay_lock_preserves_base_and_unrelated_entries(ss, tmp_path, monkeypatch):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill", "other"])
    monkeypatch.setattr(ss, "git_commit_hash", lambda root: "old-commit")
    _write_current_lock(ss, base)
    _write_current_lock(ss, personal)

    base_path = base / ".skillcatalog.lock.json"
    personal_path = personal / ".skillcatalog.lock.json"
    base_before = base_path.read_bytes()
    personal_before = json.loads(personal_path.read_text())

    skill_md = personal / ".skills-src" / "skills" / "pskill" / "SKILL.md"
    skill_md.write_text(skill_md.read_text() + "changed\n")
    monkeypatch.setattr(ss, "git_commit_hash", lambda root: "new-commit")

    assert ss.main(_lock_argv(base, personal, "--skill", "pskill")) == 0
    personal_after = json.loads(personal_path.read_text())
    assert base_path.read_bytes() == base_before
    assert personal_after["skills"]["other"] == personal_before["skills"]["other"]
    assert personal_after["skills"]["pskill"]["tree_hash"] != personal_before["skills"]["pskill"]["tree_hash"]
    assert personal_after["skills"]["pskill"]["source_commit"] == "new-commit"


def test_targeted_base_lock_preserves_overlay_file(ss, tmp_path, monkeypatch):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"])
    monkeypatch.setattr(ss, "git_commit_hash", lambda root: "old-commit")
    _write_current_lock(ss, base)
    _write_current_lock(ss, personal)

    personal_path = personal / ".skillcatalog.lock.json"
    personal_before = personal_path.read_bytes()
    skill_md = base / ".skills-src" / "skills" / "alpha" / "SKILL.md"
    skill_md.write_text(skill_md.read_text() + "changed\n")
    monkeypatch.setattr(ss, "git_commit_hash", lambda root: "new-commit")

    assert ss.main(_lock_argv(base, personal, "--skill", "alpha")) == 0
    base_lock = json.loads((base / ".skillcatalog.lock.json").read_text())
    assert personal_path.read_bytes() == personal_before
    assert base_lock["skills"]["alpha"]["source_commit"] == "new-commit"


def test_targeted_lock_rejects_unknown_skill_without_writes(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"])
    _write_current_lock(ss, base)
    _write_current_lock(ss, personal)
    base_path = base / ".skillcatalog.lock.json"
    personal_path = personal / ".skillcatalog.lock.json"
    base_before = base_path.read_bytes()
    personal_before = personal_path.read_bytes()

    assert ss.main(_lock_argv(base, personal, "--skill", "missing")) == 2
    assert base_path.read_bytes() == base_before
    assert personal_path.read_bytes() == personal_before


def test_targeted_lock_requires_existing_owner_lock(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"])
    _write_current_lock(ss, base)
    base_path = base / ".skillcatalog.lock.json"
    base_before = base_path.read_bytes()
    personal_path = personal / ".skillcatalog.lock.json"

    assert ss.main(_lock_argv(base, personal, "--skill", "pskill")) == 2
    assert base_path.read_bytes() == base_before
    assert not personal_path.exists()


def test_targeted_lock_rejects_non_object_owner_lock_without_writes(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"])
    _write_current_lock(ss, base)
    base_path = base / ".skillcatalog.lock.json"
    personal_path = personal / ".skillcatalog.lock.json"
    base_before = base_path.read_bytes()
    personal_path.write_text("[]\n")
    personal_before = personal_path.read_bytes()

    assert ss.main(_lock_argv(base, personal, "--skill", "pskill")) == 2
    assert base_path.read_bytes() == base_before
    assert personal_path.read_bytes() == personal_before


def test_targeted_lock_rejects_invalid_utf8_owner_lock_without_writes(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"])
    _write_current_lock(ss, base)
    base_path = base / ".skillcatalog.lock.json"
    personal_path = personal / ".skillcatalog.lock.json"
    base_before = base_path.read_bytes()
    personal_path.write_bytes(b"\xff\xfe\n")
    personal_before = personal_path.read_bytes()

    assert ss.main(_lock_argv(base, personal, "--skill", "pskill")) == 2
    assert base_path.read_bytes() == base_before
    assert personal_path.read_bytes() == personal_before


def test_targeted_lock_rejects_malformed_unrelated_entry_without_writes(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill", "other"])
    _write_current_lock(ss, base)
    _write_current_lock(ss, personal)
    base_path = base / ".skillcatalog.lock.json"
    personal_path = personal / ".skillcatalog.lock.json"
    base_before = base_path.read_bytes()
    personal_lock = json.loads(personal_path.read_text())
    personal_lock["skills"]["other"] = []
    personal_path.write_text(json.dumps(personal_lock, indent=2, sort_keys=True) + "\n")
    personal_before = personal_path.read_bytes()

    assert ss.main(_lock_argv(base, personal, "--skill", "pskill")) == 2
    assert base_path.read_bytes() == base_before
    assert personal_path.read_bytes() == personal_before


def test_explicit_all_retains_full_refresh_behavior(ss, tmp_path, monkeypatch):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"])
    monkeypatch.setattr(ss, "git_commit_hash", lambda root: "old-commit")
    _write_current_lock(ss, base)
    _write_current_lock(ss, personal)
    monkeypatch.setattr(ss, "git_commit_hash", lambda root: "new-commit")

    assert ss.main(_lock_argv(base, personal, "--all")) == 0
    base_lock = json.loads((base / ".skillcatalog.lock.json").read_text())
    personal_lock = json.loads((personal / ".skillcatalog.lock.json").read_text())
    assert base_lock["skills"]["alpha"]["source_commit"] == "new-commit"
    assert personal_lock["skills"]["pskill"]["source_commit"] == "new-commit"


def test_cmd_lock_writes_both_repo_locks_and_refuses_cross_owner_duplicate(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"])
    ap = ss.build_arg_parser()
    args = ap.parse_args(["lock", "--profile", "personal", "--base-root", str(base),
                           "--overlay-root", str(personal), "--home", str(tmp_path / "home"), "--all"])
    rc = ss.cmd_lock(args)
    assert rc == 0
    base_lock = json.loads((base / ".skillcatalog.lock.json").read_text())
    personal_lock = json.loads((personal / ".skillcatalog.lock.json").read_text())
    assert "alpha" in base_lock["skills"]
    assert "pskill" in personal_lock["skills"]

    # now introduce a cross-owner duplicate name (fresh repo dir) and confirm lock refuses it
    dup_personal = build_repo(tmp_path / "personal-dup", owner="personal-managed", roles=["personal"],
                               skill_names=["alpha"], targets=["native", "codex", "pi", "hermes"])
    rc2 = ss.main(["lock", "--profile", "personal", "--base-root", str(base),
                   "--overlay-root", str(dup_personal), "--home", str(tmp_path / "home"), "--all"])
    assert rc2 == 2
