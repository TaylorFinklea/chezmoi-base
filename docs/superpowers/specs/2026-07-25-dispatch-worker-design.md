# Dispatch Worker Skill Design

## Decision

Replace `dispatch-to-pi` with `dispatch-worker`. Keep `delegate` as the policy layer that decides whether and where to delegate; make `dispatch-worker` the procedural layer that executes one bounded worker task while the current session remains orchestrator.

## Scope

- Rename the canonical base-owned skill and catalog entry.
- Prefer native harness subagents when available, then OMP for a generic one-shot external worker.
- Retain Pi via `pi-liveness` as an explicit compatibility/provider path.
- Retain `orchestra` for schema-validated output.
- Remove the static roster table and legacy scorecard-as-routing-source claims.
- Route eligibility and model selection through `delegate`, Musterroll, and the shared AGENTS policy.
- Replace active references in `delegate`, `guildhall-orchestration`, and `loops`.
- Retire the Claude-only `pi-dispatch` wrapper only if it is owned by this repository; otherwise update its owner in the same migration.
- Do not rewrite historical specs, plans, decisions, or experience records.

## Boundaries

`delegate` owns:

- retain-versus-dispatch decisions;
- tier, complexity, provider, and model-family selection;
- authorization and data-policy gates;
- reviewer-panel shape.

`dispatch-worker` owns:

- selecting the reachable execution mechanism for an already-approved worker profile;
- invoking native subagents, OMP, Pi, or `orchestra` correctly;
- preserving closed-stdin and bounded one-shot behavior;
- returning the worker output and verification evidence;
- recording provenance through Afterfact when available, with the existing interim Experience Log only where shared policy still requires it.

`guildhall-orchestration` continues to own queued, scheduled, multi-repository, and Undertake work. `loops` continues to own Ralph phase loops. `fallback-orchestration` continues to own cases where the external driver is the orchestrator.

## Execution Order

1. Native harness subagent when it can reach the selected profile.
2. OMP one-shot for generic external worker execution: `omp --model <dispatch-id> --thinking <effort> --auto-approve --no-session -p '<task>' < /dev/null`.
3. Pi compatibility/provider path: `pi-liveness --model <dispatch-id> --thinking <effort> --approve -p '<task>' < /dev/null`; use `--no-tools` without `--approve` for read-only analysis.
4. `orchestra` instead of raw one-shot dispatch when the result must satisfy a schema.

A harness or provider being listed does not establish eligibility, credentials, or live quota. The orchestrator must complete `delegate` eligibility checks first. A heartbeat proves only child activity and never authorizes retry, cancellation, or provider fallback.

## Failure Handling

- Unreachable selected mechanism: use the next eligible mechanism only when it reaches the same approved profile; otherwise return the concrete blocker.
- Authentication or quota failure: report observed evidence; do not infer or silently change providers.
- Worker scope drift or unverifiable output: reject the result and retain adjudication in the orchestrator.
- Never turn one-shot dispatch into a queue or autonomous retry loop.

## Verification

- Catalog and lock contain `dispatch-worker` and no `dispatch-to-pi`.
- Active skill bodies contain no procedural dependency on `dispatch-to-pi` or the retired wrapper.
- Skill composition passes for personal and work roles.
- OMP worker test proves the documented invocation contract.
- Public-safety scanner passes because the base repository is public.
- Both role preflights pass; no HOME apply occurs.
