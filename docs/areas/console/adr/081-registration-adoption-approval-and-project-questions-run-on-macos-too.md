# ADR-console-081 — Registration, adoption approval and project questions run on macOS too

- **Status:** accepted
- **Decided in:** #1330

## Context

eleven-m5, a Mac, is the only console host, and ADR-console-028 D9, ADR-console-058 D2 and ADR-console-075 D1 kept registration, adoption approval and project questions Linux only, so the page answered 409 on the one host that runs the console.

## Decision

**D1. Where they run.** Registering a project, its plan answers and Register card, approving an adoption (apply, push, pull request), registering a merged adoption and project questions run on Linux and macOS, the platforms `manager.supported` admits, and nowhere else. Any other platform keeps the not-available refusals.

**D2. The children.** Each child is started by `manager.run_in_own_group` in its own session with the same argv on both platforms, and the console's stop ends each one's group, except a fast-forward merge already started, which the stop lets finish (ADR-console-070 D7). None of them ever used a systemd scope, and none needs `systemd-run`, `systemctl` or `/proc`.

**D3. The console drains them as it closes.** On macOS the console's launchd job leaves process groups alone (ADR-console-075 D3), so a child in its own session would outlive the console. `close` sets the stop first, which ends each running child's group and admits no new run (a request then is refused: the console is stopping); it then waits for every accepted run that can start an adoption child to end (a registration, a confirmed or answer run, the discard of a cancel, an approval, a merged-registration retry), including a fast-forward merge already started, which the stop lets finish (ADR-console-070 D7). A run that ends after close began writes no ended row, as before. Manager launches are not waited for. On Linux the unit's control-group kill ends the same children.

## Consequences

- Amends ADR-console-028 D9, ADR-console-058 D2 and the sentence of ADR-console-075 D1 that kept these Linux only.
- The evidence is the `console-register` check on eleven-m5 with a throwaway repository.
