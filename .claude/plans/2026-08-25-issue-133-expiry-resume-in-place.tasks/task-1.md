# Task 1: Reap first, resume in place

Discharges AC1, AC3, AC4, and the first half of AC2. Rests on spec rows D1, D2,
D3, D6, D7, D8, D9, D11, D12, and on the new D13, D14.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (this is the first task).
- Produces, for Tasks 2–4:
  - `_apply_one_issue_policy` calls `demote_expired_attempt(ledger_issue, latest, now=now)`
    at exactly **one** site, before any lane predicate is derived. Every later
    predicate (`handed_off`, `suspended`, `retryable`) reads the post-reap attempt.
  - `retryable` no longer contains `expired`; the two predicates are mutually
    exclusive by construction.
  - Every decision returned from the suspension/resume region carries the real
    `expired` value; every decision below it carries `expired=False` behind one
    `assert not expired`.
  - `command_control`'s fallback persistence pass is spelled
    `elif analysis[issue]["expired"] and issue not in planned:`.
- Produces no new function, no new CLI flag, and no new dict key.

**Invariants:**
- A wall-clock expiry never appends an attempt: for any issue whose only
  terminal-free history is expiries, `len(issue_state["attempts"]) == 1` forever.
- After a reaped-and-resumed sweep the attempt keeps its number, its `worktree`
  and its `owner`; only `launches` grows and `deadline_at`/`last_progress_at`
  re-base to `now + attempt_budget_minutes`.
- No sweep emits both a `resumed` action for an issue and an `idle` re-plan of
  the same issue: `planned[issue]` is written by at most one pass.
- The `expired` delta's `state` is read from the persisted ledger and is
  therefore the attempt's real post-policy state.
- A `retried` or `retry_refused` delta is unreachable from a wall-clock deadline.

---

- [ ] **Step 1: Write the failing tests**

All edits are in `WorkflowStateLifecycleTest`.

**1a.** Add these five tests at the **end of the class**, immediately after
`test_check_launch_separates_well_formed_negatives_from_errors` and before
`class ArtifactBudgetPolicyResolutionTest` (base line ~5271):

```python
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
```

**1b.** Delete `test_direct_expiry_retries_on_absent_candidate_then_refuses_attempt_two`
(base line 4612) — its scenario is carried forward in full by
`test_direct_expiry_resumes_in_place_and_ignores_the_candidate` above, which is
the rewrite AC4 asks for, not a deletion of coverage. Do not delete any other
test.

**1c.** Re-point the three surviving control-side fixtures:

In `test_control_combined_six_stage_single_ledger_replay` (base line 1243):

```python
        self.assertEqual([d["kind"] for d in decided["deltas"]],
                         ["expired", "resumed", "spawned"])
        self.assertEqual([a["id"] for a in decided["actions"]],
                         ["51:1:2", "53:1:1", "wait:2026-08-19T13:01:00Z"])
```

and in the same test change the concurrent finish so it names issue 51's only
attempt:

```python
        finished = self.concurrent_finish(
            {51: (1, self.merged_result(51)), 53: (1, self.merged_result(53))},
            now="2026-08-19T12:40:00Z",
        )
```

Everything else in that test — the `paths[51]` worktree assertion, the replay
comparisons, the six-stage structure — stays exactly as it is. The `wait`
instant is unchanged because a resume re-bases the window from the same `now`.

In `test_control_demo_3_expires_retries_and_fills_unrelated_capacity` (base
line 1380), rename it to
`test_control_demo_3_expires_resumes_and_fills_unrelated_capacity` and re-point:

```python
        self.assertEqual([a["kind"] for a in response["actions"]],
                         ["resume", "spawn", "wait"])
        resume, spawn = response["actions"][:2]
        self.assertEqual((resume["id"], resume["worktree"]), ("51:1:2", paths[51]))
        self.assertEqual((spawn["id"], spawn["issue"]), ("53:1:1", 53))
        self.assertEqual([d["kind"] for d in response["deltas"]],
                         ["expired", "resumed", "spawned"])
```

In `test_control_attempt_two_deadline_emits_only_retry_refused` (base line 1638),
rename it to `test_control_attempt_two_deadline_suspends_instead_of_refusing`,
keep the whole owner-reported-failure setup and the
`self.assertEqual(retried["actions"][0]["id"], "47:2:1")` assertion exactly as
they are — that retry is AC3's guarantee and must stay asserted — and replace
only the closing block:

```python
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
```

