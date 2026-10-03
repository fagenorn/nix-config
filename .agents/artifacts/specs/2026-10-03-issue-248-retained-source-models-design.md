# Issue 248 — retained source models (DP234-SOURCE)

## Problem

Parent [234](https://github.com/fagenorn/nix-config/issues/234) (DERIVE) needs
authenticated, checkable answers about two retained deliveries, issue 121 and
issue 100, plus an honest estimate of issue 121's unexecuted Task 7. DERIVE's
single boundary stopped at G0 with exit 3 after its Task 1. The
[decomposition](https://github.com/fagenorn/nix-config/blob/6e5224edcdd6477fbde42439f01c2ffaf211ac91/.agents/artifacts/specs/2026-10-03-issue-234-derive-decomposition-design.md)
splits it by command publication. This child, `DP234-SOURCE` / slug
`retained-source-models`, delivers the library half: three models in
`agent_tools`, each with a `derive_*`/`validate_*` pair and a portable real-Git
test tier. The sibling REPLAY child turns them into commands.

Three defects make the parent's Task-1 and recovery inputs unusable as they are:

- **I1.** A clone-local graft adds a redundant parent while the raw objects,
  signatures and the 30-commit range stay the same. The recovered adapter then
  accepts 31 edges, and the fixed-selector `tasks-1` path accepts a rehashed
  forged table as valid unavailable evidence.
- **N1.** `validate_task7` raises a raw `TypeError` on an unhashable `operation`
  rather than `invalid_table`.
- **N2.** Overlapping move-root new prefixes make derive and validate disagree.

The parent's review also deferred minors M2, M4, M5 and M6.

Immutable `DELIVERY_BASE`: `5f865639eb669ac80ea66c50c9a20a0636fa1dde`. That is
integration with published CORE ([233](https://github.com/fagenorn/nix-config/issues/233))
and nothing of DERIVE. Every complete gate covers every process and product
commit after it. Parents 234 and 226 stay open.

## Binding parent design

The [DERIVE design at `6e5224e`](https://github.com/fagenorn/nix-config/blob/6e5224edcdd6477fbde42439f01c2ffaf211ac91/.agents/artifacts/specs/2026-10-03-issue-234-retained-review-derivation-design.md)
("parent spec") binds this child for:

- the sections *Issue-121 adapter and the ancestry fix*, *Historical outcomes*,
  *Task-7 table and Task-8 effect* and *Issue-100 payload and byte domains*;
- its rows D2, D4, D5, D11, D12, D15, D17 and D18;
- the recovery rows R1 and R3, and the SOURCE part of R4.

This spec does not restate those contracts. It records only what this child
adds, narrows or fixes, and a row here wins over the parent only where it says
"refines parent Dn". Rows prefixed `S` are this issue's decisions. `parent Dn`
cites the parent ledger.

## Solution

Three domain modules on CORE's published primitives (parent D1/D11), plus their
tests:

| Module | Model | Entry points |
|---|---|---|
| `review_task7` | `task7-estimate/v1` (173 rows, compact encoding per parent D18) and the fileless Task-8 effect | `derive_task7`, `validate_task7`, `compose`, `TASK8_EFFECT`, `TASK7_PINS` |
| `review_issue121` | The 30 assignments, the plan anchors, the ordered raw edges, three historical outcomes and the aggregate | `classify`, `contribution_edges`, `plan_anchors`, `reconstruct_boundary`, `derive_121`, `validate_121`, `unavailable_ids`, `ISSUE_121_PINS` |
| `review_issue100` | 543 edge records, 115 contributions, pending overlaps, criteria and the two byte domains | `verify_archive`, `historical_records`, `fresh_records`, `derive_100`, `validate_100`, `ISSUE_100_PINS` |

The interface signatures, pin records and error classes are the ones the parent
plan's Tasks 1–3 already fixed (parent D12): `Task7Pins`, `Issue121Pins`,
`Issue100Pins`, `Domain`, `EstimateError`, `ContributionError` and
`Issue100Error`. This child's plan carries them forward unchanged except where a
row below says otherwise.

Everything else stays out of this child: the command-table rows, both commands,
the witness and anchor, derivation's bundle writer, the full-shape tier and the
`agent-retained-tests` recipe all belong to REPLAY (S1).

### Recovery manifest

Each task report names the rows it consumes and every effect it deliberately
leaves out. Sources are recovery input only: their commits, signatures, tests
and reviews accept nothing here, and every recovered byte gets a fresh review
in this child's range.

| ID | Source | Recover into | Disposition |
|---|---|---|---|
| S-R1 | `92a0c79c` blobs: `review_task7.py` `fc721644`, `tests/retained_review_test_support.py` `15e28b21` and `tests/test_review_task7.py` `b49b3af9`, plus the one `agent-workflow-tests` line and the two `LEGACY_MIGRATION_INPUTS` allowances | Task 1 | Restore the blobs, then fix N1, N2, M2, M5 and M6 and disposition M4 (S3–S6). Remove the conditionally skipping real-table test (S7). Land it as one implementation commit; the task report carries the diff from the recovered blobs (S8). |
| parent R1 | `35e6fd7a` `review_contributions.py` + test | Task 2 | Fixed assignments, the plan-anchor check, the selector and prerequisite fact shapes, and the `reconstruct_boundary`/`derive_121` structure. Re-author it as `review_issue121`. Drop its `rev-list --parents`/`--topo-order` enumeration and its ancestry check (parent D2). |
| parent R3 | `55cef035`, deriver blob `913ab952` | Task 3 | The issue-100 constants, `PROCESS_PATHS`, `PENDING_PATHS`, the criteria, the producer and manifest digests and the archive-envelope check. Replace its `rev-list` range with `original_range`, and its `nofollow` reads with `read_regular`. Drop the pathname-multiplier projections and the hard-coded boundary expectations (rejected I2). |
| parent R4 (SOURCE part) | Newly authored | Tasks 1–3 | The raw-parent edge fix in both entry points, the Task-7 fixes, and the portable fixtures for issue 121 and issue 100. |

## Decisions

### Task-7 model (Task 1)

The parent's contracts hold: the counts 173/165/54/108/3/5/3, the R100 move
bound with maximization across compatible sources, the renderer-spec write and
add bounds, the `authored-estimate` project identity, the closed composition
rule, `observed_actual: null` and `TASK8_EFFECT`. This task changes four things.

**N1, closed input shapes (S3).** `validate_task7` type-checks every row member
before it uses that member as a key, an index or a set member. `operation` must
be a `str` in the closed rule set, and `new_path` must be a `str`. `input` must
match the closed `{blob, mode, bytes, lines}` shape with hex identities of the
pinned length. Every malformed value raises `EstimateError("invalid_table")`.

The validator is a pure function of JSON-shaped data. It never catches broad
exceptions to translate them (the-bar *Root causes*), so a raw `TypeError`,
`KeyError` or `AttributeError` that escapes is a defect. The test proves this
with a mutation matrix: every row member and every top-level member is replaced
by each JSON kind (object, array, string, integer, Boolean, null), and also
removed. Each case must raise `EstimateError` with code `invalid_table`.

**N2, one move-root resolver (S4).** `_pins` refuses any root set in which two
old prefixes, or two new prefixes, are equal, or where one is a path prefix of
the other (`a` vs `a/b`). Such a set raises `unsupported_estimate`. One resolver
then maps old to new and new to old, and both derive and validate use it, so
they cannot disagree. The real roots (`.claude/specs`, `.claude/plans` and
`.out-of-scope`, mapping to `.agents/artifacts/...` and
`.agents/knowledge/rejections`) do not overlap, so the real table is unchanged.

**Sound records (S5).** Two fixes:

- **M2.** `compose` takes added and deleted line counts from a `--numstat -z`
  diff of the same scratch trees. Payload parsing undercounts here, because a
  generated-evidence record's payload is a summary, which yields zero lines. A
  numstat row must exist for every measured record, and a missing row raises
  `unsupported_composition`. A binary row (`-`) counts zero lines, which is
  CORE's numstat convention.
- **M5.** The full delete/add write bound becomes an upper bound for any hunking
  Git chooses, at every context the packing policy admits. CORE's
  `review_actual` packing policy is the source of those contexts, and they are
  read, never copied. CORE generates records under `--inter-hunk-context=0`. At
  context `c`, two hunks stay separate only across more than `2c` unchanged
  lines, so the number of hunks for an `L`-line input is bounded by `L` and `c`.
  The bound adds, for the worst admitted context, every extra hunk's maximal
  header beyond what its omitted lines save. The maximal header includes Git's
  truncated function-context text. The formula and that header maximum are named
  module constants, with their derivation in a docstring.

  This refines parent D4's write bound. It only ever raises a bound, so it can
  never undercharge. The real table stays under the 49,152 B ceiling (S7
  measures it).

**M4 and M6, the validation contract (S6).** `validate_task7` stays Git-free.
It proves that a table is the exact rebuild from its own input facts plus the
pins. It cannot prove that those facts are the pinned tree's facts.
Authenticity is `derive_task7` equality against the pinned tree. REPLAY's
derivation runs that equality before it writes the anchor, and replay trusts
facts only through the anchor digest (parent D6/D11). The module docstring says
so; that is the M4 disposition. For M6, every `compose` refusal and rule branch
gets a named case:

- a rename into or out of a target;
- a non-blob or unknown status;
- a move that exceeds its R100 bound over the pinned base;
- the write larger-wins rule;
- moves over a foreign final tree.

Each case asserts that the source `snapshot` is unchanged.

### Issue-121 adapter (Task 2)

Parent § *Issue-121 adapter and the ancestry fix*, § *Historical outcomes*, D2,
D5 and D17 bind this task in full.

**I1 in both entry points.** The shared raw edge path is the only edge source.
`derive_121` and `reconstruct_boundary` both call `contribution_edges`, which
reads `original_range` order and `original_commit(...).parents`. It requires one
raw parent per commit, equal to the preceding member, or to the base for the
first commit. The selector then compares the caller's table against its own
recomputation canonically.

Every `HistoryError` or `ForecastError` reaching either entry point is re-raised
as `ContributionError("history_unauthenticated")`, with the original as
`__cause__` (S9). That holds even when it happens inside a reconstruction that
would otherwise produce a `projection_unavailable` row: a history-authority
failure is never an outcome. CORE's `ReconstructionUnavailable` (a
`ForecastError` subclass) is the one exception. It is caught first, by type, and
remains the authenticated unavailable route.

**Outcomes are measured or explained, never asserted.** The adapter records
`aggregate.actual`, `aggregate.projected`, `tasks-1-3`, `tasks-4-6` and
`tasks-7-8` with the closed fields of the parent spec. Neither the source nor
the tests name an expected status for a real boundary.

The portable tests do assert per-fixture statuses. Each fixture is built to
force one route: a late fix that touches a path of an excluded task, a
prerequisite with no matching closure, and a future-only boundary. Those
statuses are facts of the fixture, not of the retained history.

### Issue-100 verifier (Task 3)

Parent § *Issue-100 payload and byte domains* binds this task.

**The counts are precise.** R3 and the parent spec use "543 history edges".
That is 543 per-path edge records (`edge_facts` rows) over the 82 range commits
and their 91 raw parent edges, 9 of which come from merges. Every parent ordinal
is included. The payload keeps both levels:

- the raw parent edge list, from `original_commit` parents in `original_range`
  order;
- the records under each edge.

`validate_100` recomputes 82/91/9/543 from the tables, never from constants
alone (S10).

**Two domains, two policies.** The payload has two tables:

- `historical` is `retained-git-records/v1`, produced by the fixed recipe
  replayed from the R3 argv and config. It must reproduce the archive shards
  byte for byte.
- `fresh` is `review-git-records/v1`, produced by `actual_inputs_from_trees`
  with `RECORD_POLICY`.

Each table carries `record_table_policy {domain, policy_sha256}`. A domain must
carry its own policy digest, so swapping labels or digests is invalid. No
function measures the historical domain as a review package, and historical
bytes never bound fresh ones.

**Archive reads come before decode.** The producer, the manifest and each
ordered shard are read with `read_regular`, which does not follow symlinks and
takes an explicit byte limit. Their raw SHA-256 values must match the pins
before any strict JSON decode. The archive directory is an explicit argument,
never derived from a repository path (S11).

### Package standards and verification

- **No new history reads.** No retained module calls `git rev-list`, `git log`
  or `rev-parse <commit>^{tree}` for parents, membership, order or trees. Each
  task's verification includes a failing-capable `rg` check over its module.
  Git is otherwise run by name only for blob and tree reads, the fixed issue-100
  recipe, the scratch index work in `compose`, and `verify-commit` under an
  isolated signers file.
- **Agent-helper standards 1–5.** These apply as written. Digests use
  `telemetry_digest` or CORE's `canonical_bytes`. Nothing loads modules
  dynamically, edits `sys.path` or uses `__file__` inside the package.
- **The build covers new modules automatically.** `lib/agent-tools.nix` derives
  `pythonImportsCheck` by walking the package tree, so `just build` import-checks
  every new module with no Nix edit (S12). The plan verifies this with
  `just build` after Task 1. It does not add a module list.
- **Whole-record sizing.** Every changed file stays one whole review record. The
  plan prices each forecast from the recovered blob measurements plus the fix
  delta, per parent D15 (S13).

### Delivery gate

This child authors its own process package: this spec, an indexed v3 plan with
`derived_from: null`, task members, honest forecasts and subject reserves of two
per task plus sixteen for process (S20, S23), three for Task 2 (S22) and four for Task 3 (S23). Before any product work, published CORE's
`review-feasibility project` runs with the matching reviewed source closure over
the whole committed plan. Exit 0 within budget clears G0. Exit 2 or 3 stops the
child with no bootstrap; exit 3 stops for decomposition. Any change to the plan
or the forecasts requires a renewed projection. The parent's base, branch,
G0 runs and checkpoint are never reused as this child's.

The complete fixed-base actual gate runs after every task and fix, and at the
final head.

The final gates are:

- the focused tests;
- the full `agent-workflow-tests`;
- `just build`;
- separate authorship-independent conformance and correctness reviews;
- the real-object proof (S7).

The real-object proof runs only in disposable clones whose `objects/info/alternates`
names the primary store read-only. Grafts and replace refs are written only in
those clones. The primary checkout's refs, index and objects and the issue-100
archive must be byte-identical before and after.

## Test seams

These are the existing seams, and no others:

- Modules are imported normally under the recipe's `PYTHONPATH`.
- Fixtures are temporary real Git repositories and ephemeral SSH keys, built
  through the one shared `tests/retained_review_test_support.py` (parent D12).
  Like `tests/test_review_feasibility.py`, it locates the source checkout from
  its own file, which only tests may do.
- `source_budget_env` stages the source budget helper for
  `describe("review-package")`.

`tests/test_review_task7.py`, `tests/test_review_issue121.py` and
`tests/test_review_issue100.py` are listed in `agent-workflow-tests`. Each one
fails at base, because its module does not exist there.

| Contract | Portable evidence |
|---|---|
| Task-7 table | Exact fixture counts and unique mappings. A removed variable bound gives `unsupported_estimate`. A rehashed fact, renderer, blob or digest change is invalid. Real producer records stay within row bounds under the hostile rename, quoting and rename-limit environment, for every operation shape, including a multi-hunk write with maximal function-context headers, measured at every policy context (S5). `observed_actual` is null. Task 8 has zero bytes and is unexecuted. |
| N1 / N2 / M6 | The S3 mutation matrix: every case is `invalid_table` and none raises a raw exception. Overlapping roots give `unsupported_estimate`. There is a named case for every `compose` branch (S6). |
| I1 (both entry points) | On linear real-Git fixtures, each of these makes both `contribution_edges`/`derive_121` and `reconstruct_boundary` `tasks-1` raise `ContributionError`: a graft, a replacement ref, an alternate replace base, a shallow file, the routing variables (`GIT_DIR`, `GIT_OBJECT_DIRECTORY`, `GIT_REPLACE_REF_BASE`, `GIT_GRAFT_FILE`), and a raw parent deletion or reorder under a rehashed table. The clean control yields one ordinal-1 edge per commit. Source refs, index, objects and file contents are unchanged. |
| Assignments and anchors | Unknown, task-zero, duplicate, multiple, observed-7/8, reordered, omitted and duplicate-final-record mutations fail. A forged or wrong-key signature and a substituted plan blob fail. |
| Outcomes | Closed row shapes. An unavailable row that carries a tree, metrics or records fails. Removing or reordering an edge after the failed one fails, as do forged or removed failure references. |
| Issue 100 | On a fixture with one merge and a fixture-pinned recipe: the archive is byte-identical before and after. A symlinked, oversized or wrong-digest producer, manifest or shard is refused before decode. A domain label or policy swap is invalid. Rehashed edge-order, coverage, contribution-fact and summary changes are invalid. A missing superseded criterion and an out-of-range edge parent are invalid. |

## Out of scope

The following belong to REPLAY: command-table rows, both commands, the
witness/anchor and bundle writer, launcher tests, the committed full-shape tier
and the `agent-retained-tests` recipe. A defect REPLAY finds in these modules is
fixed and re-reviewed in REPLAY's range. EVIDENCE (235) commits the outputs and
the trust identity.

This child makes no CLAUDE.md edit (parent D16), no caps change and no
generated-exemption change. It runs no Task 7 or Task 8 and performs no
registration or activation. It never writes to retained worktrees, parent
evidence, the primary object store, the archive or lifecycle state, and it adds
no refs to protect the unreferenced issue-121 objects.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| S1 | This child ships exactly three library modules (parent D11 names) with their portable tests, the shared support module, three `agent-workflow-tests` entries and the two contracts-test allowances. It adds no command rows, commands, witness, bundle or recipe | Decomposition Q1/Q2; issue 248 scope; agent-helper standard 1 | Publishing a command early: it would need launcher and full-shape acceptance that REPLAY owns |
| S2 | This spec cites the parent spec at `6e5224e` by permalink and records only deltas (S-rows). Parent rows stay binding unless an S-row says "refines parent Dn" | The parent design is not on main; the-bar DRY (one authoritative home); design-spec budget | Copying the parent spec (two drifting homes, about 35 KB over budget) or merging it to main first (out of scope) |
| S3 | N1: closed type checks before any hash, index or membership use. There is no broad `except` translation. A JSON-kind mutation matrix over every row and top-level member proves `invalid_table` | Issue 248 acceptance (a raw TypeError fails); the-bar *Root causes*, *Fail loud* and *Tests that can fail* | Wrapping `validate_task7` in `except Exception` → `invalid_table`: it mutes real defects |
| S4 | N2: refuse equal or path-prefix-overlapping old or new prefixes as `unsupported_estimate`. One resolver serves derive and validate | Issue 248 offers "refused, or resolved identically"; refusal is smaller; the real roots are disjoint | Longest-prefix resolution: new policy the signed brief never states, and two maps to keep in sync |
| S5 | M2: line counts come from `--numstat -z` over the composed trees. M5: the write bound covers the worst hunk split at every packing-policy context, with the formula derived in the module. Refines parent D4: bounds only rise | Generated-evidence payloads are summaries; CORE packs at contexts 10 down to 0 with `--inter-hunk-context=0`, so a context-0 record can split at every unchanged line; the-bar *Root causes* (sound bound, not a test that happens to pass) | Keeping the single-hunk form and relying on `compose`'s max rule: the table row itself would still undercharge a multi-hunk write |
| S6 | M4: `validate_task7` is a Git-free rebuild check; authenticity is `derive_task7` equality, run by REPLAY's derivation and anchored for replay. M6: a named test for each `compose` branch | Parent D6/D11 (derivation runs validators, replay trusts the anchor); parent D18 (validate rebuilds from facts) | Re-reading Git in `validate_task7`: it breaks the Git-free replay contract |
| S7 | The portable tier holds no retained objects; the recovered test that skipped without `fe85677c` is removed. SOURCE's real-object proof is a final-gate step: the controller and a fresh adversarial reviewer run the library entry points on disposable alternates-backed clones of the primary store plus the explicit issue-100 archive directory. That covers the I1 graft/rehash refusals, a clean control of exactly 30 edges, the real table at 173 rows and ≤ 49,152 canonical bytes, and both issue-100 domains. They record the evidence in this child's SDD workspace. REPLAY's full-shape tier is the committed acceptance | `fe85677c` is unreferenced (not on main), so CI cannot read it; parent D8 (no silent skips; full shape is REPLAY's); decomposition Q3 | Keeping the conditional skip (the CI gate passes by skipping), or adding a retained-inputs recipe now (REPLAY's D14 scope) |
| S8 | Task 1 lands the recovered and fixed files as one implementation commit. Its report carries the diff against `fc721644`/`15e28b21`/`b49b3af9` | Decomposition Q2 (old commits are provenance only); subject reserves of two per task | A verbatim-restore commit followed by a fix commit: it spends the fix reserve before review, and the review covers whole files anyway |
| S9 | A `HistoryError` or `ForecastError` from either 121 entry point becomes `ContributionError("history_unauthenticated")`, even inside a reconstruction. Only `ReconstructionUnavailable`, caught first by type, is an unavailable outcome | Parent D2 (virtualization is invalid, never unavailable); I1's selector symptom | Catching `ForecastError` broadly in reconstruction: the subclass hierarchy would turn a graft into valid unavailable evidence |
| S10 | "543 edges" means 543 `edge_facts` records over 82 commits / 91 raw parent edges (9 merges). The payload keeps both levels, and the validator recomputes all four counts | R3 `derive_issue_100` (`len(edge_objects) != 543`, `merge_count != 9`); measured `original_range` closure | Treating 543 as commit-parent edges: it is false for the real range and unverifiable |
| S11 | `derive_100` takes the archive directory as an explicit argument. No module embeds R3's archive path relative to a checkout | Parent § Commands (explicit inputs only); the archive is ignored, machine-local state | Deriving it from the live repository path (R3's `ARCHIVE_RELATIVE`): a hidden input |
| S12 | There is no `lib/agent-tools.nix` edit: its tree walk already import-checks every new module. `just build` proves it | `lib/agent-tools.nix` derives `pythonImportsCheck` from the package tree | Adding an explicit module list: a second home for package membership |
| S13 | Forecasts start from measured recovered blobs (`review_task7.py` 26,018 B and test 20,807 B) plus each fix delta, priced per parent D15. Expected ceilings are about 30,720 B and 27,648 B, above the decomposition's 28,672/23,552 charge, and well inside its ×1.25 stress fit. G0 decides | Decomposition Q2 ("revise honestly") and the measured fit table | Holding the 28,672/23,552 charge: the N1 matrix and the M6 cases would overrun it after G0 and force a mid-delivery stop |
| S14 | Plan-level forecast and gate shape. Task 2/3 modules and tests are priced from the parent plan's D15 estimates, raised where this spec adds cases (issue-121 test 32,072 B; issue-100 module 27,012 B from R3's measured issue-100 half). The support module is re-based on its measured 5,144 B blob, growing to 20,480 B over three contributions. The evidence checkpoint is the spec commit `ccd6552`, plan commits are its process-only tail, and G0 projects at completed-through 0. `validate_task7` runs the pin checks before its table translation, so a bad pin set is `unsupported_estimate` from derive and validate alike | Parent D15; S13; the CORE and parent plans' checkpoint precedent; S4 (overlap is `unsupported_estimate`) | Copying the parent forecasts verbatim (support overcharged about 2x, issue-100 undercharged); translating pin faults into `invalid_table` (blames the table for a pin defect) |
| S15 | M5 formula: a write row adds `(HUNK_HEADER_MAX - first) + max_c (min(in, out) // (2c+1)) * max(0, HUNK_HEADER_MAX - 2(2c+1))` over the packing policy's contexts, with `HUNK_HEADER_MAX` from the line-count digit width plus Git's 80-byte function-context truncation. Each split needs more than `2c` unchanged lines, and each such line saves at least 2 bytes against the full delete/add. Adds and moves are unchanged. Refines S5 | S5; RECORD_POLICY `--inter-hunk-context=0`; xdiff `struct func_line` | Ignoring the savings credit (a looser bound than S5 states), or applying it to adds (an add is always one hunk at line 1, with no function context) |
| S16 | The issue-121 payload gains `records`, a final-record table. Closed `actual` rows (one whole initial-context record per measured outcome, with ordered edge lineage) and `estimate` rows (`compose` rows, Task-7 table bounds), keyed by `scope` = outcome label and `path`, with telemetry-digest ids. `record_refs` list exactly their scope's rows, so each record resolves once. `estimate_refs` is the table digest for the two table-consuming outcomes. Task 2's module and test forecasts rise to 31,602 B and 33,502 B (revises S14's 32,072 B test price) | Codex plan review B1: `record_refs` had no target, and parent-edge records cannot hold cumulative or composed finals. Parent § *Historical outcomes* ("every reference resolves exactly once"); R1 `_record_facts` (per-outcome final records with edge lineage) | Referencing edge records directly: a final record after several edges or a composition has no single edge. A table per outcome would put the records in five homes, so uniqueness could not be checked in one place |
| S17 | Fixtures force the routes they assert. The generated-evidence case oversizes its designer above `member_max_bytes`, and lines come from the file. The missing-prerequisite case interleaves owners `(1, 2, 4, 3, 5, 6)`. The late-fix case asserts all four selected edges. `task7_fixture(repo, pins)` pins the Task-7 prerequisite at the linear fixture's own head, where a seed provides the Task-7 inventory, and a clean `derive_121` payload must validate before any mutation. The support ceiling becomes 21,504 B (revises S14's 20,480 B) | Codex plan review B2, B3 and S1, verified: CORE `review_actual.actual_inputs_from_trees` calls `_ef_designer_evidence` only above `limits.member_max_bytes`; `(1, 2, 3, 6, 3)` owns four Task 1–3 commits; the default owners close tasks 1–3 before Task 4; parent § *Historical outcomes* (tasks-7-8's prerequisite has product closure 1–6) | Reviewer's fixture corrections accepted as-is. Importing Task 1's `fixture_pins` was rejected because it builds its own repository, which is the incoherence S1 names |
| S18 | Task-1 G0 revision. `validate_task7` refuses an input `mode` outside the Git blob modes `100644`/`100755`/`120000` as `invalid_table`. The malformed-member matrix forges a move row's `bytes`/`lines` only with non-integer kinds, because no rebuilt member depends on them and a Git-free validator cannot see a well-typed change there; `derive_task7` equality authenticates them (M4). The test bound rises to 31,744 B / +560 after the briefed tests measured 28,478 B / +466, and G0 is renewed | Task-1 implementer measurement against S13's bound; M4's Git-free contract | Narrowing move inputs to `{blob, mode}`: it changes the parent D18 row shape. Truncating tests or keeping the bound: the plan forbids both |
| S19 | M5 also covers `compose`'s own write bound: when the base tree holds a target, its measured removal plus `_record` add gains the S15 allowance computed from the removed and output line counts. The `review_task7.py` bound rises to 32,768 B / +600, and G0 is renewed | Task-1 review: a 40-hunk write measured 22,874 B against a 20,879 B `compose` bound, and Task 2 consumes `compose` rows (S16) | Limiting M5 to table rows: `compose` would emit an unsound bound that Task 2 builds on |
| S20 | Task-2 G0 revision. The `review_issue121.py` bound rises to 37,888 B / +660, and the process subject reserve rises from ten to fourteen 64-byte subjects; G0 is renewed | Task-2 implementer: the complete module measured a 35,373 B / +607 add record against a 31,602 B / +590 bound after one compaction, with every remaining check required by S9/S16; Task 1 used two process subjects (fix range plus evidence), so ten cannot cover Tasks 2-3 | Cutting required validation to fit, which is truncation (S13) |
| S21 | Task-3 G0 revision. R3's criterion AC-MIG-02 names the legacy token `resolve-bindings`, and every criterion keeps its original text and digest, so `review_issue100.py` gets one `LEGACY_MIGRATION_INPUTS` row in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, the allowance route Task 1 used. The contracts test becomes a cumulative Task 1 + Task 3 record bounded at 3,072 B / +5, and G0 is renewed | Task-3 implementer: `test_living_source_has_no_legacy_policy_surface` refuses `python/agent_tools/review_issue100.py:42: resolve-bindings`, the only failure among 188 contracts tests | Escaping the token as `resolve\x2dbindings`: it hides a legacy mention from the scan, which must not widen silently. Loading criteria texts from R3's blob: a hidden input |
| S22 | Final-review G0 revision. The correctness axis found three validation gaps: issue-121 final-record lineage and edge-fact shapes, and the issue-100 head entry against its history. Tasks 2 and 3 each get a third 64-byte subject for one final-review fix commit; the `review_issue100.py` bound rises to 29,184 B / +540 and its test to 21,504 B / +370; G0 is renewed | Task-3 fix round 1 left the module 1 B under its bound, and the plan reserved one fix subject per task, already used | Cutting validation to fit (S13); deferring a validator gap that accepts a rehashed forged payload |
| S23 | G2 revision. The real-object proof found that `validate_100` binds a raw parent only as "the base or an earlier range commit", so a rehashed payload with a re-pointed parent validates while the counts stay 82/91/9/543. `Issue100Pins` gains a pinned digest of the raw parent edges, which `validate_100` recomputes. Task 3 gets a fourth 64-byte subject, its test bound rises to 23,552 B / +400, the process reserve rises to sixteen subjects and the spec, plan-root and Task-3 process bounds rise; G0 is renewed | G2 adversarial reviewer on the real objects (defect D1); the portable fixture hid it because its live commit lies outside its range (D2) | Leaving the gap to REPLAY: G2 is this child's gate and it fails; relying on the head-entry walk, which refuses only first-parent forgeries |

Design and grill frontier: closed within the approved scope. The resolved
bindings carry no context-map or ADR route, so this ledger is the issue's
decision store.
