# Task 2: workflow-state probes the live checkout, and a legacy attempt resumes and retries

Spec §1–§2 and T1–T5, per D2, D3, D4, D13, D14, D19. This task delivers A1's
helper side: `build-delivery --kind contract` reads a slugless worktree's live
branch, and control and direct-owner then resume or retry the legacy attempt at
its recorded path. No lifecycle code changes. Control and direct-owner already
bind a contract by its `remove_worktree` path, not by its branch.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Modify: `CLAUDE.md`
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py`

**Interfaces:**
- Consumes (Task 1): `runtime.requires_worktree_branch(value, policy)`,
  `runtime.worktree_pattern_refusal(worktree, clause)`, and
  `runtime.build_delivery(..., worktree_branch=...)`.
- Produces:
  - `workflow-state.py`: `GIT_TIMEOUT_SECONDS = 60`,
    `class WorktreeBranchUnavailable(Exception)` (its message is one §2 reason
    clause, without the leading `, and `), and
    `live_worktree_branch(path: str) -> str`.
  - `BuilderHarness.linked_worktree(name: str, branch: str) -> str`, and the
    module helper `authored_policy() -> dict`. Task 5 does not need them.

**Invariants:**
- git is read only for `--kind contract`, only when `requires_worktree_branch`
  is true, and only through `git -C <path> rev-parse --show-toplevel` and
  `git -C <path> symbolic-ref --quiet --short HEAD`. Both run by name on PATH
  with a 60-second timeout. No lock is taken and nothing is written.
- The probe maps each outcome to exactly one clause, in this order:

  | Condition | Clause |
  |---|---|
  | `os.path.lexists(path)` is false | `the worktree is absent` |
  | not a non-symlink directory (`_non_symlink(Path(path), stat.S_ISDIR)`) | `it is not a directory` |
  | `rev-parse` cannot start, times out or exits non-zero | `git failed: <detail>` |
  | `realpath` of its output ≠ `realpath(path)` | `it is not the top level of a git worktree` |
  | `symbolic-ref` exits 1 with empty stderr | `its HEAD is detached` |
  | `symbolic-ref` cannot start, times out, exits otherwise, or prints no single line | `git failed: <detail>` |

  `<detail>` is the first non-empty stderr line (stripped), else `exit <code>`.
  For a start failure it is `str(error)`, and for a timeout it is
  `timed out after 60 seconds` (D19).
- A probe failure raises
  `WorkflowError("build-delivery refused: " + runtime.worktree_pattern_refusal(worktree, clause))`
  before any build. A live branch outside the pattern is refused by the builder's
  re-check (Task 1), which carries the same kept prefix.
- The #181 worktree-policy veto (`check_contract_worktree`) still runs after
  every contract build, the live-branch ones included.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_delivery_workflow.py`:

1. Extend the resolver import to
   `from .test_resolve_project import git, make_home, make_project_root, run as run_resolver, source_contract`.

2. Add this module helper after the `LATER = ...` constant:

```python
SLUGLESS = "worktree-issue-171"


def authored_policy():
    """The seven sealed members of this repo's authored contract, by provenance key."""
    authored = source_contract()
    vcs, tracker = authored["bindings"]["vcs"], authored["bindings"]["tracker"]
    return {"project_id": authored["project"]["id"], "tracker_kind": tracker["kind"],
            "repository_slug": tracker["repo_slug"], "branch_pattern": vcs["branch_pattern"],
            "worktree_prefix": vcs["worktree"]["prefix"],
            "integration_branch": vcs["integration_branch"],
            "delete_branch": vcs["merge"]["delete_branch"]}
```

3. Add this method to `BuilderHarness`, after `worktree_project`:

```python
    def linked_worktree(self, name, branch):
        """A real `git worktree add` of the committed synthetic project (#192 D14).

        The project is committed once per root with the hermetic `git` helper,
        so the worktree carries `.agents/project.json` and resolves exactly as
        the root does. Returns the worktree's absolute path.
        """
        if getattr(self, "committed_root", None) != self.root:
            git(self.root, "add", "-A")
            git(self.root, "commit", "--quiet", "-m", "synthetic project")
            self.committed_root = self.root
        path = self.root / ".worktrees" / name
        git(self.root, "worktree", "add", "--quiet", "-b", branch, str(path))
        return str(path)
```

4. Add to `WorktreePolicyTest.test_help_states_the_contract_resolution_root` one
   more clause in its tuple:

```python
                "The contract's branch is the worktree path's final component when that "
                "name matches the issue branch pattern; otherwise it is the branch "
                "checked out at that path, which must be the top level of a git "
                "worktree, and that branch must match the pattern.",
```

5. Add this class after `WorktreePolicyTest`:

```python
class LegacyWorktreeTest(BuilderHarness, unittest.TestCase):
    """#192 A1, T1-T3: a slugless worktree takes its contract branch from its checkout."""

    @classmethod
    def setUpClass(cls):
        cls.model = load(MODEL, "delivery_model_legacy_worktree", package=True)

    def slugless_input(self):
        return self.contract_input(worktree=str(self.root / ".worktrees" / SLUGLESS))

    def refusal(self, clause):
        return (b"workflow-state: build-delivery refused: worktree name "
                b"'worktree-issue-171' does not match the issue branch pattern, and "
                + clause + b"\n")

    def test_a_slugless_worktree_builds_from_its_live_branch(self):
        self.project()
        path = self.linked_worktree(SLUGLESS, WORKTREE_NAME)
        value = self.slugless_input()
        self.assertEqual(value["worktree"], path)
        built = self.build("contract", value)
        contract = built["contract"]
        literals = {stage["id"]: stage["target_ref"].get("value")
                    for stage in contract["stages"]}
        self.assertEqual(contract["stages"][0]["target_ref"]["constraints"]["branch"],
                         WORKTREE_NAME)
        self.assertEqual((literals["delete_remote_branch"], literals["delete_local_branch"],
                          literals["remove_worktree"]), (WORKTREE_NAME, WORKTREE_NAME, path))
        self.assertEqual(contract["provenance"]["digest"], self.model.canonical_digest({
            "policy": authored_policy(), "issue": 171, "worktree": path,
            "source": {"kind": value["source_kind"], "reference": value["source_reference"]},
            "branch": WORKTREE_NAME}))
        git(self.root, "worktree", "remove", path)
        self.assertFalse(os.path.lexists(path))
        served = self.cli("build-delivery", "--repo-root", self.root, "--kind",
                          "initial-intent", "--input", "-",
                          stdin=json.dumps({"contract": contract}).encode()).stdout
        self.assertEqual(served, self.model.canonical_bytes(built["initial_intent"]))
        declared = {item["id"]: item for item in built["initial_intent"]["scopes"]}
        for stage in contract["stages"]:
            with self.subTest(stage=stage["id"]):
                scope = self.build("scope", {"contract": contract, "stage_id": stage["id"]})
                self.assertEqual(declared[scope["id"]], scope)

    def test_a_slugless_worktree_without_a_patterned_live_branch_refuses(self):
        def regular_file(path):
            Path(path).write_text("not a worktree\n", encoding="utf-8")

        def symlink(path):
            Path(path).symlink_to(self.linked_worktree("linked", WORKTREE_NAME),
                                  target_is_directory=True)

        def plain_directory(path):
            Path(path).mkdir()

        def detached(path):
            self.linked_worktree(SLUGLESS, WORKTREE_NAME)
            git(Path(path), "checkout", "--quiet", "--detach")

        def feature_branch(path):
            self.linked_worktree(SLUGLESS, "feature-x")

        def broken_gitdir(path):
            Path(path).mkdir()
            (Path(path) / ".git").write_text(f"gitdir: {self.root / 'missing'}\n",
                                             encoding="utf-8")

        for label, arrange, clause in (
                ("absent", None, lambda: b"the worktree is absent"),
                ("regular file", regular_file, lambda: b"it is not a directory"),
                ("symlink to a worktree", symlink, lambda: b"it is not a directory"),
                ("plain subdirectory of the checkout", plain_directory,
                 lambda: b"it is not the top level of a git worktree"),
                ("detached HEAD", detached, lambda: b"its HEAD is detached"),
                ("unpatterned branch", feature_branch,
                 lambda: b"its checked-out branch 'feature-x' does not match either"),
                ("git failure", broken_gitdir,
                 lambda: b"git failed: fatal: not a git repository: "
                         + str(self.root / "missing").encode())):
            with self.subTest(label=label):
                self.project()
                value = self.slugless_input()
                if arrange is not None:
                    arrange(value["worktree"])
                refused = self.build("contract", value, ok=False)
                self.assertEqual((refused.returncode, refused.stdout, refused.stderr),
                                 (2, b"", self.refusal(clause())))

    def test_a_patterned_name_reads_no_git(self):
        """T3: rule 1 never runs git, so a patterned directory with broken git builds."""
        self.project()
        raw = json.dumps(self.contract_input()).encode()
        absent = self.cli("build-delivery", "--repo-root", self.root, "--kind", "contract",
                          "--input", "-", stdin=raw).stdout
        self.worktree_project()
        shutil.rmtree(Path(self.worktree) / ".git")
        (Path(self.worktree) / ".git").write_text(f"gitdir: {self.root / 'missing'}\n",
                                                  encoding="utf-8")
        present = self.cli("build-delivery", "--repo-root", self.root, "--kind", "contract",
                           "--input", "-", stdin=raw).stdout
        self.assertEqual(present, absent)
```

