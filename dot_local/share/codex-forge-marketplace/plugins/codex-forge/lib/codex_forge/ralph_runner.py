"""Detached, stdlib-only Ralph supervisor used by Codex Forge.

The launcher owns this process group. This process waits on a private, one-use
parent gate before it can start real Ralph, then drains both pipes into bounded
private tail files and atomically publishes a receipt for later recovery.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import threading
import time

MAX_OUTPUT_BYTES = 64 * 1024
MAX_OUTPUT_LINES = 200
GATE_WAIT_SECONDS = 5.0
GATE_POLL_SECONDS = 0.02
REDACTED = b"[REDACTED]"
GATE_PENDING = b"waiting\n"
GATE_ARMED = b"armed\n"
MARKER_ENV = "CODEX_FORGE_RALPH_OWNERSHIP_MARKER"
_NAME_RE = re.compile(
    r"ralph-(?:(?:stdout|stderr)-[0-9a-f]{64}\.log|receipt-[0-9a-f]{64}\.json|gate-[0-9a-f]{64}\.gate)"
)


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
        os.write(fd, raw)
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


def _gate_is_armed(root: Path, name: str) -> bool:
    path, expected = _private_regular(root, name)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        observed = os.fstat(fd)
        if (not stat.S_ISREG(observed.st_mode) or observed.st_ino != expected.st_ino or
                observed.st_dev != expected.st_dev):
            raise ValueError("private Ralph gate changed")
        raw = os.read(fd, max(len(GATE_PENDING), len(GATE_ARMED)) + 1)
        if os.read(fd, 1):
            raise ValueError("invalid private Ralph gate")
    finally:
        os.close(fd)
    if raw == GATE_PENDING:
        return False
    if raw != GATE_ARMED:
        raise ValueError("invalid private Ralph gate")
    current = path.lstat()
    if (current.st_ino != expected.st_ino or current.st_dev != expected.st_dev or
            stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode)):
        raise ValueError("private Ralph gate changed")
    path.unlink()
    directory = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return True


def _await_gate(root: Path, name: str, stop_signal: list[int]) -> bool:
    deadline = time.monotonic() + GATE_WAIT_SECONDS
    while time.monotonic() < deadline:
        if stop_signal:
            return False
        if _gate_is_armed(root, name):
            return True
        time.sleep(GATE_POLL_SECONDS)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--stdout-name", required=True)
    parser.add_argument("--stderr-name", required=True)
    parser.add_argument("--receipt-name", required=True)
    parser.add_argument("--gate-name", required=True)
    args = parser.parse_args(argv)
    root = _root(args.data_root)
    marker = os.environ.get(MARKER_ENV, "")
    secrets = tuple(item for item in (
        marker.encode("utf-8"), hashlib.sha256(marker.encode("utf-8")).hexdigest().encode("ascii")
    ) if item)
    # Secrets are final before either pipe can be read; carry must cover every
    # token/digest split across the 8192-byte streaming reads.
    stdout_sink = _TailFile(_open_log(root, args.stdout_name), secrets)
    stderr_sink = _TailFile(_open_log(root, args.stderr_name), secrets)
    _private_regular(root, args.receipt_name)
    child: subprocess.Popen[bytes] | None = None
    exit_code = 127
    started = False
    stop_signal: list[int] = []

    def stopped(signum: int, _frame: object) -> None:
        stop_signal.append(signum)

    signal.signal(signal.SIGTERM, stopped)
    signal.signal(signal.SIGINT, stopped)
    try:
        _private_regular(root, args.gate_name)
        if not _await_gate(root, args.gate_name, stop_signal):
            stderr_sink.append(b"Ralph supervisor gate was not armed\n")
        else:
            child = subprocess.Popen(["ralph", "-t", "codex"], stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=os.getcwd())
            started = True
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
    finally:
        stdout_sink.close()
        stderr_sink.close()
        _atomic_receipt(root, args.receipt_name, {
            "version": 1,
            "status": "completed" if exit_code == 0 else "failed",
            "exit_code": int(exit_code),
            "completed_at": time.time(),
            "interrupted": bool(stop_signal),
        })
    return 0 if exit_code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
