# Autonomous mode (`--auto`)

Read this file once, when you detect `--auto` in the invocation. It replaces the checkpoint
behavior in `SKILL.md`; everything else in `SKILL.md` still applies.

The shift is *what you do at a decision point*, not *what work gets done*. Every phase still
produces the same artifact at the same quality bar. Brainstorm still happens. Grill still happens.
Standards review still happens. You don't get to skip thinking — you only stop waiting for the user.

Direct autonomous acquisition always includes both `new_run` and
`owner_unavailable` in every strict request, and both fields are `false` unless
the current user instruction explicitly authorizes that exact transition.
Self-answering never infers `owner_unavailable` from a restart, missing process
handle, silence, or an active ledger, and never infers `new_run` from terminal
replay, a reopened tracker, or a desire to continue. Process, tracker, and
terminal observations are facts, not authorization. A resume is not a takeover:
resuming a `suspended` attempt requires neither `new_run` nor `owner_unavailable` — suspension is not a terminal replay, so re-entry clears it with both flags left `false`.

## The self-answer pattern

Wherever a phase or sub-skill would ask the user a clarifying question, present option sets, or pause
at a `**CHECKPOINT**`:

1. **Ground first.** Use this phase's `GROUNDING.md` cache (see `grounding.md` beside `SKILL.md`). If the
   decision reaches into an area the cache doesn't cover, load that area and append it.
2. **Pick the most defensible default** — the choice that aligns with documented invariants and ADRs,
   matches existing precedent in the codebase, honors the issue author's stated intent, and keeps
   scope tight. When two options are both defensible, prefer the smaller, more reversible, more
   idiomatic one.
3. **Log it** as a row in the spec's `## Decision ledger` (the table format in `decision-ledger.md`),
   applying the non-obvious-only filter — routine splits, commit boundaries, and obvious verification
   commands are not rows. Plans and ADRs cite the ID. This is the audit trail: a human reviewing the
   PR can challenge any choice without re-deriving it.
4. **Continue.** Don't post the question. Don't wait.

Auto-resolving a checkpoint never skips `workflow-state progress`: persist the
gate decision at every phase checkpoint and obey its returned action before the
next phase starts. If it returns a durable handoff, invoke `handoff` at the
per-run destination, finalize it through `workflow-state progress`, and stop.
For every ordinarily owned terminal result, call `workflow-state finish`
successfully before any notification to the dispatcher; persistence always
precedes notification. The only exception is the successful direct Phase-5 relay:
the delegated fresh owner has already persisted the canonical terminal result, so
the earlier controller must not call `workflow-state finish` again. A
delegated-owner dispatch failure remains an ordinarily owned terminal result and
must be persisted before notification.

Sub-skills (`design`, `grill-with-docs`, `writing-plans`, `sdd`,
`ship-issue`) don't know about `--auto`. *You* carry the autonomous-mode context — when one tells you
to ask or wait, run the self-answer pattern instead.

## When *not* to auto-resolve

There are no checkpoint gates, but two content-level stops still apply, because they are judgments
about the work itself rather than user-approval gates:

- **Phase 0 wrong-issue-type stop.** If the issue is several issues bundled, a duplicate, a pure
  question, or otherwise not implementable, surface that and stop. Auto-mode means "decide without
  asking", not "implement something incoherent". The same holds for the Phase-0 pre-flight stops
  (open/merged PR, dirty or multiple matching worktrees, and a matching worktree whose
  disposability cannot be proven — prefer resuming it; never delete on ambiguity).
  When lifecycle identity exists, finalize this terminal result through the
  SKILL.md terminal return procedure before stopping.
- **Phase 0 fog gate.** Before any worktree exists, test the grounded issue: can every open question
  be *phrased precisely* and answered from the docs, codebase precedent, or the issue itself with a
  defensible default? Vague-but-phraseable questions are normal `--auto` work — self-answer them.
  **Fog** is different: a question you cannot state sharply, a load-bearing term the docs mark
  undefined or out-of-scope, no acceptance criterion that would make any answer falsifiable. Fog is
  an abort — stop before creating anything, name each foggy question in the stop report, and emit a
  `wayfind` decision ticket per question (when that skill and a tracker are available; otherwise the
  stop report carries the list). Abort conservatively: fog is the exception, autonomy stays the
  default posture.
- **Phase 5 blocking findings.** Apply blocking fixes to the plan inline. If a blocker can't be fixed
  by editing the plan — it means the spec or the issue scope is wrong — back up to that phase, redo
  it, and log the loop in the decision ledger.

