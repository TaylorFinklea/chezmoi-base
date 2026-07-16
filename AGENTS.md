# AGENTS.md — chezmoi-base (front door)

This repo is the **entry point for dotfile changes on every machine**. The user
comes here and describes a change; the agent decides which repo the change
belongs in and routes it there. Machine-agnostic entry, machine-aware routing.
This file is repo meta (listed in `.chezmoiignore`), never a managed target.

## Topology

| Repo | Visibility | Present on | Owns |
|---|---|---|---|
| `chezmoi-base` (this) | **public** | all machines | generic, sanitized config only |
| `~/git/chezmoi-personal` | private | personal Macs only | personal overlay + not-yet-decomposed bulk |
| `~/git/chezmoi-work` | private (SSH) | work + personal Macs | work-specific targets only |

- Composition: base + exactly one overlay per machine. **One target file = one
  owner repo**; `scripts/chezmoi-compose preflight <personal|work>` enforces
  disjoint ownership and must pass before committing a routing change.
- Never clone `chezmoi-personal` on a work machine. Never put secrets,
  credentials, personal or work identifiers, Hermes content, or private remote
  URLs in base.
- On a personal Mac, cross-session handoff state (roadmap, current-state,
  decisions, phase specs) lives in `../chezmoi-personal/.docs/ai/` — read it at
  session start. Work-Mac sessions rely on commit messages and this file.

## Routing a change (decision order)

1. **Target already managed?** Edit its current owner. Find it: check each
   repo's source tree, or `chezmoi managed` per stack.
2. **New + generic + public-safe + wanted on both machine types** → base.
   Must pass the safety scanner; templates here may branch on `machine_role`
   but never `ai_profile` (base composes under both overlays).
3. **Personal-specific or private** → `chezmoi-personal` (personal Mac only —
   on a work Mac, say so and defer; do not stage personal content anywhere else).
4. **Work-specific** → `chezmoi-work`.
5. **Mixed-ownership surfaces are special** — codex `config.toml`, the
   `ai.json` MCP catalog, codex `tui.toml`/`desktop.toml` partials. They have
   parity tests and a pending decomposition plan (see chezmoi-personal roadmap:
   Hermes personal/work boundary). Never relocate them casually; duplicated
   partials must be edited in both overlays together or their parity test fails.

## Reach check — say it before committing

- An edit in **base or work lands on the work machines**. If the request
  sounded personal, confirm intent with the user first.
- An edit in **personal never reaches work**. If the user said "everywhere",
  route to base (if public-safe) or duplicate into work behind a parity test
  (pattern: `chezmoi-personal/scripts/tests/test_codex_tui_partial_parity.sh`).
- Pushing base **publishes** — it is a public repo.

## Moving a file between repos

`git rm` from the old owner, add to the new owner, run preflight for **both**
roles, run the scanner if base gained content. **Never** add a `.chezmoiremove`
entry in an overlay for a target now owned by base — it would delete the live
file on the next overlay apply, and preflight cannot detect that case.

## Verify

```bash
scripts/chezmoi-compose preflight personal   # and: preflight work
scripts/chezmoi-compose diff personal        # never applies
python3 scripts/check-public-safety.py       # gate before any base commit/push
python3 tests/test-public-safety.py          # scanner's own suite
bash tests/test-compose.sh                   # runner suite
```

Cross-overlay parity tests live in `chezmoi-personal/scripts/tests/` and run on
the personal Mac only.

## Apply

Applies to live HOME are **human-authorized and targeted** — never bare, never
headless. Expected perpetual drift (classify before treating a failed `verify`
as a problem): `.claude/settings.json` and `.codex/config.toml` are
runtime-rewritten by their apps; anything beyond those two files is real.
