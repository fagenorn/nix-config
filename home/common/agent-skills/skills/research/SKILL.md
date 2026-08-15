---
name: research
description: Investigate a question against primary sources in a background agent and capture cited findings as a Markdown file. Use to delegate reading legwork.
---

# Research

<!-- agent-dispatch: id=research-background-researcher role=researcher model=sonnet effort=medium -->
Agent(subagent_type="general-purpose", model="sonnet", effort="medium", run_in_background=true) performs the bounded primary-source synthesis and writes exactly one cited findings artifact while the caller keeps working.

The research question must be sharply bounded before launch. If it becomes open-ended, ambiguous, or judgment-bearing, stop the cheap-tier run and re-dispatch the `issue-owner` on Opus/high; record that escalation and selected role in the caller's existing ledger or fixed-schema report.

Its job:

1. Investigate the question against **primary sources** — official docs, source code, specs, first-party APIs — not a secondary write-up of them. Follow every claim back to the source that owns it.
2. Write the findings to exactly one Markdown file under the project's `specDir` (from `~/.agents/bin/resolve-bindings`; helper missing → `.claude/skills.config.json`, default `.claude/specs`), citing the source for each claim. Create no other artifact. State the artifact's durability explicitly at the top of the file — **committed** (the caller commits it with the work), **attached** (linked from the ticket/issue that asked), or **intentionally temporary** (deleted once the decision that needed it is recorded) — chosen deliberately from the caller's intent, never left implicit.
3. Report back exactly `{file_path, key_facts[]}` — the path it wrote, and only the facts the caller asked for. Everything else stays in the file.

## Live availability and blocking evidence

When the question includes a live availability or blocking conclusion, keep the
one-artifact contract above: put the evidence and its validation result in the
same Markdown findings file, retain no second project artifact, and keep the
exact `{file_path, key_facts[]}` return shape.

Represent the live evidence as schema version 1 with `kind` set to
`research-observations`. Every observation must have a unique observation ID in
`id`, an independent execution ID in `execution_id`, an `observed_at` timestamp
with an explicit UTC offset, a non-empty source identity in `source`, and a
non-empty `outcome`.

A `transient` conclusion based on one observation must reference exactly one
observation ID in `observation_ids`, stay scoped to that observation, and include
a non-empty independent follow-up in `follow_up`. A `standing` conclusion
requires at least two observations with distinct `execution_id` values and
distinct normalized `observed_at` timestamps — two independent timepoints.

Materialize the embedded evidence object as a temporary validation input and run
`agent-evidence research <artifact.json>` (the helper at
`~/.agents/bin/agent-evidence`; use the full path if the bare name does not
resolve on PATH). Only after the command exits 0 may the
agent return a standing conclusion. On failure, preserve the observations and
diagnostics in the sole Markdown findings file, return no standing conclusion,
and retain no temporary input as a second artifact.
