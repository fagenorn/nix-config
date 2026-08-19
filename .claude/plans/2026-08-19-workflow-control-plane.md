# Workflow Control Plane Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Make `workflow-state control` the single compact, deterministic dispatcher
interface and reduce `orchestrate-issues` to external observation, action execution,
one-shot waiting, and final rendering.

**Architecture:** The existing locked ledger remains the durable source of truth and
keeps schema version 1. `init-run` returns a strict bounded latest-requirement bootstrap;
a strict interface-version-1 request then enters the sole policy command, `control`,
whose one transaction validates observations, applies lifecycle precedence, records
accepted launches, and returns bounded summaries, current deltas, typed actions, and
one deadline. The Claude skill becomes the adapter for tracker, worktree, owner, spawn,
replaceable one-shot wait, and report I/O. See D1–D15.

**Tech stack:** Python 3 standard library (`argparse`, `copy`, `datetime`, `fcntl`,
`json`, `pathlib`, atomic filesystem operations); `unittest` subprocess/CLI tests;
Markdown skill contracts; JSON eval fixtures; Nix/Just verification.

**Spec:** `.claude/specs/2026-08-19-workflow-control-plane-design.md` is the source of
truth. It owns the only issue-level decision ledger; this plan cites D1–D15 and does not
duplicate its rows.

## Global Constraints

- Keep durable `SCHEMA_VERSION = 1`; the control wire contract uses
  `interface_version = 1` independently for bounded bootstrap and control messages
  (D2, D10).
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
- Capacity is `max(0, max_parallel - occupied)`, where `occupied` counts only latest
  active attempts without a current unavailable observation. Handed-off/current-
  unavailable attempts consume a slot only when their resume action is accepted (D12).
- `init-run` returns one exact latest requirement per durable issue and never raw state,
  attempts, launches, phase history, deadlines, handoffs, or results (D10).
- D13 permits a consumed candidate only for actionless identical-request replay. Wrong
  instant/path, same-instant terminal state, or current-unavailable state rejects it;
  any new dispatch requires current worktree facts.
- The adapter gathers a verified absent candidate for every requested issue without an
  `init-run` requirement and for each absent/mismatched returned path. It never
  classifies tracker readiness; `control` ignores candidates it does not use (D15).
- Wait replacement follows D11 and D14: missing/already-exited cancellation is
  idempotent; an arm failure clears truthful adapter wait state and fails loudly; the
  host reaps inherited detached observers before a full restart rearms.
- Tests use only the control CLI, owner CLI commands, and reopened `state.json`; they
  never import transition helpers (D8).
- Any prose written into `SKILL.md` or eval JSON must describe the behavior present in
  the code at that task's commit. Derive exact wording from the implementation if a
  sentence in this plan is less precise than the live behavior.
- Commits remain SSH-signed and include `Co-Authored-By: Codex
  <noreply@openai.com>`. Never disable signing.

## File structure

- `home/common/agent-skills/scripts/workflow-state.py` — sole owner of request
  validation, bounded bootstrap projection, lifecycle scheduling policy, atomic launch
  persistence, compact response construction, and the four public lifecycle commands.
- `home/common/agent-skills/tests/test_workflow_state.py` — subprocess CLI and reopened
  filesystem contract, including malformed inputs, policy precedence, concurrency,
  compactness, one combined replay, and focused scenario diagnostics.
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
  file-backed JSON and injected timestamps; assert the exact bootstrap/request/response
  nested shapes, exit status, and canonical stdout.
- **Durable filesystem seam:** reopen `state.json` after every control decision and
  after concurrent `finish` subprocesses; assert persistence precedes envelope output.
- **Scenario seam:** one single-run/single-ledger test carries all six replay stages in
  the spec; focused scenario cases remain independent diagnostics.
- **Skill contract seam:** exact prose and eval assertions prove normalized
  observations, the five action kinds, one superseding wait, finalize rendering, and
  absence of retired dispatcher policy.
- **Build seam:** `just agent-workflow-tests`, then `just build`.

An implementer needing another seam must stop: that is a plan defect, not license to
test an internal transition function.

