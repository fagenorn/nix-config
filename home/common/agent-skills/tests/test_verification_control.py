"""Verification blockers resolved by `workflow-state control` (issue 545), through the CLI
from source.

Run: just agent-workflow-tests
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools import verification_blocker as vb

from .test_verification_suspension import NEXT, T, VerificationHarness, failure, observed
from .test_workflow_state import BUDGET_POLICY, SCRIPT

X, Y = failure(), failure(path="Cargo.lock")
X_ID, Y_ID = vb.blocker_id(X), vb.blocker_id(Y)
FINALIZE = [{"id": "finalize", "kind": "finalize"}]


def asked(blocker):
    """The summary requirement of an attempt parked on `blocker`'s open record."""
    return {"kind": "verification", "blocker_id": vb.blocker_id(blocker),
            "sources": [{"name": "flake-lock",
                         "paths": blocker["facts"][0]["source"]["paths"]}]}


class ControlHarness(VerificationHarness):
    def parked(self, *pairs):
        """Spawn each issue of `pairs`, then park it on its failure, a minute apart from T(5)."""
        self.spawn_all(*(issue for issue, _ in pairs))
        for minute, (issue, blocker) in enumerate(pairs, start=5):
            self.park(issue, blocker, now=T(minute))

    def request(self, minute, *observations, issues=(61, 62), **fields):
        return self.control_request(now=T(minute), issues=list(issues),
                                    tracker=[self.tracker_fact(issue) for issue in issues],
                                    worktrees=self.recorded(*issues),
                                    verification=list(observations), **fields)

    def sweep(self, minute, *observations, issues=(61, 62), **fields):
        return self.control_validated(
            request=self.request(minute, *observations, issues=issues, **fields))

    def refused(self, raw):
        """`control` over request bytes `raw`, which it must refuse."""
        path = self.root / "refused-request.json"
        path.write_bytes(raw)
        return self.run_cli("control", "--repo-root", self.root, "--run-id", self.run_id,
                            "--request-file", path, ok=False)

    def blockers(self):
        return self.read_state()["verification_blockers"]

    @staticmethod
    def summaries(reply):
        return {item["issue"]: item for item in reply["summaries"]}

    @staticmethod
    def awaited(summary):
        """The verification requirements among a summary's requirements."""
        return [item for item in summary["requirements"] if item["kind"] == "verification"]

    @staticmethod
    def dispatched(reply):
        return [(action["kind"], action["id"]) for action in reply["actions"]
                if action["kind"] in ("spawn", "resume", "retry")]


class ReplayTest(ControlHarness, unittest.TestCase):
    def test_no_or_an_equal_observation_resumes_nothing_and_writes_nothing(self):
        self.parked((61, X), (62, X))
        attempts = {issue: self.attempt(issue) for issue in (61, 62)}
        held = self.blockers()
        first = self.sweep(7)
        self.assertEqual(first["actions"], FINALIZE)
        self.assertEqual(self.blockers(), held)
        before = self.tree_snapshot()
        for directed in (False, True):
            with self.subTest(human_directed=directed):
                reply = self.sweep(8, observed(X), human_directed=directed)
                self.assertEqual(reply["actions"], FINALIZE)
                for issue in (61, 62):
                    summary = self.summaries(reply)[issue]
                    self.assertEqual(
                        (summary["state"], summary["blocked_on"], self.awaited(summary)),
                        ("suspended", "verification", [asked(X)]))
                    self.assertEqual(self.attempt(issue), attempts[issue])
                self.assertEqual(self.tree_snapshot(), before)


