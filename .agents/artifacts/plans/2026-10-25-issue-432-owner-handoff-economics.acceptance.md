# Acceptance record — issue 432

Taken on host mbp; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/432).

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] Eval 8 launches owners with lifecycle identity (direct `--auto`) on a fixture issue that crosses 110k, reaches Phase 6, enters Phase 7, and includes an owner wait on a child over 300 s — measured: a trial's asserts over its transcripts (measured gate notes, peak, ledger phase, long child wait) | code | Eval 8's asserts 1–5 (`from-issue/evals/evals.json` id 8: lifecycle ledger phase ≥ 6, every owner gate call measured, an owner call ≥ 110,000, Phase 7 entered, an owner long child wait) and its shape test in `test_eval_cases.py`. They are graded on every Task-8 trial. | pending | pending | pending | pending |
| AC2 | [code] `agent-costs --report owners` reports list-price dollars per delivered issue at per-model prices, peak context and per-issue or per-trial variance, for live transcripts and for eval runs (`--eval-results`) — measured: unit tests on fixture transcripts covering a boot, a cache rewrite after a TTL gap, a hand-off chain and eval grouping | code | `tests/test_agent_owner_report.py`: boot 29k→98k, 6-minute-gap rewrite priced as a 5-minute write, two-launch hand-off chain with a worker child, delivered/undelivered dollar formula, eval grouping (2 arms × 2 trials, mean and sd; an interrupted `PASS` trial left out, D26), approximate pricing. Run by `just agent-workflow-tests`. | pending | pending | pending | pending |
| AC3 | [code] Each candidate is a replay toggle that applies to any eval run or live corpus: the threshold with the sweep and the per-phase variant, boot slimming, the guard, the cap, keepalive and help; the live harness toggles the threshold knobs and any kept guard or cap through `EVAL_POLICY`, and tree-revision candidates through `EVAL_TREE` — measured: replay unit tests and the harness test | code | `tests/test_agent_owner_replay.py` covers every toggle (threshold sweep and per-phase, boot slimming, guard, cap, keepalive, help), and `test-run-eval-tree.sh` covers the `EVAL_POLICY` cases. Both run by `just agent-workflow-tests`. | pending | pending | pending | pending |
| AC4 | [evidence] The A/B report gives the baseline's and each candidate's dollars per delivered issue with variance, which were kept and which rejected with their numbers, and the threshold sweep (at least 90k, 110k, 140k and 170k, and the per-phase grid when boots differ by phase); the report names the chosen value and why — measured: the report | evidence | `just agent-costs --report owners --sweep --days 14` on mbp at the final head, plus the eval-mode report. § A/B and sweep report: baseline and each candidate's $/delivered issue with sd, kept and rejected candidates with numbers, a sweep covering 90k, 110k, 140k, 170k (and the per-phase grid when boots differ > 25%), and the chosen value with the reason. | § A/B and sweep report sections 3 and 4: the sweep table holds 90,000 ($146.68 per delivered issue), 110,000 ($86.21), 140,000 ($68.41), 170,000 ($66.18) and 200,000 ($65.95), plus `never` ($68.02) as the reference row; chosen 200,000, the lowest numeric cost, with a paired lower bound of $10.14 per lineage against the simpler arm; baseline $86.25 replayed ($68.14 observed, sd $19.78, n 231) and every candidate with its saving, lower bound, derived sd, share and keep/reject; the per-phase grid did not run (Phase 6-7 `B` median 22.5% above Phase 0-5, under 25%). | `271f81aa` | Host mbp, 2026-10-25T17:53Z, `just agent-costs --report owners --days 14 --sweep` text and JSON, 231 lineages, last 14d by file mtime, Claude Code 2.1.302, identity check true. | pending-controller |
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

