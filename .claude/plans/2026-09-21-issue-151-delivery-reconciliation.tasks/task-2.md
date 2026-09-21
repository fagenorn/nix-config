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
- Workflow-state writes schema 3: legacy issue/attempts/outcome plus delivery and
  independently capped remainders. Mutation-only `upgrade_state(value, *,
  run_id, migration_contracts)` composes valid 1→2→3 in memory, calls
  `validate_state(candidate, *, run_id)`, then writes at most once. Current-launch
  validates legacy reads separately without lock/upgrade/write.
- Control v2 retains all v1 top-level keys, replaces only nested `owners`, and
  adds issue-keyed maps `forge`, `delivery_contracts`, `authorization_intents`,
  `authority_observations`, `reevaluation_evidence`, `delivery_observations`.
  Each map has exactly canonical decimal keys for requested issues. Forge values
  are existing forge objects; contracts are strict object|null; other values are
  explicit sorted unique named-object arrays (`[]` when empty). Missing/extra/`01`, or null contract
  with candidate facts, refuses before lock. Direct retains v1 keys plus nullable
  `delivery_contract` and sorted unique `authorization_intents`,
  `authority_observations`, `reevaluation_evidence`, `delivery_observations`.
  Owner value is exact event_id/issue/custody/state=`unavailable`;
  duplicate event or `(issue,kind,ordinal,launch)` refuses. Historical custody
  has no current effect; hybrid/unknown/mismatch refuses; remainder never
  fabricates attempt.
- Control outer output retains exact v1 keys and no ledger root. Summary replaces
  `attempt` with nullable custody, retains all other v1 fields, and adds nullable
  contract digest, ordered pending stages and sorted requirements; it therefore
  carries a `delivery_contract` requirement even when no action exists. Delta is
  exact issue/custody/kind/state with nullable custody. Wait/finalize stay exact.
  Spawn/resume/retry retain v1 fields and add custody, contract/digest, pending
  stages, requirements and nullable evaluation. Direct owner retains v1 fields
  and adds the same block. Direct observe admits the four exact acquisition
  requirements and four strict delivery requirements. Terminal retains v1.
- `delivery_remainder` has the design's exact fields plus nullable
  `authority_evaluation`. All nested response members validate through Task 1;
  callers never derive a stage from tracker/forge state.
- `checkpoint-delivery` validates ship-checkpoint bytes before decode/lock.
  Ordinary `delivery_checkpointed` is active|suspended and nonterminal. Fourth
  unchanged suspension stores 3 and returns exact terminal `delivery_stalled`
  without next action/requirements/evaluation/block. Evaluation actions appear
  only after consumption.
- Replaces the source finish entry with
  `finish --repo-root ROOT --run-id RUN --now UTC --summary-file FILE`.
  `ship-summary/v2` carries issue and custody, so separate issue/attempt guessing
  is absent. Under lock it rechecks the same action, persists final facts/result,
  then emits the exact common identity/accepted/pending envelope. Complete has
  kind/state `delivery_complete` and no pending stage. Genuine failure adds
  `result_source: owner` and `reason_code: owner_reported_failure` with kind/state
  `terminal_failed`; stall stays `delivery_stalled`; eligible retry returns
  `delivery_remainder`. Requirements and partial progress are never failure.
- `artifact_budget.py` adds `ship-checkpoint` and `workflow-response` to the closed boundary set and
  validates `ship-handoff/v2`, `ship-checkpoint/v2`, and `ship-summary/v2` by
  loading Task 1's model. `workflow-response` validates raw control/direct,
  current-launch, bootstrap, checkpoint and finish responses before decode.
  `workflow_bootstrap` v2 has exact interface/kind/run/requirements keys; each
  sorted requirement has issue, owner, custody and recorded worktree. It selects
  the nonterminal custody, else latest remainder, else latest implementation.
  Callers consume every requirement into normalized owner/worktree observations
  before control. Legacy v1 summary remains historical-read-only.