class ExplicitRetryTest(ControlHarness, unittest.TestCase):
    def test_retry_detaches_only_one_attempt_from_a_shared_blocker(self):
        self.parked((61, X), (62, X))
        blockers = self.blockers()
        other = self.attempt(62)
        done = self.run_cli("retry-verification", "--repo-root", self.root,
                            "--run-id", self.run_id, "--issue", 61, "--attempt", 1,
                            "--blocker-id", X_ID, "--now", T(7))
        self.assertEqual(self.validated_response(done.stdout)["blocked_on"], "human_gate")
        self.assertEqual(self.blockers(), blockers)
        self.assertEqual(self.attempt(62), other)
        self.assertEqual(self.dispatched(self.sweep(8, observed(X), human_directed=False)), [])
        self.assertEqual(self.dispatched(self.sweep(9, observed(X), human_directed=True)),
                         [("resume", "61:1:2")])
        self.assertEqual(self.attempt(62), other)
        self.assertEqual(self.blockers(), blockers)


class ChangeTest(ControlHarness, unittest.TestCase):
    def test_a_selected_change_resumes_only_the_attempts_it_releases(self):
        self.parked((61, X), (62, Y))
        reply = self.sweep(7, observed(X), observed(Y, NEXT))
        self.assertEqual(self.dispatched(reply), [("resume", "62:1:2")])
        summaries = self.summaries(reply)
        self.assertEqual((summaries[61]["state"], self.awaited(summaries[61])),
                         ("suspended", [asked(X)]))
        self.assertEqual((summaries[62]["state"], self.awaited(summaries[62])),
                         ("active", []))
        blockers = self.blockers()
        self.assertEqual((blockers[X_ID]["state"], blockers[X_ID]["resolution"]),
                         ("open", None))
        self.assertEqual((blockers[Y_ID]["state"], blockers[Y_ID]["resolution"]),
                         ("resolved", {"facts": observed(Y, NEXT)["facts"]}))
        self.assertEqual(blockers[Y_ID]["attempts"], [{"issue": 62, "attempt": 1}])

    def retained(self, *issues):
        """Give each attempt the work a resume must keep: a handoff document, phase 2 after
        the handoff's relaunch, and a progress marker on a real worktree."""
        for issue in issues:
            self.init_worktree(self.worktree(issue), branch=f"issue-{issue}")
            self.progress(issue=issue, phase=2, now=T(1), turn_count=118,
                          handoff_path=self.write_handoff(issue))
        self.assertEqual(self.dispatched(self.sweep(2, issues=issues)),
                         [("resume", f"{issue}:1:2") for issue in issues])
        for issue in issues:
            self.assertEqual(self.mark_progress(action_id=f"{issue}:1:2", now=T(3))["outcome"],
                             "baseline")

    def test_capacity_resumes_in_request_order_and_keeps_the_retained_work(self):
        self.spawn_all(61, 62)
        self.retained(61, 62)
        for minute, issue in ((4, 61), (5, 62)):
            self.park(issue, X, now=T(minute))
        before = {issue: self.attempt(issue) for issue in (61, 62)}
        self.assertEqual((before[62]["phase"], before[62]["suspend_phase"]), (2, 2))
        self.assertTrue(before[62]["handoff_path"] and before[62]["progress_marker"])
        reply = self.sweep(7, observed(X, NEXT), issues=(62, 61), max_parallel=1)
        self.assertEqual(self.dispatched(reply), [("resume", "62:1:3")])
        (action,) = [item for item in reply["actions"] if item["kind"] == "resume"]
        self.assertEqual((action["handoff_path"], action["deadline_at"]),
                         (before[62]["handoff_path"], "2026-08-13T20:37:00Z"))
        self.assertEqual(self.awaited(self.summaries(reply)[61]), [])
        self.assertEqual(self.blockers()[X_ID]["state"], "resolved")
        resumed = self.attempt(62)
        for field in ("attempt", "owner", "worktree", "handoff_path", "phase",
                      "progress_marker", "suspend_phase", "stalled_resumes"):
            with self.subTest(field=field):
                self.assertEqual(resumed[field], before[62][field])
        self.assertEqual(
            (resumed["state"], resumed["blocked_on"], resumed["verification_blocker"],
             resumed["launch_kind"], len(resumed["launches"]), resumed["deadline_at"]),
            ("active", None, None, "resume", 3, "2026-08-13T20:37:00Z"))
        self.assertEqual(self.attempt(61), before[61])
        self.assertEqual(self.check_launch(action_id="62:1:2")["reason"], "superseded_launch")
        self.assertEqual(self.check_launch(action_id="62:1:3")["reason"], "current")
        later = self.sweep(8, issues=(62, 61), max_parallel=2)
        self.assertEqual(self.dispatched(later), [("resume", "61:1:3")])
        self.assertEqual(self.blockers()[X_ID]["attempts"],
                         [{"issue": 61, "attempt": 1}, {"issue": 62, "attempt": 1}])

    def test_a_resumed_attempt_expires_on_its_fresh_window(self):
        self.parked((61, X))
        self.sweep(7, observed(X, NEXT), issues=(61,))
        reaped = self.sweep(37, issues=(61,))
        self.assertEqual([(delta["kind"], delta["state"]) for delta in reaped["deltas"]],
                         [("expired", "active"), ("resumed", "active")])
        self.assertEqual(self.dispatched(reaped), [("resume", "61:1:3")])
        self.assertEqual(self.blockers()[X_ID]["state"], "resolved")

    def test_the_stall_bound_still_stops_a_fourth_park(self):
        self.spawn_all(61)
        values = ["a" * 40, "b" * 40, "c" * 40, "d" * 40]
        for cycle in range(3):
            blocker = failure(value=values[cycle])
            self.park(61, blocker, now=T(2 * cycle + 1))
            reply = self.sweep(2 * cycle + 2, observed(blocker, values[cycle + 1]), issues=(61,))
            self.assertEqual(self.dispatched(reply), [("resume", f"61:1:{cycle + 2}")])
        stopped = self.park(61, failure(value=values[3]), now=T(7))
        self.assertEqual((stopped["kind"], stopped["source"], stopped["reason"]),
                         ("terminal", "lifecycle", "stopped"))
        attempt = self.attempt(61)
        self.assertEqual((attempt["state"], attempt["result_source"],
                          attempt["verification_blocker"]), ("stopped", "stalled", None))
        self.assertEqual(sorted(self.blockers()),
                         sorted(vb.blocker_id(failure(value=value)) for value in values[:3]))
        self.assertEqual({record["state"] for record in self.blockers().values()},
                         {"resolved"})


