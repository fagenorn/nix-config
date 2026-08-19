# Enforce budgets for issue-delivery artifacts

Issue: https://github.com/fagenorn/nix-config/issues/49

## Problem

Issue delivery produces four durable artifact types: design specifications, implementation plans,
handoffs, and review packages. The workflow already passes most of them by path, but nothing defines
how large the file behind that path may become. A producer can therefore finish successfully with an
artifact too large for its next reader, and each consuming skill has to improvise whether to read,
scope, summarize, or abandon it.

That gap is measurable in this repository. A sample of the 15 most recent design specs ranged from
13,555 to 51,862 bytes (median about 36.5 KiB). The 15 most recent plans ranged from 22,880 to
108,333 bytes. Where the task structure was machine-detectable, plan headers were about 6.2–13.2 KiB
and individual task sections reached about 37.3 KiB. Five live recent handoffs ranged from 1,707 to
6,654 bytes. Full review-package equivalents for eight recent merged branches ranged from 83,358 to
380,554 bytes.

Recent Claude-session evidence reinforces that the expensive surface is repeated context, not disk
storage. Thirty primary-repository transcripts modified during the sampled period reached 3,340,351
bytes, while repository history records that a phase report may be re-read about 87 times by its
caller. Transcript bytes are not used as artifact thresholds—they include protocol metadata—but they
support two existing invariants: detailed evidence stays on disk, and inter-agent results carry paths
plus compact summaries.

The repository needs one authoritative, machine-readable policy and one enforcement seam. Every
producer must measure after its last write and before it publishes success. Exceeding a limit must
lead through a producer-specific compact or split path and ultimately to a truthful stop; a missing
measurement is never permission to succeed.

## Solution

Add an artifact-budget module consisting of a versioned JSON policy and a Python standard-library
checker exposed at the same stable agent-tools location as the existing workflow helpers. Skills do
not carry threshold numbers. They invoke the checker and interpret its closed result states.

The checker has three stable commands:

```text
artifact-budget check \
  --kind <design-spec|implementation-plan|handoff|review-package> \
  --root <artifact-root-path> \
  [--policy <policy-path>] \
  --format json

artifact-budget validate-report \
  --boundary <producer|sdd|ship-handoff|ship-summary> \
  --input <path|-> \
  [--policy <policy-path>]

artifact-budget validate-detail-input \
  --input <path|-> \
  [--policy <policy-path>]
```

`--policy` exists for repository tests and pre-install development. Normal skill use omits it and
loads the repository-managed policy from its installed stable path. For a one-file kind the root is
the complete artifact. For a package kind the checker discovers every member in the root's required
sibling member directory; callers cannot omit a large member from the measurement. It rejects a
missing package directory, symlinks, subdirectories, unrecognized member names, and unreadable or
duplicate resolved paths, then emits exactly one versioned result. It exits 0 only for
`within_budget`, 3 for a valid measurement that is `over_budget`, and 2 for an invocation, policy,
package-shape, schema, or I/O error. Exit 2 is a failed measurement and must fail the producer; it
never degrades to `unmeasured` success.

Phase reports are canonical UTF-8 JSON objects, never Markdown/YAML or prose wrappers.
`validate-report` reads exactly one JSON object from a non-symlink regular file or stdin (`-`),
rejects duplicate keys, non-standard constants, malformed UTF-8, trailing non-whitespace, and the
selected boundary's closed schema, then emits the same semantic object as key-sorted compact UTF-8
JSON plus one newline. Success is stdout only and exit 0. Every parse, schema, invocation, or I/O
failure emits no stdout, exactly one stable class diagnostic on stderr, and exit 2. Producers write
a sibling temporary candidate, invoke this command, and transport only its validated stdout bytes;
callers run received bytes back through the same command before trusting them. The shared policy's
`phase_reports.wire_max_bytes` bounds both bytes read and canonical bytes emitted, so no fixed-shape
string field can make the transport unbounded.

`validate-detail-input` reads one no-follow regular file or stdin and requires exactly
`{"interface_version":1,"findings":[...]}` with a non-empty array and D15's exact finding
fields, types, enums, and parked-ruling rule. Success emits canonical compact JSON plus newline and
exit 0. Missing/unreadable input emits no stdout, `artifact-budget: cannot read detail input\n`,
exit 2; empty/malformed/wrong-schema input emits no stdout,
`artifact-budget: invalid detail input\n`, exit 2.

