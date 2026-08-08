---
name: from-issue
description: Drive one tracker issue through investigate → spec → plan → review → execute in a worktree. Use for "work on issue #X"; pass --auto for autonomous mode.
argument-hint: "<issue number or URL> [--auto]"
---

# From Issue

Counterpart to `to-issues`. Take a single tracker issue from triage to merged code by chaining the canonical skills, with a human checkpoint at every phase.

## Project bindings (resolve first)

This skill is project-agnostic. Before acting, resolve project-specific values:

1. If `.claude/skills.config.json` exists at the project root, read it for the bindings below.
2. For any absent key (or no config file), auto-detect: issue tracker = `gh` if the git remote is github.com (else `glab`/none); verify commands from the manifest (package.json scripts, *.slnx/*.sln → dotnet test, Cargo.toml → cargo test, go.mod → go test, Makefile → make test); branches from the repo default.
3. Defaults when neither config nor detection yields a value: integrationBranch=main, defaultBranch=main, commit.coAuthoredBy=true, unsetGithubToken=false, specDir=.claude/specs, planDir=.claude/plans.
4. Degrade gracefully: any configured-but-absent doc path, sibling skill, or hints file is skipped silently — never read a file that does not exist, never hard-fail on a missing optional binding.

Keys this skill uses: `integrationBranch`, `defaultBranch`, `issueTracker{kind,cli}`, `unsetGithubToken`, `commit.coAuthoredBy`, `docPaths{context,adrDir,standards,architecture,gitWorktrees}`, `specDir`, `planDir`, `branchNaming{pattern,worktreePrefix}`, `projectHints`, `codex.planReview{enabled,focus}`.

`codex.planReview.enabled` defaults to `true` when absent. Set it to `false` to restore the fresh native reviewer for Phase 5. `codex.planReview.focus` defaults to `null`; when set, pass its project-specific emphasis to the reviewer in addition to `projectHints`. Existing project configurations require no migration.

Throughout this skill, `<tracker-cli>` means the resolved `issueTracker.cli` (default `gh`), `<integration-branch>` the resolved `integrationBranch` (default `main`), and `<default-branch>` the resolved `defaultBranch` (default `main`). When `issueTracker.kind=none`, skip every issue/PR-linkage step and operate on the branch alone (a "tracker URL" the user gives you is just a label).

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

Worktree-first is deliberate. Earlier versions of this flow ran brainstorm/grill/plan on the integration branch directly and only created the worktree before execute. Under parallel `--auto` runs that pattern caused two failure modes: (a) spec/plan commits made on the integration branch got cross-contaminated when another agent's index landed under your commit, and (b) when the worktree was finally created mid-flow it inherited local integration-branch state, which carried foreign in-flight commits from other agents. Branching off `origin/<integration-branch>` *before* any commits land eliminates both.

## Checkpoints

Checkpoint between every phase. Don't auto-chain. After each phase, state the artifact produced (file path or short summary) and wait for the user to confirm before invoking the next sub-skill.

The reason is failure cost: a wrong spec wastes one revision; a wrong plan wastes a worktree of execution. The earlier you catch a misalignment, the cheaper it is.

**Override:** if the invocation includes `--auto`, see "Autonomous mode" below — checkpoints become self-resolved decisions logged inline.

## Doc-grounded questions

During Phase 2 and Phase 3, ground in the project's docs before asking the user clarifying questions or presenting option sets. If the `doc-grounded-questions` skill is available, invoke it (via the Skill tool) — it forces the agent to read the context doc (`docPaths.context`), the relevant ADRs (`docPaths.adrDir`), and the coding-standards doc (`docPaths.standards`) first, so questions surface real unknowns instead of relitigating documented decisions. **If that skill is not available, fall back inline:** read whichever of those configured doc paths exist (skip any that don't), then form the question. Either way the grounding happens before the question.

In autonomous mode, the same procedure drives the self-answer step — you ground in the docs first, then answer the question yourself rather than passing it to the user.

## tracker-cli hygiene

If `unsetGithubToken` is true (config), `unset GITHUB_TOKEN` (or `env -u GITHUB_TOKEN`) before every `<tracker-cli>` call — some harnesses export a token without the target org's access, and the explicit literal commands in the phases below include this. If `unsetGithubToken` is false (the default), do **not** strip the token; the ambient credential is the one to use. Whichever applies, the rule extends uniformly to any `<tracker-cli>` call you add ad-hoc. If `docPaths.gitWorktrees` is configured and exists, it may document the project's specific stance on this.

## Skill tool invocations

Every sub-skill referenced in this flow — `superpowers:using-git-worktrees`, `superpowers:brainstorming`, `grill-with-docs`, `superpowers:writing-plans`, `doc-grounded-questions`, `codex-collaboration`, `superpowers:subagent-driven-development`, `ship-issue` — goes through the `Skill` tool when available, not paraphrased inline. The Skill tool fires the loader and the harness records the invocation; reading procedures from memory skips both, and the skill's progressive-disclosure resources never get pulled in. `codex-collaboration` is intentionally Claude-only and non-user-invocable; native Codex sessions therefore use the Phase-5 native reviewer fallback. **When a referenced sibling skill is not installed**, fall back to the inline behavior named in that phase (folding grill into the brainstorm, clarifying without the doc-grounding skill, reviewing with a fresh native agent, delivering via plain git/PR steps); don't hard-fail on a missing sibling.

`doc-grounded-questions` in particular is a hard gate when present: every decision point that would normally surface a clarifying question to the user (or self-answer one in `--auto`) requires a Skill-tool firing this turn. Don't skip because "you already read it" — re-invoke per decision so the body re-injects up-to-date pointers and binds the *specific* decision in front of you. If the skill is absent, re-read the configured doc paths per decision instead.

The phases below assume these rules and don't restate them for each sub-skill.

## Autonomous mode (`--auto`)

Detect by scanning the invocation arguments for the literal token `--auto` (e.g. `/from-issue 62 --auto`, `from-issue #62 --auto`). If present, run the whole flow end-to-end with no user checkpoints. If absent — including when the user just says "work on issue #62" — stay in interactive mode and use the per-phase checkpoints above. Default is off.

The shift is *what you do at a decision point*, not *what work gets done*. Every phase still produces the same artifact at the same quality bar. Brainstorm still happens. Grill still happens. Standards review still happens. You don't get to skip thinking — you only stop waiting for the user.

### The self-answer pattern

Whenever a phase or sub-skill would normally ask the user a clarifying question, present option sets, or pause at a `**CHECKPOINT**`:

1. **Ground first.** Invoke `doc-grounded-questions` if available (per the Skill-tool rule above), else re-read the configured doc paths. Re-read the sections that bind *this specific* decision; "I already read it earlier in the flow" doesn't substitute.

2. **Pick the most defensible default.** The choice that (a) aligns with documented invariants and ADRs, (b) matches existing precedent in the codebase, (c) honors the issue author's stated intent, and (d) keeps scope tight. When two options are both defensible, prefer the one that's smaller, more reversible, and more idiomatic to the surrounding code.

3. **Log the decision inline in the artifact.** Each artifact you produce (spec, plan, ADR) must include an `## Auto-resolved decisions` section listing every self-answered question. One entry per decision:

   ```markdown
   ### <short question / decision title>
   - **Question:** what would have been asked
   - **Choice:** what you picked
   - **Grounding:** the docs / code / issue references that justify it (link or quote)
   - **Alternative considered:** what you rejected and why
   ```

   This is the audit trail. A human reviewing the PR can read this section and challenge any choice without re-deriving it. The plan in Phase 4 carries the same section — same template, same fields. Standards-review fixes in Phase 5 extend (not replace) the plan's section. The discipline drops between Phase 2 and Phase 4 if you let the plan feel "mechanical"; it isn't.

4. **Continue.** Don't post the question to the user. Don't wait. Move to the next step.

### When *not* to auto-resolve

Autonomous mode is "trust the agent end-to-end" — there are no checkpoint gates. But two content-level stops from the existing flow still apply, because they are judgments about the issue itself, not user-approval gates:

- **Phase 0 wrong-issue-type stop.** If the issue is multiple issues bundled, a duplicate, a pure question, or otherwise not implementable, surface that finding and stop. Auto-mode means "decide without asking," not "implement something incoherent."
- **Phase 5 blocking standards findings.** Apply blocking fixes to the plan inline (as the interactive flow already does). If a blocker can't be fixed by editing the plan — it indicates the spec or the issue scope is wrong — back up the relevant phase, redo it, and log the loop in `Auto-resolved decisions`.

Phase 5 should-fix findings in `--auto`: apply inline by default and log them in `Auto-resolved decisions` with the reviewer's rationale. Exception: should-fixes implying a scope change (e.g. "the plan covers feature A but the spec promised A+B") — back up to the relevant phase rather than scope-creep the plan.

Everything else — option choices, scope boundary calls, ADR phrasing, plan task granularity — you decide and log.

### Sub-skill behavior

Sub-skills (`brainstorming`, `grill-with-docs`, `writing-plans`, `subagent-driven-development`, `ship-issue`) don't know about `--auto`. *You* are the agent invoking them, and *you* carry the autonomous-mode context. When a sub-skill instructs you to ask the user a clarifying question or wait for confirmation, run the self-answer pattern instead. The sub-skill's output still lands in the same file at the same quality bar.

## Phase 0 — Investigate

Build a shared mental model of what the issue is asking for *before* opening the brainstorm. Light touch — no files yet.

(When `issueTracker.kind=none`, skip the issue-fetch and PR pre-flight steps below; treat the user's description as the issue, and base the investigation on the named scope plus a codebase grep.)

### Pre-flight: existing PR / worktree check

Before fetching the issue, confirm nothing is already shipping it. A real incident burned ~4 hours when two parallel `--auto` sessions raced on the same issue and the second had no idea the first was already mid-flow.

1. `<tracker-cli> pr list --state all --search "issue-<num>" --json number,title,headRefName,state` (prefix with `unset GITHUB_TOKEN &&` only if `unsetGithubToken` is true) — default search hits PR titles, bodies, *and* branch names, so it catches PRs whose branch is `<worktreePrefix>issue-<num>-...` even if the title doesn't include the issue number. Don't narrow with `in:title,body` — that skips the branch-name match, which is exactly how the incident PR was nameable.
2. **Open PR** matching this issue: stop. Surface the PR URL and recommend `/ship-issue <num>` to resume the existing flow (CI poll, review fixes, merge), or that the user close the PR before retrying.
3. **Merged PR**: stop. The issue has already landed on the integration branch; surface the merge commit and ask whether the user meant a different issue or a follow-up.
4. **Closed-without-merge**: check the close reason first — `<tracker-cli> pr view <pr>` for body + comments. If marked duplicate / superseded / replaced by another PR, surface that and stop (don't re-implement work that landed under a different number). Otherwise the PR was likely abandoned; continue and Phase 1 creates a fresh branch. In `--auto`, log this as an Auto-resolved decision rather than asking the user.
5. `git worktree list | grep <worktreePrefix>issue-<num>-` — collect every match.
   - Zero matches: continue.
   - One match, no uncommitted work: clean up (`git worktree remove <path>` + `git branch -D <branch>`). This handles orphans from a prior run that exited mid-flow.
   - One match with uncommitted work: stop and ask the user — their in-progress state isn't yours to discard.
   - Multiple matches: stop and ask the user which to resume or discard. Steady-state shouldn't produce this, but it can accumulate after repeated aborts and the resolution depends on which run was most recent.

This check is cheap (one tracker call, one `git` call) and prevents the most expensive failure mode the flow has produced.

### Investigate

1. Fetch the issue: `<tracker-cli> issue view <num> --json title,body,labels,comments,url,assignees,milestone` (prefix with `unset GITHUB_TOKEN &&` only if `unsetGithubToken` is true).
2. Read references in the body (file paths, ADR numbers, commit SHAs, linked issues).
3. Skim the context doc (`docPaths.context`) and the ADR dir (`docPaths.adrDir`) for terms or decisions the issue touches — skip either if not configured/present.
4. Grep the codebase for the central concepts named in the issue.
5. Post a short investigation note in the conversation covering:
   - **Restatement** in your own words
   - **Relevant existing code** — paths + a one-line role each
   - **Documented constraints** — context-doc terms, ADRs, coding-standards sections that bind the work
   - **Open questions** for the user
   - **Suggested scope boundary** — what's in, what's deliberately out
   - **Scope-size estimate** — rough file count + lines touched, and whether the mechanical-only shortcut below applies

If the issue is actually multiple issues bundled, stop and suggest `to-issues` to break it up first. If it's a question or a duplicate, report that and stop.

**The Open questions section is mandatory even in `--auto`.** Self-answering happens in the spec's `## Auto-resolved decisions`, *not* by silently dropping the section from the Phase-0 note. The Phase-0 enumeration is the audit point: the spec's resolutions are downstream of it. If you can't think of any open questions, write "None — Phase 2 will surface anything missed" rather than omitting the bullet. Reviewers reading the transcript later look for this section to verify the agent actually thought about what was unknown.

### Mechanical-only shortcut

Declare the issue `mechanical-only` only when the entire planned change is deletion or renaming and has **no** behavioral, configuration, interface, generated-output, or semantic-documentation effect. File count and line count alone never qualify a change. Downstream phases lean: Phase 5 self-grades the plan against the same review contract; Phase 6 dispatches one implementer+reviewer pair for the whole change. The full pipeline still runs — brainstorm, grill, plan, ship. A mechanical plan does not need manufactured TDD framing; state why the shortcut applies and use direct verification instead.

**CHECKPOINT** — Confirm restatement + scope before brainstorming. For each open question in the investigation note, require explicit per-question disposition from the user: an answer, "defer to brainstorm" (resolve in Phase 2), or "agent-choose" (auto-resolve and log per the doc-grounding pattern). A bare "proceed" without dispositions means: re-prompt — the questions don't vanish on the way to Phase 2.

## Phase 1 — Worktree

Create the isolated workspace before any spec/plan/grill commits land — those commits go *in the worktree*, not on the integration branch. This is the structural fix for parallel-`--auto` cross-contamination (see "Worktree-first is deliberate" above).

1. `git fetch origin` (prefix with `unset GITHUB_TOKEN &&` only if `unsetGithubToken` is true) — get latest remote refs.
2. Invoke `superpowers:using-git-worktrees` (the skill encodes the destructive-ops carve-out and the worktree-prefix contract). Branch name follows `branchNaming.pattern` (default `issue-<num>-<slug>`) → `issue-<num>-<short-slug>`. The harness's `EnterWorktree` prepends `branchNaming.worktreePrefix` (default `worktree-`), so the on-disk branch becomes `<worktreePrefix>issue-<num>-<short-slug>`. Both forms are accepted downstream; don't strip the prefix manually. (If the worktree skill is absent, create the worktree with plain git: `git worktree add -b <branch> <path> origin/<integration-branch>`.)

   **Check position before calling the worktree tools.** A transcript audit found ~43% of all `EnterWorktree`/`ExitWorktree` failures are calls made while already positioned — the harness pins one worktree per session and refuses redundant or cross-pinned entries. Before `EnterWorktree`: compare `pwd` with the intended worktree path — already there → skip the call; pinned to a *different* worktree → `ExitWorktree` with `action: "keep"` first, then enter. Don't discover the pin state by letting the call fail.
3. **Base the worktree on `origin/<integration-branch>`**, not local integration branch. Local integration branch may carry foreign in-flight commits from parallel agents (other `/from-issue --auto` runs, or unrelated WIP). Branching off `origin/<integration-branch>` guarantees a clean base; the merge-with-integration-branch happens later via `ship-issue` Phase 1.
4. `cd` into the worktree. All subsequent phases (Brainstorm/Grill/Plan/StandardsReview/Execute) operate inside the worktree. Verify with `git rev-parse --git-common-dir ≠ git rev-parse --git-dir`.

**CHECKPOINT** — Confirm worktree path and base before brainstorming. In `--auto`, the base check is automatic but log the resulting commit SHA in the investigation note for the audit trail.

## Phase 2 — Brainstorm

Invoke `superpowers:brainstorming` to produce a design doc under `specDir` (default `.claude/specs`), committed in the worktree. (If that skill is absent, run the brainstorm inline: explore intent, requirements, and at least two design options before writing the spec.)

Before opening any new question, resolve every Phase 0 carryover — answer it from the user's Phase 0 disposition, lift it explicitly into the brainstorm, or auto-resolve it. Don't restart the question list with a fresh first question while earlier questions sit unanswered.

Before asking the first clarifying question, run the doc-grounding step (hard gate, per the Skill-tool rule above).

**CHECKPOINT** — User approves the spec file in writing.

## Phase 3 — Grill

Invoke `grill-with-docs` (project-local skill — use the bare name `grill-with-docs`, not `superpowers:grill-with-docs`; the latter doesn't exist and invoking both wastes context). It sharpens the spec against the context doc, surfaces glossary conflicts, and may produce new ADRs. ADRs and context-doc updates commit in the worktree alongside the spec; they ship to the integration branch when the PR merges, same as everything else.

**If `grill-with-docs` is not installed**, fold the grill into the brainstorm inline: re-read `docPaths.context` and `docPaths.adrDir` (whichever exist), challenge the spec's terminology against the project's existing vocabulary, and record any decisions that warrant an ADR directly in `docPaths.adrDir` (or note the absence of an ADR convention and capture the decision in the spec).

The doc-grounding step applies here too.

**CHECKPOINT** — Confirm all doc updates (context-doc edits, new ADRs) and the refined spec.

## Phase 4 — Plan

Invoke `superpowers:writing-plans` to produce an implementation plan under `planDir` (default `.claude/plans`), committed in the worktree. (If that skill is absent, write the plan inline as a numbered task list with explicit verification gates per task.)

**The plan file must include an `## Auto-resolved decisions` section** when `--auto` is on, and *should* include one when interactive — even there, the plan author makes judgment calls about task granularity, test framing, verification gates, and commit boundaries that warrant a record. Same Question / Choice / Grounding / Alternative-considered template as the spec.

**Plan-prose ≠ code-prose.** Anything the plan dictates that the implementer will copy verbatim into the codebase — a docstring, a `// ...` comment, a context-doc sentence, an ADR clause — must be phrased as the *live code will actually behave*, not as the plan hypothesises it will. Recurrent post-PR-review fix-up category: implementer copies plan-prose into a comment, code lands slightly different, prose becomes a lie. If you can't yet describe what the code *will* do precisely, write the prose as a TODO with the open question, not as a definitive statement — execute-phase rewrites it from the implemented code.

**CHECKPOINT** — User reviews the plan file.

## Phase 5 — Standards review

A plan reviewed only by the author risks blind spots — and the agent who just wrote the plan is the author. Unless Phase 0 marked the plan `mechanical-only`, choose the reviewer as follows:

1. Resolve `codex.planReview.enabled` (default `true`) and `codex.planReview.focus` (default `null`).
2. When enabled and the Claude-only `codex-collaboration` skill is available, invoke its `plan-review` operation. Pass the issue and acceptance criteria, Phase-0 investigation and open questions, the worktree base SHA, spec and plan paths, relevant `AGENTS.md`/`CLAUDE.md`, optional skills configuration, manifests, `projectHints`, configured documentation paths, detected verification commands, the optional review focus, and the review contract below. The skill owns foreground execution, isolation, read-only enforcement, result validation, and its one-time native-Claude fallback on a real Codex failure. A busy or concurrent reviewer is never a fallback condition.
3. When Codex review is disabled or `codex-collaboration` is unavailable (including when this skill runs natively in Codex), dispatch one fresh native reviewer (`Agent` tool, `general-purpose`) with no inherited context and give it the same inputs and review contract.

The review contract for either path is:

> Review the implementation plan at `<plan-path>` against the project's coding bar.
>
> First ground in the project's docs: invoke `doc-grounded-questions` if available, else read whichever of these exist — the context doc (`docPaths.context`), the relevant ADRs (`docPaths.adrDir`), the coding-standards doc (`docPaths.standards`), and the architecture doc (`docPaths.architecture`). Then read the issue body (`<tracker-cli> issue view <num>` — prefix with `unset GITHUB_TOKEN &&` only if `unsetGithubToken` is true), the spec at `<spec-path>`, and the plan.
>
> When checking specific findings, **read the live file at HEAD** rather than relying on snapshot/diff views — code may have been edited since the plan was written, and stale snapshots produce false-positive should-fixes.
>
> For each plan task, flag anything that violates the grounded constraints. Pay particular attention to: framework-first (custom executors/state machines where a framework primitive already exists), production-grade-by-default (half-finished branches, missing error paths at boundaries), DI rules, and the test-fixture conventions in the coding-standards doc.
>
> If `projectHints` is configured and the file exists, read it for project-specific review hints/examples and fold those into this pass (e.g. recurring repo-specific plan bugs that have escaped review before).
>
> Additionally, scan against this **common-miss checklist** — categories that have repeatedly slipped past plan review and surfaced only at PR review:
> - **UX alternate-dismiss paths.** Modal/dialog/typed-confirmation/destructive-action surfaces must specify state-reset behavior for every *user-reachable* dismiss path. Your finding for this category must include an itemized checklist — one line per path, marked with what the plan says (or "not specified") for each:
>   ```
>   - [ ] X button: <plan's behavior or "not specified">
>   - [ ] Cancel button: <…>
>   - [ ] Esc key: <…>
>   - [ ] Overlay click: <…>
>   - [ ] Browser back / navigation away: <…>
>   - [ ] Programmatic close (e.g. on success): <…>
>   ```
>   The checklist forces the *act* of checking; relying on the reviewer to mentally enumerate is how an Esc-key gap once leaked. Any **user-reachable** path the plan doesn't address is a Blocker. A path that's not user-reachable on this surface (e.g., no programmatic close because there's no success state) is fine — say so explicitly in the checklist, don't omit the row.
> - **Boundary-error fallbacks at unfamiliar-principal / missing-entity points.** Auth user that doesn't exist, admin not yet seeded, feature flag missing, downstream table empty. Does the plan name the failure mode and the graceful path, or does it assume the happy path? "Production-grade by default" fires here.
> - **Defensive guards against future refactor.** When the plan introduces a `switch` on an enum, a polymorphic dispatch, a base-class extension, or a new arm of an exception hierarchy — does it specify what *fails loudly* when the type/enum/hierarchy is extended later, so the next contributor doesn't silently fall into a default branch?
> - **Plan-prose / live-code parity.** Any docstring, comment, context-doc sentence, or ADR clause the plan tells the implementer to write — does the wording match what the code will *actually* do? Drift here is a PR-review fix-up commit waiting to happen.
> - **Stale prose audit.** Distinct from "plan-prose / live-code parity" above: that bullet checks prose the plan *dictates the implementer write*; this one checks prose that *already exists* in files adjacent to the diff. For every context-doc sentence, ADR clause, docstring, or comment near the PR's footprint, re-read the live file. Terminology the PR retires (renamed concepts, deprecated class names, removed fields) must be purged in *all* adjacent comments and doc references — not just the diff's immediate footprint. This is one of the most common post-PR-review fix-up categories.
> - **Dead branches after iteration.** If Phase 4 → Phase 5 revisions changed the design (e.g., "use the framework's collapsible primitive" replacing hand-rolled state, "switch from an explicit field to a derived value"), walk every code path the plan still describes and confirm each is reachable. Pivoted plans leave stranded `else` branches, unused props, and `if (legacyFlag)` arms that the implementer dutifully writes and the PR reviewer dutifully flags.
> - **Test-assertion specificity, not just scenarios.** Where the plan says "add a test that returns 400" or "asserts the array shape", grade whether the named assertion will *pin the documented contract* — error-body shape and content-type, ordering with discriminating rows, specific error-message format, role/aria attributes for UI. Tests that pass under any 400 emitter, against any non-null array, or by matching a substring of a transformed value aren't pinning anything; flag as Should-fix.
> - **Spec ↔ implementation message-format parity.** Operator-facing error messages, fallback strings, audit-trail formats, and UI status labels that the spec promises must match the implementation byte-for-byte (or the implementation must explain why its actual format is equivalent/better). A spec-promised exact string that falls through to a generic default is a real gap caught only at PR review when missed here.
> - **DRY against existing helpers.** For any new helper, hook, or utility the plan introduces, grep for similar prior patterns. If a near-duplicate exists, the plan should either reuse it or justify why a new one is needed. Duplicate helpers fixed only at PR review are a recurring waste.
>
> Output a structured review:
>
> - **Blocking** — must fix before execution
> - **Should-fix** — strong recommendation, justify if you skip
> - **Discussion** — judgment calls worth raising with the user
>
> Don't propose new features. Don't second-guess scope. Grade only against the bar.

**Mechanical-only shortcut.** If Phase 0 declared the plan `mechanical-only`, replace reviewer dispatch with a self-grade: read the issue, spec, plan, relevant live files, and coding standards, then grade against the same Blocking/Should-fix/Discussion buckets. Any behavioral, configuration, interface, generated-output, or semantic-documentation consequence disqualifies the shortcut, regardless of file count or diff size.

For a Codex review, verify every actionable finding against the live worktree before changing the plan; stale or unsupported findings are recorded as rejected, not silently applied. Record concise provenance (Codex version, review job identifier, base SHA, and whether native fallback was used) plus the disposition of each finding in the plan or Phase-5 audit note. Never copy the raw Codex transcript into project artifacts.

Apply blocking fixes inline to the plan file (this falls under the standing local-commit authorization). Bring should-fix items to the user; in `--auto`, apply them inline too. **Extend the plan's `## Auto-resolved decisions` section** (create it if Phase 4 didn't) with one entry per applied finding:

```markdown
### <short title — e.g. "B1: test-fixture isolation">
- **Question:** <the reviewer's note, verbatim or condensed>
- **Choice:** <what you edited>
- **Grounding:** <reviewer's rationale + doc cite if any>
- **Alternative considered:** <if you considered keeping the original; otherwise "Reviewer's call accepted as-is.">
```

This is the in-file audit trail the commit-message scope (`plan(issue-N): apply standards-review blockers`) doesn't carry — useful when a future reviewer is reading the plan stand-alone.

**One entry per finding, not consolidated.** When a Phase-5 finding *bears on* a question Phase 4 already self-answered — confirming it, refining it, or reversing it — append a *new* entry (`### S2: <reviewer's framing>`) rather than amending the original. The original entry stays verbatim; the reviewer's entry stands alongside, so a future reader can trace the design's evolution chronologically (Phase 4's choice first, Phase 5's pushback second).

When Phase 5 *reverses* the Phase 4 choice, the new entry's `Alternative considered` field describes what *the reviewer* rejected (typically the Phase 4 choice the reviewer found insufficient, with their grounding) — not what Phase 4 originally considered. The Phase 4 entry above already records that.

**CHECKPOINT** — Confirm standards review is clean.

## Phase 6 — Execute

Invoke `superpowers:subagent-driven-development`. It reads the plan, dispatches implementer subagents per task, and reviews each output. (If that skill is absent, execute the plan task-by-task yourself, running the verify commands and reviewing each task's diff before moving on.)

If Phase 0 declared the plan `mechanical-only`, dispatch a single implementer+reviewer pair for the whole change rather than per-task chains — the per-task ceremony adds no signal when there is only one mechanical task.

**CHECKPOINT** — Confirm the implementation is committed on the feature branch.

## Phase 7 — Ship

Dispatch `ship-issue` as a fresh subagent via the `Agent` tool (subagent_type `general-purpose`). Don't invoke it inline via the `Skill` tool — by Phase 7 this conversation already carries every `from-issue` artifact (investigate notes, brainstorm, grill, plan, standards-review, execute-phase implementer outputs). Continuing in-context means `ship-issue` does its full 100+ model turns over a ~200-300k accumulated context. A subagent gets a fresh ~10k-token context with only what we hand it, and returns one summary message — cuts ~1-3M weighted tokens per run versus same-context invocation.

**If `ship-issue` is not installed**, run the delivery inline with plain git/tracker steps: push the branch, open a PR against `<integration-branch>` (`<tracker-cli> pr create --base <integration-branch>`, prefixed with `unset GITHUB_TOKEN &&` only if `unsetGithubToken` is true), dispatch a fresh reviewer subagent over the diff, wait for CI (`<tracker-cli> pr checks --watch`), merge with a true merge commit (`--no-ff`), link/close the issue if `issueTracker.kind != none`, and clean up the worktree + branch. Honor `commit.coAuthoredBy` on any commit you create (see Notes). When `issueTracker.kind=none`, just merge the branch into `<integration-branch>` locally and clean up.

Subagent prompt (the handoff goes in the prompt, not a file — the subagent's starting context *is* the prompt):

```
You are running ship-issue for issue #<num> in <autonomous|interactive> mode. Use
"autonomous" only when the from-issue invocation included `--auto`; otherwise use
"interactive".

Handoff from from-issue:
  issue_number:   <num>
  branch:         <branch-name>
  worktree_path:  <absolute-worktree-path>
  spec_path:      <relative-from-repo-root>
  plan_path:      <relative-from-repo-root>
  head_sha:       <SHA at end of Phase 6 execute>
  auto:           true|false  (from --auto flag)
  summary:        <one paragraph: what shipped, key deltas the PR reviewer subagent
                   should weight heavily, anything non-obvious about scope>

Your task:
  1. Invoke the `ship-issue` skill via the Skill tool. Read its SKILL.md and follow
     every phase 0 → 8 in order. The pre-flight checks still run — the handoff is a
     hint, the worktree state is ground truth.
  2. In Phase 5 (PR review), dispatch the reviewer subagent as ship-issue instructs.
     Nested Agent calls are supported.
  3. In Phase 6, block on `<tracker-cli> pr checks --watch` per ship-issue's
     instructions.
  4. If auto is true, apply ship-issue's auto-mode rules throughout: apply Blocking
     and Should-fix items inline rather than surfacing; only Discussion items and
     genuinely blocked situations should return to me. If auto is false, honor every
     ship-issue checkpoint and confirmation; return anything requiring a user decision
     instead of treating it as autonomous.

Return to me, in your final message:
  - PR URL
  - merge commit SHA on the integration branch
  - issue close state
  - any Discussion items the reviewer raised
  - anything that needed manual intervention
```

**Phase-number namespace.** `ship-issue` has its own Phase 0–8 sequence (pre-flight, sync, verify, consolidate, PR, review, CI, merge, cleanup). When narrating progress in transcripts (and when the subagent reports back), prefix with `ship-Phase-N` to distinguish from `from-issue` phases; otherwise a reader sees `Phase 6 done → Phase 0 pre-flight → Phase 6 CI` and can't tell which `Phase 6` is which.

## Notes

- Standing local-commit authorization covers spec, plan, doc updates, and fix commits during this flow — don't re-confirm each commit (when the project documents such an authorization; otherwise follow the user's commit policy).
- **`Co-Authored-By` trailer follows `commit.coAuthoredBy` (default: include).** Append it on every commit produced by this flow (spec, plan, ADR, standards-fix, execute-phase work) unless `commit.coAuthoredBy` is false in the project config. The matching note in `ship-issue/SKILL.md` resolves the same way.
- Per-action confirmation still required for push, PR open/merge, force-push, hook bypass — these stay gated even mid-flow.
- **Don't disable GPG signing defensively** (no `-c commit.gpgsign=false`, no `--no-gpg-sign`). Signing failures aren't yours to work around — surface them. Standards review flags signing bypasses as blockers anyway, so the "defensive" disable costs you a recovery loop. The standing local-commit authorization does not extend to bypassing signing. (Respect `commit.gpgSign` from config when set: `inherit` = don't override the repo's signing config.)
- **PR bodies and comments use full URLs, not bare `#N`.** Writing `#107` in a PR body backlinks to whatever issue/PR has number 107 in the forge's resolution context, which can land on unrelated refs (cross-repo, archived issues, etc.). Use the full issue/PR URL (derive the repo slug from `repoSlug` if configured, else `git remote get-url origin`). This also applies to standards-review subagent prompts where you summarize references.
- If a phase reveals the previous phase was wrong (e.g., grill exposes a spec assumption that breaks the design), back up to that phase and redo. Don't paper over it.
