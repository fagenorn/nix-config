# Task 5: Evidence, intervals, grants and the lapse-versus-renewal demo

**Files:**
- Modify: `python/agent_tools/transaction_custody.py`
- Modify: `python/agent_tools/transaction_core.py`
- Modify: `tests/test_transaction_custody.py` (append classes before `if __name__`)

**Interfaces:**
- Consumes (Tasks 3–4): `CUSTODY_EVENTS`, `self._check_custody(prior, custody, now)`,
  `_require_custody_shape`, `self._transaction_locked`, `self._now()`, `_format_at`,
  the v2 validator's per-type dispatch and `_EVENT_KEYS`, `GrantInvalid`, `renew`,
  `acquire`, `release`; test helpers `CustodyCase`, `plain`, `TTL`, `KEYS`, `PATH`.
- Produces, `transaction_custody`: `EVIDENCE_FORMS = ("event", "snapshot", "interval")`
  and the pure fold
  `admissibility(events: Sequence[Mapping[str, Any]]) -> tuple[list[dict], list[dict]]`.
- Produces, `transaction_core`: `Transaction` gains, after `custody`,
  `evidence: tuple[Mapping[str, Any], ...]` and `grants: tuple[Mapping[str, Any], ...]`;
  `TransactionStore.record_evidence(self, custody, *, evidence_id: str, form: str, reference: str) -> Transaction`;
  `TransactionStore.open_interval(self, custody, *, evidence_id: str) -> Transaction`;
  `TransactionStore.issue_grant(self, custody, *, grant_id: str, actor: str) -> Transaction`;
  `TransactionStore.check_grant(self, custody, grant_id: str) -> Mapping[str, Any]`.
  Task 7's executor calls the first two.

**Invariants:**
- New closed events: `evidence_recorded {seq, type, at, evidence_id, form, reference,
  fence}`, `interval_opened {seq, type, at, evidence_id, fence}`, `grant_issued {seq,
  type, at, grant_id, actor, fence}`; each `fence` equals the open span's fence (D10).
- Validator: each of the three sits inside an open custody span with an equal fence;
  `evidence_id` is unique across `evidence_recorded` and `interval_opened` except one
  `interval_opened` followed later by exactly one `evidence_recorded` of form `interval`
  and the same id; an `interval` record needs that earlier open; `grant_id` is unique.
- `evidence` entries (one per `evidence_recorded`, in `seq` order):
  `{evidence_id, form, reference, fence, seq, admissible, void_reason}`; `grants`
  entries: `{grant_id, actor, fence, seq, valid}`. *Latest fence* = the fence of the last
  `lease_acquired`/`lease_reacquired`. `event` → always admissible; `snapshot` →
  admissible iff fence == latest, else `fence_changed`; `interval` → a custody event with
  `seq` strictly between its `interval_opened` and its record is `fence_discontinuity`,
  else fence != latest is `fence_changed`, else admissible (D15, D20). A grant is `valid`
  iff its fence == latest and the last custody event is not a release or lapse (D16).
  Verdicts are derived on every load and never stored.
- All four operations run the fenced check under the transaction lock; a terminal
  refuses the three writers with `TransitionRefused` first; a reused id or closing an
  unopened interval is `StateInvalid` before any write (D27). `check_grant` writes
  nothing and raises `GrantInvalid` for an unknown grant or a fence that is not the
  presented one; it never re-stamps.
