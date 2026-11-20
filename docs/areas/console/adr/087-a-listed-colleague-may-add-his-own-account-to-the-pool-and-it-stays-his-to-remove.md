# ADR-console-087 — A listed colleague may add his own account to the pool, and it stays his to remove

- **Status:** accepted
- **Decided in:** #1342

## Context

ADR-console-066 D3 keeps accounts and sign-in owner-only, so a guest never holds an account of the pool, and ADR-console-023 makes the console alone the chooser of the profile a new session runs on. On 19 Nov the owner decided that a listed colleague may add his own Claude account to the pool, and answered five design questions. This record keeps those answers so the slices that build them have a decision to cite; it changes no code.

## Decision

**D1. Whose sprints run on a colleague's account.** His own sprints first; anyone's sprints when it has room. This amends ADR-console-023 D1: among the profiles with room, a colleague's own account is the choice for a sprint that colleague started, and any other sprint may use it only when it has room under the rule there. The owner's pin (ADR-console-023 D1) outranks this preference: a pinned profile with room is the choice for every sprint, a colleague's own included, and his own account is preferred only among the profiles left when no pin is in effect. This record adds no other precedence over ADR-console-023 D1.

**D2. Consent.** Before Sign in, the guest page shows one plain sentence saying the credential is kept on the owner's host under the owner's user, so any process of the owner can use it. Sign in stays disabled until he ticks that he agrees.

**D3. Who may sign it out or remove it.** The colleague, for his own account only, and the owner. The owner may also exclude it from the pool (ADR-console-023 D1); the colleague may not.

**D4. How the pages show whose it is.** The guest page labels the account `yours` for its owner and `Account n` for everyone else (ADR-console-086 D3). The owner's page shows the colleague's login beside the row.

**D5. Removal.** At once. This is an exception to ADR-console-026 (D6 and its Consequences), which lets a session under a removed profile keep running, and it covers only a colleague's account removed by its colleague or the owner: each manager running on that account restarts on the pool's choice (ADR-console-023 D1), and when no profile has room or none is signed in, that manager waits as ADR-console-023 D4 says, with the earliest reset or with no resume time. Any other session on the account keeps running, and removing the owner's own account is unchanged.

**D6. Spend stays the owner's.** A colleague's account changes nothing in ADR-console-086 D2: money is the owner's bill, and a spend per account or per project would reveal work on projects the colleague is not listed for. The guest view's `spend` stays null, whoever holds the account.

## Considered options

- Only the colleague's own sprints on his account: leaves room unused while the owner's sprints wait.
- Any sprint first on a colleague's account: spends a colleague's allowance before his own work needs it.
- No consent sentence: the colleague would not learn that any process of the owner can use the credential.
- Showing the colleague his account's spend: the same figure per account would reveal work on projects he is not listed for.

## Consequences

- Amends ADR-console-066 D3 (a guest may add and remove his own account) and ADR-console-023 D1 (whose sprints a profile serves).
- The account and its credential are still the owner's host's. The trust boundary is the one ADR-console-077 D3 restates for the shared Mac, which replaced ADR-console-066 D1's loopback argument: the owner's processes can use the credential and other local users cannot reach the console, and the consent in D2 states that to the colleague.
- Built in #1343: the console chooses the `colleague-<n>` name itself, and the `account.added` row carries the colleague's login as `by`, which ends on a completed removal of the profile and is retained past the usual retention. Three guest account writes, `POST /api/guest-account`, `/api/guest-signin-code` and `/api/guest-signin-cancel`, each act on his own profile only. The add carries consent as `true` on the wire (`{"consent": true}`) and the console picks the profile: his own live sign-in, else one of his profiles that is not signed in, else a new one. The ownership row is appended before the launcher creates the profile, so an add that stops once the directory exists leaves it his and his retry reuses that name, and a revocation never leaves a profile that is no one's. The code and the cancel carry the attempt the add answered and act on that attempt only, so a stale tab cannot stop a newer sign-in. The answer carries the attempt, the link and the route, without `port` and `forward`, and with no link for a loopback-only run.
- Related: ADR-console-086.
