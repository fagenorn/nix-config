---
name: worktrees
description: Put work in an isolated git worktree and leave it safely. Use before feature work, plan execution, or prototypes that must not touch the current branch.
---

# Worktrees

Guarantee an isolated workspace exists, then hand control back. The caller owns branching policy, the work, and shipping.

## Destructive-ops carve-out

Creating a worktree is safe and needs no confirmation. Removing one, discarding changes in one, or deleting its branch is destructive: do it only when the caller's flow authorizes it (from-issue's orphan cleanup, ship-issue's post-merge cleanup) or the user asks. Uncommitted work in a worktree you didn't create is never yours to discard — report it.

Never repair a worktree with `git reset --hard`, `git checkout --`, `git clean -fdx`, or `git branch -D`. Those destroy state you cannot see the value of; describe the situation instead. `git clean -fdx` also deletes git-ignored scratch a run in progress depends on: in a feature worktree that is `ship-issue`'s retained Minor/Discussion detail, and in the primary checkout it is every plan's SDD workspace.

## Already positioned? Skip the call

A worktree-failure audit found **43% of `EnterWorktree`/`ExitWorktree` errors are calls made while already positioned** — the harness pins one worktree per session and refuses redundant or cross-pinned entries. Check state; don't discover it by letting a call fail.

- Before `EnterWorktree`: compare `pwd` with the target path. Already inside it → skip the call entirely. Pinned to a different worktree → `ExitWorktree` with `action: "keep"` first.
- On leaving: `action: "keep"` whenever another session or agent may still be using the worktree. `"remove"` only when this flow created it and its work has landed.
- Never call `ExitWorktree` from outside the worktree — `cd` in first.

## Detect existing isolation

```bash
[ "$(git rev-parse --git-dir)" != "$(git rev-parse --git-common-dir)" ] &&
  ! git rev-parse --show-superproject-working-tree 2>/dev/null | grep -q .
```

True → you are already in a linked worktree; report the path and branch and stop. (The submodule check matters: a submodule also has a distinct git-dir and is *not* isolation.)

## Branch and prefix contract

The caller's `branchNaming.pattern` (default `issue-<num>-<slug>`) names the branch. **`EnterWorktree` prepends `branchNaming.worktreePrefix`** (default `worktree-`), so the on-disk branch is `<worktreePrefix><pattern>`. Both forms are accepted by everything downstream — pre-flight searches, PR lookups, cleanup — so never strip the prefix to "correct" it, and never assume its absence.

No native worktree tool: `git worktree add -b <branch> <path> origin/<integration-branch>`. Base on the remote ref, not the local branch, which may carry another agent's in-flight commits. Put worktrees in `.worktrees/` at the repo root and confirm it is ignored (`git check-ignore -q .worktrees`) before creating anything inside it. If creation fails — sandbox permission error or anything else — **never silently work in place**: isolation was the caller's requirement, and in-place work puts commits on a branch the caller promised not to touch. Report blocked with the exact failure and ask for direction; the caller decides between fixing permissions, another location, or explicitly authorizing in-place work.

## refs/stash is shared

**Stashes are global to the repository, not per worktree.** In any parallel run — several agents, several worktrees — a stash you push can be popped by another worktree and lands as a foreign diff. Don't stash. Commit on your own branch instead; a throwaway commit is recoverable and private, a lost stash is neither.

## Setup and baseline

Run the project's install step only if the worktree needs it (a fresh `node_modules`, `cargo build`, `uv sync`), then the caller's verify command once. A failing baseline before you change anything makes every later failure ambiguous — report it rather than proceeding silently.
