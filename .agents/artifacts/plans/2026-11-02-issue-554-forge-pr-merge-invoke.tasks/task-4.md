# Task 4: The preview observes the merge binding

Per D3, D14 and D15; spec §1 (Surfaces) and §2. Read the plan root's Global Constraints first.

**Files:**
- Modify: `python/agent_tools/release_verification.py` (module docstring; new `observe_merge`)
- Modify: `python/agent_tools/release_driver.py` (module docstring, `_candidate`, `_document`, `_new_plan`)
- Modify: `tests/forge_world.py` (new `merge_observation_ready`)
- Modify: `tests/test_release_verification.py` (new `MergeObservationTest`)
- Modify: `tests/test_release_driver.py` (new `MergePreviewTest`)
- Modify: `tests/test_release_command.py` (new `TwoBranchCommandTest`)
- Modify: `python/README.md` (§ Release driver: the candidate sentence of the opening paragraph, the **Verification** paragraph and the **Preview** paragraph)

**Interfaces:**
- Consumes: Task 1's `release_profile.candidate_problem`, `binds_merge`, `bind_candidate`, `release_test_support.MERGE` and `merge_profile()`; Task 2's `ForgeWorld.verification_ready` and `FLOOR_PROTECTION`.
- Produces:
  - `release_verification.observe_merge(*, repository: str, integration_branch: str, default_branch: str, commit: str) -> dict`. It returns `{"pr": int, "base_tip": str}` or raises `VerificationRefused`. It makes these three `gh api <path>` reads in order, through the module's `_read`, under its own `READ_BUDGET_SECONDS` deadline:
    1. `repos/<repository>/pulls?state=open&base=<default>&head=<owner>:<integration>&per_page=2`, where `<owner>` is `repository.split("/")[0]`. It must be a list. An empty list is `release_pr_missing` (detail `no open pull request from <owner>:<integration> into <default>`). Two or more entries, or an entry that is not `{number: int (not bool) >= 1, head: {sha: 40 lowercase hex}}`, is `verification_unavailable`. A head other than `commit` is `release_pr_stale` (detail `pull request <number> is at <sha>, not the candidate <commit>`).
    2. `repos/<repository>/git/ref/heads/<default>`. Its `object.sha` must be 40 lowercase hex, else `verification_unavailable`, and it is `base_tip`.
    3. `repos/<repository>/compare/<base_tip>...<commit>`. `status` must be the string `ahead`. Any other string is `release_pr_behind`, with the exact detail `<integration> is <status> relative to <default> at <base_tip>: merge <default> into <integration>, push, wait for CI and preview again`. A missing or non-string status is `verification_unavailable`.

    Every read failure is `verification_unavailable`, as for `observe`. A refusal stops the later reads.
  - `ForgeWorld.merge_observation_ready(*, prs=None, base_tip=CANONICAL["base_tip"], compare="ahead", slug=CANONICAL["slug"], integration="dev", default=CANONICAL["branch"], commit=CANONICAL["commit"])` registers those three reads (`prs` defaults to `[{"number": CANONICAL["pr"], "head": {"sha": commit, "ref": integration}}]`; the ref answer is `{"object": {"sha": base_tip, "type": "commit"}}`; the compare answer is `{"status": compare}`). The ref read's argv equals the fixture's `pr_merge.base_ref` row for `main`, so it agrees with `merge_ready` on the same `base_tip`.
  - The preview document's `candidate` is `{version, commit, title, merge}`, where `merge` is `{pr, base_tip}` or `null`.

**Invariants:**
- `_new_plan` follows this order:
  1. `candidate_required`.
  2. `release_profile.candidate_problem(dict(candidate))`, which raises `Refusal("candidate_invalid", …)`.
  3. When `binds_merge(self.compiled)`, `observe_merge(repository=self._repository(), integration_branch=project.integration_branch, default_branch=project.default_branch, commit=candidate["commit"])`. A `VerificationRefused` becomes the plan's `refusal` (`Refusal(code, detail)`, `repair_id` null), and then the receipt is not read and `verification` is `null`.
  4. The receipt, as at base.
  5. `version_reserved`, as at base.

  The plan's candidate is `{**candidate, "merge": observed}` when a merge was observed, else the operator's candidate unchanged, so `_create`'s `bind_candidate` gets `merge` exactly when the profile consumes it.
