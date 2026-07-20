# Codex Forge Plugin

Status: approved 2026-07-19
Owner: `chezmoi-base` (public; intentionally reaches personal and work machines)

## Problem

Pi's `/forge` turns a rough implementation request into an approved execution
contract before any writer starts. Codex has the same need, but it does not load
Pi extensions. A Codex skill alone can describe the workflow, yet it cannot
reliably prove user approval or block writer tools during shaping.

Codex now has stable skills, plugins, multi-agent support, and lifecycle hooks.
A native plugin can bundle the workflow and its guardrails without coupling
Forge to unrelated user-level Moshi, harness-deck, or Herdr hooks.

## Goals

- Provide a Codex `$forge` workflow on personal and work machines.
- Reconnoiter before asking questions.
- Ask at most three material questions by default and five under the hard cap.
- Prevent writer activity until an immutable Execution Brief is approved.
- Require user-originated, session-bound approval rather than trusting a model
  assertion.
- Dispatch approved work either in the current Codex session or through guarded
  `ralph -t codex` execution.
- Persist status and support resume, cancellation, and failure reporting.

## Non-goals

- Replacing Pi Forge or sharing Pi's TypeScript implementation.
- Providing an operating-system sandbox.
- Defending against a user who disables or declines to trust the plugin hooks.
- Treating Codex transcript files as a stable API.
- Adding Conductor dispatch in this version.
- Publishing the plugin to a remote marketplace.

## Packaging and deployment

Create a managed local Codex plugin named `codex-forge`. Its source and local
marketplace live under the public base stack and render into a generic managed
location beneath `~/.agents/plugins/`. The plugin contains:

- `.codex-plugin/plugin.json` — versioned plugin manifest;
- `skills/forge/SKILL.md` — `$forge` discovery and orchestration instructions;
- `hooks/hooks.json` — plugin-scoped lifecycle registration;
- a standard-library Python helper for state, validation, policy, and dispatch;
- tests and static JSON fixtures needed to validate the bundle.

The local marketplace identifier is `local-managed`; no personal or work
identifier enters the public repository. Personal and work Codex configuration enable the same `codex-forge` plugin
from the `local-managed` marketplace.
Their shared plugin stanza remains byte-equivalent under a parity test.

A managed, idempotent install/update step registers the local marketplace and
refreshes Codex's plugin cache without deleting unrelated marketplaces,
plugins, or app-generated configuration. New or changed command hooks still
require native Codex trust review. `$forge` refuses to start unless the current
plugin version has produced a session heartbeat.

This placement is intentional: base and work changes land on work machines.
The plugin and all bundled behavior must remain generic and public-safe.

## Components

### Forge skill

The skill owns the conversational workflow:

1. start a guarded Forge session;
2. inspect repository instructions, code, tests, and primary documentation;
3. ask only material unresolved decisions;
4. record reversible assumptions for lower-impact uncertainty;
5. submit a complete Execution Brief for validation and freezing;
6. present the exact nonce-bearing approval choices;
7. after approval, run direct Codex execution or guarded Ralph dispatch;
8. report verification and final status.

The skill must never claim hook protection when the helper reports no trusted
heartbeat. It must not implement or mutate repository files while state is
`shaping` or `frozen`.

### Lifecycle hooks

The plugin registers these hooks:

- `SessionStart` — write a versioned heartbeat and restore model-visible status
  for an active session;
- `PreToolUse` — enforce shaping/frozen tool policy and bind helper operations
  to the Codex session ID supplied by the hook event;
- `UserPromptSubmit` — validate nonce-bearing approve, revise, and cancel
  messages as user-originated state transitions;
- `PostToolUse` — record the exit status and bounded evidence for exact
  verification commands executed during direct dispatch;
- `Stop` — prevent silent abandonment of an executing session when required
  verification or owned-process cleanup remains outstanding.

Hooks use documented JSON input/output fields. They do not parse the unstable
transcript format. Subagents receive the parent session ID, so active shaping
policy applies to their local tool calls as well.

### Helper and state

