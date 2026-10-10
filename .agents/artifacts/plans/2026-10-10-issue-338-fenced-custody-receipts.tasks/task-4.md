# Task 4: Owner transports: the launch fence and misbinding

`progress`, `suspend` and the legacy `finish` learn which launch is calling, and every owner transport refuses a session that stands in another attempt's worktree. Read the root's Global Constraints first. Decisions: D7, D9, D11, D13, D19, D20, D22.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`, `python/agent_tools/attempt_store.py`
- Modify: `home/common/agent-skills/tests/test_attempt_custody.py` (add)
- Modify (harness transports, D22): `home/common/agent-skills/tests/test_workflow_state.py`, `test_delivery_workflow.py`, `test_host_admission.py`

**Interfaces:**
- Consumes: Task 3's `attempt_store.custody_of`, `FencingRefused`, `store_root`, `ledger_store`, `LockedRead.bound_launches`; Task 2's `launch_id`, `worktree_key`, `LIVE_STATES`; `workflow-state.py`'s `parse_action_id`, `parse_worker_id`, `render_action_id`, `canonical_worktree_path`, `read_state_unlocked`, `resolve_repo_root`, `require_regular_path`.
- Produces:
  - `attempt_store.standing_worktree(store: Path, directory: str) -> str | None`: for `directory` and each ancestor, nearest first, the first path whose `worktree_key` has a lease record (`inspect_lease`, holder or not); `None` when none has, or when the store directory does not exist. No lock, no write, no child process; a core error is a `StoreFault`.
  - CLI: `progress`, `suspend` and `finish` accept an optional `--action-id`.
  - `workflow-state.py`: `class OwnerCall` with fields `issue`, `attempt`, `action_id` (`None` for an attempt-keyed call), `keyed` (true for the three transports above), `report` (`None` in this task), `supplied` (the parsed `--now` or `None`), `summary` (false in this task); `admit_owner_call(state_path, state, bound_launches, call) -> int | None`; `transact(…, owner_call: OwnerCall | None = None)`, which calls `admit_owner_call` on the locked state before the mutation; `refuse_misbound(repo_root_value, run_id, *, issue, remainder, ordinal) -> None`.

**The launch fence** (`admit_owner_call`; returns the caller's launch ordinal, or `None` when no fence applies):

1. An unknown issue, or an attempt ordinal past the issue's attempts → `None`: the engine refuses in its own words.
2. A named launch must be an implementation id of the same issue and attempt, else `WorkflowError("--action-id does not name this issue and attempt")`.
3. An attempt-keyed call speaks for the attempt's bound launch: the custody subject's `bound_launch` when the attempt has a custody transaction; else `bound_launches[(issue, attempt)]` when this write is the bind; else null when the attempt is its issue's latest and in `LIVE_STATES`; any other attempt → `None` (D11: no custody transaction, today's behaviour). A null bound launch is `FencingRefused("launch_identity_required", …)`, telling the caller to pass `--action-id`.
4. For a `keyed` call on an `active` attempt whose last launch is not the caller's: `FencingRefused("superseded_launch", …)` naming both launch ids.
5. In every other case the mutation runs and the engine's own refusals apply unchanged (D13).

`progress`, `suspend` and the legacy `finish` pass `owner_call=OwnerCall(issue=args.issue, attempt=args.attempt, action_id=args.action_id, keyed=True, …)` to `transact`. No other transport passes one in this task.

**Misbinding** (`refuse_misbound`, per D7):

1. `standing = standing_worktree(store_root(<resolved repo root>/.superpowers), os.path.normcase(os.path.realpath(os.getcwd())))`. `None` → return: the session stands in no attempt worktree.
2. Read the addressed run's ledger with `read_state_unlocked` (a missing ledger, issue or record → return: the engine refuses later) and take the recorded worktree of the addressed attempt, or remainder when `remainder` is true, through `canonical_worktree_path`.
3. When it differs from `standing`: `FencingRefused("custody_misbound", …)` naming both paths and the remedy (run from the addressed worktree, or from outside every attempt worktree).

Each owner transport calls it after its arguments and report are validated and before it calls `workflow_paths`, `transact`, an unlocked ledger read or a git probe: `progress`, `suspend` and legacy `finish` with `--issue`/`--attempt`; `finish --summary-file` and `checkpoint-delivery` with the validated report's `issue` and `custody` (`kind`, and `attempt` or `remainder`); `register-worker`, `mark-progress` and `declare-lane` with their `--action-id`; `release-worker` with the launch of its `--worker-id`. The directory is observed by the helper: no argument or environment variable supplies it.

**Invariants:**
- A misbound transport exits 2 with `workflow-state: fencing violation: custody_misbound: …` and leaves every path under the repository root byte-identical: no lock file, directory or ledger write.
- The same transports from the repository root, from a directory with no lease record, or from the addressed worktree are not refused for misbinding.
- `superseded_launch` and `launch_identity_required` leave the `.superpowers` tree unchanged.
- An attempt with no custody transaction that is terminal answers an attempt-keyed transport exactly as before.
- `check-launch`, `current-launch`, `owner-liveness`, `resume-pack`, `control` and `direct-owner` call neither check.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_attempt_custody.py`, add after the `agent_tools` imports:

```python
from .test_delivered_control import DELIVERED, DISPATCH, LIVE, DeliveredControlHarness, at
```

Add this method to `LifecycleCustody`:

```python
    def legacy_owner_resumed_to_launch_2(self):
        """A schema-8 ledger with a live owner on 14:1:1, bound by control's write, then
        expired, reaped and resumed to 14:1:2."""
        self.spawn_14()
        self.install_legacy(self.read_state(), "orchestrate-14", version=8)
        self.assertEqual(self.read_state()["schema_version"], 8)
        recorded = [self.worktree_fact(14, recorded={
            "path": os.path.abspath(self.worktree), "state": "matching_issue_branch"})]
        self.control(now="2026-08-13T20:00:30Z", issues=[14], max_parallel=100,
                     tracker=[self.tracker_fact(14)], worktrees=recorded)
        self.assertEqual(self.custody(14).subject["bound_launch"], 1)
        self.expire(issue=14, worktree=self.worktree, now=T(31))
        self.resume(issue=14, worktree=self.worktree, now=T(32))
        self.assertEqual(self.custody(14).custody.executor_id, "14:1:2")
```

Add these classes before the `__main__` guard:

```python
class LaunchFenceTest(LifecycleCustody, unittest.TestCase):
    def test_ac5_attempt_keyed_progress_and_suspend_after_a_successor_launch(self):
        self.legacy_owner_resumed_to_launch_2()
        before = self.tree()
        self.assert_fenced(self.progress(phase=1, now=T(33), action_id=False, ok=False),
                           "superseded_launch", before)
        self.assert_fenced(self.suspend(issue=14, attempt=1, blocked_on="transport",
                                        now=T(33), action_id=False, ok=False),
                           "superseded_launch", before)
        self.progress(phase=1, now=T(33))  # the successor names its launch and is admitted

    def test_ac5_an_attempt_created_at_schema_9_needs_its_launch_named(self):
        self.spawn_14()
        self.expire(issue=14, worktree=self.worktree, now=T(31))
        self.resume(issue=14, worktree=self.worktree, now=T(32))
        before = self.tree()
        self.assert_fenced(self.progress(phase=1, now=T(33), action_id=False, ok=False),
                           "launch_identity_required", before)
        self.assert_fenced(self.progress(phase=1, now=T(33), action_id="14:1:1", ok=False),
                           "superseded_launch", before)
        self.assert_fenced(self.suspend(issue=14, attempt=1, blocked_on="transport",
                                        now=T(33), action_id="14:1:1", ok=False),
                           "superseded_launch", before)

    def test_an_attempt_terminal_before_the_bind_keeps_the_engines_answers(self):
        self.spawn_14()
        self.finish(1, self.stopped(), now=T(5))
        self.install_legacy(self.read_state(), "orchestrate-14", version=8)
        replayed = self.finish(1, self.stopped(), now=T(6), action_id=False)
        self.assertEqual(replayed["state"], "stopped")
        self.assertEqual(self.read_state()["schema_version"], 9)
        self.assertIsNone(self.custody(14))
        conflict = self.finish(1, self.stopped("another"), now=T(7), action_id=False, ok=False)
        self.assertEqual(conflict.returncode, 2)
        self.assertIn("conflicting terminal result for issue 14 attempt 1", conflict.stderr)
        self.assertIsNone(self.custody(14))


class DeliveredCustody(CustodyReads, DeliveredControlHarness):
    def ledger_path(self):
        return self.ledger

    def observed_root(self):
        return Path(self.root)

    def spawn(self, *issues):
        """Spawn `issues` under contracts at minute 0; their implementation custodies."""
        self.setup_run()
        spawned = self.control(0, recorded=dict.fromkeys(issues), contracts=True)
        return {action["issue"]: action["custody"] for action in spawned["actions"]
                if action["kind"] in DISPATCH}

    def summary(self, custody, historical_state, observations=(), authority=(), **result):
        issue = custody["action_id"].partition(":")[0]
        contract = self.built[int(issue)]["contract"]
        historical = {"issue": int(issue), "state": historical_state, "pr_url": None,
                      "merge_sha": None, "issue_closed": False, "discussion_items": [],
                      "detail_state": "none", "report_path": None, "notes": "late", **result}
        return self.validated("ship-summary", {
            "interface_version": 2, "issue": int(issue), "state": "terminal_failed",
            "custody": custody, "historical_owner_result": historical,
            "delivery_contract_digest": self.model.canonical_digest(contract),
            "delivery_observations": sorted(observations, key=lambda item: item["id"]),
            "authority_observations": list(authority), "reevaluation_evidence": [],
            "detail_state": "none", "report_path": None, "notes": "late"})


class MisbindingTest(DeliveredCustody, unittest.TestCase):
    def transports(self, custody):
        issue, action = DELIVERED, custody["action_id"]
        contract = self.built[issue]["contract"]
        checkpoint = self.validated("ship-checkpoint", {
            "interface_version": 2, "issue": issue, "custody": custody,
            "contract_digest": self.model.canonical_digest(contract),
            "delivery_observations": [], "authority_observations": [],
            "reevaluation_evidence": [],
            "requested_scope": self.build("scope", {"contract": contract,
                                                    "stage_id": "merge_pr"}),
            "detail_state": "none", "report_path": None, "notes": ""})
        result = self.root / "result.json"
        result.write_text(json.dumps({
            "issue": issue, "state": "stopped", "pr_url": None, "merge_sha": None,
            "issue_closed": False, "discussion_items": [], "detail_state": "none",
            "report_path": None, "notes": "stop"}), encoding="utf-8")
        keyed = ("--issue", issue, "--attempt", 1, "--action-id", action)
        return {
            "progress": (("progress", *self.run_args, *keyed, "--phase", 1, "--now", at(1),
                          "--turn-ceiling", 120, "--context-ceiling", 150000,
                          "--turn-headroom", 2, "--context-headroom", 10000,
                          "--next-needs-context", "true", "--artifacts-sufficient", "false",
                          "--remainder-self-contained", "false"), None),
            "suspend": (("suspend", *self.run_args, *keyed, "--blocked-on", "transport",
                         "--now", at(1)), None),
            "finish": (("finish", *self.run_args, *keyed, "--result-file", result,
                        "--now", at(1)), None),
            "finish-summary": (("finish", *self.run_args, "--now", at(1), "--summary-file",
                                "-"), self.summary(custody, "stopped")),
            "checkpoint-delivery": (("checkpoint-delivery", *self.run_args, "--now", at(1),
                                     "--checkpoint-file", "-"), checkpoint),
            "mark-progress": (("mark-progress", *self.run_args, "--now", at(1),
                               "--action-id", action), None),
            "declare-lane": (("declare-lane", *self.run_args, "--now", at(1), "--action-id",
                              action, "--lane", "light", "--budget-minutes", 20, "--reason",
                              "triage"), None),
            "register-worker": (("register-worker", *self.run_args, "--now", at(1),
                                 "--action-id", action), None),
            "release-worker": (("release-worker", *self.run_args, "--now", at(1),
                                "--worker-id", f"{action}:w1", "--event", "returned"), None)}

    def test_ac3_a_session_in_another_attempts_worktree_is_refused_before_any_write(self):
        custodies = self.spawn(DELIVERED, LIVE)
        for worktree in self.worktrees.values():
            (Path(worktree) / "nested").mkdir(parents=True)
        transports = self.transports(custodies[DELIVERED])
        before = self.tree()
        other = Path(self.worktrees[LIVE]) / "nested"
        for name, (argv, stdin) in transports.items():
            with self.subTest(transport=name):
                refused = self.cli(*argv, stdin=stdin, ok=False, cwd=other)
                self.assert_fenced(refused, "custody_misbound", before)
                for path in (self.worktrees[DELIVERED], self.worktrees[LIVE]):
                    self.assertIn(os.path.realpath(path).encode(), refused.stderr)
        for standing in (self.root, self.worktrees[DELIVERED]):
            for name in ("register-worker", "progress"):
                with self.subTest(transport=name, standing=standing):
                    argv, stdin = transports[name]
                    self.cli(*argv, stdin=stdin, cwd=standing)
        for name, (argv, stdin) in transports.items():
            with self.subTest(admitted=name):
                own = self.cli(*argv, stdin=stdin, ok=False, cwd=self.worktrees[DELIVERED])
                self.assertNotIn(b"fencing violation", own.stderr)
```

