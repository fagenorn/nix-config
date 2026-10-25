# Acceptance record — issue 432

Taken on host mbp; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/432).

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] Eval 8 launches owners with lifecycle identity (direct `--auto`) on a fixture issue that crosses 110k, reaches Phase 6, enters Phase 7, and includes an owner wait on a child over 300 s — measured: a trial's asserts over its transcripts (measured gate notes, peak, ledger phase, long child wait) | code | Eval 8's asserts 1–5 (`from-issue/evals/evals.json` id 8: lifecycle ledger phase ≥ 6, every owner gate call measured, an owner call ≥ 110,000, Phase 7 entered, an owner long child wait) and its shape test in `test_eval_cases.py`. They are graded on every Task-8 trial. | pending | pending | pending | pending |
| AC2 | [code] `agent-costs --report owners` reports list-price dollars per delivered issue at per-model prices, peak context and per-issue or per-trial variance, for live transcripts and for eval runs (`--eval-results`) — measured: unit tests on fixture transcripts covering a boot, a cache rewrite after a TTL gap, a hand-off chain and eval grouping | code | `tests/test_agent_owner_report.py`: boot 29k→98k, 6-minute-gap rewrite priced as a 5-minute write, two-launch hand-off chain with a worker child, delivered/undelivered dollar formula, eval grouping (2 arms × 2 trials, mean and sd; an interrupted `PASS` trial left out, D26), approximate pricing. Run by `just agent-workflow-tests`. | pending | pending | pending | pending |
| AC3 | [code] Each candidate is a replay toggle that applies to any eval run or live corpus: the threshold with the sweep and the per-phase variant, boot slimming, the guard, the cap, keepalive and help; the live harness toggles the threshold knobs and any kept guard or cap through `EVAL_POLICY`, and tree-revision candidates through `EVAL_TREE` — measured: replay unit tests and the harness test | code | `tests/test_agent_owner_replay.py` covers every toggle (threshold sweep and per-phase, boot slimming, guard, cap, keepalive, help), and `test-run-eval-tree.sh` covers the `EVAL_POLICY` cases. Both run by `just agent-workflow-tests`. | pending | pending | pending | pending |
| AC4 | [evidence] The A/B report gives the baseline's and each candidate's dollars per delivered issue with variance, which were kept and which rejected with their numbers, and the threshold sweep (at least 90k, 110k, 140k and 170k, and the per-phase grid when boots differ by phase); the report names the chosen value and why — measured: the report | evidence | `just agent-costs --report owners --sweep --days 14` on mbp at the final head, plus the eval-mode report. § A/B and sweep report: baseline and each candidate's $/delivered issue with sd, kept and rejected candidates with numbers, a sweep covering 90k, 110k, 140k, 170k (and the per-phase grid when boots differ > 25%), and the chosen value with the reason. | pending | pending | pending | pending |
| AC5 | [code] Kept candidates are merged with contract tests; `just agent-workflow-tests`, `just agent-instruction-budget` (no raise label) and `just build` pass — measured: those commands | code | Each kept candidate's contract tests (named in Task 7), plus `just agent-workflow-tests`, `just agent-instruction-budget` (no `--raise-label`) and `just build` exiting 0 on the final head. | pending | pending | pending | pending |
| AC6 | [evidence] In eval 8, the candidate arm's mean dollars per delivered trial is below the baseline arm's, and every trial's verdict is `PASS`; with no candidate kept the report says so and AC6 is not met — measured: eval 8 on mbp | evidence | At the final head after both arms: `just agent-costs --report owners --format json --eval-results home/common/agent-skills/evals/results/results.jsonl --eval from-issue:8 >"$SCRATCH/eval-arms.json"`, then `jq -c '.arms[]' "$SCRATCH/eval-arms.json"`. Conditions: eval 8 in tree mode on mbp, `EVAL_MODEL=opus`, `EVAL_MAX_USD=40`; arms `<Task 6 commit, 12 chars>/default` (baseline) and `<final head, 12 chars>/default` (candidate), two trials each (D15, D22). Met when each arm has `n` 2 and `delivered` 2 (only completed `PASS` trials count, D26) and the candidate's `dollars_per_delivered` is below the baseline's. Otherwise, or with no candidate kept, not met (D23, D26). | pending | pending | pending | pending |

## Acquisition probe

Taken on host mbp before any paid trial, with no model spend. The sandbox is built the way `run_trial` builds one: the fixture copied, `git init -b main`, the initial commit, a bare origin and a push. Then `evals/setups/tracked-issue/setup.sh <WORK> <REPO>` ran (it wrote `<WORK>/bin/gh`, bound the tracker to `github` and committed `chore: track issues on github` to the sandbox's `main`). The sandbox and its ledger lived under a launch scratch directory, and the repository's own ledger was never named. `HOME` was a scratch directory holding only the platform manifest and host declaration, so no file under `~/.agents/share` was read or written.

Each call was `PATH=<WORK>/bin:$PATH` and the tree's `workflow-state` (`PYTHONPATH=$PWD/python python3 -P home/common/agent-skills/scripts/workflow-state.py`), with acquire-direct.md's interface_version 2 request for issue 4 and `attempt_budget_minutes` 180:

```text
workflow-state direct-owner --repo-root <REPO> --request-file - < request
```

| Call | Request adds | Reply |
|------|--------------|-------|
| 1 | nothing (all observations `null`) | `observe`: `[{"kind":"tracker"}]` |
| 2 | `tracker` = `{"issue": 4, "state": "open", "open_blockers": [], "decision_blockers": []}`, from `gh issue view 4 --json state` (`{"state":"OPEN"}`) and the empty `gh api …/issues/4/dependencies/blocked_by` and `…/sub_issues` reads (`[]`) | `observe`: `[{"kind":"forge_pr","path":"issue-4-"}]`, `run_id` now set |
| 3 | `forge` = `{"state": "none", "url": null, "merge_sha": null}`, from `gh pr list --state all --search issue-4- --json number,title,headRefName,state` (`[]`) | `observe`: `[{"kind":"candidate_worktree"}]` |
| 4 | `worktree` = `{"issue": 4, "recorded": null, "candidate": {"path": "<REPO>/.worktrees/worktree-issue-4-priorities", "state": "available"}}`, after checking that neither the path nor the branch `worktree-issue-4-priorities` existed | `observe`: `[{"kind":"delivery_contract","subject_id":"4",…}]` |
| 5 | `delivery_contract` and `authorization_intents`, from `workflow-state build-delivery --repo-root <REPO> --kind contract --input -` fed `{"issue": 4, "worktree": "<REPO>/.worktrees/worktree-issue-4-priorities", "source_kind": "explicit_user", "source_reference": "invocation:/from-issue 4 --auto"}` | `owner` |

The final reply:

- `kind`: `owner`
- `action_id`: `4:1:1`
- `deadline_at`: `2026-10-25T19:21:52Z` (180 minutes after the call)

The shim logged exactly four calls (`issue view 4 --json state`, the two `api` reads and the `pr list`), each with exit 0. The probe sandbox was removed afterwards.
