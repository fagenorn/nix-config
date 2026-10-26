# Path-Conditional Verification Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A change that touches none of a verification id's listed paths gets that id reported as skipped, with its authored reason, never as passed. The project contract declares the condition, `resolve-project` validates it, and `verified-tree` plans which ids run, so sdd and ship run only those ids.

**Architecture:** Task 1 teaches `resolve-project` the optional `bindings.workflow.verification_conditions` member: a grammar with named violations, passed through as authored. It also moves the any-path × any-glob matcher into `resolve_project`, and `lane-triage` reuses it. Task 2 makes `verified-tree` resolve the worktree itself and drop `--verification`. It computes the change from the merge base with `origin/<integration_branch>` and prints `{run, skipped, status, tree}`. `record` writes only `run`. Task 3 moves sdd's Final verification and ship-issue's Phase 2 onto the new interface within the existing instruction budget.

**Tech stack:** Python 3 standard library (`unittest`, `fnmatch`, `subprocess`), Git plumbing (`merge-base`, `diff-tree -r --no-renames --name-only -z`, `write-tree` on a temporary index), Markdown skill documents, the `agent_tools.instruction_load` gate, and Just.

Spec: `.agents/artifacts/specs/2026-10-26-issue-437-conditional-verification-design.md`. This plan cites its `## Decision ledger` rows by ID and appends D14 and D15. Issue: https://github.com/fagenorn/nix-config/issues/437.

## Global Constraints

