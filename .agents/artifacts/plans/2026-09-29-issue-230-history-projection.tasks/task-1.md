# Task 1: Centralize complete history construction and migrate every writer

Read the plan root's Global Constraints and the linked specification before
editing. This is one full-risk task governed by D1–D4.

**Files:**
- Modify: `python/agent_tools/transaction_history.py`
- Modify: `python/agent_tools/transaction_core.py`
- Test: `tests/test_transaction_custody.py`
- Test: `tests/test_transaction_core.py`

**Interfaces:**
- Retain `validate_state(document: Any, transaction_id: str,
  indexed: Callable[[str], str | None]) -> None`, `snapshot(document: dict) ->
  Transaction` and every `TransactionStore` public signature.
- Add history-private `_history_projection(document: dict, transaction_id: str)
  -> tuple[str, str | None, dict | None, int]`, ordered as state, parked origin,
  custody, revision. It consumes admitted document metadata plus the candidate
  history; it never consumes the stored four projections as truth.
- Add history `append_events(prior: dict, event_fields: list[dict], *, at: str)
  -> dict`. `prior` is the store's validated document under its transaction lock;
  fields have neither `seq` nor `at`; `at` is the store's one formatted timestamp.
  The result is a complete detached document with a validated history.
- Replace internal history `reaped(document, at, reason) -> dict` with
  `reap_events(document: dict, reason: str) -> list[dict]` returning only fields.
- Retain the name `owner_result_event`, changing its internal signature to
  `owner_result_event(document: dict, *, executor_id: str, fence: dict,
  result: dict, lapsed: bool) -> dict`; remove `at` and return fields without
  envelopes. Update the only core caller and imports. These are internal recipes,
  not additions to the store's public surface.

**Invariants:**
- The five mutation recipes assign neither document projections nor event
  envelopes; event payload `owner_result.custody` remains valid recipe data.
- The constructor deep-copies both prior content and appended field data,
  assigns contiguous sequences after the existing events and the passed `at`,
  walks once, then installs all four returned projections in one location.
- Stored validation's existing metadata/index checks precede the shared walk;
  its projection checks follow the walk in state/parking/custody/revision order.
- Event dispatch, fold state, prefixes given to subordinate rules, trailing
  pairing and terminal-custody validation retain their current order.
- Recipe event order and all existing admission/effect boundaries remain exact;
  no-op reap/renewal does not construct or rewrite a document.

- [ ] **Step 1: Strengthen the existing mutation round-trip assertions.**

Add `import datetime` to `tests/test_transaction_custody.py`. Add the following
methods to its existing `CustodyCase`; these inspect only accepted store/layout
seams. The expected values at each call below are handwritten; this helper does
not derive any projection from events.

```python
    def expected_event(self, seq, kind, **fields):
        at = datetime.datetime.fromtimestamp(
            self.clock.now / 1000, datetime.timezone.utc).isoformat(
                timespec="milliseconds").replace("+00:00", "Z")
        return {"seq": seq, "type": kind, "at": at, **fields}

    def assertStoredProjection(self, after, *, state, parked_from, custody,
                               revision, tail):
        transaction_id = after.transaction_id
        held = None if custody is None else {
            "executor_id": custody.executor_id, "subject_path": custody.subject_path,
            "fence": plain(custody.fence)}
        expected = {"state": state, "parked_from": parked_from,
                    "custody": held, "revision": revision}
        document = self.state_doc(transaction_id)
        self.assertEqual({key: document[key] for key in expected}, expected)
        loaded = TransactionStore(self.root, clock=self.clock).load(transaction_id)
        for snapshot in (after, loaded):
            self.assertEqual((snapshot.state, snapshot.parked_from,
                              snapshot.custody, snapshot.revision),
                             (state, parked_from, custody, revision))
            self.assertEqual([dict(event) for event in snapshot.events],
                             document["events"])
        self.assertEqual(len(document["events"]), revision)
        self.assertEqual([event["seq"] for event in document["events"]],
                         list(range(1, revision + 1)))
        self.assertEqual(document["events"][-len(tail):], tail)
```

Preserve existing assertions and extend these exact tests at the indicated
point, before any later mutation/clock change. Each code block is the full
addition at that point.

In `AcquireTest.test_a_first_acquisition_grants_epoch_one_and_appends_one_event`,
after the existing state-custody assertion:

```python
        self.assertStoredProjection(
            after, state="created", parked_from=None, custody=custody, revision=2,
            tail=[self.expected_event(2, "lease_acquired", executor_id="exec-a",
                                      subject_path=PATH, fence=plain(custody.fence))])
```

In `AcquireTest.test_release_keeps_the_epoch_and_every_reacquisition_advances_it`,
immediately after `released = self.store.release(first)`:

```python
        self.assertStoredProjection(
            released, state="created", parked_from=None, custody=None, revision=3,
            tail=[self.expected_event(3, "lease_released", fence=plain(first.fence),
                                      reason="released")])
```

In that same test replace `second = self.acquire(transaction_id, executor="exec-b")`
with this code, retaining the remaining existing checks:

```python
        second_snapshot = self.store.acquire(
            transaction_id, executor_id="exec-b", subject_path=PATH, ttl_ms=TTL)
        second = second_snapshot.custody
        self.assertStoredProjection(
            second_snapshot, state="created", parked_from=None, custody=second,
            revision=4, tail=[self.expected_event(
                4, "lease_reacquired", executor_id="exec-b", subject_path=PATH,
                fence=plain(second.fence), prior_executor_id="exec-a",
                prior_fence=plain(first.fence), reason="released")])
```

In `AcquireTest.test_acquisition_over_an_unreaped_lapse_records_the_lapse_first`,
replace its `second = self.acquire(...)` with this code and retain existing checks:

```python
        second_snapshot = self.store.acquire(
            transaction_id, executor_id="exec-b", subject_path=PATH, ttl_ms=TTL)
        second = second_snapshot.custody
        self.assertStoredProjection(
            second_snapshot, state="created", parked_from=None, custody=second,
            revision=4, tail=[
                self.expected_event(3, "lease_lapse_detected",
                                    fence=plain(first.fence), executor_id="exec-a"),
                self.expected_event(4, "lease_reacquired", executor_id="exec-b",
                                    subject_path=PATH, fence=plain(second.fence),
                                    prior_executor_id="exec-a",
                                    prior_fence=plain(first.fence), reason="expired")])
```

In `QuiesceTest.test_parked_custody_is_renewed_up_to_the_window_then_quiesced`,
immediately after its `after = self.store.renew(custody)`:

```python
        self.assertStoredProjection(
            after, state="attention_required", parked_from="created", custody=None,
            revision=4, tail=[self.expected_event(
                4, "lease_released", fence=plain(custody.fence), reason="quiesced")])
```

Add this complete test to `EvidenceTest` to cover transition, ordinary
non-transition append, parking/resume and terminal-release envelopes together:

```python
    def test_append_projections_round_trip_through_parking_and_terminal_release(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        fence = plain(custody.fence)
        after = self.store.advance(transaction_id, "awaiting_verification",
                                   reason="verify", custody=custody)
        self.assertStoredProjection(
            after, state="awaiting_verification", parked_from=None,
            custody=custody, revision=3, tail=[self.expected_event(
                3, "transitioned", **{"from": "created", "to": "awaiting_verification",
                                      "reason": "verify", "external_state": None})])
        after = self.store.record_evidence(custody, evidence_id="e1", form="snapshot",
                                           reference="evidence://a")
        self.assertStoredProjection(
            after, state="awaiting_verification", parked_from=None,
            custody=custody, revision=4, tail=[self.expected_event(
                4, "evidence_recorded", evidence_id="e1", form="snapshot",
                reference="evidence://a", fence=fence)])
        after = self.store.advance(transaction_id, "attention_required", reason="wait",
                                   custody=custody)
        self.assertStoredProjection(
            after, state="attention_required", parked_from="awaiting_verification",
            custody=custody, revision=5, tail=[self.expected_event(
                5, "transitioned", **{"from": "awaiting_verification",
                                      "to": "attention_required", "reason": "wait",
                                      "external_state": None})])
        after = self.store.advance(transaction_id, "awaiting_verification", reason="resume",
                                   custody=custody)
        self.assertStoredProjection(
            after, state="awaiting_verification", parked_from=None,
            custody=custody, revision=6, tail=[self.expected_event(
                6, "transitioned", **{"from": "attention_required",
                                      "to": "awaiting_verification", "reason": "resume",
                                      "external_state": None})])
        after = self.store.advance(transaction_id, "abandoned", reason="done",
                                   external_state="known", custody=custody)
        self.assertStoredProjection(
            after, state="abandoned", parked_from=None, custody=None, revision=8,
            tail=[self.expected_event(
                7, "transitioned", **{"from": "awaiting_verification", "to": "abandoned",
                                      "reason": "done", "external_state": "known"}),
                  self.expected_event(8, "lease_released", fence=fence, reason="terminal")])
        for key in KEYS:
            self.assertIsNone(self.store.inspect_lease(key)["holder"])
```

