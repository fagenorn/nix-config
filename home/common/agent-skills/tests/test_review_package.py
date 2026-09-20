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
from unittest import mock


ROOT = Path(__file__).parents[4]
COMMAND = ROOT / "home/common/agent-skills/skills/sdd/scripts/review-package"
MODULE = ROOT / "home/common/agent-skills/scripts/artifact_budget.py"
POLICY = ROOT / "home/common/agent-skills/artifact-budget-policy.json"
sys.path.insert(0, str(MODULE.parent))
review_package_module = types.ModuleType("review_package")
SourceFileLoader("review_package", str(COMMAND)).exec_module(review_package_module)


# An artifact_budget shim: the real API when imported, a hard refusal when run
# as a script. review-package uses both faces — check_artifact/load_limits
# in-process, then `sys.executable <artifact_budget.__file__> validate-report`
# for the producer report — so only the second one may fail (D16). The
# sys.modules registration is load-bearing: dataclasses resolves
# cls.__module__ through sys.modules while exec_module runs.
REPORT_VALIDATOR_STUB = '''import sys

if __name__ == "__main__":
    sys.stderr.write("stub validator refuses validate-report\\n")
    raise SystemExit(9)

import types
from importlib.machinery import SourceFileLoader

_real = types.ModuleType("_real_artifact_budget")
sys.modules["_real_artifact_budget"] = _real
SourceFileLoader("_real_artifact_budget", REAL_MODULE_PATH).exec_module(_real)
ArtifactBudgetError = _real.ArtifactBudgetError
CheckResult = _real.CheckResult
check_artifact = _real.check_artifact
load_limits = _real.load_limits
'''


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
                      issue: str = "49", producer: str = "sdd", head: str,
                      output: Path | str | None = None):
        argv = [
            str(COMMAND), "--detail-input", str(source), "--producer", producer,
             "--issue", issue, "--branch", branch, "--run-id", run_id,
             "--head", head]
        if output is not None:
            argv += ["--output", str(output)]
        return subprocess.run(argv, cwd=repo, env=env, text=True,
                              capture_output=True, check=False)

    def test_unavailable_validator_has_one_stable_cli_failure(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            for broken in (False, True):
                with self.subTest(broken=broken):
                    home = directory / ("broken" if broken else "missing")
                    module_home = home / ".agents/lib/python"
                    module_home.mkdir(parents=True)
                    if broken:
                        (module_home / "artifact_budget.py").write_text(
                            "raise RuntimeError('broken validator')\n", encoding="utf-8"
                        )
                    env = os.environ.copy()
                    env.update({"HOME": str(home), "PYTHONPATH": ""})
                    result = subprocess.run(
                        [str(COMMAND)], cwd=directory, env=env, text=True,
                        capture_output=True, check=False,
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(
                        result.stderr, "review-package: validator unavailable\n"
                    )

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

    def test_fragmented_complete_diffs_use_bounded_adaptive_context_package(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            plan, env = self.setup_repo(repo)
            target_sizes = [
                25_203, 10_617, 59_012, 8_037, 50_410, 18_999,
                22_184, 54_145, 42_155, 44_332, 19_559, 12_004,
                25_696, 15_635, 23_066, 34_082, 5_682, 6_805,
            ]
            paths = []
            for number in range(len(target_sizes)):
                path = repo / f"f-{number:02d}.txt"
                path.write_text("small\n", encoding="utf-8")
                paths.append(path)
            base = self.commit(repo, "base", env)
            for number, (path, size) in enumerate(zip(paths, target_sizes)):
                path.write_text(chr(65 + number) * size + "\n", encoding="utf-8")
            head = self.commit(repo, "fragmented complete diffs", env)
            out = repo / "review.json"

            result = self.invoke(repo, plan, base, head, out, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["state"], "complete")
            manifest = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(manifest["interface_version"], 3)
            self.assertEqual(manifest["packaging"], {
                "context_lines": 7,
                "shard_strategy": "stable-first-fit-whole-file",
            })
            self.assertEqual(manifest["generated_evidence"], [])
            self.assertEqual(manifest["coverage"], {
                "complete": True,
                "file_diff_count": len(paths),
                "byte_complete_file_count": len(paths),
                "generated_evidence_file_count": 0,
            })
            self.assertLessEqual(len(manifest["shards"]), 8)
            self.assertTrue(all(item["bytes"] <= 65_536
                                for item in manifest["shards"]))
            expected = subprocess.run(
                ["git", "-C", str(repo), "diff", "--no-ext-diff", "--binary", "-U7",
                 f"{base}..{head}"], check=True, capture_output=True,
            ).stdout
            self.assertEqual(manifest["source_diff_bytes"], len(expected))
            packaged = b"".join((out.parent / item["path"]).read_bytes()
                                 for item in manifest["shards"])
            self.assertEqual(manifest["total_review_bytes"], len(packaged))
            for path in paths:
                header = f"diff --git a/{path.name} b/{path.name}\n".encode()
                self.assertEqual(packaged.count(header), 1)

    def test_multiple_commits_are_ordered_with_exact_full_identity(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            plan, env = self.setup_repo(repo)
            (repo / "a.txt").write_text("base\n", encoding="utf-8")
            base = self.commit(repo, "base", env)
            (repo / "a.txt").write_text("one\n", encoding="utf-8")
            first = self.commit(repo, "first change", env)
            (repo / "a.txt").write_text("two\n", encoding="utf-8")
            second = self.commit(repo, "second change", env)
            out = repo / "review.json"
            result = self.invoke(repo, plan, base, second, out, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(manifest["commits"], [
                {"sha": first, "subject": "first change"},
                {"sha": second, "subject": "second change"},
            ])

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

    def test_oversized_ef_designer_uses_bounded_semantic_evidence(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            plan, env = self.setup_repo(repo)
            migration_dir = repo / "src/App/Migrations"
            migration_dir.mkdir(parents=True)
            (migration_dir / "20260826010101_AddWidgets.cs").write_text(
                "public class AddWidgets { public void Up() {} public void Down() {} }\n",
                encoding="utf-8",
            )
            base = self.commit(repo, "base", env)
            designer = migration_dir / "20260826010101_AddWidgets.Designer.cs"
            designer.write_text(
                "\ufeff// <auto-generated />\n"
                "[Migration(\"20260826010101_AddWidgets\")]\n"
                "partial class AddWidgets {\n"
                "  void BuildTargetModel() {\n"
                "    modelBuilder.HasAnnotation(\"ProductVersion\", \"10.0.10\");\n"
                + "    modelBuilder.Entity(\"Widget\", b => { b.Property<int>(\"Id\"); "
                  "b.HasIndex(\"Id\"); b.HasOne(\"Owner\"); b.ToTable(\"widgets\"); });\n"
                  * 1_100
                + "  }\n}\n",
                encoding="utf-8",
            )
            head = self.commit(repo, "add generated designer", env)
            out = repo / "review.json"

            result = self.invoke(repo, plan, base, head, out, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["state"], "complete")
            manifest = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(manifest["interface_version"], 2)
            self.assertEqual(manifest["coverage"], {
                "complete": True,
                "file_diff_count": 1,
                "byte_complete_file_count": 0,
                "generated_evidence_file_count": 1,
            })
            self.assertGreater(manifest["source_diff_bytes"], 65_536)
            self.assertLess(manifest["total_review_bytes"], manifest["source_diff_bytes"])
            self.assertEqual(len(manifest["generated_evidence"]), 1)
            evidence = manifest["generated_evidence"][0]
            self.assertEqual(evidence["path"], designer.relative_to(repo).as_posix())
            self.assertEqual(evidence["kind"], "ef-core-migration-designer")
            self.assertIsNone(evidence["base"])
            self.assertEqual(evidence["head"]["migration_id"],
                             "20260826010101_AddWidgets")
            self.assertEqual(evidence["head"]["product_version"], "10.0.10")
            self.assertEqual(evidence["head"]["entity_types"], 1_100)
            self.assertTrue(all(item["bytes"] <= 65_536
                                for item in manifest["shards"]))
            packaged = b"".join((out.parent / item["path"]).read_bytes()
                                for item in manifest["shards"])
            self.assertIn(b'review-package-generated-evidence', packaged)
            self.assertNotIn(b'modelBuilder.Entity("Widget"', packaged)

    def test_oversized_designer_without_ef_generated_contract_still_stops(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            plan, env = self.setup_repo(repo)
            path = repo / "src/App/Migrations/NotGenerated.Designer.cs"
            path.parent.mkdir(parents=True)
            path.write_text("small\n", encoding="utf-8")
            base = self.commit(repo, "base", env)
            path.write_text("X" * 70_000 + "\n", encoding="utf-8")
            head = self.commit(repo, "large handwritten designer", env)
            out = repo / "review.json"

            result = self.invoke(repo, plan, base, head, out, env)

            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertEqual(json.loads(result.stdout)["state"], "decompose_required")

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

    def test_detail_publishes_from_a_primary_whose_common_dir_is_not_dot_git(self):
        """Identity first, primary second — the rule `sdd-workspace` applies.

        A `git init --separate-git-dir=` checkout reports a common dir named
        after the target, and a submodule working tree reports
        `<super>/.git/modules/<name>`; both own their common dir, so both are
        the primary. Demanding the `.git` name before deciding which checkout
        this is refused them here while `sdd-workspace` accepted them all run
        long — and delivery-detail publication is the last step of a run, so
        the refusal landed only at completion, after the work it publishes.
        """
        with tempfile.TemporaryDirectory() as raw:
            # Resolved: on macOS the temp root reaches through /var -> /private/var,
            # and the common dir git reports below is the physical path.
            directory = Path(raw).resolve()
            main = directory / "main"
            main.mkdir()
            subprocess.run(
                ["git", "init", "-q", "--separate-git-dir",
                 str(directory / "gd"), str(main)],
                check=True, capture_output=True,
            )
            _, env = self.setup_repo(main)
            common = self.run_git(
                main, "rev-parse", "--path-format=absolute", "--git-common-dir",
            ).strip()
            self.assertEqual(Path(common), directory / "gd")
            (main / "seed.txt").write_text("seed\n", encoding="utf-8")
            head = self.commit(main, "seed", env)
            # `--branch` must name the checkout's current branch; `git init`
            # picks the default branch from ambient config, so pin it here.
            self.run_git(main, "branch", "-M", "issue-49")
            source = main / "findings.json"
            source.write_text(json.dumps({
                "interface_version": 1,
                "findings": [{
                    "axis": "ship", "severity": "Minor", "status": "minor",
                    "text": "Retain this detail", "ruling": None,
                }],
            }), encoding="utf-8")
            out = main / ".superpowers/issue-delivery/49/run-1" / f"sdd-{head}.json"
            result = self.invoke_detail(main, source, env, head=head, output=out)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["artifact"]["path"],
                             out.relative_to(main).as_posix())
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["purpose"],
                             "delivery-detail")

    def test_detail_mode_rejects_untrusted_destinations_and_identity(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            main, linked, _, env, head = self.setup_linked_repo(directory)
            source = linked / "findings.json"
            valid_finding = {
                "axis": "ship", "severity": "Minor", "status": "minor",
                "text": "Retain this detail", "ruling": None,
            }
            source.write_text(json.dumps({"interface_version": 1,
                                          "findings": [valid_finding]}),
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
            bad_identity = [
                {"issue": "0"}, {"issue": "-1"}, {"issue": "true"},
                {"producer": "unknown"}, {"head": "abc"}, {"head": "B" * 40},
            ]
            for values in bad_identity:
                with self.subTest(values=values):
                    kwargs = {"head": head, **values}
                    result = self.invoke_detail(linked, source, env, **kwargs)
                    self.assertEqual((result.returncode, result.stdout), (2, ""))

    def test_detail_mode_rejects_a_symlink_parent(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            main, linked, _, env, head = self.setup_linked_repo(directory)
            source = linked / "findings.json"
            valid_finding = {
                "axis": "ship", "severity": "Minor", "status": "minor",
                "text": "Retain this detail", "ruling": None,
            }
            source.write_text(json.dumps({"interface_version": 1,
                                          "findings": [valid_finding]}),
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
            valid_finding = {
                "axis": "ship", "severity": "Minor", "status": "minor",
                "text": "Retain this detail", "ruling": None,
            }
            source.write_text(json.dumps({"interface_version": 1,
                                          "findings": [valid_finding]}),
                              encoding="utf-8")
            home = main / ".superpowers/issue-delivery"
            home.mkdir(parents=True)
            target = directory / "outside-ignore"
            target.write_text("*\n", encoding="utf-8")
            (home / ".gitignore").symlink_to(target)
            result = self.invoke_detail(linked, source, env, head=head)
            self.assertEqual((result.returncode, result.stdout), (2, ""))

    def test_detail_output_assertion_rejects_a_symlink_alias(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            main, linked, _, env, head = self.setup_linked_repo(directory)
            source = linked / "findings.json"
            source.write_text(json.dumps({
                "interface_version": 1,
                "findings": [{
                    "axis": "ship", "severity": "Minor", "status": "minor",
                    "text": "Retain this detail", "ruling": None,
                }],
            }), encoding="utf-8")
            expected_parent = main / ".superpowers/issue-delivery/49/run-1"
            expected_parent.mkdir(parents=True)
            (main / "delivery-alias").symlink_to(main / ".superpowers",
                                                 target_is_directory=True)
            aliased = (
                main / "delivery-alias/issue-delivery/49/run-1"
                / f"sdd-{head}.json"
            )
            result = self.invoke_detail(linked, source, env, head=head, output=aliased)
            self.assertEqual((result.returncode, result.stdout), (2, ""))

    def test_detail_output_assertion_rejects_a_primary_checkout_alias(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            main, linked, _, env, head = self.setup_linked_repo(directory)
            source = linked / "findings.json"
            source.write_text(json.dumps({
                "interface_version": 1,
                "findings": [{
                    "axis": "ship", "severity": "Minor", "status": "minor",
                    "text": "Retain this detail", "ruling": None,
                }],
            }), encoding="utf-8")
            alias = directory / "main-alias"
            alias.symlink_to(main, target_is_directory=True)
            aliased = (
                alias / ".superpowers/issue-delivery/49/run-1"
                / f"sdd-{head}.json"
            )
            result = self.invoke_detail(linked, source, env, head=head, output=aliased)
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

    def publication_fixture(
        self,
        directory: Path,
        members: tuple[bytes, ...] = (b"staged-one", b"staged-two"),
    ) -> tuple[Path, Path, Path]:
        stage = directory / "stage"
        stage_members = stage / "review.shards"
        stage_members.mkdir(parents=True)
        stage_root = stage / "review.json"
        stage_root.write_bytes(b"staged-manifest")
        for number, raw in enumerate(members, 1):
            (stage_members / f"shard-{number:03d}.diff").write_bytes(raw)
        final_root = directory / "review.json"
        return stage_root, final_root, directory / "review.shards"

    def test_publication_cleanup_stays_with_retained_member_directory(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            stage_root, final_root, final_members = self.publication_fixture(directory)
            stage_members = stage_root.with_suffix(".shards")
            original_members = directory / "review-original"
            competitor = final_members / "shard-001.diff"
            sentinel = final_members / "competitor"

            def replace_at_manifest(label: str, _path: Path):
                if label != "manifest":
                    return
                final_members.rename(original_members)
                final_members.mkdir()
                os.link(stage_members / "shard-001.diff", competitor,
                        follow_symlinks=False)
                sentinel.write_bytes(b"competitor-bytes")

            with self.assertRaises(review_package_module.PublicationError):
                review_package_module.publish_package(
                    stage_root, final_root, replace_at_manifest
                )

            self.assertFalse(final_root.exists())
            self.assertTrue(competitor.exists())
            self.assertEqual(competitor.read_bytes(), b"staged-one")
            self.assertEqual(sentinel.read_bytes(), b"competitor-bytes")
            self.assertEqual(list(original_members.iterdir()), [])

    def test_publication_rejects_changed_directory_and_link_identities(self):
        for mutation in ("directory-before-first", "member-before-second",
                         "directory-before-manifest"):
            attempts = 128 if mutation == "directory-before-first" else 1
            for attempt in range(attempts):
                with (self.subTest(mutation=mutation, attempt=attempt + 1),
                      tempfile.TemporaryDirectory() as raw):
                    directory = Path(raw)
                    stage_root, final_root, final_members = self.publication_fixture(
                        directory
                    )
                    competitor = b"competitor-bytes"
                    competed_path = final_members / "competitor"
                    observed: dict[str, tuple[int, int]] = {}

                    def replace_directory():
                        before = final_members.lstat()
                        observed["before"] = (before.st_dev, before.st_ino)
                        for member in final_members.iterdir():
                            member.unlink()
                        final_members.rmdir()
                        final_members.mkdir()
                        after = final_members.lstat()
                        observed["after"] = (after.st_dev, after.st_ino)
                        competed_path.write_bytes(competitor)

                    def inject(label: str, _path: Path):
                        if (mutation == "directory-before-first"
                                and label == "member:shard-001.diff"):
                            replace_directory()
                        elif (mutation == "member-before-second"
                              and label == "member:shard-002.diff"):
                            prior = final_members / "shard-001.diff"
                            prior.unlink()
                            prior.write_bytes(competitor)
                        elif (mutation == "directory-before-manifest"
                              and label == "manifest"):
                            replace_directory()

                    try:
                        review_package_module.publish_package(
                            stage_root, final_root, inject
                        )
                    except review_package_module.PublicationError:
                        pass
                    else:
                        self.fail(
                            "publication accepted replacement: "
                            f"mutation={mutation} attempt={attempt + 1}/{attempts} "
                            f"platform={sys.platform} before={observed.get('before')} "
                            f"after={observed.get('after')}"
                        )

                    self.assertFalse(final_root.exists())
                    if mutation == "member-before-second":
                        competed_path = final_members / "shard-001.diff"
                    self.assertEqual(competed_path.read_bytes(), competitor)

    def test_parent_swap_cannot_redirect_publication_outside_root(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            primary = directory / "primary"
            outside = directory / "outside"
            stage = directory / "stage"
            primary.mkdir()
            outside.mkdir()
            stage_members = stage / "review.shards"
            stage_members.mkdir(parents=True)
            stage_root = stage / "review.json"
            stage_root.write_bytes(b"staged-manifest")
            (stage_members / "shard-001.diff").write_bytes(b"staged-shard")
            chain = review_package_module._ensure_directories(
                primary, ["identity"], retain=True
            )
            self.assertIsNotNone(chain)
            identity = primary / "identity"
            moved = primary / "identity-moved"
            final_root = identity / "review.json"

            def swap_parent(label: str, _path: Path):
                if label == "member_dir":
                    identity.rename(moved)
                    identity.symlink_to(outside, target_is_directory=True)

            try:
                with self.assertRaises(review_package_module.PublicationError):
                    review_package_module.publish_package(
                        stage_root, final_root, swap_parent,
                        final_parent_fd=chain.leaf,
                        verify_final_parent=chain.verify,
                    )
            finally:
                chain.close()
            self.assertEqual(list(outside.iterdir()), [])
            self.assertFalse((moved / "review.json").exists())
            self.assertFalse((moved / "review.shards").exists())

    def test_member_link_cannot_be_redirected_at_the_syscall_boundary(self):
        for replacement in ("directory", "symlink"):
            with (self.subTest(replacement=replacement),
                  tempfile.TemporaryDirectory() as raw):
                directory = Path(raw)
                stage_root, final_root, final_members = self.publication_fixture(
                    directory, (b"staged-one",)
                )
                stage_members = stage_root.with_suffix(".shards")
                original_members = directory / "review-original"
                outside = directory / "outside"
                outside.mkdir()
                redirected_during_link = False
                real_link = review_package_module.os.link

                def replace_then_link(source, destination, *args, **kwargs):
                    nonlocal redirected_during_link
                    if Path(source).parent == stage_members:
                        final_members.rename(original_members)
                        if replacement == "directory":
                            final_members.mkdir()
                            replacement_root = final_members
                        else:
                            final_members.symlink_to(outside, target_is_directory=True)
                            replacement_root = outside
                        (replacement_root / "competitor").write_bytes(
                            b"competitor-bytes"
                        )
                        result = real_link(source, destination, *args, **kwargs)
                        redirected_during_link = (
                            replacement_root / Path(source).name
                        ).exists()
                        return result
                    return real_link(source, destination, *args, **kwargs)

                with mock.patch.object(
                    review_package_module.os, "link", side_effect=replace_then_link
                ):
                    with self.assertRaises(review_package_module.PublicationError):
                        review_package_module.publish_package(stage_root, final_root)

                replacement_root = (
                    final_members if replacement == "directory" else outside
                )
                self.assertFalse(redirected_during_link)
                self.assertEqual(
                    {path.name for path in replacement_root.iterdir()}, {"competitor"}
                )
                self.assertEqual(
                    (replacement_root / "competitor").read_bytes(),
                    b"competitor-bytes",
                )
                self.assertEqual(list(original_members.iterdir()), [])
                self.assertFalse(final_root.exists())

    def test_member_directory_acquisition_errors_refuse_without_deleting_name(self):
        for fault in ("open", "fstat"):
            with (self.subTest(fault=fault),
                  tempfile.TemporaryDirectory() as raw):
                directory = Path(raw)
                stage_root, final_root, final_members = self.publication_fixture(
                    directory, (b"staged-one",)
                )
                real_open = review_package_module.os.open
                real_fstat = review_package_module.os.fstat
                acquired: list[int] = []

                def open_member(path, flags, *args, **kwargs):
                    if Path(path).name == final_members.name and fault == "open":
                        raise OSError("injected member-directory open failure")
                    descriptor = real_open(path, flags, *args, **kwargs)
                    if Path(path).name == final_members.name:
                        acquired.append(descriptor)
                    return descriptor

                def stat_member(descriptor):
                    if acquired and descriptor == acquired[-1] and fault == "fstat":
                        raise OSError("injected member-directory stat failure")
                    return real_fstat(descriptor)

                with (mock.patch.object(review_package_module.os, "open",
                                        side_effect=open_member),
                      mock.patch.object(review_package_module.os, "fstat",
                                        side_effect=stat_member)):
                    with self.assertRaises(review_package_module.PublicationError):
                        review_package_module.publish_package(stage_root, final_root)

                self.assertTrue(final_members.is_dir())
                self.assertEqual(list(final_members.iterdir()), [])
                self.assertFalse(final_root.exists())
                for descriptor in acquired:
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)

    def test_member_directory_acquisition_rejects_open_boundary_replacement(self):
        for boundary in ("before-open", "after-open"):
            with (self.subTest(boundary=boundary),
                  tempfile.TemporaryDirectory() as raw):
                directory = Path(raw)
                stage_root, final_root, final_members = self.publication_fixture(
                    directory, (b"staged-one",)
                )
                original_members = directory / "review-original"
                sentinel = final_members / "competitor"
                real_open = review_package_module.os.open
                acquired: list[int] = []
                callbacks: list[str] = []

                def observe_callback(label: str, _path: Path):
                    callbacks.append(label)

                def replace_around_open(path, flags, *args, **kwargs):
                    if Path(path) != final_members:
                        return real_open(path, flags, *args, **kwargs)
                    if boundary == "before-open":
                        final_members.rename(original_members)
                        final_members.mkdir()
                        sentinel.write_bytes(b"competitor-bytes")
                        descriptor = real_open(path, flags, *args, **kwargs)
                    else:
                        descriptor = real_open(path, flags, *args, **kwargs)
                        final_members.rename(original_members)
                        final_members.mkdir()
                        sentinel.write_bytes(b"competitor-bytes")
                    acquired.append(descriptor)
                    return descriptor

                with mock.patch.object(
                    review_package_module.os, "open", side_effect=replace_around_open
                ):
                    with self.assertRaises(review_package_module.PublicationError):
                        review_package_module.publish_package(
                            stage_root, final_root, observe_callback
                        )

                self.assertEqual(callbacks, ["member_dir"])
                self.assertEqual(sentinel.read_bytes(), b"competitor-bytes")
                self.assertEqual(list(original_members.iterdir()), [])
                self.assertFalse(final_root.exists())
                self.assertTrue(acquired)
                for descriptor in acquired:
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)

    def test_publication_releases_owned_descriptors_and_preserves_borrowed_parent(self):
        for outcome in ("success", "publication-failure"):
            with (self.subTest(outcome=outcome),
                  tempfile.TemporaryDirectory() as raw):
                directory = Path(raw)
                primary = directory / "primary"
                primary.mkdir()
                chain = review_package_module._ensure_directories(
                    primary, ["destination"], retain=True
                )
                self.assertIsNotNone(chain)
                destination = primary / "destination"
                stage_root, _, _ = self.publication_fixture(
                    directory / "fixture", (b"staged-one",)
                )
                final_root = destination / "review.json"
                starting_cwd = Path.cwd()
                real_open = review_package_module.os.open
                opened: list[int] = []
                member_fds: list[int] = []

                def observe_open(path, flags, *args, **kwargs):
                    descriptor = real_open(path, flags, *args, **kwargs)
                    opened.append(descriptor)
                    if Path(path).name == "review.shards":
                        member_fds.append(descriptor)
                    return descriptor

                def compete_with_manifest(label: str, path: Path):
                    if outcome == "publication-failure" and label == "manifest":
                        path.write_bytes(b"competitor-manifest")

                try:
                    with mock.patch.object(
                        review_package_module.os, "open", side_effect=observe_open
                    ):
                        if outcome == "success":
                            review_package_module.publish_package(
                                stage_root, final_root,
                                final_parent_fd=chain.leaf,
                                verify_final_parent=chain.verify,
                            )
                        else:
                            with self.assertRaises(
                                review_package_module.PublicationError
                            ):
                                review_package_module.publish_package(
                                    stage_root, final_root, compete_with_manifest,
                                    final_parent_fd=chain.leaf,
                                    verify_final_parent=chain.verify,
                                )

                    self.assertEqual(Path.cwd(), starting_cwd)
                    os.fstat(chain.leaf)
                    self.assertTrue(opened)
                    self.assertTrue(member_fds)
                    for descriptor in opened:
                        with self.assertRaises(OSError):
                            os.fstat(descriptor)
                    if outcome == "success":
                        self.assertEqual(final_root.read_bytes(), b"staged-manifest")
                    else:
                        self.assertEqual(
                            final_root.read_bytes(), b"competitor-manifest"
                        )
                finally:
                    chain.close()

    def test_publication_releases_member_descriptor_without_parent_fd(self):
        for outcome in ("success", "publication-failure"):
            with (self.subTest(outcome=outcome),
                  tempfile.TemporaryDirectory() as raw):
                directory = Path(raw)
                stage_root, final_root, final_members = self.publication_fixture(
                    directory, (b"staged-one",)
                )
                starting_cwd = Path.cwd()
                real_open = review_package_module.os.open
                member_fds: list[int] = []

                def observe_open(path, flags, *args, **kwargs):
                    descriptor = real_open(path, flags, *args, **kwargs)
                    if Path(path) == final_members:
                        member_fds.append(descriptor)
                    return descriptor

                def compete_with_manifest(label: str, path: Path):
                    if outcome == "publication-failure" and label == "manifest":
                        path.write_bytes(b"competitor-manifest")

                with mock.patch.object(
                    review_package_module.os, "open", side_effect=observe_open
                ):
                    if outcome == "success":
                        review_package_module.publish_package(stage_root, final_root)
                    else:
                        with self.assertRaises(review_package_module.PublicationError):
                            review_package_module.publish_package(
                                stage_root, final_root, compete_with_manifest
                            )

                self.assertEqual(Path.cwd(), starting_cwd)
                self.assertTrue(member_fds)
                for descriptor in member_fds:
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)
                if outcome == "success":
                    self.assertEqual(final_root.read_bytes(), b"staged-manifest")
                else:
                    self.assertEqual(final_root.read_bytes(), b"competitor-manifest")

    def test_close_failure_after_publication_preserves_package_and_recycled_fd(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            primary = directory / "primary"
            primary.mkdir()
            chain = review_package_module._ensure_directories(
                primary, ["destination"], retain=True
            )
            self.assertIsNotNone(chain)
            destination = primary / "destination"
            stage_root, _, _ = self.publication_fixture(
                directory / "fixture", (b"staged-one",)
            )
            final_root = destination / "review.json"
            final_members = destination / "review.shards"
            starting_cwd = Path.cwd()
            real_open = review_package_module.os.open
            real_close = review_package_module.os.close
            opened: list[int] = []
            member_fds: list[int] = []
            recycled_fd: int | None = None
            injected = False

            def observe_open(path, flags, *args, **kwargs):
                descriptor = real_open(path, flags, *args, **kwargs)
                opened.append(descriptor)
                if Path(path).name == final_members.name:
                    member_fds.append(descriptor)
                return descriptor

            def fail_after_real_close(descriptor):
                nonlocal recycled_fd, injected
                if member_fds and descriptor == member_fds[-1] and not injected:
                    real_close(descriptor)
                    recycled_fd = real_open(os.devnull, os.O_RDONLY)
                    if recycled_fd != descriptor:
                        real_close(recycled_fd)
                        recycled_fd = None
                        raise RuntimeError("fixture could not observe fd reuse")
                    injected = True
                    raise OSError("injected close failure after real close")
                return real_close(descriptor)

            try:
                with (mock.patch.object(review_package_module.os, "open",
                                        side_effect=observe_open),
                      mock.patch.object(review_package_module.os, "close",
                                        side_effect=fail_after_real_close)):
                    with self.assertRaises(review_package_module.PublicationError):
                        review_package_module.publish_package(
                            stage_root, final_root,
                            final_parent_fd=chain.leaf,
                            verify_final_parent=chain.verify,
                        )

                self.assertTrue(injected)
                self.assertIsNotNone(recycled_fd)
                os.fstat(recycled_fd)
                self.assertEqual(Path.cwd(), starting_cwd)
                os.fstat(chain.leaf)
                for descriptor in opened:
                    if descriptor != recycled_fd:
                        with self.assertRaises(OSError):
                            os.fstat(descriptor)
                self.assertEqual(final_root.read_bytes(), b"staged-manifest")
                self.assertEqual(
                    (final_members / "shard-001.diff").read_bytes(), b"staged-one"
                )
            finally:
                if recycled_fd is not None:
                    real_close(recycled_fd)
                chain.close()

    def test_restoration_failure_still_closes_saved_cwd_descriptor(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            primary = directory / "primary"
            primary.mkdir()
            chain = review_package_module._ensure_directories(
                primary, ["destination"], retain=True
            )
            self.assertIsNotNone(chain)
            destination = primary / "destination"
            stage_root, _, _ = self.publication_fixture(
                directory / "fixture", (b"staged-one",)
            )
            final_root = destination / "review.json"
            starting_cwd = Path.cwd()
            real_open = review_package_module.os.open
            real_close = review_package_module.os.close
            real_fchdir = review_package_module.os.fchdir
            rescue_fd = real_open(
                starting_cwd,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            previous_fds: list[int] = []
            member_fds: list[int] = []

            def observe_open(path, flags, *args, **kwargs):
                descriptor = real_open(path, flags, *args, **kwargs)
                if Path(path) == starting_cwd:
                    previous_fds.append(descriptor)
                if Path(path).name == "review.shards":
                    member_fds.append(descriptor)
                return descriptor

            def fail_restoration(descriptor):
                if previous_fds and descriptor == previous_fds[-1]:
                    raise OSError("injected cwd restoration failure")
                return real_fchdir(descriptor)

            try:
                try:
                    with (mock.patch.object(review_package_module.os, "open",
                                            side_effect=observe_open),
                          mock.patch.object(review_package_module.os, "fchdir",
                                            side_effect=fail_restoration)):
                        with self.assertRaises(review_package_module.PublicationError):
                            review_package_module.publish_package(
                                stage_root, final_root,
                                final_parent_fd=chain.leaf,
                                verify_final_parent=chain.verify,
                            )
                finally:
                    real_fchdir(rescue_fd)
                    real_close(rescue_fd)

                self.assertEqual(Path.cwd(), starting_cwd)
                self.assertTrue(previous_fds)
                self.assertTrue(member_fds)
                for descriptor in previous_fds + member_fds:
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)
                os.fstat(chain.leaf)
                self.assertEqual(final_root.read_bytes(), b"staged-manifest")
            finally:
                chain.close()

    def test_publication_failure_remains_primary_when_release_also_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            stage_root, final_root, final_members = self.publication_fixture(
                directory, (b"staged-one",)
            )
            stage_members = stage_root.with_suffix(".shards")
            real_open = review_package_module.os.open
            real_link = review_package_module.os.link
            real_close = review_package_module.os.close
            member_fds: list[int] = []
            release_failed = False

            def observe_open(path, flags, *args, **kwargs):
                descriptor = real_open(path, flags, *args, **kwargs)
                if Path(path) == final_members:
                    member_fds.append(descriptor)
                return descriptor

            def fail_member_link(source, destination, *args, **kwargs):
                if Path(source).parent == stage_members:
                    raise OSError("injected publication failure")
                return real_link(source, destination, *args, **kwargs)

            def fail_member_release(descriptor):
                nonlocal release_failed
                if member_fds and descriptor == member_fds[-1] and not release_failed:
                    real_close(descriptor)
                    release_failed = True
                    raise OSError("injected member release failure")
                return real_close(descriptor)

            with (mock.patch.object(review_package_module.os, "open",
                                    side_effect=observe_open),
                  mock.patch.object(review_package_module.os, "link",
                                    side_effect=fail_member_link),
                  mock.patch.object(review_package_module.os, "close",
                                    side_effect=fail_member_release)):
                with self.assertRaises(
                    review_package_module.PublicationError
                ) as raised:
                    review_package_module.publish_package(stage_root, final_root)

            failure = raised.exception
            self.assertEqual(str(failure), "exclusive package publication failed")
            self.assertIsInstance(failure.__cause__, OSError)
            self.assertEqual(str(failure.__cause__), "injected publication failure")
            self.assertTrue(release_failed)
            self.assertTrue(any(
                "injected member release failure" in note
                for note in getattr(failure, "__notes__", [])
            ))
            for descriptor in member_fds:
                with self.assertRaises(OSError):
                    os.fstat(descriptor)
            self.assertFalse(final_root.exists())

    def test_stage_write_failure_removes_partial_stage_directory(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            final_root = directory / "review.json"
            with mock.patch.object(
                Path, "write_bytes",
                side_effect=OSError("injected write failure"),
            ):
                with self.assertRaises(review_package_module.GenerationError):
                    review_package_module._write_stage(
                        final_root, {"manifest": "candidate"}, [b"member"], "diff"
                    )
            self.assertFalse(any(".stage-" in path.name for path in directory.iterdir()))

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

    def test_report_validation_failure_removes_the_report_candidate(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw) / "repo"
            repo.mkdir()
            plan, env = self.setup_repo(repo)
            (repo / "a.txt").write_text("before\n", encoding="utf-8")
            base = self.commit(repo, "base", env)
            (repo / "a.txt").write_text("after\n", encoding="utf-8")
            head = self.commit(repo, "change a", env)

            shim = Path(env["PYTHONPATH"]) / "artifact_budget.py"
            shim.unlink()
            shim.write_text(
                REPORT_VALIDATOR_STUB.replace("REAL_MODULE_PATH", repr(str(MODULE))),
                encoding="utf-8",
            )
            scratch = Path(raw) / "tmp"
            scratch.mkdir()
            env["TMPDIR"] = str(scratch)

            result = self.invoke(repo, plan, base, head, repo / "review.json", env)

            # Non-vacuity: the run reached the candidate rather than refusing at
            # bootstrap. "validator unavailable" here would mean the shim broke
            # the in-process API and nothing was ever created to clean up.
            self.assertEqual(result.stderr, "review-package: generation failed\n")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertEqual(
                sorted(p.name for p in scratch.glob("review-package-report-*.json")),
                [],
            )
