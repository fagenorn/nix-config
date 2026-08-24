# Workflow Scratch Containment Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Give every class of ephemeral workflow scratch one home outside the working tree it is generated in, make its cleanup a named mechanism rather than an assertion, and put a tracked ignore file behind both — per the spec `.claude/specs/2026-08-23-workflow-scratch-containment-design.md` (issue fagenorn/nix-config#102).

**Architecture:** Two classes move. Producer-report candidates and `workflow-state` request files leave the repository entirely for `${TMPDIR:-/tmp}`, stated as one verbatim clause shared by every skill that prescribes them so the four contracts cannot drift. The SDD workspace stops resolving from the process cwd and resolves the **primary checkout** the way `review-package._primary_checkout` already does, bucketed per checkout (`primary/` or `wt-<worktree-name>/`) so two checkouts running one plan never share a ledger — and, because a bucket outlives the worktree that named it, `ship-issue` prunes a feature worktree's bucket when it removes the worktree. A tracked `.gitignore` becomes the backstop that machine-local `.git/info/exclude` never was, and corpus-wide contract tests plus a new `sdd-workspace` suite pin all of it.

**Tech stack:** Bash (`sdd-workspace`, `task-brief`); Python 3 stdlib only (`unittest`, driving CLIs through `subprocess` against real `git init` fixtures); Markdown skill prose under contract tests; `git check-ignore` for the ignore backstop.

## Global Constraints

- Python 3 standard library only; no new dependencies anywhere.
- `sdd-workspace` keeps its interface exactly: one positional `PLAN_FILE`, one absolute path on stdout, exit 2 with a message on stderr for every refusal. No new flags, no `--repo-root` (per D4).
- The SDD workspace stays outside `.git/` — Claude Code treats `.git/` as protected and denies agent writes there, which would block an implementer subagent's report file. Any rewritten header must keep that reason (per D3).
- The self-ignoring `*` `.gitignore` written at `<primary>/.superpowers/sdd/` is kept even though this repository's tracked `.gitignore` makes it redundant here: these skills run in projects that have no such rule.
- All skill-prose matching in tests is done on whitespace-normalized text (`\s+` → one space) on both sides — the corpus hard-wraps at ~80 columns and every contract sentence spans lines (per D10).
- Prose this plan dictates verbatim is the exact text to write; it describes behaviour that is true after the task it belongs to.
- `handoff`'s **publication temporary** must stay a sibling of the durable destination; only its **report candidate** moves (per D2). Do not "fix" the publication sibling. In the skill text it keeps the file's own name, "the sibling temporary" — the plan's role label is not coined into the corpus.
- `.superpowers/ship-review/<issue>/retained-detail.json` stays in the feature worktree (per D7). It is the single named exception, not a leak.
- Nothing in this plan deletes a `.superpowers/` directory inside another worktree (per D8).
- `CLAUDE.md` was already corrected in the design commit (per D13). No task re-edits it; Task 6 verifies the shipped behaviour matches it.
- Run all verification from the worktree root `/Users/anis/tmp/nix-config/.claude/worktrees/worktree-issue-102-workflow-scratch-containment` unless a step says otherwise.

## Test seams

Four files, three existing. No task may invent a fifth.

