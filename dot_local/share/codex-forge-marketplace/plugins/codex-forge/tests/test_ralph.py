import errno
import hashlib
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "lib"))

from codex_forge import ralph as ralph_module
from codex_forge import ralph_runner
from codex_forge.brief import Brief, DecisionEnvelope, Phase
from codex_forge.ralph import (
    ProcessIdentity,
    RalphError,
    cancel_owned_ralph,
    check_ralph_eligibility,
    inspect_ralph_eligibility,
    launch_ralph_dispatch,
    prepare_ralph_dispatch,
    read_ralph_output,
    read_ralph_receipt,
    recover_ralph_status,
)


BRIEF = Brief(
    1, "Add cached search", ("cache",), (), (), ("tests pass",), (), (), (),
    DecisionEnvelope(("formatting",), ("security",)),
    (Phase("Implement", "senior", "python3 -m unittest"),
     Phase("Document", "junior", "python3 -m py_compile")), "ralph",
)


class FakePopen:
    def __init__(self, *, running: bool):
        self.pid = 4242
        self.stdout = io.BytesIO()
        self.stderr = io.BytesIO()
        self.returncode = None if running else 0
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminate_calls += 1
        self.returncode = 0

    def kill(self):
        self.kill_calls += 1
        self.returncode = 0

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class RalphTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / ".docs/ai").mkdir(parents=True)
        (self.repo / ".docs/ai/current-state.md").write_bytes(
            b"# Current State\n\n## Branch\nmain\n\n## Plan\n\n## Blockers\n- None\n")
        (self.repo / ".docs/ai/roadmap.md").write_bytes(
            b"# Roadmap\n\n### Now\n- [ ] Existing\n\n### Next\n- Later\n")
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Forge Test"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "forge-test"], cwd=self.repo, check=True)
        subprocess.run(["git", "add", ".docs/ai"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "baseline"], cwd=self.repo, check=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.ralph = self.bin / "ralph"
        self.ralph.write_text("#!/bin/sh\nexit 0\n")
        self.ralph.chmod(0o755)
        self.path = os.environ.get("PATH", "")

    def tearDown(self):
        self.tmp.cleanup()

    def env(self, **extra):
        return {"PATH": f"{self.bin}{os.pathsep}{self.path}", **extra}

    def prepare(self):
        with mock.patch.dict(os.environ, self.env(), clear=False):
            return prepare_ralph_dispatch(BRIEF, self.repo, date="2026-07-20")

    def launch(self, preparation, *, on_spawn=None, on_abort=None):
        return launch_ralph_dispatch(preparation, data_root=self.root / "ralph-data",
                                     launch_id="b" * 64, on_spawn=on_spawn, on_abort=on_abort)

    def wait_receipt(self, launch, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            receipt = read_ralph_receipt(self.root / "ralph-data", launch.launch_id)
            if receipt and receipt["status"] in {"completed", "failed"}:
                return receipt
            time.sleep(0.02)
        self.fail("Ralph runner did not publish a terminal receipt")

    def test_rejects_all_eligibility_guards(self):
        cases = (
            {"is_git": False}, {"clean": False}, {"current_state": None},
            {"roadmap": None}, {"has_beads": True}, {"ralph_exists": False},
        )
        for patch in cases:
            kwargs = dict(is_git=True, clean=True, current_state="## Plan\n\n",
                          roadmap="# Roadmap\n", has_beads=False, brief=BRIEF,
                          ralph_exists=True)
            kwargs.update(patch)
            with self.subTest(patch=patch):
                self.assertFalse(check_ralph_eligibility(**kwargs).eligible)

    def test_inspect_rejects_non_git_and_dirty_repositories(self):
        non_git = self.root / "not-git"
        non_git.mkdir()
        (non_git / ".docs/ai").mkdir(parents=True)
        (non_git / ".docs/ai/current-state.md").write_text("## Plan\n\n")
        (non_git / ".docs/ai/roadmap.md").write_text("# Roadmap\n")
        with mock.patch.dict(os.environ, self.env(), clear=False):
            self.assertIn("Current directory is not a Git repository.",
                          inspect_ralph_eligibility(BRIEF, non_git).reasons)
            (self.repo / "dirty").write_text("x")
            self.assertIn("Git worktree is not clean.", inspect_ralph_eligibility(BRIEF, self.repo).reasons)

    def test_rejects_occupied_plan_lead_missing_verify_and_short_brief(self):
        occupied = check_ralph_eligibility(
            is_git=True, clean=True, current_state="## Plan\n- [ ] active\n", roadmap="x\n",
            has_beads=False, brief=BRIEF)
        self.assertIn("Current Plan already has items.", occupied.reasons)
        bad = Brief(BRIEF.version, BRIEF.goal, BRIEF.scope, BRIEF.non_goals, BRIEF.decisions,
                    BRIEF.acceptance, BRIEF.patterns, BRIEF.verification, BRIEF.assumptions,
                    BRIEF.decision_envelope, (Phase("Lead", "lead", ""),), "ralph")
        result = check_ralph_eligibility(is_git=True, clean=True, current_state="## Plan\n\n",
                                         roadmap="x\n", has_beads=False, brief=bad)
        self.assertFalse(result.eligible)
        self.assertTrue(any("two" in reason for reason in result.reasons))
        self.assertTrue(any("Lead" in reason for reason in result.reasons))
        self.assertTrue(any("lacks" in reason for reason in result.reasons))

    def test_structural_utf8_newline_and_symlink_guards(self):
        for value in (b"## Plan\r\n", b"## Plan\n\xff"):
            with self.subTest(value=value):
                path = self.repo / ".docs/ai/current-state.md"
                path.write_bytes(value)
                with mock.patch.dict(os.environ, self.env(), clear=False):
                    with self.assertRaises(RalphError):
                        inspect_ralph_eligibility(BRIEF, self.repo)
        outside = self.root / "outside"
        outside.mkdir()
        current = self.repo / ".docs/ai/current-state.md"
        current.unlink()
        current.symlink_to(outside / "state")
        with mock.patch.dict(os.environ, self.env(), clear=False):
            with self.assertRaises(RalphError):
                inspect_ralph_eligibility(BRIEF, self.repo)

    def test_prepare_uses_exact_codex_preflight_and_owned_commit(self):
        log = self.root / "ralph.log"
        self.ralph.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$*\" >> \"$RALPH_LOG\"\n"
            "if [ \"${1:-}\" = \"-n\" ]; then\n"
            "  test ! -e .docs/ai/phases/add-cached-search-spec.md\n"
            "  ! grep -q '^- \\[ \\]' .docs/ai/current-state.md\n"
            "fi\n"
            "exit 0\n"
        )
        self.ralph.chmod(0o755)
        with mock.patch.dict(os.environ, self.env(RALPH_LOG=str(log)), clear=False):
            preparation = prepare_ralph_dispatch(BRIEF, self.repo, date="2026-07-20")
        self.assertEqual(preparation.planning_commit, subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip())
        self.assertEqual(log.read_text().splitlines(), ["-n 0 -t codex"])
        self.assertEqual(subprocess.check_output(
            ["git", "show", "--pretty=format:", "--name-only", "HEAD"], cwd=self.repo, text=True).splitlines(),
            [".docs/ai/current-state.md", ".docs/ai/phases/add-cached-search-spec.md", ".docs/ai/roadmap.md"])
        self.assertIn("- [ ] Implement. Verify: `python3 -m unittest` (tier_floor: senior)",
                      (self.repo / ".docs/ai/current-state.md").read_text())
        self.assertTrue((self.repo / ".docs/ai/phases/add-cached-search-spec.md").exists())

    def test_preflight_failure_restores_byte_exact_files(self):
        before = {path: path.read_bytes() for path in (self.repo / ".docs/ai").glob("*.md")}
        self.ralph.write_text("#!/bin/sh\necho failed >&2\nexit 7\n")
        self.ralph.chmod(0o755)
        with mock.patch.dict(os.environ, self.env(), clear=False):
            with self.assertRaisesRegex(RalphError, "Ralph preflight failed"):
                prepare_ralph_dispatch(BRIEF, self.repo)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertFalse((self.repo / ".docs/ai/phases/add-cached-search-spec.md").exists())
        self.assertEqual(subprocess.check_output(["git", "log", "-1", "--format=%s"], cwd=self.repo, text=True).strip(), "baseline")

    def test_preflight_clean_commit_is_rejected_without_planning_writes(self):
        before_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        before = {path: path.read_bytes() for path in (self.repo / ".docs/ai").glob("*.md")}
        self.ralph.write_text(
            "#!/bin/sh\n"
            "if [ \"${1:-}\" = \"-n\" ]; then git commit --allow-empty -qm preflight-mutated-head; fi\n"
        )
        self.ralph.chmod(0o755)
        with mock.patch.dict(os.environ, self.env(), clear=False):
            with self.assertRaisesRegex(RalphError, "modified HEAD"):
                prepare_ralph_dispatch(BRIEF, self.repo)
        self.assertNotEqual(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip(), before_head)
        self.assertEqual(subprocess.check_output(["git", "log", "-1", "--format=%s"], cwd=self.repo, text=True).strip(), "preflight-mutated-head")
        self.assertFalse((self.repo / ".docs/ai/phases/add-cached-search-spec.md").exists())
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(subprocess.check_output(["git", "status", "--porcelain"], cwd=self.repo, text=True), "")

    def test_planning_commit_failure_restores_byte_exact_files(self):
        original_run = ralph_module._run

        def fail_commit(args, cwd, **kwargs):
            if list(args[:2]) == ["git", "commit"]:
                raise RalphError("git commit: injected")
            return original_run(args, cwd, **kwargs)

        with mock.patch.dict(os.environ, self.env(), clear=False), \
             mock.patch.object(ralph_module, "_run", side_effect=fail_commit):
            with self.assertRaisesRegex(RalphError, "injected"):
                prepare_ralph_dispatch(BRIEF, self.repo)
        self.assertEqual(subprocess.check_output(["git", "log", "-1", "--format=%s"], cwd=self.repo, text=True).strip(), "baseline")
        self.assertEqual(subprocess.check_output(["git", "status", "--porcelain"], cwd=self.repo, text=True), "")
        self.assertFalse((self.repo / ".docs/ai/phases/add-cached-search-spec.md").exists())

    def test_post_commit_rev_parse_failure_rolls_back_only_owned_plan(self):
        original_run = ralph_module._run
        committed = False
        failed = False

        def fail_rev_parse(args, cwd, **kwargs):
            nonlocal committed, failed
            result = original_run(args, cwd, **kwargs)
            if list(args[:2]) == ["git", "commit"]:
                committed = True
            elif committed and not failed and list(args) == ["git", "rev-parse", "HEAD"]:
                failed = True
                raise RalphError("injected post-commit rev-parse failure")
            return result

        before = {path: path.read_bytes() for path in (self.repo / ".docs/ai").glob("*.md")}
        with mock.patch.dict(os.environ, self.env(), clear=False), \
             mock.patch.object(ralph_module, "_run", side_effect=fail_rev_parse):
            with self.assertRaisesRegex(RalphError, "post-commit rev-parse"):
                prepare_ralph_dispatch(BRIEF, self.repo)
        self.assertTrue(failed)
        self.assertEqual(subprocess.check_output(["git", "log", "-1", "--format=%s"], cwd=self.repo, text=True).strip(), "baseline")
        self.assertEqual(subprocess.check_output(["git", "status", "--porcelain"], cwd=self.repo, text=True), "")
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertFalse((self.repo / ".docs/ai/phases/add-cached-search-spec.md").exists())

    def test_post_commit_preparation_construction_failure_rolls_back_only_owned_plan(self):
        before = {path: path.read_bytes() for path in (self.repo / ".docs/ai").glob("*.md")}
        with mock.patch.dict(os.environ, self.env(), clear=False), \
             mock.patch.object(ralph_module, "RalphPreparation", side_effect=RuntimeError("injected preparation failure")):
            with self.assertRaisesRegex(RuntimeError, "injected preparation failure"):
                prepare_ralph_dispatch(BRIEF, self.repo)
        self.assertEqual(subprocess.check_output(["git", "log", "-1", "--format=%s"], cwd=self.repo, text=True).strip(), "baseline")
        self.assertEqual(subprocess.check_output(["git", "status", "--porcelain"], cwd=self.repo, text=True), "")
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertFalse((self.repo / ".docs/ai/phases/add-cached-search-spec.md").exists())

    def test_spawn_failure_rolls_back_only_before_spawn(self):
        preparation = self.prepare()
        with mock.patch.object(ralph_module, "_spawn_backend", side_effect=OSError("missing")):
            with self.assertRaisesRegex(RalphError, "before spawn"):
                self.launch(preparation)
        self.assertEqual(subprocess.check_output(["git", "log", "-1", "--format=%s"], cwd=self.repo, text=True).strip(), "baseline")
        self.assertFalse((self.repo / ".docs/ai/phases/add-cached-search-spec.md").exists())

    def test_second_pipe_creation_closes_first_pair_and_rolls_back_transaction(self):
        original_pipe = os.pipe
        acquired = []
        calls = 0

        def fail_second_pipe():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected second pipe failure")
            pair = original_pipe()
            acquired.extend(pair)
            return pair

        with mock.patch.object(ralph_module.os, "pipe", side_effect=fail_second_pipe):
            with self.assertRaisesRegex(OSError, "second pipe"):
                ralph_module._launch_pipes()
        for fd in acquired:
            with self.subTest(fd=fd):
                with self.assertRaises(OSError) as failure:
                    os.fstat(fd)
                self.assertEqual(failure.exception.errno, errno.EBADF)

        preparation = self.prepare()
        calls = 0
        with mock.patch.object(ralph_module.os, "pipe", side_effect=fail_second_pipe):
            with self.assertRaisesRegex(RalphError, "before spawn"):
                self.launch(preparation)
        self.assertEqual(subprocess.check_output(
            ["git", "log", "-1", "--format=%s"], cwd=self.repo, text=True).strip(), "baseline")
        self.assertFalse((self.repo / ".docs/ai/phases/add-cached-search-spec.md").exists())

    def test_post_arm_ack_timeout_is_bounded_and_never_rewinds_git(self):
        read_fd, write_fd = os.pipe()
        try:
            started = time.monotonic()
            with mock.patch.object(ralph_module, "ACK_WAIT_TIMEOUT_SECONDS", 0.05):
                with self.assertRaises(TimeoutError):
                    ralph_module._read_exact_ack(read_fd)
            self.assertLess(time.monotonic() - started, 0.5)
        finally:
            os.close(read_fd)
            os.close(write_fd)

        child = FakePopen(running=True)
        identity = ProcessIdentity(child.pid, "started", child.pid, "a" * 64)
        with mock.patch.object(ralph_module, "_spawn_backend", return_value=child), \
             mock.patch.object(ralph_module, "_identity", return_value=identity), \
             mock.patch.object(ralph_module, "_read_exact_ack", side_effect=TimeoutError("injected")):
            with self.assertRaises(ralph_module.RalphLaunchRecoveryError):
                self.launch(self.prepare())
        self.assertNotEqual(subprocess.check_output(
            ["git", "log", "-1", "--format=%s"], cwd=self.repo, text=True).strip(), "baseline")

    def test_ack_loss_real_child_attests_arm_and_is_reaped_without_git_rewind(self):
        attestation = self.root / "arm-attestation"
        script = (
            "import os, pathlib, sys, time\n"
            "fd = int(sys.argv[1])\n"
            "path = pathlib.Path(sys.argv[2])\n"
            "value = os.read(fd, 1)\n"
            "if value != b'A':\n"
            "    path.write_bytes(b'wrong:' + value)\n"
            "    raise SystemExit(91)\n"
            "tmp = path.with_suffix('.tmp')\n"
            "with open(tmp, 'wb') as stream:\n"
            "    stream.write(value)\n"
            "    stream.flush()\n"
            "    os.fsync(stream.fileno())\n"
            "os.replace(tmp, path)\n"
            "directory = os.open(str(path.parent), os.O_RDONLY)\n"
            "os.fsync(directory)\n"
            "os.close(directory)\n"
            "time.sleep(0.5)\n"
        )
        parent_fds = []
        child_pids = []
        real_launch_pipes = ralph_module._launch_pipes

        def launch_pipes():
            pipes = real_launch_pipes()
            parent_fds.extend(pipes)
            return pipes

        def spawn_backend(cwd, marker, _data_root, _launch_id, *, arm_read_fd,
                          acknowledgement_write_fd):
            environment = dict(os.environ)
            environment[ralph_module.OWNERSHIP_MARKER_ENV] = marker
            child = subprocess.Popen(
                [sys.executable, "-c", script, str(arm_read_fd), str(attestation)],
                cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True, env=environment,
                close_fds=True, pass_fds=(arm_read_fd, acknowledgement_write_fd),
            )
            child_pids.append(child.pid)
            return child

        with mock.patch.object(ralph_module, "_launch_pipes", side_effect=launch_pipes), \
             mock.patch.object(ralph_module, "_spawn_backend", side_effect=spawn_backend), \
             mock.patch.object(ralph_module, "ACK_WAIT_TIMEOUT_SECONDS", 0.1):
            with self.assertRaises(ralph_module.RalphLaunchRecoveryError):
                self.launch(self.prepare())

        deadline = time.monotonic() + 1
        while not attestation.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(attestation.read_bytes(), b"A")
        self.assertEqual(len(child_pids), 1)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(child_pids[0], 0)
            except ProcessLookupError:
                break
            except PermissionError:
                self.fail("ACK-loss child remains live")
            time.sleep(0.02)
        else:
            self.fail("ACK-loss child remained live or zombie after detached reaper deadline")
        for fd in parent_fds:
            with self.subTest(fd=fd), self.assertRaises(OSError):
                os.fstat(fd)
        self.assertNotEqual(subprocess.check_output(
            ["git", "log", "-1", "--format=%s"], cwd=self.repo, text=True).strip(), "baseline")

    def test_failed_pre_popen_rollback_is_always_recovery_required(self):
        preparation = self.prepare()
        with mock.patch.object(ralph_module, "_private_root", side_effect=RalphError("root failed")), \
             mock.patch.object(ralph_module, "_rollback", side_effect=RalphError("rollback failed")):
            with self.assertRaises(ralph_module.RalphLaunchRecoveryError):
                self.launch(preparation)

    def test_no_pipe_fd_leak_after_supervisor_start_failure(self):
        before = len(os.listdir("/dev/fd"))
        preparation = self.prepare()
        with mock.patch.object(ralph_module, "_spawn_backend", side_effect=OSError("missing")):
            with self.assertRaises(RalphError):
                self.launch(preparation)
        self.assertEqual(len(os.listdir("/dev/fd")), before)

    def test_async_launch_returns_promptly_and_receipt_bounds_output(self):
        log = self.root / "ralph.log"
        self.ralph.write_text(
            "#!/bin/sh\n"
            "printf '%s\n' \"$*\" >> \"$RALPH_LOG\"\n"
            "[ \"${1:-}\" = \"-n\" ] && exit 0\n"
            "printf 'phase output\n'\n"
            "sleep 0.3\n"
        )
        self.ralph.chmod(0o755)
        with mock.patch.dict(os.environ, self.env(RALPH_LOG=str(log)), clear=False):
            preparation = self.prepare()
            started = time.monotonic()
            launch = self.launch(preparation)
            self.assertLess(time.monotonic() - started, 0.25)
            receipt = self.wait_receipt(launch)
        self.assertEqual(receipt, {"status": "completed", "exit_code": 0})
        self.assertEqual(read_ralph_output(self.root / "ralph-data", launch.launch_id, "stdout"), "phase output\n")
        self.assertEqual(log.read_text().splitlines(), ["-n 0 -t codex", "-t codex"])
        time.sleep(0.1)
        with self.assertRaises(ProcessLookupError):
            os.kill(launch.identity.pid, 0)
        self.assertNotEqual(subprocess.check_output(["git", "log", "-1", "--format=%s"], cwd=self.repo, text=True).strip(), "baseline")

    def test_pre_arm_callback_failure_rolls_back_plan_and_reaps_unarmed_supervisor(self):
        self.ralph.write_text("#!/bin/sh\n[ \"${1:-}\" = \"-n\" ] && exit 0\nsleep 30\n")
        self.ralph.chmod(0o755)
        spawned = []
        def fail_after_spawn(launch):
            spawned.append(launch.identity.pid)
            raise RuntimeError("state persistence failed")
        with mock.patch.dict(os.environ, self.env(), clear=False), \
             mock.patch.object(ralph_module, "KILL_GRACE_SECONDS", 0.05):
            preparation = self.prepare()
            with self.assertRaisesRegex(RuntimeError, "state persistence failed"):
                self.launch(preparation, on_spawn=fail_after_spawn)
        self.assertEqual(subprocess.check_output(["git", "log", "-1", "--format=%s"], cwd=self.repo, text=True).strip(), "baseline")
        self.assertFalse((self.repo / ".docs/ai/phases/add-cached-search-spec.md").exists())
        self.assertEqual(len(spawned), 1)
        with self.assertRaises(ProcessLookupError):
            os.kill(spawned[0], 0)

    def test_identity_acquisition_failure_uses_popen_handle_without_group_signal(self):
        child = FakePopen(running=True)
        with mock.patch.object(ralph_module, "_spawn_backend", return_value=child), \
             mock.patch.object(ralph_module, "_identity", return_value=None), \
             mock.patch.object(ralph_module.os, "killpg") as killpg:
            with self.assertRaisesRegex(RalphError, "identity could not be established"):
                self.launch(self.prepare())
        self.assertEqual(child.terminate_calls, 1)
        self.assertEqual(killpg.call_args_list, [])

    def test_recovery_rejects_restored_and_reused_pids(self):
        digest = "a" * 64
        record = {"pid": 20, "pgid": 20, "start": "old", "marker_digest": digest}
        with mock.patch.object(ralph_module, "_identity", return_value=None):
            self.assertFalse(recover_ralph_status(record)["owned"])
        reused = ProcessIdentity(20, "new", 20, digest)
        with mock.patch.object(ralph_module, "_identity", return_value=reused):
            self.assertFalse(recover_ralph_status(record)["owned"])
        with self.assertRaises(RalphError):
            cancel_owned_ralph(record, identity=lambda _pid, _marker: reused)

    def test_cancellation_escalates_only_for_the_same_owned_identity(self):
        digest = "a" * 64
        process = ProcessIdentity(41, "start", 41, digest)
        record = {"pid": 41, "pgid": 41, "start": "start", "marker_digest": digest}
        with mock.patch.object(ralph_module.os, "killpg") as killpg:
            result = cancel_owned_ralph(record, grace_seconds=0, identity=lambda _pid, _marker: process)
        self.assertTrue(result["forced"])
        self.assertEqual(killpg.call_args_list, [
            mock.call(41, signal.SIGTERM), mock.call(41, signal.SIGKILL),
        ])
        with mock.patch.object(ralph_module.os, "killpg") as killpg:
            with self.assertRaises(RalphError):
                cancel_owned_ralph(record, grace_seconds=0, identity=lambda _pid, _marker: None)
        self.assertEqual(killpg.call_args_list, [])

    def test_cancellation_revalidates_before_term_and_refuses_reused_group(self):
        digest = "a" * 64
        process = ProcessIdentity(41, "start", 41, digest)
        reused = ProcessIdentity(41, "reused", 42, digest)
        record = {"pid": 41, "pgid": 41, "start": "start", "marker_digest": digest}
        identities = iter((process, reused))
        with mock.patch.object(ralph_module.os, "killpg") as killpg:
            with self.assertRaises(RalphError):
                cancel_owned_ralph(record, identity=lambda _pid, _marker: next(identities))
        self.assertEqual(killpg.call_args_list, [])

    def test_darwin_same_second_reuse_with_a_missing_or_different_marker_is_never_owned_or_signalled(self):
        expected = "a" * 64
        record = {"pid": 41, "pgid": 41, "start": "1700000000.000001", "marker_digest": expected}
        for observed in (None, ProcessIdentity(41, "1700000000.000002", 41, expected),
                         ProcessIdentity(41, "1700000000.000001", 41, "b" * 64)):
            with self.subTest(observed=observed), \
                 mock.patch.object(ralph_module.os, "killpg") as killpg:
                self.assertFalse(recover_ralph_status(
                    record, identity=lambda _pid, _marker: observed)["owned"])
                with self.assertRaises(RalphError):
                    cancel_owned_ralph(record, identity=lambda _pid, _marker: observed)
                self.assertEqual(killpg.call_args_list, [])

    def test_supervisor_marker_stays_in_environment_and_pipes_are_explicitly_inherited(self):
        marker = "private-launch-marker"
        data = self.root / "ralph-data"
        data.mkdir()
        for name in ralph_module._private_names("a" * 64):
            (data / name).write_bytes(b"")
        arm_read, arm_write = os.pipe()
        ack_read, ack_write = os.pipe()
        try:
            with mock.patch.object(ralph_module.subprocess, "Popen") as popen:
                ralph_module._spawn_backend(self.repo, marker, data, "a" * 64,
                                            arm_read_fd=arm_read, acknowledgement_write_fd=ack_write)
            args, kwargs = popen.call_args
            self.assertIn("ralph_runner.py", args[0][1])
            self.assertEqual(kwargs["env"][ralph_module.OWNERSHIP_MARKER_ENV], marker)
            self.assertNotIn(marker, args[0])
            self.assertNotEqual(ralph_module._marker_digest(marker), marker)
            self.assertEqual(kwargs["pass_fds"], (arm_read, ack_write))
            self.assertTrue(kwargs["close_fds"])
        finally:
            for fd in (arm_read, arm_write, ack_read, ack_write):
                os.close(fd)

    def test_streaming_redaction_handles_every_8192_boundary_adjacent_and_eof_tail(self):
        token = b"token-boundary-123"
        digest = hashlib.sha256(token).hexdigest().encode("ascii")
        for secret in (token, digest):
            for split in range(len(secret) + 1):
                with self.subTest(secret_length=len(secret), split=split):
                    path = self.root / f"stream-{len(secret)}-{split}.log"
                    path.write_bytes(b"")
                    path.chmod(0o600)
                    fd = os.open(path, os.O_WRONLY)
                    sink = ralph_runner._TailFile(fd, (token, digest))
                    prefix = b"ordinary-start:" + b"x" * (8192 - len(b"ordinary-start:") - split)
                    sink.append(prefix + secret[:split])
                    sink.append(secret[split:] + b"|" + token + digest + token + b"|ordinary-end\n")
                    sink.close()
                    output = path.read_bytes()
                    self.assertIn(b"ordinary-start:", output)
                    self.assertIn(b"ordinary-end\n", output)
                    self.assertNotIn(token, output)
                    self.assertNotIn(digest, output)
                    self.assertIn(b"[REDACTED]", output)
        eof = self.root / "stream-eof.log"
        eof.write_bytes(b"")
        eof.chmod(0o600)
        fd = os.open(eof, os.O_WRONLY)
        sink = ralph_runner._TailFile(fd, (token, digest))
        sink.append(b"ordinary-eof:" + token + digest)
        sink.close()
        self.assertNotIn(token, eof.read_bytes())
        self.assertNotIn(digest, eof.read_bytes())

    def test_supervisor_waits_for_persistence_gate_before_spawning_real_ralph(self):
        started = self.root / "ralph-started"
        self.ralph.write_text(
            "#!/bin/sh\n[ \"${1:-}\" = \"-n\" ] && exit 0\ntouch \"$RALPH_STARTED\"\n"
        )
        self.ralph.chmod(0o755)
        def persisted(_launch):
            self.assertFalse(started.exists())
        with mock.patch.dict(os.environ, self.env(RALPH_STARTED=str(started)), clear=False):
            launch = self.launch(self.prepare(), on_spawn=persisted)
            self.assertEqual(self.wait_receipt(launch)["exit_code"], 0)
        self.assertTrue(started.exists())

    def test_private_pre_popen_failures_roll_back_plan_before_supervisor_starts(self):
        for failure in ("root", 1, 2, 3):
            with self.subTest(failure=failure):
                preparation = self.prepare()
                if failure == "root":
                    patcher = mock.patch.object(ralph_module, "_private_root", side_effect=RalphError("injected root"))
                else:
                    original_create = ralph_module._create_private_file
                    calls = 0
                    def fail_create(*args, **kwargs):
                        nonlocal calls
                        calls += 1
                        if calls == failure:
                            raise RalphError("injected private file")
                        return original_create(*args, **kwargs)
                    patcher = mock.patch.object(ralph_module, "_create_private_file", side_effect=fail_create)
                with patcher:
                    with self.assertRaisesRegex(RalphError, "injected"):
                        launch_ralph_dispatch(preparation, data_root=self.root / f"ralph-data-{failure}",
                                              launch_id="c" * 64)
                self.assertEqual(subprocess.check_output(
                    ["git", "log", "-1", "--format=%s"], cwd=self.repo, text=True).strip(), "baseline")
                self.assertEqual(subprocess.check_output(["git", "status", "--porcelain"], cwd=self.repo, text=True), "")
                self.assertFalse((self.repo / ".docs/ai/phases/add-cached-search-spec.md").exists())

    def test_static_private_root_symlink_or_file_collision_rolls_back_plan(self):
        for symlink_root in (True, False):
            with self.subTest(symlink_root=symlink_root):
                preparation = self.prepare()
                data = self.root / f"private-{symlink_root}"
                if symlink_root:
                    target = self.root / "outside"
                    target.mkdir()
                    data.symlink_to(target, target_is_directory=True)
                else:
                    data.mkdir(mode=0o700)
                    (data / ralph_module._private_names("e" * 64)[0]).write_bytes(b"collision")
                with self.assertRaises(RalphError):
                    launch_ralph_dispatch(preparation, data_root=data, launch_id="e" * 64)
                self.assertEqual(subprocess.check_output(
                    ["git", "log", "-1", "--format=%s"], cwd=self.repo, text=True).strip(), "baseline")
                self.assertEqual(subprocess.check_output(["git", "status", "--porcelain"], cwd=self.repo, text=True), "")

    def test_delayed_pipe_arm_has_no_timeout_and_acknowledges_only_after_popen(self):
        data = self.root / "runner-delayed"
        data.mkdir(mode=0o700)
        launch_id = "f" * 64
        stdout_name, stderr_name, receipt_name = ralph_module._private_names(launch_id)
        for name in (stdout_name, stderr_name, receipt_name):
            path = data / name
            path.write_bytes(b"")
            path.chmod(0o600)
        arm_read, arm_write = os.pipe()
        ack_read, ack_write = os.pipe()
        result = []
        args = [
            "--data-root", str(data), "--stdout-name", stdout_name,
            "--stderr-name", stderr_name, "--receipt-name", receipt_name,
            "--arm-fd", str(arm_read), "--ack-fd", str(ack_write),
        ]
        try:
            with mock.patch.dict(os.environ, self.env(), clear=False):
                runner = threading.Thread(target=lambda: result.append(ralph_runner.main(args)))
                runner.start()
                time.sleep(0.15)
                self.assertTrue(runner.is_alive())
                self.assertIsNone(read_ralph_receipt(data, launch_id))
                os.set_blocking(ack_read, False)
                with self.assertRaises(BlockingIOError):
                    os.read(ack_read, 1)
                os.set_blocking(ack_read, True)
                self.assertEqual(os.write(arm_write, b"A"), 1)
                os.close(arm_write)
                arm_write = -1
                self.assertEqual(os.read(ack_read, 1), b"S")
                self.assertEqual(os.read(ack_read, 1), b"")
                runner.join(5)
            self.assertFalse(runner.is_alive())
            self.assertEqual(result, [0])
            self.assertEqual(read_ralph_receipt(data, launch_id), {"status": "completed", "exit_code": 0})
        finally:
            for fd in (arm_read, arm_write, ack_read, ack_write):
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass

    def test_spawn_failure_receipt_returns_failure_ack_without_real_popen(self):
        data = self.root / "runner-spawn-failure"
        data.mkdir(mode=0o700)
        launch_id = "9" * 64
        stdout_name, stderr_name, receipt_name = ralph_module._private_names(launch_id)
        for name in (stdout_name, stderr_name, receipt_name):
            path = data / name
            path.write_bytes(b"")
            path.chmod(0o600)
        arm_read, arm_write = os.pipe()
        ack_read, ack_write = os.pipe()
        result = []
        args = [
            "--data-root", str(data), "--stdout-name", stdout_name,
            "--stderr-name", stderr_name, "--receipt-name", receipt_name,
            "--arm-fd", str(arm_read), "--ack-fd", str(ack_write),
        ]
        try:
            with mock.patch.dict(os.environ, {"PATH": ""}, clear=False):
                runner = threading.Thread(target=lambda: result.append(ralph_runner.main(args)))
                runner.start()
                self.assertEqual(os.write(arm_write, b"A"), 1)
                os.close(arm_write)
                arm_write = -1
                self.assertEqual(os.read(ack_read, 1), b"F")
                self.assertEqual(os.read(ack_read, 1), b"")
                runner.join(5)
            self.assertEqual(result, [1])
            self.assertEqual(read_ralph_receipt(data, launch_id), {"status": "spawn_failed"})
        finally:
            for fd in (arm_read, arm_write, ack_read, ack_write):
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass

    def test_inherited_arm_pipe_eof_publishes_prearm_abort_without_spawning_ralph(self):
        data = self.root / "runner-eof"
        data.mkdir(mode=0o700)
        launch_id = "d" * 64
        stdout_name, stderr_name, receipt_name = ralph_module._private_names(launch_id)
        for name in (stdout_name, stderr_name, receipt_name):
            path = data / name
            path.write_bytes(b"")
            path.chmod(0o600)
        arm_read, arm_write = os.pipe()
        ack_read, ack_write = os.pipe()
        try:
            os.close(arm_write)
            with mock.patch.dict(os.environ, self.env(), clear=False):
                self.assertEqual(ralph_runner.main([
                    "--data-root", str(data), "--stdout-name", stdout_name,
                    "--stderr-name", stderr_name, "--receipt-name", receipt_name,
                    "--arm-fd", str(arm_read), "--ack-fd", str(ack_write),
                ]), 1)
            self.assertEqual(read_ralph_receipt(data, launch_id), {"status": "prearm_aborted"})
            self.assertEqual(os.read(ack_read, 1), b"")
        finally:
            for fd in (arm_read, ack_read, ack_write):
                try:
                    os.close(fd)
                except OSError:
                    pass

    def test_identity_failure_reaps_unarmed_supervisor_without_spawning_ralph(self):
        started = self.root / "ralph-started"
        self.ralph.write_text(
            "#!/bin/sh\n[ \"${1:-}\" = \"-n\" ] && exit 0\ntouch \"$RALPH_STARTED\"\n"
        )
        self.ralph.chmod(0o755)
        with mock.patch.dict(os.environ, self.env(RALPH_STARTED=str(started)), clear=False), \
             mock.patch.object(ralph_module, "_identity", return_value=None):
            with self.assertRaisesRegex(RalphError, "identity could not be established"):
                self.launch(self.prepare())
        self.assertFalse(started.exists())
        self.assertEqual(subprocess.check_output(
            ["git", "log", "-1", "--format=%s"], cwd=self.repo, text=True).strip(), "baseline")

    def test_supervisor_redacts_and_bounds_tail_files(self):
        self.ralph.write_text(
            "#!/bin/sh\n"
            "[ \"${1:-}\" = \"-n\" ] && exit 0\n"
            "python3 -c 'import hashlib, os, sys; t=os.environ[\"CODEX_FORGE_RALPH_OWNERSHIP_MARKER\"]; d=hashlib.sha256(t.encode()).hexdigest(); print(t); print(d); print(\"x\" * 100000); print(t+d, file=sys.stderr)'\n"
        )
        self.ralph.chmod(0o755)
        token = "launch-token-abc123"
        digest = hashlib.sha256(token.encode()).hexdigest()
        with mock.patch.dict(os.environ, self.env(), clear=False), \
             mock.patch.object(ralph_module.secrets, "token_urlsafe", return_value=token):
            launch = self.launch(self.prepare())
            self.assertEqual(self.wait_receipt(launch)["exit_code"], 0)
        stdout = read_ralph_output(self.root / "ralph-data", launch.launch_id, "stdout", limit=64 * 1024)
        stderr = read_ralph_output(self.root / "ralph-data", launch.launch_id, "stderr", limit=64 * 1024)
        self.assertLessEqual(len(stdout.encode()), 64 * 1024)
        self.assertNotIn(token, stdout + stderr)
        self.assertNotIn(digest, stdout + stderr)
        self.assertIn("[REDACTED]", stderr)


if __name__ == "__main__":
    unittest.main()
