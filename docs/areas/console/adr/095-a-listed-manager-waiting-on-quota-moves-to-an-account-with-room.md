# ADR-console-095 — A listed manager waiting on quota moves to an account with room

- **Status:** accepted
- **Decided in:** #1378

## Context

ADR-console-020 holds every send while a manager's account is out, and the sprint reads `waiting on quota until <reset>`. #1278 and #1279 move only a gone manager, so a listed manager waited for hours while another account had room: on 20 Nov four of five managers waited this way and a release was about 4.5 hours late. `continue` and `retry-manager` both refuse such a sprint, so the owner had no way to push it on.

## Decision

**D1. Which account.** The account is chosen by the rule of a gone manager's move (#1278, the owner's choice): the profile a new session would get, kept only while it is another account that has room.

**D2. Who qualifies.** A manager qualifies when all of these hold: the console has a stopper; the manager is started and listed idle or at its limit (never working); its sprint is open with work, not stalled, with no open no-progress item; fewer than three bring-backs are counted in the hour (ADR-console-017); its account is out; and no move of it was cancelled.

**D3. How it moves.** One job stops the session and starts a takeover. The takeover reads the sprint's contract, recap and inbox as any takeover does. Just before the stop it checks again that the move holds, that no session of the manager works and that the listed one is on the profile the sprint records. It starts only when the listing read after the stop shows neither the manager nor a session it stopped, no other session carries its name, and the #1279 checks still hold, and it checks the same once more after the permission read. Both listings are conclusive: a registry file that cannot be read fails the move. Any failure starts nothing, writes no row and moves nothing again until the account has room; a session that was stopped is woken after the reset.

**D4. What is recorded and said.** The start row carries `moved`. The digest says `<title> moved to another account` once, in place of the takeover sentence, and the new manager's first send does not say the sprint resumed after the quota reset.

**D5. No account with room.** Nothing is stopped and the sprint reads waiting on quota as before.

## Consequences

- A move costs one stopped session and one new session that starts from the sprint's records, not the old conversation.
- A manager in the middle of work is not stopped.
- A move counts against the bring-back limit.
- Without a stopper (a platform the console cannot stop a session on) the sprint waits as before.
- Amends ADR-console-020.
- Related: ADR-console-017, ADR-console-023, ADR-console-087.
