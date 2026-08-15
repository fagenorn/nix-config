# Phase 0 detail — pre-flight queries and the investigation note

Loaded from `SKILL.md` at Phase 0. The stop rules and worktree-safety inspection live in `SKILL.md`; this file carries the working detail.

## PR pre-flight queries

1. `<tracker-cli> pr list --state all --search "issue-<num>" --json number,title,headRefName,state`. The default search hits titles, bodies *and* branch names, catching PRs whose branch is `<worktreePrefix>issue-<num>-...` even when the title omits the number; don't narrow with `in:title,body`.
2. **Open PR** for this issue: stop. Surface the URL and recommend `/ship-issue <num>` to resume it, or that the user close it first.
3. **Merged PR**: stop. Surface the merge commit; ask whether they meant a different issue or a follow-up.
4. **Closed unmerged**: check why (`<tracker-cli> pr view <pr>` for body + comments). Duplicate/superseded/replaced → surface and stop. Otherwise it was abandoned: continue, and Phase 1 makes a fresh branch. In `--auto`, carry this into the spec's decision ledger.

## Investigate

1. `<tracker-cli> issue view <num> --json title,body,labels,comments,url,assignees,milestone`.
2. Read the references in the body: file paths, ADR numbers, commit SHAs, linked issues.
3. Skim the map's area files and their `adr/` dirs for terms and decisions the issue touches.
4. Grep the codebase for the concepts it names.
5. Post a short investigation note covering: **Restatement** in your own words; **Relevant existing code** (paths + one-line role each); **Documented constraints** (context terms, ADRs, standards that bind the work); **Open questions**; **Suggested scope boundary** (in vs. deliberately out); **Scope-size estimate** (rough files + lines, and whether the mechanical-only shortcut applies).

**Size gates measure product changes (C4):** when estimating or later counting scope via `git diff --numstat`, exclude this run's own `specDir`/`planDir` artifacts — they are process output, not the product. Historical artifacts that are themselves the requested product still count.
