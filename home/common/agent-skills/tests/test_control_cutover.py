"""Control-plane cutover to core state (#339), through the CLI from source.

Run: just agent-workflow-tests
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools import attempt_custody as ac
from agent_tools import attempt_delivery as ad

from .test_attempt_custody import DeliveredCustody
from .test_delivered_control import DELIVERED, DISPATCH, LIVE, at
from .test_delivery_workflow import WORKFLOW

REPO = Path(__file__).resolve().parents[4]
BASE_COMMIT = "079b835c54fabe6baf550097c40debc595a81bda"
RUN_ID = re.compile(rb"rel_[0-9a-f-]{36}")
MERGED = {"state": "merged", "url": f"https://github.com/fagenorn/nix-config/pull/{DELIVERED}",
          "merge_sha": "b" * 40}
ROLES = {"owner": 1, "reviewer": 1, "worker": 1}
MATCHING = {DELIVERED: "matching_issue_branch"}
BOTH = {**MATCHING, LIVE: "matching_issue_branch"}


class Cutover(DeliveredCustody):
    """`DeliveredCustody` over either helper generation: `cli` runs this checkout's helper
    ("head") or the whole package-2 helper extracted from `BASE_COMMIT` ("base", D16)."""

    generation = "head"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        found = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e",
                                f"{BASE_COMMIT}^{{commit}}"], capture_output=True)
        if found.returncode != 0:
            raise AssertionError(
                f"base commit {BASE_COMMIT} is missing; fetch it, do not skip (D16)")
        cls.base = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, cls.base, True)
        archive = subprocess.run(
            ["git", "-C", str(REPO), "archive", BASE_COMMIT, "python/agent_tools",
             "home/common/agent-skills/scripts",
             "home/common/agent-skills/artifact-budget-policy.json"],
            capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(cls.base)], input=archive.stdout, check=True)

    def cli(self, *args, stdin=None, ok=True, cwd=None):
        if self.generation == "head":
            return super().cli(*args, stdin=stdin, ok=ok, cwd=cwd)
        completed = subprocess.run(
            [sys.executable, str(self.base / WORKFLOW.relative_to(REPO)), *map(str, args)],
            input=stdin, capture_output=True, check=False, cwd=cwd,
            env={**os.environ, "HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1",
                 "PYTHONPATH": str(self.base / "python")})
        if ok:
            self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        return completed

    def declare(self, slots):
        (self.home / ".agents/share/host-declaration.json").write_text(json.dumps(
            {"schema_version": 1, "routes": {
                "claude-code": {"support": "supported", "agent_slots": slots},
                "codex": {"support": "unsupported"}}}), encoding="utf-8")

    def transaction(self, key):
        identity = self.core().lookup(key)
        return None if identity is None else self.core().load(identity)

    def remainder(self, issue, ordinal=1):
        return self.transaction(ad.remainder_key(
            self.ledger_document()["transaction_id"], issue, ordinal))

    def delivery(self, issue, ordinal=1):
        digest = self.ledger_document()["issues"][str(issue)]["delivery"]["contract_digest"]
        return self.transaction(ad.delivery_key(issue, digest, ordinal))

    def claim_ids(self, transaction):
        return [entry["evidence_id"] for entry in transaction.evidence
                if entry["evidence_id"].startswith("admission-claim:")]

    def launched(self, reply):
        return [a["custody"]["action_id"] for a in reply["actions"] if a["kind"] in DISPATCH]

    def reason(self, transaction):
        """The reason of the transaction's last lifecycle transition."""
        return [event["reason"] for event in transaction.events
                if event["type"] == "transitioned"][-1]

    def sweep(self, minute, *, forge=None, observations=None, max_parallel=2, ok=True,
              **kwargs):
        """One control sweep as bytes in, completed process out; `kwargs` as `request`."""
        request = json.loads(self.request(minute, **kwargs))
        request["max_parallel"] = max_parallel
        for issue, fact in (forge or {}).items():
            request["forge"][str(issue)] = fact
        for issue, items in (observations or {}).items():
            request["delivery_observations"][str(issue)] = items
        return self.cli("control", *self.run_args, "--request-file", "-",
                        stdin=json.dumps(request).encode(), ok=ok)

    def reply(self, minute, **kwargs):
        return json.loads(self.validated("workflow-response",
                                         self.sweep(minute, **kwargs).stdout))

    def held(self, state="unavailable", issue=LIVE, launch=1):
        return {"event_id": f"{issue}-{state}-{launch}", "issue": issue, "state": state,
                "custody": {"kind": "implementation", "attempt": 1, "launch": launch,
                            "action_id": f"{issue}:1:{launch}"}}

    def failing(self, action_id, minute):
        """The owner of launch `action_id` reports `failed` before selecting an output."""
        issue, attempt, launch = action_id.split(":")
        custody = {"kind": "implementation", "attempt": int(attempt), "launch": int(launch),
                   "action_id": action_id}
        return self.finish(self.summary(custody, "failed"), minute)

    def select(self, minute):
        """Observe 207's selected output through a sweep, so `deliver` can follow."""
        contract = self.built[DELIVERED]["contract"]
        self.selection = self.build("selected-output", {
            "contract": contract, "head": "a" * 40, "tree": "c" * 40,
            "acceptance_ref": f".claude/specs/issue-{DELIVERED}.md", "review_ref": "clean",
            "test_ref": "checks"})
        selected = self.observed(contract, at(minute), "selected_output",
                                 selection=self.selection)
        return self.sweep(minute, recorded=MATCHING, contracts=True,
                          observations={DELIVERED: [selected]})

    def rewrite(self, change):
        """Edit the stored ledger by hand, in the helper's own serialization."""
        document = self.ledger_document()
        change(document)
        self.ledger.write_text(
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8")

    def four_slots(self):
        """Two issues on a four-slot route: 207 is launched and 209 waits for a role set."""
        self.setup_run()
        self.declare(4)
        first = self.reply(0, recorded={DELIVERED: None, LIVE: None}, contracts=True)
        self.assertEqual(first["admission"]["waiting"], [LIVE])

    def reconciled(self):
        """207 is spawned under a contract and merged on the forge by minute 31: that sweep
        reconciles attempt 1 and launches remainder r1, whose custody is returned."""
        self.spawn(DELIVERED)
        reply = self.reply(31, recorded=MATCHING, forge={DELIVERED: MERGED})
        (custody,) = [a["custody"] for a in reply["actions"] if a["kind"] in DISPATCH]
        self.assertEqual(custody["action_id"], f"{DELIVERED}:r1:1")
        return custody

    def delivered(self):
        """`reconciled`, then remainder r1 selects an output and completes the delivery."""
        custody = self.reconciled()
        self.select(32)
        self.deliver(custody, at(33))


class SpanClaimTest(Cutover, unittest.TestCase):
    def test_an_unavailable_owner_gives_its_span_up_in_that_write(self):
        self.spawn(DELIVERED, LIVE)
        withheld = self.reply(5, recorded=BOTH, owners=[self.held()], max_parallel=1)
        self.assertEqual(self.launched(withheld), [])
        released = {claim["holder"]: claim["release_event"]
                    for claim in self.ledger_document()["admission"]["claims"]}
        self.assertEqual((self.records(LIVE)[0][0]["state"], released[f"{LIVE}:1:1"]),
                         ("active", "owner_unavailable"))
        gone = self.custody(LIVE)
        self.assertEqual((gone.state, gone.custody, self.lease(self.worktrees[LIVE])["holder"]),
                         ("created", None, None))
        taken = self.reply(6, recorded=BOTH, owners=[self.held()])
        self.assertEqual(self.launched(taken), [f"{LIVE}:1:2"])
        held = self.custody(LIVE)
        self.assertEqual((held.custody.executor_id, self.claim_ids(held)[-1]),
                         (f"{LIVE}:1:2", f"admission-claim:{LIVE}:1:2:2"))

    def test_a_delivered_record_holds_no_span(self):
        self.delivered()
        held = self.remainder(DELIVERED)
        self.assertIsNotNone(held)
        self.assertEqual((self.records(DELIVERED)[1][0]["state"], held.custody,
                          self.lease(self.worktrees[DELIVERED])["holder"]),
                         ("active", None, None))


class CapacityWakeTest(Cutover, unittest.TestCase):
    def refused(self):
        custody = self.spawn(DELIVERED, LIVE)
        reply = self.reply(1, recorded=BOTH, owners=[self.held("launch_refused")])
        self.assertEqual(reply["admission"]["waiting"], [LIVE])
        return custody

    def test_ac2_a_refused_launch_parks_and_the_freeing_write_wakes_it(self):
        self.refused()
        parked = self.custody(LIVE)
        self.assertEqual((parked.state, parked.custody, self.reason(parked)),
                         ("attention_required", None, "suspended:host_capacity"))
        before = self.tree()
        self.assertEqual(self.reply(2, recorded=BOTH)["admission"]["waiting"], [LIVE])
        self.assertEqual(self.tree(), before)
        self.failing(f"{DELIVERED}:1:1", 3)  # another owner's exit frees capacity
        woken = self.custody(LIVE)
        self.assertEqual((woken.state, woken.custody, self.reason(woken)),
                         ("created", None, "capacity_released"))
        resumed = self.reply(4, recorded=BOTH)
        self.assertIn(f"{LIVE}:1:2", self.launched(resumed))
        self.assertEqual(self.custody(LIVE).custody.executor_id, f"{LIVE}:1:2")

    def test_ac2_a_waiting_issue_spends_nothing_and_is_admitted_when_the_span_closes(self):
        self.four_slots()
        held = self.custody(DELIVERED)
        self.assertEqual((held.custody.executor_id, self.claim_ids(held)),
                         (f"{DELIVERED}:1:1", [f"admission-claim:{DELIVERED}:1:1:1"]))
        document = self.ledger_document()
        self.assertIsNone(self.core().lookup(
            ac.creation_key(document["transaction_id"], LIVE, 1)))
        self.assertFalse(document["issues"].get(str(LIVE), {"attempts": []})["attempts"])
        before = self.tree()
        waiting = {DELIVERED: "matching_issue_branch", LIVE: None}
        idle = self.reply(1, recorded=waiting, contracts=True)
        self.assertEqual((idle["admission"]["waiting"], self.tree()), ([LIVE], before))
        self.select(2)
        self.deliver({"kind": "implementation", "attempt": 1, "launch": 1,
                      "action_id": f"{DELIVERED}:1:1"}, at(3))
        self.assertIsNone(self.custody(DELIVERED).custody)  # closed by the owner's command
        admitted = self.reply(4, recorded={DELIVERED: "absent", LIVE: None}, contracts=True,
                              closed={DELIVERED})
        self.assertEqual(self.launched(admitted), [f"{LIVE}:1:1"])

    def test_ac2_check_launch_prints_the_base_bytes_and_touches_nothing(self):
        self.generation = "base"
        self.spawn(DELIVERED)
        elsewhere = ("--repo-root", self.root, "--run-id",
                     "rel_01890a5d-ac96-774b-bcce-b302099a8057")
        probes = [(self.run_args, f"{DELIVERED}:1:1"), (self.run_args, "999:1:1"),
                  (self.run_args, f"{DELIVERED}:2:1"), (elsewhere, f"{DELIVERED}:1:1")]

        def answers():
            return [self.cli("check-launch", *run, "--action-id", action).stdout
                    for run, action in probes]

        expected, before = answers(), self.tree()
        self.generation = "head"
        self.assertEqual((answers(), self.tree()), (expected, before))  # a schema-9 ledger
        self.cli("migrate", "--repo-root", self.root, "--apply")
        self.assertEqual(self.ledger_document()["schema_version"], 10)
        bound = self.tree()
        self.assertEqual((answers(), self.tree()), (expected, bound))


class SchemaTenTest(Cutover, unittest.TestCase):
    def migrate(self, *flags):
        return json.loads(self.cli("migrate", "--repo-root", self.root, *flags).stdout)

    def schema_nine(self, fixture):
        """Run `fixture` on the package-2 helper and return to this one (D16)."""
        self.generation = "base"
        fixture()
        self.generation = "head"
        self.assertEqual(self.ledger_document()["schema_version"], 9)

    def test_ac4_the_bind_is_dry_run_first_and_the_base_helper_refuses_schema_10(self):
        def fixture():
            self.spawn(DELIVERED, LIVE)
            self.reply(1, recorded=BOTH, owners=[self.held("launch_refused")])

        self.schema_nine(fixture)
        before = self.tree()
        (row,) = self.migrate()["ledgers"]
        self.assertEqual((row["schema_version"], row["verdict"], row["reason"]),
                         (9, "migrate", None))
        self.assertEqual(self.tree(), before)
        (row,) = self.migrate("--apply")["ledgers"]
        self.assertEqual((row["schema_version"], row["verdict"]), (10, "migrated"))
        self.assertEqual(self.claim_ids(self.custody(DELIVERED)),
                         [f"admission-claim:{DELIVERED}:1:1:1"])
        self.assertEqual(self.custody(LIVE).state, "attention_required")
        bound = self.tree()
        self.assertEqual(self.migrate("--apply")["ledgers"][0]["verdict"], "current")
        self.assertEqual(self.tree(), bound)
        self.generation = "base"
        for command in (("check-launch", "--action-id", f"{DELIVERED}:1:1"),
                        ("register-worker", "--action-id", f"{DELIVERED}:1:1", "--now", at(2))):
            with self.subTest(command=command[0]):
                refused = self.cli(command[0], *self.run_args, *command[1:], ok=False)
                self.assertEqual(refused.returncode, 2, refused.stdout)
                self.assertIn(b"unknown_schema", refused.stderr)
                self.assertEqual(self.tree(), bound)

    def test_the_bind_gives_a_live_remainder_custody_at_its_launch_count(self):
        self.schema_nine(self.reconciled)
        self.assertIsNone(self.remainder(DELIVERED))
        self.migrate("--apply")
        held = self.remainder(DELIVERED)
        self.assertIsNotNone(held)
        self.assertEqual((held.subject["bound_launch"], held.custody.executor_id, held.state),
                         (1, f"{DELIVERED}:r1:1", "created"))
        self.assertEqual(self.claim_ids(held), [f"admission-claim:{DELIVERED}:r1:1:2"])


class StoreReadTest(Cutover, unittest.TestCase):
    def test_ac1_occupancy_is_counted_from_the_store(self):
        self.four_slots()

        def drop(document):
            claims = document["admission"]["claims"]
            claims[:] = [c for c in claims if c["holder"] != f"{DELIVERED}:1:1"]

        self.rewrite(drop)
        report = self.reply(1, recorded={DELIVERED: "matching_issue_branch", LIVE: None},
                            contracts=True)["admission"]
        self.assertEqual((report["waiting"], report["reserved"], report["available"]),
                         ([LIVE], {"controller": 1, **ROLES}, 0))
        self.assertIsNone(self.custody(LIVE))

    def test_a_cut_suspension_keeps_its_slot(self):
        self.four_slots()
        self.core(at(1)).release(self.custody(DELIVERED).custody)
        report = self.reply(2, recorded={**MATCHING, LIVE: None}, contracts=True)["admission"]
        self.assertEqual((report["waiting"], report["reserved"], report["available"]),
                         ([LIVE], {"controller": 1, **ROLES}, 0))
        self.assertIsNone(self.custody(LIVE))

    def test_the_capacity_gate_is_read_from_the_store(self):
        self.spawn(DELIVERED, LIVE)
        self.reply(1, recorded=BOTH, owners=[self.held("launch_refused")])
        self.failing(f"{DELIVERED}:1:1", 3)

        def swap(document):  # by the block alone, the refusal now came last
            claims = {c["holder"]: c for c in document["admission"]["claims"]}
            freed, refused = claims[f"{DELIVERED}:1:1"], claims[f"{LIVE}:1:1"]
            freed["release_seq"], refused["release_seq"] = (refused["release_seq"],
                                                            freed["release_seq"])

        self.rewrite(swap)
        resumed = self.reply(4, recorded=BOTH)
        self.assertNotIn(LIVE, resumed["admission"]["waiting"])
        self.assertIn(f"{LIVE}:1:2", self.launched(resumed))

    def test_a_remainders_occupancy_is_counted_from_the_store(self):
        self.four_slots()
        waiting = {**MATCHING, LIVE: None}
        for minute in (31, 32):
            self.reply(minute, recorded=waiting, contracts=True, forge={DELIVERED: MERGED})
        held = f"{DELIVERED}:r1:1"
        self.assertEqual(self.claim_ids(self.remainder(DELIVERED)),
                         [f"admission-claim:{held}:2"])

        def drop(document):
            claims = document["admission"]["claims"]
            claims[:] = [c for c in claims if c["holder"] != held]

        self.rewrite(drop)
        report = self.reply(33, recorded=waiting, contracts=True,
                            forge={DELIVERED: MERGED})["admission"]
        self.assertEqual((report["waiting"], report["reserved"], report["available"]),
                         ([LIVE], {"controller": 1, **ROLES}, 0))
        self.assertIsNone(self.custody(LIVE))

    def test_a_parked_suspension_resumes_in_the_sweep_that_frees_capacity(self):
        self.spawn(DELIVERED, LIVE)
        self.reply(1, recorded=BOTH, owners=[self.held("launch_refused")])
        self.assertEqual(self.custody(LIVE).state, "attention_required")
        freed = self.reply(2, recorded=BOTH, owners=[self.held(issue=DELIVERED)])
        self.assertNotIn(LIVE, freed["admission"]["waiting"])
        self.assertIn(f"{LIVE}:1:2", self.launched(freed))
