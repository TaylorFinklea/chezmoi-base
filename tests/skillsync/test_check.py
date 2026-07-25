import shutil
from pathlib import Path

from .conftest import make_base_repo, make_personal_repo, make_work_repo


def _check(ss, base, overlay, profile, tmp_path, extra=()):
    return ss.main([
        "check", "--profile", profile, "--base-root", str(base), "--overlay-root", str(overlay),
        "--home", str(tmp_path / "home"), *extra,
    ])


def _lock(ss, base, overlay, profile, tmp_path, extra=()):
    return ss.main([
        "lock", "--profile", profile, "--base-root", str(base), "--overlay-root", str(overlay),
        "--home", str(tmp_path / "home"), *extra,
    ])


def test_check_clean_personal_profile_returns_zero(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"])
    assert _lock(ss, base, personal, "personal", tmp_path) == 0
    assert _check(ss, base, personal, "personal", tmp_path) == 0


def test_check_reports_stale_lock_as_drift(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"])
    assert _lock(ss, base, personal, "personal", tmp_path) == 0
    skill_md = base / ".skills-src" / "skills" / "alpha" / "SKILL.md"
    skill_md.write_text(skill_md.read_text() + "drift\n")
    assert _check(ss, base, personal, "personal", tmp_path) == 1


def test_check_invalid_composition_returns_two(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["shared"])
    personal = make_personal_repo(tmp_path, skill_names=["shared"])  # cross-catalog collision
    assert _check(ss, base, personal, "personal", tmp_path) == 2


def test_check_work_profile_without_require_sources_never_touches_external_source(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"])
    work = make_work_repo(tmp_path, skill_names=["wskill"])  # NO external_source_dir created at all
    # freshen base's own lock via the personal profile (base's content is identical either way)
    assert _lock(ss, base, personal, "personal", tmp_path) == 0
    rc = _check(ss, base, work, "work", tmp_path)
    assert rc == 0  # schema/shape valid even though the external source doesn't exist anywhere


def test_check_work_profile_require_sources_needs_existing_work_root(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    work = make_work_repo(tmp_path, skill_names=["wskill"])
    rc = _check(ss, base, work, "work", tmp_path, extra=["--require-sources"])
    assert rc == 2  # no --work-root supplied at all


def test_check_work_profile_require_sources_with_real_source_is_clean(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    work_src = tmp_path / "work-src"
    work = make_work_repo(tmp_path, skill_names=["wskill"], external_source_dir=work_src)
    assert _lock(ss, base, work, "work", tmp_path, extra=["--work-root", str(work_src)]) == 0
    rc = _check(ss, base, work, "work", tmp_path, extra=["--require-sources", "--work-root", str(work_src)])
    assert rc == 0


def test_check_work_profile_require_sources_missing_work_root_dir_fails(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    work = make_work_repo(tmp_path, skill_names=["wskill"])
    rc = _check(ss, base, work, "work", tmp_path,
                extra=["--require-sources", "--work-root", str(tmp_path / "does-not-exist")])
    assert rc == 2


def test_check_hands_off_to_public_safety_scanner(ss, tmp_path):
    """When the base repo ships scripts/check-public-safety.py, check invokes it
    and fails if it finds a violation. The injected token below is built by
    concatenation at runtime so this committed test file itself never contains
    a literal secret-shaped string that would trip the very scanner it tests."""
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"])
    scanner_src = Path(__file__).resolve().parents[2] / "scripts" / "check-public-safety.py"
    (base / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(scanner_src, base / "scripts" / "check-public-safety.py")
    assert _lock(ss, base, personal, "personal", tmp_path) == 0
    assert _check(ss, base, personal, "personal", tmp_path) == 0

    # inject a forbidden github-credential-shaped token into base's own source content
    fake_token = "gh" + "p_" + ("x" * 24)
    skill_md = base / ".skills-src" / "skills" / "alpha" / "SKILL.md"
    skill_md.write_text(skill_md.read_text() + "\n" + fake_token + "\n")
    assert _check(ss, base, personal, "personal", tmp_path) == 2
