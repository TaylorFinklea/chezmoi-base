#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git -C "$(dirname "${BASH_SOURCE[0]}")/.." rev-parse --show-toplevel)"
plugin="$repo_root/dot_local/share/codex-forge-marketplace/plugins/codex-forge"
fixture="$(mktemp -d)"
trap 'rm -rf "$fixture"' EXIT

make_repo() {
  local destination="$1"
  mkdir -p "$destination/.docs/ai"
  git -C "$destination" init -q
  git -C "$destination" config user.name "Forge Test"
  git -C "$destination" config user.email "forge@example.invalid"
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
  git -C "$destination" add .docs/ai
  git -C "$destination" commit -q -m "test: baseline"
}

mkdir -p "$fixture/bin"
cat > "$fixture/bin/ralph" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$RALPH_LOG"
if [[ "${1:-}" == "-n" && "${RALPH_FAIL_PREFLIGHT:-0}" == "1" ]]; then
  echo "injected preflight failure" >&2
  exit 7
fi
if [[ "${1:-}" == "-n" ]]; then
  test -f .docs/ai/phases/add-cached-search-spec.md
  grep -q '^- \[ \] Implement\. Verify: `python3 -m unittest` (tier_floor: senior)' .docs/ai/current-state.md
fi
EOF
chmod +x "$fixture/bin/ralph"

make_repo "$fixture/success"
PATH="$fixture/bin:$PATH" RALPH_LOG="$fixture/ralph.log" PYTHONPATH="$plugin/lib" python3 - "$fixture/success" <<'EOF'
from pathlib import Path
import sys

from codex_forge.brief import Brief, DecisionEnvelope, Phase
from codex_forge.ralph import launch_ralph_dispatch, prepare_ralph_dispatch

cwd = Path(sys.argv[1])
brief = Brief(
    1, "Add cached search", ("cache",), (), (), ("tests pass",), (), (), (),
    DecisionEnvelope(("formatting",), ("security",)),
    (Phase("Implement", "senior", "python3 -m unittest"),
     Phase("Document", "junior", "python3 -m py_compile")), "ralph",
)
prepared = prepare_ralph_dispatch(brief, cwd, date="2026-07-20")
result = launch_ralph_dispatch(prepared)
if result.exit_code != 0:
    raise SystemExit(result.exit_code)
EOF

[[ "$(sed -n '1p' "$fixture/ralph.log")" == "-n 0 -t codex" ]]
[[ "$(sed -n '2p' "$fixture/ralph.log")" == "-t codex" ]]
! grep -q -- '-L' "$fixture/ralph.log"
[[ "$(git -C "$fixture/success" log -1 --pretty=%s)" == "plan: prepare Forge Ralph execution for Add cached search" ]]
mapfile -t planned_paths < <(git -C "$fixture/success" show --pretty=format: --name-only HEAD | sed '/^$/d' | sort)
[[ "${planned_paths[*]}" == ".docs/ai/current-state.md .docs/ai/phases/add-cached-search-spec.md .docs/ai/roadmap.md" ]]
[[ -z "$(git -C "$fixture/success" status --porcelain)" ]]
grep -q '^- \[ \] Implement\. Verify: `python3 -m unittest` (tier_floor: senior)' "$fixture/success/.docs/ai/current-state.md"
test -f "$fixture/success/.docs/ai/phases/add-cached-search-spec.md"

make_repo "$fixture/failure"
cp "$fixture/failure/.docs/ai/current-state.md" "$fixture/before-current-state.md"
cp "$fixture/failure/.docs/ai/roadmap.md" "$fixture/before-roadmap.md"
if PATH="$fixture/bin:$PATH" RALPH_LOG="$fixture/failure.log" RALPH_FAIL_PREFLIGHT=1 PYTHONPATH="$plugin/lib" python3 - "$fixture/failure" <<'EOF'
from pathlib import Path
import sys

from codex_forge.brief import Brief, DecisionEnvelope, Phase
from codex_forge.ralph import RalphError, prepare_ralph_dispatch

brief = Brief(
    1, "Add cached search", ("cache",), (), (), ("tests pass",), (), (), (),
    DecisionEnvelope(("formatting",), ("security",)),
    (Phase("Implement", "senior", "python3 -m unittest"),
     Phase("Document", "junior", "python3 -m py_compile")), "ralph",
)
try:
    prepare_ralph_dispatch(brief, Path(sys.argv[1]))
except RalphError:
    raise SystemExit(0)
raise SystemExit("expected Ralph preflight to fail")
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

echo "Codex Forge Ralph fixture passed"
