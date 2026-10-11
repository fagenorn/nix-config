# Task 5: Runs by index: `direct-owner`, `build-delivery` and `init-run --issue-set`

The three places where the control plane found a run by listing `.superpowers/workflows/` become keyed lookups in the creation-key index: `direct-owner`'s prefix scan, `build-delivery`'s installing-ledger scan, and the orchestrator's run reuse, which moves from skill prose into `init-run --issue-set`. Decisions: D8–D11, D16, D22–D24.

**Files:**
- Modify: `python/agent_tools/attempt_identity.py`, `python/agent_tools/attempt_store.py`, `python/agent_tools/attempt_delivery_store.py`
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`command_direct_owner`, `_installing_runs` and its two callers' docstrings, `command_init_run`, the `init-run` parser)
- Modify: `home/common/agent-skills/tests/test_control_cutover.py` (add), `tests/test_attempt_identity.py` (add)
- Modify (floor, D16 and D22 only): `home/common/agent-skills/tests/test_workflow_state.py`, `test_attempt_migration.py`, `test_delivery_workflow.py`

**Interfaces:**
- Consumes: `attempt_identity.direct_key`, `run_key`, `subject_handle`; `attempt_store.lookup_run`, `creation_key_plan`, `mint_run`, `reading`; Task 4's delivery transactions.
- Produces:
  - `attempt_identity.issue_set_caller_key(issues: Iterable[int], ordinal: int) -> str`: `issue-set:<numbers sorted, unique, joined by ->:<ordinal>`; `ValueError` for no issue, a member that is not an `int` in 1 to `_MAX_ISSUE`, an ordinal below 1, or a key the caller-key grammar refuses
  - `attempt_store.direct_runs(store: Path, workflows_dir: Path, issue: int) -> Iterator[tuple[int, str, Path]]`, replacing `indexed_direct_runs`: `(sequence, handle, run_dir)` from sequence 1, lazily
  - `attempt_store.unmigrated_direct(store: Path, workflows_dir: Path, issue: int) -> bool`
  - `attempt_delivery_store.installing_runs(store: Path, issue: int, digest: str) -> list[str]`: run handles in ordinal order
  - `workflow-state init-run --issue-set <n>-<n>…`, the third member of the handle group

