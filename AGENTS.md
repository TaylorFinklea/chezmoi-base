# chezmoi-base front door

This public repository is the entry point for dotfile changes on all machines. This file is repository guidance, listed in `.chezmoiignore`, and is never a managed target.

## Ownership and routing

| Repository | Machines | Owns |
|---|---|---|
| `chezmoi-base` (this repo) | all | Generic, sanitized, public-safe configuration |
| `~/git/chezmoi-personal` | personal Macs | Personal and private configuration |
| `~/git/chezmoi-work` | work and personal Macs | Work-specific configuration |

Composition is base plus exactly one overlay. One rendered target has one owner; `scripts/chezmoi-compose preflight personal` and `preflight work` must both pass before changing ownership.

Use Beads as the actionable issue, dependency, assignment, and status tracker for coding work in every project. Markdown in the owning repository carries roadmap direction, milestones, rationale, and handoff, with Beads ID references instead of a duplicate issue-status ledger. On a personal Mac, read `../chezmoi-personal/.docs/ai/current-state.md` first for personal overlay context when starting dotfile work. Consult its roadmap or decisions when relevant; do not copy private personal context into base. Work-Mac sessions rely on recent commits and this guide, plus the owning repository's docs when available.

1. Edit an existing target in its current owner. Locate it in source or with `chezmoi managed`.
2. Put new content in base only when it is generic, safe for a public repository, and wanted on both machine types. Run the public-safety scanner. Base templates may branch on `machine_role`, never `ai_profile`.
3. Keep personal or private content in `chezmoi-personal`; on a work Mac, defer rather than clone or stage it elsewhere.
4. Keep work-only content in `chezmoi-work`.
5. Base owns shared Codex instructions and native agent definitions. `~/.codex/config.toml`, plugins, MCP connections, permissions, and runtime state are app-owned. Overlays may own their Codex hooks, skill sources, and private integration catalogs.

Never clone the personal repo on a work machine or put secrets, credentials, personal or work identifiers, Hermes content, or private remote URLs in base.

## Reach and ownership changes

Base and work changes reach work machines; confirm when a request sounds personal. Personal changes do not reach work. For an “everywhere” request, use safe base ownership or duplicate into work with a parity test. Pushing base publishes its contents.

To move a target, remove it from the old owner and add it to the new owner; preflight both roles and run the scanner if base gains content. Never add an overlay `.chezmoiremove` for a target now owned by base: it deletes the live target and preflight cannot detect it.

## Checks and live application

Use `scripts/chezmoi-compose diff <role>` for a non-applying diff. Before a base commit, run `python3 scripts/check-public-safety.py`, its test suite, and `bash tests/test-compose.sh`; run both profile preflights for ownership changes. Cross-overlay parity tests live in the personal repo and run on the personal Mac.

Routine convergence uses `scripts/chezmoi-compose sync` (`chezmoi-sync`). It applies clean drift only and reports conflicts for the user to resolve. `.codex/config.toml` is app-rewritten and skip-listed as expected drift; do not import or reconcile it as chezmoi state. A live interactive sync or targeted `scripts/chezmoi-compose apply <role> <target>...` requires current-conversation authorization for that exact command and scope. Restate the command and scope before running; authorization covers one operation and expires when it completes or the conversation ends. Do not broaden targets or choose conflicts. Bare `chezmoi apply`, headless apply, unattended conflict resolution, and unapproved `--force` are forbidden.
