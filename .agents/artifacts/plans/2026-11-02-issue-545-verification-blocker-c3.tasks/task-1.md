# Task 1: Resolution rules and the resume predicate

**Files:**
- Modify: `python/agent_tools/verification_blocker.py` (module docstring list; `requirement`, `validate_observations` and `resolve`, inserted immediately before `def validate_blockers`)
- Modify: `tests/test_verification_blocker.py` (three classes and two helpers before `if __name__ == "__main__":`)
- Modify: `python/agent_tools/attempt_custody.py` (the comment above `BLOCKED_ON_VALUES`; `resume_permitted`)
- Modify: `tests/test_attempt_custody.py` (`VocabularyTest.test_three_cause_classes_partition_the_attempt_causes`)
- Modify: `python/README.md` (`## verification-observe`, first paragraph: one sentence added)

**Interfaces:**
- Consumes: `verification_blocker`'s `BlockerRefused`, `REQUIREMENT_KIND`, `_refuse`, `validate_observation`, `validate_requirement` (c1); the schema-11 record shape `park` writes (c2).
- Produces (Tasks 2–4 import these exact names):
  - `requirement(record: Mapping) -> dict`
  - `validate_observations(value: object) -> list`
  - `resolve(blockers: dict, observations: object) -> tuple[frozenset[str], frozenset[str]]` — `(resolved ids, equal ids)`
  - `attempt_custody.resume_permitted(blocked_on: str, *, human_directed: bool, blocker_resolved: bool = False) -> bool`

**Invariants:**
- `verification_blocker` stays pure and imports only what it imports now (issue 543 D15; D2).
- `requirement` builds a new object and never mutates the record; `validate_observations` returns its argument itself; `resolve` checks every observation before it changes anything, changes only `blockers`, and never `observations` (D2, D4).
- Every refusal is one `BlockerRefused` line; the tests read the exact texts below.
- `resume_permitted` keeps its answer for every existing call: `blocker_resolved` defaults to the fail-closed `False` (D5).

- [ ] **Step 1: Write the failing tests**

In `tests/test_verification_blocker.py`, insert this block between the end of `UpgradeTenTest` and `if __name__ == "__main__":` (two blank lines before each top-level definition). It reuses the module's `A`, `B`, `PINNED_ID`, `ZERO_ID`, `fact`, `failure`, `edited`, `record` and `changed_facts`.