`retry_refused` keeps live coverage through the owner-reported entrance in
`test_only_one_fresh_retry_and_refusal_links_prior_attempts` and
`test_refused_third_attempt_result_is_not_supersedable`, so this re-pointing
loses no delta-kind coverage (per D14).

**1d.** Strengthen `test_control_expiry_deltas_follow_reversed_request_order`
(base line 1409) — it stays green either way today, which is exactly why the
state it reports is worth pinning. Replace its final assertion with:

```python
        self.assertEqual(response["deltas"], [
            {"issue": 51, "attempt": 1, "kind": "expired", "state": "suspended"},
            {"issue": 47, "attempt": 1, "kind": "expired", "state": "suspended"},
        ])
```

- [ ] **Step 2: Run the tests and watch them fail**

```sh
python3 home/common/agent-skills/tests/test_workflow_state.py 2>&1 | tail -40
```
Expected: failures in the five new tests plus the four re-pointed ones. The
signature failures are `51:2:1 != 51:1:2` (a fresh attempt where a resume was
expected), `'retried' != 'resumed'`, and `KeyError`/`StopIteration` from
`dispatch_action(response, "resume")` finding no resume action.

- [ ] **Step 3: Reap first inside `_apply_one_issue_policy`**

In `home/common/agent-skills/scripts/workflow-state.py`, restructure the region
that begins at `now_value = parse_utc(now, "policy now")` (base line ~1770) so
its order is: identity and cross-checks (unchanged) → `expired` and
`active_unexpired` → the owner-unavailable refusal → the forge-merged
reconciliation → **the reaper** → the remaining predicates → everything else
(per D1, D3).

1. Keep `expired` and `active_unexpired` exactly as they are, and **move**
   `handed_off`, `suspended` and `retryable` below the reaper.
2. Leave `def forge_requirement()` and the
   `if current_owner_unavailable and not active_unexpired: raise` refusal where
   they are; `active_unexpired` is already false for an expired attempt, so the
   refusal's condition, message and outcome are untouched (spec, Out of scope).
3. **Hoist** the whole `if forge is not None and forge["state"] == "merged" and
   latest is not None:` block — including its existing two-line comment and its
   `assert ledger_issue is not None` — so it sits immediately after that
   refusal and immediately before the reaper. It keeps
   `return decision("reconcile", changed=True, expired=False)`.
4. Insert the single reaper call directly after it:

```python
    if expired:
        # One reaper, one call site, running before any lane predicate is
        # derived: everything below sees an ordinary suspension, or the stall
        # escalation's terminal (per D1). Reconciliation is deliberately above
        # this line — an escalation would otherwise return a terminal before a
        # merged pull request was ever considered (per D3).
        assert latest is not None and ledger_issue is not None
        demote_expired_attempt(ledger_issue, latest, now=now)
```

5. Immediately after the reaper, define the three post-reap predicates. Drop the
   now-dead `and not expired` conjuncts from `handed_off` and `suspended` (a
   reaped attempt is `suspended` or `stopped`, never either of those states),
   and drop `expired` from `retryable`:

```python
    handed_off = bool(latest is not None and latest["state"] == "handed_off")
    suspended = bool(
        latest is not None
        and latest["state"] == "suspended"
        and (human_directed or latest["blocked_on"] in AUTO_RESUMABLE_BLOCKED_ON)
    )
    retryable = bool(
        latest is not None
        and (
            (latest["state"] == "failed" and latest["result_source"] == "owner")
            or (latest["state"] == "stopped" and latest["result_source"] == "expiry")
        )
    )
```

- [ ] **Step 4: Propagate `expired` and `changed` out of the suspension region**

Six branches change, and only these six (per D6). Their target values are the
spec's `### Where a reaped attempt goes, lane by lane` table:

1. The early terminal check becomes
   `return decision("terminal", changed=expired, expired=expired)`. Post-reap it
   is reachable with `expired=True` only for the stall escalation, whose
   `stopped`/`stalled` record is neither `retryable` nor `suspended`.
2. `if active_unexpired and not current_owner_unavailable:` keeps
   `decision("idle", expired=False)` — `active_unexpired` implies not expired.
3. The suspension tracker-halt branch becomes
   `return decision("terminal", changed=expired, expired=expired,
   tracker_reason=halted, blockers=control_blockers(tracker))`.
4. In the resume lane, the no-slot return becomes
   `return decision("idle", desired="resume", changed=expired, expired=expired)`.
5. Both `observe` returns in the resume lane (the forge one and the
   recorded-worktree one) become `expired=expired`, `changed` left at its
   default `False` — a reap whose decision is not persisted is discarded and
   re-derived from the same stored attempt on the next call, which is what keeps
   `stalled_resumes` from inflating across observation rounds (per D12).
