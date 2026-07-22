---
name: handoff-prompt
description: Generate a self-contained prompt to hand off backlog work to another AI agent (cheaper model, different harness, or web UI). Reads roadmap state, picks items, and produces a copy-pasteable prompt with all context inline.
user-invocable: true
disable-model-invocation: true
hide: true
---

# Handoff Prompt Generator

Generate a self-contained prompt for handing backlog work to another AI agent — a cheaper model (Sonnet, Haiku, GPT, Kimi), a different harness (Codex, Opencode, Copilot), or a web UI (claude.ai, chatgpt.com). Useful when rate-limited or when you want a different tool to work the queue while you context-switch.

## Usage

`/handoff-prompt` — pick up to 4 unchecked backlog items
`/handoff-prompt 3` — limit to N items
`/handoff-prompt <keyword>` — only items mentioning the keyword in their entry

## What to do

1. **Read the roadmap** at `.docs/ai/roadmap.md`. If the repo points to a different roadmap path in its `AGENTS.md` or `CLAUDE.md`, use that.

2. **Identify unchecked backlog items** — `- [ ]` items in the `## Backlog` section. Skip items with `<!-- failed YYYY-MM-DD -->` markers unless the user says otherwise.

3. **Check recent git history** — `git log --oneline -10`. If commits suggest items were completed but not marked `[x]`, note them.

4. **Select items** based on the argument:
   - Default: up to 4 items, lower `tier_floor` first (junior/senior before lead)
   - Number: limit to that many
   - Keyword: only items whose entry contains the keyword

5. **For each item**, read the referenced files to verify paths still exist and capture the surrounding code style.

6. **Generate the prompt** using this structure:

```
You are working on [project name] — [one-line description].

## Repo
[absolute path to repo]

## Rules
- Read files before editing them.
- Make one commit per item. Do not push.
- Don't change anything beyond what the item describes.
- Don't add comments, docstrings, or type annotations to code you didn't change.
- Run one shell command at a time. Don't chain with &&.
- Stop and report if you get stuck — don't guess.

## Verify changes with
[build/test command from AGENTS.md or repo conventions]

## Items (work in order; stop if stuck)

### 1. [item title]
[full backlog entry inlined: scope, files, acceptance, verify]
[any code context the agent will need — current content of relevant lines]
[suggested commit message]

### 2. ...

---

After completing items, report what you did and what (if anything) you couldn't finish.
```

7. **Output the prompt** as a fenced code block so the user can copy-paste it directly into another agent.

## Key principles

- **Self-contained**: the prompt must include ALL context. The receiving agent cannot read your CLAUDE.md, AGENTS.md, or roadmap — everything is inline.
- **Explicit file paths**: absolute paths or paths relative to the repo root.
- **Verify command**: always include the build/test command.
- **One commit per item**.
- **Stop on stuck**: tell the agent to stop and report rather than guess.

## Resume protocol

When you (or another agent) come back after a handoff:

1. `git log --oneline -10` to see what was committed.
2. Read the changed files to verify quality.
3. Run the build/test command.
4. Update the roadmap to mark completed items and note any issues.
5. Only then start new work.
