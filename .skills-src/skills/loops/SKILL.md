---
name: loops
description: Use when running direct Ralph phase loops over one repo's `.docs/ai/current-state.md` Plan and deciding where that simple loop runs. Not for Guildhall/Conductor cycle dispatch, beads fleet orchestration, provider fallback, or Arena comparisons.
---

# Loop strategy — where simple Ralph phase loops run

Use this for plain `ralph` loops over one repo's `.docs/ai/current-state.md`
Plan. If the request mentions Guildhall, Conductor cycle/dispatch, provider
fallback, fleet queues, or beads orchestration, use `guildhall-orchestration`
instead. If it asks to compare harness/model candidates on the same bead, use
`conductor-arena`.

Route a simple loop by **who orchestrates** and **which model does the work**.
Rule of thumb: **if it's a Claude model and you're already in Claude Code, keep
it in-session; everything else loops through `ralph`.**

## Inside a Claude Code session (the usual case)

- **Claude-model work stays IN-SESSION.** Loop / fan-out with native **Sonnet subagents**
  (Task tool) or a **dynamic Workflow** (`agent(…, {model: 'sonnet'})`). Sonnet is the default
  worker; reserve Opus for the hardest lead work. You (the orchestrator) keep planning,
  verifying, and committing.
  - **Do NOT `ralph -t claude` from inside Claude Code** — it spawns a second Claude on top of
    this one. Loop in-session instead.
- **External headless loops → `ralph`:**
  - `RALPH_CODEX_MODEL=sol|terra|luna ralph -t codex` — direct Codex routing.
    Sol defaults to `max`; Terra defaults to `xhigh`; Luna defaults to `medium`
    (Junior), while Luna `high`/`xhigh`/`max` is Senior. Set
    `RALPH_CODEX_REASONING_EFFORT` to select an explicit effort. `ultra` is
    valid for Sol and Terra only — never Luna. `luna-high` and `luna-medium`
    choose the two Luna bands without separately setting effort.
  - `RALPH_OPENCODE_MODEL=sol|terra|luna ralph -t opencode` — maps GPT-5.6 to
    `openai/gpt-5.6-*`; OpenCode currently exposes variants only through
    `xhigh`, so Sol uses `xhigh` there rather than its Codex/Pi `max` default.
    `luna-medium` is Junior and `luna-high` is Senior. Existing friendly names
    `glm|minimax|qwen` remain available with harness-specific
    provider IDs. NeuralWatt GLM shortcuts default to short/thinking
    (`nw-glm|nw-glm-short` → `glm-5.2-short`);
    choose fast/non-thinking explicitly (`nw-glm-fast|nw-glm-short-fast` →
    `glm-5.2-short-fast`) only for mechanical or latency-sensitive loop items with
    strong Verify gates. Ollama Cloud subscription aliases (`ollama-glm`,
    `ollama-kimi`, `ollama-minimax`; shorter `oc-*` aliases also work) resolve to
    `ollama-cloud/glm-5.2`, `ollama-cloud/kimi-k2.6`, and
    `ollama-cloud/minimax-m3` as a distinct provider/quota lane.
    Local Ollama aliases (`local-gemma`, `local-qwen`, `local-qwen-27b`,
    `local-oss`; `ol-*` short forms also work) resolve to `ollama-local/<tag>` and
    run entirely on this machine — no key, no quota, no spend, nothing transmitted.
    Personal Mac only. Use them when every metered lane is rate-limited, when the
    repo is private enough that no cloud lane is acceptable, or for cheap fan-out
    where latency does not matter. They are slower than a cloud API call, and only
    one large local model can be resident at a time.
  - `RALPH_PI_MODEL=sol|terra|luna ralph -t pi` — maps GPT-5.6 to
    `openai-codex/gpt-5.6-*`. Pi defaults Sol to `max`, Terra to `xhigh`, and
    Luna to `medium`; use `RALPH_PI_THINKING=high` (or `luna-high`) for Senior
    Luna. Pi supports through `max`, not `ultra`. Existing `glm|
    minimax|qwen|nw-glm|nw-kimi|ollama-glm` aliases remain available. Use the
    short/thinking NeuralWatt default for normal implementation, review,
    debugging, security, migration, or ambiguous work; use fast/non-thinking
    only for rote docs sync, formatting, simple search/replace, deterministic
    checklist work, or runs protected by a verifier/auditor. Kimi has no short
    variant, so `nw-kimi|nw-kimi-fast` resolve to `kimi-k2.6-fast`; use the
    Ollama aliases when you want the subscription-backed lane; pass a full
    `provider/id` when you need a specific long-context or thinky variant.
  - `RALPH_AGY_MODEL='Gemini 3.5 Flash (High)' ralph -t agy` — Antigravity CLI
    via Google OAuth/subscription, defaulting to max-reasoning Flash. Use it as a
    limited free Junior/S loop lane; the `--add-dir "$PWD"` pin in `ralph` is
    load-bearing because AGY is project-scoped rather than cwd-scoped.
  - These are the standing-pre-authorized models (see `~/.claude/model-scorecard.md`) — no
    per-dispatch confirm; still log each run.

## Outside Claude Code (a shell, cron, another harness)

- Any ralph backend, **including Claude models headless**:
  `RALPH_CLAUDE_MODEL=sonnet ralph -t claude` (passed through as `claude -p --model sonnet`).
  This is the **only** context where ralph should drive a Claude model — from inside Claude
  Code, use in-session orchestration. Codex and OpenCode can likewise be pinned with
  `RALPH_CODEX_MODEL` + `RALPH_CODEX_REASONING_EFFORT` and `RALPH_OPENCODE_MODEL`; AGY can be pinned with
  `RALPH_AGY_MODEL`.

## ralph gates (all backends)

- Loops one unchecked `## Plan` item per iteration from `.docs/ai/current-state.md`, fresh
  context each (AGENTS.md "Phase loop").
- **Refuses** if any unchecked item lacks a `Verify:` command, or is tagged `tier_floor: lead`
  (decomposition doesn't loop headlessly — expand it interactively; `-L` overrides). `-a`
  audits each commit with the orchestra fallback verifier and stops on failure.
- Headless iterations never run `chezmoi apply` — applying to live HOME stays a human step.

For **one-shot** offload (not looping) and the live roster / dispatch IDs, see the
`dispatch-to-pi` skill and `~/.claude/model-scorecard.md`.
