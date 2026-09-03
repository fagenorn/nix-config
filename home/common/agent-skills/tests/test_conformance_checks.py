"""Contract tests for the repository- and verification-domain evaluators.

Path classification, the runtime ignore sentinel, shell indirection, the two
residue checks and the release-profile lint trio, each judged through one
`doctor` run against a temporary root (D16). The ladder, the host domain and
the report schema are in test_conformance.py."""

from __future__ import annotations

import fcntl
import json
import os
import sys
import unittest
from pathlib import Path

# The suite modules are imported by path, so the tests directory is not
# already on sys.path; the shared support module lives beside them.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conformance_test_support import (  # noqa: E402
    REPO_ROOT, ReportAssertions, doctor, fixture, load_module, make_root, run,
)


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
            report, by_id = doctor(self, make_root(tmp))
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

    def test_a_declared_release_command_is_unsupported_not_absent(self):
        with fixture() as tmp:
            root = make_root(tmp)
            path = root / ".agents/project.json"
            contract = json.loads(path.read_text(encoding="utf-8"))
            contract["bindings"]["workflow"]["release"] = "codex-review"
            contract["capabilities"]["release"] = {"support": "supported"}
            path.write_text(json.dumps(contract), encoding="utf-8")
            report, by_id = doctor(self, root)
            for check_id in RELEASE_PROFILE_IDS:
                check = by_id[check_id]
                self.assertEqual([check["status"], check["reason_code"]],
                                 ["not_run", "profile_unsupported"])
                self.assertEqual(check["facts"], {"declared": True,
                                                  "release_command": "codex-review"})
            self.assertEqual(report["outcome"]["status"], "passed")
            self.assert_validates(report)

    def test_an_unknown_locator_state_raises(self):
        """S3: the closed-set default branch (D32)."""
        checks = load_module().CHECKS_MODULE
        original = checks.find_release_profile
        checks.find_release_profile = lambda _context: ("compiled", "x")
        self.addCleanup(setattr, checks, "find_release_profile", original)
        with self.assertRaises(ValueError):
            checks.check_release_profile_restore_anchor(object())
