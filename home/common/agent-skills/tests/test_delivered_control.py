"""Control never launches a delivered issue and never commits a rejected reply (#220)."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
import unittest

from .test_delivery_workflow import (ARTIFACT_BUDGET, MODEL, NOW, POLICY, SOURCES,
                                     BuilderHarness, load)

DELIVERED, LIVE = 207, 209
ISSUES = (DELIVERED, LIVE)
PROPOSED = {"merge_pr", "close_tracker", "remove_worktree", "delete_local_branch"}
DISPATCH = {"spawn", "resume", "retry", "delivery_remainder"}


def at(minute):
    start = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    return (start + timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ")


class DeliveredControlTest(BuilderHarness, unittest.TestCase):
    """The issue-207 shape of run-20260927-204-205-206-207-208-209 over the real CLI."""

    @classmethod
    def setUpClass(cls):
        cls.model = load(MODEL, "delivery_model_delivered_control", package=True)

    def boundary(self, name, raw):
        """Run the real artifact-budget validator; return the completed process."""
        return subprocess.run(
            [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
             name, "--input", "-", "--policy", str(POLICY)],
            input=raw if isinstance(raw, bytes) else json.dumps(raw).encode(),
            capture_output=True, check=False)

    def validated(self, name, value):
        checked = self.boundary(name, value)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        return checked.stdout

    def setup_run(self):
        self.project()
        (self.home / ".agents/share/host-declaration.json").write_text(json.dumps(
            {"schema_version": 1, "routes": {
                "claude-code": {"support": "supported", "agent_slots": 7},
                "codex": {"support": "unsupported"}}}), encoding="utf-8")
        self.run_args = ("--repo-root", self.root, "--run-id", "delivered")
        self.ledger = self.root / ".superpowers/workflows/delivered/state.json"
        self.cli("init-run", *self.run_args, "--now", at(0))
        self.worktrees = {n: str(self.root / ".worktrees" / f"worktree-issue-{n}-shape")
                          for n in ISSUES}
        self.built = {n: self.build("contract", self.contract_input(
            issue=n, worktree=self.worktrees[n], now=at(0),
            source_reference="invocation:/orchestrate-issues 207 209")) for n in ISSUES}

    def request(self, minute, *, recorded, owners=(), contracts=False, closed=(),
                recoveries=None):
        """One control request over the issues ``recorded`` names, in its order.

        ``recorded`` maps each issue to its recorded worktree state, or to None
        for a spawn at the absent candidate path. Issues in ``closed`` are
        observed with a closed tracker, as the adapter sees a delivered issue.
        ``recoveries`` maps an issue to the recovery proof its request carries.
        """
        issues = list(recorded)
        def fact(n):
            if recorded[n] is None:
                return {"issue": n, "recorded": None,
                        "candidate": {"path": self.worktrees[n], "state": "absent"}}
            return {"issue": n, "candidate": None,
                    "recorded": {"path": self.worktrees[n], "state": recorded[n]}}
        request = self.control_request(
            issues, now=at(minute),
            contracts={str(n): self.built[n]["contract"] if contracts else None
                       for n in issues},
            intents={str(n): [self.built[n]["initial_intent"]] if contracts else []
                     for n in issues},
            worktrees=[fact(n) for n in issues])
        request["owners"] = list(owners)
        for n, proof in (recoveries or {}).items():
            request["recoveries"][str(n)] = proof
        for item in request["tracker"]:
            if item["issue"] in closed:
                item["state"] = "closed"
        return json.dumps(request).encode()

    def control(self, minute, **kwargs):
        completed = self.cli("control", *self.run_args, "--request-file", "-",
                             stdin=self.request(minute, **kwargs))
        return json.loads(self.validated("workflow-response", completed.stdout))

    def observed(self, contract, when, kind, **facts):
        return self.build("observation", {"contract": contract,
            "observation_kind": kind, "source_kind": SOURCES[kind],
            "source_reference": f"probe:{kind}", "observed_at": when,
            "evidence": f"{kind} evidence", **facts})

    def fail_after_selection(self, custody, when):
        """The implementation custody stops after selecting; remainder r1 takes over."""
        contract = self.built[DELIVERED]["contract"]
        digest = self.model.canonical_digest(contract)
        self.selection = self.build("selected-output", {"contract": contract,
            "head": "a" * 40, "tree": "c" * 40,
            "acceptance_ref": f".claude/specs/issue-{DELIVERED}.md",
            "review_ref": "clean", "test_ref": "checks"})
        self.selected = self.observed(contract, when, "selected_output",
                                      selection=self.selection)
        historical = {"issue": DELIVERED, "state": "failed", "pr_url": None,
            "merge_sha": None, "issue_closed": False, "discussion_items": [],
            "detail_state": "none", "report_path": None, "notes": "failed after selection"}
        summary = {"interface_version": 2, "issue": DELIVERED, "state": "terminal_failed",
            "custody": custody, "historical_owner_result": historical,
            "delivery_contract_digest": digest, "delivery_observations": [self.selected],
            "authority_observations": [], "reevaluation_evidence": [],
            "detail_state": "none", "report_path": None, "notes": "failed after selection"}
        remainder = json.loads(self.cli("finish", *self.run_args, "--now", when,
            "--summary-file", "-", stdin=self.validated("ship-summary", summary)).stdout)
        self.assertEqual(remainder["kind"], "delivery_remainder")
        return remainder

    def deliver(self, custody, when):
        """Remainder custody walks every remaining stage and finishes delivery_complete."""
        issue, contract = DELIVERED, self.built[DELIVERED]["contract"]
        digest = self.model.canonical_digest(contract)
        url = f"https://github.com/fagenorn/nix-config/pull/{issue}"
        head, merge_sha = "a" * 40, "b" * 40
        observed = lambda kind, **facts: self.observed(contract, when, kind, **facts)
        facts = {
            "select_reviewed_output": [],
            "publish_branch": [observed("branch_published", head=head)],
            "open_pr": [observed("pr_opened", pr_number=issue, pr_url=url, head=head)],
            "merge_pr": [observed("pr_merged", pr_number=issue, pr_url=url, head=head,
                                  merge_sha=merge_sha)],
            "close_tracker": [observed("tracker_closed", close_reason="completed",
                                       observation_identity=f"github:issue:{issue}:closed")],
            "delete_remote_branch": [observed("remote_branch_absent")],
            "remove_worktree": [observed("worktree_absent")],
            "delete_local_branch": [observed("local_branch_absent")]}
        pending, authority = [], []
        for stage in contract["stages"]:
            if stage["id"] in PROPOSED:
                scope = self.build("scope", {"contract": contract, "stage_id": stage["id"]})
                self.cli("checkpoint-delivery", *self.run_args, "--now", when,
                    "--checkpoint-file", "-", stdin=self.validated("ship-checkpoint", {
                        "interface_version": 2, "issue": issue, "custody": custody,
                        "contract_digest": digest,
                        "delivery_observations": sorted(pending, key=lambda i: i["id"]),
                        "authority_observations": authority, "reevaluation_evidence": [],
                        "requested_scope": scope, "detail_state": "none",
                        "report_path": None, "notes": ""}))
                pending, authority = [], [self.build("authority-observation", {
                    "contract": contract, "scope_id": scope["id"],
                    "launch_id": custody["action_id"], "authority_kind": "native_guard",
                    "verdict": "allowed", "reason_code": "guard_allowed",
                    "observed_at": when, "evidence": stage["id"]})]
            pending += facts[stage["id"]]
        by_kind = {i["observation_kind"]: i["id"] for items in facts.values() for i in items}
        completing = pending + [
            observed("implementation_delivered", selection=self.selection,
                     merge_sha=merge_sha, integrated_ref="refs/heads/main",
                     merge_observation_id=by_kind["pr_merged"]),
            observed("cleanup_complete",
                     remote_branch_observation_ids=[by_kind["remote_branch_absent"]],
                     local_branch_observation_ids=[by_kind["local_branch_absent"]],
                     worktree_observation_ids=[by_kind["worktree_absent"]],
                     detail_pointer=f".superpowers/issue-delivery/{issue}/detail.json",
                     read_evidence="detail read")]
        historical = {"issue": issue, "state": "merged", "pr_url": url,
            "merge_sha": merge_sha, "issue_closed": True, "discussion_items": [],
            "detail_state": "none", "report_path": None, "notes": "delivered"}
        summary = {"interface_version": 2, "issue": issue, "state": "delivery_complete",
            "custody": custody, "historical_owner_result": historical,
            "delivery_contract_digest": digest,
            "delivery_observations": sorted(completing, key=lambda i: i["id"]),
            "authority_observations": authority, "reevaluation_evidence": [],
            "detail_state": "none", "report_path": None, "notes": "delivered"}
        finished = json.loads(self.cli("finish", *self.run_args, "--now", when,
            "--summary-file", "-", stdin=self.validated("ship-summary", summary)).stdout)
        self.assertEqual(finished["kind"], "delivery_complete")

    def delivered_shape(self):
        """Drive 207 to delivery through r1 after four launches, then spawn 209.

        Attempt 1 of 207 is spawned at minute 0 and resumed after each expiry at
        minutes 31, 62 and 93 (launches 2 to 4). It fails after selection at 94,
        minting r1 with deadline minute 274, and r1 finishes delivery_complete at
        95. 209 spawns at 250, with 207 observed closed and its worktree absent, so
        209's launch 1 is live until minute 280, past r1's deadline. Returns
        209's custody.
        """
        self.setup_run()
        spawned = self.control(0, recorded={DELIVERED: None}, contracts=True)
        launched = [a["custody"] for a in spawned["actions"] if a["kind"] in DISPATCH]
        for minute in (31, 62, 93):
            response = self.control(minute, recorded={DELIVERED: "matching_issue_branch"})
            launched = [a["custody"] for a in response["actions"] if a["kind"] in DISPATCH]
        self.assertEqual([c["action_id"] for c in launched], [f"{DELIVERED}:1:4"])
        remainder = self.fail_after_selection(launched[0], at(94))
        self.assertEqual((remainder["custody"]["action_id"], remainder["deadline_at"]),
                         (f"{DELIVERED}:r1:1", at(274)))
        self.deliver(remainder["custody"], at(95))
        spawned = self.control(250, recorded={DELIVERED: "absent", LIVE: None},
                               contracts=True, closed={DELIVERED})
        live = [a["custody"] for a in spawned["actions"] if a["kind"] in DISPATCH]
        self.assertEqual([c["action_id"] for c in live], [f"{LIVE}:1:1"])
        return live[0]

    def records(self, issue):
        """The ledger's attempts and remainders for ``issue``, as stored."""
        stored = json.loads(self.ledger.read_text(encoding="utf-8"))["issues"][str(issue)]
        return stored["attempts"], stored["delivery_remainders"]

    def after_delivery(self, minute, live, *, recorded=None, **kwargs):
        """The sweep that follows delivery: 209's owner is reported unavailable."""
        return self.cli("control", *self.run_args, "--request-file", "-", ok=False,
            stdin=self.request(minute, recorded=recorded or {
                                   DELIVERED: "absent", LIVE: "matching_issue_branch"},
                               closed={DELIVERED},
                               owners=[{"event_id": "209-unavailable", "issue": LIVE,
                                        "custody": live, "state": "unavailable"}],
                               **kwargs))

    def assert_only_live_resumed(self, completed, before):
        """Exit 0, a boundary-valid reply, 209's resume only, 207 untouched."""
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        checked = self.boundary("workflow-response", completed.stdout)
        self.assertEqual((checked.returncode, checked.stderr), (0, b""))
        self.assertEqual(checked.stdout, completed.stdout)
        response = json.loads(completed.stdout)
        dispatched = [a for a in response["actions"] if a["kind"] in DISPATCH]
        self.assertEqual([(a["issue"], a["custody"]["action_id"]) for a in dispatched],
                         [(LIVE, f"{LIVE}:1:2")])
        self.assertFalse([a for a in response["actions"] if a.get("issue") == DELIVERED])
        self.assertEqual([d for d in response["deltas"] if d["issue"] == DELIVERED], [])
        self.assertNotIn(DELIVERED, response["admission"]["waiting"])
        self.assertEqual(self.records(DELIVERED), before)
        return response

    def test_a_delivered_issue_is_never_relaunched(self):
        """Acceptance 1: past r1's deadline, control plans nothing for delivered 207.

        At the base commit the reaper suspends the still-active r1 and the resume
        lane relaunches it as `207:1:2` with null custody, which the boundary
        rejects after the ledger has committed the launch.
        """
        live = self.delivered_shape()
        before = self.records(DELIVERED)
        self.assert_only_live_resumed(self.after_delivery(275, live), before)

    def test_a_stale_delivered_custody_is_reported_not_dispatched(self):
        """Acceptance 3: a pre-fix sweep's extra r1 launch is reported, never dispatched."""
        live = self.delivered_shape()
        pristine = self.ledger.read_bytes()
        stored = json.loads(pristine)
        remainder = stored["issues"][str(DELIVERED)]["delivery_remainders"][0]
        # The launch a pre-fix sweep committed: a resume at the ledger's last write.
        remainder["launches"].append({"kind": "resume", "owner": remainder["owner"],
                                      "worktree": remainder["worktree"],
                                      "at": stored["updated_at"]})
        self.ledger.write_text(json.dumps(stored), encoding="utf-8")
        loaded = json.loads(self.cli("current-launch", *self.run_args, "--action-id",
                                     f"{DELIVERED}:r1:2").stdout)
        self.assertFalse(loaded["current"])
        before = self.records(DELIVERED)
        stale = self.after_delivery(251, live)
        self.assertEqual(stale.returncode, 0, stale.stderr.decode())
        self.validated("workflow-response", stale.stdout)
        response = json.loads(stale.stdout)
        self.assertFalse([a for a in response["actions"] if a.get("issue") == DELIVERED])
        self.assertFalse([d for d in response["deltas"] if d["issue"] == DELIVERED])
        summary = next(s for s in response["summaries"] if s["issue"] == DELIVERED)
        self.assertEqual(summary["custody"], {"kind": "remainder", "remainder": 1,
                                              "launch": 2, "action_id": f"{DELIVERED}:r1:2"})
        self.assertEqual((summary["state"], summary["pending_stage_ids"]), ("closed", []))
        self.assertIsNotNone(summary["contract_digest"])
        # The delivered signature (per D13): live custody with every stage observed
        # also has empty pending stages, but owes postconditions and names an owner.
        self.assertEqual(summary["requirements"], [])
        self.assertIsNone(summary["owner"])
        self.assertEqual(self.records(DELIVERED), before)
        # The same sweep over the unamended ledger differs only in the named launch.
        self.ledger.write_bytes(pristine)
        clean = self.after_delivery(251, live)
        self.assertEqual(clean.returncode, 0, clean.stderr.decode())
        baseline = next(s for s in json.loads(clean.stdout)["summaries"]
                        if s["issue"] == DELIVERED)
        self.assertEqual(baseline["custody"]["action_id"], f"{DELIVERED}:r1:1")
        self.assertEqual({**baseline, "custody": summary["custody"]}, summary)

    def test_a_delivered_candidate_observation_is_skipped(self):
        """The post-restart shape: the adapter reports only 207's candidate worktree.

        Delivered 207's verdict carries no `custody_kind`, so without the replay
        loop's delivered skip (Step 3 item 4) this sweep raises `current control
        action requires a recorded worktree observation` (per D12, D14).
        """
        live = self.delivered_shape()
        before = self.records(DELIVERED)
        self.assert_only_live_resumed(self.after_delivery(
            275, live, recorded={DELIVERED: None, LIVE: "matching_issue_branch"}), before)

    def test_a_delivered_recovery_proof_is_not_consumed(self):
        """A structurally valid recovery proof for 207 is ignored, not refused (per D9).

        At the base commit `recovery_policy` refuses the whole sweep, since r1 is
        not a terminal failed first remainder; the gate never reaches it.
        """
        live = self.delivered_shape()
        before = self.records(DELIVERED)
        contract = self.built[DELIVERED]["contract"]
        scope = self.build("scope", {"contract": contract, "stage_id": "merge_pr"})
        evidence = lambda kind, when, digit: {"source_kind": kind,
            "reference": f"{kind}:probe", "observed_at": at(when),
            "evidence_digest": "sha256:" + digit * 64}
        proof = {"schema_version": 1, "kind": "delivery-recovery", "id": "",
            "contract_digest": self.model.canonical_digest(contract),
            "stage_id": "merge_pr", "requested_scope": scope,
            "failure": {"kind": "effect_failure", "effect_attempted": True,
                        "classification": "transient", **evidence("host", 260, "4")},
            "effect_absence": {"kind": "effect_absence", "absent": True,
                               "probe_succeeded": True, **evidence("filesystem", 261, "5")},
            "basis": {"kind": "changed_relevant_evidence", "scope_id": scope["id"],
                      **evidence("tracker", 261, "6")}}
        proof["id"] = self.model.canonical_digest(proof, omit_derived="id")
        self.assert_only_live_resumed(self.after_delivery(
            275, live, contracts=True, recoveries={DELIVERED: proof}), before)
        self.assertEqual(len(self.records(DELIVERED)[1]), 1)


if __name__ == "__main__":
    unittest.main()