**Invariants:**
- No function reachable from `control`, `direct-owner`, `build-delivery`, `init-run`, `check-launch` or an owner transport lists `workflows`. `attempt_store._inventory` (`migrate`) keeps its listing.
- **`direct_runs`.** For each sequence from 1, `lookup_run(store, direct_key(issue, sequence))`; a miss ends the list. The handle is `subject_handle(subject, id)` of that run transaction (a subject `subject_violation` refuses is `StoreRefused("direct run index entry is not a run transaction")`) and `run_dir` is `workflows_dir / handle`. A missing `run_dir` or `state.json` ends the list: that entry is the reserved id of the next mint. A `run_dir` that is a symlink or not a directory is `StoreRefused("direct run entry must be a non-symlink directory")`.
- **`unmigrated_direct`** walks the index to the first sequence with no entry and answers whether `workflows_dir / f"direct-{issue}-{sequence:06d}"` exists (`lstat`). No lock; nothing created.
- **`direct-owner`** calls `unmigrated_direct` before it creates `.superpowers`, `workflows` or the issue lock, and again once it holds the issue lock; true is `WorkflowError("unmigrated direct run: run workflow-state migrate --apply")` with nothing written. Its runs are `direct_runs(...)` alone, each retained and checked as a probed run is today (state lock, exactly the requested issue, identity equal to `RunIdentity("direct", issue, sequence)`); one below the current schema is still committed under its held lock. No other directory entry is read, so a stray or malformed `direct-…` name is not an error. The `direct run sequence exhausted` refusal stays.
- **`installing_runs`** probes `delivery_key(issue, digest, n)` from 1 to the first miss and maps each transaction's `subject["run"]` to that run's handle. `_installing_runs` yields `workflows / handle` for each, in that order, keeping its per-run skips (a name that is not a run id, a path that is not a non-symlink directory, a state file that is absent, unreadable or unparsable, a raw digest that differs), so a delivery transaction a cut write left ahead of its ledger matches nothing (D24). `installed_initial_intent` takes the first match; `installing_ledger_delivery` refuses two or more, naming them in that order. With no match both keep today's answers. A contract with no delivery transaction (a schema-9 ledger not yet bound) is not found.
- **`init-run --issue-set`.** The text must match `[1-9][0-9]{0,6}(-[1-9][0-9]{0,6})*`; otherwise, and when `issue_set_caller_key` raises, the refusal is `WorkflowError("invalid issue set")`. For `k` from 1, take the run under `run_key(issue_set_caller_key(numbers, k))`. No entry, or an entry whose ledger file is absent: mint or take that run and initialize it as `--creation-key` does. A ledger `read_state_unlocked` refuses: `WorkflowError(f"init-run refused: run {run_id} is invalid")`. A *reusable* ledger (some requested issue has no entry in `issues`, a null `outcome`, or a last attempt or last remainder that is `active`, `handed_off` or `suspended`): re-bootstrap it as `--run-id` does. Otherwise try `k + 1`. The reply is the bootstrap the other two forms print; they behave as before.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_control_cutover.py`, change the import to `from .test_attempt_custody import DeliveredCustody, LifecycleCustody` and append:

```python
class IndexResolutionTest(Cutover, unittest.TestCase):
    @property
    def workflows(self):
        return self.root / ".superpowers/workflows"

    def adopt(self, bootstrap):
        """Address the run a bootstrap reply names; returns its id."""
        minted = json.loads(bootstrap.stdout)["run_id"]
        self.run_args = ("--repo-root", self.root, "--run-id", minted)
        self.ledger = self.workflows / minted / "state.json"
        return minted

    def issue_set(self, text, minute=0, ok=True):
        return self.cli("init-run", "--repo-root", self.root, "--issue-set", text, "--now",
                        at(minute), ok=ok)

    def direct(self, minute=0, ok=True):
        """`direct-owner` for issue 41 with every fact a first launch needs."""
        worktree = str(self.root / ".worktrees/worktree-issue-41-direct")
        built = self.build("contract", self.contract_input(
            issue=41, worktree=worktree, now=at(0), source_reference="invocation:/from-issue 41"))
        request = self.direct_request(
            issue=41, now=at(minute), delivery_contract=built["contract"],
            authorization_intents=[built["initial_intent"]],
            forge={"state": "none", "url": None, "merge_sha": None},
            tracker={"issue": 41, "state": "open", "open_blockers": [], "decision_blockers": []},
            worktree={"issue": 41, "recorded": None,
                      "candidate": {"path": worktree, "state": "absent"}})
        return self.cli("direct-owner", "--repo-root", self.root, "--request-file", "-",
                        stdin=json.dumps(request).encode(), ok=ok)

    def current_selection(self, ok=True):
        return self.cli("build-delivery", "--repo-root", self.root, "--kind",
                        "current-selection", "--input", "-", ok=ok, stdin=json.dumps(
                            {"contract": self.built[DELIVERED]["contract"]}).encode())

    def script(self, unlistable):
        """Every control-plane command once over a root whose `workflows` holds only the
        `.gitignore` a used root has (D23); returns each stdout with run ids replaced."""
        shutil.rmtree(self.root / ".superpowers", ignore_errors=True)
        self.workflows.mkdir(parents=True)
        (self.workflows / ".gitignore").write_text("*\n", encoding="utf-8")
        if unlistable:
            os.chmod(self.workflows, 0o300)
            self.addCleanup(os.chmod, self.workflows, 0o700)
            with self.assertRaises(PermissionError):
                os.listdir(self.workflows)
        boot = self.issue_set(f"{LIVE}-{DELIVERED}")
        self.adopt(boot)
        outputs = [
            boot, self.sweep(0, recorded={DELIVERED: None, LIVE: None}, contracts=True),
            self.select(1),
            self.cli("progress", *self.run_args, "--issue", DELIVERED, "--attempt", 1,
                     "--phase", 1, "--now", at(2), "--turn-count", 10, "--context-tokens",
                     20000, "--next-needs-context", "true", "--artifacts-sufficient", "false",
                     "--remainder-self-contained", "false", "--action-id", f"{DELIVERED}:1:1"),
            self.cli("check-launch", *self.run_args, "--action-id", f"{DELIVERED}:1:1"),
            self.direct(), self.current_selection(),
            self.issue_set(f"{DELIVERED}-{LIVE}", 3)]
        return [RUN_ID.sub(b"RUN", done.stdout) for done in outputs]

    def test_ac1_no_control_plane_command_lists_the_workflows_directory(self):
        self.setup_run()
        readable = self.script(False)
        self.assertEqual(self.script(True), readable)

    def test_ac1_a_stray_or_copied_directory_is_not_a_run(self):
        self.setup_run()
        clean = RUN_ID.sub(b"RUN", self.direct().stdout)
        shutil.rmtree(self.root / ".superpowers")
        strays = [self.workflows / name / "state.json"
                  for name in ("direct-41-000009", "direct-41-bad")]
        for path in strays:
            path.parent.mkdir(parents=True)
            path.write_text("{}\n", encoding="utf-8")
        self.assertEqual(RUN_ID.sub(b"RUN", self.direct().stdout), clean)
        self.assertEqual([path.read_text(encoding="utf-8") for path in strays],
                         ["{}\n", "{}\n"])
        indexed = self.adopt(self.issue_set(f"{DELIVERED}-{LIVE}"))
        self.sweep(0, recorded={DELIVERED: None}, contracts=True)
        self.select(1)
        served = self.current_selection().stdout
        shutil.copytree(self.ledger.parent, self.workflows / "zz-copy")
        self.assertEqual(self.current_selection().stdout, served)
        self.assertEqual(json.loads(self.issue_set(f"{LIVE}-{DELIVERED}", 2).stdout)["run_id"],
                         indexed)

    def test_ac1_an_index_entry_without_a_ledger_is_reused(self):
        self.setup_run()
        first = json.loads(self.direct().stdout)["run_id"]
        shutil.rmtree(self.workflows / first)
        self.assertEqual(json.loads(self.direct().stdout)["run_id"], first)
        minted = json.loads(self.issue_set("9-7").stdout)["run_id"]
        shutil.rmtree(self.workflows / minted)
        self.assertEqual(json.loads(self.issue_set("7-9-7", 1).stdout)["run_id"], minted)

    def test_a_finished_run_is_not_reused_and_a_live_one_is(self):
        self.setup_run()
        live = self.adopt(self.issue_set(str(DELIVERED)))
        self.sweep(0, recorded={DELIVERED: None}, contracts=True)
        self.assertEqual(json.loads(self.issue_set(str(DELIVERED), 1).stdout)["run_id"], live)
        self.failing(f"{DELIVERED}:1:1", 2)
        fresh = json.loads(self.issue_set(str(DELIVERED), 3).stdout)["run_id"]
        self.assertNotEqual(fresh, live)
        self.assertEqual(
            self.core().lookup(f"attempt-run/v1:run:issue-set:{DELIVERED}:2"), fresh)
        for text in ("207-x", "0", "", "207--209"):
            refused = self.issue_set(text, ok=False)
            self.assertEqual((refused.returncode, refused.stdout), (2, b""), text)

    def test_two_runs_installing_one_contract_keep_the_refusal_in_install_order(self):
        self.spawn(DELIVERED)
        self.select(1)
        first = self.run_args[3]
        second = self.adopt(self.cli("init-run", "--repo-root", self.root, "--creation-key",
                                     "second", "--now", at(31)))
        self.sweep(31, recorded={DELIVERED: None}, contracts=True)
        refused = self.current_selection(ok=False)
        self.assertEqual((refused.returncode, refused.stderr), (
            2, b"workflow-state: build-delivery refused: the contract is installed by more "
               b"than one ledger: " + f"{first}, {second}\n".encode()))
        later = self.delivery(DELIVERED, 2)
        self.assertIsNotNone(later)
        self.assertEqual(later.subject["run"], second)


