# Task 1: Ledger rules in the pure blocker module

**Files:**
- Modify: `python/agent_tools/verification_blocker.py` (module docstring list; new private constants; `park`, `validate_blockers`, `upgrade_ten` after `blocker_id`; `blocker_id` reads the shared identity-member tuple)
- Modify: `tests/test_verification_blocker.py` (three new classes before `if __name__ == "__main__":`)
- Modify: `python/README.md` (the first paragraph of `## verification-observe`: one clause reworded, one sentence added)

**Interfaces:**
- Consumes: the module's own `BlockerRefused`, `FAILURE_KIND`, `SCHEMA_VERSION`, `blocker_id`, `_closed`, `_refuse`, `_valued_facts` (c1, unchanged).
- Produces (Task 2 and Task 3 import these exact names):
  - `park(blockers: dict, failure: object, issue: int, attempt: int) -> str`
  - `validate_blockers(blockers: object, pointers: Mapping[tuple[int, int], str | None]) -> None`
  - `upgrade_ten(document: object) -> dict`

**Invariants:**
- Still pure: the module imports only `copy`, `json`, `re`, `unicodedata`, `collections.abc` and `agent_tools.canonical` and touches no file, clock, process or environment variable (issue 543 D15; D2).
- Every refusal is one `BlockerRefused` line `<field>: <reason>`; a map key, pointer or issue key it names is JSON-escaped, so a value holding a newline still gives one line (D20). The tests read the exact texts Step 3 lists.
- `park` changes only the mapping it is given, never rewrites a record's content, never deletes a record, and returns the id. `upgrade_ten` never mutates its input. `validate_blockers` returns `None` and mutates nothing.

- [ ] **Step 1: Write the failing tests** in `tests/test_verification_blocker.py`

Insert this block between the end of `LoadTest` and `if __name__ == "__main__":` (two blank lines before each top-level definition). It reuses the module's `A`, `B`, `PINNED_ID`, `ZERO_ID`, `fact`, `failure`, `edited` and `sized`.

