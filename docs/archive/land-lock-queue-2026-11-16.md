# Land lock queue, the 39 landings up to #1190 (2026-11-16)

This measures the 39 landings on `main` from 2026-11-16 01:02:25 to 22:34:14 UTC, the last one being #1190 (a landing is a pull request that took the land lock itself; one indirect merge, #1080, is listed apart), and how long each spent asking for, waiting for and holding the land lock, and how long the required checks on its merged head took. Every figure is derived from the forge alone (pull requests, workflow runs and check runs); the tables below are the output of the program under Reproduce, pasted verbatim.

## Method

The forge keeps no record of the lock `refs/agent-locks/land/main` or of its queue refs ([ADR-claims-004](../areas/claims/adr/004-the-land-lock-is-a-cas-ref.md), [ADR-claims-012](../areas/claims/adr/012-waiters-on-the-land-lock-queue-in-forge-clock-order.md)): a pull request's timeline holds no lock event. So the lock ask and the hold are derived from each pull request's `createdAt` and `mergedAt` and the serial order of the merges, which the lock enforces. For a landing, `prev` is the merge time of the landing before it.

- A landing is a pull request whose merge commit is not its own head. When the forge marks a pull request merged because its head already reached `main` inside another landing, its merge commit is its head: it is an indirect merge, held no lock cycle of its own, and is neither a row nor a `prev`. #1080 is one: its head `f1a9d0f65a16` reached `main` through `a6aa3148`, merged into #1116 by `69ee02fa`, and the forge stamped it merged 2 seconds after #1116. Counting it as a landing would add a wait of 1185.4 minutes for a pull request that never took the lock. Its own lock history is unknown.
- Ask to merge is `mergedAt` minus `createdAt`.
- Wait is `max(0, prev - createdAt)`: the time the pull request existed while an earlier landing still held the lock.
- Hold is `mergedAt - max(createdAt, prev)`: from the moment the lock could be the pull request's to its merge.
- Handoff, for a pull request created before `prev` only, is the start of its earliest CI run at or after `prev` minus `prev`: the previous merge to the waiter's first CI run after it, which is the waiter's acquire plus its sync push and the run's creation.
- CI runs is the number of attempts of the `ci.yaml` workflow on the branch whose start (`run_started_at`) lies in `[createdAt, mergedAt]`. A run with several attempts is read attempt by attempt, because the run object shows only its latest attempt. A cancelled attempt in the interval counts.
- The required checks are read from the merged head's check runs (`filter=all`, every attempt): only runs of the Actions app (id 15368) that completed with success, named `Nix Eval`, `Agent Workflow Tests` or `Instruction Budget`, and completed at or before `mergedAt`. Per name the latest such run is the measured one. A name with no such run prints `-`.
- AWT before test step and AWT test step split the measured `Agent Workflow Tests` job (its check run id is the Actions job id) at the step `Run agent workflow tests`: the job's start to the step's start, and the step's own duration.
- Final-head CI wall is the earliest start to the latest completion among the measured check runs; Green to merge is `mergedAt` minus the latest completion among them.

Only results inside a landing's interval are measured, so Handoff and Green to merge are never negative and a rerun after the merge changes no row. The provenance table names every measured check run and every counted attempt as `<run id>/<attempt>`.

The estimator has known biases. A delivery marked for the owner's look (#1139), the conflict probe (#941) and a red own check (#1001) stop before or skip the lock, so those pull requests ask for it after `createdAt` and Wait is overstated for them. A pull request that was not waiting when the previous merge landed has its own pre-lock CI counted in Hold, so Hold is an upper bound. Handoff also counts the sync push and the run's creation, and a push made while waiting would shorten it. AWT test step includes the `nix shell` realization before the suite starts, which no column splits. The final-head columns are measured directly.

## Measurements

