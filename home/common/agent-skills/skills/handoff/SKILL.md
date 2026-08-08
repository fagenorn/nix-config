---
name: handoff
description: Compact the current conversation into a handoff document so a fresh session or another agent can continue the work.
argument-hint: "What will the next session be used for?"
---

Write a handoff document summarising the current conversation so a fresh agent can continue the work. Save it to a temp file whose name you generate portably — e.g. `mktemp "${TMPDIR:-/tmp}/handoff-XXXXXX.md"` (the explicit `XXXXXX` template works on both macOS/BSD and Linux). Read the file before you write to it.

Suggest the skills to be used, if any, by the next session.

Do not duplicate content already captured in other artifacts (specs, plans, design docs, issues, commits, diffs). Reference them by path or URL instead.

Redact anything sensitive on the way in — API keys, tokens, passwords, personally identifiable information. Command output sitting in context is the usual source, and the handoff doc outlives the session that wrote it.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.
