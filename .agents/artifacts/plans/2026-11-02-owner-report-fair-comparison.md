# Owner Report Fair Comparison Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `just agent-costs --report owners` selects lineages by when they started, counts each one's whole spend and its deliveries from the same calls once it has settled, adds keepalive ping spend from the cache proxy's log, and prints per-project rows, owner $ per lineage and a baseline-against-candidate comparison with its ratios.

**Architecture:** `agent_owner_report.collect` gains start windows, a settle period and a ping log (per D13). It scans every transcript, gives each lineage a project and a start (per D2, D4), keeps the settled lineages whose start lies in a window (per D1–D3), and attributes the pings that the new `agent_tools.keepalive_pings` reads and prices to them by conversation handle (per D5, D6, D12). The new `agent_tools.agent_owner_rollup` holds the one aggregate behind the arm, project and comparison rows (per D7, D9). `agent_costs` only adds and checks flags. The `agent-owner-report` document becomes `schema_version` 2 (per D8), and `python/README.md` § agent-costs carries the contract, edited by each task for its own change.

**Tech stack:** Python 3 standard library (`argparse`, `dataclasses`, `json`, `statistics`, `subprocess`, `unittest`), Just, Nix.

Spec: `.agents/artifacts/specs/2026-11-02-owner-report-fair-comparison-design.md`. A bare "Dn" cites its `## Decision ledger`, and "#432 Dn" cites `2026-10-25-issue-432-owner-handoff-economics-design.md`. Issue: https://github.com/fagenorn/nix-config/issues/503.

## Global Constraints

- Base `4e944cb4` (`origin/main` at planning). Spec commits `ef8cbcf7` and `0ab7ab27`, plus the planning commit that appends D12 and D13.
- Standard library only: `python/pyproject.toml` keeps `dependencies = []`. New code is a module of `agent_tools` under `python/`, and `agent_costs` stays a thin shell over importable functions (docs/standards/agent-helpers.md rules 1–3).
- Not edited: `python/agent_tools/agent_owner_replay.py`, `agent_boot_report.py`, `cache_keepalive.py`, `cache_proxy.py`, `model_pricing.py`, any `.nix` file, the `justfile`, `CLAUDE.md`, `AGENTS.md`, `home/common/claude-code/README.md`. `collect`'s existing callers call it unchanged (D13).
- Every existing test in `tests/test_agent_owner_report.py`, `tests/test_agent_owner_replay.py` and `tests/test_agent_boot_report.py` stays byte-for-byte as it is and keeps passing. New tests go into `tests/test_agent_owner_report.py` only (D11).
- One home per helper, never a copy: `conversation_handle` from `agent_tools.cache_keepalive`; `repo_root`, `project_name`, `parse_rfc3339_utc`, `format_rfc3339_utc`, `event_in_window` and `percentile` from `agent_tools.agent_costs`; `usage_cost` from `agent_tools.model_pricing`.
- Lineage rows keep `owner_dollars` and `total_dollars` calls-only, because the replay's identity check reads `total_dollars` (D6).
- Comments, docstrings and README sentences describe the code as it behaves at the task's commit, never a later task's. No `TODO` or `FIXME`. Code prose and the README cite this spec as `issue 503 Dn`, never a bare `Dn`.
- The contract is `python/README.md` § agent-costs, the **Owner report (issue 432)** paragraph and its italic sub-paragraphs (*Owner.*, *Lineage and descendants.*, *Delivered.*, *Calls and phases.*, *Eval grouping.*, *Document.*, *Replay (issue 432).*). Each task edits the sentences its change falsifies and adds its own in the section's style. Every number, key and message it states is read from the code at that commit.
- Run every long command, each test command included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout. Commit through `launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <git commit args>`. Commits are SSH-signed and end with the session's trailer lines. Scratch files go under the root that `launch-scope scratch` prints. Never run `just switch`, and never push.
- **Owner tests** (timeout 300 s, about 10 s; at base they end `Ran 15 tests` and `OK`). Append `-k <pattern>` to focus:

  ```bash
  bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests.test_agent_owner_report 2>&1 | tail -4'
  ```

- **Neighbour tests** (timeout 300 s; at base `Ran 48 tests`, `OK`). They must stay green after every task that touches `agent_owner_report.py` or `transcript_calls.py`:

  ```bash
  bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests.test_agent_owner_replay tests.test_agent_boot_report 2>&1 | tail -4'
  ```

- Final gate (sdd runs it once, on the final head): `just build` and `just agent-workflow-tests`, timeout 3600 s each. No task runs `just build`. Its only check of `python/` is an import of every module, and each task's tests already import every module the task touches through `agent_costs`.

## Test seams

