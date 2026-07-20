---
name: forge
description: Use $forge to shape a Codex Forge brief before implementation.
---

# `$forge`

`$forge` is a guarded shaping workflow. It does not implement the requested
work; it produces an immutable brief and an exact approval command for the
hook-controlled session.

## Rules

1. **Recon first.** Begin with read-only reconnaissance of the current
   repository, relevant files, existing conventions, and verification commands.
   Do not infer facts that can be checked directly.
2. Ask **one focused question at a time**. The default cap is **3 questions**;
   **5 is the hard maximum**. Refuse a sixth question and ask the user to
   revise the scope or provide a decision.
3. While shaping, make **no writes**: no file edits, generated files, git
   mutations, installs, deployments, or shell environment overrides. Use only
   the hook-permitted read-only tools and the managed forge-scout.
4. Require a current hook heartbeat before each control-CLI mutation. Refuse
   to continue if the heartbeat or the exact cwd/repository binding is absent or
   stale. Never accept model-provided session or data identity.
5. Resolve the CLI relative to this loaded SKILL.md: `../../bin/codex-forge`.
   Invoke that installed canonical path directly. Do not substitute `python`, a
   PATH lookup, a copied helper, a model-visible `PLUGIN_ROOT` variable, or a
   path under `hooks/`.
6. Structured inputs are one exact unpadded base64url argument. Build the JSON
   value in the model's reasoning, encode its UTF-8 bytes with the base64url
   alphabet (`A-Z`, `a-z`, `0-9`, `_`, `-`), and remove any trailing `=`
   padding. Do not start a Python, `base64`, Node, or other encoder process.
   Do not use pipes, heredocs, redirects, command substitution, chaining,
   `write_stdin`, or a supplied `env` object. The hook validates this grammar
   before injecting its own session/data environment.
7. Begin, status, and complete take no payload argument. Question, freeze, and
   fail each take exactly one encoded JSON argument:
   `../../bin/codex-forge question <payload>`,
   `../../bin/codex-forge freeze <payload>`, or
   `../../bin/codex-forge fail <payload>`. Never send structured input on
   stdin. The CLI decodes UTF-8 and validates exactly one JSON value before
   applying question, brief, or failure validation.
8. Freeze by invoking `../../bin/codex-forge freeze <payload>` directly. Do not
   claim a freeze from prose. The CLI validates and digests the brief and
   creates the single-use nonce.
9. Present exactly the nonce choices emitted by the CLI: `approve <nonce> direct`,
   `approve <nonce> ralph`, `revise <nonce>`, or `cancel <nonce>`. Do not accept
   prose-only approval, altered nonce text, or an omitted dispatcher. Choose
   direct for a bounded task and Ralph only when the frozen brief explicitly
   calls for its bounded phase loop.
10. Do not start implementation until the hook confirms the exact nonce choice
    and the CLI/state transition. `$forge` does not implement execution,
    verification recording, Ralph orchestration, or completion behavior owned by
    later tasks.

## Procedure

- Resolve `../../bin/codex-forge` from this skill file before every invocation;
  use `begin` only after recon and only with hook-injected environment.
- Use `question <payload>` with one encoded JSON object at a time. Keep the
  encoded argument within the CLI's fixed bound and never interpolate shell
  text.
- Build the complete brief, encode it internally as described above, and call
  `../../bin/codex-forge freeze <payload>` directly.
- End the frozen turn by printing only the brief summary and the four exact
  approve/revise/cancel command choices. Never print a made-up nonce.
- After the user chooses, let the hook-confirmed state transition determine
  whether direct or Ralph execution is available; do not bypass it.
