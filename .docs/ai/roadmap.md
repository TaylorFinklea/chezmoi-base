# Roadmap

> Durable goals and milestones. Updated when scope changes, not every session.

## Vision

Shared base layer of the three-repo chezmoi setup (base / personal / work) —
the front door for all dotfile changes on any machine.

## Now / Next / Later

### Now

- [x] **Herdr Ask OMP backend — retired 2026-10-01** with herdr and
      herdr-ask everywhere; superseded, no apply needed. Original note
      (2026-08-01): Base now renders a safe custom-process `omp` backend with
      sessions, tools, LSP, PTY execution, extensions, skills, and rules
      disabled; `pi` remains the default. Personal preflight and released
      Herdr Ask 0.1.0 validation pass. User to run the targeted composed apply
      for `~/Library/Application Support/herdr-ask/config.toml`, then
      `herdr-ask doctor omp`. Work-profile preflight remains unverified on this
      Mac because `~/git/chezmoi-work` is absent.

- [ ] **Decide whether to `skillsync migrate` the 91 unmanaged codex/pi/hermes
      skills.** They work today but skillsync doesn't own them, so they drift
      silently and `sync` will never update them. `migrate` adopts only entries
      whose `tree_hash` already matches the composed output and refuses the rest,
      so it is non-destructive — but the refusals then need hand-reconciling.
      Verify: `skillsync diff …` reports 0 unmanaged.

### Next

- [ ]

### Later

- [ ]

## Backlog

> Self-contained items any agent can execute. Each entry should include scope, file paths, acceptance criteria, verification steps, a `tier_floor` (`lead`/`senior`/`junior` — gates ownership), and a `complexity` (`S`/`M`/`L`/`XL`). See Tiered model routing in AGENTS.md.

## Constraints

- Applying to live HOME is human-only; headless iterations never apply.
- Changes here propagate to the work machine too — verify reach before landing.
