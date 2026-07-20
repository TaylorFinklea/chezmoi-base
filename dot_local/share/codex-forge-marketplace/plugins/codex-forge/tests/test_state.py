import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "lib"))

from codex_forge.state import ForgeState, RepoIdentity, StateError, StateStore, transition


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "state"
        self.store = StateStore(self.root, "0.1.0")
        self.cwd = Path(self.tmp.name) / "repo"
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

    def test_rejects_disallowed_transitions(self):
        for status, event in (("shaping", "approve_direct"), ("frozen", "begin"), ("completed", "cancel"), ("cancelled", "fail"), ("ralph_running", "approve_direct")):
            source = ForgeState("x", self.cwd.resolve(), None, status, 1, "0.1.0")
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

    def test_canonical_cwd_and_repository_binding(self):
        link = Path(self.tmp.name) / "link"
        link.symlink_to(self.cwd, target_is_directory=True)
        state = self.store.create("s", link, self.repo)
        self.assertEqual(state.cwd, self.cwd.resolve())
        self.assertEqual(state.repo.root, self.cwd.resolve())
        outside = Path(self.tmp.name) / "outside"
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
