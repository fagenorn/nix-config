# Installed Legacy Contracts Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `workflow-state build-delivery` serves every contract-taking kind for a
contract it cannot re-derive when, and only when, a ledger under `--repo-root`
has installed that exact contract, so an in-flight owner can reach
`delivery_complete`
([#193](https://github.com/fagenorn/nix-config/issues/193)).

**Architecture:** The pure builder gains one derivation check, shared by a new
predicate `requires_installed_intent` and the contract check. The contract check
now yields the contract's reference initial intent, derived or handed in as
`installed_intent`, and `initial-intent`, `scope` and `authority-observation`
read it (Task 1). workflow-state extracts check-launch's unlocked reader, and it
adds a lookup beside it that scans the runs under `--repo-root` for the
installing ledger. It runs that lookup only when the predicate is true, and it
states the one ledger read in help (Task 2). `CLAUDE.md` and ship-handoff
restate it (Task 3).

**Tech stack:** Python 3 stdlib (`json`, `stat`, `pathlib`, `unittest`),
Markdown skill prose, `just`.

Spec (source of truth, read it whole):
`.agents/artifacts/specs/2026-09-26-issue-193-installed-legacy-contracts-design.md`,
D1–D13.

## Global Constraints

- Scope is exactly the spec's. Its `## Out of scope` list binds: no migration
  verb, no change to `--kind contract`, `_SOURCE_KINDS` or any contract, intent
  or ledger schema, no successor-intent scopes, and no move into `agent_tools`
  (D1, D9, D10).
- The builder and runtime do no I/O. `WORKFLOW_DELIVERY_BUILD_INTERFACE_VERSION`
  and `WORKFLOW_DELIVERY_INTERFACE_VERSION` stay 1 (D5).
- A contract that re-derives is served byte for byte as at base, and no ledger
  is read for it (D2).
- Every existing refusal text stays. The only new texts are
  `<R>; no ledger under the repo root installs this contract`,
  `installed initial intent does not match the contract`,
  `installing ledger <run-id> is invalid` and
  `the contract's initial intent declares no single scope for stage <id>` (D7).
- Every refusal still exits 2 with empty stdout and exactly one stderr line,
  `workflow-state: <message>\n`, through the existing `main`.
- The lookup takes no lock, reads no clock and writes nothing (D4).
- Tests use only the seams below, with temporary project roots and `HOME`s.
  Never open or repair `.superpowers/workflows/` in the primary checkout.
- The helpers under `~/.agents/bin` are `main`'s build. Every gate runs this
  worktree's `home/common/agent-skills/scripts/*` directly or through the tests.
- No file is created and no `.nix` file changes. `just build` runs once, in the
  final gate. Never run `just switch`.
- Run targeted tests from the worktree root as
  `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/<file>.py -k <Class>`.
  Summarize output to the `FAIL:`/`ERROR:` ids and the `Ran`/`OK`/`FAILED` lines.
- Commits are conventional and SSH-signed. Never disable signing, and surface a
  signing failure. Each message ends with the two trailer lines
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_014t9cPhYQiiTKbbAn8vTEaq`.

Path abbreviations used in members: `S` = `home/common/agent-skills/scripts`,
`T` = `home/common/agent-skills/tests`,
`SH` = `home/common/agent-skills/skills/from-issue/ship-handoff.md`.

## Test seams

- **Delivery-loop CLI seam:** `DeliveryLoopTest.deliver` in
  `T/test_delivery_workflow.py`, with a hand-built contract source. It covers
  AC1, AC2 before installation, and AC2 for a mutated contract (D8).
- **Ledger-read seam:** the same harness. It covers the invalid installing
  ledger, the skip of an unparsable run, the absent lock file, the unfollowed
  symlinked `.superpowers`, a derived build beside an invalid ledger and under an
  absent root, and the absent-root refusal (D8, D13).
- **Help seam:** `test_help_states_the_contract_resolution_root`, with
  whitespace normalized (D11).
- **Runtime-facade seam:** `InstalledIntentTest` in `T/test_workflow_delivery.py`.
  It covers the predicate, the not-installed clause, the installed-intent
  re-check and the no-single-scope refusal (D12).
- **Skill contract suites:** `T/test_workflow_skill_contracts.py`,
  `T/test_shell_example_contracts.py` and `T/test_dispatch_contracts.py`. They
  only need to stay green after the ship-handoff edit.

## Delivery estimate and boundaries

These figures are estimates from the planning probe. Seven files change and none
is created. Product code grows by about 140 lines net across
`S/workflow_delivery_build.py`, `S/workflow_delivery.py` and `S/workflow-state.py`.
Tests grow by about 220 lines across two files. The docs change one sentence each
in `CLAUDE.md` and ship-handoff. The unified diff should be about 50 KB, which
fits one review package. The main risk is
a derived contract's output drifting, and the unchanged builder and loop tests
pin it. Tasks run in index order, and each depends on every earlier one. The
plan adds 7 tests, 5 in Task 1 and 2 in Task 2, so the suite's 1305 tests at
`6c23e64` become 1312. The suite takes about 9 minutes.

## Task index

Task 1 — The builder serves a contract against its reference initial intent — `S/workflow_delivery_build.py`, `S/workflow_delivery.py`, `T/test_workflow_delivery.py` — full — [task-1.md](2026-09-26-issue-193-installed-legacy-contracts.tasks/task-1.md)

Task 2 — workflow-state finds the installing ledger and serves its intent — `S/workflow-state.py`, `T/test_delivery_workflow.py` — full — [task-2.md](2026-09-26-issue-193-installed-legacy-contracts.tasks/task-2.md)

Task 3 — State the ledger read in the living docs, then run the final gate — `CLAUDE.md`, `SH` — full — [task-3.md](2026-09-26-issue-193-installed-legacy-contracts.tasks/task-3.md)

## Criterion → task trace

| Criterion | Task |
|---|---|
| AC1: an installed hand-built contract gets `selected-output` and `observation` objects | 1 (reference intent), 2 (lookup, loop test) |
| AC1: `finish` reaches `delivery_complete` | 2 |
| AC2: no ledger entry is refused | 1 (clause), 2 (every kind before installation) |
| AC2: a mutated contract is refused | 2 |

## Decisions

The spec's `## Decision ledger` is authoritative. Tasks cite D1–D11 from design.
Planning added two rows. **D12** adds the runtime-facade seam for the builder's
own re-check. **D13** settles the lookup details §2 leaves open: symlinked
directories, a match that changes on re-read, the unprefixed root refusal, and
the verbatim reader.

A planning probe applied every task's code, tests and prose, as written, to a
scratch copy of `6c23e64`. Each watch-it-fail step failed as its member says, and
each targeted gate passed. Three mutants were caught: `scope` re-deriving through
`_scope`, the command consulting ledgers for every contract, and the lookup
following a symlinked `.superpowers`.
`WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests` gave `Ran 1312 tests`
and `OK (skipped=4)`. `just build` was not probed.

---
