# ADR-console-025 — The owner adds an account from the page

- **Status:** accepted
- **Decided in:** #842, #1027

## Context

ADR-console-024 let the owner sign a profile in from the page, but a profile has to exist first, and the only way to make one was `claude-account add` in a terminal. #842 decided that the owner adds an account from the page too: the console creates the profile through the launcher and goes straight into its sign-in, so a new account is one name typed and one link followed. The launcher stays the one implementation of profile creation (ADR-hosts-005), and the reading of ADR-console-022 stays the only thing that says whether a profile is signed in.

## Decision

**D1. The action and the write.** The page's header carries an Add account control. Its write is `POST /api/account-add`, a member of `PAGE_WRITES` under the guard of ADR-console-008. It carries one `application/json` body of at most 4096 bytes, `{"name": <string>}`; a body that is not that object is `400 bad account`. A refusal on its merits is `409` with the reason (D2, and `adding an account is not available on this host` when the console has no account adder, sign-in runs or sign-in reader). Success is `200` with `{"attempt": <int>, "link": <string> | null, "profile": <name>}`.

**D2. The name.** The rule is the launcher's: `a-z`, `0-9`, `-` and `_`, at least one character. The name `default` is refused, and so is a name that already has a profile. The `409` reasons are `not an account name: use a-z, 0-9, - and _`, `default is not an account name`, `account <name> already exists` and `adding an account is not available on this host`. The page and the console give the same reason texts, and a name the console passes is a name the launcher creates.

**D3. One creation.** The console runs `claude-account add <name>` with no shell, a bound of 30 seconds and its output discarded; it makes no directory and no link itself. The profile is what ADR-hosts-005 makes: links to `~/.claude/<entry>`, a `.claude.json` copied without the login, and mode 0700. A launcher that fails is `502` `the account could not be created: <kind>` and appends nothing.

**D4. Straight into the sign-in.** The console refreshes its profile list, so the new profile is listed at once. It reads the profile's sign-in once with the reader of ADR-console-022, under the ticket rule of ADR-console-024 D6, so a signed-out reading opens the profile's sign-in item. Then the start of ADR-console-024 D1 runs, and its link is in the add's answer. This amends ADR-console-024 D3: the link appears in the start answer and the add answer, and in no other. A failed read records nothing and invents no status: the profile stays `unknown`, no item opens, and the page's Add account control itself carries the link, the code field and Cancel (posting the existing ADR-console-024 code and cancel writes) until the item appears or the run ends. A start that fails keeps the profile, with `502` `the account was added; its sign-in could not start: <kind>`. An unfinished sign-in leaves the profile signed out with its item and its Sign in action.

**D5. What is stored.** An added profile appends one `account.added` row with exactly `by` (`owner`) and `profile`; the kind is not kept past retention, and the view's `accounts_added` is folded from the retained rows. A refusal and a failed creation append none. No link is in any row, stderr line, view or stream frame.

**D6. The page.** This amends ADR-console-002. The Add account control sits in the header. The account name is a fourth typed thing and its draft, selection and focus survive every frame. A link held from an add that waits for its item is kept in memory like the sign-in link of ADR-console-024 D3, and while no sign-in item shows the added profile the control carries its sign-in continuation: the link, the code field and Cancel. An add that answers with no link still holds its attempt, and the continuation then offers Get sign-in link (the start write again, which joins the live run) and Cancel until a link arrives or the run ends. When the profile's sign-in item appears, the card takes over the typed code, its selection and its focus.

**D7. Linux only.** The console adds an account only where it starts a sign-in, which is Linux. The macOS half is held on #894.

## Consequences

- A new account is made and signed in from the page, with no terminal.
- A profile added from the page is the same as one added in a terminal, because the console creates it only by running the launcher.
- The console runs a third kind of command beside the status reader and the sign-in run, and it stays under the secrecy of D5.
- Related: ADR-console-002 (the page rules), ADR-console-008 (the page writes), ADR-console-022 (the sign-in reading), ADR-console-024 (the sign-in from the page), ADR-hosts-005 (the account profiles).
