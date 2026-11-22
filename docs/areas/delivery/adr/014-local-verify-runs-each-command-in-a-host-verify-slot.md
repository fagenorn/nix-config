# ADR-delivery-014 — Local verify runs each command in a host verify slot

- **Status:** accepted
- **Decided in:** issue 1383

## Context

A verification run is heavy, and several delivery runs can start on one host at once. ADR-delivery-006 bounds the jobs inside one run, but nothing bounded the runs themselves, so a shared host could be loaded by every run's suite at the same time.

## Decision

- D1. The number of verify slots a host offers lives in the host declaration, with a default of one.
- D2. A slot held by a dead process is given back.
- D3. A run in progress is never preempted.
- D4. The count is the optional top-level declaration member `verify_slots`. Its value is a plain integer of at least 1; a boolean, 0, a float or a string makes the declaration invalid. An absent member is 1, and so is a missing declaration file. An invalid declaration is refused: `verify-slot` exits 2 and runs nothing. The committed declaration stays without the member, so every host gets 1.
- D5. A slot is an exclusive non-blocking `flock` on `slot-<i>.lock` for `i` in `0..count-1`, in one directory that belongs to the host and not to an account: `/tmp/agent-verify-slots`, or the directory `VERIFY_SLOT_DIR` names (a seam for tests). The directory has mode 1777 and the files mode 0666, so every local account of a shared host draws on the same slots; a slot directory under `$HOME` would give each account its own and admit one run per account. There is no lease, expiry or pid check: a live holder keeps its slot however long it runs (D3), and the kernel releases the lock of a dead holder (D2). Admission counts the live holders of every `slot-*.lock` file, not only the first `count`: a run that took a slot gives it back and waits when the holders, itself included, outnumber the declared count, so a count lowered while a higher-numbered slot is held never admits a run beside that holder. The wait limit is checked before each further try, so a slot freed after the limit is not taken.
- D6. The holder is the `verify-slot` process itself, and its child never inherits the lock descriptor. A `verify-slot` killed by SIGKILL gives its slot back at once, even while its child still runs. SIGTERM, SIGHUP and SIGINT are forwarded to the child; the holder waits for it, releases the slot and exits 128 plus the signal.
- D7. A slot is taken per verification command, not once per verify step. Each command is its own Bash call, and holding a slot across calls would need a detached process, which the lifecycle guard refuses.
- D8. A waiting run polls every 0.2 seconds and no order among waiters is promised. It says on stderr when it starts to wait and when it got a slot. The result schema of the delivery program does not change.
- D9. The delivery program passes `--wait-limit 600`. At the limit `verify-slot` prints its no-slot line and exits 75. The verify clerk then runs the same argv again, up to 12 attempts in all, and after the last reports the id as `fail`. This keeps each Bash call, the wait plus the run, inside the 60-minute bound the verify prompt already states. The retry holds in every verification prompt, the one rerun of a failure outside the branch's changed files included: an attempt that ran nothing is not a run of the command, so it uses up neither the verification's "once" nor the rerun's "never a second time", and a busy host never turns a rerun into a fix wave. A verification that exhausts the attempts reports the id as `fail` with `no_slot: true`; the program reads that mark and stops the delivery at the `verify` stage, with no rerun and no fix step, because the command never ran and no code defect is shown.
- D10. The verification cache key stays the declared entries, unwrapped. Wrapping changes no contract, and a cached ready stop is still reused.
- D11. A child exit code is passed through, and a child killed by a signal exits 128 plus the signal. A child that cannot start exits 127. A usage error, an unset `HOME`, an invalid or unusable (not a file) declaration entry, or an unusable slot directory exits 2; only an absent declaration file means the default. The command lives in the delivery area next to `host_admission`, and adds no glossary term, because the context map is at its budget.
- D12. The deliver-direct skill's verify is out of scope here and is follow-up issue 1578. The acceptance criteria name only the delivery program's verify step; the skill is at its byte cap and the instruction corpus at its ceiling, so wrapping it needs a trim elsewhere or a raise label that only the owner applies.

## Considered options

- **A lease file with a pid check.** Rejected: a pid can be reused, so a stale lease could look live, and an expiry would preempt a run in progress, against D3.
- **One slot per verify step, held by a detached process.** Rejected: the lifecycle guard refuses detached processes, and a slot held across Bash calls needs one.
- **Blocking `LOCK_EX`.** Rejected: it has no wait limit and cannot wait on several slots at once.
- **Wrapping the deliver-direct skill's verify in the same change.** Deferred to issue 1578: the skill is at its byte cap and the instruction corpus at its ceiling.

## Consequences

- A SIGKILLed `verify-slot` frees its slot while its child may still run, so that child is briefly uncounted.
- There is no FIFO order: a waiter that polls at the right moment can overtake an older one.
- A host that wants more than one slot needs its own declaration source; none does today.
- Until issue 1578 lands, a deliver-direct verify is not counted against the slot and can run beside a slotted one.
- The slot count complements ADR-delivery-006's per-run job count: that bounds the jobs of one run, this bounds the runs of one host.
