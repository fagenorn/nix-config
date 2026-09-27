# C4+G2 post-deploy evidence — first end-to-end batch of the collapsed ladder (2026-08-10/16)

Successor to `2026-08-10-c4g2-evidence.md` (the pre-deploy input). That file
gathered five runs to justify collapsing the review ladder 4→2; this one records
what the collapsed ladder actually did in production, over `orchestrate-issues`
across nodo #1217, #1215, #805. Read this instead of re-deriving.

**3/3 merged.** #1217 → PR #1229 (`221f207d5`) · #805 → PR #1230 (`b009e9f78`) ·
#1215 → PR #1245 (`eccab1585`). Batch ran at plugin **p3**; the runtime has since
advanced to **p8** (see "Codex leg" below — several conclusions the batch reached
are superseded by that work and are corrected here, not repeated).

## The runs

| Issue | PR / merge | Phase-5 gate | Conformance axis (native) | Correctness axis |
|-------|-----------|--------------|---------------------------|------------------|
| #1217 admin-mcp secret CRUD | #1229 / `221f207d5` | full path — 3,911 lines / 9 files ≫ 400 | **paid**: 0C / 1I / 2M + AC confirmation, 3 fixes applied | Codex worker died silently (~19 min); one native fallback → 0C/0I/3M |
| #805 workflow-editor 409 recovery | #1230 / `b009e9f78` | full path — 4,451 lines / 14 files ≫ 400 | findings incl. ADR-012 stale pointer | ran native **without** pre-flighting Codex (see Drift) |
| #1215 user-mcp self-serve secrets | #1245 / `eccab1585` | full path — 2,816 lines / 41 files after excluding generated Designer + spec/plan artifacts | Clean at rung 2; 3 conformance findings at fix wave | Codex worker died silently; fallback → 1I + 3M |

## What the batch validated

- **D4/D5 — two-axis parallel isolated review.** Ran in sdd's rung-2 slot for the
  first time (#1215, `bb100b877..7457fbab6`) and again at ship for all three.
  Conformance and correctness dispatched as parallel isolated subagents over the
  same diff package. Ship's axis reviewers reused sdd's templates verbatim.
- **D6 — the axis is never skipped.** Held 3/3 under Codex failure. In every case a
  controller (ship or sdd, *not* the stalled bridge subagent) diagnosed the dead job,
  declared a real failure per contract, and dispatched the one-time native fallback
  itself.
- **D7 — one fixer, axis-labeled deduped list, then per-axis scoped re-reviews.**
  Executed exactly as specced on #805 and #1215 (fix wave `71b9aad3b` closed all 7
  findings in one commit, C1 with a both-ways mutation proof; suite 6,507/0).
- **D8/S3 — degradation gate mechanics.** Gate reasoned correctly 3/3, including
  S3's generated-file exclusion (#1215's 2,816-line count is *post*-exclusion). See
  "Merge-delta" below for what this did **not** prove.
- **D10 — implementer addressing.** Task-1 fix-round implementer reported via final
  message + report file and notified its parent by real name (`issue-1215`); zero
  `general-purpose` misaddressing, down from 2/2 pipelines pre-fix.
- **F1 — all-parked counts as clean.** #1215's Finish report triaged 27 ledger
  deferred/parked lines plus 1 parked-with-ruling finding and still reported
  `review_state: clean`. Pre-F1 this would have reported `residuals` and permanently
  disabled ship's degradation path.
- **Severity mapping** C/I/M ≙ Blocking/Should-fix/Discussion exercised for real on
  #1217. Discussion items arrived axis-labeled (`[correctness/Minor] C1 …`) with
  stable IDs and file:line anchors intact through the entire report chain.
