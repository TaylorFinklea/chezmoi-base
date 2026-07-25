---
name: git-cleanup
description: "Safely analyzes and cleans up local git branches and worktrees by categorizing them as merged, squash-merged, superseded, or active work."
disable-model-invocation: true
allowed-tools:
  - Bash
  - Read
  - Grep
  - AskUserQuestion
---

# Git Cleanup

Safely clean up accumulated git worktrees and local branches by categorizing them
into: safely deletable (merged), potentially related (similar themes), and active
work (keep).

This skill is a thin spine. The mechanical state-gathering lives in
`scripts/analyze-branches.sh`; the rules for deciding each branch's category and
delete flag live in `references/categorization.md`. The safety gates below stay
here — they are the part that must never be skipped.

## When to Use

- When the user has accumulated many local branches and worktrees
- When branches have been merged but not cleaned up locally
- When remote branches have been deleted but local tracking branches remain

## When NOT to Use

- Do not use for remote branch management (this is local cleanup only)
- Do not use for repository maintenance tasks like gc or prune
- Not designed for headless or non-interactive automation (requires user confirmations at two gates)

## Core Principle: SAFETY FIRST

**Never delete anything without explicit user confirmation.** This skill uses a
gated workflow where users must approve before any destructive action. Branch
names can contain characters that break shell expansion — always quote
`"$branch"` in commands.

## Workflow

### Phase 1: Gather state

Run the bundled analyzer from inside the target repo — it gathers everything in
one read-only pass (it never deletes):

```bash
bash scripts/analyze-branches.sh
```

It prints: default/protected branches, `git branch -vv`, worktrees, merged
branches, recent PR merge history, per-branch unique-commit + unpushed status,
name-prefix groups, and dirty-state warnings for every worktree and the cwd.

### Phase 2: Categorize

Read `references/categorization.md` and apply it to the analyzer output:

1. **Group related branches FIRST.** Branches sharing a name prefix are likely
   related iterations — analyze them as a group and mark superseded ones only
   with evidence (a PR merged the work, or a newer branch contains all commits).
   Name prefix alone is never sufficient.
2. **Then categorize the rest individually** via the decision tree, mapping each
   to its category and correct delete flag (`-d` merged, `-D` squash-merged /
   superseded).

The reference also carries the squash-merge force-delete rule, the PR-history
investigation commands, the full category table, and the rationalizations to
reject. Consult it before assigning any category.

### GATE 1: Present complete analysis

Present everything in ONE comprehensive view, organized as:

1. **Related Branch Groups** — one table per group with columns Branch | Status | Evidence; one-line recommendation per group.
2. **Individual Branches** — separate sub-tables for "Safe to delete (-d)", "Safe to delete (squash-merged, -D)", "Needs review", and "Keep".
3. **Worktrees** — Path | Branch | Status table. Flag any DIRTY worktree prominently — its uncommitted changes will be LOST on removal.
4. **Summary** — counts per category, then ask what to clean up.

Use AskUserQuestion with options:
- Delete all recommended (groups + merged + squash-merged)
- Delete specific groups/categories
- Let me pick individual branches

**Do not proceed until user responds.**

### GATE 2: Final confirmation with exact commands

Show the EXACT commands that will run, with correct flags:

```markdown
I will execute:

# Merged branches (safe delete)
git branch -d fix/typo

# Squash-merged / superseded branches (force delete - work is in main via PRs)
git branch -D feature/login
git branch -D feature/api

# Worktrees
git worktree remove ../proj-auth

Confirm? (yes/no)
```

**IMPORTANT:** This is the ONLY confirmation needed for deletion. Do not add
extra confirmations if `-D` is required. Refuse to remove a dirty worktree
without explicit data-loss acknowledgment.

### Phase 3: Execute

Run each deletion as a **separate command** so partial failures don't block
remaining deletions. Report each result inline. If a deletion fails, report the
error and continue.

### Phase 4: Report

Show what was deleted (with delete flag used) and what remains. Group remaining
branches by category (current, active work, needs review). Keep it terse — the
user just confirmed at GATE 2; no need to re-justify each deletion.

## Safety Rules

1. **Never invoke automatically** — Only run when user explicitly uses `/git-cleanup`
2. **Two confirmation gates only** — Analysis review, then deletion confirmation
3. **Use correct delete command** — `-d` for merged, `-D` for squash-merged/superseded
4. **Never touch protected branches** — main, master, develop, release/* (filtered programmatically)
5. **Block dirty worktree removal** — Refuse without explicit data loss acknowledgment
6. **Group related branches** — Don't scatter them across categories
