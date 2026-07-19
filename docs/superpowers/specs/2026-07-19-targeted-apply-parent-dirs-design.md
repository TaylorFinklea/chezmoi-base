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

Keep exact managed-target validation and base/overlay batching unchanged. Add
chezmoi's native `--parent-dirs` option to both targeted apply invocations:

```text
chezmoi apply --parent-dirs -- <validated-targets>
```

Chezmoi, rather than the wrapper, creates required parents and applies any
managed parent attributes. The wrapper must not call `mkdir -p`: doing so could
create security-sensitive directories with generic umask-derived modes.

Directory targets remain unsupported because ownership routing is based on the
exact absolute file/symlink lists returned by each source's `chezmoi managed`.
Routine `sync`, `diff`, `verify`, and preflight behavior do not change.

## Error behavior

- Unmanaged targets still fail before any apply call.
- Ownership collisions still fail in preflight.
- A base-owned target is still applied only through base; an overlay-owned
  target only through the selected overlay.
- Any native chezmoi parent/application failure propagates unchanged.

## Tests

Extend `tests/test-compose.sh` so its fake chezmoi:

1. records `apply --parent-dirs -- <targets>`;
2. rejects a targeted file whose parent is absent when `--parent-dirs` is
   missing;
3. creates the missing parent and target when the flag is present;
4. verifies base and overlay batches both use the flag;
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

A targeted apply of a newly introduced nested managed file succeeds against an
empty destination tree without any manual directory creation, while exact
ownership routing and public-safety gates remain green.
