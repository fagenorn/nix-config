# Host-Local Release Units Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A release profile can declare a locally signed, installed bundle and a per-user launchd agent through two neutral, registered adapters, so the Argus-shaped profile compiles with no violations while every existing profile keeps its digest (issue 547 AC1–AC3).

**Architecture:** Two new standard-library modules, `agent_tools.codesigned_artifact_adapter` (`install`, publication `materialize`) and `agent_tools.launchd_agent_adapter` (`activate`, activation `local_apply`, plus the `agent_running` liveness predicate), join the closed `release_adapter.REGISTRY` (D1–D8). `release_adapter.watch_operation` narrows to `publication_triggered` (D10); the grammar, compiler, resolver and driver are unchanged (D11). Tests run both adapters in process over a fake host world and drive the real `TransactionStore` (D13, D16).

**Tech stack:** Python 3 standard library (`plistlib`, `subprocess`, `shutil`, `unittest`), Just, Nix.

Spec: `.agents/artifacts/specs/2026-11-02-issue-547-host-local-release-units-design.md`. A bare "Dn" cites its `## Decision ledger`, and "124 Dn", "465 Dn" and "368 Dn" cite the specs it names. Issue: https://github.com/fagenorn/nix-config/issues/547.

## Global Constraints

- Base `328f08da` (`origin/main`). Spec commit `fe8fe60a`, plus the planning commit that appends D19–D22.
- The two new modules import only the standard library and `agent_tools.canonical`, and each exposes exactly `describe`, `inspect` and `invoke` (D1). `release_adapter` imports them, never the reverse.
- Not edited (D11): `release_profile.py`, `resolve_project.py`, `release.py`, `release_driver.py`, `guard_policy.py`, `forge_adapter.py`, `actions_health_adapter.py`, every `transaction_*.py`, `.agents/project.json`, `lib/agent-tools.nix`, the lifecycle guard, `CLAUDE.md` and `AGENTS.md`.
- No file under `python/agent_tools/` contains `argus` in any case (AC2). Argus values live only in `tests/fixtures/release/argus-shaped-profile.json` and in the tests that load it. The adapter suites use neutral names (`dev.example.notifier`, `notifierd`).
- No test reaches this host's `launchctl`, `codesign` or `security`: every adapter call in a test runs inside `tests/host_world.py`'s `HostWorld`, whose `PATH` is its own `bin/` (D3, D13).
- Comments, docstrings and README sentences describe the code as it behaves at the task's commit; no `TODO` or `FIXME`. New code cites this spec as "issue 547 Dn", because a bare `Dn` in `release_adapter.py` means 124's.
- Commit messages say "issue 547", never `#547`, and no gate command or commit message pairs `git` with `push`.
- Commits go through `launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- <git commit args>`. They are SSH-signed, with subject `feat(issue-547/T<n>): …`, and end with the session's trailer.
- Run every long command in the foreground from the worktree root as `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Scratch goes under `launch-scope scratch`. Never `just switch`, and never push.
- A task that creates a test file adds it to `justfile`'s `agent-workflow-tests` list right after `tests/test_release_adapter_core.py` (Task 4's after Task 2's), in that task's commit.
- **Focused tests** (timeout 600 s), from the worktree root: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest <files> [-k <pattern>] 2>&1 | tail -4'`.
- `just build` (timeout 3600 s) import-checks every git-tracked `agent_tools` module and builds `DESCRIPTORS`, so a task that changes `python/agent_tools/` runs it after `git add`. sdd's final gate runs `just build` and `just agent-workflow-tests` (timeout 3600 s each) once, on the final head.

## Test seams

The spec's § Test seams; a task needing another seam is a plan bug.

1. Each adapter in process over `HostWorld`: a fake-only `PATH` (a logging `git` wrapper over the real one, plus fake `security`, `codesign` and `launchctl`), a temporary `HOME`, and a temporary checkout as the working directory (D13, D21).
2. Registry and descriptors, imported (`tests/test_release_adapter_core.py`, `tests/test_release_grammar.py`).
3. The grammar, compiler, resolver and `release profile inspect`, with the Argus-shaped fixture and the real registry (D11).
4. The real `TransactionStore` with one `core_binding` per alias over `HostWorld` (D16).
5. The AC2 static scan of `python/agent_tools/*.py`.

