# Task 1: workflow-state admits the `agent_dispatch` suspension cause

Decisions: D6 (the new owner-reportable cause, not auto-resumable), D7 (only
the attempt-cause set changes), D11 (seam S1), D18 (the shipped engine alone
gains the value; #117's record and the core port are #125's). The test code's
`# per D20` follows this test file's existing citation for
`assert_controller_finalized`, which is #150's ledger, not this spec's. Spec
§"The genuine gap: an
`agent_dispatch` suspension" and §"Test seams" T1–T3. Work from the worktree
root. Every shell block starts with `set -euo pipefail` (`set -uo pipefail` in
the watch-it-fail step) and this abbreviation, which the blocks below omit:

```bash
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
```

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (the constant
  block at lines 30–38, and the `human_directed` paragraph of the
  `_apply_one_issue_policy` docstring at about line 1887)
- Test: `home/common/agent-skills/tests/test_workflow_state.py` (three new
  methods in `WorkflowStateLifecycleTest`, directly above
  `def test_prior_schema_ledger_upgrades_on_load`)

**Interfaces:**
- Consumes: nothing from another task. The tests use the existing
  `LifecycleHarness` helpers `init_run`, `spawn(issue=, worktree=, budget_minutes=)`,
  `suspend(issue=, attempt=, blocked_on=, now=, ok=True)`,
  `control(now=, issues=, tracker=, worktrees=, human_directed=)`,
  `worktree_fact`, `tracker_fact`, `read_state`, `state_path`,
  `assert_control_response_shape`, `assert_controller_finalized(before, *, now)`,
  `acquire_direct()`, `direct_owner(now=, worktree=)` and `direct_state_path(run_id)`.
- Produces, for Tasks 3 and 4:
  - `workflow-state suspend --blocked-on agent_dispatch` succeeds on an active
    attempt. Its stdout envelope is
    `{"kind":"suspended","issue":<n>,"attempt":<k>,"blocked_on":"agent_dispatch","stalled_resumes":<0|1|2>,"reentry":"/from-issue <n> --auto"}`,
    which is the existing shape.
  - `BLOCKED_ON_VALUES` holds `agent_dispatch`. `OWNER_BLOCKED_ON_VALUES` holds
    it by derivation, and `AUTO_RESUMABLE_BLOCKED_ON` does not.

**Invariants:**
- `sorted(OWNER_BLOCKED_ON_VALUES)` is exactly `["agent_dispatch", "external",
  "human_gate", "transport", "usage_limit"]`. `unknown` and `host_capacity` stay
  refused by `suspend`, so the existing
  `test_suspend_rejects_a_nonactive_attempt_and_the_reserved_cause` and
  `test_host_admission.py`'s `test_direct_runs_and_owners_cannot_report_host_capacity`
  stay green.
- `AUTO_RESUMABLE_BLOCKED_ON` keeps its bytes. A sweep with
  `human_directed: false` never resumes `agent_dispatch`. A human-directed sweep
  and a direct owner do resume it.
- `STALL_LIMIT` (3), `SCHEMA_VERSION` (4) and every other set in `S/` keep their
  values. `workflow_delivery.py`'s remainder set and `delivery_model/_wire.py`'s
  checkpoint-response set are not touched (D7).
- A suspension consumes no attempt. The attempt has no result, no finish time
  and no result source, and the issue has no outcome.

- [ ] **Step 1: Write the failing tests**

Insert these three methods into `WorkflowStateLifecycleTest`, directly above
`    def test_prior_schema_ledger_upgrades_on_load(self):`. Keep the existing
four-space class indentation.

```python
    def test_agent_dispatch_suspension_parks_the_attempt_without_spending_it(self):
        # A context that cannot launch the agents a phase needs is an
        # environmental pause with its own owner-reported cause, never a
        # terminal verdict: the attempt stays resumable and is not consumed
        # (per D6).
        self.init_run()
        worktree = str(Path(self.root) / "wt-19")
        self.spawn(issue=19, worktree=worktree, budget_minutes=10)
        completed = self.suspend(
            issue=19, attempt=1, blocked_on="agent_dispatch",
            now="2026-08-13T20:05:00Z",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {
            "kind": "suspended", "issue": 19, "attempt": 1,
            "blocked_on": "agent_dispatch", "stalled_resumes": 0,
            "reentry": "/from-issue 19 --auto",
        })
        issue = self.read_state()["issues"]["19"]
        self.assertEqual([attempt["attempt"] for attempt in issue["attempts"]], [1])
        attempt = issue["attempts"][-1]
        self.assertEqual(attempt["state"], "suspended")
        self.assertEqual(attempt["blocked_on"], "agent_dispatch")
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
```

- [ ] **Step 2: Run the tests and watch them fail**

```bash
set -uo pipefail
T=home/common/agent-skills/tests
PYTHONPATH=python python3 -m unittest $T/test_workflow_state.py -k agent_dispatch 2>&1 \
  | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED|invalid choice' | cut -c1-160
```

Expected: `Ran 3 tests` and `FAILED (failures=3)`. Each failure carries
`argument --blocked-on: invalid choice: 'agent_dispatch' (choose from external,
human_gate, transport, usage_limit)`.

- [ ] **Step 3: Write the minimal implementation**

1. In `$S/workflow-state.py`, replace exactly this block:
   ```
   BLOCKED_ON_VALUES = frozenset(
       {"usage_limit", "transport", "human_gate", "external", "unknown", "host_capacity"}
   )
   ```
   with a comment and the widened set below. Leave the `host_capacity` comment
   above it and the `OWNER_BLOCKED_ON_VALUES`, `AUTO_RESUMABLE_BLOCKED_ON` and
   `STALL_LIMIT` lines below it byte-identical.
   ```python
   # ``agent_dispatch`` is written only by an owner, through ``suspend``, when its
   # own context cannot launch the agents a phase needs. It is not auto-resumable:
   # the ledger cannot see how deep a relaunch would run, and blind resumes would
   # spend ``STALL_LIMIT``, so only a human-directed re-entry clears it (per D6).
   BLOCKED_ON_VALUES = frozenset({
       "usage_limit", "transport", "human_gate", "external", "unknown", "host_capacity",
       "agent_dispatch",
   })
   ```
2. In the `_apply_one_issue_policy` docstring, the paragraph that begins
   `Every caller drives an environmentally suspended attempt back to work` ends
   with these lines today:
   ```
       re-entry by name, which is the only thing that clears a
       `human_gate`/`external` suspension: a direct owner always carries it, and an
       orchestrated sweep carries it exactly when the caller listed the issue
       numbers itself. A `--label`/`--milestone` sweep never does, so it leaves
       those parked and reports them.
   ```
   Replace them with:
   ```
       re-entry by name, which is the only thing that clears a
       `human_gate`/`external`/`agent_dispatch` suspension: a direct owner always
       carries it, and an orchestrated sweep carries it exactly when the caller
       listed the issue numbers itself. A `--label`/`--milestone` sweep never does,
       so it leaves those parked and reports them.
   ```
No other line in `$S/` changes. The `suspend` parser's
`choices=sorted(OWNER_BLOCKED_ON_VALUES)` picks up the value by derivation, so
leave it as it is.

- [ ] **Step 4: Verify**

```bash
set -euo pipefail
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
PYTHONPATH=python python3 -m unittest $T/test_workflow_state.py -k agent_dispatch -k suspen -k human 2>&1 \
  | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
python3 - <<'EOF'
import importlib.util
spec = importlib.util.spec_from_file_location("ws", "home/common/agent-skills/scripts/workflow-state.py")
ws = importlib.util.module_from_spec(spec); spec.loader.exec_module(ws)
assert sorted(ws.OWNER_BLOCKED_ON_VALUES) == ["agent_dispatch", "external", "human_gate", "transport", "usage_limit"], ws.OWNER_BLOCKED_ON_VALUES
assert "agent_dispatch" not in ws.AUTO_RESUMABLE_BLOCKED_ON
assert (ws.STALL_LIMIT, ws.SCHEMA_VERSION) == (3, 4)
print("constants-ok")
EOF
if git diff --quiet HEAD -- $S/workflow_delivery.py $S/delivery_model; then echo untouched-ok; else exit 1; fi
PYTHONPATH=python python3 -m unittest $T/test_workflow_state.py $T/test_host_admission.py 2>&1 \
  | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
```

Expected: the filtered run shows `Ran 19 tests` and `OK`. Then `constants-ok` and
`untouched-ok`. The two whole suites together show `Ran 174 tests` and `OK`,
which is the base count plus these 3 tests; a sync merge that adds tests raises
it. The whole-suite run takes about 4 minutes.

- [ ] **Step 5: Commit**

```bash
set -euo pipefail
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
git add $S/workflow-state.py $T/test_workflow_state.py
git commit -m "feat(workflow-state): add the agent_dispatch suspension cause" \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013ho926R9qjak8E3fLvEdq6"
```
