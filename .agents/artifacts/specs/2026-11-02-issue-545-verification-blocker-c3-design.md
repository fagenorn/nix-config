# Shared verification blocker: control and direct-owner resolution — issue 545 (228 c3)

Issue: https://github.com/fagenorn/nix-config/issues/545, boundary `c3` of
https://github.com/fagenorn/nix-config/issues/228 (parent Tasks 4 and 5). Its blockers
https://github.com/fagenorn/nix-config/issues/543 (c1, the pure module and the adapter) and
https://github.com/fagenorn/nix-config/issues/544 (c2, ledger schema 11 and parking) are merged.
The parent spec (D1–D25), plan and Tasks 4–5 at `0361d66c` are provenance only; every rule
below was re-decided against the code c1 and c2 landed. Their rows are cited as "issue 543
D<n>" and "issue 544 D<n>", the parent's as "parent D<n>". Designed autonomously
(`from-issue --auto`); every call made without the user is a row in the Decision ledger.

## Triage

input: {"signals": {"contract_change": {"value": "hit", "evidence": "control request/reply interface 3->4, init-run bootstrap 2->3, direct-owner request interface 2->3 all change"}, "concurrency_or_persistence": {"value": "hit", "evidence": "control sweep and direct-owner write ledger verification_blockers resolution under the state lock"}, "open_design_questions": {"value": "doubt", "evidence": "parent spec D1-D25 settles most, but must be re-grounded against what 543/544 actually landed"}, "criteria_shape": {"value": "no", "evidence": "four acceptance criteria, each verified by named unittest files and just recipes"}}, "paths": [20 predicted paths: workflow-state.py, workflow_delivery_wire.py, delivery_model/_wire.py, orchestrate_control.py, attempt_observations.py, the listed tests, acquire-durable.md, acquire-direct.md, orchestrate-issues/SKILL.md, python/README.md, justfile]}
verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions","risk_path"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

c2 parks an attempt on a shared verification blocker, but nothing can release it. A control
sweep reports the attempt `suspended` and dispatches nothing; `direct-owner` replies
`suspended` and writes nothing. The stored record's `resolved` form exists, yet no command
compares an observation with it or writes it, so a parked attempt waits until a merge
reconciles it or a human abandons the issue.

The user needs the lifecycle helper to:

- ask a caller for exactly the observation a parked attempt awaits, in the closed shape the
  adapter prints;
- treat an equal observation as no change: the blocker stays, nothing resumes, nothing is
  written;
- record a resolution, before any reply that resumes, when a successful observation of the
  same sources changes at least one selected value;
- then resume the same attempt in place, through the unchanged capacity, launch, expiry and
  stall rules;
- refuse, with nothing written, an observation that does not answer an open blocker exactly.

## Solution

1. **Pure rules.** `agent_tools.verification_blocker` gains requirement rendering, the
   observation list check and the comparison that resolves records (D2).
2. **Resume predicate.** The observation-gated class resumes exactly when its blocker is
   `resolved` (D5).
3. **Control interface 4.** The request carries `verification`, a list of observations.
   Control resolves them before any issue is analysed. Each summary of an attempt parked on an
   open blocker carries that blocker's requirement (D6).
4. **Bootstrap interface 3.** `init-run` lists the requirement of every open blocker that an
   unfinished issue's latest attempt is parked on (D6).
5. **Direct-owner request interface 3.** The request carries `verification`. A gate asks for
   the observation, answers an equal one with `suspended`, and resumes on a changed one (D7).
6. **Wire, catalogue and callers.** The validator, the `expects` catalogue, `orchestrate-control`
   and the skill request blocks move with the versions, within the current instruction
   headroom. Only docs this change makes false are corrected (D9–D11).

No ledger schema step: schema 11 already defines and validates the `resolved` form (issue
544 D4).

**Demo** (temporary ledger roots, no network):

1. Issues 61 and 62 are parked on blocker X (`flake.lock`). A sweep with no observation
   resumes neither. Both summaries and the bootstrap carry X's requirement.
