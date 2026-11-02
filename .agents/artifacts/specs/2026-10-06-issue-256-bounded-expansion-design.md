# Issue 256 — bound compact-payload expansion on forged members

## Problem

Since [#254](https://github.com/fagenorn/nix-config/issues/254) (PR 257) a
retained bundle stores the issue-100 payload at schema 2 and the issue-121
payload at schema 4, and `expand_100` / `expand_121` rebuild SOURCE's model from
them. `validate_bundle` expands both members before the components, Task-7 and
SOURCE pin checks, and `validate_*` and `compact_*` expand again. Before #254 the
member *was* the model, so the 1,048,576 B decode bound (`MEMBER_MAX_BYTES`)
also bounded every model validation built. Now a forged member inside that
bound can make expansion do super-linear work: #254's G2 adversarial review
measured a 975,603 B issue-100 member with no answer after 240 s at 1.16 GB,
and `replay-retained` under the forger's digest with no answer after 120 s.
Nothing is ever accepted, and only a caller who trusts the forger's anchor
digest reaches it (RP7 trust injection), which is why #254 parked it.

A reader replaying a hostile bundle must instead get the existing closed
refusal, `invalid_payload`, within a small stated time and memory bound.

## Measured causes

Reproduced on the base (`31be729`) with bounded probes (60 s timeout,
`tracemalloc`) over the committed retained payloads, each forged by appending
rows. "Model" is the canonical bytes of the expansion.

| Expander | Shape | Payload | Result on the base |
|---|---|---|---|
| 100 | rename chain of *n* records on one edge, a fresh row on every chain path | 116,247 B (*n* = 400) | 76 s; doubling *n* costs ~5x |
| 100 | one record referenced *n* more times by an edge | 70,118 B (*n* = 4,000) | 1.7 s, model 1.94 MB (~200x per 2-byte reference) |
| 100 | one 200 kB path referenced by 200 more edge references | 262,518 B | model 82.8 MB |
| 121 | *n* more edges each recording one path, *n* actual rows on it | 98,917 B (*n* = 1,000) | 2.2 s, model 76 MB; doubling *n* costs 4x |
| 121 | rename chain, one edge reference repeated | ≤ 1.4 MB | linear, 2–3x amplification |

Re-checked on the base at spec close: the real models are 341,492 B and
211,097 B with the digests below, and the issue-121 edges × actual rows shape
with full-width commit rows (n = 2,000, a 658,917 B member) expands to a
298,893,097 B model, 4x the n = 1,000 model.

Three mechanisms, confirming the issue's suspects:

1. **`_refs` (issue 100) is cubic in time.** For each fresh row it iterates a
   fixed point over every edge record until the rename-connected name set stops
   growing: rows × passes × records, with a small output. This is #254's I1.
2. **Output is quadratic.** An actual issue-121 record carries its path's
   lineage, at most one id per selected edge, so rows × edges ids (#254's source
   M1). `_lineage` also copies a growing set per record and then scans every
   edge per path. An issue-100 contribution likewise carries its component's
   reference pairs.
3. **Interned references amplify.** A two-byte index re-materialises a whole
   record, a path string or a 40-hex entry; a long path referenced many times
   makes every digest of the model (`_identified`, the witness tables, the
   canonical-form round trip) serialise it again. Each step is linear in
   references but multiplies the canonical bytes everything downstream hashes.

`_at_head`'s per-commit dict copy and the per-parent `nodes[:i + 1]` slice are
quadratic in commits too. The slice goes (D4). `_at_head` stays: each step
needs a charged parent edge and each entry a charged record (D3), so under the
budget it copies at most about 1.4 × 10⁷ entries (4,000 steps × 3,500 records),
well under a second.

## Solution

Two changes in both expanders, nothing else in the bundle contract (D1):

**An expansion budget.** Every row an expander materialises — a parent edge, a
tree entry, a dereferenced edge record, a historical or fresh row, a
contribution, an overlap, a class, an anchor, a final record, an outcome's edge
list, and each lineage set element it holds — is charged its canonical bytes as
it is built, before it joins the model. The first charge that takes the total
above `MEMBER_MAX_BYTES` raises the module's `invalid_payload` (D2, D3). Every
loop is then linear in the payload or in the charged bytes, so time and memory
are O(member + budget). The committed real payloads charge about 340 kB
(issue 100, model 341,492 B) and 195 kB (issue 121, model 211,097 B), measured
on a prototype.

**Linear derivations.** `_refs` becomes one rename-component grouping per
edge list and `_lineage` an incremental pass whose work is charged, both with
unchanged output, serving `model_*` and `expand_*` alike (D4).

The prototype was checked end to end: the real committed payloads expand to the
same canonical bytes as on the base (issue 100
`5d10b020…1022df`, issue 121 `8401a3a9…549bce`, the digests #254's G2 recorded),
and the focused suites pass unchanged. Every forged shape above, grown to the
decode bound, is refused `invalid_payload`:

| Maximal forged member (≈1,000,000 B) | Time | Peak traced |
|---|---|---|
| 100 rename chain + fresh rows (I1) | 0.48 s | 8.1 MB |
| 100 repeated record reference | 0.26 s | 1.7 MB |
| 100 long path, repeated | 0.07 s | 1.0 MB |
| 100 extra commits | 0.86 s | 10.1 MB |
| 121 edges × actual rows (M1) | 0.49 s | 4.5 MB |
| 121 rename chain / repeated edge record | ≤ 0.22 s | ≤ 1.4 MB |

## Decisions

### The budget

- **Size.** The budget is `MEMBER_MAX_BYTES`, the decode bound that limited
  these very models when they were the members. It is not a new number and no
  cap moves. A model the base's decode bound would have refused is refused
  again, now as `invalid_payload` (D2).
- **Home.** `MEMBER_MAX_BYTES` and the budget move into one new small package
  module, `review_expansion`. `review_issue100` and `review_issue121` charge
  through it, and `review_witness` imports the constant from it, so the public
  name `review_witness.MEMBER_MAX_BYTES` and its value stay the same. The
  constant cannot stay in `review_witness`, because the expanders would then
  import their own importer (D2).
- **What is charged** (D3). The canonical bytes of each materialised row,
  including an id when the row is identified. An embedded list is charged per
  element as it is built, never after a whole list is built. Lineage elements
  are charged at the width of one edge id each time one is added to a set or
  copied into one.
  Members copied verbatim from the payload (range, outcomes, policies,
  operational effects) are not charged: they are bounded by the member itself.
  Each issue-100 criterion row is charged whole, its text included (D11).
- **Reading the bound.** A budget reads `review_expansion.MEMBER_MAX_BYTES` when
  its `expand_*` call starts, never a copy bound at import, so patching that
  public name moves the budget alone. `review_witness` and `review_derivation`
  keep their own imported names for the decode bound, as today (D5).
- **Scope of a budget.** Each `expand_*` call starts a fresh budget. The three
  expansions a bundle validation makes are each bounded, so the total is too.
- **Refusal.** The budget raises each module's existing `invalid_payload`
  (`Issue100Error`, `ContributionError`). A value `canonical_bytes` cannot
  encode at a charge is `invalid_payload` too, never a raw `TypeError`.
- **Derivation.** `compact_*` runs `expand_*`, so derivation charges as well. A
  future real model whose charge exceeded the bound would be refused at
  derivation. That is consistent: the base could not have replayed such a model
  either.

### Linear derivations (D4)

- **`_refs`.** A union–find over each record's `path` and `old_path` gives the
  rename-connected components. One pass in edge and record order appends each
  `[edge, record]` pair to its component, and a row takes a fresh copy of its
  component's list. This is exactly the old fixed point's result (it computes
  the connected component). Cost is O(records) plus the charged output.
- **`_lineage`.** Same rule as today: a record on `new` gives `new` the old
  path's lineage, its own and this edge; a rename also gives `old` this edge.
  A same-path record adds to its set in place. A rename copies, and each element
  copied is charged. A path's list is produced on demand, in edge order, and
  memoised for the slot. Edges whose ids coincide are all emitted, as the old
  `edge["id"] in ids` filter emits them. `_actual` (derivation) and
  `expand_121` share it. `_actual` passes no budget: its model is charged when
  `compact_121` expands it.
- **Parent edges.** The earlier-parent rule (CP16) checks `0 <= p <= i`
  directly instead of indexing a fresh slice.

### Unchanged

The schemas (issue 100 v2, issue 121 v4), every cap and decode bound, every
refusal code and its order in `validate_bundle`, both command shells, the
witness and anchor, `_at_head` and the post-expansion validators all stay as
they are. Each validator now runs over a model no larger than the base allowed.
Their remaining super-linear scans are bounded by pins, not by the payload (D7).
The committed evidence bundle and its trusted digest stay valid: replay checks
no running tool closure. `expand_100`'s docstring loses "nothing bounds the
memory…" and states the budget, and `expand_121`'s gains the same sentence.

## Test seams

The existing seams only (as #254's § *Test seams*): modules imported under the
recipe's `PYTHONPATH`, the portable compact suites, `replay()` over a portable
bundle with the replay suite's `rebound` trust injection, the committed-evidence suite
and the retained tier. Forged payloads are built by appending rows to the
committed retained payloads (in-repo files, so the portable suites need no Git
fixture to build one). The forging builders live in
`retained_review_test_support`, which the compact and replay suites already
import; the replay case uses the replay suite's own `rebound` method to re-anchor
the forged bundle. No test reads a private name (D5).

| Issue criterion | Evidence |
|---|---|
| 1. Maximal forged member refused within a stated bound, failing on the #257 tree | Per expander, a maximal shape from § *Measured causes* (issue 100: the I1 rename chain with fresh rows; issue 121: edges × actual rows), with canonical bytes in [1,000,000, `MEMBER_MAX_BYTES`]. `expand_*` raises `invalid_payload` within **5 s** wall time, enforced by an interval timer so the base fails at the bound instead of hanging, with a **32 MiB** `tracemalloc` peak. Time is taken on an untraced call and the peak on a separate traced call, each under the timer (D7). The same shapes through `replay()` under the forger's digest meet the same bound, decoding included (D6); the prototype measured ≤1 s and ≤12 MiB for decode plus expansion |
| 2. Linear or explicitly bounded, both expanders | The budget (D3) plus a charge-site matrix: one amplification per charged site, each refused `invalid_payload`; patching the public `review_expansion.MEMBER_MAX_BYTES` below a real fixture's model refuses it, and the shipped value accepts it |
| 3. Real payloads byte-identical; second derivation identical | `test_review_evidence` over the committed bundle; the tier's existing `expand_*` = `model_*` and determinism checks; the derived payloads equal the committed ones |
| 4. No cap raised, no code added | Existing constant and code-set assertions stay green, and the constant's value is asserted where it is today |
| 5. Suites, tier, build | § *Delivery gates* |

## Delivery gates

- The plan carries its own forecast and clears `review-feasibility project` at
  `--completed-through 0` before any product commit, renewed per accepted task,
  following #254's CP12 precedent. The two expander modules (43,017 B and
  38,660 B) and their suites are priced with care, and the new module is small.
- At the final head: `just agent-workflow-tests`, `just build`,
  `just agent-installed-skill-tests`, and
  `just agent-retained-tests /Users/anis/tmp/nix-config` with
  `AGENT_RETAINED_TOOL_COMMIT` left at the default (the final head). No skip
  counts as a pass.
- Code review repeats #254's I1 probe (a ≈975 kB issue-100 member) and the M1
  probe against the final head and records the time and peak.

## Out of scope

Schema, cap, decode-bound or refusal-code changes; record splitting; the
witness, anchor, CORE loader and Task-7 table; reordering `validate_bundle`;
pin checks inside the expanders; rewriting `_at_head` or the post-expansion
validators; #254's interpreter-limit findings (`RecursionError` near the JSON
depth limit, oversized integers); the committed evidence bundle and its
`TOOL_COMMIT`; any CLAUDE.md edit (no sentence there describes expansion).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Bound expansion inside both expanders with a charged budget plus linear `_refs`/`_lineage`; pin-free, no schema change | Issue 256 criteria 1–2 (bound the *expanders*); CP4 (expansion is pure and pin-free); measured: output itself is quadratic (rows × lineage) and interned references amplify, so an algorithmic fix alone cannot bound it, and the cubic `_refs` is slow at a small output, so a budget alone cannot | Pin and shape pre-checks before expansion (`validate_bundle` reorder): leaves `expand_*` unbounded for every other caller, changes refusal order, and no pin bounds path lengths. Algorithmic fixes only: output stays quadratic |
| D2 | The budget is `MEMBER_MAX_BYTES` of charged canonical bytes. The constant moves, unchanged in name and value, into a new module `review_expansion` with the budget; `review_witness` imports it | Before #254 the model was the member under this decode bound (RP13, CP10), so it restores exactly the base's envelope; the-bar DRY (one home); an import cycle forbids the expanders importing `review_witness`; real charges ≈340 kB and ≈195 kB | A new constant or a multiple of the member size: an invented number that must change with the decode bound. A second equal constant: two homes for one bound. The helper inside one expander module: the other model module would import its sibling. `review_forecast`, already imported by all three: the-bar's one reason to change, and it is the forecast-package module |
| D3 | Every materialised row is charged as it is built, an embedded list per element, a lineage set per element held; the first excess is `invalid_payload`. Verbatim-copied members are not charged | The-bar (fail loud; tests that can fail): one uniform rule a reviewer checks site by site; charging before building bounds memory as well as time | An exact pre-pass of the model's size: a second description of the model's shape that drifts. Charging only the super-linear sites: each unlisted site needs its own linearity argument, and long-path amplification reaches every row with a path |
| D4 | `_refs` becomes a union–find grouping and `_lineage` an incremental pass with charged rename copies and on-demand, memoised, edge-ordered lists (duplicate ids preserved). Both replace the old functions for derivation and expansion alike. The earlier-parent check drops the slice. `_at_head` is unchanged | The-bar DRY (one rule for `model_*` and `expand_*`); the prototype matches the base byte for byte on the real payloads and passes the focused suites; `_at_head` is bounded by charged rows | Keeping the old functions for derivation: two copies of one rule. A bitset lineage: memory grows as names × edges. Rewriting `_at_head`: YAGNI under the budget |
| D5 | Seams: `expand_*` in the portable compact suites, `replay()` under trust injection via the replay suite's existing `rebound` method, the committed-evidence suite and the tier. Forgeries are built by appending rows; builders live in test support; the budget boundary is tested by patching the public constant, which the budget reads per call | #254 § *Test seams* (no new seam, no private name); the-bar (tests that can fail): the charge-site matrix turns red when any one charge is removed | A subprocess-only command test: no portable memory measure. Pinning model digests in tests: CP11 (fitted) |
| D6 | Stated bound: a maximal forged member (≥1,000,000 B, ≤ `MEMBER_MAX_BYTES`) is refused within 5 s wall time and a 32 MiB `tracemalloc` peak around the call. Time is enforced by `signal.setitimer` so the #257 tree fails at 5 s; memory by `tracemalloc` | Issue 256 criterion 1 ("stated bound … fails on the tree #254 delivers"); prototype ≤0.9 s and ≤12 MB, a 5x and 2.6x margin for slower CI; both shapes fail on the base by time, without exhausting memory | Asserting elapsed time after the call: hangs on the base. Child-process RSS: units and accounting differ between Linux and macOS. Tighter bounds: flaky on a loaded runner |
| D7 | Grill refinements: (a) the post-expansion validators stay unchanged because each super-linear scan runs only after pins fix its row count (issue 100 checks the pinned fresh-record count before the rows × head-entries directory scan; issue 121 iterates five fixed labels), so under the budget their cost is linear in the model times pinned counts. (b) Time is asserted on an untraced call and memory on a separate traced call, both under the 5 s timer | Code read at grill: `_validate_tables` precedes `_validate_contributions`; `validate_121` loops over `LABELS`. `tracemalloc` slows allocation-heavy code, so one traced call would test the tracer's overhead against the time bound | Budgeting the validators too: they are post-pin, out of the issue's scope. One combined traced call: a time bound coupled to tracer overhead, flaky on a loaded runner |
| D8 | Plan refinements of D3, D5 and D6: (a) the issue-121 maximal forgery uses the shortest values expansion reads (about 19,300 edges and rows); (b) the charge-site matrix holds one amplification per charged site, each of which expands without refusal on the base, and it pins the bound, not each charge's presence: where a site's rows feed a later charge (a fresh row its contribution, an edge its outcome lists), removing that one charge can leave the matrix green, which narrows D5's "turns red when any one charge is removed"; (c) a failure's `evidence_refs`, ids built from indices, are charged as an outcome edge list, and lineage is built for `actual` slots only, its one reader | Planning probes on the base `31be729`: the full-width M1 shape at ≈1 MB (n ≈ 3,200) expands in 3.5 s, inside the 5 s bound, while the short-value M1 and the I1 chain overrun it, also through `replay()`; every matrix case expanded without refusal there; D3 (an evidence reference turns 2 B into 73 B) | A full-width forgery: passes on the base, so it cannot meet criterion 1's "fails on the #254 tree". A matrix that turns red per removed charge: needs instrumentation or a private name, against D5 |
| D9 | Phase-5 review: Task 2 adds a below-budget lineage-equivalence test (renames, coincident edge ids) against a test-local copy of the base rule; G3 runs under `pipefail` | Codex plan review S1 (round trips share the rewritten helper, so cannot establish equivalence alone) and S2 (`| tail` masks failures) | Rely on the committed-payload SHA pin alone — it exercises no rename chain or coincident id |
| D10 | Task-2 execution: (a) the `tests/test_review_compact121.py` forecast is raised to 8,192 B / +80 / −2, because D9's test made the actual record +64 lines; (b) where Task 2's review flagged code the plan dictates word for word (the bounded-refusal check copied across three suites, and the `amplified_*` site chains with no `else: raise`), the plan text stands and the final review triages both findings; (c) Step 4's `agent-workflow-tests` and `just build` run once, in the final verification at the branch tip | The plan's size-bound rule ("a committed forecast revision and a renewed G0, never truncation"); the brief's verbatim test text, already reviewed in Phase 5; sdd's final verification is the plan's single run of the declared verification, and all eight focused suites passed on the Task-2 diff | Truncating D9's test. A fix round that rewrites plan-dictated test text with no human ruling. Running the hour-long suite twice when the attempt deadline is tight |
| D11 | Final review (fix 0235fd9): (a) each issue-100 criterion row is charged whole, its text included, so § What is charged no longer lists criteria text as uncharged; (b) the D10(b) triage defers both findings, the copied bounded-refusal check and the `amplified_*` chains without `else: raise`, as parked with the ruling that the plan text governs, recorded in the SDD delivery detail | The final review found that a payload of empty criteria under the decode bound expanded to a model several times the budget; D10(b) left both findings to the final review | Leaving criteria text uncharged, which lets that model through. Rewriting plan-dictated test text with no human ruling |