- Callers consume validated v2 actions and fence effects; linked model/handoff
  docs own shared contracts.

**Invariants:**
- Per D8/D14, schema-1 and schema-2 migrations preserve every legacy attempt,
  outcome, result byte and detail pointer. They initialize empty delivery truth
  only: no contract, intent, authority, observation, selected output, stage fact,
  postcondition success, remainder or cleanup claim.
- Migration is idempotent/fail-closed; malformed, ambiguous or model-load/version
  failures leave original ledger bytes unchanged.
- `migration_contracts` comes only from structurally validated interface-2
  delivery contracts in the request. Empty legacy delivery may use null; any
  candidate delivery/authority fact or remainder dispatch requires one matching
  contract. Missing, conflicting or repository-mismatched context refuses with
  no write. A read-only launch query over schema 1/2 returns its exact four-key
  result and leaves bytes and filesystem inventory unchanged.
- Per D3/D18, every effect path performs current-launch before the effect and
  again before writing its observation. A stale caller writes nothing. A current
  direct/control collector may persist a late authority fact under its original
  launch; old allowed facts cannot authorize current effects, and old rejections
  remain operative. Checkpoint/summary remain fenced to their own custody.
- A post-rejection evaluation action is emitted only by the transaction that
  first persists its stable consumption use key. Retry, transfer or crash after
  persistence returns no second action. Covering successor intent and bound
  reevaluation evidence are separate bases; ordinary authorized actions do not
  manufacture a new-permission requirement.
- Checkpoint deduplicates facts and ordinary blockers suspend nonterminally;
  only unchanged-progress count 3 terminalizes and returns `delivery_stalled`.
- Remainder action ids are `issue:r<remainder>:launch`; implementation ids remain
  `issue:attempt:launch`. Resume keeps ordinal/deadline and increments neither
  retry count. A genuine failed remainder with absent effect and valid recovery
  basis may allocate at most the second ordinal.
- Merge observation is folded before expiry. Successive same-token suspensions
  persist counters 0, 1, 2, then 3; the first three may resume and 3 terminalizes
  as stalled. Accepted stage/postcondition progress clears phase and resets 0. Capacity ordering and
  existing implementation retry behavior remain intact.
- This is one source-only atomic cutover: no activation, external effect,
  mixed schema/caller/report midpoint or duplicate model validation. Artifact
  validation proves structure/ids only; locked checks decide live authority.

- [ ] **Step 1: Write migration and public delivery-round-trip tests**

Update `test_workflow_state.py` fixtures for interface 2 and exact custody refs;
retain every lifecycle test. Add a schema-1 terminal-plus-active fixture and
exercise public control with a validated issue-151 migration contract. Assert
schema 3, byte-equivalent legacy results, no invented delivery success or
evaluation consumption, interface 2 output, and a byte-identical second call.

Also add a pure migration test that calls
`upgrade_state(value, run_id=self.run_id, migration_contracts={151: contract})`
on the detached schema-1 value, asserts schema 3 and unchanged input, then calls
`validate_state(result, run_id=self.run_id)` explicitly. Patch
`atomic_write_state` only in a focused transaction test and assert it is called
once with a schema-3 value; there must be no call whose value is schema 2.

Add a focused transaction test that patches `atomic_write_state` to fail on a
new evaluation consumption, asserts response rendering is never called and state
bytes remain unchanged, then reruns unpatched and observes exactly one action.

Add two public no-write regressions. A schema-2 request that carries candidate
delivery/authority facts without a contract, and one whose contract repository
does not match those facts, both exit nonzero and preserve exact ledger bytes.
Separately, write a valid schema-1 active attempt, call `current-launch` with its
implementation action id, and assert exit 0, the exact four-key current result,
byte-identical ledger and unchanged whole temporary-root inventory. A remainder
id against that legacy ledger likewise returns exit 0/current false without a
write. These public assertions supplement the pure migration unit; neither is
replaced by mocking.

