# ADR-console-030 — The owner approves a ready adoption on the page and the console opens its pull request

- **Status:** accepted
- **Decided in:** #1054

## Context

ADR-console-029 takes a plan to `ready` on the page and then leaves applying it to `adopt-project apply` in a terminal. #1054 puts applying on the page and carries it on to a pull request the owner merges: the console applies the plan, pushes the one adoption branch, opens its pull request and tells the owner when it is ready to merge (owner decision O2). The plan stays the judge of what is applied (ADR-project-contract-004), and the console never merges.

## Decision

**D1. The write.** `POST /api/plan-approve` is a member of `PAGE_WRITES` under ADR-console-008. Its body is one `application/json` object of at most 4096 bytes, exactly `{"plan_id"}`, a non-empty string with no character below 0x20 and no 0x7F. Any other body is `400` `bad plan approval`. The route is not `/api/approve`, which is the brief approval of ADR-console-013. Refusals on the merits are `409`, append nothing and run nothing, and come in this order:

1. `approving an adoption is not available on this host` (no adopter, or no forge);
2. `a registration is already running for <name>` (a registration, an answer or an approval run is under way);
3. `that plan is no longer the one shown; approve the plan shown now` (the latest row has no plan id, or another one);
4. `only a ready plan can be approved`;
5. `the pull request of this plan is already open` (its pull request is open or ready), or `the pull request of this plan was already merged; register the repository again` (D7).

Success is an empty `204` once the run is dispatched. Each refusal is also one stderr line `console: plan_approve_refused <reason>`.

**D2. The run.** The run is dispatched on a tracked thread of its own and never on the request path.

