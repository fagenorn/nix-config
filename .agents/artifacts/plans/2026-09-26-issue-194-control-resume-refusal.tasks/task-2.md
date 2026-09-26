# Task 2: Control refuses an unresumable resume per issue

Decisions: D1, D3, D4, D5, D8, D9, D10, D12, D13, D14. Spec "Resume lane: refuse
per issue (D1, D4, D5)", "Summary: the `worktree_fact` refusal (D3)" and "Test
seams". Work from the worktree root, at Task 1's commit. Every shell block
starts with `set -euo pipefail` (`set -uo pipefail` in the watch-it-fail step)
and these abbreviations, which the blocks below omit:

```bash
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
O=home/common/claude-code/skills/orchestrate-issues/SKILL.md
```

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (a nested
  `worktree_unresumable` in `command_control`'s inner `control(state)`, the
  resume lane's `observe` branch, the `control_summary(...)` call, and the
  module-level `control_summary` wrapper)
- Modify: `home/common/agent-skills/scripts/workflow_delivery.py`
  (`DeliveryRuntime.control_summary` only)
- Modify: `home/common/agent-skills/scripts/workflow_delivery_wire.py`
  (`DeliveryProjection.control_summary` only)
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md` (§5, one sentence)
- Test: `home/common/agent-skills/tests/test_workflow_state.py` (two module
  constants, two `LifecycleHarness` helpers, one replaced test, two new tests,
  and the tail of `test_absent_resume_exception_rejects_every_adjacent_case_without_mutation`)
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py`
  (`DeliveryAdmissionTest.remainder_sweeps` gains `recorded`, and one new test)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (one test)

**Interfaces:**
- Consumes: Task 1's `workflow-response` rules for one `worktree_fact` per
  control summary. Inside `control(state)` (existing): `worktree_by_issue`,
  `apply_policy(issue, dispatch_permitted) -> dict`, `planned`, `admit`,
  `slot_withheld`, `refusal_gated`. The implementation lane's resume `observe`
  result carries `requirements == [{"kind": "recorded_worktree", "path": <attempt
  worktree>}]`, and the remainder lane's carries the same shape. The
  forge-unobserved `observe` carries a `forge_pr` requirement and must still raise.
- Produces: the nested
  `worktree_unresumable(issue: int, result: dict[str, Any]) -> bool` and the
  local `unresumable: dict[int, dict[str, str]]` of `{"path", "state"}`
  observations. The keyword-only `unresumable: dict[str, str] | None` on
  `workflow-state.control_summary` (default `None`), on
  `DeliveryRuntime.control_summary` (through `**values`) and on
  `DeliveryProjection.control_summary` (required). In the tests:
  `LifecycleHarness.control_validated(**request_fields) -> dict`,
  the static `LifecycleHarness.unresumable_fact(path, recorded_state) -> dict`,
  and the `recorded` keyword on `remainder_sweeps`'s
  `control(now, max_parallel=1, *, spawn=False, recorded="matching_issue_branch")`.

**Invariants:**
- The lane's order is unchanged: capacity, the suspended-and-unobserved skip,
  `refusal_gated`, `slot_withheld`, then the dispatch-permitted plan (D5). The
  new check runs only when that plan answers `observe`.
- An `observe` that is not exactly one `recorded_worktree` requirement for the
  reported path, observed `absent` or `mismatch`, still raises
  `resume control action requires a matching recorded worktree observation` (D1).
- A refused issue is replanned with dispatch withheld and never reaches `admit`.
  It takes no `max_parallel` unit, no claim and no `waiting` entry. Its reap and
  `expired` delta persist (D4).
- `_apply_one_issue_policy`, `remainder_policy`, the remainder worktree check,
  the direct owner, `admit`, the action loop and the expiry fallback are
  byte-unchanged (D10).
- A summary without a refusal is byte-identical to the base (D13).
- New code names say "unresumable", never "refused" or "refusal" (D12).

- [ ] **Step 1: Write the failing tests**

1. In `$T/test_workflow_state.py`, directly after the `MODEL_FIXTURES = ...` line, add:

   ```python
   ARTIFACT_BUDGET = Path(__file__).parents[1] / "scripts" / "artifact_budget.py"
   BUDGET_POLICY = Path(__file__).parents[1] / "artifact-budget-policy.json"
   ```

