"""Contract tests for the repository- and verification-domain evaluators.

Path classification, the runtime ignore sentinel, shell indirection, the two
residue checks and the release-profile lint trio, each judged through one
`doctor` run against a temporary root (D16). The ladder, the host domain and
the report schema are in test_conformance.py."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import types
import unittest
import unittest.mock
from pathlib import Path

from agent_tools.delivery import context_map_lint, standards_lint
from agent_tools.project_contract import resolve_project

from .conformance_test_support import (
    CLEAN_MAP, HERMETIC_ENV, INTEGRATION_REF, REPO_ROOT, ReportAssertions,
    commit_all, doctor, fixture, git, load_module, make_root, platform_env, run,
    write_clean_map,
)
from .test_resolve_project import STANDARDS


RELEASE_FIXTURES = REPO_ROOT / "tests/fixtures/release"


def conformance_lint_facts(problems: list) -> dict:
    """The facts a lint's diagnostics become, computed here from the diagnostic
    format (`<label>: <text>`) rather than by the code under test."""
    labels = {p.split(": ", 1)[0] for p in problems if ": " in p}
    labels = {l for l in labels if l and not any(c.isspace() for c in l)
              and not l.startswith("/") and ".." not in Path(l).parts}
    return {"paths": sorted(labels)[:8], "count": len(problems)}


def release_fixture(name: str) -> dict:
    return json.loads((RELEASE_FIXTURES / name).read_text(encoding="utf-8"))


def write_file(root: Path, relative: str, text: str = "x\n") -> Path:
    """One file at `relative` under `root`, with every parent created."""
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


class PathClassificationTest(ReportAssertions, unittest.TestCase):
    """#72: the four lifecycle classes are closed. A path matching none of them
    is a finding, never a new implicit class, and every offender is named
    repository-relative so a reader can open it."""

    CHECK_ID = "repository.paths.classified"
    REPAIR_ID = "lifecycle.path.classify"

    def test_a_conformant_tree_passes_with_no_repair_and_no_facts(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp))
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["domain"], check["subject_kind"], check["status"],
                 check["reason_code"], check["repair_id"], check["facts"]],
                ["repository", "path", "passed", None, None, {}])
            self.assert_validates(report)

    def test_a_path_outside_every_class_is_a_finding(self):
        """An unadmitted `artifacts/` bucket is unclassified for the same reason
        a stray directory is: the class list, not the parent, admits a path."""
        for relative in (".agents/scratchpad/notes.txt",
                         ".agents/artifacts/scratch/x.md"):
            with self.subTest(relative=relative), fixture() as tmp:
                root = make_root(tmp)
                write_file(root, relative)
                report, by_id = doctor(self, root)
                check = by_id[self.CHECK_ID]
                self.assertEqual(
                    [check["status"], check["reason_code"], check["repair_id"]],
                    ["failed", "unclassified_path", self.REPAIR_ID])
                self.assertEqual(check["facts"],
                                 {"paths": [relative], "count": 1})
                repair = {r["repair_id"]: r
                          for r in report["repairs"]}[self.REPAIR_ID]
                self.assertEqual(
                    [repair["module"], repair["safety_class"], repair["operation"]],
                    ["conformance", "user_action", None])
                self.assert_validates(report)

    def test_an_unclassified_symlink_cannot_escape_by_pointing_at_a_directory(self):
        """`rglob` does not descend through a directory symlink and `is_file()`
        rejects the link itself, so a link judged only by what it resolves to
        would contribute no subject at all — the one shape that turns an
        unclassified path into silence rather than a finding."""
        for label, target in (("directory", ".agents/artifacts/specs"),
                              ("dangling", ".agents/nowhere")):
            with self.subTest(target=label), fixture() as tmp:
                root = make_root(tmp)
                (root / ".agents/scratchpad").symlink_to(root / target)
                report, by_id = doctor(self, root)
                check = by_id[self.CHECK_ID]
                self.assertEqual(
                    [check["status"], check["reason_code"], check["repair_id"]],
                    ["failed", "unclassified_path", self.REPAIR_ID])
                self.assertEqual(check["facts"],
                                 {"paths": [".agents/scratchpad"], "count": 1})
                self.assert_validates(report)

    def test_runtime_state_is_a_class_not_an_escape(self):
        with fixture() as tmp:
            root = make_root(tmp)
            write_file(root, ".agents/runtime/state/run-1/state.json", "{}\n")
            report, by_id = doctor(self, root)
            check = by_id[self.CHECK_ID]
            self.assertEqual([check["status"], check["facts"]], ["passed", {}])
            self.assert_validates(report)

    def test_every_admitted_artifacts_bucket_is_canonical_tracked(self):
        """The bucket list is the admitting mechanism: `replays` holds #283's
        committed light-lane replay records beside specs, plans and evidence."""
        for bucket in ("specs", "plans", "evidence", "handoffs", "notes",
                       "replays"):
            relative = f".agents/artifacts/{bucket}/2026-10-08-x/records/1.json"
            with self.subTest(bucket=bucket), fixture() as tmp:
                root = make_root(tmp)
                write_file(root, relative, "{}\n")
                report, by_id = doctor(self, root)
                check = by_id[self.CHECK_ID]
                self.assertEqual([check["status"], check["facts"]],
                                 ["passed", {}])
                self.assert_validates(report)

    def test_many_long_offending_paths_are_capped_bounded_and_distinct(self):
        """D30: a repository-relative path has no length ceiling, so an
        unbounded fact would fail the engine's own report validation and turn a
        repository finding into `resolver_failure`. D41: the eight slots name
        eight subjects.

        Ten sibling trees each share a prefix longer than MAX_FACT_STRING, so
        the three paths inside a tree bound to one identical string. Bounding
        before de-duplicating is the whole difference between eight subjects
        and one subject repeated eight times.
        """
        with fixture() as tmp:
            root = make_root(tmp)
            for group in range(10):
                deep = "/".join([f".agents/scratchpad/g{group}"] + ["d" * 40] * 6)
                for index in range(3):
                    write_file(root, f"{deep}/f{index}.txt")
            report, by_id = doctor(self, root)
            check = by_id[self.CHECK_ID]
            paths = check["facts"]["paths"]
            self.assertEqual(check["status"], "failed")
            self.assertEqual(check["facts"]["count"], 30)
            self.assertEqual(len(paths), 8)
            self.assertEqual({len(path) for path in paths}, {200})
            self.assertEqual(len(set(paths)), 8)   # eight subjects, not one
            self.assertEqual(paths, sorted(paths))
            self.assert_validates(report)


class IgnoreSentinelTest(ReportAssertions, unittest.TestCase):
    """#72: `.agents/runtime/` is covered by a root rule or by the committed
    sentinel — either spelling, because both are legitimate homes. Only the
    tracked ignore files are read; `.git/info/exclude` is machine-local and a
    machine-local rule cannot be the repository's classification."""

    CHECK_ID = "repository.ignore.runtime_sentinel"
    REPAIR_ID = "lifecycle.ignore.repair"

    def build(self, tmp: Path, gitignore: str, sentinel: bool = False) -> Path:
        root = make_root(tmp)
        (root / ".gitignore").write_text(gitignore, encoding="utf-8")
        if sentinel:
            write_file(root, ".agents/runtime/.gitignore", "*\n")  # exactly b"*\n"
        return root

    def test_either_spelling_of_the_runtime_rule_passes(self):
        for label, gitignore, sentinel in (
                ("root rule", "# comment\n\n.agents/runtime/\n", False),
                ("committed sentinel", "result\n", True)):
            with self.subTest(coverage=label), fixture() as tmp:
                report, by_id = doctor(self, self.build(tmp, gitignore, sentinel))
                check = by_id[self.CHECK_ID]
                self.assertEqual(
                    [check["domain"], check["subject_kind"], check["status"],
                     check["reason_code"], check["repair_id"], check["facts"]],
                    ["repository", "path", "passed", None, None, {}])
                self.assert_validates(report)

    def test_neither_spelling_present_is_the_missing_finding(self):
        with fixture() as tmp:
            report, by_id = doctor(self, self.build(tmp, "result\n"))
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["status"], check["reason_code"], check["repair_id"]],
                ["failed", "runtime_ignore_missing", self.REPAIR_ID])
            self.assertEqual(check["facts"],
                             {"root_gitignore": True, "sentinel": False})
            repair = {r["repair_id"]: r for r in report["repairs"]}[self.REPAIR_ID]
            self.assertEqual(
                [repair["module"], repair["safety_class"], repair["operation"]],
                ["conformance", "worktree", None])
            self.assert_validates(report)

    def test_an_overbroad_rule_outranks_a_covered_runtime_subtree(self):
        """The runtime rule is present and the check still fails: an overbroad
        ignore conceals authored truth, so it is the finding that is reported."""
        with fixture() as tmp:
            report, by_id = doctor(
                self, self.build(tmp, ".agents/runtime/\n.agents/*\n"))
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["status"], check["reason_code"], check["repair_id"]],
                ["failed", "overbroad_ignore", self.REPAIR_ID])
            self.assertEqual(check["facts"],
                             {"rules": [".agents/*"], "count": 1})
            self.assert_validates(report)


