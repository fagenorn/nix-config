# Task 2: Atomically adopt schema 3 and delivery transports

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Modify: `home/common/agent-skills/scripts/artifact_budget.py`
- Modify: `home/common/agent-skills/tests/test_workflow_state.py`
- Modify: `home/common/agent-skills/tests/test_artifact_budget.py`
- Create: `home/common/agent-skills/tests/test_delivery_workflow.py`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md`
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-issue/REVIEW.md`
- Modify: `home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md`
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify: `home/common/claude-code/skills/orchestrate-issues/evals/evals.json`
- Modify: `justfile`

**Interfaces:**
- Consumes the accepted Task 1 module by explicit path, requires
  `MODEL_INTERFACE_VERSION == 1`, and calls its validators/reducer rather than
  retaining parallel delivery tables.
- `workflow-state.py` writes schema 3. Its issue row has exactly legacy `issue`,
  `attempts`, `outcome` plus `delivery` and `delivery_remainders`; both custody
  arrays remain independently capped at two ordinals. Reads accept schema 3 or
  valid schema 2, and per D14 valid schema 1 through an in-memory adjacent
  1→2→3 chain; one complete validation precedes at most one atomic persistence.
- Control request interface 2 is the exact interface-1 request plus issue-keyed,
  sorted `forge`, `delivery_contracts`, `authorization_intents`,
  `authority_observations`, `reevaluation_evidence`, and
  `delivery_observations`. Direct request interface 2 has the exact interface-1
  keys plus nullable `delivery_contract` and the four sorted arrays for its issue.
  Both validate the complete request before lock/mutation and use one transition
  function.
- The action union adds `delivery_remainder`. A remainder response has exactly
  the fields specified in the design and returns ordered `pending_stage_ids` and
  strict requirements; callers never derive a stage from tracker/forge state.
- Adds CLI
  `checkpoint-delivery --repo-root ROOT --run-id RUN --now UTC --checkpoint-file FILE`.
  It validates raw bytes through
  `artifact-budget validate-report --boundary ship-checkpoint` before decode,
  locks, rechecks exact custody, folds observations atomically, reduces, and
  either returns the next typed action/requirement or suspends the same custody.
  Its response has exactly `interface_version` 2, literal `kind`
  `delivery_checkpointed`, `ledger_repo_root`, `run_id`, `issue`, `owner`,
  `custody`, `contract_digest`, sorted `accepted_observation_ids`, ordered
  `pending_stage_ids`, nullable `next_action`, sorted `requirements`, `state`
  (`active | suspended`), and nullable `blocked_on`.
- Replaces the source finish entry with
  `finish --repo-root ROOT --run-id RUN --now UTC --summary-file FILE`.
  `ship-summary/v2` carries issue and custody, so separate issue/attempt guessing
  is absent. Under lock it rechecks the same action, persists final facts/result,
  then emits `delivery_complete`, a genuine `terminal_failed`, or an eligible
  next remainder. Requirements and partial progress are never terminal failure.
- `artifact_budget.py` adds `ship-checkpoint` to the closed boundary set and
  validates `ship-handoff/v2`, `ship-checkpoint/v2`, and `ship-summary/v2` by
  loading Task 1's model. It may still read the exact legacy v1 summary shape for
  retained evidence, but no schema-3 producer emits it and workflow-state's v2
  finish rejects it.
- Production caller prose/evals consume only interface 2 and the closed typed
  action. They copy contract/intents/digests exactly, validate raw stdout before
  decode, run `current-launch` immediately before each effect, checkpoint the
  returned observation before advancing, and never invent implementation,
  delivery, authority or terminal failure.
- Runtime schemas remain centralized in `delivery_model.py`; the operational
  transport sequence is stated once in `from-issue/ship-handoff.md` and linked
  where a caller needs it. Do not paste field tables into every `SKILL.md`.

**Invariants:**
- Per D8/D14, schema-1 and schema-2 migrations preserve every legacy attempt,
  outcome, result byte and detail pointer. They initialize empty delivery truth
  only: no contract, intent, authority, observation, selected output, stage fact,
  postcondition success, remainder or cleanup claim.
- Migration is idempotent and fail-closed. Unknown fields, partial schema-3
  objects, invalid legacy rows, ambiguous repository identity, model-load error
  or version mismatch leave the original ledger byte-identical.
