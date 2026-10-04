# Issue 249 — retained derivation, portable replay and the full-shape tier (DP234-REPLAY)

## Problem

Parent [234](https://github.com/fagenorn/nix-config/issues/234) (DERIVE) must let
anyone check two retained deliveries without the retained repositories. Its
first child, SOURCE ([248](https://github.com/fagenorn/nix-config/issues/248)),
published three library models on CORE. Nothing yet turns them into evidence: no
witness or anchor, no bundle writer, no replay, no command and no committed
acceptance on the real objects. This child, `DP234-REPLAY` / slug
`retained-derivation-replay`, delivers those and completes DERIVE's tooling.
[EVIDENCE 235](https://github.com/fagenorn/nix-config/issues/235) then commits
the concrete bundle.

SOURCE merged at its projected review ceiling, so its unfixed review findings
fall into this child's range, and two facts measured for this design (RP13,
RP14) change how the delivery must be run.

Immutable `DELIVERY_BASE`: `218f5bc0bf3556fa05959e6ba24175685b58e2a9`,
integration with published CORE and SOURCE. Every complete gate covers every
process and product commit after it. Parents 234 and 226 stay open.

## Binding parent design

The [DERIVE design at `6e5224e`](https://github.com/fagenorn/nix-config/blob/6e5224edcdd6477fbde42439f01c2ffaf211ac91/.agents/artifacts/specs/2026-10-03-issue-234-retained-review-derivation-design.md)
("parent spec") binds this child for § *Bundle, witness and anchor*,
§ *Commands*, § *DERIVE's own delivery gate* and § *Test seams*, and for its
rows D1, D3, D6–D10, D13, D14, D16 and D17. The
[decomposition](https://github.com/fagenorn/nix-config/blob/6e5224edcdd6477fbde42439f01c2ffaf211ac91/.agents/artifacts/specs/2026-10-03-issue-234-derive-decomposition-design.md)
Q1–Q4 assigns parent plan Tasks 4–8 here. The
[SOURCE spec](2026-10-03-issue-248-retained-source-models-design.md) rows S6,
S9–S11, S16 and S22–S24 describe the modules this child consumes.

This spec does not restate those contracts. It records what this child adds,
narrows or fixes. Rows prefixed `RP` are this issue's decisions; `parent Dn` and
`Sn` cite the other ledgers. A row wins over the parent only where it says
"refines".

## Solution

Three library modules and two thin command modules join `agent_tools`, two rows
join the command table, and three SOURCE modules get small corrections.

| Module | Responsibility | Public surface |
|---|---|---|
| `review_witness` | The bundle contract: tool closure, witness, anchor, authentication and full semantic validation | `WitnessError`, `ANCHOR_NAME`, `PAYLOAD_NAMES`, `ANCHOR_MAX_BYTES`, `MEMBER_MAX_BYTES`, `tool_closure`, `verify_running_closure`, `build_witness`, `build_anchor`, `authenticate`, `validate_bundle` |
| `review_derivation` | Deterministic five-file derivation into a fresh directory | `DeriveInputs`, `DerivationError`, `derive_bundle` |
| `review_replay` | Classification of a validated bundle and the retained result | `ReplayUnavailable`, `replay` |
| `derive_review_feasibility_fixtures` | Command shell | `main(argv=None) -> int` |
| `replay_retained` | Command shell | `main(argv=None) -> int` |

Signatures (pins are the SOURCE pin records, passed explicitly, parent D12):

- `tool_closure(tool_repo: Path, tool_commit: str) -> dict`
- `verify_running_closure(closure: dict) -> None`
- `build_witness(components: dict, payloads: Mapping[str, dict], raw: Mapping[str, bytes]) -> dict`
- `build_anchor(components: dict, raw: Mapping[str, bytes]) -> dict`
- `authenticate(bundle_dir: Path, expected_anchor_sha256: str) -> tuple[dict, dict[str, bytes]]`
- `validate_bundle(anchor: dict, raw: Mapping[str, bytes], *, task7_pins, issue121_pins, issue100_pins) -> dict[str, dict]`
- `DeriveInputs(issue_121_repo, issue_100_repo, archive_dir, tool_repo: Path; tool_commit: str; output_dir: Path)`, frozen
- `derive_bundle(inputs: DeriveInputs, *, task7_pins, issue121_pins, issue100_pins, authority: BudgetAuthority) -> dict`
- `replay(bundle_dir: Path, expected_anchor_sha256: str, *, task7_pins, issue121_pins, issue100_pins) -> dict`

Both commands pass only the real pin constants (`TASK7_PINS`, `ISSUE_121_PINS`,
`ISSUE_100_PINS`) and offer no pin option.

## Decisions

### Inherited SOURCE corrections

The first task fixes SOURCE defects before any new module builds on them, so the
G2 source pin covers the corrected bytes (RP1).

| Inherited finding (248 review ledgers) | Disposition |
|---|---|
| **Important, parked:** issue-100 `_validate_history` refuses a same-commit file/directory swap that `edge_facts` emits | Already fixed at this base by S24 (`b914df4`): the file side of a record is a blob or commit entry, the other side null or a tree. Both modules carry a swap test. No change; the full-shape tier validates the real payload through it. |
| `review_task7._numstat` splits every tab | **Fix.** Split the two counts only (`split(b"\t", 2)`), with a `compose` case over a path that holds a tab. |
| `review_issue100._checked` never hex-validates `producer_sha256`/`manifest_sha256` | **Fix.** Both must be 64 lowercase hex, else `invalid_pins`; one test per pin. |
| Git-free `validate_121` binds edges to the base and the assignments but not the last assignment to `pins.head` (found by this design's grill) | **Fix.** `_assigned` refuses pins whose last assignment is not `pins.head`, as `assignment_mismatch` (the code the existing mutation cases expect), which closes the parent's "chain from the pinned base to the pinned head" without Git. |
| `head_entry.oid` unconstrained where a contribution path became a directory; validators accept a consistently rehashed record byte count or digest | **Decline in the validators.** No Git-free check can re-measure a record or a tree (S6). RP7 states where each such fact is authenticated. |
| `derive_121` turns a `derive_task7` pin fault into an unavailable outcome | **Closed by RP5** without a SOURCE edit: derivation derives the table first and refuses on any `EstimateError`. |
| Pinned raw-parent digest also fixes Git's range order; issue-100 file side is strict | **Accept.** Both fail closed. |
| Readability in `review_issue100` (chained requires, a walrus, a loop variable); broad `KeyError`/`TypeError` translation to `invalid_payload`; redundant guarded history calls, the unused `table` parameter and `_estimate_code` naming in `review_issue121`; the duplicated edge-record shape check; test structure (fixture mixin, support imports, unreachable unknown-status and binary-numstat branches) | **Decline** (RP1). None changes behaviour, each fails closed, and each would add a large modify record on a 30 KB file that G2 must then re-review. The duplicated shape check is pinned on both sides by its own swap test. |
| 248's test-seams table omits its S22–S24 cases; a 65-byte subject; trailer wording | **Decline.** 248's spec and history are accepted point-in-time records. This plan checks every subject's byte length before committing. |
| 248's G2 ran while commits landed, and used `tasks-1-3` where the demo names `tasks-1` | **Fix by design:** RP11 (quiescent runs, selector `tasks-1`). |

### Tool closure

`tool_closure` returns `{commit, files}`: every blob under `python/agent_tools/`
at the full, original-history-authenticated `--tool-commit`, as sorted
`{path, blob, raw_sha256}` rows. It reads with `git ls-tree -r -z` and
`cat-file` only. A path that is not a regular blob refuses.

`verify_running_closure` reads the running package through
`importlib.resources.files("agent_tools")` and never loads a module by path
(parent D6). It walks the package, ignoring `__pycache__` directories only. The
set of relative paths must equal the closure's and each file's SHA-256 must
equal its row. An extra, missing or differing file is `tool_closure`. A dirty
source tree and a stale build therefore both refuse.

### Witness and anchor

The bundle is exactly `issue-121.json`, `issue-100-derived.json`,
`task7-estimate.json`, `derivation-witness.json` and `derivation-anchor.json`,
each `canonical_bytes` output (sorted, compact, ASCII, one LF). The first three are the *fixtures*; with the witness they are the four *payloads* the anchor hashes.

Five provenance groups, the *components*, are computed once and appear
identically in the witness and the anchor:

| Group | Members |
|---|---|
| `tool` | `commit`, `files`, `artifact_policy_sha256` (the budget authority's), `packing_policy_sha256`, `record_policy_sha256` |
| `issue_121` | `base`, `head`, `tree` (the head's raw tree), `signer_sha256` |
| `issue_100` | `base`, `head`, `live`, `parent_edges_sha256` |
| `archive` | `verify_archive`'s result: `producer_sha256`, `manifest_sha256`, `shards` |
| `estimate` | `prerequisite_commit`, `prerequisite_tree`, `plan_root_blob`, `task7_blob`, `model_version`, `table_sha256` (`telemetry_digest` of the table) |

**Witness** (version 2, kind `review-feasibility-derivation-witness`): exactly
`schema_version, kind, components, fixtures, tables, table_policies`.

- `fixtures`: the three fixture payloads in path order, each
  `{path, bytes, raw_sha256}`.
- `tables`: for each named table of each fixture, `{fixture, table, rows, sha256}`
  with `telemetry_digest` of the table. One module constant lists the tables:
  issue 121 `classes, edges, anchors, records`; issue 100
  `parent_edges, edges, contributions, pending_overlaps, criteria`, plus
  `tables.historical` and `tables.fresh`; the estimate's `rows`.
- `table_policies`: `{"<fixture>#<table>": {domain, policy_sha256}}` for the
  three raw-record tables (issue 121 `records`, issue 100 `tables.historical`
  and `tables.fresh`), copied from the payloads.

It carries no anchor identity and no digest of itself.

**Anchor**: CORE's `retained-anchor/v2` contract exactly (parent D3). Keys
`schema_version` (2), `kind` (`review-feasibility-derivation-anchor`), the five
groups and `payload: {encoding: "canonical-json-ascii-lf/v1", members}`. The
members are `{path, bytes, raw_sha256}` in the loader's fixed order (witness,
issue 100, issue 121, estimate), and `raw_sha256` is bare 64-hex, as
`review_forecast._derivation` requires. The anchor's identity is
`telemetry_digest(anchor)`.

**Acyclic construction.** Each step reads only earlier outputs:

1. components (inputs and tool closure only);
2. the three fixture payloads;
3. the witness, over the components and the fixtures' raw bytes;
4. the anchor, over the components and all four payloads' raw bytes.

No payload names the anchor, and the anchor is in no payload, so no digest
depends on itself.

### Derivation and its command

`derive-review-feasibility-fixtures` takes exactly six required options:
`--issue-121-repo`, `--issue-100-repo`, `--archive-dir`, `--tool-repo`,
`--tool-commit FULL_SHA` and `--output-dir`. The budget authority is the one
ambient dependency: `describe("review-package")` runs `artifact-budget` by name
on `PATH` (parent D9), and its policy identity is bound in the `tool` group.

`derive_bundle` runs in this order:

1. **Refuse bad inputs and a bad output.** `--tool-commit` must be 40 lowercase hex and each input a directory (`invalid_inputs`). `output_dir` must not exist (`lstat`, so a dangling
   symlink counts) and its parent must be a directory: `output_exists`. Its
   resolved path must not equal, contain or lie inside any input path or any
   input repository's common Git directory: `output_aliases_input`. Inputs may
   coincide with each other.
2. **Tool closure.** `verify_running_closure(tool_closure(...))`.
3. **Payloads.** `derive_task7` on the issue-121 repository, then `derive_121`,
   then `derive_100` with the issue-100 repository as both its issue and live
   repository (RP4). Any `EstimateError` is fatal (RP5).
4. **Encode** the three payloads; refuse a member above `MEMBER_MAX_BYTES`
   (`member_oversize`).
5. **Witness, then anchor**, as above.
6. **Self-validate.** `validate_bundle` over the anchor and the raw members: the
   same function replay runs (parent D11, RP2).
7. **Publish.** Everything is written in one private
   `mkdtemp(dir=output_dir.parent, prefix=".derive-")` directory, which is
   renamed to `output_dir` only after step 6. A `finally` removes it, so a
   failure leaves neither output nor scratch.

It returns `{anchor_sha256, members}` over all five files in path order, each
`{path, bytes, raw_sha256}`. The command prints `canonical_bytes` of it.

**Determinism.** No clock, locale, hostname, path, environment value or
directory order reaches an output. Two derivations are byte-identical.

**Inputs stay unchanged** by construction: derivation issues only read-only
plumbing, SOURCE's scratch work happens in alternates-backed temporaries, and
CORE's guard refuses grafts, replace refs, shallow files and routing variables.
The tests prove it (RP6); derivation takes no runtime snapshot.

### Replay and its command

`replay-retained --fixtures-dir DIR --expected-anchor-sha256 sha256:HEX`.
Replay runs no Git, needs no budget authority and reads only `DIR`. Each parser's `prog` is its command name.

1. **Anchor.** A malformed expected digest is `expected_digest`. Read
   `derivation-anchor.json` with `read_regular` under `ANCHOR_MAX_BYTES`
   (`anchor_unreadable`), strict-decode it and require the closed version-2
   shape and canonical bytes (`anchor_shape`), then
   `telemetry_digest(anchor) == expected` (`anchor_digest`).
2. **Members.** The directory must hold exactly the five names, each a regular
   file and not a symlink (`member_set`). Every declared `bytes` is at most
   `MEMBER_MAX_BYTES`. Each member is read with its declared size as the limit,
   and its length and SHA-256 must match before anything decodes it
   (`member_digest`). Names are fixed constants, so no member path can traverse.
3. **Semantics** (`validate_bundle`). In order: strict-decode each payload and
   require canonical bytes (`member_noncanonical`); the witness's closed shape,
   components equal to the anchor's, fixtures equal to the anchor's members, and
   every table row count, digest and policy recomputed (`witness_shape`,
   `component_mismatch`, `table_mismatch`); the components against the pins and
   policy constants (`component_mismatch`); `validate_task7`; `validate_121`
   with that table; `validate_100`; every measured outcome's
   `artifact_policy_sha256` equal to the `tool` group's (`policy_mismatch`).
   The SOURCE validators already own the Git-free chain checks: issue 121's
   ordinal-1 chain from the pinned base through the pinned assignments, and
   issue 100's pinned raw-parent edges over the pinned range.
4. **Classify**, only now. `unavailable_ids` lists unavailable outcomes in
   outcome order.

| Outcome | Exit | stdout | stderr |
|---|---|---|---|
| Every outcome measured, over budget included | 0 | canonical result | empty |
| Any outcome unavailable | 2 | empty | `replay-retained: projection_unavailable: <ids joined by ",">` |
| Invalid input, at any step | 2 | empty | `replay-retained: invalid: <code>` |

The result is `{schema_version: 3, kind: "review-feasibility-retained-result",
anchor_sha256, issue_121: {aggregate, boundaries, operational_effects},
issue_100: {history_edge_count, disposition_counts, pending_overlap_count,
fixture_sha256}}`. The issue-100 counts come from the validated summary
(`edge_records`, the three dispositions, `pending_overlaps`), and
`fixture_sha256` is the member's raw digest. No mixed object is emitted.

The derive command shares the last row's shape:
`derive-review-feasibility-fixtures: invalid: <code>`, exit 2, empty stdout.

### Error codes

`WitnessError` and `DerivationError` refuse an undeclared code at construction,
as `EstimateError` does. The codes this child owns are closed:

- `review_witness`: `tool_closure`, `anchor_unreadable`, `anchor_shape`,
  `anchor_digest`, `expected_digest`, `member_set`, `member_digest`,
  `member_noncanonical`, `witness_shape`, `component_mismatch`,
  `table_mismatch`, `policy_mismatch`.
- `review_derivation`: `invalid_inputs`, `output_exists`,
  `output_aliases_input`, `member_oversize`.
- The command shells: `usage` (the parser's `error` raises, as
  `review_feasibility._Parser`), `budget_unavailable` (`BudgetError`) and
  `io_error` (`OSError`).

`EstimateError`, `ContributionError` and `Issue100Error` pass their own `code`
through unchanged. Every emitted code matches `[a-z0-9_]+`. Nothing else is
caught: an unexpected exception is a defect and exits with a traceback (RP8).

### Publication

`lib/agent-tools.nix` gains `"derive-review-feasibility-fixtures"` after
`"context-map-lint"` and `"replay-retained"` after `"promotion"`, keeping the
list sorted. The generated launcher is used unchanged. Nothing else in Nix
changes: the module walk already import-checks the new modules (S12). No
CLAUDE.md edit is made (parent D16); the command table and module docstrings
are the documentation.

Source and built commands must give identical exit codes, stdout bytes and
stderr under a hostile `PYTHONPATH`, `NIX_PYTHONPATH` and working-directory
`agent_tools`. The portable cases live in `tests/test_agent_tools_launchers.py`
and need no retained input: a missing bundle, a forged bundle whose digest is
coherent, and an existing output directory that must stay untouched.

### Full-shape tier

```just
agent-retained-tests root: build
```

The recipe resolves the single built `home-manager-files` output as
`agent-installed-skill-tests` does, sets `AGENT_RETAINED_ROOT={{root}}`,
`AGENT_SKILLS_INSTALLED_HOME` and `PYTHONPATH`, runs
`tests/test_review_retained_full.py` and `tests/test_agent_tools_launchers.py`,
and fails when unittest reports any skip (RP10). It is not listed in
`agent-workflow-tests`. Parent plan Task 8's invariants bind: the archive at
`<root>/.superpowers/review-evidence/100/direct-100-000002/source-integration-a7b7c6f`,
both issue repositories at `<root>`, the tool repository at the recipe checkout,
`AGENT_RETAINED_TOOL_COMMIT` else `HEAD` with equal `python` trees (parent D17),
and the pinned-renderer staging rules (parent D10).

Outside the recipe both retained classes skip. Inside it, a missing commit or
archive file fails. The five checks:

1. **I1.** In a disposable `git clone --shared --no-checkout` of the root, the
   clean control yields exactly 30 edges. With a clone-local `info/grafts`,
   `contribution_edges`, `reconstruct_boundary` with selector `tasks-1` given
   the rehashed 31-edge table, and the derive command all refuse; the command
   exits 2 with empty stdout and no output directory.
2. **Renderer.** The pinned adopt tool runs `plan` then `apply` in a disposable
   clone with an ephemeral SSH key; every record of its commit, measured with
   `actual_inputs_from_trees`, is at most its row bound. `verify --register` is
   never run.
3. **Domains.** Archive and fresh issue-100 domains are exactly 1,005,707 B /
   115 records and 1,012,913 B / 115 records, distinct, and a label swap fails.
4. **Substitution.** Over the real bundle, per RP7: each component,
   record-digest and reference substitution with every in-bundle hash
   recomputed is refused under the trusted digest; each Git-free-determined one
   is also refused by `validate_bundle` under trust injection; a malformed
   issue-100 or estimate payload beside a valid issue-121 refusal is invalid.
5. **Leaks.** No output holds a shard body line, a scratch or home path, key
   material or policy file text.

It also derives twice with identical bytes, replays a copied bundle with the
sources unreachable (scratch `cwd` and `HOME`, neither `git` nor `artifact-budget` on `PATH`)
and asserts the exit contract for whatever outcomes the proof produced, never a
named status. `RetainedLauncherTest` repeats derive and replay through the built
launchers under the hostile channels and requires identical bytes and outcomes; the built derive finds the built tree's `artifact-budget` on `PATH`, as the module's existing dependency environment arranges.

Every mutation happens in a disposable clone or a copied bundle. The root's
refs, index digest, `info/grafts`, `shallow`, `objects` listing and archive
bytes are compared before and after each test (RP11).

### Measured payload sizes and EVIDENCE

Derived read-only from the real objects on 2026-10-04 with the published
modules: `task7-estimate.json` 43,757 B, `issue-121.json` 211,097 B and
`issue-100-derived.json` 341,492 B (its 543 edge records alone are 234,333 B).

EVIDENCE must commit each file as one whole review record under CORE's
unchanged 65,536 B member cap and 524,288 B aggregate (parent D18's grounding).
Two payloads exceed the member cap and the three together exceed the aggregate.
**EVIDENCE cannot commit the bundle these encodings produce.** Parent D18
compacted the estimate for the same reason; nobody measured the other two.

This child does not re-encode them (RP13). It satisfies its own six criteria
with the real sizes, keeps its new code independent of row encodings (only
`review_witness`'s table-name constant and the result's summary keys read
payload members), and reports the measurement so that a third DERIVE child can
own compact encodings before EVIDENCE starts. That child changes `python/`, so
it repeats G2 and re-pins the tool commit. `MEMBER_MAX_BYTES` (1,048,576) and
`ANCHOR_MAX_BYTES` (32,768, about twice the expected real anchor; the
implementer confirms it) are decode-safety bounds, not review limits.

### Review-feasibility headroom

CORE's projector adds every reserved subject of an unfinished task, and the
process reserve while any task is unfinished, **on top of** the commits already
in the range. Each reserved subject byte costs six root bytes. SOURCE renewed G0
at `--completed-through 0` throughout, so its final projection charged all
reserves plus 28 real commits: root 16,359 of 16,384 B. The same head projected
at `--completed-through 3` measures root 4,187 B and total 307,928 B, exactly
its actual gate. The ceiling was the projection mode, not the delivery.

Synthetic committed plans of this child's shape, projected by CORE at this base
(each run twice, byte-identical, `validate-result` exit 0):

| Shape | file_count | largest | root | total |
|---|---|---|---|---|
| Six tasks; process 109,056 B; product 216,576 B; 2 subjects per task + 10 | 6 | 63,488 | 10,753 | 314,369 |
| Stress: process ×1.4, product ×1.25, 3 subjects per task + 14 | 9 | 61,209 | 15,446 | 411,320 |

The stress shape uses all eight payloads, so member count is the binding
dimension here, then root. The strategy (RP14):

- **Advance the projection.** G0 runs at `--completed-through 0` before product
  work. After task N is accepted and its ranges are recorded, every renewed G0
  runs at `--completed-through N`, as CORE's own plan did. A finished task then
  costs its actual records and subjects, not its reserve. At the last task the
  projection equals the actual gate, so final-review and PR-review fixes need no
  reserve.
- **Subjects.** At most 64 bytes, two per task (implementation and one fix) and
  ten for process, checked by byte length before each commit. A second fix
  round takes one ruling that adds one subject.
- **Bounded files.** No new module above 20,480 B, no new test module above
  20,480 B except the full-shape module (36,864 B), so three records share a
  payload. Each forecast bound carries its D15 price plus about ten percent, and
  one revision per file is expected, not exceptional.
- **Compact process.** The spec's record is bounded at 45,056 B (it measures about 37 KB as written, 8 KB above the first table row's input, with room for ledger rows), the plan root under
  16,384 B and each member under 12,288 B. Rulings append ledger rows; they do
  not restate members.
- **Not done:** the declined rows above, any refactor of a SOURCE module beyond
  the three corrections, payload re-encoding (RP13) and any CLAUDE.md edit.

These are projections of forecasts. The committed plan's own G0 decides.

### Delivery gates

- **G0, projection.** Published CORE's `review-feasibility project` over the
  whole committed plan (`derived_from: null`), in the matching source gate
  environment, then `validate-result` and an independent second run that must
  reproduce every field. Exit 0 within budget clears it. Exit 2 or 3 stops with
  no bootstrap; exit 3 stops for decomposition. Any plan, spec or forecast
  change renews it, per RP14.
- **G1, actual.** The complete fixed-base `review-package` after every task and
  fix and at the final head, validated and independently checked, with equal
  metrics.
- **G2, source pin.** After the replay task, when `python/` is complete: an
  independent review of the complete `python/` source at a pinned commit,
  SOURCE's modules included, plus a fresh adversarial reviewer who repeats the
  graft and rehash reproduction in disposable clones against the library entry
  points and the source derive command. That commit is the `--tool-commit` of
  every authoritative full-shape run. Later tasks change no `python/` byte; any
  later `python/` change repeats G2 and G0.
- **G3, final.** Focused tests, full `just agent-workflow-tests`, `just build`,
  `just agent-installed-skill-tests` and
  `just agent-retained-tests /Users/anis/tmp/nix-config` with the G2 pin, no
  skip counted as a pass, then separate authorship-independent conformance and
  correctness reviews. Required CI stays the merge gate. Nothing is activated.

G2 and G3 retained runs are quiescent: nothing commits in this repository
family while they run, and a differing root snapshot voids the run (RP11).

## Test seams

The existing seams, and no others: modules imported under the recipe's
`PYTHONPATH`; commands as `python -m agent_tools.<module>`; temporary real Git
repositories and ephemeral keys through `tests/retained_review_test_support.py`,
which gains bundle fixtures that return plain paths and pins; `source_budget_env`
for the budget authority; `tests/test_agent_tools_launchers.py` as the only
module that touches built launchers. Portable suites
(`test_review_witness`, `test_review_derivation`, `test_review_replay`) are
listed in `agent-workflow-tests` and fail at base.

| Acceptance criterion | Spec section | Portable evidence | Full-shape or installed evidence |
|---|---|---|---|
| Derivation | Derivation and its command | A missing option is `usage`. Existing, dangling-symlink, input-equal, input-nested and Git-directory output paths refuse and leave nothing. A failing pin leaves no output and no scratch. Full snapshots of every input repository and the archive are equal after success and after each failure. The summary is canonical. Two runs are byte-identical and no output holds a scratch or home path. | Two real derivations are byte-identical; the root is unchanged. |
| Anchor and witness | Tool closure; Witness and anchor | CORE's real `_derivation` accepts a committed bundle. The witness has exactly its six keys and no anchor identity. A changed, extra or missing running file is `tool_closure`. The closure is sorted and complete. | The real anchor is under `ANCHOR_MAX_BYTES`; a dirty or mismatched `python` tree refuses. |
| Replay ordering and exits | Replay and its command | Member bytes are bound before decode (a non-JSON member is `member_digest`, not a decode error). A replacement anchor fails the unchanged digest. Missing, extra and symlinked members fail. An oversized anchor fails before decode. From a valid unavailable control, a malformed issue-100 or estimate sibling with coherent digests is invalid. Ids follow outcome order. An over-budget measured fixture exits 0 with the v3 result. The command emits exactly one stderr line and empty stdout on exit 2. | Replay with sources unreachable and a `PATH` that holds neither `git` nor `artifact-budget`; substitution check 4. |
| Built parity | Publication | — | `just agent-installed-skill-tests`: floor rows, portable parity under hostile channels. `RetainedLauncherTest`: real derive and replay parity. |
| Full-shape tier | Full-shape tier | Outside the recipe the classes skip, which is never acceptance. | The five checks; a missing input fails; the recipe fails on any skip. |
| Delivery gates | Review-feasibility headroom; Delivery gates | G0 and G1 results and the G2 evidence live in the SDD workspace. | G3 runs at the final head with the G2 pin. |
| Inherited corrections | Inherited SOURCE corrections | A tab-bearing path composes. A malformed digest pin is `invalid_pins`. Pins whose last assignment is not the head are `assignment_mismatch`. | The real payloads derive and validate through the corrected modules. |

## Out of scope

EVIDENCE owns committing the five outputs, the published trust identity and the
committed-bundle regressions. A separate DERIVE child owns compact payload
encodings (RP13). Also out of scope: any CLAUDE.md edit, host activation,
caller adoption, lifecycle rollout, executing Task 7 or 8, registration,
changed caps, split records, expanded generated exemptions and fitted results.

Nothing writes the retained root, its object store, the archive, parent
evidence or lifecycle state, and no ref is added to protect the unreferenced
issue-121 objects: an absent object fails closed.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| RP1 | Six tasks: inherited SOURCE corrections first, then parent Tasks 4–8. Three corrections are made (numstat split, digest-pin hex check, head-bound assignments); readability, structure and DRY-only findings are declined | Issue 249 ("fixed here and re-reviewed"); brief default (fix cheap correctness, decline readability that threatens the budget); G2 pins corrected bytes | Folding the corrections into the derivation task (hides them in a larger review); refactoring two 30 KB modules (large modify records that G2 re-reviews, for no behaviour change) |
| RP2 | `validate_bundle` lives in `review_witness` and is the single full semantic validation; derivation calls it before publishing and replay calls it before classifying. `review_replay` only classifies. Refines parent plan Task 6, which placed it in replay | Parent D11 (derivation runs the same validators); the-bar DRY (one home for "what a valid bundle is"); derivation precedes replay in task order | Two compositions of the validators, one per module: a bundle derivation accepts and replay refuses |
| RP3 | Components are five groups computed once and embedded identically in witness and anchor, including the full tool file list. `tables` is driven by one table-name constant | Parent § Bundle ("components equal the anchor's"; the tool component binds the sorted closure); measured closure of about 55 files, about 11 KB per copy | A closure digest in the anchor with the list only in the witness: the components would differ, and the loader-facing anchor would not carry the reviewed identities |
| RP4 | `derive_100` receives the `--issue-100-repo` path as both issue and live repository | Parent § Commands (six explicit inputs); S11 (no hidden input); the live commit is in the same store | Using `--tool-repo` as the live repository: couples evidence to the tool checkout. A seventh option: contradicts the acceptance criterion |
| RP5 | Derivation derives the estimate table first and any `EstimateError` is fatal, so a bundle always holds a valid table and `validate_121` always receives one | The bundle's four fixed payload names (parent D3); inherited Minor on `derive_121`'s table-failure route | Emitting a bundle without an estimate file, or a placeholder table: breaks CORE's loader or fabricates evidence |
| RP6 | Derivation takes no runtime before/after snapshot. Input immutability is a property proved by tests on quiescent disposable inputs. Refines parent plan Task 5's `input_mutated` check | Every input fact is content-addressed or digest-pinned and CORE's guard refuses virtualization, so no mutation can change an output undetected; the real root is a live multi-worktree store (248's G2 false difference) | Hashing the whole checkout twice per run: slow, and spuriously fails whenever another worktree commits |
| RP7 | Substitution refusal has two layers. Under the trusted digest, any change, however rehashed, is `anchor_digest` or `member_digest`. Under test-only trust injection, `validate_bundle` refuses every substitution the pins and cross-table closure determine. `tool.commit` and re-measured record bytes or digests are not Git-free-determinable and are refused by the first layer and by re-derivation only. Refines parent plan Task 8's "replay against the new digest" | Parent D6 (trust is the caller's digest); S6 (Git-free validators rebuild, derivation authenticates); inherited Minors on rehashed record facts | Claiming a Git-free refusal for record re-measurement: untestable and false. Pinning output digests in the tool: a fitted result |
| RP8 | Replay does not verify its own running closure against the anchor's tool group, and neither command catches unexpected exceptions | Parent § Bundle (the closure check binds derivation); the-bar *Root causes* and *Fail loud*; S3 | A replay-time closure check (no later tool could replay committed evidence); a catch-all mapped to `invalid` (mutes defects) |
| RP9 | `--output-dir` must not exist and must not alias any input path or input Git directory; publication is one rename of a sibling scratch directory. A same-user race on the path is out of the threat model | Issue 249 Derivation criterion; parent plan Task 5 | Exclusive `mkdir` plus per-file moves: more states to clean up for no accepted threat |
| RP10 | The retained recipe fails when unittest reports any skip; retained classes skip only when `AGENT_RETAINED_ROOT` is unset | Issue 249 ("a missing input fails rather than skips"); parent D8/D14; the launcher module has only its class-level skip | Trusting reviewers to read the skip count: 248's suite passed with three skips reported |
| RP11 | Retained runs compare the root strictly and must be quiescent; a differing root voids the run and it is repeated. The committed I1 case uses selector `tasks-1` | Inherited conformance Minor on 248's G2; issue 249 demo | Tolerating added objects or moved refs: no way to attribute them to another actor |
| RP12 | Bundle fixtures in the support module return plain paths and pins and import no REPLAY module | Inherited Minor (support imports couple suites); agent-helper standard 5 | Returning `DeriveInputs` from support: every retained suite would import the derivation module |
| RP13 | This child keeps SOURCE's payload encodings and reports that two real payloads exceed the member cap EVIDENCE must commit under. Compact encodings are a separate DERIVE child before EVIDENCE | Measured 211,097 B and 341,492 B against 65,536 B; parent D18; EVIDENCE 235 (source defects are fixed in the owning dependency); the design skill's rule that a scope expansion returns to the caller; the stress projection already uses eight of eight payloads | Re-encoding both schemas, validators and suites here: a second SOURCE-sized change in a boundary with no spare payload. Raising caps or splitting files: forbidden by parent D3 and the unchanged caps |
| RP14 | Renewed G0 runs at `--completed-through N` once task N is accepted; reserves stay two per task plus ten for process at 64 bytes; modules and members are size-bounded as above | Measured: 248's head projects root 16,359 B at 0 and 4,187 B at 3; CORE plan precedent (`--completed-through 1`, then 2); `review_projection._project_input`; issue 249 (reserves) | Renewing at 0 throughout (charges finished work twice and strands the delivery); raising reserves pre-emptively (each 64-byte subject costs about 447 root bytes) |
| RP15 | Task 1's corrections refuse two cases the published suites did not expect. A `None` digest pin is `invalid_pins`, so 248's `test_none_digest_pin_never_switches_the_digest_check_off`, which asserted `archive_digest_mismatch`, is replaced by one malformed-pin test per digest. An empty assignment list is `assignment_mismatch` | Measured at planning: with the three edits applied, that test is the only one of SOURCE's 62 cases to fail; the hex check precedes every archive read; an empty list has no last assignment to bind to the head | Exempting `None` from the hex check: keeps a sentinel path through the pin the correction closes |
| RP16 | Component values: a closure `path` is relative to `python/agent_tools/`; closure, fixture and member `raw_sha256` are bare 64-hex and `signer_sha256` is CORE's `raw_digest` form; `issue_121.tree` is `task7_pins.prerequisite_tree`; derivation assembles the groups privately and `validate_bundle` is the only shape authority. Git-free, `tool.commit`, `tool.files` and `archive.shards` are checked for closed shape only | RP2, RP3, RP7; `review_forecast._derivation` requires bare member digests; `derive_task7` authenticates that tree and `review_issue121._context` binds it to the pinned head; `verify_archive`'s result is embedded unchanged | A public components builder in `review_witness` (widens the closed surface); a second Git read for the head tree in derivation (a failure path outside the closed codes) |
| RP17 | The replay command's exit-0 and `projection_unavailable` mappings are tested in process by calling `main` with the module's three pin names patched to fixture pins; subprocess tests cover the real-pin refusals. `member_oversize` is tested by patching the derivation module's `MEMBER_MAX_BYTES` name | Both commands pass only real pins (parent D12), so no portable bundle reaches those two exits through a subprocess and the full-shape proof exercises only one of them; a 1 MiB fixture would exceed every test-record bound | A pin option or environment override (a test channel in the shipped command, rejected by parent D12); leaving an exit mapping untested |
| RP18 | Refines RP14's member bound: each plan member has its own forecast record, sized from its measured bytes plus about twelve percent, instead of one 12,288 B ceiling; the plan root's record is bounded at 17,408 B | The plan skill requires each task's failing tests and wire-contract helpers in full; the committed plan's G0 clears with these bounds (figures in the plan's *Execution gates*) | Cutting test code from members to meet 12,288 B: each implementer would re-derive the bundle assembly that the tests pin |
| RP19 | Witness refusals the spec left open: a witness whose `fixtures` differ from the payloads is `witness_shape`; witness `tables` follow fixture path order; a malformed `tool.artifact_policy_sha256` is `component_mismatch` | Task 2 review; each is the nearest closed code and the order is the one `build_witness` already emits | New codes for each case: the closed set is the spec's, and no consumer distinguishes them |
| RP20 | In `authenticate`, any `OSError` while reading the anchor (missing directory, missing or symlinked anchor) is `anchor_unreadable`, and an anchor nested too deeply to decode is `anchor_shape`. A payload member that deep still propagates as an unexpected exception (RP8) | Replay step 1 names `anchor_unreadable` for the read; Task 5's parity case expects it for a missing directory | Leaving the bare `OSError` to the shell's `io_error`: source and built would then disagree with step 1 |
| RP21 | Derivation refuses an anchor above `ANCHOR_MAX_BYTES` as `member_oversize` before publishing. Output aliasing stays a resolved-path comparison, and a missing `git` stays `invalid_inputs` | Task 3 review: a larger anchor would publish and then never replay; the anchor is a bundle member, so the existing code fits | A new code, or device-and-inode aliasing checks: the plan fixes both mechanisms and neither gap overwrites anything |

Design and grill frontier: closed within the approved scope. The resolved
bindings carry no context-map or ADR route, so this ledger is the issue's
decision store.