```python
AT = ("facts", 0, "value", "objects", 0)
OTHER = failure(facts=[fact("a-lock", ("a.lock", "b.lock")), fact("c-lock", ("c.lock",))])
OTHER_ID = vb.blocker_id(OTHER)


def observed(value=None, **changes):
    """The observation `verification-observe observe` prints for `value`'s record when
    nothing changed: its id, repository and facts (issue 545 D4)."""
    value = failure() if value is None else value
    result = {"kind": "verification-observation", "schema_version": 1,
              "blocker_id": vb.blocker_id(value),
              "repository": copy.deepcopy(value["repository"]),
              "facts": copy.deepcopy(value["facts"])}
    result.update(changes)
    return result


def run_blockers():
    """Two open records: the pinned one parked by 61:1, `OTHER` by 62:1."""
    return {PINNED_ID: record(), OTHER_ID: record(OTHER, attempts=((62, 1),))}


class RequirementTest(unittest.TestCase):
    def test_the_requirement_names_each_source_in_order_and_no_value(self):
        held = record(OTHER)
        before = copy.deepcopy(held)
        rendered = vb.requirement(held)
        self.assertEqual(rendered, {"kind": "verification", "blocker_id": OTHER_ID,
                                    "sources": [{"name": "a-lock", "paths": ["a.lock", "b.lock"]},
                                                {"name": "c-lock", "paths": ["c.lock"]}]})
        self.assertIs(vb.validate_requirement(rendered), rendered)
        rendered["sources"][0]["paths"].append("d.lock")
        self.assertEqual(held, before)


class ObservationListTest(unittest.TestCase):
    def test_a_list_of_distinct_observations_is_returned_itself(self):
        value = [observed(), observed(OTHER)]
        self.assertIs(vb.validate_observations(value), value)
        empty = []
        self.assertIs(vb.validate_observations(empty), empty)

    def test_a_bad_list_is_refused_naming_the_element(self):
        cases = {
            "not a list": ({"0": observed()}, "verification: must be a list"),
            "invalid element": ([observed(), observed(schema_version=2)],
                                "verification[1]: observation.schema_version: must be 1"),
            "secret-shaped": ([observed(facts=[fact(paths=(".env",))])],
                              "verification[0]: facts[0].source.paths[0]: secret-shaped"),
            "repeated id": ([observed(), observed()],
                            "verification[1].blocker_id: repeats an earlier observation"),
        }
        for label, (value, line) in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(vb.BlockerRefused) as caught:
                    vb.validate_observations(value)
                self.assertEqual(str(caught.exception), line)


class ResolveTest(unittest.TestCase):
    POINTERS = {(61, 1): None, (62, 1): None}

    def test_an_equal_observation_resolves_nothing(self):
        blockers = run_blockers()
        before = copy.deepcopy(blockers)
        self.assertEqual(vb.resolve(blockers, [observed()]),
                         (frozenset(), frozenset({PINNED_ID})))
        self.assertEqual(blockers, before)
        self.assertEqual(vb.resolve(blockers, []), (frozenset(), frozenset()))

    def test_a_changed_value_resolves_with_a_copy_of_the_observed_facts(self):
        deleted = edited(edited(observed(), (*AT, "object"), None), (*AT, "mode"), None)
        for label, value in (("object", edited(observed(), (*AT, "object"), B)),
                             ("mode only", edited(observed(), (*AT, "mode"), "100755")),
                             ("path deleted", deleted)):
            with self.subTest(change=label):
                blockers = run_blockers()
                self.assertEqual(vb.resolve(blockers, [value]),
                                 (frozenset({PINNED_ID}), frozenset()))
                self.assertEqual(blockers, {
                    PINNED_ID: record(state="resolved", resolution={"facts": value["facts"]}),
                    OTHER_ID: record(OTHER, attempts=((62, 1),))})
                self.assertIsNone(vb.validate_blockers(blockers, self.POINTERS))
                value["facts"][0]["name"] = "renamed"
                self.assertEqual(blockers[PINNED_ID]["resolution"]["facts"][0]["name"],
                                 "flake-lock")

    def test_one_equal_beside_one_changed_resolves_only_the_changed(self):
        blockers = run_blockers()
        changed = edited(observed(OTHER), ("facts", 1, "value", "objects", 0, "object"), B)
        self.assertEqual(vb.resolve(blockers, [observed(), changed]),
                         (frozenset({OTHER_ID}), frozenset({PINNED_ID})))
        self.assertEqual(blockers[PINNED_ID], record())
        self.assertEqual(blockers[OTHER_ID], record(OTHER, attempts=((62, 1),),
                                                    state="resolved",
                                                    resolution={"facts": changed["facts"]}))

    def test_an_observation_that_answers_no_open_blocker_exactly_is_refused(self):
        resolved = run_blockers()
        resolved[PINNED_ID].update(state="resolved", resolution={"facts": changed_facts()})
        two = observed(OTHER)
        moved = observed()
        moved["facts"][0]["source"]["paths"] = ["other.lock"]
        moved["facts"][0]["value"]["objects"][0]["path"] = "other.lock"
        unknown = "verification[0].blocker_id: names no open blocker of this run"
        sources = "verification[0].facts: must carry the blocker's names and sources in order"
        cases = {
            "unknown id": (run_blockers(), observed(blocker_id=ZERO_ID), unknown),
            "resolved record": (resolved, observed(), unknown),
            "other repository": (run_blockers(), edited(
                observed(), ("repository", "integration_branch"), "release"),
                "verification[0].repository: must equal the blocker's repository"),
            "missing fact": (run_blockers(), {**two, "facts": two["facts"][:1]}, sources),
            "extra fact": (run_blockers(), {**observed(), "facts": observed()["facts"] + [
                fact("g-lock", ("g.lock",))]}, sources),
            "renamed fact": (run_blockers(), edited(observed(), ("facts", 0, "name"),
                                                    "flake-lockfile"), sources),
            "substituted source": (run_blockers(), moved, sources),
            "reordered facts": (run_blockers(), {**two, "facts": two["facts"][::-1]},
                                "verification[0]: facts[1].name: must be sorted and unique"),
        }
        for label, (blockers, value, line) in cases.items():
            with self.subTest(case=label):
                before, kept = copy.deepcopy(blockers), copy.deepcopy(value)
                with self.assertRaises(vb.BlockerRefused) as caught:
                    vb.resolve(blockers, [value])
                self.assertEqual(str(caught.exception), line)
                self.assertEqual((blockers, value), (before, kept))

    def test_a_refused_later_observation_leaves_the_earlier_record_open(self):
        blockers = run_blockers()
        before = copy.deepcopy(blockers)
        values = [edited(observed(), (*AT, "object"), B), observed(blocker_id=ZERO_ID)]
        kept = copy.deepcopy(values)
        with self.assertRaises(vb.BlockerRefused) as caught:
            vb.resolve(blockers, values)
        self.assertEqual(str(caught.exception),
                         "verification[1].blocker_id: names no open blocker of this run")
        self.assertEqual((blockers, values), (before, kept))
```

