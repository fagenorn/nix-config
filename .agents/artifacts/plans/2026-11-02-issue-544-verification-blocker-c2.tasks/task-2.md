# Task 2: Ledger schema 11 and strict migration

**Files:**
- Modify: `python/agent_tools/attempt_identity.py` (`_MAX_SCHEMA_VERSION`, the `schema_refusal` docstring)
- Modify: `tests/test_attempt_identity.py` (`test_schema_refusal`)
- Modify: `python/agent_tools/attempt_store.py` (module docstring; version constants; `LockedRead` docstring; `_schema_ten` replaced; `locked_read`; `check_unlocked`; `_row_verdict`; the `migration_row` comment)
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (the `agent_tools` import; `SCHEMA_VERSION`; `STATE_FIELDS`, `LEGACY_STATE_FIELDS`, `ATTEMPT_FIELDS`, `LEGACY_ATTEMPT_FIELDS`, `SUSPENSION_DEFAULTS`; `validate_attempt`; `validate_state`; `new_run_state`; `reconcile_merged_attempt`, `stop_attempt`, `resume_attempt`; the `# Bind:` comment in `command_direct_owner`)
- Create: `home/common/agent-skills/tests/test_verification_suspension.py`
- Modify (fixtures, D13): `home/common/agent-skills/tests/test_workflow_state.py`, `home/common/agent-skills/tests/test_attempt_migration.py`, `home/common/agent-skills/tests/test_control_cutover.py`, `home/common/agent-skills/tests/test_attempt_custody.py`, `home/common/agent-skills/tests/test_delivery_workflow.py`, `home/common/agent-skills/tests/test_host_admission.py`, `home/common/agent-skills/tests/test_delivery_sealing.py`
- Modify: `justfile` (one line, `    home/common/agent-skills/tests/test_verification_suspension.py \`, right after `    home/common/agent-skills/tests/test_attempt_custody.py \`)
- Modify: `home/common/agent-skills/README.md` (three sentences of § Run identity and migrate)

**Interfaces:**
- Consumes: Task 1's `verification_blocker.validate_blockers(blockers, pointers)`, `upgrade_ten(document)` and `BlockerRefused`.
- Produces (Task 3 relies on these):
  - Every ledger a helper writes is schema 11: `verification_blockers` (the run's map, `{}` in a new run) and each attempt's `verification_blocker` (`None` in `SUSPENSION_DEFAULTS`, so `new_control_attempt` creates it `None`).
  - `validate_attempt(value, *, issue, expected_number, direct, schema_version: int)` enforces at 11 that the pointer is non-null exactly when the attempt is `suspended` with `blocked_on` `"verification"`; `validate_state` at 11 also runs `validate_blockers`, so a write that leaves the pair or a record inconsistent is refused before anything is written.
  - `reconcile_merged_attempt`, `stop_attempt` and `resume_attempt` set `verification_blocker` to `None` beside `blocked_on`.
  - `attempt_store.VERIFICATION_SCHEMA_VERSION = 11`, the store's current version.
  - The new module's `LedgerHarness(LifecycleHarness)` with `worktree(issue)`, `spawn_all(*issues)`, `migrate(*flags)` and `assert_locked_refusal(state, line)` (writes `state` as the ledger, expects `init-run --run-id` to exit 2 with exactly `workflow-state: <line>` and the `.superpowers` tree unchanged), and the constants `BASE_COMMIT`, `REPO`, `HELPER` and `T`.

**Invariants:**
- Schema 7 is still the shape of a legacy document before it is bound: `validate_state(..., schema_version=7)` checks `LEGACY_STATE_FIELDS` and `LEGACY_ATTEMPT_FIELDS`, neither holding a new member; only schemas 11 and 7 are validated (D5).
- The store's one 10 → 11 step is `upgrade_ten`, and its `BlockerRefused` is `LedgerRefused("invalid_state", <its line>)` (D9, D15). Schemas 8, 9 and 10 are bound, copied as 10, stepped, validated at 11 and returned with `changed` set; 8 keeps its launch plan and 8 and 9 their remainder plan, and 10 has neither. A ≤ 7 ledger is upgraded, planned and stepped before `mint_run`, so a refused step mints nothing. `check_unlocked` returns a ≤ 7 ledger as its schema-7 candidate, as before. `migrate` reports 8, 9 and 10 as `migrate`, 11 as `current` or `migrated`.
- Nothing writes a blocker record yet, and `verification` is not yet a cause, so every pointer stays `None` until Task 3; `validate_blockers` runs on `{}` for every existing ledger, and a hand-written pointer on any attempt is refused by every locked read, writing nothing (D19).
- The fixed base's helper refuses a schema-11 ledger as `unknown_schema` and writes nothing (#337 D10); there is no reverse step.

- [ ] **Step 1: Write the failing tests**

`tests/test_attempt_identity.py`, `test_schema_refusal`: the known versions become `(1, 7, 8, 9, 10, 11)` and the first refused document `{"schema_version": 12}`.

Create `home/common/agent-skills/tests/test_verification_suspension.py`:

```python
"""Ledger schema 11 and shared verification blockers (issue 544), through the CLI from source.

Run: just agent-workflow-tests
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .test_workflow_state import LifecycleHarness

# The delivery base: the schema-10 helper this change must not be read by (issue 544 D9).
BASE_COMMIT = "87d6065fc1749c0b7b6c427beb9b1d3051bc198d"
REPO = Path(__file__).resolve().parents[4]
HELPER = Path("home/common/agent-skills/scripts/workflow-state.py")
T = "2026-08-13T20:{:02d}:00Z".format


class LedgerHarness(LifecycleHarness):
    """Orchestrated attempts in a temporary ledger root, and the ledger at older schemas."""

    def worktree(self, issue):
        return str((self.root / f"wt-{issue}").resolve())

    def spawn_all(self, *issues):
        self.init_run()
        for issue in issues:
            self.spawn(issue=issue, worktree=self.worktree(issue))

    def migrate(self, *flags):
        completed = self.run_cli("migrate", "--repo-root", self.root, *flags)
        return json.loads(completed.stdout)["ledgers"]

    def assert_locked_refusal(self, state, line):
        """`state`, written as the ledger, is refused by a locked read with `line`; nothing
        under `.superpowers` changes."""
        self.write_state(state)
        before = self.tree_snapshot()
        done = self.run_cli("init-run", "--repo-root", self.root, "--run-id", self.run_id,
                            ok=False)
        self.assertEqual((done.returncode, done.stdout, done.stderr),
                         (2, "", f"workflow-state: {line}\n"))
        self.assertEqual(self.tree_snapshot(), before)


class SchemaElevenTest(LedgerHarness, unittest.TestCase):
    def test_a_new_ledger_is_schema_eleven_with_no_blockers(self):
        self.spawn_all(61)
        state = self.read_state()
        self.assertEqual((state["schema_version"], state["verification_blockers"]), (11, {}))
        self.assertIsNone(state["issues"]["61"]["attempts"][0]["verification_blocker"])

    def test_a_schema_ten_ledger_migrates_strictly(self):
        self.spawn_all(61)
        current = self.read_state()
        self.write_state(self._as_legacy(current, 10))
        before = self.tree_snapshot()
        self.assertEqual([(row["schema_version"], row["verdict"]) for row in self.migrate()],
                         [(10, "migrate")])
        self.assertEqual(self.tree_snapshot(), before)
        self.assertEqual([(row["schema_version"], row["verdict"])
                          for row in self.migrate("--apply")], [(11, "migrated")])
        self.assertEqual(self.read_state(), current)
        self.assertEqual([row["verdict"] for row in self.migrate()], ["current"])

    def test_a_schema_ten_ledger_holding_a_new_member_is_refused_unchanged(self):
        self.spawn_all(61)
        ten = self._as_legacy(self.read_state(), 10)
        pointed = json.loads(json.dumps(ten))
        pointed["issues"]["61"]["attempts"][0]["verification_blocker"] = None
        for label, document in (("blocker map", {**ten, "verification_blockers": {}}),
                                ("attempt pointer", pointed)):
            with self.subTest(member=label):
                self.write_state(document)
                before = self.tree_snapshot()
                (row,) = self.migrate("--apply")
                self.assertEqual((row["verdict"], row["reason"]), ("refused", "invalid_state"))
                done = self.run_cli("init-run", "--repo-root", self.root, "--run-id",
                                    self.run_id, ok=False)
                self.assertEqual(done.returncode, 2, done.stdout)
                self.assertIn("invalid_state", done.stderr)
                self.assertEqual(self.tree_snapshot(), before)


class PointerRuleTest(LedgerHarness, unittest.TestCase):
    """A pointer outside a verification suspension is refused, unchanged (issue 544 D5, D19)."""

    def test_a_pointer_outside_a_verification_suspension_is_refused(self):
        self.spawn_all(61, 62)
        self.suspend(issue=62, attempt=1, blocked_on="transport", now=T(5))
        good = self.read_state()
        for issue, label in ((61, "active"), (62, "suspended on transport")):
            with self.subTest(attempt=label):
                state = json.loads(json.dumps(good))
                state["issues"][str(issue)]["attempts"][0]["verification_blocker"] = (
                    "sha256:" + "0" * 64)
                self.assert_locked_refusal(state, "invalid attempt verification blocker")


class HelperGenerationTest(LedgerHarness, unittest.TestCase):
    """A helper older than the ledger's schema refuses it and writes nothing (#337 D10)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        found = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e",
                                f"{BASE_COMMIT}^{{commit}}"], capture_output=True)
        if found.returncode != 0:
            raise AssertionError(f"base commit {BASE_COMMIT} is missing; fetch it, do not skip")
        cls.base = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, cls.base, True)
        archive = subprocess.run(
            ["git", "-C", str(REPO), "archive", BASE_COMMIT, "python/agent_tools",
             str(HELPER.parent), "home/common/agent-skills/artifact-budget-policy.json"],
            capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(cls.base)], input=archive.stdout, check=True)

    def helper(self, generation, *argv):
        if generation == "head":
            return self.run_cli(*argv, ok=False)
        return subprocess.run(
            [sys.executable, str(self.base / HELPER), *map(str, argv)], capture_output=True,
            text=True, cwd=self.base, timeout=300,
            env={**self.cli_env, "PYTHONPATH": str(self.base / "python"),
                 "PYTHONDONTWRITEBYTECODE": "1"})

    def assert_refused_unchanged(self, generation):
        """Every ledger-reading command refuses `unknown_schema`; migrate reports it as a row."""
        control = self.root / "control-request.json"
        control.write_text(json.dumps(self.control_request(
            now=T(6), issues=[61], tracker=[self.tracker_fact(61)], worktrees=[])), "utf-8")
        direct = self.root / "direct-request.json"
        direct.write_text(json.dumps(self.direct_request(issue=61, now=T(6))), "utf-8")
        run = ("--repo-root", self.root, "--run-id", self.run_id)
        calls = {
            "check-launch": ("check-launch", *run, "--action-id", "61:1:1"),
            "suspend": ("suspend", *run, "--blocked-on", "transport", "--now", T(6),
                        "--action-id", "61:1:1"),
            "control": ("control", *run, "--request-file", control),
            "init-run": ("init-run", "--repo-root", self.root, "--run-id", self.run_id),
            "direct-owner": ("direct-owner", "--repo-root", self.root, "--request-file", direct),
            "migrate": ("migrate", "--repo-root", self.root),
            "migrate --apply": ("migrate", "--repo-root", self.root, "--apply"),
        }
        before = self.tree_snapshot()
        for name, argv in calls.items():
            with self.subTest(generation=generation, command=name):
                done = self.helper(generation, *argv)
                if name.startswith("migrate"):
                    (row,) = json.loads(done.stdout)["ledgers"]
                    self.assertEqual((done.returncode, row["verdict"], row["reason"]),
                                     (0, "refused", "unknown_schema"))
                else:
                    self.assertEqual(done.returncode, 2, done.stdout)
                    self.assertIn("unknown_schema", done.stderr)
                self.assertEqual(self.tree_snapshot(), before)

    def test_the_base_helper_refuses_a_schema_eleven_ledger(self):
        self.spawn_all(61)
        current = self.read_state()
        self.write_state(self._as_legacy(current, 10))
        before = self.tree_snapshot()
        done = self.helper("base", "migrate", "--repo-root", self.root)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([row["verdict"] for row in json.loads(done.stdout)["ledgers"]],
                         ["current"])
        self.assertEqual(self.tree_snapshot(), before)
        self.write_state(current)
        self.assert_refused_unchanged("base")

    def test_the_head_helper_refuses_schema_twelve(self):
        self.spawn_all(61)
        self.write_state({**self.read_state(), "schema_version": 12})
        self.assert_refused_unchanged("head")


