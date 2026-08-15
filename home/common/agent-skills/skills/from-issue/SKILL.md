---
name: from-issue
description: Drive one tracker issue through investigate → spec → plan → review → execute in a worktree. Use for "work on issue #X"; pass --auto for autonomous mode.
argument-hint: "<issue number or URL> [--auto]"
---

# From Issue

Counterpart to `to-issues`. Take one tracker issue from triage to merged code by chaining the canonical skills, with a human checkpoint at every phase.

## Files beside this one

- **`AUTO.md`** — autonomous-mode rules. Read it *once*, now, only if the invocation contains the literal token `--auto`.
- **`bindings.md`** — project bindings. Read it now and resolve them first; `<tracker-cli>`, `<integration-branch>`, `specDir`, `planDir`, and the tracker-cli hygiene rule come from there.
- **`grounding.md`** (Phases 2–5), **`decision-ledger.md`**, **`investigate.md`** (Phase 0), **`standards-review.md`** (Phase 5), **`ship-handoff.md`** (Phase 7) — loaded at the named phase.
- **`REVIEW-CONTRACT.md`** — the Phase-5 reviewer contract. Hand it over **by absolute path**, never read it into this conversation.

## Lifecycle identity

Resolve the optional lifecycle envelope supplied by a dispatcher:
`ledger_repo_root`, `run_id`, `attempt`, `owner`, and normalized `worktree`.
Treat all five as one identity; never guess a missing field. Preserve the
immutable ledger_repo_root exactly as supplied, and keep it distinct from the
separate owner worktree recorded on the attempt. Every `workflow-state` command in
this owner or its delegated remainder uses `--repo-root <ledger_repo_root>`;
never substitute the current checkout or owner worktree. A direct standalone invocation remains compatible
and does not require a ledger; it may `workflow-state init-run` its own run only when
the user explicitly requests durable orchestration, carrying that root as `ledger_repo_root`.

## The flow

```
0. Investigate        → summary + open questions (no files yet)
1. Worktree (skill)   → isolated workspace off origin/<integration-branch>
2. Brainstorm (skill) → <specDir>/<date>-<topic>-design.md
3. Grill (skill)      → spec refinements + context-doc / ADR updates
4. Plan (skill)       → <planDir>/<date>-<feature>.md
5. Standards review   → Codex plan review, native fallback, or self-grade
6. Execute (skill)    → subagent-driven-development
7. Ship (skill)       → ship-issue: PR, review, CI, merge, cleanup
```

**Checkpoints.** Checkpoint between every phase; don't auto-chain. State the artifact produced and wait for the user. A wrong spec costs one revision; a wrong plan costs a worktree of execution. With `--auto`, checkpoints become self-resolved ledger rows — see `AUTO.md`; only the Phase-0 stops and unfixable Phase-5 blockers still stop.

## Decision ledger (artifact discipline)

Non-obvious decisions this flow makes instead of the user live in **one issue-level ledger table** in the spec, under a section named exactly `## Decision ledger` — format and rules in `decision-ledger.md` beside this file. The plan and ADRs cite rows by ID ("per D3") and never restate them. Log only non-obvious decisions (scope, interface, behavioral, test-seam, irreversible, user-preference); consolidation of related rows is permitted and encouraged. Mandatory under `--auto`; expected interactively too.

## Risk lanes

Assigned per task at planning time (Phase 4), recorded in the plan's `## Task index`, and applied by `sdd` during execution:

- **mechanical** — deletion/renaming with **no** behavioral, configuration, interface, generated-output, or semantic-documentation effect; file and line counts never qualify a change on their own.
- **low-risk** — small semantic changes: bounded, locally-verifiable behavior changes, **excluding** anything touching concurrency, lifecycle, destructive operations, security, release, migration, or public contracts.
- **full** — everything else.

Mechanical and low-risk tasks get scoped (inline or reviewer-lite) verification; full-lane tasks get a full per-task review. The independent final two-axis review is mandatory for **every** lane.

