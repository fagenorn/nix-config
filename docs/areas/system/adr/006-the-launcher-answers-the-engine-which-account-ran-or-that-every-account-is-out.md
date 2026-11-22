# ADR-system-006 — The launcher answers the engine which account ran, or that every account is out

- **Status:** accepted
- **Decided in:** #1493, #1495, #1521

## Context

An engine agent step that hits a usage limit must tell a quota wait from a failure, and the engine never calls the console (#1495): the launcher asking the console is the only link between them. The launcher already asks the console which profile a new session starts under (ADR-hosts-008), and the console's answer can carry whether every account is out (ADR-console-023). The launch had no way to hand the engine that answer: a launch with every account out started a client under some profile regardless, and the engine could not learn which account a session ran under.

## Decision

- **D1, the opt-in.** `claude-account run` honours `CLAUDE_ACCOUNT_ANSWER`, a file path, only when it is non-empty. The launcher captures it first and unsets it before anything else, so no client (the loop's, or the caller-chosen configuration directory's) inherits it and a nested launch cannot write the outer launch's answer.
- **D2, the query.** With the variable set the launcher asks `GET /api/profile?all_out=1`; without it the request stays `GET /api/profile`, and nothing else about a launch changes.
- **D3, the account answer.** Before each client start (the first launch and each `switch` relaunch) the launcher writes exactly `{"account":"<name>"}` and a newline to the file, through `<path>.tmp.<pid>` and `mv`. `<name>` is the account the client starts under (a profile name or `default`). `CLAUDE_ACCOUNT=<name>` asks no console and still writes it. A caller-chosen `CLAUDE_CONFIG_DIR` starts the client early and writes no answer.
- **D4, the all-out answer.** When the console's body matches exactly `{"all_out":true,"profile":null,"resumes_at":<null or a UTC time ending in Z>}` the launcher writes exactly `{"all_out":true,"resumes_at":<the same token>}` and a newline, starts no client, prints nothing on stdout or stderr, and exits 75. Any other body, and a silent or closed console, fall back as before. The marker is read only when `CLAUDE_ACCOUNT` is empty, so an override shaped like it is an invalid account name.
- **D5, the engine never calls the console.** The engine reads only the file and the exit status. The probe stays builtin-only: no curl or jq starts on that path.

## Consequences

- ADR-hosts-008 and ADR-console-023 are amended: a launch that names an answer file asks the profile question with `all_out=1`.
- Exit 75 from `claude-account run` means every account is out, and only when the answer file is named.
- A new client start in `cmd_run` must write the account answer, and must never inherit the variable.
