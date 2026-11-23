---
area: Console
budget: 200 lines
---

# Console

Console covers the local pages, the desk page that tells the owner whether they are needed and shows the fleet's projects and the Spend page, and the service behind them: its event log, its derived view and its update stream.

## Language

**Console**:
The per-host loopback service and its two pages: the desk page, which says whether the owner is needed and shows the projects of the fleet registry, and the Spend page (ADR-console-052). Its truth is its own append-only event log; the page shows a view derived from that log (ADR-console-001). Only a loopback `Host` from a process of the owner's own user reaches the owner's port (ADR-console-076), and a named colleague reaches it only through Tailscale Serve on a guest socket of its own (ADR-console-066, ADR-console-077).
_Avoid_: dashboard, lead console

**Inbox item**:
Anything waiting on the owner that the console asks them to act on, whatever its source; a manager's brief or question is one. The console's statement counts the open ones, "N things need you"; with none and a readable tracker it reads "Nothing needs you". A session waiting in its terminal is not one (ADR-console-004), and a manager's waiting state alone counts nothing (#1424); a manager's held Bash prompt is a permission card the owner answers on the page, and an open card is one item reading "Allow the command once or refuse it on its card." A manager that cannot hear the console is counted too and reads "Bring the manager back, or drop the sprint.", so the statement never says "Nothing needs you" beside a sprint that reads waiting on you (#1247). A held issue whose only open acceptance criteria are owner reviews, with no live runner prompt, is one owner check card per such criterion (ADR-console-054); a closed issue, or one whose held check is already settled, raises none; a look marker whose approved head merged raises none (ADR-console-054 D8).
_Avoid_: ask, notification

**Answered item**:
An inbox item whose owner-action marker has every box ticked, on the tracker or from the page (ADR-console-010); for a verification prompt, the box it was answered with (ADR-console-012). A prompt with both boxes ticked is not answered. It reads as one line, answered <age>, waiting for the agent, opening to its choices and the link; it is not counted, and leaves the list once its marker is no longer live.
_Avoid_: resolved item

**Held work**:
What an inbox item holds back: its own issue plus the open issues it blocks. Items are ordered by it.
_Avoid_: priority

**Waiting since**:
When the console first saw an inbox item, kept in its event log because the tracker cannot supply it.
_Avoid_: age

**Quiet project**:
A registered project with no open work, no live session and no open sprint. It renders as one line, and more than three of them fold into one group, "N quiet projects".
_Avoid_: dormant project, idle project

**Guest**:
A named colleague the owner lists for chosen projects, who reaches the console through Tailscale Serve on a guest door of its own (a Unix socket only Serve and the owner can open, ADR-console-077), shared at this host's own tailnet name, read from this host's Tailscale client (ADR-console-078), reachable from another device only while the tailnet's access rules allow TCP 443 to this host (ADR-console-079), and never on the owner's port; the guest page carries a guest token (its own write token, in its HTML and no other guest response; the owner's token, a credential and the sign-in client's output never reach a guest), shows only the listed projects, and sees the pool's room under neutral account labels (ADR-console-086) and leaves spend, account names and controls, activation, registration, the access list and every release or production confirmation to the owner (ADR-console-066); on the guest page a guest may add and sign in a Claude account of his own after ticking the owner's consent, shown to him as `yours` (ADR-console-087), and may state a goal on a listed project and, on sprints they started, approve or ask for changes to the brief, answer questions other than a look before merge or one the manager marked `owner_only`, and message the manager; everything else there is read-only.
_Avoid_: user, viewer

**Goal**:
The sentence or two the owner states on the page for one registered project, kept in the console's log and never on the tracker (ADR-console-011).
_Avoid_: task, request

**Brief**:
The manager's answer to a goal: a title of at most 60 characters that names the sprint, what done looks like, what is excluded, the slices, the risks and what it expects to ask. It waits in the inbox until the owner approves it, which starts the sprint, or answers it with a reply; a newer brief replaces it (ADR-console-013, ADR-console-027). It may carry up to eight pictures, each with a line, shown as thumbnails on its card and full size in the viewer (ADR-console-038).
_Avoid_: plan, proposal

**Manager**:
The one agent a sprint has: it writes the brief and the reports and never writes code (#835). The console starts it as a background Claude Code session in the project's root, under the profile the console chooses for every new session (ADR-console-023: the most weekly allowance left among the profiles not signed out; the per-project account binding is no longer read), drafts the brief under the contract `sprint contract` prints and shows it inside its sprint with its state (ADR-console-015). It reads the owner's messages with `sprint inbox` at the start of every turn, and after approval its contract tells it to end the turn before any tracker action once the sprint is no longer open (ADR-console-016). A manager gone two minutes while its sprint has work is woken in place or replaced (ADR-console-017). A manager idle five minutes while its sprint has work is told to go on (not while its own delivery run is in progress and has moved in the last 30 minutes or reads waiting on CI, a commit, a release step or the land lock), and waits out its account's quota, or moves to an account with room when its session is stopped and a takeover starts there (ADR-console-020, ADR-console-095). Its session runs with the client's background isolation guard off; a Bash permission prompt whose call states its reason waits up to ten minutes for the owner on a permission card, one with no reason is sent back to the manager for one, and every other prompt is refused at once with one fixed sentence, so a delivery can write its plan (ADR-console-021, ADR-console-100, ADR-console-104). Its session runs in `auto`, and its sprint's detail says why: where its project declares no production or its production rules are in the guard's policy it would run in `bypassPermissions`, which waits on a wake path a bypass manager can receive (ADR-console-060). Its settings also carry two hooks that let it run only its own sprint's pull request merge, its own required check runs' failed-job rerun and the plain `release transaction run` (never abandon or dispose), and deny rules that refuse an `--admin` merge and a release abandon, while its allow rules admit those forms, bare or behind the guard's `env -u` credential prefix, so auto mode does not judge them and the hook still decides each; the console refuses every other merge or rerun (ADR-console-094, ADR-console-098, ADR-console-102), and the release command refuses a candidate the owner has not approved. A plain `sed -n`, `head`, `tail`, `cat`, `grep` or `wc` read whose every path is in its session's own saved tool output or its project root runs without a card (ADR-console-103).
_Avoid_: owner, worker, agent, bot

**Release card**:
The owner's approval of one release candidate, the pair of a commit and a version, as a card outside any sprint: the lead posts it with `release-card post`, the owner clicks Approve release or Decline on the page, and the release command runs only a candidate with an approved card of the last 90 days (ADR-console-097).
_Avoid_: release permit, release authorization

**Permission card**:
A manager's held Bash permission prompt as a card the owner answers on the page with Allow once or Refuse; it names the command, shows the manager's stated reason and shows only while the manager's hook still waits for it, an unanswered prompt is refused after ten minutes, and a prompt with no stated reason is sent back to the manager for one and raises no card (ADR-console-100, ADR-console-104); a long command's card opens with a summary read from its text (what it writes and runs and anything outside the manager's worktree, or that it could not be read) and folds the full text (ADR-console-105).
_Avoid_: terminal prompt, approval

**Message**:
What the owner says to one sprint: an approval, a change request, free text or the answer to a question. The console stores it, the manager reads it with `sprint inbox`, and its sprint shows where it stands: sent (with when the manager picks it up: within a minute when it runs on Linux or macOS (ADR-console-075), else at its next turn), picked up (`sprint inbox` returned it), replied (the manager's reply under it), or not picked up after 5 min, with what the owner can do about it. A brief approval shows only until the manager picks it up; a reply to it shows as the manager's own line, with no approval line above it. The owner's words read "You: <words>" and the manager's reply "Manager: <reply>". Only the latest exchange shows, older ones on demand; a reply stays new until the owner's next look and is announced under the statement, outside the count (ADR-console-016).
_Avoid_: chat, comment

**Question round**:
The questions a manager sends at once with `sprint ask`: each leads with its ask (at most 140 characters), may add a context (at most 400), says what it blocks and offers two to four options of at most 80 characters, one recommended. Each question is an inbox item kept only in the console's log; the owner answers it on the page with an option, their own words, or both in one send, and the answer reaches the manager as a message (ADR-console-072). A sprint has one open round at a time unless a round is a blocker, and reads waiting on you (n) while any question is open (ADR-console-019, ADR-console-027). A question may carry up to eight pictures, each with a line and optionally marked before or after, shown on its card and full size in a viewer (ADR-console-038). A question whose ask or context names screenshots, a `.png` file or a screenshots folder must carry a picture, or the round is refused with the question named (ADR-console-038). A manager takes back its own open question with `sprint withdraw-question`, or replaces it by naming it in a new round, and the owner then sees only the new card; an answer to a question taken back is refused (ADR-console-019). A look card names its issue, pull request and head, and the console records the owner's approval on the issue itself (ADR-console-074). A question the manager marks consequential, and every look card, opens with no option picked: the Recommended badge stays and nothing is sent until the owner picks or types (ADR-console-092).
_Avoid_: poll, survey

**Notice**:
A short bounded message a manager posts for its project with `sprint notice`, of kind claim, heads-up or hand-off, and the project's other managers read with `sprint notices`. The owner posts a heads-up to every manager of a project from the page, and only the owner withdraws it (ADR-console-044). It is kept only in the console's log, and it is information, never approval: nothing is refused because of one. A claim names files and its slice's issue and ends when the slice lands. A notice also ends when it is withdrawn or when its sprint ends (ADR-console-044). Every manager is shown the open notices of its project's other sprints, one line each, in its first prompt, with `sprint inbox` and with `sprint status`, and an overlap of two claims is ordered by a default rule, so only one the rule cannot settle reaches the owner, as one line on the page under its two sprints, never a question (ADR-console-046, ADR-console-085, ADR-console-091). The owner reads a project's open notices in its closed "Notices (n)" fold in the Work column, which counts in nothing that needs the owner. A claim notice is not a **Claim** of the Claims area, which is an issue's delivery marker.
_Avoid_: lock, reservation, announcement

**Live fault**:
An issue of a sprint its manager declared live in production with `sprint live-fault` and its evidence (what was observed, when, how it was proven). It needs no go-ahead; the owner's page shows it on the sprint's line, where only the owner withdraws it, and once one is declared scope changes go to the follow-up issue, never into the fix (ADR-console-099).
_Avoid_: incident, outage, hotfix

**Project question**:
What the owner asks about one registered project, from the page, in its project's Ask box, where the answer opens in the main column, formatted, with what the session needs from the owner as buttons (ADR-console-067). A short read-only session the console starts in the project's folder answers it; the question and its one answer, failure or time-out are kept only in the console's log, never on the tracker, until the owner deletes its thread; a question that looks like a password, token or key is refused and nothing of it is kept (ADR-console-058, ADR-console-093). Its session's spend shows on the Spend page under its project and the questions aspect (ADR-console-059). Its session reads the console's own records of that project (spend, sprints, deliveries, activations and held checks) from a file the console writes for it, and no other file of the console's state (ADR-console-089). An answer offers Dig deeper, which asks again on a stronger model with a longer limit, reads only its checkout and the counts, times and token sums of the project's own delivery transcripts that the console aggregates, and shows its spend before and after (ADR-console-101).
_Avoid_: query, ask

**Question thread**:
A project question and its follow-ups, in order: a follow-up's session gets the thread's earlier questions and answers under the same read-only rules. A thread is kept only in the console's log, and a project's past threads are listed newest first in its closed "Questions (n)" fold, which counts in nothing (ADR-console-059).
_Avoid_: conversation, chat

**Picture**:
One PNG a manager sent to the console, kept by the console under its SHA-256 hash and shown only to the page; one nobody references is removed a day after it was last sent (ADR-console-036). A question's, a brief's and a report's pictures are shown as thumbnails on their card (a report's in its Detail fold) and full size in a modal viewer (ADR-console-038); an owner check card shows the PNGs its prompt names under the project's root or a configured screenshot location the same way (ADR-console-045).
_Avoid_: screenshot file, attachment

**Nudge**:
The console's one fixed sentence telling a manager to read its inbox, by relay to a running manager or by waking a stopped one in place; it never carries the owner's words (ADR-console-016). One other fixed sentence tells an idle manager to run `sprint recap` and `sprint inbox` and go on, at most one every ten minutes and three without a report, none while a report's wait-until time is ahead or its pause stands (ADR-console-020). A relay comes from a sender in the manager's own permission mode that can only message (ADR-console-068).
_Avoid_: ping, notification

**Bring-back**:
The console waking a gone manager in place, or starting a successor, while its sprint has work; three within an hour stop the tries and raise one inbox item, managers keep failing (ADR-console-017).
_Avoid_: restart loop, resurrection

**Report**:
The manager's fixed-shape account after each batch and on any change of state: a status line, each issue's stage or outcome, the inbox items it raised, the next step and the milestone; the closing report ends the sprint (ADR-console-014, ADR-console-018). It may carry up to eight pictures, each with a line, shown as thumbnails in its Detail fold and full size in the viewer (ADR-console-038). A status line that starts with `merge refused: <reason>` marks a merge the guard refused; the sprint's line reads it until a later report without it clears it (the manager's report after the issue lands), and it is never a question (ADR-console-048). A report may state a wait-until time or a pause, and the sprint's line then says so (ADR-console-020).
_Avoid_: update, log

**Sprint**:
One goal, later its issues and its outcome, in one project (#834). A running sprint is one block in the Work column naming its project, its title, one line of what it is doing now, built from its report's milestone and its issues' stages, who has the ball ("manager working", "waiting on you" or "nothing running, may be stuck", the last read only when nothing the sprint reads has moved for fifteen minutes, session output and a running check under its sessions included (ADR-console-042), a manager that failed to start before any brief is waiting on you, with its own card giving the reason in plain words and Retry); while only CI on its pull request, a delivery committing or a release step moves it, its line says which (ADR-console-050), and while only a delivery waiting for or holding the land lock moves it, its line reads "waiting its turn to merge" (ADR-console-050) and its progress, with its own controls ("Stop and report" while it can be stopped and "Drop the sprint", in a closed "End the sprint" fold); its manager session and report (its status line first) are listed inside it, and a manager that failed to start or is missing offers a retry. Waiting on you covers a brief or question that waits on the owner, an open permission card of the sprint's manager, and a manager that cannot hear the console (a manager's waiting state alone is not waiting on you, #1424), its transcript ending in a peer message the client held and did not deliver; the line then reads "the manager cannot hear the console" and says what the owner can do (ADR-console-042). An owner check on a held issue that blocks none of its open issues is not waiting on you: it shows as a "Your check" line inside the block and stays an inbox item. Ended sprints are lines of the one Finished sprints list, the closing report and the sprint's last exchange opening from its line. It is named by its brief's title (else its goal's first sentence), and only its own detail carries the goal (ADR-console-011, ADR-console-013, ADR-console-014, ADR-console-015, ADR-console-018, ADR-console-027, ADR-console-042, ADR-console-050, ADR-console-051).
_Avoid_: job, run

**Session**:
One running Claude Code process on this host, shown under the project of its working directory's main checkout, with one state: working, waiting for an answer, waiting for a permission, idle, or stopped on a usage limit (ADR-console-004).
_Avoid_: agent, terminal

**Outside sprints**:
The one quiet line of a project that counts its sessions working and waiting; opening it lists each session with its delivery runs in flight. It raises no inbox item.
_Avoid_: ad-hoc work, side work

**Not yet managed**:
A repository with a live session that is not in the fleet registry; it is listed with its sessions and counts as no project. A session outside any repository is not listed.
_Avoid_: unregistered project, orphan

**Last looked**:
The last time the page held focus for more than five seconds, recorded by the console when that hold ends, so every browser reads the same one (#837).
_Avoid_: last seen, last visit

**Digest**:
"Since you last looked": what changed since the last look in plain sentences, newest first, five shown and the rest under "Earlier"; a first visit covers the last eight hours. A session named for a sprint adds no line: the sprint's brief, report and drop lines say what it did.
_Avoid_: activity feed, changelog

**Delivery run**:
One Workflow run of a delivery program started by a session, shown under that session in its project's Outside sprints line while it has no final record: each issue it carries with its stage in plain words (queued, planning, plan review, building task n of m, final review, verifying, landing, done; working for a step the console does not know), and how long since it last moved, quiet for N min after fifteen minutes (ADR-console-005); a run of a running sprint's issue reads its sprint's movement for that issue and, while only a wait moves it, ends with that wait (ADR-console-005). The run reads as one sentence of counts by stage, its issues and stages shown when its line is opened.
_Avoid_: sprint, job

**Spend**:
The tokens (input, cache writes, cache reads, output) and estimated list-price dollars the host's sessions and delivery runs used, read from their transcripts and shown per day for 30 days by session, project, sprint, run, phase, account and aspect (ADR-console-049).
_Avoid_: cost, usage

**Spend page**:
The console's second page, at `/spend`, opened from the "Spend" link in the desk page's top bar: today's, the last 7 days' or the last 30 days' spend in tokens and estimated dollars, a per-day trend and the breakdowns by project, sprint, phase, account and aspect; a sprint's or run's spend figure on the desk page opens that item with its phase breakdown. It only reads (ADR-console-052).
_Avoid_: metrics page, dashboard

**Limit reading**:
The last unified rate-limit state the cache proxy saw for one account profile: status, weekly and 5-hour use, and resets. An idle or exhausted profile is read too: on Linux and macOS the console sends one small request under every listed profile every 10 minutes (ADR-console-006).
_Avoid_: usage

**Limit stop**:
A refusal because a window is used up, recorded with its window and reset (ADR-console-006).
_Avoid_: rate limit error

**Capacity strip**:
The top-bar strip, kept to one line, that starts with one word, fine, tight or out, beside its icon, then each account with a reading as its name, a bar and one figure, its share of the week left or out until a time. Only the accounts are listed, the named profiles under `profiles/`; the unprofiled `~/.claude` is not one and is never shown. It reads "tight" when one profile has room among two or more while every other reads out, folds profiles with no reading into one note and names a signed-out profile as signed out, outside that note; idle profiles are read too, so the note counts only profiles not yet read (ADR-console-006). An excluded profile is shown marked excluded and is not counted in fine, tight or out (ADR-console-023). An account signed in under two profiles is shown and counted once, and an excluded account's bar is dimmed. It holds no button and shows sign-in words only for a signed-out profile or one whose sign-in ends within three days. It opens the accounts panel.
_Avoid_: quota bar

**Accounts panel**:
The one place that holds every account control and detail: opened from the capacity strip or the `a` key and closed with Escape, one row per account with its allowance details, the account it is signed in to, sign-in end and run status, and Exclude, Pin, Sign in and Remove, then Add account (ADR-console-023, ADR-console-024, ADR-console-026).
_Avoid_: settings page, account menu

**Account label**:
The neutral name `Account <n>` a guest sees for one account of the pool; every profile signed in to that account shares it, it stays with the account while the account stays in the pool, across a console restart, and carries nothing of a profile name, address or organisation (ADR-console-086); a colleague sees `yours` for the account he added himself (ADR-console-087).
_Avoid_: account name, profile

**Activation line**:
The one line at the head of the Work column when origin's integration branch carries a merged change this host is built from and does not run, in console wording for a console change and in plain words otherwise. It names the commit and carries Activate, which has the console run this host's activation for that commit; it then reads the run's outcome in plain words. It is not an inbox item and is not counted in the statement (ADR-console-043, ADR-system-004, ADR-console-073).
_Avoid_: deploy banner, update notice

**Sign-in state**:
Whether a profile's client is signed in (with the end of that sign-in), signed out, or unknown, read from the client's own status command every 10 minutes on Linux and macOS. A signed-out profile, or one whose sign-in ends within three days, is one inbox item that carries the Sign in action: the console runs the client's sign-in with no terminal and shows its link on the page, with a field for a code; an unknown state asks nothing (ADR-console-022, ADR-console-024). A running sign-in's link and code field show in the profile's row of the accounts panel while it is open, and the action reads Sign in for a profile never signed in, Sign in again otherwise. An account added on the page goes straight into its sign-in (ADR-console-024). The reading also keeps the account name (address) the status command reports; the profile's row of the accounts panel shows it and flags two profiles on one account as "same account as <other>" (ADR-console-022, ADR-console-023).
_Avoid_: login expiry

**Excluded profile**:
An account the owner keeps out of the console's automatic choice with the Exclude toggle in the accounts panel, which reads Include while it is excluded; it is never the profile a new session or a manager gets, its allowance and sign-in are still read, and it is kept in the console's log until included again (ADR-console-023).
_Avoid_: disabled profile, paused account

**Pinned profile**:
The one account the owner pins with Pin in the accounts panel (Unpin while pinned); every new session and manager gets it while it has room. Out of allowance, signed out or not yet read, the automatic choice applies and the accounts panel says the pin is not in effect, why and which profile is used instead; it is kept in the console's log until unpinned (ADR-console-023).
_Avoid_: favourite profile, default account

**Console service**:
The user service that runs the console on each host. On Linux the systemd unit retries without limit, three seconds apart (`RestartSec`, and `StartLimitIntervalSec = 0` in place of systemd's default start limit), so a console that cannot bind its port because another process holds it keeps retrying and serves within one interval of the port being freed, with no manual restart (#884); launchd's `KeepAlive` does the same on macOS, whose job also leaves its children's process groups alone (`AbandonProcessGroup`, ADR-console-075), so a manager started in its own session outlives a restart of the console.
_Avoid_: daemon

**Registration**:
The owner's request, from the page, that the console plan a repository's adoption and, when it is already adopted, record it in the fleet registry; the page shows its result in plain lines (ADR-console-028). Before it plans, the console compares the checkout with its remote and offers to update a checkout that is behind (ADR-console-070).
_Avoid_: import, onboarding

**Plan question**:
One open question of a repository's adoption plan, shown on the page as an inbox item titled `Register <name>`, a question card with exactly the answers the plan offers, or one line saying why it cannot be answered there (ADR-console-029).
_Avoid_: adoption prompt, open decision

**Drafted contract**:
The project-schema-3 contract the console drafts for a repository that has none, from its remote and its tracked files: five authored values (the branch finished work merges into, the lint and test commands, the release and the production rules), three shown with a Change control and two under one counted line that opens to a plain list, each changeable before the plan is applied, and beside them the values the platform derives (the project id and issue tracker, the checks a pull request must pass, the platform versions it runs on, the minutes per delivery attempt, the agent knowledge files it holds) shown as facts with no Change control, each naming the missing file when the repository cannot state it; it lives in the console's state and the stored plan until `adopt-project apply` writes it (ADR-console-031, ADR-console-033, ADR-console-082).
_Avoid_: generated contract, default contract

**Folder trust**:
The client's per-profile record, `projects[<git root>].hasTrustDialogAccepted` in the profile's `.claude.json`, that lets a background session run in a folder; the console writes it, for every profile, when the owner approves a registration and for every registered project each time the console starts, and a profile added later gets every registered project (ADR-console-034).
_Avoid_: workspace trust, permission

**Approved adoption**:
A ready adoption plan the owner approved on the page by choosing `Apply it` on its question card: the console applies it in its own worktree, pushes its one branch, opens its pull request and raises one inbox card while the pull request is ready to merge, has a failed check, holds commits the console did not push, or was closed while another registration is shown; the owner merges it with Merge on that card, pinned to the recorded head (ADR-console-030, ADR-console-088).
_Avoid_: auto-adoption, auto-merge

**Merged adoption**:
An approved adoption whose pull request the owner merged: the console registers its project once origin's integration branch carries the adoption, says so in the digest, and asks the owner to Retry on a question card when the registration is refused (ADR-console-028).
_Avoid_: auto-registration
