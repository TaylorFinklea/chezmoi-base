from .conftest import write_skill


def test_stage_projection_codex_reduces_frontmatter_and_copies_refs(ss, tmp_path):
    src = write_skill(tmp_path / "src", "foo", extra_frontmatter={"allowed-tools": "[Bash]"},
                       extra_files={"references/r.md": "ref"})
    staged = ss.stage_projection(src, "codex", "standard", tmp_path / "stage")
    meta, _ = ss.split_frontmatter((staged / "SKILL.md").read_text())
    assert meta == {"name": "foo", "description": "does a thing"}       # reduced
    assert (staged / "references" / "r.md").read_text() == "ref"          # refs copied


def test_stage_projection_codex_carries_source_owned_openai_yaml(ss, tmp_path):
    src = write_skill(tmp_path / "src", "foo",
                       extra_files={"agents/openai.yaml": "interface:\n  display_name: Src\n"})
    staged = ss.stage_projection(src, "codex", "standard", tmp_path / "stage")
    assert "Src" in (staged / "agents" / "openai.yaml").read_text()


def test_stage_projection_codex_overwrites_hand_tuned_dest_yaml(ss, tmp_path):
    """Behavior 6: destination-sidecar preservation across resync is REMOVED —
    a re-stage from source now always overwrites the dest sidecar with the
    source-owned (or generated) content; hand edits become a reported
    conflict at the sync-engine layer (test_sync.py), not a silent keep at
    the transform layer. `stage_projection()` always wipes any pre-existing
    staging destination before `_stage_codex()` runs, so a hand-edited file
    left over at the staging path from a prior run must not survive."""
    src = write_skill(tmp_path / "src", "foo")  # no agents/ dir at all
    stage_root = tmp_path / "stage"
    dest_agents = stage_root / "codex" / "foo" / "agents"
    dest_agents.mkdir(parents=True)
    (dest_agents / "openai.yaml").write_text("interface:\n  display_name: HandEdited\n")
    staged = ss.stage_projection(src, "codex", "standard", stage_root)
    assert "HandEdited" not in (staged / "agents" / "openai.yaml").read_text()


def test_stage_projection_codex_generates_openai_yaml_when_absent(ss, tmp_path):
    src = write_skill(tmp_path / "src", "foo")  # no agents/
    staged = ss.stage_projection(src, "codex", "standard", tmp_path / "stage")
    assert (staged / "agents" / "openai.yaml").exists()


def test_stage_projection_codex_is_deterministic(ss, tmp_path):
    """Deterministic tree hash of the transformed output — same source, two
    independent stagings into different roots must hash identically."""
    src = write_skill(tmp_path / "src", "foo", extra_files={"references/r.md": "ref"})
    staged_a = ss.stage_projection(src, "codex", "standard", tmp_path / "stage-a")
    staged_b = ss.stage_projection(src, "codex", "standard", tmp_path / "stage-b")
    assert ss.tree_hash(staged_a) == ss.tree_hash(staged_b)


def test_stage_projection_native_is_verbatim_copy(ss, tmp_path):
    src = write_skill(tmp_path / "src", "foo", extra_frontmatter={"allowed-tools": "[Bash]"})
    staged = ss.stage_projection(src, "native", "standard", tmp_path / "stage")
    meta, _ = ss.split_frontmatter((staged / "SKILL.md").read_text())
    assert meta["allowed-tools"] == ["Bash"]  # untouched, unlike codex reduction
