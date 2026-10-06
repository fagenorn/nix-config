# Task 2: The issue-121 expander

`expand_121` charges every row it builds to the expansion budget, and `_lineage` becomes an incremental pass whose copies are charged, serving derivation and expansion alike (spec § *Solution*, § *Linear derivations*; D1, D3, D4, D5, D6, D7, D8). Task 1 delivered `review_expansion` and the issue-100 side.

**Files:**
- Modify: `python/agent_tools/review_issue121.py`
- Modify: `tests/retained_review_test_support.py` (second of two contributions)
- Modify: `tests/test_review_compact121.py`
- Modify: `tests/test_review_replay.py` (second of two)

**Interfaces:**
- Consumes (Task 1): `review_expansion.Budget(refusal)` with `add(size)` and `charge(value) -> value`, reading `review_expansion.MEMBER_MAX_BYTES` when constructed; from `tests/retained_review_test_support.py`, `BOUND_PEAK`, `BOUND_SECONDS`, `WINDOW`, `LONG`, `measured(call, *, traced=False, seconds=BOUND_SECONDS) -> (error, elapsed, peak)`, `committed(name)`, `maximal(build) -> (payload, size)`; in `tests/test_review_replay.py`, the module-level `FORGED` rows `(member name, builder, error type)` that `test_maximal_forged_member_is_refused_within_the_bound` loops over. In `review_issue121` today: `_lineage(edges)`, `_actual(label, item, edges)`, `expand_121(payload)`, `_identified`, `_at`, `_rows`, `_closed`, `LABELS`, `_TASKS`, `ContributionError`.
- Produces (`review_issue121`): `_lineage(edges, budget=None) -> Callable[[str], list | None]` (private): the lookup of a path's edge ids in edge order, `None` for a path no record names.
- Produces (support): `edges_by_rows_121(n)`, `SITES_121`, `amplified_121(site)`.

**Invariants:**
- `expand_121` of the committed issue-121 payload has canonical bytes of length 211,097 and SHA-256 `8401a3a9297353aaadbd83e166ef8ae3475c0b3cfc73dfee471e6349d2549bce`, as at `DELIVERY_BASE`; `model_121` builds the same model for every fixture (the compact and issue-121 suites pass unchanged).
- `_lineage` keeps the old rule and output exactly: a record on `new` gives `new` the old path's ids, its own and this edge's; a rename also gives `old` this edge's; a path's list is every edge, in edge order, whose id is in its set, so edges whose ids coincide are all emitted (D4).
- Each `expand_121` call starts one fresh `Budget(lambda: ContributionError("invalid_payload"))` before it builds any row; `_actual` passes no budget (its model is charged when `compact_121` expands it).
- `expand_121` raises only `ContributionError("invalid_payload")` for any JSON value. No cap, refusal code or check order changes (D7).

- [ ] **Step 1: Write the failing tests.**

`tests/retained_review_test_support.py`: append

```python
def edges_by_rows_121(n: int) -> dict:
    """The committed issue-121 payload plus `n` edges that each modify one path, `forged`, and `n`
    `aggregate.actual` rows on it (#254's M1). Each value is as short as expansion reads it, so that a
    maximal member holds about 19,000 of each and its expansion at the base outlasts the bound (D8)."""
    payload = committed("issue-121.json")
    path = len(payload["paths"])
    payload["paths"].append("forged")
    for k in range(n):
        payload["classes"].append([f"{k:x}", 0])
        payload["edges"].append([["M", path, None, None, 0, "", ""]])
    payload["records"]["aggregate.actual"]["rows"] += [[path, 0, ""]] * n
    return payload


SITES_121 = ("class", "tree_entry", "edge_record", "anchor", "final_record", "outcome_edge_list", "lineage")


def amplified_121(site: str) -> dict:
    """The committed issue-121 payload with the rows of one charged site of `expand_121` amplified past
    the budget. Each is well formed: before issue 256 every one expanded without refusal (D8)."""
    payload = committed("issue-121.json")
    long = len(payload["paths"])
    payload["paths"].append(LONG)
    if site == "class":  # 60,000 more classes, beyond the last edge
        payload["classes"] += [["", 0]] * 60_000
    elif site == "tree_entry":  # 50,000 more entries, never referenced
        payload["entries"].append(["100644", "blob", [""] * 50_000])
    elif site == "edge_record":
        payload["edges"][0] += [["M", long, None, None, 0, "", ""]] * 10
    elif site == "anchor":
        payload["anchors"] += [[long, "", ""]] * 10
    elif site == "final_record":
        payload["records"]["aggregate.projected"]["rows"] += [[long, 0, 0, 0]] * 10
    elif site == "outcome_edge_list":  # one failure's evidence references, 30,000 more
        failed = next(row for row in payload["outcomes"] if "failure" in row)
        failed["failure"]["evidence_refs"] += [0] * 30_000
    elif site == "lineage":  # a chain of 1,500 renames, one per edge: the sets copied grow by one each
        start = len(payload["paths"])
        payload["paths"] += [f"forged/{k}" for k in range(1_501)]
        for k in range(1_500):
            payload["classes"].append([f"{k:x}", 0])
            payload["edges"].append([["R100", start + k + 1, None, None, 0, "", "", start + k]])
    return payload
```

