# Dispatch Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Pi-named one-shot offload skill with a harness-neutral worker-dispatch procedure that prefers native subagents and OMP while retaining explicit Pi and orchestra paths.

**Architecture:** `delegate` remains the policy and routing layer. The base-owned `dispatch-worker` skill becomes the execution layer; active base and personal guidance points to it, while Undertake, Ralph loops, and fallback orchestration keep their existing boundaries.

**Tech Stack:** Markdown Skills, TOML skill catalog, JSON skill lock, Python `skillsync`, Bash verification scripts.

## Global Constraints

- Base is public: no private identifiers, credentials, or secret-bearing content.
- Do not apply changes to HOME.
- Do not rewrite historical plans, specs, decisions, or experience records.
- Musterroll is operational roster truth; Afterfact is scorecard destination.
- OMP is preferred but not exclusive; Pi remains an explicit compatibility/provider path.

---

### Task 1: Canonical skill cutover

**Files:**
- Rename: `.skills-src/skills/dispatch-to-pi/` → `.skills-src/skills/dispatch-worker/`
- Modify: `.skills-src/skills/dispatch-worker/SKILL.md`
- Modify: `.skillcatalog.toml`
- Modify: `.skillcatalog.lock.json`

**Interfaces:**
- Consumes: an already-approved profile selected under `delegate` policy.
- Produces: `dispatch-worker`, a one-shot execution procedure for native subagents, OMP, Pi, and schema-validated orchestra runs.

- [ ] Rename the source directory and catalog entry so a stale lock fails before implementation.
- [ ] Run `private_dot_local/bin/executable_skillsync check --profile personal --base-root . --overlay-root ../chezmoi-personal --home /tmp/dispatch-worker-home --state-root /tmp/dispatch-worker-state` and confirm it rejects the stale lock.
- [ ] Replace the skill body with the approved boundaries, execution order, exact one-shot commands, evidence rules, and failure behavior from the design spec.
- [ ] Run `private_dot_local/bin/executable_skillsync lock --repo-root .` to regenerate the base lock.
- [ ] Re-run the focused `skillsync check` and confirm success.

### Task 2: Active base references

**Files:**
- Modify: `.skills-src/skills/delegate/SKILL.md`
- Modify: `.skills-src/skills/guildhall-orchestration/SKILL.md`
- Modify: `.skills-src/skills/loops/SKILL.md`

**Interfaces:**
- Consumes: the `dispatch-worker` name from Task 1.
- Produces: active routing guidance with no dependency on `dispatch-to-pi` or the legacy scorecard as roster truth.

- [ ] Replace `delegate` logging/mechanics references with `dispatch-worker`, Musterroll routing truth, and Afterfact-first provenance language.
- [ ] Change Guildhall’s one-shot routing row to `dispatch-worker`.
- [ ] Change loops’ one-shot pointer to `dispatch-worker` and Musterroll.
- [ ] Search active `.skills-src/skills` content for `dispatch-to-pi` and confirm only historical/non-active content is absent.

### Task 3: Personal global-policy cleanup

**Files:**
- Modify: `../chezmoi-personal/AGENTS.md`
- Modify: `../chezmoi-personal/dot_claude/templates/tiers.md`
- Modify: `../chezmoi-personal/dot_claude/create_model-scorecard.md`
- Delete: `../chezmoi-personal/dot_claude/agents/pi-dispatch.md`

**Interfaces:**
- Consumes: the shared `dispatch-worker` procedure and canonical Musterroll/Afterfact policy.
- Produces: global instructions that no longer advertise a Pi-specific dispatch skill or wrapper agent.

- [ ] Replace active `dispatch-to-pi` references with `dispatch-worker` and remove the `pi-dispatch` wrapper recommendation.
- [ ] Keep direct `pi-liveness` documented as a valid explicit compatibility path.
- [ ] Remove the wrapper agent file rather than leaving an alias or deprecation shim.
- [ ] Search the four active files for `dispatch-to-pi|pi-dispatch` and confirm no matches.

### Task 4: Verify composed behavior and commit

**Files:**
- Modify only if needed: `.skillcatalog.lock.json`
- Modify handoff state in `../chezmoi-personal/.docs/ai/` only for the completed active migration.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: a public-safe base commit and a separate personal policy commit, with no HOME mutation.

- [ ] Run `bash tests/test-skill-composition.sh`.
- [ ] Run `python3 scripts/check-public-safety.py`.
- [ ] Run `scripts/chezmoi-compose preflight personal` and `scripts/chezmoi-compose preflight work`.
- [ ] Run `bash ../chezmoi-personal/scripts/tests/test_omp_worker.sh`.
- [ ] Search active base/personal policy and skill sources for stale names; exclude historical docs and records.
- [ ] Commit base files with `feat(skills): replace Pi dispatch with worker dispatch`.
- [ ] Commit personal files with `docs(routing): adopt harness-neutral worker dispatch`, leaving unrelated `scripts/install-homebrew-personal.sh` untouched.
