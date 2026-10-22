"""`orchestrate-control` run from source (#403, spec seam 1; D26)."""
import json
import unittest
from pathlib import Path

from .orchestrate_world import INVALID, SLUG, OrchestrateWorld


def report(done):
    return json.loads(done.stdout)


def gitlab(contract):
    contract["bindings"]["tracker"]["kind"] = "gitlab"
    contract["release"] = "unsupported"  # a GitHub release profile needs a GitHub tracker


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
                 "empty label": ["start", "--repo-root", str(world.root), "--label", ""],
                 "empty milestone": ["start", "--repo-root", str(world.root), "--milestone", ""],
                 "empty run id": ["start", "--repo-root", str(world.root), "12",
                                  "--run-id", ""],
                 "no subcommand": []}
        for name, argv in cases.items():
            with self.subTest(name):
                done = world.run(*argv)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (2, "", INVALID))


STEP_ORDER = ["bindings", "bootstrap", "tracker", "forge", "worktrees", "control", "project"]


def steps_before(step):
    return STEP_ORDER[:STEP_ORDER.index(step)]


def assert_refused(case, done, command, step, completed):
    case.assertEqual(done.returncode, 2, done.stdout + done.stderr)
    out = json.loads(done.stdout)
    case.assertEqual(set(out), {"command", "outcome", "step", "detail", "completed_steps",
                                "response"})
    case.assertEqual((out["command"], out["outcome"], out["step"], out["completed_steps"]),
                     (command, "refused", step, completed))
    case.assertLessEqual(len(out["detail"]), 300)
    case.assertNotIn("\n", out["detail"])
    return out


def keyed(issues, value):
    return {str(issue): value for issue in issues}