`tests/test_review_compact121.py`: add `from unittest.mock import patch` if absent, extend the support import with `BOUND_PEAK, BOUND_SECONDS, SITES_121, WINDOW, amplified_121, committed, edges_by_rows_121, maximal, measured`, and append:

```python
class Bounded121Test(unittest.TestCase):
    """Issue 256: what `expand_121` builds from a forged payload is bounded (D3, D6, D8)."""

    def refused(self, payload, *, bound=True):
        for traced in ((False, True) if bound else (False,)):
            error, elapsed, peak = measured(lambda: expand_121(payload), traced=traced)
            self.assertIsInstance(error, ContributionError, f"{error!r} after {elapsed:.2f} s")
            self.assertEqual(error.code, "invalid_payload")
            if traced:
                self.assertLess(peak, BOUND_PEAK)
            else:
                self.assertLess(elapsed, BOUND_SECONDS)

    def test_maximal_edges_by_rows_is_refused_within_the_bound(self):
        self.assertEqual(expand_121(edges_by_rows_121(20))["schema_version"], 3)  # the forgery is well formed
        payload, size = maximal(edges_by_rows_121)
        self.assertTrue(WINDOW[0] <= size <= WINDOW[1], size)
        self.refused(payload)

    def test_each_amplified_site_is_refused(self):
        for site in SITES_121:
            with self.subTest(site=site):
                self.refused(amplified_121(site), bound=False)

    def test_the_budget_reads_the_public_bound(self):
        payload = committed("issue-121.json")
        self.assertEqual(expand_121(payload)["schema_version"], 3)
        with patch("agent_tools.review_expansion.MEMBER_MAX_BYTES", 100_000):  # below the real model's charge
            with self.assertRaises(ContributionError) as caught:
                expand_121(payload)
        self.assertEqual(caught.exception.code, "invalid_payload")
```

