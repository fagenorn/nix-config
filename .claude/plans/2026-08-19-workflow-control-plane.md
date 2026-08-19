# Workflow Control Plane Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Make `workflow-state control` the single compact, deterministic dispatcher
interface and reduce `orchestrate-issues` to external observation, action execution,
one-shot waiting, and final rendering.

**Architecture:** The existing locked ledger remains the durable source of truth and
keeps schema version 1. A strict interface-version-1 request enters through the Python
CLI; one transaction validates observations, applies lifecycle precedence, records
accepted launches, and returns bounded summaries, current deltas, typed actions, and
one deadline. The Claude skill becomes the adapter for tracker, worktree, owner, spawn,
wait, and report I/O. See the accepted spec and D1–D9.

**Tech stack:** Python 3 standard library (`argparse`, `copy`, `datetime`, `fcntl`,
`json`, `pathlib`, atomic filesystem operations); `unittest` subprocess/CLI tests;
Markdown skill contracts; JSON eval fixtures; Nix/Just verification.

**Spec:** `.claude/specs/2026-08-19-workflow-control-plane-design.md` is the source of
truth. It owns the only issue-level decision ledger; this plan cites D1–D9 and does not
duplicate its rows.

## Global Constraints

- Keep durable `SCHEMA_VERSION = 1`; the control wire contract uses
  `interface_version = 1` independently (D2).
- Keep `init-run`, `progress`, and `finish` behavior and their CLI shapes. Remove the
  public `launch` and `reconcile` commands only after every in-repository caller and
  test uses `control` (D1).
- The helper remains Python-standard-library-only and performs no tracker, Git,
  worktree, process-spawn, sleep, polling, or wall-clock I/O. `request["now"]` is its
  only decision instant (D3).
- Request and response objects are strict closed shapes. Unknown fields, versions,
  enum members, identities, duplicates, non-monotonic times, relative paths, and facts
  outside the requested issue set fail before the ledger is rewritten.
- Every accepted `spawn`, `resume`, or `retry` is represented in the ledger before its
  envelope can reach stdout (D5).
- Response JSON remains canonical (`sort_keys=True`, compact separators),
  newline-terminated, and bounded as specified by D4. It exposes no attempt history,
  launches, phase inputs, result provenance, or older results.
- Resume, retry, and first-spawn precedence, issue-order tie breaking, two-attempt cap,
  and verified matching-worktree reuse follow D6 and D7. No task may recreate this
  policy in skill prose.
- Tests use only the control CLI, owner CLI commands, and reopened `state.json`; they
  never import transition helpers (D8).
- Any prose written into `SKILL.md` or eval JSON must describe the behavior present in
  the code at that task's commit. Derive exact wording from the implementation if a
  sentence in this plan is less precise than the live behavior.
- Commits remain SSH-signed and include `Co-Authored-By: Codex
  <noreply@openai.com>`. Never disable signing.
- Baseline commit is `26175d953d5bac78f190d0c53bde4b38746b3030`.

## File structure

- `home/common/agent-skills/scripts/workflow-state.py` — sole owner of request
  validation, lifecycle scheduling policy, atomic launch persistence, compact response
  construction, and the four public lifecycle commands.
- `home/common/agent-skills/tests/test_workflow_state.py` — subprocess CLI and reopened
  filesystem contract, including malformed inputs, policy precedence, concurrency,
  compactness, and five combined demo scenarios.
- `home/common/claude-code/skills/orchestrate-issues/SKILL.md` — adapter-only dispatcher
  contract; it gathers normalized observations and executes returned envelopes.
- `home/common/agent-skills/skills/from-issue/SKILL.md` — owner-side handoff wording;
  owners retain `progress`/`finish` and are resumed only from a dispatcher envelope.
- `home/common/claude-code/skills/orchestrate-issues/evals/evals.json` — deployed
  grader for the new control seam and absence of hand-assembled policy.
