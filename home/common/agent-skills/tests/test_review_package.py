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

    def test_publication_rejects_changed_directory_and_link_identities(self):
        for mutation in ("directory-before-first", "member-before-second",
                         "directory-before-manifest"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as raw:
                directory = Path(raw)
                stage = directory / "stage"
                stage_members = stage / "review.shards"
                stage_members.mkdir(parents=True)
                stage_root = stage / "review.json"
                stage_root.write_bytes(b"staged-manifest")
                (stage_members / "shard-001.diff").write_bytes(b"staged-one")
                (stage_members / "shard-002.diff").write_bytes(b"staged-two")
                final_root = directory / "review.json"
                final_members = directory / "review.shards"
                competitor = b"competitor-bytes"
                competed_path = final_members / "competitor"

                def inject(label: str, path: Path):
                    if mutation == "directory-before-first" and label == "member:shard-001.diff":
                        final_members.rmdir()
                        final_members.mkdir()
                        competed_path.write_bytes(competitor)
                    elif mutation == "member-before-second" and label == "member:shard-002.diff":
                        prior = final_members / "shard-001.diff"
                        prior.unlink()
                        prior.write_bytes(competitor)
                    elif mutation == "directory-before-manifest" and label == "manifest":
                        for member in final_members.iterdir():
                            member.unlink()
                        final_members.rmdir()
                        final_members.mkdir()
                        competed_path.write_bytes(competitor)

                with self.assertRaises(review_package_module.PublicationError):
                    review_package_module.publish_package(stage_root, final_root, inject)
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
