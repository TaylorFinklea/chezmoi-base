"""Fail-closed Codex Ralph preparation, launch, recovery, and cancellation."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import threading
import time
from typing import Any, Callable, Mapping, Sequence

from .brief import Brief, Phase

MAX_OUTPUT_BYTES = 64 * 1024
MAX_OUTPUT_LINES = 200
KILL_GRACE_SECONDS = 2.0
FORGE_PATHS = (".docs/ai/current-state.md", ".docs/ai/roadmap.md")


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


@dataclass(frozen=True)
class RalphResult:
    exit_code: int
    stdout: str
    stderr: str


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


def _rollback(preparation: RalphPreparation) -> None:
    rollback_error: Exception | None = None
    try:
        head = _run(["git", "rev-parse", "HEAD"], preparation.cwd, check=True).stdout.strip()
        if head == preparation.planning_commit:
            _run(["git", "reset", "--soft", preparation.before_head], preparation.cwd, check=True)
            _run(["git", "reset", "--", *preparation.paths], preparation.cwd, check=True)
    except Exception as exc:
        rollback_error = exc
    finally:
        _restore(preparation.cwd, preparation.snapshots)
    if rollback_error is not None:
        raise RalphError("Forge planning rollback could not be completed") from rollback_error


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
    try:
        current = _render_current_state(_read_structural(_safe_path(cwd, FORGE_PATHS[0])), brief.phases)
        roadmap = _render_roadmap(_read_structural(_safe_path(cwd, FORGE_PATHS[1])), brief)
        generated = _render_phase_spec(brief, date)
        for relative_path, content in ((FORGE_PATHS[0], current), (FORGE_PATHS[1], roadmap),
                                       (_phase_spec_path(brief), generated)):
            path = _safe_path(cwd, relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="")
        baseline = _snapshot(cwd, paths)
        status_before = _run(["git", "status", "--porcelain"], cwd, check=True).stdout
        preflight = _run(["ralph", "-n", "0", "-t", "codex"], cwd, check=False)
        if preflight.returncode:
            detail = (preflight.stderr or preflight.stdout).strip()
            raise RalphError("Ralph preflight failed" + (f": {detail}" if detail else ""))
        if _snapshot(cwd, paths) != baseline:
            raise RalphError("Ralph preflight modified Forge handoff bytes")
        if _run(["git", "status", "--porcelain"], cwd, check=True).stdout != status_before:
            raise RalphError("Ralph preflight modified the worktree")
        _run(["git", "add", "--", *paths], cwd, check=True)
        staged = _run(["git", "diff", "--cached", "--name-only", "--", *paths], cwd, check=True)
        if set(staged.stdout.splitlines()) != set(paths):
            raise RalphError("Forge planning commit contains unexpected files")
        _run(["git", "commit", "-m", f"plan: prepare Forge Ralph execution for {brief.goal}"], cwd, check=True)
        planning_commit = _run(["git", "rev-parse", "HEAD"], cwd, check=True).stdout.strip()
        if not planning_commit:
            raise RalphError("Forge planning commit could not be identified")
        return RalphPreparation(cwd, tuple(paths), snapshots, before_head, planning_commit)
    except Exception:
        _restore_preparation_failure(cwd, snapshots, paths)
        raise


def _bounded_raw(value: bytes) -> bytes:
    lines = value.splitlines(keepends=True)[-MAX_OUTPUT_LINES:]
    return b"".join(lines)[-MAX_OUTPUT_BYTES:]


def _bounded(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    text = _bounded_raw(raw).decode("utf-8", "replace")
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_OUTPUT_BYTES:
        return text
    return encoded[-MAX_OUTPUT_BYTES:].decode("utf-8", "ignore")


def _append_bounded(previous: bytes, chunk: bytes) -> bytes:
    return _bounded_raw(previous + chunk)


def _identity(pid: int) -> ProcessIdentity | None:
    if type(pid) is not int or pid <= 0:
        return None
    try:
        pgid = os.getpgid(pid)
    except OSError:
        return None
    proc = Path(f"/proc/{pid}/stat")
    if proc.exists():
        try:
            _, _, fields = proc.read_text(encoding="ascii").rpartition(") ")
            return ProcessIdentity(pid, fields.split()[19], pgid)
        except (OSError, UnicodeError, IndexError):
            return None
    try:
        result = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    start = result.stdout.strip()
    return ProcessIdentity(pid, start, pgid) if result.returncode == 0 and start else None


def _same_identity(record: Mapping[str, Any], identity: ProcessIdentity | None) -> bool:
    return (identity is not None and type(record.get("pid")) is int and
            type(record.get("pgid")) is int and isinstance(record.get("start"), str) and
            record["pid"] == identity.pid and record["pgid"] == identity.pgid and
            record["start"] == identity.start)


def _spawn_backend(cwd: Path) -> subprocess.Popen[bytes]:
    """Spawn only the Ralph backend; Git commands deliberately use ``_run``."""
    return subprocess.Popen(["ralph", "-t", "codex"], cwd=cwd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            start_new_session=True)


def _close_pipes(child: subprocess.Popen[bytes]) -> None:
    for stream in (child.stdout, child.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass


def _group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except OSError:
        return False


def _terminate_group(pgid: int, child: subprocess.Popen[bytes], *, grace_seconds: float = KILL_GRACE_SECONDS) -> None:
    try:
        if _group_exists(pgid):
            try:
                os.killpg(pgid, signal.SIGTERM)
            except OSError:
                pass
            else:
                deadline = time.monotonic() + max(0.01, grace_seconds)
                while time.monotonic() < deadline:
                    if not _group_exists(pgid):
                        break
                    time.sleep(0.02)
                else:
                    if _group_exists(pgid):
                        try:
                            os.killpg(pgid, signal.SIGKILL)
                        except OSError:
                            pass
    finally:
        # Reap even when the group already disappeared; otherwise a failed
        # post-spawn callback can leave a zombie Popen object behind.
        try:
            child.wait(timeout=max(0.01, grace_seconds))
        except (subprocess.TimeoutExpired, OSError):
            pass


def _capture_pipe(stream: Any, buffer: list[bytes]) -> None:
    try:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            buffer[0] = _append_bounded(buffer[0], chunk)
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _run_backend(cwd: Path, *, on_started: Callable[[], None] | None = None,
                 on_spawn: Callable[[ProcessIdentity], None] | None = None,
                 on_output: Callable[[str, str], None] | None = None) -> RalphResult:
    try:
        child = _spawn_backend(cwd)
    except OSError as exc:
        raise RalphError("Ralph launch failed before spawn") from exc

    # This is the transaction boundary: after Popen returns no Git rewind is
    # permitted, including if a later reader or identity operation fails.
    if on_started:
        on_started()
    stdout: list[bytes] = [b""]
    stderr: list[bytes] = [b""]
    readers = [
        threading.Thread(target=_capture_pipe, args=(child.stdout, stdout), daemon=True),
        threading.Thread(target=_capture_pipe, args=(child.stderr, stderr), daemon=True),
    ]

    try:
        for reader in readers:
            reader.start()
        identity = _identity(child.pid)
        if identity is None:
            raise RalphError("Ralph process identity could not be established")
        if on_spawn:
            on_spawn(identity)
        exit_code = child.wait()
        # The dedicated session is owned by this launch. A backend that exits
        # while leaving descendants behind must not leave an uncontrolled group.
        _terminate_group(identity.pgid, child, grace_seconds=KILL_GRACE_SECONDS)
        for reader in readers:
            if reader.is_alive():
                reader.join(timeout=KILL_GRACE_SECONDS)
        _close_pipes(child)
        out = _bounded(stdout[0])
        err = _bounded(stderr[0])
        if on_output:
            if out:
                on_output("stdout", out)
            if err:
                on_output("stderr", err)
        return RalphResult(exit_code, out, err)
    except Exception:
        _terminate_group(child.pid, child, grace_seconds=KILL_GRACE_SECONDS)
        raise
    finally:
        _close_pipes(child)
        for reader in readers:
            if reader.is_alive():
                reader.join(timeout=KILL_GRACE_SECONDS)


def launch_ralph_dispatch(preparation: RalphPreparation, *, on_spawn: Callable[[ProcessIdentity], None] | None = None,
                          on_output: Callable[[str, str], None] | None = None) -> RalphResult:
    spawned = False

    def started_callback() -> None:
        nonlocal spawned
        spawned = True

    try:
        return _run_backend(preparation.cwd, on_started=started_callback, on_spawn=on_spawn,
                            on_output=on_output)
    except Exception:
        # Only a failure before Popen returns may rewind Forge's planning commit.
        # Once a backend process existed, even a later persistence failure retains
        # the durable plan rather than rewriting Git history after dispatch.
        if not spawned:
            _rollback(preparation)
        raise


def recover_ralph_status(record: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(record, Mapping) or type(record.get("pid")) is not int:
        return {"owned": False, "running": False, "reason": "no Ralph instance record"}
    identity = _identity(record["pid"])
    if not _same_identity(record, identity):
        return {"owned": False, "running": False, "reason": "Ralph PID identity no longer matches"}
    if not _group_exists(identity.pgid):
        return {"owned": True, "running": False, "pid": identity.pid, "pgid": identity.pgid}
    return {"owned": True, "running": True, "pid": identity.pid, "pgid": identity.pgid}


def cancel_owned_ralph(record: Mapping[str, Any] | None, *, grace_seconds: float = KILL_GRACE_SECONDS,
                       identity: Callable[[int], ProcessIdentity | None] = _identity) -> dict[str, Any]:
    if not isinstance(record, Mapping) or type(record.get("pid")) is not int:
        raise RalphError("Ralph instance is not owned")
    current = identity(record["pid"])
    if not _same_identity(record, current):
        raise RalphError("Ralph PID identity no longer matches; refusing to signal")
    try:
        os.killpg(current.pgid, signal.SIGTERM)
    except OSError:
        return {"cancelled": False, "owned": True, "running": False}
    deadline = time.monotonic() + max(0.01, grace_seconds)
    while time.monotonic() < deadline:
        current = identity(record["pid"])
        if not _same_identity(record, current):
            return {"cancelled": True, "owned": True, "running": False}
        time.sleep(0.02)
    # Revalidate the leader identity immediately before escalation. Once it is
    # gone or reused, a recycled process group is never signalled.
    current = identity(record["pid"])
    if not _same_identity(record, current):
        return {"cancelled": True, "owned": True, "running": False}
    try:
        os.killpg(current.pgid, signal.SIGKILL)
    except OSError:
        return {"cancelled": False, "owned": True, "running": False}
    return {"cancelled": True, "owned": True, "running": False, "forced": True}
