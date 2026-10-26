# Task 3: Remainders parked on a gated cause wait for direction

Spec § Remainder resume gating, § Test seams (delivery workflow suite); per D3, D6, D8, D9. After this task a delivery remainder suspended on `human_gate` or `external` is relaunched only by a `human_directed` request; an undirected `control` sweep gives it the attempt lane's parked verdict, so the sweep dispatches nothing, charges no slot, leaves the issue's ledger entry alone and, with nothing else running, finalizes with the parked summary. Auto-resumable causes (`transport`, `unknown`, `host_capacity`, `owner_unavailable`) resume as before. The attempt lane's behaviour does not change.

**Files:**
- Modify: `python/agent_tools/attempt_custody.py`
- Modify: `tests/test_attempt_custody.py` (`VocabularyTest.test_the_closed_sets_are_the_shipped_ones`)
- Modify: `home/common/agent-skills/scripts/workflow_delivery.py` (`delivery_policy`, `remainder_policy`, one import)
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`_apply_one_issue_policy`: one argument and its docstring)
- Modify: `home/common/agent-skills/tests/test_delivery_workflow.py`
- Modify: `home/common/agent-skills/tests/test_workflow_delivery.py`
- Modify: `home/common/agent-skills/tests/test_delivery_model.py`

**Interfaces:**
- Consumes: `BLOCKED_ON_VALUES`, `AUTO_RESUMABLE_BLOCKED_ON` (`attempt_custody`); `_apply_one_issue_policy(..., human_directed: bool = False, ...)`, whose callers already pass `request["human_directed"]` (control, both passes) and `True` (direct); `remainder_policy`'s local `result(operation, *, changed=False, desired="resume", requirements=None)`.
- Produces:
  - `attempt_custody.HUMAN_GATED_BLOCKED_ON: frozenset[str]` = `BLOCKED_ON_VALUES - AUTO_RESUMABLE_BLOCKED_ON` = `{"human_gate", "external", "agent_dispatch"}` (D8).
  - `DeliveryRuntime.delivery_policy(self, issue_state, *, issue, request, source_kind, now, dispatch_permitted, remainder_deadline, owner_unavailable, tracker_halted, recorded_worktree, human_directed: bool)`: `human_directed` required, no default; passed through to `remainder_policy`.
  - `DeliveryRuntime.remainder_policy(self, issue_state, *, now, owner_unavailable, dispatch_permitted, tracker_halted, recorded_worktree, remainder_deadline, preview=None, issue=None, request=None, source_kind=None, human_directed: bool)`: `human_directed` required, no default.
  - `remainder_sweeps`'s `control(now, max_parallel=1, *, spawn=False, recorded="matching_issue_branch", human_directed=True)` in `test_delivery_workflow.py` (D9).

**Invariants:**
- The park check runs after the `failed` (stall-bound) branch, the preview, the `owner_unavailable` applicability raise and the live-custody `idle` branch, and before the `dispatch_permitted`, worktree-requirement and resume steps (D3, D8). It fires exactly when `remainder["state"] == "suspended"`, `not human_directed` and `remainder["blocked_on"] in HUMAN_GATED_BLOCKED_ON`, and returns `result("terminal", desired="terminal")`: `changed` false, `requirements` empty, `custody_kind` `remainder`, `expired` false (a reaped remainder carries `unknown`, so it is never parked).
- The parked verdict mutates nothing: no launch appended, `state`, `blocked_on` and `deadline_at` unchanged.
- `_apply_one_issue_policy` passes its own `human_directed` to `delivery_policy`; its attempt-lane predicate (`human_directed or latest["blocked_on"] in AUTO_RESUMABLE_BLOCKED_ON`) is untouched.
- No schema change, no migration, no new request member; `STALL_LIMIT` and the stall counter are untouched.

- [ ] **Step 1: Write the failing tests**

1. `tests/test_attempt_custody.py`, `test_the_closed_sets_are_the_shipped_ones`, after the `AUTO_RESUMABLE_BLOCKED_ON` assertion:

```python
        self.assertEqual(ac.HUMAN_GATED_BLOCKED_ON, {"human_gate", "external", "agent_dispatch"})
```

2. `home/common/agent-skills/tests/test_delivery_workflow.py`, `remainder_sweeps`: its inner `control` becomes