Create `test_delivery_workflow.py` with strict synthetic fixtures and one CLI
`DeliveryHarness`. `known_unavailability` emits a fact only from an explicit
fixture fact, never from bootstrap presence; its event ids are nonempty/stable.
`owner_observation_case` constructs exact malformed/duplicate/historical cases.
Its methods are `init(*, schema_fixture=None)`, `control`, `direct`, `current`,
`checkpoint`, `finish`, `state_bytes`, and `state`, with the argument signatures
shown by their calls below. Every successful stdout, including `init`, passes raw
through `workflow-response` before decode; init returns the strict bootstrap.
Report inputs use named boundaries before workflow-state; errors are not decoded.

```python
class DeliveryWorkflowRoundTripTest(unittest.TestCase):
    def setUp(self):
        self.h = DeliveryHarness(self)
        self.fx = DeliveryFixtures()
        self.bootstrap = self.h.init()
        self.assertEqual(self.bootstrap["requirements"], [])

    def test_bootstrap_requirements_cover_both_custody_kinds(self):
        for kind in ("implementation", "remainder"):
            h = DeliveryHarness(self)
            boot = h.init(schema_fixture=self.fx.active_custody_state(kind))
            requirement = boot["requirements"][0]
            self.assertEqual(self.fx.control_from_bootstrap(boot, unavailable=[])["owners"], [])
            fact = self.fx.known_unavailability(requirement)
            request = self.fx.control_from_bootstrap(boot, unavailable=[fact])
            self.assertEqual(request["owners"][0]["custody"]["action_id"],
                             requirement["custody"]["action_id"])
            self.assertTrue(request["worktrees"])
            h.control(request, now=self.fx.t0)

    def test_control_envelope_and_owner_observation_refusals(self):
        for variant in ("missing_map_issue", "extra_map_issue", "noncanonical_01",
                        "null_contract_with_facts", "hybrid", "unknown_custody",
                        "issue_action_mismatch", "duplicate_event_conflict",
                        "duplicate_custody"):
            with self.subTest(variant=variant):
                before = self.h.state_bytes()
                refused = self.h.control(self.fx.owner_observation_case(variant),
                                         now=self.fx.t0, ok=False)
                self.assertNotEqual(refused.returncode, 0)
                self.assertEqual(self.h.state_bytes(), before)
        historical = self.h.control(self.fx.owner_observation_case("known_historical"),
                                    now=self.fx.t0)
        self.assertTrue(self.fx.current_custody_remains_active(historical))

    def test_normal_v3_owner_merge_precedes_delivered_truth(self):
        owner = self.h.direct(self.fx.direct_request(), now=self.fx.t0)
        self.assertEqual(owner["kind"], "owner")
        self.assertEqual(owner["custody"]["kind"], "implementation")
        custody = owner["custody"]
        effects = FakeProvider()
        for stage in ("select", "publish", "open", "merge"):
            before_effect = self.h.current(custody)
            self.assertEqual(set(before_effect), {
                "action_id", "current", "current_action_id", "reason"
            })
            self.assertTrue(before_effect["current"])
            observation = effects.perform(owner, stage)
            before_write = self.h.current(custody)
            self.assertTrue(before_write["current"])
            self.assertEqual(before_write["action_id"], custody["action_id"])
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

    # Add one no-contract test: control summary has null custody/digest, empty
    # pending stages, one delivery_contract requirement and no issue action;
    # direct observe returns that same strict requirement.
    # Add one D18 test: persist denial and consumption; a later matching allow
    # with current intent advances the open stage, then a newer same-scope
    # rejection suspends on human_gate while the original denial remains.

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
        reevaluation = self.fx.reevaluation(denial)
        resumed = self.h.direct(
            self.fx.direct_request(reevaluation=[reevaluation]), now=self.fx.tick()
        )
        self.assertEqual(resumed["custody"]["attempt"], custody["attempt"])
        self.assertEqual(resumed["deadline_at"], owner["deadline_at"])
        permit = resumed["authority_evaluation"]
        self.assertEqual(permit["basis_id"], reevaluation["id"])
        persisted = self.h.state()["issues"]["151"]["delivery"]
        self.assertEqual(
            [item["use_key"] for item in persisted["authority_evaluation_consumptions"]],
            [permit["use_key"]],
        )
        replay = self.h.direct(
            self.fx.direct_request(reevaluation=[reevaluation]), now=self.fx.tick()
        )
        self.assertIsNone(replay["authority_evaluation"])
        self.assertEqual(len(
            self.h.state()["issues"]["151"]["delivery"]["authority_evaluation_consumptions"]
        ), 1)
        self.assertEqual(len(self.h.state()["issues"]["151"]["attempts"]), 1)
        self.assertTrue(self.fx.contains_observation(self.h.state()["issues"]["151"], denial["id"]))

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

    def test_effect_result_after_transfer_requires_current_collector(self):
        owner = self.h.direct(self.fx.direct_request(), now=self.fx.t0)
        old = owner["custody"]
        returned = self.fx.provider_result_for("publish", custody=old)
        successor = self.h.control(self.fx.transfer_request(old), now=self.fx.tick())["actions"][0]
        before = self.h.state_bytes()
        self.assertFalse(self.h.current(old)["current"])
        old_write = self.h.checkpoint(
            self.fx.checkpoint(old, delivery=[returned]), now=self.fx.tick(), ok=False
        )
        self.assertNotEqual(old_write.returncode, 0)
        self.assertEqual(self.h.state_bytes(), before)
        self.assertTrue(self.h.current(successor["custody"])["current"])
        accepted = self.h.checkpoint(
            self.fx.checkpoint(successor["custody"], delivery=[returned]), now=self.fx.tick()
        )
        self.assertEqual(accepted["accepted_observation_ids"], [returned["id"]])

    def test_successor_collects_late_authority_without_reusing_old_allow(self):
        owner = self.h.direct(self.fx.direct_request(), now=self.fx.t0)
        old = owner["custody"]
        allowed = self.fx.host_allowed("publish", custody=old)
        rejected = self.fx.host_rejection("open", custody=old)
        new = self.h.control(self.fx.transfer_request(old), now=self.fx.tick())["actions"][0]
        result = self.h.direct(self.fx.direct_request(
            custody=new["custody"], authority=[allowed, rejected]
        ), now=self.fx.tick())
        stored = self.h.state()["issues"]["151"]["delivery"]["authority_observations"]
        self.assertTrue({allowed["id"], rejected["id"]} <= {x["id"] for x in stored})
        self.assertEqual(result["blocked_on"], "human_gate")
        self.assertEqual(self.fx.current_authorized_effects(self.h.state(), 151), [])

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
        self.assertEqual(missing["state"], "active")
        self.assertIsNone(missing["blocked_on"])
        self.assertIsNone(missing["next_action"])

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

    def test_four_no_progress_suspensions_allow_exactly_three_resumes(self):
        action = self.h.direct(
            self.fx.failed_delivery_request(effect_absent=True), now=self.fx.t0
        )
        self.assertEqual(action["custody"]["remainder"], 1)
        seen = [action["custody"]["action_id"]]
        for suspension_number in range(1, 5):
            custody = action["custody"]
            self.assertTrue(self.h.current(custody)["current"])
            suspended = self.h.checkpoint(
                self.fx.transport_suspension(custody), now=self.fx.tick()
            )
            if suspension_number < 4:
                self.assertEqual((suspended["kind"], suspended["state"]),
                                 ("delivery_checkpointed", "suspended"))
                action = self.h.direct(self.fx.resume_request(suspended), now=self.fx.tick())
                seen.append(action["custody"]["action_id"])
            else:
                self.assertEqual((suspended["kind"], suspended["state"],
                                  suspended["stalled_resumes"], suspended["result_source"]),
                                 ("delivery_stalled", "terminal_failed", 3, "stalled"))
                self.assertEqual(suspended["reason_code"],
                                 "suspension_stalled_without_progress")
                refused = self.h.direct(self.fx.resume_request(suspended), now=self.fx.tick())
                self.assertNotEqual(refused["kind"], "delivery_remainder")
        self.assertEqual(seen, ["151:r1:1", "151:r1:2", "151:r1:3", "151:r1:4"])
        self.assertEqual(self.fx.remainder_count(self.h.state(), 151), 1)

    def test_progress_resets_stall_streak(self):
        action = self.h.direct(self.fx.pending_remainder_request(), now=self.fx.t0)
        for expected in (0, 1):
            parked = self.h.checkpoint(
                self.fx.transport_suspension(action["custody"]), now=self.fx.tick()
            )
            self.assertEqual(self.fx.stalled_resumes(self.h.state(), 151), expected)
            action = self.h.direct(self.fx.resume_request(parked), now=self.fx.tick())
        progress = self.fx.observed_stage("close", custody=action["custody"])
        action = self.h.checkpoint(
            self.fx.checkpoint(action["custody"], delivery=[progress]), now=self.fx.tick()
        )
        self.assertEqual((self.fx.suspend_phase(self.h.state(), 151),
                          self.fx.stalled_resumes(self.h.state(), 151)), (None, 0))
        seen = []
        for expected in (0, 1, 2, 3):
            parked = self.h.checkpoint(
                self.fx.transport_suspension(action["custody"]), now=self.fx.tick()
            )
            seen.append(self.fx.stalled_resumes(self.h.state(), 151))
            if expected < 3:
                action = self.h.direct(self.fx.resume_request(parked), now=self.fx.tick())
            else:
                self.assertEqual((parked["kind"], parked["state"]),
                                 ("delivery_stalled", "terminal_failed"))
        self.assertEqual(seen, [0, 1, 2, 3])
        self.assertEqual(self.fx.result_source(self.h.state(), 151), "stalled")

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

    def test_remainder_retry_requires_failure_recovery_and_retryability(self):
        first = self.h.direct(self.fx.failed_delivery_request(effect_absent=True), now=self.fx.t0)
        active = self.h.direct(self.fx.retry_request(first), now=self.fx.tick())
        self.assertEqual(active["custody"]["remainder"], 1)
        self.assertEqual(self.fx.remainder_count(self.h.state(), 151), 1)
        parked = self.h.checkpoint(
            self.fx.transport_suspension(first["custody"]), now=self.fx.tick()
        )
        resumed = self.h.direct(self.fx.resume_request(parked), now=self.fx.tick())
        self.assertEqual(resumed["custody"]["remainder"], 1)
        self.h.finish(self.fx.failed_summary(resumed), now=self.fx.tick())
        for issue, variant in ((152, "missing_recovery_basis"), (153, "nonretryable")):
            prior = self.h.direct(
                self.fx.failed_delivery_request(issue=issue, effect_absent=True),
                now=self.fx.tick(),
            )
            self.assertEqual(
                self.h.finish(self.fx.failed_summary(prior), now=self.fx.tick())["state"],
                "terminal_failed",
            )
            refused = self.h.direct(
                self.fx.retry_request(prior, variant=variant), now=self.fx.tick()
            )
            self.assertNotEqual(refused.get("kind"), "delivery_remainder")
            self.assertEqual(self.fx.remainder_count(self.h.state(), issue), 1)

    def test_remainder_retry_cap_stops_third_ordinal(self):
        first = self.h.direct(
            self.fx.failed_delivery_request(issue=154, effect_absent=True), now=self.fx.t0
        )
        self.h.finish(self.fx.failed_summary(first), now=self.fx.tick())
        second = self.h.direct(
            self.fx.retry_request(first, variant="new_recovery_basis"), now=self.fx.tick()
        )
        self.assertEqual(second["custody"]["remainder"], 2)
        self.h.finish(self.fx.failed_summary(second), now=self.fx.tick())
        third = self.h.direct(
            self.fx.retry_request(second, variant="new_recovery_basis"), now=self.fx.tick()
        )
        self.assertNotEqual(third.get("kind"), "delivery_remainder")
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

Implement every named harness method in this test file before the class using
`subprocess.run`, canonical temporary report files, and assertions that raw
stdout has validated before `json.loads`. `DeliveryFixtures` contains
the full strict literal constructors used by these tests and validates each
object through `delivery_model.validate_delivery_object`; `FakeProvider` has one
`calls` list and no network path. Do not replace these public CLI tests with
monkeypatches of workflow-state internals. `round_trip_with_layout("installed")`
uses an explicit temporary HOME with lexical wrapper/library symlinks to regular fake
store files. It never reads real HOME; negatives replace only the model leaf with
missing/directory/wrong-interface cases.

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
    })
    for name, boundary, raw in mutations.values():
        with self.subTest(name=name):
            refused = self.run_validate_raw(boundary, raw)
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(refused.stdout, b"")
```