2. Repeating that sweep with an equal observation of X resumes nothing and leaves
   `.superpowers` byte-identical.
3. A substituted source, a missing fact or another repository exits 2, and nothing changes.
4. At `max_parallel` 1 a changed observation resolves X:
   - 61 resumes in place with launch 2 and a fresh window;
   - 62 stays parked on the resolved record, and the bootstrap lists nothing;
   - the next sweep resumes 62 with no observation.
5. Direct issue 73, parked: `observe verification` → equal: `suspended`, nothing written →
   changed without a worktree fact: `observe recorded_worktree`, nothing written → changed
   with it: `owner` with `launch_kind` `resume`, the resolution committed.

### This delivery's own gates

- **Fixed base.** `e692c9685c3e4b08f55c327c5f2b8c699fc95bc4`. Integration advances never
  move it.
- **Forecast and reviews.** The plan commits a complete review-feasibility forecast. Each
  task gets a fresh independent review, then distinct conformance and correctness reviews
  follow. Parent, c1 and c2 reviews do not count.
- **Size.** `workflow-state.py` (risk path, already larger than one review member) gets
  only constants, the loader flag, the two resolution call sites, the policy gate and the
  `new_run` message. Rules live in the pure module (issue 544 D2).
- **Verification.** Focused tests, `just agent-workflow-tests`, `just build`. Tests use
  temporary ledgers, repositories and `HOME`s. No live ledger or retained attempt is read or
  written, and `just switch` never runs.

## Decisions

### Pure rules (D2)

In `agent_tools.verification_blocker`, which still imports only `canonical` and the
standard library:

- `requirement(record) -> dict` renders `{"kind": "verification", "blocker_id": <id>,
  "sources": [{"name", "paths"}, …]}` from the record's facts in their order, with no
  values. It checks the result with `validate_requirement`. It copies; it never mutates.
- `validate_observations(value) -> list` takes a list. Every element passes
  `validate_observation`, and no `blocker_id` repeats. Refusals name `verification[<i>]`. It
  returns its argument.
- `resolve(blockers, observations) -> (resolved: frozenset[str], equal: frozenset[str])`
  first checks everything (D4). Then, per observation:
  - all values equal the record's: the id joins `equal`, and the record is untouched;
  - otherwise the record becomes `state` `resolved` with `resolution` `{"facts": <a deep
    copy of the observed facts>}`, and the id joins `resolved`.

  A value is the whole `{objects: [{path, mode, object}]}`, so a mode-only change resolves
  (issue 543 D17). "Changed" is derived, never stored (issue 544 D4). `resolve` changes only
  the mapping it is given, and only when no observation is refused.

### Acceptance of an observation (D4)

An observation is accepted only when:

- its `blocker_id` names a record of this run's `verification_blockers` whose `state` is
  `open`; an unknown id and a `resolved` record are refused alike;
- its `repository` equals the record's;
- its facts carry exactly the record's `(name, source)` pairs, in order: no fact missing,
  extra, renamed or with a substituted source.

Any refusal refuses the whole request: exit 2 with one line, `workflow-state: invalid
verification observation: <field>: <reason>`, and nothing is written. An observation carries
no timestamp, and the helper checks no freshness. Freshness is the adapter's contract: every
`verification-observe observe` fetches and reads anew, and a failed probe prints nothing, so
it never reaches a request (issue 543). A replayed stale observation can cause at most one
spurious resume, which the unchanged stall bound limits.

### Resume predicate and policy (D5)

`resume_permitted(blocked_on, *, human_directed, blocker_resolved=False)`:

- observation-gated: returns `blocker_resolved`, whatever `human_directed` says;
- `blocker_resolved` true with any other class: `ValueError`;
- the other classes: unchanged.

The default is the fail-closed answer.

The one-issue policy receives the run's blocker map (after resolution) and the ids observed
equal. A latest attempt suspended on `verification` is resumable exactly when its pointer's
record is `resolved`.

