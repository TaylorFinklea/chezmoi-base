# Codex Forge Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a native Codex plugin that shapes implementation requests behind an enforced write gate, requires nonce-backed user approval, and dispatches approved work through direct Codex or guarded Ralph on personal and work machines.

**Architecture:** A public `codex-forge` plugin bundles the `$forge` skill, lifecycle hooks, and a Python-standard-library state/dispatch helper. The plugin is installed from a chezmoi-managed local marketplace; plugin hooks bind helper operations to Codex's real session ID and block writer tools until `UserPromptSubmit` validates a single-use approval nonce.

**Tech Stack:** Codex CLI 0.144.6+, Codex skills/plugins/hooks, Python 3 standard library, Bash 3.2, chezmoi composition, Git, Ralph.

## Global Constraints

- Public plugin source lives in `chezmoi-base` and intentionally reaches personal and work machines.
- Marketplace name: `local-managed`; plugin name: `codex-forge`; initial version: `0.1.0`.
- Default question budget: 3; hard cap: 5.
- Approval nonce lifetime: 30 minutes; nonce is single-use, session-bound, and repository-bound.
- No repository mutation before nonce approval.
- Unknown local tools fail closed during shaping and frozen states.
- Python helper uses only the standard library; no runtime package installation.
- Ralph requires clean Git, empty Plan, at least two exact-Verify non-Lead phases, runs `ralph -n 0 -t codex` preflight, then launches `ralph -t codex`; never pass `-L` to either invocation.
- Pre-spawn rollback restores only Forge-owned planning files; never rewind commits after spawn.
- Preserve unrelated Codex runtime configuration and existing Atuin/Neovim drift.
- Hook trust stays a native, explicit Codex user action.

---

### Task 1: Teach compose sync to run isolated chezmoi scripts

**Files:**
- Modify: `scripts/chezmoi-compose`
- Modify: `tests/test-compose.sh`

**Interfaces:**
- Consumes: native `chezmoi status` entries whose code is ` R` and target begins `.chezmoiscripts/`.
- Produces: one `chezmoi apply --include scripts` call per source with pending scripts, without applying ordinary file drift.

- [ ] **Step 1: Extend the fake chezmoi with script-only apply behavior**

Add a fake status case for ` R .chezmoiscripts/install-codex-forge.sh`. Extend the fake `apply` parser so `--include scripts` records:

```text
apply-scripts:<source>:--include scripts
```

and creates a marker, while proving an unrelated missing destination file is not materialized.

- [ ] **Step 2: Add failing sync assertions**

Add a test source with one run-on-change script status and one unrelated file status. Assert that sync:

```text
- invokes apply --include scripts exactly once for that source;
- does not put the script pseudo-target into the decision queue;
- does not use --force;
- does not apply unrelated file content through the script-only call.
```

- [ ] **Step 3: Run the focused test and confirm RED**

Run:

```bash
bash tests/test-compose.sh
```

Expected: FAIL because `.chezmoiscripts/install-codex-forge.sh` is treated as a decision and no script-only apply occurs.

- [ ] **Step 4: Implement script classification**

In `classify_source`, track a source-local `scripts_pending` flag. Handle only this exact case specially:

```bash
if [ "$code" = ' R' ] && [[ "$target" == .chezmoiscripts/* ]]; then
  scripts_pending=1
  continue
fi
```

After ordinary and forced file batches, execute:

```bash
if [ "$scripts_pending" -eq 1 ]; then
  run_chezmoi "$source" apply --include scripts
fi
```

Do not broaden handling of other unknown status codes.

- [ ] **Step 5: Run compose regression coverage**

Run:

```bash
bash tests/test-compose.sh
scripts/chezmoi-compose preflight personal
scripts/chezmoi-compose preflight work
```

Expected: all assertions pass; both preflights exit 0.

- [ ] **Step 6: Commit Task 1**

```bash
git add scripts/chezmoi-compose tests/test-compose.sh
git commit -m "feat(compose): run managed scripts in isolation"
```

---

### Task 2: Implement the Execution Brief and persistent state domain