Fixtures cover all reports, bootstrap/stalled/evaluation responses, revocation
and consumption under one contract/custody. Mutations recompute enclosing hashes;
duplicate-key/UTF-8 remain raw. Action mismatch is internally inconsistent, host
reference type is structural, and a shaped string grants nothing. Legacy v1
summary is readable only on its historical path and rejects v2 members.

Semantic tests send valid stale custody, audience/payload mismatch and shaped
host references past structure into locked refusal/no-authority behavior.

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

Use a closed role mapping; evals carry complete input and typed response.

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
`ship-checkpoint`/`workflow-response` are not report boundaries, and production
callers do not carry the v2 protocol. Preserve the terminal output. Fix test construction errors
before implementation; do not accept a RED caused by malformed fixtures.

- [ ] **Step 4: Implement schema 3 and the atomic runtime cutover**

Load the model before request or ledger. Select source
`scripts/delivery_model/__init__.py` or exactly installed lexical
`~/.agents/lib/python/delivery_model/__init__.py`. Build its package spec with
the parent search location, insert it for relative imports and require v1; on
failure remove it and loaded private members.
Never alter/search `sys.path`, load private files separately or fall back. Any
missing entry/private file, non-file entry or wrong version refuses before
decode/mutation. A managed directory symlink is valid.

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