## Task index

| ID | Title | Exact files | Risk lane |
| --- | --- | --- | --- |
| Task 1 | Add bounded bootstrap and the strict versioned control wire contract | `home/common/agent-skills/scripts/workflow-state.py`; `home/common/agent-skills/tests/test_workflow_state.py` | full |
| Task 2 | Move lifecycle scheduling and the single combined replay behind control | `home/common/agent-skills/scripts/workflow-state.py`; `home/common/agent-skills/tests/test_workflow_state.py` | full |
| Task 3 | Retire launch/reconcile and migrate the remaining lifecycle suite | `home/common/agent-skills/scripts/workflow-state.py`; `home/common/agent-skills/tests/test_workflow_state.py` | full |
| Task 4 | Make orchestrate-issues a control adapter and migrate its grader | `home/common/claude-code/skills/orchestrate-issues/SKILL.md`; `home/common/agent-skills/skills/from-issue/SKILL.md`; `home/common/claude-code/skills/orchestrate-issues/evals/evals.json`; `home/common/agent-skills/tests/test_workflow_skill_contracts.py` | full |

Every task is `full`: all four touch lifecycle behavior or a public command/agent
contract. No deletion in Task 3 qualifies as mechanical because it removes public CLI
surface.

## Decisions

The spec's `## Decision ledger` is authoritative. Tasks cite D1–D15 at the exact points
where those bindings constrain implementation. Phase-5 review added D10–D12,
self-review added D13, and final re-review added D14–D15; this plan does not duplicate
their rows.

## Phase-5 review provenance and dispositions

- Reviewer: native fresh reviewer `/root/issue47_plan_review`
- Artifact: `/Users/anis/tmp/nix-config/.git/worktrees/issue-47-workflow-control-plane/PLAN-REVIEW.md`
- Reviewed base SHA: `68f52bc16f237fdfb6df82e141ea07adf5cdfe92`
- Fallback: native because `codex-collaboration` was unavailable

| Finding | Disposition |
| --- | --- |
| Single combined replay missing | accepted — Task 2 now carries the exact six stages in one run/ledger |
| Restart bootstrap not actionable | accepted — Task 1 adds the D10 strict bounded `init-run` projection |
| Wire shapes under-tested | accepted — Task 1 pins malformed inputs and exact nested variants |
| Wait supersession non-operational | accepted — Task 4 pins D11 cancellation/replacement/stale-wake behavior |
| Retired-policy checks fragile | accepted — Task 4 scopes positive response-only behavior and forbidden policy vocabulary |
| Standalone lifecycle stale | accepted — Task 4 pins direct ledger-free use and D10 durable bootstrap/adoption |
| Capacity formula implicit | accepted — Task 2 implements and tests D12 explicitly |

### Final re-review provenance and dispositions

- Reviewer: native fresh reviewer `/root/issue47_plan_review`
- Artifact: `/Users/anis/tmp/nix-config/.git/worktrees/issue-47-workflow-control-plane/PLAN-REVIEW.md`
- Reviewed HEAD: `c4e3862de6478c22d296cec047050b4f3ba67e70`
- Fallback: native because `codex-collaboration` was unavailable

| Finding | Disposition |
| --- | --- |
| Adapter still classified tracker readiness | accepted — Task 4 gathers one harmless candidate for every no-requirement issue and leaves classification to control per D15 |
| Bootstrap/D13 tests did not discriminate latest identity and unsafe near-misses | accepted — Task 2 pins post-resume/post-retry projection plus actionless replay and all requested negatives |
| Configured budget migration implicit | accepted — Task 4 migrates the live binding contract to exact request fields |
| Wait failure semantics unspecified | accepted — Task 4 pins idempotent missing/exited cancellation and truthful fail-loud arm failure per D14 |
| Full-restart observer ownership unclear | accepted — Task 4 makes inherited-detached-observer cleanup an explicit host precondition per D14 |

---

### Task 1: Add bounded bootstrap and the strict versioned control wire contract

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes: the existing `transact`, `validate_state`, `parse_utc`, `format_utc`,
  `validate_result`, and `print_json` functions; the durable schema is unchanged.
