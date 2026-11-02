# Task 4: Worker and progress replies pass the boundary, pinned by the skill-named reply contract

Spec § Decisions (Workflow-response validator, worker and progress replies; Which replies are workflow responses); § Test seams (Skill pipes match the validator; The validator refuses bad shapes); per D5, D6, D8 and D11. The AC3 contract is this task's failing test: at its starting commit it is red for exactly `register-worker`, `release-worker` and `mark-progress`. The validator branches turn it green.

**Files:**
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py` (new id patterns and three reply checks; dispatch lines in `_workflow_response` right after the check-launch branch)
- Modify: `home/common/agent-skills/tests/test_attempt_custody.py` (`DeliveredCustody.merge_checkpoint` keeps its reply bytes)
- Test: `home/common/agent-skills/tests/test_artifact_budget.py` (module helpers and new class `SkillNamedReplyTest`)
- Test: `home/common/agent-skills/tests/test_delivery_model.py` (new class `WorkerReplyResponseTest`)

**Interfaces:**
- Consumes: Task 2's observe check, so the `direct-owner` driver's described reply passes. From the test harnesses:
  - `DeliveredCustody` (`test_attempt_custody.py`): `spawn(*issues) -> {issue: custody}`, which runs `setup_run` (a fresh project, HOME with a host declaration, a run, contracts for 207 and 209) and a minute-0 control spawn; `summary(custody, historical_state) -> bytes`; and `merge_checkpoint(custody, minute)`.
  - From `DeliveredControlHarness` and `BuilderHarness`: `project()`, `setup_run()`, `request(minute, *, recorded, contracts)`, `cli(*args, stdin=None, ok=True)` (bytes, asserting exit 0), `boundary(name, raw) -> CompletedProcess`, `linked_worktree(name, branch) -> str`, `direct_request(**changes) -> dict` (the empty issue-171 interface-2 request), `run_args` and `worktrees`.
  - `DELIVERED` (207) and `at(minute)` from `test_delivered_control.py`, and `load_source_module` from `test_workflow_state.py`.
- Produces: `DeliveredCustody.checkpoint_reply: bytes`, the stdout of `merge_checkpoint`'s `checkpoint-delivery` call. Also `skill_texts()`, `workflow_state_subcommands()`, `skill_named_workflow_responses()` and `NOT_WORKFLOW_RESPONSES` in `test_artifact_budget.py`.

**Invariants:**
- A `register-worker` reply, members exactly `{worker_id, launch, parent}`, passes when `launch` is a launch id, `worker_id` is `<launch>:w<n>`, and `parent` is null or a worker id of the same launch.
- A `release-worker` reply, members exactly `{worker_id, release_event, released}`, passes when `release_event` is `returned` or `stopped` and `released` lists unique worker ids of `worker_id`'s launch. That list is empty or contains `worker_id`, and for `returned` it is `[]` or `[worker_id]`.
- A `mark-progress` reply, members exactly `{action_id, outcome, marker}`, passes when `action_id` is a launch id, `outcome` is one of `baseline`, `advanced`, `unchanged` or `diverged`, and `marker` is 40 or 64 lowercase hex characters.
- A launch id is `<issue>:[r]<n>:<launch>`, each ordinal 1–18 digits with no leading zero, which is the helper's `ACTION_ID_PATTERN` grammar. The validator keeps its own copy, as it does `_LAUNCH_REASONS` (D4). `check-worker` and `declare-lane` replies stay rejected (spec § Out of scope).
- The helper's three outputs are unchanged (D6).
- The derived skill-named set comes from every `*.md` under the shared, Claude-only and Codex skill trees outside `evals/`. It keeps the names that are subcommands of the helper's own parser and removes `build-delivery` and `resume-pack` (D5). That set must equal the set of `reply_*` drivers (D11).
- Each driver starts a fresh project and returns one real reply's stdout, in the argv form the skills use. Each reply passes the boundary with exit 0, empty stderr, and stdout equal to the input.

- [ ] **Step 1: Keep the checkpoint reply**

In `DeliveredCustody.merge_checkpoint` (`test_attempt_custody.py`, about line 553), assign the `checkpoint-delivery` call's stdout: `self.checkpoint_reply = self.cli("checkpoint-delivery", ...).stdout`, with the arguments unchanged. Add to its docstring: "The `checkpoint-delivery` reply's bytes are kept in `self.checkpoint_reply`."

- [ ] **Step 2: Write the failing tests**

`test_artifact_budget.py`: add `import argparse` and `import re` to the imports. Below the existing `from ._delivery_model_fixtures import ...` line, add:

```python
from .test_attempt_custody import DeliveredCustody
from .test_delivered_control import DELIVERED, at
from .test_workflow_state import load_source_module
```

After the `import artifact_budget` line, add:

```python
WORKFLOW_STATE = ROOT / "home/common/agent-skills/scripts/workflow-state.py"
SKILL_TREES = (ROOT / "home/common/agent-skills/skills", ROOT / "home/common/claude-code/skills",
               ROOT / "home/common/codex/skills")
