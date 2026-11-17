# ADR-console-057 — Session output and a running check move a sprint

- **Status:** accepted
- **Decided in:** #1185

## Context

ADR-console-042 gave a running sprint one movement reading, and ADR-console-050 added three signals read from the forge and the checkout. All of them are things a delivery leaves behind at a step boundary. A sprint whose work is a long run inside one step, a review round of subagents or a test run that takes ten minutes, writes no journal row, makes no commit and opens no pull request for longer than the fifteen-minute window of ADR-console-005, so it read "quiet for N min, may be stuck" while it was working. The only evidence the console had was the state of a session, and a session that is not `working` can still be running a check in its terminal. This decision adds two signals from the host itself, a session's output and a running check, and keeps the rest of ADR-console-042 and ADR-console-050 as they are.

## Decision

**D1. Session output.** A session's output is the newest write among its transcript files: `<projects>/<slug>/<session_id>.jsonl` and every `.jsonl` anywhere under `<projects>/<slug>/<session_id>/`, over every slug directory of every projects directory. The subtree is included because a delivery's review round writes its workflow agents' transcripts (under `subagents/workflows/`) and its subagents' transcripts, not the session's own file. An absent or unreadable path is skipped. The newest write seen never moves back.

**D2. A running check.** A running check is CPU used by a process under a sprint's session, read from `/proc`. Only descendants of the session's pid count, never the session process itself, because an idle background session burns CPU of its own. The CPU of a process is utime, stime, cutime and cstime, a process is keyed by its pid and its start time, and a process new since the last reading counts all of its CPU. The check moves the sprint when the CPU used between two readings is at least one second (`CHECK_CPU_MS`), so a watcher loop idling at a few milliseconds per poll does not read as a running check. The first reading of a session moves nothing, because there is nothing to compare it with. With no `/proc` there is no signal and the reading is as before.

**D3. Which sessions are a sprint's.** A listed session belongs to a running sprint when it carries the sprint's manager name, is its `manager_session`, or runs a delivery of one of the issues of its report or of the report's inbox, the set of ADR-console-042 D3 and ADR-console-050 D2. The times are kept per association of a session with a sprint. A reading refreshes only the associations it carries, so a session that finished one sprint's delivery and moved to another refreshes only its new sprint, and the sprint it left ages into quiet.

**D4. No new sentence.** The two signals join the base reading, not the wait signals of ADR-console-050. A sprint that session output or a running check moves shows its stage phrase and never a wait sentence, so ADR-console-050 D3 is unchanged.

**D5. Last-seen times.** Like ADR-console-050 D1 and D5, the times are the last seen, never refreshed once a session leaves its association, and live in memory only: a restart loses them and reads at once. The reading runs in the movement poll every two minutes, for a project with at least one such session. A session reader that raises prints `console: movement_sessions_failed <project_id> <Type>: <message>` on stderr, and the project merges with no session reading while the forge and local halves are unaffected.

**D6. A reply to the nudge is not movement.** ADR-console-020 sends an idle manager a nudge, and the manager's reply writes its transcript and may run commands. Output or CPU of a manager session within `NUDGE_REPLY_MS` (five minutes) after the sprint's last idle nudge moves nothing, so a nudged idle manager still reads as may be stuck and the console's own send is not read as a sign of life. A delivery session's output in that window still counts, and while the reply runs the manager reads working, which already moves the sprint. The fold applies this window as it reads, so a reply never replaces the last qualifying time and earlier movement keeps the sprint moving; the view applies it again to what it is given.

**D7. The sprint entry's `movement` member.** A sprint entry carries `movement`: its session associations, each with `session_id`, `manager` and `read_at` (the start of the last completed read of that association), the sprint's `nudged_at` and its `base_at`, the newest of the sprint's own older signals. The host check reads it so that it judges a sprint only on output a completed read could have seen: a write after `read_at` is not yet read, so it is "not yet" and never "not met".

## Consequences

- A sprint whose manager or delivery is writing or running a check stays moving for the window after the last write or reading, and its line gives its stage phrase.
- A background watcher at near-zero CPU, an idle session's own process and a manager's reply to a nudge keep nothing alive.
- A session's output moves its sprint at most two minutes late, the poll's period, and a write after the last read counts only from the next one.
- The cost is one transcript-tree walk per sprint session and one `/proc` scan per project per poll, with no write and no lock beyond the ingest lock's brief reads.
- ADR-console-042 stays in force; its status line names this decision, and its D2 is read with D1 above.
- Related: ADR-console-005, ADR-console-020, ADR-console-042, ADR-console-050.