- Per D3, every effect path performs current-launch before the effect and again
  before writing its observation. A stale caller cannot write even if its effect
  returned; only a current trusted controller may later ingest exact source-bound
  evidence through the normal request/checkpoint input.
- Checkpoint deduplicates identical facts and rejects a conflicting same-id body
  before any write. A true blocking reason atomically records progress and
  suspends that same custody as `human_gate`, `external`, or `transport`; local
  evidence stays active and `unknown` remains reaper-only.
- Remainder action ids are `issue:r<remainder>:launch`; implementation ids remain
  `issue:attempt:launch`. Resume keeps ordinal/deadline and increments neither
  retry count. A genuine failed remainder with absent effect and valid recovery
  basis may allocate at most the second ordinal.
- Merge observation is folded before expiry. Three no-progress resumes stall,
  while progress-token change resets the stall sequence. Capacity ordering and
  existing implementation retry behavior remain intact.
- No source command opens or migrates the real issue-151 ledger. No installed
  activation, bridge runtime, provider command or external mutation is added.
- The Task 2 commit is one atomic source protocol cutover. No committed midpoint
  may expose schema 3 with v1 callers, v2 reports with schema 2, or duplicated
  model validation.

- [ ] **Step 1: Write migration and public delivery-round-trip tests**

First update existing fixtures in `test_workflow_state.py` to construct valid
interface-2 requests and exact custody refs. Retain every current lifecycle test;
add this explicit legacy-chain regression:

```python
def test_schema_one_migrates_through_two_to_three_with_one_atomic_write(self):
    self.init_run()
    legacy = self.legacy_schema_one_state_with_terminal_and_active_results()
    self.state_path.write_bytes(self.canonical_state_bytes(legacy))
    before_results = copy.deepcopy([
        attempt.get("result")
        for issue in legacy["issues"].values()
        for attempt in issue["attempts"]
    ])
    request = self.interface_two_control_request()
    response = self.control(request=request, now=DEFAULT_NOW)
    migrated = json.loads(self.state_path.read_text(encoding="utf-8"))
    self.assertEqual(migrated["schema_version"], 3)
    self.assertEqual([
        attempt.get("result")
        for issue in migrated["issues"].values()
        for attempt in issue["attempts"]
    ], before_results)
    self.assertEqual(self.delivery_success_claims(migrated), [])
    self.assertEqual(response["interface_version"], 2)

    stable = self.state_path.read_bytes()
    self.control(request=request, now=DEFAULT_NOW)
    self.assertEqual(self.state_path.read_bytes(), stable)
```

Beside that public regression, add a pure migration test that loads the source
module, calls `upgrade_state` on the same detached schema-1 value, and asserts
the returned value is schema 3 while the input remains byte-for-byte unchanged.
Patch `atomic_write_state` only in a focused transaction test and assert it is
called once with a schema-3 value; there must be no call whose value is schema 2.
This unit assertion supplements the public CLI migration rather than replacing
it.

Create `test_delivery_workflow.py`. Its fixture factory writes complete strict
contract, intent, selected output, authority and delivery observations using the
Task 1 public model; it creates only `sim.invalid` identities, fixed 40-hex
subjects and temporary ledgers. Put all CLI invocation in `DeliveryHarness`.
Its exact methods are `init(*, schema_fixture=None)`,
`control(request, *, now, ok=True)`, `direct(request, *, now, ok=True)`,
`current(custody, *, ok=True)`, `checkpoint(report, *, now, ok=True)`,
`finish(report, *, now, ok=True)`, `state_bytes()`, and `state()`. Each command
writes its request/report as canonical bytes under the harness temporary root,
invokes `workflow-state.py` in a subprocess, and returns decoded stdout only
after the corresponding artifact validator succeeds.

