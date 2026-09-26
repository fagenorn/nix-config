# Task 1: One admission step for every dispatch lane

Decisions: D3, D4 (T4 is baseline), D5 (T1's byte identity), D6, D7, D8, D9,
D10. Spec "The admission step (D3)", "Response contract (D5)" and "Test seams".
Work from the worktree root. Every shell block starts with `set -euo pipefail`
(`set -uo pipefail` in the watch-it-fail step) and these abbreviations, which
the blocks below omit:

```bash
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
```

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (a nested
  `admit` in `command_control`'s inner `control(state)`, and the five dispatch
  lanes that follow it)
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py`
  (`DeliveryAdmissionTest`: one fixture method, one static helper, three tests)

**Interfaces:**
- Consumes (existing, `DeliveryAdmissionTest`): `control_request(contract)`,
  `report_common(custody, digest)`, `failed_summary(custody, digest)`; the
  module imports `contract_and_delivery_for_stage`, `observation`,
  `selection`, `authority`, `seal`, `make_home`; the constants `WORKFLOW`,
  `ARTIFACT_BUDGET`, `POLICY`, `NOW`. Inside `control(state)`:
  `acquire(issue: int) -> None`, `planned`, `proposal_order`, the local
  `capacity`, and the module constant
  `CONTROL_DISPATCH_KINDS = frozenset({"spawn", "resume", "retry", "recover"})`.
- Produces: the nested
  `admit(issue: int, result: dict[str, Any], *, charge: bool = True) -> bool`
  (no test calls it, per D6). In the tests,
  `DeliveryAdmissionTest.remainder_sweeps(self, root, home, run_id) -> (control, checkpoint)`,
  where `control(now: str, max_parallel: int = 1, *, spawn: bool = False) -> bytes`
  returns the raw response and
  `checkpoint(custody: dict, now: str, denial: dict | None = None) -> dict`
  returns the decoded checkpoint response, and the static
  `DeliveryAdmissionTest.remainder_launch(response: bytes) -> dict`. Task 2
  consumes all three test names.

**Invariants:**
- An issue enters `proposal_order` only through `admit` or the `refuse`
  branch: `grep -c 'proposal_order.append(' $S/workflow-state.py` is `2` after
  this task (it is `6` at the start).
- `admit` never raises. A non-dispatch operation returns False, is charged
  nothing, and stays in `planned`, so a `changed` result is still persisted
  and still summarized (D8).
- The recover lane passes `charge=analysis[issue]["changed"]`, so a re-emitted
  recover takes no new claim (#150 D21).
- Each lane keeps its pre-checks (capacity, `slot_withheld`, `refusal_gated`,
  the round-still-owed skip) and its `observe` raise, in their current order.
  Only the three `if result["operation"] == "contract": continue` skips go
  (`3` → `0`).
- The action loop (`for issue in proposal_order:` and its closed delta map),
  the `refuse` branch, and the expiry fallback's comment and
  `issue not in planned` guard stay byte-unchanged.
- A live remainder swept at a free slot yields the same response bytes and the
  same ledger bytes as the same sweep at `max_parallel` 1 (D5).

- [ ] **Step 1: Write the failing tests**

In `class DeliveryAdmissionTest` of `$T/test_delivery_workflow.py`, insert this
block directly after `test_a_refused_remainder_launch_parks_under_host_capacity`
and before `test_control_allocates_only_one_proven_second_remainder`. The
remainder's deadline is three hours after its finish (`03:00:01Z`), which is why
T3's expiry sweep is at `04:00:00Z`.

```python
    def remainder_sweeps(self, root, home, run_id):
        """Drive a claude-code run until remainder r1:1 is suspended on a denial (#190).

        Issue 151's owner spawns, fails after selecting its output, and an
        authority denial parks the minted remainder on ``human_gate``. Returns
        ``(control, checkpoint)``. ``control(now, max_parallel=1)`` sweeps with
        the recorded worktree observed and returns the raw response bytes.
        ``checkpoint(custody, now)`` reports that custody again without progress
        and returns the decoded response.
        """
        contract, delivery, actual = contract_and_delivery_for_stage(self.model, "publish")
        digest = self.model.canonical_digest(contract)
        worktree = str(root / "worktree"); run = ("--repo-root", root, "--run-id", run_id)

        def invoke(*args, stdin=None):
            completed = subprocess.run(
                [sys.executable, str(WORKFLOW), *map(str, args)],
                input=None if stdin is None else json.dumps(stdin).encode(),
                capture_output=True, check=False, env={**os.environ, "HOME": str(home)})
            self.assertEqual(completed.returncode, 0, completed.stderr.decode())
            return completed.stdout

        def control(now, max_parallel=1, *, spawn=False):
            request = self.control_request(contract)
            request.update(host_route="claude-code", now=now, max_parallel=max_parallel,
                tracker=[{"issue": 151, "state": "open" if spawn else "closed",
                          "open_blockers": [], "decision_blockers": []}],
                worktrees=[{"issue": 151,
                    "recorded": None if spawn else {"path": worktree,
                                                    "state": "matching_issue_branch"},
                    "candidate": {"path": worktree, "state": "absent"} if spawn else None}])
            request["authorization_intents"]["151"] = delivery["authorization_intents"]
            return invoke("control", *run, "--request-file", "-", stdin=request)

        def checkpoint(custody, now, denial=None):
            report = self.report_common(custody, digest)
            report["requested_scope"] = actual
            if denial is not None:
                report["authority_observations"] = [denial]
            return json.loads(invoke("checkpoint-delivery", *run, "--checkpoint-file",
                                     "-", "--now", now, stdin=report))

        invoke("init-run", *run, "--now", NOW)
        owner = json.loads(control(NOW, spawn=True))["actions"][0]
        failed = self.failed_summary(owner["custody"], digest)
        failed["delivery_observations"] = [observation(
            self.model, contract, "selected_output",
            {"selected_output": selection(self.model, digest)})]
        remainder = json.loads(invoke("finish", *run, "--summary-file", "-",
                                      "--now", "2026-09-21T00:00:01Z", stdin=failed))
        denial = authority(self.model, contract, actual, remainder["custody"])
        denial["observed_at"] = "2026-09-21T00:00:02Z"; seal(self.model, denial)
        parked = checkpoint(remainder["custody"], "2026-09-21T00:00:02Z", denial)
        self.assertEqual((parked["state"], parked["blocked_on"]), ("suspended", "human_gate"))
        return control, checkpoint

    @staticmethod
    def remainder_launch(response):
        """The response's one ``delivery_remainder`` action; StopIteration when absent."""
        return next(item for item in json.loads(response)["actions"]
                    if item["kind"] == "delivery_remainder")

    def test_a_live_remainder_with_a_free_slot_matches_the_exhausted_sweep(self):
        """T1: a live remainder takes no free slot and the sweep does not crash."""
        home = make_home(); self.addCleanup(shutil.rmtree, home, True)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); run_id = "live-remainder"
            control, _ = self.remainder_sweeps(root, home, run_id)
            launch = self.remainder_launch(control("2026-09-21T00:00:03Z"))
            self.assertEqual((launch["custody"]["remainder"], launch["custody"]["launch"]),
                             (1, 2))
            state_path = root / f".superpowers/workflows/{run_id}/state.json"
            ledger = state_path.read_bytes()
            free = control("2026-09-21T00:00:04Z", max_parallel=2)
            free_ledger = state_path.read_bytes()
            validated = subprocess.run(
                [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
                 "workflow-response", "--input", "-", "--policy", str(POLICY)],
                input=free, capture_output=True, check=False)
            self.assertEqual((validated.returncode, validated.stderr), (0, b""))
            self.assertEqual(validated.stdout, free)
            # The same sweep with capacity exhausted, from the same pre-sweep ledger.
            state_path.write_bytes(ledger)
            exhausted = control("2026-09-21T00:00:04Z", max_parallel=1)
            self.assertEqual(free, exhausted)
            self.assertEqual(free_ledger, state_path.read_bytes())

    def test_a_stall_bound_remainder_reap_persists_failed_without_a_dispatch(self):
        """T3: the reap that crosses the stall bound fails the remainder, dispatching nothing."""
        home = make_home(); self.addCleanup(shutil.rmtree, home, True)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); run_id = "stalled-remainder"
            control, checkpoint = self.remainder_sweeps(root, home, run_id)
            for launch, now, reported in (
                    (2, "2026-09-21T00:00:03Z", "2026-09-21T00:00:04Z"),
                    (3, "2026-09-21T00:00:05Z", "2026-09-21T00:00:06Z"),
                    (4, "2026-09-21T00:00:07Z", None)):
                action = self.remainder_launch(control(now))
                self.assertEqual(action["custody"]["launch"], launch)
                if reported is not None:
                    self.assertEqual(checkpoint(action["custody"], reported)["state"],
                                     "suspended")
            state_path = root / f".superpowers/workflows/{run_id}/state.json"
            record = json.loads(state_path.read_text())["issues"]["151"]["delivery_remainders"][0]
            self.assertEqual((record["state"], record["stalled_resumes"]), ("active", 2))
            # r1:4's deadline is 2026-09-21T03:00:01Z; this sweep lands after it.
            response = json.loads(control("2026-09-21T04:00:00Z"))
            record = json.loads(state_path.read_text())["issues"]["151"]["delivery_remainders"][0]
            self.assertEqual(
                (record["state"], record["result_source"], record["stalled_resumes"]),
                ("failed", "stalled", 3))
            self.assertEqual([item["kind"] for item in response["actions"]], ["finalize"])
            summary = next(item for item in response["summaries"] if item["issue"] == 151)
            self.assertEqual((summary["state"], summary["custody"]["kind"]),
                             ("failed", "remainder"))

    def test_a_suspended_remainder_with_a_free_slot_resumes(self):
        """T4: baseline, a resumable human-gate remainder still resumes at a free slot."""
        home = make_home(); self.addCleanup(shutil.rmtree, home, True)
        with tempfile.TemporaryDirectory() as raw:
            control, _ = self.remainder_sweeps(Path(raw), home, "suspended-remainder")
            action = self.remainder_launch(control("2026-09-21T00:00:03Z", max_parallel=2))
            self.assertEqual((action["custody"]["remainder"], action["custody"]["launch"]),
                             (1, 2))
