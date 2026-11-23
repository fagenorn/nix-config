# ADR-verification-010 — A retired host's checks go to its successor or are reported

- **Status:** accepted
- **Decided in:** #1291

## Context

The drive of `anis-desktop` failed on 18 Nov and the host will not run passes again. A held check bound to it would wait forever, and every other host would post a stale prompt naming a host that cannot answer. The block grammar and its lint still allow a block to name `anis-desktop`, and held blocks do.

## Decision

The runner carries one map of retired hosts to their successors, `verify_run.RETIRED_HOSTS` (`anis-desktop` to `eleven-m5`), the default of a `retired` keyword on `pass_repo` and `pass_issue`, so the scheduled pass, `just verify` and a manual run agree without a new flag.

A check bound to a retired host is taken by its successor exactly when the unattended gate would run it (ADR-verification-003): an evidence check with no `ask` or `act`, no live or paid effects, and a command only when it is a verification id. Probes are taken; a script is taken only when its text at the commit it runs at is readable and names nothing Linux-only (`verify_run.LINUX_ONLY`: systemd tools, `/proc`, `/sys`, NixOS paths), because the successor is darwin, so an unreadable or Linux-only script is taken by nobody. Any other check is taken by nobody: every host reports it as one `pending` line with reason `host_retired`, after a final result and before any owner answer or decision prompt, and it is never answered. In a host list a retired member is replaced by its successor when the check is takeable and dropped otherwise, and an empty list is `host_retired`.

A writing pass ends with reason `host_retired` every live runner prompt of the block that names a retired host or belongs to a check no host can take, and every live `verify-due` marker a retired host wrote, so no answer, stale rule or lapse reads them. An `ask` or `act` prompt a retired host posted for a check another live host can answer is not ended: it is renamed in place to the successor (its `host` field and its sentence), so it keeps its boxes and its answer. The console's owner waits skip a check bound only to retired hosts, as the runner never asks it. The `verify-seen` report and the stale rule follow the effective host, and a taken check goes stale only after its successor has reported on the block. A stale prompt's identity includes its host. The successor also recovers a retired host's follow-up claim.

## Consequences

- A returning host is restored by removing its entry from the map; the block grammar and the lint are unchanged.
- `host_retired` is a new line reason and a new end reason.
- A stale prompt's identity now includes its host, so an ended prompt naming the retired host never blocks the successor's.
- Related: ADR-verification-003 (the unattended gate), ADR-verification-008.
- Amends ADR-verification-009 (D1: a stale prompt's identity includes its host; a retired host's live prompts end without an answer).