The result is a bounded shape:

```json
{
  "interface_version": 1,
  "kind": "implementation-plan",
  "status": "within_budget",
  "metrics": {
    "root_bytes": 12000,
    "total_bytes": 84000,
    "file_count": 5,
    "largest_member_bytes": 21000
  },
  "violations": []
}
```

`violations` is a sorted subset of the four closed codes `root_bytes`, `member_bytes`,
`member_count`, and `aggregate_bytes`; it never contains prose or one entry per file. Unknown policy
versions, artifact kinds, policy fields, result fields, or violation codes fail loudly.

### Initial policy

All byte values are exact bytes; KiB below means 1,024 bytes. `root` is the path handed to the next
phase. A member is content named by that root and read independently by a consumer.

| Artifact kind | Root limit | Member limit | Member count | Aggregate limit | Successful root shape |
|---|---:|---:|---:|---:|---|
| Design spec | 65,536 (64 KiB) | none | 0 | 65,536 | One Markdown spec containing the decision ledger |
| Implementation plan | 16,384 (16 KiB) | 49,152 (48 KiB) | 8 | 131,072 (128 KiB) | Markdown index naming task-member files |
| Handoff | 8,192 (8 KiB) | none | 0 | 8,192 | One Markdown handoff |
| Review package | 16,384 (16 KiB) | 65,536 (64 KiB) | 8 | 524,288 (512 KiB) | Versioned manifest naming diff shards |

The limits are rounded binary ceilings above the observed normal range rather than arbitrary prose
limits. The spec and handoff ceilings are respectively about 26% and 23% above their observed maxima.
The plan root, task-member, and aggregate ceilings are about 24%, 29%, and 21% above the observed
header, task, and total maxima; eight members cover the observed maximum of seven tasks. The review
aggregate ceiling is about 38% above the observed maximum, while 64 KiB shards put a hard bound on
one diff read. The 16 KiB manifest ceiling follows the already-observed plan-index/header envelope.

These are initial repository policy values, not runtime model/token budgets. Future threshold changes
edit the policy with new evidence and tests; they do not require editing producer prose.

### Artifact shapes

The design spec remains one file. Its `## Decision ledger` remains the only rationale store. Evidence,
examples, and repeated constraints may be compacted or replaced with stable references, but ledger
rows are consolidated only when their meaning remains intact and are never copied into plan members.

An implementation plan becomes a package. Its root is a thin index containing the goal,
architecture, global constraints, test seams, task index, decision-ID citations, and links to the
task members. For a root named `<stem>.md`, members are the contiguous regular files
`<stem>.tasks/task-1.md` through `task-N.md`; no other directory entry is allowed. The checker
enumerates that directory rather than trusting a caller-supplied list. The index must reference every
member exactly once, and may reference no task outside that directory. Each task member carries the
exact files, interfaces, invariants, failing tests,
implementation steps, verification gate, and commit scope for that task. Shared constraints and
rationale remain behind root/spec references; task-specific values remain in the member so an
implementer does not need another task. The task-brief adapter resolves the indexed member and writes
the same bounded brief shape used today. The plan path in all public workflow contracts continues to
mean the root index.

A handoff remains one file. It references specs, plans, commits, workflow state, and reports rather
than duplicating them. For a durable destination, budget enforcement happens on the fully written
sibling temporary file before the existing atomic install/replace step, so an oversized handoff is
never published as a valid durable resume point.

A review package becomes a purpose-discriminated JSON manifest plus deterministic shards. For a
`diff-review` root named
`<stem>.json`, shards are contiguous regular files named
`<stem>.shards/shard-001.diff` through `shard-NNN.diff`; no other directory entry is allowed. The
generator treats Git's diff as a byte stream and groups complete file diffs
in emitted order until adding the next file would exceed the member limit. It never reorders files,
decodes patch bytes to split them, or splits a file diff silently. The versioned manifest records the
range, commit/stat summary, ordered generated shard paths, actual per-shard bytes, total bytes, and
coverage; it must reference every shard exactly once and no file outside the sibling directory. The
checker enumerates the directory and rejects a manifest/member mismatch. If one complete file diff
exceeds the member limit, or the member-count/aggregate limit would be exceeded, generation returns
`decompose_required`; it does not emit a successful partial package. Task and final reviewers receive
the manifest path and compact package metrics, never an inlined diff or shard list. Review rubrics
read the manifest and its shards in manifest order and must report unreadable shards explicitly.
Every manifest integer rejects booleans. Git numstat `-` for a binary file contributes zero to both
the insertion and deletion totals, matching the existing `diff-scope` convention, while the file
still contributes to `files_changed` and its complete binary patch remains in the diff stream.

