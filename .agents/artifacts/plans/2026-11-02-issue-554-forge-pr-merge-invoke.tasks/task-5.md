# Task 5: The two-branch run, its park reason and crash resume

Per D7, D12 and D15; spec §4 and the race rows 6, 7, 8, 10 and 16. Read the plan root's Global Constraints first. The release core's code is not touched: recovery is its ordinary inspect-before-retry path.

**Files:**
- Modify: `python/agent_tools/release_driver.py` (`_Drive.action`, `_Drive.stopped`)
- Modify: `tests/release_driver_support.py` (`StatefulForge`; new `LandedDespiteExit`)
- Modify: `tests/test_release_crash_matrix.py` (new `TwoBranchMatrixTest`)
- Modify: `python/README.md` (§ Release driver, the **Run** paragraph: one sentence)

**Interfaces:**
- Consumes:
  - Task 1's `rs.forge_merge_profile()` and `support.MERGE`.
  - Task 2's `ForgeWorld.merge_ready` and `FLOOR_PROTECTION`.
  - Task 3's `invoke_ready(merged_compare=…, fetch_exit=…)` and the merged-tag registrations.
  - Task 4's `merge_observation_ready` and the merge-aware `preview`.
  - The core's `invocation_returned` event `{action_id, attempt, result, error_class, reference}`, and `_view(transaction, name)["action_id"]`.
- Produces:
  - `_Drive.stopped(name: str, status: str, after: str = "") -> str`. It parks with reason `f"{name}: {status}{after}"`.
  - After an `invoke_action` that leaves the action unsatisfied, `after` is `f" after {result} {error_class}: {reference}"`, read from that action's latest `invocation_returned` event, when its `result` is not `accepted`. Otherwise `after` is empty.
  - `StatefulForge(world)` keeps its base `__init__` and does not call `merge_ready()`. That call would re-register `repos/<slug>/git/ref/heads/main`, which single-branch tests answer through `verification_ready()` as the integration tip (PR554-01). Two-branch tests call `self.world.merge_ready(...)` themselves. `invoke` calls `self.land(request)` after an accepted invoke. `land(request: dict) -> None`:
    - `pr_merge` re-registers `pr_merge.view` as `MERGED` with `mergeCommit.oid == CANONICAL["merge_commit"]` and `headRefOid == CANONICAL["commit"]`, and `pr_merge.merge_commit` with parents `[merge.base_tip, candidate.commit]`.
    - `tag` peels the tag to `CANONICAL["merge_commit"]` when `"merge" in candidate`, else to `CANONICAL["commit"]`.
    - `release` is as at base.
  - `LandedDespiteExit(StatefulForge)`: for `pr_merge` it calls `self.land(request)` even when the invoke's result is `unknown`, as a merge that landed while `gh` exited non-zero would.

**Invariants:**
- A park after a pre-invoke inspection (`absent` never invoked, or `diverged`) keeps its base reason `<name>: <status>`; `in_progress` and `unknown` still return `wait` with no park. The `InvocationRefused` park is unchanged.
- The reason string is what `status()["release"]["reason"]` returns (128 D25), for every operation, not only `pr_merge`.
- A two-branch release drives `merge`, `tag`, `github-release`, then `deploy`. A crash after the merge leaves its intent open with no recorded inspection (the core records the inspection only after `invoke` returns), so the resume preview lists `merge` again with a fresh token (PR554-02). The resumed run's first inspection reads it `satisfied`, so it never runs a second `gh pr merge`. The tag lands at the merge commit.
- The existing fixture-merge matrix (`MatrixCase`, `CrashMatrixTest`, `FixtureShapeTest`) is unchanged and still passes.

- [ ] **Step 1: Write the failing tests**

Update `StatefulForge` and add `LandedDespiteExit` per Interfaces. Then add to `tests/test_release_crash_matrix.py` (add `from . import forge_world, release_test_support as support` and import `CANONICAL` from `.forge_world`):