- `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — exact skill/eval
  anchors for the adapter boundary and retired commands.

No Nix module, resolver, Just recipe, durable schema, ADR, glossary, or context map
changes (D2, D9).

## Test seams

- **Control CLI seam:** subprocess `init-run`, `control`, `progress`, and `finish` with
  file-backed JSON and injected timestamps; assert exit status and canonical stdout.
- **Durable filesystem seam:** reopen `state.json` after every control decision and
  after concurrent `finish` subprocesses; assert persistence precedes envelope output.
- **Scenario seam:** five named multi-issue demo tests in the existing workflow-state
  test module cover the combined replay in the spec.
- **Skill contract seam:** exact prose and eval assertions prove normalized
  observations, the five action kinds, one superseding wait, finalize rendering, and
  absence of retired dispatcher policy.
- **Build seam:** `just agent-workflow-tests`, then `just build`.

An implementer needing another seam must stop: that is a plan defect, not license to
test an internal transition function.

## Task index

| ID | Title | Exact files | Risk lane |
| --- | --- | --- | --- |
| Task 1 | Add the strict versioned control CLI and bounded response | `home/common/agent-skills/scripts/workflow-state.py`; `home/common/agent-skills/tests/test_workflow_state.py` | full |
| Task 2 | Move lifecycle scheduling and the five combined demos behind control | `home/common/agent-skills/scripts/workflow-state.py`; `home/common/agent-skills/tests/test_workflow_state.py` | full |
| Task 3 | Retire launch/reconcile and migrate the remaining lifecycle suite | `home/common/agent-skills/scripts/workflow-state.py`; `home/common/agent-skills/tests/test_workflow_state.py` | full |
| Task 4 | Make orchestrate-issues a control adapter and migrate its grader | `home/common/claude-code/skills/orchestrate-issues/SKILL.md`; `home/common/agent-skills/skills/from-issue/SKILL.md`; `home/common/claude-code/skills/orchestrate-issues/evals/evals.json`; `home/common/agent-skills/tests/test_workflow_skill_contracts.py` | full |

Every task is `full`: all four touch lifecycle behavior or a public command/agent
contract. No deletion in Task 3 qualifies as mechanical because it removes public CLI
surface.

## Decisions

The spec's `## Decision ledger` is authoritative. Tasks cite D1–D9 at the exact points
where those bindings constrain implementation. Planning introduced no new non-obvious
decision, so no ledger row is added.

---

### Task 1: Add the strict versioned control CLI and bounded response

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes: the existing `transact`, `validate_state`, `parse_utc`, `format_utc`,
  `validate_result`, and `print_json` functions; the durable schema is unchanged.
- Produces:
  - CLI: `workflow-state control --repo-root <root> --run-id <run-id>
    --request-file <absolute-json-path>`.
  - `CONTROL_INTERFACE_VERSION = 1`.
  - `load_control_request(path_value: str) -> dict[str, Any]`, which rejects a
    non-absolute request path, unreadable/invalid JSON, and every structural or
    closed-set violation before transaction mutation.
  - `command_control(args: argparse.Namespace) -> int`, which runs one transaction and
    prints exactly one canonical response line.
  - Test helpers:
    `tracker_fact(issue: int, *, state: str = "open", open_blockers: list[int] | None = None,
    decision_blockers: list[dict[str, Any]] | None = None) -> dict[str, Any]`;
    `worktree_fact(issue: int, *, recorded: dict[str, Any] | None = None,
    candidate: dict[str, Any] | None = None) -> dict[str, Any]`;
    `control_request(*, now: str, issues: list[int], tracker: list[dict[str, Any]],
    worktrees: list[dict[str, Any]], owners: list[dict[str, Any]] | None = None,
    max_parallel: int = 2, attempt_budget_minutes: int = 30) -> dict[str, Any]`;
    `control_raw(*, request: dict[str, Any] | None = None, ok: bool = True,
    **request_fields: Any) -> subprocess.CompletedProcess[str]`; and
    `control(**request_fields: Any) -> dict[str, Any]`.

**Invariants:**
- The request has exactly the eight top-level fields and nested exact shapes from the
  spec. Plain positive integers reject booleans. `issues` is ordered and unique;
  tracker has exactly one observation per requested issue; owner event IDs are
  nonempty; worktree observations are unique and within `issues`.
- `now` is RFC3339 UTC and is not earlier than durable `updated_at`.
- Recorded paths are absolute and equal the latest attempt's durable worktree.
  Candidate paths are absolute and carry only `state: "absent"`.
