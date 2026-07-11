# chezmoi-base

This public repository contains generic configuration only.

It is composed with exactly one overlay: either private personal or private work. It never contains Hermes, credentials, personal identifiers, work identifiers, or private remote URLs.

Public clone URL: `https://github.com/TaylorFinklea/chezmoi-base.git`

The composition runner supports `preflight`, `diff`, and `verify`; it never runs `apply`.

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

`chezmoi apply` is intentionally absent; later plans supply a human-reviewed, targeted apply procedure only after source ownership is established.
