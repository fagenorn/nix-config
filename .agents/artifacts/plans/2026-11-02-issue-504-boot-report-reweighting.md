# Boot Report Reweighting, Medians and Sub-totals Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `just agent-costs --report boot --baseline SINCE..BEFORE` reweights the event window's B, with and without tool schemas, to the baseline window's host × phase group × project mix. It prints a median beside every mean and splits each boot into boot reading and first-unit work. A whole-file `cat` followed by a `Read` of the same file now counts as a reread.

**Architecture:** `agent_boot_report` gains extent-aware read keys (per D5) and two sub-totals per boot. It collects each root once per window, giving each boot an arm and its lineage's project (per D1, D2). A new pure module, `agent_tools.agent_boot_rollup`, holds the group rows, the one median function and the reweighting (per D3, D4, D7, D9, D10). `agent_costs` only parses and checks `--baseline` for the boot report. The `agent-boot-report` document becomes `schema_version` 2 (per D6). The contract lives in `python/README.md` § agent-costs, and each task edits it for its own change.

**Tech stack:** Python 3 standard library (`argparse`, `fractions`, `json`, `statistics`, `subprocess`, `unittest`), Just, Nix.

Spec: `.agents/artifacts/specs/2026-11-02-issue-504-boot-report-reweighting-design.md`. A bare "Dn" cites its `## Decision ledger`. Issue: https://github.com/fagenorn/nix-config/issues/504 (parent #448).

## Global Constraints

- Base `328f08da` (`origin/main` at planning). The spec commits are `7011f6a6` and `7c5ed79a`, plus the planning commit that appends D9–D11.
- Standard library only: `python/pyproject.toml` keeps `dependencies = []`. The new module lives under `python/agent_tools/` and is not a command, so it gets no row in `lib/agent-tools.nix`. `agent_costs` stays a thin shell (docs/standards/agent-helpers.md rules 1–3).
- Not edited: `agent_owner_report.py`, `agent_owner_rollup.py`, `agent_owner_replay.py`, `context_meter_commands.py`, `transcript_calls.py`, `tests/owner_transcripts.py`, any `.nix` file, the `justfile`, `CLAUDE.md` and `AGENTS.md`. The owner report and its `--baseline` keep their behaviour.
- One home per name:
  - from `agent_owner_report`: the arm constants `LIVE_ARM`, `BASELINE_ARM` and `CANDIDATE_ARM`, and `StartWindow`, `parse_range`, `start_window_label`, `boot_facts`, `boot_slice`;
  - from `agent_costs`: `human` and `print_table`;
  - in `agent_boot_report`: the bucket and sub-total tuples;
  - in `agent_boot_rollup`: `ALL`, `COHORTS`, `PHASE_GROUPS` and `median` (D9).
- Tests change only in `tests/test_agent_boot_report.py`. Existing tests keep passing. Only Task 3 edits existing lines: the three `unsplit` assertions (D6) and `two_call_boot`'s new `repo_root` keyword.
- Comments, docstrings and README sentences describe the code as of the task's commit, never a later task's, and carry no `TODO` or `FIXME`. Code prose and the README cite `issue 504 Dn`, never a bare `Dn`. A task's README text is checked against the implemented code before commit and corrected to match it.
- The contract is `python/README.md` § agent-costs, in the **Boot report (issue 448)** paragraph and its italic sub-paragraphs. Tasks add *Sub-totals and medians*, *Windows and arms* and *Reweighting*, and Task 3 also edits one clause of the **Owner report** paragraph.
- Run every command in the foreground from the worktree root, with an explicit timeout, as `launch-scope exec --repo-root <ledger repo root> --run-id <run id> --worker-id <worker id> -- <argv>`. Commit through `launch-commit` with the same three options, then `-- <git commit args>`. Commits are SSH-signed, and `<trailer>` is the session's `Co-Authored-By` line. Scratch files go under the root that `launch-scope scratch` prints. Never run `just switch`, and never push.
- **Boot tests** (timeout 300 s, about 10 s; at base `Ran 14 tests`, `OK`). Append `-k <pattern>` to focus:

  ```bash
  bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests.test_agent_boot_report 2>&1 | tail -4'
  ```

