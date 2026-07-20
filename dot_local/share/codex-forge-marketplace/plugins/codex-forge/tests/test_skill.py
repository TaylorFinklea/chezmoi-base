from pathlib import Path
import re
import unittest


class SkillTests(unittest.TestCase):
    def test_forge_skill_contract(self):
        path = Path(__file__).parents[1] / "skills" / "forge" / "SKILL.md"
        text = path.read_text()
        self.assertRegex(text, r"^---\nname: forge\n")
        for required in (
            "$forge", "Recon first", "default cap is **3 questions**",
            "**5 is the hard maximum**", "no writes", "freeze",
            "approve <nonce> direct", "approve <nonce> ralph",
            "revise <nonce>", "cancel <nonce>", "direct", "Ralph",
            "current hook heartbeat", "../../bin/codex-forge", "loaded SKILL.md",
            "prose-only approval", "Ralph handoff", "ralph-preflight",
            "ralph-launch", "ralph-status", "ralph-cancel", "never rewrites Git",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)
        self.assertNotIn("hooks/forge_hook.py", text)
        self.assertRegex(text, re.compile(r"one focused question", re.I))


if __name__ == "__main__":
    unittest.main()
