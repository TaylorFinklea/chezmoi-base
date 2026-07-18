# Local data

## Normal daily composition

Local composition TOML and persistent state live outside every source repository:

```text
~/.config/chezmoi-compose/base.toml
~/.config/chezmoi-compose/personal.toml
~/.config/chezmoi-compose/work.toml
~/.local/state/chezmoi-compose/base.boltdb
~/.local/state/chezmoi-compose/personal.boltdb
~/.local/state/chezmoi-compose/work.boltdb
```

With no environment overrides, `chezmoi-compose preflight`, `diff`, and `verify` select the TOML and persistent-state file for each source:

| Source | TOML | Persistent state |
| --- | --- | --- |
| base | `~/.config/chezmoi-compose/base.toml` | `~/.local/state/chezmoi-compose/base.boltdb` |
| personal overlay | `~/.config/chezmoi-compose/personal.toml` | `~/.local/state/chezmoi-compose/personal.boltdb` |
| work overlay | `~/.config/chezmoi-compose/work.toml` | `~/.local/state/chezmoi-compose/work.boltdb` |

The TOML files are local composition inputs. The XDG state files are operational state, not managed configuration or targets written by chezmoi. Do not add either to a source repository. The runner's read-only commands (`preflight`, `diff`, `verify`) never write managed targets to `HOME`; `sync` and `apply` are the only writer subcommands.

Initial TOML contains only these exact files. On a personal Mac, `base.toml` is:

```toml
[data]
machine_role = "personal"
```

On a work Mac, `base.toml` is:

```toml
[data]
machine_role = "work"
```

`personal.toml`:

```toml
[data]
ai_profile = "personal"
machine_role = "personal"
```

`work.toml`:

```toml
[data]
ai_profile = "work"
machine_role = "work"
```

## Sync automation

`chezmoi-sync` (shim at `~/.local/bin/chezmoi-sync`) runs
`chezmoi-compose sync` for the machine's role: ff-only pull, preflight,
auto-apply clean drift, and per-file decisions for real conflicts
(non-interactive runs leave conflicts untouched, exit 2, and post a
notification). Log: `~/.local/state/chezmoi-compose/sync.log`.

Activate the daily launchd schedule once per machine:

```sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.chezmoi-compose.sync.plist
```

## Isolated validation with direct applies

Use direct applies only to validate a composition against temporary paths. Create both the destination and state root with `mktemp -d`; pass them as `CHEZMOI_DESTINATION` and `CHEZMOI_STATE_ROOT` to every runner command. Each direct apply must name its own temporary `--persistent-state` file. The recipes fail fast and use an `EXIT` trap to remove both temporary directories after success or failure. Never substitute `HOME` for the temporary destination.

### Personal: base + personal overlay

```bash
(
  set -eu
  personal_destination="$(mktemp -d)"
  personal_state=
  cleanup_personal_validation() {
    rm -rf "$personal_destination" "${personal_state:-}"
  }
  trap cleanup_personal_validation EXIT
  personal_state="$(mktemp -d)"

  CHEZMOI_DESTINATION="$personal_destination" CHEZMOI_STATE_ROOT="$personal_state" "$HOME/git/chezmoi-base/scripts/chezmoi-compose" preflight personal
  CHEZMOI_DESTINATION="$personal_destination" CHEZMOI_STATE_ROOT="$personal_state" "$HOME/git/chezmoi-base/scripts/chezmoi-compose" diff personal
  chezmoi --source "$HOME/git/chezmoi-base" --config "$HOME/.config/chezmoi-compose/base.toml" --persistent-state "$personal_state/base.boltdb" --destination "$personal_destination" apply
  chezmoi --source "$HOME/git/chezmoi-personal" --config "$HOME/.config/chezmoi-compose/personal.toml" --persistent-state "$personal_state/personal.boltdb" --destination "$personal_destination" apply
  CHEZMOI_DESTINATION="$personal_destination" CHEZMOI_STATE_ROOT="$personal_state" "$HOME/git/chezmoi-base/scripts/chezmoi-compose" verify personal
)
```

### Work: base + work overlay

```bash
(
  set -eu
  work_destination="$(mktemp -d)"
  work_state=
  cleanup_work_validation() {
    rm -rf "$work_destination" "${work_state:-}"
  }
  trap cleanup_work_validation EXIT
  work_state="$(mktemp -d)"

  CHEZMOI_DESTINATION="$work_destination" CHEZMOI_STATE_ROOT="$work_state" "$HOME/git/chezmoi-base/scripts/chezmoi-compose" preflight work
  CHEZMOI_DESTINATION="$work_destination" CHEZMOI_STATE_ROOT="$work_state" "$HOME/git/chezmoi-base/scripts/chezmoi-compose" diff work
  chezmoi --source "$HOME/git/chezmoi-base" --config "$HOME/.config/chezmoi-compose/base.toml" --persistent-state "$work_state/base.boltdb" --destination "$work_destination" apply
  chezmoi --source "$HOME/git/chezmoi-work" --config "$HOME/.config/chezmoi-compose/work.toml" --persistent-state "$work_state/work.boltdb" --destination "$work_destination" apply
  CHEZMOI_DESTINATION="$work_destination" CHEZMOI_STATE_ROOT="$work_state" "$HOME/git/chezmoi-base/scripts/chezmoi-compose" verify work
)
```

These direct applies may write managed targets only to their temporary destinations. The `EXIT` trap removes both temporary directories after validation, including when a command fails. Neither this validation mode nor normal daily composition permits a managed target write to `HOME`; a later human-reviewed, targeted apply is required after source ownership is established.