Should-fix findings: apply inline and log with the reviewer's rationale. Exception: a should-fix that
implies a scope change ("the plan covers A but the spec promised A+B") — back up rather than
scope-creep the plan. Everything else — option choices, scope boundary calls, ADR phrasing, plan task
granularity — you decide and log.

## Phases 2–4 run as subagents

Interactive mode runs these phases inline and conversationally. **In `--auto` they are dispatched**,
because brainstorm and grill transcripts are the single largest context sink in the flow and none of
it is needed downstream — the artifacts are.

**The orchestrator (this session) holds only three things: the Phase-0 issue summary, the resolved
config bindings, and each phase's returned report.** Brainstorm and grill conversation must never
enter this context. Don't ask a subagent to "show its reasoning"; the reasoning belongs in the
committed artifact.

Both dispatches select the `issue-owner` matrix role on Opus/high explicitly;
design quality is worth paying for here. Purely mechanical dispatches elsewhere
in the flow use `mechanic` on Sonnet/high; reviewer-shaped first passes use
`reviewer` on Opus/high.

Both prompts must carry, inline (the subagent starts with no context and loads no skills of its own
beyond the exceptions named below):

- the Phase-0 issue summary and scope boundary,
- the resolved bindings it needs (`specDir`, `planDir`, `docPaths.*`, `projectHints`,
  `commit.coAuthoredBy`, `<tracker-cli>`, `unsetGithubToken`),
- the absolute worktree path, and an instruction to `cd` there and commit its artifacts there,
- the self-answer pattern above and the `## Decision ledger` table format with its non-obvious-only
  filter, pasted verbatim from `decision-ledger.md`,
- the fixed return schema, with "details live in the committed files, not in your report".

**Skill exception.** Each subagent *should* invoke, through its own `Skill` tool, the globally
installed skills its phase names — `grill-with-docs` and `doc-grounded-questions` for the design
subagent, `writing-plans` and `doc-grounded-questions` for the plan subagent, plus
`design` if present. Those load in the subagent's context, not yours. If one isn't
installed, it uses the inline fallback named in the corresponding `SKILL.md` phase.

### Design subagent — Phases 2 + 3

<!-- agent-dispatch: id=from-issue-design-grill role=issue-owner model=opus effort=high -->
Agent(subagent_type="general-purpose", model="opus", effort="high") launches the autonomous design-and-grill owner.

One dispatch covering brainstorm and grill. It produces the design doc under `specDir`, applies the
grill's refinements to it, and writes any context-doc updates and ADRs — all committed in the
worktree. Splitting these into two dispatches would mean re-establishing the whole design in a second
prompt for no gain.

After the final mutation, write a candidate producer report, run
`artifact-budget validate-report --boundary producer`, and return only validated stdout bytes.
never inline artifact contents or member paths. The exact `complete` report is:

```
{"state":"complete","artifact":{"kind":"design-spec","path":"<root relative to repo>","metrics":{"root_bytes":<int>,"total_bytes":<int>,"file_count":<int>,"largest_member_bytes":<int>},"budget_status":"within_budget"},"notes":"<bounded note>"}
```

The exact over-budget report includes the checker's ordered, non-empty
`violations` array:

```
{"state":"decompose_required","artifact":{"kind":"design-spec","path":"<root relative to repo>","metrics":{"root_bytes":<int>,"total_bytes":<int>,"file_count":<int>,"largest_member_bytes":<int>},"budget_status":"over_budget","violations":["root_bytes"]},"notes":"<bounded note>"}
```

For `failed`, `artifact` is exactly `null` before a root exists or exactly
`{"kind":"design-spec","path":"<root relative to repo>"}` after one exists;
metrics, budget status, and violations are forbidden in both failed rows.
The orchestrator keeps only the artifact root and metrics; ADR paths and ledger
choices stay in the spec.

### Plan subagent — Phase 4 (+ mechanical Phase 5)

<!-- agent-dispatch: id=from-issue-planning role=issue-owner model=opus effort=high -->
Agent(subagent_type="general-purpose", model="opus", effort="high") launches the autonomous planning owner.

Writes the implementation plan package under `planDir`, committed in the worktree, with a `## Task index`
carrying each task's risk lane; it cites decision-ledger rows by ID and appends new non-obvious
plan-level decisions to the spec's ledger. Give it the validated spec artifact
root and metrics plus notes — not a transcript. `SKILL.md`'s plan-prose ≠
code-prose rule goes in the prompt.

