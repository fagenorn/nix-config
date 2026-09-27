# Task 4: Control interface 3 — route binding, admission and the capacity report

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`validate_control_request`, `command_control`)
- Modify: `home/common/agent-skills/scripts/workflow_delivery.py` (`live_launches`)
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py` (`_control_response`)
- Modify: `home/common/agent-skills/tests/test_workflow_state.py` (`LifecycleHarness` HOME fixture and interface-3 helpers)
- Modify: `home/common/agent-skills/tests/test_delivery_workflow.py`, `home/common/agent-skills/tests/_delivery_model_fixtures.py`, `home/common/agent-skills/tests/test_delivery_model.py` (interface-3 requests and responses; `test_artifact_budget.py` reads the same fixture unchanged)
- Test: `home/common/agent-skills/tests/test_host_admission.py`

**Interfaces:**
- Consumes (Tasks 1, 3): `route_verdict`, library constants, `parse_claim_holder`, `release_claim`, `settle_admission`, `commit_state`, `LifecycleHarness`; test helpers `install_declaration`, `declaration`, `boundary`, `claim`.
- Produces:
  - `CONTROL_INTERFACE_VERSION = 3`; request member `host_route`; response member `admission` = `{"route", "declared_slots", "reserved": {"controller", "owner", "worker", "reviewer"}, "available", "waiting"}` (per D8).
  - `DeliveryRuntime.live_launches(state, *, at_time, unavailable) -> set[str]` — current-custody `action_id`s whose record is `active`, `at_time < deadline_at` and identity not in `unavailable`; `occupied_count` returns its length.
  - `LifecycleHarness`: `setUp` also creates `self.home` (a temporary directory outside `self.root`) holding the declaration `{"claude-code": 64 supported, "codex": unsupported}` and `self.cli_env = {**os.environ, "HOME": str(self.home)}`; every workflow-state subprocess the harness or a test starts passes `env=self.cli_env` (`run_cli`, `concurrent_finish`, `run_control_at_root`, the concurrent-controls test ≈L3579); `control_request(..., host_route="claude-code")` sends `interface_version` 3 and `host_route`; `control_raw(..., legacy=True)` converts through `_legacy_control` (which also pops `admission`) only when `legacy`; `_legacy_control` is unchanged otherwise (per D23).
  - `T/test_host_admission.py`: constants `T0`, `ZERO` and the mixin `AdmissionSweeps(LifecycleHarness)` with `slots(count)`, `sweep(now, issues=(12, 14), *, recorded=(), unobserved=(), forge=None, owners=None, ok=True, **fields)`, `claims()` and `kinds(response)`, as written below.

**Invariants:**
- `host_route` is `direct` or a grammar-valid route; `direct` requires exactly one requested issue and `max_parallel` 1 and reads no declaration; any other route must answer `supported` from `route_verdict`, else `WorkflowError` before the transaction (per D3, D9).
- The run binds its route at its first interface-3 sweep; a later sweep naming another route is refused with no write (per D3, D20).
- Every owner dispatch that creates a launch has a claimed role set in the same write; admission is all-or-nothing and composes with `max_parallel` in every lane (per D4, D6, D21).
- `waiting` lists, in request order, exactly the issues a lane skipped for want of a free role set while `max_parallel` had room; their summary state is unchanged; a waiting issue with no installed contract carries `delivery_contract_required` (per D21).
- A sweep ending in `finalize` persists no new controller claim and releases a held one `finalized` (per D20).
- `reserved` counts the roles of held claims whose holder is the controller or in `live_launches` after this sweep; `available = max(0, declared_slots − Σreserved)`; for `direct` the report is `declared_slots: null, available: null`, all-zero `reserved`, `waiting: []`.

- [ ] **Step 1: Write the failing tests**

Update the harness (Produces), then append to `T/test_host_admission.py`:

```python
T0 = "2026-08-13T20:00:00Z"
ZERO = {"controller": 0, "owner": 0, "worker": 0, "reviewer": 0}