6. The dispatched resume becomes
   `return decision("resume", changed=True, expired=expired)`.

Without the `changed`, branches 1, 3 and 4 would compute the reap and throw it
away; without the `expired`, the sweep would neither report the delta nor run
the pass that persists it.

- [ ] **Step 5: Delete the four in-lane demotions and assert the region is dry**

Immediately after the resume lane's closing `return`, before
`needs_new_work = latest is None or retryable`, add:

```python
    # Below this line an expired attempt is impossible: the reaper made it
    # `suspended` (auto-resumable, so the lane above always claims it) or
    # `stopped(stalled)` (claimed by the terminal check). A future edit that
    # reopens the path fails here rather than silently emitting an `expired`
    # delta from the wrong lane (per D6).
    assert not expired
```

Then, in the region below it, delete every `demote_expired_attempt` call and
pass `expired=False` from every return:

- the `needs_new_work and tracker is None` observe → `expired=False`;
- the `halt_reason is not None` branch → collapse it to
  `return decision("terminal", expired=False, tracker_reason=halt_reason,
  blockers=blockers)`, deleting the local `changed` variable and its
  `if expired:` demotion;
- the unobserved-forge observe → `expired=False`;
- the `retryable and latest["attempt"] >= 2` refuse lane → both returns become
  `expired=False`, and its `if expired: demote_expired_attempt(...)` is deleted;
- the `if not dispatch_permitted:` block → collapse to the single
  `return decision("idle", desired="retry" if retryable else "spawn",
  expired=False)`, deleting the `if expired:` arm entirely;
- the three `observe` returns in the worktree-selection region → `expired=False`;
- the final construction → delete `if expired and latest is not None:
  demote_expired_attempt(...)` and return `expired=False`.

`attempt_number = 2 if retryable else 1` and everything about `new_run`, the
attempt cap and the refuse lane's own semantics are untouched (spec, Out of
scope).

- [ ] **Step 6: Narrow `command_control`'s fallback persistence pass**

In `command_control`'s second pass, delete the `desired == "retry"` branch's
inner `elif analysis[issue]["expired"]: apply_policy(issue, False)` — `retryable`
and `expired` are now mutually exclusive, so it cannot execute — and guard the
outer fallback (per D7):

```python
            elif analysis[issue]["expired"] and issue not in planned:
                # The resume pass may already have dispatched this reap.
                # Re-planning it with dispatch withheld would replace that
                # resume with a suspension while the issue stayed in
                # `proposal_order`, and the {spawn, resume, retry} delta map
                # would then KeyError on "idle" (per D7).
                apply_policy(issue, False)
```

Nothing else in `command_control` changes: the `expired` delta loop already
reads the persisted state, `CONTROL_DELTA_KINDS` and `CONTROL_DISPATCH_KINDS`
stay as they are, and the resume pass's "round still owed" skip already tests
`attempt["state"] == "suspended"`, which a reaped attempt now satisfies.

- [ ] **Step 7: Verify**

```sh
python3 home/common/agent-skills/tests/test_workflow_state.py 2>&1 | tail -5
```
Expected: `OK`, 132 tests, zero failures and zero errors — the five new tests
pass, the four rewrites pass, and every retry-lane test driven by `fail_owner`
or `legacy_expiry_record`, every `expire(...)`-driven suspension test, and both
of #132's `check_launch` tests pass untouched.

Then pin the structural claims:

```sh
S=home/common/agent-skills/scripts/workflow-state.py
sites=$(grep -c "demote_expired_attempt(" "$S")
if [ "$sites" -ne 2 ]; then
  echo "expected the definition plus exactly one call site, found $sites"; exit 1
fi
if sed -n '/^    retryable = bool(/,/^    )$/p' "$S" | grep -q "expired"; then
  echo "retryable still folds in expired"; exit 1
fi
if ! grep -q "^    assert not expired$" "$S"; then
  echo "the below-the-lane guard is missing"; exit 1
fi
if ! grep -q 'elif analysis\[issue\]\["expired"\] and issue not in planned:' "$S"; then
  echo "the fallback persistence pass is unguarded"; exit 1
fi
```
Expected: no output, exit 0. At the commit this task starts from the first check
counts **5** and the other three all fail, so every gate is falsifiable.

- [ ] **Step 8: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py \
        home/common/agent-skills/tests/test_workflow_state.py
git commit -m "fix(issue-133): reap an expired attempt before any lane predicate"
```
Include the `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.
Never disable commit signing.