class ShellIndirectionTest(ReportAssertions, unittest.TestCase):
    """The command *policy* check: the resolver already validated command shape,
    and neither re-implements the other. Facts carry command ids, never argv."""

    CHECK_ID = "verification.commands.no_shell_indirection"
    REPAIR_ID = "contract.commands.destructure"

    def with_argv(self, root: Path, command_id: str, argv: list) -> Path:
        contract = root / ".agents/project.json"
        authored = json.loads(contract.read_text(encoding="utf-8"))
        authored["bindings"]["commands"][command_id]["argv"] = argv
        contract.write_text(json.dumps(authored, indent=2), encoding="utf-8")
        return root

    def test_plain_argv_passes_with_no_repair_and_no_facts(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp))
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["domain"], check["subject_kind"], check["status"],
                 check["reason_code"], check["repair_id"], check["facts"]],
                ["verification", "command", "passed", None, None, {}])
            self.assert_validates(report)

    def test_a_shell_or_a_metacharacter_names_the_offending_command_id(self):
        for label, argv in (("shell -c", ["bash", "-c", "just build"]),
                            ("bundled -lc", ["bash", "-lc", "just build"]),
                            ("bundled -ec", ["sh", "-ec", "just build"]),
                            ("metacharacter", ["just", "build && just switch"])):
            with self.subTest(indirection=label), fixture() as tmp:
                root = self.with_argv(make_root(tmp), "nix-build", argv)
                report, by_id = doctor(self, root)
                check = by_id[self.CHECK_ID]
                self.assertEqual(
                    [check["status"], check["reason_code"], check["repair_id"]],
                    ["failed", "shell_indirection", self.REPAIR_ID])
                self.assertEqual(check["facts"],
                                 {"commands": ["nix-build"], "count": 1})
                repair = {r["repair_id"]: r
                          for r in report["repairs"]}[self.REPAIR_ID]
                self.assertEqual(
                    [repair["module"], repair["safety_class"], repair["operation"]],
                    ["resolve-project", "user_action", None])
                self.assert_validates(report)

    def test_ci_selects_the_verification_check_and_fleet_does_not(self):
        """The purpose table's own claim, proved rather than assumed."""
        for purpose, expected in (("ci", True), ("fleet", False)):
            with self.subTest(purpose=purpose), fixture() as tmp:
                code, out, err = run("run", "--purpose", purpose, "--repo-root",
                                     str(make_root(tmp)))
                self.assertEqual(code, 0, err)
                ids = [c["id"] for c in json.loads(out)["checks"]]
                self.assertEqual(self.CHECK_ID in ids, expected)


class ConformanceWorkflowCheckTest(ReportAssertions, unittest.TestCase):
    """The interim freshness check: the committed conformance workflow is
    judged against the renderer's bytes until a contract declares it."""

    CHECK_ID = "verification.conformance_workflow.fresh"
    REPAIR_ID = "conformance.workflow.regenerate"
    TARGET = ".github/workflows/conformance.yaml"

    def ci(self, root: Path) -> tuple[int, dict]:
        code, out, err = run("run", "--purpose", "ci", "--repo-root", str(root))
        self.assertIn(code, (0, 1), err)
        return code, json.loads(out)

    def write_workflow(self, root: Path, data: bytes) -> None:
        target = root / self.TARGET
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def test_a_hand_edited_conformance_workflow_turns_ci_red_and_names_it(self):
        with fixture() as tmp:
            root = make_root(tmp)
            self.write_workflow(
                root,
                resolve_project.render_conformance_workflow("main", 2)
                + b"# hand edit\n")
            code, report = self.ci(root)
            self.assertEqual(code, 1)
            self.assertEqual(report["outcome"], {
                "status": "failed", "primary_check_id": self.CHECK_ID})
            check = {c["id"]: c for c in report["checks"]}[self.CHECK_ID]
            self.assertEqual(
                [check["status"], check["reason_code"], check["repair_id"],
                 check["facts"]],
                ["failed", "conformance_workflow_stale", self.REPAIR_ID,
                 {"target": self.TARGET, "state": "stale"}])
            repair = {r["repair_id"]: r for r in report["repairs"]}[self.REPAIR_ID]
            self.assertEqual(
                [repair["module"], repair["safety_class"], repair["operation"]],
                ["resolve-project", "worktree", None])
            self.assert_validates(report)

    def test_the_rendered_workflow_and_an_absent_one_both_pass(self):
        for label, data in (
                ("rendered", resolve_project.render_conformance_workflow("main", 2)),
                ("absent", None)):
            with self.subTest(workflow=label), fixture() as tmp:
                root = make_root(tmp)
                if data is not None:
                    self.write_workflow(root, data)
                code, report = self.ci(root)
                self.assertEqual(code, 0)
                check = {c["id"]: c for c in report["checks"]}[self.CHECK_ID]
                self.assertEqual([check["status"], check["facts"]], ["passed", {}])
                self.assertEqual(report["outcome"]["status"], "passed")

    def test_a_workflow_entry_that_is_not_a_regular_file_is_stale(self):
        rendered = resolve_project.render_conformance_workflow("main", 2)
        for label in ("dangling symlink", "symlink to the rendered bytes"):
            with self.subTest(entry=label), fixture() as tmp:
                root = make_root(tmp)
                target = root / self.TARGET
                target.parent.mkdir(parents=True, exist_ok=True)
                if label == "dangling symlink":
                    target.symlink_to(tmp / "missing.yaml")
                else:
                    (tmp / "elsewhere.yaml").write_bytes(rendered)
                    target.symlink_to(tmp / "elsewhere.yaml")
                code, report = self.ci(root)
                self.assertEqual(code, 1)
                check = {c["id"]: c for c in report["checks"]}[self.CHECK_ID]
                self.assertEqual(
                    [check["status"], check["reason_code"], check["facts"]],
                    ["failed", "conformance_workflow_stale",
                     {"target": self.TARGET, "state": "stale"}])
                self.assert_validates(report)

    def test_an_unrenderable_branch_is_a_finding(self):
        with fixture() as tmp:
            root = make_root(tmp)
            contract = root / ".agents/project.json"
            authored = json.loads(contract.read_text(encoding="utf-8"))
            authored["bindings"]["vcs"]["integration_branch"] = "main: x"
            contract.write_text(json.dumps(authored, indent=2), encoding="utf-8")
            self.write_workflow(root, b"anything\n")
            code, report = self.ci(root)
            self.assertEqual(code, 1)
            check = {c["id"]: c for c in report["checks"]}[self.CHECK_ID]
            self.assertEqual(
                [check["status"], check["facts"]],
                ["failed", {"target": self.TARGET, "state": "unrenderable"}])

    def test_ci_and_doctor_select_it_and_adoption_and_fleet_do_not(self):
        selected = {}
        for purpose in ("ci", "doctor", "adoption", "fleet"):
            with fixture() as tmp:
                code, out, err = run("run", "--purpose", purpose, "--repo-root",
                                     str(make_root(tmp)))
                self.assertEqual(code, 0, err)
                selected[purpose] = self.CHECK_ID in [
                    c["id"] for c in json.loads(out)["checks"]]
        self.assertEqual(selected, {"ci": True, "doctor": True,
                                    "adoption": False, "fleet": False})

    def test_a_declared_workflow_projection_passes_doctor(self):
        with fixture() as tmp:
            root = make_root(tmp)
            contract = root / ".agents/project.json"
            authored = json.loads(contract.read_text(encoding="utf-8"))
            authored["projections"].append({
                "id": "conformance.workflow", "kind": "conformance_workflow",
                "target": self.TARGET})
            contract.write_text(json.dumps(authored, indent=2), encoding="utf-8")
            self.write_workflow(
                root, resolve_project.render_conformance_workflow("main", 2))
            report, by_id = doctor(self, root)
            for check_id in ("repository.projection.fresh",
                             "repository.paths.classified",
                             "host.policy_path.no_follow_readable",
                             self.CHECK_ID):
                self.assertEqual(by_id[check_id]["status"], "passed", check_id)


