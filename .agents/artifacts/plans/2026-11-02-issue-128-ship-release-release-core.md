# Ship-release on the Release Core Implementation Plan

> **For agentic workers:** execute with the `sdd` skill, one implementer per task, reviewed
> between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `ship-release` becomes a thin client of the release core through a new
`release transaction status|preview|run|abandon` area, as #128's three review packages on
one branch.

**Architecture:** `python/agent_tools/` gains `release_verification` (CI receipt),
`release_driver` (selection to status) and `release_cutover` (legacy state), behind one new
`release` area (D3). The driver composes only `TransactionStore`, `compile_profile`,
`bind_candidate` and `core_binding`; the skill keeps preparation and narrative (D9).

**Tech stack:** Python 3 standard library, `unittest`, Just, Markdown skills.

Spec: `.agents/artifacts/specs/2026-11-02-issue-128-ship-release-release-core-design.md`, the
source of truth. "§n" cites its `## Decisions`, "Dn" its ledger; planning added D18–D26 and
the standards review D27–D29.

## Global Constraints

- Standard library only. Never edit `python/agent_tools/transaction_*.py`, `forge_adapter.py`,
  `release_adapter.py`, `release_profile.py`, `.agents/project.json`, `lib/agent-tools.nix`,
  the lifecycle guard, `CLAUDE.md` or `AGENTS.md` (D2, D3, §9).
- `docs/standards/agent-helpers.md`: no `sys.path` edits or `__file__` lookups; digests only
  through `agent_tools.canonical.telemetry_digest`. Command tests run
  `[sys.executable, "-m", "agent_tools.release", ...]`.
- Output is one document through `resolve_project.emit_json`. A driver refusal is
  `{"error":{"code","repair_id","detail"}}`, exit 3; a resolver refusal stays byte for byte,
  exit 2 (D18).
- Shared constants, verbatim:
  - store root `<common dir>/agent-release/store`, both directories `0o700`, created only by
    `run`; creation key `release/v1:<project id>:<profile id>:<n>`, `n` from 1;
  - custody executor `release-driver`, TTL `900000` ms;
  - authority: transaction `release`; per-token grants `release-irreversible`; scope grant
    `release-scope`, id `release-scope:<acquisition ordinal>`; every grant actor `operator`,
    kind `human`;
  - verification receipt schema `release-verification/v1`, one 30-second budget,
    `GITHUB_TOKEN` and `GH_TOKEN` removed from the child environment.
- Never release custody in a `finally` (D21).
- A task creating a test file adds it to `justfile`'s `agent-workflow-tests` list beside
  `tests/test_release_command.py`, in that task's commit.
- Suite form, from the worktree root:
  `PYTHONPATH=python python3 -m agent_tools.suite_runner <files> 2>&1 | tail -4`; one test:
  `PYTHONPATH=python python3 -m unittest tests.<module>.<Class>.<test> 2>&1 | tail -4`.
- Commits are SSH-signed, subject `feat(issue-128/T<n>): …`, ending with the session's
  attribution trailer.
- Package check (D23), from the worktree root, must exit 0:

```bash
set -euo pipefail
BASE="$(git log --reverse --format=%H -F --grep='feat(issue-128/<first>):' | head -1)"
test -n "$BASE"
OUT="$(mktemp -d "${TMPDIR:-/tmp}/rp-XXXXXX")/review.json"
review-package .agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.md \
  "$(git rev-parse "$BASE^")" "$(git rev-parse HEAD)" "$OUT" > "$OUT.report"
grep -q '"state":"complete"' "$OUT.report"
```

## Test seams

The spec's `## Test seams`; a task needing another is a plan bug.

1. The `release` command from source with `tests/forge_world.py`'s fakes on `PATH` (D12).
2. The driver on the real `TransactionStore`, injecting registry, clock and common dir (D20).
3. The crash matrix: a registry entry raises after its mutation; the clock passes the TTL.
4. The skill contract, `test_ship_release_contracts.py`.
5. Measurement: `instruction_load` and `agent_gate_bundle`.

## Delivery estimate and boundaries

Rationale only; the numbers are in the forecast blocks (D29).

- `all` (Tasks 1–8) is the one boundary: the three packages share one branch, so its
  projection is the pre-dispatch gate.
- P1 (1–4) alone leaves the old skill beside a dormant command, P2 (5) adds proof only, and
  P3 (6–8) is the cutover. Each package's last task runs `review-package` (D23, D29).
- Bounds are padded: `README.md`'s long lines inflate records; Task 6's driver bound covers a
  conditional Task 5 fix.

## Task index