- `report(root, *extra)` in `tests/test_agent_owner_report.py` runs `python -m agent_tools.agent_costs --report owners --format json --days 0 --projects-dir <root>` as a subprocess and asserts exit 0 (#432 D17, D11).
- Fixtures from `tests/owner_transcripts.py`: `Session` (gains `cwd`, D13), `progress` (gains `repo_root`), and the ping-log lines `ping_line`, `request_line` and `STDERR_LINE`, whose handles come from `cache_keepalive.conversation_handle` (D11). Expected dollars come from `cost`, and `ping_cost` builds on it.
- Usage errors go through `run(root, *argv)`, which does not check the exit status: exit 2, empty stdout and no argparse `unrecognized arguments`, in the pattern of `test_owners_report_refuses_foreign_flags`.
- Text output goes through `text(root, *extra)` and asserts headings and line prefixes only.

## Delivery estimate and boundaries

All figures are estimates. While planning, the calls-only arithmetic of every new fixture (owner and total dollars, deliveries, peaks, the replay's identity check) was checked against the base report. Eight changed files: `agent_owner_report.py` about +240/−25, `agent_owner_rollup.py` new (about 100 lines), `keepalive_pings.py` new (about 60), `agent_costs.py` about +50, `transcript_calls.py` about +6, `tests/owner_transcripts.py` about +40, `tests/test_agent_owner_report.py` about +470, and `python/README.md` about +10 KB rewritten in place. That is about 950 lines in all, beyond the issue's 400–700 guess. The growth is mostly hand-computed test rows. If one review package cannot hold it, the independently deliverable slices are Tasks 1–3 (project rows, matched deliveries), Tasks 4–5 (start mode and comparison), Task 6 (pings) and Task 7 (document version and text). Each leaves the README true at its commit.

## Task index

Task 1 — Lineage project and start — `python/agent_tools/transcript_calls.py`, `python/agent_tools/agent_owner_report.py`, `tests/owner_transcripts.py`, `tests/test_agent_owner_report.py`, `python/README.md` — full — [task-1.md](2026-11-02-owner-report-fair-comparison.tasks/task-1.md)

Task 2 — Deliveries come from counted calls — `python/agent_tools/agent_owner_report.py`, `tests/test_agent_owner_report.py`, `python/README.md` — full — [task-2.md](2026-11-02-owner-report-fair-comparison.tasks/task-2.md)

Task 3 — One aggregate for arm and project rows — `python/agent_tools/agent_owner_rollup.py`, `python/agent_tools/agent_owner_report.py`, `tests/test_agent_owner_report.py`, `python/README.md` — full — [task-3.md](2026-11-02-owner-report-fair-comparison.tasks/task-3.md)

Task 4 — Start mode with a settle period — `python/agent_tools/agent_owner_report.py`, `python/agent_tools/agent_costs.py`, `tests/test_agent_owner_report.py`, `python/README.md` — full — [task-4.md](2026-11-02-owner-report-fair-comparison.tasks/task-4.md)

Task 5 — Baseline-against-candidate comparison — `python/agent_tools/agent_owner_rollup.py`, `python/agent_tools/agent_owner_report.py`, `python/agent_tools/agent_costs.py`, `tests/test_agent_owner_report.py`, `python/README.md` — full — [task-5.md](2026-11-02-owner-report-fair-comparison.tasks/task-5.md)

Task 6 — Keepalive ping spend — `python/agent_tools/keepalive_pings.py`, `python/agent_tools/agent_owner_report.py`, `python/agent_tools/agent_costs.py`, `tests/owner_transcripts.py`, `tests/test_agent_owner_report.py`, `python/README.md` — full — [task-6.md](2026-11-02-owner-report-fair-comparison.tasks/task-6.md)

Task 7 — Document version 2 and text output — `python/agent_tools/agent_owner_report.py`, `python/agent_tools/agent_costs.py`, `tests/test_agent_owner_report.py`, `python/README.md` — full — [task-7.md](2026-11-02-owner-report-fair-comparison.tasks/task-7.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 4 | `tests/test_agent_owner_report.py::OwnerReportTest::test_a_start_window_counts_whole_settled_lineages_that_started_inside_it`. A lineage that starts in the window counts every call, including those after the window. One that started before it is left out despite delivering inside it. One younger than the settle period is left out and listed as unsettled. It runs with `::test_settle_days_zero_counts_the_young_lineage_too` and Task 2's `::test_an_event_window_clips_deliveries_with_the_spend`. Each fails at its task's start commit (Step 2), and `just agent-workflow-tests` runs them green at the final gate. |
| AC2 | code | Task 6 | `::test_pings_are_priced_and_attributed_or_unattributed_within_the_event_window` and `::test_a_left_out_lineage_s_pings_are_neither_attributed_nor_unattributed` cover ping pricing and attribution. Task 5's `::test_a_two_window_comparison_by_arm_and_project` and `::test_a_window_with_no_lineage_keeps_an_arm_row_with_n_0` cover the hand-computed per-project and two-window output. Each fails at its task's start commit, and `just agent-workflow-tests` runs them green at the final gate. |

## Decisions

The plan rests on D1 (start mode and its range grammar), D2 (start, report end and settle), D3 (one call set for spend and deliveries), D4 (project), D5 and D6 (ping input and attribution), D7 (arms, aggregate and comparison), D8 (schema version 2), D9 (modules), D10 (one root per run) and D11 (the subprocess seam and production-shaped fixtures). Planning appends D12 (how pings and left-out lineages are counted) and D13 (`collect`'s new keywords, project read order in an event window, `print_document`'s eval flag, and which fixture records carry a `cwd`). Phase 5 appends D14 (event mode's `started` and a dropped event-mode lineage's pings).

## Standards review provenance

Reviewer: Codex (`codex-plan-review`, gpt-6-astra, xhigh), isolated read-only mode, no focus, base SHA 4e944cb4639ee99c39a8b640ecc878838e16838c, no fallback. Findings: 3 accepted, 0 rejected, 0 deferred. PR-01 (Blocking): Task 1's claim that `started` is the same with and without an event window was false, because event mode passes the event start as the mtime cutoff; Task 1 now states the event-mode limit, per D14 (start mode already reads every transcript, per D1, so AC1 is unaffected). PR-02 (Should fix): Task 6's left-out test adds an owner ping after the start window and asserts it counts in full. PR-03 (Discussion): Task 6 states that a dropped event-mode lineage's in-window pings are unattributed, per D14.

---

## Review feasibility delivery

```json
{"actual_evidence":{"head":"426de6202428623e78ebd656cd1e04d99b14a4ab","kind":"git-range-ownership/v1","process_ranges":[{"base":"4e944cb4639ee99c39a8b640ecc878838e16838c","boundaries":["all"],"head":"30d3a6c94b7b56dc0a96102c5c926bdd1ef08fc1"}],"tree":"72017e5bbf35d1c1ae7c4c31c733b8e5315f71cc"},"boundaries":[{"acceptance":"Issue 503 complete: AC1 and AC2 green under just agent-workflow-tests","depends_on":[],"id":"all","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64],"process_forecast_ids":["s","p","t1","t2","t3","t4","t5","t6","t7"],"process_package":{"plan":".agents/artifacts/plans/2026-11-02-owner-report-fair-comparison.md","spec":".agents/artifacts/specs/2026-11-02-owner-report-fair-comparison-design.md","tasks":[".agents/artifacts/plans/2026-11-02-owner-report-fair-comparison.tasks/task-1.md",".agents/artifacts/plans/2026-11-02-owner-report-fair-comparison.tasks/task-2.md",".agents/artifacts/plans/2026-11-02-owner-report-fair-comparison.tasks/task-3.md",".agents/artifacts/plans/2026-11-02-owner-report-fair-comparison.tasks/task-4.md",".agents/artifacts/plans/2026-11-02-owner-report-fair-comparison.tasks/task-5.md",".agents/artifacts/plans/2026-11-02-owner-report-fair-comparison.tasks/task-6.md",".agents/artifacts/plans/2026-11-02-owner-report-fair-comparison.tasks/task-7.md"]},"tasks":[1,2,3,4,5,6,7]}],"delivery_base":"4e944cb4639ee99c39a8b640ecc878838e16838c","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":460,"boundary":"all","deleted_lines":0,"record_bytes":36864,"support":{"covers":["s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"s","last_task":7,"owner":0,"path":".agents/artifacts/specs/2026-11-02-owner-report-fair-comparison-design.md"},{"bounds":[{"added_lines":120,"boundary":"all","deleted_lines":0,"record_bytes":20480,"support":{"covers":["p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-owner-report-fair-comparison.md"},{"bounds":[{"added_lines":160,"boundary":"all","deleted_lines":0,"record_bytes":16384,"support":{"covers":["t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-owner-report-fair-comparison.tasks/task-1.md"},{"bounds":[{"added_lines":90,"boundary":"all","deleted_lines":0,"record_bytes":8192,"support":{"covers":["t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-owner-report-fair-comparison.tasks/task-2.md"},{"bounds":[{"added_lines":140,"boundary":"all","deleted_lines":0,"record_bytes":14336,"support":{"covers":["t3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-owner-report-fair-comparison.tasks/task-3.md"},{"bounds":[{"added_lines":230,"boundary":"all","deleted_lines":0,"record_bytes":20480,"support":{"covers":["t4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t4","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-owner-report-fair-comparison.tasks/task-4.md"},{"bounds":[{"added_lines":230,"boundary":"all","deleted_lines":0,"record_bytes":20480,"support":{"covers":["t5"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t5","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-owner-report-fair-comparison.tasks/task-5.md"},{"bounds":[{"added_lines":310,"boundary":"all","deleted_lines":0,"record_bytes":24576,"support":{"covers":["t6"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t6","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-owner-report-fair-comparison.tasks/task-6.md"},{"bounds":[{"added_lines":170,"boundary":"all","deleted_lines":0,"record_bytes":14336,"support":{"covers":["t7"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t7","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-owner-report-fair-comparison.tasks/task-7.md"}],"proposed_boundary":"all","schema_version":3}
```