```python
class DeliveryWorkflowRoundTripTest(unittest.TestCase):
    def setUp(self):
        self.h = DeliveryHarness(self)
        self.fx = DeliveryFixtures()
        self.h.init()

    def test_normal_v3_owner_merge_precedes_delivered_truth(self):
        owner = self.h.direct(self.fx.direct_request(), now=self.fx.t0)
        self.assertEqual(owner["kind"], "owner")
        self.assertEqual(owner["custody"]["kind"], "implementation")
        custody = owner["custody"]
        effects = FakeProvider()
        for stage in ("select", "publish", "open", "merge"):
            self.assertTrue(self.h.current(custody)["current"])
            observation = effects.perform(owner, stage)
            checkpoint = self.h.checkpoint(
                self.fx.checkpoint(custody, delivery=[observation]), now=self.fx.tick()
            )
            owner = checkpoint["next_action"]
        state = self.h.state()["issues"]["151"]["delivery"]["postconditions"]
        self.assertEqual(state["pr_merged"]["state"], "observed")
        self.assertEqual(state["implementation_delivered"]["state"], "pending")
        reachability = effects.observe_integration(owner, subject="a" * 40)
        done = self.h.finish(
            self.fx.summary(custody, delivery=[reachability]), now=self.fx.tick()
        )
        self.assertEqual(done["state"], "delivery_complete")
        self.assertEqual(effects.calls, ["select", "publish", "open", "merge"])
        self.assertTrue(all(
            value["state"] in {"observed", "not_applicable"}
            for value in self.h.state()["issues"]["151"]["delivery"]["postconditions"].values()
        ))

    def test_normalized_controller_fact_does_not_replace_native_authority(self):
        request = self.fx.direct_request()
        request["authorization_intents"] = [self.fx.successor_intent(source="explicit_user")]
        owner = self.h.direct(request, now=self.fx.t0)
        self.assertEqual(owner["requirements"][0]["reason_code"], "native_evaluation_required")
        self.assertNotIn("allowed", json.dumps(self.h.state()))
        forged = self.fx.summary(owner["custody"], authority=[self.fx.unbound_allowed()])
        refused = self.h.finish(forged, now=self.fx.tick(), ok=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertNotIn("allowed", self.h.state_path.read_text(encoding="utf-8"))

    def test_partial_effect_then_denial_suspends_and_resumes_same_custody(self):
        owner = self.h.direct(self.fx.direct_request(), now=self.fx.t0)
        custody = owner["custody"]
        effect = self.fx.observed_stage("publish", custody=custody)
        denial = self.fx.host_rejection("open", custody=custody)
        checkpoint = self.h.checkpoint(
            self.fx.checkpoint(custody, delivery=[effect], authority=[denial]),
            now=self.fx.tick(),
        )
        self.assertEqual(checkpoint["state"], "suspended")
        self.assertEqual(checkpoint["blocked_on"], "human_gate")
        persisted = self.h.state()["issues"]["151"]
        self.assertTrue(self.fx.contains_observation(persisted, effect["id"]))
        resumed = self.h.direct(
            self.fx.direct_request(reevaluation=[self.fx.reevaluation(denial)]),
            now=self.fx.tick(),
        )
        self.assertEqual(resumed["custody"]["attempt"], custody["attempt"])
        self.assertEqual(resumed["deadline_at"], owner["deadline_at"])
        self.assertEqual(len(self.h.state()["issues"]["151"]["attempts"]), 1)
        self.assertTrue(self.fx.contains_observation(self.h.state()["issues"]["151"], denial["id"]))

    def test_stale_launch_has_zero_effect_and_zero_write(self):
        owner = self.h.direct(self.fx.direct_request(), now=self.fx.t0)
        stale = owner["custody"]
        self.h.control(self.fx.transfer_request(stale), now=self.fx.tick())
        before = self.h.state_bytes()
        provider = FakeProvider()
        self.assertFalse(self.h.current(stale, ok=False).returncode == 0)
        provider.perform_only_if_current(self.h, stale, "merge")
        self.assertEqual(provider.calls, [])
        refused = self.h.checkpoint(
            self.fx.checkpoint(stale, delivery=[self.fx.observed_stage("merge", custody=stale)]),
            now=self.fx.tick(), ok=False,
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(self.h.state_bytes(), before)

    def test_effect_result_after_transfer_requires_current_collector(self):
        owner = self.h.direct(self.fx.direct_request(), now=self.fx.t0)
        old = owner["custody"]
        returned = self.fx.provider_result_for("publish", custody=old)
        successor = self.h.control(self.fx.transfer_request(old), now=self.fx.tick())["actions"][0]
        before = self.h.state_bytes()
        old_write = self.h.checkpoint(
            self.fx.checkpoint(old, delivery=[returned]), now=self.fx.tick(), ok=False
        )
        self.assertNotEqual(old_write.returncode, 0)
        self.assertEqual(self.h.state_bytes(), before)
        accepted = self.h.checkpoint(
            self.fx.checkpoint(successor["custody"], delivery=[returned]), now=self.fx.tick()
        )
        self.assertEqual(accepted["accepted_observation_ids"], [returned["id"]])

    def test_nodo_arcwave_argus_and_normal_cases(self):
        nodo = self.fx.nodo_case()
        action = self.h.direct(nodo.request, now=self.fx.t0)
        self.assertEqual(action["kind"], "delivery_remainder")
        self.assertEqual(action["pending_stage_ids"], ["close", "remote", "worktree", "local"])
        self.assertEqual(len(self.h.state()["issues"]["1314"]["attempts"]), nodo.prior_attempts)
        self.assertEqual(self.h.finish(nodo.complete(action), now=self.fx.tick())["state"], "delivery_complete")

        arc = self.fx.arcwave_case()
        action = self.h.direct(arc.request, now=self.fx.tick())
        self.assertEqual(action["pending_stage_ids"][0], "record")
        missing = self.h.checkpoint(arc.without_live_head(action), now=self.fx.tick())
        self.assertEqual(missing["requirements"][0]["reason_code"], "live_pr_head_required")
        self.assertFalse(missing["terminal"])

        argus = self.fx.argus_case()
        exact = self.h.direct(argus.exact_private_request, now=self.fx.tick())
        self.assertNotIn("scope_tuple_required", json.dumps(exact))
        for request in (argus.public_request, argus.other_endpoint_request,
                        argus.other_payload_request):
            refused = self.h.direct(request, now=self.fx.tick())
            self.assertEqual(refused["requirements"][0]["reason_code"], "scope_tuple_required")
        completed = self.h.checkpoint(argus.human_completion(exact), now=self.fx.tick())
        self.assertTrue(argus.rejection_id in json.dumps(self.h.state()))
        self.assertNotIn("agent_authorized", json.dumps(completed))

    def test_remainder_cap_resume_stall_expiry_and_merge_order(self):
        first = self.h.direct(self.fx.failed_delivery_request(effect_absent=True), now=self.fx.t0)
        self.assertEqual(first["custody"]["remainder"], 1)
        resumed = first
        for _ in range(2):
            resumed = self.h.direct(self.fx.resume_request(resumed), now=self.fx.tick())
            self.assertEqual(resumed["custody"]["remainder"], 1)
        stalled = self.h.direct(self.fx.resume_request(resumed), now=self.fx.tick())
        self.assertEqual(stalled["state"], "suspended")
        self.assertEqual(stalled["suspend_phase"], "stall")

        merge = self.fx.merge_observation(first["custody"])
        at_deadline = self.h.checkpoint(
            self.fx.checkpoint(first["custody"], delivery=[merge]),
            now=first["deadline_at"],
        )
        self.assertIn(merge["id"], at_deadline["accepted_observation_ids"])
        self.assertEqual(self.fx.remainder_count(self.h.state(), 151), 1)
        second = self.h.direct(self.fx.retry_request(at_deadline), now=self.fx.tick())
        self.assertEqual(second["custody"]["remainder"], 2)
        capped = self.h.finish(self.fx.failed_summary(second), now=self.fx.tick())
        self.assertEqual(capped["state"], "terminal_failed")
        self.assertEqual(self.fx.remainder_count(self.h.state(), 151), 2)

    def test_source_and_installed_cli_load_one_model_and_fail_closed(self):
        source = self.h.round_trip_with_layout("source")
        installed = self.h.round_trip_with_layout("installed")
        self.assertEqual(source.semantic_result, installed.semantic_result)
        for mutation in ("missing", "directory", "wrong_interface"):
            run = self.h.round_trip_with_layout("installed", model_mutation=mutation, ok=False)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(run.ledger_after, run.ledger_before)
```

