---
name: dispatch-to-pi
description: "Use when offloading bounded work to a different model while you orchestrate, including GPT-5.6 Sol, Terra, and Luna or cheaper Pi workers. Not for Guildhall/Conductor fleet sessions."
---

# Dispatching work to other models (you stay the orchestrator)

You (the main loop) keep planning, reviewing, and judging. Offload **bounded, well-specified**
Senior/Junior work — mechanical edits, fan-out, clear implementation items — to a cheaper model,
and reserve yourself for Lead work (architecture, decomposition, final review). This is the
inverse of `fallback-orchestration` (where Pi *is* the orchestrator); here Pi models are workers
you dispatch to.

For Guildhall/Conductor fleet sessions, queue dispatch, provider fallback, or
cycle approval, use `guildhall-orchestration`; Conductor stays the orchestrator.

## The roster — `~/.claude/model-scorecard.md`

The session-owned, cross-project **model scorecard** is the source of truth for who does what.
Read it to route; it overrides the illustrative ratings in `~/.claude/templates/tiers.md`. A
project may override with its own `.docs/ai/model-scorecard.md`. Current dispatch IDs:

| Model | Dispatch ID | Owns | Gate |
|---|---|---|---|
| sonnet-5 | Claude Task subagent / Workflow | Lead (all but hardest) / Senior | native — no gate |
| sonnet-4.6 | Claude Task subagent | Senior (L) | native — no gate |
| gpt-5.6-sol | `openai-codex/gpt-5.6-sol` at `max` | Lead / Architect (XL) | pre-authorized |
| gpt-5.6-terra | `openai-codex/gpt-5.6-terra` at `xhigh` | Lead (XL) | pre-authorized |
| gpt-5.6-luna-senior | `openai-codex/gpt-5.6-luna` at `high`/`xhigh`/`max` | Senior (L) | pre-authorized |
| gpt-5.6-luna-junior | `openai-codex/gpt-5.6-luna` at `low`/`medium` | Junior (S) | pre-authorized |
| minimax-m3 | `opencode-go/minimax-m3` | Senior (M) | pre-authorized |
| qwen3.7-max | `opencode-go/qwen3.7-max` | Senior (M) | pre-authorized |
| glm-5.2 | `opencode-go/glm-5.2` | Senior (M) | pre-authorized |
| ollama-glm-5.2 | `ollama-cloud/glm-5.2` | Senior (M) | pre-authorized |
| ollama-kimi-k2.6 | `ollama-cloud/kimi-k2.6` | Senior (M) | pre-authorized |
| ollama-minimax-m3 | `ollama-cloud/minimax-m3` | Senior (M) | pre-authorized |
| nw-glm-5.2 | `neuralwatt/glm-5.2` | Senior (M) | pre-authorized |
| nw-glm-5.2-short | `neuralwatt/glm-5.2-short` | Senior (M, 200K ctx) | pre-authorized |
| nw-glm-5.2-fast | `neuralwatt/glm-5.2-fast` | Junior (S, no reasoning) | pre-authorized |
| nw-kimi-k2.6 | `neuralwatt/kimi-k2.6` | Senior (M) | pre-authorized |
| nw-kimi-k2.6-fast | `neuralwatt/kimi-k2.6-fast` | Junior (S, no reasoning) | pre-authorized |

The `neuralwatt/*` models share their base model with the `opencode-go/*` lane but
sit on a **distinct provider account/quota** — use them as a fallback when the
shared opencode-go weekly cap is exhausted. The `*-fast` variants are
non-reasoning (no thinking support → Junior-tier for mechanical fan-out).

The `ollama-cloud/*` models are served by Ollama Cloud using the subscription API key. They are a distinct paid provider/quota lane for the same base models (`glm-5.2`, `kimi-k2.6`, `minimax-m3`); use the `ollama-*` / `oc-*` Ralph aliases or the full dispatch IDs above.

GPT-5.6 is not a cheap fan-out replacement: use Sol for architecture, Terra for
the hardest Lead implementation/review, Luna `high+` for Senior execution, and
Luna `low`/`medium` only for tight Junior work. Pi supports GPT-5.6 through
`max`, not `ultra`.

## The gate (this is the important rule)

- **Native Claude subagents (Sonnet) via the Task tool: dispatch freely.** That's normal
  Claude Code fan-out — no permission needed.
- **The named Pi models above (GPT-5.6 at the listed efforts, glm-5.2, minimax-m3, qwen3.7-max, NeuralWatt, and Ollama Cloud)
  are standing pre-authorized** — dispatch without a per-task confirm (still log every run).
- **The named AGY free lane (`agy-gemini-3.5-flash-free`) is also standing
  pre-authorized**, but this skill does not invoke it; use `ralph -t agy` for
  direct loops or let Conductor dispatch the roster row.
- **Any *other* non-Anthropic model: CONFIRM with the user first.** Propose the offload — "I'll
  hand task X to <model>, ok?" — and wait for a yes before dispatching. Don't silently ship work
  to an unvetted external provider. (Leaving `pi`/`orchestra` un-allowlisted means a Bash prompt
  is a backstop, but the proposal is the real gate.)

## How to dispatch

- **Claude Code:** hand the task to the **`pi-dispatch` subagent** (Task tool) — a thin wrapper subagent
  that runs `pi` and relays the result; parallelize N of them in an ultracode workflow. Or shell
  `pi` directly.
- **Direct invocation (any harness):** `pi-liveness --model <dispatch-id> --thinking <effort> --approve -p '<task>' < /dev/null`
  for real work or a text deliverable that may wait. Its safe progress records show only child activity; a heartbeat is not provider health and never authorizes a retry or cancellation. Add
  `--no-tools` (and drop `--approve`) for read-only analysis. Raw `pi` remains valid for short probes.
- **Schema-validated result:** use the orchestra driver — `bun run ~/.local/lib/orchestra/cli.ts`
  or `agentWithSchema` — not a raw `pi -p`.

## Keep score

After a non-default model does real work, append one line to the **Experience Log** in the
scorecard: `YYYY-MM-DD — <model> — <task> — quality N/5, reliability {committed?/scope?} — what
worked / where it fell flat`. Move a roster rating only when the log shows real evidence. This is
what makes routing improve over time — including for native Claude subagents, not just the pi models.
