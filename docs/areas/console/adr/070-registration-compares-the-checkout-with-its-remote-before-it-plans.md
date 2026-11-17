# ADR-console-070 — Registration compares the checkout with its remote before it plans

- **Status:** accepted
- **Decided in:** #1233

## Context

A registration planned from the checkout exactly as it stood on disk. A checkout that was days behind its remote planned and drafted from old files: it could draft a contract the remote already had, or plan against a contract the remote had since changed, and the owner saw nothing that said so. The adoption tool reads the working tree (its plan and verify run the resolver there), so the only way to change what it plans from is to change the checkout, and ADR-console-031 D8 said nothing was written into the checkout before `adopt-project apply`.

## Decision

**D1. When it compares.** A fresh registration compares first: `Register project`, `Try again`, and the run that follows a successful `Update it`. A confirmed `Register it` run and every plan-answer run do not compare; they continue a plan that was already made.

**D2. What it compares.** Only `origin`, and only its default branch. The console runs the listing `adopt_inspection` already owns (`ls-remote --symref origin HEAD refs/heads/*`, parsed by `adopt_inspection.parse_remote_heads`) and fetches that branch with `adopt_inspection.fetch_pinned_args`, which carries `--no-tags`, `--no-write-fetch-head`, `--no-auto-maintenance`, `--no-recurse-submodules` and `--refmap=`, so the fetch writes only `refs/remotes/origin/<branch>` and its objects: no tag, no `FETCH_HEAD`, no configured mapping, no maintenance and no submodule. The branch name is used only when it is a safe name, so a remote cannot steer the refspec. The checkout is behind by the commits of `refs/remotes/origin/<branch>` that `HEAD` does not reach, and the remote has a contract when `.agents/project.json` is in that commit's tree. Every child is an argv list with no shell, no standard input, `GIT_TERMINAL_PROMPT=0` and `-c core.hooksPath=/dev/null`, and is bound: 10 s for a local read, 120 s for the listing and the fetch. The comparison never moves `HEAD`, a local branch or the working tree.

**D3. The behind card.** A checkout that is behind gets one `behind` row, with no plan, no draft and no child. Its headline is `<name> is <N> commit(s) behind its remote, which already has a project contract.` or `... which has no project contract yet.` and its card, of reason `register_behind`, offers `Update it` and `Not now`. The page answers it on the existing `POST /api/register-confirm` with the choice `update` or `not_now`; no new write route is added (ADR-console-008). There is no option to plan anyway: a plan from a stale checkout is the fault this decision removes. `Not now` sets the card aside until the owner registers again.

**D4. The update.** `Update it` fast-forwards the checkout with `merge --ff-only --no-overwrite-ignore`, runs no hook, and does so only when the checked-out branch is the remote's default branch, no tracked file has a change and `HEAD` has no commit the remote lacks. Otherwise it stops and the row is the failed row `<name> could not be updated: <reason>.` with the note `Update the checkout in a terminal, then choose Try again.`, which raises the existing Try again card; the four refusals read `another branch is checked out`, `it has changes that are not committed`, `it has commits that are not on its remote` and `git could not move it forward`. `--no-overwrite-ignore` keeps an ignored local file, such as an uncommitted working-tree contract, from being overwritten by the merge. The update grants no folder trust: only `Register it` and `Apply it` grant it (ADR-console-034). This amends ADR-console-031 D8: before apply, the owner's `Update it` is the one thing that moves the checkout.

**D5. An unreadable remote.** A remote that cannot be read (the listing or the fetch fails, times out or is cancelled) does not stop the registration: it runs as it did before, and its row carries the member `remote` with the sentence `The remote could not be read, so the console used the checkout as it is.` The view entry carries it and keeps it beside the needs-you line while a card names the root, which amends ADR-console-035 D3. Every later plan-answer row of that registration keeps it, because the plan still comes from the unchecked checkout. It is never put into `lines`, which feed the apply card and the pull request body.

**D6. No origin, or no default branch.** A checkout with no `origin`, or whose remote lists no safe default branch, is today's run: nothing is fetched, nothing is said.

**D7. Diagnostics and shutdown.** A failing comparison or update keeps git's own words out of the page and in the console's log (ADR-console-035 D8): the service writes the failing step and git's stderr as a `registration_error` line with verb `compare` or `update` before it shows the plain sentence. Each child runs in its own process group, and the console's stop event ends the running child's group; nothing is started after it is set, and the service starts no compare, draft or plan after it. The one child a stop does not end is the fast-forward merge once it has started: git writes the working tree before it moves `HEAD`, and a kill would leave a half-written tree and a stale `index.lock`.

## Consequences

- A registration of a stale checkout asks before it plans, and says how far behind the checkout is and whether the remote already has a contract.
- The remote listing and the pinned fetch have one home, `adopt_inspection`; the console writes no second copy of either.
- Tests sandbox every remote as a bare repository under a temporary directory with `GIT_ALLOW_PROTOCOL=file`; none touches a real remote.
- Related: ADR-console-008, ADR-console-028, ADR-console-031, ADR-console-034, ADR-console-035.
