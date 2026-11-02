# Task 3: The verification cause, suspension and parked lane

**Files:**
- Modify: `python/agent_tools/attempt_custody.py` (the cause comment and `BLOCKED_ON_VALUES`; `OBSERVATION_GATED_BLOCKED_ON`; `HUMAN_GATED_BLOCKED_ON`; `resume_permitted` after `suspension_reason`)
- Modify: `tests/test_attempt_custody.py` (`VocabularyTest`)
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (the `attempt_custody` import; `suspended_reply` after `reentry_command`; `_apply_one_issue_policy`; `command_direct_owner`; `command_suspend`; the `suspend` parser)
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py` (the `suspended` reply's cause set)
- Modify: `home/common/agent-skills/tests/test_verification_suspension.py` (a harness and three classes after Task 2's classes)
- Modify: `home/common/agent-skills/README.md` (§ Attempt custody and fencing's vocabulary list; a new `### Verification blockers` subsection before `### Resume pack`)

**Interfaces:**
- Consumes: Task 1's `verification_blocker.park`, `strict_load`, `blocker_id`, `BlockerRefused`; Task 2's schema-11 ledger (`verification_blockers`, the attempt's `verification_blocker`, the attempt rule in `validate_attempt`), and the module Task 2 created, with its `LedgerHarness` (`worktree`, `spawn_all`) and `T`; `LifecycleHarness`'s `run_cli`, `launch_arguments`, `suspend`, `control`, `control_validated`, `acquire_direct`, `direct_run_id`, `direct_request`, `direct_owner_at_root`, `validated_response`, `tree_snapshot`, `read_state`, `write_state`, `worktree_fact`, `tracker_fact`, `delivery_model` and `delivery_fixtures`.
- Produces (c3 builds on these exact names):
  - `attempt_custody.OBSERVATION_GATED_BLOCKED_ON = frozenset({"verification"})` and `resume_permitted(blocked_on: str, *, human_directed: bool) -> bool`.
  - `workflow-state`: `suspended_reply(runtime, *, run_id: str, issue: int, attempt: dict) -> dict`; `_apply_one_issue_policy(..., reply_parked: bool = False)` and its operation `"parked"`; `suspend --verification-input <absolute-path|->`.
  - The test module's `failure(failure_class="dependency", path="flake.lock")`, `record(attempts)` and `VerificationHarness` (`park`, `attempt`, `custody_reason`, `recorded`, `suspended_reply`).

**Invariants:**
- The three classes partition `BLOCKED_ON_VALUES`; `HUMAN_GATED_BLOCKED_ON`'s members are unchanged (`human_gate`, `external`, `agent_dispatch`), so `workflow_delivery.remainder_policy`, which reads it, is untouched (D6). `OWNER_BLOCKED_ON_VALUES` and `SUSPENSION_CAUSES` gain `verification` by derivation, so `suspend --blocked-on` offers it and custody parks `suspended:verification`.
- `--verification-input` is required exactly with `--blocked-on verification`; the input is read, strict-loaded, validated and identified before `refuse_misbound` and before any lock, so every refusal exits 2 with `.superpowers` byte-identical (D8).
- Inside the transaction `suspend_attempt` decides first: at the stall bound the reply is `terminal` and no record is created or touched; otherwise `park` and the pointer land in the one write `transact` validates at schema 11 and commits before the reply prints (D8). The reply envelope does not name the blocker.
- Control's two `_apply_one_issue_policy` calls are unchanged: a parked attempt is not resumable there and gets the existing non-dispatching `terminal` verdict in any sweep, directed or not (D7, D14). `direct-owner` passes `reply_parked=True`: merged-forge reconciliation, then the tracker halt, then `observe` `forge_pr`, then `parked`, answered by `suspended_reply` with nothing written; `new_run` stays refused for a suspended latest attempt.
- `delivery_model` still imports no `agent_tools`; no interface version moves (D10).

- [ ] **Step 1: Write the failing tests**

`tests/test_attempt_custody.py`, `VocabularyTest`: `test_the_closed_sets_are_the_shipped_ones` pins `BLOCKED_ON_VALUES` with `"verification"` added (its other pins, `HUMAN_GATED_BLOCKED_ON` included, are unchanged), and after it add:

```python
    def test_three_cause_classes_partition_the_attempt_causes(self):
        self.assertEqual(ac.OBSERVATION_GATED_BLOCKED_ON, {"verification"})
        classes = (ac.AUTO_RESUMABLE_BLOCKED_ON, ac.HUMAN_GATED_BLOCKED_ON,
                   ac.OBSERVATION_GATED_BLOCKED_ON)
        self.assertEqual(frozenset().union(*classes), ac.BLOCKED_ON_VALUES)
        self.assertEqual(sum(map(len, classes)), len(ac.BLOCKED_ON_VALUES))
        for cause in sorted(ac.BLOCKED_ON_VALUES):
            for directed in (False, True):
                expected = (cause in ac.AUTO_RESUMABLE_BLOCKED_ON
                            or (cause in ac.HUMAN_GATED_BLOCKED_ON and directed))
                with self.subTest(cause=cause, human_directed=directed):
                    self.assertIs(ac.resume_permitted(cause, human_directed=directed), expected)
        for value in ("owner_unavailable", "nonsense", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ac.resume_permitted(value, human_directed=True)
        self.assertEqual(ac.suspension_reason("verification"), "suspended:verification")
        self.assertEqual(ac.blocked_on_of("suspended:verification"), "verification")
```

`home/common/agent-skills/tests/test_verification_suspension.py`: add `import copy` before `import json`, and after the standard-library imports, before `from .test_workflow_state import LifecycleHarness`:

```python
from agent_tools import attempt_custody as ac
from agent_tools import verification_blocker as vb
from agent_tools.transaction_core import TransactionStore

```

Then insert this block after `HelperGenerationTest` and before `if __name__ == "__main__":` (two blank lines around each top-level definition):

```python
LOCK = "a" * 40
DIRECT_NOW = "2026-08-20T10:{:02d}:00Z".format


def failure(failure_class="dependency", path="flake.lock"):
    """A `verification-failure` as `verification-observe failure` prints it (issue 543)."""
    return {"kind": "verification-failure", "schema_version": 1,
            "repository": {"project_id": "fagenorn/nix-config", "integration_branch": "main"},
            "command": {"id": "nix-build", "argv": ["just", "build"], "cwd": ".", "env": []},
            "failure_class": failure_class,
            "facts": [{"name": "flake-lock", "source": {"paths": [path]},
                       "value": {"objects": [{"path": path, "mode": "100644", "object": LOCK}]}}]}


def record(attempts):
    """The open record two equal failures share (issue 544 D3)."""
    value = failure()
    return {"id": vb.blocker_id(value), "repository": value["repository"],
            "command": value["command"], "failure_class": "dependency", "facts": value["facts"],
            "attempts": [{"issue": issue, "attempt": 1} for issue in attempts],
            "state": "open", "resolution": None}


class VerificationHarness(LedgerHarness):
    """Attempts suspended on verification blockers through the public `suspend`."""

    def park(self, issue, raw, *, now, cause="verification", flag=True, ok=True):
        """`suspend` attempt 1 of `issue` on `cause` with `raw` (an object, or bytes) as the
        `--verification-input` file; `flag=False` omits the flag."""
        path = self.root / f"failure-{issue}.json"
        path.write_bytes(raw if isinstance(raw, bytes) else json.dumps(raw).encode())
        done = self.run_cli(
            "suspend", "--repo-root", self.root, "--run-id", self.run_id, "--issue", issue,
            "--attempt", 1, "--blocked-on", cause,
            *(("--verification-input", path) if flag else ()), "--now", now,
            *self.launch_arguments(issue, 1, None), ok=ok)
        return self.validated_response(done.stdout) if ok else done

    def attempt(self, issue):
        return self.read_state()["issues"][str(issue)]["attempts"][0]

    def custody_reason(self, issue):
        """The reason of the last transition of attempt 1's custody transaction."""
        store = TransactionStore(self.store_root)
        transaction = store.load(store.lookup(
            ac.creation_key(self.read_state()["transaction_id"], issue, 1)))
        return [event["reason"] for event in transaction.events
                if event["type"] == "transitioned"][-1]

    def recorded(self, issue):
        return [self.worktree_fact(issue, recorded={"path": self.worktree(issue),
                                                    "state": "matching_issue_branch"})]

    def suspended_reply(self, issue):
        return {"interface_version": 2, "kind": "suspended", "run_id": self.run_id,
                "issue": issue, "custody": {"kind": "implementation", "attempt": 1,
                                            "launch": 1, "action_id": f"{issue}:1:1"},
                "blocked_on": "verification", "reentry": f"/from-issue {issue} --auto"}


class SuspensionTest(VerificationHarness, unittest.TestCase):
    def test_equal_failures_of_two_attempts_share_one_record(self):
        self.spawn_all(61, 62)
        for minute, issue in ((5, 61), (6, 62)):
            self.assertEqual(self.park(issue, failure(), now=T(minute)),
                             self.suspended_reply(issue))
        identity = vb.blocker_id(failure())
        self.assertEqual(self.read_state()["verification_blockers"],
                         {identity: record([61, 62])})
        for issue in (61, 62):
            attempt = self.attempt(issue)
            self.assertEqual(
                (attempt["state"], attempt["blocked_on"], attempt["verification_blocker"]),
                ("suspended", "verification", identity))
            self.assertEqual(self.custody_reason(issue), "suspended:verification")

    def test_a_bad_input_or_flag_is_refused_before_anything_is_written(self):
        self.spawn_all(61)
        before = self.tree_snapshot()
        cases = {
            "duplicate key": ({"raw": b'{"kind": "verification-failure", "kind": "x"}'},
                              "invalid verification input: input: duplicate JSON key 'kind'"),
            "not JSON": ({"raw": b"{"}, "invalid verification input: input: "),
            "unclassified": ({"raw": failure(failure_class="product")},
                             "invalid verification input: failure_class: unclassified"),
            "secret-shaped": ({"raw": failure(path=".env")}, "invalid verification input: "
                              "facts[0].source.paths[0]: secret-shaped"),
            "missing flag": ({"raw": failure(), "flag": False},
                             "--verification-input is required with --blocked-on verification"),
            "stray flag": ({"raw": failure(), "cause": "transport"},
                           "--verification-input is only valid with --blocked-on verification"),
        }
        for label, (arguments, line) in cases.items():
            with self.subTest(case=label):
                raw = arguments.pop("raw")
                done = self.park(61, raw, now=T(5), ok=False, **arguments)
                self.assertEqual((done.returncode, done.stdout), (2, ""))
                if line.endswith(": "):  # the JSON decoder's own message follows
                    self.assertTrue(done.stderr.startswith(f"workflow-state: {line}"), done.stderr)
                    self.assertEqual(done.stderr.count("\n"), 1, done.stderr)
                else:
                    self.assertEqual(done.stderr, f"workflow-state: {line}\n")
                self.assertEqual(self.tree_snapshot(), before)

    def test_the_stall_bound_stops_the_attempt_and_records_no_blocker(self):
        self.spawn_all(61)
        for minute in (1, 3, 5):
            self.suspend(issue=61, attempt=1, blocked_on="transport", now=T(minute))
            self.control(now=T(minute + 1), issues=[61], tracker=[self.tracker_fact(61)],
                         worktrees=self.recorded(61), max_parallel=100)
        reply = self.park(61, failure(), now=T(7))
        self.assertEqual((reply["kind"], reply["source"], reply["reason"]),
                         ("terminal", "lifecycle", "stopped"))
        attempt = self.attempt(61)
        self.assertEqual((self.read_state()["verification_blockers"], attempt["state"],
                          attempt["result_source"], attempt["verification_blocker"]),
                         ({}, "stopped", "stalled", None))

    def test_a_resolved_record_is_reopened_by_a_later_suspension(self):
        self.spawn_all(61, 62)
        self.park(61, failure(), now=T(5))
        identity = vb.blocker_id(failure())
        state = self.read_state()
        held = state["verification_blockers"][identity]
        changed = copy.deepcopy(held["facts"])
        changed[0]["value"]["objects"][0]["object"] = "b" * 40
        held.update(state="resolved", resolution={"facts": changed})
        self.write_state(state)
        self.park(62, failure(), now=T(6))
        self.assertEqual(self.read_state()["verification_blockers"],
                         {identity: record([61, 62])})


class ParkedTest(VerificationHarness, unittest.TestCase):
    def test_no_sweep_resumes_a_parked_attempt(self):
        self.spawn_all(61)
        self.park(61, failure(), now=T(5))
        for minute, directed in ((6, False), (7, True)):
            with self.subTest(human_directed=directed):
                issue_before = self.read_state()["issues"]["61"]
                reply = self.control_validated(now=T(minute), issues=[61],
                                               tracker=[self.tracker_fact(61)],
                                               worktrees=self.recorded(61),
                                               human_directed=directed)
                self.assertEqual((reply["actions"], reply["next_deadline"]),
                                 ([{"id": "finalize", "kind": "finalize"}], None))
                (summary,) = reply["summaries"]
                self.assertEqual((summary["state"], summary["blocked_on"]),
                                 ("suspended", "verification"))
                self.assertEqual(self.read_state()["issues"]["61"], issue_before)

    def test_direct_owner_replies_suspended_until_a_merge_reconciles(self):
        self.acquire_direct(issue=73)
        self.run_id = self.direct_run_id(73, 1)
        self.park(73, failure(), now=DIRECT_NOW(5))
        before = self.tree_snapshot()

        def direct(minute, **fields):
            done = self.direct_owner_at_root(
                self.root, self.direct_request(issue=73, now=DIRECT_NOW(minute), **fields))
            return self.validated_response(done.stdout)

        observe = direct(6, forge=None)
        self.assertEqual((observe["kind"], [item["kind"] for item in observe["requirements"]]),
                         ("observe", ["forge_pr"]))
        self.assertEqual(direct(7), self.suspended_reply(73))
        self.assertEqual(self.tree_snapshot(), before)
        merged = {"state": "merged", "url": "https://github.com/fagenorn/nix-config/pull/73",
                  "merge_sha": "b" * 40}
        reply = direct(8, forge=merged)
        self.assertEqual((reply["kind"], reply["reason"]), ("terminal", "merged"))
        attempt = self.attempt(73)
        self.assertEqual((attempt["state"], attempt["blocked_on"],
                          attempt["verification_blocker"]), ("merged", None, None))
        self.assertEqual(self.read_state()["verification_blockers"], {
            vb.blocker_id(failure()): record([73])})


class WireCauseTest(LifecycleHarness, unittest.TestCase):
    def test_the_suspended_reply_admits_exactly_the_owner_causes(self):
        model = self.delivery_model
        reply = self.delivery_fixtures.workflow_responses(model)["suspended"]

        def validate(cause):
            value = {**copy.deepcopy(reply), "blocked_on": cause}
            return value, model.validate_delivery_object(
                value, expected_kind="workflow-response", notes_max_characters=4096)

        for cause in sorted(ac.OWNER_BLOCKED_ON_VALUES):
            with self.subTest(cause=cause):
                value, validated = validate(cause)
                self.assertEqual(validated, value)
        for cause in ("unknown", "host_capacity", "owner_unavailable"):
            with self.subTest(cause=cause), self.assertRaises(model.DeliveryModelError):
                validate(cause)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_attempt_custody.py home/common/agent-skills/tests/test_verification_suspension.py 2>&1 | tail -4'`
Expected: `Ran 45 tests` and `FAILED (failures=12, errors=1)`: `test_three_cause_classes_partition_the_attempt_causes` errors (`no attribute 'OBSERVATION_GATED_BLOCKED_ON'`); `test_the_closed_sets_are_the_shipped_ones` fails; every `SuspensionTest` and `ParkedTest` case fails, the suspensions on argparse's `unrecognized arguments: --verification-input` and the six refusal subtests on their stderr line (argparse's usage text). `WireCauseTest` passes at this commit, because the vocabulary and the wire set still agree; from Step 3 on it fails if one moves without the other.

