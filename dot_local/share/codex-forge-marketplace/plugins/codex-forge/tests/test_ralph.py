import hashlib
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "lib"))

from codex_forge import ralph as ralph_module
from codex_forge.brief import Brief, DecisionEnvelope, Phase
from codex_forge.ralph import (
    ProcessIdentity,
    RalphError,
    cancel_owned_ralph,
    check_ralph_eligibility,
    inspect_ralph_eligibility,
    launch_ralph_dispatch,
    prepare_ralph_dispatch,
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
        subprocess.run(["git", "config", "user.email", "forge@example.invalid"], cwd=self.repo, check=True)
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
                launch_ralph_dispatch(preparation)
        self.assertEqual(subprocess.check_output(["git", "log", "-1", "--format=%s"], cwd=self.repo, text=True).strip(), "baseline")
        self.assertFalse((self.repo / ".docs/ai/phases/add-cached-search-spec.md").exists())

    def test_spawned_result_never_rewinds_and_uses_exact_backend_argv(self):
        log = self.root / "ralph.log"
        self.ralph.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$RALPH_LOG\"\nprintf 'phase output\\n'\n")
        self.ralph.chmod(0o755)
        with mock.patch.dict(os.environ, self.env(RALPH_LOG=str(log)), clear=False):
            preparation = prepare_ralph_dispatch(BRIEF, self.repo)
            result = launch_ralph_dispatch(preparation)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout, "phase output\n")
        self.assertEqual(log.read_text().splitlines(), ["-n 0 -t codex", "-t codex"])
        self.assertNotIn("-L", log.read_text())
        self.assertNotEqual(subprocess.check_output(["git", "log", "-1", "--format=%s"], cwd=self.repo, text=True).strip(), "baseline")
        self.assertTrue((self.repo / ".docs/ai/phases/add-cached-search-spec.md").exists())

    def test_spawned_callback_failure_keeps_plan_and_reaps_group(self):
        self.ralph.write_text("#!/bin/sh\n[ \"${1:-}\" = \"-n\" ] && exit 0\nsleep 30\n")
        self.ralph.chmod(0o755)
        spawned: list[int] = []

        def fail_after_spawn(identity):
            spawned.append(identity.pid)
            raise RuntimeError("state persistence failed")

        with mock.patch.dict(os.environ, self.env(), clear=False), \
             mock.patch.object(ralph_module, "KILL_GRACE_SECONDS", 0.05):
            preparation = prepare_ralph_dispatch(BRIEF, self.repo)
            with self.assertRaisesRegex(RuntimeError, "state persistence failed"):
                launch_ralph_dispatch(preparation, on_spawn=fail_after_spawn)
        self.assertNotEqual(subprocess.check_output(["git", "log", "-1", "--format=%s"], cwd=self.repo, text=True).strip(), "baseline")
        self.assertEqual(len(spawned), 1)
        with self.assertRaises(ProcessLookupError):
            os.kill(spawned[0], 0)

    def test_identity_acquisition_failure_uses_popen_handle_without_group_signal(self):
        child = FakePopen(running=True)
        with mock.patch.object(ralph_module, "_spawn_backend", return_value=child), \
             mock.patch.object(ralph_module, "_identity", return_value=None), \
             mock.patch.object(ralph_module.os, "killpg") as killpg:
            with self.assertRaisesRegex(RalphError, "identity could not be established"):
                launch_ralph_dispatch(self.prepare())
        self.assertEqual(child.terminate_calls, 1)
        self.assertEqual(child.kill_calls, 0)
        self.assertEqual(killpg.call_args_list, [])
        self.assertNotEqual(subprocess.check_output(["git", "log", "-1", "--format=%s"], cwd=self.repo, text=True).strip(), "baseline")

    def test_exited_child_identity_failure_never_signals_group(self):
        child = FakePopen(running=False)
        with mock.patch.object(ralph_module, "_spawn_backend", return_value=child), \
             mock.patch.object(ralph_module, "_identity", return_value=None), \
             mock.patch.object(ralph_module.os, "killpg") as killpg:
            with self.assertRaisesRegex(RalphError, "identity could not be established"):
                launch_ralph_dispatch(self.prepare())
        self.assertEqual(child.terminate_calls, 0)
        self.assertEqual(killpg.call_args_list, [])

    def test_pid_reuse_during_exception_cleanup_never_signals_foreign_group(self):
        child = FakePopen(running=True)
        calls = 0
        marker = "a" * 64

        def identities(pid, marker_digest=None):
            nonlocal calls
            calls += 1
            if calls == 1:
                return ProcessIdentity(pid, "owned", pid, marker_digest)
            return ProcessIdentity(pid, "reused", pid + 1, marker_digest)

        with mock.patch.object(ralph_module, "_spawn_backend", return_value=child), \
             mock.patch.object(ralph_module, "_identity", side_effect=identities), \
             mock.patch.object(ralph_module.os, "killpg") as killpg:
            with self.assertRaisesRegex(RuntimeError, "state persistence failed"):
                launch_ralph_dispatch(self.prepare(), on_spawn=lambda _: (_ for _ in ()).throw(RuntimeError("state persistence failed")))
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

    def test_darwin_marker_probe_uses_argument_array_and_rejects_missing_or_different_markers(self):
        token = "darwin-private-token"
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        command = ["ps", "-E", "-ww", "-o", "command=", "-p", "71"]
        matching = subprocess.CompletedProcess(command, 0, f"/bin/sh {ralph_module.OWNERSHIP_MARKER_ENV}={token}\n", "")
        missing = subprocess.CompletedProcess(command, 0, "/bin/sh OTHER=value\n", "")
        different = subprocess.CompletedProcess(command, 0, f"/bin/sh {ralph_module.OWNERSHIP_MARKER_ENV}=different\n", "")
        with mock.patch.object(ralph_module.sys, "platform", "darwin"), \
             mock.patch.object(ralph_module.subprocess, "run", side_effect=(matching, missing, different)) as run:
            self.assertTrue(ralph_module._marker_matches(71, digest))
            self.assertFalse(ralph_module._marker_matches(71, digest))
            self.assertFalse(ralph_module._marker_matches(71, digest))
        self.assertEqual([call.args[0] for call in run.call_args_list], [command, command, command])

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

    def test_backend_marker_stays_in_environment_and_only_its_digest_is_persistable(self):
        marker = "private-launch-marker"
        with mock.patch.object(ralph_module.subprocess, "Popen") as popen:
            ralph_module._spawn_backend(self.repo, marker)
        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["ralph", "-t", "codex"])
        self.assertEqual(kwargs["env"][ralph_module.OWNERSHIP_MARKER_ENV], marker)
        self.assertNotIn(marker, args[0])
        self.assertNotEqual(ralph_module._marker_digest(marker), marker)

    def test_output_is_bounded(self):
        self.ralph.write_text("#!/bin/sh\npython3 -c 'print(\"x\" * 100000)'\n")
        self.ralph.chmod(0o755)
        with mock.patch.dict(os.environ, self.env(), clear=False):
            preparation = prepare_ralph_dispatch(BRIEF, self.repo)
            result = launch_ralph_dispatch(preparation)
        self.assertLessEqual(len(result.stdout.encode()), 64 * 1024)


if __name__ == "__main__":
    unittest.main()