```python
TWO_BRANCH = ["merge", "tag", "github-release", "deploy"]


class TwoBranchMatrixTest(unittest.TestCase):
    """Issue 554: the real forge merges, then tags its merge commit (spec §4, AC3)."""

    def setUp(self):
        self.world = ForgeWorld(self)
        self.world.verification_ready(integration="dev")
        self.world.merge_observation_ready()
        self.clock = rs.Clock()
        self.forge, self.deploy = rs.StatefulForge(self.world), rs.FixtureDeploy()
        self.world.merge_ready()

    def driver(self, forge=None, crash=None):
        forge = forge or self.forge
        if crash is not None:
            forge = rs.CrashAt(forge, crash, after=True)
        project = rs.project(self, profiles={"two-branch": rs.forge_merge_profile()}, integration="dev")
        return release_driver.Driver(project, registry={"github-forge": forge, "fixture-deploy": self.deploy},
                                     clock=self.clock)

    def merges(self):
        return [c for c in self.world.calls() if c["tool"] == "gh" and c["argv"][:2] == ["pr", "merge"]]

    def tags(self):
        return [c["argv"] for c in self.world.calls() if c["tool"] == "git" and c["argv"][:2] == ["tag", "-a"]]

    def test_a_confirmed_two_branch_release_merges_once_and_tags_the_merge_commit(self):
        driver = self.driver()
        shown, result = rs.release(driver, rs.candidate())
        self.assertEqual([c["action"] for c in shown["confirmations"]], TWO_BRANCH[:3])
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        self.assertEqual(len(self.merges()), 1)
        self.assertEqual(self.tags(), [["tag", "-a", CANONICAL["tag"], CANONICAL["merge_commit"],
                                        "-m", f"release: {CANONICAL['tag']}"]])

    def test_a_crash_after_the_merge_tags_the_merge_commit(self):
        """Issue 554 row 10, AC3."""
        driver = self.driver(crash="pr_merge")
        shown = driver.preview(rs.candidate())
        with self.assertRaises(rs.Crash):
            driver.run(rs.candidate(), [c["token"] for c in shown["confirmations"]])
        self.clock.advance(release_driver.CUSTODY_TTL_MS + 1)
        resumed = driver.preview(None)
        self.assertEqual((resumed["mode"], resumed["candidate"]["merge"]), ("resume", support.MERGE))
        # The crash left merge's intent open with no recorded inspection, so it is not stored
        # satisfied and is confirmed again; the resumed run inspects it and never re-invokes.
        self.assertEqual([c["action"] for c in resumed["confirmations"]], TWO_BRANCH[:3])
        result = driver.run(None, [c["token"] for c in resumed["confirmations"]])
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        self.assertEqual(len(self.merges()), 1)
        self.assertEqual([argv[3] for argv in self.tags()], [CANONICAL["merge_commit"]])
        actions = {a["name"]: (a["status"], a["attempts"]) for a in driver.status()["release"]["actions"]}
        # One attempt: the intent the crashed invoke opened. The resume adds an inspection, not an attempt.
        self.assertEqual(actions["merge"], ("satisfied", 1))

    def test_a_provider_refused_merge_parks_with_no_effect(self):
        """Issue 554 rows 6 and 7: GitHub refuses a moved base or a moved head; the PR stays open."""
        for stderr in ("GraphQL: Head branch is out of date (mergePullRequest)",
                       "GraphQL: Head branch was modified. Review and try the merge again."):
            with self.subTest(stderr=stderr):
                self.setUp()
                self.world.merge_ready(merge_exit=1, merge_stderr=stderr)
                driver = self.driver()
                _, result = rs.release(driver, rs.candidate())
                self.assertEqual((result["state"], result["next"]), ("attention_required", "attention"))
                reason = driver.status()["release"]["reason"]
                self.assertTrue(reason.startswith("merge: absent after unknown transient_transport: "), reason)
                self.assertEqual((len(self.merges()), self.tags()), (1, []))
                self.assertEqual(driver.abandon()["state"], "abandoned")

    def test_a_landed_merge_that_exits_non_zero_is_satisfied(self):
        """Issue 554 row 8: the same-call inspection reads MERGED, and the tag follows."""
        forge = rs.LandedDespiteExit(self.world)
        self.world.merge_ready(merge_exit=1, merge_stderr="gh: connection reset")
        driver = self.driver(forge=forge)
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        self.assertEqual(len(self.merges()), 1)
        self.assertEqual([argv[3] for argv in self.tags()], [CANONICAL["merge_commit"]])

    def test_a_floor_refusal_parks_with_its_reason_and_abandons(self):
        """Issue 554 row 16, AC2."""
        floor = forge_world.FLOOR_PROTECTION
        self.world.merge_ready(protection={**floor, "enforce_admins": {"enabled": False}})
        driver = self.driver()
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual(result["next"], "attention")
        self.assertEqual(driver.status()["release"]["reason"],
                         "merge: absent after rejected precondition_failed: "
                         "protection_floor_unmet: enforce_admins")
        self.assertEqual((self.merges(), self.tags()), ([], []))
        self.assertEqual(driver.abandon()["state"], "abandoned")
```