2. In `class LifecycleHarness`, directly after `def control(self, **request_fields)`, add:

   ```python
       def control_validated(self, **request_fields):
           """Sweep, returning interface-3 bytes the `workflow-response` boundary passes (#194)."""
           completed = self.control_raw(legacy=False, ok=False, **request_fields)
           self.assertEqual(completed.returncode, 0, completed.stderr)
           validated = subprocess.run(
               [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
                "workflow-response", "--input", "-", "--policy", str(BUDGET_POLICY)],
               input=completed.stdout, capture_output=True, text=True, check=False,
               env=self.cli_env)
           self.assertEqual((validated.returncode, validated.stderr), (0, ""))
           self.assertEqual(validated.stdout, completed.stdout)
           return json.loads(completed.stdout)

       @staticmethod
       def unresumable_fact(path, recorded_state):
           """The summary requirement of a resume its recorded worktree ended (#194 D3)."""
           return {"kind": "worktree_fact", "subject_id": path,
                   "reason_code": f"recorded_worktree_{recorded_state}",
                   "detail_pointer": None}
   ```

3. Replace the whole of
   `test_control_requires_matching_recorded_state_for_resume_atomically` with
   these three tests (D8). The first splits the old subtests. T1 covers T2 as
   its `mismatch` subtest. The handoff's deadline is `20:30:00Z`, so T4's sweep
   at `21:00:00Z` reaps it:

   ```python
       def test_an_unmatched_resume_refuses_its_issue_unless_a_candidate_would_move_it(self):
           """An unavailable owner's resume on an absent or mismatched worktree (#194 D8).

           Without a candidate only the issue is refused, in its summary, and the
           sweep's claim release persists. A candidate never relocates a resume,
           so it still refuses the whole sweep, at the current-action check.
           """
           self.init_run(now="2026-08-19T12:00:00Z")
           path = str(self.root / "wt-47")
           replacement = str(self.root / "replacement-47")
           self.control(
               now="2026-08-19T12:00:00Z", issues=[47],
               tracker=[self.tracker_fact(47)],
               worktrees=[self.worktree_fact(
                   47, candidate={"path": path, "state": "absent"})],
           )
           before = self.state_path.read_bytes()
           for recorded_state in ("absent", "mismatch"):
               request = {"now": "2026-08-19T12:01:00Z", "issues": [47],
                          "tracker": [self.tracker_fact(47)],
                          "owners": [self.owner_fact(event_id=f"47-{recorded_state}",
                                                     issue=47, attempt=1, launch=1)]}
               recorded = {"path": path, "state": recorded_state}
               with self.subTest(recorded_state=recorded_state, candidate=True):
                   rejected = self.control_raw(
                       **request, ok=False, worktrees=[self.worktree_fact(
                           47, recorded=recorded,
                           candidate={"path": replacement, "state": "absent"})])
                   self.assertEqual((rejected.returncode, rejected.stdout), (2, ""))
                   self.assertIn(
                       "current control action requires a recorded worktree observation",
                       rejected.stderr)
                   self.assertEqual(self.state_path.read_bytes(), before)
               with self.subTest(recorded_state=recorded_state, candidate=False):
                   response = self.control_validated(
                       **request, worktrees=[self.worktree_fact(47, recorded=recorded)])
                   self.assertEqual([item["kind"] for item in response["actions"]], ["wait"])
                   self.assertEqual(response["deltas"], [])
                   summary = response["summaries"][0]
                   self.assertEqual(summary["state"], "active")
                   self.assertIn(self.unresumable_fact(path, recorded_state),
                                 summary["requirements"])
                   state = self.read_state()
                   self.assertEqual(state["issues"]["47"], json.loads(before)["issues"]["47"])
                   self.assertEqual(
                       [(claim["holder"], claim["release_event"])
                        for claim in state["admission"]["claims"]],
                       [("controller", None), ("47:1:1", "owner_unavailable")])
               self.state_path.write_bytes(before)

       def test_an_unresumable_suspension_refuses_only_its_own_issue(self):
           """T1, T2 (#194): its neighbour spawns, and the refused issue is reported, unchanged.

           `max_parallel=1` is the discriminating case: a refused issue that
           took a unit would leave its neighbour unspawned.
           """
           for recorded_state, max_parallel in (
                   ("absent", 1), ("absent", 2), ("mismatch", 1), ("mismatch", 2)):
               with self.subTest(recorded_state=recorded_state, max_parallel=max_parallel):
                   self.run_id = f"unresumable-{recorded_state}-{max_parallel}"
                   self.init_run()
                   path = os.path.abspath(self.root / f"wt-47-{recorded_state}-{max_parallel}")
                   spare = os.path.abspath(self.root / f"wt-51-{recorded_state}-{max_parallel}")
                   self.spawn(issue=47, worktree=path)
                   self.progress(issue=47, phase=1, now="2026-08-13T20:01:00Z")
                   self.suspend(issue=47, attempt=1, blocked_on="usage_limit",
                                now="2026-08-13T20:02:00Z")
                   before = self.read_state()["issues"]["47"]
                   response = self.control_validated(
                       now="2026-08-13T20:03:00Z", issues=[47, 51],
                       tracker=[self.tracker_fact(47), self.tracker_fact(51)],
                       worktrees=[
                           self.worktree_fact(47, recorded={"path": path,
                                                            "state": recorded_state}),
                           self.worktree_fact(51, candidate={"path": spare,
                                                             "state": "absent"})],
                       max_parallel=max_parallel)
                   self.assertEqual(
                       [(item["kind"], item.get("issue")) for item in response["actions"]],
                       [("spawn", 51), ("wait", None)])
                   self.assertEqual([(item["issue"], item["kind"]) for item in response["deltas"]],
                                    [(51, "spawned")])
                   self.assertEqual(response["admission"]["waiting"], [])
                   summary = response["summaries"][0]
                   self.assertEqual((summary["issue"], summary["state"], summary["blocked_on"]),
                                    (47, "suspended", "usage_limit"))
                   self.assertIn(self.unresumable_fact(path, recorded_state),
                                 summary["requirements"])
                   state = self.read_state()
                   self.assertEqual(state["issues"]["47"], before)
                   self.assertFalse(any(
                       claim["holder"].startswith("47:") and claim["released_at"] is None
                       for claim in state["admission"]["claims"]))

       def test_an_unresumable_expired_handoff_still_persists_its_reap(self):
           """T4 (#194): the refused issue keeps this sweep's reap and its `expired` delta."""
           self.init_run()
           path = os.path.abspath(self.root / "wt-48")
           self.spawn(issue=48, worktree=path)
           handoff = self.write_handoff(48)
           self.progress(issue=48, phase=1, now="2026-08-13T20:01:00Z",
                         turn_count=118, handoff_path=handoff)
           attempt = self.read_state()["issues"]["48"]["attempts"][-1]
           self.assertEqual((attempt["state"], attempt["deadline_at"]),
                            ("handed_off", "2026-08-13T20:30:00Z"))
           response = self.control_validated(
               now="2026-08-13T21:00:00Z", issues=[48],
               tracker=[self.tracker_fact(48)],
               worktrees=[self.worktree_fact(48, recorded={"path": path, "state": "absent"})],
               max_parallel=1)
           self.assertEqual(response["actions"], [{"id": "finalize", "kind": "finalize"}])
           self.assertEqual(
               [(item["issue"], item["kind"], item["state"]) for item in response["deltas"]],
               [(48, "expired", "suspended")])
           self.assertIn(self.unresumable_fact(path, "absent"),
                         response["summaries"][0]["requirements"])
           attempt = self.read_state()["issues"]["48"]["attempts"][-1]
           self.assertEqual((attempt["state"], attempt["blocked_on"]), ("suspended", "unknown"))
   ```

