---
name: from-issue
description: Drive one tracker issue through investigate → spec → plan → review → execute in a worktree. Use for "work on issue #X"; pass --auto for autonomous mode.
argument-hint: "<issue number or URL> [--auto]"
---

# From Issue

Counterpart to `to-issues`. Take one tracker issue from triage to merged code by chaining the canonical skills, with a human checkpoint at every phase.

## Files beside this one

- **`AUTO.md`** — autonomous-mode rules. Read it *once*, now, if the invocation arguments contain the literal token `--auto` (`/from-issue 62 --auto`, `from-issue #62 --auto`). Otherwise never read it.
- **`REVIEW-CONTRACT.md`** — the Phase-5 reviewer contract. Reviewer text: hand it over **by absolute path**, never read it into this conversation.

## Project bindings (resolve first)

1. Read `.claude/skills.config.json` at the project root if it exists.
2. Auto-detect what it doesn't set: issue tracker = `gh` if the remote is github.com, else `glab`/none; verify commands from the manifest (npm scripts, dotnet, cargo, go, make); branches from the repo default.
3. Defaults when neither yields a value: integrationBranch=main, defaultBranch=main, commit.coAuthoredBy=true, unsetGithubToken=false, specDir=.claude/specs, planDir=.claude/plans, codex.planReview.enabled=true, codex.planReview.focus=null.
4. Degrade gracefully: a configured-but-absent doc path, sibling skill, or hints file is skipped silently. Never read a file that doesn't exist; never hard-fail on a missing optional binding.

