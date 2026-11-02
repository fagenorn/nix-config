# Task 2: The derived row carries the declared checks, and the row check confirms them

Spec § The derived row, § The row check, § Documentation (`## Guard policy`, `python/README.md`). Rests on D4, D5 and D10. After this task the compiler writes each row as `{default_branch, integration_branch, required_checks, evidence}` under `derivation.schema_version` 3, `derive` reports `schema_version` 2, the guard's loader demands the member, and the row check confirms it. The guard reads the confirmed list but nothing judges a merge by it until Task 3. The compiler, the loader and both suites change in one commit: the guard suite's round trips compile with the source compiler and judge with the built guard, so a row shape that only one side knows would break them.

**Files:**
- Modify: `python/agent_tools/guard_policy.py` (`DERIVE_REPORT_SCHEMA_VERSION`, `DERIVATION_SCHEMA_VERSION`, the `GUARD_SLUG` comment, `_proof`)
- Modify: `home/common/claude-code/lifecycle_guard.py` (`DERIVED_ROW_KEYS`, `load_compiled_policy`, `_report_mismatch`)
- Test: `tests/test_guard_policy.py`
- Test: `tests/test_claude_permission_guard.py`
- Modify: `home/common/claude-code/README.md` (`## Guard policy`)
- Modify: `python/README.md` (§ guard-policy)

**Interfaces:**
- Consumes: Task 1's member, read from the resolved snapshot as `payload["bindings"]["vcs"]["merge"].get("required_checks")` (absent and `None` both mean none). In the guard suite: `write_policy`, `rows_env`, `run_guard`, `make_repo`, `assert_unconfirmed`, `FOUR_VERBS`, `NODO`, `NODO_ROW`, `ABSENT`, `COMPILED_ROW_SHAPES`. In `tests/test_guard_policy.py`: `WorldCase`, `DeriveTest.derived`, `GuardPolicyWorld.project(..., mutate=)`.
- Produces: a derived row's `required_checks`, a sorted `list[str]`, `[]` when none is declared. `DERIVATION_SCHEMA_VERSION = 3` and `DERIVE_REPORT_SCHEMA_VERSION = 2`. `DERIVED_ROW_KEYS` gains `"required_checks"`. `NODO_ROW` gains `"required_checks": []`. Task 3 reads a confirmed row's list as `row["required_checks"]`.

**Invariants:**
- The compiler writes `sorted(...)` of the declared list. It reads the list from the resolved snapshot of the pinned contract, as it reads the two branches. `evidence` and `unsupported_name` are unchanged (D4: the loader's rule equals the resolver's, so no row is refused for its checks).
- The loader's closed key set has four members. A row whose `required_checks` is missing, `null`, not a list, holds an entry that is not a non-empty string, or repeats an entry makes the whole compiled policy contribute no row, with the reason `<path>: derived_repositories <slug> required_checks must be a list of distinct non-empty strings`. A schema-2 row, which lacks the member, is that case.
- `_report_mismatch`, `derived` outcome: a `row` whose `required_checks` is not a list of strings is `unreadable report (exit <n>)`. The branches are compared first and keep their message. Then the two lists must be equal as lists, order included, or the check refuses with `it derives required checks <derived>, the row names <compiled>`, each list as `json.dumps(value, separators=(",", ":"))`. `evidence` is never compared.
- Every guard-suite assertion outside this task's edits keeps its verdict. The existing row literals change only by gaining `"required_checks": []` (D10), and the adversarial table (`# Adversarial table.` to `# Release arm: the declared integration branch`) changes only through `NODO_ROW`.

- [ ] **Step 1: Write the failing tests**

`tests/test_guard_policy.py`:

1. `ROW_MEMBERS = {"default_branch", "integration_branch", "required_checks", "evidence"}`.
2. In `test_a_nodo_shaped_and_a_single_branch_project_both_derive`, change `self.assertEqual(derivation["schema_version"], 2)` to `3`. After the `for row in rows.values():` loop, add `self.assertEqual([row["required_checks"] for row in rows.values()], [[], []])`.
3. In `DeriveTest.derived`, the expected tuple's first member becomes `2`: `(2, repository, "derived", None)`.
4. Add to `DeriveTest`, after `test_a_registered_slug_derives_the_row_compile_writes`:

```python
    def test_declared_required_checks_reach_the_row_sorted(self):
        """Issue 552 D1, D4: the row carries the contract's checks sorted, `[]` for an
        absent or null member, and derive reports the row compile writes."""
        def declare(checks):
            def mutate(contract):
                contract["bindings"]["vcs"]["merge"]["required_checks"] = checks
            return mutate

        self.world.project("fixture/checks", "fagenorn/checks",
                           mutate=declare(["lint", "CI / build (unit + forced)"]))
        self.world.project("fixture/null", "fagenorn/null", mutate=declare(None))
        self.world.project("fixture/absent", "fagenorn/absent")
        self.assertEqual(self.world.compile()[0], 0)
        rows = self.world.policy()["derived_repositories"]
        self.assertEqual(rows["fagenorn/checks"]["required_checks"],
                         ["CI / build (unit + forced)", "lint"])
        self.assertEqual([rows[slug]["required_checks"]
                          for slug in ("fagenorn/null", "fagenorn/absent")], [[], []])
        self.assertEqual(self.derived("fagenorn/checks")["row"], rows["fagenorn/checks"])
```

`tests/test_claude_permission_guard.py`. Wrap any line past 99 characters as the surrounding code does.

1. `NODO_ROW = {"default_branch": "main", "integration_branch": "dev", "required_checks": [], "evidence": {}}`.
2. Add `"required_checks": [],` after the `"integration_branch"` member of each literal row in these tests. Change nothing else in them:
   - `test_a_row_beside_a_literal_integration_base_is_refused` (the `trunk`/`release` row);
   - `test_literal_owner_does_not_bypass_the_derived_row_check`;
   - `test_single_branch_derived_row_keeps_the_default_branch_only_rule` (the policy row and the `rows_env` row);
   - `test_a_compiled_policy_round_trips_through_the_guard` (the `acme/forged` row);
   - `test_a_row_for_an_unregistered_repository_is_refused_at_use`;
   - `test_a_row_whose_branches_differ_from_the_derivation_is_refused` (the policy row and the `rows_env` row of `fagenorn/tool`);
   - `test_the_row_check_never_sees_a_hostile_shell_environment` (`row`).
3. In `COMPILED_ROW_SHAPES`, give `"row lacks evidence"` the row `{"default_branch": "main", "integration_branch": "dev", "required_checks": []}`, so that it lacks only `evidence`. Directly after `"evidence is not an object"`, add:

```python
        "the schema-2 row shape": {"derived_repositories": {
            NODO: {"default_branch": "main", "integration_branch": "dev", "evidence": {}}}},
        "required_checks is null": {"derived_repositories": {
            NODO: {**NODO_ROW, "required_checks": None}}},
        "required_checks is not a list": {"derived_repositories": {
            NODO: {**NODO_ROW, "required_checks": "CI"}}},
        "a required check is empty": {"derived_repositories": {
            NODO: {**NODO_ROW, "required_checks": ["CI", ""]}}},
        "a required check is not a string": {"derived_repositories": {
            NODO: {**NODO_ROW, "required_checks": ["CI", 7]}}},
        "a required check repeats": {"derived_repositories": {
            NODO: {**NODO_ROW, "required_checks": ["CI", "CI"]}}},
```

4. Insert directly before `def test_a_failing_row_check_refuses_with_no_fallback`:

```python
    def test_a_row_whose_required_checks_differ_from_the_derivation_is_refused(self):
        """Issue 552 D5: the row check confirms the declared checks as lists, order
        included, and a derived report whose checks are not a list of strings is
        unreadable."""
        slug = "acme/checks"
        derived = {"default_branch": "main", "integration_branch": "main",
                   "required_checks": ["CI", "lint"], "evidence": {}}
        env = self.rows_env({slug: derived})
        confirmed = self.write_policy(derivation={}, derived_repositories={slug: derived})
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(confirmed))
        allowed = self.run_guard("git push -u origin topic", guard_args=args, env=env,
                                 cwd=self.make_repo(f"git@github.com:{slug}.git"))
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        for compiled, named in ((["lint"], '["lint"]'), (["lint", "CI"], '["lint","CI"]'),
                                ([], "[]")):
            policy = self.write_policy(derivation={}, derived_repositories={
                slug: {**derived, "required_checks": compiled}})
            self.assert_unconfirmed(
                slug, f'it derives required checks ["CI","lint"], the row names {named}',
                env=env, guard_args=("--gh-bin", str(self.fake_gh), "--policy", str(policy)))
        for reported in (ABSENT, None, "CI", ["CI", 7]):
            row = {key: value for key, value in {**derived, "required_checks": reported}.items()
                   if value is not ABSENT}
            self.assert_unconfirmed(slug, "unreadable report (exit 0)", guard_args=args,
                                    env=self.rows_env({slug: row}))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_guard_policy.py 2>&1 | tail -4'`