# Issue 473 D5: the skill-named subcommands whose stdout is no workflow response.
NOT_WORKFLOW_RESPONSES = frozenset({"build-delivery", "resume-pack"})
SKILL_CALL = re.compile(r"workflow-state ([a-z][a-z-]*)")
VALIDATOR_PIPE = re.compile(r"\|\s*artifact-budget validate-report(?P<arguments>[^|]*)")


def skill_texts():
    """Every skill document of the shared, Claude-only and Codex trees, evals excluded."""
    for tree in SKILL_TREES:
        for path in sorted(tree.rglob("*.md")):
            if "evals" not in path.relative_to(tree).parts:
                yield path, path.read_text(encoding="utf-8")


def workflow_state_subcommands():
    """The subcommand names of workflow-state's own parser, loaded from source."""
    parser = load_source_module(WORKFLOW_STATE, "artifact_budget_test_workflow_state").build_parser()
    return frozenset(next(action for action in parser._actions
                          if isinstance(action, argparse._SubParsersAction)).choices)


def skill_named_workflow_responses():
    """Every workflow-state subcommand a skill names whose reply is a workflow response."""
    commands = workflow_state_subcommands()
    named = {name for _, text in skill_texts() for name in SKILL_CALL.findall(text)}
    return frozenset(named & commands) - NOT_WORKFLOW_RESPONSES
