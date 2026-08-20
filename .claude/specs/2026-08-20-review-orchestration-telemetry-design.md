# Truthful review and orchestration telemetry

Issue: https://github.com/fagenorn/nix-config/issues/48

## Problem

Two reporting paths erase distinctions that operators rely on.

The detached Codex transport launches both plan and diff reviews through the same reviewer mode, but the companion runtime currently writes every such job as `plan-review`. A diff review therefore becomes indistinguishable from a plan review in the durable job record and every surface derived from it. Cleanup, cancellation, worker-death reconciliation, and SessionEnd handling also recognize the literal plan-review kind instead of the common review class. Extending those branches independently for diff review would preserve the label while duplicating one lifecycle.

The cost report has the inverse problem: it keeps distinctions in transcript files but erases them during grouping. It assigns a root session and all subagent transcripts from the root transcript's cwd set. A dispatcher that owns several issues consequently absorbs the issue-owner work that actually ran in separate issue worktrees. Constructing a process pool is also unconditional, so an environment that denies multiprocessing semaphores raises `PermissionError` before a report can be produced even though sequential scanning has identical semantics.

The result must be truthful without changing the accounting model: plan and diff reviews remain different operations under one review lifecycle; issue-owner work follows the owner transcript's actual worktree; dispatcher and non-owner work remains explicit multi-issue overhead; and parallelism may degrade without changing ordered scan values or aggregate turns, tokens, and estimated cost.

## Solution

Make review operation an explicit closed-set value at the transport boundary. The collaboration caller supplies a two-line envelope consisting of the worktree root and `REVIEW_OPERATION: plan-review | diff-review`. The bridge validates that declaration and invokes the existing task command with `--reviewer <operation>`. The CLI validates the same two values again, persists the value as the job `kind` and request review kind, and keeps `jobClass: review`. Invalid, absent, or ambiguous operation values fail before launch. No second review command, worker, state schema, or lifecycle implementation is introduced.

Use the common review class for shared job behavior. Operation kind remains visible in launch payloads, stored records, kind labels, status output, result output/JSON, and operation-specific titles. The human result renderer adds an operation header for these transport reviews and leaves the stored raw output unchanged beneath it; the bridge continues extracting the raw field from JSON. Cancellation, liveness reconciliation, reviewer-runtime cleanup, SessionEnd terminalization and cleanup, and retention continue through their existing generic branches, with no plan-review/diff-review switch. Existing active/terminal status predicates remain authoritative. A legacy plan-review record already carries the common class and therefore continues to follow the same behavior without migration.

Change cost grouping from session-only attribution to ordered transcript attribution. Each scan result retains the transcript's agent identity and cwd evidence. A subagent transcript is issue-owner work only when its agent identity matches the orchestrator's `issue-<number>-owner-<attempt>` convention and its own cwd evidence resolves to exactly one issue worktree for the same number. That transcript's complete additive telemetry is assigned once to that issue. Arbitrary helpers, native reviewers, Codex transport reviewers, ambiguous owner transcripts, and every root transcript stay with the root session group. When a session contains proven owners for more than one issue, that root group is explicitly `(multi-issue)` regardless of incidental root cwd changes.

Preserve review-operation evidence on Codex transport transcripts. The scanner recognizes the initial sidechain envelope's exact `REVIEW_OPERATION: plan-review | diff-review` field and qualifies that transcript's existing `codex-collaboration` skill attribution as `codex-collaboration/plan-review` or `codex-collaboration/diff-review`. The existing “turns by skill attribution” output can then show both operations; there is no inferred review result, new price dimension, or speculative telemetry schema.

Wrap process-pool use in one ordered scanning boundary. It attempts to materialize the entire mapped result list before any result is accumulated. Any ordinary exception during pool construction, mapping, iteration, or pool teardown discards that unconsumed attempt, emits one concise stderr disclosure, and rescans every path sequentially in the original job order. Sequential exceptions retain their normal failure behavior. This makes pool unavailability a performance degradation, not a correctness degradation, and prevents partial parallel values from being counted before the retry.