## Skill-tool invocations

Sub-skills named here — `worktrees`, `design`, `grill-with-docs`, `writing-plans`, `doc-grounded-questions`, `codex-collaboration`, `sdd`, `ship-issue` — go through the `Skill` tool, never paraphrased from memory. `codex-collaboration` is Claude-only, so native Codex sessions take the Phase-5 native-reviewer path.

**Never hard-fail on a missing sibling** — run the phase inline: brainstorm as intent + requirements + ≥2 options; grill against the map's areas and `adr/` dirs; plan as numbered tasks with a verification gate each; execute task-by-task with the verify commands; ship per the Phase-7 fallback.

## Dispatch and budget rules

**Structured report-backs.** A subagent's final message is re-read by its caller on every later turn, so every `Agent` dispatch states a fixed return schema: artifact paths, a one-word verdict/state, ≤500 characters of notes; details live in worktree files. Prefer the tiered agent types over `general-purpose`.

**Executable phase gate.** At every phase boundary, including Phase 0 through
Phase 7, call `workflow-state progress` when lifecycle identity exists. Pass the
observed turn count and context tokens when available, the completed phase, and
truthful booleans for next-phase context need, artifact sufficiency, and
remainder self-containment. Do not fabricate usage:
omit unavailable `--turn-count` or `--context-tokens`. Use the
defaults `--turn-ceiling 120 --context-ceiling 150000 --turn-headroom 2
--context-headroom 10000`. Obey the returned action exactly; the closed set is
`continue | fresh_start | handoff | delegate`:

1. **`continue`** — proceed in this conversation.
2. **`fresh_start`** — start a fresh conversation from committed artifacts; do
   not carry conversational state.
3. **`handoff`** — beneath `ledger_repo_root`, create only the run's non-symlink
   `handoffs/` directory if missing; never pre-create the destination leaf (the
   `handoff` skill owns safe first-file creation). Invoke `handoff` with a
   destination beneath `.superpowers/workflows/<run-id>/handoffs/`, repeat
   `workflow-state progress` with `--handoff-path <exact-path>` to finalize
   `handed_off` on the same attempt, and stop. Resume later with `workflow-state
   launch --resume-handoff <exact-path>` and the same identity.
4. **`delegate`** —
<!-- agent-dispatch: id=from-issue-phase-delegate role=issue-owner model=opus effort=high -->
Agent(subagent_type="general-purpose", model="opus", effort="high") delegates the entire remainder to a fresh issue owner with the lifecycle envelope and artifact paths.
   This is a fresh agent; it reconstructs context from those artifacts rather than inheriting conversation history.
   Exception — **ledger-only remainder**: when every content artifact is final and only `workflow-state` transitions plus verbatim result relay remain, delegate to the cheap bookkeeper instead:
<!-- agent-dispatch: id=from-issue-ledger-remainder role=bookkeeper model=haiku effort=low -->
Agent(subagent_type="mechanic", model="haiku", effort="low") executes the ledger-only remainder: the exact workflow-state commands and verbatim JSON relay, with no content judgment.
   Give it the exact commands, identities, and paths inline; it decides nothing and edits nothing.

Without lifecycle identity, apply the same action order locally with the
120-turn/150000-token ceilings and default interactive handoff behavior.

## Terminal return procedure

Use this one procedure for Phase-0 content stops, budget stops, execution failure,
and Phase-7 success whenever lifecycle identity exists. Assemble a temporary JSON
file with exactly `issue`, `state`, `pr_url`, `merge_sha`, `issue_closed`,
`discussion_items`, and `notes` (≤500 characters). Pass it with
`--result-file <path>` to `workflow-state finish` using the exact run, issue,
attempt, and current time. Capture stdout; only after that durable write succeeds,
send the exact JSON from stdout unchanged to the caller.

The rule is: failure to persist is a failure to finish. Surface it and never report the issue as merged or completed.
Without lifecycle identity, send the same compact schema directly.

## Phase 0 — Investigate

