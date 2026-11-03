# Phase 0 detail — pre-flight queries and the investigation note

Loaded from `SKILL.md` at Phase 0. Build a shared mental model before the brainstorm; write no files yet. Run the PR pre-flight, then the worktree pre-flight, then investigate and post the note.

## PR pre-flight queries

1. `<tracker-cli> pr list --state all --search "issue-<num>" --json number,title,headRefName,state`. The default search hits titles, bodies *and* branch names; don't narrow with `in:title,body`.
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

## Worktree pre-flight

Run `git worktree list` and keep the entries whose bracketed branch field starts with `<bindings.vcs.worktree.prefix>issue-<num>-`:

- none → continue;
- one → **inspect before touching it**; a "clean" tree can still hold committed work that only ships at Phase 7. Check four signals: unpushed commits (`git log origin/<integration-branch>..<branch> --oneline`); workflow-state ledger attempts naming it that are `active` or `handed_off`; tracker/PR state referencing the branch; spec/plan artifacts under the retained specification and plan directories inside it. If **any** exist → prefer resume: resume that worktree when existing authorization covers the exact continuation; otherwise ask for the missing decision. On conflicting signals stop as blocked through the terminal return procedure. Deletion (`git worktree remove` + `git branch -D`) only when **provably disposable**: zero commits ahead, no active or handed-off ledger attempt, no spec/plan artifacts, no uncommitted work;
- one with uncommitted work → **stop and ask the user**; their in-progress state isn't yours to discard;
- several → stop and ask which to resume or discard.

## Investigate

1. `<tracker-cli> issue view <num> --json title,body,labels,comments,url,assignees,milestone`.
2. Read the references in the body: file paths, ADR numbers, commit SHAs, linked issues.
3. Skim the map's area files and their `adr/` dirs for terms and decisions the issue touches.
4. Grep the codebase for the concepts it names.
5. Post a short investigation note covering: **Restatement** in your own words; **Relevant existing code** (paths + one-line role each); **Documented constraints** (context terms, ADRs, standards that bind the work); **Open questions**; **Suggested scope boundary** (in vs. deliberately out); **Scope-size estimate** (rough files + lines, and whether the mechanical-only shortcut applies).

**Stops:** several issues bundled → stop and suggest `to-issues`; a question or a duplicate → report and stop. **Open questions is mandatory even in `--auto`** — self-answering happens in the spec's `## Decision ledger`; with nothing open, write "None — Phase 2 will surface anything missed".

**Size gates measure product changes:** a Phase-0 estimate covers the product change alone. Once the branch has a range, `diff-scope` is the accounting authority (ship-issue's Phase-5 gate carries the invocation and the thresholds): measure, never hand-count, and pass one `--artifact-path` per file this run wrote — never an entire retained artifact directory. Historical artifacts that are themselves the requested product still count.
