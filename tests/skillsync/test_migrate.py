import json

import pytest

from .conftest import make_base_repo, make_personal_repo


def _setup(tmp_path):
    base = make_base_repo(tmp_path, skill_names=["alpha"], targets=["pi"])
    personal = make_personal_repo(tmp_path, skill_names=["pskill"], targets=["pi"])
    home = tmp_path / "home"
    state_root = tmp_path / "state"
    return base, personal, home, state_root


def _run(ss, cmd, base, personal, home, state_root, extra=()):
    argv = [cmd, "--profile", "personal", "--base-root", str(base), "--overlay-root", str(personal),
            "--home", str(home), "--state-root", str(state_root), *extra]
    return ss.main(argv)


def _exact_projection(ss, base, name, home):
    """What sync would generate for skill `name` at the Pi target, staged
    for direct comparison/adoption in these tests."""
    src = base / ".skills-src" / "skills" / name
    import shutil
    dest = home / ".pi" / "agent" / "skills" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    return dest


def test_migrate_dry_run_reports_without_writing(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    _exact_projection(ss, base, "alpha", home)
    rc = _run(ss, "migrate", base, personal, home, state_root)
    assert rc == 1  # pending adoption reported
    assert not (home / ".pi" / "agent" / "skills" / "alpha" / ".skillsync-owner.json").exists()
    assert not (state_root / "ledger.json").exists()


def test_migrate_adopts_exact_match_legacy_directory(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    _exact_projection(ss, base, "alpha", home)
    rc = _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"])
    assert rc == 0
    assert (home / ".pi" / "agent" / "skills" / "alpha" / ".skillsync-owner.json").exists()
    ledger = json.loads((state_root / "ledger.json").read_text())
    assert "pi:alpha" in ledger["targets"]
    # bytes of the pre-existing SKILL.md were not rewritten (adoption != resync)
    original_bytes = (base / ".skills-src" / "skills" / "alpha" / "SKILL.md").read_bytes()
    assert (home / ".pi" / "agent" / "skills" / "alpha" / "SKILL.md").read_bytes() == original_bytes


def test_migrate_refuses_adoption_on_content_mismatch(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    dest = home / ".pi" / "agent" / "skills" / "alpha"
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text("---\nname: alpha\ndescription: totally different\n---\nnot the same body\n")
    rc = _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"])
    assert rc == 1
    assert not (dest / ".skillsync-owner.json").exists()
    ledger_path = state_root / "ledger.json"
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text())
        assert "pi:alpha" not in ledger.get("targets", {})
    # mismatched content is left exactly as-is, never overwritten
    assert "totally different" in (dest / "SKILL.md").read_text()


def test_migrate_prunes_only_stamped_retired_skills(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    assert _run(ss, "sync", base, personal, home, state_root) == 0

    # retire "alpha" from the base catalog (rewrite catalog TOML without it)
    from .conftest import write_catalog_toml
    write_catalog_toml(base, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills", records=[])

    rc = _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"])
    assert rc == 0
    assert not (home / ".pi" / "agent" / "skills" / "alpha").exists()  # pruned
    assert (home / ".pi" / "agent" / "skills" / "pskill").exists()      # still catalogued, untouched
    ledger = json.loads((state_root / "ledger.json").read_text())
    assert "pi:alpha" not in ledger["targets"]


def test_migrate_blocks_prune_of_hand_edited_retired_skill(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    assert _run(ss, "sync", base, personal, home, state_root) == 0
    dest = home / ".pi" / "agent" / "skills" / "alpha"
    (dest / "SKILL.md").write_text((dest / "SKILL.md").read_text() + "hand edited after retirement\n")

    from .conftest import write_catalog_toml
    write_catalog_toml(base, owner="base-managed", roles=["personal", "work"],
                        source_root=".skills-src/skills", records=[])

    rc = _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"])
    assert rc == 1
    assert dest.exists()  # NOT deleted — content diverged from what we generated
    ledger = json.loads((state_root / "ledger.json").read_text())
    assert "pi:alpha" in ledger["targets"]  # ledger entry retained, unresolved


def _seed_native_retired_target(ss, home, state_root, *, stamp_owner="base-managed"):
    dest = home / ".claude" / "skills" / "alpha"
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text("legacy native projection\n")
    source = "base-managed:.skills-src/skills/alpha"
    generated_hash = ss.tree_hash(dest)
    ss.write_owner_stamp(
        dest, owner=stamp_owner, source=source,
        generated_hash=generated_hash, transform="standard",
    )
    target_hash = ss.tree_hash(dest)
    state_root.mkdir(parents=True, exist_ok=True)
    (state_root / "ledger.json").write_text(json.dumps({
        "schema": 1,
        "targets": {
            "native:alpha": {
                "owner": "base-managed", "source": source,
                "generated_hash": generated_hash, "target_hash": target_hash,
                "transform": "standard",
            },
        },
    }))
    return dest


def test_migrate_prunes_matching_retired_native_target(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    dest = _seed_native_retired_target(ss, home, state_root)

    assert _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"]) == 0
    assert not dest.exists()
    ledger = json.loads((state_root / "ledger.json").read_text())
    assert "native:alpha" not in ledger["targets"]


@pytest.mark.parametrize("mismatch", ["owner", "content"])
def test_migrate_refuses_mismatched_retired_native_target(ss, tmp_path, mismatch):
    base, personal, home, state_root = _setup(tmp_path)
    dest = _seed_native_retired_target(
        ss, home, state_root,
        stamp_owner="personal-managed" if mismatch == "owner" else "base-managed",
    )
    if mismatch == "content":
        with (dest / "SKILL.md").open("a") as handle:
            handle.write("changed after migration stamp\n")

    assert _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"]) == 1
    assert dest.exists()
    ledger = json.loads((state_root / "ledger.json").read_text())
    assert "native:alpha" in ledger["targets"]


def test_migrate_blocks_non_object_native_owner_stamp(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    dest = _seed_native_retired_target(ss, home, state_root)
    (dest / ".skillsync-owner.json").write_text("[]\n")

    assert _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"]) == 1
    assert dest.exists()
    ledger = json.loads((state_root / "ledger.json").read_text())
    assert "native:alpha" in ledger["targets"]


@pytest.mark.parametrize("field", ["owner", "transform"])
@pytest.mark.parametrize("malformed", [[], {}], ids=["list", "object"])
def test_migrate_blocks_non_string_native_owner_and_transform(ss, tmp_path, capsys, field, malformed):
    base, personal, home, state_root = _setup(tmp_path)
    dest = _seed_native_retired_target(ss, home, state_root)
    stamp_path = dest / ".skillsync-owner.json"
    stamp = json.loads(stamp_path.read_text())
    stamp[field] = malformed
    stamp_path.write_text(json.dumps(stamp))
    ledger_path = state_root / "ledger.json"
    ledger = json.loads(ledger_path.read_text())
    ledger["targets"]["native:alpha"][field] = malformed
    ledger_path.write_text(json.dumps(ledger))
    content_before = (dest / "SKILL.md").read_bytes()

    assert _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"]) == 1
    assert "blocked prune native/alpha" in capsys.readouterr().err
    assert (dest / "SKILL.md").read_bytes() == content_before
    assert json.loads(stamp_path.read_text()) == stamp
    assert json.loads(ledger_path.read_text())["targets"]["native:alpha"][field] == malformed


def test_migrate_blocks_identically_changed_but_well_formed_generated_hash(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    dest = _seed_native_retired_target(ss, home, state_root)
    actual_hash = ss.tree_hash(dest)
    replacement_digest = "0" * 64 if not actual_hash.endswith("0" * 64) else "1" * 64
    replacement_hash = f"sha256:{replacement_digest}"
    stamp_path = dest / ".skillsync-owner.json"
    stamp = json.loads(stamp_path.read_text())
    stamp["generated_hash"] = replacement_hash
    stamp_path.write_text(json.dumps(stamp))
    ledger_path = state_root / "ledger.json"
    ledger = json.loads(ledger_path.read_text())
    ledger["targets"]["native:alpha"]["generated_hash"] = replacement_hash
    ledger_path.write_text(json.dumps(ledger))

    assert _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"]) == 1
    assert dest.exists()
    ledger = json.loads(ledger_path.read_text())
    assert "native:alpha" in ledger["targets"]


@pytest.mark.parametrize("malformed", ["stamp-generated", "ledger-generated", "ledger-target"])
def test_migrate_blocks_malformed_native_hashes(ss, tmp_path, malformed):
    base, personal, home, state_root = _setup(tmp_path)
    dest = _seed_native_retired_target(ss, home, state_root)
    stamp_path = dest / ".skillsync-owner.json"
    stamp = json.loads(stamp_path.read_text())
    ledger_path = state_root / "ledger.json"
    ledger = json.loads(ledger_path.read_text())
    entry = ledger["targets"]["native:alpha"]
    if malformed == "stamp-generated":
        stamp["generated_hash"] = "sha256:not-a-digest"
        stamp_path.write_text(json.dumps(stamp))
    elif malformed == "ledger-generated":
        entry["generated_hash"] = "sha256:not-a-digest"
    else:
        entry["target_hash"] = "sha256:not-a-digest"
    ledger_path.write_text(json.dumps(ledger))

    assert _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"]) == 1
    assert dest.exists()
    ledger = json.loads(ledger_path.read_text())
    assert "native:alpha" in ledger["targets"]


def test_migrate_preserves_native_ledger_when_default_path_is_absent(ss, tmp_path):
    import shutil

    base, personal, home, state_root = _setup(tmp_path)
    dest = _seed_native_retired_target(ss, home, state_root)
    shutil.rmtree(dest)

    assert _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"]) == 1
    ledger = json.loads((state_root / "ledger.json").read_text())
    assert "native:alpha" in ledger["targets"]


@pytest.mark.parametrize("component", ["home", ".claude", "skills", "alpha"])
def test_migrate_blocks_native_prune_through_symlink_component(ss, tmp_path, component):
    import shutil

    base, personal, home, state_root = _setup(tmp_path)
    dest = _seed_native_retired_target(ss, home, state_root)
    if component == "home":
        redirected = tmp_path / "redirected-home"
        shutil.move(home, redirected)
        home.symlink_to(redirected, target_is_directory=True)
        outside_dest = redirected / ".claude" / "skills" / "alpha"
    elif component == ".claude":
        redirected = tmp_path / "redirected-claude"
        shutil.move(home / ".claude", redirected)
        (home / ".claude").symlink_to(redirected, target_is_directory=True)
        outside_dest = redirected / "skills" / "alpha"
    elif component == "skills":
        redirected = tmp_path / "redirected-skills"
        shutil.move(home / ".claude" / "skills", redirected)
        (home / ".claude" / "skills").symlink_to(redirected, target_is_directory=True)
        outside_dest = redirected / "alpha"
    else:
        redirected = tmp_path / "redirected-alpha"
        shutil.move(dest, redirected)
        dest.symlink_to(redirected, target_is_directory=True)
        outside_dest = redirected

    assert _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"]) == 1
    assert outside_dest.exists()
    ledger = json.loads((state_root / "ledger.json").read_text())
    assert "native:alpha" in ledger["targets"]


def test_migrate_never_touches_unmanaged_sibling(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    stray = home / ".pi" / "agent" / "skills" / "totally-unrelated"
    stray.mkdir(parents=True)
    (stray / "SKILL.md").write_text("---\nname: totally-unrelated\ndescription: not in any catalog\n---\nx\n")
    rc = _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"])
    assert (stray / "SKILL.md").exists()
    assert (stray / "SKILL.md").read_text() == "---\nname: totally-unrelated\ndescription: not in any catalog\n---\nx\n"


def test_migrate_ignores_ledger_entries_for_unknown_targets(ss, tmp_path):
    base, personal, home, state_root = _setup(tmp_path)
    state_root.mkdir(parents=True)
    legacy_entry = {
        "owner": "personal-managed",
        "source": "personal-managed:.skills-src/skills/legacy",
        "generated_hash": "old-generated-hash",
        "target_hash": "old-target-hash",
        "transform": "standard",
    }
    ledger_path = state_root / "ledger.json"
    ledger_path.write_text(json.dumps({"schema": 1, "targets": {"unknown:legacy": legacy_entry}}))

    assert _run(ss, "migrate", base, personal, home, state_root, extra=["--apply"]) == 0
    ledger = json.loads(ledger_path.read_text())
    assert ledger["targets"]["unknown:legacy"] == legacy_entry
    assert not home.exists()