- Apply runs as the bounded child `adopt-project apply --plan-id <id>`, 1800 seconds (its gates run the contract's verification commands in full), under ADR-console-028 D3's other bounds (no shell, its own process group, `stdin` from the null device, cancelled when the console closes). Apply works in its own worktree outside the target repository and leaves the target's checkout, HEAD and current branch as they were.
- Deletions are acknowledged (`--acknowledge-deletions`) only when the shown row's lines hold a line starting `deletes `: the owner approves exactly what the page showed, and a stored plan that gained a deletion since is refused by apply. The only deletion a plan makes is a superseded evidence record of an earlier adoption, so it is a re-adoption's.
- The pull request's base is the integration branch the resolver read from the applied worktree, returned by apply as the `integration_branch` member of its result; the console reads no contract file.
- The push sends exactly `<commit>:refs/heads/adopt-<12 hex>` to `origin`, where `<commit>` is the full hash apply recorded in the `applied` row: the local branch is never read, so a branch that moved after a failed push cannot publish content the apply gates did not run on, and the page's commit is what the pull request holds. It has `--no-follow-tags` so that no tag rides along whatever `push.followTags` says, within 120 seconds, with prompts off (`GIT_TERMINAL_PROMPT=0`), in its own group, never forced. A branch that is not `adopt-<12 hex>`, or a commit that is not 40 lowercase hex digits, is refused before any process starts.
- The pull request is made through `gh api` (a cancellable runner of the console's own, because `forge_api.run_gh` cannot be cancelled), each call bounded at 30 seconds. It is titled `Adopt <name> onto the agent platform` and its body is the plan's headline and change lines. At most one pull request exists per adoption: before opening, the run looks for an open pull request of the same head and base (`find_pull_request`), and after a failed open it looks once more, so a pull request the forge created before its answer was lost is found on the retry and not opened twice.
- The link is built locally, `https://github.com/<slug>/pull/<number>`, and never read from the forge's answer (as ADR-console-003 does for items). The poll reads the repository that recorded link names, never the checkout's origin of the day, so a moved checkout or a changed origin neither stops the poll nor reads another repository's pull request of the same number.

**D3. The rows.** Two kinds record an approved adoption: `adoption.step`, with the steps `applied`, `apply_failed`, `push_failed`, `open_failed` and `opened`, and `adoption.pull_request`, with the states `open`, `ready`, `merged` and `closed`. Neither is a kept kind (ADR-console-009), so the 90-day retention removes them, and the inbox item goes with them. An `applied` row is appended as soon as apply is green, so a console that closes before the push still resumes: the row is appended even when the close has begun, because apply has already made its branch and a fresh apply on a restart would be refused. While a run is under way the registration's `adoption` is `running`.

**D4. What the page is told.** The registration view gains an `adoption` entry (`status`, `step`, `state`, `headline`, `lines`, `note`, `branch`, `commit`, `url`), worded by `approve.entry`, `approve.apply_failure` and `approve.forge_failure`: each failed step says in plain words what failed and what the owner can do next. No headline, line or note shows an error code, a repair id, an HTTP status, a failure kind or an exception type (#1057, #1062). The original failure (code, detail, transience, exception and traceback) is written to stderr first, as one `console: plan_approve_error <json>` line, before it is translated (the-bar, "Truthful terminal states").

**D5. Retry.** A failed push or pull request keeps the applied branch, and the page offers Try again on the same route. The retry resumes at the step that failed and never runs apply again for a pushed or kept branch. A failed apply offers Approve again, and its note names what to remove first (a kept worktree, a dirty file, a branch left from an earlier attempt).

**D6. The pull request's state and the inbox item.** A poll reads each opened adoption's pull request every 120 seconds (`ADOPTION_SECONDS`), whatever project activity, outside the ingest lock, and appends a row only when the state changes. A pull request is ready to merge when it is open, not merged, and its `mergeable_state` is `clean`, `unstable` or `has_hooks`. `unstable` counts as ready because GitHub answers it for a pull request that can be merged while a check that is not required is pending or failing: this repository requires only `Nix Eval`, `Agent Workflow Tests` and `Instruction Budget`, so the pull request reads `unstable` while `Flake Checker` runs. `blocked` (a required check or review is missing), `behind`, `dirty`, `unknown` and `draft` are not ready. A ready pull request is one inbox item of reason `adoption`, keyed `adoption/<plan id>`, headed `The adoption of <project> is ready to merge`, carrying its link and number. It counts in the inbox total and the headline, sits after the sign-in entries and before the questions, and the sentence is `Open the pull request to merge the adoption.` It is gone once the pull request is merged, closed or reads open again.

**D7. A closed or merged adoption.** A plan id is fixed by the repository's inputs and its answers, so registering an unchanged checkout again gives back the same plan. Approve is refused only while the pull request is open or ready, or once it is merged. A closed one is approved again as a fresh apply, and its note names the branch to delete in the checkout and on origin first, because apply cannot create a branch that still exists. A merged one's note says to bring the checkout up to date with the integration branch before registering again.

**D8. Shutdown.** Every child and every `gh` call runs in its own process group with the console's stop event as `cancel`. The run checks the stop event between stages, a cancelled call ends the run with no row, and `close` joins the approval worker, so the next Try again resumes from the last row.

**D9. The page.** A ready plan with no adoption shows Approve; a step that can be resumed shows Try again. Under the plan, the adoption block shows its headline, lines and note, and a link to the pull request when there is one; the ready pull request is also a card in the inbox. The words are the view's (ADR-console-029 D8). A ready plan's note becomes `The plan is ready: press Approve to apply it and open its pull request, or run adopt-project apply --plan-id <plan id> in a terminal.`, which amends ADR-console-029 D5.

**D10. The console never merges.** It pushes one branch and opens one pull request; the forge's required checks keep merge safety (`.agents/knowledge/rejections/ungated-agent-merges.md`). The owner merges on the forge. Merging from the page is a later sprint.

## Consequences

- The owner takes a repository from a ready plan to a pull request with no terminal, and merges it on the forge once the required checks pass.
- Tests sandbox HOME, every repository, the remote and the forge: never a real push or pull request (O1).
- No host check is added (P8): a real approval would push and open a real pull request.
- A push needs the host's git credential for `origin`, and the pull request needs the host's `gh` credential.
- A re-adoption's deletion is acknowledged by approving the plan that shows it.
- Related: ADR-console-008, ADR-console-028, ADR-console-029, ADR-project-contract-004.