The `delivery-detail` review-package variant stores SDD parked/residual findings and ship-review
Minor/Discussion detail without transporting a growing list. Its strict root has exactly
`interface_version`, `kind: "review-package"`, `purpose: "delivery-detail"`, `context` (exactly
`issue`, `branch`, `producer: "sdd" | "ship-review"`), ordered `shards`,
`total_detail_bytes`, and `coverage` (exactly `complete: true` and `finding_count`). Members are
contiguous `shard-NNN.jsonl`; each line is one canonical JSON finding with exact `axis`, `severity`,
`status`, `text`, and nullable `ruling`. `axis` is `conformance | correctness | ship`, severity is
`Critical | Important | Minor | Blocking | Should-fix | Discussion`, and status is
`parked | residual | discussion | minor`; text is non-empty and ruling is required for `parked`.
Whole finding records are greedily grouped without splitting.
It uses the same review-package root/member/count/aggregate ceilings; the policy contains no second
copy of those numbers. The checker selects the exact manifest/member schema from `purpose`.

Delivery-detail roots live under the primary checkout, never the removable feature worktree or
protected Git metadata: `<main-root>/.superpowers/issue-delivery/<issue>/<run-or-branch>/<producer>-<head>.json`.
The delivery-detail producer independently derives `<main-root>` as the parent of absolute
`git rev-parse --git-common-dir`,
requires that common directory's basename to be `.git`, confirms the parent with
`git -C <main-root> rev-parse --show-toplevel`, and validates every existing report-home parent as a
non-symlink directory. It accepts a positive issue, valid branch, optional run ID, producer, and full
head SHA—not destination authority—and derives the exact issue/run-or-hashed-branch and
per-producer/head leaf itself. An optional asserted output is accepted only when it equals that exact
derived absolute path. Before publication it exclusively creates or validates no-follow
`<main-root>/.superpowers/issue-delivery/.gitignore` with exact bytes `*\n`; any conflicting type or
content fails. Issue is a non-boolean positive integer; producer is the closed two-value enum; head
is a full lowercase object SHA; branch must pass Git ref validation and equal the linked worktree's
current branch; an explicit run ID matches `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`, while absent identity
is exactly `branch-<lowercase SHA-256 of UTF-8 branch>`. Traversal, a symlink parent, malformed or
mismatched identity, `.git`, outside-root, and feature-worktree destinations fail before publication.
It returns a primary-root-relative `report_path`. SDD finalizes this package before deleting its
per-plan workspace; ship review finalizes it before Phase 8 cleanup. A consumer rechecks the package
and reads it before cleanup/terminal persistence. When findings exist, `report_path` is required and
bounded notes include that exact path; `null` is allowed only when there is genuinely no detail.
Failure to durably publish and validate required detail makes the phase `stopped`/`failed` and keeps
the worktree; detail is never force-emptied to satisfy the transport schema. Before publication,
the caller writes the exact detail input to a bounded repository-relative retained-candidate path
beneath the live feature worktree's `.superpowers/` workspace. If publication fails with a non-empty
collection, `detail_state: unpublished` points to that still-readable candidate, bounded notes name
the same path, and cleanup/worktree removal is forbidden. SDD/from-issue and ship/workflow-state
pass the no-follow file through `validate-detail-input` and compare/consume canonical stdout bytes;
mere readability never permits acceptance or persistence. It never claims a durable review package.

Both variants generate under a unique sibling staging directory and are fully shape-validated and
measured there before publication. Publication has no check-then-rename window: exclusively create
the final member directory, exclusively hard-link each staged member into it, and exclusively
hard-link the staged manifest last. Any destination that appears concurrently makes that mutation
fail without replacement. Cleanup unlinks only entries whose device/inode identity still matches
this invocation's staged file and removes its member directory only when empty and still at the
identity recorded immediately after its exclusive creation. Symlink,
non-regular, cross-device, and existing-path cases fail closed. A successful run leaves no staging
entry or orphan member; a failed retry or injected race preserves every competitor byte-identically.

