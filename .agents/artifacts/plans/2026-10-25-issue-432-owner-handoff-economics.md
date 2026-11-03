# Owner Hand-off Economics Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `just agent-costs --report owners` prices owner lineages in list-price dollars per delivered issue and replays them under counterfactual hand-off policies. Eval 8 runs a real lifecycle-identity pipeline that calibrates the replay. Only the candidates the replay keeps are built, and they are confirmed against a live baseline arm, with the A/B and sweep report committed.

**Architecture:** Measurement first (D1): a per-model price table (D2) and a shared call reader (D19) feed an owner report of lineages, descendants, delivery and eval arms (D3, D4, D17, D20). A shift-model replay prices the sweep and each candidate on paired per-issue differences (D5, D7, D8, D18, D21) through `agent_tools.phase_budget`, the one policy home of gate and meter, overridable by `AGENT_PHASE_BUDGET` (D6). The harness gains tree shims, `EVAL_POLICY` and eval 8 (D15, D16); kept candidates ship one commit each (D9–D14), checked by live arms (D22, D23).

**Tech stack:** Python 3.13 standard library (`dataclasses`, `statistics`, `json`, `functools`, `argparse`), `unittest` driving `python -m agent_tools.<module>` from source, Bash and `jq`, Nix (`just build`), Just.

Spec: `.agents/artifacts/specs/2026-10-25-issue-432-owner-handoff-economics-design.md`. This plan appends ledger rows D19–D23, and its standards review D24–D27. Issue: https://github.com/fagenorn/nix-config/issues/432. Acceptance record and A/B report: `.agents/artifacts/plans/2026-10-25-issue-432-owner-handoff-economics.acceptance.md`. Task 6 creates it and Task 8 completes it.

## Global Constraints