```

- [ ] **Step 2: Watch them fail**

```bash
set -uo pipefail
PYTHONPATH=python python3 -m unittest $T/test_delivery_workflow.py \
  -k live_remainder_with_a_free_slot -k stall_bound_remainder \
  -k suspended_remainder_with_a_free_slot 2>&1 \
  | grep -E '^(FAIL|ERROR):|KeyError|AssertionError|^Ran|^OK|^FAILED'
```

Expected: `Ran 3 tests` and `FAILED (failures=2)`.
`test_a_live_remainder_with_a_free_slot_matches_the_exhausted_sweep` fails with
`KeyError: 'idle'`, and
`test_a_stall_bound_remainder_reap_persists_failed_without_a_dispatch` fails with
`KeyError: 'terminal'`. T4 passes, as baseline coverage (D4). Any other failure
means the fixture is wrong: stop and report it.

- [ ] **Step 3: Add the admission step**

In `command_control`'s inner `control(state)`, directly after
`proposal_order: list[int] = []` and before `def apply_policy`, add this. The
full code is given because it carries D3's charge rule and D8's
filter-not-raise decision.

```python
        def admit(issue: int, result: dict[str, Any], *, charge: bool = True) -> bool:
            """Queue ``result`` when it dispatches, charging it unless ``charge`` is false (D3).

            Any operation outside ``CONTROL_DISPATCH_KINDS`` is a policy verdict,
            not an error: it is queued nowhere, charged nothing and left in
            ``planned``, and the call returns False (D8). A dispatch joins
            ``proposal_order``; with ``charge`` it also claims its role set
            through ``acquire`` and spends one ``max_parallel`` unit.
            """
            nonlocal capacity
            if result["operation"] not in CONTROL_DISPATCH_KINDS:
                return False
            proposal_order.append(issue)
            if charge:
                acquire(issue)
                capacity -= 1
            return True
