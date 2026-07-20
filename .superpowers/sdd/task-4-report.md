# Task 4 Report

Status: DONE

## Commit

- `0c4710d feat(codex-forge): add guarded shaping workflow`

## RED evidence

- Added `tests/test_cli.py` and `tests/test_skill.py` before implementation.
- Focused run initially failed on missing CLI behavior and the skill command-contract assertion.

## GREEN evidence

- `python3 -m unittest dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_cli.py dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_skill.py -v` — passed; 4 tests.
- Full plugin discovery suite — passed; 59 tests.

## Interfaces

- `${PLUGIN_ROOT}/bin/codex-forge` resolves the adjacent `lib` directory and dispatches one explicit subcommand.
- `codex_forge.cli` implements `begin`, `question`, `freeze`, `status`, `complete`, and `fail` with bounded JSON responses and stable error objects.
- Mutating operations require hook-injected `CODEX_FORGE_SESSION_ID` and absolute `CODEX_FORGE_DATA`, current heartbeat, and exact cwd/repository binding.
- `freeze` validates the complete stdin brief, stores canonical brief plus SHA-256 digest, and writes a 256-bit single-use approval nonce with the Task 3 exact 1800-second approval schema.
- `$forge` documents recon-first shaping, three-question default/five-question hard cap, no repository writes while shaping, heartbeat and canonical CLI requirements, exact nonce choices, and direct/Ralph selection boundaries.
- Task 3 helper recognition now accepts only executable `${PLUGIN_ROOT}/bin/codex-forge status`; PATH aliases and the old `hooks/forge_hook.py` placeholder are not injected.

## Self-review

- Scope is limited to Task 4 CLI/skill/tests and the Task 3 helper-path reconciliation.
- No HOME, overlay, push, model-provided identity, shell evaluation, or Task 5/6 execution behavior was added.
- Existing Task 3 hook tests were updated from the placeholder helper path to the canonical executable path.
- Pre-existing untracked `.pi-subagents/` was not modified or staged.
- Residual concern: `complete` intentionally accepts only the Task 4 terminal verification marker (`passed`); richer verification recording remains Task 5 scope.

## Review fixes

Status: DONE

### RED evidence

- Added contract coverage for all six canonical helper subcommands and injection after approval.
- Added regressions for repository-controlled/arbitrary legacy helper lookalikes, supplied env/extra helper input, duplicate begin, stale heartbeat, changed repository binding, terminal verification, bounded failure reason, and freeze write/transition/cleanup failures.
- Freeze rollback tests initially exercised missing behavior before the cleanup/retry implementation.

### GREEN evidence

- Focused CLI/hooks/policy/skill suite: `python3 -m unittest ...` — 39 tests passed.
- Full plugin discovery: `python3 -m unittest discover -s dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests -p 'test_*.py'` — 62 tests passed.
- `python3 -m py_compile ...` — passed.
- `git diff --check` — passed.

### Self-review

- Canonical helper grammar is exact `${PLUGIN_ROOT}/bin/codex-forge {begin|question|freeze|status|complete|fail}` with exact tool input shape and hook-injected session/data; legacy `python3 .../hooks/forge_hook.py status` is no longer policy-allowed.
- Freeze cleans only the hashed session-owned brief/approval records on every failure and retries interrupted cleanup fail closed; Task 5/6 behavior remains untouched.
- Skill resolves `../../bin/codex-forge` relative to its loaded SKILL.md and does not depend on a model-visible `PLUGIN_ROOT` variable.

### Base64url transport decision

- User decision: replace stdin model payloads with one exact unpadded base64url argument for `question`, `freeze`, and `fail`; `begin`, `status`, and `complete` accept no payload. Reject padding, invalid alphabet, oversize values, invalid UTF-8, trailing JSON, wrong argument counts, shell metacharacters, and model-supplied environment before helper injection.
- RED evidence: prior CLI/hook tests failed after removing stdin transport until callers, canonical helper grammar, and structured decoding were updated; added regressions cover valid payloads and all requested rejection classes.
- GREEN evidence: full plugin discovery passed with 65 tests; focused CLI/hooks/skill tests passed with 35 tests; `StateStore.replace` coverage now exercises publication failure and uncertain post-replace directory-fsync failure, then reloads and safely continues from the published state.

### Uncertain freeze publication closure

- Freeze now reloads state after replace failures; pre-publication failures clean exact session-owned records, while published frozen state retains approval/brief records and returns the original nonce.
- Identical freeze retries and status remain usable after an uncertain directory-fsync failure.
- Canonical helper validation rejects the bare helper path without indexing past the parsed command.
- Verification: full plugin discovery passed with 66 tests; py_compile and git diff --check passed.

### Completion gate closure

- `complete` now rejects every `executing` and `ralph_running` session with `verification_not_terminal`; lifecycle status alone can never transition to `completed` pending Task 5 exact verification records.
- Added regressions covering both executing and ralph_running states, including state-preservation assertions.
- Full plugin discovery: 68 tests passed; `git diff --check` passed.
