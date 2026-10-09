import ast
import contextlib
import copy
from datetime import datetime, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

if __package__:
    from .test_delivered_control import DELIVERED, DISPATCH, LIVE, DeliveredControlHarness
else:
    # tests/test_launch_commit.py loads this file from its source as a standalone
    # module (its D14) for LifecycleHarness alone; with no parent package the #273
    # held-control case below, which needs the package's #220 driver, is not defined.
    DeliveredControlHarness = None


SCRIPT = Path(__file__).parents[1] / "scripts" / "workflow-state.py"
SDD_WORKSPACE = Path(__file__).parents[1] / "skills" / "sdd" / "scripts" / "sdd-workspace"
MODEL = Path(__file__).parents[1] / "scripts" / "delivery_model" / "__init__.py"
MODEL_FIXTURES = Path(__file__).with_name("_delivery_model_fixtures.py")
ARTIFACT_BUDGET = Path(__file__).parents[1] / "scripts" / "artifact_budget.py"
BUDGET_POLICY = Path(__file__).parents[1] / "artifact-budget-policy.json"
DEFAULT_NOW = "2026-08-13T20:00:00Z"


def load_source_module(path, name, *, package=False):
    options = {"submodule_search_locations": [str(path.parent)]} if package else {}
    spec = importlib.util.spec_from_file_location(name, path, **options)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


INPROCESS_CLI = load_source_module(
    Path(__file__).with_name("_inprocess_cli.py"), "workflow_state_test_inprocess_cli"
)


class LifecycleHarness:
    """The lifecycle suites' CLI runner, request builders and ledger helpers."""

    @classmethod
    def setUpClass(cls):
        cls.delivery_model = load_source_module(
            MODEL, "workflow_state_test_delivery_model", package=True
        )
        cls.delivery_fixtures = load_source_module(
            MODEL_FIXTURES, "workflow_state_test_delivery_fixtures"
        )

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.run_id = "issue-14-test"
        self.control_request_serial = 0
        self.direct_request_serial = 0
        # The CLI runs with HOME at a fixture declaring 64 claude-code slots, so
        # suites that predate admission never bind a slot (per D23).
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.home = Path(home.name).resolve()
        declaration = self.home / ".agents/share/host-declaration.json"
        declaration.parent.mkdir(parents=True)
        declaration.write_text(json.dumps({"schema_version": 1, "routes": {
            "claude-code": {"support": "supported", "agent_slots": 64},
            "codex": {"support": "unsupported"}}}), encoding="utf-8")
        self.cli_env = {**os.environ, "HOME": str(self.home)}

    @staticmethod
    def empty_delivery():
        return {"contract": None, "contract_digest": None,
                "authorization_intents": [], "authorization_chain_digest": None,
                "authority_observations": [], "reevaluation_evidence": [],
                "authority_evaluation_consumptions": [], "delivery_observations": [],
                "selected_outputs": [], "stage_facts": [], "postconditions": {}}

    @staticmethod
    def _as_legacy(state, version, *, keep_delivery=False):
        state = copy.deepcopy(state)
        state["schema_version"] = version
        if version < 7:
            for issue in state["issues"].values():
                for attempt in issue["attempts"]:
                    for field in ("lane", "lane_budget_minutes", "lane_history"):
                        attempt.pop(field, None)
        if version < 6:
            for issue in state["issues"].values():
                for attempt in issue["attempts"]:
                    attempt.pop("progress_marker", None)
        if version < 5:
            state.pop("workers", None)
        if version < 4:
            state.pop("admission", None)
        if version < 3 and not keep_delivery:
            for issue in state["issues"].values():
                issue.pop("delivery", None)
                issue.pop("delivery_remainders", None)
        if version == 1:
            state.pop("prior_run")
            for issue in state["issues"].values():
                for attempt in issue["attempts"]:
                    for field in ("blocked_on", "suspend_phase", "stalled_resumes"):
                        attempt.pop(field)
        return state

    def _assert_current_launch_refuses_unchanged(self, state):
        self.write_state(state)
        before = self.state_path.read_bytes()
        inventory = sorted(path.relative_to(self.root) for path in self.root.rglob("*"))
        result = self.run_cli(
            "current-launch", "--repo-root", self.root, "--run-id", self.run_id,
            "--action-id", "151:1:1", ok=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(
            sorted(path.relative_to(self.root) for path in self.root.rglob("*")),
            inventory,
        )

    def _spawn_151(self):
        self.init_run()
        self.spawn(issue=151, worktree=str(self.root / "wt-151"), budget_minutes=10)

    @staticmethod
    def _changed(value, path, replacement):
        value = copy.deepcopy(value)
        target = value
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = replacement
        return value

    def _restore_deliveries(self, prior):
        migrated = self.read_state()
        for key, issue in migrated["issues"].items():
            previous = prior["issues"].get(key)
            if previous is not None and "delivery" in previous:
                issue["delivery"] = previous["delivery"]
                issue["delivery_remainders"] = previous["delivery_remainders"]
        if "workers" in prior:
            migrated["workers"] = prior["workers"]
        self.write_state(migrated)

    @property
    def workflows_dir(self):
        return self.root / ".superpowers" / "workflows"

    @property
    def state_path(self):
        return self.workflows_dir / self.run_id / "state.json"

    def run_cli(self, *args, ok=True):
        completed = INPROCESS_CLI.run_script(SCRIPT, args, env=self.cli_env)
        if ok and completed.returncode != 0:
            self.fail(
                f"command failed with {completed.returncode}: {completed.stderr}"
            )
        return completed

    def init_run(self, *, now=DEFAULT_NOW):
        completed = self.run_cli(
            "init-run",
            "--repo-root",
            self.root,
            "--run-id",
            self.run_id,
            "--now",
            now,
        )
        value = json.loads(completed.stdout)
        return {"interface_version": 1, "run_id": value["run_id"],
                "requirements": [self._legacy_bootstrap(item)
                                 for item in value["requirements"]]}

    @staticmethod
    def _legacy_bootstrap(item):
        custody = item["custody"]
        if custody["kind"] != "implementation":
            return item
        return {"issue": item["issue"], "attempt": custody["attempt"],
                "owner": item["owner"], "action_id": custody["action_id"],
                "recorded_worktree": item["recorded_worktree"]}

    @staticmethod
    def _legacy_direct(value):
        value = copy.deepcopy(value)
        value["interface_version"] = 1
        if value.get("kind") == "owner":
            for name in ("custody", "contract", "contract_digest",
                         "pending_stage_ids", "requirements",
                         "authority_evaluation", "requested_scope"):
                value.pop(name, None)
        return value

    @staticmethod
    def _legacy_control(value):
        value = copy.deepcopy(value); value["interface_version"] = 1
        value.pop("admission", None)
        for summary in value["summaries"]:
            custody = summary.pop("custody")
            summary["attempt"] = (None if custody is None
                                  else custody.get("attempt"))
            for name in ("contract_digest", "pending_stage_ids", "requirements"):
                summary.pop(name)
        for delta in value["deltas"]:
            custody = delta.pop("custody")
            delta["attempt"] = None if custody is None else custody.get("attempt")
        for action in value["actions"]:
            if action.get("kind") in {"spawn", "resume", "retry"}:
                for name in ("custody", "contract", "contract_digest",
                             "pending_stage_ids", "requirements",
                             "authority_evaluation", "requested_scope"):
                    action.pop(name, None)
        return value

    def progress(
        self,
        *,
        issue=14,
        attempt=1,
        phase=1,
        now=DEFAULT_NOW,
        turn_count=10,
        context_tokens=20000,
        turn_ceiling=120,
        context_ceiling=150000,
        turn_headroom=2,
        context_headroom=10000,
        next_needs_context=True,
        artifacts_sufficient=False,
        remainder_self_contained=False,
        handoff_path=None,
        ok=True,
    ):
        args = [
            "progress",
            "--repo-root",
            self.root,
            "--run-id",
            self.run_id,
            "--issue",
            issue,
            "--attempt",
            attempt,
            "--phase",
            phase,
            "--now",
            now,
            "--turn-ceiling",
            turn_ceiling,
            "--context-ceiling",
            context_ceiling,
            "--turn-headroom",
            turn_headroom,
            "--context-headroom",
            context_headroom,
            "--next-needs-context",
            str(next_needs_context).lower(),
            "--artifacts-sufficient",
            str(artifacts_sufficient).lower(),
            "--remainder-self-contained",
            str(remainder_self_contained).lower(),
        ]
        if turn_count is not None:
            args.extend(("--turn-count", turn_count))
        if context_tokens is not None:
            args.extend(("--context-tokens", context_tokens))
        if handoff_path is not None:
            args.extend(("--handoff-path", handoff_path))
        completed = self.run_cli(*args, ok=ok)
        return self.validated_response(completed.stdout) if ok else completed

    def write_handoff(self, issue, contents="durable handoff\n"):
        handoffs = self.workflows_dir / self.run_id / "handoffs"
        handoffs.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=handoffs, delete=False
        ) as output:
            temporary_path = Path(output.name)
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        handoff_path = handoffs / f"issue-{issue}.md"
        os.replace(temporary_path, handoff_path)
        return handoff_path

    def write_delivery_detail(self, relative):
        root = self.root / relative
        members = root.with_suffix(".shards")
        members.mkdir(parents=True)
        finding = {
            "axis": "correctness", "severity": "Minor", "status": "parked",
            "text": "durable detail", "ruling": "accepted",
        }
        record = (json.dumps(finding, sort_keys=True, separators=(",", ":")) + "\n").encode()
        member = members / "shard-001.jsonl"
        member.write_bytes(record)
        manifest = {
            "interface_version": 1,
            "kind": "review-package",
            "purpose": "delivery-detail",
            "context": {"issue": 14, "branch": "issue-14", "producer": "ship-review"},
            "shards": [{"path": f"{members.name}/{member.name}", "bytes": len(record)}],
            "total_detail_bytes": len(record),
            "coverage": {"complete": True, "finding_count": 1},
        }
        root.write_text(json.dumps(manifest), encoding="utf-8")
        return root

    def finish(self, attempt, result, *, issue=14, now=DEFAULT_NOW, ok=True):
        current_bytes = self.state_path.read_bytes()
        self.write_state(self._as_legacy(json.loads(current_bytes), 2))
        result_path = self.root / f"result-{issue}-{attempt}.json"
        result_path.write_text(json.dumps(result), encoding="utf-8")
        completed = self.run_cli(
            "finish",
            "--repo-root",
            self.root,
            "--run-id",
            self.run_id,
            "--issue",
            issue,
            "--attempt",
            attempt,
            "--result-file",
            result_path,
            "--now",
            now,
            ok=ok,
        )
        if ok:
            self._restore_deliveries(json.loads(current_bytes))
        else:
            self.state_path.write_bytes(current_bytes)
        return json.loads(completed.stdout) if ok else completed

    @staticmethod
    def tracker_fact(issue, *, state="open", open_blockers=None,
                     decision_blockers=None):
        return {
            "issue": issue,
            "state": state,
            "open_blockers": [] if open_blockers is None else open_blockers,
            "decision_blockers": (
                [] if decision_blockers is None else decision_blockers
            ),
        }

    @staticmethod
    def worktree_fact(issue, *, recorded=None, candidate=None):
        return {"issue": issue, "recorded": recorded, "candidate": candidate}

    @staticmethod
    def owner_fact(*, event_id, issue, attempt, launch, state="unavailable"):
        return {
            "event_id": event_id,
            "issue": issue,
            "custody": {"kind": "implementation", "attempt": attempt,
                        "launch": launch, "action_id": f"{issue}:{attempt}:{launch}"},
            "state": state,
        }

    def delivery_contract(self, issue):
        model, fixtures = self.delivery_model, self.delivery_fixtures
        contract, delivery = fixtures.contract_and_delivery(model)
        first = copy.deepcopy(delivery["authorization_intents"][0])
        for declared in first["scopes"]:
            declared["target"]["issue"] = issue
            fixtures.seal(model, declared)
        fixtures.seal(model, first)
        contract["issue"] = issue
        contract["deliverable"]["id"] = f"delivery-{issue}"
        contract["initial_authorization_intent_id"] = first["id"]
        contract["initial_authorization_intent_digest"] = model.canonical_digest(first)
        contract["provenance"]["reference"] = f"issue:{issue}"
        delivery = fixtures.rebind_contract(model, contract, delivery)
        delivery["authorization_intents"] = [first]
        delivery["authorization_chain_digest"] = model.canonical_digest(
            {"intent_ids": [first["id"]]}
        )
        model.validate_delivery_object(
            delivery, expected_kind="delivery", notes_max_characters=1_000_000
        )
        return contract, first

    def control_request(self, *, now, issues, tracker, worktrees, owners=None,
                        max_parallel=2, attempt_budget_minutes=30,
                        human_directed=False, host_route="claude-code"):
        contracts = {str(issue): self.delivery_contract(issue) for issue in issues}
        return {
            "interface_version": 3,
            "host_route": host_route,
            "now": now,
            "max_parallel": max_parallel,
            "attempt_budget_minutes": attempt_budget_minutes,
            "human_directed": human_directed,
            "issues": issues,
            "tracker": tracker,
            "owners": [] if owners is None else owners,
            "worktrees": worktrees,
            "forge": {str(issue): self.no_pull_request() for issue in issues},
            "delivery_contracts": {key: value[0] for key, value in contracts.items()},
            "authorization_intents": {key: [value[1]] for key, value in contracts.items()},
            "authority_observations": {str(issue): [] for issue in issues},
            "reevaluation_evidence": {str(issue): [] for issue in issues},
            "delivery_observations": {str(issue): [] for issue in issues},
            "requested_scopes": {str(issue): None for issue in issues},
            "recoveries": {str(issue): None for issue in issues},
        }

    def control_raw(self, *, request=None, ok=True, legacy=True, **request_fields):
        value = request if request is not None else self.control_request(**request_fields)
        self.control_request_serial += 1
        request_path = self.root / f"control-{self.control_request_serial}.json"
        request_path.write_text(json.dumps(value), encoding="utf-8")
        completed = self.run_cli(
            "control",
            "--repo-root", self.root,
            "--run-id", self.run_id,
            "--request-file", request_path,
            ok=ok,
        )
        if legacy and completed.returncode == 0:
            completed.stdout = json.dumps(
                self._legacy_control(json.loads(completed.stdout)),
                sort_keys=True, separators=(",", ":")) + "\n"
        return completed

    def control(self, **request_fields):
        return json.loads(self.control_raw(**request_fields).stdout)

    def validated_response(self, stdout):
        """Decode reply bytes the `workflow-response` boundary passes unchanged (#191 D7)."""
        validated = subprocess.run(
            [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
             "workflow-response", "--input", "-", "--policy", str(BUDGET_POLICY)],
            input=stdout, capture_output=True, text=True, check=False,
            env=self.cli_env)
        self.assertEqual((validated.returncode, validated.stderr), (0, ""))
        self.assertEqual(validated.stdout, stdout)
        return json.loads(stdout)

    def control_validated(self, **request_fields):
        """Sweep, returning interface-3 bytes the `workflow-response` boundary passes (#194)."""
        completed = self.control_raw(legacy=False, ok=False, **request_fields)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return self.validated_response(completed.stdout)

    @staticmethod
    def unresumable_fact(path, recorded_state):
        """The summary requirement of a resume its recorded worktree ended (#194 D3)."""
        return {"kind": "worktree_fact", "subject_id": path,
                "reason_code": f"recorded_worktree_{recorded_state}",
                "detail_pointer": None}

    UNOBSERVED = object()

    def direct_request(self, *, issue=73, now="2026-08-20T10:00:00Z",
                       attempt_budget_minutes=180, new_run=False,
                       owner_unavailable=False, tracker=None, worktree=None,
                       forge=UNOBSERVED):
        contract, first = self.delivery_contract(issue)
        return {
            "interface_version": 2,
            "issue": issue,
            "now": now,
            "attempt_budget_minutes": attempt_budget_minutes,
            "new_run": new_run,
            "owner_unavailable": owner_unavailable,
            "tracker": tracker,
            "worktree": worktree,
            "forge": self.no_pull_request() if forge is self.UNOBSERVED else forge,
            "delivery_contract": contract,
            "authorization_intents": [first],
            "authority_observations": [],
            "reevaluation_evidence": [],
            "delivery_observations": [],
            "requested_scope": None,
            "recovery": None,
        }

    @staticmethod
    def no_pull_request():
        """The forge observation for an issue whose branch has no PR."""
        return {"state": "none", "url": None, "merge_sha": None}

    def direct_owner_raw(self, *, request=None, ok=True, **request_fields):
        value = request if request is not None else self.direct_request(**request_fields)
        self.direct_request_serial += 1
        request_path = self.root / f"direct-request-{self.direct_request_serial}.json"
        request_path.write_text(json.dumps(value), encoding="utf-8")
        completed = self.run_cli(
            "direct-owner", "--repo-root", self.root,
            "--request-file", request_path, ok=ok,
        )
        if completed.returncode == 0:
            completed.stdout = json.dumps(
                self._legacy_direct(json.loads(completed.stdout)),
                sort_keys=True, separators=(",", ":")) + "\n"
        return completed

    def direct_owner(self, **request_fields):
        return json.loads(self.direct_owner_raw(**request_fields).stdout)

    def direct_owner_at_root(self, root, request, *, ok=True):
        self.direct_request_serial += 1
        request_path = Path(root) / f"direct-request-{self.direct_request_serial}.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        return self.run_cli(
            "direct-owner", "--repo-root", root,
            "--request-file", request_path, ok=ok,
        )

    def direct_state_path(self, run_id):
        return self.workflows_dir / run_id / "state.json"

    def acquire_direct(self, *, issue=73, now="2026-08-20T10:00:00Z",
                       worktree=None, attempt_budget_minutes=180):
        candidate = os.path.abspath(worktree or self.root / f"worktree-issue-{issue}")
        common = {"issue": issue, "now": now,
                  "attempt_budget_minutes": attempt_budget_minutes}
        self.assertEqual(self.direct_owner(**common), {
            "interface_version": 1, "kind": "observe", "issue": issue,
            "run_id": None, "requirements": [{"kind": "tracker"}],
        })
        tracker = self.tracker_fact(issue)
        selected = self.direct_owner(**common, tracker=tracker)
        self.assertEqual(selected, {
            "interface_version": 1, "kind": "observe", "issue": issue,
            "run_id": f"direct-{issue}-000001",
            "requirements": [{"kind": "candidate_worktree"}],
        })
        return self.direct_owner(
            **common, tracker=tracker,
            worktree=self.worktree_fact(
                issue, candidate={"path": candidate, "state": "absent"},
            ),
        )

    @staticmethod
    def dispatch_action(response, kind):
        return next(action for action in response["actions"] if action["kind"] == kind)

    def spawn(self, *, issue, worktree, now=DEFAULT_NOW, budget_minutes=30):
        canonical_worktree = os.path.abspath(worktree)
        response = self.control(
            now=now,
            issues=[issue],
            tracker=[self.tracker_fact(issue)],
            worktrees=[self.worktree_fact(
                issue,
                candidate={"path": canonical_worktree, "state": "absent"},
            )],
            max_parallel=100,
            attempt_budget_minutes=budget_minutes,
        )
        return self.dispatch_action(response, "spawn")

    def resume(self, *, issue, worktree, now, owner_unavailable=False):
        state = self.read_state()["issues"][str(issue)]
        attempt = state["attempts"][-1]
        self.assertEqual(os.path.abspath(worktree), attempt["worktree"])
        owners = None
        if owner_unavailable:
            owners = [self.owner_fact(
                event_id=f"{issue}-owner-unavailable",
                issue=issue,
                attempt=attempt["attempt"],
                launch=len(attempt["launches"]),
            )]
        response = self.control(
            now=now,
            issues=[issue],
            tracker=[self.tracker_fact(issue)],
            owners=owners,
            worktrees=[self.worktree_fact(issue, recorded={
                "path": attempt["worktree"],
                "state": "matching_issue_branch",
            })],
            max_parallel=100,
        )
        return self.dispatch_action(response, "resume")

    def retry(self, *, issue, worktree, now, budget_minutes=30):
        latest = self.read_state()["issues"][str(issue)]["attempts"][-1]
        canonical_worktree = os.path.abspath(worktree)
        if canonical_worktree == latest["worktree"]:
            worktree_fact = self.worktree_fact(issue, recorded={
                "path": canonical_worktree,
                "state": "matching_issue_branch",
            })
        else:
            worktree_fact = self.worktree_fact(issue, candidate={
                "path": canonical_worktree,
                "state": "absent",
            })
        response = self.control(
            now=now,
            issues=[issue],
            tracker=[self.tracker_fact(issue)],
            worktrees=[worktree_fact],
            max_parallel=100,
            attempt_budget_minutes=budget_minutes,
        )
        return self.dispatch_action(response, "retry")

    def expire(self, *, issue, worktree, now):
        latest = self.read_state()["issues"][str(issue)]["attempts"][-1]
        self.assertEqual(os.path.abspath(worktree), latest["worktree"])
        return self.control(
            now=now,
            issues=[issue],
            tracker=[self.tracker_fact(issue, state="closed")],
            worktrees=[self.worktree_fact(issue, recorded={
                "path": latest["worktree"],
                "state": "matching_issue_branch",
            })],
            max_parallel=100,
        )

    def fail_owner(self, *, issue, attempt, now=DEFAULT_NOW, notes="owner failed"):
        return self.finish(
            attempt,
            {
                **self.merged_result(issue),
                "state": "failed",
                "pr_url": None,
                "merge_sha": None,
                "issue_closed": False,
                "notes": notes,
            },
            issue=issue,
            now=now,
        )

    def assert_control_response_shape(self, response):
        self.assertEqual(set(response), {
            "interface_version", "run_id", "now", "summaries", "deltas",
            "actions", "next_deadline",
        })
        self.assertIs(type(response["interface_version"]), int)
        self.assertIsInstance(response["run_id"], str)
        self.assertIsInstance(response["now"], str)
        self.assertIsInstance(response["summaries"], list)
        self.assertIsInstance(response["deltas"], list)
        self.assertIsInstance(response["actions"], list)
        self.assertTrue(response["next_deadline"] is None or
                        isinstance(response["next_deadline"], str))
        for summary in response["summaries"]:
            if response["interface_version"] == 2:
                self.assertEqual(set(summary), {
                    "issue", "state", "custody", "owner", "worktree",
                    "deadline_at", "blocked_on", "blockers", "result",
                    "contract_digest", "pending_stage_ids", "requirements",
                })
                summary = {**summary, "attempt": (
                    None if summary["custody"] is None else
                    summary["custody"].get("attempt"))}
            else:
                self.assertEqual(set(summary), {
                    "issue", "state", "attempt", "owner", "worktree",
                    "deadline_at", "blocked_on", "blockers", "result",
                })
            self.assertIs(type(summary["issue"]), int)
            self.assertIn(summary["state"], {
                "queued", "blocked", "fogged", "active", "handed_off",
                "suspended", "merged", "stopped", "failed", "closed",
            })
            self.assertIsInstance(summary["blockers"], list)
            self.assertTrue(summary["attempt"] is None or
                            type(summary["attempt"]) is int)
            for field in ("owner", "worktree", "deadline_at", "blocked_on"):
                self.assertTrue(summary[field] is None or
                                isinstance(summary[field], str))
            self.assertTrue(summary["blocked_on"] is None or
                            summary["state"] == "suspended")
            for blocker in summary["blockers"]:
                self.assertEqual(set(blocker), {"kind", "issue", "url"})
                self.assertIn(blocker["kind"], {"issue", "decision"})
                self.assertIs(type(blocker["issue"]), int)
                self.assertTrue(blocker["url"] is None or
                                isinstance(blocker["url"], str))
            if summary["result"] is not None:
                self.assertEqual(set(summary["result"]), {
                    "issue", "state", "pr_url", "merge_sha", "issue_closed",
                    "discussion_items", "detail_state", "report_path", "notes",
                })
                self.assertIs(type(summary["result"]["issue"]), int)
                self.assertIn(summary["result"]["state"], {"merged", "stopped", "failed"})
                for field in ("pr_url", "merge_sha"):
                    self.assertTrue(summary["result"][field] is None or
                                    isinstance(summary["result"][field], str))
                self.assertIs(type(summary["result"]["issue_closed"]), bool)
                self.assertIsInstance(summary["result"]["discussion_items"], list)
                self.assertIsInstance(summary["result"]["notes"], str)
        for delta in response["deltas"]:
            self.assertEqual(set(delta), {"issue", "attempt", "kind", "state"})
            self.assertIs(type(delta["issue"]), int)
            self.assertIs(type(delta["attempt"]), int)
            self.assertIn(delta["kind"], {
                "expired", "spawned", "resumed", "retried", "retry_refused",
            })
            self.assertIsInstance(delta["state"], str)
        for action in response["actions"]:
            self.assertIsInstance(action["id"], str)
            self.assertIsInstance(action["kind"], str)
            if action["kind"] in {"spawn", "resume", "retry"}:
                self.assertEqual(set(action), {
                    "id", "kind", "issue", "attempt", "owner", "worktree",
                    "handoff_path", "deadline_at",
                })
                self.assertIs(type(action["issue"]), int)
                self.assertIs(type(action["attempt"]), int)
                self.assertIsInstance(action["owner"], str)
                self.assertIsInstance(action["worktree"], str)
                self.assertTrue(action["handoff_path"] is None or
                                isinstance(action["handoff_path"], str))
                self.assertIsInstance(action["deadline_at"], str)
            elif action["kind"] == "wait":
                self.assertEqual(set(action), {
                    "id", "kind", "wake_on", "deadline_at", "wait_seconds",
                })
                self.assertIs(type(action["wait_seconds"]), int)
                self.assertGreaterEqual(action["wait_seconds"], 0)
                self.assertIsInstance(action["wake_on"], list)
                self.assertTrue(set(action["wake_on"]) <= {
                    "owner_notification", "tracker_change", "deadline",
                })
                # A wait always names the instant it ends; a deadline-less wait
                # is outlawed, control finalizes instead.
                self.assertIsInstance(action["deadline_at"], str)
            elif action["kind"] == "finalize":
                self.assertEqual(action, {"id": "finalize", "kind": "finalize"})
            else:
                self.fail(f"unknown control action kind: {action['kind']!r}")

    def read_state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def assert_controller_finalized(self, before, *, now):
        """The ledger `before` as a sweep ending in `finalize` at `now` leaves it
        (per D20): its held controller claim released `finalized`, or, for a
        ledger a schema-2 round trip left unbound (D23), only the re-bound route
        with nothing live to adopt."""
        expected = json.loads(before)
        admission = expected["admission"]
        if admission is None:
            expected["admission"] = {"route": "claude-code", "releases": 0, "claims": []}
        else:
            controller = next(claim for claim in admission["claims"]
                              if claim["holder"] == "controller"
                              and claim["released_at"] is None)
            admission["releases"] += 1
            controller.update(released_at=now, release_event="finalized",
                              release_seq=admission["releases"])
        expected["updated_at"] = now
        self.assertEqual(self.read_state(), expected)

    @staticmethod
    def spawned_admission(issue, *, at=DEFAULT_NOW):
        """The admission block one claude-code sweep writes when it spawns `issue`:
        the route binding, the controller claim a `wait` keeps, then the owner
        role set of launch `issue:1:1` (per D4, D20, D21)."""
        held = {"released_at": None, "release_event": None, "release_seq": None}
        return {"route": "claude-code", "releases": 0, "claims": [
            {"holder": "controller", "roles": {"controller": 1}, "acquired_at": at, **held},
            {"holder": f"{issue}:1:1", "roles": {"owner": 1, "worker": 1, "reviewer": 1},
             "acquired_at": at, **held}]}

    def write_state(self, state):
        self.state_path.write_text(
            json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    def suspend(self, *, issue, attempt, blocked_on, now, ok=True):
        completed = self.run_cli(
            "suspend",
            "--repo-root", self.root,
            "--run-id", self.run_id,
            "--issue", issue,
            "--attempt", attempt,
            "--blocked-on", blocked_on,
            "--now", now,
            ok=ok,
        )
        return self.validated_response(completed.stdout) if ok else completed

    def check_launch_raw(self, *, action_id, repo_root=None, run_id=None, ok=True):
        return self.run_cli(
            "check-launch",
            "--repo-root", self.root if repo_root is None else repo_root,
            "--run-id", self.run_id if run_id is None else run_id,
            "--action-id", action_id,
            ok=ok,
        )

    def check_launch(self, **kwargs):
        """Query one launch identity and pin the redundancy invariant on the way."""
        completed = self.check_launch_raw(**kwargs)
        answer = json.loads(completed.stdout)
        self.assertEqual(
            set(answer), {"action_id", "current", "current_action_id", "reason"}
        )
        self.assertEqual(answer["action_id"], kwargs["action_id"])
        # The boolean is deliberately redundant with the two identity fields
        # (per D1); if they ever disagree the discriminator is lying.
        self.assertEqual(
            answer["current"],
            answer["current_action_id"] is not None
            and answer["action_id"] == answer["current_action_id"],
        )
        return answer

    def register_worker(self, *, action_id, now, parent=None, ok=True):
        args = ["register-worker", "--repo-root", self.root, "--run-id", self.run_id,
                "--now", now, "--action-id", action_id]
        if parent is not None:
            args.extend(("--parent", parent))
        completed = self.run_cli(*args, ok=ok)
        return json.loads(completed.stdout) if ok else completed

    def mark_progress(self, *, action_id, now, ok=True):
        completed = self.run_cli(
            "mark-progress", "--repo-root", self.root, "--run-id", self.run_id,
            "--now", now, "--action-id", action_id, ok=ok)
        return json.loads(completed.stdout) if ok else completed

    def declare_lane(self, *, action_id, now, lane, budget_minutes, reason, ok=True):
        completed = self.run_cli(
            "declare-lane", "--repo-root", self.root, "--run-id", self.run_id,
            "--now", now, "--action-id", action_id, "--lane", lane,
            "--budget-minutes", str(budget_minutes), "--reason", reason, ok=ok)
        return json.loads(completed.stdout) if ok else completed

    @staticmethod
    def git(worktree, *args):
        completed = subprocess.run(["git", "-C", str(worktree), *args], check=True,
                                   capture_output=True, text=True)
        return completed.stdout.strip()

    def init_worktree(self, path, *, branch):
        """A real git repository at `path` with one commit on `branch` (#250 D13).

        The fixture repository turns commit signing off for itself: it lives in a
        temporary directory and must not depend on the machine's signing key.
        """
        Path(path).mkdir(parents=True)
        self.git(path, "init", "--quiet", "--initial-branch", branch)
        for key, value in (("user.name", "Fixture"),
                           ("user.email", "fixture@example.test"),
                           ("commit.gpgsign", "false")):
            self.git(path, "config", key, value)
        return self.commit(path)

    def commit(self, worktree, message="work"):
        self.git(worktree, "commit", "--quiet", "--allow-empty", "--message", message)
        return self.git(worktree, "rev-parse", "HEAD")

    def release_worker(self, *, worker_id, event, now, ok=True):
        completed = self.run_cli(
            "release-worker", "--repo-root", self.root, "--run-id", self.run_id,
            "--now", now, "--worker-id", worker_id, "--event", event, ok=ok)
        return json.loads(completed.stdout) if ok else completed

    def check_worker_raw(self, worker_id, *, run_id=None, ok=True):
        return self.run_cli(
            "check-worker", "--repo-root", self.root,
            "--run-id", self.run_id if run_id is None else run_id,
            "--worker-id", worker_id, ok=ok)

    def check_worker(self, worker_id, **kwargs):
        answer = json.loads(self.check_worker_raw(worker_id, **kwargs).stdout)
        self.assertEqual(set(answer), {"worker_id", "live", "current_action_id", "reason"})
        self.assertEqual(answer["worker_id"], worker_id)
        self.assertIs(answer["live"], answer["reason"] == "live")
        return answer

    def legacy_expiry_record(self, *, issue, now, prior_schema=False):
        """Stamp the terminal reaper record written before the suspension model.

        The reaper now demotes an expired attempt to `suspended`, but ledgers
        holding the old `stopped`/`result_source="expiry"` shape must keep
        loading and keep driving the retry ladder and the provisional-result
        override, so the tests that pin those rules seed the record directly.
        `prior_schema` writes it under schema 2, without the admission block
        and the delivery fields — the on-disk shape a live run carries across
        deploy.
        """
        state = self.read_state()
        issue_state = state["issues"][str(issue)]
        attempt = issue_state["attempts"][-1]
        result = {
            **self.merged_result(issue),
            "state": "stopped", "pr_url": None, "merge_sha": None,
            "issue_closed": False,
            "notes": (
                f"attempt deadline expired; worktree: {attempt['worktree']}"
            ),
        }
        attempt.update({
            "state": "stopped", "blocked_on": None,
            "result": copy.deepcopy(result), "finished_at": now,
            "result_source": "expiry",
        })
        issue_state["outcome"] = copy.deepcopy(result)
        state["updated_at"] = now
        # The record predates admission, so it carries none: a held claim would
        # otherwise name a launch this record just ended. The next sweep
        # re-binds and adopts (per D11, D23).
        state["admission"] = None
        if prior_schema:
            state["schema_version"] = 2
            state.pop("admission")
            state.pop("workers")
            issue_state.pop("delivery")
            issue_state.pop("delivery_remainders")
        self.write_state(state)
        return result

    @staticmethod
    def merged_result(issue=14):
        return {
            "issue": issue,
            "state": "merged",
            "pr_url": "https://github.com/fagenorn/nix-config/pull/15",
            "merge_sha": "abc123abc123abc123abc123abc123abc123abcd",
            "issue_closed": True,
            "discussion_items": [],
            "detail_state": "none",
            "report_path": None,
            "notes": "",
        }

    def concurrent_finish(self, results, *, now):
        current = self.read_state()
        self.write_state(self._as_legacy(current, 2))
        wrapper = (
            "import os,sys; fd=int(sys.argv[1]); script=sys.argv[2]; "
            "args=sys.argv[3:]; os.read(fd,1); "
            "os.execv(sys.executable,[sys.executable,script,*args])"
        )
        processes = []
        write_fds = []
        for issue, (attempt, result) in results.items():
            result_path = self.root / f"concurrent-result-{issue}.json"
            result_path.write_text(json.dumps(result), encoding="utf-8")
            read_fd, write_fd = os.pipe()
            args = [
                "finish", "--repo-root", str(self.root),
                "--run-id", self.run_id, "--issue", str(issue),
                "--attempt", str(attempt), "--result-file", str(result_path),
                "--now", now,
            ]
            process = subprocess.Popen(
                [sys.executable, "-c", wrapper, str(read_fd), str(SCRIPT), *args],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                pass_fds=(read_fd,), env=self.cli_env,
            )
            os.close(read_fd)
            processes.append((issue, attempt, result, process))
            write_fds.append(write_fd)
        for write_fd in write_fds:
            os.write(write_fd, b"x")
            os.close(write_fd)
        for _, _, _, process in processes:
            process.communicate()
        self.assertTrue(all(process.returncode == 0 for *_, process in processes))
        self._restore_deliveries(current)
        return [process for *_, process in processes]

    def copy_ledger_root(self, state_bytes):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        run_dir = root / ".superpowers" / "workflows" / self.run_id
        run_dir.mkdir(parents=True)
        (run_dir / "state.json").write_bytes(state_bytes)
        return root

    def run_control_at_root(self, root, request):
        request_path = root / "copied-control.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        completed = INPROCESS_CLI.run_script(
            SCRIPT,
            ["control", "--repo-root", root, "--run-id", self.run_id,
             "--request-file", request_path],
            env=self.cli_env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        completed.stdout = json.dumps(
            self._legacy_control(json.loads(completed.stdout)),
            sort_keys=True, separators=(",", ":")) + "\n"
        return completed


class WorkflowStateLifecycleTest(LifecycleHarness, unittest.TestCase):
    def test_public_cli_exposes_direct_owner_but_not_retired_commands(self):
        completed = self.run_cli("--help")
        self.assertIn("direct-owner", completed.stdout)
        for retired in ("launch", "reconcile"):
            rejected = self.run_cli(retired, ok=False)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("invalid choice", rejected.stderr)

    def test_init_run_returns_only_the_strict_bounded_bootstrap(self):
        fresh = self.init_run(now="2026-08-19T12:00:00Z")
        self.assertEqual(fresh, {
            "interface_version": 1,
            "run_id": self.run_id,
            "requirements": [],
        })
        paths = {issue: str(self.root / f"wt-{issue}") for issue in (47, 51)}
        self.control(now="2026-08-19T12:00:00Z", issues=[51, 47],
                     tracker=[self.tracker_fact(51), self.tracker_fact(47)],
                     worktrees=[self.worktree_fact(
                         issue, candidate={"path": paths[issue], "state": "absent"}
                     ) for issue in (51, 47)])
        restarted = self.init_run(now="2026-08-19T12:01:00Z")
        self.assertEqual(restarted, {
            "interface_version": 1,
            "run_id": self.run_id,
            "requirements": [
                {"issue": 47, "attempt": 1, "owner": "47:1",
                 "action_id": "47:1:1",
                 "recorded_worktree": paths[47]},
                {"issue": 51, "attempt": 1, "owner": "51:1",
                 "action_id": "51:1:1",
                 "recorded_worktree": paths[51]},
            ],
        })
        rendered = json.dumps(restarted)
        for forbidden in (
            "attempts", "launches", "deadline_at", "phase", "handoff",
            "result", "prior", "state",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_control_starts_ready_issues_persists_before_emission_and_bounds_output(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        paths = {issue: str(self.root / f"wt-{issue}") for issue in (47, 51, 53)}
        response = self.control(
            now="2026-08-19T12:00:00Z",
            issues=[47, 51, 53],
            max_parallel=2,
            attempt_budget_minutes=180,
            tracker=[self.tracker_fact(issue) for issue in (47, 51, 53)],
            worktrees=[
                self.worktree_fact(
                    issue,
                    candidate={"path": paths[issue], "state": "absent"},
                )
                for issue in (47, 51, 53)
            ],
        )
        self.assertEqual([item["state"] for item in response["summaries"]],
                         ["active", "active", "queued"])
        self.assertEqual([item["kind"] for item in response["deltas"]],
                         ["spawned", "spawned"])
        self.assertEqual([item["kind"] for item in response["actions"]],
                         ["spawn", "spawn", "wait"])
        self.assertEqual([item["id"] for item in response["actions"]],
                         ["47:1:1", "51:1:1", "wait:2026-08-19T15:00:00Z"])
        self.assertEqual(response["summaries"][0], {
            "issue": 47, "state": "active", "attempt": 1, "owner": "47:1",
            "worktree": paths[47], "deadline_at": "2026-08-19T15:00:00Z",
            "blocked_on": None, "blockers": [], "result": None,
        })
        self.assertEqual(response["deltas"][0], {
            "issue": 47, "attempt": 1, "kind": "spawned", "state": "active",
        })
        self.assertEqual(response["actions"][0], {
            "id": "47:1:1", "kind": "spawn", "issue": 47, "attempt": 1,
            "owner": "47:1", "worktree": paths[47], "handoff_path": None,
            "deadline_at": "2026-08-19T15:00:00Z",
        })
        self.assertEqual(response["actions"][-1], {
            "id": "wait:2026-08-19T15:00:00Z", "kind": "wait",
            "wake_on": ["deadline", "owner_notification", "tracker_change"],
            "deadline_at": "2026-08-19T15:00:00Z", "wait_seconds": 10800,
        })
        self.assertEqual(response["next_deadline"], "2026-08-19T15:00:00Z")
        reopened = self.read_state()
        for issue in (47, 51):
            attempt = reopened["issues"][str(issue)]["attempts"][0]
            self.assertEqual(attempt["owner"], f"{issue}:1")
            self.assertEqual(len(attempt["launches"]), 1)
        self.assertNotIn("53", reopened["issues"])

    def test_control_response_is_canonical_compact_and_current_only(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        completed = self.control_raw(
            now="2026-08-19T12:00:00Z",
            issues=[47],
            tracker=[self.tracker_fact(47)],
            worktrees=[self.worktree_fact(
                47, candidate={"path": str(self.root / "wt-47"), "state": "absent"}
            )],
        )
        response = json.loads(completed.stdout)
        self.assert_control_response_shape(response)
        self.assertEqual(
            completed.stdout,
            json.dumps(response, sort_keys=True, separators=(",", ":")) + "\n",
        )
        rendered = completed.stdout
        for forbidden in (
            '"attempts"', '"launches"', '"phase_inputs"',
            '"prior_attempt"', '"result_source"',
        ):
            self.assertNotIn(forbidden, rendered)
        self.assertEqual(len(response["summaries"]), 1)
        self.assertLessEqual(len(response["deltas"]), 1)
        self.assertLessEqual(
            len([a for a in response["actions"] if a["kind"] != "wait"]), 2
        )

    def test_control_finalizes_on_blocked_issues_from_current_facts(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        waiting = self.control(
            now="2026-08-19T12:00:00Z",
            issues=[47],
            tracker=[self.tracker_fact(47, open_blockers=[40])],
            worktrees=[],
        )
        self.assertEqual(waiting["summaries"][0]["state"], "blocked")
        self.assertEqual(waiting["summaries"][0]["blockers"], [
            {"kind": "issue", "issue": 40, "url": None}
        ])
        # Nothing is running, so no deadline can end a wait: control renders the
        # blockers and returns instead of parking on a notification (per D12).
        self.assertEqual(waiting["actions"], [{"id": "finalize", "kind": "finalize"}])
        self.assertIsNone(waiting["next_deadline"])
        fogged = self.control(
            now="2026-08-19T12:00:30Z", issues=[47],
            tracker=[self.tracker_fact(47, decision_blockers=[{
                "issue": 41,
                "url": "https://github.com/fagenorn/nix-config/issues/41",
            }])], worktrees=[],
        )
        self.assertEqual(fogged["summaries"][0]["state"], "fogged")
        self.assertEqual(fogged["summaries"][0]["blockers"], [{
            "kind": "decision", "issue": 41,
            "url": "https://github.com/fagenorn/nix-config/issues/41",
        }])
        combined = self.control(
            now="2026-08-19T12:00:45Z", issues=[47],
            tracker=[self.tracker_fact(
                47,
                open_blockers=[40],
                decision_blockers=[{
                    "issue": 41,
                    "url": "https://github.com/fagenorn/nix-config/issues/41",
                }],
            )],
            worktrees=[],
        )
        self.assertEqual(combined["summaries"][0]["state"], "fogged")
        self.assertEqual(combined["summaries"][0]["blockers"], [
            {
                "kind": "decision", "issue": 41,
                "url": "https://github.com/fagenorn/nix-config/issues/41",
            },
            {"kind": "issue", "issue": 40, "url": None},
        ])
        finalized = self.control(
            now="2026-08-19T12:01:00Z",
            issues=[47],
            tracker=[self.tracker_fact(47, state="closed")],
            worktrees=[],
        )
        self.assertEqual(finalized["summaries"][0]["state"], "closed")
        self.assertEqual(finalized["actions"], [{"id": "finalize", "kind": "finalize"}])
        self.assertIsNone(finalized["next_deadline"])

    def test_control_rejects_bad_observations_without_rewriting_the_ledger(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        valid = self.control_request(
            now="2026-08-19T12:00:00Z",
            issues=[47],
            tracker=[self.tracker_fact(47)],
            worktrees=[self.worktree_fact(
                47, candidate={"path": str(self.root / "wt-47"), "state": "absent"}
            )],
        )
        mutations = {
            "unsupported control interface version":
                lambda value: value.__setitem__("interface_version", 1),
            "invalid control request fields":
                lambda value: value.__setitem__("extra", True),
            "duplicate control issue":
                lambda value: value["issues"].append(47),
            "invalid control issue":
                lambda value: value["issues"].__setitem__(0, True),
            "tracker observations must match requested issues":
                lambda value: value["tracker"].clear(),
            "duplicate tracker observation":
                lambda value: value["tracker"].append(dict(value["tracker"][0])),
            "invalid tracker state":
                lambda value: value["tracker"][0].__setitem__("state", "merged"),
            "invalid tracker observation fields":
                lambda value: value["tracker"][0].pop("decision_blockers"),
            "invalid tracker open blocker":
                lambda value: value["tracker"][0].__setitem__("open_blockers", [True]),
            "invalid decision blocker fields":
                lambda value: value["tracker"][0].__setitem__(
                    "decision_blockers", [{"issue": 40}]
                ),
            "invalid decision blocker issue":
                lambda value: value["tracker"][0].__setitem__(
                    "decision_blockers", [{"issue": True, "url": "https://example.test/40"}]
                ),
            "invalid decision blocker url":
                lambda value: value["tracker"][0].__setitem__(
                    "decision_blockers", [{"issue": 40, "url": 40}]
                ),
            "decision blocker url":
                lambda value: value["tracker"][0].__setitem__(
                    "decision_blockers", [{"issue": 40, "url": None}]
                ),
            "invalid max_parallel":
                lambda value: value.__setitem__("max_parallel", True),
            "invalid attempt_budget_minutes":
                lambda value: value.__setitem__("attempt_budget_minutes", False),
            "invalid owner observation fields":
                lambda value: value["owners"].append({
                    "event_id": "x", "issue": 47, "attempt": 1, "launch": 1,
                }),
            "invalid owner event_id":
                lambda value: value["owners"].append(self.owner_fact(
                    event_id="", issue=47, attempt=1, launch=1
                )),
            "invalid owner state":
                lambda value: value["owners"].append(self.owner_fact(
                    event_id="x", issue=47, attempt=1, launch=1, state="dead"
                )),
            "invalid owner attempt":
                lambda value: value["owners"].append(self.owner_fact(
                    event_id="x", issue=47, attempt=True, launch=1
                )),
            "invalid owner issue":
                lambda value: value["owners"].append(self.owner_fact(
                    event_id="x", issue=True, attempt=1, launch=1
                )),
            "invalid owner launch":
                lambda value: value["owners"].append(self.owner_fact(
                    event_id="x", issue=47, attempt=1, launch=False
                )),
            "duplicate worktree observation":
                lambda value: value["worktrees"].append(copy.deepcopy(value["worktrees"][0])),
            "invalid candidate path":
                lambda value: value["worktrees"][0]["candidate"].__setitem__("path", "wt-47"),
            "invalid candidate fields":
                lambda value: value["worktrees"][0]["candidate"].pop("state"),
            "invalid candidate state":
                lambda value: value["worktrees"][0]["candidate"].__setitem__("state", "free"),
            "invalid recorded fields":
                lambda value: value["worktrees"][0].__setitem__(
                    "recorded", {"path": str(self.root / "wt-47")}
                ),
            "worktree observation outside requested issues":
                lambda value: value["worktrees"][0].__setitem__("issue", 99),
            "control time must not move backward":
                lambda value: value.__setitem__("now", "2026-08-19T11:59:59Z"),
        }
        before = self.state_path.read_bytes()
        for message, mutate in mutations.items():
            with self.subTest(message=message):
                request = copy.deepcopy(valid)
                mutate(request)
                completed = self.control_raw(request=request, ok=False)
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(completed.stdout, "")
                expected = ("invalid owner custody" if message in {
                    "invalid owner attempt", "invalid owner launch"} else message)
                self.assertIn(expected, completed.stderr)
                self.assertEqual(self.state_path.read_bytes(), before)

    def test_control_rejects_nonpositive_max_parallel(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        before = self.state_path.read_bytes()
        for max_parallel in (0, -1):
            with self.subTest(max_parallel=max_parallel):
                completed = self.control_raw(
                    now="2026-08-19T12:00:00Z",
                    issues=[47],
                    max_parallel=max_parallel,
                    tracker=[self.tracker_fact(47)],
                    worktrees=[],
                    ok=False,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(completed.stdout, "")
                self.assertIn("invalid max_parallel", completed.stderr)
                self.assertEqual(self.state_path.read_bytes(), before)

    def test_control_rejects_bad_request_files_and_recorded_path_mismatch(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        for request_path, message in (
            ("relative.json", "request file path must be absolute"),
            (self.root / "missing.json", "cannot read control request file"),
        ):
            with self.subTest(message=message):
                completed = self.run_cli(
                    "control", "--repo-root", self.root, "--run-id", self.run_id,
                    "--request-file", request_path, ok=False,
                )
                self.assertIn(message, completed.stderr)
        invalid_json = self.root / "invalid-control.json"
        invalid_json.write_text("{", encoding="utf-8")
        completed = self.run_cli(
            "control", "--repo-root", self.root, "--run-id", self.run_id,
            "--request-file", invalid_json, ok=False,
        )
        self.assertIn("invalid control request JSON", completed.stderr)

        path = str(self.root / "wt-47")
        self.control(now="2026-08-19T12:00:00Z", issues=[47],
                     tracker=[self.tracker_fact(47)],
                     worktrees=[self.worktree_fact(
                         47, candidate={"path": path, "state": "absent"})])
        before = self.state_path.read_bytes()
        mismatch = self.control_raw(
            now="2026-08-19T12:01:00Z", issues=[47],
            tracker=[self.tracker_fact(47)],
            worktrees=[self.worktree_fact(47, recorded={
                "path": str(self.root / "other"),
                "state": "matching_issue_branch",
            })], ok=False,
        )
        self.assertIn("recorded worktree path does not match ledger", mismatch.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_control_uses_recorded_state_to_select_retry_worktree(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        issues = [47, 51]
        recorded_paths = {issue: str(self.root / f"wt-{issue}") for issue in issues}
        candidate_paths = {
            issue: str(self.root / f"replacement-{issue}") for issue in issues
        }
        self.control(
            now="2026-08-19T12:00:00Z",
            issues=issues,
            tracker=[self.tracker_fact(issue) for issue in issues],
            worktrees=[
                self.worktree_fact(
                    issue,
                    candidate={"path": recorded_paths[issue], "state": "absent"},
                )
                for issue in issues
            ],
        )
        failed = {
            **self.merged_result(47),
            "state": "failed",
            "pr_url": None,
            "merge_sha": None,
            "issue_closed": False,
            "notes": "owner unavailable",
        }
        for issue in issues:
            self.finish(1, {**failed, "issue": issue}, issue=issue,
                        now="2026-08-19T12:05:00Z")

        before = self.state_path.read_bytes()
        missing_candidate = self.control_raw(
            now="2026-08-19T12:06:00Z",
            issues=issues,
            tracker=[self.tracker_fact(issue) for issue in issues],
            worktrees=[
                self.worktree_fact(
                    47,
                    recorded={"path": recorded_paths[47], "state": "absent"},
                ),
                self.worktree_fact(
                    51,
                    recorded={"path": recorded_paths[51], "state": "mismatch"},
                    candidate={"path": candidate_paths[51], "state": "absent"},
                ),
            ],
            ok=False,
        )
        self.assertIn("verified worktree observation", missing_candidate.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

        response = self.control(
            now="2026-08-19T12:06:00Z",
            issues=issues,
            tracker=[self.tracker_fact(issue) for issue in issues],
            worktrees=[
                self.worktree_fact(
                    47,
                    recorded={"path": recorded_paths[47], "state": "absent"},
                    candidate={"path": candidate_paths[47], "state": "absent"},
                ),
                self.worktree_fact(
                    51,
                    recorded={"path": recorded_paths[51], "state": "mismatch"},
                    candidate={"path": candidate_paths[51], "state": "absent"},
                ),
            ],
        )
        self.assertEqual(
            [(action["issue"], action["worktree"]) for action in response["actions"][:-1]],
            [(47, candidate_paths[47]), (51, candidate_paths[51])],
        )
        state = self.read_state()
        self.assertEqual(
            [state["issues"][str(issue)]["attempts"][-1]["worktree"] for issue in issues],
            [candidate_paths[47], candidate_paths[51]],
        )

    def test_an_unmatched_resume_refuses_its_issue_unless_a_candidate_would_move_it(self):
        """An unavailable owner's resume on an absent or mismatched worktree (#194 D8).

        Without a candidate only the issue is refused, in its summary, and the
        sweep's claim release persists. A candidate never relocates a resume,
        so it still refuses the whole sweep, at the current-action check.
        """
        self.init_run(now="2026-08-19T12:00:00Z")
        path = str(self.root / "wt-47")
        replacement = str(self.root / "replacement-47")
        self.control(
            now="2026-08-19T12:00:00Z", issues=[47],
            tracker=[self.tracker_fact(47)],
            worktrees=[self.worktree_fact(
                47, candidate={"path": path, "state": "absent"})],
        )
        before = self.state_path.read_bytes()
        for recorded_state in ("absent", "mismatch"):
            request = {"now": "2026-08-19T12:01:00Z", "issues": [47],
                       "tracker": [self.tracker_fact(47)],
                       "owners": [self.owner_fact(event_id=f"47-{recorded_state}",
                                                  issue=47, attempt=1, launch=1)]}
            recorded = {"path": path, "state": recorded_state}
            with self.subTest(recorded_state=recorded_state, candidate=True):
                rejected = self.control_raw(
                    **request, ok=False, worktrees=[self.worktree_fact(
                        47, recorded=recorded,
                        candidate={"path": replacement, "state": "absent"})])
                self.assertEqual((rejected.returncode, rejected.stdout), (2, ""))
                self.assertIn(
                    "current control action requires a recorded worktree observation",
                    rejected.stderr)
                self.assertEqual(self.state_path.read_bytes(), before)
            with self.subTest(recorded_state=recorded_state, candidate=False):
                response = self.control_validated(
                    **request, worktrees=[self.worktree_fact(47, recorded=recorded)])
                self.assertEqual([item["kind"] for item in response["actions"]], ["wait"])
                self.assertEqual(response["deltas"], [])
                summary = response["summaries"][0]
                self.assertEqual(summary["state"], "active")
                self.assertIn(self.unresumable_fact(path, recorded_state),
                              summary["requirements"])
                state = self.read_state()
                self.assertEqual(state["issues"]["47"], json.loads(before)["issues"]["47"])
                self.assertEqual(
                    [(claim["holder"], claim["release_event"])
                     for claim in state["admission"]["claims"]],
                    [("controller", None), ("47:1:1", "owner_unavailable")])
            self.state_path.write_bytes(before)

    def test_an_unresumable_suspension_refuses_only_its_own_issue(self):
        """T1, T2 (#194): its neighbour spawns, and the refused issue is reported, unchanged.

        `max_parallel=1` is the discriminating case: a refused issue that
        took a unit would leave its neighbour unspawned.
        """
        for recorded_state, max_parallel in (
                ("absent", 1), ("absent", 2), ("mismatch", 1), ("mismatch", 2)):
            with self.subTest(recorded_state=recorded_state, max_parallel=max_parallel):
                self.run_id = f"unresumable-{recorded_state}-{max_parallel}"
                self.init_run()
                path = os.path.abspath(self.root / f"wt-47-{recorded_state}-{max_parallel}")
                spare = os.path.abspath(self.root / f"wt-51-{recorded_state}-{max_parallel}")
                self.spawn(issue=47, worktree=path)
                self.progress(issue=47, phase=1, now="2026-08-13T20:01:00Z")
                self.suspend(issue=47, attempt=1, blocked_on="usage_limit",
                             now="2026-08-13T20:02:00Z")
                before = self.read_state()["issues"]["47"]
                response = self.control_validated(
                    now="2026-08-13T20:03:00Z", issues=[47, 51],
                    tracker=[self.tracker_fact(47), self.tracker_fact(51)],
                    worktrees=[
                        self.worktree_fact(47, recorded={"path": path,
                                                         "state": recorded_state}),
                        self.worktree_fact(51, candidate={"path": spare,
                                                          "state": "absent"})],
                    max_parallel=max_parallel)
                self.assertEqual(
                    [(item["kind"], item.get("issue")) for item in response["actions"]],
                    [("spawn", 51), ("wait", None)])
                self.assertEqual([(item["issue"], item["kind"]) for item in response["deltas"]],
                                 [(51, "spawned")])
                self.assertEqual(response["admission"]["waiting"], [])
                summary = response["summaries"][0]
                self.assertEqual((summary["issue"], summary["state"], summary["blocked_on"]),
                                 (47, "suspended", "usage_limit"))
                self.assertIn(self.unresumable_fact(path, recorded_state),
                              summary["requirements"])
                state = self.read_state()
                self.assertEqual(state["issues"]["47"], before)
                self.assertFalse(any(
                    claim["holder"].startswith("47:") and claim["released_at"] is None
                    for claim in state["admission"]["claims"]))

    def test_an_unresumable_expired_handoff_still_persists_its_reap(self):
        """T4 (#194): the refused issue keeps this sweep's reap and its `expired` delta."""
        self.init_run()
        path = os.path.abspath(self.root / "wt-48")
        self.spawn(issue=48, worktree=path)
        handoff = self.write_handoff(48)
        self.progress(issue=48, phase=1, now="2026-08-13T20:01:00Z",
                      turn_count=118, handoff_path=handoff)
        attempt = self.read_state()["issues"]["48"]["attempts"][-1]
        self.assertEqual((attempt["state"], attempt["deadline_at"]),
                         ("handed_off", "2026-08-13T20:30:00Z"))
        response = self.control_validated(
            now="2026-08-13T21:00:00Z", issues=[48],
            tracker=[self.tracker_fact(48)],
            worktrees=[self.worktree_fact(48, recorded={"path": path, "state": "absent"})],
            max_parallel=1)
        self.assertEqual(response["actions"], [{"id": "finalize", "kind": "finalize"}])
        self.assertEqual(
            [(item["issue"], item["kind"], item["state"]) for item in response["deltas"]],
            [(48, "expired", "suspended")])
        self.assertIn(self.unresumable_fact(path, "absent"),
                      response["summaries"][0]["requirements"])
        attempt = self.read_state()["issues"]["48"]["attempts"][-1]
        self.assertEqual((attempt["state"], attempt["blocked_on"]), ("suspended", "unknown"))

    def test_control_rejects_candidate_path_aliases_atomically(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        shared = str(self.root / "shared-worktree")
        before = self.state_path.read_bytes()
        duplicate = self.control_raw(
            now="2026-08-19T12:00:00Z", issues=[47, 51], max_parallel=2,
            tracker=[self.tracker_fact(47), self.tracker_fact(51)],
            worktrees=[
                self.worktree_fact(
                    47, candidate={"path": shared, "state": "absent"}),
                self.worktree_fact(
                    51, candidate={"path": shared, "state": "absent"}),
            ], ok=False,
        )
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn("candidate worktree path", duplicate.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

        self.control(
            now="2026-08-19T12:00:00Z", issues=[47],
            tracker=[self.tracker_fact(47)],
            worktrees=[self.worktree_fact(
                47, candidate={"path": shared, "state": "absent"})],
        )
        recorded = self.state_path.read_bytes()
        alias = self.control_raw(
            now="2026-08-19T12:01:00Z", issues=[47, 51], max_parallel=2,
            tracker=[self.tracker_fact(47), self.tracker_fact(51)],
            worktrees=[self.worktree_fact(
                51, candidate={"path": shared, "state": "absent"})],
            ok=False,
        )
        self.assertNotEqual(alias.returncode, 0)
        self.assertIn("candidate worktree path", alias.stderr)
        self.assertEqual(self.state_path.read_bytes(), recorded)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_control_rejects_candidates_aliasing_through_symlinked_parents(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        real_parent = self.root / "real-worktrees"
        real_parent.mkdir()
        alias_parent = self.root / "worktree-alias"
        alias_parent.symlink_to(real_parent, target_is_directory=True)
        before = self.state_path.read_bytes()
        rejected = self.control_raw(
            now="2026-08-19T12:00:00Z", issues=[47, 51], max_parallel=2,
            tracker=[self.tracker_fact(47), self.tracker_fact(51)],
            worktrees=[
                self.worktree_fact(47, candidate={
                    "path": str(real_parent / "shared"), "state": "absent",
                }),
                self.worktree_fact(51, candidate={
                    "path": str(alias_parent / "shared"), "state": "absent",
                }),
            ],
            ok=False,
        )
        self.assertIn("candidate worktree path", rejected.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_control_accepts_shared_candidate_when_no_action_consumes_it(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        shared = str(self.root / "unused-shared-worktree")
        response = self.control(
            now="2026-08-19T12:00:00Z", issues=[47, 51], max_parallel=2,
            tracker=[
                self.tracker_fact(47, open_blockers=[40]),
                self.tracker_fact(51, open_blockers=[40]),
            ],
            worktrees=[
                self.worktree_fact(
                    47, candidate={"path": shared, "state": "absent"}),
                self.worktree_fact(
                    51, candidate={"path": shared, "state": "absent"}),
            ],
        )
        self.assertEqual([s["state"] for s in response["summaries"]],
                         ["blocked", "blocked"])
        self.assertEqual(response["deltas"], [])
        self.assertEqual(response["actions"], [{"id": "finalize", "kind": "finalize"}])
        self.assertIsNone(response["next_deadline"])
        self.assertEqual(self.read_state()["issues"], {})

    def test_control_consumed_candidate_replay_is_strictly_bounded(self):
        now = "2026-08-19T12:00:00Z"
        path = str(self.root / "wt-47")
        self.init_run(now=now)
        original = self.control(
            now=now, issues=[47],
            tracker=[self.tracker_fact(47)],
            worktrees=[self.worktree_fact(
                47, candidate={"path": path, "state": "absent"})],
        )
        self.assertEqual([action["kind"] for action in original["actions"]],
                         ["spawn", "wait"])
        active = self.state_path.read_bytes()

        rejected = {
            "wrong instant": self.control_request(
                now="2026-08-19T12:00:01Z", issues=[47],
                tracker=[self.tracker_fact(47)],
                worktrees=[self.worktree_fact(
                    47, candidate={"path": path, "state": "absent"})],
            ),
            "wrong path": self.control_request(
                now=now, issues=[47],
                tracker=[self.tracker_fact(47)],
                worktrees=[self.worktree_fact(47, candidate={
                    "path": str(self.root / "other-47"), "state": "absent",
                })],
            ),
            "current unavailable": self.control_request(
                now=now, issues=[47],
                tracker=[self.tracker_fact(47)],
                owners=[self.owner_fact(
                    event_id="unavailable-47-1-1", issue=47, attempt=1, launch=1,
                )],
                worktrees=[self.worktree_fact(
                    47, candidate={"path": path, "state": "absent"})],
            ),
            "new dispatch": self.control_request(
                now=now, issues=[47, 51],
                tracker=[self.tracker_fact(47), self.tracker_fact(51)],
                worktrees=[
                    self.worktree_fact(
                        47, candidate={"path": path, "state": "absent"}),
                    self.worktree_fact(51, candidate={
                        "path": str(self.root / "wt-51"), "state": "absent",
                    }),
                ],
            ),
        }
        for case, request in rejected.items():
            with self.subTest(case=case):
                completed = self.control_raw(request=request, ok=False)
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(completed.stdout, "")
                self.assertIn("recorded worktree observation", completed.stderr)
                self.assertEqual(self.state_path.read_bytes(), active)

        replayed = self.control(
            now=now, issues=[47],
            tracker=[self.tracker_fact(47)],
            worktrees=[self.worktree_fact(
                47, candidate={"path": path, "state": "absent"})],
        )
        self.assertEqual(replayed["deltas"], [])
        self.assertEqual([action["kind"] for action in replayed["actions"]], ["wait"])
        self.assertEqual(self.state_path.read_bytes(), active)

        self.finish(1, self.merged_result(47), issue=47, now=now)
        terminal = self.state_path.read_bytes()
        completed = self.control_raw(
            now=now, issues=[47],
            tracker=[self.tracker_fact(47)],
            worktrees=[self.worktree_fact(
                47, candidate={"path": path, "state": "absent"})],
            ok=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")
        self.assertIn("recorded worktree observation", completed.stderr)
        self.assertEqual(self.state_path.read_bytes(), terminal)

    def test_control_combined_six_stage_single_ledger_replay(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        paths = {issue: str(self.root / f"wt-{issue}") for issue in (47, 51, 53)}

        # 1. Two dispatches, one queued issue, one earliest deadline.
        initial = self.control(
            now="2026-08-19T12:00:00Z", issues=[47, 51, 53], max_parallel=2,
            attempt_budget_minutes=30,
            tracker=[self.tracker_fact(i) for i in (47, 51, 53)],
            worktrees=[self.worktree_fact(
                i, candidate={"path": paths[i], "state": "absent"}
            ) for i in (47, 51, 53)],
        )
        self.assertEqual([a["id"] for a in initial["actions"]],
                         ["47:1:1", "51:1:1", "wait:2026-08-19T12:30:00Z"])
        self.assertEqual(initial["summaries"][2]["state"], "queued")
        self.assertEqual(initial["next_deadline"], "2026-08-19T12:30:00Z")

        # 2. The first owner succeeds after its fixed deadline; owner truth wins.
        late = self.merged_result(47)
        self.finish(1, late, issue=47, now="2026-08-19T12:31:00Z")
        self.assertEqual(self.read_state()["issues"]["47"]["outcome"], late)

        # Capture the exact state immediately before the composite expiry/retry/spawn.
        pre_action_state = self.state_path.read_bytes()
        decision_request = self.control_request(
            now="2026-08-19T12:31:00Z", issues=[47, 51, 53], max_parallel=2,
            attempt_budget_minutes=30,
            tracker=[self.tracker_fact(i) for i in (47, 51, 53)],
            worktrees=[
                self.worktree_fact(51, recorded={
                    "path": paths[51], "state": "matching_issue_branch",
                }),
                self.worktree_fact(53, candidate={
                    "path": paths[53], "state": "absent",
                }),
            ],
        )

        # 3. Silent expiry resumes attempt 1 in place on the recorded path
        #    while unrelated work starts.
        decision = self.control_raw(request=decision_request)
        decided = json.loads(decision.stdout)
        self.assertEqual([d["kind"] for d in decided["deltas"]],
                         ["expired", "resumed", "spawned"])
        self.assertEqual([a["id"] for a in decided["actions"]],
                         ["51:1:2", "53:1:1", "wait:2026-08-19T13:01:00Z"])
        self.assertEqual(decided["actions"][0]["worktree"], paths[51])
        post_action_state = self.state_path.read_bytes()

        # 4. The resumed owner and unrelated active owner finish concurrently.
        finished = self.concurrent_finish(
            {51: (1, self.merged_result(51)), 53: (1, self.merged_result(53))},
            now="2026-08-19T12:40:00Z",
        )
        self.assertEqual(sum(process.returncode == 0 for process in finished), 2)
        reopened = self.read_state()
        self.assertEqual(reopened["issues"]["51"]["outcome"], self.merged_result(51))
        self.assertEqual(reopened["issues"]["53"]["outcome"], self.merged_result(53))

        # 5. One current summary per issue and one finalize action drain the run.
        final_request = self.control_request(
            now="2026-08-19T12:41:00Z", issues=[47, 51, 53], max_parallel=2,
            attempt_budget_minutes=30,
            tracker=[self.tracker_fact(i, state="closed") for i in (47, 51, 53)],
            worktrees=[],
        )
        final = self.control_raw(request=final_request)
        final_value = json.loads(final.stdout)
        self.assertEqual(final_value["actions"], [{"id": "finalize", "kind": "finalize"}])
        self.assertEqual([s["issue"] for s in final_value["summaries"]], [47, 51, 53])
        self.assertTrue(all(s["state"] == "merged" for s in final_value["summaries"]))
        self.assertIsNone(final_value["next_deadline"])
        final_bytes = self.state_path.read_bytes()
        final_replay = self.control_raw(request=final_request)
        self.assertEqual(final_replay.stdout, final.stdout)
        self.assertEqual(self.state_path.read_bytes(), final_bytes)

        # 6. Replay both sides of the composite decision after the main run drains.
        copied_pre_root = self.copy_ledger_root(pre_action_state)
        copied_pre = self.run_control_at_root(copied_pre_root, decision_request)
        self.assertEqual(copied_pre.stdout, decision.stdout)
        copied_advanced_root = self.copy_ledger_root(post_action_state)
        copied_advanced_state = (
            copied_advanced_root / ".superpowers" / "workflows" /
            self.run_id / "state.json"
        )
        advanced_before = copied_advanced_state.read_bytes()
        copied_advanced = self.run_control_at_root(copied_advanced_root, decision_request)
        replayed_value = json.loads(copied_advanced.stdout)
        self.assertEqual([a["kind"] for a in replayed_value["actions"]], ["wait"])
        self.assertEqual(replayed_value["deltas"], [])
        self.assertEqual(copied_advanced_state.read_bytes(), advanced_before)

        for response in (initial, decided, replayed_value, final_value):
            self.assert_control_response_shape(response)
            rendered = json.dumps(response)
            for forbidden in ("attempts", "launches", "phase_inputs", "prior_attempt"):
                self.assertNotIn(forbidden, rendered)

    def test_control_demo_1_starts_two_and_waits_at_the_earliest_deadline(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        response = self.control(
            now="2026-08-19T12:00:00Z", issues=[47, 51, 53], max_parallel=2,
            attempt_budget_minutes=180,
            tracker=[self.tracker_fact(i) for i in (47, 51, 53)],
            worktrees=[self.worktree_fact(
                i, candidate={"path": str(self.root / f"wt-{i}"), "state": "absent"}
            ) for i in (47, 51, 53)],
        )
        self.assertEqual([a["kind"] for a in response["actions"]],
                         ["spawn", "spawn", "wait"])
        self.assertEqual(response["next_deadline"], "2026-08-19T15:00:00Z")
        self.assertEqual(response["summaries"][2]["state"], "queued")

    def test_control_demo_2_late_merged_finish_beats_the_deadline(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        self.control(
            now="2026-08-19T12:00:00Z", issues=[47, 51], max_parallel=2,
            attempt_budget_minutes=30,
            tracker=[self.tracker_fact(47), self.tracker_fact(51)],
            worktrees=[self.worktree_fact(
                i, candidate={"path": str(self.root / f"wt-{i}"), "state": "absent"}
            ) for i in (47, 51)],
        )
        result = self.merged_result(47)
        self.finish(1, result, issue=47, now="2026-08-19T12:31:00Z")
        response = self.control(
            now="2026-08-19T12:31:00Z", issues=[47, 51], max_parallel=2,
            attempt_budget_minutes=30,
            tracker=[self.tracker_fact(47),
                     self.tracker_fact(51, open_blockers=[40])], worktrees=[],
        )
        summary = next(item for item in response["summaries"] if item["issue"] == 47)
        self.assertEqual(summary["state"], "merged")
        self.assertEqual(summary["result"], result)
        self.assertNotIn(47, [d["issue"] for d in response["deltas"] if d["kind"] == "expired"])

    def test_control_demo_3_expires_resumes_and_fills_unrelated_capacity(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        paths = {i: str(self.root / f"wt-{i}") for i in (47, 51, 53)}
        self.control(
            now="2026-08-19T12:00:00Z", issues=[47, 51, 53], max_parallel=2,
            attempt_budget_minutes=30,
            tracker=[self.tracker_fact(i) for i in (47, 51, 53)],
            worktrees=[self.worktree_fact(
                i, candidate={"path": paths[i], "state": "absent"}
            ) for i in (47, 51, 53)],
        )
        self.finish(1, self.merged_result(47), issue=47, now="2026-08-19T12:20:00Z")
        response = self.control(
            now="2026-08-19T12:30:00Z", issues=[47, 51, 53], max_parallel=2,
            attempt_budget_minutes=30,
            tracker=[self.tracker_fact(i) for i in (47, 51, 53)],
            worktrees=[
                self.worktree_fact(51, recorded={"path": paths[51], "state": "matching_issue_branch"}),
                self.worktree_fact(53, candidate={"path": paths[53], "state": "absent"}),
            ],
        )
        self.assertEqual([a["kind"] for a in response["actions"]],
                         ["resume", "spawn", "wait"])
        resume, spawn = response["actions"][:2]
        self.assertEqual((resume["id"], resume["worktree"]), ("51:1:2", paths[51]))
        self.assertEqual((spawn["id"], spawn["issue"]), ("53:1:1", 53))
        self.assertEqual([d["kind"] for d in response["deltas"]],
                         ["expired", "resumed", "spawned"])

    def test_control_expiry_deltas_follow_reversed_request_order(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        issues = [47, 51]
        self.control(
            now="2026-08-19T12:00:00Z", issues=issues,
            tracker=[self.tracker_fact(issue) for issue in issues],
            worktrees=[self.worktree_fact(
                issue,
                candidate={"path": str(self.root / f"wt-{issue}"), "state": "absent"},
            ) for issue in issues],
        )
        response = self.control(
            now="2026-08-19T12:30:00Z", issues=[51, 47],
            tracker=[self.tracker_fact(issue, open_blockers=[40])
                     for issue in (51, 47)],
            worktrees=[],
        )
        self.assertEqual([item["issue"] for item in response["summaries"]], [51, 47])
        self.assertEqual(response["deltas"], [
            {"issue": 51, "attempt": 1, "kind": "expired", "state": "suspended"},
            {"issue": 47, "attempt": 1, "kind": "expired", "state": "suspended"},
        ])

    def test_control_subset_does_not_expire_or_report_unrequested_issue(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        issues = [47, 51]
        self.control(
            now="2026-08-19T12:00:00Z", issues=issues,
            tracker=[self.tracker_fact(issue) for issue in issues],
            worktrees=[self.worktree_fact(
                issue,
                candidate={"path": str(self.root / f"wt-{issue}"), "state": "absent"},
            ) for issue in issues],
        )
        unrequested_before = copy.deepcopy(self.read_state()["issues"]["51"])
        response = self.control(
            now="2026-08-19T12:30:00Z", issues=[47],
            tracker=[self.tracker_fact(47, open_blockers=[40])],
            worktrees=[],
        )
        self.assertEqual([item["issue"] for item in response["summaries"]], [47])
        self.assertEqual([item["issue"] for item in response["deltas"]], [47])
        self.assertFalse(any(item.get("issue") == 51 for item in response["actions"]))
        self.assertIsNone(response["next_deadline"])
        self.assertEqual(self.read_state()["issues"]["51"], unrequested_before)

    def test_control_demo_4_concurrent_finishes_survive_reopen(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        paths = {i: str(self.root / f"wt-{i}") for i in (47, 51)}
        self.control(
            now="2026-08-19T12:00:00Z", issues=[47, 51], max_parallel=2,
            tracker=[self.tracker_fact(47), self.tracker_fact(51)],
            worktrees=[self.worktree_fact(
                i, candidate={"path": paths[i], "state": "absent"}
            ) for i in (47, 51)],
        )
        failed = {**self.merged_result(47), "state": "failed", "pr_url": None,
                  "merge_sha": None, "issue_closed": False, "notes": "harness"}
        self.finish(1, failed, issue=47, now="2026-08-19T12:04:00Z")
        self.control(
            now="2026-08-19T12:05:00Z", issues=[47, 51], max_parallel=2,
            tracker=[self.tracker_fact(47), self.tracker_fact(51)],
            worktrees=[self.worktree_fact(
                47, recorded={"path": paths[47], "state": "matching_issue_branch"}
            )],
        )
        completed = self.concurrent_finish(
            {47: (2, self.merged_result(47)), 51: (1, self.merged_result(51))},
            now="2026-08-19T12:10:00Z",
        )
        self.assertEqual(sum(item.returncode == 0 for item in completed), 2)
        reopened = self.read_state()
        self.assertEqual(reopened["issues"]["47"]["outcome"], self.merged_result(47))
        self.assertEqual(reopened["issues"]["51"]["outcome"], self.merged_result(51))

    def test_control_demo_5_finalizes_and_replays_without_history_or_duplicate_launch(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        path = str(self.root / "wt-47")
        request = self.control_request(
            now="2026-08-19T12:00:00Z", issues=[47],
            tracker=[self.tracker_fact(47)],
            worktrees=[self.worktree_fact(
                47, candidate={"path": path, "state": "absent"}
            )],
        )
        before = self.state_path.read_bytes()
        first = self.control_raw(request=request)
        advanced = self.state_path.read_bytes()
        copied_root = self.copy_ledger_root(before)
        copied = self.run_control_at_root(copied_root, request)
        self.assertEqual(first.stdout, copied.stdout)
        repeated_request = self.control_request(
            now="2026-08-19T12:00:00Z", issues=[47],
            tracker=[self.tracker_fact(47)],
            worktrees=[],
        )
        repeated = self.control_raw(request=repeated_request)
        self.assertEqual(self.state_path.read_bytes(), advanced)
        self.assertEqual([a["kind"] for a in json.loads(repeated.stdout)["actions"]], ["wait"])
        self.finish(1, self.merged_result(47), issue=47, now="2026-08-19T12:10:00Z")
        final = self.control(
            now="2026-08-19T12:10:00Z", issues=[47],
            tracker=[self.tracker_fact(47, state="closed")], worktrees=[],
        )
        self.assertEqual(final["actions"], [{"id": "finalize", "kind": "finalize"}])
        self.assertEqual(len(final["summaries"]), 1)
        for forbidden in ("attempts", "launches", "phase_inputs", "prior_attempt"):
            self.assertNotIn(forbidden, json.dumps(final))

    def test_control_orders_resumes_before_retry_before_spawn(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        paths = {i: str(self.root / f"wt-{i}") for i in (47, 51, 53, 59)}
        self.control(
            now="2026-08-19T12:00:00Z", issues=[47, 51, 53, 59], max_parallel=3,
            tracker=[self.tracker_fact(i, open_blockers=[40] if i == 59 else [])
                     for i in (47, 51, 53, 59)],
            worktrees=[self.worktree_fact(
                i, candidate={"path": paths[i], "state": "absent"}
            ) for i in (47, 51, 53)],
        )
        handoff = self.write_handoff(47)
        self.progress(issue=47, phase=1, now="2026-08-19T12:05:00Z",
                      context_tokens=140000, handoff_path=handoff)
        failed = {**self.merged_result(53), "state": "failed", "pr_url": None,
                  "merge_sha": None, "issue_closed": False, "notes": "harness"}
        self.finish(1, failed, issue=53, now="2026-08-19T12:05:00Z")
        response = self.control(
            now="2026-08-19T12:06:00Z", issues=[47, 51, 53, 59], max_parallel=4,
            tracker=[self.tracker_fact(i) for i in (47, 51, 53, 59)],
            owners=[self.owner_fact(event_id="51-a1-exit", issue=51,
                                    attempt=1, launch=1)],
            worktrees=[
                self.worktree_fact(i, recorded={"path": paths[i],
                                                "state": "matching_issue_branch"})
                for i in (47, 51, 53)
            ] + [self.worktree_fact(
                59, candidate={"path": paths[59], "state": "absent"}
            )],
        )
        self.assert_control_response_shape(response)
        self.assertEqual([a["kind"] for a in response["actions"]],
                         ["resume", "resume", "retry", "spawn", "wait"])
        self.assertEqual([a["id"] for a in response["actions"][:-1]],
                         ["47:1:2", "51:1:2", "53:2:1", "59:1:1"])
        self.assertEqual(response["actions"][0], {
            "id": "47:1:2", "kind": "resume", "issue": 47, "attempt": 1,
            "owner": "47:1", "worktree": paths[47],
            "handoff_path": str(handoff), "deadline_at": "2026-08-19T12:30:00Z",
        })
        self.assertEqual(response["actions"][1], {
            "id": "51:1:2", "kind": "resume", "issue": 51, "attempt": 1,
            "owner": "51:1", "worktree": paths[51], "handoff_path": None,
            "deadline_at": "2026-08-19T12:30:00Z",
        })
        self.assertEqual(response["actions"][2], {
            "id": "53:2:1", "kind": "retry", "issue": 53, "attempt": 2,
            "owner": "53:2", "worktree": paths[53], "handoff_path": None,
            "deadline_at": "2026-08-19T12:36:00Z",
        })

    def test_control_ignores_consumed_owner_event_and_rejects_future_event_atomically(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        path = str(self.root / "wt-47")
        self.control(now="2026-08-19T12:00:00Z", issues=[47],
                     tracker=[self.tracker_fact(47)],
                     worktrees=[self.worktree_fact(
                         47, candidate={"path": path, "state": "absent"})])
        event = self.owner_fact(event_id="47-a1-exit", issue=47, attempt=1, launch=1)
        facts = [self.worktree_fact(
            47, recorded={"path": path, "state": "matching_issue_branch"})]
        resumed = self.control(now="2026-08-19T12:01:00Z", issues=[47],
                               tracker=[self.tracker_fact(47)], owners=[event],
                               worktrees=facts)
        self.assertEqual(resumed["actions"][0]["id"], "47:1:2")
        repeated = self.control(now="2026-08-19T12:01:00Z", issues=[47],
                                tracker=[self.tracker_fact(47)], owners=[event],
                                worktrees=[])
        self.assertEqual([a["kind"] for a in repeated["actions"]], ["wait"])
        before = self.state_path.read_bytes()
        future = self.owner_fact(event_id="47-future", issue=47,
                                 attempt=1, launch=3)
        rejected = self.control_raw(now="2026-08-19T12:02:00Z", issues=[47],
                                    tracker=[self.tracker_fact(47)], owners=[future],
                                    worktrees=[], ok=False)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_control_does_not_retry_owner_stopped_and_refuses_attempt_three(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        paths = {i: str(self.root / f"wt-{i}") for i in (47, 51)}
        self.control(now="2026-08-19T12:00:00Z", issues=[47, 51],
                     tracker=[self.tracker_fact(47), self.tracker_fact(51)],
                     worktrees=[self.worktree_fact(
                         i, candidate={"path": paths[i], "state": "absent"})
                         for i in (47, 51)])
        stopped = {**self.merged_result(47), "state": "stopped", "pr_url": None,
                   "merge_sha": None, "issue_closed": False, "notes": "content verdict"}
        failed = {**self.merged_result(51), "state": "failed", "pr_url": None,
                  "merge_sha": None, "issue_closed": False, "notes": "harness"}
        self.finish(1, stopped, issue=47, now="2026-08-19T12:05:00Z")
        self.finish(1, failed, issue=51, now="2026-08-19T12:05:00Z")
        retry = self.control(
            now="2026-08-19T12:06:00Z", issues=[47, 51],
            tracker=[self.tracker_fact(47), self.tracker_fact(51)],
            worktrees=[self.worktree_fact(
                51, recorded={"path": paths[51], "state": "matching_issue_branch"})],
        )
        self.assertNotIn(47, [a.get("issue") for a in retry["actions"]])
        self.assertEqual(retry["actions"][0]["id"], "51:2:1")
        self.finish(2, failed, issue=51, now="2026-08-19T12:07:00Z")
        refused = self.control(now="2026-08-19T12:08:00Z", issues=[47, 51],
                               tracker=[self.tracker_fact(47), self.tracker_fact(51)],
                               worktrees=[])
        self.assert_control_response_shape(refused)
        refusal_delta = next(d for d in refused["deltas"] if d["issue"] == 51)
        self.assertEqual(refusal_delta, {
            "issue": 51, "attempt": 2, "kind": "retry_refused", "state": "failed",
        })
        summary = next(s for s in refused["summaries"] if s["issue"] == 51)
        self.assertEqual(set(summary["result"]), {
            "issue", "state", "pr_url", "merge_sha", "issue_closed",
            "discussion_items", "detail_state", "report_path", "notes",
        })
        self.assertEqual(summary["result"]["state"], "failed")
        self.assertIn("attempts 1 and 2", summary["result"]["notes"])
        persisted = self.read_state()["issues"]["51"]
        self.assertEqual(len(persisted["attempts"]), 2)
        self.assertEqual(persisted["attempts"][-1]["result_source"], "refused")
        self.assertEqual(persisted["outcome"], summary["result"])

    def test_control_attempt_two_deadline_suspends_instead_of_refusing(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        path = str(self.root / "wt-47")
        self.control(
            now="2026-08-19T12:00:00Z", issues=[47],
            tracker=[self.tracker_fact(47)],
            worktrees=[self.worktree_fact(
                47, candidate={"path": path, "state": "absent"})],
        )
        failed = {
            **self.merged_result(47),
            "state": "failed",
            "pr_url": None,
            "merge_sha": None,
            "issue_closed": False,
            "notes": "owner unavailable",
        }
        self.finish(1, failed, issue=47, now="2026-08-19T12:01:00Z")
        retried = self.control(
            now="2026-08-19T12:02:00Z", issues=[47],
            tracker=[self.tracker_fact(47)],
            worktrees=[self.worktree_fact(
                47, recorded={"path": path, "state": "matching_issue_branch"})],
        )
        self.assertEqual(retried["actions"][0]["id"], "47:2:1")

        expired = self.control(
            now="2026-08-19T12:32:00Z", issues=[47],
            tracker=[self.tracker_fact(47)], worktrees=[],
        )
        self.assertEqual(expired["deltas"], [{
            "issue": 47, "attempt": 2, "kind": "expired", "state": "suspended",
        }])
        persisted = self.read_state()["issues"]["47"]["attempts"][-1]
        self.assertEqual(
            (persisted["state"], persisted["blocked_on"],
             persisted["result_source"]),
            ("suspended", "unknown", None),
        )
        self.assertEqual(len(self.read_state()["issues"]["47"]["attempts"]), 2)

    def test_control_tracker_blockers_and_fog_suppress_only_new_work(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        path = str(self.root / "wt-47")
        self.control(now="2026-08-19T12:00:00Z", issues=[47],
                     tracker=[self.tracker_fact(47)],
                     worktrees=[self.worktree_fact(
                         47, candidate={"path": path, "state": "absent"})])
        response = self.control(
            now="2026-08-19T12:01:00Z", issues=[47, 51, 53],
            tracker=[
                self.tracker_fact(47, state="closed"),
                self.tracker_fact(51, open_blockers=[40]),
                self.tracker_fact(53, decision_blockers=[
                    {"issue": 52, "url": "https://github.com/fagenorn/nix-config/issues/52"}
                ]),
            ], worktrees=[],
        )
        self.assertEqual([s["state"] for s in response["summaries"]],
                         ["active", "blocked", "fogged"])
        self.assertEqual([a["kind"] for a in response["actions"]], ["wait"])

    def test_control_requires_verified_worktree_fact_for_an_accepted_action(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        before = self.state_path.read_bytes()
        missing = self.control_raw(now="2026-08-19T12:00:00Z", issues=[47],
                                   tracker=[self.tracker_fact(47)], worktrees=[],
                                   ok=False)
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(self.state_path.read_bytes(), before)
        relative = self.control_raw(
            now="2026-08-19T12:00:00Z", issues=[47],
            tracker=[self.tracker_fact(47)],
            worktrees=[self.worktree_fact(
                47, candidate={"path": "relative", "state": "absent"})], ok=False,
        )
        self.assertNotEqual(relative.returncode, 0)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_init_run_bootstrap_projects_latest_resume_and_retry_identity(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        paths = {i: str(self.root / f"wt-{i}") for i in (47, 51)}
        self.control(
            now="2026-08-19T12:00:00Z", issues=[47, 51], max_parallel=2,
            tracker=[self.tracker_fact(47), self.tracker_fact(51)],
            worktrees=[self.worktree_fact(
                i, candidate={"path": paths[i], "state": "absent"}
            ) for i in (47, 51)],
        )
        resumed = self.control(
            now="2026-08-19T12:01:00Z", issues=[47, 51], max_parallel=2,
            tracker=[self.tracker_fact(47), self.tracker_fact(51)],
            owners=[self.owner_fact(event_id="47-exit", issue=47,
                                    attempt=1, launch=1)],
            worktrees=[self.worktree_fact(47, recorded={
                "path": paths[47], "state": "matching_issue_branch",
            })],
        )
        self.assertEqual(resumed["actions"][0]["id"], "47:1:2")
        after_resume = self.init_run(now="2026-08-19T12:01:00Z")
        self.assertEqual(after_resume["requirements"], [
            {"issue": 47, "attempt": 1, "owner": "47:1",
             "action_id": "47:1:2", "recorded_worktree": paths[47]},
            {"issue": 51, "attempt": 1, "owner": "51:1",
             "action_id": "51:1:1", "recorded_worktree": paths[51]},
        ])

        failed = {**self.merged_result(51), "state": "failed", "pr_url": None,
                  "merge_sha": None, "issue_closed": False, "notes": "harness"}
        self.finish(1, failed, issue=51, now="2026-08-19T12:02:00Z")
        retried = self.control(
            now="2026-08-19T12:03:00Z", issues=[47, 51], max_parallel=2,
            tracker=[self.tracker_fact(47), self.tracker_fact(51)],
            worktrees=[self.worktree_fact(51, recorded={
                "path": paths[51], "state": "matching_issue_branch",
            })],
        )
        self.assertEqual(retried["actions"][0]["id"], "51:2:1")
        after_retry = self.init_run(now="2026-08-19T12:03:00Z")
        self.assertEqual(after_retry["requirements"][1], {
            "issue": 51, "attempt": 2, "owner": "51:2",
            "action_id": "51:2:1", "recorded_worktree": paths[51],
        })

    def test_consumed_candidate_is_only_an_actionless_exact_replay(self):
        self.init_run(now="2026-08-19T12:00:00Z")
        path = str(self.root / "wt-47")
        original = self.control_request(
            now="2026-08-19T12:00:00Z", issues=[47],
            tracker=[self.tracker_fact(47)],
            worktrees=[self.worktree_fact(
                47, candidate={"path": path, "state": "absent"})],
        )
        self.control_raw(request=original)
        advanced = self.state_path.read_bytes()
        exact = json.loads(self.control_raw(request=original).stdout)
        self.assertEqual(exact["deltas"], [])
        self.assertEqual([a["kind"] for a in exact["actions"]], ["wait"])
        self.assertEqual(self.state_path.read_bytes(), advanced)

        wrong_instant = copy.deepcopy(original)
        wrong_instant["now"] = "2026-08-19T12:00:01Z"
        self.assertNotEqual(self.control_raw(request=wrong_instant,
                                             ok=False).returncode, 0)
        wrong_path = self.control_request(
            now="2026-08-19T12:00:00Z", issues=[47, 51],
            tracker=[self.tracker_fact(47), self.tracker_fact(51)],
            worktrees=[self.worktree_fact(
                51, candidate={"path": path, "state": "absent"})],
        )
        self.assertNotEqual(self.control_raw(request=wrong_path,
                                             ok=False).returncode, 0)

        unavailable = copy.deepcopy(original)
        unavailable["owners"] = [self.owner_fact(
            event_id="47-exit", issue=47, attempt=1, launch=1)]
        self.assertNotEqual(self.control_raw(request=unavailable,
                                             ok=False).returncode, 0)
        self.assertEqual(self.state_path.read_bytes(), advanced)

        failed = {**self.merged_result(47), "state": "failed", "pr_url": None,
                  "merge_sha": None, "issue_closed": False, "notes": "harness"}
        self.finish(1, failed, issue=47, now="2026-08-19T12:00:00Z")
        terminal = self.state_path.read_bytes()
        self.assertNotEqual(self.control_raw(request=original, ok=False).returncode, 0)
        self.assertEqual(self.state_path.read_bytes(), terminal)

        current = self.control(
            now="2026-08-19T12:00:00Z", issues=[47],
            tracker=[self.tracker_fact(47)],
            worktrees=[self.worktree_fact(47, recorded={
                "path": path, "state": "matching_issue_branch",
            })],
        )
        self.assertEqual(current["actions"][0]["id"], "47:2:1")

    def test_delayed_notification_recovers_durable_terminal_result(self):
        self.init_run()
        first = self.spawn(issue=14, worktree=self.root / "wt-a")
        result = self.merged_result()
        persisted = self.finish(first["attempt"], result)
        recovered = self.control(
            now="2026-08-13T20:10:00Z",
            issues=[14],
            tracker=[self.tracker_fact(14)],
            worktrees=[self.worktree_fact(14, recorded={
                "path": first["worktree"], "state": "matching_issue_branch",
            })],
        )
        self.assertEqual(persisted, result)
        self.assert_control_response_shape(recovered)
        self.assertEqual(recovered["summaries"][0]["result"], result)
        self.assertEqual(recovered["actions"], [{"id": "finalize", "kind": "finalize"}])

    def test_unavailable_owner_resume_keeps_attempt_and_deadline(self):
        self.init_run()
        worktree = self.root / "parent" / ".." / "wt-a"
        first = self.spawn(issue=14, worktree=worktree)
        started_at = self.read_state()["issues"]["14"]["attempts"][0]["started_at"]
        resumed = self.resume(
            issue=14,
            worktree=self.root / "wt-a",
            now="2026-08-13T20:20:00Z",
            owner_unavailable=True,
        )
        self.assertEqual((resumed["attempt"], resumed["kind"]), (1, "resume"))
        self.assertEqual((resumed["owner"], resumed["id"]), ("14:1", "14:1:2"))
        self.assertEqual(resumed["deadline_at"], first["deadline_at"])

        persisted = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual(persisted["started_at"], started_at)
        self.assertEqual(persisted["issue"], 14)
        self.assertEqual(
            persisted["launches"],
            [
                {
                    "kind": "fresh",
                    "owner": "14:1",
                    "worktree": os.path.abspath(self.root / "wt-a"),
                    "at": DEFAULT_NOW,
                },
                {
                    "kind": "resume",
                    "owner": "14:1",
                    "worktree": os.path.abspath(self.root / "wt-a"),
                    "at": "2026-08-13T20:20:00Z",
                },
            ],
        )

    def test_only_one_fresh_retry_and_refusal_links_prior_attempts(self):
        self.init_run()
        first = self.spawn(issue=14, worktree=self.root / "wt-a")
        self.fail_owner(issue=14, attempt=1, now="2026-08-13T20:01:00Z")
        second = self.retry(
            issue=14, worktree=self.root / "wt-b", now="2026-08-13T20:10:00Z"
        )
        self.fail_owner(issue=14, attempt=2, now="2026-08-13T20:15:00Z")
        refused = self.control(
            now="2026-08-13T20:20:00Z",
            issues=[14],
            tracker=[self.tracker_fact(14)],
            worktrees=[self.worktree_fact(14, recorded={
                "path": second["worktree"], "state": "matching_issue_branch",
            })],
        )
        state = self.read_state()
        self.assertEqual(second["attempt"], 2)
        self.assertEqual(state["issues"]["14"]["attempts"][1]["prior_attempt"], 1)
        self.assertEqual(first["issue"], 14)
        self.assertEqual(second["issue"], 14)
        self.assertEqual(state["issues"]["14"]["outcome"]["state"], "failed")
        self.assertEqual(os.path.abspath(self.root / "wt-a"), first["worktree"])
        self.assertIn(
            os.path.abspath(self.root / "wt-a"),
            state["issues"]["14"]["attempts"][0]["result"]["notes"],
        )
        self.assertIn(
            os.path.abspath(self.root / "wt-b"),
            state["issues"]["14"]["outcome"]["notes"],
        )
        self.assert_control_response_shape(refused)
        self.assertEqual(refused["deltas"], [{
            "issue": 14, "attempt": 2, "kind": "retry_refused", "state": "failed",
        }])

    def test_owner_death_expiry_reports_a_suspended_summary_with_its_worktree(self):
        """A silent owner leaves resumable work, not a verdict, in the projection."""
        self.init_run()
        worktree = self.root / "silent-owner"
        launched = self.spawn(issue=14, worktree=worktree, budget_minutes=10)
        reconciled = self.expire(
            issue=14, worktree=worktree, now="2026-08-13T20:10:00Z"
        )
        self.assert_control_response_shape(reconciled)
        summary = reconciled["summaries"][0]
        self.assertEqual(launched["deadline_at"], "2026-08-13T20:10:00Z")
        self.assertEqual(summary["state"], "suspended")
        self.assertEqual(summary["worktree"], os.path.abspath(worktree))
        self.assertIsNone(summary["result"])
        self.assertEqual(
            self.read_state()["issues"]["14"]["attempts"][0]["worktree"],
            os.path.abspath(worktree),
        )

    def test_owner_unavailable_after_the_deadline_is_superseded_by_expiry(self):
        """A stalled verdict read just before the deadline still recovers (#310 D18)."""
        self.init_run()
        worktree = self.root / "stalled-owner"
        self.spawn(issue=14, worktree=worktree, budget_minutes=10)
        attempt = self.read_state()["issues"]["14"]["attempts"][-1]
        response = self.control(
            now="2026-08-13T20:10:00Z",
            issues=[14],
            tracker=[self.tracker_fact(14)],
            owners=[self.owner_fact(
                event_id="14-owner-unavailable", issue=14,
                attempt=attempt["attempt"], launch=len(attempt["launches"]),
            )],
            worktrees=[self.worktree_fact(14, recorded={
                "path": attempt["worktree"], "state": "matching_issue_branch",
            })],
            max_parallel=100,
        )
        self.assert_control_response_shape(response)
        self.assertEqual(
            [(d["kind"], d["attempt"]) for d in response["deltas"]],
            [("expired", 1), ("resumed", 1)],
        )

    def test_owner_failed_retry_and_refusal_stamp_their_result_source(self):
        self.init_run()
        self.spawn(issue=14, worktree=self.root / "wt-a")
        self.fail_owner(issue=14, attempt=1, now="2026-08-13T20:05:00Z")
        retry = self.retry(
            issue=14, worktree=self.root / "wt-b", now="2026-08-13T20:10:00Z"
        )
        attempts = self.read_state()["issues"]["14"]["attempts"]
        self.assertEqual(attempts[0]["state"], "failed")
        self.assertEqual(attempts[0]["result_source"], "owner")
        self.assertEqual(attempts[0]["finished_at"], "2026-08-13T20:05:00Z")
        self.assertIsNone(attempts[1]["finished_at"])
        self.assertIsNone(attempts[1]["result_source"])

        self.fail_owner(issue=14, attempt=2, now="2026-08-13T20:15:00Z")
        refused = self.control(
            now="2026-08-13T20:20:00Z",
            issues=[14],
            tracker=[self.tracker_fact(14)],
            worktrees=[self.worktree_fact(14, recorded={
                "path": retry["worktree"], "state": "matching_issue_branch",
            })],
        )
        self.assert_control_response_shape(refused)
        attempts = self.read_state()["issues"]["14"]["attempts"]
        self.assertEqual(attempts[1]["state"], "failed")
        self.assertEqual(attempts[1]["result_source"], "refused")
        self.assertEqual(attempts[1]["finished_at"], "2026-08-13T20:20:00Z")

    def test_late_merged_finish_preserves_the_owner_result(self):
        self.init_run()
        worktree = self.root / "late-owner"
        launched = self.spawn(issue=14, worktree=worktree, budget_minutes=10)
        reported = self.merged_result()
        stdout_json = self.finish(
            launched["attempt"],
            reported,
            now="2026-08-13T20:10:00Z",
        )
        state = self.read_state()
        attempt = state["issues"]["14"]["attempts"][0]
        outcome = state["issues"]["14"]["outcome"]
        self.assertEqual(attempt["state"], "merged")
        self.assertEqual(attempt["result"]["state"], "merged")
        self.assertEqual(attempt["result"]["pr_url"], reported["pr_url"])
        self.assertEqual(attempt["result"]["merge_sha"], reported["merge_sha"])
        self.assertIs(attempt["result"]["issue_closed"], True)
        self.assertEqual(attempt["result"]["notes"], "")
        self.assertEqual(attempt["finished_at"], "2026-08-13T20:10:00Z")
        self.assertGreaterEqual(attempt["finished_at"], attempt["deadline_at"])
        self.assertEqual(attempt["result_source"], "owner")
        self.assertEqual(outcome, attempt["result"])
        self.assertEqual(stdout_json, attempt["result"])

    def test_legacy_expiry_record_stays_provisional_until_the_owner_reports(self):
        self.init_run()
        worktree = self.root / "wt-a"
        self.spawn(issue=14, worktree=worktree, budget_minutes=10)
        self.legacy_expiry_record(
            issue=14, now="2026-08-13T20:10:00Z", prior_schema=True
        )
        attempt = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual(attempt["state"], "stopped")
        self.assertEqual(attempt["result_source"], "expiry")

        merged = {
            **self.merged_result(),
            "notes": "merged after the deadline",
        }
        stdout_json = self.finish(1, merged, now="2026-08-13T20:20:00Z")
        state = self.read_state()
        attempt = state["issues"]["14"]["attempts"][0]
        self.assertEqual(state["schema_version"], 7)
        self.assertIsNone(attempt["blocked_on"])
        self.assertEqual(attempt["stalled_resumes"], 0)
        self.assertEqual(attempt["state"], "merged")
        self.assertEqual(attempt["result_source"], "owner")
        self.assertEqual(attempt["finished_at"], "2026-08-13T20:20:00Z")
        self.assertEqual(attempt["result"]["notes"], "merged after the deadline")
        self.assertEqual(state["issues"]["14"]["outcome"], attempt["result"])
        self.assertEqual(stdout_json, attempt["result"])

        before = self.state_path.read_bytes()
        other = {
            **self.merged_result(),
            "state": "failed",
            "pr_url": None,
            "merge_sha": None,
            "issue_closed": False,
            "notes": "conflicting",
        }
        rejected = self.finish(1, other, now="2026-08-13T20:30:00Z", ok=False)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("conflicting terminal result", rejected.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_expired_older_attempt_cannot_supersede_after_a_fresh_retry(self):
        self.init_run()
        worktree = self.root / "wt-a"
        self.spawn(issue=14, worktree=worktree, budget_minutes=10)
        self.legacy_expiry_record(issue=14, now="2026-08-13T20:10:00Z")
        self.retry(issue=14, worktree=worktree, now="2026-08-13T20:15:00Z")
        before = self.state_path.read_bytes()
        rejected = self.finish(
            1, self.merged_result(), now="2026-08-13T20:20:00Z", ok=False
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("conflicting terminal result", rejected.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_refused_third_attempt_result_is_not_supersedable(self):
        self.init_run()
        self.spawn(issue=14, worktree=self.root / "wt-a")
        self.fail_owner(issue=14, attempt=1, now="2026-08-13T20:05:00Z")
        retry = self.retry(
            issue=14, worktree=self.root / "wt-b", now="2026-08-13T20:10:00Z"
        )
        self.fail_owner(issue=14, attempt=2, now="2026-08-13T20:15:00Z")
        refused = self.control(
            now="2026-08-13T20:20:00Z",
            issues=[14],
            tracker=[self.tracker_fact(14)],
            worktrees=[self.worktree_fact(14, recorded={
                "path": retry["worktree"], "state": "matching_issue_branch",
            })],
        )
        self.assertEqual(refused["deltas"][0]["kind"], "retry_refused")
        before = self.state_path.read_bytes()
        rejected = self.finish(
            2, self.merged_result(), now="2026-08-13T20:25:00Z", ok=False
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("conflicting terminal result", rejected.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_owner_report_supersedes_the_stalled_synthetic_stop(self):
        self.init_run()
        worktree = self.root / "wt-stalled"
        self.spawn(issue=14, worktree=worktree, budget_minutes=10)
        for index in range(3):
            self.suspend(
                issue=14, attempt=1, blocked_on="usage_limit",
                now=f"2026-08-13T20:0{2 * index + 1}:00Z",
            )
            self.resume(
                issue=14, worktree=worktree,
                now=f"2026-08-13T20:0{2 * index + 2}:00Z",
            )
        self.suspend(
            issue=14, attempt=1, blocked_on="usage_limit",
            now="2026-08-13T20:08:00Z",
        )
        stalled = self.read_state()["issues"]["14"]["attempts"][-1]
        self.assertEqual(stalled["result_source"], "stalled")

        reported = {**self.merged_result(), "notes": "shipped after the stall"}
        stdout_json = self.finish(1, reported, now="2026-08-13T20:30:00Z")
        state = self.read_state()
        attempt = state["issues"]["14"]["attempts"][-1]
        self.assertEqual(attempt["state"], "merged")
        self.assertEqual(attempt["result_source"], "owner")
        self.assertEqual(attempt["finished_at"], "2026-08-13T20:30:00Z")
        self.assertEqual(attempt["result"]["notes"], "shipped after the stall")
        self.assertEqual(state["issues"]["14"]["outcome"], attempt["result"])
        self.assertEqual(stdout_json, attempt["result"])

        before = self.state_path.read_bytes()
        rejected = self.finish(
            1, {**self.merged_result(), "notes": "second owner report"},
            now="2026-08-13T20:35:00Z", ok=False,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn(
            "conflicting terminal result for issue 14 attempt 1", rejected.stderr
        )
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_finish_rejects_time_before_last_progress(self):
        self.init_run()
        self.spawn(issue=14, worktree=self.root / "wt-a")
        self.progress(issue=14, attempt=1, phase=3, now="2026-08-13T20:05:00Z")
        before = self.state_path.read_bytes()
        rejected = self.finish(
            1, self.merged_result(), now="2026-08-13T20:02:00Z", ok=False
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("finish time must not move backward", rejected.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_handed_off_finish_rejects_without_changing_state(self):
        self.init_run()
        self.spawn(issue=14, worktree=self.root / "wt-a")
        handoff_path = self.write_handoff(14)
        handed_off = self.progress(
            turn_count=118,
            context_tokens=20000,
            handoff_path=handoff_path,
        )
        self.assertEqual(handed_off["handoff_path"], str(handoff_path))
        self.assertEqual(self.read_state()["issues"]["14"]["attempts"][0]["state"], "handed_off")
        before = self.state_path.read_bytes()
        rejected = self.finish(1, self.merged_result(), ok=False)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("active attempt", rejected.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_legacy_expiry_record_can_use_the_single_fresh_retry(self):
        self.init_run()
        worktree = self.root / "silent-owner"
        self.spawn(issue=14, worktree=worktree, budget_minutes=10)
        self.legacy_expiry_record(issue=14, now="2026-08-13T20:10:00Z")
        retried = self.retry(
            issue=14, worktree=self.root / "retry-owner",
            now="2026-08-13T20:11:00Z",
        )
        self.assertEqual(retried["attempt"], 2)
        self.assertEqual(
            self.read_state()["issues"]["14"]["attempts"][1]["prior_attempt"], 1
        )
        state = self.read_state()["issues"]["14"]
        self.assertIsNone(state["outcome"])
        self.assertEqual(state["attempts"][0]["state"], "stopped")

    def test_backward_control_clock_cannot_corrupt_the_prior_attempt(self):
        self.init_run(now="2026-08-13T19:00:00Z")
        first_worktree = self.root / "wt-a"
        self.spawn(issue=14, worktree=first_worktree, budget_minutes=30)
        first_started = self.read_state()["issues"]["14"]["attempts"][0]["started_at"]
        self.assertEqual(first_started, DEFAULT_NOW)

        before = self.state_path.read_bytes()
        refused = self.control_raw(
            now="2026-08-13T19:30:00Z",
            issues=[14],
            tracker=[self.tracker_fact(14)],
            worktrees=[self.worktree_fact(14, candidate={
                "path": str(self.root / "wt-b"), "state": "absent",
            })],
            max_parallel=100,
            attempt_budget_minutes=30,
            ok=False,
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(self.state_path.read_bytes(), before)

        self.expire(issue=14, worktree=first_worktree, now="2026-08-13T20:31:00Z")
        suspended = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual(suspended["state"], "suspended")
        self.assertIsNone(suspended["finished_at"])

        self.legacy_expiry_record(issue=14, now="2026-08-13T20:31:00Z")
        stopped = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual(stopped["state"], "stopped")
        self.assertEqual(stopped["result_source"], "expiry")
        self.assertGreaterEqual(stopped["finished_at"], stopped["started_at"])

        retried = self.retry(
            issue=14, worktree=self.root / "wt-b",
            now="2026-08-13T20:32:00Z", budget_minutes=30,
        )
        self.assertEqual(retried["attempt"], 2)
        rejected = self.progress(
            issue=14, attempt=1, now="2026-08-13T20:33:00Z", ok=False
        )
        self.assertNotIn("invalid attempt finish time order", rejected.stderr)
        again = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertGreaterEqual(again["finished_at"], again["started_at"])

    def test_fresh_retry_may_reuse_the_prior_attempt_worktree(self):
        self.init_run()
        shared = self.root / "wt-issue-14"
        resolved = os.path.abspath(shared)
        self.spawn(issue=14, worktree=shared, budget_minutes=10)
        self.fail_owner(issue=14, attempt=1, now="2026-08-13T20:05:00Z")
        first = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual(first["state"], "failed")
        self.assertEqual(first["result_source"], "owner")
        self.assertEqual(first["worktree"], resolved)

        retried = self.retry(issue=14, worktree=shared, now="2026-08-13T20:15:00Z")
        self.assertEqual(retried["attempt"], 2)
        self.assertEqual(retried["worktree"], resolved)
        self.assertEqual(retried["kind"], "retry")
        attempts = self.read_state()["issues"]["14"]["attempts"]
        self.assertEqual(attempts[1]["prior_attempt"], 1)
        self.assertEqual(attempts[1]["state"], "active")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[1]["worktree"], attempts[0]["worktree"])

        blocked = {
            **self.merged_result(),
            "state": "stopped",
            "pr_url": None,
            "merge_sha": None,
            "issue_closed": False,
            "notes": "blocked",
        }
        self.finish(2, blocked, now="2026-08-13T20:30:00Z")
        before = self.state_path.read_bytes()
        resumed = self.control(
            now="2026-08-13T20:40:00Z",
            issues=[14],
            tracker=[self.tracker_fact(14)],
            worktrees=[self.worktree_fact(14, recorded={
                "path": resolved, "state": "matching_issue_branch",
            })],
        )
        self.assert_control_response_shape(resumed)
        self.assertEqual(resumed["summaries"][0]["state"], "stopped")
        self.assertEqual(resumed["actions"], [{"id": "finalize", "kind": "finalize"}])
        self.assertEqual(len(self.read_state()["issues"]["14"]["attempts"]), 2)
        self.assert_controller_finalized(before, now="2026-08-13T20:40:00Z")  # per D20

    def test_progress_action_precedence_and_complete_inputs_are_persisted(self):
        self.init_run()
        cases = [
            (
                {
                    "remainder_self_contained": True,
                    "turn_count": 119,
                    "context_tokens": 149000,
                },
                "handoff",
            ),
            (
                {
                    "next_needs_context": False,
                    "artifacts_sufficient": True,
                    "turn_count": 119,
                    "context_tokens": 149000,
                },
                "fresh_start",
            ),
            (
                {
                    "next_needs_context": True,
                    "turn_count": 10,
                    "context_tokens": 20000,
                },
                "continue",
            ),
            (
                {
                    "next_needs_context": True,
                    "turn_count": 118,
                    "context_tokens": 20000,
                },
                "handoff",
            ),
            (
                {
                    "next_needs_context": True,
                    "turn_count": 10,
                    "context_tokens": 140000,
                },
                "handoff",
            ),
            (
                {
                    "next_needs_context": True,
                    "turn_count": None,
                    "context_tokens": None,
                },
                "continue",
            ),
        ]
        for index, (overrides, expected_action) in enumerate(cases, start=1):
            issue = 20 + index
            self.spawn(issue=issue, worktree=self.root / f"wt-{issue}")
            result = self.progress(issue=issue, phase=index, **overrides)
            persisted = self.read_state()["issues"][str(issue)]["attempts"][0]
            expected_inputs = {
                "turn_count": overrides.get("turn_count", 10),
                "context_tokens": overrides.get("context_tokens", 20000),
                "turn_ceiling": 120,
                "context_ceiling": 150000,
                "turn_headroom": 2,
                "context_headroom": 10000,
                "next_needs_context": overrides.get("next_needs_context", True),
                "artifacts_sufficient": overrides.get("artifacts_sufficient", False),
                "remainder_self_contained": overrides.get(
                    "remainder_self_contained", False
                ),
            }
            with self.subTest(expected_action=expected_action):
                self.assertEqual(result["action"], expected_action)
                self.assertEqual(persisted["phase_action"], expected_action)
                self.assertEqual(persisted["phase"], index)
                self.assertEqual(persisted["last_progress_at"], DEFAULT_NOW)
                self.assertEqual(persisted["phase_inputs"], expected_inputs)

    def test_direct_progress_uses_complete_artifact_first_precedence(self):
        cases = (
            ({"turn_count": None, "context_tokens": None,
              "remainder_self_contained": True}, "delegate"),
            ({"turn_count": 118, "context_tokens": 20000,
              "remainder_self_contained": True}, "delegate"),
            ({"turn_count": 118, "context_tokens": 140000,
              "next_needs_context": False, "artifacts_sufficient": True,
              "remainder_self_contained": True}, "delegate"),
            ({"turn_count": None, "context_tokens": None,
              "next_needs_context": False, "artifacts_sufficient": True},
             "fresh_start"),
            ({"turn_count": 118, "context_tokens": 140000,
              "next_needs_context": False, "artifacts_sufficient": True},
             "fresh_start"),
            ({"turn_count": None, "context_tokens": 140000,
              "next_needs_context": True}, "handoff"),
            ({"turn_count": None, "context_tokens": None,
              "next_needs_context": True}, "continue"),
            ({"turn_count": None, "context_tokens": None,
              "next_needs_context": False, "artifacts_sufficient": False},
             "handoff"),
            ({"turn_count": 10, "context_tokens": 20000,
              "next_needs_context": True}, "continue"),
        )
        for offset, (overrides, expected) in enumerate(cases, start=80):
            with self.subTest(issue=offset, expected=expected):
                owner = self.acquire_direct(issue=offset)
                self.run_id = owner["run_id"]
                result = self.progress(
                    issue=offset, phase=1, now="2026-08-20T10:05:00Z",
                    **overrides,
                )
                attempt = json.loads(
                    self.direct_state_path(owner["run_id"]).read_text()
                )["issues"][str(offset)]["attempts"][0]
                self.assertEqual(result["action"], expected)
                self.assertEqual(attempt["phase_action"], expected)
                self.assertEqual(attempt["phase_inputs"]["remainder_self_contained"],
                                 overrides.get("remainder_self_contained", False))
                self.assertEqual(attempt["deadline_at"], owner["deadline_at"])

    def test_non_direct_phase_order_and_ledger_bytes_remain_exact(self):
        for run_id in ("dispatcher-owned", "durable-interactive"):
            with self.subTest(run_id=run_id):
                self.run_id = run_id
                self.init_run()
                worktree = os.path.abspath(self.root / f"{run_id}-worktree")
                self.spawn(issue=14, worktree=worktree)
                delivery = copy.deepcopy(self.read_state()["issues"]["14"]["delivery"])
                result = self.progress(
                    issue=14, phase=1, turn_count=118, context_tokens=20000,
                    remainder_self_contained=True,
                )
                expected_inputs = {
                    "turn_count": 118, "context_tokens": 20000,
                    "turn_ceiling": 120, "context_ceiling": 150000,
                    "turn_headroom": 2, "context_headroom": 10000,
                    "next_needs_context": True, "artifacts_sufficient": False,
                    "remainder_self_contained": True,
                }
                expected_attempt = {
                    "issue": 14, "attempt": 1, "owner": "14:1",
                    "worktree": worktree, "started_at": DEFAULT_NOW,
                    "deadline_at": "2026-08-13T20:30:00Z", "state": "active",
                    "launch_kind": "fresh", "launches": [{
                        "kind": "fresh", "owner": "14:1",
                        "worktree": worktree, "at": DEFAULT_NOW,
                    }],
                    "prior_attempt": None, "result": None, "finished_at": None,
                    "result_source": None, "handoff_path": None, "phase": 1,
                    "last_progress_at": DEFAULT_NOW, "phase_action": "handoff",
                    "phase_inputs": expected_inputs,
                    "blocked_on": None, "suspend_phase": None,
                    "stalled_resumes": 0, "progress_marker": None,
                    "lane": None, "lane_budget_minutes": None, "lane_history": [],
                }
                expected_state = {
                    "schema_version": 7, "run_id": run_id, "workers": [],
                    "created_at": DEFAULT_NOW, "updated_at": DEFAULT_NOW,
                    "prior_run": None, "admission": self.spawned_admission(14),
                    "issues": {"14": {
                        "issue": 14, "attempts": [expected_attempt],
                        "outcome": None, "delivery": delivery,
                        "delivery_remainders": [],
                    }},
                }
                expected_bytes = (json.dumps(
                    expected_state, sort_keys=True, separators=(",", ":")
                ) + "\n").encode()
                self.assertEqual(result, {"interface_version": 2, "kind": "phase_gate", "run_id": run_id, "issue": 14, "custody": {"kind": "implementation", "attempt": 1, "launch": 1, "action_id": "14:1:1"}, "action": "handoff", "handoff_path": None})
                self.assertEqual(self.state_path.read_bytes(), expected_bytes)

    def test_zero_sequence_direct_shaped_dispatcher_keeps_non_direct_progress_and_reopen_bytes(self):
        self.run_id = "direct-14-000000"
        self.init_run()
        worktree = os.path.abspath(self.root / "zero-sequence-worktree")
        self.spawn(issue=14, worktree=worktree)
        delivery = copy.deepcopy(self.read_state()["issues"]["14"]["delivery"])
        result = self.progress(
            issue=14, phase=1, turn_count=118, context_tokens=20000,
            remainder_self_contained=True,
        )
        expected_inputs = {
            "turn_count": 118, "context_tokens": 20000,
            "turn_ceiling": 120, "context_ceiling": 150000,
            "turn_headroom": 2, "context_headroom": 10000,
            "next_needs_context": True, "artifacts_sufficient": False,
            "remainder_self_contained": True,
        }
        expected_attempt = {
            "issue": 14, "attempt": 1, "owner": "14:1",
            "worktree": worktree, "started_at": DEFAULT_NOW,
            "deadline_at": "2026-08-13T20:30:00Z", "state": "active",
            "launch_kind": "fresh", "launches": [{
                "kind": "fresh", "owner": "14:1",
                "worktree": worktree, "at": DEFAULT_NOW,
            }],
            "prior_attempt": None, "result": None, "finished_at": None,
            "result_source": None, "handoff_path": None, "phase": 1,
            "last_progress_at": DEFAULT_NOW, "phase_action": "handoff",
            "phase_inputs": expected_inputs,
            "blocked_on": None, "suspend_phase": None, "stalled_resumes": 0,
            "progress_marker": None,
            "lane": None, "lane_budget_minutes": None, "lane_history": [],
        }
        expected_state = {
            "schema_version": 7, "run_id": self.run_id, "workers": [],
            "created_at": DEFAULT_NOW, "updated_at": DEFAULT_NOW,
            "prior_run": None, "admission": self.spawned_admission(14),
            "issues": {"14": {
                "issue": 14, "attempts": [expected_attempt], "outcome": None,
                "delivery": delivery, "delivery_remainders": [],
            }},
        }
        expected_bytes = (json.dumps(
            expected_state, sort_keys=True, separators=(",", ":")
        ) + "\n").encode()
        self.assertEqual(result, {"interface_version": 2, "kind": "phase_gate", "run_id": "direct-14-000000", "issue": 14, "custody": {"kind": "implementation", "attempt": 1, "launch": 1, "action_id": "14:1:1"}, "action": "handoff", "handoff_path": None})
        self.assertEqual(self.state_path.read_bytes(), expected_bytes)

        reopened = self.control_raw(
            now=DEFAULT_NOW, issues=[14], tracker=[self.tracker_fact(14)],
            worktrees=[], max_parallel=1,
        )
        self.assertEqual(reopened.returncode, 0)
        self.assertEqual(self.state_path.read_bytes(), expected_bytes)

    def test_phase_action_validation_is_bound_to_run_identity(self):
        self.run_id = "dispatcher-corruption"
        self.init_run()
        self.spawn(issue=14, worktree=self.root / "dispatcher-worktree")
        self.progress(
            issue=14, phase=1, turn_count=118, context_tokens=20000,
            remainder_self_contained=True,
        )
        state = self.read_state()
        state["issues"]["14"]["attempts"][0]["phase_action"] = "delegate"
        self.state_path.write_text(json.dumps(state), encoding="utf-8")
        before = self.state_path.read_bytes()
        rejected = self.control_raw(
            now=DEFAULT_NOW, issues=[14], tracker=[self.tracker_fact(14)],
            worktrees=[], max_parallel=1, ok=False,
        )
        self.assertIn("phase action does not match persisted inputs", rejected.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

        owner = self.acquire_direct(issue=73)
        self.run_id = owner["run_id"]
        self.progress(
            issue=73, phase=1, now="2026-08-20T10:05:00Z",
            turn_count=118, context_tokens=20000,
            remainder_self_contained=True,
        )
        direct_path = self.direct_state_path(owner["run_id"])
        state = json.loads(direct_path.read_text())
        state["issues"]["73"]["attempts"][0]["phase_action"] = "handoff"
        direct_path.write_text(json.dumps(state), encoding="utf-8")
        before = direct_path.read_bytes()
        rejected = self.direct_owner_raw(
            issue=73, now="2026-08-20T10:06:00Z", ok=False,
        )
        self.assertIn("phase action does not match persisted inputs", rejected.stderr)
        self.assertEqual(direct_path.read_bytes(), before)

    def test_delegate_requires_measured_usage_below_both_ceilings(self):
        self.init_run()
        self.spawn(issue=14, worktree=self.root / "wt-a")
        delegated = self.progress(
            issue=14,
            attempt=1,
            phase=3,
            now="2026-08-13T20:05:00Z",
            turn_count=10,
            context_tokens=20000,
            next_needs_context=True,
            artifacts_sufficient=False,
            remainder_self_contained=True,
        )
        self.assertEqual(delegated["action"], "delegate")

        unknown_usage = self.progress(
            issue=14,
            attempt=1,
            phase=4,
            now="2026-08-13T20:10:00Z",
            turn_count=None,
            context_tokens=None,
            next_needs_context=True,
            artifacts_sufficient=False,
            remainder_self_contained=True,
        )
        self.assertEqual(unknown_usage["action"], "continue")

        at_context_ceiling = self.progress(
            issue=14,
            attempt=1,
            phase=5,
            now="2026-08-13T20:15:00Z",
            turn_count=10,
            context_tokens=140000,
            next_needs_context=True,
            artifacts_sufficient=False,
            remainder_self_contained=True,
        )
        self.assertEqual(at_context_ceiling["action"], "handoff")

        at_turn_ceiling = self.progress(
            issue=14,
            attempt=1,
            phase=6,
            now="2026-08-13T20:20:00Z",
            turn_count=118,
            context_tokens=20000,
            next_needs_context=True,
            artifacts_sufficient=False,
            remainder_self_contained=True,
        )
        self.assertEqual(at_turn_ceiling["action"], "handoff")

    def test_unknown_usage_continues_a_dispatched_run_across_phase_gates(self):
        """A harness with no context-token count must not pin a run to handoff.

        Omitting --context-tokens is the truthful report on a harness that exposes
        no authoritative count. Treating that as a budget signal handed every
        dispatched owner off at its first phase gate.
        """
        self.init_run()
        self.spawn(issue=14, worktree=self.root / "wt-a")
        for phase in (0, 1, 2):
            decision = self.progress(
                issue=14,
                attempt=1,
                phase=phase,
                now=f"2026-08-13T20:0{phase}:00Z",
                turn_count=None,
                context_tokens=None,
                next_needs_context=True,
                artifacts_sufficient=False,
                remainder_self_contained=False,
            )
            with self.subTest(phase=phase):
                self.assertEqual(
                    (decision["action"], self.read_state()["issues"]["14"]["attempts"][0]["state"]),
                    ("continue", "active"),
                )

        # A measured near-ceiling count is still a handoff.
        at_ceiling = self.progress(
            issue=14, attempt=1, phase=3, now="2026-08-13T20:03:00Z",
            turn_count=118, context_tokens=None, next_needs_context=True,
            artifacts_sufficient=False, remainder_self_contained=False,
        )
        self.assertEqual(at_ceiling["action"], "handoff")

    def test_durable_handoff_requires_safe_file_and_resumes_same_attempt(self):
        self.init_run()
        worktree = self.root / "wt-a"
        launched = self.spawn(issue=14, worktree=worktree)
        decision = self.progress(turn_count=118, context_tokens=20000)
        self.assertEqual(
            (decision["action"], self.read_state()["issues"]["14"]["attempts"][0]["state"]), ("handoff", "active")
        )
        self.assertIsNone(decision["handoff_path"])

        nonexistent = self.workflows_dir / self.run_id / "handoffs" / "missing.md"
        before = self.state_path.read_bytes()
        rejected = self.progress(
            turn_count=118, context_tokens=20000, handoff_path=nonexistent, ok=False
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(self.state_path.read_bytes(), before)

        outside = self.root / "outside-handoff.md"
        outside.write_text("outside\n", encoding="utf-8")
        rejected = self.progress(
            turn_count=118, context_tokens=20000, handoff_path=outside, ok=False
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(self.state_path.read_bytes(), before)

        handoff_path = self.write_handoff(14)
        finalized = self.progress(
            turn_count=118, context_tokens=20000, handoff_path=handoff_path
        )
        self.assertEqual(self.read_state()["issues"]["14"]["attempts"][0]["state"], "handed_off")
        self.assertEqual(finalized["handoff_path"], str(handoff_path))

        before = self.state_path.read_bytes()
        rejected = self.control_raw(
            now="2026-08-13T20:05:00Z",
            issues=[14],
            tracker=[self.tracker_fact(14)],
            worktrees=[self.worktree_fact(14, recorded={
                "path": str(self.root / "wrong-worktree"),
                "state": "matching_issue_branch",
            })],
            max_parallel=100,
            ok=False,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(self.state_path.read_bytes(), before)

        resumed = self.resume(
            issue=14, worktree=worktree, now="2026-08-13T20:05:00Z"
        )
        self.assertEqual((resumed["attempt"], resumed["kind"]), (1, "resume"))
        self.assertEqual((resumed["owner"], resumed["id"]), ("14:1", "14:1:2"))
        self.assertEqual(resumed["deadline_at"], launched["deadline_at"])
        self.assertEqual(
            len(self.read_state()["issues"]["14"]["attempts"][0]["launches"]), 2
        )
        continued = self.progress(
            phase=2,
            now="2026-08-13T20:06:00Z",
            turn_count=10,
            context_tokens=20000,
        )
        self.assertEqual((continued["action"], continued["handoff_path"], continued["custody"]["action_id"]), ("continue", None, "14:1:2"))
        attempt = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual((attempt["state"], attempt["handoff_path"]), ("active", str(handoff_path)))

    def test_control_revalidates_handoff_before_resume(self):
        self.init_run()
        worktree = self.root / "wt-a"
        self.spawn(issue=14, worktree=worktree)
        handoff_path = self.write_handoff(14)
        self.progress(
            turn_count=118, context_tokens=20000, handoff_path=handoff_path
        )
        before = self.state_path.read_bytes()
        handoff_path.unlink()
        rejected = self.control_raw(
            now="2026-08-13T20:05:00Z",
            issues=[14],
            tracker=[self.tracker_fact(14)],
            worktrees=[self.worktree_fact(14, recorded={
                "path": str(worktree), "state": "matching_issue_branch",
            })],
            max_parallel=100,
            ok=False,
        )
        self.assertIn("handoff path does not exist", rejected.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_late_handoff_legacy_expiry_permits_fresh_retry(self):
        self.init_run()
        worktree = self.root / "wt-a"
        self.spawn(issue=14, worktree=worktree)
        handoff_path = self.write_handoff(14)
        self.progress(turn_count=118, context_tokens=20000, handoff_path=handoff_path)

        self.legacy_expiry_record(issue=14, now="2026-08-13T20:31:00Z")
        persisted = self.read_state()["issues"]["14"]
        self.assertEqual(persisted["outcome"]["state"], "stopped")
        self.assertIn(os.path.abspath(worktree), persisted["outcome"]["notes"])
        self.assertEqual(persisted["attempts"][0]["state"], "stopped")
        self.assertEqual(len(persisted["attempts"][0]["launches"]), 1)

        retried = self.retry(
            issue=14, worktree=self.root / "wt-b",
            now="2026-08-13T20:32:00Z",
        )
        self.assertEqual((retried["attempt"], retried["kind"]), (2, "retry"))
        self.assertEqual(
            self.read_state()["issues"]["14"]["attempts"][1]["prior_attempt"], 1
        )

    def test_control_suspends_unresumed_handoff_without_losing_it(self):
        self.init_run()
        worktree = self.root / "wt-a"
        self.spawn(issue=14, worktree=worktree)
        handoff_path = self.write_handoff(14)
        self.progress(turn_count=118, context_tokens=20000, handoff_path=handoff_path)

        reconciled = self.expire(
            issue=14, worktree=worktree, now="2026-08-13T20:31:00Z"
        )
        self.assert_control_response_shape(reconciled)
        self.assertEqual(reconciled["deltas"], [{
            "issue": 14, "attempt": 1, "kind": "expired", "state": "suspended",
        }])
        persisted = self.read_state()["issues"]["14"]
        attempt = persisted["attempts"][0]
        self.assertEqual(attempt["state"], "suspended")
        self.assertEqual(attempt["blocked_on"], "unknown")
        self.assertEqual(attempt["handoff_path"], str(handoff_path))
        self.assertEqual(attempt["phase_action"], "handoff")
        self.assertIsNone(persisted["outcome"])
        self.assertTrue(handoff_path.is_file())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_handoff_symlink_escape_is_rejected_without_state_change(self):
        self.init_run()
        self.spawn(issue=14, worktree=self.root / "wt-a")
        handoffs = self.workflows_dir / self.run_id / "handoffs"
        handoffs.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        external = outside / "handoff.md"
        external.write_text("external\n", encoding="utf-8")
        (handoffs / "escape").symlink_to(outside, target_is_directory=True)
        before = self.state_path.read_bytes()
        rejected = self.progress(
            turn_count=118,
            context_tokens=20000,
            handoff_path=handoffs / "escape" / "handoff.md",
            ok=False,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(external.read_text(encoding="utf-8"), "external\n")

    def test_progress_rejects_threshold_continue_invalid_inputs_and_transitions(self):
        self.init_run()
        self.spawn(issue=14, worktree=self.root / "wt-a")
        at_turn_threshold = self.progress(turn_count=118, context_tokens=20000)
        self.assertEqual(at_turn_threshold["action"], "handoff")
        at_context_threshold = self.progress(
            phase=2, turn_count=10, context_tokens=140000
        )
        self.assertEqual(at_context_threshold["action"], "handoff")

        for args in (
            ("--next-needs-context", "yes"),
            ("--turn-count", "-1"),
            ("--turn-headroom", "120"),
        ):
            with self.subTest(args=args):
                command = [
                    "progress",
                    "--repo-root",
                    self.root,
                    "--run-id",
                    self.run_id,
                    "--issue",
                    14,
                    "--attempt",
                    1,
                    "--phase",
                    3,
                    "--now",
                    DEFAULT_NOW,
                    "--turn-ceiling",
                    120,
                    "--context-ceiling",
                    150000,
                    "--turn-headroom",
                    2,
                    "--context-headroom",
                    10000,
                    "--next-needs-context",
                    "true",
                    "--artifacts-sufficient",
                    "false",
                    "--remainder-self-contained",
                    "false",
                    *args,
                ]
                before = self.state_path.read_bytes()
                rejected = self.run_cli(*command, ok=False)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(self.state_path.read_bytes(), before)

        backward = self.progress(phase=1, ok=False)
        self.assertNotEqual(backward.returncode, 0)
        terminal = self.finish(1, self.merged_result())
        self.assertEqual(terminal["state"], "merged")
        rejected = self.progress(phase=3, ok=False)
        self.assertNotEqual(rejected.returncode, 0)

    def test_combined_controller_demo_has_one_authoritative_outcome_per_issue(self):
        self.init_run()

        completed = self.spawn(issue=14, worktree=self.root / "wt-a")
        durable_result = self.merged_result(14)
        self.finish(completed["attempt"], durable_result, issue=14)
        delayed_result = {
            **durable_result,
            "state": "failed",
            "pr_url": None,
            "merge_sha": None,
            "issue_closed": False,
            "notes": "delayed notification",
        }
        delayed = self.finish(1, delayed_result, issue=14, ok=False)
        self.assertNotEqual(delayed.returncode, 0)

        issue_15_worktree = self.root / "wt-15"
        self.spawn(issue=15, worktree=issue_15_worktree, budget_minutes=10)
        self.spawn(issue=16, worktree=self.root / "wt-16")
        decision = self.progress(
            issue=16,
            now="2026-08-13T20:05:00Z",
            turn_count=10,
            context_tokens=140000,
        )
        self.assertEqual(decision["action"], "handoff")
        handoff_path = self.write_handoff(16)
        self.progress(
            issue=16,
            now="2026-08-13T20:05:00Z",
            turn_count=10,
            context_tokens=140000,
            handoff_path=handoff_path,
        )
        self.expire(
            issue=15, worktree=issue_15_worktree, now="2026-08-13T20:10:00Z"
        )

        final_response = self.control(
            now="2026-08-13T20:11:00Z",
            issues=[14, 15],
            tracker=[self.tracker_fact(14), self.tracker_fact(15, state="closed")],
            worktrees=[],
            max_parallel=1,
        )
        self.assert_control_response_shape(final_response)
        final_state = self.read_state()
        self.assertEqual(set(final_state["issues"]), {"14", "15", "16"})
        self.assertEqual(final_state["issues"]["14"]["outcome"], durable_result)
        self.assertIsNone(final_state["issues"]["15"]["outcome"])
        self.assertEqual(
            final_state["issues"]["15"]["attempts"][-1]["state"], "suspended"
        )
        self.assertEqual(
            final_state["issues"]["15"]["attempts"][-1]["blocked_on"], "unknown"
        )
        self.assertIsNone(final_state["issues"]["16"]["outcome"])
        self.assertEqual(
            final_state["issues"]["16"]["attempts"][-1]["state"], "handed_off"
        )
        for issue_state in final_state["issues"].values():
            self.assertLessEqual(len(issue_state["attempts"]), 2)
            self.assertTrue(
                all(attempt["attempt"] <= 2 for attempt in issue_state["attempts"])
            )
        resumable = Path(
            final_state["issues"]["16"]["attempts"][-1]["handoff_path"]
        )
        self.assertEqual(resumable, handoff_path)
        self.assertTrue(resumable.is_file())

    def test_matching_repeated_finish_is_idempotent(self):
        self.init_run()
        attempt = self.spawn(issue=14, worktree=self.root / "wt-a")["attempt"]
        result = self.merged_result()
        first = self.finish(attempt, result)
        before = self.state_path.read_bytes()
        repeated = self.finish(attempt, result, now="2026-08-13T20:05:00Z")
        self.assertEqual(repeated, first)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_conflicting_write_rejection_leaves_state_bytes_unchanged(self):
        self.init_run()
        attempt = self.spawn(issue=14, worktree=self.root / "wt-a")["attempt"]
        self.finish(attempt, self.merged_result())
        before = self.state_path.read_bytes()
        conflict = {
            **self.merged_result(),
            "state": "failed",
            "pr_url": None,
            "merge_sha": None,
            "issue_closed": False,
            "notes": "late conflicting result",
        }
        completed = self.finish(attempt, conflict, ok=False)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("conflicting terminal result", completed.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_terminal_control_returns_stored_result_without_dispatching(self):
        self.init_run()
        worktree = self.root / "wt-a"
        attempt = self.spawn(issue=14, worktree=worktree)["attempt"]
        result = self.merged_result()
        self.finish(attempt, result)
        before = self.state_path.read_bytes()
        resumed = self.control(
            now="2026-08-13T20:20:00Z",
            issues=[14],
            tracker=[self.tracker_fact(14)],
            worktrees=[self.worktree_fact(14, recorded={
                "path": os.path.abspath(worktree), "state": "matching_issue_branch",
            })],
        )
        self.assert_control_response_shape(resumed)
        self.assertEqual(resumed["summaries"][0]["result"], result)
        self.assertEqual(resumed["actions"], [{"id": "finalize", "kind": "finalize"}])
        self.assert_controller_finalized(before, now="2026-08-13T20:20:00Z")  # per D20

    def test_invalid_schema_state_and_action_are_rejected_without_changes(self):
        corruptions = (
            ("schema", lambda state: state.__setitem__("schema_version", 99)),
            (
                "lineage",
                lambda state: state.__setitem__("prior_run", state["run_id"]),
            ),
            (
                "state",
                lambda state: state["issues"]["14"]["attempts"][0].__setitem__(
                    "state", "unknown"
                ),
            ),
            (
                "action",
                lambda state: state["issues"]["14"]["attempts"][0].__setitem__(
                    "phase_action", "unknown"
                ),
            ),
        )
        for label, corrupt in corruptions:
            with self.subTest(label=label):
                self.init_run()
                if label != "schema":
                    self.spawn(issue=14, worktree=self.root / "wt-a")
                state = self.read_state()
                corrupt(state)
                self.state_path.write_text(json.dumps(state), encoding="utf-8")
                before = self.state_path.read_bytes()
                completed = self.control_raw(
                    now=DEFAULT_NOW,
                    issues=[14],
                    tracker=[self.tracker_fact(14)],
                    worktrees=[],
                    max_parallel=1,
                    ok=False,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(self.state_path.read_bytes(), before)
                self.state_path.unlink()

    def test_cross_field_lifecycle_corruption_is_rejected_without_changes(self):
        terminal = self.merged_result()
        stopped = {
            **terminal,
            "state": "stopped",
            "pr_url": None,
            "merge_sha": None,
            "issue_closed": False,
            "notes": "stopped",
        }
        corruptions = (
            (
                "active-with-result",
                lambda attempt: attempt.__setitem__("result", terminal),
                None,
            ),
            (
                "terminal-without-result",
                lambda attempt: attempt.__setitem__("state", "merged"),
                None,
            ),
            (
                "terminal-state-mismatch",
                lambda attempt: attempt.update(
                    {"state": "failed", "result": terminal}
                ),
                None,
            ),
            (
                "launch-kind-mismatch",
                lambda attempt: attempt.__setitem__("launch_kind", "resume"),
                None,
            ),
            (
                "start-after-progress",
                lambda attempt: attempt.__setitem__(
                    "started_at", "2026-08-13T20:01:00Z"
                ),
                None,
            ),
            (
                "progress-after-deadline",
                lambda attempt: attempt.__setitem__(
                    "last_progress_at", "2026-08-13T20:31:00Z"
                ),
                None,
            ),
            (
                "launch-before-start",
                lambda attempt: attempt["launches"][0].__setitem__(
                    "at", "2026-08-13T19:59:00Z"
                ),
                None,
            ),
            (
                "launch-after-deadline",
                lambda attempt: attempt["launches"][0].__setitem__(
                    "at", "2026-08-13T20:31:00Z"
                ),
                None,
            ),
            (
                "terminal-without-finished-at",
                lambda attempt: attempt.update(
                    {
                        "state": "merged",
                        "result": terminal,
                        "finished_at": None,
                        "result_source": "owner",
                    }
                ),
                "must all be null or all be set",
            ),
            (
                "nonterminal-with-result-source",
                lambda attempt: attempt.__setitem__("result_source", "owner"),
                "must all be null or all be set",
            ),
            (
                "unknown-result-source",
                lambda attempt: attempt.update(
                    {
                        "state": "merged",
                        "result": terminal,
                        "finished_at": "2026-08-13T20:05:00Z",
                        "result_source": "reaper",
                    }
                ),
                "invalid attempt result source",
            ),
            (
                "finished-at-before-start",
                lambda attempt: attempt.update(
                    {
                        "state": "merged",
                        "result": terminal,
                        "finished_at": "2026-08-13T19:59:59Z",
                        "result_source": "owner",
                    }
                ),
                "invalid attempt finish time order",
            ),
            (
                "expiry-finished-before-deadline",
                lambda attempt: attempt.update(
                    {
                        "state": "stopped",
                        "result": stopped,
                        "finished_at": "2026-08-13T20:29:59Z",
                        "result_source": "expiry",
                    }
                ),
                "expiry finish time must not precede the attempt deadline",
            ),
        )
        for label, corrupt, message in corruptions:
            with self.subTest(label=label):
                self.init_run()
                self.spawn(issue=14, worktree=self.root / "wt-a")
                state = self.read_state()
                attempt = state["issues"]["14"]["attempts"][0]
                corrupt(attempt)
                self.state_path.write_text(json.dumps(state), encoding="utf-8")
                before = self.state_path.read_bytes()
                completed = self.control_raw(
                    now=DEFAULT_NOW,
                    issues=[14],
                    tracker=[self.tracker_fact(14)],
                    worktrees=[],
                    max_parallel=1,
                    ok=False,
                )
                self.assertNotEqual(completed.returncode, 0)
                if message is not None:
                    self.assertIn(message, completed.stderr)
                self.assertEqual(self.state_path.read_bytes(), before)
                self.state_path.unlink()

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_repository_path_escapes_are_rejected_before_external_mutation(self):
        outside_temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(outside_temporary_directory.cleanup)
        outside = Path(outside_temporary_directory.name)

        missing_root = self.root / "missing-repository"
        missing = self.run_cli(
            "init-run",
            "--repo-root",
            missing_root,
            "--run-id",
            self.run_id,
            "--now",
            DEFAULT_NOW,
            ok=False,
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertFalse(missing_root.exists())

        symlink_root = self.root / "symlink-root"
        symlink_root.mkdir()
        (symlink_root / ".superpowers").symlink_to(
            outside, target_is_directory=True
        )
        escaped = self.run_cli(
            "init-run",
            "--repo-root",
            symlink_root,
            "--run-id",
            self.run_id,
            "--now",
            DEFAULT_NOW,
            ok=False,
        )
        self.assertNotEqual(escaped.returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlinked_stable_lock_and_state_are_rejected_without_external_mutation(self):
        outside_temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(outside_temporary_directory.cleanup)
        outside = Path(outside_temporary_directory.name)

        for stable_name in ("state.lock", "state.json"):
            with self.subTest(stable_name=stable_name):
                run_id = f"stable-{stable_name.replace('.', '-')}"
                self.run_cli(
                    "init-run",
                    "--repo-root",
                    self.root,
                    "--run-id",
                    run_id,
                    "--now",
                    DEFAULT_NOW,
                )
                run_dir = self.workflows_dir / run_id
                stable_path = run_dir / stable_name
                external_path = outside / stable_name
                if stable_name == "state.json":
                    external_path.write_bytes(stable_path.read_bytes())
                else:
                    external_path.write_bytes(b"external lock sentinel")
                before = external_path.read_bytes()
                request_path = self.root / f"control-{run_id}.json"
                request_path.write_text(json.dumps(self.control_request(
                    now=DEFAULT_NOW,
                    issues=[14],
                    tracker=[self.tracker_fact(14)],
                    worktrees=[],
                    max_parallel=1,
                )), encoding="utf-8")
                stable_path.unlink()
                stable_path.symlink_to(external_path)

                rejected = self.run_cli(
                    "control",
                    "--repo-root",
                    self.root,
                    "--run-id",
                    run_id,
                    "--request-file",
                    request_path,
                    ok=False,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(external_path.read_bytes(), before)

    def test_result_schema_note_length_and_nullable_url_sha_validation(self):
        self.init_run()
        attempt = self.spawn(issue=14, worktree=self.root / "wt-a")["attempt"]
        invalid_results = (
            {**self.merged_result(), "extra": "field"},
            {key: value for key, value in self.merged_result().items() if key != "notes"},
            {**self.merged_result(), "state": "active"},
            {**self.merged_result(), "notes": "x" * 501},
            {**self.merged_result(), "pr_url": 15},
            {**self.merged_result(), "merge_sha": False},
            {**self.merged_result(), "issue_closed": 1},
            {**self.merged_result(), "discussion_items": "none"},
            {**self.merged_result(), "issue": 15},
        )
        for index, result in enumerate(invalid_results):
            with self.subTest(index=index):
                before = self.state_path.read_bytes()
                completed = self.finish(attempt, result, ok=False)
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(self.state_path.read_bytes(), before)

        nullable = {
            **self.merged_result(),
            "state": "stopped",
            "pr_url": None,
            "merge_sha": None,
            "issue_closed": False,
            "notes": "stopped cleanly",
        }
        normalized = self.finish(attempt, nullable)
        self.assertEqual(
            {key: normalized[key] for key in nullable if key != "notes"},
            {key: nullable[key] for key in nullable if key != "notes"},
        )
        self.assertIn(nullable["notes"], normalized["notes"])
        self.assertIn(os.path.abspath(self.root / "wt-a"), normalized["notes"])
        self.assertLessEqual(len(normalized["notes"]), 500)

    def test_terminal_result_report_path_is_one_validated_durable_scalar(self):
        self.init_run()
        attempt = self.spawn(issue=14, worktree=self.root / "wt-a")["attempt"]
        detail = ".superpowers/issue-delivery/14/run-1/ship-review-a.json"
        self.write_delivery_detail(detail)
        valid = {**self.merged_result(), "detail_state": "present", "report_path": detail,
                 "notes": f"details: {detail}"}
        invalid = (
            {key: value for key, value in valid.items() if key != "report_path"},
            {**valid, "report_path": [detail]},
            {**valid, "report_path": "/tmp/outside.json"},
            {**valid, "report_path": "../outside.json"},
            {**valid, "notes": "detail omitted"},
            {**valid, "discussion_items": ["not durably moved"]},
        )
        for candidate in invalid:
            before = self.state_path.read_bytes()
            self.finish(attempt, candidate, ok=False)
            self.assertEqual(self.state_path.read_bytes(), before)
        normalized = self.finish(attempt, valid)
        self.assertEqual(normalized["report_path"], detail)
        self.assertIn(detail, normalized["notes"])

    def test_present_ship_detail_must_exist_be_valid_and_stay_beneath_repo_root(self):
        self.init_run()
        attempt = self.spawn(issue=14, worktree=self.root / "wt-a")["attempt"]
        detail = ".superpowers/issue-delivery/14/run-1/ship-review-a.json"
        result = {**self.merged_result(), "detail_state": "present", "report_path": detail,
                  "notes": f"details: {detail}"}

        before = self.state_path.read_bytes()
        self.finish(attempt, result, ok=False)
        self.assertEqual(self.state_path.read_bytes(), before)

        root = self.write_delivery_detail(detail)
        root.write_text("{}", encoding="utf-8")
        self.finish(attempt, result, ok=False)
        self.assertEqual(self.state_path.read_bytes(), before)

        outside = self.root.parent / f"{self.root.name}-outside"
        outside.mkdir()
        self.addCleanup(lambda: outside.rmdir() if outside.exists() else None)
        escaped_parent = self.root / ".superpowers/issue-delivery/14/escape"
        escaped_parent.parent.mkdir(parents=True, exist_ok=True)
        escaped_parent.symlink_to(outside, target_is_directory=True)
        escaped = ".superpowers/issue-delivery/14/escape/review.json"
        escaped_result = {**result, "report_path": escaped, "notes": f"details: {escaped}"}
        self.finish(attempt, escaped_result, ok=False)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_unpublished_ship_detail_retains_a_readable_candidate(self):
        self.init_run()
        worktree = self.root / "wt-a"
        attempt = self.spawn(issue=14, worktree=worktree)["attempt"]
        relative = ".superpowers/ship-review/14/retained-detail.json"
        retained = worktree / relative
        payload = ('{"interface_version":1,"findings":[{"axis":"ship","ruling":null,'
                   '"severity":"Minor","status":"minor","text":"kept"}]}')
        result = {**self.merged_result(), "state": "stopped", "pr_url": None,
                  "merge_sha": None, "issue_closed": False,
                  "detail_state": "unpublished", "report_path": relative,
                  "discussion_items": [],
                  "notes": f"publication failed; retained: {relative}"}
        before = self.state_path.read_bytes()
        self.finish(attempt, result, ok=False)
        self.assertEqual(self.state_path.read_bytes(), before)
        retained.parent.mkdir(parents=True)
        invalid_payloads = ("", "{", '{"interface_version":2,"findings":[]}',
                            '{"interface_version":1,"items":[]}',
                            '{"interface_version":1,"findings":[]}')
        for invalid in invalid_payloads:
            retained.write_text(invalid, encoding="utf-8")
            before = self.state_path.read_bytes()
            self.finish(attempt, result, ok=False)
            self.assertEqual(self.state_path.read_bytes(), before)
        retained.write_text(payload, encoding="utf-8")
        normalized = self.finish(attempt, result)
        self.assertEqual(normalized["detail_state"], "unpublished")
        self.assertEqual(retained.read_text(encoding="utf-8"), payload)

    def test_workflows_gitignore_contains_wildcard(self):
        self.init_run()
        self.assertEqual(
            (self.workflows_dir / ".gitignore").read_text(encoding="utf-8"), "*\n"
        )

    def test_invalid_time_run_id_and_identity_are_rejected(self):
        invalid_init_args = (
            ("--run-id", "../escape", "--now", DEFAULT_NOW),
            ("--run-id", self.run_id, "--now", "2026-08-13T20:00:00"),
            ("--run-id", self.run_id, "--now", "2026-08-13T21:00:00+01:00"),
        )
        for args in invalid_init_args:
            with self.subTest(args=args):
                completed = self.run_cli(
                    "init-run", "--repo-root", self.root, *args, ok=False
                )
                self.assertNotEqual(completed.returncode, 0)

        self.init_run()
        before = self.state_path.read_bytes()
        completed = self.run_cli(
            "finish",
            "--repo-root",
            self.root,
            "--run-id",
            self.run_id,
            "--issue",
            14,
            "--attempt",
            1,
            "--result-file",
            self.root / "missing.json",
            "--now",
            DEFAULT_NOW,
            ok=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(self.state_path.read_bytes(), before)

    @unittest.skipUnless(hasattr(os, "pipe") and os.name == "posix", "POSIX barrier")
    def test_concurrent_controls_for_distinct_issues_preserve_both_updates(self):
        self.init_run()
        wrapper = (
            "import os,sys; "
            "fd=int(sys.argv[1]); script=sys.argv[2]; args=sys.argv[3:]; "
            "os.read(fd,1); os.execv(sys.executable,[sys.executable,script,*args])"
        )
        processes = []
        write_fds = []
        for issue in (14, 15):
            read_fd, write_fd = os.pipe()
            request_path = self.root / f"concurrent-control-{issue}.json"
            request_path.write_text(json.dumps(self.control_request(
                now=DEFAULT_NOW,
                issues=[issue],
                tracker=[self.tracker_fact(issue)],
                worktrees=[self.worktree_fact(issue, candidate={
                    "path": str(self.root / f"wt-{issue}"), "state": "absent",
                })],
                max_parallel=2,
            )), encoding="utf-8")
            args = [
                "control",
                "--repo-root",
                str(self.root),
                "--run-id",
                self.run_id,
                "--request-file",
                str(request_path),
            ]
            process = subprocess.Popen(
                [sys.executable, "-c", wrapper, str(read_fd), str(SCRIPT), *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                pass_fds=(read_fd,),
                env=self.cli_env,
            )
            os.close(read_fd)
            processes.append(process)
            write_fds.append(write_fd)

        for write_fd in write_fds:
            os.write(write_fd, b"x")
            os.close(write_fd)

        for process in processes:
            stdout, stderr = process.communicate()
            self.assertEqual(process.returncode, 0, stderr)
            response = self._legacy_control(json.loads(stdout))
            self.assert_control_response_shape(response)
            dispatch = self.dispatch_action(response, "spawn")
            self.assertEqual((dispatch["attempt"], dispatch["owner"]), (
                1, f"{dispatch['issue']}:1",
            ))

        reopened = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(set(reopened["issues"]), {"14", "15"})
        for issue in (14, 15):
            attempt = reopened["issues"][str(issue)]["attempts"][0]
            self.assertEqual(attempt["issue"], issue)
            self.assertEqual(len(attempt["launches"]), 1)

    def test_direct_owner_observes_then_atomically_persists_first_owner(self):
        owner = self.acquire_direct()
        worktree = os.path.abspath(self.root / "worktree-issue-73")
        self.assertEqual(owner, {
            "interface_version": 1, "kind": "owner",
            "ledger_repo_root": str(self.root.resolve()),
            "run_id": "direct-73-000001", "issue": 73, "attempt": 1,
            "owner": "73:1", "action_id": "73:1:1", "launch_kind": "spawn",
            "worktree": worktree, "handoff_path": None,
            "deadline_at": "2026-08-20T13:00:00Z",
        })
        state = json.loads(self.direct_state_path(owner["run_id"]).read_text())
        self.assertEqual(len(state["issues"]["73"]["attempts"]), 1)
        self.assertEqual(state["issues"]["73"]["attempts"][0]["worktree"], worktree)
        self.assertEqual(state["issues"]["73"]["attempts"][0]["launches"], [{
            "kind": "fresh", "owner": "73:1", "worktree": worktree,
            "at": "2026-08-20T10:00:00Z",
        }])

    def test_direct_owner_strict_request_failures_precede_mutation(self):
        valid = self.direct_request()
        cases = {
            "unknown": {**valid, "extra": None},
            "missing required": {
                key: value for key, value in valid.items()
                if key != "attempt_budget_minutes"
            },
            "version": {**valid, "interface_version": 1},
            "boolean version": {**valid, "interface_version": True},
            "boolean issue": {**valid, "issue": True},
            "oversized issue": {**valid, "issue": int("9" * 115)},
            "zero budget": {**valid, "attempt_budget_minutes": 0},
            "boolean budget": {**valid, "attempt_budget_minutes": True},
            "nonboolean new run": {**valid, "new_run": 1},
            "nonboolean owner unavailable": {**valid, "owner_unavailable": "false"},
            "local time": {**valid, "now": "2026-08-20T10:00:00"},
            "both flags": {**valid, "new_run": True, "owner_unavailable": True},
            "tracker mismatch": {**valid, "tracker": self.tracker_fact(74)},
            "worktree mismatch": {**valid, "worktree": self.worktree_fact(74)},
            "unknown forge field": {
                **valid, "forge": {**self.no_pull_request(), "extra": None},
            },
            "unknown forge state": {
                **valid, "forge": {**self.no_pull_request(), "state": "draft"},
            },
            "merged forge without a sha": {**valid, "forge": {
                "state": "merged",
                "url": "https://github.com/fagenorn/nix-config/pull/78",
                "merge_sha": None,
            }},
            "unmerged forge with a sha": {**valid, "forge": {
                **self.no_pull_request(),
                "merge_sha": "f3fac95aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            }},
            "abbreviated merge sha": {**valid, "forge": {
                "state": "merged",
                "url": "https://github.com/fagenorn/nix-config/pull/78",
                "merge_sha": "f3fac95",
            }},
        }
        for label, request in cases.items():
            with self.subTest(label=label):
                completed = self.direct_owner_raw(request=request, ok=False)
                self.assertEqual(completed.returncode, 2)
                self.assertEqual(completed.stdout, "")
        self.assertFalse(self.workflows_dir.exists())

    def test_direct_owner_rejects_an_unrepresentable_deadline_without_traceback(self):
        candidate = os.path.abspath(self.root / "worktree-issue-73")
        # A supplied `now` may lead the clock by at most 60 s (#309 D6), so the
        # deadline overflow is reached by a budget too long for any date, not a late `now`.
        rejected = self.direct_owner_raw(
            now="2026-09-30T12:00:00Z",
            attempt_budget_minutes=10**10,
            tracker=self.tracker_fact(73),
            worktree=self.worktree_fact(
                73, candidate={"path": candidate, "state": "absent"},
            ),
            ok=False,
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertEqual(rejected.stdout, "")
        self.assertIn("attempt deadline is out of range", rejected.stderr)
        self.assertNotIn("Traceback", rejected.stderr)
        self.assertFalse((self.workflows_dir / "direct-73-000001").exists())

    def test_direct_owner_requires_explicit_unavailable_authorization_to_resume_active(self):
        owner = self.acquire_direct()
        state_path = self.direct_state_path(owner["run_id"])
        before = state_path.read_bytes()
        refused = self.direct_owner_raw(ok=False)
        self.assertIn("active", refused.stderr)
        self.assertEqual(state_path.read_bytes(), before)
        needed = self.direct_owner(owner_unavailable=True)
        self.assertEqual(needed["requirements"], [{
            "kind": "recorded_worktree", "path": owner["worktree"],
        }])
        resumed = self.direct_owner(
            owner_unavailable=True,
            worktree=self.worktree_fact(73, recorded={
                "path": owner["worktree"], "state": "matching_issue_branch",
            }),
        )
        self.assertEqual(
            (resumed["run_id"], resumed["attempt"], resumed["owner"],
             resumed["action_id"], resumed["launch_kind"], resumed["deadline_at"]),
            ("direct-73-000001", 1, "73:1", "73:1:2", "resume",
             "2026-08-20T13:00:00Z"),
        )
        persisted = json.loads(state_path.read_text())["issues"]["73"]["attempts"][0]
        self.assertEqual(len(persisted["launches"]), 2)
        self.assertEqual(persisted["started_at"], "2026-08-20T10:00:00Z")

    def test_direct_owner_automatically_resumes_handoff_with_fixed_identity(self):
        owner = self.acquire_direct()
        self.run_id = owner["run_id"]
        handoff = self.write_handoff(73)
        self.progress(
            issue=73, now="2026-08-20T10:30:00Z", phase=4,
            turn_count=118, artifacts_sufficient=False,
            next_needs_context=True, handoff_path=handoff,
        )
        needed = self.direct_owner(now="2026-08-20T10:31:00Z")
        self.assertEqual(needed["requirements"], [{
            "kind": "recorded_worktree", "path": owner["worktree"],
        }])
        resumed = self.direct_owner(
            now="2026-08-20T10:31:00Z",
            worktree=self.worktree_fact(73, recorded={
                "path": owner["worktree"], "state": "matching_issue_branch",
            }),
        )
        self.assertEqual(resumed["launch_kind"], "resume")
        self.assertEqual(resumed["handoff_path"], str(handoff))
        self.assertEqual(resumed["deadline_at"], owner["deadline_at"])

    def test_direct_phase_zero_handoff_resumes_its_exact_absent_reservation(self):
        owner = self.acquire_direct(issue=73)
        self.run_id = owner["run_id"]
        handoff = self.write_handoff(73)
        self.progress(
            issue=73, phase=0, now="2026-08-20T10:01:00Z",
            turn_count=118, context_tokens=20000,
            next_needs_context=True, artifacts_sufficient=False,
            handoff_path=handoff,
        )
        before = json.loads(self.direct_state_path(owner["run_id"]).read_text())
        alternate = os.path.abspath(self.root / "alternate-worktree-73")
        resumed = self.direct_owner(
            issue=73, now="2026-08-20T10:02:00Z",
            worktree=self.worktree_fact(
                73,
                recorded={"path": owner["worktree"], "state": "absent"},
                candidate={"path": alternate, "state": "absent"},
            ),
        )
        self.assertEqual(resumed, {
            **owner, "action_id": "73:1:2", "launch_kind": "resume",
            "handoff_path": str(handoff),
        })
        after = json.loads(self.direct_state_path(owner["run_id"]).read_text())
        attempt = after["issues"]["73"]["attempts"][0]
        old_attempt = before["issues"]["73"]["attempts"][0]
        for field in ("issue", "attempt", "owner", "worktree", "started_at",
                      "deadline_at", "handoff_path"):
            self.assertEqual(attempt[field], old_attempt[field])
        self.assertEqual(attempt["state"], "active")
        self.assertEqual(attempt["launch_kind"], "resume")
        self.assertEqual(len(attempt["launches"]), 2)
        self.assertEqual(resumed["owner"], owner["owner"])
        self.assertEqual(resumed["worktree"], owner["worktree"])
        self.assertNotEqual(resumed["worktree"], alternate)
        self.assertEqual(len(after["issues"]["73"]["attempts"]), 1)
        self.assertFalse(self.direct_state_path("direct-73-000002").exists())

    def test_absent_resume_exception_rejects_every_adjacent_case_without_mutation(self):
        owner = self.acquire_direct(issue=74)
        self.run_id = owner["run_id"]
        handoff = self.write_handoff(74)
        self.progress(
            issue=74, phase=1, now="2026-08-20T10:01:00Z",
            turn_count=118, handoff_path=handoff,
        )
        path = self.direct_state_path(owner["run_id"])
        before = path.read_bytes()
        observed = self.direct_owner(
            issue=74, now="2026-08-20T10:02:00Z",
            worktree=self.worktree_fact(74, recorded={
                "path": owner["worktree"], "state": "absent",
            }),
        )
        self.assertEqual(observed["kind"], "observe")
        self.assertEqual(path.read_bytes(), before)

        active = self.acquire_direct(issue=75)
        active_path = self.direct_state_path(active["run_id"])
        before = active_path.read_bytes()
        observed = self.direct_owner(
            issue=75, now="2026-08-20T10:02:00Z", owner_unavailable=True,
            worktree=self.worktree_fact(75, recorded={
                "path": active["worktree"], "state": "absent",
            }),
        )
        self.assertEqual(observed["kind"], "observe")
        self.assertEqual(active_path.read_bytes(), before)

        owner = self.acquire_direct(issue=76)
        self.run_id = owner["run_id"]
        handoff = self.write_handoff(76)
        self.progress(
            issue=76, phase=0, now="2026-08-20T10:01:00Z",
            turn_count=118, handoff_path=handoff,
        )
        path = self.direct_state_path(owner["run_id"])
        before = path.read_bytes()
        replacement = os.path.abspath(self.root / "alternate-76")
        for recorded in (None, {
            "path": owner["worktree"], "state": "mismatch",
        }):
            with self.subTest(recorded=recorded):
                observed = self.direct_owner(
                    issue=76, now="2026-08-20T10:02:00Z",
                    worktree=self.worktree_fact(
                        76, recorded=recorded,
                        candidate={"path": replacement, "state": "absent"},
                    ),
                )
                self.assertEqual(observed["kind"], "observe")
                self.assertEqual(observed["requirements"], [{
                    "kind": "recorded_worktree", "path": owner["worktree"],
                }])
                self.assertEqual(path.read_bytes(), before)
        wrong = self.direct_owner_raw(
            issue=76, now="2026-08-20T10:02:00Z",
            worktree=self.worktree_fact(76, recorded={
                "path": os.path.abspath(self.root / "wrong-76"),
                "state": "absent",
            }), ok=False,
        )
        self.assertIn("recorded worktree path does not match ledger", wrong.stderr)
        self.assertEqual(path.read_bytes(), before)

        # The exception is bounded by the phase, not by who dispatches: an
        # orchestrated handoff past Phase 0 owns a worktree it must still show,
        # so its absence refuses that issue alone, in its summary (#194).
        self.run_id = "dispatcher-phase-one"
        self.init_run(now="2026-08-20T10:00:00Z")
        dispatched = self.spawn(
            issue=77, worktree=self.root / "dispatcher-77",
            now="2026-08-20T10:00:00Z",
        )
        handoff = self.write_handoff(77)
        self.progress(
            issue=77, phase=1, now="2026-08-20T10:01:00Z",
            turn_count=118, handoff_path=handoff,
        )
        before = self.state_path.read_bytes()
        response = self.control_validated(
            now="2026-08-20T10:02:00Z", issues=[77],
            tracker=[self.tracker_fact(77)],
            worktrees=[self.worktree_fact(77, recorded={
                "path": dispatched["worktree"], "state": "absent",
            })], max_parallel=1,
        )
        self.assertEqual([item["kind"] for item in response["actions"]], ["wait"])
        self.assertEqual(response["summaries"][0]["state"], "handed_off")
        self.assertIn(self.unresumable_fact(dispatched["worktree"], "absent"),
                      response["summaries"][0]["requirements"])
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_zero_sequence_direct_shaped_dispatcher_resumes_an_absent_reservation(self):
        """The Phase-0 absent exception no longer reads the run id (per D7)."""
        self.run_id = "direct-78-000000"
        self.init_run(now="2026-08-20T10:00:00Z")
        dispatched = self.spawn(
            issue=78, worktree=self.root / "dispatcher-78",
            now="2026-08-20T10:00:00Z",
        )
        handoff = self.write_handoff(78)
        self.progress(
            issue=78, phase=0, now="2026-08-20T10:01:00Z",
            turn_count=118, handoff_path=handoff,
        )
        resumed = self.control(
            now="2026-08-20T10:02:00Z", issues=[78],
            tracker=[self.tracker_fact(78)],
            worktrees=[self.worktree_fact(78, recorded={
                "path": dispatched["worktree"], "state": "absent",
            })], max_parallel=1,
        )
        self.assert_control_response_shape(resumed)
        action = self.dispatch_action(resumed, "resume")
        self.assertEqual(action["worktree"], dispatched["worktree"])
        self.assertEqual(action["handoff_path"], str(handoff))
        attempt = self.read_state()["issues"]["78"]["attempts"][-1]
        self.assertEqual(attempt["state"], "active")
        self.assertEqual(len(attempt["launches"]), 2)

    def test_absent_direct_handoff_materializes_exact_worktree_then_records_phase_one(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            origin = root / "origin.git"
            repo = root / "repo"
            worktree = root / "worktree-issue-73"
            subprocess.run(["git", "init", "--bare", str(origin)], check=True,
                           capture_output=True, text=True)
            subprocess.run(["git", "clone", str(origin), str(repo)], check=True,
                           capture_output=True, text=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Fixture"],
                           check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email",
                            "fixture@example.test"], check=True)
            subprocess.run(["git", "-C", str(repo), "checkout", "-b", "main"],
                           check=True, capture_output=True, text=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "fixture"],
                           check=True, capture_output=True, text=True)
            subprocess.run(["git", "-C", str(repo), "push", "-u", "origin", "main"],
                           check=True, capture_output=True, text=True)

            original_root, original_run_id = self.root, self.run_id
            self.root = repo
            self.addCleanup(setattr, self, "root", original_root)
            self.addCleanup(setattr, self, "run_id", original_run_id)
            owner = self.acquire_direct(issue=73, worktree=worktree)
            self.run_id = owner["run_id"]
            handoff = self.write_handoff(73)
            self.progress(
                issue=73, phase=0, now="2026-08-20T10:01:00Z",
                turn_count=118, handoff_path=handoff,
            )
            self.assertFalse(worktree.exists())
            resumed = self.direct_owner(
                issue=73, now="2026-08-20T10:02:00Z",
                worktree=self.worktree_fact(73, recorded={
                    "path": str(worktree), "state": "absent",
                }),
            )
            self.assertEqual(resumed["worktree"], str(worktree))
            self.assertEqual(resumed["launch_kind"], "resume")
            self.assertFalse(worktree.exists())

            subprocess.run([
                "git", "-C", str(repo), "worktree", "add", "-b", "issue-73-fixture",
                str(worktree), "origin/main",
            ], check=True, capture_output=True, text=True)
            branch = subprocess.run([
                "git", "-C", str(worktree), "rev-parse", "--abbrev-ref", "HEAD",
            ], check=True, capture_output=True, text=True).stdout.strip()
            self.assertEqual(branch, "issue-73-fixture")
            progressed = self.progress(
                issue=73, phase=1, now="2026-08-20T10:03:00Z",
                turn_count=10, context_tokens=20000,
            )
            self.assertEqual(progressed["custody"]["action_id"], "73:1:2")
            state = json.loads(self.direct_state_path(owner["run_id"]).read_text())
            attempts = state["issues"]["73"]["attempts"]
            self.assertEqual(attempts[0]["phase"], 1)
            self.assertEqual(len(attempts), 1)
            self.assertEqual(len(attempts[0]["launches"]), 2)
            self.assertEqual(attempts[0]["worktree"], str(worktree))
            runs = sorted(path.name for path in self.workflows_dir.glob("direct-73-*"))
            self.assertEqual(runs, [owner["run_id"]])

    def test_direct_owner_retries_owner_failure_then_replays_terminal_and_starts_new_run(self):
        owner = self.acquire_direct()
        self.run_id = owner["run_id"]
        self.fail_owner(issue=73, attempt=1, now="2026-08-20T10:20:00Z")
        tracker = self.tracker_fact(73)
        self.assertEqual(self.direct_owner(now="2026-08-20T10:21:00Z")["requirements"], [
            {"kind": "tracker"},
        ])
        needed = self.direct_owner(now="2026-08-20T10:21:00Z", tracker=tracker)
        self.assertEqual(needed["requirements"], [{
            "kind": "recorded_worktree", "path": owner["worktree"],
        }])
        retry = self.direct_owner(
            now="2026-08-20T10:21:00Z", tracker=tracker,
            worktree=self.worktree_fact(73, recorded={
                "path": owner["worktree"], "state": "matching_issue_branch",
            }),
        )
        self.assertEqual(
            (retry["attempt"], retry["owner"], retry["action_id"],
             retry["launch_kind"], retry["worktree"]),
            (2, "73:2", "73:2:1", "retry", owner["worktree"]),
        )
        self.fail_owner(issue=73, attempt=2, now="2026-08-20T10:30:00Z")
        refused = self.direct_owner(
            now="2026-08-20T10:31:00Z", tracker=tracker,
            worktree=self.worktree_fact(73, recorded={
                "path": owner["worktree"], "state": "matching_issue_branch",
            }),
        )
        self.assertEqual((refused["kind"], refused["source"], refused["reason"]),
                         ("terminal", "lifecycle", "failed"))
        replay = self.direct_owner(now="2026-08-20T10:32:00Z")
        self.assertEqual(replay, refused)
        next_needed = self.direct_owner(
            now="2026-08-20T10:33:00Z", new_run=True, tracker=tracker,
        )
        self.assertEqual(next_needed["run_id"], "direct-73-000002")
        self.assertEqual(next_needed["requirements"], [{
            "kind": "recorded_worktree", "path": owner["worktree"],
        }])
        renewed = self.direct_owner(
            now="2026-08-20T10:33:00Z", new_run=True, tracker=tracker,
            worktree=self.worktree_fact(73, recorded={
                "path": owner["worktree"], "state": "matching_issue_branch",
            }),
        )
        self.assertEqual(
            (renewed["run_id"], renewed["attempt"], renewed["launch_kind"],
             renewed["worktree"]),
            ("direct-73-000002", 1, "spawn", owner["worktree"]),
        )
        self.assertTrue(self.direct_state_path("direct-73-000001").exists())
        self.assertTrue(self.direct_state_path("direct-73-000002").exists())

    def test_direct_new_run_tracker_terminals_do_not_leak_uncreated_run_id(self):
        owner = self.acquire_direct()
        self.run_id = owner["run_id"]
        self.finish(1, self.merged_result(73), issue=73,
                    now="2026-08-20T10:01:00Z")
        cases = (
            (self.tracker_fact(73, state="closed"), "closed", []),
            (self.tracker_fact(73, open_blockers=[12], decision_blockers=[
                {"issue": 99, "url": "https://example.test/issues/99"},
            ]), "fogged", [
                {"kind": "issue", "issue": 12, "url": None},
                {"kind": "decision", "issue": 99,
                 "url": "https://example.test/issues/99"},
            ]),
            (self.tracker_fact(73, open_blockers=[12]), "blocked", [
                {"kind": "issue", "issue": 12, "url": None},
            ]),
        )
        for tracker, reason, blockers in cases:
            with self.subTest(reason=reason):
                self.assertEqual(self.direct_owner(
                    now="2026-08-20T10:02:00Z", new_run=True,
                    tracker=tracker,
                ), {
                    "interface_version": 1, "kind": "terminal", "issue": 73,
                    "run_id": None, "source": "tracker", "reason": reason,
                    "blockers": blockers, "result": None,
                    "reentry": "/from-issue 73 --auto",
                })
                self.assertFalse(
                    self.direct_state_path("direct-73-000002").exists()
                )

    def test_direct_owner_tracker_terminals_use_closed_precedence_and_closed_shapes(self):
        cases = (
            (self.tracker_fact(73, state="closed"), "closed", []),
            (self.tracker_fact(73, open_blockers=[12], decision_blockers=[
                {"issue": 99, "url": "https://example.test/issues/99"},
            ]), "fogged", [{
                "kind": "issue", "issue": 12, "url": None,
            }, {
                "kind": "decision", "issue": 99,
                "url": "https://example.test/issues/99",
            }]),
            (self.tracker_fact(73, open_blockers=[12]), "blocked", [{
                "kind": "issue", "issue": 12, "url": None,
            }]),
        )
        for tracker, reason, blockers in cases:
            with self.subTest(reason=reason):
                terminal = self.direct_owner(tracker=tracker)
                self.assertEqual(terminal, {
                    "interface_version": 1, "kind": "terminal", "issue": 73,
                    "run_id": None, "source": "tracker", "reason": reason,
                    "blockers": blockers, "result": None,
                    "reentry": "/from-issue 73 --auto",
                })
                self.assertFalse(any(
                    path.name.startswith("direct-73-")
                    for path in self.workflows_dir.iterdir()
                ))

    def test_reserved_direct_ids_are_closed_to_init_and_control_but_open_to_owner_mutations(self):
        request_path = self.root / "control-reserved.json"
        request_path.write_text(json.dumps(self.control_request(
            now="2026-08-20T10:00:00Z", issues=[73],
            tracker=[self.tracker_fact(73)], worktrees=[],
        )), encoding="utf-8")
        for run_id in ("direct-73-000001", "direct-73-999999"):
            rejected_init = self.run_cli(
                "init-run", "--repo-root", self.root, "--run-id", run_id,
                "--now", "2026-08-20T10:00:00Z", ok=False,
            )
            rejected_control = self.run_cli(
                "control", "--repo-root", self.root, "--run-id", run_id,
                "--request-file", request_path, ok=False,
            )
            for rejected in (rejected_init, rejected_control):
                self.assertEqual(rejected.returncode, 2)
                self.assertEqual(rejected.stdout, "")
            self.assertFalse((self.workflows_dir / run_id).exists())

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            zero_id = "direct-73-000000"
            initialized = self.run_cli(
                "init-run", "--repo-root", root, "--run-id", zero_id,
                "--now", "2026-08-20T10:00:00Z",
            )
            self.assertEqual(json.loads(initialized.stdout), {
                "interface_version": 2, "kind": "workflow_bootstrap",
                "run_id": zero_id, "requirements": [],
            })
            zero_request = root / "control-zero.json"
            zero_request.write_text(json.dumps(self.control_request(
                now="2026-08-20T10:01:00Z", issues=[73],
                tracker=[self.tracker_fact(73, state="closed")], worktrees=[],
            )), encoding="utf-8")
            controlled = self.run_cli(
                "control", "--repo-root", root, "--run-id", zero_id,
                "--request-file", zero_request,
            )
            controlled_value = json.loads(controlled.stdout)
            self.assertEqual(controlled_value["interface_version"], 3)
            self.assertEqual(controlled_value["run_id"], zero_id)
            self.assertEqual(controlled_value["summaries"][0]["state"], "closed")
            self.assertEqual(controlled_value["actions"],
                             [{"id": "finalize", "kind": "finalize"}])

        run_id = "direct-73-000001"
        owner = self.acquire_direct()
        before = self.direct_state_path(run_id).read_bytes()
        existing_init = self.run_cli(
            "init-run", "--repo-root", self.root, "--run-id", run_id,
            "--now", "2026-08-20T10:01:00Z", ok=False,
        )
        existing_control = self.run_cli(
            "control", "--repo-root", self.root, "--run-id", run_id,
            "--request-file", request_path, ok=False,
        )
        for rejected in (existing_init, existing_control):
            self.assertEqual(rejected.returncode, 2)
            self.assertEqual(rejected.stdout, "")
        self.assertEqual(self.direct_state_path(run_id).read_bytes(), before)
        self.run_id = owner["run_id"]
        progress = self.progress(issue=73, now="2026-08-20T10:01:00Z")
        self.assertEqual(progress["action"], "continue")
        finished = self.finish(
            1, self.merged_result(73), issue=73, now="2026-08-20T10:02:00Z",
        )
        self.assertEqual(finished["state"], "merged")

    def test_direct_discovery_rejects_malformed_and_ambiguous_history_without_rewrite(self):
        owner = self.acquire_direct()
        first_dir = self.workflows_dir / owner["run_id"]
        first_state = json.loads((first_dir / "state.json").read_text())
        second_dir = self.workflows_dir / "direct-73-000002"
        second_dir.mkdir()
        (second_dir / "state.lock").write_bytes(b"")
        second_state = copy.deepcopy(first_state)
        second_state["run_id"] = "direct-73-000002"
        (second_dir / "state.json").write_text(
            json.dumps(second_state, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        snapshots = {
            path: path.read_bytes()
            for path in (first_dir / "state.json", second_dir / "state.json")
        }
        ambiguous = self.direct_owner_raw(ok=False)
        self.assertIn("nonterminal", ambiguous.stderr)
        self.assertEqual({path: path.read_bytes() for path in snapshots}, snapshots)
        malformed = self.workflows_dir / "direct-73-bad"
        malformed.mkdir()
        rejected = self.direct_owner_raw(ok=False)
        self.assertIn("malformed", rejected.stderr)
        self.assertEqual({path: path.read_bytes() for path in snapshots}, snapshots)

    def test_concurrent_first_direct_calls_create_one_run_and_one_attempt(self):
        request_path = self.root / "concurrent-direct.json"
        candidate = os.path.abspath(self.root / "worktree-issue-73")
        request_path.write_text(json.dumps(self.direct_request(
            tracker=self.tracker_fact(73),
            worktree=self.worktree_fact(73, candidate={
                "path": candidate, "state": "absent",
            }),
        )), encoding="utf-8")
        wrapper = (
            "import os,sys; fd=int(sys.argv[1]); os.read(fd,1); "
            "os.execv(sys.executable,[sys.executable,*sys.argv[2:]])"
        )
        processes = []
        writers = []
        for _ in range(2):
            reader, writer = os.pipe()
            process = subprocess.Popen(
                [sys.executable, "-c", wrapper, str(reader), str(SCRIPT),
                 "direct-owner", "--repo-root", str(self.root),
                 "--request-file", str(request_path)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                pass_fds=(reader,),
            )
            os.close(reader)
            processes.append(process)
            writers.append(writer)
        for writer in writers:
            os.write(writer, b"x")
            os.close(writer)
        completed = [process.communicate() + (process.wait(),) for process in processes]
        self.assertEqual(sorted(item[2] for item in completed), [0, 2])
        successful = [json.loads(stdout) for stdout, _, code in completed if code == 0]
        self.assertEqual(len(successful), 1)
        self.assertEqual(successful[0]["run_id"], "direct-73-000001")
        runs = sorted(path.name for path in self.workflows_dir.iterdir()
                      if path.name.startswith("direct-73-") and path.is_dir())
        self.assertEqual(runs, ["direct-73-000001"])
        state = json.loads(self.direct_state_path(runs[0]).read_text())
        self.assertEqual(len(state["issues"]["73"]["attempts"]), 1)
        self.assertEqual(len(state["issues"]["73"]["attempts"][0]["launches"]), 1)

    def test_direct_discovery_rejects_every_unsafe_retained_entry(self):
        owner = self.acquire_direct()
        valid_state = self.direct_state_path(owner["run_id"]).read_bytes()

        def materialize(root, *, directory="real", issue_lock="missing",
                        lock="file", state="file", state_bytes=valid_state):
            workflows = root / ".superpowers" / "workflows"
            workflows.mkdir(parents=True)
            if issue_lock == "symlink":
                target = root / "issue-lock-target"
                target.write_bytes(b"external issue lock sentinel")
                (workflows / ".direct-73.lock").symlink_to(target)
            elif issue_lock == "directory":
                (workflows / ".direct-73.lock").mkdir()
            run = workflows / "direct-73-000001"
            if directory == "file":
                run.write_bytes(b"claimed namespace sentinel")
                return
            if directory == "symlink":
                target = root / "run-target"
                target.mkdir()
                run.symlink_to(target, target_is_directory=True)
                return
            run.mkdir()
            if lock == "file":
                (run / "state.lock").write_bytes(b"")
            elif lock == "symlink":
                target = root / "lock-target"
                target.write_bytes(b"")
                (run / "state.lock").symlink_to(target)
            if state == "file":
                (run / "state.json").write_bytes(state_bytes)
            elif state == "symlink":
                target = root / "state-target"
                target.write_bytes(state_bytes)
                (run / "state.json").symlink_to(target)

        wrong_issue = json.loads(valid_state)
        issue_state = wrong_issue["issues"].pop("73")
        issue_state["issue"] = 74
        for attempt in issue_state["attempts"]:
            attempt["issue"] = 74
            attempt["owner"] = attempt["owner"].replace("73:", "74:")
            for launch in attempt["launches"]:
                launch["owner"] = launch["owner"].replace("73:", "74:")
        wrong_issue["issues"]["74"] = issue_state
        wrong_bytes = (json.dumps(
            wrong_issue, sort_keys=True, separators=(",", ":")
        ) + "\n").encode()
        cases = {
            "regular-file run entry": {"directory": "file"},
            "symlink directory": {"directory": "symlink"},
            "symlink issue lock": {"issue_lock": "symlink"},
            "non-regular issue lock": {"issue_lock": "directory"},
            "missing lock": {"lock": "missing"},
            "symlink lock": {"lock": "symlink"},
            "missing state": {"state": "missing"},
            "symlink state": {"state": "symlink"},
            "corrupt state": {"state_bytes": b"{not-json\n"},
            "wrong issue": {"state_bytes": wrong_bytes},
        }
        for label, kwargs in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                materialize(root, **kwargs)
                before = {
                    path: path.read_bytes()
                    for path in root.rglob("state.json") if path.is_file()
                }
                rejected = self.direct_owner_at_root(
                    root, self.direct_request(), ok=False,
                )
                self.assertEqual(rejected.returncode, 2)
                self.assertEqual(rejected.stdout, "")
                if label == "symlink issue lock":
                    self.assertEqual(
                        (root / "issue-lock-target").read_bytes(),
                        b"external issue lock sentinel",
                    )
                self.assertEqual(
                    {path: path.read_bytes() for path in before}, before,
                )

    def test_direct_discovery_adopts_an_empty_retained_run_as_nonterminal(self):
        run_id = "direct-73-000001"
        run = self.workflows_dir / run_id
        run.mkdir(parents=True)
        (run / "state.lock").write_bytes(b"")
        state = {
            "schema_version": 1, "run_id": run_id,
            "created_at": "2026-08-20T10:00:00Z",
            "updated_at": "2026-08-20T10:00:00Z",
            "issues": {"73": {"issue": 73, "attempts": [], "outcome": None}},
        }
        (run / "state.json").write_text(
            json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        first = self.direct_owner()
        self.assertEqual(first["run_id"], run_id)
        self.assertEqual(first["requirements"], [{"kind": "tracker"}])
        tracker = self.tracker_fact(73)
        second = self.direct_owner(tracker=tracker)
        self.assertEqual(second["run_id"], run_id)
        self.assertEqual(second["requirements"], [{"kind": "candidate_worktree"}])
        owner = self.direct_owner(
            tracker=tracker,
            worktree=self.worktree_fact(73, candidate={
                "path": os.path.abspath(self.root / "worktree-issue-73"),
                "state": "absent",
            }),
        )
        self.assertEqual((owner["run_id"], owner["attempt"], owner["launch_kind"]),
                         (run_id, 1, "spawn"))
        self.assertFalse((self.workflows_dir / "direct-73-000002").exists())

    def test_direct_discovery_rejects_nonterminal_below_newer_terminal(self):
        owner = self.acquire_direct()
        active = json.loads(self.direct_state_path(owner["run_id"]).read_text())
        terminal = copy.deepcopy(active)
        terminal["run_id"] = "direct-73-000002"
        terminal["updated_at"] = "2026-08-20T10:01:00Z"
        attempt = terminal["issues"]["73"]["attempts"][0]
        result = self.merged_result(73)
        attempt.update({
            "state": "merged", "result": result,
            "finished_at": "2026-08-20T10:01:00Z", "result_source": "owner",
        })
        terminal["issues"]["73"]["outcome"] = copy.deepcopy(result)
        second = self.workflows_dir / "direct-73-000002"
        second.mkdir()
        (second / "state.lock").write_bytes(b"")
        (second / "state.json").write_text(
            json.dumps(terminal, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        snapshots = {
            path: path.read_bytes()
            for path in (
                self.direct_state_path("direct-73-000001"),
                self.direct_state_path("direct-73-000002"),
            )
        }
        rejected = self.direct_owner_raw(ok=False)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("newer terminal", rejected.stderr)
        self.assertEqual({path: path.read_bytes() for path in snapshots}, snapshots)

    def test_direct_sequence_exhaustion_fails_without_overwriting_terminal_history(self):
        owner = self.acquire_direct()
        self.run_id = owner["run_id"]
        self.finish(1, self.merged_result(73), issue=73,
                    now="2026-08-20T10:01:00Z")
        source = self.workflows_dir / owner["run_id"]
        exhausted = self.workflows_dir / "direct-73-999999"
        source.rename(exhausted)
        state_path = exhausted / "state.json"
        state = json.loads(state_path.read_text())
        state["run_id"] = "direct-73-999999"
        state_path.write_text(
            json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        before = state_path.read_bytes()
        rejected = self.direct_owner_raw(
            new_run=True, tracker=self.tracker_fact(73),
            worktree=self.worktree_fact(73, recorded={
                "path": owner["worktree"], "state": "matching_issue_branch",
            }), ok=False,
        )
        self.assertIn("exhaust", rejected.stderr)
        self.assertEqual(state_path.read_bytes(), before)

    def test_direct_authorization_flags_fail_when_not_applicable(self):
        for field in ("new_run", "owner_unavailable"):
            rejected = self.direct_owner_raw(
                request=self.direct_request(**{field: True}), ok=False,
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertEqual(rejected.stdout, "")
        owner = self.acquire_direct()
        state_path = self.direct_state_path(owner["run_id"])
        before = state_path.read_bytes()
        active_new = self.direct_owner_raw(new_run=True, ok=False)
        self.assertEqual(active_new.returncode, 2)
        self.assertEqual(state_path.read_bytes(), before)
        self.run_id = owner["run_id"]
        self.finish(1, self.merged_result(73), issue=73,
                    now="2026-08-20T10:01:00Z")
        before = state_path.read_bytes()
        terminal_takeover = self.direct_owner_raw(owner_unavailable=True, ok=False)
        self.assertEqual(terminal_takeover.returncode, 2)
        self.assertEqual(state_path.read_bytes(), before)

    def test_new_run_is_rejected_while_latest_attempt_is_suspended(self):
        owner = self.acquire_direct()
        self.run_id = owner["run_id"]
        self.suspend(
            issue=73, attempt=1, blocked_on="usage_limit",
            now="2026-08-20T10:30:00Z",
        )
        state_path = self.direct_state_path(owner["run_id"])
        before = state_path.read_bytes()
        refused = self.direct_owner_raw(
            now="2026-08-20T11:00:00Z", new_run=True,
            tracker=self.tracker_fact(73),
            worktree=self.worktree_fact(73, recorded={
                "path": owner["worktree"], "state": "matching_issue_branch",
            }),
            ok=False,
        )
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(refused.stdout, "")
        self.assertIn("suspended attempt is resumable", refused.stderr)
        self.assertEqual(state_path.read_bytes(), before)
        self.assertFalse((self.workflows_dir / "direct-73-000002").exists())

    def test_direct_owner_resumes_a_suspension_in_a_fresh_budget_window(self):
        owner = self.acquire_direct()
        self.run_id = owner["run_id"]
        self.suspend(
            issue=73, attempt=1, blocked_on="usage_limit",
            now="2026-08-20T10:30:00Z",
        )
        needed = self.direct_owner(now="2026-08-20T15:00:00Z")
        self.assertEqual(needed, {
            "interface_version": 1, "kind": "observe", "issue": 73,
            "run_id": owner["run_id"], "requirements": [{
                "kind": "recorded_worktree", "path": owner["worktree"],
            }],
        })
        resumed = self.direct_owner(
            now="2026-08-20T15:00:00Z",
            worktree=self.worktree_fact(73, recorded={
                "path": owner["worktree"], "state": "matching_issue_branch",
            }),
        )
        self.assertEqual(resumed, {
            **owner, "action_id": "73:1:2", "launch_kind": "resume",
            "deadline_at": "2026-08-20T18:00:00Z",
        })
        attempt = json.loads(
            self.direct_state_path(owner["run_id"]).read_text()
        )["issues"]["73"]["attempts"][-1]
        self.assertEqual(attempt["state"], "active")
        self.assertIsNone(attempt["blocked_on"])
        self.assertIsNone(attempt["result"])
        self.assertEqual((attempt["attempt"], attempt["prior_attempt"]), (1, None))
        self.assertEqual(attempt["started_at"], "2026-08-20T10:00:00Z")
        self.assertEqual(attempt["last_progress_at"], "2026-08-20T15:00:00Z")
        self.assertEqual(attempt["launches"], [
            {"kind": "fresh", "owner": "73:1", "worktree": owner["worktree"],
             "at": "2026-08-20T10:00:00Z"},
            {"kind": "resume", "owner": "73:1", "worktree": owner["worktree"],
             "at": "2026-08-20T15:00:00Z"},
        ])
        self.assertEqual((attempt["suspend_phase"], attempt["stalled_resumes"]),
                         (0, 0))
        self.assertFalse(self.direct_state_path("direct-73-000002").exists())
        # The window is fresh, not merely restated: the resumed owner can work.
        self.assertEqual(
            self.progress(issue=73, now="2026-08-20T15:30:00Z")["action"],
            "continue",
        )

    def test_second_reentry_over_the_resumed_attempt_refuses_without_mutation(self):
        owner = self.acquire_direct()
        self.run_id = owner["run_id"]
        self.suspend(
            issue=73, attempt=1, blocked_on="transport",
            now="2026-08-20T10:30:00Z",
        )
        matching = self.worktree_fact(73, recorded={
            "path": owner["worktree"], "state": "matching_issue_branch",
        })
        self.direct_owner(now="2026-08-20T11:00:00Z", worktree=matching)
        state_path = self.direct_state_path(owner["run_id"])
        before = state_path.read_bytes()
        again = self.direct_owner_raw(
            now="2026-08-20T11:05:00Z", worktree=matching, ok=False,
        )
        self.assertEqual(again.returncode, 2)
        self.assertEqual(again.stdout, "")
        self.assertIn("direct run has an active owner", again.stderr)
        self.assertEqual(state_path.read_bytes(), before)

    def test_owner_unavailable_is_not_applicable_to_a_suspended_attempt(self):
        owner = self.acquire_direct()
        self.run_id = owner["run_id"]
        self.suspend(
            issue=73, attempt=1, blocked_on="human_gate",
            now="2026-08-20T10:30:00Z",
        )
        state_path = self.direct_state_path(owner["run_id"])
        before = state_path.read_bytes()
        refused = self.direct_owner_raw(
            now="2026-08-20T11:00:00Z", owner_unavailable=True,
            worktree=self.worktree_fact(73, recorded={
                "path": owner["worktree"], "state": "matching_issue_branch",
            }),
            ok=False,
        )
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(refused.stdout, "")
        self.assertIn("owner_unavailable is not applicable", refused.stderr)
        self.assertEqual(state_path.read_bytes(), before)

    def test_phase_zero_suspension_resumes_its_exact_absent_reservation(self):
        owner = self.acquire_direct()
        self.run_id = owner["run_id"]
        self.suspend(
            issue=73, attempt=1, blocked_on="usage_limit",
            now="2026-08-20T10:05:00Z",
        )
        alternate = os.path.abspath(self.root / "alternate-worktree-73")
        resumed = self.direct_owner(
            now="2026-08-20T10:06:00Z",
            worktree=self.worktree_fact(
                73,
                recorded={"path": owner["worktree"], "state": "absent"},
                candidate={"path": alternate, "state": "absent"},
            ),
        )
        self.assertEqual(resumed, {
            **owner, "action_id": "73:1:2", "launch_kind": "resume",
            "deadline_at": "2026-08-20T13:06:00Z",
        })
        persisted = json.loads(
            self.direct_state_path(owner["run_id"]).read_text()
        )["issues"]["73"]
        self.assertEqual(len(persisted["attempts"]), 1)
        self.assertEqual(persisted["attempts"][0]["worktree"], owner["worktree"])

    def test_direct_new_run_records_the_prior_run_link(self):
        owner = self.acquire_direct(issue=31)
        self.run_id = owner["run_id"]
        self.finish(
            1,
            {
                **self.merged_result(31), "state": "stopped", "pr_url": None,
                "merge_sha": None, "issue_closed": False,
                "notes": "semantic stop",
            },
            issue=31, now="2026-08-20T10:05:00Z",
        )
        tracker = self.tracker_fact(31)
        renewed = self.direct_owner(
            issue=31, new_run=True, now="2026-08-20T10:10:00Z", tracker=tracker,
            worktree=self.worktree_fact(31, recorded={
                "path": owner["worktree"], "state": "matching_issue_branch",
            }),
        )
        self.assertEqual(renewed["kind"], "owner")
        self.assertEqual(renewed["run_id"], "direct-31-000002")
        successor = json.loads(
            self.direct_state_path(renewed["run_id"]).read_text()
        )
        self.assertEqual(successor["prior_run"], owner["run_id"])
        predecessor = json.loads(
            self.direct_state_path(owner["run_id"]).read_text()
        )
        self.assertIsNone(predecessor["prior_run"])

    def test_merged_forge_observation_reconciles_before_ownership(self):
        owner = self.acquire_direct(issue=32)
        self.run_id = owner["run_id"]
        self.suspend(
            issue=32, attempt=1, blocked_on="human_gate",
            now="2026-08-20T10:30:00Z",
        )
        reconciled = self.direct_owner(
            issue=32, now="2026-08-20T11:00:00Z",
            worktree=self.worktree_fact(32, recorded={
                "path": owner["worktree"], "state": "matching_issue_branch",
            }),
            forge={
                "state": "merged",
                "url": "https://github.com/fagenorn/nix-config/pull/78",
                "merge_sha": "f3fac95aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            },
        )
        state = json.loads(self.direct_state_path(owner["run_id"]).read_text())
        attempt = state["issues"]["32"]["attempts"][-1]
        self.assertEqual(reconciled, {
            "interface_version": 1, "kind": "terminal", "issue": 32,
            "run_id": owner["run_id"], "source": "lifecycle", "reason": "merged",
            "blockers": [], "result": attempt["result"],
            "reentry": "/from-issue 32 --auto",
        })
        self.assertEqual(attempt["state"], "merged")
        self.assertEqual(attempt["result_source"], "superseded")
        self.assertIsNone(attempt["blocked_on"])
        self.assertEqual(attempt["finished_at"], "2026-08-20T11:00:00Z")
        self.assertEqual(attempt["result"], {
            "issue": 32, "state": "merged",
            "pr_url": "https://github.com/fagenorn/nix-config/pull/78",
            "merge_sha": "f3fac95aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "issue_closed": False, "discussion_items": [],
            "detail_state": "none", "report_path": None,
            "notes": "reconciled from forge observation",
        })
        self.assertEqual(state["issues"]["32"]["outcome"], attempt["result"])
        # The reconciled record is terminal: a later re-entry replays it.
        self.assertEqual(
            self.direct_owner(issue=32, now="2026-08-20T11:05:00Z"), reconciled
        )

    def test_merged_forge_reconcile_preserves_the_superseded_owner_detail(self):
        # A merged pull request is ground truth and supersedes an owner's own
        # failed verdict (per D3), but the owner's durable delivery pointer is
        # the only record of what was reported and must survive the supersede.
        owner = self.acquire_direct(issue=38)
        self.run_id = owner["run_id"]
        report_path = ".superpowers/issue-delivery/38/run-1/ship-review.json"
        owner_result = {
            "issue": 38, "state": "failed", "pr_url": None, "merge_sha": None,
            "issue_closed": False, "discussion_items": [],
            "detail_state": "present", "report_path": report_path,
            "notes": f"owner verdict; details: {report_path}",
        }
        state = self.read_state()
        issue_state = state["issues"]["38"]
        attempt = issue_state["attempts"][-1]
        attempt.update({
            "state": "failed", "blocked_on": None,
            "result": copy.deepcopy(owner_result),
            "finished_at": "2026-08-20T10:30:00Z",
            "result_source": "owner",
        })
        issue_state["outcome"] = copy.deepcopy(owner_result)
        state["updated_at"] = "2026-08-20T10:30:00Z"
        self.write_state(state)

        reconciled = self.direct_owner(
            issue=38, now="2026-08-20T11:00:00Z",
            worktree=self.worktree_fact(38, recorded={
                "path": owner["worktree"], "state": "matching_issue_branch",
            }),
            forge={
                "state": "merged",
                "url": "https://github.com/fagenorn/nix-config/pull/81",
                "merge_sha": "c7c7c7c7c7c7c7c7c7c7c7c7c7c7c7c7c7c7c7c7",
            },
        )
        self.assertEqual((reconciled["kind"], reconciled["reason"]),
                         ("terminal", "merged"))
        persisted = json.loads(
            self.direct_state_path(owner["run_id"]).read_text()
        )["issues"]["38"]
        attempt = persisted["attempts"][-1]
        self.assertEqual(attempt["state"], "merged")
        self.assertEqual(attempt["result_source"], "superseded")
        result = attempt["result"]
        self.assertEqual(result["state"], "merged")
        self.assertEqual(
            result["merge_sha"],
            "c7c7c7c7c7c7c7c7c7c7c7c7c7c7c7c7c7c7c7c7",
        )
        self.assertEqual(
            result["pr_url"], "https://github.com/fagenorn/nix-config/pull/81"
        )
        # The owner's delivery pointer is carried forward, not nulled.
        self.assertEqual(result["report_path"], report_path)
        self.assertEqual(result["detail_state"], "present")
        # The note records that a prior owner verdict was superseded.
        self.assertIn("reconciled from forge observation", result["notes"])
        self.assertIn("superseded", result["notes"])
        self.assertIn("owner", result["notes"])
        self.assertIn("failed", result["notes"])
        self.assertLessEqual(len(result["notes"]), 500)
        self.assertEqual(persisted["outcome"], result)
        self.assertEqual(reconciled["result"], result)

    def test_merged_forge_reconcile_over_synthetic_record_keeps_no_detail(self):
        # The common case is untouched: reconciling over a synthetic reaper
        # record (no owner report, no delivery pointer) still yields the bare
        # forge observation with no report_path and an unchanged note.
        owner = self.acquire_direct(issue=39)
        self.run_id = owner["run_id"]
        self.legacy_expiry_record(issue=39, now="2026-08-20T13:00:00Z")
        reconciled = self.direct_owner(
            issue=39, now="2026-08-20T13:30:00Z",
            forge={
                "state": "merged",
                "url": "https://github.com/fagenorn/nix-config/pull/82",
                "merge_sha": "d8d8d8d8d8d8d8d8d8d8d8d8d8d8d8d8d8d8d8d8",
            },
        )
        persisted = json.loads(
            self.direct_state_path(owner["run_id"]).read_text()
        )["issues"]["39"]
        result = persisted["attempts"][-1]["result"]
        self.assertEqual(result, {
            "issue": 39, "state": "merged",
            "pr_url": "https://github.com/fagenorn/nix-config/pull/82",
            "merge_sha": "d8d8d8d8d8d8d8d8d8d8d8d8d8d8d8d8d8d8d8d8",
            "issue_closed": False, "discussion_items": [],
            "detail_state": "none", "report_path": None,
            "notes": "reconciled from forge observation",
        })
        self.assertEqual(persisted["outcome"], result)
        self.assertEqual(reconciled["result"], result)

    def test_merged_forge_reconciles_a_stale_record_instead_of_retrying(self):
        owner = self.acquire_direct(issue=34)
        self.run_id = owner["run_id"]
        self.legacy_expiry_record(issue=34, now="2026-08-20T13:00:00Z")
        reconciled = self.direct_owner(
            issue=34, now="2026-08-20T13:30:00Z",
            forge={
                "state": "merged",
                "url": "https://github.com/fagenorn/nix-config/pull/79",
                "merge_sha": "b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1",
            },
        )
        self.assertEqual((reconciled["kind"], reconciled["reason"]),
                         ("terminal", "merged"))
        persisted = json.loads(
            self.direct_state_path(owner["run_id"]).read_text()
        )["issues"]["34"]
        self.assertEqual(len(persisted["attempts"]), 1)
        attempt = persisted["attempts"][-1]
        self.assertEqual(attempt["state"], "merged")
        self.assertEqual(attempt["result_source"], "superseded")
        self.assertEqual(
            attempt["result"]["merge_sha"],
            "b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1",
        )
        self.assertEqual(persisted["outcome"], attempt["result"])
        # A reconciled record is a verdict: no owner may overwrite it.
        rejected = self.finish(
            1, self.merged_result(34), issue=34,
            now="2026-08-20T14:00:00Z", ok=False,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("conflicting terminal result", rejected.stderr)

    def test_open_or_closed_forge_leaves_the_ladder_unchanged(self):
        for index, forge_state in enumerate(("open", "closed")):
            issue = 35 + index
            with self.subTest(forge_state=forge_state):
                owner = self.acquire_direct(issue=issue)
                self.run_id = owner["run_id"]
                self.suspend(
                    issue=issue, attempt=1, blocked_on="usage_limit",
                    now="2026-08-20T10:30:00Z",
                )
                resumed = self.direct_owner(
                    issue=issue, now="2026-08-20T11:00:00Z",
                    worktree=self.worktree_fact(issue, recorded={
                        "path": owner["worktree"],
                        "state": "matching_issue_branch",
                    }),
                    forge={
                        "state": forge_state,
                        "url": "https://github.com/fagenorn/nix-config/pull/80",
                        "merge_sha": None,
                    },
                )
                self.assertEqual((resumed["kind"], resumed["launch_kind"]),
                                 ("owner", "resume"))
                attempt = json.loads(
                    self.direct_state_path(owner["run_id"]).read_text()
                )["issues"][str(issue)]["attempts"][-1]
                self.assertEqual(attempt["state"], "active")
                self.assertIsNone(attempt["result"])

    def test_unobserved_forge_yields_a_forge_pr_requirement(self):
        # The tracker rung comes first: a closed or blocked issue ends the
        # request without anyone reading the forge.
        self.assertEqual(
            self.direct_owner(
                issue=33, now="2026-08-20T10:00:00Z", forge=None,
            )["requirements"],
            [{"kind": "tracker"}],
        )
        needed = self.direct_owner(
            issue=33, now="2026-08-20T10:00:00Z",
            tracker=self.tracker_fact(33), forge=None,
        )
        self.assertEqual(needed, {
            "interface_version": 1, "kind": "observe", "issue": 33,
            "run_id": "direct-33-000001",
            "requirements": [{"kind": "forge_pr", "path": "issue-33-"}],
        })
        self.assertFalse((self.workflows_dir / "direct-33-000001").exists())
        # An observed forge without a pull request continues the ladder.
        self.assertEqual(
            self.direct_owner(
                issue=33, now="2026-08-20T10:00:00Z",
                tracker=self.tracker_fact(33),
            )["requirements"],
            [{"kind": "candidate_worktree"}],
        )

    def test_direct_terminal_replay_is_canonical_for_merged_and_owner_stopped(self):
        merged_owner = self.acquire_direct(issue=73)
        self.run_id = merged_owner["run_id"]
        merged = self.finish(1, self.merged_result(73), issue=73,
                             now="2026-08-20T10:01:00Z")
        first = self.direct_owner_raw(issue=73, now="2026-08-20T10:02:00Z")
        second = self.direct_owner_raw(issue=73, now="2026-08-20T10:03:00Z")
        self.assertEqual(first.stdout, second.stdout)
        self.assertTrue(first.stdout.endswith("\n"))
        merged_terminal = json.loads(first.stdout)
        self.assertEqual(merged_terminal, {
            "interface_version": 1, "kind": "terminal", "issue": 73,
            "run_id": merged_owner["run_id"], "source": "lifecycle",
            "reason": "merged", "blockers": [], "result": merged,
            "reentry": "/from-issue 73 --auto",
        })

        stopped_owner = self.acquire_direct(issue=74)
        self.run_id = stopped_owner["run_id"]
        stopped_result = {
            **self.merged_result(74), "state": "stopped", "pr_url": None,
            "merge_sha": None, "issue_closed": False, "notes": "content stop",
        }
        stopped = self.finish(1, stopped_result, issue=74,
                              now="2026-08-20T10:01:00Z")
        stopped_terminal = self.direct_owner(issue=74,
                                             now="2026-08-20T10:02:00Z")
        self.assertEqual(stopped_terminal, {
            "interface_version": 1, "kind": "terminal", "issue": 74,
            "run_id": stopped_owner["run_id"], "source": "lifecycle",
            "reason": "stopped", "blockers": [], "result": stopped,
            "reentry": "/from-issue 74 --auto",
        })

    def test_direct_and_control_project_the_same_one_issue_retry_policy(self):
        control_worktree = os.path.abspath(self.root / "control-worktree-14")
        self.init_run(now="2026-08-20T10:00:00Z")
        control_first = self.spawn(
            issue=14, worktree=control_worktree,
            now="2026-08-20T10:00:00Z", budget_minutes=180,
        )
        self.fail_owner(issue=14, attempt=1, now="2026-08-20T10:10:00Z")
        control_retry = self.retry(
            issue=14, worktree=control_worktree,
            now="2026-08-20T10:11:00Z", budget_minutes=180,
        )

        direct_worktree = os.path.abspath(self.root / "direct-worktree-73")
        direct_first = self.acquire_direct(issue=73, worktree=direct_worktree)
        self.run_id = direct_first["run_id"]
        self.fail_owner(issue=73, attempt=1, now="2026-08-20T10:10:00Z")
        direct_retry = self.direct_owner(
            now="2026-08-20T10:11:00Z", tracker=self.tracker_fact(73),
            worktree=self.worktree_fact(73, recorded={
                "path": direct_worktree, "state": "matching_issue_branch",
            }),
        )
        self.assertEqual(control_first["deadline_at"], direct_first["deadline_at"])
        self.assertEqual(control_retry["attempt"], direct_retry["attempt"])
        self.assertEqual(control_retry["deadline_at"], direct_retry["deadline_at"])
        self.assertEqual(control_retry["kind"], direct_retry["launch_kind"])
        self.assertEqual(control_retry["worktree"], control_worktree)
        self.assertEqual(direct_retry["worktree"], direct_worktree)

    def test_expiry_demotes_active_attempt_to_suspended(self):
        self.init_run()
        worktree = str(Path(self.root) / "wt-14")
        self.spawn(issue=14, worktree=worktree, budget_minutes=10)
        response = self.expire(issue=14, worktree=worktree, now="2026-08-13T20:10:00Z")
        self.assertEqual(response["deltas"], [
            {"issue": 14, "attempt": 1, "kind": "expired", "state": "suspended"},
        ])
        state = self.read_state()
        attempt = state["issues"]["14"]["attempts"][-1]
        self.assertEqual(attempt["state"], "suspended")
        self.assertEqual(attempt["blocked_on"], "unknown")
        self.assertIsNone(attempt["result"])
        self.assertIsNone(attempt["finished_at"])
        self.assertIsNone(attempt["result_source"])
        self.assertIsNone(state["issues"]["14"]["outcome"])

    def test_suspend_subcommand_records_blocked_on_and_reentry(self):
        self.init_run()
        worktree = str(Path(self.root) / "wt-15")
        self.spawn(issue=15, worktree=worktree, budget_minutes=10)
        envelope = self.suspend(
            issue=15, attempt=1, blocked_on="usage_limit",
            now="2026-08-13T20:05:00Z",
        )
        self.assertEqual(envelope, {
            "interface_version": 2, "kind": "suspended", "run_id": self.run_id,
            "issue": 15, "custody": {"kind": "implementation", "attempt": 1,
                                     "launch": 1, "action_id": "15:1:1"},
            "blocked_on": "usage_limit", "reentry": "/from-issue 15 --auto",
        })
        attempt = self.read_state()["issues"]["15"]["attempts"][-1]
        self.assertEqual(attempt["state"], "suspended")
        self.assertEqual(attempt["blocked_on"], "usage_limit")
        self.assertEqual(attempt["suspend_phase"], 0)
        self.assertEqual(attempt["stalled_resumes"], 0)
        self.assertIsNone(attempt["result"])

    def test_third_stalled_suspension_escalates_to_synthetic_stop(self):
        self.init_run()
        worktree = str(Path(self.root) / "wt-16")
        self.spawn(issue=16, worktree=worktree, budget_minutes=10)
        for index in range(3):
            envelope = self.suspend(
                issue=16, attempt=1, blocked_on="usage_limit",
                now=f"2026-08-13T20:0{2 * index + 1}:00Z",
            )
            self.assertEqual((envelope["kind"], envelope["custody"]["launch"]),
                             ("suspended", index + 1))
            self.assertEqual(
                self.read_state()["issues"]["16"]["attempts"][-1]["stalled_resumes"], index)
            self.resume(
                issue=16, worktree=worktree,
                now=f"2026-08-13T20:0{2 * index + 2}:00Z",
            )
        final = self.suspend(
            issue=16, attempt=1, blocked_on="usage_limit",
            now="2026-08-13T20:08:00Z",
        )
        persisted = self.read_state()["issues"]["16"]
        attempt = persisted["attempts"][-1]
        self.assertEqual(attempt["state"], "stopped")
        self.assertEqual(attempt["result_source"], "stalled")
        self.assertIsNone(attempt["blocked_on"])
        self.assertIn("stalled without phase progress", attempt["result"]["notes"])
        self.assertEqual(persisted["outcome"], attempt["result"])
        self.assertEqual(final, {
            "interface_version": 2, "kind": "terminal", "issue": 16,
            "run_id": self.run_id, "source": "lifecycle", "reason": "stopped",
            "blockers": [], "result": attempt["result"],
            "reentry": "/from-issue 16 --auto",
        })

    def test_suspend_rejects_a_nonactive_attempt_and_the_reserved_cause(self):
        self.init_run()
        worktree = str(Path(self.root) / "wt-18")
        self.spawn(issue=18, worktree=worktree, budget_minutes=10)
        self.suspend(
            issue=18, attempt=1, blocked_on="transport",
            now="2026-08-13T20:02:00Z",
        )
        before = self.state_path.read_bytes()
        repeated = self.suspend(
            issue=18, attempt=1, blocked_on="transport",
            now="2026-08-13T20:03:00Z", ok=False,
        )
        self.assertNotEqual(repeated.returncode, 0)
        self.assertIn("only an active attempt can suspend", repeated.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

        reserved = self.suspend(
            issue=18, attempt=1, blocked_on="unknown",
            now="2026-08-13T20:04:00Z", ok=False,
        )
        self.assertNotEqual(reserved.returncode, 0)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_agent_dispatch_suspension_parks_the_attempt_without_spending_it(self):
        # A context that cannot launch the agents a phase needs is an
        # environmental pause with its own owner-reported cause, never a
        # terminal verdict: the attempt stays resumable and is not consumed
        # (per D6).
        self.init_run()
        worktree = str(Path(self.root) / "wt-19")
        self.spawn(issue=19, worktree=worktree, budget_minutes=10)
        envelope = self.suspend(
            issue=19, attempt=1, blocked_on="agent_dispatch",
            now="2026-08-13T20:05:00Z",
        )
        self.assertEqual(envelope, {
            "interface_version": 2, "kind": "suspended", "run_id": self.run_id,
            "issue": 19, "custody": {"kind": "implementation", "attempt": 1,
                                     "launch": 1, "action_id": "19:1:1"},
            "blocked_on": "agent_dispatch", "reentry": "/from-issue 19 --auto",
        })
        issue = self.read_state()["issues"]["19"]
        self.assertEqual([attempt["attempt"] for attempt in issue["attempts"]], [1])
        attempt = issue["attempts"][-1]
        self.assertEqual(attempt["state"], "suspended")
        self.assertEqual(attempt["blocked_on"], "agent_dispatch")
        self.assertEqual(attempt["stalled_resumes"], 0)
        self.assertIsNone(attempt["result"])
        self.assertIsNone(attempt["finished_at"])
        self.assertIsNone(attempt["result_source"])
        self.assertIsNone(issue["outcome"])

    def test_agent_dispatch_suspension_waits_for_a_human_directed_sweep(self):
        # The ledger cannot see how deep a relaunch would run, so a sweep that
        # did not name the issue leaves it parked; a sweep that named it
        # resumes it like any human-directed re-entry (per D6).
        self.init_run()
        worktree = str(Path(self.root) / "wt-48")
        self.spawn(issue=48, worktree=worktree, budget_minutes=10)
        self.suspend(
            issue=48, attempt=1, blocked_on="agent_dispatch",
            now="2026-08-13T20:05:00Z",
        )
        observed = [self.worktree_fact(48, recorded={
            "path": os.path.abspath(worktree), "state": "matching_issue_branch",
        })]
        parked = self.state_path.read_bytes()
        swept = self.control(
            now="2026-08-13T20:06:00Z", issues=[48],
            tracker=[self.tracker_fact(48)], worktrees=observed,
            human_directed=False,
        )
        self.assert_control_response_shape(swept)
        self.assertEqual([a for a in swept["actions"] if a["kind"] == "resume"], [])
        self.assertEqual(swept["actions"][-1], {"id": "finalize", "kind": "finalize"})
        self.assertEqual(swept["deltas"], [])
        summary = next(s for s in swept["summaries"] if s["issue"] == 48)
        self.assertEqual((summary["state"], summary["blocked_on"]),
                         ("suspended", "agent_dispatch"))
        self.assert_controller_finalized(parked, now="2026-08-13T20:06:00Z")  # per D20

        directed = self.control(
            now="2026-08-13T20:07:00Z", issues=[48],
            tracker=[self.tracker_fact(48)], worktrees=observed,
            human_directed=True,
        )
        self.assert_control_response_shape(directed)
        self.assertIn(("resume", 48), [(a["kind"], a.get("issue"))
                                       for a in directed["actions"]])
        attempt = self.read_state()["issues"]["48"]["attempts"][-1]
        self.assertEqual((attempt["state"], attempt["blocked_on"]), ("active", None))
        # The directed sweep resumes the same attempt; none is consumed (per D15).
        self.assertEqual(
            [a["attempt"] for a in self.read_state()["issues"]["48"]["attempts"]], [1])

    def test_direct_reentry_resumes_an_agent_dispatch_suspension_in_place(self):
        # A direct owner always carries human_directed, so `/from-issue N
        # --auto` clears `agent_dispatch` on the same attempt and worktree,
        # opening no second attempt and no second run (per D6).
        owner = self.acquire_direct()
        self.run_id = owner["run_id"]
        self.suspend(
            issue=73, attempt=1, blocked_on="agent_dispatch",
            now="2026-08-20T10:30:00Z",
        )
        resumed = self.direct_owner(
            now="2026-08-20T15:00:00Z",
            worktree=self.worktree_fact(73, recorded={
                "path": owner["worktree"], "state": "matching_issue_branch",
            }),
        )
        self.assertEqual(resumed, {
            **owner, "action_id": "73:1:2", "launch_kind": "resume",
            "deadline_at": "2026-08-20T18:00:00Z",
        })
        issue = json.loads(
            self.direct_state_path(owner["run_id"]).read_text()
        )["issues"]["73"]
        self.assertEqual([attempt["attempt"] for attempt in issue["attempts"]], [1])
        attempt = issue["attempts"][-1]
        self.assertEqual(attempt["state"], "active")
        self.assertIsNone(attempt["blocked_on"])
        self.assertIsNone(attempt["result"])
        self.assertIsNone(attempt["prior_attempt"])
        self.assertFalse(self.direct_state_path("direct-73-000002").exists())

    def test_deadline_suspension_parks_the_attempt_without_spending_it(self):
        # An owner that stops cleanly at an sdd task boundary before its
        # deadline parks the attempt like any environmental pause: it stays
        # resumable and is not consumed (#281 D2).
        self.init_run()
        worktree = str(Path(self.root) / "wt-21")
        self.spawn(issue=21, worktree=worktree, budget_minutes=10)
        envelope = self.suspend(
            issue=21, attempt=1, blocked_on="deadline",
            now="2026-08-13T20:05:00Z",
        )
        self.assertEqual(envelope, {
            "interface_version": 2, "kind": "suspended", "run_id": self.run_id,
            "issue": 21, "custody": {"kind": "implementation", "attempt": 1,
                                     "launch": 1, "action_id": "21:1:1"},
            "blocked_on": "deadline", "reentry": "/from-issue 21 --auto",
        })
        issue = self.read_state()["issues"]["21"]
        self.assertEqual([attempt["attempt"] for attempt in issue["attempts"]], [1])
        attempt = issue["attempts"][-1]
        self.assertEqual(attempt["state"], "suspended")
        self.assertEqual(attempt["blocked_on"], "deadline")
        self.assertEqual(attempt["stalled_resumes"], 0)
        self.assertIsNone(attempt["result"])
        self.assertIsNone(attempt["finished_at"])
        self.assertIsNone(attempt["result_source"])
        self.assertIsNone(issue["outcome"])

    def test_a_label_sweep_resumes_a_deadline_suspension(self):
        # `deadline` is auto-resumable: a sweep that did not name the issue
        # (human_directed false) resumes it on the same attempt and worktree
        # (#281 D2).
        self.init_run()
        worktree = str(Path(self.root) / "wt-49")
        self.spawn(issue=49, worktree=worktree, budget_minutes=10)
        self.suspend(
            issue=49, attempt=1, blocked_on="deadline",
            now="2026-08-13T20:05:00Z",
        )
        observed = [self.worktree_fact(49, recorded={
            "path": os.path.abspath(worktree), "state": "matching_issue_branch",
        })]
        swept = self.control(
            now="2026-08-13T20:06:00Z", issues=[49],
            tracker=[self.tracker_fact(49)], worktrees=observed,
            human_directed=False,
        )
        self.assert_control_response_shape(swept)
        self.assertIn(("resume", 49), [(a["kind"], a.get("issue"))
                                       for a in swept["actions"]])
        issue = self.read_state()["issues"]["49"]
        self.assertEqual([a["attempt"] for a in issue["attempts"]], [1])
        attempt = issue["attempts"][-1]
        self.assertEqual((attempt["state"], attempt["blocked_on"]), ("active", None))
        self.assertEqual(attempt["worktree"], os.path.abspath(worktree))

    def test_direct_reentry_resumes_a_deadline_suspension_in_place(self):
        owner = self.acquire_direct()
        self.run_id = owner["run_id"]
        self.suspend(
            issue=73, attempt=1, blocked_on="deadline",
            now="2026-08-20T10:30:00Z",
        )
        resumed = self.direct_owner(
            now="2026-08-20T15:00:00Z",
            worktree=self.worktree_fact(73, recorded={
                "path": owner["worktree"], "state": "matching_issue_branch",
            }),
        )
        self.assertEqual(resumed, {
            **owner, "action_id": "73:1:2", "launch_kind": "resume",
            "deadline_at": "2026-08-20T18:00:00Z",
        })
        issue = json.loads(
            self.direct_state_path(owner["run_id"]).read_text()
        )["issues"]["73"]
        self.assertEqual([attempt["attempt"] for attempt in issue["attempts"]], [1])
        attempt = issue["attempts"][-1]
        self.assertEqual((attempt["state"], attempt["blocked_on"]), ("active", None))
        self.assertIsNone(attempt["prior_attempt"])

    def test_prior_schema_ledger_upgrades_on_load(self):
        self.init_run()
        worktree = str(Path(self.root) / "wt-17")
        self.spawn(issue=17, worktree=worktree, budget_minutes=10)
        state = self.read_state()
        current_version = state["schema_version"]
        self.write_state(self._as_legacy(state, current_version - 1))
        self.suspend(
            issue=17, attempt=1, blocked_on="external",
            now="2026-08-13T20:02:00Z",
        )
        upgraded = self.read_state()
        self.assertEqual(upgraded["schema_version"], current_version)
        self.assertIsNone(upgraded["prior_run"])
        latest = upgraded["issues"]["17"]["attempts"][-1]
        self.assertEqual(latest["stalled_resumes"], 0)
        self.assertEqual(latest["suspend_phase"], 0)
        self.assertEqual(latest["blocked_on"], "external")

    def test_schema_one_migrates_through_two_and_three_to_four_with_one_atomic_write(self):
        self._spawn_151()
        schema_one = self._as_legacy(self.read_state(), 1)
        original = copy.deepcopy(schema_one)
        workflow = load_source_module(SCRIPT, "workflow_state_schema_four_test")
        contract, _ = self.delivery_fixtures.contract_and_delivery(self.delivery_model)
        migrated = workflow.upgrade_state(
            schema_one, run_id=self.run_id, migration_contracts={151: contract}
        )
        self.assertEqual(schema_one, original)
        self.assertEqual(migrated["schema_version"], 7)
        self.assertEqual(workflow.validate_state(migrated, run_id=self.run_id), migrated)
        issue = migrated["issues"]["151"]
        self.assertEqual(issue["delivery_remainders"], [])
        empty = self.empty_delivery()
        empty["postconditions"] = issue["delivery"]["postconditions"]
        self.assertEqual(issue["delivery"], empty)

    def test_schema_one_and_two_mutations_write_only_final_schema_four_once(self):
        self._spawn_151()
        workflow = load_source_module(SCRIPT, "workflow_state_atomic_migration")
        baseline = self.read_state()
        for version in (1, 2):
            state = self._as_legacy(baseline, version)
            self.write_state(state)
            with mock.patch.object(workflow, "atomic_write_state") as write:
                value = workflow.transact(
                    str(self.root), self.run_id,
                    lambda current: (current, False), migration_contracts={},
                )
            self.assertEqual(state, self._as_legacy(baseline, version))
            self.assertEqual(value["schema_version"], 7)
            write.assert_called_once()
            self.assertEqual(write.call_args.args[2]["schema_version"], 7)

    def test_locked_loader_requires_keyword_migration_context(self):
        self.init_run()
        workflow = load_source_module(SCRIPT, "workflow_state_loader_context")
        with self.assertRaises(TypeError):
            workflow.read_locked_state(self.state_path, self.run_id, {})

    def test_legacy_terminal_and_active_rows_migrate_byte_exact(self):
        self._spawn_151()
        self.finish(1, self.merged_result(151), issue=151,
                    now="2026-08-13T20:02:00Z")
        self.spawn(issue=152, worktree=str(self.root / "wt-152"), budget_minutes=10,
                   now="2026-08-13T20:03:00Z")
        legacy = self.read_state()
        terminal = legacy["issues"]["151"]
        terminal["attempts"][0]["result"]["detail_state"] = "present"
        terminal["attempts"][0]["result"]["report_path"] = "/tmp/legacy-detail.md"
        terminal["outcome"]["detail_state"] = "present"
        terminal["outcome"]["report_path"] = "/tmp/legacy-detail.md"
        legacy = self._as_legacy(legacy, 2)
        legacy_rows = copy.deepcopy(legacy["issues"])
        workflow = load_source_module(SCRIPT, "workflow_state_legacy_rows")
        migrated = workflow.upgrade_state(legacy, run_id=self.run_id,
                                          migration_contracts={})
        self.assertEqual(migrated["schema_version"], 7)
        for key, legacy_issue in legacy_rows.items():
            migrated_issue = migrated["issues"][key]
            # Schemas 6 and 7 add keys to every attempt (#250 D4, #280 D3);
            # every legacy field still migrates byte-exact.
            attempts = copy.deepcopy(migrated_issue["attempts"])
            for attempt in attempts:
                self.assertIsNone(attempt.pop("progress_marker"))
                self.assertEqual(
                    (attempt.pop("lane"), attempt.pop("lane_budget_minutes"),
                     attempt.pop("lane_history")),
                    (None, None, []))
            self.assertEqual(
                {"issue": migrated_issue["issue"], "attempts": attempts,
                 "outcome": migrated_issue["outcome"]},
                legacy_issue,
            )
        self.assertEqual(workflow.validate_state(migrated, run_id=self.run_id), migrated)

    def test_malformed_legacy_current_launch_refuses_without_write(self):
        self._spawn_151()
        schema_three = self.read_state()
        valid = self._as_legacy(schema_three, 1)
        attempt = ("issues", "151", "attempts", 0)
        changes = [
            (("schema_version",), True), (("issues", "151", "issue"), 152),
            (attempt + ("owner",), 123), (attempt + ("launches",), []),
            (attempt + ("blocked_on",), None), (attempt + ("suspend_phase",), None),
            (attempt + ("stalled_resumes",), None),
            (("issues", "151", "attempts", 0), []),
        ]
        for path, replacement in changes:
            self._assert_current_launch_refuses_unchanged(
                self._changed(valid, path, replacement)
            )
        self._assert_current_launch_refuses_unchanged(
            self._changed(schema_three, ("schema_version",), 3.0)
        )

    def test_schema_one_current_launch_is_read_only_for_attempt_and_remainder(self):
        self._spawn_151()
        state = self._as_legacy(self.read_state(), 1)
        self.write_state(state)
        before = self.state_path.read_bytes()
        inventory = sorted(path.relative_to(self.root) for path in self.root.rglob("*"))
        expected = (
            ("151:1:1", True, "151:1:1", "current"),
            ("151:r1:1", False, None, "unknown_attempt"),
        )
        for action_id, current, current_id, reason in expected:
            result = self.run_cli(
                "current-launch", "--repo-root", self.root, "--run-id", self.run_id,
                "--action-id", action_id,
            )
            self.assertEqual(json.loads(result.stdout), {
                "action_id": action_id, "current": current,
                "current_action_id": current_id, "reason": reason,
            })
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(
            sorted(path.relative_to(self.root) for path in self.root.rglob("*")),
            inventory,
        )

    def test_legacy_hybrid_delivery_fields_refuse_without_write_or_migration(self):
        self._spawn_151()
        workflow = load_source_module(SCRIPT, "workflow_state_schema_two_hybrid")
        baseline = self.read_state()
        for version in (1, 2):
            state = self._as_legacy(baseline, version, keep_delivery=True)
            self._assert_current_launch_refuses_unchanged(state)
            with self.assertRaises(workflow.WorkflowError):
                workflow.upgrade_state(state, run_id=self.run_id,
                                       migration_contracts={})

    def test_future_schema_ledger_is_rejected_without_changes(self):
        self.init_run()
        worktree = str(Path(self.root) / "wt-19")
        self.spawn(issue=19, worktree=worktree, budget_minutes=10)
        state = self.read_state()
        state["schema_version"] = state["schema_version"] + 1
        self.write_state(state)
        before = self.state_path.read_bytes()
        rejected = self.suspend(
            issue=19, attempt=1, blocked_on="external",
            now="2026-08-13T20:02:00Z", ok=False,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("unsupported workflow state schema version", rejected.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_control_auto_resumes_suspended_attempts(self):
        self.init_run()
        worktree = str(Path(self.root) / "wt-41")
        self.spawn(issue=41, worktree=worktree, budget_minutes=10)
        self.expire(issue=41, worktree=worktree, now="2026-08-13T20:10:00Z")
        self.assertEqual(
            self.read_state()["issues"]["41"]["attempts"][-1]["blocked_on"],
            "unknown",
        )
        response = self.control(
            now="2026-08-13T21:00:00Z",
            issues=[41],
            tracker=[self.tracker_fact(41)],
            worktrees=[self.worktree_fact(41, recorded={
                "path": os.path.abspath(worktree),
                "state": "matching_issue_branch",
            })],
        )
        self.assert_control_response_shape(response)
        kinds = [(action["kind"], action.get("issue")) for action in response["actions"]]
        self.assertIn(("resume", 41), kinds)
        self.assertIn(
            {"issue": 41, "attempt": 1, "kind": "resumed", "state": "active"},
            response["deltas"],
        )
        attempt = self.read_state()["issues"]["41"]["attempts"][-1]
        self.assertEqual(attempt["state"], "active")
        self.assertIsNone(attempt["blocked_on"])
        self.assertEqual(attempt["deadline_at"], "2026-08-13T21:30:00Z")

    def test_control_never_emits_a_deadline_less_wait(self):
        self.init_run()
        worktree = str(Path(self.root) / "wt-42")
        self.spawn(issue=42, worktree=worktree, budget_minutes=10)
        self.suspend(
            issue=42, attempt=1, blocked_on="human_gate",
            now="2026-08-13T20:05:00Z",
        )
        response = self.control(
            now="2026-08-13T20:06:00Z",
            issues=[42],
            tracker=[self.tracker_fact(42)],
            worktrees=[self.worktree_fact(42, recorded={
                "path": os.path.abspath(worktree),
                "state": "matching_issue_branch",
            })],
        )
        self.assert_control_response_shape(response)
        self.assertEqual(response["actions"][-1], {"id": "finalize", "kind": "finalize"})
        for action in response["actions"]:
            if action["kind"] == "wait":
                self.assertIsNotNone(action["deadline_at"])
        summary = next(s for s in response["summaries"] if s["issue"] == 42)
        self.assertEqual(summary["state"], "suspended")
        self.assertEqual(summary["blocked_on"], "human_gate")

    def test_human_gate_suspension_is_not_auto_resumed(self):
        self.init_run()
        worktree = str(Path(self.root) / "wt-43")
        self.spawn(issue=43, worktree=worktree, budget_minutes=10)
        self.suspend(
            issue=43, attempt=1, blocked_on="external",
            now="2026-08-13T20:05:00Z",
        )
        before = self.state_path.read_bytes()
        response = self.control(
            now="2026-08-13T20:06:00Z",
            issues=[43],
            tracker=[self.tracker_fact(43)],
            worktrees=[self.worktree_fact(43, recorded={
                "path": os.path.abspath(worktree),
                "state": "matching_issue_branch",
            })],
        )
        self.assert_control_response_shape(response)
        self.assertEqual([a for a in response["actions"] if a["kind"] == "resume"], [])
        self.assertEqual(response["deltas"], [])
        attempt = self.read_state()["issues"]["43"]["attempts"][-1]
        self.assertEqual(attempt["state"], "suspended")
        self.assertEqual(attempt["blocked_on"], "external")
        self.assert_controller_finalized(before, now="2026-08-13T20:06:00Z")  # per D20

    def test_human_directed_control_resumes_a_gated_suspension(self):
        # A sweep the caller named issue-by-issue carries the same consent a
        # direct owner does, so it clears `human_gate`/`external` the way
        # re-entry always has. A `--label`/`--milestone` sweep sends
        # human_directed=false and still leaves them parked.
        self.init_run()
        gates = {45: "human_gate", 46: "external"}
        for issue in gates:
            self.spawn(
                issue=issue, worktree=str(Path(self.root) / f"wt-{issue}"),
                budget_minutes=10,
            )
        for issue, blocked_on in gates.items():
            self.suspend(
                issue=issue, attempt=1, blocked_on=blocked_on,
                now="2026-08-13T20:05:00Z",
            )

        def observations():
            return [
                self.worktree_fact(issue, recorded={
                    "path": os.path.abspath(str(Path(self.root) / f"wt-{issue}")),
                    "state": "matching_issue_branch",
                })
                for issue in (45, 46)
            ]

        parked = self.state_path.read_bytes()
        swept = self.control(
            now="2026-08-13T20:06:00Z", issues=[45, 46],
            tracker=[self.tracker_fact(45), self.tracker_fact(46)],
            worktrees=observations(), human_directed=False,
        )
        self.assert_control_response_shape(swept)
        self.assertEqual([a for a in swept["actions"] if a["kind"] == "resume"], [])
        self.assertEqual(swept["deltas"], [])
        self.assert_controller_finalized(parked, now="2026-08-13T20:06:00Z")  # per D20

        directed = self.control(
            now="2026-08-13T20:07:00Z", issues=[45, 46],
            tracker=[self.tracker_fact(45), self.tracker_fact(46)],
            worktrees=observations(), human_directed=True,
        )
        self.assert_control_response_shape(directed)
        resumed = {a["issue"] for a in directed["actions"] if a["kind"] == "resume"}
        self.assertEqual(resumed, {45, 46})
        for issue in (45, 46):
            self.assertIn(
                {"issue": issue, "attempt": 1, "kind": "resumed", "state": "active"},
                directed["deltas"],
            )
            attempt = self.read_state()["issues"][str(issue)]["attempts"][-1]
            self.assertEqual(attempt["state"], "active")
            self.assertIsNone(attempt["blocked_on"])

    def test_control_rejects_a_non_boolean_human_directed(self):
        self.init_run()
        for bad in ("true", 1, None):
            request = self.control_request(
                now="2026-08-13T20:06:00Z", issues=[47],
                tracker=[self.tracker_fact(47)], worktrees=[],
            )
            request["human_directed"] = bad
            refused = self.control_raw(request=request, ok=False)
            self.assertEqual(refused.returncode, 2)
            self.assertEqual(refused.stdout, "")
            self.assertIn("invalid control human_directed", refused.stderr)

    def test_orchestrated_phase_zero_handoff_resumes_with_absent_worktree(self):
        self.init_run()
        worktree = str(Path(self.root) / "wt-44")
        self.spawn(issue=44, worktree=worktree)
        handoff = self.write_handoff(44)
        self.progress(
            issue=44, phase=0, now="2026-08-13T20:01:00Z",
            turn_count=118, context_tokens=20000, handoff_path=handoff,
        )
        self.assertEqual(
            self.read_state()["issues"]["44"]["attempts"][-1]["state"], "handed_off"
        )
        completed = self.control_raw(
            now="2026-08-13T20:05:00Z",
            issues=[44],
            tracker=[self.tracker_fact(44)],
            worktrees=[self.worktree_fact(44, recorded={
                "path": os.path.abspath(worktree), "state": "absent",
            })],
            ok=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        response = json.loads(completed.stdout)
        self.assert_control_response_shape(response)
        self.assertIn("resume", [action["kind"] for action in response["actions"]])
        attempt = self.read_state()["issues"]["44"]["attempts"][-1]
        self.assertEqual(attempt["state"], "active")
        self.assertEqual(attempt["worktree"], os.path.abspath(worktree))

    def test_control_leaves_an_unobserved_resume_for_the_next_round(self):
        self.init_run()
        worktree = str(Path(self.root) / "wt-45")
        self.spawn(issue=45, worktree=worktree, budget_minutes=10)
        self.expire(issue=45, worktree=worktree, now="2026-08-13T20:10:00Z")
        before = self.state_path.read_bytes()
        completed = self.control_raw(
            now="2026-08-13T21:00:00Z",
            issues=[45],
            tracker=[self.tracker_fact(45)],
            worktrees=[],
            ok=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        response = json.loads(completed.stdout)
        self.assert_control_response_shape(response)
        self.assertEqual(response["actions"], [{"id": "finalize", "kind": "finalize"}])
        self.assertEqual(response["summaries"][0]["state"], "suspended")
        self.assertEqual(response["summaries"][0]["blocked_on"], "unknown")
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_control_still_demands_the_worktree_of_an_unobserved_handoff(self):
        """Only a suspension is owed an observation round; a handoff is not."""
        self.init_run()
        worktree = self.root / "wt-46"
        self.spawn(issue=46, worktree=worktree)
        handoff = self.write_handoff(46)
        self.progress(
            issue=46, phase=1, now="2026-08-13T20:01:00Z",
            turn_count=118, handoff_path=handoff,
        )
        self.assertEqual(
            self.read_state()["issues"]["46"]["attempts"][-1]["state"], "handed_off"
        )
        before = self.state_path.read_bytes()
        rejected = self.control_raw(
            now="2026-08-13T20:02:00Z",
            issues=[46],
            tracker=[self.tracker_fact(46)],
            worktrees=[],
            ok=False,
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertEqual(rejected.stdout, "")
        self.assertIn(
            "resume control action requires a matching recorded worktree observation",
            rejected.stderr,
        )
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_a_halted_tracker_parks_a_suspension_instead_of_resuming_it(self):
        self.init_run()
        worktree = str(Path(self.root) / "wt-91")
        self.spawn(issue=91, worktree=worktree, budget_minutes=10)
        self.expire(issue=91, worktree=worktree, now="2026-08-13T20:10:00Z")
        suspended = self.read_state()["issues"]["91"]["attempts"][-1]
        self.assertEqual(suspended["state"], "suspended")
        before = self.state_path.read_bytes()
        halted = {
            "closed": self.tracker_fact(91, state="closed"),
            "blocked": self.tracker_fact(91, open_blockers=[40]),
            "fogged": self.tracker_fact(91, decision_blockers=[
                {"issue": 41, "url": "https://github.com/fagenorn/nix-config/issues/41"},
            ]),
        }
        for reason, tracker in halted.items():
            with self.subTest(reason=reason):
                response = self.control(
                    now="2026-08-13T21:00:00Z",
                    issues=[91],
                    tracker=[tracker],
                    worktrees=[self.worktree_fact(91, recorded={
                        "path": os.path.abspath(worktree),
                        "state": "matching_issue_branch",
                    })],
                )
                self.assert_control_response_shape(response)
                # The retry lane's closed-issue path demotes nothing that is
                # already demoted and dispatches nothing: no action, no delta.
                self.assertEqual(
                    [a for a in response["actions"] if a["kind"] == "resume"], []
                )
                self.assertEqual(
                    response["actions"], [{"id": "finalize", "kind": "finalize"}]
                )
                self.assertEqual(response["deltas"], [])
                self.assertEqual(response["summaries"][0]["state"], "suspended")
                self.assertEqual(response["summaries"][0]["blocked_on"], "unknown")
                self.assertEqual(
                    self.read_state()["issues"]["91"]["attempts"][-1], suspended
                )
                self.assertEqual(self.state_path.read_bytes(), before)

    def test_check_launch_supersedes_a_predecessor_attempt_after_a_failed_owner(self):
        # The successor attempt is opened by an owner-reported failure, never by
        # expiry: issue #133 changes expiry accounting and touches this same
        # helper, and an expiry-driven fixture would be invalidated by it. Do
        # not "simplify" this back to `expire`/`legacy_expiry_record`.
        self.init_run()
        worktree = str(Path(self.root) / "wt-14")
        spawned = self.spawn(issue=14, worktree=worktree)
        self.assertEqual(spawned["id"], "14:1:1")
        live = self.state_path.read_bytes()
        self.assertEqual(self.check_launch(action_id="14:1:1"), {
            "action_id": "14:1:1", "current": True,
            "current_action_id": "14:1:1", "reason": "current",
        })
        self.assertEqual(self.state_path.read_bytes(), live)

        self.fail_owner(issue=14, attempt=1, now="2026-08-13T20:05:00Z")
        self.assertEqual(self.check_launch(action_id="14:1:1"), {
            "action_id": "14:1:1", "current": False,
            "current_action_id": None, "reason": "inactive_attempt",
        })

        # The retry reuses the predecessor's worktree, which is the shared-checkout
        # reality this guard exists for.
        retried = self.retry(issue=14, worktree=worktree, now="2026-08-13T20:10:00Z")
        self.assertEqual(retried["id"], "14:2:1")
        after = self.state_path.read_bytes()
        self.assertEqual(self.check_launch(action_id="14:1:1"), {
            "action_id": "14:1:1", "current": False,
            "current_action_id": "14:2:1", "reason": "superseded_attempt",
        })
        self.assertEqual(self.check_launch(action_id="14:2:1"), {
            "action_id": "14:2:1", "current": True,
            "current_action_id": "14:2:1", "reason": "current",
        })
        self.assertEqual(self.state_path.read_bytes(), after)

    def test_check_launch_supersedes_a_predecessor_launch_after_a_resume(self):
        self.init_run()
        worktree = str(Path(self.root) / "wt-14")
        self.assertEqual(self.spawn(issue=14, worktree=worktree)["id"], "14:1:1")
        self.suspend(
            issue=14, attempt=1, blocked_on="transport", now="2026-08-13T20:05:00Z",
        )
        self.assertEqual(self.check_launch(action_id="14:1:1"), {
            "action_id": "14:1:1", "current": False,
            "current_action_id": None, "reason": "inactive_attempt",
        })

        resumed = self.resume(issue=14, worktree=worktree, now="2026-08-13T20:06:00Z")
        self.assertEqual(resumed["id"], "14:1:2")
        after = self.state_path.read_bytes()
        self.assertEqual(self.check_launch(action_id="14:1:1"), {
            "action_id": "14:1:1", "current": False,
            "current_action_id": "14:1:2", "reason": "superseded_launch",
        })
        self.assertEqual(self.check_launch(action_id="14:1:2"), {
            "action_id": "14:1:2", "current": True,
            "current_action_id": "14:1:2", "reason": "current",
        })
        self.assertEqual(self.state_path.read_bytes(), after)

    def test_check_launch_creates_nothing_for_a_run_that_does_not_exist(self):
        # `transact`/`workflow_paths` would create `.superpowers/`, the run dir,
        # the workflows `.gitignore` and `state.lock` (per D4). The whole-tree
        # assertion is what proves this verb uses neither.
        first = self.check_launch_raw(action_id="14:1:1")
        self.assertEqual(json.loads(first.stdout), {
            "action_id": "14:1:1", "current": False,
            "current_action_id": None, "reason": "unknown_run",
        })
        self.assertFalse((self.root / ".superpowers").exists())
        self.assertFalse(self.workflows_dir.exists())
        second = self.check_launch_raw(action_id="14:1:1")
        self.assertEqual(second.stdout, first.stdout)
        self.assertFalse((self.root / ".superpowers").exists())

    def test_check_launch_separates_well_formed_negatives_from_errors(self):
        self.init_run()
        self.spawn(issue=14, worktree=str(Path(self.root) / "wt-14"))
        before = self.state_path.read_bytes()
        # Assert the WHOLE answer, not just `reason`. The helper's redundancy
        # invariant only cross-checks `current` against `current_action_id`, so
        # an implementation that echoed the queried id back as
        # `current_action_id` and answered `current: true` would satisfy it and
        # still let a superseded launch merge — exactly the bug under test.
        live = "14:1:1"
        answers = (
            ("absent run", {"action_id": live, "run_id": "issue-99-absent"},
             {"action_id": live, "current": False,
              "current_action_id": None, "reason": "unknown_run"}),
            ("issue not in the ledger", {"action_id": "99:1:1"},
             {"action_id": "99:1:1", "current": False,
              "current_action_id": None, "reason": "unknown_issue"}),
            ("attempt beyond the count", {"action_id": "14:9:1"},
             {"action_id": "14:9:1", "current": False,
              "current_action_id": live, "reason": "unknown_attempt"}),
            ("launch beyond the latest", {"action_id": "14:1:9"},
             {"action_id": "14:1:9", "current": False,
              "current_action_id": live, "reason": "superseded_launch"}),
        )
        for label, kwargs, expected in answers:
            with self.subTest(row=label):
                completed = self.check_launch_raw(**kwargs)
                self.assertEqual(json.loads(completed.stdout), expected)
                # Canonical stdout: sorted keys, compact separators, one
                # trailing newline, exactly as `print_json` emits it.
                self.assertEqual(
                    completed.stdout,
                    json.dumps(expected, sort_keys=True,
                               separators=(",", ":")) + "\n",
                )
                # Re-run through the helper so the redundancy invariant is
                # checked on this row too.
                self.check_launch(**kwargs)
                self.assertEqual(self.state_path.read_bytes(), before)
        errors = (
            ("repository root does not exist",
             {"action_id": "14:1:1", "repo_root": str(self.root / "absent")}),
            ("run id outside the grammar",
             {"action_id": "14:1:1", "run_id": "bad/run"}),
            ("action id with two components", {"action_id": "14:1"}),
            ("action id with a zero ordinal", {"action_id": "14:0:1"}),
            # Well-formed-looking but absurd: an unbounded digit run reaches
            # `int()` past CPython's 4300-digit conversion limit, which must
            # still be the controlled refusal, not an uncaught ValueError.
            ("action id with an oversized ordinal",
             {"action_id": "1" * 5000 + ":1:1"}),
        )
        for label, kwargs in errors:
            with self.subTest(row=label):
                completed = self.check_launch_raw(ok=False, **kwargs)
                self.assertEqual(completed.returncode, 2)
                self.assertEqual(completed.stdout, "")
                self.assertNotIn("Traceback", completed.stderr)
                self.assertEqual(self.state_path.read_bytes(), before)

        # A ledger that cannot be read is a fault, not a refusal (per D3). Both
        # rows destroy the fixture, so they run last.
        self.state_path.write_text("{not json", encoding="utf-8")
        corrupt = self.check_launch_raw(action_id="14:1:1", ok=False)
        self.assertEqual((corrupt.returncode, corrupt.stdout), (2, ""))
        self.assertNotIn("Traceback", corrupt.stderr)

        self.state_path.unlink()
        self.state_path.symlink_to(self.root / "elsewhere.json")
        linked = self.check_launch_raw(action_id="14:1:1", ok=False)
        self.assertEqual((linked.returncode, linked.stdout), (2, ""))
        self.assertNotIn("Traceback", linked.stderr)

    def test_control_expiry_resumes_in_place_when_a_slot_is_free(self):
        # The demo in issue #133: a free slot must not turn an interruption into
        # a consumed attempt (per D1).
        self.init_run(now="2026-08-19T12:00:00Z")
        path = str(self.root / "wt-51")
        self.spawn(issue=51, worktree=path, now="2026-08-19T12:00:00Z",
                   budget_minutes=30)
        response = self.control(
            now="2026-08-19T12:30:00Z", issues=[51], max_parallel=2,
            attempt_budget_minutes=30,
            tracker=[self.tracker_fact(51)],
            worktrees=[self.worktree_fact(51, recorded={
                "path": path, "state": "matching_issue_branch"})],
        )
        self.assertEqual(response["deltas"], [
            {"issue": 51, "attempt": 1, "kind": "expired", "state": "active"},
            {"issue": 51, "attempt": 1, "kind": "resumed", "state": "active"},
        ])
        action = self.dispatch_action(response, "resume")
        self.assertEqual(
            (action["id"], action["attempt"], action["worktree"],
             action["deadline_at"]),
            ("51:1:2", 1, path, "2026-08-19T13:00:00Z"),
        )
        attempts = self.read_state()["issues"]["51"]["attempts"]
        self.assertEqual(len(attempts), 1)
        self.assertEqual(
            (attempts[0]["state"], attempts[0]["launch_kind"],
             len(attempts[0]["launches"]), attempts[0]["blocked_on"],
             attempts[0]["stalled_resumes"], attempts[0]["suspend_phase"]),
            ("active", "resume", 2, None, 0, 0),
        )
        self.assertIsNone(self.read_state()["issues"]["51"]["outcome"])

    def test_control_expiry_parks_when_capacity_is_full_then_resumes_next_sweep(self):
        # Same-sweep when the suspension lane can dispatch, next sweep otherwise
        # — expiry inherits the lane's timing rule, it does not get one (per D2).
        self.init_run(now="2026-08-19T12:00:00Z")
        paths = {51: str(self.root / "wt-51"), 53: str(self.root / "wt-53")}
        self.spawn(issue=51, worktree=paths[51], now="2026-08-19T12:00:00Z",
                   budget_minutes=30)
        self.spawn(issue=53, worktree=paths[53], now="2026-08-19T12:00:00Z",
                   budget_minutes=180)
        observed = self.worktree_fact(51, recorded={
            "path": paths[51], "state": "matching_issue_branch"})

        parked = self.control(
            now="2026-08-19T12:30:00Z", issues=[51, 53], max_parallel=1,
            attempt_budget_minutes=30,
            tracker=[self.tracker_fact(issue) for issue in (51, 53)],
            worktrees=[observed],
        )
        self.assertEqual(parked["deltas"], [
            {"issue": 51, "attempt": 1, "kind": "expired", "state": "suspended"},
        ])
        self.assertEqual([action["kind"] for action in parked["actions"]], ["wait"])
        attempt = self.read_state()["issues"]["51"]["attempts"][-1]
        self.assertEqual(
            (attempt["state"], attempt["blocked_on"], len(attempt["launches"])),
            ("suspended", "unknown", 1),
        )
        summary = next(item for item in parked["summaries"] if item["issue"] == 51)
        self.assertEqual(
            (summary["state"], summary["blocked_on"], summary["worktree"]),
            ("suspended", "unknown", paths[51]),
        )

        self.finish(1, self.merged_result(53), issue=53,
                    now="2026-08-19T12:40:00Z")
        resumed = self.control(
            now="2026-08-19T12:45:00Z", issues=[51, 53], max_parallel=1,
            attempt_budget_minutes=30,
            tracker=[self.tracker_fact(issue) for issue in (51, 53)],
            worktrees=[observed],
        )
        # The parked attempt is `suspended`, not `active`/`handed_off`, so this
        # sweep sees no expiry at all — only the resume the pause already owed.
        self.assertEqual(resumed["deltas"], [
            {"issue": 51, "attempt": 1, "kind": "resumed", "state": "active"},
        ])
        action = self.dispatch_action(resumed, "resume")
        self.assertEqual((action["id"], action["deadline_at"]),
                         ("51:1:2", "2026-08-19T13:15:00Z"))
        self.assertEqual(len(self.read_state()["issues"]["51"]["attempts"]), 1)

    def test_control_expiry_parks_when_the_recorded_worktree_is_unobserved(self):
        # The "round still owed" skip already covers a reaped attempt because it
        # tests `state == "suspended"` (per D2); it costs one sweep, never an
        # attempt.
        self.init_run(now="2026-08-19T12:00:00Z")
        path = str(self.root / "wt-51")
        self.spawn(issue=51, worktree=path, now="2026-08-19T12:00:00Z",
                   budget_minutes=30)
        parked = self.control(
            now="2026-08-19T12:30:00Z", issues=[51], max_parallel=2,
            attempt_budget_minutes=30,
            tracker=[self.tracker_fact(51)], worktrees=[],
        )
        self.assertEqual(parked["deltas"], [
            {"issue": 51, "attempt": 1, "kind": "expired", "state": "suspended"},
        ])
        # No active or handed-off attempt is left, so no deadline is armed.
        self.assertEqual(parked["actions"], [{"id": "finalize", "kind": "finalize"}])
        self.assertIsNone(parked["next_deadline"])

        resumed = self.control(
            now="2026-08-19T12:31:00Z", issues=[51], max_parallel=2,
            attempt_budget_minutes=30,
            tracker=[self.tracker_fact(51)],
            worktrees=[self.worktree_fact(51, recorded={
                "path": path, "state": "matching_issue_branch"})],
        )
        action = self.dispatch_action(resumed, "resume")
        self.assertEqual((action["id"], action["deadline_at"]),
                         ("51:1:2", "2026-08-19T13:01:00Z"))
        self.assertEqual(len(self.read_state()["issues"]["51"]["attempts"]), 1)

    def test_control_double_expiry_resumes_twice_and_spends_no_retry(self):
        # Issue #133 AC2. Two expiries, two resume launches, one attempt.
        self.init_run(now="2026-08-19T12:00:00Z")
        path = str(self.root / "wt-51")
        self.spawn(issue=51, worktree=path, now="2026-08-19T12:00:00Z",
                   budget_minutes=30)
        observed = [self.worktree_fact(51, recorded={
            "path": path, "state": "matching_issue_branch"})]
        kinds = []
        for moment, launch, deadline in (
            ("2026-08-19T12:30:00Z", "51:1:2", "2026-08-19T13:00:00Z"),
            ("2026-08-19T13:00:00Z", "51:1:3", "2026-08-19T13:30:00Z"),
        ):
            response = self.control(
                now=moment, issues=[51], max_parallel=2,
                attempt_budget_minutes=30,
                tracker=[self.tracker_fact(51)], worktrees=observed,
            )
            kinds.extend(delta["kind"] for delta in response["deltas"])
            action = self.dispatch_action(response, "resume")
            self.assertEqual(
                (action["id"], action["attempt"], action["deadline_at"]),
                (launch, 1, deadline),
            )
        self.assertEqual(kinds, ["expired", "resumed", "expired", "resumed"])
        self.assertNotIn("retried", kinds)
        self.assertNotIn("retry_refused", kinds)
        attempts = self.read_state()["issues"]["51"]["attempts"]
        self.assertEqual(len(attempts), 1)
        self.assertEqual(
            (attempts[0]["attempt"], attempts[0]["stalled_resumes"],
             attempts[0]["suspend_phase"], len(attempts[0]["launches"])),
            (1, 1, 0, 3),
        )

    def test_direct_expiry_resumes_in_place_and_ignores_the_candidate(self):
        # Replaces the retry-then-refuse fixture: a direct re-entry after a
        # crash resumes attempt 1, it does not spend the fresh retry (per D2).
        # The reaped attempt is at phase 0, so an `absent` recorded worktree is
        # the reservation intact, not a mismatch (per D13).
        owner = self.acquire_direct(attempt_budget_minutes=30)
        tracker = self.tracker_fact(73)
        replacement = os.path.abspath(self.root / "replacement-worktree-73")
        first = self.direct_owner(
            now="2026-08-20T10:30:00Z", attempt_budget_minutes=30,
            tracker=tracker,
            worktree=self.worktree_fact(
                73,
                recorded={"path": owner["worktree"], "state": "absent"},
                candidate={"path": replacement, "state": "absent"},
            ),
        )
        self.assertEqual(
            (first["kind"], first["attempt"], first["action_id"],
             first["launch_kind"], first["worktree"], first["deadline_at"]),
            ("owner", 1, "73:1:2", "resume", owner["worktree"],
             "2026-08-20T11:00:00Z"),
        )

        second = self.direct_owner(
            now="2026-08-20T11:00:00Z", attempt_budget_minutes=30,
            tracker=tracker,
            worktree=self.worktree_fact(73, recorded={
                "path": owner["worktree"], "state": "absent"}),
        )
        self.assertEqual(
            (second["attempt"], second["action_id"], second["launch_kind"],
             second["deadline_at"]),
            (1, "73:1:3", "resume", "2026-08-20T11:30:00Z"),
        )

        # Inherited, not introduced: a recorded worktree the caller cannot
        # vouch for is re-asked for, exactly as any other suspension in that
        # position. Filed as a follow-up, not fixed here (spec, Out of scope).
        stranded = self.direct_owner(
            now="2026-08-20T11:30:00Z", attempt_budget_minutes=30,
            tracker=tracker,
            worktree=self.worktree_fact(73, recorded={
                "path": owner["worktree"], "state": "mismatch"}),
        )
        self.assertEqual(stranded, {
            "interface_version": 1, "kind": "observe", "issue": 73,
            "run_id": owner["run_id"],
            "requirements": [
                {"kind": "recorded_worktree", "path": owner["worktree"]},
            ],
        })
        state = json.loads(self.direct_state_path(owner["run_id"]).read_text())
        attempts = state["issues"]["73"]["attempts"]
        self.assertEqual(len(attempts), 1)
        self.assertIsNone(attempts[-1]["result_source"])
        self.assertIsNone(state["issues"]["73"]["outcome"])

    def test_control_fourth_expiry_at_one_phase_escalates_to_a_synthetic_stop(self):
        # `stalled_resumes` counts 0, 1, 2 across suspensions at an unchanged
        # phase, so three expiry-driven resumes are free and the fourth expiry
        # terminates the attempt (per D4). Before this change the retry lane
        # stamped that terminal and then cleared it.
        self.init_run(now="2026-08-19T12:00:00Z")
        path = str(self.root / "wt-51")
        self.spawn(issue=51, worktree=path, now="2026-08-19T12:00:00Z",
                   budget_minutes=30)
        observed = [self.worktree_fact(51, recorded={
            "path": path, "state": "matching_issue_branch"})]

        def sweep(moment):
            return self.control(
                now=moment, issues=[51], max_parallel=2,
                attempt_budget_minutes=30,
                tracker=[self.tracker_fact(51)], worktrees=observed,
            )

        for moment, launch in (
            ("2026-08-19T12:30:00Z", "51:1:2"),
            ("2026-08-19T13:00:00Z", "51:1:3"),
            ("2026-08-19T13:30:00Z", "51:1:4"),
        ):
            self.assertEqual(self.dispatch_action(sweep(moment), "resume")["id"],
                             launch)

        escalated = sweep("2026-08-19T14:00:00Z")
        self.assertEqual(escalated["deltas"], [
            {"issue": 51, "attempt": 1, "kind": "expired", "state": "stopped"},
        ])
        self.assertEqual(escalated["actions"],
                         [{"id": "finalize", "kind": "finalize"}])
        issue_state = self.read_state()["issues"]["51"]
        attempt = issue_state["attempts"][-1]
        self.assertEqual(len(issue_state["attempts"]), 1)
        self.assertEqual(
            (attempt["state"], attempt["result_source"], attempt["blocked_on"]),
            ("stopped", "stalled", None),
        )
        self.assertIn("stalled without phase progress", attempt["result"]["notes"])
        self.assertEqual(issue_state["outcome"], attempt["result"])

    def test_direct_expiry_escalation_matches_the_next_call_terminal_replay(self):
        owner = self.acquire_direct(attempt_budget_minutes=30)
        tracker = self.tracker_fact(73)
        observed = self.worktree_fact(73, recorded={
            "path": owner["worktree"], "state": "absent"})
        for moment, launch in (
            ("2026-08-20T10:30:00Z", "73:1:2"),
            ("2026-08-20T11:00:00Z", "73:1:3"),
            ("2026-08-20T11:30:00Z", "73:1:4"),
        ):
            resumed = self.direct_owner(
                now=moment, attempt_budget_minutes=30, tracker=tracker,
                worktree=observed,
            )
            self.assertEqual(resumed["action_id"], launch)

        escalated = self.direct_owner_raw(
            now="2026-08-20T12:00:00Z", attempt_budget_minutes=30,
            tracker=tracker, worktree=observed,
        )
        envelope = json.loads(escalated.stdout)
        state = json.loads(self.direct_state_path(owner["run_id"]).read_text())
        outcome = state["issues"]["73"]["outcome"]
        self.assertEqual(envelope, {
            "interface_version": 1, "kind": "terminal", "issue": 73,
            "run_id": owner["run_id"], "source": "lifecycle",
            "reason": "stopped", "blockers": [], "result": outcome,
            "reentry": "/from-issue 73 --auto",
        })
        attempts = state["issues"]["73"]["attempts"]
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[-1]["result_source"], "stalled")

        # The next call reaches the same envelope through terminal replay, so
        # the two must agree byte for byte (per D4).
        replayed = self.direct_owner_raw(
            now="2026-08-20T12:05:00Z", attempt_budget_minutes=30,
            tracker=tracker, worktree=observed,
        )
        self.assertEqual(replayed.stdout, escalated.stdout)

    def test_expired_handoff_resumes_the_same_attempt_and_revalidates_its_document(self):
        # Before this change an expired handoff entered the retry lane and got
        # an attempt 2 whose `handoff_path` was null — the document was silently
        # abandoned (per D5).
        self.init_run()
        worktree = self.root / "wt-a"
        self.spawn(issue=14, worktree=worktree)
        handoff_path = self.write_handoff(14)
        self.progress(turn_count=118, context_tokens=20000,
                      handoff_path=handoff_path)
        observed = [self.worktree_fact(14, recorded={
            "path": os.path.abspath(worktree), "state": "matching_issue_branch"})]

        response = self.control(
            now="2026-08-13T20:31:00Z", issues=[14], max_parallel=2,
            attempt_budget_minutes=30,
            tracker=[self.tracker_fact(14)], worktrees=observed,
        )
        self.assertEqual([delta["kind"] for delta in response["deltas"]],
                         ["expired", "resumed"])
        action = self.dispatch_action(response, "resume")
        self.assertEqual(
            (action["id"], action["attempt"], action["worktree"],
             action["handoff_path"], action["deadline_at"]),
            ("14:1:2", 1, os.path.abspath(worktree), str(handoff_path),
             "2026-08-13T21:01:00Z"),
        )
        attempts = self.read_state()["issues"]["14"]["attempts"]
        self.assertEqual(len(attempts), 1)
        self.assertEqual(
            (attempts[0]["state"], attempts[0]["handoff_path"]),
            ("active", str(handoff_path)),
        )
        self.assertTrue(handoff_path.is_file())

        # The second resume of one handoff is where the state-keyed guard used
        # to hand out an unvalidated path: the attempt is `suspended`, not
        # `handed_off`, yet the response is about to publish `handoff_path`.
        handoff_path.unlink()
        before = self.state_path.read_bytes()
        rejected = self.control_raw(
            now="2026-08-13T21:01:00Z", issues=[14], max_parallel=2,
            attempt_budget_minutes=30,
            tracker=[self.tracker_fact(14)], worktrees=observed,
            ok=False,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertNotIn("Traceback", rejected.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)


class WorkerRegistryTest(LifecycleHarness, unittest.TestCase):
    """The run-level worker registry of #222: register, release, check-worker."""

    def spawn_14(self):
        self.init_run()
        spawned = self.spawn(issue=14, worktree=str(self.root / "wt-14"))
        self.assertEqual(spawned["id"], "14:1:1")

    def test_register_assigns_dense_ordinals_and_check_worker_reads_live(self):
        self.spawn_14()
        self.assertEqual(
            self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z"),
            {"worker_id": "14:1:1:w1", "launch": "14:1:1", "parent": None})
        self.assertEqual(
            self.register_worker(action_id="14:1:1", now="2026-08-13T20:02:00Z",
                                 parent="14:1:1:w1"),
            {"worker_id": "14:1:1:w2", "launch": "14:1:1", "parent": "14:1:1:w1"})
        before = self.state_path.read_bytes()
        self.assertEqual(self.check_worker("14:1:1:w2"), {
            "worker_id": "14:1:1:w2", "live": True,
            "current_action_id": "14:1:1", "reason": "live"})
        self.assertEqual(self.check_worker("14:1:1:w9")["reason"], "unknown_worker")
        self.assertEqual(self.state_path.read_bytes(), before)
        state = self.read_state()
        self.assertEqual(state["schema_version"], 7)
        self.assertEqual(state["workers"][0], {
            "worker_id": "14:1:1:w1", "launch": "14:1:1", "parent": None,
            "registered_at": "2026-08-13T20:01:00Z", "released_at": None,
            "release_event": None})

    def test_register_refuses_without_writing(self):
        self.spawn_14()
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z")
        before = self.state_path.read_bytes()
        cases = {
            "unknown parent": dict(action_id="14:1:1", now="2026-08-13T20:02:00Z",
                                   parent="14:1:1:w7"),
            "superseded launch": dict(action_id="14:1:9", now="2026-08-13T20:02:00Z"),
            "clock moved backward": dict(action_id="14:1:1", now="2026-08-13T19:59:00Z"),
            "malformed launch": dict(action_id="14:1", now="2026-08-13T20:02:00Z"),
        }
        for name, arguments in cases.items():
            with self.subTest(name):
                refused = self.register_worker(ok=False, **arguments)
                self.assertEqual(refused.returncode, 2)
                self.assertEqual(refused.stdout, "")
                self.assertEqual(self.state_path.read_bytes(), before)

    def test_register_refuses_an_inactive_launch(self):
        self.spawn_14()
        self.suspend(issue=14, attempt=1, blocked_on="transport",
                     now="2026-08-13T20:05:00Z")
        before = self.state_path.read_bytes()
        refused = self.register_worker(action_id="14:1:1", now="2026-08-13T20:06:00Z",
                                       ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("inactive_attempt", refused.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_returned_release_waits_for_live_children_and_stopped_cascades(self):
        self.spawn_14()
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z")
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:02:00Z",
                             parent="14:1:1:w1")
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:02:00Z",
                             parent="14:1:1:w2")
        refused = self.release_worker(worker_id="14:1:1:w1", event="returned",
                                      now="2026-08-13T20:03:00Z", ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("14:1:1:w2", refused.stderr)
        self.assertEqual(
            self.release_worker(worker_id="14:1:1:w1", event="stopped",
                                now="2026-08-13T20:03:00Z"),
            {"worker_id": "14:1:1:w1", "release_event": "stopped",
             "released": ["14:1:1:w1", "14:1:1:w2", "14:1:1:w3"]})
        for worker in ("14:1:1:w1", "14:1:1:w2", "14:1:1:w3"):
            self.assertEqual(self.check_worker(worker)["reason"], "released")
        self.assertEqual(
            {w["released_at"] for w in self.read_state()["workers"]},
            {"2026-08-13T20:03:00Z"})
        before = self.state_path.read_bytes()
        self.assertEqual(
            self.release_worker(worker_id="14:1:1:w1", event="stopped",
                                now="2026-08-13T20:04:00Z")["released"], [])
        self.assertEqual(self.state_path.read_bytes(), before)
        conflict = self.release_worker(worker_id="14:1:1:w2", event="returned",
                                       now="2026-08-13T20:04:00Z", ok=False)
        self.assertEqual(conflict.returncode, 2)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_a_returned_child_lets_its_parent_return(self):
        self.spawn_14()
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z")
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z",
                             parent="14:1:1:w1")
        self.release_worker(worker_id="14:1:1:w2", event="returned",
                            now="2026-08-13T20:02:00Z")
        self.assertEqual(
            self.release_worker(worker_id="14:1:1:w1", event="returned",
                                now="2026-08-13T20:02:00Z")["released"],
            ["14:1:1:w1"])

    def test_a_resume_after_an_unavailable_owner_fences_its_workers(self):
        self.spawn_14()
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z")
        resumed = self.resume(issue=14, worktree=str(self.root / "wt-14"),
                              now="2026-08-13T20:06:00Z", owner_unavailable=True)
        self.assertEqual(resumed["id"], "14:1:2")
        self.assertEqual(self.check_worker("14:1:1:w1"), {
            "worker_id": "14:1:1:w1", "live": False,
            "current_action_id": "14:1:2", "reason": "superseded_launch"})
        self.assertIsNone(self.read_state()["workers"][0]["released_at"])
        self.assertEqual(
            self.register_worker(action_id="14:1:2",
                                 now="2026-08-13T20:07:00Z")["worker_id"],
            "14:1:2:w1")
        refused = self.register_worker(action_id="14:1:1", now="2026-08-13T20:07:00Z",
                                       parent="14:1:1:w1", ok=False)
        self.assertEqual(refused.returncode, 2)

    def test_check_worker_answers_an_unknown_run_without_creating_anything(self):
        inventory = sorted(self.root.rglob("*"))
        self.assertEqual(self.check_worker("14:1:1:w1"), {
            "worker_id": "14:1:1:w1", "live": False,
            "current_action_id": None, "reason": "unknown_run"})
        self.assertEqual(sorted(self.root.rglob("*")), inventory)
        malformed = self.check_worker_raw("14:1:1:w0", ok=False)
        self.assertEqual((malformed.returncode, malformed.stdout), (2, ""))

    def test_a_schema_four_ledger_reads_unlocked_and_upgrades_on_first_write(self):
        self.spawn_14()
        legacy = self._as_legacy(self.read_state(), 4)
        self.assertNotIn("workers", legacy)
        self.write_state(legacy)
        before = self.state_path.read_bytes()
        self.assertEqual(self.check_worker("14:1:1:w1")["reason"], "unknown_worker")
        self.assertEqual(self.check_launch(action_id="14:1:1")["reason"], "current")
        self.assertEqual(self.state_path.read_bytes(), before)
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z")
        upgraded = self.read_state()
        self.assertEqual(upgraded["schema_version"], 7)
        self.assertEqual([w["worker_id"] for w in upgraded["workers"]], ["14:1:1:w1"])
        hybrid = self._as_legacy(upgraded, 4)
        hybrid["workers"] = []
        self.write_state(hybrid)
        self.assertEqual(self.check_worker_raw("14:1:1:w1", ok=False).returncode, 2)

    def test_the_validator_closes_every_worker_record(self):
        self.spawn_14()
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z")
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:02:00Z",
                             parent="14:1:1:w1")
        valid = self.read_state()

        def edited(**fields_by_index):
            value = copy.deepcopy(valid)
            for index, fields in fields_by_index.items():
                value["workers"][int(index[1:])].update(fields)
            return value

        cases = {
            "not a list": self._changed(valid, ("workers",), {}),
            "extra field": edited(w0={"note": "x"}),
            "zero ordinal": edited(w0={"worker_id": "14:1:1:w0"}),
            "id outside its launch": edited(w0={"launch": "14:1:2"}),
            "unknown launch": edited(w0={"worker_id": "14:1:9:w1", "launch": "14:1:9"},
                                     w1={"parent": None}),
            "ordinal gap": edited(w1={"worker_id": "14:1:1:w3"}),
            "parent not earlier": edited(w0={"parent": "14:1:1:w2"}),
            "release time without event": edited(
                w1={"released_at": "2026-08-13T20:02:00Z"}),
            "event without release time": edited(w1={"release_event": "returned"}),
            "unknown event": edited(
                w1={"released_at": "2026-08-13T20:02:00Z", "release_event": "vanished"}),
            "registered after update": edited(w0={"registered_at": "2099-01-01T00:00:00Z"}),
            "released before registered": edited(
                w1={"released_at": "2026-08-13T20:01:30Z", "release_event": "returned"}),
            "stopped with an unreleased child": edited(
                w0={"released_at": "2026-08-13T20:02:00Z", "release_event": "stopped"}),
            "null registration time": edited(w0={"registered_at": None}),
            "numeric release time": edited(
                w1={"released_at": 1786651320, "release_event": "returned"}),
        }
        mistyped_times = {"null registration time", "numeric release time"}
        for name, state in cases.items():
            with self.subTest(name):
                self.write_state(state)
                refused = self.check_worker_raw("14:1:1:w1", ok=False)
                self.assertEqual((refused.returncode, refused.stdout), (2, ""))
                if name in mistyped_times:
                    self.assertIn("invalid workflow workers", refused.stderr)


class ProgressMarkerSchemaTest(LifecycleHarness, unittest.TestCase):
    """#250 D4: schema 6 gives every attempt a nullable `progress_marker`."""

    def spawn_16(self):
        self.init_run()
        self.worktree = str(self.root / "wt-16")
        self.spawn(issue=16, worktree=self.worktree, budget_minutes=10)

    def attempt(self):
        return self.read_state()["issues"]["16"]["attempts"][-1]

    def with_marker(self, state, marker):
        value = copy.deepcopy(state)
        value["issues"]["16"]["attempts"][0]["progress_marker"] = marker
        return value

    def assert_refused_unchanged(self, state):
        self.write_state(state)
        before = self.state_path.read_bytes()
        refused = self.check_launch_raw(action_id="16:1:1", ok=False)
        self.assertEqual((refused.returncode, self.state_path.read_bytes()), (2, before))

    def test_a_new_attempt_starts_with_a_null_marker_at_schema_six(self):
        self.spawn_16()
        self.assertEqual(self.read_state()["schema_version"], 7)
        self.assertIsNone(self.attempt()["progress_marker"])

    def test_a_schema_five_ledger_keeps_its_stall_count_and_upgrades_on_first_write(self):
        self.spawn_16()
        self.suspend(issue=16, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:01:00Z")
        self.resume(issue=16, worktree=self.worktree, now="2026-08-13T20:02:00Z")
        self.suspend(issue=16, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:03:00Z")
        self.assertEqual(self.attempt()["stalled_resumes"], 1)
        legacy = self._as_legacy(self.read_state(), 5)
        self.assertEqual(legacy["schema_version"], 5)
        self.assertNotIn("progress_marker", legacy["issues"]["16"]["attempts"][0])
        self.write_state(legacy)
        before = self.state_path.read_bytes()
        self.assertEqual(self.check_launch(action_id="16:1:2")["reason"],
                         "inactive_attempt")
        self.assertEqual(self.state_path.read_bytes(), before)
        self.resume(issue=16, worktree=self.worktree, now="2026-08-13T20:04:00Z")
        upgraded = self.read_state()
        attempt = upgraded["issues"]["16"]["attempts"][0]
        self.assertEqual(
            (upgraded["schema_version"], attempt["progress_marker"],
             attempt["stalled_resumes"], attempt["suspend_phase"]),
            (7, None, 1, 0))

    def test_a_schema_five_hybrid_is_refused_without_a_write(self):
        self.spawn_16()
        hybrid = self._as_legacy(self.read_state(), 5)
        hybrid["issues"]["16"]["attempts"][0]["progress_marker"] = None
        self.assert_refused_unchanged(hybrid)
        before = self.state_path.read_bytes()
        refused = self.suspend(issue=16, attempt=1, blocked_on="external",
                               now="2026-08-13T20:02:00Z", ok=False)
        self.assertEqual((refused.returncode, self.state_path.read_bytes()), (2, before))

    def test_the_validator_closes_the_marker(self):
        self.spawn_16()
        valid = self.read_state()
        for marker in ("a" * 40, "0123456789abcdef" * 4):
            with self.subTest(accepted=marker):
                self.write_state(self.with_marker(valid, marker))
                self.assertEqual(self.check_launch(action_id="16:1:1")["reason"],
                                 "current")
        rejected = {
            "abbreviated": "abc1234", "uppercase": "A" * 40, "41 characters": "a" * 41,
            "63 characters": "a" * 63, "not hexadecimal": "g" * 40, "empty": "",
            "trailing newline": "a" * 40 + "\n", "integer": 7, "boolean": True,
        }
        for label, marker in rejected.items():
            with self.subTest(rejected=label):
                self.assert_refused_unchanged(self.with_marker(valid, marker))
        missing = copy.deepcopy(valid)
        del missing["issues"]["16"]["attempts"][0]["progress_marker"]
        self.assert_refused_unchanged(missing)


class LaneSchemaTest(LifecycleHarness, unittest.TestCase):
    """#280 D3, D5: schema 7 gives every attempt a lane, a lane budget and a lane history."""

    LATER = "2026-08-13T20:05:00Z"
    ESCALATIONS = ("important_finding", "second_fix_round", "light_deadline",
                   "unpredicted_risk")

    def spawn_16(self):
        self.init_run()
        self.worktree = str(self.root / "wt-16")
        self.spawn(issue=16, worktree=self.worktree, budget_minutes=240)

    def attempt(self):
        return self.read_state()["issues"]["16"]["attempts"][-1]

    def lane_of(self, attempt):
        return (attempt["lane"], attempt["lane_budget_minutes"], attempt["lane_history"])

    @staticmethod
    def with_lane(state, lane, budget, history):
        value = copy.deepcopy(state)
        value["issues"]["16"]["attempts"][0].update(
            lane=lane, lane_budget_minutes=budget, lane_history=history)
        return value

    def assert_refused_unchanged(self, state):
        self.write_state(state)
        before = self.state_path.read_bytes()
        refused = self.check_launch_raw(action_id="16:1:1", ok=False)
        self.assertEqual((refused.returncode, self.state_path.read_bytes()), (2, before))

    def test_a_new_attempt_starts_without_a_lane_at_schema_seven(self):
        self.spawn_16()
        self.assertEqual(self.read_state()["schema_version"], 7)
        self.assertEqual(self.lane_of(self.attempt()), (None, None, []))

    def test_a_retry_attempt_does_not_inherit_its_predecessors_lane(self):
        self.spawn_16()
        # `fail_owner` routes through the legacy `finish` transport, which
        # downgrades the ledger to schema 2 and so drops lane fields; set the
        # predecessor's lane only after the failure has landed (Phase-5 PR280-02).
        self.fail_owner(issue=16, attempt=1, now="2026-08-13T20:01:00Z")
        self.write_state(self.with_lane(
            self.read_state(), "light", 90,
            [{"lane": "light", "reason": "triage", "at": DEFAULT_NOW}]))
        self.assertEqual(self.lane_of(self.read_state()["issues"]["16"]["attempts"][0])[0],
                         "light")
        self.retry(issue=16, worktree=self.root / "wt-16b", now="2026-08-13T20:10:00Z")
        issue = self.read_state()["issues"]["16"]
        self.assertEqual(self.lane_of(issue["attempts"][0])[0], "light")
        self.assertEqual(self.lane_of(issue["attempts"][1]), (None, None, []))

    def test_a_schema_six_ledger_migrates_with_null_lane_fields(self):
        self.spawn_16()
        legacy = self._as_legacy(self.read_state(), 6)
        self.assertEqual(legacy["schema_version"], 6)
        for field in ("lane", "lane_budget_minutes", "lane_history"):
            self.assertNotIn(field, legacy["issues"]["16"]["attempts"][0])
        self.write_state(legacy)
        before = self.state_path.read_bytes()
        self.assertEqual(self.check_launch(action_id="16:1:1")["reason"], "current")
        self.assertEqual(self.state_path.read_bytes(), before)
        self.suspend(issue=16, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:01:00Z")
        upgraded = self.read_state()
        self.assertEqual(
            (upgraded["schema_version"],
             self.lane_of(upgraded["issues"]["16"]["attempts"][0])),
            (7, (None, None, [])))

    def test_a_schema_six_hybrid_is_refused_without_a_write(self):
        self.spawn_16()
        valid = self.read_state()
        for field, value in (("lane", None), ("lane_budget_minutes", None),
                             ("lane_history", [])):
            with self.subTest(field=field):
                hybrid = self._as_legacy(valid, 6)
                hybrid["issues"]["16"]["attempts"][0][field] = value
                self.assert_refused_unchanged(hybrid)

    def test_the_validator_closes_the_lane_fields(self):
        self.spawn_16()
        valid = self.read_state()
        light = {"lane": "light", "reason": "triage", "at": DEFAULT_NOW}
        full = {"lane": "full", "reason": "triage", "at": DEFAULT_NOW}
        accepted = {"light": ("light", 90, [light]), "full": ("full", 240, [full])}
        for reason in self.ESCALATIONS:
            accepted[f"escalated by {reason}"] = ("full", 240, [
                light, {"lane": "full", "reason": reason, "at": self.LATER}])
        for label, lane in accepted.items():
            with self.subTest(accepted=label):
                self.write_state(self.with_lane(valid, *lane))
                self.assertEqual(self.check_launch(action_id="16:1:1")["reason"],
                                 "current")
        escalated = {"lane": "full", "reason": "important_finding", "at": self.LATER}
        rejected = {
            "lane without a budget": ("light", None, [light]),
            "budget without a lane": (None, 90, []),
            "lane without a history": ("light", 90, []),
            "history without a lane": (None, None, [light]),
            "unknown lane": ("medium", 90, [{**light, "lane": "medium"}]),
            "last entry disagrees with the lane": ("full", 90, [light]),
            "zero budget": ("light", 0, [light]),
            "boolean budget": ("light", True, [light]),
            "string budget": ("light", "90", [light]),
            "history that is not a list": ("light", 90, {"0": light}),
            "entry with an extra key": ("light", 90, [{**light, "note": "x"}]),
            "entry missing its time": ("light", 90, [{"lane": "light", "reason": "triage"}]),
            "unknown reason": ("light", 90, [{**light, "reason": "whim"}]),
            "escalation reason on a first entry": (
                "light", 90, [{**light, "reason": "important_finding"}]),
            "triage on an escalation": ("full", 240, [light, {**escalated, "reason": "triage"}]),
            "full to light": ("light", 90, [full, {**light, "at": self.LATER}]),
            "light to light": ("light", 90, [light, {**escalated, "lane": "light"}]),
            "full to full": ("full", 240, [full, escalated]),
            "time moving backward": ("full", 240, [
                {**light, "at": self.LATER}, {**escalated, "at": DEFAULT_NOW}]),
            "entry before the attempt started": (
                "light", 90, [{**light, "at": "2026-08-13T19:59:59Z"}]),
            "unparseable time": ("light", 90, [{**light, "at": "yesterday"}]),
            "list-valued reason": ("light", 90, [{**light, "reason": ["triage"]}]),
            "null time": ("light", 90, [{**light, "at": None}]),
            "list-valued lane": ("light", 90, [{**light, "lane": ["light"]}]),
        }
        for label, lane in rejected.items():
            with self.subTest(rejected=label):
                self.assert_refused_unchanged(self.with_lane(valid, *lane))
        for field in ("lane", "lane_budget_minutes", "lane_history"):
            with self.subTest(missing=field):
                missing = copy.deepcopy(valid)
                del missing["issues"]["16"]["attempts"][0][field]
                self.assert_refused_unchanged(missing)


class DeclareLaneTest(LifecycleHarness, unittest.TestCase):
    """#280: `declare-lane` records an attempt's lane and re-bases its deadline."""

    def setUp(self):
        super().setUp()
        self.init_run()
        self.worktree = str(self.root / "wt-16")
        self.spawn(issue=16, worktree=self.worktree, budget_minutes=240)

    def attempt(self, issue=16):
        return self.read_state()["issues"][str(issue)]["attempts"][-1]

    def declare(self, lane, *, now, budget=None, reason="triage", action_id="16:1:1",
                ok=True):
        if budget is None:
            budget = 90 if lane == "light" else 240
        return self.declare_lane(action_id=action_id, now=now, lane=lane,
                                 budget_minutes=budget, reason=reason, ok=ok)

    def assert_refused(self, clause, lane, **declare):
        before = self.state_path.read_bytes()
        refused = self.declare(lane, ok=False, **declare)
        self.assertEqual(
            (refused.returncode, refused.stdout, self.state_path.read_bytes()),
            (2, "", before))
        self.assertIn(clause, refused.stderr)

    def test_light_rebases_the_deadline_from_the_launch_and_records_history(self):
        before = self.attempt()
        self.assertEqual(before["deadline_at"], "2026-08-14T00:00:00Z")
        reply = self.declare("light", now="2026-08-13T20:05:00Z")
        self.assertEqual(reply, {"action_id": "16:1:1", "lane": "light",
                                 "budget_minutes": 90,
                                 "deadline_at": "2026-08-13T21:30:00Z"})
        after = self.attempt()
        self.assertEqual(
            (after["lane"], after["lane_budget_minutes"], after["deadline_at"],
             after["lane_history"]),
            ("light", 90, "2026-08-13T21:30:00Z",
             [{"lane": "light", "reason": "triage", "at": "2026-08-13T20:05:00Z"}]))
        self.assertEqual(self.read_state()["updated_at"], "2026-08-13T20:05:00Z")
        untouched = ("last_progress_at", "phase", "suspend_phase", "stalled_resumes",
                     "launches", "state", "started_at")
        self.assertEqual({key: after[key] for key in untouched},
                         {key: before[key] for key in untouched})

    def test_light_escalates_to_full_from_the_same_launch(self):
        self.declare("light", now="2026-08-13T20:05:00Z")
        reply = self.declare("full", now="2026-08-13T20:40:00Z",
                             reason="second_fix_round")
        self.assertEqual(reply["deadline_at"], "2026-08-14T00:00:00Z")
        self.assertEqual(
            [(entry["lane"], entry["reason"]) for entry in self.attempt()["lane_history"]],
            [("light", "triage"), ("full", "second_fix_round")])

    def test_full_is_declared_from_triage_with_its_own_budget(self):
        reply = self.declare("full", now="2026-08-13T20:05:00Z", budget=200)
        self.assertEqual((reply["lane"], reply["budget_minutes"], reply["deadline_at"]),
                         ("full", 200, "2026-08-13T23:20:00Z"))

    def test_a_live_worker_does_not_block_a_declaration(self):
        self.register_worker(action_id="16:1:1", now="2026-08-13T20:01:00Z")
        self.assertEqual(self.declare("light", now="2026-08-13T20:02:00Z")["lane"],
                         "light")

    def test_refuses_full_to_light_and_light_to_light(self):
        self.spawn(issue=17, worktree=str(self.root / "wt-17"), budget_minutes=240)
        self.declare("full", now="2026-08-13T20:05:00Z")
        self.assert_refused("declare-lane refused: lane full cannot become light",
                            "light", now="2026-08-13T20:06:00Z")
        self.assert_refused("declare-lane refused: lane full cannot become full",
                            "full", now="2026-08-13T20:06:00Z",
                            reason="important_finding")
        self.declare("light", now="2026-08-13T20:07:00Z", action_id="17:1:1")
        self.assert_refused("declare-lane refused: lane light cannot become light",
                            "light", now="2026-08-13T20:08:00Z", action_id="17:1:1")

    def test_refuses_a_reason_the_transition_does_not_allow(self):
        self.assert_refused(
            "declare-lane refused: reason important_finding does not allow "
            "lane none to become light",
            "light", now="2026-08-13T20:05:00Z", reason="important_finding")
        self.declare("light", now="2026-08-13T20:05:00Z")
        self.assert_refused(
            "declare-lane refused: reason triage does not allow lane light to become full",
            "full", now="2026-08-13T20:06:00Z", reason="triage")
        self.assert_refused("invalid choice", "light", now="2026-08-13T20:06:00Z",
                            reason="whim")

    def test_refuses_a_launch_that_is_not_current(self):
        self.assert_refused("declare-lane refused: launch 99:1:1 is unknown_issue",
                            "light", now="2026-08-13T20:01:00Z", action_id="99:1:1")
        self.suspend(issue=16, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:01:00Z")
        self.assert_refused("declare-lane refused: launch 16:1:1 is inactive_attempt",
                            "light", now="2026-08-13T20:02:00Z")
        self.resume(issue=16, worktree=self.worktree, now="2026-08-13T20:03:00Z")
        self.assert_refused("declare-lane refused: launch 16:1:1 is superseded_launch",
                            "light", now="2026-08-13T20:04:00Z")
        reply = self.declare("light", now="2026-08-13T20:04:00Z", action_id="16:1:2")
        self.assertEqual(reply["deadline_at"], "2026-08-13T21:33:00Z")

    def test_refuses_a_remainder_launch_a_zero_budget_and_time_moving_backward(self):
        self.assert_refused("declare-lane refused: a remainder launch carries no lane",
                            "light", now="2026-08-13T20:01:00Z", action_id="16:r1:1")
        self.assert_refused("invalid --budget-minutes", "light",
                            now="2026-08-13T20:01:00Z", budget=0)
        self.declare("light", now="2026-08-13T20:05:00Z")
        self.assert_refused("declare-lane refused: time must not move backward",
                            "full", now="2026-08-13T20:04:00Z",
                            reason="important_finding")

    def test_an_omitted_now_stamps_the_ledger_clock(self):
        self.cli_env["WORKFLOW_STATE_TEST_CLOCK"] = "2026-08-13T20:10:00Z"
        completed = self.run_cli(
            "declare-lane", "--repo-root", self.root, "--run-id", self.run_id,
            "--action-id", "16:1:1", "--lane", "light", "--budget-minutes", "90",
            "--reason", "triage")
        self.assertEqual(json.loads(completed.stdout)["deadline_at"], "2026-08-13T21:30:00Z")
        self.assertEqual(self.attempt()["lane_history"],
                         [{"lane": "light", "reason": "triage", "at": "2026-08-13T20:10:00Z"}])
        self.assertEqual(self.read_state()["updated_at"], "2026-08-13T20:10:00Z")

    def test_refuses_a_rebased_deadline_that_is_not_after_now(self):
        for now in ("2026-08-13T21:30:00Z", "2026-08-13T21:31:00Z"):
            with self.subTest(lane="light", now=now):
                self.assert_refused(
                    f"declare-lane refused: deadline 2026-08-13T21:30:00Z is not after {now}",
                    "light", now=now)
        self.assert_refused(
            "declare-lane refused: deadline 2026-08-13T21:00:00Z is not after "
            "2026-08-13T21:31:00Z",
            "full", now="2026-08-13T21:31:00Z", budget=60)
        self.assertIsNone(self.attempt()["lane"])
        self.assert_refused(
            "declare-lane refused: deadline 2026-08-13T21:31:00Z is not after "
            "2026-08-13T21:31:00Z",
            "light", now="2026-08-13T21:31:00Z", budget=91)
        reply = self.declare("light", now="2026-08-13T21:31:00Z", budget=92)
        self.assertEqual(reply["deadline_at"], "2026-08-13T21:32:00Z")

    def test_a_suspension_resume_uses_the_lane_budget_or_the_request_budget(self):
        for issue in (17, 18):
            self.spawn(issue=issue, worktree=str(self.root / f"wt-{issue}"),
                       budget_minutes=240)
        self.declare("light", now="2026-08-13T20:05:00Z")
        self.declare("full", now="2026-08-13T20:05:00Z", budget=200, action_id="18:1:1")
        for issue in (16, 17, 18):
            self.suspend(issue=issue, attempt=1, blocked_on="usage_limit",
                         now="2026-08-13T20:10:00Z")
        # `resume` sends the harness's default request budget of 30 minutes.
        expected = {16: ("2026-08-13T23:00:00Z", "2026-08-14T00:30:00Z", "light"),
                    17: ("2026-08-13T23:01:00Z", "2026-08-13T23:31:00Z", None),
                    18: ("2026-08-13T23:02:00Z", "2026-08-14T02:22:00Z", "full")}
        for issue, (now, deadline, lane) in expected.items():
            with self.subTest(issue=issue):
                self.resume(issue=issue, worktree=str(self.root / f"wt-{issue}"), now=now)
                attempt = self.attempt(issue)
                self.assertEqual(
                    (attempt["state"], attempt["deadline_at"], attempt["last_progress_at"],
                     attempt["lane"], len(attempt["launches"])),
                    ("active", deadline, now, lane, 2))

    def test_a_takeover_inside_the_window_keeps_the_declared_deadline(self):
        self.declare("light", now="2026-08-13T20:05:00Z")
        self.resume(issue=16, worktree=self.worktree, now="2026-08-13T20:20:00Z",
                    owner_unavailable=True)
        attempt = self.attempt()
        self.assertEqual((attempt["deadline_at"], attempt["lane"], len(attempt["launches"])),
                         ("2026-08-13T21:30:00Z", "light", 2))


class ProgressMarkerTest(LifecycleHarness, unittest.TestCase):
    """#250: `mark-progress` records durable forward movement of the attempt worktree."""

    def setUp(self):
        super().setUp()
        self.seconds = 0
        self.init_run()
        self.worktree = self.root / "wt-16"
        self.base = self.init_worktree(self.worktree, branch="issue-16")
        self.spawn(issue=16, worktree=str(self.worktree), budget_minutes=10)

    def tick(self):
        self.seconds += 1
        return f"2026-08-13T20:{self.seconds // 60:02d}:{self.seconds % 60:02d}Z"

    def attempt(self):
        return self.read_state()["issues"]["16"]["attempts"][-1]

    def launch(self):
        return f"16:1:{len(self.attempt()['launches'])}"

    def mark(self):
        return self.mark_progress(action_id=self.launch(), now=self.tick())

    def park(self):
        return self.suspend(issue=16, attempt=1, blocked_on="usage_limit",
                            now=self.tick())

    def wake(self):
        self.resume(issue=16, worktree=str(self.worktree), now=self.tick())

    def advance(self):
        head = self.commit(self.worktree)
        self.assertEqual(self.mark(), {"action_id": self.launch(),
                                       "outcome": "advanced", "marker": head})
        return head

    def assert_refused(self, action_id, clause, *, now=None):
        before = self.state_path.read_bytes()
        refused = self.mark_progress(action_id=action_id, now=now or self.tick(),
                                     ok=False)
        self.assertEqual(
            (refused.returncode, refused.stdout, self.state_path.read_bytes()),
            (2, "", before))
        self.assertIn("mark-progress refused: " + clause, refused.stderr)

    def assert_no_write(self, outcome, marker):
        before = self.state_path.read_bytes()
        self.assertEqual(self.mark(), {"action_id": self.launch(),
                                       "outcome": outcome, "marker": marker})
        self.assertEqual(self.state_path.read_bytes(), before)

    def assert_stalled(self, final):
        issue = self.read_state()["issues"]["16"]
        attempt = issue["attempts"][-1]
        self.assertEqual((attempt["state"], attempt["result_source"]),
                         ("stopped", "stalled"))
        self.assertIn("stalled without phase progress", attempt["result"]["notes"])
        self.assertEqual(issue["outcome"], attempt["result"])
        self.assertEqual(final, {
            "interface_version": 2, "kind": "terminal", "issue": 16,
            "run_id": self.run_id, "source": "lifecycle", "reason": "stopped",
            "blockers": [], "result": attempt["result"],
            "reentry": "/from-issue 16 --auto",
        })

    def stall_through(self, between):
        """Four suspensions, with `between()` run while each launch is active."""
        for _ in range(3):
            between()
            self.assertEqual(self.park()["kind"], "suspended")
            self.wake()
        between()
        self.assert_stalled(self.park())

    def test_outcomes_follow_the_ancestry_of_the_checked_out_commit(self):
        self.assertEqual(self.mark(), {"action_id": "16:1:1", "outcome": "baseline",
                                       "marker": self.base})
        self.assert_no_write("unchanged", self.base)
        second = self.advance()
        self.git(self.worktree, "reset", "--quiet", "--hard", self.base)
        self.assert_no_write("diverged", second)
        self.commit(self.worktree, "sibling")
        self.assert_no_write("diverged", second)
        self.git(self.worktree, "reset", "--quiet", "--hard", second)
        self.assert_no_write("unchanged", second)

    def test_a_baseline_keeps_the_stall_count_and_an_advance_clears_it(self):
        for _ in range(2):
            self.park()
            self.wake()
        self.assertEqual(self.mark()["outcome"], "baseline")
        before = self.attempt()
        self.assertEqual((before["stalled_resumes"], before["suspend_phase"]), (1, 0))
        head = self.commit(self.worktree)
        now = self.tick()
        self.assertEqual(
            self.mark_progress(action_id="16:1:3", now=now),
            {"action_id": "16:1:3", "outcome": "advanced", "marker": head})
        state = self.read_state()
        after = state["issues"]["16"]["attempts"][-1]
        self.assertEqual(state["updated_at"], now)
        self.assertEqual(
            (after["progress_marker"], after["stalled_resumes"], after["suspend_phase"]),
            (head, 0, None))
        written = {"progress_marker", "stalled_resumes", "suspend_phase"}
        self.assertEqual({name: value for name, value in after.items()
                          if name not in written},
                         {name: value for name, value in before.items()
                          if name not in written})

    def test_new_commits_between_suspensions_never_stall(self):
        self.progress(issue=16, phase=6, now=self.tick())
        self.assertEqual(self.mark()["outcome"], "baseline")
        for _ in range(5):
            self.advance()
            self.assertEqual(self.park()["kind"], "suspended")
            attempt = self.attempt()
            self.assertEqual((attempt["suspend_phase"], attempt["stalled_resumes"]),
                             (6, 0))
            self.wake()
        self.assertEqual(self.attempt()["state"], "active")

    def test_a_baseline_alone_still_stalls_at_the_fourth_suspension(self):
        self.stall_through(self.mark)

    def test_a_replayed_marker_still_stalls_at_the_fourth_suspension(self):
        self.mark()
        head = self.advance()
        self.stall_through(lambda: self.assert_no_write("unchanged", head))

    def test_rewinding_and_re_advancing_still_stalls_at_the_fourth_suspension(self):
        self.mark()
        head = self.advance()

        def rewind_and_return():
            self.git(self.worktree, "reset", "--quiet", "--hard", self.base)
            self.assert_no_write("diverged", head)
            self.git(self.worktree, "reset", "--quiet", "--hard", head)
            self.assert_no_write("unchanged", head)

        self.stall_through(rewind_and_return)

    def test_a_recording_refused_while_suspended_still_stalls(self):
        self.mark()
        for _ in range(3):
            self.assertEqual(self.park()["kind"], "suspended")
            self.commit(self.worktree)
            launch = self.launch()
            self.assert_refused(launch, f"launch {launch} is inactive_attempt")
            self.wake()
        self.assert_stalled(self.park())
        self.assert_refused("16:1:4", "launch 16:1:4 is inactive_attempt")
        self.assertEqual(self.attempt()["progress_marker"], self.base)

    def test_the_marker_survives_a_suspend_and_resume(self):
        self.mark()
        head = self.advance()
        self.park()
        self.assertEqual(self.attempt()["progress_marker"], head)
        # check-launch validates the stored ledger strictly on every read.
        self.assertEqual(self.check_launch(action_id="16:1:1")["reason"],
                         "inactive_attempt")
        self.wake()
        self.assertEqual(self.attempt()["progress_marker"], head)
        self.assert_no_write("unchanged", head)

    def test_expiry_demotions_after_new_commits_never_stall(self):
        observed = [self.worktree_fact(16, recorded={
            "path": str(self.worktree), "state": "matching_issue_branch"})]
        self.mark_progress(action_id="16:1:1", now="2026-08-13T20:01:00Z")
        for index, (marked_at, expired_at) in enumerate((
            ("2026-08-13T20:05:00Z", "2026-08-13T20:10:00Z"),
            ("2026-08-13T20:35:00Z", "2026-08-13T20:40:00Z"),
            ("2026-08-13T21:05:00Z", "2026-08-13T21:10:00Z"),
            ("2026-08-13T21:35:00Z", "2026-08-13T21:40:00Z"),
            ("2026-08-13T22:05:00Z", "2026-08-13T22:10:00Z"),
        )):
            self.commit(self.worktree)
            marked = self.mark_progress(action_id=f"16:1:{index + 1}", now=marked_at)
            self.assertEqual(marked["outcome"], "advanced")
            swept = self.control(
                now=expired_at, issues=[16], max_parallel=2,
                attempt_budget_minutes=30, tracker=[self.tracker_fact(16)],
                worktrees=observed)
            self.assertEqual(self.dispatch_action(swept, "resume")["id"],
                             f"16:1:{index + 2}")
            self.assertEqual(self.attempt()["stalled_resumes"], 0)

    def test_identity_and_clock_refusals_write_nothing(self):
        self.mark()
        for action_id, clause in (
            ("16:1:9", "launch 16:1:9 is superseded_launch"),
            ("16:2:1", "launch 16:2:1 is unknown_attempt"),
            ("99:1:1", "launch 99:1:1 is unknown_issue"),
            ("16:r1:1", "a remainder launch keeps its own bound"),
        ):
            with self.subTest(action_id=action_id):
                self.assert_refused(action_id, clause)
        self.assert_refused("16:1:1", "time must not move backward",
                            now="2026-08-13T19:59:00Z")
        before = self.state_path.read_bytes()
        malformed = self.mark_progress(action_id="16:1", now=self.tick(), ok=False)
        self.assertEqual((malformed.returncode, self.state_path.read_bytes()),
                         (2, before))
        absent = self.run_cli(
            "mark-progress", "--repo-root", self.root, "--run-id", "issue-99-absent",
            "--now", self.tick(), "--action-id", "16:1:1", ok=False)
        self.assertEqual(absent.returncode, 2)
        self.assertIn("mark-progress refused: launch 16:1:1 is unknown_run",
                      absent.stderr)
        self.park()
        self.wake()
        self.assert_refused("16:1:1", "launch 16:1:1 is superseded_launch")

    def test_worktree_probe_refusals_write_nothing(self):
        self.mark()
        self.git(self.worktree, "checkout", "--quiet", "--detach")
        self.assert_refused("16:1:1", "its HEAD is detached")
        self.git(self.worktree, "checkout", "--quiet", "issue-16")
        state = self.read_state()
        state["issues"]["16"]["attempts"][0]["progress_marker"] = "0" * 40
        self.write_state(state)
        self.commit(self.worktree)
        self.assert_refused("16:1:1", "git failed")  # a marker git does not know
        shutil.rmtree(self.worktree)
        self.assert_refused("16:1:1", "the worktree is absent")
        self.worktree.mkdir()
        self.assert_refused("16:1:1", "git failed")  # not a git repository
        self.git(self.worktree, "init", "--quiet", "--initial-branch", "issue-16")
        self.assert_refused("16:1:1", "git failed")  # an unborn branch: no commit

    def test_a_schema_five_ledger_records_a_baseline_and_upgrades(self):
        self.write_state(self._as_legacy(self.read_state(), 5))
        self.assertEqual(self.mark(), {"action_id": "16:1:1", "outcome": "baseline",
                                       "marker": self.base})
        state = self.read_state()
        self.assertEqual(
            (state["schema_version"],
             state["issues"]["16"]["attempts"][0]["progress_marker"]),
            (7, self.base))

    def race(self, module_name, interleave, *, now="2026-08-13T20:09:00Z"):
        """Run `mark-progress` in-process with `interleave()` between its probe and
        its transaction (#250 D14); returns the exit code, stderr and the ledger
        bytes `interleave()` left behind."""
        workflow = load_source_module(SCRIPT, module_name)
        probe = workflow.probe_progress_head
        left = {}

        def racing_probe(worktree, marker):
            observed = probe(worktree, marker)
            interleave()
            left["bytes"] = self.state_path.read_bytes()
            return observed

        stderr = io.StringIO()
        with mock.patch.object(workflow, "probe_progress_head", racing_probe), \
                contextlib.redirect_stderr(stderr):
            code = workflow.main([
                "mark-progress", "--repo-root", str(self.root), "--run-id",
                self.run_id, "--now", now, "--action-id", "16:1:1"])
        return code, stderr.getvalue(), left["bytes"]

    def test_a_marker_recorded_during_the_probe_refuses_the_stale_write(self):
        # A second recording lands between this call's probe and its transaction.
        code, stderr, left = self.race("workflow_state_progress_marker_race", self.mark)
        self.assertEqual((code, self.state_path.read_bytes()), (2, left))
        self.assertIn("mark-progress refused: the attempt changed during the probe",
                      stderr)
        self.assertEqual(self.attempt()["progress_marker"], self.base)

    def test_a_launch_suspended_during_the_probe_refuses_the_stale_write(self):
        # The marker and worktree still match what the probe used, and the new
        # commit would be `advanced`; only the locked launch re-check can refuse.
        self.mark()
        self.commit(self.worktree)
        code, stderr, left = self.race("workflow_state_progress_launch_race", self.park)
        self.assertEqual((code, self.state_path.read_bytes()), (2, left))
        self.assertIn("mark-progress refused: launch 16:1:1 is inactive_attempt", stderr)
        attempt = self.attempt()
        self.assertEqual(
            (attempt["state"], attempt["progress_marker"], attempt["suspend_phase"]),
            ("suspended", self.base, 0))


class ResumePackHarness(LifecycleHarness):
    """Issue 16's attempt on a real git worktree, and the `resume-pack` runners."""

    def setUp(self):
        super().setUp()
        self.seconds = 0
        self.init_run()
        self.make_worktree()
        self.spawn(issue=16, worktree=str(self.worktree), budget_minutes=10)

    def make_worktree(self):
        """Set `self.worktree` and its first commit `self.base`; Task 2 overrides it."""
        self.worktree = self.root / "wt-16"
        self.base = self.init_worktree(self.worktree, branch="issue-16")

    def tick(self):
        self.seconds += 1
        return f"2026-08-13T20:{self.seconds // 60:02d}:{self.seconds % 60:02d}Z"

    def attempt(self):
        return self.read_state()["issues"]["16"]["attempts"][-1]

    def pack_raw(self, action_id, *, run_id=None):
        return self.run_cli(
            "resume-pack", "--repo-root", self.root,
            "--run-id", self.run_id if run_id is None else run_id,
            "--action-id", action_id, ok=False)

    def pack(self, action_id):
        completed = self.pack_raw(action_id)
        self.assertEqual((completed.returncode, completed.stderr), (0, ""))
        return json.loads(completed.stdout)

    def assert_refused(self, action_id, clause, *, run_id=None):
        before = self.state_path.read_bytes()
        refused = self.pack_raw(action_id, run_id=run_id)
        self.assertEqual((refused.returncode, refused.stdout), (2, ""))
        self.assertIn("workflow-state: resume-pack refused: " + clause, refused.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def expected_ledger(self):
        attempt = self.attempt()
        return {"state": attempt["state"], "phase": attempt["phase"],
                "launch_kind": attempt["launch_kind"],
                "launches": len(attempt["launches"]),
                "deadline_at": attempt["deadline_at"],
                "blocked_on": attempt["blocked_on"],
                "handoff_path": attempt["handoff_path"],
                "progress_marker": attempt["progress_marker"]}

    def sdd_ledger(self, plan, entries, *, tasks=None):
        """Write a plan and its SDD ledger where `sdd-workspace` puts it (#265 D5)."""
        plan_path = Path(plan) if Path(plan).is_absolute() else self.worktree / plan
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text("# plan\n", encoding="utf-8")
        if tasks is not None:
            members = plan_path.parent / f"{plan_path.stem}.tasks"
            members.mkdir()
            for number in range(1, tasks + 1):
                (members / f"task-{number}.md").write_text("task\n", encoding="utf-8")
        workspace = subprocess.run(
            [str(SDD_WORKSPACE), plan], cwd=self.worktree, check=True,
            capture_output=True, text=True).stdout.strip()
        Path(workspace, "progress.md").write_text(
            "\n".join([f"# SDD ledger — plan: {plan}", *entries]) + "\n",
            encoding="utf-8")
        return workspace


class ResumePackTest(ResumePackHarness, unittest.TestCase):
    """#265: `resume-pack` summarises one launch for its relaunched owner."""

    def test_an_active_current_launch_packs_ledger_worktree_and_commits_ahead(self):
        self.mark_progress(action_id="16:1:1", now=self.tick())
        first = self.commit(self.worktree, "first task")
        second = self.commit(self.worktree, "second task")
        self.assertEqual(self.pack("16:1:1"), {
            "kind": "resume_pack", "version": 1, "run_id": self.run_id,
            "issue": 16, "attempt": 1, "action_id": "16:1:1", "current": True,
            "ledger": self.expected_ledger(),
            "worktree": {"path": self.attempt()["worktree"], "branch": "issue-16",
                         "head": second, "dirty_paths": 0},
            "commits_since_marker": {
                "base": self.base, "relation": "ahead", "count": 2,
                "commits": [{"sha": second[:12], "subject": "second task"},
                            {"sha": first[:12], "subject": "first task"}],
                "truncated": False},
            "sdd": None,
            "next_action": {"kind": "start_phase", "phase": 0},
        })
        self.assertEqual(self.expected_ledger()["progress_marker"], self.base)

    def test_relations_none_same_and_diverged(self):
        empty = {"count": 0, "commits": [], "truncated": False}
        pack = self.pack("16:1:1")
        self.assertEqual(pack["commits_since_marker"],
                         {"base": None, "relation": "none", **empty})
        self.mark_progress(action_id="16:1:1", now=self.tick())
        self.assertEqual(self.pack("16:1:1")["commits_since_marker"],
                         {"base": self.base, "relation": "same", **empty})
        moved = self.commit(self.worktree)
        self.mark_progress(action_id="16:1:1", now=self.tick())
        self.git(self.worktree, "reset", "--quiet", "--hard", self.base)
        pack = self.pack("16:1:1")
        self.assertEqual(pack["commits_since_marker"],
                         {"base": moved, "relation": "diverged", **empty})
        self.assertEqual(pack["next_action"],
                         {"kind": "reorient", "reason": "diverged_marker"})

    def test_dirty_paths_count_uncommitted_entries(self):
        (self.worktree / "a.txt").write_text("a\n", encoding="utf-8")
        (self.worktree / "b.txt").write_text("b\n", encoding="utf-8")
        self.assertEqual(self.pack("16:1:1")["worktree"]["dirty_paths"], 2)

    def test_a_suspended_attempt_previews_its_last_launch(self):
        self.mark_progress(action_id="16:1:1", now=self.tick())
        work = self.commit(self.worktree, "task one")
        self.suspend(issue=16, attempt=1, blocked_on="usage_limit", now=self.tick())
        pack = self.pack("16:1:1")
        self.assertEqual((pack["current"], pack["ledger"]),
                         (False, self.expected_ledger()))
        self.assertEqual((pack["ledger"]["state"], pack["ledger"]["blocked_on"]),
                         ("suspended", "usage_limit"))
        self.assertEqual(pack["commits_since_marker"]["commits"],
                         [{"sha": work[:12], "subject": "task one"}])
        self.assertEqual(pack["next_action"], {"kind": "start_phase", "phase": 0})
        self.assert_refused("16:1:2", "launch 16:1:2 is superseded_launch")
        self.resume(issue=16, worktree=str(self.worktree), now=self.tick())
        resumed = self.pack("16:1:2")
        self.assertEqual((resumed["current"], resumed["action_id"],
                          resumed["ledger"]["launch_kind"], resumed["ledger"]["launches"]),
                         (True, "16:1:2", "resume", 2))
        self.assertEqual(resumed["commits_since_marker"], pack["commits_since_marker"])
        self.assert_refused("16:1:1", "launch 16:1:1 is superseded_launch")

    def test_a_handoff_gate_points_at_its_handoff_until_the_next_gate(self):
        handoff = self.write_handoff(16)
        self.progress(issue=16, phase=1, now=self.tick(), turn_count=118,
                      handoff_path=handoff)
        stored = self.attempt()["handoff_path"]
        preview = self.pack("16:1:1")
        self.assertEqual((preview["current"], preview["ledger"]["state"]),
                         (False, "handed_off"))
        self.assertEqual(preview["next_action"], {"kind": "read_handoff", "path": stored})
        self.resume(issue=16, worktree=str(self.worktree), now=self.tick())
        self.assertEqual(self.pack("16:1:2")["next_action"],
                         {"kind": "read_handoff", "path": stored})
        self.progress(issue=16, phase=2, now=self.tick())
        pack = self.pack("16:1:2")
        self.assertEqual(pack["ledger"]["handoff_path"], stored)
        self.assertEqual(pack["next_action"], {"kind": "start_phase", "phase": 3})

    def test_phase_0_restarts_until_its_gate_is_recorded(self):
        # Final review C-001: a fresh attempt sits at phase 0 with no gate, so
        # an interrupted Phase 0 is unfinished, not complete.
        self.assertIsNone(self.attempt()["phase_action"])
        self.assertEqual(self.pack("16:1:1")["next_action"],
                         {"kind": "start_phase", "phase": 0})
        self.progress(issue=16, phase=0, now=self.tick())
        self.assertEqual(self.pack("16:1:1")["next_action"],
                         {"kind": "start_phase", "phase": 1})

    def test_a_completed_phase_7_reorients(self):
        self.progress(issue=16, phase=7, now=self.tick())
        self.assertEqual(self.pack("16:1:1")["next_action"],
                         {"kind": "reorient", "reason": "delivery_phases_complete"})

    def test_non_current_launches_are_refused_with_empty_stdout(self):
        self.assert_refused("16:1:2", "launch 16:1:2 is superseded_launch")
        self.assert_refused("16:2:1", "launch 16:2:1 is unknown_attempt")
        self.assert_refused("17:1:1", "launch 17:1:1 is unknown_issue")
        self.assert_refused("16:r1:1", "a remainder launch has no resume pack")
        self.assert_refused("16:1:1", "launch 16:1:1 is unknown_run",
                            run_id="issue-99-absent")
        malformed = self.pack_raw("16:1")
        self.assertEqual((malformed.returncode, malformed.stdout), (2, ""))
        self.assertIn("invalid action_id", malformed.stderr)
        self.fail_owner(issue=16, attempt=1, now=self.tick())
        self.assert_refused("16:1:1", "launch 16:1:1 is inactive_attempt")
        self.retry(issue=16, worktree=str(self.worktree), now=self.tick())
        self.assert_refused("16:1:1", "launch 16:1:1 is superseded_attempt")
        retried = self.pack("16:2:1")
        self.assertEqual((retried["attempt"], retried["current"]), (2, True))

    def test_an_unreadable_worktree_is_refused(self):
        self.git(self.worktree, "checkout", "--quiet", "--detach")
        self.assert_refused("16:1:1", "its HEAD is detached")
        shutil.rmtree(self.worktree)
        self.assert_refused("16:1:1", "the worktree is absent")

    def test_resume_pack_writes_nothing(self):
        tracked = self.worktree / "tracked.txt"
        tracked.write_text("one\n", encoding="utf-8")
        self.git(self.worktree, "add", "tracked.txt")
        self.commit(self.worktree, "tracked")
        tracked.write_text("two\n", encoding="utf-8")
        index = self.worktree / ".git" / "index"
        before = (self.state_path.read_bytes(), index.read_bytes(),
                  sorted(path.relative_to(self.root) for path in self.root.rglob("*")))
        self.assertEqual(self.pack("16:1:1")["worktree"]["dirty_paths"], 1)
        self.assert_refused("16:1:2", "launch 16:1:2 is superseded_launch")
        after = (self.state_path.read_bytes(), index.read_bytes(),
                 sorted(path.relative_to(self.root) for path in self.root.rglob("*")))
        self.assertEqual(after, before)
        self.assertFalse((self.worktree / ".superpowers").exists())

    def signed_commit(self, subject):
        """A commit carrying an SSH signature header, written without any key.

        `log.showSignature` prints its verification result (no allowed-signers
        file is configured, so "No signature") on stdout, even under `--format`.
        """
        tree = self.git(self.worktree, "rev-parse", "HEAD^{tree}")
        parent = self.git(self.worktree, "rev-parse", "HEAD")
        body = (f"tree {tree}\nparent {parent}\n"
                "author Fixture <fixture@example.test> 1700000000 +0000\n"
                "committer Fixture <fixture@example.test> 1700000000 +0000\n"
                "gpgsig -----BEGIN SSH SIGNATURE-----\n U1NIU0lH\n"
                " -----END SSH SIGNATURE-----\n\n" + subject + "\n")
        sha = subprocess.run(
            ["git", "-C", str(self.worktree), "hash-object", "-t", "commit", "-w",
             "--stdin"], input=body, check=True, capture_output=True,
            text=True).stdout.strip()
        self.git(self.worktree, "reset", "--quiet", "--hard", sha)
        return sha

    def test_the_commit_list_ignores_log_show_signature(self):
        # #265 D4: no signature line `log.showSignature` adds may become a commit.
        self.mark_progress(action_id="16:1:1", now=self.tick())
        first = self.signed_commit("first task")
        second = self.signed_commit("second task")
        self.git(self.worktree, "config", "log.showSignature", "true")
        self.assertIn("No signature", self.git(
            self.worktree, "log", "--max-count=1", "--format=%H%x1f%s"))
        self.assertEqual(self.pack("16:1:1")["commits_since_marker"], {
            "base": self.base, "relation": "ahead", "count": 2,
            "commits": [{"sha": second[:12], "subject": "second task"},
                        {"sha": first[:12], "subject": "first task"}],
            "truncated": False})

    def test_the_commit_list_is_bounded(self):
        self.mark_progress(action_id="16:1:1", now=self.tick())
        for number in range(25):
            self.commit(self.worktree, f"{number:02d} " + "x" * 150)
        completed = self.pack_raw("16:1:1")
        self.assertLess(len(completed.stdout.encode("utf-8")), 4096)
        section = json.loads(completed.stdout)["commits_since_marker"]
        self.assertEqual((section["count"], len(section["commits"]), section["truncated"]),
                         (25, 20, True))
        self.assertTrue(section["commits"][0]["subject"].startswith("24 "))
        self.assertEqual({len(commit["subject"]) for commit in section["commits"]}, {100})
        self.assertEqual({len(commit["sha"]) for commit in section["commits"]}, {12})

    def test_a_primary_checkout_reads_the_primary_bucket(self):
        workspace = self.sdd_ledger("plans/p.md", ["Task 1: complete (review clean)"])
        self.assertEqual(Path(workspace).parent.name, "primary")
        self.assertEqual(self.pack("16:1:1")["sdd"]["workspace"], workspace)


class ResumePackSddTest(ResumePackHarness, unittest.TestCase):
    """#265: the pack reads the attempt worktree's SDD bucket by sdd-workspace's rule."""

    COMPLETE = "Task {}: complete (commits aaaaaaa..bbbbbbb, review clean)"
    FIX = "Task {}: fix round 1/5 (1 addressed, 0 open — x; commits ccccccc..ddddddd)"

    def make_worktree(self):
        self.primary = self.root / "primary"
        self.init_worktree(self.primary, branch="main")
        self.worktree = self.primary / ".worktrees" / "wt-16"
        self.git(self.primary, "worktree", "add", "--quiet", "-b", "issue-16",
                 str(self.worktree))
        self.base = self.git(self.worktree, "rev-parse", "HEAD")

    def at_phase(self, phase):
        self.progress(issue=16, phase=phase, now=self.tick())

    def test_phase_5_with_a_task_mid_fix_loop_resumes_it(self):
        self.at_phase(5)
        entries = [self.COMPLETE.format(1), self.FIX.format(2)]
        workspace = self.sdd_ledger("plans/p.md", entries, tasks=3)
        self.assertEqual(Path(workspace).parent.name, "wt-wt-16")
        pack = self.pack("16:1:1")
        self.assertEqual(pack["sdd"], {"workspace": workspace, "plan": "plans/p.md",
                                       "task_count": 3, "completed": [1],
                                       "last_entry": self.FIX.format(2),
                                       "last_entry_truncated": False})
        self.assertEqual(pack["next_action"], {"kind": "resume_task", "phase": 6,
                                               "task": 2, "mid_fix_loop": True})

    def test_a_task_with_no_lines_starts_fresh(self):
        self.at_phase(5)
        self.sdd_ledger("plans/p.md", [self.FIX.format(1), self.COMPLETE.format(1)],
                        tasks=2)
        self.assertEqual(self.pack("16:1:1")["next_action"],
                         {"kind": "resume_task", "phase": 6, "task": 2,
                          "mid_fix_loop": False})

    def test_every_task_complete_finishes_phase_6(self):
        self.at_phase(5)
        self.sdd_ledger("plans/p.md", [self.COMPLETE.format(2), self.COMPLETE.format(1)],
                        tasks=2)
        pack = self.pack("16:1:1")
        self.assertEqual(pack["sdd"]["completed"], [1, 2])
        self.assertEqual(pack["next_action"], {"kind": "finish_phase", "phase": 6})

    def test_an_unknown_task_count_never_finishes(self):
        self.at_phase(5)
        self.sdd_ledger("plans/p.md", [self.COMPLETE.format(1), self.COMPLETE.format(2)])
        pack = self.pack("16:1:1")
        self.assertIsNone(pack["sdd"]["task_count"])
        self.assertEqual(pack["next_action"], {"kind": "resume_task", "phase": 6,
                                               "task": 3, "mid_fix_loop": False})

    def test_an_empty_task_member_directory_is_an_unknown_count(self):
        # Final review: zero members must never read as "every task complete".
        self.at_phase(5)
        self.sdd_ledger("plans/p.md", [], tasks=0)
        pack = self.pack("16:1:1")
        self.assertIsNone(pack["sdd"]["task_count"])
        self.assertEqual(pack["next_action"], {"kind": "resume_task", "phase": 6,
                                               "task": 1, "mid_fix_loop": False})

    def test_an_absolute_plan_path_is_used_as_is(self):
        self.at_phase(5)
        plan = str(self.worktree / "plans" / "p.md")
        self.sdd_ledger(plan, [self.COMPLETE.format(1)], tasks=1)
        pack = self.pack("16:1:1")
        self.assertEqual((pack["sdd"]["plan"], pack["sdd"]["task_count"]), (plan, 1))
        self.assertEqual(pack["next_action"], {"kind": "finish_phase", "phase": 6})

    def test_sdd_position_outside_phase_5_does_not_steer(self):
        self.sdd_ledger("plans/p.md", [self.FIX.format(1)], tasks=2)
        pack = self.pack("16:1:1")
        self.assertEqual(pack["sdd"]["completed"], [])
        self.assertEqual(pack["next_action"], {"kind": "start_phase", "phase": 0})

    def test_two_plan_ledgers_are_ambiguous(self):
        self.at_phase(5)
        self.sdd_ledger("plans/b.md", [self.COMPLETE.format(1)])
        self.sdd_ledger("plans/a.md", [self.COMPLETE.format(1)])
        pack = self.pack("16:1:1")
        self.assertEqual(pack["sdd"], {"ambiguous": ["a", "b"], "ambiguous_count": 2})
        self.assertEqual(pack["next_action"],
                         {"kind": "reorient", "reason": "ambiguous_sdd_workspace"})

    def test_a_ledger_naming_no_plan_is_not_a_ledger(self):
        workspace = self.sdd_ledger("plans/p.md", [self.COMPLETE.format(1)])
        Path(workspace, "progress.md").write_text("# notes\n", encoding="utf-8")
        self.assertIsNone(self.pack("16:1:1")["sdd"])

    def test_a_symlinked_bucket_is_refused(self):
        bucket = Path(self.sdd_ledger("plans/p.md", [])).parent
        shutil.rmtree(bucket)
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        bucket.symlink_to(elsewhere, target_is_directory=True)
        self.assert_refused("16:1:1", "the SDD workspace cannot be resolved")

    def test_the_last_entry_is_bounded(self):
        self.mark_progress(action_id="16:1:1", now=self.tick())
        for number in range(25):
            self.commit(self.worktree, f"{number:02d} " + "x" * 150)
        self.sdd_ledger("plans/p.md", [self.COMPLETE.format(1), "y" * 600], tasks=1)
        completed = self.pack_raw("16:1:1")
        self.assertLess(len(completed.stdout.encode("utf-8")), 4096)
        sdd = json.loads(completed.stdout)["sdd"]
        self.assertEqual((sdd["last_entry"], sdd["last_entry_truncated"]),
                         ("y" * 400, True))

    def test_unicode_ambiguous_names_shed_from_the_end(self):
        names = [f"{number}" + "\u00e9" * 99 for number in range(9)]
        for name in names:
            self.sdd_ledger(f"plans/{name}.md", [self.COMPLETE.format(1)])
        completed = self.pack_raw("16:1:1")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertLess(len(completed.stdout.encode("utf-8")), 4096)
        pack = json.loads(completed.stdout)
        kept = len(pack["sdd"]["ambiguous"])
        self.assertTrue(0 < kept < 8, kept)
        self.assertEqual(pack["sdd"], {"ambiguous": names[:kept], "ambiguous_count": 9})
        self.assertEqual(pack["next_action"],
                         {"kind": "reorient", "reason": "ambiguous_sdd_workspace"})
        pack["sdd"]["ambiguous"].append(names[kept])
        self.assertGreaterEqual(rendered_size(pack), 4096)

    def test_no_ledger_reads_create_nothing(self):
        self.assertIsNone(self.pack("16:1:1")["sdd"])
        self.assertFalse((self.primary / ".superpowers").exists())


def rendered_size(pack):
    """Bytes of `render_json(pack)`: sorted keys, compact, ASCII-escaped, newline."""
    return len(json.dumps(pack, sort_keys=True, separators=(",", ":")) + "\n")


class ResumePackBoundTest(ResumePackHarness, unittest.TestCase):
    """#265 D15: the rendered pack stays under 4096 bytes whatever its text escapes to."""

    DEPTH = 3

    def make_worktree(self):
        # Each component is 120 `é` (240 UTF-8 bytes, 720 escaped JSON bytes).
        self.worktree = self.root.joinpath(*["\u00e9" * 120] * self.DEPTH)
        self.base = self.init_worktree(self.worktree, branch="issue-16")

    def test_unicode_subjects_on_a_long_path_shed_the_oldest_commits(self):
        self.mark_progress(action_id="16:1:1", now=self.tick())
        commits = [self.commit(self.worktree, f"{number:02d} " + "\u00e9" * 150)
                   for number in range(25)]
        completed = self.pack_raw("16:1:1")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertLess(len(completed.stdout.encode("utf-8")), 4096)
        pack = json.loads(completed.stdout)
        section = pack["commits_since_marker"]
        kept = len(section["commits"])
        self.assertTrue(0 < kept < 20, kept)
        self.assertEqual((section["count"], section["truncated"]), (25, True))
        newest_first = [{"sha": sha[:12], "subject": f"{number:02d} " + "\u00e9" * 97}
                        for number, sha in reversed(list(enumerate(commits)))]
        self.assertEqual(section["commits"], newest_first[:kept])
        section["commits"].append(newest_first[kept])
        self.assertGreaterEqual(rendered_size(pack), 4096)

    def test_paths_that_cannot_fit_are_refused(self):
        self.sdd_ledger("plans/p.md", ["Task 1: complete (review clean)"], tasks=1)
        self.assert_refused("16:1:1", "the pack exceeds 4096 bytes")


class ResumePackEntryBoundTest(ResumePackHarness, unittest.TestCase):
    """#265 D15: a Unicode last entry on a long path is cut until the pack fits."""

    DEPTH = 1
    make_worktree = ResumePackBoundTest.make_worktree

    def test_a_unicode_last_entry_is_cut_to_the_byte_bound(self):
        self.progress(issue=16, phase=5, now=self.tick())
        entry = "\u00e9" * 400
        self.sdd_ledger("plans/p.md", ["Task 1: complete (review clean)", entry], tasks=2)
        completed = self.pack_raw("16:1:1")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertLess(len(completed.stdout.encode("utf-8")), 4096)
        pack = json.loads(completed.stdout)
        kept = pack["sdd"]["last_entry"]
        self.assertTrue(0 < len(kept) < 400 and entry.startswith(kept), len(kept))
        self.assertTrue(pack["sdd"]["last_entry_truncated"])
        self.assertEqual(pack["next_action"], {"kind": "resume_task", "phase": 6,
                                               "task": 2, "mid_fix_loop": False})
        pack["sdd"]["last_entry"] = entry[:len(kept) + 1]
        self.assertGreaterEqual(rendered_size(pack), 4096)


class OwnerExitFenceTest(LifecycleHarness, unittest.TestCase):
    """Owner-path writes that end a launch refuse while it has a live worker (#222)."""

    def spawn_with_worker(self):
        self.init_run()
        self.spawn(issue=14, worktree=str(self.root / "wt-14"))
        return self.register_worker(action_id="14:1:1",
                                    now="2026-08-13T20:01:00Z")["worker_id"]

    def assert_refused(self, completed, before, *workers):
        self.assertEqual((completed.returncode, completed.stdout), (2, ""))
        self.assertIn("live workers: " + ", ".join(workers), completed.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_suspend_refuses_until_the_worker_returns(self):
        worker = self.spawn_with_worker()
        before = self.state_path.read_bytes()
        self.assert_refused(
            self.suspend(issue=14, attempt=1, blocked_on="external",
                         now="2026-08-13T20:02:00Z", ok=False), before, worker)
        self.release_worker(worker_id=worker, event="returned",
                            now="2026-08-13T20:03:00Z")
        self.assertEqual(
            self.suspend(issue=14, attempt=1, blocked_on="external",
                         now="2026-08-13T20:03:00Z")["kind"], "suspended")

    def test_suspend_proceeds_once_the_worker_tree_is_stopped(self):
        worker = self.spawn_with_worker()
        child = self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z",
                                     parent=worker)["worker_id"]
        before = self.state_path.read_bytes()
        self.assert_refused(
            self.suspend(issue=14, attempt=1, blocked_on="agent_dispatch",
                         now="2026-08-13T20:02:00Z", ok=False), before, worker, child)
        self.release_worker(worker_id=worker, event="stopped",
                            now="2026-08-13T20:03:00Z")
        self.assertEqual(
            self.suspend(issue=14, attempt=1, blocked_on="agent_dispatch",
                         now="2026-08-13T20:03:00Z")["kind"], "suspended")

    def test_a_deadline_suspend_refuses_until_the_worker_is_released(self):
        worker = self.spawn_with_worker()
        before = self.state_path.read_bytes()
        self.assert_refused(
            self.suspend(issue=14, attempt=1, blocked_on="deadline",
                         now="2026-08-13T20:02:00Z", ok=False), before, worker)
        self.release_worker(worker_id=worker, event="stopped",
                            now="2026-08-13T20:03:00Z")
        self.assertEqual(
            self.suspend(issue=14, attempt=1, blocked_on="deadline",
                         now="2026-08-13T20:03:00Z")["blocked_on"], "deadline")

    def test_a_handoff_progress_refuses_but_plain_progress_does_not(self):
        worker = self.spawn_with_worker()
        self.progress(issue=14, phase=1, now="2026-08-13T20:02:00Z")
        handoff = self.write_handoff(14)
        before = self.state_path.read_bytes()
        self.assert_refused(
            self.progress(issue=14, phase=1, now="2026-08-13T20:03:00Z",
                          turn_count=118, handoff_path=handoff, ok=False),
            before, worker)
        self.release_worker(worker_id=worker, event="returned",
                            now="2026-08-13T20:04:00Z")
        handed = self.progress(issue=14, phase=1, now="2026-08-13T20:04:00Z",
                               turn_count=118, handoff_path=handoff)
        self.assertEqual(handed["action"], "handoff")

    def test_legacy_finish_refuses_until_the_worker_returns(self):
        worker = self.spawn_with_worker()
        # The harness `finish` round-trips through schema 2, which drops the
        # registry, so this case writes the contractless v5 state directly.
        state = self.read_state()
        state["issues"]["14"]["delivery"] = self.empty_delivery()
        state["issues"]["14"]["delivery_remainders"] = []
        self.write_state(state)
        result_path = self.root / "result-14-1.json"
        result_path.write_text(json.dumps({
            **self.merged_result(), "state": "failed", "pr_url": None,
            "merge_sha": None, "issue_closed": False, "notes": "owner failed"}),
            encoding="utf-8")

        def finish(now, ok):
            return self.run_cli("finish", "--repo-root", self.root, "--run-id",
                                self.run_id, "--issue", 14, "--attempt", 1,
                                "--result-file", result_path, "--now", now, ok=ok)

        before = self.state_path.read_bytes()
        self.assert_refused(finish("2026-08-13T20:02:00Z", False), before, worker)
        self.release_worker(worker_id=worker, event="returned",
                            now="2026-08-13T20:03:00Z")
        self.assertEqual(
            json.loads(finish("2026-08-13T20:03:00Z", True).stdout)["state"], "failed")

    def test_another_issues_worker_never_blocks(self):
        self.init_run()
        self.spawn(issue=14, worktree=str(self.root / "wt-14"))
        self.spawn(issue=15, worktree=str(self.root / "wt-15"))
        self.register_worker(action_id="15:1:1", now="2026-08-13T20:01:00Z")
        self.assertEqual(
            self.suspend(issue=14, attempt=1, blocked_on="external",
                         now="2026-08-13T20:02:00Z")["kind"], "suspended")


class PhaseGateReplyTest(LifecycleHarness, unittest.TestCase):
    """#191 D5: `progress` replies with one closed, validated `phase_gate`."""

    def test_each_action_names_its_custody_and_only_this_calls_handoff(self):
        self.init_run()
        worktree = self.root / "wt-14"
        self.spawn(issue=14, worktree=worktree)
        gate = {"interface_version": 2, "kind": "phase_gate", "run_id": self.run_id,
                "issue": 14, "custody": {"kind": "implementation", "attempt": 1,
                                         "launch": 1, "action_id": "14:1:1"},
                "handoff_path": None}
        for phase, overrides, action in (
                (1, {}, "continue"),
                (2, {"next_needs_context": False, "artifacts_sufficient": True}, "fresh_start"),
                (3, {"turn_count": 118}, "handoff"),
                (4, {"remainder_self_contained": True}, "delegate")):
            with self.subTest(action=action):
                reply = self.progress(phase=phase, now=f"2026-08-13T20:0{phase}:00Z",
                                      **overrides)
                self.assertEqual(reply, {**gate, "action": action})
                attempt = self.read_state()["issues"]["14"]["attempts"][0]
                self.assertEqual((attempt["phase"], attempt["phase_action"], attempt["state"]),
                                 (phase, action, "active"))
        handoff = self.write_handoff(14)
        finalized = self.progress(phase=5, now="2026-08-13T20:05:00Z", turn_count=118,
                                  handoff_path=handoff)
        self.assertEqual(finalized, {**gate, "action": "handoff", "handoff_path": str(handoff)})
        attempt = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual((attempt["state"], attempt["handoff_path"]),
                         ("handed_off", str(handoff)))
        self.resume(issue=14, worktree=worktree, now="2026-08-13T20:06:00Z")
        resumed = self.progress(phase=6, now="2026-08-13T20:07:00Z")
        self.assertEqual(resumed, {**gate, "action": "continue", "custody": {
            "kind": "implementation", "attempt": 1, "launch": 2, "action_id": "14:1:2"}})
        self.assertEqual(
            self.read_state()["issues"]["14"]["attempts"][0]["handoff_path"], str(handoff))

    def test_a_direct_run_replies_with_its_own_run_and_issue(self):
        owner = self.acquire_direct(issue=191)
        self.run_id = owner["run_id"]
        reply = self.progress(issue=191, phase=1, now="2026-08-20T10:05:00Z",
                              remainder_self_contained=True)
        self.assertEqual(reply, {
            "interface_version": 2, "kind": "phase_gate", "run_id": "direct-191-000001",
            "issue": 191, "custody": {"kind": "implementation", "attempt": 1,
                                      "launch": 1, "action_id": "191:1:1"},
            "action": "delegate", "handoff_path": None})


class SuspendReplyTest(LifecycleHarness, unittest.TestCase):
    """#191 D6: `suspend` replies with `suspended`, or the replay at the stall bound."""

    def test_a_direct_stall_bound_suspend_replies_with_the_next_replay(self):
        owner = self.acquire_direct(issue=16)
        self.run_id = owner["run_id"]
        recorded = {"path": owner["worktree"], "state": "matching_issue_branch"}
        for index in range(3):
            parked = self.suspend(issue=16, attempt=1, blocked_on="usage_limit",
                                  now=f"2026-08-20T10:0{2 * index + 1}:00Z")
            self.assertEqual(parked["custody"]["action_id"], f"16:1:{index + 1}")
            resumed = self.direct_owner(
                issue=16, now=f"2026-08-20T10:0{2 * index + 2}:00Z",
                worktree=self.worktree_fact(16, recorded=recorded))
            self.assertEqual(resumed["launch_kind"], "resume")
        stalled = self.suspend(issue=16, attempt=1, blocked_on="usage_limit",
                               now="2026-08-20T10:08:00Z")
        replay = self.direct_owner_at_root(
            self.root, self.direct_request(issue=16, now="2026-08-20T10:09:00Z"))
        self.assertEqual(stalled, self.validated_response(replay.stdout))
        self.assertEqual((stalled["kind"], stalled["source"], stalled["reason"]),
                         ("terminal", "lifecycle", "stopped"))
        persisted = json.loads(
            self.direct_state_path(owner["run_id"]).read_text())["issues"]["16"]
        self.assertEqual((persisted["attempts"][-1]["result_source"], persisted["outcome"]),
                         ("stalled", stalled["result"]))


class ReconciledReplyBoundaryTest(LifecycleHarness, unittest.TestCase):
    """#191: every reply that projects a reconciled merge passes the boundary."""

    MERGED_PR = {"state": "merged",
                 "url": "https://github.com/fagenorn/nix-config/pull/187",
                 "merge_sha": "bad94161012db5d285176762e4f4a9247d2f4d48"}
    # The record run-20260923-147-153-154-150-148-149-126-155 persisted for #154.
    RECONCILED_154 = {
        "issue": 154, "state": "merged",
        "pr_url": "https://github.com/fagenorn/nix-config/pull/187",
        "merge_sha": "bad94161012db5d285176762e4f4a9247d2f4d48",
        "issue_closed": False, "discussion_items": [],
        "detail_state": "none", "report_path": None,
        "notes": "reconciled from forge observation",
    }

    def contractless_sweep(self, issue, *, now, tracker_state="open"):
        """A validated sweep of a ledger with no delivery contract, the forge merged."""
        worktree = self.read_state()["issues"][str(issue)]["attempts"][-1]["worktree"]
        request = self.control_request(
            now=now, issues=[issue],
            tracker=[self.tracker_fact(issue, state=tracker_state)],
            worktrees=[self.worktree_fact(issue, recorded={
                "path": worktree, "state": "matching_issue_branch"})],
            max_parallel=1)
        request["delivery_contracts"][str(issue)] = None
        request["authorization_intents"][str(issue)] = []
        request["forge"][str(issue)] = copy.deepcopy(self.MERGED_PR)
        return self.control_validated(request=request)

    def test_control_relays_a_reconciled_merge_on_every_sweep(self):
        """Acceptance 1 (D2): reconciled, the result keeps `issue_closed` false and validates."""
        for tracker_state in ("closed", "open"):
            with self.subTest(tracker=tracker_state):
                self.run_id = f"reconcile-{tracker_state}"
                self.init_run()
                self.spawn(issue=47, worktree=self.root / f"wt-47-{tracker_state}")
                self.suspend(issue=47, attempt=1, blocked_on="usage_limit",
                             now="2026-08-13T20:02:00Z")
                state = self.read_state()
                state["issues"]["47"]["delivery"] = self.empty_delivery()
                self.write_state(state)
                for now in ("2026-08-13T20:03:00Z", "2026-08-13T20:04:00Z"):
                    summary = self.contractless_sweep(
                        47, now=now, tracker_state=tracker_state)["summaries"][0]
                    self.assertEqual(
                        (summary["state"], summary["result"]["state"],
                         summary["result"]["issue_closed"]), ("merged", "merged", False))
                attempt = self.read_state()["issues"]["47"]["attempts"][-1]
                self.assertEqual((attempt["state"], attempt["result_source"]),
                                 ("merged", "superseded"))

    def test_control_relays_the_persisted_154_record(self):
        """Acceptance 2 (D4): the shape run-…-155 holds for #154 validates, unmigrated."""
        self.run_id = "run-20260923-147-153-154-150-148-149-126-155"
        self.init_run()
        self.spawn(issue=154, worktree=self.root / "worktree-issue-154")
        self.suspend(issue=154, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:02:00Z")
        state = self.read_state()
        issue = state["issues"]["154"]
        attempt = issue["attempts"][-1]
        attempt.update({"state": "merged", "blocked_on": None,
                        "result": copy.deepcopy(self.RECONCILED_154),
                        "finished_at": "2026-08-13T20:05:00Z",
                        "result_source": "superseded"})
        issue["outcome"] = copy.deepcopy(self.RECONCILED_154)
        issue["delivery"] = self.empty_delivery()
        self.write_state(state)
        before = self.state_path.read_bytes()
        response = self.contractless_sweep(154, now="2026-08-13T20:06:00Z")
        self.assertEqual(response["summaries"][0]["result"], self.RECONCILED_154)
        self.assertEqual(
            json.loads(self.state_path.read_bytes())["issues"]["154"]["attempts"],
            json.loads(before)["issues"]["154"]["attempts"])

    def test_direct_replays_of_a_reconciled_merge_validate(self):
        """Acceptance 2 (D4): raw direct replays validate, bare or carrying a superseded pointer."""
        durable = ".superpowers/issue-delivery/154/run-1/ship-review.json"
        retained = ".superpowers/ship-review/154/retained-detail.json"
        for detail_state, report_path in (("none", None), ("present", durable),
                                          ("unpublished", retained)):
            with self.subTest(detail_state=detail_state):
                root = self.root / f"direct-{detail_state}"
                root.mkdir()
                root = root.resolve()
                self.root = root
                owner = self.acquire_direct(issue=154)
                if report_path is not None:
                    verdict = {**self.RECONCILED_154, "state": "failed", "pr_url": None,
                               "merge_sha": None, "detail_state": detail_state,
                               "report_path": report_path,
                               "notes": f"owner verdict; details: {report_path}"}
                    path = self.direct_state_path(owner["run_id"])
                    state = json.loads(path.read_text())
                    attempt = state["issues"]["154"]["attempts"][-1]
                    attempt.update({"state": "failed", "blocked_on": None,
                                    "result": copy.deepcopy(verdict),
                                    "finished_at": "2026-08-20T10:30:00Z",
                                    "result_source": "owner"})
                    state["issues"]["154"]["outcome"] = copy.deepcopy(verdict)
                    path.write_text(json.dumps(state), encoding="utf-8")
                else:
                    self.run_id = owner["run_id"]
                    self.suspend(issue=154, attempt=1, blocked_on="human_gate",
                                 now="2026-08-20T10:30:00Z")
                replies = []
                for now, forge in (("2026-08-20T11:00:00Z", self.MERGED_PR),
                                   ("2026-08-20T11:05:00Z", self.no_pull_request())):
                    request = self.direct_request(
                        issue=154, now=now, forge=copy.deepcopy(forge),
                        worktree=self.worktree_fact(154, recorded={
                            "path": owner["worktree"], "state": "matching_issue_branch"}))
                    completed = self.direct_owner_at_root(root, request)
                    replies.append(self.validated_response(completed.stdout))
                reconciled, replayed = replies
                self.assertEqual((replayed["kind"], replayed["reason"]), ("terminal", "merged"))
                self.assertEqual(replayed, reconciled)
                result = replayed["result"]
                self.assertEqual((result["issue_closed"], result["detail_state"],
                                  result["report_path"]), (False, detail_state, report_path))
                if report_path is None:
                    self.assertEqual(result, self.RECONCILED_154)


class ResolverOutcomeTest(unittest.TestCase):
    """D2: resolver outcomes no real resolver produces are failures, never refusals."""

    @classmethod
    def setUpClass(cls):
        cls.workflow = load_source_module(SCRIPT, "workflow_state_resolver_outcome")

    def message(self, returncode, stdout, stderr):
        completed = subprocess.CompletedProcess(
            ["resolve-project", "resolve"], returncode, stdout, stderr)
        with self.assertRaises(self.workflow.WorkflowError) as caught:
            self.workflow.classify_resolver_outcome(completed, "worktree")
        return str(caught.exception)

    def test_non_conforming_outcomes_are_failures_carrying_the_resolver_body(self):
        refusal = (b'{"error":{"code":"not_onboarded","repair_id":"r",'
                   b'"violations":[{"message":"m","pointer":""}]}}\n')
        cases = (
            ("non-JSON stdout on exit 1", 1, b"Traceback: boom\n", b"stack\n",
             r'{"exit":1,"stderr":"stack\n","stdout":"Traceback: boom\n"}'),
            ("a non-object on exit 0", 0, b"[1, 2]\n", b"",
             r'{"exit":0,"stderr":"","stdout":"[1, 2]\n"}'),
            ("a refusal missing members", 2, b'{"error":{"code":"invalid_contract"}}\n', b"",
             r'{"exit":2,"stderr":"","stdout":"{\"error\":{\"code\":\"invalid_contract\"}}\n"}'),
            ("an unknown error member", 2,
             b'{"error":{"code":"c","hint":"h","repair_id":"r","violations":[]}}', b"",
             r'{"exit":2,"stderr":"","stdout":"{\"error\":{\"code\":\"c\",\"hint\":\"h\",'
             r'\"repair_id\":\"r\",\"violations\":[]}}"}'),
            ("a violation missing its message", 2,
             b'{"error":{"code":"c","repair_id":"r","violations":[{"pointer":"/a"}]}}', b"",
             r'{"exit":2,"stderr":"","stdout":"{\"error\":{\"code\":\"c\",\"repair_id\":\"r\",'
             r'\"violations\":[{\"pointer\":\"/a\"}]}}"}'),
            ("non-JSON stdout on exit 0", 0, b"not json\n", b"",
             r'{"exit":0,"stderr":"","stdout":"not json\n"}'),
            ("non-JSON stdout on exit 2", 2, b"not json\n", b"",
             r'{"exit":2,"stderr":"","stdout":"not json\n"}'),
            ("a refusal document that is not an object", 2, b'["error"]', b"",
             r'{"exit":2,"stderr":"","stdout":"[\"error\"]"}'),
            ("an extra top-level member", 2,
             b'{"error":{"code":"c","repair_id":"r","violations":[]},"x":1}', b"",
             r'{"exit":2,"stderr":"","stdout":"{\"error\":{\"code\":\"c\",\"repair_id\":\"r\",'
             r'\"violations\":[]},\"x\":1}"}'),
            ("an error that is not an object", 2, b'{"error":1}', b"",
             r'{"exit":2,"stderr":"","stdout":"{\"error\":1}"}'),
            ("a non-string code", 2,
             b'{"error":{"code":1,"repair_id":"r","violations":[]}}', b"",
             r'{"exit":2,"stderr":"","stdout":"{\"error\":{\"code\":1,\"repair_id\":\"r\",'
             r'\"violations\":[]}}"}'),
            ("a non-string repair_id", 2,
             b'{"error":{"code":"c","repair_id":null,"violations":[]}}', b"",
             r'{"exit":2,"stderr":"","stdout":"{\"error\":{\"code\":\"c\",\"repair_id\":null,'
             r'\"violations\":[]}}"}'),
            ("a non-string reason_code", 2,
             b'{"error":{"code":"c","reason_code":2,"repair_id":"r","violations":[]}}', b"",
             r'{"exit":2,"stderr":"","stdout":"{\"error\":{\"code\":\"c\",\"reason_code\":2,'
             r'\"repair_id\":\"r\",\"violations\":[]}}"}'),
            ("violations that are not a list", 2,
             b'{"error":{"code":"c","repair_id":"r","violations":{}}}', b"",
             r'{"exit":2,"stderr":"","stdout":"{\"error\":{\"code\":\"c\",\"repair_id\":\"r\",'
             r'\"violations\":{}}}"}'),
            ("a violation that is not an object", 2,
             b'{"error":{"code":"c","repair_id":"r","violations":[1]}}', b"",
             r'{"exit":2,"stderr":"","stdout":"{\"error\":{\"code\":\"c\",\"repair_id\":\"r\",'
             r'\"violations\":[1]}}"}'),
            ("a non-string violation pointer", 2,
             b'{"error":{"code":"c","repair_id":"r","violations":[{"message":"m","pointer":0}]}}',
             b"",
             r'{"exit":2,"stderr":"","stdout":"{\"error\":{\"code\":\"c\",\"repair_id\":\"r\",'
             r'\"violations\":[{\"message\":\"m\",\"pointer\":0}]}}"}'),
            ("a well-formed refusal on exit 1", 1, refusal, b"",
             r'{"exit":1,"stderr":"","stdout":"{\"error\":{\"code\":\"not_onboarded\",'
             r'\"repair_id\":\"r\",\"violations\":[{\"message\":\"m\",\"pointer\":\"\"}]}}\n"}'),
            ("undecodable bytes", 1, b"\xff\n", b"\xfe",
             r'{"exit":1,"stderr":"\ufffd","stdout":"\ufffd\n"}'),
        )
        for label, returncode, stdout, stderr, body in cases:
            with self.subTest(label=label):
                self.assertEqual(self.message(returncode, stdout, stderr),
                                 "resolve-project failed at worktree: " + body)

    def test_a_timeout_is_reported_as_a_timeout_at_its_label(self):
        expired = subprocess.TimeoutExpired(["resolve-project", "resolve"], 60)
        with mock.patch.object(self.workflow.subprocess, "run", side_effect=expired):
            with self.assertRaises(self.workflow.WorkflowError) as caught:
                self.workflow.resolve_project_policy("/nonexistent/ledger", "repo-root")
        self.assertEqual(str(caught.exception), "resolve-project timed out at repo-root")


class ArtifactBudgetPolicyResolutionTest(unittest.TestCase):
    """Cover the installed layout, where the policy is a home-manager symlink."""

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_installed_symlinked_policy_validates_a_terminal_result(self):
        scripts = Path(__file__).parents[1] / "scripts"
        policy = Path(__file__).parents[1] / "artifact-budget-policy.json"
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            binaries = home / ".agents/bin"
            library = home / ".agents/lib/python"
            share = home / ".agents/share"
            for directory in (binaries, library, share):
                directory.mkdir(parents=True)
            installed_script = binaries / "workflow-state.py"
            installed_script.write_bytes((scripts / "workflow-state.py").read_bytes())
            wrapper = binaries / "artifact-budget"
            wrapper.write_bytes((scripts / "artifact-budget").read_bytes())
            wrapper.chmod(0o755)
            (library / "artifact_budget.py").write_bytes(
                (scripts / "artifact_budget.py").read_bytes()
            )
            (library / "workflow_delivery.py").write_bytes(
                (scripts / "workflow_delivery.py").read_bytes()
            )
            shutil.copytree(scripts / "delivery_model", library / "delivery_model")
            # home-manager installs the policy as a store symlink, never a copy.
            (share / "artifact-budget-policy.json").symlink_to(policy)

            probe = (
                "import importlib.util, json, sys\n"
                "spec = importlib.util.spec_from_file_location('ws', sys.argv[1])\n"
                "module = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(module)\n"
                "_, resolved = module.artifact_budget_paths()\n"
                "summary = module.terminal_result(1320, 'stopped', 'attempt deadline expired')\n"
                "print(json.dumps({'policy': str(resolved), 'state': summary['state']}))\n"
            )
            completed = subprocess.run(
                [sys.executable, "-c", probe, str(installed_script)],
                capture_output=True, text=True, check=False,
                env={**os.environ, "HOME": str(home)},
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            observed = json.loads(completed.stdout)
            self.assertEqual(observed["state"], "stopped")
            # The explicit --policy argument must name the resolved regular file:
            # artifact-budget refuses a symlink passed as --policy.
            self.assertFalse(Path(observed["policy"]).is_symlink())
            self.assertEqual(
                Path(observed["policy"]).resolve(), policy.resolve()
            )


if DeliveredControlHarness is not None:
    class HeldControlTest(DeliveredControlHarness, unittest.TestCase):
        """#273 AC2: a held delivery holds no custody, reads `held`, and is never relaunched."""

        def summaries(self, response):
            return {item["issue"]: item for item in response["summaries"]}

        def test_a_held_delivery_is_never_relaunched_and_reads_held(self):
            self.deliver_through_remainder(held=True)
            before = self.records(DELIVERED)
            # Minute 275 is past r1's deadline (274); 209 depends on held 207.
            response = self.control(275, recorded={DELIVERED: "absent", LIVE: None},
                                    contracts=True, blockers={LIVE: [DELIVERED]})
            self.assertEqual([a for a in response["actions"] if a.get("issue") == DELIVERED], [])
            self.assertEqual([d for d in response["deltas"] if d["issue"] == DELIVERED], [])
            self.assertEqual([a for a in response["actions"] if a["kind"] in DISPATCH], [])
            self.assertNotIn(DELIVERED, response["admission"]["waiting"])
            held = self.summaries(response)[DELIVERED]
            # Summary custody keeps #220 D4's diagnostic projection unchanged (it may
            # name a stale nonterminal record); "no current custody" is proven by the
            # empty dispatch actions above and the null owner below (PR273-1).
            self.assertEqual((held["state"], held["owner"],
                              held["pending_stage_ids"], held["requirements"]),
                             ("held", None, [], []))
            self.assertIsNotNone(held["contract_digest"])
            dependent = self.summaries(response)[LIVE]
            self.assertEqual(dependent["state"], "blocked")
            self.assertEqual(dependent["blockers"],
                             [{"kind": "issue", "issue": DELIVERED, "url": None}])
            self.assertEqual(self.records(DELIVERED), before)

        def test_a_held_issue_a_human_closed_reads_closed(self):
            self.deliver_through_remainder(held=True)
            response = self.control(275, recorded={DELIVERED: "absent"}, contracts=True,
                                    closed={DELIVERED})
            self.assertEqual(self.summaries(response)[DELIVERED]["state"], "closed")

        def test_only_a_held_observation_projects_held(self):
            # D15, D18: a tracker_closed delivery whose tracker reads open is not held.
            self.deliver_through_remainder(held=False)
            response = self.control(275, recorded={DELIVERED: "absent"}, contracts=True)
            self.assertEqual(self.summaries(response)[DELIVERED]["state"], "queued")


class LedgerClockSeamTest(LifecycleHarness, unittest.TestCase):
    """#309 D1, D2, D11: one clock seam, and an override that can only pin the present or past."""

    CLOCK_CALLS = frozenset({("datetime", "now"), ("datetime", "utcnow"), ("datetime", "today"),
                             ("date", "today"), ("time", "time"), ("time", "time_ns")})

    def setUp(self):
        super().setUp()
        self.cli_env.pop("WORKFLOW_STATE_TEST_CLOCK", None)

    def init_without_time(self):
        return self.run_cli("init-run", "--repo-root", self.root, "--run-id", self.run_id,
                            ok=False)

    def test_an_override_later_than_the_clock_is_refused(self):
        self.cli_env["WORKFLOW_STATE_TEST_CLOCK"] = "2999-01-01T00:00:00Z"
        refused = self.init_without_time()
        self.assertEqual((refused.returncode, refused.stdout), (2, ""))
        self.assertRegex(refused.stderr,
                         r"^workflow-state: invalid WORKFLOW_STATE_TEST_CLOCK: "
                         r"2999-01-01T00:00:00Z is later than the clock "
                         r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n$")
        self.assertFalse(self.state_path.exists())

    def test_a_malformed_override_is_refused(self):
        for value in ("yesterday", "2026-08-13T20:00:00"):
            with self.subTest(value=value):
                self.cli_env["WORKFLOW_STATE_TEST_CLOCK"] = value
                refused = self.init_without_time()
                self.assertEqual(
                    (refused.returncode, refused.stdout, refused.stderr),
                    (2, "", "workflow-state: invalid WORKFLOW_STATE_TEST_CLOCK: "
                            "expected an RFC3339 UTC timestamp\n"))
                self.assertFalse(self.state_path.exists())

    def test_the_override_pins_the_stamp_and_an_empty_one_is_the_clock(self):
        self.cli_env["WORKFLOW_STATE_TEST_CLOCK"] = "2026-09-30T12:00:00Z"
        self.assertEqual(self.init_without_time().returncode, 0)
        self.assertEqual(self.read_state()["updated_at"], "2026-09-30T12:00:00Z")
        self.run_id = "issue-14-empty-override"
        self.cli_env["WORKFLOW_STATE_TEST_CLOCK"] = ""
        self.assertEqual(self.init_without_time().returncode, 0)
        stamp = datetime.fromisoformat(self.read_state()["updated_at"].replace("Z", "+00:00"))
        self.assertLessEqual(abs((datetime.now(timezone.utc) - stamp).total_seconds()), 5)

    def sites(self, path):
        """(kind, innermost enclosing function name) for each clock call and override literal."""
        found = []

        def visit(node, owner):
            for child in ast.iter_child_nodes(node):
                inner = (child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                         else owner)
                if isinstance(child, ast.Constant) and child.value == "WORKFLOW_STATE_TEST_CLOCK":
                    found.append(("override", owner))
                if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                        and isinstance(child.func.value, ast.Name)
                        and (child.func.value.id, child.func.attr) in self.CLOCK_CALLS):
                    found.append(("clock", owner))
                visit(child, inner)

        visit(ast.parse(path.read_text(encoding="utf-8")), None)
        return found

    def test_only_ledger_clock_reads_the_clock_or_the_override(self):
        scripts = SCRIPT.parent
        self.assertEqual(set(self.sites(SCRIPT)),
                         {("override", "ledger_clock"), ("clock", "ledger_clock")})
        others = [*sorted(scripts.glob("workflow_delivery*.py")),
                  *sorted((scripts / "delivery_model").glob("*.py"))]
        self.assertTrue(others)
        for path in others:
            with self.subTest(path=path.name):
                self.assertEqual(self.sites(path), [])


class OwnerLivenessTest(LifecycleHarness, unittest.TestCase):
    """#310 D2-D5, D10, D11: workflow-state owner-liveness."""

    SKEW = ("workflow-state: --since {s} is {n} seconds ahead of the clock {c}; a supplied "
            "time may lead it by at most 60 seconds — omit it to use the clock\n")

    def setUp(self):
        super().setUp()
        self.init_run()
        self.worktrees = {n: str(self.root / f"wt-{n}") for n in (14, 16)}
        response = self.control(
            now=DEFAULT_NOW, issues=[14, 16], max_parallel=2, attempt_budget_minutes=180,
            tracker=[self.tracker_fact(n) for n in (14, 16)],
            worktrees=[self.worktree_fact(n, candidate={"path": self.worktrees[n],
                                                         "state": "absent"})
                       for n in (14, 16)])
        self.assertEqual([a["id"] for a in response["actions"] if a["kind"] == "spawn"],
                         ["14:1:1", "16:1:1"])

    def inventory(self):
        return (self.state_path.read_bytes(),
                sorted(p.relative_to(self.root) for p in self.root.rglob("*")))

    def call(self, clock, *, action_id="14:1:1", stall="30", since=None, run_id=None):
        # The pinned clock is scoped to this one call, so later ledger writes in
        # the same test are skew-checked against the real clock (PR310-02).
        previous = self.cli_env.get("WORKFLOW_STATE_TEST_CLOCK")
        self.cli_env["WORKFLOW_STATE_TEST_CLOCK"] = clock
        args = ["owner-liveness", "--repo-root", self.root,
                "--run-id", self.run_id if run_id is None else run_id,
                "--action-id", action_id, "--stall-minutes", stall]
        if since is not None:
            args += ["--since", since]
        try:
            before = self.inventory()
            completed = self.run_cli(*args, ok=False)
            self.assertEqual(self.inventory(), before)
        finally:
            if previous is None:
                self.cli_env.pop("WORKFLOW_STATE_TEST_CLOCK", None)
            else:
                self.cli_env["WORKFLOW_STATE_TEST_CLOCK"] = previous
        return completed

    def liveness(self, clock, **kwargs):
        completed = self.call(clock, **kwargs)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return self.validated_response(completed.stdout)

    def reply(self, verdict, since, progress_at, stall_at, wait, *, action_id="14:1:1",
              reason="current"):
        return {"interface_version": 1, "kind": "owner_liveness", "action_id": action_id,
                "reason": reason, "verdict": verdict, "since": since,
                "progress_at": progress_at, "stall_at": stall_at, "wait_seconds": wait}

    def assert_refused(self, completed, stderr):
        self.assertEqual((completed.returncode, completed.stdout, completed.stderr),
                         (2, "", stderr))

    def test_live_names_the_seconds_left_from_the_clock(self):
        self.assertEqual(self.liveness("2026-08-13T20:10:07Z"), self.reply(
            "live", "2026-08-13T20:10:07Z", "2026-08-13T20:00:00Z",
            "2026-08-13T20:40:07Z", 1800))
        # A since ahead of the clock (within the skew) lengthens the wait past the bound.
        self.assertEqual(
            self.liveness("2026-08-13T20:10:07Z", since="2026-08-13T20:10:37Z"),
            self.reply("live", "2026-08-13T20:10:37Z", "2026-08-13T20:00:00Z",
                       "2026-08-13T20:40:37Z", 1830))

    def test_stalled_exactly_at_stall_at(self):
        since = "2026-08-13T20:10:00Z"
        self.assertEqual(self.liveness("2026-08-13T20:39:59Z", since=since), self.reply(
            "live", since, "2026-08-13T20:00:00Z", "2026-08-13T20:40:00Z", 1))
        self.assertEqual(self.liveness("2026-08-13T20:40:00Z", since=since), self.reply(
            "stalled", since, "2026-08-13T20:00:00Z", "2026-08-13T20:40:00Z", None))

    def test_past_deadline_wins_over_stalled(self):
        since = "2026-08-13T20:10:00Z"
        self.assertEqual(self.liveness("2026-08-13T22:59:59Z", since=since)["verdict"],
                         "stalled")
        self.assertEqual(self.liveness("2026-08-13T23:00:00Z", since=since), self.reply(
            "past_deadline", since, "2026-08-13T20:00:00Z", "2026-08-13T20:40:00Z", None))

    def test_a_since_later_than_progress_moves_stall_at(self):
        self.assertEqual(
            self.liveness("2026-08-13T20:30:00Z", since="2026-08-13T20:20:00Z")["stall_at"],
            "2026-08-13T20:50:00Z")
        self.assertEqual(self.liveness("2026-08-13T20:30:00Z")["stall_at"],
                         "2026-08-13T21:00:00Z")

    def test_only_this_launchs_workers_move_progress(self):
        worker = self.register_worker(action_id="14:1:1", now="2026-08-13T20:20:00Z")
        self.assertEqual(self.liveness("2026-08-13T20:21:00Z", since=DEFAULT_NOW)
                         ["progress_at"], "2026-08-13T20:20:00Z")
        self.release_worker(worker_id=worker["worker_id"], event="returned",
                            now="2026-08-13T20:25:00Z")
        self.register_worker(action_id="16:1:1", now="2026-08-13T20:30:00Z")
        ours = self.liveness("2026-08-13T20:31:00Z", since=DEFAULT_NOW)
        self.assertEqual((ours["progress_at"], ours["stall_at"]),
                         ("2026-08-13T20:25:00Z", "2026-08-13T20:55:00Z"))
        theirs = self.liveness("2026-08-13T20:31:00Z", action_id="16:1:1", since=DEFAULT_NOW)
        self.assertEqual(theirs["progress_at"], "2026-08-13T20:30:00Z")

    def test_fractional_stored_progress_is_truncated_and_never_rewritten(self):
        # PR310-01: a supplied fractional --now is stored as given; the reply
        # truncates it to whole seconds and passes the boundary unchanged.
        self.progress(issue=14, phase=1, now="2026-08-13T20:15:00.750000Z")
        stored = self.state_path.read_bytes()
        reply = self.liveness("2026-08-13T20:16:00Z", since=DEFAULT_NOW)
        self.assertEqual((reply["progress_at"], reply["stall_at"], reply["wait_seconds"]),
                         ("2026-08-13T20:15:00Z", "2026-08-13T20:45:00Z", 1740))
        self.assertEqual(self.state_path.read_bytes(), stored)

    def test_recorded_progress_moves_progress(self):
        self.progress(issue=14, phase=1, now="2026-08-13T20:15:00Z")
        self.assertEqual(self.read_state()["issues"]["14"]["attempts"][-1]["last_progress_at"],
                         "2026-08-13T20:15:00Z")
        self.assertEqual(self.liveness("2026-08-13T20:16:00Z", since=DEFAULT_NOW)
                         ["progress_at"], "2026-08-13T20:15:00Z")

    def test_a_launch_that_is_not_current_is_not_current(self):
        self.assertEqual(
            self.liveness("2026-08-13T20:10:00Z", run_id="no-such-run"),
            self.reply("not_current", "2026-08-13T20:10:00Z", None, None, None,
                       reason="unknown_run"))
        self.suspend(issue=14, attempt=1, blocked_on="transport", now="2026-08-13T20:05:00Z")
        self.resume(issue=14, worktree=self.worktrees[14], now="2026-08-13T20:06:00Z")
        self.assertEqual(self.liveness("2026-08-13T20:10:00Z")["reason"], "superseded_launch")
        self.assertEqual(self.liveness("2026-08-13T20:10:00Z")["verdict"], "not_current")
        resumed = self.liveness("2026-08-13T20:10:00Z", action_id="14:1:2")
        self.assertEqual((resumed["verdict"], resumed["progress_at"]),
                         ("live", "2026-08-13T20:06:00Z"))

    def test_malformed_arguments_are_refused_without_a_write(self):
        clock = "2026-08-13T20:10:00Z"
        for stall in ("0", "-1", "01", "1.5", "abc", "", "1234567890"):
            with self.subTest(stall=stall):
                self.assert_refused(self.call(clock, stall=stall), "workflow-state: invalid "
                                    "--stall-minutes: expected a positive integer\n")
        for since in ("yesterday", "2026-08-13T20:10:00.5Z", "2026-08-13T20:10:00+00:00"):
            with self.subTest(since=since):
                self.assert_refused(self.call(clock, since=since), "workflow-state: invalid "
                                    "--since: expected an RFC3339 UTC timestamp\n")
        self.assert_refused(self.call(clock, action_id="14:1"),
                            "workflow-state: invalid action_id\n")
        self.assert_refused(self.call(clock, run_id="bad/run"),
                            "workflow-state: invalid run_id\n")

    def test_a_since_over_the_skew_bound_is_refused(self):
        clock = "2026-08-13T20:10:00Z"
        self.assertEqual(self.liveness(clock, since="2026-08-13T20:11:00Z")["since"],
                         "2026-08-13T20:11:00Z")
        self.assert_refused(self.call(clock, since="2026-08-13T20:11:01Z"), self.SKEW.format(
            s="2026-08-13T20:11:01Z", n=61, c=clock))

    def test_the_boundary_refuses_a_mutated_reply(self):
        live = self.liveness("2026-08-13T20:10:00Z")
        stalled = self.liveness("2026-08-13T20:40:00Z", since="2026-08-13T20:10:00Z")
        for name, value in (("stall_at_off_minute", {**live, "stall_at": "2026-08-13T20:40:30Z"}),
                            ("wait_on_stalled", {**stalled, "wait_seconds": 60})):
            with self.subTest(name=name):
                checked = subprocess.run(
                    [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
                     "workflow-response", "--input", "-", "--policy", str(BUDGET_POLICY)],
                    input=json.dumps(value), capture_output=True, text=True, check=False,
                    env=self.cli_env)
                self.assertEqual(checked.returncode, 2)


class ControlWaitSecondsTest(LifecycleHarness, unittest.TestCase):
    """#310 D9: control computes the wait observer's sleep."""

    def wait_action(self, response):
        waits = [a for a in response["actions"] if a["kind"] == "wait"]
        self.assertEqual(len(waits), 1)
        return waits[0]

    def test_the_wait_names_the_seconds_until_its_deadline(self):
        self.init_run()
        worktree = str(self.root / "wt-14")
        response = self.control_validated(
            now=DEFAULT_NOW, issues=[14], max_parallel=100, attempt_budget_minutes=30,
            tracker=[self.tracker_fact(14)],
            worktrees=[self.worktree_fact(14, candidate={"path": worktree,
                                                          "state": "absent"})])
        self.assertEqual(self.wait_action(response), {
            "id": "wait:2026-08-13T20:30:00Z", "kind": "wait",
            "wake_on": ["deadline", "owner_notification", "tracker_change"],
            "deadline_at": "2026-08-13T20:30:00Z", "wait_seconds": 1800})
        later = self.control_validated(
            now="2026-08-13T20:10:07Z", issues=[14], max_parallel=100,
            attempt_budget_minutes=30, tracker=[self.tracker_fact(14)],
            worktrees=[self.worktree_fact(14, recorded={
                "path": os.path.abspath(worktree), "state": "matching_issue_branch"})])
        self.assertEqual(self.wait_action(later)["wait_seconds"], 1193)

    def test_the_boundary_refuses_any_other_wait_seconds(self):
        self.init_run()
        response = self.control_validated(
            now=DEFAULT_NOW, issues=[14], max_parallel=100, attempt_budget_minutes=30,
            tracker=[self.tracker_fact(14)],
            worktrees=[self.worktree_fact(14, candidate={"path": str(self.root / "wt-14"),
                                                          "state": "absent"})])
        for value in (1799, 1801, -1, True, None):
            with self.subTest(wait_seconds=value):
                mutated = json.loads(json.dumps(response))
                self.wait_action(mutated)["wait_seconds"] = value
                checked = subprocess.run(
                    [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
                     "workflow-response", "--input", "-", "--policy", str(BUDGET_POLICY)],
                    input=json.dumps(mutated), capture_output=True, text=True, check=False,
                    env=self.cli_env)
                self.assertEqual(checked.returncode, 2)


if __name__ == "__main__":
    unittest.main()
