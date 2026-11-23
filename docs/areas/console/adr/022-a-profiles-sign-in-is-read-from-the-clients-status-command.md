# ADR-console-022 — A profile's sign-in is read from the client's status command

Context: a lapsed or missing login showed nowhere on the page. Decision: the console asks the client itself, `claude-account run auth status --json` per profile, beside each probe. It runs with the proxy off and no inherited key, and stores one row per change of state, end or account. A signed-out profile has no room, and an unknown status raises nothing. Rejected: reading the client's credential file.
