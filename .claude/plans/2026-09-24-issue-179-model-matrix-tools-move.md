# Model-Matrix Tools Move Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Move the model-matrix validator, the model-drift family, `diff-scope`
and `context-map-lint` into `agent_tools`, deploy the three commands as package
launchers, and leave the telemetry digest and the duplicate-key hook defined only
in `agent_tools.canonical`
([#179](https://github.com/fagenorn/nix-config/issues/179)).

**Architecture:** Seven `git mv` moves into `python/agent_tools/`, each with only
the spec's listed edits. The drift family moves first, trading its
`SourceFileLoader` blocks for package imports (Task 1). The matrix follows and
takes the drift schema's validator load with it (Task 2). `diff-scope` and
`context-map-lint` become command-table rows (Tasks 3–4). The installed-layout
test pins the four deployed launchers, and the slice is verified end to end
(Task 5).

**Tech stack:** Python 3 stdlib (`unittest`, subprocess round trips),
nixpkgs `buildPythonPackage` via `lib/agent-tools.nix`, Home Manager, `just`,
Markdown.

Spec (source of truth, read it whole):
`.claude/specs/2026-09-24-issue-179-model-matrix-tools-move-design.md`, D1–D12.
It is a slice of `.claude/specs/2026-09-24-agent-tools-package-design.md`
(parent D1–D16) on top of
`.claude/specs/2026-09-24-issue-175-agent-tools-foundation-design.md`
(#175 D1–D14). Both bind.

## Global Constraints

- Command names, `~/.agents/bin` paths, and argv, stdin, stdout and exit
  contracts stay unchanged (parent D15). Existing assertions pass as they are,
  except D7's two location literals. The only new assertions are the drift
  reporter's `-m --help` run (D6) and the installed test's floor and misuse map
  (D8). `tests/test_context_map_lint.py` joins the recipe.
- Every move uses `git mv`. Its content edits are exactly the spec's D2–D5
  list for that file: no reformatting, no reflow, no renamed helper, and no
  split function (parent D14). Unused imports go. The `__main__` block stays.
- Living documents naming a moved file are re-pointed in the move's own commit
  (the-bar, Moves keep their history). Point-in-time records under
  `.claude/specs` and `.claude/plans` keep their paths.
- Recipes assign `PYTHONPATH="{{agent_tools_path}}"` on each line that runs
  package code. There is no justfile-wide `export` (#175 D6).
- Scope is exactly the spec's `## Out of scope`: no other cluster, no argparse
  for the linter, no oracle replacement, no function split and no test
  relocation.
- The shared wiring files are `justfile`, `home/common/agent-skills/default.nix`,
  `CLAUDE.md` and the contracts test. Edits to them stay local, never reflow a
  neighbouring line, and never re-run `nixfmt` (D11).
- Flakes see tracked files only, and `git mv` stages. `git add` any other new
  file before `just build`. Never run `just switch`.
- `~/.agents/bin` is an older activation. Gates run this worktree's source with
  an absolute `PYTHONPATH="$PWD/python"`, because the diff-scope children run in
  scratch working directories, or its build (`./result`).
- Run the full suite as `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests`,
  CI's mode. On this machine the activated `~/.agents/skills` predates the
  source, so `test_installed_policy_surface_matches_source_contract` fails at
  the base without it. In this mode the base reports `Ran 1222 tests` and
  `OK (skipped=2)`: that test and the installed dispatch class skip. Expect
  1223 after Task 1, 1224 after Task 2 and 1228 after Task 4, with
  `skipped=2` throughout. A run
  takes about 8–20 minutes. Summarize any failure to its failing test ids.
- Commits are conventional and SSH-signed. Never disable signing. Each message
  ends with the harness's two trailer lines (`Co-Authored-By:` and
  `Claude-Session:`).

Path abbreviations used in members: `PK` = `python/agent_tools`,
`AS` = `home/common/agent-skills`.

## Test seams

- **Seam 1, from source.** The existing suites run under the recipe's
  `PYTHONPATH`. They run commands as `[sys.executable, "-m", "agent_tools.<module>", …]`
  and import modules normally. This slice adds the drift reporter's `-m --help`
  run and puts the context-map-lint suite in the recipe (D6).
- **Seam 2, installed layout.** `tests/test_agent_tools_launchers.py` runs only
  from `just agent-installed-skill-tests`. It gains the misuse map (Task 4) and
  the floor (Task 5) (D8).
- Seam 3, the guard's registered hook, is untouched.
- **Shown once, not committed.** The build-time imports check covers the moved
  modules through each task's `just build`. The demos run in Task 5.
- `unittest -v` prints no line for a passing subtest. Gates check launchers by
  reading the built `.agents/bin` entries, not by reading verbose output.

## Delivery estimate and boundaries

These figures are estimates. About 21 product files change: `diff-scope`
counts each rename once and counts tests as product files, so the PR crosses
ship-issue's 20-product-file small-diff boundary and gets the full two-axis
review with a scoped Codex diff packet. The seven renames carry
about 2,450 lines with roughly 60 edited, and new test code is about 30 lines.
The Nix change is about 10 lines, and one `CLAUDE.md` sentence changes. With
rename detection the diff is about 25–40 KB, which fits one review package. The
main growth risk is edits beyond the spec's lists breaking rename pairing: the
reporter pairs at about 79%, and the others at 92–100%. Tasks run in index
order, and each depends on every earlier one (D12).

## Task index

Task 1 — Move the drift family into the package — `scripts/agent-model-drift.py` → `PK/agent_model_drift.py`, `scripts/agent-model-drift-routing.py` → `PK/agent_model_drift_routing.py`, `scripts/agent-model-drift-scheduling.py` → `PK/agent_model_drift_scheduling.py`, `scripts/agent-model-drift-schema.py` → `PK/agent_model_drift_schema.py`, `tests/agent_model_drift_test_support.py`, `tests/test_agent_model_drift_schema.py`, `tests/test_agent_model_drift_routing.py`, `tests/test_agent_model_drift_scheduling.py`, `tests/test_agent_model_drift_producer_integration.py`, `justfile` — full — [task-1.md](2026-09-24-issue-179-model-matrix-tools-move.tasks/task-1.md)

Task 2 — Ship agent-model-matrix as a package launcher — `AS/scripts/agent-model-matrix.py` → `PK/agent_model_matrix.py`, `PK/agent_model_drift_schema.py`, `lib/agent-tools.nix`, `AS/default.nix`, `AS/tests/test_agent_model_matrix.py`, `tests/agent_model_drift_test_support.py`, `justfile` — full — [task-2.md](2026-09-24-issue-179-model-matrix-tools-move.tasks/task-2.md)

Task 3 — Ship diff-scope as a package launcher — `AS/scripts/diff-scope.py` → `PK/diff_scope.py`, `lib/agent-tools.nix`, `AS/default.nix`, `AS/tests/test_diff_scope.py`, `AS/tests/test_workflow_skill_contracts.py` — full — [task-3.md](2026-09-24-issue-179-model-matrix-tools-move.tasks/task-3.md)

Task 4 — Ship context-map-lint as a package launcher — `scripts/context-map-lint.py` → `PK/context_map_lint.py`, `lib/agent-tools.nix`, `AS/default.nix`, `tests/test_context_map_lint.py`, `AS/tests/test_workflow_skill_contracts.py`, `tests/test_agent_tools_launchers.py`, `justfile`, `CLAUDE.md` — full — [task-4.md](2026-09-24-issue-179-model-matrix-tools-move.tasks/task-4.md)

Task 5 — Pin the deployed launcher floor and verify the slice — `tests/test_agent_tools_launchers.py` — low-risk — [task-5.md](2026-09-24-issue-179-model-matrix-tools-move.tasks/task-5.md)

## Criterion → task trace

| Criterion | Task |
|---|---|
| AC1: the three commands are package launchers exercised by the installed-layout test | 2, 3, 4 (rows and launchers), 4 (misuse map), 5 (floor, final check) |
| AC2: the drift family reaches the matrix and its siblings by package imports, with no file-path loader in these modules or their tests | 1 (siblings, suites), 2 (validator, fixture, matrix suite), 3 (diff-scope suite), 4 (lint suite), 5 (final greps) |
| AC3: the telemetry digest and the duplicate-key hook are defined only in `agent_tools.canonical` | 1 (drift digests, drift hook), 2 (matrix hook), 5 (final greps) |
| Regression floor: names, paths and contracts unchanged; existing assertions pass as they are; living docs re-pointed | 1–4 (per-command byte identity, docs), 5 (all three against the PR base) |
| Demo: `just agent-model-matrix`, `just agent-model-drift`, installed test | 1, 2, 5 |

## Decisions

The spec's `## Decision ledger` is authoritative. Tasks cite D1–D11 from design
and cite the parent's rows as "parent D*n*". Planning added one row:

- **D12** fixes the task order, including the one commit in which the moved
  drift schema still loads the flat validator by path (Tasks 1–2), and where
  D8's misuse map and floor land (Tasks 4–5).

A planning probe on a scratch export of `19b354a` applied Tasks 1–5's edits in
order. The drift suites passed in Task 1's intermediate state. A duplicate key
and a 5,000-digit integer each printed `cannot load JSON input` and exited 2.
With every edit applied, the darwin build passed and
`just agent-installed-skill-tests` ran 15 tests OK. The pre-map launcher test
failed on `context-map-lint` with `2 != 0`, and a home without `diff-scope`
failed the floor. The three `--help` answers were byte-identical to the base
scripts, and the full suite in source mode ran 1227 tests,
`OK (skipped=2)`, before Phase 5 added the matrix pin (D13). All seven
renames paired at 79–100%.

---

## Standards review provenance

- Reviewer: Claude fallback (one fresh native standards reviewer). Codex
  `plan-review` failed with its usage limit (`CODEX_REVIEW_FAILURE`), so the
  one-time native fallback ran; Codex was not retried.
- Base `2c36848681a6ef18bee933bec966bd869b31013b`, plan head `48e429b`;
  read-only review; no focus configured.
- Findings: 2 should-fix accepted (delivery estimate, constant annotations);
  4 discussion items: 2 accepted (duplicate-key pins, per D13; the Task 5
  `REPO_ROOT` note), 2 rejected — the legacy-surface pathspec moves with
  the linter in Task 4 as planned, because the final tree's scan covers
  `python/` and nothing added in Tasks 2–3 escapes it; and the `CLAUDE.md`
  sentence stays, because the lifecycle guard is no package helper (parent
  D1, D4) and #176 owns its own prose.
