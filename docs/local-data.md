# Local data

Local composition data and state live at these exact locations:

```text
~/.config/chezmoi-compose/base.toml
~/.config/chezmoi-compose/personal.toml
~/.config/chezmoi-compose/work.toml
~/.local/state/chezmoi-compose/base.boltdb
~/.local/state/chezmoi-compose/personal.boltdb
~/.local/state/chezmoi-compose/work.boltdb
```

Initial TOML contains only one of these forms:

```toml
[data]
machine_role = "personal"
```

or:

```toml
[data]
machine_role = "work"
```

Later Hermes values are permitted only in the personal local data file.
