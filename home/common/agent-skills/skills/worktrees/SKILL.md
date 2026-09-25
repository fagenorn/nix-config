---
name: worktrees
description: Put work in an isolated git worktree and leave it safely. Use before feature work, plan execution, or prototypes that must not touch the current branch.
---

# Worktrees

Run `resolve-project resolve --repo-root <checkout>` once at phase entry and retain the full `ResolvedProject` in memory. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. All branch, worktree naming, signing, merge, and deletion policy comes from `bindings.vcs`.

Guarantee an isolated workspace exists, then hand control back. The caller owns branching policy, the work, and shipping.

## Destructive-ops carve-out

Creating a worktree is safe and needs no confirmation. Removing one, discarding changes in one, or deleting its branch is destructive: do it only when the caller's flow authorizes it (from-issue's orphan cleanup, ship-issue's post-merge cleanup) or the user asks. Uncommitted work in a worktree you didn't create is never yours to discard — report it.

Never repair a worktree with `git reset --hard`, `git checkout --`, `git clean -fdx`, or `git branch -D`. Those destroy state you cannot see the value of; describe the situation instead. `git clean -fdx` also deletes git-ignored scratch a run in progress depends on: in a feature worktree that is `ship-issue`'s retained Minor/Discussion detail, and in the primary checkout it is every plan's SDD workspace.

## Already positioned? Skip the call

A worktree-failure audit found **43% of `EnterWorktree`/`ExitWorktree` errors are calls made while already positioned** — the harness pins one worktree per session and refuses redundant or cross-pinned entries. Check state; don't discover it by letting a call fail.

- Before `EnterWorktree`: compare `pwd` with the target path. Already inside it → skip the call entirely. Pinned to a different worktree → `ExitWorktree` with `action: "keep"` first.
- On leaving: `action: "keep"` whenever another session or agent may still be using the worktree. `"remove"` only when this flow created it and its work has landed.
- Never call `ExitWorktree` from outside the worktree — `cd` in first.

## Shell forms the isolation checker refuses

The same audit found the **shell form** of a command costs 197 error turns, roughly **four times** the redundant-entry class above — the largest single class. The checker runs a command only when it can verify the command stays inside the worktree, and it can do that for one plain command whose targets are literal arguments. Shell control flow and redirection hide the target, so it refuses them rather than guess. Four forms do this: a multi-clause chain (`&&`, `||`, `;`), a pipe, a redirect (including `2>/dev/null`), and a heredoc fed to a command's stdin.

What works instead:

- One command per call. A dependent step is the next call, decided by reading the previous call's exit status and output. Filter or count output by reading it, not by piping it.
- Create files with the file-writing tool and pass them by path where the CLI takes one (`--notes-file`, `-F <file>`), or pass a body as one literal quoted argument with no substitution inside it.
- Carry the directory inside the invocation: absolute paths under the worktree root, or the tool's own directory flag such as `git -C <path>`. A prelude that `cd`s in and chains onward is itself the refused chain.
- Treat a non-zero exit as information — read it and decide the next call — rather than suppressing stderr.
- One chain is sanctioned: the `unset GITHUB_TOKEN && ` prefix that `from-issue/bindings.md`'s tracker-cli hygiene prescribes, spelled exactly as there. The lifecycle guard accepts that literal and nothing looser.
- One pipeline is sanctioned: a lifecycle helper call — one heredoc-fed `workflow-state` command, optionally piped into or out of `artifact-budget validate-report --input -` — stays exactly as `from-issue/SKILL.md`'s lifecycle-call rule spells it, because that rule writes no request file. The shape belongs to those whole-allowed helpers alone: never copy a pipe or heredoc into another command on its strength. Should the checker refuse one, report the refusal rather than reshape the call: that rule owns its form.
- Refused → change the shell form, never the isolation. Rewriting the command to work outside the worktree defeats the call that put you in it.

## Detect existing isolation

```bash
git rev-parse --path-format=absolute --git-dir --git-common-dir --show-superproject-working-tree
```

Compare the first two lines: different → you are already in a linked worktree; report the path and branch and stop. Identical → this is the default checkout. `--path-format=absolute` keeps that comparison true from a subdirectory: without it git prints the common directory relative to the current directory, so a subdirectory of the default checkout reads as a linked worktree. The superproject flag prints **no line at all** outside a submodule, so two lines is the normal case and a third line means a submodule: its first two lines match, so only the third line distinguishes it from the default checkout, and it is *not* isolation.

## Branch and prefix contract

`bindings.vcs.branch_pattern` names the branch. **`EnterWorktree` prepends
`bindings.vcs.worktree.prefix`**, so the on-disk branch is
`<worktree-prefix><pattern>`. Both forms are accepted by everything downstream
— pre-flight searches, PR lookups, cleanup — so never strip the prefix to
"correct" it, and never assume its absence.

No native worktree tool: `git worktree add -b <branch> <path> origin/<integration-branch>`. Base on the remote ref, not the local branch, which may carry another agent's in-flight commits. Resolve an authored relative `bindings.vcs.worktree.root` against `project.root`, put worktrees only beneath that resolved root, and confirm that root is ignored before creating anything inside it. If creation fails — sandbox permission error or anything else — **never silently work in place**: isolation was the caller's requirement, and in-place work puts commits on a branch the caller promised not to touch. Report blocked with the exact failure and ask for direction; the caller decides between fixing permissions, another location, or explicitly authorizing in-place work.

## refs/stash is shared

**Stashes are global to the repository, not per worktree.** In any parallel run — several agents, several worktrees — a stash you push can be popped by another worktree and lands as a foreign diff. Don't stash. Commit on your own branch instead; a throwaway commit is recoverable and private, a lost stash is neither.

## Setup and baseline

Run the project's install step only if the worktree needs it (a fresh `node_modules`, `cargo build`, `uv sync`), then the caller's verify command once. A failing baseline before you change anything makes every later failure ambiguous — report it rather than proceeding silently.
