"""Codex lifecycle hook protocol for Codex Forge."""

from dataclasses import dataclass
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import tempfile
import time
from typing import Any, Mapping, Optional

from .policy import classify_tool
from .state import StateError, StateStore, transition

PLUGIN_VERSION = "0.1.0"
CONTINUATION_LIMIT = 1
APPROVAL_TTL_SECONDS = 30 * 60
INVALID_APPROVAL_REASON = (
    "Forge requires an exact approval command: approve <nonce> direct|ralph, "
    "revise <nonce>, or cancel <nonce>."
)


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


def _safe_root(root: Path) -> None:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    if root.is_symlink() or not root.is_dir():
        raise HookError("Forge data root must be a directory")


def _write_json(root: Path, name: str, payload: Mapping[str, Any]) -> None:
    _safe_root(root)
    target = root / name
    if target.exists() and (target.is_symlink() or not target.is_file()):
        raise HookError("Forge hook record must be a regular file")
    raw = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    temporary = root / ("." + name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(raw)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)


def _read_json(root: Path, name: str) -> Optional[dict[str, Any]]:
    target = root / name
    try:
        if target.is_symlink() or not target.is_file():
            return None
        with target.open("rb") as stream:
            payload = json.loads(stream.read(1024 * 1024 + 1))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


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


def _helper_command(command: Any) -> bool:
    if not isinstance(command, str):
        return False
    try:
        words = shlex.split(command, posix=True)
    except ValueError:
        return False
    if not words:
        return False
    for word in words:
        name = Path(word).name
        if name in {"codex-forge", "forge_hook.py"}:
            return word.endswith("codex-forge") or name == "forge_hook.py"
    return False


def _inject_helper_input(tool_input: Any, event: Mapping[str, Any], env: Any) -> Optional[dict[str, Any]]:
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    if not _helper_command(command):
        return None
    session_id = _session_id(event)
    if session_id is None:
        return None
    updated = deepcopy(tool_input)
    helper_env = dict(updated.get("env") or {})
    helper_env["CODEX_FORGE_SESSION_ID"] = session_id
    helper_env["CODEX_FORGE_DATA"] = str(_data_root(env))
    updated["env"] = helper_env
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
    expires = record.get("expires_at")
    try:
        if isinstance(expires, str):
            expires = float(expires)
        if float(expires) <= now:
            return False
    except (TypeError, ValueError):
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
    _write_json(_data_root(env), _hashed_name("heartbeat-", session_id), {
        "plugin_version": PLUGIN_VERSION,
        "session_id": session_id,
        "cwd": cwd,
        "timestamp": _now(env),
    })
    state = _load_state(event, env)
    return HookResult(_hook_output("SessionStart", additionalContext=_status_context(state)))


def _handle_pre_tool(event: Mapping[str, Any], env: Any) -> HookResult:
    state = _load_state(event, env)
    decision = classify_tool(event.get("tool_name", ""), event.get("tool_input", {}), state)
    if decision.deny:
        return HookResult(_hook_output(
            "PreToolUse", permissionDecision="deny",
            permissionDecisionReason=(
                "Forge shaping blocks writer tools until nonce approval."
                if "writer" in decision.reason or "writer" in event.get("tool_name", "").lower()
                else decision.reason
            ),
        ), blocked=True)
    updated = _inject_helper_input(event.get("tool_input"), event, env)
    if updated is not None:
        return HookResult(_hook_output("PreToolUse", updatedInput=updated))
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
    if action == "approve":
        next_state = transition(state, "approve_direct" if dispatcher == "direct" else "approve_ralph")
    elif action == "revise":
        next_state = transition(state, "revise")
    else:
        next_state = transition(state, "cancel")
    _store(env).replace(next_state)
    record = dict(record)
    record["used"] = True
    record["used_at"] = _now(env)
    _write_json(_data_root(env), _hashed_name("approval-", state.session_id), record)
    return HookResult({})


def _handle_stop(event: Mapping[str, Any], env: Any) -> HookResult:
    state = _load_state(event, env)
    if state is None or state.status in {"shaping", "frozen", "completed", "cancelled", "failed"}:
        return HookResult({})
    if state.status not in {"executing", "ralph_running"}:
        return HookResult({})
    name = _hashed_name("stop-", state.session_id)
    record = _read_json(_data_root(env), name) or {"count": 0}
    try:
        count = int(record.get("count", 0))
    except (TypeError, ValueError):
        count = CONTINUATION_LIMIT
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