- In mode `new`, the `plan_digest` candidate input gains `"merge": <the plan candidate's merge or None>`. A base tip that moves between `preview` and `run` changes `plan_digest`, so every token is stale (row 12).
- A resumed preview reads `merge` from the stored subject (`_candidate` returns `stored.get("merge")`) and makes no merge read. A profile that consumes no `merge` makes no merge read, and its document's `candidate.merge` is `null`.
- Every refused document still lists the confirmations (128 D18), creates no store and calls no adapter. The preview never duplicates the protection floor (D14).
- `release_verification.observe` is unchanged.

- [ ] **Step 1: Write the failing tests**

Add `merge_observation_ready`. In `tests/test_release_verification.py`:

```python
def observe_merge(**overrides):
    arguments = {"repository": CANONICAL["slug"], "integration_branch": "dev",
                 "default_branch": "main", "commit": CANONICAL["commit"]}
    return verification.observe_merge(**{**arguments, **overrides})


class MergeObservationTest(unittest.TestCase):
    """Issue 554 D3: the one open release PR, the default tip and their compare."""

    def setUp(self):
        self.world = ForgeWorld(self)

    def test_the_open_release_pr_and_the_default_tip_bind(self):
        self.world.merge_observation_ready()
        self.assertEqual(observe_merge(), {"pr": CANONICAL["pr"], "base_tip": CANONICAL["base_tip"]})
        slug, tip, commit = CANONICAL["slug"], CANONICAL["base_tip"], CANONICAL["commit"]
        self.assertEqual([c["argv"] for c in self.world.calls()], [
            ["api", f"repos/{slug}/pulls?state=open&base=main&head=fagenorn:dev&per_page=2"],
            ["api", f"repos/{slug}/git/ref/heads/main"],
            ["api", f"repos/{slug}/compare/{tip}...{commit}"]])
        self.assertFalse(any(c["token_visible"] for c in self.world.calls()))

    def test_each_refusal_names_its_code_and_stops_the_reads(self):
        entry = {"number": CANONICAL["pr"], "head": {"sha": CANONICAL["commit"]}}
        cases = ((dict(prs=[]), "release_pr_missing", 1),
                 (dict(prs=[entry, {**entry, "number": 337}]), "verification_unavailable", 1),
                 (dict(prs=[{**entry, "head": {"sha": "9" * 40}}]), "release_pr_stale", 1),
                 (dict(prs=[{**entry, "number": True}]), "verification_unavailable", 1),
                 (dict(base_tip="5" * 39), "verification_unavailable", 2),
                 (dict(compare="behind"), "release_pr_behind", 3),
                 (dict(compare="diverged"), "release_pr_behind", 3),
                 (dict(compare="identical"), "release_pr_behind", 3))
        for ready, code, reads in cases:
            with self.subTest(ready=ready):
                self.world.reset()
                self.world.merge_observation_ready(**ready)
                with self.assertRaises(verification.VerificationRefused) as caught:
                    observe_merge()
                self.assertEqual((caught.exception.code, len(self.world.calls())), (code, reads))

    def test_behind_says_how_to_repair(self):
        self.world.merge_observation_ready(compare="diverged")
        with self.assertRaises(verification.VerificationRefused) as caught:
            observe_merge()
        self.assertEqual(caught.exception.detail,
                         f"dev is diverged relative to main at {CANONICAL['base_tip']}: merge main "
                         "into dev, push, wait for CI and preview again")
```

In `tests/test_release_driver.py`:

```python
class MergePreviewTest(DriverCase):
    """Issue 554 D3: a two-branch preview observes the release PR before the receipt."""

    def setUp(self):
        super().setUp()
        self.world.verification_ready(integration="dev")
        self.world.merge_observation_ready()

    def two_branch(self):
        return self.driver(rs.project(self, profiles={"two-branch": support.merge_profile()},
                                      integration="dev"))

    def test_a_two_branch_profile_passes_the_shape_gate_and_lists_three_confirmations(self):
        """Issue 554 AC1."""
        driver = self.two_branch()
        self.assertIsNone(driver.shape_refusal())
        document = driver.preview(rs.candidate())
        self.assertEqual((document["runnable"], document["refusal"]), (True, None))
        self.assertEqual([c["action"] for c in document["confirmations"]], ["merge", "tag", "github-release"])
        self.assertEqual(document["candidate"]["merge"], support.MERGE)
        self.assertFalse((driver.project.common_dir / "agent-release").exists())

    def test_merge_observation_refusals_create_nothing(self):
        """Issue 554 row 11."""
        stale = [{"number": CANONICAL["pr"], "head": {"sha": "9" * 40}}]
        for code, ready in (("release_pr_missing", dict(prs=[])), ("release_pr_stale", dict(prs=stale)),
                            ("release_pr_behind", dict(compare="diverged"))):
            with self.subTest(code=code):
                self.world.reset()
                self.world.verification_ready(integration="dev")
                self.world.merge_observation_ready(**ready)
                driver = self.two_branch()
                document = driver.preview(rs.candidate())
                self.assertEqual((document["runnable"], document["refusal"]["code"],
                                  document["refusal"]["repair_id"], document["verification"],
                                  document["candidate"]["merge"]), (False, code, None, None, None))
                self.assertEqual(len(document["confirmations"]), 3)
                self.assertFalse(any("check-runs" in c["argv"][-1] for c in self.world.calls()))
                self.assertRefusal(code, driver.run, rs.candidate(),
                                   [c["token"] for c in document["confirmations"]])
                self.assertFalse((driver.project.common_dir / "agent-release").exists())

    def test_a_moved_base_between_preview_and_run_is_stale(self):
        """Issue 554 row 12."""
        driver = self.two_branch()
        tokens = [c["token"] for c in driver.preview(rs.candidate())["confirmations"]]
        self.world.merge_observation_ready(base_tip="6" * 40)
        self.assertRefusal("confirmation_stale", driver.run, rs.candidate(), tokens)
        self.assertFalse((driver.project.common_dir / "agent-release").exists())

    def test_a_single_branch_preview_binds_no_merge(self):
        self.world.reset()
        self.world.verification_ready()
        document = self.driver().preview(rs.candidate())
        self.assertEqual((document["runnable"], document["candidate"]["merge"]), (True, None))
        self.assertFalse(any("/pulls?" in c["argv"][-1] for c in self.world.calls()))

    def test_a_resumed_preview_reads_merge_from_the_stored_subject(self):
        driver = self.two_branch()
        rs.seed(driver, merge=support.MERGE)
        self.world.reset()
        document = driver.preview(None)
        self.assertEqual((document["mode"], document["candidate"]["merge"]), ("resume", support.MERGE))
        self.assertEqual(self.world.calls(), [])
```

In `tests/test_release_command.py` (import `release_test_support as support` if absent):

```python
class TwoBranchCommandTest(ReleaseCommandCase):
    """Issue 554 row 11: the command prints the merge observation's refusal in its document."""

    def setUp(self):
        super().setUp()
        contract = self.contract()
        contract["bindings"]["vcs"]["integration_branch"] = "dev"
        contract["release"]["profiles"] = {"github-release": support.merge_profile()}
        self.write_contract(contract)
        self.world = ForgeWorld(self)
        self.world.verification_ready(integration="dev")
        notes = tempfile.TemporaryDirectory()
        self.addCleanup(notes.cleanup)
        self.notes = Path(notes.name) / "notes.md"
        self.notes.write_text("notes body\n", encoding="utf-8")

    def test_preview_refuses_a_missing_release_pr(self):
        self.world.merge_observation_ready(prs=[])
        code, document, err = self.run_release(
            "transaction", "preview", "--commit", CANONICAL["commit"], "--version", CANONICAL["tag"],
            "--title", CANONICAL["title"], "--notes-file", str(self.notes))
        self.assertEqual((code, document["runnable"], document["refusal"]["code"]),
                         (3, False, "release_pr_missing"), err)
        self.assertEqual([c["action"] for c in document["confirmations"]], ["merge", "tag", "github-release"])
        self.assertIsNone(document["verification"])
        self.assertFalse((self.root / ".git/agent-release").exists())
```

