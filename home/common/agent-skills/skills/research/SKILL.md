---
name: research
description: Investigate a question against primary sources in a background agent and capture cited findings as a Markdown file. Use to delegate reading legwork.
---

# Research

Spin up a **background agent** to do the research, so you keep working while it reads.

Its job:

1. Investigate the question against **primary sources** — official docs, source code, specs, first-party APIs — not a secondary write-up of them. Follow every claim back to the source that owns it.
2. Write the findings to a single Markdown file under the project's `specDir` (from `.claude/skills.config.json`, default `.claude/specs`), citing the source for each claim.
3. Report back exactly `{file_path, key_facts[]}` — the path it wrote, and only the facts the caller asked for. Everything else stays in the file.
