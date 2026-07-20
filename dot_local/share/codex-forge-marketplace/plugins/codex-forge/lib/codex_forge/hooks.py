"""Codex lifecycle hook protocol for Codex Forge."""

from dataclasses import dataclass
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import stat
import tempfile
import time
import tomllib
from typing import Any, Mapping, Optional

from .policy import PolicyDecision, _has_agent_environment, _tool_input_command, classify_tool
from .state import SecureJSONRecordStore, StateError, StateStore, transition

PLUGIN_VERSION = "0.1.0"
CONTINUATION_LIMIT = 1
APPROVAL_TTL_SECONDS = 30 * 60
MAX_ISSUED_AT_FUTURE_SECONDS = 5 * 60
INVALID_APPROVAL_REASON = (
    "Forge requires an exact approval command: approve <nonce> direct|ralph, "
    "revise <nonce>, or cancel <nonce>."
)
FORGE_SCOUT_INSTRUCTIONS = (
    "Explore only the relevant files, command output, and local conventions. Return\n"
    "concise findings with exact paths and evidence that help the parent decide or\n"
    "implement. Do not edit files, alter git state, run deployments, or infer facts\n"
    "that can be checked directly.\n"
)
FORGE_SCOUT_PROFILE = {
    "name": "forge-scout",
    "description": "Fast, read-only codebase and configuration reconnaissance.",
    "model": "gpt-5.6-luna",
    "model_reasoning_effort": "medium",
    "sandbox_mode": "read-only",
    "developer_instructions": FORGE_SCOUT_INSTRUCTIONS,
}
FORGE_SCOUT_PROFILE_MAX_BYTES = 64 * 1024
# Structured model input is bounded by the former stdin transport limit. The
# encoded cap is fixed so hooks can reject it before adding injected env.
# Keep the decoded limit below common execve argument ceilings while retaining
# the former bounded-input invariant for every structured control record.
STRUCTURED_INPUT_MAX_BYTES = 48 * 1024
STRUCTURED_ARG_MAX_CHARS = 4 * ((STRUCTURED_INPUT_MAX_BYTES + 2) // 3)
_STRUCTURED_ARG_RE = re.compile(r"[A-Za-z0-9_-]+")


@dataclass(frozen=True)
class HookResult:
    output: dict[str, Any]
    exit_code: int = 0
    blocked: bool = False

    def as_dict(self) -> dict[str, Any]:
        return self.output


class HookError(ValueError):
    pass


def _env_value(env: Any, key: str, default: Any = None) -> Any:
    if isinstance(env, Mapping):
        return env.get(key, default)
    return getattr(env, key, default)


def _now(env: Any) -> float:
    value = _env_value(env, "now", None)
    if callable(value):
        value = value()
    return float(value) if value is not None else time.time()


def _data_root(env: Any) -> Path:
    value = _env_value(env, "data_root", None)
    if value is None:
        value = _env_value(env, "CODEX_FORGE_DATA", None)
    if value is None:
        value = _env_value(env, "CODEX_FORGE_STATE_DIR", None)
    if value is None:
        value = os.environ.get("CODEX_FORGE_STATE_DIR", str(Path(tempfile.gettempdir()) / "codex-forge"))
    return Path(value)


def _store(env: Any) -> StateStore:
    store = _env_value(env, "store", None)
    if store is not None:
        return store
    return StateStore(_data_root(env), PLUGIN_VERSION)


def _session_id(event: Mapping[str, Any]) -> Optional[str]:
    value = event.get("session_id")
    return value if isinstance(value, str) and value else None


def _event_cwd(event: Mapping[str, Any]) -> Optional[Path]:
    value = event.get("cwd")
    if not isinstance(value, str) or not value:
        return None
    try:
        return Path(value).resolve(strict=True)
    except OSError:
        return None


def _hook_output(event_name: str, **fields: Any) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": event_name, **fields}}


def _block_prompt() -> HookResult:
    return HookResult({"decision": "block", "reason": INVALID_APPROVAL_REASON}, blocked=True)


def _hashed_name(prefix: str, session_id: str) -> str:
    return prefix + hashlib.sha256(session_id.encode("utf-8")).hexdigest() + ".json"


HOOK_RECORD_MAX_BYTES = 1024 * 1024


def _record_store(root: Path) -> SecureJSONRecordStore:
    return SecureJSONRecordStore(root, max_bytes=HOOK_RECORD_MAX_BYTES)


def _finite_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _validate_hook_record(name: str, payload: Mapping[str, Any]) -> None:
    if not isinstance(payload, Mapping):
        raise HookError("Forge hook record is malformed or inaccessible")
    if name.startswith("heartbeat-"):
        required = {"plugin_version", "session_id", "cwd", "timestamp"}
        if set(payload) != required:
            raise HookError("Forge heartbeat record is malformed")
        if (payload["plugin_version"] != PLUGIN_VERSION or
                not isinstance(payload["session_id"], str) or not payload["session_id"] or
                not isinstance(payload["cwd"], str) or not payload["cwd"] or
                not _finite_number(payload["timestamp"])):
            raise HookError("Forge heartbeat record is malformed")
        return
    if name.startswith("approval-"):
        required = {"nonce", "session_id", "cwd", "repo", "issued_at", "expires_at", "used"}
        allowed = required | {"used_at"}
        if not required <= set(payload) or set(payload) - allowed:
            raise HookError("Forge approval record is malformed")
        if (not isinstance(payload["nonce"], str) or not payload["nonce"] or
                not isinstance(payload["session_id"], str) or not payload["session_id"] or
                not isinstance(payload["cwd"], str) or not payload["cwd"] or
                (payload["repo"] is not None and not isinstance(payload["repo"], str)) or
                not _finite_number(payload["issued_at"]) or
                not _finite_number(payload["expires_at"]) or
                type(payload["used"]) is not bool):
            raise HookError("Forge approval record is malformed")
        if payload["expires_at"] - payload["issued_at"] != APPROVAL_TTL_SECONDS:
            raise HookError("Forge approval record is malformed")
        if "used_at" in payload and not _finite_number(payload["used_at"]):
            raise HookError("Forge approval record is malformed")
        return
    if name.startswith("stop-"):
        if set(payload) != {"count"} or type(payload["count"]) is not int or not 0 <= payload["count"] <= CONTINUATION_LIMIT:
            raise HookError("Forge Stop record is malformed")


def _write_json(root: Path, name: str, payload: Mapping[str, Any]) -> None:
    _validate_hook_record(name, payload)
    try:
        _record_store(root).write(name, payload)
    except (StateError, OSError, TypeError) as exc:
        raise HookError("Forge hook record could not be persisted") from exc


def _read_json(root: Path, name: str) -> Optional[dict[str, Any]]:
    try:
        payload = _record_store(root).read(name)
    except (StateError, OSError) as exc:
        raise HookError("Forge hook record is malformed or inaccessible") from exc
    if payload is not None:
        _validate_hook_record(name, payload)
    return payload


def _status_context(state: Any) -> str:
    if state is None:
        return "Codex Forge: shaping session ready."
    return f"Codex Forge: session {state.session_id} is {state.status}."


def _load_state(event: Mapping[str, Any], env: Any) -> Any:
    session_id = _session_id(event)
    if session_id is None:
        return None
    try:
        return _store(env).load(session_id)
    except (StateError, ValueError, OSError) as exc:
        raise HookError("Forge state is malformed or inaccessible") from exc


def _helper_path(env: Any) -> Optional[Path]:
    value = _env_value(env, "PLUGIN_ROOT", None)
    if not isinstance(value, str) or not value:
        return None
    root_path = Path(value)
    try:
        root_info = root_path.lstat()
        root = root_path.resolve(strict=True)
        bin_dir = root / "bin"
        bin_info = bin_dir.lstat()
        helper = bin_dir / "codex-forge"
        helper_info = helper.lstat()
    except OSError:
        return None
    if (root != root_path or stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode) or
            stat.S_ISLNK(bin_info.st_mode) or not stat.S_ISDIR(bin_info.st_mode) or
            stat.S_ISLNK(helper_info.st_mode) or not stat.S_ISREG(helper_info.st_mode) or
            not (helper_info.st_mode & stat.S_IXUSR)):
        return None
    return helper


