# Issue 233 — review projection core

## Problem

A delivery needs a trustworthy answer about its complete review cost and any
independently deliverable descendant. Task-range success, unsupported estimates
and altered Git ancestry cannot establish that answer. Integration lacks the
shared packaged producer and generic projector. This delivery publishes both,
with complete source and installed acceptance, without historical fixtures.

Design identity: `DP226-CORE`. Immutable child `DELIVERY_BASE`:
`8836b641551b1ab6f2662379f0c0b83e38f5a0fb`. Every complete gate includes all
process and product commits after this base; integration advances never move it.
The approved sequence is [CORE 233](https://github.com/fagenorn/nix-config/issues/233)
→ [DERIVE 234](https://github.com/fagenorn/nix-config/issues/234)
→ [EVIDENCE 235](https://github.com/fagenorn/nix-config/issues/235).
Parent [226](https://github.com/fagenorn/nix-config/issues/226) stays open until
all assigned requirements/findings have accepted published evidence and a final
parent audit. Its validated complete overflow authorized this decomposition;
no CORE fit is asserted before authoritative measurement.

## Solution

Recover accepted actual/generic work selectively, correct its shared immutable
Git provenance boundary, and publish `review-package` plus `review-feasibility
project/validate-result` through the existing agent-helper package. One actual
record/candidate/packing path serves production and projection. External pinned
budget policy remains authoritative. The independently reviewed corrected source
must successfully project CORE's entire committed plan before installed
publication. Use the explicitly approved conditional source bootstrap below.

### Recovery manifest

Frozen recovery range: `6a8f8a27ebce364cc58de0e5469f72296de42e18` to
`a5e942fddd53b0c559f20aae4a674ac3b0e901a5`, retained in the issue-226 worktree.
Its design and decomposition documents dated 2026-09-29, original task briefs,
reviews and both run histories remain unchanged provenance, never CORE acceptance.
The following is the source-effect → child-requirement manifest. Recovery commits
must identify these rows and any selectively omitted effects in their task reports.

| ID / original identity | Recover into CORE | Disposition |
|---|---|---|
| R1: `adb76e36c871cd0c6acc0df7a5ec03d033c33c1e` (accepted Task 1) | Actual records/candidates, whole-record packer, budget adapter, thin producer and publication; budget query/pinning and legacy tests | Preserve the VCS move from the sdd `review-package` script to `agent_tools.review_publish`; retain ordinary/detail/publication behavior. Source modules/tests and minimum stale-reference repairs accompanying that move may enter bootstrap (D6); command-table/default-module changes, installed tests and broader living documentation belong to later publication. |
| R2: `5907f05a6cf7f0a4e672afa7b2f5cbe680c32e0e` through accepted Task-2 head `adf52bdba1e204a4945f811d9fea03c1836ddaa7` | Generic forecast/ownership/graph/projection/validation, actual packing-policy identity and bounded symbolic measurement; generic source tests | Recover the complete accepted effect, including the earlier implementation and final correction, then apply new provenance correction and fresh review. |
| R3: `35e6fd7aa59f11160b08047b967e0be6cd919bac` (unaccepted Task 3) | Shared typed reconstruction refusals; `test_review_projection_cases` and only its test registration | Select these generic effects explicitly. Exclude retained contribution adapter/tests and their registration; DERIVE owns them and their I1 correction. Passing old tests do not accept R3. |
| R4: newly authored child work | Raw-parent/edge/prerequisite correction, independent adversarial tests, missing command/publication/installed coverage and current architecture references | Charge all recovery adjustments, fixes, sequential shared-path edits, process artifacts and subjects in the committed forecast. No whole parent commit imports unrelated process or retained work. |

## Decisions

### Package and authority

Keep importable packing, actual construction, forecast/provenance, projection and
publication operations separate by responsibility; command modules parse/read,
call them, write and map exits. Use shared canonical JSON strict-load hooks and
semantic digests, the existing sibling-command helper, and external commands by
name on PATH. No dynamic imports, path-derived module calls or private estimator.

Recover the external `artifact-budget describe --kind ... --format json` query:
one closed versioned response supplies the requested artifact kind, four limits,
report wire bound and raw policy digest through its existing loader. It exposes no
project policy. Check/report/detail-validation accept the optional expected-policy
digest; package callers pin it, while legacy invocations remain compatible.
Strictly validate response framing, canonical bytes, shape, limits and exit
agreement. A policy change during an operation fails it. Existing actual producer
CLI, safe publication, detail mode, complete coverage and generated-record rules
remain covered; do not migrate the wider budget/delivery-model cluster.

### Committed v3 contract

`project` receives plan root, immutable base, exact committed head,
completed-through ordinal and optional logical package basename (defaulting to
the actual producer's range-derived name). It writes no package or lifecycle
state. Read the entire indexed plan package at that head, budget-check it, require
committed blobs to equal worktree bytes and reject unindexed/missing members,
symlinks, unsafe paths, uncommitted changes and base/head/tree disagreement.
Require canonical closed version-3 delivery/task blocks; reject duplicate keys,
non-finite numbers, booleans posing as integers, unknown fields/versions and
ambiguous block/index linkage. CORE's own plan has `derived_from: null`.

The delivery block names its base, proposed boundary, ordered boundaries,
owner-zero process records and actual-evidence checkpoint. Each indexed task
owns its ordinal, future subject-byte bounds, ordered records and actual ranges.
Each contribution has a unique ID, owner, final logical path, operation,
completion horizon and ordered per-boundary cumulative support: additions,
deletions, complete-record bytes and the exact same-path contribution prefix it
covers. Product membership equals boundaries containing its owner; process
membership names that boundary's own spec/root/indexed task package. Bounds are
relative to each boundary's prerequisite. Unsupported operations/support are
unavailable; CORE adds no retained model or derivation/replay capability.

Repeated same-path contributions remain ordered provenance but produce one final
logical record. For unfinished work use the larger of the complete observed
record and supported cumulative bound; never drop unforecast actual records.
Completed forecasts require corresponding actual effects or a supported closed
deletion/fileless proof; unsupported fileless/rename forecasts remain unavailable.
Keep actual records, future bounds and process provenance distinct. Use shared
length-based placement and exact manifest/encoded-subject arithmetic for very
large bounds without allocating the forecasted bytes or imposing a new numeric
cap. Symbolic measurements cannot be published as actual review records.

Actual ownership uses `git-range-ownership/v1` with exact head/tree and process
ranges; task ranges identify their ordinal owner. Expand complete reachable
`base..head` differences, never path-filtered approximations. In topological
contribution order, disjoint ranges classify every checkpoint commit exactly
once and preserve every original ordered parent edge with path/blob/mode/record
facts. All range endpoints belong to the authenticated delivery closure. The
checkpoint precedes the evidence-recording commit. Its tail to invocation head
must be a single-parent chain changing only the proposed boundary's declared
process paths; charge all tail effects, including the plan update. Product or
undeclared-path tails are invalid. Completing product work requires a committed
checkpoint/range refresh, changing the package identity without self-hashing.

### Original Git history and standalone reconstruction

One shared original-history authority authenticates raw commit object identity,
tree and ordered parent headers independently of traversal/evidence hashes.
Use it at actual range/subject collection, generic ownership and metadata tails,
edge construction, ancestry/range expansion, prerequisite validation and direct
reconstruction. Parent ordinal is checked against the raw original parent list;
arbitrary pairs of valid commits do not constitute an edge. Effective traversals
must agree with this authority in membership and parent order before any facts or
outcomes are accepted. Rehashed tables and signatures over unchanged objects do
not authenticate a virtual graph. Reject graft/replacement/shallow ancestry that
changes or prevents proof of the original graph; assess environment/configuration
routes as well as repository-local metadata. Preserve existing replacement-ref
and applicable signature defenses. Missing objects or unverifiable closure fails
closed. The source repository, index, worktree and object state remain unchanged.

Each candidate's prerequisite is the delivery base or an exact completed-task
commit/tree whose task set equals the transitive dependency closure and excludes
candidate tasks. Null IDs are paired and permitted only while dependencies are
unfinished. An eligible prerequisite must be an authenticated ancestor of the
evidence head with matching tree; its complete product effects are exactly all
observed contributions of those dependencies, plus explicitly classified process
effects. Missing or unrelated prerequisite effects are invalid. A tree alone,
aggregate historical head or unproved synthetic combination is not a substitute.

Reconstruct only ordered owned candidate product commits and explicitly assigned
process commits in disposable storage from that prerequisite. Authenticate the
entire supplied edge closure before a conservative refusal can conceal bad later
evidence. For each single-parent effect, touched old/new paths must exactly match
the original preimage and postimage entries. Merges preserve all original edges
and require proof of every included effect exactly once. Measure the final unique
records with the shared actual tree-diff builder, then apply only this candidate's
future/process bounds. Bind prerequisite commit/tree, reconstructed tree,
contribution sequence and process-forecast identities to the result.

Whole-path proof intentionally cannot establish all independent same-file hunks.
Dependent excluded edits, disjoint hunks on a changed path, ambiguous/repeated
context, split/relocation effects and unsupported prerequisite composition yield
neutral `projection_unavailable` diagnostics when the evidence is authentic but
the proof is unsupported. Such refusal neither invents a dependency nor emits
partial final records, metrics or a successful projection. Altered provenance is
invalid, not an acceptable unavailable proof.

### Packing, graph and results

Fresh actual/projected records share `review-git-records/v1`: exact-content renames
only, no copies, unlimited rename search, quoted paths, full object IDs, fixed a/b
prefixes, Myers with fixed indicators, no indent/inter-hunk heuristics, color,
relative paths, external diff or textconv. Configuration cannot change record
bytes. R100 requires identical blobs/modes; modified moves use ordinary complete
records. The packing-policy digest binds this record policy and selection logic.

Preserve U10 sequential whole-record packing. Only initial member-count or
aggregate overflow permits U7/U5/U3/U1/U0 stable first-fit whole-file candidates,
in that order. Select the first pass; if all fail, return the initial candidate's
result. Preserve all four external caps, complete changed lines, whole records,
logical manifest/shard names, root/aggregate charges and the manifest's file-count
contribution. No record splitting, expanded generated exemption or hidden costs.

Boundaries form one rooted reachable acyclic tree: unique IDs, one null-parent
root containing every task, nonempty ordered task sets and exact disjoint child
partitions. Independently validate dependency references/cycles and preceding
disjoint deliverability; containment alone proves no dependency. Every boundary
declares standalone acceptance and its own process package, record IDs and subject
forecasts. On valid root overflow, only declared reachable strict descendants
containing the first unfinished task with satisfied exact prerequisites qualify.
Rank fitting reconstructed candidates by fewest tasks, aggregate bytes, then
committed input order. If no eligible candidate fits, the recommendation is null. Unsupported
reconstruction fails unavailable; it cannot be silently skipped to manufacture a
recommendation. Recommendations confer no lifecycle or delivery authority.

The closed canonical result binds version/kind; base/head/tree; plan-package,
forecast, ownership, packing-policy and artifact-policy digests; package basename;
completed ordinal/boundary; actual/projected record counts; `root_bytes`,
`total_bytes`, `file_count`, `largest_member_bytes`; ordered violations and optional
recommendation with its prerequisite/tree/contribution/process identities and
metrics. Success is `complete/within_budget` with exit 0; valid overflow is
`decompose_required/over_budget` with exit 3. Invalid/unavailable input, provenance,
support or reconstruction uses exit 2 and no success object.

`validate-result` bounds bytes before strict decoding and checks canonical wire,
closed schema, supported identities, metrics/violations/status consistency and
supplied producer exit before emitting canonical bytes. Consumers then compare
every expected identity and all four metrics to independent invocation/evidence;
valid shape alone clears nothing. Actual-only projection must exactly match the
actual producer's candidate and four metrics for the same range/policy/name.

### Admission, conditional bootstrap and completion

Preferred admission inspected source `adf52bdba1e204a4945f811d9fea03c1836ddaa7`.
Reviewer `/root/admit_core233_source` confirmed graft and replacement-ref routes
adding a redundant parent while raw objects/range and actual metrics stayed fixed:
generic project/validate-result accepted rehashed two-edge ownership for a raw
one-parent commit; prerequisite and reconstruction checks also accepted it.
Canonical negative controls and bounded actual-only parity passed. The review
ended after a runtime interruption before full closure review/digest and final
independent source-fingerprint comparison. No admitted closure or policy is
claimed. **Admission is unavailable**; the approved conditional bootstrap applies
(D2), and no further pre-repair probe is required to authorize it.

Pinned report in the primary checkout:
`.superpowers/sdd/wt-worktree-issue-233-review-projection-core/2026-09-30-issue-233-review-projection-core/source-admission.md`,
raw SHA-256 `319a8abc5c57ce22e22f74064670a272aa4c85128bce6b1a5cfb8db96012b18a`.
Its observed artifact-policy identity is
`sha256:1348b74e61f4826edc7919873033fdcc36924823f912ba5d62a7ac83289df25c`;
packing-policy identity is
`sha256:00d86e10b8c5b777e7dbcd103ee1434576996396be77c20bdffd44a153decce5`.
These bind the negative evidence, not corrected-source admission.

Before product recovery, commit the full indexed design/plan/forecast and pass the
complete actual gate from the fixed child base. Forecast all recovery, correction,
tests, remaining publication, process/fix/shared-path effects and future subjects
honestly. Existing forecasts remain until supported scope-specific replacements
exist. This exception permits only shared actual/generic source recovery/correction
and necessary source tests. An essential VCS move includes only the minimum
references made stale by that move, in the same commit and forecast (D6); this
permits no new command publication, installed wiring or broader documentation.
Every task/fix still needs fresh independent review,
complete actual production and independent checking, with focused/full/applicable
build verification. Actual overflow stops immediately.

At the earliest corrected independently reviewed source commit, bind the entire
producer/projector/budget/canonical closure and policy identities and project the
entire already committed CORE plan, including remaining publication/tests/process.
Validate canonical stdout, independently match all identities/metrics and require
exit 0/within-budget before any work beyond this source boundary, installed
publication or final acceptance. Exit 2 or 3 stops; neither extends the exception.
Source changes require fresh review and projection; plan changes require a new
committed package and projection. A passing subrange or historical result cannot
clear a complete gate, and source admission itself never claims full-plan fit.

Publication adds both command-table launchers, removes the superseded legacy
mapping, repoints living documentation and verifies source/built policy and
behavior parity. Use the current isolated launcher that clears hostile Python/Nix
environment influence. Build only; never activate the host. At final head require
the fixed-base complete actual gate, exact actual-only projection parity, focused
tests, full `agent-workflow-tests`, managed `nix-build`, installed checks without
acceptance-by-skip, and separate authorship-independent final conformance and
correctness reviews of the complete delivery. Required CI status remains a merge
gate. All committed process work remains in review cost.

## Test seams

Use the existing source subprocess/pure packing seam and installed-layout seam;
no new private test substitute. Source commands run by package module under the
recipe environment. Temporary real Git repositories provide observable evidence;
independent actual producer/checker invocations verify complete packages.

| Contract | Required independent evidence |
|---|---|
| Actual/legacy and policy parity | Ordinary/detail/safe publication, empty/rename/binary/generated records, each cap and exact edge, all adaptive choices and initial fallback; hostile Git config; policy changes between description/check/validation; exact naming/four metrics and actual-only parity. |
| Strict plan/result and bounded forecasts | Complete indexed/committed linkage, canonical/malformed/unknown fields, uncommitted/symlink/path failures, ownership gaps/overlaps/order, undeclared product tail, wrong identities/exits, all actual/future substitutions, missing completed effects, larger actual wins, cumulative shared-path coverage and huge scalar bounds without proportional allocation. |
| Real standalone candidates | Separate disjoint-path and sequential shared-path positives, exact completed prerequisites, excluded unrelated effects, standalone tree/record/producer/checker equality; root overflow with fitting descendant, each tie-break separately decisive including order reversal, cheaper unrelated sibling excluded and no-fit null. |
| Invalid graphs and unsupported proof | Disconnected/root/parent/dependency cycles, invalid partitions/closure/process packages, wrong/null/tree-only prerequisites; paired dependent and independent shared-hunk refusals, split/context/relocation/merge and synthetic-composition refusals, complete edge evidence and no partial success. |
| Original history | Disposable graft adding a redundant non-parent while raw objects/range stay fixed; replacement refs, parent deletion/reordering, related shallow/environment virtualization and rehashed altered edges. Exercise generic project, edge and prerequisite/direct reconstruction boundaries; distinguish invalid provenance from honest refusal and verify unchanged source state. A fresh independent reviewer rechecks the correction at the pinned child commit. |
| Managed publication | Both built commands and external policy query/check contract, canonical valid/malformed inputs, real actual/project/validate parity under hostile `PYTHONPATH` and `NIX_PYTHON*`; use existing launcher tests and no shared fake installed state. |

## Out of scope

DERIVE owns retained contribution attribution/adapters, Task-7 model, fileless
Task 8, issue-100 provenance, authenticated derivation/witness/replay and full-shape
scratch acceptance. EVIDENCE owns the reviewed five-file publication and concrete
source/built replay. Preserve their complete parent requirements and findings.
CORE does not advertise retained replay. No caller adoption or lifecycle rollout,
broad helper migration, real retained registration/reconciliation, policy snapshot,
host activation, retained-state/ledger mutation or cleanup. General hunk proof,
inverse relocation and synthetic prerequisite composition remain unsupported.
No changed caps, hidden costs, forecast fiction or generated-exemption expansion.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Adopt [CORE 233](https://github.com/fagenorn/nix-config/issues/233) → [DERIVE 234](https://github.com/fagenorn/nix-config/issues/234) → [EVIDENCE 235](https://github.com/fagenorn/nix-config/issues/235), preserving the full parent disposition; CORE publishes complete actual/generic tools with its own immutable base/process/reviews. | User adoption on 2026-09-30; issue 233; parent decomposition P1/P2 and validated complete overflow. | Task-number split or inherited parent acceptance strands usable publication and bypasses complete gates. |
| D2 | Failed fresh admission selects the expressly authorized CORE-only shared-source bootstrap; the earliest corrected reviewed closure must pass the entire committed-plan projection before publication. | Issue 233 explicit conditional authority; independent generic graft reproduction; fixed child base. | Admit old Task-2 acceptance, extend bootstrap, or accept exit 2/3: original-parent authenticity or full-plan fit is unproved. |
| D3 | Retain one shared actual/packing path, external pinned policy and v3 ordered ownership/cumulative forecasts, including bounded symbolic subject/record measurement. | Accepted R1/R2; package standard; parent D1/D2/D7/D9/D10/D13/D14. | Private estimator, copied policy, lowered bounds or silent schema change breaks exact parity and honest coverage. |
| D4 | Authenticate raw original ordered parents once at the shared Git boundary and reuse that authority across ranges, edges, metadata tails, prerequisites and reconstruction. | Task-3 I1 plus fresh generic admission; defense in depth. | Traversal-only or rehashed-evidence checks authenticate the same attacker-controlled virtual ancestry. |
| D5 | Preserve exact whole-path proof and neutral unsupported outcomes; prove positive recommendations with independent real-Git fixtures and source/built command seams. | Parent D17/D18 and generic R3; issue 233; observable-test and YAGNI standards. | Infer semantic dependency, copy aggregate files, add speculative hunk composition or mock measured parity. |
| D6 | Include minimum stale-reference repairs in the same forecasted commit as an essential source move; defer command publication, installed wiring and broader documentation until the source gate. | The bar's move-history rule; authorized coherent CORE source recovery; owner clarification on 2026-09-30. | Break living references, duplicate the final producer or use the move to expand the bootstrap's publication authority. |

Design/grill frontier is closed within the approved scope. No context-map or ADR
write route exists in the retained project bindings; this ledger is the issue's
decision store. The full plan's authoritative measurement remains outstanding.
