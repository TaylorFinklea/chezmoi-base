import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "lib"))

from codex_forge import hooks as hooks_module
from codex_forge.hooks import FORGE_SCOUT_INSTRUCTIONS, PLUGIN_VERSION, handle_hook
from codex_forge.state import ForgeState, StateStore, transition


class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.data = self.root / "data"
        self.cwd = self.root / "repo"
        self.cwd.mkdir()
        self.home = self.root / "home"
        self.profile = self.home / ".codex" / "agents" / "forge-scout.toml"
        self.profile.parent.mkdir(parents=True)
        self.plugin_root = Path(__file__).parents[1].resolve()
        self.profile.write_text(
            'name = "forge-scout"\n'
            'description = "Fast, read-only codebase and configuration reconnaissance."\n'
            'model = "gpt-5.6-luna"\n'
            'model_reasoning_effort = "medium"\n'
            'sandbox_mode = "read-only"\n'
            'developer_instructions = """\n'
            + FORGE_SCOUT_INSTRUCTIONS
            + '"""\n'
        )
        self.session = "hook-session"
        self.store = StateStore(self.data, PLUGIN_VERSION)
        self.env = {"data_root": self.data, "now": 1000.0, "HOME": str(self.home),
                    "PLUGIN_ROOT": str(self.plugin_root), "store": self.store}

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

    def test_session_start_canonicalizes_default_temporary_root(self):
        real_temp = self.root / "real-temp"
        real_temp.mkdir()
        temporary_alias = self.root / "temporary-alias"
        temporary_alias.symlink_to(real_temp, target_is_directory=True)
        environment = {key: value for key, value in self.env.items()
                       if key not in {"data_root", "store"}}
        with mock.patch.object(hooks_module.tempfile, "gettempdir", return_value=str(temporary_alias)):
            result = handle_hook(self.event("SessionStart", source="startup"), environment)
        self.assertEqual(result.output, {"hookSpecificOutput": {
            "hookEventName": "SessionStart", "additionalContext": "Codex Forge: shaping session ready."
        }})
        self.assertTrue((real_temp / "codex-forge").is_dir())

    def test_pre_tool_use_exact_denial_and_helper_injection(self):
        self.store.create(self.session, self.cwd, None)
        denied = handle_hook(self.event("PreToolUse", tool_name="Write", tool_input={"file_path": "x"}), self.env)
        self.assertEqual(denied.output, {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "Forge shaping blocks writer tools until nonce approval."
        }})
        helper = str(self.plugin_root / "bin" / "codex-forge")
        payload = "eyJxdWVzdGlvbiI6Im9uZSJ9"
        helper_commands = {
            "begin": f"{helper} begin", "question": f"{helper} question {payload}",
            "freeze": f"{helper} freeze {payload}", "status": f"{helper} status",
            "complete": f"{helper} complete", "fail": f"{helper} fail {payload}",
            "ralph-preflight": f"{helper} ralph-preflight",
            "ralph-launch": f"{helper} ralph-launch",
            "ralph-status": f"{helper} ralph-status",
            "ralph-cancel": f"{helper} ralph-cancel",
        }
        for subcommand, command in helper_commands.items():
            with self.subTest(subcommand=subcommand):
                allowed = handle_hook(self.event("PreToolUse", tool_name="Bash",
                                                  tool_input={"command": command}), self.env)
                updated = allowed.output["hookSpecificOutput"]["updatedInput"]
                self.assertEqual(updated["env"], {"CODEX_FORGE_DATA": str(self.data), "CODEX_FORGE_SESSION_ID": self.session})
        self.store.replace(transition(self.store.load(self.session), "freeze"))
        self.store.replace(transition(self.store.load(self.session), "approve_direct"))
        for subcommand, command in (("complete", f"{helper} complete"), ("fail", f"{helper} fail {payload}")):
            with self.subTest(approved_subcommand=subcommand):
                allowed = handle_hook(self.event("PreToolUse", tool_name="Bash",
                                                  tool_input={"command": command}), self.env)
                updated = allowed.output["hookSpecificOutput"]["updatedInput"]
                self.assertEqual(updated["env"], {"CODEX_FORGE_DATA": str(self.data), "CODEX_FORGE_SESSION_ID": self.session})
        untouched = handle_hook(self.event("PreToolUse", tool_name="Bash",
                                           tool_input={"command": "git status"}), self.env)
        self.assertEqual(untouched.output, {})
        for command in ("codex-forge status", "forge_hook.py status", "hooks/forge_hook.py status",
                        str(self.plugin_root / "hooks" / "forge_hook.py") + " status",
                        "/tmp/forge_hook.py status", f"python3 {helper} status", f"{helper} status extra",
                        f"{helper} question abc=", f"{helper} question abc+", f"{helper} question {'a' * 65537}",
                        f"{helper} question eyJxdWVzdGlvbiI6Im9uZSJ9|cat",
                        f"{helper} question eyJxdWVzdGlvbiI6Im9uZSJ9;echo bad",
                        f"{helper} question $(echo bad)", f"{helper} question eyJxdWVzdGlvbiI6Im9uZSJ9 > /tmp/x",
                        f"{helper} --status", f"{helper} question --session-id model", "git status forge_hook.py",
                        "ls codex-forge", "python forge_hook.py status", "codex-forge", "forge_hook.py", helper):
            with self.subTest(command=command):
                result = handle_hook(self.event("PreToolUse", tool_name="Bash",
                                                tool_input={"command": command}), self.env)
                self.assertNotIn("updatedInput", result.output.get("hookSpecificOutput", {}))

    def test_bash_environment_bypass_is_denied_before_helper_injection(self):
        self.store.create(self.session, self.cwd, None)
        helper = str(self.plugin_root / "bin" / "codex-forge")
        cases = (
            ("git status", {"PATH": "/tmp"}),
            ("git status", {"PYTHONPATH": "/tmp"}),
            ("git status", ["BASH_ENV=/tmp/evil"]),
            (f"{helper} status", {}),
            (f"{helper} status", {"PATH": "/tmp"}),
            (f"{helper} status", {"CODEX_FORGE_DATA": "/tmp"}),
            (f"{helper} status", {"timeout": 1}),
        )
        for command, environment in cases:
            with self.subTest(command=command, environment=environment):
                result = handle_hook(self.event("PreToolUse", tool_name="Bash",
                                                tool_input={"command": command, "env": environment}), self.env)
                output = result.output["hookSpecificOutput"]
                self.assertEqual(output["permissionDecision"], "deny")
                self.assertNotIn("updatedInput", output)

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
                                        "issued_at": 1000.0, "expires_at": 2800.0, "used": False}))
        return nonce

    def test_invalid_prompt_is_exact_block_and_valid_nonce_is_session_bound(self):
        self._freeze_with_nonce()
        invalid = handle_hook(self.event("UserPromptSubmit", prompt="approve abc123"), self.env)
        self.assertEqual(invalid.output, {"decision": "block", "reason":
                         "Forge requires an exact approval command: approve <nonce> direct|ralph, revise <nonce>, or cancel <nonce>."})
        approved = handle_hook(self.event("UserPromptSubmit", prompt="approve abc123 direct"), self.env)
        self.assertEqual(approved.output, {})
        self.assertEqual(self.store.load(self.session).status, "approved_direct")

    def test_approval_consumes_nonce_before_state_persistence_failure(self):
        self._freeze_with_nonce()
        original_replace = self.store.replace
        def fail_replace(state):
            raise OSError("injected persistence failure")
        self.store.replace = fail_replace
        result = handle_hook(self.event("UserPromptSubmit", prompt="approve abc123 direct"), self.env)
        self.assertEqual(result.exit_code, 2)
        self.assertTrue(result.blocked)
        self.assertEqual(self.store.load(self.session).status, "frozen")
        approval = self.data / ("approval-" + __import__("hashlib").sha256(self.session.encode()).hexdigest() + ".json")
        self.assertFalse(json.loads(approval.read_text())["used"])
        self.store.replace = original_replace
        retry = handle_hook(self.event("UserPromptSubmit", prompt="approve abc123 direct"), self.env)
        self.assertEqual(retry.output, {})
        self.assertEqual(self.store.load(self.session).status, "approved_direct")

    def test_nonce_restore_failure_is_explicit_and_fail_closed(self):
        self._freeze_with_nonce()
        original_replace = self.store.replace
        original_write = hooks_module._write_json
        writes = 0
        def fail_transition(_state):
            raise OSError("injected")
        def fail_restore(*args, **kwargs):
            nonlocal writes
            writes += 1
            if writes == 2:
                raise hooks_module.HookError("injected restore")
            return original_write(*args, **kwargs)
        self.store.replace = fail_transition
        with mock.patch.object(hooks_module, "_write_json", side_effect=fail_restore):
            result = handle_hook(self.event("UserPromptSubmit", prompt="approve abc123 direct"), self.env)
        self.store.replace = original_replace
        self.assertTrue(result.blocked)
        self.assertIn("nonce recovery is required", result.output["reason"])
        self.assertTrue(json.loads((self.data / ("approval-" + __import__("hashlib").sha256(self.session.encode()).hexdigest() + ".json")).read_text())["used"])

    def test_user_prompt_rejects_stale_or_replayed_nonce(self):
        self._freeze_with_nonce()
        self.env["now"] = 2900.0
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

    def test_user_prompt_rejects_nonfinite_and_boolean_expiry(self):
        for expiry in (float("nan"), float("inf"), float("-inf"), True, False):
            with self.subTest(expiry=expiry):
                self._freeze_with_nonce()
                approval = self.data / ("approval-" + __import__("hashlib").sha256(self.session.encode()).hexdigest() + ".json")
                payload = json.loads(approval.read_text())
                payload["expires_at"] = expiry
                approval.write_text(json.dumps(payload))
                result = handle_hook(self.event("UserPromptSubmit", prompt="approve abc123 direct"), self.env)
                self.assertEqual(result.output["decision"], "block")

    def test_approval_requires_exact_thirty_minute_schema_and_reasonable_issue_time(self):
        for mutate in (
            lambda p: p.update({"issued_at": 1001.0}),
            lambda p: p.update({"expires_at": 2801.0}),
            lambda p: p.update({"issued_at": 1000.0, "expires_at": 2801.0}),
            lambda p: p.update({"issued_at": True}),
            lambda p: p.update({"used": 0}),
            lambda p: p.update({"unexpected": 1}),
            lambda p: p.update({"issued_at": 1601.0, "expires_at": 3401.0}),
        ):
            with self.subTest(mutate=mutate):
                self._freeze_with_nonce()
                approval = self.data / ("approval-" + __import__("hashlib").sha256(self.session.encode()).hexdigest() + ".json")
                payload = json.loads(approval.read_text())
                mutate(payload)
                approval.write_text(json.dumps(payload))
                result = handle_hook(self.event("UserPromptSubmit", prompt="approve abc123 direct"), self.env)
                self.assertTrue(result.blocked)
                self.assertEqual(result.output["decision"], "block")

    def test_malformed_heartbeat_record_fails_closed_instead_of_overwriting(self):
        self.data.mkdir(mode=0o700)
        heartbeat = self.data / ("heartbeat-" + __import__("hashlib").sha256(self.session.encode()).hexdigest() + ".json")
        heartbeat.write_text(json.dumps({"plugin_version": PLUGIN_VERSION, "session_id": self.session,
                                         "cwd": str(self.cwd), "timestamp": 1000.0, "extra": True}))
        result = handle_hook(self.event("SessionStart", source="startup", reason="startup"), self.env)
        self.assertEqual(result.exit_code, 2)
        self.assertTrue(result.blocked)

    def test_stop_record_requires_bounded_nonnegative_integer(self):
        state = self.store.create(self.session, self.cwd, None)
        self.store.replace(transition(transition(state, "freeze"), "approve_direct"))
        self.store.replace(transition(self.store.load(self.session), "begin"))
        stop = self.data / ("stop-" + __import__("hashlib").sha256(self.session.encode()).hexdigest() + ".json")
        for count in (-1, 2, True, False, "0"):
            with self.subTest(count=count):
                stop.write_text(json.dumps({"count": count}))
                result = handle_hook(self.event("Stop", stop_hook_active=False, last_assistant_message="incomplete"), self.env)
                self.assertEqual(result.exit_code, 2)
                self.assertTrue(result.blocked)

    def test_profile_is_verified_before_heartbeat_and_agent_start(self):
        self.profile.write_text(self.profile.read_text().replace('sandbox_mode = "read-only"', 'sandbox_mode = "workspace-write"'))
        result = handle_hook(self.event("SessionStart", source="startup", reason="startup"), self.env)
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(list(self.data.glob("*")) if self.data.exists() else [], [])
        self.store.create(self.session, self.cwd, None)
        result = handle_hook(self.event("PreToolUse", tool_name="Agent",
                                        tool_input={"agent_type": "forge-scout", "prompt": "inspect"}), self.env)
        self.assertEqual(result.exit_code, 0)
        self.assertTrue(result.blocked)

    def test_profile_must_be_regular_non_symlink(self):
        target = self.root / "profile-target.toml"
        target.write_text(self.profile.read_text())
        self.profile.unlink()
        self.profile.symlink_to(target)
        result = handle_hook(self.event("SessionStart", source="startup", reason="startup"), self.env)
        self.assertEqual(result.exit_code, 2)

    def test_malformed_tool_name_returns_fail_closed_output(self):
        self.store.create(self.session, self.cwd, None)
        for tool_name in (None, [], {}, 7):
            with self.subTest(tool_name=tool_name):
                result = handle_hook(self.event("PreToolUse", tool_name=tool_name, tool_input={}), self.env)
                self.assertEqual(result.output, {"hookSpecificOutput": {
                    "hookEventName": "PreToolUse", "permissionDecision": "deny",
                    "permissionDecisionReason": "Forge shaping denies unknown tools."
                }})
                self.assertTrue(result.blocked)

    def test_post_tool_records_exact_verification_and_stop_fails_on_second_attempt(self):
        state = self.store.create(self.session, self.cwd, None)
        state = transition(transition(state, "freeze"), "approve_direct")
        state = transition(state, "begin")
        state = ForgeState(state.session_id, state.cwd, state.repo, state.status,
                           state.schema_version, state.plugin_version, "digest",
                           ("python3 -m unittest",), ())
        self.store.replace(state)
        unrelated = handle_hook(self.event("PostToolUse", tool_name="Bash",
                                            tool_input={"command": "git status"},
                                            tool_response={"output": "bad"}), self.env)
        self.assertEqual(unrelated.output, {})
        for tool_input in (None, [], "python3 -m unittest", {}, {"command": None}):
            with self.subTest(tool_input=tool_input):
                malformed = handle_hook(self.event("PostToolUse", tool_name="Bash",
                                                    tool_input=tool_input,
                                                    tool_response={"exit_code": 0}), self.env)
                self.assertTrue(malformed.blocked)
                self.assertEqual(malformed.exit_code, 2)
                self.assertIn("tool_input is malformed", malformed.output["reason"])
        for tool_response in (None, [], {"output": "missing exit"},
                              {"exit_code": True}, {"exit_code": "0"},
                              {"exit_code": None}):
            with self.subTest(tool_response=tool_response):
                malformed = handle_hook(self.event("PostToolUse", tool_name="Bash",
                                                    tool_input={"command": "python3 -m unittest"},
                                                    tool_response=tool_response), self.env)
                self.assertTrue(malformed.blocked)
                self.assertEqual(malformed.exit_code, 2)
                self.assertIn("tool_response is malformed", malformed.output["reason"])
        passed = handle_hook(self.event("PostToolUse", tool_name="Bash",
                                        tool_input={"command": "python3 -m unittest"},
                                        tool_response={"exit_code": 0, "output": "ok"}), self.env)
        self.assertEqual(passed.output, {})
        self.assertEqual(len(self.store.load(self.session).verification_records), 1)
        self.store.replace(ForgeState(self.session, self.cwd, None, "executing", 1, "0.1.0",
                                      "digest", ("python3 -m unittest", "git diff --check"),
                                      self.store.load(self.session).verification_records))
        first = handle_hook(self.event("Stop", stop_hook_active=False, last_assistant_message="incomplete"), self.env)
        self.assertEqual(first.output["decision"], "block")
        second = handle_hook(self.event("Stop", stop_hook_active=True, last_assistant_message="incomplete"), self.env)
        self.assertEqual(second.output, {})
        self.assertEqual(second.exit_code, 0)
        self.assertEqual(self.store.load(self.session).status, "failed")
        third = handle_hook(self.event("Stop", stop_hook_active=True, last_assistant_message="incomplete"), self.env)
        self.assertEqual(third.output, {})
        self.assertEqual(self.store.load(self.session).status, "failed")

    def test_stop_recovers_ralph_or_leaves_owned_run_actionable_once(self):
        state = self.store.create(self.session, self.cwd, None)
        state = transition(transition(transition(state, "freeze"), "approve_ralph"), "ralph_start")
        self.store.replace(state)
        name = "ralph-" + __import__("hashlib").sha256(self.session.encode()).hexdigest() + ".json"
        self.data.mkdir(mode=0o700, exist_ok=True)
        (self.data / name).write_text(json.dumps({"pid": 123, "pgid": 123, "start": "start", "marker_digest": "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE=", "launch_id": "a" * 64}))
        with mock.patch.object(hooks_module, "read_ralph_receipt", return_value=None), \
             mock.patch.object(hooks_module, "recover_ralph_status", return_value={"owned": True, "running": True}):
            first = handle_hook(self.event("Stop"), self.env)
            second = handle_hook(self.event("Stop"), self.env)
        self.assertTrue(first.blocked)
        self.assertIn("ralph-status", first.output["reason"])
        self.assertEqual(second.output, {})
        self.assertEqual(self.store.load(self.session).status, "ralph_running")
        with mock.patch.object(hooks_module, "read_ralph_receipt", return_value={"status": "completed", "exit_code": 0}):
            recovered = handle_hook(self.event("Stop"), self.env)
        self.assertEqual(recovered.output, {})
        self.assertEqual(self.store.load(self.session).status, "completed")

    def test_direct_writers_are_bound_to_cwd_and_repository(self):
        state = self.store.create(self.session, self.cwd, None)
        state = transition(transition(state, "freeze"), "approve_direct")
        self.store.replace(state)
        allowed = handle_hook(self.event("PreToolUse", tool_name="Write",
                                         tool_input={"file_path": "x"}), self.env)
        self.assertEqual(allowed.output, {})
        other = self.root / "other"
        other.mkdir()
        denied = handle_hook(self.event("PreToolUse", cwd=str(other), tool_name="Write",
                                        tool_input={"file_path": "x"}), self.env)
        self.assertTrue(denied.blocked)

    def test_entrypoint_reads_one_object_and_emits_json(self):
        entry = Path(__file__).parents[1] / "hooks" / "forge_hook.py"
        event = self.event("PostToolUse", tool_name="Bash", tool_input={}, tool_response={})
        result = subprocess.run([sys.executable, str(entry)], input=json.dumps(event), text=True,
                                capture_output=True, env={**os.environ, "CODEX_FORGE_STATE_DIR": str(self.data)})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {})
        leading = subprocess.run([sys.executable, str(entry)], input=" \n\t" + json.dumps(event) + " \n", text=True,
                                 capture_output=True, env={**os.environ, "CODEX_FORGE_STATE_DIR": str(self.data)})
        self.assertEqual(leading.returncode, 0)
        bad = subprocess.run([sys.executable, str(entry)], input="{} {}", text=True, capture_output=True)
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(bad.stdout, "")
        self.assertEqual(bad.stderr, "stdin must contain exactly one JSON object\n")

    def test_entrypoint_returns_success_for_json_tool_denial(self):
        self.store.create(self.session, self.cwd, None)
        entry = Path(__file__).parents[1] / "hooks" / "forge_hook.py"
        event = self.event("PreToolUse", tool_name="Write", tool_input={"file_path": "x"})
        result = subprocess.run([sys.executable, str(entry)], input=json.dumps(event), text=True,
                                capture_output=True, env={**os.environ, "CODEX_FORGE_STATE_DIR": str(self.data)})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "Forge shaping blocks writer tools until nonce approval."
        }})

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
