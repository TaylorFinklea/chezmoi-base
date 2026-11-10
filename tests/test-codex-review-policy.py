import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "dot_codex" / "AGENTS.md.tmpl"


class CodexReviewPolicyTests(unittest.TestCase):
    def render(self, role):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "chezmoi.toml"
            config.write_text(f'[data]\nmachine_role = "{role}"\n')
            result = subprocess.run(
                ["chezmoi", "--config", str(config), "execute-template", "--file", str(TEMPLATE)],
                check=True,
                capture_output=True,
                text=True,
            )
        return result.stdout

    def test_personal_profile_has_ollama_cloud_authorization_and_review(self):
        rendered = self.render("personal")
        self.assertIn("Ollama Cloud to receive any content Codex is authorized to access", rendered)
        self.assertIn("separate workspaces", rendered)
        self.assertIn("changed or newly created packets", rendered)
        self.assertIn("Also request one independent Ollama Cloud review", rendered)
        self.assertNotIn("{{", rendered)

    def test_work_profile_does_not_require_or_attempt_ollama(self):
        rendered = self.render("work")
        self.assertIn("Do not require or attempt Ollama reviews", rendered)
        self.assertNotIn("Also request one independent Ollama Cloud review", rendered)
        self.assertNotIn("Ollama Cloud to receive any content Codex is authorized to access", rendered)
        self.assertNotIn("{{", rendered)


if __name__ == "__main__":
    unittest.main()
