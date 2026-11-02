# Shared verification blocker: ledger schema 11 suspension — issue 544 (228 c2)

Issue: https://github.com/fagenorn/nix-config/issues/544, boundary `c2` of
https://github.com/fagenorn/nix-config/issues/228 (parent Task 3). Its blocker
https://github.com/fagenorn/nix-config/issues/543 (c1, the pure module and the adapter) is
merged. The parent spec (D1–D25), plan and Task 3 at `0361d66c` are provenance only; every
rule below was re-decided for this child. c1's rows are cited as "issue 543 D<n>", the
parent's as "parent D<n>". Designed autonomously (`from-issue --auto`); every call made
without the user is a row in the Decision ledger.

## Triage

Input: `{"signals": {"contract_change": {"value": "hit", "evidence": "ledger schema 11, a new verification blocked_on cause, a suspend --verification-input flag and the suspended reply's cause set in delivery_model/_wire.py"}, "concurrency_or_persistence": {"value": "hit", "evidence": "adds persisted run-scoped verification_blockers and attempt backreferences under the ledger lock, with strict migration from schema 10 and older"}, "open_design_questions": {"value": "doubt", "evidence": "parent spec D1-D25 and Task 3 are provenance only; c1 deferred park, validate_blockers and upgrade_ten to this child (issue-543 D1)"}, "criteria_shape": {"value": "doubt", "evidence": "four criteria; 'nothing touches live retained attempts or activates the host' has no single deterministic check"}}, "paths": ["python/agent_tools/verification_blocker.py", "python/agent_tools/attempt_custody.py", "python/agent_tools/attempt_identity.py", "python/agent_tools/attempt_store.py", "home/common/agent-skills/scripts/workflow-state.py", "home/common/agent-skills/scripts/delivery_model/_wire.py", "tests/test_attempt_custody.py", "tests/test_attempt_identity.py", "tests/test_verification_blocker.py", "home/common/agent-skills/tests/test_workflow_state.py", "home/common/agent-skills/tests/test_attempt_migration.py", "home/common/agent-skills/tests/test_control_cutover.py", "home/common/agent-skills/tests/test_verification_suspension.py", "justfile"]}`
Verdict: `{"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Problem

c1 gave a verification failure one closed shape and one content identity, but nothing can
park an attempt on it. Today an owner whose declared verification command fails for a reason
outside the change can only suspend on `transport` (a blind resume that spends the stall
bound) or `external` (any human re-entry resumes it). The ledger stores a per-attempt
`blocked_on` only, so it cannot say that two attempts wait on the same failure, and it has no
place for the failure's facts that a later resolution (c3) must compare against.

The user needs an owner to suspend on a qualifying failure so that:

- equal normalized failures in one run share one stored record that names every attempt
  parked on it;
- only the failure's selected typed facts are persisted, and a malformed, unclassified or
  secret-shaped input is refused before anything is written;
- existing ledgers move to the new schema strictly, and a helper that predates it refuses
  the new ledger without touching it;
- nothing resumes a parked attempt until c3 adds resolution.

## Solution

1. **A cause and its class.** `verification` joins the attempt suspension vocabulary as a
   third, observation-gated class beside the auto-resumable and human-gated ones. No sweep
   and no re-entry resumes it in this child (D6).
2. **Ledger schema 11.** The run gains `verification_blockers`, one closed record per
   blocker id, and each attempt gains `verification_blocker`, the id of the blocker it is
   currently parked on (D3–D5).
3. **Suspension input.** `workflow-state suspend --blocked-on verification
   --verification-input <-|absolute-path>` takes the `verification-failure` that
   `verification-observe failure` prints, validates it before the ledger lock, and parks the
   attempt on the record in the same write (D8).
4. **Migration.** Schema 10 and older migrate strictly to 11. The schema-10 helper already
   refuses a schema-11 ledger as `unknown_schema` without writing (D9).
5. **Parked behaviour until c3.** Control gives a parked attempt its existing non-dispatching
   verdict. The direct owner gets the existing `suspended` reply and nothing is written (D7).
6. **Wire and docs.** The `suspended` reply's cause set admits `verification` (D10). The
   lifecycle README sentences that this change makes false are corrected (D11).

**Demo** (temporary ledger roots, no network):

1. Issues 61 and 62 are spawned. Both suspend with the same failure. The ledger then holds
   one open record whose `attempts` are `61:1` and `62:1`, and each attempt points at it.
   Custody parks both as `suspended:verification`.
2. A directed control sweep resumes neither. A direct run parked the same way gets the
   `suspended` reply, and nothing is written.
3. A secret-shaped, unclassified or duplicate-key input exits 2, and `.superpowers` is
   byte-identical.
4. A schema-10 copy migrates to 11. The delivery-base helper refuses the result with
   `unknown_schema` and leaves its bytes unchanged.

### This delivery's own gates

- **Fixed base.** `87d6065fc1749c0b7b6c427beb9b1d3051bc198d`. Integration advances never
  move it. It is also the "older installed helper" the refusal test extracts (D9).
- **Forecast and reviews.** The plan commits a complete review-feasibility forecast. Each
  task gets a fresh independent review, then distinct conformance and correctness reviews
  follow. Parent and c1 reviews do not count.
- **Size.** `workflow-state.py` (risk path, already larger than one review member) gets only
  the schema constants, the validation hooks and the edits D5–D8 name. Rules live in the
  pure modules (D2).
- **Verification.** Focused tests, `just agent-workflow-tests`, `just build`. Tests use
  temporary ledgers, repositories and `HOME`s. No live ledger or retained attempt is read or
  written, and `just switch` never runs.

## Decisions

### Vocabulary and the resume predicate (D6)

In `agent_tools.attempt_custody`:

- `BLOCKED_ON_VALUES` gains `verification`. `OWNER_BLOCKED_ON_VALUES` and
  `SUSPENSION_CAUSES` follow by derivation, so `suspend --blocked-on` offers it and the
  custody transaction parks with `suspended:verification`.
- New `OBSERVATION_GATED_BLOCKED_ON = {"verification"}`.
- `HUMAN_GATED_BLOCKED_ON` becomes `BLOCKED_ON_VALUES − AUTO_RESUMABLE_BLOCKED_ON −
  OBSERVATION_GATED_BLOCKED_ON`, so its members, and the remainder policy that reads it, are
  unchanged. The three classes partition the attempt causes.
- New `resume_permitted(blocked_on, *, human_directed) -> bool`:
  - an auto-resumable cause gives `True`;
  - a human-gated cause gives `human_directed`;
  - an observation-gated cause gives `False`;
  - any other value raises `ValueError`.

  c3 extends the observation-gated branch with its resolution input.

The attempt policy's resumable-suspension test calls `resume_permitted` in place of
`human_directed or blocked_on in AUTO_RESUMABLE_BLOCKED_ON`. The stall bound, the reaper,
capacity and current-launch rules are unchanged. A verification suspension counts toward
the stall bound like any other.

### Ledger schema 11 (D3, D4, D5)

```json
"verification_blockers": {
  "sha256:<64 hex>": {
    "id": "sha256:<64 hex>",
    "repository": {"project_id": "…", "integration_branch": "main"},
    "command": {"id": "nix-build", "argv": ["just", "build"], "cwd": ".", "env": []},
    "failure_class": "dependency",
    "facts": [{"name": "flake-lock", "source": {"paths": ["flake.lock"]},
               "value": {"objects": [{"path": "flake.lock", "mode": "100644",
                                      "object": "<hex>"}]}}],
    "attempts": [{"issue": 61, "attempt": 1}, {"issue": 62, "attempt": 1}],
    "state": "open", "resolution": null}}