## Delivery estimate and boundaries

Rationale only; the numbers are in the forecast blocks.

- `all` (Tasks 1–7) is the one boundary: one branch and one review package (D14). Tasks 1–3 are D14's group A, which stands alone because a bundle-only profile compiles, and Tasks 4–7 are group B. If ship's `diff-scope` reports the branch over the review limit, the split comes after Task 3 (D14).
- Bounds are padded. `python/README.md`'s release lines run to 4 KB, so its record carries about 27 KB of context, and adapter and suite records allow one fix round.

## Task index

Task 1 — `watch_operation` watches only a publication-triggered operation — `python/agent_tools/release_adapter.py`, `tests/test_release_adapter_core.py`, `python/README.md` — full — [task-1.md](2026-11-02-issue-547-host-local-release-units.tasks/task-1.md)

Task 2 — Host world and the `codesigned-artifact` read half — `tests/host_world.py`, `python/agent_tools/codesigned_artifact_adapter.py`, `tests/test_codesigned_artifact_adapter.py`, `justfile` — full — [task-2.md](2026-11-02-issue-547-host-local-release-units.tasks/task-2.md)

Task 3 — `codesigned-artifact` install, registration and docs — `python/agent_tools/codesigned_artifact_adapter.py`, `tests/test_codesigned_artifact_adapter.py`, `python/agent_tools/release_adapter.py`, `tests/test_release_adapter_core.py`, `tests/test_release_grammar.py`, `python/README.md` — full — [task-3.md](2026-11-02-issue-547-host-local-release-units.tasks/task-3.md)

Task 4 — Fake `launchctl` and the `launchd-agent` read half — `tests/host_world.py`, `python/agent_tools/launchd_agent_adapter.py`, `tests/test_launchd_agent_adapter.py`, `justfile` — full — [task-4.md](2026-11-02-issue-547-host-local-release-units.tasks/task-4.md)

Task 5 — `launchd-agent` activation, registration, AC2 and docs — `python/agent_tools/launchd_agent_adapter.py`, `tests/test_launchd_agent_adapter.py`, `python/agent_tools/release_adapter.py`, `tests/test_release_adapter_core.py`, `tests/test_release_grammar.py`, `python/README.md` — full — [task-5.md](2026-11-02-issue-547-host-local-release-units.tasks/task-5.md)

Task 6 — The Argus-shaped profile compiles, resolves and inspects (AC1) — `tests/fixtures/release/argus-shaped-profile.json`, `tests/release_test_support.py`, `tests/test_release_grammar.py`, `tests/test_release_profile.py`, `home/common/agent-skills/tests/test_resolve_project.py`, `tests/test_release_command.py`, `python/README.md` — full — [task-6.md](2026-11-02-issue-547-host-local-release-units.tasks/task-6.md)

Task 7 — The core settles an Argus-shaped release over the host world — `tests/test_release_adapter_core.py`, `python/README.md` — full — [task-7.md](2026-11-02-issue-547-host-local-release-units.tasks/task-7.md)

## Acceptance map

The issue's criteria are untagged; all three are classified `code`.

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 6 | `tests/test_release_grammar.py::HostLocalProfileTest::test_the_argus_shaped_profile_has_no_violations`, `tests/test_release_profile.py::HostLocalProfileTest::test_the_argus_shaped_profile_compiles_and_binds`, `home/common/agent-skills/tests/test_resolve_project.py::HostLocalReleaseTest::test_the_argus_shaped_contract_resolves_available` and `tests/test_release_command.py::HostLocalInspectTest::test_the_argus_shaped_profile_is_admissible`, each failing at Task 6's start (no fixture). All four run green under `just agent-workflow-tests` at the final gate. |
| AC2 | code (classified) | Task 5 | `tests/test_release_adapter_core.py::RegistryTest::test_no_agent_tools_module_names_argus` |
| AC3 | code (classified) | Task 3 | `tests/test_release_adapter_core.py::RegistryTest::test_prior_descriptors_and_forge_profiles_keep_their_base_digests` (D22), and the release, conformance, adoption and guard-policy suites green under `just agent-workflow-tests` at the final gate |

## Decisions