- [ ] **Step 3: Implement**

`python/agent_tools/attempt_custody.py` (D6):
- Add `"verification"` to `BLOCKED_ON_VALUES`, and append to the cause comment above it: `# ``verification`` is an owner value: ``suspend --verification-input`` writes it when a` / `# declared verification command fails for a reason outside the change, and parks the attempt` / `# on the run's shared verification blocker. It is observation-gated: no sweep and no human` / `# re-entry resumes it, and nothing records the observation that would (issue 544 D6).`
- After `AUTO_RESUMABLE_BLOCKED_ON` add `# A suspension cause only an observation of the blocker it names clears (issue 544 D6).` and `OBSERVATION_GATED_BLOCKED_ON = frozenset({"verification"})`; then `HUMAN_GATED_BLOCKED_ON = (BLOCKED_ON_VALUES - AUTO_RESUMABLE_BLOCKED_ON - OBSERVATION_GATED_BLOCKED_ON)`, its comment unchanged.
- After `suspension_reason` add `resume_permitted(blocked_on: str, *, human_directed: bool) -> bool`: a non-`str` or a value outside `BLOCKED_ON_VALUES` (`owner_unavailable` included) raises `ValueError(f"blocked_on {blocked_on!r} is not one of {sorted(BLOCKED_ON_VALUES)}")`; an auto-resumable cause gives `True`, a human-gated one `human_directed`, the rest (observation-gated) `False`. Its docstring states that table and that no attempt is suspended on `owner_unavailable`.