In `tests/test_attempt_custody.py`, `VocabularyTest.test_three_cause_classes_partition_the_attempt_causes`, replace the inner `with self.subTest(cause=cause, human_directed=directed):` block (one `assertIs`) with:

```python
                with self.subTest(cause=cause, human_directed=directed):
                    self.assertIs(ac.resume_permitted(cause, human_directed=directed), expected)
                    self.assertIs(ac.resume_permitted(cause, human_directed=directed,
                                                      blocker_resolved=False), expected)
                if cause in ac.OBSERVATION_GATED_BLOCKED_ON:
                    with self.subTest(cause=cause, human_directed=directed, resolved=True):
                        self.assertIs(ac.resume_permitted(cause, human_directed=directed,
                                                          blocker_resolved=True), True)
                else:
                    with self.subTest(cause=cause, human_directed=directed, resolved=True), \
                            self.assertRaises(ValueError):
                        ac.resume_permitted(cause, human_directed=directed,
                                            blocker_resolved=True)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 300 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_verification_blocker.py tests/test_attempt_custody.py 2>&1 | tail -3'`
Expected: `Ran 65 tests` and `FAILED (errors=56)`: 36 `TypeError: resume_permitted() got an unexpected keyword argument 'blocker_resolved'`, 14 `AttributeError` for `resolve`, 5 for `validate_observations`, 1 for `requirement`; every other test passes.

- [ ] **Step 3: Write the rules**

`python/agent_tools/verification_blocker.py`, module docstring: end the "ledger's schema-11 rules" bullet with `;` instead of `.` and add after it:

```text
- the resolution rules (issue 545 D2, D4): `requirement`, the requirement that asks for
  an observation of a record, `validate_observations`, the check of a request's list of
  observations, and `resolve`, which marks each record an observation changes `resolved`.
```

Insert before `def validate_blockers`, each with a docstring stating the contract below:
- `requirement(record)` (D2): returns `validate_requirement({"kind": REQUIREMENT_KIND, "blocker_id": record["id"], "sources": [{"name": fact["name"], "paths": list(fact["source"]["paths"])} for fact in record["facts"]]})`.
- `validate_observations(value)` (D4): not a list is `verification: must be a list`; each element through `validate_observation`, a `BlockerRefused` re-raised as `verification[<i>]: <that refusal>`; a `blocker_id` seen earlier in the list is `verification[<i>].blocker_id: repeats an earlier observation`. Returns `value`.
- `resolve(blockers, observations)` (D2, D4): first `validate_observations(observations)`. Then, for each observation in order, with `label = f"verification[{index}]"`, before any change: `blockers.get(blocker_id)` that is `None` or whose `state` is not `open` is `<label>.blocker_id: names no open blocker of this run`; a `repository` unequal to the record's is `<label>.repository: must equal the blocker's repository`; a `[(name, source)]` list unequal to the record's is `<label>.facts: must carry the blocker's names and sources in order`. Only then, per observation: when every `value` equals the record's at the same position the id joins `equal` and the record is untouched; otherwise `state` becomes `resolved`, `resolution` becomes `{"facts": copy.deepcopy(observation["facts"])}` and the id joins `resolved`. Returns `(frozenset(resolved), frozenset(equal))`.

