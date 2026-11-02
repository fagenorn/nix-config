# Guarded remote branch deletion, and remainders that wait for a human — issue 458

Design for https://github.com/fagenorn/nix-config/issues/458. Base: `b3236d3f`
(`origin/main`). Approval source: autonomous (`--auto`), decision ledger. A bare
"Dn" cites this spec's ledger; "351 D2" cites
`2026-10-10-issue-351-guarded-command-shape-design.md`, "190" the
`2026-09-26-issue-190-control-idle-remainder-design.md` spec, and "198 D6" the
`2026-09-27-issue-198-ship-reviewer-dispatch-design.md` spec.

## Triage

Input signals: contract_change=hit (new guard form, ship-issue spelling); concurrency_or_persistence=hit (persisted remainder resume policy); open_design_questions=hit (two fix directions, relaunch semantics); criteria_shape=doubt (end-to-end no-human-step criterion); paths lifecycle_guard.py, claude-code/README.md, tests/fixtures/guarded-command-shapes.json, tests/test_claude_permission_guard.py, ship-issue/SKILL.md, ship-issue/HUMAN-GATE.md, workflow_delivery.py, agent-skills/tests/test_delivery_workflow.py. Verdict: `{"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}`. ran: full (shadow)

## Problem

Sometimes `gh pr merge … --delete-branch` merges the PR but leaves the remote
branch in place. Ship-issue then falls back to `git push origin --delete
<branch>` (SKILL.md Phase 7, HUMAN-GATE.md Gate 2 chain). The lifecycle guard
refuses that command (`unsafe push: unknown flag --delete`). The guard's form
table has no remote-deletion form, by design (351 D2). That design was settled
when no remote-deletion refusal had ever been seen. The shape fixture's
`branch.remote` row pins the refusal. So the `delete_remote_branch` delivery
stage has no spelling the guard accepts. DELIVERY-LOOP's denial step then parks
the delivery remainder on `human_gate`.

The parked remainder does not stay parked. The remainder policy resumes any
suspended remainder whatever its `blocked_on` is. In nodocom run
`rel_01a17895-…` (elevenyellow/nodocom#2467) the remainder was relaunched as
`r1:1` → `r1:2` → `r1:3`. Each launch cost 3–5 minutes and about 75k tokens,
and each hit the same refusal. A human unblocked it with an unadjudicated
`gh api -X DELETE`, and the next launch reached `delivery_complete`. The
attempt lane does not behave like this: it resumes a `human_gate`, `external`
or `agent_dispatch` suspension only when the sweep is `human_directed`. But
`orchestrate-control` sends `human_directed: true` on every sweep of an
explicit-number session, so in those sessions the attempt lane's gate is open
on every sweep too.

The owner wants three outcomes. A surviving remote branch is deleted under the
guard with no human step. The guard and ship-issue name one remote-deletion
spelling, and a shape test pins it. A remainder suspended on `human_gate` is not
relaunched in a loop; the session instead finalizes with a human-gate re-entry
line.

## Solution

1. **Guard form.** The push operation gains a third form,
   `git push origin --delete refs/heads/<branch>`. It runs the push arm's
   authorization and branch-name checks and refuses the repository's permanent
   branches (D1, D2).
2. **One spelling.** Ship-issue Phase 7 and the HUMAN-GATE Gate 2 chain spell
   exactly that form. The fixture's `branch.remote` row flips to accepted in all
   three prefix variants, and the old bare spelling becomes a guard-only refused
   shape (D1, D6).
3. **Remainder gating.** The remainder lane takes the attempt lane's consent
   rule. A remainder suspended on a cause that needs a human (`human_gate`,
   `external`) resumes only when the sweep is `human_directed`. Otherwise it
   parks, and the session finalizes with its re-entry line (D3).
4. **Direction is spent once.** `orchestrate-control` sends `human_directed`
   true only on the first sweep of an explicit-number session. A gated
   suspension that arises later in the same session waits for the human, in
   both lanes (D4).

## Decisions

### The remote-deletion form (AC1, AC2)

`FORM_TABLE["push"]` gains a third form, after `tag` and `branch`, with id
`delete` and template `git push origin --delete refs/heads/<branch>`. The
`<branch>` slot is glued to the literal `refs/heads/`, like the tag arm's
`refs/tags/<vX.Y.Z>`. The form inherits the push operation's properties and
handling unchanged:

- the whole-text character rule;
- the optional scrub prefix (`unset GITHUB_TOKEN && `, `env -u GITHUB_TOKEN `
  and the other members of the accepted set);
- one `git -C <dir>`, whose directory becomes the repository context;
- per-segment judgment;
- the place in the refusal's accepted-forms list, now third.

The table compiles at start-up as before, and `--delete` joins the push
operation's known flags.

The ref is qualified because git resolves a bare deletion target against the
remote's refs. git-push(1) says: "If `<dst>` unambiguously refers to a ref on
the `<repository>` remote, then push to that ref." So
`git push origin --delete v1.2.3` deletes a release tag when no branch of that
name exists. The bare form would let the guard approve a tag deletion it could
not tell apart from a branch deletion. The qualified form can only name a
branch (D1).

Judging an accepted match, in order (D2):

1. **Standing authorization.** Same as every repository-bound verb: the owner is
   in the base policy's `authorized_owners`, or the repository has a derived row
   that the row check confirmed. Checked before the match, as the push arm does
   now.
2. **Branch name.** The slot value passes the push branch arm's name rule: not empty,
   no leading dash, no `:` or `+`, no unsafe character, no namespace component
   (`refs/heads/refs/heads/x` is refused), and `git check-ref-format --branch`.
   A failure is a text refusal that prints the accepted forms.
3. **Default branch resolvable.** If `origin/HEAD` cannot be resolved, refuse
   with `cannot resolve the repository default branch`.
4. **Not a permanent branch.** If the value is the default branch, or the
   repository's declared integration branch (from `integration_bases` or a
   confirmed derived row), refuse with
   `refusing to delete the permanent branch <branch>`. This is a state refusal:
   it names only its problem, like the default-branch push refusal, because no
   spelling would pass.

