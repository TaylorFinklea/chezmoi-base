from .conftest import make_base_repo, make_personal_repo


def _diff(ss, base, personal, tmp_path, extra=()):
    return ss.main([
        "diff", "--profile", "personal", "--base-root", str(base), "--overlay-root", str(personal),
        "--home", str(tmp_path / "home"), "--state-root", str(tmp_path / "state"), *extra,
    ])


def test_diff_reports_pending_create_and_never_writes(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"], targets=["native"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"], targets=["native"])
    rc = _diff(ss, base, personal, tmp_path)
    assert rc == 1
    assert not (tmp_path / "home" / ".claude" / "skills" / "alpha").exists()  # diff never writes
    assert not (tmp_path / "state" / "ledger.json").exists()


def test_diff_clean_after_sync(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"], targets=["native"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"], targets=["native"])
    assert ss.main(["sync", "--profile", "personal", "--base-root", str(base), "--overlay-root", str(personal),
                     "--home", str(tmp_path / "home"), "--state-root", str(tmp_path / "state")]) == 0
    assert _diff(ss, base, personal, tmp_path) == 0