Compute report totals once from the ordered scan-result sequence before grouping. Integer totals are folded directly and cost uses one stable ordered fold; the report does not reconstruct global cost from the newly partitioned group subtotals. This makes the “unchanged totals” claim independent of group partitioning and floating-point reassociation.

The synthetic acceptance demo is one root dispatcher transcript, two named issue-owner transcripts in different issue worktrees, one unrelated helper, one plan-review transport, and one diff-review transport. It proves separate issue rows, explicit multi-issue overhead, separate operation attributions, one assignment per transcript, unchanged aggregate turns/tokens/cost, and byte-equivalent stdout values when the pool boundary is forced to fall back.

## Decisions

### Review operation contract

The transport envelope's first two lines are exactly `WORKTREE_ROOT: <absolute path>` and `REVIEW_OPERATION: <operation>`; the packet follows those lines unchanged. The task CLI makes the existing `--reviewer` option value-bearing. The only accepted values are `plan-review` and `diff-review`; there is no boolean compatibility form and no separate `--review-kind` option. The bridge checks one and only one operation declaration before launching, while the CLI independently checks the value before constructing or persisting a job. The persisted request carries the operation value rather than a redundant reviewer boolean, and the worker revalidates it before reviewer execution derives isolation, read-only enforcement, the timeout default, and no-thread-persistence.

The job record stores the operation in `kind` and the lifecycle family in `jobClass`. The kind label and title are derived from the operation so human status output does not collapse it to “review.” JSON launch, status, and result payloads expose the same persisted value. Human result output identifies the operation before the unchanged reviewer body. The bridge still returns the reviewer's raw output verbatim because it reads `rawOutput` from result JSON rather than relaying the human renderer.

### Lifecycle classification boundary

The review operation closed set is consulted only at ingress, reviewer execution setup, record construction, and display. Once a valid reviewer job exists, shared behavior branches on `jobClass: review` and status, never on `plan-review` versus `diff-review`:

- cancellation uses the existing review-class termination and isolated-runtime cleanup path;
- dead-worker reconciliation cleans the review runtime before persisting failure;
- SessionEnd reconciles, terminalizes, and retries cleanup for review-class jobs;
- status phase/type rendering recognizes the review class while displaying the preserved kind;
- retention remains status-based and exempts every active record, independent of operation.

These are one implementation with parameterized operation coverage. Adding a third operation in the future would still require an explicit closed-set change at ingress; it would not require another lifecycle branch.

### Transcript attribution contract

Attribution is based on evidence inside each transcript, not on the directory that happened to contain the root session. Owner identity is a top-level record `agentId` matching the harness form `aissue-<positive issue>-owner-<positive attempt>-<generated suffix>`; issue location is the set of issue-worktree numbers in that transcript's assistant-record cwd values. Both must resolve to the same single issue. A missing identity, arbitrary general-purpose name, reviewer identity, multiple issue cwds, no issue cwd, or identity/cwd disagreement is not issue-owner evidence and stays in the root group.

All additive fields from a proven owner transcript move together, including turns, token buckets, estimated cost, models, effort, stop reasons, phase and skill attribution, agent counts, and prompt/result byte samples. Each non-root transcript increments the subagent count only in its destination group. Non-additive peak context uses the existing maximum rule within the destination group. Every scanned result has exactly one destination. Root-session counts and root-only outcome/intervention semantics remain rooted; the global transcript and subagent counts still describe the input set. Global turns, token buckets, and cost come from the ordered raw results rather than a second fold over group totals.

The root key is forced to multi-issue when the session contains proven owners for two or more distinct issues. With zero or one proven owner, existing directory/root-cwd issue resolution remains in force, so ordinary single-issue sessions do not change. Non-owner descendants remain root overhead even if their cwd names an issue; cwd alone is deliberately insufficient to call helper or reviewer work issue-owner work.

### Review-operation evidence