Implement every named harness method in this test file before the class using
`subprocess.run`, canonical temporary report files, and assertions that raw
stdout has validated before `json.loads`. `DeliveryFixtures` contains
the full strict literal constructors used by these tests and validates each
object through `delivery_model.validate_delivery_object`; `FakeProvider` has one
`calls` list and no network path. Do not replace these public CLI tests with
monkeypatches of workflow-state internals.

- [ ] **Step 2: Write report-boundary and production-caller tests**

Extend `test_artifact_budget.py` with a table-driven raw-byte test:

```python
def test_delivery_v2_boundaries_accept_exact_shapes_and_reject_hybrids(self):
    valid = delivery_boundary_fixtures()
    for boundary in ("ship-handoff", "ship-checkpoint", "ship-summary"):
        with self.subTest(boundary=boundary):
            accepted = self.run_validate(boundary, valid[boundary], use_stdin=True)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertEqual(accepted.stdout, canonical_bytes(valid[boundary]))
    mutations = delivery_boundary_mutations(valid)
    self.assertEqual(set(mutations), {
        "unknown_key", "legacy_new_hybrid", "changed_contract_digest",
        "stale_action", "missing_postcondition_evidence", "public_audience",
        "changed_data_digest", "fabricated_host_reference",
        "unsuccessful_absence_probe", "bool_ordinal", "duplicate_observation",
    })
    for name, boundary, raw in mutations.values():
        with self.subTest(name=name):
            refused = self.run_validate_raw(boundary, raw)
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(refused.stdout, b"")
```

