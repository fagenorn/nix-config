# Launch scratch roots (#277)

Slice S3 of the [launch process reaping design](2026-10-06-launch-process-reaping-design.md)
(cited as "parent Dn"), on top of [#276's `exec` and `reap`](2026-10-07-issue-276-launch-scope-exec-reap-design.md)
(cited as "#276 Dn"). The parent settles the rule: reap deletes only inside a
launch's own scratch root, and every other worktree is only reported (parent
D8). This spec pins the `scratch` verb, what reap removes, and which worktrees
it reports.

## Problem

An agent that needs a scratch directory or a throwaway worktree makes one
wherever it likes, usually under `$TMPDIR`. When the agent is stopped or
superseded, nothing knows the directory exists. In the #262 run this left the
`issue262-accept/base` worktree behind, registered in the main repository with
no owner. The user chose to keep that worktree, so a fix must not delete it.

## Solution

1. **`launch-scope scratch`** prints one scratch root per launch. The first
   call creates it, and every later call prints the same path. The launch's
   owner and its workers share the root.
2. **`reap` removes the root.** After a launch's processes are gone, reap
   force-removes every worktree of the repository that is registered inside the
   root and deletes the root. It never runs a repository-wide
   `git worktree prune`, which would also drop registrations outside every root (D10).
3. **`reap` reports leftovers.** Every reap lists the registered worktrees that
   sit outside the main checkout and outside every recorded scratch root as
   `unattributed_worktrees`, and deletes none of them.
4. **Adoption.** Each lifecycle-identity `exec` sentence from #276 gains a
   `scratch` counterpart. The leaf-agent clauses stay unchanged.

## Decisions

### Command surface

```text
launch-scope scratch --repo-root R --run-id I (--action-id A | --worker-id W)
```

