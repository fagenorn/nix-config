---
name: codex-collaboration
description: Runs and dispositions a read-only Codex plan or diff review. Use for a configured Codex review.
user-invocable: false
---

# Codex Collaboration

`plan-review` follows [PLAN-REVIEW.md](./PLAN-REVIEW.md); `diff-review` follows [DIFF-REVIEW.md](./DIFF-REVIEW.md). Codex only reviews; the parent Claude agent owns plan edits and disposition.

## Phase entry and selection

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain
the returned `ResolvedProject` in memory, and treat every resolver error as fatal
before mutation or external effects. On refusal, preserve and report the
resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never
translate it into a partial snapshot or fallback. The operation documents never read raw policy, infer Git policy or resolve again.

`plan-review` selects `bindings.workflow.review.plan` and `capabilities.review.plan`; `diff-review` selects `bindings.workflow.review.code` and `capabilities.review.code`. Route the capability before dereferencing any command: `blocked` stops with its reason and repair ID; `unsupported` makes no Codex call and hands the operation, with no result or fallback verdict, back to its calling controller's native route; only `available` keeps the selected `review_id` and dereferences `bindings.commands[review_id]`. No default, plugin bridge or second resolver. `bindings.paths.hints` is the only project-hint input, passed by path when available.

## Read-only packet rules

Every packet says: remain read-only; do not edit files, mutate Git, create commits, branches or worktrees, change issues or PRs, install dependencies or ship. Use read-only repository and Git inspection of live HEAD files, within the assigned scope. A limit of your own sandbox is never a finding: report what you could not verify as an unreadable artifact or unresolved unknown in the operation's unknowns field. An artifact defect exposed by a failed command is still a finding, anchored in the artifact with evidence.

## Direct configured review

Build the packet from the operation document. Before invoking, classify the selected command's authored argv. It is the one supported shape, the companion shape, only when:

- the basename of `argv[0]` is exactly `codex-companion`;
- `argv[1]` is `task`;
- the remaining tokens are exactly `--reviewer <op>` plus an optional `--fresh`, in any order;
- `<op>` equals the running operation (`plan-review` or `diff-review`).

Any other flag or positional token (this skill owns model, effort, cwd and output, and a positional would displace the stdin packet), and any other argv, bare `["codex"]` included, is a **binding shape error**: a configuration error with no Codex call, no retry and no native fallback. It stops the operation the way `blocked` does, without a repair ID, with one error naming the operation, the `review_id`, the authored argv, the expected form `codex-companion task [--fresh] --reviewer <op>`, and the first failing cause in this order: an executable other than `codex-companion` (bare `codex` included), a subcommand other than `task`, a missing or mismatched `--reviewer`, an unsupported companion token.

**Invocation.** Keep the command's base argv, cwd and declared env (unset only declared env names), append the exact tail, and send the whole packet on stdin, with no positional argument, in the foreground:

```text
bindings.commands[review_id].argv \
  --model gpt-6-astra --effort xhigh \
  --cwd <absolute-worktree> --json
```

The companion's reviewer mode already forces a fresh, read-only, ephemeral thread with its own wall-clock budget.

**Validation.** Require exit 0 and stdout that parses as exactly one JSON object with `status` `0`, empty `touchedFiles`, `runtime.model` `gpt-6-astra`, `runtime.reasoningEffort` `xhigh` and a non-empty `rawOutput` string (the companion's last agent message); then validate the operation's headings. Only that success establishes reviewer identity `Codex`.

On the `available` route a daemon, slot or capacity rejection is surfaced verbatim and stops: no retry, no native fallback. A Codex call under `unsupported` is a routing error, never a capacity rejection. A completed runtime failure, a malformed or mismatched payload, or an operation-schema failure takes exactly one native fallback with the same packet, never a Codex retry; the fallback is not route-establishment evidence.

## Disposition

For `plan-review`, the parent Claude agent verifies and dispositions every finding per PLAN-REVIEW.md. For `diff-review`, return the validated result unmodified to the calling controller per DIFF-REVIEW.md.
