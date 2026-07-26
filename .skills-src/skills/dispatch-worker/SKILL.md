---
name: dispatch-worker
description: "Use after delegate selects an approved worker profile, when executing one bounded task while the current session remains orchestrator. Chooses native subagents, OMP, Pi compatibility, or schema-validated orchestra execution. Not for Guildhall/Undertake fleet sessions or Ralph loops."
---

# Dispatch one worker task

The current session keeps decomposition, ambiguity, adjudication, and final
verification. This skill executes one bounded task using a worker profile that
has already passed the `delegate` eligibility, authorization, data-policy, and
routing checks.

Do not use this skill to choose a model. Musterroll is operational roster truth;
`delegate` owns retain-versus-dispatch and profile selection. An enabled profile
does not prove credentials, reachability, or live quota.

For queued, scheduled, multi-repository, provider-fallback, or native Undertake
work, use `guildhall-orchestration`. For phase loops, use `loops`. When an
external driver must orchestrate rather than merely execute one task, use
`fallback-orchestration`.

## Execution order

Use the first mechanism that can reach the already-approved profile. Do not
silently substitute a different provider or profile.

1. **Native harness subagent.** Prefer the harness's native task/subagent tool
   when it can address the selected profile. Give it one complete target,
   change, and acceptance contract. The orchestrator reviews the result.
2. **OMP one-shot.** Preferred generic external worker path:
   `omp --model <dispatch-id> --thinking <effort> --auto-approve --no-session -p '<task>' < /dev/null`.
   Keep stdin closed and the run sessionless. The prompt must identify the repo,
   exact scope, exclusions, and verification evidence to return.
3. **Pi compatibility/provider path.** Use
   `pi-liveness --model <dispatch-id> --thinking <effort> --approve -p '<task>' < /dev/null`
   when the approved profile is reachable through Pi or OMP is unavailable. For
   read-only analysis, add `--no-tools` and omit `--approve`. Raw `pi` is only a
   short-probe option. A heartbeat proves child activity, not provider health;
   it never authorizes retry, cancellation, or fallback.
4. **Schema-validated result.** Use `bun run ~/.local/lib/orchestra/cli.ts` or
   `agentWithSchema` instead of a raw one-shot command whenever the result must
   satisfy a schema.

## Worker contract

Every dispatch must state:

- the exact files, symbols, or artifact to inspect or modify;
- the requested change and explicit non-goals;
- observable acceptance criteria and the evidence to return;
- that the worker must skip project-wide formatting, lint, and test suites when
  the orchestrator will run them once after all work lands;
- the selected profile and author provenance for later review.

The worker does not broaden scope, select another model, retry a provider, or
adjudicate its own result. The orchestrator verifies claimed edits and evidence.

## Failure handling

- If a mechanism cannot reach the selected profile, use the next mechanism only
  when it reaches that same approved profile. Otherwise return the blocker.
- Report authentication, quota, timeout, and provider errors exactly as
  observed. Never infer quota state or silently switch providers.
- Reject scope-drifted, unverifiable, or incomplete output; do not relabel it as
  success.
- Never turn this one-shot procedure into a queue, autonomous retry loop, or
  fallback chain.

## Evidence and provenance

Record the author profile with the returned artifact. Prefer the Undertake /
Afterfact interaction path when it exists for this dispatch. Until shared policy
retires the interim Experience Log, record the one-line evidence required by
AGENTS.md; never use that legacy log as routing truth or mutate Musterroll from a
single result.
