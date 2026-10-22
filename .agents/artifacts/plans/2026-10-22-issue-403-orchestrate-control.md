# `orchestrate-control` Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A new `agent_tools` command, `orchestrate-control` (`start`, `step`), gathers the facts of an `orchestrate-issues` control round from the bound tracker, the forge, git and `workflow-state`, runs the round and projects its dispatches, so no orchestrator writes its own glue.

**Architecture:** One module, `python/agent_tools/orchestrate_control.py`, shaped like `sdd_gate.py`: a thin argparse shell over importable functions, a fixed step order per subcommand, one compact JSON object on stdout (ready exit 0, refused exit 2). It resolves the project in process (D12), runs `workflow-state`, `artifact-budget`, `git` and the bound tracker CLI by name on `PATH`, validates every workflow response at the `workflow-response` boundary (D13) and writes no file (D3, D22). One command-table row installs the launcher.

**Tech stack:** Python 3 standard library (`argparse`, `subprocess`, `json`, `dataclasses`, `unittest`), Nix (`lib/agent-tools.nix` command table), the GitHub GraphQL API through `gh api graphql`.

Spec: `.agents/artifacts/specs/2026-10-21-orchestrate-control-facts-design.md`; its `## Decision ledger` rows are cited by ID, D26–D29 appended by this plan. Issue: https://github.com/fagenorn/nix-config/issues/403

## Global Constraints