Build a shared mental model *before* the brainstorm. No files yet. Read `investigate.md` for the pre-flight queries and the note structure. (When `issueTracker.kind=none`, skip the fetch and PR pre-flight.)

**Pre-flight** — two sessions racing on one issue is the most expensive failure this flow produces. Run the PR pre-flight per `investigate.md` (open PR → stop; merged → stop; closed-unmerged → judge). Then `git worktree list | grep <worktreePrefix>issue-<num>-`:

- none → continue;
- one → **inspect before touching it**; a "clean" tree can still hold committed work that only ships at Phase 7. Check four signals: unpushed commits (`git log origin/<integration-branch>..<branch> --oneline`); workflow-state ledger attempts naming it that are `active` or `handed_off`; tracker/PR state referencing the branch; spec/plan artifacts under `specDir`/`planDir` inside it. If **any** exist → resume that worktree (interactively, propose resume and wait; in `--auto`, prefer resume, and on conflicting signals stop as blocked through the terminal return procedure). Deletion (`git worktree remove` + `git branch -D`) only when **provably disposable**: zero commits ahead, no active or handed-off ledger attempt, no spec/plan artifacts, no uncommitted work;
- one with uncommitted work → **stop and ask the user**; their in-progress state isn't yours to discard;
- several → stop and ask which to resume or discard.

Investigate per `investigate.md` and post the note. Several issues bundled → stop, suggest `to-issues`. Question or duplicate → report and stop. Every Phase-0 early stop uses the terminal return procedure when lifecycle identity
exists: write a `stopped` or `failed` result through `workflow-state finish` before notifying the caller.

**Open questions is mandatory even in `--auto`** — self-answering happens in the spec's `## Decision ledger`, not by dropping the section. With nothing open, write "None — Phase 2 will surface anything missed".

**Mechanical-only shortcut.** Declare `mechanical-only` only when the **entire** change fits the mechanical lane (§Risk lanes). Then Phase 5 self-grades against `REVIEW-CONTRACT.md` and Phase 6 dispatches one mechanic+reviewer pair for the whole change. Every phase still runs; skip manufactured TDD framing.

**CHECKPOINT** — Confirm restatement + scope. Require a per-question disposition for each open question: an answer, "defer to brainstorm", or "agent-choose". A bare "proceed" means re-prompt.

## Phase 1 — Worktree

Create the workspace before any spec/plan/grill commit lands; those commits go *in the worktree*, never on the integration branch.

When a lifecycle envelope exists, use its exact absolute `worktree` as the
attempt workspace. Re-check that it is absent from the filesystem and from
`git worktree list`, then create the worktree at that exact path from
`origin/<integration-branch>`. If the path is occupied or mismatched, fail the attempt
through the terminal return procedure; never remove unknown contents and never choose another path.
The envelope identity stays bound to this path through shipping and cleanup.
Direct standalone invocation keeps the standard `worktrees` flow:

1. `git fetch origin`. Invoke `worktrees` (it encodes the destructive-ops carve-out, the prefix contract, and the position checks before `EnterWorktree`/`ExitWorktree`). For lifecycle use, invoke it only if it accepts the envelope's exact path; otherwise `git worktree add -b <branch> <exact-envelope-path> origin/<integration-branch>`. Branch = `branchNaming.pattern`; the on-disk branch carries `branchNaming.worktreePrefix` — both forms are accepted downstream, don't strip it.
2. **Base on `origin/<integration-branch>`**, never the local branch, which may carry other agents' in-flight commits. The merge happens later, in `ship-issue`.
3. `cd` into the worktree; every later phase runs inside it. Verify `git rev-parse --git-common-dir` ≠ `git rev-parse --git-dir`.

**CHECKPOINT** — Confirm worktree path and base; in `--auto` log the base SHA in the investigation note.

## Phase 2 — Brainstorm

Invoke `design` for a design doc under `specDir`, committed in the worktree. Ground first per `grounding.md`. Resolve every Phase-0 carryover before opening a new question.