def make_run(root: Path, worktree: str, run_id: str, states: list, *,
             lock: bool = True, results: bool = True,
             ledger: str | None = None) -> Path:
    """A nested ledger run directory, by default a removable one.

    `lock` writes the canonical state.lock, `results` gives each terminal
    attempt a matching durable result, and `ledger` replaces the state.json
    bytes outright. A removable run needs all of them (D34).
    """
    run = root / ".worktrees" / worktree / ".superpowers" / "workflows" / run_id
    run.mkdir(parents=True)
    attempts = [{"state": s,
                 "result": {"state": s} if results else None} for s in states]
    run.joinpath("state.json").write_text(
        ledger if ledger is not None
        else json.dumps({"issues": {"1": {"attempts": attempts}}}),
        encoding="utf-8")
    if lock:
        run.joinpath("state.lock").write_bytes(b"")
    return run


class NeverRiseCheckTest(ReportAssertions, unittest.TestCase):
    """The never-rise check, judged through one `ci` run on a committed root
    whose integration ref the fixture moves (#1455)."""

    CHECK_ID = "verification.violations.never_rise"

    def ci(self, root: Path) -> tuple[int, dict, dict]:
        code, out, err = run("run", "--purpose", "ci", "--repo-root", str(root))
        self.assertIn(code, (0, 1), err)
        report = json.loads(out)
        return code, report, {c["id"]: c for c in report["checks"]}

    def summary(self, check: dict) -> list:
        return [check["status"], check["reason_code"], check["repair_id"],
                check["facts"]]

    def big_base(self, root: Path) -> str:
        """A 1,600-line file committed and made the integration tip; its sha."""
        write_file(root, "src/big.py", "x = 1\n" * 1600)
        commit_all(root, "big")
        git(root, "update-ref", INTEGRATION_REF, "HEAD")
        return git(root, "rev-parse", "HEAD").strip()

    def test_a_grown_over_budget_file_turns_ci_red_and_names_the_rule(self):
        with fixture() as tmp:
            root = make_root(tmp)
            base = self.big_base(root)
            with (root / "src/big.py").open("a", encoding="utf-8") as handle:
                handle.write("x = 1\n")
            commit_all(root, "grow")
            code, report, by_id = self.ci(root)
            self.assertEqual(code, 1)
            self.assertEqual(report["outcome"], {
                "status": "failed", "primary_check_id": self.CHECK_ID})
            self.assertEqual(
                self.summary(by_id[self.CHECK_ID]),
                ["failed", "violation_count_rose", "violations.never_rise.reduce",
                 {"merge_base": base, "rule": "B17", "base_count": 1,
                  "branch_count": 1, "violations": ["B17 src/big.py:1601"],
                  "rules": ["B17"]}])
            self.assert_validates(report)

    def test_a_tree_level_with_its_merge_base_passes_ci(self):
        with fixture() as tmp:
            root = make_root(tmp)
            code, report, by_id = self.ci(root)
            self.assertEqual(code, 0)
            self.assertEqual(
                self.summary(by_id[self.CHECK_ID]),
                ["passed", None, None,
                 {"merge_base": git(root, "rev-parse", "HEAD").strip()}])

    def test_a_missing_integration_ref_is_a_failed_check(self):
        with fixture() as tmp:
            root = make_root(tmp)
            git(root, "update-ref", "-d", INTEGRATION_REF)
            code, report, by_id = self.ci(root)
            self.assertEqual(code, 1)
            self.assertEqual(
                self.summary(by_id[self.CHECK_ID]),
                ["failed", "history_unavailable", "violations.history.fetch",
                 {"integration_branch": "main"}])
            self.assert_validates(report)

    def test_an_integration_branch_git_cannot_be_given_is_a_failed_check(self):
        with fixture() as tmp:
            root = make_root(tmp)
            contract = root / ".agents/project.json"
            authored = json.loads(contract.read_text(encoding="utf-8"))
            authored["bindings"]["vcs"]["integration_branch"] = "ma\x00in"
            contract.write_text(json.dumps(authored, indent=2), encoding="utf-8")
            code, report, by_id = self.ci(root)
            self.assertEqual(code, 1)
            self.assertEqual(
                self.summary(by_id[self.CHECK_ID])[:3],
                ["failed", "history_unavailable", "violations.history.fetch"])
            self.assert_validates(report)

    def test_an_uncommitted_growth_is_not_judged(self):
        with fixture() as tmp:
            root = make_root(tmp)
            self.big_base(root)
            with (root / "src/big.py").open("a", encoding="utf-8") as handle:
                handle.write("x = 1\n" * 10)
            code, _, by_id = self.ci(root)
            self.assertEqual(by_id[self.CHECK_ID]["status"], "passed")
            self.assertEqual(code, 0)

    def test_the_new_violations_are_bounded(self):
        with fixture() as tmp:
            root = make_root(tmp)
            for index in range(9):
                write_file(root, f"src/n{index}.py", "x = 1\n" * 1501)
            commit_all(root, "many")
            code, report, by_id = self.ci(root)
            self.assertEqual(code, 1)
            facts = by_id[self.CHECK_ID]["facts"]
            self.assertEqual([facts["base_count"], facts["branch_count"],
                              len(facts["violations"])], [0, 9, 8])
            self.assert_validates(report)

    def red(self, root: Path) -> dict:
        code, report, by_id = self.ci(root)
        self.assertEqual(code, 1)
        self.assert_validates(report)
        return by_id[self.CHECK_ID]

    def test_a_committed_todo_comment_turns_ci_red_naming_b20(self):
        with fixture() as tmp:
            root = make_root(tmp)
            base = git(root, "rev-parse", "refs/remotes/origin/main").strip()
            write_file(root, "src/todo.py", "x = 1\n# TODO: finish\n")
            commit_all(root, "todo")
            self.assertEqual(
                self.summary(self.red(root)),
                ["failed", "violation_count_rose", "violations.never_rise.reduce",
                 {"merge_base": base, "rule": "B20", "base_count": 0,
                  "branch_count": 1, "violations": ["B20 src/todo.py:2"],
                  "rules": ["B20"]}])

    def test_a_long_block_holding_a_fixme_turns_ci_red_naming_b19_and_b20(self):
        with fixture() as tmp:
            root = make_root(tmp)
            base = git(root, "rev-parse", "refs/remotes/origin/main").strip()
            write_file(root, "src/long.py",
                       "x = 1\n# a\n# FIXME: b\n# c\n# d\n# e\n# f\n")
            commit_all(root, "long")
            self.assertEqual(
                self.summary(self.red(root)),
                ["failed", "violation_count_rose", "violations.never_rise.reduce",
                 {"merge_base": base, "rule": "B19", "base_count": 0,
                  "branch_count": 1, "violations": ["B19 src/long.py:2"],
                  "rules": ["B19", "B20"]}])

    def test_a_link_to_the_contracts_own_tracker_turns_ci_red_naming_b18(self):
        with fixture() as tmp:
            root = make_root(tmp)
            contract = root / ".agents/project.json"
            authored = json.loads(contract.read_text(encoding="utf-8"))
            other = authored["bindings"]["tracker"]["repo_slug"]
            authored["bindings"]["tracker"]["repo_slug"] = "fixture-owner/fixture-repo"
            targets = authored["release"]["profiles"]["github-release"]["bindings"]["targets"]
            targets["repository"]["repository"] = "fixture-owner/fixture-repo"
            contract.write_text(json.dumps(authored, indent=2), encoding="utf-8")
            write_file(root, "src/ref.py",
                       "x = 1\n# https://github.com/fixture-owner/fixture-repo/issues/7\n"
                       + f"# https://github.com/{other}/issues/7\n")
            commit_all(root, "ref")
            facts = self.red(root)["facts"]
            self.assertEqual(facts["rule"], "B18")
            self.assertEqual(facts["violations"], ["B18 src/ref.py:2"])


