# Register Against the Remote Integration Branch Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `adopt-project verify --register` proves conformance and integration against the fetched `origin` integration branch, and leaves the local branch, working tree and untracked files untouched (https://github.com/fagenorn/nix-config/issues/341).

**Architecture:** `verify_repository` reads everything through one *verification source* (ref label, pinned commit, resolver directory, inventory). Plain `verify` builds the `HEAD` source. `--register` builds a remote source: `ls-remote` names the remote default, an explicit-refspec fetch pins a commit, and a `git archive` export of that commit is what the resolver checks. `register_project` checks ancestry against the pinned commit id and the contract's branch against the fetched branch.

**Tech stack:** Python 3 standard library (`subprocess`, `tarfile`, `tempfile`, `contextlib`, `dataclasses`), git 2.51 CLI, `unittest`.

Spec: `.agents/artifacts/specs/2026-10-09-issue-341-register-against-remote-integration-branch-design.md` (its `## Decision ledger` rows D1–D11 are cited by ID). Its `## Solution` steps 1–7 are the algorithm Tasks 2 and 3 implement.

## Global Constraints

- Code lives in `python/agent_tools/` (`adopt_inspection.py`, `adopt_verify.py`, `adopt_project.py`); tests in `home/common/agent-skills/tests/test_adopt_verify.py`. No other source file changes.
- No new `ADOPT_ERROR_CODES` member (D6). Repair ids used: `adopt.registration.no_remote`, `adopt.registration.remote_default_unknown`, `adopt.registration.integration_branch_unresolved`, `adopt.registration.not_integrated` (all `not_integrated`); `adopt.git.remote_unreachable`, `adopt.git.fetch_failed`, `adopt.git.export_failed`, `adopt.git.unparseable_tree` (all `adopt_failure`).
- The remote is always the literal name `origin` (D2). No new CLI flag.
- `plan` and `apply` behaviour is untouched; `tracked_inventory` keeps its signature and callers.
- The resolver is reached only through the `run_resolver` callable `adopt_project` passes in (#148 D26). `adopt_verify` never imports `adopt_project`.
- Network git calls (`ls-remote`, `fetch`) run with `GIT_TERMINAL_PROMPT=0` and the existing 300 s timeout.
- Commands run from the worktree root, in the foreground under `launch-scope exec … --`. Focused tests: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_verify.py [-k <pattern>]`, timeout at least 600 s (the whole file takes about 20 s at base).
- Final gate, once on the final head (sdd's final gate, not a per-task gate): `just build` (timeout 3600 s) and `just agent-workflow-tests` (timeout 3600 s).

## Test seams

- The CLI as a child process: `python -m agent_tools.adopt_project verify --repo-root … [--register]` under a temporary `HOME` through `VerifyTestCase.verify`, with `origin` a local bare repository made by the new `publish` helper (D9).
- `adopt_verify.register_project` imported directly, for the inner checks no CLI path reaches (D7, D9).

## Delivery estimate and boundaries

Estimates: 4 changed files plus this plan. `adopt_inspection.py` about +120 lines, `adopt_verify.py` about +150, `adopt_project.py` about +30 (mostly docstring), `test_adopt_verify.py` about +250. One review package; no slicing needed.

## Task index

Task 1 — Verification source seam and the `revision` report member — `python/agent_tools/adopt_inspection.py`, `python/agent_tools/adopt_verify.py`, `python/agent_tools/adopt_project.py`, `home/common/agent-skills/tests/test_adopt_verify.py` — full — [task-1.md](2026-10-09-issue-341-register-against-remote-integration-branch.tasks/task-1.md)
Task 2 — Register from the fetched remote default branch — `python/agent_tools/adopt_inspection.py`, `python/agent_tools/adopt_verify.py`, `python/agent_tools/adopt_project.py`, `home/common/agent-skills/tests/test_adopt_verify.py` — full — [task-2.md](2026-10-09-issue-341-register-against-remote-integration-branch.tasks/task-2.md)
Task 3 — Follow the contract's integration branch, and rewrite the docs — `python/agent_tools/adopt_verify.py`, `python/agent_tools/adopt_project.py`, `home/common/agent-skills/tests/test_adopt_verify.py` — full — [task-3.md](2026-10-09-issue-341-register-against-remote-integration-branch.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 2 | `test_adopt_verify.py::RemoteRegistrationTest::test_a_diverged_local_branch_registers_from_the_remote` |
| AC2 | code (classified) | Task 2 | `test_adopt_verify.py::RemoteRegistrationTest::test_an_unpushed_adoption_refuses_not_integrated` and `::test_an_adoption_only_on_its_apply_branch_refuses_not_integrated` |
| AC3 | code (classified) | Task 3 | `just agent-workflow-tests` on the final head (sdd's final gate) |

## Decisions

- Only `--register` moves to the remote: D1. Remote is `origin`: D2. Integration branch from the remote contract, one hop: D3. Explicit-refspec fetch and pinned id: D4, with its flags per D11. Export-and-check: D5. Closed codes, repair ids carry the cause: D6. Integration gate and inner checks: D7. `revision` member and schema 2: D8. Test seams: D9.
- Revision readers in place of the `HEAD` helpers, `HEAD` pinned in plain `verify`: D10 (appended by this plan). Fetch flags and the `FETCH_HEAD` witness: D11 (appended by this plan).
