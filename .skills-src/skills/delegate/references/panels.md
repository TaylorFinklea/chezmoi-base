# Panels — family map, presets, reachability

## Model-family map (developer lineage — NOT inference provider)

A family is who trained the model. The same base model on different
providers is ONE family: `opencode-go/glm-5.2`, `neuralwatt/glm-5.2*`, and
`ollama-cloud/glm-5.2` are all zhipu.

| Family | Models |
|---|---|
| anthropic | Fable, Opus, Sonnet, Haiku |
| openai | GPT-5.6 Sol / Terra / Luna, GPT-mini |
| zhipu | GLM-5.x (all lanes) |
| moonshot | Kimi K2.x, Kimi K3 (all lanes) |
| minimax | MiniMax M3 (all lanes) |
| alibaba | Qwen 3.x max / plus |
| google | Gemini (AI Studio, AGY) |
| deepseek | DeepSeek v4 |
| xiaomi | MiMo |

## Presets (criteria, not member lists — resolve against the live roster)

- **adversarial-review** — reviewer(s): tier = lead (per
  scorecard/Musterroll), family ≠ the artifact AUTHOR's family, reachable from this harness. The
  author is the model that wrote the artifact — if implementation was
  delegated, that delegate, not you. When Anthropic differs from that author,
  prefer eligible/reachable Claude Opus 5 at max; use the Opus 4.8 fallback
  when Opus 5 is unavailable. Default 1 reviewer; 2–3 from distinct families
  for XL / architecture decisions. Output per `review-contract.md`; the
  orchestrator adjudicates.
- **author provenance** — record the author model on every delegated
  artifact (the Experience Log line suffices). Provenance missing → never
  silently weaken the family rule: use two reviewers from two families, or
  ask the user.
- **load spread** — when dispatching several parallel tasks, prefer
  distinct quota lanes among eligible models. Ordering and fallback chains
  stay owned by the scorecard / Musterroll / Undertake.

## Reachability

| From | Cross-family Lead reviewer routes |
|---|---|
| Claude Code | Claude Opus 5 is same-family, so use GPT-5.6 Sol / Terra (codex CLI or pi `openai-codex/*`); kimi-k3, qwen3.7-max via pi |
| Codex / Pi / OMP | Prefer Claude Opus 5 through its max-effort OMP profile when Musterroll reports it eligible and the harness confirms credentials; use the Opus 4.8 fallback. Headless `claude -p` remains unreliable (scorecard 2026-07-11/12), so do not treat it as the route. |

Live tier / ceiling / dispatch IDs: `musterroll roster snapshot --json` →
fallback read `~/git/musterroll/roster.toml` → else the
AGENTS.md pre-authorized list, fail closed. Role-strength evidence:
`~/.claude/model-scorecard.md` (Live Roster + Experience Log) — not here.

Sunset: this file migrates into Musterroll/Afterfact (`bursar-97a` lineage
field, `hindsight-fxm` staleness gate). Review 2026-10-01 or on Afterfact
parity, whichever first — then delete this file.
