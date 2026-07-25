---
name: slash
description: Save the last assistant message verbatim to ~/.claude/saved/<project>/ and the clipboard, then prompt the user to run /clear. User-invoked only.
user-invocable: true
disable-model-invocation: true
hide: true
---

# slash

Capture the most recent substantial assistant message — verbatim — to a file and the clipboard, so a specific nugget survives a context clear. Then remind the user to run `/clear`.

Runs only when the user types `/slash`. Never auto-triggers.

## Why this exists

Cross-session handoff lives in `.docs/ai/` and usually captures everything needed for continuity. Occasionally the *last message itself* — a session summary, an insight, a generated snippet — holds something specific worth keeping verbatim before context is cleared. This skill grabs it.

A skill cannot clear context itself. This skill does the save; the user runs `/clear` afterward.

## Usage

`/slash` — save the last assistant message; title is auto-derived
`/slash <title>` — save it under a title you provide (also used for the filename)

## What to do

### 1. Find the message to save

Save the **most recent substantial assistant message** in this conversation — normally the message right before this `/slash` invocation (a session summary or wrap-up).

If the immediately preceding assistant turn is trivial — a bare "You're welcome", "Done", or a one-line acknowledgement — walk back to the last substantial assistant message instead.

If there is no prior assistant message at all, tell the user there is nothing to save and stop.

### 2. Resolve the destination

- **Project**: run `git rev-parse --show-toplevel 2>/dev/null`. If it prints a path, the project is that path's basename. If it prints nothing (not a git repo), the project is the basename of the current working directory.
- **Timestamp**: run `date +%Y-%m-%d-%H%M` (e.g. `2026-05-21-1430`).
- **Title and slug**:
  - If the user passed text after `/slash`, that text is the title. Lowercase and kebab-case it for the slug.
  - Otherwise derive a short 3–6 word title from the message content, and a kebab-case slug from that title.
- **File path**: `~/.claude/saved/<project>/<timestamp>-<slug>.md` — expand `~` to the absolute home directory for any tool call that needs an absolute path.

### 3. Write the file

Create the directory:

```bash
mkdir -p "$HOME/.claude/saved/<project>"
```

Then write the file with the Write tool, using the absolute path. Structure:

```markdown
# <Title>

- **Saved:** <YYYY-MM-DD HH:MM>
- **Project:** <project>
- **Source:** Claude Code session

---

<the assistant message, reproduced verbatim>
```

**Verbatim means verbatim.** Reproduce the message exactly — every character, code block, list, heading, and line break as written. Do not summarize, paraphrase, reformat, fix typos, or trim. The point is a lossless capture.

### 4. Copy to the clipboard

```bash
pbcopy < "<absolute file path>"
```

This puts the full saved file on the clipboard, ready to paste into the fresh conversation after clearing.

### 5. Report and prompt

Print a short confirmation — the file path, that it is also on the clipboard, and a reminder to run `/clear`:

```
Saved → ~/.claude/saved/<project>/<timestamp>-<slug>.md
Also on the clipboard.
Run /clear now to clear context.
```

## Notes

- `~/.claude/saved/` is runtime data — created on demand, not chezmoi-managed, not committed anywhere.
- macOS only: step 4 uses `pbcopy`.
- This skill cannot run `/clear` itself. The final step is always the user's keystroke.