**Files:**
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/lib/codex_forge/__init__.py`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/lib/codex_forge/brief.py`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/lib/codex_forge/state.py`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_brief.py`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_state.py`

**Interfaces:**
- Produces: `parse_brief(raw) -> Brief`, `canonical_brief_bytes(brief) -> bytes`, `brief_digest(brief) -> str`, `StateStore`, and `transition(state, event) -> ForgeState`.
- State schema version: `1`; plugin version: `0.1.0`.

- [ ] **Step 1: Write failing brief tests**

Cover required scalar/list fields, exact verification commands, phase validation, newline/control-character rejection in structural fields, unknown-key rejection, deterministic canonical bytes, and digest stability. The brief data contract is:

```python
{
    "version": 1,
    "goal": str,
    "scope": list[str],
    "non_goals": list[str],
    "decisions": list[str],
    "acceptance": list[str],
    "patterns": list[str],
    "verification": list[str],
    "assumptions": list[str],
    "decision_envelope": {"autonomous": list[str], "escalate": list[str]},
    "phases": list[{"name": str, "tier_floor": "senior" | "junior", "verify": str}],
    "dispatcher": "direct" | "ralph",
}
```

- [ ] **Step 2: Write failing state tests**

Cover every allowed and rejected transition among:

```text
shaping → frozen → approved_direct → executing → completed
shaping → frozen → approved_ralph → ralph_running → completed
frozen → shaping
shaping|frozen|approved_*|executing|ralph_running → cancelled|failed
```

Also test private directory mode, atomic replacement, schema/plugin mismatch, canonical cwd/repository binding, symlink rejection, invalid UTF-8 rejection, and missing/corrupt state.

- [ ] **Step 3: Run tests and confirm RED**

Run:

```bash
python3 -m unittest discover -s dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests -p 'test_*.py' -v
```

Expected: import failures for `codex_forge.brief` and `codex_forge.state`.

- [ ] **Step 4: Implement the brief domain**

Use frozen dataclasses for `Brief`, `DecisionEnvelope`, and `Phase`. Validate before construction. Serialize canonical JSON with sorted keys, compact separators, UTF-8, and `ensure_ascii=False`; digest with SHA-256.

- [ ] **Step 5: Implement state persistence and transitions**

`StateStore(data_root: Path, plugin_version: str)` must expose:

```python
load(session_id: str) -> ForgeState | None
create(session_id: str, cwd: Path, repo: RepoIdentity | None) -> ForgeState
replace(state: ForgeState) -> None
delete(session_id: str) -> None
```

Reject path-derived session identifiers; map session IDs to SHA-256 filenames. Create directories as `0700`, files as `0600`, open with no-follow semantics where supported, fsync file and directory, then atomically replace.

- [ ] **Step 6: Run Task 2 tests**

Run the unittest command from Step 3.

Expected: all brief and state tests pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add dot_local/share/codex-forge-marketplace/plugins/codex-forge/lib dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests
git commit -m "feat(codex-forge): add brief and state domain"
```

---

### Task 3: Add shaping policy and lifecycle hook protocol

