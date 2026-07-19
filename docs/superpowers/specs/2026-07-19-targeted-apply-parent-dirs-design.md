# Targeted Apply Parent Directories

Status: approved 2026-07-19
Owner: `chezmoi-base` (public; reaches personal and work machines)

## Problem

`scripts/chezmoi-compose apply <role> <absolute-target>...` validates exact
managed-file ownership, then calls `chezmoi apply -- <targets>`. On a fresh
machine, an exact file target fails when its parent directory does not yet
exist. This forced users to create managed directory trees manually, defeating
fresh-machine reproducibility.

## Design

Keep exact managed-target validation, drift classification, decision flow, and
base/overlay batching unchanged. Add chezmoi's native `--parent-dirs` option to
every wrapper-generated apply invocation:

```text
chezmoi apply --parent-dirs -- <clean-targets>
chezmoi apply --force --parent-dirs -- <forced-or-approved-targets>
```

This covers automatic clean sync batches, force-sync batches, interactive
overwrite decisions, and the explicit targeted `apply` command. Chezmoi, rather
than the wrapper, creates required parents and applies any managed parent
attributes. The wrapper must not call `mkdir -p`: doing so could create
security-sensitive directories with generic umask-derived modes.

Directory targets remain unsupported because ownership routing is based on the
exact absolute file/symlink lists returned by each source's `chezmoi managed`.
`diff`, `verify`, preflight, pull, and drift-decision semantics do not change.

## Error behavior

- Unmanaged targets still fail before any apply call.
- Ownership collisions still fail in preflight.
- A base-owned target is still applied only through base; an overlay-owned
  target only through the selected overlay.
- Any native chezmoi parent/application failure propagates unchanged.

## Tests

Extend `tests/test-compose.sh` so its fake chezmoi:

1. records clean `apply --parent-dirs -- <targets>` and forced
   `apply --force --parent-dirs -- <targets>` calls;
2. rejects any file apply whose parent is absent when `--parent-dirs` is
   missing;
3. creates missing parents and targets when the flag is present;
4. verifies sync, interactive overwrite, base, and overlay batches all use the
   flag;
5. keeps unmanaged-target rejection unchanged.

Verify with:

```bash
bash tests/test-compose.sh
scripts/chezmoi-compose preflight personal
scripts/chezmoi-compose preflight work
python3 scripts/check-public-safety.py
python3 tests/test-public-safety.py
```

## Acceptance

Both routine sync and targeted apply can install newly introduced nested
managed files into an empty destination tree without manual directory
creation, while drift decisions, exact ownership routing, and public-safety
gates remain green.
