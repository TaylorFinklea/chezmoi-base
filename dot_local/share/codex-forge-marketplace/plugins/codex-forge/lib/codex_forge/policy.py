"""Fail-closed tool shaping for Codex Forge lifecycle hooks."""

from dataclasses import dataclass
import re
import shlex
from typing import Any, Optional


SHAPING_STATUSES = frozenset(("shaping", "frozen"))
WRITER_TOOLS = frozenset(("apply_patch", "Edit", "Write", "write_file", "file_write"))
READ_ONLY_COMMANDS = frozenset(("status", "log", "diff", "show", "rev-parse"))
SAFE_PROGRAMS = frozenset(("rg", "find", "ls", "pwd", "which", "command"))
INTERPRETERS = frozenset(("python", "python3", "node", "nodejs", "ruby", "perl"))
CONTROL_SYNTAX = re.compile(r"(?:[;&|<>`]|\$\(|\$\{|\n|\r)")


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


def _is_read_only_agent(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    mode = value.get("mode")
    agent_type = value.get("agent_type")
    if isinstance(mode, str) and mode.lower() in {"read", "readonly", "read-only", "scout", "explore"}:
        return True
    if isinstance(agent_type, str) and agent_type.lower() in {"scout", "reader", "explorer", "read-only"}:
        return True
    text = " ".join(str(value.get(key, "")) for key in ("prompt", "task", "description")).lower()
    if not text:
        return False
    writer_words = re.search(r"\b(write|edit|modify|mutat|implement|patch|create|delete|remove)\w*\b", text)
    scout_words = re.search(r"\b(read|scout|inspect|explore|analy[sz]e|report|find|search)\w*\b", text)
    return bool(scout_words and not writer_words)


def _shell_allowed(command: Any) -> bool:
    if not isinstance(command, str) or not command.strip() or CONTROL_SYNTAX.search(command):
        return False
    try:
        words = shlex.split(command, posix=True)
    except ValueError:
        return False
    if not words or any(not isinstance(word, str) or not word for word in words):
        return False
    program = words[0].rsplit("/", 1)[-1]
    if program == "git":
        if len(words) < 2 or words[1] not in READ_ONLY_COMMANDS:
            return False
        return not any(word in {"-c", "--exec-path"} for word in words[2:])
    if program in SAFE_PROGRAMS or program == "codex-forge":
        return True
    if program in {"pytest", "py.test"}:
        return "--collect-only" in words[1:]
    if program in INTERPRETERS:
        # Interpreter invocation is only useful here for non-running test discovery.
        return "--collect-only" in words
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


def classify_tool(tool_name: str, tool_input: Any, state: Any) -> PolicyDecision:
    """Classify a Codex tool without executing or expanding its shell input.

    A missing Forge state means the normal Codex policy remains authoritative.
    During shaping/frozen, only explicit read-only operations are accepted.
    """
    if state is None:
        return PolicyDecision(True, "no Forge state; defer to Codex policy")
    status = getattr(state, "status", None)
    if status not in SHAPING_STATUSES:
        # Approved execution is still not an OS sandbox; hooks only guard the
        # pre-approval workflow and leave normal Codex permissions in charge.
        return PolicyDecision(True, "Forge approval is active")
    if not isinstance(tool_name, str) or not tool_name:
        return PolicyDecision(False, "Forge shaping denies unknown tools.", False)
    canonical = tool_name.rsplit(".", 1)[-1]
    if canonical in WRITER_TOOLS or tool_name.lower() in {name.lower() for name in WRITER_TOOLS}:
        return PolicyDecision(False, "Forge shaping blocks writer tools until nonce approval.")
    if canonical in {"request_user_input", "RequestUserInput"}:
        return PolicyDecision(True, "user input is permitted during shaping")
    if canonical.lower() in {"browser", "computer", "web_search", "websearch"}:
        return PolicyDecision(True, "hosted tool is outside the Forge hook path")
    if canonical in {"Agent", "spawn_agent", "SpawnAgent", "agent"}:
        if _is_read_only_agent(tool_input):
            return PolicyDecision(True, "read-only scout agent is permitted during shaping")
        return PolicyDecision(False, "Forge shaping blocks writer or mixed-mode agents until nonce approval.")
    if canonical == "Bash" or tool_name in {"Bash", "shell", "Shell"}:
        if _shell_allowed(_tool_input_command(tool_input)):
            return PolicyDecision(True, "read-only shell command is permitted during shaping")
        return PolicyDecision(False, "Forge shaping blocks mutating or ambiguous shell commands.")
    # MCP tools are not assumed safe merely because their names are structured.
    if tool_name.startswith("mcp__") or tool_name.startswith("MCP") or "://" in tool_name:
        return PolicyDecision(False, "Forge shaping denies unknown MCP tools.", False)
    return PolicyDecision(False, "Forge shaping denies unknown tools.", False)


# Exposed for focused tests without making shell classification executable.
def is_read_only_shell(command: Any) -> bool:
    return _shell_allowed(command)
