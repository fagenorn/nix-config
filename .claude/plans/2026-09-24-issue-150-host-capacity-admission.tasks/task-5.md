# Task 5: Bounded launch refusal

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (blocking causes, refusal application, resume-lane gate)
- Modify: `home/common/agent-skills/scripts/workflow_delivery.py` (`validate_control_custody`, remainder blocker set, `suspend_remainder`)
- Modify: `home/common/agent-skills/scripts/workflow_delivery_wire.py` (`_owner`, `validate_control_observations`, `suspend_remainder`)
- Test: `home/common/agent-skills/tests/test_host_admission.py`, `home/common/agent-skills/tests/test_delivery_workflow.py`

**Interfaces:**
- Consumes (Tasks 3–4): `settle_admission`, `release_claim`, `parse_claim_holder`, control steps A–J, `AdmissionSweeps`, `T0`.
- Produces:
  - `BLOCKED_ON_VALUES` gains `host_capacity`; `OWNER_BLOCKED_ON_VALUES = BLOCKED_ON_VALUES - {"unknown", "host_capacity"}` (so `suspend --blocked-on host_capacity` is a usage error); `AUTO_RESUMABLE_BLOCKED_ON` gains `host_capacity`.
  - Owner observation `state` ∈ {`unavailable`, `launch_refused`}; `DeliveryProjection._owner` returns `(event_id, identity, state)`.
  - `DeliveryRuntime.validate_control_custody(state, request) -> tuple[set, set]` — `(unavailable, refused)` current-launch identities, each set filled from its own state; stale identities are dropped as today.
  - `DeliveryProjection.suspend_remainder(issue_state, remainder, now, *, blocked_on)` holding today's `suspend_expired_remainder` body with the cause as a parameter; `suspend_expired_remainder` calls it with `"unknown"`; `DeliveryRuntime.suspend_remainder` delegates. The remainder `blocked_on` set gains `host_capacity`.

**Invariants:**
- A refusal is applied only to an issue's current `active` launch whose `action_id` names a held claim, under a non-`direct` route; a current launch failing either test, or any refusal under `direct`, is a `WorkflowError` with no write (per D22).
- Applying a refusal suspends that custody at its current phase with `blocked_on: host_capacity` (attempt: `suspend_attempt`, writing the issue outcome when it returns `False`; remainder: `suspend_remainder`) before `settle_admission`, which releases the claim `launch_refused` — or `finished` at the anti-zombie bound (per D7, D19).
- The resume lane withholds a custody suspended on `host_capacity` — it joins `waiting` — until some other claim has a `release_seq` greater than that of the released `launch_refused` claim naming its current launch; a missing refused claim is an internal error.
- `unavailable` keeps its instant takeover, subject to admission (per D7).

- [ ] **Step 1: Write the failing tests**

Append to `T/test_host_admission.py`:

```python
class LaunchRefusalTest(AdmissionSweeps, unittest.TestCase):
    """D7, D22: a refused launch parks under host_capacity until another release."""

    def refused(self, issue, launch=1):
        fact = self.owner_fact(event_id=f"refused-{issue}-{launch}", issue=issue,
                               attempt=1, launch=launch)
        return {**fact, "state": "launch_refused"}

    @staticmethod
    def summary(response, issue):
        return next(s for s in response["summaries"] if s["issue"] == issue)

    def admitted_pair(self):
        self.slots(7)
        self.init_run()
        self.sweep(T0)  # 12 and 14 spawned

    def test_a_refusal_parks_the_launch_until_another_claim_is_released(self):
        self.admitted_pair()
        parked = self.sweep("2026-08-13T20:01:00Z", recorded=(12, 14),
                            owners=[self.refused(14)])
        self.assertEqual(self.kinds(parked), [("wait", None)])
        self.assertEqual((self.summary(parked, 14)["state"],
                          self.summary(parked, 14)["blocked_on"]),
                         ("suspended", "host_capacity"))
        self.assertEqual(parked["admission"]["waiting"], [14])
        refused = self.claims()["14:1:1"]
        self.assertEqual(refused["release_event"], "launch_refused")
        woken = self.sweep("2026-08-13T20:02:00Z", recorded=(12, 14))
        self.assertEqual((self.kinds(woken), woken["admission"]["waiting"]),
                         ([("wait", None)], [14]))
        self.suspend(issue=12, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:03:00Z")
        resumed = self.sweep("2026-08-13T20:04:00Z", recorded=(14,), unobserved=(12,))
        self.assertEqual(self.kinds(resumed), [("resume", 14), ("wait", None)])
        claims = self.claims()
        self.assertGreater(claims["12:1:1"]["release_seq"], refused["release_seq"])
        self.assertIsNone(claims["14:1:2"]["released_at"])

    def test_the_anti_zombie_bound_ends_a_launch_that_keeps_being_refused(self):
        self.admitted_pair()
        self.sweep("2026-08-13T20:01:00Z", recorded=(12, 14), owners=[self.refused(14)])
        state = self.read_state()
        state["issues"]["14"]["attempts"][0]["stalled_resumes"] = 2  # two resumes spent
        self.write_state(state)
        self.suspend(issue=12, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:02:00Z")
        self.sweep("2026-08-13T20:03:00Z", recorded=(14,), unobserved=(12,))  # 14:1:2
        final = self.sweep("2026-08-13T20:04:00Z", recorded=(14,), unobserved=(12,),
                           owners=[self.refused(14, launch=2)])
        self.assertEqual(self.summary(final, 14)["state"], "stopped")
        self.assertEqual(self.claims()["14:1:2"]["release_event"], "finished")
        self.assertFalse(any(a.get("issue") == 14 for a in final["actions"]))

    def test_inapplicable_refusals_write_nothing_and_stale_ones_are_ignored(self):
        self.admitted_pair()
        self.sweep("2026-08-13T20:01:00Z", recorded=(12, 14), owners=[self.refused(14)])
        before = self.state_path.read_bytes()
        again = {**self.refused(14), "event_id": "refused-again"}
        rejected = self.sweep("2026-08-13T20:02:00Z", recorded=(12, 14), owners=[again],
                              ok=False)
        self.assertEqual((rejected.returncode, self.state_path.read_bytes()), (2, before))
        dead = self.owner_fact(event_id="12-dead", issue=12, attempt=1, launch=1)
        self.sweep("2026-08-13T20:03:00Z", recorded=(12, 14), owners=[dead])  # 12:1:2
        stale = self.sweep("2026-08-13T20:04:00Z", recorded=(12, 14),
                           owners=[self.refused(12)])
        self.assertEqual(self.summary(stale, 12)["state"], "active")
        self.assertIsNone(self.claims()["12:1:2"]["released_at"])

    def test_direct_runs_and_owners_cannot_report_host_capacity(self):
        install_declaration(self.home, None)
        self.init_run()
        self.sweep(T0, issues=(12,), host_route="direct", max_parallel=1)
        before = self.state_path.read_bytes()
        refused = self.sweep("2026-08-13T20:01:00Z", issues=(12,), recorded=(12,),
                             host_route="direct", max_parallel=1,
                             owners=[self.refused(12)], ok=False)
        self.assertEqual((refused.returncode, self.state_path.read_bytes()), (2, before))
        usage = self.suspend(issue=12, attempt=1, blocked_on="host_capacity",
                             now="2026-08-13T20:02:00Z", ok=False)
        self.assertEqual((usage.returncode, self.state_path.read_bytes()), (2, before))
```

Add to `DeliveryAdmissionTest` in `T/test_delivery_workflow.py` (it follows
`test_control_resumes_remainder_without_spending_implementation_attempt` under the
`claude-code` route, then refuses the resumed remainder launch):