class LintChecksTest(ReportAssertions, unittest.TestCase):
    """The context-map lint and the standards lint, each run in process by the
    engine and judged through one `ci` run (#1452 D4, D5, D7). A diagnostic is
    raw text, so only its repo-relative label ever becomes a fact."""

    MAP_ID = "verification.context_map.lint"
    STANDARDS_ID = "verification.standards.lint"
    MAP_REPAIR = "docs.context_map.repair"

    def ci(self, root: Path, env: dict | None = None) -> tuple[int, dict, dict]:
        code, out, err = run("run", "--purpose", "ci", "--repo-root", str(root),
                             env=env)
        self.assertIn(code, (0, 1), err)
        report = json.loads(out)
        return code, report, {c["id"]: c for c in report["checks"]}

    def summary(self, check: dict) -> list:
        return [check["status"], check["reason_code"], check["repair_id"],
                check["facts"]]

    def edit_contract(self, root: Path, mutate) -> None:
        contract = root / ".agents/project.json"
        authored = json.loads(contract.read_text(encoding="utf-8"))
        mutate(authored)
        contract.write_text(json.dumps(authored, indent=2), encoding="utf-8")

    def set_context(self, root: Path, entries: list) -> None:
        self.edit_contract(
            root, lambda a: a["bindings"]["paths"].__setitem__("context", entries))
        for entry in entries:
            if Path(entry).name == "CONTEXT-MAP.md":
                write_clean_map(root / entry)
            else:
                write_file(root, entry, "")

    def test_a_broken_context_map_turns_ci_red_and_names_the_check(self):
        with fixture() as tmp:
            root = make_root(tmp)
            write_file(root, "docs/CONTEXT-MAP.md", "")
            code, report, by_id = self.ci(root)
            self.assertEqual(code, 1)
            self.assertEqual(report["outcome"], {
                "status": "failed", "primary_check_id": self.MAP_ID})
            self.assertEqual(
                self.summary(by_id[self.MAP_ID]),
                ["failed", "context_map_lint_failed", self.MAP_REPAIR,
                 {"paths": ["docs/CONTEXT-MAP.md"], "count": 1}])
            self.assert_validates(report)

    def test_a_broken_standards_tree_turns_ci_red_and_names_the_check(self):
        with fixture() as tmp:
            root = make_root(tmp)
            write_file(root, "docs/standards/orphan.md", "# Orphan\n")
            code, report, by_id = self.ci(root)
            self.assertEqual(code, 1)
            self.assertEqual(report["outcome"], {
                "status": "failed", "primary_check_id": self.STANDARDS_ID})
            check = by_id[self.STANDARDS_ID]
            self.assertEqual(check["status"], "failed")
            self.assertEqual([check["reason_code"], check["repair_id"]],
                             ["standards_lint_failed", "docs.standards.repair"])
            self.assertEqual(
                check["facts"],
                conformance_lint_facts(standards_lint.lint(root, STANDARDS)))
            self.assertIn("docs/standards/README.md", check["facts"]["paths"])
            self.assert_validates(report)

    def test_a_clean_tree_passes_both_lints_and_ci_exits_zero(self):
        with fixture() as tmp:
            root = make_root(tmp)
            self.assertEqual(
                context_map_lint.check(root, root / "docs/CONTEXT-MAP.md"), [])
            code, report, by_id = self.ci(root)
            self.assertEqual(code, 0)
            self.assertEqual(report["outcome"]["status"], "passed")
            for check_id in (self.MAP_ID, self.STANDARDS_ID):
                self.assertEqual([by_id[check_id]["status"],
                                  by_id[check_id]["facts"]], ["passed", {}])

    def test_an_area_context_file_beside_the_map_is_not_linted_as_a_map(self):
        with fixture() as tmp:
            root = make_root(tmp)
            self.set_context(root, ["docs/CONTEXT-MAP.md",
                                    "docs/areas/backlog/CONTEXT.md",
                                    "docs/areas/system/CONTEXT.md"])
            # With `docs/areas` present the lint also checks the layout, so the
            # map names both areas and each area file carries its front matter;
            # neither area file holds an `## Areas` table, so linting one as a
            # map would report `no '## Areas' table found`.
            rows = "".join(
                f"| {name} | [CONTEXT](./areas/{name.lower()}/CONTEXT.md) | "
                f"The {name} area | `.agents/project.json` |\n"
                for name in ("Backlog", "System"))
            write_file(root, "docs/CONTEXT-MAP.md", CLEAN_MAP.split("| Fixture")[0]
                       + rows + "\n## Terms\n\n| Term | Area |\n|---|---|\n")
            (root / "docs/fixture-CONTEXT.md").unlink()
            for name in ("Backlog", "System"):
                write_file(root, f"docs/areas/{name.lower()}/CONTEXT.md",
                           f"---\narea: {name}\nbudget: 20 lines\n---\n\n# {name}\n")
            self.assertEqual(
                context_map_lint.check(root, root / "docs/CONTEXT-MAP.md"), [])
            code, _, by_id = self.ci(root)
            self.assertEqual(code, 0)
            self.assertEqual([by_id[self.MAP_ID]["status"],
                              by_id[self.MAP_ID]["facts"]], ["passed", {}])

    def test_no_map_entry_means_no_lint(self):
        for label in ("area file only", "no entries"):
            with self.subTest(context=label), fixture() as tmp:
                root = make_root(tmp)
                if label == "area file only":
                    self.set_context(root, ["docs/areas/backlog/CONTEXT.md"])
                else:
                    self.set_context(root, [])
                    self.edit_contract(
                        root, lambda a: a["capabilities"]["knowledge.context"]
                        .__setitem__("support", "unsupported"))
                code, _, by_id = self.ci(root)
                self.assertEqual(code, 0)
                self.assertEqual([by_id[self.MAP_ID]["status"],
                                  by_id[self.MAP_ID]["facts"]], ["passed", {}])

    def test_two_maps_are_an_ambiguous_contract(self):
        with fixture() as tmp:
            root = make_root(tmp)
            self.set_context(root, ["docs/CONTEXT-MAP.md",
                                    "docs/other/CONTEXT-MAP.md"])
            code, report, by_id = self.ci(root)
            self.assertEqual(code, 1)
            self.assertEqual(report["outcome"], {
                "status": "failed", "primary_check_id": self.MAP_ID})
            self.assertEqual(
                self.summary(by_id[self.MAP_ID]),
                ["failed", "context_map_ambiguous", self.MAP_REPAIR,
                 {"paths": ["docs/CONTEXT-MAP.md", "docs/other/CONTEXT-MAP.md"],
                  "count": 2}])

    def write_marker_lint(self, tmp: Path, root: Path) -> dict:
        """A `map-lint` on PATH that would leave a marker inside and outside."""
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        script = bin_dir / "map-lint"
        script.write_text(
            f"#!/bin/sh\n: > {root}/inside-marker\n: > {tmp}/outside-marker\n",
            encoding="utf-8")
        script.chmod(0o755)
        self.edit_contract(root, lambda a: a["bindings"]["commands"].__setitem__(
            "context-map-lint", {"argv": ["map-lint"], "cwd": ".", "env": []}))
        return {**HERMETIC_ENV,
                "PATH": os.pathsep.join([str(bin_dir), HERMETIC_ENV["PATH"]])}

    def test_a_declared_repository_lint_is_delegated_and_never_run(self):
        with fixture() as tmp:
            root = make_root(tmp)
            write_file(root, "docs/CONTEXT-MAP.md", "")
            env = self.write_marker_lint(tmp, root)
            code, report, by_id = self.ci(root, env)
            self.assertEqual(code, 0)
            self.assertEqual(report["outcome"]["status"], "passed")
            self.assertEqual(
                self.summary(by_id[self.MAP_ID]),
                ["warning", "context_map_lint_delegated",
                 "docs.context_map.run_repository_lint",
                 {"command": "context-map-lint"}])
            self.assertFalse((root / "inside-marker").exists())
            self.assertFalse((tmp / "outside-marker").exists())

    def test_an_unreadable_map_or_shard_is_a_finding_not_a_refusal(self):
        with fixture() as tmp:
            root = make_root(tmp)
            (root / "docs/CONTEXT-MAP.md").write_bytes(b"\xff\xfe\n")
            code, report, by_id = self.ci(root)
            self.assertEqual(code, 1)
            self.assertEqual(report["outcome"]["primary_check_id"], self.MAP_ID)
            self.assertEqual(
                self.summary(by_id[self.MAP_ID]),
                ["failed", "context_map_unreadable", self.MAP_REPAIR,
                 {"paths": ["docs/CONTEXT-MAP.md"], "count": 1}])
            self.assert_validates(report)
        with fixture() as tmp:
            root = make_root(tmp)
            (root / "docs/standards").mkdir(parents=True, exist_ok=True)
            (root / "docs/standards/bad.md").write_bytes(b"\xff\n")
            with self.assertRaises(UnicodeDecodeError):
                standards_lint.lint(root, STANDARDS)
            code, report, by_id = self.ci(root)
            self.assertEqual(code, 1)
            self.assertEqual(report["outcome"]["primary_check_id"],
                             self.STANDARDS_ID)
            check = by_id[self.STANDARDS_ID]
            self.assertEqual([check["status"], check["reason_code"]],
                             ["failed", "standards_unreadable"])
            self.assert_validates(report)

    def test_an_absolute_governs_glob_is_a_finding_not_a_refusal(self):
        with fixture() as tmp:
            root = make_root(tmp)
            write_file(root, "docs/CONTEXT-MAP.md", CLEAN_MAP.replace(
                "`.agents/project.json`", "`/etc/*`"))
            code, report, by_id = self.ci(root)
            self.assertEqual(code, 1)
            self.assertEqual(report["outcome"]["primary_check_id"], self.MAP_ID)
            self.assertEqual(
                self.summary(by_id[self.MAP_ID]),
                ["failed", "context_map_lint_failed", self.MAP_REPAIR,
                 {"paths": ["docs/CONTEXT-MAP.md"], "count": 1}])
            self.assert_validates(report)

    def test_a_map_resolving_outside_the_root_is_not_read(self):
        with fixture() as tmp:
            root = make_root(tmp)
            outside = tmp / "outside" / "CONTEXT-MAP.md"
            write_clean_map(outside)
            (root / "docs/CONTEXT-MAP.md").unlink()
            (root / "docs/CONTEXT-MAP.md").symlink_to(outside)
            code, _, by_id = self.ci(root)
            self.assertEqual(code, 1)
            self.assertEqual(
                self.summary(by_id[self.MAP_ID]),
                ["failed", "context_map_outside_root", self.MAP_REPAIR,
                 {"paths": ["docs/CONTEXT-MAP.md"], "count": 1}])

    def test_an_area_file_outside_the_root_is_a_finding_and_is_never_read(self):
        for label, link in (("relative", "../../outside/CONTEXT.md"),
                            ("absolute", None)):
            with self.subTest(link=label), fixture() as tmp:
                root = make_root(tmp)
                outside = tmp / "outside" / "CONTEXT.md"
                write_file(tmp, "outside/CONTEXT.md", "no front matter\n")
                write_file(root, "docs/CONTEXT-MAP.md", CLEAN_MAP.replace(
                    "./fixture-CONTEXT.md", link or str(outside)))
                opened = []
                original = Path.read_text

                def recording(path, *args, **kwargs):
                    opened.append(Path(path).resolve())
                    return original(path, *args, **kwargs)

                with unittest.mock.patch.object(Path, "read_text", recording):
                    problems = context_map_lint.check(
                        root, root / "docs/CONTEXT-MAP.md")
                self.assertNotIn(outside.resolve(), opened)
                self.assertTrue(
                    any("outside the repository" in problem
                        for problem in problems), problems)
                code, _, by_id = self.ci(root)
                self.assertEqual(code, 1)
                self.assertEqual(
                    self.summary(by_id[self.MAP_ID]),
                    ["failed", "context_map_lint_failed", self.MAP_REPAIR,
                     {"paths": ["docs/CONTEXT-MAP.md"], "count": len(problems)}])

    def test_a_docs_areas_symlinked_outside_the_root_is_a_finding_and_is_never_read(self):
        with fixture() as tmp:
            root = make_root(tmp)
            write_file(tmp, "host/secret/adr/001-a.md", "# ADR-secret-001 — A\n")
            write_file(tmp, "host/other/private.md", "private\n")
            areas = root / "docs/areas"
            if areas.is_symlink() or areas.is_file():
                areas.unlink()
            elif areas.is_dir():
                shutil.rmtree(areas)
            areas.symlink_to(tmp / "host")
            opened = []
            original = Path.read_text

            def recording(path, *args, **kwargs):
                opened.append(Path(path).resolve())
                return original(path, *args, **kwargs)

            with unittest.mock.patch.object(Path, "read_text", recording):
                problems = context_map_lint.check(
                    root, root / "docs/CONTEXT-MAP.md")
            host = (tmp / "host").resolve()
            self.assertEqual(
                [path for path in opened if host in path.parents], [])
            self.assertTrue(
                any("resolves outside the repository" in problem
                    for problem in problems), problems)
            self.assertFalse(
                any(str(tmp) in problem for problem in problems), problems)

    def test_a_link_under_docs_to_the_outside_is_a_finding_and_is_never_read(self):
        def link_area(root, tmp):
            write_file(tmp, "host/slug/adr/001-a.md", "# ADR-slug-001 — A\n")
            (root / "docs/areas/slug").symlink_to(tmp / "host/slug")

        def link_record(root, tmp):
            write_file(tmp, "host/secret.md", "# ADR-real-001 — A\n")
            (root / "docs/areas/real/adr").mkdir(parents=True)
            (root / "docs/areas/real/adr/001-a.md").symlink_to(
                tmp / "host/secret.md")

        def link_adr_dir(root, tmp):
            write_file(tmp, "host/adr/001-a.md", "# ADR-real-001 — A\n")
            (root / "docs/areas/real").mkdir(parents=True)
            (root / "docs/areas/real/adr").symlink_to(tmp / "host/adr")

        def link_doc(root, tmp):
            write_file(tmp, "host/leak.md", "ADR-nope-001\n")
            (root / "docs/leak.md").symlink_to(tmp / "host/leak.md")

        def link_readme(root, tmp):
            write_file(tmp, "host/readme.md", "leaks/\n")
            (root / "docs/README.md").symlink_to(tmp / "host/readme.md")

        for case in (link_area, link_record, link_adr_dir, link_doc,
                     link_readme):
            with self.subTest(case=case.__name__), fixture() as tmp:
                root = make_root(tmp)
                (root / "docs/areas").mkdir(parents=True, exist_ok=True)
                readme = root / "docs/README.md"
                if case is link_readme and readme.exists():
                    readme.unlink()
                case(root, tmp)
                opened = []
                original = Path.read_text

                def recording(path, *args, **kwargs):
                    opened.append(Path(path).resolve())
                    return original(path, *args, **kwargs)

                with unittest.mock.patch.object(Path, "read_text", recording):
                    problems = context_map_lint.check(
                        root, root / "docs/CONTEXT-MAP.md")
                host = (tmp / "host").resolve()
                self.assertEqual(
                    [path for path in opened if host in path.parents], [])
                leaks = [problem for problem in problems
                         if "resolves outside the repository" in problem]
                self.assertEqual(len(leaks), 1, problems)
                self.assertFalse(
                    any(str(tmp) in problem or "host" in problem
                        for problem in leaks), leaks)

    def test_lint_facts_carry_no_absolute_path_or_authored_text(self):
        with self.subTest(case="long path"), fixture() as tmp:
            root = make_root(tmp)
            long_entry = "docs/" + "a" * 230 + "/CONTEXT-MAP.md"
            self.set_context(root, [long_entry])
            write_file(root, long_entry, "")
            _, report, by_id = self.ci(root)
            for value in by_id[self.MAP_ID]["facts"].values():
                for text in (value if isinstance(value, list) else [value]):
                    if isinstance(text, str):
                        self.assertLessEqual(len(text), 200)
            self.assert_validates(report)
        with self.subTest(case="absolute diagnostic"), fixture() as tmp:
            root = make_root(tmp)
            write_file(tmp, "outside/CONTEXT.md", "no front matter\n")
            write_file(root, "docs/CONTEXT-MAP.md", CLEAN_MAP.replace(
                "./fixture-CONTEXT.md", "../../outside/CONTEXT.md")
                       + "\n[broken](./missing.md)\n")
            problems = context_map_lint.check(root, root / "docs/CONTEXT-MAP.md")
            self.assertTrue(any(str(tmp) in problem for problem in problems),
                            problems)
            _, _, by_id = self.ci(root)
            facts = by_id[self.MAP_ID]["facts"]
            self.assertNotIn(str(tmp), json.dumps(facts))
            self.assertIn("docs/CONTEXT-MAP.md", facts["paths"])
        with self.subTest(case="authored line"), fixture() as tmp:
            root = make_root(tmp)
            write_file(root, "docs/standards/rules.md",
                       "# Rules\n\n1. AUTHORED-LINE-MARKER\n")
            problems = standards_lint.lint(root, STANDARDS)
            self.assertTrue(
                any("AUTHORED-LINE-MARKER" in problem for problem in problems),
                problems)
            _, _, by_id = self.ci(root)
            self.assertEqual(by_id[self.STANDARDS_ID]["status"], "failed")
            self.assertNotIn("AUTHORED-LINE-MARKER",
                             json.dumps(by_id[self.STANDARDS_ID]["facts"]))

    def test_a_missing_platform_standards_directory_is_its_own_finding(self):
        with fixture() as tmp:
            env = platform_env(tmp, standards=None)
            _, by_id = doctor(self, make_root(tmp), env=env)
            self.assertEqual(
                self.summary(by_id[self.STANDARDS_ID]),
                ["failed", "platform_standards_missing",
                 "platform.standards.install", {}])

    def test_ci_and_doctor_select_both_and_adoption_and_fleet_do_not(self):
        selected = {}
        for purpose in ("ci", "doctor", "adoption", "fleet"):
            with fixture() as tmp:
                code, out, err = run("run", "--purpose", purpose, "--repo-root",
                                     str(make_root(tmp)))
                self.assertEqual(code, 0, err)
                ids = [c["id"] for c in json.loads(out)["checks"]]
                selected[purpose] = (self.MAP_ID in ids, self.STANDARDS_ID in ids)
        self.assertEqual(selected, {
            "ci": (True, True), "doctor": (True, True),
            "adoption": (False, False), "fleet": (False, False)})


