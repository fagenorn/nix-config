---
name: handoff
description: Compact the current conversation into a handoff document so a fresh session or another agent can continue the work.
argument-hint: "What will the next session be used for?"
---

Write a handoff document summarising the current conversation so a fresh agent can continue the work.

By default, create a nondurable candidate with a portable name — e.g. `mktemp
"${TMPDIR:-/tmp}/handoff-XXXXXX.md"` (the explicit `XXXXXX` template works on
both macOS/BSD and Linux). `mktemp` creates the empty file as it generates the
name: write the full candidate straight into it; do not read the just-created
empty file back first. The durable publication protocol below exists only for a
caller-provided destination.

A caller-provided destination with the current `run_id` is accepted only under
that run's `.superpowers/workflows/<run-id>/handoffs/` directory. Require
that directory to exist, then validate the complete non-symlink parent path using
no-follow directory opens. Reject every path escape, symlink component, or
non-directory parent. Inspect the destination leaf without following it; reject
an existing symlink or non-regular file, but allow a missing destination.

For that caller-provided destination, write and fsync the full candidate as a
sibling temporary regular file without following any leaf. Do not open the
destination for writing and do not publish yet.

Two temporaries are involved in the durable publication route below and must not
be confused. The sibling temporary holds the checked artifact bytes and is
written as a sibling of the durable destination, because the install is a
same-directory hard-link or atomic replace — sibling placement is a correctness
requirement, not a convenience. The report candidate holds the producer-report
JSON, is never published, has no life beyond the call, and therefore lives in OS
temp. The default nondurable candidate above is neither and needs no protocol.

## Candidate budget state machine

Measurement and remediation follow the authoritative final-writer rule (D5).
After the full candidate has been written, run `artifact-budget check --kind
handoff --root <candidate-root> --format json`. Do not embed thresholds or use
an ad-hoc byte counter. Exit 2 is `failed`; include the candidate root when known but no
fabricated metrics or status. On the first exit 3, perform one semantic rewrite:
remove duplicated artifact, lifecycle, diff, and log content while preserving the
continuation decisions and references, then run `artifact-budget check --kind
handoff --root <candidate-root> --format json` once more. There is no second
rewrite. A second exit 3 is `stopped`, never `complete`.

For a nondurable candidate, retain that over-budget candidate for inspection. For
a durable request, never install an over-budget candidate: remove its unpublished
sibling temporary pathname after moving the same regular file, without changing
its bytes, to a clearly nondurable retained-candidate path used in the stopped
report. If an identity-preserving move is unavailable, remove the sibling name
and stop failed rather than copy unmeasured bytes. Any checker exit 2 removes an
unpublished candidate. Thus a terminal checker exit 2 or exit 3 must leave the
existing destination byte-identical and clean up all unpublished temporary names.

Any content mutation after a successful check invalidates the metrics and makes
that writer responsible for remeasurement. Renaming or installing the same checked
regular file without changing its bytes is publication, not a content mutation.

## Producer report and publication

The report returned for the final outcome is exactly one producer object (D11, D14) whose closed
state row is `state: complete | stopped | failed`:

- `complete` has one artifact with `kind: handoff`, the published or nondurable
  root `path`, `metrics` containing exactly `root_bytes`, `total_bytes`,
  `file_count`, and `largest_member_bytes`, and `budget_status: within_budget`.
- `stopped` has the retained nondurable candidate `path`, the same exact metrics,
  `budget_status: over_budget`, and the checker's sorted closed `violations`.
- `failed` has a null artifact before a root is known, or only `kind` and `path`
  when it is known. Include no fabricated metrics or budget status.

Bound `notes` using only the shared policy's
`phase_reports.notes_max_characters`. Reports must never inline artifact contents,
member lists, policy, logs, lifecycle rows, or diff content.

Only after the last artifact check, serialize the row as UTF-8 to a report
candidate outside every working tree — create it with `mktemp
"${TMPDIR:-/tmp}/producer-report-XXXXXX.json"` (the explicit `XXXXXX` template
works on both macOS/BSD and Linux) — invoke `artifact-budget validate-report
--boundary producer --input <report-candidate>`, and remove that candidate under
an unconditional cleanup that runs on every outcome, including validation
rejection and failure: a shell `trap` on `EXIT HUP INT TERM`, or the equivalent
`finally`. Hold only the exact validated stdout bytes. Validation exit 2 is
`failed`: emit no Markdown, YAML, candidate JSON, truncated text, or prose
fallback. It must also leave the existing destination byte-identical and remove
unpublished temporary names.

Only an exit-0 artifact check and an exit-0 report validation may reach durable
publication. When the destination is missing, install the checked sibling file
with an exclusive atomic operation (for example, hard-link it to the destination)
that fails if the leaf appeared concurrently; never overwrite that race. The
missing destination is created atomically, then the temporary name is removed.
When an existing regular destination is present, open and read it before writing,
verify that the same regular file is still at the leaf, then atomically replace it
with the checked sibling temporary file. Fsync the parent directory. Publication
failure cleans the unpublished file and is `failed`; discard the held success bytes,
write the root-only failed row to a fresh report candidate created and cleaned up the same way, validate and remove
it by the same protocol, and return only that validated stdout. If this validation
also exits 2, emit nothing rather than substitute a prose result. On publication
success, return only the previously validated stdout bytes, whose root path is the
exact destination. For the default nondurable route, return those bytes after
validation without a replace.

Suggest the skills to be used, if any, by the next session.

Do not duplicate content already captured in other artifacts (specs, plans, design docs, issues, commits, diffs). Reference them by path or URL instead.

Do not duplicate lifecycle JSON in the handoff document. The run ledger owns
identity, phase action, attempt state, and compact outcomes; reference the run and
artifact paths only.

Redact anything sensitive on the way in — API keys, tokens, passwords, personally identifiable information. Command output sitting in context is the usual source, and the handoff doc outlives the session that wrote it.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.