- **Owner tests** (timeout 300 s; at base `Ran 70 tests`, `OK`). Run them after any task that touches `agent_costs.py`:

  ```bash
  bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests.test_agent_owner_report tests.test_agent_owner_replay 2>&1 | tail -4'
  ```

- Final gate (sdd runs it once, on the final head): `just build` and `just agent-workflow-tests`, timeout 3600 s each. No task runs either one.

## Test seams

- `report(*roots, extra=())` and `costs(*args)` in `tests/test_agent_boot_report.py` run `python -m agent_tools.agent_costs --report boot` as a subprocess (D8, #448 test seam 1). `report` adds `--format json --days 0` and asserts exit 0.
- Fixtures come from `tests/owner_transcripts.py` (`Session`, `progress(..., repo_root=)`, `gate_reply`) through the file's `opening`, `dispatch`, `two_call_boot` and Task 1's `stepped_boot`. Windows are RFC3339 bounds around `at()` instants, with T0 at 2026-10-25T09:00Z.
- Usage errors expect exit 2 with empty stdout, in the pattern of `test_foreign_flags_are_usage_errors`.
- Text output is checked by heading positions and line regexes only, in the pattern of `test_text_output_prints_its_four_sections_and_footer`.

## Delivery estimate and boundaries

All figures are estimates. Planning ran every fixture's B and buckets through the base report (pair reads, four-boot medians, the two-window boots); the reweighted figures are hand values. The change touches `agent_boot_report.py` (about +185/−80), the new `agent_boot_rollup.py` (about 145 lines), `agent_costs.py` (about +40/−10), the tests (about +380) and about 9 KB of README rewritten in place. That is about 750 lines, which one review package holds, so the plan has one boundary. If a split is needed, the slices that deliver independently are Task 1 (read keys), Task 2 (medians and sub-totals) and Tasks 3–4 (windows and reweighting). Each leaves the README true at its commit.

## Task index

Task 1 — Extent-aware read keys — `python/agent_tools/agent_boot_report.py`, `python/README.md`, `tests/test_agent_boot_report.py` — full — [task-1.md](2026-11-02-issue-504-boot-report-reweighting.tasks/task-1.md)

Task 2 — Rollup module, medians and the two sub-totals — `python/agent_tools/agent_boot_rollup.py`, `python/agent_tools/agent_boot_report.py`, `python/README.md`, `tests/test_agent_boot_report.py` — full — [task-2.md](2026-11-02-issue-504-boot-report-reweighting.tasks/task-2.md)

Task 3 — Baseline window, arms and the boot's project — `python/agent_tools/agent_costs.py`, `python/agent_tools/agent_boot_report.py`, `python/agent_tools/agent_boot_rollup.py`, `python/README.md`, `tests/test_agent_boot_report.py` — full — [task-3.md](2026-11-02-issue-504-boot-report-reweighting.tasks/task-3.md)

Task 4 — Reweighting to the baseline's host × phase group × project mix — `python/agent_tools/agent_boot_rollup.py`, `python/agent_tools/agent_boot_report.py`, `python/README.md`, `tests/test_agent_boot_report.py` — full — [task-4.md](2026-11-02-issue-504-boot-report-reweighting.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 4 | `tests/test_agent_boot_report.py::WindowsTest::test_the_candidate_is_reweighted_to_the_baseline_project_mix` checks the reweighted means and weighted medians against hand values (two projects in opposite proportions across two windows), together with `::WindowsTest::test_strata_in_one_window_drop_out_and_a_scope_with_none_in_common_is_null`. Medians and the reading/work split come from Task 2's `::BootReportTest::test_group_rows_carry_medians_and_both_sub_totals` and `::test_text_output_prints_medians_beside_means_and_the_sub_total_rows`. The reread is Task 1's `::BootReportTest::test_a_whole_read_covers_every_later_read_of_its_file`, a `cat X` then a `Read X`. Each fails at its task's start commit (Step 2), and `just agent-workflow-tests` runs them green at the final gate. |

## Decisions

The plan rests on D1–D8. Planning appends three rows to the spec's ledger: D9 (the rollup owns the grouping axes and takes the bucket names as an argument), D10 (exact weighted means, every statistic a float or `null`) and D11 (text headings per arm). The standards review appends D12 (a command cut by a substitution is never a whole read) and D13 (a host-and-cohort reweighting test).

## Standards review provenance

Reviewer: Codex (`codex-plan-review`, gpt-6-astra, xhigh), isolated read-only mode, base 328f08daca0cd21e71a622f98c91c3f3a7a6728c, plan head a9446c4d, no focus, no fallback. Four findings, all accepted, none rejected or deferred: PR-001 (blocking, Task 1, D12), PR-002 (blocking, Tasks 2 and 4: the rollup check greps imports only), PR-003 (should fix, Task 2: four top-skills alignments), PR-004 (should fix, Task 4, D13).

---

## Review feasibility delivery

```json
{"actual_evidence":{"head":"f44a13d2fa8828f559f5d065c8aa0a1e9d464080","kind":"git-range-ownership/v1","process_ranges":[{"base":"328f08daca0cd21e71a622f98c91c3f3a7a6728c","boundaries":["all"],"head":"65e822d7b6ec3fda3ea0eee33dad0ae5e4c504f3"},{"base":"dc9482fc6460b98c82dfa5e0a55354ec91358cd6","boundaries":["all"],"head":"47bcd47c928919ef505df67fde2638d7f1bfd535"},{"base":"6ba26ce0b972a08994f9ab95dfea00f933e4323e","boundaries":["all"],"head":"0a5dc9ccf8df4c41c11751ce67abc705fd599e59"}],"tree":"fb1dbb96217965b8f68ab54f9efbabb86a562f8a"},"boundaries":[{"acceptance":"Issue 504 complete: AC1 green under just agent-workflow-tests","depends_on":[],"id":"all","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64,64,64],"process_forecast_ids":["s","p","t1","t2","t3","t4"],"process_package":{"plan":".agents/artifacts/plans/2026-11-02-issue-504-boot-report-reweighting.md","spec":".agents/artifacts/specs/2026-11-02-issue-504-boot-report-reweighting-design.md","tasks":[".agents/artifacts/plans/2026-11-02-issue-504-boot-report-reweighting.tasks/task-1.md",".agents/artifacts/plans/2026-11-02-issue-504-boot-report-reweighting.tasks/task-2.md",".agents/artifacts/plans/2026-11-02-issue-504-boot-report-reweighting.tasks/task-3.md",".agents/artifacts/plans/2026-11-02-issue-504-boot-report-reweighting.tasks/task-4.md"]},"tasks":[1,2,3,4]}],"delivery_base":"328f08daca0cd21e71a622f98c91c3f3a7a6728c","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":340,"boundary":"all","deleted_lines":0,"record_bytes":32768,"support":{"covers":["s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"s","last_task":4,"owner":0,"path":".agents/artifacts/specs/2026-11-02-issue-504-boot-report-reweighting-design.md"},{"bounds":[{"added_lines":130,"boundary":"all","deleted_lines":0,"record_bytes":20480,"support":{"covers":["p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-504-boot-report-reweighting.md"},{"bounds":[{"added_lines":150,"boundary":"all","deleted_lines":0,"record_bytes":16384,"support":{"covers":["t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-504-boot-report-reweighting.tasks/task-1.md"},{"bounds":[{"added_lines":175,"boundary":"all","deleted_lines":0,"record_bytes":18432,"support":{"covers":["t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-504-boot-report-reweighting.tasks/task-2.md"},{"bounds":[{"added_lines":275,"boundary":"all","deleted_lines":0,"record_bytes":26624,"support":{"covers":["t3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-504-boot-report-reweighting.tasks/task-3.md"},{"bounds":[{"added_lines":180,"boundary":"all","deleted_lines":0,"record_bytes":20480,"support":{"covers":["t4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t4","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-504-boot-report-reweighting.tasks/task-4.md"}],"proposed_boundary":"all","schema_version":3}
```
