# ADR Format

ADRs live in the project's decision-record directory, sequentially numbered `0001-slug.md`. Scan the directory for the highest number and increment.

**Adaptive location.** Prefer `.claude/skills.config.json`'s `docPaths.adrDir`; otherwise follow whichever of `docs/adr/`, `docs/decisions/`, `doc/adr/`, `adr/` or `RFCs/` the repo already has. Default to `docs/adr/` only when neither tells you otherwise, and create the directory lazily with the first ADR.

## Template

```md
# {Short title of the decision}

{1-3 sentences: the context, what was decided, and why.}
```

An ADR is a paragraph. The value is recording *that* a decision was made and *why* — not filling out sections. Add `Status` front-matter (`proposed | accepted | deprecated | superseded by ADR-NNNN`) only in repos that actually revisit decisions, `Considered Options` only when a rejected alternative will otherwise be re-proposed, and `Consequences` only for downstream effects a reader would not derive.

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
