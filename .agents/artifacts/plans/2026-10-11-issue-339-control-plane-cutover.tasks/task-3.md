# Task 3: Control reads occupancy and the capacity gate from the store

`command_control` stops deciding slot occupancy and the `host_capacity` gate from the ledger's `admission` block alone: it takes one lock-free view of the store at its locked read, and the store wins a disagreement. Replies are the base's whenever the two agree. Read the root's Global Constraints first. Decisions: D1, D4, D12, D23.

**Files:**
- Modify: `python/agent_tools/attempt_store.py`
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`command_control` only)
- Modify: `home/common/agent-skills/tests/test_control_cutover.py` (add)

**Interfaces:**
- Consumes: `attempt_custody.launch_fence`, `claimed`, `claim_roles`, `span_lapsed`, `gate_open`; `custody_of`, `remainder_custody_of`; the `Cutover` mixin.
- Produces in `agent_tools.attempt_store`:

```python
class LaunchView(NamedTuple):
    """The store's view of one record's current launch. `spanned`: the core ever gave it
    a span. `open`: that span is the transaction's open span and has not lapsed. `roles`:
    the claim entry's role set, None when not open or unclaimed. `parked`: the
    transaction is `attention_required`."""

    spanned: bool
    open: bool
    roles: dict[str, int] | None
    parked: bool


def launch_views(store: Path, state: dict, *, now_ms: int) -> dict[str, LaunchView]:
    """A view per current launch of each issue's last attempt and last remainder that has
    a custody transaction, keyed by launch id. Lock-free and read-only; a core error is a
    `StoreFault`."""
```

**Invariants:**
- `command_control` calls `launch_views` once, on the state as read, after `stamp_request` and before it changes `state`, with `now_ms=at_ms(request["now"])`.
- **Occupancy.** A launch occupies only while it is the current launch of an `active` record in the sweep's own state and the request does not report its owner unavailable, so a launch this sweep refuses, reaps or supersedes frees its slot in the same sweep, as at the base. For such a launch: when its view is `spanned` and not (`open` with `roles` None), the store decides, and it occupies with `view.roles` exactly when `view.open`. Otherwise (no view, a launch the store never gave a span, an open span with no claim entry) the ledger decides as at the base: it occupies with the block's held claim for it when `runtime.live_launches` names it. `available` before the lanes and `reserved`/`available` in the reply both use this rule, plus the controller's claim, which stays a block fact.
- **The gate.** For a record suspended on `host_capacity` with current launch `holder`: when this sweep recorded the refusal, or `holder` has no view, the base's rule applies unchanged (`gate_open` over the block, with the `internal error` for a missing refused claim). Otherwise the store decides: not `parked` means it may resume; `parked` means it waits unless this sweep itself released a claim by an event other than `launch_refused` (a `release_seq` above the block's `releases` at the start of the sweep).
- `waiting`, the lane order, `max_parallel`, the claims this sweep acquires and every reply field are computed as before. A sweep that changes nothing writes nothing.

- [ ] **Step 1: Write the failing tests**

Append to `home/common/agent-skills/tests/test_control_cutover.py`:

```python
class StoreReadTest(Cutover, unittest.TestCase):
    def test_ac1_occupancy_is_counted_from_the_store(self):
        self.four_slots()

        def drop(document):
            claims = document["admission"]["claims"]
            claims[:] = [c for c in claims if c["holder"] != f"{DELIVERED}:1:1"]

        self.rewrite(drop)
        report = self.reply(1, recorded={DELIVERED: "matching_issue_branch", LIVE: None},
                            contracts=True)["admission"]
        self.assertEqual((report["waiting"], report["reserved"], report["available"]),
                         ([LIVE], {"controller": 1, **ROLES}, 0))
        self.assertIsNone(self.custody(LIVE))

    def test_the_capacity_gate_is_read_from_the_store(self):
        self.spawn(DELIVERED, LIVE)
        self.reply(1, recorded=BOTH, owners=[self.held("launch_refused")])
        self.failing(f"{DELIVERED}:1:1", 3)

        def swap(document):  # by the block alone, the refusal now came last
            claims = {c["holder"]: c for c in document["admission"]["claims"]}
            freed, refused = claims[f"{DELIVERED}:1:1"], claims[f"{LIVE}:1:1"]
            freed["release_seq"], refused["release_seq"] = (refused["release_seq"],
                                                            freed["release_seq"])

        self.rewrite(swap)
        resumed = self.reply(4, recorded=BOTH)
        self.assertNotIn(LIVE, resumed["admission"]["waiting"])
        self.assertIn(f"{LIVE}:1:2", self.launched(resumed))
```

- [ ] **Step 2: Run them and watch them fail**

Run: `PYTEST T/test_control_cutover.py -k StoreReadTest`
Expected: FAIL, 2 tests: `([], {...}, 0) != ([209], {...}, 0)` (209 is admitted into a slot the store shows taken) and `209 unexpectedly found in [209]` (the block gates a suspension the store shows woken).

- [ ] **Step 3: Implement**

Add `LaunchView` and `launch_views`; replace the three ledger-only computations in `command_control` (the `available` sum, `refusal_gated`, the `reserved` sum of the admission report). One local function serves both sums. `refusal_gated`'s docstring states the rule as built.

- [ ] **Step 4: Verify**

Run: `PYTEST T/test_control_cutover.py T/test_control_decisions.py T/test_admission_replay.py T/test_host_admission.py T/test_delivered_control.py`
Expected: `OK`; `test_control_cutover.py` runs 9 tests.

Run: `PYTEST T/test_workflow_state.py` (timeout 1800 s)
Expected: `OK`.

Run: `git diff --stat BASE -- T/fixtures T/test_admission_replay.py`
Expected: empty output.

- [ ] **Step 5: Commit**

```bash
git add python home
launch-commit … -- -m "feat(workflow-state): control reads occupancy and the capacity gate from the store (#339)"
```
