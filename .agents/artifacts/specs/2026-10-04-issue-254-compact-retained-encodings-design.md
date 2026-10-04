# Issue 254 — compact retained payload encodings (DP234-COMPACT)

## Problem

[EVIDENCE 235](https://github.com/fagenorn/nix-config/issues/235) must commit
the five-file retained bundle, each file as one whole review record under
CORE's unchanged caps: 65,536 B per member, eight members, 524,288 B in all.
Derived from the real retained objects with the modules published at `7e17c81`,
`issue-121.json` is 211,097 B and `issue-100-derived.json` is 341,492 B, and
with `task7-estimate.json` (43,757 B) the three total 596,346 B. EVIDENCE
cannot commit that bundle, and parent
[234](https://github.com/fagenorn/nix-config/issues/234) forbids every shortcut:
no moved cap, no split file, no omission, truncation, handwritten record split
or expanded generated exemption (parent D3).

This child, `DP234-COMPACT`, is DERIVE's third after SOURCE
([248](https://github.com/fagenorn/nix-config/issues/248)) and REPLAY
([249](https://github.com/fagenorn/nix-config/issues/249)). It gives the two
payloads compact encodings that keep every fact, and repeats G0 and G2.

Immutable `DELIVERY_BASE`: `7e17c8196569b0a96950f07ff886884690ffa224`,
integration with published CORE, SOURCE and REPLAY. Parents 234 and 226 stay
open.

## Binding designs

The [SOURCE spec](2026-10-03-issue-248-retained-source-models-design.md) (rows
S6, S9, S10, S16, S22–S24), the
[REPLAY spec](2026-10-04-issue-249-retained-derivation-replay-design.md) (rows
RP2, RP5, RP7, RP8, RP13, RP14, RP16, RP17, RP19, RP22 and its § *Delivery
gates*) and the
[DERIVE design at `6e5224e`](https://github.com/fagenorn/nix-config/blob/6e5224edcdd6477fbde42439f01c2ffaf211ac91/.agents/artifacts/specs/2026-10-03-issue-234-retained-review-derivation-design.md)
(parent D3, D18) bind this child. This spec records only what it adds or
changes. Rows prefixed `CP` are this issue's decisions.

Two terms are used throughout. The **model** is the object SOURCE's encoding
yields: issue 100 at `schema_version` 1, issue 121 at `schema_version` 3. From
this child on it exists only in memory. The **payload** is the compact object
whose canonical bytes are the bundle file. REPLAY's *fixtures* (the three
derived files) and *payloads* (the four files the anchor hashes) keep their
meaning; SOURCE's specs call the model "the payload".

## Measured feasibility

Measured on 2026-10-04 before any product work, with a prototype compactor and
expander per payload. The inputs are the models derived read-only from the real
retained objects by the base modules (211,097 B and 341,492 B, reproduced twice
with equal SHA-256). Bytes are `review_forecast.canonical_bytes`.

| File | Encoding | Bytes | Below 65,536 B |
|---|---|---|---|
| `issue-100-derived.json` | Payload v2: interned tables, base85 digests (CP2) | 62,118 | 3,418 |
| `issue-121.json` | Payload v4: interned tables, hex digests kept (CP3) | 48,917 | 16,619 |
| `task7-estimate.json` | Unchanged (parent D18) | 43,757 | 21,779 |
| `derivation-witness.json` | Unchanged shape, tool closure at the base (57 files) | 15,891 | 49,645 |
| `derivation-anchor.json` | Unchanged shape, same closure | 13,769 | 51,767 |

**Result: feasible for both payloads.** For each one, on the real objects:

- the expansion of the payload's canonical bytes equals the model byte for
  byte (same canonical bytes, so the same SHA-256 as the base derivation);
- compacting that expansion reproduces the payload byte for byte.

Both properties also hold on the portable fixtures: the issue-100 fixture (a
merge, a rename, a file that became a directory, both swap directions) and four
issue-121 shapes (all measured, two unavailable routes, the swap fixture).

**Five-file total: 184,452 B**, 339,836 B below the aggregate. Committed in a
scratch repository under a 75-character directory and measured by CORE's
`actual_inputs_from_trees` and `select_candidate`, the five are five whole
records with no generated-evidence summary: 62,587 B, 49,362 B, 44,217 B,
16,363 B and 14,238 B. The package is `within_budget` at 187,328 B in four
of eight payload members, largest 62,587 B. A diff header adds about 470 B to
a file, so the issue-100 record sits 2,949 B below the cap.

**Headroom for EVIDENCE.** EVIDENCE's process and test records get about
337 kB and four empty members, plus the slack in the four used ones. REPLAY's
stress projection, a six-task child, priced its whole process package at about
153 kB, and EVIDENCE is smaller. The full-shape tier asserts each file at most
65,536 B and the five together at most 196,608 B (three members' worth, CP10),
which leaves EVIDENCE about 327 kB even at that bound. Its need is at most
about 160 kB by the reference above.

The retained objects are pinned, so these sizes are constants of the encoding:
headroom is spent only by a later encoding change. Three measured reserves stay
unused (CP5).

Hex digests cannot fit issue 100: the same structure with hex measures
85,017 B, and its 1,147 distinct digests alone are 62,128 B. Base64 measures
64,673 B, which a diff header pushes over the cap.

## Solution

Each model module keeps SOURCE's derivation as the model builder and gains a
compactor and an expander. No new module, command, option or bundle file is
added, and no cap or bound constant changes.

| Function | Contract |
|---|---|
| `model_100(issue_repo, live_repo, archive_dir, pins, limits)`, `model_121(repo, pins, task7_pins, authority)` | The model, read from Git exactly as SOURCE's `derive_*` reads it. |
| `compact_100(model)`, `compact_121(model)` | The payload. Pure. A model the payload cannot represent is `invalid_payload`. |
| `expand_100(payload)`, `expand_121(payload)` | The model. Pure, Git-free and pin-free: it reads the payload alone. Anything but a closed, well-typed payload is `invalid_payload`. |
| `validate_100(payload, pins)`, `validate_121(payload, pins, table)` | Expand, check the expansion against the pins, require the canonical form, return the model. |
| `derive_100(...)`, `derive_121(...)` | Same arguments as today; return the payload. |

Codes are the modules' existing ones: `Issue100Error` and `ContributionError`
with `invalid_payload`, `invalid_pins` and `assignment_mismatch` as today.

**Derivation** builds the model, compacts it, validates the payload and then
requires the returned expansion to equal the model it read from Git, else
`invalid_payload`. Every derivation therefore proves, on its own inputs, that
the bytes it publishes expand to SOURCE's encoding (CP1).

**Validation** has three steps, all Git-free:

1. *Expand.* Closed keys, value types, index ranges and digest tokens are
   checked before use. A raw `KeyError`, `IndexError` or `TypeError` escaping
   is a defect (S3's rule).
2. *Check the expansion against the pins*, with SOURCE's checks: range, pinned
   raw-parent digest, edge and record shapes, both domains, labels, overlaps,
   criteria, counts; assignments, anchors, outcomes, prerequisites, failure
   references, the tasks-7-8 rows against the table.
3. *Canonical form.* `compact(model)` must equal the payload canonically
   (CP6). One fact set has exactly one payload.

A SOURCE check that expansion makes true by construction (a row id against its
row, a reference list against its recomputation, the summary against the
tables) is removed from step 2, because no payload can reach it and the-bar
keeps no guard that no test can turn red. The rule itself now lives once, in
the expander. On an expansion, step 2 refuses exactly what SOURCE's validator
refuses on the same model. On the derivation side the removed checks are
replaced by the equality above: the model read from Git must be the expansion,
and the expansion satisfies them by construction.

### Issue-100 payload, `schema_version` 2

A *packed* string is RFC 1924 base85 (`base64.b85encode`, the alphabet Git's
binary patches use) of concatenated raw digests. Twenty and thirty-two bytes
are multiples of four, so every object id is exactly 25 characters and every
SHA-256 exactly 40, and item `i` is one fixed-width token. No alphabet
character needs JSON escaping. An *entry reference* is `null` or an index into
the entries in table order.

| Member | Content |
|---|---|
| `schema_version`, `kind` | `2`, the unchanged kind |
| `range` | `{base, head, live}`, hex |
| `commits` | Packed ids of the 82 range commits, in range order |
| `parents` | Per commit, its raw parents in ordinal order, each an index into `[base, *commits]` |
| `paths` | Every path the payload names, sorted, unique |
| `entries` | `[mode, kind, packed ids]` per distinct `(mode, kind)`, sorted; ids ascending and unique |
| `records` | The 419 distinct edge records in first-use order: `[operation, path, before, after, record_bytes]`, plus the old path for a rename |
| `record_sha256` | Packed, one digest per `records` row |
| `edges` | Per raw parent edge, in `parents` order, its record indices in order (543 in all) |
| `tables` | `historical: {record_table_policy, bytes, sha256}` and `fresh: {record_table_policy, paths, bytes, sha256}`; `bytes` and `paths` are lists, `sha256` packed |
| `live` | Per fresh record, the live entry reference |
| `head_trees` | `[fresh index, entry reference]` for each path that is a directory at the head (none in the real payload) |
| `process` | Fresh indices of the historical-process paths |
| `pending_overlaps` | `[path, base entry reference]` per overlap |
| `overlap_sha256` | Packed, three per overlap in `_PAIRS` order |
| `criteria` | SOURCE's rows without `text_sha256` |

Recomputed by the expander, each from stored members only:

| Model member | Recomputed from |
|---|---|
| `range.commits`, `parent_edges`, each edge's `parent`, `commit`, `parent_ordinal` | `commits`, `parents` |
| Each edge's records, repeated across a merge's edges | `edges`, `records`, `record_sha256`, `entries`, `paths` |
| Contribution `path`, `record_sha256` | The fresh row at the same index |
| Contribution `head_entry` | The first-parent walk SOURCE's `_at_head` does; a `head_trees` row where the path is a directory |
| `disposition` | `process`, else head entry equal to live entry |
| `pending`, overlap `live_entry` and `head_entry` | The overlap paths and the contribution on that path |
| `edge_refs`, every `id`, `summary` | SOURCE's `_refs`, `telemetry_digest`, `_counts` |
| Criterion `text_sha256` | SHA-256 of its `text` |

### Issue-121 payload, `schema_version` 4

Digests and object ids stay hex strings, written as the model writes them.

| Member | Content |
|---|---|
| `schema_version`, `kind`, `range` | `4`, the unchanged kind, `{base, head}` |
| `classes` | The 30 assignments in range order: `[commit, owner]`, plus the reason for a process row |
| `paths`, `entries` | As issue 100, with each group's ids as a hex list |
| `edges` | Per assignment, its records: `[operation, path, before, after, record_bytes, record_sha256, hunk_header_sha256]`, plus the old path for a rename |
| `signer_sha256` | The one signer digest every anchor carries |
| `anchors` | `[path, commit, blob]` per plan path |
| `records` | Per outcome label that has final records: `{kind, rows}`; an `actual` row is `[path, record_bytes, record_sha256]`, an `estimate` row `[path, record_bytes, added_lines, deleted_lines]` |
| `outcomes` | The five outcome rows in label order, each with its `state`, `prerequisite` and `estimate_refs` as the model has them, then `result_tree` and `measurement`, or `failure` whose `evidence_refs` are edge indices |
| `operational_effects`, `record_table_policy` | As the model has them |

Recomputed by the expander: each edge's `parent`, `commit`, `parent_ordinal`
and `owner` (the chain from the base through `classes`); all 430 row ids; each
anchor's `signer_sha256`; each record's `kind` and `scope`; an actual record's
`edge_ids` (SOURCE's `_lineage` over its outcome's edges); each outcome's
`boundary`, `edge_ids` and `record_refs`; a failure's `evidence_refs` ids. The
173 tasks-7-8 rows stay stored, so the expansion needs no other bundle file,
and validation still compares them with the estimate table.

### Witness, derivation, replay and commands

- **Witness tables read the models** (CP7). `validate_bundle` expands both
  retained fixtures at its tables step. An expansion refusal passes through
  with the model's own `invalid_payload`; everything else there is still
  `table_mismatch`. The table-name constant, the witness's closed shape and
  its version 2 are unchanged, and so are the rows and digests it reports for
  the same objects: 91, 91, 115, 4, 10, 115, 115; 30, 30, 9, 391; 173. Only
  `fixtures` (bytes and raw digests of the compact files) differ.
  `build_witness` receives the models for its tables and the payloads' raw
  bytes for its fixtures.
- **`validate_bundle` returns** the witness, the estimate table and the two
  models by member name (CP13), so `replay` and its result
  (`review-feasibility-retained-result`, version 3) are unchanged in shape:
  `summary`, `aggregate`, `boundaries` and `operational_effects` are read from
  the models. RP19's three witness refusals and RP22's tree check are kept.
- **Old encodings are refused** (CP8). A SOURCE-encoded member, however
  coherent its witness and anchor, fails expansion's closed version and key
  check: `replay-retained: invalid: invalid_payload`, exit 2, empty stdout.
  No reader for an old version exists.
- **`derive_bundle`** changes only in what it hands the witness. Both command
  shells are unchanged: same options, exits and stderr lines.
  `MEMBER_MAX_BYTES` and `ANCHOR_MAX_BYTES` stay decode bounds (CP10).
- **Task 7** is untouched: its table, validator and bytes (CP10).

## Decisions

### Why a packed digest is still a whole record

A packed string holds every bit of every digest, losslessly, in the same file
and the same JSON member as the rows it belongs to. It is decoded by one
standard-library call. Nothing is truncated, hashed down, moved to another
file or left to a pin. The token widths make item boundaries visible, and step
3 refuses any second spelling of the same bytes. The alternative that keeps
hex does not exist under the cap (CP2).

### What may be recomputed

A member is recomputed only when it is a pure function of members stored in the
same payload (CP4). A fact that merely equals a pin stays stored: the criteria,
the assignments, the process paths, the overlap paths, both table policies and
the range. Expansion therefore takes no pins, and the facts are recoverable
from the bytes with the retained repositories, the archive and Git all absent.

Each recomputed member has a test that alters what it is computed from:

| Recomputed member | Input altered, re-compacted | Refusal |
|---|---|---|
| `parent_edges`, edge identity | A `parents` index moved to the base or an earlier commit; a commit's list emptied or reordered | `invalid_payload` (pinned raw-parent digest, coverage) |
| Edge records, `summary.edge_records` | A record index dropped from, or repeated in, an edge | `invalid_payload` (pinned counts) |
| `head_entry`, `disposition`, split counts | The last first-parent record's `after` changed on an integrated path; a `process` index added or removed; a `live` reference set to the head's | `invalid_payload` |
| `pending`, overlap entries | An overlap path changed or removed; an overlap on a non-candidate path | `invalid_payload` |
| Directory head | A `head_trees` row on a file path; a blob reference in one; the row removed | `invalid_payload` |
| `text_sha256`, criteria | A criterion text, state or row changed or removed | `invalid_payload` |
| Issue-121 edge chain and ids | A `classes` row moved, removed or re-owned | `invalid_payload` |
| Lineage, `record_refs`, `edge_ids` | An edge record's path changed; a record row moved to another scope; a row duplicated | `invalid_payload` |
| Failure references | An evidence index pointed at an edge outside the outcome's selection, removed or repeated | `invalid_payload` |
| Anchor signer and writer | `signer_sha256` changed; an anchor's commit or blob no longer the latest writing edge | `invalid_payload` |

### Published refusals on the compact encodings

| Refusal (SOURCE, REPLAY) | How it is reached on a payload | Code |
|---|---|---|
| Rehashed alteration of coverage, order or facts | The table above, with witness and anchor rebuilt under trust injection | `invalid_payload` |
| The same, bundle digests left stale | Any changed byte | `member_digest`, or `anchor_digest` when the anchor is rebuilt |
| Missing or reordered edge | A `commits` token or `parents` row removed or exchanged, an `edges` row removed; an issue-121 `edges` row removed, or a `classes` row removed or exchanged (CP17) | `invalid_payload` |
| Duplicate logical record | A repeated `records` row, entry id, path or final-record row | `invalid_payload` (step 3, or the unique scope-and-path rule) |
| Domain label or policy swap; historical bytes under fresh | `tables` policies or `bytes` exchanged | `invalid_payload` |
| Replacement anchor, tool-closure change, partial bundle | Unchanged paths | `anchor_digest`, `tool_closure`, `member_set` |
| Component, tree and policy substitutions (RP7, RP22) | Unchanged paths, reading the models | `component_mismatch`, `policy_mismatch` |
| Stale witness table or policy | Unchanged: the digest is over the model's table | `table_mismatch` |
| Old encoding | CP8 | `invalid_payload` |

Record bytes, record digests, the assignment of records to an edge and
`tool.commit` remain outside what a Git-free check can determine, exactly as
RP7 states; the trusted digest and derivation refuse them. Pin faults keep
`invalid_pins` and `assignment_mismatch`.

### File and directory swap (parked Important from 248)

The finding was that issue 100's history check refused the tree entry
`edge_facts` emits when a file and a directory swap at one path in one commit,
while issue 121's accepted it. S24 fixed it before SOURCE merged, REPLAY's
inherited table records that, and at this base both modules' swap tests pass.
This child carries the rule and both tests onto the compact encodings (CP9):
the directory side is a tree entry in `entries`, an added file may name the
directory it replaced, a deleted file the directory it became, and a
file entry forged onto that side is `invalid_payload` in both models.

### Delivery gates

REPLAY's § *Delivery gates* and RP14 apply with this child's base (CP12).

- **G0.** This spec, an indexed plan with `derived_from: null`, its task
  members and honest forecasts are committed; published CORE's
  `review-feasibility project` clears them at `--completed-through 0` before
  any product commit, validated and reproduced, and is renewed at
  `--completed-through N` after each accepted task and after any plan, spec or
  forecast change. Exit 2 or 3 stops with no bootstrap.
- **G1.** The complete fixed-base actual gate after every task and fix and at
  the final head.
- **G2.** After the last `python/` change: an authorship-independent review of
  the complete `python/` source at one pinned commit, and a fresh adversarial
  reviewer who repeats REPLAY's graft and rehash reproduction, compares the
  expansion of a scratch bundle with the models that the modules at
  `7e17c81` derive from the same objects, byte for byte, and tries
  non-canonical payloads. That commit is `AGENT_RETAINED_TOOL_COMMIT` for every
  authoritative run. Its full SHA, the five measured sizes and the new schema
  versions are posted on issue 235. A later `python/` change repeats G2 and
  the post.
- **G3.** Focused suites, `just agent-workflow-tests`, `just build`,
  `just agent-installed-skill-tests` and
  `just agent-retained-tests /Users/anis/tmp/nix-config` with the G2 pin, no
  skip counted as a pass, then separate conformance and correctness reviews.
  Retained runs are quiescent (RP11).

The two model modules and their suites are near 30–39 kB each, so the plan
prices their modify records with care. If G0 returns exit 3, the split is by
model: issue 121 first, then issue 100 with the witness change.

## Test seams

The existing seams and no others: modules imported under the recipe's
`PYTHONPATH`; commands as `python -m agent_tools.<module>`; real temporary Git
repositories through `tests/retained_review_test_support.py`;
`source_budget_env`; `tests/test_agent_tools_launchers.py` as the only module
touching built launchers; the full-shape tier under `just agent-retained-tests`.
A forged payload is built by changing a model or a payload and, where the case
needs it, calling `compact_*`; no test reads a private name.

| Issue criterion | Evidence |
|---|---|
| 1. Measured feasibility before product work | § *Measured feasibility* |
| 2. Each payload at most 65,536 B; tier asserts all five | Full-shape tier: every bundle file's length at most 65,536 |
| 3. Total and EVIDENCE headroom | § *Measured feasibility*; tier asserts the five-file sum at most 196,608 |
| 4. Issue-100 facts; fact-for-fact expansion | Tier: `expand_100` of the derived payload equals `model_100` from the same objects; the expansion holds 543 records, 115 contributions, 8/38/69 with 65 and 4, four overlaps, zero reconciled, ten criteria, both domains. Portable: the same equality on the fixture |
| 5. Issue-121 facts; expansion | Tier: `expand_121` equals `model_121`; 30 assignments (twelve process, eighteen task, the late Task-3 fix), ordered edges, nine anchors, both aggregates, each boundary's outcome with its closed fields. Portable: every fixture shape |
| 6. Every refusal, source and built; recomputed members | The two tables above in the portable suites; substitution checks 4 of the tier over the real bundle; built-launcher parity for the portable refusals and the real replay, sources unreachable |
| 7. Determinism, unchanged root, no skip | Existing tier checks, unchanged |
| 8. New versions; old encodings refused | Portable replay and command cases: a bundle holding the model as its member, digests coherent, is `invalid_payload` from source and built |
| 9. Swap disposition | CP9; both swap tests on payloads |
| 10. G2 and the pin on 235 | § *Delivery gates* |
| 11. G0, G1, suites, build, installed tier | § *Delivery gates* |

A JSON-kind mutation matrix, as S3's, runs over every top-level member of
both payloads and every position of one row per table: each kind and each
removal is `invalid_payload` and never a raw exception.

## Risks

- **Issue-100 headroom is 3,418 B** (2,949 B as a record). A review that adds
  a stored member spends it. CP5's reserves recover about 3.6 kB without
  touching a fact.
- **Witness and anchor grow** about 250 B per file added to `agent_tools`.
  This child adds none.
- **Reproducibility** still depends on a host without Git attributes or
  `diff.orderFile` (RP24,
  [255](https://github.com/fagenorn/nix-config/issues/255)).

## Out of scope

EVIDENCE: committing the bundle, the published trust identity and its
regressions. Also out: any cap, bound or packing-policy change; splitting a
file; the Task-7 table; the anchor contract and CORE's loader; a reader for old
encodings; a new command, option or module; any CLAUDE.md edit (no sentence
there describes these encodings); CORE's attribute guard (255); activation,
registration and lifecycle rollout. Nothing writes the retained root, its
object store or the archive.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| CP1 | Each module keeps SOURCE's Git derivation as `model_*` and adds a pure `compact_*`/`expand_*` pair. `derive_*` returns the payload after requiring its expansion to equal the model; `validate_*` is expand, pin checks, canonical form. No new module; the base85 primitive lives in `review_issue100`, its only user | Issue 254 (fact-for-fact equality with SOURCE's encoding; every refusal keeps its code); S6 (Git-free validators rebuild); the-bar DRY and YAGNI; measured exact round trips | Rewriting both validators over compact rows (two rule sets, every refusal re-proved from nothing). Building the payload straight from Git (no SOURCE encoding left to compare with) |
| CP2 | Issue-100 digests and object ids are RFC 1924 base85 in packed strings of fixed-width tokens (25 and 40 characters) | Measured: hex 85,017 B, base64 64,673 B, base85 62,118 B at one structure; `canonical_bytes` is ASCII JSON; 20 and 32 are multiples of 4; standard library | Hex: over the cap by 19,481 B. Base64: 863 B of headroom, lost to the diff header, and tokens do not align. A custom larger alphabet: about 2% smaller, not standard |
| CP3 | Issue-121 keeps hex digests verbatim and stores the tasks-7-8 rows | Measured 48,917 B, 16,619 B below the cap; smallest change that fits | Base85 there too: a transformation nothing needs. Reading tasks-7-8 rows from the estimate file: the payload would not expand alone |
| CP4 | A member is recomputed only as a pure function of members stored in the same payload. Pin-equal facts stay stored and expansion takes no pins. Each recomputed member has an input-alteration test | Issue 254 ("recoverable from the compact bytes alone"; criterion 6); issue 235 (every criterion preserved) | Dropping criteria, assignments and process paths to the pins: about 5 kB smaller, but those facts would then live in the tool, not the record |
| CP5 | Three measured reductions are not taken: deriving every `before` from base-tree entries plus the first-parent chain (−1,310 B, holds on all 543 real records), a directory table for paths (−1,579 B), columnar records (−771 B) | Brief (smaller, more reversible option); 3,418 B already clears the cap; each adds a rule SOURCE never had | Taking them now for margin: more expander rules for G2 to review, against sizes that cannot drift |
| CP6 | Canonical form is one check: `compact(expand(payload))` equals the payload. It covers table order, uniqueness, unused rows, first-use order, base85 spelling, negative indices and `true` for `1` | The-bar DRY; issue 254 (duplicate logical record refused) | A separate guard per ordering rule: many small checks, each needing its own failing test |
| CP7 | Witness tables are counted and digested over the models; the table-name constant and witness version 2 stay. An expansion refusal at that step passes through as `invalid_payload` | The witness then reports the facts the criteria name (543 through 91 edges, 115, 4, 10, 30, 391) with the values REPLAY's witness gives for the same objects, and it anchors the expansion rules, so a later tool with another expander fails `table_mismatch` (RP8) | Counting compact members: rows would be encoding artefacts (419 distinct tuples), packed strings have no rows, and nothing would bind the expander |
| CP8 | Old encodings fail the expander's closed version and key check as `invalid_payload`. No compatibility reader and no new code | Issue 254 criterion 8; RP19 (nearest closed code); the-bar YAGNI | A dedicated `schema_version` code: the closed sets are published and no consumer distinguishes it |
| CP9 | The parked swap finding is closed as already fixed by S24. The rule and both swap tests move onto the payloads, with the forged file-on-the-directory-side case | Verified at the base: both swap tests pass; REPLAY's inherited table; the prototype round-trips both swap fixtures | Re-fixing or relaxing the rule: nothing is broken, and the file side must stay strict (S24) |
| CP10 | Task 7 is untouched. `MEMBER_MAX_BYTES` stays a decode bound. The tier asserts each file at most 65,536 B and the five at most 196,608 B | Parent D18; RP13 (decode bounds are not review limits); issue 254 criteria 2 and 3; the record, not the file, meets CORE's cap, and EVIDENCE's actual gate measures the record | Lowering the decode bound to the review cap: couples replay of committed evidence to a review limit. Asserting exact sizes: a fitted result |
| CP11 | The oracle for fact-for-fact equality is `model_*`, SOURCE's unchanged derivation, in the tier and the portable suites; G2 adds an independent comparison with the modules at `7e17c81` | Issue 254 criteria 4 and 5; RP7 (no output digest pinned in the tool) | Pinning the SOURCE payloads' digests or sizes in a test: fitted, and the issue-121 measurement carries the host's policy digest |
| CP12 | This child runs REPLAY's gates with base `7e17c81`: G0 before product work and advanced per RP14, G1 after each task and fix, G2 after the last `python/` change with the pin, sizes and versions posted on issue 235, G3 at the final head. An exit-3 G0 splits by model | Issue 254 criteria 10 and 11; DERIVE decomposition (every child clears its own G0); RP13 (G2 repeats) | Reusing REPLAY's G2 pin: its `python/` bytes are not this child's |
| CP13 | `validate_*` return the model, and `validate_bundle` returns the two models under their member names; `unavailable_ids` and the replay result read models and keep their shapes | RP2 (one validation, replay only classifies); the result contract EVIDENCE consumes | Expanding again in `replay`: a second caller of the expander that could drift from what was validated |
| CP14 | Refines CP1: the derivation equality lives in `compact_*`, which packs the model and refuses, as `invalid_payload`, one whose packing does not expand back to it. `derive_*` is model, compact, validate, with no second comparison. `model_121` returns the model alone; `derive_121` takes the Task-7 table from the private helper both share | § *Solution* ("a model the payload cannot represent is `invalid_payload`"); measured at planning: with validation routed through that round trip all 43 published SOURCE cases pass unchanged (48 refusals at the round trip, 53 at SOURCE's checks on the expansion); the-bar (no guard that no test can turn red); § *Test seams* (no private name) | The comparison inside `derive_*` only: reachable only by patching `model_*`, and the published forged-model cases would lose their route |
| CP15 | Payload-level cases live in two new portable suites, `tests/test_review_compact100.py` and `tests/test_review_compact121.py`, listed in `agent-workflow-tests`. The published SOURCE suites keep their forged-model cases, routed through `compact_*` | CORE's 65,536 B whole-record cap: those suites are 24,374 B and 30,034 B, and the U10 record of a rewrite approaches old plus new; § *Test seams* (portable suites under the recipe) | Rewriting both suites in place: modify records no honest forecast holds below the cap |
| CP16 | `expand_100` terminates on every input: before the first-parent walk it refuses a repeated commit, a commit equal to the base and a parent index that is not the base or an earlier commit. The earlier-parent rule therefore lives in the expander | Measured at planning: the prototype expander never returns on a `parents` index that names a later commit, nor on a repeated `commits` token; SOURCE ran that check before `_at_head` | Leaving the rule to step 2, which runs only after expansion returns |
| CP17 | Corrects § *Published refusals*: in issue 121 a reordered edge is an exchanged `classes` row. Exchanging two `edges` rows moves records between commits, which no Git-free check determines (RP7), exactly as in SOURCE's encoding; the trusted digest and derivation refuse it. In the JSON-kind matrix an entry reference is `null` or an index, so neither kind is malformed in the other's place | Measured on the portable fixtures: exchanged `edges` rows validate, and a candidate's `live` reference changed between `null` and an index validates; § *Published refusals*, closing paragraph; RP7 | Binding records to commits Git-free: no pin determines it, and SOURCE never did |
| CP18 | Built-launcher parity is proved twice. Portable: a stub bundle built with `json` and `hashlib` alone gives `invalid_payload` for a SOURCE-encoded member under the real pins (expansion precedes the component check), `anchor_digest`, `member_digest` and `member_set`, and the derive command gives `tool_closure`. Real: `RetainedLauncherTest` replays a rehashed alteration of the real bundle, built and from source | The launcher suite is the only module touching built launchers and imports no `agent_tools` outside the retained recipe; both commands pass only real pins (parent D12); issue 254 criteria 6 and 8 | A pin option or environment override in the shipped commands; importing `agent_tools` in the installed tier |

Design and grill frontier: closed within the approved scope. The resolved
bindings carry no context-map or ADR route, so this ledger is the issue's
decision store.
