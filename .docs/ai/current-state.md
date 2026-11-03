# Current State

**Branch:** `main`
**Updated:** 2026-11-03

## Active work

[BEADS-DEFAULT](roadmap.md#now) uses separate per-project personal/work stores.
Actionable follow-up and verification are tracked in local Beads issue
`chezmoi-base-iil`; do not copy its task status into this document.

**Next action:** Obtain fresh exact-command approval for the local-only
bootstrap correction's activation and publication. Work-machine activation and
runtime verification must occur on
that machine; do not apply its overlay to personal HOME.

## Blockers

- Work-machine runtime cannot be qualified by local source checks.
- Prior apply and push approvals were consumed by their successful operations;
  they do not authorize another activation or publication.

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

Keep this file as a compact entry point and handoff. The roadmap retains project
direction and milestone references; Beads owns actionable tasks. Native Goals
retain the approved thread outcome and lifecycle.
