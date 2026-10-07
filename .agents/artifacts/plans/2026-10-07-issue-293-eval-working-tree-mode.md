# Eval Working-Tree Mode and Baseline Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `run-eval.sh` evaluates a checkout's skills through `EVAL_TREE` and records tokens in every row. `ship-issue`, `sdd`, `ship-release` and `orchestrate-issues` each gain a scripted `pipeline` case, and a committed Sonnet/Opus baseline covers the five pipeline skills (#293, slice S3 of #291).

**Architecture:** Working-tree mode is one setup prologue in `run-eval.sh`. It validates the tree, builds one temp root holding `config/` (the `CLAUDE_CONFIG_DIR`) and `bin/` (the command-table shims), probes auth, and removes the root on every exit path. After that it shares every code path with deployed mode. Both modes switch to `--output-format json`, and the row writer adds the tree and token fields. Three new closed setup kinds take their committed inputs from `evals/setups/issue-3/`. Spec: `.agents/artifacts/specs/2026-10-07-issue-293-eval-working-tree-mode-design.md` (ledger D1–D22).

**Tech stack:** Bash (GNU and BSD portable), `jq`, git, Python 3 standard-library `unittest`, the `claude` CLI (`-p --output-format json`).

## Global Constraints

- One new runner variable, `EVAL_TREE`, and one optional override, `EVAL_SETTINGS`. With `EVAL_TREE` unset, every existing behaviour holds, apart from the JSON output and the new row fields (spec "Decisions").
- `run-eval.sh` keeps exactly one `resolve-project resolve --repo-root "$REPO"` and the existing refusal block, byte for byte. `test_workflow_skill_contracts.test_eval_runner_reports_a_resolver_refusal_without_a_second_resolution` pins both.
- No change to any skill's `SKILL.md` or support files, any helper's behaviour, `fixture-repo/`, or any `.nix` file (spec "Out of scope"). Eval data (`evals.json`) and `assert-lib.sh` are the harness, not skill instructions: Task 3 changes them, per D19.
- Scripts are portable between GNU and BSD: `mktemp -d "<dir>/name.XXXXXX"`, `cd … && pwd -P` instead of `realpath`, and no `sed -i`, `readlink -f` or `find -printf`. `just agent-workflow-tests` runs on ubuntu CI with no `claude`, no `~/.claude` and no `~/.agents`.
- Eval text in `evals.json` never contains `resolve-bindings`, `skills.config.json`, `helper missing`, `auto-detect absent` or `default GitHub`. Orchestrate expected outputs never contain `workflow-state launch`, `workflow-state reconcile`, `override`, `resume before fresh`, `occupied slots`, `run is drained`, `result_source`, `permits a retry`, `attempts 1 and 2` or `earliest armed deadline`.
- Run every test command from the worktree root, in the foreground, with an explicit timeout: unittest and bash tests `timeout 600`.
- Final-gate verification, run once by sdd on the final head and not per task: `just build` (timeout 3600 s) and `just agent-workflow-tests` (timeout 3600 s).

## Test seams

- The runner as a black box: `home/common/agent-skills/evals/tests/test-run-eval-tree.sh`, which copies `evals/` and runs it with a fake `claude` first on `PATH` (spec "Test seams", per D16).
- The case files as data: `home/common/agent-skills/tests/test_eval_cases.py` (spec "Test seams").
- The R8 contract in `home/common/agent-skills/tests/test_ship_release_contracts.py`, narrowed per D8.
- Real model runs only in Task 4. The evidence AC is graded from the committed rows.

## Delivery estimate and boundaries

Estimates: about 10 changed product files and 6 new input files. That is roughly 250 runner lines, a 300-line bash test, 120 unittest lines, four cases and a 14-row results file. One slice. The largest growth risk is the bash test, which stays well under the review-package member limit.

## Task index

