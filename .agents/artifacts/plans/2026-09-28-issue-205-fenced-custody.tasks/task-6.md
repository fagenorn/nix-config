# Task 6: Extract the transaction-state document model into `transaction_history`

**Files:**
- Create: `python/agent_tools/transaction_history.py`
- Modify: `python/agent_tools/transaction_core.py`
- Modify: `tests/test_transaction_core.py` (`StorageModuleTest` gains one test; the
  `from agent_tools import …` line gains `transaction_history`)
- Modify: `tests/test_transaction_core_sweep.py` (`NEUTRAL_MODULES` gains the new module)

A move with no behavior change, per D33: every existing test passes unmodified, every
refusal keeps its class, message and order, and every byte the store writes is unchanged.

**Interfaces:**
- Consumes (Tasks 1–5, `transaction_core`): `SCHEMA`, `FORWARD`, `PARKINGS`,
  `TERMINALS`, `STATES`, `TRANSITIONS`, `Custody`, `Transaction`, `_ID_PATTERN`,
  `_AT_PATTERN`, `_KEY_COLLECTIONS`, `_STATE_KEYS`, `_CREATED_KEYS`, `_TRANSITIONED_KEYS`, `_ENVELOPE_KEYS`,
  `_OPENING_KEYS`, `_EVENT_KEYS`, `_FENCED_EVENTS`, `_RELEASE_REASONS`,
  `_EXTERNAL_STATES`, `_edge_allowed`, `_is_id`, `_format_at`, `_parse_at`,
  `_parked_since`, `_is_timestamp`, `_key_set_violation`, `_fold_transitioned`,
  `_is_subject_path`, `_CustodyFold`, `_id_violation`, `_note_id`, `_fold_closing`,
  `_fold_opening`, `_fold_fenced`, `_fold_custody`, `_validate_state`, `_snapshot`,
  `_require_custody_shape`, `_require_texts`, `_bound_path`.
- Produces (`agent_tools.transaction_history`, bodies moved verbatim except as stated):
  - public, moved with their names: `SCHEMA`, `FORWARD`, `PARKINGS`, `TERMINALS`,
    `STATES`, `TRANSITIONS`, `Custody`, `Transaction`;
  - public, the leading underscore dropped: `EXTERNAL_STATES`, `edge_allowed`, `is_id`, `format_at`, `parked_since`, `key_set_violation`,
    `is_subject_path`, `bound_path`, `snapshot`, `require_custody_shape`,
    `require_texts`;
  - `validate_state(document: Any, transaction_id: str, indexed: Callable[[str], str | None]) -> None`
    — `_validate_state` with its one I/O call, `_read_index(root, creation_key)`,
    replaced by `indexed(creation_key)` at the same point and under the same
    `UnicodeEncodeError` handler;
  - `fenced_id_violation(events: Sequence[Mapping[str, Any]], event: Mapping[str, Any]) -> str | None`
    — the id fold `_append_fenced` builds inline (note the id of every earlier
    evidence, interval and grant record, then `_id_violation`);
  - private: `_parse_at`, `_is_timestamp`, the patterns and key sets (`_EVENT_KEYS`
    included: nothing outside the module reads it), `_CustodyFold`,
    `_id_violation`, `_note_id`, the `_fold_*` functions, and a new
    `_check_envelope(event, seq, keys, refuse)` that holds the closed-key-set, `seq` and
    `at` checks `_fold_transitioned`, `_fold_fenced` and `_fold_custody` each repeat.
- Produces (`agent_tools.transaction_core`): binds every name `transaction_history` moved
  from it that tests import (`SCHEMA`, `FORWARD`, `PARKINGS`, `TERMINALS`, `STATES`,
  `TRANSITIONS`, `Custody`, `Transaction`) as the same objects; keeps `INDEX_SCHEMA`,
  `PARKED_CUSTODY_WINDOW_MS`, `_MAX_CLOCK_MS`, `_INDEX_KEYS`, `_mint_id`, `_index_path`,
  `_read_index`, `_require_creatable` and `TransactionStore`; keeps a private
  `_validate_state(document, transaction_id, root)` that calls
  `validate_state(document, transaction_id, lambda key: _read_index(root, key))`, so its
  call sites stay as they are. Task 7 adds its validator rules to `transaction_history`
  and its store methods to `transaction_core`.

**Invariants:**
- Import direction is core → history → custody → storage: `transaction_history` imports
  only the standard library, `agent_tools.transaction_custody` (`CUSTODY_EVENTS`,
  `EVIDENCE_FORMS`, `admissibility`, `fence_violation`) and
  `agent_tools.transaction_storage` (`StateInvalid`, `serialize`) — Task 7 adds
  `agent_tools.canonical`; nothing imports
  `transaction_core` or `transaction_history` except the modules to its left and tests.
- `transaction_history` reads no file, no lock and no clock.
- `_check_envelope` raises exactly the messages the three copies raise today
  (`event {seq} is not the closed {type} event`, `event {seq} does not carry seq {seq}`,
  `event {seq} at is not a YYYY-MM-DDTHH:MM:SS.mmmZ timestamp`), in that order.
- Review budget: after this task's commit, each touched Python file's cumulative
  `-U10` diff from the branch base stays within the caps in Step 6, so that Task 7's
  additions still leave every file under 55000 bytes.

- [ ] **Step 1: Write the failing tests** — in `tests/test_transaction_core.py` change
  the import line to `from agent_tools import transaction_core, transaction_history,
  transaction_storage` and append to `StorageModuleTest`:

```python
    def test_the_core_re_exports_the_history_surface(self):
        for name in ("SCHEMA", "FORWARD", "PARKINGS", "TERMINALS", "STATES",
                     "TRANSITIONS", "Custody", "Transaction"):
            with self.subTest(name=name):
                self.assertIs(getattr(transaction_core, name),
                              getattr(transaction_history, name))
```

In `tests/test_transaction_core_sweep.py` replace the two lines above `NeutralityTest`
with:

```python
from agent_tools import transaction_custody, transaction_history, transaction_storage

NEUTRAL_MODULES = (transaction_core, transaction_history, transaction_custody,
                   transaction_storage)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core.py 2>&1 | tail -3`
Expected: FAIL — `ImportError: cannot import name 'transaction_history'`.

- [ ] **Step 3: Write the minimal implementation**

1. Create `transaction_history.py` with this module docstring: "The transaction-state/v2
   document model of the transaction core (#205 D33): the lifecycle vocabularies, the
   `Custody` credential and `Transaction` snapshot types, the credential shape checks, the
   pure history validator and the snapshot fold. It reads no file, lock or clock:
   `validate_state` takes the creation-key index lookup as a callable, which
   `agent_tools.transaction_core` binds to its store root." Move the consumed names into
   it per the Interfaces list; delete them from `transaction_core` (no second copy).
2. Extract `_check_envelope` and call it from `_fold_transitioned` (with
   `_TRANSITIONED_KEYS`), `_fold_fenced` and `_fold_custody` (with
   `_EVENT_KEYS[event_type]`) in place of their three inline copies.
3. `_append_fenced` calls `fenced_id_violation(prior["events"], event)` in place of its
   inline fold; the refusal message stays `f"{transaction_id}: {operation}: {violation}"`.
4. `transaction_core` imports what it uses from `transaction_history` by the public names
   and updates its call sites; it does not import any `_`-prefixed name from a sibling,
   and drops each sibling import it no longer uses (`fence_violation` and
   `CUSTODY_EVENTS` among them, since only the moved code read them).
5. In `transaction_core`'s module docstring, replace the last two sentences with: "The
   durable-file primitives and the refusal hierarchy live in
   `agent_tools.transaction_storage`, and the document model — vocabularies, `Custody`,
   `Transaction`, the validator and the snapshot fold — in
   `agent_tools.transaction_history`; this module re-exports the errors and the public
   model names. The module has no command and no caller yet." Docstrings of moved
   functions move with them unchanged.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core.py tests/test_transaction_custody.py tests/test_transaction_core_sweep.py 2>&1 | tail -3`
Expected: `OK` (Task 5's count + 1).

Run: `if grep -nE '^(def|class) (_?(snapshot|edge_allowed|format_at|parse_at|parked_since)\b|_fold_|_CustodyFold)' python/agent_tools/transaction_core.py; then exit 1; fi`
Expected: no output, exit 0 (the moved bodies are gone; the `_validate_state` binding
stays).

Run (import direction, both ways):

```bash
test -z "$(grep -hoE '^(from|import) agent_tools\.[a-z_]+' python/agent_tools/transaction_history.py \
  | grep -vE 'agent_tools\.(canonical|transaction_custody|transaction_storage)$')" \
  && ! grep -nE 'agent_tools\.transaction_(history|core)' \
       python/agent_tools/transaction_custody.py python/agent_tools/transaction_storage.py
```

Expected: exit 0 — `transaction_history` imports no sibling but `transaction_custody`,
`transaction_storage` (and `agent_tools.canonical`, which Task 7 adds), and neither of
those two names `transaction_history` or `transaction_core`.

Run: `just agent-workflow-tests 2>&1 | tail -3` — Expected: `OK`.

Run: `git add python/agent_tools/transaction_history.py && just build 2>&1 | tail -3`
Expected: success (the flake copies only git-tracked files, so the new module is staged
first; the Nix import check then loads it).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/transaction_history.py python/agent_tools/transaction_core.py \
  tests/test_transaction_core.py tests/test_transaction_core_sweep.py
git commit -m "refactor(transaction-core): move the state document model to transaction_history (#205)"
```

- [ ] **Step 6: Check the review budget** (after the commit)

Run (every file the branch changes, plus this task's tighter caps):

```bash
base=66ccba5844eab2af9c68962c54a28f874585ee80; fail=0
size() { git diff -U10 "$base" HEAD -- "$1" | wc -c; }
for f in $(git diff --name-only "$base" HEAD); do
  n=$(size "$f"); printf '%s %s\n' "$n" "$f"; [ "$n" -lt 65536 ] || fail=1
done
[ "$(size python/agent_tools/transaction_core.py)" -le 50000 ] || fail=1
[ "$(size python/agent_tools/transaction_history.py)" -le 30000 ] || fail=1
for f in tests/test_transaction_core.py tests/test_transaction_core_sweep.py; do
  [ "$(size "$f")" -le 55000 ] || fail=1
done
test "$fail" = 0
```

Expected: exit 0 (estimates from a dry run of the move: core ~49000, history ~24000).
A miss means the task is not done. Moving a function that already existed at the base
commit (`_mint_id`, `_index_path`, `_read_index`, `_require_creatable`) makes the core's
diff larger, because its unchanged base lines become deletions. The productive moves
are the pure candidate compositions inside the store methods, each into a
`transaction_history` function the method calls: the transitioned and terminal-release
build in `_advance_locked`, the `lease_released` candidate that `release` and `renew`'s
quiesce each build (one shared function), and the opening-event build in
`_acquisition`. Make them in a follow-up commit and re-run this step.
