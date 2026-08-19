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
                        max_parallel=2, attempt_budget_minutes=30):
        return {
            "interface_version": 1,
            "now": now,
            "max_parallel": max_parallel,
            "attempt_budget_minutes": attempt_budget_minutes,
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
                "deadline_at", "blockers", "result",
            })
            self.assertIs(type(summary["issue"]), int)
            self.assertIn(summary["state"], {
                "queued", "blocked", "fogged", "active", "handed_off",
                "merged", "stopped", "failed", "closed",
            })
            self.assertIsInstance(summary["blockers"], list)
            self.assertTrue(summary["attempt"] is None or
                            type(summary["attempt"]) is int)
            for field in ("owner", "worktree", "deadline_at"):
                self.assertTrue(summary[field] is None or
                                isinstance(summary[field], str))
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
                self.assertTrue(action["deadline_at"] is None or
                                isinstance(action["deadline_at"], str))
            elif action["kind"] == "finalize":
                self.assertEqual(action, {"id": "finalize", "kind": "finalize"})
            else:
                self.fail(f"unknown control action kind: {action['kind']!r}")

    def read_state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))

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

    def test_public_cli_exposes_only_the_four_lifecycle_commands(self):
        completed = self.run_cli("--help")
        self.assertIn("{init-run,control,finish,progress}", completed.stdout)
        self.assertNotIn("launch", completed.stdout)
        self.assertNotIn("reconcile", completed.stdout)
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
            "blockers": [], "result": None,
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

    def test_control_returns_external_wait_and_finalize_from_current_facts(self):
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
        self.assertEqual(waiting["actions"], [{
            "id": "wait:external",
            "kind": "wait",
            "wake_on": ["owner_notification", "tracker_change"],
            "deadline_at": None,
        }])
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
        self.assertEqual(response["actions"], [{
            "id": "wait:external",
            "kind": "wait",
            "wake_on": ["owner_notification", "tracker_change"],
            "deadline_at": None,
        }])
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
                         ["expired", "retried", "spawned"])
        self.assertEqual([a["id"] for a in decided["actions"]],
                         ["51:2:1", "53:1:1", "wait:2026-08-19T13:01:00Z"])
        self.assertEqual(decided["actions"][0]["worktree"], paths[51])
        post_action_state = self.state_path.read_bytes()

        # 4. The retried owner and unrelated active owner finish concurrently.
        finished = self.concurrent_finish(
            {51: (2, self.merged_result(51)), 53: (1, self.merged_result(53))},
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

    def test_control_demo_3_expires_retries_and_fills_unrelated_capacity(self):
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
                         ["retry", "spawn", "wait"])
        retry, spawn = response["actions"][:2]
        self.assertEqual((retry["id"], retry["worktree"]), ("51:2:1", paths[51]))
        self.assertEqual((spawn["id"], spawn["issue"]), ("53:1:1", 53))
        self.assertEqual([d["kind"] for d in response["deltas"]],
                         ["expired", "retried", "spawned"])

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
        self.assertEqual([item["issue"] for item in response["deltas"]], [51, 47])
        self.assertEqual([item["kind"] for item in response["deltas"]],
                         ["expired", "expired"])

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

    def test_control_attempt_two_deadline_emits_only_retry_refused(self):
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

        refused = self.control(
            now="2026-08-19T12:32:00Z", issues=[47],
            tracker=[self.tracker_fact(47)], worktrees=[],
        )
        self.assertEqual(refused["deltas"], [{
            "issue": 47, "attempt": 2, "kind": "retry_refused", "state": "failed",
        }])
        persisted = self.read_state()["issues"]["47"]["attempts"][-1]
        self.assertEqual(persisted["result_source"], "refused")

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

    def test_owner_death_expiry_stops_active_attempt_with_worktree(self):
        self.init_run()
        worktree = self.root / "silent-owner"
        launched = self.spawn(issue=14, worktree=worktree, budget_minutes=10)
        reconciled = self.expire(
            issue=14, worktree=worktree, now="2026-08-13T20:10:00Z"
        )
        self.assert_control_response_shape(reconciled)
        self.assertEqual(reconciled["deltas"], [{
            "issue": 14, "attempt": 1, "kind": "expired", "state": "stopped",
        }])
        attempt = self.read_state()["issues"]["14"]["attempts"][0]
        outcome = self.read_state()["issues"]["14"]["outcome"]
        self.assertEqual(launched["deadline_at"], "2026-08-13T20:10:00Z")
        self.assertEqual((attempt["state"], outcome["state"]), ("stopped", "stopped"))
        self.assertIn(os.path.abspath(worktree), outcome["notes"])
        self.assertLessEqual(len(outcome["notes"]), 500)
        self.assertEqual(attempt["result_source"], "expiry")
        self.assertEqual(attempt["finished_at"], "2026-08-13T20:10:00Z")
        self.assertGreaterEqual(attempt["finished_at"], attempt["deadline_at"])

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

    def test_expiry_result_is_provisional_until_the_owner_reports(self):
        self.init_run()
        worktree = self.root / "wt-a"
        self.spawn(issue=14, worktree=worktree, budget_minutes=10)
        self.expire(issue=14, worktree=worktree, now="2026-08-13T20:10:00Z")
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
        self.expire(issue=14, worktree=worktree, now="2026-08-13T20:10:00Z")
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

    def test_owner_death_expiry_can_use_the_single_fresh_retry(self):
        self.init_run()
        worktree = self.root / "silent-owner"
        self.spawn(issue=14, worktree=worktree, budget_minutes=10)
        self.expire(issue=14, worktree=worktree, now="2026-08-13T20:10:00Z")
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
        self.expire(issue=14, worktree=shared, now="2026-08-13T20:10:00Z")
        first = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual(first["state"], "stopped")
        self.assertEqual(first["result_source"], "expiry")
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
                "handoff",
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
        self.assertEqual(unknown_usage["phase_action"], "handoff")

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

    def test_late_handoff_control_expires_and_permits_fresh_retry(self):
        self.init_run()
        worktree = self.root / "wt-a"
        self.spawn(issue=14, worktree=worktree)
        handoff_path = self.write_handoff(14)
        self.progress(turn_count=118, context_tokens=20000, handoff_path=handoff_path)

        completed = self.expire(
            issue=14, worktree=worktree, now="2026-08-13T20:31:00Z"
        )
        self.assert_control_response_shape(completed)
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

    def test_control_expires_unresumed_handoff_and_permits_fresh_retry(self):
        self.init_run()
        worktree = self.root / "wt-a"
        self.spawn(issue=14, worktree=worktree)
        handoff_path = self.write_handoff(14)
        self.progress(turn_count=118, context_tokens=20000, handoff_path=handoff_path)

        reconciled = self.expire(
            issue=14, worktree=worktree, now="2026-08-13T20:31:00Z"
        )
        self.assert_control_response_shape(reconciled)
        persisted = self.read_state()["issues"]["14"]
        attempt = persisted["attempts"][0]
        self.assertEqual((attempt["state"], persisted["outcome"]["state"]), ("stopped", "stopped"))
        self.assertEqual(attempt["handoff_path"], str(handoff_path))
        self.assertIn(os.path.abspath(worktree), persisted["outcome"]["notes"])

        retried = self.retry(
            issue=14, worktree=self.root / "wt-b",
            now="2026-08-13T20:32:00Z",
        )
        self.assertEqual((retried["attempt"], retried["kind"]), (2, "retry"))

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
        self.assertEqual(final_state["issues"]["15"]["outcome"]["state"], "stopped")
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


if __name__ == "__main__":
    unittest.main()
