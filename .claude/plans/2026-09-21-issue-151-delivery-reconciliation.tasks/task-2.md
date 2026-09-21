# Task 2: Atomically adopt schema 3 and delivery transports

**Files:**
- Modify: `home/common/agent-skills/scripts/delivery_model/_objects.py`
- Modify: `home/common/agent-skills/scripts/delivery_model/_reconcile.py`
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py`
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Modify: `home/common/agent-skills/scripts/artifact_budget.py`
- Modify: `home/common/agent-skills/tests/_delivery_model_fixtures.py`
- Modify: `home/common/agent-skills/tests/test_delivery_model.py`
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
- Retain Task 1's eight-name v1 facade. Private `_objects`/`_reconcile`/`_wire`
  own D19 stage relationships/reduction/envelopes; workflow-state supplies facts,
  not policy copies.
- Workflow-state writes schema 3. `upgrade_state(value, *, run_id,
  migration_contracts)` composes 1→2→3 in memory, validates the candidate with
  keyword `run_id`, and writes once at most. Current-launch validates legacy
  reads without lock, upgrade or write.
- Control v2 keeps v1 top-level keys, replaces `owners`, and adds issue-keyed
  `forge`, `delivery_contracts`, `authorization_intents`,
  `authority_observations`, `reevaluation_evidence`, `delivery_observations`,
  `requested_scopes`. Each map has exactly the requested canonical decimal keys;
  values are forge objects, strict contract|null, sorted unique fact arrays, or
  strict scope|null. Missing/extra/`01`, or null contract with facts/scope,
  refuses before lock. Direct keeps v1 keys plus singular contract,
  those four fact arrays and required nullable `requested_scope`. Owner facts are
  exact event_id/issue/custody/state=unavailable; duplicate event/custody,
  historical-as-current, hybrid, unknown or mismatch refuses.
- Control output keeps v1 outer keys. Summary has custody|null instead of attempt,
  contract digest|null, ordered stages and sorted requirements; delta is exact
  issue/custody/kind/state. Wait/finalize stay exact. Spawn/resume/retry/direct
  owner add strict custody, contract/digest, stages, requirements and nullable
  evaluation/scope. Direct observe admits all eight typed requirements; terminal
  stays v1. Remainder adds evaluation/scope. Finish-created
  remainder uses null scope and the ready-stage requirement, or an observation
  requirement keyed by a missing postcondition when no stage is ready. It invents
  no effect stage. Every nested member validates through the model.
- `ship-checkpoint/v2` requires nullable post-fold ready-stage scope. Ordinary
  `delivery_checkpointed` echoes it and is active|suspended; count-3
  `delivery_stalled` has no action/requirements/evaluation/block/scope. Finish is
  `finish --repo-root ROOT --run-id RUN --now UTC --summary-file FILE`: complete
  has no pending stage; genuine owner failure has the accepted reason/source;
  eligible retry returns remainder; partial progress/requirements never fail.
- Artifact-budget adds `ship-checkpoint`/`workflow-response`, loads the model and
  validates v2 reports plus raw workflow responses before decode. Bootstrap picks
  active custody, else latest remainder, else implementation; callers normalize
  requirements before control. Legacy v1 summary stays read-only.
- Handoff preserves prior scope as history; summaries/stalled outputs add none.
  Callers bind invocation to echo, fence before effect/observation, and never
  derive stages from tracker/forge.

**Invariants:**
- Per D8/D14/D17, migrations preserve attempts/outcomes/result bytes/details and
  initialize no delivery truth. Request-derived contract|null context must match
  candidate facts/remainder. Malformed, ambiguous or mismatched input writes
  nothing. Legacy current-launch returns four exact keys, changing no bytes.
- Per D3/D18, every effect and observation uses the exact current launch. Late
  direct/control facts retain original launch; old allow grants nothing and old
  rejection remains. A post-rejection action appears only with its first durably
  persisted consumption; replay/transfer/crash cannot reissue it. Successor
  intent and reevaluation evidence are independent bases.
- Per D19, callers build scope without copying intent; after folding, the model
  binds it to the ordered ready stage/target. Null yields the ready-stage local
  requirement or preserves dependency/postcondition requirements when none is
  ready. Wrong/dependency/completed scope refuses without write; valid uncovered
  scope human-gates; covered ordinary scope native-evaluates without prior allow.
  Next stage, transfer and resume require fresh proposals.
- Selected-output ingestion verifies acceptance/review/test categories; ids imply
  none. Checkpoint deduplicates; blockers suspend. Merge folds before expiry.
  Same-token suspensions store 0/1/2/3; three resumes are allowed, 3 stalls, and
  real progress resets 0.
- Implementation/remainder identities stay disjoint. Resume keeps ordinal/deadline
  and spends no retry; only failure+absent effect+recovery allocates remainder 2,
  never 3. Implementation retry/capacity remains.
- One source-only atomic cutover has no activation/effect/mixed generation.
  Structure grants no authority; workflow checks freshness under lock.
  Tests use synthetic ledgers/layouts.

- [ ] **Step 1: Write migration and public delivery-round-trip tests**

Extend `_delivery_model_fixtures.py` with `contract_and_delivery_for_stage(model,
stage_id)` and `stage_scope(model, contract, stage_id)`: both build sealed strict
synthetic objects from the contract stage, not from an intent. Add this public
model regression to `test_delivery_model.py`:

```python
def test_requested_scope_is_bound_to_postfold_contract_stage(self):
    contract, delivery = contract_and_delivery(self.model); active = custody()
    def reduce(c, d, scope):
        return self.model.reduce_delivery(c, d, evaluation=evaluation(
            custody=active, current_launch=True, requested_scope=scope))

    old_merge = delivery["authorization_intents"][0]["scopes"][0]
    with self.assertRaises(self.model.DeliveryModelError):
        reduce(contract, delivery, old_merge)
    missing = reduce(contract, delivery, None)
    self.assertIsNone(missing["requested_scope"])
    self.assertEqual(missing["requirements"], [{
        "kind": "scope_tuple", "subject_id": "select",
        "reason_code": "scope_tuple_required", "detail_pointer": None}])
    uncovered = reduce(contract, delivery, stage_scope(self.model, contract, "select"))
    self.assertEqual((uncovered["blocking"]["blocked_on"],
                      uncovered["requirements"][0]["reason_code"]),
                     ("human_gate", "authorization_intent_required"))
    covered_contract, covered_delivery, covered_scope = \
        contract_and_delivery_for_stage(self.model, "select")
    ordinary = reduce(covered_contract, covered_delivery, covered_scope)
    self.assertEqual((ordinary["requested_scope"],
                      ordinary["requirements"][0]["reason_code"],
                      ordinary["blocking"]),
                     (covered_scope, "native_evaluation_required", None))