6. `ContractLifecycleTest.attempt` must build the attempt at the path it is
   given, because an attempt's launch event records the same worktree, and a
   later `update` of `worktree` alone fails `invalid launch identity`. Change its
   first two lines to:

```python
    def attempt(self, issue, number=1, *, worktree=None, **changes):
        value = self.workflow.new_control_attempt(issue=issue, attempt_number=number,
            worktree=worktree or self.worktree, now=NOW, deadline_at="2026-09-21T01:00:00Z")
```

7. Add these two methods to `ContractLifecycleTest`, after
   `test_contractless_direct_retry_on_an_absent_path_asks_for_its_contract`:

```python
    def test_control_resumes_a_legacy_slugless_attempt_with_its_built_contract(self):
        """T4: a suspended schema-2 attempt at a slugless live worktree resumes in place."""
        self.project()
        path = self.linked_worktree(SLUGLESS, WORKTREE_NAME)
        suspended = self.attempt(171, worktree=path)
        self.workflow.suspend_attempt(suspended, blocked_on="external", now=NOW)
        state = self.write_run("legacy", [suspended], schema=2)
        recorded = [{"issue": 171, "recorded": {"path": path,
                     "state": "matching_issue_branch"}, "candidate": None}]
        asked = self.control("legacy", self.control_request([171], now=LATER,
                                                            worktrees=recorded))
        self.assertEqual((asked["summaries"][0]["contract_digest"],
                          asked["summaries"][0]["requirements"]), (None, CONTRACT_REQUIRED))
        self.assertEqual([item for item in asked["actions"] if item.get("issue") == 171], [])
        built = self.build("contract", self.contract_input(worktree=path))
        digest = self.model.canonical_digest(built["contract"])
        resumed = self.control("legacy", self.control_request([171], now=LATER,
            worktrees=recorded, contracts={"171": built["contract"]},
            intents={"171": [built["initial_intent"]]}))
        action = resumed["actions"][0]
        self.assertEqual((action["kind"], action["worktree"], action["contract_digest"]),
                         ("resume", path, digest))
        self.assertEqual(
            json.loads(state.read_text())["issues"]["171"]["delivery"]["contract_digest"],
            digest)

    def test_direct_retries_a_legacy_slugless_attempt_in_place(self):
        """T5: a failed schema-2 direct attempt at a slugless live worktree retries in place."""
        self.project()
        path = self.linked_worktree(SLUGLESS, WORKTREE_NAME)
        self.write_run("direct-171-000001", [self.attempt(
            171, worktree=path, state="failed", result_source="owner", finished_at=NOW,
            result=self.workflow.terminal_result(171, "failed", "one"))], schema=2)
        facts = {"tracker": TRACKER, "forge": NO_PR, "worktree": {"issue": 171,
                 "recorded": {"path": path, "state": "matching_issue_branch"},
                 "candidate": None}}
        self.assertEqual(self.direct(**facts), {"interface_version": 2, "kind": "observe",
            "issue": 171, "run_id": "direct-171-000001", "requirements": CONTRACT_REQUIRED})
        built = self.build("contract", self.contract_input(worktree=path))
        owner = self.direct(delivery_contract=built["contract"],
                            authorization_intents=[built["initial_intent"]], **facts)
        self.assertEqual((owner["kind"], owner["launch_kind"], owner["attempt"],
                          owner["worktree"]), ("owner", "retry", 2, path))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k LegacyWorktreeTest -k legacy_slugless -k test_help_states`
Expected: `FAILED`. T1, T4 and T5 fail at the contract build with exit 2 and
`worktree name 'worktree-issue-171' does not match the issue branch pattern`.
All seven T2 subtests fail, because stderr carries that bare prefix with no
clause. The help pin fails. T3 already passes, since it guards rule 1's no-git
property.

