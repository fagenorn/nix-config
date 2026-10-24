"""`orchestrate-control` run from source (#403, spec seam 1; D26)."""
import json
import shutil
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


STEP_ORDER = ["bindings", "bootstrap", "tracker", "forge", "worktrees", "contracts", "control",
              "project"]


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

    def test_a_recorded_worktree_whose_path_holds_a_newline_still_matches(self):
        world = OrchestrateWorld(self)
        session = world.start("12")["session"]
        path = str(world.root / ".worktrees" / "line\nbreak" / "worktree-issue-12-orchestrated")
        world.seed_spawn(session, [12], paths={12: path})
        world.add_worktree(path, "worktree-issue-12-orchestrated")
        done, _ = world.step(session)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(world.requests()[0]["worktrees"], [{"issue": 12, "candidate": None,
            "recorded": {"path": path, "state": "matching_issue_branch"}}])

    def test_a_prunable_registration_is_not_a_matching_worktree(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14")["session"]
        world.seed_spawn(session, [12])
        world.add_worktree(world.candidate(12), "worktree-issue-12-orchestrated")
        (Path(world.candidate(12)) / ".git").unlink()
        world.add_worktree(world.candidate(14), "topic-14")
        (Path(world.candidate(14)) / ".git").unlink()
        shutil.rmtree(world.candidate(14))
        self.assertEqual(world.git("worktree", "list", "--porcelain").count("prunable"), 2)
        done, _ = world.step(session)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(world.requests()[0]["worktrees"], [
            {"issue": 12, "candidate": None,
             "recorded": {"path": world.candidate(12), "state": "mismatch"}},
            {"issue": 14, "recorded": None,
             "candidate": {"path": world.candidate(14, "-2"), "state": "absent"}}])

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
            "first_sweep not boolean": changed(first_sweep=1),
            "NUL in run_id": changed(session={**session, "run_id": session["run_id"] + "\0"})}
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


ENVELOPE = ("action_id", "launch_kind", "issue", "attempt", "owner", "worktree", "handoff_path")


def projected(action, root, run_id):
    value = {k: v for k, v in action.items() if k not in ("id", "kind")}
    value.update(action_id=action["id"], launch_kind=action["kind"], kind="owner",
                 interface_version=2, ledger_repo_root=str(root), run_id=run_id)
    return value