```python
def record(value=None, attempts=((61, 1),), state="open", resolution=None):
    """The schema-11 record `park` writes for `value` (issue 544 D3)."""
    value = failure() if value is None else value
    return {"id": vb.blocker_id(value), "repository": copy.deepcopy(value["repository"]),
            "command": copy.deepcopy(value["command"]),
            "failure_class": value["failure_class"], "facts": copy.deepcopy(value["facts"]),
            "attempts": [{"issue": issue, "attempt": number} for issue, number in attempts],
            "state": state, "resolution": resolution}


def changed_facts(value=None, objects=(B,)):
    """The record's facts with the one path's object replaced: a resolution's facts."""
    value = failure() if value is None else value
    facts = copy.deepcopy(value["facts"])
    for entry, object_id in zip(facts[0]["value"]["objects"], objects):
        entry["object"] = object_id
    return facts


class ParkTest(unittest.TestCase):
    def test_park_creates_then_joins_keeping_history_once(self):
        blockers = {}
        identity = vb.park(blockers, failure(), 62, 1)
        self.assertEqual(identity, PINNED_ID)
        self.assertEqual(blockers, {PINNED_ID: record(attempts=((62, 1),))})
        self.assertEqual(vb.park(blockers, failure(), 61, 2), PINNED_ID)
        self.assertEqual(vb.park(blockers, failure(), 62, 1), PINNED_ID)
        self.assertEqual(blockers, {PINNED_ID: record(attempts=((61, 2), (62, 1)))})
        other = failure(failure_class="environment")
        self.assertEqual(vb.park(blockers, other, 61, 2), vb.blocker_id(other))
        self.assertEqual(sorted(blockers), sorted([PINNED_ID, vb.blocker_id(other)]))

    def test_park_reopens_a_resolved_record_and_never_rewrites_content(self):
        blockers = {PINNED_ID: record(state="resolved",
                                      resolution={"facts": changed_facts()})}
        self.assertEqual(vb.park(blockers, failure(), 61, 1), PINNED_ID)
        self.assertEqual(blockers, {PINNED_ID: record()})

    def test_park_copies_the_failure_and_touches_only_the_map(self):
        value, blockers = failure(), {}
        before = copy.deepcopy(value)
        vb.park(blockers, value, 61, 1)
        self.assertEqual(value, before)
        blockers[PINNED_ID]["facts"][0]["name"] = "changed"
        self.assertEqual(value, before)

    def test_park_refuses_a_bad_reference_or_failure_and_writes_nothing(self):
        for issue, number, field in ((0, 1, "issue"), (True, 1, "issue"), ("61", 1, "issue"),
                                     (61, 0, "attempt"), (61, False, "attempt")):
            blockers = {}
            with self.subTest(issue=issue, attempt=number), \
                    self.assertRaises(vb.BlockerRefused) as caught:
                vb.park(blockers, failure(), issue, number)
            self.assertEqual(str(caught.exception), f"{field}: must be a positive integer")
            self.assertEqual(blockers, {})
        blockers = {}
        with self.assertRaises(vb.BlockerRefused):
            vb.park(blockers, failure(failure_class="product"), 61, 1)
        self.assertEqual(blockers, {})


class RecordRulesTest(unittest.TestCase):
    POINTERS = {(61, 1): PINNED_ID, (62, 1): None, (62, 2): None}

    def assert_refused(self, blockers, pointers, prefix):
        with self.assertRaises(vb.BlockerRefused) as caught:
            vb.validate_blockers(blockers, pointers)
        self.assertTrue(str(caught.exception).startswith(prefix), str(caught.exception))
        self.assertNotIn("\n", str(caught.exception))

    def test_valid_maps_pass(self):
        resolved = record(attempts=((61, 1), (62, 2)), state="resolved",
                          resolution={"facts": changed_facts()})
        for blockers in ({PINNED_ID: record()}, {PINNED_ID: resolved}):
            with self.subTest(blockers=str(blockers)[:40]):
                self.assertIsNone(vb.validate_blockers(blockers, self.POINTERS))
        self.assertIsNone(vb.validate_blockers({}, {(61, 1): None}))
        # A record outlives its attempts' parking: R3 keeps the history (issue 544 D3).
        self.assertIsNone(vb.validate_blockers({PINNED_ID: record()}, {(61, 1): None}))

    def test_each_rule_refuses(self):
        key = f"verification_blockers[{PINNED_ID}]"
        secret = failure(facts=[fact(paths=(".env",))])
        secret_record = {**record(), "facts": secret["facts"]}
        moved = changed_facts()
        moved[0]["source"]["paths"] = ["other.lock"]
        moved[0]["value"]["objects"][0]["path"] = "other.lock"
        cases = {
            "R1 not an object": ([], self.POINTERS, "verification_blockers: must be an object"),
            "R1 key is not the id": ({ZERO_ID: record()}, {(61, 1): ZERO_ID},
                                     f"verification_blockers[{ZERO_ID}].id"),
            "R1 id is not the content": ({PINNED_ID: {**record(), "failure_class": "environment"}},
                                         self.POINTERS, f"{key}.id"),
            "R1 secret-shaped content": ({PINNED_ID: secret_record}, self.POINTERS,
                                         f"{key}: facts[0].source.paths[0]: secret-shaped"),
            "R1 oversized content": ({PINNED_ID: {**record(), "facts": sized("flake-lockx")["facts"]}},
                                     self.POINTERS, f"{key}: failure: longer than 2048"),
            "R2 unknown member": ({PINNED_ID: {**record(), "note": "x"}}, self.POINTERS,
                                  f"{key}: missing [], unknown ['note']"),
            "R2 missing member": ({PINNED_ID: edited(record(), ("resolution",), KeyError)},
                                  self.POINTERS, f"{key}: missing ['resolution']"),
            "R3 empty attempts": ({PINNED_ID: record(attempts=())}, {}, f"{key}.attempts"),
            "R3 boolean attempt": ({PINNED_ID: edited(record(), ("attempts", 0, "attempt"), True)},
                                   self.POINTERS, f"{key}.attempts[0].attempt"),
            "R3 open reference": ({PINNED_ID: edited(record(), ("attempts", 0, "note"), 1)},
                                  self.POINTERS, f"{key}.attempts[0]"),
            "R3 unsorted": ({PINNED_ID: record(attempts=((62, 1), (61, 1)))}, self.POINTERS,
                            f"{key}.attempts"),
            "R3 repeated": ({PINNED_ID: record(attempts=((61, 1), (61, 1)))}, self.POINTERS,
                            f"{key}.attempts"),
            "R3 not of this run": ({PINNED_ID: record(attempts=((61, 1), (63, 1)))},
                                   self.POINTERS, f"{key}.attempts[1]"),
            "R4 unknown state": ({PINNED_ID: record(state="closed")}, self.POINTERS,
                                 f"{key}.state"),
            "R4 open with a resolution": ({PINNED_ID: record(resolution={"facts": changed_facts()})},
                                          self.POINTERS, f"{key}.resolution"),
            "R4 resolved without one": ({PINNED_ID: record(state="resolved")}, self.POINTERS,
                                        f"{key}.resolution"),
            "R4 open resolution object": ({PINNED_ID: record(
                state="resolved", resolution={"facts": changed_facts(), "note": 1})},
                self.POINTERS, f"{key}.resolution"),
            "R4 invalid resolved facts": ({PINNED_ID: record(
                state="resolved", resolution={"facts": changed_facts(objects=("x",))})},
                self.POINTERS, f"{key}.resolution.facts"),
            "R4 substituted source": ({PINNED_ID: record(
                state="resolved", resolution={"facts": moved})}, self.POINTERS,
                f"{key}.resolution.facts"),
            "R4 nothing changed": ({PINNED_ID: record(
                state="resolved", resolution={"facts": copy.deepcopy(failure()["facts"])})},
                self.POINTERS, f"{key}.resolution.facts"),
            "R5 pointer to no record": ({}, self.POINTERS, "verification_blockers: attempt 61:1"),
            "R5 pointer to a record without it": ({PINNED_ID: record(attempts=((62, 1),))},
                                                  self.POINTERS,
                                                  "verification_blockers: attempt 61:1"),
            "a key with a newline": ({"a\nb": record()}, self.POINTERS,
                                     "verification_blockers[a\\nb].id: must equal its key"),
            "a pointer with a newline": ({}, {(61, 1): "x\ny"},
                                         "verification_blockers: attempt 61:1 points at x\\ny"),
        }
        for label, (blockers, pointers, prefix) in cases.items():
            with self.subTest(case=label):
                self.assert_refused(blockers, pointers, prefix)


class UpgradeTenTest(unittest.TestCase):
    def ten(self):
        attempt = {"issue": 61, "attempt": 1, "state": "active", "blocked_on": None}
        return {"schema_version": 10, "run_id": "r", "transaction_id": "t",
                "issues": {"61": {"issue": 61, "attempts": [attempt, dict(attempt, attempt=2)]},
                           "62": {"issue": 62, "attempts": []}}}

    def test_the_step_adds_both_members_and_mutates_nothing(self):
        document = self.ten()
        before = copy.deepcopy(document)
        upgraded = vb.upgrade_ten(document)
        self.assertEqual(document, before)
        expected = copy.deepcopy(before)
        expected.update(schema_version=11, verification_blockers={})
        for attempt in expected["issues"]["61"]["attempts"]:
            attempt["verification_blocker"] = None
        self.assertEqual(upgraded, expected)
        upgraded["issues"]["61"]["attempts"][0]["state"] = "changed"
        self.assertEqual(document, before)

    def test_a_present_member_or_another_schema_is_refused(self):
        document = self.ten()
        pointed = copy.deepcopy(document)
        pointed["issues"]["61"]["attempts"][1]["verification_blocker"] = None
        cases = (
            ("verification_blockers: present before schema 11",
             {**document, "verification_blockers": {}}),
            ("issues[61].attempts[1].verification_blocker: present before schema 11", pointed),
            ("schema_version: must be 10", {**document, "schema_version": 11}),
            ("schema_version: must be 10", {**document, "schema_version": True}),
            ("issues: must be an object", {**document, "issues": []}),
            ("issues[6\\n1]: must be an object with an attempts list",
             {**document, "issues": {"6\n1": []}}),
        )
        for message, value in cases:
            before = copy.deepcopy(value)
            with self.subTest(message=message), self.assertRaises(vb.BlockerRefused) as caught:
                vb.upgrade_ten(value)
            self.assertEqual(str(caught.exception), message)
            self.assertEqual(value, before)
        with self.assertRaises(vb.BlockerRefused):
            vb.upgrade_ten([])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 300 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_verification_blocker.py 2>&1 | tail -4'`