_HELPER_SUBCOMMANDS = frozenset(("begin", "question", "freeze", "status", "complete", "fail"))
_HELPER_PAYLOAD_SUBCOMMANDS = frozenset(("question", "freeze", "fail"))


def _valid_structured_argument(value: Any) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= STRUCTURED_ARG_MAX_CHARS
            and _STRUCTURED_ARG_RE.fullmatch(value) is not None)


def _helper_command(command: Any, env: Any) -> bool:
    """Recognize only the installed helper and its exact argument grammar."""
    if not isinstance(command, str):
        return False
    helper = _helper_path(env)
    if helper is None:
        return False
    try:
        words = shlex.split(command, posix=True)
    except ValueError:
        return False
    if len(words) < 2 or words[0] != str(helper) or words[1] not in _HELPER_SUBCOMMANDS:
        return False
    if command != " ".join(words):
        return False
    subcommand = words[1]
    if subcommand in _HELPER_PAYLOAD_SUBCOMMANDS:
        return len(words) == 3 and _valid_structured_argument(words[2])
    return len(words) == 2


def _helper_input(tool_input: Any, env: Any) -> bool:
    return isinstance(tool_input, dict) and set(tool_input) == {"command"} and _helper_command(tool_input.get("command"), env)


def _profile_path(env: Any) -> Path:
    home = _env_value(env, "home", None)
    if home is None:
        home = _env_value(env, "HOME", None)
    if home is None:
        home = os.environ.get("HOME")
    if not isinstance(home, str) or not home:
        raise HookError("Forge scout profile is missing or invalid")
    return Path(home) / ".codex" / "agents" / "forge-scout.toml"