- Produces:
  - `init-run` response: exact top-level fields `interface_version`, `run_id`,
    `requirements`; each requirement has exactly `issue`, `attempt`, `owner`,
    `action_id`, and `recorded_worktree` (D10).
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
- `init-run` creates/validates the raw state under the existing lock but prints only the
  strict version-1 bootstrap. Requirements are latest-attempt-only, positive-issue
  sorted, canonical, and empty for a fresh run; raw history never crosses stdout.
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
- The only consumed-candidate replay accepted is D13's actionless causal match: the
  latest attempt remains active, has no current-unavailable event, and its same exact
  path was consumed by the first launch at the identical request instant. Wrong
  instant/path, same-instant terminal, current-unavailable, or any request that could
  dispatch remains an atomic rejection and requires current worktree facts.
- Response top-level fields are exactly `interface_version`, `run_id`, `now`,
  `summaries`, `deltas`, `actions`, `next_deadline`. Summary, delta, dispatch, wait,
  and finalize fields and enum members are exactly those in the spec (D4).
- Collections follow request issue order; output is canonical and newline-terminated.
- This task implements enough scheduling for never-launched ready issues, blocked,
  fogged, tracker-closed, no-deadline wait, and drained finalize. Task 2 adds
  expiry/resume/retry policy.
- `launch` and `reconcile` remain temporarily callable so this task's commit is green;
  Task 3 removes them after migration (D1).

- [ ] **Step 1: Add the failing bootstrap and CLI contract tests**

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
                    "discussion_items", "notes",
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
```

Then add these tests:

```python
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
```

- [ ] **Step 2: Run the focused tests and observe the red state**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-47-workflow-control-plane/home/common/agent-skills
python3 -m unittest -v \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_init_run_returns_only_the_strict_bounded_bootstrap \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_starts_ready_issues_persists_before_emission_and_bounds_output \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_response_is_canonical_compact_and_current_only \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_returns_external_wait_and_finalize_from_current_facts \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_rejects_bad_observations_without_rewriting_the_ledger \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_rejects_bad_request_files_and_recorded_path_mismatch \
  2>&1 | tail -30
```

Expected: FAIL because `init-run` still prints raw state and `control` is not a
recognized command; `state.json` remains byte-identical in every rejection case.

- [ ] **Step 3: Implement the strict request and response boundary**

In `workflow-state.py`:

1. Declare tuples/frozensets beside the existing schema constants for the exact
   bootstrap, control request/response, nested object shapes, and enums. Keep interface
   constants separate from durable-schema constants (D2, D10).
2. Change `command_init_run` to create/validate as today but project the post-transaction
   state into exact latest requirements, positive-issue sorted, before `print_json`.
   Never return or copy raw attempt objects to stdout.
3. Implement `load_control_request` and nested validators. Read the request file before
   entering `transact`, then repeat ledger-dependent identity/path/timestamp checks
   inside the locked mutation. Every closed-set default raises `WorkflowError`.
4. Add a `control` parser with only `--repo-root`, `--run-id`, and `--request-file`;
   unlike the other commands it has no `--now` because `now` is in the request.
5. For the scheduling subset in this task, derive blocked/fogged/closed/queued states,
   fill capacity with never-launched ready issues in request order, and use only a
   verified absent candidate. Create attempts with owner `<issue>:1`, one fresh launch
   at request `now`, and fixed deadline `now + attempt_budget_minutes`.
6. Reuse the existing locked state mutation and atomic replace. Construct the response
   only from the post-mutation state. Append exactly one `wait` or `finalize` envelope
   after dispatch envelopes.
7. Build summaries field-by-field; never copy an attempt dict into a response. Build
   blockers as homogeneous `{kind, issue, url}` objects; all top-level collections
   preserve requested issue order.

- [ ] **Step 4: Verify the task**

Run the Step 2 command again. Expected: every focused bootstrap/wire test passes. Then
run:

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
git commit -m "feat(workflow-state): add bounded bootstrap and control boundary

