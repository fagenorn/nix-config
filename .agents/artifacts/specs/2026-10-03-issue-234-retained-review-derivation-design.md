# Issue 234 — retained review derivation and portable replay

## Problem

Parent [226](https://github.com/fagenorn/nix-config/issues/226) needs authenticated
answers about two retained deliveries (issue 121 and issue 100) that anyone can
check without the retained repositories. CORE
([233](https://github.com/fagenorn/nix-config/issues/233), merged in #246) now
publishes the shared actual producer, the generic projector and one raw
original-history authority. It has no retained adapter, no Task-7 model, no
issue-100 verifier, no witness and no derive or replay command. The only retained
adapter is the unaccepted Task-3 recovery input. Its open Important finding (I1)
shows that a clone-local graft adds a redundant parent while the raw objects,
signatures and exact 30-commit range stay the same. `derive_121` then accepts 31
edges, and the direct `tasks-1` adapter accepts the rehashed forged table as
valid unavailable evidence.

Design identity `DP226-DERIVE`, slug `retained-review-derivation`, second of
CORE → DERIVE → [EVIDENCE 235](https://github.com/fagenorn/nix-config/issues/235).
Immutable child `DELIVERY_BASE`: `93e6059a6fece769a621657c5889278b9cb9e0d7`
(integration containing accepted, published CORE). Every complete gate covers
all process and product commits after it. Parent 226 stays open.

## Solution

Add six library modules and two command modules to `agent_tools` (D1), each
built on CORE's published primitives:

- **issue-121 adapter**: classifies all 30 commits, builds the ordered original
  edges from raw parents, and handles the fixed `tasks-N`/`tasks-N-M` selectors.
- **Task-7 model**: the 173-row estimate table and the fileless Task-8 effect.
- **issue-100 verifier**: checks the historical byte domain and the payload.
- **witness/anchor authentication**.
- **derivation**: writes one deterministic portable bundle.
- **replay**: checks that bundle without Git.

Two command-table rows are added, `derive-review-feasibility-fixtures` and
`replay-retained`. Derivation reads only immutable Git objects and archive bytes
named explicitly by the caller, and writes only into a fresh output directory.
Replay needs only the bundle and a trusted anchor identity that the caller
supplies.

The I1 correction (D2) removes every effective-traversal parent read from the
retained path and checks each claimed edge against CORE's raw parent authority.
Historical boundaries remain measurements. Where reconstruction cannot be
proved, the result is an authenticated, neutral `projection_unavailable`. No
result is fitted.

### Recovery manifest

The rows below record which source effects become which child requirements. Each
implementation task report names the rows it consumes and any effects it
deliberately leaves out. These sources are recovery input only. Their old tests
and reviews accept nothing here.

| ID / original identity | Recover into DERIVE | Disposition |
|---|---|---|
| R1: `35e6fd7aa59f11160b08047b967e0be6cd919bac` `review_contributions.py` + `tests/test_review_contributions.py` | Fixed assignments, plan-anchor signature check, selector/prerequisite fact shapes, `reconstruct_boundary`/`derive_121` structure | Re-author under the new module name. Replace `rev-list --parents`/`--topo-order` edge enumeration and the ancestry check with the CORE authority (D2). CORE already took the generic R3 effects. |
| R2: `a5e942fddd53b0c559f20aae4a674ac3b0e901a5` parent spec D4/D8/D10/D11/D16–D19 and task-4/5/6 briefs | Task-7 table, anchor/witness, historical domain, outcome-row and replay contracts | Recover these as contract text, except where a later decision here supersedes them. The briefs' file names and CLI shapes are superseded by D1/D6. |
| R3: `55cef0357fc648bede7e6840d6186d7dd4d10dd8` deriver blob `913ab952801cf9d8dc59d89fa674a3ba38a3ed2d` | issue-100 constants (range/live/criteria/pending paths/accepted body digest) and the archive-envelope check | Port these into the package. Drop its pathname-multiplier projections and its hard-coded boundary expectations: they are the rejected I2 model. |
| R4: newly authored | Raw-parent edge fix, Task-7 renderer/composition model, witness/replay, both commands, full-shape tier | Charged in DERIVE's own committed forecast. |

## Decisions

### Package shape and the CORE seam

Responsibilities split by domain operation (D1). Each command module only parses,
reads, calls, writes and maps exits. Canonical bytes and digests use
`agent_tools.canonical` (`telemetry_digest` and the strict-load hooks) or CORE's
`canonical_bytes`/`strict_json`, never a local copy. Git facts come only from
CORE's original-history functions (`original_range`/`original_commit`/
`original_ancestor`/`original_edge` through the `review_forecast` wrappers,
`edge_facts`). Reconstruction uses `reconstruct_owned`. Fresh records use
`actual_inputs_from_trees` with `RECORD_POLICY`, and measurement uses
`select_candidate` with the `describe("review-package")` authority. No retained
module calls `git rev-list`, `git log` or `rev-parse <commit>^{tree}` to establish
parents, membership, order or trees. Policy limits are never copied.

Every changed file must stay a single whole review record well under the
65,536-byte member cap, because records are never split. Modules and tests are
divided along the same domains to keep that true. The plan forecasts each file,
and CORE's projection of the whole plan decides fit (D9).

### Issue-121 adapter and the ancestry fix

The adapter pins range
`65748f480124515b9d0ee1467e958bbd9d54fc4a..fe85677c8bd26c808ac69c2ee21b17ff6e262923`.
It also pins the twelve exact process commit/reason pairs from issue 226 (both
`design_budget_fix` rows included) and the eighteen task 1–6 assignments
recovered from R1. The late fix `8e6f0681908cb1ba3d352be5d26540dab731ffeb` stays
Task 3. `classify` requires exactly that ordered raw range and assigns each
commit exactly once. Unknown, task-zero, invented, duplicate or multiple
assignments fail, as does an observed Task 7/8 in the range.

Edges come from the raw commit objects (D2). For each commit in CORE's
`original_range` order, its raw parent list (`OriginalCommit.parents`) yields one
`edge_facts` row per original ordinal. The retained range is linear, so the
adapter also requires exactly one raw parent per commit, each equal to the
preceding range member or the base. That gives exactly 30 edges. A traversal that
disagrees with the raw parents is refused by CORE's `_guard`/`_traversal`. A
graft, replacement ref, shallow file or routing variable makes the operation
invalid (`ContributionError` caused by `HistoryError`). It never becomes a valid
unavailable outcome or merely changes a refusal reason. An edge row carries
parent, commit, raw ordinal, owner, per-record old/new path, before/after
entries, record bytes/digest and hunk-header digest. Its `id` is the telemetry
digest of everything else. Source bodies are never retained.

The fixed-selector entry point (`reconstruct_boundary`, `tasks-N`/`tasks-N-M`
over owners 1–6) recomputes the complete edge table through that same raw path.
It then requires the caller's ordered edges to match canonically, so a rehashed
forged table (31 edges, reordered, dropped or added) is invalid. The prerequisite
must be either the delivery base or an authenticated commit/tree. Every product
commit through it must belong exactly to the dependency closure `1..first-1`. A
null commit/tree pair is accepted only when no such commit exists. Ownership is
never taken from a caller-authored plan path.

Plan anchors pin the root plan blob `8294252bb15684d9bf6054d7faf84ac98a376923`
and the task-7 blob `c8c622dd6389dc844a7fc638c305d2ab71223cb8`. Each latest writer
of the nine plan paths is verified against the pinned SSH signer under an
isolated allowed-signers/revocation file. The writing commit and blob identity
come from the raw closure. The replacement-ref and signature defenses stay in
force alongside the new raw check.

### Historical outcomes

Every outcome row is closed:
`boundary,state,prerequisite,edge_ids,estimate_refs` plus the fields of its tag.

- **`measured`** adds `result_tree,record_refs,measurement`.
  `measurement` = `{package_name,packing_policy_sha256,artifact_policy_sha256,metrics,budget_status,violations}`,
  with all four metrics and ordinary within/over-budget semantics.
- **`projection_unavailable`** adds only `failure:{stage,code,evidence_refs}`. It
  never carries a tree, records, metrics, status or null placeholders.

`edge_ids` always lists the complete selected original edge sequence, even when
proof stops early. Every reference resolves exactly once into the authenticated
tables.

The issue-121 payload holds `aggregate:{actual,projected}` and the ordered
boundaries `tasks-1-3`, `tasks-4-6`, `tasks-7-8`. No status is predetermined, and
none is hard-coded or asserted by derivation or tests.

| Boundary | Prerequisite | Supported route |
|---|---|---|
| `aggregate.actual` | base | Measure the complete fixed range with the shared builder. |
| `aggregate.projected` | base | Actual plus the composed Task-7 table (D4). An unsupported composition makes it unavailable. |
| `tasks-1-3` | base | Whole-path replay of owned commits. The late fix touches paths from excluded Task 6, so CORE's proof stops there and the boundary is unavailable with that edge as evidence. |
| `tasks-4-6` | completed tasks 1–3 | No raw commit has exactly that product closure, so the result is `prerequisite_composition_unsupported` (or `dependency_unavailable` when replaying the dependency fails). |
| `tasks-7-8` | `fe85677c…` (product closure exactly tasks 1–6) | Future-only: no owned actual commits, plus the Task-7 table. `result_tree` equals the prerequisite tree, and no executed tree is invented. |

These routes describe how each boundary is decided, not what it must conclude:
whatever the real proof yields is recorded.

Historical boundaries charge no newly authored process estimates (D5). Their
process artifacts already exist as aggregate provenance or inside the
prerequisite. The signed Task-7 brief makes the Tasks 7–8 repository package
exactly one adoption commit. `operational_effects` is exactly
`[{task:8,repository_bytes:0,state:"unexecuted",acceptance:"post-integration-registration-evidence"}]`.
No fit claims registration or activation.

### Task-7 table and Task-8 effect

`task7-estimate/v1` is authored by this issue. It binds:

- the D10 record policy and packing-policy digests;
- the pinned tree of `fe85677c`;
- the plan-root and task-7 blobs;
- the operation-model version;
- every renderer/source blob identity (the adopt tool's sources at `fe85677c`);
- the fixed subject template `chore(adopt): adopt <project_id> at plan <12-char fragment>`;
- separate `historical_scope`, `projection_estimate` and `observed_actual: null` fields.

It has exactly 173 unique final logical paths:

- **165 unchanged moves**: 54 specs, 108 plans and three rejected/deferred decisions.
- **Five rewrites**: the project contract, ignore rules, legacy skills
  configuration and both generated instruction projections.
- **Three additions**: runtime sentinel, migration map and adoption evidence.

Mappings are derived from the pinned tree and typed rules. Unknown digest
contents in paths use fixed-length 64-hex placeholders and are charged at full
encoded length. A row records operation, old/new path, input blob/mode/bytes/
lines, shape-fact references, output bytes/lines, record bytes and derivation
rule. Counts are non-Boolean integers.

Bounds are relative to the table's prerequisite (the pinned tree).

- **Moves** require equal blobs and modes. An R100 record bound covers the actual
  Git headers, escaping of both quoted paths, and the similarity/rename/mode
  lines. Path length alone never counts as a size model. Where identical blobs
  admit several pairings, each destination takes the maximum over compatible
  sources, and the actual Git pairing is kept separately.
- **Writes and additions** bound the whole rendered output. The fixed portions
  come from the pinned renderer/schema. Every variable field's count and maximum
  encoded length are fixed before the bound is computed, and the bound covers
  the full delete/add record: Git and hunk headers, line prefixes and
  no-newline markers.
- **The migration map** covers all 165 sorted pairs.
- **Adoption evidence** covers the finite source, decision and check sets and the
  platform/base/projection identities.
- **The two instruction projections** have separate bounds.

The project identity is an explicitly labeled `authored-estimate`, recorded as
`max_encoded_bytes` only (D4). No project contract is read or persisted. A
missing renderer, an unbounded field or an incomplete inventory produces
`unsupported_estimate` and an unavailable outcome, never a multiplier, a
percentage reserve or an unexplained ceiling.

For projections whose prerequisite is not the pinned tree (`aggregate.projected`),
the composition rule is closed. Moves are applied as exact blob relocations in a
disposable index over the projection's final actual tree. Their records are
measured with the shared builder. When the prerequisite is the pinned tree they
must not exceed the row's R100 bound, and otherwise they are measured as
whatever add or delete/add record Git yields. Write targets take the larger of
the measured removal of the prior blob plus the row's output bound and the
observed record, following CORE's larger-wins rule. A composition this rule
cannot express is unavailable.

The model is checked against real output in two ways:

- In the portable tier, the real source producer runs under hostile rename,
  quoting and rename-limit configuration on real-Git fixtures that reproduce
  each operation shape.
- In the full-shape tier, the pinned renderer runs for real (D10). The pinned
  adopt tool, its five libraries and the resolver are materialized from their
  blobs into a staged scratch `HOME` and run by command name on a scratch `PATH`.
  It runs `plan` and then `apply` in a disposable, alternates-backed clone of the
  pinned tree, signing with an ephemeral SSH key generated in scratch. Every
  record of the resulting commit is measured with the shared builder and must be
  no larger than its row bound.

Neither touches the retained checkout, the user's signing key or a real
registry: `verify --register` is never invoked. Observed Task-7
actuals stay `null`.

### Issue-100 payload and byte domains

The payload pins base `6d4b7a49dd3a44c079c8310e902a86665a6805f0`, head
`a7b7c6f45787c7c928d064b46ed499087b5b3c46` and live
`cba57498b1ec25f904bd2653029636c79abba41f`. It keeps:

- all 543 ordered history edges with raw parent ordinals;
- 115 contributions: 8 historical-process, 38 already-integrated and 69
  candidate (65 ordinary, four needing reconciliation), with zero reconciled;
- the four pending overlaps: `.github/workflows/ci.yaml`, `CLAUDE.md`, `justfile`,
  `tests/test_branch_protection.py`;
- every governing and superseded criterion with its original digest.

The summary fields are recomputed from the complete tables and are never
independent assertions. A candidate label proves neither integration nor
activation.

Archive bytes are checked before they are decoded: producer, manifest and ordered
shards are read without following symlinks and within bounds, and must match the
pinned identities. The fixed `retained-git-records/v1` recipe (source commit
`55cef035…`, blob `913ab952…`, exact argv/config) must reproduce them as 1,005,707
bytes / 115 records / SHA-256 `3869e4bf…92bc`. Fresh `review-git-records/v1`
records are a separate domain: 1,012,913 bytes / 115 records / `5c6c4fbe…c9d4`.
Each raw-record table carries `record_table_policy:{domain,policy_sha256}`, and
the witness `table_policies` maps every such table. A relabeled domain is
refused. Historical bytes are never used as fresh bounds, and no command offers
a historical measurement mode.

### Bundle, witness and anchor

The bundle is exactly five canonical ASCII-LF files: `issue-121.json`,
`issue-100-derived.json`, `task7-estimate.json`, `derivation-witness.json` and
`derivation-anchor.json`. The anchor conforms to the contract that CORE's
`derived_from: retained-anchor/v2` loader already enforces (D3):

- version 2, kind `review-feasibility-derivation-anchor`;
- keys `schema_version,kind,tool,issue_121,issue_100,archive,estimate,payload`;
- `payload:{encoding:"canonical-json-ascii-lf/v1",members:[{path,bytes,raw_sha256}]}`
  over the four sorted payload files.

The witness is version 2 with exactly
`schema_version,kind,components,fixtures,tables,table_policies`. Its components
equal the anchor's. It holds no anchor identity and no digest of itself.

Construction is acyclic. Derivation:

1. verifies the inputs and the tool closure;
2. emits the three fixture payloads;
3. emits the witness that references their raw bytes;
4. hashes all four into `anchor.payload` and writes the anchor last.

The tool component binds the reviewed `--tool-commit` and the sorted
`{path,blob,raw_sha256}` closure of the entire `agent_tools` package. At
derivation, the running package's module bytes must equal those blobs (D6). The
artifact-policy identity is bound too. Output files lie outside the tool closure.

Replay proceeds in a fixed order:

1. Bound and strictly decode the anchor, then compare `telemetry_digest(anchor)`
   with the caller's expected digest.
2. Check every raw member's size and SHA-256 before any semantic decode. A
   missing, extra, symlinked or traversing member fails.
3. Run full semantic validation: closed shapes, component equality, table
   references, raw parent ordinals, ordered edge and contribution coverage,
   unique final records, domain policies, every issue-100 fact and criterion,
   the Task-7 table counts/bounds/identities, and every outcome row's
   references. Without Git, replay also re-checks the structure of the history
   tables: issue 121 must form an exact linear chain of 30 ordinal-1 edges from
   the pinned base to the pinned head, and every issue-100 edge's commit and
   parent must close over the pinned range.
4. Only then classify the outcomes.

If every outcome is measured, replay exits 0 with a canonical v3
`review-feasibility-retained-result` that holds `issue_121`
(`aggregate`, `boundaries`, `operational_effects`) and `issue_100`
(`history_edge_count`, `disposition_counts`, `pending_overlap_count`,
`fixture_sha256`). A measured over-budget outcome is still exit 0, because it is
a valid measurement.

If any outcome is unavailable, replay exits 2 with empty stdout. Its single
stderr line is `replay-retained: projection_unavailable: <ordered ids>`, written
only after complete validation. Invalid input also exits 2, with
`replay-retained: invalid: <code>`. A malformed sibling never hides behind an
expected refusal, and no mixed success object is emitted (D7).

### Commands

`derive-review-feasibility-fixtures` takes explicit inputs only, all required:
`--issue-121-repo`, `--issue-100-repo`, `--archive-dir`, `--tool-repo`,
`--tool-commit FULL_SHA` and `--output-dir`.

- The output directory must not exist and must not alias any input. Scratch
  space is private and is removed on every outcome. A failure leaves no output
  directory.
- Inputs (refs, index, worktree, objects, archive bytes) are unchanged before
  and after, on both success and failure.
- On success it prints one canonical summary,
  `{anchor_sha256,members:[{path,bytes,raw_sha256}]}`, and exits 0. It exits 2 on
  any invalid input.
- Two derivations from the same inputs are byte-identical: no clock, locale,
  temporary-path or ordering leak.

`replay-retained` takes `--fixtures-dir DIR --expected-anchor-sha256 sha256:HEX`.
The anchor is the bundle's fixed `derivation-anchor.json`, and the anchor is
trusted only through the expected digest (D6). Both parsers keep the closed
`prog` and the error mapping of `review-feasibility`, and both run under the
isolated launcher.

### DERIVE's own delivery gate

Before implementation, commit this spec, the complete indexed v3 plan and its
honest forecasts. The forecasts charge every module, test, recipe, command-table
row, documentation edit, expected fixes, shared-path sequences and subjects. The
plan's `derived_from` is `null`, because EVIDENCE commits the anchor.

Before any product work, CORE's published `review-feasibility project` must
project the entire committed plan, followed by `validate-result` and an
independent comparison of every identity and all four metrics. It runs with the
matching reviewed source closure (source `artifact-budget` on `PATH`), not an
ambient installed helper (D9). Exit 0/within budget clears the gate. Exit 2 or 3
stops, with no new bootstrap. Plan or source changes require a new committed
package and a renewed projection.

The complete fixed-base actual gate runs after every task and fix, and again at
the end. The derivation source gets independent review at a pinned child commit,
and that commit is the `--tool-commit` for authoritative full-shape runs. A
fresh adversarial reviewer repeats the graft/rehash reproduction on disposable
clones. The final gates are the focused tests, full `agent-workflow-tests`,
managed `nix-build`, the installed tests, the retained full-shape tier, and
distinct authorship-independent conformance and correctness reviews. No gate
passes by skipping.

## Test seams

The test seams are the existing ones: source commands run as
`python -m agent_tools.<module>` under the recipe's `PYTHONPATH`, temporary real
Git repositories with importable functions, and the installed-layout module for
built launchers. Two tiers (D8):

- **Portable tier.** Listed in `agent-workflow-tests` and runnable in CI. It uses
  real-Git fixtures and the actual source producer, with no retained objects.
- **Full-shape tier.** Run by a new build-dependent recipe that always sets one
  explicit retained-inputs variable. It covers a source module and a retained
  class in the launcher test module. Following the `AGENT_SKILLS_INSTALLED_HOME`
  precedent, these skip only when run outside their recipe. With the variable
  set, missing or unreachable inputs fail. Full-shape acceptance comes only from
  this recipe.

| Contract | Required independent evidence |
|---|---|
| Ancestry fix (both entry points) | Portable: real-Git linear fixtures with graft, replacement ref, alternate replace base, shallow file, routing variables, and raw parent deletion/reorder under a rehashed table. Both the deriving entry and the selector adapter raise invalid. A clean control passes. Source refs/index/objects are unchanged. Full-shape: a disposable alternates-backed clone of the retained objects with clone-local `info/grafts` reproduces I1. The derive command and `tasks-1` both refuse the 31-edge and rehashed forms, while the clean control yields exactly 30 edges. |
| Assignments and anchors | All 30 assignments are exact. Unknown, task-zero, duplicate, multiple, observed-7/8, reordered, omitted and duplicate-final-record mutations fail. Forged or wrong-key signatures and substituted plan blobs fail. |
| Outcomes | Each row's closed shape. An unavailable row with a tree, metrics or records attached fails. Removing or reordering an edge after the failed one fails. Forged or removed failure references fail. No status is hard-coded. |
| Task-7/8 | Exact 173/165/54/108/3/5/3 and unique mappings. Real producer records under hostile config stay within bounds for every operation shape. In full-shape, real pinned-renderer output stays within its row bounds. Removing a variable bound gives `unsupported_estimate`. Rehashed changes to facts, renderer, blob or digest fail. `observed_actual` is null. Task 8 has zero bytes and is unexecuted. |
| Issue-100 and domains | Full-shape: archive and fresh byte domains match exactly and stay distinct, and label swaps fail. 543/115/8-38-69(65+4)/4/0 and every criterion hold. Rehashed coverage, order or fact changes fail. The archive is byte-identical before and after. |
| Witness/anchor | Portable: raw-member binding before decode, a replacement anchor against the unchanged expected digest, and missing, extra or symlinked members. Full-shape: on the real bundle, each tool, source, tree, archive or estimate component change and each record-digest or reference substitution with all mutable hashes recomputed is refused. With test-only trust injection to reach semantics, a malformed issue-100 or Task-7 next to a valid issue-121 refusal is invalid, not unavailable. |
| Bundle and commands | Full-shape: two derivations into fresh directories are byte-identical. Replay with the source repositories unreachable gives the expected exit and stdout/stderr contract. Source and built derive/replay produce the same bytes and outcome under hostile `PYTHONPATH`/`NIX_PYTHON*`. Inputs are unchanged. No source bodies, transcripts, credentials or policy snapshots appear. Every output is bounded. |

## Out of scope

The following belong to EVIDENCE: committing the five concrete outputs, the
published trust identity, and the concrete committed-bundle regressions. Also
out of scope: host activation (`just switch`), caller adoption, lifecycle
rollout, executing Task 7 or Task 8, and real registration, reconciliation or
activation.

Nothing changes in retained worktrees, parent evidence, lifecycle state or the
object store. That includes adding refs to protect the unreferenced issue-121
objects: an absent object fails closed. Also excluded are general hunk
independence, inverse relocation, synthetic prerequisite composition, changed
caps, expanded generated exemptions, split records and fitted historical
results.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Six domain modules (121 adapter, Task-7 model, issue-100 verifier, witness/anchor, derivation, replay) plus two thin command modules named after their command-table rows | Agent-helper standard 1–2; the-bar SRP; issue 234 command names; whole-record member cap | One retained module or a `review-feasibility replay-retained` subcommand: mixes responsibilities, creates oversized records, and contradicts the approved command rows |
| D2 | Retained edges and membership come only from CORE raw parents. The linear range must produce exactly 30 single-parent edges. Both entry points recompute through that path, and virtualization is invalid, never unavailable | Task-3 I1; CORE D4/D9 and the `review_git` authority; issue 234 ancestry decision | Patch only `contribution_edges`, or compare against effective traversal: the selector would still trust a rehashed table, and a changed refusal reason is not rejection |
| D3 | Adopt CORE's committed `retained-anchor/v2` anchor contract and the four payload names exactly, with a witness that carries no anchor identity | CORE `derived_from` loader; parent D5/D8 | A new anchor version: EVIDENCE's committed bundle would fail CORE's existing loader |
| D4 | Task-7 table relative to the pinned prerequisite tree; aggregate projection through a closed exact-relocation composition; project identity as a bounded `authored-estimate`; real-output checks in both tiers | Parent D4/D10; issue 234 "real rendered outputs"; bootstrap rule against snapshotting policy | Read or persist the project contract, apply pinned-tree R100 bounds to a different base, or use path multipliers: policy leak, undercharge, or the rejected I2 model |
| D5 | Historical boundaries charge no newly authored process estimates; the Tasks 7–8 package is exactly the signed single adoption commit plus its table rows | Signed Task-7 brief; parent D3 (historical process stays aggregate provenance) | Invent per-boundary spec/plan forecasts: fabricated evidence for deliveries that never existed |
| D6 | The tool closure is the whole `agent_tools` package, checked against `--tool-commit` blobs by reading package resources (not loading modules). Replay reads the anchor at its fixed bundle name and trusts only the caller-supplied digest | Issue 234 "reviewed tool identities"; standard 3 bans import machinery and `__file__` lookup; the-bar token economy | Import-graph closure: fragile static analysis. `--anchor PATH`: an extra parameter with no added trust |
| D7 | Replay exit 0 when all outcomes are measured (including over budget); exit 2 with `projection_unavailable` stderr only after complete validation; `invalid:` stderr otherwise | Parent Task-5 outcome contract; the-bar truthful terminal states | Exit 3 for historical overflow: suggests a delivery decision; partial success objects |
| D8 | Two tiers: the portable tier in `agent-workflow-tests`, and a full-shape tier run by a dedicated build-dependent recipe that always supplies explicit retained inputs; launcher cases stay in the installed-layout module | Retained issue-121 objects have no ref and the archive is machine-local ignored state; `AGENT_SKILLS_INSTALLED_HOME` precedent; standard 5; issue 234 forbids synthetic stand-ins | Full-shape tests in CI (they would fail with no inputs), or synthetic-only acceptance (rejected by the issue) |
| D9 | The DERIVE plan is a v3 plan with `derived_from: null`. Published CORE must project it with the matching reviewed closure before any product work. Exit 2/3 stops without a bootstrap | Issue 234 decisions; CORE D2/D8 | Run on the ambient installed helper (it lacks `describe` until a switch), or extend the CORE bootstrap |
| D10 | Real Task-7 output comes from running the pinned adopt tool's `plan` then `apply` in a disposable alternates-backed clone, with a staged HOME and an ephemeral scratch SSH signing key | The pinned planner keeps write bytes in memory and only `apply` materializes them; the signed contract requires `-S`; issue 234 "real rendered outputs satisfy the model" | Lend it the user's signing key or the retained checkout (credential/state exposure), or re-implement the renderer (a second answer to what adoption writes) |

Design/grill frontier is closed within the approved scope. No context-map or ADR
write route exists in the resolved bindings, so this ledger is the issue's
decision store.