When Phase 0 declared the issue `mechanical-only`, this dispatch also performs the Phase-5 self-grade
(read issue, spec, plan, live files, standards; grade against Blocking / Should-fix / Discussion) and
applies its own blocking fixes before returning.

After the final mutation, write a candidate producer report, run
`artifact-budget validate-report --boundary producer`, and return only validated stdout bytes.
never inline artifact contents or task member paths. The exact `complete` report is:

```
{"state":"complete","artifact":{"kind":"implementation-plan","path":"<root relative to repo>","metrics":{"root_bytes":<int>,"total_bytes":<int>,"file_count":<int>,"largest_member_bytes":<int>},"budget_status":"within_budget"},"notes":"<bounded note>"}
```

The exact over-budget report includes the checker's ordered, non-empty
`violations` array:

```
{"state":"decompose_required","artifact":{"kind":"implementation-plan","path":"<root relative to repo>","metrics":{"root_bytes":<int>,"total_bytes":<int>,"file_count":<int>,"largest_member_bytes":<int>},"budget_status":"over_budget","violations":["root_bytes"]},"notes":"<bounded note>"}
```

For `failed`, `artifact` is exactly `null` before a root exists or exactly
`{"kind":"implementation-plan","path":"<root relative to repo>"}` after one
exists; metrics, budget status, and violations are forbidden in both failed
rows. `complete` plus any status other than `within_budget` is a contract error.

### Mandatory direct implementation-owner rollover

This section applies to every module-owned direct autonomous run. Phase 5 is
the last phase owned by the controller that acquired the persisted
`direct-owner` envelope; implementation and delivery belong to one fresh owner.

#### Mandatory transfer gate

First, finish Phase 5 and confirm that the controller has
dispositioned every Blocking and accepted Should-fix finding. Apply accepted
review edits and any decision-ledger writes, then commit the reviewed plan and
ledger. After the last mutation, run fresh
`artifact-budget check --kind design-spec` and
`artifact-budget check --kind implementation-plan` checks. Retain each
checker's `root_bytes`, `total_bytes`, `file_count`, and
`largest_member_bytes`, and require both results to be `within_budget`. If a
commit hook changes either artifact, repeat the check and commit sequence until
the committed roots and retained measurements agree. Require a clean worktree,
then resolve the full lowercase 40-hex current commit as `reviewed_head_sha`;
that commit is the content identity reviewed at this gate.

Once no conversational dependency remains, call `workflow-state progress` for
completed Phase 5 with truthful available usage and the exact gate values
`next_needs_context=false`, `artifacts_sufficient=true`, and
`remainder_self_contained=true`. Require the persisted action to be `delegate`;
then dispatch exactly one fresh issue owner at the existing
`from-issue-phase-delegate` tier. This mandatory transfer includes
mechanical-only direct autonomous runs.

The continuation is one closed JSON object shaped like this representative
value:

```json
{
  "owner": {
    "interface_version": 1,
    "kind": "owner",
    "ledger_repo_root": "/absolute/primary-checkout",
    "run_id": "direct-74-000001",
    "issue": 74,
    "attempt": 1,
    "owner": "74:1",
    "action_id": "74:1:1",
    "launch_kind": "spawn",
    "worktree": "/absolute/issue-worktree",
    "handoff_path": null,
    "deadline_at": "2026-08-20T12:00:00Z"
  },
  "reviewed_head_sha": "0123456789abcdef0123456789abcdef01234567",
  "spec_artifact": {
    "kind": "design-spec",
    "path": ".claude/specs/issue-74.md",
    "metrics": {
      "root_bytes": 1000,
      "total_bytes": 1000,
      "file_count": 1,
      "largest_member_bytes": 1000
    },
    "budget_status": "within_budget"
  },
  "plan_artifact": {
    "kind": "implementation-plan",
    "path": ".claude/plans/issue-74.md",
    "metrics": {
      "root_bytes": 2000,
      "total_bytes": 6000,
      "file_count": 3,
      "largest_member_bytes": 2000
    },
    "budget_status": "within_budget"
  }
}
```

Pass the unchanged owner object, `reviewed_head_sha`, and the two measured
artifact blocks only:

- no artifact contents;
- no task-member paths;
- no review transcript;
- no conversation summary;
- no alternate worktree;
- no reconstructed lifecycle field; and
- no authorization flag.

Repository bindings are re-resolved in the delegated worktree.