if __name__ == "__main__":
    unittest.main()
```

Move the existing suites to schema 11 (D13). Each edit below is a pin of the current schema, a relabel to an older one, or a literal ledger; nothing else in those files changes:

- `test_workflow_state.py`: `LifecycleHarness._as_legacy` drops `verification_blockers` and every attempt's `verification_blocker` when `version < 11`, as its first step after setting the version (`pop(..., None)`, so a legacy input without them passes); `assert_bound` and its docstring say schema 11; `_legacy_finish_input` tests `stored["schema_version"] != 11` and its docstring says schema-11; the two literal expected states in `test_zero_sequence_direct_shaped_dispatcher_*` and the test before it gain `"verification_blockers": {}` and `"schema_version": 11`, and their `expected_attempt` gains `"verification_blocker": None`; every remaining `schema_version` pin of a written ledger moves from 10 to 11 (`assertEqual(state["schema_version"], 10)`, `write.call_args.args[2]["schema_version"]`, and the tuples `(10, None, 1, 0)`, `(10, (None, None, []))`, `(10, self.base)`).
- `test_attempt_migration.py`: the unknown-schema fixture `edit_ledger("orchestrate-90", schema_version=11)` becomes 12; the bound pins `(10, first["run_id"])`, `(10, "orchestrate-21-24-r2")` and `legacy["schema_version"], 10` become 11, and the comment `the schema-10 ledger` becomes `the schema-11 ledger`.
- `test_control_cutover.py`: the two pins after `migrate --apply` (`schema_version` 10, and `(10, "migrated")`) become 11. Its base helper (a schema-9 helper) is unchanged.
- `test_attempt_custody.py` (agent-skills): the six `self.read_state()["schema_version"], 10` pins become 11.
- `test_delivery_workflow.py`: every builder that relabels a `new_run_state`/`new_control_attempt` shape as an older schema also drops both members: `DeliveryAdmissionTest.legacy` pops `verification_blockers` and adds `"verification_blocker"` to the attempt fields it pops, and its version-1 branch pops the literal `("blocked_on", "suspend_phase", "stalled_resumes")` instead of iterating `SUSPENSION_DEFAULTS`, which now holds the pointer too; the schema-2 `legacy` in `HelperInputTest.test_every_input_flag_reads_stdin_and_refuses_relative_paths` and the schema-2 `state` in `ContractLifecycleTest.test_v1_owners_survive_the_migration_to_interface_two` pop `verification_blockers` and add `"verification_blocker"` to the attempt fields they pop; `ContractLifecycleTest.write_run` pops `verification_blockers` beside `transaction_id` and strips `verification_blocker` from every attempt it is given; `ContractLifecycleTest.test_contractless_retry_on_an_absent_path_asks_for_its_contract` strips `verification_blocker` from the `holder` attempt it adds to that schema-7 ledger; `ContractLifecycleTest.assert_bound` expects `schema_version=11`, `verification_blockers={}` and every attempt's `verification_blocker` `None`; and the three pins of a bound ledger (`write.call_args.args[2]["schema_version"]`, the `(10, ...)` tuple after it, and `json.loads(path.read_text())["schema_version"]`) become 11.
- `test_host_admission.py` and `test_delivery_sealing.py`: the one pin each becomes 11.

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_attempt_identity.py home/common/agent-skills/tests/test_verification_suspension.py 2>&1 | tail -4'`
Expected: `Ran 28 tests` and `FAILED (failures=13, errors=1)`: `test_schema_refusal` (11 is still refused); `test_a_new_ledger_is_schema_eleven_with_no_blockers` errors with `KeyError: 'verification_blockers'`; `test_a_schema_ten_ledger_migrates_strictly` (a schema-10 ledger is still `current`); both subtests of `test_a_schema_ten_ledger_holding_a_new_member_is_refused_unchanged` (`invalid workflow state schema`/`invalid attempt schema` rather than `invalid_state`); both subtests of `test_a_pointer_outside_a_verification_suspension_is_refused` (`invalid attempt schema` at schema 10 rather than the pointer rule's line); and the seven base-helper subtests (the ledger is still schema 10, which the base helper reads: a call succeeds or refuses for another reason, such as `direct-owner`'s orchestrated hold, and both `migrate` rows are `current`). `test_the_head_helper_refuses_schema_twelve` already passes, since no helper reads schema 12. The fixture edits are not red-tested alone: they fail only once the schema moves.

