"""Detached, stdlib-only Ralph supervisor used by Codex Forge.

The launcher owns this process group.  This process starts the real Ralph child
in that group, continuously drains both pipes into bounded private tail files,
and atomically publishes a receipt for recovery after the CLI exits.
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
REDACTED = b"[REDACTED]"
MARKER_ENV = "CODEX_FORGE_RALPH_OWNERSHIP_MARKER"
_NAME_RE = re.compile(r"ralph-(?:stdout|stderr|receipt)-[0-9a-f]{64}\.(?:log|json)")


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


def _open_log(root: Path, name: str) -> int:
    path = root / _safe_name(name)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError("invalid private Ralph output file")
    return os.open(path, os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)


def _atomic_receipt(root: Path, name: str, payload: dict[str, object]) -> None:
    target = root / _safe_name(name)
    try:
        info = target.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ValueError("invalid private Ralph receipt")
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

    def append(self, chunk: bytes) -> None:
        self.pending += chunk
        if len(self.pending) > self.carry:
            emit, self.pending = self.pending[:-self.carry], self.pending[-self.carry:]
            self.value = _tail(self.value + _redact(emit, self.secrets))
            self._publish()

    def close(self) -> None:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--stdout-name", required=True)
    parser.add_argument("--stderr-name", required=True)
    parser.add_argument("--receipt-name", required=True)
    args = parser.parse_args(argv)
    root = _root(args.data_root)
    stdout_sink = _TailFile(_open_log(root, args.stdout_name), ())
    stderr_sink = _TailFile(_open_log(root, args.stderr_name), ())
    marker = os.environ.get(MARKER_ENV, "")
    secrets = tuple(item for item in (marker.encode("utf-8"), hashlib.sha256(marker.encode("utf-8")).hexdigest().encode("ascii")) if item)
    stdout_sink.secrets = secrets
    stderr_sink.secrets = secrets
    child: subprocess.Popen[bytes] | None = None
    exit_code = 127
    started = False
    stop_signal: list[int] = []

    def stopped(signum: int, _frame: object) -> None:
        stop_signal.append(signum)

    signal.signal(signal.SIGTERM, stopped)
    signal.signal(signal.SIGINT, stopped)
    try:
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
