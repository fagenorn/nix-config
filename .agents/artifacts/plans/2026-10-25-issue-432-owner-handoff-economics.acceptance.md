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

Taken on host mbp before any paid trial, with no model spend. The sandbox is built the way `run_trial` builds one: the fixture copied, `git init -b main`, the initial commit, a bare origin and a push. Then `evals/setups/tracked-issue/setup.sh <WORK> <REPO>` ran (it wrote `<WORK>/bin/gh`, bound the tracker to `github` and committed `chore: track issues on github` to the sandbox's `main`). The sandbox and its ledger lived under a launch scratch directory, and the repository's own ledger was never named. `HOME` was a scratch directory holding only the platform manifest and host declaration; the host declaration under the real `~/.agents/share` was read to copy it there, and no file under `~/.agents/share` was written.

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

## Replay verdicts

Taken on host mbp. Step 1 ran at 2026-10-25T16:33:11Z (it finished at 16:33:46Z) on `d0f53a0d`, the calibration fix below, with `just agent-costs --report owners --days 14 --sweep` in text and JSON form. Eval 8's baseline arm was running in a detached worktree at the time; its trial transcripts were not yet part of the 226 lineages.

**Corpus.** Window `last 14d by file mtime`. 226 lineages, 434 owner launches (423 fresh-owner boots: 241 in Phases 0-5, 182 in Phases 6-7), 121 delivered. By project (lineages, delivered): nodocom 159, 85; arcwave 26, 14; nix-config 24, 12; jarbird 17, 10. The context meter deployed with PR #428, merged at `2026-10-25T07:00:48Z` (`gh pr view 428 --json mergedAt`). By each lineage's first call, 217 lineages (119 delivered) began before that merge and 9 (2 delivered) after it; 3 span it. The observed corpus is therefore almost entirely a product without the meter, and the replay is what prices the meter's policy.

**Pricing and identity.** `https://platform.claude.com/docs/en/about-claude/pricing`, 2026-10-25, 0 calls priced approximately. `calibration.identity_matches` is `true` (max error $0.000000000).

**Calibration correction.** The first sweep on this corpus gave 45.19 hand-offs per issue for the baseline, $148.95 per delivered issue, and a threshold saving of $44.70 (200,000, 1.40 hand-offs per issue). It was a calibration artifact (`replay-calibration-diagnosis.md`, §2 and §3). `boot_facts` ended a fresh owner's boot at its first registering call, but in 95 of 181 Phase 6-7 boots a dispatched child was already out by then, so B included the owner's first unit of work, which the shift model's observed increments already carry. B(6-7) was 118,110, above the 110,000 threshold, so each replayed fresh owner re-crossed on its first Bash call. Commit `d0f53a0d` ends the boot at the earlier of the registering call and the last call before the first call with a child out, in `boot_facts`, the fit's boot output and the calibration. With it B(6-7) is 103,984 (B(0-5) 88,746 → 84,845), the baseline hands off 15.31 times per issue at $84.01 per delivered issue, and the threshold row (200,000) hands off 1.26 times and saves $10.36 per issue (lower bound $9.89). The diagnosis predicted about 104k, about 16 hand-offs and $10-12; the run shows the same. The live product does transfer a fresh owner that registers above the threshold, once per owner: fresh owners in this very run registered at 127-129k and transferred within 5-7 calls under the 110,000 product threshold (`agent-a7f17a2bdce2af9ae` at call 44, then `delegate` at call 46; `agent-ad816b00ecb7620b4` at call 36, then `delegate` at call 38). The replay's magnitude, not its mechanism, was wrong.

Secondary observations from the diagnosis (§5), recorded and not fixed here:

- Direct runs are detected too rarely: a run counts as direct only when a `workflow-state` result starts with a `kind: "owner"` reply, so a reply written to a file and read back shows `direct: false`; it touches only the gate path.
- The meter path of the replay never consults the gate. Live, the note leads to a gate that may answer `delegate` or `fresh_start`; each is still a transfer to a fresh owner.
- The gate path of the replay does not latch. Live, a measured progress call at or above the threshold sets `notified` without a note, so the replay can add one meter hand-off after a crossing first seen at a gate.
- The guard and the cap are priced only on top of the threshold the sweep already chose (200,000), never on the 110,000 the product ships; at 110,000 the diagnosis measured them as real savings (for example guard 40,000 hands off 3.99 times per issue).

**Simulated arms and calibration** (the text report, verbatim):

```text
Simulated arms (savings are per lineage against the baseline replay; a sweep step's rows are against the step's simpler arm; hand-offs and deaths per issue):

arm                                      step       spec                                     $ / delivered  mean saving  lower bound  saves  hand-offs  deaths  peak p90  verdict     live check
---------------------------------------  ---------  ---------------------------------------  -------------  -----------  -----------  -----  ---------  ------  --------  ----------  ----------
baseline                                 baseline   threshold=110000                                $84.01        $0.00        $0.00     0%      15.31    9.10   159.10k  baseline    no
boot:slim                                boot       boot=slim                                       $83.99        $0.01       $-0.00     3%      15.30    9.10   159.10k  not chosen  no
threshold:90000                          threshold  threshold=90000                                $142.19      $-31.15      $-32.55     0%      51.23    9.11   158.02k  not chosen  yes
threshold:110000                         threshold  threshold=110000                                $84.01        $0.00        $0.00     0%      15.31    9.10   159.10k  not chosen  no
threshold:140000                         threshold  threshold=140000                                $66.92        $9.15        $8.73    96%       4.07    9.07   163.69k  not chosen  no
threshold:170000                         threshold  threshold=170000                                $64.81       $10.28        $9.82    97%       2.09    8.99   186.74k  not chosen  no
threshold:200000                         threshold  threshold=200000                                $64.66       $10.36        $9.89    97%       1.26    8.96   211.51k  chosen      no
threshold:never                          threshold  threshold=never                                 $66.83        $9.20        $8.74    94%       0.00    8.92   359.32k  info        no
threshold:200000,guard:20000             guard      threshold=200000,guard=20000                    $64.68       $-0.01       $-0.03     1%       1.25    8.95   211.52k  not chosen  no
threshold:200000,guard:40000             guard      threshold=200000,guard=40000                    $64.69       $-0.02       $-0.04     2%       1.24    8.95   212.23k  not chosen  no
threshold:200000,guard:60000             guard      threshold=200000,guard=60000                    $64.73       $-0.04       $-0.07     4%       1.21    8.95   215.93k  not chosen  no
threshold:200000,cap:1                   cap        threshold=200000,cap=1                          $65.05       $-0.21       $-0.33    12%       0.95    8.96   271.32k  not chosen  no
threshold:200000,cap:2                   cap        threshold=200000,cap=2                          $64.71       $-0.03       $-0.07     1%       1.23    8.96   212.83k  not chosen  no
threshold:200000,cap:3                   cap        threshold=200000,cap=3                          $64.66        $0.00        $0.00     0%       1.26    8.96   211.51k  not chosen  no
threshold:200000,help:drop               help       threshold=200000,help=drop                      $64.56        $0.05        $0.03    86%       1.25    8.95   211.61k  chosen      no
threshold:200000,help:drop,keepalive:on  keepalive  threshold=200000,help=drop,keepalive=on         $56.33        $4.41        $4.13    96%       1.25    0.00   211.61k  info        no
threshold                                final      threshold=200000                                $64.66       $10.36        $9.89    97%       1.26    8.96   211.51k  keep        no
help                                     final      help=drop                                       $83.82        $0.10        $0.08    89%      15.25    9.09   159.10k  keep        no
combined                                 final      threshold=200000,help=drop                      $64.56       $10.41        $9.95    99%       1.25    8.95   211.61k  keep        no

Calibration:

Identity replay matches the priced lineages: yes (max error $0.000000000)
Boot model: start 37.43k; boot calls {'0-5': 13, '6-7': 17}; B {'0-5': 84845, '6-7': 103984}; slimmable {'0-5': 0, '6-7': 0}; hand-off overhead calls 7; boot output 16; defaults: none

phase  boots  observed p50  modelled p50
-----  -----  ------------  ------------
0-5      241         $0.53         $0.57
6-7      182         $0.71         $0.74
```

Reading the verdicts (D18, D23). The shift model keeps observed increments after a hand-off and cannot see a fresh owner's re-reads, so it favours hand-offs; a kept arm that hands off more than the baseline carries `live_confirmation_required: true`. No kept arm does: threshold=200000 hands off 1.26 times per issue against the baseline's 15.31, so its `live_confirmation_required` is `false`. `threshold=never` is a reference row, never built (D27). `keepalive` is `info`, never built.

| Candidate | Step | Arm spec | Mean saving | Lower bound | Share | Verdict | Live confirmation required |
|-----------|------|----------|-------------|-------------|-------|---------|----------------------------|
| threshold | final | `threshold=200000` | $10.36 | $9.89 | 97% | keep | false |
| boot slimming | boot | `boot=slim` | $0.01 | $-0.00 | 3% | not chosen | false |
| guard | guard | `threshold=200000,guard=20000` / `40000` / `60000` | $-0.01 / $-0.02 / $-0.04 | $-0.03 / $-0.04 / $-0.07 | 1% / 2% / 4% | not chosen | false |
| cap | cap | `threshold=200000,cap=1` / `2` / `3` | $-0.21 / $-0.03 / $0.00 | $-0.33 / $-0.07 / $0.00 | 12% / 1% / 0% | not chosen | false |
| no `--help` | final | `help=drop` | $0.10 | $0.08 | 89% | keep | false |
| keepalive | keepalive | `keepalive=on` | $4.41 | $4.13 | 96% | info (never built) | false |
| combined | final | `threshold=200000,help=drop` | $10.41 | $9.95 | 99% | keep | false |

The per-phase grid did not run: the Phase 6-7 `B` median (103,984) is 22.6% above the Phase 0-5 one (84,845), under the 25% bar. What is built: 7A (threshold 200,000 in every phase) and 7E (no `--help`); 7B, 7C and 7D are rejected and get no product code (D9).
