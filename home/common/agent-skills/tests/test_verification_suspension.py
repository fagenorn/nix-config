"""Ledger schema 11 and shared verification blockers (issue 544), through the CLI from source.

Run: just agent-workflow-tests
"""

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools import attempt_custody as ac
from agent_tools import verification_blocker as vb
from agent_tools.transaction_core import TransactionStore

from .test_workflow_state import LifecycleHarness

# The delivery base: the schema-10 helper this change must not be read by (issue 544 D9).
BASE_COMMIT = "87d6065fc1749c0b7b6c427beb9b1d3051bc198d"
REPO = Path(__file__).resolve().parents[4]
HELPER = Path("home/common/agent-skills/scripts/workflow-state.py")
T = "2026-08-13T20:{:02d}:00Z".format


class LedgerHarness(LifecycleHarness):
    """Orchestrated attempts in a temporary ledger root, and the ledger at older schemas."""

    def worktree(self, issue):
        return str((self.root / f"wt-{issue}").resolve())

    def spawn_all(self, *issues):
        self.init_run()
        for issue in issues:
            self.spawn(issue=issue, worktree=self.worktree(issue))

    def migrate(self, *flags):
        completed = self.run_cli("migrate", "--repo-root", self.root, *flags)
        return json.loads(completed.stdout)["ledgers"]

    def assert_locked_refusal(self, state, line):
        """`state`, written as the ledger, is refused by a locked read with `line`; nothing
        under `.superpowers` changes."""
        self.write_state(state)
        before = self.tree_snapshot()
        done = self.run_cli("init-run", "--repo-root", self.root, "--run-id", self.run_id,
                            ok=False)
        self.assertEqual((done.returncode, done.stdout, done.stderr),
                         (2, "", f"workflow-state: {line}\n"))
        self.assertEqual(self.tree_snapshot(), before)


class SchemaElevenTest(LedgerHarness, unittest.TestCase):
    def test_a_new_ledger_is_schema_eleven_with_no_blockers(self):
        self.spawn_all(61)
        state = self.read_state()
        self.assertEqual((state["schema_version"], state["verification_blockers"]), (11, {}))
        self.assertIsNone(state["issues"]["61"]["attempts"][0]["verification_blocker"])

    def test_a_schema_ten_ledger_migrates_strictly(self):
        self.spawn_all(61)
        current = self.read_state()
        self.write_state(self._as_legacy(current, 10))
        before = self.tree_snapshot()
        self.assertEqual([(row["schema_version"], row["verdict"]) for row in self.migrate()],
                         [(10, "migrate")])
        self.assertEqual(self.tree_snapshot(), before)
        self.assertEqual([(row["schema_version"], row["verdict"])
                          for row in self.migrate("--apply")], [(11, "migrated")])
        self.assertEqual(self.read_state(), current)
        self.assertEqual([row["verdict"] for row in self.migrate()], ["current"])

    def test_a_schema_ten_ledger_holding_a_new_member_is_refused_unchanged(self):
        self.spawn_all(61)
        ten = self._as_legacy(self.read_state(), 10)
        pointed = json.loads(json.dumps(ten))
        pointed["issues"]["61"]["attempts"][0]["verification_blocker"] = None
        for label, document in (("blocker map", {**ten, "verification_blockers": {}}),
                                ("attempt pointer", pointed)):
            with self.subTest(member=label):
                self.write_state(document)
                before = self.tree_snapshot()
                (row,) = self.migrate("--apply")
                self.assertEqual((row["verdict"], row["reason"]), ("refused", "invalid_state"))
                done = self.run_cli("init-run", "--repo-root", self.root, "--run-id",
                                    self.run_id, ok=False)
                self.assertEqual(done.returncode, 2, done.stdout)
                self.assertIn("invalid_state", done.stderr)
                self.assertEqual(self.tree_snapshot(), before)


class PointerRuleTest(LedgerHarness, unittest.TestCase):
    """A pointer outside a verification suspension is refused, unchanged (issue 544 D5, D19)."""

    def test_a_pointer_outside_a_verification_suspension_is_refused(self):
        self.spawn_all(61, 62)
        self.suspend(issue=62, attempt=1, blocked_on="transport", now=T(5))
        good = self.read_state()
        for issue, label in ((61, "active"), (62, "suspended on transport")):
            with self.subTest(attempt=label):
                state = json.loads(json.dumps(good))
                state["issues"][str(issue)]["attempts"][0]["verification_blocker"] = (
                    "sha256:" + "0" * 64)
                self.assert_locked_refusal(state, "invalid attempt verification blocker")


