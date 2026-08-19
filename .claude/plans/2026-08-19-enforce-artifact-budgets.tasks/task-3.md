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
- Consumes: Task 1's `artifact_budget.load_limits`, `check_artifact`, and canonical `validate-report` CLI; Task 2's validated plan root/workspace; D4, D5, D6, D8, D9, and D12–D16.
- Produces: diff mode `review-package PLAN_FILE BASE HEAD [OUTFILE]`, where default root is `<workspace>/review-<base7>..<head7>.json`; delivery-detail mode `review-package --detail-input <findings.json> --producer <sdd|ship-review> --issue <positive-int> --branch <branch> --run-id <safe-id|-> --head <sha> [--output <asserted-derived-path>]`. Detail mode independently derives the primary checkout and exact final root; `--output` is only an equality assertion, never destination authority. Both roots use `<stem>.shards/`; diff members end `.diff`, detail members `.jsonl`.
- Stdout is one compact report. Success: `{"state":"complete","artifact":{"kind":"review-package","path":...,"metrics":{...},"budget_status":"within_budget"},"notes":...}` and exit 0. Valid oversize: same shape plus `violations`, `state:"decompose_required"`, `budget_status:"over_budget"`, exit 3. Invocation/generation/measurement error: `state:"failed"`, root path when known, no metrics/status, exit 2.

**Invariants:**
- Diff manifest fields are exactly: `interface_version: 1`; `kind: "review-package"`; `purpose: "diff-review"`; `range` with full `base`/`head` SHAs; ordered exact commits/stat/shards; integer `total_diff_bytes`; complete file coverage. Delivery-detail input is exactly `{"interface_version":1,"findings":[...]}`; its manifest uses D15's exact context/shards/`total_detail_bytes`/finding coverage schema and one canonical exact-field JSON finding per line. Every integer rejects booleans.
- The diff stream is byte-identical to `git diff --no-ext-diff --binary -U10 BASE..HEAD`. Split only before a line beginning `diff --git `; never decode or reorder patch bytes. Greedily append complete file diffs to the current shard while the authoritative member ceiling still fits.
- A complete file diff larger than the member ceiling remains whole in one oversized candidate shard; too many/too-large complete shards remain a complete candidate package. The final checker returns `decompose_required`; no truncation, partial coverage, reviewer dispatch, or success state occurs.
- Build the complete convention-named candidate under a unique sibling staging directory and check it after the manifest's final byte. Publication never relies on a precheck: `publish_package(stage_root, final_root, before_mutation: Callable[[str, Path], None] | None = None)` exclusively creates the final member directory, exclusively hard-links each staged member, then exclusively hard-links the manifest last. Any collision/cross-device error fails without replacement. Cleanup unlinks only this invocation's `(st_dev, st_ino)`-matching entries and removes its directory only when empty and still at its recorded post-`mkdir` identity. The callback is an import-level deterministic test seam called before `member_dir`, every `member:<name>`, and `manifest` mutation; production passes `None`.
- Parse Git `--numstat -z` without decoding path bytes for counts: each binary `-` insertion/deletion value contributes zero while its row contributes one to `files_changed`; text values are strict non-negative decimal integers.
- Task and final review dispatches carry manifest root plus four metrics, not shard lists or diff contents. Unscoped rubrics read the strict manifest then each shard once in manifest order and explicitly report an unreadable/mismatched shard.
- Per D9, the >20-product-file correctness packet carries root/metrics as range-coverage evidence but does not read full-range shards; it fetches only `diff-scope`'s selected literal paths. Conformance and every unscoped review consume all shards.
- Every initial, task-fix, final, and final-fix `review-package` call parses stdout and return code before dispatch: exit 0 plus a validated complete report permits dispatch; exit 3 records/returns `decompose_required` with no reviewer dispatched; exit 2 or any malformed/unknown result records `failed` with no reviewer dispatched.
- Every generator report is written as candidate JSON and sent through `artifact-budget validate-report --boundary producer`; only validated stdout is emitted. Every caller validates received bytes through the same CLI stdin seam before branch/dispatch logic.
- Fixture commit helpers pass the fixed author/committer-date environment on every `git commit`; constructing the same range twice in fresh repositories produces byte-identical canonical manifests and shards.
- Detail mode resolves absolute `git rev-parse --git-common-dir`, requires its basename to be `.git`, takes its parent, and confirms that exact directory with `git -C <parent> rev-parse --show-toplevel`. It derives `<main>/.superpowers/issue-delivery/<issue>/<identity>/<producer>-<head>.json`, where identity is a validated run id or `branch-` plus the lowercase SHA-256 of the UTF-8 branch. Issue, producer, full lowercase head SHA, checked-out branch, and run id are strict; traversal, symlink parents, `.git`, outside-root, feature-worktree, malformed identity, and a non-equal `--output` fail before publication.
- Before detail publication, create or validate `.superpowers/issue-delivery/.gitignore` as a no-follow regular file containing exactly `*\n`. Exclusive create uses `O_CREAT|O_EXCL|O_WRONLY` and `O_NOFOLLOW` where available; an existing entry must be non-symlink, regular, and byte-exact. Then create descendants with the same no-follow/fail-closed discipline. A repository without a broad local exclude must report every generated package member as ignored.