- [ ] **Step 3: Implement**

`python/agent_tools/attempt_identity.py`: `_MAX_SCHEMA_VERSION = 11`; the `schema_refusal` docstring says `1-11`.

`python/agent_tools/attempt_store.py` (D9, D15):
- Import `from agent_tools import verification_blocker as verification_rules`. After `CORE_STATE_SCHEMA_VERSION` add `VERIFICATION_SCHEMA_VERSION = 11  # the current version: the run's verification blockers`; the three older constants stay as step names.
- Module docstring: after the sentence ending `capacity gate.` add: "From schema 11 every older ledger also takes `agent_tools.verification_blocker.upgrade_ten`, the strict step that adds the run's verification blockers (issue 544 D9)." `LockedRead`'s docstring says schema 11, and `changed` is true for "a schema-10 or older document".
- Replace `_schema_ten` by `_schema_eleven(candidate) -> dict`, which returns `verification_rules.upgrade_ten(candidate)` and maps `BlockerRefused` to `LedgerRefused("invalid_state", str(error))`, and `_bound_candidate(document, identity, *, run_id, validate) -> tuple[dict, dict, dict]`: a deep copy of a schema 8, 9 or 10 `document` with `schema_version` 10, passed through `_schema_eleven` and `validate`; the launch plan is `plan_custody(validated)` only for a stored 8, and the remainder plan `delivery_rules.plan_remainder_migration(validated)` for a stored 8 or 9 and `{}` for 10.
- `locked_read`: schema 11 is read as current (`changed` false, no plans); 8, 9 and 10 go through `_bound_candidate` with `changed` set; a ≤ 7 ledger is upgraded and planned as before, then gets `schema_version` 10 and `_schema_eleven` before `candidate["transaction_id"] = mint_run(store, plan)`. The docstring says so ("stepped to schema 11"; "A refused ledger mints nothing" stays true).
- `check_unlocked`: 11 is validated as current; 8, 9 and 10 return `_bound_candidate(...)[0]`; ≤ 7 is unchanged. Docstring updated to these numbers.
- `_row_verdict`: the bound branch covers 8, 9, 10 and 11; 11 is validated directly and is `current` (or `migrated`), the others go through `_bound_candidate` and are `migrate`; any `StoreRefused` there, the step's `invalid_state` included, is the row's `invalid_state`. The `migration_row` comment reads `(schema 8 to 11)`.

