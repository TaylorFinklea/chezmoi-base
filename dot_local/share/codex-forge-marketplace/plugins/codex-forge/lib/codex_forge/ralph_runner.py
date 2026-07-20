"""Detached, stdlib-only Ralph supervisor used by Codex Forge.

The launcher owns this process group.  The supervisor cannot call real Ralph
until it consumes one inherited arm byte; it acknowledges only after the real
``ralph -t codex`` Popen succeeds.  Pipe EOF before that byte is a durable
pre-arm abort, not a timeout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import stat
import subprocess
import sys
import threading
import time

MAX_OUTPUT_BYTES = 64 * 1024
MAX_OUTPUT_LINES = 200
REDACTED = b"[REDACTED]"
ARM_BYTE = b"A"
ACK_SPAWNED = b"S"
ACK_SPAWN_FAILED = b"F"
MARKER_ENV = "CODEX_FORGE_RALPH_OWNERSHIP_MARKER"
_NAME_RE = re.compile(r"ralph-(?:(?:stdout|stderr)-[0-9a-f]{64}\.log|receipt-[0-9a-f]{64}\.json)")


def _safe_name(value: str) -> str:
    if not _NAME_RE.fullmatch(value):
        raise ValueError("invalid private Ralph file name")
    return value


def _root(path: str) -> Path:
    root = Path(path)
    info = root.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("invalid private Ralph data root")
    return root


def _private_regular(root: Path, name: str) -> tuple[Path, os.stat_result]:
    path = root / _safe_name(name)
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or
            stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
        raise ValueError("invalid private Ralph file")
    return path, info


def _open_log(root: Path, name: str) -> int:
    path, expected = _private_regular(root, name)
    fd = os.open(path, os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    observed = os.fstat(fd)
    if (not stat.S_ISREG(observed.st_mode) or observed.st_ino != expected.st_ino or
            observed.st_dev != expected.st_dev):
        os.close(fd)
        raise ValueError("invalid private Ralph output file")
    return fd


def _atomic_receipt(root: Path, name: str, payload: dict[str, object]) -> None:
    target = root / _safe_name(name)
    try:
        _private_regular(root, name)
    except FileNotFoundError:
        pass
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    temp = root / ("." + name + "." + str(os.getpid()) + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        view = memoryview(raw)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.replace(temp, target)
        os.chmod(target, 0o600)
        directory = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        raise


def _tail(value: bytes) -> bytes:
    return b"".join(value.splitlines(keepends=True)[-MAX_OUTPUT_LINES:])[-MAX_OUTPUT_BYTES:]


def _redact(value: bytes, secrets: tuple[bytes, ...]) -> bytes:
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        value = value.replace(secret, REDACTED)
    return value


class _TailFile:
    def __init__(self, fd: int, secrets: tuple[bytes, ...]):
        self.fd = fd
        self.secrets = secrets
        self.carry = max((len(item) for item in secrets), default=1)
        self.pending = b""
        self.value = b""
        self.lock = threading.Lock()

    def append(self, chunk: bytes) -> None:
        with self.lock:
            self.pending += chunk
            if len(self.pending) > self.carry:
                cut = self._safe_cut()
                if cut:
                    emit, self.pending = self.pending[:cut], self.pending[cut:]
                    self.value = _tail(self.value + _redact(emit, self.secrets))
                    self._publish()

    def _safe_cut(self) -> int:
        """Keep every raw secret that would otherwise straddle an emission."""
        cut = len(self.pending) - self.carry
        changed = True
        while changed:
            changed = False
            for secret in self.secrets:
                if not secret:
                    continue
                start = self.pending.find(secret)
                while start >= 0:
                    end = start + len(secret)
                    if start < cut < end:
                        cut = start
                        changed = True
                        break
                    start = self.pending.find(secret, start + 1)
                if changed:
                    break
        return cut

    def close(self) -> None:
        with self.lock:
            self.value = _tail(self.value + _redact(self.pending, self.secrets))
            self.pending = b""
            self._publish()
            os.fsync(self.fd)
            os.close(self.fd)

    def _publish(self) -> None:
        os.lseek(self.fd, 0, os.SEEK_SET)
        os.ftruncate(self.fd, 0)
        view = memoryview(self.value)
        while view:
            view = view[os.write(self.fd, view):]


def _drain(stream: object, sink: _TailFile) -> None:
    try:
        while True:
            chunk = stream.read(8192)  # type: ignore[attr-defined]
            if not chunk:
                return
            sink.append(chunk)
    finally:
        try:
            stream.close()  # type: ignore[attr-defined]
        except OSError:
            pass


def _pipe_fd(value: str) -> int:
    try:
        fd = int(value)
    except ValueError as exc:
        raise ValueError("invalid inherited Ralph pipe") from exc
    if fd < 0 or not stat.S_ISFIFO(os.fstat(fd).st_mode):
        raise ValueError("invalid inherited Ralph pipe")
    return fd


def _await_arm(fd: int, stop_signal: list[int]) -> bool:
    """Wait indefinitely for one exact arm byte; EOF proves a pre-arm abort."""
    try:
        while not stop_signal:
            readable, _, _ = select.select([fd], [], [], 0.1)
            if not readable:
                continue
            arm = os.read(fd, 1)
            if arm != ARM_BYTE:
                return False
            # The launcher closes immediately after the one atomic byte.  A
            # second byte is protocol corruption; EOF completes the exact arm.
            while not stop_signal:
                readable, _, _ = select.select([fd], [], [], 0.1)
                if readable:
                    return os.read(fd, 1) == b""
            return False
        return False
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _acknowledge(fd: int, value: bytes) -> None:
    try:
        if value not in {ACK_SPAWNED, ACK_SPAWN_FAILED} or os.write(fd, value) != 1:
            raise OSError("could not acknowledge Ralph supervisor")
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--stdout-name", required=True)
    parser.add_argument("--stderr-name", required=True)
    parser.add_argument("--receipt-name", required=True)
    parser.add_argument("--arm-fd", required=True)
    parser.add_argument("--ack-fd", required=True)
    args = parser.parse_args(argv)
    root = _root(args.data_root)
    arm_fd = _pipe_fd(args.arm_fd)
    acknowledgement_fd = _pipe_fd(args.ack_fd)
    if arm_fd == acknowledgement_fd:
        raise ValueError("invalid inherited Ralph pipe")
    marker = os.environ.get(MARKER_ENV, "")
    secrets = tuple(item for item in (
        marker.encode("utf-8"), hashlib.sha256(marker.encode("utf-8")).hexdigest().encode("ascii")
    ) if item)
    stdout_sink = _TailFile(_open_log(root, args.stdout_name), secrets)
    stderr_sink = _TailFile(_open_log(root, args.stderr_name), secrets)
    _private_regular(root, args.receipt_name)
    child: subprocess.Popen[bytes] | None = None
    exit_code = 127
    started = False
    acknowledgement_sent = False
    stop_signal: list[int] = []

    def stopped(signum: int, _frame: object) -> None:
        stop_signal.append(signum)

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, stopped)
        signal.signal(signal.SIGINT, stopped)
    try:
        if not _await_arm(arm_fd, stop_signal):
            stderr_sink.append(b"Ralph supervisor pre-arm abort\n")
            _atomic_receipt(root, args.receipt_name, {
                "version": 1, "status": "prearm_aborted", "completed_at": time.time(),
            })
        else:
            try:
                child = subprocess.Popen(["ralph", "-t", "codex"], stdin=subprocess.DEVNULL,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=os.getcwd(),
                                         close_fds=True)
            except (OSError, subprocess.SubprocessError):
                stderr_sink.append(b"Ralph supervisor could not start Ralph\n")
                _atomic_receipt(root, args.receipt_name, {
                    "version": 1, "status": "spawn_failed", "completed_at": time.time(),
                })
                _acknowledge(acknowledgement_fd, ACK_SPAWN_FAILED)
                acknowledgement_sent = True
            else:
                started = True
                # Receipt publication is the durable real-Popen boundary.  The
                # acknowledgement is deliberately later than this write.
                _atomic_receipt(root, args.receipt_name, {
                    "version": 1, "status": "spawned", "ralph_pid": child.pid, "started_at": time.time(),
                })
                _acknowledge(acknowledgement_fd, ACK_SPAWNED)
                acknowledgement_sent = True
                _atomic_receipt(root, args.receipt_name, {
                    "version": 1, "status": "running", "ralph_pid": child.pid, "started_at": time.time(),
                })
                readers = [threading.Thread(target=_drain, args=(child.stdout, stdout_sink), daemon=True),
                           threading.Thread(target=_drain, args=(child.stderr, stderr_sink), daemon=True)]
                for reader in readers:
                    reader.start()
                while child.poll() is None:
                    if stop_signal:
                        child.terminate()
                    try:
                        exit_code = child.wait(timeout=0.1)
                    except subprocess.TimeoutExpired:
                        continue
                exit_code = child.returncode if child.returncode is not None else exit_code
                for reader in readers:
                    reader.join(timeout=2)
    except BaseException as exc:
        if child is not None and child.poll() is None:
            try:
                child.terminate()
                exit_code = child.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    child.kill()
                    exit_code = child.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    exit_code = 127
        if not started:
            stderr_sink.append((f"Ralph supervisor failed: {type(exc).__name__}\n").encode("utf-8"))
            if not acknowledgement_sent:
                try:
                    _atomic_receipt(root, args.receipt_name, {
                        "version": 1, "status": "spawn_failed", "completed_at": time.time(),
                    })
                    _acknowledge(acknowledgement_fd, ACK_SPAWN_FAILED)
                    acknowledgement_sent = True
                except OSError:
                    pass
    finally:
        if not acknowledgement_sent:
            try:
                os.close(acknowledgement_fd)
            except OSError:
                pass
        stdout_sink.close()
        stderr_sink.close()
        if started:
            _atomic_receipt(root, args.receipt_name, {
                "version": 1,
                "status": "completed" if exit_code == 0 else "failed",
                "exit_code": int(exit_code),
                "completed_at": time.time(),
                "interrupted": bool(stop_signal),
            })
    return 0 if started and exit_code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
