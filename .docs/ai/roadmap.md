# Roadmap

> Durable goals and milestones. Updated when scope changes, not every session.

## Vision

Shared base layer of the three-repo chezmoi setup (base / personal / work) —
the front door for all dotfile changes on any machine.

## Now / Next / Later

### Now

- [x] **Materialize the `native` (Claude Code) skill target.** Done 2026-07-27:
      `skillsync sync` created all 41 skills in `~/.claude/skills` (39 + the two
      security skills added the same day). `delegate` and `dispatch-worker` are
      now present, as AGENTS.md assumes. Codex/Pi/Hermes trees were left
      untouched — `cmd_sync` acts only on create/recreate/update and merely
      *reports* unmanaged entries.
      Caveat: `skillsync check` reported **clean** throughout this gap, and
      again while the lock sat stale after a catalog edit. `check` validates
      catalog/lock internals only — it compares neither lock-to-catalog nor
      catalog-to-disk. Use `diff` for both classes of drift.
      Caveat: `sync` exits **1** whenever any unmanaged entry exists (91 do,
      pre-existing). Exit 1 here is normal, not failure.
      Verify: `skillsync diff …` reports no `create native/*` (now 91 unmanaged, 0 create).

- [ ] **Decide whether to `skillsync migrate` the 91 unmanaged codex/pi/hermes
      skills.** They work today but skillsync doesn't own them, so they drift
      silently and `sync` will never update them. `migrate` adopts only entries
      whose `tree_hash` already matches the composed output and refuses the rest,
      so it is non-destructive — but the refusals then need hand-reconciling.
      Verify: `skillsync diff …` reports 0 unmanaged.

- [x] **Decide which codex-only skills gain `native`.** Resolved 2026-07-27:
      `security-best-practices` + `security-threat-model` gained `native`
      (chezmoi-personal `5a89ea2`). The rest stay codex-only — see
      decisions.md for the skip rationale, so it isn't re-litigated.
      Remaining codex-only: chatgpt-apps, cloudflare-deploy, doc, figma,
      frontend-skill, jupyter-notebook, pdf, playwright, screenshot, sora,
      speech. Uncatalogued on disk: imagegen, openai-docs, transcribe.
      Caveat: the two new ones are *eligible* only — they do not exist in
      `~/.claude/skills` until the sync item above runs.

- [ ] **Refresh `~/.claude/templates/handoff/current-state.md`.** It still seeds
      the pre-loop-state format ("Last Session Summary", "Build Status"), which
      AGENTS.md's Session End routing table now forbids. Every repo seeded from
      it starts non-conformant. Source: `chezmoi-personal/dot_claude/templates/`.

### Next

- [ ]

### Later

- [ ]

## Backlog

> Self-contained items any agent can execute. Each entry should include scope, file paths, acceptance criteria, verification steps, a `tier_floor` (`lead`/`senior`/`junior` — gates ownership), and a `complexity` (`S`/`M`/`L`/`XL`). See Tiered model routing in AGENTS.md.

## Constraints

- Applying to live HOME is human-only; headless/Ralph iterations never apply.
- Changes here propagate to the work machine too — verify reach before landing.
