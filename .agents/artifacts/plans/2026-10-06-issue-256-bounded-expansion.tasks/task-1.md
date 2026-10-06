# Task 1: Expansion budget and the issue-100 expander

The decode bound moves into a new module with the expansion budget, and `expand_100` charges every row it builds and derives `edge_refs` in linear time (spec § *Solution*, § *Decisions*; D1, D2, D3, D4, D5, D6, D8). Issue 121 is untouched until Task 2.

**Files:**
- Create: `python/agent_tools/review_expansion.py`
- Modify: `python/agent_tools/review_witness.py` (import of the bound only)
- Modify: `python/agent_tools/review_issue100.py`
- Create: `tests/test_review_expansion.py`
- Modify: `tests/retained_review_test_support.py` (first of two contributions)
- Modify: `tests/test_review_compact100.py`
- Modify: `tests/test_review_replay.py` (first of two)
- Modify: `justfile` (add `    tests/test_review_expansion.py \` immediately before `    tests/test_review_issue121.py \` in `agent-workflow-tests`)

**Interfaces:**
- Consumes: in `review_issue100`, `expand_100(payload)`, `model_100(...)`, `_refs(edges, path)`, `_at`, `_rows`, `_columns`, `_unpacked`, `_identified`, `_at_head`, `Issue100Error`; in `review_witness`, `MEMBER_MAX_BYTES = 1048576`; `review_forecast.canonical_bytes`; in the replay suite, `ReplayTest.shared`, `ReplayTest.models`, `ReplayTest.rebound`, `GROUPS`.
- Produces (`review_expansion`):
  - `MEMBER_MAX_BYTES = 1048576`, the one home of the decode bound. `review_witness` imports it, so `review_witness.MEMBER_MAX_BYTES` keeps its name and value; `review_derivation` keeps importing it from `review_witness` (D2, D5).
  - `Budget(refusal: Callable[[], Exception])`: reads `MEMBER_MAX_BYTES` when constructed. `add(size: int) -> None` adds `size` and raises `refusal()` once the total exceeds the bound (a total equal to it passes). `charge(value) -> value` adds `len(canonical_bytes(value))` and returns `value`; a value `canonical_bytes` cannot encode (`TypeError`, `ValueError`) raises `refusal()` from it.
- Produces (`review_issue100`): `_refs(edges, budget=None) -> Callable[[str], list]` (private; signature fixed here so that Task 2's reviewer can compare it with `_lineage`).
- Produces (`tests/retained_review_test_support.py`, used by Task 2): `BUNDLE`, `BOUND_SECONDS = 5.0`, `BOUND_PEAK = 32 * 2**20`, `WINDOW = (1_000_000, MEMBER_MAX_BYTES)`, `LONG`, `Overtime`, `measured(call, *, traced=False, seconds=BOUND_SECONDS) -> (error, elapsed, peak)`, `committed(name) -> dict`, `maximal(build) -> (payload, size)`, `rename_chain_100(n)`, `SITES_100`, `amplified_100(site)`, and the private `_repacked(text, extra)`.
- Produces (`tests/test_review_replay.py`): module-level `FORGED`, a tuple of `(member name, builder, error type)` rows, and `ReplayTest.test_maximal_forged_member_is_refused_within_the_bound`, which loops over it. Task 2 appends the issue-121 row.

**Invariants:**
- `expand_100` of the committed issue-100 payload has canonical bytes of length 341,492 and SHA-256 `5d10b020a087be9cba8ea38906fd2f7b656bb8b8f39b7b17d272b7a01b1022df`, as at `DELIVERY_BASE`; `model_100` builds the same model as before for every fixture (the compact and issue-100 suites pass unchanged).
- Each `expand_100` call starts one fresh `Budget(lambda: Issue100Error("invalid_payload"))` before it builds any row; `compact_100` and `validate_100` charge through the `expand_100` calls they make, and `model_100` charges nothing (D3, D4).
- `expand_100` raises only `Issue100Error("invalid_payload")` for any JSON value; a charge never lets `TypeError` or `ValueError` escape.
- No cap, decode bound, refusal code or check order changes; `validate_100` is unchanged apart from what `expand_100` now refuses (D7).

- [ ] **Step 1: Write the failing tests.**

`tests/test_review_expansion.py` (new):

```python
"""The expansion budget of the retained compact payloads (issue 256; D2, D3, D5)."""
import unittest
from unittest.mock import patch

from agent_tools import review_expansion, review_witness
from agent_tools.review_expansion import MEMBER_MAX_BYTES, Budget
from agent_tools.review_forecast import canonical_bytes


class Refused(Exception):
    pass


class BudgetTest(unittest.TestCase):
    def test_the_bound_is_the_decode_bound_with_one_home(self):
        self.assertEqual(MEMBER_MAX_BYTES, 1048576)
        self.assertIs(review_witness.MEMBER_MAX_BYTES, review_expansion.MEMBER_MAX_BYTES)

    def test_charges_sum_canonical_bytes_up_to_the_bound(self):
        budget, row = Budget(Refused), {"path": "a", "bytes": 1}
        self.assertIs(budget.charge(row), row)
        budget.add(MEMBER_MAX_BYTES - len(canonical_bytes(row)))  # exactly at the bound
        with self.assertRaises(Refused):
            budget.add(1)

    def test_the_bound_is_read_when_a_budget_starts(self):
        with patch("agent_tools.review_expansion.MEMBER_MAX_BYTES", 10):
            small = Budget(Refused)
        large = Budget(Refused)
        large.add(11)
        with self.assertRaises(Refused):
            small.add(11)

    def test_an_unencodable_value_is_the_refusal(self):
        for value in (object(), {1: "a", "b": 2}, {1, 2}):
            with self.subTest(value=repr(value)):
                with self.assertRaises(Refused):
                    Budget(Refused).charge(value)


if __name__ == "__main__":
    unittest.main()
```

`tests/retained_review_test_support.py`: add `base64`, `signal`, `time` and `tracemalloc` to the imports, plus `from agent_tools.review_expansion import MEMBER_MAX_BYTES` and `from agent_tools.review_forecast import canonical_bytes`, and append:

```python
BUNDLE = SOURCE / "tests/fixtures/retained-review-evidence"
BOUND_SECONDS, BOUND_PEAK = 5.0, 32 * 2**20  # the stated bound of a maximal forged member (issue 256 D6)
WINDOW = (1_000_000, MEMBER_MAX_BYTES)  # a maximal forged member's canonical bytes
LONG = "L" * 120_000  # one long path, referenced at a single charged site


class Overtime(Exception):
    """The interval timer of `measured` fired inside the call."""


def _overtime(signum, frame):
    raise Overtime()


def measured(call, *, traced=False, seconds=BOUND_SECONDS) -> tuple:
    """`(exception or None, elapsed seconds, traced peak bytes)` of `call()` under a `seconds` interval
    timer, which raises `Overtime` inside the call, so a slow call fails at the bound instead of hanging.
    The peak is `tracemalloc`'s, taken only when `traced`; time is meaningful only on an untraced call (D7)."""
    previous = signal.signal(signal.SIGALRM, _overtime)
    if traced:
        tracemalloc.start()
    error, start = None, time.perf_counter()
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        try:
            call()
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    except Exception as exc:  # the caller asserts which one
        error = exc
    elapsed = time.perf_counter() - start
    peak = tracemalloc.get_traced_memory()[1] if traced else 0
    if traced:
        tracemalloc.stop()
    signal.signal(signal.SIGALRM, previous)
    return error, elapsed, peak


def committed(name: str) -> dict:
    """A fresh decode of the committed retained payload `name`."""
    return json.loads((BUNDLE / name).read_bytes())


def _repacked(text: str, extra: bytes) -> str:
    """The base85 string `text` with the raw bytes `extra` appended to what it packs."""
    return base64.b85encode(base64.b85decode(text) + extra).decode("ascii")


def maximal(build) -> tuple:
    """`(payload, canonical bytes)` of `build(n)` for the largest `n` it finds whose bytes fit `WINDOW`."""
    low, high = 1, 1
    while len(canonical_bytes(build(high))) < WINDOW[0]:
        low, high = high, high * 2
    while low < high:
        middle = (low + high + 1) // 2
        if len(canonical_bytes(build(middle))) <= WINDOW[1]:
            low = middle
        else:
            high = middle - 1
    payload = build(low)
    return payload, len(canonical_bytes(payload))


def _head_edge(payload) -> int:
    """The index of the head commit's first-parent edge in an issue-100 payload whose last commit is the head."""
    return sum(len(listed) for listed in payload["parents"][:-1])


def _added_at_head(payload, path: str) -> int:
    """Add `path` by the head's first-parent edge of an issue-100 payload; its path index."""
    payload["paths"].append(path)
    payload["edges"][_head_edge(payload)].append(len(payload["records"]))
    payload["records"].append(["A", len(payload["paths"]) - 1, None, 0, 1])
    payload["record_sha256"] = _repacked(payload["record_sha256"], bytes(32))
    return len(payload["paths"]) - 1


def _fresh(payload, paths: list) -> None:
    """Append one fresh row per path index, with no live entry, to an issue-100 payload."""
    fresh = payload["tables"]["fresh"]
    fresh["paths"] += paths
    fresh["bytes"] += [1] * len(paths)
    fresh["sha256"] = _repacked(fresh["sha256"], bytes(32 * len(paths)))
    payload["live"] += [None] * len(paths)


def rename_chain_100(n: int) -> dict:
    """The committed issue-100 payload plus a chain of `n` renames, `forged/0` to `forged/n`, on the head's
    first-parent edge, and one fresh row on every path of the chain (#254's I1)."""
    payload = committed("issue-100-derived.json")
    start, edge = len(payload["paths"]), _head_edge(payload)
    payload["paths"] += [f"forged/{k}" for k in range(n + 1)]
    for k in range(n):
        payload["edges"][edge].append(len(payload["records"]))
        payload["records"].append(["R100", start + k + 1, None, 0, 1, start + k])
    payload["record_sha256"] = _repacked(payload["record_sha256"], bytes(32 * n))
    _fresh(payload, list(range(start, start + n + 1)))
    return payload


SITES_100 = ("parent_edge", "tree_entry", "edge_record", "historical_row", "fresh_row", "contribution", "overlap")


def amplified_100(site: str) -> dict:
    """The committed issue-100 payload with the rows of one charged site of `expand_100` amplified past
    the budget. Each is well formed: before issue 256 every one expanded without refusal (D8)."""
    payload = committed("issue-100-derived.json")
    if site == "parent_edge":  # 150,000 more parents of the head, each with an empty edge
        payload["parents"][-1] += [0] * 150_000
        payload["edges"] += [[]] * 150_000
    elif site == "tree_entry":  # 36,000 more entries, never referenced
        payload["entries"].append(["100644", "blob", _repacked("", bytes(20 * 36_000))])
    elif site == "edge_record":  # one record referenced 100,000 more times
        payload["edges"][_head_edge(payload)] += [0] * 100_000
    elif site == "historical_row":
        old = payload["tables"]["historical"]
        old["bytes"] += [0] * 20_000
        old["sha256"] = _repacked(old["sha256"], bytes(32 * 20_000))
    elif site == "fresh_row":  # twelve fresh rows on one long path
        _fresh(payload, [_added_at_head(payload, LONG)] * 12)
    elif site == "contribution":  # 2,000 fresh rows on a path with 100 records
        path = _added_at_head(payload, "forged")
        payload["edges"][_head_edge(payload)] += [len(payload["records"]) - 1] * 99
        _fresh(payload, [path] * 2_000)
    elif site == "overlap":  # ten overlaps on one long fresh path
        path = _added_at_head(payload, LONG)
        _fresh(payload, [path])
        payload["pending_overlaps"] += [[path, None]] * 10
        payload["overlap_sha256"] = _repacked(payload["overlap_sha256"], bytes(96 * 10))
    return payload
```

`tests/test_review_compact100.py`: extend the support import with `BOUND_PEAK, BOUND_SECONDS, SITES_100, WINDOW, amplified_100, committed, maximal, measured, rename_chain_100`, and append:

```python
class Bounded100Test(unittest.TestCase):
    """Issue 256: what `expand_100` builds from a forged payload is bounded (D3, D6, D8)."""

    def refused(self, payload, *, bound=True):
        for traced in ((False, True) if bound else (False,)):
            error, elapsed, peak = measured(lambda: expand_100(payload), traced=traced)
            self.assertIsInstance(error, Issue100Error, f"{error!r} after {elapsed:.2f} s")
            self.assertEqual(error.code, "invalid_payload")
            if traced:
                self.assertLess(peak, BOUND_PEAK)
            else:
                self.assertLess(elapsed, BOUND_SECONDS)

    def test_maximal_rename_chain_is_refused_within_the_bound(self):
        self.assertEqual(expand_100(rename_chain_100(20))["schema_version"], 1)  # the forgery is well formed
        payload, size = maximal(rename_chain_100)
        self.assertTrue(WINDOW[0] <= size <= WINDOW[1], size)
        self.refused(payload)

    def test_each_amplified_site_is_refused(self):
        for site in SITES_100:
            with self.subTest(site=site):
                self.refused(amplified_100(site), bound=False)

    def test_the_budget_reads_the_public_bound(self):
        payload = committed("issue-100-derived.json")
        self.assertEqual(expand_100(payload)["schema_version"], 1)
        with patch("agent_tools.review_expansion.MEMBER_MAX_BYTES", 100_000):  # below the real model's charge
            with self.assertRaises(Issue100Error) as caught:
                expand_100(payload)
        self.assertEqual(caught.exception.code, "invalid_payload")
```

`tests/test_review_replay.py`: extend the support import with `BOUND_PEAK, BOUND_SECONDS, maximal, measured, rename_chain_100`; after `ZERO = ...` add

```python
FORGED = (("issue-100-derived.json", rename_chain_100, Issue100Error),)  # maximal forged members (issue 256)
```

and add to `ReplayTest`:

```python
    def test_maximal_forged_member_is_refused_within_the_bound(self):
        """Decoding and expanding a maximal forged member under the forger's own digest (issue 256 D6). The
        witness keeps the portable tables: expansion refuses before the tables are compared."""
        source, expected, kwargs = self.shared()
        for name, build, error_type in FORGED:
            with self.subTest(member=name):
                bundle = Path(shutil.copytree(source, self.tmp / name))
                anchor, raw = authenticate(bundle, expected)
                payloads = {member: json.loads(data) for member, data in raw.items()}
                models = self.models(payloads)
                forged, size = maximal(build)
                raw = {**raw, name: canonical_bytes(forged)}
                forger, _ = self.rebound(bundle, {group: anchor[group] for group in GROUPS}, payloads, raw, models)
                for traced in (False, True):
                    error, elapsed, peak = measured(lambda: replay(bundle, forger, **kwargs), traced=traced)
                    self.assertIsInstance(error, error_type, f"{error!r} after {elapsed:.2f} s ({size} B)")
                    self.assertEqual(error.code, "invalid_payload")
                    if traced:
                        self.assertLess(peak, BOUND_PEAK)
                    else:
                        self.assertLess(elapsed, BOUND_SECONDS)
```

- [ ] **Step 2: Run them and watch them fail.**

```bash
PYTHONPATH=python timeout 600 python3 -m unittest tests.test_review_expansion 2>&1 | tail -3
PYTHONPATH=python timeout 600 python3 -m unittest tests.test_review_compact100.Bounded100Test 2>&1 | tail -3
```

Expected at the starting commit: both fail with `ModuleNotFoundError: No module named 'agent_tools.review_expansion'`. To see the bound fail on the tree #254 delivered, temporarily make the support module's import `from agent_tools.review_witness import MEMBER_MAX_BYTES` and run `Bounded100Test.test_maximal_rename_chain_is_refused_within_the_bound`: it fails with `Overtime() after 5.00 s`. Restore the import before Step 3.

- [ ] **Step 3: Implement.**

1. `review_expansion.py`: a module docstring saying it holds the decode bound of a retained bundle member, which `review_witness` imports, and the per-call budget the two expanders charge (issue 256). Then exactly:

```python
MEMBER_MAX_BYTES = 1048576


class Budget:
    """Canonical bytes one expansion has built, at most `MEMBER_MAX_BYTES` as read when it is created."""

    def __init__(self, refusal: Callable[[], Exception]) -> None:
        self._limit, self._spent, self._refusal = MEMBER_MAX_BYTES, 0, refusal

    def add(self, size: int) -> None:
        self._spent += size
        if self._spent > self._limit:
            raise self._refusal()

    def charge(self, value):
        try:
            size = len(canonical_bytes(value))
        except (TypeError, ValueError) as exc:
            raise self._refusal() from exc
        self.add(size)
        return value
```

2. `review_witness.py`: delete `MEMBER_MAX_BYTES = 1048576` and import the name from `agent_tools.review_expansion`. Nothing else changes.

3. `review_issue100._refs(edges, budget=None)` replaces `_refs(edges, path)`. One pass unions each record's `path` and `old_path` (a union–find over path strings); a second pass, in edge order and then record order, appends `[e, r]` to the list of its record's `path` root. It returns `lookup(path)`: a fresh `list` copy of the list of `path`'s root (`[]` for a path no record names), charging each copied element with `budget.charge` when `budget` is given. That is exactly the old fixed point's output, the rename-connected component in edge and record order (D4). Its docstring states that rule and that the lookup copies. `model_100` builds `refs = _refs(edges)` once, after its edge loop, and calls `refs(path)` per fresh record.

4. `expand_100` (D3, D4): construct `budget = Budget(lambda: Issue100Error("invalid_payload"))` before building any row, then charge each row as it is built, before it joins the model:
   - a parent edge: `type(p) is int and 0 <= p <= i` replaces `_at(nodes[:i + 1], p)` and indexes `nodes[p]`;
   - a tree entry, as `entries` is built (one charge per entry dict);
   - a dereferenced edge record, inside `record(index)`;
   - a historical row and a fresh row;
   - a contribution: `edge_refs` comes from `refs = _refs(edges, budget)` built once before the contribution loop, so each pair is charged as copied; the rest of the row, its id included, is charged once with `edge_refs` left out (charge `{**row, "edge_refs": []}` after `_identified`);
   - an overlap, once identified.
   The range, criteria text and policies copied from the payload are not charged, and `_at_head` and the post-expansion validators are unchanged (D7). In the docstring, replace "and nothing bounds the memory that the model of a large payload takes" with: "Every row it builds is charged, as it is built, to a budget of `review_expansion.MEMBER_MAX_BYTES` canonical bytes read when the call starts, and the first charge past it is `invalid_payload`, so the work a payload causes is bounded by its size and that budget."

4a. The docstring sentence above must stay true of the code as built; if the implementation charges a site differently from this list, rewrite the sentence from the code and name the difference in the task report.

5. Add the `justfile` line.

- [ ] **Step 4: Verify.**

```bash
set -euo pipefail
PYTHONPATH=python timeout 2400 python3 -m unittest tests.test_review_expansion tests.test_review_compact100 \
  tests.test_review_issue100 tests.test_review_witness tests.test_review_derivation tests.test_review_replay \
  tests.test_review_evidence 2>&1 | tail -3
PYTHONPATH=python python3 -c '
import hashlib, json
from agent_tools.review_forecast import canonical_bytes
from agent_tools.review_issue100 import expand_100
model = canonical_bytes(expand_100(json.load(open("tests/fixtures/retained-review-evidence/issue-100-derived.json"))))
assert (len(model), hashlib.sha256(model).hexdigest()) == (341492, "5d10b020a087be9cba8ea38906fd2f7b656bb8b8f39b7b17d272b7a01b1022df")'
if grep -q 'nodes\[:i + 1\]' python/agent_tools/review_issue100.py; then exit 1; fi
if grep -q 'nothing bounds the memory' python/agent_tools/review_issue100.py; then exit 1; fi
if grep -qE '^MEMBER_MAX_BYTES = ' python/agent_tools/review_witness.py; then exit 1; fi
if ! just --show agent-workflow-tests | grep -q 'tests/test_review_expansion.py'; then exit 1; fi
git diff --stat 31be7292b40159c5a3f49cc24f21b3292ba4ce89 -- python/agent_tools | tail -1
timeout 7200 just agent-workflow-tests 2>&1 | tail -3
timeout 3600 just build 2>&1 | tail -3
```

The seven suites end `OK`; at the starting commit the first line fails on the missing module. The `--stat` line names exactly three files. The suites listed besides the new cases pass unchanged.

- [ ] **Step 5: Commit.** Stage only the eight Files. Check that `printf %s "$subject" | wc -c` is at most 64, then commit through `launch-commit` with `feat(review): bound issue-100 expansion by a budget (#256)`. A review-fix commit uses `fix(review): address Task-1 review findings (#256)`.

- [ ] **Step 6: G1 (controller).** Run the plan root's G1 at the new `HEAD`, record this task's `actual_ranges` and refresh `actual_evidence` in a process-only commit, then renew G0 at `--completed-through 1`.

## Forecast basis

Estimates. A modify record is the U7 diff against `DELIVERY_BASE` (#254's 315-line `review_issue100.py` diff measured 27,774 B); an add is the file plus one byte per line plus 512.
- `review_expansion.py`: about 45 lines and 1,800 B: 4,096 B / +60.
- `review_witness.py`: one import, one deleted line: 4,096 B / +3 / −2.
- `review_issue100.py`: `_refs` rewritten, `model_100` one call, about thirty charged lines and the docstring in `expand_100`: 26,624 B / +120 / −80.
- `tests/test_review_expansion.py`: the suite above (about 1,700 B): 4,096 B / +60.
- `tests/retained_review_test_support.py`, first of two: the block above (about 6,500 B, 150 lines) in one hunk: 12,288 B / +170 / −2.
- `tests/test_review_compact100.py`: 6,144 B / +45 / −2. `tests/test_review_replay.py`, first of two: 6,144 B / +35 / −2. `justfile`, the one line: 2,048 B / +1.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":1,"records":[{"bounds":[{"added_lines":60,"boundary":"bounded","deleted_lines":0,"record_bytes":4096,"support":{"covers":["t1-1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-1","last_task":1,"owner":1,"path":"python/agent_tools/review_expansion.py"},{"bounds":[{"added_lines":3,"boundary":"bounded","deleted_lines":2,"record_bytes":4096,"support":{"covers":["t1-2"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-2","last_task":1,"owner":1,"path":"python/agent_tools/review_witness.py"},{"bounds":[{"added_lines":120,"boundary":"bounded","deleted_lines":80,"record_bytes":26624,"support":{"covers":["t1-3"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-3","last_task":1,"owner":1,"path":"python/agent_tools/review_issue100.py"},{"bounds":[{"added_lines":60,"boundary":"bounded","deleted_lines":0,"record_bytes":4096,"support":{"covers":["t1-4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-4","last_task":1,"owner":1,"path":"tests/test_review_expansion.py"},{"bounds":[{"added_lines":170,"boundary":"bounded","deleted_lines":2,"record_bytes":12288,"support":{"covers":["t1-5"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-5","last_task":2,"owner":1,"path":"tests/retained_review_test_support.py"},{"bounds":[{"added_lines":45,"boundary":"bounded","deleted_lines":2,"record_bytes":6144,"support":{"covers":["t1-6"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-6","last_task":1,"owner":1,"path":"tests/test_review_compact100.py"},{"bounds":[{"added_lines":35,"boundary":"bounded","deleted_lines":2,"record_bytes":6144,"support":{"covers":["t1-7"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-7","last_task":2,"owner":1,"path":"tests/test_review_replay.py"},{"bounds":[{"added_lines":1,"boundary":"bounded","deleted_lines":0,"record_bytes":2048,"support":{"covers":["t1-8"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-8","last_task":1,"owner":1,"path":"justfile"}]}}
```
