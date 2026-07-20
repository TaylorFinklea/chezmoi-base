"""Fail-closed tool shaping for Codex Forge lifecycle hooks."""

from dataclasses import dataclass
import re
import shlex
from typing import Any, Optional


SHAPING_STATUSES = frozenset(("shaping", "frozen"))
WRITER_TOOLS = frozenset(("apply_patch", "Edit", "Write", "write_file", "file_write"))
CONTROL_SYNTAX = re.compile(r"(?:[;&|<>`]|\$\(|\$\{|\n|\r)")
MCP_NAMESPACE = re.compile(r"(?i)(?:^|[._:/\\-])mcp(?:$|[._:/\\-])")
BASH_ENVIRONMENT_FIELDS = frozenset((
    "cwd", "workdir", "working_directory", "shell", "executable", "timeout", "timeout_ms",
    "sandbox_permissions", "additional_permissions", "run_in_background", "environment",
))


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""
    recognized: bool = True

    @property
    def deny(self) -> bool:
        return not self.allowed

    @property
    def decision(self) -> str:
        return "allow" if self.allowed else "deny"

    @property
    def permission_decision(self) -> str:
        return "allow" if self.allowed else "deny"


def _is_forge_scout(value: Any) -> bool:
    """Accept only the exact managed profile invocation, without prompt filtering."""
    if not isinstance(value, dict):
        return False
    if set(value) - {"agent_type", "prompt"}:
        return False
    if value.get("agent_type") != "forge-scout":
        return False
    return "prompt" not in value or isinstance(value["prompt"], str)


def _safe_git(words: list[str]) -> bool:
    if len(words) < 2:
        return False
    command = words[1]
    args = words[2:]
    requires_no_textconv = command in {"log", "diff", "show"}
    if command == "status":
        options = {"--short", "--branch", "--porcelain", "--untracked-files", "--ignored", "--ahead-behind"}
    elif command == "log":
        options = {"--oneline", "--decorate", "--all", "--graph", "--stat", "--patch", "--no-patch", "--follow", "--no-textconv"}
    elif command == "diff":
        options = {"--stat", "--name-only", "--name-status", "--check", "--cached", "--staged", "--no-ext-diff", "--no-renames", "--no-textconv"}
    elif command == "show":
        options = {"--stat", "--name-only", "--name-status", "--format=short", "--no-patch", "--patch", "--no-textconv"}
    elif command == "rev-parse":
        options = {"--show-toplevel", "--show-prefix", "--git-dir", "--is-inside-work-tree", "--is-inside-git-dir", "--verify"}
    else:
        return False
    after_separator = False
    saw_no_textconv = False
    for arg in args:
        if arg == "--":
            after_separator = True
            continue
        if after_separator:
            continue
        if arg in options:
            saw_no_textconv = saw_no_textconv or arg == "--no-textconv"
            continue
        if command == "log" and (re.fullmatch(r"-[0-9]+", arg) or re.fullmatch(r"--(?:max-count|since|until)=.+", arg)):
            continue
        if command == "rev-parse" and arg.startswith("--verify="):
            continue
        if arg.startswith("-"):
            return False
    return not requires_no_textconv or saw_no_textconv


def _safe_ls(words: list[str]) -> bool:
    short_options = set("1ACFHLRSTUacdfghiklmnopqrstux")
    long_options = {
        "--all", "--almost-all", "--author", "--classify", "--directory", "--full-time",
        "--group-directories-first", "--human-readable", "--inode", "--long", "--size",
        "--time-style=long-iso", "--color=never",
    }
    for arg in words[1:]:
        if arg == "--":
            continue
        if arg.startswith("--"):
            if arg not in long_options:
                return False
        elif arg.startswith("-"):
            if not arg or any(char not in short_options for char in arg[1:]):
                return False
    return True


def _safe_rg(words: list[str]) -> bool:
    no_value = {"-n", "--line-number", "-l", "--files-with-matches", "-i", "--ignore-case", "-w", "--word-regexp", "-F", "--fixed-strings", "--hidden", "--no-ignore", "--files", "--count", "--stats"}
    value_prefixes = ("--glob=", "--type=", "--max-count=")
    value_options = {"-g", "--glob", "-t", "--type", "--max-count"}
    expecting = False
    for arg in words[1:]:
        if expecting:
            if not arg or arg.startswith("-"):
                return False
            expecting = False
            continue
        if arg in no_value or any(arg.startswith(prefix) for prefix in value_prefixes):
            continue
        if arg in value_options:
            expecting = True
            continue
        if arg.startswith("-"):
            return False
    return not expecting