class RefusalTest(ControlHarness, unittest.TestCase):
    def test_an_observation_that_answers_no_open_blocker_exactly_is_refused(self):
        self.parked((61, X), (62, X), (63, Y))
        self.sweep(8, observed(Y, NEXT), issues=(61, 62, 63))
        before = self.tree_snapshot()
        extra = observed(X)
        extra["facts"].append({"name": "go-sum", "source": {"paths": ["go.sum"]},
                               "value": {"objects": [{"path": "go.sum", "mode": "100644",
                                                      "object": NEXT}]}})
        moved = observed(failure(path="other.lock"))
        moved["blocker_id"] = X_ID
        other = observed(X)
        other["repository"]["integration_branch"] = "release"
        malformed = {**observed(X), "schema_version": 2}
        secret = observed(X)
        secret["facts"][0]["source"]["paths"] = [".env"]
        secret["facts"][0]["value"]["objects"][0]["path"] = ".env"
        unknown = "verification[0].blocker_id: names no open blocker of this run"
        sources = "verification[0].facts: must carry the blocker's names and sources in order"
        cases = {
            "missing fact": ([{**observed(X), "facts": []}],
                             "verification[0]: facts: must be a list of 1 to 4 items"),
            "extra fact": ([extra], sources),
            "substituted source": ([moved], sources),
            "other repository": ([other],
                                 "verification[0].repository: must equal the blocker's "
                                 "repository"),
            "repeated id": ([observed(X), observed(X, NEXT)],
                            "verification[1].blocker_id: repeats an earlier observation"),
            "unknown id": ([observed(failure("environment"))], unknown),
            "resolved id": ([observed(Y, NEXT)], unknown),
            "malformed": ([malformed], "verification[0]: observation.schema_version: must be 1"),
            "secret-shaped": ([secret],
                              "verification[0]: facts[0].source.paths[0]: secret-shaped"),
        }
        for label, (observations, line) in cases.items():
            with self.subTest(case=label):
                done = self.refused(json.dumps(
                    self.request(9, *observations, issues=(61, 62, 63))).encode())
                self.assertEqual((done.returncode, done.stdout, done.stderr),
                                 (2, "", f"workflow-state: invalid verification observation: "
                                         f"{line}\n"))
                self.assertEqual(self.tree_snapshot(), before)
        text = json.dumps(self.request(9, observed(X, NEXT), issues=(61, 62, 63)))
        loads = {
            "interface 3": (json.dumps({**json.loads(text), "interface_version": 3}),
                            "unsupported control interface version"),
            "duplicate key": (text[:-1] + ', "verification": []}',
                              "invalid control request JSON: duplicate JSON key "
                              "'verification'"),
            "non-finite literal": (text.replace('"max_parallel": 2', '"max_parallel": NaN'),
                                   "invalid control request JSON: JSON constant NaN is not "
                                   "allowed"),
        }
        for label, (raw, line) in loads.items():
            with self.subTest(case=label):
                done = self.refused(raw.encode())
                self.assertEqual((done.returncode, done.stdout, done.stderr),
                                 (2, "", f"workflow-state: {line}\n"))
                self.assertEqual(self.tree_snapshot(), before)