- Base: `7e65b0c551ea6163dbd18c8ffef38deaf86fd0a9` (`origin/main` at planning). Tasks land in index order; each task's tests extend the previous task's files.
- Files this plan changes, and no others: `python/agent_tools/orchestrate_control.py` (new), `tests/orchestrate_world.py` (new), `tests/test_orchestrate_control.py` (new), `lib/agent-tools.nix`, `tests/test_agent_tools_launchers.py`, `justfile`, `python/README.md`. Nothing under `home/common/agent-skills/` or `home/common/claude-code/` changes: the skill rewrite and the admission-replay seam are a follow-up (D11).
- `docs/standards/agent-helpers.md` rules 1–5: one package module plus one command-table row; parser `prog` is `orchestrate-control`; no `sys.path` edits, `importlib` or `__file__` lookups in `python/`; the resolver is imported (`agent_tools.resolve_project.resolve`, D12); every other child runs by command name on `PATH`.
- Every JSON the command reads (stdin and every child's stdout) is loaded with `object_pairs_hook=reject_duplicate_keys` and `parse_constant=reject_nonfinite_literal` from `agent_tools.canonical`.
- Every child runs with `capture_output=True`, `check=False` and explicit stdin (the bytes it consumes, else `subprocess.DEVNULL`). Every tracker-CLI child's environment is `os.environ` less each name in `bindings.tracker.credential_env.unset_before_invocation`.
- The command writes no file and holds no lock (D3, D22, D25); it never sends `now` to `control`.
- Step names, exactly: `start` — `bindings`, `route`, `issues`, `bootstrap`; `step` — `bindings`, `bootstrap`, `tracker`, `forge`, `worktrees`, `contracts`, `control`, `project` (`contracts` joins in Task 4).
- Exit codes: 0 ready or unsupported; 2 refused; an invalid invocation prints `orchestrate-control: invalid invocation` on stderr, nothing on stdout, exit 2 (D15).
- Ready and refusal objects are one line: `json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n"`. A refusal is exactly `{command, outcome: "refused", step, detail, completed_steps, response}`; `detail` is `" ".join(text.split())[:300]`.
- Prose that lands in the repository (docstrings, comments, `python/README.md`) describes the code as it behaves at that task's commit.
- Every long command, each test run included, runs in the foreground from the worktree root with an explicit timeout above its duration. A worker whose brief carries a `Lifecycle worker:` line runs it as `launch-scope exec --repo-root <R> --run-id <I> --worker-id <W> -- <argv>`, creates scratch only under `launch-scope scratch …`, and commits through `launch-commit … -- <git commit args>`; commits are signed and end with the session's trailers.
- Focused tests: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_orchestrate_control.py [-k <pattern>]` (timeout 900 s). `just build` and `just agent-installed-skill-tests`: timeout 3600 s each.
- Final gate (sdd's, once on the final head): `just build`, `just agent-workflow-tests` and `just agent-installed-skill-tests` (timeout 3600 s each).

## Test seams

- Command from source (spec seam 1): `python -m agent_tools.orchestrate_control` in the world of `tests/orchestrate_world.py` (D26) — real `git`, the source `workflow-state` and `artifact-budget` behind logging fault-rule shims, a fake `gh`, a resolvable fixture project, a temporary `HOME`. Suite: `tests/test_orchestrate_control.py`.
- Installed layout (spec seam 2): `LAUNCHER_FLOOR` in `tests/test_agent_tools_launchers.py`, run by `just agent-installed-skill-tests`.
- No other seam: no test imports a private helper of the module; assertions read the command's stdout, exit code, the world's call log and the logged `control` requests.

## Delivery estimate and boundaries

Estimates: 7 changed files. `orchestrate_control.py` about 650 lines, `orchestrate_world.py` about 330, the suite about 750; one line each in `lib/agent-tools.nix`, the launcher test and `justfile`; about 40 lines of `python/README.md`. One review package is expected to fit; the aggregate-growth risk is the suite. Task 2 leaves `project` refusing every dispatch kind until Task 3 projects them, and Task 4 inserts `contracts`; each intermediate head is honest and passes its own tests. Task 1 alone is deliverable (the `start` contract and launcher); Tasks 2–4 build `step`.

## Task index

Task 1 — `start`, the test world and the command row — `python/agent_tools/orchestrate_control.py`, `tests/orchestrate_world.py`, `tests/test_orchestrate_control.py`, `lib/agent-tools.nix`, `tests/test_agent_tools_launchers.py`, `justfile`, `python/README.md` — full — [task-1.md](2026-10-22-issue-403-orchestrate-control.tasks/task-1.md)
Task 2 — `step` facts and one control round — `python/agent_tools/orchestrate_control.py`, `tests/orchestrate_world.py`, `tests/test_orchestrate_control.py` — full — [task-2.md](2026-10-22-issue-403-orchestrate-control.tasks/task-2.md)
Task 3 — Dispatch projection and resume packs — `python/agent_tools/orchestrate_control.py`, `tests/orchestrate_world.py`, `tests/test_orchestrate_control.py` — full — [task-3.md](2026-10-22-issue-403-orchestrate-control.tasks/task-3.md)
Task 4 — Delivery contracts, chaining, the refusal table and the `step` contract — `python/agent_tools/orchestrate_control.py`, `tests/orchestrate_world.py`, `tests/test_orchestrate_control.py`, `python/README.md` — full — [task-4.md](2026-10-22-issue-403-orchestrate-control.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `tests/test_orchestrate_control.py`: `StartTest.test_explicit_numbers_give_a_human_directed_session`, `test_a_label_or_milestone_gives_a_standing_repository_session`, `test_run_id_re_enters_the_run`, `test_an_unsupported_route_prints_no_session` |
| AC2 | code | Task 2 | `FactsTest.test_the_request_carries_the_bound_policy_and_control_accepts_it`, `TrackerTest.test_one_tracker_call_per_hundred_issues`, `ForgeTest.test_the_forge_listing_is_paginated_uncapped_and_matched`, `FactsTest.test_no_gh_child_sees_an_unset_variable` |
| AC3 | code | Task 2 | `WorktreeTest.test_recorded_worktrees_normalize_to_three_states`, `test_a_leftover_worktree_or_branch_moves_the_candidate_to_2`, `test_candidate_exhaustion_refuses_at_worktrees` |
| AC4 | code | Task 2 | `TrackerTest.test_open_blockers_split_into_numbers_and_decision_blockers`, `test_a_cross_repository_open_blocker_refuses_at_tracker` |
| AC5 | code | Task 4 | `ContractTest.test_first_sweep_builds_for_null_digest_requirements_from_the_recorded_worktree`, `test_contracts_due_are_built_and_refused_ones_never`, `test_a_builder_refusal_is_reported_and_joins_refused_contracts` |
| AC6 | code | Task 4 | `ChainTest.test_a_fresh_set_chains_one_contract_round_into_spawns`, `test_a_reply_with_a_dispatch_is_never_chained`, `test_every_listed_refusal_ends_the_run` |
| AC7 | code | Task 3 | `ProjectTest.test_a_resume_carries_its_owner_object_and_resume_pack`, `test_a_failing_resume_pack_leaves_it_null`, `test_a_remainder_dispatch_is_its_action_verbatim`; the spawn projection again in Task 4's `ChainTest.test_a_fresh_set_chains_one_contract_round_into_spawns` |
| AC8 | code | Task 4 | `RefusalTableTest.test_every_start_step_refuses_with_its_name`, `test_every_step_step_refuses_with_its_name_and_the_response_after_control`, `test_no_file_is_created_under_the_ledger_root_or_working_directory` |
| AC9 | code | Task 1 | `tests/test_agent_tools_launchers.py` with `orchestrate-control` in `LAUNCHER_FLOOR`, run by `just agent-installed-skill-tests` (builds first); the new suite in `just agent-workflow-tests` |

## Decisions

- Command home, report shape, no disk state, adapter-carried state and per-call bindings: per D1–D5, D12, D15, D22, D25.
- Chaining and its request: per D6, D18; chained-phase failures refuse at `control`: per D28 (appended).
- Tracker, forge and sweep reads: per D7, D8, D9, D16, D20, D24; their exact wire: per D27 (appended).
- Worktree facts and candidates: per D10, D19, D21. Contracts and validation boundary: per D13, D17. Closed action set: per D23. `--run-id` and long sets: per D14.
- Test world, fault rules and seeded spawns: per D26 (appended). Interface details (verbatim root, verbatim builder line, argv vs `issues` refusals, owner checks): per D29 (appended).
- Scope excludes the skill rewrite and the replay seam: per D11.

---
