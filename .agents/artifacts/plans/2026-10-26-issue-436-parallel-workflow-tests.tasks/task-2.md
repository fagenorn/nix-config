# Task 2: The recipe hands its curated members to the runner

Spec § Members and the recipe, per D2–D5. `just agent-workflow-tests` stops running one `python3 -m unittest -v` process followed by a separate `bash` line. Instead it passes its arguments and its member list to `agent_tools.suite_runner`. The eval-tree script becomes the last member, and the runner's own test module joins the list.

**Files:**
- Modify: `justfile` (the `agent-workflow-tests` recipe and the comment line above it)
- Modify: `tests/test_suite_runner.py` (append one test class)

**Interfaces:**
- Consumes: from Task 1, `agent_tools.suite_runner.validate_members(members: Sequence[str], cwd: Path) -> None`, which raises `UsageError` for a refused list. Also `python -m agent_tools.suite_runner [--jobs N] member…`, with exit 2 on a usage error.
- Produces: `just agent-workflow-tests [--jobs N]`. The verification id `agent-workflow-tests` and its argv `just agent-workflow-tests` are unchanged, and so is the CI invocation (D4).

**Invariants:**
- The recipe header is exactly `agent-workflow-tests *args:`. Its first body line is exactly `  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.suite_runner {{args}} \`. Every later body line is one member, indented four spaces, ending ` \` except the last.
- The 102 existing member paths keep their current order and spelling (D3). `tests/test_suite_runner.py` comes right after `tests/test_branch_protection.py`. `home/common/agent-skills/evals/tests/test-run-eval-tree.sh` is the last member. The old trailing line `  bash home/common/agent-skills/evals/tests/test-run-eval-tree.sh` is gone.
- The comment line directly above the recipe is the one `just --list` shows. It names the default cap and serial mode (D5).
- The existing justfile pins stay green: `tests/test_agent_model_drift_scheduling.py::RepositoryWiringTest::test_justfile_wires_new_suite_without_dropping_issue_100_boundaries`, and `home/common/agent-skills/tests/test_delivery_model.py`'s `test_nix_publication_and_managed_test_registration`.

- [ ] **Step 1: Write the failing test**

In `tests/test_suite_runner.py`:
- After the line `from agent_tools.suite_runner import MemberResult`, add a blank line and then these two constants:

```python
REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_TREE_SCRIPT = "home/common/agent-skills/evals/tests/test-run-eval-tree.sh"
```

- Append this class at the end of the module:

```python
class RecipeWiringTest(unittest.TestCase):
    def test_the_recipe_hands_its_curated_members_to_the_runner(self):
        lines = (REPO_ROOT / "justfile").read_text(encoding="utf-8").splitlines()
        start = lines.index("agent-workflow-tests *args:")
        body = []
        for line in lines[start + 1:]:
            if not line.startswith("  "):
                break
            body.append(line)
        self.assertEqual(
            body[0],
            '  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.suite_runner {{args}} \\')
        self.assertTrue(all(line.endswith(" \\") for line in body[:-1]), body)
        self.assertFalse(body[-1].endswith("\\"), body[-1])
        members = [line.strip().removesuffix(" \\") for line in body[1:]]
        self.assertTrue(all(line.startswith("    ") for line in body[1:]), body)
        self.assertEqual(members[-1], EVAL_TREE_SCRIPT)
        self.assertIn("tests/test_suite_runner.py", members)
        suite_runner.validate_members(members, REPO_ROOT)
```

- [ ] **Step 2: Run the test and watch it fail**

Run the focused form (Global Constraints) on `tests/test_suite_runner.py -k RecipeWiringTest`.
Expected: FAIL with one `ERROR`: `ValueError: 'agent-workflow-tests *args:' is not in list`, because the header at base is `agent-workflow-tests:`.

- [ ] **Step 3: Write the minimal implementation**

In `justfile`, make three edits:
1. Replace the comment line `# Verify durable workflow lifecycle and skill contracts without agent/network timing.` with:
   `# Verify durable workflow lifecycle and skill contracts, 4 test files at a time (--jobs N sets the cap; --jobs 1 runs them serially with live output).`
2. Replace the header `agent-workflow-tests:` with `agent-workflow-tests *args:`, and the first body line `  PYTHONPATH="{{agent_tools_path}}" python3 -m unittest -v \` with `  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.suite_runner {{args}} \`.
3. Change the end of the member list from:

```just
    tests/test_branch_protection.py
  bash home/common/agent-skills/evals/tests/test-run-eval-tree.sh
```

to:

```just
    tests/test_branch_protection.py \
    tests/test_suite_runner.py \
    home/common/agent-skills/evals/tests/test-run-eval-tree.sh
```

Change no other member line.

- [ ] **Step 4: Verify**

Run the focused form on `tests/test_suite_runner.py tests/test_agent_model_drift_scheduling.py`, then on `home/common/agent-skills/tests/test_delivery_model.py -k test_nix_publication_and_managed_test_registration`.
Expected: both `OK`. The first is 15 runner tests plus the drift-scheduling module.

Run `bash -c 'just agent-workflow-tests --jobs 0; echo "exit=$?"' 2>&1 | tail -3`.
Expected, in order: an `agent-workflow-tests: error: argument --jobs: …` line; `just`'s `error: Recipe \`agent-workflow-tests\` failed … with exit code 2`; and `exit=2`. No `suite-runner: start` line appears.

Run `bash -c 'diff <(git show 9d2abb3f:justfile | sed -n "/^agent-workflow-tests:/,/^$/p" | grep -E "^    " | sed "s/ \\\\$//") <(sed -n "/^agent-workflow-tests \*args:/,/^$/p" justfile | grep -E "^    " | sed "s/ \\\\$//")'`.
Expected: only `> tests/test_suite_runner.py` and `> home/common/agent-skills/evals/tests/test-run-eval-tree.sh` are added. No base member line is removed or reordered.

Run `just --list 2>/dev/null | grep 'agent-workflow-tests'`.
Expected: one line that shows `*args` and the new comment.

- [ ] **Step 5: Commit**

```bash
git add justfile tests/test_suite_runner.py
launch-commit … -- -m "feat(issue-436): run agent-workflow-tests through the suite runner" -m "<session trailers>"
```

Verify: `git status --short` prints nothing.