- [ ] **Step 2: Pin reap and owner-result projections while retaining their lease evidence.**

In `ReapTest.test_reaping_a_lapse_parks_with_a_synthesized_stop_once`, after the
initial clock advance and before reaping, capture the existing lease bytes:

```python
        leases_before = {key: self.lease_path(key).read_bytes() for key in KEYS}
```

Immediately after its first `reaped = self.store.reap(...)`, add:

```python
        self.assertStoredProjection(
            reaped, state="attention_required", parked_from="proving", custody=None,
            revision=10, tail=[
                self.expected_event(8, "lease_lapse_detected",
                                    fence=plain(custody.fence), executor_id="exec-a"),
                self.expected_event(9, "stop_synthesized", fence=plain(custody.fence),
                                    executor_id="exec-a", reason="lease expired"),
                self.expected_event(10, "transitioned", **{
                    "from": "proving", "to": "attention_required",
                    "reason": "lease expired", "external_state": "unknown"})])
        self.assertEqual({key: self.lease_path(key).read_bytes() for key in KEYS},
                         leases_before)
```

Keep this test's existing repeated-reap byte equality and stale-writer refusals.
In `ReapTest.test_reaping_a_parked_lapse_adds_no_transition`, after the clock
advance and before reaping, create a successor that shares a key and capture
all lease files after it acquires:

```python
        successor = self.new("successor", keys=("project:alpha", "target:beta"))
        taken = self.acquire(successor, executor="exec-b", path="/work/beta")
        lease_keys = ("project:alpha", "target:alpha", "target:beta")
        leases_before = {key: self.lease_path(key).read_bytes() for key in lease_keys}
```

After its `reaped = self.store.reap(...)`, add:

```python
        self.assertStoredProjection(
            reaped, state="attention_required", parked_from="created", custody=None,
            revision=5, tail=[
                self.expected_event(4, "lease_lapse_detected",
                                    fence=plain(custody.fence), executor_id="exec-a"),
                self.expected_event(5, "stop_synthesized", fence=plain(custody.fence),
                                    executor_id="exec-a", reason="lease expired")])
        self.assertEqual({key: self.lease_path(key).read_bytes() for key in lease_keys},
                         leases_before)
        self.assertEqual(self.store.load(successor).custody, taken)
        before = self.files()
        self.assertEqual(self.store.reap(transaction_id, reason="again"), reaped)
        self.assertEqual(self.files(), before)
```

In `OwnerResultTest.test_a_late_authentic_result_is_kept_beside_the_synthesized_stop`,
between its `stop = ...` and `after = self.late(...)`, acquire a successor and
capture its lease records:

```python
        successor = self.new("successor", keys=("project:alpha", "target:beta"))
        taken = self.acquire(successor, executor="exec-b", path="/work/beta")
        lease_keys = ("project:alpha", "target:alpha", "target:beta")
        leases_before = {key: self.lease_path(key).read_bytes() for key in lease_keys}
```

Immediately after `after = self.late(...)`, add:

```python
        self.assertStoredProjection(
            after, state="attention_required", parked_from="proving", custody=None,
            revision=11, tail=[self.expected_event(
                11, "owner_result", executor_id="exec-a", fence=plain(custody.fence),
                custody="stale", supersedes=9, result={"status": "done", "items": [1, 2]})])
        self.assertEqual({key: self.lease_path(key).read_bytes() for key in lease_keys},
                         leases_before)
        self.assertEqual(self.store.load(successor).custody, taken)
```

Replace `OwnerResultTest.test_a_result_under_live_custody_is_current` with this
complete body, retaining the original current-result assertions and adding a
lapsed, unreaped result. This is an existing scenario extended at the same seam:

```python
    def test_a_result_under_live_custody_is_current(self):
        transaction_id, custody = self.proving()
        leases_before = {key: self.lease_path(key).read_bytes() for key in KEYS}
        after = self.late(transaction_id, custody)
        self.assertStoredProjection(
            after, state="proving", parked_from=None, custody=custody, revision=8,
            tail=[self.expected_event(
                8, "owner_result", executor_id="exec-a", fence=plain(custody.fence),
                custody="current", supersedes=None,
                result={"status": "done", "items": [1, 2]})])
        event = after.events[-1]
        self.assertEqual((event["custody"], event["supersedes"]), ("current", None))
        self.assertEqual(self.store.load(transaction_id).custody, custody)
        self.clock.advance(TTL)
        after = self.late(transaction_id, custody)
        self.assertStoredProjection(
            after, state="proving", parked_from=None, custody=custody, revision=9,
            tail=[self.expected_event(
                9, "owner_result", executor_id="exec-a", fence=plain(custody.fence),
                custody="stale", supersedes=None,
                result={"status": "done", "items": [1, 2]})])
        self.assertEqual({key: self.lease_path(key).read_bytes() for key in KEYS},
                         leases_before)
```

- [ ] **Step 3: Pin corruption refusal precedence and unchanged damaged bytes.**

Add this complete test to `LoadTest` in `tests/test_transaction_core.py` using
its existing imports and `StoreCase` helpers. Each row starts with a valid
stored parked transaction and supplies competing faults explicitly.

```python
    def test_history_and_projection_faults_keep_their_refusal_order(self):
        transaction_id = self.store.create(
            "precedence", SUBJECT, concurrency_keys=KEYS, proof=EMPTY_PROOF,
            recovery=EMPTY_RECOVERY).transaction_id
        self.store.advance(transaction_id, "attention_required", reason="wait")
        base = self.document(transaction_id)
        faults = {"state": "ready", "parked_from": "ready",
                  "custody": {"executor_id": "forged"}, "revision": True}
        cases = [
            ({**faults, "schema": "broken"}, True,
             "schema 'broken' is not transaction-state/v5"),
            (faults, True, "event 2 does not carry seq 2"),
            (faults, False, "state does not equal the folded state attention_required"),
            ({key: value for key, value in faults.items() if key != "state"},
             False, "parked_from does not equal the folded parked_from"),
            ({"custody": faults["custody"], "revision": True},
             False, "custody does not equal the folded custody"),
            ({"revision": True}, False, "revision does not equal the number of events"),
            ({"revision": 99}, False, "revision does not equal the number of events"),
        ]
        for updates, gap, message in cases:
            with self.subTest(message=message, updates=updates):
                damaged = copy.deepcopy(base)
                damaged.update(copy.deepcopy(updates))
                if gap:
                    damaged["events"][1]["seq"] = 99
                self.write(transaction_id, damaged)
                raw = self.state_path(transaction_id).read_bytes()
                with self.assertRaises(StateInvalid) as caught:
                    TransactionStore(self.root).load(transaction_id)
                self.assertEqual(str(caught.exception), f"{transaction_id}: {message}")
                self.assertEqual(self.state_path(transaction_id).read_bytes(), raw)
        self.write(transaction_id, base)
        self.assertEqual(self.store.load(transaction_id).parked_from, "created")
```

- [ ] **Step 4: Establish the red structural gate before changing production.**

Run `PYTHONPATH=python python3 -m unittest -q tests/test_transaction_core.py
tests/test_transaction_custody.py`. The added behavior characterizations are
expected to pass at baseline: this task changes ownership of rules, not public
behavior. Do not invent a behavioral failure or add an internal helper test.
Then run this source-inspection gate from the worktree; it supplies the required
failure before the refactor. Planning ran this exact gate at `3c4abea`: exit 1
reported independent projection assignments, recipe envelopes and candidate
revalidation in both owned production files.

```sh
python3 - <<'PY'
import ast
from pathlib import Path
fields = {'state', 'parked_from', 'custody', 'revision'}
selections = {
    'python/agent_tools/transaction_core.py': {
        '_append', '_acquisition', '_released', 'reap', 'record_owner_result'},
    'python/agent_tools/transaction_history.py': {'reaped', 'reap_events', 'owner_result_event'},
}
findings = []
for filename, names in selections.items():
    tree = ast.parse(Path(filename).read_text())
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef) or function.name not in names:
            continue
        for node in ast.walk(function):
            if (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store)
                    and isinstance(node.slice, ast.Constant) and node.slice.value in fields):
                findings.append(f'{filename}:{node.lineno}: recipe assigns {node.slice.value}')
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and key.value in {'seq', 'at'}:
                        findings.append(f'{filename}:{key.lineno}: recipe supplies {key.value}')
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in {'_validate_state', 'validate_state'}):
                findings.append(f'{filename}:{node.lineno}: recipe revalidates its candidate')
if findings:
    raise SystemExit('\n'.join(findings))
print('Recipe source gate passed; inspect the shared walk and call graph separately.')
PY
```

