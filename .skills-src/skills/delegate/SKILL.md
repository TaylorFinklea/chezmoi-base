---
name: delegate
description: "Use when orchestrating multi-step work as a Lead-tier session — dispatching to cheaper models, distributing load, or picking adversarial reviewers — or when the user says delegate/distribute/dispatch/review with another model. Loads the delegation posture, panel criteria, and model-family map. Not for Conductor/Guildhall/Arena/Ralph sessions."
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
- Enabled in the Bursar roster — `bursar roster snapshot --json`; fallback:
  read `~/git/bursar/roster.toml` directly; neither available
  → pre-authorized list only, fail closed.
- `data_policy`: `free-trains-input` lanes need repo policy or per-bead
  opt-in.
- Reachable from THIS harness — see `references/panels.md` reachability.
- Quota: `bursar status --json` when available; runtime 429s are the real
  signal. Never invent quota state from model prose.

## Routing (decides WHO)

Follow AGENTS.md `## Tiered model routing` (theory:
`~/.claude/templates/tiers.md`): lowest capable tier, most efficient model
whose ceiling ≥ complexity.

## Panels

Review shapes, the model-family map, and per-harness reachability:
`references/panels.md`. Adversarial reviews use the output contract in
`references/review-contract.md`.

## Logging

Every non-default dispatch gets a one-line Experience Log entry
(`~/.claude/model-scorecard.md`) per AGENTS.md; the `dispatch-to-pi` skill
owns dispatch mechanics and the scoring format.

## Boundaries

- This skill is **data + criteria, never procedure** — it names shapes and
  membership rules, not orchestration logic.
- Single interactive session only. Queued, scheduled, or multi-repo work is
  Conductor's (see `guildhall-orchestration`). Conductor / Arena / Ralph
  sessions never load this posture.
- Mechanics live elsewhere: `dispatch-to-pi` (pi offload),
  `fallback-orchestration` (orchestra driver), `local-models` (Ollama lane).
- When the Conductor-backed `adversarial-design-review` skill ships (spec
  2026-07-13), formal N-reviewer runs defer to it; this skill's preset stays
  the quick interactive path.
