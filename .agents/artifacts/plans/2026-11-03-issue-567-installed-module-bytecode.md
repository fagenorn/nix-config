# Installed Module Bytecode Clear Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** After a switch, an installed agent module never runs bytecode compiled from its previous source, while a second load of an unchanged module still compiles nothing (issue 567).

**Architecture:** One shell script, `clear-library-bytecode`, renames `~/.agents/lib/python/__pycache__` into a fresh private directory inside the library and then removes that directory (D3). A Home Manager activation entry ordered after `linkGeneration` runs it on every switch. A failure is reported and the switch goes on (D1, D4). No loader changes. The tests run the same file the activation runs (D2, D6, D7).

**Tech stack:** Bash (`mktemp`, `mv`, `rm`), the Home Manager activation DAG, Python 3 standard-library `unittest`, Just.

Spec: `.agents/artifacts/specs/2026-11-03-issue-567-installed-module-bytecode-design.md`. A bare "Dn" cites its `## Decision ledger`. Issue: https://github.com/fagenorn/nix-config/issues/567.

## Global Constraints

- Base `fc13636d` (`origin/main`), spec commit `8b36e8e2`.
- Only the files in the Task index change. Every loader's code, `lib/agent-tools.nix`, `justfile`, `CLAUDE.md` and `python/README.md` stay as they are. The script gets no `home.file` entry (D1, D5, D7; spec § Out of scope).
- The script uses only `mktemp -d <template>`, `mv --` and `rm -rf --`, in forms GNU and BSD share, under `set -eu`, with nothing muted (spec § Decisions, D3).
- Commits go through `launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- <git commit args>`. They are SSH-signed and use the subject form `fix(issue-567): …`. They say "issue 567", never a bare `#567`, and end with the session's `Co-Authored-By` trailer.
- Run every long command in the foreground from the worktree root as `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Scratch goes under `launch-scope scratch`. Never run `just switch`, and never push.
- sdd's final gate runs `just build` and `just agent-workflow-tests` (timeout 3600 s each) once, on the final head.

## Test seams

The spec's § Test seams. Implementers test only at these.

1. Same-size edit after a switch (AC1, and AC2 in the installed layout): `DeliveryAdmissionTest.test_a_same_size_module_edit_runs_after_the_library_cache_is_cleared`. It runs a real `init-run` through links to a stand-in store whose files have modification time 1, with the negative control before the clear (D6).
2. The script on its own: `LibraryBytecodeClearTest`, against temporary libraries (D2, D3, D7).
3. The wiring: a Nix text pin on `home/common/agent-skills/default.nix`, and, after `just build`, the order of the steps in the built activation script.
4. AC2 in the source layout: `test_a_second_init_run_compiles_nothing_into_its_bytecode_cache` (issue 499). It does not change and must stay green.

## Delivery estimate and boundaries

- `all` (Tasks 1–2) is the only boundary. The two small tasks fit one review package, and a split would review the script apart from the activation that runs it.

## Task index

Task 1 — The clearing script and its proofs — `home/common/agent-skills/scripts/clear-library-bytecode`, `home/common/agent-skills/tests/test_delivery_workflow.py` — full — [task-1.md](2026-11-03-issue-567-installed-module-bytecode.tasks/task-1.md)

Task 2 — Every activation clears the library cache, documented — `home/common/agent-skills/default.nix`, `home/common/agent-skills/tests/test_delivery_workflow.py`, `home/common/agent-skills/README.md`, `home/common/agent-skills/scripts/workflow-state.py` — full — [task-2.md](2026-11-03-issue-567-installed-module-bytecode.tasks/task-2.md)

Both tasks are full lane: the script deletes a directory, and the activation runs that deletion on every switch, with a concurrency residual the README documents (D3).

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `home/common/agent-skills/tests/test_delivery_workflow.py::DeliveryAdmissionTest::test_a_same_size_module_edit_runs_after_the_library_cache_is_cleared`, a member of `just agent-workflow-tests`. Before the clear, the negative control shows the stale load. After the same-size relink and the clear, `init-run` exits 2 with `workflow-state: delivery runtime: interface`: the edited code ran (D6). |
| AC2 | code | Task 1 | The same test's last assertion covers the installed layout: a further `init-run` leaves every file in the library's `__pycache__` with its bytes and modification time unchanged. `DeliveryAdmissionTest::test_a_second_init_run_compiles_nothing_into_its_bytecode_cache` (issue 499, unchanged) covers the source layout. Task 1 runs both. |

## Decisions

Per D1 (activation clear, no loader changes), D2 (one script that both the activation and the suite run), D3 (rename, then remove, with the residual documented), D4 (`errorEcho`, and the switch continues), D5 (the top-level cache only, docstrings re-pointed) and D6 (proof through the production loader, with a negative control). Planning added D7 (the script's location, argv and invocation).

---

## Review feasibility delivery

```json
{"actual_evidence":{"head":"fc13636dc79c759d4e830551db6d6d8fc31e2e9c","kind":"git-range-ownership/v1","process_ranges":[],"tree":"fc1d3958ecce32fadad6bbd122a67a3b7de8c550"},"boundaries":[{"acceptance":"Issue 567 complete: the clearing script and its tests green, every activation runs it after linkGeneration, just agent-workflow-tests and just build","depends_on":[],"id":"all","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64],"process_forecast_ids":["s","p","t1","t2"],"process_package":{"plan":".agents/artifacts/plans/2026-11-03-issue-567-installed-module-bytecode.md","spec":".agents/artifacts/specs/2026-11-03-issue-567-installed-module-bytecode-design.md","tasks":[".agents/artifacts/plans/2026-11-03-issue-567-installed-module-bytecode.tasks/task-1.md",".agents/artifacts/plans/2026-11-03-issue-567-installed-module-bytecode.tasks/task-2.md"]},"tasks":[1,2]}],"delivery_base":"fc13636dc79c759d4e830551db6d6d8fc31e2e9c","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":220,"boundary":"all","deleted_lines":0,"record_bytes":24576,"support":{"covers":["s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"s","last_task":2,"owner":0,"path":".agents/artifacts/specs/2026-11-03-issue-567-installed-module-bytecode-design.md"},{"bounds":[{"added_lines":120,"boundary":"all","deleted_lines":0,"record_bytes":16384,"support":{"covers":["p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p","last_task":2,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-567-installed-module-bytecode.md"},{"bounds":[{"added_lines":320,"boundary":"all","deleted_lines":0,"record_bytes":24576,"support":{"covers":["t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1","last_task":2,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-567-installed-module-bytecode.tasks/task-1.md"},{"bounds":[{"added_lines":180,"boundary":"all","deleted_lines":0,"record_bytes":20480,"support":{"covers":["t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2","last_task":2,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-567-installed-module-bytecode.tasks/task-2.md"}],"proposed_boundary":"all","schema_version":3}
```