| Decisions | Tasks |
|---|---|
| D1, D3, D12 (two modules, real tools, no guard) | 2–5 |
| D2, D6 (modes and effects; `absent` means not this candidate) | 2–5, 7 |
| D4, D5, D19 (stamps, predicates, derived reason spaces) | 2, 4 |
| D7, D8, D17 (target kinds, closed configs, inner checks) | 2–5 |
| D9, D20 (build stays outside; staging and swap) | 3 |
| D15 (budgets and the `rejected`/`unknown` boundary) | 3, 5 |
| D18 (program path) | 5 |
| D10, D11 (deploy watch; no generic change) | 1, 6 |
| D13, D21 (host world; host tool grammars) | 2, 4 |
| D14 (one branch, split after Task 3 if needed) | the boundary |
| D16 (core end-to-end seam) | 7 |
| D22 (AC3 digest pins) | 3 |

Planning appended D19–D22.

---

## Review feasibility delivery

```json
{"actual_evidence":{"head":"328f08daca0cd21e71a622f98c91c3f3a7a6728c","kind":"git-range-ownership/v1","process_ranges":[],"tree":"e5f2f5e40149d63e4bfa776ae400315fbf16a01c"},"boundaries":[{"acceptance":"Issue 547 complete: AC1 to AC3 green under just agent-workflow-tests and just build","depends_on":[],"id":"all","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64,64],"process_forecast_ids":["s","p","t1","t2","t3","t4","t5","t6","t7"],"process_package":{"plan":".agents/artifacts/plans/2026-11-02-issue-547-host-local-release-units.md","spec":".agents/artifacts/specs/2026-11-02-issue-547-host-local-release-units-design.md","tasks":[".agents/artifacts/plans/2026-11-02-issue-547-host-local-release-units.tasks/task-1.md",".agents/artifacts/plans/2026-11-02-issue-547-host-local-release-units.tasks/task-2.md",".agents/artifacts/plans/2026-11-02-issue-547-host-local-release-units.tasks/task-3.md",".agents/artifacts/plans/2026-11-02-issue-547-host-local-release-units.tasks/task-4.md",".agents/artifacts/plans/2026-11-02-issue-547-host-local-release-units.tasks/task-5.md",".agents/artifacts/plans/2026-11-02-issue-547-host-local-release-units.tasks/task-6.md",".agents/artifacts/plans/2026-11-02-issue-547-host-local-release-units.tasks/task-7.md"]},"tasks":[1,2,3,4,5,6,7]}],"delivery_base":"328f08daca0cd21e71a622f98c91c3f3a7a6728c","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":540,"boundary":"all","deleted_lines":0,"record_bytes":49152,"support":{"covers":["s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"s","last_task":7,"owner":0,"path":".agents/artifacts/specs/2026-11-02-issue-547-host-local-release-units-design.md"},{"bounds":[{"added_lines":140,"boundary":"all","deleted_lines":0,"record_bytes":16384,"support":{"covers":["p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-547-host-local-release-units.md"},{"bounds":[{"added_lines":100,"boundary":"all","deleted_lines":0,"record_bytes":9216,"support":{"covers":["t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-547-host-local-release-units.tasks/task-1.md"},{"bounds":[{"added_lines":230,"boundary":"all","deleted_lines":0,"record_bytes":24576,"support":{"covers":["t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-547-host-local-release-units.tasks/task-2.md"},{"bounds":[{"added_lines":195,"boundary":"all","deleted_lines":0,"record_bytes":19456,"support":{"covers":["t3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-547-host-local-release-units.tasks/task-3.md"},{"bounds":[{"added_lines":265,"boundary":"all","deleted_lines":0,"record_bytes":24576,"support":{"covers":["t4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t4","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-547-host-local-release-units.tasks/task-4.md"},{"bounds":[{"added_lines":195,"boundary":"all","deleted_lines":0,"record_bytes":18432,"support":{"covers":["t5"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t5","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-547-host-local-release-units.tasks/task-5.md"},{"bounds":[{"added_lines":200,"boundary":"all","deleted_lines":0,"record_bytes":17408,"support":{"covers":["t6"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t6","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-547-host-local-release-units.tasks/task-6.md"},{"bounds":[{"added_lines":170,"boundary":"all","deleted_lines":0,"record_bytes":12288,"support":{"covers":["t7"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t7","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-547-host-local-release-units.tasks/task-7.md"}],"proposed_boundary":"all","schema_version":3}
```
