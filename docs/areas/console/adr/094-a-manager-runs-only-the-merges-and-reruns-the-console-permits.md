# ADR-console-094 — A manager runs only the merges and reruns the console permits

- **Status:** accepted
- **Decided in:** #1377

## Context

ADR-console-021 refuses every permission prompt in a manager's session, and the owner's global settings allow `Bash(gh pr merge:*)`, so a manager's merge of its sprint's green pull requests and a rerun of a failed check all ended at the owner's hands. The owner decided on 21 Nov 2026: "Allowed for a manager session: `gh pr merge <n> --repo <its project> --match-head-commit <sha>` of a pull request of its own sprint's issue, still judged by the lifecycle guard; `release transaction run` only for a release whose card the owner approved; `gh run rerun <id> --failed --repo <its project>` of its own pull requests' check runs. Still refused: `--admin` merges, merges of other sprints' or unrelated pull requests, production commands outside the release path, deploy reruns, `release transaction abandon` and dispose, and a release run with no approved card. Grant nothing broader."

The owner then removed the release from this decision (21 Nov 2026): a permit that judges the text of a shell command cannot name every spelling that runs a release, so none is granted here, and release enforcement is issue 1401. The manager's settings grant no release run and carry no release rule.

## Decision

**D1. The owner's list is the whole grant.** A manager may run, each alone, its own sprint's merge at its matched head and the failed-job rerun of its own pull requests' required check runs. Everything else stays refused, and nothing broader is granted.

**D2. The grant is a hook decision, not an allow rule.** The settings file carries one `PreToolUse` and one `PostToolUse` command hook, matcher `Bash`, commands `sprint permit` (60 seconds) and `sprint permit --landed` (30 seconds), and no `if` filter, because a spelling an `if` rule missed would fall to the global `Bash(gh pr merge:*)` allow. `permissions` holds `defaultMode` and `deny`: no allow rule, no ask rule, no `autoMode`, no `disableAllHooks`. A rule's `*` cannot tell the sprint's pull request from another or a deploy run from a check run, and the file is written only at launch and wake.

**D3. Exact shapes.** The console judges only the literal-word grammar: plain words, single-quoted words and double-quoted words without `$`, a backtick, a backslash or `!`; any operator, redirection, expansion, glob, comment, tilde, brace or newline refuses. A merge is `gh pr merge <n> --repo <slug> --<strategy> --match-head-commit <sha>` with `--delete-branch` exactly when the project's merge settings delete the branch; a rerun is `gh run rerun <id> --failed --repo <slug>`.

**D4. Its own sprint's issue.** The calling session is the sprint's manager session, the issue is in the sprint's newest report, a delivery run seen in that session carries it (the sprint keeps that record after the run is cleaned up), and no other open sprint of the project reports it. A sprint that has ended, a done report included, grants nothing. A pull request is the issue's when its head branch in the project's own repository carries the issue under the project's branch pattern.

**D5. A rerun is of the sprint's check run** only when the run's event is a pull request, its head repository is the project's, its head branch carries an own issue, the run's pull requests include a same-repository pull request on that branch at the run's head, and every job the rerun would run is named by a required status check of that pull request's base branch that GitHub Actions can satisfy. A failed-job rerun runs every job of the latest attempt that did not succeed, skipped dependents included, across all pages of jobs. Every other run is a deploy or unrelated rerun. A merge names the pull request's head: a different head is refused.

**D6. Every verdict is recorded.** A decided verdict appends a `permit.judged` row; the `PostToolUse` hook appends a `permit.landed` row only when an allow for the same sprint, session, tool call and merge target was judged within the last 30 minutes. The client names each tool call, and both rows carry that name. A lifecycle-guard refusal blocks the call, so no `PostToolUse` fires.

**D7. Fail closed and revalidate.** An allow needs an active sprint and the calling session as its manager; after the forge reads, the sprint is read again under the ingest lock and any change denies. `sprint permit` prints a deny for a command naming a granted verb when the console, the forge or the input cannot be read, and returns at once, silent, for every other command.

**D8. The evidence window opens at the activation.** The check that a manager merged its own pull request counts from the host's first ok activation whose commit contains the merge commit, never from a committer date, and only a merge made in the manager's own tool call, in the sprint that reported the issue, never another sprint's.

**Deny rules.** The settings also carry `Bash(gh pr merge *--admin*)`. A deny rule blocks in every mode and whatever a hook returns.

## Consequences

- The lifecycle guard still judges every merge the hook allows (ADR-guard-003): the hook skips the permission prompt, never the guard.
- Every deploy rerun stays the owner's, and the permit decides nothing about a release.
- Each Bash call of a manager spawns one `sprint permit` that returns at once for a command naming no granted verb.
- A bypass manager (ADR-console-060 D6, never chosen today) keeps the deny rules and the hooks.
- A settings file written before this decision gains the hooks and the rules the next time its manager is launched or woken.
- Related: ADR-console-021, ADR-console-060.
