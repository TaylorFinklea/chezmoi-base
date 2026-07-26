---
name: delegate
description: "Use when orchestrating multi-step work as a Lead-tier session — dispatching to cheaper models, distributing load, or picking adversarial reviewers — or when the user says delegate/distribute/dispatch/review with another model. Loads the delegation posture, panel criteria, and model-family map. Not for native Undertake plan/review, Guildhall, or Ralph sessions."
---

# Delegate — orchestrator briefing

You are the **orchestrator** — a role, not a rank. This posture applies only
if your session model is Lead-tier per `~/.claude/templates/tiers.md`.
Unknown or below Lead → do NOT self-elevate; work your own tier and run the
normal tier self-check instead.

If you haven't yet this session, emit the allocation map now, one line:
`retain: <items> | delegate: <item→model>`.

## Delegate-when (decides WHETHER)

Delegate a task only if it is **bounded** (closed scope, clear spec),
**independent** (no tangled shared context), **verifiable** (a command or
crisp acceptance), and context transfer is cheap. Complexity (S/M/L/XL)
picks the model; boundedness decides whether to delegate at all. An S task
with tangled context stays retained; an isolated L task can go.

## Eligibility (before any dispatch — pointers, not an engine)

- Standing pre-authorized list: AGENTS.md `## Model dispatch / offloading`.
  Anything else: confirm with the user BEFORE dispatching.
- Enabled in the Musterroll roster — `musterroll roster snapshot --json`;
  fallback: read `~/git/musterroll/roster.toml` directly;
  neither available → pre-authorized list only, fail closed.
- `data_policy`: `free-trains-input` lanes need repo policy or per-bead
  opt-in.
- Reachable from THIS harness — see `references/panels.md` reachability.
- Quota: `musterroll status --json` when available; runtime 429s are the real
  signal. Never invent quota state from model prose.

## Routing (decides WHO)

Follow AGENTS.md `## Tiered model routing` (theory:
`~/.claude/templates/tiers.md`): lowest capable tier, most efficient model
whose ceiling ≥ complexity.
When Anthropic differs from the artifact author's family and Musterroll plus
the current harness confirm eligibility and reachability, `claude-opus-5` at `max`
is the preferred different-family adversarial reviewer and an available
Lead/Senior delegation option. `claude-opus-4-8` remains the fallback; an enabled
profile never proves credentials or live provider availability.

## Panels

Review shapes, the model-family map, and per-harness reachability:
`references/panels.md`. Adversarial reviews use the output contract in
`references/review-contract.md`.

## Provenance

Record the author profile for every delegated artifact. Use Afterfact evidence
when the execution path supports it; `dispatch-worker` owns the mechanics and
the interim Experience Log behavior required by AGENTS.md.

## Boundaries

- This skill is **data + criteria, never procedure** — it names shapes and
  membership rules, not orchestration logic.
- Single interactive session only. Queued, scheduled, multi-repo, or native
  Undertake `plan`/`review` work is Undertake's (see
  `guildhall-orchestration`). Undertake / Ralph sessions never load this posture.
- Mechanics live elsewhere: `dispatch-worker` (one bounded worker task),
  `fallback-orchestration` (orchestra driver), `local-models` (Ollama lane).
- When the Undertake-backed `adversarial-design-review` skill ships (spec
  2026-07-13), formal N-reviewer runs defer to it; this skill's preset stays
  the quick interactive path.