`home/common/agent-skills/scripts/workflow-state.py`:
- In the `agent_tools.attempt_custody` import, drop `AUTO_RESUMABLE_BLOCKED_ON` (nothing else reads it) and add `OBSERVATION_GATED_BLOCKED_ON` and `resume_permitted`, keeping the list sorted.
- After `reentry_command` add `suspended_reply(runtime, *, run_id: str, issue: int, attempt: dict[str, Any]) -> dict[str, Any]`, returning `{"interface_version": 2, "kind": "suspended", "run_id": run_id, "issue": issue, "custody": runtime.custody_for_record(issue, "implementation", attempt), "blocked_on": attempt["blocked_on"], "reentry": reentry_command(issue)}`; docstring: the interface-2 `suspended` envelope of a suspended attempt, `suspend`'s reply and the direct owner's for an attempt parked on an observation-gated cause (issue 544 D7). `command_suspend`'s inline envelope is replaced by a call to it (same bytes).
- Before `command_suspend` add `verification_failure(args) -> dict[str, Any] | None` (D8): without `--verification-input` it returns `None`, or raises `WorkflowError("--verification-input is required with --blocked-on verification")` when `args.blocked_on == "verification"`; with it and another cause it raises `WorkflowError("--verification-input is only valid with --blocked-on verification")`; otherwise `raw = read_input_bytes(args.verification_input, "verification input")`, `failure = verification_blocker.strict_load(raw)` and `verification_blocker.blocker_id(failure)` (validates and identifies), a `BlockerRefused` becoming `WorkflowError(f"invalid verification input: {error}")`, and it returns `failure`.
- `command_suspend`: `failure = verification_failure(args)` right after `supplied = supplied_time(...)`, before `refuse_misbound`. In the mutation, after the `if not suspended:` (stall) branch, `if failure is not None: attempt["verification_blocker"] = verification_blocker.park(state["verification_blockers"], failure, args.issue, args.attempt)`, then `return suspended_reply(runtime, run_id=args.run_id, issue=args.issue, attempt=attempt), True`. Its docstring gains a paragraph: `--verification-input` is required exactly with `--blocked-on verification`; its failure is read and checked before the ledger is locked, so a refused input writes nothing; a granted suspension then parks the attempt on the run's shared blocker in the same write (issue 544 D8).
- Parser: `suspend.add_argument("--verification-input", help=("absolute path, or - for stdin, of the verification-failure that verification-observe failure printed; required exactly with --blocked-on verification"))`.
- `_apply_one_issue_policy` (D7, D14): a new last keyword `reply_parked: bool = False`. `suspended` uses `resume_permitted(latest["blocked_on"], human_directed=human_directed)` in place of `(human_directed or latest["blocked_on"] in AUTO_RESUMABLE_BLOCKED_ON)`; add `parked = bool(reply_parked and latest is not None and latest["state"] == "suspended" and latest["blocked_on"] in OBSERVATION_GATED_BLOCKED_ON)`. The `terminal` check reads `not (active_unexpired or handed_off or suspended or retryable or parked)`, and the tracker-halt block `if (suspended or parked) and tracker is not None:`. Directly after that block add `if parked:` returning `decision("observe", requirements=unobserved_forge, expired=False)` when `unobserved_forge = forge_requirement()` is not `None`, else `decision("parked", expired=False)`. The docstring sentence ending `leaves those parked and reports them.` continues with the text in the block below.

  ```text
  Nothing resumes an attempt suspended on
  an observation-gated cause (`verification`, issue 544 D6, D7): without
  ``reply_parked`` its verdict is ``terminal``, as control gets it; with it, as
  the direct owner asks, it passes the tracker halt and the forge requirement
  and then returns ``parked``, which changes nothing.
  ```
