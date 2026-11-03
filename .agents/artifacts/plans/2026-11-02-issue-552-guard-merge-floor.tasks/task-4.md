# Task 4: An Argus-shaped project merges under the floor, end to end (AC1)

Spec § Acceptance mapping (AC1), § Test seams seam 4. Rests on D8, D10 and D14. After this task one guard-suite test runs the real compiler and the real row check over an Argus-shaped fixture project, and drives a ship-issue-form merge into `main` through the built guard against the plan-gated answer. It also shows that no central policy table names Argus. The live merge on `fagenorn/argus` belongs to https://github.com/fagenorn/nix-config/issues/129 (D8).

**Files:**
- Test: `tests/test_claude_permission_guard.py` (one new test)
- Modify: `home/common/claude-code/README.md` (the plan-gated floor paragraph, one sentence)

**Interfaces:**
- Consumes: Tasks 1 to 3 as built: the resolver accepts `bindings.vcs.merge.required_checks`, the compiler writes and `derive` reports it sorted, and the guard judges the floor. Test helpers: `GuardPolicyWorld` (`project(..., mutate=)`, `compile(base=)`, `policy()`, `row_check()`, `output`), `BASE_POLICY_PATH`, `make_repo`, `run_guard`, `refusal_line`, `HEAD_SHA`, and from Task 3 `check_run`, `UNPROTECTED`, `LOOKUP_FAILED` and the fake `gh` mode `http_error`.
- Produces: `ClaudePermissionGuardTest.test_an_argus_shaped_project_merges_under_the_plan_gated_floor`.

**Invariants:**
- The declaration lives only in the fixture contract (`mutate`). The base policy, `default.nix` and the guard source gain no slug, and the test asserts it for `argus` in any case.
- The merge is ship-issue's form with the credential-scrub prefix, a subject and `--match-head-commit` (`tests/fixtures/guarded-command-shapes.json`, `merge.subject`).
- No other test, fixture or source file changes.

- [ ] **Step 1: Write the failing test**

In `tests/test_claude_permission_guard.py`, insert directly after `test_an_arcwave_shaped_project_is_judged_by_its_compiled_row`, before `def test_a_compiled_policy_loads_whatever_branch_names_the_fleet_carries`:

```python
    def test_an_argus_shaped_project_merges_under_the_plan_gated_floor(self):
        """Issue 552 AC1, D8: a registered project whose forge cannot protect its default
        branch, and whose own contract declares its CI check, is judged by the floor through
        its compiled and confirmed row, and no central policy table names it."""
        slug = "fagenorn/argus"
        check = "memory foundation (unit + forced checks)"
        world = GuardPolicyWorld(self)
        world.project("argus", slug, publication_free=True, mutate=lambda contract: (
            contract["bindings"]["vcs"]["merge"].update(required_checks=[check])))
        code, report, stderr = world.compile(base=BASE_POLICY_PATH)
        self.assertEqual((0, [slug], []), (code, report["derived"], report["refused"]), stderr)
        row = world.policy()["derived_repositories"][slug]
        self.assertEqual(("main", "main", [check]), (
            row["default_branch"], row["integration_branch"], row["required_checks"]))
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(world.output),
                "--derive-bin", str(world.row_check()), "--derive-timeout-seconds", "25")
        repo = self.make_repo(f"git@github.com:{slug}.git")
        merge = (f"unset GITHUB_TOKEN && gh pr merge 9 --repo {slug} --merge --subject "
                 f'"feat: memory foundation (#9)" --match-head-commit {self.HEAD_SHA} '
                 "--delete-branch")

        def merged(rollup, mode="http_error"):
            facts = {"state": "OPEN", "baseRefName": "main", "headRefName": "issue-9-topic",
                     "headRefOid": self.HEAD_SHA, "mergeStateStatus": "CLEAN",
                     "url": f"https://github.com/{slug}/pull/9", "statusCheckRollup": rollup}
            return self.run_guard(merge, cwd=repo, guard_args=args, timeout=60, env={
                "FAKE_PR_JSON": json.dumps(facts), "FAKE_PROTECTION_MODE": mode})

        allowed = merged([self.check_run(check)])
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        floor = f"{self.UNPROTECTED}, and the declared required check {check} "
        self.assertEqual(floor + "is missing from the PR's check rollup",
                         self.refusal_line(merged([self.check_run("CI / lint")])))
        self.assertEqual(floor + "is not green (CheckRun COMPLETED/FAILURE)",
                         self.refusal_line(merged([self.check_run(check,
                                                                  conclusion="FAILURE")])))
        self.assertTrue(self.refusal_line(merged([self.check_run(check)], mode="nonzero"))
                        .startswith(self.LOOKUP_FAILED + "fake protection failure"))
        root = Path(__file__).resolve().parents[1]
        central = (BASE_POLICY_PATH, root / "home/common/claude-code/default.nix",
                   root / "home/common/claude-code/lifecycle_guard.py")
        self.assertEqual([], [str(path) for path in central
                              if "argus" in path.read_text(encoding="utf-8").lower()])
```

- [ ] **Step 2: Run the test and confirm it can fail**

Tasks 1 to 3 already hold, so the test passes on arrival. Confirm by hand that it can fail. In the working tree only, change `"required_checks": sorted(vcs["merge"].get("required_checks") or [])` in `python/agent_tools/guard_policy.py`'s `_proof` to `"required_checks": []`. Then run the Guard suite (root § Global Constraints, timeout 3600 s) with `-k argus_shaped` after the test file.
Expected: FAIL. The row assertion shows `[]` where `['memory foundation (unit + forced checks)']` was expected. Before the test is inserted, the same command runs no test, which also fails.
Run `git checkout -- python/agent_tools/guard_policy.py` to restore the file, then `git status --short python/` and confirm the output is empty.

- [ ] **Step 3: Name the test in the guard README (D14)**

In `home/common/claude-code/README.md`, the plan-gated floor paragraph that Task 3 added ends `and the protection demand governs again with no contract change.` Append one sentence to that paragraph: `` `test_an_argus_shaped_project_merges_under_the_plan_gated_floor` drives the floor end to end, with `guard-policy derive` run from source as the row check over a fixture fleet. `` Leave the `## Allow surface and lifecycle guard` sentence that names three such tests unchanged (D14).

- [ ] **Step 4: Verify**

Run the full Guard suite (root § Global Constraints, timeout 3600 s).
Expected: PASS, `OK`, Task 3's count plus one test.

Run: `if grep -qi argus home/common/claude-code/default.nix home/common/claude-code/lifecycle_guard.py python/agent_tools/*.py; then exit 1; fi`
Expected: exit 0. No central policy source names Argus (AC1). The guard README names only the test, as it names the arcwave test.

- [ ] **Step 5: Commit**

```bash
git add tests/test_claude_permission_guard.py home/common/claude-code/README.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "test(issue-552/T4): an Argus-shaped project merges under the plan-gated floor" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"981fb167ad76a28e64aec4ea9bd99f4a213a1b21","head":"13a30c6d28b10aa522c884f9340dd7b2d591a624"}],"commit_subject_bytes":[64,64,64,64],"id":4,"records":[{"bounds":[{"added_lines":350,"boundary":"all","deleted_lines":18,"record_bytes":46080,"support":{"covers":["r2d","r3b","r4a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4a","last_task":4,"owner":4,"path":"tests/test_claude_permission_guard.py"},{"bounds":[{"added_lines":12,"boundary":"all","deleted_lines":8,"record_bytes":60416,"support":{"covers":["r2e","r3c","r4b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4b","last_task":4,"owner":4,"path":"home/common/claude-code/README.md"}]}}
```
