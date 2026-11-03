# ADR Format

ADRs live in the area they concern, `docs/areas/<slug>/adr/`, or in `system` when a decision spans areas or belongs to none, using the ADR home passed from the retained `bindings.paths.context` selection. Create the `adr/` directory with its first record.

- **Numbering is per directory**: `NNN-kebab-title.md`, three digits from `001`; take the next free number in that directory at merge time.
- **The id is `ADR-<slug>-NNN`**, the directory's slug plus the file's number, restated in the header `# ADR-<slug>-NNN — Title`. The full id is the only citation form anywhere, even inside its own area.
- **Parallel sessions** collide only within one area: the first branch to reach the integration branch keeps the number, and the later one renumbers its file, header and own citations before merging.
- **A migrated or moved record** takes the destination's next free number, moves through the VCS's own move, and gains a `- **Formerly:** ADR-<old-id>` line right after its `- **Status:**` line, or under the header when there is none. Living references are re-pointed in the same commit; citations inside other accepted records stay as written.
- Nobody maintains an ADR index: `ls` of an `adr/` directory is one.

## Template

```md
# ADR-<slug>-NNN — {Short title of the decision}

{1-3 sentences: the context, what was decided, and why.}
```

An ADR is a paragraph recording *that* a decision was made and *why*. Add `Status` (`proposed | accepted | deprecated | superseded by ADR-<slug>-NNN`) only in repos that revisit decisions, `Considered Options` only when a rejected alternative would otherwise be re-proposed, and `Consequences` only for effects a reader would not derive.

## The gate

Write an ADR only when all three hold:

1. **Hard to reverse**: changing course later carries real cost.
2. **Surprising without context**: a future reader would wonder why it was done this way.
3. **The result of a real trade-off**: there were genuine alternatives.

Typical passes: architectural shape, integration patterns between areas, technology choices with real lock-in, ownership and scope boundaries (the explicit no's especially), deliberate deviations from the obvious path, constraints invisible in the code, and rejections that would otherwise be re-litigated. Typical failures: swappable library picks, naming, anything the code states plainly or the coding standards settle.

A decision about what a *word* means is a glossary definition in the owning area's `CONTEXT.md`, not an ADR. When a decision constrains both design and vocabulary, the ADR states it and the glossary entry links to it.