```

Every attempt gains `"verification_blocker": "sha256:<64 hex>" | null`. The suspension
defaults that a new attempt is created with gain it as `null`. Delivery remainders do not
change. An attempt is *parked on* a blocker while it is suspended on `verification` with
its pointer naming that record. The suspension, its custody parking and `park` below are
the same event at three levels.

**Record rules** (`validate_blockers(blockers, pointers) -> None`, where `pointers` maps
every attempt of the run, `(issue, attempt)`, to its pointer; run by `validate_state` at 11
on every read and write):

- R1. The map is an object. Each key equals its record's `id`. The `id` equals
  `blocker_id` of the failure rebuilt from the record's `repository`, `command`,
  `failure_class` and `facts`, so the content passes c1's failure validation, including the
  secret-shape rule and the 2,048-byte bound.
- R2. A record has exactly the eight members shown.
- R3. `attempts` is a non-empty list of closed `{issue, attempt}` objects with positive
  `int`s (no `bool`). It is strictly increasing by `(issue, attempt)`, and each entry names
  an attempt of this run. It keeps every attempt that ever parked on the record, so an
  attempt that left parking stays listed.
- R4. `state` is `open` with `resolution` `null`, or `resolved` with `resolution`
  `{"facts": [...]}`:
  - those facts are valid valued facts with exactly the record's names and sources, in
    order;
  - at least one fact's `value` differs from the record's.
- R5. Cross-reference: every non-null attempt `verification_blocker` names a record whose
  `attempts` contain that attempt.

**Attempt rule** (`validate_attempt` at 11): `verification_blocker` is non-null exactly when
the attempt is `suspended` with `blocked_on` `verification`, and is then `sha256:` plus 64
lowercase hex characters. Validation at schema 7, for a legacy document not yet migrated,
uses the attempt and state member sets without the two new members.

**Writers.**

- `park(blockers, failure, issue, attempt) -> str`, in `agent_tools.verification_blocker`,
  validates the failure and computes its id. It then:
  - creates the record `open` with this one reference when the id is new;
  - otherwise adds the reference once in sorted order, and reopens a `resolved` record
    (`state` `open`, `resolution` `null`).

  It never rewrites a record's content, which equal ids already make equal. It returns the
  id, and it changes only the mapping it is given.
- Records are never deleted.
- The resolved form is read and validated here, but only c3 writes it (D4).
- The writers that end a suspension (`resume_attempt`, `stop_attempt` and
  `reconcile_merged_attempt`) clear `verification_blocker` together with `blocked_on`.
  `validate_attempt` refuses any write that leaves the pair inconsistent.

### Suspension (D8)

`workflow-state suspend … --blocked-on verification --verification-input <-|absolute-path>`

1. **Before the lock.**
   - The flag is required exactly with `--blocked-on verification`. Otherwise the command
     refuses with `--verification-input is required with --blocked-on verification` or
     `--verification-input is only valid with --blocked-on verification`.
   - The input bytes are read with the helper's existing reader: `-` is stdin, anything
     else must be an absolute path.
   - The input is loaded with c1's `strict_load` and checked with `validate_failure`, and
     its id is computed. A `BlockerRefused` exits 2 as `workflow-state: invalid verification
     input: <field>: <reason>`.
   - Nothing is locked, created or written before this step passes, so every refusal
     leaves `.superpowers` byte-identical.
2. **Inside the transaction.**
   - The existing checks run unchanged: the identity, the active state, the time order and
     the fence.
   - `suspend_attempt` decides first. At the stall bound it stops the attempt
     `stopped(stalled)` and the reply is `terminal`, as today. No record is created or
     touched.
   - Otherwise `park` runs and the attempt's `verification_blocker` is set, in the same
     write. Suspensions serialize on the ledger lock, so concurrent owners with equal
     failures join one record.
   - `transact` validates schema 11 and commits before anything is printed.
3. **Reply.** The existing interface-2 `suspended` envelope with `blocked_on`
   `verification`. It is built by one shared `suspended_reply`, which the direct owner uses
   too (D7). The closed envelope does not name the blocker; the ledger does.

Only the failure's identity members are persisted: no `kind`, no version and no input
bytes. The record therefore carries the selected typed facts and nothing else.
`workflow-state` resolves nothing, so it checks the failure's shape only. The adapter's
guard remains the authority on what counts as a failure (issue 543 D7).

### Migration and older helpers (D9)

- `attempt_identity`'s `schema_refusal` accepts schemas 1–11.
- `attempt_store`'s current version becomes 11.
- `upgrade_ten(document) -> dict` (pure, in `verification_blocker`):
  - it takes a schema-10 document;
  - it refuses `BlockerRefused` when `verification_blockers` or any attempt's
    `verification_blocker` is already present;
  - otherwise it returns a copy with `verification_blockers: {}`, every attempt's pointer
    `null` and `schema_version` 11;
  - it never mutates its input.
- The store maps its refusal to `LedgerRefused("invalid_state")`.
- **Locked read and unlocked check.**
  - A schema-11 ledger is bound and validated.
  - A schema-10 ledger is bound, passed through the step and validated at 11 with
    `changed` set. It has no bind plans.
  - Schemas 8 and 9 keep their bind plans and then take the same step.
  - Schemas 7 and older take their existing chain, then the step.
  - The migration is committed by the ledger's next locked write, or by `migrate --apply`.
- **`migrate`.** It reports 8, 9 and 10 as `migrate`, and 11 as `current` (or `migrated`
  after an apply).
- **No reverse.** There is no reverse step and no writer marker.
- **Older helpers.** A helper older than schema 11 refuses the ledger through its existing
  `unknown_schema` check, and every one of its writes stops before mutating (#337 D10).

### Parked attempts until c3 (D7)

- **Control** (any sweep, directed or not): a latest attempt suspended on `verification` is
  not resumable, so the policy returns its existing non-dispatching `terminal` verdict, as it
  does for a human-gated cause in an undirected sweep. The sweep dispatches nothing for it
  and arms no deadline for it. Its summary reports `suspended` with `blocked_on`
  `verification`. A merged-PR reconciliation still closes it, and that clears the pointer
  (R3 keeps the reference).
- **Direct owner** (always `human_directed`): such an attempt follows a resumable
  suspension's lane up to its forge requirement:
  1. The merged-forge reconciliation runs first (unchanged).
  2. A supplied tracker observation that halts gives the tracker `terminal` reply.
  3. A missing forge observation gives `observe` `forge_pr`.
  4. Otherwise the policy returns the new verdict `parked`. Direct-owner answers it with
     `suspended_reply` and writes nothing, in place of the worktree requirement and the
     resume.

  `new_run` stays refused for a suspended latest attempt, unchanged. This is the branch
  point that c3's observation gate replaces.

### Wire (D10)

`delivery_model`'s `suspended` reply validator admits `verification` in its literal cause
set. `delivery_model` still imports no `agent_tools`. No interface version moves: the
control response, the direct-owner replies and the bootstrap keep their shapes.

## Test seams

Assertions read exit codes, replies, persisted ledgers, custody transactions and tree
snapshots, never helper call counts (D12).

- **Pure rules**, by import, in `tests/test_verification_blocker.py`:
  - `park` creates, joins, keeps history, adds a reference once, and reopens a resolved
    record;
  - a `validate_blockers` table with one row per rule R1–R5, including a resolved record
    whose source is substituted or whose values are all unchanged;
  - `upgrade_ten`: an exact output, a refusal when a member is present, and no mutation of
    its input.
- **Vocabulary**, in `tests/test_attempt_custody.py`:
  - the pinned sets, including the three-class partition;
  - a full `resume_permitted` table over cause and `human_directed`;
  - `ValueError` for `owner_unavailable` and for an unknown value;
  - `suspension_reason("verification")`.

  `tests/test_attempt_identity.py`: schemas 1–11 are known and 12 is refused.
- **CLI**, in the new `test_verification_suspension.py`, reusing `LifecycleHarness` as
  `test_attempt_custody`, `test_attempt_migration` and `test_host_admission` already do:
  - two attempts share one record, with consistent pointers and custody parked
    `suspended:verification`;
  - refused inputs exit 2 with an unchanged tree: duplicate key, non-JSON, unclassified,
    secret-shaped, a missing flag and a stray flag;
  - the stall bound gives `terminal` and touches no record;
  - a directed control sweep leaves the attempt parked;
  - direct-owner gives `observe forge_pr`, then `suspended` with nothing written, and a
    merged forge reconciles the attempt and clears the pointer;
  - a hand-built resolved record is reopened by `suspend`;
  - every `OWNER_BLOCKED_ON_VALUES` member validates as a `suspended` reply, and
    `unknown` and `host_capacity` are refused (the pin of the wire's literal set);
  - strict 10 → 11 through `migrate` and `--apply`, and an `invalid_state` refusal with an
    unchanged tree for a schema-10 ledger that already holds a new member;
  - the head helper refuses schema 12;
  - the base helper, extracted with `git archive` from the fixed base (the precedent of
    `test_control_cutover` and `test_attempt_migration`), refuses the schema-11 ledger as
    `unknown_schema` with an unchanged tree through `check-launch`, `suspend`, `control`,
    `init-run`, `direct-owner` and `migrate`. `migrate` reports a `refused` row with exit
    0, with and without `--apply`.
- **Fixtures** (D13):
  - schema numbers move from 10 to 11 and the unknown-schema probes from 11 to 12 in
    `test_workflow_state`, `test_attempt_migration`, `test_control_cutover`, the
    agent-skills `test_attempt_custody`, `test_delivery_workflow`, `test_host_admission`
    and `test_delivery_sealing`;
  - literal schema-10 states, attempts and bound-ledger expectations (such as
    `test_delivery_workflow`'s `assert_bound`) gain the two members;
  - every builder that relabels a head state as an older schema (`_as_legacy`, which
    `test_control_cutover` inherits, `test_delivery_workflow`'s `legacy`, and direct
    relabels such as a document set to schema 8) drops both new members below 11.
- **Integration**: the new module is listed in `just agent-workflow-tests` after
  `test_attempt_custody.py`. `just build`.

## Out of scope

- Recording a resolution, comparing observations, rendering requirements, resuming a parked
  attempt, the `verification` request members, control interface 4, direct-owner request 3
  and bootstrap 3. These are c3 (https://github.com/fagenorn/nix-config/issues/545).
- `orchestrate-control` gathering, the from-issue and sdd procedures, `acquire-direct`'s
  handling of a `suspended` reply, the full protocol docs and instruction ceilings. These
  are c4 (https://github.com/fagenorn/nix-config/issues/546). Until c4, `acquire-direct`
  fails loudly on the `suspended` kind, as it does on any unknown kind.
- Verification blockers on delivery remainders, and any change to the adapter or to the
  secret-shape rule.
- Cross-record invariants beyond R5, such as one repository per run, and any blocker store
  shared across runs: equal failures in two runs get two records with one id.
- Live ledgers, retained attempts, host activation (`just switch`) and any reverse
  migration.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Scope: the `verification` cause and its class, schema 11 (records and pointers), `suspend --verification-input`, strict 10 → 11 migration, the wire cause set, safe parked behaviour in control and direct-owner, and the README sentences the change falsifies. No resolution writer, resume, interface bump or procedure. | Issue: "Resolution and resume are out of scope here"; issue 543 D1 (record and state rules and migration are c2's); c3 and c4 bodies. | Parent Task 3's whole surface (`resume_permitted(blocker_resolved=…)`, observation-aware policy arguments): there is no caller until c3. |
| D2 | `park`, `validate_blockers` and `upgrade_ten` live in `agent_tools.verification_blocker`, which still imports only `canonical` and the standard library. `attempt_store` composes the step, and `workflow-state` calls the rules. | Issue 543 D1 and D15; precedent of pure domain modules owning their migration step (`plan_custody_migration`, `plan_remainder_migration`); agent-helpers rule 1. | Rules inside `workflow-state.py`: a risk path already over the member limit, and only one side of the boundary. Rules in `attempt_store`, the effectful module. |
| D3 | One run-scoped map keyed by blocker id. Each record repeats its `id` (like `issues` values repeat `issue`) and keeps `attempts` as history. Records are never deleted. | AC1 "one closed shared blocker record with consistent attempt backreferences"; the `issues` map precedent; parent D5. | Backreferences to currently parked attempts only, which makes every exit writer edit the run-level map and forgets who parked. Deleting records, which loses what a resolution released. |
| D4 | Schema 11 defines and validates the complete record now, including the `resolved` form, which only c3 writes. `resolution` is `{"facts": [...]}` with at least one changed value; "changed" is derived, not stored. `park` reopens a resolved record. | The schema number is the compatibility signal (#337 D10, README § Run identity); c3's issue plans no ledger schema step; The Bar DRY. | Admitting only `open`: a c3 widening would make a c2 helper refuse a valid ledger as `invalid_state` rather than `unknown_schema`. Omitting `state`/`resolution`: it forces schema 12 in c3. Storing `changed`: a derived copy. |
| D5 | The attempt pointer `verification_blocker` is one of the suspension defaults. It is non-null exactly while the attempt is suspended on `verification`, and it is cleared wherever `blocked_on` is. Schema-7 validation uses the member sets without the new members. | AC1 consistency in both directions; c3 must know which blocker a parked attempt awaits; `validate_attempt` fails loud on a missed clear. | Deriving the blocker from the records: ambiguous once history keeps an attempt in several records. |
| D6 | `verification` is a third, observation-gated class. `HUMAN_GATED` excludes it. `resume_permitted(blocked_on, *, human_directed)` dispatches over the three classes and raises otherwise; the observation-gated branch is `False` here. | Issue 228: a human re-entry never authorizes a resume; The Bar "Fail loud"; `attempt_custody` is the home of the cause classes. | Letting it fall into `HUMAN_GATED` by subtraction, where every directed sweep and direct owner resumes blindly. `AUTO_RESUMABLE`, which spends the stall bound on an unchanged failure. |
| D7 | Control keeps its existing non-dispatching `terminal` verdict for a parked attempt. The direct owner follows the resumable lane through the tracker halt and the forge requirement, then a new `parked` verdict replies with the shared interface-2 `suspended` envelope and writes nothing. The merged-PR reconciliation and the tracker halt stay as exits, and `new_run` stays refused. | Control's rule that any non-dispatch operation is a verdict; direct-owner's `terminal` branch assumes a stall result and would fail on a suspended attempt; parent D9 places c3's gate there. | Refusing the direct owner, which strands a merged PR's reconciliation. A `terminal` reply, which says falsely that the run ended. A new control verdict, which changes a path nothing needs changed. |
| D8 | The flag is required exactly with `verification`. The input (stdin or absolute path) is strict-loaded, validated and identified before the ledger lock, so a refusal exits 2 with `.superpowers` unchanged. Inside, `suspend_attempt` decides first; the stall bound gives `terminal` and no record. `park` revalidates, and the write commits before the reply prints. | AC1 "fail before mutation"; agent-helpers rule 4 (c1's `strict_load` composes the canonical hooks); The Bar defense in depth. | `load_json_request`, which accepts duplicate keys. Parking before the stall decision, which records a blocker for a stopped attempt. |
| D9 | The store's current version is 11. Schema 10 is bound and stepped with no bind plans, 8 and 9 keep their plans and step, and 7 and older compose. A present new member is `invalid_state`, and `migrate` reports 10 as `migrate`. The fixed base's helper is proved to refuse a schema-11 ledger as `unknown_schema` with an unchanged tree. | README: "A helper older than a ledger's schema refuses it" (#337 D10); the base-helper extraction precedent in `test_control_cutover` and `test_attempt_migration`; AC2. | A lenient step that overwrites present members, which hides a corrupt ledger. A writer marker naming the helper, which adds state the refusal already covers. |
| D10 | The `suspended` reply's literal cause set gains `verification`, and a test pins it to `OWNER_BLOCKED_ON_VALUES`. No interface version moves. | `delivery_model` imports no `agent_tools`; #473 D9 (reply additions keep version 2); #473 D11 pin precedent. | Importing `attempt_custody` into `delivery_model`. Bumping interface 2 for a value added to a closed list. |
| D11 | Docs change only where this change makes them false or incomplete. In the agent-skills README § Lifecycle helpers: the schema-11 step, the cause in the vocabulary list, the flag, and the known limitation that nothing resumes it before c3. In `python/README.md`: the pure module's added rules. | The Bar: re-point living documents in the same change, and known limitations belong in docs; c4 owns the protocol docs. | Full protocol docs now (c4). Leaving the closed vocabulary list stale. |
| D12 | Test seams: pure tables by import; vocabulary pins; CLI behaviour in a new `test_verification_suspension` module over `LifecycleHarness`, including the base helper and migration; schema-number and fixture updates in the four existing CLI modules. | agent-helpers rule 5; The Bar "Tests that can fail"; `LifecycleHarness` reuse precedent. | Call-count assertions. A separate migration module, which splits one schema's behaviour across files. |
| D13 | Refines D12 (grill): the schema bump reaches every test that pins the current number, compares a bound ledger literally or relabels a head state as older, including three modules outside the triage paths (`test_delivery_workflow`, `test_host_admission`, `test_delivery_sealing`). Legacy builders drop both new members below 11. | Code reads during the grill (`_as_legacy`, `legacy`, `assert_bound`); D9's strict step refuses a present member. | Teaching the 10 → 11 step to tolerate present members so the fixtures need no change, which hides a corrupt ledger (D9). |
| D14 | Planning: `_apply_one_issue_policy` takes a keyword `reply_parked` (default false) that only `direct-owner` passes. With it, an attempt suspended on an observation-gated cause takes D7's direct lane and ends in `parked`; without it, as at both control call sites, it is not resumable and gets the existing `terminal`. | D7; the policy already separates its callers by keyword (`require_forge`, `human_directed`); The Bar: explicit over implicit. | Keying the lane on `require_forge`, which ties the reply to an unrelated observation duty. Returning `parked` to control, which D7 rejects. |
| D15 | Planning: the store runs one strict step, `upgrade_ten` with `BlockerRefused` mapped to `invalid_state`, for every ledger below 11. Schemas 8, 9 and 10 share one bound-candidate helper, and 10 gets no bind plans. A ≤ 7 ledger is stepped before its run is minted, so a refused step mints nothing. `check_unlocked` still returns a ≤ 7 ledger as its schema-7 candidate. | D9; `locked_read`: "A refused ledger mints nothing"; precedent of the 8/9 bind helper. | Stepping after `mint_run`, where today's code sets the schema number, which mints a run for a ledger that is then refused. A separate 10-only branch, which duplicates the bind path. |
| D16 | Planning (test seams): the wire pin validates through the delivery model loaded from source, in-process (`validate_delivery_object`), and leaves `test_delivery_model.py`'s literal list as the older subset. The base-helper test first shows the extracted helper runs (its `migrate` reads a schema-10 copy as `current`) and only then asserts its refusals. | D10, D12; issue 500's in-process precedent; #337 D26's positive control in `test_attempt_migration`. | Using the existing literal in `test_delivery_model.py` as the pin, which never compares against `OWNER_BLOCKED_ON_VALUES`. Refusal assertions without a positive control, which would also pass for a helper that cannot start. |
| D17 | Planning: `validate_attempt` checks only that a non-null pointer is a string. The `sha256:` shape comes from R5 in the same `validate_state` call: every non-null pointer must name a record, and R1 makes every key an id. So `workflow-state` holds no second copy of the id pattern. | D5; issue 543 D1 (`verification_blocker` is the one home of the id shape); The Bar DRY. | A `sha256:` regular expression in `workflow-state`, which copies c1's private pattern and refuses nothing R5 lets through. |
| D18 | Standards review (PR544-B1): below schema 11, `validate_attempt` refuses a `verification` cause as `invalid suspended attempt cause`. Task 3 adds this beside the vocabulary change. A legacy ledger holding one is then refused in its schema-7 validation, before `mint_run`, by `migrate` and every locked read. | Reviewer: once the shared vocabulary admits `verification`, the ≤ 7 route mints and only then refuses the missing pointer, which breaks D15's "a refused step mints nothing". No legacy writer ever produced the cause. | Validating at 11 before minting, which cannot work because schema-11 validation needs the minted `transaction_id`. |
| D19 | Standards review (PR544-S1): the pointer rule gets refusal tests through a public locked read (`init-run --run-id`) on hand-written schema-11 ledgers. Each test pins the exact line and an unchanged `.superpowers` tree. Task 2 covers a pointer on an active attempt and on a `transport` suspension. Task 3 covers a parked attempt with no pointer, with a pointer to no record, and with a pointer to a record that does not list it. | Reviewer: the rule had no negative integration test; D12. | The pure R5 table alone, which never runs `validate_attempt` or the CLI. |
| D20 | Standards review (PR544-S3): `verification_blocker` refusals pass every map key, pointer and issue key they name through `_shown` (JSON-escaped, a string unquoted), so a key that holds a newline still gives one line. | Reviewer: `workflow-state` prints a refusal verbatim, and an unescaped key could make it multi-line. The c1 one-line contract. | `repr`, which adds quotes and so changes the labels the tests and docs use for ordinary ids. |
