# Roadmap

> Project direction and milestone status. Beads owns actionable tasks and
> dependencies after activation; link issue IDs rather than duplicating their
> status. A roadmap item never authorizes work.

## Vision

Shared base layer of the three-repo chezmoi setup (base / personal / work) —
the front door for all dotfile changes on any machine.

## Now / Next / Later

### Now

- [ ] **BEADS-DEFAULT — Default Beads integration for both machine profiles.**
      Approved 2026-11-03. Shared Codex/OpenCode guidance and profile provisioning
      are implemented; personal activation and base/work publication succeeded.
      Bootstrap follow-up is tracked in Beads `chezmoi-base-iil`; work-machine
      runtime remains unverified. Acceptance:
      separate per-project stores, no personal/work queue sharing or automatic
      remote sync, isolated functional checks, profile composition checks,
      independent reviews, and scoped source commits. Live activation requires
      separately authorized exact commands and targets.

### Next

- None queued.

### Later

- None queued.

## Completed

- [x] **2026-10-31: Clarify lead-owned Markdown task state and handoffs.**
      Shared guidance, owner-repository routing, and base tracking docs now
      define one status record, meaningful updates, and authorized task
      selection. Required source checks and independent Sol plus direct
      DeepSeek reviews passed. Source-only; no live apply.

## Backlog

> Capture enough scope and completion detail to make a nontrivial item
> actionable. Add owners, dependencies, and verification steps when useful;
> there is no mandatory tier or complexity taxonomy. An item is not permission
> to start: the lead assigns work within the user's approved scope.

### Historical carryover (not scheduled)

Old Herdr/OMP and skillsync notes are historical context only, not active work.
Revalidate against current source and obtain a lead assignment before
rescheduling or acting on them.

- Herdr Ask OMP was recorded as retired on 2026-10-01; prior apply and
  work-profile notes are stale and require revalidation.
- An older note proposed adopting 91 unmanaged codex/pi/hermes skills with
  skillsync. Its status and assumptions are stale and require revalidation.

## Constraints

- A live interactive composed sync or targeted apply requires authorization in
  the current conversation for the exact command and targets; that authorization
  expires when the operation completes or the conversation ends. Bare
  `chezmoi apply`, headless apply, unattended conflict resolution, and
  unapproved `--force` are forbidden.
- Changes here propagate to the work machine too — verify reach before landing.