| PR | Issue | Merged (UTC) | Ask to merge (min) | Wait (min) | Hold (min) | Handoff (min) | CI runs | Nix Eval (min) | Agent Workflow Tests (min) | AWT before test step (min) | AWT test step (min) | Instruction Budget (min) | Final-head CI wall (min) | Green to merge (min) |
|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| #1094 | 1089 | 2026-11-16 01:02:25 | 10.9 | 0.0 | 10.9 | - | 1 | 1.2 | 10.2 | 0.2 | 9.8 | 0.2 | 10.2 | 0.7 |
| #1093 | 1088 | 2026-11-16 01:17:46 | 44.3 | 28.9 | 15.3 | 5.6 | 3 | 0.9 | 9.2 | 0.2 | 8.9 | 0.1 | 9.2 | 0.5 |
| #1096 | 1090 | 2026-11-16 03:13:00 | 8.5 | 0.0 | 8.5 | - | 1 | 1.3 | 7.8 | 0.3 | 7.4 | 0.2 | 7.8 | 0.6 |
| #1098 | 1092 | 2026-11-16 03:45:38 | 8.4 | 0.0 | 8.4 | - | 1 | 1.4 | 7.8 | 0.2 | 7.5 | 0.1 | 7.8 | 0.5 |
| #1100 | 1086 | 2026-11-16 04:10:52 | 11.7 | 0.0 | 11.7 | - | 1 | 1.3 | 7.7 | 0.2 | 7.4 | 0.1 | 7.7 | 0.5 |
| #1101 | 1099 | 2026-11-16 05:03:33 | 23.3 | 0.0 | 23.3 | - | 1 | 1.1 | 7.8 | 0.2 | 7.5 | 0.1 | 7.8 | 9.2 |
| #1102 | 1091 | 2026-11-16 10:04:13 | 22.0 | 0.0 | 22.0 | - | 1 | 1.1 | 10.5 | 0.2 | 10.3 | 0.1 | 10.5 | 0.6 |
| #1116 | 1103 | 2026-11-16 10:33:58 | 9.7 | 0.0 | 9.7 | - | 1 | 1.2 | 9.0 | 0.1 | 8.8 | 0.1 | 9.0 | 0.6 |
| #1121 | 1109 | 2026-11-16 10:58:09 | 10.2 | 0.0 | 10.2 | - | 2 | 0.9 | 8.1 | 0.2 | 7.8 | 0.1 | 8.4 | 0.9 |
| #1122 | 1114 | 2026-11-16 11:39:29 | 9.8 | 0.0 | 9.8 | - | 2 | 0.8 | 8.0 | 0.2 | 7.7 | 0.2 | 8.3 | 0.5 |
| #1123 | 1117 | 2026-11-16 12:14:48 | 43.5 | 8.1 | 35.3 | 1.0 | 3 | 1.2 | 8.4 | 0.3 | 8.1 | 0.2 | 8.4 | 0.7 |
| #1125 | 1112 | 2026-11-16 12:46:20 | 52.7 | 21.1 | 31.5 | 5.8 | 3 | 1.0 | 10.6 | 0.2 | 10.4 | 0.2 | 10.6 | 0.7 |
| #1128 | 1119 | 2026-11-16 13:00:56 | 11.3 | 0.0 | 11.3 | - | 2 | 1.4 | 8.2 | 0.3 | 7.9 | 0.2 | 8.5 | 2.0 |
| #1130 | 1118 | 2026-11-16 13:13:29 | 18.0 | 5.5 | 12.6 | 3.3 | 2 | 1.1 | 8.4 | 0.2 | 8.2 | 0.3 | 8.7 | 0.5 |
| #1143 | 1131 | 2026-11-16 13:44:09 | 16.1 | 0.0 | 16.1 | - | 2 | 1.0 | 8.2 | 0.3 | 7.9 | 0.2 | 8.5 | 0.7 |
| #1127 | 1115 | 2026-11-16 14:07:54 | 96.3 | 72.6 | 23.8 | 1.2 | 3 | 1.1 | 8.5 | 0.3 | 8.1 | 0.1 | 8.5 | 1.1 |
| #1144 | 1133 | 2026-11-16 14:20:46 | 24.1 | 11.2 | 12.9 | 1.9 | 2 | 1.3 | 10.2 | 0.2 | 9.9 | 0.1 | 10.2 | 0.6 |
| #1145 | 1134 | 2026-11-16 14:44:44 | 32.9 | 8.9 | 24.0 | 1.4 | 3 | 1.1 | 10.1 | 0.2 | 9.8 | 0.2 | 10.1 | 1.3 |
| #1126 | 1110 | 2026-11-16 15:00:27 | 160.5 | 144.8 | 15.7 | 2.9 | 7 | 1.2 | 8.3 | 0.2 | 8.0 | 0.1 | 8.5 | 0.7 |
| #1154 | 1147 | 2026-11-16 15:16:11 | 23.6 | 7.9 | 15.7 | 3.2 | 2 | 1.1 | 11.7 | 0.2 | 11.4 | 0.1 | 11.7 | 0.8 |
| #1156 | 1132 | 2026-11-16 15:30:54 | 32.7 | 18.0 | 14.7 | 5.8 | 2 | 1.2 | 8.4 | 0.3 | 8.0 | 0.1 | 8.4 | 0.5 |
| #1155 | 1111 | 2026-11-16 15:41:10 | 44.2 | 34.0 | 10.3 | 1.1 | 3 | 0.8 | 8.4 | 0.3 | 8.1 | 0.1 | 8.5 | 0.6 |
| #1157 | 1138 | 2026-11-16 16:07:47 | 47.0 | 20.4 | 26.6 | 1.2 | 3 | 1.1 | 8.4 | 0.3 | 8.0 | 0.1 | 8.4 | 0.7 |
| #1158 | 1148 | 2026-11-16 16:18:13 | 49.4 | 39.0 | 10.4 | 1.1 | 2 | 1.2 | 8.7 | 0.1 | 8.5 | 0.2 | 8.7 | 0.6 |
| #1159 | 1124 | 2026-11-16 17:50:32 | 140.4 | 48.1 | 92.3 | 83.0 | 2 | 1.0 | 8.7 | 0.2 | 8.5 | 0.1 | 8.7 | 0.7 |
| #1163 | 1135 | 2026-11-16 18:22:25 | 33.9 | 2.0 | 31.9 | 4.0 | 3 | 1.1 | 8.6 | 0.3 | 8.2 | 0.3 | 8.6 | 0.7 |
| #1165 | 1141 | 2026-11-16 18:34:06 | 13.6 | 1.9 | 11.7 | 1.0 | 2 | 1.9 | 9.2 | 0.2 | 8.9 | 0.1 | 9.5 | 1.1 |
| #1161 | 1120 | 2026-11-16 19:18:34 | 217.9 | 173.5 | 44.5 | 3.5 | 3 | 1.0 | 8.3 | 0.2 | 8.1 | 0.1 | 8.3 | 0.6 |
| #1167 | 1139 | 2026-11-16 19:42:57 | 56.5 | 32.1 | 24.4 | 0.9 | 3 | 1.0 | 9.9 | 0.2 | 9.7 | 0.1 | 9.9 | 1.0 |
| #1164 | 1113 | 2026-11-16 20:16:13 | 125.8 | 92.5 | 33.3 | 1.1 | 3 | 1.0 | 10.6 | 0.2 | 10.3 | 0.3 | 10.6 | 0.9 |
| #1171 | 1160 | 2026-11-16 20:32:00 | 65.4 | 49.6 | 15.8 | 6.6 | 2 | 1.1 | 8.5 | 0.3 | 8.1 | 0.1 | 8.6 | 0.6 |
| #1172 | 1149 | 2026-11-16 20:44:36 | 56.3 | 43.7 | 12.6 | 1.3 | 2 | 0.9 | 10.2 | 0.2 | 10.0 | 0.2 | 10.2 | 1.0 |
| #1168 | 1129 | 2026-11-16 21:13:47 | 124.5 | 95.4 | 29.2 | 0.9 | 4 | 1.1 | 9.9 | 0.2 | 9.7 | 0.1 | 9.9 | 0.6 |
| #1174 | 1140 | 2026-11-16 21:26:32 | 39.8 | 27.0 | 12.8 | 0.9 | 2 | 1.1 | 10.7 | 0.2 | 10.5 | 0.3 | 10.7 | 1.0 |
| #1169 | 1136 | 2026-11-16 21:39:52 | 150.3 | 136.9 | 13.3 | 2.9 | 2 | 1.1 | 9.7 | 0.2 | 9.5 | 0.2 | 9.7 | 0.7 |
| #1175 | 1173 | 2026-11-16 21:57:03 | 25.2 | 8.0 | 17.2 | 1.1 | 2 | 1.1 | 15.3 | 3.5 | 11.8 | 0.1 | 15.3 | 0.7 |
| #1188 | 1150 | 2026-11-16 22:09:35 | 11.5 | 0.0 | 11.5 | - | 2 | 1.4 | 8.7 | 0.2 | 8.4 | 0.1 | 9.0 | 1.4 |
| #1189 | 1142 | 2026-11-16 22:21:01 | 18.4 | 7.0 | 11.4 | 1.2 | 2 | 1.1 | 8.7 | 0.1 | 8.5 | 0.2 | 9.0 | 1.2 |
| #1190 | 1183 | 2026-11-16 22:34:14 | 12.9 | 0.0 | 12.9 | - | 2 | 1.0 | 11.1 | 0.2 | 10.8 | 0.1 | 11.4 | 0.7 |