class UnmigratedDirectTest(LifecycleCustody, unittest.TestCase):
    def test_ac1_an_unbound_legacy_direct_ledger_is_refused_until_it_is_migrated(self):
        owner = self.acquire_direct()
        legacy = self.workflows_dir / "direct-73-000001"
        (self.workflows_dir / owner["run_id"]).rename(legacy)
        state = self._as_legacy(json.loads((legacy / "state.json").read_text()), 7,
                                handle="direct-73-000001")
        (legacy / "state.json").write_text(
            json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        shutil.rmtree(self.store_root)  # no index entry names the ledger
        before = self.tree()
        facts = {"tracker": self.tracker_fact(73), "worktree": self.worktree_fact(73, recorded={
            "path": owner["worktree"], "state": "matching_issue_branch"})}
        refused = self.direct_owner_raw(**facts, ok=False)
        self.assertEqual((refused.returncode, refused.stderr), (
            2, "workflow-state: unmigrated direct run: run workflow-state migrate --apply\n"))
        self.assertEqual(self.tree(), before)
        self.run_cli("migrate", "--repo-root", self.root, "--apply")
        taken = self.direct_owner(owner_unavailable=True, **facts)
        self.assertEqual((taken["kind"], taken["run_id"]), ("owner", "direct-73-000001"))
```

Add to `tests/test_attempt_identity.py`:

```python
class IssueSetKeyTest(unittest.TestCase):
    def test_the_key_is_the_sorted_unique_issue_numbers_and_an_ordinal(self):
        self.assertEqual(ai.issue_set_caller_key([14, 12, 14], 2), "issue-set:12-14:2")
        self.assertEqual(ai.run_key(ai.issue_set_caller_key((7,), 1)),
                         "attempt-run/v1:run:issue-set:7:1")
        for issues, ordinal in (([], 1), ([0], 1), ([True], 1), (["7"], 1), ([7], 0),
                                (list(range(1, 60)), 1)):
            with self.subTest(issues=issues, ordinal=ordinal):
                with self.assertRaises(ValueError):
                    ai.issue_set_caller_key(issues, ordinal)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `PYTEST T/test_control_cutover.py -k IndexResolutionTest -k UnmigratedDirectTest` and `PYTEST tests/test_attempt_identity.py`
Expected: FAIL. Four `IndexResolutionTest` cases fail on `init-run`'s usage error (`--issue-set` is unknown) or on `malformed direct run namespace entry`; `test_two_runs_installing_one_contract_keep_the_refusal_in_install_order` passes (it pins today's refusal and Task 4's ordinals); `UnmigratedDirectTest` fails because the legacy ledger is bound on the spot (`direct run has an active owner`); `IssueSetKeyTest` fails on the missing function.

- [ ] **Step 3: Implement**

The three package functions and the three engine sites, to the invariants above. In `command_direct_owner` delete the `os.scandir` block and the `claimed` list; the preflight loop runs over `direct_runs` only. `command_init_run`'s docstring names the three forms.

- [ ] **Step 4: Apply the declared floor changes**

Only these (D16, D22):
- a test that hand-installs a legacy `direct-<issue>-<sequence>` ledger and then calls `direct-owner` runs `migrate --apply` first, unless on-the-spot binding was its subject, in which case it asserts the `unmigrated direct run` refusal and an unchanged tree;
- a test where a stray, malformed or symlinked `direct-…` entry that no index entry names was refused now asserts the call's ordinary reply and the entry's unchanged bytes;
- the sequence-exhaustion test becomes such a stray-directory case (sequence 999999 is reachable only through the index entries below it);
- an installing-ledger test built by copying a run directory (`zz-copy`) asserts that the copy is not found (the more-than-one refusal is covered by the new two-run test), and a `build-delivery` lookup test over a hand-written ledger binds it with `migrate --apply` first.

- [ ] **Step 5: Verify**

Run: `PYTEST T/test_control_cutover.py T/test_control_decisions.py tests/test_attempt_identity.py T/test_attempt_migration.py T/test_attempt_custody.py T/test_delivered_control.py`
Expected: `OK`; `test_control_cutover.py` runs 18 tests.

Run: `PYTEST T/test_workflow_state.py T/test_delivery_workflow.py`
Expected: `OK`.

Run: `grep -n "os.scandir\|\.iterdir()\|os.listdir\|glob(" home/common/agent-skills/scripts/workflow-state.py python/agent_tools/attempt_store.py python/agent_tools/attempt_delivery_store.py`
Expected: exactly three lines: `os.listdir(workflows)` in `attempt_store._inventory`, and the two `iterdir()` calls of `read_sdd_position`, which read an sdd workspace bucket.

- [ ] **Step 6: Commit**

```bash
git add python home tests
launch-commit … -- -m "feat(workflow-state): resolve runs by index key, not by listing workflows (#339)"
```
