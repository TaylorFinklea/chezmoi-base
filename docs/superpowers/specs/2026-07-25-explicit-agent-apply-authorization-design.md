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

## Current Authorization

The user explicitly authorized `scripts/chezmoi-compose sync` in this conversation after approving this policy amendment. Once the policy commits, the agent may execute that one sync and verify `dispatch-worker` activation.
