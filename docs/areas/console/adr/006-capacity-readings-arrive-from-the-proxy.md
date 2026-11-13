# ADR-console-006 — Capacity readings arrive from the proxy and are kept per profile

- **Status:** accepted
- **Decided in:** #839, #849, #860, #895, #1009, #1010, #1016

## Context

The owner needs to see from the page how much of each account's capacity is left and when it comes back, and to know when every account is out. The cache proxy sees the unified rate-limit headers of every response (ADR-hosts-007), so the console takes its readings from the proxy and reads no credential file. A profile with no live session, or whose first request is refused, was never credited a reading, so idle and exhausted profiles stayed "no reading yet" (#1009).

## Decision

`POST /api/readings` is the second write route. It narrows ADR-console-004's "`POST /api/hooks` is the one write route": it has the same refusals (a request carrying an `Origin` header and one whose body is not JSON), answers an empty `204`, and appends only `capacity.reading` and `capacity.stop` events.

A reading is attributed to a profile through the console's own probes first (below), then through the session the registry places under that profile (the registry directory names it), else through the last folded account-to-profile pair. No credential file is read. The last reading per profile is kept; a passed reset reads as reset and unused, a window without its own reset takes the reading's top-level reset, and a refusal that lost its top-level reset ends at the reset of the window it names.

**Readings the console asks for (#1009).** On Linux, every 10 minutes and once 30 seconds after it starts, the console sends one small request under each listed profile, `claude-account run -p --session-id <id> --no-session-persistence --strict-mcp-config --model haiku --max-turns 1 <prompt>` with `CLAUDE_ACCOUNT=<profile>` and `CLAUDE_CACHE_PROXY=required`, no terminal, in an empty temporary directory, so the profile's own login signs it, it goes through the cache proxy and it leaves no transcript. While the proxy does not answer the launcher refuses the probe instead of sending it direct (ADR-hosts-004), so a probe never spends a request that yields no reading. A probe that outlives its 120 s timeout has its whole process group killed, the Claude child the launcher waits on included, before its profile may be probed again. The console never reads, stores or logs a credential. The console picks the session id (a new UUID) before starting the client and remembers the profile under it for the last 256 probes; a reading whose session is one of them is credited to that profile before any other rule, a refusal (HTTP 429) included, which leaves the profile out with its reset. Hooks and registry entries of a probe session are dropped, so a probe is never a session on the page (ADR-console-004). One probe per profile is in flight; one that fails or times out is one stderr line naming its profile and its kind, and the profile keeps its last reading. The proxy's forwarding is unchanged and nothing is added to the request stream (ADR-hosts-007). Off Linux no probe is made, as no manager is started (ADR-console-015).

The listed profiles are the accounts: every directory under `profiles/` whose name is an account name (`a-z`, `0-9`, `-`, `_`, never `default`), used or not, and no others. The unprofiled client directory (`~/.claude`, whose sessions are named `default`) is not an account: it is never listed, probed or read for sign-in and raises no sign-in item, while a session run from it is still shown in its project and readings stored for it stay in the log unshown (#1016). A profile with no reading counts in one note on the strip, "<n> with no reading yet", and keeps "every profile is out" from firing, while a profile whose sign-in reads signed out is listed as signed out, is not in the note and does not block "every profile is out" (ADR-console-022), and one removed with `claude-account rm` drops out of the strip and the count at the next poll while its readings stay in the log. The capacity strip sits in the top bar. When every profile is out the statement says so and when everything resumes, and nothing is asked of the owner. "Tight" is one profile with room among two or more while every other profile reads out.

## Consequences

- On Linux a listed profile whose login works shows a reading within one interval of the console's start, idle or exhausted; one never read (a probe that keeps failing) still counts in "no reading yet", and while one does, no "every profile is out" statement is made.
- A session the registry does not place under a profile is attributed only by an account already paired with one, unless it is a console probe, whose reading is credited to the profile the console sent it under.
- Each listed profile costs one small request every 10 minutes.
- The probe relies on the client putting the `--session-id` it was given in the request's `metadata.user_id`, which the cache proxy reports (`agent_tools.hosts.rate_limits.identity`).
- The log grows by one row per reading and per stop.
