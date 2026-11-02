# Task 5: The Instruction Budget workflow and the protection payload

Per D2, D10, D14, D20 (and program D5). Measures issue #292 AC4.

**Files:**
- Create: `.github/workflows/instruction-budget.yaml`
- Modify: `.github/branch-protection.json`
- Modify: `.github/workflows/ci.yaml` (the comment above `nix-eval:` only)
- Modify: `justfile` (the `protect-main` summary comment only)
- Modify: `tests/test_branch_protection.py`

**Interfaces:**
- Consumes: the CLI `python3 -m agent_tools.instruction_load check [--base REV] [--raise-label]` from Task 4. Also `test_branch_protection.py`'s existing helpers: `workflow_lines`, `_top_level_block`, `job_blocks`, `job_body`, `job_names`, `trigger_block`, `trigger_branches`, `job_if_expression`, `workflow_permissions`, `job_permission_lines`, `step_blocks`, `payload`, `required_contexts`.
- Produces: the required context `Instruction Budget`, reported by the job key `instruction-budget` in `.github/workflows/instruction-budget.yaml`. Also a protection payload requiring `Nix Eval` and `Instruction Budget` with `strict: true`.

**Invariants:**
- The new job is plain. It has no job-level `if:`, `needs:`, `strategy:`, `uses:` or `continue-on-error:`, and no step-level `if:` (per D10). The existing green-without-work and plain-job pins apply to it unchanged.
- It never reads a token or secret. It reads the label only from the event payload. Permissions are `contents: read`.
- `ci.yaml`'s jobs, triggers and steps are byte-identical. Only the comment block above `nix-eval:` changes.
- Every job `name:` is unique across `.github/workflows/*.yaml`, so a required context maps to exactly one job.
- No step runs `just protect-main` or any other forge write (per D2).

- [ ] **Step 1: Write the failing test**

Rewrite `tests/test_branch_protection.py` as follows. Keep every existing test except the ones replaced here.

1. **Make the helpers path-aware.** Add `WORKFLOWS = REPO_ROOT / ".github" / "workflows"` and `BUDGET_WORKFLOW = WORKFLOWS / "instruction-budget.yaml"`.
   - Give each helper that reads a workflow a trailing parameter `path=WORKFLOW`, threaded down to `workflow_lines(path)`: `workflow_lines`, `_top_level_block`, `job_blocks`, `workflow_permissions`, `job_body`, `job_names`, `trigger_block`, `trigger_branches`, `job_if_expression` and `step_blocks`.
   - Existing callers that pass no path keep reading `ci.yaml`. The two `mock.patch(f"{__name__}.workflow_lines", ...)` tests keep working, because the mock accepts any argument.
   - Update the module docstring and the `WORKFLOW` comment so they say that `ci.yaml` and `instruction-budget.yaml` share one indentation convention.
2. **Refuse a duplicate name in one workflow.** In `job_names(path=WORKFLOW)`, before `names[name] = key`, raise `AssertionError(f"job name {name!r} is defined twice in {path.name}")` when `name` is already in `names`. Without it the map silently keeps the last job, so `required_jobs()` below could never see the duplicate (per D20).
3. **Add the cross-workflow map**, after `job_names`:

```python
def all_workflows():
    return sorted(WORKFLOWS.glob("*.yaml")) + sorted(WORKFLOWS.glob("*.yml"))


def required_jobs():
    """Map each job name in any workflow to its `(workflow path, job key)`.

    A name defined in two workflows is refused: GitHub would report both under the
    one required context, and a passing duplicate could stand in for a failing gate.
    """
    found = {}
    for path in all_workflows():
        for name, key in job_names(path).items():
            if name in found:
                raise AssertionError(f"job name {name!r} is defined in {found[name][0].name} "
                                     f"and {path.name}")
            found[name] = (path, key)
    return found
```

4. **Replace the expected payload**:

```python
EXPECTED_PROTECTION_PAYLOAD = {
    "required_status_checks": {
        "strict": True,
        "checks": [{"context": "Nix Eval", "app_id": 15368},
                   {"context": "Instruction Budget", "app_id": 15368}],
    },
    "enforce_admins": True,
    "required_pull_request_reviews": None,
    "restrictions": None,
}
```

   In `test_payload_carries_every_key_the_api_requires`, change `self.assertIs(False, data["required_status_checks"]["strict"])` to `self.assertIs(True, ...)`. Add the comment `# strict: two PRs that each pass on their own base cannot merge into a breach (program D5).`

