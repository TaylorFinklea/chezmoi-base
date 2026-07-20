"""Bounded, session-bound evidence for direct Forge verification."""

from dataclasses import replace
import hashlib
import json
import math
import re
import time
from typing import Any, Mapping

from .state import ForgeState

PREVIEW_BYTES = 4 * 1024
RESPONSE_MAX_BYTES = 10 * 1024 * 1024


class VerificationError(ValueError):
    pass


def _json_bytes(value: Any) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise VerificationError("verification response is not valid JSON") from exc
    if len(raw) > RESPONSE_MAX_BYTES:
        raise VerificationError("verification response is oversized")
    return raw


def _preview(response: Mapping[str, Any]) -> tuple[str, str]:
    output = response.get("output", "")
    if isinstance(output, str):
        text = output
    else:
        text = json.dumps(output, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    encoded = text.encode("utf-8")
    if len(encoded) <= PREVIEW_BYTES:
        return text, text
    head = encoded[:PREVIEW_BYTES].decode("utf-8", errors="replace")
    tail = encoded[-PREVIEW_BYTES:].decode("utf-8", errors="replace")
    return head, tail


def _repo_binding(state: ForgeState) -> str | None:
    return str(state.repo.root) if state.repo is not None else None


def record_verification(state: ForgeState, command: str, response: Mapping[str, Any]) -> ForgeState:
    """Append one bounded attempt for an exact frozen verification command."""
    if not isinstance(state, ForgeState) or state.status != "executing":
        raise VerificationError("verification requires direct execution")
    if not state.brief_digest:
        raise VerificationError("verification brief binding is missing")
    if not isinstance(command, str) or command not in state.verification_commands:
        raise VerificationError("verification command is not in the frozen brief")
    if not isinstance(response, Mapping) or "exit_code" not in response:
        raise VerificationError("verification response is missing exit status")
    for key, expected in (("session_id", state.session_id), ("cwd", str(state.cwd)),
                          ("repo", _repo_binding(state)), ("brief_digest", state.brief_digest)):
        if key in response and response[key] != expected:
            raise VerificationError("verification response binding does not match the Forge session")
    exit_code = response["exit_code"]
    if type(exit_code) is not int:
        raise VerificationError("verification response has an invalid exit status")
    raw = _json_bytes(dict(response))
    head, tail = _preview(response)
    evidence = {
        "session_id": state.session_id,
        "cwd": str(state.cwd),
        "repo": _repo_binding(state),
        "brief_digest": state.brief_digest,
        "command": command,
        "exit_code": exit_code,
        "head": head,
        "tail": tail,
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "timestamp": time.time(),
    }
    return replace(state, verification_records=state.verification_records + (evidence,))


def _valid_evidence(state: ForgeState, record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    required = {"session_id", "cwd", "repo", "brief_digest", "command", "exit_code",
                "head", "tail", "response_sha256", "timestamp"}
    if set(record) != required:
        return False
    if (record["session_id"] != state.session_id or record["cwd"] != str(state.cwd) or
            record["repo"] != _repo_binding(state) or record["brief_digest"] != state.brief_digest or
            record["command"] not in state.verification_commands or type(record["exit_code"]) is not int or
            not isinstance(record["head"], str) or not isinstance(record["tail"], str) or
            len(record["head"].encode("utf-8")) > PREVIEW_BYTES or
            len(record["tail"].encode("utf-8")) > PREVIEW_BYTES or
            not isinstance(record["response_sha256"], str) or
            re.fullmatch(r"[0-9a-f]{64}", record["response_sha256"]) is None or
            isinstance(record["timestamp"], bool) or not isinstance(record["timestamp"], (int, float)) or
            not math.isfinite(record["timestamp"])):
        return False
    return True


def missing_verification_commands(state: ForgeState) -> tuple[str, ...]:
    """Return frozen commands without a passing exact evidence record."""
    passing = {
        record["command"] for record in state.verification_records
        if _valid_evidence(state, record) and record["exit_code"] == 0
    }
    return tuple(command for command in state.verification_commands if command not in passing)


def verification_complete(state: ForgeState) -> bool:
    return bool(state.verification_commands) and not missing_verification_commands(state)
