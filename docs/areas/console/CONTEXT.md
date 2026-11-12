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
Anything waiting on the owner that the console asks them to act on, whatever its source; a manager's brief is one. The console's statement counts the open ones, "N things need you"; with none and a readable tracker it reads "Nothing needs you". A session waiting in its terminal is not one: it is answered there (ADR-console-004).
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
The one agent a sprint has: it writes the brief and the reports and never writes code (#835). The console starts it as a background Claude Code session in the project's root, under the profile with the most weekly allowance left, drafts the brief under the contract `sprint contract` prints and shows it inside its sprint with its state (ADR-console-015). It reads the owner's messages with `sprint inbox` at the start of every turn, and after approval its contract tells it to end the turn before any tracker action once the sprint is no longer open (ADR-console-016).
_Avoid_: owner, worker, agent, bot

**Message**:
What the owner says to one sprint: an approval, a change request or free text. The console stores it, the manager reads it with `sprint inbox`, and the sprint line shows it as sent, delivered or read, with the manager's reply under it (ADR-console-016).
_Avoid_: chat, comment

**Nudge**:
The console's one fixed sentence telling a manager to read its inbox, by relay to a running manager or by waking a stopped one in place; it never carries the owner's words (ADR-console-016).
_Avoid_: ping, notification

**Report**:
The manager's fixed-shape account after each batch and on any change of state: a status line, each issue's stage or outcome, the inbox items it raised, the next step and the milestone (ADR-console-014).
_Avoid_: update, log

**Sprint**:
One goal, later its issues and its outcome, in one project (#834), shown under its project as one line with its state (drafting the brief, starting, on track, waiting on you, quiet and may be stuck, closing or done), its progress and its manager's status until it is withdrawn; its manager session is listed inside it, and a manager that failed to start or is missing offers a retry (ADR-console-011, ADR-console-013, ADR-console-014, ADR-console-015).
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
"Since you last looked": what changed since the last look in plain sentences, newest first, five shown and the rest under "Earlier"; a first visit covers the last eight hours.
_Avoid_: activity feed, changelog

**Delivery run**:
One Workflow run of a delivery program started by a session, shown under that session in its project's Outside sprints line while it has no final record: each issue it carries with its stage in plain words (queued, planning, plan review, building task n of m, final review, verifying, landing, done; working for a step the console does not know), and how long since it last moved, quiet for N min after fifteen minutes (ADR-console-005). The run reads as one sentence of counts by stage, its issues and stages shown when its line is opened.
_Avoid_: sprint, job

**Limit reading**:
The last unified rate-limit state the cache proxy saw for one account profile: status, weekly and 5-hour use, and resets (ADR-console-006).
_Avoid_: usage

**Limit stop**:
A refusal because a window is used up, recorded with its window and reset (ADR-console-006).
_Avoid_: rate limit error

**Capacity strip**:
The top-bar line of each profile's share left and next reset. It reads "tight" when one profile has room among two or more while every other reads out, folds profiles with no reading into one note, and is promoted into the statement when every profile is out (ADR-console-006).
_Avoid_: quota bar

**Console service**:
The user service that runs the console on each host. On Linux the systemd unit retries without limit, three seconds apart (`RestartSec`, and `StartLimitIntervalSec = 0` in place of systemd's default start limit), so a console that cannot bind its port because another process holds it keeps retrying and serves within one interval of the port being freed, with no manual restart (#884); launchd's `KeepAlive` does the same on macOS.
_Avoid_: daemon