- `command_direct_owner`: the policy call passes `reply_parked=True`; after the lifecycle `terminal` branch add `elif operation == "parked":` with the comment `# No re-entry resumes a parked attempt; the reply writes nothing.` and `response = suspended_reply(runtime, run_id=run_id, issue=issue, attempt=policy["attempt"])`.

`home/common/agent-skills/scripts/delivery_model/_wire.py`: in the `suspended` branch, the literal set becomes `{"usage_limit", "transport", "human_gate", "external", "agent_dispatch", "deadline", "verification"}` (D10).

`home/common/agent-skills/README.md`:
- In § Attempt custody and fencing, the closed vocabulary list (`usage_limit` … `deadline`) gains `verification` as its last item, before the closing parenthesis. Nothing else in that paragraph changes.
- Insert this subsection, with one blank line around it, directly before `### Resume pack`:

```markdown
### Verification blockers

An owner whose declared verification command fails for a reason outside its change suspends on a shared verification blocker (issue 544, [design](../../../.agents/artifacts/specs/2026-11-02-issue-544-verification-blocker-c2-design.md)): `workflow-state suspend … --blocked-on verification --verification-input <absolute-path|->` takes the `verification-failure` that `verification-observe failure` prints (`python/README.md` § verification-observe). The flag is required exactly with that cause. The input is read as strict JSON and checked before the ledger is locked, so a repeated key, a malformed, unclassified or secret-shaped failure, or a missing or stray flag exits 2 with `workflow-state: invalid verification input: <field>: <reason>` or the flag's own line, and writes nothing. A suspension at the stall bound stops the attempt `stopped(stalled)` as any other does and records no blocker. Otherwise, in the same write, the run's `verification_blockers` map (schema 11) gains or joins the record keyed by the failure's `blocker_id`: it holds only the failure's `repository`, `command`, `failure_class` and `facts`, every attempt that ever parked on it in `attempts`, and `state` `open` (a `resolved` record is reopened). The attempt's `verification_blocker` names that record, custody parks with `suspended:verification`, and the reply is the `suspended` envelope. Equal failures in one run therefore share one record, and no record is deleted. `verification` is observation-gated (`agent_tools.attempt_custody.resume_permitted`): a control sweep, directed or not, reports the attempt `suspended` and dispatches nothing for it, and `direct-owner`, after the tracker halt and the `forge_pr` observation it asks for, replies with the same `suspended` envelope and writes nothing. A merged pull request still reconciles the attempt, which clears its pointer while the record keeps it in `attempts`. Known limitation: nothing records a resolution or resumes a parked attempt yet; that is issue 545.
```