Keys used: `integrationBranch`, `defaultBranch`, `issueTracker{kind,cli}`, `unsetGithubToken`, `commit.coAuthoredBy`, `docPaths{context,contextMap,standards,architecture,gitWorktrees}` (`docPaths.adrDir` is a legacy override; ADR homes normally come from the map's areas), `specDir`, `planDir`, `branchNaming{pattern,worktreePrefix}`, `projectHints`, `codex.planReview{enabled,focus}`.

`<tracker-cli>` = resolved `issueTracker.cli`; `<integration-branch>`, `<default-branch>` likewise. When `issueTracker.kind=none`, skip every issue/PR-linkage step and operate on the branch alone (a "tracker URL" the user gives you is just a label).

**tracker-cli hygiene.** When `unsetGithubToken` is true, prefix *every* `<tracker-cli>` call — including ones you add ad-hoc — with `unset GITHUB_TOKEN &&`; some harnesses export a token without the target org's access. When false (default), use the ambient credential.

## Lifecycle identity

Resolve the optional lifecycle envelope supplied by a dispatcher:
`ledger_repo_root`, `run_id`, `attempt`, `owner`, and normalized `worktree`.
Treat all five as one identity; never guess a missing field. Preserve the
immutable ledger_repo_root exactly as supplied, and keep it distinct from the
separate owner worktree recorded on the attempt. Every `workflow-state` command in
this owner or its delegated remainder uses `--repo-root <ledger_repo_root>`;
never substitute the current checkout or owner worktree. A direct standalone invocation remains compatible
and does not require a ledger. An interactive standalone run may initialize its
own run with `workflow-state init-run` only when the user explicitly requests
durable orchestration; in that case resolve its ledger root once and carry it as
`ledger_repo_root`. Otherwise follow the canonical flow unchanged.

## The flow

```
0. Investigate           → summary + open questions (no files yet)
1. Worktree (skill)      → isolated workspace based on origin/<integration-branch>; spec/plan/grill commits land here
2. Brainstorm (skill)    → <specDir>/<date>-<topic>-design.md
3. Grill (skill)         → spec refinements + context-doc / ADR updates
4. Plan (skill)          → <planDir>/<date>-<feature>.md
5. Standards review      → independent Codex plan review, native fallback, or mechanical self-grade
6. Execute (skill)       → subagent-driven-development
7. Ship (skill)          → ship-issue: merge integration branch, PR, review, CI, merge, cleanup
```

## Checkpoints

Checkpoint between every phase; don't auto-chain. State the artifact produced (path or short summary) and wait for the user before invoking the next sub-skill. A wrong spec costs one revision; a wrong plan costs a worktree of execution.

**Override:** with `--auto`, checkpoints become self-resolved decisions logged inline — see `AUTO.md`. Two content-level stops survive there: the Phase-0 wrong-issue-type and pre-flight stops, and Phase-5 blocking findings that editing the plan can't fix.

## Auto-resolved decisions (artifact discipline)

Every artifact this flow produces — spec, plan, ADR — carries a section named exactly `## Auto-resolved decisions` listing each question the agent answered instead of the user. Mandatory under `--auto`; expected interactively too, since the author still calls task granularity, test framing, verification gates, and commit boundaries. One entry per decision:

```markdown
### <short question / decision title>
- **Question:** what would have been asked
- **Choice:** what you picked
- **Grounding:** the docs / code / issue references that justify it (link or quote)
- **Alternative considered:** what you rejected and why
```

**Never consolidate entries.** Phase-5 findings *extend* the plan's section instead of amending Phase-4 entries, so a reader can trace the design chronologically. When a Phase-5 entry reverses a Phase-4 choice, its `Alternative considered` describes what *the reviewer* rejected.

## Doc grounding

Phases 2–5 ground in the project's docs before their first clarifying question, option set, or review pass. Invoke `doc-grounded-questions`: it reads the context map / context doc, the ADRs owned by the areas it loaded (`docs/areas/<slug>/adr/`, plus `system`), and `docPaths.standards`, then caches the result in the worktree's git-dir `GROUNDING.md` (`"$(git rev-parse --git-dir)/GROUNDING.md"` — never a working-tree path, which would get committed and collide across parallel runs).

**Ground once per phase, not once per decision.** After the phase's first pass, read `GROUNDING.md` instead of re-running it; re-invoke only when a decision reaches an area the cache doesn't cover, then append that area. Each new phase starts a new cache. Without the skill, do the same by hand: read whichever configured doc paths exist, write the same `GROUNDING.md`, reuse it for the rest of the phase.

## Skill-tool invocations

Sub-skills named here — `worktrees`, `design`, `grill-with-docs`, `writing-plans`, `doc-grounded-questions`, `codex-collaboration`, `sdd`, `ship-issue` — go through the `Skill` tool, never paraphrased from memory; the tool fires the loader and pulls in the skill's progressive-disclosure resources. `codex-collaboration` is Claude-only and non-user-invocable, so native Codex sessions take the Phase-5 native-reviewer path.

**Never hard-fail on a missing sibling** — run the phase inline instead: brainstorm as intent + requirements + ≥2 design options; grill by re-reading the map's areas and their `adr/` dirs, challenging the spec's terminology against the project's vocabulary, and recording ADR-worthy decisions in the owning area's `adr/` (or in the spec if there's no ADR convention); plan as a numbered task list with a verification gate per task; execute task-by-task, running the verify commands and reviewing each diff; ship per the Phase-7 fallback.

## Dispatch and budget rules

**Structured report-backs.** A subagent's final message is re-read by its caller on every later turn (~87 re-reads per report, measured). Every `Agent` dispatch here states a fixed return schema in its prompt: artifact paths, a one-word verdict/state, ≤500 characters of notes. Details go in worktree files, never in the report. Use the tiered agent types where the task fits — `implementer`, `reviewer`, `mechanic` — over `general-purpose`.

**Executable phase gate.** At every phase boundary, including Phase 0 through
Phase 7, call `workflow-state progress` when lifecycle identity exists. Pass the
observed turn count and context tokens when available, the completed phase, and
truthful booleans for whether the next phase needs this context, committed
artifacts fully reconstruct it, and the remainder is self-contained. Do not fabricate usage:
omit unavailable `--turn-count` or `--context-tokens`. Use the
defaults `--turn-ceiling 120 --context-ceiling 150000 --turn-headroom 2
--context-headroom 10000`. Obey the returned action exactly; the closed set is
`continue | fresh_start | handoff | delegate`:

1. **`continue`** — proceed in this conversation.
2. **`fresh_start`** — start a fresh conversation from committed artifacts; do
   not carry conversational state.
3. **`handoff`** — beneath `ledger_repo_root`, validate the established run
   directory and create only its non-symlink `handoffs/` directory if missing.
   Never pre-create or touch the destination leaf; the `handoff` skill owns safe
   first-file creation. Invoke `handoff` with a destination beneath
   `.superpowers/workflows/<run-id>/handoffs/`, then repeat `workflow-state
   progress` with `--handoff-path <exact-path>` to finalize `handed_off` on the
   same attempt, and stop. Resume later with `workflow-state launch
   --resume-handoff <exact-path>` and the same identity.
4. **`delegate`** — dispatch the entire remainder to a fresh agent with the
   lifecycle envelope and artifact paths.

Without lifecycle identity, retain direct standalone compatibility: apply the
same action order locally, using the 120-turn/150000-token ceilings, and use the
default interactive handoff behavior.

## Terminal return procedure

Use this one procedure for Phase-0 content stops, budget stops, execution failure,
and Phase-7 success whenever lifecycle identity exists. Assemble a temporary JSON
file with exactly `issue`, `state`, `pr_url`, `merge_sha`, `issue_closed`,
`discussion_items`, and `notes` (`notes` is at most 500 characters). Pass it with
`--result-file <path>` to `workflow-state finish` using the exact run, issue,
attempt, and current time. Capture stdout; only after that durable write succeeds,
send the exact JSON from stdout unchanged to the caller.

The rule is: failure to persist is a failure to finish. Surface it and never report the issue as merged or completed.
Without lifecycle identity, send the same compact schema
directly so existing standalone callers remain compatible.

## Phase 0 — Investigate

Build a shared mental model *before* opening the brainstorm. No files yet. (When `issueTracker.kind=none`, skip the fetch and PR pre-flight: the user's description is the issue.)

### Pre-flight: existing PR / worktree check

Confirm nothing is already shipping this issue — two sessions racing on one issue is the most expensive failure this flow produces, and the check costs one tracker call plus one `git` call.

1. `<tracker-cli> pr list --state all --search "issue-<num>" --json number,title,headRefName,state`. The default search hits titles, bodies *and* branch names, catching PRs whose branch is `<worktreePrefix>issue-<num>-...` even when the title omits the number; don't narrow with `in:title,body`.
2. **Open PR** for this issue: stop. Surface the URL and recommend `/ship-issue <num>` to resume it, or that the user close it first.
3. **Merged PR**: stop. Surface the merge commit; ask whether they meant a different issue or a follow-up.
4. **Closed unmerged**: check why (`<tracker-cli> pr view <pr>` for body + comments). Duplicate/superseded/replaced → surface and stop. Otherwise it was abandoned: continue, and Phase 1 makes a fresh branch. In `--auto`, log this as an Auto-resolved decision.
5. `git worktree list | grep <worktreePrefix>issue-<num>-`:
   - none → continue;
   - one, clean → remove it (`git worktree remove <path>` + `git branch -D <branch>`), an orphan from a run that exited mid-flow;
   - one with uncommitted work → **stop and ask the user**; their in-progress state isn't yours to discard;
   - several → stop and ask which to resume or discard.

### Investigate

1. `<tracker-cli> issue view <num> --json title,body,labels,comments,url,assignees,milestone`.
2. Read the references in the body: file paths, ADR numbers, commit SHAs, linked issues.
3. Skim the map's area files and their `adr/` dirs for terms and decisions the issue touches.
4. Grep the codebase for the concepts it names.
5. Post a short investigation note covering: **Restatement** in your own words; **Relevant existing code** (paths + one-line role each); **Documented constraints** (context terms, ADRs, standards that bind the work); **Open questions**; **Suggested scope boundary** (in vs. deliberately out); **Scope-size estimate** (rough files + lines, and whether the mechanical-only shortcut applies).

If the issue is several issues bundled, stop and suggest `to-issues`. If it's a question or duplicate, report that and stop.

Every Phase-0 early stop above uses the terminal return procedure when lifecycle identity
exists: write a `stopped` or `failed` result through `workflow-state finish`
before notifying the caller.

**Open questions is mandatory even in `--auto`** — self-answering happens in the spec's `## Auto-resolved decisions`, not by dropping the section, which is the audit point the resolutions hang off. With nothing open, write "None — Phase 2 will surface anything missed".

### Mechanical-only shortcut

Declare `mechanical-only` only when the entire change is deletion or renaming with **no** behavioral, configuration, interface, generated-output, or semantic-documentation effect; file and line counts never qualify a change on their own. Then Phase 5 self-grades against `REVIEW-CONTRACT.md` and Phase 6 dispatches one implementer+reviewer pair for the whole change. Every phase still runs. Skip manufactured TDD framing: state why the shortcut applies and verify directly.

**CHECKPOINT** — Confirm restatement + scope. Require a per-question disposition for each open question: an answer, "defer to brainstorm", or "agent-choose" (auto-resolve and log). A bare "proceed" means re-prompt — the questions don't vanish on the way to Phase 2.

## Phase 1 — Worktree

Create the workspace before any spec/plan/grill commit lands; those commits go *in the worktree*, never on the integration branch.

When a lifecycle envelope exists, use its exact absolute `worktree` as the
attempt workspace. Re-check that it is absent from the filesystem and from
`git worktree list`, then create the worktree at that exact path from
`origin/<integration-branch>`. If the path is occupied or mismatched, fail the attempt
through the terminal return procedure; never remove unknown contents and never choose another path.
The envelope identity remains bound to this path through shipping and cleanup.
Direct standalone invocation keeps the standard `worktrees` flow below, including
its configured naming and worktree-root behavior.

1. `git fetch origin`.
2. For direct standalone use, invoke `worktrees` (it encodes the destructive-ops carve-out and the prefix contract). For lifecycle use, invoke it only if it accepts the envelope's exact path without renaming; otherwise use its documented fallback `git worktree add -b <branch> <exact-envelope-path> origin/<integration-branch>`. Branch follows `branchNaming.pattern` (default `issue-<num>-<slug>`); `EnterWorktree` prepends `branchNaming.worktreePrefix` (default `worktree-`), so the standalone on-disk branch is `<worktreePrefix>issue-<num>-<short-slug>`. Both branch forms are accepted downstream — don't strip the prefix.

   **Check position before calling the worktree tools.** ~43% of `EnterWorktree`/`ExitWorktree` failures are calls made while already positioned; the harness pins one worktree per session and refuses redundant or cross-pinned entries. Before `EnterWorktree`, compare `pwd` with the intended path: already there → skip the call; pinned elsewhere → `ExitWorktree` with `action: "keep"` first. Don't discover the pin state by letting the call fail.
3. **Base on `origin/<integration-branch>`**, never the local branch, which may carry other agents' in-flight commits; branching off the remote ref before any commit lands is what stops parallel runs cross-contaminating each other. The merge with the integration branch happens later, in `ship-issue`.
4. `cd` into the worktree; every later phase runs inside it. Verify `git rev-parse --git-common-dir` ≠ `git rev-parse --git-dir`.

**CHECKPOINT** — Confirm worktree path and base. In `--auto` the base check is automatic, but log the resulting SHA in the investigation note.

## Phase 2 — Brainstorm

Invoke `design` for a design doc under `specDir`, committed in the worktree.

Resolve every Phase-0 carryover before opening a new question — answer it from the user's disposition, lift it into the brainstorm, or auto-resolve it. Don't restart the question list while earlier questions sit unanswered. Ground before the first clarifying question.

**CHECKPOINT** — User approves the spec file in writing.

## Phase 3 — Grill

Invoke `grill-with-docs`. It sharpens the spec against the context doc, surfaces glossary conflicts, and may produce ADRs; those and any context-doc edits commit in the worktree alongside the spec and ship when the PR merges.

**CHECKPOINT** — Confirm all doc updates and the refined spec.

## Phase 4 — Plan

Invoke `writing-plans` for a plan under `planDir`, committed in the worktree, carrying its own `## Auto-resolved decisions` section.

**Plan-prose ≠ code-prose.** Anything the plan dictates that the implementer copies verbatim into the codebase — docstring, comment, context-doc sentence, ADR clause — must describe how the live code *will actually behave*, not how the plan hypothesises it. Otherwise the code lands slightly different and the prose becomes a lie (a recurring post-PR fix-up). If you can't describe the behavior precisely yet, write a TODO with the open question; the execute phase rewrites it from the implemented code.

**CHECKPOINT** — User reviews the plan file.

## Phase 5 — Standards review

A plan reviewed only by its author risks blind spots, and you are the author. Unless Phase 0 marked it `mechanical-only`:

1. Resolve `codex.planReview.enabled` (default `true`) and `.focus` (default `null`; when set, pass its emphasis alongside `projectHints`).
2. **Enabled and `codex-collaboration` available** → invoke its `plan-review` operation. It assembles the packet itself (its SKILL.md enumerates the contents) and owns foreground execution, isolation, read-only enforcement, validation, and a one-time native fallback on a real Codex failure — a busy or concurrent reviewer is never a fallback condition. Supply the issue and acceptance criteria, the Phase-0 investigation and open questions, the worktree base SHA, the spec and plan paths, the optional focus, and — as the review contract — **the absolute path to `REVIEW-CONTRACT.md` beside this file**, which it reads into the packet.
3. **Disabled or unavailable** (including when this skill runs natively in Codex) → dispatch one fresh `reviewer` agent, no inherited context, same inputs, same `REVIEW-CONTRACT.md` path, told to read that file first.

**The contract travels by path, never inlined** — pasting reviewer text here costs the orchestrator its full length for the rest of the session.

**Mechanical-only:** replace the dispatch with a self-grade — read the issue, spec, plan, live files, and `REVIEW-CONTRACT.md`, then grade against the same Blocking / Should-fix / Discussion buckets. Any behavioral, configuration, interface, generated-output, or semantic-documentation consequence disqualifies the shortcut.

Verify every actionable finding against the live worktree before touching the plan; stale or unsupported ones are recorded as rejected, not silently applied. Record provenance in the plan (reviewer, job id, base SHA, whether fallback was used) plus each disposition, and never copy a raw reviewer transcript into project artifacts.

Apply blocking fixes inline to the plan (standing local-commit authorization). Bring should-fix items to the user; in `--auto`, apply them too. Extend the plan's `## Auto-resolved decisions` with one entry per applied finding, titled by finding ID (`### B1: test-fixture isolation`): **Question** = the reviewer's note, **Choice** = what you edited, **Grounding** = their rationale plus any doc cite, **Alternative considered** = what you weighed, or "Reviewer's call accepted as-is."

**CHECKPOINT** — Confirm standards review is clean.

## Phase 6 — Execute

Invoke `sdd`: it reads the plan, dispatches an implementer per task, and reviews each output.

If the plan is `mechanical-only`, dispatch a single implementer+reviewer pair for the whole change; per-task ceremony adds no signal for one mechanical task.

**CHECKPOINT** — Confirm the implementation is committed on the feature branch.

sdd's report includes `review_state` (`clean | residuals | unknown`) from its two-axis
final review; carry it verbatim into the Phase-7 handoff — ship-issue's Phase-5
degradation decision reads it.

## Phase 7 — Ship

Dispatch `ship-issue` as a fresh subagent via the `Agent` tool (`general-purpose`) — not inline via `Skill`. By now this conversation carries every artifact of the flow, and ship-issue's ~100 turns over that 200–300k prefix costs ~1–3M weighted tokens versus a fresh ~10k subagent that returns one summary.

Absent → deliver inline: push the branch, open a PR against `<integration-branch>`, dispatch a fresh reviewer subagent over the diff, wait for CI (`<tracker-cli> pr checks --watch`), merge `--no-ff`, close the issue, clean up worktree + branch. With `issueTracker.kind=none`, merge locally and clean up.

Subagent prompt (the handoff goes in the prompt, not a file — the subagent's starting context *is* the prompt):

```
You are running ship-issue for issue #<num> in <autonomous|interactive> mode. Use
"autonomous" only when the from-issue invocation included `--auto`; otherwise use
"interactive".

Handoff from from-issue:
  ledger_repo_root: <immutable ledger root from the lifecycle envelope>
  run_id:            <run id from the lifecycle envelope>
  attempt:           <attempt from the lifecycle envelope>
  owner:             <owner from the lifecycle envelope>
  owner_worktree:    <separate owner worktree from the lifecycle envelope>
  issue_number:   <num>
  branch:         <branch-name>
  worktree_path:  <absolute-worktree-path>
  spec_path:      <relative-from-repo-root>
  plan_path:      <relative-from-repo-root>
  head_sha:       <SHA at end of Phase 6 execute>
  review_state:   <clean | residuals | unknown — from sdd's report>
  auto:           true|false  (from --auto flag)
  summary:        <one paragraph: what shipped, key deltas the PR reviewer subagent
                   should weight heavily, anything non-obvious about scope>

Your task:
  1. Invoke the `ship-issue` skill via the Skill tool. Read its SKILL.md and follow
     every phase 0 → 8 in order. The pre-flight checks still run — the handoff is a
     hint, the worktree state is ground truth.
  2. In Phase 5 (PR review), follow ship-issue's path selection — it may dispatch
     zero (empty merge-delta), one, or two reviewer subagents.
     Nested Agent calls are supported.
  3. In Phase 6, block on `<tracker-cli> pr checks --watch` per ship-issue's
     instructions.
  4. If auto is true, apply ship-issue's auto-mode rules throughout: apply Blocking
     and Should-fix items inline rather than surfacing; only Discussion items and
     genuinely blocked situations should return to me. If auto is false, honor every
     ship-issue checkpoint and confirmation; return anything requiring a user decision
     instead of treating it as autonomous.

Return to me, as your final message, exactly this report — details live in the
PR and the worktree, not the report:
  issue:            <num>
  state:            merged | stopped | failed
  pr_url:           <url>
  merge_sha:        <sha on the integration branch>
  issue_closed:     true | false
  discussion_items: <reviewer's Discussion/Minor items, verbatim, labeled by axis
                     when the two-axis path ran; [] if none>
  notes:            <≤500 chars: anything that needed manual intervention>
```

**Phase-number namespace.** `ship-issue` runs its own Phase 0–8; prefix its phases `ship-Phase-N` when narrating or reporting so the two sequences stay distinguishable.

After receiving the ship report, from-issue owns the terminal durable write:
assemble its compact result, call `workflow-state finish`, then send the exact JSON
printed on stdout unchanged. A fresh ship agent never writes the owner's final
ledger result. Apply the same terminal return procedure to any Phase-6 execution
failure or Phase-7 stopped/failed report.

## Notes

- Standing local-commit authorization covers spec, plan, doc, and fix commits in this flow — don't re-confirm each one (where the project documents such an authorization; otherwise follow the user's commit policy). Push, PR open/merge, force-push, and hook bypass stay per-action gated.
- Append `Co-Authored-By` to every commit this flow produces unless `commit.coAuthoredBy` is false.
- **Never disable GPG signing defensively** — no `-c commit.gpgsign=false`, no `--no-gpg-sign`. Surface signing failures; the local-commit authorization doesn't extend to bypassing them, and standards review flags bypasses as blockers. Respect `commit.gpgSign` when set (`inherit` = don't override the repo).
- **PR bodies, comments, and subagent prompts use full URLs, not bare `#N`** — a bare number resolves against the forge's context and can land on an unrelated cross-repo or archived ref. Derive the slug from `repoSlug` if configured, else `git remote get-url origin`.
- If a phase reveals the previous one was wrong (the grill exposes a spec assumption that breaks the design), back up to that phase and redo it. Don't paper over it.