def _verify_forge_scout_profile(env: Any) -> None:
    path = _profile_path(env)
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise HookError("Forge scout profile is missing or invalid")
        if info.st_size > FORGE_SCOUT_PROFILE_MAX_BYTES:
            raise HookError("Forge scout profile is missing or invalid")
        payload = tomllib.loads(path.read_bytes().decode("utf-8"))
    except HookError:
        raise
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, TypeError, ValueError) as exc:
        raise HookError("Forge scout profile is missing or invalid") from exc
    if payload != FORGE_SCOUT_PROFILE:
        raise HookError("Forge scout profile is missing or invalid")


def _inject_helper_input(tool_input: Any, event: Mapping[str, Any], env: Any) -> Optional[dict[str, Any]]:
    if not _helper_input(tool_input, env):
        return None
    command = tool_input["command"]
    session_id = _session_id(event)
    if session_id is None:
        return None
    updated = deepcopy(tool_input)
    updated["env"] = {
        "CODEX_FORGE_SESSION_ID": session_id,
        "CODEX_FORGE_DATA": str(_data_root(env)),
    }
    return updated


def _repo_token(state: Any) -> Optional[str]:
    repo = getattr(state, "repo", None)
    if repo is None:
        return None
    return str(getattr(repo, "root", ""))


def _approval_record(event: Mapping[str, Any], env: Any) -> Optional[dict[str, Any]]:
    session_id = _session_id(event)
    if session_id is None:
        return None
    return _read_json(_data_root(env), _hashed_name("approval-", session_id))


def _approval_matches(record: Mapping[str, Any], state: Any, event: Mapping[str, Any], now: float) -> bool:
    if record.get("used") is True or record.get("session_id") != state.session_id:
        return False
    cwd = _event_cwd(event)
    if cwd is None or cwd != state.cwd:
        return False
    if record.get("cwd") != str(state.cwd):
        return False
    repo = _repo_token(state)
    if record.get("repo") != repo:
        return False
    issued = record.get("issued_at")
    expires = record.get("expires_at")
    if not _finite_number(issued) or not _finite_number(expires) or not _finite_number(now):
        return False
    if expires - issued != APPROVAL_TTL_SECONDS:
        return False
    if issued > now + MAX_ISSUED_AT_FUTURE_SECONDS:
        return False
    if expires <= now:
        return False
    return True


def _prompt(event: Mapping[str, Any]) -> Optional[str]:
    value = event.get("prompt")
    if value is None:
        value = event.get("user_prompt")
    return value if isinstance(value, str) else None


def _handle_session_start(event: Mapping[str, Any], env: Any) -> HookResult:
    session_id = _session_id(event)
    cwd = event.get("cwd")
    if session_id is None or not isinstance(cwd, str):
        raise HookError("SessionStart requires session_id and cwd")
    _verify_forge_scout_profile(env)
    heartbeat_name = _hashed_name("heartbeat-", session_id)
    _read_json(_data_root(env), heartbeat_name)
    _write_json(_data_root(env), heartbeat_name, {
        "plugin_version": PLUGIN_VERSION,
        "session_id": session_id,
        "cwd": cwd,
        "timestamp": _now(env),
    })
    state = _load_state(event, env)
    return HookResult(_hook_output("SessionStart", additionalContext=_status_context(state)))


