---
name: worktrees
description: Put work in an isolated git worktree and leave it safely. Use before feature work, plan execution, or prototypes that must not touch the current branch.
---

# Worktrees

Guarantee an isolated workspace exists, then hand control back. The caller owns branching policy, the work, and shipping.

## Destructive-ops carve-out

Creating a worktree is safe and needs no confirmation. Removing one, discarding changes in one, or deleting its branch is destructive: do it only when the caller's flow authorizes it (from-issue's orphan cleanup, ship-issue's post-merge cleanup) or the user asks. Uncommitted work in a worktree you didn't create is never yours to discard — report it.

Never repair a worktree with `git reset --hard`, `git checkout --`, `git clean -fdx`, or `git branch -D`. Those destroy state you cannot see the value of; describe the situation instead. `git clean -fdx` also deletes git-ignored scratch (ledgers, review packages) that a run in progress depends on.

## Already positioned? Skip the call

A worktree-failure audit found **43% of `EnterWorktree`/`ExitWorktree` errors are calls made while already positioned** — the harness pins one worktree per session and refuses redundant or cross-pinned entries. Check state; don't discover it by letting a call fail.

- Before `EnterWorktree`: compare `pwd` with the target path. Already inside it → skip the call entirely. Pinned to a different worktree → `ExitWorktree` with `action: "keep"` first.
- On leaving: `action: "keep"` whenever another session or agent may still be using the worktree. `"remove"` only when this flow created it and its work has landed.
- Never call `ExitWorktree` from outside the worktree — `cd` in first.

## Shell forms the isolation checker refuses

The same audit found the **shell form** of a command costs roughly **four times** as many errors as the redundant-entry class above — the largest single class. The checker is static: it can confirm a command stays inside the worktree only when the target is a literal argument of a single invocation. Shell control flow and redirection hide the target, so they are refused. The three refused forms are a multi-clause chain, a redirect, and a heredoc fed to a command's stdin.

What works instead:

- One command per call. A dependent step is a second call, never a chain — no `&&`, no `||`, no `;`.
- Create and truncate files with the file-writing tool, never a redirect or a heredoc. The tool takes an explicit path the checker can read.
- Hand a long body to a CLI by path — `--body-file`, `--notes-file`, `-F <file>`, `@<file>` — after the file-writing tool has written it.
- Carry paths inside the single invocation: absolute paths under the worktree root, or the tool's own directory flag such as `git -C <path>`. A prelude that `cd`s in and chains with `&&` is itself the refused chain.
- Refused → change the shell form, never the isolation. Rewriting the command to work outside the worktree defeats the call that put you in it.

## Detect existing isolation

```bash
git rev-parse --git-dir --git-common-dir --show-superproject-working-tree
```

Compare the first two lines: different → you are already in a linked worktree; report the path and branch and stop. Identical → this is the default checkout. The superproject flag prints **no line at all** outside a submodule, so two lines is the normal case and a third line means a submodule: its first two lines match, so only the third line distinguishes it from the default checkout, and it is *not* isolation.

## Branch and prefix contract

The caller's `branchNaming.pattern` (default `issue-<num>-<slug>`) names the branch. **`EnterWorktree` prepends `branchNaming.worktreePrefix`** (default `worktree-`), so the on-disk branch is `<worktreePrefix><pattern>`. Both forms are accepted by everything downstream — pre-flight searches, PR lookups, cleanup — so never strip the prefix to "correct" it, and never assume its absence.

No native worktree tool: `git worktree add -b <branch> <path> origin/<integration-branch>`. Base on the remote ref, not the local branch, which may carry another agent's in-flight commits. Put worktrees in `.worktrees/` at the repo root and confirm it is ignored (`git check-ignore -q .worktrees`) before creating anything inside it. If creation fails — sandbox permission error or anything else — **never silently work in place**: isolation was the caller's requirement, and in-place work puts commits on a branch the caller promised not to touch. Report blocked with the exact failure and ask for direction; the caller decides between fixing permissions, another location, or explicitly authorizing in-place work.

## refs/stash is shared

**Stashes are global to the repository, not per worktree.** In any parallel run — several agents, several worktrees — a stash you push can be popped by another worktree and lands as a foreign diff. Don't stash. Commit on your own branch instead; a throwaway commit is recoverable and private, a lost stash is neither.

## Setup and baseline

Run the project's install step only if the worktree needs it (a fresh `node_modules`, `cargo build`, `uv sync`), then the caller's verify command once. A failing baseline before you change anything makes every later failure ambiguous — report it rather than proceeding silently.
