# Adopt and register nix-config — issue 149

Design for [#149](https://github.com/fagenorn/nix-config/issues/149), 2026-09-24. Base
`origin/main` `2c368486`. Parent #121 (Tasks 7–8 are the boundary). The engine landed
through #148, whose spec (`.claude/specs/2026-09-24-issue-148-adoption-plan-apply-verify-design.md`,
cited "#148 Dn") carries the digest of every #121 ID cited here ("#121 Dn"). The retained
#121 Task 7 and Task 8 plans on `worktree-issue-121-adoption-v1` are read-only evidence.
This spec and its plan live under `.claude/` and are themselves relocated by the adoption
they describe. The legacy paths they cite are point-in-time and are not rewritten.

## Problem

The adoption engine is on `main`, but nix-config itself is not adopted. Its specs, plans
and rejections still sit in the legacy `.claude/specs`, `.claude/plans` and `.out-of-scope`
trees. The contract still points at those trees. There is no evidence record and no
path-migration map, and the fleet registry does not exist. Until the real adoption lands
on `main` and is registered, `platform-status --fleet` shows an empty fleet, and #71's
serialized adoption stages cannot start.

Three things make this more than running `plan` and `apply`:

- The deployed runtime (`~/.agents`, generation of 2026-09-24 11:51) has no
  `adopt-project` and no `adopt_*` libraries. Registration needs an operator
  `just switch`, and the agent never runs one.
- The apply relocates this run's own spec and plan, and the tracker issue must stay open
  until registration evidence exists. The ship flow's `Closes #N` and its Phase-8 close
  would otherwise end the issue at merge.
- `main` keeps moving while sibling issues land specs and plans under `.claude/`. On this
  machine `merge.directoryRenames=true` is set, so a sync silently moves such a file into
  the renamed tree. The file then sits outside the permanent map, and nothing reports it.

## Solution