```

- [ ] **Step 4: Route the five lanes through it**

Replace exactly each tail below. Leave every line above it unchanged.

1. The first-remainder lane, after `if slot_withheld(issue): continue`. Keep
   its `custody_kind` filter:

   ```python
   # before
               result = apply_policy(issue, True)
               if result.get("custody_kind") != "remainder":
                   continue
               proposal_order.append(issue)
               acquire(issue)
               capacity -= 1
   # after
               result = apply_policy(issue, True)
               if result.get("custody_kind") == "remainder":
                   admit(issue, result)
   ```

2. The recover lane, after its two `analysis[issue]["changed"]` pre-checks:

   ```python
   # before
               apply_policy(issue, True)
               proposal_order.append(issue)
               if analysis[issue]["changed"]:
                   acquire(issue)
                   capacity -= 1
   # after
               admit(issue, apply_policy(issue, True), charge=analysis[issue]["changed"])
   ```

3. The resume lane, the retry branch and the spawn lane, each after its
   `if result["operation"] == "observe": raise WorkflowError(...)`. Delete the
   `contract` skip and the three queue-and-charge lines, and put one call at the
   same indentation as the deleted `if`:

   ```python
   # before (resume and spawn at 12 spaces; retry at 20)
               if result["operation"] == "contract":
                   continue
               proposal_order.append(issue)
               acquire(issue)
               capacity -= 1
   # after
               admit(issue, result)
   ```

- [ ] **Step 5: Verify**

```bash
set -euo pipefail
PYTHONPATH=python python3 -m unittest $T/test_delivery_workflow.py \
  -k live_remainder_with_a_free_slot -k stall_bound_remainder \
  -k suspended_remainder_with_a_free_slot -k contractless_public_outputs \
  -k contractless_retry_on_an_absent_path -k every_input_flag_reads_stdin 2>&1 \
  | grep -E '^(FAIL|ERROR):|KeyError|AssertionError|^Ran|^OK|^FAILED'