4. In `test_absent_resume_exception_rejects_every_adjacent_case_without_mutation`,
   flip the Phase-1 orchestrated handoff (D8, D14). Its summary is contracted.
   Extend the comment and replace the final sweep:

   ```python
   # before
           # The exception is bounded by the phase, not by who dispatches: an
           # orchestrated handoff past Phase 0 owns a worktree it must still show.
   # after
           # The exception is bounded by the phase, not by who dispatches: an
           # orchestrated handoff past Phase 0 owns a worktree it must still show,
           # so its absence refuses that issue alone, in its summary (#194).
   ```

   ```python
   # before
           before = self.state_path.read_bytes()
           rejected = self.control_raw(
               now="2026-08-20T10:02:00Z", issues=[77],
               tracker=[self.tracker_fact(77)],
               worktrees=[self.worktree_fact(77, recorded={
                   "path": dispatched["worktree"], "state": "absent",
               })], max_parallel=1, ok=False,
           )
           self.assertIn("matching recorded worktree", rejected.stderr)
           self.assertEqual(self.state_path.read_bytes(), before)
   # after
           before = self.state_path.read_bytes()
           response = self.control_validated(
               now="2026-08-20T10:02:00Z", issues=[77],
               tracker=[self.tracker_fact(77)],
               worktrees=[self.worktree_fact(77, recorded={
                   "path": dispatched["worktree"], "state": "absent",
               })], max_parallel=1,
           )
           self.assertEqual([item["kind"] for item in response["actions"]], ["wait"])
           self.assertEqual(response["summaries"][0]["state"], "handed_off")
           self.assertIn(self.unresumable_fact(dispatched["worktree"], "absent"),
                         response["summaries"][0]["requirements"])
           self.assertEqual(self.state_path.read_bytes(), before)
   ```

   `test_control_still_demands_the_worktree_of_an_unobserved_handoff` stays
   byte-unchanged (D8).