`migrate_1_to_2` retains suspension defaults/`prior_run`; `migrate_2_to_3` adds
only empty delivery/remainders. Validated request `migration_contracts` is null
only for empty delivery and mandatory for candidate facts/remainders; never infer
it from legacy fields. Upgrade a detached copy and write only final validated v3.
Missing/ambiguous/mismatched context refuses with unchanged bytes.

Mutations upgrade under lock. `current-launch` reads without a lock, sends
schema 1/2 to `validate_legacy_state(value, run_id=run_id)` and schema 3 to
`validate_state(value, run_id=run_id)`, projects legacy implementation custody,
and never writes. Keep `run_id` keyword-only on every validation call.

Normalize control/direct to one issue-keyed transition. Validate objects/digests
before lock; under lock reload, validate custody, fold facts, reduce, and return
typed custody/requirement. Only trusted control/direct appends intent.

Implement `checkpoint-delivery` and the v2 finish entry exactly as **Interfaces**
states. Capture the report as regular raw bytes, invoke artifact-budget on those
bytes before JSON decode, then under lock compare issue/run/contract/custody to
ledger truth. Persist facts and suspension in one atomic replacement. Emit
canonical JSON only after persistence. Checkpoint terminalizes only count-3 anti-zombie stall via the exact
`delivery_stalled` response; finish never maps a requirement or partial success to `terminal_failed`.

