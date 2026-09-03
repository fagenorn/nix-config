# Task 6: Residue checks — nested ledgers proved by `flock`, and root scratch

**Files:**
- Modify: `home/common/agent-skills/scripts/conformance.py`
- Modify: `home/common/agent-skills/tests/test_conformance.py`

**Interfaces:**
- Consumes from Task 2: `Check`, `Outcome`, `Context` (`context.root`, `context.contract`), `REGISTRY`, `REPAIRS`.
- Produces `check_residue_nested_ledger`, `check_residue_root_scratch`, `ROOT_SCRATCH_PATTERNS`, `LEDGER_RESULT_STATES`, two registry entries and three repairs.

**Invariants:**
- **Nothing is deleted, moved or written.** v1 reports repairs; it never executes one (D10).
- The lock is *evidence*, never a claim: a non-blocking `fcntl.flock(LOCK_EX | LOCK_NB)` is attempted, and the descriptor is closed — releasing the lock — immediately, in a `finally`.
- The lock file is opened `os.O_RDONLY`. It is **never created**: a run directory with no `state.lock` is treated as lock-not-held, because creating one would be a write under the subject root.
- **Elapsed time is never consulted** — no `mtime`, no age, no clock (D10, #72).
- Both checks report `warning`, never `failed`: retained residue is untidy, not non-conformant, and a machine mid-run must not read as a broken repository (D8). A `warning` still contributes its repair.
- No v1 repair carries `destructive`.
- `ROOT_SCRATCH_PATTERNS` is the single authoritative home for the scratch policy; `.gitignore` is its backstop, asserted by a consistency test (D11).

## `repository.residue.nested_ledger`

**Subject set.** Ledger run directories that live inside a *worktree* rather than in the primary checkout: for each immediate child directory `w` of `<root>/<vcs.worktree.root>` (from the authored contract; absent directory → empty set), every immediate child directory of `w/.superpowers/workflows/`. Each such directory is a run; its repository-relative path is the subject.

**Per-run classification.**

1. `lock = w/.superpowers/workflows/<run>/state.lock`. If it exists as a regular file, `fd = os.open(lock, os.O_RDONLY)`, then in a `try`/`finally`: attempt `fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)`; a `BlockingIOError` or `OSError` means the lock is held elsewhere; success means it is free, and `fcntl.flock(fd, fcntl.LOCK_UN)` then `os.close(fd)` in the `finally` releases it. If the file does not exist, treat the lock as free.
2. **Held → `live_owner`.** Classification stops; the ledger is not read.
3. **Free →** read `<run>/state.json` as UTF-8 JSON. Collect every attempt state as `[a["state"] for issue in state["issues"].values() for a in issue["attempts"]]`. An absent, unreadable, non-JSON or unexpectedly-shaped ledger yields an empty state list — never an exception (D19).
   - Every collected state equals `"merged"` **and** the list is non-empty → `terminal_residue`.
   - Anything else — a `failed` or `stopped` attempt, a still-`active` attempt no lock is holding, or an unreadable ledger → `unacknowledged_residue`.

```python
LEDGER_RESULT_STATES = ("merged", "stopped", "failed")
```

**The finding.** No run directories → `Outcome("passed")`. Otherwise the reason code is the most severe class present, in the order `live_owner`, `unacknowledged_residue`, `terminal_residue`, and:

```python
Outcome("warning", <reason_code>, <repair id for that reason code>, {
    "runs": <up to 8 offending repository-relative run directory paths, sorted>,
    "count": <total run directories found>,
    "live_owner": <int: runs whose lock is held>,
    "unacknowledged": <int>,
    "terminal": <int>,
})
```

Ordering `live_owner` first is what keeps the report honest: a report naming a removable run while another is live must not offer the `worktree` repair, because a reader acting on it would sweep the whole set.

**Repairs** (D26):
- `lifecycle.residue.nested_ledger.retain` → `{"module": "conformance", "safety_class": "user_action", "operation": None}` — for `live_owner` and `unacknowledged_residue`.
- `lifecycle.residue.nested_ledger.remove` → `{"module": "conformance", "safety_class": "worktree", "operation": None}` — for `terminal_residue` only. `operation` is null because v1 executes no repair.

## `repository.residue.root_scratch`

```python
ROOT_SCRATCH_PATTERNS = ("producer-report-*.json", "review-package-report-*.json",
                         "*.tmp.??????", ".resolve-project.*.tmp")
```

Match with `fnmatch.fnmatch` against the **names** of the immediate children of `<root>` that are regular files — never recursively, because these are `mktemp` outputs that escaped `$TMPDIR` into the repository root and nowhere else. No offender → `Outcome("passed")`. Otherwise:

```python
Outcome("warning", "root_scratch_present", "lifecycle.residue.root_scratch", {
    "files": <up to 8 offending file names, sorted>,
    "count": <total>,
})
```

Repair `lifecycle.residue.root_scratch` → `{"module": "conformance", "safety_class": "worktree", "operation": None}`. These files have no owner and no lock, so no lock probe applies.

## Registry entries this task adds

| Id | Domain | Subject kind | Req. | Depends on | Reason codes |
|---|---|---|---|---|---|
| `repository.residue.nested_ledger` | repository | residue | **optional** | `repository.contract.valid` | `live_owner`, `terminal_residue`, `unacknowledged_residue` |
| `repository.residue.root_scratch` | repository | residue | **optional** | `repository.contract.present` | `root_scratch_present` |

`root_scratch` depends only on `present`, so it still reports on a repository whose contract is invalid: its pattern set is a constant, not contract-derived.

- [ ] **Step 1: Write the failing test**

Append to `home/common/agent-skills/tests/test_conformance.py`; add `import fcntl` and `import fnmatch`.

```python
def make_run(root: Path, worktree: str, run_id: str, states: list) -> Path:
    """A nested ledger run directory with a state.json carrying `states`."""
    run = root / ".worktrees" / worktree / ".superpowers" / "workflows" / run_id
    run.mkdir(parents=True)
    (run / "state.json").write_text(json.dumps(
        {"issues": {"1": {"attempts": [{"state": s} for s in states]}}}),
        encoding="utf-8")
    return run


class NestedLedgerResidueTest(ReportAssertions, unittest.TestCase):
    """AC5: orphaned ledgers are reported with non-destructive repairs unless a
    lock proves no live owner."""

    def doctor(self, root: Path) -> dict:
        code, out, err = run("run", "--purpose", "doctor", "--repo-root", str(root))
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_no_worktrees_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self.doctor(make_root(Path(tmp)))
            check = {c["id"]: c for c in report["checks"]}[
                "repository.residue.nested_ledger"]
            self.assertEqual(check["status"], "passed")
            self.assertEqual(check["requirement"], "optional")

    def test_a_fully_merged_run_is_terminal_residue_with_a_worktree_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            make_run(root, "worktree-a", "run-1", ["merged"])
            report = self.doctor(root)
            check = {c["id"]: c for c in report["checks"]}[
                "repository.residue.nested_ledger"]
            self.assertEqual(check["status"], "warning")
            self.assertEqual(check["reason_code"], "terminal_residue")
            self.assertEqual(check["repair_id"],
                             "lifecycle.residue.nested_ledger.remove")
            self.assertEqual(check["facts"]["runs"],
                             [".worktrees/worktree-a/.superpowers/workflows/run-1"])
            self.assertEqual(check["facts"]["terminal"], 1)
            self.assertEqual(check["facts"]["live_owner"], 0)
            repair = {r["repair_id"]: r for r in report["repairs"]}[
                "lifecycle.residue.nested_ledger.remove"]
            self.assertEqual(repair["safety_class"], "worktree")
            self.assert_validates(report)

    def test_a_failed_attempt_is_unacknowledged_with_a_user_action_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            make_run(root, "worktree-a", "run-1", ["merged", "failed"])
            check = {c["id"]: c for c in self.doctor(root)["checks"]}[
                "repository.residue.nested_ledger"]
            self.assertEqual(check["reason_code"], "unacknowledged_residue")
            self.assertEqual(check["repair_id"],
                             "lifecycle.residue.nested_ledger.retain")

    def test_a_held_lock_reports_live_owner_and_outranks_terminal_residue(self):
        """The kernel, not a sleep, proves the live owner (D16)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            make_run(root, "worktree-a", "run-1", ["merged"])
            live = make_run(root, "worktree-b", "run-2", ["active"])
            lock = live / "state.lock"
            lock.write_bytes(b"")
            fd = os.open(lock, os.O_RDONLY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                report = self.doctor(root)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
            check = {c["id"]: c for c in report["checks"]}[
                "repository.residue.nested_ledger"]
            self.assertEqual(check["status"], "warning")
            self.assertEqual(check["reason_code"], "live_owner")
            self.assertEqual(check["repair_id"],
                             "lifecycle.residue.nested_ledger.retain")
            self.assertEqual(check["facts"]["live_owner"], 1)
            self.assertEqual(check["facts"]["count"], 2)
            self.assertEqual(
                {r["repair_id"]: r for r in report["repairs"]}[
                    "lifecycle.residue.nested_ledger.retain"]["safety_class"],
                "user_action")
            self.assert_validates(report)

    def test_the_lock_is_released_and_never_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            run_dir = make_run(root, "worktree-a", "run-1", ["merged"])
            self.doctor(root)
            self.assertFalse((run_dir / "state.lock").exists())
            (run_dir / "state.lock").write_bytes(b"")
            self.doctor(root)
            fd = os.open(run_dir / "state.lock", os.O_RDONLY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def test_residue_never_drives_the_outcome_to_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            make_run(root, "worktree-a", "run-1", ["failed"])
            report = self.doctor(root)
            self.assertEqual(report["outcome"]["status"], "passed")
            self.assertIsNone(report["outcome"]["primary_check_id"])

    def test_no_repair_in_the_report_is_destructive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            make_run(root, "worktree-a", "run-1", ["merged"])
            (root / "producer-report-abc123.json").write_text("{}", encoding="utf-8")
            report = self.doctor(root)
            self.assertTrue(report["repairs"])
            for repair in report["repairs"]:
                self.assertNotEqual(repair["safety_class"], "destructive")


class RootScratchResidueTest(ReportAssertions, unittest.TestCase):
    def test_scratch_files_in_the_root_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            (root / "producer-report-abc123.json").write_text("{}", encoding="utf-8")
            (root / "brief.tmp.AbC123").write_text("x", encoding="utf-8")
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", str(root))
            report = json.loads(out)
            check = {c["id"]: c for c in report["checks"]}[
                "repository.residue.root_scratch"]
            self.assertEqual(check["status"], "warning")
            self.assertEqual(check["reason_code"], "root_scratch_present")
            self.assertEqual(check["facts"]["files"],
                             ["brief.tmp.AbC123", "producer-report-abc123.json"])
            self.assertEqual(check["repair_id"], "lifecycle.residue.root_scratch")
            self.assert_validates(report)

    def test_a_clean_root_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = run("run", "--purpose", "doctor",
                               "--repo-root", str(make_root(Path(tmp))))
            self.assertEqual({c["id"]: c for c in json.loads(out)["checks"]}[
                "repository.residue.root_scratch"]["status"], "passed")

    def test_it_still_reports_when_the_contract_is_invalid(self):
        """It depends only on repository.contract.present, so it is not suppressed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            contract = json.loads(
                (root / ".agents/project.json").read_text(encoding="utf-8"))
            contract["bindings"]["extra"] = {}
            (root / ".agents/project.json").write_text(
                json.dumps(contract), encoding="utf-8")
            (root / "producer-report-x.json").write_text("{}", encoding="utf-8")
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", str(root))
            by_id = {c["id"]: c for c in json.loads(out)["checks"]}
            self.assertEqual(by_id["repository.contract.valid"]["status"], "failed")
            self.assertEqual(by_id["repository.residue.root_scratch"]["status"],
                             "warning")
            self.assertEqual(by_id["repository.paths.classified"]["status"],
                             "suppressed")


class ScratchPatternConsistencyTest(unittest.TestCase):
    """D11: the engine owns the policy; the tracked .gitignore is its backstop."""

    def test_every_engine_scratch_pattern_is_in_the_tracked_gitignore(self):
        module = load_module()
        rules = {line.strip() for line
                 in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
        for pattern in module.ROOT_SCRATCH_PATTERNS:
            self.assertIn(pattern, rules, f"{pattern} is not backstopped in .gitignore")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py`
Expected: the three new classes fail — `KeyError` on the two ids, and `AttributeError: module has no attribute 'ROOT_SCRATCH_PATTERNS'` for the consistency case.

- [ ] **Step 3: Write the minimal implementation**

```python
def check_residue_nested_ledger(context: "Context") -> "Outcome":
    """Contract: warning when a ledger run directory lives inside a worktree.
    A non-blocking flock is evidence of a live owner and is released at once;
    nothing is deleted and elapsed time is never consulted (D10)."""


def check_residue_root_scratch(context: "Context") -> "Outcome":
    """Contract: warning when an immediate child file of the project root
    matches the closed scratch pattern set."""
```

Add both registry entries and the three repairs. `import fcntl` and `import fnmatch` at the top of the script.

- [ ] **Step 4: Verify**

```bash
python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py
just agent-workflow-tests
python3 home/common/agent-skills/scripts/conformance.py run --purpose doctor --repo-root . \
  | python3 -c 'import json,sys; r=json.load(sys.stdin); print([c["id"] for c in r["checks"] if c["id"].startswith("repository.residue")], [x["safety_class"] for x in r["repairs"]])'
if python3 home/common/agent-skills/scripts/conformance.py run --purpose doctor --repo-root . \
   | grep -q '"destructive"'; then echo "a destructive repair reached the report"; exit 1; fi
```

Expected: unittest OK; `just agent-workflow-tests` passes; the third command lists both residue ids and a safety-class list containing no `destructive`; the guard prints nothing and exits 0.

Falsifiability at the base commit: the third command prints `[] ...` with neither residue id present.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/conformance.py \
        home/common/agent-skills/tests/test_conformance.py
git commit -m "$(cat <<'MSG'
feat(conformance): report retained residue with the lock as its only evidence

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0128oBTKhwUFwSefRhxX2PAy
MSG
)"
```
