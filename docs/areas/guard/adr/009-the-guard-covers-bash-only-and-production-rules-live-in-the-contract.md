# ADR-guard-009 — The guard covers the Bash tool only, and production rules live in the project contract

- **Status:** accepted
- **Decided in:** #1147

## Context

A manager's session runs under the global default permission mode, `auto`, whose per-command judgement refused harmless work three times on 2026-11-16 (an empty green sync merge, a project's documented read-only production check, a release agent's read), and each refusal became a card for the owner. ADR-console-021 already makes a manager's session refuse every permission prompt, so a refusal ends the step. The plan is to run managers in `bypassPermissions` and let the guard stand for the few actions that must never happen. Nobody had written down what the guard can and cannot see, so that switch would rest on an assumption.

## Decision

**What the guard adjudicates.** The five lifecycle verbs (a push, a pull request creation, a branch deletion, a merge, a release creation), the detaching words (`nohup`, `setsid` and `disown`) in every repository, and an agent adding the raise label (ADR-guard-005). Its hook is registered for the Bash tool only: the `PreToolUse` matcher in `home/common/claude-code/default.nix` is `Bash`. Every other tool call reaches no guard.

**Mode.** A `PreToolUse` hook runs before the permission decision, and `bypassPermissions` removes prompts, not hooks, so the guard keeps judging a Bash call in bypass. The check is a throwaway session on this host's pinned Claude Code (2.1.322) started with `--permission-mode bypassPermissions` in a scratch repository, running a guarded verb (`git push origin main`), which the guard must refuse. The result is recorded below once it has been observed.

**What a shell-command guard cannot cover**, each with the nearest enforceable control:

| Route | Why the guard misses it | Nearest enforceable control |
|---|---|---|
| An MCP tool call | The hook sees the Bash tool only | A `PreToolUse` matcher on the declared `mcp__` tool names |
| A write to a key file through Edit or Write | These tools run no shell command | A `PreToolUse` matcher on those tools, judged against declared globs |
| A production command hidden in a project script, alias or `just` recipe | The guard reads the words of the command line, not what the script runs | Declare the contract's command id as the production rule, not the inner binary |
| A raw HTTP call carrying a token | Nothing in the command line names a verb, and the token is the authority | None the hook can enforce: a residual gap |
| A session that edits its own settings to drop the hook | `~/.claude/settings.json` is a writable copy (ADR-guard-006) | None: the guard is not a sandbox, it catches the mistakes of a cooperating session (ADR-guard-005, ADR-guard-006) |

**The decision.** Production rules are declared in the project contract and enforced by the guard in every permission mode. A **production rule** names a command id of the contract, a **read-only route** is a declared way to reach production that only reads, and an **approved release path** is the one declared way to change it. A manager runs in `bypassPermissions` only where those rules are in place or the project declares no production. This record decides the policy; the contract field and the guard's reading of it are separate work, and until they exist a project that declares production is not run in bypass.

## Consequences

- Moving managers to bypass gives up the per-command judgement of `auto` for every route in the table above, except where a matcher or the contract recovers it.
- A residual gap stays a gap. The mitigation for a raw HTTP call is not to hold the token in the session's environment, which no hook enforces.
- A new tool the guard has no matcher for is uncovered by default, so adding a tool that can reach production means adding its matcher in the same change.
