import pytest

from .conftest import write_skill


def test_write_codex_skill_reduces_frontmatter_and_copies_refs(ss, tmp_path):
    src = write_skill(tmp_path / "src", "foo", extra_frontmatter={"allowed-tools": "[Bash]"},
                       extra_files={"references/r.md": "ref"})
    codex_root = tmp_path / "codex"
    codex_root.mkdir()
    ss.write_codex_skill(src, codex_root)
    dest = codex_root / "foo"
    meta, _ = ss.split_frontmatter((dest / "SKILL.md").read_text())
    assert meta == {"name": "foo", "description": "does a thing"}       # reduced
    assert (dest / "references" / "r.md").read_text() == "ref"          # refs copied


def test_write_codex_carries_source_owned_openai_yaml(ss, tmp_path):
    src = write_skill(tmp_path / "src", "foo", extra_files={"agents/openai.yaml": "interface:\n  display_name: Src\n"})
    codex_root = tmp_path / "codex"
    codex_root.mkdir()
    ss.write_codex_skill(src, codex_root)
    assert "Src" in (codex_root / "foo" / "agents" / "openai.yaml").read_text()


def test_write_codex_no_longer_preserves_hand_tuned_dest_yaml(ss, tmp_path):
    """Behavior 6: destination-sidecar preservation across resync is REMOVED —
    a re-sync from source now always overwrites the dest sidecar with the
    source-owned (or generated) content; hand edits become a reported conflict
    at the sync-engine layer, not a silent keep at the transform layer."""
    src = write_skill(tmp_path / "src", "foo")  # no agents/ dir at all
    codex_root = tmp_path / "codex"
    dest_agents = codex_root / "foo" / "agents"
    dest_agents.mkdir(parents=True)
    (dest_agents / "openai.yaml").write_text("interface:\n  display_name: HandEdited\n")
    ss.write_codex_skill(src, codex_root)
    assert "HandEdited" not in (codex_root / "foo" / "agents" / "openai.yaml").read_text()


def test_write_codex_generates_openai_yaml_when_absent(ss, tmp_path):
    src = write_skill(tmp_path / "src", "foo")  # no agents/
    codex_root = tmp_path / "codex"
    codex_root.mkdir()
    ss.write_codex_skill(src, codex_root)
    assert (codex_root / "foo" / "agents" / "openai.yaml").exists()

def test_write_codex_refuses_reserved_system_dir(ss, tmp_path):
    src = write_skill(tmp_path / "src", "foo")
    codex_root = tmp_path / "codex" / ".system"
    codex_root.mkdir(parents=True)
    with pytest.raises(ss.SkillError, match="reserved"):
        ss.write_codex_skill(src, codex_root)


def test_write_codex_skill_is_deterministic(ss, tmp_path):
    """Deterministic tree hash of the transformed output — same source, two
    independent writes into different roots must hash identically."""
    src = write_skill(tmp_path / "src", "foo", extra_files={"references/r.md": "ref"})
    dest_a = ss.write_codex_skill(src, tmp_path / "codex-a")
    dest_b = ss.write_codex_skill(src, tmp_path / "codex-b")
    assert ss.tree_hash(dest_a) == ss.tree_hash(dest_b)


def test_stage_projection_native_is_verbatim_copy(ss, tmp_path):
    src = write_skill(tmp_path / "src", "foo", extra_frontmatter={"allowed-tools": "[Bash]"})
    staged = ss.stage_projection(src, "native", "standard", tmp_path / "stage")
    meta, _ = ss.split_frontmatter((staged / "SKILL.md").read_text())
    assert meta["allowed-tools"] == ["Bash"]  # untouched, unlike codex reduction
