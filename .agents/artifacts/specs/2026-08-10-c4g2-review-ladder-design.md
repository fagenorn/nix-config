# C4+G2 — Collapse the review ladder 4→2 around a two-axis diff review

Interview date: 2026-08-10. Three AskUserQuestion rounds, all decisions user-confirmed
(grounding: git-dir `GROUNDING.md`; evidence: `.claude/specs/2026-08-10-c4g2-evidence.md`,
five real nodo issues through the full pipeline). Ledger task #15, the last open revamp item.

## Problem

A full `from-issue --auto` run reviews the same work four times: the plan (Phase 5), each
sdd task, the whole branch at sdd's final review, and ~the same whole-branch diff again at
ship-issue's PR review — plus a `decision-check` gate that has never fired anywhere.
The evidence run showed where the signal actually is: the plan-review slot caught
load-bearing Blocking findings in 5/5 runs, while the two back-to-back whole-branch reads
duplicate each other (~11 min and a full re-read each), and the one review that ran under
budget covered only plan-internal consistency + live code — the spec/ADR/standards axis
went entirely unread in #1218. The ladder is expensive where it is redundant and thin
exactly where the leaks are.

## Solution

Two rungs, each with a distinct job:

- **Rung 1 — plan review (unchanged shape).** from-issue Phase 5: Codex `plan-review`
  via codex-collaboration, native `reviewer` fallback on real failure,
  `REVIEW-CONTRACT.md` travels by path and keeps its full common-miss checklist.
- **Rung 2 — one two-axis diff review** in sdd's final-review slot (in-worktree,
  pre-ship), replacing sdd's single final reviewer *and* ship-issue's full PR review:
  - **Conformance axis (native Claude `reviewer`)** — did the diff deliver what
    issue + spec + plan promised, honoring ADRs, context docs, and standards.
    Map-first doc grounding is this reviewer's first step.
  - **Correctness axis (Codex, via a new codex-collaboration `diff-review` operation)** —
    is it built right: bugs, edge cases, tests that pin behavior, cross-task integration.
    Native `reviewer` fallback on real Codex failure; the axis is never skipped.

  The axes run as parallel isolated subagents over the same diff package. Verdicts are
  ≤400 words each, severity Critical/Important/Minor, and are **never merged** into one
  narrative. One fixer wave receives both lists labeled by axis; each axis with findings
  gets one scoped re-review; residuals follow sdd's breaker/adjudication rules.

Per-task reviews survive unchanged as sdd-internal execution gates. `decision-check` is
deleted. ship-issue Phase 5 degrades to a merge-delta-only check when the branch is
SDD-clean, conflict-free, and small; the full two-axis review runs at ship for `risky`
issues, critical paths, big diffs, or unknown review state.

## Decisions

### D1 — The collapse removes branch-level duplication, not execution gates

The ladder becomes rung 1 + rung 2. sdd's per-task reviews (spec compliance + quality per
task, feeding the 5-round fix loop with its round-4 codex:rescue stuck-breaker) stay
exactly as they are: they are task-scoped, cheap, and the mechanism that keeps fixes from
end-loading. What dies: sdd's single final whole-branch reviewer (replaced by the two-axis
pair in the same slot), ship-issue's full PR review (degraded, D8), and `decision-check`
(deleted, D3).

### D2 — Rung 2 lives in sdd's final-review slot

In the worktree, before ship — branch-level defects are found before the PR exists, not
after (no fix-push-CI churn on findings a pre-PR review would have caught). The sdd
controller builds one diff package (`review-package` over MERGE_BASE..HEAD) and dispatches
both axis reviewers against it. ship sees the true merged result later only through the
degraded check or the risky-path full review (D8).

### D3 — `decision-check` is deleted

Remove the operation from codex-collaboration, the `codex.decisionReview` binding from
from-issue, and AUTO.md's cross-check step. Rationale: it has never fired (default off),
it has no fallback by design, and every auto-resolved decision is already inside the
artifacts both remaining rungs read — the plan reviewer reads the plan's
`## Auto-resolved decisions` section at rung 1, and the conformance axis re-reads spec and
plan at rung 2. A third, never-exercised mechanism is dead weight.

### D4 — Axis assignment: Codex takes correctness, native takes conformance

- **Conformance (native).** Inputs: the diff package, issue body + acceptance criteria,
  spec and plan paths, map-first doc grounding (context map → intersecting area
  `CONTEXT.md`s → cited ADRs → applicable standards shards). Grades delivered-vs-promised
  coverage, stale-prose audit around the diff's footprint, spec↔implementation
  message-format parity, terminology against the areas' canonical terms.