The identity rules are `exec`'s: exactly one identity, and a worker's launch is
its ID without the `:w<n>` suffix (#276 D2). The safe-segment check is also
`exec`'s (#276 D10). A worker reaches its owner's root through that derivation,
because the root is per launch (D1).

1. Validate the arguments and resolve the registry. A usage error, or a `git`
   or `workflow-state` that cannot be started, exits 2 with nothing on stdout.
2. Check liveness the way `exec` does (#276 D4). On any answer other than a
   positive one for this identity, print one canonical JSON line
   `{"action_id", "created": false, "reason"}` and exit 3. The reasons are
   `exec`'s. A refusal creates nothing and deletes nothing (D2).
3. Read the launch's scratch record. If there is none, create the root with
   `mkdtemp(prefix="launch-scope-")` under the system temp directory. Record its
   real path with an exclusive create. A caller that loses the race to
   another `scratch` call removes its own empty directory and uses the winner's
   record (D3).
4. If the recorded root is missing, recreate it at the same path with mode
   0700. A recorded path that exists but is not a real directory, or a record
   that is malformed, exits 2 (D4).
5. Print the root's real path and a newline, as plain text, and exit 0.

### Scratch record

The record is `scratch.json` in the launch's registry directory. It holds
`{"path"}`, written canonically and loaded strictly with `agent_tools.canonical`'s
hooks. The path is valid only when all of these hold:

- it is absolute and equal to its own real path;
- its basename matches `launch-scope-[a-z0-9_]+`.

Validation does not depend on the reader's `TMPDIR`, because an owner and the
adapter's sweep may run with different temp directories (D4). The name is not
a group row (`<nonce>.json`), so the row parser ignores it. Reap's snapshot
already covers every regular file, so a record written during a reap makes that
round unclean and triggers another round (#276 D16).

### Reap

Each launch is reaped as #276 specifies. Then, in the round where the
processes are gone, the snapshot is unchanged and no marked process is live,
the scratch step runs before the proved files are removed. The step uses the
snapshot's record:

1. No record means there is nothing to do. A malformed or invalid record skips
   the launch with `scratch_not_removed` and keeps its directory.
2. List the repository's worktrees with `git -C R worktree list --porcelain -z`.
   A worktree is inside the root when its real path is the root or lies below
   it. Each such worktree, except the main worktree, is removed with
   `git -C R worktree remove --force --force <path>`. A registration whose
   directory is already gone is removed the same way: `remove --force --force`
   drops the registration of a missing worktree, locked or not (D10). Git records real paths, so
   a worktree reached through a symlink that leads out of the root counts as
   outside and is kept; `rmtree` removes only the link.
3. Delete the root with `shutil.rmtree` if it exists. A root that is already
   gone is not an error; a root that step 2 took away, because a worktree
   occupied the root itself, counts as deleted by this reap.
4. List again. Any worktree still
   registered inside the root, or any failed remove or rmtree, skips the
   launch with `scratch_not_removed` and keeps the record and directory for the
   next reap. Each failure names on stderr the operation, the path, and git's
   exit status and stderr or the filesystem error (D11).
5. `worktrees_removed` is the sorted real paths that were registered inside the
   root before step 2 and are gone after step 4. `scratch_removed` is true when
   this reap deleted the root directory, by `rmtree` or by removing a worktree
   that occupied the root (D5).

Only then does #276's proved-file removal delete `scratch.json` with the rows.
Repeating a reap is still a no-op. The record is gone, so the report shows
`worktrees_removed: []` and `scratch_removed: false`.

### Unattributed worktrees

After every launch has been handled, both `--action-id` and `--sweep` list the
repository's worktrees once more. The list excludes:

- the main worktree (the first porcelain entry) and every worktree whose real
  path lies below it, which covers the `.worktrees/` issue worktrees;
- every worktree inside a root named by a valid `scratch.json` anywhere in the
  registry, across all runs.

The remaining real paths, sorted, are `unattributed_worktrees`. They are never
removed, and they do not affect the exit code (D6, parent D8).

The report becomes
`{"reaped": [{"action_id", "scratch_removed", "signalled", "worktrees_removed"}], "skipped": [{"action_id", "reason"}], "unattributed_worktrees": [<path>]}`.
It is canonical, and its lists stay sorted. The exit codes are #276 D6's.
`scratch_not_removed` is one more skip reason and exits 1. A worktree listing
that git cannot produce is a helper error and exits 2 with nothing on stdout.

### Adoption wiring

Every site that #276 D8 gave the `exec` sentence also gets the scratch
sentence, placed right after it. The leaf-agent clauses stay byte-identical,
and the existing test that they never name `launch-scope` stays (D7).

- **Owner** (from-issue's lifecycle identity): "Create every scratch directory
  or scratch worktree under the path that
  `launch-scope scratch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
  prints."
- **Worker** (from-issue **Writing workers**, sdd's lifecycle-worker rule and
  implementer prompt, both `ship-handoff.md` prompts, ship-issue's registered
  children): "Create every scratch directory or scratch worktree under the path
  that `launch-scope scratch --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id>`
  prints."
- **AUTO.md**'s Phase 2–4 prompt list names "the `launch-scope exec` and
  `scratch` sentences that follow it there".
- **Self-reap** prose in from-issue says that the reap also removes the
  launch's scratch root and the worktrees inside it.
- **CLAUDE.md**'s `launch-scope` sentence gains `scratch`, the root's removal
  and `unattributed_worktrees`. The module docstring and the argparse usage
  gain the verb, the record, the report members and the new skip reason.
- **Load ceilings**: each `instruction-load.json` profile whose files grow is
  raised in the same change, with a "Ceiling raised for #277" note (#276 D9).

## Test seams

- **`python -m agent_tools.launch_scope`** in `tests/test_launch_scope.py`,
  using the existing `ScopeHarness`. Each case sets `TMPDIR` to a temp
  directory the test owns, so roots never leak (D8). The cases are:
  - repeat calls print one path, and that path is recorded (AC1);
  - a worker and its owner get the same root;
  - a superseded launch is refused with exit 3, and nothing is created;
  - a missing root is recreated, and a malformed record exits 2;
  - a worktree added inside the root is gone from `git worktree list` and from
    disk after `reap --action-id`, and also after `--sweep` (AC2);
  - a worktree whose directory was already deleted is unregistered, while a
    missing registration outside every root stays registered (D10);
  - a worktree occupying the root itself reports `scratch_removed: true`;
  - a failed removal names the operation, path and cause on stderr (D11);
  - a failed record publication leaves neither a root nor a temporary record (D11);
  - a worktree in an unrelated temp directory appears in
    `unattributed_worktrees` and still exists, while a worktree below the main
    checkout and one inside a live launch's root are not listed (AC3);
  - a repeat reap reports `[]` and `false`;
  - a removal failure skips the launch with `scratch_not_removed`. This uses
    an in-process patch, which follows #276 D12.

  On darwin the temp directory sits behind `/var`, a symlink to
  `/private/var`, so the normalization cases run for real.
- **`test_workflow_skill_contracts.py`**: `assert_ordered` puts each scratch
  sentence right after its `exec` sentence at every #276 site, and
  `test_claude_md_describes_launch_scope` gains the scratch anchors. AC4 runs
  under `just agent-workflow-tests`.
- **`tests/test_agent_tools_launchers.py`** and `just build` are unchanged
  seams. They cover no new row.

## Out of scope

- Deleting any unattributed worktree. That includes `issue262-accept/base`,
  the scratchpad worktrees and any other existing leftover (parent D8).
- Reaping issue worktrees, or any ledger or `workflow-state` change.
- Scratch roots for anything other than a launch: per run, per worker or
  per-call roots.
- Guard changes (S4), Codex parity (parent D12), and settings allowlisting.
- Cleaning registrations of other repositories whose worktrees sit inside a
  root. `rmtree` deletes their files, and their own `prune` drops the
  registration.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | One scratch root per launch, shared by the owner and its workers. `scratch` takes `--action-id` or `--worker-id`, exactly one, and a worker reaches its owner's root through the `:w<n>` derivation | Parent D2 (the registry is per launch); #276 D2 | A per-worker root multiplies records and reap work, and workers already belong to their launch's reap (parent D6) |
| D2 | `scratch` checks liveness first, and refuses with exit 3 and `{"action_id","created":false,"reason"}` using `exec`'s reasons. A refusal creates and deletes nothing. A supersession between the check and the create, or a recreate that lands while a reap removes the root, leaves a root that only a later sweep, if one runs, reaps. That is an accepted residual | #222 D12 and #276 D4 fence vocabulary. Parent D11 accepts the check-then-act window. A directory runs nothing, so #276 D5's row-before-check reason does not apply | Recording before the check and undoing on refusal could delete a root that a live owner received from a concurrent call. No check at all hands superseded agents fresh roots that nothing sweeps after `finalize` |
| D3 | The record is `scratch.json` in the launch directory, created exclusively (`link` of a temp file). The loser of a creation race removes its own empty `mkdtemp` directory. Success prints the bare real path, not JSON | Parent D2's `{"path"}` record; the-bar token economy (the path is used directly in `$(…)`) | Overwriting a record lets two concurrent first calls hand out different roots. JSON output costs every caller a parse |
| D4 | The record is valid only when its path is absolute, equal to its real path, and its basename is `launch-scope-[a-z0-9_]+`. Validity never depends on the reader's `TMPDIR`. A missing root is recreated at its recorded path. A malformed record, or a path that is not a real directory, exits 2 for `scratch` and skips with `scratch_not_removed` for reap | Defense in depth before an `rmtree`. Probed 2026-10-07: `mkdtemp` returns `/var/folders/…` while git records `/private/var/…`, and an owner and the sweep can see different `TMPDIR`s. The-bar fail loud | Checking against `gettempdir()` would refuse the owner's root inside a sweep with another `TMPDIR`. Replacing a vanished root with a new one breaks the "same path on repeat" contract |
| D5 | Reap removes the scratch only after the round is clean, before the proved-file removal. It removes inside worktrees with `remove --force --force` (the main worktree never), rmtrees the root, prunes, and verifies by listing again. Any failure skips with `scratch_not_removed` (exit 1) and keeps the record for the next reap. `worktrees_removed` is a sorted list of real paths, from the before and after listings. `scratch_removed` means this reap deleted the directory | Parent D8, the issue's force-remove-then-prune order, #276 D6 and D16. Probed: `worktree remove` on a missing directory fails with 128 and `prune` drops it | Removing the scratch before the processes die races commands still writing into it. Reporting a count hides which trees went. Deleting the record on a failed removal loses the root for good |
| D6 | `unattributed_worktrees` is every registered worktree that is not the main worktree, not below the main worktree, and not inside any valid recorded root across all runs. It is reported on every reap, never removed, and never affects the exit code | #276 D1 (unattributed must not flag every issue worktree); parent D8; the live list (2026-10-07) holds `.worktrees/*`, scratchpad trees and `issue262-accept/base` | Reading the configured worktree root needs `resolve-project`, a dependency for a report-only field. Excluding only scratch roots reports the main checkout and every issue worktree as leaks. Making leftovers exit non-zero turns every sweep red over a tree the user chose to keep |
| D7 | Adoption is one scratch sentence placed right after each #276 `exec` sentence. The leaf-agent clauses stay byte-identical. Issue AC4 ("the leaf clause routes scratch") is met by these lifecycle-identity sentences, as #276 D8 met its "leaf clause names `exec`" criterion | #276 D8; parent D7; `test_dispatch_contracts.py` verbatim-once contract | Editing the leaf clauses spends tokens in every reviewer prompt and agent definition, none of which ever holds a lifecycle identity |
| D8 | Tests drive real `git worktree` operations with `TMPDIR` pinned to a test-owned directory. Only the removal-failure branch is patched in process | #276 D10 and D12 precedent; the-bar tests that can fail | Mocking git cannot catch the `/var` and `/private/var` mismatch that the issue names |
| D9 | Plan-level edge rules. `scratch` calls `require_supported_platform` first and exits 2 on an unsupported platform, as `exec` and `reap` do. A registration inside the root whose directory is gone and that `prune` keeps (a locked one) fails the step as `scratch_not_removed`, and nothing unlocks it | No reap can run where `scratch` would hand out a root, and parent D8 forbids removing anything reap cannot account for; the-bar fail loud | Handing out roots on a platform reap refuses leaks every one. Running `git worktree unlock` overrides a lock someone set on purpose |
| D10 | Reverses D5's prune and D9's locked-registration rule. Reap never runs a repository-wide `git worktree prune`; it runs `git worktree remove --force --force` on every registration inside the root, present or missing, locked or not, and re-lists to verify | Codex plan review PR277-01: prune drops every prunable registration, including missing ones outside every root, which parent D8 says reap only reports. Git 2.51 removes a missing, locked registration under double force (checked locally) | Keeping the prune deletes registrations reap cannot account for. Leaving locked missing registrations as a permanent skip strands the launch when the lock sits inside the launch's own root |
| D11 | Failure paths keep evidence and leak nothing: `scratch` removes its freshly made root and temporary record on every failure before the record is published; reap's scratch step names each failed operation, its path and its cause on stderr while keeping the D5 report and exit code | Codex plan review PR277-02 and PR277-04; the-bar diagnostics rule | Cleaning up only on `FileExistsError` leaks an unrecorded root no reap can find; a bare `scratch_not_removed` hides which path failed and why |
