# ADR Format

ADRs live in the area they concern: `docs/areas/<slug>/adr/`, named `NNN-kebab-title.md`. **Each directory numbers its own records** — three digits, starting at `001`. Writing one means listing that directory and taking its next free number at merge time; what other areas have numbered is irrelevant.

**Which directory.** The area whose `governs:` globs cover the code the decision constrains, or `docs/areas/system/` when it spans areas or belongs to none. The map's Areas table is the list to choose from — ADR homes are derived from the map, not configured. (`docPaths.adrDir` is a legacy override, honoured only in repos still on a single central ADR directory.) Create the `adr/` directory lazily, with the first record that needs it.

**The id is `ADR-<slug>-NNN`** and the header line restates it: `# ADR-<slug>-NNN — Title`, where `<slug>` equals the containing area directory's name and `NNN` equals the filename's number. Both are linted. That full id is the only citation form anywhere in the repo — never a bare number, not even from inside the record's own area.

**Parallel sessions** can now only collide inside one area, and the rule is first-to-land: the branch that reaches the integration branch first keeps the number; the later branch renumbers itself — file, header, and its own citations — before merging.

**A record that was migrated or moved** carries a `- **Formerly:** ADR-<old-id>` line — immediately after its `- **Status:**` line where the repo carries one, otherwise directly under the header — whether the old id is a four-digit leftover from a migration or another area's `ADR-<slug>-NNN`. That line is the grep path from any historical citation to where the record now lives; living references are re-pointed at the same time, but citations inside other accepted records stay as they were written.

## Template

```md
# ADR-<slug>-NNN — {Short title of the decision}

{1-3 sentences: the context, what was decided, and why.}
```

An ADR is a paragraph. The value is recording *that* a decision was made and *why* — not filling out sections. Add `Status` (`proposed | accepted | deprecated | superseded by ADR-<slug>-NNN`) only in repos that actually revisit decisions, `Considered Options` only when a rejected alternative will otherwise be re-proposed, and `Consequences` only for downstream effects a reader would not derive.

## The gate

Write an ADR only when all three hold:

1. **Hard to reverse** — changing your mind later carries real cost.
2. **Surprising without context** — a future reader will look at the code and wonder why on earth it was done this way.
3. **The result of a real trade-off** — there were genuine alternatives and one was picked for stated reasons.

Miss any one and skip it. Easy to reverse: you will just reverse it. Unsurprising: nobody will wonder. No alternative: there is nothing to record beyond "we did the obvious thing." Most decisions in a session fail this gate, and an ADR log that grows with every issue has stopped being readable.

Typical passes: architectural shape, integration patterns between areas, technology choices carrying real lock-in, ownership and scope boundaries (the explicit no's especially), deliberate deviations from the obvious path, constraints invisible in the code, and rejections that would otherwise be re-litigated.

Typical failures: library picks you could swap in an afternoon, naming, anything the code states plainly, and anything already settled by the coding standards.

## Relationship to the glossary

A decision that settles what a *word* means is not an ADR — it is a definition, and it belongs in the owning area's `CONTEXT.md`. Write an ADR when the decision constrains the *design*; write a glossary entry when it constrains the *vocabulary*. When both, the ADR states the decision and the glossary entry links to it.