test "$(grep -c 'proposal_order.append(' $S/workflow-state.py)" = 2
test "$(grep -c 'if result\["operation"\] == "contract":' $S/workflow-state.py)" = 0
test "$(grep -cE '^ +admit\(issue, ' $S/workflow-state.py)" = 5
```

Expected: `Ran 6 tests`, `OK`, and each `test` exits 0. The last three tests
are the existing contract tests that pin `admit`'s membership filter. With the
filter removed, they fail on `KeyError: 'contract'` (D3).

```bash
set -euo pipefail
PYTHONPATH=python python3 -m unittest $T/test_workflow_state.py \
  $T/test_host_admission.py $T/test_admission_replay.py \
  $T/test_delivery_workflow.py $T/test_workflow_delivery.py 2>&1 \
  | grep -E '^(FAIL|ERROR):|^Ran|^OK|^FAILED'
```

Expected: `Ran 229 tests` and `OK`. That is the 226 at the base plus this task's
3. It takes about six minutes.

- [ ] **Step 6: Commit**

```bash
set -euo pipefail
git add $S/workflow-state.py $T/test_delivery_workflow.py
git commit -m "fix(workflow-state): queue only dispatches in control lanes (#190)" \
  -m "One nested admission step queues a planned result and charges it capacity only when its operation is a dispatch kind, so a live or stall-bound remainder no longer reaches the action loop's closed delta map." \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
