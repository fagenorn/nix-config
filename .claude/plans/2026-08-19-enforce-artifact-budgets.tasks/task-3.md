# Task 3: Generate bounded review manifests and whole-file diff shards

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/scripts/review-package`
- Create/Test: `home/common/agent-skills/tests/test_review_package.py`
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md`
- Modify: `home/common/agent-skills/skills/sdd/fix-loop.md`
- Modify: `home/common/agent-skills/skills/sdd/final-review.md`
- Modify: `home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`
- Modify: `home/common/agent-skills/skills/sdd/re-review-prompt.md`
- Modify: `home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md`
- Modify: `home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md`
- Modify: `home/common/claude-code/skills/codex-collaboration/DIFF-REVIEW.md`
- Modify: `home/common/claude-code/skills/codex-collaboration/evals/evals.json`
- Modify/Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Modify: `Justfile`

**Interfaces:**
- Consumes: Task 1's `artifact_budget.load_limits`, `check_artifact`, and `validate_producer_report`; Task 2's validated plan root/workspace; D4, D5, D6, D8, D9, D12, and D13.
- Produces: `review-package PLAN_FILE BASE HEAD [OUTFILE]`, where default root is `<workspace>/review-<base7>..<head7>.json` and members are `<stem>.shards/shard-001.diff`…`shard-NNN.diff`.
- Stdout is one compact report. Success: `{"state":"complete","artifact":{"kind":"review-package","path":...,"metrics":{...},"budget_status":"within_budget"},"notes":...}` and exit 0. Valid oversize: same shape plus `violations`, `state:"decompose_required"`, `budget_status:"over_budget"`, exit 3. Invocation/generation/measurement error: `state:"failed"`, root path when known, no metrics/status, exit 2.

**Invariants:**
- Manifest fields are exactly: `interface_version: 1`; `kind: "review-package"`; `range` with full `base`/`head` SHAs; ordered `commits` entries with exact `sha`/`subject`; `stat` with integer `files_changed`/`insertions`/`deletions`; ordered `shards` entries with relative `path`/actual `bytes`; integer `total_diff_bytes`; `coverage` with `complete: true` and integer `file_diff_count`. Every integer rejects booleans.
- The diff stream is byte-identical to `git diff --no-ext-diff --binary -U10 BASE..HEAD`. Split only before a line beginning `diff --git `; never decode or reorder patch bytes. Greedily append complete file diffs to the current shard while the authoritative member ceiling still fits.
- A complete file diff larger than the member ceiling remains whole in one oversized candidate shard; too many/too-large complete shards remain a complete candidate package. The final checker returns `decompose_required`; no truncation, partial coverage, reviewer dispatch, or success state occurs.
- Build the complete convention-named candidate under a unique sibling staging directory, then run the checker after the manifest's final byte. If final root or member directory already exists in any form, return failed/exit 2 without touching it. For a new path, rename the validated member directory into place and publish the manifest last; if that final rename fails, remove only the newly published member directory. Valid over-budget candidates are published for diagnosis/decomposition. Success/over leaves no staging entry or orphan shard; any refused retry preserves the prior manifest and every shard byte-identically.
- Parse Git `--numstat -z` without decoding path bytes for counts: each binary `-` insertion/deletion value contributes zero while its row contributes one to `files_changed`; text values are strict non-negative decimal integers.
- Task and final review dispatches carry manifest root plus four metrics, not shard lists or diff contents. Unscoped rubrics read the strict manifest then each shard once in manifest order and explicitly report an unreadable/mismatched shard.
- Per D9, the >20-product-file correctness packet carries root/metrics as range-coverage evidence but does not read full-range shards; it fetches only `diff-scope`'s selected literal paths. Conformance and every unscoped review consume all shards.
- Every initial, task-fix, final, and final-fix `review-package` call parses stdout and return code before dispatch: exit 0 plus a validated complete report permits dispatch; exit 3 records/returns `decompose_required` with no reviewer dispatched; exit 2 or any malformed/unknown result records `failed` with no reviewer dispatched.