- Base `48481846` (`origin/main` at planning). Tasks land in index order. One exception: right after Task 6 is committed and reviewed, the sdd controller itself runs Task 8 § Part A (the baseline arm), then continues with Task 7 (D22).
- Python standard library only. `home/common/claude-code/lifecycle_guard.py` and the guard's hook entry are not edited. `--report cache`'s `--context-threshold` default stays 120,000.
- `docs/standards/agent-helpers.md` rules 1–6 bind every new module and test: a parser's `prog` is the command name; package code has no `sys.path` edit, no `importlib` load and no `__file__` lookup; tests run `python -m agent_tools.<module>` or import modules; skill-text tests pin only argv and vetted shell examples, and phrase pins are deleted in the slice that slims their text.
- Comments, docstrings and README sentences describe the code as it behaves at that task's commit. Write "issue 432", never a bare `#432`. No `TODO`/`FIXME`, no mutable default argument, and no knob, field or flag for a candidate that is not kept (D9).
- Pricing per D2. Spend per D15: `EVAL_MODEL=opus`, at most $40 per trial and $160 in total. Live arms per D22: never start a trial that cannot finish before `deadline_at`, and record a missing trial as an evidence gap, never a sample.
- Never run `just switch`, never touch `~/.agents/share/host-declaration.json`, never add the `instruction-budget-raise` label. Hot instruction-budget headroom is about 2 B (from-issue-controller), 55 B (implementation-owner) and 567 B (orchestrated-issue-owner). Every skill-text edit is byte-neutral or smaller per profile, and `just agent-instruction-budget` runs after it.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commits go through `launch-commit … -- <git commit args>`, SSH-signed, ending with the session's two trailer lines. Scratch files live under the root that `launch-scope scratch` prints.
- **Report tests** (timeout 900 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_agent_costs.py tests/test_agent_owner_report.py tests/test_agent_owner_replay.py 2>&1 | tail -4'` (name only the files that exist at that task).
- **Meter and policy tests** (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_phase_budget.py tests/test_context_meter.py 2>&1 | tail -4'`.
- **Gate tests** (timeout 2400 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_attempt_migration.py 2>&1 | tail -4'`.
- **Harness tests** (timeout 900 s): `bash -c 'set -o pipefail; bash home/common/agent-skills/evals/tests/test-run-eval-tree.sh 2>&1 | tail -20'` and `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_eval_cases.py 2>&1 | tail -4'`.
- **Build** (timeout 3600 s): `bash -c 'set -o pipefail; just build 2>&1 | tail -3'`.
- Final gate (sdd, once on the final head): `just build`, `just agent-workflow-tests` (timeout 3600 s each) and `just agent-instruction-budget`, each passing.

## Test seams

- Seam 1: `python -m agent_tools.agent_costs --report owners` over fixture transcripts in a temporary projects dir, with `.meta.json` parents and production-shaped usage (per D19, D20).
- Seam 2: the replay through `agent_owner_replay` functions on constructed lineages, and the CLI's `--policy`/`--sweep` JSON.
- Seam 3: `phase_budget` imported (grammar, `AGENT_PHASE_BUDGET`, thresholds, `select_phase_action`'s moved table).
- Seam 4: `workflow-state progress` and `suspend` through `test_workflow_state.py`'s `LifecycleHarness` (phase + 1 defaults; identity derivation and the cap if kept).
- Seam 5: `python -m agent_tools.context_meter` through `tests/test_context_meter.py`'s `MeterHarness` (policy override, phase tracking, old records; the baseline if kept).
- Seam 6: `test-run-eval-tree.sh` with its fake `claude`, and `test_eval_cases.py`.
- Seam 7: skill text through `test_workflow_skill_contracts.py` and `test_shell_example_contracts.py` (if a skill-text candidate is kept).
- Seam 8: the final gate, and the eval-8 arms on mbp with the A/B report.

## Delivery estimate and boundaries

Estimates: about 35 changed files plus the record and results rows; new modules `model_pricing.py` (~120 lines), `transcript_calls.py` (~200, mostly moved), `agent_owner_report.py` (~650), `agent_owner_replay.py` (~600); ~1,700 test lines; 20–200 lines per kept candidate. Likely over one review package. Independently deliverable slices, where any split cuts: S1 = Tasks 1–2, S2 = 3–4, S3 = 5–6, S4 = 7 (a commit per kept candidate), S5 = 8.

## Task index

Task 1 — Per-model pricing and the shared call reader — `python/agent_tools/model_pricing.py`, `python/agent_tools/transcript_calls.py`, `python/agent_tools/agent_costs.py`, `python/agent_tools/agent_cache_report.py`, `tests/test_agent_costs.py`, `python/README.md` — full — [task-1.md](2026-10-25-issue-432-owner-handoff-economics.tasks/task-1.md)
Task 2 — The owner report: lineages, delivery, eval grouping — `python/agent_tools/agent_owner_report.py`, `python/agent_tools/context_meter_commands.py`, `python/agent_tools/agent_costs.py`, `tests/owner_transcripts.py`, `tests/test_agent_owner_report.py`, `justfile`, `python/README.md` — full — [task-2.md](2026-10-25-issue-432-owner-handoff-economics.tasks/task-2.md)
Task 3 — The policy home: `PhaseBudget`, `AGENT_PHASE_BUDGET` and phase-aware meter — `python/agent_tools/phase_budget.py`, `home/common/agent-skills/scripts/workflow-state.py`, `python/agent_tools/context_meter.py`, `python/agent_tools/context_meter_crossing.py`, `tests/test_phase_budget.py`, `tests/test_context_meter.py`, `home/common/agent-skills/tests/test_workflow_state.py`, `justfile`, `python/README.md`, `home/common/claude-code/README.md` — full — [task-3.md](2026-10-25-issue-432-owner-handoff-economics.tasks/task-3.md)
Task 4 — The replay, the sweep and the keep rule — `python/agent_tools/agent_owner_replay.py`, `python/agent_tools/agent_owner_report.py`, `python/agent_tools/agent_costs.py`, `tests/test_agent_owner_replay.py`, `justfile`, `python/README.md` — full — [task-4.md](2026-10-25-issue-432-owner-handoff-economics.tasks/task-4.md)
Task 5 — Tree-mode `workflow-state` shim, derived settings and `EVAL_POLICY` — `home/common/agent-skills/evals/run-eval.sh`, `home/common/agent-skills/evals/tests/test-run-eval-tree.sh`, `home/common/agent-skills/evals/tests/fixtures/settings.json`, `home/common/agent-skills/evals/README.md` — full — [task-5.md](2026-10-25-issue-432-owner-handoff-economics.tasks/task-5.md)
Task 6 — Eval 8, the `tracked-issue` setup and the acquisition probe — `home/common/agent-skills/evals/run-eval.sh`, `home/common/agent-skills/evals/assert-lib.sh`, `home/common/agent-skills/evals/setups/tracked-issue/setup.sh`, `home/common/agent-skills/evals/setups/tracked-issue/gh.py`, `home/common/agent-skills/evals/fixture-repo/issues/004-priorities-and-due-dates.md`, `home/common/agent-skills/evals/fixture-repo/tests/test_acceptance.py`, `home/common/agent-skills/skills/from-issue/evals/evals.json`, `home/common/agent-skills/tests/test_eval_cases.py`, `home/common/agent-skills/evals/tests/test-run-eval-tree.sh`, `home/common/agent-skills/evals/README.md`, `.agents/artifacts/plans/2026-10-25-issue-432-owner-handoff-economics.acceptance.md` — full — [task-6.md](2026-10-25-issue-432-owner-handoff-economics.tasks/task-6.md)
Task 7 — Replay verdicts, then only the kept candidates (one commit each) — `.agents/artifacts/plans/2026-10-25-issue-432-owner-handoff-economics.acceptance.md`, and per kept candidate: `python/agent_tools/phase_budget.py`, `python/agent_tools/context_meter.py`, `python/agent_tools/context_meter_crossing.py`, `home/common/agent-skills/scripts/workflow-state.py`, `python/agent_tools/attempt_store.py`, `python/agent_tools/attempt_identity.py`, `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/from-issue/delegated-owner.md`, `home/common/agent-skills/skills/from-issue/resume-pack.md`, their tests and READMEs — full — [task-7.md](2026-10-25-issue-432-owner-handoff-economics.tasks/task-7.md)
Task 8 — Live arms, the A/B and sweep report and the verdict — `.agents/artifacts/plans/2026-10-25-issue-432-owner-handoff-economics.acceptance.md`, `home/common/agent-skills/evals/results/results.jsonl` — full — [task-8.md](2026-10-25-issue-432-owner-handoff-economics.tasks/task-8.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 6 | Eval 8's asserts 1–5 (`from-issue/evals/evals.json` id 8: lifecycle ledger phase ≥ 6, every owner gate call measured, an owner call ≥ 110,000, Phase 7 entered, an owner long child wait) and its shape test in `test_eval_cases.py`. They are graded on every Task-8 trial and recorded in acceptance-record row `AC1`. |
| AC2 | code | Task 2 | `tests/test_agent_owner_report.py`: boot 29k→98k, 6-minute-gap rewrite priced as a 5-minute write, two-launch hand-off chain with a worker child, delivered/undelivered dollar formula, eval grouping (2 arms × 2 trials, mean and sd; an interrupted `PASS` trial left out, D26), approximate pricing. Run by `just agent-workflow-tests`. |
| AC3 | code | Task 4 | `tests/test_agent_owner_replay.py` covers every toggle (threshold sweep and per-phase, boot slimming, guard, cap, keepalive, help), and Task 5's `test-run-eval-tree.sh` covers the `EVAL_POLICY` cases. Both run by `just agent-workflow-tests`. |
| AC4 | evidence | Task 8 | `just agent-costs --report owners --sweep --days 14` on mbp at the final head, plus the eval-mode report. Acceptance-record row `AC4` and § A/B and sweep report: baseline and each candidate's $/delivered issue with sd, kept and rejected candidates with numbers, a sweep covering 90k, 110k, 140k, 170k (and the per-phase grid when boots differ > 25%), and the chosen value with the reason. |
| AC5 | code | Task 7 | Each kept candidate's contract tests (named in Task 7), plus `just agent-workflow-tests`, `just agent-instruction-budget` (no `--raise-label`) and `just build` exiting 0 on the final head. |
| AC6 | evidence | Task 8 | Command, at the final head after both arms: `just agent-costs --report owners --format json --eval-results home/common/agent-skills/evals/results/results.jsonl --eval from-issue:8 >"$SCRATCH/eval-arms.json"`, then `jq -c '.arms[]' "$SCRATCH/eval-arms.json"`. Conditions: eval 8 in tree mode on mbp, `EVAL_MODEL=opus`, `EVAL_MAX_USD=40`; arms `<Task 6 commit, 12 chars>/default` (baseline) and `<final head, 12 chars>/default` (candidate), two trials each (D15, D22). Met when each arm has `n` 2 and `delivered` 2 (only completed `PASS` trials count, D26) and the candidate's `dollars_per_delivered` is below the baseline's. Otherwise, or with no candidate kept, not met (D23, D26). Acceptance-record row `AC6`. |

## Decisions

- Task 1 per D1, D2, D19; Task 2 per D3, D4, D17, D20; Task 3 per D6, D21; Task 4 per D5, D7, D8, D18, D21; Task 5 per D16; Task 6 per D15; Task 7 per D9–D14, D21; Task 8 per D8, D22, D23.
- Standards review: replay comparator and final subset per D24; cap inputs, migration and reset per D25; trial eligibility and baseline-only prediction per D26; `never` per D27.

## Standards review provenance

Reviewer `Codex` (gpt-6-astra, xhigh), isolated read-only, no focus, no fallback; base `48481846`, reviewed head `a8b3c000`. 7 Blocking and 3 Should-fix findings, no Discussion: 10 accepted, 0 rejected, 0 deferred (D24–D27).

---