`home/common/agent-skills/scripts/workflow-state.py` (D3, D5):
- `from agent_tools import attempt_observations, attempt_store, phase_budget, verification_blocker`; `SCHEMA_VERSION = 11`.
- `STATE_FIELDS` gains `"verification_blockers"`; `LEGACY_STATE_FIELDS = STATE_FIELDS - {"transaction_id", "verification_blockers"}` with its comment extended to "and stepped to schema 11 (issue 544)". `ATTEMPT_FIELDS` gains `"verification_blocker"`, and after it `LEGACY_ATTEMPT_FIELDS = ATTEMPT_FIELDS - {"verification_blocker"}`. `SUSPENSION_DEFAULTS` gains `"verification_blocker": None`.
- `validate_attempt` gains the keyword `schema_version: int` and checks `ATTEMPT_FIELDS` at `SCHEMA_VERSION`, else `LEGACY_ATTEMPT_FIELDS`. At `SCHEMA_VERSION`, after the suspension-cause check, it refuses `invalid attempt verification blocker` unless the pointer is non-null exactly when `state == "suspended"` and `blocked_on == "verification"`, and a non-null pointer is a `str`; with a comment that the pointer names the blocker the attempt is parked on and that R5, run by `validate_state` below, refuses any pointer that is not a record's id (issue 544 D5, D17).
- `validate_state` passes `schema_version=schema_version` to `validate_attempt`; at `SCHEMA_VERSION`, after the issues loop and before `validate_workers`, it builds `pointers = {(int(key), attempt["attempt"]): attempt["verification_blocker"]}` over every attempt and calls `verification_blocker.validate_blockers(value["verification_blockers"], pointers)`, mapping `BlockerRefused` to `WorkflowError(f"invalid verification blockers: {error}")`. Its docstring says "11, or 7 for a document not yet bound" and "at schema 11".
- In `command_direct_owner`, the comment `# Bind: a legacy ledger is committed as schema 10 at once, under its held lock.` says schema 11.
- `new_run_state` adds `"verification_blockers": {}`. `reconcile_merged_attempt`, `stop_attempt` and `resume_attempt` each set `attempt["verification_blocker"] = None` on the line after `attempt["blocked_on"] = None`.