### Producer behavior and timing

Measurement is valid only after the producer's last content mutation. Any later append, review fix,
or ledger row makes prior metrics stale and transfers remeasurement responsibility to that writer.
In particular, planning and Phase 5 must recheck the spec when they append or consolidate decision
rows, as well as checking the plan they produce or amend.

Every producer follows the applicable sequence exactly:

| Producer | First over-budget action | Second action | Terminal behavior |
|---|---|---|---|
| Design/grill | Compact repetition, examples, and evidence references without weakening required sections or ledger meaning; remeasure | If it still exceeds policy, identify independent deliverables as proposed decomposition without silently narrowing the issue | Return `decompose_required` with draft path, metrics, and violation codes; do not call it approved or complete |
| Planning | Emit the index-plus-task package; compact repetition into root/spec references and remeasure all members | Split a task only where both results are independently testable; if count/aggregate still exceeds policy, require issue decomposition | Return `decompose_required`; do not dispatch SDD or report plan completion |
| Handoff | Rewrite once to remove duplicated artifact, lifecycle, diff, and log content; remeasure before publication | None—the handoff is already a summary | Return `stopped` with candidate path and metrics; do not install a durable resume point or call the handoff ready |
| Review package | Generate manifest and file-boundary shards, then measure the complete package | None—a file diff is not safely summarized or truncated by the packaging tool | Return `decompose_required` and exit 3; reviewers are not dispatched and no axis may report clean |

A producer may take several editing passes inside its named compact/split action, but it may not loop
between strategies or invent a larger limit. The state transition is deterministic: generate →
measure → named remediation → remeasure → success or the named truthful stop. Existing task/issue
decomposition checkpoints decide what work resumes; this policy does not create a retry budget.

### Phase and agent result contract

Producer reports use exactly three top-level fields: `state`, `artifact`, and `notes`. A successful
report has exactly this JSON shape:

```json
{"artifact":{"budget_status":"within_budget","kind":"implementation-plan","metrics":{"file_count":5,"largest_member_bytes":21000,"root_bytes":12000,"total_bytes":84000},"path":".claude/plans/2026-08-19-example.md"},"notes":"validated","state":"complete"}
```

The path is the artifact root; consumers discover members from the root rather than receiving a
potentially growing path list. Metrics use the four fixed non-negative integers returned by the
checker. Reports never include artifact contents, diff fragments, raw logs, policy copies, the
spec's decision-ledger rows, ADR-path lists, decision lists, open-item lists, member lists, or
free-form summaries. Those details remain behind the artifact root, spec ledger, or workflow's
existing durable ledger. No producer-specific extra key is accepted. The only free text is `notes`,
whose maximum comes from `phase_reports.notes_max_characters` in the shared policy.

An over-budget report uses the same artifact object with `over_budget`, adds the checker's closed
violation codes, and uses the producer's terminal state from the table above. A failed measurement
uses `state: failed`, the root path when one exists, and no fabricated metrics or budget status. A
caller treats `state: complete` without `within_budget` and all four checker metrics as a contract
error. A caller never recomputes metrics from prose or trusts a producer's claim without the checker
result.

Cross-phase and ship handoffs carry fixed scalar lifecycle fields, current artifact root/metrics,
and policy-bounded `notes`; they do not restore removed lists under a new name. The Phase-7
one-paragraph summary becomes `notes`. The legacy terminal lifecycle field `discussion_items`
remains for schema compatibility but is always the empty list; Discussion/Minor detail stays in its
durable package or readable retained candidate and only its bounded path plus notes travels.

The shared module validates these exhaustive state matrices (`full` means exact
`kind,path,metrics,budget_status`; `over` additionally requires non-empty closed `violations`;
`root-only` means exact `kind,path`; `—` means JSON `null`):

| Producer row | `state` | `artifact` | Required combination |
|---|---|---|---|
| complete | `complete` | full | any core kind, `within_budget`, no `violations` |
| design over | `decompose_required` | over | `design-spec`, `over_budget` |
| plan over | `decompose_required` | over | `implementation-plan`, `over_budget` |
| review over | `decompose_required` | over | `review-package`, `over_budget` |
| handoff over | `stopped` | over | `handoff`, `over_budget` |
| failed before root | `failed` | — | no artifact fields |
| failed after root | `failed` | root-only | metrics/status/violations forbidden |

