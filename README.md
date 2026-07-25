# chezmoi-base

This public repository contains generic configuration only.

It is composed with exactly one overlay: either private personal or private work. It never contains Hermes, credentials, personal identifiers, work identifiers, or private remote URLs.

Public clone URL: https://github.com/TaylorFinklea/chezmoi-base.git

## Normal daily composition

The runner supports `preflight`, `diff`, and `verify`; it never runs `apply`. With no environment overrides, those commands use the per-source TOML files in `~/.config/chezmoi-compose` and per-source persistent state in `~/.local/state/chezmoi-compose`. The state files are operational state, not managed configuration or targets written by chezmoi.

```bash
# Personal Mac: base + private personal overlay
~/git/chezmoi-base/scripts/chezmoi-compose preflight personal
~/git/chezmoi-base/scripts/chezmoi-compose diff personal
~/git/chezmoi-base/scripts/chezmoi-compose verify personal

# Work Mac: base + private work overlay
~/git/chezmoi-base/scripts/chezmoi-compose preflight work
~/git/chezmoi-base/scripts/chezmoi-compose diff work
~/git/chezmoi-base/scripts/chezmoi-compose verify work
```

These normal commands do not write managed targets to `HOME`.
Each successful preflight runs target-ownership validation before `skillsync check`. Work preflight validates its catalog and lock without reading work Skill sources unless `--require-sources` is supplied. `diff` appends the non-applying `skillsync diff`. `sync` requires a source-validating Skills check before any apply, then runs `skillsync sync --non-interactive` only after repository updates, preflight, and a clean chezmoi sync; Skills conflicts are reported, notified, and left untouched.


## Isolated validation

Validation that needs direct `chezmoi apply` commands uses a separate temporary destination and state directory: set both `CHEZMOI_DESTINATION` and `CHEZMOI_STATE_ROOT` to `mktemp -d` paths for the runner, pass explicit temporary `--persistent-state` files to each direct apply, and remove both directories with an `EXIT` cleanup trap. The complete personal and work recipes are in [docs/local-data.md](docs/local-data.md).

Neither normal composition nor isolated validation permits a managed target write to `HOME`. A later human-reviewed, targeted apply is required after source ownership is established.