This bounded inspection is not a new unit-test seam. It catches the current
duplication; human source review below also catches alternate assignment syntax,
renamed duplicate reducers or hidden extra walks that this syntactic gate cannot.

- [ ] **Step 5: Extract the authoritative validating walk (D1, D2).**

Implement `_history_projection` in `transaction_history.py`. Move, in order,
the existing `events = document["events"]` block through the final
`terminal state ... still holds custody` check out of `validate_state`.
Initialize `keys` from the admitted document and use the same
`StateInvalid(f"{transaction_id}: {rule}")` messages. Return state, parked,
folded custody and `len(events)`. Keep `_CustodyFold`, actions and `ProofFold`
local to this walk. Do not introduce a second transition/custody algorithm.

Leave all document/schema/identity/plan/index/subject/concurrency checks in
`validate_state` in their original order, then call `_history_projection`.
Keep its four strict comparisons in their existing order and with their
existing type checks and exact messages, using the returned revision in the
last comparison. In particular, boolean revisions are invalid.

Preserve each helper's current position relative to `_fold_transitioned`,
terminal action refusal, recovery transition checks, action application,
proof evidence-id checks and proof application. Pass the same event prefixes,
folded state and open fence. The recovery validator reads immutable document
plans/identity and takes folded state/fence explicitly; do not pre-install
candidate projections to accommodate it or change its interface. Keep the
existing full stored validator in the creation path.

- [ ] **Step 6: Add detached complete-document construction and field recipes (D1–D3).**

Implement `append_events` with the interface above. Deep-copy `prior` and
event fields; extend only the copied event list, assigning `seq` from its
existing length and `at` from the supplied timestamp. Call `_history_projection`
once and install exactly its four results in the candidate. Do not call
`validate_state`, an index callback, the clock, a lease authority or a store
method. The internal caller contract guarantees admitted immutable metadata;
history validation still checks the full resulting event list, including
creation-event envelopes/digests and every newly appended event.

Replace `reaped` with `reap_events`: held-custody lapse fields first, synthesized
stop with the same fence/executor and supplied reason second, then only outside
`PARKINGS` a transition from the prior state to `attention_required` with
external state `unknown`. It returns fields, assigns no projections and has
no `at` or `seq`. Update `owner_result_event` to omit those two envelope fields
and its `at` argument, preserving current/stale judgment, latest matching stop
sequence in `supersedes`, result copying and all event payload fields.

- [ ] **Step 7: Migrate ordinary append and terminal release (D3).**

In core `_append`, copy the supplied field list for recipe composition. Capture
the prior custody fence. Determine terminal release from an explicit
`transitioned` event whose `to` is in `TERMINALS`; do not simulate state or
parking changes. When that recipe reaches a terminal under custody, append
the existing `lease_released` fields with reason `terminal` last, before the
constructor runs. Preserve a single `format_at(now)` timestamp across the recipe.

Construct through `append_events`, then retain the current write/lease-lock
branches: terminal release writes the candidate before clearing the old fence;
non-releasing append writes state alone. Remove candidate projection mutations,
event-envelope composition and the subsequent full `_validate_state` call.
Do not move `_append_fenced`'s evidence-id check or any callers' admission checks.

- [ ] **Step 8: Migrate acquisition and release/quiesce (D3).**

In `_acquisition`, retain own-span liveness refusal before `first_live_key`,
then obtain `next_fence` at the existing point. Build fields only. A lapsed
held span contributes `lease_lapse_detected` before the opening; choose the
opening's prior span and expired/released reason using prior events plus that
selected lapse. No candidate custody/revision assignment remains. Return
`append_events(prior, fields, at=format_at(now))`. `acquire` must still hold
leases using the fully constructed candidate's fence before writing state.