- Shape errors (`StateInvalid`, before any lock): ids, `reference` and `actor` not
  non-empty `str`; `form` not in `EVIDENCE_FORMS`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_transaction_custody.py`:

```python
class EvidenceTest(CustodyCase):
    def test_evidence_is_stamped_with_the_current_fence(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        after = self.store.record_evidence(custody, evidence_id="e1", form="snapshot",
                                           reference="evidence://a")
        event = dict(after.events[-1])
        self.assertEqual(set(event), {"seq", "type", "at", "evidence_id", "form",
                                      "reference", "fence"})
        self.assertEqual(event["fence"], plain(custody.fence))
        [entry] = after.evidence
        self.assertEqual(dict(entry), {
            "evidence_id": "e1", "form": "snapshot", "reference": "evidence://a",
            "fence": plain(custody.fence), "seq": 3, "admissible": True,
            "void_reason": None})
        self.assertEqual(TransactionStore(self.root).load(transaction_id).evidence,
                         after.evidence)

    def test_a_lapse_advances_the_epoch_and_voids_snapshots_while_renewal_does_neither(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        self.store.record_evidence(custody, evidence_id="s1", form="snapshot",
                                   reference="r")
        self.store.record_evidence(custody, evidence_id="e1", form="event", reference="r")
        self.store.open_interval(custody, evidence_id="i1")
        self.clock.advance(TTL // 2 + 1)
        self.store.renew(custody)
        self.store.record_evidence(custody, evidence_id="i1", form="interval",
                                   reference="r")
        self.store.issue_grant(custody, grant_id="g1", actor="publisher")
        renewed = self.store.load(transaction_id)
        self.assertEqual([e["admissible"] for e in renewed.evidence], [True, True, True])
        self.assertEqual([g["valid"] for g in renewed.grants], [True])
        self.assertEqual(self.store.check_grant(custody, "g1")["grant_id"], "g1")
        self.assertEqual((self.store.inspect_lease(KEYS[0])["epoch"],
                          self.store.inspect_lease(KEYS[0])["holder"]["term"]), (1, 2))
        self.assertEqual([t for t in self.types(transaction_id) if t.startswith("lease_")],
                         ["lease_acquired"])

        self.clock.advance(TTL)
        successor = self.acquire(transaction_id, executor="exec-b")
        self.assertEqual(self.store.inspect_lease(KEYS[0])["epoch"], 2)
        lapsed = self.store.load(transaction_id)
        self.assertEqual([(e["evidence_id"], e["admissible"], e["void_reason"])
                          for e in lapsed.evidence],
                         [("s1", False, "fence_changed"), ("e1", True, None),
                          ("i1", False, "fence_changed")])
        self.assertEqual([g["valid"] for g in lapsed.grants], [False])
        self.assertRefusedUnchanged(GrantInvalid,
                                    lambda: self.store.check_grant(successor, "g1"))
        self.assertRefusedUnchanged(StaleCustody,
                                    lambda: self.store.check_grant(custody, "g1"))

    def test_an_interval_broken_by_a_custody_event_reads_fence_discontinuity(self):
        transaction_id = self.new()
        first = self.acquire(transaction_id)
        self.store.open_interval(first, evidence_id="i1")
        self.store.release(first)
        second = self.acquire(transaction_id)
        self.store.record_evidence(second, evidence_id="i1", form="interval", reference="r")
        self.store.open_interval(second, evidence_id="i2")
        after = self.store.record_evidence(second, evidence_id="i2", form="interval",
                                           reference="r")
        self.assertEqual([(e["evidence_id"], e["admissible"], e["void_reason"])
                          for e in after.evidence],
                         [("i1", False, "fence_discontinuity"), ("i2", True, None)])

    def test_a_released_span_invalidates_its_grants(self):
        custody = self.acquire(self.new())
        self.store.issue_grant(custody, grant_id="g1", actor="a")
        self.assertEqual([g["valid"] for g in self.store.release(custody).grants], [False])

    def test_reused_ids_and_unopened_intervals_are_refused_before_any_write(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        self.store.record_evidence(custody, evidence_id="e1", form="event", reference="r")
        self.store.open_interval(custody, evidence_id="i1")
        self.store.issue_grant(custody, grant_id="g1", actor="a")
        for call in (
                lambda: self.store.record_evidence(custody, evidence_id="e1", form="event",
                                                   reference="r"),
                lambda: self.store.open_interval(custody, evidence_id="e1"),
                lambda: self.store.open_interval(custody, evidence_id="i1"),
                lambda: self.store.record_evidence(custody, evidence_id="e1",
                                                   form="interval", reference="r"),
                lambda: self.store.record_evidence(custody, evidence_id="i1",
                                                   form="snapshot", reference="r"),
                lambda: self.store.issue_grant(custody, grant_id="g1", actor="a"),
                lambda: self.store.record_evidence(custody, evidence_id="x", form="guess",
                                                   reference="r"),
                lambda: self.store.record_evidence(custody, evidence_id="", form="event",
                                                   reference="r"),
                lambda: self.store.issue_grant(custody, grant_id="g2", actor="")):
            self.assertRefusedUnchanged(StateInvalid, call)
        self.assertRefusedUnchanged(GrantInvalid,
                                    lambda: self.store.check_grant(custody, "nope"))
        self.assertTrue(issubclass(GrantInvalid, FenceViolation))

    def test_stale_or_terminal_writers_are_refused_before_any_write(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        writes = (
            lambda: self.store.record_evidence(custody, evidence_id="s", form="snapshot",
                                               reference="r"),
            lambda: self.store.open_interval(custody, evidence_id="i"),
            lambda: self.store.issue_grant(custody, grant_id="g", actor="a"))
        self.clock.advance(TTL)
        for call in writes:
            self.assertRefusedUnchanged(StaleCustody, call)
        custody = self.acquire(transaction_id)
        self.store.advance(transaction_id, "abandoned", reason="r", external_state="known",
                           custody=custody)
        for call in writes:
            self.assertRefusedUnchanged(TransitionRefused, call)

    def test_hand_edited_evidence_histories_are_state_invalid(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        self.store.open_interval(custody, evidence_id="i1")
        self.store.record_evidence(custody, evidence_id="i1", form="interval", reference="r")
        self.store.issue_grant(custody, grant_id="g1", actor="a")
        base = self.state_doc(transaction_id)
        created, acquired, opened, closed, granted = base["events"]
        foreign = {k: {**v, "epoch": 9} for k, v in opened["fence"].items()}

        def events(*replacement):
            return lambda d: {**d, "events": [created, *replacement],
                              "revision": 1 + len(replacement)}

        cases = {
            "evidence outside a span": events({**closed, "seq": 2, "form": "snapshot"}),
            "foreign fence": events(acquired, {**opened, "fence": foreign}, closed, granted),
            "close without open": events(acquired, {**closed, "seq": 3}),
            "duplicate grant": events(acquired, opened, closed, granted,
                                      {**granted, "seq": 6}),
            "unknown form": events(acquired, opened, {**closed, "form": "guess"}, granted),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                (self.root / transaction_id / "state.json").write_text(
                    serialize(mutate(copy.deepcopy(base))))
                with self.assertRaises(StateInvalid):
                    self.store.load(transaction_id)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_custody.py 2>&1 | tail -3`
Expected: FAIL — `AttributeError: 'TransactionStore' object has no attribute 'record_evidence'`.

- [ ] **Step 3: Write the minimal implementation**

1. `admissibility(events)` in `transaction_custody`, pure (no I/O): one pass collecting
   custody-event `seq`s, the latest fence, whether the last custody event closes a span,
   each `interval_opened` seq by id, then the entries per the invariants. It returns
   fresh dicts; `_snapshot` wraps each in `MappingProxyType` inside a tuple.
2. Extend `_EVENT_KEYS` and the validator dispatch with the three types and the rules
   above. A write-time duplicate or unopened-interval check runs before building the
   candidate so its message names the id; the validator stays the backstop.
3. The four operations share one private helper that performs: shape checks → lock →
   `prior` → (writers) terminal refusal → `now` → `_check_custody` → operation rule →
   append one event stamped `_format_at(now)` with `fence = plain(prior custody fence)`
   → validate → `atomic_write`. `check_grant` stops after `_check_custody`, finds the grant
   in `admissibility(prior["events"])`, and returns it as a `MappingProxyType` when its
   fence equals the presented fence, else raises `GrantInvalid` naming the id.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_custody.py tests/test_transaction_core.py tests/test_transaction_core_sweep.py 2>&1 | tail -3`
Expected: `OK` (Task 4 count + 7 tests).

Run: `PYTHONPATH=python python3 -m unittest tests.test_transaction_custody.EvidenceTest.test_a_lapse_advances_the_epoch_and_voids_snapshots_while_renewal_does_neither 2>&1 | tail -1`
Expected: `OK` (the #205 demo).

Run: `just agent-workflow-tests 2>&1 | tail -3` — Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/transaction_custody.py python/agent_tools/transaction_core.py \
  tests/test_transaction_custody.py
git commit -m "feat(transaction-core): fence evidence, intervals and grants (#205)"
```
