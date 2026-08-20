# Task 1: Add the strict direct-owner lifecycle acquisition interface

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes: the existing schema-1 ledger, hardened workflow directory/regular-file/lock primitives, atomic state replacement, tracker/worktree validators, one-issue `control` policy, and D1–D7/D9.
- Produces: `workflow-state direct-owner --repo-root <absolute-ledger-repository-root> --request-file <absolute-json-path>`; strict `DIRECT_OWNER_INTERFACE_VERSION = 1`; strict request loader/validator; retained direct-run discovery; canonical `observe | owner | terminal` responses.
- Produces one private one-issue policy operation, named `_apply_one_issue_policy`, whose keyword-only inputs are the validated ledger issue (or no prior issue), optional normalized tracker/worktree observations, injected `now` and `attempt_budget_minutes`, an internally derived current-owner-unavailable boolean, dispatch permission, and the selected run directory. Its result is a closed proposed operation (`observe | spawn | resume | retry | refuse | terminal | idle`) plus a changed boolean and the projection data needed by the caller. Both `command_control` and `command_direct_owner` call it; neither carries a second copy of resume/retry/refusal rules. The private representation may use a frozen record, but those inputs, operations, and outputs are fixed.
- Preserves: the exact public `init-run`, `control`, `progress`, and `finish` arguments and all existing dispatcher response shapes. Parser help adds `direct-owner` and no retired operation.

**Invariants:**
- The request has exactly `interface_version`, `issue`, `now`, `attempt_budget_minutes`, `new_run`, `owner_unavailable`, `tracker`, and `worktree`. Version is integer 1; issue/budget are positive plain integers; `now` is normalized RFC3339 UTC; authorizations are literal booleans and cannot both be true; nullable observations reuse the existing exact validators and must name the requested issue.
- Validate the complete request before creating the workflows directory, issue lock, or run directory. A syntactically valid request may create only `.direct-<issue>.lock` until an accepted first launch is ready.
- Discovery treats every entry beginning `direct-<issue>-` as claimed namespace: its suffix must be exactly six digits; each match must be a non-symlink directory with existing non-symlink regular `state.lock` and `state.json`; the state validates against the directory run ID and contains exactly the requested issue. No matching state is ignored.
- Hold the exclusive stable issue lock throughout discovery and the selected/new run transaction. Acquire every inspected/selected run lock only after it. Preserve an atomic snapshot across classification and mutation; never release the selected run lock and then act on stale state.
- Classify lifecycle work with the shared retry policy: empty, active, handed-off, attempt-1 expiry, owner-failed attempt 1, and an attempt-2 state still requiring durable refusal are nonterminal. More than one nonterminal run, or a nonterminal run below a greater terminal sequence, is corrupt. With one nonterminal run adopt it; with none replay the greatest terminal unless `new_run` is applicable.
- Initial/new allocation chooses one plus the greatest retained sequence, starts at `000001`, and fails at `999999`. A new run never overwrites/removes earlier directories. Its initial schema plus first accepted attempt/action are one atomic write; no empty newly initialized ledger is exposed.
- An unexpired active attempt fails before requesting facts or mutating unless `owner_unavailable` is true. That flag is applicable only to that state, derives the latest attempt/launch identity internally, requires its exact matching recorded worktree, and appends a resume launch without changing owner, attempt, start, deadline, worktree, or handoff.
- A handed-off attempt automatically requests/validates its recorded worktree and resumes with the stored handoff. Expiry and owner-failed outcomes reuse the existing retry/refusal rules and worktree choice. A first/retry/new-run launch requests tracker facts before worktree facts; tracker precedence is closed, decision blocker/fogged, ordinary blocker/blocked.
- `observe.requirements` is ordered and contains only exact `tracker`, `recorded_worktree`, or `candidate_worktree` items. `run_id` is null before selection and otherwise the selected direct ID. Supplying one observation round may reveal the next; observation never changes a ledger.
- `owner` is printed only after persistence and has exactly the fields in D6, with `ledger_repo_root` equal to the validated immutable absolute root and `launch_kind` translated to `spawn | resume | retry`. `terminal` has only the D6 fields and either a lifecycle result/non-null run ID/empty blockers or a tracker result-null/normalized blockers/nullable run ID. No direct response contains control summaries, deltas, wait, finalize, or dispatcher action arrays.
- `new_run` is applicable only when retained history exists and the latest run is terminal. It creates the next sequence with a fresh two-attempt allowance after tracker readiness and reuses the latest terminal worktree only when observed matching; otherwise it requires a verified absent candidate. Lifecycle terminal replay is byte-equivalent across processes when `new_run` is false.
- Reject exact reserved direct IDs in public `init-run` and `control` before `workflow_paths` can create/open them. Do not apply that rejection to `progress` or `finish`; their existing state/attempt/result validation remains the authority.
- JSON remains key-sorted compact UTF-8 with one trailing newline. All failures exit 2, write no success stdout, and preserve every pre-existing `state.json` byte-for-byte. Creating the stable issue lock is not a lifecycle mutation.

