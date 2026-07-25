import json

from .conftest import build_repo, make_base_repo, make_personal_repo, make_work_repo


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


def test_cmd_lock_writes_both_repo_locks_and_refuses_cross_owner_duplicate(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"])
    ap = ss.build_arg_parser()
    args = ap.parse_args(["lock", "--profile", "personal", "--base-root", str(base),
                           "--overlay-root", str(personal), "--home", str(tmp_path / "home")])
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
                   "--overlay-root", str(dup_personal), "--home", str(tmp_path / "home")])
    assert rc2 == 2