**Files:**
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/lib/codex_forge/policy.py`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/lib/codex_forge/hooks.py`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/hooks/forge_hook.py`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/hooks/hooks.json`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/fixtures/hooks/*.json`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_policy.py`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_hooks.py`

**Interfaces:**
- Consumes: documented Codex hook JSON for `SessionStart`, `PreToolUse`, `UserPromptSubmit`, `PostToolUse`, and `Stop`.
- Produces: `classify_tool(tool_name, tool_input, state) -> PolicyDecision` and `handle_hook(event, env) -> HookResult`.

- [ ] **Step 1: Add real-shaped hook fixtures and failing tests**

Fixtures must include common fields (`session_id`, `cwd`, `hook_event_name`, `model`) plus each event's documented fields. Tests assert exact Codex-compatible output shapes, including:

```json
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Forge shaping blocks writer tools until nonce approval."}}
```

and exact `decision: "block"` behavior for invalid approval prompts.

- [ ] **Step 2: Add adversarial policy tests**

Deny during shaping/frozen:

```text
apply_patch/Edit/Write;
shell redirects, pipes, chaining, substitutions, heredocs, rm/mv/cp/install/tee;
python/node/ruby/perl -c/e indirect execution;
git mutation;
unknown MCP/local tools;
writer or mixed-mode spawn_agent payloads.
```

Allow narrowly read-only commands (`git status`, `git log`, `git diff`, `rg`, `find`, `ls`, test discovery without execution), hosted-tool gaps documented as outside the hook path, `request_user_input`, and read-only scout agents.

- [ ] **Step 3: Run policy/hook tests and confirm RED**

Run:

```bash
python3 -m unittest dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_policy.py dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_hooks.py -v
```

Expected: imports fail.

- [ ] **Step 4: Implement allowlist policy**

Parse shell input conservatively; do not invoke a shell to classify it. Reject control operators and ambiguous syntax before command allowlisting. Recognize Codex's canonical `Bash`, `apply_patch`, `Agent`, and MCP tool names. Unknown local tools deny while state is shaping/frozen and fall through to normal Codex policy when no Forge state exists.

- [ ] **Step 5: Implement hook handling**

- `SessionStart`: write heartbeat `{plugin_version, session_id, cwd, timestamp}` and emit concise status context.
- `PreToolUse`: load session state, enforce policy, and inject `CODEX_FORGE_SESSION_ID` plus `CODEX_FORGE_DATA` only into recognized plugin-helper commands.
- `UserPromptSubmit`: accept only complete nonce commands; bind session/cwd/repository and enforce 30-minute expiry.
- `PostToolUse`: no-op until Task 5 adds verification recording.
- `Stop`: allow shaping/frozen turns to end; use a bounded continuation counter for incomplete execution.

- [ ] **Step 6: Add the hook entrypoint and registration**

`forge_hook.py` must add the plugin `lib` directory to `sys.path`, read exactly one JSON object from stdin, call `handle_hook`, emit one JSON object, and return exit 2 only for documented blocking failures. `hooks.json` invokes it through `${PLUGIN_ROOT}` for all five events.

- [ ] **Step 7: Run Task 3 and full plugin tests**

Run:

```bash
python3 -m unittest discover -s dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests -p 'test_*.py' -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 3**

```bash
git add dot_local/share/codex-forge-marketplace/plugins/codex-forge
git commit -m "feat(codex-forge): enforce shaping with lifecycle hooks"
```

---

### Task 4: Add the guarded control CLI and `$forge` skill

**Files:**
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/bin/codex-forge`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/lib/codex_forge/cli.py`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/skills/forge/SKILL.md`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_cli.py`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_skill.py`

**Interfaces:**
- Produces CLI subcommands: `begin`, `question`, `freeze`, `status`, `complete`, and `fail`.
- Every mutating subcommand requires hook-injected `CODEX_FORGE_SESSION_ID` and `CODEX_FORGE_DATA`.

- [ ] **Step 1: Write failing CLI tests**

Test bounded JSON stdout and structured base64url JSON input for:

```text
begin -- creates shaping state only with a current heartbeat;
question <base64url-json> -- increments before returning and rejects attempt 6;
freeze <base64url-json> -- validates brief, stores digest, creates 256-bit nonce, expires in 30 minutes;
status -- returns bounded state without full logs;
complete -- rejects non-terminal verification;
fail <base64url-json> -- records a bounded failure reason.
```

Structured arguments are unpadded base64url using only `[A-Za-z0-9_-]`, have a
fixed encoded-size cap, decode as UTF-8, and contain exactly one JSON value.

Reject model-supplied session/data arguments, missing injected environment, changed cwd/repository, duplicate begin, and malformed JSON.

- [ ] **Step 2: Write failing skill contract tests**

Assert the skill frontmatter is `name: forge`, describes `$forge`, and includes all hard rules: recon first, default 3/hard 5, no writes while shaping, freeze through CLI, exact nonce choices, direct/Ralph selection, and heartbeat refusal.

- [ ] **Step 3: Run tests and confirm RED**

Run:

```bash
python3 -m unittest dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_cli.py dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_skill.py -v
```

Expected: missing CLI and skill failures.

- [ ] **Step 4: Implement the CLI**

The executable resolves `../lib`, imports `codex_forge.cli`, and never
evaluates user text as shell. `question`, `freeze`, and `fail` accept exactly
one size-bounded, unpadded base64url JSON argument; `freeze` decodes and
validates the complete brief. The hook's canonical helper grammar validates the
same alphabet/count before environment injection. Output one bounded JSON
response. Error responses use a stable `{ok:false, code, message}` shape and
non-zero exit.

- [ ] **Step 5: Write the skill**

Use the loaded skill's own path to invoke `../../bin/codex-forge`. Require one focused question at a time. End the frozen turn by printing only the brief summary plus exact approve/revise/cancel commands. Do not permit prose-only approval or direct implementation before hook-confirmed state changes.

- [ ] **Step 6: Run Task 4 and full plugin tests**

Run the Task 3 discovery command.

Expected: all tests pass.

- [ ] **Step 7: Commit Task 4**

```bash
git add dot_local/share/codex-forge-marketplace/plugins/codex-forge
git commit -m "feat(codex-forge): add guarded shaping workflow"
```

---

### Task 5: Enforce direct execution verification and completion

**Files:**
- Modify: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/lib/codex_forge/hooks.py`
- Modify: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/lib/codex_forge/cli.py`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/lib/codex_forge/verification.py`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_verification.py`
- Modify: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_hooks.py`
- Modify: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_cli.py`

**Interfaces:**
- Produces: `record_verification(state, command, response) -> ForgeState` and completion eligibility for direct execution.

- [ ] **Step 1: Write failing verification tests**

Require exact command equality with the frozen brief, exit status 0, bounded output preview, output digest, timestamp, and one evidence record per required command. Reject lookalike commands, stale brief digests, missing exit status, and replay from another session.

- [ ] **Step 2: Write failing direct-state hook tests**

After `approve <nonce> direct`, assert writer tools unlock only for the bound session/cwd/repository. Assert `PostToolUse` records only exact verification commands and `Stop` continues at most once when execution lacks required evidence.

- [ ] **Step 3: Run tests and confirm RED**

Run:

```bash
python3 -m unittest dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_verification.py dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_hooks.py -v
```

Expected: direct verification assertions fail.

- [ ] **Step 4: Implement verification recording**

Store at most 4 KiB head/tail evidence per command plus SHA-256 of the complete model-visible response. Never store unbounded output. Preserve failed attempts but require a later passing attempt.

- [ ] **Step 5: Gate completion and Stop behavior**

`complete` transitions only when every exact verification command has a passing record. A bounded Stop continuation tells Codex which commands remain; a second Stop fails the Forge run and releases the guard rather than looping forever.

- [ ] **Step 6: Run full plugin tests**

Run the Task 3 discovery command.

Expected: all tests pass.

- [ ] **Step 7: Commit Task 5**

```bash
git add dot_local/share/codex-forge-marketplace/plugins/codex-forge
git commit -m "feat(codex-forge): require direct verification evidence"
```

---

### Task 6: Add guarded Ralph preparation, launch, recovery, and cancellation

**Files:**
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/lib/codex_forge/ralph.py`
- Modify: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/lib/codex_forge/cli.py`
- Modify: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/skills/forge/SKILL.md`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_ralph.py`
- Create: `tests/test_codex_forge_ralph.sh`

**Interfaces:**
- Produces: `inspect_ralph_eligibility`, `prepare_ralph_dispatch`, `recover_ralph_status`, and `cancel_owned_ralph`.
- Adds CLI subcommands: `ralph-preflight`, `ralph-launch`, `ralph-status`, and `ralph-cancel`.

- [ ] **Step 1: Read the existing Pi Ralph transaction pattern**

Read these codebase-derived references before writing signatures or Git mechanics:

```text
../chezmoi-personal/dot_pi/agent/extensions/forge/ralph.ts
../chezmoi-personal/dot_pi/agent/extensions/forge/ralph.test.ts
../chezmoi-personal/scripts/tests/test_forge_ralph.sh
```

Mirror its clean-repo, exact-snapshot, spawn-boundary, output-bound, and process-group ownership patterns. Replace only backend-specific Pi details with the spec's Codex values.

- [ ] **Step 2: Write failing Python eligibility/transaction tests**

Cover non-Git, dirty Git, non-empty Plan, fewer than two phases, Lead phases, missing Verify, invalid structural newlines, missing Ralph, unsafe symlink planning files, planning-commit failure, spawn failure rollback, no post-spawn rewind, restored-but-unowned PID, PID reuse, and bounded logs.

- [ ] **Step 3: Write the failing temporary-Git shell fixture**

Create a temporary repository with `.docs/ai/`, a fake backend environment, and real `ralph -n 0 -t codex`. Assert exact argv excludes `-L`, the planning commit contains only Forge-owned files, and pre-spawn failure restores byte-exact files.

- [ ] **Step 4: Run Ralph tests and confirm RED**

Run:

```bash
python3 -m unittest dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests/test_ralph.py -v
bash tests/test_codex_forge_ralph.sh
```

Expected: missing Ralph adapter failures.

- [ ] **Step 5: Implement eligibility and Markdown preparation**

Parse `.docs/ai/current-state.md` structurally, require an empty Plan, render exact phase checkboxes with Verify commands, snapshot only Forge-owned paths, and validate regular files/no symlinks before writes.

- [ ] **Step 6: Implement launch and rollback boundary**

Use subprocess argument arrays for real preflight and launch:

```text
ralph -n 0 -t codex
ralph -t codex
```

The zero-iteration preflight occurs before planning writes. Create one planning
commit before the actual launch spawn. On pre-spawn failure, restore exact snapshots and remove only that planning commit when HEAD still matches. After successful spawn, record PID/process group and never reset Git.

- [ ] **Step 7: Implement status and cancellation**

Recover only plugin-owned processes whose recorded identity still matches. Bound output, escalate TERM to KILL after a finite timeout, and never signal a restored or reused unowned PID.

- [ ] **Step 8: Run Ralph and full plugin tests**

Run both Step 4 commands and the full plugin discovery command.

Expected: all tests pass.

- [ ] **Step 9: Commit Task 6**

```bash
git add dot_local/share/codex-forge-marketplace/plugins/codex-forge tests/test_codex_forge_ralph.sh
git commit -m "feat(codex-forge): add guarded Ralph dispatch"
```

---

### Task 7: Package and install the native plugin through a local marketplace

**Files:**
- Create: `dot_local/share/codex-forge-marketplace/dot_agents/plugins/marketplace.json`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/dot_codex-plugin/plugin.json`
- Create: `.chezmoiscripts/run_onchange_after_install-codex-forge.sh.tmpl`
- Create: `tests/test_codex_forge_plugin.sh`
- Create: `dot_local/share/codex-forge-marketplace/plugins/codex-forge/README.md`

**Interfaces:**
- Marketplace root after rendering: `~/.local/share/codex-forge-marketplace`.
- Selector behavior: `codex plugin add codex-forge --marketplace local-managed`.

- [ ] **Step 1: Write the failing temporary-CODEX_HOME installer test**

Render the base source into a temporary HOME, run the rendered installer twice, and assert:

```text
marketplace local-managed is registered;
codex-forge version 0.1.0 is copied into plugin cache;
plugin is enabled;
second run is idempotent;
an unrelated marketplace/plugin config stanza remains byte-equivalent;
plugin list reports version 0.1.0 and the cached manifest resolves the Forge
skill and hook bundle.
```

- [ ] **Step 2: Run the installer test and confirm RED**

Run:

```bash
bash tests/test_codex_forge_plugin.sh
```

Expected: marketplace/manifest/installer files are missing.

- [ ] **Step 3: Add marketplace and plugin manifests**

Marketplace entry uses local source `./plugins/codex-forge`, category `Productivity`, installation `AVAILABLE`, and authentication `ON_INSTALL`. Plugin manifest declares version `0.1.0`, `skills: "./skills/"`, and `hooks: "./hooks/hooks.json"`.

- [ ] **Step 4: Add the idempotent run-on-change installer**

The rendered script must:

```bash
codex plugin marketplace add "$HOME/.local/share/codex-forge-marketplace" --json
codex plugin add codex-forge --marketplace local-managed --json
```

Fail non-zero on either command, preserve unrelated config, and embed plugin version `0.1.0` so a future version bump changes the run-on-change content hash.

- [ ] **Step 5: Add operator documentation**

Document install/update, `/hooks` trust, `$forge`, nonce choices, direct/Ralph status, cancellation, and the workflow-enforcement threat boundary.

- [ ] **Step 6: Run plugin packaging and policy tests**

Run:

```bash
bash tests/test_codex_forge_plugin.sh
python3 -m unittest discover -s dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests -p 'test_*.py' -v
python3 tests/test-public-safety.py
```

Expected: installer idempotency passes, plugin tests pass, and 48+ public-safety tests pass.

- [ ] **Step 7: Run the scanner against a clean clone containing the branch**

Run the scanner from a disposable clean clone or equivalent clean export so ignored `ai-scratch/` content cannot create unrelated findings.

Expected: scanner exits 0.

- [ ] **Step 8: Commit Task 7**

```bash
git add dot_local/share/codex-forge-marketplace .chezmoiscripts/run_onchange_after_install-codex-forge.sh.tmpl tests/test_codex_forge_plugin.sh
git commit -m "feat(codex): package Forge as a managed plugin"
```

---

### Task 8: Enable Forge in personal and work Codex configuration

**Files:**
- Modify in `chezmoi-personal`: `.chezmoidata/ai.json`
- Modify in `chezmoi-work`: `.chezmoidata/ai.json`
- Modify in both overlays: `.chezmoitemplates/codex/plugins.toml`
- Modify in `chezmoi-work`: `dot_codex/private_config.toml.tmpl`
- Modify in `chezmoi-personal`: `scripts/tests/test_codex_tui_partial_parity.sh`

**Interfaces:**
- Produces byte-identical shared marketplace/plugin partials in both overlays.
- Adds `codex-forge` with scope `shared` to both `codexPlugins` arrays.

- [ ] **Step 1: Extend the parity test and confirm RED**

Add `plugins.toml` to the parity partial list. Run:

```bash
bash scripts/tests/test_codex_tui_partial_parity.sh
```

Expected: FAIL after changing only the personal plugin partial in the next step, proving the guard covers this surface.

- [ ] **Step 2: Add the shared marketplace stanza to the personal partial**

Render:

```toml
[marketplaces.local-managed]
source_type = "local"
source = "<home>/.local/share/codex-forge-marketplace"
```

using the existing chezmoi home-dir template value. Add a shared
`codexPlugins` entry whose ID is the marketplace-qualified plugin selector
formed from `codex-forge`, an at-sign, and `local-managed`.

- [ ] **Step 3: Mirror the exact partial and data entry in work**

Copy the same `plugins.toml` content and add the same shared plugin entry to work `ai.json`. Change work Codex `[features] hooks` from `false` to `true`; update its comment to state that work does not run Moshi but does load trusted plugin-scoped hooks.

- [ ] **Step 4: Run overlay parity and rendering tests**

Run from `chezmoi-personal`:

```bash
bash scripts/tests/test_codex_tui_partial_parity.sh
bash scripts/tests/test_codex_mcp_parity.sh
```

Render both Codex configs with their existing profile-data pattern and parse each with Python `tomllib`.

Expected: parity tests pass; both rendered configs contain
`marketplaces.local-managed`, an enabled `plugins` entry for the
marketplace-qualified Forge selector, and `features.hooks = true`.

- [ ] **Step 5: Run both compose preflights**

From `chezmoi-base`:

```bash
scripts/chezmoi-compose preflight personal
scripts/chezmoi-compose preflight work
```

Expected: both exit 0 with no ownership collisions.

- [ ] **Step 6: Commit the work overlay**

```bash
git -C ../chezmoi-work add .chezmoidata/ai.json .chezmoitemplates/codex/plugins.toml dot_codex/private_config.toml.tmpl
git -C ../chezmoi-work commit -m "feat(codex): enable shared Forge plugin"
```

- [ ] **Step 7: Commit the personal overlay**

```bash
git -C ../chezmoi-personal add .chezmoidata/ai.json .chezmoitemplates/codex/plugins.toml scripts/tests/test_codex_tui_partial_parity.sh
git -C ../chezmoi-personal commit -m "feat(codex): enable shared Forge plugin"
```

Do not stage unrelated `dot_config/atuin/config.toml` or `dot_config/nvim/lazyvim.json` drift.

---

### Task 9: Final review, deployment, and handoff

**Files:**
- Modify in `chezmoi-personal`: `.docs/ai/decisions.md`
- Modify in `chezmoi-personal`: `.docs/ai/roadmap.md`
- Modify in `chezmoi-personal`: `.docs/ai/current-state.md`
- Create in `chezmoi-personal`: `.docs/ai/phases/codex-forge-plugin-report.md`

**Interfaces:**
- Produces final automated evidence, live installation status, and explicit human trust/smoke actions.

- [ ] **Step 1: Run the complete automated gate**

From `chezmoi-base`, run:

```bash
bash tests/test-compose.sh
bash tests/test_codex_forge_plugin.sh
bash tests/test_codex_forge_ralph.sh
python3 -m unittest discover -s dot_local/share/codex-forge-marketplace/plugins/codex-forge/tests -p 'test_*.py' -v
python3 tests/test-public-safety.py
scripts/chezmoi-compose preflight personal
scripts/chezmoi-compose preflight work
git diff --check
```

From `chezmoi-personal`, run:

```bash
bash scripts/tests/test_codex_tui_partial_parity.sh
bash scripts/tests/test_codex_mcp_parity.sh
git diff --check
```

From `chezmoi-work`, run:

```bash
git diff --check
```

Run the base scanner from a clean clone containing the final commits.

Expected: every command exits 0.

- [ ] **Step 2: Request independent adversarial review**

Review the complete cross-repo diff with an equal-or-higher-tier read-only reviewer. Require explicit findings for hook bypasses, nonce provenance, state/path safety, command classification, direct verification, Ralph transaction boundaries, plugin install/config preservation, and work-machine public-safety.

Fix accepted Critical/Important findings with focused RED/GREEN tests, rerun the full gate, and obtain a final Ready-to-merge verdict.

- [ ] **Step 3: Merge the implementation branches locally**

Fast-forward or merge the reviewed base, personal, and work branches into each repository's `main`. Do not push.

- [ ] **Step 4: Apply only managed plugin source files to the live personal stack**

Use `scripts/chezmoi-compose apply personal` with exact managed marketplace/plugin file targets. Do not apply the entire Codex config and do not resolve unrelated drift.

- [ ] **Step 5: Install/update the live plugin without overwriting config**

Run the same two idempotent native commands as the rendered installer:

```bash
codex plugin marketplace add "$HOME/.local/share/codex-forge-marketplace" --json
codex plugin add codex-forge --marketplace local-managed --json
```

Verify `codex plugin list --json` reports version `0.1.0` enabled and existing unrelated plugin entries remain present.

- [ ] **Step 6: Update decision and handoff records**

Append one concise ADR: native plugin chosen over skill-only/global-hook designs because Forge bundles a skill with lifecycle enforcement and needs plugin-owned state; nonce approval is user-originated; deployment is public base plus overlay config parity. Update roadmap/current-state with automated results and the pending `/hooks` trust plus two human smokes. Write the implementation report with commit IDs and residual threat boundary.

- [ ] **Step 7: Commit handoff documentation**

```bash
git -C ../chezmoi-personal add .docs/ai/decisions.md .docs/ai/roadmap.md .docs/ai/current-state.md .docs/ai/phases/codex-forge-plugin-report.md
git -C ../chezmoi-personal commit -m "docs(codex): record Forge plugin delivery"
```

- [ ] **Step 8: Stop at the native trust gate**

Ask the user to restart Codex, open `/hooks`, trust the `codex-forge` plugin hooks, restart again, then run one nonce-approved direct `$forge` and one disposable Ralph `$forge`. Do not claim interactive completion before those checks.
