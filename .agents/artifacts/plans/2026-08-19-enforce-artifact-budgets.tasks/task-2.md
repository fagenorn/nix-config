# Task 2: Produce and consume indexed implementation-plan packages

**Files:**
- Modify: `home/common/agent-skills/skills/writing-plans/SKILL.md`
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md`
- Modify: `home/common/agent-skills/skills/sdd/scripts/task-brief`
- Modify: `home/common/agent-skills/skills/from-issue/REVIEW-CONTRACT.md`
- Modify: `home/common/claude-code/skills/codex-collaboration/PLAN-REVIEW.md`
- Create/Test: `home/common/agent-skills/tests/test_task_brief.py`
- Modify/Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Modify: `Justfile`

**Interfaces:**
- Consumes: Task 1's executable `artifact-budget` wrapper, installed/source module, fixed implementation-plan result, and `validate-report` wire seam; D3, D5, D6, D8, D11, and D14.
- Produces: root `<planDir>/<stem>.md`; members `<planDir>/<stem>.tasks/task-1.md` through `task-N.md`; one Task-index row per member ending exactly in `[task-N.md](<stem>.tasks/task-N.md)`; `task-brief PLAN_FILE N [OUTFILE]` that validates the package and copies only the indexed member into the brief.
- The planning report has exactly `state`, one `artifact` object, and policy-bounded `notes`. The artifact root replaces `plan_path`; `open_items` is removed, with unresolved blocking state expressed by `state` and bounded notes pointing to the plan/spec. Over-budget adds the closed `violations` array inside `artifact`.

**Invariants:**
- The root contains goal, architecture, technology, Global Constraints, Test seams, Task index, decision-ID citations, and task-member links; it contains no numbered task bodies or copied ledger rationale.
- Every member is self-contained for one implementer: exact files, consumed/produced interfaces, task-specific invariants, complete failing tests, implementation actions, at least one falsifiable gate, and commit scope. It does not duplicate global constraints or decision rationale.
- Planning measures after writing root and all members. First over-budget remediation compacts repeated prose into root/spec references; second remediation splits only an independently testable task. Persisting root/member/count/aggregate violations return `decompose_required`, and `state: complete` is forbidden.
- `task-brief` fails before writing its output when the checker exits 2/3, when task N has no exact indexed link, or when its resolved link is not the convention path. Its output is byte-identical to that member and contains no other task.
- SDD validates the complete plan package once at setup, retains the root header plus its four checker metrics, and passes the root path/metrics plus the current brief path to implementers and reviewers. A missing/unreadable member is a contract failure, never a fallback to monolithic parsing.
- Phase-5 plan review validates the package first and reads root plus every member from discovery order. Review findings identify the member task or root section; accepted edits remeasure the complete plan.
- Planning and its callers validate the exact D11 report object; legacy `open_items`, `decisions`, `adr_paths`, or `summary` fields are contract errors.
- Planning writes its final report object to a sibling temporary UTF-8 JSON file, runs `artifact-budget validate-report --boundary producer --input <temp>`, deletes the candidate, and returns only the exact validated stdout bytes. Phase 5/from-issue validate those received bytes again through stdin before reading state or advancing.

- [ ] **Step 1: Write failing task-brief and plan-contract tests**

Create this CLI test module; helper methods shown here are part of the test and must be implemented exactly as used:

```python
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).parents[4]
TASK_BRIEF = ROOT / "home/common/agent-skills/skills/sdd/scripts/task-brief"
BUDGET = ROOT / "home/common/agent-skills/scripts/artifact_budget.py"
WRAPPER = ROOT / "home/common/agent-skills/scripts/artifact-budget"
POLICY = ROOT / "home/common/agent-skills/artifact-budget-policy.json"


