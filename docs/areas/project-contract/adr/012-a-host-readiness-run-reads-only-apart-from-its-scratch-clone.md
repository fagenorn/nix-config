# ADR-project-contract-012 — A host readiness run reads only, apart from its scratch clone

- **Status:** accepted
- **Decided in:** issue 1382

## Context

Host faults were found one delivery at a time: a missing executable, a logged-out credential or a failing commit hook surfaced only when a delivery reached the step that needed it.

## Decision

`host-readiness <project-id>` runs every check that a registered project is ready on this host, one line per check, and keeps going after a failure. It has no production command and no release run: a verification command that would run a declared production command, or a `release transaction` verb other than `status` and a read-only `preview`, is not run and its check fails. The preview is `--read-only`, never takes the land lock and carries no candidate. The commit-hook check is an empty commit in a clean clone under the registered checkout's commit hooks, proven by the new commit with the old HEAD as its parent. The children run with no forge token and no Git redirect, and their directories are contained in the clone, so a verification directory that escapes through a symlink is not run. The clone lives in a scratch directory that is removed on every outcome the process lives through, and a killed run's scratch is swept by the next run. A live run's scratch, another user's directory and a symlink are never touched.

## Consequences

- A run lasts as long as the project's verification.
- The post-merge check runs under a 600 s budget. On a slow pass it reads "not yet" and is retried.
- A project whose adapter credential class has no probe fails its login line until a probe is added.
- `release transaction preview` gained `--read-only`.
