import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


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

    def run_cli(self, command, payload=None, *, cwd=None, env=None):
        result = subprocess.run([str(CLI), command], input=None if payload is None else json.dumps(payload),
                                text=True, capture_output=True, cwd=cwd or self.cwd,
                                env=env or self.env)
        return result, json.loads(result.stdout)

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
        result = subprocess.run([str(CLI), "freeze"], input="{bad", text=True, capture_output=True,
                                cwd=self.cwd, env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["code"], "invalid_json")


if __name__ == "__main__":
    unittest.main()