Projects restart requirements, validates normalized observations, and returns
canonical bounded responses while preserving schema version 1. Per D2-D5/D8/D10.

Co-Authored-By: Codex <noreply@openai.com>"
```

---

### Task 2: Move lifecycle scheduling and the single combined replay behind control

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
- `occupied` is exactly the count of latest active attempts without a current
  unavailable observation; `available = max(0, max_parallel - occupied)`. Handed-off
  and current-unavailable attempts do not occupy before selection, and each accepted
  resume/retry/spawn decrements available once (D12).
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
- `init-run` always projects the latest launch identity: a resumed attempt exposes its
  new launch action ID, and a retry exposes the new attempt/owner/first-launch ID (D10).
- D13 is actionless only. Exact active replay may consume its original candidate;
  wrong instant, a collision on the wrong durable path, same-instant terminal state,
  and current-unavailable state reject atomically. Resume/retry/new dispatch requires
  the current recorded/candidate facts.

- [ ] **Step 1: Write one exact six-stage combined replay, then focused scenarios**

Add this test first. It uses one `init_run`, one run ID, and one ledger from initial
dispatch through finalization. The byte-copied root branches only to prove deterministic
replay of the captured pre-action state; it does not replace the main sequence:

```python
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
```

Keep the following five independent tests as focused diagnostics. They use Task 1's
fixture helpers plus existing `finish`, `progress`, `write_handoff`, and `read_state`
helpers, but they do not count as the D8 composition proof:

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
            "discussion_items", "notes",
        })
        self.assertEqual(summary["result"]["state"], "failed")
        self.assertIn("attempts 1 and 2", summary["result"]["notes"])
        persisted = self.read_state()["issues"]["51"]
        self.assertEqual(len(persisted["attempts"]), 2)
        self.assertEqual(persisted["attempts"][-1]["result_source"], "refused")
        self.assertEqual(persisted["outcome"], summary["result"])

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
```

- [ ] **Step 2: Run the new scenarios and observe the red state**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-47-workflow-control-plane/home/common/agent-skills
python3 -m unittest -v \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_combined_six_stage_single_ledger_replay \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_demo_1_starts_two_and_waits_at_the_earliest_deadline \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_demo_2_late_merged_finish_beats_the_deadline \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_demo_3_expires_retries_and_fills_unrelated_capacity \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_demo_4_concurrent_finishes_survive_reopen \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_control_demo_5_finalizes_and_replays_without_history_or_duplicate_launch \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_init_run_bootstrap_projects_latest_resume_and_retry_identity \
  tests.test_workflow_state.WorkflowStateLifecycleTest.test_consumed_candidate_is_only_an_actionless_exact_replay \
  2>&1 | tail -35
