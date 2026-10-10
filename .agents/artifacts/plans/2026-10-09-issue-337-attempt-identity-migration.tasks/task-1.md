# Task 1: Core `lookup` and the pure `attempt_identity` module

**Files:**
- Modify: `python/agent_tools/transaction_core.py` (add `TransactionStore.lookup`; the module docstring's "No command and no caller until #125" sentence stays until Task 2 makes `workflow-state` a caller)
- Create: `python/agent_tools/attempt_identity.py`
- Modify: `tests/test_transaction_core.py` (one new `LookupTest` class)
- Create: `tests/test_attempt_identity.py`
- Modify: `justfile` (add `tests/test_attempt_identity.py` to `agent-workflow-tests`, right after `tests/test_transaction_core.py`)

**Interfaces:**
- Consumes: `transaction_core._read_index(root, key)`, `transaction_storage.is_id` (nothing else).
- Produces (later tasks import exactly these names):
  - `TransactionStore.lookup(self, creation_key: str) -> str | None` — the id the key's index entry names, else `None`. A `creation_key` that is not a non-empty `str` is `StateInvalid`; a malformed entry is `StateInvalid` (same as `_read_index`). Takes no lock, creates nothing (not even `creation-keys/`), writes nothing (D2).
  - In `agent_tools.attempt_identity`:
    - constants `SUBJECT_SCHEMA = "attempt-run/v1"`, `REPORT_SCHEMA = "attempt-migration-report/v1"`, `AUTHORITY_CLASS = "attempt-run"`, `LEGACY_DIALECTS = ("direct", "orchestrate", "issues", "run")`, `REFUSAL_REASONS = ("unknown_schema", "invalid_state", "unknown_dialect", "ambiguous_lineage", "location_mismatch")`, `VERDICTS = ("current", "migrate", "migrated", "refused")`, `REPORT_ROW_FIELDS = ("ledger", "run_id", "schema_version", "dialect", "alias", "issues", "prior_run", "prior_transaction_id", "transaction_id", "verdict", "reason")`.
    - `class MigrationRefused(ValueError)` with attribute `reason` (one of `REFUSAL_REASONS`); `str(error)` is `"<reason>: <detail>"`.
    - `@dataclass(frozen=True) class RunIdentity: kind: str; issue: int | None; sequence: int | None` (`kind` is `"direct"` or `"orchestrated"`; `issue`/`sequence` set only for direct). Property `direct -> bool`.
    - `@dataclass(frozen=True) class RunPlan: creation_key: str; subject: Mapping[str, Any]` (subject held as a `MappingProxyType` over a private copy; `plan.subject_json()` returns a fresh plain `dict`).
    - `classify(run_id: object) -> str | None` — one of `LEGACY_DIALECTS`, `"core"`, or `None`.
    - `legacy_alias(run_id: str) -> dict` — `{"dialect", "run_id", "issues", "date", "retry"}`; raises `MigrationRefused("unknown_dialect")` for anything not a legacy dialect (including `core`).
    - `legacy_identity(run_id: str) -> RunIdentity` — from the alias (direct → issue and sequence from the id); raises like `legacy_alias`.
    - `direct_key(issue: int, sequence: int) -> str`, `legacy_key(run_id: str) -> str`, `run_key(caller_key: str) -> str` (`ValueError` unless `caller_key` fullmatches `[A-Za-z0-9][A-Za-z0-9._:-]{0,127}`).
    - `prior_run_violation(identity: RunIdentity, prior_run: object, *, run_id: str) -> str | None` — the schema-8 lineage rule.
    - `schema_refusal(document: object) -> str | None` — `"unknown_schema"` unless `document` is a dict whose `schema_version` is an `int` (not `bool`) in 1–8.
    - `plan_migration(document: dict) -> RunPlan` — the pure 7 → 8 plan over a validated schema-7 document.
    - `minted_plan(*, identity: RunIdentity, prior_run: str | None, caller_key: str | None) -> RunPlan` — new runs (alias `null`).
    - `subject_violation(subject: object) -> str | None`, `identity_of(subject: Mapping) -> RunIdentity`, `subject_handle(subject: Mapping, transaction_id: str) -> str`.
    - `creation_arguments(plan: RunPlan) -> dict` — `{"concurrency_keys": ["attempt-run:" + key], "proof": {"units": [], "obligations": [], "collectors": {}}, "recovery": {"effects": {}, "units": []}, "authority_class": "attempt-run"}`, fresh objects each call (D6).
    - `report(mode: str, rows: list[dict]) -> dict` — `{"schema", "mode", "ledgers", "counts"}`; rows sorted by `ledger`; `counts` has all four verdict keys; `ValueError` on an unknown mode (`dry_run`/`apply`), a row whose key set is not `REPORT_ROW_FIELDS`, or an unknown verdict/reason.

**Invariants:**
- Every function in `attempt_identity` is pure: no file, directory, clock or environment read (D3, D7). The module imports only the standard library and `agent_tools.transaction_storage.is_id`.
- Grammar is full-string; exactly the spec's table (spec § Dialect grammar): issue `[1-9][0-9]{0,6}`; date = 8 digits forming a valid calendar date (`datetime.date(y, m, d)` succeeds); retry `-r[1-9][0-9]*`; direct sequence 6 digits with value ≥ 1.
- `plan_migration` refuses with `unknown_dialect` when `run_id` is unknown or `core` (schema ≤ 7); with `ambiguous_lineage` when an orchestrated-dialect run records a non-null `prior_run`, when a direct run's `issues` keys are not exactly `{str(issue)}`, or when a direct `prior_run` is not a `direct` id for the same issue with a lower sequence. A `-r<n>` suffix only sets `alias.retry`; it never sets `prior_run`.
- Subject (closed, exactly these keys): `{"schema": "attempt-run/v1", "kind", "issue", "sequence", "prior_run", "alias"}`. Direct legacy key `attempt-run/v1:direct:<issue>:<sequence>` (sequence as a plain int, no padding); non-direct legacy key `attempt-run/v1:legacy:<run_id>`; new orchestrated key `attempt-run/v1:run:<caller key>`.
- `prior_run_violation`: orchestrated → violation unless `None`; direct → `None` is fine, a `core` id is fine, a `direct`-dialect id is fine only for the same issue with a lower sequence than `identity.sequence`; anything else, or `prior_run == run_id`, is a violation (string message).
- `subject_handle` returns `alias["run_id"]` when `alias` is not null, else `transaction_id`.

- [ ] **Step 1: Write the failing tests**

`tests/test_attempt_identity.py`:

```python
"""Attempt run identity: grammar, plan, subject and report (#337 D1-D3, D6, D7).

Run: just agent-workflow-tests
"""

import hashlib
import tempfile
import unittest
from pathlib import Path

from agent_tools import attempt_identity as ai
from agent_tools.transaction_core import StateInvalid, TransactionStore

CORE_ID = "rel_0190f0e0-0000-7000-8000-000000000000"


def schema7(run_id, *, issues=("41",), prior_run=None):
    return {"schema_version": 7, "run_id": run_id, "prior_run": prior_run,
            "issues": {key: {} for key in issues}}


class GrammarTest(unittest.TestCase):
    def test_each_dialect_classifies_and_aliases_exactly(self):
        cases = {
            "direct-100-000003": ("direct", [100], None, None),
            "orchestrate-21-24-r2": ("orchestrate", [21, 24], None, 2),
            "issues-29-30-20260817-r2": ("issues", [29, 30], "20260817", 2),
            "issues-29-30": ("issues", [29, 30], None, None),
            "run-20261009-337-338-339": ("run", [337, 338, 339], "20261009", None),
        }
        for run_id, (dialect, issues, date, retry) in cases.items():
            with self.subTest(run_id=run_id):
                self.assertEqual(ai.classify(run_id), dialect)
                self.assertEqual(ai.legacy_alias(run_id), {
                    "dialect": dialect, "run_id": run_id, "issues": issues,
                    "date": date, "retry": retry})
        self.assertEqual(ai.classify(CORE_ID), "core")

    def test_anything_else_is_unknown_dialect(self):
        for run_id in ("issue-14-test", "replay", "direct-41-000000", "direct-41-1",
                       "orchestrate", "orchestrate-21-r0", "issues-12345678",
                       "run-20261399-337", "run-20261009", "orchestrate-021",
                       "Orchestrate-21", CORE_ID, "rel_not-a-uuid", 7, None):
            with self.subTest(run_id=run_id):
                if run_id != CORE_ID:
                    self.assertIsNone(ai.classify(run_id))
                if isinstance(run_id, str):
                    with self.assertRaises(ai.MigrationRefused) as caught:
                        ai.legacy_alias(run_id)
                    self.assertEqual(caught.exception.reason, "unknown_dialect")

    def test_keys(self):
        self.assertEqual(ai.direct_key(41, 2), "attempt-run/v1:direct:41:2")
        self.assertEqual(ai.legacy_key("run-20261009-337"),
                         "attempt-run/v1:legacy:run-20261009-337")
        self.assertEqual(ai.run_key("orchestrate-issues:20261010:337-338"),
                         "attempt-run/v1:run:orchestrate-issues:20261010:337-338")
        for bad in ("", "-x", "a/b", "a b", "x" * 129):
            with self.subTest(key=bad), self.assertRaises(ValueError):
                ai.run_key(bad)


class PlanTest(unittest.TestCase):
    def test_direct_plan_keeps_recorded_lineage(self):
        plan = ai.plan_migration(schema7("direct-41-000002", prior_run="direct-41-000001"))
        self.assertEqual(plan.creation_key, "attempt-run/v1:direct:41:2")
        self.assertEqual(plan.subject_json(), {
            "schema": "attempt-run/v1", "kind": "direct", "issue": 41, "sequence": 2,
            "prior_run": "direct-41-000001", "alias": ai.legacy_alias("direct-41-000002")})

    def test_grouped_run_records_its_name_not_membership(self):
        plan = ai.plan_migration(schema7("run-20261009-337-338-339", issues=("337",)))
        self.assertEqual(plan.creation_key, "attempt-run/v1:legacy:run-20261009-337-338-339")
        subject = plan.subject_json()
        self.assertEqual((subject["kind"], subject["issue"], subject["prior_run"]),
                         ("orchestrated", None, None))
        self.assertEqual(subject["alias"]["issues"], [337, 338, 339])
        self.assertNotIn("issues", subject)

    def test_retry_suffix_links_nothing(self):
        subject = ai.plan_migration(schema7("orchestrate-21-24-r2", issues=())).subject_json()
        self.assertEqual((subject["prior_run"], subject["alias"]["retry"]), (None, 2))

    def test_refusals_carry_closed_reasons(self):
        cases = {
            "unknown_dialect": [schema7("issue-14-test"), schema7(CORE_ID)],
            "ambiguous_lineage": [
                schema7("orchestrate-21-24", prior_run="orchestrate-21"),
                schema7("direct-41-000002", issues=("41", "42")),
                schema7("direct-41-000002", issues=()),
                schema7("direct-41-000002", prior_run="direct-42-000001"),
                schema7("direct-41-000002", prior_run="direct-41-000002"),
                schema7("direct-41-000002", prior_run="direct-41-000003"),
                schema7("direct-41-000002", prior_run="orchestrate-41")],
        }
        for reason, documents in cases.items():
            for document in documents:
                with self.subTest(reason=reason, document=document), \
                        self.assertRaises(ai.MigrationRefused) as caught:
                    ai.plan_migration(document)
                self.assertEqual(caught.exception.reason, reason)
                self.assertIn(caught.exception.reason, ai.REFUSAL_REASONS)

    def test_schema_refusal(self):
        for version in (1, 7, 8):
            self.assertIsNone(ai.schema_refusal({"schema_version": version}))
        for document in ({"schema_version": 9}, {"schema_version": 0},
                         {"schema_version": True}, {"schema_version": "7"}, {}, [], None):
            with self.subTest(document=document):
                self.assertEqual(ai.schema_refusal(document), "unknown_schema")

    def test_plans_are_immutable_and_deterministic(self):
        document = schema7("direct-41-000001")
        first, second = ai.plan_migration(document), ai.plan_migration(document)
        self.assertEqual(first, second)
        first.subject_json()["kind"] = "x"
        self.assertEqual(first.subject["kind"], "direct")
        with self.assertRaises(TypeError):
            first.subject["kind"] = "x"


class SubjectTest(unittest.TestCase):
    def test_minted_subjects_and_handles(self):
        direct = ai.minted_plan(identity=ai.RunIdentity("direct", 41, 3),
                                prior_run="direct-41-000002", caller_key=None)
        self.assertEqual(direct.creation_key, "attempt-run/v1:direct:41:3")
        self.assertIsNone(direct.subject["alias"])
        orchestrated = ai.minted_plan(identity=ai.RunIdentity("orchestrated", None, None),
                                      prior_run=None, caller_key="k1")
        self.assertEqual(orchestrated.creation_key, "attempt-run/v1:run:k1")
        for plan in (direct, orchestrated):
            self.assertIsNone(ai.subject_violation(plan.subject_json()))
        self.assertEqual(ai.subject_handle(direct.subject, CORE_ID), CORE_ID)
        legacy = ai.plan_migration(schema7("direct-41-000001"))
        self.assertEqual(ai.subject_handle(legacy.subject, CORE_ID), "direct-41-000001")
        self.assertEqual(ai.identity_of(legacy.subject), ai.RunIdentity("direct", 41, 1))
        self.assertIsNotNone(ai.subject_violation({**legacy.subject_json(), "extra": 1}))

    def test_prior_run_rule(self):
        direct = ai.RunIdentity("direct", 41, 3)
        for prior in (None, CORE_ID, "direct-41-000002"):
            self.assertIsNone(ai.prior_run_violation(direct, prior, run_id=CORE_ID))
        for prior in ("direct-41-000003", "direct-40-000001", "orchestrate-41", 5):
            with self.subTest(prior=prior):
                self.assertIsNotNone(ai.prior_run_violation(direct, prior, run_id="x"))
        # A run cannot precede itself.
        self.assertIsNotNone(ai.prior_run_violation(direct, CORE_ID, run_id=CORE_ID))
        orchestrated = ai.RunIdentity("orchestrated", None, None)
        self.assertIsNone(ai.prior_run_violation(orchestrated, None, run_id="x"))
        self.assertIsNotNone(ai.prior_run_violation(orchestrated, "direct-41-000001", run_id="x"))

    def test_creation_arguments_are_the_inert_ones(self):
        plan = ai.plan_migration(schema7("direct-41-000001"))
        arguments = ai.creation_arguments(plan)
        self.assertEqual(arguments, {
            "concurrency_keys": ["attempt-run:attempt-run/v1:direct:41:1"],
            "proof": {"units": [], "obligations": [], "collectors": {}},
            "recovery": {"effects": {}, "units": []}, "authority_class": "attempt-run"})
        arguments["proof"]["units"].append(1)
        self.assertEqual(ai.creation_arguments(plan)["proof"]["units"], [])


class ReportTest(unittest.TestCase):
    def row(self, ledger, verdict, reason=None):
        return {**{field: None for field in ai.REPORT_ROW_FIELDS},
                "ledger": ledger, "verdict": verdict, "reason": reason}

    def test_rows_sorted_and_counted(self):
        value = ai.report("dry_run", [self.row("b", "migrate"),
                                      self.row("a", "refused", "unknown_dialect")])
        self.assertEqual(value["schema"], "attempt-migration-report/v1")
        self.assertEqual([row["ledger"] for row in value["ledgers"]], ["a", "b"])
        self.assertEqual(value["counts"],
                         {"current": 0, "migrate": 1, "migrated": 0, "refused": 1})

    def test_malformed_input_is_refused(self):
        for mode, rows in (("other", []), ("apply", [{"ledger": "a"}]),
                           ("apply", [self.row("a", "maybe")]),
                           ("apply", [self.row("a", "refused", "because")])):
            with self.subTest(mode=mode, rows=rows), self.assertRaises(ValueError):
                ai.report(mode, rows)


class StoreRoundTripTest(unittest.TestCase):
    def test_a_created_run_transaction_is_found_by_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TransactionStore(Path(tmp))
            plan = ai.plan_migration(schema7("direct-41-000001"))
            created = store.create(plan.creation_key, plan.subject_json(),
                                   **ai.creation_arguments(plan))
            self.assertEqual(store.lookup(plan.creation_key), created.transaction_id)
            self.assertEqual(created.state, "created")
```

Add to `tests/test_transaction_core.py`:

```python
class LookupTest(StoreCase):
    def test_lookup_reads_the_index_and_writes_nothing(self):
        self.assertIsNone(self.store.lookup("demo:none"))
        self.assertEqual(self.tree(), [])
        created = self.store.create("demo:a", SUBJECT, concurrency_keys=KEYS,
                                    proof=EMPTY_PROOF, recovery=EMPTY_RECOVERY,
                                    authority_class=AUTHORITY)
        before = {path: (self.root / path).read_bytes() if (self.root / path).is_file()
                  else None for path in self.tree()}
        self.assertEqual(self.store.lookup("demo:a"), created.transaction_id)
        self.assertIsNone(self.store.lookup("demo:b"))
        self.assertEqual({path: (self.root / path).read_bytes() if (self.root / path).is_file()
                          else None for path in self.tree()}, before)

    def test_a_bad_key_or_entry_is_state_invalid(self):
        for key in ("", None, 7):
            with self.subTest(key=key), self.assertRaises(StateInvalid):
                self.store.lookup(key)
        self.store.create("demo:a", SUBJECT, concurrency_keys=KEYS, proof=EMPTY_PROOF,
                          recovery=EMPTY_RECOVERY, authority_class=AUTHORITY)
        self.index_path("demo:a").write_text("{}")
        with self.assertRaises(StateInvalid):
            self.store.lookup("demo:a")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_attempt_identity.py tests/test_transaction_core.py -k Lookup -k Grammar -k Plan -k Subject -k Report -k StoreRoundTrip`
Expected: errors — `No module named 'agent_tools.attempt_identity'` and `'TransactionStore' object has no attribute 'lookup'`.

- [ ] **Step 3: Write the minimal implementation**

`lookup`: `if type(creation_key) is not str or not creation_key: raise StateInvalid(...)`, then `return _read_index(self.root, creation_key)`. Docstring: "The id `creation_key`'s index entry names, or None; reads the index as `create` does and writes, creates and locks nothing (#337 D2)."

`attempt_identity`: one compiled regex per dialect (prefixes are disjoint, so at most one matches); `classify` returns `"core"` when `is_id(run_id)`. `plan_migration` takes `document["run_id"]`, `document["issues"]`, `document["prior_run"]` only — never a path. Subject construction is the one place that builds the closed dict; `subject_violation` checks the exact key set, the schema literal, the kind, int/null types per kind, and (when `alias` is not null) that `alias == legacy_alias(alias["run_id"])`. `report` validates rows against `REPORT_ROW_FIELDS`, `VERDICTS`, `REFUSAL_REASONS ∪ {None}` and returns plain data (rendering is the caller's). Module docstring states it is the pure half of #337's run identity: grammar, plan, subject and report, and that `workflow-state` owns every effect.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_attempt_identity.py tests/test_transaction_core.py tests/test_transaction_core_sweep.py`
Expected: OK, no failures. Then `grep -n "tests/test_attempt_identity.py" justfile` prints one line inside `agent-workflow-tests`.

- [ ] **Step 5: Commit**

`git add python/agent_tools/transaction_core.py python/agent_tools/attempt_identity.py tests/test_transaction_core.py tests/test_attempt_identity.py justfile`, then `launch-commit … -- -m "feat(core): attempt run identity module and read-only lookup (#337)"` with the session trailers.
