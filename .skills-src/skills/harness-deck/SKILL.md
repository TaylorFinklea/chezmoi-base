---
name: "harness-deck"
description: "Use to publish a harness-deck/hdeck report — summarize major work (feature/refactor/audit/investigation) or a multi-session roadmap as a durable dashboard record, or pose an interactive ask/decision/approval question too rich for a native inline picker: a mock-up to react to, a paragraph per option, more explanation than option labels hold, or an answer that must survive a context clear. Reports can render arbitrary HTML/CSS/SVG via the `html` block, so reach for harness-deck when you want a custom layout, rendered mock-up, or inline visual that plain markdown can't express. NOT for short, self-explanatory select/multi-select choices — those belong in the harness's native inline picker, not a report."
---

# Publishing to harness-deck

harness-deck is the user's local dashboard for AI coding work. It reads
`report.json` manifests from agents (one per "run") and renders them into a
unified themed view, plus a per-project current-state + roadmap view. When a
manifest includes interactive blocks (`ask`, `decision`, `approval`), the
dashboard records the user's answer in a `responses.json` next to the report
— so an agent can ask a question that survives across sessions.

The full schema is the source of truth in `CONTRACT.md`, which the binary
embeds: run `harness-deck contract` (or `hdeck contract`) to print it, or read
the MCP `harness-deck://contract` resource — no repo clone needed. Read it for
anything beyond the basics here.

## When to publish a report

harness-deck does two jobs — don't conflate either with routine chat.

