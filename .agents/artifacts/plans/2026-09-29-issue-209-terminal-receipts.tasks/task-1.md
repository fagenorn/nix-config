# Task 1: Schema v6 — authority class, actor kind, and `failed` closed

**Files:**
- Create: `python/agent_tools/transaction_disposition.py` (the reserved reason and the two
  `failed` rules only, for now)
- Modify: `python/agent_tools/transaction_history.py` (v6, `ACTOR_KINDS`, the `created`
  and `grant_issued` key sets, the pairing dispatch)
- Modify: `python/agent_tools/transaction_custody.py` (the grants view)
- Modify: `python/agent_tools/transaction_core.py` (module docstring cut; `create`,
  `_create`, `_create_locked`, `roll_forward`, `issue_grant`, `advance`; re-exports)
- Create: `tests/test_transaction_disposition.py`
- Modify: `justfile` (add `tests/test_transaction_disposition.py` after
  `tests/test_transaction_recovery_settle.py` in `agent-workflow-tests`)
- Modify, only as the invariants say: `tests/test_transaction_core.py`,
  `tests/test_transaction_custody.py`, `tests/test_transaction_invocation.py`,
  `tests/test_transaction_plan.py`, `tests/test_transaction_proof.py`,
  `tests/test_transaction_recovery_plan.py`, `tests/test_transaction_recovery.py`,
  `tests/test_transaction_recovery_settle.py`, `tests/transaction_core_sweep_support.py`,
  `tests/test_transaction_core_sweep.py`

**Interfaces:**
- Consumes: the #208 code base at `93bf5fd`.
- Produces:
  - `TransactionStore.create(creation_key, subject, *, concurrency_keys, proof, recovery,
    authority_class: str) -> Transaction`; `_create(creation_key, subject,
    concurrency_keys, proof, recovery, recovers, authority_class)`.
  - `TransactionStore.roll_forward(custody, *, grant_id, reason, creation_key, subject,
    concurrency_keys, proof, recovery, authority_class: str) -> Transaction`.
  - `TransactionStore.issue_grant(custody, *, grant_id, actor, actor_kind: str,
    authority_class: str) -> Transaction`.
  - `transaction_history.ACTOR_KINDS = ("human", "agent")`, re-exported by the core.
  - `transaction_disposition.FAILURE_REASON = "failure_disposed"`,
    `disposition_advance_violation(target: str, reason: str) -> str | None` and
    `disposition_pairing_violation(previous: Mapping | None, event: Mapping | None) ->
    str | None`.
  - Test constants: `tests/test_transaction_custody.py` defines `AUTHORITY =
    "release:alpha"`, and `CustodyCase.new` passes it. Task 4 imports it.

**Invariants:**
- `SCHEMA = "transaction-state/v6"`. A v5 document fails closed on the existing schema
  rule, naming `transaction-state/v5` (per D17).
- `_CREATED_KEYS` gains `authority_class`, which must be a non-empty string (rule text
  contains `authority_class`). `_EVENT_KEYS["grant_issued"]` gains `actor_kind` and
  `authority_class`. `_fold_fenced`'s existing non-empty-string loop covers both. Then
  `actor_kind` must be in `ACTOR_KINDS` (rule text `actor_kind is not human or agent`)
  (per D11, D22).
- `create` refuses `StateInvalid` before any lock when `authority_class` is not a
  non-empty string. The check sits in `_require_creatable`, which gains the parameter. A
  same-key create whose stored class differs adds `authority class` to the `differs`
  list, after `recovers`. `roll_forward` passes its own `authority_class` to `_create`
  (per D11, D18).
- `issue_grant` runs `require_texts` over `grant_id`, `actor` and `authority_class`, then
  refuses an `actor_kind` outside `ACTOR_KINDS` with `StateInvalid`, all before any lock.
  `admissibility`'s grant entries gain `actor_kind` and `authority_class`, copied from the
  event, so `Transaction.grants` and `check_grant` carry them (per D22).
- `disposition_advance_violation` returns `"failed is entered only through
  dispose_failed"` for target `failed`. For reason `failure_disposed` it returns
  `"reserved reason failure_disposed is written only by dispose_failed"`. Otherwise it
  returns None. `advance` calls it right after `advance_violation`, before the unresolved
  check (per D8, D21).
- `disposition_pairing_violation(previous, event)` works the way
  `recovery_pairing_violation` does. After a `failure_disposed`, the next event must be the
  transition `attention_required -> failed` with reason `failure_disposed` and external
  state `known` (else `"failure_disposed is not immediately followed by attention_required
  -> failed with reason failure_disposed and external state known"`). A transition into
  `failed` must follow a `failure_disposed` (else `"transition into failed does not
  immediately follow failure_disposed"`). A transition with reason `failure_disposed` must
  follow its event (else `"reserved reason failure_disposed does not immediately follow its
  event"`). `validate_state` ORs it after the two existing pairing calls, both in the loop
  and at the end. `failure_disposed` is not a dispatched event type yet, so every `failed`
  document is refused until Task 4 (per D21).