- **Resolved.** It takes the ordinary suspension lane in control and `direct-owner` alike:
  forge reconciliation and the tracker halt first, then the handoff check, the recorded
  worktree and the contract, then `resume_attempt`. That keeps:
  - the issue, attempt, owner, worktree, `handoff_path` and phase (the helper never touches
    the worktree, so its reviewed commits stay);
  - the progress marker, `suspend_phase` and `stalled_resumes`.

  It appends the next launch ordinal and re-bases the window to the lane budget, or to the
  request's budget for an attempt with no lane. It clears `blocked_on` and the pointer. The
  record stays `resolved` and keeps the attempt in `attempts`.
- **Open, control.** The existing non-dispatching `terminal` verdict (issue 544 D7).
- **Open, direct-owner** (`reply_parked`), after the tracker halt and the `forge_pr`
  requirement:
  - id observed equal: `parked`;
  - otherwise: `observe` with `[requirement(record)]`.

Capacity ordering, `slot_withheld`, `refusal_gated`, current-launch fencing, the reaper and
the stall bound are untouched. A verification suspension still counts toward the stall bound.

### Control interface 4 and bootstrap interface 3 (D6)

**Request.** It gains exactly `verification`, a list (`[]` when there is nothing to
report), and moves to interface 4. Version 3 is refused before the lock. The list passes
`validate_observations` before the lock.

**Resolution.** Inside the transaction, after the time check and before the policy analyses
any issue, control runs `resolve` on the run's map.

- A non-empty `resolved` set marks the sweep changed. The resolution then commits in the
  sweep's write whether or not an attempt resumes in it. Capacity, a missing worktree
  observation or a tracker halt may hold the attempt; the next sweep resumes it with no new
  observation.
