# Consolidate Learnings

Phase 3 of `ship-issue`. Mine the session for high-signal learnings and promote them to docs that already exist — or drop them.

This included document receives the phase owner's retained `ResolvedProject`; it uses passed `bindings.paths`, `bindings.vcs`, and `bindings.workflow` values without resolving or inferring policy.

Project-agnostic: destination paths come only from the parent’s retained `bindings.paths` and `capabilities.knowledge.*`. An authored unsupported knowledge capability takes its documented no-knowledge route.

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
| New domain term, clarified invariant | A passed `bindings.paths.context` destination |
| Hard-to-reverse decision with real alternatives | A passed context-area ADR destination, after the three-part test: hard-to-reverse + surprising-without-context + result-of-a-real-trade-off |
| Tooling, CI, or operations quirk | The passed `bindings.paths` destination that covers the surface |
| Codebase-wide rule | A passed `bindings.paths.standards` destination |
| Skill workflow issue (a phase failed predictably, a prompt was unclear, a step got skipped wrongly) | The caller-provided skill source destination |

Where the project ships format references next to the grilling skill (`grill-with-docs`'s `CONTEXT-FORMAT.md` / `ADR-FORMAT.md`), use them for the context/ADR rows; if absent, match the destination doc's existing neighbours.

A candidate requiring a brand-new top-level doc is a leap — push back unless the user explicitly wants it.

## The procedure

### 1. Mine the source surface

Look only at what actually happened; don't speculate about what could go wrong in the abstract.

- `git log <branch> ^origin/<integration-branch> --oneline` — look for `fixup!`/`squash!` and merge commits that needed thought.
- Use the caller-selected verification command for failed CI runs; skip it when `capabilities.tracker` is unsupported.
- Diff the caller-provided artifact paths from `bindings.paths.artifacts` — spec/plan revisions during execution mark where the original design was wrong.
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

Edit each accepted destination inline, matching the format that doc already uses. Commit as `docs(<scope>): <one-line summary>`, one commit per destination file, following `bindings.vcs`.

### 6. Empty outcome

The expected outcome for most issues — but it's a *claim*, so back it with the evidence trail from step 1 so a reviewer can confirm the mining actually happened:

> "No high-signal learnings to promote — continuing to PR. (`git log <branch> ^origin/<integration-branch>`: N commits, no `fixup!`/`squash!`; selected verification: clean; artifact diff: clean.)"

Don't force a learning that isn't there, and don't skip the mining to declare "empty" by default.