```


Table cases fold select before a fresh publish proposal; reject pre-fold publish,
nonnull-after-completion and wrong target/slot; and preserve input/ledger bytes.

In `test_workflow_state.py`, retain all lifecycle tests and update fixtures to
interface 2/custody refs. Public control migrates a schema-1 terminal+active
fixture with validated contract: schema 3, byte-equal legacy result, no invented
delivery/consumption, v2 output, idempotent second call. A pure test calls
`upgrade_state(value, run_id=self.run_id, migration_contracts={151: contract})`,
asserts detached input unchanged and validates the result with keyword `run_id`.
The transaction mock sees one final schema-3 write and never schema 2. A failed
consumption write renders no response and preserves bytes; rerun emits one action.

Public no-write cases reject contractless candidate facts and repository-mismatch.
Legacy active implementation current-launch returns the exact four keys at exit
0 with identical ledger/root inventory; a remainder id is likewise a read-only
false result. Mocks do not replace these CLI cases.

Create `test_delivery_workflow.py` with strict fixtures and one subprocess
`DeliveryHarness`: `init(*, schema_fixture=None)`, `control`, `direct`, `current`,
`checkpoint`, `finish`, `state_bytes`, `state`. Successful raw stdout (including
strict bootstrap) validates before decode; named report boundaries precede
workflow-state and errors are not decoded. `known_unavailability` emits only an
explicit stable-id fact, never bootstrap presence; owner cases cover malformed,
duplicate and historical facts.
`direct_request(requested_scope=...)`, control's issue-keyed `requested_scopes`,
and `checkpoint(..., requested_scope=...)` always include the required nullable
field; scope builders derive actual synthetic commands, never intents.

```python
class DeliveryWorkflowRoundTripTest(unittest.TestCase):
    def setUp(self):
        self.h = DeliveryHarness(self)
        self.fx = DeliveryFixtures()
        self.bootstrap = self.h.init()
        self.assertEqual(self.bootstrap["requirements"], [])

    def test_bootstrap_and_owner_observation_contracts(self):
        for kind in ("implementation", "remainder"):
            h = DeliveryHarness(self)
            boot = h.init(schema_fixture=self.fx.active_custody_state(kind))
            requirement = boot["requirements"][0]
            self.assertEqual(self.fx.control_from_bootstrap(
                boot, unavailable=[])["owners"], [])
            request = self.fx.control_from_bootstrap(
                boot, unavailable=[self.fx.known_unavailability(requirement)])
            self.assertEqual(request["owners"][0]["custody"]["action_id"],
                             requirement["custody"]["action_id"])
            self.assertTrue(request["worktrees"]); h.control(request, now=self.fx.t0)
        for variant in ("missing_map_issue", "extra_map_issue", "noncanonical_01",
                        "null_contract_with_facts", "hybrid", "unknown_custody",
                        "issue_action_mismatch", "duplicate_event_conflict",
                        "duplicate_custody"):
            before = self.h.state_bytes()
            refused = self.h.control(self.fx.owner_observation_case(variant),
                                     now=self.fx.t0, ok=False)
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(self.h.state_bytes(), before)
        historical = self.h.control(self.fx.owner_observation_case("known_historical"),
                                    now=self.fx.t0)
        self.assertTrue(self.fx.current_custody_remains_active(historical))

    def test_normal_v3_owner_merge_precedes_delivered_truth(self):
        stages = ("select", "publish", "open", "merge")
        owner = self.h.direct(self.fx.direct_request(
            requested_scope=self.fx.requested_scope(stages[0])), now=self.fx.t0)
        custody = owner["custody"]
        effects = FakeProvider()
        for index, stage in enumerate(stages):
            self.assertTrue(self.h.current(custody)["current"])
            allowed, observed = effects.evaluate_and_perform(self.h, owner, stage)
            next_scope = (self.fx.requested_scope(stages[index + 1])
                          if index + 1 < len(stages) else None)
            checkpoint = self.h.checkpoint(self.fx.checkpoint(
                custody, authority=[allowed], delivery=[observed],
                requested_scope=next_scope), now=self.fx.tick())
            if next_scope is not None:
                owner = checkpoint["next_action"]
                self.assertEqual(owner["requested_scope"], next_scope)
        self.assertIsNone(checkpoint["requested_scope"])
        self.assertIsNone(checkpoint["next_action"])
        self.assertEqual(checkpoint["requirements"], [{
            "kind": "observation", "subject_id": "implementation_delivered",
            "reason_code": "postcondition_observation_required",
            "detail_pointer": None,
        }])
        state = self.h.state()["issues"]["151"]["delivery"]["postconditions"]
        self.assertEqual(state["pr_merged"]["state"], "observed")
        self.assertEqual(state["implementation_delivered"]["state"], "pending")
        reachability = effects.observe_integration(custody, subject="a" * 40)
        done = self.h.finish(
            self.fx.summary(custody, delivery=[reachability]), now=self.fx.tick())
        self.assertEqual(done["state"], "delivery_complete")
        self.assertEqual(effects.calls, list(stages))

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

    def test_actual_scope_outcomes_echo_and_ordinary_execution(self):
        premature = DeliveryHarness(self); premature.init()
        premature.assert_refused_without_write("direct", self.fx.direct_request(
            requested_scope=self.fx.requested_scope("publish")), now=self.fx.t0)
        owner = self.h.owner_after_completed_stage(self.fx, "select")
        provider = FakeProvider()
        scope = self.fx.requested_scope("publish")
        self.assertEqual(owner["requested_scope"], scope)
        self.assertEqual(owner["requirements"][0]["reason_code"],
                         "native_evaluation_required")
        self.assertNotIn("allowed", json.dumps(self.h.state()))
        before = self.h.state_bytes()
        provider.perform_only_if_scope(self.h, owner, self.fx.requested_scope("open"))
        self.assertEqual((provider.calls, self.h.state_bytes()), ([], before))
        allowed, effect = provider.evaluate_and_perform(self.h, owner, "publish")
        next_scope = self.fx.requested_scope("open")
        checked = self.h.checkpoint(self.fx.checkpoint(
            owner["custody"], authority=[allowed], delivery=[effect],
            requested_scope=next_scope), now=self.fx.tick())
        self.assertEqual((checked["requested_scope"],
                          checked["next_action"]["requested_scope"]),
                         (next_scope, next_scope))
        self.assertEqual(provider.calls, ["publish"])

        missing = self.h.direct(self.fx.direct_request(requested_scope=None),
                                now=self.fx.tick())
        self.assertIsNone(missing["requested_scope"])
        self.assertEqual(missing["requirements"][0], {
            "kind": "scope_tuple", "subject_id": "open",
            "reason_code": "scope_tuple_required", "detail_pointer": None})
        for invalid in (self.fx.requested_scope("merge"),
                        self.fx.requested_scope("open", target="other")):
            self.h.assert_refused_without_write("direct", self.fx.direct_request(
                requested_scope=invalid), now=self.fx.tick())

    # Assert requirement-only contractless outputs.

    def test_denial_consumption_resume_and_transfer_replay(self):
        owner = self.h.owner_after_completed_stage(self.fx, "select")
        custody = owner["custody"]
        denial = self.fx.host_rejection("publish", custody=custody)
        scope = self.fx.requested_scope("publish")
        checkpoint = self.h.checkpoint(self.fx.checkpoint(
            custody, authority=[denial], requested_scope=scope),
            now=self.fx.tick())
        self.assertEqual((checkpoint["state"], checkpoint["blocked_on"],
                          checkpoint["requested_scope"]),
                         ("suspended", "human_gate", scope))
        evidence = self.fx.reevaluation(denial)
        resumed = self.h.direct(self.fx.resume_request(
            checkpoint, requested_scope=None), now=self.fx.tick())
        self.assertIsNone(resumed["requested_scope"])
        self.assertEqual((resumed["custody"]["attempt"], resumed["deadline_at"]),
                         (custody["attempt"], owner["deadline_at"]))
        evaluated = self.h.checkpoint(self.fx.checkpoint(
            resumed["custody"], reevaluation=[evidence], requested_scope=scope),
            now=self.fx.tick())
        self.assertEqual((evaluated["requested_scope"], evaluated["next_action"]),
                         (scope, None))
        permit = evaluated["authority_evaluation"]
        self.assertEqual((permit["basis_id"], [x["use_key"] for x in
            self.h.state()["issues"]["151"]["delivery"]
              ["authority_evaluation_consumptions"]]),
                         (evidence["id"], [permit["use_key"]]))
        allowed = self.fx.allowed_for_permit(permit, resumed["custody"])
        active = self.h.checkpoint(self.fx.checkpoint(
            resumed["custody"], authority=[allowed], requested_scope=scope),
            now=self.fx.tick())
        self.assertEqual((active["state"], active["blocked_on"]), ("active", None))
        later = self.fx.later_rejection(scope, resumed["custody"])
        stopped = self.h.checkpoint(self.fx.checkpoint(
            resumed["custody"], authority=[later], requested_scope=scope),
            now=self.fx.tick())
        self.assertEqual((stopped["state"], stopped["blocked_on"]),
                         ("suspended", "human_gate"))
        replay = self.h.direct(self.fx.resume_request(
            stopped, requested_scope=scope, reevaluation=[evidence]), now=self.fx.tick())
        self.assertIsNone(replay["authority_evaluation"])
        successor = self.h.control(self.fx.transfer_request(replay["custody"]),
                                   now=self.fx.tick())["actions"][0]
        transferred = self.h.direct(self.fx.direct_request(
            custody=successor["custody"], requested_scope=scope,
            reevaluation=[evidence]), now=self.fx.tick())
        self.assertIsNone(transferred["authority_evaluation"])
        self.assertEqual(len(self.h.state()["issues"]["151"]["delivery"]
                             ["authority_evaluation_consumptions"]), 1)
        self.assertTrue(self.fx.contains_observation(
            self.h.state()["issues"]["151"], denial["id"]))

    def test_stale_launch_has_zero_effect_and_zero_write(self):
        owner = self.h.direct(self.fx.direct_request(), now=self.fx.t0)
        stale = owner["custody"]
        self.h.control(self.fx.transfer_request(stale), now=self.fx.tick())
        before = self.h.state_bytes()
        provider = FakeProvider()
        stale_result = self.h.current(stale)
        self.assertEqual(stale_result, {
            "action_id": stale["action_id"], "current": False,
            "current_action_id": self.fx.current_action_id(),
            "reason": "superseded_launch",
        })
        provider.perform_only_if_current(self.h, stale, "merge")
        self.assertEqual(provider.calls, [])
        refused = self.h.checkpoint(
            self.fx.checkpoint(stale, delivery=[self.fx.observed_stage("merge", custody=stale)]),
            now=self.fx.tick(), ok=False,
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(self.h.state_bytes(), before)

    def test_successor_collects_late_effect_and_authority_without_old_grant(self):
        scope = self.fx.requested_scope("select")
        owner = self.h.direct(self.fx.direct_request(requested_scope=scope), now=self.fx.t0)
        old = owner["custody"]
        returned = self.fx.provider_result_for("select", custody=old)
        allowed = self.fx.host_allowed("select", custody=old)
        rejected = self.fx.host_rejection("select", custody=old)
        successor = self.h.control(self.fx.transfer_request(old),
                                   now=self.fx.tick())["actions"][0]
        before = self.h.state_bytes()
        old_write = self.h.checkpoint(self.fx.checkpoint(
            old, delivery=[returned]), now=self.fx.tick(), ok=False)
        self.assertNotEqual(old_write.returncode, 0)
        self.assertEqual(self.h.state_bytes(), before)
        current = self.h.direct(self.fx.direct_request(
            custody=successor["custody"], requested_scope=scope,
            authority=[allowed]),
            now=self.fx.tick())
        self.assertEqual(current["requirements"][0]["reason_code"],
                         "native_evaluation_required")
        blocked = self.h.direct(self.fx.direct_request(
            custody=successor["custody"], requested_scope=scope,
            authority=[rejected]), now=self.fx.tick())
        stored = self.h.state()["issues"]["151"]["delivery"]["authority_observations"]
        self.assertTrue({allowed["id"], rejected["id"]} <= {x["id"] for x in stored})
        self.assertEqual(self.fx.blocked_on(self.h.state(), 151), "human_gate")
        collector = self.h.direct(self.fx.resume_request(
            blocked, requested_scope=None), now=self.fx.tick())
        self.assertIsNone(collector["requested_scope"])
        accepted = self.h.checkpoint(self.fx.checkpoint(
            collector["custody"], delivery=[returned], requested_scope=None),
            now=self.fx.tick())
        self.assertEqual(accepted["accepted_observation_ids"], [returned["id"]])
        self.assertEqual(self.fx.current_authorized_effects(self.h.state(), 151), [])

    def test_nodo_arcwave_and_argus_simulations(self):
        nodo = self.fx.nodo_case(); action = self.h.direct(nodo.request, now=self.fx.t0)
        self.assertEqual((action["kind"], action["pending_stage_ids"]),
                         ("delivery_remainder", ["close", "remote", "worktree", "local"]))
        self.assertEqual(len(self.h.state()["issues"]["1314"]["attempts"]),
                         nodo.prior_attempts)
        self.assertEqual(self.h.finish(nodo.complete(action),
                                       now=self.fx.tick())["state"], "delivery_complete")

        arc = self.fx.arcwave_case(); action = self.h.direct(arc.request, now=self.fx.tick())
        self.assertEqual(action["pending_stage_ids"][0], "record")
        missing = self.h.checkpoint(arc.without_live_head(action), now=self.fx.tick())
        self.assertEqual((missing["requirements"][0]["reason_code"],
                          missing["state"], missing["blocked_on"], missing["next_action"]),
                         ("live_pr_head_required", "active", None, None))

        argus = self.fx.argus_case()
        exact = self.h.direct(argus.exact_private_request, now=self.fx.tick())
        self.assertEqual((exact["requested_scope"],
                          exact["requirements"][0]["reason_code"]),
                         (argus.private_scope, "native_evaluation_required"))
        provider = FakeProvider()
        for field in ("endpoint", "audience", "payload", "principal", "risk", "spend"):
            request = argus.stage_valid_uncovered_request(field)
            self.assertNotEqual(canonical_bytes(request),
                                canonical_bytes(argus.exact_private_request))
            refused = self.h.direct(request, now=self.fx.tick())
            self.assertEqual(refused["requirements"][0]["reason_code"],
                             "authorization_intent_required")
            self.assertEqual(self.fx.blocked_on(self.h.state(), 151), "human_gate")
            provider.perform_only_if_scope(
                self.h, refused, request["requested_scope"])
        self.h.assert_refused_without_write(
            "direct", argus.selected_output_conflict_request, now=self.fx.tick())
        self.assertEqual(provider.calls, [])
        current = self.h.direct(argus.exact_private_request, now=self.fx.tick())
        completed = self.h.checkpoint(argus.human_completion(current), now=self.fx.tick())
        self.assertIn(argus.rejection_id, json.dumps(self.h.state()))
        self.assertNotIn("agent_authorized", json.dumps(completed))

    def test_stall_count_and_progress_reset_are_exact(self):
        action = self.h.direct(self.fx.pending_remainder_request(), now=self.fx.t0)
        seen = [action["custody"]["action_id"]]
        for expected in (0, 1, 2, 3):
            parked = self.h.checkpoint(
                self.fx.transport_suspension(action["custody"]), now=self.fx.tick())
            self.assertEqual(self.fx.stalled_resumes(self.h.state(), 151), expected)
            if expected < 3:
                self.assertEqual((parked["kind"], parked["state"]),
                                 ("delivery_checkpointed", "suspended"))
                action = self.h.direct(self.fx.resume_request(parked), now=self.fx.tick())
                seen.append(action["custody"]["action_id"])
            else:
                self.assertEqual((parked["kind"], parked["state"],
                                  parked["stalled_resumes"], parked["result_source"]),
                                 ("delivery_stalled", "terminal_failed", 3, "stalled"))
        self.assertEqual(seen, ["151:r1:1", "151:r1:2", "151:r1:3", "151:r1:4"])
        self.assertEqual(self.fx.remainder_count(self.h.state(), 151), 1)
        self.assertNotEqual(self.h.direct(self.fx.resume_request(parked),
                                          now=self.fx.tick()).get("kind"),
                            "delivery_remainder")

        h = DeliveryHarness(self); action = h.direct(
            self.fx.pending_remainder_request(issue=152), now=self.fx.t0)
        for expected in (0, 1):
            parked = h.checkpoint(self.fx.transport_suspension(action["custody"]),
                                  now=self.fx.tick())
            self.assertEqual(self.fx.stalled_resumes(h.state(), 152), expected)
            action = h.direct(self.fx.resume_request(parked), now=self.fx.tick())
        progress = self.fx.observed_stage("close", custody=action["custody"])
        action = h.checkpoint(self.fx.checkpoint(
            action["custody"], delivery=[progress], requested_scope=None),
            now=self.fx.tick())
        self.assertEqual((self.fx.suspend_phase(h.state(), 152),
                          self.fx.stalled_resumes(h.state(), 152)), (None, 0))
        after_reset = []
        for expected in (0, 1, 2, 3):
            parked = h.checkpoint(self.fx.transport_suspension(action["custody"]),
                                  now=self.fx.tick())
            after_reset.append(self.fx.stalled_resumes(h.state(), 152))
            if expected < 3:
                action = h.direct(self.fx.resume_request(parked), now=self.fx.tick())
            else:
                self.assertEqual((parked["kind"], parked["state"]),
                                 ("delivery_stalled", "terminal_failed"))
        self.assertEqual(after_reset, [0, 1, 2, 3])

    def test_merge_is_persisted_before_independent_deadline_reaping(self):
        action = self.h.direct(self.fx.pending_merge_at_deadline(), now=self.fx.t0)
        custody = action["custody"]
        merge = self.fx.merge_observation(custody)
        self.assertTrue(self.h.current(custody)["current"])
        at_deadline = self.h.checkpoint(
            self.fx.checkpoint(custody, delivery=[merge]),
            now=action["deadline_at"],
        )
        self.assertIn(merge["id"], at_deadline["accepted_observation_ids"])
        self.assertTrue(self.fx.contains_observation(self.h.state()["issues"]["151"], merge["id"]))
        self.assertEqual(self.fx.remainder_count(self.h.state(), 151), 1)

    def test_remainder_retry_admission_resume_and_cap(self):
        first = self.h.direct(self.fx.failed_delivery_request(effect_absent=True),
                              now=self.fx.t0)
        active = self.h.direct(self.fx.retry_request(first), now=self.fx.tick())
        self.assertEqual(active["custody"]["remainder"], 1)
        parked = self.h.checkpoint(self.fx.transport_suspension(active["custody"]),
                                   now=self.fx.tick())
        resumed = self.h.direct(self.fx.resume_request(parked), now=self.fx.tick())
        self.assertEqual(resumed["custody"]["remainder"], 1)
        custody_only = self.h.finish(self.fx.failed_summary(resumed), now=self.fx.tick())
        self.assertEqual((custody_only["kind"], custody_only["requested_scope"]),
                         ("delivery_remainder", None))
        self.assertEqual(custody_only["requirements"][0]["reason_code"],
                         "scope_tuple_required")
        provider = FakeProvider(); provider.perform_only_if_scope(
            self.h, custody_only, requested_scope=None)
        self.assertEqual(provider.calls, [])
        next_scope = self.fx.requested_scope(custody_only["pending_stage_ids"][0])
        admitted = self.h.direct(self.fx.retry_request(
            custody_only, requested_scope=next_scope),
            now=self.fx.tick())
        self.assertEqual(admitted["requested_scope"], next_scope)
        provider.perform_only_if_scope(self.h, admitted, next_scope)
        self.assertEqual(provider.calls, [custody_only["pending_stage_ids"][0]])

        for issue, variant in ((152, "missing_recovery_basis"),
                               (153, "nonretryable")):
            prior = self.h.direct(self.fx.failed_delivery_request(
                issue=issue, effect_absent=True), now=self.fx.tick())
            self.assertEqual(self.h.finish(self.fx.failed_summary(prior),
                                           now=self.fx.tick())["state"],
                             "terminal_failed")
            refused = self.h.direct(self.fx.retry_request(prior, variant=variant),
                                    now=self.fx.tick())
            self.assertNotEqual(refused.get("kind"), "delivery_remainder")
            self.assertEqual(self.fx.remainder_count(self.h.state(), issue), 1)

        prior = self.h.direct(self.fx.failed_delivery_request(
            issue=154, effect_absent=True), now=self.fx.tick())
        for expected in (2, 3):
            self.h.finish(self.fx.failed_summary(prior), now=self.fx.tick())
            candidate = self.h.direct(self.fx.retry_request(
                prior, variant="new_recovery_basis"), now=self.fx.tick())
            if expected == 2:
                self.assertEqual(candidate["custody"]["remainder"], 2)
                prior = candidate
            else:
                self.assertNotEqual(candidate.get("kind"), "delivery_remainder")
        self.assertEqual(self.fx.remainder_count(self.h.state(), 154), 2)

    def test_source_and_installed_cli_load_one_model_and_fail_closed(self):
        source = self.h.round_trip_with_layout("source")
        installed = self.h.round_trip_with_layout("installed")
        self.assertEqual(source.semantic_result, installed.semantic_result)
        for mutation in ("missing", "directory", "wrong_interface"):
            run = self.h.round_trip_with_layout("installed", model_mutation=mutation, ok=False)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(run.ledger_after, run.ledger_before)
```

Implement named harness methods before the class with `subprocess.run`, temp
reports and raw validation before decode. `DeliveryFixtures` holds strict,
model-validated literals; `FakeProvider` has one
`calls` list. Do not replace CLI tests with
monkeypatches of workflow-state internals. Installed round trips use temp HOME and
lexical wrapper/library symlinks to fake-store files; negatives
replace only the model leaf with missing/directory/wrong-interface cases.
Clone the after-merge/pending-integration fixture through genuine failure: finish
returns custody-only remainder with null scope and exact
`implementation_delivered/postcondition_observation_required`; any nonnull fresh
proposal refuses because no effect stage is ready.

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
    for response in workflow_response_fixtures():
        accepted = self.run_validate("workflow-response", response, use_stdin=True)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(accepted.stdout, canonical_bytes(response))
        if response.get("kind") in {"owner", "delivery_remainder",
                                    "delivery_checkpointed"}:
            self.assertIn("requested_scope", response)
    mutations = delivery_boundary_mutations(valid)
    self.assertEqual(set(mutations), {
        "unknown_key", "legacy_new_hybrid", "changed_contract_digest",
        "action_id_mismatch", "missing_postcondition_evidence",
        "invalid_host_reference_type",
        "unsuccessful_absence_probe", "bool_ordinal", "duplicate_observation",
        "revocation_subject_mismatch", "duplicate_consumption_use_key",
        "permit_consumption_mismatch", "bootstrap_custody_mismatch",
        "control_summary_attempt_hybrid", "control_delta_attempt_hybrid",
        "nested_action_extra_key", "observe_requirement_hybrid",
        "control_summary_invalid_legacy_result", "terminal_invalid_legacy_result",
        "ship_summary_invalid_historical_owner_result",
        "remainder_missing_evaluation", "checkpoint_nested_requirement",
        "complete_with_pending_stage", "failed_wrong_reason",
        "stalled_response_extra_action", "duplicate_json_key", "invalid_utf8",
        "requested_scope_missing", "checkpoint_scope_action_mismatch",
        "handoff_scope_hybrid",
    })
    for name, boundary, raw in mutations.values():
        with self.subTest(name=name):
            refused = self.run_validate_raw(boundary, raw)
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(refused.stdout, b"")
```

Fixtures cover every report/response and scope echo under one contract/custody.
Mutations recompute enclosing hashes except raw duplicate-key/UTF-8. Legacy v1 is
historical-only. Semantic tests pass shaped stale/scope/host claims through
structure to locked refusal/no-authority behavior.

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
        "workflow-response", "workflow_bootstrap", "bootstrap requirements",
        "checkpoint-delivery", "delivery_remainder", "requested_scope",
        "bind the actual invocation",
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
                   "implementation_delivered", "pr_merged", "actual scope",
                   "fresh proposal"):
        self.assertIn(phrase, text)