- A candidate is required only when this invocation accepts a fresh attempt needing a
  new path; a recorded observation is required only when a current action needs it.
  Missing action-critical facts fail without changing `state.json` (D3, D7).
- Response top-level fields are exactly `interface_version`, `run_id`, `now`,
  `summaries`, `deltas`, `actions`, `next_deadline`. Summary, delta, dispatch, wait,
  and finalize fields and enum members are exactly those in the spec (D4).
- Collections follow request issue order; output is canonical and newline-terminated.
- This task implements enough scheduling for never-launched ready issues, blocked,
  fogged, tracker-closed, no-deadline wait, and drained finalize. Task 2 adds
  expiry/resume/retry policy.
- `launch` and `reconcile` remain temporarily callable so this task's commit is green;
  Task 3 removes them after migration (D1).

- [ ] **Step 1: Add the failing CLI contract tests**

Add `import copy`, initialize `self.control_request_serial = 0` in `setUp`, and add the
fixture helpers beside the existing lifecycle test helpers exactly as follows. The
fixture builds values but intentionally performs no production validation:

```python
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
```

Then add these tests:

```python
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
        self.assertEqual(
            completed.stdout,
            json.dumps(response, sort_keys=True, separators=(",", ":")) + "\n",
        )
        self.assertEqual(set(response), {
            "interface_version", "run_id", "now", "summaries", "deltas",
            "actions", "next_deadline",
        })
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
        self.assertEqual(waiting["actions"], [{
            "id": "wait:external",
            "kind": "wait",
            "wake_on": ["owner_notification", "tracker_change"],
            "deadline_at": None,
        }])
        self.assertIsNone(waiting["next_deadline"])
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
            "unknown-version": lambda value: value.__setitem__("interface_version", 2),
            "unknown-field": lambda value: value.__setitem__("extra", True),
            "duplicate-issue": lambda value: value["issues"].append(47),
            "missing-tracker": lambda value: value["tracker"].clear(),
            "duplicate-tracker": lambda value: value["tracker"].append(dict(value["tracker"][0])),
            "unknown-tracker-state": lambda value: value["tracker"][0].__setitem__("state", "merged"),
            "unknown-tracker-field": lambda value: value["tracker"][0].__setitem__("title", "x"),
            "boolean-parallelism": lambda value: value.__setitem__("max_parallel", True),
            "relative-candidate": lambda value: value["worktrees"][0]["candidate"].__setitem__("path", "wt-47"),
            "unknown-candidate-state": lambda value: value["worktrees"][0]["candidate"].__setitem__("state", "free"),
            "outside-issue": lambda value: value["worktrees"][0].__setitem__("issue", 99),
            "backward-time": lambda value: value.__setitem__("now", "2026-08-19T11:59:59Z"),
        }
        before = self.state_path.read_bytes()
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                request = copy.deepcopy(valid)
                mutate(request)
                completed = self.control_raw(request=request, ok=False)
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(completed.stdout, "")
                self.assertEqual(self.state_path.read_bytes(), before)
```

- [ ] **Step 2: Run the focused tests and observe the red state**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-47-workflow-control-plane/home/common/agent-skills
python3 -m unittest -v \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_starts_ready_issues_persists_before_emission_and_bounds_output \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_response_is_canonical_compact_and_current_only \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_returns_external_wait_and_finalize_from_current_facts \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_rejects_bad_observations_without_rewriting_the_ledger \
  2>&1 | tail -30
