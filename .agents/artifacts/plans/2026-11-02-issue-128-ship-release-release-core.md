# Ship-release on the Release Core Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Make `ship-release` a thin client of the shipped release core through a new
`release transaction status|preview|run|abandon` area, delivered as #128's three review
packages on one branch.

**Architecture:** Three standard-library modules in `python/agent_tools/`:
`release_verification` (the candidate's required-CI receipt), `release_driver` (selection,
gates, store, preview, tokens, run, abandon, status) and `release_cutover` (the legacy
state file). They sit behind one new area of the existing `release` command (D3). The
driver composes only the shipped `TransactionStore`, `compile_profile`, `bind_candidate`
and `core_binding`. The skill keeps preparation and narrative (D9).

**Tech stack:** Python 3 standard library, `unittest`, Just, Markdown skills.

The design spec is `.agents/artifacts/specs/2026-11-02-issue-128-ship-release-release-core-design.md`.
It is the source of truth: "§n" cites its `## Decisions` sections and "Dn" its
`## Decision ledger`. This plan appended D18–D26.

## Global Constraints

- Standard library only. No edit to `python/agent_tools/transaction_*.py`,
  `forge_adapter.py`, `release_adapter.py`, `release_profile.py`, `.agents/project.json`,
  `lib/agent-tools.nix`, the lifecycle guard, `CLAUDE.md` or `AGENTS.md` (D2, D3, §9).
- `docs/standards/agent-helpers.md`: no `sys.path` edits, no `__file__` lookups, digests
  only through `agent_tools.canonical.telemetry_digest`. Command tests run
  `[sys.executable, "-m", "agent_tools.release", ...]`.
- Output: one document through `agent_tools.resolve_project.emit_json`. A driver refusal is
  `{"error":{"code","repair_id","detail"}}` with exit 3. A resolver refusal stays byte for
  byte with exit 2 (D18).
- Shared constants, verbatim:
  - store root: `<common dir>/agent-release/store`, both directories mode `0o700`, created
    only by `run`;
  - creation key: `release/v1:<project id>:<profile id>:<n>`, with `n` from 1;
  - custody: executor `release-driver`, TTL `900000` ms;
  - authority: transaction `release`; per-token grants `release-irreversible`; the scope
    grant `release-scope`, id `release-scope:<acquisition ordinal>`. Every grant has actor
    `operator` and actor kind `human`;
  - verification: receipt schema `release-verification/v1`, one 30-second budget, and
    `GITHUB_TOKEN` and `GH_TOKEN` removed from the child environment.
- Per D21, never release custody in a `finally`.
- A task that creates a test file adds it to the `agent-workflow-tests` list in `justfile`
  beside `tests/test_release_command.py`, in that task's commit.
- Focused runs from the worktree root:
  `PYTHONPATH=python python3 -m agent_tools.suite_runner <test file> 2>&1 | tail -4`, or
  `PYTHONPATH=python python3 -m unittest tests.<module>.<Class>.<test> 2>&1 | tail -4`.
- Commits are SSH-signed and never unsigned. Subject is `feat(issue-128/T<n>): …`, and each
  ends with the attribution trailer the executing session supplies.

## Test seams

Exactly the spec's `## Test seams`. A task that needs another is a plan bug.

1. The `release` command from source, against a temporary main checkout, with
   `tests/forge_world.py`'s fake `gh`, `git` and guard on `PATH`. The three verification
   reads extend the world, outside the spelling fixture (D12).
2. The driver library against the real `TransactionStore`, injecting the registry, the
   clock and the common dir (D20).
3. The crash matrix: a registry entry wraps an adapter and raises after its provider
   mutation, and the injected clock passes the TTL (D12, D21).
4. The skill contract, `home/common/agent-skills/tests/test_ship_release_contracts.py`.
5. Measurement: `instruction_load report`/`check` and `agent_gate_bundle` over the
   committed manifest.

## Delivery estimate and boundaries

Estimates only.

- **P1 (Tasks 1–4):** about 9 files. `release_driver.py` is about 22 KB and
  `test_release_driver.py` about 24 KB.
- **P2 (Task 5):** about 4 files, about 20 KB of tests and fixtures.
- **P3 (Tasks 6–8):** about 12 files. `SKILL.md` shrinks from 21,321 bytes to under
  9.5 KB, and the deletion diff is the largest single member.

Each package is deliverable alone:

- P1 alone leaves the old skill working beside a dormant command.
- P1+P2 adds proof only.
- P3 is the cutover.

The likeliest growth risks are `release_driver.py` crossing 48 KB and the aggregate P1
diff. Each package's last task runs `review-package` (D23). A `decompose_required` result
splits the offending file before continuing.

## Task index

Task 1 — Verification receipt — `python/agent_tools/release_verification.py`, `tests/forge_world.py`, `tests/test_release_verification.py`, `justfile` — full — [task-1.md](2026-11-02-issue-128-ship-release-release-core.tasks/task-1.md)

Task 2 — Driver read side: selection, gates, store, tokens, status, preview — `python/agent_tools/release_driver.py`, `tests/release_driver_support.py`, `tests/test_release_driver.py`, `justfile` — full — [task-2.md](2026-11-02-issue-128-ship-release-release-core.tasks/task-2.md)

Task 3 — Driver `run` and `abandon` — `python/agent_tools/release_driver.py`, `tests/release_driver_support.py`, `tests/test_release_driver.py` — full — [task-3.md](2026-11-02-issue-128-ship-release-release-core.tasks/task-3.md)

