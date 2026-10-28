# Decisions

> Architecture decision records. Entries are append-only by default, one entry per decision.
> Explicit owner requests for redaction or removal are an exception.

## [2026-08-01] `herdr-ask` converges through both release channels from base

**Context**: Base already manages the shared `herdr-ask` configuration and a
Herdr keybinding that invokes `dev.herdr-ask.open`, but fresh machines received
neither the PATH-visible binary nor the plugin providing that action.

**Decision**: A base-owned run-on-change script pins version 0.1.0, installs or
upgrades `taylorfinklea/tap/herdr-ask`, and installs or refreshes the matching
`TaylorFinklea/herdr-ask` Herdr plugin tag. Normal composed sync runs the script
for both personal and work roles.

**Alternatives considered**: Homebrew only plus changing the keybinding to a
direct popup (rejected — changes the existing plugin-action behavior); plugin
only (rejected — leaves no standalone `herdr-ask` command on PATH); duplicate
package entries in both overlays (rejected — two owners can drift).

**Upgrade rule**: Bump the version literal in the base script when publishing a
new release. Its content change schedules another run on every machine.

## [2026-08-01] OMP is a safe custom Herdr Ask process backend

**Context**: The managed Herdr Ask release is 0.1.0, which has no built-in OMP
adapter. Waiting for a new Herdr Ask release would leave composed machines
without the requested backend.

**Decision**: Configure `omp` through Herdr Ask's existing custom-process
contract. Requests use stdin; the fixed argv enables print mode and disables
sessions, tools, LSP, PTY execution, extensions, skills, and rule discovery.
The Herdr Ask system prompt remains explicit. `model = "auto"` leaves model
selection to OMP unless the user supplies a concrete model.

**Alternative considered**: Treat OMP as Pi's built-in adapter (rejected — that
adapter invokes the `pi` executable and depends on Pi-specific flags and model
discovery). A future first-class OMP adapter may replace this block after it is
released across both Herdr Ask distribution channels.

## [2026-08-10] Share tmux core through base and keep Moshi personal-only

The complete tmux setup is now base-owned: the config, cheatsheet, which-key
menu, TmuxAI config, and TPM plugin externals compose on both personal and
work machines. The personal overlay retains `moshi-status.sh` and adds
`tmux-local.conf`; the shared config sources that file only when present.

This preserves one-target/one-owner composition while keeping Moshi hooks out
of work environments. The public-safety allowlist explicitly admits the six
public plugin repositories used by the base external manifest.

## [2026-10-14] Codex uses only Luna and Sol, with local adversarial review

Codex routing uses only Luna 6 and Sol 6.1. Luna implements and explores;
`worker_sol` replaces `worker_terra` as the escalation after a failed Luna
attempt, and `reviewer` runs Sol. Terra is never used, and Astra only when the
owner asks.

Every non-trivial change gets the Sol `reviewer` plus a read-only adversarial
review using a locally available Ollama model: DeepSeek V4.1 Flash, MiniMax M3.1
Flash, or GLM 5.3 Flash. Reviewed commits carry `Reviewed-by:` trailers for both
reviews. Overlays list the two retired agent files in `.chezmoiremove` so
composed applies delete them on both machines.
