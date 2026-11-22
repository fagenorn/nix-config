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
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Callable
from unittest import mock

from agent_tools.project_contract import host_readiness
from agent_tools.project_contract.host_readiness import (
    COMMIT_PROBE_MESSAGE,
    LOGIN_PROBES,
    remove_scratch,
    sweep_stale_scratch,
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

from .test_fleet_preflight import FleetFixtures
from .test_resolve_project import (
    ResolverTestCase,
    git,
    install_registry,
    registry,
    source_contract,
    tree_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
GUARD_SOURCE = REPO_ROOT / "home/common/claude-code/lifecycle_guard.py"
BASE = "b" * 40
TREE = "e" * 40

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
        if "rev-parse" in argv and "HEAD^{tree}" in argv:
            return Completed(0, f"{BASE}\n{TREE}\n", "")
        if "log" in argv and "-1" in argv:
            return Completed(0, f"{BASE}\n{COMMIT_PROBE_MESSAGE}\n{TREE}\n", "")
        if "inspect" in argv and "profile" in argv:
            return Completed(0, json.dumps(self.inspection), "")
        if "preview" in argv and "transaction" in argv:
            return Completed(3, json.dumps({"error": {
                "code": "candidate_required", "repair_id": None,
                "detail": "a new release needs a candidate"}}), "")
        return Completed(0, "", "")

    def argvs(self) -> list[tuple[str, ...]]:
        return [call[0] for call in self.calls]


def load_guard():
    spec = importlib.util.spec_from_file_location("lifecycle_guard_source", GUARD_SOURCE)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    return guard


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

    def test_a_hooks_path_inside_git_gets_the_registered_checkouts_hooks(self):
        hooks = self.root / ".git/hooks"
        hooks.mkdir(parents=True)
        (hooks / "pre-commit").write_bytes(b"#!/bin/sh\nexit 1\n")
        (hooks / "pre-commit").chmod(0o755)
        runner = FakeRunner(self.common)
        runner.when(lambda argv: "--get" in argv, Completed(0, ".git/hooks\n", ""))
        checks, _ = self.run_it(runner=runner)
        self.assertEqual(b"#!/bin/sh\nexit 1\n", (self.clone / ".git/hooks/pre-commit").read_bytes())
        self.assertTrue(next(c for c in checks if c.id == "commit-hook").passed)
        runner = FakeRunner(self.common)
        runner.when(lambda argv: "--get" in argv, Completed(0, "../../../outside\n", ""))
        checks, _ = self.run_it(runner=runner)
        self.assertTrue(line(checks, "commit-hook").endswith(
            "core.hooksPath ../../../outside is outside the clean checkout"))

    def test_the_probe_commit_is_empty_and_proves_it(self):
        checks, runner = self.run_it()
        argvs = runner.argvs()
        reset = ("git", "-C", str(self.clone), "reset", "--quiet")
        self.assertIn(reset, argvs)
        self.assertLess(argvs.index(reset),
                        next(i for i, a in enumerate(argvs) if a[-1] == COMMIT_PROBE_MESSAGE))
        runner = FakeRunner(self.common)
        runner.when(lambda argv: "log" in argv,
                    Completed(0, f"{BASE}\n{COMMIT_PROBE_MESSAGE}\n{'d' * 40}\n", ""))
        checks, _ = self.run_it(runner=runner)
        self.assertEqual("fail commit-hook: the probe commit exited 0 but was not empty",
                         line(checks, "commit-hook"))

    def test_a_relative_origin_is_read_from_the_registered_checkout(self):
        for url, expected in (("../origin.git", os.path.normpath(self.root / "../origin.git")),
                              ("/srv/origin.git", "/srv/origin.git"),
                              ("https://example.invalid/o.git", "https://example.invalid/o.git"),
                              ("git@example.invalid:o/p.git", "git@example.invalid:o/p.git")):
            with self.subTest(url=url):
                runner = FakeRunner(self.common)
                runner.when(lambda argv: "get-url" in argv, Completed(0, url + "\n", ""))
                self.run_it(runner=runner)
                clone = next(a for a in runner.argvs() if a[:2] == ("git", "clone"))
                self.assertEqual([expected, str(self.clone)], list(clone[-2:]))

    def test_a_login_probe_that_times_out_names_the_timeout(self):
        row = "release-login github-release forge-keyring"
        runner = FakeRunner(self.common)
        runner.when(lambda argv: argv[:2] == ("gh", "auth"), Completed(None, "", ""))
        checks, _ = self.run_it(runner=runner)
        self.assertEqual(f"fail {row}: gh auth status --hostname github.com did not finish "
                         "within 30 s", line(checks, row))

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

    def test_a_one_word_production_verb_is_not_hit_as_another_programs_argument(self):
        snap = fake_snapshot(self.root, **{
            "bindings.commands": {"deploy": {"argv": ["./scripts/deploy.sh"], "cwd": str(self.root), "env": []}},
            "production.read_only": {"commands": [], "mcp_tools": []}})
        for argv in (["shellcheck", "scripts/deploy.sh"], ["git", "add", "scripts/deploy.sh"],
                     ["sh", "-c", "shellcheck scripts/deploy.sh"]):
            with self.subTest(argv=argv):
                self.assertIsNone(refusal(argv, snap))
        for argv in (["./scripts/deploy.sh"], ["timeout", "5", "./scripts/deploy.sh"],
                     ["sh", "-c", "true && ./scripts/deploy.sh"]):
            with self.subTest(argv=argv):
                self.assertEqual("would run production command deploy", refusal(argv, snap))

    def test_a_one_word_production_verb_behind_a_shell_prefix_is_refused(self):
        guard = load_guard()
        rules = {"fagenorn/ready": {
            "changes": [{"id": "deploy", "argv": ["deploy"]}], "read_only": [],
            "release_profile": "github-release"}}
        snap = fake_snapshot(self.root, **{
            "bindings.commands": {"deploy": {"argv": ["deploy"], "cwd": str(self.root), "env": []}},
            "production.read_only": {"commands": [], "mcp_tools": []}})
        production = "would run production command deploy"
        for argv in (["sh", "-c", "true\ndeploy"], ["time", "deploy"],
                     ["sh", "-c", "{ deploy; }"], ["sh", "-c", "if true; then deploy; fi"],
                     ["sh", "-c", "x=1 deploy"], ["sh", "-c", "! deploy"]):
            with self.subTest(argv=argv):
                self.assertTrue(guard.production_hits(shlex.join(argv), rules)[0])
                self.assertEqual(production, refusal(argv, snap))
        for argv in (["sh", "-c", "true # note\ndeploy"], ["sh", "-c", "A=1 B=2 time deploy"],
                     ["sh", "-c", "for x in a; do deploy; done"],
                     ["sh", "-c", "while true; do x=1 deploy; done"]):
            with self.subTest(argv=argv):
                self.assertEqual(production, refusal(argv, snap))
        for argv in (["sh", "-c", "echo deploy"], ["sh", "-c", "true\necho deploy"],
                     ["sh", "-c", "x=1 echo deploy"], ["sh", "-c", "{ echo deploy; }"]):
            with self.subTest(argv=argv):
                self.assertIsNone(refusal(argv, snap))
        probe = fake_snapshot(self.root, **{
            "bindings.commands": {"deploy": {"argv": ["./probe"], "cwd": str(self.root), "env": []}},
            "production.read_only": {"commands": [], "mcp_tools": []}})
        self.assertEqual(production, refusal(["sh", "-c", "MODE=ci ./probe"], probe))

    def test_a_one_word_production_verb_run_by_a_shell_script_or_eval_is_refused(self):
        guard = load_guard()
        rules = {"fagenorn/ready": {
            "changes": [{"id": "deploy", "argv": ["deploy"]}], "read_only": [],
            "release_profile": "github-release"}}
        snap = fake_snapshot(self.root, **{
            "bindings.commands": {"deploy": {"argv": ["deploy"], "cwd": str(self.root), "env": []}},
            "production.read_only": {"commands": [], "mcp_tools": []}})
        production = "would run production command deploy"
        for argv in (["sh", "-c", "deploy"], ["bash", "-c", "deploy"], ["eval", "deploy"],
                     ["sh", "-c", "eval deploy"], ["sh", "-c", "\\deploy"],
                     ["sh", "-c", "'deploy'"], ["sh", "-c", "d\\\neploy"],
                     ["bash", "-lc", "deploy"], ["bash", "-o", "pipefail", "-c", "deploy"],
                     ["env", "sh", "-c", "deploy"], ["timeout", "5", "sh", "-c", "deploy"],
                     ["eval", "'deploy'"], ["sh", "-c", "eval 'deploy'"]):
            with self.subTest(argv=argv):
                self.assertTrue(guard.production_hits(shlex.join(argv), rules)[0])
                self.assertEqual(production, refusal(argv, snap))
        for argv in (["sh", "-c", "true"], ["sh", "-c", "echo deploy"],
                     ["eval", "echo", "deploy"], ["echo", "sh", "-c", "deploy"]):
            with self.subTest(argv=argv):
                self.assertIsNone(refusal(argv, snap))

    def test_a_shell_script_is_read_past_options_written_around_its_c_flag(self):
        guard = load_guard()
        rules = {"fagenorn/ready": {
            "changes": [{"id": "deploy", "argv": ["deploy"]}], "read_only": [],
            "release_profile": "github-release"}}
        snap = fake_snapshot(self.root, **{
            "bindings.commands": {"deploy": {"argv": ["deploy"], "cwd": str(self.root), "env": []}},
            "production.read_only": {"commands": [], "mcp_tools": []}})
        production = "would run production command deploy"
        for argv in (["sh", "-c", "--", "deploy"], ["bash", "-c", "-e", "deploy"],
                     ["bash", "-O", "extglob", "-c", "deploy"], ["bash", "+O", "extglob", "-c", "deploy"],
                     ["bash", "--rcfile", "x", "-c", "deploy"],
                     ["bash", "--init-file", "x", "-c", "deploy"],
                     ["bash", "--norc", "-c", "deploy"],
                     ["bash", "-c", "-o", "pipefail", "-e", "--", "deploy"],
                     ["bash", "-co", "pipefail", "deploy"], ["bash", "-e", "-c", "-u", "deploy"],
                     ["env", "bash", "-O", "extglob", "-c", "--", "deploy"],
                     ["sh", "-c", "-", "deploy"], ["bash", "-c", "+", "deploy"],
                     ["dash", "-c", "-e", "-", "deploy"],
                     ["zsh", "--emulate", "sh", "-c", "deploy"]):
            with self.subTest(argv=argv):
                self.assertTrue(guard.production_hits(shlex.join(argv), rules)[0])
                self.assertEqual(production, refusal(argv, snap))
        # A `+`-prefixed -c spelling turns the option off in some shells and is no excuse: no
        # option is parsed, every word a shell is given is read as shell text.
        for argv in (["sh", "+c", "deploy"], ["zsh", "+c", "deploy"],
                     ["bash", "-e", "+c", "deploy"], ["dash", "+ec", "deploy"],
                     ["env", "sh", "+c", "deploy"], ["bash", "--rcfile", "deploy", "-c", "true"],
                     ["bash", "-O", "deploy", "-c", "true"], ["sh", "deploy"]):
            with self.subTest(argv=argv):
                self.assertEqual(production, refusal(argv, snap))
        for argv in (["bash", "-O", "extglob", "-c", "true"], ["bash", "-c", "--", "echo deploy"],
                     ["sh", "-c", "-", "echo deploy"], ["sh", "+c", "echo deploy"],
                     ["echo", "sh", "+c", "deploy"]):
            with self.subTest(argv=argv):
                self.assertIsNone(refusal(argv, snap))

    def test_a_project_root_with_a_quote_or_a_space_is_a_plain_path_argument(self):
        base = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, base, True)
        for name in ("bob's app", 'say "hi" app'):
            root = base / name
            root.mkdir()
            snap = fake_snapshot(root)
            with self.subTest(name=name):
                self.assertIsNone(refusal(["git", "-C", str(root), "remote", "get-url", "origin"], snap))
                self.assertIsNone(refusal(["x", "--repo-root", str(root)], snap))
                self.assertEqual("would run production command deploy", refusal(
                    ["sh", "-c", f"cd {shlex.quote(str(root))} && just switch"], snap))
        self.assertEqual("would run shell text it cannot read",
                         refusal(["sh", "-c", "/no/such dir's/just switch"], fake_snapshot(self.root)))


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

    def test_a_daemon_in_a_session_of_its_own_ends_with_its_check(self):
        script = ("import subprocess, sys, time\n"
                  "p = subprocess.Popen(['sleep', '300'], start_new_session=True)\n"
                  "open(sys.argv[1], 'w').write(str(p.pid))\n"
                  "time.sleep(float(sys.argv[2]))\n")
        for name, hold, limit in (("timeout", "60", 2.0), ("exit", "0.5", 30.0)):
            with self.subTest(name):
                pid_file = self.tmp / f"{name}.pid"
                leashed_run([sys.executable, "-c", script, str(pid_file), hold], self.tmp, limit)
                pid = int(pid_file.read_text(encoding="utf-8"))
                for _ in range(50):
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.1)
                else:
                    os.kill(pid, signal.SIGKILL)
                    self.fail("the daemon outlived its check")

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


