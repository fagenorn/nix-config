---
name: codex-collaboration
description: Run a private, isolated Codex pass for plan-review or diff-review and disposition its findings.
user-invocable: false
---

# Codex Collaboration

`plan-review` uses [PLAN-REVIEW.md](./PLAN-REVIEW.md); `diff-review` uses
[DIFF-REVIEW.md](./DIFF-REVIEW.md). Keep Codex review-only. The parent Claude
agent owns plan edits and disposition.

## Phase entry and selection

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain
the returned `ResolvedProject` in memory, and treat every resolver error as fatal
before mutation or external effects. On refusal, preserve and report the
resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never
translate it into a partial snapshot or fallback. Do not read raw policy, infer
Git policy, or resolve again in either support document.

For `plan-review`, select `bindings.workflow.review.plan` and
`capabilities.review.plan`; for `diff-review`, select
`bindings.workflow.review.code` and `capabilities.review.code`. Route that
retained capability before dereferencing any command entry: `blocked` stops with
its capability reason and repair ID; `unsupported` makes no Codex call and
returns the operation, with no result and no fallback verdict, to its calling
controller's documented native route. Only for `available`, retain the selected
`review_id` and dereference `bindings.commands[review_id]`. Do not use a default,
a plugin bridge, or a second resolver. `bindings.paths.hints` is the only
project-hint input and is supplied by path when it is available.

## Read-only packet rules

Every packet says: remain read-only; do not edit files, mutate Git, create
commits/branches/worktrees, change issues or PRs, install dependencies, or ship.
Use read-only repository and Git inspection only, inspect live HEAD files, and
stay in assigned scope. A limitation of your own execution environment is never
a finding: the sandbox denies every write, so report what you could not verify
as an unreadable artifact or unresolved unknown in the operation's existing
unresolved unknowns field, while an artifact defect exposed by a failed command is
still reportable; anchor it in the artifact with evidence.

## Direct configured review

Build the operation packet from its support document. Before any invocation,
classify the selected command's authored argv into exactly one review binding
shape:

1. Exec shape: the basename of `argv[0]` is exactly `codex`.
2. Companion shape: the basename of `argv[0]` is exactly `codex-companion`,
   `argv[1]` is `task`, and the remaining tokens are exactly `--reviewer <op>`
   plus an optional `--fresh`, in any order, where `<op>` equals the running
   operation. No other flag and no positional token may appear: this skill owns
   model, effort, cwd and output, and a positional would displace the stdin
   packet.
3. Anything else is a **binding shape error**.

A binding shape error is a configuration error. It makes no Codex call, no
retry and no native fallback, and stops the operation with one error. The error
names the operation, the `review_id`, the authored argv, and exactly one cause:
unrecognised executable, a companion subcommand other than `task`, a missing or
mismatched `--reviewer`, or an unsupported companion token. It stops the way
`blocked` does, but carries no capability repair ID.

**Exec shape.** Create absolute JSONL and
last-message candidates under `${TMPDIR:-/tmp}` and remove both with `trap` or
`finally` on every outcome. Preserve the selected command object's base argv,
cwd, and declared env (unset only declared env names), append the exact tail,
and send the complete packet on stdin:

```text
bindings.commands[review_id].argv \
  exec --sandbox read-only --model gpt-6-astra \
  -c model_reasoning_effort="xhigh" --json \
  --output-last-message <absolute-last-message> --ephemeral \
  -C <absolute-worktree> -
```

Validate every JSONL object. Require its runtime-selection event to report the
selected model `gpt-6-astra` and selected reasoning effort `xhigh`; require
exactly one terminal agent-message; require a non-empty last-message file whose
UTF-8 bytes equal that terminal agent-message byte-for-byte; then validate the
operation headings. Only that success establishes reviewer identity `Codex`.

**Companion shape.** Preserve the selected command object's base argv, cwd, and
declared env (unset only declared env names), append the exact tail, and send
the complete packet on stdin with no positional argument, in the foreground:

```text
bindings.commands[review_id].argv \
  --model gpt-6-astra --effort xhigh \
  --cwd <absolute-worktree> --json
```

The companion's reviewer mode forces a fresh, read-only, ephemeral thread and
applies its own wall-clock budget, so the tail passes none of these. Require
exit status 0 and stdout that parses as exactly one JSON object in which
`status` is `0`, `touchedFiles` is empty, `runtime.model` is `gpt-6-astra`,
`runtime.reasoningEffort` is `xhigh`, and `rawOutput` is a non-empty string, the
companion's last captured agent message; then validate the operation headings.
No JSONL or last-message candidate is created on this route. Only that success
establishes reviewer identity `Codex`.

On the `available` route, a daemon, slot, or capacity rejection is a binding
capacity rejection: surface it verbatim, stop, make no retry, and take no native
fallback. A Codex call made under `unsupported` is a routing error, never a
capacity rejection. A completed available-command runtime failure, malformed or
mismatched metadata/output, or operation-schema failure uses exactly one native
fallback with the same packet; never retry Codex. The fallback is not
route-establishment evidence.

## Disposition

For `plan-review`, the parent Claude agent verifies and dispositions every
finding per PLAN-REVIEW.md. For `diff-review`, return the validated result
unmodified to the calling controller per DIFF-REVIEW.md.