Expected: FAIL. Rows lack `required_checks`, `derivation.schema_version` is 2 and the derive report's is 1.

Run the Guard suite (root § Global Constraints, timeout 3600 s).
Expected: FAIL. The built guard still loads three-member rows only, so every fixture policy holding a four-member row contributes no row. Failures include `test_prefixed_merge_reaches_acceptance_on_the_integration_base` (exit 2, `outside standing authorization`), `test_a_compiled_policy_round_trips_through_the_guard` (its forged row now has four members) and the new test.

- [ ] **Step 3: Write the minimal implementation**

`python/agent_tools/guard_policy.py`:
- `DERIVE_REPORT_SCHEMA_VERSION = 2` and `DERIVATION_SCHEMA_VERSION = 3`.
- `_proof` returns `{"default_branch": ..., "integration_branch": ..., "required_checks": sorted(vcs["merge"].get("required_checks") or []), "evidence": {...}}`. The `evidence` value is unchanged.
- Append to the comment above `GUARD_SLUG`: `Its rule for a row's required_checks, a list of distinct non-empty strings, is the resolver's own rule for the contract member (issue 552 D4), so unsupported_name has no case for it.`

`home/common/claude-code/lifecycle_guard.py`:
- `DERIVED_ROW_KEYS = frozenset({"default_branch", "integration_branch", "required_checks", "evidence"})`.
- `load_compiled_policy`: after the branch loop and before the `evidence` check, refuse a `required_checks` that is not a list, holds an entry that is not a non-empty `str`, or repeats an entry. Run the length-of-set test only after every entry is known to be a string. The reason is `f"{path}: derived_repositories {repository} required_checks must be a list of distinct non-empty strings"`. In the docstring, "the guard reads a row's two branches and leaves" becomes "the guard reads a row's two branches and its required checks and leaves".
- `_report_mismatch`: the `derived` branch adds to its shape test that `derived.get("required_checks")` is a `list` whose every entry is a `str`. After the unchanged branch comparison, it returns the required-checks message from the Invariants when `derived["required_checks"] != row["required_checks"]`. The docstring becomes: `Why report (the row check's parsed stdout) does not confirm row, or None.` followed by `A shape failure, a row.required_checks that is not a list of strings included, is an unreadable report. The branches are compared first, then the required checks as lists, order included (issue 552 D5); evidence is never compared.` Keep the backticks of the current docstring style.