class TaskBriefPackageTest(unittest.TestCase):
    def make_repo(self, directory: Path) -> tuple[Path, dict[str, str]]:
        subprocess.run(["git", "init", "-q", str(directory)], check=True)
        bin_dir = directory / "bin"
        bin_dir.mkdir()
        (bin_dir / "artifact-budget").symlink_to(WRAPPER)
        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        home = directory / "home"
        policy_dir = home / ".agents/share"
        policy_dir.mkdir(parents=True)
        (policy_dir / "artifact-budget-policy.json").symlink_to(POLICY)
        module_dir = home / ".agents/lib/python"
        module_dir.mkdir(parents=True)
        (module_dir / "artifact_budget.py").symlink_to(BUDGET)
        env["HOME"] = str(home)
        return directory / "plan.md", env

    def write_package(self, root: Path) -> tuple[bytes, bytes]:
        members = root.with_suffix("").with_name(root.stem + ".tasks")
        members.mkdir()
        first = b"# Task 1: First\n\nfirst-only\n"
        second = b"# Task 2: Second\n\nsecond-only\n"
        (members / "task-1.md").write_bytes(first)
        (members / "task-2.md").write_bytes(second)
        root.write_text(
            "# Plan\n\n## Task index\n\n"
            "Task 1 — First — a.py — full — [task-1.md](plan.tasks/task-1.md)\n\n"
            "Task 2 — Second — b.py — full — [task-2.md](plan.tasks/task-2.md)\n",
            encoding="utf-8",
        )
        return first, second

    def test_copies_only_the_exact_indexed_member(self):
        with tempfile.TemporaryDirectory() as raw:
            root, env = self.make_repo(Path(raw))
            first, second = self.write_package(root)
            out = Path(raw) / "brief.md"
            result = subprocess.run(
                [str(TASK_BRIEF), str(root), "2", str(out)], env=env,
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(out.read_bytes(), second)
            self.assertNotIn(first, out.read_bytes())

    def test_missing_or_nonconventional_link_fails_without_output(self):
        with tempfile.TemporaryDirectory() as raw:
            root, env = self.make_repo(Path(raw))
            self.write_package(root)
            root.write_text(root.read_text(encoding="utf-8").replace(
                "plan.tasks/task-2.md", "elsewhere/task-2.md"), encoding="utf-8")
            out = Path(raw) / "brief.md"
            result = subprocess.run(
                [str(TASK_BRIEF), str(root), "2", str(out)], env=env,
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertFalse(out.exists())

    def test_over_budget_package_fails_before_replacing_existing_brief(self):
        with tempfile.TemporaryDirectory() as raw:
            root, env = self.make_repo(Path(raw))
            self.write_package(root)
            root.write_bytes(root.read_bytes() + b"x" * 16_384)
            out = Path(raw) / "brief.md"
            out.write_bytes(b"valid-old-brief")
            result = subprocess.run(
                [str(TASK_BRIEF), str(root), "1", str(out)], env=env,
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 3)
            self.assertEqual(out.read_bytes(), b"valid-old-brief")
            self.assertNotIn("Permission denied", result.stderr)
```

Add workflow contract tests with these exact assertions, using the test module's existing loaded `writing-plans`, SDD, Phase-5 review-contract, and Codex plan-review texts:

```python
def test_plan_package_contract_is_root_only_and_fail_closed(self):
    self.assertIn("<stem>.tasks/task-1.md", self.writing_plans)
    self.assertIn("[task-N.md](<stem>.tasks/task-N.md)", self.writing_plans)
    self.assert_ordered(self.writing_plans, "write every task member", "artifact-budget check",
                        "compact repeated prose", "split only where both results are independently testable",
                        "decompose_required")
    self.assertIn("report only the root path and four metrics", self.writing_plans)
    for forbidden in ("open_items:", "decisions:", "adr_paths:", "summary:"):
        self.assertNotRegex(self.writing_plans, rf"(?m)^\s*{re.escape(forbidden)}")
    self.assert_ordered(self.writing_plans, "candidate JSON", "validate-report",
                        "validated stdout bytes")

def test_sdd_validates_plan_before_extracting_a_member(self):
    setup = self.section(self.sdd, "## Setup", "## Agent tiers")
    self.assert_ordered(setup, "artifact-budget check", "read the root and every indexed member")
    self.assertIn("scripts/task-brief PLAN_FILE N", self.sdd)
    self.assertIn("root path and all four metrics", self.sdd)
    self.assertIn("missing or unreadable member is a contract error", self.sdd)
```

Expose the relevant files as class attributes if the current test setup does not already load them. Add `test_task_brief.py` to the `agent-workflow-tests` recipe.

- [ ] **Step 2: Run focused tests and confirm monolithic-plan assumptions fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_task_brief.py home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: FAIL because `task-brief` still extracts headings from one monolithic plan and the producer/reviewer contracts do not require package validation or root metrics.

- [ ] **Step 3: Implement the package producer, reader, and plan-review contracts**

Rewrite `writing-plans` so the root header shape remains the current plan header but numbered tasks live only in the sibling directory. State the exact link suffix from D8, contiguous numbering, max eight members, final measurement order, two remediation states, and exact D14 producer JSON report with no producer-specific fields. After the last measurement, write a sibling temporary candidate JSON, invoke `validate-report --boundary producer`, clean the candidate, and return only validated stdout; exit 2 is `failed`, never a prose fallback. Preserve its existing test-first, no-placeholder, gate-scoping, lane, and self-review requirements. Its self-review checks root/member reference equality, per-member completeness, and both root/spec remeasurement when it appended a ledger row.

Change `task-brief` to validate arguments and task number, run `artifact-budget check --kind implementation-plan --root "$plan" --format json`, propagate exit 2/3, parse the exact Task-index link for N without accepting arbitrary Markdown, then copy through a sibling temporary file and atomic rename so an existing valid brief survives failure. Reject multiple links for N. Preserve default workspace naming.

In SDD setup, run the checker before initial plan validation, reject non-`within_budget`/missing metrics, and read root plus all task members exactly once for conflict scanning. Thereafter retain only root header/index/metrics and current task brief. Include root path, four metrics, and brief path—never members or contents—in task/reviewer dispatch context.

Update both plan-review routes so the reviewer runs the checker, reads the root and every discovered member, and reports unreadable members. The review packet still supplies only the plan root and metrics. Phase 5 validates the received report JSON through `validate-report --boundary producer --input -` before use. Accepted Phase-5 edits are incomplete until the orchestrator rechecks plan and any amended spec after the last write.

- [ ] **Step 4: Verify the executable adapter and workflow contract**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_task_brief.py`

Expected: PASS; exact member bytes are copied, malformed/over-budget packages fail, and an old brief survives.

Run: `just agent-workflow-tests`

Expected: PASS; a missing package validation, member-list report, or stale Phase-5 measurement fails the suite.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/writing-plans/SKILL.md \
  home/common/agent-skills/skills/sdd/SKILL.md \
  home/common/agent-skills/skills/sdd/scripts/task-brief \
  home/common/agent-skills/skills/from-issue/REVIEW-CONTRACT.md \
  home/common/claude-code/skills/codex-collaboration/PLAN-REVIEW.md \
  home/common/agent-skills/tests/test_task_brief.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py Justfile
git commit -m "feat(issue-49): package implementation plans" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```
