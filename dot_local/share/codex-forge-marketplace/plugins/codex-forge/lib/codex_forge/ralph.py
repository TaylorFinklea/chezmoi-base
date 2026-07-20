"""Fail-closed Codex Ralph preparation, launch, recovery, and cancellation."""

from __future__ import annotations

from dataclasses import dataclass
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import stat
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Mapping, Sequence

from .brief import Brief, Phase
from .state import SecureJSONRecordStore, StateError

MAX_OUTPUT_BYTES = 64 * 1024
MAX_OUTPUT_LINES = 200
KILL_GRACE_SECONDS = 2.0
FORGE_PATHS = (".docs/ai/current-state.md", ".docs/ai/roadmap.md")
OWNERSHIP_MARKER_ENV = "CODEX_FORGE_RALPH_OWNERSHIP_MARKER"
_MARKER_DIGEST_BYTES = 32


class RalphError(RuntimeError):
    pass


@dataclass(frozen=True)
class RalphEligibility:
    eligible: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class FileSnapshot:
    path: str
    existed: bool
    content: bytes = b""


@dataclass(frozen=True)
class RalphPreparation:
    cwd: Path
    paths: tuple[str, ...]
    snapshots: tuple[FileSnapshot, ...]
    before_head: str
    planning_commit: str


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    start: str
    pgid: int
    marker_digest: str | None = None


@dataclass(frozen=True)
class RalphResult:
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class RalphLaunch:
    identity: ProcessIdentity
    launch_id: str
    stdout_name: str
    stderr_name: str
    receipt_name: str


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return result or "forge-execution"


def _phase_spec_path(brief: Brief) -> str:
    return f".docs/ai/phases/{_slug(brief.goal)}-spec.md"


def _safe_path(cwd: Path, relative_path: str) -> Path:
    root = Path(cwd).resolve(strict=True)
    target = (root / relative_path).resolve(strict=False)
    ai_root = root / ".docs" / "ai"
    if target != ai_root and ai_root not in target.parents:
        raise RalphError(f"Forge path escapes .docs/ai: {relative_path}")
    cursor = root
    for part in target.relative_to(root).parts:
        cursor /= part
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(info.st_mode):
            raise RalphError(f"Forge refuses symlinked .docs/ai path: {relative_path}")
        if cursor != target and not stat.S_ISDIR(info.st_mode):
            raise RalphError(f"Forge path parent is not a directory: {relative_path}")
    return target


def _read_structural(path: Path) -> str:
    try:
        info = path.lstat()
    except OSError as exc:
        raise RalphError(f"Forge planning file is inaccessible: {path}") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RalphError(f"Forge planning file must be a regular non-symlink file: {path}")
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RalphError(f"Forge planning file must be valid UTF-8: {path}") from exc
    if "\r" in text or not text.endswith("\n") or "\x00" in text:
        raise RalphError(f"Forge planning file has invalid structural newlines: {path}")
    return text


def _plan_bounds(text: str) -> tuple[int, int]:
    lines = text.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.rstrip("\n") == "## Plan"]
    if len(starts) != 1:
        raise RalphError("current-state.md must contain exactly one ## Plan section")
    start = starts[0]
    end = next((index for index in range(start + 1, len(lines))
                if lines[index].startswith("## ")), len(lines))
    return start, end


def _plan_is_empty(text: str) -> bool:
    lines = text.splitlines(keepends=True)
    start, end = _plan_bounds(text)
    return not any(line.strip() for line in lines[start + 1:end])


def _render_current_state(text: str, phases: Sequence[Phase]) -> str:
    lines = text.splitlines(keepends=True)
    start, end = _plan_bounds(text)
    rendered = lines[:start + 1]
    for phase in phases:
        rendered.append(f"- [ ] {phase.name}. Verify: `{phase.verify}` (tier_floor: {phase.tier_floor})\n")
    rendered.extend(lines[end:])
    return "".join(rendered)