class NestedLedgerResidueTest(ReportAssertions, unittest.TestCase):
    """AC5: orphaned ledgers are reported with non-destructive repairs unless a
    lock proves no live owner."""

    CHECK_ID = "repository.residue.nested_ledger"
    RETAIN_ID = "lifecycle.residue.nested_ledger.retain"
    REMOVE_ID = "lifecycle.residue.nested_ledger.remove"

    def check(self, root):
        return doctor(self, root)[1][self.CHECK_ID]

    def test_a_locked_merged_run_with_results_is_removable(self):
        with fixture() as tmp:
            root = make_root(tmp)
            make_run(root, "worktree-a", "run-1", ["merged"])
            report, by_id = doctor(self, root)
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["status"], check["reason_code"], check["repair_id"]],
                ["warning", "terminal_residue", self.REMOVE_ID])
            self.assertEqual(check["facts"]["runs"],
                             [".worktrees/worktree-a/.superpowers/workflows/run-1"])
            self.assertEqual([check["facts"]["terminal"],
                              check["facts"]["live_owner"]], [1, 0])
            self.assertEqual(
                {r["repair_id"]: r for r in report["repairs"]}[
                    self.REMOVE_ID]["safety_class"],
                "worktree")
            self.assert_validates(report)

    def test_neither_proof_alone_makes_a_run_removable(self):
        """D34: a missing lock, a missing result, a mismatched result, a
        non-merged state and a malformed ledger are all unacknowledged."""
        cases = {
            "no_lock": dict(states=["merged"], lock=False),
            "no_result": dict(states=["merged"], results=False),
            "not_merged": dict(states=["merged", "failed"]),
            "still_active": dict(states=["active"], results=False),
            "malformed": dict(states=["merged"], ledger="{ broken"),
            "mismatched": dict(states=["merged"],
                               ledger=json.dumps({"issues": {"1": {"attempts": [
                                   {"state": "merged",
                                    "result": {"state": "stopped"}}]}}})),
        }
        for name, kwargs in cases.items():
            with self.subTest(case=name), fixture() as tmp:
                root = make_root(tmp)
                make_run(root, "worktree-a", "run-1", **kwargs)
                check = self.check(root)
                self.assertEqual(
                    [check["reason_code"], check["repair_id"],
                     check["facts"]["terminal"]],
                    ["unacknowledged_residue", self.RETAIN_ID, 0])

    def test_a_held_lock_reports_live_owner_and_outranks_terminal_residue(self):
        """The kernel, not a sleep, proves the live owner (D16)."""
        with fixture() as tmp:
            root = make_root(tmp)
            make_run(root, "worktree-a", "run-1", ["merged"])
            live = make_run(root, "worktree-b", "run-2", ["active"], results=False)
            fd = os.open(live / "state.lock", os.O_RDONLY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                report, by_id = doctor(self, root)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["status"], check["reason_code"], check["repair_id"]],
                ["warning", "live_owner", self.RETAIN_ID])
            self.assertEqual([check["facts"]["live_owner"],
                              check["facts"]["count"]], [1, 2])
            self.assertEqual(
                {r["repair_id"]: r for r in report["repairs"]}[
                    self.RETAIN_ID]["safety_class"],
                "user_action")
            self.assert_validates(report)

    def test_the_lock_is_released_and_never_created(self):
        """The probe writes nothing: an unlocked run stays unlocked, and the
        lock the engine did take is free again once the run has finished."""
        with fixture() as tmp:
            root = make_root(tmp)
            unlocked = make_run(root, "worktree-a", "run-1", ["merged"],
                                lock=False)
            locked = make_run(root, "worktree-b", "run-2", ["merged"])
            doctor(self, root)
            self.assertFalse((unlocked / "state.lock").exists())
            fd = os.open(locked / "state.lock", os.O_RDONLY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def test_no_worktrees_passes(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp))
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["domain"], check["subject_kind"], check["requirement"],
                 check["status"], check["reason_code"], check["repair_id"],
                 check["facts"]],
                ["repository", "residue", "optional", "passed", None, None, {}])
            self.assert_validates(report)

    def test_residue_never_drives_the_outcome_to_failed(self):
        """D8: a warning is recorded with its repair and left out of the
        outcome, so a machine holding residue is not a broken repository."""
        with fixture() as tmp:
            root = make_root(tmp)
            make_run(root, "worktree-a", "run-1", ["failed"])
            report, by_id = doctor(self, root)
            self.assertEqual(by_id[self.CHECK_ID]["status"], "warning")
            self.assertEqual(report["outcome"],
                             {"status": "passed", "primary_check_id": None})
            self.assert_validates(report)

    def test_no_repair_in_the_report_is_destructive(self):
        """D10: v1 satisfies the cleanup rule by never reaching for the
        exemption — no repair it can emit carries `destructive`."""
        with fixture() as tmp:
            root = make_root(tmp)
            make_run(root, "worktree-a", "run-1", ["merged"])
            write_file(root, "producer-report-abc123.json", "{}\n")
            report, _ = doctor(self, root)
            self.assertTrue(report["repairs"])
            self.assertNotIn("destructive",
                             [r["safety_class"] for r in report["repairs"]])
            self.assert_validates(report)

    def test_an_unlistable_worktree_root_yields_no_runs_rather_than_an_error(self):
        """D19, D32: `Path.is_dir` swallows an OSError and answers False, so it
        never protects the listing after it. One unreadable directory must not
        turn a whole doctor run into `resolver_failure` with no report."""
        with fixture() as tmp:
            root = make_root(tmp)
            make_run(root, "worktree-a", "run-1", ["merged"])
            worktrees = root / ".worktrees"
            worktrees.chmod(0o000)
            try:
                if os.access(worktrees, os.R_OK):  # root, or a mode-less fs
                    self.skipTest("mode bits do not restrict this process")
                report, by_id = doctor(self, root)
            finally:
                worktrees.chmod(0o755)
            check = by_id[self.CHECK_ID]
            self.assertEqual([check["status"], check["reason_code"],
                              check["facts"]], ["passed", None, {}])
            self.assert_validates(report)