| Figure | Median | p90 | Max | Sum |
|---|---:|---:|---:|---:|
| Ask to merge (min) | 32.7 | 140.4 | 217.9 | 1903.5 |
| Wait (min) | 8.1 | 95.4 | 173.5 | 1138.1 |
| Hold (min) | 14.7 | 33.3 | 92.3 | 765.5 |
| Handoff (min) | 1.4 | 5.8 | 83.0 | 143.9 |
| CI runs | 2.0 | 3.0 | 7.0 | 89.0 |
| Nix Eval (min) | 1.1 | 1.4 | 1.9 | 43.9 |
| Agent Workflow Tests (min) | 8.7 | 10.7 | 15.3 | 360.7 |
| AWT before test step (min) | 0.2 | 0.3 | 3.5 | 11.8 |
| AWT test step (min) | 8.5 | 10.5 | 11.8 | 346.4 |
| Instruction Budget (min) | 0.1 | 0.3 | 0.3 | 5.9 |
| Final-head CI wall (min) | 8.7 | 10.7 | 15.3 | 363.8 |
| Green to merge (min) | 0.7 | 1.3 | 9.2 | 39.0 |

Landings: 39, merged 2026-11-16 01:02:25 to 2026-11-16 22:34:14 (UTC).
Indirect merges (no lock cycle of their own): #1080 merged 2026-11-16 10:34:00 (UTC).