def _render_roadmap(text: str, brief: Brief) -> str:
    marker = f"{brief.goal} — Forge execution"
    if marker in text:
        raise RalphError("roadmap already contains this Forge execution")
    lines = text.splitlines(keepends=True)
    now = next((index for index, line in enumerate(lines) if line.rstrip("\n") == "### Now"), None)
    if now is None:
        return text + ("\n" if not text.endswith("\n") else "") + f"### Now\n- [ ] {marker}\n"
    end = next((index for index in range(now + 1, len(lines)) if lines[index].startswith("### ")), len(lines))
    return "".join(lines[:end] + [f"- [ ] {marker}\n"] + lines[end:])


def _render_phase_spec(brief: Brief, date: str | None = None) -> str:
    date = date or time.strftime("%Y-%m-%d", time.gmtime())
    phases = "\n".join(
        f"{index}. {phase.name} ({phase.tier_floor}) — Verify: `{phase.verify}`"
        for index, phase in enumerate(brief.phases, 1)
    )
    return (f"# Forge Execution Brief: {brief.goal}\n\n"
            f"Prepared: {date}\n\n"
            f"## Goal\n{brief.goal}\n\n"
            f"## Phases\n{phases}\n")


def check_ralph_eligibility(*, is_git: bool, clean: bool, current_state: str | None,
                            roadmap: str | None, has_beads: bool, brief: Brief,
                            phase_spec_exists: bool = False, ralph_exists: bool = True) -> RalphEligibility:
    reasons: list[str] = []
    if not is_git:
        reasons.append("Current directory is not a Git repository.")
    if not clean:
        reasons.append("Git worktree is not clean.")
    if current_state is None:
        reasons.append(".docs/ai/current-state.md is missing.")
    if roadmap is None:
        reasons.append(".docs/ai/roadmap.md is missing.")
    if has_beads:
        reasons.append("Ralph dispatch is disabled for beads repositories.")
    if not ralph_exists:
        reasons.append("ralph executable is missing.")
    if current_state is not None:
        try:
            if not _plan_is_empty(current_state):
                reasons.append("Current Plan already has items.")
        except RalphError as exc:
            reasons.append(str(exc))
    if phase_spec_exists:
        reasons.append("Forge phase spec already exists.")
    if len(brief.phases) < 2:
        reasons.append("Ralph requires at least two independently verifiable phases.")
    for index, phase in enumerate(brief.phases, 1):
        if phase.tier_floor == "lead":
            reasons.append(f"Phase {index} is Lead-tier and cannot run through Ralph.")
        if not phase.verify.strip():
            reasons.append(f"Phase {index} lacks an exact Verify command.")
    return RalphEligibility(not reasons, tuple(reasons))


def _ralph_exists() -> bool:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        executable = Path(directory or ".") / "ralph"
        if executable.is_file() and os.access(executable, os.X_OK):
            return True
    return False


def inspect_ralph_eligibility(brief: Brief, cwd: Path) -> RalphEligibility:
    cwd = Path(cwd).resolve(strict=True)
    try:
        git = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=cwd,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        git = None
    is_git = bool(git and git.returncode == 0 and git.stdout.strip() == "true")
    clean = False
    if is_git:
        try:
            status = subprocess.run(["git", "status", "--porcelain"], cwd=cwd,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, timeout=5)
            clean = status.returncode == 0 and not status.stdout
        except (OSError, subprocess.SubprocessError):
            pass
    current_path = _safe_path(cwd, FORGE_PATHS[0])
    roadmap_path = _safe_path(cwd, FORGE_PATHS[1])
    current = _read_structural(current_path) if current_path.exists() else None
    roadmap = _read_structural(roadmap_path) if roadmap_path.exists() else None
    phase_path = _safe_path(cwd, _phase_spec_path(brief))
    return check_ralph_eligibility(
        is_git=is_git, clean=clean, current_state=current, roadmap=roadmap,
        has_beads=(cwd / ".beads").exists(), brief=brief,
        phase_spec_exists=phase_path.exists(), ralph_exists=_ralph_exists(),
    )