**Note, 2026-10-25T17:53Z, on the final code head `271f81aa` (the corpus has grown to 231 lineages).** Step 1 above is kept as recorded. Re-run at the final head, the step row for `boot=slim` reads `chosen` and its final row `keep`: mean saving $0.0215 per lineage, lower bound $0.0025, 3% of lineages saving, against $0.01 and $-0.00 in the record above. The flip comes from corpus growth (231 lineages against 226, the live eval trials' transcripts among them; the same flip shows at `5f513e7d`), not from the fixes `7a22ae80`, `02a5ba1f`, `d39c07a9`. Ruling (owner `432:1:3`, `--auto`): 7B stays unbuilt. Step 1 is the plan's decision point and recorded boot slimming as not chosen; a $0.02 saving per lineage with a $0.0025 lower bound is far inside any practical resolution, it sits on a corpus the trials themselves moved, and building it means skill-text edits under about 2 B of from-issue-controller instruction headroom. At the final head boot slimming passes on a grown corpus and is not built (decision point: Task 7 Step 1). The sweep rows in the A/B report below therefore carry a `boot=slim,` prefix, since the coordinate pass builds on the chosen boot; the product has no boot slimming, and the `threshold` and `help` final rows (against the baseline replay, boot unchanged) and the built-combination row are the ones that describe it.

## A/B and sweep report

Taken on host mbp, round 1 (sweep and candidates) at 2026-10-25T17:53Z on code head `271f81aa`; the live arms are still running, so section 5 is filled in round 2. Sources: `$SCRATCH/live-sweep.txt` (`just agent-costs --report owners --days 14 --sweep`), `live-sweep.json` (the same with `--format json`) and `live-built.json` (the same with `--policy built=threshold=200000,help=drop`, run seconds later: the running trials' transcripts grow the corpus between invocations, so its baseline reads $86.27 against $86.25 in the sweep).

### 1. Corpus, pricing and identity

Window `last 14d by file mtime`: 231 lineages, 447 owner launches (431 fresh-owner boots: 245 in Phases 0-5, 186 in Phases 6-7), 121 delivered, 12 observed hand-offs (0.05 per lineage). It holds no eval-arm lineage: the corpus is the live product, mostly without the context meter (merged `2026-10-25T07:00:48Z`, per Replay verdicts). Pricing: `https://platform.claude.com/docs/en/about-claude/pricing`, 2026-10-25, 0 calls priced approximately. Identity check re-run at the final head: `calibration.identity_matches` is `true` (max error $0.000000000). Unattributed: 655 transcripts, $1,625.17, 10 owners without an issue.

The arms and boots tables, verbatim:

```text
Arms (dollars per delivered issue = all spend of the arm / delivered; sd is the sample standard deviation over delivered rows):

arm     n  delivered  $ / delivered      sd  undelivered $  peak p50  peak p90
----  ---  ---------  -------------  ------  -------------  --------  --------
live  231        121         $68.14  $19.78      $3,726.30   267.60k   359.32k

Fresh-owner boots by phase (B = context at the end of the boot, the registering call or the last call before the first child; slimmable = boot tokens a smaller resume would skip):

phase  boots    B p50    B p90  start p50  boot calls p50  slimmable p50
-----  -----  -------  -------  ---------  --------------  -------------
0-5      245   84.70k  109.40k     37.08k              13              0
6-7      186  103.78k  139.00k     37.64k              17              0
```

### 2. The baseline policy's dollars per delivered issue

Two baselines, kept apart. Observed (the live arm, from the arms table above): $68.14 per delivered issue, sd $19.78 (sample sd of `total_dollars` over the 121 delivered lineages), n = 231 lineages, 121 delivered. Replayed (the baseline policy `threshold=110000`, the meter policy the product shipped before this issue): $86.25 per delivered issue, 15.23 hand-offs and 9.01 deaths per issue, peak p90 160.05k, over the same 231 lineages; the simulated rows carry no sd of dollars per delivered issue, only the paired mean saving and its lower bound (section 4). The replayed baseline sits above the observed live arm because most of the corpus ran without the meter (0.05 observed hand-offs per lineage against 15.23 replayed). The live eval baseline arm (mean and sd over its trials) is section 5.

### 3. Threshold sweep and the chosen value

Rows verbatim from the simulated-arms table (`$ / delivered` is all spend of the arm over its delivered lineages; `mean saving` and `lower bound` are per lineage against the step's simpler arm, here `boot=slim`, which replays within $0.05 per delivered issue of the baseline):

```text
arm                                                step       spec                                               $ / delivered  mean saving  lower bound  saves  hand-offs  deaths  peak p90  verdict     live check
-------------------------------------------------  ---------  -------------------------------------------------  -------------  -----------  -----------  -----  ---------  ------  --------  ----------  ----------
baseline                                           baseline   threshold=110000                                          $86.25        $0.00        $0.00     0%      15.23    9.01   160.05k  baseline    no
boot:slim                                          boot       boot=slim                                                 $86.21        $0.02        $0.00     3%      15.20    9.01   160.05k  chosen      no
boot:slim,threshold:90000                          threshold  boot=slim,threshold=90000                                $146.68      $-31.68      $-33.09     0%      50.87    9.02   160.05k  not chosen  yes
boot:slim,threshold:110000                         threshold  boot=slim,threshold=110000                                $86.21        $0.00        $0.00     0%      15.20    9.01   160.05k  not chosen  no
boot:slim,threshold:140000                         threshold  boot=slim,threshold=140000                                $68.41        $9.32        $8.90    96%       4.04    8.97   164.32k  not chosen  no
boot:slim,threshold:170000                         threshold  boot=slim,threshold=170000                                $66.18       $10.49       $10.02    97%       2.08    8.88   186.74k  not chosen  no
boot:slim,threshold:200000                         threshold  boot=slim,threshold=200000                                $65.95       $10.61       $10.14    97%       1.25    8.85   212.23k  chosen      no
boot:slim,threshold:never                          threshold  boot=slim,threshold=never                                 $68.02        $9.53        $9.07    94%       0.00    8.81   359.32k  info        no
```

Chosen: **200,000** in every phase. It has the lowest dollars per delivered issue of the numeric thresholds ($65.95, against $66.18 at 170,000, $68.41 at 140,000 and $86.21 at 110,000), and it keeps against the simpler arm with a paired one-sided 90% lower bound of $10.14 per lineage (mean $10.61, 97% of lineages saving), well clear of zero; the tool chooses the cheapest candidate that passes the keep rule against the simpler arm (D7), and 200,000 does. Without boot slimming (the product) the same threshold prices at $65.98 per delivered issue (final row `threshold`: mean $10.62, lower bound $10.14). 90,000 is far worse ($146.68, 50.87 hand-offs per issue, mean saving $-31.68, `live check` yes). `never` is a reference row (D27) and is not the cheapest: $68.02 per delivered issue, $2.07 above 200,000, so the D27 statement that `never` is cheapest does not apply. The per-phase grid did not run: the Phase 6-7 `B` median (103.78k) is 22.5% above the Phase 0-5 one (84.70k), under the 25% bar.

Caveats: 200,000 hands off 1.25 times per issue against the baseline's 15.20, so no sweep arm carries `live_confirmation_required` except 90,000 (not chosen). The corpus's observed peaks (p50 267.6k, p90 359.3k) show owners already run past 200k on larger windows, so the threshold is a cost lever and not a window limit; whether eval 8's asserts hold under the 200,000 default (assert 3 expects an owner call at or above 110,000) is read from the trials in round 2.

### 4. Each candidate alone and in the combinations

Rows come from the final-step rows (each alone against the baseline replay), the guard, cap and keepalive step rows (against the step's simpler arm), and the built combination from `live-built.json`. The simulated rows carry a lower bound and no sd, so the sd column is derived: from LB = mean - 1.2816 sd / sqrt(n) (`ONE_SIDED_90`, `keep_rule` in `agent_owner_replay.py`) with n = 231 lineages (231 for the last row), sd = (mean - LB) sqrt(n) / 1.2816; it is the sd of the per-lineage saving in dollars, not of dollars per delivered issue.

| Candidate | Step | Arm spec | $ / delivered | Mean saving | Lower bound | sd (derived) | Share | Verdict | Live confirmation required |
|---|---|---|---|---|---|---|---|---|---|
| boot slimming (alone) | final | `boot=slim` | $86.21 | $0.02 | $0.00 | $0.23 | 3% | keep (replay-only; not built, ruling below) | false |
| threshold 200,000 (alone) | final | `threshold=200000` | $65.98 | $10.62 | $10.14 | $5.61 | 97% | keep (built, 7A) | false |
| no `--help` (alone) | final | `help=drop` | $86.05 | $0.10 | $0.08 | $0.30 | 89% | keep (built, 7E) | false |
| guard 20,000 | guard | `boot=slim,threshold=200000,guard=20000` | $65.98 | $-0.01 | $-0.03 | $0.21 | 1% | reject (not chosen) | false |
| guard 40,000 | guard | `boot=slim,threshold=200000,guard=40000` | $65.99 | $-0.02 | $-0.04 | $0.23 | 2% | reject (not chosen) | false |
| guard 60,000 | guard | `boot=slim,threshold=200000,guard=60000` | $66.02 | $-0.04 | $-0.07 | $0.38 | 4% | reject (not chosen) | false |
| cap 1 | cap | `boot=slim,threshold=200000,cap=1` | $66.32 | $-0.19 | $-0.31 | $1.35 | 12% | reject (not chosen) | false |
| cap 2 | cap | `boot=slim,threshold=200000,cap=2` | $66.01 | $-0.03 | $-0.06 | $0.40 | 1% | reject (not chosen) | false |
| cap 3 | cap | `boot=slim,threshold=200000,cap=3` | $65.95 | $0.00 | $0.00 | $0.00 | 0% | reject (not chosen) | false |
| keepalive on | keepalive | `boot=slim,threshold=200000,help=drop,keepalive=on` | $57.55 | $4.35 | $4.08 | $3.20 | 95% | info (never built) | false |
| combined, replay-only (boot, threshold, help) | final | `boot=slim,threshold=200000,help=drop` | $65.86 | $10.68 | $10.21 | $5.60 | 99% | keep (boot=slim part not built) | false |
| built combination (threshold, help) | policy | `threshold=200000,help=drop` | $65.89 | $10.68 | $10.21 | $5.59 | 99% | keep (what the product ships) | false |

Reading it. Kept and built: the 200,000 threshold ($10.62 per lineage, lower bound $10.14) and no `--help` ($0.10, lower bound $0.08); together they save $10.68 per lineage (lower bound $10.21), and the product's price is $65.89 per delivered issue against the replayed baseline's $86.27, with 1.24 hand-offs per issue against 15.23. Kept by the replay and not built: boot slimming (ruling in Replay verdicts). Rejected: the guard (every value has a negative mean saving, $-0.01 to $-0.04, and lower bounds of $-0.03 to $-0.07) and the cap (cap 1 loses $0.19 per lineage; cap 3 never binds and is the same as no cap). Information only: keepalive, never built (section 7). No kept arm has `live_confirmation_required` true, so D23 would revert nothing: the kept candidates hand off less often than the baseline, which the shift model's bias does not favour.

Known biases of the shift model. (a) It favours hand-offs (D18): after a hand-off it keeps the observed increments and cannot see a fresh owner's later re-reads, so every saving above is an upper-leaning estimate; a live trial is the only check on it. (b) The hand-off undo and the fitted boot end differ in where they stop: the undo of an observed `handoff` still joins the two owners at the registering call (`_owners` in `agent_owner_replay.py`, with `boot_slim` summed over `calls[:index + 1]`), while the fitted `B` (the boot output of the calibration fix `d0f53a0d`) now ends at the earlier of the registering call and the last call before the first child. Where a child went out first, the undone observed hand-offs and the simulated ones use different cuts; the direction and size of that mismatch are not measured here. (c) The corpus is mostly pre-meter, so the replay prices the meter policy and the observed live arm does not.

### 5. Live arms

Pending round 2: the trials are still running.

### 6. Conditions

- Host `mbp` (`hostname -s`); Claude Code `2.1.302`.
- Baseline arm: tree `8e6ffc339ee7a85be39ef8cae8cbbde776500c18` (Task 6's commit), settings `/nix/store/3ndqx4id1nxps2jxz60yrh0xxyvqyxzl-claude-code-settings.json`, `EVAL_MODEL=opus`, `EVAL_MAX_USD=40`, `EVAL_TIMEOUT=7200`; trials 1 and 2 started 16:30Z, trial 3 at 16:48Z.
- Candidate arm: tree `5f513e7d0c6b5fded644e54fe4fb0b8b91d1ee2b` (Task 7 plus the harness fix), settings `/nix/store/b2qhfvqw1v86xcmxcw1vbf9djgxvrfsh-claude-code-settings.json`, same model, spend cap and timeout; one trial, started 16:55Z. The final code head `271f81aa` differs from it only in the replay and report code, their tests, `python/README.md` and one record sentence (`git diff --stat 5f513e7d..271f81aa`: 7 files, none of them product code a trial runs), so the trial runs the shipped product.
- Evidence gap, baseline trial 1: it ended at 1023 s with `claude_exit` 0, verdict FAIL 2/6 and $4.87. Cause: the root owner handed off after Phase 0, dispatched the relaunched owner as a background agent and ended its turn, and `claude -p` stopped background tasks 10 minutes after the last turn (print mode's background-wait ceiling; its message names `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`). It is a harness defect and not product behaviour, and it is an evidence gap, not a sample, even though `claude_exit` is 0. Baseline trial 2 started in the same condition and showed the same shape (its root transcript idle since 16:36Z); the controller decides whether it is a sample.
- Harness fix `5f513e7d` (`fix(evals): a print-mode trial waits for its background agents`): `run-eval.sh` exports `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0` into the trial's environment; baseline trial 3 and the candidate trial ran with it. The baseline tree `8e6ffc33` itself is unchanged, so the baseline arm is the same product, with the fix in its launch environment only for trial 3.
- D15's 4-trial cap leaves no more trials after these four launches, so neither arm can reach two clean samples (baseline: trial 3, and trial 2 if the controller rules it a sample; candidate: one trial). AC6 is not met regardless, because it needs `n` 2 and `delivered` 2 in each arm.
- `absolute_path_calls` per trial: round 2.

### 7. Keepalive for issue 423

`keepalive=on` revives every cache death and adds a cache-read ping per 270 s of gap (`⌈gap/270⌉ − 1`). Priced on top of the 200,000 threshold and `help=drop` (boot slimming included in the replay arm), it takes dollars per delivered issue from $65.86 to $57.55: $8.31 less per delivered issue (12.6%), a mean saving of $4.35 per lineage (lower bound $4.08, derived sd $3.20, 95% of lineages saving), and deaths per issue from 8.84 to 0.00. It is an `info` row, never built here (D9). For issue 423 this is the replay's price of a perfect keepalive, an upper-leaning estimate: it assumes every ping lands inside the cache's life and revives it, and it inherits the shift model's bias toward fewer re-reads; no live trial measured pings.