- `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — every corpus-wide prose contract and the ignore backstop. Follows that module's prior art: `REPO_ROOT`-relative path constants and boundaries spelled exactly once at module level (`GATE_LINE_BOUNDARY`).
- `home/common/agent-skills/tests/test_sdd_workspace.py` (new) — the `sdd-workspace` CLI end-to-end against a real `git init` primary and real `git worktree add` linked worktrees. Follows `test_task_brief.py`'s `make_repo` fixture style.
- `home/common/agent-skills/tests/test_review_package.py` — the forced report-validation failure, reusing `setup_repo`'s `HOME`/`PYTHONPATH` module home.
- `home/common/agent-skills/tests/test_task_brief.py` — the forced member-copy failure, using the `PATH`-injected `bin/` the fixture already builds.

Whole-repo gates: `just agent-workflow-tests` (all Python suites; CI does not run them) — run by **Tasks 1, 3 and 6**, because Task 1 re-anchors three existing assertions and must prove the module green itself rather than deferring five failures five commits downstream, and Task 3 proves its new suite is picked up by the recipe — and `just build` (the Nix evaluation, this repository's only local build gate — every changed skill file is materialised through the flake).

## Task index

Task 1 — Producer-report candidates leave the working tree — home/common/agent-skills/skills/{design,grill-with-docs,writing-plans,handoff}/SKILL.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-1.md](2026-08-23-workflow-scratch-containment.tasks/task-1.md)
Task 2 — Lifecycle request files get a stated home — home/common/agent-skills/skills/from-issue/SKILL.md, home/common/claude-code/skills/orchestrate-issues/SKILL.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-2.md](2026-08-23-workflow-scratch-containment.tasks/task-2.md)
Task 3 — Primary-rooted, per-checkout SDD workspace — home/common/agent-skills/skills/sdd/scripts/sdd-workspace, home/common/agent-skills/tests/test_sdd_workspace.py, justfile — full — [task-3.md](2026-08-23-workflow-scratch-containment.tasks/task-3.md)
Task 4 — Workspace documentation, the `.superpowers/` allowlist, and bucket cleanup — home/common/agent-skills/skills/sdd/SKILL.md, home/common/agent-skills/skills/sdd/scripts/task-brief, home/common/agent-skills/skills/ship-issue/REVIEW.md, home/common/agent-skills/skills/ship-issue/SKILL.md, home/common/agent-skills/skills/worktrees/SKILL.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-4.md](2026-08-23-workflow-scratch-containment.tasks/task-4.md)
Task 5 — Tracked `.gitignore` backstop — .gitignore, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-5.md](2026-08-23-workflow-scratch-containment.tasks/task-5.md)
Task 6 — Forced-failure cleanup pins, residual containment, rollout — home/common/agent-skills/tests/test_review_package.py, home/common/agent-skills/tests/test_task_brief.py — full — [task-6.md](2026-08-23-workflow-scratch-containment.tasks/task-6.md)

Order: 3 → 4 (Task 4's prose describes behaviour Task 3 implements). Tasks 1, 2 and 5 are independent of everything. Task 6 last: it runs both whole-repo gates and asserts this worktree carries no stray report candidate or temporary — while deliberately leaving this run's own pre-Task-3 `.superpowers/` ledger alone — which is only meaningful once every other task has landed.

## Execution state

Execution on this branch did not start from zero. A previous ledger-free owner
implemented Tasks 1, 2 and 3 and committed them, together with this plan and the
spec, as the single commit `503f7dc`; it died before any per-task review ran and
left no `sdd` ledger. Attempt 1 of run `direct-102-000001` resumed that branch
(per D25) and seeded the plan's `sdd` workspace ledger from the observed branch
state (per D26).

- **Tasks 1, 2, 3 — implemented, unreviewed.** Present at `503f7dc` and verified
  green at resume: `just agent-workflow-tests` runs 427 tests OK, the Task-1
  corpus grep for the retired wording prints nothing, and `test_sdd_workspace.py`
  contributes 8 passing tests through the `agent-workflow-tests` recipe. Each
  still owes the first-pass full-lane review its lane requires; the ledger says
  so per task, and the review scope is that task's `## Task index` file set
  within `503f7dc`.
- **Tasks 4, 5, 6 — not started.** `sdd/SKILL.md` carries no primary-checkout
  wording, the tracked `.gitignore` still holds only `result`, `__pycache__/`
  and `*.pyc`, and neither forced-failure pin exists.

The three landed tasks share one commit, so their diffs are not separable by
commit range; scope each review by files, not by revision. The mandatory final
two-axis review still covers the whole branch, `503f7dc` included.

## Decisions

The spec owns the single issue-level decision ledger (D1–D17); tasks cite rows by ID and never restate them. Planning appended D15 (the exit-2 driver the spec named cannot reach step 4 — corrected to a decoy bare repository), D16 (the report-validation shim must register itself in `sys.modules` or the run stops at "validator unavailable" — a vacuous pass), and D17 (one identical literal for all three request-file prescriptions plus a corpus rule, so the assertion is an occurrence count rather than three positional greps).

Phase-5 standards review added D18–D24 and amended D5 in place (a narrowed claim, not a reversal).

Attempt 1 of run `direct-102-000001` appended D25–D27 when it resumed this branch: how the pre-existing worktree was adopted, why the seeded `sdd` ledger says `implemented` rather than `complete` for Tasks 1–3, and why the standards review above is not re-run. They record the resume, not the build — no task text changed.

Two facts every task must hold: the cleanup code at `task-brief:97` (`trap … EXIT HUP INT TERM`) and in `review-package._validated_report` (`finally: unlink`) is **already correct**. What issue #102's second acceptance criterion is missing is a *test* that forces those branches, not a fix — Task 6 adds regression pins, and no task may "make them fail first" by breaking working cleanup.

---

## Standards review provenance

Reviewer: **Claude fallback** — the one-time native pass taken because the Codex plan-review job timed out after 840000 ms (`CODEX_REVIEW_FAILURE`), a real Codex failure rather than a concurrency condition. Run isolated and read-only against base SHA `f6743e5d55864902104c9f0949a1f000b1114e5b`, with no review focus configured.

Dispositions: 1 Blocking — accepted. 5 Should-fix — all accepted. 7 Discussion — 4 applied as plan edits, 1 accepted as a known residual with no change, 1 subsumed by the Blocking fix, 1 not applicable (no UI surface). Nothing rejected, nothing deferred.

Known residual: `SIBLING_CANDIDATE_RE` is wording-anchored, so a future skill that phrases the same mistake differently ("write the report next to the artifact root") would pass Task 1's guard. The general defence is Task 4's closed `.superpowers/` segment allowlist. This is the trade-off D10 already accepted and is carried knowingly.
