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
The manager's answer to a goal: what done looks like, what is excluded, the slices, the risks and what it expects to ask. It waits in the inbox until the owner approves it, which starts the sprint, or answers it with a reply; a newer brief replaces it (ADR-console-013).
_Avoid_: plan, proposal

**Manager**:
The one agent a sprint has: it writes the brief and the reports and never writes code (#835). The console starts it as a background Claude Code session in the project's root, under the profile the console chooses for every new session (ADR-console-023: the most weekly allowance left among the profiles not signed out; the per-project account binding is no longer read), drafts the brief under the contract `sprint contract` prints and shows it inside its sprint with its state (ADR-console-015). It reads the owner's messages with `sprint inbox` at the start of every turn, and after approval its contract tells it to end the turn before any tracker action once the sprint is no longer open (ADR-console-016). A manager gone two minutes while its sprint has work is woken in place or replaced (ADR-console-017). A manager idle five minutes while its sprint has work is told to go on (not while its own delivery run is in progress and has moved in the last 30 minutes), and waits out its account's quota (ADR-console-020). Its session runs with the client's background isolation guard off and every permission prompt refused with one fixed sentence, so a delivery can write its plan and nothing waits on a prompt nobody sees (ADR-console-021).
_Avoid_: owner, worker, agent, bot

**Message**:
What the owner says to one sprint: an approval, a change request, free text or the answer to a question. The console stores it, the manager reads it with `sprint inbox`, and the sprint line shows it as sent, delivered or read, with the manager's reply under it (ADR-console-016).
_Avoid_: chat, comment

**Question round**:
The questions a manager sends at once with `sprint ask`: each says what it blocks and offers two to four options, one recommended. Each question is an inbox item kept only in the console's log; the owner answers it on the page with an option or their own words, and the answer reaches the manager as a message. A sprint has one open round at a time unless a round is a blocker, and reads waiting on you (n) while any question is open (ADR-console-019).
_Avoid_: poll, survey

**Nudge**:
The console's one fixed sentence telling a manager to read its inbox, by relay to a running manager or by waking a stopped one in place; it never carries the owner's words (ADR-console-016). One other fixed sentence tells an idle manager to run `sprint recap` and `sprint inbox` and go on, at most one every ten minutes and three without a report (ADR-console-020).
_Avoid_: ping, notification

**Bring-back**:
The console waking a gone manager in place, or starting a successor, while its sprint has work; three within an hour stop the tries and raise one inbox item, managers keep failing (ADR-console-017).
_Avoid_: restart loop, resurrection

**Report**:
The manager's fixed-shape account after each batch and on any change of state: a status line, each issue's stage or outcome, the inbox items it raised, the next step and the milestone; the closing report ends the sprint (ADR-console-014, ADR-console-018).
_Avoid_: update, log

**Sprint**:
One goal, later its issues and its outcome, in one project (#834), shown under its project as one line with its state (drafting the brief, starting, on track, waiting on you, waiting on quota until <time>, quiet and may be stuck, closing, done, stopping or stopped by you), its progress and its manager's status; its manager session is listed inside it, and a manager that failed to start or is missing offers a retry. An ended sprint folds into its project's Finished sprints a day after it ends (ADR-console-011, ADR-console-013, ADR-console-014, ADR-console-015, ADR-console-018).
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
"Since you last looked": what changed since the last look in plain sentences, newest first, five shown and the rest under "Earlier"; a first visit covers the last eight hours. A session named for a sprint adds no line: the sprint's brief, report and withdrawal lines say what it did.
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
The top-bar line that starts with one word, fine, tight or out, beside its icon, then each profile with a reading as its name, a bar and its share of the week left, then the next reset as a weekday and time, or when work resumes once every profile is out. Only the accounts are listed, the named profiles under `profiles/`; the unprofiled `~/.claude` is not one and is never shown. It reads "tight" when one profile has room among two or more while every other reads out, folds profiles with no reading into one note and names a signed-out profile as signed out, outside that note; idle profiles are read too, so the note counts only profiles not yet read (ADR-console-006, ADR-console-002). An excluded profile is shown marked excluded and is not counted in fine, tight or out (ADR-console-023).
_Avoid_: quota bar

**Sign-in state**:
Whether a profile's client is signed in (with the end of that sign-in), signed out, or unknown, read from the client's own status command every 10 minutes on Linux. A signed-out profile, or one whose sign-in ends within three days, is one inbox item that carries the Sign in action: the console runs the client's sign-in with no terminal and shows its link on the page, with a field for a code; an unknown state asks nothing (ADR-console-022, ADR-console-024). A running sign-in's link and code field show on every page of the console, and the action reads Sign in for a profile never signed in, Sign in again otherwise. An account added on the page goes straight into its sign-in (ADR-console-025).
_Avoid_: login expiry

**Excluded profile**:
An account the owner keeps out of the console's automatic choice with the Exclude toggle on its capacity strip entry, which reads Include while it is excluded; it is never the profile a new session or a manager gets, its allowance and sign-in are still read, and it is kept in the console's log until included again (ADR-console-023).
_Avoid_: disabled profile, paused account

**Pinned profile**:
The one account the owner pins with Pin on its capacity strip entry (Unpin while pinned); every new session and manager gets it while it has room. Out of allowance, signed out or not yet read, the automatic choice applies and the strip says the pin is not in effect, why and which profile is used instead; it is kept in the console's log until unpinned (ADR-console-023).
_Avoid_: favourite profile, default account

**Console service**:
The user service that runs the console on each host. On Linux the systemd unit retries without limit, three seconds apart (`RestartSec`, and `StartLimitIntervalSec = 0` in place of systemd's default start limit), so a console that cannot bind its port because another process holds it keeps retrying and serves within one interval of the port being freed, with no manual restart (#884); launchd's `KeepAlive` does the same on macOS.
_Avoid_: daemon