```python
        def control(now, max_parallel=1, *, spawn=False, recorded="matching_issue_branch",
                    human_directed=True):
            request = self.control_request(contract)
            request.update(host_route="claude-code", now=now, max_parallel=max_parallel,
                human_directed=human_directed,
```

(the rest of the call unchanged), and its docstring sentence about `control` gains: `` ``human_directed`` is the request's value, true by default because the remainder this fixture parks waits on ``human_gate`` and only a directed sweep resumes it (issue 458 D3, D9). ``

3. Same file: in `test_control_resumes_remainder_without_spending_implementation_attempt`, the resume request's `resume.update(now="2026-09-21T00:00:03Z",` gains `human_directed=True,`; in `test_a_refused_remainder_launch_parks_under_host_capacity`, its local `control`'s `request.update(host_route="claude-code", now=now, owners=list(owners),` gains `human_directed=True,` on the next line.

4. Same file, insert directly before `test_an_absent_remainder_worktree_refuses_only_the_remainder`:

```python
    def test_an_undirected_sweep_parks_a_gated_remainder_until_a_directed_one(self):
        """Issue 458 D3: no undirected sweep relaunches a `human_gate` remainder.

        Each such sweep dispatches nothing, charges no slot, leaves the issue's
        ledger entry alone and finalizes with the parked summary; the next
        human-directed sweep resumes it.
        """
        home = make_home(); self.addCleanup(shutil.rmtree, home, True)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            control, _, run_id = self.remainder_sweeps(root, home, "parked-remainder")
            state_path = root / f".superpowers/workflows/{run_id}/state.json"
            before = json.loads(state_path.read_text())["issues"]["151"]
            for now in ("2026-09-21T00:00:03Z", "2026-09-21T00:00:04Z"):
                with self.subTest(now=now):
                    value = json.loads(control(now, max_parallel=2, human_directed=False))
                    self.assertEqual([item["kind"] for item in value["actions"]], ["finalize"])
                    self.assertEqual(value["admission"]["waiting"], [])
                    summary = next(item for item in value["summaries"] if item["issue"] == 151)
                    self.assertEqual(
                        (summary["state"], summary["blocked_on"], summary["custody"]["kind"]),
                        ("suspended", "human_gate", "remainder"))
                    self.assertEqual(json.loads(state_path.read_text())["issues"]["151"], before)
            action = self.remainder_launch(
                control("2026-09-21T00:00:05Z", max_parallel=2, human_directed=True))
            self.assertEqual((action["custody"]["remainder"], action["custody"]["launch"]),
                             (1, 2))

    def test_an_auto_resumable_remainder_resumes_without_direction(self):
        """Issue 458 D3, D9: only a gated cause waits for direction; `owner_unavailable`
        does not. No control path this fixture drives writes that cause, so the test
        rewrites the parked remainder's `blocked_on` in the ledger."""
        home = make_home(); self.addCleanup(shutil.rmtree, home, True)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            control, _, run_id = self.remainder_sweeps(root, home, "auto-remainder")
            state_path = root / f".superpowers/workflows/{run_id}/state.json"
            state = json.loads(state_path.read_text())
            state["issues"]["151"]["delivery_remainders"][0]["blocked_on"] = "owner_unavailable"
            state_path.write_text(json.dumps(state))
            action = self.remainder_launch(
                control("2026-09-21T00:00:03Z", max_parallel=2, human_directed=False))
            self.assertEqual((action["custody"]["remainder"], action["custody"]["launch"]),
                             (1, 2))
```

5. `home/common/agent-skills/tests/test_workflow_delivery.py`: the module helper `direct_policy` passes `human_directed=True` to `runtime.delivery_policy`; the `common` dicts of `test_remainder_reentry_uses_ready_stage_worktree_requirement` and `test_an_unavailable_owner_past_the_remainder_deadline_yields_to_expiry` gain `human_directed=True` (their fixture remainder is suspended on `external`, D6, D9).

