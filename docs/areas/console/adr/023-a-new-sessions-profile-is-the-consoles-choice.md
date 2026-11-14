# ADR-console-023 — A new session's profile is the console's choice, on a route and in a file

- **Status:** accepted
- **Decided in:** #839, #842, #1011, #1016, #1028, #1029

## Context

#839 (item 4) decided that a new session runs under the profile with the most weekly headroom, ties broken on five-hour headroom, and that the per-project binding is no longer consulted. #842 decided that the launcher asks the console for that profile with a short deadline, that the console writes its choice to a file whenever it changes, and that with no file the launcher uses the most recently used signed-in profile. Until now only the console's manager launch used the choice (ADR-console-015), and with no reading it fell back to the project's binding in `bindings.tsv`.

## Decision

**D1. The rule.** A profile has room when its capacity reads ok or reset, unless it is signed out (ADR-console-022): a signed-out profile has no room. An excluded profile has no room either and is never the choice, in the room rule or in the most-recently-used fallback, so with every other profile out the manager waits and with none signed in nothing is chosen (#1028). The owner excludes and includes a profile on the page through `POST /api/exclusion`, a page write under ADR-console-008, which appends one `profile.exclusion` row; the exclusion is the folded state of those rows, rebuilt from the log at a restart, and the retention pass keeps a profile's newest row while it says excluded. An excluded profile's allowance and sign-in are still read, and the capacity strip shows it marked excluded. The owner pins one profile at a time on the page through `POST /api/pin`, a page write under ADR-console-008, which appends one `profile.pin` row; the pin is the folded state of those rows, rebuilt from the log at a restart, and the retention pass keeps the newest row while a pin is in force. A pinned profile with room (the room above) is the choice, whatever the others' allowance; with no room the pin is not in effect, the choice follows the rule above, the pin stays set and applies again once the profile has room (the owner's answer of 2026-11-13), and the page says the pin is not in effect, why and which profile is used instead. Pinning an excluded profile is refused (include it first) and the pinned profile cannot be excluded (unpin it first). `CLAUDE_ACCOUNT=<profile> claude` still overrides one launch (ADR-hosts-008). Per-project pins are not built. Among the profiles with room the choice is the one with the most weekly allowance left, then the most five-hour allowance left, then the smallest name. With no profile known to have room, the choice is the most recently used signed-in profile, its use being the latest log row of any of its sessions; that use is kept after the session leaves and is rebuilt from the log when the console restarts, the retention pass leaving the assignment row a retained row of the session needs. When no listed profile has room and none is signed in, nothing is chosen. The unprofiled client directory is not a listed profile (ADR-console-006), so it is never chosen, and a host with no named profile has nothing to choose (#1016).

**D2. The route.** `GET /api/profile` answers `{"profile":"<name>"}`, and `{"profile":null}` when nothing is chosen. It sits behind the loopback check and takes no token, because it changes nothing (ADR-console-008 governs only the page's writes).

**D3. The file.** The file `chosen-profile` in the accounts directory holds the choice. It is written atomically and only when the choice changes, and it is removed when nothing is chosen. The choice is checked at every session poll and at every route answer.

**D4. The manager launch.** The manager launch uses the same choice. When every profile that is not signed out is out, it still waits until the earliest reset (ADR-console-015, ADR-console-020), and when nothing is chosen it waits with no resume time. The console does not read the binding.

## Consequences

- The launcher, in the next slice, can ask the route or read the file.
- A signed-out profile is never chosen, which amends ADR-console-022 D6.
- A profile with an unknown sign-in can still be chosen when it has the most room.
- With no file the launcher applies its own fallback.
- Exclusions (#1028) and the one pin (#1029) are inputs to the choice; per-project pins are not built.
- The Hosts binding stays until the launcher stops reading it.
- Related: ADR-console-015 (the profile rule), ADR-console-020 (the quota wait), ADR-console-022 (the sign-in reading).