| PR | Head | Nix Eval check run | Agent Workflow Tests check run | Instruction Budget check run | CI run attempts |
|---:|---|---:|---:|---:|---|
| #1094 | 3f1391cb3fdd | 133023732586 | 133023732591 | 133023732127 | 43782842251/1 |
| #1093 | 5f1becd94cb9 | 133028774274 | 133028773882 | 133028774185 | 43781081717/1 43782291899/1 43784432124/1 |
| #1096 | 13457484a23d | 133064633315 | 133064633686 | 133064633321 | 43795934122/1 |
| #1098 | 8d9311235d9d | 133075213613 | 133075213918 | 133075213625 | 43799279455/1 |
| #1100 | 0e0b23727992 | 133083102095 | 133083102904 | 133083101816 | 43801656118/1 |
| #1101 | 3cadd78ddd62 | 133097104155 | 133097103846 | 133097103893 | 43806096096/1 |
| #1102 | 1dfd9890369d | 133218721991 | 133218722120 | 133218721786 | 43843778726/1 |
| #1116 | d21c3d985b4e | 133234773703 | 133234773256 | 133234773390 | 43848522728/1 |
| #1121 | d2d39a8b0c3d | 133247368153 | 133247368338 | 133247241775 | 43852057656/1 43852177680/1 |
| #1122 | cb8728ce3ec2 | 133268645803 | 133268645701 | 133268503682 | 43858246449/1 43858398074/1 |
| #1123 | 643833b345e7 | 133285887930 | 133285888395 | 133285888220 | 43858501535/1 43859821309/1 43863453140/1 |
| #1125 | 55cc64ddea41 | 133300984593 | 133300984962 | 133300984380 | 43863683654/1 43865703524/1 43867866574/1 |
| #1128 | 13878294b993 | 133309122193 | 133309122657 | 133308978067 | 43870083358/1 43870183239/1 |
| #1130 | da54bace71ba | 133316392840 | 133316392724 | 133316240911 | 43870966838/1 43872276020/1 |
| #1143 | 61c814b44f54 | 133333162829 | 133333162640 | 133333017982 | 43876031063/1 43877139799/1 |
| #1127 | ce15fc0b56be | 133346346473 | 133346347080 | 133346346001 | 43867369328/1 43878832103/1 43880945174/1 |
| #1144 | 711dc2039d81 | 133353089239 | 133353089937 | 133353080217 | 43880690022/1 43882867614/1 |
| #1145 | 831bef1785fd | 133367518419 | 133367518892 | 133367517374 | 43883213701/1 43884991707/1 43886937575/1 |
| #1126 | 9febe75fccb9 | 133378923997 | 133378923779 | 133378764345 | 43870433536/1 43874672677/1 43874905680/1 43876704376/1 43885266812/1 43889478074/1 43890131203/1 |
| #1154 | ad10ff3a8211 | 133386499235 | 133386499208 | 133386480254 | 43890384568/1 43892305296/1 |
| #1156 | 19a76e385b28 | 133397954822 | 133397954906 | 133397955909 | 43891390756/1 43895533181/1 |
| #1155 | 436f0bac12d8 | 133404382042 | 133404382039 | 133404380235 | 43891376565/1 43895067461/1 43897344880/1 |
| #1157 | a8eb21aee1c5 | 133421920410 | 133421920437 | 133421917209 | 43895340793/1 43899259904/1 43902317630/1 |
| #1158 | 8389117a97f3 | 133428685862 | 133428685393 | 133428690210 | 43896802038/1 43904245996/1 |
| #1159 | aadda4d8ae65 | 133487798352 | 133487798274 | 133487797638 | 43897043287/1 43920962886/1 |
| #1163 | b6c4be278198 | 133507237130 | 133507237666 | 133507238880 | 43923252887/1 43923838197/1 43926490807/1 |
| #1165 | eb3c275c7bdd | 133513701676 | 133513702290 | 133513541016 | 43927801118/1 43928291880/1 |
| #1161 | f6088f451a21 | 133541998271 | 133541997716 | 133541997878 | 43929347203/1 43930792643/1 43936394560/1 |
| #1167 | dc87ccc24e32 | 133555746475 | 133555746692 | 133555745279 | 43932364274/1 43938130682/1 43940304816/1 |
| #1164 | 38b0d2eee31b | 133575644465 | 133575644836 | 133575643033 | 43933150827/1 43942397483/1 43945982712/1 |
| #1171 | 3e20c798f155 | 133586706164 | 133586706838 | 133586706818 | 43939393803/1 43949157656/1 |
| #1172 | 1b8c62fd510c | 133593042853 | 133593043255 | 133593042769 | 43943159392/1 43950974002/1 |
| #1168 | 480c2b1b8bf9 | 133610861788 | 133610862226 | 133610862741 | 43936339631/1 43952803009/1 43953071821/1 43956079273/1 |
| #1174 | 9723394cced6 | 133617864073 | 133617864214 | 133617864904 | 43953297109/1 43958084836/1 |
| #1169 | 77cad97e1696 | 133626645143 | 133626644921 | 133626643650 | 43936399323/1 43960598195/1 |
| #1175 | 634d93e4d55f | 133633462821 | 133633463201 | 133633462288 | 43961029020/1 43962541317/1 |
| #1188 | 5f15b7c04c10 | 133644048258 | 133644048163 | 133643896744 | 43965367140/1 43965541126/1 |
| #1189 | 0fc1462a454d | 133650803946 | 133650803606 | 133650636829 | 43966121931/1 43967488767/1 |
| #1190 | df472460fafe | 133657353008 | 133657353091 | 133657194586 | 43969267720/1 43969381103/1 |

