---
name: chezmoi-reconcile
description: "Use when reconciling chezmoi drift in the dotfiles source repo — running chezmoi diff/apply/re-add, deciding source-vs-home direction, migrating a config surface across agents, or writing a commit/handoff claim about a config file. Carries the direction-decision logic and the hard-won gotchas (sister-config check, mktemp probing, verify-before-claiming, hidden PUA glyphs)."
---

# Chezmoi drift reconciliation

This repo is the source of truth for dotfiles managed by chezmoi. `chezmoi diff`
shows where `~/` has diverged from the repo. Drift can flow either way;
**default to surfacing it before resolving it.**

## Decide direction before touching anything

**Don't reflexively `chezmoi apply` (or `--force`).** Decide direction first:

- Source is right, home is stale → `chezmoi apply` is correct.
- Home is right, source is stale → hand-edit the source, then `chezmoi apply`
  (or `chezmoi re-add` if the file isn't templated).
- Both have intentional changes → manual merge.

For files the user actively hand-edits (`~/.tmux.conf`, shell rc files, editor
configs), assume the home-side diff is intentional unless the user said
otherwise. Show the diff and ask before clobbering.

## Gotchas

The highest-signal content here — each is a real incident that already bit a
past session.

| Gotcha | What to do |
|---|---|
| **Sister-config drift.** Some config surfaces have parallel files across harnesses and agents. The exact siblings and ownership can change over time. | Before migrating a shared integration, discover the current sibling surfaces and whether each is source-managed or app-managed. Search for the old pattern across those actual siblings before declaring the migration done. |
| **Probe canonical shapes against `mktemp -d`, never live HOME.** | For moshi-hook: `HOME=$(mktemp -d) moshi-hook install --target <agent>` writes the daemon's expected layout into a throwaway dir. Diff that against `dot_<agent>/hooks.json` to spot drift. Hook event names differ across agents — Claude has `PreToolUse`/`PostToolUse`; Codex does not. |
| **Verify claims before writing them.** "Force-applied the daemon-based hooks.json" is only true if the source is actually daemon-based — otherwise the breadcrumb misleads the next session. | Don't describe a file as "daemon-based" / "migrated" / "current" in a commit message or `current-state.md` without reading it first. |
| **Hidden glyphs hide drift.** Powerline-style status lines embed Private Use Area characters (U+E0B0–U+E0BF) that some readers collapse in display. | When two visually-identical status-line strings are supposed to mirror each other (e.g. `status-right` vs `@local_status_right`), confirm parity with `xxd`, not eyeballing. |
| **Daemon-installed integrations drift ahead of source.** `herdr` (and similar) install versioned hooks per-agent at runtime; source lags a version behind. `chezmoi diff` shows home-newer everywhere but looks like hand-edits. | Decide direction with `herdr integration status --outdated-only` (or the agent's own `status` cmd) — if home reports "current", home is canonical: `chezmoi re-add` home→source for all 5 sister files at once. Don't mktemp-probe these (the daemon checks installed-against-current, not install-time output). |
| **App-owned configuration is not chezmoi drift.** `~/.codex/config.toml` is app-owned and is not a chezmoi-managed target. Other runtime-edited files may still be intentionally managed as a seeded base. | Exclude app-owned files from reconciliation and inspect them with the owning app or CLI. For managed runtime-edited files, surface drift and decide direction explicitly before applying. |
| **`chezmoi diff <directory>` silently reports nothing.** It exits 0 with empty output even when files beneath it differ — a false "clean" that reads exactly like a real one. Cost a session a wrong "no apply needed" claim. | Only `chezmoi diff <file>` and bare `chezmoi diff` are trustworthy. To scope a check, run bare `chezmoi diff` and grep the `^diff --git` lines. |
| **Never put prose bodies in `.chezmoitemplates/`.** chezmoi *eagerly parses every file* there at startup, so one literal `{{` in any file breaks `chezmoi apply` **globally** — not just that file. `skills/agentic-actions-auditor` is full of literal `${{ github.event.* }}`, which would take down the codex profile routing that shares the registry. | Shared prose (skill bodies) lives in `.skills-src/` — a plain dot-dir chezmoi ignores as a target and never parses — pulled in with `{{ include ".skills-src/..." }}`, which reads the file **literally**. Reserve `.chezmoitemplates/` for content you actually want templated. |

## Caveat

Live application follows repository policy. Never use bare `chezmoi apply`, and
never apply from a headless loop. An interactive agent may apply
only exact composed targets explicitly authorized in the current conversation,
then must verify those exact targets. Otherwise stop after rendering and diffing.
