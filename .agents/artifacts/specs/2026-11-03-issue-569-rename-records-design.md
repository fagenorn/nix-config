# Review packaging pairs edited moves as rename records — issue 569

Issue: https://github.com/fagenorn/nix-config/issues/569. It unblocks
https://github.com/fagenorn/nix-config/issues/178, which stopped at planning
because `review-feasibility confirm` exited 3 (`member_bytes`, `member_count`,
`aggregate_bytes`). Designed autonomously (`from-issue --auto`); every call made
without the user is a row in the Decision ledger. Earlier ledgers are cited as
"439 Dn" (whole-file deletion), "233" (review projection core), "248" (retained
source models) and "178 Dn".

## Triage

Input: `{"signals": {"contract_change": {"value": "hit", "evidence": "Record policy is versioned to review-git-records/v2, RECORD_OPERATIONS and the forecast contribution schema (change: rename with old_path) change."}, "concurrency_or_persistence": {"value": "no", "evidence": "Pure diff measurement and forecast validation; no locking or persisted runtime state beyond committed retained evidence that must stay unchanged."}, "open_design_questions": {"value": "hit", "evidence": "The fixed similarity threshold value, the ambiguous-pairing tie-break and how v1 retained domains stay pinned are not fixed by the issue."}, "criteria_shape": {"value": "hit", "evidence": "Eight acceptance criteria, including the retained tier on a quiescent root."}}, "paths": ["python/agent_tools/review_actual.py", "python/agent_tools/review_forecast.py", "python/agent_tools/review_projection.py", "python/README.md", "home/common/agent-skills/tests/test_review_package.py", "tests/test_review_forecast.py"]}`
Verdict: `{"hits":["contract_change","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Problem

A delivery that moves files and edits them cannot be reviewed or planned today.

- **Review packages.** The record policy pairs only exact renames
  (`--find-renames=100%`). A `git mv` with any edit packs as a deletion of the
  old path plus a whole-file addition of the new one. Measured on a scratch
  clone of `3be26be2`: the ten #178 moves with a light, simulated edit
  (shebang dropped, one import line per 400 lines, one symbol renamed) pack as
  20 records totalling 1,257,389 B at 10 lines of context, largest 293,839 B,
  over all three caps. The same ten files with the same edits, paired as
  renames, are 10 records totalling 100,864 B, largest 22,611 B. The whole-file add half never gets generated
  evidence, so the delivery is `decompose_required` however it is cut.
- **Forecasts.** A plan cannot describe a move. `change: rename` is refused as
  `projection_unavailable`, so #178 D20 forecast each move as a whole-file
  delete plus add and the projection overflowed.
- **No split works.** A prep delivery cannot stay green at the old location,
  and any later edit in the same PR range turns an `R100` back into delete plus
  add.

## Solution

Fresh review measurement moves to a new record policy,
`review-git-records/v2`. It is v1 with a new kind and one argument changed:
renames pair at 50% similarity (per D1). An edited move becomes one record keyed by its new path.
The record body is git's own rename section with every hunk. A pure rename stays
header-only. Copy detection stays off and the rename search stays unlimited.

The retained evidence keeps measuring and replaying under v1, which is frozen
beside v2. That keeps the committed bundle, its anchor digest and its tool
commit unchanged (per D2).

The forecast accepts `change: rename` with a required `old_path`. Its bound is
the whole rename record at 10 lines of context (per D7, D8). A completed rename
consumes its old path (per D9).

No cap moves.

## Decisions

### Record policy v2 (D1, D3, D4)

- `review-git-records/v2` is v1's policy object with exactly two changes:
  `kind` becomes `review-git-records/v2`, and `--find-renames=100%` becomes
  `--find-renames=50%`. The git configuration stays `diff.renames=true` (never
  `copies`), `diff.renameLimit=0` and `core.quotePath=true`. Every other diff
  argument is unchanged. The threshold is written explicitly in the argv, so it
  never depends on git's default. The record view of issue 255 stays as it is:
  no configuration, attribute or environment source can change the pairing.
- The packing policy keeps its kind and rules (`review-packing/v1`). Its digest
  moves because it binds the record policy's digest (per D3).
- **Pairing is git's own (per D4).** Git pairs deleted sources with added
  destinations by score. Ties go to git's own order, and each source is used at
  most once. The generator never re-pairs. Measured with git 2.51:
  - One deleted file and two equally similar added files: the first destination
    path pairs (`R099 a.txt b.txt`) and the other stays `A`.
  - Two identical deleted files and one similar added file: the first source
    path pairs and the other stays `D`.
  - Three runs gave the same records.
  - Pairing is fixed per git version. Every host runs the flake-pinned git
    (2.51.2 here). A host whose git paired differently would make `confirm`
    refuse rather than pass.
  - Inexact detection now runs, and costs at most 0.4 s on the repo's
    largest ranges (up to 1,839 adds, measured).

  An unpaired source stays a `D` record, and an oversized one still gets
  `whole-file-deletion` evidence (439 D1). An unpaired destination stays an `A`
  record.
- A move below 50% similarity stays delete plus add, and its oversized add half
  still fails `member_bytes` with no retry. 439 D2 still holds below the
  threshold. At or above it, 439 D2 and 233's "R100 only, modified moves use
  ordinary records" rule are amended.

### Record shape (D4)

- **Moved and edited.** One record keyed by the new path. Its body is git's
  `diff --git a/<old> b/<new>` section verbatim: any `old mode`/`new mode`
  lines, `similarity index N%`, `rename from`, `rename to`, the `index` line,
  `--- a/<old>`, `+++ b/<new>` and every hunk of the old blob against the new
  blob, at the candidate's context. The old path has no record of its own; it
  appears only inside the new path's section. This is how the design reads the
  issue's "the old path appears only as `rename from`".
- **Pure rename.** It stays header-only. That includes a mode change: an exact
  move that drops the executable bit is `R100` with mode lines and no hunk
  (measured).
- **Coverage.** Name-only, name-status, numstat and patch run under the same
  policy, so they agree:
  - a rename is one path, one status entry, one numstat row (rename framing,
    which `_parse_numstat` already reads) and one section;
  - `stat.files_changed` equals `coverage.file_diff_count`;
  - an edited move whose blobs differ in N lines has exactly N `+`/`-` lines in
    its record.

  Measured on the ten #178 files: the per-record `+`/`-` counts sum to
  numstat's 85/53, and `files_changed` is 10.
- **No generated evidence on renames (per D5).** A rename record is never
  replaced by generated evidence. An oversized one stays whole, and the package
  is `decompose_required`. `ef-core-migration-designer` and
  `whole-file-deletion` keep applying to the non-rename records they apply to
  today.

### One operation table (D6)

- A single operation rule, derived from the record policy, serves both
  `_record_operations` and `edge_facts`. `RECORD_OPERATIONS` becomes that one
  table, so it and the edge-facts table cannot drift.
  - `A`, `M`, `D` and `T` carry one name.
  - `R` followed by a three-digit score carries two names (old, then new),
    when the score is at least the floor named by the policy's
    `--find-renames=<N>%` argument and at most 100.
  - Every other token is refused (fail loud).

  Under v1 the floor is 100, so v1 accepts exactly what it accepts today.
- `edge_facts` decides a token's arity from that rule before it reads any
  name; today it reads names first. A rename edge record keeps today's `R100`
  shape: `operation` (the token, score included), `path` (new), `old_path`,
  `before` read at the old path, `after` read at the new path, `record_bytes`
  and `record_sha256`.
- The projection's patch replay already runs `git apply --cached` over the
  policy's patch, which applies rename sections with hunks. Probed: a mode
  change, rename and edit patch rebuilds the exact tree.

### Two record domains (D2, D11)

- `review_actual` holds two record policies:
  - the living one, `review-git-records/v2`, under today's names;
  - the frozen `review-git-records/v1`, kept byte for byte, with its packing
    digest.

  Their digests are pinned by test to the committed literals:
  - v1 record policy: `sha256:73cc5609e8a395d33a210b20f413a72179300475b2f6d1c55fed097c7f6ee63b`;
  - v1 packing policy: `sha256:fbb7b821b21015c5e56a4829c0c33dd2e7233a09a5826287cc563634098b43bf`.
- These entry points take the record policy as a keyword argument that defaults
  to v2: `git_diff`, `actual_inputs`, `actual_inputs_from_trees`, `edge_facts`
  and `reconstruct_owned`. The argument must be one of the two policy objects,
  and each digest's self-check still runs. Anything else is refused.
  `select_candidate` takes no policy: both packing variants choose the same
  candidates.
- **The retained domain is v1 by definition.** These modules pass v1 to every
  measurement call and pin v1's record and packing digests wherever they write
  or compare a policy identity today:
  - the issue-100 fresh table and its `Domain`;
  - the issue-121 `record_table_policy`, its measurements and its edges and
    replays;
  - the Task-7 identities and compositions;
  - the derivation's tool group;
  - the witness's component check.

  `replay-retained`, the committed bundle, `ANCHOR_SHA256` and `TOOL_COMMIT`
  stay unchanged. The retained validators keep their own closed sets with
  `R100`: that is a retained-domain fact, not the live table.
- Fresh measurement uses v2: `review-package`, `review-feasibility`
  `project`/`gate`/`confirm`, and forecast ownership evidence. A saved
  feasibility summary computed before the change no longer confirms, because
  its `packing_policy_sha256` differs. That refusal is correct: the policy
  changed. No committed plan block embeds a policy digest.

### Forecast contract (D7, D8, D13)

- A record's `change` is `add`, `modify`, `delete` or `rename`. `fileless` is
  still refused as `projection_unavailable`.
- A `rename` record has the closed key set
  `id owner path old_path change last_task bounds`. Every other change keeps
  `id owner path change last_task bounds`, so every existing block, and every
  block #559's writer emits, stays valid.
- `old_path` must pass the same path rule as `path` and differ from it. A
  `rename` without `old_path`, or any other record carrying one, is refused.
- `schema_version` stays 3. `_records` keeps its signature.
- A rename accumulates under its new `path`, like any other record. Its
  `covers` is the prefix of that path's ids in the boundary, its horizon is the
  last task touching the new path, and boundary membership is unchanged.
- **Conservative bound (per D8).** A rename's `record_bytes`, `added_lines` and
  `deleted_lines` cover the whole record that `review-package` will measure at
  its new path at 10 lines of context. That record is git's rename section from
  the base blob the content came from (`old_path` in the boundary's base, or the
  first path of a rename chain) to the final blob at `path`. So it includes any
  earlier edit to that content in the boundary. A pure move is its header-only
  record.
- **When git will not pair (per D13).** Git pairs only a source that is gone at
  the boundary's end, and it may prefer a closer destination. If a later task
  re-adds `old_path` (probed: `M o.txt`, `A p.txt`), or another added path
  matches the source better, the new path measures as a whole-file add. The
  bound then covers that add. The forecast states the move; the bound states
  what git will measure.
- **Projection (per D8).** A future rename is charged like a future add of its
  new path: the larger of the bound and any current record at the new path,
  plus its unobserved lines. Any actual record of the old path stays in the
  projection until the rename completes. That overcounts and never undercounts.
  A future rename whose new path is absent at the head needs subject forecasts,
  as future `add` and `modify` content does today.

### Completed effects (D9)

Today a completed contribution needs an owned effect on its path. That rule
stands, and an `R<NNN>` edge record whose new path is the contribution's path
counts as such an effect. Two rules are added:

- **A completed rename consumes its old path.** The old path must be absent from
  the candidate's own tree unless the actual package holds a record for it,
  such as the `D` half of an unpaired range or a later re-add.
- **A completed contribution with no actual record is accepted only if** its
  path is absent from the candidate's tree, and either:
  - it is a `delete` with an owned effect that removes the path, which is a `D`
    record or a rename record whose `old_path` it is; or
  - its path is the old path of a completed rename in the same boundary.

  Any other completed contribution with no actual record is still refused.

### Coordination with #559 (D10)

- This work changes neither `review_budget` nor `review_feasibility`, which the
  in-flight https://github.com/fagenorn/nix-config/issues/559 branch edits.
- The #559 forecast writer calls `_records` and emits only
  `add`/`modify`/`delete`, so it needs no change.
- Both branches edit the review packaging section of `python/README.md`.
  Whichever lands second resolves that textual conflict.

### Documentation

`python/README.md` is the contract's home:

- **Review packaging section:** the v2 policy and its 50% threshold, copy
  detection off, the record shape of a rename, git's pairing and its
  determinism, unpaired halves, and that a rename record never takes generated
  evidence.
- **Review feasibility forecast paragraph:** `rename` with `old_path`, the
  rename bound under the conservative-bound rule (including when git will not
  pair), and consumption of the old path.
- **Retained review evidence section:** one sentence saying the retained
  domain measures and replays under the frozen `review-git-records/v1`.

Prior specs are point-in-time records and stay unedited; this ledger records
the amendments.

## Test seams

Each seam is an existing public boundary, extended rather than replaced.

- **`review-package` CLI**, the 439 seam in `test_review_package.py`:
  - An edited move is one record keyed by the new path. It carries the full
    rename section, its `+`/`-` count equals the numstat count for the pair,
    coverage is complete, and `stat` equals `git diff --numstat` under v2.
    This replaces the "rename with edit" negative (439 AC2).
  - A move below 50% is still `D`+`A`. An oversized one exits 3 with
    `member_bytes`, and the `D` half carries `whole-file-deletion` evidence.
  - Ambiguous fixtures, one source with two equal destinations and two equal
    sources with one destination, pair as measured on every run. The unpaired
    oversized source keeps its evidence.
  - An oversized rename record stays whole and exits 3.
  - An exact rename with and without a mode change stays header-only.
  - The independent expected-diff argv in those tests moves to
    `--find-renames=50%`.
- **Record view table**, `test_review_record_view.py` (issue 255): the
  neutral-by-argument rows name the v2 argument. The existing inexact-rename
  fixture (two deletions, one near-copy) becomes a live v2 case: a hostile
  `diff.renameLimit=1` or `diff.renames=false` would split the pair, and the
  policy keeps it.
- **Policy identities**, the existing packing-policy test in
  `test_review_feasibility.py`: the v2 kind and argv, the frozen v1 literal
  digests, an unknown policy refused by `git_diff`, and the operation rule
  tested against raw name-status bytes: `R049` refused under v2, `R050`
  accepted, `R099` refused under v1, and a three-name `R` refused.
- **Forecast loader and projection**, `test_review_feasibility.py` and
  `test_review_projection_cases.py`:
  - The refusal table: `rename` with `old_path` accepted; a `rename` without
    it, an `old_path` on an `add`, and `old_path == path` refused; `fileless`
    still refused.
  - A plan forecasting an edited move as a `rename` projects at
    `completed_through` 0 with no `projection_unavailable`. After the move
    commit, the measured package's record and totals are at most the earlier
    projection.
  - Consumption: an earlier `modify` of the old path, completed with the
    rename, is accepted.
  - A forecast `delete`+`add` that git pairs is accepted.
  - A completed rename whose old path survives in the candidate tree is
    refused.
- **History edges**, `test_review_history.py`: rename edge facts come from
  the shared rule.
- **Retained domain (per D11).** The real retained ranges hold no rename at all.
  Every first-parent and per-edge diff of the issue-121 and issue-100 ranges
  was measured at 50%, and nothing paired. So neither the retained tier nor the
  committed bytes can tell a v1 measurement from a v2 one. The seams are:
  - An edited move added to a retained unit fixture (the issue-121 linear
    fixture or the Task-7 fixture) measures as v1 `D`+`A`, and the retained
    validators accept it. Under v2 it would be an `R0NN` record those
    validators refuse.
  - `test_review_evidence.py` replays the committed bundle unchanged (fast
    tier).
  - `just agent-retained-tests` on a quiescent root rederives byte-identical
    payloads and reproduces the committed bundle at `TOOL_COMMIT`.
- **The ten #178 pure moves** measure 2,618 B as header-only `R100` records
  under both policies (measured here; re-measured on a scratch clone for the
  acceptance record).
- **No cap is raised.** `artifact-budget-policy.json`, the adaptive-violation
  set and the `member_bytes` no-retry rule are unchanged. Their existing pins
  stay green.
- **Verification:** `just agent-workflow-tests`, `just agent-retained-tests` on
  a quiescent root, and `just build`.

## Out of scope

- Re-planning #178: amending its D20, tightening its bounds, and moving its D3
  rename and D7 test into a follow-on delivery. #178 does that after this lands.
- Raising any cap, or changing the adaptive set or packing rules.
- Copy detection, and break/rewrite detection (`-B`).
- Generated evidence for an oversized rename record, such as a moved EF
  designer (per D5).
- Rename handling in `adopt_apply`, `diff_scope`, `verified-tree`, and scoped
  reviews' per-path `git diff -- <path>`. A pathspec hides the old path from
  git, so a scoped review sees a move as an add. Reviewer prompts are also
  unchanged: git's rename section describes itself (per D12).
- #559's forecast writer emitting `rename` records: a follow-up once both land.
- Migrating or rederiving the retained evidence under v2.
- `edge_facts` refusing a typechange edge. A `T` is two sections, so today it
  fails "edge record coverage mismatch" (probed). This is a separate, existing
  bug that this design does not touch.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | `review-git-records/v2` pairs renames at an explicit `--find-renames=50%`; copies off, `diff.renameLimit=0` kept. Above the threshold this amends 439 D2 and 233's R100-only rule; below it, edited moves stay `D`+`A` | Measured: #177's 11 edited moves score 77–100% and only 1 pairs at 100%; all 34 inexact renames over 781 first-parent commits are genuine moves at 50–99% (lowest 50, 52, 52, 68); simulated #178 moves score 82–99%; 50% is git's default and the R3 historical recipe's value | 80–90%: drops real moves (`adopt_project` 77%, `review_publish` 52%, an edited 642 B `__init__` 82%) back to whole-file `D`+`A`. Below 50%: beyond git's tuned default with no measured move to gain |
| D2 | Freeze v1 beside the living v2 as a closed set of two; measurement entry points take the policy as a keyword defaulting to v2 and refuse anything else; the retained modules pass v1 and pin v1's record and packing digests | Issue AC: `replay-retained` unchanged and pinned to its tool commit; the committed bundle embeds v1 digests in five places; the retained tier compares current-tool payloads with the committed ones byte for byte; 248: "a domain must carry its own policy digest" | Rederiving the bundle under v2: moves `ANCHOR_SHA256` and `TOOL_COMMIT`, which the AC forbids. Keeping the living names on v1 and opting fresh callers into v2: the living name would describe a retired policy, and a new fresh caller would silently measure the frozen domain |
| D3 | The packing kind stays `review-packing/v1`; its digest moves only because it binds the record digest; a frozen v1 packing digest serves the retained domain | 233: "the packing-policy digest binds this record policy"; the packing rules are untouched | Bumping the packing kind: it signals a packing-rule change that did not happen |
| D4 | Records are git's own: git's pairing (score, then git's order, each source once) under the fixed argv in the record view, and git's rename section verbatim, keyed by the new path. "Old path only as `rename from`" reads as "no record of its own" | the-bar Framework-first; probes: ties pick the first destination or first source path, stably over runs; `git apply --cached` rebuilds the tree from rename sections; numstat already frames renames | A custom pairing pass or rewritten headers: diverges from numstat and from the patch that `reconstruct_owned` applies, which breaks coverage parity |
| D5 | A rename record never takes generated evidence; an oversized one stays whole at exit 3 | 439: "Modifications and renames keep their whole records"; EF evidence reads the base side at the record's path, which is absent for a rename destination and would report the move as an add | EF or deletion evidence read over `old_path`: a new evidence shape and validator rule for a case no delivery has measured |
| D6 | One operation rule derived from the policy (`A M D T` one name; `R` plus a score between the `--find-renames` floor and 100, two names) serves `_record_operations` and `edge_facts`; `edge_facts` decides arity before reading names | Issue: "`RECORD_OPERATIONS` and the edge-facts table change together"; the-bar DRY and Fail loud; `edge_facts` hard-codes its own set today | Two hand-kept sets: the drift is what makes `edge_facts` refuse every inexact rename |
| D7 | `rename` requires `old_path` (valid, not equal to `path`); the key set is closed per change, so other records keep theirs; `schema_version` stays 3; `_records` keeps its signature; renames accumulate under the new path; `fileless` stays refused | No existing block changes meaning (rename was refused); #559's writer imports `_records` and emits add/modify/delete only | An optional `old_path` on every record (weakens the closed set). A schema bump (invalidates every in-flight plan for an additive change) |
| D8 | A rename bound covers the whole U10 record measured at its new path, from the base blob its content came from to the final blob, earlier edits in the boundary included; a future rename is charged like a future add of its new path (subject forecasts included), and the old path's actual record stays charged until completion | Issue: "the rename record size at 10 lines of context, accumulated per path"; README's conservative-bound rule; the projection's max(bound, current) rule | Chaining `old_path`'s `covers` into the new path: provenance machinery for a case with no measured need. Bounding only the edit hunks: undercounts headers and context |
| D9 | A completed rename consumes its old path (absent from the candidate tree unless it has an actual record); a missing-record contribution passes only absent from the tree and as a delete with a `D` or rename-from effect, or as the old path of a completed rename; no owned `R` edge is required of the rename itself | Issue: "treats the old path as consumed"; existing deletion proof in the candidate's own tree; v2 pairs a forecast `delete`+`add` into one record | Requiring an owned `R` edge: refuses a copy-then-delete move that the range still pairs. Keeping delete's D-only rule: refuses every forecast `delete`+`add` that git pairs |
| D10 | Coordinate with #559 by not touching `review_budget`/`review_feasibility` or `_records`' signature; the README conflict goes to whichever lands second; rename support in the writer is a follow-up | #559 branch diff (unmerged): edits those two modules and adds a README paragraph after the forecast paragraph | Waiting for #559 to merge: blocks #178 on work that shares no code with it |
| D11 | Prove the retained v1 binding with an edited move in a retained unit fixture (v1 measures `D`+`A`, and the retained validators refuse v2's `R0NN`) plus literal v1 digest pins, beside the committed-bundle replay and the retained tier | Measured: the issue-121 and issue-100 ranges and edges hold no rename at any threshold, so their bytes cannot tell v1 from v2; the-bar Tests that can fail | Relying on the retained tier alone: a retained call site left on v2 would stay green |
| D12 | Scope stops at the issue's What to build: reviewer prompts, scoped per-path reviews, `adopt_apply`, `diff_scope`, `verified-tree` and the typechange edge bug stay unchanged | Phase-0 scope boundary; agent-guidance instruction budget; the issue lists only `review_actual`, `review_forecast`, `review_projection` and the README | Teaching the prompts about renames or fixing pathspec moves now: unrequested prompt bytes and a second subsystem |
| D13 | (grill) A rename's bound is what git will measure at its new path: a rename section only when `old_path` is gone at the boundary's end and git pairs that source with this path; otherwise the whole-file add | Probes: a re-added old path leaves `M old`, `A new`; with two equal destinations the first path pairs; the conservative-bound rule bounds what `review-package` measures | Detecting a re-add or a better match at load time: needs future trees that do not exist yet, and the measured actual already replaces the bound once the move lands |
| D14 | (plan) `RECORD_POLICY_V1` and `PACKING_POLICY_V1` are frozen literals and the living `RECORD_POLICY` is its own literal; a test pins v1's two digests and that v2 differs from v1 only in `kind` and the first diff argument | the-bar DRY: deduplicate only copies that must change together, and the frozen and living policies never do; D2 keeps v1 byte for byte | Spreading one policy into the other: an edit to the living packing rules would silently move the frozen v1 digest, and shared nested objects let one mutation reach both |
| D15 | (plan) The rule is `review_actual.record_operation(token, record_policy) -> (operation, name_count)` over `RECORD_OPERATIONS = {"A": 1, "M": 1, "D": 1, "T": 1, "R": 2}`, its `R` floor read from the policy's one `--find-renames=<N>%` argument; `_record_operations` takes the policy, and `edge_facts` maps a refusal to `ForecastError` | D6; the-bar Fail loud, DRY | A per-policy set of accepted `R` tokens: a second table kept in step with the argv by hand |
| D16 | (plan) D11's proof lands with the flip (Task 2), on opt-in `edited_move` variants of `linear_fixture` (through `model_121`: edges, aggregate actual, Task-7 composition, reconstruction) and `issue100_fixture` (`fresh_records`, `model_100`), each beside a living-policy `R097` control | D11; the-bar Tests that can fail; planning probes: leaving one retained call site on the living policy turned the matching case red | One fixture only: issue 100's two call sites stay unguarded. The proof in the freeze task (Task 1): its control cannot fail before the flip |
| D17 | (plan) Tests stay clear of #559's hunks: the new forecast cases go to `test_review_projection_cases.py`; `test_review_feasibility.py` gains only `RecordPolicyDomainTest` before `SourceProjectionFixture`, a class-level `seed` of extra base files in that fixture, and refusal-table rows | D10; the #559 branch edits that file at its lines 408 and 957, appending a class | Appending new classes to `test_review_feasibility.py`: a textual conflict with #559's appended class |
| D18 | (plan) Task 4 measures AC6 (the ten #178 `git mv`s on a clone of the base, under both policies) and AC8's retained tier on a private quiescent root at the final code head, and writes the acceptance record's evidence columns | sdd's final review: whoever measured writes the evidence columns; #556's private-root procedure; the issue's "on a quiescent root" | Leaving them to sdd's final verification: the retained tier is not a declared verification command, so nothing would run it |
