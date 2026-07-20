import concurrent.futures
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "lib"))

from codex_forge.state import ForgeState, RepoIdentity, StateError, StateStore, transition


_MAX_RECORD_BYTES = 10 * 1024 * 1024


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name).resolve()
        self.root = self.tmp_path / "state"
        self.store = StateStore(self.root, "0.1.0")
        self.cwd = self.tmp_path / "repo"
        self.cwd.mkdir()
        self.repo = RepoIdentity(self.cwd, "abc123")

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_load_and_private_permissions(self):
        state = self.store.create("session-1", self.cwd, self.repo)
        self.assertEqual(state.status, "shaping")
        self.assertEqual(state.schema_version, 1)
        self.assertEqual(state.plugin_version, "0.1.0")
        self.assertEqual(state.cwd, self.cwd.resolve())
        self.assertEqual(self.store.load("session-1"), state)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        record = next(self.root.iterdir())
        self.assertEqual(stat.S_IMODE(record.stat().st_mode), 0o600)
        self.assertEqual(record.name, __import__("hashlib").sha256(b"session-1").hexdigest())

    def test_rejects_path_derived_session_identifiers(self):
        for session_id in ("", ".", "..", "a/b", "a\\b", "a\x00b"):
            with self.subTest(session_id=session_id), self.assertRaises(ValueError):
                self.store.create(session_id, self.cwd, None)

    def test_all_allowed_transitions(self):
        state = self.store.create("s", self.cwd, None)
        state = transition(state, "freeze")
        self.assertEqual(state.status, "frozen")
        state = transition(state, "approve_direct")
        self.assertEqual(state.status, "approved_direct")
        state = transition(state, "begin")
        self.assertEqual(state.status, "executing")
        self.assertEqual(transition(state, "complete").status, "completed")

        state = transition(self.store.create("r", self.cwd, None), "freeze")
        state = transition(state, "approve_ralph")
        state = transition(state, "ralph_start")
        self.assertEqual(transition(state, "complete").status, "completed")
        self.assertEqual(transition(transition(self.store.create("x", self.cwd, None), "freeze"), "revise").status, "shaping")
        for status in ("shaping", "frozen", "approved_direct", "approved_ralph", "executing", "ralph_running"):
            source = ForgeState("x", self.cwd.resolve(), None, status, 1, "0.1.0")
            for event in ("cancel", "fail"):
                with self.subTest(status=status, event=event):
                    self.assertIn(transition(source, event).status, ("cancelled", "failed"))

    def test_rejects_every_disallowed_transition(self):
        allowed = {
            "shaping": {"freeze", "cancel", "fail"},
            "frozen": {"revise", "approve_direct", "approve_ralph", "cancel", "fail"},
            "approved_direct": {"begin", "cancel", "fail"},
            "approved_ralph": {"ralph_start", "cancel", "fail"},
            "executing": {"complete", "cancel", "fail"},
            "ralph_running": {"complete", "cancel", "fail"},
            "completed": set(),
            "cancelled": set(),
            "failed": set(),
        }
        events = {"freeze", "revise", "approve_direct", "approve_ralph", "begin",
                  "ralph_start", "complete", "cancel", "fail"}
        for status, permitted in allowed.items():
            source = ForgeState("x", self.cwd.resolve(), None, status, 1, "0.1.0")
            for event in events - permitted:
                with self.subTest(status=status, event=event), self.assertRaises(ValueError):
                    transition(source, event)

    def test_replace_is_atomic_and_rejects_mismatch(self):
        state = self.store.create("s", self.cwd, None)
        replacement = transition(state, "freeze")
        self.store.replace(replacement)
        self.assertEqual(self.store.load("s").status, "frozen")
        wrong_schema = ForgeState("s", replacement.cwd, None, "frozen", 99, "0.1.0")
        with self.assertRaises(StateError):
            self.store.replace(wrong_schema)
        wrong_plugin = ForgeState("s", replacement.cwd, None, "frozen", 1, "9.9.9")
        with self.assertRaises(StateError):
            self.store.replace(wrong_plugin)
        invalid_cwd = ForgeState("s", self.tmp_path / "missing", None, "frozen", 1, "0.1.0")
        with self.assertRaises(StateError):
            self.store.replace(invalid_cwd)

    def test_corrupt_invalid_utf8_and_symlink_fail_closed(self):
        self.assertIsNone(self.store.load("missing"))
        state = self.store.create("s", self.cwd, None)
        path = self.store.path_for("s")
        path.write_bytes(b"not json")
        with self.assertRaises(StateError):
            self.store.load("s")
        path.write_bytes(b"\xff")
        with self.assertRaises(StateError):
            self.store.load("s")
        path.unlink()
        target = self.root / "target"
        target.write_text("{}")
        path.symlink_to(target)
        with self.assertRaises(StateError):
            self.store.load("s")

    def test_root_symlink_is_rejected_by_load_and_delete(self):
        self.store.create("s", self.cwd, None)
        real_root = self.tmp_path / "real-state"
        self.root.rename(real_root)
        self.root.symlink_to(real_root, target_is_directory=True)
        for operation in (self.store.load, self.store.delete):
            with self.subTest(operation=operation.__name__), self.assertRaises(StateError):
                operation("s")

    def test_root_symlink_is_rejected_by_create(self):
        real_root = self.tmp_path / "real-state"
        real_root.mkdir()
        self.root.symlink_to(real_root, target_is_directory=True)
        with self.assertRaises(StateError):
            self.store.create("s", self.cwd, None)
        self.assertEqual(list(real_root.iterdir()), [])

    def test_root_symlink_is_rejected_by_replace(self):
        state = self.store.create("s", self.cwd, None)
        replacement = transition(state, "freeze")
        real_root = self.tmp_path / "real-state"
        self.root.rename(real_root)
        self.root.symlink_to(real_root, target_is_directory=True)
        with self.assertRaises(StateError):
            self.store.replace(replacement)
        self.assertEqual(StateStore(real_root, "0.1.0").load("s"), state)

    def test_existing_data_root_symlink_or_file_ancestors_are_rejected(self):
        real_parent = self.tmp_path / "real-parent"
        real_parent.mkdir()
        real_root = real_parent / "state"
        real_store = StateStore(real_root, "0.1.0")
        state = real_store.create("s", self.cwd, None)
        replacement = transition(state, "freeze")

        symlink_parent = self.tmp_path / "symlink-parent"
        symlink_parent.symlink_to(real_parent, target_is_directory=True)
        symlink_store = StateStore(symlink_parent / "state", "0.1.0")
        file_parent = self.tmp_path / "file-parent"
        file_parent.write_text("not a directory")
        file_store = StateStore(file_parent / "state", "0.1.0")

        for store in (symlink_store, file_store):
            for operation in (
                lambda: store.create("new", self.cwd, None),
                lambda: store.load("s"),
                lambda: store.replace(replacement),
                lambda: store.delete("s"),
            ):
                with self.subTest(store=store.data_root, operation=operation):
                    with self.assertRaises(StateError):
                        operation()
        self.assertEqual(real_store.load("s"), state)

    def test_persisted_field_types_are_validated_before_serialization(self):
        with self.assertRaises(ValueError):
            self.store.create("bad-head", self.cwd, RepoIdentity(self.cwd, True))
        with self.assertRaises(ValueError):
            self.store.create("bad-head", self.cwd, RepoIdentity(self.cwd, 7))

        state = self.store.create("s", self.cwd, None)
        invalid_states = (
            ForgeState("s", self.cwd, None, "shaping", True, "0.1.0"),
            ForgeState("s", self.cwd, RepoIdentity(self.cwd, True), "shaping", 1, "0.1.0"),
            ForgeState("s", self.cwd, object(), "shaping", 1, "0.1.0"),
            ForgeState("s", str(self.cwd), None, "shaping", 1, "0.1.0"),
            ForgeState("s", self.cwd, None, True, 1, "0.1.0"),
            ForgeState("s", self.cwd, None, "shaping", 1, True),
        )
        for invalid in invalid_states:
            with self.subTest(invalid=invalid), self.assertRaises(StateError):
                self.store.replace(invalid)
        self.assertEqual(self.store.load("s"), state)

    def test_replace_success_has_one_final_record_and_failed_publication_preserves_it(self):
        state = self.store.create("s", self.cwd, None)
        replacement = transition(state, "freeze")
        self.store.replace(replacement)
        self.assertEqual(self.store.load("s"), replacement)
        self.assertEqual([entry.name for entry in self.root.iterdir()], [self.store.path_for("s").name])

        failed = transition(replacement, "approve_direct")
        with mock.patch("codex_forge.state.os.replace", side_effect=OSError("publish failed")):
            with self.assertRaises(StateError):
                self.store.replace(failed)
        self.assertEqual(self.store.load("s"), replacement)
        self.assertEqual([entry.name for entry in self.root.iterdir()], [self.store.path_for("s").name])

    def test_loaded_and_replaced_bindings_must_be_real_directories(self):
        state = self.store.create("s", self.cwd, self.repo)
        path = self.store.path_for("s")
        payload = json.loads(path.read_text())
        missing = self.cwd / "missing"
        payload["cwd"] = str(missing)
        path.write_text(json.dumps(payload))
        with self.assertRaises(StateError):
            self.store.load("s")

        path.write_text(json.dumps({
            "schema_version": 1,
            "plugin_version": "0.1.0",
            "session_id": "s",
            "cwd": str(self.cwd),
            "repo": {"root": str(missing), "head": "abc123", "git_dir": None},
            "status": "shaping",
        }))
        with self.assertRaises(StateError):
            self.store.load("s")

        replacement = ForgeState("replace", self.cwd, RepoIdentity(missing), "shaping", 1, "0.1.0")
        with self.assertRaises(StateError):
            self.store.replace(replacement)

    def test_trailing_content_beyond_read_cap_is_rejected(self):
        state = self.store.create("s", self.cwd, None)
        path = self.store.path_for("s")
        payload = path.read_bytes()
        path.write_bytes(payload + b" " * (_MAX_RECORD_BYTES - len(payload)) + b"\xff")
        with self.assertRaises(StateError):
            self.store.load("s")

    def test_concurrent_creators_are_exclusive(self):
        def create():
            try:
                self.store.create("same", self.cwd, None)
                return "created"
            except StateError:
                return "rejected"

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: create(), range(8)))
        self.assertEqual(results.count("created"), 1)
        self.assertEqual(results.count("rejected"), 7)

    def test_canonical_cwd_and_repository_binding(self):
        link = self.tmp_path / "link"
        link.symlink_to(self.cwd, target_is_directory=True)
        state = self.store.create("s", link, self.repo)
        self.assertEqual(state.cwd, self.cwd.resolve())
        self.assertEqual(state.repo.root, self.cwd.resolve())
        outside = self.tmp_path / "outside"
        outside.mkdir()
        with self.assertRaises(ValueError):
            self.store.create("bad", outside, self.repo)

    def test_delete(self):
        self.store.create("s", self.cwd, None)
        self.store.delete("s")
        self.assertIsNone(self.store.load("s"))
        self.store.delete("s")


if __name__ == "__main__":
    unittest.main()