- [ ] **Step 1: Write failing review-package CLI tests**

Create the test module below. `install_budget_runtime` makes source-tree execution use the same stable paths as deployment; `commit` supplies deterministic Git identities/dates so manifest bytes are repeatable.

```python
from __future__ import annotations

import json
from importlib.machinery import SourceFileLoader
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest


ROOT = Path(__file__).parents[4]
COMMAND = ROOT / "home/common/agent-skills/skills/sdd/scripts/review-package"
MODULE = ROOT / "home/common/agent-skills/scripts/artifact_budget.py"
POLICY = ROOT / "home/common/agent-skills/artifact-budget-policy.json"
sys.path.insert(0, str(MODULE.parent))
review_package_module = types.ModuleType("review_package")
SourceFileLoader("review_package", str(COMMAND)).exec_module(review_package_module)


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

    def setup_linked_repo(self, directory: Path):
        main = directory / "main"
        linked = directory / "linked"
        main.mkdir()
        plan, env = self.setup_repo(main)
        (main / "seed.txt").write_text("seed\n", encoding="utf-8")
        head = self.commit(main, "seed", env)
        self.run_git(main, "worktree", "add", "-q", "-b", "issue-49", str(linked))
        (main / ".git/info/exclude").write_text("", encoding="utf-8")
        return main, linked, str(linked / Path(plan).name), env, head

    def commit(self, repo: Path, message: str, env: dict[str, str]) -> str:
        subprocess.run(["git", "-C", str(repo), "add", "-A"], env=env, check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", message],
                       env=env, check=True)
        return self.run_git(repo, "rev-parse", "HEAD").strip()

    def invoke(self, repo: Path, plan: str, base: str, head: str,
               out: Path, env: dict[str, str]):
        return subprocess.run([str(COMMAND), plan, base, head, str(out)], cwd=repo,
                              env=env, text=True, capture_output=True, check=False)

    def invoke_detail(self, repo: Path, source: Path, env: dict[str, str],
                      *, run_id: str = "run-1", branch: str = "issue-49",
                      head: str, output: Path | str | None = None):
        argv = [
            str(COMMAND), "--detail-input", str(source), "--producer", "sdd",
             "--issue", "49", "--branch", branch, "--run-id", run_id,
             "--head", head]
        if output is not None:
            argv += ["--output", str(output)]
        return subprocess.run(argv, cwd=repo, env=env, text=True,
                              capture_output=True, check=False)

    def test_small_range_has_one_complete_reconstructable_shard(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            plan, env = self.setup_repo(repo)
            (repo / "a.txt").write_text("before\n", encoding="utf-8")
            base = self.commit(repo, "base", env)
            (repo / "a.txt").write_text("after\n", encoding="utf-8")
            head = self.commit(repo, "change a", env)
            out = repo / "review.json"
            result = self.invoke(repo, plan, base, head, out, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["state"], "complete")
            self.assertEqual(report["artifact"]["budget_status"], "within_budget")
            manifest = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(manifest["purpose"], "diff-review")
            self.assertEqual(set(manifest), {"interface_version", "kind", "purpose", "range",
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
            base = self.commit(repo, "base", env)
            (repo / "a.txt").write_text("A" * 40_000 + "\n", encoding="utf-8")
            (repo / "b.txt").write_text("B" * 40_000 + "\n", encoding="utf-8")
            head = self.commit(repo, "large separate files", env)
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
            base = self.commit(repo, "base", env)
            (repo / "large.txt").write_text("X" * 70_000 + "\n", encoding="utf-8")
            head = self.commit(repo, "oversized file", env)
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
            base = self.commit(repo, "base", env)
            for number in range(9):
                (repo / f"f-{number}.txt").write_text(
                    chr(65 + number) * 33_000 + "\n", encoding="utf-8")
            head = self.commit(repo, "nine large files", env)
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
            base = self.commit(repo, "base binary", env)
            (repo / "binary.dat").write_bytes(b"\x00after")
            head = self.commit(repo, "change binary", env)
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
            base = self.commit(repo, "base", env)
            (repo / "a.txt").write_text("after\n", encoding="utf-8")
            head = self.commit(repo, "change", env)
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

    def test_delivery_detail_uses_the_shared_review_budget_and_canonical_findings(self):
        with tempfile.TemporaryDirectory() as raw:
            main, linked, _, env, head = self.setup_linked_repo(Path(raw))
            findings = [
                {"axis": "correctness", "severity": "Minor", "status": "parked",
                 "text": "Keep this evidence", "ruling": "accepted for follow-up"},
                {"axis": "conformance", "severity": "Discussion", "status": "residual",
                 "text": "Explain this tradeoff", "ruling": None},
            ]
            source = linked / "findings.json"
            source.write_text(json.dumps({"interface_version": 1, "findings": findings}),
                              encoding="utf-8")
            out = main / ".superpowers/issue-delivery/49/run-1" / f"sdd-{head}.json"
            result = self.invoke_detail(linked, source, env, head=head, output=out)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["artifact"]["path"], out.relative_to(main).as_posix())
            ignore_file = main / ".superpowers/issue-delivery/.gitignore"
            self.assertEqual(ignore_file.read_bytes(), b"*\n")
            ignored_root = self.run_git(main, "check-ignore", "-v",
                                        out.relative_to(main).as_posix())
            self.assertIn(ignore_file.relative_to(main).as_posix(), ignored_root)
            member = out.with_suffix(".shards") / "shard-001.jsonl"
            ignored_member = self.run_git(main, "check-ignore", "-v",
                                          member.relative_to(main).as_posix())
            self.assertIn(ignore_file.relative_to(main).as_posix(), ignored_member)
            self.run_git(main, "worktree", "remove", "--force", str(linked))
            manifest = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(manifest["purpose"], "delivery-detail")
            self.assertEqual(manifest["context"],
                             {"issue": 49, "branch": "issue-49", "producer": "sdd"})
            rebuilt = b"".join((out.parent / item["path"]).read_bytes()
                               for item in manifest["shards"])
            decoded = [json.loads(line) for line in rebuilt.splitlines()]
            self.assertEqual(decoded, findings)
            self.assertEqual(manifest["coverage"],
                             {"complete": True, "finding_count": len(findings)})
            self.assertEqual(json.loads(result.stdout)["artifact"]["budget_status"],
                             "within_budget")

    def test_detail_mode_rejects_untrusted_destinations_and_identity(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            main, linked, _, env, head = self.setup_linked_repo(directory)
            source = linked / "findings.json"
            source.write_text(json.dumps({"interface_version": 1, "findings": []}),
                              encoding="utf-8")
            expected = main / ".superpowers/issue-delivery/49/run-1" / f"sdd-{head}.json"
            bad_outputs = [
                linked / ".superpowers/issue-delivery/49/run-1" / f"sdd-{head}.json",
                directory / "outside.json", main / ".git/delivery.json",
                str(expected.parent / ".." / "escape.json"),
            ]
            for output in bad_outputs:
                with self.subTest(output=output):
                    result = self.invoke_detail(linked, source, env, head=head, output=output)
                    self.assertEqual((result.returncode, result.stdout), (2, ""))
            for run_id, branch in (("../bad", "issue-49"), ("run-1", "../bad"),
                                   ("run-1", "main")):
                with self.subTest(run_id=run_id, branch=branch):
                    result = self.invoke_detail(linked, source, env, head=head,
                                                run_id=run_id, branch=branch)
                    self.assertEqual((result.returncode, result.stdout), (2, ""))

    def test_detail_mode_rejects_a_symlink_parent(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            main, linked, _, env, head = self.setup_linked_repo(directory)
            source = linked / "findings.json"
            source.write_text(json.dumps({"interface_version": 1, "findings": []}),
                              encoding="utf-8")
            home = main / ".superpowers/issue-delivery"
            home.mkdir(parents=True)
            (home / ".gitignore").write_text("*\n", encoding="utf-8")
            outside = directory / "outside"
            outside.mkdir()
            (home / "49").symlink_to(outside, target_is_directory=True)
            result = self.invoke_detail(linked, source, env, head=head)
            self.assertEqual((result.returncode, result.stdout), (2, ""))

    def test_detail_mode_rejects_a_symlink_ignore_file(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            main, linked, _, env, head = self.setup_linked_repo(directory)
            source = linked / "findings.json"
            source.write_text(json.dumps({"interface_version": 1, "findings": []}),
                              encoding="utf-8")
            home = main / ".superpowers/issue-delivery"
            home.mkdir(parents=True)
            target = directory / "outside-ignore"
            target.write_text("*\n", encoding="utf-8")
            (home / ".gitignore").symlink_to(target)
            result = self.invoke_detail(linked, source, env, head=head)
            self.assertEqual((result.returncode, result.stdout), (2, ""))

    def test_publication_races_never_replace_a_competitor(self):
        for boundary in ("member_dir", "member:shard-001.diff",
                         "member:shard-002.diff", "manifest"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as raw:
                directory = Path(raw)
                stage = directory / "stage"
                stage_members = stage / "review.shards"
                stage_members.mkdir(parents=True)
                stage_root = stage / "review.json"
                stage_root.write_bytes(b"staged-manifest")
                (stage_members / "shard-001.diff").write_bytes(b"staged-shard")
                (stage_members / "shard-002.diff").write_bytes(b"staged-shard-two")
                final_root = directory / "review.json"
                competitor = b"competitor-bytes"
                competed_path = None

                def inject(label: str, path: Path):
                    nonlocal competed_path
                    if label != boundary:
                        return
                    if label == "member_dir":
                        path.mkdir()
                        competed_path = path / "competitor"
                    else:
                        competed_path = path
                    competed_path.write_bytes(competitor)

                with self.assertRaises(review_package_module.PublicationError):
                    review_package_module.publish_package(stage_root, final_root, inject)
                self.assertIsNotNone(competed_path)
                self.assertEqual(competed_path.read_bytes(), competitor)
                final_members = directory / "review.shards"
                if boundary == "manifest":
                    self.assertFalse(final_members.exists())
                else:
                    self.assertEqual({p.name for p in final_members.iterdir()},
                                     {competed_path.name})

    def test_fixed_commit_environment_makes_two_packages_byte_identical(self):
        snapshots = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as raw:
                repo = Path(raw)
                plan, env = self.setup_repo(repo)
                (repo / "a.txt").write_text("before\n", encoding="utf-8")
                base = self.commit(repo, "base", env)
                (repo / "a.txt").write_text("after\n", encoding="utf-8")
                head = self.commit(repo, "change", env)
                out = repo / "review.json"
                result = self.invoke(repo, plan, base, head, out, env)
                self.assertEqual(result.returncode, 0, result.stderr)
                snapshots.append((out.read_bytes(),
                    [(p.name, p.read_bytes()) for p in sorted((repo / "review.shards").iterdir())]))
        self.assertEqual(snapshots[0], snapshots[1])
```