Only the production-shaped initial bridge prompt is operation evidence: a sidechain's root user record begins with the two exact transport-envelope lines and contains one valid operation field. The cheap transcript prefilter admits that envelope even when the user record is large. When the same transcript's assistant turns carry `attributionSkill: codex-collaboration`, their attribution key is qualified by that operation. Other occurrences of the words plan-review or diff-review in prompts, findings, or repository prose are ignored. This reuses the transport contract and fields the harness already emits while keeping the report surface unchanged.

### Ordered pool fallback

Scanning accepts an ordered path list and returns an equally sized ordered value list. The parallel branch is fully materialized inside the protected boundary. Accumulation begins only after that boundary returns, so a pool that yields some values and then fails cannot leak a partial prefix into the report. The fallback catches ordinary exceptions, writes exactly one stderr line of the form `Process pool unavailable (<ExceptionClass>); scanning sequentially.`, and runs the same scanner over all paths sequentially. It does not catch process termination signals, and it does not swallow a scanner bug: if the sequential retry raises, the command still fails. Tests force failures through an injected executor factory at this internal boundary; no CLI or environment toggle is added.

## Test seams

1. **Companion CLI subprocess and durable records.** Extend the existing foreground and detached reviewer tests to run a shared table for both operation kinds. Assert the launch payload, persisted request and job record, read-only isolated execution, operation-specific `kind`/label/title, completed result JSON, and raw-output durability. Add negative CLI cases for a missing or unsupported reviewer value and a worker-side invalid persisted value. The bridge-definition contract test pins the closed transport envelope and value-bearing command; the workflow contract suite pins that callers supply both envelope lines.

2. **Status, result, and cancellation surfaces.** Use the existing subprocess/status fixtures and state resolvers with production-shaped jobs. Both kinds must render distinctly in status, identify themselves in human result output, and appear unchanged in result JSON; the raw reviewer body remains byte-identical below the human header and in JSON. Cancellation produces the same terminal record and removes the isolated runtime. Assertions target command output and files, not internal call counts.

3. **Worker liveness and SessionEnd lifecycle.** Parameterize the existing dead-worker and post-mortem fixtures over plan-review and diff-review. For each kind, prove dead-worker failure, cleanup-before-terminal-write outcomes, live-worker SessionEnd cancellation, already-terminal cleanup, record retention, and the active-record retention exemption. One shared fixture/case table prevents per-operation lifecycle tests from becoming duplicate implementations.

4. **Transcript scanner evidence.** Add focused scanner tests for the exact harness owner identity, same-issue cwd agreement, ambiguous or mismatched cwd refusal, arbitrary helper/reviewer exclusion, large production-shaped bridge prompts for both review operations, and rejection of operation words outside the envelope. Tests assert extracted evidence and additive values from the transcript boundary.

5. **Synthetic orchestration report.** Expand the end-to-end fake projects tree to the full demo topology. Assert rows for both issues plus `(multi-issue)`, both qualified Codex operation attributions, exact expected aggregate turns, every token bucket, stable cost, and one-count-per-transcript invariants. Include a helper whose cwd names an issue to prove cwd alone cannot move it. Also compare each global total with the direct ordered fold over all scan results, not merely the rendered rounded value.

6. **Fallback equivalence.** Test the ordered scan boundary with an executor that fails at construction and one that fails after beginning iteration. Capture the single stderr disclosure and compare the complete ordered values with a sequential scan. Run the full synthetic report through normal and forced-fallback paths and require identical stdout/report values; only the fallback disclosure may differ on stderr.

7. **Repository gates.** Test the regenerated patched upstream tree with its env-scrubbed focused/full Node suite, run the Python telemetry suite, run `just agent-workflow-tests`, and run `just build`. Patch semantics are inspected in the patched source tree, never by patch-wide grep; the regenerated zero-context patch and revision bump are the repository integration boundary.

## Out of scope