```

Use a closed role mapping; evals carry complete input and typed response.

- [ ] **Step 3: Run the new tests and observe RED**

```bash
python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py \
  -k requested_scope -v
python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py \
  -k test_schema_one_migrates_through_two_to_three_with_one_atomic_write -v
python3 -m unittest home/common/agent-skills/tests/test_artifact_budget.py \
  -k test_delivery_v2_boundaries_accept_exact_shapes_and_reject_hybrids -v
python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -v
python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  -k delivery_interface_two -v
```

Expected: nonzero because D19, schema/interface v3/v2, new boundaries and callers
are absent. Preserve output and fix malformed fixtures before implementation.

- [ ] **Step 4: Implement schema 3 and the atomic runtime cutover**

Before request/ledger decode, load source `scripts/delivery_model/__init__.py` or
installed lexical `~/.agents/lib/python/delivery_model/__init__.py` as a package
with parent search location; require v1 and remove partial modules on failure.
Never search/edit `sys.path`, load private leaves or fall back. Missing/non-file/
wrong-version input refuses; a managed directory symlink is valid.

Replace the one-step `PRIOR_SCHEMA_VERSION` assumption with explicit adjacent
migrators:

```python
MIGRATORS = {1: migrate_1_to_2, 2: migrate_2_to_3}