In `_released`, construct one release event using the prior fence and existing
reason. Preserve state-write then clear, inside both already acquired locks.
Keep `release` and `renew` admission and quiesce decisions unchanged. A renewal
that does not quiesce continues to return the prior snapshot without history.

- [ ] **Step 9: Migrate reap and late owner results (D3).**

`reap` keeps its existing validated load, terminal/no-custody/live-span no-ops
and clock/lapse judgment. Feed `reap_events(prior, reason)` to `append_events`
with `format_at(now)`, then perform the existing state-only write. It neither
takes custody nor clears lease records.

`record_owner_result` keeps argument, terminal, issued-span and bound-path checks
in order. Preserve the store's `span_lapsed` judgment at the same clock reading.
Pass the event fields from `owner_result_event` in a one-element list to
`append_events`, followed by the existing state-only write. Remove its manual
revision update and candidate validation. Do not change #229's `_capture_result`
or external callback result handling anywhere else in core.

Update the affected module/function documentation to name the real final
constructor, walk and recipe boundaries. Keep creation, storage, leases and
action/proof/recovery rule implementations outside this edit.

- [ ] **Step 10: Verify runtime compatibility and inspect the structural guarantee.**

Run the Step 4 focused command and source gate again; both must exit 0. The
characterizations must show every changed writer returns/stores/reloads the
expected projections, envelopes, order and custody; damaged documents must
retain their bytes and report the expected first refusal.

Run the complete focused transaction suite (quiet output):

```sh
PYTHONPATH=python python3 -m unittest -q \
  tests/test_transaction_core.py tests/test_transaction_custody.py \
  tests/test_transaction_invocation.py tests/test_transaction_plan.py \
  tests/test_transaction_proof.py tests/test_transaction_recovery_plan.py \
  tests/test_transaction_recovery.py tests/test_transaction_recovery_settle.py \
  tests/test_transaction_core_sweep.py
```

Expected: all tests pass, including the prior 281 focused tests plus additions;
do not assert an exact count. This retains action/proof/recovery, result ownership,
refused-without-write, lock contention, terminal/recovery pairing, store sweep,
snapshot independence and source neutrality regressions.

Inspect the diff and call graph with bounded reads and record the evidence:

- Exactly one authoritative event walk supplies construction and stored
  comparison. Its pre-walk/post-walk refusal order matches the prior validator.
- All five writers receive complete candidates from `append_events`; no hidden
  manual assignments, envelope numbering or independent reducer survives.
- Candidate construction performs that walk once, with no later full validator;
  prior admission validation is preserved. Snapshot's pre-existing derived views
  are unchanged and are not a newly added candidate-validation pass.
- Inputs are detached before modification; no constructor mutation can reach
  the prior or recipe data. Loading never normalizes tampered projections.
- Trace the existing transaction/lease locks and durable calls: acquire holds
  before state save; release/quiesce/terminal save before clear; reap/result save
  only; unchanged operations write nothing. No write moved ahead of checking.
- `git diff --stat 6d7a0b3a47d5a480e1540ce1931dd012f5f1ad0b -- python/agent_tools/transaction_history.py python/agent_tools/transaction_core.py tests/test_transaction_custody.py tests/test_transaction_core.py`
  covers only this task's files. Read their actual diff; no unscoped range or
  exact changed-file/commit-count gate applies.

Then run the resolved verification entries from this worktree:

```sh
just agent-workflow-tests > /tmp/issue-230-agent-workflow-tests.log 2>&1
```

Capture the exit status before inspecting `tail -n 8` of that log; require exit 0,
not merely a passing-looking tail. Repeat that pattern for `just build` using
`/tmp/issue-230-build.log`; require exit 0. Report failures from the relevant
bounded log ranges, fix within scope and rerun affected checks. Neither command
activates the configuration. Do not claim implementation results from the
baseline or broaden testing again after final required checks pass unless code
changes or new concerns justify it.

- [ ] **Step 11: Commit the complete, verified refactor.**

```sh
git add python/agent_tools/transaction_history.py python/agent_tools/transaction_core.py \
  tests/test_transaction_custody.py tests/test_transaction_core.py
git commit -S -m "refactor(transaction): derive candidates from shared history rules" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```

Keep signing enabled; request the authorized Git metadata escalation if the
sandbox blocks it. Report changed behavior (none intended), test results and
source/order evidence to the task reviewer. Do not ship or acquire lifecycle
ownership from this task.
