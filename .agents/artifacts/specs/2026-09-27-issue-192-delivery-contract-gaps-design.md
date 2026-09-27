# Issue 192: legacy worktree contracts and post-review syncs

Decision for [#192](https://github.com/fagenorn/nix-config/issues/192),
2026-09-27. Status: delegated (autonomous `--auto`). It builds on the #151
delivery design (`2026-09-21-issue-151-delivery-reconciliation-design.md`,
"SPEC151") and the #171 contract-source design (`2026-09-23-issue-171-…`,
"SPEC171"). Their rows still bind, except where a row below says it refines one.

## Problem

Run `run-20260923-147-153-154-150-148-149-126-155` stranded issues in two ways.

1. **A legacy worktree can never get a contract.** Attempts recorded before
   contracts existed used slugless paths such as `.worktrees/worktree-issue-154`,
   while their real branches carried slugs (`worktree-issue-154-shell-checker-examples`).
   `build-delivery --kind contract` takes the contract's branch from the
   worktree path's final component and refuses a name outside
   `[<prefix>]issue-<num>-<slug>`. Control requires a contract before it
   resumes or retries such an attempt, and the contract binds the recorded path
   (SPEC171 D8). So the attempt can be neither resumed nor retried. #154 had to
   restart as a separate direct run on a new branch cut at the old head.
2. **A sync of `main` after review strands the remainder.** The selection pins
   the reviewed commit. When `main` moves afterwards and the PR conflicts,
   resolving the conflict needs a new head. No stage re-selects or re-pushes, the
   ledger cannot fold a merge at any head except the selected one, and the
   owner recorded the provider's refusal as an authority rejection
   (`merge_conflicts_requires_new_head`, an owner-composed reason). That
   rejection parks every later merge proposal on `human_gate`, and relaunches
   climb `stalled_resumes`. For #150 (PR #184), `main` had to be merged in twice.
   Once the dispatcher merged the PR out of band, the remainder could only end
   `terminal_failed`: "the ledger cannot fold the merge: it landed at head
   0503fa1, not the immutable selection dd5e398".

Acceptance:

- **A1:** a legacy attempt whose slugless recorded worktree is on a slugged
  branch can be resumed or retried through a documented route.
- **A2:** a remainder whose PR needs a sync of the integration branch after
  review can reach `pr_merged` and cleanup without manual out-of-band merging.

## Solution

- **Gap 1: the branch comes from the live checkout.** The contract builder
  still takes its branch from the worktree's name whenever that name is an issue
  branch, so every contract that builds today builds byte-identically. Only when
  the name is not one does `workflow-state` read the branch the worktree at that
  path has checked out, and the builder accepts it if the issue branch pattern
  does. The contract keeps the recorded path as its `remove_worktree` target
  and the live branch as its slot and branch-deletion targets. Nothing is
  relocated, and no ledger write is made. The one prose assumption that a
  branch equals its path name, `expected_branch` in AUTO.md, reads the
  contract's branch instead.
- **Gap 2: a sync after review is selected too.** A selection stays immutable,
  but a slot may now hold a **selection chain**. The root is today's
  `selected-output/v1`. Each later link is a **sync selection**, a
  `selected-output/v2` whose head is one merge commit: its first parent is the
  previous head, and its second parent is an integration-branch commit. The
  chain's tip is the slot's **current selection**, so publish, open, merge,
  scope matching and delivery proof all follow it, and the earlier selections
  stay in history. ship-issue gains a post-selection sync route. The owner makes
  one sync merge, reviews its combined diff, pushes, waits for CI and records
  the sync selection, then records `branch_published`/`pr_opened` at the new
  head and proposes the merge. A merge the provider refuses because the PR
  cannot merge into its base is not an authority denial, so it parks nothing.

## Decisions

### 1. Contract branch derivation (per D2, D3, D4)

`DeliveryBuilder._build_contract` computes the issue branch regex once, in one
private home shared with the new predicate below. That regex is the binding's
pattern with `<num>` as the decimal issue, `<slug>` as `[a-z0-9][a-z0-9-]*`,
and the worktree prefix optional. The branch is then chosen in this order:

1. The worktree path's final component, when the regex accepts it. This is
   unchanged, and no git is read.
2. Otherwise, the value of a new keyword, `worktree_branch`, when it is given
   and the regex accepts it.
3. Otherwise, a refusal (§2).