- Base `ca6ba1ae2b37e56c1361a8656c29af1f39b89348` (`origin/main` at planning). Tasks land in index order, each on top of the one before.
- The contract grammar, pointers and repair ids are the spec's (§ Contract grammar, per D1 and D2). The change, matching rule and failure cases are the spec's (§ The change and the matching rule, per D3 and D4, refined by D14). The interface and record are the spec's (§ `verified-tree` interface, per D5 and D6).
- No task edits `.agents/project.json` (D10). No task edits `home/common/agent-skills/evals/fixture-repo/.agents/project.json`, `python/agent_tools/adopt_apply.py`, `python/agent_tools/conformance_checks.py`, `home/common/agent-skills/scripts/workflow_delivery_build.py` or `home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md` (D8, D9). No task edits `.github/` or `lib/agent-tools.nix`, whose `verified-tree` row is unchanged.
- `home/common/agent-skills/instruction-load.json` ends unchanged from base, because no ceiling is raised (D7, D15). Only the user applies the `instruction-budget-raise` label: never apply it, and never ask a tool to apply it.
- `verified-tree` keeps the record schema `verified-tree/v1` and its strict parsing, and gets no compatibility handling for `--verification` (D6, D13).
- Comments, docstrings, README text and skill sentences describe the code as it behaves at that task's commit. In code and tests, write "issue 437", never a bare `#437`. No `TODO` or `FIXME`.
- Run every long command, each test and gate included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commits go through `launch-commit … -- <git commit args>`, signed, and end with the session's trailers. Scratch files live under the root that `launch-scope scratch …` prints.
- Focused test form (timeout 900 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest <test files> [-k <name>] 2>&1 | tail -6'`.
- Final gate (sdd, once on the final head): `just agent-workflow-tests` (about 20 min; timeout 3600 s; ends `OK (skipped=…)`) and `just build` (timeout 3600 s). On this host that builds the darwin configuration. The installed `verified-tree` and skills are still the base ones until `just switch`, so the final gate itself runs the old `--verification` form (D13).

## Test seams

- `verified-tree` at the CLI level: `python -m agent_tools.verified_tree` in a throwaway copy of the eval fixture project. The copy's contract gains a second id, `suite`, with a condition. A temporary `HOME` holds the committed platform manifest, and `refs/remotes/origin/main` points at the base commit (`tests/test_verified_tree.py`, `VerifiedTreeTest`; per D12).
- `resolve-project resolve` as a subprocess against a temporary root holding a copy of this repository's contract (`home/common/agent-skills/tests/test_resolve_project.py`, new class `VerificationConditionsTest`, modelled on `LightLaneTest`).
- The shared matcher, through `lane-triage`'s unchanged suite (`tests/test_lane_triage.py`, per D3).
- Skill machine text through `SDD_MACHINE_TEXT` and `SHIP_ISSUE_MACHINE_TEXT` (`home/common/agent-skills/tests/test_workflow_skill_contracts.py`, per D15).
- Gates: `just agent-instruction-budget` with no label (D7), `just agent-workflow-tests` and `just build`.

## Delivery estimate and boundaries

These are estimates from a measured prototype at base. The plan touches 10 product files, plus this plan and the spec ledger. `resolve_project.py` grows by about 60 lines, `verified_tree.py` by about 50 net (its docstring rewritten), and `lane_triage.py` shrinks by 2. `test_resolve_project.py` grows by about 105 lines. `tests/test_verified_tree.py` is rewritten onto the fixture harness, about +190/−90. `python/README.md` changes one section, and the skill documents change by −16 B and +137 B. That is about 640 changed lines, or 35 KB of diff, in one review package, with no file record near the 64 KB member limit. Task 1 can be delivered alone. Task 2 needs Task 1's matcher and grammar. Task 3 describes Task 2's interface.

## Task index

Task 1 — `resolve-project` accepts `verification_conditions`; one shared glob matcher — `python/agent_tools/resolve_project.py`, `python/agent_tools/lane_triage.py`, `home/common/agent-skills/tests/test_resolve_project.py` — full — [task-1.md](2026-10-26-issue-437-conditional-verification.tasks/task-1.md)
Task 2 — `verified-tree` resolves its own plan and records only what ran — `python/agent_tools/verified_tree.py`, `tests/test_verified_tree.py`, `python/README.md` — full — [task-2.md](2026-10-26-issue-437-conditional-verification.tasks/task-2.md)
Task 3 — sdd and ship run the plan's `run` ids and record each skip — `home/common/agent-skills/skills/sdd/final-review.md`, `home/common/agent-skills/skills/ship-issue/SKILL.md`, `home/common/agent-skills/skills/ship-issue/evals/evals.json`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-3.md](2026-10-26-issue-437-conditional-verification.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 2 | `tests/test_verified_tree.py::VerifiedTreeTest::test_a_change_outside_every_listed_path_skips_the_conditional_id`: `run` is `["test"]` and `skipped` is `[{"id": "suite", "reason": <authored reason>}]`; the record holds `["test"]`; the next `check` is `verified` with the same `skipped`. Runs under `just agent-workflow-tests` |
| AC2 | code | Task 2 | `tests/test_verified_tree.py::VerifiedTreeTest::test_a_change_to_a_listed_path_runs_the_conditional_id` (committed edit, staged new file, tracked working-tree edit, deletion, rename out of a listed directory, nested path under a `*` glob) and `::test_a_pass_that_skipped_the_conditional_id_is_unverified_once_a_listed_path_changes`. Runs under `just agent-workflow-tests` |
| AC3 | code | Task 1 | `home/common/agent-skills/tests/test_resolve_project.py::VerificationConditionsTest::test_a_valid_member_round_trips_unchanged` and `::test_each_malformed_member_is_refused_with_its_pointer`. The second has one row per grammar case, the issue's empty path list, absolute path and unknown key among them, each asserting `invalid_contract`, the repair id and the single pointer. Runs under `just agent-workflow-tests` |
| AC4 | human | Task 1 | The issue tags this `[code]`; the map grades it `human` per D10, so it stays `human_pending`. Judgment by the owner: after approving the list in the PR (AC5) and running `just switch`, the owner (or a session the owner directs) lands a follow-up commit that authors exactly the approved `verification_conditions` object in `.agents/project.json`. That commit cites `resolve-project resolve --repo-root <checkout>` exiting 0 at its head. No task of this plan does it, and ship holds the issue `needs-verification` |
| AC5 | human | Task 1 | Judgment by the owner, reviewing the PR: the spec's § Proposed gated paths list (D11) is what the owner wants gated. Ship reports it `human_pending` |

## Decisions

- Grammar, named violations and pass-through per D1 and D2; the one shared matcher per D3 (Task 1).
- Change computation per D4 and D14; self-resolution, the `{run, skipped, status, tree}` output and the dropped `--verification` per D5 and D13; the v1 record holding only `run` per D6; the fixture-copy test seam per D12 (Task 2).
- Consumers run `run` and record each skip per D7; the Declared verification line is unchanged per D8; other readers unchanged per D9; the pin form and the measured wording per D15 (Task 3).
- Nothing authored in this repository's contract, and AC4 graded `human`, per D10; the proposed list per D11 (AC4, AC5).

---