```

Expected: FAIL because `control` is not a recognized command; `state.json` remains
byte-identical in the rejection case.

- [ ] **Step 3: Implement the strict request and response boundary**

In `workflow-state.py`:

1. Declare tuples/frozensets beside the existing schema constants for every exact
   control request/response shape and enum. Keep interface constants separate from
   durable-schema constants (D2).
2. Implement `load_control_request` and nested validators. Read the request file before
   entering `transact`, then repeat ledger-dependent identity/path/timestamp checks
   inside the locked mutation. Every closed-set default raises `WorkflowError`.
3. Add a `control` parser with only `--repo-root`, `--run-id`, and `--request-file`;
   unlike the other commands it has no `--now` because `now` is in the request.
4. For the scheduling subset in this task, derive blocked/fogged/closed/queued states,
   fill capacity with never-launched ready issues in request order, and use only a
   verified absent candidate. Create attempts with owner `<issue>:1`, one fresh launch
   at request `now`, and fixed deadline `now + attempt_budget_minutes`.
5. Reuse the existing locked state mutation and atomic replace. Construct the response
   only from the post-mutation state. Append exactly one `wait` or `finalize` envelope
   after dispatch envelopes.
6. Build summaries field-by-field; never copy an attempt dict into a response. Build
   blockers as homogeneous `{kind, issue, url}` objects; all top-level collections
   preserve requested issue order.

- [ ] **Step 4: Verify the task**

Run the Step 2 command again. Expected: all four tests pass. Then run:

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-47-workflow-control-plane/home/common/agent-skills
python3 -m unittest tests.test_workflow_state -q
```

Expected: `OK`; all pre-existing public-command tests also remain green at this
intermediate commit. Any response containing a forbidden history key or any changed
ledger bytes after a rejected request blocks the commit.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
git commit -m "feat(workflow-state): add the versioned control boundary

Validates normalized observations and returns canonical bounded scheduling
responses while preserving schema version 1. Per D2-D5 and D8.

Co-Authored-By: Codex <noreply@openai.com>"
```

---

### Task 2: Move lifecycle scheduling and the five combined demos behind control

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes from Task 1: `control`, its strict request/response shapes, canonical output,
  test fixture helpers, and atomically persisted first-spawn actions.
- Produces: complete control behavior for owner notifications, expiry, handed-off and
  unavailable-owner resume, terminal retry/refusal, maximum-parallel accounting,
  earliest deadline, idempotent advanced-state replay, and deterministic copied-state
  replay.
- Dispatch action IDs are `<issue>:<attempt>:<launch-ordinal>` and lifecycle owners are
  `<issue>:<attempt>`. `wait` IDs are `wait:<deadline>` or `wait:external`.

**Invariants:**
- Full validation and durable-result authority precede every mutation; expiry precedes
  readiness; capacity filling is resume, retry, then first spawn, preserving issue order
  within each pass (D6).
- An `unavailable` owner event may name only an existing current/past launch. A future or
  nonexistent launch fails atomically. A stale launch/attempt notification is ignored.
  A current event is consumed by appending the next launch ordinal, so replay cannot
  emit it again.
- Resume preserves attempt, owner, worktree, start, deadline, phase data, and handoff;
  it appends one resume launch. A resume needing a missing/mismatched recorded worktree
  fails loudly.
- Retry creates only attempt 2, derives a new owner, keeps a verified
  `matching_issue_branch` recorded path or requires a verified absent candidate, and
  never creates attempt 3 (D7).
- Tracker blockers/fog/closed suppress new spawn or retry but do not terminate a
  nonterminal durable attempt. Owner `stopped` is not retried; owner `failed` and
  provisional expiry are retryable once; merged is final (D6).
- `next_deadline` is the minimum deadline among latest active/handed-off attempts and
  equals the terminal wait envelope. Dispatch-action count is at most `max_parallel`;
  exactly one control action ends every response (D4).
- A late `finish` on the latest expired attempt remains authoritative. Concurrent
  finishes serialize through the existing lock and both survive reopen.

- [ ] **Step 1: Write the five combined demo scenarios**

Add exactly these five test methods. Each is a multi-issue CLI scenario and uses only
Task 1's fixture helpers plus existing `finish`, `progress`, `write_handoff`, and
`read_state` helpers:

```python
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
```

Add the helpers used above exactly as follows. The barrier makes both terminal writers
contend on the real lock; the copied ledger is built from the supplied captured bytes,
never from the current advanced file:

```python
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
```

Add these focused cases after the demos. They pin the individual policies whose
composition the demos exercise:

```python
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
        self.assertEqual([a["kind"] for a in response["actions"]],
                         ["resume", "resume", "retry", "spawn", "wait"])
        self.assertEqual([a["id"] for a in response["actions"][:-1]],
                         ["47:1:2", "51:1:2", "53:2:1", "59:1:1"])

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
        self.assertIn("retry_refused", [d["kind"] for d in refused["deltas"]])
        self.assertEqual(len(self.read_state()["issues"]["51"]["attempts"]), 2)

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
```

- [ ] **Step 2: Run the new scenarios and observe the red state**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-47-workflow-control-plane/home/common/agent-skills
python3 -m unittest -v \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_demo_1_starts_two_and_waits_at_the_earliest_deadline \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_demo_2_late_merged_finish_beats_the_deadline \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_demo_3_expires_retries_and_fills_unrelated_capacity \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_demo_4_concurrent_finishes_survive_reopen \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_demo_5_finalizes_and_replays_without_history_or_duplicate_launch \
  2>&1 | tail -35
```

