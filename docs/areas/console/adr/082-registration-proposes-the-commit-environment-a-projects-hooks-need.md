# ADR-console-082 — Registration proposes the commit environment a project's hooks need

- **Status:** accepted; amended by ADR-console-083
- **Decided in:** #1268

## Context

ADR-project-contract-008 lets a contract name the command its adoption commit runs through, but D4 left the console's drafted contract without a field for it. A checkout whose commit hooks need its development environment therefore still failed at the adoption commit, and the owner had to write the contract by hand to get past it. Registration can see the signs of that need and propose the command.

## Decision

**D1. The recognised environment is a root `devenv.nix` in `HEAD`.** The draft proposes `devenv shell --` when a root `devenv.nix` is present in `HEAD`, the base revision Apply's worktree is created from, and the checkout has installed commit hooks (D2). An untracked or staged-only file does not count, because Apply's worktree would not hold it. It is a safe default, so no question card is asked in this slice. Rejected: asking a question for a checkout with no recognised environment, because such a checkout stays planned exactly as today.

**D2. What "installed commit hooks" means.** These are executable `pre-commit`, `prepare-commit-msg` or `commit-msg` files, the hooks whose exit status can stop a commit, in the repository's own hooks directory. That directory is its local `core.hooksPath`, else the common directory's `hooks`. `post-commit` is rejected: git ignores its exit status, and git-lfs installs one in every LFS checkout. Global and system `core.hooksPath` are ignored, because a host-wide pass-through would make every checkout look hooked. `.sample` files never count. Reading runs no hook.

**D3. The field `commit-environment` exists only in such drafts.** This amends ADR-console-031 D2's closed table of 29 fields. It is a main line, `commits run in its development shell: devenv shell (found in its files)`, whose line leaves the trailing `--` off the command while the value and the contract keep it, and whose Change offers `none` or a typed command. This amends ADR-console-033 D1: a draft with the field has eight main lines and eight visible Change controls, and every other draft keeps seven. A draft without the field is unchanged, its plan id included. The ready Apply card states the field's line as its first line. To change it before Apply, the owner chooses `Not now`, which shows the draft and its Change controls again.

**D4. The contract gets the command and the binding.** The contract gets the commands entry `commit-environment` (`argv` from `shlex`, `cwd` `.`, `env` empty) and `bindings.vcs.commit.environment`. `none` writes neither. A resolver refusal reopens the field as a card. This amends ADR-project-contract-008 D4.

**D5. Apply commits through it.** Apply is unchanged from ADR-project-contract-008 D2-D7: it commits through the named command in the worktree.

## Consequences

- An existing contract is never changed by this.
- The command must be on the console service's `PATH`.
- Amends ADR-console-031 (D2's table), ADR-console-033 (D1's seven lines) and ADR-project-contract-008 (D4).
- The behaviour is pinned in `tests/test_console_contract_draft.py` and `tests/test_console_commit_failure.py`.