class AdmissionSweeps(LifecycleHarness):
    """Interface-3 sweeps over issues 12 and 14 (and 15) with a per-test declaration."""

    def slots(self, count):
        install_declaration(self.home, declaration(**{
            "claude-code": {"support": "supported", "agent_slots": count},
            "codex": {"support": "unsupported"}}))

    def sweep(self, now, issues=(12, 14), *, recorded=(), unobserved=(), forge=None,
              owners=None, ok=True, **fields):
        def fact(n):
            path = str(self.root / f"wt-{n}")
            if n in recorded:
                return self.worktree_fact(n, recorded={"path": path,
                                                       "state": "matching_issue_branch"})
            return self.worktree_fact(n, candidate={"path": path, "state": "absent"})
        request = self.control_request(
            now=now, issues=list(issues), tracker=[self.tracker_fact(n) for n in issues],
            worktrees=[fact(n) for n in issues if n not in unobserved], owners=owners,
            **fields)
        request["forge"].update(forge or {})
        completed = self.control_raw(request=request, ok=ok, legacy=False)
        if not ok:
            return completed
        return boundary(self, completed.stdout.encode())

    def claims(self):
        return {c["holder"]: c for c in self.read_state()["admission"]["claims"]}

    def kinds(self, response):
        return [(a["kind"], a.get("issue")) for a in response["actions"]]


