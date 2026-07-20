import sys
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
        for command in ("git status", "git log --oneline -3", "git diff --stat", "git show HEAD",
                        "rg -n TODO .", "find . -name 'test_*.py'", "ls -la", "pytest --collect-only"):
            with self.subTest(command=command):
                self.assertTrue(is_read_only_shell(command))
                self.assertTrue(classify_tool("Bash", {"command": command}, self.frozen).allowed)

    def test_agents_request_input_and_hosted_gaps(self):
        self.assertTrue(classify_tool("request_user_input", {}, self.state).allowed)
        self.assertTrue(classify_tool("Agent", {"agent_type": "scout", "prompt": "inspect only"}, self.state).allowed)
        self.assertFalse(classify_tool("Agent", {"prompt": "implement the change"}, self.state).allowed)
        self.assertFalse(classify_tool("Agent", {"agent_type": "scout", "task": {"prompt": "write the report to disk"}}, self.state).allowed)
        self.assertFalse(classify_tool("Agent", {"mode": "read-only", "metadata": [{"description": "edit files"}]}, self.state).allowed)
        self.assertTrue(classify_tool("computer", {"action": "screenshot"}, self.state).allowed)
        self.assertFalse(classify_tool("mcp__local__write", {}, self.state).allowed)
        self.assertFalse(classify_tool("unknown_local_tool", {}, self.state).allowed)

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

    def test_missing_state_and_approved_state_defer_to_codex(self):
        self.assertTrue(classify_tool("unknown_local_tool", {}, None).allowed)
        self.assertTrue(classify_tool("Write", {}, self.approved).allowed)


if __name__ == "__main__":
    unittest.main()
