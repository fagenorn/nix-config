---
name: doc-grounded-questions
description: Grounds questions and reviews in the project's docs and standards. Invoke before asking a design question, offering options or reviewing.
---

# Doc-Grounded Questions

Before asking the user a design question or presenting options, ground the question in the project's docs and code. [REFERENCE.md](./REFERENCE.md) holds the cache format, the question shape and the decision-log and standards layouts.

## Project bindings (resolve first)

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. Use `bindings.paths.context`, `bindings.paths.standards`, `bindings.paths.architecture`, and `bindings.paths.hints`, as `capabilities.knowledge.*` allows; a required blocked capability stops, while authored unsupported takes its documented no-capability route.

## The grounding pass

Select the context map only from the retained `bindings.paths.context` list, in authored order: entries whose basename is exactly `CONTEXT-MAP.md`. None means no map and no linter run; one selects that absolute path; several is an invalid caller contract that stops before any invocation. Never probe the filesystem, sort the list, take a first match, or infer a location.

1. **Read the selected map in full** (it is capped at 150 lines), then open an area's `CONTEXT.md` only when its `governs:` globs intersect the paths the issue touches or one of its terms appears in the issue or your question. Use the canonical terms you find. With no map, use only the retained context entries the owner passed.
2. **Scan decision records** only at paths passed through the retained context selection and allowed by `capabilities.knowledge.*`: list each directory, read titles, open the relevant records. A settled decision is stated, and you ask only whether anything has changed.
3. **Read the standards that apply**: always the machine-global `~/.agents/standards/the-bar.md` and its `stacks/*.md` shards matching the change's file extensions, then the project deltas in the retained `bindings.paths.standards`. Drop any option that violates a rule, or say why you surface it anyway.
4. **Read architecture** from the retained `bindings.paths.architecture` when the question spans components. Past ~400 lines, grep a document's headings and read only the governing sections; this applies to every long document except the map.
5. **Grep the codebase** for the central concept, inline when the lookup is small. When it needs a bounded read-only exploration pass, dispatch:

<!-- agent-dispatch: id=doc-grounded-bounded-code-lookup role=explorer model=sonnet effort=medium -->
Agent(subagent_type="Explore", model="sonnet", effort="medium") performs one sharply bounded read-only central-concept lookup without resolving the question.

   If the codebase already commits to a pattern, the default option is to match it, and any divergence needs a reason. If the lookup turns open-ended, ambiguous or judgment-bearing, stop the cheap-tier run and re-dispatch the `issue-owner` on Opus/high; record that escalation and the selected role in the caller's existing ledger or fixed-schema report.

Use the retained `bindings.paths.hints` only where the knowledge capability documents that route.

## Ground once per phase

Run the pass **once per phase** and write its findings to `"$(git rev-parse --git-dir)/GROUNDING.md"`: per worktree and outside the working tree, so it is never committed (outside a git repo, use the platform temp dir). Later questions read the cache. When a decision reaches an area not in it, load that one area, append it, and continue. A new phase starts a new cache; never re-read a map or area file already cached in this phase.

## Asking

Lead with the constraints you found (the context definition, the settled ADR, the standards rule), then ask only the open part. If the docs fully answer the question, don't ask: state the answer with its citation and continue.

Ground at the start of and during brainstorm, spec, grilling and standards-review phases; delivery escalations (merge conflict, failing lint, test or CI, a review blocker, cleanup) and reviewer dispatch; `writing-plans` before offering approaches; reviewer or audit subagents grading against the standards and decision log; and any ad-hoc design conversation. Where a sibling skill is not installed, apply the same pass to the current flow.

Skip it for pure preference questions, questions about the user's goals, and anything already in this phase's `GROUNDING.md`.