`delivery_boundary_fixtures()` returns all three exact design shapes sharing one
contract/custody. `delivery_boundary_mutations()` recomputes enclosing hashes
after each semantic mutation so every case reaches the intended validator;
duplicate-key and invalid-UTF-8 cases mutate raw bytes and remain raw through the
validator. Also assert a strict v1 legacy summary remains readable only by its
legacy validator path, while adding any v2 member to it fails.

Extend `test_workflow_skill_contracts.py` and orchestration evals with:

```python
def test_delivery_interface_two_is_one_atomic_production_caller_contract(self):
    documents = {
        str(path.relative_to(REPO_ROOT)): normalized(path.read_text(encoding="utf-8"))
        for path in (FROM_ISSUE, AUTO, FROM_ISSUE.parent / "ship-handoff.md",
                     SHIP_ISSUE, SHIP_ISSUE_REVIEW, SHIP_ISSUE_HUMAN_GATE,
                     ORCHESTRATE)
    }
    required = (
        "interface_version 2", "ship-checkpoint/v2", "ship-summary/v2",
        "custody", "current-launch", "validate before decoding",
        "checkpoint-delivery", "delivery_remainder",
    )
    for name, text in documents.items():
        with self.subTest(name=name):
            for phrase in required_for_document(name, required):
                self.assertIn(phrase, text)
    corpus = " ".join(documents.values())
    self.assertNotIn("infer the next stage from tracker", corpus)
    self.assertNotIn("unfinished delivery as failed", corpus)
    self.assertNotRegex(corpus, r"--attempt\s+<.*>\s+--result-file")

def test_orchestration_eval_covers_denial_partial_progress_and_remainder(self):
    cases = json.loads(ORCHESTRATE_EVALS.read_text(encoding="utf-8"))
    text = json.dumps(cases, sort_keys=True)
    for phrase in ("partial effect", "host rejection", "same custody",
                   "delivery_remainder", "zero external effect",
                   "implementation_delivered", "pr_merged"):
        self.assertIn(phrase, text)
```

Define `required_for_document` as a closed literal mapping in the test, so each
caller is held only to its role but every required phrase is assigned at least
once. The orchestration eval includes a fully specified simulated input and
expected typed response, not only keyword prose.

- [ ] **Step 3: Run the new tests and observe RED**

```bash
python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py \
  -k test_schema_one_migrates_through_two_to_three_with_one_atomic_write -v
python3 -m unittest home/common/agent-skills/tests/test_artifact_budget.py \
  -k test_delivery_v2_boundaries_accept_exact_shapes_and_reject_hybrids -v
python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -v
python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  -k delivery_interface_two -v
```

Expected: exit nonzero because workflow state is schema 2/interface 1,
`ship-checkpoint` is not a report boundary, and production callers do not carry
the v2 protocol. Preserve the terminal output. Fix test construction errors
before implementation; do not accept a RED caused by malformed fixtures.

- [ ] **Step 4: Implement schema 3 and the atomic runtime cutover**

Load the model before reading a request or ledger. Follow the existing
`conformance.py` `SourceFileLoader` pattern: source uses the regular sibling,
installed mode uses exactly lexical `~/.agents/lib/python/delivery_model.py`;
register the module before execution, remove it after a failed load, require a
regular file and interface version 1, and never search `sys.path`.

Replace the one-step `PRIOR_SCHEMA_VERSION` assumption with explicit adjacent
migrators:

```python
MIGRATORS = {1: migrate_1_to_2, 2: migrate_2_to_3}

def upgrade_state(value):
    candidate = copy.deepcopy(value)
    seen = set()
    while isinstance(candidate, dict) and candidate.get("schema_version") != 3:
        version = candidate.get("schema_version")
        if type(version) is not int or version in seen or version not in MIGRATORS:
            return value
        seen.add(version)
        candidate = MIGRATORS[version](candidate)
    return validate_state(candidate)
```