When rule 2 applies, the provenance digest input gains a `branch` member,
`{policy, issue, worktree, source, branch}`, so the digest covers the observed
input it used. Under rule 1 the input stays exactly
`{policy, issue, worktree, source}`. The rest of the contract is derived as
today: the reviewed slot's `constraints.branch`, the `delete_remote_branch`
and `delete_local_branch` literals take the chosen branch, and `remove_worktree`
keeps the input path. Intent re-derivation (`_derivation`, `_intent`,
`_contract_facts`) already reads the branch from the contract's slot and the
path from its `remove_worktree` literal. It never re-runs the path rule, so
every other kind re-derives such a contract after the worktree is gone.

The builder gains a pure predicate, `requires_worktree_branch(value, policy)`,
which `DeliveryRuntime` forwards like `requires_installed_intent` (#193 D5). It
is true only when three things hold. `value` is a well-formed contract input,
meaning the closed keys, their types, a supported source kind, and an absolute
normalized worktree. The policy's sealed members are well-typed and its
tracker is `github`. And the regex rejects the path's final component. Every
other input answers false and meets its existing refusal inside the build,
so the order of refusals does not change.

`command_build_delivery`, for `--kind contract` only, runs the predicate after
resolving the repo-root policy. Only when it is true does it call a new
function, `live_worktree_branch(path)`, and pass the result as
`worktree_branch`. The build, and then `check_contract_worktree` (#181), run as
today. `live_worktree_branch` is read-only and runs `git` by name on `PATH`
with a 60-second timeout, as the other helpers here do. It requires three
things:

- the path is a non-symlink directory;
- `git -C <path> rev-parse --show-toplevel` succeeds, and its output resolves
  (`realpath`) to the path's own resolved form, so a directory inside another
  checkout is not taken as that checkout;
- `git -C <path> symbolic-ref --quiet --short HEAD` prints one branch name.

Any other outcome raises the refusal in §2, before any build.

### 2. Refusals (per D4)

Every refusal still exits 2 with empty stdout and one stderr line, and the
existing text is kept as the prefix:
`workflow-state: build-delivery refused: worktree name '<name>' does not match the issue branch pattern`.
The line then gains exactly one clause naming the reason:

| Condition | Clause appended |
|---|---|
| path absent | `, and the worktree is absent` |
| exists but is not a non-symlink directory | `, and it is not a directory` |
| not the top level of a git worktree | `, and it is not the top level of a git worktree` |
| detached HEAD | `, and its HEAD is detached` |
| git fails, cannot start or times out | `, and git failed: <first stderr line, or the start/timeout error>` |
| live branch outside the pattern (the builder's re-check) | `, and its checked-out branch '<branch>' does not match either` |

The pattern-matching path, and every other refusal text, is unchanged. The
worktree-policy veto of #181 still runs after a live-branch build. A legacy
branch whose checkout resolves to different sealed policy is refused as it is
today, and syncing the integration branch into it is the ordinary fix.

### 3. Owner-side branch checks (per D5)

AUTO.md's fresh delegated owner derives `expected_branch` from the owner
object's `contract`, as the reviewed slot's `constraints.branch`, not from the
worktree's final path component. It still requires that value to match the
binding-derived accepted regex, and `git -C owner.worktree branch --show-current`
to equal it. Nothing else in the skill tree equates a branch with a path.
orchestrate-issues' sentence "a candidate's final path component is the branch
its contract will carry" stays true, because a candidate is absent and so
builds by rule 1. ship-issue's Phase 0 checks the live branch against the
pattern already. The adapter and direct acquisition prose need no change: they
already build a recorded issue's contract from its recorded path.

### 4. Selection chains (per D6, D7, D15, D16)

A sync selection is a `selected-output/v2`. It has exactly the v1 members with
`schema_version: 2`, plus `sync`, which has exactly three members.
`prior_selection_id` is the digest id of the selection it extends.
`first_parent` and `integration_parent` are its head's two parents, which must
be two distinct non-empty strings, and neither may equal its own
`subject_value`. A sync selection's `subject_kind` is `commit`. v1 is unchanged
and is always a chain's root. The id and derived-member rules are those of v1.
The addition is additive grammar within state schema 4 and interface 2, as
SPEC171 D12's refinements were: persisted ledgers stay valid, and an older
helper refuses a ledger that holds a sync selection without mutating it.

One private model function, `_selection_chain(selections, slot filter)`, owns
the chain. Its slot filter is the one `_selection_for_stage` applies today:
contract digest, slot, subject kind, repository, branch and base. Over the
selections that pass it, the function requires the following, and otherwise
rejects with the existing `conflicting selected outputs`:

- exactly one v1 root, or no selection at all;
- every sync selection names a prior selection in the set, and its
  `first_parent` equals that prior selection's `subject_value`;
- no selection is the prior selection of two others;
- every member is reachable from the root, and no head repeats;
- each sync selection's three evidence arrays contain its prior selection's.

It returns the chain in order, and its tip is the slot's current selection.
Every consumer reads the tip:

- `_selection_for_stage` returns it. Through it, stage scope matching,
  publish/open/merge observation matching, `_pr_numbers` and `_selected_head`
  follow the tip. The `select_reviewed_output` stage is observed by the
  `selected_output` observation that introduced the tip, the same observation
  kind as today, so the stage table does not change.
- `match_scope` and `_scope_mismatch` bind a slot's output and data to the tip
  instead of requiring exactly one selection. Their public seam, a list of
  selections, is unchanged.
- The `implementation_delivered` postcondition matches only when its selected
  subject is the tip.
- The `delivery` validator admits a selection only as a member of its stage's
  chain. The `ship-handoff` validator requires the handoff's `selected_outputs`
  to form a valid chain or be empty.
- **Final once merged.** The `delivery` validator rejects a delivery in which a
  `pr_merged` observation's `expected_head` is the head of a chain member that
  is not the tip. So no sync selection can follow a merge.

Stage facts are recomputed on every fold, as today. A sync selection therefore
makes the old head's `branch_published` and `pr_opened` observations stop
matching, and those stages are pending again until observations at the new
head fold. The route (§6) folds them in the same checkpoint as the sync
selection, and a checkpoint that proposes the `merge_pr` scope without them is
refused with no write, since `publish_branch` is then the ready stage.
Authority observations stay keyed to the declared slot-form scope, which the
tip still satisfies, so no successor intent is needed.

### 5. The `sync-selection` builder kind (per D8, D15)

`build-delivery --kind sync-selection` takes exactly `contract`,
`prior_selection` (a sealed selection of that contract), `head`, `tree`,
`parents`, `review_ref` and `test_ref`. It refuses, with one named reason each,
when:

- `prior_selection` is not a valid selection of this contract;
- `parents` is not a list of two distinct non-empty strings;
- `parents[0]` is not the prior selection's `subject_value`;
- `head` equals the prior selection's head.

It seals a sync selection:

- `sync`: `{prior_selection_id, first_parent: parents[0], integration_parent: parents[1]}`;
- data identity: `canonical_digest({"kind":"git-tree","value":<tree>})`;
- acceptance ids: the prior selection's, inherited, because a sync does not
  change what was accepted;
- review ids: the prior selection's plus `review:<review_ref>@<head>`;
- test ids: the prior selection's plus `test:<test_ref>@<head>`;
- `evidence_digest`: over `{head, review_ref, test_ref, sync}`.

The skill fixes `review_ref` as `merge-delta-empty` or `merge-delta-clean`, and
`test_ref` as `checks`. A relaunched owner therefore re-derives the same sync
selection. The contract-taking kinds reach an installed legacy contract through
the #193 lookup unchanged. The existing `observation` and
`implementation_delivered` kinds accept a sync selection unchanged, and the
runtime validates the output as `selected-output`.

### 6. The post-selection sync route (per D9, D10, D11, D12, D17, D18)

The route belongs to whoever holds the merge gate: the ship owner under
implementation custody, or a remainder owner. It is described once, in
`ship-issue/CI-MERGE.md`, as a new `## Post-selection sync` section. SKILL.md
points to it in one sentence each from `## Delivery loop` (steps 3 and 6),
`## Remainder mode`, and Phase 6's divergence rule. That rule's "never resolve
it by re-pushing, resetting, re-reviewing or merging" stop gains one exception:
a PR head the route admits.

**A sync run.** A PR head is a *sync run* from the tip when its first-parent
walk back to the tip passes only two-parent merge commits, each of whose second
parents `git merge-base --is-ancestor <parent> origin/<integration>` confirms
(after `git fetch origin`). Each commit in a sync run becomes one sync
selection, oldest first, and each is reviewed on its own. All of them fold in
one checkpoint.

**Trigger.** Before the merge, the owner reads
`gh pr view <pr> --json state,headRefOid,mergeable`. The route runs in three
cases:

- the PR is open with `mergeable: CONFLICTING`, or a merge was refused because
  the head conflicts with its base or is behind it where the base requires an
  up-to-date head. A head that is merely behind a base with no such rule is
  merged as it is;
- the PR is open, its head is not the tip, and the head is a sync run from the
  tip, which is a crash after the push;
- the PR has merged at a head that is a sync run from the tip.

**Steps.**

1. **Sync.** Make one merge of `origin/<integration>` into the tip under
   `SYNC.md`, so the first parent is the tip. Fold its conflict resolutions and
   sweeps into that merge commit.
2. **Verify.** Run the Phase 2 verification commands.
3. **Review.** Run REVIEW.md's merge-delta check over that commit's combined
   diff, `git show --cc`, through SKILL.md's merge-delta reviewer (the
   existing `ship-issue-merge-delta-review` site; no new dispatch marker). Apply
   findings by amending the unpushed merge commit, which keeps both parents.
   An empty delta is `merge-delta-empty`. A delta whose Blocking and Should-fix
   findings are all applied and re-reviewed is `merge-delta-clean`. Minor and
   Discussion findings are retained under REVIEW.md's durable-detail rules.
4. **Push.** Run `check-launch`, then `git push`.
5. **Wait for CI.** Run Phase 6's CI wait, with the reviewed head re-fixed to
   the new head.
6. **Select.** Build `--kind sync-selection` over the tip selection, the new
   head, its tree and its parents (`git rev-list --parents -n 1 <head>`),
   chaining one per commit of a sync run. Then build `branch_published` and
   `pr_opened` (the same PR) at the new head. Checkpoint them all with
   `--kind scope` for `merge_pr`.
7. **Merge.** Continue with the merge cycle.

Steps 1 to 5 precede the sync selection. So, as with pre-selection publication
(SPEC171 D15), they run under the guard, repository policy and the
`check-launch` fence, with no checkpoint. After a crash past step 4, the route
resumes at step 3 for the pushed sync run, and step 5 then waits for CI.

**A merge that already landed at a sync run.** If the PR has merged at such a
head, the owner runs step 3 for each commit, then step 6 without a push or a CI
wait. It adds the `pr_merged` observation at that head to the same checkpoint,
then continues with cleanup. This is the fold #194 D7 handed to #192. A
Blocking finding here cannot be amended, so it is a stop.

**Refusals and stops.** A merge the provider refuses because the PR cannot
merge into its base is a stale-head condition, not a denial. The owner records
no authority observation for it. Everything else stays the genuinely-blocked
stop that Phase 6 already defines, and a human then decides:

- a PR head that is not a sync run from the tip, such as a non-merge commit, a
  first parent off the chain, or an unconfirmed integration parent;
- a Blocking finding left once the commit is pushed;
- red CI that needs a fix commit.

If the base moves again after a sync, the next sync extends the chain. From the
first sync on, every later step's "selection" is the current selection. That
includes the `implementation_delivered` observation Delivery loop step 7 builds.

### 7. Documentation (per D13)

These surfaces change:

- **`build-delivery --help`.** This is authoritative, and a test pins it. It
  gains the branch rule (a worktree name that is not an issue branch takes its
  checkout's branch) and the `sync-selection` choice.
- **CLAUDE.md.** The "Delivery objects are built" bullet gains one clause for
  each rule.
- **Skills.** ship-issue's SKILL.md (the Delivery loop, Remainder mode and
  Phase 6 pointers) and CI-MERGE.md, and AUTO.md.
- **Instruction-load ceilings.** Every profile whose hot bytes grow is
  re-measured: `ship-owner`, and the profiles that load AUTO.md.

There is no ADR, because the repo has no ADR home (SPEC171 D21). SPEC151 and
SPEC171 are point-in-time records and are not edited. This ledger refines them.

## Test seams (per D14)

The seams are the existing ones: the builder CLI (`BuilderHarness`), the
`direct-owner`/`control`/`checkpoint-delivery`/`finish` round trips
(`test_delivery_workflow.py`, `test_workflow_state.py`), the model facade
(`test_delivery_model.py`), `artifact-budget validate-report` inside those round
trips, and the skill contract pins. The git fixture follows
`test_workflow_state.py`'s bare-origin clone and `git worktree add`, with the
synthetic project committed so the worktree resolves.

**A1**

- **T1, build.** A linked worktree at slugless `.worktrees/worktree-issue-171`,
  on branch `worktree-issue-171-delivery-contract-source`, builds a contract
  whose slot branch and both branch-deletion literals are the live branch and
  whose `remove_worktree` literal is the slugless path, and whose provenance
  digest is the canonical digest of `{policy, issue, worktree, source, branch}`.
  After
  `git worktree remove`, `--kind initial-intent` returns the same bytes, and
  `--kind scope` serves every stage.
- **T2, refusals.** The same slugless name, absent; on a detached HEAD; on
  branch `feature-x`; and as a plain subdirectory of the project checkout. Each
  exits 2 with empty stdout, the kept prefix and its §2 clause.
- **T3, unchanged path.** The existing byte-identity and refusal tests stay
  green unchanged. A pattern-matching name on a non-git directory still builds,
  which proves no git is read.
- **T4, control resume.** A migrated schema-2 run holds a suspended attempt at
  the slugless live worktree. A human-directed control sweep, given a recorded
  `matching_issue_branch` observation and a null contract, reports
  `delivery_contract_required`. With
  the contract built from the recorded path, the next sweep returns `resume`
  at that path and installs the contract.
- **T5, direct retry.** A migrated schema-2 direct run whose attempt 1 failed
  (owner verdict) at the slugless path. `direct-owner` asks for the contract,
  then returns `owner` with `launch_kind: retry`, attempt 2, at the same path.
- **T6, skill pin.** AUTO.md's delegated-owner check takes `expected_branch`
  from the contract's reviewed slot.

**A2**

- **T7, remainder after a sync.** The implementation custody checkpoints
  selection H0 with `branch_published`/`pr_opened` (PR 5) at H0 and the
  `merge_pr` scope. It then finishes `terminal_failed` with a `stopped` row,
  which returns remainder 1. The remainder's null-scope checkpoint follows. Then
  `--kind sync-selection` builds H1 with parents `[H0, M]`, and the sync
  selection, `branch_published` at H1 and `pr_opened` (PR 5, H1) are
  checkpointed with the `merge_pr` scope. The echo requires
  `native_evaluation_required`. The merge follows at H1, then every cleanup
  cycle, then `finish` with `delivery_complete` and `implementation_delivered`
  over H1. The stored delivery holds both selections, and `merge_pr`'s fact
  names the H1 merge. Every checkpoint and reply passes `validate-report`.
- **T8, merged-at-sync-run fold (the #150 shape).** Same setup, but the PR
  merged out of band at H2, whose sync run is H1 = `[H0, M1]` and
  H2 = `[H1, M2]`. The remainder first checkpoints a `pr_merged` at H2. It is
  accepted, and `merge_pr` stays pending. Then one checkpoint carries both sync
  selections, H2's `branch_published`/`pr_opened` and a `close_tracker` scope.
  It folds the H2 merge, and the loop completes.
- **T9, fold refusals.** Each of these exits 2 and leaves the ledger
  byte-identical: a second sync selection of H0 (a fork); a second v1 root; a
  sync selection after the merge at the tip; a sync selection with a
  `merge_pr` scope but without its H1 observations. The builder refuses each §5
  input with its reason.
- **T10, model facade.** The chain rules the builder never emits: a dangling
  prior selection, a non-commit sync selection, evidence that is not a
  superset, and a `pr_merged` at a superseded head. It also pins that
  `match_scope` binds the tip's literal output and data and refuses the
  superseded head, and that `implementation_delivered` naming H0 does not
  match.
- **T11, skill pins.** CI-MERGE.md's section defines the sync run and orders
  sync, verify, merge-delta review, `check-launch`, push, CI,
  `--kind sync-selection`, then the checkpoint with the `merge_pr` scope. It
  states the mergeability-is-not-a-denial rule. SKILL.md's Delivery loop,
  Remainder mode and Phase 6 divergence rule point to it.

## Out of scope

- #191's `progress`/`suspend` reply shapes.
- Repairing `run-20260923-…` or any ledger that already holds a merge rejection
  an owner recorded for a mergeability refusal. That rejection stays operative
  under SPEC151's D18 rules, and no builder kind seals reevaluation evidence.
- An **absent** slugless recorded worktree. It is refused with its named
  reason. Re-attaching a surviving branch at the recorded path is a human
  repair, because nothing can name that branch deterministically.
- Helper-side verification of sync parents or integration reachability. These
  are the owner's probe and review, as a v1 selection's tree is (D7).
- Non-merge fix commits after selection, and sync selections of `tree`/`record`
  selections.
- Any change to the review rubric: the merge-delta check is used as it is.
- The remainder progress-token composition.
- Moving the delivery scripts into `agent_tools` (#193 D10).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Scope, set by the orchestrator: both gaps in one issue, each meeting its acceptance criterion through a documented route, with regression tests through the real CLIs (`build-delivery`, `control`/`direct-owner`, `checkpoint-delivery`, `finish`, `artifact-budget validate-report`) and the ship-issue/from-issue/CLAUDE.md wording. Out of scope: #191's replies, review-rubric changes beyond what re-selection needs, and hand repair of `run-20260923-…`. | The owner filed both gaps together with one acceptance list. They share the contract-binding subsystem and one incident. | Splitting into two issues. |
| D2 | Gap 1: the contract takes its branch from the live worktree's checked-out branch, and only when the worktree name is not an issue branch (fallback only). The recorded slugless path stays the custody and `remove_worktree` target. No relocation, and no ledger write. Refines SPEC171 D4. | The issue's Expected, option 1. #193 D2's fallback-only precedent. SPEC171 D8/D25/D44 and #117 ("never silently relocate"). Intent re-derivation reads the branch from the contract, so the contract re-derives after the worktree is gone. | A re-home migration: a relocation verb and ledger write that break custody immutability, and it moves a worktree a suspended owner may hold. The live branch always authoritative: it re-derives or refuses every existing path, including #181's non-git fixture, and reads git on every build. |
| D3 | The builder stays pure. A predicate, `requires_worktree_branch`, gates a read-only `live_worktree_branch` probe in workflow-state: a non-symlink directory, a `realpath`-equal `--show-toplevel`, `symbolic-ref --quiet --short HEAD`, and `git` by name with a 60-second timeout. Its result enters through a `worktree_branch` keyword, and the builder re-checks it. The provenance digest gains `branch` only for a live-derived branch. | #193 D5's predicate-plus-value shape and its no-I/O builder. The `git`-by-name precedent (adopt, conformance, instruction_load, diff_scope). An in-flight adapter's unchanged build command is served (#193 D3). Byte identity for today's inputs. | A caller-supplied `branch` input: it changes three build sites' prose, leaves in-flight callers stranded, and makes the derivation agent-asserted. An exception-driven rebuild (rejected by #193 D5). Always hashing `branch` in: it re-bytes every contract, while the contract body already carries the branch. |
| D4 | The existing refusal text stays as the prefix, and one reason clause is appended: absent, not a directory, not a worktree top level, detached, git failure, or a live branch outside the pattern. | The bar: the log stream is the debugger. #193 D7 (existing texts kept, with the `branch pattern` pins). SPEC171's exit 2 with empty stdout. | A generic refusal, which hides why the fallback failed. New replacement texts, which break pinned diagnostics. |
| D5 | AUTO.md's `expected_branch` is the owner contract's reviewed-slot branch, still matched against the binding regex and against `branch --show-current`. No other prose changes for gap 1. | The orchestrator's finding that the branch-equals-path assumption lives there. A grep of the skill tree finds no other one (candidates are absent, so rule 1 holds). The bar: DRY, with the builder owning the rule. | Leaving AUTO.md alone: a resumed legacy owner would fail its own continuation check. Re-deriving the branch from the path in prose: a second home for the builder's rule. |
| D6 | Gap 2: a sync after selection selects a successor. `selected-output/v2` carries `sync{predecessor_id, first_parent, integration_parent}`. A slot's selections form one chain from its v1 root, and the tip is the current binding for every slot use. Earlier selections stay in history. Refines SPEC151's "binds once / a second value conflicts" to "binds once per reviewed head, in one chain". | #117: "a new output requires explicit selection/revalidation … retaining the previous selection in history". SPEC151's slot narrowing: the constraints are unchanged, so no new grant is needed. The issue's Expected, option 1. It works for already-installed contracts. | A sync stage before selection (the issue's option 2): it narrows the window but cannot close it, Phase 1 already syncs, and installed contracts would never gain it. Accepting a sync head at merge while the selection stays H0: the merged tree then differs from the data digest the merge scope names ("changed payload never matches"). Replacing the selection: it loses history. A new observation kind for the link: the chain would live outside `selected_outputs`, so `match_scope`'s seam would need observations. |
| D7 | The chain rules are checked on build and on fold: one v1 root, first parent equals the predecessor's head, no forks, no repeats, the evidence is a superset, and the successor is a commit. The tip alone satisfies `implementation_delivered`. A `pr_merged` at a superseded head is rejected, so a merge is final. Integration-parent reachability and the review are the owner's probe and evidence. | The bar: defense in depth, fail loud. SPEC171 ("take only what a probe returns"), where a v1 selection's tree is also owner-probed. | Helper-side git verification of parents: it adds a worktree and object-availability failure mode to one builder kind, and is inconsistent with every other sealed fact. Allowing successors after a merge: that regresses `pr_merged`. |
| D8 | The new builder kind `sync-selection` takes `{contract, predecessor, head, tree, parents, review_ref, test_ref}`. Acceptance evidence is inherited, and review and test ids are added at the new head. The skill fixes `review_ref` as `merge-delta-empty` or `merge-delta-clean` and `test_ref` as `checks`, so a relaunch re-derives the same successor. | SPEC171 D5/D42 (fixed refs, deterministic relaunch). The bar: token economy, since acceptance is not re-stated. A sync does not change what was accepted. | Overloading `--kind selected-output` with optional members: it breaks the closed input and six-key callers already in flight. A free-form review ref, which is not deterministic across relaunches. |
| D9 | The successor's sync merge, merge-delta review (`git show --cc`, with fixes amended into the unpushed merge), push and CI all precede its selection. They run under the guard and the `check-launch` fence with no checkpoint. The selection gate then folds `branch_published`/`pr_opened` at the new head, already true, with the `merge_pr` scope. | SPEC171 D15 (the same lane before the first selection). REVIEW.md's merge-delta precedent. SYNC.md folds sweeps into the merge commit. The guard forbids force pushes, so review has to precede the push. | Re-selecting before the push or CI, which breaks D15's "final CI-green head". A contract stage for the sync push: contracts are immutable, and an unbounded repetition does not fit a linear obligation chain. |
| D10 | A merge refused because the PR cannot merge into its base (`CONFLICTING`, `DIRTY` or `BEHIND`) is a stale-head condition, not an authority denial. No authority observation is recorded for it. | SPEC151: authority verdicts judge whether an effect is permitted, and a rejection stays operative against its declared scope. `merge_conflicts_requires_new_head` was owner-composed. | Recording it as `rejected`: the rejection stays operative against `merge_pr` after the sync, which is the #150 stranding. A reevaluation-evidence builder kind: a wider authority surface for a failure that is not about authority. |
| D11 | The route runs at the merge gate for either custody. The triggers are: the PR cannot merge, the PR head is an unrecorded sync successor of the tip, or the PR merged at such a head (the #194 D7 fold, without a push or CI wait). Every other divergence stays Phase 6's genuinely-blocked stop. There is one merge per successor. | The issue's A2. #194 D7 handed the fold to #192. The bar: truthful terminal states, since a landed merge should fold rather than end `terminal_failed`. | Folding only in-band syncs, which leaves an out-of-band merge at a sync head stranded. Admitting fix commits, which is an implementation change that needs full review. |
| D12 | The route's mechanics live in `ship-issue/CI-MERGE.md` (conditional in the ship-owner profile), and SKILL.md has only pointers. The instruction-load ceilings of every profile whose hot bytes grow are re-measured. | #155's instruction-load discipline (D19 re-measures). CI-MERGE.md owns the Phase 6–7 mechanics. | Inlining the route in SKILL.md (hot) or SYNC.md (hot): it adds hot bytes for a rare route. |
| D13 | Documentation: `build-delivery --help`, the CLAUDE.md delivery bullet, the ship-issue skill and CI-MERGE.md, and AUTO.md. No ADR. SPEC151 and SPEC171 are not edited. | SPEC171 D21 (no ADR home). #193 D11 (help is authoritative, and point-in-time records are kept). | Editing the accepted specs. Founding an ADR tree mid-flight. |
| D14 | Tests use only the existing seams: the builder CLI with a real git worktree fixture, the `control`/`direct-owner` round trips over migrated schema-2 ledgers, the delivery loop through `checkpoint-delivery`/`finish` with `validate-report`, the model facade for rules no builder emits, and the skill pins. | SPEC171 D19, #193 D8/D12. The bar: tests that can fail, with fixtures shaped like production (a real linked worktree). | Importing the private builder, or faking the git probe, which pins internals and misses the subprocess. |
| D15 | Grill: the terms are *sync selection* (a `selected-output/v2`), *selection chain* and *current selection* (the tip). `sync.prior_selection_id` and the builder input `prior_selection` replace D6's `predecessor_id` and D8's `predecessor`. Refines D6 and D8. | Existing vocabulary: `predecessor_intent_id`, the `successor_intent` basis and retry "successors" already name authority and custody lineage. The `prior_attempt`/`prior_remainder` style. The bar: name for intent. | Keeping "successor"/"predecessor", which collides with three lineage meanings in one model. |
| D16 | Grill: no state-schema or interface bump. A sync selection is additive grammar within schema 4 and interface 2, so persisted ledgers stay valid, and an older helper refuses a ledger that holds one without mutating it. | SPEC171 D12, which made additive refinements in place. SPEC151: older helpers reject newer grammar without mutation. | A schema bump: a migration with nothing to migrate, and a second compatibility surface. |
| D17 | Grill: a PR head reached from the tip through a *sync run* yields one sync selection per merge, oldest first, each reviewed on its own, and all of them fold in one checkpoint. A sync run is a first-parent run of two-parent merges whose second parents are confirmed ancestors of `origin/<integration>`. It covers a crash after the push and an out-of-band merge at a multi-sync head. Refines D11's "one merge per successor" and "first parent is the tip". | #150 merged `main` in twice (a `justfile` conflict, then #149's move), so its landed head was two merges above the selection. Each merge's `git show --cc` is its own reviewable delta (REVIEW.md). | One level only, which strands the #150 shape. One selection spanning several merges: the per-link first-parent rule could not be checked, and each combined diff needs its own review. |
| D18 | Grill: the route syncs proactively only on `mergeable: CONFLICTING`. A head that is merely behind is merged as it is, unless the merge is refused because the base requires an up-to-date head. Phase 6's divergence stop gains one exception, a head the route admits. Refines D11. | `.github/branch-protection.json` has `strict: false`, so a head behind `main` still merges here. Without the exception, Phase 6's "never re-review or merge a diverged head" forbids the crash-resume case. | A proactive sync on `BEHIND`: needless merges and CI cycles on bases with no up-to-date rule. Leaving Phase 6 unqualified, which contradicts the route. |
| D19 | Plan: gap 1's refusal text has one home. The builder's `worktree_pattern_refusal(worktree, clause=None)`, which the runtime forwards, composes the kept prefix and any §2 clause. workflow-state's `live_worktree_branch` raises `WorktreeBranchUnavailable` carrying its clause, and the command raises through that helper before any build. The builder composes the live-branch re-check clause itself. A git failure's detail is its first non-empty stderr line, else `exit <code>`, or the start or timeout error. Refines §1 and §2. | The bar: DRY, since two copies of a pinned text must change together. #193 D7 (kept, pinned texts). §1: the refusal is raised "before any build". | Restating the prefix in workflow-state, which makes two homes for one pinned text. Passing a probe failure into the builder as a second keyword, which widens the build seam for a refusal the command can raise first. |
| D20 | Plan: `reduce_delivery` resets `stage_facts` and `postconditions` to their pending skeleton before its intermediate validation of the merged delivery, then recomputes them as today. The final validation still judges the recomputed facts. | Matching is no longer monotone. A sync selection un-matches the `select_reviewed_output`, `publish_branch` and `open_pr` facts observed at the prior head, so validating those stale facts would reject every sync fold (§4: stage facts are recomputed on every fold). | Dropping the intermediate validation, which also guards the merged arrays before facts are computed. Keeping the stale facts, which fails every sync fold. |
| D21 | Plan: the chain binds to the contract's slot everywhere. `match_scope` computes each select stage's current selection once and gives only those tips to `_scope_mismatch`. A slot's selection outside the contract's slot tuple still answers `slot_constraint_mismatch`, and a set that is not one chain raises `conflicting selected outputs`, as the `delivery` validator does. The `sync-selection` builder requires the prior selection to be a commit selection of the contract's reviewed slot, refuses a `head` equal to the prior head before it judges `parents`, and requires both parents to differ from `head`. The final-once-merged rejection reads `a merged selection chain cannot be extended`. Refines §4 and §5. | The bar: defense in depth (the builder refuses, with a named reason, what the model would reject) and fail loud (a fork is invalid state, not a non-match). §5: "a valid selection of this contract". | Returning a mismatch reason for a fork, which hides corrupt state as an ordinary non-match. Leaving a parent equal to `head` to the runtime's generic output validation, which names no reason. |
| D22 | Plan: a Should-fix finding on a sync merge that is already pushed or already landed stops like a Blocking one. No amend can apply it, a fix commit would leave the sync run, and neither fixed `review_ref` would then be truthful. Refines §6's stops. | The bar: truthful terminal states. D8's fixed refs, where `merge-delta-clean` means every Blocking and Should-fix finding was applied. REVIEW.md: `--auto` applies Should-fix findings, so one it cannot apply is surfaced. | Retaining it as durable detail and sealing `merge-delta-clean`, which records a false review state. A third review ref, which reopens D8. |
| D23 | Plan: seams and scheduling. The builder's predicate and rule-2 units run at the runtime facade (`test_workflow_delivery.py`, #193 D12's seam) beside the CLI tests D14 names. No task merges `origin/main`. A task that grows a hot instruction document raises only the breached ceilings, to their measured hot bytes, and names #192 in the profile note (#155 D10). When `instruction-load.json` conflicts, ship-issue Phase 1's sync re-measures on the merged tree. | #193 D12 (the facade seam exists). #155 D10. The #198 plan's D16 and D19 (the ship sync owns `origin/main` and resolves the ceilings file). | Merging `origin/main` mid-plan, which moves the base under reviewed tasks. Pre-raising ceilings with headroom, which #155 forbids. |
