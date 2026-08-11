---
name: doc-grounded-questions
description: Invoke before asking a design question, presenting options, or opening a review pass — grounds questions and reviews in the project's docs (CONTEXT, ADRs, standards) first.
---

# Doc-Grounded Questions

Before asking the user a design question or presenting options during a planning/brainstorming phase, ground the question in the project's docs and code. This skill exists because most mature projects carry substantial documented context that the default "just ask" instinct routinely ignores.

## Project bindings (resolve first)

This skill is project-agnostic. Before acting, resolve project-specific values:

1. If `.claude/skills.config.json` exists at the project root, read it for the bindings below.
2. For any absent key (or no config file), auto-detect: issue tracker = `gh` if the git remote is github.com
   (else `glab`/none); verify commands from the manifest (package.json scripts, `*.slnx`/`*.sln` -> dotnet test,
   Cargo.toml -> cargo test, go.mod -> go test, Makefile -> make test); branches from the repo default.
3. Defaults when neither config nor detection yields a value: integrationBranch=main, defaultBranch=main,
   commit.coAuthoredBy=true, unsetGithubToken=false, deploy.adapter=none, specDir=.claude/specs, planDir=.claude/plans.
4. Degrade gracefully: any configured-but-absent doc path, sibling skill, or hints file is skipped silently —
   never read a file that does not exist, never hard-fail on a missing optional binding.

**Keys this skill uses:** `docPaths.{contextMap,context,standards,architecture}` (to know where the grounding
sources live), `docPaths.adrDir` (legacy override only — ADR homes normally come from the map), and `projectHints` (optional path to a project-specific vocab / review-hints appendix). All optional —
if none are configured, fall back to discovery (below).

## Why this matters

The user's time is the bottleneck. The cost of asking a question that's already answered in the project's context doc is not zero — it's:

- Time spent re-explaining
- Loss of trust that you've done the reading
- Risk that the user briefly forgets a decision and answers inconsistently with the existing doc

Worse: proposing options where one of them violates the coding bar is asking the user to validate a wrong answer. Drop those options before asking.

## What to do before each question

For every clarifying question or option set you're about to surface, do this pass first. Ground **discovery-first**: read whichever sources actually exist; skip absent ones silently.