def _snapshot(cwd: Path, paths: Sequence[str]) -> tuple[FileSnapshot, ...]:
    result = []
    for relative_path in paths:
        path = _safe_path(cwd, relative_path)
        if path.exists():
            result.append(FileSnapshot(relative_path, True, _read_structural(path).encode("utf-8")))
        else:
            result.append(FileSnapshot(relative_path, False))
    return tuple(result)


def _restore(cwd: Path, snapshots: Sequence[FileSnapshot]) -> None:
    for snapshot in snapshots:
        path = _safe_path(cwd, snapshot.path)
        if snapshot.existed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(snapshot.content)
        else:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _run(args: Sequence[str], cwd: Path, *, timeout: float = 30, check: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(list(args), cwd=cwd, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RalphError(f"command failed to start: {args[0]}") from exc
    if check and result.returncode:
        detail = (result.stderr or result.stdout or f"exit {result.returncode}").strip()
        raise RalphError(f"{' '.join(args)}: {detail}")
    return result


def _head_is_owned_planning_commit(cwd: Path, before_head: str, paths: Sequence[str],
                                  planning_subject: str, planning_commit: str | None) -> bool:
    head = _run(["git", "rev-parse", "HEAD"], cwd, check=True).stdout.strip()
    if planning_commit is not None:
        return head == planning_commit
    parent = _run(["git", "rev-parse", f"{head}^"], cwd, check=True).stdout.strip()
    changed = _run(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", head],
                   cwd, check=True).stdout.splitlines()
    subject = _run(["git", "log", "-1", "--format=%s", head], cwd, check=True).stdout.strip()
    return parent == before_head and set(changed) == set(paths) and subject == planning_subject


def _rollback_planning_commit(cwd: Path, snapshots: Sequence[FileSnapshot], paths: Sequence[str],
                              before_head: str, planning_subject: str,
                              planning_commit: str | None) -> None:
    rollback_error: Exception | None = None
    try:
        if _head_is_owned_planning_commit(cwd, before_head, paths, planning_subject, planning_commit):
            _run(["git", "reset", "--soft", before_head], cwd, check=True)
            _run(["git", "reset", "--", *paths], cwd, check=True)
    except Exception as exc:
        rollback_error = exc
    finally:
        _restore(cwd, snapshots)
    if rollback_error is not None:
        raise RalphError("Forge planning rollback could not be completed") from rollback_error


def _rollback(preparation: RalphPreparation) -> None:
    _rollback_planning_commit(preparation.cwd, preparation.snapshots, preparation.paths,
                              preparation.before_head, "", preparation.planning_commit)


def _restore_preparation_failure(cwd: Path, snapshots: Sequence[FileSnapshot], paths: Sequence[str]) -> None:
    restore_error: Exception | None = None
    try:
        _run(["git", "reset", "--", *paths], cwd, check=False)
    except Exception as exc:
        restore_error = exc
    finally:
        _restore(cwd, snapshots)
    if restore_error is not None:
        raise RalphError("Forge preparation rollback could not be completed") from restore_error


def prepare_ralph_dispatch(brief: Brief, cwd: Path, *, date: str | None = None) -> RalphPreparation:
    cwd = Path(cwd).resolve(strict=True)
    eligibility = inspect_ralph_eligibility(brief, cwd)
    if not eligibility.eligible:
        raise RalphError("Ralph is not eligible:\n- " + "\n- ".join(eligibility.reasons))
    paths = (*FORGE_PATHS, _phase_spec_path(brief))
    snapshots = _snapshot(cwd, paths)
    before_head = _run(["git", "rev-parse", "HEAD"], cwd, check=True).stdout.strip()
    planning_subject = f"plan: prepare Forge Ralph execution for {brief.goal}"
    committed = False
    planning_commit: str | None = None
    try:
        status_before = _run(["git", "status", "--porcelain"], cwd, check=True).stdout
        preflight = _run(["ralph", "-n", "0", "-t", "codex"], cwd, check=False)
        if preflight.returncode:
            detail = (preflight.stderr or preflight.stdout).strip()
            raise RalphError("Ralph preflight failed" + (f": {detail}" if detail else ""))
        if _snapshot(cwd, paths) != snapshots:
            raise RalphError("Ralph preflight modified Forge handoff bytes")
        if _run(["git", "status", "--porcelain"], cwd, check=True).stdout != status_before:
            raise RalphError("Ralph preflight modified the worktree")
        if _run(["git", "rev-parse", "HEAD"], cwd, check=True).stdout.strip() != before_head:
            raise RalphError("Ralph preflight modified HEAD")
        current = _render_current_state(_read_structural(_safe_path(cwd, FORGE_PATHS[0])), brief.phases)
        roadmap = _render_roadmap(_read_structural(_safe_path(cwd, FORGE_PATHS[1])), brief)
        generated = _render_phase_spec(brief, date)
        for relative_path, content in ((FORGE_PATHS[0], current), (FORGE_PATHS[1], roadmap),
                                       (_phase_spec_path(brief), generated)):
            path = _safe_path(cwd, relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="")
        _run(["git", "add", "--", *paths], cwd, check=True)
        staged = _run(["git", "diff", "--cached", "--name-only", "--", *paths], cwd, check=True)
        if set(staged.stdout.splitlines()) != set(paths):
            raise RalphError("Forge planning commit contains unexpected files")
        _run(["git", "commit", "-m", planning_subject], cwd, check=True)
        committed = True
        planning_commit = _run(["git", "rev-parse", "HEAD"], cwd, check=True).stdout.strip()
        if not planning_commit:
            raise RalphError("Forge planning commit could not be identified")
        return RalphPreparation(cwd, tuple(paths), snapshots, before_head, planning_commit)
    except Exception:
        if committed:
            _rollback_planning_commit(cwd, snapshots, paths, before_head, planning_subject, planning_commit)
        else:
            _restore_preparation_failure(cwd, snapshots, paths)
        raise


_REDACTION = b"[REDACTED]"


def _bounded_raw(value: bytes) -> bytes:
    lines = value.splitlines(keepends=True)[-MAX_OUTPUT_LINES:]
    return b"".join(lines)[-MAX_OUTPUT_BYTES:]


def _redact_raw(value: bytes, secrets_to_redact: Sequence[bytes]) -> bytes:
    for secret in sorted({secret for secret in secrets_to_redact if secret}, key=len, reverse=True):
        value = value.replace(secret, _REDACTION)
    return value


def _bounded(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    text = _bounded_raw(raw).decode("utf-8", "replace")
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_OUTPUT_BYTES:
        return text
    return encoded[-MAX_OUTPUT_BYTES:].decode("utf-8", "ignore")


def _append_bounded(previous: bytes, chunk: bytes) -> bytes:
    return _bounded_raw(previous + chunk)


def _marker_digest(marker: str | bytes) -> str:
    raw = marker.encode("utf-8") if isinstance(marker, str) else marker
    return hashlib.sha256(raw).hexdigest()


def _valid_marker_digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _encoded_marker_digest(value: str) -> str:
    return base64.urlsafe_b64encode(bytes.fromhex(value)).decode("ascii")


def _decoded_marker_digest(value: object) -> str | None:
    if _valid_marker_digest(value):
        return value
    if not isinstance(value, str):
        return None
    try:
        decoded = base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
    except (ValueError, UnicodeError):
        return None
    return decoded.hex() if len(decoded) == _MARKER_DIGEST_BYTES else None


def encode_marker_digest(value: str | None) -> str | None:
    """Return the non-sensitive persisted form of a launch digest."""
    decoded = _decoded_marker_digest(value)
    return _encoded_marker_digest(decoded) if decoded is not None else None


def _linux_marker_matches(pid: int, expected_digest: str) -> bool:
    try:
        entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\x00")
    except OSError:
        return False
    prefix = (OWNERSHIP_MARKER_ENV + "=").encode("ascii")
    values = [entry[len(prefix):] for entry in entries if entry.startswith(prefix)]
    if len(values) != 1:
        return False
    try:
        return secrets.compare_digest(_marker_digest(values[0].decode("ascii")), expected_digest)
    except UnicodeDecodeError:
        return False


def _marker_matches(pid: int, expected_digest: str) -> bool:
    if not _valid_marker_digest(expected_digest):
        return False
    if Path(f"/proc/{pid}/environ").exists():
        return _linux_marker_matches(pid, expected_digest)
    return False


class _DarwinProcessBSDInfo(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint32), ("status", ctypes.c_uint32),
        ("xstatus", ctypes.c_uint32), ("pid", ctypes.c_uint32),
        ("ppid", ctypes.c_uint32), ("uid", ctypes.c_uint32),
        ("gid", ctypes.c_uint32), ("ruid", ctypes.c_uint32),
        ("rgid", ctypes.c_uint32), ("svuid", ctypes.c_uint32),
        ("svgid", ctypes.c_uint32), ("reserved", ctypes.c_uint32),
        ("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32),
        ("nfiles", ctypes.c_uint32), ("pgid", ctypes.c_uint32),
        ("pjobc", ctypes.c_uint32), ("tdev", ctypes.c_uint32),
        ("tpgid", ctypes.c_uint32), ("nice", ctypes.c_int32),
        ("start_seconds", ctypes.c_uint64), ("start_microseconds", ctypes.c_uint64),
    ]


def _darwin_start(pid: int) -> str | None:
    try:
        info = _DarwinProcessBSDInfo()
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        proc_pidinfo = libproc.proc_pidinfo
        proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                 ctypes.c_void_p, ctypes.c_int]
        proc_pidinfo.restype = ctypes.c_int
        result = proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
    except (AttributeError, OSError):
        return None
    if result != ctypes.sizeof(info) or info.pid != pid:
        return None
    return f"{info.start_seconds}.{info.start_microseconds:06d}"


def _base_identity(pid: int) -> ProcessIdentity | None:
    if type(pid) is not int or pid <= 0:
        return None
    try:
        pgid = os.getpgid(pid)
    except OSError:
        return None
    if sys.platform == "darwin":
        start = _darwin_start(pid)
        return ProcessIdentity(pid, start, pgid) if start else None
    proc = Path(f"/proc/{pid}/stat")
    if proc.exists():
        try:
            _, _, fields = proc.read_text(encoding="ascii").rpartition(") ")
            return ProcessIdentity(pid, fields.split()[19], pgid)
        except (OSError, UnicodeError, IndexError):
            return None
    try:
        result = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    start = result.stdout.strip()
    return ProcessIdentity(pid, start, pgid) if result.returncode == 0 and start else None


def _identity(pid: int, marker_digest: str | None = None) -> ProcessIdentity | None:
    identity = _base_identity(pid)
    if identity is None:
        return None
    if marker_digest is None:
        return identity
    expected_digest = _decoded_marker_digest(marker_digest)
    if expected_digest is None:
        return None
    # Darwin's standard libproc API yields microsecond launch timestamps. That
    # closes same-second PID reuse even where ps does not expose shell-script
    # environments; other platforms must prove the private launch marker.
    if sys.platform == "darwin":
        return ProcessIdentity(identity.pid, identity.start, identity.pgid, expected_digest)
    if not _marker_matches(pid, expected_digest):
        return None
    return ProcessIdentity(identity.pid, identity.start, identity.pgid, expected_digest)


def _same_identity(record: Mapping[str, Any], identity: ProcessIdentity | None) -> bool:
    record_digest = _decoded_marker_digest(record.get("marker_digest"))
    identity_digest = _decoded_marker_digest(identity.marker_digest) if identity is not None else None
    return (identity is not None and type(record.get("pid")) is int and
            type(record.get("pgid")) is int and isinstance(record.get("start"), str) and
            record_digest is not None and identity_digest is not None and
            record["pid"] == identity.pid and record["pgid"] == identity.pgid and
            record["start"] == identity.start and
            secrets.compare_digest(record_digest, identity_digest))


def _private_names(launch_id: str) -> tuple[str, str, str]:
    if re.fullmatch(r"[0-9a-f]{64}", launch_id) is None:
        raise RalphError("invalid Ralph launch identifier")
    return (f"ralph-stdout-{launch_id}.log", f"ralph-stderr-{launch_id}.log",
            f"ralph-receipt-{launch_id}.json")


def _private_root(root: Path) -> Path:
    candidate = Path(root)
    try:
        if candidate.exists() and stat.S_ISLNK(candidate.lstat().st_mode):
            raise RalphError("Ralph private output root is unavailable")
    except OSError as exc:
        raise RalphError("Ralph private output root is unavailable") from exc
    root = candidate.resolve(strict=False)
    store = SecureJSONRecordStore(root, max_bytes=MAX_OUTPUT_BYTES)
    try:
        store._ensure_root()
    except (StateError, OSError) as exc:
        raise RalphError("Ralph private output root is unavailable") from exc
    return root


def _create_private_file(root: Path, name: str) -> None:
    path = root / name
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError as exc:
        raise RalphError("Ralph private output file could not be created") from exc
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_private_json(root: Path, name: str) -> dict[str, Any] | None:
    try:
        root = _private_root(root)
        return SecureJSONRecordStore(root, max_bytes=8192).read(name)
    except (StateError, OSError) as exc:
        raise RalphError("Ralph terminal receipt is malformed or inaccessible") from exc


def _receipt(launch: RalphLaunch, data_root: Path) -> dict[str, Any] | None:
    value = _read_private_json(data_root, launch.receipt_name)
    if value is None:
        return None
    status = value.get("status")
    if value.get("version") != 1 or status not in {"running", "completed", "failed"}:
        raise RalphError("Ralph terminal receipt is malformed or inaccessible")
    if status == "running":
        if type(value.get("ralph_pid")) is not int or value["ralph_pid"] <= 0:
            raise RalphError("Ralph terminal receipt is malformed or inaccessible")
        return {"status": "running"}
    if type(value.get("exit_code")) is not int or not isinstance(value.get("completed_at"), (int, float)):
        raise RalphError("Ralph terminal receipt is malformed or inaccessible")
    return {"status": status, "exit_code": value["exit_code"]}


def read_ralph_receipt(data_root: Path, launch_id: str) -> dict[str, Any] | None:
    """Read only the bounded, token-free public terminal receipt fields."""
    stdout_name, stderr_name, receipt_name = _private_names(launch_id)
    del stdout_name, stderr_name
    launch = RalphLaunch(ProcessIdentity(1, "receipt", 1, "a" * 64), launch_id, "", "", receipt_name)
    return _receipt(launch, Path(data_root).resolve(strict=False))


def read_ralph_output(data_root: Path, launch_id: str, stream: str, *, limit: int = 4096) -> str:
    if stream not in {"stdout", "stderr"} or type(limit) is not int or not 0 < limit <= MAX_OUTPUT_BYTES:
        raise RalphError("invalid Ralph output request")
    stdout_name, stderr_name, _ = _private_names(launch_id)
    root = _private_root(Path(data_root))
    path = root / (stdout_name if stream == "stdout" else stderr_name)
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise RalphError("Ralph private output is unavailable")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            size = os.fstat(fd).st_size
            os.lseek(fd, max(0, size - limit), os.SEEK_SET)
            raw = os.read(fd, limit)
        finally:
            os.close(fd)
    except RalphError:
        raise
    except OSError as exc:
        raise RalphError("Ralph private output is unavailable") from exc
    return raw.decode("utf-8", "replace")


def _spawn_backend(cwd: Path, marker: str, data_root: Path, launch_id: str) -> subprocess.Popen[bytes]:
    """Start a detached supervisor that owns Ralph's process group and pipes."""
    stdout_name, stderr_name, receipt_name = _private_names(launch_id)
    environment = dict(os.environ)
    environment[OWNERSHIP_MARKER_ENV] = marker
    runner = Path(__file__).with_name("ralph_runner.py")
    return subprocess.Popen([sys.executable, str(runner), "--data-root", str(data_root),
                             "--stdout-name", stdout_name, "--stderr-name", stderr_name,
                             "--receipt-name", receipt_name], cwd=cwd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True, env=environment)


def _group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except OSError:
        return False


def _same_process_identity(expected: ProcessIdentity, observed: ProcessIdentity | None) -> bool:
    return (observed is not None and expected.pid == observed.pid and expected.start == observed.start and
            expected.pgid == observed.pgid and expected.marker_digest is not None and
            secrets.compare_digest(expected.marker_digest, observed.marker_digest or ""))


def _matching_process_identity(expected: ProcessIdentity) -> ProcessIdentity | None:
    if not _valid_marker_digest(expected.marker_digest):
        return None
    observed = _identity(expected.pid, expected.marker_digest)
    return observed if _same_process_identity(expected, observed) else None


def _terminate_child(child: subprocess.Popen[bytes], *, grace_seconds: float) -> None:
    try:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=max(0.01, grace_seconds))
            except (subprocess.TimeoutExpired, OSError):
                if child.poll() is None:
                    child.kill()
                    try:
                        child.wait(timeout=max(0.01, grace_seconds))
                    except (subprocess.TimeoutExpired, OSError):
                        pass
    except OSError:
        pass


def _terminate_owned_group(expected: ProcessIdentity, child: subprocess.Popen[bytes], *,
                            grace_seconds: float = KILL_GRACE_SECONDS) -> None:
    current = _matching_process_identity(expected)
    if current is None:
        _terminate_child(child, grace_seconds=grace_seconds)
        return
    try:
        if not _group_exists(current.pgid):
            _terminate_child(child, grace_seconds=grace_seconds)
            return
        current = _matching_process_identity(expected)
        if current is None:
            _terminate_child(child, grace_seconds=grace_seconds)
            return
        os.killpg(current.pgid, signal.SIGTERM)
        deadline = time.monotonic() + max(0.01, grace_seconds)
        while time.monotonic() < deadline:
            current = _matching_process_identity(expected)
            if current is None or not _group_exists(current.pgid):
                return
            time.sleep(0.02)
        current = _matching_process_identity(expected)
        if current is None:
            _terminate_child(child, grace_seconds=grace_seconds)
            return
        if _group_exists(current.pgid):
            # A final identity check immediately precedes every group signal.
            current = _matching_process_identity(expected)
            if current is not None:
                os.killpg(current.pgid, signal.SIGKILL)
    except OSError:
        _terminate_child(child, grace_seconds=grace_seconds)
    finally:
        _terminate_child(child, grace_seconds=grace_seconds)


def _await_runner_ready(launch: RalphLaunch, data_root: Path, child: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        receipt = _receipt(launch, data_root)
        if receipt is not None:
            if receipt["status"] == "running":
                return
            # The state record remains recoverable; its terminal receipt will
            # make status deterministically fail rather than strand a launch.
            return
        if child.poll() is not None:
            return
        time.sleep(0.02)


def launch_ralph_dispatch(preparation: RalphPreparation, *, data_root: Path,
                          launch_id: str, on_spawn: Callable[[RalphLaunch], None] | None = None) -> RalphLaunch:
    """Return after an owned detached Ralph supervisor has been validated.

    The caller never waits for Ralph.  The supervisor drains output and writes
    the terminal receipt, so later status/cancel operations retain the same
    group-identity checks after this CLI process has exited.
    """
    root = _private_root(data_root)
    stdout_name, stderr_name, receipt_name = _private_names(launch_id)
    for name in (stdout_name, stderr_name):
        _create_private_file(root, name)
    marker = secrets.token_urlsafe(_MARKER_DIGEST_BYTES)
    marker_digest = _marker_digest(marker)
    try:
        child = _spawn_backend(preparation.cwd, marker, root, launch_id)
    except OSError as exc:
        _rollback(preparation)
        raise RalphError("Ralph launch failed before spawn") from exc
    # The Popen boundary is durable: no Git rollback after this point.
    identity = _identity(child.pid, marker_digest)
    if identity is None:
        _terminate_child(child, grace_seconds=KILL_GRACE_SECONDS)
        raise RalphError("Ralph process identity could not be established")
    launch = RalphLaunch(ProcessIdentity(identity.pid, identity.start, identity.pgid,
                                         encode_marker_digest(identity.marker_digest)),
                        launch_id, stdout_name, stderr_name, receipt_name)
    try:
        if on_spawn:
            on_spawn(launch)
        _await_runner_ready(launch, root, child)
        # Reap the detached supervisor in a live CLI process without making
        # launch synchronous. If the CLI exits first, normal parent-death
        # reparenting applies; if it remains alive, this avoids zombie children.
        threading.Thread(target=child.wait, daemon=True).start()
        return launch
    except Exception:
        _terminate_owned_group(identity, child, grace_seconds=KILL_GRACE_SECONDS)
        raise


def recover_ralph_status(record: Mapping[str, Any] | None, *,
                         identity: Callable[[int, str], ProcessIdentity | None] = _identity) -> dict[str, Any]:
    marker_digest = _decoded_marker_digest(record.get("marker_digest")) if isinstance(record, Mapping) else None
    if (not isinstance(record, Mapping) or type(record.get("pid")) is not int or
            marker_digest is None):
        return {"owned": False, "running": False, "reason": "no Ralph instance record"}
    observed = identity(record["pid"], marker_digest)
    if not _same_identity(record, observed):
        return {"owned": False, "running": False, "reason": "Ralph PID identity no longer matches"}
    if not _group_exists(observed.pgid):
        return {"owned": True, "running": False, "pid": observed.pid, "pgid": observed.pgid}
    return {"owned": True, "running": True, "pid": observed.pid, "pgid": observed.pgid}


def cancel_owned_ralph(record: Mapping[str, Any] | None, *, grace_seconds: float = KILL_GRACE_SECONDS,
                       identity: Callable[[int, str], ProcessIdentity | None] = _identity) -> dict[str, Any]:
    marker_digest = _decoded_marker_digest(record.get("marker_digest")) if isinstance(record, Mapping) else None
    if (not isinstance(record, Mapping) or type(record.get("pid")) is not int or
            marker_digest is None):
        raise RalphError("Ralph instance is not owned")
    # Acquire then immediately reacquire identity before TERM so no intervening
    # PID/PGID reuse or marker loss can redirect a group signal.
    current = identity(record["pid"], marker_digest)
    if not _same_identity(record, current):
        raise RalphError("Ralph PID identity no longer matches; refusing to signal")
    current = identity(record["pid"], marker_digest)
    if not _same_identity(record, current):
        raise RalphError("Ralph PID identity no longer matches; refusing to signal")
    try:
        os.killpg(current.pgid, signal.SIGTERM)
    except OSError:
        return {"cancelled": False, "owned": True, "running": False}
    deadline = time.monotonic() + max(0.01, grace_seconds)
    while time.monotonic() < deadline:
        current = identity(record["pid"], marker_digest)
        if not _same_identity(record, current):
            return {"cancelled": True, "owned": True, "running": False}
        time.sleep(0.02)
    # Revalidate the leader identity immediately before escalation. Once it is
    # gone, reused, or no longer proves the launch marker, a recycled process
    # group is never signalled.
    current = identity(record["pid"], marker_digest)
    if not _same_identity(record, current):
        return {"cancelled": True, "owned": True, "running": False}
    try:
        os.killpg(current.pgid, signal.SIGKILL)
    except OSError:
        return {"cancelled": False, "owned": True, "running": False}
    return {"cancelled": True, "owned": True, "running": False, "forced": True}
