# `sdd-gate` and Rendered Dispatch Briefs Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** An sdd owner crosses each task boundary with one `sdd-gate` call and dispatches the implementer and the first-pass task reviewer with a one-sentence prompt naming a brief the helper rendered from the skill's own template.

**Architecture:** Two new `agent_tools` modules. `sdd_brief` holds the pure text work: extracting a template's prompt body, filling its closed token set, reading plan-header sections and selecting standards documents. `sdd_gate` is the thin `sdd-gate` command with subcommands `review` and `next`: it reads and appends the plan workspace's ledger, runs the review-package gate through the packaged producer and `agent_tools.review_budget`, calls `workflow-state`, `sdd-workspace` and `task-brief` by name on `PATH`, and writes the brief atomically. The two task templates gain a token for every owner-filled slot, and `sdd/SKILL.md` steps 1–3 and 5 switch from hand assembly to the two calls.

**Tech stack:** Python 3 standard library (`argparse`, `subprocess`, `fnmatch`, `json`, `unittest`), Markdown skill documents, Nix (`lib/agent-tools.nix` command table, home-manager `home.file`), the `agent_tools.instruction_load` gate.

Spec: `.agents/artifacts/specs/2026-10-10-issue-353-sdd-gate-rendered-briefs-design.md`. Its `## Decision ledger` rows D1–D14 are cited by ID; D11–D14 were appended by this plan. Issue: https://github.com/fagenorn/nix-config/issues/353

## Global Constraints