**CHECKPOINT** — User approves the spec file in writing.

## Phase 3 — Grill

Invoke `grill-with-docs`. It sharpens the spec against the context doc, surfaces glossary conflicts, and may produce ADRs; those and any context-doc edits commit in the worktree and ship when the PR merges.

**CHECKPOINT** — Confirm all doc updates and the refined spec.

## Phase 4 — Plan

Invoke `writing-plans` for a plan under `planDir`, committed in the worktree. The plan header carries a `## Task index` — one line per task: ID, title, files touched, and risk lane assigned here per §Risk lanes. The plan cites ledger rows by ID and appends new non-obvious plan-level decisions to the spec's ledger.

**Plan-prose ≠ code-prose.** Prose the plan dictates verbatim into the codebase (docstrings, comments, doc sentences, ADR clauses) must describe how the live code *will actually behave*; if you can't say precisely yet, write a TODO and let the execute phase rewrite it from the implemented code.

**CHECKPOINT** — User reviews the plan file.

## Phase 5 — Standards review

Read `standards-review.md` and follow it: Codex `plan-review` when enabled and available, the native reviewer dispatch otherwise, the mechanical-only self-grade, and the finding-disposition rules (verify against the live worktree; ledger rows for applied findings; contract by path, never inlined).

**CHECKPOINT** — Confirm standards review is clean.

## Phase 6 — Execute

Invoke `sdd`: it reads the plan header, dispatches an implementer per task, and reviews each output by risk lane.

If the plan is `mechanical-only`, use one mechanic plus one first-pass reviewer for the whole change:

<!-- agent-dispatch: id=from-issue-mechanical-implementation role=mechanic model=sonnet effort=high -->
Agent(subagent_type="mechanic", model="sonnet", effort="high") executes the fully specified mechanical change.
<!-- agent-dispatch: id=from-issue-mechanical-review role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") performs its first-pass review.

**CHECKPOINT** — Confirm the implementation is committed on the feature branch.

sdd's report includes `review_state` (`clean | residuals | unknown`) from its two-axis
final review; carry it verbatim into the Phase-7 handoff — ship-issue's Phase-5
degradation decision reads it.

## Phase 7 — Ship

<!-- agent-dispatch: id=from-issue-ship-owner role=ship-owner model=opus effort=high -->
Agent(subagent_type="general-purpose", model="opus", effort="high") launches `ship-issue` as a fresh ship owner, not inline via `Skill`. By now this conversation carries every artifact of the flow; a fresh ~10k subagent returns one summary instead of ~100 turns over a 200–300k prefix.

Read `ship-handoff.md` for the exact subagent prompt — it carries the lifecycle envelope (`ledger_repo_root`, run, attempt, owner), branch, worktree, artifact paths, `review_state`, and the fixed report schema. When `ship-issue` is absent, the same file's inline fallback applies.

After receiving the ship report, from-issue owns the terminal durable write:
assemble its compact result, call `workflow-state finish`, then send the exact JSON
printed on stdout unchanged. A fresh ship agent never writes the owner's final
ledger result. Apply the same procedure to any Phase-6 execution
failure or Phase-7 stopped/failed report. `ship-issue` runs its own Phase 0–8; prefix its phases `ship-Phase-N` when narrating so the two sequences stay distinguishable.

## Notes

- Standing local-commit authorization covers spec, plan, doc, and fix commits (where the project documents it; otherwise follow the user's commit policy). Push, PR open/merge, force-push, and hook bypass stay per-action gated.
- Append `Co-Authored-By` unless `commit.coAuthoredBy` is false. **Never disable GPG signing defensively** — no `-c commit.gpgsign=false`, no `--no-gpg-sign`; surface signing failures.
- **PR bodies, comments, and subagent prompts use full URLs, not bare `#N`**; derive the slug from `repoSlug` if configured, else `git remote get-url origin`.
- If a phase reveals the previous one was wrong, back up to that phase and redo it. Don't paper over it.