class ProjectTest(unittest.TestCase):
    def resumed(self, world):
        """Seed issue 12's spawn, give it a live worktree, then report its owner unavailable."""
        session = world.start("12")["session"]
        spawn = world.seed_spawn(session, [12])[12]
        world.add_worktree(world.candidate(12), "worktree-issue-12-orchestrated")
        owner = {"event_id": "12-unavailable", "issue": 12, "custody": spawn["custody"],
                 "state": "unavailable"}
        return session, world.step(session, owners=[owner])

    def test_a_resume_carries_its_owner_object_and_resume_pack(self):
        world = OrchestrateWorld(self)
        session, (done, out) = self.resumed(world)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        (action,) = [a for a in out["response"]["actions"] if a["kind"] != "wait"]
        self.assertEqual(action["kind"], "resume")
        (dispatch,) = out["dispatches"]
        self.assertEqual(set(dispatch), {*ENVELOPE, "owner_object", "resume_pack"})
        self.assertEqual({k: dispatch[k] for k in ENVELOPE}, {
            "action_id": action["id"], "launch_kind": "resume", "issue": 12,
            "attempt": action["attempt"], "owner": action["owner"],
            "worktree": action["worktree"], "handoff_path": action["handoff_path"]})
        expected = projected(action, world.root, session["run_id"])
        self.assertEqual(json.loads(dispatch["owner_object"]), expected)
        checked = world.validate(expected)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(dispatch["owner_object"], checked.stdout.decode().removesuffix("\n"))
        (call,) = world.calls("workflow-state", "resume-pack")
        self.assertEqual(call["argv"], ["resume-pack", "--repo-root", str(world.root),
                                        "--run-id", session["run_id"], "--action-id", action["id"]])
        pack = world.ws(*call["argv"])
        self.assertEqual(pack.returncode, 0, pack.stderr)
        self.assertEqual(dispatch["resume_pack"], pack.stdout.decode())

    def test_a_failing_resume_pack_leaves_it_null(self):
        world = OrchestrateWorld(self)
        world.fault("workflow-state", "resume-pack", exit=2,
                    stderr="workflow-state: resume-pack refused: fixture\n")
        _, (done, out) = self.resumed(world)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        (dispatch,) = out["dispatches"]
        self.assertEqual((dispatch["launch_kind"], dispatch["resume_pack"]), ("resume", None))

    def test_a_remainder_dispatch_is_its_action_verbatim(self):
        world = OrchestrateWorld(self)
        session = world.start("12")["session"]
        remainder = {"interface_version": 2, "kind": "delivery_remainder",
                     "ledger_repo_root": str(world.root), "run_id": session["run_id"],
                     "issue": 12, "source_attempt": 1, "owner": "12:r1",
                     "custody": {"kind": "remainder", "remainder": 1, "launch": 1,
                                 "action_id": "12:r1:1"},
                     "worktree": world.candidate(12), "contract": None, "contract_digest": None,
                     "pending_stage_ids": [], "deadline_at": "2026-10-22T01:00:00Z",
                     "requirements": [], "authority_evaluation": None, "requested_scope": None}
        canned = {"interface_version": 3, "run_id": session["run_id"],
                  "now": "2026-10-22T00:00:00Z", "summaries": [], "deltas": [],
                  "actions": [remainder], "next_deadline": None, "admission": None}
        world.fault("workflow-state", "control", stdout=json.dumps(canned) + "\n")
        world.fault("artifact-budget", "validate-report", passthrough=True)
        done, out = world.step(session)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(out["dispatches"], [{
            "action_id": "12:r1:1", "launch_kind": "delivery_remainder", "issue": 12,
            "attempt": 1, "owner": "12:r1", "worktree": world.candidate(12),
            "handoff_path": None, "resume_pack": None,
            "owner_object": json.dumps(remainder, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":"))}])
        self.assertEqual(world.calls("workflow-state", "resume-pack"), [])

    def test_an_owner_object_the_boundary_refuses_refuses_at_project(self):
        world = OrchestrateWorld(self)
        world.fault("artifact-budget", "validate-report", stdin_kind="owner", exit=2,
                    stderr="artifact-budget: invalid report\n")
        _, (done, _) = self.resumed(world)
        out = assert_refused(self, done, "step", "project", steps_before("project"))
        self.assertIn("validate-report", out["detail"])
        self.assertIn("resume", [a["kind"] for a in out["response"]["actions"]])


REFUSED_LINE = "workflow-state: build-delivery refused: fixture"


def builds(world):
    return [json.loads(c["stdin"]) for c in world.calls("workflow-state", "build-delivery")]


def contract_input(world, issue, session, path=None):
    return {"issue": issue, "worktree": path or world.candidate(issue),
            "source_kind": session["source"]["kind"],
            "source_reference": session["source"]["reference"]}


def asking(response):
    return sorted(s["issue"] for s in response["summaries"]
                  if any(r.get("reason_code") == "delivery_contract_required"
                         for r in s["requirements"]))


