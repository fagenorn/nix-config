# ADR-console-015 — A stated goal starts a manager in its own scope

- **Status:** accepted; amended by ADR-console-017, ADR-console-023
- **Decided in:** #831, #835, #839, #888, #1016

## Context

ADR-console-011 turned a goal stated on the page into a sprint, and ADR-console-013 carried a manager's brief to the page, but nothing started the manager. #835 decided that a sprint has one manager and that the console starts it; #839 decided that it runs in the background under the profile with the most weekly allowance left; #831 found that `claude --bg` returns in about a second and detaches a supervisor, that there is one supervisor per configuration directory, that an untrusted directory is refused, that the account must be named explicitly and that a supervisor started inside a unit dies with that unit. This slice starts the manager, shows what became of it and lets the owner retry a start that failed.

## Decision

**Launch and scope.** On a stated goal the console runs, off its ingest lock, `systemd-run --user --scope --quiet --collect --description=agent manager <name> -- claude-account run --bg --name <name> --settings <file> "You are the manager of one sprint, started by the console. Run \"sprint contract\" first and follow what it prints. The goal: <goal>"` in the project's root, the goal appended verbatim, with `CLAUDE_ACCOUNT=<profile>` in the client's environment. The scope keeps the detached supervisor from dying with the console's unit (#831). `claude-account` syncs the profile, routes through the cache proxy, which is what produces limit readings, and runs the pinned binary. The output goes to `DEVNULL` and a temporary file, never a pipe, because the detached supervisor may keep inherited descriptors open.

**Profile rule.** A profile has room when its capacity reads ok or reset. The manager takes the profile with the most weekly allowance left, then the most five-hour allowance left (an unknown reading lowest), then the lowest name. When no profile has room and every one reads out, the sprint waits until the earliest reset and no manager starts. A signed-out profile has no room; with no profile known to have room and not every profile out, the choice is the most recently used signed-in profile, and with none signed in nothing is chosen and the manager waits (the unprofiled client directory is never chosen, ADR-console-006). The per-project binding is not read (ADR-console-023). The profile directories are read when the choice is made, because a profile created after the console started is unseen by the poll until its next round.

**Identity per session, not per client.** One supervisor serves a configuration directory (#831), so a second manager on the same profile, or one on a profile whose supervisor the owner started, may not see the launching client's environment. The sprint's identifier and secret are therefore written to a per-sprint settings file, `sprint-secrets/<id>.settings.json` (mode 0600, in the 0700 directory of ADR-console-011), as the `env` of `{"CONSOLE_SPRINT_ID", "CONSOLE_SPRINT_SECRET"}`, and passed with `--settings`, and they are removed from the client's environment. `sprint` reads both from the environment when `--sprint` and `--secret-file` are absent, so the manager never handles the secret. Withdrawing a goal removes the file with the secret. That a `--bg` session started through a running supervisor receives its own `--settings` cannot be observed before deploy; the post-activation check states two sprints on one profile and requires each brief to be version 1 on its own sprint.

**Three rows, not kept.** The outcome is recorded as `manager.started` (sprint, profile, session name), `manager.failed` (sprint, reason) or `manager.waiting` (sprint, until), and the latest row of an open sprint is its manager row. They are not kept kinds, so the store needs no schema bump; a sprint older than 90 days may lose its manager row on restart, which then reads as no manager and offers retry.

**One rule for state and retry.** `sprints.manager_status` gives the state, its text and whether retry is offered, and the view renders it while the retry route enforces it. `unavailable` is a host with no launcher; `failed` and `waiting` offer retry only while the sprint has no listed session and no brief, because a launch can fail after its detached session was handed off and a retry would start a second manager; `started` offers none while its session is listed, a brief exists or two minutes have not passed since the row, and otherwise reads `missing` (the manager is not running) with retry, so a manager that never appears, or died before its brief, is reported and not silent. A sprint with no row offers retry past two minutes with no brief and no listed session, which covers a sprint stated before the deploy.

**Retry, not relaunch.** `POST /api/retry-manager` is a page write under ADR-console-008 and appends nothing when it refuses. Nothing relaunches automatically, a quota reset included: automatic resume is a later slice of #835. A launch is reserved under the ingest lock in the same critical section that decides it may run, the goal's append or the retry's eligibility check, and the job rechecks the sprint before launching, so concurrent retries start one manager.

**Session name.** The session is named `<project id> sprint <sprint id>`. A listed session of the sprint's project with exactly that name is shown inside its sprint, with its manager state, and not in Outside sprints.

**macOS.** There is no launcher on macOS: the sprint reads `unavailable` and nothing starts. Only Linux has `systemd-run`.

**The unit's PATH.** The console unit's PATH gains the user profile and the system profile on Linux, and the launch puts `~/.agents/bin` first, so `claude-account`, its coreutils, `systemd-run`, `sprint` and `resolve-project` are found. A systemd user unit does not read `home.sessionPath`.

**The contract's home.** The manager's contract is a document of the console package, `agent_tools/console/manager-contract.md`, shipped as package data like the page and printed by `sprint contract`; the launch prompt tells the manager to run it first. It states one manager per sprint, only existing skills, never code, reversible matters decided and recorded in the brief, the owner reached only through `sprint`, the five parts of the brief and the refusal handling, and the pull request reviews that prose. Only a manager reads it, so it adds nothing to the instruction corpus other sessions load and the Instruction Budget ceilings are unchanged. Later slices extend this document.

**Two verify checks.** One committed script, run after activation on the Linux host, gates on behaviour: two marked goals on one project each get a brief at version 1 and, after a restart of the console, both managers are in a fresh process-validated registry read. It has live effects, so each run needs the owner's tick, and a brief that has not arrived stays not-yet until the check expires. The second check only observes the time from goal to brief against the ten-minute target, from the console's own timestamps.

## Consequences

- A stated goal starts one background session under the profile with the most room, and a failure is shown inside the sprint with its reason and a retry.
- A manager that never appears reads missing after two minutes and can be retried; a manager that died before its brief reads the same.
- Every profile out leaves the sprint waiting until the earliest reset, and the owner retries after it.
- The secret is on disk in two 0600 files of one sprint and in the manager's session environment, and in no argv, log row, view or stderr line.
- On macOS no manager starts.
- The Instruction Budget is unchanged: the contract is not a skill.
