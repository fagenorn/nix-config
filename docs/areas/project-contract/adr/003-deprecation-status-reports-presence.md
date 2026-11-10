# ADR-project-contract-003 — `platform-status` reports a deprecated file by presence, not git tracking

- **Status:** accepted
- **Decided in:** issue 580, issue 579 (P2)

## Context

`resolve-project platform-status` tells an operator which deprecated or removed `project_file` a project still holds. Asking git whether the file is tracked would be the precise answer, but the command starts no child process.

## Decision

A `project_file` entry is reported when its subject exists under the project root by `os.lstat`, a dangling symlink included, whether or not git tracks it. A report never changes `compatible`, `reason_code`, `repair_id` or the exit code, and `resolve` never reads it.

## Consequences

- An untracked or ignored copy is still reported, so the operator may see a file that no commit holds.
- Only ENOENT and ENOTDIR mean absent; any other error reads as `null` rather than a clean report.