```

Expected: the combined replay and focused demos 2–5 fail on absent
expiry/retry/replay/drain behavior; the post-resume/post-retry bootstrap and D13
discriminators also fail until the latest-launch projection and actionless exception
are complete. Focused demo 1 passes from Task 1. A failure caused only by fixture setup
must be corrected before implementation begins.

- [ ] **Step 3: Implement the complete transaction policy**

Inside `command_control`'s one `transact` callback, implement the spec's numbered order
literally:

1. Validate every observation and all ledger-dependent identities before mutation.
   Recognize D13's consumed-candidate replay only when the latest attempt is active,
   has no current-unavailable event, its path and first-launch instant exactly match
   the candidate and request `now`, and no transition/action for that issue can result.
   Reject wrong-instant/path, terminal/current-unavailable, and every other collision
   before mutation; require current facts for any new dispatch.
2. Leave durable terminal owner results authoritative; classify stale notifications
   without writing.
3. Expire every latest active/handed-off attempt whose fixed deadline is reached using
   the existing provisional expiry record.
4. Derive readiness from normalized tracker facts without terminating active work.
5. Compute occupied capacity from post-expiry latest attempts.
   The formula is `max(0, request["max_parallel"] - occupied)`, with `occupied` limited
   to current external owners exactly as D12 defines. Decrement once for every accepted
   dispatch action, including a resume.
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

Expected: `OK`. The single combined replay, five focused demos, latest-bootstrap
identity cases, D13 positive/negative discriminators, and all focused policy cases
pass; reopening the ledger shows each emitted dispatch launch already present.
Any duplicate action on advanced replay, noncanonical copied-state replay, lost
concurrent result, or leaked history key blocks the commit.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
git commit -m "feat(workflow-state): centralize dispatcher lifecycle policy

Applies expiry and resume-retry-spawn precedence atomically, persists actions
before emission, and proves the single-ledger six-stage replay. Per D4-D8/D10/D12-D13.

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
- Consumes from Tasks 1–3: the exact bounded bootstrap/control contracts and final
  four-command public CLI.
- Produces:
  - Dispatcher flow: resolve inputs/bindings; call `init-run`; inspect exactly its
    returned `recorded_worktree` requirements; verify an absent candidate for every
    requested issue without a requirement plus every absent/mismatched returned path;
    correlate notifications with returned owner/action identity; query tracker facts;
    normalize any owner notification; map configured limits to the exact request
    fields; call `control`; execute returned actions in order; replace at most one wait;
    render finalize summaries.
  - Owner dispatch envelope: immutable ledger root, run ID, issue/attempt, lifecycle
    owner token, exact worktree, optional handoff path, literal
    `from-issue <num> --auto`.
  - Contract/eval assertions for all five action kinds and absence of manual policy.

**Invariants:**
- The dispatcher does not read issue content, code, specs, plans, diffs, or review
  findings. Tracker and worktree adapters normalize external facts only (D3).
- Restart bootstrap consumes only `init-run.requirements`; raw ledger state is neither
  printed nor reconstructed. Returned issue/attempt/owner/path fields identify the
  exact paths to inspect and current host notification to correlate before the first
  action-ready request (D10).
- For every requested issue absent from bootstrap requirements, the adapter gathers a
  harmless verified absent candidate without deciding tracker readiness. It also
  gathers one for an absent/mismatched returned path; `control` ignores unused facts
  (D15).
- The skill does not count attempts/capacity, classify retryable results, choose
  resume/retry/spawn precedence, calculate deadline minima, infer drain, or call retired
  commands. It follows the returned action order (D1, D6).
- `spawn`, `resume`, and `retry` pass helper-issued owner/action identity unchanged;
  `resume` includes the durable handoff path when present. Host task IDs remain outside
  the lifecycle contract.
- Adapter state has only `current_wait_id` and `current_wait_handle`. For a new ID,
  publish it first, cancel the old handle, then arm/store the new handle; a wake carries
  its ID and is ignored unless it equals the current ID. The same ID never duplicates an
  observer; finalize clears the ID before cancellation (D11). A missing/already-exited
  old handle is idempotent and replacement arming continues. If arming fails, clear or
  mark both adapter fields uninstalled and fail loudly that no wake is installed (D14).
- On full dispatcher restart, the host reaps/cancels inherited detached observers
  before the restarted adapter rearms from a returned wait ID. Process-local adapter
  state cannot discover or adopt them (D14).
- Binding migration is exact: resolved `agentBudgetMinutes` populates request
  `attempt_budget_minutes`, and resolved `maxParallel` populates request `max_parallel`.
- A finalize envelope renders the final table and discussion items from the same
  response's bounded summaries; no second ledger reconstruction occurs (D4).
- `from-issue` retains `progress` and `finish`; its handoff text says the dispatcher
  resumes from a returned `resume` envelope and contains no owner-side `launch` call.
- Direct `from-issue` stays ledger-free. Explicit durable standalone use calls bounded
  `init-run`, then one-issue `control` with `max_parallel: 1`, adopts its first `spawn`
  envelope as its own lifecycle identity/worktree, and never spawns a duplicate (D10).
- Eval expected outputs move in the same commit as skill prose and grade normalized
  facts, `control`, typed action execution, compact output, and retired-policy absence.

- [ ] **Step 1: Replace the old skill tests with failing control-contract tests**

In `WorkflowSkillContractsTest`, replace launch/reconcile-specific assertions with:

```python
    def test_dispatcher_is_a_control_adapter_not_a_policy_owner(self):
        observe = self.section(
            self.orchestrate, "## 2. Bootstrap and observe", "## 3. Decide"
        )
        decide = self.section(
            self.orchestrate, "## 3. Decide", "## 4. Execute control actions"
        )
        execute = self.section(
            self.orchestrate, "## 4. Execute control actions", "## 5. Final report"
        )
        self.assert_ordered(observe, "workflow-state init-run", "requirements",
                            "action_id", "recorded_worktree", "normalized")
        self.assert_ordered(
            observe, "every requested issue without a bootstrap requirement",
            "verified absent candidate", "control ignores unused candidates",
        )
        self.assertNotIn("tracker-ready", observe)
        self.assertNotIn("classify tracker readiness", observe)
        self.assert_ordered(decide, "--request-file <absolute-json-path>",
                            "workflow-state control",
                            "only source of action order, kind, and lifecycle identity")
        for retired in ("workflow-state launch", "workflow-state reconcile"):
            self.assertNotIn(retired, self.orchestrate)
        for retired_policy_anchor in (
            "resume before fresh", "attempts 1 and 2", "permits a retry",
            "result_source", "earliest armed deadline", "deadline minima",
            "occupied slots", "count capacity", "run is drained",
            "fresh owner identity",
        ):
            self.assertNotIn(retired_policy_anchor, observe + decide + execute)

    def test_dispatcher_maps_resolved_limits_into_control_request(self):
        resolve = self.section(
            self.orchestrate, "## 1. Resolve issue set and bindings",
            "## 2. Bootstrap and observe",
        )
        self.assertIn(
            "resolved `agentBudgetMinutes` as request `attempt_budget_minutes`",
            resolve,
        )
        self.assertIn(
            "resolved `maxParallel` as request `max_parallel`",
            resolve,
        )
        self.assertNotIn("--budget-minutes <budget>", resolve)

    def test_dispatcher_executes_the_closed_control_action_set(self):
        action_section = self.section(
            self.orchestrate, "## 4. Execute control actions", "## 5. Final report"
        )
        for kind in ("spawn", "resume", "retry", "wait", "finalize"):
            self.assertIn(f"`{kind}`", action_section)
        self.assertIn("returned order", action_section)
        self.assertIn("owner token unchanged", action_section)
        self.assertIn("handoff_path", action_section)
        self.assertIn(
            "Any other kind is a contract error: stop without executing it and surface the unknown kind",
            action_section,
        )
        self.assertNotIn("host task ID as lifecycle identity", action_section)

    def test_dispatcher_uses_one_superseding_wait(self):
        action_section = self.section(
            self.orchestrate, "## 4. Execute control actions", "## 5. Final report"
        )
        self.assert_ordered(
            action_section,
            "current_wait_id", "publish the new wait ID", "cancel the old handle",
            "arm and store the new one-shot observer",
        )
        self.assertIn("same wait ID", action_section)
        self.assertIn("does not arm another observer", action_section)
        self.assertIn("wake carries its wait ID", action_section)
        self.assertIn("ignore it unless it equals `current_wait_id`", action_section)
        self.assert_ordered(action_section, "`finalize`", "clear `current_wait_id`",
                            "cancel the outstanding handle")
        self.assertIn("No polling or repeated short sleeps", action_section)

    def test_dispatcher_wait_failures_and_restart_cleanup_are_explicit(self):
        action_section = self.section(
            self.orchestrate, "## 4. Execute control actions", "## 5. Final report"
        )
        self.assert_ordered(
            action_section, "missing or already exited", "idempotent",
            "arm the replacement",
        )
        self.assert_ordered(
            action_section, "arming fails", "clear `current_wait_id`",
            "clear `current_wait_handle`", "no wake is installed", "fail loudly",
        )
        self.assert_ordered(
            self.orchestrate, "full dispatcher restart",
            "host reaps or cancels inherited detached wait observers",
            "before", "rearm",
        )
        self.assertIn("process-local", self.orchestrate)

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

    def test_from_issue_standalone_modes_use_live_lifecycle_interfaces(self):
        identity = self.section(
            self.from_issue, "## Lifecycle identity", "## The flow"
        )
        self.assertIn("Direct standalone invocation remains ledger-free", identity)
        self.assert_ordered(
            identity,
            "explicitly requests durable standalone orchestration",
            "workflow-state init-run", "bounded `requirements`",
            "max_parallel: 1", "workflow-state control", "first `spawn` envelope",
            "adopt", "do not spawn another owner",
        )
        self.assertIn("fail loudly", identity)

    def test_orchestrate_evals_grade_control_and_reject_retired_policy(self):
        expected = " ".join(
            case["expected_output"] for case in self.orchestrate_evals["evals"]
        )
        for anchor in (
            "workflow-state init-run", "action_id", "recorded_worktree",
            "workflow-state control",
            "normalized", "spawn", "resume", "retry", "wait", "finalize",
            "bounded summaries", "unknown action kind", "cancel the old wait",
            "stale wake ID", "already-exited wait", "no wake is installed",
            "reap inherited detached wait observers",
        ):
            self.assertIn(anchor, expected)
        for retired in ("workflow-state launch", "workflow-state reconcile"):
            self.assertNotIn(retired, expected)
        for retired_policy_anchor in (
            "resume before fresh", "attempts 1 and 2", "permits a retry",
            "result_source", "earliest armed deadline", "occupied slots",
            "run is drained",
        ):
            self.assertNotIn(retired_policy_anchor, expected)
