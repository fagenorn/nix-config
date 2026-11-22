"""Contract tests for the readiness core, `agent_tools.project_contract.host_readiness` (issue 1382).

The core runs every readiness check for one resolved project and returns one
`Check` row per check. The cases pin the check ids and their order, the failure
details, the refusal gate that keeps a production command and a release run
from starting, the shared budget and its exit code, and the leashed runner.
The seams are `run_checks(snapshot, scratch, run=, on_path=, clock=, budget=)`
with a recording fake runner, a fake PATH lookup and a fake clock over a real
temporary scratch directory, plus `refusal`, `render`, `exit_code` and
`leashed_run` called directly (the last with real processes). The lifecycle
guard's source is loaded here, never by the package, to prove the core's argv
never hits its production rules.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shlex
import shutil
import stat
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Callable
from unittest import mock

from agent_tools.project_contract.host_readiness import (
    COMMIT_PROBE_MESSAGE,
    LOGIN_PROBES,
    VERIFICATION_LIMIT_SECONDS,
    Check,
    Completed,
    exit_code,
    leashed_run,
    refusal,
    render,
    run_checks,
)
from agent_tools.release import release_adapter
from agent_tools.system.siblings import sibling_argv

REPO_ROOT = Path(__file__).resolve().parents[4]
GUARD_SOURCE = REPO_ROOT / "home/common/claude-code/lifecycle_guard.py"
BASE = "b" * 40

INSPECTION = {
    "profile": {"admissible": True},
    "conformance": {"findings": [],
                    "adapters": {"forge": {"executables": {"gh": True, "git": True}}}},
    "bindings": {
        "adapters": {"forge": {"adapter": "github-forge", "config": {}}},
        "credentials": {"forge-keyring": {"adapter": "forge", "class": "gh_keyring"}},
    },
}


def fake_snapshot(root: Path, **over: Any) -> dict:
    """A resolved project: two verification commands, a production deploy and a release profile."""
    here = str(root)
    commands = {name: {"argv": argv, "cwd": here, "env": []} for name, argv in {
        "lint": ["just", "lint"], "test": ["just", "test"], "deploy": ["just", "switch"],
        "dry-run": ["just", "switch", "--dry-run"], "nix-build": ["just", "build"],
        "commit-environment": ["devenv", "shell", "--"]}.items()}
    snapshot: dict = {
        "project": {"id": "fagenorn/ready", "name": "ready", "root": here},
        "bindings": {
            "commands": commands,
            "vcs": {"integration_branch": "main", "default_branch": "main",
                    "commit": {"environment": "commit-environment"}},
            "workflow": {"verification": ["lint", "test"]},
        },
        "capabilities": {"release": {"state": "available", "reason_code": None, "repair_id": None}},
        "release": {"targets": [{"profile": "github-release", "adapter": "github-forge",
                                 "operations": ["release", "tag"], "target": {}}]},
        "production": {"status": "declared",
                       "changes": {"commands": ["deploy"], "key_files": [], "mcp_tools": []},
                       "read_only": {"commands": ["nix-build", "dry-run"], "mcp_tools": []},
                       "release_profile": "github-release"},
    }
    for path, value in over.items():
        node = snapshot
        *parents, last = path.split(".")
        for part in parents:
            node = node[part]
        node[last] = value
    return snapshot


class FakeRunner:
    """A recording `run` seam: overrides first, then defaults by argv content."""

    def __init__(self, common: Path, inspection: dict | None = None,
                 now: list[float] | None = None, step: float = 0.0) -> None:
        self.common = common
        self.inspection = INSPECTION if inspection is None else inspection
        self.now = now
        self.step = step
        self.calls: list[tuple[tuple[str, ...], Path, float]] = []
        self.overrides: list[tuple[Callable[[tuple[str, ...]], bool], Completed]] = []

    def when(self, predicate: Callable[[tuple[str, ...]], bool], answer: Completed) -> None:
        self.overrides.append((predicate, answer))

    def __call__(self, argv, cwd, timeout) -> Completed:
        argv = tuple(argv)
        self.calls.append((argv, Path(cwd), timeout))
        if self.now is not None:
            self.now[0] += self.step
        for predicate, answer in self.overrides:
            if predicate(argv):
                return answer
        return self.default(argv)

    def default(self, argv: tuple[str, ...]) -> Completed:
        if "get-url" in argv:
            return Completed(0, "/tmp/origin.git\n", "")
        if argv[:2] == ("git", "clone"):
            Path(argv[-1]).mkdir(parents=True, exist_ok=True)
            return Completed(0, "", "")
        if "--get" in argv and "config" in argv:
            return Completed(1, "", "")
        if "--git-common-dir" in argv:
            return Completed(0, f"{self.common}\n", "")
        if argv[-2:] == ("rev-parse", "HEAD"):
            return Completed(0, BASE + "\n", "")
        if "log" in argv and "-1" in argv:
            return Completed(0, f"{BASE}\n{COMMIT_PROBE_MESSAGE}\n", "")
        if "inspect" in argv and "profile" in argv:
            return Completed(0, json.dumps(self.inspection), "")
        if "preview" in argv and "transaction" in argv:
            return Completed(3, json.dumps({"error": {
                "code": "candidate_required", "repair_id": None,
                "detail": "a new release needs a candidate"}}), "")
        return Completed(0, "", "")

    def argvs(self) -> list[tuple[str, ...]]:
        return [call[0] for call in self.calls]


def refused_answer(code: str, **shape: Any) -> str:
    return json.dumps({"error": {"code": code, "repair_id": None, **shape}})


def ids(checks) -> list[str]:
    return [check.id for check in checks]


def line(checks, check_id: str) -> str:
    for text in render(checks).splitlines():
        if text.split(":")[0].split(" ", 1)[1] == check_id:
            return text
    raise AssertionError(f"no line for {check_id}: {render(checks)}")


class ReadinessCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.scratch = Path(tempfile.mkdtemp()).resolve()
        self.common = Path(tempfile.mkdtemp()).resolve()
        (self.common / "hooks").mkdir()
        self.clone = self.scratch / "checkout"
        for each in (self.root, self.scratch, self.common):
            self.addCleanup(shutil.rmtree, each, True)

    def run_it(self, snapshot=None, runner: FakeRunner | None = None, **kwargs):
        runner = runner or FakeRunner(self.common)
        kwargs.setdefault("on_path", lambda name: True)
        checks = run_checks(snapshot or fake_snapshot(self.root), self.scratch, run=runner, **kwargs)
        return checks, runner


class ReadinessChecksTest(ReadinessCase):
    def test_a_ready_project_reports_one_passing_line_per_check(self):
        checks, _ = self.run_it()
        self.assertEqual(
            ["checkout", "verification lint", "verification test", "commit-hook",
             "release-command", "release-profile github-release",
             "release-preview github-release", "release-login github-release forge-keyring"],
            ids(checks))
        self.assertTrue(all(check.passed for check in checks), render(checks))

    def test_a_failed_clone_fails_every_check_that_needs_the_checkout_and_still_runs_the_rest(self):
        runner = FakeRunner(self.common)
        runner.when(lambda argv: argv[:2] == ("git", "clone"),
                    Completed(128, "", "warning: x\nfatal: repository not found\n"))
        checks, _ = self.run_it(runner=runner)
        self.assertEqual("fail checkout: git clone of main exited 128: fatal: repository not found",
                         line(checks, "checkout"))
        for name in ("verification lint", "verification test", "commit-hook"):
            check = next(c for c in checks if c.id == name)
            self.assertEqual((False, "no clean checkout of main", False),
                             (check.passed, check.detail, check.spent))
        for name in ("release-command", "release-profile github-release",
                     "release-preview github-release",
                     "release-login github-release forge-keyring"):
            self.assertTrue(next(c for c in checks if c.id == name).passed, name)
        for argv in runner.argvs():
            self.assertNotEqual("just", argv[0])
            self.assertNotEqual(COMMIT_PROBE_MESSAGE, argv[-1])

    def test_a_failing_verification_command_names_its_exit_and_last_line(self):
        runner = FakeRunner(self.common)
        runner.when(lambda argv: argv == ("just", "test"),
                    Completed(1, "out\n", "test: run nix-build\ntest: failed: nix-build\n\n"))
        checks, _ = self.run_it(runner=runner)
        self.assertEqual("fail verification test: just test exited 1: test: failed: nix-build",
                         line(checks, "verification test"))
        self.assertEqual("pass verification lint", line(checks, "verification lint"))
        self.assertEqual(1, exit_code(checks))

    def test_a_verification_command_runs_in_the_clone_under_its_own_limit(self):
        snapshot = fake_snapshot(self.root, **{"bindings.vcs.integration_branch": "develop"})
        snapshot["bindings"]["commands"]["lint"]["cwd"] = str(self.root / "sub")
        (self.clone / "sub").mkdir(parents=True)
        checks, runner = self.run_it(snapshot)
        clones = [call for call in runner.calls if call[0][:2] == ("git", "clone")]
        self.assertEqual([(("git", "clone", "--quiet", "--no-tags", "--single-branch", "--branch",
                            "develop", "--", "/tmp/origin.git", str(self.clone)),
                           self.scratch, 600)], clones)
        lint = [call for call in runner.calls if call[0] == ("just", "lint")]
        self.assertEqual([(("just", "lint"), self.clone / "sub", VERIFICATION_LIMIT_SECONDS)], lint)
        self.assertEqual(3600, VERIFICATION_LIMIT_SECONDS)

    def test_a_directory_that_leaves_the_checkout_through_a_symlink_is_not_run(self):
        outside = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, outside, True)
        self.clone.mkdir()
        (self.clone / "esc").symlink_to(outside)
        with self.subTest("verification"):
            snapshot = fake_snapshot(self.root)
            snapshot["bindings"]["commands"]["lint"]["cwd"] = str(self.root / "esc")
            checks, runner = self.run_it(snapshot)
            self.assertEqual("fail verification lint: its directory esc is not inside the "
                             "clean checkout; not run", line(checks, "verification lint"))
            self.assertNotIn(("just", "lint"), runner.argvs())
            self.assertEqual([], list(outside.iterdir()))
        with self.subTest("commit environment"):
            snapshot = fake_snapshot(self.root)
            snapshot["bindings"]["commands"]["commit-environment"]["cwd"] = str(self.root / "esc")
            checks, runner = self.run_it(snapshot)
            self.assertEqual("fail commit-hook: the commit environment's directory esc is not "
                             "inside the clean checkout; not run", line(checks, "commit-hook"))
            for argv in runner.argvs():
                if "-C" in argv:
                    self.assertNotEqual("commit", argv[argv.index("-C") + 2])

    def test_the_commit_hook_runs_through_the_commit_environment_within_its_limit(self):
        snapshot = fake_snapshot(self.root)
        snapshot["bindings"]["commands"]["commit-environment"]["cwd"] = str(self.root / "sub")
        (self.clone / "sub").mkdir(parents=True)
        checks, runner = self.run_it(snapshot)
        probe = ("devenv", "shell", "--", "git", "-C", str(self.clone), "commit", "--allow-empty",
                 "--quiet", "-m", "host-readiness probe")
        self.assertIn((probe, self.clone / "sub", 120), runner.calls)
        timed_out = FakeRunner(self.common)
        timed_out.when(lambda argv: argv == probe, Completed(None, "", ""))
        checks, _ = self.run_it(snapshot, timed_out)
        self.assertEqual("fail commit-hook: the probe commit did not finish within 120 s",
                         line(checks, "commit-hook"))
        bare = fake_snapshot(self.root, **{"bindings.vcs.commit": {}})
        _, runner = self.run_it(bare)
        self.assertIn((("git", "-C", str(self.clone), "commit", "--allow-empty", "--quiet",
                        "-m", "host-readiness probe"), self.clone, 120), runner.calls)

    def test_the_registered_checkouts_commit_hooks_run_in_the_clone(self):
        hooks = self.common / "hooks"
        for name, mode, body in (("pre-commit", 0o755, b"#!/bin/sh\nexit 1\n"),
                                 ("post-update", 0o755, b"#!/bin/sh\n"),
                                 ("commit-msg", 0o644, b"#!/bin/sh\n")):
            (hooks / name).write_bytes(body)
            (hooks / name).chmod(mode)
        with self.subTest("copied"):
            self.run_it()
            copied = self.clone / ".git/hooks"
            self.assertEqual(b"#!/bin/sh\nexit 1\n", (copied / "pre-commit").read_bytes())
            self.assertTrue((copied / "pre-commit").stat().st_mode & stat.S_IXUSR)
            self.assertEqual(["pre-commit"], sorted(p.name for p in copied.iterdir()))
        with self.subTest("hooks path"):
            runner = FakeRunner(self.common)
            runner.when(lambda argv: "--get" in argv, Completed(0, "tools/hooks\n", ""))
            self.run_it(runner=runner)
            configure = ("git", "-C", str(self.clone), "config", "--local", "core.hooksPath",
                         "tools/hooks")
            argvs = runner.argvs()
            self.assertLess(argvs.index(configure),
                            next(i for i, a in enumerate(argvs) if a[-1] == COMMIT_PROBE_MESSAGE))
        with self.subTest("unreadable"):
            runner = FakeRunner(self.common)
            runner.when(lambda argv: "--get" in argv, Completed(128, "", "fatal: bad config\n"))
            checks, _ = self.run_it(runner=runner)
            detail = next(c for c in checks if c.id == "commit-hook").detail
            self.assertTrue(detail.startswith(f"the commit hooks of {self.root} could not be read: "))
            self.assertTrue(detail.endswith("exited 128: fatal: bad config"))
            self.assertFalse(any(a[-1] == COMMIT_PROBE_MESSAGE for a in runner.argvs()))

    def test_a_commit_environment_that_makes_no_commit_fails(self):
        runner = FakeRunner(self.common)
        runner.when(lambda argv: "log" in argv, Completed(0, f"{'c' * 40}\nan older commit\n", ""))
        checks, _ = self.run_it(runner=runner)
        self.assertEqual("fail commit-hook: the probe commit exited 0 but made no commit",
                         line(checks, "commit-hook"))
        self.assertEqual(1, exit_code(checks))

    def test_without_release_on_path_one_line_names_it(self):
        checks, _ = self.run_it(on_path=lambda name: name != "release")
        self.assertEqual(["release-command"], [c.id for c in checks if not c.passed])
        self.assertEqual("fail release-command: the release command is not on PATH",
                         line(checks, "release-command"))
        for name in ("release-profile github-release", "release-preview github-release"):
            self.assertTrue(next(c for c in checks if c.id == name).passed)

    def test_a_blocked_release_capability_names_its_cause(self):
        snapshot = fake_snapshot(self.root, **{"capabilities.release": {
            "state": "blocked", "reason_code": "release_adapter_unavailable", "repair_id": "x"}})
        inspection = copy.deepcopy(INSPECTION)
        inspection["conformance"]["adapters"]["forge"]["executables"]["gh"] = False
        checks, _ = self.run_it(snapshot, FakeRunner(self.common, inspection))
        rows = ids(checks)
        self.assertEqual(["release", "release-command", "release-profile github-release"],
                         rows[rows.index("release"):rows.index("release") + 3])
        self.assertEqual("fail release: the release capability is blocked: "
                         "release_adapter_unavailable", line(checks, "release"))
        self.assertEqual("fail release-profile github-release: adapter forge needs gh, "
                         "which is not on PATH", line(checks, "release-profile github-release"))
        self.assertEqual(1, exit_code(checks))

    def test_an_inadmissible_profile_or_a_missing_executable_fails_the_profile_line(self):
        profile = "release-profile github-release"
        with self.subTest("inadmissible"):
            inspection = copy.deepcopy(INSPECTION)
            inspection["profile"]["admissible"] = False
            inspection["conformance"]["findings"] = [
                {"rule": "r", "reason": "z_reason", "pointer": ""},
                {"rule": "s", "reason": "a_reason", "pointer": ""}]
            checks, _ = self.run_it(runner=FakeRunner(self.common, inspection))
            self.assertEqual(f"fail {profile}: the profile is not admissible: a_reason, z_reason",
                             line(checks, profile))
        with self.subTest("missing executable"):
            inspection = copy.deepcopy(INSPECTION)
            inspection["conformance"]["adapters"]["forge"]["executables"]["gh"] = False
            checks, _ = self.run_it(runner=FakeRunner(self.common, inspection))
            self.assertEqual(f"fail {profile}: adapter forge needs gh, which is not on PATH",
                             line(checks, profile))
        with self.subTest("refused"):
            runner = FakeRunner(self.common)
            runner.when(lambda argv: "inspect" in argv, Completed(2, refused_answer(
                "profile_unknown", repair_id="x",
                violations=[{"pointer": "/release", "message": "no profile github-release"}]), ""))
            checks, _ = self.run_it(runner=runner)
            self.assertEqual(f"fail {profile}: release profile inspect refused profile_unknown: "
                             "no profile github-release", line(checks, profile))
            self.assertFalse([i for i in ids(checks) if i.startswith("release-login")])

    def test_a_preview_refusal_of_either_shape_is_named_and_later_checks_still_run(self):
        _, runner = self.run_it()
        preview = [a for a in runner.argvs() if "preview" in a]
        self.assertEqual([(*sibling_argv("release.release"), "transaction", "preview", "--profile",
                           "github-release", "--repo-root", str(self.root), "--read-only")], preview)
        row = "release-preview github-release"
        shapes = {
            "driver refusal": (3, refused_answer("not_main_checkout", detail="d"),
                               "release transaction preview refused not_main_checkout: d"),
            "contract error": (2, refused_answer("capability_unavailable", violations=[{
                "pointer": "/capabilities/release",
                "message": "required capability is blocked: release_adapter_unavailable"}]),
                "release transaction preview refused capability_unavailable: required "
                "capability is blocked: release_adapter_unavailable"),
            "refused document": (3, json.dumps({"mode": "resume", "runnable": False, "refusal": {
                "code": "profile_drift", "repair_id": None, "detail": "e"}}),
                "release transaction preview refused profile_drift: e"),
        }
        for name, (code, out, detail) in shapes.items():
            with self.subTest(name):
                runner = FakeRunner(self.common)
                runner.when(lambda argv: "preview" in argv, Completed(code, out, ""))
                checks, _ = self.run_it(runner=runner)
                self.assertEqual(f"fail {row}: {detail}", line(checks, row))
                self.assertEqual("pass release-login github-release forge-keyring",
                                 render(checks).splitlines()[-1])

    def test_a_release_in_flight_is_previewed_read_only(self):
        runner = FakeRunner(self.common)
        runner.when(lambda argv: "preview" in argv, Completed(0, json.dumps(
            {"mode": "resume", "runnable": True, "lock": None, "confirmations": []}), ""))
        checks, _ = self.run_it(runner=runner)
        self.assertEqual("pass release-preview github-release: a release is in flight; it was "
                         "previewed read-only, with no lock", line(checks, "release-preview github-release"))
        for argv in runner.argvs():
            if "transaction" in argv:
                self.assertEqual("preview", argv[argv.index("transaction") + 1])
                self.assertIn("--read-only", argv)

    def test_each_credential_handle_gets_one_login_line(self):
        row = "release-login github-release forge-keyring"
        checks, runner = self.run_it()
        self.assertIn((("gh", "auth", "status", "--hostname", "github.com"), self.root, 30),
                      runner.calls)
        failing = FakeRunner(self.common)
        failing.when(lambda argv: argv[:2] == ("gh", "auth"), Completed(1, "", ""))
        checks, _ = self.run_it(runner=failing)
        self.assertEqual(f"fail {row}: gh is not logged in to github.com; run gh auth login",
                         line(checks, row))
        card = copy.deepcopy(INSPECTION)
        card["bindings"]["credentials"]["forge-keyring"]["class"] = "smartcard"
        checks, _ = self.run_it(runner=FakeRunner(self.common, card))
        self.assertEqual(f"fail {row}: no login check is defined for credential class smartcard",
                         line(checks, row))
        signing = copy.deepcopy(INSPECTION)
        signing["bindings"]["credentials"] = {
            "signing": {"adapter": "sign", "class": "codesigning_identity"}}
        signing["bindings"]["adapters"] = {"sign": {"adapter": "codesigned-artifact", "config": {
            "install": {"source": "N.app", "identity_prefix": "Apple Development: Me",
                        "adhoc_fallback": False}}}}
        listing = "".join(f'  {i}) {"B" * 40} "Developer ID Application: Other (Z)"\n'
                          for i in range(1, 11)) + "    10 valid identities found\n"
        runner = FakeRunner(self.common, signing)
        runner.when(lambda argv: argv[0] == "security", Completed(0, listing, ""))
        checks, _ = self.run_it(runner=runner)
        self.assertEqual("fail release-login github-release signing: no_signing_identity: none "
                         "starts with Apple Development: Me",
                         line(checks, "release-login github-release signing"))
        adhoc = copy.deepcopy(signing)
        adhoc["bindings"]["adapters"]["sign"]["config"]["install"]["adhoc_fallback"] = True
        runner = FakeRunner(self.common, adhoc)
        runner.when(lambda argv: argv[0] == "security",
                    Completed(0, "     0 valid identities found\n", ""))
        checks, _ = self.run_it(runner=runner)
        self.assertEqual("pass release-login github-release signing",
                         line(checks, "release-login github-release signing"))

    def test_every_adapter_credential_class_has_a_login_check(self):
        classes = set().union(*(d["credential_classes"] for d in release_adapter.DESCRIPTORS.values()))
        self.assertLessEqual(classes, set(LOGIN_PROBES))

    def railway_inspection(self) -> dict:
        inspection = copy.deepcopy(INSPECTION)
        inspection["bindings"]["adapters"]["deploy"] = {"adapter": "railway-deploy", "config": {
            "api": {"project": "nodo-prod", "environment": "production", "services": ["api"]}}}
        return inspection

    def test_a_railway_node_gets_a_link_line_judged_by_the_adapters_rule(self):
        row = "release-link github-release api"
        runner = FakeRunner(self.common, self.railway_inspection())
        runner.when(lambda argv: argv[:2] == ("railway", "status"), Completed(0, json.dumps(
            {"name": "other", "environments": {"edges": []}}), ""))
        checks, _ = self.run_it(runner=runner)
        self.assertEqual(f"fail {row}: the linked project is not nodo-prod with environment production",
                         line(checks, row))
        self.assertIn((("railway", "status", "--json"), self.root, 30), runner.calls)
        runner = FakeRunner(self.common, self.railway_inspection())
        runner.when(lambda argv: argv[:2] == ("railway", "status"), Completed(0, json.dumps({
            "name": "nodo-prod", "environments": {"edges": [{"node": {"name": "production"}}]}}), ""))
        checks, _ = self.run_it(runner=runner)
        self.assertEqual(f"pass {row}", line(checks, row))

    def test_a_project_without_release_reports_one_line(self):
        snapshot = fake_snapshot(self.root, **{"capabilities.release.state": "unsupported"})
        checks, runner = self.run_it(snapshot)
        self.assertEqual("pass release: the project declares no release profile",
                         render(checks).splitlines()[-1])
        self.assertFalse(any("agent_tools.release.release" in a for a in runner.argvs()))

    def test_a_production_verification_command_is_not_run(self):
        for argv in (["just", "switch"], ["sh", "-c", "just switch"],
                     ["bash", "-c", "true && just switch"]):
            with self.subTest(argv=argv):
                snapshot = fake_snapshot(self.root)
                snapshot["bindings"]["commands"]["test"]["argv"] = argv
                checks, runner = self.run_it(snapshot)
                self.assertEqual("fail verification test: would run production command deploy; "
                                 "not run", line(checks, "verification test"))
                self.assertNotIn(tuple(argv), runner.argvs())
        snapshot = fake_snapshot(self.root)
        snapshot["bindings"]["commands"]["test"]["argv"] = ["just", "switch", "--dry-run"]
        checks, runner = self.run_it(snapshot)
        self.assertIn(("just", "switch", "--dry-run"), runner.argvs())
        self.assertEqual("pass verification test", line(checks, "verification test"))

    def test_no_child_argv_hits_the_guards_production_rules(self):
        spec = importlib.util.spec_from_file_location("lifecycle_guard_source", GUARD_SOURCE)
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        rules = {"fagenorn/ready": {
            "changes": [{"id": "deploy", "argv": ["just", "switch"]}],
            "read_only": [{"id": "nix-build", "argv": ["just", "build"]},
                          {"id": "dry-run", "argv": ["just", "switch", "--dry-run"]}],
            "release_profile": "github-release"}}
        snap = fake_snapshot(self.root)
        for argv in (["just", "switch"], ["sh", "-c", "just switch"],
                     ["bash", "-c", "true && just switch"],
                     ["devenv", "shell", "--", "just", "switch"],
                     ["timeout", "600", "just", "switch"]):
            with self.subTest(argv=argv):
                self.assertTrue(guard.production_hits(shlex.join(argv), rules)[0])
                self.assertIsNotNone(refusal(argv, snap))
        dry = ["just", "switch", "--dry-run"]
        self.assertFalse(guard.production_hits(shlex.join(dry), rules)[0])
        self.assertIsNone(refusal(dry, snap))
        runner = FakeRunner(self.common, self.railway_inspection())
        self.run_it(runner=runner)
        self.assertTrue(any(a[:2] == ("railway", "status") for a in runner.argvs()))
        for argv in runner.argvs():
            self.assertFalse(guard.production_hits(shlex.join(argv), rules)[0], argv)


class RefusalTest(ReadinessCase):
    def test_refusal_reads_production_and_release_verbs_in_argv_and_shell_text(self):
        snap = fake_snapshot(self.root)
        production = "would run production command deploy"
        for argv in (["/usr/local/bin/just", "switch"],
                     ["devenv", "shell", "--", "just", "--justfile", "j", "switch"],
                     ["sh", "-c", "just switch"], ["sh", "-c", "cd x; just switch"],
                     ["devenv", "shell", "--", "sh", "-c", "(just switch)"]):
            with self.subTest(argv=argv):
                self.assertEqual(production, refusal(argv, snap))
        for argv in (["sh", "-c", "echo $(just switch)"], ["sh", "-c", "echo `x`"],
                     ["sh", "-c", "just 'switch"]):
            with self.subTest(argv=argv):
                self.assertEqual("would run shell text it cannot read", refusal(argv, snap))
        for argv in (["release", "transaction", "run", "--confirm", "t"],
                     ["sh", "-c", "release transaction run --confirm t"]):
            with self.subTest(argv=argv):
                self.assertEqual("would run release transaction run", refusal(argv, snap))
        self.assertEqual("would run release transaction abandon", refusal(
            [*sibling_argv("release.release"), "transaction", "abandon"], snap))
        self.assertEqual("would run release transaction preview without --read-only",
                         refusal(["release", "transaction", "preview"], snap))
        for argv in (["release", "transaction", "preview", "--read-only"],
                     ["release", "transaction", "status"], ["just", "build"], ["just", "test"],
                     ["just", "switch", "--dry-run"], ["sh", "-c", "test -f a && test ! -f b"],
                     ["git", "commit", "-m", "host-readiness probe"]):
            with self.subTest(argv=argv):
                self.assertIsNone(refusal(argv, snap))
        none = fake_snapshot(self.root, **{"production.status": "none"})
        self.assertIsNone(refusal(["just", "switch"], none))


class RenderTest(unittest.TestCase):
    def test_exit_code_is_one_on_any_failure_and_three_when_only_the_budget_failed(self):
        passing = [Check("a", True, None), Check("b", True, "n")]
        failing = Check("c", False, "why")
        self.assertEqual("pass a\npass b: n\nfail c: why\n", render([*passing, failing]))
        self.assertEqual(0, exit_code(passing))
        self.assertEqual(1, exit_code([*passing, failing]))
        spent = Check("d", False, "x", True)
        self.assertEqual(3, exit_code([Check("a", True, None), spent]))
        self.assertEqual(1, exit_code([failing, spent]))


class BudgetTest(ReadinessCase):
    def test_a_spent_budget_ends_the_run_and_exits_three(self):
        now = [0.0]
        runner = FakeRunner(self.common, now=now, step=30.0)
        runner.when(lambda argv: argv[:2] == ("git", "clone"), Completed(None, "", ""))
        checks, _ = self.run_it(runner=runner, clock=lambda: now[0], budget=50)
        clone = next(call for call in runner.calls if call[0][:2] == ("git", "clone"))
        self.assertEqual(20, clone[2])
        self.assertEqual("fail checkout: git clone of main did not finish within the run's "
                         "budget of 50 s", line(checks, "checkout"))
        by_id = {check.id: check for check in checks}
        self.assertTrue(by_id["checkout"].spent)
        for name in ("verification lint", "verification test", "commit-hook"):
            self.assertTrue(by_id[name].spent, name)
        profile = by_id["release-profile github-release"]
        self.assertEqual((False, "the run's budget of 50 s is spent; not run"),
                         (profile.passed, profile.detail))
        self.assertFalse(any("inspect" in a for a in runner.argvs()))
        self.assertTrue(by_id["release-command"].passed)
        self.assertEqual(3, exit_code(checks))
        now[0] = 0.0
        checks, _ = self.run_it(runner=FakeRunner(self.common, now=now, step=30.0),
                                clock=lambda: now[0], budget=50, on_path=lambda name: False)
        self.assertEqual(1, exit_code(checks))


class LeashedRunTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_a_hanging_tree_ends_at_its_limit(self):
        started = time.monotonic()
        done = leashed_run(["sh", "-c", "sleep 30 & sleep 30"], self.tmp, 1.0)
        self.assertIsNone(done.returncode)
        self.assertLess(time.monotonic() - started, 10)

    def test_a_child_gets_no_forge_token_or_git_redirect_and_a_missing_program_is_127(self):
        env = {"GH_TOKEN": "x", "GITHUB_TOKEN": "y", "GIT_DIR": "/nowhere",
               "GIT_INDEX_FILE": "/nowhere/index", "GIT_WORK_TREE": "/nowhere"}
        with mock.patch.dict(os.environ, env):
            done = leashed_run(
                ["sh", "-c", 'printf %s "${GH_TOKEN-u}${GITHUB_TOKEN-u}${GIT_DIR-u}'
                             '${GIT_INDEX_FILE-u}${GIT_WORK_TREE-u}"'], self.tmp, 10)
        self.assertEqual("uuuuu", done.stdout)
        missing = leashed_run(["no-such-program-1382"], self.tmp, 10)
        self.assertEqual(127, missing.returncode)
        self.assertTrue(missing.stderr.startswith("no-such-program-1382 cannot start"))


if __name__ == "__main__":
    unittest.main()
