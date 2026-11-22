# ADR-project-contract-016 — The never-rise check compares each rule with the merge base

- **Status:** accepted
- **Decided in:** #1455 (per #1414, #1422)

## Context

A rule such as the 1,500-line limit on source and test files could not be enforced on a tree that already holds files over it: a plain run fails forever, and a committed baseline file or a raise label would let the count rise unseen. The decision of #1414 is that the baseline is computed on every run from the branch's own history, with one violation line per violation and no raise path; #1422 sets the first rule, one 1,500-line limit for every source and test file. The Conformance workflow also judged GitHub's synthetic merge commit on a shallow checkout, which holds neither the merge base nor the branch's own head.

## Decision

**D1. Base and branch.** The base is `git merge-base HEAD refs/remotes/origin/<bindings.vcs.integration_branch>` and the branch is `HEAD`. It is never the integration tip itself: on diverged history a tip comparison passes a rise. A missing ref or any failed git read is a `failed` check (`history_unavailable`), never a pass.

**D2. Commits only.** Both sides are read from commits; the working tree is never judged, so a run is deterministic and read-only.

**D3. Per-rule count, per-file comparison.** Each enforcer runs on both revisions. A rule fails when its violation count rises; a per-file rule fails for each file whose own violations rose, so a file already over the budget may not end longer.

**D4. Renames.** A moved file is matched to its base path by git's rename detection (`git diff-tree -M`, git's default similarity) and only for per-file rules. A move git does not pair is a new file.

**D5. The size violation's line.** A size violation's line is the file's last line, so the printed line shows the size and the per-file comparison reads it.

**D6. What counts as source.** A source or test file is every tracked text file except documentation, data, lock files and patches: its lower-cased suffix is not in `size_lint.NON_SOURCE_SUFFIXES` and its name is not in `size_lint.NON_SOURCE_NAMES`. Extensionless scripts and sourced shell fragments are judged, and an unknown suffix is judged (fail closed).

**D7. Verification domain.** The check is a `verification`-domain check, so `ci` and `doctor` run it and `adoption` and `fleet` do not (as ADR-project-contract-015 D5).

**D8. The Conformance checkout.** The rendered workflow checks out `${{ github.event.pull_request.head.sha || github.sha }}` with full history (`fetch-depth: 0`), amending ADR-project-contract-015 D3. On `pull_request` that is the branch head, not GitHub's synthetic merge commit, whose first parent is the integration tip and would hide the branch's own growth behind independent edits on the integration branch; on `push` it is the pushed commit. The engine reads no CI event file: after a full fetch the merge base of the head with `origin/<branch>` equals the merge base with the event's base sha, and `doctor` and `ci` judge the same way.

**D9. Registered command, not the gate.** `size-lint` is a registered command, but the gate is the conformance check, not the command's exit, because files already over the budget make a plain run fail.

**D10. Read-only, non-fetching children.** Every engine git child is bounded, runs with `GIT_NO_LAZY_FETCH=1`, never follows an inherited repository selection and never colours its output (`--no-color`), so a partial clone missing a blob is `history_unavailable` and fetches nothing, and forced colour cannot corrupt a path.

**D11. One violation, one line.** The violation text escapes the path reversibly (a backslash doubled; `\n`, `\r`, `\t` named; other C0 and DEL as `\xNN`; `\x85` and the two Unicode line separators as `\uNNNN`), so a violation is always one output line.

## Consequences

- Files already over the budget stop growing; shrinking them is optional and never required.
- A `push` run judges the pushed commit against itself and passes.
- A `doctor` run on a checkout without the integration branch's remote ref, or on a partial clone missing a blob, reports `history_unavailable` and fetches nothing.
- The Conformance workflow fetches the whole history, which costs more than a shallow checkout.
- Rejected: a committed baseline file, because it is a second source of truth that can be edited to hide a rise.
- Rejected: a raise label (issue 1414), because the rule has no raise path.
- Rejected: judging GitHub's synthetic merge commit, because independent edits on the integration branch hide the branch's own growth.
