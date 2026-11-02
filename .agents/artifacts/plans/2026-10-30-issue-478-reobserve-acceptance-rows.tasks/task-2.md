# Task 2: Criteria cases: re-observed records close or hold through the engine

Spec § Test seams item 1. Rests on D9. After this task, `ShipDeliveryTest.deliver` takes the acceptance state instead of a boolean. Two issue-478 cases drive `acceptance-record reobserve` from source against a record in the harness root and finish delivery through the real compiler, validator and engine. In the first, a CI-pending `code` row observed green closes the issue. In the second, a pending `human` row still holds it.

**Files:**
- Modify: `home/common/agent-skills/tests/test_ship_delivery.py`

**Interfaces:**
- Consumes: Task 1's CLI, run as `[sys.executable, "-m", "agent_tools.acceptance_record", "reobserve", "--record", <path>, "--head", <sha>, "--checks", <file>, "--row", <ACn>...]` with `cwd` the record's root. It prints `{"acceptance_state": ..., "changed": [...]}` on exit 0. It exits 2 with empty stdout when a `--row` names a `human` row.
- Consumes from the harness: `self.root`, `self.runtime`, `self.env`, `HELD_RECORD` (`.claude/plans/2026-09-21-issue-171.acceptance.md`), `self.state_path`, and the selection head `"a" * 40` that `selected()` installs.
- Produces: `deliver(self, *, acceptance_state="met", remainder=False) -> dict`. It holds exactly when `acceptance_state` is `"unmet"` or `"human_pending"`, carries that value into the `tracker_held` facts, and otherwise closes through `tracker_closed`. It returns the stored issue, `json.loads(self.state_path.read_text())["issues"]["171"]`.

**Invariants:**
- The existing hold case now passes `acceptance_state="unmet"`, the close case passes nothing (`"met"`) and the remainder case is unchanged. All ten existing tests still pass.
- Each new case's close-or-hold comes from the helper's printed `acceptance_state`, never a literal.
- The CI-pending contrast (`Nix Eval` `pending`) leaves the record byte-identical and prints `unmet` with `changed: []`: the hold that the handoff value gives today.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_ship_delivery.py`, add these module constants after the `from .test_delivery_workflow import (...)` block, separated by one blank line before and two before `class ShipDeliveryTest`:

```python
# Issue 478: an acceptance record as sdd writes it, for ship's re-observation step.
RECORD_TOP = ("# Acceptance record — issue 171\n\n"
              "| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |\n"
              "|----|-----------|------|------------------|----------|--------|------------|---------|\n")
SUITE_MET = ("| AC1 | the suite passes | code | `just agent-workflow-tests` "
             "| in final verification | 1111111 | host mbp | met |\n")
CI_PENDING = ("| AC2 | CI `Nix Eval` green | code | `just build`; CI `Nix Eval` green on the PR "
              "| just build: exit 0 at 1111111 | 1111111 | host mbp | unverified |\n")
HUMAN_PENDING = ("| AC2 | the user confirms the demo | human | the user reads the hold comment "
                 "| — | 1111111 | — | human_pending |\n")