class PersistenceTest(ControlHarness, unittest.TestCase):
    def test_a_rejected_reply_commits_no_resolution(self):
        """Issue 545 D6, #220 D5: the reply is validated before the sweep's write commits."""
        self.parked((61, X), (62, X))
        tree = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, tree, True)
        shutil.copytree(SCRIPT.parent, tree / "agent-skills/scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        policy = json.loads(BUDGET_POLICY.read_text(encoding="utf-8"))
        policy["workflow_responses"]["wire_max_bytes"] = 64
        (tree / "agent-skills/artifact-budget-policy.json").write_text(
            json.dumps(policy), encoding="utf-8")
        path = self.root / "resolving-request.json"
        path.write_text(json.dumps(self.request(7, observed(X, NEXT))), encoding="utf-8")
        before = self.tree_snapshot()
        done = subprocess.run(
            [sys.executable, str(tree / "agent-skills/scripts/workflow-state.py"), "control",
             "--repo-root", str(self.root), "--run-id", self.run_id, "--request-file",
             str(path)], capture_output=True, text=True, check=False, env=self.cli_env)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (
            2, "", "workflow-state: artifact-budget validate-report rejected the "
                   "workflow-response boundary\n"))
        self.assertEqual(self.tree_snapshot(), before)
        self.assertEqual(self.blockers()[X_ID]["state"], "open")


