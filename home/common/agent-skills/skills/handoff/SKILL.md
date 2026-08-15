---
name: handoff
description: Compact the current conversation into a handoff document so a fresh session or another agent can continue the work.
argument-hint: "What will the next session be used for?"
---

Write a handoff document summarising the current conversation so a fresh agent can continue the work.

By default, save it to a temp file whose name you generate portably — e.g.
`mktemp "${TMPDIR:-/tmp}/handoff-XXXXXX.md"` (the explicit `XXXXXX` template
works on both macOS/BSD and Linux). This remains the default for interactive use.
`mktemp` creates the (empty) file as it generates the name: write the document
straight into it and report the path — do not read the just-created empty file
back first. The verify-and-replace protocol below exists for caller-provided
durable destinations only, never for this default.

A caller-provided destination with the current `run_id` is accepted only under
that run's `.superpowers/workflows/<run-id>/handoffs/` directory. Require
that directory to exist, then validate the complete non-symlink parent path using
no-follow directory opens. Reject every path escape, symlink component, or
non-directory parent. Inspect the destination leaf without following it; reject
an existing symlink or non-regular file, but allow a missing destination.

For that caller-provided destination: write and fsync a sibling temporary
regular file without following any leaf.
When the destination is missing, install it with an exclusive atomic operation
(for example, hard-link the temporary file to the destination) that will fail if
the leaf appeared concurrently; never overwrite that race. The missing
destination is created atomically, then the temporary name is removed. When an
existing regular destination is present, open and read it before writing, verify
that the same regular file is still at the leaf, then atomically replace it with
the sibling temporary file. Fsync the parent directory and return the exact
destination path. Clean up the temporary file on every failure.

Suggest the skills to be used, if any, by the next session.

Do not duplicate content already captured in other artifacts (specs, plans, design docs, issues, commits, diffs). Reference them by path or URL instead.

Do not duplicate lifecycle JSON in the handoff document. The run ledger owns
identity, phase action, attempt state, and compact outcomes; reference the run and
artifact paths only.

Redact anything sensitive on the way in — API keys, tokens, passwords, personally identifiable information. Command output sitting in context is the usual source, and the handoff doc outlives the session that wrote it.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.