Expected: `Ran 24 tests` and `FAILED (errors=35)` — the 35 errors, tests and subtests, are all `AttributeError: module 'agent_tools.verification_blocker' has no attribute 'park'` (or `validate_blockers`, `upgrade_ten`); the 16 c1 tests pass.

- [ ] **Step 3: Write the rules** in `python/agent_tools/verification_blocker.py`

Imports: add `import copy` before `import json`, and `from collections.abc import Mapping` after `import unicodedata`. After `_BLOCKER_ID` add, with a comment that the identity covers these members and the ledger record keeps them (issue 543 D3):

- `_IDENTITY_MEMBERS = ("command", "failure_class", "facts", "repository")`; `blocker_id` now digests `{member: failure[member] for member in _IDENTITY_MEMBERS}` (same bytes, so `PINNED_ID` is unchanged).
- `_RECORD_MEMBERS = {"id", "attempts", "state", "resolution", *_IDENTITY_MEMBERS}` and `_REFERENCE_MEMBERS = {"issue", "attempt"}`.

After `_refuse` add `_shown(value) -> str`, the form a value takes inside a refusal: `text = json.dumps(value, ensure_ascii=True, default=repr)`, returned without its quotes for a `str` (`text[1:-1]`) and as is otherwise, so a newline becomes the two characters `\n` and the refusal stays one line (D20). Every map key, pointer and issue key below is interpolated through it.