def upgrade_state(value, *, run_id, migration_contracts):
    candidate = copy.deepcopy(value)
    seen = set()
    while isinstance(candidate, dict) and candidate.get("schema_version") != 3:
        version = candidate.get("schema_version")
        if type(version) is not int or version in seen or version not in MIGRATORS:
            raise WorkflowError("unsupported workflow state schema version")
        seen.add(version)
        candidate = MIGRATORS[version](candidate, migration_contracts)
    return validate_state(candidate, run_id=run_id)
```

1→2 retains suspension/`prior_run`; 2→3 adds only empty delivery/remainders.
Request `migration_contracts` may be null only for empty delivery; candidate
facts/remainder require one match, never legacy inference. Upgrade a detached
copy and write only validated v3; bad context preserves bytes.

Mutations upgrade under lock. Lock-free/no-write current-launch calls
`validate_legacy_state(value, run_id=run_id)` for 1/2 or `validate_state(...,
run_id=run_id)` for 3 and projects legacy implementation custody. Normalize
control/direct to one issue-keyed transition: validate objects/digests before
lock, then reload, validate custody, fold/reduce and return typed output. Only
trusted control/direct appends intent.

Without changing the facade, `_objects.py` keeps the sole stage/effect/target
relationship; `_reconcile.py` folds, selects the ordered ready stage and applies
D19 before existing intent/native/D18 reduction. Null-ready returns its local
requirement; wrong/dependency/completed scope rejects before write. `_wire.py`
requires/correlates request and effect-response scope, keeps handoff historical,
and excludes terminal/stalled scope. Workflow-state renders only the reducer's
canonical scope.

For checkpoint/finish, capture regular raw report bytes, run artifact-budget
before decode, then lock and compare issue/run/contract/custody. Atomically
persist before canonical output. Reduce observations/progress before deadline/
stall/retry; only count-3 stalls. Requirements/partial success never fail. Resume
in place; remainder 2 needs failure+absent effect+recovery; refuse 3 and preserve
implementation retry/capacity.

- [ ] **Step 5: Implement report validation and all production callers**

Add `ship-checkpoint`/`workflow-response` v2 dispatch. Capture raw bytes; reject
duplicate keys/invalid UTF-8; model-validate exact outer/nested shapes; emit
canonical bytes without copying schemas. Legacy v1 summary is historical-only;
hybrids/v1 schema-3 finish refuse. Each nonnull control/direct `result` or
`historical_owner_result` must pass legacy then model validation before decode.
The response union covers all accepted outcomes. Validate bootstrap, consume all
custody requirements, then construct control. Structural checks grant nothing.

Update from-issue, AUTO, its ship handoff, ship-issue, REVIEW, HUMAN-GATE, and
orchestration together. Their normative sequence is:

1. validate raw init/direct/control/current/checkpoint/finish responses through
   `workflow-response`, and handoff/checkpoint/summary reports through named
   boundaries, before decoding; consume bootstrap requirements before control;
2. copy the exact contract, intent chain, digests, custody and pending stages;
3. construct actual scope from command/provider/audience/endpoint/data/principal/
   risk/spend, never intent; require it to equal the validated response echo;
4. execute only the returned closed action after response validation and a
   `current-launch` exact four-key current result; an authority evaluation action
   thereby runs only after its consumption transaction committed;
   ordinary covered scope may native-evaluate and execute in this invocation;
5. recheck current launch before submitting the returned observation;
6. submit `ship-checkpoint/v2` immediately for partial progress or blocking
   authority/provider results and wait for persisted response;
7. use `ship-summary/v2` only for all required postconditions or genuine custody
   failure; retain selected-output/delivered acceptance, review and test
   references by category; and
8. follow the returned typed implementation/remainder/requirement outcome without
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
  receipt_exit=$?
  set -e
  printf '%s\n' "$receipt_exit" >"$receipt"
  return "$receipt_exit"
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
python3 - <<'PY'
from pathlib import Path
root = Path("/private/tmp/issue-151-skill-validation-env")
config = root / "devenv.nix"
expected = """{ pkgs, ... }:
{
  packages = [ pkgs.python3Packages.pyyaml ];
}
"""
root.mkdir(parents=True, exist_ok=True)
if not config.exists(): config.write_text(expected, encoding="utf-8")
assert config.read_text(encoding="utf-8") == expected
PY
task_root=$PWD
(
  cd /private/tmp/issue-151-skill-validation-env
  for skill in home/common/agent-skills/skills/{from-issue,ship-issue} \
               home/common/claude-code/skills/orchestrate-issues; do
    devenv shell -- python3 \
      /Users/anis/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
      "$task_root/$skill"
  done
)
```

