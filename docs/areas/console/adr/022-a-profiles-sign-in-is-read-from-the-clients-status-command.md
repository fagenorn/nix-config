# ADR-console-022 — A profile's sign-in is read from the client's status command

- **Status:** accepted
- **Decided in:** #839, #842, #1010

## Context

A profile's login can end, or never have been made, and nothing on the page said so: a profile with no reading looked like an idle one (ADR-console-006), and the owner learned a login had lapsed only when a manager failed to start. The client answers "am I signed in, and until when" itself, so the console asks the client and reads no credential file.

## Decision

**D1. The command.** On Linux the console runs `claude-account run auth status --json` with `CLAUDE_ACCOUNT=<profile>`, in an empty temporary directory with no terminal, in its own process group, within 30 seconds. The client prints one JSON object and exits 0 when signed in and 1 when not. Exit 0 with `loggedIn` true is signed in, and its end is `loginExpiresAt` (an ISO 8601 time; absent or null is signed in with no known end); exit 1 with `loggedIn` false is signed out; anything else is unknown. The command sends no model request, so it runs with `CLAUDE_CACHE_PROXY=0` and without an inherited base URL, key or token: a down cache proxy must not make the state unknown, and an inherited key must not stand in for the profile's own sign-in.

**D2. What is stored.** One `signin.reading` row per change, with exactly the profile, the state (`signed_in`, `signed_out` or `unknown`) and the end (`ends_at`, an ISO time with an offset, null unless signed in). The address, organisation and plan the client also prints are dropped. A row is appended only when the state or the end differs from the folded one.

**D3. The schedule.** The reading is made inside each probe job of ADR-console-006, before the probe, under the same in-flight mark, stop event and schedule: 30 seconds after the console starts, then every 10 minutes. A service with a reader and no prober still runs the schedule.

**D4. The ask.** A profile asks the owner when it is signed out, or signed in with a known end three days or less away (an end that has passed included). It is one inbox item, `signin/<profile>`, whose command is `CLAUDE_ACCOUNT=<profile> claude`, placed after the progress items and before the questions (briefs, stalls, progress, sign-in, questions, tracker items), counted in the statement and its headline. A fresh sign-in ends more than three days ahead and closes it.

**D5. Unknown raises nothing.** A status that fails, times out, exits otherwise or cannot be read records `unknown`, one stderr line `console: signin_unknown <profile> <kind>` and nothing else: the last answer wins, so an unknown sign-in closes an open ask and asks none.

**D6. Signed out is not "no reading".** In the shown capacity a signed-out profile is named as signed out, is left out of the no-reading note, and does not block "every profile is out": it has no room and is not waiting for a reading. Tight and all out are decided over the profiles that are not signed out. The launch choice and the quota wait do not change: the manager's launch choice keeps ADR-console-015's profile rule over the capacity without sign-ins, so a signed-out profile with no reading is still an unknown profile there. Skipping signed-out profiles at launch is a later change.

**D7. Reading, not credentials.** The console opens no credential file and starts no client but the launcher; the client's own login answers.

## Consequences

- A lapsed or never-made login shows within one interval, with the command to fix it, and three days before an end it asks before anything fails.
- A signed-out profile with an old capacity reading shows as signed out and no longer counts toward "every profile is out" in the shown capacity, while the launch can still pick it (ADR-console-015) until the launch learns to skip it.
- Each listed profile costs one status command every 10 minutes, with no request to the model.
- The log grows by one row per change of state or end.
- Related: ADR-console-006 (the probe schedule and the listed profiles), ADR-console-015 (the profile rule).