- [ ] **Step 4: Verify**

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_attempt_custody.py tests/test_attempt_identity.py home/common/agent-skills/tests/test_verification_suspension.py home/common/agent-skills/tests/test_delivery_model.py 2>&1 | tail -3'`
Expected: `Ran 130 tests` and `OK` (33, 22, 12 and 63 per module; the new module's 12 are Task 2's 5 and this task's 7).

Run (timeout 1800 s; about 3 minutes): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_attempt_migration.py home/common/agent-skills/tests/test_attempt_custody.py home/common/agent-skills/tests/test_control_cutover.py 2>&1 | tail -3'`
Expected: `Ran 377 tests` and `OK`. With the first command this runs all six modules AC3 names.

Stage this task's files (Step 5's `git add` line; a Git-backed build sees only tracked content), then build (timeout 3600 s; the build imports every `agent_tools` module): `bash -c 'set -o pipefail; just build 2>&1 | tail -3'`
Expected: exit 0.

Run: `if git diff --cached --name-only 87d6065fc1749c0b7b6c427beb9b1d3051bc198d -- home/common/agent-skills/scripts/workflow_delivery.py lib/agent-tools.nix python/agent_tools/verification_observe.py | grep .; then exit 1; fi; grep -c '"verification"}' home/common/agent-skills/scripts/delivery_model/_wire.py`
Expected: no path printed, then `1`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/attempt_custody.py tests/test_attempt_custody.py \
  home/common/agent-skills/scripts/workflow-state.py \
  home/common/agent-skills/scripts/delivery_model/_wire.py \
  home/common/agent-skills/tests/test_verification_suspension.py home/common/agent-skills/README.md