Reduce in contract order: observations/progress precede deadline/stall/retry.
Resume in place; remainder 2 needs genuine failure, absent effect and recovery;
refuse a third. Retain implementation retry/capacity tests.

- [ ] **Step 5: Implement report validation and all production callers**

Add the `ship-checkpoint` and `workflow-response` boundaries and v2 dispatch in `artifact_budget.py`.
Capture raw bytes before decode, preserve duplicate-key and invalid-UTF-8
refusal, load the pure model, validate the outer boundary's exact keys and every
nested delivery object, then emit the accepted canonical bytes. Do not copy a
second object schema into artifact-budget. Keep strict legacy v1 summary reading
only for historical files; reject hybrids and do not let schema-3 finish consume
v1. Run the existing legacy validator before the shared model validator for
every nonnull control/direct `result` and `ship-summary/v2.historical_owner_result`;
both must accept before decode. The response union covers control/direct, current-launch,
`workflow_bootstrap`, ordinary/stalled checkpoint and finish outcomes. Validate
bootstrap before decode, consume all custody requirements into observations, then
construct control. The structural validator performs no ledger/authentication.

Update from-issue, AUTO, its ship handoff, ship-issue, REVIEW, HUMAN-GATE, and
orchestration together. Their normative sequence is:

1. validate raw init/direct/control/current/checkpoint/finish responses through
   `workflow-response`, and handoff/checkpoint/summary reports through named
   boundaries, before decoding; consume bootstrap requirements before control;
