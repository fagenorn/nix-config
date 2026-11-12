"""The verify script that no test manager's record is left in any profile (#970).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent_tools.console import cleanup_check, nudge
from agent_tools.system import siblings
from tests.test_verify_checks import committed_mode

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/console-check-cleanup"
PROJECT = "owner/p01"


class CleanupCheckTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.pdir = self.dir / "owner%2Fp01"
        self.pdir.mkdir()
        self.runs = []
        self.exit = 0
        self.configured = ["work"]
        self.listings = {}
        self.read = []

    def fresh(self, name, names, profiles, project=PROJECT):
        (self.pdir / f"{name}-result.json").write_text(json.dumps({
            "status": "met", "cleared": {"project": project, "names": names,
                                         "profiles": profiles}}))

    def all_fresh(self, profiles=None):
        def pick(own):
            return own if profiles is None else profiles
        self.fresh("manager-start", ["p sprint a", "p sprint b"], pick(["work"]))
        self.fresh("owner-message", ["p sprint c"], pick(["work"]))
        self.fresh("manager-revive", ["p sprint d"], pick(["p2"]))

    def run_check(self, module, project, state_file, result_file):
        self.runs.append((module, project, state_file, result_file))
        return self.exit

    def lister(self, profile, cwd):
        self.read.append(profile)
        outcome = self.listings[profile]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cleanup_check.main(
                ["--project", PROJECT, "--checks-dir", str(self.dir)],
                run_check=self.run_check, lister=self.lister, profiles=lambda: self.configured)
        return code, json.loads(out.getvalue())

    def test_a_check_without_a_result_of_this_version_is_run_alone_and_the_run_is_not_yet(self):
        self.assertEqual((75, {"check": "manager-start", "check_exit": 0, "status": "waiting"}),
                         self.check())
        self.assertEqual([("console.manager_check", PROJECT, self.pdir / "manager-start.json",
                           self.pdir / "manager-start-result.json")], self.runs)
        self.assertEqual([], self.read)
        self.fresh("manager-start", ["p sprint a"], ["work"])
        (self.pdir / "owner-message-result.json").write_text(
            json.dumps({"status": "met", "read_seconds": 4}))
        self.exit = 1
        self.assertEqual((75, {"check": "owner-message", "check_exit": 1, "status": "waiting"}),
                         self.check())
        self.assertEqual(2, len(self.runs))
        self.assertEqual(("console.message_check", PROJECT, self.pdir / "owner-message.json",
                          self.pdir / "owner-message-result.json"), self.runs[-1])

    def test_a_result_written_for_another_project_is_run_again(self):
        self.all_fresh()
        self.fresh("manager-start", ["q sprint a"], ["work"], project="owner/p02")
        self.assertEqual((75, {"check": "manager-start", "check_exit": 0, "status": "waiting"}),
                         self.check())
        self.assertEqual(["console.manager_check"], [run[0] for run in self.runs])
        self.assertEqual([], self.read)

    def test_three_fresh_results_and_no_named_session_listed_is_met(self):
        self.all_fresh()
        self.configured = ["default", "work"]
        self.listings = {"default": [], "work": [{"sessionId": "x", "name": "other"}], "p2": []}
        self.assertEqual((0, {"names": ["p sprint a", "p sprint b", "p sprint c", "p sprint d"],
                              "profiles": ["default", "p2", "work"], "status": "met"}),
                         self.check())
        self.assertEqual(["default", "p2", "work"], self.read)
        self.assertEqual([], self.runs)

    def test_a_leftover_in_a_profile_no_check_stopped_in_is_not_met(self):
        self.all_fresh(profiles=[])
        self.configured = ["p2", "work"]
        self.listings = {"work": [], "p2": [{"sessionId": "y", "name": "p sprint c"}]}
        self.assertEqual((1, {"left": ["p sprint c"], "status": "not_met"}), self.check())
        self.assertIn("p2", self.read)

    def test_no_profile_to_read_is_not_yet(self):
        self.all_fresh(profiles=[])
        self.configured = []
        self.assertEqual((75, {"status": "no_profiles"}), self.check())
        self.assertEqual([], self.read)

    def test_a_named_session_still_listed_is_not_met(self):
        self.all_fresh()
        self.configured = ["default", "work"]
        self.listings = {"default": [], "p2": [], "work": [
            {"sessionId": "x", "name": "p sprint c"}, {"sessionId": "y"}]}
        self.assertEqual((1, {"left": ["p sprint c"], "status": "not_met"}), self.check())

    def test_an_unreadable_listing_is_not_yet(self):
        self.all_fresh()
        self.configured = ["default", "work"]
        self.listings = {"default": [], "work": [], "p2": nudge.ListingUnreadable(
            "the listing exited 1")}
        self.assertEqual((75, {"profile": "p2", "reason": "the listing exited 1",
                               "status": "no_listing"}), self.check())

    def test_the_check_is_launched_through_the_shared_sibling_launcher(self):
        with mock.patch.object(siblings, "sibling_argv",
                               side_effect=lambda module: ["launch", module]), \
                mock.patch.object(cleanup_check.subprocess, "run",
                                  return_value=SimpleNamespace(returncode=3)) as run:
            code = cleanup_check.default_run_check(
                "console.revive_check", PROJECT, Path("/s.json"), Path("/r.json"))
        self.assertEqual(3, code)
        self.assertEqual(["launch", "console.revive_check", "start", "--project", PROJECT,
                          "--state-file", "/s.json", "--result-file", "/r.json"],
                         run.call_args.args[0])
        self.assertIs(subprocess.DEVNULL, run.call_args.kwargs["stdin"])

    def test_the_wrapper_runs_the_module_and_is_executable(self):
        text = (ROOT / WRAPPER).read_text()
        self.assertTrue(text.startswith("#!/bin/sh"))
        self.assertIn("agent_tools.console.cleanup_check", text)
        self.assertEqual("100755", committed_mode(ROOT / WRAPPER))


if __name__ == "__main__":
    unittest.main()