- The reply is validated at the `workflow-response` boundary before `transact` commits
  (#220 D5), so a rejected reply commits no resolution.

**Response.** It moves to interface 4; its members do not change. A summary whose live
custody record is an attempt parked on an `open` record carries `requirement(record)` among
its `requirements`, in canonical-bytes order, whether the observation was missing or equal.
An attempt waiting on a `resolved` record carries none. A parked attempt arms no deadline, so
a run whose only remaining work is parked ends in `finalize`, as today.

**Bootstrap.** `workflow_bootstrap` gains exactly `verification`, and moves to interface 3.
It lists, sorted and unique by `blocker_id`, the requirement of every `open` record that the
latest attempt of an issue with incomplete delivery is parked on. `requirements` is
unchanged. It is the one read before a control call, so a gathering caller (c4) can answer
every awaited blocker in one call.

**Rendering.** `workflow_delivery_wire` builds the bootstrap and the summary. Both render
with `verification_blocker.requirement`, so no second copy of the shape exists outside the
validator (D9).

### Concurrency (D15)

The map is read and written only inside the run's locked transaction: `control`,
`direct-owner` (under the issue and run locks), `suspend`'s `park`, and `init-run`'s
bootstrap, which is a locked read. A `suspend` that joins or reopens a record is therefore
ordered before or after a resolution, never interleaved. A resolution compares the
observation with the record's stored facts at that moment. An attempt that joins between
the observation and the sweep failed on those same stored values (equal ids mean equal
facts), so the observed change releases it too.

### Direct-owner request interface 3 (D7)

**Request.** It gains `verification`: `[]` until the helper asks, then the observations that
answer what it asked. Requests move to interface 3. Every reply keeps `interface_version` 2
(#473 D9), so the request version gets its own constant. The list passes
`validate_observations` before any lock.

**Resolution.** It runs under the issue and run locks, after the run is selected and before
the policy. The observations resolve against a deep copy of the selected run's map, or an
empty map when the call starts a run (`new_run`, or no run). Refusals are D4's.

**Gate.** It applies to a selected run whose latest attempt is parked on `verification`,
after forge reconciliation, the tracker halt and the `forge_pr` requirement, and before the
recorded-worktree and contract requirements:

| Record (after this call's resolution) | Reply | Written |
|---|---|---|
| `open`, not observed | `observe` with its requirement and `expects` (D10) | nothing |
| `open`, observed equal | `suspended` (the existing envelope) | nothing |
| `resolved` | the ordinary resume lane: `observe` for a missing fact, else `owner` with `launch_kind` `resume` | the copy, in the resume's write only |

- **Commit only with the resume.** Only the write that resumes commits the copy, before the
  `owner` reply prints. Every other reply writes no resolution, so acquire-direct's resent
  observation still names an `open` record on its next call (parent D21).
- **No loop.** An equal observation gets `suspended`, never `observe`, so resending it cannot
  loop.
- **`direct-owner` is always human-directed**, and that never bypasses the gate (D5).
- **`new_run`.** It stays refused for every suspended latest attempt. For a
  verification-parked one the line names the blocker: `new_run is not applicable: suspended
  attempt resumes in place once verification blocker <id> resolves`. Other causes keep their
  line. A parked attempt leaves only through a resolution, a merged-PR reconciliation or the
  stall bound (parent D19).

### Strict request loading (D8)

The `control` and `direct-owner` request files load through the `agent_tools.canonical`
hooks. A repeated key or a non-finite literal exits 2 with `invalid <label> JSON: <reason>`
before any lock. Their observations are authority for a resume, and c2's suspension input
already refuses duplicate keys (issue 544 D8). The `build-delivery` input keeps its loader.

### Wire validator (D9)

In `delivery_model`, which still imports no `agent_tools`:

- **Control response.** Interface 4 only.
  - A summary's requirements admit the closed `verification` requirement: exactly `kind`,
    `blocker_id` (a `sha256:` digest) and `sources` (1–4 closed `{name, paths}`, each with
    1–8 non-empty string paths).
  - At most one per summary, and only on a `suspended` summary with `blocked_on`
    `verification`.
  - It is outside the null-`contract_digest` rule's remainder, so a lifecycle-only summary may
    carry it.
  - No action may name an issue whose summary carries one, as for a missing contract.
- **Bootstrap.** Interface 3 only; `verification` sorted and unique by `blocker_id`, each the
  same closed requirement.
- **Observe reply.** `_OBSERVE_SLOTS` gains `verification` → `verification`. `build` is a
  string for `delivery_contract` and `verification`, null for the rest.
- **Nowhere else.** Owner, remainder and checkpoint requirement lists still refuse the kind.

### Observation catalogue (D10)

`agent_tools.attempt_observations` gains `VERIFICATION_BUILD = "verification-observe observe
--repo-root <ledger_repo_root> --input -"` and a `verification` entry:

- `slot`: `verification`, a list the caller appends one answer to;
- `members`: the five members of one `verification-observation`. Each meaning names its
  closed values: the kind literal, schema version 1, the entry modes and `null` for an
  absent path, taken from `verification_blocker`'s constants;
- `example`: one observation that passes `validate_observation`;
- `build`: `VERIFICATION_BUILD`, which reads the requirement less `expects`.

The module docstring's `build` sentence becomes: the command that produces the slot's value
from an `example`-shaped input (`delivery_contract`) or from the requirement less `expects`
(`verification`).

### Callers and docs within the current headroom (D11)

- **`orchestrate-control`.** `CONTROL_VERSION` 4; `control_request` sends `"verification": []`
  and its docstring says interface 4. Gathering is c4.
- **`acquire-direct.md`.** Only the version digits and `"verification": [],` in the request
  block: about 22 bytes on `from-issue-controller`'s hot profile, which has 116 bytes of
  headroom on both hosts. "Keep every other slot as shown" already covers it.
- **`acquire-durable.md`** (16 bytes of conditional headroom). Only the digit. The route
  already sends unnamed empty members such as `owners` that way. It keeps its
  exactly-one-dispatch rule, so a re-bootstrapped run parked on `verification` fails loudly
  there (parent D16).
- **`orchestrate-issues/SKILL.md`** (17 bytes). Only the digit.
- **No ceiling moves.** `test_instruction_load` and `just agent-instruction-budget` stay green.
- **`python/README.md`.** "interface-3 control response" becomes 4. The pure module's
  paragraph gains `requirement`, `validate_observations` and `resolve`.
- **`home/common/agent-skills/README.md`, issue-544 paragraph.**
  - What c3 makes false is corrected: control 4 and direct-owner request 3 resolve and resume.
  - Its known limitation becomes: no caller gathers observations yet. `orchestrate-control`
    sends `[]`, and acquire-direct fails loudly on a `verification` requirement and on
    `suspended`. That is https://github.com/fagenorn/nix-config/issues/546.
- **`direct-owner --help`.** It says "interface-3 request", lists the `suspended` reply, and
  says that `build` is null or the command that builds the answer.

### Re-grounding against c1 and c2 (D14)

Parent Tasks 4–5 do not match what landed:

- **Resolution shape.** It is `{"facts"}` alone, with no `changed` list, so tests assert the
  stored facts.
- **Value objects.** They carry `mode`.
- **The c2 harness.** It has `VerificationHarness.park`, `failure(failure_class, path)`,
  `record`, `LOCK`, `T`, `DIRECT_NOW` and a one-issue `recorded`. It has no `NEXT`, no
  `observed`, no value parameter on `failure` and no multi-issue `recorded`; c3 adds them to
  that module.
- **What exists and what does not.** `parked`, `reply_parked` and `suspended_reply` exist;
  `verification_observed` and the pure `requirement`/`resolve` do not.
- **c2's parked direct test.** It expected `suspended` with no observation. It now expects
  `observe verification` first and sends an equal observation for `suspended`.

## Test seams

Assertions read exit codes, replies, persisted ledgers and tree snapshots, never helper call
counts (D12).

- **Pure rules**, by import, in `tests/test_verification_blocker.py`:
  - `requirement`: the exact shape and order, and no mutation of the record;
  - `validate_observations`: a non-list, an invalid element, a repeated id;
  - `resolve`:
    - accepted: equal, one changed, mode-only changed, and one equal beside one changed;
    - refused: unknown id, resolved record, other repository, missing, extra, renamed,
      reordered or substituted fact;
    - all-or-nothing: a refusal of the second observation leaves the first record untouched;
    - neither argument is mutated on refusal.
- **Vocabulary**, in `tests/test_attempt_custody.py`: the `resume_permitted` table gains
  `blocker_resolved`, plus `ValueError` for a resolved flag on another class.
- **Control CLI**, in the new `test_verification_control.py` over `VerificationHarness`:
  - **unchanged replay:** after a sweep with no observation, a repeat with an equal one
    leaves both attempts parked, the requirement in both summaries and the tree
    byte-identical;
  - **unrelated and selected changes:** blockers X and Y; X equal and Y changed in one sweep
    resumes only Y's attempt, and X's attempt keeps its requirement;
  - **human direction:** a directed sweep does not bypass the gate;
  - **failed probe:** with no observation, nothing about the record is written;
  - **missing selector or changed source:** a missing, extra or substituted fact, another
    repository, a repeated, unknown or resolved id, a malformed or secret-shaped observation,
    interface 3 and a duplicate JSON key all exit 2 with the tree unchanged;
  - **capacity and retained work:**
    - at `max_parallel` 1, request order picks the resume, and the second resumes on the
      next sweep with no observation;
    - each keeps every D5 field and gets a fresh deadline and the next launch;
    - `check-launch` reports the old launch `superseded_launch` and the new one current;
  - **stall bound:** three park → resolve → resume cycles at one phase; the fourth park stops
    the attempt `stalled` and records no blocker;
  - **persistence before output:** a copied helper whose policy rejects every reply exits 2
    with empty stdout and an unchanged tree, so no resolution commits (the precedent of
    `test_delivered_control`);
  - **bootstrap:** version 3, the listing, and emptying after the resolution.
- **Direct CLI**, in the new `test_verification_direct.py`:
  - the D7 sequence, with an unchanged tree until the `owner` reply and the committed
    resolution after it;
  - refusals of another repository, a repeated or unknown id, interface 2 and a duplicate
    key;
  - `new_run` naming the blocker id.
- **Wire**, by behaviour (issue 544 D16):
  - control 4 and bootstrap 3 are accepted, and 3 and 2 refused;
  - `requirement(record)` passes;
  - refused: a requirement with a member added or removed, one on a non-suspended summary or
    twice, a dispatch naming a parked issue, the kind in an owner action's requirements.
  - The observe slot is pinned by `ObservationCatalogueTest` and `DirectObserveExpectsTest`
    gaining a `verification` row; its example is a request the helper accepts.
- **Skill contracts** (agent-helpers rule 6): acquire-direct's request key set gains
  `verification` at version 3.
- **`orchestrate-control`**: the expected request is interface 4 with `"verification": []`,
  and replies are 4.
- **Fixtures and older helpers** (D13): every version-pinning fixture moves, and each
  extracted base helper keeps receiving and validating its own versions.
- **Integration**: the two new modules are listed in `just agent-workflow-tests` after
  `test_verification_suspension.py`, then `just build`.

## Out of scope

- c4 (https://github.com/fagenorn/nix-config/issues/546):
  - `orchestrate-control` gathering and `verification_refusals`;
  - the from-issue and sdd procedures, acquire-direct's handling of a `verification`
    requirement or a `suspended` reply, and the suspension procedure's new cause;
  - instruction ceilings and the full protocol docs.
- Any ledger schema step, and any change to the adapter, the failure and observation
  shapes, the identity or the secret-shape rule.
- Observation timestamps or freshness checks inside `workflow-state`.
- An abandonment route or a human override for a parked attempt.
- Verification blockers on delivery remainders; live ledgers, retained attempts, host
  activation (`just switch`).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Scope: parent Tasks 4–5 re-grounded. In: the pure rules, the predicate, control 4, bootstrap 3, direct-owner request 3, wire, catalogue, the version text of the three callers, and the docs and help this change falsifies. No gathering, procedure or ceiling change. | Issue 545 "What to build" and AC; parent D20 (each interface task moves its own callers); issue 544 D11. | Parent Task 6–7 surface (gathering, procedures), which is c4 and needs ceiling raises the user alone labels. |
| D2 | `requirement`, `validate_observations` and `resolve` live in `verification_blocker`. `resolve` checks every observation before changing anything, mutates only the given map, and returns `(resolved, equal)` id sets. | Issue 543 D1 (comparison and rendering are c3's); issue 544 D2 (rules in the pure module, the `park` precedent); agent-helpers rule 1. | Rules inside `workflow-state.py`, a risk path over the member limit, used by two callers. A per-observation writer that can half-apply a request. |
| D3 | Control 4 (request and reply), bootstrap 3 and the direct-owner request 3 move together. Direct replies stay 2. The ledger stays at schema 11. A caller at the old version is refused before any write. | #150 D8; #473 D9; issue 544 D4 (schema 11 already validates `resolved`, so a c2 helper reads a c3 ledger and keeps the attempt parked); parent D8. | A schema 12 step, which adds nothing a c2 helper cannot already read. Bumping every direct reply, churning the owner object for no compatibility gain. |
| D4 | An observation must name an `open` record of the run, carry its repository, and its exact `(name, source)` pairs in order. Anything else refuses the whole request with exit 2 and no write. Unknown and `resolved` ids are refused alike. No timestamp: freshness is the adapter's contract. | Issue AC2 ("from the same sources"); AC5 (missing selectors, changed sources); parent D7; The Bar "Fail loud". | Ignoring a mismatched observation, which hides caller bugs. An `observed_at` stamp, a caller assertion the I/O-free helper cannot check. |
| D5 | `resume_permitted` gains `blocker_resolved` (default false, fail-closed; true with another class raises). The policy gets the run's map and the ids observed equal. A resolved verification attempt takes the ordinary suspension lane unchanged, in both callers. | Issue 544 D6 ("c3 extends the observation-gated branch"); AC3 (capacity, current launch, expiry and stall intact); issue 544 D14 keyword precedent. | A separate resume path for verification, which would duplicate capacity, fencing and window rules. A predicate default of true. |
| D6 | Control resolves before any issue is analysed. A resolution commits in the sweep's write whether or not a slot resumes it, and never when the reply boundary rejects. Summaries carry the requirement only for an open record. The bootstrap lists open awaited records, sorted by id, rendered by the pure function. | AC2; #220 D5 (validate before commit); parent D10, D21 (control commits regardless); `max_parallel` would otherwise strand the second attempt. | Committing only with a resume, which forces a new observation for every capacity-withheld attempt. A second control round for verification, skipped whenever the first dispatches. |
| D7 | Direct-owner gate after forge reconciliation, the tracker halt and `forge_pr`, before the worktree and contract: open and unobserved → `observe`; equal → `suspended`, no write; resolved → the resume lane. The resolved copy commits only in the resume's write. The `new_run` refusal names the blocker id. | AC2; parent D9, D19, D21 (acquire-direct resends retained facts; an observe loop on equal values); issue 544 D7 (the `parked` branch point). | Committing at once, which makes the resent observation name a resolved record and refuses the next call. A `terminal` reply, which says falsely that the run ended. |
| D8 | `control` and `direct-owner` requests load strictly (repeated keys and non-finite literals refused before any lock); `build-delivery` input does not change. | Agent-helpers rule 4; issue 544 D8 (the suspension input is strict); The Bar "Defense in depth"; parent D23. | Strictness on the `verification` member alone, which cannot see a key `json.loads` already collapsed. |
| D9 | The validator admits the closed `verification` requirement only in control summaries (at most one, only when `suspended` on `verification`, outside the null-digest remainder, no action for that issue), in the bootstrap and in observe replies, where `build` is required. No other list admits it. | `delivery_model` imports no `agent_tools`; parent D11; the existing `worktree_fact` and missing-contract rules. | Admitting the kind in the shared requirement check, which would let owner, remainder and checkpoint replies carry it. |
| D10 | The catalogue's `verification` entry describes one observation (members, closed values from the pure module's constants, a valid example). Its `build` is the adapter's `observe` over the requirement less `expects`. The docstring's `build` sentence is generalised. | Parent D24; #473 D4 catalogue; issue 543 (the adapter takes a bare requirement); The Bar DRY. | Teaching the adapter to accept `expects`, which reopens c1's closed shape. Describing the adapter input in `members`. |
| D11 | Callers move within today's headroom. acquire-direct gains the member and the digits (about 22 of 116 bytes). acquire-durable (16 bytes) and orchestrate-issues (17 bytes) change only the digit. No ceiling moves. Both READMEs and `--help` are corrected where they turn false. | Measured `instruction_load report` at the base; CLAUDE.md (only the user labels a raise); The Bar (re-point living docs; known limitations in docs); issue 544 D11. | Naming `verification: []` in acquire-durable's prose (about 20 bytes, over its 16). Leaving the README's "nothing resumes yet" limitation, which c3 makes false. |
| D12 | Test seams: pure tables; two new CLI modules, `test_verification_control` and `test_verification_direct`, over the extended `VerificationHarness`; behavioural wire pins; the rule-6 key-set pin. AC5's "unrelated change" is an equal blocker beside a changed one at the ledger level, while path-level unrelated commits stay in c1's adapter tests. | Agent-helpers rules 5–6; The Bar "Tests that can fail"; parent D25 file split; issue 544 D16 behavioural pin. | One module for both interfaces, which mixes two tasks' records. Constant-for-constant pins that never run the validator. |
| D13 | Fixtures move with the versions in every module that builds or pins a control 3 request or reply, a bootstrap 2 or a direct-owner 2 request. The known set: `test_workflow_state`, `test_delivery_workflow`, `_delivery_model_fixtures`, `test_artifact_budget`, `test_workflow_skill_contracts`, `orchestrate_world` and `test_orchestrate_control`. Calls to an extracted older helper still send that helper's own versions, without `verification`, and a reply they validate goes through that helper's own extracted validator. These are `test_verification_suspension`'s base generation and `test_control_cutover`'s. Each keeps its fixed base. | Both base helpers load the request before the ledger and pin control 3 and direct 2, and `test_control_cutover` checks base replies with the head validator, so head shapes would fail on the version, not on the behaviour under test; issue 544 D13 (fixture blast radius). | Moving those tests' base commits, which changes what they prove. Teaching head builders a version switch every caller must thread. |
| D14 | Re-grounding: resolutions store `{"facts"}` only; objects carry `mode`; c3 adds `NEXT`, `observed`, a value parameter for `failure` and a multi-issue `recorded` to the c2 harness; c2's parked direct test now expects `observe verification` before `suspended`. | Issue 544 D4; issue 543 D17; the landed `test_verification_suspension` module. | Following parent Task 4–5 test code verbatim, which asserts a `changed` member and helper names that do not exist. |
| D15 | Grill: the blocker map is read and written only inside the run's locked transaction (control, direct-owner, `park`, the bootstrap's locked read). A concurrent `suspend` that joins or reopens a record is ordered by the lock, and a resolution always compares against the stored facts at that moment. | Triage `concurrency_or_persistence`; `transact` and the direct-owner run locks; issue 544 D8 (suspensions serialize on the ledger lock). | Reading the map lock-free for the bootstrap or the gate, which could list or resolve a record a concurrent `park` has just reopened. |
| D16 | Plan, test seam: `test_control_decisions`' decision twin decodes each validated reply and, for a control reply, checks and sets aside `interface_version` (3 for the base generation, 4 for head) before comparing; everything else stays equal. `Cutover` sends the base helper its own control interface without `verification` and validates base replies with the base's extracted `artifact_budget.py` and policy, which also serves `test_delivery_sealing`'s base fixtures. Extends D13's known set. | The twin's byte comparison would fail on the version alone; D13 (each generation receives and validates its own versions); both modules inherit `Cutover`. | Moving `BASE_COMMIT` (D13 rejects it). A textual version substitution in the compared bytes. |
| D17 | Plan: `direct-owner` resolves right after the `new_run` and `owner_unavailable` applicability checks, before the terminal replay and before a new run's mint, against an empty map for `new_run` or no run. A refusal writes nothing but the issue lock file the call already holds, and a terminal replay carrying an unanswerable observation is refused too. | D4 (nothing written); D7 (under the issue and run locks, before the policy); the mint writes the index before the policy runs. | Resolving at the policy call, after the mint, which leaves an index entry behind a refused call. |
| D18 | Plan: the corpus ceiling (403959 bytes) has 7 bytes of headroom at the base, below acquire-direct's 22-byte `"verification": [],` line, which every acquisition needs because the request is closed. orchestrate-issues `SKILL.md` therefore drops its descriptive `interface_version 3 ` from "the same … control response" (20 bytes) instead of moving the digit; acquire-durable still moves only its digit. Refines D11, which measured the profile ceilings only. | `instruction_load check` at the base (corpus 403952 of 403959); CLAUDE.md (only the user labels a raise); `orchestrate-control`, not the skill, composes and pins the control request. | Raising the ceiling, which needs the user's label. An optional `verification` member, which reopens D7's closed request. |
| D19 | Standards review: refines D17. A refused observation writes no resolution, attempt, launch, index entry or run. The only bytes it can leave are those `direct-owner` commits before resolving whatever it later returns: the issue lock file and the bind of a legacy (schema 10 or older) ledger, which is idempotent and holds no blocker, so any observation against it is refused. The bind is not moved behind the resolution; a test pins that a refused call leaves the bound ledger and a repeated call changes nothing. | Live `command_direct_owner` commits a legacy ledger's bind (`read.changed`) before the planned resolution point; D4 (no resolution or resume on a refusal); issue 544 D9 (the strict 10 -> 11 step). | Moving the bind after the resolution, which restructures the preflight every direct call shares. Keeping D17's "nothing but the issue lock", which the bind makes false. |
