# Superseded-launch forge-write guard — design

Issue: https://github.com/fagenorn/nix-config/issues/132

## Problem

The lifecycle ledger reserves **one worktree per issue** and deliberately hands
that same worktree and branch to the successor attempt. Nothing excludes the
still-running predecessor from writing there. Two supersession shapes produce a
live predecessor:

- a `retry` opens attempt N+1 on the recorded worktree, and
- a `resume` appends a launch to the *same* attempt (an owner-unavailable
  takeover, or the auto-resume of an attempt the reaper demoted to
  `suspended(unknown)`), silently re-legitimising whatever process is still
  running under it.

`control` has no action kind that stops a launch, and the dispatcher keeps the
host task handle only for notification correlation. So supersession is a ledger
fact that never reaches the superseded process.

The exposure is the shipping window. Phase 7 runs as a fresh ship subagent
between from-issue's Phase-6 and Phase-7 `workflow-state progress` calls, and in
that whole window — sync, push, PR, review, CI wait, merge — there is **zero
ledger contact**. A stale owner learns it is stale only after the merge, when
`progress --phase 7` is refused. Two things compound it:

- ship-issue's Phase-6 tip check compares the PR head to the *live local*
  `git rev-parse HEAD`. Both attempts share one checkout, so local HEAD already
  contains the successor's commits, and the prescribed remedy on divergence
  ("re-push first") would make the predecessor push the successor's unreviewed
  work itself.
- the merge is an unpinned `--merge --delete-branch`, and the permission guard
  validates command shape and repository state, never lifecycle identity.

The harmful interleaving: attempt 1's ship owner reviews `BASE_SHA..HEAD_SHA` and
starts the CI watch; attempt 2 pushes more onto the shared branch; CI re-runs on
the new head and goes green; attempt 1 merges a head nobody reviewed, while the
ship summary truthfully reports the merge SHA and the review record truthfully
cites the earlier `HEAD_SHA`. That this has come out right so far is sequencing
luck.

## Solution

Give the owner a way to ask the ledger, cheaply and without writing, whether it
is still the launch the ledger entitles — and make ship-issue ask immediately
before every forge write it makes up to and including the merge.

1. A new **read-only** `workflow-state check-launch` verb answers whether one
   `issue:attempt:launch` identity is the current launch of the latest attempt
   for that issue. It takes no clock, holds no lock, creates nothing and writes
   nothing.
2. ship-issue calls it immediately before each pre-merge forge write and
   proceeds only on `current: true`. Every other outcome — a negative answer, a
   non-zero exit, an absent helper, unparseable output — refuses the write.
3. The from-issue ship handoff carries the launch-level `action_id` so the query
   is answerable, joining the handoff's existing all-or-nothing lifecycle group.
4. A refusal is a **stop that writes nothing anywhere**: no forge write, no
   ledger write, no cleanup — the successor is working in that same worktree on
   that same branch.
5. ship-issue's Phase-6 tip check compares the PR head to the reviewed
   `HEAD_SHA`, and divergence is escalated as unreviewed commits on the branch,
   never resolved by re-pushing.

## Decisions

### The query: `workflow-state check-launch`

Exact argv — three flags, no clock:

```text
~/.agents/bin/workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <issue:attempt:launch>
```

All three are required. `--action-id` is the single opaque `issue:attempt:launch`
string the acquisition envelope already issued (per D2); the verb parses it
itself, so there is no `--issue`.

**Exit 0 — an answer.** One canonical JSON object on stdout via the existing
`print_json` (sorted keys, `(",", ":")` separators, trailing newline), exactly
four keys:

```json
{"action_id":"<the echoed argument>","current":<bool>,"current_action_id":"<action id or null>","reason":"<closed-set string>"}
```

- `current_action_id` — the identity the ledger currently entitles: rendered from
  the latest attempt when that attempt's state is `active`, and `null` otherwise
  (no attempts, or the latest attempt is `handed_off`/`suspended`/`stopped`/
  `failed`/`merged` — none of those has a live launch).
- `current` — the discriminator the caller reads. The invariant, asserted in the
  suite, is `current == (current_action_id is not None and action_id ==
  current_action_id)`. It is deliberately redundant with the other two fields:
  a model comparing two strings is a failure site, a model reading one boolean
  is not (the-bar, *Token economy*).
- `reason` — always present, one of a closed set, evaluated in this exact
  precedence so the classification is deterministic:

  | # | Condition | `reason` |
  |---|-----------|----------|
  | 1 | no `state.json` under `<repo-root>/.superpowers/workflows/<run-id>/` | `unknown_run` |
  | 2 | the ledger has no entry for that issue, or the entry has no attempts | `unknown_issue` |
  | 3 | the attempt ordinal exceeds the recorded attempt count | `unknown_attempt` |
  | 4 | the attempt ordinal names a real but not the latest attempt | `superseded_attempt` |
  | 5 | it is the latest attempt, but its state is not `active` | `inactive_attempt` |
  | 6 | latest and active, but the launch ordinal is not the latest launch | `superseded_launch` |
  | 7 | otherwise | `current` |

  `current` is `true` only at row 7. Rows 4 and 6 are the two supersession
  shapes the issue names; keeping them distinct is what lets each test in the
  suite fail for exactly one reason (the-bar, *Tests that can fail*).

