# Codex Forge

Codex Forge packages the `$forge` workflow for shaping an Execution Brief,
getting an explicit approval, and running verified work either directly in
Codex or through guarded Ralph dispatch.

## Install and update

The managed chezmoi installer registers the `local-managed` marketplace and
installs `codex-forge` from the local marketplace. It uses Codex's native
commands and is safe to run repeatedly:

```bash
codex plugin marketplace add "$HOME/.local/share/codex-forge-marketplace" --json
codex plugin add codex-forge --marketplace local-managed --json
```

The plugin version is `0.1.0`. A source update changes the managed installer
hash, so chezmoi can run the same update path after a version bump. Inspect
installation and enabled status with:

```text
codex plugin list --marketplace local-managed --json
```

## Trust and hooks

Forge uses plugin-scoped lifecycle hooks for heartbeat, tool policy, approval,
verification, and stop handling. After installation, open Codex's `/hooks`
view, review the `codex-forge` commands, and explicitly trust them before using
`$forge`. Restart Codex after changing trust. Forge reports missing or
untrusted hook heartbeats instead of claiming that the workflow is protected.

## `$forge` and approval

Use `$forge` to begin shaping. Forge first gathers repository context, then
asks only material questions and freezes an Execution Brief. Approval is a
user-originated command containing the displayed, single-use nonce:

```text
approve <nonce> direct
approve <nonce> ralph
revise <nonce>
cancel <nonce>
```

The nonce binds approval to the current session and repository and expires.
Never copy a nonce from another session or approve a brief whose scope is not
what you intend. `revise` invalidates approval and returns to shaping;
`cancel` closes a non-running session.

## Execution and status

`direct` runs the approved brief in the current Codex session and records exact
verification evidence. `ralph` is available only when its clean-repository,
plan, phase, and backend preflight checks pass. Launch returns after a detached,
plugin-owned process group is validated; its supervisor drains output into
private bounded tail files and atomically records the terminal exit receipt.
Use `$forge status` to inspect lifecycle state, selected dispatcher, bounded
approval expiry, direct verification progress, and Ralph ownership/running/
terminal status. `ralph-status` reconciles a zero receipt to completed and a
nonzero, invalid, or missing receipt to failed. Cancellation only signals a
process group still proven to be owned by Forge, with bounded graceful and
forced termination.

## Threat boundary

Forge enforces workflow policy through Codex hooks and its plugin helper; it is
not an operating-system sandbox. Codex's normal sandbox and approval settings
still govern approved execution. Users can disable hooks, leave them
untrusted, or use specialized paths outside the lifecycle coverage, and local
filesystem races are outside this version's threat model. Forge fails closed
when state, session identity, repository identity, nonce, or hook heartbeat
checks do not validate. Review the plugin source and trust decisions before
running it in a repository.