```

Add this class before the `if __name__ == "__main__":` block:

```python
class SkillNamedReplyTest(DeliveredCustody, unittest.TestCase):
    """Issue 473 AC3: each workflow-state reply a skill names passes the workflow-response
    boundary. A driver is a `reply_<subcommand>` method that returns one real reply."""

    def drivers(self):
        return {name[len("reply_"):].replace("_", "-"): getattr(self, name)
                for name in dir(self) if name.startswith("reply_")}

    def launched(self):
        """Spawn 207 under its contract at minute 0: its custody and action id."""
        custody = self.spawn(DELIVERED)[DELIVERED]
        return custody, custody["action_id"]

    def reply_init_run(self):
        self.project()
        return self.cli("init-run", "--repo-root", self.root, "--creation-key",
                        "from-issue:207:1", "--now", at(0)).stdout

    def reply_control(self):
        self.setup_run()
        return self.cli("control", *self.run_args, "--request-file", "-", stdin=self.request(
            0, recorded={DELIVERED: None}, contracts=True)).stdout

    def reply_direct_owner(self):
        self.project()
        return self.cli("direct-owner", "--repo-root", self.root, "--request-file", "-",
                        stdin=json.dumps(self.direct_request()).encode()).stdout

    def reply_check_launch(self):
        _, action = self.launched()
        return self.cli("check-launch", *self.run_args, "--action-id", action).stdout

    def reply_current_launch(self):
        _, action = self.launched()
        return self.cli("current-launch", *self.run_args, "--action-id", action).stdout

    def reply_owner_liveness(self):
        _, action = self.launched()
        with mock.patch.dict(os.environ, {"WORKFLOW_STATE_TEST_CLOCK": at(1)}):
            return self.cli("owner-liveness", *self.run_args, "--action-id", action,
                            "--stall-minutes", "90").stdout

    def reply_register_worker(self):
        _, action = self.launched()
        return self.cli("register-worker", *self.run_args, "--now", at(1),
                        "--action-id", action).stdout

    def reply_release_worker(self):
        _, action = self.launched()
        self.cli("register-worker", *self.run_args, "--now", at(1), "--action-id", action)
        return self.cli("release-worker", *self.run_args, "--now", at(2),
                        "--worker-id", f"{action}:w1", "--event", "returned").stdout

    def reply_mark_progress(self):
        _, action = self.launched()
        self.linked_worktree(Path(self.worktrees[DELIVERED]).name, "issue-207-shape")
        return self.cli("mark-progress", *self.run_args, "--now", at(1),
                        "--action-id", action).stdout

    def reply_progress(self):
        _, action = self.launched()
        return self.cli("progress", *self.run_args, "--action-id", action, "--phase", "1",
                        "--next-needs-context", "true", "--artifacts-sufficient", "false",
                        "--remainder-self-contained", "false", "--now", at(1)).stdout

    def reply_suspend(self):
        _, action = self.launched()
        return self.cli("suspend", *self.run_args, "--action-id", action,
                        "--blocked-on", "transport", "--now", at(1)).stdout

    def reply_finish(self):
        custody, _ = self.launched()
        return self.cli("finish", *self.run_args, "--now", at(1), "--summary-file", "-",
                        stdin=self.summary(custody, "stopped")).stdout

    def reply_checkpoint_delivery(self):
        custody, _ = self.launched()
        self.merge_checkpoint(custody, 1)
        return self.checkpoint_reply

    def reply_host_route(self):
        self.setup_run()
        return self.cli("host-route", "--route", "codex").stdout

    def test_the_drivers_cover_exactly_the_skill_named_replies(self):
        self.assertEqual(set(self.drivers()), skill_named_workflow_responses())

    def test_every_skill_named_reply_passes_the_workflow_response_boundary(self):
        for name, reply in sorted(self.drivers().items()):
            with self.subTest(subcommand=name):
                raw = reply()
                checked = self.boundary("workflow-response", raw)
                self.assertEqual((checked.returncode, checked.stderr), (0, b""))
                self.assertEqual(checked.stdout, raw)

    def test_every_explicit_validator_pipe_names_the_workflow_response_boundary(self):
        replies = skill_named_workflow_responses()
        piped = []
        for path, text in skill_texts():
            for line in text.splitlines():
                for call in SKILL_CALL.finditer(line):
                    pipe = VALIDATOR_PIPE.search(line, call.end())
                    if call[1] not in replies or pipe is None:
                        continue
                    piped.append((path.name, call[1]))
                    with self.subTest(document=path.name, subcommand=call[1]):
                        self.assertIn("--boundary workflow-response", pipe["arguments"])
        self.assertTrue(piped)
