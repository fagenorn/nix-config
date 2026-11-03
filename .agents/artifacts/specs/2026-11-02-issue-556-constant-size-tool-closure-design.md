# A constant-size tool closure in the retained bundle — issue 556

Issue: https://github.com/fagenorn/nix-config/issues/556. It blocks
https://github.com/fagenorn/nix-config/issues/256 and
https://github.com/fagenorn/nix-config/issues/255, whose acceptance needs the
retained tier green. Designed autonomously (`from-issue --auto`); every call made
without the user is a row in the Decision ledger. Earlier ledgers are cited as
"parent 234 Dn" (the DERIVE design at `6e5224e`), "RPn" (issue 249), "CPn"
(issue 254) and "EVn" (issue 235).

## Triage

Input: `{"signals": {"contract_change": {"value": "hit", "evidence": "the derivation anchor and witness schemas (tool.files closure rows) are the retained-evidence contract read by replay-retained and the committed fixture"}, "concurrency_or_persistence": {"value": "doubt", "evidence": "retained evidence bundles are persisted artifacts; no locking or concurrency involved"}, "open_design_questions": {"value": "hit", "evidence": "whether to narrow the tool closure to the derivation's import closure or to a constant-size tree digest, and how committed evidence stays verifiable, is open"}, "criteria_shape": {"value": "no", "evidence": "three acceptance criteria, each verified by just agent-retained-tests, just agent-workflow-tests and just build"}}, "paths": ["python/agent_tools/review_witness.py", "python/agent_tools/derive_review_feasibility_fixtures.py", "python/agent_tools/replay_retained.py", "tests/test_review_retained_full.py", "tests/test_review_witness.py", "python/README.md"]}`
Verdict: `{"hits":["contract_change","concurrency_or_persistence","open_design_questions"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Problem

`just agent-retained-tests <root>` fails one case on `main`,
`test_bundle_files_fit_the_whole_record_caps`: the bundle the tier derives at
test time is 203,078 B against the tier's 196,608 B bound (three members' worth
of CORE's whole-record cap, CP10). The committed bundle is 184,452 B and the
tier's other 46 cases pass. Until the tier is green, #256 and #255 cannot meet
their acceptance, and nobody can claim the retained tier as evidence.

### Measured cause

`tool_closure` lists one `{path, blob, raw_sha256}` row for every blob under
`python/agent_tools/` at the tool commit, about 161 B per row. The `tool` group
holds that list, and the group appears twice: in the anchor and in the
witness's `components` (RP3). Each package file therefore costs about 322 B of
bundle.

| Tool commit | Package files | Five-file total | Anchor |
|---|---|---|---|
| `691d8f25` (the committed evidence's) | 57 | 184,452 B | 13,769 B |
| `65fd4c21` (before #256 merged, from the issue) | 101 | 198,536 B | — |
| `e692c968` (this base) | 115 | 203,078 B | 23,082 B |

Measured on 2026-11-02 with the source derive command at this base, against
`/Users/anis/tmp/nix-config` (read only). The three fixture payloads are byte
for byte the committed ones, the four non-tool groups equal the committed
anchor's, and the policy digest is unchanged. Only the tool group's list grew:
from 9,177 B to 18,490 B per copy. Nothing else moved.

The growth has no bound. The agent-helper standard sends all new helper code
into this package, so the list keeps growing. At about 175 files the anchor
would also pass `ANCHOR_MAX_BYTES` (32,768 B), and derivation would refuse its
own output as `member_oversize`.

### Why the cap is right and the encoding is wrong

CP10 set the five-file bound on one premise: "the retained objects are pinned,
so these sizes are constants of the encoding: headroom is spent only by a later
encoding change". Every group except `tool` holds pinned facts. RP3 chose the
full list when the package was about 55 files. The premise held then, and the
package's growth has since broken it. The bound is right. The tool group is the
one member whose size is not a constant of the encoding.

## Solution

The tool group binds the closure by one digest instead of listing it.

| Member | Before | After |
|---|---|---|
| `commit` | the tool commit | unchanged |
| closure binding | `files`: the sorted `{path, blob, raw_sha256}` rows | `files_sha256`: `telemetry_digest` of exactly those rows |
| `artifact_policy_sha256`, `packing_policy_sha256`, `record_policy_sha256` | unchanged | unchanged |

`tool_closure` and `verify_running_closure` do not change. Derivation still
computes the full rows from Git and still requires the running package to equal
them before it reads any retained object. Only the encoded group changes. All
five members are fixed-width strings, so the group is 436 B whatever the
package holds.

Simulated on both measured bundles, with only the tool group re-encoded:

| | Anchor | Witness | Five-file total | Under 196,608 B |
|---|---|---|---|---|
| 57 or 115 package files | 4,671 B | 6,794 B | 166,257 B | 30,351 B |

The committed evidence is derived again with the new tool and re-pinned, under
EVIDENCE's publication protocol as D5 adapts it. No cap, bound or decode limit
changes.

## Decisions

### The tool group (D1, D2, D3)

- `files_sha256 = telemetry_digest(closure["files"])`, the agent-helper
  standard's one canonical digest, over the rows `tool_closure` returns: sorted
  by `path`, each `{path, blob, raw_sha256}`. Anyone with the tool repository
  recomputes it from `tool.commit`, so it binds the same facts as the list did,
  with SHA-256 over every file's bytes and the commit's own object ids.
- The name follows the groups' existing rule, `<value>_sha256` for
  `telemetry_digest(<value>)`, as in `parent_edges_sha256` and `table_sha256`.
- `derive_bundle` assembles the group privately, as it does every group (RP16):
  the commit, the digest of the rows and the three policy digests. The rows
  never leave derivation.
- RP3 rejected a different digest design: a digest in the anchor with the list
  only in the witness, because the components would then differ and the anchor
  would not carry the reviewed identities. Here both copies hold the same
  digest, so the components stay identical. The anchor still carries the
  reviewed commit and binds every reviewed file by SHA-256. Nothing ever read
  the listed rows: CORE's loader checks only that `tool` is an object, replay
  never checks the closure (RP8), and Git-free validation checked their shape
  only (RP16). Only `review_witness`, `derive_bundle` (which spreads the
  closure into the group) and the witness suite touch `tool.files`.
- The witness and anchor `schema_version` stay 2 and their keys stay the same.
  The anchor's version is CORE's `retained-anchor/v2` envelope (parent 234 D3),
  whose loader requires only that `tool` be an object. The witness's components
  must equal the anchor's, so a witness-only bump would describe nothing the
  anchor does not. The old shape is refused as `component_mismatch`, an
  existing code.

### Validation (D2)

`validate_bundle` requires the tool group to be closed over exactly
`commit, files_sha256, artifact_policy_sha256, packing_policy_sha256,
record_policy_sha256`. `commit` is 40 hex and `files_sha256` a
`sha256:`-prefixed 64-hex digest. Anything else, a `files` list included, is
`component_mismatch`. No other refusal code, error class or command outcome
changes.

RP7's two layers keep their meaning. Under the trusted digest, any change to
the group is `anchor_digest`, or `member_digest` once the trusted anchor is
restored, as for every other site. Git-free, `files_sha256`, like `tool.commit`
and `archive.shards`, is checked for shape only. Re-derivation alone
authenticates it: derivation recomputes it, and the reproduction case compares
bytes. Replay still never compares the running package with the tool group
(RP8).

### Committed evidence (D4, D5)

The validator accepts one shape, so the committed bundle, which still holds the
57-row list, must be derived again. Its three fixture payloads stay byte for
byte the same. The anchor and the witness change, and so do the literals
`ANCHOR_SHA256` and `TOOL_COMMIT`. The re-issue follows EVIDENCE's publication
protocol ("a later change is a new derivation under this same protocol"), with
D5's adaptations:

1. **Tool commit `T`.** `T` is the last branch commit that changes `python/`,
   taken once the encoding task's review has passed, its fixes included.
   Through publication, `HEAD:python` equals `T:python`.
2. **Host basis.** EVIDENCE's step 1, unchanged. Any attribute or `diff.*`
   setting stops publication (#255 is open, RP24).
3. **Derivation A.** The source command, `--tool-commit T`, in `T`'s matching
   source environment: `T`'s package, and the budget helper and policy from
   `T`'s tree, as the reproduction case runs them. It runs against a quiescent
   retained root that is compared before and after (RP11). The root
   is the issue's private copy: a `git clone --no-local` with all refs, plus the
   main checkout's object store for the unreachable pins and its `.superpowers/`
   archive. A's three fixture payloads must equal the committed ones byte for
   byte. If one differs, publication stops and names the bound identity that
   moved (EVIDENCE step 4). A's five files replace the committed five, and
   A's `anchor_sha256` and `T` become the literals, in one commit. The blobs
   read back from Git must equal A's files.
4. **Derivation B** is the final verification's retained-tier run at the branch
   head, a separate actor from A. Its reproduction case derives again from a
   clone at `T` and must equal the committed five byte for byte and the literal
   digest (EV4). Its launcher case proves built-and-source parity. EVIDENCE's
   design-time digest cannot exist here, because `T` does not exist while this
   is designed. The anchor binds `T`, so the digest is fixed only by A.
5. **A later change on this branch** repeats steps 1–4 only if the branch-head
   tool would refuse the committed bundle, or would emit different bytes from
   `T`'s for the pinned inputs beyond `tool.commit` and `files_sha256`. That
   means a change to the encoding, to the derivation or validation code, or to
   the review-package policy digest. A change
   that only moves the package, such as a new module or a merge from `main`,
   leaves the evidence bound to `T`. That is EV4's rule for any later package
   change, and the reproduction case keeps deriving at `T`.

### Documents (D6)

`python/README.md` § *Retained review evidence*, the home that `CLAUDE.md`
names for this contract, gains one sentence. The bundle's `tool` group binds
the whole package as the tool commit and `files_sha256`, so the bundle's size
does not grow with the package. The module docstrings of `review_witness` and
`review_derivation` name `tool.files_sha256` wherever they name `tool.files`.
So does the tier's comment on its Git-free site table. Point-in-time records,
the 234/249/254/235 specs, plans and audit included, are not edited.

### Headroom (D7)

No new size target or assertion is added. Once the change lands, the five-file
total is again a function of pinned objects and fixed-width encodings, the
premise CP10 states, so the tier's existing assertions are the right ones. Each
file is at most 65,536 B and the five together at most 196,608 B. The tier
already asserts that the class derivation's anchor is at most
`ANCHOR_MAX_BYTES`, and derivation refuses a larger one.
Expected after the change: 166,257 B, with 30,351 B to spare, and an anchor of
4,671 B.

### Delivery order

1. Encoding, validator and their tests, with the docstrings and the README
   sentence. Its last `python/` commit, once the review passes, is `T`
   (D5 step 1).
2. Re-issue the evidence and the literals (D5 steps 2–3).
3. Final verification: `just agent-workflow-tests`, `just build` and
   `just agent-retained-tests <quiescent root>`, the last as D5 step 4. A
   skipped case is not acceptance.

## Test seams

The existing seams, no new module, recipe or command. Modules are imported
under the recipe's `PYTHONPATH`. Commands run as
`python -m agent_tools.<module>`. The portable suites run in CI. The full-shape
tier runs locally against a retained root.

| Seam | Prior art | What it proves here |
|---|---|---|
| `tests/test_review_witness.py` (portable) | its component-substitution table and closure cases | The closed tool shape: a `files` list in place of or beside `files_sha256`, a missing `files_sha256` and a non-digest one are each `component_mismatch`. `tool_closure` keeps its sorted, complete rows, and the fixture's group digest is `telemetry_digest` of them. `verify_running_closure` still refuses a changed, extra or missing file |
| `tests/test_review_derivation.py` (portable, real package via `tool_fixture`) | its derive-twice and summary cases | A derived anchor's tool group is exactly the five members, and its `files_sha256` equals `telemetry_digest` of `tool_closure`'s rows for the tool commit. This is the binding that no Git-free check can make |
| `tests/test_review_evidence.py` (portable, committed copy) | EV3, EV6 | Unchanged cases over the re-issued copy: authentic replay to the historical refusal, the literal facts, the tamper and site tables. It now runs on the format the tool emits |
| `tests/test_review_retained_full.py` (tier) | CP10, EV4 | Acceptance 1. The cap case on a fresh derivation, the reproduction case at `T`, two byte-identical derivations, and the dirty-tool refusal |
| `tests/test_agent_tools_launchers.py` (installed and tier) | EV3's built cases | Unchanged. The built replay of the committed copy equals the source's |

No case asserts an exact file size (CP10, CP11). A test fixture that builds
components mirrors derivation's assembly, as the witness suite's fixture
already does.

## Out of scope

- Raising, lowering or adding any cap, bound or decode limit:
  `MEMBER_MAX_BYTES`, `ANCHOR_MAX_BYTES`, the tier's `MEMBER_CAP` and
  `BUNDLE_CAP`, CORE's policy.
- Changing what the closure covers. It stays the whole package (parent 234 D6),
  and `verify_running_closure`'s exact-equality rule stays.
- The three fixture payloads' encodings, the witness's tables, the other four
  component groups, and the anchor envelope CORE loads.
- A reader for the old tool-group shape (D4).
- Any replay-time closure check (RP8).
- #256's expansion bound and #255's attribute guard. This issue only unblocks
  them.
- Editing point-in-time records: earlier specs, plans, the 226 audit and the
  issue 235 spec's recorded digest.

## Risks

- **Re-issue needs a quiescent full root.** The shared checkout changes under
  concurrent agents and voids runs (RP11). D5 names the private-copy recipe the
  issue used.
- **A late source fix moves the evidence.** D5 step 5 limits this to fixes
  that change the bundle's encoding, its derivation or validation, or the
  policy digest.
- **A `main` change can stop step 3.** If a sync moves the review-package
  policy digest or a retained input before publication, A's payloads differ.
  Publication then stops and names that identity. It never adopts the new
  bytes silently.
- **The reproduction case needs `T` in the checkout's object store.** The merge
  strategy keeps branch commits, so `T` stays reachable from `main`.
- **The tier takes about half an hour,** plus one derivation of about 2–7
  minutes for A.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Fix the encoding, not the cap: the tool group binds the closure by one constant-size digest in both copies. Refines RP3 (the full list in both copies) and keeps its rule that the components are identical | Measured: 322 B per package file, all the growth, 57 → 115 files; CP10's premise that sizes are constants of the encoding; issue 556 and #256 forbid raising caps; parent 234 § Bundle requires only that the group *bind* the closure | Narrowing to the derive/replay import closure: parent 234 D6 rejected it as fragile static analysis, and it still grows. The list in one copy only: RP3 rejected differing components, and the anchor still breaks 32,768 B near 175 files. Dropping `blob` from the rows: 191,578 B today, which is room for about 22 more files at 222 B each, and the slope is still unbounded. Raising `BUNDLE_CAP`: forbidden, and growth would only overrun it again |
| D2 | `files_sha256 = telemetry_digest(rows)` over `tool_closure`'s unchanged sorted `{path, blob, raw_sha256}` rows. The group is closed over five fixed-width members, and any other shape is `component_mismatch`. Both schema versions stay 2 | agent-helper standard 4 (one canonical digest); the `parent_edges_sha256`/`table_sha256` naming precedent; CORE's loader checks only that `tool` is an object (parent 234 D3); RP7/RP16 (Git-free shape only) | The Git tree id of `python/agent_tools`: SHA-1, already implied by `commit`, so it adds nothing. A digest over `{path, raw_sha256}` only: verification would need a second row builder. Bumping the witness version alone: the anchor carries the same group and cannot bump |
| D3 | `tool_closure` and `verify_running_closure` keep their contracts. `derive_bundle` turns the rows into the digest privately, and no public builder is added | RP16 (derivation assembles the groups privately; a public components builder widens the closed surface); parent 234 D6 (the exact running-package check) | Folding the running check into `tool_closure` so that it returns the digest: verification would then need rows that no longer exist. A public `tool_component` helper: rejected by RP16 |
| D4 | The validator accepts only the new shape, and the committed evidence is derived again and re-pinned: new `ANCHOR_SHA256` and `TOOL_COMMIT`, and new anchor and witness bytes. The three payloads are expected to stay identical | EVIDENCE: "a later change is a new derivation under this same protocol"; 254 refuses SOURCE's old encodings and 235 scoped out "a reader for old encodings"; the-bar YAGNI and Root causes; CI's committed-copy suite should exercise the shape the tool emits | A dual-shape validator that keeps the 57-row bundle valid: a permanent special case for the unbounded shape, and CI would check only the legacy shape on real data. Leaving the committed bundle stale: the portable suite would fail |
| D5 | The re-issue protocol refines EV5. `T` is the reviewed encoding commit. Derivation A, from source at `T` on the private quiescent root, must reproduce the three payloads exactly. Derivation B is the final tier run's reproduction case. A later bundle-changing `python/` fix repeats it | EV5, EV8, RP11, RP24; EV4 (evidence bound to its tool commit); the issue's root recipe; the anchor binds `T`, so no design-time digest can exist | EVIDENCE's design-time digest leg: impossible before `T` exists. A bespoke built-launcher derivation B: the tier's reproduction and launcher-parity cases already give an independent re-derivation and the built path |
| D6 | One `python/README.md` sentence states the tool group's digest binding and why the bundle stays a constant size. Living docstrings and the tier's site comment are updated, and point-in-time records are not | `CLAUDE.md` names `python/README.md` as the home for retained-evidence detail; the-bar *Moves keep their history* (accepted records keep their bytes) | A new section or an ADR: the bindings carry no ADR route, and this ledger is the decision store. Amending the 249/254 specs: point-in-time records |
| D7 | No new headroom target or size assertion. The existing per-file and five-file bounds become stable once the bundle is a constant of the encoding: 166,257 B expected, 30,351 B below the bound | CP10 (bounds stated, exact sizes rejected as fitted); CP11; the measured simulation above | A tighter tier bound or an exact-size pin: fitted to today's bytes. A test that varies the package's file count: verification refuses any package that is not the running one, and the closed fixed-width shape already makes the size constant |
| D8 | Refines D5 (grill). Derivation A runs in `T`'s matching source environment: `T`'s package, budget helper and policy. Steps 1–4 repeat only for a later change that the branch-head tool would refuse the committed bundle over, or that changes its bytes beyond `tool.commit` and `files_sha256`: the encoding, the derivation or validation code, or the policy digest. A package-only move, a merge from `main` included, leaves the evidence bound to `T` | EVIDENCE publication step 2 ("in the matching source environment"); `validate_bundle`'s `policy_mismatch` ties issue 121's measurements to the tool group's policy digest; measured: the digest at this base equals the committed one; EV4 | Deriving A with the installed helper: its policy can differ and change `issue-121.json` for a reason unrelated to the encoding. Re-issuing after every `python/` change: EV4 rejected forced republication for unrelated changes |
| D9 | Plan. Two tasks with a red window at `T`. Task 1 makes every `python/` change, and its reviewed head is `T`. Task 2 re-derives the evidence at `T`. Between them the committed-copy suites (`tests/test_review_evidence.py`, the launchers' committed-evidence case) fail as `component_mismatch`. So Task 1's gate is the focused suites plus the tier's cap and twin-derivation cases alone. The full tier first runs in Task 2's gate, as A's own check; derivation B stays the final gate's (D5 step 4) | D4 (one accepted shape); D5 (`T` follows the encoding review, and the anchor binds `T`, so the evidence cannot share `T`'s commit); the tier's `tool_commit()` requires `T:python` to equal `HEAD:python` | One task: `T` would come before its own review (D5). A dual-shape validator to keep `T` green: rejected by D4. The full tier at `T`: its committed-evidence launcher case is red by construction |
| D10 | Plan. Every retained run reads a private root, built fresh under the runner's `launch-scope scratch`: a `git clone --no-local --no-checkout` of the main checkout, plus a copy of its whole `.git/objects` (for unreachable pins such as `fe85677c`) and of the one archive directory the tier reads | RP11; the issue's recipe; planning built one (42 MB, the four retained commits present) and reproduced the base failure on it (203,078 B) | The shared main checkout: concurrent agents void its runs (RP11). The main object store as an alternate: a gc or repack there would go unseen, because `root_state` walks only the root's own `objects`. All of `.superpowers` (156 MB): the tier reads only the archive |

Design and grill frontier: closed within the approved scope. The resolved
bindings carry no context map, glossary or ADR route, so this ledger is the
issue's decision store and no domain document was written.