Task 4 — `release transaction` command, README, P1 feasibility — `python/agent_tools/release.py`, `tests/test_release_command.py`, `python/README.md` — full — [task-4.md](2026-11-02-issue-128-ship-release-release-core.tasks/task-4.md)

Task 5 — Crash and retry matrix, P2 feasibility — `tests/release_driver_support.py`, `tests/test_release_crash_matrix.py`, `python/agent_tools/release_driver.py`, `justfile` — full — [task-5.md](2026-11-02-issue-128-ship-release-release-core.tasks/task-5.md)

Task 6 — Legacy cutover — `python/agent_tools/release_cutover.py`, `python/agent_tools/release_driver.py`, `tests/test_release_cutover.py`, `tests/test_release_command.py`, `python/README.md`, `justfile` — full — [task-6.md](2026-11-02-issue-128-ship-release-release-core.tasks/task-6.md)

Task 7 — Skill rewrite, contract, evals, ceilings — `home/common/agent-skills/skills/ship-release/SKILL.md`, `home/common/agent-skills/skills/ship-release/CHANGELOG.md`, `home/common/agent-skills/skills/ship-release/evals/evals.json`, `home/common/agent-skills/tests/test_ship_release_contracts.py`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/instruction-load.json` — full — [task-7.md](2026-11-02-issue-128-ship-release-release-core.tasks/task-7.md)

Task 8 — #70 evidence, measurement, demo, P3 feasibility — `.agents/artifacts/evidence/release-128-trials.json`, `.agents/artifacts/evidence/release-128-bundle.json`, `tests/test_release_evidence.py`, `justfile` — full — [task-8.md](2026-11-02-issue-128-ship-release-release-core.tasks/task-8.md)

## Acceptance map

Criteria in issue order: the six of `## Acceptance criteria`, then the four of
`### Additional acceptance criteria`. The issue tags none, so each kind is classified,
following the spec's `## Acceptance mapping`.

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 7 | `home/common/agent-skills/tests/test_ship_release_contracts.py`: `test_skill_names_no_legacy_state` and `test_release_examples_parse_and_cover_every_subcommand`; plus `tests/test_release_command.py`: `TransactionCommandTest.test_status_shows_a_nonterminal_release` (Task 4) |
| AC2 | code (classified) | Task 4 | `tests/test_release_command.py`: `TransactionCommandTest.test_preview_names_tag_and_release` and `test_run_without_every_current_token_writes_nothing` |
| AC3 | code (classified) | Task 5 | `tests/test_release_crash_matrix.py`: `CrashMatrixTest.test_merge_done_tag_interrupted_resumes_without_remerge_or_retag` (fixture merge arm, per D2) |
| AC4 | code (classified) | Task 3 | `tests/test_release_driver.py`: `RunRefusalTest.test_red_or_pending_ci_reserves_no_version` and `AbandonTest.test_guard_denied_first_action_abandons_and_frees_the_version` |
| AC5 | human (classified) | Task 8 | Evidence half: `instruction_load report --base 0a25b8072c8252d069774f68e75981c39c137691 --head <last commit touching ship-release/SKILL.md or CHANGELOG.md> --format json`, read-only; threshold: hot head bytes ≤ 17,698 for `ship-release` and `release-owner` on both hosts (base 29,498); acceptance-record row `AC5`. Approval half: `approved` needs paired live trials in both strata, run by the owner (D11). The committed bundle reads `unmeasured`, so the row stays `human_pending` and delivery holds the issue open |
| AC6 | code (classified) | Task 6 | `tests/test_release_cutover.py`: `ClassifyTest` (all four classes); `tests/test_release_command.py`: `LegacyCommandTest.test_in_flight_and_unreadable_refuse_and_touch_nothing` |
| AC7 | code (classified) | Task 4 | AC2's tests; `tests/test_release_driver.py`: `RunTest.test_actions_run_in_bind_candidate_order_with_its_parameters`; the P1 `review-package` run in Task 4 Step 6 |
| AC8 | code (classified) | Task 5 | `tests/test_release_crash_matrix.py`: `CrashMatrixTest`, one case per arm (merge, tag, Release, deploy), and `test_each_postcondition_is_inspected_before_the_next_action` |
| AC9 | evidence (classified) | Task 8 | AC6's tests, plus AC5's measurement command and threshold; acceptance-record row `AC9` |
| AC10 | evidence (classified) | Task 8 | `review-package` prints `"state":"complete"` for P1 (Task 4), P2 (Task 5) and P3 (Task 8) (D23). The eight #90 divergences hold as the spec's table checks them: 1–3 and 5 in `tests/test_release_driver.py` (Task 3), 4 in `tests/test_release_command.py` (Task 4), 6 in `tests/test_release_crash_matrix.py` (Task 5), and 7–8 in the existing `tests/test_release_profile.py` and `tests/test_release_grammar.py` (run in Task 8); acceptance-record row `AC10` |

## Decisions

The spec's ledger holds every choice, and this plan appended D18–D26. Task coverage:

| Decisions | Tasks |
|---|---|
| D1, D13, D26 (shapes, selection, no anchors) | 2 |
| D2, D12, D20, D21 (no forge merge, crash seam, router, custody) | 3, 5 |
| D3, D18, D19 (one area, refusals, gate 1) | 2, 4 |
| D4, D14, D16 (store, key, reservation, abandon) | 2, 3 |
| D5, D22 (receipt, verification reads) | 1, 3 |
| D6, D7, D17, D25 (tokens, one pass, stable tokens, status reason) | 2, 3, 7 |
| D8 (legacy) | 6 |
| D9, D10 (skill, measurement) | 7 |
| D11, D23, D24 (evidence, feasibility) | 4, 5, 8 |

---
