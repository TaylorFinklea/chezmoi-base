# Beads project task tracking

Use Beads (`bd`) by default for actionable issues, dependencies, ownership, and
status in every coding project, in both harnesses. There is no opt-in
step. Where supported, native Goals remain the approved outcome and thread
lifecycle; transient todos remain execution steps. The lead creates or claims
issues, assigns and updates them, and workers report progress and evidence to
the lead. A ready issue does not authorize work; follow the user's requested
scope and approval boundaries. Close issues only when their required evidence
and reviews are complete.

At the start of substantive project work, resume, and after compaction, resolve
the actual project/workspace root and confirm it is writable. Inspect the
project and its ancestors for `.beads` state, tracker configuration, relevant
environment redirection, and linked worktree relationships before writes. A
read-only `bd --sandbox where` probe is allowed to inspect the selected store.
Do not write while its location or ownership is uncertain. Reject
ancestor, neighboring-project, global, or cross-project stores. A linked
worktree may use the same project's existing store only when that relationship
and store are verified. Never set `BEADS_DIR` or use `bd --global`.

Do not initialize Beads for questions, read-only exploration, `$HOME`, or a
directory that is not an identified writable project. If no Beads store or
other project-specific tracker exists and the probe does not resolve to another
store, initialize the local embedded Dolt store from the project's working
directory:

```sh
bd init --skip-agents --skip-hooks --role contributor --non-interactive --sandbox
```

Preserve existing data. Never force-init, overwrite, or automatically import
an archive; ask the user if another tracker or existing state creates a
conflict. On every substantive start, resume, and after compaction, whether the
store already existed or was just initialized, run `bd --sandbox where` from
the project root to verify the selected project-local store, then run
`bd --sandbox prime` at that verified root.

Pass Beads' `--sandbox` global flag on every project command (for example,
`bd --sandbox list`) to disable Dolt auto-push. Each project keeps its own local
embedded Dolt database. Never use a central home-directory queue, personal/work
shared store, or server; never configure or infer a remote from Git remotes or
run automatic data sync, push, or pull. Use any remote operation only when the
user explicitly requests and approves that exact operation. Personal and work
projects remain separate. Do not bulk-initialize checkouts.