- The `TRANSITIONS` table is unchanged.
- The core module docstring is at most 1200 bytes. It is a map: the store, its root and
  clock, one clause per sibling module naming what that module owns, and "no command and
  no caller until #125". Everything it drops already lives in the named module's
  docstring. Measure it with
  `python3 -c "import ast;print(len(ast.get_docstring(ast.parse(open('python/agent_tools/transaction_core.py').read()),clean=False)))"`
  (per D19).
- `transaction_disposition.py`'s module docstring says what it holds now: the reserved
  reason and the two `failed` rules. Tasks 4–5 extend it.
- Existing tests change only as follows. Every `create` passes `authority_class=AUTHORITY`
  (imported from `tests/test_transaction_custody.py`; `tests/test_transaction_core.py`
  defines its own equal constant beside `EMPTY_RECOVERY`). Every `roll_forward` passes
  `authority_class=AUTHORITY`. Every `issue_grant` passes `actor_kind="agent",
  authority_class=AUTHORITY`. The exact `created` key-set assertions
  (`tests/test_transaction_core.py` ~line 148, `tests/test_transaction_plan.py` ~line
  291) gain `authority_class`. Exact grant-entry assertions gain the two fields.
  `transaction-state/v5` becomes `v6`, and
  `test_new_state_is_v5_and_a_v3_document_fails_closed_naming_its_version` is renamed
  `…_v6_…`. In `tests/test_transaction_core.py`, `PATHS_TO_TERMINAL` loses `failed`, and
  the `attention_required` allowed set in
  `test_every_allowed_edge_is_accepted_and_every_other_target_refused` becomes
  `{"created", "abandoned"}`. In `tests/test_transaction_invocation.py`,
  `test_an_open_attempt_blocks_a_terminal` advances to `abandoned` instead of `failed`.
  The sweep support's module constant `AUTHORITY_CLASS = "fixture-release"` goes to its
  `create` and `roll_forward`. `recover()`'s grant becomes `actor_kind="agent",
  authority_class=AUTHORITY_CLASS`. `tests/test_transaction_core_sweep.py`'s two creates
  pass it too.
- `transaction_disposition` joins `NEUTRAL_MODULES` in `tests/test_transaction_core_sweep.py`.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_transaction_disposition.py`:

```python
"""Transaction core slice 6: authority, the failed disposition and its grounds (#209).

Run: just agent-workflow-tests
"""

import copy
import unittest

from agent_tools import transaction_core, transaction_history
from agent_tools.transaction_core import (
    ACTOR_KINDS, CreationConflict, StateInvalid, TransitionRefused)

from .test_transaction_custody import (
    AUTHORITY, EMPTY_PROOF, EMPTY_RECOVERY, KEYS, SUBJECT, CustodyCase)


def appended(document, *events):
    """`document` with `events` appended by hand, each stamped with the last `at`."""
    document = copy.deepcopy(document)
    for fields in events:
        document["events"].append({"seq": len(document["events"]) + 1,
                                   "at": document["events"][-1]["at"], **fields})
    document["revision"] = len(document["events"])
    return document


def moved(source, target, reason="r", external_state="known"):
    return {"type": "transitioned", "from": source, "to": target, "reason": reason,
            "external_state": external_state}


class AuthorityTest(CustodyCase):
    def create(self, key="k", authority_class=AUTHORITY):
        return self.store.create(key, SUBJECT, concurrency_keys=KEYS, proof=EMPTY_PROOF,
                                 recovery=EMPTY_RECOVERY, authority_class=authority_class)

    def test_create_stores_a_required_authority_class_and_compares_it(self):
        created = self.create()
        document = self.state_doc(created.transaction_id)
        self.assertEqual((document["schema"], document["events"][0]["authority_class"]),
                         ("transaction-state/v6", AUTHORITY))
        with self.assertRaises(TypeError):
            self.store.create("k2", SUBJECT, concurrency_keys=KEYS, proof=EMPTY_PROOF,
                              recovery=EMPTY_RECOVERY)
        before = self.files()
        for bad in ("", None, 7):
            with self.subTest(bad=bad), self.assertRaises(StateInvalid):
                self.create("k3", authority_class=bad)
        with self.assertRaises(CreationConflict) as caught:
            self.create(authority_class="release:beta")
        self.assertIn("authority class", str(caught.exception))
        self.assertEqual(self.files(), before)
        self.assertEqual(self.create().transaction_id, created.transaction_id)

    def test_a_grant_records_its_actor_kind_and_authority_class(self):
        self.assertEqual(ACTOR_KINDS, ("human", "agent"))
        self.assertIs(transaction_core.ACTOR_KINDS, transaction_history.ACTOR_KINDS)
        custody = self.acquire(self.new())
        after = self.store.issue_grant(custody, grant_id="g", actor="op", actor_kind="human",
                                       authority_class=AUTHORITY)
        event = dict(after.events[-1])
        self.assertEqual((event["actor_kind"], event["authority_class"]), ("human", AUTHORITY))
        self.assertEqual((after.grants[0]["actor_kind"], after.grants[0]["authority_class"]),
                         ("human", AUTHORITY))
        for bad in ({"actor_kind": "robot"}, {"actor_kind": ""}, {"authority_class": ""}):
            arguments = {"actor_kind": "agent", "authority_class": AUTHORITY, **bad}
            with self.subTest(bad=bad):
                self.assertRefusedUnchanged(StateInvalid, lambda: self.store.issue_grant(
                    custody, grant_id="g2", actor="op", **arguments))
        with self.assertRaises(TypeError):
            self.store.issue_grant(custody, grant_id="g3", actor="op")

    def test_hand_edited_authority_fields_are_state_invalid(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        self.store.issue_grant(custody, grant_id="g", actor="op", actor_kind="agent",
                               authority_class=AUTHORITY)
        document = self.state_doc(transaction_id)
        grant = len(document["events"]) - 1
        cases = (
            (lambda d: d["events"][0].update(authority_class=""), "authority_class"),
            (lambda d: d["events"][0].pop("authority_class"), "closed created event"),
            (lambda d: d["events"][grant].update(actor_kind="robot"),
             "actor_kind is not human or agent"),
            (lambda d: d["events"][grant].update(authority_class=""), "authority_class"),
            (lambda d: d.update(schema="transaction-state/v5"), "transaction-state/v5"))
        for edit, fragment in cases:
            with self.subTest(fragment=fragment):
                edited = copy.deepcopy(document)
                edit(edited)
                self.assertRuleRefuses(transaction_id, edited, fragment)


class FailedClosedTest(CustodyCase):
    def test_advance_never_enters_failed_nor_writes_the_reserved_reason(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        self.store.advance(transaction_id, "attention_required", reason="r",
                           external_state="known", custody=custody)
        for target, reason, fragment in (
                ("failed", "r", "failed is entered only through dispose_failed"),
                ("abandoned", "failure_disposed", "reserved reason failure_disposed"),
                ("created", "failure_disposed", "reserved reason failure_disposed")):
            with self.subTest(target=target, reason=reason):
                error = self.assertRefusedUnchanged(TransitionRefused, lambda: self.store.advance(
                    transaction_id, target, reason=reason, external_state="known",
                    custody=custody))
                self.assertIn(fragment, str(error))

    def test_a_hand_built_failed_or_reserved_reason_is_state_invalid(self):
        transaction_id = self.new()
        document = self.state_doc(transaction_id)
        cases = (
            ((moved("created", "attention_required"),
              moved("attention_required", "failed", "failure_disposed")),
             "transition into failed does not immediately follow failure_disposed"),
            ((moved("created", "attention_required"), moved("attention_required", "failed")),
             "transition into failed does not immediately follow failure_disposed"),
            ((moved("created", "abandoned", "failure_disposed"),),
             "reserved reason failure_disposed does not immediately follow its event"))
        for events, fragment in cases:
            with self.subTest(fragment=fragment):
                edited = appended(document, *events)
                last = edited["events"][-1]["to"]
                edited.update(state=last,
                              parked_from="created" if last == "attention_required" else None)
                self.assertRuleRefuses(transaction_id, edited, fragment)
```

  Make the existing-test changes the invariants list. The hand-built `failed` cases
  set `parked_from` only when the last state is a parking. Every refusal fires in the
  event loop, before the projection checks.

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_disposition.py 2>&1 | tail -3`.
  Expected: ERROR (`ACTOR_KINDS` cannot be imported).

- [ ] **Step 3: Implement** the invariants. First cut the core module docstring (D19),
  then thread `authority_class` through `create` → `_create` → `_create_locked` (stored
  on the `created` event beside `recovers`) and `roll_forward`. Add `actor_kind` and
  `authority_class` to `issue_grant` and its event, then the history rules, the grants
  view and the disposition module. Update the `create`, `issue_grant`, `advance`,
  `validate_state` and `transaction_history` module docstrings from the resulting code.

- [ ] **Step 4: Verify.**
  Run the slice unit command with `tests/test_transaction_disposition.py`. Expected: `OK`.

```bash
grep -q 'SCHEMA = "transaction-state/v6"' python/agent_tools/transaction_history.py || exit 1
if grep -rn "transaction-state/v5\"\|is_v5" tests/test_transaction_core.py tests/test_transaction_invocation.py tests/test_transaction_plan.py python/agent_tools/transaction_*.py; then exit 1; fi
n=$(python3 -c "import ast;print(len(ast.get_docstring(ast.parse(open('python/agent_tools/transaction_core.py').read()),clean=False)))"); [ "$n" -le 1200 ] || exit 1
grep -q 'tests/test_transaction_disposition.py' justfile || exit 1
```

  Run: `git add -A python tests justfile && just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.** Stage exactly this task's **Files**, then:

```bash
git commit -m "feat(transaction-core): authority class, actor kind and a closed failed under v6 (#209)"
```

- [ ] **Step 6: Check the review budget** with `FILES="python/agent_tools/transaction_history.py python/agent_tools/transaction_custody.py python/agent_tools/transaction_disposition.py python/agent_tools/transaction_core.py tests/test_transaction_disposition.py tests/test_transaction_core.py tests/test_transaction_custody.py"`.
  Expected: exit 0.

Decisions: per D8, D11, D17, D18, D19, D21, D22.
