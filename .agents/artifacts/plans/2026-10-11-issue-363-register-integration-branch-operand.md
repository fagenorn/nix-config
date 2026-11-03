# verify --register Reaches the Integration Branch Through an Operand Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `adopt-project verify --register --integration-branch <name>` registers a repository whose default branch's contract does not resolve against the named integration branch on `origin`, and the report and the fleet registry entry record that branch override.

**Architecture:** `agent_platform` lets a registry entry carry one optional closed member, `branch_override`, in its validator and writer. `adopt_verify.remote_source` takes the operand as a third input, consults it only after the default branch's contract failed to resolve, and marks the `VerificationSource` it yields; `verify_repository` and `register_project` build the override object from that source. `adopt_project.command_verify` stays a thin shell that refuses a misused operand and passes it on.

**Tech stack:** Python 3 standard library (`agent_tools` package under `python/`), `unittest`, git fixture repositories with a local bare `origin`.

Spec: `.agents/artifacts/specs/2026-10-11-issue-363-register-integration-branch-operand-design.md` (requirements R1–R10; its `## Decision ledger` rows D1–D10 are cited by ID).

## Global Constraints

- Base: `96174d0ec1a6b4f507059bdcdff56f5532442bbf` (`origin/main` at planning).
- Standard library only. Policy lives in `adopt_verify` and `agent_platform`; `adopt_project` only parses, refuses a misused operand and calls (`docs/standards/agent-helpers.md` rule 2).
- Unchanged: `ADOPT_ERROR_CODES`, `VERIFY_SCHEMA_VERSION` (2), `REGISTRY_SCHEMA_VERSION` (1), `REGISTRY_ENTRY_MEMBERS`, `python/agent_tools/adopt_inspection.py`, `resolve_project.py`, `adopt_planning.py`, plain `verify`, and the contract schema (D4, D5, R10).
- A run that does not select its branch through the operand produces today's report and registry bytes (R7, R8).
- No existing line of `home/common/agent-skills/tests/test_adopt_verify.py` is edited or removed: every change to it is an addition (AC4). Gate, run by each task that touches it: `git diff --numstat 96174d0ec1a6 -- home/common/agent-skills/tests/test_adopt_verify.py` prints `0` in its second column.
- No repository-specific branch name, path or identity in production code (R10); `dev`, `main`, `stale`, `old` and `other` appear in tests only.
- Prose that lands in code (docstrings, comments, help text, error messages, README sentences) describes the code as it behaves at that task's commit; where a task lists facts instead of a sentence, write the sentence from the implemented code.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration; commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root.
- Python tests run as `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_verify.py [-k <pattern>]` (timeout at least 900 s; the suite starts git and resolver subprocesses).
- Final gate, once on the final head (sdd's, not per task): `just agent-workflow-tests` (timeout 3600 s) and `just build` (timeout 3600 s).

## Test seams

- The CLI as a child process (`VerifyTestCase.verify`, `report`, `refuse`, running `python -m agent_tools.adopt_project`) against a local bare `origin` built by `publish`, under the temporary `HOME` (341 D9).
- Imported functions for what no CLI path reaches: `adopt_verify.register_project` (existing cases) and `agent_platform.validate_registry`, `write_registry`, `read_registry` (D7).

## Delivery estimate and boundaries

Estimates: 6 changed files — `agent_platform.py`, `adopt_verify.py`, `adopt_project.py`, `test_adopt_verify.py`, `test_resolve_platform_status.py` (one docstring), `python/README.md` — about +130 production lines and +330 test lines, one review package. Task 1 is independently deliverable. The aggregate-growth risk is `test_adopt_verify.py` (668 lines at base, about 1000 after).

## Task index

Task 1 — Registry entry admits the optional `branch_override` — `python/agent_tools/agent_platform.py`, `home/common/agent-skills/tests/test_adopt_verify.py`, `home/common/agent-skills/tests/test_resolve_platform_status.py` — full — [task-1.md](2026-10-11-issue-363-register-integration-branch-operand.tasks/task-1.md)
Task 2 — `--integration-branch` operand, branch reach, report and registration — `python/agent_tools/adopt_verify.py`, `python/agent_tools/adopt_project.py`, `home/common/agent-skills/tests/test_adopt_verify.py` — full — [task-2.md](2026-10-11-issue-363-register-integration-branch-operand.tasks/task-2.md)
Task 3 — Checkout isolation, registry lifecycle cases and the documented contract — `home/common/agent-skills/tests/test_adopt_verify.py`, `python/README.md` — full — [task-3.md](2026-10-11-issue-363-register-integration-branch-operand.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 2 | `test_adopt_verify.py`: `IntegrationBranchOperandTest.test_the_operand_registers_against_the_integration_branch` (with `test_a_default_branch_without_a_contract_takes_the_operand_too` and the premise case `test_the_stale_fixture_contract_is_refused_invalid_contract`) |
| AC2 | code (classified) | Task 2 | `test_adopt_verify.py`: `IntegrationBranchOperandTest.test_an_operand_branch_without_the_record_refuses_not_integrated` |
| AC3 | code (classified) | Task 2 | `test_adopt_verify.py`: `IntegrationBranchOperandTest.test_an_operand_the_remote_and_its_contract_do_not_confirm_refuses` |
| AC4 | code (classified) | Task 2 | `test_adopt_verify.py`: `IntegrationBranchOperandTest.test_a_resolving_default_ignores_an_agreeing_operand` (with `test_a_resolving_default_refuses_a_disagreeing_operand`, the unedited `RegistrationTest`, `RemoteRegistrationTest`, `RegisterProjectInnerCheckTest` and `VerifyReadOnlyTest`, and the zero-deletion gate of Global Constraints) |
| AC5 | code (classified) | Task 3 | `test_adopt_verify.py`: `IntegrationBranchOperandLifecycleTest.test_nothing_is_read_from_the_checkout` |
| AC6 | evidence (classified) | Task 3 | Command `just agent-workflow-tests`, run on the final head after Task 3 by sdd's final gate; threshold: exit code `0`; acceptance-record row `AC6` |

## Decisions

- Operand only, as a pointer the remote and the branch's own contract confirm: D1. When it acts and when it refuses: D2.
- The `branch_override` object in the registry entry and the report, with no version bump: D3, D4. Where it is carried and built, and its registry violation codes: D9 (appended by this plan).
- Refusals reuse the closed codes; the operand without `--register`: D5. A repeated operand, and where both checks sit: D8 (appended by this plan).
- The unresolved-default message: D6.
- The stale-default fixture and the seams: D7. How the fixture is built, where the new cases live, and the two substitutions the fixture forces: D10 (appended by this plan).

---

## Standards review provenance

Reviewer: Codex (`codex-plan-review`), isolated read-only mode, no fallback, no focus. Base SHA 96174d0ec1a6b4f507059bdcdff56f5532442bbf. Findings: 0 blocking, 2 should-fix, 0 discussion; 2 accepted, 0 rejected, 0 deferred. PR-01 (Task 2): the unlisted-branch tracking-ref assertion moved inside its own subtest and no longer claims that no fetch was attempted. PR-02 (Task 1): the two remaining "identity and a location and nothing else" prose sites are reworded. Neither is a ledger-level decision.
