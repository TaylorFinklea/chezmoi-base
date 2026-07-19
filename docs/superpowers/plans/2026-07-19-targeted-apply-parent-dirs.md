# Targeted Apply Parent Directories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every `chezmoi-compose` apply path create missing managed parent directories through chezmoi itself.

**Architecture:** Preserve exact ownership validation, drift classification, and batching. Pass chezmoi's native `--parent-dirs` flag on clean, forced, interactive-decision, and explicitly targeted apply invocations; extend the existing fake-chezmoi runner to fail when missing parents are not requested and to materialize targets when they are.

**Tech Stack:** Bash 3.2-compatible shell, chezmoi CLI, existing shell test harness.

## Global Constraints

- Change public `chezmoi-base`; behavior reaches both personal and work machines.
- Never create target parents with wrapper-owned `mkdir -p`; chezmoi owns parent semantics and modes.
- Keep exact absolute managed-file/symlink ownership validation.
- Preserve `sync`, preflight, collision, pull, skip-list, and drift-decision semantics.
- Do not run a live HOME apply from the agent.

---

### Task 1: Apply managed parents on every compose write path

**Files:**
- Modify: `tests/test-compose.sh`
- Modify: `scripts/chezmoi-compose`

**Interfaces:**
- Consumes: `run_chezmoi <source> apply [flags] -- <absolute-target>...` and existing base/overlay batches.
- Produces: every wrapper-generated apply argv contains `--parent-dirs` before `--`; no CLI surface changes.

- [ ] **Step 1: Strengthen the fake chezmoi apply behavior and expected argv**

In `tests/test-compose.sh`, retain the existing call log, then make the fake
`apply)` branch parse `--force`, require `--parent-dirs`, consume `--`, create
each target's parent, and materialize each target:

```bash
  apply)
    printf 'apply-args:%s:%s\n' "$source" "$*" >> "$CHEZMOI_CALL_LOG"
    parent_dirs=0
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --force) shift ;;
        --parent-dirs) parent_dirs=1; shift ;;
        --) shift; break ;;
        *) printf 'unexpected apply option: %s\n' "$1" >&2; exit 70 ;;
      esac
    done
    for target in "$@"; do
      parent=${target%/*}
      if [ ! -d "$parent" ] && [ "$parent_dirs" -ne 1 ]; then
        printf 'missing parent without --parent-dirs: %s\n' "$parent" >&2
        exit 71
      fi
      mkdir -p "$parent"
      : > "$target"
    done
    ;;
```

Update exact call assertions to require:

```text
apply-args:<source>:--parent-dirs -- <target>
apply-args:<source>:--force --parent-dirs -- <target>
```

After the targeted base/overlay apply, assert both targets exist. Add an
interactive conflict case that pipes `o` to `sync personal --no-pull` and
asserts its overwrite call uses `--force --parent-dirs --`.

- [ ] **Step 2: Run the runner test and confirm RED**

Run:

```bash
bash tests/test-compose.sh
```

Expected: FAIL because current apply invocations omit `--parent-dirs`; the fake
chezmoi reports a missing parent or an exact argv assertion fails.

- [ ] **Step 3: Add native parent application to all four call sites**

In `scripts/chezmoi-compose`, change only the apply argument vectors:

```bash
run_chezmoi "$source" apply --parent-dirs -- "${plain_batch[@]}"
run_chezmoi "$source" apply --force --parent-dirs -- "${force_batch[@]}"
run_chezmoi "$source" apply --force --parent-dirs -- "$abs"
run_chezmoi "${sources[0]}" apply --parent-dirs -- "${base_batch[@]}"
run_chezmoi "${sources[1]}" apply --parent-dirs -- "${overlay_batch[@]}"
```

Do not alter classification, ownership, or decision code.

- [ ] **Step 4: Run focused and public verification**

Run:

```bash
bash tests/test-compose.sh
scripts/chezmoi-compose preflight personal
scripts/chezmoi-compose preflight work
python3 tests/test-public-safety.py
```

Expected: all pass.

The live-tree scanner has a known unrelated `ai-scratch/` false positive. Run
`python3 scripts/check-public-safety.py` in a clean disposable local clone that
contains the pending script/test diff; expected exit 0.

- [ ] **Step 5: Probe fresh-destination behavior with real chezmoi**

Use `mktemp -d` for destination and persistent state, pre-create no managed
parent directories, then invoke the updated wrapper with environment overrides
and one nested exact managed target. Assert the target is created. Never point
this probe at live HOME.

- [ ] **Step 6: Commit**

```bash
git add scripts/chezmoi-compose tests/test-compose.sh docs/superpowers/plans/2026-07-19-targeted-apply-parent-dirs.md
git commit -m "fix(compose): create parents for managed apply targets"
```
