import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "workflow-state.py"
DEFAULT_NOW = "2026-08-13T20:00:00Z"


class WorkflowStateLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.run_id = "issue-14-test"
        self.control_request_serial = 0
        self.direct_request_serial = 0

    @property
    def workflows_dir(self):
        return self.root / ".superpowers" / "workflows"

    @property
    def state_path(self):
        return self.workflows_dir / self.run_id / "state.json"

    def run_cli(self, *args, ok=True):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)],
            capture_output=True,
            text=True,
            check=False,
        )
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
        return json.loads(completed.stdout)

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
        return json.loads(completed.stdout) if ok else completed

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
            "attempt": attempt,
            "launch": launch,
            "state": state,
        }

    def control_request(self, *, now, issues, tracker, worktrees, owners=None,
                        max_parallel=2, attempt_budget_minutes=30,
                        human_directed=False):
        return {
            "interface_version": 1,
            "now": now,
            "max_parallel": max_parallel,
            "attempt_budget_minutes": attempt_budget_minutes,
            "human_directed": human_directed,
            "issues": issues,
            "tracker": tracker,
            "owners": [] if owners is None else owners,
            "worktrees": worktrees,
        }

    def control_raw(self, *, request=None, ok=True, **request_fields):
        value = request if request is not None else self.control_request(**request_fields)
        self.control_request_serial += 1
        request_path = self.root / f"control-{self.control_request_serial}.json"
        request_path.write_text(json.dumps(value), encoding="utf-8")
        return self.run_cli(
            "control",
            "--repo-root", self.root,
            "--run-id", self.run_id,
            "--request-file", request_path,
            ok=ok,
        )

    def control(self, **request_fields):
        return json.loads(self.control_raw(**request_fields).stdout)

    UNOBSERVED = object()

    def direct_request(self, *, issue=73, now="2026-08-20T10:00:00Z",
                       attempt_budget_minutes=180, new_run=False,
                       owner_unavailable=False, tracker=None, worktree=None,
                       forge=UNOBSERVED):
        return {
            "interface_version": 1,
            "issue": issue,
            "now": now,
            "attempt_budget_minutes": attempt_budget_minutes,
            "new_run": new_run,
            "owner_unavailable": owner_unavailable,
            "tracker": tracker,
            "worktree": worktree,
            "forge": self.no_pull_request() if forge is self.UNOBSERVED else forge,
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
        return self.run_cli(
            "direct-owner", "--repo-root", self.root,
            "--request-file", request_path, ok=ok,
        )

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
                    "id", "kind", "wake_on", "deadline_at",
                })
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

    def write_state(self, state):
        self.state_path.write_text(
            json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    def suspend(self, *, issue, attempt, blocked_on, now, ok=True):
        return self.run_cli(
            "suspend",
            "--repo-root", self.root,
            "--run-id", self.run_id,
            "--issue", issue,
            "--attempt", attempt,
            "--blocked-on", blocked_on,
            "--now", now,
            ok=ok,
        )

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

    def legacy_expiry_record(self, *, issue, now, prior_schema=False):
        """Stamp the terminal reaper record written before the suspension model.

        The reaper now demotes an expired attempt to `suspended`, but ledgers
        holding the old `stopped`/`result_source="expiry"` shape must keep
        loading and keep driving the retry ladder and the provisional-result
        override, so the tests that pin those rules seed the record directly.
        `prior_schema` writes it under the previous `schema_version` without the
        suspension fields or the run lineage link — the on-disk shape a live run
        carries across deploy.
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
        if prior_schema:
            state["schema_version"] = state["schema_version"] - 1
            state.pop("prior_run", None)
            for record in issue_state["attempts"]:
                for field in ("blocked_on", "suspend_phase", "stalled_resumes"):
                    record.pop(field, None)
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
                pass_fds=(read_fd,),
            )
            os.close(read_fd)
            processes.append(process)
            write_fds.append(write_fd)
        for write_fd in write_fds:
            os.write(write_fd, b"x")
            os.close(write_fd)
        for process in processes:
            _, stderr = process.communicate()
            self.assertEqual(process.returncode, 0, stderr)
        return processes

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
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "control", "--repo-root", str(root),
             "--run-id", self.run_id, "--request-file", str(request_path)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed

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
            "wake_on": ["owner_notification", "tracker_change", "deadline"],
            "deadline_at": "2026-08-19T15:00:00Z",
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
            {"kind": "issue", "issue": 40, "url": None},
            {
                "kind": "decision", "issue": 41,
                "url": "https://github.com/fagenorn/nix-config/issues/41",
            },
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
                lambda value: value.__setitem__("interface_version", 2),
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
                self.assertIn(message, completed.stderr)
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

    def test_control_requires_matching_recorded_state_for_resume_atomically(self):
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
            with self.subTest(recorded_state=recorded_state):
                rejected = self.control_raw(
                    now="2026-08-19T12:01:00Z", issues=[47],
                    tracker=[self.tracker_fact(47)],
                    owners=[self.owner_fact(event_id=f"47-{recorded_state}", issue=47,
                                            attempt=1, launch=1)],
                    worktrees=[self.worktree_fact(
                        47,
                        recorded={"path": path, "state": recorded_state},
                        candidate={"path": replacement, "state": "absent"},
                    )],
                    ok=False,
                )
                self.assertIn("matching recorded worktree", rejected.stderr)
                self.assertEqual(self.state_path.read_bytes(), before)

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

        # 3. Silent expiry retries on the recorded path while unrelated work starts.
        decision = self.control_raw(request=decision_request)
        decided = json.loads(decision.stdout)
        self.assertEqual([d["kind"] for d in decided["deltas"]],
                         ["expired", "resumed", "spawned"])
        self.assertEqual([a["id"] for a in decided["actions"]],
                         ["51:1:2", "53:1:1", "wait:2026-08-19T13:01:00Z"])
        self.assertEqual(decided["actions"][0]["worktree"], paths[51])
        post_action_state = self.state_path.read_bytes()

        # 4. The retried owner and unrelated active owner finish concurrently.
        finished = self.concurrent_finish(
            {51: (1, self.merged_result(51)), 53: (1, self.merged_result(53))},
            now="2026-08-19T12:40:00Z",
        )
        self.assertTrue(all(process.returncode == 0 for process in finished))
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
        self.assertTrue(all(item.returncode == 0 for item in completed))
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
        self.assertEqual(state["schema_version"], 2)
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
        self.assertEqual(handed_off["state"], "handed_off")
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
        self.assertEqual(self.state_path.read_bytes(), before)

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
                self.assertEqual(result["phase_action"], expected_action)
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
                self.assertEqual(result["phase_action"], expected)
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
                    "stalled_resumes": 0,
                }
                expected_state = {
                    "schema_version": 2, "run_id": run_id,
                    "created_at": DEFAULT_NOW, "updated_at": DEFAULT_NOW,
                    "prior_run": None,
                    "issues": {"14": {
                        "issue": 14, "attempts": [expected_attempt],
                        "outcome": None,
                    }},
                }
                expected_bytes = (json.dumps(
                    expected_state, sort_keys=True, separators=(",", ":")
                ) + "\n").encode()
                self.assertEqual(result, expected_attempt)
                self.assertEqual(self.state_path.read_bytes(), expected_bytes)

    def test_zero_sequence_direct_shaped_dispatcher_keeps_non_direct_progress_and_reopen_bytes(self):
        self.run_id = "direct-14-000000"
        self.init_run()
        worktree = os.path.abspath(self.root / "zero-sequence-worktree")
        self.spawn(issue=14, worktree=worktree)
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
        }
        expected_state = {
            "schema_version": 2, "run_id": self.run_id,
            "created_at": DEFAULT_NOW, "updated_at": DEFAULT_NOW,
            "prior_run": None,
            "issues": {"14": {
                "issue": 14, "attempts": [expected_attempt], "outcome": None,
            }},
        }
        expected_bytes = (json.dumps(
            expected_state, sort_keys=True, separators=(",", ":")
        ) + "\n").encode()
        self.assertEqual(result, expected_attempt)
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
        self.assertEqual(delegated["phase_action"], "delegate")

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
        self.assertEqual(unknown_usage["phase_action"], "continue")

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
        self.assertEqual(at_context_ceiling["phase_action"], "handoff")

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
        self.assertEqual(at_turn_ceiling["phase_action"], "handoff")

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
                    (decision["phase_action"], decision["state"]),
                    ("continue", "active"),
                )

        # A measured near-ceiling count is still a handoff.
        at_ceiling = self.progress(
            issue=14, attempt=1, phase=3, now="2026-08-13T20:03:00Z",
            turn_count=118, context_tokens=None, next_needs_context=True,
            artifacts_sufficient=False, remainder_self_contained=False,
        )
        self.assertEqual(at_ceiling["phase_action"], "handoff")

    def test_durable_handoff_requires_safe_file_and_resumes_same_attempt(self):
        self.init_run()
        worktree = self.root / "wt-a"
        launched = self.spawn(issue=14, worktree=worktree)
        decision = self.progress(turn_count=118, context_tokens=20000)
        self.assertEqual(
            (decision["phase_action"], decision["state"]), ("handoff", "active")
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
        self.assertEqual(finalized["state"], "handed_off")
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
        self.assertEqual((continued["phase_action"], continued["state"]), ("continue", "active"))
        self.assertEqual(continued["handoff_path"], str(handoff_path))

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
        self.assertEqual(at_turn_threshold["phase_action"], "handoff")
        at_context_threshold = self.progress(
            phase=2, turn_count=10, context_tokens=140000
        )
        self.assertEqual(at_context_threshold["phase_action"], "handoff")

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
        self.assertEqual(decision["phase_action"], "handoff")
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
        self.assertEqual(self.state_path.read_bytes(), before)

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
            response = json.loads(stdout)
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
            "version": {**valid, "interface_version": 2},
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
        rejected = self.direct_owner_raw(
            now="9999-12-31T23:59:59Z",
            attempt_budget_minutes=1,
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
        # orchestrated handoff past Phase 0 owns a worktree it must still show.
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
        rejected = self.control_raw(
            now="2026-08-20T10:02:00Z", issues=[77],
            tracker=[self.tracker_fact(77)],
            worktrees=[self.worktree_fact(77, recorded={
                "path": dispatched["worktree"], "state": "absent",
            })], max_parallel=1, ok=False,
        )
        self.assertIn("matching recorded worktree", rejected.stderr)
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
            self.assertEqual(progressed["phase"], 1)
            state = json.loads(self.direct_state_path(owner["run_id"]).read_text())
            attempts = state["issues"]["73"]["attempts"]
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
                "interface_version": 1, "run_id": zero_id,
                "requirements": [],
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
            self.assertEqual(json.loads(controlled.stdout), {
                "interface_version": 1, "run_id": zero_id,
                "now": "2026-08-20T10:01:00Z",
                "summaries": [{
                    "issue": 73, "state": "closed", "attempt": None,
                    "owner": None, "worktree": None, "deadline_at": None,
                    "blocked_on": None, "blockers": [], "result": None,
                }],
                "deltas": [], "actions": [{"id": "finalize", "kind": "finalize"}],
                "next_deadline": None,
            })

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
        self.assertEqual(progress["phase_action"], "continue")
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
            self.progress(issue=73, now="2026-08-20T15:30:00Z")["phase_action"],
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
        completed = self.suspend(
            issue=15, attempt=1, blocked_on="usage_limit",
            now="2026-08-13T20:05:00Z",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        envelope = json.loads(completed.stdout)
        self.assertEqual(envelope, {
            "kind": "suspended", "issue": 15, "attempt": 1,
            "blocked_on": "usage_limit", "stalled_resumes": 0,
            "reentry": "/from-issue 15 --auto",
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
            completed = self.suspend(
                issue=16, attempt=1, blocked_on="usage_limit",
                now=f"2026-08-13T20:0{2 * index + 1}:00Z",
            )
            envelope = json.loads(completed.stdout)
            self.assertEqual(envelope["kind"], "suspended")
            self.assertEqual(envelope["stalled_resumes"], index)
            self.resume(
                issue=16, worktree=worktree,
                now=f"2026-08-13T20:0{2 * index + 2}:00Z",
            )
        final = self.suspend(
            issue=16, attempt=1, blocked_on="usage_limit",
            now="2026-08-13T20:08:00Z",
        )
        attempt = json.loads(final.stdout)
        self.assertEqual(attempt["state"], "stopped")
        self.assertEqual(attempt["result_source"], "stalled")
        self.assertIsNone(attempt["blocked_on"])
        self.assertIn("stalled without phase progress", attempt["result"]["notes"])
        persisted = self.read_state()["issues"]["16"]
        self.assertEqual(persisted["attempts"][-1], attempt)
        self.assertEqual(persisted["outcome"], attempt["result"])

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

    def test_prior_schema_ledger_upgrades_on_load(self):
        self.init_run()
        worktree = str(Path(self.root) / "wt-17")
        self.spawn(issue=17, worktree=worktree, budget_minutes=10)
        state = self.read_state()
        current_version = state["schema_version"]
        state["schema_version"] = current_version - 1
        state.pop("prior_run", None)
        for attempt in state["issues"]["17"]["attempts"]:
            for field in ("blocked_on", "suspend_phase", "stalled_resumes"):
                attempt.pop(field, None)
        self.write_state(state)
        completed = self.suspend(
            issue=17, attempt=1, blocked_on="external",
            now="2026-08-13T20:02:00Z",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        upgraded = self.read_state()
        self.assertEqual(upgraded["schema_version"], current_version)
        self.assertIsNone(upgraded["prior_run"])
        latest = upgraded["issues"]["17"]["attempts"][-1]
        self.assertEqual(latest["stalled_resumes"], 0)
        self.assertEqual(latest["suspend_phase"], 0)
        self.assertEqual(latest["blocked_on"], "external")

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
        self.assertEqual(self.state_path.read_bytes(), before)

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
        self.assertEqual(self.state_path.read_bytes(), parked)

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


if __name__ == "__main__":
    unittest.main()
