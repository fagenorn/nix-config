# Task 1: Invocation vocabulary, `action_id`, errors and moved codecs

**Files:**
- Create: `python/agent_tools/transaction_invocation.py`
- Modify: `python/agent_tools/transaction_storage.py` (codecs and two errors)
- Modify: `python/agent_tools/transaction_history.py` (import the moved codecs)
- Modify: `python/agent_tools/transaction_core.py` (re-exports only)
- Create: `tests/test_transaction_invocation.py`
- Modify: `tests/test_transaction_core_sweep.py` (`NEUTRAL_MODULES`)
- Modify: `justfile` (`agent-workflow-tests` list)

**Interfaces:**
- Consumes (base commit): `transaction_history.format_at(ms) -> str`,
  `transaction_history._parse_at(at) -> int`, `transaction_history.json_object_violation(value)
  -> str | None`, `transaction_storage.TransactionError`, `StateInvalid`,
  `agent_tools.canonical.telemetry_digest(body) -> "sha256:<64 hex>"`.
- Produces (`agent_tools.transaction_storage`, per D15): `format_at(ms: int) -> str`,
  `parse_at(at: str) -> int` (the body of history's `_parse_at`, now public),
  `json_object_violation(value: Any) -> str | None` (body moved verbatim);
  `class InvocationRefused(TransactionError)` with `__init__(self, message: str, *, reason:
  str)` storing `self.reason`; `class EffectResultInvalid(TransactionError)`.
- Produces (`agent_tools.transaction_history`): the same three names imported from storage
  (history's `format_at` and `json_object_violation` stay importable; `parked_since` calls
  `parse_at`); `_parse_at` is gone.
- Produces (`agent_tools.transaction_invocation`, later tasks import these exact names):
  `OUTCOMES = ("absent", "in_progress", "satisfied", "diverged", "unknown")`,
  `RESULTS = ("accepted", "rejected", "unknown")`,
  `ERROR_CLASSES = ("transient_transport", "provider_throttled", "provider_unavailable",
  "invalid_input", "authorization_denied", "precondition_failed", "unsupported_operation")`,
  `RETRY_SAFE_CLASSES = frozenset(ERROR_CLASSES[:3])`, `MAX_ATTEMPTS = 3`,
  `RETRY_WINDOW_MS = 900_000`, `EFFECT_STATES = ("publishing", "activating")`,
  `REFUSAL_REASONS = ("inspection_required", "not_absent", "not_retryable",
  "budget_exhausted", "window_closed", "state_not_effectful", "attempt_in_flight")`;
  `action_violation(name: Any, parameters: Any) -> str | None`;
  `action_id(transaction_id: str, name: str, parameters: dict) -> str`.
- Produces (`agent_tools.transaction_core` re-exports): `action_id`, `MAX_ATTEMPTS`,
  `RETRY_WINDOW_MS`, `InvocationRefused`, `EffectResultInvalid`.

**Invariants:**
- `action_id(t, n, p) == "act_" + telemetry_digest([t, n, p])[len("sha256:"):][:32]` (per D4).
- `action_id` refuses (`StateInvalid`, message naming the transaction id and the rule) a
  `transaction_id` that is not a non-empty string, a `name` that is not a non-empty
  UTF-8-encodable string, and `parameters` for which `json_object_violation` returns a rule.
- `transaction_invocation` imports only `agent_tools.canonical`, `transaction_custody`
  and `transaction_storage` (never core or history) and reads no file, lock or clock.
- No behavior of slices 1–2 changes: every existing transaction test passes unmodified.

- [ ] **Step 1: Write the failing tests** — create `tests/test_transaction_invocation.py`:

```python
"""Transaction core slice 3: the administrative protocol (#206).

Run: just agent-workflow-tests
"""

import unittest

from agent_tools import transaction_history, transaction_storage
from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_core import (
    MAX_ATTEMPTS, RETRY_WINDOW_MS, EffectResultInvalid, InvocationRefused, StateInvalid,
    TransactionError, action_id)

from .test_transaction_custody import T0

TID = "rel_01890a5d-ac96-7abc-8def-0123456789ab"


class ActionIdTest(unittest.TestCase):
    def test_the_id_is_act_plus_the_first_32_hex_of_the_digest(self):
        parameters = {"mode": "materialize", "subject": {"digest": "sha256:abc"}}
        expected = "act_" + telemetry_digest([TID, "build", parameters])[7:39]
        self.assertEqual(action_id(TID, "build", parameters), expected)
        self.assertRegex(expected, r"\Aact_[0-9a-f]{32}\Z")

    def test_re_derivation_is_stable_under_parameter_key_order(self):
        first = action_id(TID, "build", {"a": 1, "b": [1, 2]})
        self.assertEqual(action_id(TID, "build", {"b": [1, 2], "a": 1}), first)
        self.assertEqual(action_id(TID, "build", {"a": 1, "b": [1, 2]}), first)

    def test_any_changed_input_changes_the_id(self):
        base = action_id(TID, "build", {"a": 1})
        changed = {action_id(TID[:-1] + "c", "build", {"a": 1}),
                   action_id(TID, "stage", {"a": 1}), action_id(TID, "build", {"a": 2}),
                   action_id(TID, "build", {})}
        self.assertEqual(len(changed), 4)
        self.assertNotIn(base, changed)

    def test_malformed_inputs_are_refused(self):
        for args in ((TID, "", {}), (TID, 7, {}), (TID, "\ud800", {}), (TID, "b", []),
                     (TID, "b", {"x": float("nan")}), (TID, "b", {1: "x"}),
                     ("", "b", {}), (None, "b", {})):
            with self.subTest(args=args), self.assertRaises(StateInvalid):
                action_id(*args)


class VocabularyTest(unittest.TestCase):
    def test_the_retry_budget_constants(self):
        self.assertEqual((MAX_ATTEMPTS, RETRY_WINDOW_MS), (3, 900_000))

    def test_the_new_errors_are_transaction_errors_homed_in_storage(self):
        self.assertIs(InvocationRefused, transaction_storage.InvocationRefused)
        self.assertIs(EffectResultInvalid, transaction_storage.EffectResultInvalid)
        self.assertTrue(issubclass(InvocationRefused, TransactionError))
        self.assertTrue(issubclass(EffectResultInvalid, TransactionError))
        error = InvocationRefused("rel_x: refused", reason="window_closed")
        self.assertEqual((error.reason, str(error)), ("window_closed", "rel_x: refused"))

    def test_the_codecs_have_one_home_in_storage(self):
        for name in ("format_at", "json_object_violation"):
            self.assertIs(getattr(transaction_history, name),
                          getattr(transaction_storage, name))
        self.assertEqual(transaction_storage.format_at(T0 + 1234), "2027-01-15T08:00:01.234Z")
        self.assertEqual(transaction_storage.parse_at("2027-01-15T08:00:01.234Z"), T0 + 1234)


if __name__ == "__main__":
    unittest.main()
```

  In `tests/test_transaction_core_sweep.py`, change the late import and tuple to:

```python
from agent_tools import (transaction_custody, transaction_history, transaction_invocation,
                         transaction_storage)

NEUTRAL_MODULES = (transaction_core, transaction_history, transaction_invocation,
                   transaction_custody, transaction_storage)
```

  In `justfile`, add `    tests/test_transaction_invocation.py \` directly after the
  `tests/test_transaction_custody.py \` line of `agent-workflow-tests`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_invocation.py 2>&1 | tail -3`
Expected: FAIL — `ImportError: cannot import name 'MAX_ATTEMPTS'`.

- [ ] **Step 3: Implement**

  1. Storage: add `import calendar, datetime` and `from agent_tools.canonical import
     telemetry_digest`; move `format_at` and `_parse_at` (renamed `parse_at`) and
     `json_object_violation` from history verbatim (docstrings kept; `json_object_violation`
     keeps citing #205 D34). Add the two errors after `LeaseUnavailable`, docstrings:
     `"""An administrative-protocol refusal before any write or effect call; `reason` names
     the rule (#206 D7)."""` and `"""An effect result outside the closed shapes; nothing from
     that call is recorded (#206 D11)."""`.
  2. History: delete the moved bodies, import `format_at`, `json_object_violation`,
     `parse_at` from storage, and switch `parked_since` to `parse_at`. Drop imports that
     become unused (`calendar`; keep `datetime`, still used by `_is_timestamp`).
  3. New module: a docstring stating what it holds now (vocabularies, retry constants,
     `action_id`) and that it reads no file, lock or clock; the constants above;

```python
def action_violation(name: Any, parameters: Any) -> str | None:
    """The first rule an action's name or parameters break, or None (#206 D4)."""
    if type(name) is not str or not name:
        return f"name {name!r} is not a non-empty string"
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return f"name {name!r} is not encodable as UTF-8"
    violation = json_object_violation(parameters)
    return None if violation is None else f"parameters {violation}"


def action_id(transaction_id: str, name: str, parameters: dict) -> str:
    """`act_` + the first 32 hex digits of the digest of [transaction id, name,
    parameters]; also the idempotency key an effect receives (#206 D4)."""
    if type(transaction_id) is not str or not transaction_id:
        raise StateInvalid(f"{transaction_id!r}: action_id: transaction_id is not a "
                           f"non-empty string")
    violation = action_violation(name, parameters)
    if violation is not None:
        raise StateInvalid(f"{transaction_id}: action_id: {violation}")
    return "act_" + telemetry_digest([transaction_id, name, parameters])[7:39]
```

  4. Core: import `MAX_ATTEMPTS, RETRY_WINDOW_MS, action_id` from
     `transaction_invocation` and `EffectResultInvalid, InvocationRefused` from storage
     (re-exports; unused-name linting is not configured). Add one sentence to the module
     docstring naming `agent_tools.transaction_invocation` as the home of `action_id` and
     the retry constants.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_invocation.py tests/test_transaction_core.py tests/test_transaction_custody.py tests/test_transaction_core_sweep.py 2>&1 | tail -3`
Expected: `OK` (the sweep's neutrality test now covers five modules).

Run (import direction; exits 1 on a back-import):

```bash
if grep -nE "transaction_(core|history)" python/agent_tools/transaction_invocation.py \
    | grep -E "^[0-9]+:(from|import) "; then exit 1; fi
grep -c "tests/test_transaction_invocation.py" justfile   # expect 1
```

Run: `just build 2>&1 | tail -3` — Expected: success; the Nix import check loads the new
module (stage it with `git add` first: the flake sees only tracked files).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/transaction_invocation.py python/agent_tools/transaction_storage.py \
  python/agent_tools/transaction_history.py python/agent_tools/transaction_core.py \
  tests/test_transaction_invocation.py tests/test_transaction_core_sweep.py justfile
git commit -m "feat(transaction-core): add the invocation vocabulary and action ids (#206)"
```

Decisions: per D1, D4, D7, D11, D15.