- [ ] **Step 2: Change the harness transports (D22)**

In `LifecycleHarness` (`test_workflow_state.py`), add:

```python
    def launch_arguments(self, issue, attempt, action_id):
        """`--action-id` for an owner transport: the attempt's last launch unless the test
        names one; `False` sends the transport attempt-keyed (#338 D9)."""
        if action_id is False:
            return ()
        if action_id is None:
            try:
                record = self.read_state()["issues"][str(issue)]["attempts"][attempt - 1]
            except (KeyError, IndexError, TypeError, ValueError, OSError):
                return ()
            action_id = f"{issue}:{attempt}:{len(record['launches'])}"
        return ("--action-id", action_id)
```

`progress`, `suspend` and `finish` gain a keyword `action_id=None` and append `*self.launch_arguments(issue, attempt, action_id)` to their argv (`finish` computes it before it rewrites the ledger); `concurrent_finish` appends `*self.launch_arguments(issue, attempt, None)`. In `BuilderHarness.cli` (`test_delivery_workflow.py`), add a keyword `cwd=None` and pass it to `subprocess.run`.

- [ ] **Step 3: Run the new tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_custody.py -k LaunchFenceTest -k MisbindingTest`
Expected: all 4 fail: argparse rejects `--action-id` (exit 2, `unrecognized arguments`), and the misbound transports are not refused with `custody_misbound`.

- [ ] **Step 4: Implement**

Implement the interfaces, the fence and the misbinding check above. Docstrings are written from the implemented code.

- [ ] **Step 5: Name the launch in the remaining raw transports (D22)**

Pre-existing tests that send `progress`, `suspend` or the legacy `finish` by raw argv now get `launch_identity_required` on an attempt created at schema 9. Add `--action-id <issue>:<attempt>:<last launch>` to each such call, changing nothing else. The prototype found them in `test_workflow_state.py` (`OwnerExitFenceTest.test_legacy_finish_refuses_until_the_worker_returns`), `test_host_admission.py` (`test_finish_releases_the_claim_in_its_own_write`) and `test_delivery_workflow.py` (`test_contracted_reconciliation_mints_remainder_one`, `test_direct_acquisition_asks_for_the_contract_last`, `test_legacy_finish_lands_only_on_contractless_issues`, `test_reconciled_remainder_waits_for_capacity`, `test_schema_four_accepts_the_legacy_finish_transport_on_a_contractless_issue`, `test_typed_effect_uses_raw_validation_and_both_launch_fences`, and `LedgerClockTest`'s `test_a_backward_refusal_names_the_wait` and `test_every_flag_command_without_a_time_stamps_the_clock`); treat the list as a start, not as complete.

- [ ] **Step 6: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_custody.py`
Expected: `OK`, 11 tests.

Run, one command each, timeout 1800 s: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/<file>` for `test_workflow_state.py`, `test_attempt_migration.py`, `test_host_admission.py`, `test_delivery_workflow.py`, `test_delivered_control.py`.
Expected: `OK` for each. A failure that is not a raw transport missing its launch is a defect or a spec conflict (Global Constraints).

- [ ] **Step 7: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py python/agent_tools/attempt_store.py home/common/agent-skills/tests
launch-commit … -- -m "feat(workflow-state): fence owner transports by launch and by worktree (#338)"
```
