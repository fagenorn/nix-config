---
name: doc-grounded-questions
description: Use before asking the user a clarifying question, presenting design options, recommending an approach, or evaluating code against the documented bar (PR review, audit, standards review). Forces grounding in the project's domain docs (context/glossary, ADRs, coding standards, architecture) and existing code first so questions surface real unknowns and reviews cite the actual rules — instead of relitigating documented decisions, proposing options the standards already rule out, or grading against a remembered version of the bar. Invoke even mid-conversation, every time you are about to ask a design question or open a review pass.
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

**Keys this skill uses:** `docPaths.{context,adrDir,standards,architecture}` (to know where the grounding sources
live), and `projectHints` (optional path to a project-specific vocab / review-hints appendix). All optional — if
none are configured, fall back to discovery (below).

## Why this matters

The user's time is the bottleneck. The cost of asking a question that's already answered in the project's context doc is not zero — it's:

- Time spent re-explaining
- Loss of trust that you've done the reading
- Risk that the user briefly forgets a decision and answers inconsistently with the existing doc

Worse: proposing options where one of them violates the coding bar is asking the user to validate a wrong answer. Drop those options before asking.

## What to do before each question

For every clarifying question or option set you're about to surface, do this pass first. Ground **discovery-first**: read whichever sources actually exist; skip absent ones silently.

1. **Find and read the context/glossary doc.** Use `docPaths.context` if configured; otherwise look for the common
   locations (`CONTEXT.md`, `GLOSSARY.md`, `CONTEXT-MAP.md`, or a top-of-`README` domain section). If a term in
   your question is defined there, use the canonical term and don't ask the user to disambiguate it again.

2. **Find and scan the decision log.** Use `docPaths.adrDir` if configured; otherwise look for the common ADR
   directories (`docs/adr/`, `docs/adrs/`, `docs/decisions/`, `adr/`). List the directory, read the titles, and
   open any that look relevant. If a decision is already settled, state the existing decision and ask only whether
   anything has *changed* since.

3. **Find and read the coding-standards / contributing doc.** Use `docPaths.standards` if configured; otherwise
   look for the common locations (`CONTRIBUTING.md`, `docs/coding-standards.md`, `docs/style.md`, a "Code style"
   section in the README). If one of your proposed options violates whatever the project's standards doc states,
   drop it from the option set or call out why you're surfacing it anyway.

4. **Find and read the architecture doc** if the question touches more than one component. Use `docPaths.architecture`
   if configured; otherwise look for `ARCHITECTURE.md`, `docs/architecture.md`, or a "Architecture" README section.
   Read it for cross-tier invariants.

5. **Grep the codebase** for the central concept. If the codebase already commits to a pattern, the default option
   should be "match the existing pattern" and you must justify any divergence.

If a `projectHints` file is configured and present, read it too — it carries project-specific vocab and review hints
that sharpen the grounding.

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
  `from-issue`, `grill-with-docs`, or `superpowers:brainstorming` exist, this fires inside each of their
  question-asking phases)
- Delivery escalations — every mid-flow escalation (merge conflict, lint/test failure, CI failure, review-blocker,
  cleanup) and the reviewer-dispatch step (if a sibling `ship-issue` skill exists, this fires at each of its
  escalation points)
- `superpowers:writing-plans` when you're about to ask the user to choose between approaches
- Reviewer / audit subagents grading a diff or plan against the project's standards doc and decision log
- Any ad-hoc design conversation where you'd otherwise just ask

The named sibling skills (`from-issue`, `ship-issue`, `grill-with-docs`, `superpowers:*`) are referenced opportunistically — if a given one is not installed, ignore that bullet and apply the same grounding pass to whatever flow you are actually in.

## When to skip

- Pure preference questions ("do you want feature A or feature B?") — the docs can't answer these
- Questions about user intent or goals — the docs describe the system, not what the user wants next
- Within the same conversation you've already grounded a closely related question — don't re-grep for every follow-up

## Cost note

Grounding takes seconds, not minutes — you're reading short markdown files and a handful of grep results, not the whole repo. If you're tempted to skip it because "it'll take too long," that's a sign you're about to ask a question that doesn't deserve to be asked.
