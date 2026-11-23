# ADR Format

ADRs live in the area they concern, `docs/areas/<slug>/adr/`, or in `system` when a decision spans areas or belongs to none, using the ADR home passed from the retained `bindings.paths.context` selection; the first record creates `adr/`.

- **Numbering is per directory**: `NNN-kebab-title.md` from `001`; at merge take one past the highest number ever used there; a deleted number is never reused.
- **The id is `ADR-<slug>-NNN`**, restated in the header `# ADR-<slug>-NNN — Title`, and is the only citation form, even inside its own area.
- **Parallel sessions** collide only within one area: the first branch to merge keeps the number; the later one renumbers its file, header and own citations.
- **A migrated or moved record** takes the destination's next number through the VCS's own move and gains a `**Formerly:** ADR-<old-id>` line under the header; living references are re-pointed in the same commit, citations inside other records stay.
- **A record is current or gone**: an amendment edits it in place; a superseded record is deleted in the change that supersedes it.
- `ls` of an `adr/` directory is its index.

## Template

```md
# ADR-<slug>-NNN — {Short title}

{One paragraph: the context, the decision, the rejected alternative and why.}
```

A record is its header, an optional `**Formerly:**` line and one paragraph, at most 1,500 bytes: no section, list or status line. The context-map lint counts each breach, and a record over the cap may not grow.

## The gate

A decision record is written only in design and grilling, never by a delivery agent, and only when it is hard to reverse, surprising without context, a real trade-off and names its rejected alternative. Else how it works goes to the code, its tests and module docstring; a rule for every change to a standard with an id; a word's meaning to the glossary; a one-off choice or a bug's story to the issue and commit message.
