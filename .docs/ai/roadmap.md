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

- [ ] **Decide which codex-only skills gain `native`.** 13 skills in the
      *personal* catalog are `targets = ["codex"]`: chatgpt-apps,
      cloudflare-deploy, doc, figma, frontend-skill, jupyter-notebook, pdf,
      playwright, screenshot, security-best-practices, security-threat-model,
      sora, speech. A further 3 are on disk in `~/.codex/skills` but in no
      catalog at all: imagegen, openai-docs, transcribe.
      Caveat: several overlap Claude Code built-ins (screenshot/playwright vs
      claude-in-chrome; pdf vs native PDF Read; jupyter-notebook vs NotebookEdit;
      frontend-skill vs the frontend-design plugin) — sync only what adds
      something. The OpenAI-product skills (sora, speech, imagegen, transcribe,
      openai-docs, chatgpt-apps) are not portable to Claude.

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
