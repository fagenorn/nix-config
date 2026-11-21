# ADR-console-075 — A manager on macOS starts in its own session outside the console's launchd job

- **Status:** accepted; amended by ADR-console-081
- **Decided in:** #894, #831

## Context

ADR-console-015 had no launcher on macOS, because `systemd-run`, which keeps a manager in its own scope, exists only on Linux. A Mac therefore ran no managers, sent no nudges, probed no profile and could not sign one in or add or remove an account from the page. The obvious fix, starting the manager as a child of the console, fails on launchd: when a job dies, launchd ends every remaining process in the job's process group, so a manager started inside the console's group would die at every restart of the console and every activation (#831), which is exactly what the scope was for on Linux.

## Decision

**D1. Where it runs.** Managers, nudges, wakes, stops, capacity probes, the reading of a profile's sign-in, sign-in runs and the page's account add and account remove are supported on Linux and macOS and on nothing else. Registration, adoption approval and project questions stay Linux only, as ADR-console-028 D9 and ADR-console-058 D2 decided; this decision does not move them.

**D2. The launch.** On macOS the launch argument list is the client's own, `claude-account run ...`, with no scope in front of it, and it is started with `start_new_session`, so the manager is its own session and process group and is not in the console's. The failure reasons, the timeout and the stderr capture are the Linux launch's, and a launch that times out ends the whole group it started, the account wrapper and the client it waits for, so the client cannot start a manager after the failure is recorded.

**D3. The console's job.** The launchd job that runs the console sets `AbandonProcessGroup = true`, so launchd no longer ends the processes left in the job's process group when the console stops. Together with D2 a manager outlives a restart of the console and an activation. The key spares every process of the console's group, so the console's own stop commands run in sessions of their own and the console ends the ones still running as it closes, which keeps a hung stop from outliving the console; managers are not touched.

**D4. Wakes and the relay.** A wake or a revive of a stopped manager (`claude-account run --resume <id> --bg ...`) is started the same way, in its own session with no scope. The relay of ADR-console-016 is unchanged, as it never used a scope.

**D5. The job's PATH.** The console job's PATH carries the owner's profile and the system profile, so `claude-account` and the programs it and the client need are found. A launchd job reads no shell profile.

**D6. The restart check.** The post-activation check of ADR-console-015 restarts only the launchd job that serves the console's port: it signals the process id `launchctl print` reports for the job that serves the port, looked for in the gui domain and then the system domain, and waits for a new process id of that job in the same domain to be back on the port. A resumed run makes the same check before it reads anything. Any other console on the port is not the job, and the check reads not yet (exit 75), never failed.

**D7. The launcher check.** The check that shows the client launches under the console's profile on a Mac isolates its launches under a temporary HOME and accounts directory, so a run on the owner's Mac writes nothing of the owner's. The isolated accounts directory chooses a profile other than the console's, so a launcher that ignores the console's answer cannot pass on its fallback, and the check reads only the console the installed launcher asks (port 27184).

**D8. The page checks' reading.** A page check reads only the console's own log rows, those after the sequence number `--after-seq` names, so rows another host recorded never meet it.

**D10. The page account check.** The check `console-page-account` adds and removes a throwaway profile through the page's own writes and the page token, and posts nothing when its reading is already met. It removes a profile only when its own add created it or its met reading above the watermark shows an earlier run did: a profile of the same name that was already there is left alone and the check is not met, so the name must be one the owner does not use.

## Consequences

- The unavailable notice (ADR-console-015, ADR-console-064) remains only for platforms other than Linux and macOS. Registration and project questions still say unavailable on macOS.
- The launcher's two launches are shown before merge by the `console-launch-profile` check on eleven-m5. The evidence after activation is the `console-manager-start` check there, which reads not yet until the console there runs as its launchd job (#1290), and the `console-page-account` check, which adds and removes a throwaway profile through the page. The page's Sign in on a Mac is an owner check, because a sign-in needs the owner's login.
- Every page check reads only the Mac console's own log rows (`--after-seq`, D8), so rows recorded on another host never meet it.
- This amends ADR-console-015, ADR-console-016, ADR-console-006, ADR-console-018, ADR-console-022, ADR-console-024, ADR-console-025 and ADR-console-026 in the clauses that said no manager starts on macOS.
