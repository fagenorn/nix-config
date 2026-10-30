# Self-describing observe requirements, and workflow-state replies pinned to the workflow-response boundary — issue 473

Design for https://github.com/fagenorn/nix-config/issues/473. Base: `8212d8fb`
(`origin/main`). Approval source: autonomous (`--auto`), decision ledger. A bare
"Dn" cites this spec's ledger.

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "the direct-owner observe requirement objects and the workflow-response validator's closed shapes change"}, "concurrency_or_persistence": {"value": "no", "evidence": "observe responses and subcommand stdout are not persisted; no ledger schema change"}, "open_design_questions": {"value": "hit", "evidence": "where the observation description lives and how register-worker output becomes valid are open"}, "criteria_shape": {"value": "no", "evidence": "four criteria, each measured by a named test or just agent-workflow-tests"}}, "paths": ["home/common/agent-skills/scripts/workflow-state.py", "home/common/agent-skills/scripts/delivery_model/_wire.py", "home/common/agent-skills/skills/from-issue/acquire-direct.md", "home/common/agent-skills/tests/test_workflow_state.py", "home/common/agent-skills/tests/test_workflow_skill_contracts.py"]}
Verdict: {"hits":["contract_change","open_design_questions","risk_path"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

A direct autonomous owner acquires an issue by calling `workflow-state
direct-owner` until it stops answering `kind: observe`. Each observe reply
names what it wants as bare requirements, such as `{"kind":"tracker"}` or
`{"kind":"forge_pr","path":"issue-73-"}`. Nothing in the reply says which
request member the answer goes in, or what members and values that answer
has. `direct-owner --help` lists only `--repo-root` and `--request-file`. The
shapes are written down only in from-issue's `acquire-direct.md` (which lists
the requirement shapes but not the observation shapes) and in the helper
source. In the Oct 21–30 retro, about 37 of 177 Claude transcripts read helper
source in the store three or more times to learn JSON shapes. One nodocom
session spent about 12 rounds on `direct-owner` alone.

Separately, from-issue's lifecycle-call rule says to pipe *each*
`workflow-state` reply through `artifact-budget validate-report --boundary
workflow-response` before decoding it (only `resume-pack` is exempt). Yet
`register-worker`, `release-worker` and `mark-progress` print objects the
validator rejects. A Codex nodocom run followed the rule on `register-worker`
and failed (rollout 2026-10-29T19-59-39). `build-delivery` prints sealed
delivery values that are not workflow responses either, but the rule does not
exempt it. No test ties the skills' pipes to the helper's real output.

## Solution

1. Every requirement in a direct-owner `observe` reply carries an `expects`
   member. It names the request member the answer fills (`slot`), describes
   that answer's members and gives an `example` of it. For the one requirement
   whose answer is built rather than observed (`delivery_contract`), `build`
   names the builder command. The descriptions live in one new package module.
   That module is also the home of the tracker, forge and worktree observation
   vocabulary the request validators check, so a description cannot drift from
   what the helper accepts. `direct-owner --help` names `expects`.
2. The workflow-response validator gains a closed check for `expects` on
   observe replies. It also gains exact-member branches for the
   `register-worker`, `release-worker` and `mark-progress` replies. from-issue's
   lifecycle-call rule now exempts `build-delivery` beside `resume-pack`.
3. A contract test reads every `workflow-state` subcommand the skill texts name.
   It drives each one through the real CLI and pipes its stdout through the
   `workflow-response` boundary, so a skill can no longer name a reply that the
   validator rejects.

## Decisions

### The `expects` member (per D1, D2)

The observe envelope is unchanged: `interface_version`, `kind`, `issue`,
nullable `run_id`, `requirements`. Each requirement keeps its present members
and gains `expects`, a closed object with exactly these members:

- `slot`: the direct-owner request member the answer is sent in.
- `members`: an object mapping each member name of that answer to a one-line
  meaning. Where a member has a closed value set, the meaning lists it, derived
  from the same constant the request validator checks. Where a member is an
  array of objects, the meaning names the element's members.
- `example`: one illustrative answer with exactly the keys of `members`.
- `build`: `null` when the owner observes the answer and sends an
  `example`-shaped value. Otherwise it is the `workflow-state` command line,
  with `<ledger_repo_root>` as the only placeholder, that turns an
  `example`-shaped input into the slot's value.

The catalogue is closed over the five kinds a direct-owner observe can return:

| kind | slot | build | example (issue 73) |
|---|---|---|---|
| `tracker` | `tracker` | null | `{"issue":73,"state":"open","open_blockers":[],"decision_blockers":[]}` |
| `recorded_worktree` | `worktree` | null | `{"issue":73,"recorded":{"path":"/repo/.worktrees/worktree-issue-73-example","state":"matching_issue_branch"},"candidate":null}` |
| `candidate_worktree` | `worktree` | null | `{"issue":73,"recorded":null,"candidate":{"path":"/repo/.worktrees/worktree-issue-73-example","state":"absent"}}` |
| `forge_pr` | `forge` | null | `{"state":"none","url":null,"merge_sha":null}` |
| `delivery_contract` | `delivery_contract` | `workflow-state build-delivery --repo-root <ledger_repo_root> --kind contract --input -` | `{"issue":73,"worktree":"/repo/.worktrees/worktree-issue-73-example","source_kind":"explicit_user","source_reference":"invocation:/from-issue 73 --auto"}` |

`members` for the two worktree kinds are the same three names. Their meanings
say that the request carries one `worktree` object for both kinds: the member
a requirement asked for is set, and any member asked for earlier in the same
acquisition is kept. The `delivery_contract` members describe the builder
input. The builder prints `contract` and `initial_intent`; sending them as
`delivery_contract` and as the only `authorization_intents` member stays in
`acquire-direct.md`. The example omits the builder's optional `now`, because
the builder stamps it.

Each kind's whole `expects` is constant. Its example is illustrative (issue
73, the same issue as `acquire-direct.md`'s request example), and its `build`
keeps the `<ledger_repo_root>` placeholder. Nothing is filled from the live
reply. A tracker or worktree example pasted verbatim for any other issue is
therefore refused by the request's issue-match check, instead of passing as a
fabricated observation.

Descriptions are attached only where the observe envelope is built, after the
one-issue policy has decided. The reply keeps `interface_version` 2 (per
D9). The policy, its requirement comparisons, control summaries and
delivery-block `requirements` keep their present bare shapes (per D4). A requirement kind with no catalogue entry is a closed-set miss. It
refuses the call as a helper error (exit 2, empty stdout) and never sends a
reply without `expects`.

### Vocabulary home (per D3)

A new standard-library module in `agent_tools` holds the observation
vocabulary and the `expects` catalogue. Its name follows the `attempt_*`
family, e.g. `attempt_observations`. The vocabulary is the tracker, decision
blocker and forge member sets, their state sets, and the worktree observation's
member, `recorded`/`candidate` member and state sets. `workflow-state.py`
imports the tracker and forge constants it defines today, and the worktree
validator in the delivery wire module imports the sets it now writes as
literals. Both files keep their validation logic unchanged; only the constants
move. The module exposes the closed kind set and one function that returns a
requirement with its `expects` attached. It does no I/O and imports nothing
from the flat scripts.

The contract builder's input member set stays with the builder, since it is
the builder's own contract and includes `now`. A test pins the
`delivery_contract` description's members to that set minus `now`.

### `direct-owner --help` (per D1)

The `direct-owner` subparser gains a `description`, following the precedent
of `build-delivery` and `owner-liveness`. It says that the command acquires,
resumes or replays one issue's direct owner from one interface-2 request and
prints one `observe`, `owner`, `delivery_remainder` or `terminal` reply. It
also says that each requirement of an observe reply carries `expects`, and
names its four members.

### Workflow-response validator (per D4, D6)

- **Observe replies.** These get their own requirement check, separate from the
  shared one that control summaries and delivery blocks use. It accepts only
  the five direct kinds, with their present members plus `expects`, and no
  requirement may appear twice. `expects` must have exactly the four members.
  `slot` must match the kind as in the table above. `build` must be null for the four observed kinds and a
  non-empty string for `delivery_contract`. `members` must be a non-empty
  object of non-empty strings. `example` must be an object whose key set equals
  the key set of `members`. The validator does not compare the description with
  the catalogue: the delivery model stays a self-contained library, and the
  catalogue's content is the tests' job. The kind-to-slot table is therefore
  kept twice, once on each side of the trust boundary, as the validator already
  keeps its own launch-reason set. The AC1 scenarios pin the two copies
  together. The shared requirement check is unchanged, so control summaries
  keep their shape.
- **Worker and progress replies.** Like the check-launch reply, these are
  matched by exact member set. Each branch sits before the kind-less
  control-response fallback.
  - `register-worker`, members `{worker_id, launch, parent}`: `launch` is a
    launch id; `worker_id` is `<launch>:w<n>`; `parent` is null or a worker id
    of the same launch.
  - `release-worker`, members `{worker_id, release_event, released}`:
    `release_event` is `returned` or `stopped`; `released` is a list of unique
    worker ids of `worker_id`'s launch, either empty or containing `worker_id`.
    For `returned` it is `[]` or `[worker_id]`.
  - `mark-progress`, members `{action_id, outcome, marker}`: `outcome` is one
    of `baseline`, `advanced`, `unchanged`, `diverged`; `marker` is a 40- or
    64-character lowercase hex commit id.

  The helper's output for all three is unchanged.

### Which replies are workflow responses (per D5)

Every `workflow-state` subcommand that a skill text names is a workflow
response, except `build-delivery` (sealed delivery values, which the next
request's own validation checks) and `resume-pack` (already exempt). from-issue's
lifecycle-call rule is reworded to name both exemptions. The subcommands named
today are `direct-owner`, `check-launch`, `current-launch`, `progress`,
`finish`, `suspend`, `checkpoint-delivery`, `owner-liveness`, `host-route`,
`control`, `init-run`, `register-worker`, `release-worker` and `mark-progress`.
`declare-lane`, `check-worker`, `migrate` and `finish-delivery` are named by no
skill, so they stay out of scope until a skill names one.

### Skill and doc text (per D7)

- `acquire-direct.md`: the observe step stops spelling out the five exact
  requirement shapes, because the validator now enforces them and `expects`
  describes each one. It points at `expects` instead: `slot`, `members`,
  `example`, and `build` when non-null. It keeps the observation rules (observe
  only what each asks, and how), the builder example block, the
  contract-to-slot mapping and the fail-loud rules.
- `from-issue/SKILL.md`: the lifecycle-call rule's exemption clause names
  `build-delivery` and `resume-pack`, and keeps "a resume pack stays untrusted
  until its checks pass".
- The instruction-budget gate is a required CI context, and raising a ceiling
  needs a label that only a human applies. Current headroom is 45 bytes for
  `from-issue-controller` (which loads both files) and 18 bytes for
  `implementation-owner` (which loads `SKILL.md` alone). Each edit on its own
  must therefore be byte-neutral or shrinking. `just agent-instruction-budget`
  must pass.
- `home/common/agent-skills/README.md` § Lifecycle helpers gains a short
  "Direct-owner observations" subsection. It covers `expects` and its members,
  where the catalogue lives, and the rule that every skill-named reply except
  the two exemptions passes the `workflow-response` boundary.

## Test seams

All seams are existing CLI boundaries driven from source.

- **Every kind is described (AC1).** In `test_workflow_state.py`, using
  `LifecycleHarness`: one table maps each kind in the module's closed kind set
  to a scenario that makes `direct-owner` return it. The scenarios are the
  first call for `tracker`, an unobserved forge for `forge_pr`, a new run for
  `candidate_worktree`, a resume for `recorded_worktree` and a missing contract
  for `delivery_contract`, following the existing acquisition tests. Each reply
  passes `validated_response`, and its requirement carries `expects` with
  non-empty `members` and an `example` with matching keys. The table's keys
  must equal the closed kind set, so a kind without a scenario fails, and so
  does a kind the envelope cannot describe. Each example must be accepted by
  the consumer that reads it. For the four observed kinds, the example is
  placed in its `slot` of an otherwise-empty issue-73 request, and that
  request must pass the helper's request validation (the script loaded from
  source, as `test_delivery_workflow.py` already calls
  `validate_direct_owner_request`). The `delivery_contract` members must equal
  the builder input set minus `now`.
- **Help names `expects` (AC2).** In `test_workflow_state.py`: `workflow-state
  direct-owner --help` exits 0, and its stdout names `expects` and each of its
  four member names. These are machine names, not English phrases.
- **Skill pipes match the validator (AC3).** In
  `test_workflow_skill_contracts.py`, with the harnesses that sibling suites
  already import: `DeliveredControlHarness` for runs with installed contracts,
  and `LifecycleHarness` for direct acquisition. The driver table follows the
  per-subcommand argv table in `test_attempt_custody.py`
  (`MisbindingTest.transports`). The test collects every `workflow-state
  <name>` in the skill trees (shared, Claude-only and Codex skills, `evals/` excluded),
  keeps the names that are subcommands of the helper's own parser, and removes
  the two exemptions. That derived set must be covered by a table of drivers.
  Each driver produces one real reply in the argv form the skills use (for
  example `finish --summary-file -`). Every reply must pass `artifact-budget
  validate-report --boundary workflow-response` unchanged. Every explicit
  `| artifact-budget validate-report` pipe that follows a `workflow-state` call
  in the skill text must name `--boundary workflow-response`. A skill that
  starts naming another subcommand turns the test red until a driver exists and the
  reply validates. This follows the agent-helpers rule that skill-text tests may
  pin `workflow-state` argv.
- **The validator refuses bad shapes.** In `test_delivery_model.py`, following
  its existing observe and requirement refusal cases: an observe requirement
  without `expects`, with an extra member, with a wrong `slot`, with `build`
  set or missing for the wrong kind, with `example` keys that differ from
  `members`, and with a control-only kind (`scope_tuple`) are each refused. A
  `checkpointed` reply whose requirements carry `expects` is also refused, so
  the shared shape is unchanged. Mutated register, release and mark-progress
  replies are refused: wrong launch, unknown event, `released` without the
  worker, unknown outcome, and a short marker. The `_delivery_model_fixtures`
  observe fixture and the existing tests that pin bare observe requirements
  are updated to the new shape.
- **Prose pins.** `test_direct_auto_observe_owner_terminal_loop_is_closed`
  stops pinning the five literal shapes and pins the `expects` key set instead,
  which is a JSON key set of a lifecycle contract. The resume-pack exemption pin
  stays green.
- `just agent-workflow-tests`, `just agent-instruction-budget` and `just build`
  pass.

## Out of scope

- The orchestrate-control owner-observation shape, and control-summary
  requirement shapes: https://github.com/fagenorn/nix-config/issues/469.
- Moving the observation validators or `workflow-state.py` into `agent_tools`.
  Only the vocabulary constants move; the cluster move belongs to its own PR.
- Describing the direct-owner request shape in `--help`. `acquire-direct.md`
  holds it.
- Validating `build-delivery` output at any `validate-report` boundary, and
  adding `declare-lane`, `check-worker`, `migrate` or `finish-delivery` replies
  to the validator.
- Adding `kind` discriminators to the worker and progress replies.
- Raising any instruction-budget ceiling.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Each direct observe requirement carries an inline `expects` member, attached when the envelope is built; `direct-owner --help` gets a `description` naming `expects` and its members | Issue demo: the observe reply itself "shows the member names and an example"; the bar's token economy (one place, read when needed); the `build-delivery`/`owner-liveness` `description=` precedent | A separate catalogue the reply points at (a `--describe` mode or a doc path): the reply would not show the shape, and it adds a command surface to keep in step |
| D2 | `expects` = `{slot, members, example, build}`: `members` maps each name to a meaning with any closed value set; `build` is non-null only for `delivery_contract` (the builder argv); each kind's whole `expects` is constant, with an illustrative issue-73 example and a `<ledger_repo_root>` placeholder | Retro: the rounds were spent finding the slot and state values, which a bare name list does not give; an issue-73 example pasted for another issue fails the issue-match check | `members` as a bare name list (loses value sets); filling the example or `build` from the live reply (pasteable as a fabricated observation, and no longer a pure constant); folding the builder into `slot` (hides that the value is built, not observed) |
| D3 | A new pure `agent_tools` module owns the tracker, forge and worktree observation vocabulary and the `expects` catalogue; `workflow-state.py` and the delivery wire module import the constants; validators stay put; the builder input set is test-pinned, not moved | agent-helpers rule 1 (new helper code goes in the package) and rule 3 (the package cannot import flat scripts); the bar's DRY; the `attempt_custody` "vocabulary's home" precedent | The catalogue in `workflow-state.py` (breaks rule 1); a catalogue holding its own copies of the sets (two homes); moving the validators too (a cluster move outside this issue) |
| D4 | Observe replies get their own closed requirement check: the five direct kinds only, no duplicates, exact `expects` shape, slot by kind, build by kind, `example` keys equal to `members`; the shared check for control summaries and delivery blocks is unchanged; no comparison with the catalogue, so the kind-to-slot table is the validator's own copy, pinned to the catalogue by the AC1 scenarios | Closed exact-member wire validation; the bar's defense in depth (the validator already keeps its own launch-reason set); issue 469 owns the control shape; `delivery_model` imports nothing from `agent_tools` | Extending the shared requirement check (would change control summaries); validating `expects` against the catalogue inside the delivery model (couples the installed library to the package) |
| D5 | Workflow responses are every subcommand a skill names, except `build-delivery` and `resume-pack`; from-issue's rule names both exemptions; the AC3 test derives the set from skill text | from-issue's "pipe each reply" rule is what the failed run obeyed; agent-helpers rule 6 allows pinning `workflow-state` argv | Only explicit `\| validate-report` pipes (misses `register-worker`, the reported failure); validating builder output at `workflow-response` (sealed values are checked by the next request's own validation) |
| D6 | `register-worker`, `release-worker` and `mark-progress` replies are validated by exact member set, like `check-launch`; the helper output is unchanged | The `check-launch` precedent in the same validator; consumers (`sdd_gate`, owner report) read members by name; smallest reversible change | Adding `kind`/`interface_version` discriminators (changes three wire outputs and their fixtures for no extra safety) |
| D7 | `acquire-direct.md` drops the five literal requirement shapes for an `expects` pointer; the `SKILL.md` exemption clause is reworded; both edits are byte-neutral or shrinking; a README § Lifecycle helpers subsection records the contract | The instruction budget is a required gate (headroom 18–45 bytes, raising needs a human label); the CLAUDE.md home for helper-contract detail; the bar's single home | Keeping the shapes in prose as well as in `expects` (two homes, and over budget) |
| D8 | Tests drive the real CLI: AC1 maps every catalogue kind to a reachable scenario and checks examples against their consumers; AC3 drives one real reply per derived subcommand through the boundary; validator refusals live in `test_delivery_model.py` | The bar: tests that can fail and fixtures shaped like production values; the `validated_response`, `LifecycleHarness`, `DeliveredControlHarness` and `MisbindingTest.transports` precedents | Recorded reply fixtures (go stale silently); checking only the catalogue's own data (passes for a kind the helper never emits) |
| D9 | The direct-owner reply keeps `interface_version` 2; `expects` is an added member, not a new interface | The skills, helper and delivery model ship together in one home-manager generation; nothing persists the observe reply; the request shape is unchanged | Bumping to 3 (the version is shared with the unchanged request, and every caller and fixture would churn for no compatibility gain) |