**Terminology.** "Superseded" already has a narrower meaning in this ledger:
`result_source: "superseded"` marks an attempt record that a *forge observation*
reconciled. The `reason` values here mean something different — a *launch* that a
newer launch or attempt displaced — and the two never appear in the same field.
The issue's own vocabulary is "a predecessor whose attempt was superseded", so the
`reason` names follow it rather than inventing a third word; this paragraph is
where the two senses are pinned, since the repository has no glossary file.

**Exit 2 — no answer.** The existing `main()` handler prints
`workflow-state: <message>` to stderr and returns 2 for every `WorkflowError`
and `OSError`; argparse failures exit 2 too. Nothing new is added to that path.

The verb's precedence table has no default fall-through: row 7 is reached only
when rows 1-6 are all false, and the state-classification step dispatches over
`ATTEMPT_STATES` as a closed set (the-bar, *Fail loud*).

### Read-only, by construction

`transact` cannot be used, and neither can `workflow_paths`: between them they
create `.superpowers/`, `.superpowers/workflows/`, the run directory, the
`workflows/.gitignore` file and `state.lock`, and they persist whenever the
mutation reports `changed`. `check-launch` therefore resolves its own path:

1. `resolve_repo_root(--repo-root)` — the existing validator, which only stats
   and resolves and never creates.
2. `RUN_ID_PATTERN` on `--run-id` directly, not via `workflow_paths`.
3. `state_path = <repo-root>/.superpowers/workflows/<run-id>/state.json`, probed
   with `require_regular_path(..., allow_missing=True)`.
4. On a present file, `read_locked_state(state_path, run_id)` — despite its name
   that function takes no lock; it opens `O_RDONLY|O_NOFOLLOW`, decodes, and
   returns `validate_state(upgrade_state(value))`. Reusing it gives the query
   byte-identical validation and prior-schema upgrade semantics to every writer
   (the-bar, *DRY*). `upgrade_state` fills the prior-schema fields **in memory
   only**; nothing persists them.

No lock is taken. `atomic_write_state` publishes by `os.replace`, so a reader
sees either the complete prior file or the complete new one, never a torn one;
taking the lock would mean creating `state.lock`, which is a write. The
implementation carries one comment saying exactly that — the code already says
what it does, the comment says why (the-bar, *Maintainability over cleverness*).

The verb takes **no `--now`** (per D4). It therefore cannot evaluate a deadline,
cannot call `demote_expired_attempt`, and structurally cannot persist a reaper
demotion. The reaper runs only inside `control` and `direct-owner` today; this
verb keeps it that way. The visible consequence, stated so nobody reads it as a
bug: an attempt whose deadline has passed but which no `control` sweep has yet
visited still answers `current`, because no successor launch exists yet. Expiry
accounting is #133's and lease fencing is #125's; this verb reports the ledger
as written.

### What is an answer and what is an error

The rule, and the reason the distinction is not hand-waving even though the
caller refuses the write either way:

> A **positive** answer requires evidence. Every absence the ledger can express
> is a well-formed negative. Only an inability to read a valid ledger, or an
> argument that is not a well-formed question, is an error.

| Condition | Outcome |
|-----------|---------|
| `--repo-root` missing, a symlink, or not a directory | exit 2 |
| `--run-id` fails `RUN_ID_PATTERN` | exit 2 |
| `--action-id` is not three `[1-9][0-9]*` components separated by `:` | exit 2 |
| `state.json` absent | exit 0, `unknown_run` |
| `state.json` present but a symlink or not a regular file | exit 2 |
| `state.json` unreadable, not JSON, or fails `validate_state` | exit 2 |
| issue / attempt / launch not found in a valid ledger | exit 0, negative |

A bad repo root or run id means the caller handed over a broken coordinate
system — that is a handoff defect, not a supersession, and it must be loud. A
corrupt ledger reported as "not current" would hide corruption behind a routine
refusal (the-bar, *Truthful terminal states*, *Fail loud*). A *missing* ledger,
by contrast, is a fact the ledger expresses: a run that does not exist entitles
nobody, so no identity is its current launch.

`action_id` rendering exists twice today, identically, in `bootstrap_response`
and `direct_owner_response`. `check-launch` needs the same rendering for
`current_action_id` — a third copy that must change together with the other two.
Extract one render helper and one parse counterpart beside it, and route all
three call sites through the render helper (the-bar, *DRY*: deduplicate when the
copies must change together).

### The ship handoff carries the launch

`artifact_budget.validate_ship_handoff_report` is a **closed** key set —
`_exact_keys` is set equality, so unknown keys and missing keys both fail, and
there is no expressible "optional" key. Adding the field is therefore in scope
and mandatory:

- the boundary's key set gains `action_id`, making it 17 keys;
- `action_id` joins the existing all-or-nothing **lifecycle group**
  (`ledger_repo_root`, `run_id`, `attempt`, `owner`, `owner_worktree`), so it is
  non-null exactly when the rest are. That closed validator is the fail-loud
  site: from-issue physically cannot emit a handoff that carries lifecycle
  identity without the launch;
- the value check is `_string` only. The authoritative `issue:attempt:launch`
  grammar lives in `workflow-state.py`, which renders it and now parses it;
  re-encoding the grammar as a second regex in the validator would give one
  contract two homes. The validator is the outer check (fail fast, useful
  message); `check-launch` is the inner one (correctness). Neither is dropped
  because the other exists (the-bar, *Defense in depth*).

In `ship-handoff.md` the field is appended to the lifecycle run of the candidate
template, immediately after `owner_worktree`, so the documented key order of the
existing group is undisturbed. The accepted spec that recorded that order is a
point-in-time record and is not rewritten.

