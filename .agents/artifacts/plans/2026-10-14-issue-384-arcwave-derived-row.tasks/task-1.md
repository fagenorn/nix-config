# Task 1: Drop the Arcwave literal and prove its derived row in the suites

Spec § Solution, § Decisions and § Test seams, per D1, D2, D3 and D4. After this task the built base policy's `integration_bases` is `{}`, and the guard suite proves that a project shaped like Arcwave is derived against that base and judged through its compiled row.

**Files:**
- Modify: `home/common/claude-code/default.nix` (`integrationBases` and its comment only)
- Modify: `home/common/claude-code/README.md` (§ Guard policy, the base-policy paragraph only)
- Modify: `tests/test_claude_permission_guard.py` (`test_built_base_policy_holds_exactly_the_five_trusted_members`, `test_a_row_beside_a_literal_integration_base_is_refused`, new `test_an_arcwave_shaped_project_is_judged_by_its_compiled_row`)
- Modify: `tests/guard_policy_world.py` (`GuardPolicyWorld.write_base` default)
- Modify: `tests/test_guard_policy.py` (`test_literal_conflict_withholds_the_derived_row_only`)

**Interfaces:**
- Consumes (existing, unchanged): in the guard suite, `BASE_POLICY_PATH`, `self.base_policy`, `self.write_base(**members) -> Path`, `self.write_policy(**members) -> Path`, `self.make_repo(origin) -> Path`, `self.run_guard(command, cwd=, env=, guard_args=, timeout=)`, `self.release_env(**overrides) -> dict` (overrides replace members of the release PR JSON; protection is poisoned), `self.fake_gh`; `GuardPolicyWorld(test_case)`, `.project(project_id, slug, *, integration_branch=, publication_free=)`, `.compile(*, base=) -> (exit, report, stderr)` where `report["derived"]` is a sorted slug list and `report["refused"]` a list of `{project_id, reason_code, …}`, `.policy() -> dict`, `.output`, `.row_check() -> Path`.
- Produces: the built base policy with `integration_bases == {}`; the new guard-suite test named above (Task 2 and the acceptance map cite it).

**Invariants:**
- The built base policy keeps exactly the five members `authorized_owners`, `integration_bases`, `git_bin`, `gh_bin`, `jq_bin` (D1).
- `default.nix` names neither `elevenyellow` nor `fagenorn/arcwave` (D3).
- No test reads a literal row from the built base policy; a test that needs one writes it into a fixture base (D2).
- `lifecycle_guard.py`, `python/agent_tools/` and the adversarial table are untouched.

- [ ] **Step 1: Write the tests**

In `tests/test_claude_permission_guard.py`, replace the body of `test_built_base_policy_holds_exactly_the_five_trusted_members` with:

```python
    def test_built_base_policy_holds_exactly_the_five_trusted_members(self):
        """Issue 377 R1, R5; issue 384 D3: the store file holds the trusted members and no
        literal integration row, since every repository with one is a registered project."""
        self.assertEqual({"authorized_owners", "integration_bases", "git_bin", "gh_bin", "jq_bin"},
                         set(self.base_policy))
        self.assertEqual(["fagenorn"], self.base_policy["authorized_owners"])
        self.assertEqual({}, self.base_policy["integration_bases"])
        for member, name in (("git_bin", "git"), ("gh_bin", "gh"), ("jq_bin", "jq")):
            self.assertRegex(self.base_policy[member], rf"^/nix/store/[^/]+/bin/{name}$")
        source = Path(__file__).resolve().parents[1] / "home/common/claude-code/default.nix"
        text = source.read_text(encoding="utf-8")
        self.assertEqual([], [name for name in ("elevenyellow", "fagenorn/arcwave")
                              if name in text])
```

Replace `test_a_row_beside_a_literal_integration_base_is_refused` with (the fixture slug is neutral and under the authorized owner, per D2):

```python
    def test_a_row_beside_a_literal_integration_base_is_refused(self):
        """Issue 377 D5: the compiled policy cannot recast a literal repository."""
        slug = "fagenorn/literal-fixture"
        base = self.write_base(integration_bases={slug: "dev"})
        policy = self.write_policy(derivation={}, derived_repositories={
            slug: {"default_branch": "trunk", "integration_branch": "release", "evidence": {}}})
        args = ("--gh-bin", str(self.fake_gh), "--base-policy", str(base),
                "--policy", str(policy))
        repo = self.make_repo(f"git@github.com:{slug}.git")
        for label, command in (
            ("push", "git push -u origin topic"),
            ("PR creation", f'gh pr create --repo {slug} --base release --head t '
                            '--title "x" --body "y"'),
            ("merge", f"gh pr merge 7 --repo {slug} --merge --delete-branch"),
        ):
            with self.subTest(verb=label):
                result = self.run_guard(command, cwd=repo, guard_args=args)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(
                    f"lifecycle guard: unsafe {label}: repository {slug} has both a literal "
                    "integration base and a derived policy row; repair: run claude-guard-policy",
                    result.stderr)
        literal_only = self.run_guard("git push -u origin topic", cwd=repo, guard_args=(
            "--gh-bin", str(self.fake_gh), "--base-policy", str(base)))
        self.assertEqual(0, literal_only.returncode, literal_only.stderr)
```

Add directly after `test_a_compiled_policy_round_trips_through_the_guard` (D4):