- [ ] **Step 1: Write failing review-package CLI tests**

Create the test module below. `install_budget_runtime` makes source-tree execution use the same stable paths as deployment; `commit` supplies deterministic Git identities/dates so manifest bytes are repeatable.

```python
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).parents[4]
COMMAND = ROOT / "home/common/agent-skills/skills/sdd/scripts/review-package"
MODULE = ROOT / "home/common/agent-skills/scripts/artifact_budget.py"
POLICY = ROOT / "home/common/agent-skills/artifact-budget-policy.json"


class ReviewPackageCliTest(unittest.TestCase):
    def run_git(self, repo: Path, *args: str, text: bool = True):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True, text=text).stdout

    def setup_repo(self, directory: Path) -> tuple[str, dict[str, str]]:
        self.run_git(directory, "init", "-q")
        self.run_git(directory, "config", "user.name", "Fixture")
        self.run_git(directory, "config", "user.email", "fixture@example.test")
        members = directory / "plan.tasks"
        members.mkdir()
        (members / "task-1.md").write_text("# Task 1: Fixture\n", encoding="utf-8")
        (directory / "plan.md").write_text(
            "# Plan\n\n## Task index\n\n"
            "Task 1 — Fixture — a.txt — full — [task-1.md](plan.tasks/task-1.md)\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        home = directory / "home"
        lib = home / ".agents/lib/python"
        share = home / ".agents/share"
        lib.mkdir(parents=True)
        share.mkdir(parents=True)
        (lib / "artifact_budget.py").symlink_to(MODULE)
        (share / "artifact-budget-policy.json").symlink_to(POLICY)
        env.update({"HOME": str(home), "PYTHONPATH": str(lib),
                    "GIT_AUTHOR_DATE": "2026-08-19T12:00:00Z",
                    "GIT_COMMITTER_DATE": "2026-08-19T12:00:00Z"})
        return str(directory / "plan.md"), env

    def commit(self, repo: Path, message: str) -> str:
        self.run_git(repo, "add", "-A")
        self.run_git(repo, "commit", "-q", "-m", message)
        return self.run_git(repo, "rev-parse", "HEAD").strip()

    def invoke(self, repo: Path, plan: str, base: str, head: str,
               out: Path, env: dict[str, str]):
        return subprocess.run([str(COMMAND), plan, base, head, str(out)], cwd=repo,
                              env=env, text=True, capture_output=True, check=False)

    def test_small_range_has_one_complete_reconstructable_shard(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            plan, env = self.setup_repo(repo)
            (repo / "a.txt").write_text("before\n", encoding="utf-8")
            base = self.commit(repo, "base")
            (repo / "a.txt").write_text("after\n", encoding="utf-8")
            head = self.commit(repo, "change a")
            out = repo / "review.json"
            result = self.invoke(repo, plan, base, head, out, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["state"], "complete")
            self.assertEqual(report["artifact"]["budget_status"], "within_budget")
            manifest = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(set(manifest), {"interface_version", "kind", "range",
                "commits", "stat", "shards", "total_diff_bytes", "coverage"})
            rebuilt = b"".join((out.parent / item["path"]).read_bytes()
                               for item in manifest["shards"])
            expected = subprocess.run(
                ["git", "-C", str(repo), "diff", "--no-ext-diff", "--binary", "-U10",
                 f"{base}..{head}"], check=True, capture_output=True).stdout
            self.assertEqual(rebuilt, expected)
            self.assertEqual(manifest["total_diff_bytes"], len(expected))
            self.assertTrue(manifest["coverage"]["complete"])
            self.assertEqual({path.name for path in out.parent.iterdir() if path.name.startswith("review")},
                             {"review.json", "review.shards"})
            self.assertFalse(any("stage" in path.name for path in out.parent.iterdir()))

    def test_multiple_file_diffs_are_grouped_without_splitting_or_reordering(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            plan, env = self.setup_repo(repo)
            (repo / "a.txt").write_text("a\n", encoding="utf-8")
            (repo / "b.txt").write_text("b\n", encoding="utf-8")
            base = self.commit(repo, "base")
            (repo / "a.txt").write_text("A" * 40_000 + "\n", encoding="utf-8")
            (repo / "b.txt").write_text("B" * 40_000 + "\n", encoding="utf-8")
            head = self.commit(repo, "large separate files")
            out = repo / "review.json"
            result = self.invoke(repo, plan, base, head, out, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["shards"]), 2)
            self.assertTrue(all(item["bytes"] <= 65_536 for item in manifest["shards"]))
            self.assertEqual([item["path"] for item in manifest["shards"]],
                             ["review.shards/shard-001.diff", "review.shards/shard-002.diff"])

    def test_single_oversized_file_is_complete_but_never_successful(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            plan, env = self.setup_repo(repo)
            (repo / "large.txt").write_text("small\n", encoding="utf-8")
            base = self.commit(repo, "base")
            (repo / "large.txt").write_text("X" * 70_000 + "\n", encoding="utf-8")
            head = self.commit(repo, "oversized file")
            out = repo / "review.json"
            result = self.invoke(repo, plan, base, head, out, env)
            self.assertEqual(result.returncode, 3, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["state"], "decompose_required")
            self.assertEqual(report["artifact"]["budget_status"], "over_budget")
            self.assertIn("member_bytes", report["artifact"]["violations"])
            manifest = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(manifest["coverage"]["complete"])
            self.assertGreater(manifest["shards"][0]["bytes"], 65_536)
            self.assertNotIn('"state":"complete"', result.stdout)

    def test_nine_complete_shards_stop_on_member_count_without_losing_coverage(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            plan, env = self.setup_repo(repo)
            for number in range(9):
                (repo / f"f-{number}.txt").write_text("small\n", encoding="utf-8")
            base = self.commit(repo, "base")
            for number in range(9):
                (repo / f"f-{number}.txt").write_text(
                    chr(65 + number) * 33_000 + "\n", encoding="utf-8")
            head = self.commit(repo, "nine large files")
            out = repo / "review.json"
            result = self.invoke(repo, plan, base, head, out, env)
            self.assertEqual(result.returncode, 3, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["state"], "decompose_required")
            self.assertIn("member_count", report["artifact"]["violations"])
            manifest = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["shards"]), 9)
            self.assertEqual(manifest["coverage"]["file_diff_count"], 9)
            rebuilt = b"".join((out.parent / item["path"]).read_bytes()
                               for item in manifest["shards"])
            expected = subprocess.run(
                ["git", "-C", str(repo), "diff", "--no-ext-diff", "--binary", "-U10",
                 f"{base}..{head}"], check=True, capture_output=True).stdout
            self.assertEqual(rebuilt, expected)

    def test_binary_numstat_is_zero_churn_but_diff_bytes_are_covered(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            plan, env = self.setup_repo(repo)
            (repo / "binary.dat").write_bytes(b"\x00before")
            base = self.commit(repo, "base binary")
            (repo / "binary.dat").write_bytes(b"\x00after")
            head = self.commit(repo, "change binary")
            out = repo / "review.json"
            result = self.invoke(repo, plan, base, head, out, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(manifest["stat"],
                             {"files_changed": 1, "insertions": 0, "deletions": 0})
            rebuilt = b"".join((out.parent / item["path"]).read_bytes()
                               for item in manifest["shards"])
            self.assertIn(b"GIT binary patch", rebuilt)

    def test_retry_refuses_existing_valid_package_without_touching_it(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            plan, env = self.setup_repo(repo)
            (repo / "a.txt").write_text("before\n", encoding="utf-8")
            base = self.commit(repo, "base")
            (repo / "a.txt").write_text("after\n", encoding="utf-8")
            head = self.commit(repo, "change")
            out = repo / "review.json"
            first = self.invoke(repo, plan, base, head, out, env)
            self.assertEqual(first.returncode, 0, first.stderr)
            manifest_before = out.read_bytes()
            members_before = {p.name: p.read_bytes() for p in (repo / "review.shards").iterdir()}
            retry = self.invoke(repo, plan, base, head, out, env)
            self.assertEqual(retry.returncode, 2)
            self.assertEqual(json.loads(retry.stdout)["state"], "failed")
            self.assertEqual(out.read_bytes(), manifest_before)
            self.assertEqual({p.name: p.read_bytes() for p in (repo / "review.shards").iterdir()},
                             members_before)
            self.assertFalse(any("stage" in p.name for p in repo.iterdir()))
```