```

Keep the existing background-agent placement, immutable ledger-root, lifecycle-envelope,
phase-gate, terminal-write, exact-worktree adoption, and bare-helper-path tests. Update
their retired command anchors. Replace the live
`test_orchestrate_resolves_the_attempt_budget_from_the_resolver` test with
`test_dispatcher_maps_resolved_limits_into_control_request` above: it migrates
`resolve-bindings.agentBudgetMinutes` to request `attempt_budget_minutes` and
`resolve-bindings.maxParallel` to request `max_parallel`, rather than merely checking
that both configured names appear. In
`test_owner_lifecycle_is_optional_for_direct_use_and_covers_all_stops`, replace the old
`direct standalone invocation remains compatible` assertion with
`Direct standalone invocation remains ledger-free`; the new standalone test above owns
the explicit durable branch.

- [ ] **Step 2: Run the contract tests and observe the red state**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-47-workflow-control-plane/home/common/agent-skills
python3 -m unittest tests.test_workflow_skill_contracts.WorkflowSkillContractsTest -q
```

Expected: FAIL because the skill/evals still call `launch`/`reconcile`, narrate policy,
lack bounded bootstrap, exact configured-limit mapping, policy-free candidate gathering,
and operational wait failure/restart behavior, and leave standalone/handoff branches on
the retired command.

