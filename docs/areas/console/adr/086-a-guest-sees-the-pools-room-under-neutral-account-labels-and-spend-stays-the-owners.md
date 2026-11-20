# ADR-console-086 — A guest sees the pool's room under neutral account labels, and spend stays the owner's

- **Status:** accepted
- **Decided in:** #1341

## Context

ADR-console-066 D3 left accounts, capacity and spend to the owner, so a listed colleague could not tell how much room the pool had or why a sprint of his waited. The owner asked on 19 Nov to make the accounts' usage visible to colleagues. The capacity view names every profile, and a profile name or the address it is signed in to identifies a person or a company, so the figures cannot be shown as the owner sees them.

## Decision

**D1. What a guest sees.** The guest view carries a `pool` member beside the empty `capacity` and the null `spend`: one state (`fine`, `tight`, `out`, or none while no account in use has a reading) with the capacity view's own `tight`, `all_out`, `resumes_at` and `no_reading`, and one row per account under a label `Account <n>` with the state, the percent of the week and of the session left, when each window resets, the next reset, the end of an outage and whether the account is in use. Each running sprint of a listed project carries the label of the account its manager is on. A guest never receives a profile name, an address, an organisation or a proxy account id.

**D2. Spend stays the owner's.** The guest view's `spend` stays null. Money is the owner's bill, and a spend per account or per project would reveal work on projects the colleague is not listed for.

**D3. The numbering.** A number belongs to an account, not to a profile. An account is the counted profile of one address together with the profiles signed in to that address, or one profile with no address, so every profile of an account shares its label and the duplicates have no row of their own. An account keeps the smallest number any of its profiles held (preferring a profile that already had an address, so an account a new profile signs in to keeps its number), accounts with an address first and then by their smallest profile name, and each account without one takes the smallest positive integer nobody holds; a number no account kept is free again. An alias, a pin or a removal therefore never moves a label. A signed-out or excluded account stays a row, marked as not in use, and does not count toward the line. The numbering lives in `account-numbers.json` beside the event log, so a restart keeps it; an unreadable file numbers afresh.

## Considered options

- Numbers by name order on every read: removing an account renumbers every account after it.
- Numbers per profile: an alias that sorts first, or a pin, moves the account's label to another profile's number.
- Memory only: a restart renumbers after a removal.
- A label row in the event log: a new kind of row for a cosmetic number.
- Showing spend: reveals the work on projects the colleague is not listed for.

## Consequences

- Amends ADR-console-066 D3 (the guest page shows the pool and the account of each running sprint) and ADR-console-002's Guest page rule (the side column opens with the pool).
- Account controls, sign-in and Add account stay the owner's.
- The service numbers every profile before it publishes a guest view, so a row never lacks a number.
