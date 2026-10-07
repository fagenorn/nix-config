# Task 2: Issue-3 setup inputs and three setup kinds

**Files:**
- Create: `home/common/agent-skills/evals/setups/issue-3/2026-10-07-issue-3-rename-flag-design.md`
- Create: `home/common/agent-skills/evals/setups/issue-3/2026-10-07-issue-3-rename-flag.md`
- Create: `home/common/agent-skills/evals/setups/issue-3/2026-10-07-issue-3-rename-flag.tasks/task-1.md`
- Create: `home/common/agent-skills/evals/setups/issue-3/implementation.patch`
- Create: `home/common/agent-skills/evals/tests/fixtures/setup-smoke-evals.json`
- Create: `home/common/agent-skills/tests/test_eval_cases.py`
- Modify: `home/common/agent-skills/evals/run-eval.sh` (setup dispatch and assert exports only)
- Modify: `home/common/agent-skills/evals/assert-lib.sh` (header comment only)
- Modify: `home/common/agent-skills/evals/README.md` (Conventions only)
- Modify: `home/common/agent-skills/evals/tests/test-run-eval-tree.sh` (append one section)
- Modify: `justfile` (one unittest path)

**Interfaces:**
- Consumes these pieces of Task 1:
  - from `test-run-eval-tree.sh`: the helpers `scenario` (sets `S`, `COPY`, `STATE` and `RUN_TMP`), `check` and `FAKE_BIN`, and the fake `claude`, which prints a canned result with `input_tokens` 246;
  - the runner's `record_result` row fields `tree`, `tree_rev`, `tree_dirty` and `input_tokens`;
  - `SPEC_DIR` and `PLAN_DIR`, both absolute paths under `$REPO`.
- Produces, for Task 3:
  - setup kinds `shippable-worktree`, `planned-worktree` and `release-ready`, which take no setup parameters;
  - the worktree `$WORK/worktree-issue-3-rename-flag` on branch `worktree-issue-3-rename-flag`, exported as `PRE_WT` by the two worktree kinds;
  - the assert env `BASE_MAIN`, which is local `main`'s SHA after setup and is set for every pipeline case (D15);
  - `test_eval_cases.py`, with the module constants `REPO_ROOT`, `SKILL_ROOTS` and `case_files()`, and the class `EvalCasesTest`.

**Invariants:**
- The setup dispatch stays one closed `case "$SETUP_KIND" in … esac`, containing no nested `case`, whose `*)` arm dies (D7). The test reads its arms from the first `esac` after the `case` line.
- `fixture-repo/` is not modified. Every input comes from `$HERE/setups/issue-3/`.
- The worktree kinds leave local `main` and origin `main` at the initial commit. `shippable-worktree` adds exactly three commits on the branch (spec, plan, implementation) and `planned-worktree` adds two (spec, plan). Both leave the worktree clean.
- `release-ready` tags `v0.1.0`, annotated, on the initial commit. It merges a `feat:` commit, which applies `implementation.patch`, into `main` with `--no-ff`, pushes `main` and `v0.1.0`, deletes the local feature branch, and leaves `main` checked out and clean (D15).
- The setup spec passes `artifact-budget check --kind design-spec`, and the setup plan package passes `--kind implementation-plan`, under `home/common/agent-skills/artifact-budget-policy.json`.

- [ ] **Step 1: Write the failing tests**

Create `home/common/agent-skills/tests/test_eval_cases.py`:

```python
"""Eval case files as data (#293): setup kinds, setup inputs and pipeline cases."""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
EVALS_DIR = REPO_ROOT / "home/common/agent-skills/evals"
RUNNER = EVALS_DIR / "run-eval.sh"
SETUP_INPUTS = EVALS_DIR / "setups/issue-3"
SKILL_ROOTS = (
    REPO_ROOT / "home/common/agent-skills/skills",
    REPO_ROOT / "home/common/claude-code/skills",
)
BUDGET = REPO_ROOT / "home/common/agent-skills/scripts/artifact_budget.py"
POLICY = REPO_ROOT / "home/common/agent-skills/artifact-budget-policy.json"
SETUP_KINDS = {"dirty-worktree", "shippable-worktree", "planned-worktree", "release-ready"}


def case_files():
    return sorted(path for root in SKILL_ROOTS for path in root.glob("*/evals/evals.json"))


def runner_setup_arms():
    text = RUNNER.read_text(encoding="utf-8")
    start = text.index('case "$SETUP_KIND" in')
    block = text[start:text.index("esac", start)]
    arms = set()
    for label in re.findall(r'^\s*([a-z|"*-]+)\)', block, re.M):
        arms.update(alt for alt in label.split("|") if alt not in ('""', "*"))
    return arms


class EvalCasesTest(unittest.TestCase):
    def test_runner_dispatch_arms_are_the_closed_setup_kinds(self):
        self.assertEqual(runner_setup_arms(), SETUP_KINDS)

    def test_every_named_setup_kind_is_a_runner_arm(self):
        arms = runner_setup_arms()
        for path in case_files():
            for case in json.loads(path.read_text(encoding="utf-8"))["evals"]:
                kind = (case.get("setup") or {}).get("kind")
                if kind is not None:
                    with self.subTest(path=str(path.relative_to(REPO_ROOT)), case=case["id"]):
                        self.assertIn(kind, arms)

    def assert_within_budget(self, kind, root):
        done = subprocess.run(
            [sys.executable, str(BUDGET), "check", "--kind", kind, "--root", str(root),
             "--policy", str(POLICY), "--format", "json"],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["status"], "within_budget")

    def test_setup_spec_passes_the_design_spec_budget(self):
        self.assert_within_budget(
            "design-spec", SETUP_INPUTS / "2026-10-07-issue-3-rename-flag-design.md")

    def test_setup_plan_passes_the_implementation_plan_budget(self):
        self.assert_within_budget(
            "implementation-plan", SETUP_INPUTS / "2026-10-07-issue-3-rename-flag.md")

    def test_setup_patch_implements_issue_three_on_the_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "repo"
            shutil.copytree(EVALS_DIR / "fixture-repo", work,
                            ignore=shutil.ignore_patterns("__pycache__"))
            subprocess.run(["git", "init", "-q", str(work)], check=True)
            applied = subprocess.run(
                ["git", "-C", str(work), "apply", str(SETUP_INPUTS / "implementation.patch")],
                capture_output=True, text=True)
            self.assertEqual(applied.returncode, 0, applied.stderr)
            tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-q"],
                                   cwd=work, capture_output=True, text=True, timeout=120)
            self.assertEqual(tests.returncode, 0, tests.stderr)
            probe = str(Path(tmp) / "probe.json")
            cli = [sys.executable, "-m", "tinytask", "--file", probe, "list"]
            self.assertEqual(subprocess.run(cli + ["--include-done"], cwd=work,
                                            capture_output=True).returncode, 0)
            self.assertEqual(subprocess.run(cli + ["--all"], cwd=work,
                                            capture_output=True).returncode, 2)
            for relative in ("tinytask/cli.py", "README.md", "tests/test_cli.py"):
                with self.subTest(file=relative):
                    self.assertNotIn("--all", (work / relative).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
```

Create `home/common/agent-skills/evals/tests/fixtures/setup-smoke-evals.json`. It holds one synthetic skill's cases, and its asserts grade the setup itself:

```json
{
  "skill_name": "setup-smoke",
  "evals": [
    {
      "id": 1, "name": "shippable-worktree-shape", "mode": "pipeline",
      "setup": { "kind": "shippable-worktree" },
      "prompt": "setup smoke", "expected_output": "setup state only",
      "asserts": [
        { "name": "worktree on the issue-3 branch", "shell": "[ \"$PRE_WT\" = \"$WORK/worktree-issue-3-rename-flag\" ] && [ \"$(git -C \"$PRE_WT\" rev-parse --abbrev-ref HEAD)\" = worktree-issue-3-rename-flag ]" },
        { "name": "three clean commits", "shell": "[ \"$(git -C \"$PRE_WT\" rev-list --count main..HEAD)\" -eq 3 ] && [ -z \"$(git -C \"$PRE_WT\" status --porcelain)\" ]" },
        { "name": "spec and plan package in the retained dirs", "shell": "has_file \"$PRE_WT/${SPEC_DIR#\"$REPO\"/}\"/2026-10-07-issue-3-rename-flag-design.md && has_file \"$PRE_WT/${PLAN_DIR#\"$REPO\"/}\"/2026-10-07-issue-3-rename-flag.md && has_file \"$PRE_WT/${PLAN_DIR#\"$REPO\"/}\"/2026-10-07-issue-3-rename-flag.tasks/task-1.md" },
        { "name": "implementation applied and tests pass", "shell": "cd \"$PRE_WT\" && python3 -m unittest discover -q 2>/dev/null && python3 -m tinytask --file \"$WORK/probe.json\" list --include-done >/dev/null && ! python3 -m tinytask --file \"$WORK/probe.json\" list --all 2>/dev/null" },
        { "name": "main unchanged and named by BASE_MAIN", "shell": "[ \"$BASE_MAIN\" = \"$(git -C \"$REPO\" rev-parse main)\" ] && [ \"$BASE_MAIN\" = \"$(git -C \"$ORIGIN\" rev-parse main)\" ] && [ \"$(git -C \"$REPO\" rev-list --count main)\" -eq 1 ]" }
      ]
    },
    {
      "id": 2, "name": "planned-worktree-shape", "mode": "pipeline",
      "setup": { "kind": "planned-worktree" },
      "prompt": "setup smoke", "expected_output": "setup state only",
      "asserts": [
        { "name": "worktree on the issue-3 branch", "shell": "[ \"$PRE_WT\" = \"$WORK/worktree-issue-3-rename-flag\" ] && [ \"$(git -C \"$PRE_WT\" rev-parse --abbrev-ref HEAD)\" = worktree-issue-3-rename-flag ]" },
        { "name": "two clean commits", "shell": "[ \"$(git -C \"$PRE_WT\" rev-list --count main..HEAD)\" -eq 2 ] && [ -z \"$(git -C \"$PRE_WT\" status --porcelain)\" ]" },
        { "name": "spec and plan package in the retained dirs", "shell": "has_file \"$PRE_WT/${SPEC_DIR#\"$REPO\"/}\"/2026-10-07-issue-3-rename-flag-design.md && has_file \"$PRE_WT/${PLAN_DIR#\"$REPO\"/}\"/2026-10-07-issue-3-rename-flag.tasks/task-1.md" },
        { "name": "implementation not applied", "shell": "grep -q -- 'add_argument(.--all' \"$PRE_WT/tinytask/cli.py\"" },
        { "name": "main unchanged and named by BASE_MAIN", "shell": "[ \"$BASE_MAIN\" = \"$(git -C \"$REPO\" rev-parse main)\" ] && [ \"$BASE_MAIN\" = \"$(git -C \"$ORIGIN\" rev-parse main)\" ] && [ \"$(git -C \"$REPO\" rev-list --count main)\" -eq 1 ]" }
      ]
    },
    {
      "id": 3, "name": "release-ready-shape", "mode": "pipeline",
      "setup": { "kind": "release-ready" },
      "prompt": "setup smoke", "expected_output": "setup state only",
      "asserts": [
        { "name": "v0.1.0 annotated on the root commit", "shell": "[ \"$(git -C \"$REPO\" cat-file -t v0.1.0)\" = tag ] && [ \"$(git -C \"$REPO\" rev-parse 'v0.1.0^{commit}')\" = \"$(git -C \"$REPO\" rev-list --max-parents=0 main)\" ]" },
        { "name": "main ends in a --no-ff merge of a feat: commit", "shell": "[ \"$(git -C \"$REPO\" rev-list --merges --count main)\" -eq 1 ] && git -C \"$REPO\" log -1 --format=%s 'main^2' | grep -q '^feat'" },
        { "name": "origin carries main and only v0.1.0", "shell": "[ \"$(git -C \"$ORIGIN\" rev-parse main)\" = \"$BASE_MAIN\" ] && [ \"$(git -C \"$ORIGIN\" tag -l)\" = v0.1.0 ]" },
        { "name": "clean main checkout and no worktree", "shell": "[ -z \"$PRE_WT\" ] && [ \"$WT_COUNT\" -eq 0 ] && [ -z \"$(git -C \"$REPO\" status --porcelain)\" ] && [ \"$(git -C \"$REPO\" rev-parse --abbrev-ref HEAD)\" = main ] && [ -z \"$(git -C \"$REPO\" branch --list 'feat/*')\" ]" }
      ]
    }
  ]
}
```

Append this section to `test-run-eval-tree.sh`, immediately before the line `if [ "$FAILURES" -ne 0 ]; then`:

```bash
# --- setup kinds, smoke-tested in deployed mode (D15, D16) -------------------------
cat >"$FAKE_BIN/resolve-project" <<SHIM
#!/usr/bin/env bash
PYTHONPATH="$TREE/python" exec python3 -P -m agent_tools.resolve_project "\$@"
SHIM
chmod +x "$FAKE_BIN/resolve-project"
row_is_deployed_pass() {
  last_row | jq -e '.verdict == "PASS" and .failed == 0 and .tree == "deployed"
    and .tree_rev == null and .tree_dirty == null and .input_tokens == 246' >/dev/null
}
smoke_tmp_holds_only_its_sandbox() {
  local entry
  for entry in "$RUN_TMP"/* "$RUN_TMP"/.[!.]*; do
    [ -e "$entry" ] || continue
    case "$(basename "$entry")" in
      eval-setup-smoke-"$1".*) ;;
      *) echo "left behind: $entry"; return 1 ;;
    esac
  done
}
for id in 1 2 3; do
  scenario "setup-smoke-$id"
  mkdir -p "$S/skills/setup-smoke/evals"
  cp "$EVALS_SRC/tests/fixtures/setup-smoke-evals.json" "$S/skills/setup-smoke/evals/evals.json"
  env FAKE_STATE="$STATE" TMPDIR="$RUN_TMP" PATH="$FAKE_BIN:$PATH" EVAL_TIMEOUT=120 \
    bash "$COPY/run-eval.sh" setup-smoke "$id" >"$S/log" 2>&1
  status=$?
  check "setup smoke $id: every setup assert passes" test "$status" -eq 0
  check "setup smoke $id: the row is a deployed-mode PASS" row_is_deployed_pass
  check "setup smoke $id: deployed mode makes no temp root" smoke_tmp_holds_only_its_sandbox "$id"
done
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python timeout 600 python3 -m unittest home/common/agent-skills/tests/test_eval_cases.py 2>&1 | tail -n 5`
Expected: `FAILED`. The arms are `{'dirty-worktree'}`, and the setup inputs do not exist.

Run: `timeout 600 bash home/common/agent-skills/evals/tests/test-run-eval-tree.sh 2>&1 | grep -E '^(FAIL|ok) +setup smoke' | head`
Expected: `FAIL  setup smoke 1: every setup assert passes`, because the runner dies with `unknown setup kind: shippable-worktree`.

- [ ] **Step 3: Write the setup inputs**

The inputs describe fixture issue 3 (`fixture-repo/issues/003-mechanical.md`) as finished upstream phases would leave it.

- **`implementation.patch`.** Copy `fixture-repo/` to a scratch dir, run `git init` and commit it, then make these edits there:
  - In `tinytask/cli.py`: `--all` becomes `--include-done`, keeping the help `include done tasks`, and `args.all` becomes `args.include_done`.
  - In `README.md`: the example line becomes `python3 -m tinytask list --include-done`.
  - In `tests/test_cli.py`: `test_list_all_includes_done_tasks` becomes `test_list_include_done_includes_done_tasks`, and it calls `list --include-done`.

  Generate the patch with `git diff` from the scratch root, using paths `a/…` and `b/…`. Add no `--all` test: issue criterion 4 bans the old name anywhere in the repo, committed tests included. Criterion 2 (`--all` is a usage error) is checked from outside the repo, by `test_setup_patch_implements_issue_three_on_the_fixture` here and by the sdd case's assert in Task 3.