Reading the summary: `Agent Workflow Tests` is the critical path of every hold, at a median of 8.7 minutes against 1.1 for `Nix Eval` and 0.1 for `Instruction Budget`, and its test step (median 8.5 minutes) is almost all of it; the job's own set-up before that step is a median 0.2 minutes. The median hold is 14.7 minutes (p90 33.3, maximum 92.3), so a hold is the final-head CI wall plus about six minutes of handoff, sync push and the waiter's own pre-lock work; the median handoff from one merge to the next waiter's first CI run is 1.4 minutes (p90 5.8), with one outlier of 83.0 minutes (#1159). The merge follows the last required check by a median 0.7 minutes (p90 1.3, maximum 9.2, #1101). The issue's figure of about 25 minutes per re-run on 16 Nov is not confirmed: the final-head CI wall has a median of 8.7 minutes, p90 10.7 and maximum 15.3.

## Reproduce

This needs an authenticated `gh` and `python3`; it prints the tables above exactly. The window and the interval cutoff are fixed, so a re-run prints the same rows.

```sh
python3 -I - <<'PY'
import json
import math
import re
import statistics
import subprocess
import sys
from datetime import datetime, timezone

REPO = "fagenorn/nix-config"
R = "repos/" + REPO
APP = 15368
CHECKS = ("Nix Eval", "Agent Workflow Tests", "Instruction Budget")
STEP = "Run agent workflow tests"
CUTOFF = "2026-11-16T22:34:14Z"
ROWS = 39
HEADERS = [
    "PR", "Issue", "Merged (UTC)", "Ask to merge (min)", "Wait (min)", "Hold (min)",
    "Handoff (min)", "CI runs", "Nix Eval (min)", "Agent Workflow Tests (min)",
    "AWT before test step (min)", "AWT test step (min)", "Instruction Budget (min)",
    "Final-head CI wall (min)", "Green to merge (min)",
]


def gh(*args):
    done = subprocess.run(["gh", *args], check=True, capture_output=True, text=True)
    return json.loads(done.stdout)


def listing(path, key):
    answer = gh("api", path)
    if answer["total_count"] > 100:
        print("more than 100 entries: https://api.github.com/" + path, file=sys.stderr)
        sys.exit(1)
    return answer[key]


def when(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def minutes(later, earlier):
    return (later - earlier).total_seconds() / 60


def cell(value, spec="{:.1f}"):
    return "-" if value is None else spec.format(value)


pulls = gh(
    "pr", "list", "--repo", REPO, "--state", "merged", "--base", "main",
    "--search", "merged:2026-11-13..2026-11-16", "--limit", "300",
    "--json", "number,createdAt,mergedAt,headRefName,headRefOid,mergeCommit",
)
pulls = sorted(
    (p for p in pulls if p["mergedAt"] <= CUTOFF),
    key=lambda p: (p["mergedAt"], p["number"]),
)
# The forge marks a pull request merged when its head reaches main inside another
# landing; its merge commit is then its own head. It held no lock cycle, so it is
# neither a row nor a predecessor.
indirect = [p for p in pulls if p["mergeCommit"] and p["mergeCommit"]["oid"] == p["headRefOid"]]
pulls = [p for p in pulls if p not in indirect]
if len(pulls) < ROWS + 1:
    print(len(pulls), file=sys.stderr)
    sys.exit(1)
pulls = pulls[-(ROWS + 1):]
indirect = [p for p in indirect if pulls[0]["mergedAt"] <= p["mergedAt"] <= pulls[-1]["mergedAt"]]

table, provenance = [], []
for before, pull in zip(pulls, pulls[1:]):
    created, merged, prev = when(pull["createdAt"]), when(pull["mergedAt"]), when(before["mergedAt"])
    head, branch = pull["headRefOid"], pull["headRefName"]

    starts = []
    runs = listing(f"{R}/actions/workflows/ci.yaml/runs?branch={branch}&event=pull_request&per_page=100", "workflow_runs")
    for run in runs:
        if run["run_attempt"] == 1:
            attempts = [(run["id"], 1, run["run_started_at"])]
        else:
            attempts = [
                (run["id"], k, gh("api", f"{R}/actions/runs/{run['id']}/attempts/{k}")["run_started_at"])
                for k in range(1, run["run_attempt"] + 1)
            ]
        starts += [(i, k, when(t)) for i, k, t in attempts if created <= when(t) <= merged]
    starts.sort(key=lambda a: (a[2], a[0], a[1]))
    handoff = None
    if created < prev:
        after = [t for _, _, t in starts if t >= prev]
        handoff = minutes(min(after), prev) if after else None

    measured = {}
    for run in listing(f"{R}/commits/{head}/check-runs?per_page=100&filter=all", "check_runs"):
        if (
            run["app"]["id"] == APP and run["status"] == "completed" and run["conclusion"] == "success"
            and run["name"] in CHECKS and when(run["completed_at"]) <= merged
        ):
            rank = (run["completed_at"], run["id"])
            if run["name"] not in measured or rank > (measured[run["name"]]["completed_at"], measured[run["name"]]["id"]):
                measured[run["name"]] = run
    minutes_of = {n: minutes(when(r["completed_at"]), when(r["started_at"])) for n, r in measured.items()}

    before_step = test_step = None
    awt = measured.get("Agent Workflow Tests")
    if awt:
        job = gh("api", f"{R}/actions/jobs/{awt['id']}")
        step = next((s for s in job["steps"] if s["name"] == STEP), None)
        if step:
            before_step = minutes(when(step["started_at"]), when(job["started_at"]))
            test_step = minutes(when(step["completed_at"]), when(step["started_at"]))
    wall = green = None
    if measured:
        wall = minutes(max(when(r["completed_at"]) for r in measured.values()), min(when(r["started_at"]) for r in measured.values()))
        green = minutes(merged, max(when(r["completed_at"]) for r in measured.values()))

    issue = re.match(r"issue-(\d+)-", branch)
    table.append([
        f"#{pull['number']}", issue.group(1) if issue else "-", merged.strftime("%Y-%m-%d %H:%M:%S"),
        cell(minutes(merged, created)), cell(max(0, minutes(prev, created))),
        cell(minutes(merged, max(created, prev))), cell(handoff), str(len(starts)),
        cell(minutes_of.get("Nix Eval")), cell(minutes_of.get("Agent Workflow Tests")),
        cell(before_step), cell(test_step), cell(minutes_of.get("Instruction Budget")),
        cell(wall), cell(green),
    ])
    provenance.append([
        f"#{pull['number']}", head[:12],
        *(str(measured[n]["id"]) if n in measured else "-" for n in CHECKS),
        " ".join(f"{i}/{k}" for i, k, _ in starts) or "-",
    ])

print("| " + " | ".join(HEADERS) + " |")
print("|---:|---:|---|" + "---:|" * 12)
for row in table:
    print("| " + " | ".join(row) + " |")
print()
print("| Figure | Median | p90 | Max | Sum |")
print("|---|---:|---:|---:|---:|")
for index in range(3, 15):
    values = [float(row[index]) for row in table if row[index] != "-"]
    if values:
        ordered = sorted(values)
        figures = [statistics.median(values), ordered[math.ceil(0.9 * len(values)) - 1], max(values), sum(values)]
        text = " | ".join(f"{x:.1f}" for x in figures)
    else:
        text = " | ".join(["-"] * 4)
    print(f"| {HEADERS[index]} | {text} |")
print()
print(f"Landings: {len(table)}, merged {table[0][2]} to {table[-1][2]} (UTC).")
if indirect:
    print("Indirect merges (no lock cycle of their own): " + "; ".join(
        f"#{p['number']} merged {when(p['mergedAt']).strftime('%Y-%m-%d %H:%M:%S')}" for p in indirect
    ) + " (UTC).")
print()
print("| PR | Head | Nix Eval check run | Agent Workflow Tests check run | Instruction Budget check run | CI run attempts |")
print("|---:|---|---:|---:|---:|---|")
for row in provenance:
    print("| " + " | ".join(row) + " |")
PY
```

