import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "lib"))

from codex_forge.hooks import PLUGIN_VERSION, handle_hook
from codex_forge.state import StateStore, transition


class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.data = self.root / "data"
        self.cwd = self.root / "repo"
        self.cwd.mkdir()
        self.session = "hook-session"
        self.env = {"data_root": self.data, "now": 1000.0}
        self.store = StateStore(self.data, PLUGIN_VERSION)

    def tearDown(self):
        self.tmp.cleanup()

    def event(self, name, **fields):
        return {"session_id": self.session, "cwd": str(self.cwd), "hook_event_name": name,
                "model": "gpt-5-codex", **fields}

    def test_session_start_heartbeat_and_exact_context_shape(self):
        result = handle_hook(self.event("SessionStart", source="startup", reason="startup"), self.env)
        self.assertEqual(result.output, {"hookSpecificOutput": {
            "hookEventName": "SessionStart", "additionalContext": "Codex Forge: shaping session ready."
        }})
        records = list(self.data.iterdir())
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0].read_text()), {
            "plugin_version": "0.1.0", "session_id": self.session,
            "cwd": str(self.cwd), "timestamp": 1000.0,
        })
        self.assertEqual(stat.S_IMODE(records[0].stat().st_mode), 0o600)

    def test_pre_tool_use_exact_denial_and_helper_injection(self):
        self.store.create(self.session, self.cwd, None)
        denied = handle_hook(self.event("PreToolUse", tool_name="Write", tool_input={"file_path": "x"}), self.env)
        self.assertEqual(denied.output, {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "Forge shaping blocks writer tools until nonce approval."
        }})
        allowed = handle_hook(self.event("PreToolUse", tool_name="Bash",
                                          tool_input={"command": "codex-forge status"}), self.env)
        updated = allowed.output["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["env"], {"CODEX_FORGE_DATA": str(self.data), "CODEX_FORGE_SESSION_ID": self.session})
        untouched = handle_hook(self.event("PreToolUse", tool_name="Bash",
                                           tool_input={"command": "git status"}), self.env)
        self.assertEqual(untouched.output, {})

    def _freeze_with_nonce(self, nonce="abc123"):
        existing = self.store.load(self.session)
        if existing is None:
            state = self.store.create(self.session, self.cwd, None)
        else:
            state = existing
        if state.status == "shaping":
            state = transition(state, "freeze")
        self.store.replace(state)
        approval = self.data / ("approval-" + __import__("hashlib").sha256(self.session.encode()).hexdigest() + ".json")
        self.data.mkdir(mode=0o700, exist_ok=True)
        approval.write_text(json.dumps({"nonce": nonce, "session_id": self.session,
                                        "cwd": str(self.cwd), "repo": None,
                                        "expires_at": 1300.0, "used": False}))
        return nonce

    def test_invalid_prompt_is_exact_block_and_valid_nonce_is_session_bound(self):
        self._freeze_with_nonce()
        invalid = handle_hook(self.event("UserPromptSubmit", prompt="approve abc123"), self.env)
        self.assertEqual(invalid.output, {"decision": "block", "reason":
                         "Forge requires an exact approval command: approve <nonce> direct|ralph, revise <nonce>, or cancel <nonce>."})
        approved = handle_hook(self.event("UserPromptSubmit", prompt="approve abc123 direct"), self.env)
        self.assertEqual(approved.output, {})
        self.assertEqual(self.store.load(self.session).status, "approved_direct")

    def test_user_prompt_rejects_stale_or_replayed_nonce(self):
        self._freeze_with_nonce()
        self.env["now"] = 1400.0
        stale = handle_hook(self.event("UserPromptSubmit", prompt="approve abc123 direct"), self.env)
        self.assertEqual(stale.output["decision"], "block")
        self.env["now"] = 1000.0
        self._freeze_with_nonce()
        self.assertEqual(handle_hook(self.event("UserPromptSubmit", prompt="approve abc123 direct"), self.env).output, {})
        state = self.store.load(self.session)
        self.assertEqual(state.status, "approved_direct")
        from codex_forge.state import ForgeState
        self.store.replace(ForgeState(state.session_id, state.cwd, state.repo, "frozen", state.schema_version, state.plugin_version))
        replay = handle_hook(self.event("UserPromptSubmit", prompt="approve abc123 direct"), self.env)
        self.assertEqual(replay.output["decision"], "block")

    def test_post_tool_is_noop_and_stop_continuation_is_bounded(self):
        state = self.store.create(self.session, self.cwd, None)
        self.store.replace(transition(transition(state, "freeze"), "approve_direct"))
        self.store.replace(transition(self.store.load(self.session), "begin"))
        self.assertEqual(handle_hook(self.event("PostToolUse", tool_name="Bash", tool_input={}, tool_response={}), self.env).output, {})
        first = handle_hook(self.event("Stop", stop_hook_active=False, last_assistant_message="incomplete"), self.env)
        self.assertEqual(first.output["decision"], "block")
        second = handle_hook(self.event("Stop", stop_hook_active=True, last_assistant_message="incomplete"), self.env)
        self.assertEqual(second.output, {})

    def test_entrypoint_reads_one_object_and_emits_json(self):
        entry = Path(__file__).parents[1] / "hooks" / "forge_hook.py"
        event = self.event("PostToolUse", tool_name="Bash", tool_input={}, tool_response={})
        result = subprocess.run([sys.executable, str(entry)], input=json.dumps(event), text=True,
                                capture_output=True, env={**os.environ, "CODEX_FORGE_STATE_DIR": str(self.data)})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {})
        bad = subprocess.run([sys.executable, str(entry)], input="{} {}", text=True, capture_output=True)
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(json.loads(bad.stdout)["decision"], "block")

    def test_hook_records_reject_hostile_roots_and_leaf_symlinks(self):
        outside = self.root / "outside"
        outside.mkdir()
        hostile = self.root / "hostile"
        hostile.symlink_to(outside, target_is_directory=True)
        result = handle_hook(self.event("SessionStart", source="startup", reason="startup"), {**self.env, "data_root": hostile})
        self.assertEqual(result.exit_code, 2)
        ancestor = self.root / "ancestor"
        ancestor.symlink_to(outside, target_is_directory=True)
        result = handle_hook(self.event("SessionStart", source="startup", reason="startup"), {**self.env, "data_root": ancestor / "nested"})
        self.assertEqual(result.exit_code, 2)
        self._freeze_with_nonce()
        approval = self.data / ("approval-" + __import__("hashlib").sha256(self.session.encode()).hexdigest() + ".json")
        target = self.root / "approval-target"
        target.write_text(approval.read_text())
        approval.unlink()
        approval.symlink_to(target)
        result = handle_hook(self.event("UserPromptSubmit", prompt="approve abc123 direct"), self.env)
        self.assertEqual(result.exit_code, 2)
        self.assertTrue(result.blocked)

    def test_hook_records_use_unique_private_temps_and_private_modes(self):
        self.data.mkdir(mode=0o700)
        heartbeat_name = "heartbeat-" + __import__("hashlib").sha256(self.session.encode()).hexdigest() + ".json"
        stale = self.data / ("." + heartbeat_name + ".stale.tmp")
        stale.write_text("stale")
        handle_hook(self.event("SessionStart", source="startup", reason="startup"), self.env)
        heartbeat = self.data / heartbeat_name
        self.assertEqual(stat.S_IMODE(self.data.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(heartbeat.stat().st_mode), 0o600)
        self.assertTrue(stale.exists())
        self._freeze_with_nonce()
        approval = self.data / ("approval-" + __import__("hashlib").sha256(self.session.encode()).hexdigest() + ".json")
        result = handle_hook(self.event("UserPromptSubmit", prompt="approve abc123 direct"), self.env)
        self.assertEqual(result.output, {})
        self.assertEqual(stat.S_IMODE(approval.stat().st_mode), 0o600)

    def test_malformed_oversized_and_invalid_utf8_hook_records_block_fail_closed(self):
        self._freeze_with_nonce()
        approval = self.data / ("approval-" + __import__("hashlib").sha256(self.session.encode()).hexdigest() + ".json")
        for raw in (b"{", b"x" * (1024 * 1024 + 1), b"\xff"):
            with self.subTest(size=len(raw)):
                approval.write_bytes(raw)
                result = handle_hook(self.event("UserPromptSubmit", prompt="approve abc123 direct"), self.env)
                self.assertEqual(result.exit_code, 2)
                self.assertTrue(result.blocked)

    def test_malformed_stop_record_does_not_reset_continuation_budget(self):
        state = self.store.create(self.session, self.cwd, None)
        self.store.replace(transition(transition(state, "freeze"), "approve_direct"))
        self.store.replace(transition(self.store.load(self.session), "begin"))
        stop = self.data / ("stop-" + __import__("hashlib").sha256(self.session.encode()).hexdigest() + ".json")
        self.data.mkdir(mode=0o700, exist_ok=True)
        stop.write_bytes(b"not-json")
        result = handle_hook(self.event("Stop", stop_hook_active=False, last_assistant_message="incomplete"), self.env)
        self.assertEqual(result.exit_code, 2)
        self.assertTrue(result.blocked)


if __name__ == "__main__":
    unittest.main()
