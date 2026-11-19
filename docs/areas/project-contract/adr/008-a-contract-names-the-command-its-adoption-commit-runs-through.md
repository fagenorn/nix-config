# ADR-project-contract-008 — A contract names the command its adoption commit runs through

- **Status:** accepted; D4 amended by ADR-console-082 and ADR-project-contract-009
- **Decided in:** #1249

## Context

A fresh adoption worktree lacks the generated, untracked hook configuration that a project's development environment creates, so a project whose commit hooks need that configuration failed at Apply. ADR-console-071 D3 left running the commit in the development environment open as follow-up #1249.

## Decision

**D1. The member.** `bindings.vcs.commit.environment` is optional: a non-empty string that names a `bindings.commands` key, refused `contract.vcs.not_string` or `contract.vcs.unknown_command_id` at `/bindings/vcs/commit/environment`. The resolver returns it verbatim and never inserts it, so its absence means the commit runs git alone.

**D2. The commit runs through the command, not after it.** The argv is the command's argv followed by `env GIT_TRACE2_EVENT=<trace file> git -C <worktree> commit ...`. It runs in the entry's own `cwd`, resolved (symlinks included) just before launch and required to lie inside the applied worktree; one that escapes, a missing directory or an entry without an argv is refused `adopt.commit.unresolved_environment` with the worktree retained. A hook therefore sees the environment's files, variables and `PATH`. Rejected: running the command first and then a bare commit, because a hook that needs the environment's variables or tools would still fail; skipping hooks; hardcoding the worktree root as the cwd.

**D3. The trace file reaches git alone.** The environment command's process does not get `GIT_TRACE2_EVENT`. The failing-hook evidence of #1236 keys on the first git process that writes the trace, so a git call the environment made before the commit would otherwise be taken for it.

**D4. Scope.** Only `adopt-project apply` reads the member. The console's drafted contract gets no field, because the project of #1236's rerun carries its own contract. The delivery skills' own commits are not changed.

**D5. Failure.** A failing environment command or hook, an environment executable that cannot start and a run past the bound are each retained as `adopt.commit.failed` with `commit_output`, `hook` and `exit` null when git never ran, and each launch or timeout line names the command id. A failing hook can instead be `adopt.commit.signing_unavailable`, decided by the existing probe, which now runs in the same environment, so a signer only that environment provides counts. The commit is never retried without the environment and never skips a hook. Without the binding, a git that cannot start stays `adopt.git.unavailable`.

**D6. Proof and removal.** When the environment ran, which is declared to generate untracked files, the branch proof allows untracked records but still refuses every tracked change, a change inside a submodule included whatever `ignore` it is configured with, and the proved worktree is removed with `--force`. Without the binding, the proof and the unforced removal are unchanged.

**D7. Bound and process tree.** The commit through the environment is bounded by `ENVIRONMENT_TIMEOUT_SECONDS`, the same 300 s as every other git call; the console's apply child stays bounded at 1800 s. The command runs in a process group led by a leash, a shell that reads its stdin and then kills its group. Only apply holds the leash's stdin: it closes it on every outcome, and the kernel closes it when the console kills apply's own group. Either way the launcher, git, its hooks and any straggler end with the commit, so no git can move the branch afterwards. Rejected: `subprocess.run(timeout=...)`, which kills only the launcher, and a new session alone, which the console's group kill of apply would not reach.

**D8. The card says what ran.** The console card's note stops saying the hook ran "without the project's development environment" and says it ran in the environment the contract names for its commit, or in none when it names none, which is true on both paths.

## Consequences

- A contract without the member commits as before: the same git argv, process environment and unforced removal.
- A host's installed resolver refuses the member until that host switches.
- The project adds the member and its command to its own contract before registering.
- The environment command's first run counts against the 300 s bound.
- A launcher that starts a session of its own escapes the leash. Apply still kills and reaps that launcher itself at the timeout, so apply returns; processes it started in that session may outlive it.
- This amends ADR-console-071 D3 and the wording of its card note.
