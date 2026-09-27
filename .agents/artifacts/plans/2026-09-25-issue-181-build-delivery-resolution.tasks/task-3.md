# Task 3: Cross-check an existing contract worktree and state the root in help

Decisions: D3, D4, D5, D6, D7 (help text is authoritative), D8, D9 (the
dangling-symlink case). Spec §2 "The contract build sequence", §4 "Worktree
states" and §5 "Where the root is stated". Work from the worktree root. Every
shell block starts with `set -euo pipefail` (`set -uo pipefail` in a
watch-it-fail step) and these abbreviations, which the
blocks below omit:

```bash
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
```

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (a new
  `check_contract_worktree` beside `resolve_project_policy`, one call in
  `command_build_delivery`, and the `build-delivery` subparser in `build_parser`)
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py` (one
  `BuilderHarness` method and one new class)

**Interfaces:**
- Consumes (Task 1): `resolve_project_policy(root: str, label: str) -> dict[str, Any]`,
  which raises `WorkflowError` with the labelled refused, failed or timed-out
  line. Also `BuilderHarness.resolver_refusal_line(root, label) -> bytes`.
- Consumes (Task 2): `DeliveryRuntime.check_worktree_policy(repo_root_policy, worktree_policy) -> None`.
  It raises `ValueError`, for example with
  `worktree policy differs from repo-root policy: bindings.vcs.integration_branch`.
- Produces: `check_contract_worktree(runtime: Any, policy: dict[str, Any], worktree: str) -> None`
  in workflow-state.py, and `BuilderHarness.worktree_project(mutate=None) -> Path`
  in the tests.

**Invariants:**
- An absent `worktree` (a reserved candidate) gets no second resolver run, and
  its output is unchanged. Every existing builder test leaves the harness
  worktree absent and stays green.
- The second resolution runs only after `runtime.build_delivery` has succeeded,
  so it only targets an absolute, normalized, pattern-matching path (D5). A
  malformed input still refuses before any second run.
- Presence is `os.path.lexists`, so a dangling symlink counts as present and
  fails closed.
- An existing worktree whose sealed members agree yields output byte-identical
  to the absent case, even when an unsealed member differs.
- A divergence, a worktree refusal, a failure or a timeout each exits 2 with
  empty stdout and one stderr line: `workflow-state: build-delivery refused: <reason>`
  for a divergence, and Task 1's labelled line at `worktree` for the others.
- The other six kinds never reach `check_contract_worktree`.
- The help text below describes this code as it will behave once the task is
  done. Nothing in it is aspirational.

- [ ] **Step 1: Confirm the consumed interfaces exist**

```bash
grep -c 'def resolve_project_policy(root: str, label: str)' $S/workflow-state.py
grep -c 'def check_worktree_policy' $S/workflow_delivery_build.py $S/workflow_delivery.py
grep -c 'def resolver_refusal_line' $T/test_delivery_workflow.py
```

Expected: `1`, then `…build.py:1` and `…delivery.py:1`, then `1`. If any is
`0`, stop, because Tasks 1 and 2 have not landed.

- [ ] **Step 2: Write the failing tests**

In `class BuilderHarness` of `T/test_delivery_workflow.py`, add this method
directly after `resolver_refusal_line`:

```python
    def worktree_project(self, mutate=None):
        """Lay a resolvable project at the contract input's worktree path (D8).

        `make_project_root` writes the contract, instruction source and current
        projections into a fresh temp dir. Renaming it into `.worktrees/` gives
        the worktree resolver no unintended reason to refuse, and the root's
        cleanup removes it.
        """
        contract = source_contract()
        if mutate is not None:
            mutate(contract)
        return make_project_root(contract).rename(self.worktree)
```

Add this class directly after `class DeliveryBuilderTest`:

```python
class WorktreePolicyTest(BuilderHarness, unittest.TestCase):
    """D3, D4, D7: an existing contract worktree can veto a build, never supply policy."""

    def contract_bytes(self, *, ok=True):
        return self.cli("build-delivery", "--repo-root", self.root, "--kind", "contract",
                        "--input", "-", stdin=json.dumps(self.contract_input()).encode(),
                        ok=ok)

    def test_an_agreeing_or_unsealed_difference_builds_byte_identical_output(self):
        def more_parallel(contract_value):
            contract_value["bindings"]["workflow"]["orchestration"]["max_parallel"] = 5
        for label, mutate in (("identical project", None),
                              ("unsealed difference", more_parallel)):
            with self.subTest(label=label):
                self.project()
                absent = self.contract_bytes().stdout
                self.worktree_project(mutate)
                self.assertEqual(self.contract_bytes().stdout, absent)

    def test_a_divergent_sealed_member_refuses(self):
        def retarget(contract_value):
            contract_value["bindings"]["vcs"]["integration_branch"] = "dev"
        self.project()
        self.worktree_project(retarget)
        refused = self.contract_bytes(ok=False)
        self.assertEqual((refused.returncode, refused.stdout, refused.stderr), (2, b"",
            b"workflow-state: build-delivery refused: worktree policy differs from "
            b"repo-root policy: bindings.vcs.integration_branch\n"))

    def test_an_unresolvable_worktree_relays_the_resolver_refusal(self):
        prefix = b"workflow-state: resolve-project refused at worktree: "
        for label in ("empty directory", "dangling symlink"):
            with self.subTest(label=label):
                self.project()
                if label == "empty directory":
                    Path(self.worktree).mkdir()
                else:
                    Path(self.worktree).symlink_to(self.root / "missing")
                expected = self.resolver_refusal_line(self.worktree, "worktree")
                refused = self.contract_bytes(ok=False)
                self.assertEqual((refused.returncode, refused.stdout, refused.stderr),
                                 (2, b"", expected))
                self.assertEqual(
                    json.loads(refused.stderr.removeprefix(prefix))["error"]["code"],
                    "not_onboarded")

    def test_help_states_the_contract_resolution_root(self):
        self.project()
        text = "".join(self.cli("build-delivery", "--help").stdout.decode().split())
        for clause in (
                "--kind contract resolves project policy with resolve-project at "
                "--repo-root, the ledger repository root, and seals only that policy.",
                "When the input's worktree path already exists, it also resolves there "
                "and refuses if any sealed policy member differs.",
                "when resolve-project refuses, that line ends with the resolver's error "
                "document"):
            with self.subTest(clause=clause[:40]):
                self.assertIn("".join(clause.split()), text)