There is no forge lookup: no protection read and no merged-PR check. GitHub
refuses to delete a protected branch on its own side, and ship-issue runs the
deletion only after it has verified the merge and seen a non-empty
`git ls-remote --heads origin <branch>`. Like the push branch arm, the guard
does not judge *which* feature branch is named (D2).

Verdicts the plan pins (the default branch is `main`; in the integration
repository the integration branch is `dev`):

| Command | Verdict |
|---|---|
| `git push origin --delete refs/heads/issue-458-topic` (bare, behind either prefix, behind `git -C <root>`) | allowed |
| `git push origin --delete issue-458-topic` (the old spelling) | text refusal; the accepted list includes the qualified form |
| `… --delete refs/heads/main`; `… --delete refs/heads/dev` in the integration repository | `refusing to delete the permanent branch …` |
| `… --delete refs/tags/v1.2.3`, `… refs/heads/a refs/heads/b`, `-u` added, `--delete` before `origin`, `-d` | text refusal |
| the qualified form in an unauthorized repository | `outside standing authorization` |

Branch deletion with `git branch -d`, the tag arm, the branch arm and the
merge's `--delete-branch` do not change.

### One spelling (AC2)

Ship-issue Phase 7's fallback and the HUMAN-GATE Gate 2 chain item spell
`git push origin --delete refs/heads/<branch>`, still citing `## gh hygiene`.
The deletion is an `origin` call, so `## gh hygiene`'s rule already allows the
credential-scrub prefix on it. The fixture's `branch.remote` row keeps its id,
its sites (`SKILL.md`, `HUMAN-GATE.md`) and its label `push`. Its template
becomes the qualified form, and all three variants expect exit 0. The
shell-example contract (R1–R3) then requires both documents to spell that exact
template. The old bare spelling becomes a guard-only `invocation_shapes` row
with exit 2, because it is a shape agents still reach for (D6).

The guard README's `## Adjudicated verbs` changes in four places:

- the push sentence lists the remote-deletion arm beside the tag arm as the
  second exception to "no delete flags, no namespaced refs";
- the paragraph after it describes the delete arm's checks;
- the shape-fixture sentence names the remote deletion among the forms
  ship-issue spells;
- the refusal taxonomy lists the permanent-branch deletion among the state
  refusals.

The two spelling edits add the `refs/heads/` prefix twice, 22 bytes. Measured
at the base, that puts the `ship-owner` profile's conditional load 5 bytes over
its ceiling on both hosts. So the same edits trim at least that much from the
lines they touch. For example, HUMAN-GATE's "only when … is non-empty" becomes
"if … is non-empty", which passes the gate in a trial. `just
agent-instruction-budget` passes without the raise label, and no ceiling moves
(D7).

