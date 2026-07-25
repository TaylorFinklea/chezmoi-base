# git-cleanup: categorization reference

Read this at the categorization step, after running `scripts/analyze-branches.sh`.
It carries the rules that decide each branch's category and delete flag, plus the
rationalizations that lead to data loss.

## Squash-merged branches require force delete

**IMPORTANT:** `git branch -d` will ALWAYS fail for squash-merged branches
because git cannot detect that the work was incorporated. This is expected
behavior, not an error.

When you identify a branch as squash-merged:
- Plan to use `git branch -D` (force delete) from the start.
- Do NOT try `git branch -d` first and then ask again for `-D` — this wastes
  user confirmations.
- In the confirmation step (GATE 2), show `git branch -D` for squash-merged
  branches.

## Group related branches BEFORE individual categorization

**MANDATORY.** Branches sharing a name prefix (e.g. `feature/api`,
`feature/api-v2`, `feature/api-refactor`) are almost certainly related
iterations. The prefix groups are printed by `analyze-branches.sh`. For each
group with 2+ branches:

1. **Compare commit histories** — which branches contain commits from others?
2. **Find merge evidence** — which PRs incorporated work from this group?
3. **Identify the "final" branch** — usually the most recent or most complete.
4. **Mark superseded branches** — older iterations whose work is in main or in a
   newer branch.

**SUPERSEDED requires evidence, not just a shared prefix:**
- A PR merged the work into main, OR
- A newer branch contains all commits from the older branch.
- Name prefix alone is NOT sufficient — similarly named branches may contain
  independent work.

Present each group as a markdown table with columns **Branch | Commits | PR
Merged | Status**, then a one-line recommendation citing the PR numbers that
incorporated the work.

## Thorough PR-history investigation

Don't rely on simple keyword matching. For `[gone]` branches:

```bash
# 1. Get the branch's commits that aren't in default branch
git log --oneline "$default_branch".."$branch"

# 2. Search default branch for PRs that incorporated this work
#    (search by branch name, commit message keywords, PR numbers)
git log --oneline "$default_branch" | grep -iE "(branch-name|keyword|#[0-9]+)"

# 3. For related branch groups, trace which PRs merged which work
git log --oneline "$default_branch" | grep -iE "(#[0-9]+)" | head -20
```

## Individual categorization decision tree

For branches NOT in a related group:

```
Is branch merged into default branch?
├─ YES → SAFE_TO_DELETE (use -d)
└─ NO → Is tracking a remote?
        ├─ YES → Remote deleted? ([gone])
        │        ├─ YES → Was work squash-merged? (check main for PR)
        │        │        ├─ YES → SQUASH_MERGED (use -D)
        │        │        └─ NO → REMOTE_GONE (needs review)
        │        └─ NO → Local ahead of remote? (git log origin/<branch>..<branch>)
        │                ├─ YES (has output) → UNPUSHED_WORK (keep)
        │                └─ NO (empty output) → SYNCED_WITH_REMOTE (keep)
        └─ NO → Has unique commits?
                ├─ YES → LOCAL_WORK (keep)
                └─ NO → SAFE_TO_DELETE (use -d)
```

## Category definitions

| Category | Meaning | Delete Command |
|----------|---------|----------------|
| SAFE_TO_DELETE | Merged into default branch | `git branch -d` |
| SQUASH_MERGED | Work incorporated via squash merge | `git branch -D` |
| SUPERSEDED | Part of a group, work verified in main via PR or in newer branch | `git branch -D` |
| REMOTE_GONE | Remote deleted, work NOT found in main | Review needed |
| UNPUSHED_WORK | Has commits not pushed to remote | Keep |
| LOCAL_WORK | Untracked branch with unique commits | Keep |
| SYNCED_WITH_REMOTE | Up to date with remote | Keep |

## Rationalizations to reject

These are common shortcuts that lead to data loss. Reject them:

| Rationalization | Why It's Wrong |
|-----------------|----------------|
| "The branch is old, it's probably safe to delete" | Age doesn't indicate merge status. Old branches may contain unmerged work. |
| "I can recover from reflog if needed" | Reflog entries expire. Users often don't know how to use reflog. Don't rely on it as a safety net. |
| "It's just a local branch, nothing important" | Local branches may contain the only copy of work not pushed anywhere. |
| "The PR was merged, so the branch is safe" | Squash merges don't preserve branch history. Verify the *specific* commits were incorporated. |
| "I'll just delete all the `[gone]` branches" | `[gone]` only means the remote was deleted. The local branch may have unpushed commits. |
| "The user seems to want everything deleted" | Always present analysis first. Let the user choose what to delete. |
| "The branch has commits not in main, so it has unpushed work" | "Not in main" ≠ "not pushed". A branch can be synced with its remote but not merged to main. Always check `git log origin/<branch>..<branch>`. |