- [ ] **Step 3: Rewrite the live skill and eval contracts**

Rewrite `orchestrate-issues/SKILL.md` around these sections, keeping its role boundary
and Claude-only dispatch metadata:

1. **Resolve issue set and bindings:** preserve explicit/list ordering and resolve
   `maxParallel`/`agentBudgetMinutes` through the existing binding resolver. State the
   live mapping exactly: place resolved `maxParallel` in request `max_parallel` and
   resolved `agentBudgetMinutes` in request `attempt_budget_minutes`.
2. **Bootstrap and observe:** invoke `init-run`; consume only its strict version-1
   `requirements`. One tracker read supplies state, open blockers, and decision
   blockers. Inspect exactly every returned `recorded_worktree`, then reserve an absent
   candidate for a returned absent/mismatch plus every requested issue with no
   bootstrap requirement. Do not ask the adapter to decide ready/blocked/fogged/closed;
   pass the harmless facts and state that `control` ignores unused candidates.
   Normalize the exact control request without retaining raw state or a second task
   ledger (D10, D15).
3. **Decide:** invoke `control` at start/resume and on each owner, tracker, or current
   wait-ID event. State verbatim that the response is the only source of action order,
   kind, and lifecycle identity; do not infer another action.
4. **Execute control actions:** in returned order, spawn background owners for
   `spawn`/`resume`/`retry` using unchanged lifecycle tokens and exact paths. For
   `wait`, keep only `current_wait_id/current_wait_handle`: same ID means no new
   observer; different ID publishes the replacement ID first, cancels the old handle,
   then arms/stores one new observer; a wake carries its ID and is ignored when stale.
   Missing/already-exited old handles are idempotent cancel outcomes and do not prevent
   replacement arming. If arming fails, clear/mark both fields uninstalled and fail
   loudly that no wake is installed. `finalize` clears the ID before canceling the
   handle. Any unknown kind stops before execution and surfaces the contract error
   (D11, D14, and The Bar's fail-loud rule).
5. **Final report:** render issue/state/PR/reason and grouped discussion items from the
   same finalize response's summaries.

In the restart/bootstrap notes, state the external-edge precondition verbatim in terms
of live behavior: on a full dispatcher restart, the host reaps or cancels inherited
detached wait observers before the restarted adapter rearms from the returned wait ID.
The two adapter wait fields are process-local and cannot adopt an inherited handle
(D14).

State explicitly that responses omit `attempts`, `launches`, `phase_inputs`, and older
results so no prose reader is invited to rebuild policy. Delete all attempt counting,
resume/retry classification, worktree choice, deadline calculation, and drain decision
text.

In `from-issue/SKILL.md`, update both affected live branches:

- Handoff continuation: after persisting the handoff, stop; the dispatcher later
  relaunches the same lifecycle owner/worktree/handoff from a returned `resume`
  envelope.
- Lifecycle identity: direct standalone use remains ledger-free. Only an explicit
  durable-standalone request runs bounded `init-run`, gathers normalized facts for this
  one issue, calls `control` with `max_parallel: 1`, and adopts the returned first
  `spawn` envelope as this owner's identity/exact worktree. It does not execute that
  action by spawning another owner. Missing/wrong/multiple dispatch actions fail loudly
  before Phase 1 (D10).

Do not change phase-budget semantics, terminal finish, or Phase-1 exact-path adoption.

Update both eval cases so their expected outputs grade the bounded bootstrap, response-
only order/identity, the closed action set with fail-loud unknown kind, and wait-ID
cancellation/stale-wake behavior, including missing/already-exited cancellation,
truthful arm failure, and full-restart host cleanup. Keep plan-only mode and existing
role-boundary failures. JSON must remain parseable and contain no retired command or
hand-assembled policy anchor.

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
bounded bootstrap, typed control actions, replaceable one-shot waiting, and
bounded final summaries. Per D1-D8/D10-D11/D14-D15.

Co-Authored-By: Codex <noreply@openai.com>"
```

---

## Acceptance coverage

| Spec requirement | Owning task |
| --- | --- |
| Strict bounded restart bootstrap without raw history and latest resume/retry identity | Tasks 1–2, 4 |
| Strict versioned nested request/response shapes, injected time, atomic rejection | Task 1 |
| Bounded summaries/deltas/actions and compact-output verification | Tasks 1–2 |
| Persist-before-emission and deterministic action IDs | Tasks 1–2 |
| Expiry, capacity formula, resume-before-retry-before-spawn, attempt cap, worktree reuse | Task 2 |
| Single-ledger six-stage scenario, concurrent finish, copied/advanced replay | Task 2 |
| Public `launch`/`reconcile` removal and CLI-only migrated tests | Task 3 |
| Adapter-only dispatcher, policy-free candidate gathering, exact binding-to-request mapping, five envelopes, unknown-kind failure, finalize rendering | Task 4 |
| Wait-ID replacement, cancellation-race stale wake, same-ID dedupe, idempotent dead-handle cancellation, truthful arm failure, restart-host cleanup | Task 4 |
| Actionless-only consumed-candidate replay and wrong-instant/path/terminal/unavailable negatives | Task 2 |
| Owner handoff, direct/durable standalone routes, deployed eval migration | Task 4 |
| Focused tests, whole workflow suite, and Nix distribution build | Task 4 |