5. **Required-context tests over every workflow.** Rewrite these four tests to resolve each context through `required_jobs()` and read its workflow through the returned path: `test_required_jobs_are_not_gated_off_pull_requests`, `test_required_jobs_cannot_report_green_without_evaluating`, `RequiredContexts.test_every_required_context_is_a_job_name` and `RequiredContexts.test_required_jobs_are_plain_jobs`.
   - Use `job_if_expression(key, path)`, `job_blocks(path)[key]` and so on.
   - Keep the assertion messages, naming the job's own workflow file.
   - Keep the allowed `if:` values `(None, "github.event_name != 'schedule'")`.

6. **Replace `test_required_job_still_runs_the_evaluation_it_exists_for`** with:

```python
    def test_each_required_job_still_runs_the_evaluation_it_exists_for(self):
        """Steps that run fine and evaluate nothing are the inverse of green-without-work:
        a `run:` body of `true`, another flake attribute, or a budget call that drops
        its base each leave every other assertion here green."""
        self.assertEqual(["Nix Eval", "Instruction Budget"], required_contexts())
        jobs = required_jobs()
        nix_path, nix_key = jobs["Nix Eval"]
        nix_body = job_body(nix_key, nix_path)
        self.assertRegex(nix_body, NIX_EVAL_COMMAND_RE)
        self.assertIn(EVALUATED_ATTRIBUTE, nix_body)
        budget_path, budget_key = jobs["Instruction Budget"]
        self.assertEqual(BUDGET_WORKFLOW, budget_path)
        budget_body = job_body(budget_key, budget_path)
        self.assertRegex(budget_body, BUDGET_COMMAND_RE)
        self.assertTrue(forwards_budget_args(budget_body), budget_body)
        self.assertIn("--base HEAD^1", budget_body)
        self.assertIn("--raise-label", budget_body)
```

   with these module-level definitions:

```python
BUDGET_COMMAND_RE = re.compile(r"PYTHONPATH=python python3 -m agent_tools\.instruction_load check\b")
BUDGET_INVOCATION = 'PYTHONPATH=python python3 -m agent_tools.instruction_load check "${args[@]}"'


def forwards_budget_args(body):
    """Whether the one budget call is the invocation that forwards `args`.

    Without the forwarding, `--base HEAD^1` and `--raise-label` are still built and
    still in the body, yet the check runs with neither.
    """
    calls = [line.strip() for line in body.splitlines() if BUDGET_COMMAND_RE.search(line)]
    return calls == [BUDGET_INVOCATION]
```

   In the class that holds that test, add the mutation test, in the style of `test_advisory_contract_rejects_step_and_summary_mutations`. The second mutation keeps both flags in the body, which leaves the separate `assertIn` checks green:

```python
    def test_the_budget_forwarding_rejects_mutations(self):
        body = job_body("instruction-budget", BUDGET_WORKFLOW)
        self.assertTrue(forwards_budget_args(body))
        self.assertFalse(forwards_budget_args(body + "\n" + BUDGET_INVOCATION))
        for mutated in ("check", "check --base HEAD^1 --raise-label", 'check "${args[*]}"'):
            with self.subTest(invocation=mutated):
                self.assertFalse(forwards_budget_args(body.replace('check "${args[@]}"', mutated)))
```

7. **Add the new class**, before `class RequiredContexts`:

```python
class BudgetWorkflowShape(unittest.TestCase):
    LABEL_EXPRESSION = ("contains(github.event.pull_request.labels.*.name, "
                        "'instruction-budget-raise')")

    def test_label_events_and_push_are_the_triggers(self):
        block = trigger_block("pull_request", BUDGET_WORKFLOW)
        self.assertIsNotNone(block)
        self.assertEqual(["main"], trigger_branches("pull_request", BUDGET_WORKFLOW))
        self.assertIn("    types: [opened, synchronize, reopened, labeled, unlabeled]", block)
        self.assertEqual(["main"], trigger_branches("push", BUDGET_WORKFLOW))
        for absent in ("schedule", "workflow_dispatch", "pull_request_target"):
            self.assertIsNone(trigger_block(absent, BUDGET_WORKFLOW), absent)
        for trigger in ("pull_request", "push"):
            self.assertFalse([line for line in trigger_block(trigger, BUDGET_WORKFLOW)
                              if line.startswith("    paths")])

    def test_minimum_permissions_and_no_job_override(self):
        self.assertEqual(EXPECTED_WORKFLOW_PERMISSIONS, workflow_permissions(BUDGET_WORKFLOW))
        for key, block in job_blocks(BUDGET_WORKFLOW).items():
            self.assertEqual([], job_permission_lines(block), key)

    def test_full_history_and_a_payload_derived_label(self):
        names = job_names(BUDGET_WORKFLOW)
        self.assertEqual({"Instruction Budget": "instruction-budget"}, names)
        body = job_body("instruction-budget", BUDGET_WORKFLOW)
        self.assertIn("          fetch-depth: 0", body.splitlines())
        self.assertIn(self.LABEL_EXPRESSION, body)
        for forbidden in ("secrets.", "GITHUB_TOKEN", "GH_TOKEN", "gh api", "gh pr"):
            self.assertNotIn(forbidden, body)
```

   Add to `RequiredContexts` the duplicate-name fixtures. Each patches `workflow_lines` with a fake that returns lines by path, in the style of the existing `mock.patch` tests:
   - `test_job_names_refuses_a_name_twice_in_one_workflow`: one workflow whose `jobs:` holds `  a:`/`    name: Twin` and `  b:`/`    name: Twin`. `job_names(path)` raises `AssertionError` matching `defined twice in`.
   - `test_required_jobs_refuses_a_name_in_two_workflows`: also patch `all_workflows` to return two paths, each holding one job named `Twin`. `required_jobs()` raises `AssertionError` matching `defined in a.yaml and b.yaml`.

   `test_job_names_are_extractable` additionally asserts `self.assertIn("Instruction Budget", job_names(BUDGET_WORKFLOW))`.

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest tests/test_branch_protection.py`
Expected: FAIL/ERROR. The payload still has `strict: false` and one check, `instruction-budget.yaml` does not exist, and `required_contexts()` returns `["Nix Eval"]`.

- [ ] **Step 3: Write the minimal implementation**

Create `.github/workflows/instruction-budget.yaml` exactly:

```yaml
# The growth gate (#292, program #291 D5). Required on `main` beside `Nix Eval` once
# `just protect-main` has been applied. It runs `instruction_load check`: skill lint,
# no ceiling breached, every ceiling within 5% of measured, and, on a pull request,
# raise control against the merge commit's first parent. The label is read from the
# event payload, which is why the label event types are listed: without them, adding
# or removing the label would not re-run the check. tests/test_branch_protection.py
# pins this file's shape; run `just agent-workflow-tests` after editing it.
name: Instruction Budget

on:
  pull_request:
    branches:
      - main
    types: [opened, synchronize, reopened, labeled, unlabeled]
  push:
    branches:
      - main

# One run per pull request, superseded by the PR's next event; a push run is keyed
# by event and SHA, after ci.yaml.
concurrency:
  group: instruction-budget-${{ github.event.pull_request.number || format('{0}-{1}', github.event_name, github.sha) }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

permissions:
  contents: read

jobs:
  instruction-budget:
    name: Instruction Budget
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Check the instruction budget
        env:
          EVENT_NAME: ${{ github.event_name }}
          RAISE_LABEL: ${{ github.event_name == 'pull_request' && contains(github.event.pull_request.labels.*.name, 'instruction-budget-raise') }}
        run: |
          set -euo pipefail
          args=()
          if [ "$EVENT_NAME" = pull_request ]; then
            args+=(--base HEAD^1)
            if [ "$RAISE_LABEL" = true ]; then
              args+=(--raise-label)
            fi
          fi
          PYTHONPATH=python python3 -m agent_tools.instruction_load check "${args[@]}"
```

Replace `.github/branch-protection.json` with:

```json
{
  "required_status_checks": {
    "strict": true,
    "checks": [
      {"context": "Nix Eval", "app_id": 15368},
      {"context": "Instruction Budget", "app_id": 15368}
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null
}
```

In `ci.yaml`, change the first two lines of the comment block above `nix-eval:` to say that `Nix Eval` is one of the two contexts `.github/branch-protection.json` requires on `main` (the other is `Instruction Budget`, in `instruction-budget.yaml`) once `just protect-main` has been applied. Keep the rest of the comment.

In `justfile`, change the `protect-main` summary line to `# Apply .github/branch-protection.json to `main`, making `Nix Eval` and `Instruction Budget` required checks.`

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest tests/test_branch_protection.py`
Expected: PASS, every class green.

Run: `git diff --stat HEAD -- .github/workflows/ci.yaml`
Expected: only comment lines change. `git diff -U0 HEAD -- .github/workflows/ci.yaml | grep '^[-+] ' | grep -v '^[-+]  *#'` prints nothing.

Run: `python3 -c "import json;d=json.load(open('.github/branch-protection.json'));assert d['required_status_checks']['strict'] is True;print([c['context'] for c in d['required_status_checks']['checks']])"`
Expected: `['Nix Eval', 'Instruction Budget']`.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/instruction-budget.yaml .github/branch-protection.json .github/workflows/ci.yaml justfile tests/test_branch_protection.py
git commit -m "ci: add the required Instruction Budget check with strict protection (#292)"
```
