"""`orchestrate-control` run from source (#403, spec seam 1; D26)."""
import json
import unittest

from .orchestrate_world import INVALID, SLUG, OrchestrateWorld


def report(done):
    return json.loads(done.stdout)


class StartTest(unittest.TestCase):
    def test_explicit_numbers_give_a_human_directed_session(self):
        world = OrchestrateWorld(self)
        out = world.start("14", "12")
        session = out["session"]
        self.assertEqual((out["command"], out["outcome"]), ("start", "ready"))
        self.assertEqual(set(out), {"command", "outcome", "session"})
        self.assertEqual(session, {"interface_version": 1, "run_id": session["run_id"],
                                   "issues": [14, 12], "human_directed": True,
                                   "source": {"kind": "explicit_user",
                                              "reference": "invocation:/orchestrate-issues 14 12"}})
        (init,) = world.calls("workflow-state", "init-run")
        self.assertEqual(init["argv"], ["init-run", "--repo-root", str(world.root),
                                        "--issue-set", "14-12"])
        self.assertEqual(world.calls("gh"), [])

    def test_a_label_or_milestone_gives_a_standing_repository_session(self):
        world = OrchestrateWorld(self)
        world.listing("--label", "agent:ready", [30, 12, 14])
        world.listing("--milestone", "v1", [7])
        label = world.start("--label", "agent:ready")["session"]
        milestone = world.start("--milestone", "v1")["session"]
        self.assertEqual((label["issues"], label["human_directed"], label["source"]),
                         ([12, 14, 30], False, {"kind": "standing_repository",
                                                "reference": "sweep:label:agent:ready"}))
        self.assertEqual((milestone["issues"], milestone["source"]["reference"]),
                         ([7], "sweep:milestone:v1"))
        self.assertEqual([c["argv"] for c in world.calls("gh")], [
            ["issue", "list", "--repo", SLUG, "--state", "open", "--label", "agent:ready",
             "--json", "number", "--limit", "1000"],
            ["issue", "list", "--repo", SLUG, "--state", "open", "--milestone", "v1",
             "--json", "number", "--limit", "1000"]])
        self.assertEqual([c["token_visible"] for c in world.calls("gh")], [False, False])

    def test_run_id_re_enters_the_run(self):
        world = OrchestrateWorld(self)
        first = world.start("12", "14")["session"]
        again = world.start("12", "14", "--run-id", first["run_id"])["session"]
        self.assertEqual(again, first)
        self.assertEqual(world.calls("workflow-state", "init-run")[-1]["argv"],
                         ["init-run", "--repo-root", str(world.root), "--run-id", first["run_id"]])

    def test_an_unsupported_route_prints_no_session(self):
        world = OrchestrateWorld(self, claude_code="unsupported")
        done = world.run("start", "--repo-root", world.root, "12")
        self.assertEqual(done.returncode, 0, done.stderr)
        out = report(done)
        self.assertEqual(set(out), {"command", "outcome", "route"})
        self.assertEqual((out["outcome"], out["route"]["kind"], out["route"]["support"]),
                         ("unsupported", "host_route", "unsupported"))
        self.assertEqual(world.calls("workflow-state", "init-run"), [])
        self.assertFalse((world.root / ".superpowers").exists())


class StartRefusalTest(unittest.TestCase):
    def refused(self, done, step, completed):
        self.assertEqual(done.returncode, 2, done.stderr)
        out = report(done)
        self.assertEqual(set(out), {"command", "outcome", "step", "detail",
                                    "completed_steps", "response"})
        self.assertEqual((out["command"], out["outcome"], out["step"], out["completed_steps"],
                          out["response"]), ("start", "refused", step, completed, None))
        self.assertLessEqual(len(out["detail"]), 300)
        self.assertNotIn("\n", out["detail"])
        return out

    def test_an_unresolvable_root_refuses_at_bindings(self):
        world = OrchestrateWorld(self)
        out = self.refused(world.run("start", "--repo-root", world.cwd, "12"), "bindings", [])
        self.assertIn("not_onboarded", out["detail"])
        self.assertIn("onboarding.contract.missing", out["detail"])

    def test_an_empty_or_capped_sweep_refuses_at_issues(self):
        world = OrchestrateWorld(self)
        world.listing("--label", "none", [])
        world.listing("--label", "many", range(1, 1001))
        for label in ("none", "many"):
            with self.subTest(label=label):
                self.refused(world.run("start", "--repo-root", world.root, "--label", label),
                             "issues", ["bindings", "route"])

    def test_duplicate_numbers_refuse_at_issues(self):
        world = OrchestrateWorld(self)
        self.refused(world.run("start", "--repo-root", world.root, "12", "12"),
                     "issues", ["bindings", "route"])

    def test_a_non_github_tracker_refuses_a_sweep_at_issues(self):
        def gitlab(contract):
            contract["bindings"]["tracker"]["kind"] = "gitlab"
            contract["release"] = "unsupported"  # a GitHub release profile needs a GitHub tracker

        world = OrchestrateWorld(self, mutate=gitlab)
        self.refused(world.run("start", "--repo-root", world.root, "--label", "x"),
                     "issues", ["bindings", "route"])
        self.assertEqual(world.calls("gh"), [])

    def test_a_set_too_long_for_the_issue_set_key_refuses_at_bootstrap(self):
        world = OrchestrateWorld(self)
        numbers = [str(n) for n in range(1000, 1030)]
        out = self.refused(world.run("start", "--repo-root", world.root, *numbers),
                           "bootstrap", ["bindings", "route", "issues"])
        self.assertTrue(out["detail"].endswith("invalid issue set"), out["detail"])


class StartInvocationTest(unittest.TestCase):
    def test_malformed_argv_is_an_invalid_invocation(self):
        world = OrchestrateWorld(self)
        cases = {"relative root": ["start", "--repo-root", "relative", "12"],
                 "no issues": ["start", "--repo-root", str(world.root)],
                 "numbers and label": ["start", "--repo-root", str(world.root), "12",
                                       "--label", "x"],
                 "label and milestone": ["start", "--repo-root", str(world.root),
                                         "--label", "x", "--milestone", "y"],
                 "not a number": ["start", "--repo-root", str(world.root), "12a"],
                 "zero": ["start", "--repo-root", str(world.root), "0"],
                 "no subcommand": []}
        for name, argv in cases.items():
            with self.subTest(name):
                done = world.run(*argv)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (2, "", INVALID))
