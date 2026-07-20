"""Private, fail-closed persistence for Codex Forge lifecycle state."""

from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Any, Optional

SCHEMA_VERSION = 1
PLUGIN_VERSION = "0.1.0"
_STATUSES = frozenset({
    "shaping", "frozen", "approved_direct", "approved_ralph", "executing",
    "ralph_running", "completed", "cancelled", "failed",
})


class StateError(ValueError):
    pass


@dataclass(frozen=True)
class RepoIdentity:
    root: Path
    head: Optional[str] = None
    git_dir: Optional[Path] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))
        if self.git_dir is not None:
            object.__setattr__(self, "git_dir", Path(self.git_dir))


@dataclass(frozen=True)
class ForgeState:
    session_id: str
    cwd: Path
    repo: Optional[RepoIdentity]
    status: str = "shaping"
    schema_version: int = SCHEMA_VERSION
    plugin_version: str = PLUGIN_VERSION


_ALLOWED = {
    "shaping": {"freeze": "frozen", "cancel": "cancelled", "fail": "failed"},
    "frozen": {"revise": "shaping", "approve_direct": "approved_direct", "approve_ralph": "approved_ralph", "cancel": "cancelled", "fail": "failed"},
    "approved_direct": {"begin": "executing", "cancel": "cancelled", "fail": "failed"},
    "approved_ralph": {"ralph_start": "ralph_running", "cancel": "cancelled", "fail": "failed"},
    "executing": {"complete": "completed", "cancel": "cancelled", "fail": "failed"},
    "ralph_running": {"complete": "completed", "cancel": "cancelled", "fail": "failed"},
    "completed": {},
    "cancelled": {},
    "failed": {},
}


def transition(state: ForgeState, event: str) -> ForgeState:
    if not isinstance(state, ForgeState) or state.status not in _STATUSES:
        raise ValueError("invalid state")
    try:
        status = _ALLOWED[state.status][event]
    except (KeyError, TypeError):
        raise ValueError(f"event {event!r} is not allowed from {state.status!r}") from None
    return replace(state, status=status)


def _valid_session_id(session_id: str) -> None:
    if not isinstance(session_id, str) or not session_id or session_id in (".", ".."):
        raise ValueError("invalid session identifier")
    if any(char in session_id for char in ("/", "\\", "\x00")):
        raise ValueError("session identifier must not contain path characters")


def _canonical_directory(path: Path, field: str) -> Path:
    path = Path(path)
    try:
        result = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{field} is not accessible") from exc
    if not result.is_dir():
        raise ValueError(f"{field} must be a directory")
    return result


def _repo_for_create(cwd: Path, repo: Optional[RepoIdentity]) -> Optional[RepoIdentity]:
    if repo is None:
        return None
    root = _canonical_directory(repo.root, "repository root")
    try:
        cwd.relative_to(root)
    except ValueError as exc:
        raise ValueError("cwd is outside repository root") from exc
    git_dir = None
    if repo.git_dir is not None:
        git_dir = Path(repo.git_dir).resolve(strict=True)
    return RepoIdentity(root, repo.head, git_dir)


def _state_payload(state: ForgeState) -> dict[str, Any]:
    repo = None
    if state.repo is not None:
        repo = {"root": str(state.repo.root), "head": state.repo.head,
                "git_dir": str(state.repo.git_dir) if state.repo.git_dir is not None else None}
    return {
        "schema_version": state.schema_version,
        "plugin_version": state.plugin_version,
        "session_id": state.session_id,
        "cwd": str(state.cwd),
        "repo": repo,
        "status": state.status,
    }


def _state_from_payload(payload: Any) -> ForgeState:
    keys = {"schema_version", "plugin_version", "session_id", "cwd", "repo", "status"}
    if not isinstance(payload, dict) or set(payload) != keys:
        raise StateError("invalid state shape")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != SCHEMA_VERSION:
        raise StateError("unsupported state schema")
    if not isinstance(payload["plugin_version"], str) or not payload["plugin_version"]:
        raise StateError("invalid plugin version")
    _valid_session_id(payload["session_id"])
    if not isinstance(payload["cwd"], str) or not Path(payload["cwd"]).is_absolute():
        raise StateError("invalid canonical cwd")
    cwd = Path(payload["cwd"])
    if not cwd.is_absolute() or cwd != cwd.resolve():
        raise StateError("cwd is not canonical")
    if payload["status"] not in _STATUSES:
        raise StateError("invalid lifecycle status")
    raw_repo = payload["repo"]
    repo = None
    if raw_repo is not None:
        if not isinstance(raw_repo, dict) or set(raw_repo) != {"root", "head", "git_dir"}:
            raise StateError("invalid repository identity")
        if not isinstance(raw_repo["root"], str) or not Path(raw_repo["root"]).is_absolute():
            raise StateError("invalid repository root")
        root = Path(raw_repo["root"])
        if root != root.resolve():
            raise StateError("repository root is not canonical")
        if raw_repo["head"] is not None and not isinstance(raw_repo["head"], str):
            raise StateError("invalid repository head")
        if raw_repo["git_dir"] is not None and (not isinstance(raw_repo["git_dir"], str) or not Path(raw_repo["git_dir"]).is_absolute()):
            raise StateError("invalid git directory")
        git_dir = Path(raw_repo["git_dir"]) if raw_repo["git_dir"] else None
        if git_dir is not None and git_dir != git_dir.resolve():
            raise StateError("git directory is not canonical")
        repo = RepoIdentity(root, raw_repo["head"], git_dir)
        try:
            cwd.relative_to(repo.root)
        except ValueError as exc:
            raise StateError("cwd is outside repository root") from exc
    return ForgeState(payload["session_id"], cwd, repo, payload["status"],
                      payload["schema_version"], payload["plugin_version"])


