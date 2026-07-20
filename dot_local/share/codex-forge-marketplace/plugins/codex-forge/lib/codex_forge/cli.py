"""Guarded, hook-bound Codex Forge shaping control CLI."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from typing import Any, Mapping

from .brief import brief_digest, canonical_brief_bytes, parse_brief
from .hooks import (
    APPROVAL_TTL_SECONDS,
    PLUGIN_VERSION,
    STRUCTURED_ARG_MAX_CHARS,
    STRUCTURED_INPUT_MAX_BYTES,
    _hashed_name,
)
from .state import (
    RepoIdentity, SecureJSONRecordStore, StateError, StateStore, ForgeState, transition,
    _state_from_payload, _state_payload,
)
from .verification import missing_verification_commands, verification_complete
from .ralph import (
    FileSnapshot,
    RalphError,
    RalphLaunchRecoveryError,
    RalphPreparation,
    cancel_owned_ralph,
    inspect_ralph_eligibility,
    launch_ralph_dispatch,
    prepare_ralph_dispatch,
    read_ralph_output,
    read_ralph_receipt,
    recover_ralph_status,
    rollback_ralph_preparation,
)

HEARTBEAT_MAX_AGE_SECONDS = 5 * 60
MAX_STDIN_BYTES = 2 * 1024 * 1024
MAX_QUESTION_BYTES = 4096
MAX_FAILURE_BYTES = 2048
MAX_QUESTIONS = 5
MAX_RALPH_OUTPUT_BYTES = 4 * 1024
MAX_RALPH_RECOVERY_BYTES = 2 * 1024 * 1024
_RALPH_RECOVERY_VERSION = 1


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


def _delete_record(root: Path, prefix: str, session: str) -> None:
    try:
        _record_store(root).delete(_record(root, prefix, session))
    except (StateError, OSError) as exc:
        raise CLIError("state_cleanup_failed", "Forge control state could not be cleaned up") from exc


def _cleanup_freeze_records(root: Path, session: str) -> None:
    # These are the only records freeze owns; never delete by glob or directory.
    _delete_record(root, "approval-", session)
    _delete_record(root, "brief-", session)


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


def _structured_json(argument: str) -> Any:
    if not isinstance(argument, str) or not argument:
        raise CLIError("payload_required", "structured input must be one base64url argument")
    if len(argument) > STRUCTURED_ARG_MAX_CHARS:
        raise CLIError("payload_oversized", "structured input exceeds the Forge input limit")
    if "=" in argument:
        raise CLIError("payload_padding", "structured input must use unpadded base64url")
    if not all(char.isascii() and (char.isalnum() or char in "_-") for char in argument):
        raise CLIError("payload_alphabet", "structured input contains an invalid base64url character")
    try:
        raw = base64.urlsafe_b64decode(argument + "=" * ((4 - len(argument) % 4) % 4))
    except (binascii.Error, ValueError) as exc:
        raise CLIError("payload_encoding", "structured input is not valid base64url") from exc
    if len(raw) > STRUCTURED_INPUT_MAX_BYTES:
        raise CLIError("payload_oversized", "structured input exceeds the Forge input limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CLIError("invalid_utf8", "structured input is not valid UTF-8") from exc
    decoder = json.JSONDecoder()
    try:
        value, end = decoder.raw_decode(text)
    except json.JSONDecodeError as exc:
        raise CLIError("invalid_json", "structured input must contain one JSON value") from exc
    if text[end:].strip():
        raise CLIError("trailing_json", "structured input must contain exactly one JSON value")
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


def _selected_dispatcher(state: ForgeState) -> str | None:
    if state.status in {"approved_direct", "executing"}:
        return "direct"
    if state.status == "approved_ralph" or state.status == "ralph_running":
        return "ralph"
    return None


def _approval_summary(root: Path, session: str, state: ForgeState) -> dict[str, Any]:
    record = _read_record(root, "approval-", session)
    if not isinstance(record, dict):
        return {"state": "none", "expires_in_seconds": None}
    expiry = record.get("expires_at")
    remaining = None
    if isinstance(expiry, (int, float)) and not isinstance(expiry, bool):
        remaining = max(0, min(APPROVAL_TTL_SECONDS, int(expiry - _now())))
    if state.status == "frozen" and record.get("used") is True:
        state_name = "recovery_required"
    elif state.status == "frozen" and remaining == 0:
        state_name = "expired"
    elif record.get("used") is True:
        state_name = "consumed"
    else:
        state_name = "available"
    return {"state": state_name, "expires_in_seconds": remaining}


def _summary(state: ForgeState, root: Path, session: str, *, ralph: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = _metadata(root, session)
    brief = _read_record(root, "brief-", session)
    required = len(state.verification_commands)
    passed = required - len(missing_verification_commands(state)) if required else 0
    return {
        "ok": True,
        "status": state.status,
        "question_count": meta["question_count"],
        "brief_digest": brief.get("digest") if isinstance(brief, dict) else None,
        "failure_reason": meta["failure_reason"],
        "selected_dispatcher": _selected_dispatcher(state),
        "approval": _approval_summary(root, session, state),
        "verification": {"passed": passed, "required": required, "remaining": max(0, required - passed)},
        "ralph": ralph if ralph is not None else {
            "owned": False, "running": False, "terminal": "not-started"
        },
    }


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


def question(argument: str) -> dict[str, Any]:
    session, root = _env()
    state, _, _ = _load_bound(root, session)
    if state.status != "shaping":
        raise CLIError("invalid_transition", "questions are allowed only while shaping")
    payload = _structured_json(argument)
    if not isinstance(payload, dict):
        raise CLIError("invalid_question", "structured question must be {\"question\": \"...\"}")
    if set(payload) != {"question"} or not isinstance(payload["question"], str) or not payload["question"].strip():
        raise CLIError("invalid_question", "structured question must be {\"question\": \"...\"}")
    question_text = payload["question"]
    if len(question_text.encode("utf-8")) > MAX_QUESTION_BYTES or any(ord(c) < 32 or ord(c) == 127 for c in question_text):
        raise CLIError("invalid_question", "question is empty, oversized, or contains control characters")
    meta = _metadata(root, session)
    meta["question_count"] += 1
    _write_record(root, "meta-", session, meta)
    if meta["question_count"] > MAX_QUESTIONS:
        raise CLIError("question_limit", "Forge allows at most five shaping questions")
    return {"ok": True, "attempt": meta["question_count"]}


def _published_freeze(state: ForgeState, root: Path, session: str, digest: str) -> dict[str, Any] | None:
    if state.status != "frozen":
        return None
    brief = _read_record(root, "brief-", session)
    approval = _read_record(root, "approval-", session)
    if (not isinstance(brief, dict) or brief.get("digest") != digest or
            not isinstance(approval, dict) or not isinstance(approval.get("nonce"), str) or
            approval.get("session_id") != session):
        return None
    return {"ok": True, "status": "frozen", "brief_digest": digest,
            "nonce": approval["nonce"], "expires_at": approval.get("expires_at")}


def freeze(argument: str) -> dict[str, Any]:
    session, root = _env()
    state, cwd, repo = _load_bound(root, session)
    raw = _structured_json(argument)
    try:
        brief = parse_brief(raw)
    except ValueError as exc:
        raise CLIError("invalid_brief", str(exc)) from exc
    digest = brief_digest(brief)
    published = _published_freeze(state, root, session, digest)
    if published is not None:
        return published
    if state.status != "shaping":
        raise CLIError("invalid_transition", "only a shaping session can be frozen")
    try:
        brief = parse_brief(raw)
    except ValueError as exc:
        raise CLIError("invalid_brief", str(exc)) from exc
    digest = brief_digest(brief)
    existing_brief = _read_record(root, "brief-", session)
    existing_approval = _read_record(root, "approval-", session)
    if existing_brief is not None or existing_approval is not None:
        # A shaping session can only have these records after an interrupted
        # freeze. Clean that exact session-owned pair before retrying.
        try:
            _cleanup_freeze_records(root, session)
        except CLIError as exc:
            raise CLIError("freeze_recovery_required", "an interrupted freeze could not be recovered") from exc
    issued = _now()
    nonce = secrets.token_hex(32)
    approval = {"nonce": nonce, "session_id": session, "cwd": str(cwd),
                "repo": str(state.repo.root) if state.repo is not None else None,
                "issued_at": issued, "expires_at": issued + APPROVAL_TTL_SECONDS, "used": False}
    try:
        _write_record(root, "brief-", session, {"digest": digest, "brief": json.loads(canonical_brief_bytes(brief))}, exclusive=True)
        _write_record(root, "approval-", session, approval, exclusive=True)
        frozen = transition(state, "freeze")
        frozen = ForgeState(frozen.session_id, frozen.cwd, frozen.repo, frozen.status,
                            frozen.schema_version, frozen.plugin_version, digest,
                            tuple(brief.verification), ())
        _store(root).replace(frozen)
    except (CLIError, StateError, ValueError, OSError) as exc:
        # replace() can fail after os.replace (directory fsync), so reload the
        # state before deciding whether these records are safe to remove.
        try:
            observed = _store(root).load(session)
        except (StateError, ValueError, OSError) as load_exc:
            raise CLIError("freeze_recovery_required", "freeze publication could not be determined") from load_exc
        recovered = _published_freeze(observed, root, session, digest) if observed is not None else None
        if recovered is not None:
            return recovered
        if observed is not None and observed.status == "frozen":
            raise CLIError("freeze_recovery_required", "frozen state has incomplete approval records") from exc
        try:
            _cleanup_freeze_records(root, session)
        except CLIError as cleanup_exc:
            raise CLIError("freeze_recovery_required", "an interrupted freeze could not be recovered") from cleanup_exc
        raise CLIError("freeze_failed", "immutable brief and approval could not be persisted") from exc
    return {"ok": True, "status": "frozen", "brief_digest": digest, "nonce": nonce,
            "expires_at": approval["expires_at"]}


def status() -> dict[str, Any]:
    session, root = _env()
    state, cwd, repo = _load_bound(root, session, heartbeat=False)
    ralph = {"owned": False, "running": False, "terminal": "not-started"}
    if state.status in {"approved_ralph", "ralph_running", "completed", "failed", "cancelled"}:
        state, ralph, _ = _reconcile_ralph(state, root, session, cwd, repo)
    # Reconcile exactly once: the same lifecycle snapshot supplies both status
    # and Ralph fields, even if a receipt arrives while this command runs.
    return _summary(state, root, session, ralph=ralph)


def _ralph_brief(root: Path, session: str):
    record = _read_record(root, "brief-", session)
    if not isinstance(record, dict) or not isinstance(record.get("brief"), dict):
        raise CLIError("ralph_unavailable", "the frozen Ralph brief is unavailable")
    try:
        brief = parse_brief(record["brief"])
    except ValueError as exc:
        raise CLIError("ralph_unavailable", "the frozen Ralph brief is malformed") from exc
    if brief.dispatcher != "ralph":
        raise CLIError("ralph_unavailable", "the frozen brief does not authorize Ralph")
    return brief


def _ralph_state(state: ForgeState, expected: str) -> None:
    if state.status != expected:
        raise CLIError("invalid_transition", f"Ralph requires Forge state {expected}")


def ralph_preflight() -> dict[str, Any]:
    session, root = _env()
    state, cwd, _ = _load_bound(root, session)
    _ralph_state(state, "approved_ralph")
    brief = _ralph_brief(root, session)
    try:
        result = inspect_ralph_eligibility(brief, cwd)
    except (RalphError, OSError) as exc:
        raise CLIError("ralph_ineligible", str(exc)) from exc
    return {"ok": result.eligible, "eligible": result.eligible, "reasons": list(result.reasons)}


def _restore_ralph_launch_snapshot(root: Path, session: str, state: ForgeState,
                                   record: dict[str, Any] | None) -> None:
    """Restore and prove the exact pre-handshake records before Git rewinds."""
    failure: Exception | None = None
    try:
        if record is None:
            _delete_record(root, "ralph-", session)
        else:
            _write_record(root, "ralph-", session, record)
        _store(root).replace(state)
    except Exception as exc:
        failure = exc
    try:
        observed_state = _store(root).load(session)
        observed_record = _read_record(root, "ralph-", session)
    except Exception as exc:
        raise CLIError("ralph_launch_recovery_required",
                       "Ralph launch recovery state could not be verified") from exc
    if observed_state != state or observed_record != record:
        raise CLIError("ralph_launch_recovery_required",
                       "Ralph launch state restoration is uncertain") from failure


def _recovery_payload(state: ForgeState, record: dict[str, Any] | None,
                      preparation: RalphPreparation, launch_id: str,
                      cwd: Path, repo: RepoIdentity | None) -> dict[str, Any]:
    snapshots = []
    for snapshot in preparation.snapshots:
        snapshots.append({
            "path": snapshot.path,
            "existed": snapshot.existed,
            "content": base64.b64encode(snapshot.content).decode("ascii"),
        })
    payload = {
        "version": _RALPH_RECOVERY_VERSION,
        "plugin_version": PLUGIN_VERSION,
        "session_id": state.session_id,
        "cwd": str(cwd),
        "repo_root": str(repo.root) if repo is not None else None,
        "git_dir": str(repo.git_dir) if repo is not None and repo.git_dir is not None else None,
        "launch_id": launch_id,
        "state": _state_payload(state),
        "previous_ralph_record": record,
        "preparation": {
            "cwd": str(preparation.cwd),
            "paths": list(preparation.paths),
            "snapshots": snapshots,
            "before_head": preparation.before_head,
            "planning_commit": preparation.planning_commit,
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(encoded) > MAX_RALPH_RECOVERY_BYTES:
        raise CLIError("ralph_launch_recovery_required", "Ralph launch recovery transaction is oversized")
    return payload


def _write_ralph_recovery(root: Path, session: str, state: ForgeState,
                          record: dict[str, Any] | None, preparation: RalphPreparation,
                          launch_id: str, cwd: Path, repo: RepoIdentity | None) -> None:
    payload = _recovery_payload(state, record, preparation, launch_id, cwd, repo)
    try:
        _write_record(root, "ralph-recovery-", session, payload, exclusive=True)
    except CLIError as exc:
        raise CLIError("ralph_launch_recovery_required",
                       "Ralph launch recovery transaction could not be persisted") from exc


def _delete_ralph_recovery(root: Path, session: str) -> None:
    _delete_record(root, "ralph-recovery-", session)
    if _read_record(root, "ralph-recovery-", session) is not None:
        raise CLIError("ralph_launch_recovery_required",
                       "Ralph launch recovery transaction could not be removed")


def _load_ralph_recovery(root: Path, session: str, cwd: Path,
                         repo: RepoIdentity | None) -> tuple[ForgeState, dict[str, Any] | None,
                                                               RalphPreparation, str] | None:
    payload = _read_record(root, "ralph-recovery-", session)
    if payload is None:
        return None
    required = {
        "version", "plugin_version", "session_id", "cwd", "repo_root", "git_dir", "launch_id",
        "state", "previous_ralph_record", "preparation",
    }
    expected_root = str(repo.root) if repo is not None else None
    expected_git_dir = str(repo.git_dir) if repo is not None and repo.git_dir is not None else None
    if (set(payload) != required or payload.get("version") != _RALPH_RECOVERY_VERSION or
            payload.get("plugin_version") != PLUGIN_VERSION or payload.get("session_id") != session or
            payload.get("cwd") != str(cwd) or payload.get("repo_root") != expected_root or
            payload.get("git_dir") != expected_git_dir or not isinstance(payload.get("launch_id"), str) or
            re.fullmatch(r"[0-9a-f]{64}", payload["launch_id"]) is None or
            not isinstance(payload.get("state"), dict) or
            payload.get("previous_ralph_record") is not None and not isinstance(payload.get("previous_ralph_record"), dict) or
            not isinstance(payload.get("preparation"), dict)):
        raise CLIError("ralph_launch_recovery_required", "Ralph launch recovery transaction is malformed")
    try:
        snapshot_state = _state_from_payload(payload["state"])
    except (StateError, ValueError, TypeError) as exc:
        raise CLIError("ralph_launch_recovery_required", "Ralph launch recovery state is malformed") from exc
    if (snapshot_state.session_id != session or snapshot_state.cwd != cwd or
            snapshot_state.status != "approved_ralph" or not _binding_matches(snapshot_state, cwd, repo)):
        raise CLIError("ralph_launch_recovery_required", "Ralph launch recovery binding is invalid")
    raw_preparation = payload["preparation"]
    required_preparation = {"cwd", "paths", "snapshots", "before_head", "planning_commit"}
    if (set(raw_preparation) != required_preparation or raw_preparation.get("cwd") != str(cwd) or
            not isinstance(raw_preparation.get("paths"), list) or
            not all(isinstance(path, str) and path and "\x00" not in path for path in raw_preparation["paths"]) or
            len(set(raw_preparation["paths"])) != len(raw_preparation["paths"]) or
            not isinstance(raw_preparation.get("snapshots"), list) or
            len(raw_preparation["snapshots"]) != len(raw_preparation["paths"]) or
            not isinstance(raw_preparation.get("before_head"), str) or not raw_preparation["before_head"] or
            not isinstance(raw_preparation.get("planning_commit"), str) or not raw_preparation["planning_commit"]):
        raise CLIError("ralph_launch_recovery_required", "Ralph launch recovery plan is malformed")
    snapshots: list[FileSnapshot] = []
    for expected_path, raw_snapshot in zip(raw_preparation["paths"], raw_preparation["snapshots"]):
        if (not isinstance(raw_snapshot, dict) or set(raw_snapshot) != {"path", "existed", "content"} or
                raw_snapshot.get("path") != expected_path or type(raw_snapshot.get("existed")) is not bool or
                not isinstance(raw_snapshot.get("content"), str)):
            raise CLIError("ralph_launch_recovery_required", "Ralph launch recovery snapshot is malformed")
        try:
            content = base64.b64decode(raw_snapshot["content"].encode("ascii"), validate=True)
        except (ValueError, UnicodeError) as exc:
            raise CLIError("ralph_launch_recovery_required", "Ralph launch recovery snapshot is malformed") from exc
        if not raw_snapshot["existed"] and content:
            raise CLIError("ralph_launch_recovery_required", "Ralph launch recovery snapshot is malformed")
        snapshots.append(FileSnapshot(expected_path, raw_snapshot["existed"], content))
    try:
        preparation = RalphPreparation(cwd, tuple(raw_preparation["paths"]), tuple(snapshots),
                                       raw_preparation["before_head"], raw_preparation["planning_commit"])
    except (TypeError, ValueError) as exc:
        raise CLIError("ralph_launch_recovery_required", "Ralph launch recovery plan is malformed") from exc
    return snapshot_state, payload["previous_ralph_record"], preparation, payload["launch_id"]


def _reconcile_ralph_recovery(state: ForgeState, root: Path, session: str, cwd: Path,
                              repo: RepoIdentity | None) -> tuple[ForgeState, dict[str, Any]] | None:
    try:
        recovery = _load_ralph_recovery(root, session, cwd, repo)
    except CLIError:
        return state, {"owned": False, "running": False, "terminal": "recovery-required"}
    if recovery is None:
        return None
    snapshot_state, snapshot_record, preparation, launch_id = recovery
    try:
        receipt = read_ralph_receipt(root, launch_id)
    except RalphError:
        return state, {"owned": False, "running": False, "terminal": "recovery-required"}
    if receipt is None:
        return state, {"owned": False, "running": False, "terminal": "recovery-required"}
    if receipt["status"] in {"prearm_aborted", "spawn_failed"}:
        try:
            _restore_ralph_launch_snapshot(root, session, snapshot_state, snapshot_record)
            rollback_ralph_preparation(preparation)
            _delete_ralph_recovery(root, session)
        except Exception:
            return state, {"owned": False, "running": False, "terminal": "recovery-required"}
        return snapshot_state, {"owned": False, "running": False, "terminal": receipt["status"]}
    if receipt["status"] in {"spawned", "running", "completed", "failed"}:
        # This is the durable real-Popen proof.  Never restore snapshots or
        # reset HEAD from this point, even if later lifecycle data is damaged.
        try:
            _delete_ralph_recovery(root, session)
        except CLIError:
            return state, {"owned": False, "running": False, "terminal": "recovery-required"}
        return None
    return state, {"owned": False, "running": False, "terminal": "recovery-required"}


def ralph_launch() -> dict[str, Any]:
    session, root = _env()
    state, cwd, repo = _load_bound(root, session)
    _ralph_state(state, "approved_ralph")
    brief = _ralph_brief(root, session)
    original_ralph_record = _read_record(root, "ralph-", session)
    if _read_record(root, "ralph-recovery-", session) is not None:
        raise CLIError("ralph_launch_recovery_required",
                       "an earlier Ralph launch requires recovery before another launch")
    try:
        preparation = prepare_ralph_dispatch(brief, cwd)
    except (RalphError, OSError) as exc:
        raise CLIError("ralph_prepare_failed", str(exc)) from exc
    launch_id = secrets.token_hex(32)
    try:
        _write_ralph_recovery(root, session, state, original_ralph_record,
                              preparation, launch_id, cwd, repo)
    except CLIError as exc:
        try:
            rollback_ralph_preparation(preparation)
        except Exception as rollback_exc:
            raise CLIError("ralph_launch_recovery_required",
                           "Ralph planning rollback is uncertain; recovery is required") from rollback_exc
        raise exc

    def on_spawn(launch: Any) -> None:
        payload = {
            "plugin_version": PLUGIN_VERSION,
            "session_id": session,
            "cwd": str(cwd),
            "repo_root": str(repo.root) if repo is not None else None,
            "git_dir": str(repo.git_dir) if repo is not None and repo.git_dir is not None else None,
            "planning_commit": preparation.planning_commit,
            "pid": launch.identity.pid,
            "pgid": launch.identity.pgid,
            "start": launch.identity.start,
            "marker_digest": launch.identity.marker_digest,
            "launch_id": launch.launch_id,
        }
        _write_record(root, "ralph-", session, payload)
        try:
            _store(root).replace(transition(state, "ralph_start"))
        except (StateError, ValueError, OSError) as exc:
            raise CLIError("state_write_failed", "Ralph start could not be persisted") from exc

    def on_abort() -> None:
        _restore_ralph_launch_snapshot(root, session, state, original_ralph_record)

    def on_rollback() -> None:
        _delete_ralph_recovery(root, session)

    def on_spawn_proven() -> None:
        _delete_ralph_recovery(root, session)

    try:
        launch_ralph_dispatch(preparation, data_root=root, launch_id=launch_id,
                              on_spawn=on_spawn, on_abort=on_abort,
                              on_rollback=on_rollback, on_spawn_proven=on_spawn_proven)
    except RalphLaunchRecoveryError as exc:
        raise CLIError("ralph_launch_recovery_required", str(exc)) from exc
    except CLIError:
        raise
    except (RalphError, OSError) as exc:
        raise CLIError("ralph_launch_failed", str(exc)) from exc
    return {"ok": True, "status": "ralph_running", "planning_commit": preparation.planning_commit}


def _bound_ralph_record(root: Path, session: str, cwd: Path, repo: RepoIdentity | None) -> dict[str, Any]:
    record = _read_record(root, "ralph-", session)
    required = {"plugin_version", "session_id", "cwd", "repo_root", "git_dir", "planning_commit",
                "pid", "pgid", "start", "marker_digest", "launch_id"}
    if (not isinstance(record, dict) or set(record) != required or
            record.get("plugin_version") != PLUGIN_VERSION or record.get("session_id") != session or
            record.get("cwd") != str(cwd) or not isinstance(record.get("planning_commit"), str) or
            not record["planning_commit"] or type(record.get("pid")) is not int or record["pid"] <= 0 or
            type(record.get("pgid")) is not int or record["pgid"] <= 0 or
            not isinstance(record.get("start"), str) or not record["start"] or
            not isinstance(record.get("marker_digest"), str) or len(record["marker_digest"]) != 44 or
            any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=" for char in record["marker_digest"]) or
            not isinstance(record.get("launch_id"), str) or
            re.fullmatch(r"[0-9a-f]{64}", record["launch_id"]) is None):
        raise CLIError("ralph_unavailable", "Ralph instance record is unavailable")
    expected_root = str(repo.root) if repo is not None else None
    expected_git_dir = str(repo.git_dir) if repo is not None and repo.git_dir is not None else None
    if record.get("repo_root") != expected_root or record.get("git_dir") != expected_git_dir:
        raise CLIError("binding_mismatch", "Ralph instance repository binding does not match")
    return record


def _terminal_transition(state: ForgeState, root: Path, exit_code: int) -> ForgeState:
    if state.status != "ralph_running":
        return state
    event = "complete" if exit_code == 0 else "fail"
    try:
        state = transition(state, event)
        _store(root).replace(state)
    except (StateError, ValueError, OSError) as exc:
        raise CLIError("state_write_failed", "Ralph terminal state could not be persisted") from exc
    return state


def _reconcile_ralph(state: ForgeState, root: Path, session: str, cwd: Path,
                     repo: RepoIdentity | None) -> tuple[ForgeState, dict[str, Any], dict[str, Any] | None]:
    recovered_transaction = _reconcile_ralph_recovery(state, root, session, cwd, repo)
    if recovered_transaction is not None:
        recovered_state, public = recovered_transaction
        return recovered_state, public, None
    raw = _read_record(root, "ralph-", session)
    if raw is None:
        if state.status == "ralph_running":
            state = _terminal_transition(state, root, 1)
            return state, {"owned": False, "running": False, "terminal": "missing"}, None
        return state, {"owned": False, "running": False, "terminal": "not-started"}, None
    try:
        record = _bound_ralph_record(root, session, cwd, repo)
        receipt = read_ralph_receipt(root, record["launch_id"])
    except (CLIError, RalphError):
        if state.status == "ralph_running":
            state = _terminal_transition(state, root, 1)
        return state, {"owned": False, "running": False, "terminal": "invalid"}, None
    if receipt is not None and receipt["status"] in {"completed", "failed"}:
        state = _terminal_transition(state, root, int(receipt["exit_code"]))
        return state, {"owned": True, "running": False,
                       "terminal": "completed" if receipt["exit_code"] == 0 else "failed",
                       "exit_code": receipt["exit_code"]}, record
    recovered = recover_ralph_status(record)
    if recovered.get("running"):
        return state, {"owned": bool(recovered.get("owned")), "running": True, "terminal": "running"}, record
    if state.status == "ralph_running":
        state = _terminal_transition(state, root, 1)
    return state, {"owned": bool(recovered.get("owned")), "running": False, "terminal": "missing"}, record


def ralph_status() -> dict[str, Any]:
    session, root = _env()
    state, cwd, repo = _load_bound(root, session, heartbeat=False)
    state, public, record = _reconcile_ralph(state, root, session, cwd, repo)
    result = {"ok": True, "status": state.status, **public}
    if record is not None:
        result["planning_commit"] = record["planning_commit"]
        try:
            result["stdout"] = read_ralph_output(root, record["launch_id"], "stdout", limit=MAX_RALPH_OUTPUT_BYTES)
            result["stderr"] = read_ralph_output(root, record["launch_id"], "stderr", limit=MAX_RALPH_OUTPUT_BYTES)
        except RalphError:
            result["stdout"] = ""
            result["stderr"] = ""
    return result


def ralph_cancel() -> dict[str, Any]:
    session, root = _env()
    # Long-running owned Ralph remains cancellable after the five-minute hook
    # heartbeat expires, but still requires the identical session/cwd/repo bind.
    state, cwd, repo = _load_bound(root, session, heartbeat=False)
    _ralph_state(state, "ralph_running")
    state, public, record = _reconcile_ralph(state, root, session, cwd, repo)
    if public.get("terminal") == "recovery-required":
        raise CLIError("ralph_launch_recovery_required", "Ralph launch recovery is required before cancellation")
    if state.status != "ralph_running":
        return {"ok": True, "status": state.status, **public}
    if record is None:
        raise CLIError("ralph_not_owned", "Ralph instance record is unavailable")
    try:
        result = cancel_owned_ralph(record)
    except RalphError as exc:
        raise CLIError("ralph_not_owned", str(exc)) from exc
    try:
        next_state = transition(state, "cancel")
        _store(root).replace(next_state)
    except (StateError, ValueError, OSError) as exc:
        raise CLIError("state_write_failed", "Ralph cancellation could not be persisted") from exc
    # Keep the owned record and terminal receipt for recovery/status; status
    # never exposes paths, marker material, or unbounded output.
    return {"ok": True, "status": "cancelled", **result}


def complete() -> dict[str, Any]:
    session, root = _env()
    state, cwd, repo = _load_bound(root, session)
    if state.status == "ralph_running":
        state, public, _ = _reconcile_ralph(state, root, session, cwd, repo)
        if public.get("terminal") == "recovery-required":
            raise CLIError("ralph_launch_recovery_required", "Ralph launch recovery is required before completion")
        if state.status == "completed":
            return {"ok": True, "status": "completed", "ralph": public}
        if state.status == "failed":
            raise CLIError("ralph_failed", "Ralph did not complete successfully")
        raise CLIError("ralph_terminal_required", "Ralph is still running; use ralph-status or ralph-cancel")
    if state.status != "executing" or not verification_complete(state):
        missing = missing_verification_commands(state)
        detail = ", ".join(missing[:8])
        if len(missing) > 8:
            detail += ", ..."
        raise CLIError("verification_not_terminal",
                       "completion requires passing evidence for: " + (detail or "the frozen brief"))
    try:
        next_state = transition(state, "complete")
        _store(root).replace(next_state)
    except (StateError, ValueError, OSError) as exc:
        raise CLIError("state_write_failed", "Forge completion could not be persisted") from exc
    return {"ok": True, "status": next_state.status}


def fail(argument: str) -> dict[str, Any]:
    session, root = _env()
    state, _, _ = _load_bound(root, session)
    if state.status in {"completed", "cancelled", "failed"}:
        raise CLIError("invalid_transition", "terminal Forge sessions cannot fail")
    payload = _structured_json(argument)
    if not isinstance(payload, dict):
        raise CLIError("invalid_failure", "structured failure must be {\"reason\": \"...\"}")
    if set(payload) != {"reason"} or not isinstance(payload["reason"], str):
        raise CLIError("invalid_failure", "structured failure must be {\"reason\": \"...\"}")
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


def dispatch(command: str, argument: str | None = None) -> dict[str, Any]:
    if command == "begin":
        if argument is not None:
            raise CLIError("invalid_command", "begin accepts no payload")
        return begin()
    if command == "question":
        if argument is None:
            raise CLIError("payload_required", "question requires one base64url payload")
        return question(argument)
    if command == "freeze":
        if argument is None:
            raise CLIError("payload_required", "freeze requires one base64url payload")
        return freeze(argument)
    if command == "status":
        if argument is not None:
            raise CLIError("invalid_command", "status accepts no payload")
        return status()
    if command == "complete":
        if argument is not None:
            raise CLIError("invalid_command", "complete accepts no payload")
        return complete()
    if command == "fail":
        if argument is None:
            raise CLIError("payload_required", "fail requires one base64url payload")
        return fail(argument)
    if command == "ralph-preflight":
        if argument is not None:
            raise CLIError("invalid_command", "ralph-preflight accepts no payload")
        return ralph_preflight()
    if command == "ralph-launch":
        if argument is not None:
            raise CLIError("invalid_command", "ralph-launch accepts no payload")
        return ralph_launch()
    if command == "ralph-status":
        if argument is not None:
            raise CLIError("invalid_command", "ralph-status accepts no payload")
        return ralph_status()
    if command == "ralph-cancel":
        if argument is not None:
            raise CLIError("invalid_command", "ralph-cancel accepts no payload")
        return ralph_cancel()
    raise CLIError("invalid_command", "usage: codex-forge {begin|question|freeze|status|complete|fail|ralph-preflight|ralph-launch|ralph-status|ralph-cancel}")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        commands = {"begin", "question", "freeze", "status", "complete", "fail",
                    "ralph-preflight", "ralph-launch", "ralph-status", "ralph-cancel"}
        if not args or args[0] not in commands:
            raise CLIError("invalid_command", "usage: codex-forge {begin|question|freeze|status|complete|fail|ralph-preflight|ralph-launch|ralph-status|ralph-cancel}")
        command = args[0]
        expects_payload = command in {"question", "freeze", "fail"}
        if len(args) != (2 if expects_payload else 1):
            raise CLIError("invalid_command", f"{command} accepts {'one payload' if expects_payload else 'no payload'}")
        output = dispatch(command, args[1] if expects_payload else None)
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
