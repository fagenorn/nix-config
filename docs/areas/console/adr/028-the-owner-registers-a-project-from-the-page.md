# ADR-console-028 — The owner registers a project from the page

- **Status:** accepted; amended by ADR-console-029, ADR-console-030, ADR-console-031, ADR-console-034, ADR-console-035; extended by #1055 (D10, D11)
- **Decided in:** #1052, #1055

## Context

A project reaches the page only once it is in the fleet registry, and getting it there meant `adopt-project plan` and `adopt-project verify --register` in a terminal. #1052 decided that the owner names a repository on the page and is told, in plain words, what adopting it would change; a repository that is already adopted is registered from the same control. The adoption tools stay the one implementation (ADR-project-contract-004, ADR-project-contract-005), and the console only runs them, off the request path, and says what they found.

## Decision

**D1. The action and the write.** The page's Register project control posts `POST /api/register-project`, a member of `PAGE_WRITES` under the guard of ADR-console-008. The body is one `application/json` object of at most 4096 bytes, exactly `{"path": <string>}`, with no character below 0x20 and no 0x7F; any other body is `400` `bad registration`. A refusal on its merits is `409` with its reason. Success is an empty `204`, answered as soon as the run is dispatched.

**D2. The refusals, in order.** Each refusal runs no plan and appends nothing:

1. `registering a project is not available on this host`;
2. `type the path of a repository` (empty after trimming);
3. `type the full path of the repository, starting with / or ~` (a leading `~` expands to the console's HOME);
4. `<path> is not a directory on this host`;
5. `<path> is not the top of a git checkout` (`git -C <path> rev-parse --show-toplevel`, resolved, must equal the resolved path, bounded at 10 seconds);
6. `<path> is already registered as <project id>` (a fleet registry entry whose resolved root equals it); a registry file that exists but cannot be read is refused first, as `the project registry exists but cannot be read, so no registration was started`, and an absent one is an empty fleet;
7. `a registration is already running for <name>`.

**D3. The plan run.** The console runs `adopt-project plan --repo-root <root> --format json` as a child (no shell, its own process group, `stdin` from the null device, 300 seconds, cancelled when the console closes) on a thread of its own, off the request path. The plan edits nothing in the repository (ADR-project-contract-004).

**D4. What the page is told.** The plain change lines come from the plan's `changes` and `link_rewrites`, in this order, each only when its count is above zero:

- `moves N agent file(s)`, followed by ` under .agents/` when every move target starts with `.agents/`;
- `writes the project contract`;
- `generates N file(s) from the contract` (regenerated projections);
- `writes <paths>`, the non-contract files written, other than the adoption's own records;
- `records the adoption`, when the plan writes any of those records;
- `deletes <paths>`;
- `rewrites N link(s)`;
- `rewrites N path reference(s)`.

`<paths>` names up to three paths (`a`, `a and b`, `a, b and c`) and from four on `a, b, c and N more` (#1057), counting only the files named: the adoption's own records (its path-migration record and its evidence record) are never named, and a plan that writes any ends its `writes` line with `, and records the adoption`, or shows the line `records the adoption` when it writes nothing else (#1060). The rest of the plan document is never shown. The headline names the outcome in plain words. For `bootstrap` it is `What adopting <name> would change: it has no agent files or project contract yet`, and for `reconcile` it is `What adopting <name> would change: it has agent files or a contract to bring up to date`. The note is `The plan has N open question(s).` for a draft with questions, `The plan is a draft: <first blocker>` (or `The plan is a draft.`) for a draft without, and `The plan is ready to apply.` for a ready plan. A ready plan's note is amended by ADR-console-029 D5.

**D5. Already adopted.** A `no_change` plan waits for the `Register <name>` card, and its `Register it` answer is followed by `adopt-project verify --register --repo-root <root>`, the same check the terminal runs. It reads one pinned commit of origin (ADR-project-contract-005), and the project then reaches the page through the registry watcher like any registration. A refusal is one line, `<name> was not registered: <message>` (the error's first message, never its code), `<name> was not registered.` when the error has no message, or `<name> was not registered: <result>` when the report says it registered nothing. A plan that cannot be made reads `The adoption plan for <name> failed: <message>`, or `The adoption plan for <name> could not be made.` without one. A run that failed ends the headline in words (`it took too long and was stopped`, `the adoption tool could not be started`, `it was cancelled`, `the adoption tool stopped with an error`, `the adoption tool gave an answer that could not be read`, `it stopped unexpectedly`), never in an error code or kind word (#1057), and every headline ends with a full stop. Each failed row also carries one plain next-step line in its note (#1062): a missing platform manifest says `just switch` installs it, a missing or unknown remote says to add the origin remote, an unreachable remote says to check it can be reached, `not_integrated` says to merge the adoption, each ending with pressing Register again; a run that took too long, could not start or was cancelled says to press Register again and names the terminal command; any other failure names `adopt-project plan --repo-root <path>` (`adopt-project verify --register --repo-root <path>` for a registration). Success reads `<name> is registered as <project id>.`

**D6. Migration and repair.** These are one line each: `<name> needs migration <id> first: run adopt-project migrate --migration <id> --repo-root <root>` (`migration_required`) and `<name> needs repair <id> first: run resolve-project resolve --repo-root <root>` (`repair_required`). Neither is run from the page.

**D7. What is stored.** A run that ends appends one `registration.ended` row with exactly `by` (`owner`), `root`, `project_id`, `result` (`planned`, `registered`, `not_registered`, `needs_migration`, `needs_repair` or `failed`), `outcome`, `headline`, `lines` and `note`. The row is not in `KEPT_KINDS`: it is removed by the retention of ADR-console-009. A refusal appends none. The view's top-level `registration` member is the latest row with its `at` and `status` `done`, or, while a run is under way, `status` `running` with the headline `Planning the adoption of <name>…`. It is null otherwise.

**D8. The page.** This amends ADR-console-002. A quiet Register project control sits at the foot of the side column, under the projects and shown with an empty fleet too. It opens a one-line path field with Register and Cancel. The typed path is a draft whose text, selection and focus survive every frame. A refused write shows its reason beside the control. The latest result shows beneath it (its one line and its change lines) with a Close that hides it on this page until another result arrives. The plan's open questions are inbox items (ADR-console-029 D10).

**D9. Linux only.** The console registers only where it runs its other owner commands, which is Linux.

**D10. A merged adoption registers its project (#1055).** Once the owner merges the pull request the console opened (ADR-console-030), the console registers the project itself, so the owner runs no terminal command and presses no Register again.

- Trigger and child: each adoption poll round (ADR-console-030 D6, and once at start) ends by running `adopt-project verify --register` for every adoption whose pull request reads `merged` and whose registration is absent or `waiting`, one after another on the poll thread, through the same bounded child as D5 (no shell, its own process group, `stdin` from the null device, 300 seconds, cancelled when the console closes). Never for a closed, open or ready pull request, never on the request path and never inside the ingest lock. The child reads origin, not the checkout (ADR-project-contract-005), so a plan run of another repository may proceed: the run does not take the one-registration mark `_registering`, and a per-plan set keeps one run per adoption.
- The child is told which adoption to look for: `--integration-branch` with the base the pull request was opened against, so an adoption merged into a non-default integration branch is found (ADR-project-contract-005), and `--plan-id` with the adoption's plan id, so the remote carrying an earlier adoption of the same project is `not_integrated` (`waiting`), never the new plan's registration; the registry is not written in that case.
- One row kind records it, `adoption.registration`, with exactly `plan_id`, `number`, `result` (`waiting`, `registered`, `refused`), `project_id`, `reason` and `note`. It is not a kept kind (ADR-console-009) and folds only onto an opened adoption of the same pull request number whose state is `merged`.
- Three outcomes. A `not_integrated` refusal, because origin's integration branch does not carry the adoption yet, is `waiting`: nothing is registered and the next round looks again. A green report is `registered`: the console lists the project at once, without waiting for the registry watcher, and the digest says `<project id> was registered.` Anything else, a failed run included, is `refused`: the reason is in plain words, never an error code, repair id or failure kind (D5, #1057, #1062), and the note ends `choose Retry.` The original failure, or the whole report of any run that is not a green registration with its failed checks, goes to stderr first as one `console: adoption_register_error <json>` line.
- Dedupe. The poll appends a row only when its result or reason differs from the folded one, and does not run a refused registration again. A Retry always appends its outcome, an identical refusal included, so the card's key changes and the card is fresh. The console never writes the registry: the child does (D5).
- The words. Merged and waiting: `The pull request of <name> was merged; waiting for <base> on origin to carry it before registering.` Running: `Registering <name>…`. Registered: `<name> is registered as <project id>.` Refused: `<name> was not registered: <reason>. <next step>` as one line. A closed pull request keeps `The pull request of <name> was closed without merging.` and registers nothing.
- Retry. A refused registration is one ordinary question card in the inbox (ADR-console-029 D10, #1066), reason `register_retry`, with the one option `Retry`; it counts in `N things need you`, and the Work column shows only the registration's one line. Retry posts `POST /api/adoption-register`, a `PAGE_WRITES` member under ADR-console-008, with exactly `{"plan_id"}`, at most 4096 bytes: any other body is `400` `bad registration retry`. Refusals on the merits are `409` with the reason, append nothing and run nothing, in this order: `registering a project is not available on this host`; `a registration is already running for <name>`; `that registration is not waiting for a retry` (no merged adoption of that plan has a refused registration). Success is an empty `204` once the run is dispatched on the tracked worker that `close` joins.
- The closed case. A merged adoption's Approve is refused as `the pull request of this plan was already merged` (ADR-console-030 D1), and the old advice to register the repository again is gone.
- No host check is added, and no `_registering` mark is taken (above): a real check needs a merged pull request on the forge.

**D11. The sprint's decisions.** The decisions of the sprint's four slices are kept in the ADR of the slice that made them: #1052 D1 to D9 here, #1053 and #1066 in ADR-console-029, #1054 in ADR-console-030, and #1055 in D10 above. The owner's rules for the sprint are O1 to O3: tests sandbox HOME, every repository, the remote and the forge, and host checks read the console log or set and restore their own state (O1); everything that needs the owner is an ordinary question card in the left column and counted, never a Work-column button (O2); a slice merges on green checks and the sprint manager takes the review screenshots after merge (O3).

## Consequences

- The owner can see what adopting a repository would change, and register an adopted one, with no terminal.
- Out of scope: migrating from the page, which stays a terminal command the page names. Answering the plan's questions is ADR-console-029, and applying a plan from the page is ADR-console-030.
- A project whose adoption was merged reaches the page with no terminal.
- Tests sandbox HOME (one per case), every repository, the bare remote and the forge, so no case reads or writes the real fleet registry or a real remote.
- There is no host check for D10, because a real one needs a merged pull request on the forge.
- The host check restores what it registered.
- The check restores only after the view shows the run is no longer running, and names what it leaves when it cannot see that.
- Related: ADR-console-002, ADR-console-008, ADR-console-009, ADR-project-contract-004, ADR-project-contract-005.