If the resolver refuses this contract for a reason other than the profile, stop and report the violation. Do not loosen the resolver.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_verification.py tests/test_release_driver.py tests/test_release_command.py -k Merge -k TwoBranch 2>&1 | tail -4'`
Expected: FAIL. `observe_merge` does not exist, and `_new_plan`'s base `bind_candidate` call refuses the merge-less candidate `candidate_invalid`.

- [ ] **Step 3: Write the minimal implementation**

Implement `observe_merge` and the `_new_plan` order per the Invariants. `_document` renders `candidate.get("merge")`. Rewrite the `release_driver` module docstring's sentence on `preview`'s reads: `preview` makes `release_verification`'s three reads, plus, for a profile that consumes `merge`, the three `observe_merge` reads before them (issue 554 D3). Add a paragraph to `release_verification`'s docstring that lists `observe_merge`'s reads and codes. Update the `VerificationRefused` docstring, which says the code "is `candidate_stale` or `verification_unavailable`", to name every code it now carries: `candidate_stale`, `verification_unavailable`, `release_pr_missing`, `release_pr_stale` and `release_pr_behind` (PR554-06).

In `python/README.md` § Release driver, change only these:
- The opening paragraph's "The candidate is `{version, commit, title, notes}`." gains "; for a profile that consumes `merge`, the driver adds `merge: {pr, base_tip}`, which it observes itself (issue 554 D3)".
- The **Verification** paragraph gains a first sentence. For a profile that consumes `merge`, `release_verification.observe_merge` first reads the one open PR from `<owner>:<integration>` into the default branch, the default branch's tip and `compare/<base_tip>...<commit>`, under its own 30-second budget. It refuses `release_pr_missing`, `release_pr_stale`, `release_pr_behind` or `verification_unavailable`, and `preview` then reads no receipt and shows `verification` null (issue 554 D3).
- The **Preview** paragraph states that `candidate` carries `merge` (null without one), that the `plan_digest` candidate input covers it, and that the provider calls include the merge reads.

- [ ] **Step 4: Verify**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_verification.py tests/test_release_driver.py tests/test_release_command.py tests/test_release_crash_matrix.py 2>&1 | tail -4'`
Expected: PASS, `OK`.

Run: `if git grep -n 'release_profile.bind_candidate(self.compiled, dict(candidate))' -- python/agent_tools/release_driver.py; then exit 1; fi`
Expected: exit 0 (the operator's candidate is checked by `candidate_problem`).

Run (timeout 3600 s): `just build`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/release_verification.py python/agent_tools/release_driver.py tests/forge_world.py tests/test_release_verification.py tests/test_release_driver.py tests/test_release_command.py python/README.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(issue-554/T4): observe the release PR at preview" -m "<trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":4,"records":[{"bounds":[{"added_lines":75,"boundary":"all","deleted_lines":2,"record_bytes":8192,"support":{"covers":["r4a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4a","last_task":4,"owner":4,"path":"python/agent_tools/release_verification.py"},{"bounds":[{"added_lines":30,"boundary":"all","deleted_lines":10,"record_bytes":5120,"support":{"covers":["r4b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4b","last_task":5,"owner":4,"path":"python/agent_tools/release_driver.py"},{"bounds":[{"added_lines":85,"boundary":"all","deleted_lines":10,"record_bytes":9216,"support":{"covers":["r2c","r3c","r4c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4c","last_task":4,"owner":4,"path":"tests/forge_world.py"},{"bounds":[{"added_lines":60,"boundary":"all","deleted_lines":0,"record_bytes":6144,"support":{"covers":["r4d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4d","last_task":4,"owner":4,"path":"tests/test_release_verification.py"},{"bounds":[{"added_lines":80,"boundary":"all","deleted_lines":0,"record_bytes":8192,"support":{"covers":["r4e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4e","last_task":4,"owner":4,"path":"tests/test_release_driver.py"},{"bounds":[{"added_lines":40,"boundary":"all","deleted_lines":8,"record_bytes":7168,"support":{"covers":["r2i","r4f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4f","last_task":4,"owner":4,"path":"tests/test_release_command.py"},{"bounds":[{"added_lines":7,"boundary":"all","deleted_lines":5,"record_bytes":51200,"support":{"covers":["r1f","r2k","r3e","r4g"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4g","last_task":5,"owner":4,"path":"python/README.md"}]}}
```
