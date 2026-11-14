# ADR-console-026 — The owner removes an account from the page

- **Status:** accepted
- **Decided in:** #842, #1030

## Context

ADR-console-025 let the owner add an account from the page, but taking one away still meant `claude-account rm` in a terminal, which leaves the profile's stored login behind and leaves the console's pin, exclusion and sign-in item for a profile that no longer exists. #842 decided that the owner removes an account from the page too, as deliberately as the launcher's own `rm`: the name typed, the running sessions counted, the sign-out first. The launcher stays the one implementation of profile deletion (ADR-hosts-005), and the console stays the only thing that decides what a removal changes on the page.

## Decision

**D1. The action and the write.** Each capacity strip entry carries a Remove control. Its write is `POST /api/account-remove`, a member of `PAGE_WRITES` under the guard of ADR-console-008. It carries one `application/json` body of at most 4096 bytes, `{"profile": <string>, "typed": <string>}`; a body that is not that object is `400 bad removal`. A refusal on its merits is `409` with the reason, and the console refuses, in this order: `removing an account is not available on this host` (the console has no sign-out runner, account remover or sign-in reader), `the typed name does not match` (the typed name is not the profile's), `no such profile` (the profile is not among the profile directories now; `default` never is, and no name length is capped below the body limit), `a sign-in is running for <profile>; cancel it first`, and `<profile> is still being read; try again in a moment` (`busy`, D1b). A sign-in start for a profile being removed is refused `409` `<profile> is being removed` (`removing`, D1b). A refusal appends nothing and runs nothing. Success is an empty `204`.

**D1b. The removal in progress.** A removal marks its profile in the same block, under one lock, as the check that no sign-in runs for it. While the mark is set the console starts no probe of the profile, the choice of ADR-console-023 (the `chosen-profile` file, `GET /api/profile` and a manager launch's choice) never names it, a manager launch prepared under it is chosen again, and a sign-in start for it is refused. Before the sign-out the removal waits for a probe of the profile and a manager launch under it already in flight to end, for at most 15 seconds, and refuses `busy` when they do not. Every client run goes through `claude-account run`, whose profile sync recreates the directory once the profile has passed its existence check, so a run that overlaps the deletion could bring the profile back. The mark is dropped on every way out.

**D2. Sign-out first.** The console runs `claude-account run auth logout` with `CLAUDE_ACCOUNT=<profile>` in the environment of ADR-console-022 D1, in an empty temporary directory with no terminal, in its own process group, within 30 seconds. A sign-out that fails is followed by one reading of the profile's sign-in (ADR-console-022): only a signed-out reading lets the removal go on, with the outcome `removed_signed_out_already`; any other reading keeps the profile, appends the outcome `signout_failed` and answers `502` `the account was not removed: its sign-out failed: <kind>`.

**D3. One deletion.** The console runs `claude-account rm <name>` with no shell, a bound of 30 seconds and its output discarded. The console deletes nothing itself: the launcher's `rm` removes the profile directory and the bindings that name it. A launcher that fails, or a profile still listed after it, appends the outcome `remove_failed` and answers `502` `the account was signed out but not removed: <kind>`.

**D4. What follows.** On success the console reads its profile list again, so the profile leaves the capacity strip, its sign-in item and its probes, and it writes the choice again over the profiles that remain (`chosen-profile` and `GET /api/profile`). A manager launch prepared under the profile is chosen again. The profile's own pin and exclusion are lifted: the same append carries a `profile.exclusion` row (included) when it was excluded and a `profile.pin` row (unpinned) when it was pinned, before the removal row. The profile's older readings stay in the log under the retention of ADR-console-009.

**D5. What is stored.** A removal the owner confirms appends one `account.removal` row with exactly `by` (`owner`), `profile`, `outcome` (`removed`, `removed_signed_out_already`, `signout_failed` or `remove_failed`) and `kind` (null for `removed`, else the failure kind). The row is not kept past retention. A refusal appends none. No link, token or credential is in any row, stderr line or view, and stderr names an unexpected exception's type, never its message.

**D6. The page.** This amends ADR-console-002. Remove sits on each strip entry. It opens a confirmation that says how many sessions run under the profile and that they are not stopped, asks for the profile's name typed, and enables the removal only when the typed text is the name. The typed name is a draft whose text, selection and focus survive every frame. A failed removal shows its reason beside the control. The unprofiled `~/.claude` is not a listed profile, so it is never on the strip and never offers Remove.

**D7. Linux only.** The console removes an account only where it signs one out and runs the launcher, which is Linux. The macOS half is held on #894.

## Consequences

- An account is signed out and removed from the page, with no terminal, and the console is left with no pin, exclusion, strip entry or sign-in item for it.
- A session running under a removed profile keeps running. A later launch that names the profile explicitly (`CLAUDE_ACCOUNT=<name> claude`) is refused by the launcher, which checks that the profile exists before it syncs one, so the profile comes back only through Add account or `claude-account add`. A manager launch whose launcher had already returned before the removal began is a running session like any other. The launcher is not changed.
- The console runs a fourth and fifth kind of command beside the status reader, the sign-in run and the add: the sign-out and the removal.
- Related: ADR-console-008, ADR-console-022, ADR-console-023, ADR-console-025, ADR-hosts-005.
