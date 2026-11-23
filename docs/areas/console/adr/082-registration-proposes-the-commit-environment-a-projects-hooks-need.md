# ADR-console-082 — Registration proposes the commit environment a project's hooks need

- **Status:** accepted; amended by ADR-console-083; D1-D4 amended in place by #1485: the drafted contract no longer proposes the field
- **Decided in:** #1268

## Context

ADR-project-contract-008 lets a contract name the command its adoption commit runs through, but D4 left the console's drafted contract without a field for it. A checkout whose commit hooks need its development environment therefore still failed at the adoption commit, and the owner had to write the contract by hand to get past it. Registration can see the signs of that need and propose the command.

## Decision

Amended in place by #1485: the drafted contract is project schema 3, whose commits always run in the platform's devenv command (`commit-environment`, a platform command, and `bindings.vcs.commit.environment`, a constant), so a registration's draft proposes no commit environment. D1 and D2 keep their recognition rules, which the reconcile proposal of ADR-console-083 uses; D3 and D4 now say what the draft no longer does.

**D1. The recognised environment is a root `devenv.nix` in `HEAD`.** The reconcile proposal (ADR-console-083) proposes `devenv shell --` when a root `devenv.nix` is present in `HEAD`, the base revision Apply's worktree is created from, and an installed commit hook is stranded. An untracked or staged-only file does not count, because Apply's worktree would not hold it. A registration's draft proposes nothing from #1485 on, so a checkout with a recognised environment drafts exactly the five fields and the five facts of ADR-console-031 D2.

**D2. What "installed commit hooks" means.** These are executable `pre-commit`, `prepare-commit-msg` or `commit-msg` files, the hooks whose exit status can stop a commit, in the repository's own hooks directory. That directory is its local `core.hooksPath`, else the common directory's `hooks`. `post-commit` is rejected: git ignores its exit status, and git-lfs installs one in every LFS checkout. Global and system `core.hooksPath` are ignored, because a host-wide pass-through would make every checkout look hooked. `.sample` files never count. Reading runs no hook, and the draft's reading (`read`) no longer reads hooks or environment files: `read_hooks` does, for the reconcile proposal only.

**D3. The field `commit-environment` is not drafted.** It was a main line of a draft that recognised an environment (an eighth main line, ADR-console-033 D1). It is now the one field of a reconcile proposal (ADR-console-083), shown as `commits run in its development shell: devenv shell (found in its files)`, whose line leaves the trailing `--` off the command while the value keeps it, and whose Change offers `none` or a typed command. The ready Apply card states the field's line as its first line. To change it before Apply, the owner chooses `Not now`, which shows the proposal and its Change control again.

**D4. The drafted contract carries neither the command nor the binding.** Schema 3 makes `commit-environment` a platform command and the binding a platform constant, so a draft authors neither and the resolver refuses a contract that does. A reconcile proposal still hands its command to the adopter's `--commit-environment`, never to a draft file. This amends ADR-project-contract-008 D4.

**D5. Apply commits through it.** Apply is unchanged from ADR-project-contract-008 D2-D7: it commits through the named command in the worktree.

## Consequences

- An existing contract is changed only by the reconcile proposal of ADR-console-083.
- The command must be on the console service's `PATH`.
- Amends ADR-console-031 (D2's table), ADR-console-033 (D1's lines) and ADR-project-contract-008 (D4).
- The behaviour is pinned in `tests/test_console_contract_draft.py` (a draft holds no commit environment) and `tests/test_console_commit_failure.py` (the reconcile proposal).