Task 1 — Working-tree mode, JSON token capture and committed results — home/common/agent-skills/evals/run-eval.sh, home/common/agent-skills/evals/assert-lib.sh, home/common/agent-skills/evals/.gitignore, home/common/agent-skills/evals/README.md, home/common/agent-skills/evals/results/results.jsonl, home/common/agent-skills/evals/tests/test-run-eval-tree.sh, home/common/agent-skills/evals/tests/fixtures/settings.json, justfile — full — [task-1.md](2026-10-07-issue-293-eval-working-tree-mode.tasks/task-1.md)
Task 2 — Issue-3 setup inputs and three setup kinds — home/common/agent-skills/evals/setups/issue-3/**, home/common/agent-skills/evals/run-eval.sh, home/common/agent-skills/evals/assert-lib.sh, home/common/agent-skills/evals/README.md, home/common/agent-skills/evals/tests/test-run-eval-tree.sh, home/common/agent-skills/tests/test_eval_cases.py, justfile — full — [task-2.md](2026-10-07-issue-293-eval-working-tree-mode.tasks/task-2.md)
Task 3 — Four pipeline cases, the narrowed R8 and the from-issue grader repair — home/common/agent-skills/skills/{ship-issue,sdd,ship-release,from-issue}/evals/evals.json, home/common/claude-code/skills/orchestrate-issues/evals/evals.json, home/common/agent-skills/evals/assert-lib.sh, home/common/agent-skills/tests/test_eval_cases.py, home/common/agent-skills/tests/test_ship_release_contracts.py — full — [task-3.md](2026-10-07-issue-293-eval-working-tree-mode.tasks/task-3.md)
Task 4 — Record the Sonnet/Opus baseline — home/common/agent-skills/evals/results/results.jsonl, .agents/artifacts/plans/2026-10-07-issue-293-eval-working-tree-mode.acceptance.md — full — [task-4.md](2026-10-07-issue-293-eval-working-tree-mode.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `home/common/agent-skills/evals/tests/test-run-eval-tree.sh` under `just agent-workflow-tests`. It covers four exit paths: claude exit 0, claude non-zero, auth refusal, and SIGTERM. It also covers an empty-stdout run that still writes its row |
| AC2 | code | Task 3 | `EvalCasesTest.test_each_pipeline_skill_has_a_scripted_pipeline_case` in `home/common/agent-skills/tests/test_eval_cases.py` under `just agent-workflow-tests` |
| AC3 | evidence | Task 4 | Command: the `jq -s` pair query in Task 4 Step 5, run over the committed `home/common/agent-skills/evals/results/results.jsonl`. Conditions: rows with `ts >= "2026-10-07"`, `mode == "pipeline"`, a non-null `verdict`, numeric `wall_s` and numeric `input_tokens` (D10). Threshold: all 10 pairs (5 skills × `sonnet`, `opus`) are present, and the query prints `10`. The implementer fills in acceptance-record row `AC3` |
| AC4 | human | Task 1 | Due only if credentials do not carry over, and today they do not. The user, on mbp, runs `claude setup-token` once and exports `CLAUDE_CODE_OAUTH_TOKEN`. After that, `EVAL_TREE=. just evals from-issue 1` passes the auth probe, and an uncommitted marker line in the working-tree `from-issue/SKILL.md` appears in that run's transcript. Task 1's README and its probe message name the step. Ship reports AC4 as `human_pending` in the PR body. No agent runs it |

## Decisions

Task 1 rests on D1–D6, D13, D14 and D16. Task 2 rests on D7, D15 and D16. Task 3 rests on D7, D8, D12, D15, D18 and D19. Task 4 rests on D9, D10, D13, D17 and D19. Rows D12–D17 were appended to the spec's ledger during planning, and D18–D19 during standards review.

## Standards review provenance

- Reviewer: Codex (gpt-6-astra, xhigh), isolated and read-only, against base `f0e47f5c`. No fallback reviewer was used.
- Findings: 2 Blocking and 5 Should-fix, no Discussion. 7 accepted, 0 rejected, 0 deferred. Each was re-verified against the live files before it was applied.
- R293-01 (Blocking), accepted: `usage_json` slurps, so it prints exactly one object even for empty stdout. Task 1 adds an empty-result scenario asserting that the row survives with null usage.
- R293-02 (Blocking), accepted: the orchestrate-issues case grades the builder refusal and the `delivery_contract` action, not dispatches (D18; the spec's case row was updated).
- R293-03 (Should-fix), accepted: Task 4's mode lines pin `EVAL_TRIALS=1` and unset `EVAL_SETTINGS` and `CLAUDE_CONFIG_DIR`. Deployed mode also unsets `EVAL_TREE`. This applies to reruns too.
- R293-04 (Should-fix), accepted: Task 3 Step 4 repairs the from-issue artifact paths and makes `plan_tasks_verifiable` read indexed members, with positive and negative checks (D19).
- R293-05 (Should-fix), accepted: the ship-issue assert requires `verified-tree check --verification test` to answer `verified`.
- R293-06 (Should-fix), accepted: the setup task commits no old-flag test, and criterion 2 is probed from outside the committed tree.
- R293-07 (Should-fix), accepted: the README "Cheap-first" claim and ship-release's `notes` are scoped to the cases they describe.

---