Add `test_review_package.py` to `agent-workflow-tests`.

Add workflow contract assertions that every SDD review path, including `fix-loop.md`, names `manifest`, `root path and all four metrics`, `manifest order`, and explicit unreadable-shard reporting; assert each generator call's exit-2/exit-3 branch occurs before dispatch. Assert the scoped Codex path includes root/metrics, `do not read its shards`, and one literal diff fetch per selected path. Replace the stale eval claim that `scripts/review-package` remains monolithic/untouched with the D9 behavior.

- [ ] **Step 2: Run focused tests and observe the monolithic package fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_review_package.py home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: FAIL because the command currently writes one `.diff`, has no manifest/metrics/state, and reviewer contracts assume one inlined package file.

- [ ] **Step 3: Implement deterministic generation and manifest-aware review contracts**

Rewrite `review-package` as an executable import-safe Python script. Add `~/.agents/lib/python` to `sys.path`, import Task 1's module, validate the plan/root and Git revisions, capture full SHAs/commits/stat, and obtain the `review-package` member ceiling with `load_limits`. Treat binary numstat `-` as D13 zero churn. Capture the binary diff once; find only line-start `diff --git ` boundaries; greedily group complete chunks. Refuse any existing final root/directory untouched. Write convention-named shards and final UTF-8 manifest inside a unique sibling stage, call `check_artifact` there, then publish by renaming members first and manifest last with the cleanup/first-publication rules above. Validate the fixed report before stdout. A module/policy/check/publication failure produces `failed` without invented metrics.

