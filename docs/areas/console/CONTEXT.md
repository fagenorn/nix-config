---
area: Console
budget: 200 lines
---

# Console

Console covers the local page that tells the owner whether they are needed and shows the fleet's projects, and the service behind it: its event log, its derived view and its update stream.

## Language

**Console**:
The per-host loopback service and its one page that say whether the owner is needed and show the projects of the fleet registry. Its truth is its own append-only event log; the page shows a view derived from that log (ADR-console-001).
_Avoid_: dashboard, lead console

**Inbox item**:
Anything waiting on the owner that the console asks them to act on, whatever its source; a manager's brief or question is one. The console's statement counts the open ones, "N things need you"; with none and a readable tracker it reads "Nothing needs you". A session waiting in its terminal is not one: it is answered there (ADR-console-004).
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

**Goal**:
The sentence or two the owner states on the page for one registered project, kept in the console's log and never on the tracker (ADR-console-011).
_Avoid_: task, request

**Brief**:
The manager's answer to a goal: a title of at most 60 characters that names the sprint, what done looks like, what is excluded, the slices, the risks and what it expects to ask. It waits in the inbox until the owner approves it, which starts the sprint, or answers it with a reply; a newer brief replaces it (ADR-console-013, ADR-console-027). It may carry up to eight pictures, each with a line, shown as thumbnails on its card and full size in the viewer (ADR-console-041).
_Avoid_: plan, proposal

