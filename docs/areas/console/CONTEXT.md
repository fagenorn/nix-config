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
Anything waiting on the owner, whatever its source. The console's statement counts the open ones, "N things need you"; with none and a readable tracker it reads "Nothing needs you".
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
A registered project with no open work. It renders as one line, and more than three of them fold into one group, "N quiet projects".
_Avoid_: dormant project, idle project