| SDD row | `state` / `review_state` | axis verdicts | verification | SHAs | `report_path` |
|---|---|---|---|---|---|
| clean | `complete` / `clean` | both `clean` | `passed` | both full lowercase object IDs | `detail_state: none` + null, or `present` + durable path |
| residuals | `residuals` / `residuals` | each `clean|findings`, at least one `findings` | `passed|failed` | both full IDs | `detail_state: present`; required durable path |
| failed before range | `failed` / `unknown` | both `not_run` | `not_run` | both null | `detail_state: none`; null path |
| failed after range, no detail | `failed` / `unknown` | each `not_run|clean`, not the clean-success tuple | `passed|failed` | both full IDs | `detail_state: none`; null path |
| failed after range, detail | `failed` / `unknown` | each `not_run|clean|findings`, not the clean-success tuple | `passed|failed` | both full IDs | `detail_state: present`; required durable path |
| failed after range, unpublished detail | `failed` / `unknown` | at least one `findings` | `passed|failed` | both full IDs | `detail_state: unpublished`; required retained-candidate path |

SDD top-level keys are exactly `state`, `review_state`, `conformance_verdict`,
`correctness_verdict`, `verification_state`, `base_sha`, `head_sha`, `detail_state`, `report_path`,
and `notes`. Every SDD row requires `detail_state: none | present | unpublished`: `none` requires a
null path, `present` requires the normalized primary-root-relative durable-package path, and
`unpublished` requires a normalized repository-relative `.superpowers/` retained-candidate path in
the live workspace. `unpublished` is valid only with `state: failed` and a `findings` verdict.

| Ship-handoff row | `state` | artifacts/head | review/detail |
|---|---|---|---|
| complete | `complete` | both full within-budget artifacts; full `head_sha` | closed `review_state`; durable `report_path` when SDD detail exists |
| failed before artifacts | `failed` | both artifacts and `head_sha` null | `review_state: unknown`; path null unless detail was durably published |
| failed after artifacts | `failed` | both full artifacts and full `head_sha` | closed review state; durable path required when detail exists |

Ship-handoff keys are exactly `state`, the five all-null-or-all-present lifecycle fields
`ledger_repo_root,run_id,attempt,owner,owner_worktree`, then `issue_number,branch,worktree_path`,
`spec_artifact,plan_artifact,head_sha,review_state,auto,report_path,notes`. Booleans never satisfy
integer fields.

| Ship-summary row | `state` | `pr_url` | `merge_sha` | `issue_closed` | detail |
|---|---|---|---|---|---|
| merged | `merged` | required URL | full object ID | `true` | `none`/null or `present`/durable path |
| stopped | `stopped` | URL or null | null | `false` | `none`/null, `present`/durable path, or `unpublished`/retained path |
| failed | `failed` | URL or null | null | `false` | `none`/null, `present`/durable path, or `unpublished`/retained path |

Ship-summary keys are exactly `issue,state,pr_url,merge_sha,issue_closed,discussion_items,detail_state,report_path,notes`.
`discussion_items` is always `[]`; for `unpublished`, emptiness means the retained candidate and
notes preserve the non-empty detail, not that it was discarded. Every non-null path appears in notes.
All notes use the one shared-policy character limit. Unknown fields, missing fields, legacy lists,
unlisted enum combinations, or independently nullable paired fields are contract errors.

## Decisions

### Module and interface

The artifact-budget module owns policy loading, strict schema validation, package-member discovery,
byte measurement, aggregate calculation, closed violation classification, bounded JSON rendering,
producer-report, SDD-report, ship-handoff, and ship-summary validation, and exit semantics. Producers
own content-specific compaction and package construction because only they know what text can be
removed or which tasks/diffs can be split safely. Consumers know only the root path, metrics, and
terminal state.

This gives the module depth: deleting it would scatter the same thresholds, arithmetic, closed result
states, and fail-closed rules across at least four skills and one shell generator. The interface is
small enough to exercise directly from tests and does not expose policy-parsing internals.

Two viable designs were considered:

1. A shared policy plus the checker and package shapes selected above. It centralizes knowledge,
   makes success mechanically falsifiable, and lets each producer retain semantic control.
