# ADR-console-087 — A listed colleague may add his own account to the pool, and it stays his to remove

- **Status:** accepted
- **Decided in:** #1342

## Context

ADR-console-066 D3 keeps accounts and sign-in owner-only, so a guest never holds an account of the pool, and ADR-console-023 makes the console alone the chooser of the profile a new session runs on. On 19 Nov the owner decided that a listed colleague may add his own Claude account to the pool, and answered five design questions. This record keeps those answers, so the slices that build them have a decision to cite and a later reader can tell why a colleague's account behaves differently from the owner's. It changes no code.

## Decision

**D1. Whose sprints run on a colleague's account.** His own sprints first; anyone's sprints when it has room. This amends ADR-console-023 D1: among the profiles with room, a colleague's own account is the choice for a sprint that colleague started, and any other sprint may use it only when it has room under the rule there.

**D2. Consent.** Before Sign in, the guest page shows one plain sentence saying the credential is kept on the owner's host under the owner's user, so any process of the owner can use it. Sign in stays disabled until he ticks that he agrees.

**D3. Who may sign it out or remove it.** The colleague, for his own account only, and the owner. The owner may also exclude it from the pool (ADR-console-023 D1); the colleague may not.

**D4. How the pages show whose it is.** The guest page labels the account `yours` for its owner and `Account n` for everyone else (ADR-console-086 D3). The owner's page shows the colleague's login beside the row.

**D5. Removal.** At once. Each manager running on the account restarts on the pool's choice (ADR-console-023 D1).

**D6. Spend stays the owner's.** A colleague's account changes nothing in ADR-console-086 D2: money is the owner's bill, and a spend per account or per project would reveal work on projects the colleague is not listed for. The guest view's `spend` stays null, whoever holds the account.

## Considered options

- Only the colleague's own sprints on his account: leaves room unused while the owner's sprints wait.
- Any sprint first on a colleague's account: spends a colleague's allowance before his own work needs it.
- No consent sentence: the colleague would not learn that any process of the owner can use the credential.
- Showing the colleague his account's spend: the same figure per account would reveal work on projects he is not listed for.

## Consequences

- Amends ADR-console-066 D3 (a guest may add and remove his own account) and ADR-console-023 D1 (whose sprints a profile serves).
- The account and its credential are still the owner's host's: ADR-console-066 D1's trust boundary is unchanged, and the consent in D2 is that boundary stated to the colleague.
- Related: ADR-console-086.