- Base: `cd4b1746e5a844a17f806ccf791e6840e26d4cb2` (`origin/main` at planning). Every byte count in this plan was measured there.
- `review-package`, `artifact-budget` and `workflow-state` are not edited (spec "Out of scope"): no change under `python/agent_tools/review_*.py`, `home/common/agent-skills/scripts/`.
- None of the gate files is edited: `.github/workflows/instruction-budget.yaml`, `python/agent_tools/skill_lint.py`, `python/agent_tools/instruction_load.py`, `.github/branch-protection.json`. `home/common/agent-skills/instruction-load.json` is not edited either.
- No task asks for, applies or assumes the `instruction-budget-raise` label. If the Instruction Budget gate cannot pass, the task follows "Instruction budget" below and otherwise stops and reports; it never raises a ceiling (D13).
- Of the sdd skill's files only `SKILL.md`, `implementer-prompt.md`, `task-reviewer-prompt.md` and `evals/evals.json` are edited. `fix-loop.md`, `re-review-prompt.md`, `final-review.md` and the two final-review prompts are not (D7; the conditional profiles that load them have 23 bytes of headroom).
- `home/common/claude-code/default.nix` is not edited: `sdd-gate` gets no permission allow entry (D11).
- New helper code follows `docs/standards/agent-helpers.md` rules 1–5: package modules, one command-table row, a thin command over importable functions, no `sys.path` edits, no `importlib`, no `__file__` lookups in `python/`; a packaged sibling runs through `agent_tools.siblings.sibling_argv`, an external command by its name on `PATH`.
- Every JSON document the command reads is loaded with `object_pairs_hook=reject_duplicate_keys` and `parse_constant=reject_nonfinite_literal` from `agent_tools.canonical` (rule 4).
- No new test asserts an English phrase of a shipped skill document (rule 6). Fixture templates and goldens under `tests/fixtures/sdd-gate/` are not copies of shipped prose (D9).
- Prose that lands in the repository (docstrings, comments, README and skill sentences) describes the code as it behaves at that task's commit.
- Step names, exactly: `ledger`, `release-worker`, `review-package`, `validate-report`, `budget-check`, `metrics-match`, `render-brief` (`review`); `ledger`, `ledger-complete`, `mark-progress`, `review-package`, `validate-report`, `budget-check`, `metrics-match`, `task-brief`, `prepare-brief`, `register-worker`, `write-brief` (`next`).
- Exit codes, exactly: 0 ready; 3 when `gate` is `decompose_required`; 2 for every other refusal and for an invalid invocation, which prints `sdd-gate: invalid invocation` on stderr and nothing on stdout.
- Every long command, each test command included, runs in the foreground from the worktree root with an explicit timeout above its duration. A worker whose brief carries a `Lifecycle worker:` line runs them through `launch-scope exec … -- <argv>` and commits through `launch-commit … -- <git commit arguments>`; commits are signed and carry the session's trailers.
- Test suites run as `env PYTHONPATH="$PWD/python" python3 -m unittest <file> [-k <pattern>]` (timeout 900 s). `just build` takes timeout 3600 s.
- Final gate, once on the final head (sdd's, not per task): `just build` (timeout 3600 s), `just agent-workflow-tests` (timeout 3600 s) and `just agent-instruction-budget`, which must print `check: pass`.

## Test seams

- The command, run from source as `python -m agent_tools.sdd_gate` in a temporary git repository with a temporary `HOME` and `PATH` shims for `artifact-budget`, `sdd-workspace`, `task-brief` and `workflow-state`: `tests/test_sdd_gate.py`. The lifecycle ledger is driven through `LifecycleHarness`, loaded from `home/common/agent-skills/tests/test_workflow_state.py` exactly as `tests/test_launch_commit.py` loads it.
- The rendering functions, imported from `agent_tools.sdd_brief`: `tests/test_sdd_brief.py`, including the token-identity test over the two shipped templates.
- Skill text and installation: `SDD_MACHINE_TEXT` in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `COMMAND_VOCABULARY` in `test_shell_example_contracts.py`, `LAUNCHER_FLOOR` in `tests/test_agent_tools_launchers.py`, and the Instruction Budget gate, `just agent-instruction-budget`, unchanged.

## Instruction budget

Measured at the base with `agent_tools.instruction_load`: the two owner profiles that load `sdd/SKILL.md` and both task templates have 521 and 522 bytes of hot headroom, and the corpus ceiling has 515. The corpus binds.

| File | Base bytes | After Task 1 | After Task 5 |
|---|---:|---:|---:|
| `sdd/SKILL.md` | 21844 | 21844 | 22120 |
| `sdd/implementer-prompt.md` | 6530 | 6837 | 6837 |
| `sdd/task-reviewer-prompt.md` | 7672 | 7452 | 7450 |
| Sum | 36046 | 36133 (+87) | 36407 (+361) |

The planner applied the exact text Tasks 1 and 5 dictate to a scratch copy of the base: `check: pass` after each, with 154 bytes of corpus headroom left at the end. Task 1 is first so the template growth is measured before any helper code exists; Task 5's text is dictated in full so its figure is known now. The growth is paid for by text the helper makes dead (D13).

If a measured figure is over (a review fix added words, or `main` moved): shorten only sentences this plan introduced, re-measure, and keep every pinned argv, heading, dispatch marker and leaf-agent clause. If the new text cannot shrink further and the gate still fails, stop and report BLOCKED with the gate's `ceiling:` lines. Never edit a gate file or `instruction-load.json`.

## Delivery estimate and boundaries

Estimates: about 22 changed files — two new modules (about 550 lines), two new test files (about 700 lines), ten fixture files, three sdd skill documents, `evals.json`, three existing test files, `lib/agent-tools.nix`, `home/common/agent-skills/default.nix`, `justfile`, two READMEs and the acceptance record. Net skill text +361 bytes (measured). One cumulative review package is expected to fit; the aggregate-growth risk is the two test files, and Task 4 is the largest single diff. Tasks 1–2 (rendering) are deliverable without Tasks 3–5; Task 5 needs all of 1–4.

## Task index

Task 1 — Prompt-body rendering and tokenized templates — `python/agent_tools/sdd_brief.py`, `tests/test_sdd_brief.py`, `home/common/agent-skills/skills/sdd/implementer-prompt.md`, `home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`, `justfile` — full — [task-1.md](2026-10-10-issue-353-sdd-gate-rendered-briefs.tasks/task-1.md)
Task 2 — Plan-header reading and standards selection — `python/agent_tools/sdd_brief.py`, `tests/test_sdd_brief.py` — full — [task-2.md](2026-10-10-issue-353-sdd-gate-rendered-briefs.tasks/task-2.md)
Task 3 — `sdd-gate review` and the golden reviewer brief — `python/agent_tools/sdd_gate.py`, `tests/test_sdd_gate.py`, `tests/fixtures/sdd-gate/**`, `lib/agent-tools.nix`, `tests/test_agent_tools_launchers.py`, `justfile`, `python/README.md` — full — [task-3.md](2026-10-10-issue-353-sdd-gate-rendered-briefs.tasks/task-3.md)
Task 4 — `sdd-gate next` and `task-brief` on `PATH` — `python/agent_tools/sdd_gate.py`, `tests/test_sdd_gate.py`, `tests/fixtures/sdd-gate/**`, `home/common/agent-skills/default.nix`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `python/README.md`, `home/common/agent-skills/README.md` — full — [task-4.md](2026-10-10-issue-353-sdd-gate-rendered-briefs.tasks/task-4.md)
Task 5 — The sdd skill dispatches by rendered brief — `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`, `home/common/agent-skills/skills/sdd/evals/evals.json`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/tests/test_shell_example_contracts.py`, `.agents/artifacts/plans/2026-10-10-issue-353-sdd-gate-rendered-briefs.acceptance.md` — full — [task-5.md](2026-10-10-issue-353-sdd-gate-rendered-briefs.tasks/task-5.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | evidence | Task 5 | Command: count the owner's requests between consecutive implementer dispatches in the owner transcript. Conditions: the next orchestrated nodocom issue with at least 4 tasks, run with the merged helper installed. Threshold: ≤ 6 turns per task (baseline 7.5–13.7). Task 5's implementer writes acceptance-record row AC1 as `not measured — post-merge`, Verdict `unverified` (D9). |
| AC2 | evidence | Task 5 | Command: the median `prompt` length of the owner's implementer and task-review `Agent` calls in that same transcript. Conditions: as AC1. Threshold: ≤ 1,000 characters (baseline 8.0k and 7.8k). Task 5's implementer writes acceptance-record row AC2 as `not measured — post-merge`, Verdict `unverified` (D9). |
| AC3 | code | Task 3 | `tests/test_sdd_gate.py`: `ReviewTest.test_review_renders_the_golden_reviewer_brief` and `ReviewTest.test_an_ungoverned_diff_drops_the_layer_two_document`, with Task 1's `ShippedTemplateTest.test_filling_each_token_with_itself_reproduces_the_prompt_body` in `tests/test_sdd_brief.py`; all run by `just agent-workflow-tests`. |
| AC4 | code | Task 3 | `tests/test_sdd_gate.py`: `ReviewTest.test_an_over_budget_package_is_refused_at_budget_check`, `ReviewTest.test_a_decompose_required_report_is_refused_at_validate_report` and `ReviewTest.test_a_refused_release_is_refused_at_release_worker`, each asserting the exit code, `step`, `gate` and that no brief was written. |
| AC5 | code | Task 5 | `just agent-instruction-budget` (its `lint:` lines are `skill-lint`'s) printing `check: pass`; `SDD_MACHINE_TEXT`'s two `sdd-gate` argv pins in `test_workflow_skill_contracts.py`; `test_shell_example_contracts.py` with `sdd-gate` in the vocabulary; `test_eval_cases.py` over the reworded sdd evals. |

AC1 and AC2 stay open at merge: the pull request body says they are post-merge evidence and repeats how each is measured (D9).

## Decisions

- Command home, collaborators and `--skill-dir`: D1. Two subcommands, one per boundary: D2.
- The ledger as the only state, its four line shapes and repeatable steps: D3. Refusal object, exit codes, registration last: D4.
- Which bytes a brief contains: D5, with the token check placed on the template body by D12. Standards in both briefs: D6.
- Only the implementer and first-pass review dispatches move: D7. Behaviour without a lifecycle identity: D8.
- What is verified in code and what stays post-merge evidence: D9. Reusing an existing package: D10.
- Owner context arrives as `--context-file`, not `--context-stdin`: D11 (appended by this plan; it amends the spec's Invocation).
- Parser, output and selection details the spec left open: D12 (appended by this plan).
- The byte budget, what is cut to pay for the new text, and the stop rule: D13 (appended by this plan).
- How the tests force the over-budget refusal and compare the golden: D14 (appended by this plan).

---