`migrate_1_to_2` retains the current suspension defaults and `prior_run`
behavior. `migrate_2_to_3` adds only the exact empty delivery and empty remainder
shape after deriving unambiguous project/repository identity from strict request
input. Migration occurs on a detached copy; the caller validates the final v3
state before `atomic_write_state` and never writes schema 2 as an intermediate.

Make control/direct normalize their differently shaped envelopes into one
issue-keyed transition input before locking. Validate all delivery objects and
cross-digests before lock. Under lock, reload state, revalidate custody/current
launch, fold request facts canonically, run the Task 1 reducer, then either
return implementation/remainder custody or a typed requirement. Only the trusted
control/direct boundary may append normalized intent; owner summaries cannot.

Implement `checkpoint-delivery` and the v2 finish entry exactly as **Interfaces**
states. Capture the report as regular raw bytes, invoke artifact-budget on those
bytes before JSON decode, then under lock compare issue/run/contract/custody to
ledger truth. Persist facts and suspension in one atomic replacement. Emit
canonical JSON only after persistence. Checkpoint never terminalizes custody;
finish never maps a requirement or partial success to `terminal_failed`.

Reduce stage facts in contract order. Observe merge before expiry/reaping;
calculate deadline/stall/retry only after accepted observations update the
progress token. Resume the same remainder in place; allocate remainder 2 only
after genuine failure, absent effect and valid recovery basis; refuse a third.
Keep implementation retry and capacity behavior covered by existing tests.

- [ ] **Step 5: Implement report validation and all production callers**

Add the `ship-checkpoint` boundary and v2 dispatch in `artifact_budget.py`.
Capture raw bytes before decode, preserve duplicate-key and invalid-UTF-8
refusal, load the pure model, validate the outer boundary's exact keys and every
nested delivery object, then emit the accepted canonical bytes. Do not copy a
second object schema into artifact-budget. Keep strict legacy v1 summary reading
only for historical files; reject hybrids and do not let schema-3 finish consume
v1.

Update from-issue, AUTO, its ship handoff, ship-issue, REVIEW, HUMAN-GATE, and
orchestration together. Their normative sequence is:

1. validate raw direct/control/handoff/checkpoint/summary bytes before decoding;
2. copy the exact contract, intent chain, digests, custody and pending stages;
3. execute only the returned closed action after `current-launch` returns the
   exact four-key current result for that custody;
4. recheck current launch before submitting the returned observation;
5. submit `ship-checkpoint/v2` immediately for partial progress or blocking
   authority/provider results and wait for persisted response;
6. use `ship-summary/v2` only for all required postconditions or genuine custody
   failure; and
7. follow the returned typed implementation/remainder/requirement outcome without
   synthesizing authority, delivery, retry, terminal state or a permission ritual.

Add one orchestration eval each for ordinary delivery, partial effect followed
by denial/same-custody resume, and a stale launch with zero effect/write. The
caller docs state source integration is not activation and never direct this
issue's live run through schema 3.

- [ ] **Step 6: Verify focused behavior, the full suite and managed build**

```bash
set -euo pipefail
run_with_receipt() {
  receipt=$1
  log=$2
  shift 2
  set +e
  "$@" >"$log" 2>&1
  status=$?
  set -e
  printf '%s\n' "$status" >"$receipt"
  return "$status"
}
run_with_receipt /private/tmp/issue-151-task2-focused.exit \
  /private/tmp/issue-151-task2-focused.log \
  python3 -m unittest \
    home/common/agent-skills/tests/test_delivery_model.py \
    home/common/agent-skills/tests/test_delivery_workflow.py \
    home/common/agent-skills/tests/test_workflow_state.py \
    home/common/agent-skills/tests/test_artifact_budget.py \
    home/common/agent-skills/tests/test_workflow_skill_contracts.py -v
run_with_receipt /private/tmp/issue-151-task2-full.exit \
  /private/tmp/issue-151-task2-full.log just agent-workflow-tests
run_with_receipt /private/tmp/issue-151-task2-build.exit \
  /private/tmp/issue-151-task2-build.log just build
devenv -O packages:pkgs "python3Packages.pyyaml" shell -- \
  python3 /Users/anis/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  home/common/agent-skills/skills/from-issue
devenv -O packages:pkgs "python3Packages.pyyaml" shell -- \
  python3 /Users/anis/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  home/common/agent-skills/skills/ship-issue
devenv -O packages:pkgs "python3Packages.pyyaml" shell -- \
  python3 /Users/anis/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  home/common/claude-code/skills/orchestrate-issues
```