2. A shared policy document with each skill running `wc -c` and applying its own comparisons. This
   is viable for one-file artifacts, but aggregate/member arithmetic, exit meanings, result schemas,
   and validation would still be duplicated and could drift.

A runtime/token-budget gate was not a competing design: token counts vary by model and transport and
are expressly outside this issue. Exact file bytes are portable, available before dispatch, and
stable for identical content.

### Policy schema

Policy version 1 is a strict object with `schema_version`, `unit: "bytes"`, a closed `artifacts` map,
and exact `phase_reports` integers `notes_max_characters: 500` and `wire_max_bytes: 8192`. Each artifact entry contains positive integer
`root_max_bytes` and `aggregate_max_bytes`, plus non-negative integer `member_max_bytes` and
`max_members`. For one-file kinds both member values are zero. The checker rejects booleans,
fractions, negative values, unknown keys, missing kinds, inconsistent one-file limits, and aggregate
limits smaller than the root limit.

The 500-character notes rule remains in policy because it is part of the same repeated-artifact
cost model and already has repository evidence and precedent. The module validates the exact
producer-report object and rejects extra legacy list/summary fields or notes beyond the policy value;
it does not attempt to estimate transport tokens.

### Compatibility and publication

Newly produced plans and review packages use their package shapes immediately. Historical committed
plans and transient review files are evidence, not data to migrate. No compatibility mode, automatic
rewriter, or schema negotiation is added. A resumed old workflow must finish with its original tool
generation or be replanned under the new contract; silently interpreting a monolith as a new package
would bypass member limits.

Policy and helper publication follow the repository's existing agent-tools mechanism. A build makes
both available at stable installed paths, and source-tree tests pass the repository policy explicitly.
The implementation does not alter model selection, runtime context limits, phase attempt counts,
diff-scope product gates, or CI wiring.

## Test seams

The primary seam is the artifact-budget command. Table-driven tests materialize every repository-owned
small and oversized issue fixture descriptor into temporary byte payloads and invoke the CLI. They assert exact-boundary success,
boundary-plus-one exit 3 and violation code, aggregate and member-count failures, deterministic JSON,
Unicode measured as encoded bytes, package-member auto-discovery, orphan/index/manifest mismatch and
unreadable-path rejection, unknown-policy fail-loud behavior, exact fixture metrics/status/exit code,
canonical violations, and that no over-budget result has a successful status. Descriptor metadata is
never accepted as its own proof.

The second seam is the review-package command. A temporary Git fixture proves that a small range
produces one within-budget manifest, a multi-file oversized monolith becomes ordered bounded shards,
and a single-file oversize returns `decompose_required` without a success line or truncated coverage.
A binary range proves zero insertion/deletion aggregation, malformed manifests prove booleans are not
integers, a refused retry preserves a prior package byte-for-byte, and successful first publication
leaves no staging entries or orphan shards. Tests inspect the manifest and reconstructed shard
sequence, not implementation functions.

The highest workflow seam remains `just agent-workflow-tests`. Contract fixtures represent one normal
small issue and one oversized issue. They pin that design, planning, handoff, review, and later writers
invoke measurement after their final mutation; success reports contain only root paths and fixed
metrics; over-budget reports use the required truthful terminal state; plan tasks stay self-contained
through the indexed task member; and no dispatch receives inlined artifact contents. The oversized
fixture is generated from compact repetition metadata rather than committing hundreds of kilobytes of
padding.

`just build` is the publication seam: it proves the policy and executable checker are installed with
the shared agent skills. Eval scenarios may demonstrate the prose behavior locally, but adding the
workflow suite to CI remains issue 37 and is not part of this change.

Concrete grill scenarios that must remain green:

- A spec at exactly 65,536 bytes succeeds; appending one decision row invalidates its prior metrics
  and forces remeasurement.
- A plan with eight valid task members succeeds; a ninth member stops even when aggregate bytes are
  small.
- A task member at 49,153 bytes is over budget even when the package aggregate is below 128 KiB.
- A durable handoff candidate is measured before atomic replacement, so a valid old handoff survives
  an oversized replacement attempt.
- A review range whose one file diff exceeds 64 KiB stops rather than truncating or claiming partial
  coverage.
- A missing installed helper, malformed policy, or unreadable member never becomes `unmeasured`
  success.
- A producer report containing `state: complete` with `budget_status: over_budget` is rejected as a
  contract error by its caller.

## Out of scope

