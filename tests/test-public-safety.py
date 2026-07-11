import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "check-public-safety.py"


def load_scanner():
    spec = importlib.util.spec_from_file_location("check_public_safety", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load public safety scanner")
    scanner = importlib.util.module_from_spec(spec)
    original_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(scanner)
    finally:
        sys.dont_write_bytecode = original_dont_write_bytecode
    return scanner


SCANNER = load_scanner()


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

    def test_accepts_example_addresses_followed_by_sentence_punctuation(self):
        addresses = "\n".join(
            f"email = person@{domain}{punctuation}"
            for domain in ("example.com", "example.org", "example.net")
            for punctuation in ".,;:!?"
        )
        self.assertEqual(run_scan({"dot_example": addresses}), 0)

    def test_rejects_git_remote(self):
        self.assertNotEqual(run_scan({"dot_example": "remote = git@github.com:private/repo.git"}), 0)

    def test_reports_all_sensitive_basenames_without_contents(self):
        contents = {
            ".env": "synthetic-env-value",
            "auth.json": "synthetic-auth-value",
            "state.db": "synthetic-db-value",
            "state.db-wal": "synthetic-wal-value",
            "state.db-shm": "synthetic-shm-value",
        }
        code, output = scan_output(
            {f"dot_config/{name}": value for name, value in contents.items()}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(
            output,
            "dot_config/.env: sensitive-basename\n"
            "dot_config/auth.json: sensitive-basename\n"
            "dot_config/state.db: sensitive-basename\n"
            "dot_config/state.db-shm: sensitive-basename\n"
            "dot_config/state.db-wal: sensitive-basename\n",
        )
        self.assertFalse(any(value in output for value in contents.values()))

    def test_reports_hermes_path_without_contents(self):
        code, output = scan_output({".hermes/config.yaml": "synthetic config"})
        self.assertNotEqual(code, 0)
        self.assertEqual(output, ".hermes/config.yaml: hermes-path\n")

    def test_reports_all_credential_shapes_without_values(self):
        credentials = {
            "openai": "sk-" + ("a" * 26),
            "github-ghp": "ghp_" + ("a" * 20),
            "github-gho": "gho_" + ("a" * 20),
            "github-ghs": "ghs_" + ("a" * 20),
            "github-ghu": "ghu_" + ("a" * 20),
            "github-ghr": "ghr_" + ("a" * 20),
            "slack": "xoxb-" + ("a" * 10),
            "google": "AIza" + ("a" * 30),
            "aws": "AKIA" + ("A" * 16),
        }
        code, output = scan_output(credentials)
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
            "openai: openai-credential\n"
            "slack: slack-credential\n",
        )
        self.assertFalse(any(value in output for value in credentials.values()))

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

    def test_rejects_unreadable_nested_directory_from_walker_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocked_directory = root / "nested" / "blocked"
            callback_invoked = False

            def walk_with_error(walk_root, topdown=True, onerror=None, followlinks=False):
                nonlocal callback_invoked
                if onerror is not None:
                    callback_invoked = True
                    onerror(PermissionError(13, "Permission denied", str(blocked_directory)))
                return iter(())

            output = io.StringIO()
            with mock.patch.object(SCANNER.os, "walk", walk_with_error):
                with contextlib.redirect_stdout(output):
                    code = SCANNER.scan(root)

        self.assertTrue(callback_invoked)
        self.assertNotEqual(code, 0)
        self.assertEqual(output.getvalue(), "nested/blocked: unreadable-directory\n")


if __name__ == "__main__":
    unittest.main()
