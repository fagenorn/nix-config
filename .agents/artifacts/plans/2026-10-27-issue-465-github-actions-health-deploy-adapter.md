# GitHub Actions Health Deploy Adapter Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A project with release profiles can bind the registered `github-actions-health` deploy adapter. The resolver then reports `capabilities.deploy` available, `release deploy inspect` returns one closed observation per poll, and ship-release Phase 5 polls that command to the §5c invariant with no prose fallback.

**Architecture:** A new standard-library adapter module joins the closed release-adapter registry. It has one inspect-only `publication_triggered` operation, whose `inspect` reads the newest Actions runs and then the health endpoint (D2, D6–D8, D14). The resolver accepts a `bindings.deploy` that names a registered adapter, and the grammar's `deploy_conflict` rule narrows (D3, D4, D15). `release deploy inspect` resolves the project, unsets the tracker's credential variables and prints the observation (D5, D10). ship-release §5d polls that one line within the instruction budget (D11, D13, D17).

**Tech stack:** Python 3 standard library (`subprocess`, `urllib.request`, `http.server`, `json`, `datetime`, `unittest`), the `agent_tools` package, Markdown skill documents under the Instruction Budget gate, Nix (`just build`), Just.

Spec: `.agents/artifacts/specs/2026-10-27-issue-465-github-actions-health-deploy-adapter-design.md` (spec commits `7c839700` and `2511839e`). A bare "Dn" cites the spec's `## Decision ledger`, and "124 Dn" cites the issue-124 spec it names. This plan appends D14–D17. Issue: https://github.com/fagenorn/nix-config/issues/465.

## Global Constraints

