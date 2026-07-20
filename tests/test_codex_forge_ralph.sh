#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git -C "$(dirname "${BASH_SOURCE[0]}")/.." rev-parse --show-toplevel)"
plugin="$repo_root/dot_local/share/codex-forge-marketplace/plugins/codex-forge"
ralph_executable="$(command -v ralph)"
python_executable="$(command -v python3)"
fixture="$(mktemp -d)"
trap 'rm -rf "$fixture"' EXIT

[[ -x "$ralph_executable" && -x "$python_executable" ]]

make_repo() {
  local destination="$1"
  mkdir -p "$destination/.docs/ai"
  git -C "$destination" init -q
  git -C "$destination" config user.name "Forge Test"
  git -C "$destination" config user.email "forge-test"
  cat > "$destination/.docs/ai/current-state.md" <<'EOF'
# Current State

## Branch
main

## Plan

## Blockers
- None
EOF
  cat > "$destination/.docs/ai/roadmap.md" <<'EOF'
# Roadmap

### Now
- [ ] Existing item

### Next
- Later
EOF
  cat > "$destination/.docs/ai/loop-prompt.md" <<'EOF'
Fixture Codex prompt
EOF
  git -C "$destination" add .docs/ai
  git -C "$destination" commit -q -m "test: baseline"
}

mkdir -p "$fixture/bin" "$fixture/home"
cat > "$fixture/bin/codex" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s ' "$@" >> "$CODEX_ARGV_LOG"
printf '\n' >> "$CODEX_ARGV_LOG"
[[ "$#" -eq 2 && "$1" == "exec" ]]
"$PYTHON_EXECUTABLE" - "$PWD/.docs/ai/current-state.md" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
path.write_text(path.read_text(encoding="utf-8").replace("- [ ]", "- [x]"), encoding="utf-8")
PY
EOF
chmod +x "$fixture/bin/codex"

# Observe the installed Ralph executable without replacing it. The local prompt
# keeps Ralph from reading a real HOME prompt, and the observer ignores fake Codex.
cat > "$fixture/ralph-observer.sh" <<'EOF'
trap '
  if [[ "${0:-}" == "${RALPH_EXECUTABLE:-}" ]]; then
    printf "%s " "$@" >> "$RALPH_ARGV_LOG"
    printf "\\n" >> "$RALPH_ARGV_LOG"
  fi
  trap - DEBUG
' DEBUG
EOF

fixture_path="$fixture/bin:$(dirname "$ralph_executable"):/usr/bin:/bin"
fixture_env=(
  env -i
  "PATH=$fixture_path"
  "HOME=$fixture/home"
  "RALPH_ROSTER=$fixture/no-roster.toml"
  "BASH_ENV=$fixture/ralph-observer.sh"
  "RALPH_EXECUTABLE=$ralph_executable"
  "RALPH_ARGV_LOG=$fixture/ralph.argv"
  "CODEX_ARGV_LOG=$fixture/codex.argv"
  "PYTHONPATH=$plugin/lib"
  "PYTHON_EXECUTABLE=$python_executable"
)

make_repo "$fixture/success"
"${fixture_env[@]}" "$python_executable" - "$fixture/success" "$fixture/codex.argv" <<'EOF'
from pathlib import Path
import sys

from codex_forge.brief import Brief, DecisionEnvelope, Phase
from codex_forge.ralph import launch_ralph_dispatch, prepare_ralph_dispatch, read_ralph_receipt

cwd = Path(sys.argv[1])
codex_log = Path(sys.argv[2])
brief = Brief(
    1, "Add cached search", ("cache",), (), (), ("tests pass",), (), (), (),
    DecisionEnvelope(("formatting",), ("security",)),
    (Phase("Implement", "senior", "python3 -m unittest"),
     Phase("Document", "junior", "python3 -m py_compile")), "ralph",
)
prepared = prepare_ralph_dispatch(brief, cwd, date="2026-07-20")
if codex_log.exists():
    raise SystemExit("real Ralph preflight invoked Codex")
launch = launch_ralph_dispatch(prepared, data_root=cwd.parent / "forge-data", launch_id="a" * 64)
import time
for _ in range(250):
    receipt = read_ralph_receipt(cwd.parent / "forge-data", launch.launch_id)
    if receipt and receipt["status"] in {"completed", "failed"}:
        if receipt.get("exit_code") != 0:
            raise SystemExit(receipt["exit_code"])
        break
    time.sleep(0.02)