Hand-authored work comes first, in the `sdd` loop. The adoption and registration follow as
owner delivery steps outside that loop (#121 D32). The loop re-reads the plan at its
pre-move path after every task, so it cannot run past a commit that moves the plan. The
adoption commit is the branch's last authored commit, and only sync merges may follow it
(D3).

### Probe results (read-only, scratch clone of `2c368486`, scratch `HOME`)

- `plan` returns `state: ready`, `outcome: reconcile` and `decisions.open: []`. Two runs
  give byte-identical stdout. There are 251 operations: 244 `git-mv` (164 plans, 77 specs,
  3 rejections, exactly `git ls-files` of the three trees), 5 `write-file` and 2
  `regenerate-projection`. No operation is destructive, and none is `delete-file`.
- `apply` (with the verification commands stubbed) makes one commit: 244 `R100`, 3 `A`
  (sentinel, map and record) and 2 `M` (`.agents/project.json` and `.gitignore`). The
  projections regenerate to identical bytes. On the branch, `verify` reports `adopted`,
  and `verify --register` exits 2 because the commit is not reachable from `main`.
- Then a legacy-tree file was committed on top of the adopted tree. `verify` still
  reports `adopted`. A new `plan` proposes an incremental adoption: 1 `git-mv`, a
  `delete-file` of the first evidence record, a second map and a second record.
- `just agent-workflow-tests` includes `test_installed_policy_surface_matches_source_contract`,
  which compares the installed `~/.agents/skills` with the source. That test fails on
  today's `main` under the real `HOME`, because the 11:51 generation lags `main`. It also
  fails under any scratch `HOME`. So the apply's own commit gate can pass only after an
  operator `just switch`, and a scratch-`HOME` rehearsal of the real gates cannot pass.
- The suite with that test skipped (`WORKFLOW_POLICY_SURFACE=source`, as CI runs it),
  on the adopted probe tree with the real contract: 1,222 tests OK, 2 skipped. A
  real-gates apply probe, stopped once the test above made it moot, had already passed
  `just build` inside the adopted apply worktree. The gate stops at the first failing
  command, and the tests had started. No gate-forced fix is therefore planned (D10).

### Owner procedure

**Stage A: `sdd` plan tasks.** These are hand-authored and precede any tool output.

- A1 re-points the living references (D4). This is the only planned product change.
- No gate-forced fix is planned. If the real apply's gate fails anyway, the fix is a
  new task here (D10).

**Stage B: owner delivery steps, in order (cited B1–B9).** None of them is an `sdd` task. Steps 1–7
belong to the issue owner in Phase 6, after the loop finishes and while the attempt is
still `active`. Steps 8–9 belong to the ship owner.

1. **Fresh base.** Sync `origin/main` into the branch under ship-issue's `SYNC.md` rules.
   The tree must be clean, and `just build` must succeed.
2. **Operator gate (D1).** Compare the deployed runtime with step 1's built generation.
   If they differ, run `workflow-state suspend --blocked-on human_gate`, ask for
   `just switch`, and stop. On resume, restart at step 1. Once the gate passes,
   `just agent-workflow-tests` must be green on the head under the real `HOME`. A later
   gate failure is then attributable to the adoption.
3. **Plan.** Run `adopt-project plan --repo-root <worktree>` twice and require
   byte-identical stdout. Assert `ready`, `reconcile`, `decisions.open == []`, and no
   `needs-decision`, `archive-history` or `delete-exact-duplicate` evidence action. Assert
   no destructive or `delete-file` operation. The `git-mv` source set must equal
   `git ls-files -- .claude/specs .claude/plans .out-of-scope`. Only live values are
   asserted, never the probe's counts.
4. **Apply.** Run `adopt-project apply --plan-id <id>` with the deployed runtime under the
   real `HOME` (D2). Never pass `--acknowledge-deletions`. If a commit gate fails, the
   retained evidence names the failed gate but not its output. Rerun that command in the
   retained worktree to see the output, then apply D10. Never rerun against a stale
   id, and never delete the retained worktree to get past the guard.
5. **Land on the branch.** Run `git merge --ff-only adopt-<12 hex>`, then
   `git branch -d adopt-<12 hex>`.
6. **Typed-operation review (D9).** A machine reconciliation plus a read-through. Either
   one failing blocks the push.
7. **Pre-push verification (D9).** The freshness check (D5) runs here as well.
8. **Ship.** Hand off to the `ship-issue` subagent. The spec and plan are named at their
   relocated paths (D7). The handoff's bounded `notes` point the ship owner to D5 and
   D6 (D11). Those are the non-closing PR reference, the freshness check after ship's
   sync and immediately before `gh pr merge`, and B9.
9. **Registration (D6).** The ship owner runs this after `pr_merged` and before the
   `close_tracker` cycle, against the primary checkout: first the Task-8 steps, then the
   evidence comment, then the close.

### Requirements and acceptance criteria

| AC | Requirement | Evidence |
|---|---|---|
| 1: fresh plan `ready`, no open question id | B3 on a head freshly synced with `origin/main`, repeated after any D5 re-derivation | `plan` stdout, twice, byte-identical; `decisions.open == []` |
| 2: single plan-specified commit, history kept, no copy | B4–B5 with the deployed runtime. The commit is tool-produced, carries no hand edit, and is the only commit between its base and `adopt-<12 hex>` | D9 checks 1–5 |
| 3: complete diff reviewed against the typed operations; verification and conformance gates | B6–B7 | D9: the reconciliation, the read-through, `just build`, `just agent-workflow-tests`, `conformance --purpose adoption`, and `verify --register` refusing |
| 4: registration only after integration; entry names the integrated commit | B9 against the primary checkout's local `main`, after `pr_merged` | ancestry check exit 0; `verify.adoption_commit` equals the commit that added the record and the reconciled commit |
| 5: `platform-status` and fleet preflight report registered and compatible from the deployed runtime | B9 with the D1-checked runtime | `platform-status --fleet` row with `compatible: true`, `reason_code: null`, `repair_id: null` |

## Decisions

### Operator gate (D1, D2)

The gate compares eleven deployed files with the same relative paths in the head's
built generation. That generation is the `home-manager-files` tree in the closure of
step 1's `just build` (#147 D9). Comparing against the built generation rather than
the sources stays correct if a helper later becomes a package launcher. The files are
`adopt-project`, `resolve-project`, `conformance`, `conformance-registry`,
`conformance-checks`, `agent_platform.py`, the four `adopt_*.py` libraries and
`platform-manifest.json`. Each file is followed through its store symlink and must be
byte-identical. A missing or differing file fails the gate, and the failure message
names every such file. The gate sits before the apply. At that point the attempt is still
`active`, so `workflow-state suspend` is legal, and nothing tool-produced exists yet that
could go stale during the wait. The suspension notice asks the operator to run
`just switch` on `main` at or after the head's merge-base, and it names the eleven
files. The switch is needed before the apply, and not only before registration: the
apply's `agent-workflow-tests` commit gate runs under the real `HOME`, and its
installed-surface test fails while the generation lags `main`. After the gate passes,
one runtime plans, applies, verifies and registers. At
registration (B9) the same comparison runs against a build of the merge commit. A
mismatch there stops before the close (D6).

### Freshness (D5)

The plan binds `base_revision`. Pushed commits cannot be rewritten, because the guard
allows only `git push [-u] origin <branch>`. A stale adoption therefore has to be caught
while it is still local.

- **Stale** means that, after a `git fetch`,
  `git log --format= --name-status --no-renames ADOPT^..origin/main` shows an `A` or `D`
  under `.claude/specs`, `.claude/plans` or `.out-of-scope`. Such a
  change would put a legacy artifact on `main` that the map does not cover, or would
  collide with a move. A sibling's edit (`M`) to a moved file merges onto the renamed
  path and leaves the map complete, so it is not stale. Git's rename handling does not
  replace this check: the machine's config relocates a new file silently, and git's
  default only raises a conflict that a resolver could "fix" by hand. The range starts
  at the adoption's base, so a stale commit is still caught after a sync has already
  merged it.
- **Before push:** discard the local adoption commit, and any commit after it, with
  `git reset --hard <pre-adoption head>`. Nothing is lost remotely, and no force-push is
  needed. Then sync, re-plan, re-apply and review again.
- A non-stale advance is an ordinary sync merge after the adoption commit. The adoption
  stays one commit, and B7's checks run again on the merged head.
- **After push:** never merge a stale adoption. Never relocate the new file by hand, and
  never apply the engine's incremental plan: it needs `--acknowledge-deletions` and
  produces a second adoption commit. The ship owner stops before `gh pr merge`, names the
  stale paths and leaves the issue open. Recovery needs an authorization the agent does
  not hold, either a force-push of a re-derived commit or an acknowledged incremental
  adoption, and it belongs to the operator.
- **Check points:** before the push (B7), after ship's sync, and immediately before
  `gh pr merge`. B1's sync makes the base fresh before the apply.

### Typed-operation review and pre-merge verification (D9)

Let `BASE` be the apply's base and `ADOPT` the adoption commit. All comparisons are over
complete sets parsed from `-z` output. No display, sample or `--stat` counts.

1. **Shape.** `git rev-list --count BASE..ADOPT` is 1. The message is the D28 fixed
   subject with no trailer. The commit carries an SSH `gpgsig` header. After the push,
   and before the merge, GitHub reports `verification.verified: true` for it. A local
   `git verify-commit` is not used, because this machine configures no
   `gpg.ssh.allowedSignersFile`.
2. **Every path claimed exactly once.** Take `git diff-tree -r -M100% --name-status -z`.
   Its `R100` pairs equal the `git-mv` (source, target) pairs, which equal the map's
   `moves`, old and new path. Its `A` set equals the `write-file` targets whose `before`
   is null. Its `M` set equals the `write-file` targets with a non-null `before`, plus
   any projection target whose bytes changed. There is no `D` and no rename below 100%.
   The union covers every changed path, and no path is claimed twice.
3. **Content.** The sha256 of each `write-file` target at `ADOPT` equals that operation's
   `after`. `projections-in-sync` passes.
4. **History.** `git log --follow` prints more than one commit for every moved path.
5. **No copy.** `git ls-tree -r ADOPT -- .claude/specs .claude/plans .out-of-scope` is
   empty. Exactly one record exists under `.agents/artifacts/evidence/`, and it names the
   map.
6. **Read-through.** A reviewer reads the non-rename hunks against their operations: the
   contract amendment, the sentinel's `*\n`, the `.gitignore` change, the map and the
   record. The reviewer also reads A1's re-pointed references and checks that each one
   resolves at the adopted head. `git grep` of the living tree, excluding the moved trees,
   test fixtures and the engine classifier, names no legacy path.
7. **Gates at the head to be pushed.** `just build` and `just agent-workflow-tests` pass.
   `verify` reports `adopted`. `verify --register` exits 2 with `not_integrated`. It runs
   under a scratch `HOME` whose `bin`, `lib` and `share` link to the deployed runtime and
   whose state is private, so a pre-merge check can never register the worktree's root.
   The real `~/.agents/state/fleet/` is byte-identical before and after, or absent in
   both.
   `conformance run --purpose adoption --repo-root <worktree> --offline` reports `passed`,
   and `validate-report` accepts it. `platform-status` reports `compatible: true`.

Checks 1–5 run as one uncommitted driver under `$TMPDIR`, the same pattern as #148 D4.
Nothing is added to the package. In the probe the whole `-M100%` diff was about 137 KB,
and its largest file was the 47.5 KB map. `review-package` measures it before ship's
review. A package over policy is reported as a gap, and the adoption commit is never
split to fit.

### Registration and closure (D6)

The ship flow's Phase 4 PR body replaces `Closes #149` with `Part of
https://github.com/fagenorn/nix-config/issues/149`, and no commit message on the branch
carries a closing keyword. The PR's base is the default branch, so either keyword would
close the issue at merge.

After the merge cycle's `pr_merged` observation, and before the `close_tracker`
proposal, the ship owner (D11) does the following against `/Users/anis/tmp/nix-config`:

1. Fast-forward its local `main` to the merged `origin/main` with `--ff-only`. #121 D19
   reads local `main`. A dirty checkout, one that is not on `main`, or a diverged one
   stops the run and is never forced.
2. Run the D1 comparison against a build of the merge commit.
3. Run Task 8's steps unchanged. The ancestry check comes first. Exactly one evidence
   record must be found, and it must have been introduced by the adoption commit. Save
   the registry bytes. Run `verify`, which must report `adopted`. Run `verify --register`
   and require exit 0. Assert the `{project_id, root}` entry and that every earlier
   entry is kept. Run it a second time and require byte-identical registry bytes. Run
   `platform-status --fleet` and require the row `compatible: true`. Run
   `conformance --purpose adoption` on the primary checkout.
4. Post one comment on the issue, under the delivery loop's `current-launch` fence. It
   carries each command's verbatim output, the adoption commit and the merge commit.
5. Only then run the `close_tracker` cycle.

Any failure stops the run before the close. The issue stays open, and the run returns a
truthful terminal row with the partial evidence.

### Naming the relocated run artifacts (D7)

Before the apply, the spec and plan are named by their `.claude/` paths. From B5 on,
every consumer names them at the new path the migration map gives for the old one. That
covers the review prompt, the ship handoff's `spec_artifact` and `plan_artifact`,
`diff-scope --artifact-path`, the PR body and `acceptance_ref`. No copy is ever left at
an old path.

### Siblings in flight (D8)

After the adoption merges, a sibling's next sync moves any new spec or plan it holds
into `.agents/artifacts/{specs,plans}`. On this machine that happens silently. Under
git's default it is a file-location conflict whose suggested path is the same. The file
never existed on `main` at the old path, so its absence from the map is correct. The
sibling names its artifacts by the post-sync path, by D7's rule. If a sibling's tooling
refuses that, it is a lifecycle gap and becomes a new issue (#71). This slice adds no
alias, copy or engine switch. There is a residual risk. A forge-side merge that leaves a
sibling's file at an old path puts a legacy path back on `main`, and `verify` reports
`adopted` over it, as the probe showed. That blindness is an engine gap, recorded for a
new issue and not patched here.

## Test seams

- The installed CLIs (`adopt-project`, `resolve-project`, `conformance`) as
  subprocesses. The real run uses the deployed runtime (D2). Probes and rehearsals use a
  scratch `HOME` against a scratch clone, never the worktree (#148 D4).
- Git plumbing as the review oracle: `diff-tree -M100% -z`, `ls-tree`, `log --follow`
  and `merge-base --is-ancestor`. GitHub's commit `verification` field is the oracle for
  the signature.
- The contract's verification commands `nix-build` and `agent-workflow-tests`.
- The fleet registry, read only through its bytes and `platform-status --fleet`.

No test is added. The engine's own suites already cover its behaviour, and this slice
changes no code path.

## Out of scope

- Any change to `adopt-project`, its libraries, `resolve-project` or the classifier. A
  contract or engine gap becomes a new issue (#71).
- Running `just switch`, force-pushing, `--acknowledge-deletions`, and any incremental
  or second adoption.
- Registry-backed conformance `fleet` checks, and converging `verify` onto the
  conformance engine (#148 D6, D7).
- Rewriting point-in-time records, test fixtures that name synthetic `.claude/` paths,
  or the eval fixture repository's contract.
- The retained #121 branch and worktree, which stay read-only. Codex/Claude smoke
  evidence and later #71 stages.
- Changes to `ship-issue`, `workflow-state` or the delivery-loop stage order.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The operator gate runs before the apply while the attempt is `active`. It compares eleven deployed files by name, byte for byte, with the head's built generation and suspends `blocked_on=human_gate` on any gap. The same comparison runs again against a build of the merge commit at registration. The agent never runs `just switch`. | #148 D8; CLAUDE.md "switch only when asked"; retained Task 8 (every library by name, "a stale generation registers a stale answer"); `workflow-state suspend` accepts only an active attempt; the probe found the runtime without `adopt-project`, and found that the apply's own `agent-workflow-tests` gate fails against a lagging generation | A post-merge suspension: a handed-off attempt cannot suspend, so a missing runtime could only end the attempt. Gating at push after a staging apply: two engine runs, and the wait stales the applied commit. A presence-only check: it admits a skewed library. |
| D2 | Plan, apply, verify and register all use the deployed runtime under the real `HOME`, so plans and apply worktrees live in the real `~/.agents/state/adopt/`. | #121 D14 (user-scope state); D1 makes the runtime current before the apply | Retained Task 7's staging `HOME`, which existed only because nothing was deployed. It needs a `GIT_CONFIG_GLOBAL` override to keep signing, and it plans with a runtime other than the one that registers. |
| D3 | Hand-authored commits (`sdd` tasks) come first. The tool-produced adoption commit is the branch's last authored commit, and only sync merges may follow it. Everything from the operator gate on is an owner delivery step. | #121 D32 (the loop cannot run past a commit that moves its plan); `plan_id` covers the CLAUDE.md fingerprint; the apply requires a clean tree | Adopting mid-branch: later tasks cannot be reviewed from a relocated plan. Adopting first: every hand commit reruns against a moved base. |
| D4 | A1 re-points the eight living references in four files to the classifier's deterministic new paths, in one pre-adoption commit. The files are CLAUDE.md (1), `docs/standards/agent-helpers.md` (5), the agent-skills README (1) and `HUMAN-GATE.md` (1). The README row describes every project's convention, so it names the binding `bindings.paths.rejections`, as its neighbouring rows do, and not nix-config's path. D9 check 6 proves the references resolve after the apply. | #72 (living docs change in the same project change); the bar's *Moves keep their history*; #121 D28 and D30 (the tool commit carries no hand edit, and its sweep is closed); AC2 | Editing inside the adoption commit: it would no longer be the plan-specified commit. Re-pointing after the adoption: outside `sdd` review and re-authored on every D5 re-derivation. Leaving them: dangling links on `main`. Widening the sweep: an engine change. |
| D5 | Stale means `ADOPT^..origin/main` adds or deletes a path under the three legacy trees. Before push, drop the local adoption and re-derive it on the synced head. A non-stale advance syncs normally. After push, never merge, patch or incrementally re-adopt: stop before merge and leave recovery to the operator. The check runs before push, after ship's sync and immediately before merge. | The probe: `merge.directoryRenames=true` relocates silently, and the incremental plan adds `delete-file` plus a second commit; #72 (one commit, complete map); the push guard forbids force-push | Trusting git conflicts, which never fire here. Merging main and moving the file by hand, which leaves the map incomplete. The engine's incremental adoption, which is a destructive self-approval and a second migration. |
| D6 | The PR body references #149 without a closing keyword. Registration against the primary checkout runs after `pr_merged` and before `close_tracker`, and its verbatim output is posted as one issue comment. A failure leaves the issue open, with a truthful stop. | AC4 and AC5; the bar's *Truthful terminal states*; ship-issue (a default-branch base auto-closes); #121 D19 (local `main` ancestry); retained Task 8 | `Closes #149`, which closes before registration. Registering after the close, which records ACs as met while they are unmet. Registering from the worktree, whose root is removed at cleanup. |
| D7 | From the ff-merge on, the run's spec and plan are named at their map-given relocated paths everywhere: review, handoff, `diff-scope`, PR body, `acceptance_ref`. | #72 (no compatibility copy); #121 D34 (the map is the authority); AC2 | Old paths in the handoff, which name files absent at the shipped head. A copy at the old path, which is forbidden. |
| D8 | Sibling fallout is documented, not engineered. A sibling's post-merge sync relocates its new artifacts, which are correctly absent from the map, and it names them by D7's rule. A refusal becomes a new issue. | #71 (gaps rewind, no local workaround); the probe of both git modes | An alias, copy or engine switch for old paths. Holding sibling merges, which is not this issue's authority. |
| D9 | The typed-operation review is a complete-set machine reconciliation (every changed path claimed by exactly one operation, content digests, one signed commit, `--follow` history for every move, no copy) plus a read-through of the non-rename hunks. It is followed by build, workflow tests, `verify` = `adopted`, a `verify --register` refusal that leaves the registry untouched, and `conformance --purpose adoption` passing. The driver is uncommitted. | AC3; retained Task 7's post-apply checks; #148 D4 and D5; the bar's *Verify before claiming done* | Sampling, or `git show --stat`, which prints no rename status. A committed reconciliation tool, which is new package surface nobody asked for. |
| D10 | No gate-forced fix is planned, because the adopted probe tree passes the suite and the build. If a real commit gate fails, the owner goes back to Phase 6's loop. The fix is a new plan task at the cause, with its failing case in the owning suite, reviewed like any task. Stage B then restarts at step 1 and yields a new `plan_id`. A defect in the engine stops the run and becomes a new issue. | Retained Task 7 ("fix the cause in the source ... then re-run plan"); from-issue ("back up to that phase"); #71; the bar's *Root causes* | A fix inside or after the adoption commit, which is no longer plan-specified and is unreviewed. A local engine patch, which #71 forbids. Pre-emptive test edits for failures the probe did not show (YAGNI). |
| D11 | The #149-specific ship duties reach the ship owner through the handoff's bounded `notes`, which point at D5 and D6. The duties are the non-closing reference, the freshness stop and registration before the close. Neither `ship-issue` nor the delivery-loop stage order changes. If the ship owner cannot perform a duty inside its loop, it stops before the affected effect with the issue open, and the missing post-integration stage becomes a lifecycle issue (#71). | from-issue Phase 7 dispatches `ship-issue` as a separate subagent; the loop's fixed stages go from `merge_pr` straight to `close_tracker`, and nothing sits between them; the handoff carries `notes` | Registering after the ship returns, which closes the issue before the evidence exists. Editing `ship-issue` or adding a stage here, which is a lifecycle change outside #121 Tasks 7–8. |
