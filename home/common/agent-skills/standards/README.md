# Standards

Three layers, most specific wins. Machine-global layers live here (`~/.agents/standards/`); the project layer lives in the repo.

| Layer | Where | Content |
|---|---|---|
| 0 — the bar | `the-bar.md` | Universal principles, every language, every project. |
| 1 — stack | `stacks/{dotnet,dotnet-data,dotnet-ai,typescript-react,node,python}.md` | Project-independent idioms and trap libraries for one language or framework. Version-stamped. |
| 2 — project | the repo's `docs/standards/` | Deltas only: layout, fixture machinery, telemetry names, tenant rules, migration registries. |

## Rule ids

Every rule in the three layers is one `###` heading that opens with its id, written `### B12. Fail loud`, the form the planning rules' `R1` to `R9` use.

| Layer file | Prefix |
|---|---|
| `the-bar.md` | `B` |
| `stacks/dotnet.md` | `NET` |
| `stacks/dotnet-data.md` | `NET` |
| `stacks/dotnet-ai.md` | `NET` |
| `stacks/node.md` | `NODE` |
| `stacks/python.md` | `PY` |
| `stacks/typescript-react.md` | `TSR` |
| the repo's `docs/standards/` shards | `P` |

A heading carries one id, and a new rule takes the next unused number of its prefix. The files of one stack share its prefix, and its numbers are unique across them. Ids are never renumbered or reused. Project ids are local to their repository, so a report that spans projects prefixes the repository name. `R1` to `R9` keep their ids and form and stay outside the layers.

An enforcer (a test or lint that fails when a standard is broken) cites a rule by writing `standard:` and the id with no space, as in `standard:B12`, anywhere in its text; the rule names no enforcer. A `P` id resolves against the project's own shards and every other id against the platform's standards directory. A standards lint, where the project runs one, fails on a citation of an id no applicable layer defines (a deleted rule's included) and on `standard:` followed, with no space, by something that is not an id. On demand it prints each rule with the enforcers citing it, the count of judged rules and the count of enforcers citing neither a rule id nor a decision-record id.

A suppression is the marker `suppress-standard:<id> <reason>` inside the comment of the line a platform lint's finding names, in the stack's own comment syntax (the lint reads a Python file's comments only, a string literal holding the text is no marker; any other file is read by line, so the marker text inside a string or a command there still counts); the reason runs to the end of the line, less a closing `-->` or `*/`. With the id and a reason, that finding is not counted. Without either, the marker suppresses nothing and is itself a violation, of the rule it names or, with no id, of the rule whose finding is on its line. A marker naming an id no applicable layer defines fails the standards lint, whose index reports each rule's reasoned suppressions. The never-rise check lists each one a change adds for the reviewer and fails nothing for it. Off-the-shelf tools keep their native syntax.

## Precedence

Direct user instruction > Layer 2 (project) > Layer 1 (stack) > Layer 0 (the bar) > general convention. More specific always overrides more general — the same rule that makes "match the file you're editing" beat personal preference. A recurring conflict between a layer and what the code actually does is a bug in one of them; fix it in the work that touches it, not as a separate refactor.

## Loading

Nobody reads a whole standards corpus, and a brief names files and pastes none. In an engine delivery the router decides: a `route` step before a briefed step computes the routed set of the change at that step's stage (Layer 0, the Layer-1 shards the change's file extensions choose, the Layer-2 shards whose `governs:` glob matches a touched path, the stage's hint file and the decision records the changed files cite), and the brief names those files through a placeholder that reads the step's stored result, so no agent chooses which shards apply. A stored route is reused only for the same checkout, head and stage: the briefs of one head at one stage read one result, a brief at another stage of that head reads its own, and after a new commit the next briefed step is routed again. A brief that runs before the change has a checkout, or after it has merged, names no routed files, and a landing's briefs are not routed until a later decision says which of them use a standard. A delivery program that predates the engine keeps its own brief text: Layer 0 in full plus only the shards whose globs intersect the change, and a reviewer's Standards-axis brief there adds the Fowler smell baseline. Reviewers read the files their brief names and load no skills of their own.

## The Layer-2 contract

A repo's `docs/standards/` is a directory of shards plus a **README index of at most 40 lines**, one row per shard carrying its `governs:` globs and a one-line gist — the same index-not-store discipline as `CONTEXT-MAP.md`.

- **Shape.** Each `governs` cell holds one or more code-span path globs relative to the repository root, never prose and never a glob made only of `*` and `/`. A shard in any layer is at most 8 KB (8192 bytes), and a heading, its hashes and id included, is at most 100 characters. `standards-lint` checks these shapes, the index and the ids; whether a rule restates a higher layer or is process filed as a standard stays with the reviewer.
- **Deltas only.** Anything that restates Layer 0 or 1 gets deleted, not copied. If a rule is true for every project on this stack, it belongs upstream in `stacks/`.
- **Case law is written rule-first**: each rule is one `### P<n>.` heading, then the rule in at most two sentences, plus one issue or ADR link. The narrative lives in the issue. Incident memoirs are what make a standards file grow linearly with project age.
- **Process content is not a standard.** It is a hint: process content for one delivery phase, never a rule with an id. Hints live at `.agents/knowledge/hints/`, one file per phase, named for the phase that reads it and within the platform line budget `standards-lint` sets. A review rule about the code is a Layer 2 standard with an id; review procedure is a hint. Lint commands go nowhere — the environment already names them.

## Planning rules

`acceptance-planning.md` is not a layer: it holds the rules for acceptance criteria and verification holds, read on demand by the planning and delivery skills and never pasted into briefs.

`look-before-merge.md` is not a layer either: it holds the stop and resume of an issue that needs the owner's look before merge, read on demand by `deliver-direct` and never pasted into briefs.
