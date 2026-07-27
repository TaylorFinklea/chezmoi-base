# Decisions

> Architecture decision records. Append-only — one entry per decision.

## [2026-07-27] `c` shortcut routes to Claude Code; codex moves to `cx`

**Context**: `c` had aliased to `codex` in both `dot_zshrc` and
`dot_config/fish/config.fish`. Claude Code became the primary daily harness, so
the shortest shortcut pointed at the less-used tool.

**Decision**: `c` = `claude --model opus --effort ultracode --permission-mode auto`;
`cx` = `codex`. Mirrored in zsh and fish. `ccr` (resume) left unchanged.

**Alternatives considered**: bare `claude` (rejected — loses the model/effort
defaults the user wants by default); dropping the codex alias entirely
(rejected — codex is still in active use); `co` for codex (rejected in favor of
`cx`, no collision with the `cz*`/`ccr` family).

**Rationale**: Lowest-friction shortcut should point at the most-used harness.

**Landmine**: `--effort ultracode` is **not** listed by `claude --help`, which
advertises only `low|medium|high|xhigh|max`. It is nonetheless a valid *gated*
value — the CLI decodes it to `{value: "xhigh", ultracode: true}`, i.e. xhigh
effort plus the multi-agent workflow opt-in. Verified end-to-end before
committing. Do not "fix" this to `xhigh` on the assumption it is a typo; on a
build or account without the gate it degrades rather than erroring.

## [2026-07-27] Only the two security skills cross from codex-only to `native`

**Context**: 13 skills in the chezmoi-personal catalog were `targets = ["codex"]`,
plus 3 on disk in no catalog. Question was which should also serve Claude Code.

**Decision**: Add `native` to `security-best-practices` and
`security-threat-model` only (chezmoi-personal `5a89ea2`). All others stay
codex-only.

**Rationale**: Both are harness-neutral — generic language/framework security
review and repo-grounded threat modeling, with no OpenAI-specific mechanics —
and Claude Code has no built-in equivalent. Their descriptions carry explicit
"Trigger only when…" guards, so `activation = "automatic"` won't fire them on
ordinary code review.

**Skip rationale** (recorded so it isn't re-litigated):
- *Not portable* — OpenAI-product skills: `sora`, `speech`, `imagegen`,
  `transcribe`, `openai-docs`, `chatgpt-apps`.
- *Redundant with a Claude built-in* — `screenshot`/`playwright` (claude-in-chrome
  + the chrome-devtools MCP), `pdf` (Read handles PDFs natively),
  `jupyter-notebook` (NotebookEdit), `frontend-skill` (frontend-design plugin).
- *Undecided, low value so far* — `doc`, `cloudflare-deploy`, `figma`.

**Caveat**: `security-best-practices` partially overlaps the `/security-review`
command; revisit if it proves redundant in practice.

## [2026-07-27] `.docs/ai/` seeded here; `current-state.md` overrides its template

**Context**: `chezmoi-base` is the stated front door for all dotfile work but
had no handoff docs, so cross-session state had nowhere to land.

**Decision**: Seed `.docs/ai/` from `~/.claude/templates/handoff/`, but write
`current-state.md` in the loop-state shape AGENTS.md mandates (≤20 lines;
Branch / Plan / Blockers / Open questions) rather than the template's verbose
"Last Session Summary / Build Status" layout.

**Rationale**: AGENTS.md is canonical and its Session End routing table forbids
journal prose in `current-state.md`. The shipped template predates that rule.

**Follow-up**: `~/.claude/templates/handoff/current-state.md` is stale and will
keep seeding the wrong shape into every new repo — see roadmap Now.