`justfile`: the new module right after `    home/common/agent-skills/tests/test_attempt_custody.py \`.

`home/common/agent-skills/README.md`, § Run identity and migrate (one long line):
- After the sentence that ends "`migrate` keeps its inventory listing)." insert:

  ```text
  Schema 11 (issue 544) adds the run's `verification_blockers` map and each attempt's `verification_blocker` pointer: the 10 → 11 step composes after the earlier ones, starts both empty, refuses a schema-10 ledger that already holds either member as `invalid_state`, and is committed by the ledger's next locked write or by `migrate --apply`, like the others.
  ```
- Replace `is written as schema 10 by the same two routes, in one write: a schema-8 ledger takes its attempt-custody bind (next subsection) and the schema-10 bind together and is never stored at schema 9.` with `is written as schema 11 by the same two routes, in one write: a schema-8 ledger takes its attempt-custody bind (next subsection), the schema-10 bind and the 10 → 11 step together and is never stored at schema 9 or 10.`
- Replace `so the package-2 (schema-9) helper and every earlier one refuse a schema-10 ledger; there is no reverse migration or transform, so rollback means redeploying a helper that reads schema 10` with `so a schema-10 helper and every earlier one refuse a schema-11 ledger; there is no reverse migration or transform, so rollback means redeploying a helper that reads schema 11`.

- [ ] **Step 4: Verify**

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_attempt_identity.py tests/test_verification_blocker.py home/common/agent-skills/tests/test_verification_suspension.py 2>&1 | tail -3'`
Expected: `Ran 52 tests` and `OK` (22, 24 and 6 per module).