#### Fresh delegated owner

Before reading either artifact, re-resolve `branchPattern` and `worktreePrefix`
from repository bindings in `owner.worktree`. Quote the pattern's literal bytes,
substitute decimal `owner.issue` for `<num>` and
`[a-z0-9][a-z0-9-]*` for `<slug>`, and accept exactly the resulting pattern with
either the resolved prefix or no prefix. Take normalized `owner.worktree`'s final path component
and require it to match that binding-derived accepted branch regex; that component
is the deterministic `expected_branch`. Require
`git -C owner.worktree branch --show-current` to equal `expected_branch`. A
pattern, path, or current-branch mismatch is a contract failure before either
artifact root is read. Only after that branch check, verify the current clean HEAD.
Require its full commit ID to equal `reviewed_head_sha`.
Verify both roots are tracked at that exact reviewed HEAD.
Next, independently run `artifact-budget check` for each root and compare all four metrics with the
continuation. Any mismatch stops the attempt as a contract failure.

After those checks pass, adopt the owner envelope as the existing lifecycle
identity; the fresh owner must not call `direct-owner` or perform any other
acquisition. It must begin at Phase 6, invoke `sdd` with the reviewed plan, and
validate the SDD producer report under the existing contract.

After SDD is validated, call `workflow-state progress` for completed Phase 6
with truthful available usage and `next_needs_context=false`,
`artifacts_sufficient=true`, and `remainder_self_contained=true`. Require the
persisted action `delegate`. For this already-delegated implementation owner,
that Phase-6 delegate is fulfilled by the existing fresh Phase-7 ship owner with
`auto: true`; it must not dispatch a second issue owner.

After validating the ship owner's ship-summary bytes, call
`workflow-state progress` for completed Phase 7. Make the terminal result file
and finish invocation the ledger-only remainder; use truthful available usage
and the same three gate values, require persisted `delegate`, and use the
existing ledger-only bookkeeper route.
Give the bookkeeper an exact two-command sequence and nothing else: first
`~/.agents/bin/workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <issue:attempt:launch>`
with this owner's own `action_id`, then the exact `workflow-state finish` command.
It executes exactly that sequence and relays the `finish` stdout; it decides
nothing and edits nothing. It runs `finish` only after a `current: true` answer
from a well-formed `check-launch` on exit 0. On `current: false`, a non-zero
exit, or output it cannot parse, it must write nothing, print the canonical
re-entry line as its whole result, and stop — a superseded launch's ship report
is not this run's terminal result to record. The fresh implementation owner
must return only the exact canonical JSON printed by that durable finish.

For mechanical-only direct autonomous work, the fresh owner invokes the
existing mechanical Phase-6 mechanic/reviewer route without changing its order
or ownership, then performs the same Phase-6 progress, fresh shipping, Phase-7
ledger-only progress, and terminal sequence.

#### Earlier controller stop

The earlier controller's
post-delegation action set is exactly validate, relay, and stop. For the
received bytes, run
`artifact-budget validate-report --boundary ship-summary`; after successful
validation, relay the canonical bytes unchanged to its caller and stop.

The earlier controller does not invoke `sdd`.
It does not edit implementation files.
It does not reacquire or call `direct-owner`.
It does not start or create a new attempt.
It does not dispatch a second owner.
It does not call `workflow-state finish` after delegation.
It does not continue after the delegated report. A dispatch failure is the only
terminal result it persists, and that failure is
never permission to implement locally.

### Other Phase 5–7 routes

Mechanical-only module-owned direct autonomous runs are excluded from this section
because they use the mandatory rollover above. The existing
mechanical-only ordering and ownership for other acquisition routes remains
unchanged.

Dispatcher-owned autonomous, explicitly durable interactive, and ledger-free
interactive owners retain their existing behavior: Phase 5 dispatches the
reviewer (or `codex-collaboration`) with `REVIEW-CONTRACT.md`'s path, Phase 6
runs `sdd`, and Phase 7 dispatches `ship-issue` with the appropriate handoff.
Reviewer, SDD, and shipping contracts remain unchanged for these routes, and
the owning controller continues to verify and disposition findings.

At any Phase-6 or Phase-7 push, PR-open, or merge gate the lifecycle guard does
not stand — a repository the guard does not cover, or a merge it fails closed on
— do not die at the prompt: follow `SKILL.md`'s suspension procedure, suspending
`blocked_on: human_gate` and printing the canonical re-entry line, so a later
human approval resumes the same attempt without penalty.
