"""Host agent-slot admission (#150): declaration, host-route, claims, control admission."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from .test_workflow_state import DEFAULT_NOW, SCRIPT, LifecycleHarness, load_source_module

REPO = Path(__file__).resolve().parents[4]
SCRIPTS = REPO / "home/common/agent-skills/scripts"
WORKFLOW = SCRIPTS / "workflow-state.py"
ARTIFACT_BUDGET = SCRIPTS / "artifact_budget.py"
POLICY = REPO / "home/common/agent-skills/artifact-budget-policy.json"
COMMITTED_DECLARATION = REPO / "home/common/agent-skills/host-declaration.json"
ALTERNATIVE = "/from-issue <issue> --auto"


def declaration(**routes):
    return {"schema_version": 1, "routes": routes}


def install_declaration(home, value):
    """Write `value` (JSON, or a str verbatim) as HOME's declaration; None removes it."""
    target = Path(home) / ".agents/share/host-declaration.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    if value is not None:
        target.write_text(value if isinstance(value, str) else json.dumps(value),
                          encoding="utf-8")
    return target


def boundary(case, raw):
    """Pipe raw bytes through the workflow-response boundary; return the parsed value."""
    checked = subprocess.run(
        [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
         "workflow-response", "--input", "-", "--policy", str(POLICY)],
        input=raw, capture_output=True, check=False)
    case.assertEqual((checked.returncode, checked.stdout), (0, raw), checked.stderr)
    return json.loads(raw)


class HostRouteTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.home, True)

    def host_route(self, route):
        return subprocess.run(
            [sys.executable, str(WORKFLOW), "host-route", "--route", route],
            capture_output=True, check=False, env={**os.environ, "HOME": str(self.home)})

    def answer(self, route):
        completed = self.host_route(route)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return boundary(self, completed.stdout)

    @staticmethod
    def unsupported(route, reason):
        return {"interface_version": 1, "kind": "host_route", "route": route,
                "support": "unsupported", "agent_slots": None,
                "reason_code": reason, "alternative": ALTERNATIVE}

    def test_committed_declaration_is_the_designed_host_budget(self):
        committed = json.loads(COMMITTED_DECLARATION.read_text(encoding="utf-8"))
        self.assertEqual(committed, declaration(**{
            "claude-code": {"support": "supported", "agent_slots": 7},
            "codex": {"support": "unsupported"}}))
        install_declaration(self.home, committed)
        self.assertEqual(self.answer("claude-code"), {
            "interface_version": 1, "kind": "host_route", "route": "claude-code",
            "support": "supported", "agent_slots": 7, "reason_code": None,
            "alternative": None})
        self.assertEqual(self.answer("codex"),
                         self.unsupported("codex", "declared_unsupported"))

    def test_every_reason_code_is_a_typed_answer(self):
        install_declaration(self.home, declaration(**{
            "claude-code": {"support": "supported", "agent_slots": 4}}))
        self.assertEqual(self.answer("claude-code")["agent_slots"], 4)
        self.assertEqual(self.answer("gemini"),
                         self.unsupported("gemini", "route_undeclared"))
        install_declaration(self.home, None)
        self.assertEqual(self.answer("claude-code"),
                         self.unsupported("claude-code", "declaration_missing"))

    def test_invalid_declarations_answer_declaration_invalid(self):
        supported = {"support": "supported", "agent_slots": 7}
        for label, value in (
                ("below the floor", declaration(**{"claude-code": {
                    "support": "supported", "agent_slots": 3}})),
                ("boolean slots", declaration(**{"claude-code": {
                    "support": "supported", "agent_slots": True}})),
                ("host metric", {**declaration(**{"claude-code": supported}), "cpu": 8}),
                ("route member", declaration(**{"claude-code": {**supported, "memory": 1}})),
                ("unsupported with slots", declaration(codex={
                    "support": "unsupported", "agent_slots": 4})),
                ("reserved direct", declaration(direct=supported)),
                ("bad route name", declaration(**{"Claude Code": supported})),
                ("no routes", declaration()),
                ("schema two", {"schema_version": 2, "routes": {"claude-code": supported}}),
                ("duplicate key", '{"schema_version": 1, "schema_version": 1, "routes": '
                                  '{"claude-code": {"support": "supported", "agent_slots": 7}}}'),
                ("not json", "{"),
                ("integer past the conversion limit", '{"schema_version": ' + "1" * 5000
                                                      + ', "routes": {}}'),
                ("nesting past the recursion limit", "[" * 100000 + "]" * 100000)):
            with self.subTest(label):
                install_declaration(self.home, value)
                self.assertEqual(self.answer("claude-code"),
                                 self.unsupported("claude-code", "declaration_invalid"))

    def test_usage_errors_exit_two_and_nothing_is_written(self):
        install_declaration(self.home, json.loads(
            COMMITTED_DECLARATION.read_text(encoding="utf-8")))
        before = sorted(path.relative_to(self.home) for path in self.home.rglob("*"))
        for route in ("direct", "Claude Code", ""):
            with self.subTest(route=route):
                completed = self.host_route(route)
                self.assertEqual((completed.returncode, completed.stdout), (2, b""))
        self.answer("claude-code")
        self.assertEqual(
            sorted(path.relative_to(self.home) for path in self.home.rglob("*")), before)


OWNER_ROLES = {"owner": 1, "worker": 1, "reviewer": 1}