Add `test_review_package.py` to `agent-workflow-tests`.

Add workflow contract assertions that every SDD review path, including `fix-loop.md`, names `manifest`, `root path and all four metrics`, `manifest order`, and explicit unreadable-shard reporting; assert each generator call's exit-2/exit-3 branch occurs before dispatch. Assert the scoped Codex path includes root/metrics, `do not read its shards`, and one literal diff fetch per selected path. Replace the stale eval claim that `scripts/review-package` remains monolithic/untouched with the D9 behavior.

- [ ] **Step 2: Run focused tests and observe the monolithic package fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_review_package.py home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: FAIL because the command currently writes one `.diff`, has no manifest/metrics/state, and reviewer contracts assume one inlined package file.

- [ ] **Step 3: Implement deterministic generation and manifest-aware review contracts**

Rewrite `review-package` as an executable import-safe Python script. Add `~/.agents/lib/python` to `sys.path`, import Task 1's module, validate plan/root and Git revisions, and obtain the one `review-package` limit set. Diff mode captures full SHAs/commits/stat, treats binary numstat `-` as zero churn, captures the binary diff once, finds only line-start `diff --git ` boundaries, and greedily groups complete chunks. Detail mode strictly parses the exact input finding records, canonicalizes each as one JSONL record, and greedily groups whole records under the same member limit; one oversized finding or oversized complete package yields the truthful over-budget producer state without truncation.