## Proposal

Three speed-ups have a saving per landing that the summary table gives as the median of one row, and each keeps the three required checks and the head they run on. A shortens the `Agent Workflow Tests` job's steps before its test step (median 0.2 minutes, `.github/workflows/ci.yaml` only). B shortens the holder's wait for green and merge (median 0.7 minutes, the delivery programs). C shortens the gap between one merge and the next waiter's start (median 1.4 minutes, one lock file). A quarter of the median Hold of 14.7 minutes is 3.7 minutes, and none of the three medians reaches it, so the one with the largest median is proposed: C. These are medians of the measured rows, not bounds on what a change would save; a median bounds no single landing and no sum.

**What changes.** The first waiter finds a closed lock only at a whole 120 second poll, because a merge leaves the lock's oid unchanged and the 20 second ref reads do not see it (ADR-claims-012, "The grace." and "Poll rate." bullets). A follow-up makes that waiter notice the merge sooner, so its start is not up to a poll late. The file that follow-up changes is `python/agent_tools/claims/forge_land_lock.py`. The forge-clock order of ADR-claims-012 and the CAS lock of ADR-claims-004 are kept: only how soon the first waiter looks again changes, never who is first or how the lock is taken. `.github/branch-protection.json` does not change, and neither does the sync-under-the-lock step. This document only proposes it; adopting it is a later issue.

