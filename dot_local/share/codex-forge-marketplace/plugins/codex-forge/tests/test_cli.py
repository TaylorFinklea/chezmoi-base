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
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "lib"))

from codex_forge import cli as cli_module
from codex_forge import ralph as ralph_module
from codex_forge.ralph import FileSnapshot, RalphPreparation
from codex_forge.state import RepoIdentity, StateError, StateStore, transition


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
        self.assertEqual(body["selected_dispatcher"], None)
        self.assertEqual(body["approval"]["state"], "available")
        self.assertLessEqual(body["approval"]["expires_in_seconds"], 1800)
        self.assertEqual(body["verification"], {"passed": 0, "required": 1, "remaining": 1})
        self.assertEqual(body["ralph"], {"owned": False, "running": False, "terminal": "not-started"})

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

    def test_complete_requires_every_exact_verification_record(self):
        result, _ = self.run_cli("begin")
        self.assertEqual(result.returncode, 0)
        store = StateStore(self.data, "0.1.0")
        state = store.load(self.session)
        state = transition(transition(transition(state, "freeze"), "approve_direct"), "begin")
        state = state.__class__(state.session_id, state.cwd, state.repo, state.status,
                                state.schema_version, state.plugin_version, "digest",
                                ("python3 -m unittest",), ())
        store.replace(state)
        result, body = self.run_cli("complete")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(body["code"], "verification_not_terminal")
        updated = state.__class__(state.session_id, state.cwd, state.repo, state.status,
                                  state.schema_version, state.plugin_version, "digest",
                                  state.verification_commands, ({
                                      "session_id": self.session, "cwd": str(self.cwd), "repo": None,
                                      "brief_digest": "digest", "command": "python3 -m unittest",
                                      "exit_code": 0, "head": "ok", "tail": "ok",
                                      "response_sha256": "a" * 64, "timestamp": time.time(),
                                  },))
        store.replace(updated)
        result, body = self.run_cli("complete")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(body, {"ok": True, "status": "completed"})

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
        self.assertEqual(body["code"], "ralph_failed")
        self.assertEqual(store.load(session).status, "failed")

    def test_ralph_control_commands_are_state_bound_and_persist_owned_identity(self):
        ralph_brief = {**BRIEF, "dispatcher": "ralph", "phases": [
            {"name": "implement", "tier_floor": "senior", "verify": "python3 -m unittest"},
            {"name": "document", "tier_floor": "junior", "verify": "python3 -m py_compile"},
        ]}
        self.assertEqual(self.run_cli("begin")[1]["status"], "shaping")
        digest_name = hashlib.sha256(self.session.encode()).hexdigest()
        (self.data / f"brief-{digest_name}.json").write_text(json.dumps({"digest": "ralph-digest", "brief": ralph_brief}))
        store = StateStore(self.data, "0.1.0")
        state = transition(transition(store.load(self.session), "freeze"), "approve_ralph")
        store.replace(state)

        with mock.patch.object(cli_module, "inspect_ralph_eligibility", return_value=SimpleNamespace(eligible=True, reasons=())):
            self.assertEqual(self.invoke_cli("ralph-preflight"), {"ok": True, "eligible": True, "reasons": []})

        preparation = SimpleNamespace(planning_commit="planning-commit")
        marker_digest = "a" * 64
        def launch(prepared, *, data_root, launch_id, on_spawn, on_abort, on_rollback, on_spawn_proven):
            self.assertIs(prepared, preparation)
            on_spawn(SimpleNamespace(identity=SimpleNamespace(pid=123, pgid=123, start="started", marker_digest=base64.urlsafe_b64encode(bytes.fromhex(marker_digest)).decode("ascii")), launch_id=launch_id))
            on_spawn_proven()
            return SimpleNamespace(launch_id=launch_id)

        with mock.patch.object(cli_module, "prepare_ralph_dispatch", return_value=preparation), \
             mock.patch.object(cli_module, "_write_ralph_recovery"), \
             mock.patch.object(cli_module, "launch_ralph_dispatch", side_effect=launch):
            launched = self.invoke_cli("ralph-launch")
        self.assertEqual(launched, {"ok": True, "status": "ralph_running", "planning_commit": "planning-commit"})
        self.assertEqual(store.load(self.session).status, "ralph_running")
        ralph_record = json.loads((self.data / f"ralph-{digest_name}.json").read_text())
        persisted_digest = ralph_record["marker_digest"]
        self.assertEqual(base64.urlsafe_b64decode(persisted_digest).hex(), marker_digest)
        self.assertNotIn(marker_digest, json.dumps(ralph_record))
        self.assertNotIn("private-launch-marker", json.dumps(ralph_record))

        with mock.patch.object(cli_module, "read_ralph_receipt", return_value=None), \
             mock.patch.object(cli_module, "recover_ralph_status", return_value={"owned": True, "running": True, "pid": 123, "pgid": 123}):
            observed = self.invoke_cli("ralph-status")
        self.assertEqual(observed["planning_commit"], "planning-commit")
        self.assertEqual(observed["terminal"], "running")
        self.assertTrue(observed["owned"])
        self.assertNotIn("marker_digest", observed)

        (self.data / f"heartbeat-{digest_name}.json").write_text(json.dumps({
            "plugin_version": "0.1.0", "session_id": self.session, "cwd": str(self.cwd), "timestamp": 0,
        }))
        with mock.patch.object(cli_module, "read_ralph_receipt", return_value=None), \
             mock.patch.object(cli_module, "recover_ralph_status", return_value={"owned": True, "running": True}), \
             mock.patch.object(cli_module, "cancel_owned_ralph", return_value={"cancelled": True, "owned": True, "running": False}):
            cancelled = self.invoke_cli("ralph-cancel")
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(store.load(self.session).status, "cancelled")
        self.assertTrue((self.data / f"ralph-{digest_name}.json").exists())

    def test_ralph_launch_callback_partial_persistence_restores_exact_state_and_record(self):
        self.assertEqual(self.run_cli("begin")[1]["status"], "shaping")
        store = StateStore(self.data, "0.1.0")
        state = transition(transition(store.load(self.session), "freeze"), "approve_ralph")
        store.replace(state)
        ralph_brief = {**BRIEF, "dispatcher": "ralph", "phases": [
            {"name": "implement", "tier_floor": "senior", "verify": "python3 -m unittest"},
            {"name": "document", "tier_floor": "junior", "verify": "python3 -m py_compile"},
        ]}
        digest_name = hashlib.sha256(self.session.encode()).hexdigest()
        (self.data / f"brief-{digest_name}.json").write_text(json.dumps({"digest": "ralph-digest", "brief": ralph_brief}))
        preparation = SimpleNamespace(planning_commit="planning-commit")
        marker = base64.urlsafe_b64encode(bytes.fromhex("a" * 64)).decode("ascii")
        original_replace = StateStore.replace

        def fail_running_replace(instance, next_state):
            if next_state.status == "ralph_running":
                raise StateError("injected callback persistence failure")
            return original_replace(instance, next_state)

        def launch(_prepared, *, data_root, launch_id, on_spawn, on_abort, on_rollback, on_spawn_proven):
            try:
                on_spawn(SimpleNamespace(identity=SimpleNamespace(
                    pid=123, pgid=123, start="started", marker_digest=marker), launch_id=launch_id))
            except Exception:
                on_abort()
                on_rollback()
                raise
            self.fail("callback should fail before arming")

        with mock.patch.object(cli_module, "prepare_ralph_dispatch", return_value=preparation), \
             mock.patch.object(cli_module, "_write_ralph_recovery"), \
             mock.patch.object(cli_module, "launch_ralph_dispatch", side_effect=launch), \
             mock.patch.object(StateStore, "replace", fail_running_replace):
            with self.assertRaises(cli_module.CLIError) as failure:
                self.invoke_cli("ralph-launch")
        self.assertEqual(failure.exception.code, "state_write_failed")
        self.assertEqual(store.load(self.session), state)
        self.assertFalse((self.data / f"ralph-{digest_name}.json").exists())

    def test_callback_then_launcher_crash_leaves_recoverable_prearm_transaction(self):
        self.assertEqual(self.run_cli("begin")[1]["status"], "shaping")
        store = StateStore(self.data, "0.1.0")
        approved = transition(transition(store.load(self.session), "freeze"), "approve_ralph")
        store.replace(approved)
        ralph_brief = {**BRIEF, "dispatcher": "ralph", "phases": [
            {"name": "implement", "tier_floor": "senior", "verify": "python3 -m unittest"},
            {"name": "document", "tier_floor": "junior", "verify": "python3 -m py_compile"},
        ]}
        digest_name = hashlib.sha256(self.session.encode()).hexdigest()
        (self.data / f"brief-{digest_name}.json").write_text(json.dumps({"digest": "ralph-digest", "brief": ralph_brief}))
        preparation = RalphPreparation(self.cwd, (".docs/ai/current-state.md",),
                                       (FileSnapshot(".docs/ai/current-state.md", False),),
                                       "before", "plan")
        marker = base64.urlsafe_b64encode(bytes.fromhex("a" * 64)).decode("ascii")
        def crash_after_callback(_prepared, *, data_root, launch_id, on_spawn, on_abort, on_rollback, on_spawn_proven):
            on_spawn(SimpleNamespace(identity=SimpleNamespace(
                pid=123, pgid=123, start="started", marker_digest=marker), launch_id=launch_id))
            raise cli_module.RalphLaunchRecoveryError("launcher crashed before arm")
        with mock.patch.object(cli_module, "prepare_ralph_dispatch", return_value=preparation), \
             mock.patch.object(cli_module, "launch_ralph_dispatch", side_effect=crash_after_callback):
            with self.assertRaises(cli_module.CLIError) as failure:
                self.invoke_cli("ralph-launch")
        self.assertEqual(failure.exception.code, "ralph_launch_recovery_required")
        self.assertEqual(store.load(self.session).status, "ralph_running")
        self.assertTrue((self.data / f"ralph-recovery-{digest_name}.json").exists())
        with mock.patch.object(cli_module, "read_ralph_receipt", return_value={"status": "prearm_aborted"}), \
             mock.patch.object(cli_module, "rollback_ralph_preparation") as rollback:
            body = self.invoke_cli("status")
        self.assertEqual(body["status"], "approved_ralph")
        self.assertEqual(body["ralph"]["terminal"], "prearm_aborted")
        rollback.assert_called_once_with(preparation)

    def test_restart_prearm_receipt_restores_durable_transaction_before_git_rollback(self):
        self.assertEqual(self.run_cli("begin")[1]["status"], "shaping")
        store = StateStore(self.data, "0.1.0")
        approved = transition(transition(store.load(self.session), "freeze"), "approve_ralph")
        running = transition(approved, "ralph_start")
        store.replace(running)
        launch_id = "e" * 64
        marker = base64.urlsafe_b64encode(bytes.fromhex("a" * 64)).decode("ascii")
        cli_module._write_record(self.data, "ralph-", self.session, {
            "plugin_version": "0.1.0", "session_id": self.session, "cwd": str(self.cwd),
            "repo_root": None, "git_dir": None, "planning_commit": "plan", "pid": 1,
            "pgid": 1, "start": "start", "marker_digest": marker, "launch_id": launch_id,
        })
        preparation = RalphPreparation(self.cwd, (".docs/ai/current-state.md",),
                                       (FileSnapshot(".docs/ai/current-state.md", False),),
                                       "before", "plan")
        cli_module._write_ralph_recovery(self.data, self.session, approved, None,
                                         preparation, launch_id, self.cwd, None)
        with mock.patch.object(cli_module, "read_ralph_receipt", return_value={"status": "prearm_aborted"}), \
             mock.patch.object(cli_module, "rollback_ralph_preparation") as rollback:
            body = self.invoke_cli("status")
        self.assertEqual(body["status"], "approved_ralph")
        self.assertEqual(body["ralph"]["terminal"], "prearm_aborted")
        self.assertNotIn("preparation", json.dumps(body))
        self.assertEqual(store.load(self.session), approved)
        self.assertFalse((self.data / f"ralph-{hashlib.sha256(self.session.encode()).hexdigest()}.json").exists())
        self.assertFalse((self.data / f"ralph-recovery-{hashlib.sha256(self.session.encode()).hexdigest()}.json").exists())
        rollback.assert_called_once_with(preparation)

    def test_real_runner_dies_after_arm_before_ack_keeps_recovery_transaction(self):
        (self.cwd / ".docs/ai").mkdir(parents=True)
        (self.cwd / ".docs/ai/current-state.md").write_text("## Plan\n\n")
        (self.cwd / ".docs/ai/roadmap.md").write_text("# Roadmap\n")
        subprocess.run(["git", "init", "-q"], cwd=self.cwd, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.cwd, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.cwd, check=True)
        subprocess.run(["git", "add", ".docs/ai"], cwd=self.cwd, check=True)
        subprocess.run(["git", "commit", "-qm", "baseline"], cwd=self.cwd, check=True)
        before_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.cwd, text=True).strip()
        repo = RepoIdentity(self.cwd, before_head, self.cwd / ".git")
        context = mock.patch.object(cli_module, "_current_context", return_value=(self.cwd, repo))
        with mock.patch.dict(os.environ, self.env, clear=False), context:
            self.assertEqual(cli_module.begin()["status"], "shaping")
        store = StateStore(self.data, "0.1.0")
        approved = transition(transition(store.load(self.session), "freeze"), "approve_ralph")
        store.replace(approved)
        digest_name = hashlib.sha256(self.session.encode()).hexdigest()
        ralph_brief = {**BRIEF, "dispatcher": "ralph", "phases": [
            {"name": "implement", "tier_floor": "senior", "verify": "python3 -m unittest"},
            {"name": "document", "tier_floor": "junior", "verify": "python3 -m py_compile"},
        ]}
        (self.data / f"brief-{digest_name}.json").write_text(
            json.dumps({"digest": "ralph-digest", "brief": ralph_brief}))
        preparation = RalphPreparation(
            self.cwd, (".docs/ai/current-state.md",),
            (FileSnapshot(".docs/ai/current-state.md", True, b"## Plan\n\n"),),
            before_head, before_head)
        runner = self.root / "stall-runner.py"
        runner.write_text("import os, sys, time\nos.read(int(sys.argv[1]), 1)\ntime.sleep(0.15)\n")
        children = []

        def spawn(cwd, marker, _data_root, _launch_id, *, arm_read_fd, acknowledgement_write_fd):
            child = subprocess.Popen(
                [sys.executable, str(runner), str(arm_read_fd)], cwd=cwd,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, env={**os.environ, ralph_module.OWNERSHIP_MARKER_ENV: marker},
                close_fds=True, pass_fds=(arm_read_fd, acknowledgement_write_fd))
            children.append(child)
            return child

        fd_count = len(os.listdir("/dev/fd")) if Path("/dev/fd").exists() else None
        with mock.patch.dict(os.environ, self.env, clear=False), context, \
             mock.patch.object(cli_module, "prepare_ralph_dispatch", return_value=preparation), \
             mock.patch.object(ralph_module, "ACK_WAIT_TIMEOUT_SECONDS", 0.05), \
             mock.patch.object(ralph_module, "_spawn_backend", side_effect=spawn):
            with self.assertRaises(cli_module.CLIError) as failure:
                cli_module.ralph_launch()
        self.assertEqual(failure.exception.code, "ralph_launch_recovery_required")
        self.assertEqual(len(children), 1)
        children[0].wait(timeout=2)
        self.assertEqual(subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.cwd, text=True).strip(), before_head)
        self.assertTrue((self.data / f"ralph-recovery-{digest_name}.json").exists())
        with mock.patch.dict(os.environ, self.env, clear=False), context:
            status = cli_module.ralph_status()
        self.assertEqual(status["terminal"], "recovery-required")
        self.assertEqual(store.load(self.session).status, "ralph_running")
        if fd_count is not None:
            self.assertEqual(len(os.listdir("/dev/fd")), fd_count)

    def test_spawn_proof_never_rewinds_durable_transaction(self):
        self.assertEqual(self.run_cli("begin")[1]["status"], "shaping")
        store = StateStore(self.data, "0.1.0")
        approved = transition(transition(store.load(self.session), "freeze"), "approve_ralph")
        running = transition(approved, "ralph_start")
        store.replace(running)
        launch_id = "f" * 64
        marker = base64.urlsafe_b64encode(bytes.fromhex("a" * 64)).decode("ascii")
        record = {
            "plugin_version": "0.1.0", "session_id": self.session, "cwd": str(self.cwd),
            "repo_root": None, "git_dir": None, "planning_commit": "plan", "pid": 1,
            "pgid": 1, "start": "start", "marker_digest": marker, "launch_id": launch_id,
        }
        cli_module._write_record(self.data, "ralph-", self.session, record)
        preparation = RalphPreparation(self.cwd, (".docs/ai/current-state.md",),
                                       (FileSnapshot(".docs/ai/current-state.md", False),),
                                       "before", "plan")
        cli_module._write_ralph_recovery(self.data, self.session, approved, None,
                                         preparation, launch_id, self.cwd, None)
        with mock.patch.object(cli_module, "read_ralph_receipt", return_value={"status": "spawned"}), \
             mock.patch.object(cli_module, "recover_ralph_status", return_value={"owned": True, "running": True}), \
             mock.patch.object(cli_module, "rollback_ralph_preparation") as rollback:
            body = self.invoke_cli("status")
        self.assertEqual(body["status"], "ralph_running")
        self.assertEqual(body["ralph"]["terminal"], "running")
        rollback.assert_not_called()
        self.assertTrue((self.data / f"ralph-{hashlib.sha256(self.session.encode()).hexdigest()}.json").exists())
        self.assertFalse((self.data / f"ralph-recovery-{hashlib.sha256(self.session.encode()).hexdigest()}.json").exists())

    def test_recovery_rollback_failure_is_fail_closed(self):
        self.assertEqual(self.run_cli("begin")[1]["status"], "shaping")
        store = StateStore(self.data, "0.1.0")
        approved = transition(transition(store.load(self.session), "freeze"), "approve_ralph")
        running = transition(approved, "ralph_start")
        store.replace(running)
        launch_id = "1" * 64
        preparation = RalphPreparation(self.cwd, (".docs/ai/current-state.md",),
                                       (FileSnapshot(".docs/ai/current-state.md", False),),
                                       "before", "plan")
        cli_module._write_ralph_recovery(self.data, self.session, approved, None,
                                         preparation, launch_id, self.cwd, None)
        with mock.patch.object(cli_module, "read_ralph_receipt", return_value={"status": "spawn_failed"}), \
             mock.patch.object(cli_module, "rollback_ralph_preparation", side_effect=cli_module.RalphError("no rollback")):
            body = self.invoke_cli("status")
        self.assertEqual(body["ralph"]["terminal"], "recovery-required")
        self.assertTrue((self.data / f"ralph-recovery-{hashlib.sha256(self.session.encode()).hexdigest()}.json").exists())

    def test_status_reconciles_ralph_once_and_uses_that_same_snapshot(self):
        self.assertEqual(self.run_cli("begin")[1]["status"], "shaping")
        store = StateStore(self.data, "0.1.0")
        state = transition(transition(transition(store.load(self.session), "freeze"), "approve_ralph"), "ralph_start")
        store.replace(state)
        terminal = transition(state, "complete")
        public = {"owned": True, "running": False, "terminal": "completed", "exit_code": 0}
        with mock.patch.object(cli_module, "_reconcile_ralph", return_value=(terminal, public, None)) as reconcile:
            body = self.invoke_cli("status")
        self.assertEqual(reconcile.call_count, 1)
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["ralph"], public)

    def test_ralph_status_receipt_transitions_completed_or_failed(self):
        self.assertEqual(self.run_cli("begin")[1]["status"], "shaping")
        store = StateStore(self.data, "0.1.0")
        state = store.load(self.session)
        state = transition(transition(transition(state, "freeze"), "approve_ralph"), "ralph_start")
        store.replace(state)
        digest_name = hashlib.sha256(self.session.encode()).hexdigest()
        marker = base64.urlsafe_b64encode(bytes.fromhex("a" * 64)).decode("ascii")
        (self.data / f"ralph-{digest_name}.json").write_text(json.dumps({
            "plugin_version": "0.1.0", "session_id": self.session, "cwd": str(self.cwd),
            "repo_root": None, "git_dir": None, "planning_commit": "plan", "pid": 1,
            "pgid": 1, "start": "start", "marker_digest": marker, "launch_id": "a" * 64,
        }))
        with mock.patch.object(cli_module, "read_ralph_receipt", return_value={"status": "completed", "exit_code": 0}), \
             mock.patch.object(cli_module, "read_ralph_output", return_value=""):
            body = self.invoke_cli("ralph-status")
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["terminal"], "completed")
        self.assertEqual(store.load(self.session).status, "completed")

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