Add after `blocker_id`, each with a docstring that states its contract as below:

- `_positive(value, label) -> int`: `type(value) is int and value >= 1`, else `<label>: must be a positive integer` (so `bool` is refused).
- `park(blockers, failure, issue, attempt) -> str` (D3, D4): `_positive(issue, "issue")`, `_positive(attempt, "attempt")`, then `identity = blocker_id(failure)` (which validates), all before any write. A new id gets `{"id": identity, <each identity member deep-copied from failure>, "attempts": [{"issue": issue, "attempt": attempt}], "state": "open", "resolution": None}`. A known id gets the reference only when it is not already listed, and its list is re-sorted by `(issue, attempt)`; then `state` becomes `open` and `resolution` `None` (a resolved record is reopened). Content members are never written for a known id. Returns `identity`.
- `_references(value, label, attempts)` (R3): a non-empty list (`<label>: must be a non-empty list`); each entry `_closed(entry, f"{label}[{i}]", _REFERENCE_MEMBERS)`, then `_positive` on `.issue` and `.attempt`; the `(issue, attempt)` keys strictly increase (`<label>: must be strictly increasing by issue and attempt`); each key is in `attempts` (`<label>[<i>]: names no attempt of this run`).
- `_resolution(record, label)` (R4): `open` requires `resolution is None` (`<label>.resolution: must be null while open`); a state other than `open`/`resolved` is `<label>.state: must be open or resolved`; `resolved` requires `_closed(resolution, f"{label}.resolution", {"facts"})`, `_valued_facts(resolution["facts"], f"{label}.resolution.facts")`, the same `[(name, source)]` list as the record's facts (`<label>.resolution.facts: must keep the record's names and sources`) and at least one `value` different from the record's fact at the same position (`<label>.resolution.facts: must change at least one value`).
- `validate_blockers(blockers, pointers) -> None` (R1–R5, D3–D5): not a dict is `verification_blockers: must be an object`. For each `key, record` with `label = f"verification_blockers[{_shown(key)}]"`: `_closed(record, label, _RECORD_MEMBERS)` (R2); `record["id"] != key` is `<label>.id: must equal its key`; rebuild `{"kind": FAILURE_KIND, "schema_version": SCHEMA_VERSION, <the four identity members>}` and take its `blocker_id`, mapping a `BlockerRefused` to `<label>: <that refusal>` (so c1's shape, secret-shape and 2,048-byte rules hold); an id that differs is `<label>.id: must be the identity of its content` (R1); then `_references(record["attempts"], f"{label}.attempts", pointers)` and `_resolution(record, label)`. Last (R5): every non-null pointer must name a record whose `attempts` lists `{"issue": issue, "attempt": attempt}`, else `verification_blockers: attempt <issue>:<attempt> points at <pointer>, which does not list it`, each of the three through `_shown`.
- `upgrade_ten(document) -> dict` (D9): a dict whose `schema_version` is the `int` 10, else `schema_version: must be 10`; a present `verification_blockers` is `verification_blockers: present before schema 11`; `issues` not a dict is `issues: must be an object`; an entry that is not a dict with a list `attempts` is `issues[<key>]: must be an object with an attempts list` (`<key>` through `_shown` here and below); an attempt that is not a dict is `issues[<key>].attempts[<i>]: must be an object`; a present pointer is `issues[<key>].attempts[<i>].verification_blocker: present before schema 11`. Every check runs before the copy. Returns `copy.deepcopy(document)` with `schema_version` 11, `verification_blockers` `{}` and every attempt's `verification_blocker` `None`.

Module docstring: replace the paragraph that begins `A validator returns its argument itself` with the first block below, then end the "content identity" bullet with `;` and add the second block after it:

```text
A shape validator returns its argument itself, never a copy, and never mutates
it; `validate_blockers` returns None and mutates nothing. Every refusal is one
`BlockerRefused` whose message is one line, `<field>: <reason>`, with any map key
or pointer it names JSON-escaped.
```


```text
- the ledger's schema-11 rules (issue 544 D2-D5, D9): `park`, which records an attempt
  parked on a failure in the run's blocker map, `validate_blockers`, which checks that map
  against the run's attempt pointers, and `upgrade_ten`, the strict 10 -> 11 step.
