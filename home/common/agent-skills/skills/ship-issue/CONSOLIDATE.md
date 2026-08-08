# Consolidate Learnings

Phase 3 of `ship-issue`. Mine the session for high-signal learnings and promote them to docs that already exist — or drop them.

Project-agnostic: destination paths come from `.claude/skills.config.json` (`docPaths.*`, `specDir`, `planDir`) as resolved by the parent skill. A destination the project doesn't declare has no home — see the table below.

## The bar

**Default to drop.** A junk entry costs more than a missed learning: junk compounds, because future agents discount the whole section it lives in, while a missed learning just recurs and gets caught next time.

**No abstract principles.** Concrete situation + concrete rule. "Regenerate lockfiles after integration→feature merge" is fine; "be careful with merges" is not.

**Cross-reference, don't restate.** If a learning is a specific instance of an already-documented rule, append a one-line bullet to that rule or skip entirely. Don't write a new subsection.

## The rubric

Promote only if the candidate passes ALL four:

1. **General** — applies to future work, not just this issue.
2. **Non-obvious** — a future reader can't derive it from the code + commit message alone.
3. **Load-bearing** — skipping it costs someone an hour or more next time.
4. **Not already documented** — `grep -r` the relevant doc area before drafting.

Fail any → drop.

## The destination table

A surviving candidate maps to exactly one **existing** doc. If the mapped path is absent (unconfigured, or the file doesn't exist), that learning has no home → **drop it** (or, only on explicit user request, propose creating the doc). The absence of a home is itself evidence the learning isn't load-bearing yet.

| Type of learning | Destination (config key) |
|---|---|
| New domain term, clarified invariant | `docPaths.context` |
| Hard-to-reverse decision with real alternatives | New entry under `docPaths.adrDir` — must pass the three-part test: hard-to-reverse + surprising-without-context + result-of-a-real-trade-off |
| Tooling, CI, or operations quirk | `docPaths.gitWorktrees`, `docPaths.operationsDir`, or `docPaths.devenvTooling` — whichever covers the surface |
| Codebase-wide rule | `docPaths.standards` |
| Skill workflow issue (a phase failed predictably, a prompt was unclear, a step got skipped wrongly) | The relevant `.claude/skills/<name>/SKILL.md` |

Where the project ships format references next to the grilling skill (`grill-with-docs`'s `CONTEXT-FORMAT.md` / `ADR-FORMAT.md`), use them for the context/ADR rows; if absent, match the destination doc's existing neighbours.

A candidate requiring a brand-new top-level doc is a leap — push back unless the user explicitly wants it.

## The procedure

### 1. Mine the source surface

Look only at what actually happened; don't speculate about what could go wrong in the abstract.

- `git log <branch> ^origin/<integrationBranch> --oneline` — look for `fixup!`/`squash!` (review blockers fixed) and merge commits (semantic conflicts that needed thought).
- `gh run list --branch <branch> --json conclusion,name,databaseId` + `gh run view <id>` for failed CI runs resolved in-flow. (Skip when `issueTracker.kind=none`.)
- `git diff <first-commit> <head> -- '<specDir>/*issue-<num>*' '<planDir>/*issue-<num>*'` — spec/plan revisions during execution mark where the original design was wrong.
- Conversation context: tooling surprises, escalations, repeated friction.

### 2. Apply the rubric

Run the four tests on each candidate, plus the one-line test stated explicitly: "Would this exact entry have saved someone an hour somewhere?" Anything short of a clear yes → drop.

### 3. Assign destination

From the table. No clear destination, or the mapped doc doesn't exist here → drop.

### 4. Propose

```
Candidate:        <one-line summary>
Destination:      <doc path>
Draft:            <exact text to add, formatted for that destination>
Why:              <one sentence on the friction it prevents next time>
Saved-an-hour:    <concrete scenario where this would have saved time>
```

The user responds per candidate: accept / refine / reject. Default to reject under uncertainty.

### 5. Apply

Edit each accepted destination inline, matching the format that doc already uses. Commit as `docs(<scope>): <one-line summary>`, one commit per destination file, following `commit.coAuthoredBy`.

### 6. Empty outcome

The expected outcome for most issues — but it's a *claim*, so back it with the evidence trail from step 1 so a reviewer can confirm the mining actually happened:

> "No high-signal learnings to promote — continuing to PR. (`git log <branch> ^origin/<integrationBranch>`: N commits, no `fixup!`/`squash!`; `gh run list`: no failed runs; spec/plan diff: clean.)"

Don't force a learning that isn't there, and don't skip the mining to declare "empty" by default.