**Expected saving per queued pull request (an assumed scenario, not a bound):** assume 1.4 min per landing ahead of it (the median of `Handoff (min)`) is the polling delay that C removes. Under that assumption a pull request with k landings ahead of it waits about k x 1.4 minutes less, and its own hold is unchanged: the lock hold of each holder is the same length, and the saving is the gap between one landing and the next waiter's start, which the estimated Hold (it starts at the previous merge) shows and the lock hold does not. For the 16 Nov case of five queued pull requests, that is 5 x 1.4 = 7.0 minutes. The assumption is not a measurement. The median does not bound any one handoff or the sum of k of them (the p90 handoff is 5.8 minutes and one landing, #1159, took 83.0), and a handoff also holds the waiter's sync push and the CI run's creation, which faster polling does not remove, so the removable polling delay is unknown here; the only bound the table gives is that a landing's saving cannot exceed its own handoff. Measuring that delay needs the lock's poll times, which the forge does not keep.

**Why every required check still runs on a head up to date with `main`.** `Nix Eval`, `Agent Workflow Tests` and `Instruction Budget` stay required by `.github/branch-protection.json` with `strict` true. The holder still syncs under the lock and merges with `--match-head-commit` at the synced head. C changes only when the next holder starts, not which head the checks run on, so no merge is gated differently; merge safety keeps coming from the required status checks on the pull request (`.agents/knowledge/rejections/ungated-agent-merges.md`).

