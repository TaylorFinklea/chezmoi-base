import pytest

from .conftest import make_base_repo, make_personal_repo, write_catalog_toml, write_skill


def test_load_catalog_parses_valid_schema(ss, tmp_path):
    repo = make_base_repo(tmp_path, skill_names=["alpha", "beta"])
    catalog = ss.load_catalog(repo / ".skillcatalog.toml")
    assert catalog.owner == "base-managed"
    assert catalog.roles == ("personal", "work")
    assert {r.name for r in catalog.skills} == {"alpha", "beta"}
    assert catalog.source_root == repo / ".skills-src" / "skills"


def test_load_catalog_rejects_bad_schema_version(ss, tmp_path):
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills", records=[])
    (repo / ".skillcatalog.toml").write_text(
        (repo / ".skillcatalog.toml").read_text().replace("schema = 1", "schema = 2")
    )
    with pytest.raises(ss.SkillError, match="unsupported schema"):
        ss.load_catalog(repo / ".skillcatalog.toml")


def test_load_catalog_rejects_unknown_owner(ss, tmp_path):
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills", records=[])
    text = (repo / ".skillcatalog.toml").read_text().replace('"base-managed"', '"nobody-managed"')
    (repo / ".skillcatalog.toml").write_text(text)
    with pytest.raises(ss.SkillError, match="owner must be one of"):
        ss.load_catalog(repo / ".skillcatalog.toml")


def test_load_catalog_rejects_empty_roles(ss, tmp_path):
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="base-managed", roles=[], source_root=".skills-src/skills", records=[])
    with pytest.raises(ss.SkillError, match="roles must be a nonempty subset"):
        ss.load_catalog(repo / ".skillcatalog.toml")


def test_load_catalog_rejects_missing_skill_keys(ss, tmp_path):
    repo = tmp_path / "repo"
    (repo).mkdir()
    (repo / ".skillcatalog.toml").write_text(
        'schema = 1\nowner = "base-managed"\nroles = ["personal", "work"]\n'
        'source_root = ".skills-src/skills"\n\n[[skills]]\nname = "alpha"\n'
        'targets = ["native"]\n'  # missing activation/upstream_ref/transform
    )
    with pytest.raises(ss.SkillError, match="missing keys"):
        ss.load_catalog(repo / ".skillcatalog.toml")


def test_load_catalog_rejects_duplicate_name_within_catalog(ss, tmp_path):
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills",
                        records=[{"name": "alpha", "targets": ["native"]},
                                 {"name": "alpha", "targets": ["codex"]}])
    write_skill(repo / ".skills-src" / "skills", "alpha")
    with pytest.raises(ss.SkillError, match="duplicate skill name"):
        ss.load_catalog(repo / ".skillcatalog.toml")


def test_load_catalog_rejects_reserved_skill_name(ss, tmp_path):
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills",
                        records=[{"name": ".system", "targets": ["native"]}])
    with pytest.raises(ss.SkillError, match="reserved path marker"):
        ss.load_catalog(repo / ".skillcatalog.toml")


def test_load_catalog_rejects_skill_name_with_path_separator(ss, tmp_path):
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills",
                        records=[{"name": "alpha/evil", "targets": ["native"]}])
    with pytest.raises(ss.SkillError, match="not a safe path segment"):
        ss.load_catalog(repo / ".skillcatalog.toml")


def test_load_catalog_rejects_skill_name_that_is_dot_dot(ss, tmp_path):
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills",
                        records=[{"name": "..", "targets": ["native"]}])
    with pytest.raises(ss.SkillError, match="not a safe path segment"):
        ss.load_catalog(repo / ".skillcatalog.toml")


def test_load_catalog_rejects_invalid_target(ss, tmp_path):
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills",
                        records=[{"name": "alpha", "targets": ["nowhere"]}])
    with pytest.raises(ss.SkillError, match="targets must be a nonempty subset"):
        ss.load_catalog(repo / ".skillcatalog.toml")


def test_load_catalog_rejects_hermes_target_on_base_catalog(ss, tmp_path):
    # base roles include "work"; hermes only serves "personal" -> not allowed for base.
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills",
                        records=[{"name": "alpha", "targets": ["hermes"]}])
    with pytest.raises(ss.SkillError, match="not allowed for roles"):
        ss.load_catalog(repo / ".skillcatalog.toml")