Also append to `tests/test_review_compact121.py` one below-budget equivalence case (Codex S1, per D9), `test_lineage_keeps_the_pre_256_rule`: a test-local reference copy of the `DELIVERY_BASE` `_lineage` rule (sets unioned per record, then every edge in edge order whose id is in a path's set), applied to small forged payloads built from the committed issue-121 payload with (a) a rename chain `a → b → c` plus a later modification of `a`'s new occupant and (b) two edges whose ids coincide on one path. Each must expand without refusal through `expand_121`, and the `aggregate.actual` `edge_ids` the public path yields (expansion, or `model_121` over a fixture that derives those records) must equal the reference rule's ordered lists exactly, duplicates included. Use only public names (D5); if no public seam reaches lineage for a forged payload, assert it through the derivation suite's existing `test_rehashed_final_record_lineage_is_recomputed` pattern in `tests/test_review_issue121.py` instead and name that in the task report.

`tests/test_review_replay.py`: add `edges_by_rows_121` to the support import, and make `FORGED`

```python
FORGED = (("issue-100-derived.json", rename_chain_100, Issue100Error),  # maximal forged members (issue 256)
          ("issue-121.json", edges_by_rows_121, ContributionError))
```

- [ ] **Step 2: Run them and watch them fail.**

```bash
PYTHONPATH=python timeout 600 python3 -m unittest tests.test_review_compact121.Bounded121Test 2>&1 | tail -3
```

Expected at the starting commit: `FAIL` in all three cases: `Overtime() after 5.00 s` for the maximal shape, `None` instead of a refusal for each site and for the patched bound.

- [ ] **Step 3: Implement.**

1. `_lineage(edges, budget=None)`. Keep a set of edge ids per path and, once, the positions of each id in `edges`. Walk the records in edge order. With `width = len(canonical_bytes(edge["id"]))`, charge `budget.add(width)` for every id added to a set or copied into one, when `budget` is given:
   - `old == new`: add this edge's id to `new`'s set in place;
   - a rename: `new`'s set becomes a new set, the union of `old`'s set, `new`'s set and this edge's id (every element copied is charged); then add this edge's id to `old`'s set in place.
   Return `lookup(path)`: `None` for a path without a set; otherwise the ids of every edge position held by an id in its set, sorted by position, built on first request and memoised. The docstring states the rule, that lists are built on demand and in edge order, and that only the set work is charged here (D4).
2. `_actual`: `lineage = _lineage(edges)` and `refs = lineage(record.path)`; nothing else changes.
3. `expand_121` (D3): construct `budget = Budget(lambda: ContributionError("invalid_payload"))` before building any row, then charge, as each is built and before it joins the model: each tree entry; each class; each edge record; each edge, once identified, with `records` left out (`{**edge, "records": []}`); each anchor, once identified; each final record, once identified, with `edge_ids` left out, plus one id width per `edge_ids` element; and each element of an outcome's `edge_ids` and of a failure's `evidence_refs` (an id built from an index is an outcome edge list, D8). Build each slot's lineage as `_lineage(selected[label], budget)` for an `actual` slot only, the one reader of it. The range, operational effects, policies and the stored outcome members are not charged; the post-expansion validators are unchanged (D7).
4. Add to `expand_121`'s docstring: "Every row it builds is charged, as it is built, to a budget of `review_expansion.MEMBER_MAX_BYTES` canonical bytes read when the call starts, and the first charge past it is `invalid_payload`, so the work a payload causes is bounded by its size and that budget." If the code charges a site differently from step 3, rewrite that sentence from the code and name the difference in the task report.

- [ ] **Step 4: Verify.**

```bash
set -euo pipefail
PYTHONPATH=python timeout 2400 python3 -m unittest tests.test_review_expansion tests.test_review_compact121 \
  tests.test_review_issue121 tests.test_review_compact100 tests.test_review_witness tests.test_review_derivation \
  tests.test_review_replay tests.test_review_evidence 2>&1 | tail -3
PYTHONPATH=python python3 -c '
import hashlib, json
from agent_tools.review_forecast import canonical_bytes
from agent_tools.review_issue121 import expand_121
model = canonical_bytes(expand_121(json.load(open("tests/fixtures/retained-review-evidence/issue-121.json"))))
assert (len(model), hashlib.sha256(model).hexdigest()) == (211097, "8401a3a9297353aaadbd83e166ef8ae3475c0b3cfc73dfee471e6349d2549bce")'
if grep -q 'for edge in edges if edge\["id"\] in ids' python/agent_tools/review_issue121.py; then exit 1; fi
if ! grep -q 'review_expansion' python/agent_tools/review_issue121.py; then exit 1; fi
git diff --stat 31be7292b40159c5a3f49cc24f21b3292ba4ce89 -- python/agent_tools | tail -1
timeout 7200 just agent-workflow-tests 2>&1 | tail -3
timeout 3600 just build 2>&1 | tail -3
```

The eight suites end `OK`; at the starting commit `Bounded121Test` fails. The `--stat` line names exactly four files.

- [ ] **Step 5: Commit.** Stage only the four Files. Check that `printf %s "$subject" | wc -c` is at most 64, then commit through `launch-commit` with `feat(review): bound issue-121 expansion by a budget (#256)`. A review-fix commit uses `fix(review): address Task-2 review findings (#256)`.

- [ ] **Step 6: G1 (controller).** Run the plan root's G1 at the new `HEAD`, record this task's `actual_ranges` and refresh `actual_evidence` in a process-only commit, then renew G0 at `--completed-through 2`.

## Forecast basis

Estimates. A modify record is the U7 diff against `DELIVERY_BASE`; a second contribution's bound is cumulative over both tasks.
- `review_issue121.py`: `_lineage` rewritten, `_actual` two lines, about twenty-five charged lines and the docstring in `expand_121`: 26,624 B / +120 / −70.
- `tests/retained_review_test_support.py`, both contributions: Task 1's 170 lines and the block above (about 2,900 B, 55 lines): 20,480 B / +230 / −2.
- `tests/test_review_compact121.py`: 6,144 B / +45 / −2. `tests/test_review_replay.py`, both contributions: 8,192 B / +40 / −3.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":2,"records":[{"bounds":[{"added_lines":120,"boundary":"bounded","deleted_lines":70,"record_bytes":26624,"support":{"covers":["t2-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t2-1","last_task":2,"owner":2,"path":"python/agent_tools/review_issue121.py"},{"bounds":[{"added_lines":230,"boundary":"bounded","deleted_lines":2,"record_bytes":20480,"support":{"covers":["t1-5","t2-2"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t2-2","last_task":2,"owner":2,"path":"tests/retained_review_test_support.py"},{"bounds":[{"added_lines":45,"boundary":"bounded","deleted_lines":2,"record_bytes":6144,"support":{"covers":["t2-3"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t2-3","last_task":2,"owner":2,"path":"tests/test_review_compact121.py"},{"bounds":[{"added_lines":40,"boundary":"bounded","deleted_lines":3,"record_bytes":8192,"support":{"covers":["t1-7","t2-4"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t2-4","last_task":2,"owner":2,"path":"tests/test_review_replay.py"}]}}
```