For detail mode, derive the primary checkout inside the command: resolve `git rev-parse --git-common-dir` to an absolute path without following an untrusted final component, require `.git`, derive its parent, and require `git -C <parent> rev-parse --show-toplevel` to return that exact canonical path. Validate issue as a non-boolean positive integer, producer against the two-value enum, head as a full lowercase object SHA, branch both with `git check-ref-format --branch` and against the linked worktree's current branch, and run id against `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`. A `-` run id deterministically becomes `branch-<sha256(branch UTF-8)>`. Construct the only allowed destination from those components; if `--output` is present, compare its unresolved lexical normalization and resolved existing-prefix identities to that destination and reject any mismatch, traversal, `.git`, outside-root, feature-worktree, or symlink-parent case.

Before staging detail, establish `.superpowers/issue-delivery/.gitignore` fail-closed. Walk/create `.superpowers` and `issue-delivery` one component at a time using directory FDs/no-follow checks. Exclusively create `.gitignore` with mode `0o600`, `O_CREAT|O_EXCL|O_WRONLY` and `O_NOFOLLOW` where supported, write exactly `*\n`, fsync, and verify its regular-file identity; if it already exists, accept only an ordinary non-symlink file with exactly those bytes. Create the issue/identity descendants with the same no-follow checks. Any validation/publication failure reports exit 2 and does not redirect output elsewhere.

