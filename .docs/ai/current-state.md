# Current State

**Branch:** `main`
**Updated:** 2026-11-09

## Active work

[BEADS-DEFAULT](roadmap.md#now) uses separate per-project personal/work stores.
Codex review-policy source verification is tracked in `chezmoi-base-i2b` and
`chezmoi-personal-in6`. Current activation and publication receipts, remaining
scope decisions, and rollout status live in `chezmoi-base-8s0`.

**Resume:** Read the rollout issue before another live operation; prior
exact-target apply approval is consumed when that operation finishes.
Revalidate current sources and live targets before any newly authorized
rollout. Work activation and runtime must be verified on that machine,
never by applying its overlay to personal HOME.

## Blockers

- Work-machine runtime cannot be qualified by local source checks.

## Evidence and limits

- Separate temporary project stores passed creation, dependency, claim,
  close/reopen, persistence, and cross-store visibility checks. Both profile
  preflights and rendered ownership checks passed with isolated configuration;
  the compose suite, public-safety scanner, and 53 scanner tests passed.
- Reviewed base and work commits were pushed and verified at `origin/main`;
  the personal repository was not pushed. The authorized three-target
  personal apply succeeded; live Codex, OpenCode, and HOME instructions matched
  their reviewed sources. The personal merge preserved unrelated live policy.
- Initial isolated fixtures had no Git remotes. A real base-project init showed
  that Beads 1.2.2 infers a Dolt remote from Git origin even with `--sandbox`.
  No task data was pushed. The inferred remote was removed, local-only mode and
  contributor role were verified, and this project's embedded store was kept
  outside public Git. No hooks or archives were installed or imported.
- The corrected recipe passed a fake-origin regression, local embedded-store
  and contributor-role checks, policy parity, shell syntax, and diff hygiene.
  The compose suite and 53 public-safety tests passed; the public scanner passed
  on a source snapshot excluding the ignored local task database.
- A subsequent authorized apply stopped at the scanner before changing either
  target: the live checkout's ignored local Beads database was being scanned.
  Scanner integration must preserve checks on every tracked or staged file;
  current resolution and rollout evidence belong to the issue above.

Keep this file as a compact entry point and handoff. The roadmap retains project
direction and milestone references; Beads owns actionable tasks. Native Goals
retain the approved thread outcome and lifecycle.