class WireTest(ControlHarness, unittest.TestCase):
    """Issue 545 D9, by behaviour: the validator admits the requirement only where control
    puts it."""

    def validate(self, value):
        return self.delivery_model.validate_delivery_object(
            value, expected_kind="workflow-response", notes_max_characters=4096)

    def test_the_parked_summary_is_admitted_and_nothing_near_it(self):
        self.parked((61, X), (62, X))
        reply = self.sweep(7)
        self.assertEqual(self.validate(json.loads(json.dumps(reply))), reply)
        record = self.blockers()[X_ID]
        self.assertEqual(vb.requirement(record), asked(X))
        model = self.delivery_model

        def mutated(change):
            value = json.loads(json.dumps(reply))
            change(value, value["summaries"][0])
            return value

        def added_member(value, summary):
            summary["requirements"][0]["note"] = "x"

        def removed_member(value, summary):
            del summary["requirements"][0]["sources"]

        def twice(value, summary):
            summary["requirements"].append({**asked(X), "blocker_id": "sha256:" + "f" * 64})

        def not_parked(value, summary):
            summary["state"], summary["blocked_on"] = "active", None

        def other_cause(value, summary):
            summary["blocked_on"] = "transport"

        def interface_three(value, summary):
            value["interface_version"] = 3

        for change in (added_member, removed_member, twice, not_parked, other_cause,
                       interface_three):
            with self.subTest(case=change.__name__), \
                    self.assertRaises(model.DeliveryModelError):
                self.validate(mutated(change))
        owner = self.delivery_fixtures.workflow_responses(model)["owner"]
        owner = {**json.loads(json.dumps(owner)), "requirements": [asked(X)]}
        with self.assertRaises(model.DeliveryModelError):
            self.validate(owner)

    def test_no_action_may_name_an_issue_its_summary_parks(self):
        """The reply of a real resume validates while its summary only looks parked, so the
        refusal of the same reply with the requirement is the parked-issue guard's."""
        self.parked((61, X), (62, Y))
        reply = self.sweep(7, observed(Y, NEXT))
        self.assertEqual(self.dispatched(reply), [("resume", "62:1:2")])
        model = self.delivery_model

        def parked(requirement):
            value = json.loads(json.dumps(reply))
            summary = self.summaries(value)[62]
            summary["state"], summary["blocked_on"] = "suspended", "verification"
            if requirement:
                summary["requirements"] = sorted(summary["requirements"] + [asked(Y)],
                                                 key=model.canonical_bytes)
            return value

        for value in (reply, parked(False)):
            self.assertEqual(self.validate(value), value)
        with self.assertRaises(model.DeliveryModelError):
            self.validate(parked(True))


class BootstrapTest(ControlHarness, unittest.TestCase):
    """Issue 545 D6, D9: `init-run` lists each awaited open blocker once, by id."""

    def bootstrap(self):
        done = self.run_cli("init-run", "--repo-root", self.root, "--run-id", self.run_id)
        return self.validated_response(done.stdout)

    def test_the_bootstrap_lists_the_open_blockers_awaited_until_they_resolve(self):
        self.parked((61, X), (62, Y), (63, X))
        boot = self.bootstrap()
        self.assertEqual(boot["interface_version"], 3)
        self.assertEqual(boot["verification"],
                         sorted([asked(X), asked(Y)], key=lambda item: item["blocker_id"]))
        self.assertEqual([item["issue"] for item in boot["requirements"]], [61, 62, 63])
        resolved = self.sweep(9, observed(X, NEXT), issues=(61, 62, 63), max_parallel=1)
        self.assertEqual(self.dispatched(resolved), [("resume", "61:1:2")])
        self.assertEqual(self.bootstrap()["verification"], [asked(Y)])
        self.sweep(10, observed(Y, NEXT), issues=(61, 62, 63), max_parallel=1)
        self.assertEqual({record["state"] for record in self.blockers().values()},
                         {"resolved"})
        self.assertEqual(self.bootstrap()["verification"], [])

    def test_the_validator_admits_only_interface_three(self):
        self.parked((61, X), (62, Y))
        boot = self.bootstrap()
        model = self.delivery_model

        def mutated(change):
            value = json.loads(json.dumps(boot))
            change(value)
            return value

        def interface_two(value):
            value["interface_version"] = 2

        def without_member(value):
            del value["verification"]

        def unsorted(value):
            value["verification"].reverse()

        def repeated(value):
            value["verification"].append(value["verification"][0])

        def opened(value):
            value["verification"][0]["note"] = "x"

        def other_kind(value):
            value["verification"][0]["kind"] = "worktree_fact"

        def null_kind(value):
            value["verification"][0]["kind"] = None

        self.assertEqual(model.validate_delivery_object(
            boot, expected_kind="workflow-response", notes_max_characters=4096), boot)
        for change in (interface_two, without_member, unsorted, repeated, opened, other_kind,
                       null_kind):
            with self.subTest(case=change.__name__), \
                    self.assertRaises(model.DeliveryModelError):
                model.validate_delivery_object(
                    mutated(change), expected_kind="workflow-response",
                    notes_max_characters=4096)


if __name__ == "__main__":
    unittest.main()
