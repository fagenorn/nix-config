# Task 6: Residue checks — nested ledgers proved by `flock`, and root scratch

**Files:**
- Modify: `home/common/agent-skills/scripts/conformance.py`
- Modify: `home/common/agent-skills/tests/test_conformance.py`

**Interfaces:**
- Consumes from Task 2: `Check`, `Outcome`, `Context` (`context.root`, `context.contract`), `REGISTRY`, `REPAIRS`, `bound_facts`.
- Produces `check_residue_nested_ledger`, `check_residue_root_scratch`, `ROOT_SCRATCH_PATTERNS`, `TERMINAL_LEDGER_STATES`, `REMOVABLE_LEDGER_STATE`, two registry entries and three repairs.

**Invariants:**
- **Nothing is deleted, moved or written.** v1 reports repairs; it never executes one (D10).
- The lock is *evidence*, never a claim: a non-blocking `fcntl.flock(LOCK_EX | LOCK_NB)` is attempted and released in a `finally`.
- The lock file is opened `os.O_RDONLY` and is **never created**. A run directory with **no** `state.lock` therefore proves nothing, and is classified `unacknowledged_residue` — not "free" (D34). Creating one to probe would be a write under the subject root, and treating its absence as freedom would offer a removal repair with no evidence at all behind it.
- The `worktree` removal repair is offered **only** when a lock was actually acquired *and* the ledger proves durable termination (D34). Every other shape — missing lock, unreadable or malformed ledger, an attempt with no result, a result whose state does not match its attempt — is `unacknowledged_residue`.
- **Elapsed time is never consulted** — no `mtime`, no age, no clock (D10, #72).
- Both checks report `warning`, never `failed`: retained residue is untidy, not non-conformant, and a machine mid-run must not read as a broken repository (D8). A `warning` still contributes its repair.
- No v1 repair carries `destructive`.
- `ROOT_SCRATCH_PATTERNS` is the single authoritative home for the scratch policy; `.gitignore` is its backstop, asserted by a consistency test (D11).
- Run paths and file names reach `facts` through `bound_facts` (D30): a run id and a worktree name are authored strings with no length ceiling.

## `repository.residue.nested_ledger`

**Subject set.** Ledger run directories living inside a *worktree* rather than in the primary checkout: for each immediate child directory `w` of `<root>/<vcs.worktree.root>` (from the authored contract; absent directory → empty set), every immediate child directory of `w/.superpowers/workflows/`. Each such directory is a run; its repository-relative path is the subject.

**Per-run classification (D34).** Two independent proofs are required before a run may be called removable, and each has its own failure mode:

1. **The lock proof.** `lock = <run>/state.lock`. If it is not an existing regular file, the run is `unacknowledged_residue` and classification stops — nothing was proved. Otherwise `fd = os.open(lock, os.O_RDONLY)` and, in a `try`/`finally`, attempt `fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)`; a `BlockingIOError` or `OSError` means the lock is held elsewhere → `live_owner`, classification stops and the ledger is not read. Success means no live owner; the `finally` runs `fcntl.flock(fd, fcntl.LOCK_UN)` then `os.close(fd)`.
2. **The durability proof.** Read `<run>/state.json` as UTF-8 JSON. An absent, unreadable, non-JSON or unexpectedly-shaped ledger → `unacknowledged_residue`, never an exception (D19). Otherwise collect `[a for issue in state["issues"].values() for a in issue["attempts"]]`. The run is `terminal_residue` only when the list is non-empty **and every attempt** satisfies all three of: `a["state"] == REMOVABLE_LEDGER_STATE`; `a["result"]` is an object; and `a["result"]["state"] == a["state"]`. Anything else — a `failed` or `stopped` attempt, a still-`active` attempt no lock is holding, a terminal attempt carrying no result, a result whose state disagrees with the attempt's — is `unacknowledged_residue`.

```python
TERMINAL_LEDGER_STATES = ("merged", "stopped", "failed")
REMOVABLE_LEDGER_STATE = "merged"
```

The result requirement mirrors the ledger's own validator, which refuses a terminal attempt carrying no matching result: a termination never written down is an inference, not a record, and D10 admits the `worktree` class only against a record.

**The finding.** No run directories → `Outcome("passed")`. Otherwise the reason code is the most severe class present, in the order `live_owner`, `unacknowledged_residue`, `terminal_residue`, and:

```python
Outcome("warning", <reason_code>, <repair id for that reason code>, {
    "runs": bound_facts(run_paths),      # ≤ 8 repository-relative run directories
    "count": <total run directories found>,
    "live_owner": <int>, "unacknowledged": <int>, "terminal": <int>,
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

Match with `fnmatch.fnmatch` against the **names** of the immediate children of `<root>` that are regular files — never recursively, because these are `mktemp` outputs that escaped `$TMPDIR` into the repository root and nowhere else. No offender → `Outcome("passed")`. Otherwise `Outcome("warning", "root_scratch_present", "lifecycle.residue.root_scratch", {"files": bound_facts(names), "count": len(names)})`.

Repair `lifecycle.residue.root_scratch` → `{"module": "conformance", "safety_class": "worktree", "operation": None}`. These files have no owner and no lock, so no lock probe applies.

## Registry entries this task adds

| Id | Domain | Subject kind | Req. | Depends on | `findings`: reason code → repair id |
|---|---|---|---|---|---|
| `repository.residue.nested_ledger` | repository | residue | **optional** | `repository.contract.valid` | `live_owner` → `…nested_ledger.retain`; `unacknowledged_residue` → `…nested_ledger.retain`; `terminal_residue` → `…nested_ledger.remove` |
| `repository.residue.root_scratch` | repository | residue | **optional** | `repository.contract.present` | `root_scratch_present` → `lifecycle.residue.root_scratch` |

`root_scratch` depends only on `present`, so it still reports on a repository whose contract is invalid: its pattern set is a constant, not contract-derived.

- [ ] **Step 1: Write the failing test**

Append to `home/common/agent-skills/tests/test_conformance.py`; add `import fcntl`.

```python
def make_run(root: Path, worktree: str, run_id: str, states: list, *,
             lock: bool = True, results: bool = True,
             ledger: str | None = None) -> Path:
    """A nested ledger run directory, by default a removable one.

    `lock` writes the canonical state.lock, `results` gives each terminal
    attempt a matching durable result, and `ledger` replaces the state.json
    bytes outright. A removable run needs all of them (D34).
    """
    run = root / ".worktrees" / worktree / ".superpowers" / "workflows" / run_id
    run.mkdir(parents=True)
    attempts = [{"state": s,
                 "result": {"state": s} if results else None} for s in states]
    run.joinpath("state.json").write_text(
        ledger if ledger is not None
        else json.dumps({"issues": {"1": {"attempts": attempts}}}),
        encoding="utf-8")
    if lock:
        run.joinpath("state.lock").write_bytes(b"")
    return run


class NestedLedgerResidueTest(ReportAssertions, unittest.TestCase):
    """AC5: orphaned ledgers are reported with non-destructive repairs unless a
    lock proves no live owner."""

    def check(self, root):
        return doctor(self, root)[1]["repository.residue.nested_ledger"]

    def test_a_locked_merged_run_with_results_is_removable(self):
        with fixture() as tmp:
            root = make_root(tmp)
            make_run(root, "worktree-a", "run-1", ["merged"])
            report, by_id = doctor(self, root)
            check = by_id["repository.residue.nested_ledger"]
            self.assertEqual(
                [check["status"], check["reason_code"], check["repair_id"]],
                ["warning", "terminal_residue",
                 "lifecycle.residue.nested_ledger.remove"])
            self.assertEqual(check["facts"]["runs"],
                             [".worktrees/worktree-a/.superpowers/workflows/run-1"])
            self.assertEqual([check["facts"]["terminal"],
                              check["facts"]["live_owner"]], [1, 0])
            self.assertEqual(
                {r["repair_id"]: r for r in report["repairs"]}[
                    "lifecycle.residue.nested_ledger.remove"]["safety_class"],
                "worktree")
            self.assert_validates(report)

    def test_neither_proof_alone_makes_a_run_removable(self):
        """D34: a missing lock, a missing result, a mismatched result, a
        non-merged state and a malformed ledger are all unacknowledged."""
        cases = {
            "no_lock": dict(states=["merged"], lock=False),
            "no_result": dict(states=["merged"], results=False),
            "not_merged": dict(states=["merged", "failed"]),
            "still_active": dict(states=["active"], results=False),
            "malformed": dict(states=["merged"], ledger="{ broken"),
            "mismatched": dict(states=["merged"],
                               ledger=json.dumps({"issues": {"1": {"attempts": [
                                   {"state": "merged",
                                    "result": {"state": "stopped"}}]}}})),
        }
        for name, kwargs in cases.items():
            with self.subTest(case=name), fixture() as tmp:
                root = make_root(tmp)
                make_run(root, "worktree-a", "run-1", **kwargs)
                check = self.check(root)
                self.assertEqual(
                    [check["reason_code"], check["repair_id"],
                     check["facts"]["terminal"]],
                    ["unacknowledged_residue",
                     "lifecycle.residue.nested_ledger.retain", 0])

    def test_a_held_lock_reports_live_owner_and_outranks_terminal_residue(self):
        """The kernel, not a sleep, proves the live owner (D16)."""
        with fixture() as tmp:
            root = make_root(tmp)
            make_run(root, "worktree-a", "run-1", ["merged"])
            live = make_run(root, "worktree-b", "run-2", ["active"], results=False)
            fd = os.open(live / "state.lock", os.O_RDONLY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                report, by_id = doctor(self, root)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
            check = by_id["repository.residue.nested_ledger"]
            self.assertEqual(
                [check["status"], check["reason_code"], check["repair_id"]],
                ["warning", "live_owner",
                 "lifecycle.residue.nested_ledger.retain"])
            self.assertEqual([check["facts"]["live_owner"],
                              check["facts"]["count"]], [1, 2])
            self.assertEqual(
                {r["repair_id"]: r for r in report["repairs"]}[
                    "lifecycle.residue.nested_ledger.retain"]["safety_class"],
                "user_action")
            self.assert_validates(report)

```

Four more cases complete the class. `test_the_lock_is_released_and_never_created` builds one unlocked and one locked run, calls `doctor`, then asserts the unlocked run still has **no** `state.lock` and that the test process can itself take `LOCK_EX | LOCK_NB` on the locked one — the engine created nothing and released what it took. `test_no_worktrees_passes` asserts a clean root gives `passed` with `requirement == "optional"`. `test_residue_never_drives_the_outcome_to_failed` adds one `["failed"]` run and asserts `outcome` is exactly `{"status": "passed", "primary_check_id": None}` (D8). `test_no_repair_in_the_report_is_destructive` adds one removable run plus a `producer-report-abc123.json` in the root and asserts `report["repairs"]` is non-empty and holds no `destructive` `safety_class`.

**`RootScratchResidueTest`** — the check is `repository.residue.root_scratch`:

| Case | Fixture mutation | Expected |
|---|---|---|
| scratch present | write `producer-report-abc123.json` and `brief.tmp.AbC123` in the root | `warning` / `root_scratch_present` / `lifecycle.residue.root_scratch`, `facts["files"] == ["brief.tmp.AbC123", "producer-report-abc123.json"]` |
| clean root | none | `passed` |
| invalid contract | add `bindings.extra` to the contract, write `producer-report-x.json` | `repository.contract.valid` is `failed`, `repository.paths.classified` is `suppressed`, and this check is still `warning` — it depends only on `repository.contract.present` |

**`ScratchPatternConsistencyTest`** (D11) loads the module and asserts every member of `ROOT_SCRATCH_PATTERNS` appears as a stripped line of the tracked `REPO_ROOT/.gitignore`, so the engine keeps the policy and the ignore file stays its honest backstop.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py`
Expected: the three new classes fail — `KeyError` on the two ids, and `AttributeError: module has no attribute 'ROOT_SCRATCH_PATTERNS'` for the consistency case.

- [ ] **Step 3: Write the minimal implementation**

```python
def check_residue_nested_ledger(context: "Context") -> "Outcome":
    """Contract: warning when a ledger run directory lives inside a worktree.
    A run is removable only when a non-blocking flock on its existing
    state.lock succeeded and every attempt is merged with a matching durable
    result; anything less is unacknowledged. Nothing is deleted, no lock is
    created, and elapsed time is never consulted (D10, D34)."""


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
  > /tmp/conformance-residue.json
python3 - <<'PY'
import json
report = json.load(open("/tmp/conformance-residue.json"))
print([c["id"] for c in report["checks"] if c["id"].startswith("repository.residue")])
classes = [r["safety_class"] for r in report["repairs"]]
print(classes)
assert "destructive" not in classes, "a destructive repair reached the report"
PY
rm -f /tmp/conformance-residue.json
```

Expected: unittest OK; `just agent-workflow-tests` passes; the script lists both residue ids and a safety-class list with no `destructive`, and the assertion holds.

Falsifiability at the base commit: the script prints `[]` with neither residue id present.

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