- **`2026-10-07-issue-3-rename-flag-design.md`.** A short design spec with `## Problem`, `## Solution`, `## Acceptance criteria` (the issue's four, verbatim) and a `## Decision ledger` table, in the `| ID | Choice | Grounding | Rejected alternative |` shape, with at least one row (for example: no deprecation alias, per the issue's scope).
- **`2026-10-07-issue-3-rename-flag.md`.** A plan root in the writing-plans header shape: Goal, Architecture, Global Constraints, Test seams, and a `## Task index` with exactly one row ending `[task-1.md](2026-10-07-issue-3-rename-flag.tasks/task-1.md)`. Its `## Acceptance map` has rows AC1–AC4, each of kind `code (classified)` because the issue's criteria are untagged, and each owned by `Task 1`.
- **`.tasks/task-1.md`.** One task:
  - it names the three files;
  - it gives the failing test in full: only the renamed test, `test_list_include_done_includes_done_tasks`, exactly as the patch has it. The task adds no test that names the old flag, and says why: criterion 4;
  - its steps follow red → green → commit;
  - its verification lines are `python3 -m unittest discover` → `OK`; then, run from outside the committed tree, `python3 -m tinytask --file "$(mktemp -d)/t.json" list --all; echo "exit=$?"` → `exit=2` (criterion 2); and `git grep -n -- '--all' -- tinytask tests README.md` → no output (criterion 4; the `issues/` fixtures quote the old name and are not the tool's code or docs).

- [ ] **Step 4: Implement the setup kinds and `BASE_MAIN` in `run-eval.sh`**

Add `SETUPS="$HERE/setups"` beside `FIXTURE`. In the `case "$SETUP_KIND" in` block, add two arms after `dirty-worktree)` and before `*)`. Neither arm contains a nested `case`. Every failing git step dies with `setup: <what failed>`.

- `shippable-worktree|planned-worktree)`:
  1. Set `PRE_WT="$WORK/worktree-issue-3-rename-flag"` and run `git -C "$REPO" worktree add -q -b worktree-issue-3-rename-flag "$PRE_WT" origin/main`.
  2. Set `spec_rel=${SPEC_DIR#"$REPO"/}` and `plan_rel=${PLAN_DIR#"$REPO"/}`.
  3. `mkdir -p "$PRE_WT/$spec_rel"`, copy the spec in, then `git -C "$PRE_WT" add -A` and `commit -qm "docs(spec): issue 3 rename-flag design"`.
  4. `mkdir -p "$PRE_WT/$plan_rel"`, copy the plan root and the whole `.tasks/` directory in, then add and `commit -qm "docs(plan): issue 3 rename-flag plan"`.
  5. If `[ "$SETUP_KIND" = shippable-worktree ]`, run `git -C "$PRE_WT" apply "$SETUPS/issue-3/implementation.patch"`, then add and `commit -qm "feat: rename list --all to --include-done (#3)"`.
  6. Echo `setup: <kind> worktree at $PRE_WT`.
- `release-ready)`:
  1. `git -C "$REPO" tag -a v0.1.0 -m "release: v0.1.0" main`, then `git -C "$REPO" switch -q -c feat/include-done`.
  2. Apply the patch, then add and `commit -qm "feat: rename list --all to --include-done"`.
  3. `git -C "$REPO" switch -q main`, then `git -C "$REPO" merge -q --no-ff -m "Merge branch 'feat/include-done'" feat/include-done`.
  4. `git -C "$REPO" branch -q -d feat/include-done`, then `git -C "$REPO" push -q origin main v0.1.0`.
  5. Echo `setup: release-ready main at $(git -C "$REPO" rev-parse --short main)`.

After `esac`, set `BASE_MAIN=$(git -C "$REPO" rev-parse main)` and add `BASE_MAIN` to the `export WORK REPO …` line. Document `BASE_MAIN` in `assert-lib.sh`'s header: "local `main`'s SHA right after the setup hook (the initial commit when there is no setup)". Under the README's Conventions, add one bullet naming the four setup kinds, the committed inputs in `setups/issue-3/`, and the rule that the fixture itself stays unchanged.

Add `home/common/agent-skills/tests/test_eval_cases.py \` to the `agent-workflow-tests` unittest list, directly after `home/common/agent-skills/tests/test_ship_release_contracts.py \`.

- [ ] **Step 5: Verify**

Run: `PYTHONPATH=python timeout 600 python3 -m unittest -v home/common/agent-skills/tests/test_eval_cases.py 2>&1 | tail -n 4`
Expected: `OK`, 5 tests.

Run: `timeout 600 bash home/common/agent-skills/evals/tests/test-run-eval-tree.sh 2>&1 | tail -n 12`
Expected: exit 0, all three `setup smoke` checks `ok` for ids 1–3, and `all checks passed`.

Run: `PYTHONPATH=python timeout 600 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py 2>&1 | tail -n 3`
Expected: `OK`.

Run: `git diff --quiet HEAD -- home/common/agent-skills/evals/fixture-repo && echo unchanged`
Expected: `unchanged`.

- [ ] **Step 6: Commit**

Commit the files listed above with the message `feat(evals): issue-3 setup inputs and three setup kinds (#293)`, using sdd's lifecycle commit rule.
