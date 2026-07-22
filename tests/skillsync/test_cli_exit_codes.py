"""CLI exit code convention (Acceptance): 0 clean, 1 drift/diff, 2 invalid/conflict —
exercised across all six subcommands."""
from .conftest import make_base_repo, make_personal_repo


def _argv(cmd, base, personal, tmp_path, extra=()):
    return [cmd, "--profile", "personal", "--base-root", str(base), "--overlay-root", str(personal),
            "--home", str(tmp_path / "home"), "--state-root", str(tmp_path / "state"), *extra]


def _fresh(tmp_path, suffix=""):
    base = make_base_repo(tmp_path / f"b{suffix}", skill_names=["alpha"], targets=["native"])
    personal = make_personal_repo(tmp_path / f"p{suffix}", skill_names=["pskill"], targets=["native"])
    return base, personal


def test_lock_zero_clean_two_invalid(ss, tmp_path):
    base, personal = _fresh(tmp_path, "1")
    assert ss.main(_argv("lock", base, personal, tmp_path / "1")) == 0
    dup_base, _dup_personal = _fresh(tmp_path, "2")
    from .conftest import build_repo
    dup2 = build_repo(tmp_path / "dup2", owner="personal-managed", roles=["personal"], skill_names=["alpha"],
                       targets=["native"])
    assert ss.main(_argv("lock", dup_base, dup2, tmp_path / "2")) == 2


def test_check_zero_one_two(ss, tmp_path):
    base, personal = _fresh(tmp_path, "1")
    assert ss.main(_argv("lock", base, personal, tmp_path / "1")) == 0
    assert ss.main(_argv("check", base, personal, tmp_path / "1")) == 0  # 0 clean

    skill_md = base / ".skills-src" / "skills" / "alpha" / "SKILL.md"
    skill_md.write_text(skill_md.read_text() + "drift\n")
    assert ss.main(_argv("check", base, personal, tmp_path / "1")) == 1  # 1 drift

    base2, personal2 = _fresh(tmp_path, "2")
    from .conftest import write_catalog_toml
    write_catalog_toml(personal2, owner="personal-managed", roles=["personal"], source_root=".skills-src/skills",
                        records=[{"name": "alpha", "targets": ["native"]}])
    from .conftest import write_skill
    write_skill(personal2 / ".skills-src" / "skills", "alpha")
    assert ss.main(_argv("check", base2, personal2, tmp_path / "2")) == 2  # 2 invalid (collision)


def test_diff_zero_and_one(ss, tmp_path):
    base, personal = _fresh(tmp_path, "1")
    assert ss.main(_argv("diff", base, personal, tmp_path / "1")) == 1  # 1: pending creates
    assert ss.main(_argv("sync", base, personal, tmp_path / "1")) == 0
    assert ss.main(_argv("diff", base, personal, tmp_path / "1")) == 0  # 0: clean


def test_diff_two_on_invalid_catalog(ss, tmp_path):
    base, personal = _fresh(tmp_path, "1")
    (base / ".skillcatalog.toml").write_text("schema = 2\n")  # corrupt schema
    assert ss.main(_argv("diff", base, personal, tmp_path / "1")) == 2


def test_sync_zero_and_one(ss, tmp_path):
    base, personal = _fresh(tmp_path, "1")
    assert ss.main(_argv("sync", base, personal, tmp_path / "1")) == 0  # 0: clean create
    assert ss.main(_argv("sync", base, personal, tmp_path / "1")) == 0  # 0: idempotent clean

    dest_md = tmp_path / "1" / "home" / ".claude" / "skills" / "alpha" / "SKILL.md"
    dest_md.write_text(dest_md.read_text() + "hand edit\n")
    assert ss.main(_argv("sync", base, personal, tmp_path / "1")) == 1  # 1: conflict reported


def test_sync_two_on_invalid_catalog(ss, tmp_path):
    base, personal = _fresh(tmp_path, "1")
    (base / ".skillcatalog.toml").write_text("schema = 2\n")
    assert ss.main(_argv("sync", base, personal, tmp_path / "1")) == 2


def test_migrate_zero_one_and_two(ss, tmp_path):
    base, personal = _fresh(tmp_path, "1")
    assert ss.main(_argv("migrate", base, personal, tmp_path / "1", extra=["--apply"])) == 0  # 0: nothing to do

    dest = tmp_path / "1" / "home" / ".claude" / "skills" / "alpha"
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text("hand-installed, does not match source\n")
    assert ss.main(_argv("migrate", base, personal, tmp_path / "1")) == 1  # 1: dry-run reports a refusal

    base2, personal2 = _fresh(tmp_path, "2")
    (base2 / ".skillcatalog.toml").write_text("schema = 2\n")
    assert ss.main(_argv("migrate", base2, personal2, tmp_path / "2")) == 2  # 2: invalid catalog


def test_audit_zero_and_two(ss, tmp_path):
    base, personal = _fresh(tmp_path, "1")
    assert ss.main(_argv("audit", base, personal, tmp_path / "1")) == 0  # 0: no collisions

    base2, personal2 = _fresh(tmp_path, "2")
    (base2 / ".skillcatalog.toml").write_text("schema = 2\n")
    assert ss.main(_argv("audit", base2, personal2, tmp_path / "2")) == 2  # 2: invalid catalog