def _handle_pre_tool(event: Mapping[str, Any], env: Any) -> HookResult:
    state = _load_state(event, env)
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input")
    if tool_name == "Bash" and _helper_command(_tool_input_command(tool_input), env):
        if _helper_input(tool_input, env):
            decision = PolicyDecision(True, "managed Forge control CLI is permitted during shaping")
        else:
            decision = PolicyDecision(False, "Forge control CLI requires its exact canonical command input.")
    elif tool_name == "Bash" and _has_agent_environment(tool_input):
        decision = PolicyDecision(False, "Forge shaping blocks agent-supplied Bash execution environment.")
    else:
        decision = classify_tool(tool_name, tool_input, state)
    if decision.allowed and tool_name == "Bash":
        updated = _inject_helper_input(event.get("tool_input"), event, env)
        if updated is not None:
            return HookResult(_hook_output("PreToolUse", updatedInput=updated))
    if decision.deny:
        tool_name_lower = tool_name.lower() if isinstance(tool_name, str) else ""
        return HookResult(_hook_output(
            "PreToolUse", permissionDecision="deny",
            permissionDecisionReason=(
                "Forge shaping blocks writer tools until nonce approval."
                if "writer" in decision.reason or "writer" in tool_name_lower
                else decision.reason
            ),
        ), blocked=True)
    if tool_name == "Agent":
        try:
            _verify_forge_scout_profile(env)
        except HookError as exc:
            return HookResult(_hook_output(
                "PreToolUse", permissionDecision="deny", permissionDecisionReason=str(exc)
            ), exit_code=2, blocked=True)
    return HookResult({})


def _handle_prompt(event: Mapping[str, Any], env: Any) -> HookResult:
    state = _load_state(event, env)
    if state is None or state.status != "frozen":
        return HookResult({})
    prompt = _prompt(event)
    if prompt is None:
        return _block_prompt()
    match = re.fullmatch(r"(approve|revise|cancel) ([A-Za-z0-9_-]+)(?: (direct|ralph))?", prompt)
    if match is None:
        return _block_prompt()
    action, nonce, dispatcher = match.groups()
    record = _approval_record(event, env)
    if record is None or record.get("nonce") != nonce or not _approval_matches(record, state, event, _now(env)):
        return _block_prompt()
    if action == "approve" and dispatcher is None:
        return _block_prompt()
    if action != "approve" and dispatcher is not None:
        return _block_prompt()
    record = dict(record)
    record["used"] = True
    record["used_at"] = _now(env)
    _write_json(_data_root(env), _hashed_name("approval-", state.session_id), record)
    try:
        if action == "approve":
            next_state = transition(state, "approve_direct" if dispatcher == "direct" else "approve_ralph")
        elif action == "revise":
            next_state = transition(state, "revise")
        else:
            next_state = transition(state, "cancel")
        _store(env).replace(next_state)
    except Exception as exc:
        raise HookError("Forge approval failed; nonce consumed and shaping remains locked") from exc
    return HookResult({})


def _handle_stop(event: Mapping[str, Any], env: Any) -> HookResult:
    state = _load_state(event, env)
    if state is None or state.status in {"shaping", "frozen", "completed", "cancelled", "failed"}:
        return HookResult({})
    if state.status not in {"executing", "ralph_running"}:
        return HookResult({})
    name = _hashed_name("stop-", state.session_id)
    record = _read_json(_data_root(env), name)
    count = 0 if record is None else record["count"]
    if count >= CONTINUATION_LIMIT:
        return HookResult({})
    _write_json(_data_root(env), name, {"count": count + 1})
    return HookResult({"decision": "block", "reason": "Forge execution is incomplete; continue with the remaining work."}, blocked=True)


def handle_hook(event: Mapping[str, Any], env: Any = None) -> HookResult:
    """Handle one documented Codex hook object and return one JSON response."""
    if env is None:
        env = os.environ
    if not isinstance(event, Mapping):
        raise HookError("hook input must be an object")
    event_name = event.get("hook_event_name")
    if not isinstance(event_name, str):
        raise HookError("hook_event_name is required")
    try:
        if event_name == "SessionStart":
            return _handle_session_start(event, env)
        if event_name == "PreToolUse":
            return _handle_pre_tool(event, env)
        if event_name == "UserPromptSubmit":
            return _handle_prompt(event, env)
        if event_name == "PostToolUse":
            return HookResult({})
        if event_name == "Stop":
            return _handle_stop(event, env)
        raise HookError(f"unsupported hook event: {event_name}")
    except HookError as exc:
        return HookResult({"decision": "block", "reason": str(exc)}, exit_code=2, blocked=True)