class RootScratchResidueTest(ReportAssertions, unittest.TestCase):
    """Scratch that escaped $TMPDIR into the repository root. The pattern set is
    a constant, so the check still reports on an invalid contract."""

    CHECK_ID = "repository.residue.root_scratch"
    REPAIR_ID = "lifecycle.residue.root_scratch"

    def test_root_scratch_is_named_with_its_worktree_repair(self):
        with fixture() as tmp:
            root = make_root(tmp)
            write_file(root, "producer-report-abc123.json", "{}\n")
            write_file(root, "brief.tmp.AbC123")
            report, by_id = doctor(self, root)
            check = by_id[self.CHECK_ID]
            self.assertEqual(
                [check["domain"], check["subject_kind"], check["requirement"],
                 check["status"], check["reason_code"], check["repair_id"]],
                ["repository", "residue", "optional", "warning",
                 "root_scratch_present", self.REPAIR_ID])
            self.assertEqual(
                check["facts"],
                {"files": ["brief.tmp.AbC123", "producer-report-abc123.json"],
                 "count": 2})
            repair = {r["repair_id"]: r for r in report["repairs"]}[self.REPAIR_ID]
            self.assertEqual(
                [repair["module"], repair["safety_class"], repair["operation"]],
                ["conformance", "worktree", None])
            self.assert_validates(report)

    def test_a_clean_root_passes(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp))
            check = by_id[self.CHECK_ID]
            self.assertEqual([check["status"], check["reason_code"],
                              check["repair_id"], check["facts"]],
                             ["passed", None, None, {}])
            self.assert_validates(report)

    def test_an_invalid_contract_does_not_suppress_it(self):
        """It depends only on `repository.contract.present`, so it still reports
        where a contract-derived sibling is suppressed."""
        with fixture() as tmp:
            root = make_root(tmp)
            contract = root / ".agents/project.json"
            authored = json.loads(contract.read_text(encoding="utf-8"))
            authored["bindings"]["extra"] = True
            contract.write_text(json.dumps(authored, indent=2), encoding="utf-8")
            write_file(root, "producer-report-x.json", "{}\n")
            report, by_id = doctor(self, root)
            self.assertEqual(
                [by_id["repository.contract.valid"]["status"],
                 by_id["repository.paths.classified"]["status"],
                 by_id[self.CHECK_ID]["status"],
                 by_id[self.CHECK_ID]["reason_code"]],
                ["failed", "suppressed", "warning", "root_scratch_present"])
            self.assert_validates(report)

    def test_an_unlistable_root_yields_no_names_rather_than_an_error(self):
        """Traversable but unreadable (mode 0o111): the resolver still opens the
        contract by name while the root itself cannot be listed, so the check
        can only answer `passed` (D19, D32)."""
        with fixture() as tmp:
            root = make_root(tmp)
            write_file(root, "producer-report-x.json", "{}\n")
            root.chmod(0o111)
            try:
                if os.access(root, os.R_OK) or not os.access(root, os.X_OK):
                    self.skipTest("mode bits do not restrict this process")
                report, by_id = doctor(self, root)
            finally:
                root.chmod(0o755)
            check = by_id[self.CHECK_ID]
            self.assertEqual([check["status"], check["reason_code"],
                              check["facts"]], ["passed", None, {}])
            self.assert_validates(report)