Expected: each command exits 0, each receipt is `0`, and all skills print `Skill
is valid!`. The wrapper records real status before fail-fast propagation; CLI
tests remain the behavioral evidence.

Then prove exact scope and per-file diff size:

```bash
set -euo pipefail
task_paths=(
  home/common/agent-skills/scripts/delivery_model/{_objects,_reconcile,_wire}.py
  home/common/agent-skills/scripts/{workflow-state,artifact_budget}.py
  home/common/agent-skills/tests/{_delivery_model_fixtures,test_delivery_model,test_workflow_state,test_artifact_budget,test_delivery_workflow,test_workflow_skill_contracts}.py
  home/common/agent-skills/skills/from-issue/{SKILL.md,AUTO.md,ship-handoff.md}
  home/common/agent-skills/skills/ship-issue/{SKILL.md,REVIEW.md,HUMAN-GATE.md}
  home/common/claude-code/skills/orchestrate-issues/{SKILL.md,evals/evals.json}
  justfile
)
git diff --check -- "${task_paths[@]}"
test -z "$(git diff --cached --name-only)"
candidate_index=$(mktemp "${TMPDIR:-/tmp}/issue-151-task2-index-XXXXXX")
rm "$candidate_index"
trap 'rm -f "$candidate_index"' EXIT HUP INT TERM
GIT_INDEX_FILE="$candidate_index" git read-tree HEAD
GIT_INDEX_FILE="$candidate_index" git add -- "${task_paths[@]}"
GIT_INDEX_FILE="$candidate_index" git diff --cached --check
GIT_INDEX_FILE="$candidate_index" python3 - "${task_paths[@]}" <<'PY'
import os, subprocess, sys
allowed = set(sys.argv[1:])
records = subprocess.check_output(
    ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"]
).split(b"\0")
working = {record[3:].decode() for record in records if record}
env = {**os.environ, "GIT_INDEX_FILE": os.environ["GIT_INDEX_FILE"]}
candidate = set(subprocess.check_output(
    ["git", "diff", "--cached", "--name-only", "--"], env=env
).decode().splitlines())
assert working == allowed, (working, allowed)
assert candidate == allowed, (candidate, allowed)
for path in sorted(allowed):
    diff = subprocess.check_output(
        ["git", "diff", "--cached", "--unified=10", "--", path], env=env)
    assert 0 < len(diff) <= 65_536, (path, len(diff))
PY
rm -f "$candidate_index"
trap - EXIT HUP INT TERM
test -z "$(git diff --cached --name-only)"
```

