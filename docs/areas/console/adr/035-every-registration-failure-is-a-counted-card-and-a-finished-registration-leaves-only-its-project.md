# ADR-console-035 — Every registration failure is a counted card, and a finished registration leaves only its project

- **Status:** accepted
- **Decided in:** #1085

## Context

The first screenshots of the registration flow (ADR-console-028, ADR-console-030, ADR-console-034) showed a failure as a result paragraph in the Work column. That paragraph named a terminal command (`just switch`, `cd <root> && CLAUDE_ACCOUNT=<profile> claude`, `adopt-project apply --plan-id sha256:...`), an absolute path, a branch or a commit hash, and it was not counted anywhere the owner looks. After a registration succeeded its result stayed on the page next to the project it had created, and an adoption whose pull request was open read as `No project is registered yet.` The owner's sprint rules for the flow are binding: everything that needs the owner is a counted question card; the Work column holds only the one-line state and plain lines; every failure says in plain words what to do next; and no command, plan id, hash or absolute path reaches the page.

## Decision

**D1. The failure card and its route.** A failed plan or registration (a `failed`, `not_registered`, `needs_migration` or `needs_repair` result that is neither the waiting nor the set-aside row) is one inbox question card of reason `register_failed`, titled `Register <name>`, with the options `Try again` and `Not now`. It is answered on the existing `POST /api/register-confirm` with `{"root", "choice"}`, `choice` being `try_again` or `not_now`; no route is added, so the write guard and the route table stay as they are. The page draws the card's headline, why and options verbatim and composes no word of a failure; its answered line reads `Answered, trying again` or `Answered, not now`.

**D2. Try again is a fresh registration.** `Try again` registers the root again with the same checks and run as the Register control; the answers of an earlier answer run are not carried.

**D3. The needs-you line.** While any registration card (`register_failed`, `register_apply`, `register_retry` or `register_confirm`) names the registration's root, the Work column holds the one line `Register <name>: needs you` and nothing else of that registration: no change lines, no note, no adoption. The words are on the card.

**D4. A registered root leaves only its project.** A finished registration whose root is the root of a registered project is not shown; the project shows as any project, and the digest's `<project> was registered.` line is its trace.

**D5. The adoption under way.** With no registered project, a registration that is running or has an adoption in flight makes the statement `An adoption is under way; nothing is waiting on you.` An adoption shows its one line and the one pull request link, never a branch or a commit hash.

**D6. The signing cause.** A signed adoption commit that this host cannot make is a repair of its own, `adopt.commit.signing_unavailable`, found by a probe: when the commit the contract asks to sign fails, `git commit-tree -S` of the base tree is tried, and only a failing probe names signing. Any other commit failure stays `adopt.commit.failed`. The commit is never retried unsigned.

**D7. The kept copy, in words.** A kept worktree or branch is named as a leftover copy kept on this computer, never by a path, branch name or hash, and no note says that applying again clears it: the adoption tool refuses a retained worktree and has no option to clear one, so the note tells the owner to ask an agent to remove the copy.

**D8. Plain next steps.** A next step that named a terminal command says in words who does what: ask an agent to do it in a terminal. The missing-manifest step is `Switch this computer to its current configuration to install them, then choose Try again.` A failing push or a refusal of the forge takes fixed words by kind, and a message of a child or of git that holds a path, a hash or a plan id is dropped from the page and kept in the console's log.

**D9. The trust card words.** The folder-trust `Check again` card (ADR-console-034 D5) gives the route in words: open Claude Code in the project's folder under the profile, accept its trust prompt, close it, then choose Check again. Its `command` member stays on the wire and the page never draws it.

**D10. Long paths break after a slash.** A path in an option or a change line is drawn as one span per segment split after each `/`, with a `wbr` between the segments, so a long path breaks at a slash and the text read back is unchanged. A text with no `/` is one span. `overflow-wrap: anywhere` stays as the last resort for a segment longer than the line.

**D11. Nothing stored is rewritten.** The registration flow was not live before this change, so no stored row carries the replaced words.

## Consequences

- A registration that fails is one counted card the owner answers in place, and the Work column holds one short line while it asks.
- Tests check every failure card and Work line against the pattern `--plan-id|sha256:|[0-9a-f]{12,}|(?:^|[\s("'])/\S`.
- The host check `console-register` answers the Register card it finds and meets the project in the listing, because the view no longer shows a registered result.
- ADR-console-002, ADR-console-028, ADR-console-030 and ADR-console-034 are amended where they named a command, a path or a hash.
- Related: ADR-console-002, ADR-console-028, ADR-console-029, ADR-console-030, ADR-console-033, ADR-console-034.