5. In `DeliveryAdmissionTest.remainder_sweeps` of `$T/test_delivery_workflow.py`,
   thread the recorded state. The docstring sentence
   ``` ``control(now, max_parallel=1)`` sweeps with the recorded worktree
   observed and returns the raw response bytes.``` becomes
   ``` ``control(now, max_parallel=1)`` sweeps with the recorded worktree
   observed as ``recorded`` (``matching_issue_branch`` unless given) and returns
   the raw response bytes.``` The code changes as follows:

   ```python
   # before
           def control(now, max_parallel=1, *, spawn=False):
   # after
           def control(now, max_parallel=1, *, spawn=False, recorded="matching_issue_branch"):
   ```

   ```python
   # before
                       "recorded": None if spawn else {"path": worktree,
                                                       "state": "matching_issue_branch"},
   # after
                       "recorded": None if spawn else {"path": worktree, "state": recorded},
   ```

   Then insert T3 directly before `test_a_live_remainder_short_of_agent_slots_is_not_waiting`:

   ```python
       def test_an_absent_remainder_worktree_refuses_only_the_remainder(self):
           """T3 (#194): a resumable remainder on an absent worktree is reported, not raised."""
           home = make_home(); self.addCleanup(shutil.rmtree, home, True)
           with tempfile.TemporaryDirectory() as raw:
               root = Path(raw); run_id = "absent-remainder"
               control, _ = self.remainder_sweeps(root, home, run_id)
               state_path = root / f".superpowers/workflows/{run_id}/state.json"
               before = json.loads(state_path.read_text())["issues"]["151"]
               response = control("2026-09-21T00:00:03Z", max_parallel=2, recorded="absent")
               validated = subprocess.run(
                   [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
                    "workflow-response", "--input", "-", "--policy", str(POLICY)],
                   input=response, capture_output=True, check=False)
               self.assertEqual((validated.returncode, validated.stderr), (0, b""))
               self.assertEqual(validated.stdout, response)
               value = json.loads(response)
               self.assertEqual([item["kind"] for item in value["actions"]], ["finalize"])
               summary = value["summaries"][0]
               self.assertEqual(
                   (summary["state"], summary["blocked_on"], summary["custody"]["kind"]),
                   ("suspended", "human_gate", "remainder"))
               self.assertIn({"kind": "worktree_fact", "subject_id": str(root / "worktree"),
                              "reason_code": "recorded_worktree_absent",
                              "detail_pointer": None}, summary["requirements"])
               self.assertEqual(json.loads(state_path.read_text())["issues"]["151"], before)
   ```

6. In `$T/test_workflow_skill_contracts.py`, insert directly before
   `test_background_dispatch_flag_appears_only_in_orchestrate_issues`:

   ```python
       def test_final_report_names_an_unresumable_issue(self):
           # A resume its recorded worktree ended is reported with that reason,
           # never as progressing (#194 D9, D12).
           collapsed = normalized(self.section(
               self.orchestrate, "## 5. Final report", "## Notes"))
           self.assert_ordered(
               collapsed, "`worktree_fact`", "`recorded_worktree_absent`",
               "`recorded_worktree_mismatch`", "cannot resume", "never as progressing")
   ```