```

The help check deletes all whitespace from both sides. argparse re-wraps to the
terminal width and can break a word at a hyphen, as in `--repo-` / `root`.

- [ ] **Step 3: Run the tests and watch them fail**

```bash
PYTHONPATH=python python3 -m unittest $T/test_delivery_workflow.py -k WorktreePolicyTest 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
```

Expected: `Ran 4 tests`, with `FAIL:` lines for
`test_a_divergent_sealed_member_refuses`,
`test_an_unresolvable_worktree_relays_the_resolver_refusal` and
`test_help_states_the_contract_resolution_root`. The agreeing test passes here
already. It is the regression floor that the cross-check must keep.

- [ ] **Step 4: Implement the cross-check and the help**

Add this function to `S/workflow-state.py` directly after `resolve_project_policy`:

```python
def check_contract_worktree(runtime: Any, policy: dict[str, Any], worktree: str) -> None:
    """Veto a contract whose existing worktree resolves to different sealed policy (D4).

    ``lexists`` counts a dangling symlink as present, so it fails closed; an
    absent path, such as a reserved candidate, has nothing to compare.
    """
    if not os.path.lexists(worktree):
        return
    worktree_policy = resolve_project_policy(worktree, "worktree")
    try:
        runtime.check_worktree_policy(policy, worktree_policy)
    except Exception as error:
        raise WorkflowError(f"build-delivery refused: {error}") from error
```

In `command_build_delivery`, insert these lines between the existing
`try`/`except` around `runtime.build_delivery` and the
`sys.stdout.buffer.write(...)` line:

```python
    if args.kind == "contract":
        # The builder has validated `worktree` as absolute and normalized (D5).
        check_contract_worktree(runtime, policy, value["worktree"])
```

In `build_parser`, replace the two lines
`build_delivery = subparsers.add_parser("build-delivery")` and
`build_delivery.add_argument("--repo-root", required=True)` with the following.
The text is exact because help is the authoritative root statement (D7), and
Task 4's docs and the test above quote it:

```python
    build_delivery = subparsers.add_parser("build-delivery", description=(
        "Build one sealed delivery value from --input and print it as canonical JSON. "
        "It takes no lock, reads no ledger or clock and writes nothing. "
        "--kind contract resolves project policy with resolve-project at --repo-root, "
        "the ledger repository root, and seals only that policy. When the input's "
        "worktree path already exists, it also resolves there and refuses if any "
        "sealed policy member differs. The other kinds resolve nothing. Every refusal "
        "after argument parsing exits 2 with empty stdout and one stderr line; when "
        "resolve-project refuses, that line ends with the resolver's error document as "
        "one line of canonical JSON."))
    build_delivery.add_argument("--repo-root", required=True, help=(
        "absolute ledger repository root; --kind contract resolves the policy it seals here"))
```

Leave `--kind` and `--input` unchanged.

- [ ] **Step 5: Verify**

```bash
PYTHONPATH=python python3 -m unittest $T/test_delivery_workflow.py -k WorktreePolicyTest 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
PYTHONPATH=python python3 -m unittest $T/test_delivery_workflow.py 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
PYTHONPATH=python python3 -m unittest $T/test_workflow_state.py -k ResolverOutcomeTest 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
grep -c 'os.path.lexists(worktree)' $S/workflow-state.py
```

Expected: `Ran 4 tests` and `OK`, then `OK` for the whole delivery-workflow
file, then `Ran 2 tests` and `OK`, then `1`. The whole-file run includes
`ContractLifecycleTest`. Its builds name an absent worktree and must stay
unchanged. Summarize any failure to its test ids.

- [ ] **Step 6: Commit**

```bash
git add $S/workflow-state.py $T/test_delivery_workflow.py
git commit -m "feat(workflow-state): veto contracts whose existing worktree policy diverges" \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
