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


def test_sync_missing_ledger_creates_target_cleanly(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    rc = _run(ss, "sync", base, personal, home, state_root)
    assert rc == 0
    assert (home / ".claude" / "skills" / "alpha" / "SKILL.md").exists()
    ledger = json.loads((state_root / "ledger.json").read_text())
    assert "native:alpha" in ledger["targets"]
    assert (home / ".claude" / "skills" / "alpha" / ".skillsync-owner.json").exists()


def test_sync_is_idempotent_when_clean(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    assert _run(ss, "sync", base, personal, home, state_root) == 0
    dest = home / ".claude" / "skills" / "alpha"
    mtime_before = (dest / "SKILL.md").stat().st_mtime_ns
    assert _run(ss, "sync", base, personal, home, state_root) == 0
    # clean state: nothing rewritten
    assert (dest / "SKILL.md").stat().st_mtime_ns == mtime_before


def test_sync_source_only_update_rewrites_target(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    assert _run(ss, "sync", base, personal, home, state_root) == 0
    skill_md = base / ".skills-src" / "skills" / "alpha" / "SKILL.md"
    skill_md.write_text(skill_md.read_text() + "extra line\n")
    rc = _run(ss, "sync", base, personal, home, state_root)
    assert rc == 0
    dest_text = (home / ".claude" / "skills" / "alpha" / "SKILL.md").read_text()
    assert "extra line" in dest_text


def test_sync_target_only_drift_is_reported_and_left_untouched(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    assert _run(ss, "sync", base, personal, home, state_root) == 0
    dest_md = home / ".claude" / "skills" / "alpha" / "SKILL.md"
    hand_edited = dest_md.read_text() + "HAND EDITED\n"
    dest_md.write_text(hand_edited)
    rc = _run(ss, "sync", base, personal, home, state_root)
    assert rc == 1
    assert dest_md.read_text() == hand_edited  # left untouched


def test_sync_two_sided_conflict_is_reported_and_left_untouched(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    assert _run(ss, "sync", base, personal, home, state_root) == 0
    dest_md = home / ".claude" / "skills" / "alpha" / "SKILL.md"
    hand_edited = dest_md.read_text() + "HAND EDITED\n"
    dest_md.write_text(hand_edited)
    src_md = base / ".skills-src" / "skills" / "alpha" / "SKILL.md"
    src_md.write_text(src_md.read_text() + "source changed too\n")
    rc = _run(ss, "sync", base, personal, home, state_root)
    assert rc == 1
    assert dest_md.read_text() == hand_edited  # left untouched, not auto-resolved


def test_sync_reports_unmanaged_existing_dir_without_overwriting(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    unmanaged_dir = home / ".claude" / "skills" / "alpha"
    unmanaged_dir.mkdir(parents=True)
    (unmanaged_dir / "SKILL.md").write_text("hand-installed, never synced\n")
    rc = _run(ss, "sync", base, personal, home, state_root)
    assert rc == 1
    assert (unmanaged_dir / "SKILL.md").read_text() == "hand-installed, never synced\n"
    ledger = json.loads((state_root / "ledger.json").read_text())
    assert "native:alpha" not in ledger["targets"]


def test_atomic_replace_dir_failure_leaves_prior_target_intact(ss, tmp_path):
    final_dir = tmp_path / "final"
    final_dir.mkdir()
    (final_dir / "keep.txt").write_text("original")
    staged_dir = tmp_path / "staged"
    staged_dir.mkdir()
    (staged_dir / "new.txt").write_text("new")

    real_rename = ss._rename

    def flaky_rename(src, dst):
        if str(dst) == str(final_dir) and str(src) == str(staged_dir):
            raise OSError("simulated rename failure")
        return real_rename(src, dst)

    ss._rename = flaky_rename
    try:
        try:
            ss.atomic_replace_dir(final_dir, staged_dir)
        except OSError:
            pass
        else:
            raise AssertionError("expected the simulated rename failure to propagate")
    finally:
        ss._rename = real_rename

    assert (final_dir / "keep.txt").read_text() == "original"
    assert not (final_dir / "new.txt").exists()


def test_atomic_replace_dir_first_write_has_no_prior_target(ss, tmp_path):
    final_dir = tmp_path / "final-fresh"
    staged_dir = tmp_path / "staged-fresh"
    staged_dir.mkdir()
    (staged_dir / "a.txt").write_text("a")
    ss.atomic_replace_dir(final_dir, staged_dir)
    assert (final_dir / "a.txt").read_text() == "a"
    assert not staged_dir.exists()
