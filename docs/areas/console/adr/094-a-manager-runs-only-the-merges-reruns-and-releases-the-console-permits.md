# ADR-console-094 — A manager runs only the merges, reruns and releases the console permits

- **Status:** accepted
- **Decided in:** #1377

## Context

ADR-console-021 refuses every permission prompt in a manager's session, and the owner's global settings allow `Bash(gh pr merge:*)`, so a manager's merge of its sprint's green pull requests, a rerun of a failed check and the release of a sprint's merged work all ended at the owner's hands. The owner decided on 21 Nov 2026: "Allowed for a manager session: `gh pr merge <n> --repo <its project> --match-head-commit <sha>` of a pull request of its own sprint's issue, still judged by the lifecycle guard; `release transaction run` only for a release whose card the owner approved; `gh run rerun <id> --failed --repo <its project>` of its own pull requests' check runs. Still refused: `--admin` merges, merges of other sprints' or unrelated pull requests, production commands outside the release path, deploy reruns, `release transaction abandon` and dispose, and a release run with no approved card. Grant nothing broader."

## Decision

**D1. The owner's list is the whole grant.** A manager may run, each alone, its own sprint's merge at its matched head, the failed-job rerun of its own pull requests' required check runs, and the exact release the owner approved on a release card. Everything else stays refused, and nothing broader is granted.

**D2. The grant is a hook decision, not an allow rule.** The settings file carries one `PreToolUse` and one `PostToolUse` command hook, matcher `Bash`, commands `sprint permit` (60 seconds) and `sprint permit --landed` (30 seconds), and no `if` filter, because a spelling an `if` rule missed would fall to the global `Bash(gh pr merge:*)` allow. `permissions` holds `defaultMode` and `deny`: no allow rule, no ask rule, no `autoMode`, no `disableAllHooks`. A rule's `*` cannot tell the sprint's pull request from another, a deploy run from a check run, or an approved release from any other, and the file is written only at launch and wake.

**D3. Exact shapes.** The console judges only the literal-word grammar: plain words, single-quoted words and double-quoted words without `$`, a backtick, a backslash or `!`; any operator, redirection, expansion, glob, comment, tilde, brace or newline refuses. A merge is `gh pr merge <n> --repo <slug> --<strategy> --match-head-commit <sha>` with `--delete-branch` exactly when the project's merge settings delete the branch; a rerun is `gh run rerun <id> --failed --repo <slug>`; a release is `release transaction run` with the project's root, the four candidate flags and at least one `--confirm`.

**D4. The resume form is refused.** `release transaction run` with no candidate names no release, so no card can approve it.

**D5. Its own sprint's issue.** The calling session is the sprint's manager session, the issue is in the sprint's newest report, a delivery run seen in that session carries it (the sprint keeps that record after the run is cleaned up), and no other open sprint of the project reports it. A sprint that has ended, a done report included, grants nothing. A pull request is the issue's when its head branch in the project's own repository carries the issue under the project's branch pattern.

**D6. A release card binds the preview.** A release card is a round question with a `release` member, owner only and consequential. Only an answer with no `by` key whose chosen option is the approve option, with no words, approves it. The grant binds commit, version, title and the exact set of `--confirm` tokens, which the release driver derives from the runnable preview's plan digest, so a changed profile, notes or action list is refused. A new brief clears the approvals. The page echoes the release it showed with the answer, and the console records an approval only for an echo that matches the card, so a page open from before this decision cannot approve a release it never showed. The release root must be an absolute path, because the console's working directory is not the manager's. The module and script spellings of the release command are judged and refused: only the `release` executable is granted.

**D7. The owner sees what the approve option runs.** The card shows one line built from the `release` member, never from the manager's question text.

**D8. A rerun is of the sprint's check run** only when the run's event is a pull request, its head repository is the project's, its head branch carries an own issue, the run's pull requests include a same-repository pull request on that branch at the run's head, and every job the rerun would run is named by a required status check of that pull request's base branch that GitHub Actions can satisfy. A failed-job rerun runs every job of the latest attempt that did not succeed, skipped dependents included, across all pages of jobs. Every other run is a deploy or unrelated rerun. A merge names the pull request's head: a different head is refused.

**D9. Every verdict is recorded.** A decided verdict appends a `permit.judged` row; the `PostToolUse` hook appends a `permit.landed` row only when an allow for the same sprint, session, tool call and merge target was judged within the last 30 minutes. The client names each tool call, and both rows carry that name. A lifecycle-guard refusal blocks the call, so no `PostToolUse` fires.

**D10. Fail closed and revalidate.** An allow needs an active sprint and the calling session as its manager; after the forge reads, the sprint is read again under the ingest lock and any change denies. `sprint permit` prints a deny for a command naming a granted verb when the console, the forge or the input cannot be read, and returns at once, silent, for every other command.

**D11. The evidence window opens at the activation.** The check that a manager merged its own pull request counts from the host's first ok activation whose commit contains the merge commit, never from a committer date, and only a merge made in the manager's own tool call, in the sprint that reported the issue, never another sprint's.

**Deny rules.** The settings also carry `Bash(gh pr merge *--admin*)`, `Bash(release transaction abandon*)` and `Bash(release transaction run *--dispose*)`. A deny rule blocks in every mode and whatever a hook returns.

## Consequences

- The lifecycle guard still judges every merge the hook allows (ADR-guard-003): the hook skips the permission prompt, never the guard.
- A release card the owner approves in the middle of a turn takes effect at the manager's next call, because the console judges each call against the log.
- The release resume form and every deploy rerun stay the owner's.
- Each Bash call of a manager spawns one `sprint permit` that returns at once for a command naming no granted verb.
- A bypass manager (ADR-console-060 D6, never chosen today) keeps the deny rules and the hooks.
- A settings file written before this decision gains the hooks and the rules the next time its manager is launched or woken.
- Related: ADR-console-021, ADR-console-060.
