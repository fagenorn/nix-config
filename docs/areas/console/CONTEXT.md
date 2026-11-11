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
Anything waiting on the owner that the console asks them to act on, whatever its source. The console's statement counts the open ones, "N things need you"; with none and a readable tracker it reads "Nothing needs you". A session waiting in its terminal is not one: it is answered there (ADR-console-004).
_Avoid_: ask, notification

**Answered item**:
An inbox item whose owner-action marker has every box ticked. It is shown as waiting for the agent and is not counted.
_Avoid_: resolved item

**Held work**:
What an inbox item holds back: its own issue plus the open issues it blocks. Items are ordered by it.
_Avoid_: priority

**Waiting since**:
When the console first saw an inbox item, kept in its event log because the tracker cannot supply it.
_Avoid_: age

**Quiet project**:
A registered project with no open work and no live session. It renders as one line, and more than three of them fold into one group, "N quiet projects".
_Avoid_: dormant project, idle project

**Session**:
One running Claude Code process on this host, shown under the project of its working directory's main checkout, with one state: working, waiting for an answer, waiting for a permission, idle, or stopped on a usage limit (ADR-console-004).
_Avoid_: agent, terminal

**Outside sprints**:
The one quiet line of a project that counts its sessions working and waiting; opening it lists them. It raises no inbox item.
_Avoid_: ad-hoc work, side work

**Not yet managed**:
A repository with a live session that is not in the fleet registry; it is listed with its sessions and counts as no project. A session outside any repository is not listed.
_Avoid_: unregistered project, orphan
