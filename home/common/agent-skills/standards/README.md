# Standards

Three layers, most specific wins. Machine-global layers live here (`~/.agents/standards/`); the project layer lives in the repo.

| Layer | Where | Content |
|---|---|---|
| 0 — the bar | `the-bar.md` | Universal principles, every language, every project. |
| 1 — stack | `stacks/{dotnet,typescript-react,node,python}.md` | Project-independent idioms and trap libraries for one language or framework. Version-stamped. |
| 2 — project | the repo's `docs/standards/` | Deltas only: layout, fixture machinery, telemetry names, tenant rules, migration registries. |

## Precedence

Direct user instruction > Layer 2 (project) > Layer 1 (stack) > Layer 0 (the bar) > general convention. More specific always overrides more general — the same rule that makes "match the file you're editing" beat personal preference. A recurring conflict between a layer and what the code actually does is a bug in one of them; fix it in the work that touches it, not as a separate refactor.

## Loading

Nobody reads a whole standards corpus. Briefs paste **Layer 0 in full** (~600 tokens), plus **only the shards whose globs intersect the change**: a Layer-1 shard when the diff's file extensions match it, a Layer-2 shard when its `governs:` glob matches a touched path. Reviewer Standards-axis briefs take the same set plus the Fowler smell baseline. Reviewers read the pasted brief and load no skills of their own.

## The Layer-2 contract

A repo's `docs/standards/` is a directory of shards plus a **README index of at most 40 lines**, one row per shard carrying its `governs:` globs and a one-line gist — the same index-not-store discipline as `CONTEXT-MAP.md`.

- **Deltas only.** Anything that restates Layer 0 or 1 gets deleted, not copied. If a rule is true for every project on this stack, it belongs upstream in `stacks/`.
- **Case law is written rule-first**: the rule in at most two sentences, plus one issue or ADR link. The narrative lives in the issue. Incident memoirs are what make a standards file grow linearly with project age.
- **Process content is not a standard.** Deploy checklists go to `.claude/hints/`, review procedure to `REVIEW-CONTRACT.md`, lint commands nowhere — the environment already names them.
