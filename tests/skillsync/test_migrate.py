import json

from .conftest import make_base_repo, make_personal_repo


def _setup(tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"], targets=["native"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"], targets=["native"])
    home = tmp_path / "home"
    state_root = tmp_path / "state"
    return base, personal, home, state_root


def _run(ss, cmd, base, personal, home, state_root, extra=()):
    argv = [cmd, "--profile", "personal", "--base-root", str(base), "--overlay-root", str(personal),
            "--home", str(home), "--state-root", str(state_root), *extra]
    return ss.main(argv)


def _exact_projection(ss, base, name, home):
    """What sync would generate for skill `name` at the native target, staged
    for direct comparison/adoption in these tests."""
    src = base / ".skills-src" / "skills" / name
    import shutil
    dest = home / ".claude" / "skills" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    return dest


def test_migrate_dry_run_reports_without_writing(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    _exact_projection(ss, base, "alpha", home)
    rc = _run(ss, "migrate", base, personal, home, state_root)
    assert rc == 1  # pending adoption reported
    assert not (home / ".claude" / "skills" / "alpha" / ".skillsync-owner.json").exists()
    assert not (state_root / "ledger.json").exists()


def test_migrate_adopts_exact_match_legacy_directory(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    _exact_projection(ss, base, "alpha", home)
    rc = _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"])
    assert rc == 0
    assert (home / ".claude" / "skills" / "alpha" / ".skillsync-owner.json").exists()
    ledger = json.loads((state_root / "ledger.json").read_text())
    assert "native:alpha" in ledger["targets"]
    # bytes of the pre-existing SKILL.md were not rewritten (adoption != resync)
    original_bytes = (base / ".skills-src" / "skills" / "alpha" / "SKILL.md").read_bytes()
    assert (home / ".claude" / "skills" / "alpha" / "SKILL.md").read_bytes() == original_bytes


def test_migrate_refuses_adoption_on_content_mismatch(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    dest = home / ".claude" / "skills" / "alpha"
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text("---\nname: alpha\ndescription: totally different\n---\nnot the same body\n")
    rc = _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"])
    assert rc == 1
    assert not (dest / ".skillsync-owner.json").exists()
    ledger_path = state_root / "ledger.json"
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text())
        assert "native:alpha" not in ledger.get("targets", {})
    # mismatched content is left exactly as-is, never overwritten
    assert "totally different" in (dest / "SKILL.md").read_text()


def test_migrate_prunes_only_stamped_retired_skills(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    assert _run(ss, "sync", base, personal, home, state_root) == 0

    # retire "alpha" from the base catalog (rewrite catalog TOML without it)
    from .conftest import write_catalog_toml
    write_catalog_toml(base, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills", records=[])

    rc = _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"])
    assert rc == 0
    assert not (home / ".claude" / "skills" / "alpha").exists()  # pruned
    assert (home / ".claude" / "skills" / "pskill").exists()      # still catalogued, untouched
    ledger = json.loads((state_root / "ledger.json").read_text())
    assert "native:alpha" not in ledger["targets"]


def test_migrate_blocks_prune_of_hand_edited_retired_skill(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    assert _run(ss, "sync", base, personal, home, state_root) == 0
    dest = home / ".claude" / "skills" / "alpha"
    (dest / "SKILL.md").write_text((dest / "SKILL.md").read_text() + "hand edited after retirement\n")

    from .conftest import write_catalog_toml
    write_catalog_toml(base, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills", records=[])

    rc = _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"])
    assert rc == 1
    assert dest.exists()  # NOT deleted — content diverged from what we generated
    ledger = json.loads((state_root / "ledger.json").read_text())
    assert "native:alpha" in ledger["targets"]  # ledger entry retained, unresolved


def test_migrate_never_touches_unmanaged_sibling(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    stray = home / ".claude" / "skills" / "totally-unrelated"
    stray.mkdir(parents=True)
    (stray / "SKILL.md").write_text("---\nname: totally-unrelated\ndescription: not in any catalog\n---\nx\n")
    rc = _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"])
    assert (stray / "SKILL.md").exists()
    assert (stray / "SKILL.md").read_text() == "---\nname: totally-unrelated\ndescription: not in any catalog\n---\nx\n"