### Remainder resume gating (AC3)

The remainder lane uses the attempt lane's consent rule (D3):

- **Gated causes.** A suspended remainder whose `blocked_on` needs a human
  resumes only when the sweep is `human_directed`. Gated means in
  `BLOCKED_ON_VALUES − AUTO_RESUMABLE_BLOCKED_ON`, i.e. `human_gate`,
  `external` and `agent_dispatch`. The remainder vocabulary carries only the
  first two.
- **Auto-resumable causes.** `transport`, `unknown` (the reaper's),
  `host_capacity` and the remainder-only `owner_unavailable` resume as today.
- **One home.** The gated set is defined once, beside `AUTO_RESUMABLE_BLOCKED_ON`
  in the attempt-custody module. Both lanes read it, so a cause added to the
  vocabulary is classified in one place. The attempt lane's behavior does not
  change.
- **Plumbing.** The delivery policy takes `human_directed` as an input.
  `control` passes its request's value, and `direct-owner` passes `true`, as it
  already does for the attempt lane.

A parked remainder takes the attempt lane's parked verdict:

- operation and desired outcome `terminal`, and `changed` false;
- no `delivery_remainder` action;
- no capacity charge, and no entry in `admission.waiting`;
- no write to the issue's ledger entry (the sweep's own controller bookkeeping
  is unchanged);
- a summary that reads `suspended`, its `blocked_on` and `custody.kind`
  `remainder`.

There is no schema change and no migration. A live ledger's remainder that is
already parked on a gated cause simply stops being relaunched by undirected
sweeps from the next sweep on.

A parked suspension arms no deadline, so once nothing else runs the sweep ends
in `finalize`. The orchestrate report already renders
`/from-issue <issue> --auto` for these causes (orchestrate-issues §5), which is
the re-entry line the issue asks for. The rule sits ahead of the remainder's
dispatch-permitted, worktree-requirement and resume steps, so the analysis pass
and the dispatch pass agree. The `failed` (stalled) and live-custody branches
keep their order before it.

### Direction is spent on the first sweep (AC3)

`orchestrate-control step` builds each `control` request with
`human_directed = session.human_directed and first_sweep` (D4). Both calls of a
first step carry it, including the chained `delivery_contract` round. A label
or milestone session sends `false` as before. The session object, the `start`
output and the control request schema do not change. Only the value sent on
later sweeps does.

Effect:

- Re-invoking `/orchestrate-issues <numbers>` (or `--run-id` with numbers) is a
  human's direction, and it resumes records that were already parked on a gated
  cause when it started. This is the route that completes the nodocom remainder
  once this fix is installed.
- A record that parks on a gated cause later in that session waits. Each later
  sweep sends `false`, so it is neither relaunched nor charged a slot, and the
  session finalizes with its re-entry line. The same now holds for the attempt
  lane: an explicit session used to relaunch a gated attempt on every sweep
  until the anti-zombie bound stopped it as `stalled`.
- `/from-issue <n> --auto` still always clears it: every direct invocation is
  one direction.

Accepted corner: a gated record that was parked at session start but was not
dispatched on the first sweep stays parked for that session. That happens when
no slot was free, or when the first step refused before `control` answered. Its
`finalize` summary carries the re-entry line. Nothing loops and nothing is
misreported (D4).

Docs:

- the `human_directed` paragraph of the issue policy's docstring says "on the
  session's first sweep";
- `python/README.md`'s `orchestrate-control step` contract states the
  per-sweep value;
- no skill text changes.

### Acceptance evidence

AC1 ("completes `delete_remote_branch` under the guard with no human step") is
met at merge by composition, with no `needs-verification` hold (D5). Four links
make it up:

1. The guard allows ship-issue's exact spelling, bare and behind both prefixes,
   in an authorized repository (the shape table).
2. Gate 2's grant already names the deletion, so no new human step appears.
3. A git-level test shows that the form, run against a local bare remote,
   removes the named branch and leaves a tag of the same name alone.
4. The rest of the chain is already evidenced: the observed `r1:4` reached
   `delivery_complete` once the branch was gone.

AC2 is the flipped `branch.remote` row, which the guard's shape table and the
shell-example site check both read. AC3 is the composition of two seams: the
engine parks a gated remainder under an undirected sweep, and `orchestrate-control`
sends an undirected request on every sweep after the first.

