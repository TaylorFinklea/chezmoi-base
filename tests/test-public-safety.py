import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "check-public-safety.py"


def run_scan(files):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for relative_path, contents in files.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(root)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode


def scan_output(files):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for relative_path, contents in files.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        return result.returncode, result.stdout


class PublicSafetyScannerTests(unittest.TestCase):
    def test_accepts_generic_public_identity(self):
        self.assertEqual(run_scan({"dot_gitconfig": "[user]\nname = Generic\n"}), 0)

    def test_rejects_hermes_path(self):
        self.assertNotEqual(run_scan({"private_dot_hermes/config.yaml": "x"}), 0)

    def test_rejects_openai_style_credential(self):
        self.assertNotEqual(run_scan({"dot_example": "token = " + "sk-" + ("a" * 26)}), 0)

    def test_rejects_private_user_path(self):
        self.assertNotEqual(run_scan({"dot_example": "path = /Users/someone/private"}), 0)

    def test_rejects_non_example_email(self):
        self.assertNotEqual(run_scan({"dot_example": "email = person@private.example"}), 0)

    def test_rejects_git_remote(self):
        self.assertNotEqual(run_scan({"dot_example": "remote = git@github.com:private/repo.git"}), 0)

    def test_reports_sensitive_basename_without_contents(self):
        code, output = scan_output({"dot_config/auth.json": "synthetic credential"})
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_config/auth.json: sensitive-basename\n")

    def test_reports_hermes_path_without_contents(self):
        code, output = scan_output({".hermes/config.yaml": "synthetic config"})
        self.assertNotEqual(code, 0)
        self.assertEqual(output, ".hermes/config.yaml: hermes-path\n")

    def test_reports_remaining_credential_shapes_without_values(self):
        code, output = scan_output(
            {
                "github-ghp": "ghp_" + ("a" * 20),
                "github-gho": "gho_" + ("a" * 20),
                "github-ghs": "ghs_" + ("a" * 20),
                "github-ghu": "ghu_" + ("a" * 20),
                "github-ghr": "ghr_" + ("a" * 20),
                "slack": "xoxb-" + ("a" * 10),
                "google": "AIza" + ("a" * 30),
                "aws": "AKIA" + ("A" * 16),
            }
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(
            output,
            "aws: aws-access-key\n"
            "github-gho: github-credential\n"
            "github-ghp: github-credential\n"
            "github-ghr: github-credential\n"
            "github-ghs: github-credential\n"
            "github-ghu: github-credential\n"
            "google: google-credential\n"
            "slack: slack-credential\n",
        )

    def test_reports_home_path_without_contents(self):
        code, output = scan_output({"dot_example": "path = /home/someone/private"})
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: private-path\n")

    def test_reports_ssh_url_without_contents(self):
        code, output = scan_output({"dot_example": "remote = ssh://github.com/private/repo.git"})
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: ssh-url\n")

    def test_scans_nested_tests_but_skips_root_tests(self):
        code, output = scan_output(
            {
                "tests/auth.json": "root fixture",
                "dot_config/tests/auth.json": "nested target",
            }
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_config/tests/auth.json: sensitive-basename\n")

    def test_does_not_print_matched_credential_value(self):
        secret = "sk-" + ("a" * 26)
        code, output = scan_output({"dot_example": secret})
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: openai-credential\n")
        self.assertNotIn(secret, output)


if __name__ == "__main__":
    unittest.main()
