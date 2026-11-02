---
name: worktrees
description: Creates or confirms an isolated git worktree and leaves it safely. Use before feature work, plan execution, or prototypes that must not touch the current branch.
---

# Worktrees

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. All branch, worktree naming, signing, merge, and deletion policy comes from `bindings.vcs`.

Guarantee an isolated workspace, then hand control back; the caller owns branching policy, the work and shipping.

## Destructive operations

Creating a worktree needs no confirmation. Removing one, discarding changes in one or deleting its branch happens only when the caller's flow authorizes it (from-issue's orphan cleanup, ship-issue's post-merge cleanup) or the user asks. Uncommitted work in a worktree you didn't create is never yours to discard: report it.

Never repair a worktree with `git reset --hard`, `git checkout --`, `git clean -fdx` or `git branch -D`; describe the situation instead. `git clean -fdx` also deletes ignored scratch a running flow needs: `ship-issue`'s retained Minor/Discussion detail in a feature worktree, every plan's SDD workspace in the primary checkout.

## Already positioned? Skip the call

The harness pins one worktree per session and refuses redundant or cross-pinned entries, so check state first:

- Before `EnterWorktree`, compare `pwd` with the target. Already inside it: skip the call. Pinned to another worktree: `ExitWorktree` with `action: "keep"` first.
- On leaving, use `action: "keep"` whenever another session or agent may still use the worktree; `"remove"` only when this flow created it and its work has landed.
- Call `ExitWorktree` only from inside the worktree.

## Shell forms the isolation checker refuses

The checker runs a command only when it can verify it stays inside the worktree: one plain command whose targets are literal arguments. It refuses four forms: a multi-clause chain (`&&`, `||`, `;`), a pipe, a redirect (`2>/dev/null` included), and a heredoc fed to stdin. Instead:

- One command per call; decide the next call from the previous exit status and output. Filter or count output by reading it.
- Create files with the file-writing tool and pass them by path (`--notes-file`, `-F <file>`), or pass a body as one literal quoted argument with no substitution.
- Carry the directory in the invocation: absolute paths under the worktree, or a directory flag such as `git -C <path>`. A `cd` prelude is itself a refused chain.
- Read a non-zero exit instead of suppressing stderr.
- One chain is sanctioned: the `unset GITHUB_TOKEN && ` prefix that `ship-issue/SKILL.md`'s gh hygiene derives from `bindings.tracker.credential_env.unset_before_invocation`, spelled exactly as there.
- One pipeline is sanctioned: a lifecycle helper call (one heredoc-fed `workflow-state` command, optionally piped into or out of `artifact-budget validate-report --input -`) exactly as `from-issue/SKILL.md`'s lifecycle-call rule spells it. Never copy that shape to another command. If the checker refuses one, report the refusal rather than reshape the call.
- On a refusal, change the shell form, never the isolation.

## Detect existing isolation

```bash
git rev-parse --path-format=absolute --git-dir --git-common-dir --show-superproject-working-tree
```

The first two lines differ: you are in a linked worktree; report its path and branch and stop. They match: this is the default checkout. A third line appears only inside a submodule, whose first two lines also match; a submodule is not isolation.

## Branch and prefix contract

`bindings.vcs.branch_pattern` names the branch. **`EnterWorktree` prepends `bindings.vcs.worktree.prefix`**, so the on-disk branch is `<worktree-prefix><pattern>`. Everything downstream (pre-flight searches, PR lookups, cleanup) accepts both forms: never strip the prefix, never assume its absence.

Without a native worktree tool: `git worktree add -b <branch> <path> origin/<integration-branch>`. Base on the remote ref; the local branch may carry another agent's commits. Resolve an authored relative `bindings.vcs.worktree.root` against `project.root`, create worktrees only beneath it, and confirm it is ignored first. If creation fails for any reason, **never work in place**: report blocked with the exact failure and let the caller choose between fixing permissions, another location, or explicitly authorizing in-place work.

## refs/stash is shared

Stashes are global to the repository, so another worktree can pop yours. Don't stash; commit on your own branch instead.

## Setup and baseline

Run the project's install step only if the worktree needs it, then the caller's verify command once. Report a failing baseline instead of proceeding: it makes every later failure ambiguous.