- **Live re-sync under dev churn.** `origin/dev` advanced mid-CI on #1215
  (issue-1235's migration landed from another session) → PR conflicted → ship
  returned to Phase 1, resolved one migrations-test conflict, re-verified with 103
  targeted tests, pushed, merged.

## The Codex leg — batch verdict, and its correction at p8

**What the batch saw (p3):** 0-for-6. Transport, launch, `WORKTREE_ROOT` keying,
background launch, job state, pre-flight, and failure *detection* all worked — every
p3 fix held. But every worker died the same way: mid-model-turn, after "Turn
started" / "Assistant message captured", process vanishes, no result recorded,
0-byte stdout, ~14–28 min. One death (#805, job `bg0hr1sf9`) occurred with provably
no concurrent Codex job, which weakened the contention hypothesis the batch
otherwise favoured.

**What is true at p8 (measured 2026-08-16 across all 26 reviewer jobs on disk):**

| Scope | jobs | completed | failed |
|---|---|---|---|
| All time | 26 | 18 | 8 |
| Since `deadlineAt` landed (2026-08-15T19:24Z+) | 10 | 9 | 1 |

Three corrections to the batch's conclusions:

1. **"0-byte stdout / no forensic record" is fixed.** Issue #10's R1 (worker stderr
   redirected to the job log at spawn) shipped; job logs now run 355 B – 65 KB and
   carry the full command trail up to the instant of death.
2. **"Codex never completes" is false as a general claim.** 18 of 26 jobs completed.
   The 7 silent deaths are confined to `issue-1215`, `issue-1217`, `issue-805` — the
   batch's own three worktrees, 0-for-7 — while eight other workspaces (1231, 1232,
   1233, 1235, 1239, 1247, 48, 52) complete routinely.
3. **The 8th failure is not a defect.** `issue-1233` job `reviewer-msuzyh2c-jnmuvo`
   is a clean, correctly-classified `Codex job timed out after 840000ms`, fired at
   its recorded `deadlineAt` to the second — the new machinery working as designed.

**The load-bearing correlation:** the three 0-for-7 worktrees are exactly the three
branches that blew the 400-line gate (3,911 / 4,451 / 2,816 lines). #1215's job log
shows the worker fanning out dozens of `git diff --unified=25` calls across 44 files
before dying. No V8 heap trace, `abort()`, or "JavaScript heap out of memory" appears
in any log despite p8 capturing raw stderr — consistent with an external SIGKILL
rather than in-process OOM. Root-cause investigation is tracked separately in
`2026-08-16-codex-worker-death-research.md`.

**Consequence for the ladder:** worker death and the never-observed merge-delta path
are one problem — oversized review input — not two.

## Merge-delta: still never observed

All three branches blew the ≤400-line cap, two of them by ~10×. The gate reasoned
correctly every time, so this is not a defect, but **the merge-delta and empty-delta
review behaviours remain untested**, and D8's "degraded by default" framing is in
practice "full by default" for this backlog's issue mix. Only small fix/docs issues
would exercise it.

## Contract drift worth owning

Ship-#805 ran its correctness axis native **without pre-flighting Codex**, citing a
dispatcher operational note ("Codex's one attempt this run was already spent"). Per
the written contract each `diff-review` invocation is a fresh operation and
pre-flights again. Pragmatically right — it avoided another ~19-min dead slot — but
it means a dispatcher advisory altered the contract path, and ship-phase Codex
`diff-review` went unobserved for #805. The axis itself was never skipped. This is a
prose-contract drift vector: the contract lives in prose that an operator note can
override without anything detecting it.

## Environmental stalls — the cost floor

Nine platform interruptions across the batch: 3 ENOTFOUND events (a platform-wide
API outage killed both top-level agents on 08-10), 2 weekly-limit kills, 2
session-limit kills, 1 controller stream stall, 1 task-list reset that lost the
ledger. **Every one recovered from git state; no work lost, no task re-dispatched.**
Recovery that worked ~10/10: read the subagent transcript tail under
`~/.claude/projects/<slug>/<session-id>/subagents/agent-a*.jsonl`, then send one
transcript-aware nudge. Parent-idle-while-child-works is benign and distinguishable
only by transcript read.

**Wall-clock numbers from this batch are unusable** — the outage and limit gaps span
hours. Use per-phase transcript durations for cost comparison (e.g. #1215's design
phase: ~24.5 min, ~242k tokens, 82 tool uses, producing a spec + 2 ADRs + 20 grilled
decisions).

Contention is a live hazard even single-pipeline: #1215's Task-8 full suite ran 54
min with 16 transient Npgsql timeouts (all green on re-run), confirming the
stagger-whole-suite-verifies warning.

## Open items carried forward

- Bound review-input size so oversized branches degrade to a scoped review instead of
  killing the worker (design pass pending; subsumes the merge-delta threshold question).
- Ship a small docs issue to exercise the merge-delta and empty-delta paths.
- Close the prose-contract drift vector above with an explicit pre-flight norm.
- nodo tracker items from the batch's discussion: cross-tenant delete blast radius
  (#1217 delete path), the "never valueless" invariant (#1215 C3), and grouped doc
  pointer rot. Standing: #1118 fixture churn (bit this batch again), #1185 CI-wait
  escalation, #1212 (deliberately open).