def test_load_catalog_allows_hermes_target_on_personal_only_catalog(ss, tmp_path):
    repo = make_personal_repo(tmp_path, skill_names=["pskill"], targets=["hermes"])
    catalog = ss.load_catalog(repo / ".skillcatalog.toml")
    assert catalog.skills[0].targets == ("hermes",)


def test_load_catalog_rejects_hermes_target_on_work_catalog(ss, tmp_path):
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="work-managed", roles=["work"],
                        source_root="skills",
                        records=[{"name": "wskill", "targets": ["hermes"]}])
    with pytest.raises(ss.SkillError, match="not allowed for roles"):
        ss.load_catalog(repo / ".skillcatalog.toml", validate_sources=False)


def test_load_catalog_rejects_bad_activation(ss, tmp_path):
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills",
                        records=[{"name": "alpha", "targets": ["native"], "activation": "sometimes"}])
    with pytest.raises(ss.SkillError, match="activation must be one of"):
        ss.load_catalog(repo / ".skillcatalog.toml")


def test_load_catalog_rejects_bad_transform(ss, tmp_path):
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills",
                        records=[{"name": "alpha", "targets": ["native"], "transform": "weird"}])
    with pytest.raises(ss.SkillError, match="transform must be one of"):
        ss.load_catalog(repo / ".skillcatalog.toml")


def test_load_catalog_rejects_empty_upstream_ref(ss, tmp_path):
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills",
                        records=[{"name": "alpha", "targets": ["native"], "upstream_ref": "  "}])
    with pytest.raises(ss.SkillError, match="upstream_ref must be nonempty"):
        ss.load_catalog(repo / ".skillcatalog.toml")


def test_load_catalog_rejects_missing_skill_md(ss, tmp_path):
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills",
                        records=[{"name": "ghost", "targets": ["native"]}])
    (repo / ".skills-src" / "skills").mkdir(parents=True)
    with pytest.raises(ss.SkillError, match="missing SKILL.md"):
        ss.load_catalog(repo / ".skillcatalog.toml")


def test_load_catalog_rejects_frontmatter_name_mismatch(ss, tmp_path):
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills",
                        records=[{"name": "alpha", "targets": ["native"]}])
    src = repo / ".skills-src" / "skills" / "alpha"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text("---\nname: not-alpha\ndescription: d\n---\nbody\n")
    with pytest.raises(ss.SkillError, match="frontmatter name"):
        ss.load_catalog(repo / ".skillcatalog.toml")


def test_load_catalog_rejects_empty_description(ss, tmp_path):
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills",
                        records=[{"name": "alpha", "targets": ["native"]}])
    src = repo / ".skills-src" / "skills" / "alpha"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text("---\nname: alpha\ndescription: ''\n---\nbody\n")
    with pytest.raises(ss.SkillError, match="missing/empty frontmatter description"):
        ss.load_catalog(repo / ".skillcatalog.toml")


def test_load_catalog_schema_only_skips_source_touch(ss, tmp_path):
    """validate_sources=False must not stat/read the source tree at all."""
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills",
                        records=[{"name": "ghost", "targets": ["native"]}])
    # deliberately no source tree on disk at all
    catalog = ss.load_catalog(repo / ".skillcatalog.toml", validate_sources=False)
    assert catalog.skills[0].name == "ghost"


def test_load_catalog_work_source_root_unresolved_without_work_root(ss, tmp_path):
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="work-managed", roles=["work"], source_root="skills",
                        records=[{"name": "wskill", "targets": ["native"]}])
    catalog = ss.load_catalog(repo / ".skillcatalog.toml", validate_sources=False)
    assert catalog.source_root is None
    assert catalog.external_source is True


def test_load_catalog_work_requires_work_root_to_validate_sources(ss, tmp_path):
    repo = tmp_path / "repo"
    write_catalog_toml(repo, owner="work-managed", roles=["work"], source_root="skills",
                        records=[{"name": "wskill", "targets": ["native"]}])
    with pytest.raises(ss.SkillError, match="source root unresolved"):
        ss.load_catalog(repo / ".skillcatalog.toml", validate_sources=True)