Expected: demo 1 passes from Task 1; demos 2–5 fail on absent expiry/retry/replay/drain
behavior. A test that fails only because of test-fixture setup must be corrected before
implementation begins.

- [ ] **Step 3: Implement the complete transaction policy**

Inside `command_control`'s one `transact` callback, implement the spec's numbered order
literally:

1. Validate every observation and all ledger-dependent identities before mutation.
2. Leave durable terminal owner results authoritative; classify stale notifications
   without writing.
3. Expire every latest active/handed-off attempt whose fixed deadline is reached using
   the existing provisional expiry record.
4. Derive readiness from normalized tracker facts without terminating active work.
5. Compute occupied capacity from post-expiry latest attempts.
6. In three issue-ordered passes, accept resumes, then retries, then first spawns until
   capacity is full. Reuse existing attempt construction/stop logic internally; do not
   call a public command handler from another handler.
7. Record each accepted launch before placing its envelope in the response. Emit only
   current-invocation deltas; repeated control over advanced state emits none.
8. Recompute summaries and minimum deadline from the committed post-transition state,
   then append exactly one wait/finalize envelope.

Do not add pending-action acknowledgements or exactly-once process claims (D5). Do not
write owner event IDs into schema-v1 state; current launch ordinal is the replay guard.

- [ ] **Step 4: Verify focused policy and the complete CLI module**

Run the Step 2 command, then:

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-47-workflow-control-plane/home/common/agent-skills
python3 -m unittest tests.test_workflow_state -q
```

Expected: `OK`. All five demos and all focused policy cases pass; reopening the ledger
shows each emitted dispatch launch already present. Any duplicate action on advanced
replay, noncanonical copied-state replay, lost concurrent result, or leaked history key
blocks the commit.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
git commit -m "feat(workflow-state): centralize dispatcher lifecycle policy

Applies expiry and resume-retry-spawn precedence atomically, persists actions
before emission, and proves the five combined replay scenarios. Per D4-D8.

Co-Authored-By: Codex <noreply@openai.com>"
```

---

### Task 3: Retire launch/reconcile and migrate the remaining lifecycle suite

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes from Task 2: complete `control` semantics and the test request builders.
- Produces: the final public parser exposes exactly `init-run`, `control`, `progress`,
  and `finish`. All retained lifecycle tests create/resume/retry/expire attempts through
  subprocess `control` calls.

**Invariants:**
- No in-repository test or caller invokes `workflow-state launch` or
  `workflow-state reconcile` after this task (D1, D8).
- Owner-facing `progress` and `finish` keep their exact flags, terminal authority,
  idempotency, path-hardening, and concurrent locking behavior.
- Tests covering durable attempt validation, fixed deadlines, late finish, phase
  decisions, safe handoffs, atomic conflict rejection, symlink/path attacks, canonical
  results, and concurrent writers remain behaviorally equivalent at the CLI seam.
- Tests that existed only to assert arbitrary dispatcher-provided owner identities or a
  retired command's output shape are replaced with control-contract assertions; they
  are not silently deleted.
- `command_launch`/`command_reconcile` may be split into internal domain operations if
  useful, but no parser, handler, help text, or test reaches them as public commands.

- [ ] **Step 1: Write the retirement test and migrate test setup first**

Add:

```python
    def test_public_cli_exposes_only_the_four_lifecycle_commands(self):
        completed = self.run_cli("--help")
        self.assertIn("{init-run,control,finish,progress}", completed.stdout)
        self.assertNotIn("launch", completed.stdout)
        self.assertNotIn("reconcile", completed.stdout)
        for retired in ("launch", "reconcile"):
            rejected = self.run_cli(retired, ok=False)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("invalid choice", rejected.stderr)
```

