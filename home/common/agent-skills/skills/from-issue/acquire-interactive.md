# Interactive direct acquisition

Without literal `--auto`, a dispatcher envelope or an explicit durability request, the invocation is ledger-free: it keeps the ordinary worktree flow and the compact direct return. Phase 1 runs the standard `worktrees` flow:

1. `git fetch origin`. Invoke `worktrees` (it encodes the destructive-ops carve-out, the prefix contract, and the position checks before `EnterWorktree`/`ExitWorktree`). Branch names come from retained `bindings.vcs`; both configured forms are accepted downstream, don't strip them.
2. **Base on `origin/<integration-branch>`**, never the local branch, which may carry other agents' in-flight commits.
3. `cd` into the worktree; every later phase runs inside it. Verify `git rev-parse --git-common-dir` ≠ `git rev-parse --git-dir`.