class ControlAdmissionTest(AdmissionSweeps, unittest.TestCase):
    """D4, D6, D11, D20, D21: control admits whole role sets and reports capacity."""

    def test_four_slots_admit_one_owner_and_seven_admit_both(self):
        self.slots(4)
        self.init_run()
        first = self.sweep(T0)
        self.assertEqual(self.kinds(first), [("spawn", 12), ("wait", None)])
        self.assertEqual(first["admission"], {"route": "claude-code", "declared_slots": 4,
            "reserved": {"controller": 1, "owner": 1, "worker": 1, "reviewer": 1},
            "available": 0, "waiting": [14]})
        waiting = next(s for s in first["summaries"] if s["issue"] == 14)
        self.assertEqual((waiting["state"], waiting["requirements"]), ("queued", [{
            "kind": "delivery_contract", "subject_id": "14",
            "reason_code": "delivery_contract_required", "detail_pointer": None}]))
        self.assertEqual(sorted(self.claims()), ["12:1:1", "controller"])
        woken = self.sweep("2026-08-13T20:10:00Z", recorded=(12,))  # a tracker wake
        self.assertEqual((self.kinds(woken), woken["admission"]["waiting"]),
                         ([("wait", None)], [14]))
        self.run_id = "issue-14-seven"
        self.slots(7)
        self.init_run()
        both = self.sweep(T0)
        self.assertEqual(self.kinds(both), [("spawn", 12), ("spawn", 14), ("wait", None)])
        self.assertEqual((both["admission"]["available"], both["admission"]["waiting"]),
                         (0, []))

    def test_a_released_claim_admits_the_waiting_owner(self):
        self.slots(4)
        self.init_run()
        self.sweep(T0)
        self.suspend(issue=12, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:05:00Z")
        # 12's worktree goes unobserved, so its resume is a round still owed.
        after = self.sweep("2026-08-13T20:06:00Z", unobserved=(12,))
        self.assertEqual(self.kinds(after), [("spawn", 14), ("wait", None)])
        claims = self.claims()
        self.assertEqual((claims["12:1:1"]["release_event"], claims["12:1:1"]["release_seq"]),
                         ("suspended", 1))
        self.assertIsNone(claims["14:1:1"]["released_at"])
        self.assertEqual(after["admission"]["waiting"], [])

    def test_an_unavailable_owner_is_released_and_taken_over_subject_to_admission(self):
        self.slots(4)
        self.init_run()
        self.sweep(T0)
        dead = self.owner_fact(event_id="12-dead", issue=12, attempt=1, launch=1)
        after = self.sweep("2026-08-13T20:05:00Z", recorded=(12,), owners=[dead])
        self.assertEqual(self.kinds(after), [("resume", 12), ("wait", None)])
        claims = self.claims()
        self.assertEqual(claims["12:1:1"]["release_event"], "owner_unavailable")
        self.assertIsNone(claims["12:1:2"]["released_at"])
        self.assertEqual(after["admission"]["waiting"], [14])

    def test_a_reap_suspends_and_a_reap_resumed_in_one_sweep_supersedes(self):
        for label, recorded, event in (("reaped", (), "suspended"),
                                       ("resumed", (12,), "superseded")):
            with self.subTest(label):
                self.run_id = f"reap-{label}"
                self.slots(4)
                self.init_run()
                self.sweep(T0, issues=(12,))
                self.sweep("2026-08-13T20:31:00Z", issues=(12,), recorded=recorded,
                           unobserved=() if recorded else (12,))
                self.assertEqual(self.claims()["12:1:1"]["release_event"], event)

    def test_forge_reconciliation_releases_finished(self):
        self.slots(4)
        self.init_run()
        self.sweep(T0, issues=(12,))
        merged = {"state": "merged", "merge_sha": "c" * 40,
                  "url": "https://github.com/fagenorn/nix-config/pull/12"}
        self.sweep("2026-08-13T20:31:00Z", issues=(12,), recorded=(12,),
                   forge={"12": merged})
        self.assertEqual(self.claims()["12:1:1"]["release_event"], "finished")

    def test_finalize_releases_the_controller_and_replays_byte_stable(self):
        self.slots(4)
        self.init_run()
        self.sweep(T0, issues=(12,))
        self.suspend(issue=12, attempt=1, blocked_on="human_gate",
                     now="2026-08-13T20:05:00Z")
        final = self.sweep("2026-08-13T20:06:00Z", issues=(12,), unobserved=(12,))
        self.assertEqual(final["actions"][-1]["kind"], "finalize")
        self.assertEqual(self.claims()["controller"]["release_event"], "finalized")
        self.assertEqual(final["admission"]["reserved"], ZERO)
        before = self.state_path.read_bytes()
        self.sweep("2026-08-13T20:07:00Z", issues=(12,), unobserved=(12,))
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_route_binding_is_immutable_and_unsupported_routes_write_nothing(self):
        self.slots(4)
        self.init_run()
        before = self.state_path.read_bytes()
        for label, route, issues, parallel in (
                ("declared unsupported", "codex", (12, 14), 2),
                ("undeclared", "gemini", (12, 14), 2),
                ("direct over two issues", "direct", (12, 14), 1),
                ("direct above one", "direct", (12,), 2)):
            with self.subTest(label):
                refused = self.sweep(T0, issues=issues, ok=False, host_route=route,
                                     max_parallel=parallel)
                self.assertEqual((refused.returncode, self.state_path.read_bytes()),
                                 (2, before))
        install_declaration(self.home, None)
        refused = self.sweep(T0, ok=False)
        self.assertEqual((refused.returncode, self.state_path.read_bytes()), (2, before))
        self.slots(4)
        self.sweep(T0)
        bound = self.state_path.read_bytes()
        refused = self.sweep("2026-08-13T20:01:00Z", issues=(12,), recorded=(12,),
                             ok=False, host_route="direct", max_parallel=1)
        self.assertEqual((refused.returncode, self.state_path.read_bytes()), (2, bound))

    def test_the_direct_route_reads_no_declaration_and_records_no_claims(self):
        install_declaration(self.home, None)
        self.init_run()
        response = self.sweep(T0, issues=(12,), host_route="direct", max_parallel=1)
        self.assertEqual(self.kinds(response), [("spawn", 12), ("wait", None)])
        self.assertEqual(response["admission"], {"route": "direct", "declared_slots": None,
            "reserved": ZERO, "available": None, "waiting": []})
        self.assertEqual(self.read_state()["admission"],
                         {"route": "direct", "releases": 0, "claims": []})

    def test_migrated_live_custody_is_adopted_and_new_admission_waits(self):
        self.init_run()  # the harness declaration: 64 slots
        self.sweep(T0)
        self.write_state(self._as_legacy(self.read_state(), 3))
        self.slots(4)
        response = self.sweep("2026-08-13T20:05:00Z", issues=(12, 14, 15),
                              recorded=(12, 14), max_parallel=3)
        self.assertEqual(sorted(self.claims()), ["12:1:1", "14:1:1", "controller"])
        self.assertEqual(response["admission"]["reserved"],
                         {"controller": 1, "owner": 2, "worker": 2, "reviewer": 2})
        self.assertEqual((response["admission"]["available"],
                          response["admission"]["waiting"]), (0, [15]))
```

In `T/_delivery_model_fixtures.py` the `control` fixture becomes `interface_version` 3 with
`"admission": {"route": "claude-code", "declared_slots": 7, "reserved": {"controller": 1,
"owner": 1, "worker": 1, "reviewer": 1}, "available": 3, "waiting": []}`; in
`T/test_delivery_model.py` add mutations:

```python
        bad = copy.deepcopy(fixtures["control"]); bad["admission"]["waiting"] = [151]; mutations["waiting_dispatched"] = bad
        bad = copy.deepcopy(fixtures["control"]); bad["interface_version"] = 2; mutations["control_interface_two"] = bad
        bad = copy.deepcopy(fixtures["control"]); bad["admission"]["route"] = "direct"; mutations["direct_with_slots"] = bad
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_host_admission.py home/common/agent-skills/tests/test_delivery_model.py 2>&1 | tail -4`
Expected: FAIL — `unsupported control interface version` and the v3 fixture rejected.

- [ ] **Step 3: Implement**

`validate_control_request`: the `host_route` rules in Invariants. `command_control`: `declared_slots = None` for `direct`, else `route_verdict(route)["agent_slots"]`, refusing a non-supported verdict with `WorkflowError(f"host route {route!r} is unsupported: {reason_code}")`. Inside `control(state)`, in order (a `direct` route skips B, D and every slot check):

- A. After `validate_control_custody`: bind — a `None` block becomes `{"route": route, "releases": 0, "claims": []}`; for a non-`direct` route, adopt every ledger issue's current custody whose record is `active` as a held owner claim acquired at `now`, even beyond the declaration (per D11). A bound block with another route raises.
- B. `settle_admission(state, at=now)`, then release (`owner_unavailable`, `at=now`) every held owner claim whose `parse_claim_holder` identity is in `unavailable`.
- C. The analysis loop, unchanged.
- D. Take the held controller claim, or append a new one acquired at `now` and remember it is new. `available = declared_slots − Σ roles of held claims whose holder is the controller or in runtime.live_launches(state, at_time=now, unavailable=unavailable)`.
- E. Lanes, order unchanged. Directly before each lane's `apply_policy(issue, True)` on a path that creates a launch — the remainder lane, the recover lane when `analysis[issue]["changed"]`, the resume lane after its unobserved-suspension `continue`, the retry lane inside `if capacity > 0:`, and the spawn lane — add: if `available < sum(OWNER_ROLE_SET.values())`, add the issue to `waiting` and `continue`. Where a lane appends to `proposal_order` for a dispatch, acquire the claim: `runtime.current_custody(issue, result["issue_state"])` gives the new launch; when its record is `active` and no claim (held or released) names its `action_id`, append a held owner claim acquired at `now` and subtract the role set from `available` (per D21).
- F. After applying `planned` and `control_transitions`: `settle_admission(state, at=now)`.
- G. Compute `next_deadline` before `changed`. With no deadline (`finalize`): drop a new controller claim, or release a held one `finalized` at `now`.
- H. `changed` also covers binding, adoption, every acquisition and release, and a new controller claim kept by a `wait`; `state["updated_at"] = now` when changed, as today.
- I. Summaries: `contract_required` is also true for an issue in `waiting` whose ledger issue is absent or has `delivery.contract is None`.
- J. The response adds `admission` as Invariants define, with `live_launches` recomputed after F.

`_wire.py` `_control_response`: members gain `admission`; require `interface_version` 3 (plain int) instead of `_v2`; validate `admission` exactly — `route` string; `reserved` exactly the four roles, plain ints ≥ 0; for `direct`: `declared_slots` and `available` null, `reserved` all zero, `waiting` empty; otherwise `declared_slots` int ≥ 4, `available` int ≥ 0, `waiting` unique issues forming a subsequence of the summaries' issue order; reject any action whose `issue` is in `waiting`.

Migrate the other suites to interface 3 (per D23): in `T/test_delivery_workflow.py`, `DeliveryAdmissionTest.control_request` sends `"interface_version": 3, "host_route": "direct"`; the two-issue request in `test_dispatching_control_response_passes_raw_workflow_response_validation` sends `claude-code` and its two `workflow-state` subprocesses run with `env={**os.environ, "HOME": str(make_home())}` (Task 2's `install_home` installs the committed declaration); `BuilderHarness.control_request` sends 3 and `host_route="claude-code"` (a keyword). Re-pin, citing D20, assertions that expect the first control sweep to leave the ledger byte-identical or that compare a whole ledger after control (≈L2593 gains the bound `admission`). A helper or test that hand-writes a lifecycle record outside the CLI after a claude-code sweep (`legacy_expiry_record`, in-place edits that end an attempt's custody) also writes `"admission": None`, because such a record predates admission and would otherwise leave a held claim naming no live launch; the next sweep re-binds and adopts (per D11, D23). No other expectation changes.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_host_admission.py home/common/agent-skills/tests/test_delivery_model.py 2>&1 | tail -3`
Expected: `OK`.

Run: `just agent-workflow-tests 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/scripts/workflow_delivery.py \
  home/common/agent-skills/scripts/delivery_model/_wire.py home/common/agent-skills/tests/test_host_admission.py \
  home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py \
  home/common/agent-skills/tests/_delivery_model_fixtures.py home/common/agent-skills/tests/test_delivery_model.py
git commit -m "feat(workflow-state): admit owners against declared agent slots in control interface 3 (#150)"
```
