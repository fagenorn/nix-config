# ADR-guard-002 — A git invocation that could transmit refs is refused as a push

- **Status:** accepted
- **Decided in:** issue 655, issue 672 D3, D8

## Context

Only `git push` was adjudicated, but git reaches a remote through more doors than that: aliases, external `git-<name>` programs, transports such as `send-pack`, and `-c` or environment settings whose values git runs as commands (`core.pager`, `core.sshCommand`, `GIT_SSH_COMMAND`). The guard cannot know what an alias resolves to without reading git configuration, and a configuration file is itself something an agent can write.

## Decision

A git invocation that could transmit refs and is not an admitted lifecycle form is refused as a push. The test is a set of closed tables, not a search for dangerous words: the global options git may carry, the local subcommands that cannot transmit refs, the options whose values git runs, and the environment assignments that may precede a git word. Anything outside a table is refused. The guard never reads git configuration, so an alias is refused by its name. The same rule judges a git word at a command position, at an argument position and in raw text, so the guard keeps no list of runners such as `xargs` or `timeout`.

Issue 672 D3 and D8 add two refusals that protect the pre-push hook: clearing the agent session marker `CLAUDECODE`, and `git config` naming `core.hooksPath`.

Closed tables refuse more than they need to, and the guard prefers that to an open list a new subcommand or option would slip past.

## Consequences

- A mention is judged like a command, so `rg -n git README.md`, `echo git p`, `nix-shell -p git jq`, `ps aux | grep git`, `echo $(which git) status` and a `which git` that follows a pipe or shares a command with a redirection are refused; the author writes `rg -n '[g]it'` or `echo 'git p'`. A bare-word mention such as `printenv CLAUDECODE` is refused too; `echo $CLAUDECODE` reads it.
- Residuals, none closed: a runner that takes its words from a file (`xargs -a args.txt git`), a variable assigned an option elsewhere in the command (`X=--exec=sh; git rebase $X`), and a command word the guard cannot resolve to git from the command's own text: a variable built from pieces (`G=g; H=it; $G$H p`) or set by `read`, `printf -v`, `declare -n`, `set --` or the environment, and an ANSI-C escape that spells a letter (`$'g\x69t' p`).
- Channels that run a file the agent must first write, no different from running that file (`sh /tmp/p.sh`): git configuration files (`git config core.pager …` then `git log`, hooks, `core.fsmonitor`, credential helpers), `PATH`, `HOME` and `XDG_CONFIG_HOME` assigned outside a git prefix, merge strategy programs (`-s <name>` runs `git-merge-<name>` from `PATH`), `source`d environment files, variables set by `read`, `printf -v` or `declare -n`, `ext::` remote URLs (git's default `protocol.ext.allow` is `never`), and `gh` aliases.
- Further residual classes: stdin fed to a fed command through an fd-numbered redirection (`0<<<`, `0<file`, `exec 0<`) or a zsh coprocess; a fed git after an empty substitution or unset expansion between the feeder and git (`xargs $(true) git`); git spelled through a braced default glued to literal text (`${G:-g}it`, `g${G:-i}t`). These deliberate obfuscations are out of scope for the text guard and are covered by the pre-push hook of ADR-guard-004.
- The environment-assignment check leaves `PATH` and `HOME` assigned outside a git prefix, a value set by `read`, `printf -v` or `declare -n`, and a `source`d file that assigns one.