The helper uses only the Python standard library and accepts explicit
subcommands. Hook-mediated calls receive the session ID from hook input rather
than trusting a model-provided identifier. Structured model input crosses the
Bash hook boundary as one size-bounded, unpadded base64url JSON argument; the
hook validates its alphabet and command grammar before injection, and the CLI
decodes then validates the complete JSON value. Pipes, heredocs, redirects,
and interactive `write_stdin` transport remain forbidden.

State lives in the plugin's writable data directory, not the repository. Each
record is bound to:

- schema and plugin version;
- Codex session ID;
- canonical working directory;
- Git repository identity and initial HEAD when applicable;
- current lifecycle state;
- question count and recorded decisions;
- frozen brief and its digest;
- single-use approval nonce and expiry;
- selected dispatcher;
- verification evidence;
- Ralph process-group ownership and status when applicable.

Lifecycle states are `shaping`, `frozen`, `approved_direct`, `approved_ralph`,
`executing`, `ralph_running`, `completed`, `cancelled`, and `failed`. Invalid or
unsupported transitions fail closed.

State directories are private. Writes require regular files, reject symlinks,
and use atomic replacement. A plugin-version change invalidates active state
instead of interpreting it under new rules.

## Shaping and approval flow

### Recon

After guarded state begins, Codex may use:

- read-classified shell commands;
- hosted web/documentation search;
- explicitly read-only MCP tools;
- read-only scout or research subagents;
- non-mutating planning/status tools.

It may not use file writers, mutating shell commands, unknown local tools,
write-capable MCP tools, or writer subagents.

### Questions

Candidate questions are ranked by impact times uncertainty. Ask only about
scope, user-visible behavior, public contracts, schemas, security/privacy,
irreversible architecture, or verification requirements that repository or
primary-source recon cannot answer.

The helper records each question attempt before it is asked. Three attempts are
the default budget. Attempts four and five require unresolved high-impact
ambiguity. A sixth attempt is rejected. Lower-impact uncertainty becomes an
explicit reversible assumption.

### Frozen Execution Brief

The versioned brief contains:

- goal;
- in-scope and out-of-scope work;
- approved decisions;
- acceptance criteria;
- relevant repository patterns;
- exact verification commands;
- reversible assumptions;
- decision envelope and escalation boundaries;
- optional independently verifiable phases;
- dispatcher recommendation.

Freezing validates the complete structure, stores an immutable digest, creates
a random single-use nonce, and moves state to `frozen`. No repository file is
written before approval.

The turn ends with exact choices:

```text
approve <nonce> direct
approve <nonce> ralph
revise <nonce>
cancel <nonce>
```

`UserPromptSubmit` accepts only a complete matching command for the active
session and repository. Approval consumes the nonce. Re-freezing invalidates
any previous nonce. Nonces expire 30 minutes after freezing.

## Direct Codex dispatch

`approve <nonce> direct` unlocks writer tools only for the bound Codex session
and repository. The skill executes the frozen brief in the current session and
may use configured Codex subagents. The brief's decision envelope governs
autonomous choices; contract, scope, security, destructive, or contradictory
decisions return to the user.

Completion requires successful evidence for every exact verification command.
The helper records terminal status and releases the active guard. Semantic
scope adherence remains workflow-enforced; the plugin does not replace Codex's
sandbox or Git review.

## Ralph dispatch

`approve <nonce> ralph` is eligible only when all of these hold:

- the working directory is a clean Git repository;
- `.docs/ai/current-state.md` exists and its Plan is empty;
- the brief has at least two independently verifiable phases;
- no phase has a Lead tier floor;
- every phase has an exact Verify command;
- the installed `ralph` supports the required Codex backend.

After approval, the helper runs real `ralph -n 0 -t codex` as a zero-iteration
preflight. Only after that passes may it write the Forge-owned planning files,
create one planning commit, and launch real `ralph -t codex`. Neither invocation
may pass `-L`.

Before child spawn, failures restore byte-exact snapshots of only Forge-owned
planning files and remove only the helper's own planning commit when safe.
After child spawn, Forge never rewinds commits. It records the child PID and
process-group identity, bounds captured output, and reports status. Cancellation
signals only a Ralph process group launched and still owned by this plugin
instance, with bounded graceful then forced termination.