Update SDD's task loop, `fix-loop.md`, and final review so every first-pass and fix-range generator result is parsed and validated before dispatch. For each site: exit 0 dispatches only after report/checker agreement; exit 3 records and returns `decompose_required` without dispatch; exit 2 or malformed/unknown output records and returns `failed` without dispatch. All unscoped reviewer templates read the root JSON, validate its declared coverage/bytes against supplied checker metrics, then read shards once in listed order; delete their missing-package fallback for SDD-produced packages and explicitly report unreadable evidence.

Update `DIFF-REVIEW.md`, its eval, and the correctness prompt per D9: an unscoped correctness axis consumes all shards; a scoped axis is still handed root/metrics but treats them as range coverage only, never reads shards, and fetches exactly the selected files. Conformance always reads the complete package.

- [ ] **Step 4: Verify reconstruction, truthful stops, and all review consumers**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_review_package.py`

Expected: PASS; reconstructed bytes equal Git output, shards are bounded/ordered, binary stats are zero churn, oversized cases stop, existing-package retry preserves bytes, and successful publication leaves no staging/orphan entries.

Run: `just agent-workflow-tests`

Expected: PASS; any monolithic-diff wording, shard-list transport, missing metrics, scoped-axis widening, or unreadable-evidence fallback fails the suite.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd \
  home/common/claude-code/skills/codex-collaboration/DIFF-REVIEW.md \
  home/common/claude-code/skills/codex-collaboration/evals/evals.json \
  home/common/agent-skills/tests/test_review_package.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py Justfile
git commit -m "feat(issue-49): shard review packages" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```
