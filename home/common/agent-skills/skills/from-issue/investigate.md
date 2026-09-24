# Phase 0 detail — pre-flight queries and the investigation note

This included document receives values from the phase owner's retained `ResolvedProject`; use `bindings.tracker` and `bindings.vcs` and never resolve, infer, or read project policy.

Loaded from `SKILL.md` at Phase 0. The stop rules and worktree-safety inspection live in `SKILL.md`; this file carries the working detail.

## PR pre-flight queries

1. `<tracker-cli> pr list --state all --search "issue-<num>" --json number,title,headRefName,state`. The default search hits titles, bodies *and* branch names, catching PRs whose branch is `<bindings.vcs.worktree.prefix>issue-<num>-...` even when the title omits the number; don't narrow with `in:title,body`.
2. **Open PR**: verify the exact issue, head branch, target branch, and acceptance
   evidence. When it belongs to this requested work and existing authorization
   covers delivery, resume its worktree and shipping path; do not rebuild it.
   Unknown ownership, a competing attempt, a changed target, or different scope
   stops for that specific missing decision.
3. **Merged PR**: verify the same identity and compare the landed change and live
   tracker state with the issue's acceptance criteria. Finish authorized missing
   bookkeeping such as issue closure, or report the satisfied criteria and the
   exact remaining unknown. Do not rebuild delivered work. Unmet criteria define
   follow-up scope and require that scope decision; they do not make the old
   implementation current work again.
4. **Closed unmerged**: check why (`<tracker-cli> pr view <pr>` for body + comments). Duplicate/superseded/replaced → surface and stop. Otherwise it was abandoned: continue, and Phase 1 makes a fresh branch. In `--auto`, carry this into the spec's decision ledger.

## Investigate

1. `<tracker-cli> issue view <num> --json title,body,labels,comments,url,assignees,milestone`.
2. Read the references in the body: file paths, ADR numbers, commit SHAs, linked issues.
3. Skim the map's area files and their `adr/` dirs for terms and decisions the issue touches.
4. Grep the codebase for the concepts it names.
5. Post a short investigation note covering: **Restatement** in your own words; **Relevant existing code** (paths + one-line role each); **Documented constraints** (context terms, ADRs, standards that bind the work); **Open questions**; **Suggested scope boundary** (in vs. deliberately out); **Scope-size estimate** (rough files + lines, and whether the mechanical-only shortcut applies).

**Size gates measure product changes (C4):** the Phase-0 number is an *estimate* — no range exists yet, so nothing can be measured; estimate the product change alone, leaving out this run's retained artifact-directory outputs, because they are process output. Once the branch has a range, `diff-scope` is the accounting authority (ship-issue's Phase-5 gate carries the invocation and the thresholds): measure, never hand-count, and exclude this run's own artifacts by passing one `--artifact-path` per file it wrote — never an entire retained artifact directory. Historical artifacts that are themselves the requested product still count.