Task 1 — Verification receipt — `python/agent_tools/release_verification.py`, `tests/forge_world.py`, `tests/test_release_verification.py`, `justfile` — full — [task-1.md](2026-11-02-issue-128-ship-release-release-core.tasks/task-1.md)

Task 2 — Driver read side — `python/agent_tools/release_driver.py`, `tests/release_driver_support.py`, `tests/test_release_driver.py`, `justfile` — full — [task-2.md](2026-11-02-issue-128-ship-release-release-core.tasks/task-2.md)

Task 3 — Driver `run` and `abandon` — `python/agent_tools/release_driver.py`, `tests/release_driver_support.py`, `tests/test_release_driver.py` — full — [task-3.md](2026-11-02-issue-128-ship-release-release-core.tasks/task-3.md)

Task 4 — Command, README, P1 feasibility — `python/agent_tools/release.py`, `tests/test_release_command.py`, `python/README.md`, `python/agent_tools/actions_health_adapter.py` — full — [task-4.md](2026-11-02-issue-128-ship-release-release-core.tasks/task-4.md)

Task 5 — Crash matrix, P2 feasibility — `tests/release_driver_support.py`, `tests/test_release_crash_matrix.py`, `python/agent_tools/release_driver.py`, `justfile` — full — [task-5.md](2026-11-02-issue-128-ship-release-release-core.tasks/task-5.md)

Task 6 — Legacy cutover — `python/agent_tools/release_cutover.py`, `python/agent_tools/release_driver.py`, `tests/test_release_cutover.py`, `tests/test_release_command.py`, `python/README.md`, `justfile` — full — [task-6.md](2026-11-02-issue-128-ship-release-release-core.tasks/task-6.md)

Task 7 — Skill rewrite — ship-release `SKILL.md`, `CHANGELOG.md`, `evals/evals.json`; agent-skills `tests/test_ship_release_contracts.py`, `tests/test_workflow_skill_contracts.py`, `instruction-load.json` — full — [task-7.md](2026-11-02-issue-128-ship-release-release-core.tasks/task-7.md)

Task 8 — Evidence, measurement, demo, P3 feasibility — `.agents/artifacts/evidence/release-128-trials.json`, `.agents/artifacts/evidence/release-128-bundle.json`, `tests/test_release_evidence.py`, `justfile` — full — [task-8.md](2026-11-02-issue-128-ship-release-release-core.tasks/task-8.md)

## Acceptance map

Issue order (six, then four additional); kinds classified per the spec's mapping.

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | 7 | `test_ship_release_contracts.py`: `test_skill_names_no_legacy_state`, `test_release_examples_parse_and_cover_every_subcommand`; `test_release_command.py`: `TransactionCommandTest.test_status_shows_a_nonterminal_release` (Task 4) |
| AC2 | code | 4 | `test_release_command.py`: `TransactionCommandTest.test_preview_names_tag_and_release`, `test_run_without_every_current_token_writes_nothing` |
| AC3 | code | 5 | `test_release_crash_matrix.py`: `CrashMatrixTest.test_merge_done_tag_interrupted_resumes_without_remerge_or_retag` (fixture merge, D2) |
| AC4 | code | 3 | `test_release_driver.py`: `RunRefusalTest.test_red_or_pending_ci_reserves_no_version`, `AbandonTest.test_guard_denied_first_action_abandons_and_frees_the_version` |
| AC5 | human | 8 | Evidence: `instruction_load report --base 0a25b8072c8252d069774f68e75981c39c137691 --head <last commit touching ship-release/SKILL.md or CHANGELOG.md> --format json`; hot head bytes ≤ 17,698 for `ship-release` and `release-owner`, both hosts; row `AC5`. Approval needs the owner's live trials (D11), so the row stays `human_pending` and the issue is held |
| AC6 | code | 6 | `test_release_cutover.py`: `ClassifyTest` (four classes); `test_release_command.py`: `LegacyCommandTest.test_in_flight_and_unreadable_refuse_and_touch_nothing` |
| AC7 | code | 4 | AC2's tests; `test_release_driver.py`: `RunTest.test_actions_run_in_bind_candidate_order_with_its_parameters`; Task 4 Step 6 |
| AC8 | code | 5 | `test_release_crash_matrix.py`: `CrashMatrixTest`, one case per arm (merge, tag, Release, deploy), and `test_each_postcondition_is_inspected_before_the_next_action` |
| AC9 | evidence | 8 | AC6's tests plus AC5's command and threshold; row `AC9` |
| AC10 | evidence | 8 | `review-feasibility gate` before dispatch, then `review-package` `"state":"complete"` for P1 (Task 4), P2 (Task 5), P3 (Task 8) (D23, D29). Divergences 1–3 and 5 in `test_release_driver.py` (Task 3), 4 in `test_release_command.py` (Task 4), 6 in `test_release_crash_matrix.py` (Task 5), 7–8 in `test_release_profile.py` and `test_release_grammar.py` (Task 8); row `AC10` |