```

`test_delivery_model.py`: add after `ObserveExpectsResponseTest`:

```python
class WorkerReplyResponseTest(unittest.TestCase):
    """Issue 473 D6: the register-worker, release-worker and mark-progress replies at the
    workflow-response boundary, matched by exact member set."""

    REGISTERED = {"worker_id": "207:1:1:w1", "launch": "207:1:1", "parent": None}
    RELEASED = {"worker_id": "207:1:1:w1", "release_event": "returned",
                "released": ["207:1:1:w1"]}
    MARKED = {"action_id": "207:1:1", "outcome": "baseline", "marker": "a" * 40}

    @classmethod
    def setUpClass(cls):
        cls.model = load_model(SOURCE, "delivery_model_worker_reply_test")

    def validate(self, value):
        return self.model.validate_delivery_object(
            value, expected_kind="workflow-response", notes_max_characters=4096)

    def test_each_reply_shape_is_accepted_unchanged(self):
        accepted = {
            "registered": self.REGISTERED,
            "registered_child": {**self.REGISTERED, "worker_id": "207:1:1:w2",
                                 "parent": "207:1:1:w1"},
            "registered_remainder": {"worker_id": "207:r1:1:w1", "launch": "207:r1:1",
                                     "parent": None},
            "released_returned": self.RELEASED,
            "released_repeat": {**self.RELEASED, "released": []},
            "released_stopped_subtree": {**self.RELEASED, "release_event": "stopped",
                                         "released": ["207:1:1:w1", "207:1:1:w2"]},
            "released_stopped_repeat": {**self.RELEASED, "release_event": "stopped",
                                        "released": []},
            **{f"marked_{outcome}": {**self.MARKED, "outcome": outcome}
               for outcome in ("baseline", "advanced", "unchanged", "diverged")},
            "marked_sha256": {**self.MARKED, "marker": "b" * 64},
        }
        for name, value in accepted.items():
            with self.subTest(name=name):
                self.assertEqual(self.validate(copy.deepcopy(value)), value)

    def test_every_broken_invariant_is_rejected(self):
        rejected = {
            "register_other_launch": {**self.REGISTERED, "worker_id": "207:1:2:w1"},
            "register_bad_launch": {**self.REGISTERED, "launch": "207:1",
                                    "worker_id": "207:1:w1"},
            "register_zero_ordinal": {**self.REGISTERED, "worker_id": "207:1:1:w0"},
            "register_parent_other_launch": {**self.REGISTERED, "worker_id": "207:1:1:w2",
                                             "parent": "207:1:2:w1"},
            "register_parent_not_worker": {**self.REGISTERED, "parent": "207:1:1"},
            "register_extra": {**self.REGISTERED, "registered_at": "2026-09-21T00:00:00Z"},
            "release_unknown_event": {**self.RELEASED, "release_event": "expired"},
            "release_without_worker": {**self.RELEASED, "released": ["207:1:1:w2"]},
            "release_returned_subtree": {**self.RELEASED,
                                         "released": ["207:1:1:w1", "207:1:1:w2"]},
            "release_other_launch": {**self.RELEASED, "release_event": "stopped",
                                     "released": ["207:1:1:w1", "207:1:2:w1"]},
            "release_duplicate": {**self.RELEASED, "release_event": "stopped",
                                  "released": ["207:1:1:w1", "207:1:1:w1"]},
            "release_not_list": {**self.RELEASED, "released": "207:1:1:w1"},
            "release_bad_worker": {**self.RELEASED, "worker_id": "w1", "released": []},
            "mark_unknown_outcome": {**self.MARKED, "outcome": "stalled"},
            "mark_short_marker": {**self.MARKED, "marker": "a" * 39},
            "mark_upper_marker": {**self.MARKED, "marker": "A" * 40},
            "mark_null_marker": {**self.MARKED, "marker": None},
            "mark_bad_action": {**self.MARKED, "action_id": "207:1"},
            "mark_extra": {**self.MARKED, "changed": True},
        }
        for name, value in rejected.items():
            with self.subTest(mutation=name), self.assertRaises(self.model.DeliveryModelError):
                self.validate(value)
