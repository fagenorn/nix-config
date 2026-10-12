# Publication-Free Release Profile Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A project contract can declare a release-profile forge target with `"publication": "none"`; `resolve-project resolve` lists that target under a new `release.targets` member, reports no release capability for it, and every profile-driven release path refuses it.

**Architecture:** `release_profile` answers "the authored nodes of this phase" through one function, `phase_nodes`, that every post-grammar reader uses, and only then accepts the second `publication` form in the grammar; the unchanged admissibility rules and compilers yield an empty graph, and `bind_candidate` refuses it. `resolve_project` derives `capabilities.release` and the new `release.targets` member from the authored `release`; `release` (the inspection command) reports the empty graphs. The lifecycle guard, the adapter contract and nix-config's own contract are not touched.

**Tech stack:** Python 3 standard library (`agent_tools` package under `python/`), `unittest`, the fake forge world in `tests/forge_world.py`.

Spec: `.agents/artifacts/specs/2026-10-11-issue-368-publication-free-release-profile-design.md` (requirements R1–R6; its `## Decision ledger` rows D1–D14 are cited by ID).

## Global Constraints

- Base: `40fa1f82c5a50ab8da32d15f9bf7c1d71e82e76b` (`origin/main` at planning). Tasks land in index order; a later task assumes every earlier one. Task 2 is one commit (D14).
- Standard library only. Policy lives in importable functions of `release_profile` and `resolve_project`; `release` stays a thin command shell (`docs/standards/agent-helpers.md` rule 2). No new digest or JSON helper (rule 4). Tests drive commands as `python -m agent_tools.<module>` (rule 5).
- Never edited: `.agents/project.json`, `tests/fixtures/release/github-release-profile.json`, `home/common/claude-code/lifecycle_guard.py`, `tests/test_claude_permission_guard.py`, `python/agent_tools/release_adapter.py`, `python/agent_tools/forge_adapter.py`, `python/agent_tools/conformance_checks.py`, `python/agent_tools/release_bridge.py`, the platform manifest (R4, spec section 6). Gate, run by every task: `git diff --quiet 40fa1f82c5a5 -- <those paths>` exits 0.
- No existing line of the `tests/test_release_*.py` modules is edited or removed: every change to them is an addition (R4). Gate, run by each task that touches one: `git diff --numstat 40fa1f82c5a5 -- 'tests/test_release_*.py'` prints `0` in its second column on every row.
- Unchanged vocabularies: `CAPABILITY_STATES`, `REASON_CODES`, `GRAMMAR_REPAIR_IDS`, `RULES`, `resolved_schema_version` (1), the seven members of the inspection report, the thirteen members of `ResolvedReleaseProfile` (D4, D5, D7).
- No target comes from anywhere but the authored contract: no flag, environment variable, default or repository-specific name in production code (R6). `fagenorn/nix-config`, `forge-target` and `elsewhere/other` appear in tests and fixtures only.
- The spelling `"none"` for a phase is read in two places only: the grammar (`_Profile.phases`) and `release_profile.phase_nodes`. From Task 2 on, no other line of `release_profile.py`, `release.py` or `resolve_project.py` compares a phase to `"none"` or indexes `["publication"]["actions"]` / `["activation"]["units"]` (the legacy bridge's own check in `release_bridge.py` stays).
- No resolved snapshot is written to a file, scratch included; a check that compares snapshots holds them in memory (`.agents/instructions/bootstrap.md`, D13).
- Prose that lands in code (docstrings, comments, error messages, README sentences) describes the code as it behaves at that task's commit; where a task lists facts instead of a sentence, write the sentence from the implemented code. Error messages a test pins are given verbatim.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration; commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root.
- Python tests run as `env PYTHONPATH="$PWD/python" python3 -m unittest <test file> [-k <pattern>]` (timeout 900 s; several suites start resolver subprocesses).
- Final gate, once on the final head (sdd's, not per task): `just agent-workflow-tests` (timeout 3600 s) and `just build` (timeout 3600 s).

## Test seams

- Grammar: `release_profile.grammar_violations` over `tests/release_test_support.py` builders (`tests/test_release_grammar.py`).
- Compiler: `admissibility_findings`, `phase_nodes`, `compile_profile`, `bind_candidate` with a real `TransactionStore` root (`tests/test_release_profile.py`).
- Adapter binding: `release_adapter.core_binding` over `ForgeWorld` (`tests/test_release_adapter_core.py`).
- Resolver command: `python -m agent_tools.resolve_project resolve` as a child process with a stub `PATH` (`ReleaseMemberTest` in `home/common/agent-skills/tests/test_resolve_project.py`).
- Release command: `python -m agent_tools.release profile inspect` as a child process (`tests/test_release_command.py`).
- Below the grammar (D14): `release_profile.lower`, `release_targets` and `resolve_project.release_capability` called as imported functions on the fixture profile, in the compiler suite and in `ReleaseMemberTest`.
- One fixture, `tests/fixtures/release/publication-free-profile.json`, a profile each suite places into a contract with its existing builder.

## Delivery estimate and boundaries

Estimates: 13 changed files — 3 production modules, 1 fixture, 1 test support module, 6 test modules, `python/README.md`, and the acceptance record — about +80 production lines and +330 test lines, one review package. A prototype of this shape passed `just agent-workflow-tests` at planning, and its Task 1 state was checked to leave every publication-free end-to-end test of Task 2 red. No commit is half-wired (D14): after Task 1 the grammar still refuses `"publication": "none"`, so every contract that resolves does so with a correct capability and a correct `release.targets`; Task 2 is the single commit that accepts the form, and it carries the `bind_candidate` refusal, the inspection report and the end-to-end proofs with it. Task 1 is deliverable alone; Task 2 is the largest review unit (about 7 files). Aggregate-growth risk: `home/common/agent-skills/tests/test_resolve_project.py` (1909 lines at base, about 2020 after).

## Task index

Task 1 — Readers below the grammar: `phase_nodes`, `release_targets`, `capabilities.release`, the `release` member — `python/agent_tools/release_profile.py`, `python/agent_tools/resolve_project.py`, `tests/fixtures/release/publication-free-profile.json`, `tests/release_test_support.py`, `tests/test_release_profile.py`, `home/common/agent-skills/tests/test_resolve_project.py`, `home/common/agent-skills/tests/test_resolve_platform.py` — full — [task-1.md](2026-10-12-issue-368-publication-free-release-profile.tasks/task-1.md)
Task 2 — The grammar accepts `"publication": "none"`, with the binding refusal and the inspection report — `python/agent_tools/release_profile.py`, `python/agent_tools/release.py`, `tests/test_release_grammar.py`, `tests/test_release_profile.py`, `tests/test_release_adapter_core.py`, `tests/test_release_command.py`, `home/common/agent-skills/tests/test_resolve_project.py` — full — [task-2.md](2026-10-12-issue-368-publication-free-release-profile.tasks/task-2.md)
Task 3 — Documented contract and the nix-config byte-identity evidence — `python/README.md` — full — [task-3.md](2026-10-12-issue-368-publication-free-release-profile.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 2 | `test_resolve_project.py`: `ReleaseMemberTest.test_a_publication_free_profile_exposes_its_target_and_no_capability` (the fixture itself: `test_release_grammar.py`: `PublicationFreeGrammarTest.test_the_fixture_declares_a_target_and_has_no_violation`; the member's ordering and scoping: Task 1's `test_targets_are_sorted_and_operations_belong_to_their_handle`) |
| AC2 | code (classified) | Task 2 | `test_release_adapter_core.py`: `PublicationFreeBindingTest.test_every_request_is_refused_before_any_child_process` and `test_release_profile.py`: `PublicationFreeTest.test_bind_candidate_refuses_it_before_reading_the_candidate` (capability half: the AC1 test and `ReleaseMemberTest.test_a_publication_free_profile_needs_no_adapter_executable`; scope per D8) |
| AC3 | code (classified) | Task 2 | `test_resolve_project.py`: `ReleaseMemberTest.test_a_publication_free_target_for_another_repository_is_refused` (grammar rows: `PublicationFreeGrammarTest.test_the_publishing_form_and_the_same_repository_rule_are_unchanged`) |
| AC4 | evidence (classified) | Task 3 | Command: one Python process runs the base and the head `agent_tools` as `python3 -m agent_tools.resolve_project resolve --repo-root <worktree>`, holds both outputs in memory and compares them after dropping the head's `release` member (D9, D12, D13); conditions: clean tree, same checkout root, final head, no snapshot written to disk; threshold: canonical JSON equal, `.agents/project.json` and `tests/fixtures/release/github-release-profile.json` unchanged from base, and the zero-deletion gate of Global Constraints; acceptance-record row `AC4` |
| AC5 | evidence (classified) | Task 3 | Command `just agent-workflow-tests`, run on the final head after Task 3 by sdd's final gate; threshold: exit code `0`; acceptance-record row `AC5` |

## Decisions

- The form and its three rules: D1, D2. Which repair id a stray recovery unit and a stray activation carry: D11 (appended by this plan).
- Empty graph through unchanged rules, `bind_candidate` as the stop: D3. What AC2's refusal means and why the guard is untouched: D8.
- `capabilities.release`: D4.
- The `release.targets` member and its `operations`: D5, D6. The resolver-suite key-set pins it moves: D10 (appended by this plan, corrects a D5 probe claim).
- Inspection: D7.
- AC4's meaning: D9. How it is measured: D12 (appended by this plan), in memory per D13 (appended after standards review).
- Task order — readers below the grammar first, grammar acceptance as the last behavioural commit — and the imported-function seam it needs: D14 (appended after standards review).

---

## Standards review provenance

Reviewer: Codex (`codex-plan-review`), isolated read-only mode, no fallback, no focus. Base SHA 40fa1f82c5a50ab8da32d15f9bf7c1d71e82e76b. Findings: 2 blocking, 2 should-fix; 4 accepted, 0 rejected, 0 deferred. B1 (Task 3): the AC4 comparison no longer writes resolved snapshots to scratch; both are held in one process (D13). B2 (all tasks): five tasks became three so that no commit accepts the new form before its refusal, capability and inspection exist (D14). S1 (Task 1): the target-list tests assert complete ordered output over reverse-authored profiles and handles, per-handle operations, an unused target and a repeated operation. S2 (Task 2): the grammar tests compare whole violation lists, including an activation whose contents would raise further violations if judged.
