# Roadmap

> Durable goals and milestones. Updated when scope changes, not every session.

## Vision

Shared base layer of the three-repo chezmoi setup (base / personal / work) —
the front door for all dotfile changes on any machine.

## Now / Next / Later

### Now

- [ ] **Materialize the `native` (Claude Code) skill target.** `~/.claude/skills`
      does not exist; `skillsync diff` reports `create native/<skill>` for all 39
      catalog skills with a `native` target — including `delegate` and
      `dispatch-worker`, which AGENTS.md assumes are available to every harness.
      Codex and Pi have their skills on disk but skillsync reports all 91 as
      `unmanaged` (placed outside skillsync, so it does not own them).
      Caveat: `skillsync check` reports **clean** here — it validates catalog/lock
      consistency, not whether targets were ever materialized. Use `diff`, not
      `check`, to see this class of gap.
      Verify: `skillsync diff --profile personal --base-root ~/git/chezmoi-base --overlay-root ~/git/chezmoi-personal` reports no `create native/*`.

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