- [ ] **Step 2: Watch them fail**

```bash
set -uo pipefail
PYTHONPATH=python python3 -m unittest $T/test_workflow_state.py \
  -k unmatched_resume_refuses -k unresumable_suspension -k unresumable_expired_handoff \
  -k absent_resume_exception_rejects -k unobserved_handoff 2>&1 \
  | grep -E '^(FAIL|ERROR):|AssertionError|^Ran|^OK|^FAILED'
PYTHONPATH=python python3 -m unittest $T/test_delivery_workflow.py \
  -k absent_remainder_worktree -k live_remainder_with_a_free_slot \
  -k suspended_remainder_with_a_free_slot 2>&1 \
  | grep -E '^(FAIL|ERROR):|AssertionError|^Ran|^OK|^FAILED'
PYTHONPATH=python python3 -m unittest $T/test_workflow_skill_contracts.py \
  -k unresumable_issue 2>&1 | grep -E '^(FAIL|ERROR):|^Ran|^OK|^FAILED'
```

Expected. The first run is `Ran 5 tests` and `FAILED (failures=10)` — the
T1/T2 test fails in all four of its `recorded_state` × `max_parallel`
subtests (per D15). Every failure except the two `candidate=True` subtests is
`AssertionError: 2 != 0 : workflow-state: resume control action requires a
matching recorded worktree observation`. Those two fail because the
`current control action ...` text is not in that same stderr. The
unobserved-handoff test passes. The second run is `Ran 3 tests` and
`FAILED (failures=1)`: T3 fails on the same `2 != 0` message. The third run is
`FAILED (failures=1)`. Any other failure means a fixture is wrong: stop and
report it.

- [ ] **Step 3: Refuse per issue in the resume lane**

In `command_control`'s inner `control(state)` of `$S/workflow-state.py`, insert
this directly after `refusal_gated` and before `def acquire`. The full code is
given because it carries D1's four conditions:

```python
        unresumable: dict[int, dict[str, str]] = {}

        def worktree_unresumable(issue: int, result: dict[str, Any]) -> bool:
            """Whether a truthful recorded-worktree fact ends this resume for its issue (#194 D1).

            It holds when the dispatch-permitted plan asked for exactly one
            recorded worktree and the caller reported that same path as
            ``absent`` or ``mismatch``; the observation is kept for the issue's
            summary. Any other ``observe`` is a caller-protocol error that the
            resume lane still raises.
            """
            observation = worktree_by_issue.get(issue)
            recorded = None if observation is None else observation["recorded"]
            if (recorded is None or recorded["state"] not in {"absent", "mismatch"}
                    or result["requirements"] != [{"kind": "recorded_worktree",
                                                   "path": recorded["path"]}]):
                return False
            unresumable[issue] = {"path": recorded["path"], "state": recorded["state"]}
            return True
```

Then, in the resume lane, replace its `observe` branch. Leave every line above
it unchanged except the suspended-skip comment's last sentence, which would
otherwise read as the old whole-sweep refusal:

```python
# before
                # and the next sweep resumes it. A handoff, and any worktree
                # observed as absent or mismatched, stays a refusal (per D9).
# after
                # and the next sweep resumes it. An unobserved handoff stays a
                # whole-sweep error; a worktree observed as absent or mismatched
                # refuses only its own issue, in its summary (per D9; #194 D1).
```

The `observe` branch:

```python
# before
            result = apply_policy(issue, True)
            if result["operation"] == "observe":
                raise WorkflowError(
                    "resume control action requires a matching recorded worktree observation"
                )
            admit(issue, result)
# after
            result = apply_policy(issue, True)
            if result["operation"] == "observe":
                if not worktree_unresumable(issue, result):
                    raise WorkflowError(
                        "resume control action requires a matching recorded worktree observation"
                    )
                # Persist only what a withheld dispatch would: this sweep's reap
                # and its `expired` delta, with no admission (#194 D4).
                apply_policy(issue, False)
                continue
            admit(issue, result)
```

In the `summaries = [control_summary(...)]` comprehension, add
`unresumable=unresumable.get(issue),` as the last keyword, after
`contract_required=(...)`.

- [ ] **Step 4: Render the refusal in the summary**

1. The module-level `control_summary` in `$S/workflow-state.py` gains the
   keyword `unresumable: dict[str, str] | None = None`, after
   `contract_required`, and passes `unresumable=unresumable` through to
   `_delivery().control_summary(...)`.
