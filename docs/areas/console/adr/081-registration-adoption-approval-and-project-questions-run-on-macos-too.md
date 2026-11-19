# ADR-console-081 — Registration, adoption approval and project questions run on macOS too

- **Status:** accepted
- **Decided in:** #1330

## Context

eleven-m5, a Mac, is the only console host, and ADR-console-028 D9, ADR-console-058 D2 and ADR-console-075 D1 kept registration, adoption approval and project questions Linux only, so the page answered 409 on the one host that runs the console.

## Decision

**D1. Where they run.** Registering a project, its plan answers and Register card, approving an adoption (apply, push, pull request), registering a merged adoption and project questions run on Linux and macOS, the platforms `manager.supported` admits, and nowhere else. Any other platform keeps the not-available refusals.

**D2. The children.** Each child is started by `manager.run_in_own_group` in its own session with the same argv on both platforms, and the console's stop ends each one's group, except a fast-forward merge already started, which the stop lets finish (ADR-console-070 D7). None of them ever used a systemd scope, and none needs `systemd-run`, `systemctl` or `/proc`.

## Consequences

- Amends ADR-console-028 D9, ADR-console-058 D2 and the sentence of ADR-console-075 D1 that kept these Linux only.
- The evidence is the `console-register` check on eleven-m5 with a throwaway repository.
