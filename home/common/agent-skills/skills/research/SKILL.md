---
name: research
description: Researches a question against primary sources in a background agent and files cited findings. Use to delegate reading legwork.
---

# Research

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. Use `bindings.paths.artifacts.specs` for the findings artifact.

Bound the question sharply, then launch:

<!-- agent-dispatch: id=research-background-researcher role=researcher model=sonnet effort=medium -->
Agent(subagent_type="general-purpose", model="sonnet", effort="medium", run_in_background=true) performs the bounded primary-source synthesis and writes exactly one cited findings artifact while the caller keeps working.

If the question turns open-ended, ambiguous or judgment-bearing, stop the cheap-tier run and re-dispatch the `issue-owner` on Opus/high; record that escalation and the selected role in the caller's existing ledger or fixed-schema report.

The researcher:

1. Traces every claim to its **primary source**: official docs, source code, specs, first-party APIs.
2. Writes exactly one Markdown file under `bindings.paths.artifacts.specs`, citing a source per claim, and creates no other artifact. The file's first line states its durability, chosen from the caller's intent: **committed**, **attached** (linked from the asking ticket), or **intentionally temporary** (deleted once the decision is recorded).
3. Returns exactly `{file_path, key_facts[]}`: the path and only the facts the caller asked for.

## Live availability and blocking evidence

A live availability or blocking conclusion keeps the one-file contract and return shape: the evidence and its validation result go in the same findings file.

Record the evidence as a schema-1 object of `kind` `research-observations`. Each observation has a unique `id`, an independent `execution_id`, an `observed_at` with an explicit UTC offset, a `source` and an `outcome`. A `transient` conclusion cites exactly one observation in `observation_ids` and names an independent `follow_up`; a `standing` conclusion needs at least two observations with distinct `execution_id` and `observed_at` values.

Write the object to a temporary file and run `agent-evidence research <artifact.json>` (`~/.agents/bin/agent-evidence` if the bare name does not resolve). Return a standing conclusion only after exit 0. On failure, keep the observations and diagnostics in the findings file, return no standing conclusion, and delete the temporary input.