## Decisions

| Decisions | Tasks |
|---|---|
| D1, D13, D26 (shapes, selection, no anchors) | 2 |
| D2, D12, D20, D21, D27 (no forge merge, crash seam, router, custody, proof pass) | 3, 5 |
| D3, D18, D19 (one area, refusals, gate 1) | 2, 4 |
| D4, D14, D16 (store, key, reservation, abandon) | 2, 3 |
| D5, D22 (receipt, verification reads) | 1, 3 |
| D6, D7, D17, D25 (tokens, one pass, stable tokens, status reason) | 2, 3, 7 |
| D8 (legacy) | 6 |
| D9, D10, D28 (skill, measurement, pre-flight order) | 7 |
| D11, D23, D24, D29 (evidence, feasibility, forecast) | 4, 5, 8 |

## Standards review provenance

Reviewer `Codex` (gpt-6-astra, xhigh, `codex-companion task --fresh --reviewer plan-review`),
base `0a25b8072c8252d069774f68e75981c39c137691`, isolated read-only, no fallback, no focus:
5 accepted, 0 rejected, 0 deferred. PR128-01 → D27, PR128-02 → D29, PR128-03 → D28;
PR128-04 and PR128-05 (Task 4) need no row.

## Review feasibility delivery

```json
{"actual_evidence":{"head":"0a25b8072c8252d069774f68e75981c39c137691","kind":"git-range-ownership/v1","process_ranges":[],"tree":"56422e095b8badeb215c858e36c9a19894d56a76"},"boundaries":[{"acceptance":"Issue 128 complete: ship-release is a release-core client","depends_on":[],"id":"all","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64,64,64,64,64],"process_forecast_ids":["s","p","t1","t2","t3","t4","t5","t6","t7","t8"],"process_package":{"plan":".agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.md","spec":".agents/artifacts/specs/2026-11-02-issue-128-ship-release-release-core-design.md","tasks":[".agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.tasks/task-1.md",".agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.tasks/task-2.md",".agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.tasks/task-3.md",".agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.tasks/task-4.md",".agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.tasks/task-5.md",".agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.tasks/task-6.md",".agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.tasks/task-7.md",".agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.tasks/task-8.md"]},"tasks":[1,2,3,4,5,6,7,8]}],"delivery_base":"0a25b8072c8252d069774f68e75981c39c137691","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":629,"boundary":"all","deleted_lines":0,"record_bytes":57344,"support":{"covers":["s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"s","last_task":8,"owner":0,"path":".agents/artifacts/specs/2026-11-02-issue-128-ship-release-release-core-design.md"},{"bounds":[{"added_lines":173,"boundary":"all","deleted_lines":0,"record_bytes":37888,"support":{"covers":["p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.md"},{"bounds":[{"added_lines":297,"boundary":"all","deleted_lines":0,"record_bytes":22528,"support":{"covers":["t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.tasks/task-1.md"},{"bounds":[{"added_lines":519,"boundary":"all","deleted_lines":0,"record_bytes":33792,"support":{"covers":["t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.tasks/task-2.md"},{"bounds":[{"added_lines":426,"boundary":"all","deleted_lines":0,"record_bytes":28672,"support":{"covers":["t3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.tasks/task-3.md"},{"bounds":[{"added_lines":260,"boundary":"all","deleted_lines":0,"record_bytes":20480,"support":{"covers":["t4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t4","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.tasks/task-4.md"},{"bounds":[{"added_lines":308,"boundary":"all","deleted_lines":0,"record_bytes":22528,"support":{"covers":["t5"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t5","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.tasks/task-5.md"},{"bounds":[{"added_lines":286,"boundary":"all","deleted_lines":0,"record_bytes":20480,"support":{"covers":["t6"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t6","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.tasks/task-6.md"},{"bounds":[{"added_lines":260,"boundary":"all","deleted_lines":0,"record_bytes":21504,"support":{"covers":["t7"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t7","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.tasks/task-7.md"},{"bounds":[{"added_lines":197,"boundary":"all","deleted_lines":0,"record_bytes":16384,"support":{"covers":["t8"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t8","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.tasks/task-8.md"}],"proposed_boundary":"all","schema_version":3}
```
