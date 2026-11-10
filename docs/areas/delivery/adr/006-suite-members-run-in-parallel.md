# ADR-delivery-006 — Suite members run in their own processes, in parallel by default

- **Status:** accepted
- **Decided in:** issues 436, 496, 499, 604

## Context

The agent workflow suite is CPU-bound and its CPU time does not change with the job count, so only wall time can be bought. Running every member serially made a full run too slow to use as the verification gate. The measured effect of the job count is in [the suite-runner job count record](../../../archive/suite-runner-job-count.md).

## Decision

Each member runs in its own process and at most `--jobs N` run at once. The default is `SUITE_RUNNER_JOBS` when set and non-empty, else `min(8, CPUs - 2)` with a floor of 1, so two CPUs stay free for the host and a large machine does not oversubscribe its disk and git. Members start longest first, in the order of the committed `suite_timings.json`. A test that shares state with another test process is fixed by giving it its own temporary location, never by a serial-exemption list, a retry or a lock.

## Consequences

- A host shared by several agents verifying at once must set `SUITE_RUNNER_JOBS` lower; the hosted CI job sets 4, the vCPUs of its runner.
- A stale timings file only costs wall time.
- The environment entries `maintenance.auto=false` and `gc.auto=0` do not reach a process started with an environment built from scratch or with its own `GIT_CONFIG_PARAMETERS`, nor the receive-pack of a push to a local repository, so that receiving repository still runs automatic maintenance.
- The per-run bytecode cache does not reach a process started with an environment built from scratch, nor one run with `-I` or `-E`. A descendant still running after the run ends may recreate part of the removed directory.
- CPython takes a cached file as current while its source's modification time, in whole seconds, and its size match. A test that rewrites an importable source in place to the same size within one second, then imports it in a new process, must give that process its own `PYTHONPYCACHEPREFIX` directory.
- Outside the runner, as in a direct `python -m unittest` run, a test's Python children write bytecode beside their sources where those are writable.