```python
    def test_a_refused_remainder_launch_parks_under_host_capacity(self):
        contract, delivery, actual = contract_and_delivery_for_stage(self.model, "publish")
        digest = self.model.canonical_digest(contract)
        home = make_home()
        self.addCleanup(shutil.rmtree, home, True)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); worktree = str(root / "worktree"); run_id = "refusal"
            def invoke(*args, stdin=None):
                completed = subprocess.run(
                    [sys.executable, str(WORKFLOW), *map(str, args)],
                    input=None if stdin is None else json.dumps(stdin).encode(),
                    capture_output=True, check=False,
                    env={**os.environ, "HOME": str(home)})
                self.assertEqual(completed.returncode, 0, completed.stderr)
                return json.loads(completed.stdout)
            run = ("--repo-root", root, "--run-id", run_id)
            def control(now, tracker, *, recorded, owners=()):
                request = self.control_request(contract)
                request.update(host_route="claude-code", now=now, owners=list(owners),
                    tracker=[{"issue": 151, "state": tracker, "open_blockers": [],
                              "decision_blockers": []}],
                    worktrees=[{"issue": 151,
                        "recorded": {"path": worktree, "state": "matching_issue_branch"}
                        if recorded else None,
                        "candidate": None if recorded else {"path": worktree,
                                                            "state": "absent"}}])
                request["authorization_intents"]["151"] = delivery["authorization_intents"]
                return invoke("control", *run, "--request-file", "-", stdin=request)
            invoke("init-run", *run, "--now", NOW)
            owner = control(NOW, "open", recorded=False)["actions"][0]
            failed = self.failed_summary(owner["custody"], digest)
            failed["delivery_observations"] = [observation(
                self.model, contract, "selected_output",
                {"selected_output": selection(self.model, digest)})]
            remainder = invoke("finish", *run, "--summary-file", "-",
                               "--now", "2026-09-21T00:00:01Z", stdin=failed)
            denial = authority(self.model, contract, actual, remainder["custody"])
            denial["observed_at"] = "2026-09-21T00:00:02Z"; seal(self.model, denial)
            checkpoint = self.report_common(remainder["custody"], digest)
            checkpoint.update(authority_observations=[denial], requested_scope=actual)
            invoke("checkpoint-delivery", *run, "--checkpoint-file", "-",
                   "--now", "2026-09-21T00:00:02Z", stdin=checkpoint)
            action = next(item for item in control(
                "2026-09-21T00:00:03Z", "closed", recorded=True)["actions"]
                if item["kind"] == "delivery_remainder")
            response = control("2026-09-21T00:00:04Z", "closed", recorded=True, owners=[{
                "event_id": "refused-r1", "issue": 151, "custody": action["custody"],
                "state": "launch_refused"}])
            self.assertFalse(any(item["kind"] == "delivery_remainder"
                                 for item in response["actions"]))
            self.assertEqual(response["admission"]["waiting"], [151])
            state = json.loads((root / f".superpowers/workflows/{run_id}/state.json")
                               .read_text())
            record = state["issues"]["151"]["delivery_remainders"][0]
            self.assertEqual((record["state"], record["blocked_on"]),
                             ("suspended", "host_capacity"))
            claims = {c["holder"]: c for c in state["admission"]["claims"]}
            self.assertEqual(claims[action["custody"]["action_id"]]["release_event"],
                             "launch_refused")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_host_admission.py home/common/agent-skills/tests/test_delivery_workflow.py 2>&1 | tail -4`
Expected: FAIL — `invalid owner state` (exit 2) for every `launch_refused` observation.

- [ ] **Step 3: Implement**

The Produces and Invariants above. In `command_control`, apply refusals in step A′ — after binding (Task 4 step A), before step B's `settle_admission` — in sorted identity order, mutating `state` directly; this counts as a change. In the resume lane, the gate check precedes Task 4's slot check. The `host_capacity` docstring comment beside `BLOCKED_ON_VALUES` says it is written only by control from a `launch_refused` observation, is auto-resumable, and resumes only after another claim's later release (per D7).

- [ ] **Step 4: Verify**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_host_admission.py 2>&1 | tail -3`
Expected: `OK`.

Run: `just agent-workflow-tests 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/scripts/workflow_delivery.py \
  home/common/agent-skills/scripts/workflow_delivery_wire.py home/common/agent-skills/tests/test_host_admission.py \
  home/common/agent-skills/tests/test_delivery_workflow.py
git commit -m "feat(workflow-state): park refused owner launches until another claim releases (#150)"
```
