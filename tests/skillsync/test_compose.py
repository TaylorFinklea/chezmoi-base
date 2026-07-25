import pytest

from .conftest import make_base_repo, make_personal_repo, make_work_repo, build_repo


def test_compose_profile_personal_merges_base_and_overlay(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"])
    base_cat = ss.load_catalog(base / ".skillcatalog.toml")
    overlay_cat = ss.load_catalog(personal / ".skillcatalog.toml")
    composed = ss.compose_profile("personal", base_cat, overlay_cat)
    assert set(composed.skills) == {"alpha", "pskill"}
    assert composed.skills["alpha"][0].owner == "base-managed"
    assert composed.skills["pskill"][0].owner == "personal-managed"


def test_compose_profile_rejects_cross_catalog_name_collision(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["shared-name"])
    personal = make_personal_repo(tmp_path, skill_names=["shared-name"])
    base_cat = ss.load_catalog(base / ".skillcatalog.toml")
    overlay_cat = ss.load_catalog(personal / ".skillcatalog.toml")
    with pytest.raises(ss.SkillError, match="cross-catalog name collision"):
        ss.compose_profile("personal", base_cat, overlay_cat)


def test_compose_profile_rejects_wrong_overlay_owner_for_profile(ss, tmp_path):
    """Role isolation: a work-managed overlay must never compose under profile=personal."""
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    work_src = tmp_path / "work-src"
    work = make_work_repo(tmp_path, skill_names=["wskill"], external_source_dir=work_src)
    base_cat = ss.load_catalog(base / ".skillcatalog.toml")
    work_cat = ss.load_catalog(work / ".skillcatalog.toml", work_root=work_src)
    with pytest.raises(ss.SkillError, match="requires overlay owner"):
        ss.compose_profile("personal", base_cat, work_cat)


def test_compose_profile_rejects_overlay_roles_not_matching_profile(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    # a personal-managed catalog that mistakenly declares roles=["personal","work"]
    bad_personal = build_repo(tmp_path / "personal-bad", owner="personal-managed", roles=["personal", "work"],
                               skill_names=["pskill"])
    base_cat = ss.load_catalog(base / ".skillcatalog.toml")
    overlay_cat = ss.load_catalog(bad_personal / ".skillcatalog.toml")
    with pytest.raises(ss.SkillError, match="must declare roles"):
        ss.compose_profile("personal", base_cat, overlay_cat)


def test_compose_profile_rejects_base_missing_profile_role(ss, tmp_path):
    base_work_only = build_repo(tmp_path / "base-work-only", owner="base-managed", roles=["work"],
                                 skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"])
    base_cat = ss.load_catalog(base_work_only / ".skillcatalog.toml")
    overlay_cat = ss.load_catalog(personal / ".skillcatalog.toml")
    with pytest.raises(ss.SkillError, match="does not declare role"):
        ss.compose_profile("personal", base_cat, overlay_cat)


def test_compose_profile_work_uses_external_source(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    work_src = tmp_path / "work-src"
    work = make_work_repo(tmp_path, skill_names=["wskill"], external_source_dir=work_src)
    base_cat = ss.load_catalog(base / ".skillcatalog.toml")
    work_cat = ss.load_catalog(work / ".skillcatalog.toml", work_root=work_src)
    composed = ss.compose_profile("work", base_cat, work_cat)
    assert set(composed.skills) == {"alpha", "wskill"}
    assert composed.skills["wskill"][0].external_source is True


class SpyPath:
    """Path-like stand-in that raises if any filesystem-touching method is invoked."""

    def __init__(self, log):
        self._log = log

    def __getattr__(self, item):
        self._log.append(item)
        raise AssertionError(f"work-root spy: unexpected attribute access {item!r} under --profile personal")

    def __truediv__(self, other):
        self._log.append(f"__truediv__({other!r})")
        raise AssertionError("work-root spy: unexpected path join under --profile personal")

    def __fspath__(self):
        self._log.append("__fspath__")
        raise AssertionError("work-root spy: unexpected os.fspath() under --profile personal")

    def __str__(self):
        self._log.append("__str__")
        raise AssertionError("work-root spy: unexpected str() under --profile personal")


def test_personal_profile_never_touches_work_root_spy(ss, tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"])
    log: list[str] = []
    spy = SpyPath(log)
    base_cat, overlay_cat = ss.load_profile_catalogs(
        "personal", base, personal, work_root=spy, require_sources=True
    )
    assert overlay_cat.owner == "personal-managed"
    assert log == []  # the spy was never touched


def test_work_profile_without_require_sources_also_ignores_work_root(ss, tmp_path):
    """check --profile work (no --require-sources) validates TOML shape only,
    never touching the external work source path — even a spy survives."""
    base = make_base_repo(tmp_path, skill_names=["alpha"])
    work = make_work_repo(tmp_path, skill_names=["wskill"])  # no external_source_dir at all
    log: list[str] = []
    spy = SpyPath(log)
    base_cat, overlay_cat = ss.load_profile_catalogs(
        "work", base, work, work_root=spy, require_sources=False
    )
    assert overlay_cat.owner == "work-managed"
    assert overlay_cat.source_root is None
    assert log == []