Expected: the three test/build commands exit 0 and each receipt contains `0`.
Because
the wrapper captures status with `set +e`, every invoked command writes its real
receipt before returning that status to the fail-fast outer shell. Each modified
skill folder also prints `Skill is valid!`; this checks frontmatter and unfinished
scaffolding while the executable tests above remain the behavioral evidence.

Then prove scoped content and diff size:

```bash
set -euo pipefail
git diff --check -- \
  home/common/agent-skills/scripts/workflow-state.py \
  home/common/agent-skills/scripts/artifact_budget.py \
  home/common/agent-skills/tests \
  home/common/agent-skills/skills/from-issue \
  home/common/agent-skills/skills/ship-issue \
  home/common/claude-code/skills/orchestrate-issues justfile
python3 - <<'PY'
import subprocess
paths = subprocess.check_output(["git", "diff", "--name-only", "--"]).decode().splitlines()
allowed = {
    "home/common/agent-skills/scripts/workflow-state.py",
    "home/common/agent-skills/scripts/artifact_budget.py",
    "home/common/agent-skills/tests/test_workflow_state.py",
    "home/common/agent-skills/tests/test_artifact_budget.py",
    "home/common/agent-skills/tests/test_delivery_workflow.py",
    "home/common/agent-skills/tests/test_workflow_skill_contracts.py",
    "home/common/agent-skills/skills/from-issue/SKILL.md",
    "home/common/agent-skills/skills/from-issue/AUTO.md",
    "home/common/agent-skills/skills/from-issue/ship-handoff.md",
    "home/common/agent-skills/skills/ship-issue/SKILL.md",
    "home/common/agent-skills/skills/ship-issue/REVIEW.md",
    "home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md",
    "home/common/claude-code/skills/orchestrate-issues/SKILL.md",
    "home/common/claude-code/skills/orchestrate-issues/evals/evals.json",
    "justfile",
}
assert set(paths) == allowed, (set(paths), allowed)
for path in paths:
    diff = subprocess.check_output(["git", "diff", "--unified=10", "--", path])
    assert len(diff) <= 65_536, (path, len(diff))
PY
```

Expected: exit 0; exactly the 15 Task 2 paths differ from its accepted base and
each ordinary per-file U10 diff is within 65,536 bytes. If any file exceeds the
limit, split test responsibility into a new focused test module and register it;
do not omit lines, reduce assertions, split one file's patch synthetically, or
raise a cap.

- [ ] **Step 7: Commit the atomic adoption and produce complete review evidence**

```bash
set -euo pipefail
git add \
  home/common/agent-skills/scripts/workflow-state.py \
  home/common/agent-skills/scripts/artifact_budget.py \
  home/common/agent-skills/tests/test_workflow_state.py \
  home/common/agent-skills/tests/test_artifact_budget.py \
  home/common/agent-skills/tests/test_delivery_workflow.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  home/common/agent-skills/skills/from-issue/SKILL.md \
  home/common/agent-skills/skills/from-issue/AUTO.md \
  home/common/agent-skills/skills/from-issue/ship-handoff.md \
  home/common/agent-skills/skills/ship-issue/SKILL.md \
  home/common/agent-skills/skills/ship-issue/REVIEW.md \
  home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md \
  home/common/claude-code/skills/orchestrate-issues/SKILL.md \
  home/common/claude-code/skills/orchestrate-issues/evals/evals.json \
  justfile
test -z "$(git diff --name-only)"
git diff --cached --check
git commit -S -m "feat: reconcile delivery lifecycle" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```

Expected: signed commit succeeds. Produce and validate a complete Task 2 package
from the original Task 2 base, not only the final fix commit, with all changed
paths/lines and unchanged caps. After independent Task 2 conformance and quality
acceptance, produce a fresh complete cumulative package from immutable delivery
base `4cd9408c4e538d6c9f0b9941e43d05d43a77c9a8` through final head. Final
conformance and correctness are distinct independent axes and must include the
accepted design spec as product, both task ranges, D14, actual verification
receipts and the root-controller operational bridge evidence without presenting
that evidence as shipped runtime or product tests.
