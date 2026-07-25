---
name: fallback-orchestration
description: "Use when running multi-agent or schema-validated orchestration on non-Opus models — especially when Anthropic/Opus is rate-limited — via the direct opencode-go provider (Kimi K2.7 Code, MiniMax M3) and the local `orchestra` driver. Covers the deterministic agentWithSchema/parallel/Budget primitives, per-harness invocation (Claude Code, Pi, OpenCode, Codex), and the hard-won gotchas (stdin/TTY hang, <think>-strip for MiniMax, opencode-go is a direct provider)."
---

# Fallback orchestration (non-Opus, opencode-go)

Deterministic orchestration for when Anthropic/Opus is rate-limited (or just for cheap fan-out): the **driver owns the guarantees**, harnesses are dumb headless-JSON workers. Models reach you through the **direct `opencode-go` provider** — a static `api_key` in `~/.pi/agent/auth.json`, **no proxy** (the old LiteLLM/bytesaddle proxy at `localhost:4000` is retired; don't chase it).

For Guildhall/Conductor fleet sessions, queue dispatch, cycle approval, or
provider fallback across the backlog, use `guildhall-orchestration`. This skill
is the lower-level `orchestra` driver reference.

## The #1 gotcha: close stdin when shelling a TUI CLI

`pi` (and any terminal-UI CLI) **hangs at 0 bytes** when run from an agent's non-interactive Bash — it blocks on a terminal-capability query reading a stdin that never answers. **Always redirect stdin from `/dev/null`:**

```sh
pi --model opencode-go/minimax-m3 --approve -p 'say ok' < /dev/null
```

Harness-agnostic — Claude Code / Codex / OpenCode / Pi all hit it when they shell `pi`. It once cost a full debugging session misattributed to a "wedged endpoint." The `orchestra` driver already spawns `pi` with stdin closed; this rule is for ad-hoc shell calls.

## The driver

`~/.local/lib/orchestra/` (chezmoi source: `private_dot_local/lib/orchestra/`), run with `bun`:

- `agentWithSchema(prompt, {schema, model})` → **validated** object (reason-then-emit contract → validate → repair-retry ≤2). The keystone — converts "model must format correctly" into "engine guarantees the shape."
- `parallel(thunks, {concurrency})` → throttled fan-out barrier; failed thunk → `null`. Keep concurrency low (opencode-go dislikes bursts).
- `Budget` → one global tokens/$/spawn ledger with a hard abort.
- `piAdapter` spawns `pi --mode json -p --no-session --model X` (stdin closed) and parses the assistant reply from the `message_end` event.

Verify / measure:

```sh
bun run ~/.local/lib/orchestra/selftest.ts            # 45 offline tests (no endpoint)
bun run ~/.local/lib/orchestra/selftest.ts --live 5   # 5-trial convergence per model
```

**`extractJson` strips `<think>…</think>` before parsing** — load-bearing for MiniMax M3, which interleaves reasoning that otherwise corrupts the JSON. Don't remove it.

## Workloads built on the driver — `orchestra verify` / `audit`

`verifyClaim` (driver) + the `orchestra` CLI run a deterministic **evidence command** as the oracle (the model judges its output/exit code, never produces it), then a non-Opus model returns a structured verdict. **Fail-closed**: no valid verdict, or a `pass` below the confidence floor, becomes `fail`.

```sh
orchestra verify "<claim>" --evidence "<cmd>" [--model M] [--context "<diff>"] [--min-confidence N]
orchestra audit  --before <sha> --after <sha> [--model M] [--repo D] [--state PATH]
```

- **`audit`** is the ralph post-iteration hook: between two commits it finds the Plan checkboxes that flipped `[ ]`→`[x]`, runs each item's inline `Verify:`, and judges whether the code diff (handoff docs excluded) implements it. The diff reaches the judge as **untrusted data** — an audited commit can't coerce a `pass` via embedded text.
- **`ralph -a`** (opt-in, default off) audits each iteration and **stops the loop** on a failed audit. Verifier = `ORCHESTRA_AUDIT_MODEL` (default `opencode-go/kimi-k2.7-code`, decoupled from `-t`); pass floor = `ORCHESTRA_AUDIT_MIN_CONFIDENCE` (default 0.6, `0` disables).

## Model routing (opencode-go)

- **`minimax-m3`** — pi's default; 100% first-try structured-valid via the driver (after the `<think>`-strip).
- **`kimi-k2.7-code`** — the alternate; also 100% first-try; best tool-call stability, so a good worker.
- Both are fine for worker / verifier / structured roles. Reserve a strong model (GPT-5.6 Terra / Sonnet / Opus) for the irreducible roles (decomposition, final judgment) — but those share the rate-limit ceiling you're routing around. When BOTH Anthropic and OpenAI are throttled, the **both-throttled policy is `routeBoundary()`** (driver): `decompose` → **hard-stop** (a weak model's plan has no Verify oracle to catch it), `judge`/`synth` → **degrade** to `opencode-go/deepseek-v4-pro` (1M ctx, `ORCHESTRA_BOUNDARY_FALLBACK` overrides), flagged review-required. Throttle state must come from a real 429/quota error, **never a model's say-so**. **opencode-go only — no openrouter.**

## Per-harness — what each needs to be successful

- **Claude Code (usual driver).** Drive the loop here: call the driver via `bun`, or shell `pi` directly **with `< /dev/null`**. Structured output comes from the driver, never assumed raw from the model.
- **Pi (usual worker / headless).** `ralph -t pi` defaults to the friendly `glm` alias (`opencode-go/glm-5.2`); set `RALPH_PI_MODEL=sol|terra|luna|minimax|qwen|nw-glm|ollama-glm|provider/id` to pin another roster lane. Pi has **no native schema forcing** (maintainer rejected it) — structured output is the driver's `agentWithSchema`, full stop.
- **OpenCode (alternate, smoke-test).** `opencode run --format json` (the CLI has no schema flag). Native `format:{json_schema}` exists in the SDK/server (issue #10456) but its retry is reportedly broken (#25430), so the driver still validates. OpenCode can use the configured custom provider lanes, including `ollama-cloud/glm-5.2`, `ollama-cloud/kimi-k2.6`, and `ollama-cloud/minimax-m3`; prefer Conductor roster fallbacks for fleet dispatch rather than hardcoding provider policy in prompts.
- **Codex (alternate, smoke-test).** `codex exec --json`; `--output-schema` exists but is reportedly ignored when tools/MCP are active (#15451) → driver validates.

## ralph loop gates (mechanical, not prompt-trusted)

`ralph` refuses to loop on any unchecked Plan item tagged `tier_floor: lead` (decomposition is irreducible-Opus; `-L` overrides) and never expands an empty Plan (roadmap→Plan expansion is a Lead/interactive step). A non-Opus fallback runs **pre-decomposed, Verify-gated execution only** — it does not redesign the loop.