def _safe_find(words: list[str]) -> bool:
    if len(words) < 2:
        return False
    predicates = {
        "-name": 1, "-iname": 1, "-path": 1, "-ipath": 1, "-type": 1, "-size": 1,
        "-mtime": 1, "-atime": 1, "-ctime": 1, "-user": 1, "-group": 1,
        "-maxdepth": 1, "-mindepth": 1, "-print": 0, "-print0": 0, "-ls": 0,
        "-prune": 0, "-readable": 0, "-empty": 0, "-true": 0, "-false": 0,
        "!": 0, "-not": 0, "-a": 0, "-and": 0, "-o": 0, "-or": 0,
        "(": 0, ")": 0, "-H": 0, "-L": 0, "-P": 0, "-xdev": 0, "-depth": 0,
    }
    index = 1
    while index < len(words) and not words[index].startswith("-") and words[index] not in {"!", "(", ")"}:
        index += 1
    if index == 1:
        return False
    while index < len(words):
        arg = words[index]
        if arg not in predicates:
            return False
        needed = predicates[arg]
        if index + needed >= len(words) + 0:
            return False
        for offset in range(1, needed + 1):
            operand = words[index + offset]
            if not operand or operand.startswith("-"):
                return False
        index += needed + 1
    return True


def _shell_allowed(command: Any) -> bool:
    if not isinstance(command, str) or not command.strip() or CONTROL_SYNTAX.search(command):
        return False
    try:
        words = shlex.split(command, posix=True)
    except ValueError:
        return False
    if not words or any(not isinstance(word, str) or not word or word.startswith("#") for word in words):
        return False
    program = words[0]
    if "/" in program or "\\" in program:
        return False
    if program == "git":
        return _safe_git(words)
    if program == "rg":
        return _safe_rg(words)
    if program == "find":
        return _safe_find(words)
    if program == "ls":
        return _safe_ls(words)
    if program == "pwd":
        return len(words) == 1
    if program == "which":
        return len(words) > 1 and all(re.fullmatch(r"[A-Za-z0-9_.+-]+", word) for word in words[1:])
    return False


def _tool_input_command(tool_input: Any) -> Optional[str]:
    if isinstance(tool_input, str):
        return tool_input
    if not isinstance(tool_input, dict):
        return None
    for key in ("command", "cmd", "shell_command"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return None


def _has_agent_environment(tool_input: Any) -> bool:
    if not isinstance(tool_input, dict):
        return False
    if BASH_ENVIRONMENT_FIELDS.intersection(tool_input):
        return True
    if "env" not in tool_input:
        return False
    value = tool_input["env"]
    return value not in (None, "", {}, [])


def _is_mcp_namespace(tool_name: str) -> bool:
    return bool(MCP_NAMESPACE.search(tool_name)) or tool_name.lower().startswith("mcp")


def classify_tool(tool_name: str, tool_input: Any, state: Any) -> PolicyDecision:
    """Classify a Codex tool without executing or expanding its shell input."""
    if state is None:
        return PolicyDecision(True, "no Forge state; defer to Codex policy")
    status = getattr(state, "status", None)
    if status not in {"shaping", "frozen"}:
        return PolicyDecision(True, "Forge approval is active")
    # Namespace rejection deliberately precedes every local-tool dispatch.
    if isinstance(tool_name, str) and _is_mcp_namespace(tool_name):
        return PolicyDecision(False, "Forge shaping denies unknown MCP tools.", False)
    if not isinstance(tool_name, str) or not tool_name:
        return PolicyDecision(False, "Forge shaping denies unknown tools.", False)
    if tool_name in WRITER_TOOLS:
        return PolicyDecision(False, "Forge shaping blocks writer tools until nonce approval.")
    if tool_name == "request_user_input":
        return PolicyDecision(True, "user input is permitted during shaping")
    if tool_name in {"browser", "computer", "web_search", "websearch"}:
        return PolicyDecision(True, "hosted tool is outside the Forge hook path")
    if tool_name == "Agent":
        if _is_forge_scout(tool_input):
            return PolicyDecision(True, "managed forge-scout agent is permitted during shaping")
        return PolicyDecision(False, "Forge shaping blocks non-managed or mixed-mode agents until nonce approval.")
    if tool_name == "Bash":
        if _has_agent_environment(tool_input):
            return PolicyDecision(False, "Forge shaping blocks agent-supplied Bash execution environment.")
        if _shell_allowed(_tool_input_command(tool_input)):
            return PolicyDecision(True, "read-only shell command is permitted during shaping")
        return PolicyDecision(False, "Forge shaping blocks mutating or ambiguous shell commands.")
    return PolicyDecision(False, "Forge shaping denies unknown tools.", False)


def is_read_only_shell(command: Any) -> bool:
    return _shell_allowed(command)