launch-commit … -- -m "feat(workflow-state): park on verification blockers (issue 544)" -m "<session trailers>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":3,"records":[{"bounds":[{"added_lines":30,"boundary":"all","deleted_lines":5,"record_bytes":6144,"support":{"covers":["r3a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3a","last_task":3,"owner":3,"path":"python/agent_tools/attempt_custody.py"},{"bounds":[{"added_lines":25,"boundary":"all","deleted_lines":3,"record_bytes":4096,"support":{"covers":["r3b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3b","last_task":3,"owner":3,"path":"tests/test_attempt_custody.py"},{"bounds":[{"added_lines":135,"boundary":"all","deleted_lines":32,"record_bytes":40960,"support":{"covers":["r2d","r3c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3c","last_task":3,"owner":3,"path":"home/common/agent-skills/scripts/workflow-state.py"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":1,"record_bytes":3072,"support":{"covers":["r3d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3d","last_task":3,"owner":3,"path":"home/common/agent-skills/scripts/delivery_model/_wire.py"},{"bounds":[{"added_lines":450,"boundary":"all","deleted_lines":0,"record_bytes":23552,"support":{"covers":["r2e","r3e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3e","last_task":3,"owner":3,"path":"home/common/agent-skills/tests/test_verification_suspension.py"},{"bounds":[{"added_lines":8,"boundary":"all","deleted_lines":3,"record_bytes":34816,"support":{"covers":["r2n","r3f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3f","last_task":3,"owner":3,"path":"home/common/agent-skills/README.md"}]}}
```