Both modes write their exact D15 manifest/shards in a unique sibling stage, run `check_artifact`, then call `publish_package`. Implement mutation-point exclusion with `Path.mkdir()` for the final member directory and `os.link()` for each member and the manifest; never call replace/rename/copy over a final path. Record the directory identity immediately after creation and staged/final `(st_dev, st_ino)` after every successful link. On failure, unlink only a final entry whose current identity equals the recorded staged identity, then `rmdir` only when the directory is empty and still matches its recorded identity. Map `EXDEV`, collision, symlink/non-regular parent, or changed identity to `PublicationError`. The callback fires immediately before each actual mutation and is `None` outside tests. Validate every candidate producer report through `artifact-budget validate-report --boundary producer --input <temp>` and emit only validated stdout. A module/policy/check/publication failure produces a D14 `failed` candidate and validates it before emission.

Update SDD's task loop, `fix-loop.md`, and final review so every first-pass and fix-range generator stdout is passed unchanged to `artifact-budget validate-report --boundary producer --input -` before dispatch. For each site: generator exit 0 plus validator exit 0 and report/checker agreement permits dispatch; generator exit 3 records/returns `decompose_required` with no dispatch; generator/validator exit 2 or malformed/unknown output records/returns `failed` with no dispatch. All unscoped reviewer templates read the root JSON, validate its declared coverage/bytes against supplied checker metrics, then read shards once in listed order; delete their missing-package fallback for SDD-produced packages and explicitly report unreadable evidence.

Update `DIFF-REVIEW.md`, its eval, and the correctness prompt per D9: an unscoped correctness axis consumes all shards; a scoped axis is still handed root/metrics but treats them as range coverage only, never reads shards, and fetches exactly the selected files. Conformance always reads the complete package.

- [ ] **Step 4: Verify reconstruction, truthful stops, and all review consumers**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_review_package.py`

Expected: PASS; reconstructed bytes equal Git output, both purposes stay under one review budget, binary stats are zero churn, oversized cases stop, concurrent competitors remain byte-identical at every mutation boundary, commits/packages repeat byte-for-byte, and successful publication leaves no staging/orphan entries.

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