Before deleting production handlers, migrate every older test:

- Replace every setup call to the legacy `self.launch` helper with a one-issue control
  request carrying a verified
  absent candidate; obtain attempt identity from the returned dispatch envelope.
- Replace resume calls with a handed-off attempt or a current `unavailable` observation
  plus a matching recorded-worktree fact.
- Replace retry calls with an owner-failed or expired latest attempt plus a matching
  recorded worktree/candidate fact.
- Replace every call to the legacy `self.reconcile` helper with `self.control`, passing
  an explicit injected timestamp and only the facts needed by that decision.
- Change expected owners from arbitrary strings to `<issue>:<attempt>` and expected
  launch ordinals/action IDs accordingly.
- Preserve all direct `progress` and `finish` subprocesses.

Run this inventory gate after editing the tests:

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-47-workflow-control-plane
if rg -n 'self\.(launch|reconcile)\(' home/common/agent-skills/tests/test_workflow_state.py; then
  exit 1
fi
```

Expected before migration: nonzero with the legacy helper call sites printed. Expected
after test migration: zero and no output.

- [ ] **Step 2: Run the migrated suite and observe the red retirement contract**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-47-workflow-control-plane/home/common/agent-skills
python3 -m unittest tests.test_workflow_state -q
```

Expected: exactly the new public-command test fails because help still advertises
`launch` and `reconcile`; every migrated behavioral test passes through `control`.

- [ ] **Step 3: Remove the retired public surface**

Delete the `launch` and `reconcile` subparsers and their public handlers. Retain or
extract only the internal attempt-construction, resume, expiry, and refusal operations
that `control` uses. Ensure internal names describe domain transitions rather than
retired CLI commands. Remove obsolete test helper methods and imports made unused by
the migration.

Do not alter ledger field names, `progress`, `finish`, locking, atomic replace, or
filesystem hardening while deleting the surface.

- [ ] **Step 4: Verify the final helper contract**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-47-workflow-control-plane/home/common/agent-skills
python3 -m unittest tests.test_workflow_state -q
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-47-workflow-control-plane
if rg -n 'def command_(launch|reconcile)|add_parser\("(launch|reconcile)"' \
  home/common/agent-skills/scripts/workflow-state.py; then
  exit 1
fi
```

Expected: `OK`; the prohibition prints nothing and exits zero. Any loss of a retained
lifecycle/path/concurrency assertion blocks the commit.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
git commit -m "refactor(workflow-state): retire dispatcher transition commands

Removes launch and reconcile from the public CLI after migrating every lifecycle
test to the versioned control seam. Per D1 and D8.

Co-Authored-By: Codex <noreply@openai.com>"
```

---

### Task 4: Make orchestrate-issues a control adapter and migrate its grader