```

- [ ] **Step 3: Run the tests and watch them fail**

Run (Unit run, timeout 900 s; about 20 s): `test_artifact_budget.py -k SkillNamedReplyTest`
Expected: FAIL in exactly three subtests of `test_every_skill_named_reply_passes_the_workflow_response_boundary`: `register-worker`, `release-worker` and `mark-progress`, each with exit 2 and `invalid workflow response`. The coverage and pipe tests pass.

Run: `test_delivery_model.py -k WorkerReplyResponseTest`
Expected: FAIL. Every accepted shape is rejected.

- [ ] **Step 4: Add the three reply checks**

`delivery_model/_wire.py`: add `import re` to the imports. After `_LAUNCH_REASONS`, add:

```python
# Issue 473 D6: the worker and progress replies' identities, the validator's own copy of
# the helper's grammar: a launch is `<issue>:[r]<attempt or remainder>:<launch>`.
_LAUNCH = r"[1-9][0-9]{0,17}:r?[1-9][0-9]{0,17}:[1-9][0-9]{0,17}"
_LAUNCH_ID = re.compile(_LAUNCH)
_WORKER_ID = re.compile(rf"({_LAUNCH}):w[1-9][0-9]{{0,17}}")
_COMMIT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_RELEASE_EVENTS = frozenset({"returned", "stopped"})
_PROGRESS_OUTCOMES = frozenset({"baseline", "advanced", "unchanged", "diverged"})


def _launch_id(value: Any) -> str:
    if not isinstance(value, str) or _LAUNCH_ID.fullmatch(value) is None: _reject()
    return value


def _worker_launch(value: Any) -> str:
    """The launch id of worker id `value`."""
    matched = _WORKER_ID.fullmatch(value) if isinstance(value, str) else None
    if matched is None: _reject()
    return matched[1]


def _registered_worker(value: dict[str, Any]) -> dict[str, Any]:
    if _worker_launch(value["worker_id"]) != _launch_id(value["launch"]): _reject()
    if value["parent"] is not None and _worker_launch(value["parent"]) != value["launch"]: _reject()
    return value


def _released_worker(value: dict[str, Any]) -> dict[str, Any]:
    launch = _worker_launch(value["worker_id"])
    if not isinstance(value["release_event"], str) or value["release_event"] not in _RELEASE_EVENTS: _reject()
    released = value["released"]
    if not isinstance(released, list) or any(_worker_launch(item) != launch for item in released) \
            or len(set(released)) != len(released): _reject()
    if released and value["worker_id"] not in released: _reject()
    if value["release_event"] == "returned" and released not in ([], [value["worker_id"]]): _reject()
    return value


def _progress_mark(value: dict[str, Any]) -> dict[str, Any]:
    _launch_id(value["action_id"])
    if not isinstance(value["outcome"], str) or value["outcome"] not in _PROGRESS_OUTCOMES: _reject()
    if not isinstance(value["marker"], str) or _COMMIT_ID.fullmatch(value["marker"]) is None: _reject()
    return value
```

In `_workflow_response`, right after the check-launch branch's `return value`, add:

```python
    if set(value) == {"worker_id", "launch", "parent"}: return _registered_worker(value)
    if set(value) == {"worker_id", "release_event", "released"}: return _released_worker(value)
    if set(value) == {"action_id", "outcome", "marker"}: return _progress_mark(value)
```

- [ ] **Step 5: Verify**

1. Unit run: `test_artifact_budget.py` [about 45 s]. Expected: `OK`, `SkillNamedReplyTest`'s three tests included.
2. Unit run: `test_delivery_model.py` [about 1 s]. Expected: `OK`.
3. Unit run: `test_attempt_custody.py -k MisbindingTest -k LateSummaryTest` [about 20 s]. Expected: `OK` (`merge_checkpoint` still behaves the same).
4. Helper output unchanged (exits 1 on any change): `bash -c 'test -z "$(git diff HEAD -- home/common/agent-skills/scripts/workflow-state.py)"'`.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/scripts/delivery_model/_wire.py home/common/agent-skills/tests/test_attempt_custody.py home/common/agent-skills/tests/test_artifact_budget.py home/common/agent-skills/tests/test_delivery_model.py
launch-commit ... -- -m "feat(delivery-model): worker and progress replies pass the workflow-response boundary (issue 473)"
```