- Base `5ae1b9dc` (`origin/main` at planning). Tasks land in index order, each on top of the one before.
- These files are not edited: `.agents/project.json`, `.agents/instructions/`, `CLAUDE.md`, `AGENTS.md`, `python/agent_tools/forge_adapter.py` (its token stripping stays, per spec § Out of scope), `tests/forge_world.py`, `home/common/agent-skills/instruction-load.json` and `lib/agent-tools.nix` (`release` gains a subcommand, not a launcher, per D5).
- `agent_tools.actions_health_adapter` imports only the standard library and `agent_tools.canonical`. `release_adapter` imports it, never the reverse (D14). No dependency is added (D8).
- The adapter's public surface is exactly `describe`, `inspect` and `invoke` (124 D7). `inspect` never raises and never mutates. `invoke` starts no child process.
- Instruction load: never add the `instruction-budget-raise` label. The `ship-release` and `release-owner` hot ceiling is 29,507 bytes on claude and codex, against 29,467 measured at base (D13, D17).
- Comments, docstrings and README sentences describe the code as it behaves at that task's commit. Where the implemented code differs from a clause this plan dictates, rewrite the clause from the code. Write "issue 465", never a bare `#465`. No `TODO` or `FIXME`.
- Stage each new file with `git add` before any `just build`, because the flake sees tracked files only.
- Run every long command, each test command included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration.
- Commit through `launch-commit … -- <git commit args>`. Commits are SSH-signed and end with the session's trailer lines. Scratch files live under the root that `launch-scope scratch` prints. Never run `just switch`, and never push.
- **Unit run** (timeout 900 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest <test file>... [-k <pattern>]... 2>&1 | tail -4'`.
- **Budget** (timeout 600 s): `bash -c 'set -o pipefail; just agent-instruction-budget 2>&1 | tail -3'`. Passing output ends `check: pass`.
- **Build** (timeout 3600 s): `bash -c 'set -o pipefail; just build 2>&1 | tail -3'`.
- Final gate (sdd, once on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each), plus the Budget run, which neither recipe covers.

## Test seams

Per D12 and D16:

- **Adapter, in process.** `tests/actions_world.py` provides `ActionsWorld`: a `PATH`-only fake `gh` that logs `{argv, token_visible}` and answers only the issue's exact `gh run list` argv, plus a loopback `ThreadingHTTPServer` with configured routes. `tests/test_actions_health_adapter.py` calls `actions_health_adapter.inspect` and `invoke` over it. The same file calls `release_adapter.config_problems`, `descriptor_problems`, `watch_operation` and the observation validators directly.
- **The command.** `python -m agent_tools.release deploy inspect` runs as a subprocess, through `ReleaseCommandCase.run_release` in `tests/test_release_command.py`, over `ActionsWorld`.
- **The resolver.** `resolve-project resolve` runs as a subprocess, through `ResolverTestCase.resolve`, `run_with_path` and `make_stub_bin` in `home/common/agent-skills/tests/test_resolve_project.py`.
- **The grammar.** `release_profile.grammar_violations(release, contract, descriptors)` runs with an injected registry in `tests/test_release_grammar.py`.
- **Skill text.** `ShipReleaseContractsTest` pins the two §5d lines (agent-helpers rule 6). `VocabularyGuardTest` checks every shell-fence head. The Budget run measures size.

## Delivery estimate and boundaries

All figures are estimates: 16 changed files plus this package and the spec ledger, about +1,250/−25 lines.

- Adapter module: about +300 lines.
- `tests/actions_world.py`: about +140.
- `tests/test_actions_health_adapter.py`: about +260.
- `release_adapter.py`: about +20.
- `resolve_project.py`: about +60.
- `release_profile.py`: about +15.
- `release.py`: about +50.
- Resolver tests: about +80.
- Grammar tests: about +60.
- Command tests: about +85.
- `python/README.md`: three additions.
- ship-release documents: +31 bytes net (measured, D17).
- Skill tests: about +16.
- `justfile`: +1.

The change fits one review package. If a split is forced, two slices can ship independently:

- S1 = Tasks 1–2: the adapter and resolver acceptance (AC1, AC3).
- S2 = Tasks 3–4: the command and Phase 5 (AC2).

## Task index

Task 1 — The `github-actions-health` adapter in the closed registry — `python/agent_tools/actions_health_adapter.py`, `python/agent_tools/release_adapter.py`, `tests/actions_world.py`, `tests/test_actions_health_adapter.py`, `tests/test_release_grammar.py`, `justfile`, `python/README.md` — full — [task-1.md](2026-10-27-issue-465-github-actions-health-deploy-adapter.tasks/task-1.md)
Task 2 — The resolver and grammar accept a registered deploy adapter beside profiles — `python/agent_tools/resolve_project.py`, `python/agent_tools/release_profile.py`, `home/common/agent-skills/tests/test_resolve_project.py`, `tests/test_release_grammar.py`, `python/README.md` — full — [task-2.md](2026-10-27-issue-465-github-actions-health-deploy-adapter.tasks/task-2.md)
Task 3 — `release deploy inspect` — `python/agent_tools/release.py`, `tests/test_release_command.py`, `python/README.md` — full — [task-3.md](2026-10-27-issue-465-github-actions-health-deploy-adapter.tasks/task-3.md)
Task 4 — ship-release Phase 5 polls the command — `home/common/agent-skills/skills/ship-release/SKILL.md`, `home/common/agent-skills/skills/ship-release/CHANGELOG.md`, `home/common/agent-skills/tests/test_ship_release_contracts.py`, `home/common/agent-skills/tests/test_shell_example_contracts.py` — full — [task-4.md](2026-10-27-issue-465-github-actions-health-deploy-adapter.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 2 | `home/common/agent-skills/tests/test_resolve_project.py::DeployWatchTest::test_a_jarbird_shaped_project_watches_its_deploy`: the issue's literal contract is `available` with `gh` on `PATH`, and `blocked`/`release_adapter_unavailable` without it |
| AC2 | code (classified) | Task 4 | Composition per D11: `home/common/agent-skills/tests/test_ship_release_contracts.py::ShipReleaseContractsTest::test_phase_five_polls_the_registered_adapter_command` and Task 3's `tests/test_release_command.py::DeployInspectTest::test_satisfied_needs_a_successful_run_and_a_matching_health_commit`, both run by `just agent-workflow-tests` |
| AC3 | code (classified) | Task 2 | Composition per D12 and D16, all run by `just agent-workflow-tests`: Task 1's `tests/test_actions_health_adapter.py::AdapterContractTest::test_string_list_is_a_closed_config_type`, `::AdapterContractTest::test_the_registry_carries_one_watch_operation`, `::ClassificationTest::test_satisfied_needs_a_successful_run_and_a_matching_health_commit`, `::ClassificationTest::test_intermediate_rows_never_read_health` and `::ClassificationTest::test_a_failed_run_is_a_silent_rollback_only_while_an_older_commit_serves`, plus Task 2's `home/common/agent-skills/tests/test_resolve_project.py::DeployWatchTest` and `tests/test_release_grammar.py::DeployWatchGrammarTest` |

## Decisions

- Task 1 follows D2, D6–D10, D14 and D16. Task 2 follows D1, D3, D4, D9 and D15. Task 3 follows D5, D10 and D16. Task 4 follows D11, D13 and D17.
- Planning appended four rows to the spec's ledger:
  - D14: the adapter's internals;
  - D15: the resolver helper and the report-once rule;
  - D16: test placement, refining D12;
  - D17: the measured skill trims and the vocabulary row.
- A planning trial at `2511839e` (a scratch worktree, since discarded) implemented all four tasks to measure the claims the members carry:
  - every failing test was red at its task's start and green afterwards;
  - 344 tests across the touched suites were green together;
  - the Budget run gave `check: pass` at 29,498 bytes.

---
