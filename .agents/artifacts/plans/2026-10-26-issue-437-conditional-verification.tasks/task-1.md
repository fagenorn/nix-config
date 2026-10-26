# Task 1: `resolve-project` accepts `verification_conditions`; one shared glob matcher

Spec § Contract grammar and § Resolved snapshot, per D1, D2 and D3. `bindings.workflow` gains one optional member, validated with named violations and passed through as authored. The any-path × any-glob predicate moves into `resolve_project`, and `lane-triage` calls it with no change in behaviour.

**Files:**
- Modify: `python/agent_tools/resolve_project.py` (constants block near `WORKFLOW_OPTIONAL_MEMBERS`; new `any_path_matches` after `is_canonical_path`; new `check_contract_glob` before `check_object`; `validate_workflow`; new `validate_verification_conditions` after it)
- Modify: `python/agent_tools/lane_triage.py` (`evaluate`, imports)
- Test: `home/common/agent-skills/tests/test_resolve_project.py` (new class `VerificationConditionsTest`, inserted directly before `class PublicResolveTest`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `resolve_project.any_path_matches(paths: list[str], globs: list[str]) -> bool`. Task 2 calls it.
  - The resolved snapshot's `bindings.workflow.verification_conditions` is absent, `null` or the authored object, unchanged. Task 2 reads it.
  - New repair ids `contract.workflow.unknown_verification_id`, `contract.workflow.empty_path_list` and `contract.workflow.no_unconditional_verification`. Task 2's refusal test expects the `empty_path_list` one.

**Invariants:**
- `WORKFLOW_OPTIONAL_MEMBERS == ("light_lane", "verification_conditions")`, and a new `VERIFICATION_CONDITION_MEMBERS = ("when_changed", "skip_reason")` sits beside `LIGHT_LANE_MEMBERS`.
- `any_path_matches` returns `any(fnmatch.fnmatchcase(path, glob) for path in paths for glob in globs)`, with both strings unchanged, so `*` crosses `/` (D3). `lane_triage.evaluate` adds `risk_path` exactly when `resolve_project.any_path_matches(record["paths"], light_lane["risk_paths"])`. `lane_triage.py` no longer imports `fnmatch`.
- `check_contract_glob(value, pointer, violations)` is the old `risk_paths` entry body, moved: `check_safe_path(value, pointer, "workflow", violations)`, then, only when that passes and `not is_canonical_path(value)`, a `contract.workflow.noncanonical_path` violation with `CANONICAL_PATH_MESSAGE`. The `risk_paths` loop calls it, and so does each `when_changed` entry. That way the two lists share one rule, never a copy (D2). Every existing `LightLaneTest` row passes unmodified.
- Every violation of the new member uses the existing collection (`violation`, then `raise_for_violations`), with pointers rooted at `/bindings/workflow/verification_conditions` and segments not JSON-pointer-escaped. Each row of the spec's grammar table yields exactly the pointer and repair id the test table below lists, and exactly one violation.
- The unknown-id check runs only when `workflow["verification"]` is a list. The every-id-conditional check counts only `str` ids, so a non-string `verification` entry never raises (it is already reported at `/bindings/workflow/verification/<n>`).
- `normalize_bindings` is unchanged: the member passes through by its existing deep copy, and globs are never made absolute. No schema bump, no manifest change, no new capability, and `first_unmet_prerequisite("verification", …)` still checks every declared id (spec § Resolved snapshot).

- [ ] **Step 1: Write the failing test**

In `home/common/agent-skills/tests/test_resolve_project.py`, insert this class directly before `class PublicResolveTest(InProcessTestCase):`. Every name it uses is already in the module (`ResolverTestCase`, `source_contract`).

```python
class VerificationConditionsTest(ResolverTestCase):
    """Issue 437: the optional `bindings.workflow.verification_conditions` member (D1, D2)."""

    POINTER = "/bindings/workflow/verification_conditions"
    CONDITION = {"when_changed": ["python/*", "tests/*", "justfile"],
                 "skip_reason": "no agent-tooling paths changed"}
    VALID = {"agent-workflow-tests": CONDITION}
    ABSENT = object()

    def contract_with(self, conditions):
        contract = source_contract()
        workflow = contract["bindings"]["workflow"]
        workflow["verification"] = ["nix-build", "agent-workflow-tests"]
        workflow.pop("verification_conditions", None)
        if conditions is not self.ABSENT:
            workflow["verification_conditions"] = conditions
        return contract

    def resolved_member(self, conditions):
        code, snap, err = self.resolve(self.make_root(self.contract_with(conditions)))
        self.assertEqual(code, 0, err)
        return snap["bindings"]["workflow"]

    def test_a_valid_member_round_trips_unchanged(self):
        globbed = {"agent-workflow-tests": {
            "when_changed": ["src/**/*.py", "*.nix", "a/[bc]?.py", "AGENTS.md"],
            "skip_reason": "nothing the suite reads changed"}}
        for conditions in (self.VALID, globbed, {}):
            with self.subTest(conditions=conditions):
                workflow = self.resolved_member(conditions)
                # Passed through as authored: no glob is made absolute (D1).
                self.assertEqual(workflow["verification_conditions"], conditions)
                self.assertEqual(workflow["verification"],
                                 ["nix-build", "agent-workflow-tests"])

    def test_an_absent_member_stays_absent(self):
        self.assertNotIn("verification_conditions", self.resolved_member(self.ABSENT))

    def test_null_stays_null(self):
        workflow = self.resolved_member(None)
        self.assertIn("verification_conditions", workflow)
        self.assertIsNone(workflow["verification_conditions"])

    REFUSALS = (
        # (member, pointer suffix, repair id); the suffix is rooted at POINTER.
        ([], "", "contract.workflow.not_object"),
        ("python/*", "", "contract.workflow.not_object"),
        ({"lint": CONDITION}, "/lint", "contract.workflow.unknown_verification_id"),
        ({"agent-workflow-tests": ["python/*"]}, "/agent-workflow-tests",
         "contract.workflow.not_object"),
        ({"agent-workflow-tests": {"skip_reason": "x"}},
         "/agent-workflow-tests/when_changed", "contract.workflow.member_missing"),
        ({"agent-workflow-tests": {"when_changed": ["python/*"]}},
         "/agent-workflow-tests/skip_reason", "contract.workflow.member_missing"),
        # The issue's "unknown key".
        ({"agent-workflow-tests": {**CONDITION, "paths": ["python/*"]}},
         "/agent-workflow-tests/paths", "contract.workflow.member_unexpected"),
        ({"agent-workflow-tests": {**CONDITION, "when_changed": "python/*"}},
         "/agent-workflow-tests/when_changed", "contract.workflow.not_list"),
        # The issue's "empty path list".
        ({"agent-workflow-tests": {**CONDITION, "when_changed": []}},
         "/agent-workflow-tests/when_changed", "contract.workflow.empty_path_list"),
        # The issue's "absolute path".
        ({"agent-workflow-tests": {**CONDITION, "when_changed": ["/abs/*"]}},
         "/agent-workflow-tests/when_changed/0", "contract.workflow.unsafe_path"),
        ({"agent-workflow-tests": {**CONDITION, "when_changed": ["../outside/*"]}},
         "/agent-workflow-tests/when_changed/0", "contract.workflow.unsafe_path"),
        ({"agent-workflow-tests": {**CONDITION, "when_changed": ["python/*", ""]}},
         "/agent-workflow-tests/when_changed/1", "contract.workflow.unsafe_path"),
        ({"agent-workflow-tests": {**CONDITION, "when_changed": ["python/*", 3]}},
         "/agent-workflow-tests/when_changed/1", "contract.workflow.unsafe_path"),
        ({"agent-workflow-tests": {**CONDITION, "when_changed": ["./a.py"]}},
         "/agent-workflow-tests/when_changed/0", "contract.workflow.noncanonical_path"),
        ({"agent-workflow-tests": {**CONDITION, "when_changed": ["a/"]}},
         "/agent-workflow-tests/when_changed/0", "contract.workflow.noncanonical_path"),
        ({"agent-workflow-tests": {**CONDITION, "when_changed": ["a\\b.py"]}},
         "/agent-workflow-tests/when_changed/0", "contract.workflow.noncanonical_path"),
        ({"agent-workflow-tests": {**CONDITION, "skip_reason": ""}},
         "/agent-workflow-tests/skip_reason", "contract.workflow.not_string"),
        ({"agent-workflow-tests": {**CONDITION, "skip_reason": 7}},
         "/agent-workflow-tests/skip_reason", "contract.workflow.not_string"),
        ({"nix-build": CONDITION, "agent-workflow-tests": CONDITION}, "",
         "contract.workflow.no_unconditional_verification"),
    )

    def test_each_malformed_member_is_refused_with_its_pointer(self):
        for conditions, suffix, repair_id in self.REFUSALS:
            with self.subTest(pointer=suffix, conditions=conditions):
                code, payload, _ = self.resolve(
                    self.make_root(self.contract_with(conditions)))
                error = self.assert_refusal(code, payload, "invalid_contract")
                self.assertEqual(error["repair_id"], repair_id)
                self.assertEqual([v["pointer"] for v in error["violations"]],
                                 [self.POINTER + suffix])
                self.assertTrue(error["violations"][0]["message"])

    def test_a_non_string_verification_id_is_reported_once_and_never_crashes(self):
        contract = self.contract_with(self.VALID)
        contract["bindings"]["workflow"]["verification"] = [
            "nix-build", "agent-workflow-tests", ["nix-build"]]
        code, payload, _ = self.resolve(self.make_root(contract))
        error = self.assert_refusal(code, payload, "invalid_contract")
        self.assertEqual([v["pointer"] for v in error["violations"]],
                         ["/bindings/workflow/verification/2"])
```

- [ ] **Step 2: Run the test and watch it fail**

Run the focused form on `home/common/agent-skills/tests/test_resolve_project.py -k VerificationConditionsTest`.
Expected: FAIL. At base `test_a_valid_member_round_trips_unchanged`, `test_null_stays_null`, every `test_each_malformed_member_is_refused_with_its_pointer` row and `test_a_non_string_verification_id_is_reported_once_and_never_crashes` fail with `member_unexpected` at the member's pointer. `test_an_absent_member_stays_absent` passes at base, which is expected.

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/resolve_project.py`:

1. Add `import fnmatch` in the standard-library import block, then add the two constants from the Invariants.
2. After `is_canonical_path`, add `any_path_matches` with this docstring: "True when some path matches some glob under `fnmatch.fnmatchcase`. Both are compared as spelled, so `*` also crosses `/` (#279 D4, issue 437 D3). It is the one matcher for contract path globs: `lane-triage`'s `risk_paths` and `verified-tree`'s `when_changed` both call it."
3. Before `check_object`, add `check_contract_glob` per the Invariants, with the docstring "A `workflow` path glob: a safe repository-relative path, spelled canonically (#279 D4)." Replace the body of the `risk_paths` loop with `check_contract_glob(entry, f"{pointer}/risk_paths/{index}", violations)`.
4. At the end of `validate_workflow`, call `validate_verification_conditions(workflow, violations)`, defined right after it. This code preserves the guards the Invariants name:

```python
def validate_verification_conditions(workflow: dict, violations: list[dict]) -> None:
    """Issue 437 D2: the optional `bindings.workflow.verification_conditions` member."""
    pointer = "/bindings/workflow/verification_conditions"
    conditions = workflow.get("verification_conditions")
    if conditions is None or not check_object(conditions, pointer, "workflow", violations):
        return
    declared = workflow.get("verification")
    declared = declared if isinstance(declared, list) else None
    for verification_id, condition in conditions.items():
        entry = f"{pointer}/{verification_id}"
        if declared is not None and verification_id not in declared:
            violations.append(violation(
                entry, "names no id of bindings.workflow.verification",
                "contract.workflow.unknown_verification_id"))
        if not check_object(condition, entry, "workflow", violations):
            continue
        check_exact_members(
            condition, entry, VERIFICATION_CONDITION_MEMBERS, "workflow", violations)
        if "when_changed" in condition and check_list(
                condition["when_changed"], f"{entry}/when_changed", "workflow",
                violations):
            if not condition["when_changed"]:
                violations.append(violation(
                    f"{entry}/when_changed", "must be a non-empty list",
                    "contract.workflow.empty_path_list"))
            for index, glob in enumerate(condition["when_changed"]):
                check_contract_glob(glob, f"{entry}/when_changed/{index}", violations)
        if "skip_reason" in condition:
            check_string(condition["skip_reason"], f"{entry}/skip_reason", "workflow",
                         violations)
    if declared and all(isinstance(verification_id, str) and verification_id in conditions
                        for verification_id in declared):
        violations.append(violation(
            pointer, "must leave at least one bindings.workflow.verification id "
                     "unconditional", "contract.workflow.no_unconditional_verification"))
```

In `python/agent_tools/lane_triage.py`, drop `import fnmatch` and make the `evaluate` condition `if resolve_project.any_path_matches(record["paths"], light_lane["risk_paths"]):`. The docstring and the rest of the module are unchanged.

- [ ] **Step 4: Verify**

Run the focused form (timeout 900 s; about 90 s at base) on `home/common/agent-skills/tests/test_resolve_project.py tests/test_lane_triage.py`.
Expected: `OK`, every test of both modules passing, the five `VerificationConditionsTest` tests and every `LightLaneTest` and `StallMinutesTest` row included.

Run (timeout 60 s):

```bash
set -e
if grep -q fnmatch python/agent_tools/lane_triage.py; then exit 1; fi
test "$(grep -c 'contract.workflow.noncanonical_path' python/agent_tools/resolve_project.py)" -eq 1
git diff --quiet ca6ba1ae2b37e56c1361a8656c29af1f39b89348 -- .agents/project.json home/common/agent-skills/evals/fixture-repo/.agents/project.json
```

Expected: every command exits 0. At base the first check fails, because `lane_triage.py` imports `fnmatch`. The second check finds the noncanonical repair id once, in `check_contract_glob`, and no copy in the `when_changed` loop.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/resolve_project.py python/agent_tools/lane_triage.py home/common/agent-skills/tests/test_resolve_project.py
launch-commit … -- -m "feat(resolve-project): optional verification_conditions member (issue 437)" -m "<session trailers>"
```

Verify: `git status --short -- python home tests` prints nothing.
