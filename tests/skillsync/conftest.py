import importlib.util
import json
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "private_dot_local" / "bin" / "executable_skillsync"


@pytest.fixture(scope="session")
def ss():
    """Load the extension-less uv single-file tool as an importable module."""
    spec = importlib.util.spec_from_loader("skillsync", loader=None)
    mod = importlib.util.module_from_spec(spec)
    exec(compile(TOOL.read_text(), str(TOOL), "exec"), mod.__dict__)
    return mod


# --- fixture builders shared across test modules -----------------------------


def write_skill(root: Path, name: str, *, description: str = "does a thing",
                 extra_frontmatter: dict | None = None, extra_files: dict[str, str] | None = None,
                 executable: tuple[str, ...] = ()) -> Path:
    """Create <root>/<name>/SKILL.md (+ optional extra files) with valid frontmatter."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    meta = {"name": name, "description": description}
    if extra_frontmatter:
        meta.update(extra_frontmatter)
    lines = "\n".join(f"{k}: {v}" for k, v in meta.items())
    (d / "SKILL.md").write_text(f"---\n{lines}\n---\nBody for {name}.\n")
    for rel, content in (extra_files or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    for rel in executable:
        (d / rel).chmod(0o755)
    return d


def write_catalog_toml(repo_root: Path, *, owner: str, roles: list[str], source_root: str,
                        records: list[dict], filename: str = ".skillcatalog.toml") -> Path:
    lines = [f"schema = 1", f'owner = "{owner}"', f"roles = {json.dumps(roles)}", f'source_root = "{source_root}"']
    for r in records:
        lines.append("")
        lines.append("[[skills]]")
        lines.append(f'name = "{r["name"]}"')
        lines.append(f'targets = {json.dumps(r["targets"])}')
        lines.append(f'activation = "{r.get("activation", "automatic")}"')
        lines.append(f'upstream_ref = "{r.get("upstream_ref", "repo-history")}"')
        lines.append(f'transform = "{r.get("transform", "standard")}"')
    path = repo_root / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def build_repo(repo_root: Path, *, owner: str, roles: list[str], skill_names: list[str],
                source_root: str = ".skills-src/skills", targets: list[str] | None = None,
                description: str = "does a thing") -> Path:
    """Create a full catalog repo: <repo_root>/.skillcatalog.toml + <repo_root>/<source_root>/<name>/SKILL.md."""
    targets = targets if targets is not None else ["native", "codex", "pi"]
    src_dir = repo_root / source_root
    records = []
    for name in skill_names:
        write_skill(src_dir, name, description=description)
        records.append({"name": name, "targets": targets})
    write_catalog_toml(repo_root, owner=owner, roles=roles, source_root=source_root, records=records)
    return repo_root


def make_base_repo(tmp_path: Path, skill_names: list[str] = ("alpha",), **kw) -> Path:
    return build_repo(tmp_path / "base", owner="base-managed", roles=["personal", "work"],
                       skill_names=list(skill_names), **kw)


def make_personal_repo(tmp_path: Path, skill_names: list[str] = ("pskill",), **kw) -> Path:
    kw.setdefault("targets", ["native", "codex", "pi", "hermes"])
    return build_repo(tmp_path / "personal", owner="personal-managed", roles=["personal"],
                       skill_names=list(skill_names), **kw)


def make_work_repo(tmp_path: Path, skill_names: list[str] = ("wskill",), *, external_source_dir: Path | None = None,
                    **kw) -> Path:
    """A work-managed catalog repo. `source_root` is a small relative marker
    resolved against an external --work-root, never an absolute/private path."""
    repo_root = tmp_path / "work"
    kw.setdefault("targets", ["native", "codex", "pi"])
    source_root = kw.pop("source_root", "skills")
    records = [{"name": name, "targets": kw["targets"]} for name in skill_names]
    write_catalog_toml(repo_root, owner="work-managed", roles=["work"], source_root=source_root, records=records)
    if external_source_dir is not None:
        for name in skill_names:
            write_skill(external_source_dir / source_root, name, description=kw.get("description", "does a thing"))
    return repo_root