**Files:**
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/claude-code/skills/orchestrate-issues/evals/evals.json`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes from Task 3: the exact control request/response contract and final four-command
  public CLI.
- Produces:
  - Dispatcher flow: resolve inputs/bindings; query tracker facts; inspect exact
    worktree facts; normalize any owner notification; call `control`; execute returned
    actions in order; arm at most one wait; render finalize summaries.
  - Owner dispatch envelope: immutable ledger root, run ID, issue/attempt, lifecycle
    owner token, exact worktree, optional handoff path, literal
    `from-issue <num> --auto`.
  - Contract/eval assertions for all five action kinds and absence of manual policy.

**Invariants:**
- The dispatcher does not read issue content, code, specs, plans, diffs, or review
  findings. Tracker and worktree adapters normalize external facts only (D3).
- The skill does not count attempts/capacity, classify retryable results, choose
  resume/retry/spawn precedence, calculate deadline minima, infer drain, or call retired
  commands. It follows the returned action order (D1, D6).
- `spawn`, `resume`, and `retry` pass helper-issued owner/action identity unchanged;
  `resume` includes the durable handoff path when present. Host task IDs remain outside
  the lifecycle contract.
- A wait envelope schedules at most one one-shot wake keyed by its ID. A later response
  supersedes the previous wait; no polling loop or repeated short sleep exists.
- A finalize envelope renders the final table and discussion items from the same
  response's bounded summaries; no second ledger reconstruction occurs (D4).
- `from-issue` retains `progress` and `finish`; its handoff text says the dispatcher
  resumes from a returned `resume` envelope and contains no owner-side `launch` call.
- Eval expected outputs move in the same commit as skill prose and grade normalized
  facts, `control`, typed action execution, compact output, and retired-policy absence.

- [ ] **Step 1: Replace the old skill tests with failing control-contract tests**

In `WorkflowSkillContractsTest`, replace launch/reconcile-specific assertions with:

```python
    def test_dispatcher_is_a_control_adapter_not_a_policy_owner(self):
        self.assert_ordered(
            self.orchestrate,
            "resolve-bindings",
            "normalized",
            "--request-file <absolute-json-path>",
            "workflow-state control",
            "execute",
        )
        for retired in ("workflow-state launch", "workflow-state reconcile"):
            self.assertNotIn(retired, self.orchestrate)
        for retired_policy in (
            "resume before fresh", "refuses a third fresh attempt",
            "earliest armed deadline", "counts occupied slots",
        ):
            self.assertNotIn(retired_policy, self.orchestrate)

    def test_dispatcher_executes_the_closed_control_action_set(self):
        action_section = self.section(
            self.orchestrate, "## 4. Execute control actions", "## 5. Final report"
        )
        for kind in ("spawn", "resume", "retry", "wait", "finalize"):
            self.assertIn(f"`{kind}`", action_section)
        self.assertIn("returned order", action_section)
        self.assertIn("owner token unchanged", action_section)
        self.assertIn("handoff_path", action_section)
        self.assertNotIn("host task ID as lifecycle", action_section)

    def test_dispatcher_uses_one_superseding_wait(self):
        self.assert_ordered(
            self.orchestrate,
            "wait ID", "exactly one", "one-shot", "supersedes",
        )
        self.assertIn("owner_notification", self.orchestrate)
        self.assertIn("tracker_change", self.orchestrate)
        self.assertIn("deadline", self.orchestrate)
        self.assertIn("No polling or repeated short sleeps", self.orchestrate)

    def test_dispatcher_renders_finalize_from_bounded_summaries(self):
        final_section = self.section(
            self.orchestrate, "## 5. Final report", "## Notes"
        )
        self.assertIn("finalize", final_section)
        self.assertIn("same control response", final_section)
        self.assertIn("discussion_items", final_section)
        for forbidden in ("attempts", "launches", "phase_inputs", "older results"):
            self.assertIn(forbidden, self.orchestrate)

    def test_from_issue_handoff_is_resumed_only_from_a_control_envelope(self):
        phase_gate = self.section(
            self.from_issue, "## Dispatch, phase-budget and attempt-budget rules",
            "## Terminal return procedure",
        )
        self.assertIn("returned `resume` envelope", phase_gate)
        self.assertNotIn("workflow-state launch", phase_gate)

    def test_orchestrate_evals_grade_control_and_reject_retired_policy(self):
        expected = " ".join(
            case["expected_output"] for case in self.orchestrate_evals["evals"]
        )
        for anchor in (
            "workflow-state control", "normalized", "spawn", "resume", "retry",
            "wait", "finalize", "bounded summaries",
        ):
            self.assertIn(anchor, expected)
        for retired in ("workflow-state launch", "workflow-state reconcile"):
            self.assertNotIn(retired, expected)
```

Keep the existing background-agent placement, immutable ledger-root, lifecycle-envelope,
phase-gate, terminal-write, exact-worktree adoption, and bare-helper-path tests. Update
only their retired command anchors.

- [ ] **Step 2: Run the contract tests and observe the red state**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-47-workflow-control-plane/home/common/agent-skills
python3 -m unittest tests.test_workflow_skill_contracts.WorkflowSkillContractsTest -q
```

Expected: FAIL because the skill/evals still call `launch`/`reconcile`, narrate policy,
and the owner handoff still tells itself to launch.

- [ ] **Step 3: Rewrite the live skill and eval contracts**

