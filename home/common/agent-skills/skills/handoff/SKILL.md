---
name: handoff
description: Compacts the current conversation into a handoff document so a fresh session or agent can continue the work. Use to pause or hand off work.
argument-hint: "What will the next session be used for?"
---

Write a handoff document that lets a fresh agent continue this conversation's work. Arguments, when given, describe the next session's focus: tailor the document to it.

## Content

- Open with four facts in prose: the exact deliverable, the source and scope of the user's existing authorization, the next authorized action, and any actual permission denial. Authorization survives a phase change or a new session; call out a changed target or external effect as outside it. Add no transport or lifecycle JSON keys.
- Reference specs, plans, issues, commits and diffs by path or URL; never copy them. The run ledger owns identity, phase action, attempt state and outcomes: reference the run and artifact paths, never its JSON.
- Suggest the skills the next session should use.
- Redact secrets and personal data (keys, tokens, passwords, PII), above all from command output in context: the document outlives the session.

## Destination

By default the candidate is nondurable: `mktemp "${TMPDIR:-/tmp}/handoff-XXXXXX.md"` creates it empty, so write the full candidate straight into it without reading it back.

A caller-provided destination for the current `run_id` is accepted only under that run's existing `.superpowers/workflows/<run-id>/handoffs/` directory. Validate every parent component with no-follow directory opens and reject any path escape, symlink or non-directory. Inspect the leaf without following it: reject an existing symlink or non-regular file; a missing leaf is allowed. Write and fsync the full candidate as a sibling temporary regular file without following any leaf; it must be a sibling because publication is a same-directory hard link or atomic replace. Do not open the destination for writing yet.

## Budget check

After the full candidate is written, run `artifact-budget check --kind handoff --root <candidate-root> --format json`; the checker owns every threshold.

- Exit 2 is `failed`: report the candidate root if known, with no metrics or status.
- On the first exit 3, rewrite once to remove duplicated artifact, lifecycle, diff and log content, keeping the continuation decisions and references, then check again. A second exit 3 is `stopped`, never `complete`.

On `stopped`, keep a nondurable candidate for inspection. Never install an over-budget durable candidate: move the same file, bytes unchanged, to a clearly nondurable retained path named in the report, then drop the sibling name; if no identity-preserving move exists, remove the sibling and return `failed` rather than copy unmeasured bytes. Any checker exit 2 removes the unpublished candidate. A terminal exit 2 or 3 leaves the destination byte-identical and no temporary name behind.

A content change after a passing check voids its metrics; the writer who changed the content checks again. Installing the same checked file unchanged is publication, not a change.

## Report and publication

The final outcome is one producer report `{state, artifact, notes}` (D11, D14) with `state: complete | stopped | failed`:

- `complete`: `kind: handoff`, the published or nondurable root `path`, the checker's `metrics` (`root_bytes`, `total_bytes`, `file_count`, `largest_member_bytes`) and `budget_status: within_budget`.
- `stopped`: the retained nondurable candidate `path`, the same metrics, `budget_status: over_budget` and the checker's `violations`.
- `failed`: a null artifact, or only `kind` and `path` once a root is known.

`notes` stays within the shared policy's `phase_reports.notes_max_characters` and never inlines artifact contents, member lists, policy, logs, lifecycle rows or diffs.

After the last check, write the report to a candidate from `mktemp "${TMPDIR:-/tmp}/producer-report-XXXXXX.json"`, run `artifact-budget validate-report --boundary producer --input <report-candidate>`, and remove the candidate in a cleanup that runs on every outcome (a `trap` on `EXIT HUP INT TERM`, or `finally`). Hold only the validated stdout. Validation exit 2 is `failed`: emit no fallback text, leave the destination byte-identical and remove unpublished temporaries.

Only an exit-0 check and an exit-0 validation reach durable publication:

- Missing destination: install the checked sibling with an exclusive atomic operation that fails if the leaf appeared meanwhile (a hard link, say), never overwriting that race, then remove the temporary name.
- Existing regular destination: read it, confirm the same regular file is still at the leaf, then atomically replace it with the checked sibling.
- Then fsync the parent directory.

A publication failure removes the unpublished file and is `failed`: discard the held bytes, write a root-only `failed` report to a fresh candidate, validate and clean it up the same way, and return only its validated stdout; if that validation exits 2 too, emit nothing. On success, return the held validated bytes, whose root path is the destination. The nondurable route returns them after validation, with no install.
