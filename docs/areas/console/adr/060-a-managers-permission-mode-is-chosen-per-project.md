# ADR-console-060 — A manager's permission mode is chosen per project

- **Status:** accepted
- **Decided in:** #1151

## Context

ADR-console-021 left a manager's session on the owner's global `defaultMode`, `auto`, with every permission prompt refused. In `auto` the client's classifier still stops a manager at steps nobody watching can answer, so a sprint stalls in the project where nothing the manager runs could reach production unguarded. The guard (ADR-guard-011) already refuses what production rules forbid, so where a project declares no production, or its production rules are in the guard's policy, the mode `bypassPermissions` costs no safety the guard did not already hold. The owner's own sessions must keep `auto`.

## Decision

**D1. The rule.** The console writes `permissions.defaultMode` into a manager's settings file: `bypassPermissions` when the project's resolved contract declares `production.status` `none` (reason `no production`), or declares `declared` and the guard's compiled policy holds a row of that project whose `production` member holds the changing and read-only commands, key-file globs and MCP tools the resolved contract declares (reason `production rules in place`). Every other case is `auto`: `declared` with no such row, or a row older than the declaration (`production rules declared but not in the guard's policy`), `declared` with a policy that cannot be loaded (`the guard's policy cannot be read`), any other status (`no production rules declared`), a contract that does not resolve (`the project's contract does not resolve`) and a reader that raises (`the production rules could not be read`).

**D2. Written and re-read on every launch and wake.** The mode is read off the ingest lock before every launch and before every settings refresh of a wake (message, notice and revive), never reused from the launch. The file and the row of that attempt carry the same `Permission`: `manager.started` for a launch, `sprint.nudged`, `notice.nudged` or `manager.woken` for a wake, each with a `permission` member `{"mode", "reason"}`. It travels as a return value from the refresh to the record call of the same attempt, so no attempt's mode reaches another attempt's row, and a wake whose send fails still logs the mode it wrote. An attempt that writes no file (a relay) logs none.

**D3. The policy is validated as the guard validates it.** The console cannot import the standalone guard, so `permission.policy_rows` mirrors the guard's `load_compiled_policy` step for step, and a parity test runs both loaders over the same documents and compares their constants.

**D4. The view shows the newest logged mode.** The sprint fold keeps the permission of the newest `manager.started`, `manager.woken`, `sprint.nudged` or `notice.nudged` row that carries a valid one; a manager started by older code shows none.

**D5. The owner's global `defaultMode` stays `auto`.** The mode is set only in the manager's own settings file, which outranks user settings for that session.

**D6. Amended by #1228: bypass is not chosen until a bypass manager can be woken.** The console wakes a manager with a message from another local session, and the client holds every message from another session for a human's approval when the receiving session bypasses prompts, unless the sender also bypasses ([cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging.md)). The console's wakes come from a prompting session, so a manager in bypass went deaf after its first turn, with nobody at its terminal to approve the held messages. Until a bypass wake path is proved, `permission.read` never returns `bypassPermissions`: wherever D1 would choose it, for `no production` and for `production rules in place` alike, it returns `auto` with the reason `waking a bypass manager is not yet possible`. D1's rule that picks bypass, and every other reason, are unchanged, and the page's mode line shows the new reason as it shows any other. Removing this amendment, once a wake path into a bypass manager is proved, restores D1 as written.

## Consequences

- Until D6 is lifted no manager started by the console runs in bypass, whatever its project declares. The sprint fold still reads a `bypassPermissions` row an older console logged, and `bypass_proof` reports `refused` for the same reason.
- A project whose compiled row is missing, or whose policy file the guard drops (a refused derivation, a stale policy, a session before the switch), runs its manager in `auto`.
- A change to the guard's loader must be mirrored in `permission.policy_rows`, or the parity test fails.
- `bypassPermissions` relies on `skipDangerousModePermissionPrompt`, already set in the global settings, so a background session meets no acceptance dialog.
- The `PermissionRequest` refusal hook of ADR-console-021 stays for whatever still prompts.
