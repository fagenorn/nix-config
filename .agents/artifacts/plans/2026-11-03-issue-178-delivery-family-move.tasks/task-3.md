# Task 3: Replay a pre-move ledger across the move

Decisions: D7, D13 (and D16's archive scope, D17's policy `HOME`). Spec §
"The ledger and digest regression test (D7)" and the regression floor. Work
from the worktree root. `T` = `home/common/agent-skills/tests`.

**Files:**
- Modify: `T/test_delivered_control.py`

**Interfaces:**
- Consumes: Task 1's `DeliveredControlHarness` (`project()`, which leaves
  `self.home` holding the platform manifest, the host declaration and the
  budget-policy link; `contract_input()`; `request(minute, *, recorded, contracts=False, …) -> bytes`,
  which reads `self.worktrees` and `self.built`; `validated(name, value)`),
  and this module's `DELIVERED`, `ISSUES`, `DISPATCH` and `at`.
- Produces: `PRE_MOVE_BASE` and `REPO` module constants and
  `class PreMoveLedgerReplayTest(DeliveredControlHarness, unittest.TestCase)`
  with one test.

**Invariants:**
- A missing base commit fails the class; it is never skipped.
- The base helper runs only from its archive: that commit's
  `python/agent_tools`, `home/common/agent-skills/scripts` and policy, under
  `PYTHONPATH=<archive>/python` (the replay pattern of the custody, cutover
  and suspension suites).
- The moved helper runs as `[sys.executable, "-m", "agent_tools.workflow_state", …]`
  under the recipe's `PYTHONPATH`. Both get `HOME=self.home` and the same
  `--repo-root`.

- [ ] **Step 1: Write the test**

Add below the existing imports' constants (after `DISPATCH = …`):

```python
# The delivery base of #178: the last commit whose workflow-state is the flat script.
PRE_MOVE_BASE = "f6a48dcf66fbb2171f66920c32afd4f9e5056a93"
REPO = Path(__file__).resolve().parents[4]
```

and at the end of the module:

```python
class PreMoveLedgerReplayTest(DeliveredControlHarness, unittest.TestCase):
    """#178: a ledger the pre-move helper wrote progresses under the moved one, the
    pre-move helper reads the ledger the moved one wrote (a rollback), and one contract
    input builds to the same bytes under both."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        found = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e",
                                f"{PRE_MOVE_BASE}^{{commit}}"], capture_output=True)
        if found.returncode != 0:
            raise AssertionError(
                f"base commit {PRE_MOVE_BASE} is missing; fetch it, do not skip (#178)")
        cls.base = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, cls.base, True)
        archive = subprocess.run(
            ["git", "-C", str(REPO), "archive", PRE_MOVE_BASE, "python/agent_tools",
             "home/common/agent-skills/scripts",
             "home/common/agent-skills/artifact-budget-policy.json"],
            capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(cls.base)], input=archive.stdout, check=True)

    def helper(self, generation, *args, stdin=None):
        """One exit-0 run of the pre-move helper from its archive, or of the moved one."""
        if generation == "base":
            argv = [sys.executable,
                    str(self.base / "home/common/agent-skills/scripts/workflow-state.py")]
            env = {**os.environ, "HOME": str(self.home),
                   "PYTHONPATH": str(self.base / "python")}
        else:
            argv = [sys.executable, "-m", "agent_tools.workflow_state"]
            env = {**os.environ, "HOME": str(self.home)}
        completed = subprocess.run([*argv, *map(str, args)], input=stdin,
                                   capture_output=True, check=False, env=env, timeout=300)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        return completed

    def test_a_pre_move_ledger_progresses_both_ways_and_builds_the_same_bytes(self):
        self.project()
        (self.home / ".agents/share/host-declaration.json").write_text(json.dumps(
            {"schema_version": 1, "routes": {
                "claude-code": {"support": "supported", "agent_slots": 7},
                "codex": {"support": "unsupported"}}}), encoding="utf-8")
        self.worktrees = {n: str(self.root / ".worktrees" / f"worktree-issue-{n}-shape")
                          for n in ISSUES}
        build = ("build-delivery", "--repo-root", self.root, "--kind", "contract",
                 "--input", "-")
        contract_input = json.dumps(self.contract_input(
            issue=DELIVERED, worktree=self.worktrees[DELIVERED], now=at(0),
            source_reference=f"invocation:/orchestrate-issues {DELIVERED}")).encode()
        minted = json.loads(self.helper("base", "init-run", "--repo-root", self.root,
                                        "--creation-key", "pre-move", "--now", at(0)
                                        ).stdout)["run_id"]
        run_args = ("--repo-root", self.root, "--run-id", minted)
        ledger = self.root / ".superpowers/workflows" / minted / "state.json"
        base_built = self.helper("base", *build, stdin=contract_input).stdout
        self.built = {DELIVERED: json.loads(base_built)}
        spawned = json.loads(self.helper(
            "base", "control", *run_args, "--request-file", "-",
            stdin=self.request(0, recorded={DELIVERED: None}, contracts=True)).stdout)
        launches = [a["custody"]["action_id"] for a in spawned["actions"]
                    if a["kind"] in DISPATCH]
        self.assertEqual(launches, [f"{DELIVERED}:1:1"])

        # The moved helper takes over the ledger the pre-move helper wrote.
        registered = json.loads(self.helper(
            "head", "register-worker", *run_args, "--now", at(1),
            "--action-id", launches[0]).stdout)
        self.assertEqual(registered["worker_id"], f"{DELIVERED}:1:1:w1")
        reply = self.helper("head", "control", *run_args, "--request-file", "-",
                            stdin=self.request(2, recorded={DELIVERED: "matching_issue_branch"}))
        self.validated("workflow-response", reply.stdout)
        state = json.loads(ledger.read_text(encoding="utf-8"))
        self.assertEqual(state["schema_version"], 11)
        self.assertEqual([(w["worker_id"], w["launch"]) for w in state["workers"]],
                         [(f"{DELIVERED}:1:1:w1", f"{DELIVERED}:1:1")])

        # Sealed digests are unchanged: the same input builds the same bytes.
        self.assertEqual(self.helper("head", *build, stdin=contract_input).stdout, base_built)

        # A generation rollback puts the pre-move helper back in front of this ledger.
        self.helper("base", "control", *run_args, "--request-file", "-",
                    stdin=self.request(3, recorded={DELIVERED: "matching_issue_branch"}))
```