- Model token windows, model selection, turn counts, session compaction, runtime attempt/time budgets,
  and orchestration retry policy.
- General product diff-size or degradation gates, including changing the 20-file correctness scope.
- Adding workflow tests to CI, which remains tracked by issue 37.
- Migrating or rewriting historical specs, plans, handoffs, review packages, or Claude transcripts.
- A generic document compressor, semantic summarizer, tokenizer, or automatic issue creator.
- Budgeting implementation diffs, source files, test output, PR bodies, changelogs, research reports,
  or context/glossary documents.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Enforce exact encoded bytes through one strict artifact-budget module that discovers package members from the root; use shape metrics only as bounded report context | Issue 49 requires one measurable repository-owned policy; the coding bar requires DRY knowledge, defense in depth, fail-loud closed sets, and truthful terminal states | Per-skill `wc -c` checks or caller-supplied member lists are workable but duplicate semantics or let a buggy caller omit a large member; token estimates are unstable and out of scope |
| D2 | Set initial ceilings at 64 KiB spec, 16 KiB plan root + eight 48 KiB tasks/128 KiB aggregate, 8 KiB handoff, and 16 KiB review manifest + eight 64 KiB shards/512 KiB aggregate | Measured recent ranges were 51,862-byte specs, 13.2 KiB plan headers, 37.3 KiB task sections, 108,333-byte plans, 6,654-byte handoffs, and 380,554-byte review equivalents; binary rounding leaves 21–38% headroom | Cap every artifact as one file at the observed maximum, which preserves today's monolithic context sink and gives plans/reviews no bounded read unit |
| D3 | Make plans thin indexes plus self-contained task members, while keeping shared constraints and decision rationale behind root/spec references | Issue 49 preserves self-contained task contracts and a single spec ledger; SDD already consumes only the plan header plus current task brief | Duplicate global constraints and ledger rationale into every member, which spends aggregate budget and creates drift; keep monolithic plans, which leaves individual reads unbounded |
| D4 | Make review packages manifests plus ordered whole-file diff shards and stop when a single file or complete package cannot fit | Current packages are unconditional full-range diffs up to 380,554 bytes; tests and reviewers require truthful coverage, and truncating a file would hide evidence | Split arbitrary bytes/hunks or silently omit oversized files, which produces unreadable/partial evidence that can still look clean; keep one full diff, which has no bounded read |
| D5 | Measure after the final mutation and make every later writer remeasure; follow one producer-specific remediation then return a truthful stop | Issue 49 says a producer cannot report success over threshold; the coding bar says status surfaces are truth, and planning/review can append to the spec after design measured it | Measure only at artifact creation or allow an `unmeasured` success fallback, either of which lets stale or absent evidence authorize completion |
| D6 | Pass one root path plus four integer metrics and ≤500-character notes; consumers discover members from the root and never receive artifact contents | Existing payload discipline keeps details on disk, existing phase schemas cap notes at 500 characters, and history measured about 87 re-reads of a report | Return member lists, policy copies, ledger rows, or excerpts inline, which makes report cost grow with the artifact and duplicates authoritative sources |
| D7 | Test the checker CLI and review-package CLI with small/oversized fixtures, then pin producer/caller contracts at the existing workflow suite and build seams | The coding bar requires tests at observable interfaces and fixtures shaped like production; issue 49 explicitly requires normal-small and oversized truthful-terminal demonstrations | Test helper internals or prose presence alone, which can stay green while the executable exit state, package coverage, or caller rejection is wrong |
| D8 | Freeze machine-readable package references and shared policy discovery: each plan Task-index row ends in exactly one Markdown link to its convention-named task member; review manifests use the strict version-1 `interface_version`, `kind`, `range`, `commits`, `stat`, `shards`, `total_diff_bytes`, and `coverage` fields; install the one Python budget module at both `~/.agents/bin/artifact-budget` and importable `~/.agents/lib/python/artifact_budget.py`, with its default policy at `~/.agents/share/artifact-budget-policy.json` | The checker must prove root/member agreement without trusting caller lists, `task-brief` must resolve one member deterministically, and `review-package` needs the authoritative member ceiling before it can group whole-file diffs; the repository already publishes stable agent tools through Home Manager, while an importable copy lets the generator reuse policy loading and checks rather than restating them | Infer arbitrary Markdown links or accept an extensible manifest, which makes membership ambiguous; let the generator parse policy independently or duplicate the 64 KiB ceiling, which splits D1's authority; place the policy beside repository source, which is absent in consumer projects |
| D9 | Preserve the existing 20-product-file correctness scope when the full-range review package is larger than that gate: conformance and every unscoped reviewer read the manifest and shards in order, while a scoped correctness packet receives the manifest root and metrics only as truthful range-coverage evidence and fetches exactly the selected file diffs instead of reading its shards | Issue 49 explicitly excludes changing the product diff-size gate, while D4/D6 require a bounded root-and-metrics handoff and truthful full-range coverage; keeping the full package visible but its shards out of the scoped correctness evidence preserves both contracts | Give the scoped reviewer all full-range shards, which silently defeats the existing 20-file scope; omit the manifest and metrics, which breaks the new review-package handoff contract |
| D10 | Expand an implementation-plan root to its checker-validated task members only at ship time when supplying process-artifact exclusions to `diff-scope`; all public workflow handoffs continue to carry the root and metrics only | D3 makes task members committed process artifacts, D6 forbids growing public member lists, and the existing product-size gate requires every process artifact written by the run to be excluded explicitly | Pass only the root, which miscounts task members as product changes; pass member lists through every phase report, which makes report size grow with package shape; change `diff-scope`'s product gate, which is out of scope |
| D11 | Replace producer-specific report fields with the exact `state` + one root `artifact` + policy-bounded `notes` envelope; cross-phase and ship handoffs use fixed scalars/root metrics plus the same bounded notes, and legacy terminal `discussion_items` is always empty | Phase-5 review B1 verified that live `decisions`, `open_items`, `adr_paths`, and the Phase-7 paragraph summary are unbounded despite the spec's former claim; D6 already makes the artifact and durable ledgers authoritative | Add per-list count/item limits, which introduces more repeated numeric policy and still grows transport with artifact complexity; retain the lists because they are “existing,” which leaves the acceptance gap intact |
| D12 | Refuse a review-package retry when its regular root or member directory already exists; generate in sibling staging, validate completely, publish members then manifest, and clean only newly published members if final publication fails | Phase-5 review S2 found that range-derived names collide on resume and stale shards can corrupt discovery; refusal is deterministic, preserves valid prior evidence byte-for-byte, and avoids pretending two filesystem renames are one atomic package swap | Overwrite in place, which can destroy a valid package or leave stale shards; multi-path replacement with rollback, which adds concurrency/state machinery for transient evidence when safe refusal suffices |
| D13 | Make small/oversized descriptors executable test inputs, reject booleans for every policy/result/manifest integer, and count Git binary numstat `-` as zero insertions/deletions while retaining full binary diff bytes | Phase-5 review S1/S3 found static fixture self-assertion and Python's `bool`/`int` overlap; `diff-scope` already defines binary rows as zero churn, so matching it keeps one repository meaning | Treat descriptor expectations as proof, which cannot catch mismatched payloads; accept booleans through `isinstance(int)` or invent a different binary-stat convention, both of which create silent schema/accounting drift |
| D14 | Make every phase/report boundary canonical JSON validated through shared CLI operations, with exhaustive state schemas, one versioned detail-input validator, an 8 KiB shared-policy report ceiling, and candidate-file → validated-stdout transport | Reviews through closure CL-B1 found unnamed combinations drift and mere readability cannot prove retained detail is the promised non-empty collection | Let each skill duplicate schemas or accept arbitrary readable retained bytes |
| D15 | Extend D8 with a `delivery-detail` variant under the same ceilings; derive the ignored primary destination; on failure retain and shared-validate the exact source before forbidding cleanup; transport one relative `report_path` | Reviews through closure CL-B1 showed success needs durable detail while failure needs schema-valid inspectable source without claiming publication | Force-empty detail, duplicate its schema in consumers, or remove the only retained candidate |
| D16 | Replace D12's precheck-plus-rename publication with exclusive final-directory creation and identity-tracked exclusive hard links for members and manifest, manifest last | Re-review R-B4 identified a same-plan concurrency window where ordinary rename replaces a competitor; mutation-point exclusion plus inode-checked cleanup provides the no-clobber guarantee directly | Rely on an existence precheck or ordinary rename, both of which race; lock globally, which adds stale-lock recovery and broader coordination state for a leaf-local property |