2. In `$S/workflow_delivery_wire.py`, `DeliveryProjection.control_summary`
   gains the required keyword `unresumable: dict[str, str] | None`, after
   `contract_required: bool`. Bind the existing `requirements` expression to a
   local, append the rendered refusal, and return the local (D3):

   ```python
           requirements = (missing if delivery is None or delivery["contract"] is None
                           else ([] if reduction is None else copy.deepcopy(reduction["requirements"])))
           if unresumable is not None:
               requirements.append({"kind": "worktree_fact", "subject_id": unresumable["path"],
                                    "reason_code": "recorded_worktree_" + unresumable["state"],
                                    "detail_pointer": None})
   ```

   The returned dict's `"requirements"` member becomes `requirements`.
3. In `$S/workflow_delivery.py`, `DeliveryRuntime.control_summary` sorts only a
   summary that carries the refusal (D13):

   ```python
       def control_summary(self, **values: Any) -> dict[str, Any]:
           summary = self._projection.control_summary(**values)
           if values.get("unresumable") is not None:
               # The projection holds no canonical form; the fact joins the
               # requirements in the validator's canonical-bytes order (#194 D13).
               summary["requirements"].sort(key=self._model.canonical_bytes)
           return summary
   ```

- [ ] **Step 5: Say it in the final report**

In §5 of `$O`, directly after the sentence ending
"`delivery_contract_required` is an issue that never received a contract.",
add this sentence and keep the paragraph's wrap near 80 columns (D9, D12):

> A summary whose `worktree_fact` requirement reads `recorded_worktree_absent`
> or `recorded_worktree_mismatch` is an issue that cannot resume, because its
> recorded worktree is gone or is not on the issue branch: report it as unable
> to resume for that reason, never as progressing.

- [ ] **Step 6: Verify**

```bash
set -euo pipefail
PYTHONPATH=python python3 -m unittest $T/test_workflow_state.py \
  -k unmatched_resume_refuses -k unresumable_suspension -k unresumable_expired_handoff \
  -k absent_resume_exception_rejects -k unobserved_handoff 2>&1 \
  | grep -E '^(FAIL|ERROR):|AssertionError|^Ran|^OK|^FAILED'
test "$(grep -c 'worktree_unresumable(' $S/workflow-state.py)" = 2
test "$(grep -c 'resume control action requires a matching recorded worktree observation' $S/workflow-state.py)" = 1
test "$(git diff -U0 -- $S/workflow_delivery.py | grep -c '^@@')" = 1
if git diff -U0 -- $S/workflow-state.py $S/workflow_delivery.py $S/workflow_delivery_wire.py \
    | grep -E '^\+' | grep -qiE 'refus(ed|al)'; then exit 1; fi
```

Expected: `Ran 5 tests` and `OK`, and every check exits 0. The last check
enforces D12's naming.

```bash
set -euo pipefail
PYTHONPATH=python python3 -m unittest $T/test_workflow_state.py \
  $T/test_host_admission.py $T/test_admission_replay.py \
  $T/test_delivery_workflow.py $T/test_workflow_delivery.py \
  $T/test_delivery_model.py 2>&1 | grep -E '^(FAIL|ERROR):|^Ran|^OK|^FAILED'
just agent-workflow-tests 2>&1 | grep -E '^(FAIL|ERROR):|^Ran|^OK|^FAILED'
just build 2>&1 | tail -3
```

Expected: `Ran 268 tests` and `OK` for the six suites. That is 264 at the base,
plus Task 1's one test and this task's three new ones. The run takes about four
minutes. `just agent-workflow-tests` ends in `OK`, and `just build` exits 0.

- [ ] **Step 7: Commit**

```bash
set -euo pipefail
git add $S/workflow-state.py $S/workflow_delivery.py $S/workflow_delivery_wire.py \
  $T/test_workflow_state.py $T/test_delivery_workflow.py \
  $T/test_workflow_skill_contracts.py $O
git commit -m "fix(workflow-state): refuse an unresumable resume per issue in control (#194)" \
  -m "When a resume's recorded worktree is truthfully observed absent or mismatched, control replans that issue with dispatch withheld and reports a worktree_fact in its summary instead of refusing the whole sweep; every other issue proceeds." \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
