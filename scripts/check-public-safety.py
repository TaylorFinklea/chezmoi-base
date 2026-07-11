#!/usr/bin/env python3
import argparse
import os
import posixpath
import re
import stat
import sys
from pathlib import Path
from urllib.parse import unquote, unquote_to_bytes, urlsplit


FORBIDDEN_BASENAMES = {
    ".env",
    "auth.json",
    "state.db",
    "state.db-wal",
    "state.db-shm",
}
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net"}
SCRIPT_PATH = Path(__file__).resolve()

CREDENTIAL_PATTERNS = (
    ("openai-credential", re.compile(rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}")),
    ("github-credential", re.compile(rb"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{20,}")),
    ("slack-credential", re.compile(rb"(?<![A-Za-z0-9])xox[a-z]-[A-Za-z0-9-]{10,}")),
    ("google-credential", re.compile(rb"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{30,}")),
    ("aws-access-key", re.compile(rb"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])")),
)
EMAIL_PATTERN = re.compile(rb"(?i)(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@(?P<domain>[A-Za-z0-9.-]+)")
TEXT_PATTERNS = (
    ("private-path", re.compile(rb"/Users/|/home/")),
    ("git-remote", re.compile(rb"git@")),
    ("ssh-url", re.compile(rb"ssh://")),
)
HTTPS_URL_PATTERN = re.compile(rb"(?i)(?<![A-Za-z0-9])https://[^\s<>\"']+")
ALLOWED_HTTPS_GIT_REMOTE = "https://github.com/TaylorFinklea/chezmoi-base.git"
GITHUB_HOSTNAME = "github.com"
FORGE_HOST_DOT_EQUIVALENTS = str.maketrans({"。": ".", "．": ".", "｡": "."})
CHEZMOI_TARGET_ATTRIBUTE_PREFIXES = (
    "private_",
    "executable_",
    "readonly_",
    "encrypted_",
    "exact_",
    "create_",
    "modify_",
    "remove_",
    "symlink_",
    "empty_",
)
CHEZMOI_SCRIPT_STATE_PREFIXES = (
    "run_",
    "once_",
    "onchange_",
    "before_",
    "after_",
)


def decode_target_component(component):
    while True:
        if component.startswith("literal_"):
            return component[len("literal_") :].removesuffix(".tmpl")
        if component.startswith(CHEZMOI_SCRIPT_STATE_PREFIXES):
            return None
        for prefix in CHEZMOI_TARGET_ATTRIBUTE_PREFIXES:
            if component.startswith(prefix):
                component = component[len(prefix) :]
                break
        else:
            if component.startswith("dot_"):
                return "." + component[len("dot_") :].removesuffix(".tmpl")
            return component.removesuffix(".tmpl")


def path_rules(relative_path):
    rules = set()
    decoded_parts = tuple(
        decode_target_component(component) for component in relative_path.parts
    )
    if None in decoded_parts:
        return rules
    for component in decoded_parts:
        if component == ".hermes" or component.endswith("_dot_hermes"):
            rules.add("hermes-path")
    if decoded_parts and decoded_parts[-1] in FORBIDDEN_BASENAMES:
        rules.add("sensitive-basename")
    return rules


def normalize_forge_hostname(hostname):
    return (
        unquote(hostname)
        .translate(FORGE_HOST_DOT_EQUIVALENTS)
        .lower()
        .rstrip(".")
        .removeprefix("www.")
    )


def is_github_repository(hostname, path):
    normalized_path = posixpath.normpath(path)
    path_parts = tuple(part for part in normalized_path.split("/") if part)
    return normalize_forge_hostname(hostname) == GITHUB_HOSTNAME and len(path_parts) == 2


def is_non_ascii_https_git_remote(candidate):
    remainder = candidate[len(b"https://") :]
    path_start = min(
        (
            index
            for separator in (b"/", b"?", b"#")
            if (index := remainder.find(separator)) != -1
        ),
        default=len(remainder),
    )
    authority = remainder[:path_start]
    path = remainder[path_start:].split(b"?", 1)[0].split(b"#", 1)[0]
    decoded_path = unquote_to_bytes(path)
    hostname_with_port = unquote_to_bytes(authority).rsplit(b"@", 1)[-1]
    try:
        hostname = hostname_with_port.partition(b":")[0].decode("utf-8")
    except UnicodeDecodeError:
        hostname = ""
    is_github_url = is_github_repository(
        hostname, decoded_path.decode("utf-8", "ignore")
    )
    return any(byte > 127 for byte in candidate) and (
        decoded_path.rstrip(b"/").endswith(b".git") or is_github_url
    )


def https_url_rules(contents):
    rules = set()
    for match in HTTPS_URL_PATTERN.finditer(contents):
        raw_candidate = match.group()
        candidate = raw_candidate.rstrip(b".,;:!?)]}")
        allowed_remote = ALLOWED_HTTPS_GIT_REMOTE.encode()
        is_delimited = (
            contents[match.start() - 1 : match.start()] in (b"'", b'"', b"<")
            or contents[match.end() : match.end() + 1] in (b"'", b'"', b">")
        )
        is_allowed_remote = raw_candidate == allowed_remote and not is_delimited
        if candidate.startswith(allowed_remote) and not is_allowed_remote:
            rules.add("git-remote")
            continue
        if is_non_ascii_https_git_remote(candidate):
            rules.add("git-remote")
            continue
        try:
            url = candidate.decode("ascii")
            parsed = urlsplit(url)
        except (UnicodeDecodeError, ValueError):
            continue
        if parsed.username is not None or parsed.password is not None:
            rules.add("url-credentials")
        decoded_path = unquote(parsed.path)
        is_github_url = is_github_repository(parsed.hostname or "", decoded_path)
        is_git_remote = decoded_path.rstrip("/").endswith(".git") or is_github_url
        if is_git_remote and not is_allowed_remote:
            rules.add("git-remote")
    return rules


def text_rules(contents):
    rules = {name for name, pattern in CREDENTIAL_PATTERNS if pattern.search(contents)}
    for match in EMAIL_PATTERN.finditer(contents):
        domain = match.group("domain").rstrip(b".").decode("ascii").lower()
        if domain not in ALLOWED_EMAIL_DOMAINS:
            rules.add("private-email")
            break
    rules.update(name for name, pattern in TEXT_PATTERNS if pattern.search(contents))
    rules.update(https_url_rules(contents))
    return rules


def scan(root):
    violations = set()
    try:
        root_mode = root.lstat().st_mode
    except OSError:
        print(".: unreadable-root")
        return 1
    if stat.S_ISLNK(root_mode):
        print(".: symlink-root")
        return 1
    if not stat.S_ISDIR(root_mode):
        print(".: unreadable-root")
        return 1

    def record_walk_error(error):
        filename = getattr(error, "filename", None)
        if filename is None:
            relative_path = Path(".")
        else:
            error_path = Path(filename)
            if not error_path.is_absolute():
                error_path = root / error_path
            try:
                relative_path = error_path.relative_to(root)
            except ValueError:
                relative_path = Path(".")
        violations.add((str(relative_path), "unreadable-directory"))

    def scan_root_tests_symlinks():
        tests_path = root / "tests"
        try:
            tests_mode = tests_path.lstat().st_mode
        except FileNotFoundError:
            return
        except OSError:
            violations.add(("tests", "unreadable-path"))
            return
        if stat.S_ISLNK(tests_mode):
            violations.update(
                ("tests", rule) for rule in path_rules(Path("tests")) | {"symlink"}
            )
            return
        if not stat.S_ISDIR(tests_mode):
            return

        directories = [tests_path]
        while directories:
            directory_path = directories.pop()
            relative_directory = directory_path.relative_to(root)
            try:
                with os.scandir(directory_path) as entries:
                    names = sorted(entry.name for entry in entries)
            except OSError:
                violations.add((str(relative_directory), "unreadable-directory"))
                continue
            for name in names:
                path = directory_path / name
                relative_path = path.relative_to(root)
                try:
                    mode = path.lstat().st_mode
                except OSError:
                    violations.add((str(relative_path), "unreadable-path"))
                    continue
                if stat.S_ISLNK(mode):
                    violations.update(
                        (str(relative_path), rule)
                        for rule in path_rules(relative_path) | {"symlink"}
                    )
                elif stat.S_ISDIR(mode):
                    directories.append(path)

    scan_root_tests_symlinks()

    for directory, directory_names, file_names in os.walk(
        root, topdown=True, onerror=record_walk_error, followlinks=False
    ):
        directory_path = Path(directory)
        retained_directories = []
        for name in sorted(directory_names):
            path = directory_path / name
            relative_path = path.relative_to(root)
            try:
                if stat.S_ISLNK(path.lstat().st_mode):
                    violations.update(
                        (str(relative_path), rule)
                        for rule in path_rules(relative_path) | {"symlink"}
                    )
                    continue
            except OSError:
                violations.add((str(relative_path), "unreadable-path"))
                continue
            if name in {".git", ".DS_Store"} or (directory_path == root and name == "tests"):
                continue
            retained_directories.append(name)
        directory_names[:] = retained_directories
        for name in sorted(file_names):
            path = directory_path / name
            try:
                relative_path = path.relative_to(root)
                mode = path.lstat().st_mode
                if stat.S_ISLNK(mode):
                    violations.update(
                        (str(relative_path), rule)
                        for rule in path_rules(relative_path) | {"symlink"}
                    )
                    continue
                if name == ".DS_Store" or not stat.S_ISREG(mode):
                    continue
            except (OSError, ValueError):
                relative_path = path.relative_to(root) if path.is_absolute() else path
                violations.add((str(relative_path), "unreadable-path"))
                continue
            if path.resolve() == SCRIPT_PATH:
                continue

            rules = path_rules(relative_path)
            try:
                contents = path.read_bytes()
            except OSError:
                rules.add("unreadable-file")
                contents = b""
            rules.update(text_rules(contents))
            violations.update((str(relative_path), rule) for rule in rules)

    for relative_path, rule in sorted(violations):
        print(f"{relative_path}: {rule}")
    return 1 if violations else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Reject unsafe public chezmoi source content")
    parser.add_argument(
        "--root",
        type=Path,
        default=SCRIPT_PATH.parent.parent,
        help="repository root to scan",
    )
    args = parser.parse_args(argv)
    return scan(args.root)


if __name__ == "__main__":
    sys.exit(main())
