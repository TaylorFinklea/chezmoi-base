# Explicit Agent Apply Authorization Design

## Decision

Permit an interactive agent session to run the composed chezmoi front door only when the user explicitly authorizes the exact operation in the current conversation.

## Invariants

- Authorization is operation-specific and expires when the operation completes or the conversation ends.
- The agent restates the command and scope before execution.
- Allowed entry points are `scripts/chezmoi-compose sync` and targeted `scripts/chezmoi-compose apply <role> <target>...`.
- Bare `chezmoi apply`, headless/Ralph applies, unattended conflict resolution, `--force`, and scope expansion remain forbidden unless separately and explicitly authorized where the composed command supports them.
- Interactive conflicts remain interactive; the agent does not guess an overwrite/import/skip choice.
- The agent verifies only the authorized targets after execution and reports any unrelated drift without changing it.
- An explicit interactive skip remains an unresolved decision and preserves exit
  status 2, but it does not prevent independent clean phases such as Skill
  projection from running. Non-interactive pending decisions still stop before
  those phases.
