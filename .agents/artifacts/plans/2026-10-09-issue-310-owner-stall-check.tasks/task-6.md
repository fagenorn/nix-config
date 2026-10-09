# Task 6: Stall replay over the real CLI

**Files:**
- Test: `home/common/agent-skills/tests/test_admission_replay.py` (one new test method and two module constants)

**Interfaces:**
- Consumes: Task 3's `workflow-state owner-liveness` (verdicts `live` and `stalled`, members `since`, `progress_at`, `stall_at`, `wait_seconds`); Task 4's control `wait_seconds` (the replay does not depend on its value); Task 5's rules (a) and (d), which the simulated adapter follows; the committed `stall_minutes` 90 from Task 1.
- Consumes, already in this module: `AdmissionReplayTest` and its `project`, `declare`, `validated`, `cli`, `build`, `contract_input`, `control_request` and `claims` helpers, `at(minute)`, `ISSUES = (12, 14)` and `DISPATCH`.
- Produces: the AC 1 check, `AdmissionReplayTest.test_a_silent_owner_is_freed_and_a_progressing_owner_is_left_alone`.

**Invariants (D6, D7, D8, D12):**
- The simulated adapter follows Task 5's text: on an interim notification it calls `owner-liveness` without `--since` and keeps the reply's `since`; it arms one observer per owner handle for `wait_seconds`; on a wake it calls `owner-liveness --since <liveness_since>`; `stalled` stops the owner and sends one `unavailable` observation in the next control call; `live` re-arms and sends nothing.
- `owner-liveness` reads the clock from `WORKFLOW_STATE_TEST_CLOCK`, pinned per call to the simulated minute with `mock.patch.dict(os.environ, …)`. Every other command gets an explicit `--now` or request `now`, as `replay()` does.
- Exactly one `unavailable` observation is sent in the whole run, for owner A (issue 12).
- A's claim `12:1:1` is released with `release_event` `owner_unavailable` at minute 95, before A's `deadline_at` (minute 180), and control's response dispatches a `resume` or `retry` for issue 12 with a new launch identity.
- Owner B (issue 14), whose launch registered a worker at minute 30, is answered `live` at its wake with `progress_at` minute 30 and `wait_seconds` 1500, and its claim stays unreleased.
- `replay()` and `baseline.json` are not changed.

- [ ] **Step 1: Write the failing test**

In `test_admission_replay.py`, add `import os` and `from unittest import mock` to the imports, and these constants after `DISPATCH`:

```python
# The committed bindings.workflow.orchestration.stall_minutes (#310 D1).
STALL_MINUTES = 90
STALL_ISSUES_SOURCE = "invocation:/orchestrate-issues 12 14"
```

Add this method to `AdmissionReplayTest`, after `test_a_three_slot_declaration_is_refused_before_any_ledger_write`:

```python
    def test_a_silent_owner_is_freed_and_a_progressing_owner_is_left_alone(self):
        """#310 AC1: rule (a) arms a liveness check and rule (d) frees a stalled owner."""
        self.project()
        self.declare(7)
        run = ("--repo-root", self.root, "--run-id", "replay")
        self.cli("init-run", *run, "--now", at(0))
        worktrees = {n: str(self.root / ".worktrees" / f"worktree-issue-{n}-stall")
                     for n in ISSUES}
        built = {n: self.build("contract", self.contract_input(
            issue=n, worktree=worktrees[n], now=at(0),
            source_reference=STALL_ISSUES_SOURCE)) for n in ISSUES}

        def control(minute, owners=(), *, first=False):
            def fact(n):
                if first:
                    return {"issue": n, "recorded": None,
                            "candidate": {"path": worktrees[n], "state": "absent"}}
                return {"issue": n, "candidate": None, "recorded": {
                    "path": worktrees[n], "state": "matching_issue_branch"}}
            request = self.control_request(list(ISSUES), now=at(minute),
                contracts={str(n): built[n]["contract"] if first else None for n in ISSUES},
                intents={str(n): [built[n]["initial_intent"]] if first else []
                         for n in ISSUES},
                worktrees=[fact(n) for n in ISSUES])
            request.update(attempt_budget_minutes=180, owners=list(owners))
            return json.loads(self.validated("workflow-response", self.cli(
                "control", *run, "--request-file", "-",
                stdin=json.dumps(request).encode()).stdout))

        def liveness(minute, action_id, since=None):
            argv = ["owner-liveness", *run, "--action-id", action_id,
                    "--stall-minutes", str(STALL_MINUTES)]
            if since is not None:
                argv += ["--since", since]
            with mock.patch.dict(os.environ, {"WORKFLOW_STATE_TEST_CLOCK": at(minute)}):
                return json.loads(self.validated("workflow-response", self.cli(*argv).stdout))

        first = control(0, first=True)
        custody = {a["issue"]: a["custody"] for a in first["actions"] if a["kind"] in DISPATCH}
        self.assertEqual(sorted(custody), list(ISSUES))
        deadline = {a["issue"]: a["deadline_at"] for a in first["actions"]
                    if a["kind"] in DISPATCH}
        self.assertEqual(deadline[12], at(180))

        # Rule (a): both owners notify interim at minute 5; each arms one observer.
        since, observers, stopped, observations = {}, {}, set(), []
        for issue in ISSUES:
            reply = liveness(5, custody[issue]["action_id"])
            self.assertEqual((reply["verdict"], reply["since"], reply["wait_seconds"]),
                             ("live", at(5), STALL_MINUTES * 60))
            since[issue] = reply["since"]
            observers[issue] = 5 + reply["wait_seconds"] // 60
        # B's owner records progress: a registered worker on its launch at minute 30.
        self.cli("register-worker", *run, "--now", at(30), "--action-id",
                 custody[14]["action_id"])

        # Rule (d): each observer wakes once, in time order (A first at a tie).
        wakes = sorted((minute, issue) for issue, minute in observers.items())
        self.assertEqual(wakes, [(95, 12), (95, 14)])
        for minute, issue in wakes:
            reply = liveness(minute, custody[issue]["action_id"], since=since[issue])
            if reply["verdict"] == "stalled":
                stopped.add(issue)  # the host's task-stop, then one observation
                event = {"event_id": f"{issue}-stalled", "issue": issue,
                         "custody": custody[issue], "state": "unavailable"}
                observations.append(event)
                response = control(minute, [event])
                relaunched = [a for a in response["actions"]
                              if a["kind"] in {"resume", "retry"} and a["issue"] == issue]
                self.assertEqual(len(relaunched), 1)
                self.assertNotEqual(relaunched[0]["custody"]["action_id"],
                                    custody[issue]["action_id"])
            else:
                self.assertEqual(reply["verdict"], "live")
                observers[issue] = minute + reply["wait_seconds"] // 60
                self.assertEqual((reply["progress_at"], reply["stall_at"],
                                  reply["wait_seconds"]), (at(30), at(120), 1500))

        self.assertEqual(stopped, {12})
        self.assertEqual([event["issue"] for event in observations], [12])

        # PR310-04: "exactly once" survives a stale liveness wake and a late
        # return from the stopped owner after its replacement was dispatched.
        # The stale wake is answered `not_current` (no observation, per rule (a));
        # the late return falls under rule (b), whose `check-launch` reads
        # `current: false`, so it sends nothing either.
        stale = liveness(100, custody[12]["action_id"], since=since[12])
        self.assertEqual(stale["verdict"], "not_current")
        late = json.loads(self.cli("check-launch", *run, "--action-id",
                                   custody[12]["action_id"]).stdout)
        self.assertIs(late["current"], False)
        self.assertEqual([event["issue"] for event in observations], [12])
        claims = self.claims()
        self.assertEqual((claims["12:1:1"]["release_event"], claims["12:1:1"]["released_at"]),
                         ("owner_unavailable", at(95)))
        self.assertLess(at(95), deadline[12])
        self.assertIsNone(claims["14:1:1"]["released_at"])
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_admission_replay.py -k test_a_silent_owner`
Expected: before Task 3 lands, FAIL on the first `owner-liveness` call (argparse `invalid choice`). With Tasks 1–5 already on the branch, confirm the test can fail by temporarily deleting the `register-worker` call: B then has no progress before its wake and is answered `stalled`, so the `stopped` and observation assertions fail. Restore the call before committing.

- [ ] **Step 3: Implementation**

None. Every behavior under test is already in Tasks 1–5. If the test fails with them in place, the defect is in a task's code or text. Report which invariant the replay contradicts and do not loosen an assertion.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_admission_replay.py`
Expected: PASS, every replay test, with `baseline.json` unchanged (`git diff --quiet -- home/common/agent-skills/tests/fixtures/admission-replay/baseline.json` exits 0).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_admission_replay.py
git commit -m "test(admission-replay): a silent owner is freed before its deadline (#310)"
```