else:
    raise SystemExit("Ralph runner did not publish terminal receipt")
EOF

"$python_executable" - "$fixture/ralph.argv" "$fixture/codex.argv" <<'EOF'
from pathlib import Path
import sys

ralph_args = [line.split() for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()]
if ralph_args != [["-n", "0", "-t", "codex"], ["-t", "codex"]]:
    raise SystemExit(f"unexpected installed Ralph argv: {ralph_args!r}")
if any("-L" in args for args in ralph_args):
    raise SystemExit("installed Ralph received forbidden -L")
codex_args = Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
if len(codex_args) != 1 or not codex_args[0].startswith("exec Fixture Codex prompt"):
    raise SystemExit(f"real Ralph did not reach fake Codex: {codex_args!r}")
EOF

[[ "$(git -C "$fixture/success" log -1 --pretty=%s)" == "plan: prepare Forge Ralph execution for Add cached search" ]]
mapfile -t planned_paths < <(git -C "$fixture/success" show --pretty=format: --name-only HEAD | sed '/^$/d' | sort)
[[ "${planned_paths[*]}" == ".docs/ai/current-state.md .docs/ai/phases/add-cached-search-spec.md .docs/ai/roadmap.md" ]]
git -C "$fixture/success" show HEAD:.docs/ai/current-state.md | grep -q '^- \[ \] Implement\. Verify: `python3 -m unittest` (tier_floor: senior)'
grep -q '^- \[x\] Implement\. Verify: `python3 -m unittest` (tier_floor: senior)' "$fixture/success/.docs/ai/current-state.md"
test -f "$fixture/success/.docs/ai/phases/add-cached-search-spec.md"

make_repo "$fixture/failure"
cp "$fixture/failure/.docs/ai/current-state.md" "$fixture/before-current-state.md"
cp "$fixture/failure/.docs/ai/roadmap.md" "$fixture/before-roadmap.md"
if "${fixture_env[@]}" "$python_executable" - "$fixture/failure" <<'EOF'
from pathlib import Path
import sys
from unittest import mock

from codex_forge.brief import Brief, DecisionEnvelope, Phase
from codex_forge.ralph import RalphError, launch_ralph_dispatch, prepare_ralph_dispatch

brief = Brief(
    1, "Add cached search", ("cache",), (), (), ("tests pass",), (), (), (),
    DecisionEnvelope(("formatting",), ("security",)),
    (Phase("Implement", "senior", "python3 -m unittest"),
     Phase("Document", "junior", "python3 -m py_compile")), "ralph",
)
prepared = prepare_ralph_dispatch(brief, Path(sys.argv[1]))
with mock.patch("codex_forge.ralph._spawn_backend", side_effect=OSError("injected spawn failure")):
    try:
        launch_ralph_dispatch(prepared, data_root=Path(sys.argv[1]).parent / "forge-data", launch_id="b" * 64)
    except RalphError:
        raise SystemExit(0)
raise SystemExit("expected launch to fail before Popen")
EOF
then
  :
else
  exit 1
fi
cmp "$fixture/before-current-state.md" "$fixture/failure/.docs/ai/current-state.md"
cmp "$fixture/before-roadmap.md" "$fixture/failure/.docs/ai/roadmap.md"
test ! -e "$fixture/failure/.docs/ai/phases/add-cached-search-spec.md"
[[ "$(git -C "$fixture/failure" log -1 --pretty=%s)" == "test: baseline" ]]
[[ -z "$(git -C "$fixture/failure" status --porcelain)" ]]

"$python_executable" - "$fixture/ralph.argv" "$fixture/codex.argv" <<'EOF'
from pathlib import Path
import sys

ralph_args = [line.split() for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()]
if ralph_args != [["-n", "0", "-t", "codex"], ["-t", "codex"], ["-n", "0", "-t", "codex"]]:
    raise SystemExit(f"unexpected real Ralph boundary calls: {ralph_args!r}")
if len(Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()) != 1:
    raise SystemExit("pre-spawn rollback reached fake Codex")
EOF
[[ -z "$(find "$fixture/home" -mindepth 1 -print -quit)" ]]

echo "Codex Forge Ralph fixture passed"