class FactsTest(unittest.TestCase):
    def test_the_request_carries_the_bound_policy_and_control_accepts_it(self):
        def policy(contract):
            contract["bindings"]["workflow"]["orchestration"].update(
                max_parallel=3, attempt_budget_minutes=45)
        world = OrchestrateWorld(self, mutate=policy)
        session = world.start("12", "14")["session"]
        done, out = world.step(session, first_sweep=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((out["command"], out["outcome"], out["run_id"]),
                         ("step", "ready", session["run_id"]))
        self.assertEqual((out["response"]["interface_version"], out["response"]["run_id"]),
                         (3, session["run_id"]))
        request = world.requests()[0]
        self.assertNotIn("now", request)
        self.assertEqual({k: v for k, v in request.items()
                          if k not in ("tracker", "worktrees", "forge")}, {
            "interface_version": 3, "host_route": "claude-code", "max_parallel": 3,
            "attempt_budget_minutes": 45, "human_directed": True, "issues": [12, 14],
            "owners": [], "delivery_contracts": keyed([12, 14], None),
            "authorization_intents": keyed([12, 14], []),
            "authority_observations": keyed([12, 14], []),
            "reevaluation_evidence": keyed([12, 14], []),
            "delivery_observations": keyed([12, 14], []),
            "requested_scopes": keyed([12, 14], None), "recoveries": keyed([12, 14], None)})

    def test_no_gh_child_sees_an_unset_variable(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14")["session"]
        done, _ = world.step(session)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual([c["token_visible"] for c in world.calls("gh")], [False, False])
        self.assertEqual(world.env["GITHUB_TOKEN"], "harness-token")
        self.assertEqual(world.env["ORCH_TEST_SENTINEL"], "harness-token")

    def test_a_non_control_reply_refuses_at_control(self):
        world = OrchestrateWorld(self)
        session = world.start("12")["session"]
        boot = world.ws("init-run", "--repo-root", world.root, "--run-id", session["run_id"])
        world.fault("workflow-state", "control", stdout=boot.stdout.decode())
        done, _ = world.step(session)
        assert_refused(self, done, "step", "control", steps_before("control"))
        self.assertIsNone(json.loads(done.stdout)["response"])

    def test_a_bootstrap_of_another_run_refuses_at_bootstrap(self):
        world = OrchestrateWorld(self)
        session = world.start("12")["session"]
        other = world.ws("init-run", "--repo-root", world.root, "--creation-key", "other")
        world.fault("workflow-state", "init-run", stdout=other.stdout.decode())
        assert_refused(self, world.step(session)[0], "step", "bootstrap", ["bindings"])


class TrackerTest(unittest.TestCase):
    def test_open_blockers_split_into_numbers_and_decision_blockers(self):
        world = OrchestrateWorld(self)
        world.issue(12, blocked_by=[
            world.blocker(5, labels=["wayfinder:task", "bug"]),
            world.blocker(9, labels=["bug"]),
            world.blocker(6),
            world.blocker(10, repo="Fagenorn/Nix-Config"),
            world.blocker(7, state="CLOSED", labels=["wayfinder:research"]),
            world.blocker(8, state="CLOSED", repo="other/repo")])
        world.issue(14, state="CLOSED")
        session = world.start("12", "14")["session"]
        world.step(session)
        self.assertEqual(world.requests()[0]["tracker"], [
            {"issue": 12, "state": "open", "open_blockers": [6, 9, 10],
             "decision_blockers": [{"issue": 5, "url": f"https://github.com/{SLUG}/issues/5"}]},
            {"issue": 14, "state": "closed", "open_blockers": [], "decision_blockers": []}])
        (read,) = [c["argv"] for c in world.calls("gh", "api") if "--paginate" not in c["argv"]]
        self.assertEqual(read[:3] + read[4:], ["api", "graphql", "-f",
                                               "-f", "owner=fagenorn", "-f", "name=nix-config"])
        self.assertIn("blockedBy(first: 50)", read[3])
        self.assertIn("labels(first: 25)", read[3])

    def test_a_cross_repository_open_blocker_refuses_at_tracker(self):
        world = OrchestrateWorld(self)
        world.issue(12, blocked_by=[world.blocker(5, repo="other/repo")])
        session = world.start("12")["session"]
        out = assert_refused(self, world.step(session)[0], "step", "tracker",
                             steps_before("tracker"))
        self.assertIn("other/repo", out["detail"])

    def test_a_truncated_page_a_missing_issue_or_a_pull_request_refuses_at_tracker(self):
        cases = {
            "blockers truncated": lambda w: w.issue(12, truncated=True),
            "labels truncated": lambda w: w.issue(12, blocked_by=[
                w.blocker(5, labels=["bug"], labels_truncated=True)]),
            "missing": lambda w: w.missing(12),
            "pull request": lambda w: w.issue(12, typename="PullRequest")}
        for name, arrange in cases.items():
            with self.subTest(name):
                world = OrchestrateWorld(self)
                arrange(world)
                session = world.start("12")["session"]
                assert_refused(self, world.step(session)[0], "step", "tracker",
                               steps_before("tracker"))

    def test_a_non_github_tracker_refuses_at_tracker(self):
        world = OrchestrateWorld(self, mutate=gitlab)
        session = world.start("12")["session"]
        assert_refused(self, world.step(session)[0], "step", "tracker", steps_before("tracker"))
        self.assertEqual(world.calls("gh"), [])

    def test_one_tracker_call_per_hundred_issues(self):
        world = OrchestrateWorld(self)
        minted = json.loads(world.ws("init-run", "--repo-root", world.root,
                                     "--creation-key", "k101").stdout)
        session = world.start(*map(str, range(1, 102)), "--run-id", minted["run_id"])["session"]
        world.fault("workflow-state", "control", exit=2, stderr="workflow-state: fixture stop\n")
        assert_refused(self, world.step(session)[0], "step", "control", steps_before("control"))
        api = world.calls("gh", "api")
        reads = [c["argv"] for c in api if "--paginate" not in c["argv"]]
        self.assertEqual([next(a for a in argv if a.startswith("query="))
                          .count("issueOrPullRequest(") for argv in reads], [100, 1])
        self.assertEqual(len([c for c in api if "--paginate" in c["argv"]]), 1)


class ForgeTest(unittest.TestCase):
    def test_the_forge_listing_is_paginated_uncapped_and_matched(self):
        world = OrchestrateWorld(self)
        world.pull(3, "feature-x")
        world.pull(4, "issue-12-old", state="CLOSED")
        world.pull(5, "issue-140-other")
        world.pull(6, "issue-14-fork", cross=True)
        world.pull(9, "worktree-issue-12-new")
        world.pull(12, "issue-16-done", state="MERGED", merge_oid="a" * 40)
        session = world.start("12", "14", "16")["session"]
        world.step(session)
        url = f"https://github.com/{SLUG}/pull/"
        self.assertEqual(world.requests()[0]["forge"], {
            "12": {"state": "open", "url": url + "9", "merge_sha": None},
            "14": {"state": "none", "url": None, "merge_sha": None},
            "16": {"state": "merged", "url": url + "12", "merge_sha": "a" * 40}})
        (listing,) = [c["argv"] for c in world.calls("gh", "api") if "--paginate" in c["argv"]]
        self.assertEqual(listing[:5] + listing[6:], ["api", "graphql", "--paginate", "--slurp",
                                                     "-f", "-f", "owner=fagenorn",
                                                     "-f", "name=nix-config"])
        self.assertIn("pullRequests(first: 100, after: $endCursor)", listing[5])

    def test_a_truncated_forge_listing_refuses_at_forge(self):
        world = OrchestrateWorld(self)
        world.pull(3, "feature-x")
        world.truncate_forge()
        session = world.start("12")["session"]
        assert_refused(self, world.step(session)[0], "step", "forge", steps_before("forge"))


class WorktreeTest(unittest.TestCase):
    def test_recorded_worktrees_normalize_to_three_states(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14", "16", "18")["session"]
        world.seed_spawn(session, [12, 14, 16, 18])
        world.add_worktree(world.candidate(12), "worktree-issue-12-orchestrated")
        Path(world.candidate(16)).mkdir(parents=True)
        world.add_worktree(world.candidate(18), "topic")
        world.step(session)
        recorded = lambda n, state: {"issue": n, "candidate": None,
                                     "recorded": {"path": world.candidate(n), "state": state}}
        self.assertEqual(world.requests()[0]["worktrees"], [
            recorded(12, "matching_issue_branch"), recorded(14, "absent"),
            recorded(16, "mismatch"), recorded(18, "mismatch")])

    def test_a_leftover_worktree_or_branch_moves_the_candidate_to_2(self):
        world = OrchestrateWorld(self)
        world.add_worktree(world.candidate(12), "worktree-issue-12-orchestrated")
        world.git("branch", "issue-14-orchestrated")
        session = world.start("12", "14", "16")["session"]
        done, _ = world.step(session)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        free = lambda n, suffix="": {"issue": n, "recorded": None, "candidate": {
            "path": world.candidate(n, suffix), "state": "absent"}}
        self.assertEqual(world.requests()[0]["worktrees"],
                         [free(12, "-2"), free(14, "-2"), free(16)])

    def test_candidate_exhaustion_refuses_at_worktrees(self):
        world = OrchestrateWorld(self)
        for suffix in ["", *(f"-{n}" for n in range(2, 10))]:
            world.git("branch", f"issue-12-orchestrated{suffix}")
        session = world.start("12")["session"]
        out = assert_refused(self, world.step(session)[0], "step", "worktrees",
                             steps_before("worktrees"))
        self.assertIn("12", out["detail"])

    def test_a_subset_session_observes_only_its_issues_and_avoids_their_paths(self):
        world = OrchestrateWorld(self)
        full = world.start("12", "14")["session"]
        world.add_worktree(world.candidate(14), "issue-12-elsewhere")
        world.seed_spawn(full, [12], paths={12: world.candidate(14),
                                            14: world.candidate(14, "-3")})
        world.git("worktree", "remove", "--force", world.candidate(14))
        subset = world.start("14", "--run-id", full["run_id"])["session"]
        world.step(subset)
        request = world.requests()[0]
        self.assertEqual((request["issues"], [t["issue"] for t in request["tracker"]],
                          list(request["forge"])), ([14], [14], ["14"]))
        self.assertEqual(request["worktrees"], [{"issue": 14, "recorded": None, "candidate": {
            "path": world.candidate(14, "-2"), "state": "absent"}}])


class StepInputTest(unittest.TestCase):
    def test_a_malformed_input_is_an_invalid_invocation(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14")["session"]
        good = {"session": session, "first_sweep": False, "owners": [], "contracts_due": [],
                "refused_contracts": []}

        def changed(**members):
            return json.dumps({**good, **members})
        accepted = world.run("step", "--repo-root", world.root, "--input", "-",
                             stdin=json.dumps(good))
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        owner = {"event_id": "e", "issue": 99, "custody": {}, "state": "unavailable"}
        cases = {
            "not json": "{",
            "duplicate key": '{"first_sweep": true, ' + changed()[1:],
            "extra member": changed(extra=1),
            "missing member": json.dumps({k: v for k, v in good.items() if k != "owners"}),
            "empty issues": changed(session={**session, "issues": []}),
            "source and direction disagree": changed(session={**session, "source": {
                "kind": "standing_repository", "reference": "sweep:label:x"}}),
            "foreign due": changed(contracts_due=[99]),
            "repeated refused": changed(refused_contracts=[12, 12]),
            "foreign owner": changed(owners=[owner]),
            "first_sweep not boolean": changed(first_sweep=1)}
        for name, text in cases.items():
            with self.subTest(name):
                done = world.run("step", "--repo-root", world.root, "--input", "-", stdin=text)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (2, "", INVALID))
        for argv in (["step", "--repo-root", "relative", "--input", "-"],
                     ["step", "--repo-root", str(world.root), "--input", "file.json"]):
            with self.subTest(argv=argv):
                done = world.run(*argv, stdin=json.dumps(good))
                self.assertEqual((done.returncode, done.stdout, done.stderr), (2, "", INVALID))


class ClosedSetTest(unittest.TestCase):
    def test_an_unknown_action_kind_refuses_at_project_with_the_response(self):
        world = OrchestrateWorld(self)
        session = world.start("12")["session"]
        canned = {"interface_version": 3, "run_id": session["run_id"],
                  "now": "2026-10-22T00:00:00Z", "summaries": [], "deltas": [],
                  "actions": [{"id": "x", "kind": "teleport"}], "next_deadline": None,
                  "admission": None}
        world.fault("workflow-state", "control", stdout=json.dumps(canned) + "\n")
        world.fault("artifact-budget", "validate-report", passthrough=True)
        out = assert_refused(self, world.step(session)[0], "step", "project",
                             steps_before("project"))
        self.assertEqual(out["response"], canned)
        self.assertIn("teleport", out["detail"])
