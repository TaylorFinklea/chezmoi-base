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

Initial TOML contains only these exact files:

`base.toml`:

```toml
[data]
machine_role = "personal"
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
