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


def https_url(value):
    return "https" + "://" + value


def remote_url(value):
    return "remote = " + https_url(value)


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
        return scan_output_from_root(root)


def scan_output_from_root(root):
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

    def test_distinguishes_target_bearing_and_no_target_source_states(self):
        self.assertEqual(SCANNER.decode_target_component("private_dot_env"), ".env")
        self.assertEqual(
            SCANNER.path_rules(Path("private_dot_env")), {"sensitive-basename"}
        )
        for source_name in (
            "run_dot_env",
            "once_dot_env",
            "onchange_dot_env",
            "before_dot_env",
            "after_dot_env",
        ):
            with self.subTest(source_name=source_name):
                self.assertIsNone(SCANNER.decode_target_component(source_name))
                self.assertEqual(SCANNER.path_rules(Path(source_name)), set())

    def test_ignore_source_state_has_no_managed_target(self):
        self.assertIsNone(SCANNER.decode_target_component("ignore_dot_hermes"))
        self.assertEqual(SCANNER.path_rules(Path("ignore_dot_hermes")), set())
        self.assertEqual(run_scan({"ignore_dot_hermes": "synthetic ignore source"}), 0)

    def test_rejects_decoded_forbidden_env_target_names(self):
        code, output = scan_output(
            {
                "dot_env": "synthetic env",
                "private_dot_env": "synthetic private env",
                "symlink_dot_hermes": "synthetic hermes",
            }
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(
            output,
            "dot_env: sensitive-basename\n"
            "private_dot_env: sensitive-basename\n"
            "symlink_dot_hermes: hermes-path\n",
        )

    def test_rejects_template_suffix_forbidden_env_target(self):
        code, output = scan_output({"dot_env.tmpl": "synthetic env template"})
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_env.tmpl: sensitive-basename\n")

    def test_rejects_empty_attribute_forbidden_env_target(self):
        code, output = scan_output({"empty_dot_env": "synthetic env"})
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "empty_dot_env: sensitive-basename\n")

    def test_rejects_ignore_source_state_symlink_without_target_violation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            root.mkdir()
            outside = Path(directory) / "outside"
            outside.mkdir()
            (root / "ignore_dot_hermes").symlink_to(
                outside, target_is_directory=True
            )
            code, output = scan_output_from_root(root)

        self.assertNotEqual(code, 0)
        self.assertEqual(output, "ignore_dot_hermes: symlink\n")

    def test_rejects_source_symlinks_without_following_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            root.mkdir()
            outside = Path(directory) / "outside"
            outside.mkdir()
            (outside / ".env").write_text("synthetic env")
            (root / "file-link").symlink_to(outside / ".env")
            (root / "directory-link").symlink_to(outside, target_is_directory=True)
            (root / "dangling-link").symlink_to(outside / "missing")
            code, output = scan_output_from_root(root)

        self.assertNotEqual(code, 0)
        self.assertEqual(
            output,
            "dangling-link: symlink\n"
            "directory-link: symlink\n"
            "file-link: symlink\n",
        )

    def test_rejects_symlinked_scanner_root_without_following_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            outside = Path(directory) / "outside"
            outside.mkdir()
            (outside / "dot_env").write_text("synthetic env")
            root.symlink_to(outside, target_is_directory=True)
            code, output = scan_output_from_root(root)

        self.assertNotEqual(code, 0)
        self.assertEqual(output, ".: symlink-root\n")

    def test_rejects_ds_store_source_symlink_without_following_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            root.mkdir()
            outside = Path(directory) / "outside"
            outside.mkdir()
            (outside / "dot_env").write_text("synthetic env")
            (root / ".DS_Store").symlink_to(outside, target_is_directory=True)
            code, output = scan_output_from_root(root)

        self.assertNotEqual(code, 0)
        self.assertEqual(output, ".DS_Store: symlink\n")

    def test_rejects_symlinks_nested_under_root_tests_without_following_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            nested_tests = root / "tests" / "fixtures"
            nested_tests.mkdir(parents=True)
            outside = Path(directory) / "outside"
            outside.mkdir()
            (outside / "dot_env").write_text("synthetic env")
            (nested_tests / "fixture-link").symlink_to(
                outside, target_is_directory=True
            )
            code, output = scan_output_from_root(root)

        self.assertNotEqual(code, 0)
        self.assertEqual(output, "tests/fixtures/fixture-link: symlink\n")

    def test_rejects_openai_style_credential(self):
        self.assertNotEqual(run_scan({"dot_example": "token = " + "sk-" + ("a" * 26)}), 0)

    def test_rejects_private_user_path(self):
        self.assertNotEqual(
            run_scan({"dot_example": "path = /" + "Users/someone/private"}), 0
        )

    def test_rejects_non_example_email(self):
        self.assertNotEqual(
            run_scan({"dot_example": "email = person" + "@private.example"}), 0
        )

    def test_accepts_example_addresses_followed_by_sentence_punctuation(self):
        addresses = "\n".join(
            f"email = person@{domain}{punctuation}"
            for domain in ("example.com", "example.org", "example.net")
            for punctuation in ".,;:!?"
        )
        self.assertEqual(run_scan({"dot_example": addresses}), 0)

    def test_rejects_git_remote(self):
        self.assertNotEqual(
            run_scan({"dot_example": "remote = git" + "@github.com:private/repo.git"}),
            0,
        )

    def test_accepts_canonical_https_git_remote(self):
        self.assertEqual(
            run_scan(
                {
                    "dot_example": (
                        remote_url("github.com/TaylorFinklea/chezmoi-base.git")
                    )
                }
            ),
            0,
        )

    def test_rejects_non_ascii_https_git_remotes(self):
        code, output = scan_output(
            {
                "dot_non_ascii_host": remote_url("gitföo.com/owner/repo.git"),
                "dot_non_ascii_path": remote_url("github.com/owner/répo.git"),
            }
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(
            output,
            "dot_non_ascii_host: git-remote\n"
            "dot_non_ascii_path: git-remote\n",
        )

    def test_rejects_non_ascii_github_repository_without_git_suffix(self):
        code, output = scan_output(
            {"dot_example": remote_url("github.com/private/répo")}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: git-remote\n")

    def test_rejects_non_ascii_github_repository_with_port_or_empty_userinfo(self):
        code, output = scan_output(
            {
                "dot_port": remote_url("github.com:443/private/répo"),
                "dot_userinfo": remote_url("@github.com/private/répo"),
            }
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(
            output,
            "dot_port: git-remote\n"
            "dot_userinfo: git-remote\n"
            "dot_userinfo: url-credentials\n",
        )

    def test_rejects_canonical_https_git_remote_with_non_ascii_decoration(self):
        code, output = scan_output(
            {
                "dot_fragment": (
                    remote_url("github.com/TaylorFinklea/chezmoi-base.git#é")
                ),
                "dot_query": (
                    remote_url("github.com/TaylorFinklea/chezmoi-base.git?x=é")
                ),
            }
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(
            output,
            "dot_fragment: git-remote\n"
            "dot_query: git-remote\n",
        )

    def test_rejects_canonical_https_git_remote_with_appended_path(self):
        code, output = scan_output(
            {"dot_example": remote_url("github.com/TaylorFinklea/chezmoi-base.git/extra")}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: git-remote\n")

    def test_rejects_canonical_https_git_remote_with_trailing_period(self):
        code, output = scan_output(
            {"dot_example": remote_url("github.com/TaylorFinklea/chezmoi-base.git.")}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: git-remote\n")

    def test_rejects_double_quoted_canonical_https_git_remote(self):
        code, output = scan_output(
            {"dot_example": 'remote = "' + https_url("github.com/TaylorFinklea/chezmoi-base.git") + '"'}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: git-remote\n")

    def test_rejects_angle_bracketed_canonical_https_git_remote(self):
        code, output = scan_output(
            {"dot_example": "remote = <" + https_url("github.com/TaylorFinklea/chezmoi-base.git") + ">"}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: git-remote\n")

    def test_rejects_github_url_with_percent_encoded_dot_segment(self):
        code, output = scan_output(
            {"dot_example": remote_url("github.com/%2e/private/repo")}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: git-remote\n")

    def test_rejects_noncanonical_https_git_remote(self):
        code, output = scan_output(
            {"dot_example": remote_url("github.com/private/repo.git")}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: git-remote\n")

    def test_rejects_single_quoted_noncanonical_https_git_remote(self):
        code, output = scan_output(
            {"dot_example": "remote = '" + https_url("github.com/private/repo.git") + "'"}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: git-remote\n")

    def test_rejects_single_quoted_canonical_https_git_remote(self):
        code, output = scan_output(
            {"dot_example": "remote = '" + https_url("github.com/TaylorFinklea/chezmoi-base.git") + "'"}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: git-remote\n")

    def test_rejects_https_git_remote_without_git_suffix(self):
        code, output = scan_output(
            {"dot_example": remote_url("github.com/private/repo")}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: git-remote\n")

    def test_rejects_standard_forge_https_git_remotes_without_git_suffix(self):
        code, output = scan_output(
            {
                "dot_bitbucket": remote_url("bitbucket.org/workspace/repo"),
                "dot_codeberg": remote_url("codeberg.org/owner/repo"),
                "dot_gitlab": remote_url("gitlab.com/group/repo"),
                "dot_nested_gitlab": (
                    remote_url("gitlab.com/group/subgroup/repo")
                ),
            }
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(
            output,
            "dot_bitbucket: git-remote\n"
            "dot_codeberg: git-remote\n"
            "dot_gitlab: git-remote\n"
            "dot_nested_gitlab: git-remote\n",
        )

    def test_rejects_fullwidth_github_host_without_git_suffix(self):
        code, output = scan_output(
            {"dot_example": remote_url("Ｇｉｔｈｕｂ．ｃｏｍ/owner/repo")}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: git-remote\n")

    def test_rejects_https_git_remote_with_percent_encoded_git_suffix(self):
        code, output = scan_output(
            {"dot_example": remote_url("gitlab.com/group/repo%2Egit")}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: git-remote\n")

    def test_rejects_normalized_github_hosts_without_git_suffix(self):
        code, output = scan_output(
            {
                "dot_fullwidth": remote_url("github。com/owner/repo"),
                "dot_www": remote_url("www.github.com/owner/repo"),
            }
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(
            output,
            "dot_fullwidth: git-remote\n"
            "dot_www: git-remote\n",
        )

    def test_accepts_ordinary_https_documentation_url_with_repository_like_path(self):
        self.assertEqual(
            run_scan({"dot_example": "docs = " + https_url("docs.example.com/owner/repo")}),
            0,
        )

    def test_rejects_https_git_remote_with_trailing_dot_github_host(self):
        code, output = scan_output(
            {"dot_example": remote_url("github.com./owner/repo")}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: git-remote\n")

    def test_rejects_embedded_https_url_credentials(self):
        code, output = scan_output(
            {"dot_example": "docs = " + https_url("user:password@example.com/guide")}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: url-credentials\n")

    def test_rejects_embedded_https_url_credentials_with_non_ascii_documentation_url(self):
        code, output = scan_output(
            {
                "dot_example": (
                    "docs = " + https_url("user:password" + "@docs.example.com/guide?title=Résumé")
                )
            }
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(
            output,
            "dot_example: private-email\n"
            "dot_example: url-credentials\n",
        )

    def test_accepts_ordinary_https_documentation_url(self):
        self.assertEqual(
            run_scan({"dot_example": "docs = " + https_url("docs.example.com/guide")}),
            0,
        )

    def test_accepts_non_ascii_ordinary_https_documentation_url(self):
        self.assertEqual(
            run_scan({"dot_example": "docs = " + https_url("docs.example.com/guide?title=Résumé")}),
            0,
        )

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
        code, output = scan_output({"dot_example": "path = /" + "home/someone/private"})
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: private-path\n")

    def test_reports_ssh_url_without_contents(self):
        code, output = scan_output({"dot_example": "remote = ssh" + "://github.com/private/repo.git"})
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "dot_example: ssh-url\n")

    def test_scans_regular_root_test_files(self):
        code, output = scan_output(
            {"tests/fixture.txt": "token = " + "sk-" + ("a" * 26)}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "tests/fixture.txt: openai-credential\n")

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
