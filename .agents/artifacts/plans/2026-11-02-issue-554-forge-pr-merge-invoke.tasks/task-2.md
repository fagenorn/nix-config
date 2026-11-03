# Task 2: `pr_merge` supported — descriptor, floor, prechecks, guarded merge

Per D2, D4, D5, D6, D7, D13, D16 and D17; spec §1, §3, §4 and §6. Read the plan root's Global Constraints first. `tag` and `release` keep targeting `candidate.commit` here; Task 3 retargets them.

**Files:**
- Modify: `python/agent_tools/forge_adapter.py` (module docstring, `describe`, `REQUIRED`, `_parameters_problem`, `_protection`, `_inspect_pr_merge`, `_invoke`, `_mutate`; new `_protection_facts`, `_floor_problem`, `_merge_outcome`, `_invoke_pr_merge`)
- Modify: `tests/fixtures/forge-adapter-spellings.json` (drop `canonical.head`; add rows `pr_merge.merge` and `pr_merge.head_auto_delete`)
- Modify: `tests/forge_world.py` (`FLOOR_PROTECTION`; `canonical`; `verification_ready`; new `merge_ready`)
- Modify: `tests/test_forge_adapter.py` (`PrMergeInspectTest`, `InspectFailureTest.test_invalid_parameters_make_no_call`, delete `InvokeFailureTest.test_pr_merge_is_refused_before_any_call`, new `PrMergeInvokeTest`)
- Modify: `tests/release_test_support.py` (delete `merge_descriptors`), `tests/test_release_profile.py` (`MergeBindingTest.compiled` uses `support.descriptors()`)
- Modify: `tests/test_release_grammar.py` (descriptor pin; `test_each_rule`; new `MergeProfileTest`)
- Modify: `tests/test_release_adapter_core.py` (`test_prior_descriptors_and_forge_profiles_keep_their_base_digests`)
- Modify: `tests/test_release_command.py` (`AdapterInspectTest.test_reads_a_live_pull_request_through_the_adapter`)
- Modify: `tests/test_claude_permission_guard.py` (`test_every_adapter_spelling_is_an_allowed_row`; new `test_the_adapter_merge_spelling_refuses_its_near_misses`)
- Modify: `python/README.md` (§ Release adapters: the forge paragraph's first sentence, and one new paragraph after it)

**Interfaces:**
- Consumes: Task 1's `CANDIDATE_MEMBERS`, `binds_merge`, `release_test_support.MERGE`, `merge_profile()`.
- Produces:
  - `describe()["operations"]["pr_merge"]`: `mode: materialize`, `support: supported`, `inspect: supported`, `reason: None`, `mutability: pointer_cas`, `effects: ["irreversible"]`, `recovery_capable: False`, `candidate_members: ["merge"]`.
  - `REQUIRED["pr_merge"] == ("target", "candidate")`. For `pr_merge`, `candidate` is exactly `{version, commit, merge}`. For `tag` and `release`, it is `{version, commit}` or `{version, commit, merge}`. `merge` has the same rule as `release_profile` (`type(pr) is int`, `pr >= 1`, `base_tip` 40 lowercase hex). Any other shape is `parameters_invalid` on inspect and `invalid_input` on invoke.
  - `_protection_facts(status, payload) -> {"status", "strict", "required_contexts", "enforce_admins"}`. `status` is `"ok"`, `404` (`unprotected`) or `403` (`inaccessible`). `strict` is `required_status_checks.strict is True`, and it is `False` for 404 and 403. Inspect's `_protection` and invoke's floor read both use it.
  - `_floor_problem(facts) -> str | None`: the first unmet member of `unprotected`, `inaccessible`, `strict`, `required_contexts` and `enforce_admins`.
  - `_merge_outcome(state, base, parents, parameters) -> tuple[str, str]`: the one home of the rule (spec §4 table). A base other than `target.branch` is `diverged/base_mismatch`; `OPEN` is `absent/pr_open`; `CLOSED` is `diverged/pr_closed`; `MERGED` with `parents == [merge.base_tip, candidate.commit]` is `satisfied/observed`; anything else is `diverged/merge_parents_mismatch`. Task 3 calls it to resolve the released commit.
  - `forge_world.FLOOR_PROTECTION`: `{"required_status_checks": {"strict": True, "contexts": ["Nix Eval", "Instruction Budget"], "checks": [{"context": "Nix Eval", "app_id": None}, {"context": "Instruction Budget", "app_id": None}]}, "enforce_admins": {"enabled": True}}`. With its default `checks`, `verification_ready` registers this same payload, because it now adds `"enforce_admins": {"enabled": True}`.
  - `ForgeWorld.merge_ready(*, protection=FLOOR_PROTECTION, auto_delete="false", pr_state="OPEN", pr_base=CANONICAL["branch"], pr_head=CANONICAL["commit"], base_tip=CANONICAL["base_tip"], merge_exit=0, merge_stderr="", merge_sleep=0.0)` registers, on the fixture rows' argv, the pr_merge invoke path:
    - `protection`: a dict is answered as JSON; `404` and `403` use `not_found` and `forbidden`; `"fail"` exits 1 with `gh: Internal Server Error (HTTP 500)`; `"timeout"` answers `FLOOR_PROTECTION` after 6 s.
    - `pr_merge.head_auto_delete` answers `auto_delete + "\n"`.
    - `pr_merge.view` answers `{"state": pr_state, "baseRefName": pr_base, "headRefName": "dev", "headRefOid": pr_head, "mergeCommit": None, "url": "https://github.com/<slug>/pull/<pr>", "statusCheckRollup": []}`.
    - `pr_merge.base_ref` answers `{"object": {"sha": base_tip}}`.
    - `pr_merge.merge` answers with `merge_exit`, `merge_stderr` and `merge_sleep`.
  - Fixture rows (D17), with no `canonical.head`:
    - `pr_merge.merge` (`operation: pr_merge`, `kind: mutation`): raw `gh pr merge 336 --repo fagenorn/nix-config --merge --match-head-commit 1111111111111111111111111111111111111111`.
    - `pr_merge.head_auto_delete` (`operation: pr_merge`, `kind: read`): raw `gh api repos/fagenorn/nix-config --jq .delete_branch_on_merge`.
    - Each row's `argv` is `shlex.split(raw)`.

**Invariants:**
- `pr_merge` invoke order is fixed (spec §3; D6, D13). It stops at the first refusal:
  1. request shape;
  2. `git rev-parse --show-toplevel`;
  3. same repository;
  4. protection read (`pr_merge.protection` on `target.branch`) and the floor;
  5. `pr_merge.head_auto_delete`, which must print exactly `false`;
  6. `pr_merge.view` (state `OPEN`, then `baseRefName == target.branch`, then `headRefOid == candidate.commit`);
  7. `pr_merge.base_ref` on `target.branch`, which must be `merge.base_tip`;
  8. render (`argv == ["gh", "pr", "merge", str(pr), "--repo", slug, "--merge", "--match-head-commit", commit]`, `raw = " ".join(argv)`, `shlex.split(raw) == argv`, else `invalid_input`);
  9. the guard;
  10. one mutation.
- Refusals in steps 4–7 are `rejected`/`precondition_failed`, with references exactly `protection_floor_unmet: <member>`, `head_auto_delete_on`, `pr_not_open: <STATE>`, `pr_base_mismatch: <base>`, `pr_head_mismatch: <oid>` and `base_moved: <tip>`. A failed read is `rejected`: a timeout is `transient_transport`, and anything else (non-zero exit, unparsable JSON, a missing field, a missing `gh`) is `provider_unavailable`. None of them reaches the guard or `gh pr merge`.
- The mutation: exit 0 is `accepted` with reference `https://github.com/<slug>/pull/<pr>`. A spawn failure is `rejected`/`provider_unavailable`. A timeout or any non-zero exit is `unknown`/`transient_transport`, whatever stderr says. The `already exists` and `HTTP 422` markers stay `tag` and `release` only.
- Every child runs with `GITHUB_TOKEN` and `GH_TOKEN` removed. `tag` and `release` invoke, their spellings and their tests are unchanged.
- Inspect `pr_merge` reads what base reads, and its facts' `protection` gains `strict`. Its outcome is `_merge_outcome`'s.
- `lifecycle_guard.py` is unchanged. Its release arm admits the `pr_merge.merge` row only for the declared integration branch into the default branch.

- [ ] **Step 1: Write the failing tests**

Update the fixture and `forge_world` per Interfaces. In `canonical()`, use `values["commit"]` wherever `values["head"]` was, and register `FLOOR_PROTECTION` for `pr_merge.protection`. Drop `head` from its overrides docstring. In `tests/test_forge_adapter.py`, add `from . import forge_world`, `MERGE = {"pr": C["pr"], "base_tip": C["base_tip"]}` and `MERGE_CANDIDATE = {**CANDIDATE, "merge": MERGE}`, then make these changes:

- `PrMergeInspectTest.pr()` defaults `headRefOid` to `C["commit"]`, `parents` to `(C["base_tip"], C["commit"])` and protection to `forge_world.FLOOR_PROTECTION`. `request()` is `effect("pr_merge", candidate=MERGE_CANDIDATE)`. In `test_states_and_protection_facts`, every `C["head"]` becomes `C["commit"]`. `test_the_facts_are_the_demo_readback` expects `head_oid: C["commit"]` and `protection: {"status": "protected", "strict": True, "required_contexts": ["Instruction Budget", "Nix Eval"], "enforce_admins": True}`. Add this test:

```python
    def test_a_merge_onto_a_moved_base_is_diverged(self):
        """Issue 554 row 9: GitHub merged onto a base the head already contained."""
        self.pr("MERGED", parents=("6" * 40, C["commit"]))
        observation = self.inspect(self.request())
        self.assertEqual((observation["outcome"], observation["reason"]),
                         ("diverged", "merge_parents_mismatch"))
```

- In `test_invalid_parameters_make_no_call`, the two `pr_merge` cases become `effect("pr_merge", candidate=CANDIDATE)`, `effect("pr_merge", candidate={**CANDIDATE, "merge": {**MERGE, "pr": True}})`, `effect("pr_merge", candidate={**CANDIDATE, "merge": {**MERGE, "base_tip": "5" * 39}})` and `effect("pr_merge", pr=C["pr"], expected_base_tip=C["base_tip"], expected_head=C["commit"])`.
- Delete `test_pr_merge_is_refused_before_any_call` and add:

```python
class PrMergeInvokeTest(InvokeCase):
    """Issue 554 spec §3: every refusal comes before the guard and the merge."""

    def setUp(self):
        super().setUp()
        self.world.invoke_ready()

    def merge(self, candidate=MERGE_CANDIDATE):
        result = forge_adapter.invoke({"kind": "effect", "operation": "pr_merge",
                                       "parameters": {"target": TARGET, "candidate": candidate}})
        self.assertEqual(release_adapter.invoke_result_problems(result), [])
        return result

    def guards(self):
        return [c for c in self.world.calls() if c["tool"] == "claude-bash-lifecycle-guard"]

    def merges(self):
        return [c for c in self.world.calls() if c["tool"] == "gh" and c["argv"][:2] == ["pr", "merge"]]

    def refused(self, reference, **ready):
        self.world.merge_ready(**ready)
        self.assertEqual(self.merge(), {"result": "rejected", "error_class": "precondition_failed",
                                        "reference": reference})
        self.assertEqual((self.guards(), self.merges()), ([], []))

    def test_the_happy_path_renders_the_fixture_row_and_passes_the_guard(self):
        self.world.merge_ready()
        self.assertEqual(self.merge(), {"result": "accepted", "error_class": None,
                                        "reference": f"https://github.com/{C['slug']}/pull/{C['pr']}"})
        [merge] = self.merges()
        self.assertEqual(["gh", *merge["argv"]], ROWS["pr_merge.merge"]["argv"])
        [guard] = self.guards()
        self.assertEqual(json.loads(guard["stdin"])["tool_input"]["command"], ROWS["pr_merge.merge"]["raw"])
        reads = [c["argv"] for c in self.world.calls() if c["tool"] == "gh" and c["argv"][:2] != ["pr", "merge"]]
        self.assertEqual(reads, [ROWS[i]["argv"][1:] for i in (
            "invoke.repository", "pr_merge.protection", "pr_merge.head_auto_delete",
            "pr_merge.view", "pr_merge.base_ref")])
        self.assertFalse(any(c["token_visible"] for c in self.world.calls()))

    def test_a_protection_floor_gap_refuses_before_the_guard(self):
        """Issue 554 row 1."""
        floor = forge_world.FLOOR_PROTECTION
        checks = floor["required_status_checks"]
        for member, protection in (
                ("strict", {**floor, "required_status_checks": {**checks, "strict": False}}),
                ("strict", {**floor, "required_status_checks": None}),
                ("required_contexts", {**floor, "required_status_checks": {**checks, "contexts": []}}),
                ("enforce_admins", {**floor, "enforce_admins": {"enabled": False}}),
                ("unprotected", 404), ("inaccessible", 403)):
            with self.subTest(member=member, protection=protection):
                self.world.reset()
                self.world.invoke_ready()
                self.refused(f"protection_floor_unmet: {member}", protection=protection)

    def test_a_failed_protection_read_refuses_with_no_mutation(self):
        """Issue 554 row 2."""
        for protection, error_class in (("fail", "provider_unavailable"), ("timeout", "transient_transport")):
            with self.subTest(protection=protection):
                self.world.reset()
                self.world.invoke_ready()
                self.world.merge_ready(protection=protection)
                saved = forge_adapter.CHILD_TIMEOUT_SECONDS
                forge_adapter.CHILD_TIMEOUT_SECONDS = 2
                try:
                    result = self.merge()
                finally:
                    forge_adapter.CHILD_TIMEOUT_SECONDS = saved
                self.assertEqual((result["result"], result["error_class"]), ("rejected", error_class))
                self.assertEqual((self.guards(), self.merges()), ([], []))

    def test_head_auto_delete_refuses_before_the_guard(self):
        """Issue 554 row 15."""
        for answer in ("true", "null", ""):
            with self.subTest(answer=answer):
                self.world.reset()
                self.world.invoke_ready()
                self.refused("head_auto_delete_on", auto_delete=answer)

    def test_a_pr_not_open_on_another_base_or_head_refuses(self):
        """Issue 554 row 3."""
        for ready, reference in ((dict(pr_state="MERGED"), "pr_not_open: MERGED"),
                                 (dict(pr_state="CLOSED"), "pr_not_open: CLOSED"),
                                 (dict(pr_base="release"), "pr_base_mismatch: release"),
                                 (dict(pr_head="9" * 40), "pr_head_mismatch: " + "9" * 40)):
            with self.subTest(reference=reference):
                self.world.reset()
                self.world.invoke_ready()
                self.refused(reference, **ready)

    def test_a_moved_base_refuses_base_moved(self):
        """Issue 554 row 4."""
        self.refused("base_moved: " + "6" * 40, base_tip="6" * 40)

    def test_a_guard_denial_is_authorization_denied(self):
        """Issue 554 row 5."""
        self.world.invoke_ready(guard_exit=2)
        self.world.merge_ready()
        result = self.merge()
        self.assertEqual((result["result"], result["error_class"]), ("rejected", "authorization_denied"))
        self.assertEqual((len(self.guards()), self.merges()), (1, []))

    def test_any_failed_merge_is_unknown_without_parsing_stderr(self):
        """Issue 554 D6."""
        for stderr in ("GraphQL: Head branch is out of date (mergePullRequest)", "HTTP 422: x", ""):
            with self.subTest(stderr=stderr):
                self.world.reset()
                self.world.invoke_ready()
                self.world.merge_ready(merge_exit=1, merge_stderr=stderr)
                result = self.merge()
                self.assertEqual((result["result"], result["error_class"]), ("unknown", "transient_transport"))
                self.assertEqual(len(self.merges()), 1)
        self.world.reset()
        self.world.invoke_ready()
        self.world.merge_ready(merge_sleep=6)
        saved = forge_adapter.CHILD_TIMEOUT_SECONDS
        forge_adapter.CHILD_TIMEOUT_SECONDS = 2
        try:
            result = self.merge()
        finally:
            forge_adapter.CHILD_TIMEOUT_SECONDS = saved
        self.assertEqual((result["result"], result["error_class"]), ("unknown", "transient_transport"))

    def test_an_unspawnable_merge_is_rejected(self):
        self.world.merge_ready()
        real = subprocess.run

        def run(argv, *args, **kwargs):
            if argv[:3] == ["gh", "pr", "merge"]:
                raise PermissionError(13, "Permission denied", argv[0])
            return real(argv, *args, **kwargs)
        with mock.patch.object(forge_adapter.subprocess, "run", side_effect=run):
            result = self.merge()
        self.assertEqual((result["result"], result["error_class"]), ("rejected", "provider_unavailable"))

    def test_a_malformed_merge_or_another_repository_refuses_early(self):
        for candidate in (CANDIDATE, {**CANDIDATE, "merge": {**MERGE, "pr": 0}}):
            with self.subTest(candidate=candidate):
                self.world.reset()
                result = self.merge(candidate)
                self.assertEqual((result["result"], result["error_class"]), ("rejected", "invalid_input"))
                self.assertEqual(self.world.calls(), [])
        self.world.reset()
        self.world.invoke_ready(slug="someone-else/nix-config")
        self.world.merge_ready()
        self.assertEqual(self.merge()["error_class"], "precondition_failed")
        self.assertNotIn(ROWS["pr_merge.protection"]["argv"][1:], self.world.argvs("gh"))
```

In `tests/test_release_grammar.py`:
- Rename the descriptor pin to `test_forge_descriptor_pins_pr_merge_supported`, asserting `(mode, support, inspect, reason, mutability, effects, recovery_capable, candidate_members) == ("materialize", "supported", "supported", None, "pointer_cas", ["irreversible"], False, ["merge"])`.
- Delete the `act(operation="pr_merge", mode="materialize")` case from `test_each_rule`.
- Add this class:

```python
class MergeProfileTest(unittest.TestCase):
    def test_the_jarbird_shaped_profile_compiles(self):
        """Issue 554 AC1: pr_merge -> tag -> github-release on one GitHub target."""
        self.assertEqual(violations(support.release_of("two-branch", support.merge_profile())), [])
        compiled = release_profile.compile_profile("two-branch", support.merge_profile(),
                                                   support.base_contract(), support.descriptors())
        self.assertEqual([n["id"] for n in compiled["publication"]], ["merge", "tag", "github-release"])
        self.assertTrue(release_profile.binds_merge(compiled))
```

In `tests/test_claude_permission_guard.py`, `test_every_adapter_spelling_is_an_allowed_row` runs the `pr_merge.merge` row with `FAKE_PR_JSON = json.dumps({**self.RELEASE_PR, "headRefOid": <canonical commit>, "url": f"https://github.com/{slug}/pull/336"})` added to the class env. It expects exit 0 for that row only in `distinct-integration`, and exit 2 in the other three classes. Every other row keeps `authorized or kind == "read"`. Extend the docstring with "issue 554 D5: the merge row is admitted only as the release arm's integration-into-default merge". Add:

```python
    def test_the_adapter_merge_spelling_refuses_its_near_misses(self):
        """Issue 554 D5: only the exact rendered spelling passes the release arm."""
        commit = self.SPELLINGS["canonical"]["commit"]
        row = next(r for r in self.SPELLINGS["rows"] if r["id"] == "pr_merge.merge")
        good = row["raw"].replace(self.CANONICAL_SLUG, NODO)
        repo = self.tagged_repo(NODO)
        env = {"FAKE_PR_JSON": json.dumps({**self.RELEASE_PR, "headRefOid": commit,
                                           "url": f"https://github.com/{NODO}/pull/336"})}
        self.assertEqual(0, self.run_guard(good, cwd=repo, env=env).returncode)
        for label, command in (
                ("admin", good + " --admin"), ("auto", good.replace(" --merge", " --auto --merge")),
                ("squash", good.replace("--merge", "--squash")), ("rebase", good.replace("--merge", "--rebase")),
                ("delete-branch", good + " --delete-branch"),
                ("reordered", f"gh pr merge 336 --merge --repo {NODO} --match-head-commit {commit}"),
                ("short sha", good.replace(commit, commit[:7])),
                ("no repo", good.replace(f" --repo {NODO}", "")), ("trailing", good + " extra")):
            with self.subTest(label):
                self.assertEqual(2, self.run_guard(command, cwd=repo, env=env).returncode)
```

The canonical commit is all digits, so an uppercase near miss would equal it; the existing `head uppercase` case already covers that spelling. If the unchanged guard refuses the row in `distinct-integration`, stop and report it: D5 rests on the release arm admitting that spelling as it is, and this plan never edits `lifecycle_guard.py`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_adapter.py tests/test_release_grammar.py 2>&1 | tail -4'`
Expected: FAIL. `PrMergeInvokeTest` gets `unsupported_operation`, the inspect requests are `parameters_invalid`, and the grammar refuses `merge_profile`.

Run: `bash -c 'set -o pipefail; python3 -m unittest tests/test_claude_permission_guard.py -k adapter 2>&1 | tail -4'`
Expected: FAIL. The base table expects `pr_merge.merge` admitted in `default-only`.

- [ ] **Step 3: Write the minimal implementation**

Implement the Interfaces and Invariants in `forge_adapter.py`. The protection read in invoke goes through `_gh(argv, time.monotonic() + CHILD_TIMEOUT_SECONDS)`, so `404` and `403` reach `_protection_facts`. `lookup_timeout` maps to `transient_transport`, and every other non-`ok` status to `provider_unavailable`. The other precondition reads use `_precondition_read`. JSON that does not parse, or a field that is missing or of the wrong type, is `rejected`/`provider_unavailable`. `_inspect_pr_merge` reads `merge` and `commit` from `candidate` and decides through `_merge_outcome`. In the module docstring, `describe()` declares `pr_merge` supported, and `invoke` lists the `pr_merge` steps (issue 554 D4, D6, D13). Replace the descriptor pin's "unsupported" sentence.

Delete `merge_descriptors` from `release_test_support.py`. Task 1's `MergeBindingTest.compiled` then uses `support.descriptors()`.

Update `tests/test_release_command.py::AdapterInspectTest::test_reads_a_live_pull_request_through_the_adapter`. It sends `parameters = {"target": …, "candidate": {"version": CANONICAL["tag"], "commit": CANONICAL["commit"], "merge": {"pr": CANONICAL["pr"], "base_tip": CANONICAL["base_tip"]}}}`, answers `headRefOid: CANONICAL["commit"]`, registers `forge_world.FLOOR_PROTECTION`, and also asserts `observation["facts"]["protection"]["strict"] is True`.

Re-measure (D16), with `PYTHONPATH="$PWD/python" python3 -c 'from agent_tools import release_adapter, release_profile; …'` from the worktree root and `tests/release_test_support.py` imported the way the test imports it. Replace in `test_prior_descriptors_and_forge_profiles_keep_their_base_digests` exactly the literals that changed. `github-actions-health` must keep its base digest; if it changed, stop and report. Append "; github-forge values re-measured for issue 554 D16" to its docstring.

`python/README.md` § Release adapters: in the forge paragraph, replace "declares `pr_merge` as `unsupported` with reason `target_cas_unproven`, so a profile that names it is a grammar violation, and carries" with "carries `pr_merge` (`materialize`, `pointer_cas`, supported since issue 554 D4, `candidate_members` `["merge"]`) and". Then insert one new paragraph right after that paragraph, describing exactly the Invariants above as implemented:
- the `merge` member and the expected head;
- the four prechecks, each with its reference;
- the rendered spelling and the flags it never renders;
- `accepted` with the PR URL, and `unknown` for any other exit;
- inspect's `protection.strict` and its exact-parents `satisfied`.

Cite issue 554 D4, D6, D7, D13 and D17. In the forge paragraph, the sentence "There are two mutation spellings: …" becomes three: it adds `gh pr merge <pr> --repo <slug> --merge --match-head-commit <commit>`. The following clause, "`already exists` (git) or `HTTP 422` (gh) is `precondition_failed`", is scoped to `tag` and `release`, because a failed `pr_merge` is `unknown` (PR554-06).

- [ ] **Step 4: Verify**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_adapter.py tests/test_release_grammar.py tests/test_release_profile.py tests/test_release_adapter_core.py tests/test_release_command.py tests/test_release_driver.py tests/test_release_crash_matrix.py tests/test_release_verification.py 2>&1 | tail -4'`
Expected: PASS, `OK`.

Run: `bash -c 'set -o pipefail; python3 -m unittest tests/test_claude_permission_guard.py 2>&1 | tail -4'`
Expected: PASS, `OK`.

Run: `if git grep -nE 'target_cas_unproven|expected_head|expected_base_tip' -- python/agent_tools/forge_adapter.py tests/forge_world.py tests/test_release_command.py; then exit 1; fi`
Expected: exit 0. The scope is production code and the world. `tests/test_forge_adapter.py` keeps the old-shape rejection case on purpose.

Run: `if git grep -n '"head"' -- tests/fixtures/forge-adapter-spellings.json; then exit 1; fi`
Expected: exit 0 (`canonical.head` is gone).

Run (timeout 3600 s): `just build`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/forge_adapter.py tests/fixtures/forge-adapter-spellings.json tests/forge_world.py tests/test_forge_adapter.py tests/release_test_support.py tests/test_release_profile.py tests/test_release_grammar.py tests/test_release_adapter_core.py tests/test_release_command.py tests/test_claude_permission_guard.py python/README.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(issue-554/T2): support forge pr_merge behind its floor" -m "<trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"2f00e5138d399c29a2851d953f526fa56191dbea","head":"7f236840000d5ed15aae3467ee962f6124508496"}],"commit_subject_bytes":[64,64,64],"id":2,"records":[{"bounds":[{"added_lines":180,"boundary":"all","deleted_lines":40,"record_bytes":26624,"support":{"covers":["r2a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2a","last_task":3,"owner":2,"path":"python/agent_tools/forge_adapter.py"},{"bounds":[{"added_lines":32,"boundary":"all","deleted_lines":2,"record_bytes":3072,"support":{"covers":["r2b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2b","last_task":3,"owner":2,"path":"tests/fixtures/forge-adapter-spellings.json"},{"bounds":[{"added_lines":55,"boundary":"all","deleted_lines":10,"record_bytes":7168,"support":{"covers":["r2c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2c","last_task":4,"owner":2,"path":"tests/forge_world.py"},{"bounds":[{"added_lines":200,"boundary":"all","deleted_lines":30,"record_bytes":26624,"support":{"covers":["r2d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2d","last_task":3,"owner":2,"path":"tests/test_forge_adapter.py"},{"bounds":[{"added_lines":35,"boundary":"all","deleted_lines":0,"record_bytes":4096,"support":{"covers":["r1c","r2e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2e","last_task":2,"owner":2,"path":"tests/release_test_support.py"},{"bounds":[{"added_lines":70,"boundary":"all","deleted_lines":2,"record_bytes":8192,"support":{"covers":["r1e","r2f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2f","last_task":2,"owner":2,"path":"tests/test_release_profile.py"},{"bounds":[{"added_lines":16,"boundary":"all","deleted_lines":6,"record_bytes":3072,"support":{"covers":["r2g"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2g","last_task":2,"owner":2,"path":"tests/test_release_grammar.py"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":4,"record_bytes":3072,"support":{"covers":["r2h"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2h","last_task":2,"owner":2,"path":"tests/test_release_adapter_core.py"},{"bounds":[{"added_lines":8,"boundary":"all","deleted_lines":8,"record_bytes":3072,"support":{"covers":["r2i"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2i","last_task":4,"owner":2,"path":"tests/test_release_command.py"},{"bounds":[{"added_lines":45,"boundary":"all","deleted_lines":10,"record_bytes":10240,"support":{"covers":["r2j"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2j","last_task":2,"owner":2,"path":"tests/test_claude_permission_guard.py"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":2,"record_bytes":36864,"support":{"covers":["r1f","r2k"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2k","last_task":5,"owner":2,"path":"python/README.md"}]}}
```
