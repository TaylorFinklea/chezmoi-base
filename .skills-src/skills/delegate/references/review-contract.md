# Adversarial review — output contract

Charge to give every reviewer, verbatim: "Attempt to REFUTE. No praise, no
padding. If a decision survives your attack, say so in one line and move
on."

Required output shape:

1. Numbered findings, most severe first. Each finding:
   `[SEVERITY: high/med/low]` one-line claim → 2–4 sentences of concrete
   evidence or reasoning → a specific fix.
2. A final verdict line: ship / ship-with-changes / rethink.

Rules:

- Independent first pass — a reviewer never sees another reviewer's output
  before writing its own.
- Reviewers get a SELF-CONTAINED brief (they cannot see your
  conversation): context, the artifact under review, the existing assets
  that must not be duplicated, and the charge above.
- The orchestrator adjudicates. Separate "is the finding true?" from "does
  the fix belong in this artifact?" — true findings with out-of-layer fixes
  get routed to the right repo/backlog, never absorbed into the artifact.
- Disagreement between reviewers is signal, not noise — name it in the
  adjudication.
- Log each reviewer dispatch: Experience Log line + `model-bench.jsonl`
  row, per the scorecard's own instructions.