Run (timeout 1800 s; about 5 minutes): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_attempt_migration.py home/common/agent-skills/tests/test_attempt_custody.py home/common/agent-skills/tests/test_control_cutover.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_host_admission.py home/common/agent-skills/tests/test_delivery_sealing.py 2>&1 | tail -3'`
Expected: `Ran 500 tests` and `OK` (297, 27, 33, 20, 88, 28 and 7 per module).

Run: `grep -c '^SCHEMA_VERSION = 11$' home/common/agent-skills/scripts/workflow-state.py; grep -c '^VERIFICATION_SCHEMA_VERSION = 11 ' python/agent_tools/attempt_store.py; grep -c '^_MAX_SCHEMA_VERSION = 11$' python/agent_tools/attempt_identity.py`
Expected: `1`, `1`, `1` (a `0` and exit 1 means a constant did not move).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/attempt_identity.py tests/test_attempt_identity.py \
  python/agent_tools/attempt_store.py home/common/agent-skills/scripts/workflow-state.py \
  home/common/agent-skills/tests/test_verification_suspension.py \
  home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_attempt_migration.py \
  home/common/agent-skills/tests/test_control_cutover.py home/common/agent-skills/tests/test_attempt_custody.py \
  home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_host_admission.py \
  home/common/agent-skills/tests/test_delivery_sealing.py \
  justfile home/common/agent-skills/README.md
