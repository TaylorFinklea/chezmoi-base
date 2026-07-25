#!/usr/bin/env bash
# git-cleanup: read-only branch/worktree state gathering.
#
# Prints everything the skill needs to categorize branches in ONE pass. This
# script NEVER deletes — it only inspects. Deletion stays in the skill's gated
# workflow after the user confirms. Run from inside the target repo.
#
# Sections printed: default branch, protected pattern, branches (-vv),
# worktrees, merged-into-default list, recent PR merge history, per-branch
# unique-commit + unpushed status, name-prefix groups, and dirty-state warnings
# for every worktree and the cwd.

set -uo pipefail

git rev-parse --git-dir >/dev/null 2>&1 || { echo "Not a git repo." >&2; exit 1; }

default_branch=$(git symbolic-ref refs/remotes/origin/HEAD \
  2>/dev/null | sed 's@^refs/remotes/origin/@@' || echo "main")
# Protected branches - never analyze or delete.
protected='^(main|master|develop|release/.*)$'

echo "### default branch: $default_branch"
echo "### protected pattern: $protected"

echo; echo "### local branches (-vv):"
git branch -vv

echo; echo "### worktrees:"
git worktree list

echo; echo "### fetch --prune (sync remote state):"
git fetch --prune

echo; echo "### branches merged into $default_branch:"
git branch --merged "$default_branch"

echo; echo "### recent PR merge history (squash-merge detection):"
git log --oneline "$default_branch" | grep -iE "#[0-9]+" | head -30

echo; echo "### per-branch unique commits + unpushed status:"
# For EACH non-protected branch, unique commits vs default and vs its remote.
for branch in $(git branch --format='%(refname:short)' \
  | grep -vE "$protected"); do
  echo "=== $branch ==="
  echo "Commits not in $default_branch:"
  git log --oneline "$default_branch".."$branch" 2>/dev/null | head -5
  echo "Commits not pushed to remote:"
  git log --oneline "origin/$branch".."$branch" 2>/dev/null | head -5 \
    || echo "(no remote tracking)"
done

echo; echo "### name-prefix groups (2+ share a prefix => likely related iterations):"
git branch --format='%(refname:short)' | sed 's/-[^-]*$//' | sort | uniq -c | sort -rn

echo; echo "### dirty-state check (uncommitted changes block worktree removal):"
# Each worktree path, then the cwd. Quote paths/branches — names can break
# shell expansion.
git worktree list --porcelain | awk '/^worktree /{print $2}' | while IFS= read -r wt; do
  status=$(git -C "$wt" status --porcelain 2>/dev/null)
  if [ -n "$status" ]; then
    echo "DIRTY worktree: $wt"
    printf '%s\n' "$status"
  fi
done
cwd_status=$(git status --porcelain 2>/dev/null)
[ -n "$cwd_status" ] && { echo "DIRTY cwd:"; printf '%s\n' "$cwd_status"; }

echo; echo "### PR-history probe for [gone] branches:"
echo "For each [gone] branch above, search $default_branch for the PR that incorporated it:"
echo "  git log --oneline \"$default_branch\" | grep -iE \"(branch-name|keyword|#[0-9]+)\""