Order matters, because `verification_ready` and `merge_ready` register the same protection argv, and `merge_ready` and `merge_observation_ready` register the same `heads/main` argv. The last write wins. In these tests the integration branch is `dev`, so `heads/main` is the base tip in every registration, and a test's own `merge_ready(...)` comes after `setUp` with nothing re-registering protection after it. The floor-breaking payload keeps `FLOOR_PROTECTION`'s `checks`, so the receipt still passes: it does not judge `enforce_admins` (D14). If the core refuses `abandon` in rows 6 and 7, stop and report it, because the spec's row 6 relies on the no-effect gate.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_crash_matrix.py -k TwoBranch 2>&1 | tail -4'`
Expected: FAIL. The floor and provider-refusal parks read `merge: absent` with no suffix.

- [ ] **Step 3: Write the minimal implementation**

In `_Drive.action`, after `invoke_action` returns and the status is not `satisfied`, find the latest event with `type == "invocation_returned"` and `action_id == _view(self.transaction, name)["action_id"]`. When its `result` is not `"accepted"`, pass `after` to `stopped`. In `stopped`'s docstring, state the reason format (issue 554 D12).

In `python/README.md` § Release driver's **Run** paragraph, after "one `InvocationRefused` or an `absent` or `diverged` result parks `attention_required`", add one sentence. After an invoke whose result was not `accepted`, the park reason is `<name>: <status> after <result> <error_class>: <reference>`, read from the action's latest `invocation_returned` event, so `status` shows, for example, `protection_floor_unmet: enforce_admins` (issue 554 D12).

- [ ] **Step 4: Verify**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_crash_matrix.py tests/test_release_driver.py tests/test_release_command.py tests/test_forge_adapter.py 2>&1 | tail -4'`
Expected: PASS, `OK`.

Run (timeout 3600 s): `just build`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/release_driver.py tests/release_driver_support.py tests/test_release_crash_matrix.py python/README.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(issue-554/T5): run two-branch releases, name park reasons" -m "<trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":5,"records":[{"bounds":[{"added_lines":45,"boundary":"all","deleted_lines":14,"record_bytes":8192,"support":{"covers":["r4b","r5a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r5a","last_task":5,"owner":5,"path":"python/agent_tools/release_driver.py"},{"bounds":[{"added_lines":60,"boundary":"all","deleted_lines":8,"record_bytes":8192,"support":{"covers":["r1d","r5b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r5b","last_task":5,"owner":5,"path":"tests/release_driver_support.py"},{"bounds":[{"added_lines":105,"boundary":"all","deleted_lines":0,"record_bytes":10240,"support":{"covers":["r5c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r5c","last_task":5,"owner":5,"path":"tests/test_release_crash_matrix.py"},{"bounds":[{"added_lines":8,"boundary":"all","deleted_lines":6,"record_bytes":53248,"support":{"covers":["r1f","r2k","r3e","r4g","r5d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r5d","last_task":5,"owner":5,"path":"python/README.md"}]}}
```
