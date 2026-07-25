import pytest


def test_split_frontmatter_parses_yaml_and_body(ss):
    text = "---\nname: foo\ndescription: does foo\n---\nBody here\n"
    meta, body = ss.split_frontmatter(text)
    assert meta == {"name": "foo", "description": "does foo"}
    assert body.strip() == "Body here"


def test_split_frontmatter_no_frontmatter_returns_empty_meta(ss):
    meta, body = ss.split_frontmatter("just a body, no fences\n")
    assert meta == {}
    assert body.startswith("just a body")


def test_reduce_for_codex_keeps_only_name_and_description(ss):
    meta = {"name": "foo", "description": "d", "allowed-tools": ["Bash"], "user-invocable": False}
    assert ss.reduce_for_codex(meta, "foo") == {"name": "foo", "description": "d"}


def test_reduce_for_codex_forces_name_equals_dirname(ss):
    out = ss.reduce_for_codex({"name": "Display Label", "description": "d"}, "my-skill")
    assert out["name"] == "my-skill"


def test_reduce_for_codex_requires_description(ss):
    with pytest.raises(ss.SkillError):
        ss.reduce_for_codex({"name": "foo"}, "foo")


def test_render_frontmatter_roundtrips(ss):
    rendered = ss.render_frontmatter({"name": "foo", "description": "d"})
    meta, _ = ss.split_frontmatter(rendered + "body")
    assert meta == {"name": "foo", "description": "d"}


def test_render_frontmatter_preserves_unicode_and_does_not_linefold(ss):
    desc = "Use when reconciling — em dash — " + "and a deliberately long line " * 6
    out = ss.render_frontmatter({"name": "x", "description": desc})
    assert "\\u2014" not in out          # em-dash not escaped
    assert "—" in out                     # kept literal
    assert "\\\n" not in out              # no backslash line-folding
    meta, _ = ss.split_frontmatter(out + "body")
    assert meta["description"] == desc    # exact round-trip