class ScratchPatternConsistencyTest(unittest.TestCase):
    """D11: the engine holds the scratch policy and the tracked .gitignore is
    its backstop, so every pattern must appear in both."""

    def test_every_scratch_pattern_is_backstopped_by_the_tracked_gitignore(self):
        rules = {line.strip() for line
                 in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
        for pattern in load_module().CHECKS_MODULE.ROOT_SCRATCH_PATTERNS:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, rules)


# --------------------------------------------------------------------------
# The release-profile lint trio
# --------------------------------------------------------------------------


RELEASE_PROFILE_IDS = (
    "repository.release_profile.observation_deadline",
    "repository.release_profile.restore_anchor",
    "repository.release_profile.rolled_back_reachable",
)


class ReleaseProfileLintTest(ReportAssertions, unittest.TestCase):
    """AC2: the three prototype lint items are registered with declared subjects."""

    def test_all_three_are_registered_with_a_declared_subject(self):
        with fixture() as tmp:
            root = make_root(tmp)
            path = root / ".agents/project.json"
            contract = json.loads(path.read_text(encoding="utf-8"))
            contract["release"] = "unsupported"
            contract.pop("production", None)
            path.write_text(json.dumps(contract), encoding="utf-8")
            report, by_id = doctor(self, root)
            for check_id in RELEASE_PROFILE_IDS:
                with self.subTest(check=check_id):
                    check = by_id[check_id]
                    self.assertEqual(
                        [check["domain"], check["subject_kind"],
                         check["requirement"], check["status"],
                         check["reason_code"], check["facts"]],
                        ["repository", "release_profile", "optional", "not_run",
                         "subject_absent", {"declared": False}])
                    self.assertIsNotNone(check["repair_id"])
            self.assertEqual(report["outcome"],
                             {"status": "passed", "primary_check_id": None})
            repairs = {r["repair_id"]: r for r in report["repairs"]}
            for repair_id in ("release_profile.compensate.add",
                              "release_profile.materialize.add",
                              "release_profile.deadline.require"):
                self.assertEqual(repairs[repair_id]["safety_class"], "user_action")
                self.assertIsNone(repairs[repair_id]["operation"])
            self.assert_validates(report)