- [ ] **Step 2: Run it**

Run (timeout 900 s): `PYTHONPATH=$PWD/python python3 -m unittest -v -k PreMoveLedgerReplay home/common/agent-skills/tests/test_delivered_control.py`
Expected: `Ran 1 test`, `OK`. It cannot be red first: both helpers exist
at this head and the property is that they agree. Show it can fail: replace
`base_built` in the byte-identity assertion with `base_built + b" "`, rerun,
see `FAIL` on that line, and restore it.

- [ ] **Step 3: Verify the slice**

1. Focused (timeout 1800 s): `PYTHONPATH=$PWD/python python3 -m agent_tools.suite_runner home/common/agent-skills/tests/test_delivered_control.py home/common/agent-skills/tests/test_workflow_state.py`:
   exit 0.
2. Demo, shown and not committed. `H` is the one path
   `nix-store --query --requisites ./result | grep -- '-home-manager-files$'`
   prints after `just build`; `D` is a new directory under `launch-scope scratch`
   holding `home/.agents`, a symlink to `$H/.agents`, an empty `repo`, and
   `base`, the same three-path archive of `PRE_MOVE_BASE`. With `HOME=$D/home`:
   the pre-move helper (`PYTHONPATH=$D/base/python python3 $D/base/home/common/agent-skills/scripts/workflow-state.py`)
   runs `init-run --repo-root $D/repo --creation-key demo`; then
   `$H/.agents/bin/workflow-state init-run --repo-root $D/repo --run-id <minted>`
   and `$H/.agents/bin/workflow-state control --repo-root $D/repo --run-id <minted> --request-file <f>`,
   where `<f>` holds `DeliveryAdmissionTest.control_request()`'s value from
   `T/test_delivery_workflow.py` with `now` set to the current UTC second,
   each exit 0; and `test ! -e "$H/.agents/lib/python"` holds. Paste the
   commands and exits into the review report.

- [ ] **Step 4: Commit**

One commit through `launch-commit`, subject
`test(issue-178): replay a pre-move ledger across the move`.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":3,"records":[{"bounds":[{"added_lines":136,"boundary":"all","deleted_lines":26,"record_bytes":34816,"support":{"covers":["a46","b15","c01"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"c01","last_task":3,"owner":3,"path":"home/common/agent-skills/tests/test_delivered_control.py"}]}}
```
