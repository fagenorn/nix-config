# ADR-console-003 — Sessions arrive by hooks and a five-second registry poll

- **Status:** accepted
- **Decided in:** #829, #837, #838, #857

## Context

The owner needs to see from the page whether a session waits for them. Claude Code hooks fire at once, but an interrupt raises none, and SessionStart takes no HTTP hook (#829). Neither source alone tells the console which sessions are running now.

## Decision

The generated settings carry five HTTP hooks (Stop, StopFailure, PermissionRequest, Notification and SessionEnd) that post their input to the console, one command hook for SessionStart, and the `allowedHttpHookUrls` entry that lets the HTTP hooks reach the console. The SessionStart hook is a dash-and-curl script, `home/common/claude-code/console-session-start.sh`, not a Python command: a Python start alone exceeds the 10 ms a hook may add (#838 item 6), and a console that is down must cost a session nothing.

`POST /api/hooks` is the one write route. It narrows ADR-console-001's "no endpoint changes anything": it appends session observations to the log and nothing else. It answers an empty `204` before it appends, so it never decides a permission or a stop. It refuses a request carrying an `Origin` header and one whose body is not JSON. It carries no token because it answers nothing; a write that answers a session needs the token and origin check of #838 item 7.

Every five seconds the console also polls the session registry files under `~/.claude/sessions` and under every account profile, and appends a `session.seen` event when a reading differs from what the log already folds to. Hooks give the transitions: SessionStart and Stop give idle, StopFailure gives a usage-limit stop for `rate_limit` and idle otherwise, PermissionRequest gives waiting for an answer for the `AskUserQuestion` tool and waiting for a permission otherwise, a Notification keeps or sets a waiting state or gives idle, and SessionEnd ends the session. The registry gives the statuses: `busy` is working, `idle` is idle, `waiting` is waiting for a permission when `waitingFor` is `permission prompt` and waiting for an answer otherwise. Any other status says nothing, and an idle reading never clears a usage-limit stop.

A session leaves on SessionEnd, or when two consecutive polls do not find it. A registry file counts only while its pid runs the process it names: on Linux `pidDomain` must equal the console's own and `procStart` must equal field 22 of `/proc/<pid>/stat`. A registry reading never overrides a newer hook. A poll reads the registry and applies it under the lock hooks are ingested under, so neither sees a half-applied state.

A session belongs to the project of its working directory's main checkout, which for a linked worktree is the checkout that owns it. A session outside any git repository is not shown. Unknown fields, events, kinds and statuses are ignored. A session waiting in its terminal is not an inbox item: it is answered there, and #837 item 4 keeps it to the project's one quiet "outside sprints" line.

## Consequences

- A session started under a config directory the console does not read shows only until two polls miss it.
- On darwin the pid is checked only for existence, so a reused pid can show a stale session until its registry file goes.
- A console in another pid namespace than the sessions sees none of them from the registry.
- Another HTTP hook added at any settings level now needs its own allow-list entry.
- The registry is undocumented and may change shape; that degrades to ignored fields, not to a failure.
- The log grows by one row per hook and per changed poll observation.