class StateStore:
    def __init__(self, data_root: Path, plugin_version: str):
        self.data_root = Path(data_root)
        self.plugin_version = plugin_version
        if not isinstance(plugin_version, str) or not plugin_version:
            raise ValueError("plugin_version is required")

    def _ensure_root(self) -> None:
        if self.data_root.exists() or self.data_root.is_symlink():
            if self.data_root.is_symlink() or not self.data_root.is_dir():
                raise StateError("state root must be a directory")
        else:
            self.data_root.mkdir(parents=True, mode=0o700)
        os.chmod(self.data_root, 0o700)

    def path_for(self, session_id: str) -> Path:
        _valid_session_id(session_id)
        return self.data_root / hashlib.sha256(session_id.encode("utf-8")).hexdigest()

    def _check_record(self, path: Path) -> None:
        try:
            info = path.lstat()
        except FileNotFoundError:
            return
        if stat_is_symlink(info) or not stat_is_regular(info):
            raise StateError("state record must be a regular file")

    def load(self, session_id: str) -> Optional[ForgeState]:
        path = self.path_for(session_id)
        if not self.data_root.exists():
            return None
        self._check_record(path)
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StateError("cannot open state record") from exc
        try:
            if not stat_is_regular(os.fstat(fd)):
                raise StateError("state record must be regular")
            try:
                raw = os.read(fd, 10 * 1024 * 1024)
                text = raw.decode("utf-8")
                payload = json.loads(text)
            except (UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
                raise StateError("corrupt state record") from exc
        finally:
            os.close(fd)
        state = _state_from_payload(payload)
        if state.session_id != session_id:
            raise StateError("session binding mismatch")
        if state.plugin_version != self.plugin_version:
            raise StateError("plugin version mismatch")
        return state

    def create(self, session_id: str, cwd: Path, repo: Optional[RepoIdentity]) -> ForgeState:
        _valid_session_id(session_id)
        canonical_cwd = _canonical_directory(cwd, "cwd")
        canonical_repo = _repo_for_create(canonical_cwd, repo)
        self._ensure_root()
        path = self.path_for(session_id)
        if path.exists() or path.is_symlink():
            raise StateError("state already exists")
        state = ForgeState(session_id, canonical_cwd, canonical_repo, "shaping", SCHEMA_VERSION, self.plugin_version)
        self.replace(state)
        return state

    def replace(self, state: ForgeState) -> None:
        if not isinstance(state, ForgeState):
            raise TypeError("expected ForgeState")
        _valid_session_id(state.session_id)
        if state.schema_version != SCHEMA_VERSION or state.plugin_version != self.plugin_version:
            raise StateError("state schema or plugin mismatch")
        if state.status not in _STATUSES or not Path(state.cwd).is_absolute() or Path(state.cwd) != Path(state.cwd).resolve():
            raise StateError("invalid state identity")
        self._ensure_root()
        path = self.path_for(state.session_id)
        self._check_record(path)
        payload = json.dumps(_state_payload(state), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        temp = self.data_root / ("." + path.name + "." + secrets.token_hex(12) + ".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(temp, flags, 0o600)
            try:
                view = memoryview(payload)
                while view:
                    view = view[os.write(fd, view):]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.chmod(temp, 0o600)
            os.replace(temp, path)
            dir_fd = os.open(self.data_root, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError as exc:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            raise StateError("could not atomically persist state") from exc

    def delete(self, session_id: str) -> None:
        path = self.path_for(session_id)
        if not self.data_root.exists():
            return
        self._check_record(path)
        try:
            path.unlink()
        except FileNotFoundError:
            return
        dir_fd = os.open(self.data_root, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def stat_is_symlink(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode)


def stat_is_regular(info: os.stat_result) -> bool:
    return stat.S_ISREG(info.st_mode)