def reaped_pid() -> int:
    """The pid of a child that has already exited and been waited for."""
    child = subprocess.Popen(["true"])
    child.wait()
    return child.pid


def write_executable(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    return path


class HostReadinessCommandTest(FleetFixtures, ResolverTestCase):
    def world(self, *, edit: Callable[[dict], None] | None = None, release: bool = True,
              guard_bin: bool = True, seed: Callable[[Path], None] | None = None) -> Path:
        contract = source_contract()
        contract["project"]["id"] = "fagenorn/ready"
        contract["bindings"]["commands"]["lint"] = {
            "argv": ["sh", "-c", "test -f only-on-main && test ! -f local-only"],
            "cwd": ".", "env": []}
        contract["bindings"]["commands"]["test"] = {
            "argv": ["sh", "-c", "exit 0"], "cwd": ".", "env": []}
        contract["bindings"]["workflow"]["verification"] = ["lint", "test"]
        if edit is not None:
            edit(contract)
        entry, root = self.project("fagenorn/ready", contract=contract)
        git(root, "commit", "--allow-empty", "-m", "base")
        self.registry_path = install_registry(self.home, registry(entry))
        self.root = root
        self.bare = Path(tempfile.mkdtemp()).resolve()
        git(self.bare, "init", "--bare", "--initial-branch=main")
        seed_dir = Path(tempfile.mkdtemp()).resolve()
        git(seed_dir, "init", "--initial-branch=main")
        (seed_dir / "only-on-main").write_text("x\n", encoding="utf-8")
        if seed is not None:
            seed(seed_dir)
        git(seed_dir, "add", "-A")
        git(seed_dir, "commit", "-m", "seed")
        git(seed_dir, "push", str(self.bare), "main")
        git(root, "remote", "add", "origin", str(self.bare))
        (root / "local-only").write_text("y\n", encoding="utf-8")
        self.fakebin = Path(tempfile.mkdtemp()).resolve()
        write_executable(self.fakebin / "gh", "#!/bin/sh\nexit 0\n")
        if guard_bin:
            write_executable(self.fakebin / "claude-bash-lifecycle-guard", "#!/bin/sh\nexit 0\n")
        (self.fakebin / "git").symlink_to(shutil.which("git"))
        if release:
            write_executable(self.fakebin / "release", "#!/bin/sh\nexit 0\n")
        self.tmpdir = Path(tempfile.mkdtemp()).resolve()
        return root

    def run_command(self, *args: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
        env = {
            "HOME": str(self.home), "PATH": f"{self.fakebin}:/bin",
            "PYTHONPATH": str(REPO_ROOT / "python"), "TMPDIR": str(self.tmpdir),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
            **(extra_env or {})}
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.project_contract.host_readiness", *args],
            env=env, capture_output=True, text=True, timeout=300)

    def scratches(self) -> list[str]:
        return [name for name in os.listdir(self.tmpdir) if name.startswith("host-readiness-")]

    def test_a_ready_project_passes_every_check(self):
        self.world()
        done = self.run_command("fagenorn/ready")
        self.assertEqual("", done.stderr)
        self.assertEqual(0, done.returncode, done.stdout)
        self.assertEqual([
            "pass checkout",
            "pass verification lint",
            "pass verification test",
            "pass commit-hook",
            "pass release-command",
            "pass release-profile github-release",
            "pass release-preview github-release",
            "pass release-login github-release forge-keyring",
        ], done.stdout.splitlines())

    def test_without_release_on_path_one_line_names_it_and_exit_is_one(self):
        self.world(release=False)
        done = self.run_command("fagenorn/ready")
        self.assertEqual(1, done.returncode, done.stdout)
        failed = [line for line in done.stdout.splitlines() if line.startswith("fail ")]
        self.assertEqual(["fail release-command: the release command is not on PATH"], failed)

    def test_the_run_writes_nothing_outside_its_scratch(self):
        root = self.world()

        def state():
            return (git(root, "status", "--porcelain"), tree_snapshot(root),
                    self.registry_path.read_bytes(),
                    git(self.bare, "for-each-ref"))

        before = state()
        done = self.run_command("fagenorn/ready")
        self.assertEqual(0, done.returncode, done.stdout)
        self.assertEqual(before, state())
        self.assertEqual([], self.scratches())

    def test_an_inherited_repository_redirect_cannot_reach_the_registered_checkout(self):
        root = self.world()
        head = git(root, "rev-parse", "HEAD")
        staged = git(root, "ls-files", "-s")
        index = (root / ".git/index").read_bytes()
        done = self.run_command("fagenorn/ready", extra_env={
            "GIT_DIR": str(root / ".git"), "GIT_WORK_TREE": str(root),
            "GIT_INDEX_FILE": str(root / ".git/index")})
        self.assertEqual(0, done.returncode, done.stdout)
        self.assertIn("pass commit-hook", done.stdout.splitlines())
        self.assertEqual(head, git(root, "rev-parse", "HEAD"))
        self.assertEqual("1", git(root, "rev-list", "--count", "HEAD").strip())
        self.assertEqual(staged, git(root, "ls-files", "-s"))
        self.assertEqual(index, (root / ".git/index").read_bytes())

    def test_main_removes_the_git_redirect_from_its_environment_before_it_resolves(self):
        seen = {}

        def registry_read():
            seen.update({name: os.environ.get(name) for name in ("GIT_DIR", "GIT_INDEX_FILE")})
            return []

        redirect = {"GIT_DIR": "/nowhere", "GIT_INDEX_FILE": "/nowhere/index"}
        with mock.patch.dict(os.environ, redirect), \
                mock.patch.object(host_readiness, "require_registry", registry_read), \
                mock.patch("sys.stdout"):
            self.assertEqual(2, host_readiness.main(["fagenorn/ready"]))
        self.assertEqual({"GIT_DIR": None, "GIT_INDEX_FILE": None}, seen)

    def test_a_failing_installed_hook_fails_the_commit_hook_line(self):
        root = self.world()
        hook = write_executable(root / ".git/hooks/pre-commit",
                                "#!/bin/sh\necho hook refused >&2\nexit 1\n")
        text = hook.read_text(encoding="utf-8")
        done = self.run_command("fagenorn/ready")
        self.assertEqual(1, done.returncode, done.stdout)
        self.assertIn("fail commit-hook: the probe commit exited 1: hook refused",
                      done.stdout.splitlines())
        self.assertEqual(text, hook.read_text(encoding="utf-8"))

    def test_a_hooks_path_inside_git_is_carried_to_the_clone(self):
        root = self.world()
        git(root, "config", "core.hooksPath", ".git/hooks")
        write_executable(root / ".git/hooks/pre-commit",
                         "#!/bin/sh\necho hook refused >&2\nexit 1\n")
        done = self.run_command("fagenorn/ready")
        self.assertEqual(1, done.returncode, done.stdout)
        self.assertIn("fail commit-hook: the probe commit exited 1: hook refused",
                      done.stdout.splitlines())

    def test_a_file_a_verification_command_staged_is_not_in_the_probe_commit(self):
        def edit(contract):
            contract["bindings"]["commands"]["stage"] = {
                "argv": ["git", "mv", "only-on-main", "moved"], "cwd": ".", "env": []}
            contract["bindings"]["workflow"]["verification"].append("stage")

        root = self.world(edit=edit)
        write_executable(
            root / ".git/hooks/pre-commit",
            "#!/bin/sh\ngit diff --cached --quiet && { echo empty commit refused >&2; exit 1; }\n"
            "exit 0\n")
        done = self.run_command("fagenorn/ready")
        self.assertEqual(1, done.returncode, done.stdout)
        self.assertIn("pass verification stage", done.stdout.splitlines())
        self.assertIn("fail commit-hook: the probe commit exited 1: empty commit refused",
                      done.stdout.splitlines())

    def test_a_relative_origin_clones_the_registered_checkouts_origin(self):
        root = self.world()
        git(root, "remote", "set-url", "origin", os.path.relpath(self.bare, root))
        done = self.run_command("fagenorn/ready")
        self.assertEqual(0, done.returncode, done.stdout)
        self.assertIn("pass checkout", done.stdout.splitlines())

    def test_a_commit_environment_that_never_runs_git_fails(self):
        def edit(contract):
            contract["bindings"]["commands"]["commit-environment"] = {
                "argv": ["sh", "-c", "exit 0", "wrapper"], "cwd": ".", "env": []}
            contract["bindings"]["vcs"]["commit"]["environment"] = "commit-environment"

        self.world(edit=edit)
        done = self.run_command("fagenorn/ready")
        self.assertIn("fail commit-hook: the probe commit exited 0 but made no commit",
                      done.stdout.splitlines())

    def test_a_verification_directory_that_escapes_through_a_symlink_is_not_run(self):
        outside = Path(tempfile.mkdtemp()).resolve()

        def edit(contract):
            contract["bindings"]["commands"]["probe"] = {
                "argv": ["sh", "-c", "touch escaped"], "cwd": "escape", "env": []}
            contract["bindings"]["workflow"]["verification"].append("probe")

        def seed(directory):
            (directory / "escape").symlink_to(outside)

        root = self.world(edit=edit, seed=seed)
        (root / "escape").mkdir()
        done = self.run_command("fagenorn/ready")
        self.assertIn(
            "fail verification probe: its directory escape is not inside the clean checkout; not run",
            done.stdout.splitlines())
        self.assertEqual([], list(outside.iterdir()))
        self.assertFalse((root / "escape/escaped").exists())

    def test_a_missing_adapter_executable_is_named_even_with_release_on_path(self):
        self.world(guard_bin=False)
        done = self.run_command("fagenorn/ready")
        self.assertEqual(1, done.returncode, done.stdout)
        lines = done.stdout.splitlines()
        self.assertIn("fail release: the release capability is blocked: release_adapter_unavailable",
                      lines)
        self.assertIn("fail release-profile github-release: adapter forge needs "
                      "claude-bash-lifecycle-guard, which is not on PATH", lines)

    def test_an_unregistered_project_is_refused(self):
        self.world()
        done = self.run_command("fagenorn/absent")
        self.assertEqual(2, done.returncode)
        self.assertEqual("project_unregistered", json.loads(done.stdout)["error"]["code"])
        self.assertEqual([], self.scratches())

    def test_a_project_outside_this_platforms_range_is_refused_with_its_reason(self):
        def edit(contract):
            contract["platform"] = {"min_inclusive": "99.0.0", "max_exclusive": "100.0.0"}

        self.world(edit=edit)
        done = self.run_command("fagenorn/ready")
        self.assertEqual(2, done.returncode, done.stdout)
        error = json.loads(done.stdout)["error"]
        self.assertEqual("unsupported_schema", error["code"])
        self.assertEqual("platform_too_old", error["reason_code"])
        self.assertNotIn("Traceback", done.stderr)
        self.assertEqual([], self.scratches())

    def test_a_stale_scratch_is_swept_and_a_live_one_kept(self):
        self.world()
        stale = self.tmpdir / "host-readiness-stale"
        live = self.tmpdir / "host-readiness-live"
        for directory, pid in ((stale, reaped_pid()), (live, os.getpid())):
            directory.mkdir()
            (directory / "owner").write_text(f"{pid}\n", encoding="utf-8")
        self.run_command("fagenorn/ready")
        self.assertFalse(stale.exists())
        self.assertTrue(live.exists())

    def test_the_command_has_one_table_row(self):
        row = '    "host-readiness" = "project_contract.host_readiness";'
        table = (REPO_ROOT / "lib/agent-tools.nix").read_text(encoding="utf-8")
        self.assertEqual(1, table.splitlines().count(row))
        verdicts = json.loads((REPO_ROOT / "python/agent_tools/delivery/command_verdicts.json")
                              .read_text(encoding="utf-8"))
        self.assertIn("host-readiness", verdicts)
        self.assertIsNone(verdicts["host-readiness"])


class ScratchTest(unittest.TestCase):
    def test_a_scratch_with_read_only_parts_is_removed(self):
        directory = Path(tempfile.mkdtemp()).resolve()
        (directory / "a/b").mkdir(parents=True)
        (directory / "a/b/file").write_text("x", encoding="utf-8")
        (directory / "a/b/file").chmod(0o400)
        (directory / "a/b").chmod(0o500)
        self.assertTrue(remove_scratch(directory))
        self.assertFalse(directory.exists())

    def test_a_scratch_with_an_unopenable_directory_is_removed_whatever_its_mode(self):
        for mode in (0o000, 0o200, 0o300):
            with self.subTest(mode=oct(mode)):
                directory = Path(tempfile.mkdtemp()).resolve()
                (directory / "a/b").mkdir(parents=True)
                (directory / "a/b/file").write_text("x", encoding="utf-8")
                (directory / "a/b").chmod(mode)
                (directory / "a").chmod(mode)
                self.assertTrue(remove_scratch(directory))
                self.assertFalse(directory.exists())

    def test_a_removal_that_cannot_finish_reports_false_instead_of_raising(self):
        directory = Path(tempfile.mkdtemp()).resolve()
        (directory / "file").write_text("x", encoding="utf-8")
        with mock.patch.object(os, "unlink", side_effect=PermissionError("held")):
            self.assertFalse(remove_scratch(directory))
        self.assertTrue(directory.exists())
        remove_scratch(directory)

    def test_a_directory_that_cannot_be_made_openable_reports_false_without_recursing(self):
        parent = Path(tempfile.mkdtemp()).resolve()
        dead = parent / "host-readiness-dead"
        (dead / "sub").mkdir(parents=True)
        (dead / "owner").write_text(f"{reaped_pid()}\n", encoding="utf-8")
        (dead / "sub").chmod(0o000)
        real_chmod = Path.chmod

        def refuse(path, mode, **kwargs):
            if path.name == "sub":
                raise PermissionError("held")
            return real_chmod(path, mode, **kwargs)

        with mock.patch.object(Path, "chmod", refuse):
            self.assertFalse(remove_scratch(dead))
            self.assertEqual([], sweep_stale_scratch(parent))
        self.assertTrue(dead.exists())
        (dead / "sub").chmod(0o700)
        self.assertTrue(remove_scratch(dead))

    def test_a_stale_scratch_with_an_unopenable_directory_is_swept(self):
        parent = Path(tempfile.mkdtemp()).resolve()
        dead = parent / "host-readiness-dead"
        (dead / "sub").mkdir(parents=True)
        (dead / "sub/file").write_text("x", encoding="utf-8")
        (dead / "owner").write_text(f"{reaped_pid()}\n", encoding="utf-8")
        (dead / "sub").chmod(0o000)
        self.assertEqual([dead], sweep_stale_scratch(parent))
        self.assertFalse(dead.exists())

    def test_only_a_stale_scratch_of_this_user_is_swept(self):
        parent = Path(tempfile.mkdtemp()).resolve()

        def scratch(name: str, owner: int | None) -> Path:
            directory = parent / name
            directory.mkdir()
            if owner is not None:
                (directory / "owner").write_text(f"{owner}\n", encoding="utf-8")
            return directory

        dead = scratch("host-readiness-dead", reaped_pid())
        live = scratch("host-readiness-live", os.getpid())
        old = scratch("host-readiness-unowned-old", None)
        (old / "notes.txt").write_text("a user's own files", encoding="utf-8")
        two_hours_ago = time.time() - 7200
        os.utime(old, (two_hours_ago, two_hours_ago))
        new = scratch("host-readiness-unowned-new", None)
        other = scratch("other-dir", reaped_pid())
        target = Path(tempfile.mkdtemp()).resolve()
        (target / "owner").write_text(f"{reaped_pid()}\n", encoding="utf-8")
        (parent / "host-readiness-link").symlink_to(target)
        removed = sweep_stale_scratch(parent)
        self.assertEqual([dead], removed)
        for kept in (live, old, new, other, parent / "host-readiness-link", target):
            self.assertTrue(kept.exists(), kept)


class CheckScriptTest(unittest.TestCase):
    SCRIPT = REPO_ROOT / "home/common/verify-pending/checks/host-readiness"

    def test_the_check_script_is_executable(self):
        self.assertTrue(os.access(self.SCRIPT, os.X_OK))

    def test_the_check_script_passes_a_budget_and_reads_a_spent_one_as_not_yet(self):
        home = Path(tempfile.mkdtemp()).resolve()
        (home / ".agents/bin").mkdir(parents=True)
        write_executable(home / ".agents/bin/host-readiness",
                         '#!/bin/sh\necho "$*" > "$HOME/args"\nexit "$FAKE_EXIT"\n')
        for fake, expected in ((3, 75), (0, 0), (1, 1), (2, 2)):
            done = subprocess.run(
                [str(self.SCRIPT), "fagenorn/x"], capture_output=True, text=True, timeout=60,
                env={"HOME": str(home), "PATH": "/usr/bin:/bin", "FAKE_EXIT": str(fake)})
            self.assertEqual(expected, done.returncode, (fake, done.stderr))
            self.assertEqual("--budget-seconds 600 fagenorn/x\n",
                             (home / "args").read_text(encoding="utf-8"))