class HelperGenerationTest(LedgerHarness, unittest.TestCase):
    """A helper older than the ledger's schema refuses it and writes nothing (#337 D10)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        found = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e",
                                f"{BASE_COMMIT}^{{commit}}"], capture_output=True)
        if found.returncode != 0:
            raise AssertionError(f"base commit {BASE_COMMIT} is missing; fetch it, do not skip")
        cls.base = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, cls.base, True)
        archive = subprocess.run(
            ["git", "-C", str(REPO), "archive", BASE_COMMIT, "python/agent_tools",
             str(HELPER.parent), "home/common/agent-skills/artifact-budget-policy.json"],
            capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(cls.base)], input=archive.stdout, check=True)

    def helper(self, generation, *argv):
        if generation == "head":
            return self.run_cli(*argv, ok=False)
        return subprocess.run(
            [sys.executable, str(self.base / HELPER), *map(str, argv)], capture_output=True,
            text=True, cwd=self.base, timeout=300,
            env={**self.cli_env, "PYTHONPATH": str(self.base / "python"),
                 "PYTHONDONTWRITEBYTECODE": "1"})

    def assert_refused_unchanged(self, generation):
        """Every ledger-reading command refuses `unknown_schema`; migrate reports it as a row."""
        control = self.root / "control-request.json"
        request = self.control_request(
            now=T(6), issues=[61], tracker=[self.tracker_fact(61)], worktrees=[])
        if generation == "base":
            # The base helper reads only its own request interfaces (issue 545 D13).
            request["interface_version"] = 3
            del request["verification"]
        control.write_text(json.dumps(request), "utf-8")
        direct = self.root / "direct-request.json"
        direct.write_text(json.dumps(self.direct_request(issue=61, now=T(6))), "utf-8")
        run = ("--repo-root", self.root, "--run-id", self.run_id)
        calls = {
            "check-launch": ("check-launch", *run, "--action-id", "61:1:1"),
            "suspend": ("suspend", *run, "--blocked-on", "transport", "--now", T(6),
                        "--action-id", "61:1:1"),
            "control": ("control", *run, "--request-file", control),
            "init-run": ("init-run", "--repo-root", self.root, "--run-id", self.run_id),
            "direct-owner": ("direct-owner", "--repo-root", self.root, "--request-file", direct),
            "migrate": ("migrate", "--repo-root", self.root),
            "migrate --apply": ("migrate", "--repo-root", self.root, "--apply"),
        }
        before = self.tree_snapshot()
        for name, argv in calls.items():
            with self.subTest(generation=generation, command=name):
                done = self.helper(generation, *argv)
                if name.startswith("migrate"):
                    (row,) = json.loads(done.stdout)["ledgers"]
                    self.assertEqual((done.returncode, row["verdict"], row["reason"]),
                                     (0, "refused", "unknown_schema"))
                else:
                    self.assertEqual(done.returncode, 2, done.stdout)
                    self.assertIn("unknown_schema", done.stderr)
                self.assertEqual(self.tree_snapshot(), before)

    def test_the_base_helper_refuses_a_schema_eleven_ledger(self):
        self.spawn_all(61)
        current = self.read_state()
        self.write_state(self._as_legacy(current, 10))
        before = self.tree_snapshot()
        done = self.helper("base", "migrate", "--repo-root", self.root)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([row["verdict"] for row in json.loads(done.stdout)["ledgers"]],
                         ["current"])
        self.assertEqual(self.tree_snapshot(), before)
        self.write_state(current)
        self.assert_refused_unchanged("base")

    def test_the_head_helper_refuses_schema_twelve(self):
        self.spawn_all(61)
        self.write_state({**self.read_state(), "schema_version": 12})
        self.assert_refused_unchanged("head")


LOCK, NEXT = "a" * 40, "b" * 40
DIRECT_NOW = "2026-08-20T10:{:02d}:00Z".format


def failure(failure_class="dependency", path="flake.lock", value=LOCK):
    """A `verification-failure` as `verification-observe failure` prints it (issue 543), its
    one selected path holding the object `value`."""
    return {"kind": "verification-failure", "schema_version": 1,
            "repository": {"project_id": "fagenorn/nix-config", "integration_branch": "main"},
            "command": {"id": "nix-build", "argv": ["just", "build"], "cwd": ".", "env": []},
            "failure_class": failure_class,
            "facts": [{"name": "flake-lock", "source": {"paths": [path]},
                       "value": {"objects": [{"path": path, "mode": "100644", "object": value}]}}]}


def observed(blocker, value=LOCK):
    """The `verification-observation` that `verification-observe observe` prints for the
    blocker of the failure `blocker` when its selected path holds `value` (issue 545)."""
    facts = copy.deepcopy(blocker["facts"])
    facts[0]["value"]["objects"][0]["object"] = value
    return {"kind": "verification-observation", "schema_version": 1,
            "blocker_id": vb.blocker_id(blocker),
            "repository": copy.deepcopy(blocker["repository"]), "facts": facts}


def record(attempts):
    """The open record two equal failures share (issue 544 D3)."""
    value = failure()
    return {"id": vb.blocker_id(value), "repository": value["repository"],
            "command": value["command"], "failure_class": "dependency", "facts": value["facts"],
            "attempts": [{"issue": issue, "attempt": 1} for issue in attempts],
            "state": "open", "resolution": None}


class VerificationHarness(LedgerHarness):
    """Attempts suspended on verification blockers through the public `suspend`."""

    def park(self, issue, raw, *, now, cause="verification", flag=True, ok=True):
        """`suspend` attempt 1 of `issue` on `cause` with `raw` (an object, or bytes) as the
        `--verification-input` file; `flag=False` omits the flag."""
        path = self.root / f"failure-{issue}.json"
        path.write_bytes(raw if isinstance(raw, bytes) else json.dumps(raw).encode())
        done = self.run_cli(
            "suspend", "--repo-root", self.root, "--run-id", self.run_id, "--issue", issue,
            "--attempt", 1, "--blocked-on", cause,
            *(("--verification-input", path) if flag else ()), "--now", now,
            *self.launch_arguments(issue, 1, None), ok=ok)
        return self.validated_response(done.stdout) if ok else done

    def attempt(self, issue):
        return self.read_state()["issues"][str(issue)]["attempts"][0]

    def custody_reason(self, issue):
        """The reason of the last transition of attempt 1's custody transaction."""
        store = TransactionStore(self.store_root)
        transaction = store.load(store.lookup(
            ac.creation_key(self.read_state()["transaction_id"], issue, 1)))
        return [event["reason"] for event in transaction.events
                if event["type"] == "transitioned"][-1]

    def recorded(self, *issues):
        return [self.worktree_fact(issue, recorded={"path": self.worktree(issue),
                                                    "state": "matching_issue_branch"})
                for issue in issues]

    def suspended_reply(self, issue):
        return {"interface_version": 2, "kind": "suspended", "run_id": self.run_id,
                "issue": issue, "custody": {"kind": "implementation", "attempt": 1,
                                            "launch": 1, "action_id": f"{issue}:1:1"},
                "blocked_on": "verification", "reentry": f"/from-issue {issue} --auto"}