class ReleaseProfileChecksTest(ReportAssertions, unittest.TestCase):
    def doctor_with(self, profile):
        with fixture() as tmp:
            root = make_root(tmp)
            path = root / ".agents/project.json"
            contract = json.loads(path.read_text(encoding="utf-8"))
            contract["release"] = {"profiles": {"github-release": profile}}
            path.write_text(json.dumps(contract), encoding="utf-8")
            report, by_id = doctor(self, root)
            self.assert_validates(report)
            return by_id

    def test_an_admissible_profile_passes_all_three(self):
        by_id = self.doctor_with(release_fixture("github-release-profile.json"))
        for check_id in RELEASE_PROFILE_IDS:
            self.assertEqual([by_id[check_id]["status"], by_id[check_id]["facts"]],
                             ["passed", {"declared": True}])

    def test_nix_config_contract_passes_all_three(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp))
            self.assert_validates(report)
        for check_id in RELEASE_PROFILE_IDS:
            self.assertEqual(by_id[check_id]["status"], "passed", check_id)

    def test_each_rule_fails_its_own_check(self):
        missing = release_fixture("github-release-profile.json")
        del missing["publication"]["actions"][0]["observation_deadline_ms"]
        restorable = release_fixture("github-release-profile.json")
        restorable["recovery"]["units"]["tag"] = {
            "posture": "restorable", "anchor": {"target": "repository", "predicate": "p", "parameters": {}},
            "compatibility": {"predicate": "q", "parameters": {}},
            "edges": [{"action": "restore", "operation": "tag", "parameters": {}, "residue": None}]}
        for profile, check_id, reason in (
                (missing, "repository.release_profile.observation_deadline", "observation_deadline_optional"),
                (restorable, "repository.release_profile.rolled_back_reachable", "rolled_back_unreachable")):
            with self.subTest(check_id=check_id):
                check = self.doctor_with(profile)[check_id]
                self.assertEqual([check["status"], check["reason_code"], check["facts"]["profile_id"]],
                                 ["failed", reason, "github-release"])

    def test_restore_anchor_fails_through_the_s3_seam(self):
        """D20: forge declares no in_place operation, so only an injected descriptor reaches it."""
        checks = load_module().CHECKS_MODULE
        store = release_fixture("fixture-store-descriptor.json")
        self.addCleanup(setattr, checks, "RELEASE_DESCRIPTORS", checks.RELEASE_DESCRIPTORS)
        checks.RELEASE_DESCRIPTORS = {**checks.RELEASE_DESCRIPTORS, "fixture-store": store}
        profile = release_fixture("destroyed-anchor-profile.json")
        context = types.SimpleNamespace(contract={"release": {"profiles": {"restorable": profile}}})
        outcome = checks.check_release_profile_restore_anchor(context)
        self.assertEqual((outcome.status, outcome.reason_code), ("failed", "restore_anchor_destroyed"))

    def test_profile_unsupported_is_retired(self):
        registry = load_module().registry
        for check in registry.REGISTRY:
            self.assertNotIn("profile_unsupported", [code for code, _ in check.findings])


LEFTOVER = b"Investigate before changing.\n"
LEFTOVER_SHA = hashlib.sha256(LEFTOVER).hexdigest()
HERE = "fagenorn/nix-config"


# `make_root` already creates `docs/standards` (a standards knowledge path), so
# the leftover copies live under a directory the fixture does not own.
def promoted(root, duplicates, *, state="promoted", kind="promotion-candidate",
             name="c.json"):
    """A candidate file carrying only the members the evaluator reads."""
    target = root / ".agents/knowledge/promotions/candidates" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"kind": kind, "state": state,
                                  "local_duplicates": duplicates}), encoding="utf-8")
    return target


def dup(path="notes/lesson.md", sha=LEFTOVER_SHA, repository=HERE, disposition="remove"):
    return {"repository": repository, "path": path, "sha256": sha,
            "disposition": disposition}


class PromotedDuplicateResidueTest(ReportAssertions, unittest.TestCase):
    """#127 AC4: a promoted lesson's leftover local copy fails a required check."""

    CHECK_ID = "repository.residue.promoted_duplicate"
    REMOVE_ID = "promotion.duplicate.remove"
    RECONCILE_ID = "promotion.duplicate.reconcile"

    def judge(self, root):
        report, by_id = doctor(self, root)
        self.assert_validates(report)
        return report, by_id[self.CHECK_ID]

    def test_no_candidates_directory_passes_with_zero_facts(self):
        with fixture() as tmp:
            _, check = self.judge(make_root(tmp))
            self.assertEqual(
                [check["domain"], check["subject_kind"], check["requirement"],
                 check["status"], check["reason_code"], check["repair_id"], check["facts"]],
                ["repository", "residue", "required", "passed", None, None,
                 {"duplicates": [], "count": 0, "deferred_count": 0, "retained_count": 0}])

    def test_absent_foreign_and_retained_duplicates_pass_with_scope_facts(self):
        with fixture() as tmp:
            root = make_root(tmp)
            write_file(root, "notes/keep.md")
            promoted(root, [dup(), dup(repository="fagenorn/argus"),
                            dup("notes/keep.md", disposition="project_only_residue")])
            _, check = self.judge(root)
            self.assertEqual([check["status"], check["facts"]], ["passed", {
                "duplicates": [], "count": 0, "deferred_count": 1, "retained_count": 1}])

    def test_an_unchanged_leftover_fails_with_the_remove_repair(self):
        with fixture() as tmp:
            root = make_root(tmp)
            (root / "notes").mkdir()
            (root / "notes/lesson.md").write_bytes(LEFTOVER)
            promoted(root, [dup()])
            report, check = self.judge(root)
            self.assertEqual([check["status"], check["reason_code"], check["repair_id"],
                              check["facts"]["duplicates"], check["facts"]["count"]],
                             ["failed", "promoted_duplicate_present", self.REMOVE_ID,
                              ["notes/lesson.md"], 1])
            repair = {r["repair_id"]: r for r in report["repairs"]}[self.REMOVE_ID]
            self.assertEqual([repair["module"], repair["safety_class"], repair["operation"]],
                             ["promotion", "worktree", None])
            self.assertEqual(report["outcome"]["status"], "failed")

    def test_drift_outranks_presence(self):
        with fixture() as tmp:
            root = make_root(tmp)
            (root / "notes").mkdir()
            (root / "notes/lesson.md").write_bytes(LEFTOVER)
            (root / "notes/other.md").write_bytes(b"edited\n")
            promoted(root, [dup(), dup("notes/other.md")])
            report, check = self.judge(root)
            self.assertEqual([check["reason_code"], check["repair_id"],
                              check["facts"]["count"]],
                             ["promoted_duplicate_drifted", self.RECONCILE_ID, 2])
            repair = {r["repair_id"]: r for r in report["repairs"]}[self.RECONCILE_ID]
            self.assertEqual(repair["safety_class"], "user_action")

    def test_every_drift_shape_is_drifted(self):
        def other_bytes(root):
            (root / "notes/lesson.md").write_bytes(b"edited\n")

        def directory(root):
            (root / "notes/lesson.md").mkdir()

        def leaf_link(root):
            (root / "real.md").write_bytes(LEFTOVER)
            (root / "notes/lesson.md").symlink_to(root / "real.md")

        def parent_link(root):
            (root / "real").mkdir()
            (root / "real/lesson.md").write_bytes(LEFTOVER)
            (root / "notes").rmdir()
            (root / "notes").symlink_to(root / "real", target_is_directory=True)

        def leftover(root):
            (root / "notes/lesson.md").write_bytes(LEFTOVER)

        cases = {"other_bytes": (other_bytes, dup()), "null_digest": (leftover, dup(sha=None)),
                 "directory": (directory, dup()), "leaf_link": (leaf_link, dup()),
                 "parent_link": (parent_link, dup()),
                 "traversal": (leftover, dup("../outside.md")),
                 "absolute": (leftover, dup("/etc/hosts"))}
        for name, (make, entry) in cases.items():
            with self.subTest(case=name), fixture() as tmp:
                root = make_root(tmp)
                (root / "notes").mkdir()
                make(root)
                promoted(root, [entry])
                _, check = self.judge(root)
                self.assertEqual([check["status"], check["reason_code"]],
                                 ["failed", "promoted_duplicate_drifted"])

    def test_only_promoted_candidate_files_are_judged(self):
        with fixture() as tmp:
            root = make_root(tmp)
            (root / "notes").mkdir()
            (root / "notes/lesson.md").write_bytes(LEFTOVER)
            promoted(root, [dup()], state="authorized", name="a.json")
            promoted(root, [dup()], kind="promotion-evaluation", name="b.json")
            promoted(root, [dup()], name="c.txt")
            broken = root / ".agents/knowledge/promotions/candidates/d.json"
            broken.write_text("{ broken", encoding="utf-8")
            promoted(root, "not-a-list", name="e.json")
            promoted(root, ["not-an-object", {"path": "notes/lesson.md"}], name="f.json")
            _, check = self.judge(root)
            self.assertEqual([check["status"], check["facts"]["count"]], ["passed", 0])