`home/common/claude-code/README.md`, `## Guard policy`, four edits:
1. Replace `` keyed by the exact repository slug, `{default_branch, integration_branch, evidence}`. `` with `` keyed by the exact repository slug, `{default_branch, integration_branch, required_checks, evidence}`, where `required_checks` is the sorted list of check names the project's contract declares in `bindings.vcs.merge.required_checks`, `[]` when it declares none. ``
2. Replace `` (4) it must have exited 0 with an `outcome` of `derived` whose `row` has the compiled row's `default_branch` and `integration_branch`. `` with `` (4) it must have exited 0 with an `outcome` of `derived` whose `row` has the compiled row's `default_branch` and `integration_branch`, and then its `required_checks`, equal as lists, order included (a report whose `row.required_checks` is not a list of strings is unreadable). ``
3. Replace `the reason (the row check's reason code, or the differing branches)` with `` the reason (the row check's reason code, the differing branches, or `it derives required checks <derived>, the row names <compiled>` with each list as compact JSON) ``.
4. After the `**A bad file.**` paragraph, which ends `is an installation defect.`, add this paragraph:

```markdown
**Required checks and the schema-3 transition (issue 552).** The loader demands that a row's `required_checks` be a list of distinct non-empty strings, the resolver's own rule for the contract member, so a contract that resolves always yields a row the guard loads; any other value is a malformed row, and the whole compiled policy contributes no row. The compiler writes `derivation.schema_version` 3, whose rows carry the member. A schema-2 file lacks it, so this guard reads that file as contributing no row; the activation step recompiles on every switch, so the switch that installs this guard also writes a schema-3 file. A Claude Code session started before that switch still runs the previous guard, which reads a schema-3 file as contributing no row. In both cases only a repository that relies on a derived row for its authorization is refused, until the recompile or the session restart this section asks for after an agent_tools change; a repository authorized by an owner literal keeps its authorization.
```

`python/README.md`, § guard-policy, four replacements:
1. `` A row is `{default_branch, integration_branch, evidence}`, and the evidence is identity only `` becomes `` A row is `{default_branch, integration_branch, required_checks, evidence}`. `required_checks` is the contract's `bindings.vcs.merge.required_checks` (below), read from the resolved snapshot of the pinned contract as the two branches are, sorted, or `[]` when the contract declares none; the guard's loader accepts exactly the entries the resolver accepts, so `unsupported_name` does not check them. The evidence is identity only ``.
2. `` where `schema_version` is 2 and `` becomes `` where `schema_version` is 3 and ``.
3. `takes nothing but a row's two branches from this file` becomes `takes nothing but a row's two branches and its required checks from this file`.
4. `` with the keys `schema_version` (1), `repository` `` becomes `` with the keys `schema_version` (2), `repository` ``.

- [ ] **Step 4: Verify**

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_guard_policy.py home/common/agent-skills/tests/test_resolve_project.py 2>&1 | tail -4'`
Expected: PASS, `OK`.

After `git add` of the six files, run the Guard suite (root § Global Constraints, timeout 3600 s). It builds first.
Expected: PASS, `OK`, the base count plus one test. Its three compile round trips (`test_a_compiled_policy_round_trips_through_the_guard`, `test_an_arcwave_shaped_project_is_judged_by_its_compiled_row`, `test_a_compiled_policy_loads_whatever_branch_names_the_fleet_carries`) show that the source compiler's rows load in the built guard.

Run: `if grep -q "takes nothing but a row's two branches from this file" python/README.md; then exit 1; fi`
Expected: exit 0, because the sentence that the guard takes only the two branches is gone.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/guard_policy.py home/common/claude-code/lifecycle_guard.py tests/test_guard_policy.py tests/test_claude_permission_guard.py home/common/claude-code/README.md python/README.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "feat(issue-552/T2): carry and confirm required checks in the guard row" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64,64],"id":2,"records":[{"bounds":[{"added_lines":12,"boundary":"all","deleted_lines":6,"record_bytes":8192,"support":{"covers":["r2a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2a","last_task":2,"owner":2,"path":"python/agent_tools/guard_policy.py"},{"bounds":[{"added_lines":35,"boundary":"all","deleted_lines":10,"record_bytes":12288,"support":{"covers":["r2b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2b","last_task":3,"owner":2,"path":"home/common/claude-code/lifecycle_guard.py"},{"bounds":[{"added_lines":35,"boundary":"all","deleted_lines":4,"record_bytes":12288,"support":{"covers":["r2c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2c","last_task":2,"owner":2,"path":"tests/test_guard_policy.py"},{"bounds":[{"added_lines":70,"boundary":"all","deleted_lines":16,"record_bytes":22528,"support":{"covers":["r2d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2d","last_task":4,"owner":2,"path":"tests/test_claude_permission_guard.py"},{"bounds":[{"added_lines":6,"boundary":"all","deleted_lines":4,"record_bytes":26624,"support":{"covers":["r2e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2e","last_task":4,"owner":2,"path":"home/common/claude-code/README.md"},{"bounds":[{"added_lines":8,"boundary":"all","deleted_lines":4,"record_bytes":17408,"support":{"covers":["r1c","r2f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2f","last_task":2,"owner":2,"path":"python/README.md"}]}}
```
