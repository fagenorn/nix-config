# ADR-guard-004 — A global pre-push hook judges the refs git actually pushes

- **Status:** accepted
- **Decided in:** issue 672 D3, D5, D10

## Context

The text guard reads the command an agent typed, so a push that reaches git through an alias, an `xargs` feed or a wrapper depends on how well the guard recognises each spelling (ADR-guard-002). Git itself knows the real push URL and every ref update, whatever the spelling.

## Decision

The guard has a second entry mode, `--mode pre-push`, which git runs as a global `pre-push` hook (`core.hooksPath` in the shared home-manager module, so every host carries it). It reads git's facts, the resolved push URL and one line per ref update, and judges them through the same predicates and the same base policy, compiled policy and row check as the text mode, so no push rule is written twice. The text guard stays the first line and refuses early, with accepted forms, what the hook would refuse late. The hook judges only an agent session, one whose environment holds a non-empty `CLAUDECODE`.

A global `core.hooksPath` disables every per-repository hook, so the hook chains: after an admitted agent judgement, and always outside an agent session, it runs the repository's own `pre-push` hook, and falls back to git-lfs for the hooks git-lfs would have installed.

The protection against a deliberate bypass is branch protection on the default branch (`just protect-main`, the required checks), not this hook. The hook catches mistaken spellings.

## Consequences

- The hook catches mistaken spellings (an alias, an `xargs` feed, a wrapper), not a deliberate bypass, and one indirection is enough for that. It judges only when `CLAUDECODE` is non-empty and the text guard reads only the Bash command text, so a push hidden in a script file written with the unguarded Write tool and run as `sh ./push.sh` is never seen by the text guard. That script can run `git push --no-verify` or `git -c core.hooksPath=/dev/null push`, which skip the hook, or `unset CLAUDECODE` first, which leaves it nothing to judge. A launcher that starts the child with the variable gone (`sudo`, `nix-shell --pure`, `subprocess.run(..., env={})`) does the same, and a `core.hooksPath` key built by expansion or a git config file edited directly means the managed hook does not run. The text guard's refusal to strip the marker catches the plain spelling only.
- Installers that honour `core.hooksPath` (`pre-commit install` refuses, lefthook writes into the store) must target `<git-common-dir>/hooks`, which a human can do as `GIT_CONFIG_GLOBAL=/dev/null <installer>` and the chain then finds; the same holds for an installer that cannot install into the read-only store directory.
- A repository-local `core.hooksPath` (husky, git-hooks.nix) overrides the global one, so the managed hook does not run there.
- Four hook names get no shim, so a repository's own hook of that name does not run: `push-to-checkout`, `fsmonitor-watchman`, `reference-transaction` and `post-index-change`.
- Test fixtures that push to a local remote run git with `GIT_CONFIG_GLOBAL=/dev/null`, because on a switched host the managed hook judges every push an agent session's test makes.