```python
    def test_an_arcwave_shaped_project_is_judged_by_its_compiled_row(self):
        """Issue 384 D4: a registered project with integration branch `dev` needs no literal.
        Compiled against the built base policy it is derived, not refused, and the guard
        adjudicates its feature and release arms through the confirmed row."""
        slug = "fagenorn/arcwave"
        world = GuardPolicyWorld(self)
        world.project("arcwave", slug, integration_branch="dev", publication_free=True)
        code, report, stderr = world.compile(base=BASE_POLICY_PATH)
        self.assertEqual((0, [slug], []), (code, report["derived"], report["refused"]), stderr)
        row = world.policy()["derived_repositories"][slug]
        self.assertEqual(("main", "dev"), (row["default_branch"], row["integration_branch"]))
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(world.output),
                "--derive-bin", str(world.row_check()), "--derive-timeout-seconds", "25")
        repo = self.make_repo(f"git@github.com:{slug}.git")
        create = self.run_guard(
            f'gh pr create --repo {slug} --base dev --head issue-7-topic '
            '--title "x" --body "y"', cwd=repo, guard_args=args, timeout=60)
        self.assertEqual(0, create.returncode, create.stderr)
        feature_pr = json.dumps({"state": "OPEN", "baseRefName": "dev",
                                 "headRefName": "issue-7-topic",
                                 "url": f"https://github.com/{slug}/pull/7"})
        feature = self.run_guard(
            f"gh pr merge 7 --repo {slug} --merge --delete-branch", cwd=repo, guard_args=args,
            env={"FAKE_PR_JSON": feature_pr, "FAKE_PROTECTION_MODE": "nonzero"}, timeout=60)
        self.assertEqual(0, feature.returncode, feature.stderr)
        release = f"gh pr merge 1 --repo {slug} --merge"
        url = f"https://github.com/{slug}/pull/1"
        green = self.run_guard(release, cwd=repo, guard_args=args, timeout=60,
                               env=self.release_env(url=url))
        self.assertEqual(0, green.returncode, green.stderr)
        red = self.run_guard(release, cwd=repo, guard_args=args, timeout=60,
                             env=self.release_env(url=url, statusCheckRollup=[
                                 {"__typename": "CheckRun", "status": "COMPLETED",
                                  "conclusion": "FAILURE"}]))
        self.assertEqual(2, red.returncode, red.stderr)
        unrelated = self.make_repo("git@github.com:acme/unrelated.git")
        refused = self.run_guard("git push -u origin topic", cwd=unrelated, guard_args=args,
                                 timeout=60)
        self.assertEqual(2, refused.returncode)
        self.assertIn("repository acme/unrelated is outside standing authorization",
                      refused.stderr)
```

In `tests/guard_policy_world.py`, `GuardPolicyWorld.write_base`: change the default `"integration_bases": {"fagenorn/arcwave": "dev"}` to `"integration_bases": {}` (D2).

In `tests/test_guard_policy.py`, `test_literal_conflict_withholds_the_derived_row_only`: replace the literal `"fagenorn/arcwave": "dev"` with `"fagenorn/literal-only": "dev"`, keeping `"fagenorn/one": "dev"` and every assertion.

- [ ] **Step 2: Watch the guard suite fail against the unchanged Nix**

Run: the guard-suite invocation with `-k test_built_base_policy_holds_exactly_the_five_trusted_members -k test_an_arcwave_shaped_project_is_judged_by_its_compiled_row -k test_a_row_beside_a_literal_integration_base_is_refused` (timeout 3600 s).
Expected: `FAILED (failures=2)`: the five-member test (`{} != {'fagenorn/arcwave': 'dev'}`) and the Arcwave round trip (compile exit 1, `fagenorn/arcwave` refused as `literal_conflict`). The literal-fixture test passes. Any other result means the tests do not pin this change; stop.

(Planning dry-ran these three tests at `0cc5768b`: against the built base policy they failed exactly so; against a copy with `integration_bases` `{}` only the source assertion failed, since `default.nix` still named Arcwave, and the round trip and the literal-fixture test passed.)

- [ ] **Step 3: Remove the literal**

In `home/common/claude-code/default.nix`:
- Replace the `integrationBases` attrset (the Arcwave comment lines, beginning "arcwave is a private free-plan repository", and the `"fagenorn/arcwave" = "dev";` entry) with `integrationBases = { };`.
- In the general comment above it, append two sentences to its first paragraph, the one ending "and the default branch stays acceptable everywhere." (D1): "The set is empty: every repository that has an integration branch is a registered project with a derived row. Add a row only for one that is not." Rewrap to the file's comment width. Leave every other comment line, `lifecycleGuardBasePolicy` and its comment unchanged.

In `home/common/claude-code/README.md` § Guard policy, the paragraph defining the base policy: change "(an `integration_bases` row exists only for a repository that is not a registered project)" to "(an `integration_bases` row exists only for a repository that is not a registered project, and the built set is currently empty)". Nothing else in the README changes.

- [ ] **Step 4: Verify**

Run: the guard-suite invocation (full suite, timeout 3600 s).
Expected: `OK`; the adversarial table included.

Run: the `tests/test_guard_policy.py` run (timeout 900 s).
Expected: `OK`.

Run (gate on content, timeout 60 s):

```bash
set -e
if git grep -n 'fagenorn/arcwave' -- home/common/claude-code/default.nix home/common/claude-code/README.md tests/guard_policy_world.py tests/test_guard_policy.py; then exit 1; fi
grep -q 'integrationBases = { };' home/common/claude-code/default.nix
git diff --quiet 0cc5768b -- home/common/claude-code/lifecycle_guard.py python/agent_tools
```

Expected: exit 0. Each line fails at the starting commit or on a stray edit.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/default.nix home/common/claude-code/README.md tests/test_claude_permission_guard.py tests/guard_policy_world.py tests/test_guard_policy.py
launch-commit … -- -m "fix(guard-policy): judge Arcwave by its derived row, not a literal (issue 384)"
```

Verify: `git show --stat HEAD -- home/common/claude-code tests | tail -1` reports the five files changed.
