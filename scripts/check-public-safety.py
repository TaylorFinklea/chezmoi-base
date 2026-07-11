#!/usr/bin/env python3
import argparse
import os
import re
import stat
import sys
from pathlib import Path


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


def path_rules(relative_path):
    rules = set()
    for component in relative_path.parts:
        if (
            component in {".hermes", "dot_hermes"}
            or component.endswith("_dot_hermes")
        ):
            rules.add("hermes-path")
    if relative_path.name in FORBIDDEN_BASENAMES:
        rules.add("sensitive-basename")
    return rules


def text_rules(contents):
    rules = {name for name, pattern in CREDENTIAL_PATTERNS if pattern.search(contents)}
    for match in EMAIL_PATTERN.finditer(contents):
        domain = match.group("domain").decode("ascii").lower()
        if domain not in ALLOWED_EMAIL_DOMAINS:
            rules.add("private-email")
            break
    rules.update(name for name, pattern in TEXT_PATTERNS if pattern.search(contents))
    return rules


def scan(root):
    violations = set()
    root = root.resolve()
    if not root.is_dir():
        print(".: unreadable-root")
        return 1

    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name not in {".git", ".DS_Store"}
            and not (directory_path == root and name == "tests")
        )
        for name in sorted(file_names):
            if name == ".DS_Store":
                continue
            path = directory_path / name
            try:
                if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
                    continue
                relative_path = path.relative_to(root)
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
