---
name: design
description: Turns an idea or issue into an approved design spec through batched question rounds. Use to brainstorm, design or spec work before planning.
---

# Design

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. Use `bindings.paths.artifacts.specs` for the design artifact path.

Turn an idea into a design spec the plan phase can execute from.

## The interview: round-batched frontier

Model the design as a tree of decisions. The **frontier** is every question whose prerequisites are settled. Ask the whole frontier as one numbered round:

```
❓ **Q1** — **<short title>**: <the question, with the choices when there are choices>

➡️ <your recommended answer>
```

- A question that depends on one open in the same round waits for a later round.
- Every question carries a `➡️` recommendation: commit to a defensible default before hearing the user's lean.
- Answers reshape the tree; recompute the frontier and ask the next round. Done when the frontier is empty and nothing was silently assumed.

**Ground before round 1**: invoke `doc-grounded-questions`, or read this phase's `GROUNDING.md` cache when the caller built one.

**Facts are your job; decisions are the user's.** Answer a trivial repository fact inline. When a fact needs a bounded read-only exploration pass, dispatch the explorer; when it needs cited primary sources, invoke `research`, which owns its own background launch.

<!-- agent-dispatch: id=design-bounded-fact-lookup role=explorer model=sonnet effort=medium -->
Agent(subagent_type="Explore", model="sonnet", effort="medium") performs one sharply bounded read-only fact lookup without making the design decision.

An in-flight lookup blocks only the questions downstream of it; ask the rest now. If the lookup turns open-ended, ambiguous or judgment-bearing, stop the cheap-tier run and re-dispatch the `issue-owner` on Opus/high; record that escalation and the selected role in the phase's existing fixed-schema report.

## Authorized autonomous decisions

When the caller has authorized autonomous decisions within a stated scope (literal `from-issue --auto` among others), **the `➡️` recommendation is the answer**: post no round and wait for nothing. Rounds still run in frontier order. Record each non-obvious decision in the spec's `## Decision ledger`; a decision that expands the approved scope returns to the caller.

## Guards

- **Synthesize, never re-interview.** Everything the rounds and the caller's earlier phases settled enters the spec as a decision.
- **Agree the test seams before writing the spec**: the public boundaries this work is tested at, preferring existing and higher seams, kept few.
- **YAGNI**: strip unrequested configuration, abstraction and future-proofing from every option.
- **Scope check first**: a request spanning several independent subsystems is decomposed before detail; design the first piece and hand the rest to `to-issues`.

## Output

Write the spec to `<bindings.paths.artifacts.specs>/<YYYY-MM-DD>-<topic>-design.md` in the worktree you were called in, never on the integration branch.

Sections: **Problem** (from the user's perspective) · **Solution** · **Decisions** (modules, interfaces, schema and API contracts, behavior; no file paths or line numbers) · **Test seams** (the agreed seams and the prior art they follow) · **Out of scope** (mandatory and real) · **Decision ledger**, the issue's single decision store, cited later by row ID ("per D3"), never restated:

```markdown
| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | <what was decided, one line> | <doc/standard/user statement it rests on> | <the alternative and why not, one line> |
```

Only non-obvious decisions earn a row (scope, interface, behavioral, test-seam, irreversible, user-preference), whoever answered them; skip routine task splits, commit boundaries, obvious verification and mechanical pattern-following, and merge related decisions into one row.

Then reread the spec once with fresh eyes and fix placeholders, contradictions, ambiguous requirements and scope that needs decomposing. No reviewer dispatch.

## Artifact budget

Run `artifact-budget check --kind design-spec --root <spec-root> --format json`.

- Exit 0 with `within_budget`: measured.
- Exit 2: `failed`.
- First exit 3: compact repetition, examples and evidence references without weakening a required section or the ledger's meaning, then check again. Still over: keep the draft and return `decompose_required` with the checker's `violations`, its `notes` proposing the independently deliverable parts. A second-check exit 2 is `failed`.

The design is complete only in this order: final mutation, a `within_budget` check, a commit of the spec in the worktree, then the `complete` report. A failed commit or signature is `failed`. If a commit hook changes the spec, check it again and commit exactly the measured within-budget content before reporting `complete`.

## Code map

Before the report, write the spec's **code map** into the git directory (`git rev-parse --git-dir`), named like the spec file with `.code-map.md` for `.md`: a title naming the spec file, then one entry per module, seam or contract the Decisions decide about.

```markdown
## <the spec's name for it>
- Why: <one line: why it matters to this change>
- Code: `<path>` (`<symbol>`, `<symbol>`); `<path>`
- Tests: `<path>` (`<test name>`)
```

Paths are repository-relative, outside the parentheses; `Tests:` may read `none read`. Use only what you already read: open no file for it and omit an entry you cannot fill. It holds no decision, requirement, rationale, line number or code excerpt, and is never committed or reported. If it cannot be written, still complete and say so in `notes`.

## Return control

Return one producer report `{state, artifact, notes}` with `state: complete | decompose_required | failed`:

- `complete`: `kind: design-spec`, the root `path`, the checker's `metrics` (`root_bytes`, `total_bytes`, `file_count`, `largest_member_bytes`) and `budget_status: within_budget`.
- `decompose_required`: the same with `budget_status: over_budget` and the checker's `violations`.
- `failed`: a null artifact, or only `kind` and `path` once the root is known.

`notes` stays within the shared policy's `phase_reports.notes_max_characters` and never inlines artifact contents, ledger rows, policy, logs or member lists.

After the last check, write the report to a candidate from `mktemp "${TMPDIR:-/tmp}/producer-report-XXXXXX.json"`, run `artifact-budget validate-report --boundary producer --input <report-candidate>`, and remove the candidate in a cleanup that runs on every outcome (a `trap` on `EXIT HUP INT TERM`, or `finally`). Return only the validated stdout; validation exit 2 is `failed`, with no fallback text. Do not invoke `writing-plans` or start implementing: the caller owns the next phase.