launch-commit … -- -m "feat(workflow-state): ledger schema 11 (issue 544)" -m "<session trailers>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"97558817180f2b9b622a166a5de82948fbc4c518","head":"d7a5942ffe24bcef52429308ba4b55b1277be686"}],"commit_subject_bytes":[64,64,64],"id":2,"records":[{"bounds":[{"added_lines":3,"boundary":"all","deleted_lines":3,"record_bytes":3072,"support":{"covers":["r2a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2a","last_task":2,"owner":2,"path":"python/agent_tools/attempt_identity.py"},{"bounds":[{"added_lines":3,"boundary":"all","deleted_lines":3,"record_bytes":2048,"support":{"covers":["r2b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2b","last_task":2,"owner":2,"path":"tests/test_attempt_identity.py"},{"bounds":[{"added_lines":62,"boundary":"all","deleted_lines":40,"record_bytes":18432,"support":{"covers":["r2c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2c","last_task":2,"owner":2,"path":"python/agent_tools/attempt_store.py"},{"bounds":[{"added_lines":48,"boundary":"all","deleted_lines":16,"record_bytes":21504,"support":{"covers":["r2d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2d","last_task":3,"owner":2,"path":"home/common/agent-skills/scripts/workflow-state.py"},{"bounds":[{"added_lines":230,"boundary":"all","deleted_lines":0,"record_bytes":11264,"support":{"covers":["r2e"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r2e","last_task":3,"owner":2,"path":"home/common/agent-skills/tests/test_verification_suspension.py"},{"bounds":[{"added_lines":28,"boundary":"all","deleted_lines":20,"record_bytes":21504,"support":{"covers":["r2f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2f","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_workflow_state.py"},{"bounds":[{"added_lines":7,"boundary":"all","deleted_lines":7,"record_bytes":9216,"support":{"covers":["r2g"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2g","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_attempt_migration.py"},{"bounds":[{"added_lines":3,"boundary":"all","deleted_lines":3,"record_bytes":3584,"support":{"covers":["r2h"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2h","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_control_cutover.py"},{"bounds":[{"added_lines":8,"boundary":"all","deleted_lines":8,"record_bytes":10240,"support":{"covers":["r2i"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2i","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_attempt_custody.py"},{"bounds":[{"added_lines":30,"boundary":"all","deleted_lines":15,"record_bytes":16384,"support":{"covers":["r2j"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2j","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_delivery_workflow.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":2048,"support":{"covers":["r2k"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2k","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_host_admission.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":2048,"support":{"covers":["r2l"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2l","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_delivery_sealing.py"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":0,"record_bytes":2048,"support":{"covers":["r2m"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2m","last_task":2,"owner":2,"path":"justfile"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":18432,"support":{"covers":["r2n"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2n","last_task":3,"owner":2,"path":"home/common/agent-skills/README.md"}]}}
```
