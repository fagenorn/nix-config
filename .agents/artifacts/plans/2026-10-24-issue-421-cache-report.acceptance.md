# Acceptance record — issue #421

Taken on host mbp; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/421).

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] A transcript fixture with a parent that ends its turn, is woken by a hand-back after 9 minutes and rewrites its context is reported as one death of kind "hand-back after end of turn" with the correct premium — measured: new cases in `tests/test_agent_costs.py` run by `just agent-workflow-tests` | code | `tests/test_agent_costs.py::CacheScanTest::test_a_hand_back_after_end_of_turn_is_one_death_with_its_premium` (one death of kind `hand-back after end of turn`, gap 542 s, premium `32,002 × (6.25 − 0.50) / 1e6`), run by `just agent-workflow-tests` in sdd's final gate. | in final verification | — | — | — |
| AC2 | [code] A fixture whose calls straddle the threshold reports only the above-threshold reread cost, and a fixture subagent's first request yields its write/read and per-attachment sizes — measured: same test module | code | `CacheScanTest::test_only_reads_past_the_threshold_are_priced` (calls below, at and above 120k; only the reads past it priced) and `CacheScanTest::test_first_call_and_attachments_before_the_second_call_are_the_start_up` (first write/read and each attachment's characters, a later attachment excluded), same module and gate. | in final verification | — | — | — |
| AC3 | [code] Opus-class pricing is $5 input / $25 output per Mtok — measured: a pricing test in the same module, failing against the current $15 row | code | `ScanFileTest::test_opus_class_list_price_is_five_and_twenty_five_per_mtok` (expects $53.00 for the fixture; the $15 row yields $159.00), same module and gate. | in final verification | — | — | — |
| AC4 | [evidence] On the real transcripts for 2026-10-10 → 2026-10-24 the report shows subagent cache deaths within ±15 % of 2,646 and general-purpose above-120k reread within ±15 % of $2.2k — measured: `just agent-costs` with the new report over `~/.claude/projects` on mbp, numbers pasted in the PR | evidence | On mbp at the final code head: `just agent-costs --report cache --events-since 2026-10-10T00:00:00Z --events-before 2026-10-24T21:40:00Z` over `~/.claude/projects`; thresholds: the totals line's `Subagent deaths` within ±15 % of 2,646 (2,250–3,042) and the `general-purpose` row's `reread above` cell within ±15 % of $2,200 ($1,870–$2,530). Acceptance-record row `AC4`; never tuned toward the target (D11). | `Cache report (events 2026-10-10T00:00:00Z → 2026-10-24T21:40:00Z, 5,572 transcripts, 177,588 calls)` `Subagent deaths 3,011 ($2,593 premium); main-session deaths 260 ($432)` `general-purpose           1,469        $2,156   178.91k   314.58k   907.45k` subagent deaths 3,011 (+13.8 % of 2,646; band 2,250–3,042: inside) general-purpose reread above 120k $2,156 (−2.0 % of $2,200; band $1,870–$2,530: inside) | 13be52df | host mbp; `~/.claude/projects` 11G (`du -sh`); command `just agent-costs --report cache --events-since 2026-10-10T00:00:00Z --events-before 2026-10-24T21:40:00Z`; finished 2026-10-25T01:08:18Z after 4 s; stderr holds only the recipe echo `PYTHONPATH="/Users/anis/tmp/nix-config/.worktrees/worktree-issue-421-orchestrated/python" python3 -m agent_tools.agent_costs --report cache --events-since 2026-10-10T00:00:00Z --events-before 2026-10-24T21:40:00Z`; rule not tuned (D11) | — |

## AC4 run output