CHECK_LINK = "https://github.com/fagenorn/nix-config/actions/runs/1/job/1"
```

Change `test_complete_delivery_and_hold_use_engine_accepted_payloads`'s body to `self.deliver(acceptance_state="unmet")`. Insert these methods directly before `test_complete_delivery_and_hold_use_engine_accepted_payloads`, one blank line between methods:

```python
    def tracker_outcome(self, issue):
        """The observation that satisfied the issue's tracker_closed postcondition."""
        delivery = issue["delivery"]
        observed = delivery["postconditions"]["tracker_closed"]["observation_id"]
        return next(item for item in delivery["delivery_observations"] if item["id"] == observed)

    def write_record(self, *rows):
        path = self.root / HELD_RECORD
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(RECORD_TOP + "".join(rows), encoding="utf-8")
        return path, path.read_bytes()

    def reobserve(self, buckets, *targets):
        """Issue 478: ship's re-observation, from source, at the selected head."""
        checks = self.runtime / "required-checks.json"
        checks.write_text(json.dumps([{"name": name, "bucket": bucket, "link": CHECK_LINK}
                                      for name, bucket in buckets]))
        argv = [sys.executable, "-m", "agent_tools.acceptance_record", "reobserve",
                "--record", HELD_RECORD, "--head", "a" * 40, "--checks", str(checks)]
        for target in targets:
            argv += ["--row", target]
        return subprocess.run(argv, cwd=self.root, env=self.env, capture_output=True,
                              text=True, check=False, timeout=60)

    def test_a_ci_pending_code_row_observed_green_closes_the_issue(self):
        # Issue 478 AC1: the handoff's `unmet` held this issue; the re-observed record closes it.
        path, before = self.write_record(SUITE_MET, CI_PENDING)
        pending = self.reobserve([("Nix Eval", "pending"), ("Instruction Budget", "pass")], "AC2")
        self.assertEqual((pending.returncode, pending.stderr), (0, ""))
        self.assertEqual(json.loads(pending.stdout), {"acceptance_state": "unmet", "changed": []})
        self.assertEqual(path.read_bytes(), before)
        green = self.reobserve([("Nix Eval", "pass"), ("Instruction Budget", "pass")], "AC2")
        self.assertEqual((green.returncode, green.stderr), (0, ""))
        answer = json.loads(green.stdout)
        self.assertEqual(answer, {"acceptance_state": "met", "changed": ["AC2"]})
        self.assertEqual(path.read_text(encoding="utf-8"), RECORD_TOP + SUITE_MET + (
            "| AC2 | CI `Nix Eval` green | code | `just build`; CI `Nix Eval` green on the PR "
            "| just build: exit 0 at 1111111; ship re-observed Nix Eval: pass at aaaaaaa "
            f"{CHECK_LINK} | {'a' * 40} | host mbp | met |\n"))
        issue = self.deliver(acceptance_state=answer["acceptance_state"])
        self.assertEqual(self.tracker_outcome(issue)["observation_kind"], "tracker_closed")
        self.assertIs(issue["attempts"][-1]["result"]["issue_closed"], True)

    def test_a_pending_human_row_still_holds_the_issue(self):
        # Issue 478 AC2: re-observation never grades a human row, so the issue holds.
        ci_row = CI_PENDING.replace("| AC2 |", "| AC1 |")
        path, before = self.write_record(ci_row, HUMAN_PENDING)
        refused = self.reobserve([("Nix Eval", "pass")], "AC2")
        self.assertEqual((refused.returncode, refused.stdout), (2, ""))
        self.assertEqual(path.read_bytes(), before)
        done = self.reobserve([("Nix Eval", "pass")], "AC1")
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        answer = json.loads(done.stdout)
        self.assertEqual(answer, {"acceptance_state": "human_pending", "changed": ["AC1"]})
        issue = self.deliver(acceptance_state=answer["acceptance_state"])
        held = self.tracker_outcome(issue)
        self.assertEqual(held["observation_kind"], "tracker_held")
        self.assertEqual((held["subject"]["label"], held["subject"]["acceptance_state"],
                          held["subject"]["record_path"]),
                         ("needs-verification", "human_pending", HELD_RECORD))
        self.assertIs(issue["attempts"][-1]["result"]["issue_closed"], False)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_ship_delivery.py 2>&1 | grep -E "^(Ran|OK|FAILED|TypeError)"'`
Expected: `Ran 12 tests`, `FAILED (errors=3)`. Each of the two new cases and the hold case raises `TypeError: ShipDeliveryTest.deliver() got an unexpected keyword argument 'acceptance_state'`. The new cases reach `deliver` only after their helper assertions pass.

- [ ] **Step 3: Write the minimal implementation**

Change `deliver`'s signature and first lines to:

```python
    def deliver(self, *, acceptance_state="met", remainder=False):
        """Merge, then close or hold per `acceptance_state`; returns the stored issue."""
        hold = acceptance_state in ("unmet", "human_pending")
        self.selected()
```

In its `tracker_held` observation, replace `acceptance_state="unmet"` with `acceptance_state=acceptance_state`. End the method with `return issue`, after the `if remainder: ... else: ...` block. Nothing else in the method changes.

- [ ] **Step 4: Verify**

Run the Step 2 command.
Expected: `Ran 12 tests`, `OK`.

Run (timeout 60 s): `bash -c 'set -e; F=home/common/agent-skills/tests/test_ship_delivery.py; if grep -n "hold=True\|hold=False\|acceptance_state=\"unmet\", observation_identity" "$F"; then exit 1; fi; test "$(grep -c "agent_tools.acceptance_record" "$F")" = 1'`
Expected: exit 0. At the start commit it exits 1, printing the `hold=False` signature line, the `hold=True` call and the hard-coded `acceptance_state="unmet"` observation line.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_ship_delivery.py
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "test(ship-delivery): re-observed records close or hold through the engine (issue 478)" -m "<trailers>"
```