## Guardrails and threat boundary

During `shaping` and `frozen`, `PreToolUse` denies:

- `apply_patch`, Edit, and Write aliases;
- mutating or ambiguous shell commands, including chaining, redirects,
  substitution, encoded interpreters, and indirect script execution;
- unknown or write-capable MCP tools;
- writer or mixed-mode subagent payloads;
- helper calls with forged session, repository, transition, or nonce data.

Policy is allowlist-based and fails closed for unknown local tools. Helper
subprocesses use argument arrays and never `eval` or shell-built commands.
Approved execution remains restricted by Codex's normal sandbox and approval
policy.

This is workflow enforcement, not an OS sandbox. Codex documents that some
specialized tool paths may bypass normal lifecycle hooks, and users can disable
or leave non-managed hooks untrusted. Forge therefore checks its heartbeat and
must surface that boundary rather than claiming protection when hooks are not
active. Concurrent malicious local filesystem races are outside this version's
threat model.

## Recovery and error behavior

- `SessionStart` restores active state for startup or resume and adds concise
  status context.
- `$forge status` reports lifecycle state, dispatcher, brief digest, approval
  expiry, verification progress, and Ralph ownership/status without exposing
  unbounded logs.
- Missing or untrusted hooks, malformed state, changed repository identity,
  exhausted questions, invalid briefs, stale approval, dirty Ralph state, or
  stale/non-owned PIDs fail closed.
- `revise <nonce>` returns to shaping with the prior brief retained for
  reference and its approval invalidated.
- `cancel <nonce>` closes a non-running session. Cancellation during Ralph
  execution follows owned-process termination rules.
- Stop-hook continuation is bounded so a corrupt state cannot trap Codex in an
  infinite continuation loop.

## Tests

### Unit and contract tests

- brief schema and canonical digest;
- lifecycle transition table;
- question budgets;
- nonce generation, expiry, single use, and cross-session/repository rejection;
- state path safety and atomic persistence;
- shell/tool/subagent classifier;
- direct and Ralph eligibility;
- exact-file rollback and process ownership;
- real Codex hook JSON input and output shapes.

### Adversarial tests

Cover command chaining, redirects, encoded commands, interpreter escape,
writer and mixed-mode subagents, unknown MCP calls, stale/replayed approval,
symlink state, invalid UTF-8, PID reuse, cross-session state, cross-repository
state, broad rollback, unbounded output, and shutdown of restored-but-unowned
processes.

### Integration tests

- temporary Git fixture for planning commit, real `ralph -n 0 -t codex`
  preflight, launch boundary, status, cancellation, and pre-spawn rollback;
- temporary `CODEX_HOME` local marketplace registration, plugin install,
  discovery, and idempotent update without unrelated config loss;
- plugin heartbeat refusal before trust and success after a trusted hook probe;
- personal/work plugin stanza parity;
- personal and work compose preflight;
- base public-safety scanner and its test suite.

### Human acceptance

1. Apply the base plus selected overlay stack.
2. Confirm `codex plugin list` shows `codex-forge` from `local-managed`
   enabled.
3. Review and trust the plugin hooks with `/hooks`, then restart Codex.
4. Run one `$forge` request through nonce-approved direct execution.
5. In a disposable clean repository, run one eligible two-phase request through
   nonce-approved Ralph execution.
6. Confirm status, verification evidence, cancellation ownership, and recovery
   after Codex restart.

## Acceptance

Codex on both personal and work machines can discover `$forge`, gather context,
ask only material capped questions, freeze a validated brief without repository
writes, require a genuine nonce-bearing user approval, and then execute through
direct Codex or guarded Ralph. Automated tests cover the policy and transaction
boundaries, native hook trust remains explicit, and unrelated Codex plugins,
hooks, configuration, and repository drift remain unchanged.

## References

- OpenAI Codex: Build skills — <https://developers.openai.com/codex/skills>
- OpenAI Codex: Build plugins — <https://developers.openai.com/codex/plugins/build>
- OpenAI Codex: Hooks — <https://developers.openai.com/codex/hooks>
