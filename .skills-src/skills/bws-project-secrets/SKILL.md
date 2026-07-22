---
name: bws-project-secrets
description: "Provision, migrate, and run Bitwarden Secrets Manager project secrets. Use when a user asks to set up, migrate, repair, or use BWS secrets for a repository under ~/git."
---

# BWS project secrets

Use the managed workflow. Never print, copy, or place a secret value in a
tracked file, command argument, report, or chat response.

## Onboard a repository

When the user asks to set up or migrate BWS secrets for the current repository,
complete this workflow without asking them to run intermediate commands:

1. Confirm the working directory is the repository root beneath `~/git`.
2. Locate the chezmoi source root with `dirname "$(chezmoi source-path ~/AGENTS.md)"`.
3. Run `scripts/onboard-project-to-bitwarden.py` from that source root with the
   repository, managed registry source, and dotenv migrator arguments.
4. Targeted-apply `~/.local/bin/bws-project` and
   `~/.config/bitwarden-secrets/projects.json`.
5. Run `bws-project audit --mode weekly` and report only the project/repository
   name and audit outcome.

The onboarding command creates or reuses a same-named BWS project, imports
likely dotenv secrets with their environment-variable names, and records only
the BWS project ID in the registry. It does not modify local dotenv files.

Stop and explain the non-secret conflict if the registry already has the repo,
multiple BWS projects share its name, dotenv keys collide, or BWS rejects an
operation. Do not improvise a shared project or an exception; obtain the user's
explicit direction.

## Run a project

Use `bws-project run -- <command>` from inside a registered repository. Do not
export `BWS_ACCESS_TOKEN` or call `bws run` directly.