## Test seams

- **Guard suite through the built guard** (`tests/test_claude_permission_guard.py`).
  The shape table (#351) runs the flipped `branch.remote` row and the new
  refused invocation shape from the fixture. The push grammar table gains the
  qualified-form cases from the verdict table above. Its existing
  `git push origin --delete topic` refusal row stays valid unchanged. The
  integration-repository case reuses the derived-row fixture repository the
  printed-forms test already builds. The printed-forms test (#402 D13) counts
  three push forms and fills the new one from `form_values`. One git-level test
  fills the fixture template and runs it against a local bare remote that holds
  a branch and a tag (D5). The adversarial table stays green and unchanged.
- **Shell-example contract suite** (`test_shell_example_contracts.py`, #351
  R1–R3). It reads the fixture, so the two documents' spelling is checked with
  no new test.
- **Delivery workflow suite through `workflow-state control`**
  (`test_delivery_workflow.py`, the 190 `remainder_sweeps` fixture). Three
  cases, which follow 198 T2 for the attempt lane:
  - A `human_directed: false` sweep over the `human_gate` remainder emits no
    `delivery_remainder`, ends in `finalize`, reports
    `suspended`/`human_gate`/`remainder`, and leaves the issue's ledger entry
    unchanged.
  - A `human_directed: true` sweep resumes it.
  - An auto-resumable cause (`owner_unavailable`) resumes without direction.

  The existing 190 tests that depend on control resuming the fixture's
  `human_gate` remainder send `human_directed: true` (D6). That includes the
  absent-worktree `finalize` test, which exercises the resume ladder's worktree
  check.
- **orchestrate-control facts suite** (`tests/test_orchestrate_control.py`,
  `OrchestrateWorld` request capture). For an explicit session, the control
  request carries `human_directed` true on a `first_sweep` step and false
  otherwise. A label session sends false on both.

## Out of scope

- Adjudicating `gh api`. `gh api -X DELETE …/git/refs/heads/…` stays
  unadjudicated and is not a sanctioned path.
- The stall bound. The remainder's stall counter and `STALL_LIMIT` are
  unchanged.
- Why `gh pr merge --delete-branch` sometimes leaves the remote branch. The
  fallback covers it, and the cause is gh's.
- Tracking direction per issue across sweeps, which would close the capacity
  corner (D4).
- Any `orchestrate-issues`, `from-issue` or DELIVERY-LOOP text change.
  §5's re-entry rule already covers the new parked remainders.
- The #351 and #402 specs. They are point-in-time records and stay as written,
  and this ledger records the reversal.
- Codex. It has no hook, and the qualified spelling runs natively there.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Remote deletion gets a guard-owned push form `git push origin --delete refs/heads/<branch>` (third push form, id `delete`, push properties inherited); ship-issue spells exactly it. This reverses 351 D2's rejection of a remote-delete arm | Issue's observed nodocom run: the refusal class 351 D2 found absent has now occurred; FORM_TABLE is the one home for spellings (#402); the tag arm is precedent for a glued qualified slot; git-push(1) says a bare `<dst>` that names one remote ref is pushed to that ref | Bare `--delete <branch>`: git deletes a remote tag that the bare name alone matches. `gh api -X DELETE` or another unguarded spelling: unadjudicated (issue). `:<branch>` refspec: the refspec refusal would have to be carved open |
| D2 | The delete arm checks standing authorization, the push branch arm's name rule, a resolvable default branch, and refuses the default or declared integration branch as a state refusal (`refusing to delete the permanent branch <b>`); no forge lookup | Issue fix direction ("owned-repo and non-protected-branch checks like the push arm"); #116 D5's permanent-branch set; GitHub refuses protected-branch deletion server-side; ship-issue deletes only after verifying the merge and `ls-remote` | Protection or merged-PR lookup: a forge round trip per cleanup that fails closed without gh auth or network, re-parking cleanup on `human_gate`, the failure this issue removes |
| D3 | The remainder lane takes the attempt lane's consent rule: `human_gate`/`external` resume only under `human_directed`, other causes as today; a parked remainder is the no-dispatch `terminal` verdict with an unchanged ledger; the gated set has one home beside `AUTO_RESUMABLE_BLOCKED_ON`; the delivery policy takes `human_directed` (direct: true) | 190's deferred question; the attempt lane's suspended-lane predicate and 198 D6/T2; HUMAN-GATE "Silence is not a grant … stay suspended (`--auto`)"; issue: "instead of finalizing with a human-gate re-entry line" | Remainder-only rule (control never clears, only direct does): a second consent rule beside the attempt lane's, and a re-invoked explicit session could not resume the remainder this fix unblocks |
| D4 | `orchestrate-control` sends `human_directed = session.human_directed and first_sweep`, so an explicit session's direction is spent on its first sweep in both lanes; a gated record not admitted on that sweep stays parked for the session and is reported with its re-entry line | The policy docstring: direction is "a person asked for this re-entry by name"; a direct owner's direction is one call per invocation; `first_sweep` already gates per-session work (contracts); the investigation note on every-sweep direction | Direction on every sweep (today): relaunches gated records each sweep up to the stall bound. A direction timestamp in the request and ledger: interface and schema changes for the capacity corner alone. Using the stall counter as consent: conflates progress with consent |
| D5 | AC1 is met at merge by composition: the shape table on the exact spelling, Gate 2's existing grant, a git-level test that the form deletes only a branch, and the observed `r1:4` completion; no `needs-verification` hold | Issue § Observed; criteria_shape doubt resolved by testing the one failing link offline | A live-run hold (351 D10 style): the trigger, gh leaving the remote branch, is rare and unscheduled, so the issue would stay open indefinitely |
| D6 | Test seams: the fixture's `branch.remote` row flips to exit 0 in all three variants and the bare spelling becomes a refused guard-only invocation shape; existing 190 remainder tests that rely on control resuming a `human_gate` remainder send `human_directed: true` | #351 fixture split (skill forms vs guard-only rows); the-bar "Tests that can fail": the flipped tests now state the consent they exercise | Deleting the `branch.remote` row: AC2 asks for a shape test on the shared spelling. Leaving those 190 tests on `false`: they would assert the loop this issue removes |
| D7 | Skill-text growth from the new spelling is paid for inside the touched ship-issue lines, so the Instruction Budget gate passes with no ceiling change and no raise label | Trial at base `b3236d3f`: +22 bytes put `ship-owner` conditional 5 bytes over its ceiling on claude and codex, and a 7-byte trim passes; the user's rule that only they apply `instruction-budget-raise` | Raising the ceiling: needs the user-only label. Shortening the form back to the bare spelling: reopens the tag hazard D1 closes |
| D8 | The gated set is `HUMAN_GATED_BLOCKED_ON = BLOCKED_ON_VALUES - AUTO_RESUMABLE_BLOCKED_ON` in `python/agent_tools/attempt_custody.py`; `workflow_delivery.py` imports it from `agent_tools`; `human_directed` is a required keyword (no default) of `delivery_policy` and `remainder_policy`; the park check sits right after the live-custody branch; the attempt lane's predicate keeps reading `AUTO_RESUMABLE_BLOCKED_ON` | D3's one home; the-bar fail loud (a caller that omits consent raises, never defaults); `workflow_delivery.py` runs only inside `workflow-state`'s process, which already imports `agent_tools`, and agent-helpers rule 3 bans import machinery, not a package import; the attempt predicate already partitions `BLOCKED_ON_VALUES` by `AUTO_RESUMABLE_BLOCKED_ON` | A `human_directed=False` default: a forgotten caller gates silently. Passing the set in as an argument: a second home for the classification. Rewriting the attempt predicate as `not in` the gated set: an open denylist and churn in a lane D3 leaves unchanged |
| D9 | Test seams the plan adds: `tests/test_attempt_custody.py` `VocabularyTest` pins the gated set; direct `delivery_policy`/`remainder_policy` calls in `test_workflow_delivery.py` and `test_delivery_model.py` pass `human_directed=True` (D6 extended); `remainder_sweeps`'s `control` takes `human_directed`, default true, the consent its existing callers exercise; the `owner_unavailable` case rewrites the persisted remainder's `blocked_on` after the fixture parks it | Planning trial at `7a92d5b4`: exactly 11 existing tests depend on an undirected resume of the fixture's `external`/`human_gate` remainder; no control path the 190 fixture drives writes `owner_unavailable` (only the transaction core does) | A per-cause unit table at `remainder_policy`: a seam the spec did not agree. Driving a host-reported unavailable owner: no ledger path yields the cause. A required `human_directed` in the helper: a dozen call-site edits with no consent change |
