import os

import pytest

from .conftest import write_skill


def test_tree_hash_deterministic_across_traversal_order(ss, tmp_path):
    a = tmp_path / "a"
    write_skill(a, "skill", extra_files={"references/one.md": "1", "references/two.md": "2"})
    b = tmp_path / "b"
    write_skill(b, "skill", extra_files={"references/two.md": "2", "references/one.md": "1"})
    assert ss.tree_hash(a / "skill") == ss.tree_hash(b / "skill")


def test_tree_hash_changes_with_content(ss, tmp_path):
    root = tmp_path / "skill"
    write_skill(root.parent, "skill")
    h1 = ss.tree_hash(root)
    (root / "SKILL.md").write_text((root / "SKILL.md").read_text() + "more\n")
    h2 = ss.tree_hash(root)
    assert h1 != h2


def test_tree_hash_changes_with_executable_bit(ss, tmp_path):
    root = tmp_path / "skill"
    write_skill(root.parent, "skill", extra_files={"scripts/run.sh": "#!/bin/sh\necho hi\n"})
    h1 = ss.tree_hash(root)
    (root / "scripts" / "run.sh").chmod(0o755)
    h2 = ss.tree_hash(root)
    assert h1 != h2


def test_tree_hash_ignores_owner_stamp_file(ss, tmp_path):
    root = tmp_path / "skill"
    write_skill(root.parent, "skill")
    h1 = ss.tree_hash(root)
    ss.write_owner_stamp(root, owner="base-managed", source="x", generated_hash="sha256:x", transform="standard")
    h2 = ss.tree_hash(root)
    assert h1 == h2


def test_tree_hash_rejects_escaping_symlink(ss, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    root = tmp_path / "skill"
    write_skill(root.parent, "skill")
    (root / "escape.txt").symlink_to(outside)
    with pytest.raises(ss.SkillError, match="symlink escapes"):
        ss.tree_hash(root)


def test_tree_hash_allows_internal_symlink(ss, tmp_path):
    root = tmp_path / "skill"
    write_skill(root.parent, "skill")
    (root / "references").mkdir()
    (root / "references" / "r.md").write_text("ref")
    (root / "alias.md").symlink_to(root / "references" / "r.md")
    # must not raise
    ss.tree_hash(root)


def test_tree_hash_not_a_directory_raises(ss, tmp_path):
    f = tmp_path / "notadir"
    f.write_text("x")
    with pytest.raises(ss.SkillError, match="not a directory"):
        ss.tree_hash(f)