6. `home/common/agent-skills/tests/test_delivery_model.py`, `test_runtime_historical_merge_folds_facts_before_terminal_replay`: its `runtime.delivery_policy(...)` call gains `human_directed=True`.

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 1800 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m agent_tools.suite_runner tests/test_attempt_custody.py home/common/agent-skills/tests/test_workflow_delivery.py home/common/agent-skills/tests/test_delivery_model.py home/common/agent-skills/tests/test_delivery_workflow.py 2>&1 | grep -E "^(FAIL|ERROR):|^suite-runner: summary"'`
Expected: FAIL — `test_the_closed_sets_are_the_shipped_ones` (no `HUMAN_GATED_BLOCKED_ON`); the three `test_workflow_delivery.py` tests and the `test_delivery_model.py` test raise `TypeError` on the unexpected `human_directed` keyword; `test_an_undirected_sweep_parks_a_gated_remainder_until_a_directed_one` fails with `['delivery_remainder', 'wait'] != ['finalize']`. `test_an_auto_resumable_remainder_resumes_without_direction` passes before and after: it pins that the gate stays narrow.

- [ ] **Step 3: Write the minimal implementation**

1. `python/agent_tools/attempt_custody.py`, directly after `AUTO_RESUMABLE_BLOCKED_ON`:

```python
# A suspension cause only a person clears: an attempt or a delivery remainder parked on one
# resumes only on a human-directed re-entry (issue 458 D3).
HUMAN_GATED_BLOCKED_ON = BLOCKED_ON_VALUES - AUTO_RESUMABLE_BLOCKED_ON
```

2. `home/common/agent-skills/scripts/workflow_delivery.py`: after `from typing import Any`, a blank line and `from agent_tools.attempt_custody import HUMAN_GATED_BLOCKED_ON` (D8). Add the `human_directed: bool` keyword to `delivery_policy` (after `recorded_worktree`) and to `remainder_policy` (after `source_kind`), both without a default; `delivery_policy` passes `human_directed=human_directed` to its `self.remainder_policy(...)` call. `remainder_policy`'s docstring becomes:

```python
        """Resume the current delivery remainder without spending an attempt.

        A remainder suspended on a cause in ``HUMAN_GATED_BLOCKED_ON`` resumes
        only when ``human_directed``; otherwise it gets the parked verdict, the
        no-dispatch ``terminal`` with the ledger untouched (issue 458 D3).
        """
```

and directly after the live-custody branch (`return result("idle", desired="idle")`) insert:

```python
        if (remainder["state"] == "suspended" and not human_directed
                and remainder["blocked_on"] in HUMAN_GATED_BLOCKED_ON):
            # Parked like the attempt lane's gated suspension: no dispatch, no
            # slot, the ledger untouched (issue 458 D3).
            return result("terminal", desired="terminal")
```

3. `home/common/agent-skills/scripts/workflow-state.py`, `_apply_one_issue_policy`: the `_call(None, _delivery().delivery_policy, ...)` call ends `recorded_worktree=None if worktree is None else worktree["recorded"], human_directed=human_directed)`. In its docstring replace

```
    re-entry by name, which is the only thing that clears a
    `human_gate`/`external`/`agent_dispatch` suspension: a direct owner always
    carries it, and an orchestrated sweep carries it exactly when the caller
    listed the issue numbers itself. A `--label`/`--milestone` sweep never does,
    so it leaves those parked and reports them.
```

with

```
    re-entry by name, which is the only thing that clears a suspension on a
    cause in ``HUMAN_GATED_BLOCKED_ON`` (`human_gate`/`external`/`agent_dispatch`),
    whether it parks an attempt or a delivery remainder (issue 458 D3): a direct
    owner always carries it, and an orchestrated sweep carries it exactly when
    the caller listed the issue numbers itself. A `--label`/`--milestone` sweep
    never does, so it leaves those parked and reports them.
```

- [ ] **Step 4: Verify**

Run the Step 2 command with `home/common/agent-skills/tests/test_workflow_state.py` appended to the member list (timeout 1800 s).
Expected: no `FAIL:`/`ERROR:` line; `suite-runner: summary members=5 passed=5 failed=0`.

Run: `bash -c 'if git diff -U0 -- home/common/agent-skills/scripts/workflow-state.py | grep -E "^[-+].*AUTO_RESUMABLE_BLOCKED_ON"; then exit 1; fi'`
Expected: exit 0 (the attempt-lane predicate is untouched).

Run the Build.
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/attempt_custody.py tests/test_attempt_custody.py home/common/agent-skills/scripts/workflow_delivery.py home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_workflow_delivery.py home/common/agent-skills/tests/test_delivery_model.py
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "fix(workflow): gated remainders wait for a human-directed sweep (issue 458)" -m "<trailers>"
```