## Alternatives considered

- **A, a shorter set-up before the test step.** The median of `AWT before test step (min)` is 0.2 minutes per landing, and it shortens each holder's own hold. It changes `.github/workflows/ci.yaml` only, but it is the smallest saving of the three: the one large value (3.5 minutes, #1175) is not typical.
- **B, a shorter wait between green and merge.** The median of `Green to merge (min)` is 0.7 minutes per landing (p90 1.3, maximum 9.2). It changes the delivery programs rather than one file, and its median is smaller than C's.
- **A faster suite, `SUITE_RUNNER_JOBS`, a larger runner, or the `nix shell` realization inside the test step.** The test step is almost all of the check (median 8.5 minutes), but no column splits it further, so saving not measured here; each needs its own measurement before it can be proposed.
- **GitHub's merge queue (`merge_group`).** It replaces the lock and the up-to-date rule with the forge's queue, and changes branch protection, the CI triggers and the delivery programs. Saving not measured here, and a much larger change than one lock file.
- **Landing several queued pull requests as one batch with one CI cycle.** A merged head would no longer be tested alone and a red batch needs bisecting; less safe, and saving not measured here.
- **Dropping `strict`, or skipping the sync when the new commits on `main` touch other files.** Unsafe: the merged head would not be tested on top of the current `main`, which is what the required checks are there to prove.
