# Agent-Costs Cache Report Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `agent-costs --report cache` reports cache deaths by agent type and cause, the reread cost of context above a threshold with peak-context percentiles, and subagent start-up overhead over an event-time window, and the Opus-class list price becomes $5 input / $25 output per Mtok.

**Architecture:** `agent_costs` keeps its argv shell and gains one shared write-split function and the corrected `PRICING` row (Task 1). A new module, `agent_tools.agent_cache_report`, owns the per-transcript scanner (Task 2) and the aggregation and printing of the three tables. `agent_costs.main` validates the new flags, then imports the module inside its `--report cache` branch and hands it the window, threshold, row cap, transcript root and executor factory (Task 3). Task 4 runs the report over the real store on mbp and records the AC4 evidence.

**Tech stack:** Python 3.13 standard library (`json`, `dataclasses`, `datetime`, `functools.partial`, `concurrent.futures` through `agent_costs.scan_paths`), `unittest` with fixtures built in temp dirs, Just, Nix (`just build` import-checks every package module).

Spec: `.agents/artifacts/specs/2026-10-24-issue-421-cache-report-design.md` (designed at `c42d2e66`; this plan appends ledger rows D12–D14). Its `## Decision ledger` rows are cited by ID. Issue: https://github.com/fagenorn/nix-config/issues/421.

## Global Constraints

- Base `7601d318` (`origin/main` at planning). Tasks land in index order, each on the one before it.
- Python standard library only. No Nix change (`lib/agent-tools.nix` import-checks the new module by walking the tree), no command-table row (`agent-costs` stays a `just` recipe), no `justfile` change, no `CLAUDE.md` change.
- `SCHEMA_VERSION` stays `1`; the `agent-cost-record` shape and `python/agent_tools/agent_model_drift_schema.py` are unchanged (D9).
- The default (`--report issues`) stdout stays byte-identical: `tests/fixtures/agent_costs_text_golden.txt` and `TextByteIdentityTest` are not edited.
- `agent_cache_report` imports `PRICING`, `model_family`, `cache_write_split`, `find_sessions`, `scan_paths`, `event_in_window`, `parse_rfc3339_utc`, `percentile`, `human`, `print_table` and `DISCLAIMER` from `agent_tools.agent_costs` and copies none of them (D2). `agent_costs` imports `agent_cache_report` only inside its `--report cache` branch.
- No `sys.path` edit, `importlib` load or `__file__` lookup; the parser's `prog` stays `agent-costs` (`docs/standards/agent-helpers.md` rules 2, 3).
- Comments, docstrings and README sentences describe the code as it behaves at that task's commit; write "issue 421", never a bare `#421`, in code and docs; no `TODO` or `FIXME`; no mutable default argument.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration. Commits go through `launch-commit … -- <git commit args>`, signed, ending with the session's trailers. Scratch files live under `launch-scope scratch`'s root. Never run `just switch`.
- **Focused test run** (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_agent_costs.py <-k pattern>... 2>&1 | tail -4'`. Without `-k` it runs the whole module (89 tests at base).
- **Build** (timeout 3600 s): `bash -c 'set -o pipefail; just build 2>&1 | tail -3'`; it fails when a package module does not import.
- Final gate (sdd, once on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each).

## Test seams

- The per-transcript scanner, `agent_cache_report.scan_transcript((path, is_root), since=…, before=…, threshold=…)`, called directly on production-shaped fixture files: attachment records with `rendered` lists, `origin` objects with `handback: true`, `toolEndsTurn` results, sibling `.meta.json` files (D10).
- The command: `agent_costs.main` through the existing `run_main` helper over a fixture tree, plus one `python -m agent_tools.agent_costs --report cache` run through a real process pool (D14).
- Pricing through `agent_costs.scan_file` cost, as `test_cost_uses_model_family_pricing` does; `EndToEndTest`'s cost assertion moves with the row.
- Unchanged default output: `TextByteIdentityTest`, unmodified.
- The real store, for AC4 only (Task 4).

## Delivery estimate and boundaries

Estimates only: four changed files plus the acceptance record, this plan and the spec ledger. `python/agent_tools/agent_costs.py` about +70/−15 lines (1986 → about 2040); the new `python/agent_tools/agent_cache_report.py` about 330 lines; `tests/test_agent_costs.py` about +480 lines (1669 → about 2150); `python/README.md` one new section of five paragraphs. One review package. If a package boundary demands a split, Task 1 (the price row, AC3) is independently deliverable from Tasks 2–4.

## Task index

Task 1 — Opus-class list price and the shared write-split rule — `python/agent_tools/agent_costs.py`, `tests/test_agent_costs.py`, `python/README.md` — full — [task-1.md](2026-10-24-issue-421-cache-report.tasks/task-1.md)
Task 2 — The per-transcript cache scanner: calls, window, deaths, reread, start-up — `python/agent_tools/agent_cache_report.py`, `tests/test_agent_costs.py` — full — [task-2.md](2026-10-24-issue-421-cache-report.tasks/task-2.md)
Task 3 — `--report cache`: flags, aggregation, the three tables and the contract docs — `python/agent_tools/agent_costs.py`, `python/agent_tools/agent_cache_report.py`, `tests/test_agent_costs.py`, `python/README.md` — full — [task-3.md](2026-10-24-issue-421-cache-report.tasks/task-3.md)
Task 4 — AC4 evidence over the real store and the acceptance record — `.agents/artifacts/plans/2026-10-24-issue-421-cache-report.acceptance.md` — low-risk — [task-4.md](2026-10-24-issue-421-cache-report.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 2 | `tests/test_agent_costs.py::CacheScanTest::test_a_hand_back_after_end_of_turn_is_one_death_with_its_premium` (one death of kind `hand-back after end of turn`, gap 542 s, premium `32,002 × (6.25 − 0.50) / 1e6`), run by `just agent-workflow-tests` in sdd's final gate. |
| AC2 | code | Task 2 | `CacheScanTest::test_only_reads_past_the_threshold_are_priced` (calls below, at and above 120k; only the reads past it priced) and `CacheScanTest::test_first_call_and_attachments_before_the_second_call_are_the_start_up` (first write/read and each attachment's characters, a later attachment excluded), same module and gate. |
| AC3 | code | Task 1 | `ScanFileTest::test_opus_class_list_price_is_five_and_twenty_five_per_mtok` (expects $53.00 for the fixture; the $15 row yields $159.00), same module and gate. |
| AC4 | evidence | Task 4 | On mbp at the final code head: `just agent-costs --report cache --events-since 2026-10-10T00:00:00Z --events-before 2026-10-24T21:40:00Z` over `~/.claude/projects`; thresholds: the totals line's `Subagent deaths` within ±15 % of 2,646 (2,250–3,042) and the `general-purpose` row's `reread above` cell within ±15 % of $2,200 ($1,870–$2,530). Acceptance-record row `AC4`; never tuned toward the target (D11). |

## Decisions

- The command surface and its usage errors per D1; the module boundary and the shared write-split function per D2 (Tasks 1, 3).
- The window per D3; calls, TTL and agent type per D4; the read pass, cause span, window test and attachment cut-off per D12 (Task 2).
- Cause kinds per D5, premium per D6, reread and peaks per D7, start-up attachments per D8 (Task 2).
- The price row, no version bump and the documented non-comparability per D9 (Task 1).
- Test seams per D10, with the `-m` pool run per D14 (Tasks 1–3).
- Result shape, exits, header count, table order, `-` cells and the drop note per D13 (Tasks 2, 3).
- The evidence window and the no-tuning rule per D11; its record per D14 (Task 4).
