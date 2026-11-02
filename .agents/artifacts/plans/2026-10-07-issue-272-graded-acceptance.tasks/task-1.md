# Task 1: `acceptance_state` on the sdd report and the legacy handoff

Lane: full (a report-boundary schema, which is a public contract). Decisions:
per D8, D9 and D11 of the spec's ledger. Read the spec's "`acceptance_state`
pairing (artifact-budget)" table first. This task implements every sdd row and
the legacy ship-handoff rows.

**Files:**
- Modify: `home/common/agent-skills/scripts/artifact_budget.py`
- Test: `home/common/agent-skills/tests/test_artifact_budget.py`

**Interfaces:**
- Consumes: the existing `validate_sdd_report(value, notes_max_characters)`
  and `validate_ship_handoff_report(value, notes_max_characters)` in
  `artifact_budget.py`, and the test helpers `ArtifactBudgetCliTest.make_sdd`,
  `.lifecycle`, `.full` and `.run_validate`.
- Produces (Task 2 relies on these exact names):
  - `ACCEPTANCE_STATES: frozenset[str]`, a module constant equal to
    `{"met", "unmet", "human_pending", "not_applicable"}`.
  - `acceptance_pairs_with_review(review_state: object, acceptance_state: object) -> bool`,
    the one home of the ship-handoff pairing. It is true exactly for
    `clean` → {`met`, `human_pending`, `not_applicable`}, `residuals` → any
    member of `ACCEPTANCE_STATES`, and `unknown` → {`not_applicable`}. It is
    false for every other value, including a non-string or unhashable one
    (per D11).

**Invariants:**
- `acceptance_state` is a required key of the sdd report and the legacy
  handoff. Its absence, or any value outside `ACCEPTANCE_STATES`, exits 2 with
  empty stdout and the stderr line `artifact-budget: invalid report`.
- sdd `complete`/`clean` accepts only `met`, `human_pending` and
  `not_applicable`.
- sdd `residuals`/`residuals` accepts any value, but `unmet` also requires
  `conformance_verdict: findings`.
- sdd `failed`/`unknown` with null SHAs, or with SHAs and
  `conformance_verdict: not_run`, accepts only `not_applicable`. With SHAs and
  a graded conformance axis (`clean` or `findings`) it accepts any value.
- Every report the matrices accepted before still validates once it carries
  `acceptance_state: "not_applicable"`, and every report they rejected is
  still rejected.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_artifact_budget.py`:

1. Below the `import artifact_budget` line, add the module constant:

```python
# The closed acceptance_state set (#272 D8), spelled out so the test can fail.
ACCEPTANCE = ("met", "unmet", "human_pending", "not_applicable")
```

2. Give `make_sdd` a keyword parameter, and emit the key:

```python
    def make_sdd(self, state, review, conformance, correctness, verification,
                 base, head, detail_state, report_path, acceptance="not_applicable"):
        notes = f"details: {report_path}" if report_path else "no durable detail"
        return {"state": state, "review_state": review,
                "conformance_verdict": conformance, "correctness_verdict": correctness,
                "verification_state": verification, "base_sha": base, "head_sha": head,
                "acceptance_state": acceptance,
                "detail_state": detail_state, "report_path": report_path, "notes": notes}