Rewrite `orchestrate-issues/SKILL.md` around these sections, keeping its role boundary
and Claude-only dispatch metadata:

1. **Resolve issue set and bindings:** preserve explicit/list ordering and resolve
   `maxParallel`/`agentBudgetMinutes` through the existing binding resolver.
2. **Observe:** one tracker read supplies state, open blockers, and decision blockers;
   inspect recorded paths/candidates only as required to answer the next control
   request. Normalize the exact version-1 request without retaining a second task
   ledger.
3. **Decide:** invoke `init-run` once, then `control` at start/resume and on each owner,
   tracker, or deadline event. Treat the response as authoritative and do not infer
   another action.
4. **Execute control actions:** in returned order, spawn background owners for
   `spawn`/`resume`/`retry` using unchanged lifecycle tokens and exact paths; schedule
   one one-shot wake for `wait`; end and render on `finalize`. Fail loudly on an unknown
   kind.
5. **Final report:** render issue/state/PR/reason and grouped discussion items from the
   same finalize response's summaries.

State explicitly that responses omit `attempts`, `launches`, `phase_inputs`, and older
results so no prose reader is invited to rebuild policy. Delete all attempt counting,
resume/retry classification, worktree choice, deadline calculation, and drain decision
text.

In `from-issue/SKILL.md`, replace only the handoff continuation sentence with live
behavior: after persisting the handoff, stop; the dispatcher later relaunches the same
lifecycle owner/worktree/handoff from a returned `resume` envelope. Do not change phase
budget, terminal finish, or Phase-1 exact-path adoption.

Update both eval cases so their expected outputs grade the new adapter sequence and the
closed action set. Keep plan-only mode and existing role-boundary failures. JSON must
remain parseable and contain no retired command.

- [ ] **Step 4: Run focused, full-suite, and build verification**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-47-workflow-control-plane/home/common/agent-skills
python3 -m unittest tests.test_workflow_skill_contracts.WorkflowSkillContractsTest -q
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-47-workflow-control-plane
python3 -m json.tool home/common/claude-code/skills/orchestrate-issues/evals/evals.json >/dev/null
if rg -n 'workflow-state (launch|reconcile)' \
  home/common/claude-code/skills/orchestrate-issues/SKILL.md \
  home/common/agent-skills/skills/from-issue/SKILL.md \
  home/common/claude-code/skills/orchestrate-issues/evals/evals.json; then
  exit 1
fi
just agent-workflow-tests
just build
```

Expected: focused tests and JSON validation pass; the retired-command check prints
nothing; `just build` succeeds. `just agent-workflow-tests` must have no product/test
regression. In the known restricted sandbox it may report the pre-existing sole
`tests/test_agent_costs.py` `ProcessPoolExecutor` semaphore `PermissionError` (baseline
225/226); outside that sandbox every test must pass. The exception is diagnostic only:
any additional failure or any different failure blocks completion, and the gate must
not be skipped or weakened.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/skills/orchestrate-issues/SKILL.md \
  home/common/agent-skills/skills/from-issue/SKILL.md \
  home/common/claude-code/skills/orchestrate-issues/evals/evals.json \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(orchestrate-issues): consume workflow control actions

Moves the dispatcher contract and deployed evals to normalized observations,
typed control actions, one-shot waiting, and bounded final summaries. Per D1-D8.

Co-Authored-By: Codex <noreply@openai.com>"
```

---

## Acceptance coverage

| Spec requirement | Owning task |
| --- | --- |
| Strict versioned request and response, injected time, atomic rejection | Task 1 |
| Bounded summaries/deltas/actions and compact-output verification | Tasks 1–2 |
| Persist-before-emission and deterministic action IDs | Tasks 1–2 |
| Expiry, resume-before-retry-before-spawn, attempt cap, worktree reuse | Task 2 |
| Five combined demo scenarios, concurrent finish, copied/advanced replay | Task 2 |
| Public `launch`/`reconcile` removal and CLI-only migrated tests | Task 3 |
| Adapter-only dispatcher, five envelopes, one-shot wait, finalize rendering | Task 4 |
| Owner handoff continuation and deployed eval migration | Task 4 |
| Focused tests, whole workflow suite, and Nix distribution build | Task 4 |
