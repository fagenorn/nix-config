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

The checker has one command:

```text
artifact-budget check \
  --kind <design-spec|implementation-plan|handoff|review-package> \
  --root <artifact-root-path> \
  [--policy <policy-path>] \
  --format json
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

A review package becomes a JSON manifest plus deterministic diff shards. For a root named
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

Producer reports add `state: complete | decompose_required | stopped | failed` and one `artifact`
object to their existing phase-specific fields. A successful report has exactly this budget shape:

```yaml
state: complete
artifact:
  kind: implementation-plan
  path: .claude/plans/2026-08-19-example.md
  metrics: {root_bytes: 12000, total_bytes: 84000, file_count: 5, largest_member_bytes: 21000}
  budget_status: within_budget
notes: <at most 500 characters>
```

The path is the artifact root; consumers discover members from the root rather than receiving a
potentially growing path list. Metrics use the four fixed non-negative integers returned by the
checker. Reports never include artifact contents, diff fragments, raw logs, policy copies, or the
spec's decision-ledger rows. Existing phase-specific fields such as ADR paths, verdicts, commit
ranges, and review scope remain, but they stay bounded by their existing schemas.

An over-budget report uses the same artifact object with `over_budget`, adds the checker's closed
violation codes, and uses the producer's terminal state from the table above. A failed measurement
uses `state: failed`, the root path when one exists, and no fabricated metrics or budget status. A
caller treats `state: complete` without `within_budget` and all four checker metrics as a contract
error. A caller never recomputes metrics from prose or trusts a producer's claim without the checker
result.

## Decisions

### Module and interface

The artifact-budget module owns policy loading, strict schema validation, package-member discovery,
byte measurement, aggregate calculation, closed violation classification, bounded JSON rendering,
and exit semantics. Producers
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
and `phase_reports.notes_max_characters: 500`. Each artifact entry contains positive integer
`root_max_bytes` and `aggregate_max_bytes`, plus non-negative integer `member_max_bytes` and
`max_members`. For one-file kinds both member values are zero. The checker rejects booleans,
fractions, negative values, unknown keys, missing kinds, inconsistent one-file limits, and aggregate
limits smaller than the root limit.

The 500-character notes rule remains in policy because it is part of the same repeated-artifact
cost model and already has repository evidence and precedent. The checker does not attempt to
measure an agent's transport message; workflow contract tests pin that every producer schema carries
the rule and the fixed artifact object.

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

The primary seam is the artifact-budget command. Table-driven tests invoke it with repository-owned
small and oversized issue fixture descriptors and temporary byte payloads. They assert exact-boundary success,
boundary-plus-one exit 3 and violation code, aggregate and member-count failures, deterministic JSON,
Unicode measured as encoded bytes, package-member auto-discovery, orphan/index/manifest mismatch and
unreadable-path rejection, unknown-policy fail-loud behavior, and that no over-budget result has a
successful status.

The second seam is the review-package command. A temporary Git fixture proves that a small range
produces one within-budget manifest, a multi-file oversized monolith becomes ordered bounded shards,
and a single-file oversize returns `decompose_required` without a success line or truncated coverage.
Tests inspect the manifest and reconstructed shard sequence, not implementation functions.

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