- [ ] **Step 3: Implement the probe and wire it**

In `workflow-state.py`, beside `check_contract_worktree`, add this code as
written. It fixes the clause map and the order of the checks (D19):

```python
GIT_TIMEOUT_SECONDS = 60


class WorktreeBranchUnavailable(Exception):
    """The live checkout names no branch; the message is the reason clause (#192 D19)."""


def _worktree_git(path: str, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", path, *args], capture_output=True,
                              check=False, timeout=GIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        raise WorktreeBranchUnavailable(
            f"git failed: timed out after {GIT_TIMEOUT_SECONDS} seconds") from error
    except OSError as error:
        raise WorktreeBranchUnavailable(f"git failed: {error}") from error


def _git_failed(completed: subprocess.CompletedProcess) -> WorktreeBranchUnavailable:
    lines = [line.strip() for line in
             completed.stderr.decode("utf-8", "replace").splitlines() if line.strip()]
    return WorktreeBranchUnavailable(
        "git failed: " + (lines[0] if lines else f"exit {completed.returncode}"))


def live_worktree_branch(path: str) -> str:
    """The branch checked out at ``path``, a git worktree's top level (#192 §1, D3).

    Read-only: ``git`` by name on PATH with a 60-second timeout, and no lock.
    ``lexists`` counts a dangling symlink as present, so it is refused as not a
    directory. Any other outcome raises ``WorktreeBranchUnavailable`` carrying
    the reason clause.
    """
    if not os.path.lexists(path):
        raise WorktreeBranchUnavailable("the worktree is absent")
    if not _non_symlink(Path(path), stat.S_ISDIR):
        raise WorktreeBranchUnavailable("it is not a directory")
    toplevel = _worktree_git(path, "rev-parse", "--show-toplevel")
    if toplevel.returncode != 0:
        raise _git_failed(toplevel)
    top = toplevel.stdout.decode("utf-8", "replace").rstrip("\n")
    if os.path.realpath(top) != os.path.realpath(path):
        raise WorktreeBranchUnavailable("it is not the top level of a git worktree")
    head = _worktree_git(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    if head.returncode == 1 and not head.stderr.strip():
        raise WorktreeBranchUnavailable("its HEAD is detached")
    branch = head.stdout.decode("utf-8", "replace").rstrip("\n")
    if head.returncode != 0 or not branch or "\n" in branch:
        raise _git_failed(head)
    return branch
```

In `command_build_delivery`, between resolving `policy` and the installed-intent
lookup, add:

```python
    worktree_branch = None
    if args.kind == "contract" and runtime.requires_worktree_branch(value, policy):
        try:
            worktree_branch = live_worktree_branch(value["worktree"])
        except WorktreeBranchUnavailable as unavailable:
            raise WorkflowError("build-delivery refused: " + runtime.worktree_pattern_refusal(
                value["worktree"], str(unavailable))) from unavailable
```

Pass `worktree_branch=worktree_branch` to `runtime.build_delivery`. Append this
sentence to the command's docstring:
`For --kind contract, a worktree whose name is not an issue branch is probed for
the branch it has checked out (#192 D3); that is the command's only git read.`

In the `build-delivery` parser description, insert this sentence directly after
`...and seals only that policy. `:
`The contract's branch is the worktree path's final component when that name
matches the issue branch pattern; otherwise it is the branch checked out at that
path, which must be the top level of a git worktree, and that branch must match
the pattern. `

In `CLAUDE.md`, in the "Delivery objects are built" bullet, replace
`when the input worktree already exists it resolves there too and refuses if any sealed member differs)`
with
`when the input worktree already exists it resolves there too and refuses if any sealed member differs; when the worktree's name is not an issue branch, the contract takes the branch checked out there, so a legacy slugless worktree keeps its recorded path)`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py`
Expected: `OK`, 5 tests more than at base, no `FAIL:`/`ERROR:`. That includes
every existing builder, worktree-policy, helper-input, loop and lifecycle test,
unchanged (T3).

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_delivery.py home/common/agent-skills/tests/test_workflow_state.py`
Expected: `OK`.

Run: `if grep -q "keeps its recorded path)" CLAUDE.md; then echo claude-ok; else exit 1; fi`
Expected: `claude-ok`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_delivery_workflow.py CLAUDE.md
git commit -m "feat(workflow-state): read a slugless worktree's live branch for its contract (#192)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