- [ ] **Step 1: Add failing direct-owner CLI, restart, policy, corruption, and concurrency tests**

Extend `setUp` with `self.direct_request_serial = 0`, then add these complete helpers to `WorkflowStateLifecycleTest`:

```python
    def direct_request(self, *, issue=73, now="2026-08-20T10:00:00Z",
                       attempt_budget_minutes=180, new_run=False,
                       owner_unavailable=False, tracker=None, worktree=None):
        return {
            "interface_version": 1,
            "issue": issue,
            "now": now,
            "attempt_budget_minutes": attempt_budget_minutes,
            "new_run": new_run,
            "owner_unavailable": owner_unavailable,
            "tracker": tracker,
            "worktree": worktree,
        }

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
```

Replace the old four-command help assertion and add the acquisition/strict-shape tests:

```python
    def test_public_cli_exposes_direct_owner_but_not_retired_commands(self):
        completed = self.run_cli("--help")
        self.assertIn("direct-owner", completed.stdout)
        for retired in ("launch", "reconcile"):
            rejected = self.run_cli(retired, ok=False)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("invalid choice", rejected.stderr)

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
            "version": {**valid, "interface_version": 2},
            "boolean issue": {**valid, "issue": True},
            "local time": {**valid, "now": "2026-08-20T10:00:00"},
            "both flags": {**valid, "new_run": True, "owner_unavailable": True},
            "tracker mismatch": {**valid, "tracker": self.tracker_fact(74)},
            "worktree mismatch": {**valid, "worktree": self.worktree_fact(74)},
        }
        for label, request in cases.items():
            with self.subTest(label=label):
                completed = self.direct_owner_raw(request=request, ok=False)
                self.assertEqual(completed.returncode, 2)
                self.assertEqual(completed.stdout, "")
        self.assertFalse(self.workflows_dir.exists())
```

Add the active/handoff/retry/terminal tests. Each call is a new subprocess and every accepted response is checked against reopened durable state:

```python
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
                })
                self.assertFalse(any(
                    path.name.startswith("direct-73-")
                    for path in self.workflows_dir.iterdir()
                ))
```

Add reserved-capability, discovery-corruption, and concurrent-first-call tests:

```python
    def test_reserved_direct_ids_are_closed_to_init_and_control_but_open_to_owner_mutations(self):
        run_id = "direct-73-000001"
        rejected_init = self.run_cli(
            "init-run", "--repo-root", self.root, "--run-id", run_id,
            "--now", "2026-08-20T10:00:00Z", ok=False,
        )
        self.assertEqual(rejected_init.returncode, 2)
        request_path = self.root / "control-reserved.json"
        request_path.write_text(json.dumps(self.control_request(
            now="2026-08-20T10:00:00Z", issues=[73],
            tracker=[self.tracker_fact(73)], worktrees=[],
        )), encoding="utf-8")
        rejected_control = self.run_cli(
            "control", "--repo-root", self.root, "--run-id", run_id,
            "--request-file", request_path, ok=False,
        )
        self.assertEqual(rejected_control.returncode, 2)
        self.assertFalse((self.workflows_dir / run_id).exists())
        owner = self.acquire_direct()
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
```

Add the remaining filesystem, authorization, expiry, replay, and canonical-output cases. These tests use only subprocess CLI calls and complete on-disk ledgers:

```python
    def test_direct_discovery_rejects_every_unsafe_retained_entry(self):
        owner = self.acquire_direct()
        valid_state = self.direct_state_path(owner["run_id"]).read_bytes()

        def materialize(root, *, directory="real", lock="file", state="file",
                        state_bytes=valid_state):
            workflows = root / ".superpowers" / "workflows"
            workflows.mkdir(parents=True)
            run = workflows / "direct-73-000001"
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
            "symlink directory": {"directory": "symlink"},
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

    def test_direct_expiry_retries_on_absent_candidate_then_refuses_attempt_two(self):
        owner = self.acquire_direct(attempt_budget_minutes=30)
        tracker = self.tracker_fact(73)
        replacement = os.path.abspath(self.root / "replacement-worktree-73")
        retry = self.direct_owner(
            now="2026-08-20T10:30:00Z", attempt_budget_minutes=30,
            tracker=tracker,
            worktree=self.worktree_fact(
                73,
                recorded={"path": owner["worktree"], "state": "absent"},
                candidate={"path": replacement, "state": "absent"},
            ),
        )
        self.assertEqual(
            (retry["attempt"], retry["launch_kind"], retry["worktree"],
             retry["deadline_at"]),
            (2, "retry", replacement, "2026-08-20T11:00:00Z"),
        )
        refused = self.direct_owner(
            now="2026-08-20T11:00:00Z", attempt_budget_minutes=30,
            tracker=tracker,
            worktree=self.worktree_fact(73, recorded={
                "path": replacement, "state": "matching_issue_branch",
            }),
        )
        self.assertEqual(
            (refused["kind"], refused["source"], refused["reason"]),
            ("terminal", "lifecycle", "failed"),
        )
        state = json.loads(self.direct_state_path(owner["run_id"]).read_text())
        self.assertEqual(len(state["issues"]["73"]["attempts"]), 2)
        self.assertEqual(state["issues"]["73"]["attempts"][-1]["result_source"],
                         "refused")

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
        self.assertEqual(merged_terminal["result"], merged)
        self.assertEqual(merged_terminal["reason"], "merged")

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
        self.assertEqual(stopped_terminal["reason"], "stopped")
        self.assertEqual(stopped_terminal["result"], stopped)

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
```

- [ ] **Step 2: Run the focused suite and confirm the new public contract is absent**

Run: `python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -v`

Expected: FAIL in the new direct-owner/help tests because `direct-owner` is not a parser choice; existing control/progress/finish tests remain green up to those failures.

- [ ] **Step 3: Implement strict validation, issue-locked discovery, shared policy, and closed projections**

In `workflow-state.py`:

1. Add the direct interface constant, exact field/enum sets, exact direct-ID and per-issue namespace patterns, and strict request loading. Generalize the existing absolute request-file reader without weakening control validation or its diagnostics.
2. Separate validated repository/workflows-directory resolution from run-directory creation. Generalize `open_stable_lock(path, label, allow_missing)` so normal transactions may create a run lock, while discovery requires every retained run lock to exist. Preserve no-follow open plus inode/device verification.
3. Add an issue-lock context that creates/opens only `.direct-<issue>.lock`, obtains `LOCK_EX`, scans directory entries without following links, validates every claimed namespace member, opens/locks retained runs in sequence order, and classifies them from validated state. Reject all corrupt/ambiguous/exhausted shapes before mutation.
4. Extract the one-issue transition derivation/application now nested in `command_control` behind `_apply_one_issue_policy`. Keep control's three scheduling passes, capacity, candidate exclusivity, replay exception, deltas, summary ordering, and trailing wait/finalize construction unchanged; move only the lifecycle knowledge that both entry points must share. Direct acquisition passes capacity one and nullable facts so the shared operation can return the next required observation rather than fabricating tracker/Git state.
5. Implement initial/adopt/replay/new-run selection and authorization applicability under the issue lock. For new-run worktree reuse, treat the latest retained terminal attempt's recorded path as the prior worktree input to the shared fresh/retry path selection, while writing attempt 1 into a new schema-1 ledger.
6. Map the accepted shared operation to exact direct `observe`, `owner`, or `terminal` projections. Derive action/owner identity only from the persisted attempt, translate the first fresh launch to `spawn` and a later run's fresh attempt to `spawn`, and never expose dispatcher-only state.
7. Add `reject_reserved_direct_run_id` at the start of `command_init_run` and `command_control`, before any call that can create a run directory. Register `direct-owner` with only `--repo-root` and `--request-file`. Leave `progress` and `finish` unchanged.

Implementation is incomplete if a second process can observe an empty new ledger, if an observation response changes `state.json`, if a selected run is unlocked between classification and mutation, or if any existing control response byte changes for the same ledger/request snapshot.

- [ ] **Step 4: Verify direct lifecycle behavior and policy equivalence**

Run: `python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -v`

Expected: PASS; all existing control tests plus direct strict-shape, reopened-state, corruption, capability, lifecycle, and concurrent-first-call cases pass with no sleeps or network access.

- [ ] **Step 5: Verify the owned diff and commit the complete helper tracer**

Run: `git diff --check -- home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py`

Expected: exit 0 with no output. Then inspect `git diff --stat --` with the same two pathspecs; any other implementation path is scope drift.

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
git commit -m "feat(issue-73): add durable direct owner acquisition" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

The task is complete only after its full-lane SDD review reports both spec compliance and quality clean (or clean after its scoped fix/re-review loop).
