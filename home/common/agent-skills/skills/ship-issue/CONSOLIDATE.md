# Consolidate Learnings

Phase 3 of `ship-issue`. Mine the session for high-signal learnings and promote them to docs that already exist — or drop them.

This file is project-agnostic. Destination doc paths come from `.claude/skills.config.json` (`docPaths.*`, `specDir`, `planDir`) resolved by the parent `ship-issue` skill. Any destination that the project doesn't declare (or whose file doesn't exist) simply has no home — see "The destination table" below.

## The bar

**Default to drop.** A junk doc entry costs more than a missed learning. Junk compounds: future agents read it and start discounting the section it lives in, which devalues the real content too. A missed learning recurs and gets caught next time. Asymmetry — bias toward drop.

**No abstract principles.** Concrete situation + concrete rule. "Regenerate lockfiles after integration→feature merge" is fine. "Be careful with merges" is not.

**Cross-reference, don't restate.** If a learning is a specific instance of an already-documented rule, append a one-line bullet to the existing rule, or skip entirely. Don't write a new subsection.

## The rubric

A candidate is promoted only if it passes ALL four:

1. **General** — applies to future work, not just this issue.
2. **Non-obvious** — a future reader can't derive it from the code + commit message alone.
3. **Load-bearing** — skipping it would cost someone an hour or more next time.
4. **Not already documented** — `grep -r` the relevant doc area before drafting.

Fail any → drop.

## The destination table

A surviving candidate maps to exactly one existing doc. **The destination must be a doc the project actually has** — resolve each row against the project config's `docPaths`. If the mapped doc path is absent (not configured, or the file doesn't exist), that learning type has no home → **drop it** (or, only if the user explicitly asks, propose creating the doc). The absence of a home is itself a signal that the learning isn't load-bearing yet.

| Type of learning | Destination (config key) |
|---|---|
| New domain term, clarified invariant | `docPaths.context` |
| Hard-to-reverse decision with real alternatives | New entry under `docPaths.adrDir` — must pass the three-part test: hard-to-reverse + surprising-without-context + result-of-a-real-trade-off |
| Tooling, CI, or operations quirk | `docPaths.gitWorktrees`, `docPaths.operationsDir`, or `docPaths.devenvTooling` — whichever covers the surface |
| Codebase-wide rule | `docPaths.standards` |
| Skill workflow issue (a phase failed predictably, a prompt was unclear, a step got skipped wrongly) | The relevant `.claude/skills/<name>/SKILL.md` (user or project scope) |

If the project ships format references next to the grilling skill (e.g. `grill-with-docs`'s `CONTEXT-FORMAT.md` / `ADR-FORMAT.md`), use them as the formatting guide for the `docPaths.context` / `docPaths.adrDir` rows. These are **optional pointers** — if those files don't exist, fall back to matching the format of the destination doc's existing neighbors.

If a candidate would require a brand-new top-level doc, that's a leap — push back unless the user explicitly wants the new doc.

## The procedure

### 1. Mine the source surface

Look only at what actually happened. Don't speculate about what could go wrong in the abstract. (`<integrationBranch>`, `<specDir>`, `<planDir>` come from the project config.)

- `git log <branch> ^origin/<integrationBranch> --oneline` — commits on this branch; look for `fixup!` / `squash!` patterns indicating review-blockers fixed, and merge commits indicating semantic conflicts that needed thought.
- `gh run list --branch <branch> --json conclusion,name,databaseId` + `gh run view <id>` for any failed CI runs that got resolved in-flow. (Skip when `issueTracker.kind=none`.)
- `git diff <first-commit> <head> -- '<specDir>/*issue-<num>*' '<planDir>/*issue-<num>*'` — spec/plan revisions during execution indicate where the original design was wrong (filenames are `YYYY-MM-DD-issue-<num>-<topic>*`).
- Conversation context: tooling surprises hit, escalations made, repeated friction.

### 2. Apply the rubric

For each candidate, run the four tests above. Apply the one-line test explicitly: "Would this exact entry have saved someone an hour somewhere?" If the answer isn't a clear yes, drop.

### 3. Assign destination

From the destination table. No clear destination (or the mapped doc doesn't exist in this project) → drop.

### 4. Propose

For each surviving candidate, present the user with:

```
Candidate:        <one-line summary>
Destination:      <doc path>
Draft:            <exact text to add, formatted for that destination>
Why:              <one sentence on the friction it prevents next time>
Saved-an-hour:    <concrete scenario where this would have saved time>
```

User responds per candidate: accept / refine / reject. Default to reject under uncertainty.

### 5. Apply

For each accepted candidate, edit the destination file inline. Match the format the destination already uses (context-doc entries match neighbors; ADRs match the ADR format reference if present, else the existing ADRs; coding-standards bullets match section style; operations doc entries match the surrounding table or list).

Commit accepted updates with `docs(<scope>): <one-line summary>`. One commit per destination file — keeps the history readable. Follow `commit.coAuthoredBy` for the trailer (default: include).

### 6. Empty outcome

If no candidates survived, report with the evidence trail from step 1:

> "No high-signal learnings to promote — continuing to PR. (`git log <branch> ^origin/<integrationBranch>`: N commits, no `fixup!`/`squash!`; `gh run list`: no failed runs; spec/plan diff: clean.)"

This is the expected outcome for most issues — but the empty outcome is a *claim*. Back it with the one-line search summary so a reviewer can confirm the mining actually happened. Don't force a learning that isn't there, and don't skip the mining to declare "empty" by default.