```

3. Add `"acceptance_state": "not_applicable"` to the dict that `lifecycle()`
   returns. `lifecycle()` feeds only the ship-handoff literals.
   `not_applicable` pairs with every `review_state`, so the existing handoff
   tests keep their meaning.

4. Add these two tests to `ArtifactBudgetCliTest`, directly after
   `test_every_sdd_report_matrix_row`:

```python
    def assert_rejected(self, boundary, payload, use_stdin):
        result = self.run_validate(boundary, payload, use_stdin)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, b"", b"artifact-budget: invalid report\n"), payload)

    def test_sdd_acceptance_state_is_required_closed_and_paired(self):
        """#272 D8: clean never carries unmet; residual unmet needs a conformance finding."""
        detail = ".superpowers/issue-delivery/272/run-1/sdd-a.json"
        clean = self.make_sdd("complete", "clean", "clean", "clean", "passed",
                              "a" * 40, "b" * 40, "none", None)
        conformance = self.make_sdd("residuals", "residuals", "findings", "clean",
                                    "passed", "a" * 40, "b" * 40, "present", detail)
        correctness = self.make_sdd("residuals", "residuals", "clean", "findings",
                                    "passed", "a" * 40, "b" * 40, "present", detail)
        before = self.make_sdd("failed", "unknown", "not_run", "not_run", "not_run",
                               None, None, "none", None)
        ungraded = self.make_sdd("failed", "unknown", "not_run", "clean", "failed",
                                 "a" * 40, "b" * 40, "none", None)
        graded = self.make_sdd("failed", "unknown", "findings", "clean", "failed",
                               "a" * 40, "b" * 40, "present", detail)
        accepted = [
            *({**clean, "acceptance_state": v} for v in ("met", "human_pending", "not_applicable")),
            *({**conformance, "acceptance_state": v} for v in ACCEPTANCE),
            *({**correctness, "acceptance_state": v} for v in ("met", "human_pending", "not_applicable")),
            {**before, "acceptance_state": "not_applicable"},
            {**ungraded, "acceptance_state": "not_applicable"},
            *({**graded, "acceptance_state": v} for v in ACCEPTANCE),
        ]
        for index, payload in enumerate(accepted):
            with self.subTest(accepted=index):
                result = self.run_validate("sdd", payload, index % 2 == 0)
                self.assertEqual(result.returncode, 0, (payload, result.stderr))
                self.assertEqual(json.loads(result.stdout), payload)
        rejected = [
            {**clean, "acceptance_state": "unmet"},
            {**correctness, "acceptance_state": "unmet"},
            {key: value for key, value in clean.items() if key != "acceptance_state"},
            {**clean, "acceptance_state": "unverified"},
            {**clean, "acceptance_state": True},
            {**clean, "acceptance_state": None},
            {**clean, "acceptance_state": ["met"]},
            {**before, "acceptance_state": "met"},
            {**ungraded, "acceptance_state": "unmet"},
        ]
        for index, payload in enumerate(rejected):
            with self.subTest(rejected=index):
                self.assert_rejected("sdd", payload, index % 2 == 1)

    def test_ship_handoff_acceptance_state_is_required_closed_and_paired(self):
        """#272 D8, D9: the legacy handoff pairs acceptance_state with review_state."""
        detail = ".superpowers/issue-delivery/49/run-1/sdd-a.json"
        complete = {**self.lifecycle(), "state": "complete",
                    "spec_artifact": self.full("design-spec"),
                    "plan_artifact": self.full("implementation-plan"),
                    "head_sha": "b" * 40, "review_state": "clean",
                    "report_path": None, "notes": "ok"}
        residual = {**complete, "review_state": "residuals", "report_path": detail,
                    "notes": f"details: {detail}"}
        before = {**self.lifecycle(), "state": "failed", "spec_artifact": None,
                  "plan_artifact": None, "head_sha": None, "review_state": "unknown",
                  "report_path": None, "notes": "failed"}
        after_unknown = {**complete, "state": "failed", "review_state": "unknown"}
        accepted = [
            *({**complete, "acceptance_state": v} for v in ("met", "human_pending", "not_applicable")),
            *({**residual, "acceptance_state": v} for v in ACCEPTANCE),
            {**before, "acceptance_state": "not_applicable"},
            {**after_unknown, "acceptance_state": "not_applicable"},
            {**complete, "state": "failed", "acceptance_state": "met"},
        ]
        for index, payload in enumerate(accepted):
            with self.subTest(accepted=index):
                result = self.run_validate("ship-handoff", payload, index % 2 == 0)
                self.assertEqual(result.returncode, 0, (payload, result.stderr))
        rejected = [
            {**complete, "acceptance_state": "unmet"},
            {key: value for key, value in complete.items() if key != "acceptance_state"},
            {key: value for key, value in before.items() if key != "acceptance_state"},
            {**residual, "acceptance_state": "unverified"},
            {**complete, "acceptance_state": 1},
            {**before, "acceptance_state": "met"},
            {**after_unknown, "acceptance_state": "unmet"},
        ]
        for index, payload in enumerate(rejected):
            with self.subTest(rejected=index):
                self.assert_rejected("ship-handoff", payload, index % 2 == 1)

    def test_acceptance_pairing_is_one_closed_table(self):
        """#272 D9, D11: one pairing home; unknown review states pair with nothing."""
        self.assertEqual(artifact_budget.ACCEPTANCE_STATES, frozenset(ACCEPTANCE))
        table = {"clean": {"met", "human_pending", "not_applicable"},
                 "residuals": set(ACCEPTANCE), "unknown": {"not_applicable"}}
        for review in ("clean", "residuals", "unknown", "partial", "", None, ["clean"]):
            for acceptance in (*ACCEPTANCE, "unverified", None, ["met"]):
                with self.subTest(review=review, acceptance=acceptance):
                    expected = (isinstance(review, str) and review in table
                                and isinstance(acceptance, str)
                                and acceptance in table[review])
                    self.assertIs(artifact_budget.acceptance_pairs_with_review(
                        review, acceptance), expected)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_artifact_budget.py 2>&1 | tail -5`
Expected: FAIL. The existing matrix tests now fail, because `acceptance_state`
is an unknown key under the exact key set. The new tests fail too, and
`test_acceptance_pairing_is_one_closed_table` fails with an `AttributeError`
for `ACCEPTANCE_STATES`.

- [ ] **Step 3: Write the minimal implementation**

In `artifact_budget.py`, place the closed set and the pairing beside the
report validators (above `validate_sdd_report`). The table is an exact wire
rule, so it is given here in full:

```python
# The closed acceptance_state set and its ship-handoff pairing (#272 D8, D9).
# This is the one home of both: the sdd rows below, the legacy handoff and the
# v2 handoff all read them.
ACCEPTANCE_STATES = frozenset({"met", "unmet", "human_pending", "not_applicable"})
_CLEAN_ACCEPTANCE = frozenset({"met", "human_pending", "not_applicable"})
_HANDOFF_ACCEPTANCE = {
    "clean": _CLEAN_ACCEPTANCE,
    "residuals": ACCEPTANCE_STATES,
    "unknown": frozenset({"not_applicable"}),
}