2. copy the exact contract, intent chain, digests, custody and pending stages;
3. execute only the returned closed action after response validation and a
   `current-launch` exact four-key current result; an authority evaluation action
   thereby runs only after its consumption transaction committed;
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
if config.exists():
    assert config.read_text(encoding="utf-8") == expected
else:
    config.write_text(expected, encoding="utf-8")
PY
task_root=$PWD
(
  cd /private/tmp/issue-151-skill-validation-env
  devenv shell -- python3 \
    /Users/anis/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
    "$task_root/home/common/agent-skills/skills/from-issue"
  devenv shell -- python3 \
    /Users/anis/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
    "$task_root/home/common/agent-skills/skills/ship-issue"
  devenv shell -- python3 \
    /Users/anis/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
    "$task_root/home/common/claude-code/skills/orchestrate-issues"
)
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
test -z "$(git diff --cached --name-only)"
python3 - <<'PY'
import subprocess

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
records = subprocess.check_output(
    ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"]
).split(b"\0")
changed = {record[3:].decode("utf-8") for record in records if record}
assert changed == allowed, (changed, allowed)
PY
candidate_index=$(mktemp "${TMPDIR:-/tmp}/issue-151-task2-index-XXXXXX")
rm "$candidate_index"
trap 'rm -f "$candidate_index"' EXIT HUP INT TERM
GIT_INDEX_FILE="$candidate_index" git read-tree HEAD
GIT_INDEX_FILE="$candidate_index" git add -- \
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
GIT_INDEX_FILE="$candidate_index" git diff --cached --check
GIT_INDEX_FILE="$candidate_index" python3 - <<'PY'
import os
import subprocess

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
env = {**os.environ, "GIT_INDEX_FILE": os.environ["GIT_INDEX_FILE"]}
candidate = set(subprocess.check_output(
    ["git", "diff", "--cached", "--name-only", "--"], env=env,
).decode().splitlines())
assert candidate == allowed, (candidate, allowed)
for path in sorted(allowed):
    diff = subprocess.check_output(
        ["git", "diff", "--cached", "--unified=10", "--", path], env=env,
    )
    assert 0 < len(diff) <= 65_536, (path, len(diff))
PY
rm -f "$candidate_index"
trap - EXIT HUP INT TERM
test -z "$(git diff --cached --name-only)"
```

Expected: exit 0; the temporary index includes all 15 Task 2 paths, including the
new untracked test, and each ordinary per-file U10 candidate diff is within
65,536 bytes without changing the real index. If a file requires a bounded test
split, stop and amend this member's Files roster, root task index, temporary-index
allowlist and `justfile` registration before adding it; do not omit lines, reduce
assertions, split one file's patch synthetically, or raise a cap. After the
signed commit, the actual package from the immutable Task 2 base through its
head remains the acceptance gate.

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
