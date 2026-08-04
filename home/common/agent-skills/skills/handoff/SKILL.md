---
name: handoff
description: Compact the current conversation into a handoff document so another agent (or a fresh session after a context-window reset) can pick up the work.
argument-hint: "What will the next session be used for?"
---

Write a handoff document summarising the current conversation so a fresh agent can continue the work. Save it to a temp file whose name you generate portably — e.g. `mktemp "${TMPDIR:-/tmp}/handoff-XXXXXX.md"` (the explicit `XXXXXX` template works on both macOS/BSD and Linux). Read the file before you write to it.

Suggest the skills to be used, if any, by the next session.

Do not duplicate content already captured in other artifacts (specs, plans, design docs, issues, commits, diffs). Reference them by path or URL instead.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.
