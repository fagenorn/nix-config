---
name: doc-grounded-questions
description: Invoke before asking a design question, presenting options, or opening a review pass — grounds questions and reviews in the project's docs (CONTEXT, ADRs, standards) first.
---

# Doc-Grounded Questions

Before asking the user a design question or presenting options during a planning/brainstorming phase, ground the question in the project's docs and code. Rationale, legacy fallbacks, and worked examples live in [REFERENCE.md](./REFERENCE.md); load it when a step below points there.

## Project bindings (resolve first)

Run `~/.agents/bin/resolve-bindings` from the project — it prints the standard binding set from `.claude/skills.config.json` plus auto-detection and the shared defaults; helper missing → read the config and apply the same defaults. Degrade gracefully: skip any configured-but-absent doc path, sibling skill, or hints file silently; never hard-fail on a missing optional binding.

**Keys this skill uses:** `docPaths.{contextMap,context,standards,architecture}`, `docPaths.adrDir` (legacy override only — ADR homes normally come from the map), and `projectHints` (optional vocab / review-hints appendix). All optional — none configured → discovery below.

## The grounding pass

For every clarifying question or option set you're about to surface, do this pass first. Ground **discovery-first**: read whichever sources actually exist; skip absent ones silently.

1. **Read the context map, then only the areas you need.** `docPaths.contextMap` if configured, otherwise `docs/CONTEXT-MAP.md` (or legacy root `CONTEXT-MAP.md`). Always read the map in full — it is capped at 150 lines. Then open an area's `CONTEXT.md` **only** when its `governs:` globs intersect the paths the issue touches, or one of its terms (per the map's term table) appears in the issue or your question. Use canonical terms without re-asking. No map → legacy single-doc fallback (REFERENCE.md).

2. **Scan the decision log.** The `adr/` dirs of the areas you opened in step 1, plus `docs/areas/system/adr/` always (legacy ADR homes: REFERENCE.md). List the directory, read the titles, open any that look relevant. A settled decision → state it and ask only whether anything has *changed* since.

3. **Read the standards that apply.** `~/.agents/standards/the-bar.md`, its `stacks/*.md` shards matching the change's file extensions, and project deltas at `docPaths.standards` (layer detail: REFERENCE.md). If a proposed option violates a rule you found, drop it or say why you're surfacing it anyway.

4. **Read the architecture doc** if the question touches more than one component (`docPaths.architecture`, else `ARCHITECTURE.md` / `docs/architecture.md` / a README section) for cross-tier invariants. Past ~400 lines, read by governing section, never whole — the rule for every long doc this pass sends you to, map excepted (why: REFERENCE.md).

5. **Grep the codebase** for the central concept. Keep a small direct grep inline; when the result set needs a sharply bounded read-only exploration pass, use the explicit explorer dispatch instead:

<!-- agent-dispatch: id=doc-grounded-bounded-code-lookup role=explorer model=haiku effort=medium -->
Agent(subagent_type="Explore", model="haiku", effort="medium") performs one sharply bounded read-only central-concept lookup without resolving the question.

   If the codebase already commits to a pattern, the default option should be "match the existing pattern" and you must justify any divergence. If the lookup becomes open-ended, ambiguous, or judgment-bearing, stop the cheap-tier run and re-dispatch the `issue-owner` on Opus/high; record that escalation and selected role in the caller's existing ledger or fixed-schema report.

If `projectHints` is configured and present (a directory → its `review.md`; a single file → itself), read it too.

## Ground once per phase, cache the result

The pass above runs **once per phase**, not once per question. Write what it found to `"$(git rev-parse --git-dir)/GROUNDING.md"` — per-worktree and outside the working tree, so it can never be committed (a committed cache collides across parallel runs); outside a git repo, fall back to the platform temp dir. Format and example: REFERENCE.md.

Read the cache instead of re-running the pass. Re-invoke only when a decision reaches into an area **not** in the cache — load that one area, append it, continue. A new phase starts a new cache. This is the single grounding read per phase the pipeline expects; never re-read the map or an area file already cached in this phase.

## How to phrase the question

Lead with the constraints you found — the context doc's definition, the ADR's settled decision, the standards rule — then ask only the genuinely open part (full worked shape: REFERENCE.md). That shows the homework and frames the question precisely around what's unknown.

If, after grounding, the docs fully answer the question, don't ask — state the answer with its citation and move on.

## When this skill applies

Invoke at the start of and during:

- Brainstorm/spec, grilling/stress-test, and standards-review phases (`from-issue`, `grill-with-docs`, `design`)
- Delivery escalations — merge conflict, lint/test/CI failure, review-blocker, cleanup — and reviewer dispatch (`ship-issue`)
- `writing-plans`, before asking the user to choose between approaches
- Reviewer / audit subagents grading a diff or plan against the standards doc and decision log
- Any ad-hoc design conversation where you'd otherwise just ask

Sibling skills are referenced opportunistically — where one is not installed, apply the same pass to whatever flow you are in.

## When to skip

- Pure preference questions ("feature A or feature B?") — the docs can't answer these
- Questions about user intent or goals — the docs describe the system, not what the user wants next
- Anything already in this phase's `GROUNDING.md` — read the cache, don't re-run the pass