class ContractTest(unittest.TestCase):
    def test_first_sweep_builds_for_null_digest_requirements_from_the_recorded_worktree(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14")["session"]
        world.seed_spawn(session, [12])
        boot = json.loads(world.ws("init-run", "--repo-root", world.root,
                                   "--run-id", session["run_id"]).stdout)
        (requirement,) = boot["requirements"]
        requirement["contract_digest"] = None
        world.fault("workflow-state", "init-run", stdout=json.dumps(boot) + "\n")
        world.fault("workflow-state", "control", exit=2, stderr="workflow-state: fixture stop\n")
        assert_refused(self, world.step(session, first_sweep=True)[0], "step", "control",
                       steps_before("control"))
        self.assertEqual(builds(world), [contract_input(world, 12, session)])
        self.assertEqual(world.calls("workflow-state", "build-delivery")[0]["argv"],
                         ["build-delivery", "--repo-root", str(world.root), "--kind", "contract",
                          "--input", "-"])
        assert_refused(self, world.step(session)[0], "step", "control", steps_before("control"))
        self.assertEqual(len(builds(world)), 1)

    def test_contracts_due_are_built_and_refused_ones_never(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14", "16")["session"]
        done, out = world.step(session, contracts_due=[12], refused_contracts=[14])
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(builds(world), [contract_input(world, 12, session)])
        self.assertEqual(out["control_calls"], 1)
        self.assertIn(14, asking(out["response"]))
        self.assertEqual(out["contracts_due"], [i for i in asking(out["response"]) if i != 14])
        self.assertEqual((out["refused_contracts"], out["contract_refusals"]), ([14], []))

    def test_a_builder_refusal_is_reported_and_joins_refused_contracts(self):
        world = OrchestrateWorld(self)
        world.fault("workflow-state", "build-delivery", issue=14, exit=2,
                    stderr=REFUSED_LINE + "\n")
        session = world.start("12", "14")["session"]
        done, out = world.step(session, first_sweep=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(out["control_calls"], 2)
        first, second = world.requests()
        self.assertEqual(first["delivery_contracts"], keyed([12, 14], None))
        self.assertIsNotNone(second["delivery_contracts"]["12"])
        self.assertIsNone(second["delivery_contracts"]["14"])
        self.assertEqual((len(second["authorization_intents"]["12"]),
                          second["authorization_intents"]["14"]), (1, []))
        self.assertEqual(second["owners"], [])
        for fact in ("tracker", "forge", "worktrees", "issues", "max_parallel"):
            self.assertEqual(second[fact], first[fact])
        self.assertEqual(out["contract_refusals"], [{"issue": 14, "detail": REFUSED_LINE}])

    def test_owners_ride_the_first_call_once_and_never_the_chained_one(self):
        # S1 (D30): the owner observations the adapter passes must be non-empty here,
        # or re-sending them on the chained call would go unnoticed. A real `control` answers
        # an `unavailable` observation of a live custody with a resume dispatch, never
        # contract-only, so the first call is answered with a contract-only reply of this run
        # captured from the source `control` for the identical request minus the owners.
        world = OrchestrateWorld(self)
        world.fault("workflow-state", "build-delivery", issue=14, exit=2,
                    stderr=REFUSED_LINE + "\n")
        session = world.start("12", "14")["session"]
        owner = {"event_id": "12-unavailable", "issue": 12, "state": "unavailable",
                 "custody": {"kind": "spawn", "launch": 1, "action_id": "12:1:1"}}
        world.fault("workflow-state", "control", exit=2, stderr="workflow-state: probe\n")
        world.step(session, owners=[owner])
        (probe,) = world.requests()
        world.clear_faults()
        world.fault("workflow-state", "build-delivery", issue=14, exit=2,
                    stderr=REFUSED_LINE + "\n")
        captured = world.ws("control", "--repo-root", world.root, "--run-id", session["run_id"],
                            "--request-file", "-",
                            stdin=json.dumps({**probe, "owners": []}).encode())
        self.assertEqual(captured.returncode, 0, captured.stdout + captured.stderr)
        self.assertEqual([a["kind"] for a in json.loads(captured.stdout)["actions"]],
                         ["delivery_contract"])
        world.fault("workflow-state", "control", call=2, stdout=captured.stdout.decode())
        done, out = world.step(session, owners=[owner])
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        _, first, chained = world.requests()
        self.assertEqual((first["owners"], chained["owners"], out["control_calls"]),
                         ([owner], [], 2))
        self.assertEqual(out["refused_contracts"], [14])
        self.assertNotIn(14, out["contracts_due"])
        self.assertEqual([d["issue"] for d in out["dispatches"]], [12])
        self.assertFalse(out["ends_run"])

    def test_a_builder_failure_before_control_refuses_at_contracts(self):
        cases = {"crash": {"exit": 1, "stderr": "boom\n"},
                 "exit 2 with output": {"exit": 2, "stdout": "{}", "stderr": "x\n"},
                 "no pair": {"exit": 0, "stdout": '{"contract": {}}'}}
        for name, rule in cases.items():
            with self.subTest(name):
                world = OrchestrateWorld(self)
                world.fault("workflow-state", "build-delivery", issue=12, **rule)
                session = world.start("12")["session"]
                out = assert_refused(self, world.step(session, contracts_due=[12])[0], "step",
                                     "contracts", steps_before("contracts"))
                self.assertIsNone(out["response"])
                self.assertEqual(world.requests(), [])


class ChainTest(unittest.TestCase):
    def test_a_fresh_set_chains_one_contract_round_into_spawns(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14")["session"]
        done, out = world.step(session, first_sweep=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(out["control_calls"], 2)
        first, second = world.requests()
        self.assertEqual(first["delivery_contracts"], keyed([12, 14], None))
        self.assertTrue(all(second["delivery_contracts"][k] is not None for k in ("12", "14")))
        self.assertEqual(builds(world), [contract_input(world, 12, session),
                                         contract_input(world, 14, session)])
        actions = {a["id"]: a for a in out["response"]["actions"]}
        self.assertEqual([(d["action_id"], d["launch_kind"], d["issue"], d["worktree"])
                          for d in out["dispatches"]],
                         [("12:1:1", "spawn", 12, world.candidate(12)),
                          ("14:1:1", "spawn", 14, world.candidate(14))])
        for dispatch in out["dispatches"]:
            expected = projected(actions[dispatch["action_id"]], world.root, session["run_id"])
            self.assertEqual(json.loads(dispatch["owner_object"]), expected)
            self.assertEqual(dispatch["owner_object"],
                             world.validate(expected).stdout.decode().removesuffix("\n"))
            self.assertIsNone(dispatch["resume_pack"])
        self.assertEqual((out["contracts_due"], out["refused_contracts"],
                          out["contract_refusals"], out["ends_run"]), ([], [], [], False))

    def test_a_reply_with_a_dispatch_is_never_chained(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14")["session"]
        done, out = world.step(session, contracts_due=[12, 14])
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((out["control_calls"], len(world.requests())), (1, 1))
        self.assertEqual([d["launch_kind"] for d in out["dispatches"]], ["spawn", "spawn"])

    def test_every_listed_refusal_ends_the_run(self):
        world = OrchestrateWorld(self)
        for issue in (12, 14):
            world.fault("workflow-state", "build-delivery", issue=issue, exit=2,
                        stderr=REFUSED_LINE + "\n")
        session = world.start("12", "14")["session"]
        done, out = world.step(session, first_sweep=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(out["response"]["actions"], [
            {"id": "delivery_contract", "kind": "delivery_contract", "issues": [12, 14]}])
        self.assertEqual((out["control_calls"], out["dispatches"], out["refused_contracts"],
                          out["ends_run"]), (1, [], [12, 14], True))
        self.assertEqual([r["issue"] for r in out["contract_refusals"]], [12, 14])

    def test_a_failure_in_the_chained_phase_refuses_at_control_with_the_first_reply(self):
        cases = {"second call": ("control", {"call": 2, "exit": 2,
                                             "stderr": "workflow-state: fixture stop\n"}),
                 "chained build crash": ("build-delivery", {"issue": 14, "exit": 1,
                                                            "stderr": "boom\n"})}
        for name, (sub, rule) in cases.items():
            with self.subTest(name):
                world = OrchestrateWorld(self)
                world.fault("workflow-state", sub, **rule)
                session = world.start("12", "14")["session"]
                out = assert_refused(self, world.step(session, first_sweep=True)[0], "step",
                                     "control", steps_before("control"))
                self.assertEqual(out["response"]["actions"], [
                    {"id": "delivery_contract", "kind": "delivery_contract",
                     "issues": [12, 14]}])

    def test_a_chained_reply_that_is_not_a_control_response_keeps_the_first_reply(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14")["session"]
        boot = world.ws("init-run", "--repo-root", world.root, "--run-id", session["run_id"])
        world.fault("workflow-state", "control", call=2, stdout=boot.stdout.decode())
        out = assert_refused(self, world.step(session, first_sweep=True)[0], "step",
                             "control", steps_before("control"))
        self.assertEqual(out["response"]["actions"], [
            {"id": "delivery_contract", "kind": "delivery_contract", "issues": [12, 14]}])


class RefusalTableTest(unittest.TestCase):
    def test_every_start_step_refuses_with_its_name(self):
        world = OrchestrateWorld(self)
        world.listing("--label", "none", [])
        rows = [("bindings", lambda: None, ["start", "--repo-root", world.cwd, "12"]),
                ("route", lambda: world.fault("workflow-state", "host-route", exit=2,
                                              stderr="workflow-state: fixture\n"),
                 ["start", "--repo-root", world.root, "12"]),
                ("issues", lambda: None, ["start", "--repo-root", world.root, "--label", "none"]),
                ("bootstrap", lambda: world.fault("workflow-state", "init-run", exit=2,
                                                  stderr="workflow-state: fixture\n"),
                 ["start", "--repo-root", world.root, "12"])]
        order = ["bindings", "route", "issues", "bootstrap"]
        for step, arrange, argv in rows:
            with self.subTest(step):
                world.clear_faults()
                arrange()
                out = assert_refused(self, world.run(*argv), "start", step,
                                     order[:order.index(step)])
                self.assertIsNone(out["response"])

    def test_every_step_step_refuses_with_its_name_and_the_response_after_control(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14")["session"]
        taken = [f"issue-12-orchestrated{s}" for s in ["", *(f"-{n}" for n in range(2, 10))]]
        rows = [
            ("bindings", lambda: None, {"repo_root": world.cwd}),
            ("bootstrap", lambda: world.fault("workflow-state", "init-run", exit=2,
                                              stderr="workflow-state: fixture\n"), {}),
            ("tracker", lambda: world.fault("gh", "api", exit=1, stderr="gh: fixture\n"), {}),
            ("forge", lambda: world.fault("gh", "api", argv_has="--paginate", exit=1,
                                          stderr="gh: fixture\n"), {}),
            ("worktrees", lambda: [world.git("branch", name) for name in taken], {}),
            ("contracts", lambda: world.fault("workflow-state", "build-delivery", issue=12,
                                              exit=1, stderr="boom\n"),
             {"contracts_due": [12]}),
            ("control", lambda: world.fault("workflow-state", "control", exit=2,
                                            stderr="workflow-state: fixture\n"), {}),
            ("project", lambda: world.fault("artifact-budget", "validate-report",
                                            stdin_kind="owner", exit=2,
                                            stderr="artifact-budget: invalid report\n"),
             {"contracts_due": [12, 14]})]
        for step, arrange, extra in rows:
            with self.subTest(step):
                world.clear_faults()
                arrange()
                out = assert_refused(self, world.step(session, **extra)[0], "step", step,
                                     steps_before(step))
                if step == "project":
                    self.assertEqual(out["response"]["run_id"], session["run_id"])
                else:
                    self.assertIsNone(out["response"])
                if step == "worktrees":
                    world.git("branch", "-D", *taken)

    def test_no_file_is_created_under_the_ledger_root_or_working_directory(self):
        world = OrchestrateWorld(self)
        before = (world.snapshot(world.root), world.snapshot(world.cwd))
        session = world.start("12", "14")["session"]
        done, out = world.step(session, first_sweep=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(len(out["dispatches"]), 2)
        world.fault("workflow-state", "control", exit=2, stderr="workflow-state: fixture\n")
        assert_refused(self, world.step(session)[0], "step", "control", steps_before("control"))
        self.assertTrue((world.root / ".superpowers").is_dir())
        self.assertEqual((world.snapshot(world.root), world.snapshot(world.cwd)), before)
