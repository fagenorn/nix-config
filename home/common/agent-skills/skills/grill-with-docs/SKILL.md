---
name: grill-with-docs
description: Stress-tests a spec against the domain docs, updating the glossary and ADRs as decisions settle. Use to grill a drafted spec.
---

# Grill With Docs

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. Read `bindings.paths.context` and `capabilities.knowledge.*`.

Select the context map only from the retained `bindings.paths.context` list, in authored order: entries whose basename is exactly `CONTEXT-MAP.md`. None means no map and no linter run; one selects that absolute path; several is an invalid caller contract that stops before any invocation. Never probe the filesystem, sort the list, take a first match, or infer a location.

## The interview

Interview the user relentlessly about every aspect of the spec (`from-issue` invokes this on the spec, not the plan) until you share one understanding. Model the design as a tree of decisions; the **frontier** is every question whose prerequisites are settled. Ask the whole frontier as one numbered round of `❓ question / ➡️ recommended answer` pairs; a question depending on another open question waits for a later round. Recompute the frontier after each round; done when it is empty.

When every question in a round carries a ➡️ recommendation, say once, at the first such round, that the user may reply with only the numbers they'd change: anything not named adopts its recommendation and is recorded as their decision. Three kinds of question never ride on silence: anything that redraws the destination or scope, anything hard to reverse, and anything that spends money or hands out a credential. Mark those and wait for an answer in words, however many rounds it takes.

A question a bounded read-only lookup in the code or docs can answer is explored, not asked:

<!-- agent-dispatch: id=grill-bounded-fact-lookup role=explorer model=sonnet effort=medium -->
Agent(subagent_type="Explore", model="sonnet", effort="medium") performs one sharply bounded read-only fact lookup without making the design decision.

Only questions downstream of a lookup wait for it. The decisions are the user's; the facts are yours. If the lookup turns open-ended, ambiguous or judgment-bearing, stop the cheap-tier run and re-dispatch the `issue-owner` on Opus/high; record that escalation and the selected role in the phase's existing fixed-schema report.

## Domain docs

Read existing documentation while exploring, long documents by section (`doc-grounded-questions` step 4). Areas, glossaries and decision records live only where the selected map and its passed area paths name them; with no selected map, use only the passed context paths and never create or discover a map. Create files lazily, and only where the selected map and its area paths authorize them, or in a passed writable context path when there is no map; an empty or unsupported path set has no write route. Read [CONTEXT-FORMAT.md](./CONTEXT-FORMAT.md) before creating any doc file.

During the session:

- **Challenge against the glossary**: a term used against its glossary definition is called out at once ("Your glossary defines 'cancellation' as X, but you seem to mean Y — which is it?").
- **Sharpen fuzzy language**: propose a precise canonical term for a vague or overloaded one.
- **Probe with concrete scenarios** that force precision at the boundaries between concepts.
- **Cross-reference the code**: surface any contradiction between what the user states and what the code does.
- **Update the glossary inline**: when a term resolves, write it into the owning area's glossary and add its row to the map's Terms table, in CONTEXT-FORMAT.md's format. Only terms meaningful to a domain expert.

Two same-commit obligations keep the glossary sustainable: **delete on resolve** (an ambiguity marker goes the moment the ambiguity closes; the resolution lives in the winning definition and its `_Avoid_:` line, or in an ADR) and **net-neutral writes** (a file pushed past its budget, 150 lines for the map or the front-matter `budget:` for an area, is consolidated or split before you finish: consolidate first, tightening entries past two
sentences and merging near-duplicate terms; split only when the area covers two things).

**Splitting an area** is four edits in one commit:

1. Create the new area file with front-matter (`area:`, `budget: 200 lines`), a one- or two-sentence purpose, and the moving terms copied verbatim.
2. Delete those terms from the old file.
3. Add a row to the map's `## Areas` table (name, link, one-line gist, `governs:` globs) and narrow the old area's globs.
4. Repoint the moved terms' rows in `## Terms` and add any new cross-area edge to `## Relationships`.

Then run `~/.agents/bin/context-map-lint --repo-root <absolute checkout root> --context-map <selected map path>` (no selected map, no run) and fix what it reports.

Offer an ADR only when the decision is hard to reverse, surprising without context, and the result of a real trade-off; write it per [ADR-FORMAT.md](./ADR-FORMAT.md).

## Final spec measurement

Measurement follows the final-writer rule (D5). When the grilling ends (frontier empty, or the user stops it), finish every glossary, ADR, spec and ledger edit; the last spec or ledger edit is the final mutation. Even if the grill changed nothing, measure afresh rather than repeat an earlier claim: run `artifact-budget check --kind design-spec --root <spec-root> --format json`; the checker owns the thresholds.

- Exit 0 with `within_budget`: measured.
- Exit 2 from either check: `failed`.
- First exit 3: compact repetition, examples and evidence references without weakening required sections or the ledger's meaning, then check again. Still over budget: keep the draft and return `decompose_required` with the checker's `violations`, its `notes` naming the independently deliverable parts. Never a clean grill or `complete`.

Any later mutation of the spec or ledger voids these metrics and moves a fresh check to its writer, including later planning edits.

## Report on return

Return one producer report `{state, artifact, notes}` (D11, D14), to the calling skill or to the user, with `state: complete | decompose_required | failed`:

- `complete`: `kind: design-spec`, the root `path`, the checker's `metrics` (`root_bytes`, `total_bytes`, `file_count`, `largest_member_bytes`) and `budget_status: within_budget`.
- `decompose_required`: the same with `budget_status: over_budget` and the checker's `violations`.
- `failed`: a null artifact, or only `kind` and `path` once the root is known.

`notes` stays within the shared policy's `phase_reports.notes_max_characters` and may point to the committed spec and docs, but never inlines artifact contents, ledger rows, doc or member lists, policy or logs.

After the last check, write the report to a candidate from `mktemp "${TMPDIR:-/tmp}/producer-report-XXXXXX.json"`, run `artifact-budget validate-report --boundary producer --input <report-candidate>`, and remove the candidate in a cleanup that runs on every outcome (a `trap` on `EXIT HUP INT TERM`, or `finally`). Return only the validated stdout; validation exit 2 is `failed`, with no fallback text. Do not invoke the next skill or start implementing.