class SuspensionTest(VerificationHarness, unittest.TestCase):
    def test_equal_failures_of_two_attempts_share_one_record(self):
        self.spawn_all(61, 62)
        for minute, issue in ((5, 61), (6, 62)):
            self.assertEqual(self.park(issue, failure(), now=T(minute)),
                             self.suspended_reply(issue))
        identity = vb.blocker_id(failure())
        self.assertEqual(self.read_state()["verification_blockers"],
                         {identity: record([61, 62])})
        for issue in (61, 62):
            attempt = self.attempt(issue)
            self.assertEqual(
                (attempt["state"], attempt["blocked_on"], attempt["verification_blocker"]),
                ("suspended", "verification", identity))
            self.assertEqual(self.custody_reason(issue), "suspended:verification")

    def test_a_bad_input_or_flag_is_refused_before_anything_is_written(self):
        self.spawn_all(61)
        before = self.tree_snapshot()
        cases = {
            "duplicate key": ({"raw": b'{"kind": "verification-failure", "kind": "x"}'},
                              "invalid verification input: input: duplicate JSON key 'kind'"),
            "not JSON": ({"raw": b"{"}, "invalid verification input: input: "),
            "unclassified": ({"raw": failure(failure_class="product")},
                             "invalid verification input: failure_class: unclassified"),
            "secret-shaped": ({"raw": failure(path=".env")}, "invalid verification input: "
                              "facts[0].source.paths[0]: secret-shaped"),
            "missing flag": ({"raw": failure(), "flag": False},
                             "--verification-input is required with --blocked-on verification"),
            "stray flag": ({"raw": failure(), "cause": "transport"},
                           "--verification-input is only valid with --blocked-on verification"),
        }
        for label, (arguments, line) in cases.items():
            with self.subTest(case=label):
                raw = arguments.pop("raw")
                done = self.park(61, raw, now=T(5), ok=False, **arguments)
                self.assertEqual((done.returncode, done.stdout), (2, ""))
                if line.endswith(": "):  # the JSON decoder's own message follows
                    self.assertTrue(done.stderr.startswith(f"workflow-state: {line}"), done.stderr)
                    self.assertEqual(done.stderr.count("\n"), 1, done.stderr)
                else:
                    self.assertEqual(done.stderr, f"workflow-state: {line}\n")
                self.assertEqual(self.tree_snapshot(), before)

    def test_the_stall_bound_stops_the_attempt_and_records_no_blocker(self):
        self.spawn_all(61)
        for minute in (1, 3, 5):
            self.suspend(issue=61, attempt=1, blocked_on="transport", now=T(minute))
            self.control(now=T(minute + 1), issues=[61], tracker=[self.tracker_fact(61)],
                         worktrees=self.recorded(61), max_parallel=100)
        reply = self.park(61, failure(), now=T(7))
        self.assertEqual((reply["kind"], reply["source"], reply["reason"]),
                         ("terminal", "lifecycle", "stopped"))
        attempt = self.attempt(61)
        self.assertEqual((self.read_state()["verification_blockers"], attempt["state"],
                          attempt["result_source"], attempt["verification_blocker"]),
                         ({}, "stopped", "stalled", None))

    def test_a_resolved_record_is_reopened_by_a_later_suspension(self):
        self.spawn_all(61, 62)
        self.park(61, failure(), now=T(5))
        identity = vb.blocker_id(failure())
        state = self.read_state()
        held = state["verification_blockers"][identity]
        changed = copy.deepcopy(held["facts"])
        changed[0]["value"]["objects"][0]["object"] = "b" * 40
        held.update(state="resolved", resolution={"facts": changed})
        self.write_state(state)
        self.park(62, failure(), now=T(6))
        self.assertEqual(self.read_state()["verification_blockers"],
                         {identity: record([61, 62])})