- **Correctness (Codex).** Inputs: worktree root, base..head range, the correctness
  rubric by path, standards paths (the-bar, matching stack shards, project standards
  shards), repo-level AGENTS/CLAUDE files, verify commands. No doc-corpus assembly — the
  packet stays light, which is what lets Codex return inside its budget. Grades bugs,
  boundary error handling, dead branches, assertions that actually pin the documented
  contract, DRY against existing helpers, cross-task integration.

Cross-model de-correlation lands where second-opinion value is highest (bug-spotting
blind spots); the doc-heavy axis stays where map-first grounding is native machinery.

### D5 — codex-collaboration gains a `diff-review` operation; sdd invokes it

One home for all bridge logic. `diff-review` mirrors `plan-review`'s contract: packet
assembly, `command -v codex-companion` pre-flight, `WORKTREE_ROOT:` first line, background
launch inside the bridge, 840 s runtime budget, three-section validation, one-time native
fallback on real failure only, no retry, concurrency never a fallback reason. sdd's
final-review step invokes it for the correctness axis when the skill is available (Claude
sessions) and dispatches the conformance reviewer in parallel; when unavailable
(standalone sdd, Codex-native sessions), both axes run as native `reviewer` subagents.
The parent agent keeps verify-and-disposition: re-open cited files, reject stale findings,
never store raw reviewer transcripts.

### D6 — Codex failure policy at rung 2: native fallback, same axis

Mirror rung 1: on a real Codex failure (missing binary, auth, crash, hard timeout,
`CODEX_REVIEW_FAILURE:`, malformed output after one completed run), dispatch exactly one
fresh native `reviewer` with the same axis brief. The axis never goes unreviewed — the
uncovered axis is precisely how gaps leaked in the evidence run. Provenance records the
failure class and that fallback ran.

### D7 — Verdict contract and fix flow

Both axes report Critical/Important/Minor, ≤400 words, findings anchored to file:line.
Conformance gaps land as Critical (= must fix before merge). Reports are dispositioned
per axis and never merged; where both axes flag the same lines, the controller dedupes at
fixer-dispatch time, crediting both axes in the ledger. Flow (unchanged from sdd's final
review): one fixer receives the complete labeled list; one scoped re-review per axis that
had findings; residuals adjudicated under the existing breaker rules; ledger entries carry
per-axis verdicts.

### D8 — ship-issue Phase 5: degraded by default, full ladder on risk signals

Degrade to **merge-delta-only** when ALL hold:

- **SDD clean** — both axis verdicts clean, or every residual parked-with-ruling.
  The state travels in sdd's report and from-issue's ship handoff (`review_state:
  clean | residuals | unknown`); a standalone ship with no evidence treats it as
  `unknown` → no degradation.
- **Conflict-free** — the Phase-1 sync needed no manual escalation (allowlist
  auto-resolves count as clean).
- **Small** — total branch diff ≤400 changed lines AND ≤20 files, excluding lockfiles
  and generated files.

The degraded check: one native reviewer over the sync-merge's combined diff plus any
post-review commits; when that delta is empty, record "nothing to review" and proceed to
CI. The **full two-axis review runs at ship** (same machinery as rung 2, same rubrics,
over the post-sync merge-base..HEAD) when the issue carries the `risky` label, the diff
intersects `review.criticalPaths` globs (optional binding in skills.config.json; absent =
label-only), any degradation condition fails, or review state is unknown. There is exactly
one diff-review definition, reused at both sites.

### D9 — Rubric distribution: rung 1 unchanged, diff rubrics get the diff-native checks

`REVIEW-CONTRACT.md` keeps its full checklist — it is the rung with the 5/5 evidence
record and is not weakened. The two new axis rubrics carry the diff-native categories:
conformance — delivered-vs-promised coverage, stale-prose audit, message-format parity;
correctness — dead branches after iteration, test-assertions-actually-pin, DRY against
existing helpers, plus the quality/integration checks from sdd's retired final-review
template. A category may deliberately exist in plan-form and diff-form where both are
cheap catch points.

### D10 — Riders

- **sdd grandchild-addressing bug**: implementers told to report back have
  SendMessage'd the literal agent-type name `general-purpose` (2/2 pipelines). Fix in
  sdd's dispatch/report machinery in this implementation — same files, observed failure.
- **ship-issue eval 1** expected text updates from "Phase 5 a fresh reviewer subagent"
  to the degraded-by-default shape. No new eval case (D-eval rationale under Test seams).

## Test seams

- **`just evals from-issue 1–3`** (deployed-skill pipeline evals; currently 8/8, 3/3,
  5/5). Phase 5 keeps its shape, so these stay green unmodified — they are the
  regression gate for every skill-text edit this design causes. Commit → user runs
  `just switch` → evals; never repoint `~/.claude/skills`.
- **`just evals ship-issue 1–3`** (plan-only): eval 1's expected text evolves with D8;
  evals 2–3 are unaffected (the five-step apply/push discipline still governs findings in
  both degraded and full paths).