- Pricing tables, model-family mapping, or interpreting estimated cost as billing data.
- Distributing dispatcher, helper, native-reviewer, or Codex-transport cost across issue rows.
- Inferring issue ownership from cwd alone, prompt prose alone, or arbitrary agent names.
- Changing reviewer models, timeouts, sandbox policy, isolation, raw-output contract, retry/fallback policy, or non-review task lifecycle.
- Changing the report layout beyond truthful issue grouping, operation qualification in the existing attribution line, and one stderr fallback disclosure.
- A new worker command, review state schema version, process-pool configuration flag, periodic sweeper, or migration of already persisted records.
- Deployment, switching the host configuration, or live bridge certification.
- A new documentation tree or ADR. The interface is internal and reversible, follows existing closed-set and class/kind patterns, and does not meet the repository's three-part ADR threshold.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Make `--reviewer` carry the closed operation value from an explicit bridge envelope, while records keep `kind = operation` and `jobClass = review`. | Issue #48 requires end-to-end operation truth; the-bar requires fail-loud closed sets and a small agent-facing surface. | A second `--review-kind` flag duplicates one fact; retaining bare `--reviewer` cannot distinguish operations. |
| D2 | Key shared cancellation, liveness, cleanup, SessionEnd, and status-family behavior on the review class/status, and consult operation kind only at ingress, execution setup, persistence, and display. | Issue decisions require one generic reviewer lifecycle; prior detached-reviewer and truthful-terminal-state records make the terminal writer the cleanup owner. | Literal branches for each operation duplicate lifecycle policy and will drift when another review kind is added. |
| D3 | Attribute only transcripts whose owner-shaped `agentId` and own single issue-worktree cwd agree; keep every other subagent with root overhead and force roots with multiple proven owners to `(multi-issue)`. | Real orchestrator transcripts carry both signals; issue #48 forbids absorbing owner work or distributing dispatcher overhead. | Cwd-only attribution misclassifies helpers/reviewers, while root-only attribution recreates the bug. |
| D4 | Qualify existing Codex skill-attribution turns from the exact transport-envelope operation field instead of adding a new telemetry schema. | Bridge transcripts already carry `attributionSkill` and sidechain identity; D1 supplies one authoritative operation field. | Searching arbitrary packet prose creates false operations; inventing an operation event/schema is outside the issue. |
| D5 | Materialize all parallel results before accumulation, fall back over the complete ordered input, and derive global totals once from that ordered result list. | Issue #48 defines fallback as degraded performance with unchanged exact totals; the-bar requires truthful success and root-cause disclosure. | Incremental fallback can double-count a yielded prefix, while summing repartitioned group costs can change floating-point totals. |
| D6 | Prove both operation kinds through shared high-level CLI/state/lifecycle cases and one synthetic multi-issue report with forced-fallback equivalence. | Existing plugin tests expose subprocess and durable-state seams; the-bar requires observable tests that fail for one reason. | Separate implementations per kind and patch-text assertions can agree with the same bug or lose file attribution. |
| D7 | Migrate the help text and every existing bare `--reviewer` call site with the value-bearing CLI, and require a crafted invalid worker request to exit non-zero after durably recording the exact failure. | Phase-5 review verified the old help and guard/timeout/parallel/deadline fixtures still invoke the boolean form, while `runTrackedJob` records then rethrows worker errors. | Updating only new happy-path tests leaves the full suite on an invalid CLI; expecting worker exit 0 contradicts the truthful failure path. |
| D8 | Compare forced fallback against an injected deterministic successful executor with empty stderr, pin raw synthetic cost at `0.0113625`, and test the default executor's restricted-environment degradation separately. | Phase-5 review found that using the ambient process pool as the “normal” oracle can make both sides fall back and still compare equal; the fixture's six identical Opus-priced turns have one literal expected raw cost. | Treating ambient pool availability as success evidence makes the equivalence test vacuous; grouped-only cost comparison can share a reassociation bug. |
| D9 | Guarantee cancellation operation identity in the durable cancelled record/result and shared review cleanup, without adding `kind` to the cancel command's response payload. | The issue requires truthful stored/status/result identity and identical cancellation lifecycle; the existing cancel response is a bounded acknowledgement, while `result --json` exposes the authoritative durable record. | Expanding the cancel response creates a new surface solely for a redundant assertion and exceeds the smaller contract needed by acceptance. |