**Route a question by how much context the options carry, not by whether it's a
question.** Short, self-explanatory options → ask in the harness's native
inline picker (it's faster and blocks for an answer now). An option that needs
a paragraph, a code block, a side-by-side, or a rendered mock-up → publish.

**1. Publish a report to leave a durable record** when the agent would
otherwise:

- **Summarize major work** at the end of a multi-step task — a feature,
  refactor, audit, investigation. The dashboard becomes the durable record.
- **Capture a multi-session plan** — set `kind: "roadmap"` to surface in the
  dedicated projects/roadmap view.

**2. Ask a rich question** with an `ask` (choice / yes-no / free-text),
`decision` (A/B — records the chosen side), or `approval` (approve /
request-changes) block — paired with `prose` (fenced code = a text mock-up),
`html` (a rendered mock-up), `compare` (A/B), `diff`, or `table` to carry what a
picker can't. Reach for it when:

- you're presenting a mock-up / rendered layout to react to,
- each option carries enough text to run off the screen,
- the choice needs more explanation than native option labels + descriptions fit,
- or the answer must survive a context clear / be answered async — it lands in a
  sibling `responses.json` and outlives this session.

**Don't** publish for a generic select / multi-select with short,
self-explanatory options — that's faster and clearer in the native picker.

Skip publication for trivial work (one-line fixes, exploratory reads). The
dashboard is for things worth keeping in front of the user.

## Where to write the file

Either location works; pick one per run and stick with it:

- **Central (default):** `~/.harness/reports/<project>/<run>/report.json`
- **Per-project:** `<project-root>/.harness/<run>/report.json`

`<project>` groups runs in the dashboard and should match the user's repo
name (`harness-deck`, `larkline`, …). `<run>` is any stable id —
timestamp slug, short hash, RFC4122 UUID, agent-chosen tag.

The directory may also hold artifacts; harness-deck writes
`responses.json` here when the user answers an interactive block.

## Minimum-viable report

```json
{
  "schema":  "harness-deck/report@1",
  "id":      "20260523-cleanup",
  "project": "larkline",
  "harness": "claude-code",
  "title":   "drop legacy auth shim",
  "status":  "done",
  "created": "2026-05-23T14:02:00Z",
  "blocks": [
    { "type": "prose", "markdown": "Removed the legacy bearer-token shim..." }
  ]
}
```

Mandatory: `schema`, `id`, `project`, `harness`, `title`, `status`,
`created`, `blocks`. Everything else (`agent`, `scope`, `kind`, `verdict`,
`meta`) is optional — see `CONTRACT.md` for the full set.

## Self-identify

Set `harness:` to one of:

- `claude-code` — Claude Code
- `codex` — OpenAI Codex CLI
- `opencode` — OpenCode
- `pi-mono` — Pi Mono
- `agent` — anything else

The dashboard groups and labels runs by harness.

## Status lifecycle

- `draft` — work in progress; the agent may overwrite the file
- `awaiting-review` — there's an interactive block (or a verdict)
  waiting for the user; the dashboard's inbox surfaces these
- `answered` — the user has responded; pick up `responses.json` and act
- `done` — terminal state

Update status by rewriting `report.json` with the new value.

## Content blocks (summary)

| type | purpose |
|---|---|
| `prose` | Markdown text panel |
| `metrics` | metric grid + optional sparklines / bars |
| `risks` | severity register |
| `diff` | code diffs |
| `timeline` | event log |
| `compare` | A/B comparison |
| `recommendations` | numbered actions |
| `callout` | info / warn / err aside |
| `barchart` | labeled bars |
| `table` | columnar data |
| `ask` / `decision` / `approval` | interactive — user answers in dashboard |
| `html` | raw HTML/CSS/SVG canvas — full control inside panel chrome |

`CONTRACT.md` has the per-block field tables.

### The `html` block — your full-control canvas

This is harness-deck's main advantage over plain-text or markdown reporting.
When markdown and the typed blocks above can't express what you need — a custom
layout, a rendered UI mock-up to react to, an inline `<svg>` chart or diagram, a
richer side-by-side than `compare` gives you — emit an `html` block. Its single
`html` field is rendered **verbatim** as the contents of an isolated shadow root
inside the themed panel, so you have arbitrary HTML, inline `<style>`, and
`<svg>` at your disposal.

```json
{ "type": "html", "html": "<div style=\"display:grid;grid-template-columns:1fr 1fr;gap:12px\"><div>…</div><svg viewBox=\"0 0 100 40\">…</svg></div>" }
```

Because the block is isolated, you can style it freely:

- **Your `<style>`/selectors stay inside the block** — bare selectors
  (`div { … }`) and inline `style="…"` are both safe; nothing leaks to the
  dashboard and the page's CSS won't bleed into your markup.
- **`<script>` does not run** — html blocks are for layout/visuals, not
  interactive widgets.
- **Use the Tokyo Night theme variables** for colors that adapt to light/dark
  instead of hardcoding hex — they inherit into the block: `--tn-bg`,
  `--tn-bg-highlight`, `--tn-fg`, `--tn-fg-dark`, `--tn-comment`, `--tn-blue`,
  `--tn-cyan`, `--tn-purple`, `--tn-green`, `--tn-yellow`, `--tn-orange`,
  `--tn-red`, `--tn-rule` (hairline), and semantic `--tn-ok/warn/err/info`.
  Images/SVG/tables are capped to panel width (block scrolls if wider), so a
  wide layout won't break the page.

Prefer a typed block when one fits a *recurring* shape — it restyles
automatically when the renderer changes and keeps every report consistent. Reach
for `html` freely for *one-off* rich content a typed block doesn't cover; if you
find yourself emitting the same `html` structure across many reports, that's the
signal to ask for a real typed block instead.

## Interactive blocks — full round-trip

When you include an `ask`, `decision`, or `approval` block, give it a stable
`id` and ship the report with `status: "awaiting-review"`. The user answers
in their dashboard; harness-deck writes/updates `responses.json` next to
the report:

```json
{
  "responses": {
    "<block-id>": {
      "value": "...",
      "note":  "optional user comment",
      "at":    "RFC3339"
    }
  }
}
```

To pick up the answer: poll `responses.json` (or wait for the user to tell
you), read the `value` for your block-id, then proceed. Once acted on,
update the report to `status: "answered"` and (when work is complete)
`status: "done"`.

## Validate before publishing

```bash
hdeck validate path/to/report.json
```

`ok — N block(s), no problems` means safe to publish. Fix errors before
writing the file; harness-deck's validator catches schema mistakes the
renderer would otherwise show as fallback panels.

## Live dashboard

The user typically has `hdeck serve` running at <http://127.0.0.1:7420>
(default). New and changed reports appear within ~2s via SSE — no need to
poke the server after writing the file.