- **Post-deploy observation batch** — a small orchestrate-issues run over the remaining
  `ready-for-agent` backlog is the real rung-2 validation, exactly how the old ladder was
  validated. A new pipeline eval reaching rung 2 would need Phase 6 to execute (an order
  of magnitude beyond the cheap-first suites) and is deliberately not added.
- **Codex leg**: the direct runtime smoke test plus this session's end-to-end bridge
  health-check validate every layer `diff-review` reuses.

No new seams; implementers may not add others.

## Out of scope

- CI-wait escalation redesign (escalate on no-step-progress) — nodo #1185, its own issue.
- nodo #1118 fixture churn dirtying worktrees.
- Per-task review reform and any change to the 5-round fix loop.
- Background-agent report-delivery reliability beyond the D10 addressing bug.
- ship-release's review shape.
- Changing rung 1's contract, packet, or fallback behavior (beyond deleting
  decision-check).
- A source-comment sweep or any docs-structure change (covered by the 2026-08-08 spec).

## Auto-resolved decisions

### Interactive-mode parity
- **Question:** Does the collapsed ladder differ between interactive and `--auto` runs?
- **Choice:** No — same two rungs, same degradation rules; interactive keeps its
  checkpoints (user confirms rung-2 verdicts instead of auto-applying Should-fix-class
  items).
- **Grounding:** AUTO.md's contract: autonomy changes what happens at decision points,
  not what work gets done.
- **Alternative considered:** Interactive keeps the old 4-rung ladder — rejected; two
  divergent ladders in one skill is drift by design.

### Merge-delta mechanics
- **Question:** What exactly does the degraded ship check review?
- **Choice:** The combined diff of the sync-merge commit (conflict resolutions and
  scope-creep sweeps — what changed relative to both parents) plus any commits after the
  reviewed head; empty delta → record and skip to CI.
- **Grounding:** ship-issue Phase 1's scope-creep-at-merge-time categories are the only
  new hazard surface a clean sync introduces; Phase 2 re-runs tests post-merge.
- **Alternative considered:** Re-reviewing the full PR diff — that is the duplication
  this design removes.

### Rubric transport
- **Question:** Pasted in briefs or by path?
- **Choice:** Native axis reviewers get rubrics pasted per sdd's template convention (two
  new sdd templates — conformance and correctness — replacing the final-review template);
  the Codex packet receives the correctness rubric by absolute path per
  codex-collaboration's convention.
- **Grounding:** Task #15 seed ("rubrics pasted in briefs"); sdd templates are pasted
  today; REVIEW-CONTRACT.md's by-path rule exists to keep reviewer text out of the
  orchestrator's context, which the path-handoff to Codex preserves.
- **Alternative considered:** Everything by path — breaks sdd's existing template
  mechanism for no context saving (the controller never holds the rubric either way).

### Provenance home
- **Question:** Where does rung-2 provenance live now that the plan's provenance section
  covers rung 1?
- **Choice:** The sdd ledger carries per-axis reviewer identity (Codex | native |
  fallback+class), base/head SHAs, and verdicts; sdd's report and the ship handoff carry
  `review_state`.
- **Grounding:** The ledger is sdd's durable record; the plan's provenance section stays
  rung-1-scoped as today.
- **Alternative considered:** A provenance file in the worktree — one more artifact with
  no reader.

### decision-check deletion mechanics
- **Question:** How is the deletion kept clean?
- **Choice:** Remove the operation section from codex-collaboration, the
  `codex.decisionReview` key from from-issue's bindings, and AUTO.md's step-4 cross-check
  (renumbering the self-answer pattern); grep confirms references exist only in those
  three files.
- **Grounding:** Repo-wide grep this session.
- **Alternative considered:** Deprecate-but-keep — a config key nothing reads is exactly
  the dead weight being removed.

### Spec committed on the integration branch
- **Question:** Worktree or main for this design doc?
- **Choice:** Commit on main directly (pathspec-only commit), like every prior nix-config
  design/evidence spec.
- **Grounding:** Repo precedent (docs-structure spec, evidence record — both on main);
  nix-config design sessions produce docs, not code branches.
- **Alternative considered:** A worktree per the design skill's default — process
  overhead with no parallel-run risk here.

### Terminology
- **Question:** What are the axes called in skill text?
- **Choice:** "conformance axis" and "correctness axis", with one-line definitions at
  first use in each edited skill.
- **Grounding:** Handoff and task #15 used three near-synonyms (spec/doc-conformance,
  Standards, Spec); one pair of terms, defined where used, prevents the drift the grill
  exists to catch.
- **Alternative considered:** "spec axis"/"standards axis" — both axes read standards,
  so the names mislead.