class ParkedTest(VerificationHarness, unittest.TestCase):
    def test_no_sweep_resumes_a_parked_attempt(self):
        self.spawn_all(61)
        self.park(61, failure(), now=T(5))
        for minute, directed in ((6, False), (7, True)):
            with self.subTest(human_directed=directed):
                issue_before = self.read_state()["issues"]["61"]
                reply = self.control_validated(now=T(minute), issues=[61],
                                               tracker=[self.tracker_fact(61)],
                                               worktrees=self.recorded(61),
                                               human_directed=directed)
                self.assertEqual((reply["actions"], reply["next_deadline"]),
                                 ([{"id": "finalize", "kind": "finalize"}], None))
                (summary,) = reply["summaries"]
                self.assertEqual((summary["state"], summary["blocked_on"]),
                                 ("suspended", "verification"))
                self.assertEqual(self.read_state()["issues"]["61"], issue_before)

    def test_direct_owner_replies_suspended_until_a_merge_reconciles(self):
        self.acquire_direct(issue=73)
        self.run_id = self.direct_run_id(73, 1)
        self.park(73, failure(), now=DIRECT_NOW(5))
        before = self.tree_snapshot()

        def direct(minute, **fields):
            done = self.direct_owner_at_root(
                self.root, self.direct_request(issue=73, now=DIRECT_NOW(minute), **fields))
            return self.validated_response(done.stdout)

        observe = direct(6, forge=None)
        self.assertEqual((observe["kind"], [item["kind"] for item in observe["requirements"]]),
                         ("observe", ["forge_pr"]))
        self.assertEqual(direct(7), self.suspended_reply(73))
        self.assertEqual(self.tree_snapshot(), before)
        merged = {"state": "merged", "url": "https://github.com/fagenorn/nix-config/pull/73",
                  "merge_sha": "b" * 40}
        reply = direct(8, forge=merged)
        self.assertEqual((reply["kind"], reply["reason"]), ("terminal", "merged"))
        attempt = self.attempt(73)
        self.assertEqual((attempt["state"], attempt["blocked_on"],
                          attempt["verification_blocker"]), ("merged", None, None))
        self.assertEqual(self.read_state()["verification_blockers"], {
            vb.blocker_id(failure()): record([73])})


