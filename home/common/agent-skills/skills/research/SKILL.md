---
name: research
description: Investigate a question against primary sources in a background agent and capture cited findings as a Markdown file. Use to delegate reading legwork.
---

# Research

<!-- agent-dispatch: id=research-background-explorer role=explorer model=haiku effort=medium -->
Agent(subagent_type="general-purpose", model="haiku", effort="medium", run_in_background=true) performs the bounded primary-source research while the caller keeps working.

The research question must be sharply bounded before launch. If it becomes open-ended, ambiguous, or judgment-bearing, stop the cheap-tier run and re-dispatch the `issue-owner` on Opus/high; record that escalation and selected role in the caller's existing ledger or fixed-schema report.

Its job:

1. Investigate the question against **primary sources** — official docs, source code, specs, first-party APIs — not a secondary write-up of them. Follow every claim back to the source that owns it.
2. Write the findings to a single Markdown file under the project's `specDir` (from `.claude/skills.config.json`, default `.claude/specs`), citing the source for each claim.
3. Report back exactly `{file_path, key_facts[]}` — the path it wrote, and only the facts the caller asked for. Everything else stays in the file.