1. **Read the context map, then only the areas you need.** Use `docPaths.contextMap` if configured, otherwise
   `docs/CONTEXT-MAP.md` (or legacy root `CONTEXT-MAP.md`). Always read the map in full — it is capped at 150
   lines and tells you what exists. Then open an area's `CONTEXT.md` **only** when one of these holds:
   - its `governs:` globs intersect the paths the issue touches, or
   - one of its terms (per the map's term table) appears in the issue or in the question you are about to ask.

   Opening every area file defeats the point; the map exists so you can skip the ones that don't apply. If a term
   in your question is defined in an area you opened, use the canonical term and don't ask the user to
   disambiguate it again.

   **No map?** Fall back to the legacy layout: read whichever of `docPaths.context`, `CONTEXT.md`, `GLOSSARY.md`,
   `DOMAIN.md` or a top-of-`README` domain section exists — whole when it is short, by governing section when it is
   not (step 4). Read it once, not per question.

2. **Find and scan the decision log.** Areas own their decisions: each area in the map has an `adr/` directory
   beside its `CONTEXT.md` (`docs/areas/<slug>/adr/`), plus the reserved `docs/areas/system/adr/` for decisions
   spanning areas. Scan the `adr/` dirs of the areas you opened in step 1, and `system/` always. Legacy fallback,
   for repos with no `docs/areas/`: `docPaths.adrDir` if configured, else whichever of `docs/adr/`, `docs/adrs/`,
   `docs/decisions/`, `adr/` exists. Either way: list the directory, read the titles, and open any that look
   relevant. If a decision is already settled, state the existing decision and ask only whether anything has
   *changed* since.

3. **Read the standards that apply to this change.** The universal bar is `~/.agents/standards/the-bar.md` and the
   stack shards are `~/.agents/standards/stacks/*.md` — load a shard only when the change's file extensions match
   it. Project deltas live at `docPaths.standards` (a `docs/standards/` directory with a README index carrying
   `governs:` globs, or a single `CONTRIBUTING.md` / `docs/coding-standards.md` in older repos). See
   `~/.agents/standards/README.md` for the precedence ladder. If one of your proposed options violates a rule you
   found, drop it from the option set or say why you're surfacing it anyway.

4. **Find and read the architecture doc** if the question touches more than one component. Use `docPaths.architecture`
   if configured; otherwise look for `ARCHITECTURE.md`, `docs/architecture.md`, or a "Architecture" README section.
   Read it for cross-tier invariants — and past ~400 lines, read it by governing section rather than whole: grep its
   headings first, then open only the sections covering the components in play. The same cap governs any other long
   doc this pass sends you to; the context map is the exception, and only because it is capped at 150 lines by design.
   A large architecture doc read end-to-end can cost more than every other step of this pass combined, and its two or
   three relevant sections answer the question just as well.

5. **Grep the codebase** for the central concept. If the codebase already commits to a pattern, the default option
   should be "match the existing pattern" and you must justify any divergence.

If `projectHints` is configured and present (a directory → its `review.md`; a single file → itself), read it too — it carries project-specific vocab and review hints
that sharpen the grounding.

## Ground once per phase, cache the result

The pass above runs **once per phase**, not once per question. Write what it found to
`"$(git rev-parse --git-dir)/GROUNDING.md"` — per-worktree and outside the working tree, so it can never be
committed — and read that file instead of re-running the pass. Never write the cache inside the working tree:
a committed cache collides across parallel runs (observed: two `--auto` branches add/add-conflicted on
`.claude/specs/GROUNDING.md` at merge). Outside a git repo, fall back to the platform temp dir:

```md
# Grounding — <phase>

## Areas loaded
- Billing (`src/billing/**`) — Invoice, Dunning, Settlement
- Ordering (`src/ordering/**`) — Order, Customer

## Constraints found
- ADR-system-007: Ordering and Billing communicate by domain event, never synchronous HTTP.
- the-bar.md: fail-loud at closed-set dispatch sites.
- docs/standards/testing.md: endpoint tests share the API factory fixture.

## Areas deliberately not loaded
- Fulfilment, Identity — no path or term overlap with this issue.
```

Re-invoke the pass only when a decision reaches into an area **not** in the cache — then load that one area, append
it, and continue. A new phase starts a new cache. This is the single grounding read per phase that the pipeline
expects; do not re-read the map or an area file you have already cached in this phase.

## How to phrase the question

Lead with the constraints you found, then ask only the genuinely open part. The shape (substitute your project's real terms and decisions for the placeholders):

> "`<CONTEXT-DOC>` defines '`<Domain Term>`' as `<the canonical definition>`. `<ADR-NNN>` settled that
> `<the relevant decision>` happens in `<component A>`, not `<component B>`. `<STANDARDS-DOC>` requires
> `<the applicable rule>` for all `<X>`-touching code. Given that, the open question is whether to extend
> `<the existing abstraction>` or add a sibling abstraction for the new `<edge case>` — what's your call?"

This does two things at once: shows the homework, and frames the question precisely around what's actually unknown.

If, after grounding, the question turns out to be fully answered by the docs, don't ask — state the answer and move on. ("Per `<ADR-NNN>`, `<the decision>`, so this goes there. Continuing.")

## When this skill applies

Invoke at the start of and during:

- A brainstorm / spec phase, a grilling/stress-test phase, and a standards-review phase (if the sibling skills
  `from-issue`, `grill-with-docs`, or `design` exist, this fires inside each of their
  question-asking phases)
- Delivery escalations — every mid-flow escalation (merge conflict, lint/test failure, CI failure, review-blocker,
  cleanup) and the reviewer-dispatch step (if a sibling `ship-issue` skill exists, this fires at each of its
  escalation points)
- `writing-plans` when you're about to ask the user to choose between approaches
- Reviewer / audit subagents grading a diff or plan against the project's standards doc and decision log
- Any ad-hoc design conversation where you'd otherwise just ask

The named sibling skills (`from-issue`, `ship-issue`, `grill-with-docs`, `design`, `writing-plans`) are referenced opportunistically — if a given one is not installed, ignore that bullet and apply the same grounding pass to whatever flow you are actually in.

## When to skip

- Pure preference questions ("do you want feature A or feature B?") — the docs can't answer these
- Questions about user intent or goals — the docs describe the system, not what the user wants next
- Anything already in this phase's `GROUNDING.md` — read the cache, don't re-run the pass

## Cost note

A grounded pass is the map (≤150 lines) plus the one or two area files that actually apply, plus a handful of greps — seconds, not minutes, and bounded no matter how large the project's docs have grown. If you're tempted to skip it because "it'll take too long," you're either about to ask a question that doesn't deserve to be asked, or you're loading area files the `governs:` globs told you to skip.