from-issue's **Lifecycle identity** section gains `action_id` to the identity it
adopts and threads through, and its dispatcher-envelope requirement becomes six
fields rather than five. Both acquisition routes already produce it — the
dispatcher envelope sends `action_id=<action-id>` and the `direct-owner` owner
envelope returns `action_id` — so this names a value that already exists rather
than inventing one. It is the one identity field that changes when the attempt is
relaunched, and it is passed through verbatim, never recomputed.

### The guarded write points

The rule ship-issue states is a single invariant, not an enumeration that can
drift:

> Every write to the forge or to `origin` that ship-issue makes **before the
> merge is verified** is preceded, immediately, by `check-launch`.

Concretely that is the Phase-4 `git push -u origin <branch>`, the Phase-4
`gh pr create`, every push in Phase 5's apply-and-push flow for review findings,
and the Phase-7 merge. Phase 5's fix push is included on purpose: a superseded
predecessor pushing review fixes onto the shared branch is the same harm as the
Phase-4 push, and the issue's three named writes are instances of the rule, not
its definition.

Everything **after** the merge is verified is deliberately unguarded: Phase 7's
`git push origin --delete <branch>`, and Phase 8's `gh issue close`, `git branch
-d` and `git worktree remove`. A check there could only refuse cleanup for a
merge that already landed — stranding a worktree and a branch, and contradicting
Phase 8's existing rule that a post-merge failure is recovered or retried rather
than turned into a pre-merge failure row. Deleting an already-merged branch is
idempotent and harmless. The merge is the point of no return, and the guard sits
immediately before it.

Phase 1's `git merge origin/<integrationBranch>` and Phase 3's local commits are
not forge writes and are not guarded.

The `action_id` the guard passes is the one the handoff carried, verbatim. The
ship owner never recomputes it and never derives it from `attempt`: the launch
ordinal is exactly the part it cannot know.

**Without lifecycle identity the guard is skipped silently.** A standalone
`/ship-issue <num>`, or a handoff whose lifecycle group is all-null, has no
ledger, no attempts and no supersession mechanism, so there is nothing to
consult. This is the same graceful degradation ship-issue already applies to
absent optional bindings, and it is not a hole: the all-or-nothing validator
means the group is never *partially* present.

**That is the only skip, and it is a statement about the invocation, not about
the environment.** Everywhere else this call fails closed rather than degrading.
ship-issue's house rule is to skip an absent optional helper silently and never
hard-fail on it; that rule does not apply here, and the prose says so explicitly,
because an implementer following the house style would degrade the guard into a
no-op precisely when the environment is broken. A missing `workflow-state`, a
non-zero exit, or output that does not parse into the exact four-key object
refuses the write.

### The refusal is a stop, not a suspension

The issue's wording is "abort through the suspension procedure". This design
deliberately does not call `workflow-state suspend`, and the reason is the issue
itself in ledger form:

- in the **retry** shape the predecessor's attempt is no longer `active`, so
  `suspend` is refused (`only an active attempt can suspend`, exit 2);
- in the **resume** shape the attempt *is* `active` — under the successor's
  launch. A `suspend` from the predecessor would park the successor's live
  attempt. A `finish` would terminate it.

A suspension parks an attempt the suspending process still owns. A superseded
launch owns nothing. So the refusal is:

1. do not execute the write;
2. perform no further forge write, no ledger write, and no cleanup — leave the
   worktree, the branch and any PR exactly as they are, because the successor is
   working in that same worktree on that same branch;
3. print the canonical re-entry line, `/from-issue <num> --auto`, on its own
   line — the same line `reentry_command` renders and the suspension procedure
   emits;
4. return a truthful `stopped` ship summary whose notes name the refusal, the
   reported `reason`, this `action_id` and the reported `current_action_id`.

The refusal summary's exact field values, so no implementer has to infer them:
`state: "stopped"`, `merge_sha: null`, `issue_closed: false`,
`discussion_items: []`, `pr_url` the PR when one was already opened and `null`
otherwise. `detail_state` is `"none"` with `report_path: null` when Phase 5
retained nothing; when Phase 5 did retain readable Minor/Discussion findings, it
is the existing failure-only `"unpublished"` shape — name the retained source in
notes, keep the worktree, do not claim merge success — which is already exactly
the rule for a keep-the-worktree failure. Phase 8 does not run: no delivery-detail
package is published, because the successor owns that worktree and will produce
its own. The retained candidate stays worktree-local and ends with the worktree,
as `CLAUDE.md` says it is meant to.

AC2's *intent* — "aborts without executing the write" — is fully met. Its
literal prescription is not, and this row is the record of that departure.

"A fresh ship owner never writes workflow-state itself" stays true and
unqualified as a statement about **writes**; the sentence gains a clause naming
`check-launch` as the read-only exception so a reader cannot take it as a ban on
consulting the ledger at all.

**from-issue must not turn that stop into a stale ledger write.** from-issue's
Phase 7 today applies the terminal return procedure — a `workflow-state finish`
— to any Phase-7 `stopped`/`failed` ship report. The ship owner and its parent
share one launch identity, so if the ship owner was superseded, its parent is
too, and that `finish` would be exactly the write the design just refused at the
forge. Phase 7 therefore gains one sentence: before the terminal
`workflow-state finish` for a ship report, run `check-launch` with this owner's
own `action_id`; on `current: false` or any helper failure, write nothing, print
the canonical re-entry line, and stop. One sentence, one call, the same helper —
and the trust boundary is now checked on both sides. Every ledger write a stale
launch can still reach outside that path is inventoried in the next section.

### What this guard does not close

Said plainly, so nobody reads the guard as a proof:

- **A bounded TOCTOU window survives.** The check and the write are two commands,
  not one transaction. Supersession that lands between them is not caught. What
  changes is the size of the window: from the whole shipping run — sync, push, PR,
  review, a CI watch that blocks for up to ~40 minutes, merge — down to the latency
  of one forge command. Closing it entirely means fencing custody inside the
  transaction core so the *write* carries the epoch, which is #125's slice and the
  reason its fourth acceptance criterion is the same guarantee. This is an
  owner-side advisory check, and calling it anything stronger would be papering over
  the mechanism (the-bar, *Root causes*).
- **Ledger writes by a stale launch outside D9's path stay reachable** — a
  `progress` on the successor's active attempt, a `suspend` reached from the
  deadline-rejection route. Pre-existing, not made worse here, and precisely what
  #125 closes by fencing custody inside the transaction core.
- **An unreaped expired attempt still answers `current`.** No successor launch
  exists yet, so structurally nothing has superseded it. Expiry accounting is
  #133's.

These are recorded here, in a design document, rather than as a `TODO` in source
(the-bar, *Production-grade by default*).

### The Phase-6 tip check

Replace the comparison and the remedy.

- `gh pr view <pr-num> --json headRefOid` must equal the **reviewed
  `HEAD_SHA`** — the value fixed in Phase 5, re-fixed after each applied fix
  lands and is pushed, never `git rev-parse HEAD` read afresh. Both attempts
  share one checkout, so live local HEAD is not evidence about what was
  reviewed.
- Divergence means the PR head carries commits outside the reviewed range:
  **unreviewed commits on the branch.** It is never resolved by re-pushing.
- "Escalated", in autonomous mode, means the genuinely-blocked stop ship-issue's
  auto rules already define: stop before the CI wait and before the merge,
  perform no further forge write, run no cleanup, keep the worktree and the
  branch, and return a truthful `stopped` ship summary naming the divergence
  with both SHAs — the reviewed `HEAD_SHA` and the observed `headRefOid`. Do not
  re-push, do not reset, do not re-review, do not merge. In interactive mode it
  is a surface-and-wait at the same point.

Divergence here is also *evidence* of a superseded launch, which is why the
guard runs before the merge regardless of how the tip check came out.

### Documentation

**`CLAUDE.md`** — beside the existing "so two checkouts executing the same plan
can never share a ledger", state the complementary fact: two *attempts* on one
issue do share a checkout and therefore share that sdd bucket and that branch;
the ledger hands a retry the predecessor's worktree on purpose, which is both
what lets a successor resume the task ledger seamlessly and why a still-running
predecessor must re-validate its launch identity before any forge write. The
claim goes inside the same parenthesis so the two halves of one fact stay
together.

**Skill prose on expiry** — the only skill-prose home that explains expiry to an
owner is from-issue's deadline-rejected-`progress` paragraph. Append to it,
after "Persistence precedes notification: the reaper's suspension is already
durable before you print.": expiry is wall-clock only — the reaper compares the
current instant against the attempt's `deadline_at` and never consults
`last_progress_at`, so an attempt that is actively working (blocked on a CI
watch, say) expires exactly like one whose owner is gone; a deadline bounds how
long an owner may hold the issue and says nothing about whether it is still
running. Appending keeps the anchor order that paragraph's existing contract
test pins.

## Test seams

Existing seams only; no new ones.

**Seam 1 — the `workflow-state` CLI, via subprocess** (`test_workflow_state.py`,
`WorkflowStateLifecycleTest`). Prior art: every verb in that file is exercised
through `run_cli(...)`; the module is never imported. New tests append after the
last lifecycle test and before `ArtifactBudgetPolicyResolutionTest`. A
`check_launch(...)`/`check_launch_raw(...)` helper pair mirrors the flag-verb
wrapper `suspend` uses. Required cases:

- **Retry shape, driven by an owner-reported failure.** `init_run()`;
  `spawn(issue=14, worktree=wt)` → `14:1:1`; `fail_owner(issue=14, attempt=1,
  ...)`; assert `14:1:1` now answers `inactive_attempt`;
  `retry(issue=14, worktree=wt, ...)` → `14:2:1`; assert `14:1:1` answers
  `current: false`, `reason: "superseded_attempt"`, `current_action_id:
  "14:2:1"`, and `14:2:1` answers `current: true`, `reason: "current"`. The
  retry is driven by `fail_owner` — a `finish` with `state: "failed"` — and
  never by expiry, so the expiry-accounting change tracked in #133 cannot
  invalidate it. Reusing the predecessor's worktree on the retry is legal and
  matches the shared-worktree reality.
- **Resume shape.** `init_run()`; `spawn(issue=14, worktree=wt)` → `14:1:1`;
  `suspend(issue=14, attempt=1, blocked_on="transport", ...)`; assert `14:1:1`
  answers `inactive_attempt` with `current_action_id: null`;
  `resume(issue=14, worktree=wt, ...)` (a plain `control` sweep auto-resumes a
  `transport` suspension) → `14:1:2`; assert `14:1:1` answers `current: false`,
  `reason: "superseded_launch"`, `current_action_id: "14:1:2"`, and `14:1:2`
  answers `current: true`.
- **Read-only.** `before = self.state_path.read_bytes()` around every query
  above, plus the whole-tree form for the unknown-run case
  (`assertFalse(self.workflows_dir.exists())` after querying a repo root that
  has no `.superpowers/` at all — proving the verb creates neither the
  directories nor the `.gitignore` nor the lock). Repeating a query returns
  byte-identical stdout.
- **Answer-vs-error table.** One `subTest`-driven case per row of the
  answer/error table above, asserting `(returncode, stdout, reason)`; the exit-2
  rows additionally assert `stdout == ""` and `assertNotIn("Traceback",
  stderr)`.
- **The redundancy invariant.** For every case, `current == (current_action_id
  is not None and action_id == current_action_id)`.

**Seam 2 — skill prose** (`test_workflow_skill_contracts.py`,
`WorkflowSkillContractsTest`), using the existing `self.section(...)` and
`self.assert_ordered(...)` helpers. Required assertions:

- Ordering inside `section(ship_issue, "## Phase 4 — Open PR", "## Summary")`:
  `check-launch` → `git push -u origin <branch>` → `check-launch` →
  `gh pr create`.
- Ordering inside `section(ship_issue, "## Phase 7 — Merge", "## Phase 8 —
  Cleanup")`: `check-launch` before the merge command. **Anchor the merge on
  `--delete-branch`, not on `gh pr merge`**, and keep the literal `gh pr merge`
  out of every line the new prose adds anywhere in `ship-issue/SKILL.md` —
  `test_ship_issue_merge_is_bound_to_the_resolved_repository` `assertEqual`s the
  complete list of lines containing that literal.
- The new `## Launch guard` section contains the exact command line, "Proceed
  only on `current: true`", the refusal list, "no ledger write", the post-merge
  exemption, and the ledger-free skip. It asserts the refusal routes to the
  **no-write stop** — the canonical re-entry line and a `stopped` summary — and
  `assertNotIn("workflow-state suspend", guard)`. AC6's wording is "routes a
  negative answer to suspension"; per D8 there is no suspension to route to, so
  the contract pins the stop instead. A test asserting a `suspend` here would pin
  the harm.
- ship-issue's "A fresh ship owner never writes workflow-state itself" sentence,
  in its `check-launch`-qualified form, gains an assertion. It is unpinned today,
  and it is the invariant AC3 names ("a fresh ship owner still performs no ledger
  write"); the two-file idiom of
  `test_authorization_truth_is_single_and_shared` is the shape to follow.
- from-issue Phase 7 ordering: "receiving the ship report" → `check-launch` →
  `workflow-state finish`, which also preserves the anchor order
  `test_owner_lifecycle_is_optional_for_direct_use_and_covers_all_stops`
  already pins.
- `ship-handoff.md` carries `action_id` and the pass-it-through-verbatim
  sentence; `test_autonomous_reports_and_ship_handoff_are_root_plus_metrics`
  gains `action_id` to its pinned field list.
- Phase-6 tip check: the Phase-6 section contains `HEAD_SHA` and "unreviewed
  commits", and `assertNotIn("re-push first", phase_six)`.
- `test_helper_binaries_resolve_from_bare_names` gains `("ship-issue",
  self.ship_issue)` to its `~/.agents/bin/workflow-state` subTest tuple, because
  ship-issue now invokes the helper.
- The verb name is checked against the retired-name assertions: `check-launch`
  must not make `"workflow-state launch"` appear in `orchestrate` or in
  from-issue's dispatch-rules section.

**Seam 3 — the report validator CLI** (`test_artifact_budget.py`,
`ArtifactBudgetCliTest`, via `run_validate`). The `lifecycle()` fixture gains
`action_id`; every existing ship-handoff payload in the file gains it (the
boundary is closed, so they go red otherwise); new invalid rows cover a
lifecycle group with `action_id: null` while the rest are present, and the
reverse.

**Seam 4 — the built Claude settings** (`tests/test_claude_permission_guard.py`).
Unchanged and untouched: the guard's grammar does not move, the merge keeps its
existing exact-argv shape, and the adversarial table must stay green. It is a
gate here, not a target.

## Verification

```sh
just build
just agent-workflow-tests
just show-claude-settings > "$TMPDIR/claude-settings.json" \
  && CLAUDE_SETTINGS_PATH="$TMPDIR/claude-settings.json" \
     python3 tests/test_claude_permission_guard.py -v
```

`just agent-workflow-tests` covers `test_workflow_state.py`,
`test_workflow_skill_contracts.py` and `test_artifact_budget.py` — the three
suites this change touches. The permission-guard suite is not in that recipe and
must be run separately with the built settings artifact.

## Files touched

- `home/common/agent-skills/scripts/workflow-state.py` — the `check-launch`
  verb, its subparser, the extracted action-id render/parse pair, and the three
  call sites routed through the render helper.
- `home/common/agent-skills/scripts/artifact_budget.py` — `action_id` in the
  ship-handoff key set and lifecycle group.
- `home/common/agent-skills/skills/ship-issue/SKILL.md` — the `## Launch guard`
  section, the Phase-4 / Phase-5 / Phase-7 pointers, the Phase-6 tip check, and
  the read-only clause on the never-writes sentence.
- `home/common/agent-skills/skills/from-issue/ship-handoff.md` — `action_id` in
  the candidate template and its one explaining sentence.
- `home/common/agent-skills/skills/from-issue/SKILL.md` — `action_id` in the
  lifecycle identity and the dispatcher envelope, the Phase-7 pre-`finish`
  guard sentence, and the wall-clock expiry clause.
- `home/common/agent-skills/tests/test_workflow_state.py`,
  `home/common/agent-skills/tests/test_workflow_skill_contracts.py`,
  `home/common/agent-skills/tests/test_artifact_budget.py`.
- `CLAUDE.md` — the shared-bucket claim.

## Out of scope

- **#133 — expiry accounting.** `last_progress_at` does not become an input to
  expiry here, and `check-launch` takes no clock at all. The retry-shape test is
  driven by an owner-reported failure precisely so that #133 cannot invalidate
  it.
- **#125 — epoch-fenced leases in the transaction core.** This issue is the
  narrow owner-side bridge in the current engine. Its tests are #125's
  regression floor, not something #125 may drop. Ledger writes by a stale launch
  outside the one path guarded here stay reachable and are #125's to close.
- **The Claude Code permission guard's command grammar.** The merge keeps the
  existing exact-argv shape; no `--match-head-commit`, no new verb, no change to
  `validate_push`. The guard validates command shape and repository state and
  continues not to know about lifecycle identity — the owner-side check is where
  that knowledge belongs. No allow-surface entry is needed either: `workflow-state`
  is not among the 18 allow entries today, and the existing `progress`, `suspend`
  and `finish` calls already run under `defaultMode = "auto"` without one, so
  `check-launch` runs the same way. The 17th handoff key is likewise no budget
  concern — the handoff is about a kilobyte against `phase_reports.wire_max_bytes`.
- **`control`'s `CONTROL_DISPATCH_KINDS`.** No action kind that stops a launch is
  added; the guard is advisory to the owner and changes nothing about dispatch.
- **A `docs/` tree, a context map, or an ADR file.** This repository has none;
  its binding documents are `CLAUDE.md` and
  `home/common/agent-skills/standards/the-bar.md`, and every decision here lands
  as a row below.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The verb is `check-launch`, with argv `--repo-root --run-id --action-id`, printing one four-key JSON object (`action_id`, `current`, `current_action_id`, `reason`) on exit 0. Both answers are exit 0; the discriminator is `current`. | the-bar *Token economy* (few parameters, each a failure site) and *Fail loud*; `print_json` is the house output convention; the owner-facing verbs `progress`/`suspend`/`finish` emit bare projections with no `interface_version`, unlike `control`/`direct-owner`. | Exit status as the discriminator — it collides with the exit-2 error path and makes a refusal indistinguishable from a crash. A name containing `launch` — `"workflow-state launch"` is a retired verb the contract tests assert absent. |
| D2 | The launch identity is one opaque `--action-id` string, not three flags. | `bootstrap_response` and `direct_owner_response` already render exactly `issue:attempt:launch`; the owner receives it verbatim, and the-bar's *Token economy* prefers a short handle a model emits reliably over three raw integers. | Separate `--issue/--attempt/--launch` flags — three chances to transpose a value, and a second home for a grammar the helper already owns. |
| D3 | A positive answer requires evidence; every absence the ledger can express is a well-formed negative (exit 0), and only an unreadable ledger or a malformed argument is exit 2. An absent `state.json` is `unknown_run` at exit 0; a corrupt or non-regular one is exit 2. | Issue AC1 ("an unknown run, issue, attempt, or launch answers 'not current' rather than erroring softly"); the-bar *Truthful terminal states* and *Fail loud* — a corrupt ledger reported as a routine refusal hides corruption. | Exit 2 for an unknown run — contradicts AC1 and makes a benign "this run was never created" indistinguishable from a broken ledger. Exit 0 for a corrupt ledger — silently converts a fault into a refusal. |
| D4 | `check-launch` takes no `--now`, no lock, and neither `transact` nor `workflow_paths`; it resolves the state path itself and reads through `read_locked_state`. It therefore cannot run the reaper or persist an upgrade. | `transact` creates `.superpowers/`, the run dir, `workflows/.gitignore` and `state.lock` and writes on `changed`; `workflow_paths` creates directories; `atomic_write_state` publishes by `os.replace`, so an unlocked read is never torn. Issue: "the query is read-only". | Taking `--now` for symmetry with the other verbs — it would invite an expiry evaluation that is #133's, and a clock is not needed to answer a structural question. Holding the lock — requires creating `state.lock`, which is a write. |
| D5 | `current_action_id` is non-null exactly when the latest attempt is `active`; a `suspended`, `handed_off` or terminal latest attempt has no current launch and every identity answers `inactive_attempt`. `reason` is a closed 7-value set with a fixed precedence. | the-bar *Fail loud* (closed-set dispatch, no default fall-through) and *Tests that can fail* (the two supersession shapes must be separately observable, or a bug collapsing them stays green). | Pure identity comparison ignoring attempt state — a forge-reconciled or reaped attempt would still answer `current`, letting an unentitled owner merge. A single opaque `false` — both AC5 shapes would assert the same thing. |
| D6 | `action_id` joins the ship-handoff boundary's closed key set and its all-or-nothing lifecycle group, validated as `_string` only; the authoritative grammar stays in `workflow-state.py`, which renders and now parses it. The three renderings collapse into one extracted helper. | `_exact_keys` is set equality, so the boundary is closed and "optional" is inexpressible — the module's idiom is always-present-may-be-null. the-bar *DRY* (one home per contract; deduplicate when copies must change together) and *Defense in depth* (outer check for experience, inner for correctness). | A separate optional field or a second regex in the validator — the first is inexpressible, the second gives one grammar two homes. Carrying only `attempt` — cannot catch the resume shape at all. |
| D7 | Guard **every forge/`origin` write before the merge is verified** — Phase-4 push, Phase-4 PR create, every Phase-5 fix push, the Phase-7 merge. Leave post-merge writes unguarded: the remote branch delete, `gh issue close`, `git branch -d`, `git worktree remove`. | Phase 5's apply-and-push flow pushes to the same shared branch, so the issue's three named writes are instances of a rule, not its definition. ship-issue Phase 8 already rules that a post-merge failure is recovered, not converted into a pre-merge failure row. | Guarding exactly the three named commands — an enumeration that drifts and leaves the fix push open. Guarding cleanup too — could only refuse cleanup for a merge that already landed, stranding a worktree. |
| D8 | The refusal is a stop that writes nothing anywhere: no forge write, no ledger write, no cleanup; print `/from-issue <num> --auto` and return a truthful `stopped` ship summary. It deliberately does **not** call `workflow-state suspend`, departing from AC2's literal wording. | In the retry shape `suspend` is refused (`only an active attempt can suspend`); in the resume shape it would park the *successor's* active attempt — the issue's own harm, in ledger form. "A fresh ship owner never writes workflow-state" (ship-issue Phase 8) stays true for writes. | Calling the suspension procedure literally — the resume shape makes it actively harmful. Returning `failed` instead of `stopped` — a stale `failed` invites `control` to open a third attempt. |
| D9 | from-issue's Phase 7 runs the same `check-launch` with the owner's own `action_id` immediately before the terminal `workflow-state finish` for a ship report; on `current: false` or helper failure it writes nothing, prints the re-entry line, and stops. | the-bar *Defense in depth* ("every trust boundary is checked on both sides"). Without it the design refuses the forge write and then performs the ledger write from the very launch it just proved stale, because the ship owner and its parent share one identity. | Leaving Phase 7 alone — incoherent, and it routes every supersession abort into a stale `finish`. Guarding every `workflow-state` write in from-issue — scope growth beyond the issue and a new failure mode at all eight phase gates. |
| D10 | Phase 6 compares `headRefOid` to the reviewed `HEAD_SHA` (re-fixed after each applied fix lands); divergence is "unreviewed commits on the branch". In `--auto`, "escalated" means: stop before the CI wait and the merge, no further forge write, no cleanup, keep worktree and branch, return a truthful `stopped` summary naming both SHAs. | Issue AC4; both attempts share one checkout, so live local `HEAD` is not evidence about what was reviewed. ship-issue's auto rules already define "genuinely blocked" as a return, and `--auto` never auto-resolves history. | "Re-push first" — makes the predecessor push the successor's unreviewed work. Re-reviewing the new head — silently re-legitimises commits the successor owns. |
| D11 | The `CLAUDE.md` claim goes inside the existing per-checkout-bucket parenthesis; the wall-clock expiry statement is appended to from-issue's deadline-rejected-`progress` paragraph. | Issue AC7. That paragraph is the only skill-prose home that explains expiry to an owner; the "silent owner" framing lives in `workflow-state.py` docstrings, not skill prose. Appending preserves the anchor order the paragraph's existing contract test pins. | A new documentation file or section — this repo has no `docs/` tree and the fact belongs beside the sentence it completes. Editing the docstrings instead — they are not the prose the AC names. |
| D12 | Without lifecycle identity (standalone `/ship-issue`, or an all-null lifecycle group) the guard is skipped silently. | ship-issue's stated policy of degrading gracefully on absent optional bindings; a ledger-free invocation has no attempts and no supersession mechanism, and the all-or-nothing validator means the group is never partially present. | Hard-failing without a ledger — breaks standalone `/ship-issue` outright for a hazard that cannot occur there. |
| D13 | The guard fails closed on a missing helper, a non-zero exit, or unparseable output, explicitly overriding ship-issue's degrade-gracefully house rule for this one call; and the spec records the bounded TOCTOU window the check cannot close rather than implying it does. | the-bar *Root causes* ("no special case to hide a wrong shape") and *Production-grade by default* (known limitations belong in docs). ship-issue's degradation rule is written for optional bindings, not for a safety check. | Following the house degradation rule — turns the guard into a no-op exactly when the environment is broken. Claiming the window is closed — only transaction-core fencing (#125) closes it. |
| D14 | The refusal returns `stopped` with `merge_sha: null`, `issue_closed: false`, `discussion_items: []`, `detail_state: "none"`/`report_path: null` — or the existing failure-only `"unpublished"` shape when Phase 5 retained readable findings — and skips Phase 8 entirely, publishing no delivery detail. | `validate_ship_summary_report` accepts exactly this for `stopped`; ship-issue already defines `unpublished` as the keep-the-worktree failure shape, so reusing it is less new machinery than inventing a rule. the-bar *Truthful terminal states*. | Publishing delivery detail anyway — records a delivery that did not happen, from an owner the ledger has disowned, into the successor's worktree. |
| D15 | `reason`'s `superseded_attempt`/`superseded_launch` reuse the issue's vocabulary even though `result_source: "superseded"` already means something narrower; the spec pins both senses. | The issue's own wording ("a predecessor whose attempt was superseded"); the two values never share a field, and this repository has no glossary file, so the spec is the only home. | Coining `stale_*` — a third word for one idea, diverging from the issue that everything else here cites. |
| D16 | `command_control`'s dispatch-action `id` is routed through the same extracted `render_action_id` helper as `bootstrap_response`, `direct_owner_response` and `check-launch` — four renderings collapse into one, not the three D6 counted. | the-bar *DRY* (deduplicate copies that must change together). That `id` is literally the value the dispatcher envelope hands to from-issue as `action_id` and the guard later re-validates, so it is the same grammar, not a lookalike. | Leaving it an inline f-string — keeps a fourth copy of exactly the grammar D6 deduplicates, in the one site that produces the value the guard consumes. |
| D17 | The Phase-5 fix-push guard and the reviewed-`HEAD_SHA` re-fix land in `ship-issue/REVIEW.md`, one file beyond this spec's Files-touched list. | D7 guards every Phase-5 fix push and D10 re-fixes `HEAD_SHA` after each applied fix lands; REVIEW.md owns steps 4 and 5 of the five-step apply/push flow, so it is where those two facts are actionable. | Stating the rule only in ship-issue's `## Launch guard` — leaves the flow that performs the push silent about it, which is how an enumerated rule drifts. |
| D18 | Falsifiable anchoring: AC7's `CLAUDE.md` half is gated by `grep` in its task rather than a new contract seam, and every new contract assertion anchors where it is false at base — the from-issue lifecycle anchors go in the **dispatcher** subsection, since `action_id` already appears elsewhere under `## Lifecycle identity`. | This spec's *Test seams* ("existing seams only; no new ones"); the contract suite reads `CLAUDE.md` only as a gitignore-shape fixture. the-bar *Tests that can fail*. | A `CLAUDE.md` content seam (opens a seam the spec closed) or a section-wide `assertIn("action_id", identity)` (green at base, so it can never fail). |
| D19 | Task 4 also rewrites the two tip-check sentences in `ship-issue/evals/evals.json` (eval 1's Phase-6 comparand, eval 2's Phase-6 clause plus a reviewed-`HEAD_SHA` re-fix in its step 5), and a contract test pins both. | Standards review B-132-01: the graded eval is a behavioural spec, and left naming live `git rev-parse HEAD` it would score a correct run as a failure and the defect AC4 removes as a pass. Eval 2's clause (5) keeps its local comparison — verifying your own push landed is a different question from what was reviewed. | Editing only `SKILL.md` and relying on Task 4's `re-push first` grep — that phrase never appears in the evals, so the stale expectation survives the gate. |
| D20 | The pre-`finish` guard of D9 is installed in **both** terminal routes: `SKILL.md`'s generic Phase 7 and `AUTO.md`'s direct-autonomous ledger-only bookkeeper, whose brief becomes an exact `check-launch`-then-`finish` sequence executed by the bookkeeper itself. | Standards review B-132-02: the direct-autonomous route is the one a `/from-issue <num> --auto` run — the issue's own scenario — actually takes, and its bookkeeper is told it "executes only that command". The check must sit inside the bookkeeper because a parent-side check would put an agent dispatch between check and write. | Guarding only the generic paragraph — leaves the exposed route unguarded. Checking in the dispatching parent — reopens the window the guard exists to close. |
| D21 | Three review-driven corrections to how tasks prove themselves: red-phase selectors use repeated `-k` flags with a non-zero `Ran N tests` assertion; the unknown-coordinate rows assert the whole canonical answer rather than `reason` alone; and Task 6 moves from the `low-risk` lane to `full`. | Standards review S-132-01/S-132-03/S-132-02: stdlib `unittest` reads `-k "a or b"` as one literal pattern and silently selects nothing, so the red phase proved nothing; the redundancy invariant alone would pass an implementation echoing the queried id back with `current: true`; and the `low-risk` lane excludes lifecycle and public-contract work, which Task 6's expiry prose is. | Keeping the pytest-style selector, `reason`-only assertions, and a size-based lane call — each lets the very defect its check exists to catch go green. |
| D22 | Task 2's `action_id` identity-field assertion anchors on the new identity-list sentence (`` `owner`, `action_id`, and normalized `worktree` as one identity ``) compared against `normalized(identity)`, instead of joining the section-wide identity-field loop in `test_owner_lifecycle_is_optional_for_direct_use_and_covers_all_stops`. | D18 (falsifiable anchoring) governs over Task 2's brief text, which mandated the loop entry: `action_id` already appears in `### Direct autonomous acquisition`, inside the same `## Lifecycle identity` section the loop asserts over, so `assertIn("action_id", identity)` passed before the change and could never fail for the behaviour Task 2 added. Adjudicated during the Phase-6 task review of Task 2. | Keeping the loop entry as the brief specified — a permanently-green assertion that would not notice the identity list losing `action_id` again. |
| D23 | Eval 1's graded Phase-4 walk in `ship-issue/evals/evals.json` also requires the `check-launch` guard immediately before each of its two forge writes, naming `## Launch guard` as where the rule lives and stopping without the write on anything but `current: true`. | D19's own reasoning applied to the guard rather than the tip check: the eval is the behavioural spec a graded run is scored against, and left unchanged its Phase-4 clause scores a run that omits the guard entirely as a pass — the issue's central behaviour ungraded. Surfaced by the Phase-6 task review of Task 3, applied in Task 4 because that task already opens the file under D19. | Leaving eval 1's Phase-4 walk unchanged — the issue's central behaviour would be ungraded. A separate seventh task — a second commit touching the same two lines for one sentence. |