def claim(holder, roles, at, released=None):
    """One claim record; `released` is (released_at, event, seq) or None."""
    released_at, event, seq = released or (None, None, None)
    return {"holder": holder, "roles": dict(roles), "acquired_at": at,
            "released_at": released_at, "release_event": event, "release_seq": seq}


class ClaimLedgerTest(LifecycleHarness, unittest.TestCase):
    """D5, D11, D19: schema 4 records claims; the commit boundary releases them."""

    LATER = "2026-08-13T20:30:00Z"

    def admitted(self):
        """A v4 run: contractless issue 14 active, its launch and the controller claimed."""
        self.init_run()
        workflow = load_source_module(SCRIPT, "host_admission_ledger")
        state = self.read_state()
        attempt = workflow.new_control_attempt(
            issue=14, attempt_number=1, worktree=str(self.root / "wt-14"),
            now=DEFAULT_NOW, deadline_at="2026-08-13T23:00:00Z")
        state["issues"]["14"] = {"issue": 14, "attempts": [attempt], "outcome": None,
                                 "delivery": self.empty_delivery(),
                                 "delivery_remainders": []}
        state["admission"] = {"route": "claude-code", "releases": 0, "claims": [
            claim("controller", {"controller": 1}, DEFAULT_NOW),
            claim("14:1:1", OWNER_ROLES, DEFAULT_NOW)]}
        self.write_state(state)
        return state

    def released(self, holder):
        item = {c["holder"]: c for c in self.read_state()["admission"]["claims"]}[holder]
        return item["released_at"], item["release_event"], item["release_seq"]

    def finish_14(self, now, *, ok=True):
        result = self.root / "result.json"
        result.write_text(json.dumps(self.merged_result(14)), encoding="utf-8")
        return self.run_cli("finish", "--repo-root", self.root, "--run-id", self.run_id,
                            "--issue", 14, "--attempt", 1, "--result-file", result,
                            "--now", now, ok=ok)

    def test_finish_releases_the_claim_in_its_own_write(self):
        self.admitted()
        self.finish_14(self.LATER)
        state = self.read_state()
        self.assertEqual(state["issues"]["14"]["attempts"][0]["state"], "merged")
        self.assertEqual(state["updated_at"], self.LATER)
        self.assertEqual(self.released("14:1:1"), (self.LATER, "finished", 1))
        self.assertEqual((state["admission"]["releases"], self.released("controller")),
                         (1, (None, None, None)))

    def test_suspend_releases_suspended(self):
        self.admitted()
        self.suspend(issue=14, attempt=1, blocked_on="usage_limit", now=self.LATER)
        self.assertEqual(self.released("14:1:1"), (self.LATER, "suspended", 1))

    def test_handoff_releases_handed_off(self):
        self.admitted()
        self.progress(turn_count=118, context_tokens=20000,
                      handoff_path=self.write_handoff(14), now=self.LATER)
        self.assertEqual(self.released("14:1:1"), (self.LATER, "handed_off", 1))

    def test_a_refused_write_leaves_record_and_claim_unchanged(self):
        self.admitted()
        before = self.state_path.read_bytes()
        refused = self.finish_14("2026-08-13T19:00:00Z", ok=False)
        self.assertEqual((refused.returncode, self.state_path.read_bytes()), (2, before))

    def test_state_validation_closes_the_admission_block(self):
        valid = self.admitted()
        check = ("check-launch", "--repo-root", self.root, "--run-id", self.run_id,
                 "--action-id", "14:1:1")
        self.assertEqual(self.run_cli(*check).returncode, 0)
        owner = claim("14:1:1", OWNER_ROLES, DEFAULT_NOW)
        block = lambda claims, releases=0, route="claude-code": {
            "route": route, "releases": releases, "claims": claims}
        for label, admission in (
                ("stale holder", block([claim("14:1:9", OWNER_ROLES, DEFAULT_NOW)])),
                ("two controllers", block([claim("controller", {"controller": 1},
                                                 DEFAULT_NOW)] * 2)),
                ("duplicate holder", block([claim("14:1:1", OWNER_ROLES, DEFAULT_NOW,
                                                  (DEFAULT_NOW, "suspended", 1)), owner], 1)),
                ("partial release", block([{**owner, "released_at": DEFAULT_NOW,
                                            "release_seq": 1}], 1)),
                ("counter mismatch", block([owner], 2)),
                ("wrong roles", block([claim("14:1:1", {"controller": 1}, DEFAULT_NOW)])),
                ("owner finalized", block([claim("14:1:1", OWNER_ROLES, DEFAULT_NOW,
                                                 (DEFAULT_NOW, "finalized", 1))], 1)),
                ("direct with claims", block([owner], route="direct")),
                ("extra member", {**block([]), "slots": 4})):
            with self.subTest(label):
                self.write_state({**valid, "admission": admission})
                self.assertEqual(self.run_cli(*check, ok=False).returncode, 2)

    def test_schema_three_reads_migrate_to_a_null_admission(self):
        self.admitted()
        self.write_state(self._as_legacy(self.read_state(), 3))
        self.assertEqual(self.check_launch(action_id="14:1:1")["reason"], "current")
        self.init_run()  # a locked read persists the migration
        state = self.read_state()
        self.assertEqual((state["schema_version"], state["admission"]), (4, None))

    def test_direct_runs_carry_no_admission(self):
        self.acquire_direct()
        state = json.loads(self.direct_state_path("direct-73-000001").read_text())
        self.assertIsNone(state["admission"])


if __name__ == "__main__":
    unittest.main()
