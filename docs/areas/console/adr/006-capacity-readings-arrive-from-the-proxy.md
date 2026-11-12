# ADR-console-006 — Capacity readings arrive from the proxy and are kept per profile

- **Status:** accepted
- **Decided in:** #839, #849, #860, #895

## Context

The owner needs to see from the page how much of each account's capacity is left and when it comes back, and to know when every account is out. The cache proxy sees the unified rate-limit headers of every response (ADR-hosts-007), so the console takes its readings from the proxy and reads no credential file.

## Decision

`POST /api/readings` is the second write route. It narrows ADR-console-004's "`POST /api/hooks` is the one write route": it has the same refusals (a request carrying an `Origin` header and one whose body is not JSON), answers an empty `204`, and appends only `capacity.reading` and `capacity.stop` events.

A reading is attributed to a profile through the session the registry places under that profile (the registry directory names it), else through the last folded account-to-profile pair. No credential file is read. The last reading per profile is kept; a passed reset reads as reset and unused, a window without its own reset takes the reading's top-level reset, and a refusal that lost its top-level reset ends at the reset of the window it names.

The listed profiles are `default` plus every directory under `profiles/`, used or not, and no others: a profile with no reading counts in one note on the strip, "<n> with no reading yet", and keeps "every profile is out" from firing, and one removed with `claude-account rm` drops out of the strip and the count at the next poll while its readings stay in the log. The capacity strip sits in the top bar. When every profile is out the statement says so and when everything resumes, and nothing is asked of the owner. "Tight" is one profile with room among two or more while every other profile reads out.

## Consequences

- A profile that has made no request since the console began shows "no reading yet", and while one does, no "every profile is out" statement is made.
- A session the registry does not place under a profile is attributed only by an account already paired with one.
- The log grows by one row per reading and per stop.
