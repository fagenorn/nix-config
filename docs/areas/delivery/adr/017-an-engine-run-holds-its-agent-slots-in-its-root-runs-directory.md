# ADR-delivery-017 — An engine run holds its agent slots in its root run's directory

- **Status:** accepted
- **Decided in:** issue 1522

## Context

A prototype of the engine ran 32 agent sessions at once, and each session's start-up grew from 19 seconds to 92 seconds. Nothing bounded the sessions of a run. Issue 1493 settled that the host declaration names the engine route with its own slot count, that the count bounds one run, and its amendment ruled out a count across runs.

## Decision

- D3. The engine route in the host declaration carries `agent_slots`, 8 in the committed declaration, and a host that does not admit the route starts no engine run.
- D6. A run's slots are the files `slot-0.lock` to `slot-<count-1>.lock` in `slots/` under the root run's directory, mode 0700. A slot is an exclusive non-blocking `flock` the engine process takes on a descriptor it opens itself and closes in a `finally`. The session never inherits it, and the kernel frees it when the engine dies.
- D7. Only an agent step takes a slot, for the span from `session_starting` to the return of the launch. A command step takes none.
- D8. With every slot taken, the run records `wait_started` for the `host-slot` wait once, polls every 0.2 seconds and records `wait_ended` once when it gets a slot. With a slot free at once, no wait event is recorded.

## Considered options

- **A host-wide slot directory under `/tmp`, as in ADR-delivery-014.** Rejected: the bound is per root run, and a count across runs is a recorded rejection (`host-contention-scheduling`).
- **The engine route sharing the role-set floor of the claude-code route.** Rejected: the engine has no role sets, so a floor derived from them means nothing for it.

## Consequences

- A SIGKILLed engine frees its slot at once while a session process that escaped the session's process group may still run, uncounted.
- There is no FIFO order: a waiter that polls at the right moment can overtake an older one.
- Two root runs on one host each hold their own slots, so the host can run more sessions than one run's count.
