import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "lib"))

from codex_forge import cli as cli_module
from codex_forge.state import StateError, StateStore, transition


PLUGIN = Path(__file__).parents[1]
CLI = PLUGIN / "bin" / "codex-forge"

BRIEF = {
    "version": 1, "goal": "Ship the feature", "scope": ["src"],
    "non_goals": ["docs"], "decisions": ["stdlib"], "acceptance": ["tests pass"],
    "patterns": ["existing parser"], "verification": ["python3 -m unittest"],
    "assumptions": ["repo exists"],
    "decision_envelope": {"autonomous": ["formatting"], "escalate": ["security"]},
    "phases": [{"name": "implement", "tier_floor": "senior", "verify": "python3 -m unittest"}],
    "dispatcher": "direct",
}


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.cwd = self.root / "repo"
        self.cwd.mkdir()
        self.data = self.root / "data"
        self.session = "cli-test-session"
        self.env = {**os.environ, "CODEX_FORGE_SESSION_ID": self.session,
                    "CODEX_FORGE_DATA": str(self.data)}
        heartbeat = self.data / ("heartbeat-" + hashlib.sha256(self.session.encode()).hexdigest() + ".json")
        self.data.mkdir(mode=0o700)
        heartbeat.write_text(json.dumps({"plugin_version": "0.1.0", "session_id": self.session,
                                         "cwd": str(self.cwd), "timestamp": time.time()}))

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def encode_payload(payload):
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    def run_cli(self, command, payload=None, *, cwd=None, env=None, raw_arg=None):
        args = [str(CLI), command]
        if payload is not None or raw_arg is not None:
            args.append(self.encode_payload(payload) if raw_arg is None else raw_arg)
        result = subprocess.run(args, text=True, capture_output=True, cwd=cwd or self.cwd,
                                env=env or self.env)
        return result, json.loads(result.stdout)

    def invoke_cli(self, command, payload=None):
        argument = None if payload is None else self.encode_payload(payload)
        with mock.patch.dict(os.environ, self.env, clear=False), \
             mock.patch.object(cli_module, "_current_context", return_value=(self.cwd, None)):
            return cli_module.dispatch(command, argument)

    def test_begin_question_cap_freeze_nonce_and_status(self):
        result, body = self.run_cli("begin")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(body, {"ok": True, "status": "shaping"})
        for attempt in range(1, 6):
            result, body = self.run_cli("question", {"question": f"Question {attempt}"})
            self.assertEqual(result.returncode, 0)
            self.assertEqual(body["attempt"], attempt)
        result, body = self.run_cli("question", {"question": "sixth"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(body["code"], "question_limit")
        result, body = self.run_cli("freeze", BRIEF)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(body["status"], "frozen")
        self.assertEqual(len(body["nonce"]), 64)
        approval = self.data / ("approval-" + hashlib.sha256(self.session.encode()).hexdigest() + ".json")
        approval_body = json.loads(approval.read_text())
        self.assertEqual(approval_body["expires_at"] - approval_body["issued_at"], 1800)
        self.assertFalse(approval_body["used"])
        result, body = self.run_cli("status")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(body["status"], "frozen")
        self.assertIn("brief_digest", body)

    def test_duplicate_begin_stale_heartbeat_and_changed_repository_binding_are_denied(self):
        result, body = self.run_cli("begin")
        self.assertEqual(result.returncode, 0)
        result, body = self.run_cli("begin")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(body["code"], "duplicate_begin")

        other_session = "stale-session"
        heartbeat = self.data / ("heartbeat-" + hashlib.sha256(other_session.encode()).hexdigest() + ".json")
        heartbeat.write_text(json.dumps({"plugin_version": "0.1.0", "session_id": other_session,
                                         "cwd": str(self.cwd), "timestamp": 0}))
        stale_env = {**self.env, "CODEX_FORGE_SESSION_ID": other_session}
        result, body = self.run_cli("begin", env=stale_env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(body["code"], "heartbeat_required")

        subprocess.run(["git", "init", "-q", str(self.cwd)], check=True)
        subprocess.run(["git", "-C", str(self.cwd), "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "--allow-empty", "-qm", "repo"], check=True)
        result, body = self.run_cli("status")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(body["code"], "binding_mismatch")

    def test_complete_rejects_executing_without_terminal_verification(self):
        result, _ = self.run_cli("begin")
        self.assertEqual(result.returncode, 0)
        store = StateStore(self.data, "0.1.0")
        state = store.load(self.session)
        state = transition(transition(transition(state, "freeze"), "approve_direct"), "begin")
        store.replace(state)

        result, body = self.run_cli("complete")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(body["code"], "verification_not_terminal")
        self.assertEqual(store.load(self.session).status, "executing")

    def test_complete_rejects_ralph_running_without_terminal_verification(self):
        session = "ralph-complete-session"
        env = {**self.env, "CODEX_FORGE_SESSION_ID": session}
        heartbeat = self.data / ("heartbeat-" + hashlib.sha256(session.encode()).hexdigest() + ".json")
        heartbeat.write_text(json.dumps({"plugin_version": "0.1.0", "session_id": session,
                                         "cwd": str(self.cwd), "timestamp": time.time()}))
        result, _ = self.run_cli("begin", env=env)
        self.assertEqual(result.returncode, 0)
        store = StateStore(self.data, "0.1.0")
        state = store.load(session)
        state = transition(transition(transition(state, "freeze"), "approve_ralph"), "ralph_start")
        store.replace(state)

        result, body = self.run_cli("complete", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(body["code"], "verification_not_terminal")
        self.assertEqual(store.load(session).status, "ralph_running")

    def test_fail_stores_bounded_reason(self):
        result, _ = self.run_cli("begin")
        self.assertEqual(result.returncode, 0)

        fail_session = "fail-session"
        fail_env = {**self.env, "CODEX_FORGE_SESSION_ID": fail_session}
        fail_heartbeat = self.data / ("heartbeat-" + hashlib.sha256(fail_session.encode()).hexdigest() + ".json")
        fail_heartbeat.write_text(json.dumps({"plugin_version": "0.1.0", "session_id": fail_session,
                                               "cwd": str(self.cwd), "timestamp": time.time()}))
        result, _ = self.run_cli("begin", env=fail_env)
        self.assertEqual(result.returncode, 0)
        reason = "x" * 2048
        result, body = self.run_cli("fail", {"reason": reason}, env=fail_env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(body["status"], "failed")
        meta = self.data / ("meta-" + hashlib.sha256(fail_session.encode()).hexdigest() + ".json")
        self.assertEqual(json.loads(meta.read_text())["failure_reason"], reason)
        result, body = self.run_cli("fail", {"reason": "again"}, env=fail_env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(body["code"], "invalid_transition")

    def test_freeze_rolls_back_each_boundary_and_retry_recovers_exact_records(self):
        self.run_cli("begin")
        original_write = cli_module._write_record
        for fail_call in (1, 2):
            with self.subTest(boundary=f"write-{fail_call}"):
                calls = 0
                def fail_write(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    if calls == fail_call:
                        raise cli_module.CLIError("injected", "injected")
                    return original_write(*args, **kwargs)
                with mock.patch.object(cli_module, "_write_record", side_effect=fail_write):
                    with self.assertRaises(cli_module.CLIError) as failure:
                        self.invoke_cli("freeze", BRIEF)
                self.assertIn(failure.exception.code, {"freeze_failed", "freeze_recovery_required"})
                self.assertEqual(StateStore(self.data, "0.1.0").load(self.session).status, "shaping")
                self.assertFalse((self.data / ("brief-" + hashlib.sha256(self.session.encode()).hexdigest() + ".json")).exists())
                self.assertFalse((self.data / ("approval-" + hashlib.sha256(self.session.encode()).hexdigest() + ".json")).exists())
        with mock.patch.object(cli_module, "transition", side_effect=ValueError("injected transition")):
            with self.assertRaises(cli_module.CLIError) as failure:
                self.invoke_cli("freeze", BRIEF)
        self.assertEqual(failure.exception.code, "freeze_failed")
        self.assertEqual(StateStore(self.data, "0.1.0").load(self.session).status, "shaping")

        with mock.patch.object(cli_module, "transition", side_effect=ValueError("injected transition")), \
             mock.patch.object(cli_module, "_delete_record", side_effect=cli_module.CLIError("injected", "injected")):
            with self.assertRaises(cli_module.CLIError) as failure:
                self.invoke_cli("freeze", BRIEF)
        self.assertEqual(failure.exception.code, "freeze_recovery_required")
        result, body = self.run_cli("freeze", BRIEF)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(body["status"], "frozen")

    def test_freeze_reload_distinguishes_pre_and_post_publication_failures(self):
        self.run_cli("begin")
        original_replace = StateStore.replace
        with mock.patch.object(StateStore, "replace", side_effect=StateError("before publication")):
            with self.assertRaises(cli_module.CLIError) as failure:
                self.invoke_cli("freeze", BRIEF)
        self.assertEqual(failure.exception.code, "freeze_failed")
        self.assertEqual(StateStore(self.data, "0.1.0").load(self.session).status, "shaping")
        digest_name = hashlib.sha256(self.session.encode()).hexdigest()
        self.assertFalse((self.data / f"brief-{digest_name}.json").exists())
        self.assertFalse((self.data / f"approval-{digest_name}.json").exists())

        def publish_then_raise(store, state):
            original_replace(store, state)
            raise StateError("directory fsync uncertain")

        with mock.patch.object(StateStore, "replace", publish_then_raise):
            result = self.invoke_cli("freeze", BRIEF)
        self.assertEqual(result["status"], "frozen")
        nonce = result["nonce"]
        retry = self.invoke_cli("freeze", BRIEF)
        self.assertEqual(retry["nonce"], nonce)
        self.assertEqual(self.invoke_cli("status")["brief_digest"], result["brief_digest"])

    def test_rejects_identity_arguments_missing_env_bad_json_and_cwd(self):
        result = subprocess.run([str(CLI), "begin", "--session-id", "model"], cwd=self.cwd,
                                env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        result, body = self.run_cli("begin", env={**self.env, "CODEX_FORGE_SESSION_ID": ""})
        self.assertEqual(body["code"], "missing_injected_environment")
        result, body = self.run_cli("begin", payload=None, cwd=self.cwd)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(body["status"], "shaping")
        # A different directory cannot use the hook-bound session.
        other = self.root / "other"
        other.mkdir()
        result, body = self.run_cli("status", cwd=other)
        self.assertNotEqual(result.returncode, 0)

    def test_freeze_rejects_malformed_json(self):
        self.run_cli("begin")
        result = subprocess.run([str(CLI), "freeze", "e2JhZF"], text=True, capture_output=True,
                                cwd=self.cwd, env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["code"], "invalid_json")

    def test_structured_transport_rejects_padding_alphabet_oversize_utf8_and_trailing_json(self):
        self.run_cli("begin")
        valid = self.encode_payload({"question": "one"})
        cases = (
            (valid + "=", "payload_padding"),
            (valid[:-1] + "+", "payload_alphabet"),
            ("A" * (cli_module.STRUCTURED_ARG_MAX_CHARS + 1), "payload_oversized"),
            ("_w", "invalid_utf8"),
            (self.encode_payload({"question": "one"}) + self.encode_payload({"question": "two"}), "trailing_json"),
        )
        for argument, code in cases:
            with self.subTest(code=code):
                result, body = self.run_cli("question", raw_arg=argument)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(body["code"], code)

    def test_structured_transport_requires_exact_argument_counts_and_no_stdin(self):
        self.run_cli("begin")
        valid = self.encode_payload({"question": "one"})
        for command, args in (("question", []), ("question", [valid, valid]),
                              ("begin", [valid]), ("status", [valid]), ("complete", [valid]),
                              ("fail", []), ("freeze", [valid, valid])):
            with self.subTest(command=command, args=args):
                result = subprocess.run([str(CLI), command, *args], cwd=self.cwd,
                                        env=self.env, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotEqual(json.loads(result.stdout).get("ok"), True)


if __name__ == "__main__":
    unittest.main()