Expected: exit 0; the temporary index includes all 20 Task 2 paths, each U10
diff is 1..65,536 bytes, and the real index remains empty. If a bounded test split
is needed, amend Files, the root index, `task_paths`/commit roster and `justfile`
registration; never omit lines/assertions, split a patch synthetically or raise a
cap. The signed-head package from immutable Task 2 base remains authoritative.

- [ ] **Step 7: Commit the atomic adoption and produce complete review evidence**

```bash
set -euo pipefail
task_paths=(
  home/common/agent-skills/scripts/delivery_model/{_objects,_reconcile,_wire}.py
  home/common/agent-skills/scripts/{workflow-state,artifact_budget}.py
  home/common/agent-skills/tests/{_delivery_model_fixtures,test_delivery_model,test_workflow_state,test_artifact_budget,test_delivery_workflow,test_workflow_skill_contracts}.py
  home/common/agent-skills/skills/from-issue/{SKILL.md,AUTO.md,ship-handoff.md}
  home/common/agent-skills/skills/ship-issue/{SKILL.md,REVIEW.md,HUMAN-GATE.md}
  home/common/claude-code/skills/orchestrate-issues/{SKILL.md,evals/evals.json}
  justfile
)
git add -- "${task_paths[@]}"
test -z "$(git diff --name-only)"
git diff --cached --check
git commit -S -m "feat: reconcile delivery lifecycle" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```

Expected: signed commit succeeds. Validate the complete original-Task-2-base
range, not a final fix only. After independent Task 2 conformance/quality, gate a
fresh full `4cd9408c4e538d6c9f0b9941e43d05d43a77c9a8..HEAD` package. Distinct final
conformance/correctness cover the product spec, both tasks, D14, real receipts and
root bridge evidence without presenting that evidence as shipped code/tests.
