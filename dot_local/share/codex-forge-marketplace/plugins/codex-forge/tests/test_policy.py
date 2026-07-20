import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "lib"))

from codex_forge.policy import classify_tool, is_read_only_shell
from codex_forge.state import ForgeState


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.state = ForgeState("s", Path.cwd().resolve(), None, "shaping")
        self.frozen = ForgeState("s", Path.cwd().resolve(), None, "frozen")
        self.approved = ForgeState("s", Path.cwd().resolve(), None, "approved_direct")

    def test_exact_writer_denial_shape(self):
        decision = classify_tool("apply_patch", {"patch": "*** Update File: x"}, self.state)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.decision, "deny")
        self.assertEqual(decision.reason, "Forge shaping blocks writer tools until nonce approval.")

    def test_shell_parser_rejects_adversarial_syntax_without_execution(self):
        rejected = (
            "git status | cat", "git status && touch x", "git diff > out", "git $(echo status)",
            "cat <<EOF\nsecret\nEOF", "rm -f x", "mv x y", "cp x y", "install x y", "tee x",
            "python3 -c 'open(\"x\", \"w\").write(\"x\")'", "node -e process.exit()",
            "ruby -e 'puts 1'", "perl -e 'print 1'", "git commit -am x", "git reset --hard",
        )
        for command in rejected:
            with self.subTest(command=command):
                self.assertFalse(is_read_only_shell(command))
                self.assertFalse(classify_tool("Bash", {"command": command}, self.state).allowed)

    def test_narrow_read_only_allowlist(self):
        for command in ("git status", "git log --oneline -3 --no-textconv", "git diff --stat --no-textconv", "git show --no-textconv HEAD",
                        "rg -n TODO .", "find . -name 'test_*.py'", "ls -la"):
            with self.subTest(command=command):
                self.assertTrue(is_read_only_shell(command))
                self.assertTrue(classify_tool("Bash", {"command": command}, self.frozen).allowed)

    def test_agents_request_input_and_hosted_gaps(self):
        self.assertTrue(classify_tool("request_user_input", {}, self.state).allowed)
        self.assertTrue(classify_tool("Agent", {"agent_type": "forge-scout", "prompt": "inspect only"}, self.state).allowed)
        self.assertTrue(classify_tool("Agent", {"agent_type": "forge-scout", "prompt": "overwrite all files"}, self.state).allowed)
        self.assertFalse(classify_tool("Agent", {"agent_type": "scout", "prompt": "inspect only"}, self.state).allowed)
        self.assertFalse(classify_tool("Agent", {"prompt": "implement the change"}, self.state).allowed)
        self.assertFalse(classify_tool("Agent", {"agent_type": "forge-scout", "task": {"prompt": "inspect"}}, self.state).allowed)
        self.assertFalse(classify_tool("Agent", {"agent_type": "forge-scout", "sandbox_mode": "workspace-write"}, self.state).allowed)
        self.assertFalse(classify_tool("Agent", {"mode": "read-only", "metadata": [{"description": "inspect files"}]}, self.state).allowed)
        self.assertTrue(classify_tool("computer", {"action": "screenshot"}, self.state).allowed)
        self.assertFalse(classify_tool("mcp__local__write", {}, self.state).allowed)
        self.assertFalse(classify_tool("unknown_local_tool", {}, self.state).allowed)

    def test_pytest_and_py_test_are_not_shaping_allowlist_commands(self):
        for command in ("pytest --collect-only", "py.test --collect-only", "pytest", "py.test"):
            with self.subTest(command=command):
                self.assertFalse(is_read_only_shell(command))

    def test_git_content_commands_require_no_textconv(self):
        for command in ("git log --oneline", "git diff --stat", "git show HEAD"):
            with self.subTest(command=command):
                self.assertFalse(is_read_only_shell(command))
        for command in ("git log --no-textconv --oneline", "git diff --no-textconv --stat", "git show HEAD --no-textconv"):
            with self.subTest(command=command):
                self.assertTrue(is_read_only_shell(command))

    def test_configured_textconv_cannot_execute_when_policy_command_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "marker"
            script = root / "textconv.sh"
            script.write_text(f"#!/bin/sh\nprintf x > {marker}\n")
            script.chmod(0o700)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "diff.spy.textconv", str(script)], check=True)
            (root / ".gitattributes").write_text("*.bin diff=spy\n")
            (root / "sample.bin").write_text("before\n")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
            (root / "sample.bin").write_text("after\n")
            command = "git diff --no-textconv -- sample.bin"
            self.assertTrue(is_read_only_shell(command))
            subprocess.run(command.split(), cwd=root, check=True, stdout=subprocess.DEVNULL)
            self.assertFalse(marker.exists())

    def test_exact_canonical_local_tool_names_only(self):
        for name in ("evil.Bash", "evil.Agent", "Bash.extra", "Agent/extra", "bash", "agent", "shell", "Shell"):
            with self.subTest(name=name):
                self.assertFalse(classify_tool(name, {"command": "git status"}, self.state).allowed)

    def test_allowlist_rejects_paths_wrappers_and_mutating_find_or_git_options(self):
        rejected = (
            "command touch x", "./rg -n TODO .", "./git status", "find . -delete",
            "find . -exec touch x {} ;", "find . -fprint out", "find . -fprintf out %p",
            "rg --pre cat -n TODO .", "rg --pre-glob '*.py' TODO .", "ls --quoting-style=shell .",
            "git status --output=out", "git diff --output=out", "git log --exec-path", "git commit -m x",
            "git reset --hard", "git clean -fd", "git -c core.hooksPath=x status",
        )
        for command in rejected:
            with self.subTest(command=command):
                self.assertFalse(is_read_only_shell(command))

    def test_mcp_namespace_is_rejected_before_alias_dispatch(self):
        for name in ("mcp__untrusted.Bash", "mcp.untrusted.Bash", "mcp/untrusted/Bash", "MCP::untrusted.Bash"):
            with self.subTest(name=name):
                self.assertFalse(classify_tool(name, {"command": "git status"}, self.state).allowed)

    def test_bash_execution_environment_fields_are_denied_during_shaping(self):
        commands = ("git status", "git log --oneline -3 --no-textconv", "codex-forge status")
        fields = ("cwd", "workdir", "working_directory", "shell", "executable", "timeout", "timeout_ms")
        for command in commands:
            for field in fields:
                with self.subTest(command=command, field=field):
                    self.assertFalse(classify_tool("Bash", {"command": command, field: "/tmp"}, self.state).allowed)

    def test_bash_nonempty_environment_mapping_or_list_is_denied(self):
        for environment in ({"PATH": "/tmp"}, [("PYTHONPATH", "/tmp")], ["BASH_ENV=/tmp/evil"]):
            with self.subTest(environment=environment):
                self.assertFalse(classify_tool("Bash", {"command": "git status", "env": environment}, self.state).allowed)
        self.assertTrue(classify_tool("Bash", {"command": "git status", "env": {}}, self.state).allowed)
        self.assertTrue(classify_tool("Bash", {"command": "git status", "env": []}, self.state).allowed)

    def test_missing_state_and_approved_state_defer_to_codex(self):
        self.assertTrue(classify_tool("unknown_local_tool", {}, None).allowed)
        self.assertTrue(classify_tool("Write", {}, self.approved).allowed)


if __name__ == "__main__":
    unittest.main()