class ParkedPointerTest(VerificationHarness, unittest.TestCase):
    """A parked attempt's pointer must name a record that lists it (issue 544 D5, D19)."""

    def test_a_parked_attempt_needs_a_pointer_its_record_lists(self):
        self.spawn_all(61, 62)
        self.park(61, failure(), now=T(5))
        self.park(62, failure(), now=T(6))
        identity = vb.blocker_id(failure())
        good = self.read_state()
        dangling = ("invalid verification blockers: verification_blockers: attempt 61:1 "
                    f"points at {identity}, which does not list it")

        def no_pointer(state):
            state["issues"]["61"]["attempts"][0]["verification_blocker"] = None

        def no_record(state):
            state["verification_blockers"] = {}

        def unlisted(state):
            state["verification_blockers"][identity]["attempts"] = [{"issue": 62, "attempt": 1}]

        for label, change, line in (
                ("no pointer", no_pointer, "invalid attempt verification blocker"),
                ("no record", no_record, dangling),
                ("a record that does not list it", unlisted, dangling)):
            with self.subTest(case=label):
                state = copy.deepcopy(good)
                change(state)
                self.assert_locked_refusal(state, line)


class LegacyCauseTest(LedgerHarness, unittest.TestCase):
    """A ledger below schema 11 cannot hold a verification suspension (issue 544 D18)."""

    def test_a_legacy_verification_suspension_is_refused_before_any_mint(self):
        self.spawn_all(61)
        self.suspend(issue=61, attempt=1, blocked_on="transport", now=T(5))
        state = self.read_state()
        state["issues"]["61"]["attempts"][0]["blocked_on"] = "verification"
        self.install_legacy(state, "orchestrate-61")
        before = self.tree_snapshot()
        for flags in ((), ("--apply",)):
            with self.subTest(migrate=flags):
                (row,) = [row for row in self.migrate(*flags) if row["ledger"] == "orchestrate-61"]
                self.assertEqual((row["verdict"], row["reason"]), ("refused", "invalid_state"))
                self.assertEqual(self.tree_snapshot(), before)
        done = self.run_cli("init-run", "--repo-root", self.root, "--run-id", "orchestrate-61",
                            ok=False)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (
            2, "", "workflow-state: workflow state refused: invalid_state: "
                   "invalid suspended attempt cause\n"))
        self.assertEqual(self.tree_snapshot(), before)


class WireCauseTest(LifecycleHarness, unittest.TestCase):
    def test_the_suspended_reply_admits_exactly_the_owner_causes(self):
        model = self.delivery_model
        reply = self.delivery_fixtures.workflow_responses(model)["suspended"]

        def validate(cause):
            value = {**copy.deepcopy(reply), "blocked_on": cause}
            return value, model.validate_delivery_object(
                value, expected_kind="workflow-response", notes_max_characters=4096)

        for cause in sorted(ac.OWNER_BLOCKED_ON_VALUES):
            with self.subTest(cause=cause):
                value, validated = validate(cause)
                self.assertEqual(validated, value)
        for cause in ("unknown", "host_capacity", "owner_unavailable"):
            with self.subTest(cause=cause), self.assertRaises(model.DeliveryModelError):
                validate(cause)


if __name__ == "__main__":
    unittest.main()