```

`python/README.md`, `## verification-observe`, first paragraph (nothing else in the file changes; no caller exists until Task 2): in the sentence that begins `` `agent_tools.verification_blocker` is the pure module``, the words from `and its validators return their argument` to the sentence's end become the first block below, and the second block is inserted as the next sentence:

```text
its three shape validators return their argument, and every refusal is one `BlockerRefused` line, `<field>: <reason>`.
```

```text
It also holds the schema-11 ledger rules (issue 544): `park` records an attempt parked on a failure in a run's `verification_blockers` map, `validate_blockers` checks that map against the run's attempt pointers and returns nothing, and `upgrade_ten` is the strict 10 → 11 ledger step; a map key or pointer named in their refusals is JSON-escaped, so each refusal stays one line.
```

- [ ] **Step 4: Verify**

Run (timeout 300 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_verification_blocker.py 2>&1 | tail -3'`
Expected: `Ran 24 tests` and `OK`.

Run: `if grep -nE '^(import|from) ' python/agent_tools/verification_blocker.py | grep -vE 'import (copy|json|re|unicodedata)$|^[0-9]+:from (collections\.abc|agent_tools\.canonical) import'; then exit 1; fi; grep -c 'upgrade_ten' python/README.md`
Expected: no import line printed, then `1`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/verification_blocker.py tests/test_verification_blocker.py python/README.md
launch-commit … -- -m "feat(verification): ledger rules for shared blockers (issue 544)" -m "<session trailers>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"88f0fed6fb92a233e666ca2b648c0c8c196a2ccb","head":"64fe45276198801797aa8fc0211e10963199c1fc"}],"commit_subject_bytes":[64,64,64],"id":1,"records":[{"bounds":[{"added_lines":200,"boundary":"all","deleted_lines":15,"record_bytes":14336,"support":{"covers":["r1a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1a","last_task":1,"owner":1,"path":"python/agent_tools/verification_blocker.py"},{"bounds":[{"added_lines":240,"boundary":"all","deleted_lines":10,"record_bytes":15360,"support":{"covers":["r1b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1b","last_task":1,"owner":1,"path":"tests/test_verification_blocker.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":13312,"support":{"covers":["r1c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1c","last_task":1,"owner":1,"path":"python/README.md"}]}}
```
