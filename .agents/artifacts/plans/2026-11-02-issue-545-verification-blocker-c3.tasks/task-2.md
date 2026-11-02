# Task 2: Control interface 4 resolves and resumes

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (constants, imports, `load_json_request`, two helpers, `validate_control_request`, `control_summary`, `_apply_one_issue_policy`, `command_control`, one keyword at `command_direct_owner`'s policy call)
- Modify: `home/common/agent-skills/scripts/workflow_delivery_wire.py` (`DeliveryProjection.control_summary`)
- Modify: `home/common/agent-skills/scripts/workflow_delivery.py` (`DeliveryRuntime.control_summary`)
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py` (`_verification`, `_requirements`, `_control_response`)
- Modify: `python/agent_tools/orchestrate_control.py`, `tests/test_orchestrate_control.py`, `tests/orchestrate_world.py`
- Modify: `home/common/agent-skills/skills/from-issue/acquire-durable.md`, `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `python/README.md`, `home/common/agent-skills/README.md`, `justfile`
- Create: `home/common/agent-skills/tests/test_verification_control.py`
- Modify (tests): `home/common/agent-skills/tests/test_verification_suspension.py`, `test_workflow_state.py`, `test_delivery_workflow.py`, `_delivery_model_fixtures.py`, `test_control_cutover.py`, `test_control_decisions.py` (all under `home/common/agent-skills/tests/`)

**Interfaces:**
- Consumes: Task 1's `verification_blocker.requirement`, `validate_observations`, `resolve` and `resume_permitted(..., blocker_resolved=...)`.
- Produces (Tasks 3–4 rely on these):
  - `workflow-state.py`: `load_json_request(path_value, label, *, strict=False)`; `verification_observations(value) -> list` and `resolve_verification(blockers, observations) -> tuple[frozenset[str], frozenset[str]]`, both raising `WorkflowError("invalid verification observation: <BlockerRefused line>")`; `_apply_one_issue_policy(..., verification_blockers: dict[str, Any])` (required keyword, the run's map after this call's resolution), whose locals `blocker` (the record a verification-suspended latest attempt points at, else `None`) and `blocker_resolved` exist after the reaper.
  - `delivery_model._wire`: `_verification(item)` and `_requirements(values, *, sorted_values, verification=False)`.
  - Harness (`test_verification_suspension.py`): `LOCK, NEXT = "a" * 40, "b" * 40`; `failure(failure_class="dependency", path="flake.lock", value=LOCK)`; `observed(blocker, value=LOCK)`; `VerificationHarness.recorded(*issues)`. `LifecycleHarness.control_request(..., verification=())`.
  - `test_verification_control.py`: `X`, `Y`, `X_ID`, `Y_ID`, `asked(blocker)`, `ControlHarness` (`parked`, `request`, `sweep`, `refused`, `blockers`, `summaries`, `awaited`, `dispatched`).
  - `_verification` refuses any `kind` but the literal `verification`.

**Invariants:**
- Control request and reply are interface 4 only; a version-3 request exits 2 before any lock (D3, D6).
- The control request file loads strictly; `build-delivery`'s input keeps its loader (D8).
- Resolution runs inside the transaction after the time check and before any issue is analysed; a non-empty resolved set marks the sweep changed; a reply the boundary rejects commits nothing (D6; #220 D5).
- A resolved verification attempt takes the ordinary suspension lane: capacity, `slot_withheld`, `refusal_gated`, fencing, the reaper and the stall bound are unchanged (D5).
- A summary of an attempt parked on an `open` record carries `requirement(record)` exactly once, in canonical-bytes order; a `resolved` record adds none (D6, D9).
- Older helpers are sent their own versions and checked by their own validators (D13, D16).
- No instruction ceiling moves (D11, D18).

- [ ] **Step 1: Write the failing tests**

`home/common/agent-skills/tests/test_workflow_state.py`, `LifecycleHarness.control_request`: add the keyword `verification=()` after `host_route="claude-code"`, set `"interface_version": 4`, and end the returned object with `"verification": list(verification),`. Its `control_validated` docstring says `interface-4 bytes`.

`home/common/agent-skills/tests/test_verification_suspension.py`: replace `LOCK = "a" * 40` with `LOCK, NEXT = "a" * 40, "b" * 40`. `failure` gains the keyword `value=LOCK`, which becomes the object id of its one fact (docstring: `..., its one selected path holding the object `value`.`). Add after `failure`:

```python
def observed(blocker, value=LOCK):
    """The `verification-observation` that `verification-observe observe` prints for the
    blocker of the failure `blocker` when its selected path holds `value` (issue 545)."""
    facts = copy.deepcopy(blocker["facts"])
    facts[0]["value"]["objects"][0]["object"] = value
    return {"kind": "verification-observation", "schema_version": 1,
            "blocker_id": vb.blocker_id(blocker),
            "repository": copy.deepcopy(blocker["repository"]), "facts": facts}
```

`VerificationHarness.recorded(self, issue)` becomes `recorded(self, *issues)`, returning one `matching_issue_branch` worktree fact per issue (existing one-issue callers are unchanged). In `HelperGenerationTest.assert_refused_unchanged`, build the control request into a variable first and, for `generation == "base"`, set its `interface_version` to 3 and delete `verification` before writing it, with the comment `# The base helper reads only its own request interfaces (issue 545 D13).` (D13).

Create `home/common/agent-skills/tests/test_verification_control.py`:

```python
"""Verification blockers resolved by `workflow-state control` (issue 545), through the CLI
from source.

Run: just agent-workflow-tests
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools import verification_blocker as vb

from .test_verification_suspension import NEXT, T, VerificationHarness, failure, observed
from .test_workflow_state import BUDGET_POLICY, SCRIPT

X, Y = failure(), failure(path="Cargo.lock")
X_ID, Y_ID = vb.blocker_id(X), vb.blocker_id(Y)
FINALIZE = [{"id": "finalize", "kind": "finalize"}]


def asked(blocker):
    """The summary requirement of an attempt parked on `blocker`'s open record."""
    return {"kind": "verification", "blocker_id": vb.blocker_id(blocker),
            "sources": [{"name": "flake-lock",
                         "paths": blocker["facts"][0]["source"]["paths"]}]}


class ControlHarness(VerificationHarness):
    def parked(self, *pairs):
        """Spawn each issue of `pairs`, then park it on its failure, a minute apart from T(5)."""
        self.spawn_all(*(issue for issue, _ in pairs))
        for minute, (issue, blocker) in enumerate(pairs, start=5):
            self.park(issue, blocker, now=T(minute))

    def request(self, minute, *observations, issues=(61, 62), **fields):
        return self.control_request(now=T(minute), issues=list(issues),
                                    tracker=[self.tracker_fact(issue) for issue in issues],
                                    worktrees=self.recorded(*issues),
                                    verification=list(observations), **fields)

    def sweep(self, minute, *observations, issues=(61, 62), **fields):
        return self.control_validated(
            request=self.request(minute, *observations, issues=issues, **fields))

    def refused(self, raw):
        """`control` over request bytes `raw`, which it must refuse."""
        path = self.root / "refused-request.json"
        path.write_bytes(raw)
        return self.run_cli("control", "--repo-root", self.root, "--run-id", self.run_id,
                            "--request-file", path, ok=False)

    def blockers(self):
        return self.read_state()["verification_blockers"]

    @staticmethod
    def summaries(reply):
        return {item["issue"]: item for item in reply["summaries"]}

    @staticmethod
    def awaited(summary):
        """The verification requirements among a summary's requirements."""
        return [item for item in summary["requirements"] if item["kind"] == "verification"]

    @staticmethod
    def dispatched(reply):
        return [(action["kind"], action["id"]) for action in reply["actions"]
                if action["kind"] in ("spawn", "resume", "retry")]


class ReplayTest(ControlHarness, unittest.TestCase):
    def test_no_or_an_equal_observation_resumes_nothing_and_writes_nothing(self):
        self.parked((61, X), (62, X))
        attempts = {issue: self.attempt(issue) for issue in (61, 62)}
        held = self.blockers()
        first = self.sweep(7)
        self.assertEqual(first["actions"], FINALIZE)
        self.assertEqual(self.blockers(), held)
        before = self.tree_snapshot()
        for directed in (False, True):
            with self.subTest(human_directed=directed):
                reply = self.sweep(8, observed(X), human_directed=directed)
                self.assertEqual(reply["actions"], FINALIZE)
                for issue in (61, 62):
                    summary = self.summaries(reply)[issue]
                    self.assertEqual(
                        (summary["state"], summary["blocked_on"], self.awaited(summary)),
                        ("suspended", "verification", [asked(X)]))
                    self.assertEqual(self.attempt(issue), attempts[issue])
                self.assertEqual(self.tree_snapshot(), before)


class ChangeTest(ControlHarness, unittest.TestCase):
    def test_a_selected_change_resumes_only_the_attempts_it_releases(self):
        self.parked((61, X), (62, Y))
        reply = self.sweep(7, observed(X), observed(Y, NEXT))
        self.assertEqual(self.dispatched(reply), [("resume", "62:1:2")])
        summaries = self.summaries(reply)
        self.assertEqual((summaries[61]["state"], self.awaited(summaries[61])),
                         ("suspended", [asked(X)]))
        self.assertEqual((summaries[62]["state"], self.awaited(summaries[62])),
                         ("active", []))
        blockers = self.blockers()
        self.assertEqual((blockers[X_ID]["state"], blockers[X_ID]["resolution"]),
                         ("open", None))
        self.assertEqual((blockers[Y_ID]["state"], blockers[Y_ID]["resolution"]),
                         ("resolved", {"facts": observed(Y, NEXT)["facts"]}))
        self.assertEqual(blockers[Y_ID]["attempts"], [{"issue": 62, "attempt": 1}])

    def retained(self, *issues):
        """Give each attempt the work a resume must keep: a handoff document, phase 2 after
        the handoff's relaunch, and a progress marker on a real worktree."""
        for issue in issues:
            self.init_worktree(self.worktree(issue), branch=f"issue-{issue}")
            self.progress(issue=issue, phase=2, now=T(1), turn_count=118,
                          handoff_path=self.write_handoff(issue))
        self.assertEqual(self.dispatched(self.sweep(2, issues=issues)),
                         [("resume", f"{issue}:1:2") for issue in issues])
        for issue in issues:
            self.assertEqual(self.mark_progress(action_id=f"{issue}:1:2", now=T(3))["outcome"],
                             "baseline")

    def test_capacity_resumes_in_request_order_and_keeps_the_retained_work(self):
        self.spawn_all(61, 62)
        self.retained(61, 62)
        for minute, issue in ((4, 61), (5, 62)):
            self.park(issue, X, now=T(minute))
        before = {issue: self.attempt(issue) for issue in (61, 62)}
        self.assertEqual((before[62]["phase"], before[62]["suspend_phase"]), (2, 2))
        self.assertTrue(before[62]["handoff_path"] and before[62]["progress_marker"])
        reply = self.sweep(7, observed(X, NEXT), issues=(62, 61), max_parallel=1)
        self.assertEqual(self.dispatched(reply), [("resume", "62:1:3")])
        (action,) = [item for item in reply["actions"] if item["kind"] == "resume"]
        self.assertEqual((action["handoff_path"], action["deadline_at"]),
                         (before[62]["handoff_path"], "2026-08-13T20:37:00Z"))
        self.assertEqual(self.awaited(self.summaries(reply)[61]), [])
        self.assertEqual(self.blockers()[X_ID]["state"], "resolved")
        resumed = self.attempt(62)
        for field in ("attempt", "owner", "worktree", "handoff_path", "phase",
                      "progress_marker", "suspend_phase", "stalled_resumes"):
            with self.subTest(field=field):
                self.assertEqual(resumed[field], before[62][field])
        self.assertEqual(
            (resumed["state"], resumed["blocked_on"], resumed["verification_blocker"],
             resumed["launch_kind"], len(resumed["launches"]), resumed["deadline_at"]),
            ("active", None, None, "resume", 3, "2026-08-13T20:37:00Z"))
        self.assertEqual(self.attempt(61), before[61])
        self.assertEqual(self.check_launch(action_id="62:1:2")["reason"], "superseded_launch")
        self.assertEqual(self.check_launch(action_id="62:1:3")["reason"], "current")
        later = self.sweep(8, issues=(62, 61), max_parallel=2)
        self.assertEqual(self.dispatched(later), [("resume", "61:1:3")])
        self.assertEqual(self.blockers()[X_ID]["attempts"],
                         [{"issue": 61, "attempt": 1}, {"issue": 62, "attempt": 1}])

    def test_a_resumed_attempt_expires_on_its_fresh_window(self):
        self.parked((61, X))
        self.sweep(7, observed(X, NEXT), issues=(61,))
        reaped = self.sweep(37, issues=(61,))
        self.assertEqual([(delta["kind"], delta["state"]) for delta in reaped["deltas"]],
                         [("expired", "active"), ("resumed", "active")])
        self.assertEqual(self.dispatched(reaped), [("resume", "61:1:3")])
        self.assertEqual(self.blockers()[X_ID]["state"], "resolved")

    def test_the_stall_bound_still_stops_a_fourth_park(self):
        self.spawn_all(61)
        values = ["a" * 40, "b" * 40, "c" * 40, "d" * 40]
        for cycle in range(3):
            blocker = failure(value=values[cycle])
            self.park(61, blocker, now=T(2 * cycle + 1))
            reply = self.sweep(2 * cycle + 2, observed(blocker, values[cycle + 1]), issues=(61,))
            self.assertEqual(self.dispatched(reply), [("resume", f"61:1:{cycle + 2}")])
        stopped = self.park(61, failure(value=values[3]), now=T(7))
        self.assertEqual((stopped["kind"], stopped["source"], stopped["reason"]),
                         ("terminal", "lifecycle", "stopped"))
        attempt = self.attempt(61)
        self.assertEqual((attempt["state"], attempt["result_source"],
                          attempt["verification_blocker"]), ("stopped", "stalled", None))
        self.assertEqual(sorted(self.blockers()),
                         sorted(vb.blocker_id(failure(value=value)) for value in values[:3]))
        self.assertEqual({record["state"] for record in self.blockers().values()},
                         {"resolved"})


class RefusalTest(ControlHarness, unittest.TestCase):
    def test_an_observation_that_answers_no_open_blocker_exactly_is_refused(self):
        self.parked((61, X), (62, X), (63, Y))
        self.sweep(8, observed(Y, NEXT), issues=(61, 62, 63))
        before = self.tree_snapshot()
        extra = observed(X)
        extra["facts"].append({"name": "go-sum", "source": {"paths": ["go.sum"]},
                               "value": {"objects": [{"path": "go.sum", "mode": "100644",
                                                      "object": NEXT}]}})
        moved = observed(failure(path="other.lock"))
        moved["blocker_id"] = X_ID
        other = observed(X)
        other["repository"]["integration_branch"] = "release"
        malformed = {**observed(X), "schema_version": 2}
        secret = observed(X)
        secret["facts"][0]["source"]["paths"] = [".env"]
        secret["facts"][0]["value"]["objects"][0]["path"] = ".env"
        unknown = "verification[0].blocker_id: names no open blocker of this run"
        sources = "verification[0].facts: must carry the blocker's names and sources in order"
        cases = {
            "missing fact": ([{**observed(X), "facts": []}],
                             "verification[0]: facts: must be a list of 1 to 4 items"),
            "extra fact": ([extra], sources),
            "substituted source": ([moved], sources),
            "other repository": ([other],
                                 "verification[0].repository: must equal the blocker's "
                                 "repository"),
            "repeated id": ([observed(X), observed(X, NEXT)],
                            "verification[1].blocker_id: repeats an earlier observation"),
            "unknown id": ([observed(failure("environment"))], unknown),
            "resolved id": ([observed(Y, NEXT)], unknown),
            "malformed": ([malformed], "verification[0]: observation.schema_version: must be 1"),
            "secret-shaped": ([secret],
                              "verification[0]: facts[0].source.paths[0]: secret-shaped"),
        }
        for label, (observations, line) in cases.items():
            with self.subTest(case=label):
                done = self.refused(json.dumps(
                    self.request(9, *observations, issues=(61, 62, 63))).encode())
                self.assertEqual((done.returncode, done.stdout, done.stderr),
                                 (2, "", f"workflow-state: invalid verification observation: "
                                         f"{line}\n"))
                self.assertEqual(self.tree_snapshot(), before)
        text = json.dumps(self.request(9, observed(X, NEXT), issues=(61, 62, 63)))
        loads = {
            "interface 3": (json.dumps({**json.loads(text), "interface_version": 3}),
                            "unsupported control interface version"),
            "duplicate key": (text[:-1] + ', "verification": []}',
                              "invalid control request JSON: duplicate JSON key "
                              "'verification'"),
            "non-finite literal": (text.replace('"max_parallel": 2', '"max_parallel": NaN'),
                                   "invalid control request JSON: JSON constant NaN is not "
                                   "allowed"),
        }
        for label, (raw, line) in loads.items():
            with self.subTest(case=label):
                done = self.refused(raw.encode())
                self.assertEqual((done.returncode, done.stdout, done.stderr),
                                 (2, "", f"workflow-state: {line}\n"))
                self.assertEqual(self.tree_snapshot(), before)


class PersistenceTest(ControlHarness, unittest.TestCase):
    def test_a_rejected_reply_commits_no_resolution(self):
        """Issue 545 D6, #220 D5: the reply is validated before the sweep's write commits."""
        self.parked((61, X), (62, X))
        tree = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, tree, True)
        shutil.copytree(SCRIPT.parent, tree / "agent-skills/scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        policy = json.loads(BUDGET_POLICY.read_text(encoding="utf-8"))
        policy["workflow_responses"]["wire_max_bytes"] = 64
        (tree / "agent-skills/artifact-budget-policy.json").write_text(
            json.dumps(policy), encoding="utf-8")
        path = self.root / "resolving-request.json"
        path.write_text(json.dumps(self.request(7, observed(X, NEXT))), encoding="utf-8")
        before = self.tree_snapshot()
        done = subprocess.run(
            [sys.executable, str(tree / "agent-skills/scripts/workflow-state.py"), "control",
             "--repo-root", str(self.root), "--run-id", self.run_id, "--request-file",
             str(path)], capture_output=True, text=True, check=False, env=self.cli_env)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (
            2, "", "workflow-state: artifact-budget validate-report rejected the "
                   "workflow-response boundary\n"))
        self.assertEqual(self.tree_snapshot(), before)
        self.assertEqual(self.blockers()[X_ID]["state"], "open")


class WireTest(ControlHarness, unittest.TestCase):
    """Issue 545 D9, by behaviour: the validator admits the requirement only where control
    puts it."""

    def validate(self, value):
        return self.delivery_model.validate_delivery_object(
            value, expected_kind="workflow-response", notes_max_characters=4096)

    def test_the_parked_summary_is_admitted_and_nothing_near_it(self):
        self.parked((61, X), (62, X))
        reply = self.sweep(7)
        self.assertEqual(self.validate(json.loads(json.dumps(reply))), reply)
        record = self.blockers()[X_ID]
        self.assertEqual(vb.requirement(record), asked(X))
        model = self.delivery_model

        def mutated(change):
            value = json.loads(json.dumps(reply))
            change(value, value["summaries"][0])
            return value

        def added_member(value, summary):
            summary["requirements"][0]["note"] = "x"

        def removed_member(value, summary):
            del summary["requirements"][0]["sources"]

        def twice(value, summary):
            summary["requirements"].append({**asked(X), "blocker_id": "sha256:" + "f" * 64})

        def not_parked(value, summary):
            summary["state"], summary["blocked_on"] = "active", None

        def other_cause(value, summary):
            summary["blocked_on"] = "transport"

        def interface_three(value, summary):
            value["interface_version"] = 3

        for change in (added_member, removed_member, twice, not_parked, other_cause,
                       interface_three):
            with self.subTest(case=change.__name__), \
                    self.assertRaises(model.DeliveryModelError):
                self.validate(mutated(change))
        owner = self.delivery_fixtures.workflow_responses(model)["owner"]
        owner = {**json.loads(json.dumps(owner)), "requirements": [asked(X)]}
        with self.assertRaises(model.DeliveryModelError):
            self.validate(owner)

    def test_no_action_may_name_an_issue_its_summary_parks(self):
        """The reply of a real resume validates while its summary only looks parked, so the
        refusal of the same reply with the requirement is the parked-issue guard's."""
        self.parked((61, X), (62, Y))
        reply = self.sweep(7, observed(Y, NEXT))
        self.assertEqual(self.dispatched(reply), [("resume", "62:1:2")])
        model = self.delivery_model

        def parked(requirement):
            value = json.loads(json.dumps(reply))
            summary = self.summaries(value)[62]
            summary["state"], summary["blocked_on"] = "suspended", "verification"
            if requirement:
                summary["requirements"] = sorted(summary["requirements"] + [asked(Y)],
                                                 key=model.canonical_bytes)
            return value

        for value in (reply, parked(False)):
            self.assertEqual(self.validate(value), value)
        with self.assertRaises(model.DeliveryModelError):
            self.validate(parked(True))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_verification_control.py 2>&1 | tail -3'`
Expected: `Ran 9 tests` and `FAILED (failures=9)`, each `command failed with 2: workflow-state: invalid control request fields` (the interface-3 helper refuses the new member at the first spawn).

- [ ] **Step 3: Implement control interface 4**

`workflow-state.py`:
- `CONTROL_INTERFACE_VERSION = 4`; `CONTROL_REQUEST_FIELDS` gains `"verification"`; import `reject_duplicate_keys, reject_nonfinite_literal` from `agent_tools.canonical` after the `attempt_identity` import.
- `load_json_request(path_value, label, *, strict=False)`: with `strict` it passes `object_pairs_hook=reject_duplicate_keys` and `parse_constant=reject_nonfinite_literal` to `json.loads`, and it catches `ValueError` (so a hook's refusal and a decode error both become `invalid <label> JSON: <reason>`). Docstring: `Read and decode one JSON request file. ``strict`` also refuses a repeated key and a non-finite literal, through the `agent_tools.canonical` hooks (issue 545 D8).` `load_control_request` passes `strict=True`; the builder input call stays non-strict.
- After `load_control_request` add `verification_observations(value)` (docstring `A request's `verification` list, checked before any lock (issue 545 D4).`) and `resolve_verification(blockers, observations)` (docstring `Resolve the records `observations` answer in `blockers`; returns the resolved and the equal ids. A refusal leaves `blockers` unchanged (issue 545 D2, D4).`), each wrapping its `verification_blocker` function and re-raising `BlockerRefused` as `WorkflowError(f"invalid verification observation: {error}")`.
- `validate_control_request`: right after the interface-version check, `verification_observations(request["verification"])`.
- `control_summary`: a required keyword `verification_blockers: dict[str, Any]` after `unresumable`, passed through to the runtime.
- `_apply_one_issue_policy`: a required keyword `verification_blockers: dict[str, Any]` after `reply_parked`. Replace the docstring sentences from `Nothing resumes an attempt suspended on` to `which changes nothing.` with: an attempt suspended on an observation-gated cause (`verification`) resumes exactly when its blocker in ``verification_blockers``, the run's map after this call's resolution, is ``resolved``, and then through the ordinary suspension lane below, directed or not (issue 545 D5); while the blocker is ``open``, without ``reply_parked`` its verdict is ``terminal``, as control gets it; with it, as the direct owner asks, it passes the tracker halt and the forge requirement and then returns ``parked``, which changes nothing (issue 544 D6, D7). Replace the `suspended`/`parked` definitions with:

```python
    blocker = (
        verification_blockers[latest["verification_blocker"]]
        if latest is not None and latest["state"] == "suspended"
        and latest["blocked_on"] in OBSERVATION_GATED_BLOCKED_ON else None
    )
    blocker_resolved = blocker is not None and blocker["state"] == "resolved"
    suspended = bool(
        latest is not None
        and latest["state"] == "suspended"
        and resume_permitted(latest["blocked_on"], human_directed=human_directed,
                             blocker_resolved=blocker_resolved)
    )
    parked = bool(reply_parked and blocker is not None and not blocker_resolved)
```

- `command_control`, inside `control(state)` right after the backward-time refusal: `resolved, _ = resolve_verification(state["verification_blockers"], request["verification"])`, under the comment `# The observations resolve the run's open blockers before any issue is analysed; a resolution commits with this sweep's write whether or not its attempt resumes in it (issue 545 D6).` Both `_apply_one_issue_policy` calls pass `verification_blockers=state["verification_blockers"]`; `changed` gains `or bool(resolved)`; each `control_summary(...)` passes `verification_blockers=state["verification_blockers"]`.
- `command_direct_owner`'s policy call passes `verification_blockers=({} if state is None else state["verification_blockers"])` (Task 4 replaces it).

`workflow_delivery_wire.py`: import `from agent_tools import verification_blocker`; `control_summary` gains the required keyword `verification_blockers`; after the `unresumable` fact, when `latest_kind == "implementation"`, `latest["state"] == "suspended"` and `latest["blocked_on"] == "verification"`, take `record = verification_blockers[latest["verification_blocker"]]` and, when its `state` is `open`, append `verification_blocker.requirement(record)`, with the comment `# An attempt parked on an open blocker asks for its observation; one whose blocker is resolved waits only to resume (issue 545 D6).`

`workflow_delivery.py`, `DeliveryRuntime.control_summary`: sort when `unresumable` is set **or** any requirement's `kind` is `verification`; the comment says a worktree fact or a verification requirement the projection appends joins the requirements in the validator's canonical-bytes order (#194 D13, issue 545 D6).

`delivery_model/_wire.py` (D9; it still imports no `agent_tools`):
- New `_verification(item)` before `_requirements`, docstring `The closed `verification` requirement (issue 545 D9): this module's own copy of the shape `agent_tools.verification_blocker` renders, without its path rules.`: `_object(item, _members("kind blocker_id sources"))`, `_digest(item["blocker_id"], ...)`, `item["kind"] != "verification"` is `_reject()` (the bootstrap calls it directly, so it checks the literal itself), `sources` a list of 1 to 4 items, each `_object(source, _members("name paths"))` with a non-empty string `name` and `paths` a list of 1 to 8 non-empty strings.
- `_requirements(values, *, sorted_values, verification=False)` (docstring `A requirement list; only a caller passing `verification` admits that kind (issue 545 D9).`): inside the loop, `if verification and item["kind"] == "verification": _verification(item); continue` before the existing kind branches.
- `_control_response`: interface `4`; a `parked = set()` beside `unresumable`; summaries call `_requirements(..., sorted_values=True, verification=True)`; when a summary holds verification requirements, more than one, a `state` other than `suspended` or a `blocked_on` other than `verification` is `_reject()`, else the issue joins `parked`; the null-digest remainder drops kinds `{"worktree_fact", "verification"}`; no action may name an issue in `missing_contracts | unresumable | parked`.

`orchestrate_control.py`: `CONTROL_VERSION = 4`; `control_request` ends with `"verification": []`; its docstring begins `The interface-4 `control` request` and ends `It reports no verification observation (`verification` is empty; issue 545 D11).`

Fixtures and base generations (D13, D16):
- `tests/test_orchestrate_control.py`: the two `interface_version` 3 pins (response and request) and both canned control replies become 4; the expected request ends with `"verification": []`. `tests/orchestrate_world.py`: its control request is interface 4 with `"verification": []`.
- `test_delivery_workflow.py`: the three control requests (`DeliveryAdmissionTest.control_request`, the inline request of `DeliveryAdmissionTest.test_dispatching_control_response_passes_raw_workflow_response_validation`, `BuilderHarness.control_request`) are interface 4 and end with `"verification": []`; `test_interface_two_maps_and_singular_inputs_are_closed` expects control version 4. `_delivery_model_fixtures.py`: the `control` response is interface 4. `test_workflow_state.py`: the zero-id run's control reply is version 4.
- `test_control_cutover.py`: import `ARTIFACT_BUDGET, POLICY` beside `WORKFLOW`; after `ROLES` add `BASE_REQUESTS = {"control": 3}` with the comment `# The request interface each command of the base helper reads; it refuses this checkout's (issue 545 D13).`; in `Cutover.cli`, for the base generation, when `args[0] in BASE_REQUESTS` and `stdin` is given, decode it, set `interface_version` to that entry, delete `verification` and re-encode. Add `Cutover.boundary(name, raw)`: the head generation calls `super().boundary`; the base runs `self.base / ARTIFACT_BUDGET.relative_to(REPO)` `validate-report --boundary <name> --input - --policy <self.base / POLICY.relative_to(REPO)>` on the same input (docstring: a base reply carries the base helper's own interfaces, so its own extracted validator checks it (issue 545 D13)). `test_control_decisions.py`, `DecisionTest.twin`: decode each validated reply (`json.loads` of the `RUN`-substituted bytes); before comparing, pop each control reply's (no `kind`) `interface_version`, asserting 3 for `base` and 4 for `head`, under the comment `# A control reply carries its generation's interface, 3 or 4, and nothing else differs (issue 545 D16).`; return the head replies.

Docs (D11, D18):
- `acquire-durable.md`: `interface-3 control request` becomes `interface-4 control request`; nothing else.
- `orchestrate-issues/SKILL.md`: `from the bounded summaries in the same interface_version 3 control response.` becomes `from the bounded summaries in the same control response.` (20 bytes freed under the corpus ceiling, D18).
- `python/README.md`, `## orchestrate-control`: `this run's interface-3 control response` becomes `interface-4`; the sentence `every other per-issue member is empty.` becomes `every other per-issue member is empty, and `verification` is `[]` (issue 545).`
- `home/common/agent-skills/README.md`, `### Verification blockers`: in the first paragraph, `a control sweep, directed or not, reports the attempt `suspended` and dispatches nothing for it, and `direct-owner`` becomes `only a resolution of its record releases the attempt (next paragraph), and a human-directed re-entry never does. `direct-owner``, and the closing `Known limitation: … that is issue 545.` sentence is removed. Add a second paragraph:

```text
A control sweep resolves records (issue 545, [design](../../../.agents/artifacts/specs/2026-11-02-issue-545-verification-blocker-c3-design.md)). The control request, now interface 4 (and its reply with it), carries `verification`: the `verification-observation`s that `verification-observe observe` printed, `[]` when there is none. The request file is read as strict JSON, a repeated key or a non-finite literal exiting 2 as `invalid control request JSON`. Before any lock every element must be a valid observation and no `blocker_id` may repeat; inside the sweep's transaction, before any issue is analysed, each must name an `open` record of the run, carry its `repository` and exactly its fact names and sources in order. Any other observation exits 2 with `workflow-state: invalid verification observation: <field>: <reason>` and writes nothing. An observation equal to the record in every value changes nothing. One that changes a value (an object or a mode) marks the record `resolved` with the observed facts as its `resolution`, and the sweep commits that whether or not the attempt resumes in it. An attempt parked on a `resolved` record takes the ordinary suspension lane, capacity, the recorded-worktree observation and the contract included, in this sweep or a later one that sends no observation: it keeps its issue, attempt, owner, worktree, handoff, phase and stall count, and resumes with the next launch and a fresh window, and the record keeps it in `attempts`. The summary of an attempt parked on an `open` record carries that record's `verification` requirement (`kind`, `blocker_id` and `sources`, each source a fact's `name` and `paths`) among its `requirements`, and control dispatches nothing for it. Known limitation: `orchestrate-control` sends `verification: []`, so no caller gathers an observation yet; that is issue 546.
```

- `justfile`, `agent-workflow-tests`: list `home/common/agent-skills/tests/test_verification_control.py \` right after `test_verification_suspension.py`.

- [ ] **Step 4: Verify**

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_verification_control.py home/common/agent-skills/tests/test_verification_suspension.py 2>&1 | tail -3'`
Expected: `OK`.
Run (timeout 3000 s): `PYTHONPATH="$PWD/python" python3 -m agent_tools.suite_runner --jobs 6 home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_delivery_model.py home/common/agent-skills/tests/test_control_cutover.py home/common/agent-skills/tests/test_control_decisions.py home/common/agent-skills/tests/test_delivery_sealing.py home/common/agent-skills/tests/test_delivered_control.py home/common/agent-skills/tests/test_artifact_budget.py home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py tests/test_orchestrate_control.py 2>&1 | tail -2`
Expected: `suite-runner: summary members=11 passed=11 failed=0`.
Run: `PYTHONPATH="$PWD/python" python3 -m agent_tools.instruction_load check --base e692c9685c3e4b08f55c327c5f2b8c699fc95bc4; if grep -n 'interface-3 control\|interface_version 3 control' home/common/agent-skills/skills/from-issue/acquire-durable.md home/common/claude-code/skills/orchestrate-issues/SKILL.md python/README.md; then exit 1; fi`
Expected: `check: pass` and no line printed.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/scripts/workflow_delivery_wire.py home/common/agent-skills/scripts/workflow_delivery.py home/common/agent-skills/scripts/delivery_model/_wire.py python/agent_tools/orchestrate_control.py tests/test_orchestrate_control.py tests/orchestrate_world.py home/common/agent-skills/skills/from-issue/acquire-durable.md home/common/claude-code/skills/orchestrate-issues/SKILL.md python/README.md home/common/agent-skills/README.md justfile home/common/agent-skills/tests/test_verification_control.py home/common/agent-skills/tests/test_verification_suspension.py home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/_delivery_model_fixtures.py home/common/agent-skills/tests/test_control_cutover.py home/common/agent-skills/tests/test_control_decisions.py
launch-commit … -- -m "feat(workflow-state): control interface 4 resolves blockers" -m "Issue 545." -m "<session trailers>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"1ca7e2f24eba304078881ad684951ff78fce66c2","head":"b9eaf36bc4c547196a557f3b75c9e872cd54b40b"}],"commit_subject_bytes":[64,64,64],"id":2,"records":[{"bounds":[{"added_lines":80,"boundary":"all","deleted_lines":25,"record_bytes":24576,"support":{"covers":["r2a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2a","last_task":4,"owner":2,"path":"home/common/agent-skills/scripts/workflow-state.py"},{"bounds":[{"added_lines":14,"boundary":"all","deleted_lines":3,"record_bytes":5632,"support":{"covers":["r2b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2b","last_task":3,"owner":2,"path":"home/common/agent-skills/scripts/workflow_delivery_wire.py"},{"bounds":[{"added_lines":8,"boundary":"all","deleted_lines":5,"record_bytes":2560,"support":{"covers":["r2c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2c","last_task":2,"owner":2,"path":"home/common/agent-skills/scripts/workflow_delivery.py"},{"bounds":[{"added_lines":30,"boundary":"all","deleted_lines":9,"record_bytes":11264,"support":{"covers":["r2d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2d","last_task":4,"owner":2,"path":"home/common/agent-skills/scripts/delivery_model/_wire.py"},{"bounds":[{"added_lines":8,"boundary":"all","deleted_lines":6,"record_bytes":5120,"support":{"covers":["r2e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2e","last_task":2,"owner":2,"path":"python/agent_tools/orchestrate_control.py"},{"bounds":[{"added_lines":8,"boundary":"all","deleted_lines":7,"record_bytes":6656,"support":{"covers":["r2f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2f","last_task":2,"owner":2,"path":"tests/test_orchestrate_control.py"},{"bounds":[{"added_lines":5,"boundary":"all","deleted_lines":4,"record_bytes":3584,"support":{"covers":["r2g"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2g","last_task":2,"owner":2,"path":"tests/orchestrate_world.py"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":1,"record_bytes":3072,"support":{"covers":["r2h"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2h","last_task":2,"owner":2,"path":"home/common/agent-skills/skills/from-issue/acquire-durable.md"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":1,"record_bytes":2560,"support":{"covers":["r2i"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2i","last_task":2,"owner":2,"path":"home/common/claude-code/skills/orchestrate-issues/SKILL.md"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":4,"record_bytes":32768,"support":{"covers":["r1e","r2j"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2j","last_task":2,"owner":2,"path":"python/README.md"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":2,"record_bytes":16896,"support":{"covers":["r2k"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2k","last_task":4,"owner":2,"path":"home/common/agent-skills/README.md"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":0,"record_bytes":2048,"support":{"covers":["r2l"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2l","last_task":4,"owner":2,"path":"justfile"},{"bounds":[{"added_lines":400,"boundary":"all","deleted_lines":0,"record_bytes":22528,"support":{"covers":["r2m"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r2m","last_task":3,"owner":2,"path":"home/common/agent-skills/tests/test_verification_control.py"},{"bounds":[{"added_lines":32,"boundary":"all","deleted_lines":12,"record_bytes":7680,"support":{"covers":["r2n"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2n","last_task":4,"owner":2,"path":"home/common/agent-skills/tests/test_verification_suspension.py"},{"bounds":[{"added_lines":7,"boundary":"all","deleted_lines":6,"record_bytes":6656,"support":{"covers":["r2o"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2o","last_task":4,"owner":2,"path":"home/common/agent-skills/tests/test_workflow_state.py"},{"bounds":[{"added_lines":9,"boundary":"all","deleted_lines":9,"record_bytes":10240,"support":{"covers":["r2p"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2p","last_task":4,"owner":2,"path":"home/common/agent-skills/tests/test_delivery_workflow.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":2560,"support":{"covers":["r2q"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2q","last_task":3,"owner":2,"path":"home/common/agent-skills/tests/_delivery_model_fixtures.py"},{"bounds":[{"added_lines":28,"boundary":"all","deleted_lines":3,"record_bytes":5120,"support":{"covers":["r2r"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2r","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_control_cutover.py"},{"bounds":[{"added_lines":10,"boundary":"all","deleted_lines":4,"record_bytes":3072,"support":{"covers":["r2s"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2s","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_control_decisions.py"}]}}
```