`python/agent_tools/attempt_custody.py`: the comment's last sentence above `BLOCKED_ON_VALUES` becomes `It is observation-gated: only a resolution of the blocker it names releases it, and a human re-entry never does (issue 544 D6, issue 545 D5).` `resume_permitted` gains the keyword `blocker_resolved: bool = False`. After the existing `BLOCKED_ON_VALUES` check: a cause in `OBSERVATION_GATED_BLOCKED_ON` returns `blocker_resolved`; otherwise a true `blocker_resolved` raises `ValueError(f"blocker_resolved applies only to an observation-gated cause, not {blocked_on!r}")`; the rest is unchanged. Its docstring now says an observation-gated cause resumes exactly when `blocker_resolved` says its blocker is resolved, whatever `human_directed` says (issue 545 D5), and lists the new `ValueError`.

`python/README.md`, `## verification-observe`, first paragraph: insert after the sentence ending `so each refusal stays one line.`:

```text
Its resolution rules (issue 545) are `requirement`, which renders the `verification` requirement that asks for an observation of a record (its id and each fact's name and paths, in order, with no value), `validate_observations`, which checks a request's list of observations (each one valid, no `blocker_id` twice) and returns it, and `resolve`, which first checks that every observation names an `open` record of the run's map, carries its `repository` and exactly its fact names and sources in order, refusing the whole list otherwise, and then marks each record with at least one changed value `resolved` with a copy of the observed facts, returning the resolved and the equal ids.
```

- [ ] **Step 4: Verify**

Run (timeout 300 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_verification_blocker.py tests/test_attempt_custody.py 2>&1 | tail -3'`
Expected: `Ran 65 tests` and `OK`.
Run: `if grep -nE '^(import|from) ' python/agent_tools/verification_blocker.py | grep -vE 'import (copy|json|re|unicodedata)$|^[0-9]+:from (collections\.abc|agent_tools\.canonical) import'; then exit 1; fi; grep -c 'validate_observations' python/README.md`
Expected: no import line printed, then `1`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/verification_blocker.py tests/test_verification_blocker.py python/agent_tools/attempt_custody.py tests/test_attempt_custody.py python/README.md
launch-commit … -- -m "feat(verification): resolution rules and predicate (issue 545)" -m "<session trailers>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":1,"records":[{"bounds":[{"added_lines":85,"boundary":"all","deleted_lines":5,"record_bytes":7680,"support":{"covers":["r1a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1a","last_task":1,"owner":1,"path":"python/agent_tools/verification_blocker.py"},{"bounds":[{"added_lines":170,"boundary":"all","deleted_lines":5,"record_bytes":10240,"support":{"covers":["r1b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1b","last_task":1,"owner":1,"path":"tests/test_verification_blocker.py"},{"bounds":[{"added_lines":20,"boundary":"all","deleted_lines":10,"record_bytes":5632,"support":{"covers":["r1c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1c","last_task":1,"owner":1,"path":"python/agent_tools/attempt_custody.py"},{"bounds":[{"added_lines":15,"boundary":"all","deleted_lines":3,"record_bytes":3072,"support":{"covers":["r1d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1d","last_task":1,"owner":1,"path":"tests/test_attempt_custody.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":15872,"support":{"covers":["r1e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1e","last_task":2,"owner":1,"path":"python/README.md"}]}}
```
