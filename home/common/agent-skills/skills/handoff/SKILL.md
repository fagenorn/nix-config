---
name: handoff
description: Compact the current conversation into a handoff document so a fresh session or another agent can continue the work.
argument-hint: "What will the next session be used for?"
---

Write a handoff document summarising the current conversation so a fresh agent can continue the work.

By default, save it to a temp file whose name you generate portably — e.g.
`mktemp "${TMPDIR:-/tmp}/handoff-XXXXXX.md"` (the explicit `XXXXXX` template
works on both macOS/BSD and Linux). This remains the default for interactive use.

When the caller supplies a destination with the current `run_id`, accept it only
under that run's `.superpowers/workflows/<run-id>/handoffs/` directory. Resolve
and compare both paths, reject every symlink or path escape in the destination or
its parents, and require the existing destination to be a regular non-symlink
file. Read the destination before writing. Write a sibling temporary file, flush
it, and atomically replace the validated caller-provided destination; return its
exact path. Never follow a replaced or re-resolved path after validation.

Suggest the skills to be used, if any, by the next session.

Do not duplicate content already captured in other artifacts (specs, plans, design docs, issues, commits, diffs). Reference them by path or URL instead.

Do not duplicate lifecycle JSON in the handoff document. The run ledger owns
identity, phase action, attempt state, and compact outcomes; reference the run and
artifact paths only.

Redact anything sensitive on the way in — API keys, tokens, passwords, personally identifiable information. Command output sitting in context is the usual source, and the handoff doc outlives the session that wrote it.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.