**Manager**:
The one agent a sprint has: it writes the brief and the reports and never writes code (#835). The console starts it as a background Claude Code session in the project's root, under the profile the console chooses for every new session (ADR-console-023: the most weekly allowance left among the profiles not signed out; the per-project account binding is no longer read), drafts the brief under the contract `sprint contract` prints and shows it inside its sprint with its state (ADR-console-015). It reads the owner's messages with `sprint inbox` at the start of every turn, and after approval its contract tells it to end the turn before any tracker action once the sprint is no longer open (ADR-console-016). A manager gone two minutes while its sprint has work is woken in place or replaced (ADR-console-017). A manager idle five minutes while its sprint has work is told to go on (not while its own delivery run is in progress and has moved in the last 30 minutes), and waits out its account's quota (ADR-console-020). Its session runs with the client's background isolation guard off and every permission prompt refused with one fixed sentence, so a delivery can write its plan and nothing waits on a prompt nobody sees (ADR-console-021).
_Avoid_: owner, worker, agent, bot

**Message**:
What the owner says to one sprint: an approval, a change request, free text or the answer to a question. The console stores it, the manager reads it with `sprint inbox`, and its sprint shows where it stands: sent (with when the manager picks it up: within a minute when it runs on Linux, else at its next turn), picked up (`sprint inbox` returned it), replied (the manager's reply under it), or not picked up after 5 min, with what the owner can do about it. A brief approval shows only until the manager picks it up; a reply to it shows as the manager's own line, with no approval line above it. The owner's words read "You: <words>" and the manager's reply "Manager: <reply>". Only the latest exchange shows, older ones on demand; a reply stays new until the owner's next look and is announced under the statement, outside the count (ADR-console-016).
_Avoid_: chat, comment

**Question round**:
The questions a manager sends at once with `sprint ask`: each leads with its ask (at most 140 characters), may add a context (at most 400), says what it blocks and offers two to four options of at most 80 characters, one recommended. Each question is an inbox item kept only in the console's log; the owner answers it on the page with an option or their own words, and the answer reaches the manager as a message. A sprint has one open round at a time unless a round is a blocker, and reads waiting on you (n) while any question is open (ADR-console-019, ADR-console-027). A question may carry up to eight pictures, each with a line and optionally marked before or after, shown on its card and full size in a viewer (ADR-console-038). A question whose ask or context names screenshots, a `.png` file or a screenshots folder must carry a picture, or the round is refused with the question named (ADR-console-039). A manager takes back its own open question with `sprint withdraw-question`, or replaces it by naming it in a new round, and the owner then sees only the new card; an answer to a question taken back is refused (ADR-console-040).
_Avoid_: poll, survey

**Notice**:
A short bounded message a manager posts for its project with `sprint notice`, of kind claim, heads-up or hand-off, and the project's other managers read with `sprint notices`. It is kept only in the console's log, and it is information, never approval: nothing is refused because of one. It ends when it is withdrawn or when its sprint ends (ADR-console-044). A claim notice is not a **Claim** of the Claims area, which is an issue's delivery marker.
_Avoid_: lock, reservation, announcement

**Picture**:
One PNG a manager sent to the console, kept by the console under its SHA-256 hash and shown only to the page; one nobody references is removed a day after it was last sent (ADR-console-036). A question's, a brief's and a report's pictures are shown as thumbnails on their card (a report's in its Detail fold) and full size in a modal viewer (ADR-console-038, ADR-console-041).
_Avoid_: screenshot file, attachment

**Nudge**:
The console's one fixed sentence telling a manager to read its inbox, by relay to a running manager or by waking a stopped one in place; it never carries the owner's words (ADR-console-016). One other fixed sentence tells an idle manager to run `sprint recap` and `sprint inbox` and go on, at most one every ten minutes and three without a report (ADR-console-020).
_Avoid_: ping, notification

**Bring-back**:
The console waking a gone manager in place, or starting a successor, while its sprint has work; three within an hour stop the tries and raise one inbox item, managers keep failing (ADR-console-017).
_Avoid_: restart loop, resurrection

**Report**:
The manager's fixed-shape account after each batch and on any change of state: a status line, each issue's stage or outcome, the inbox items it raised, the next step and the milestone; the closing report ends the sprint (ADR-console-014, ADR-console-018). It may carry up to eight pictures, each with a line, shown as thumbnails in its Detail fold and full size in the viewer (ADR-console-041).
_Avoid_: update, log

**Sprint**:
One goal, later its issues and its outcome, in one project (#834). A running sprint is one block in the Work column naming its project, its title, one line of what it is doing now, built from its report's milestone and its issues' stages, who has the ball ("manager working", "waiting on you" or "nothing running, may be stuck", the last read only when nothing the sprint reads has moved for fifteen minutes, or at once when its manager failed to start before any brief was approved, report sent or run moved) and its progress, with its own controls ("Stop and report" while it can be stopped and "Drop the sprint", in a closed "End the sprint" fold); its manager session and report (its status line first) are listed inside it, and a manager that failed to start or is missing offers a retry. Waiting on you covers a brief or question that waits on the owner and a manager waiting for an answer or a permission in its terminal. Ended sprints are lines of the one Finished sprints list, the closing report and the sprint's last exchange opening from its line. It is named by its brief's title (else its goal's first sentence), and only its own detail carries the goal (ADR-console-011, ADR-console-013, ADR-console-014, ADR-console-015, ADR-console-018, ADR-console-027, ADR-console-042).
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
One Workflow run of a delivery program started by a session, shown under that session in its project's Outside sprints line while it has no final record: each issue it carries with its stage in plain words (queued, planning, plan review, building task n of m, final review, verifying, landing, done; working for a step the console does not know), and how long since it last moved, quiet for N min after fifteen minutes (ADR-console-005). The run reads as one sentence of counts by stage, its issues and stages shown when its line is opened.
_Avoid_: sprint, job

**Limit reading**:
The last unified rate-limit state the cache proxy saw for one account profile: status, weekly and 5-hour use, and resets. An idle or exhausted profile is read too: on Linux the console sends one small request under every listed profile every 10 minutes (ADR-console-006).
_Avoid_: usage

**Limit stop**:
A refusal because a window is used up, recorded with its window and reset (ADR-console-006).
_Avoid_: rate limit error

**Capacity strip**:
The top-bar strip, kept to one line, that starts with one word, fine, tight or out, beside its icon, then each account with a reading as its name, a bar and one figure, its share of the week left or out until a time. Only the accounts are listed, the named profiles under `profiles/`; the unprofiled `~/.claude` is not one and is never shown. It reads "tight" when one profile has room among two or more while every other reads out, folds profiles with no reading into one note and names a signed-out profile as signed out, outside that note; idle profiles are read too, so the note counts only profiles not yet read (ADR-console-006, ADR-console-002). An excluded profile is shown marked excluded and is not counted in fine, tight or out (ADR-console-023). An account signed in under two profiles is shown and counted once, and an excluded account's bar is dimmed. It holds no button and shows sign-in words only for a signed-out profile or one whose sign-in ends within three days. It opens the accounts panel (ADR-console-002).
_Avoid_: quota bar

**Accounts panel**:
The one place that holds every account control and detail: opened from the capacity strip or the `a` key and closed with Escape, one row per account with its allowance details, the account it is signed in to, sign-in end and run status, and Exclude, Pin, Sign in and Remove, then Add account (ADR-console-002, ADR-console-023, ADR-console-024, ADR-console-025, ADR-console-026).
_Avoid_: settings page, account menu

**Activation line**:
The one line at the head of the Work column when origin's integration branch carries a console change this host does not run, naming `just switch` and the checkout to run it in; it is not an inbox item and is not counted in the statement (ADR-console-043).
_Avoid_: deploy banner, update notice

**Sign-in state**:
Whether a profile's client is signed in (with the end of that sign-in), signed out, or unknown, read from the client's own status command every 10 minutes on Linux. A signed-out profile, or one whose sign-in ends within three days, is one inbox item that carries the Sign in action: the console runs the client's sign-in with no terminal and shows its link on the page, with a field for a code; an unknown state asks nothing (ADR-console-022, ADR-console-024). A running sign-in's link and code field show in the profile's row of the accounts panel while it is open, and the action reads Sign in for a profile never signed in, Sign in again otherwise. An account added on the page goes straight into its sign-in (ADR-console-025). The reading also keeps the account name (address) the status command reports; the profile's row of the accounts panel shows it and flags two profiles on one account as "same account as <other>" (ADR-console-022, ADR-console-023).
_Avoid_: login expiry

**Excluded profile**:
An account the owner keeps out of the console's automatic choice with the Exclude toggle in the accounts panel, which reads Include while it is excluded; it is never the profile a new session or a manager gets, its allowance and sign-in are still read, and it is kept in the console's log until included again (ADR-console-023).
_Avoid_: disabled profile, paused account

**Pinned profile**:
The one account the owner pins with Pin in the accounts panel (Unpin while pinned); every new session and manager gets it while it has room. Out of allowance, signed out or not yet read, the automatic choice applies and the accounts panel says the pin is not in effect, why and which profile is used instead; it is kept in the console's log until unpinned (ADR-console-023).
_Avoid_: favourite profile, default account

**Console service**:
The user service that runs the console on each host. On Linux the systemd unit retries without limit, three seconds apart (`RestartSec`, and `StartLimitIntervalSec = 0` in place of systemd's default start limit), so a console that cannot bind its port because another process holds it keeps retrying and serves within one interval of the port being freed, with no manual restart (#884); launchd's `KeepAlive` does the same on macOS.
_Avoid_: daemon

**Registration**:
The owner's request, from the page, that the console plan a repository's adoption and, when it is already adopted, record it in the fleet registry; the page shows its result in plain lines (ADR-console-028).
_Avoid_: import, onboarding

**Plan question**:
One open question of a repository's adoption plan, shown on the page as an inbox item titled `Register <name>`, a question card with exactly the answers the plan offers, or one line saying why it cannot be answered there (ADR-console-029).
_Avoid_: adoption prompt, open decision

**Drafted contract**:
The project contract the console drafts for a repository that has none, from its remote and its tracked files; the values it read are shown with where they came from and the rest under one counted line that opens to a plain list, every value changeable before the plan is applied; it lives in the console's state and the stored plan until `adopt-project apply` writes it (ADR-console-031, ADR-console-033).
_Avoid_: generated contract, default contract

**Folder trust**:
The client's per-profile record, `projects[<git root>].hasTrustDialogAccepted` in the profile's `.claude.json`, that lets a background session run in a folder; the console writes it, for every profile, only when the owner approves a registration, and a profile added later gets every registered project (ADR-console-034).
_Avoid_: workspace trust, permission

**Approved adoption**:
A ready adoption plan the owner approved on the page by choosing `Apply it` on its question card: the console applies it in its own worktree, pushes its one branch, opens its pull request and raises one inbox item while the pull request is ready to merge; the owner merges it on the forge (ADR-console-030).
_Avoid_: auto-adoption, auto-merge

**Merged adoption**:
An approved adoption whose pull request the owner merged: the console registers its project once origin's integration branch carries the adoption, says so in the digest, and asks the owner to Retry on a question card when the registration is refused (ADR-console-028 D10).
_Avoid_: auto-registration