def acceptance_pairs_with_review(review_state: object, acceptance_state: object) -> bool:
    """True when a handoff's acceptance_state is allowed under its review_state.

    Any review_state outside the table pairs with nothing (#272 D11).
    """
    if not isinstance(review_state, str) or not isinstance(acceptance_state, str):
        return False
    allowed = _HANDOFF_ACCEPTANCE.get(review_state)
    return allowed is not None and acceptance_state in allowed
```

`validate_sdd_report`:
- Add `"acceptance_state"` to `keys`.
- After the exact-key check, read `acceptance = value["acceptance_state"]`.
  When it is not a `str`, or not in `ACCEPTANCE_STATES`, raise
  `ArtifactBudgetError("invalid SDD report")`.
- Then add exactly one conjunct to each existing branch. Leave the existing
  conjuncts unchanged.
  - `complete`/`clean`: `and acceptance in _CLEAN_ACCEPTANCE`.
  - `residuals`/`residuals`: `and (acceptance != "unmet" or value["conformance_verdict"] == "findings")`.
  - `failed`, null-SHA arm: `valid = detail == "none" and acceptance == "not_applicable"`.
  - `failed`, SHA arm: compute the existing detail rule into `valid` as
    today, then apply
    `valid = valid and (value["conformance_verdict"] != "not_run" or acceptance == "not_applicable")`.

`validate_ship_handoff_report`:
- Add `"acceptance_state"` to `keys`.
- Compute the existing state rule into `valid` as today. Then apply
  `valid = valid and acceptance_pairs_with_review(value["review_state"], value["acceptance_state"])`
  before the final `if not valid` raise.

Change nothing else in the file.

- [ ] **Step 4: Verify**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_artifact_budget.py 2>&1 | tail -3`
Expected: `OK`, and 43 tests ran (40 before, plus the 3 new ones).

Run: `if ! grep -q 'def acceptance_pairs_with_review' home/common/agent-skills/scripts/artifact_budget.py; then exit 1; fi`
Expected: exit 0. At the base commit this exits 1.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/artifact_budget.py home/common/agent-skills/tests/test_artifact_budget.py
git commit -m "feat(artifact-budget): require acceptance_state on sdd and legacy handoff reports (#272)"
```
Under a `Lifecycle worker:` line, commit with
`launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- -m "<message>"`
instead of `git commit`. `launch-commit` passes the arguments after `--` to
`git commit`.
