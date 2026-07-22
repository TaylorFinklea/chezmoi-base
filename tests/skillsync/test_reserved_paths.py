import pytest

from .conftest import make_base_repo, make_personal_repo


def test_assert_target_root_allowed_rejects_codex_system_dir(ss, tmp_path):
    with pytest.raises(ss.SkillError, match="reserved"):
        ss.assert_target_root_allowed("codex", tmp_path / ".codex" / "skills" / ".system")


def test_assert_target_root_allowed_rejects_plugin_cache(ss, tmp_path):
    with pytest.raises(ss.SkillError, match="reserved"):
        ss.assert_target_root_allowed("native", tmp_path / ".claude" / "plugins" / "cache")


def test_assert_target_root_allowed_permits_ordinary_root(ss, tmp_path):
    ss.assert_target_root_allowed("native", tmp_path / ".claude" / "skills")  # must not raise


def test_resolve_target_roots_rejects_default_when_home_is_reserved(ss, tmp_path):
    with pytest.raises(ss.SkillError, match="reserved"):
        ss.resolve_target_roots(tmp_path, {"codex": tmp_path / ".codex" / "skills" / ".system"})


def test_cli_target_root_override_refuses_codex_system_dir(ss, tmp_path):
    """Reserved-path rejection is enforced even when passed as an explicit
    CLI --target-root override, not just for the computed defaults."""
    base = make_base_repo(tmp_path, skill_names=["alpha"], targets=["native"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"], targets=["native"])
    rc = ss.main([
        "check", "--profile", "personal",
        "--base-root", str(base), "--overlay-root", str(personal),
        "--home", str(tmp_path / "home"),
        "--target-root", f"codex={tmp_path / '.codex' / 'skills' / '.system'}",
    ])
    assert rc == 2


def test_cli_target_root_override_rejects_unknown_target_name(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"], targets=["native"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"], targets=["native"])
    rc = ss.main([
        "check", "--profile", "personal",
        "--base-root", str(base), "--overlay-root", str(personal),
        "--home", str(tmp_path / "home"),
        "--target-root", f"nowhere={tmp_path / 'x'}",
    ])
    assert rc == 2