```text
Cache report (events 2026-10-10T00:00:00Z → 2026-10-24T21:40:00Z, 5,572 transcripts, 177,588 calls)

Cache deaths (idle gap > TTL - 10s, TTL 5m for subagents and 1h for main sessions; rewrite > 50% of a > 5k-token context; premium = rewrite at write price less a warm read):

agent type          cause                                deaths  median gap  premium
------------------  -----------------------------------  ------  ----------  -------
general-purpose     hand-back after end of turn           1,326       11.3m   $1,198
general-purpose     long foreground command                 820       11.4m     $816
general-purpose     task notification after end of turn     288       25.0m     $268
main                hand-back after end of turn             126      112.9m     $216
implementer         long foreground command                 399       10.1m     $167
main                task notification after end of turn      71      195.6m     $117
main                message after end of turn                49      164.1m      $76
implementer         message after end of turn                46        6.5m      $27
general-purpose     child dispatch                           19       10.5m      $21
main                other tool                               12      210.7m      $21
general-purpose     message after end of turn                23       12.5m      $20
owner-1826          child dispatch                           18        9.1m      $17
owner-1818          child dispatch                            8       11.2m      $11
reviewer            long foreground command                  11       13.9m      $10
owner-1827          child dispatch                            6        7.1m       $6
owner-1818          message after end of turn                 3       13.3m       $4
evidence-2008-2009  long foreground command                   3        7.2m       $4
owner-1818          long foreground command                   2        9.4m       $4
owner-1825          child dispatch                            5       19.8m       $4
owner-1819          child dispatch                            4       50.4m       $3
reviewer            message after end of turn                 2        6.7m       $3
general-purpose     other tool                                3       17.6m       $2
owner-1826          long foreground command                   2        6.8m       $2
main                long foreground command                   2      396.4m       $2
mechanic            long foreground command                   7        9.7m       $1
implementer         task notification after end of turn       3       10.6m       $1
implementer         other tool                                3        6.2m       $1
evidence-2008-2009  message after end of turn                 1       17.7m       $1
owner-1825          long foreground command                   1        9.6m       $1
Explore             task notification after end of turn       1       10.5m       $1

... 5 more rows not shown (--top 35 for all)

Subagent deaths 3,011 ($2,593 premium); main-session deaths 260 ($432)

Reread above 120.00k tokens of context (cache reads past that position at the read price; peak = largest single-call context per transcript):

agent type          transcripts  reread above  peak p50  peak p90  peak max
------------------  -----------  ------------  --------  --------  --------
general-purpose           1,469        $2,156   178.91k   314.58k   907.45k
main                        152          $390   128.21k   309.57k   753.16k
implementer               1,354          $240    92.43k   171.66k   751.12k
reviewer                  1,517          $224    79.45k   204.08k   409.03k
Explore                     106           $12    97.31k   181.13k   376.71k
owner-1818                    1           $11   387.42k   387.42k   387.42k
evidence-2008-2009            1            $6   301.45k   301.45k   301.45k
owner-1826                    1            $6   301.26k   301.26k   301.26k
owner-1827                    1            $4   273.06k   273.06k   273.06k
owner-1825                    1            $1   190.05k   190.05k   190.05k
fork                          4            $1   174.64k   175.74k   175.74k
retro-orch-facts              1            $0   171.06k   171.06k   171.06k
owner-1819                    1            $0   171.50k   171.50k   171.50k
mechanic                     86            $0    56.15k    68.19k   239.44k
retro-guard                   1            $0   137.39k   137.39k   137.39k
reviewer-lite               874            $0    22.87k    39.15k   127.09k
retro-gh-token                1            $0   116.37k   116.37k   116.37k
unknown                       1            $0   115.68k   115.68k   115.68k

Subagent start-up (first request's cache write and read; characters of each start-up attachment sent before the second request; medians over the subagents that carried it):

agent type          subagents  1st write  1st read  skill listing  instructions  MCP instructions  deferred tools  agent listing  environment
------------------  ---------  ---------  --------  -------------  ------------  ----------------  --------------  -------------  -----------
reviewer                1,517     15.39k     3.49k         23.83k         9.94k             4.33k               -              -        1.17k
general-purpose         1,469     21.17k    17.71k         23.83k         9.94k             4.33k           7.48k          3.83k        1.17k
implementer             1,354     18.85k    17.21k         23.83k         9.94k             4.33k           7.48k          3.83k        1.17k
reviewer-lite             874      9.20k         0              -         9.94k             4.33k               -              -        1.17k
Explore                   106     19.52k         0         24.84k             -             4.33k           7.44k              -        1.17k
mechanic                   86     26.78k         0         22.56k         9.94k             4.33k           7.77k          3.83k        1.17k
fork                        4      3.14k   144.68k              -             -                 -               -              -            -
evidence-2008-2009          1     39.66k         0         23.83k         9.94k             6.41k           8.41k          3.83k        1.17k
owner-1818                  1     36.48k         0         23.83k         9.70k             4.33k           6.64k          3.83k        1.17k
owner-1819                  1     40.11k         0         23.83k         9.70k             4.33k           6.64k          3.83k        1.17k
owner-1825                  1     36.43k         0         23.83k         9.70k             4.33k           6.64k          3.83k        1.17k
owner-1826                  1     36.48k         0         23.83k         9.70k             4.33k           6.64k          3.83k        1.17k
owner-1827                  1     17.76k    18.77k         23.83k         9.70k             4.33k           6.64k          3.83k        1.17k
retro-gh-token              1     41.99k         0         21.27k         9.94k             6.38k           7.79k          3.83k        1.45k
retro-guard                 1     19.54k    22.64k         21.27k         9.94k             6.38k           7.79k          3.83k        1.45k
retro-orch-facts            1     19.55k    22.64k         21.27k         9.94k             6.38k           7.79k          3.83k        1.45k
unknown                     1      1.93k   113.75k              -             -                 -               -              -            -

NOTE: cache reads measure logical context re-processing (tokens the model
attended to via prompt cache), and est $ applies public list prices — this is
comparative telemetry for run-over-run analysis, NOT billing data.
```
