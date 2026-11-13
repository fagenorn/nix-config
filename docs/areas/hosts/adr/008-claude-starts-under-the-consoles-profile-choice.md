# ADR-hosts-008 — `claude` starts under the console's profile choice, not the project's binding

- **Status:** accepted
- **Decided in:** #839, #842, #1012

## Context

`claude-account run` started every session of a project under the account the project was bound to in `bindings.tsv` (ADR-hosts-005), whatever that account's allowance, and the owner switched by hand. #839 decided that a new session starts on the profile with the most room, which only the console knows: it answers that profile on `GET /api/profile` and keeps it in the file `chosen-profile` in the accounts directory (ADR-console-023). #842 decided that the launcher asks with a short deadline and falls back when the console does not answer. The owner decided on 2026-11-13 (#1016) that only a named profile directory under `~/.claude-accounts/profiles/` is an account, and the unprofiled directory `default` is not.

## Decision

When `CLAUDE_ACCOUNT` is unset and the caller set no configuration directory of its own, the launcher starts under the first of these that names an existing named profile: the console's answer on `GET /api/profile`, asked under a deadline of one second; the first line of `chosen-profile`; the most recently used signed-in named profile; the first named profile by name. The last two skip a profile the owner excluded in the console (#1028), which the launcher reads on `GET /api/excluded` under its own one-second deadline just before them; when every named profile is excluded the client starts unprofiled, as with no named profile, and an unanswered console excludes nothing. A profile is signed in when its `.claude.json` holds an `oauthAccount` object, its last use is that file's modification time, and equal times go to the smaller name. An answer of `null` or `default`, or a name with no profile directory, counts as no answer. The launcher starts the client unprofiled only when no named profile exists, and then asks no console. It no longer reads `bindings.tsv` at launch. `CLAUDE_ACCOUNT=<profile> claude` still overrides one launch, and a configuration directory the caller set itself is still left alone.

## Consequences

- With the console down a launch waits at most one second for it, besides the cache proxy's half-second probe (ADR-hosts-004), and still starts.
- `claude-account list`, `status`, `use` and `/account <name>` still show and record the binding until a later change removes them; that change supersedes ADR-hosts-005.
- A profile whose login is not recorded in its own `.claude.json` counts as signed out for the fallback.
- The console's own rule decides whenever it answers; the launcher's fallback applies only when it does not.
