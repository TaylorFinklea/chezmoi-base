"""Guarded, hook-bound Codex Forge shaping control CLI."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from typing import Any, Mapping

from .brief import brief_digest, canonical_brief_bytes, parse_brief
from .hooks import APPROVAL_TTL_SECONDS, PLUGIN_VERSION, _hashed_name
from .state import RepoIdentity, SecureJSONRecordStore, StateError, StateStore, ForgeState, transition

HEARTBEAT_MAX_AGE_SECONDS = 5 * 60
MAX_STDIN_BYTES = 2 * 1024 * 1024
MAX_QUESTION_BYTES = 4096
MAX_FAILURE_BYTES = 2048
MAX_QUESTIONS = 5


class CLIError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _env() -> tuple[str, Path]:
    session = os.environ.get("CODEX_FORGE_SESSION_ID")
    data = os.environ.get("CODEX_FORGE_DATA")
    if not session or not data:
        raise CLIError("missing_injected_environment", "hook-injected Forge session and data are required")
    if any(c in session for c in ("/", "\\", "\x00")) or session in {".", ".."}:
        raise CLIError("invalid_injected_environment", "hook-injected session is invalid")
    root = Path(data)
    if not root.is_absolute():
        raise CLIError("invalid_injected_environment", "hook-injected data path must be absolute")
    return session, root


def _store(root: Path) -> StateStore:
    return StateStore(root, PLUGIN_VERSION)


def _record_store(root: Path) -> SecureJSONRecordStore:
    return SecureJSONRecordStore(root, max_bytes=MAX_STDIN_BYTES)


def _record(root: Path, prefix: str, session: str) -> str:
    return _hashed_name(prefix, session)


def _read_record(root: Path, prefix: str, session: str) -> dict[str, Any] | None:
    try:
        return _record_store(root).read(_record(root, prefix, session))
    except (StateError, OSError) as exc:
        raise CLIError("corrupt_state", "Forge control state is malformed or inaccessible") from exc


def _write_record(root: Path, prefix: str, session: str, payload: Mapping[str, Any], *, exclusive: bool = False) -> None:
    try:
        _record_store(root).write(_record(root, prefix, session), payload, exclusive=exclusive)
    except (StateError, OSError, TypeError) as exc:
        raise CLIError("state_write_failed", "Forge control state could not be persisted") from exc


def _now() -> float:
    return time.time()


def _current_context() -> tuple[Path, RepoIdentity | None]:
    try:
        cwd = Path.cwd().resolve(strict=True)
    except OSError as exc:
        raise CLIError("invalid_cwd", "current working directory is inaccessible") from exc
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel", "--git-dir", "HEAD"],
            cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, check=True, timeout=5,
        )
        lines = result.stdout.splitlines()
        if len(lines) != 3:
            return cwd, None
        root = Path(lines[0]).resolve(strict=True)
        git_dir = Path(lines[1])
        if not git_dir.is_absolute():
            git_dir = (cwd / git_dir).resolve(strict=True)
        else:
            git_dir = git_dir.resolve(strict=True)
        return cwd, RepoIdentity(root, lines[2], git_dir)
    except (OSError, subprocess.SubprocessError, ValueError):
        return cwd, None


def _heartbeat_is_current(root: Path, session: str, cwd: Path, now: float) -> None:
    record = _read_record(root, "heartbeat-", session)
    if not isinstance(record, dict) or set(record) != {"plugin_version", "session_id", "cwd", "timestamp"}:
        raise CLIError("heartbeat_required", "current Forge heartbeat is required")
    timestamp = record["timestamp"]
    if (record["plugin_version"] != PLUGIN_VERSION or record["session_id"] != session or
            not isinstance(record["cwd"], str) or not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool)):
        raise CLIError("heartbeat_required", "current Forge heartbeat is required")
    try:
        beat_cwd = Path(record["cwd"]).resolve(strict=True)
    except OSError as exc:
        raise CLIError("heartbeat_required", "current Forge heartbeat is required") from exc
    if beat_cwd != cwd or timestamp > now + 5 or now - timestamp > HEARTBEAT_MAX_AGE_SECONDS:
        raise CLIError("heartbeat_required", "current Forge heartbeat is required")


def _binding_matches(state: ForgeState, cwd: Path, repo: RepoIdentity | None) -> bool:
    if cwd != state.cwd:
        return False
    if state.repo is None:
        return repo is None
    return repo is not None and repo.root == state.repo.root and repo.git_dir == state.repo.git_dir


def _load_bound(root: Path, session: str, *, heartbeat: bool = True) -> tuple[ForgeState, Path, RepoIdentity | None]:
    cwd, repo = _current_context()
    if heartbeat:
        _heartbeat_is_current(root, session, cwd, _now())
    try:
        state = _store(root).load(session)
    except (StateError, ValueError, OSError) as exc:
        raise CLIError("state_unavailable", "Forge session state is malformed or unavailable") from exc
    if state is None:
        raise CLIError("not_started", "Forge session has not begun")
    if not _binding_matches(state, cwd, repo):
        raise CLIError("binding_mismatch", "current cwd or repository does not match the Forge session")
    return state, cwd, repo


def _stdin_json() -> Any:
    raw = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
    if len(raw) > MAX_STDIN_BYTES:
        raise CLIError("input_too_large", "stdin JSON exceeds the Forge input limit")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CLIError("invalid_json", "stdin must contain exactly one valid JSON value") from exc
    if not isinstance(value, dict):
        raise CLIError("invalid_json", "stdin must contain one JSON object")
    return value


def _metadata(root: Path, session: str) -> dict[str, Any]:
    record = _read_record(root, "meta-", session)
    if record is None:
        return {"question_count": 0, "failure_reason": None}
    if (set(record) != {"question_count", "failure_reason"} or
            type(record["question_count"]) is not int or not 0 <= record["question_count"] or
            record["failure_reason"] is not None and not isinstance(record["failure_reason"], str)):
        raise CLIError("corrupt_state", "Forge control state is malformed or inaccessible")
    return record


def _summary(state: ForgeState, root: Path, session: str) -> dict[str, Any]:
    meta = _metadata(root, session)
    brief = _read_record(root, "brief-", session)
    return {"ok": True, "status": state.status, "question_count": meta["question_count"],
            "brief_digest": brief.get("digest") if isinstance(brief, dict) else None,
            "failure_reason": meta["failure_reason"]}


def begin() -> dict[str, Any]:
    session, root = _env()
    cwd, repo = _current_context()
    _heartbeat_is_current(root, session, cwd, _now())
    store = _store(root)
    try:
        state = store.load(session)
    except (StateError, ValueError, OSError) as exc:
        raise CLIError("state_unavailable", "Forge session state is malformed or unavailable") from exc
    if state is not None:
        if state.status == "approved_direct" and _binding_matches(state, cwd, repo):
            try:
                next_state = transition(state, "begin")
                store.replace(next_state)
            except (StateError, ValueError, OSError) as exc:
                raise CLIError("state_write_failed", "Forge session state could not be advanced") from exc
            return {"ok": True, "status": next_state.status}
        raise CLIError("duplicate_begin", "Forge session has already begun")
    try:
        state = store.create(session, cwd, repo)
        _write_record(root, "meta-", session, {"question_count": 0, "failure_reason": None}, exclusive=True)
    except (StateError, ValueError, OSError) as exc:
        raise CLIError("begin_failed", "Forge session could not be created") from exc
    return {"ok": True, "status": state.status}


def question() -> dict[str, Any]:
    session, root = _env()
    state, _, _ = _load_bound(root, session)
    if state.status != "shaping":
        raise CLIError("invalid_transition", "questions are allowed only while shaping")
    payload = _stdin_json()
    if set(payload) != {"question"} or not isinstance(payload["question"], str) or not payload["question"].strip():
        raise CLIError("invalid_question", "question stdin must be {\"question\": \"...\"}")
    question_text = payload["question"]
    if len(question_text.encode("utf-8")) > MAX_QUESTION_BYTES or any(ord(c) < 32 or ord(c) == 127 for c in question_text):
        raise CLIError("invalid_question", "question is empty, oversized, or contains control characters")
    meta = _metadata(root, session)
    meta["question_count"] += 1
    _write_record(root, "meta-", session, meta)
    if meta["question_count"] > MAX_QUESTIONS:
        raise CLIError("question_limit", "Forge allows at most five shaping questions")
    return {"ok": True, "attempt": meta["question_count"]}


def freeze() -> dict[str, Any]:
    session, root = _env()
    state, cwd, repo = _load_bound(root, session)
    if state.status != "shaping":
        raise CLIError("invalid_transition", "only a shaping session can be frozen")
    raw = _stdin_json()
    try:
        brief = parse_brief(raw)
    except ValueError as exc:
        raise CLIError("invalid_brief", str(exc)) from exc
    digest = brief_digest(brief)
    if _read_record(root, "brief-", session) is not None or _read_record(root, "approval-", session) is not None:
        raise CLIError("already_frozen", "an immutable brief already exists")
    issued = _now()
    nonce = secrets.token_hex(32)
    approval = {"nonce": nonce, "session_id": session, "cwd": str(cwd),
                "repo": str(state.repo.root) if state.repo is not None else None,
                "issued_at": issued, "expires_at": issued + APPROVAL_TTL_SECONDS, "used": False}
    try:
        _write_record(root, "brief-", session, {"digest": digest, "brief": json.loads(canonical_brief_bytes(brief))}, exclusive=True)
        _write_record(root, "approval-", session, approval, exclusive=True)
        frozen = transition(state, "freeze")
        _store(root).replace(frozen)
    except (CLIError, StateError, ValueError, OSError) as exc:
        raise CLIError("freeze_failed", "immutable brief and approval could not be persisted") from exc
    return {"ok": True, "status": "frozen", "brief_digest": digest, "nonce": nonce,
            "expires_at": approval["expires_at"]}


def status() -> dict[str, Any]:
    session, root = _env()
    state, _, _ = _load_bound(root, session, heartbeat=False)
    return _summary(state, root, session)


def complete() -> dict[str, Any]:
    session, root = _env()
    state, _, _ = _load_bound(root, session)
    if state.status not in {"executing", "ralph_running"}:
        raise CLIError("invalid_transition", "completion requires an executing Forge session")
    payload = _stdin_json()
    if set(payload) != {"verification"} or payload["verification"] != "passed":
        raise CLIError("verification_not_terminal", "completion requires terminal verification: passed")
    next_state = transition(state, "complete")
    try:
        _store(root).replace(next_state)
    except (StateError, ValueError, OSError) as exc:
        raise CLIError("state_write_failed", "Forge completion could not be persisted") from exc
    return {"ok": True, "status": next_state.status}


def fail() -> dict[str, Any]:
    session, root = _env()
    state, _, _ = _load_bound(root, session)
    if state.status in {"completed", "cancelled", "failed"}:
        raise CLIError("invalid_transition", "terminal Forge sessions cannot fail")
    payload = _stdin_json()
    if set(payload) != {"reason"} or not isinstance(payload["reason"], str):
        raise CLIError("invalid_failure", "failure stdin must be {\"reason\": \"...\"}")
    reason = payload["reason"].strip()
    if not reason or len(reason.encode("utf-8")) > MAX_FAILURE_BYTES or any(ord(c) < 32 or ord(c) == 127 for c in reason):
        raise CLIError("invalid_failure", "failure reason is empty, oversized, or contains control characters")
    try:
        _write_record(root, "meta-", session, {**_metadata(root, session), "failure_reason": reason})
        next_state = transition(state, "fail")
        _store(root).replace(next_state)
    except (CLIError, StateError, ValueError, OSError) as exc:
        raise CLIError("state_write_failed", "Forge failure could not be persisted") from exc
    return {"ok": True, "status": next_state.status}


def dispatch(command: str) -> dict[str, Any]:
    if command == "begin":
        return begin()
    if command == "question":
        return question()
    if command == "freeze":
        return freeze()
    if command == "status":
        return status()
    if command == "complete":
        return complete()
    if command == "fail":
        return fail()
    raise CLIError("invalid_command", "usage: codex-forge {begin|question|freeze|status|complete|fail}")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 1:
            raise CLIError("invalid_command", "usage: codex-forge {begin|question|freeze|status|complete|fail}")
        output = dispatch(args[0])
        print(json.dumps(output, sort_keys=True, separators=(",", ":")))
        return 0
    except CLIError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "message": exc.message}, sort_keys=True, separators=(",", ":")))
        return 2
    except Exception:
        print(json.dumps({"ok": False, "code": "internal_error", "message": "Forge control operation failed"}, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
