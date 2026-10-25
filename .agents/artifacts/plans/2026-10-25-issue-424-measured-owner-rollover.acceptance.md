# Acceptance record — issue #424

Taken on host mbp; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/424).

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] Given a transcript fixture whose last call used 87,412 tokens, a `workflow-state progress` command without `--context-tokens`, and one with a wrong value, are both rewritten to carry 87412; other commands pass through unchanged — measured: hook unit tests run by `just agent-workflow-tests` | code | `tests/test_context_meter.py::ProgressRewriteTest::test_the_87412_fixture_replaces_a_missing_or_wrong_count` (no count, separate, `=`, abbreviated forms all carry exactly 87412) and `::test_other_commands_pass_through_untouched`, run by `just agent-workflow-tests`. | in final verification | — | — | — |
| AC2 | [code] The crossing instruction is injected exactly once when a fixture's context goes from 105k to 112k and not again at 118k — measured: same test module | code | `tests/test_context_meter.py::CrossingTest::test_105k_to_112k_injects_once_and_118k_does_not`, same recipe. | in final verification | — | — | — |
| AC3 | [code] The default context ceiling is 120000 with headroom 10000 and is defined once; skill-text tests carry no restated ceiling — measured: workflow-state tests and the skill-text tests in `just agent-workflow-tests` | code | `home/common/agent-skills/tests/test_workflow_state.py::PhaseBudgetDefaultsTest::test_default_ceiling_hands_off_at_110000_and_continues_at_109999` and `::test_the_four_defaults_have_one_home`, and `test_workflow_skill_contracts.py::WorkflowSkillContractsTest::test_owner_has_executable_phase_gate_and_action_semantics` (no `--context-ceiling`, `--context-headroom` or `--context-tokens` in from-issue text), same recipe. | in final verification | — | — | — |
| AC4 | [code] The lifecycle guard's adversarial table stays green with the new hook registered — measured: `tests/test_claude_permission_guard.py` via `just agent-workflow-tests` | code | The guard suite (`tests/test_claude_permission_guard.py`) against the built settings: discovery finds exactly the guard and the meter in the one Bash entry, guard checks as before, adversarial table unchanged; prints `OK`. | in final verification | — | — | — |
| AC5 | [evidence] On `just evals from-issue 1` every `workflow-state progress` call carries a measured `--context-tokens`, and no owner API call exceeds 125k context — measured: the eval transcript plus the `just agent-costs` peak-context table, on mbp | evidence | On mbp at the final code head, `EVAL_TREE=<worktree> EVAL_SETTINGS=<built settings> just evals from-issue 1`; the audit of its copied transcripts shows every `workflow-state progress` tool call joined to a meter note naming a measured value (a zero count recorded as vacuous, with the live probe, per D16), and `just agent-costs --report cache --projects-dir <copied transcripts> --days 0` plus the audit show no owner transcript peaking above 125,000. Acceptance-record row `AC5`. | `TOTAL progress_calls=0 measured=0` (0 progress calls — first clause vacuous on eval 1 (D16); the live rewrite probe below stands as the rewrite evidence)<br>`-private-var-folders-t4-b5y8ggd92zb044029--7wr9w0000gp-T-eval-from-issue-1-4dEYKW-repo/df072805-e96e-4550-9c45-55d7467ea121.jsonl	main	owner=True	peak=269992	progress_calls=0`<br>`main                  1            $2   269.99k   269.99k   269.99k`<br>unmet: the owner transcript `main` peaks at 269992 (reread table `peak max` 269.99k), above the 125000 bound; the first clause is vacuous, not met by measurement | 4c40b7ce | host mbp; Claude Code 2.1.302; EVAL_TREE=/Users/anis/tmp/nix-config/.worktrees/worktree-issue-424-orchestrated; EVAL_SETTINGS=/nix/store/0mmqqjzf1b4z7kpmch5xnwckyxjspwzp-claude-code-settings.json; EVAL_MODEL default; eval finished 2026-10-25T04:13:23Z; copied project folder -private-var-folders-t4-b5y8ggd92zb044029--7wr9w0000gp-T-eval-from-issue-1-4dEYKW-repo; tree mode runs the deployed workflow-state (only command-table rows are shimmed, D16); no `just switch` | — |
| AC6 | [evidence] No regression: `just evals from-issue 1` passes — measured: eval verdict on mbp | evidence | The same eval run's `VERDICT:` line reads `PASS`. Acceptance-record row `AC6`. | `VERDICT: PASS (9/9 asserts)` (met) | 4c40b7ce | host mbp; Claude Code 2.1.302; EVAL_TREE=/Users/anis/tmp/nix-config/.worktrees/worktree-issue-424-orchestrated; EVAL_SETTINGS=/nix/store/0mmqqjzf1b4z7kpmch5xnwckyxjspwzp-claude-code-settings.json; EVAL_MODEL default; eval finished 2026-10-25T04:13:23Z; copied project folder -private-var-folders-t4-b5y8ggd92zb044029--7wr9w0000gp-T-eval-from-issue-1-4dEYKW-repo; tree mode runs the deployed workflow-state (only command-table rows are shimmed, D16); no `just switch` | — |
| AC7 | [code] Skill text does not grow — measured: `just agent-instruction-budget` passes without the `instruction-budget-raise` label | code | `just agent-instruction-budget` exits 0 without `--raise-label`. | in final verification | — | — | — |

## Live rewrite probe

Prompt used, a two-call probe (a warm-up call first), run from an empty scratch directory with the built settings:

```text
cd "$SCRATCH/probe3" && CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1 timeout 300 claude -p --model haiku \
  --setting-sources project,local --settings "$SETTINGS" --dangerously-skip-permissions \
  --output-format json "Run these two Bash commands one at a time, in this order, then reply with only the second one's output: first `echo warm-up`, then `echo workflow-state progress --context-tokens 1`"
exit 0
$ grep -o 'workflow-state progress --context-tokens [0-9]*' "$PROBE" | sort -u
workflow-state progress --context-tokens 1
workflow-state progress --context-tokens 17813
$ grep -c 'carries --context-tokens [0-9]*, measured' "$PROBE"
3
```

A one-call probe was unmeasured because Claude Code 2.1.302 runs PreToolUse on a session's first tool call before that turn's usage record is in the transcript (spec D20); the diagnostic numbers: the built meter run by hand on that finished one-call transcript measured 20013, and a second two-call diagnostic probe measured 19851 on its second call.

## AC5 audit

```text
-private-var-folders-t4-b5y8ggd92zb044029--7wr9w0000gp-T-eval-from-issue-1-4dEYKW-repo/df072805-e96e-4550-9c45-55d7467ea121/subagents/agent-a15cfb403cc408d19.jsonl	reviewer	owner=False	peak=61400	progress_calls=0
-private-var-folders-t4-b5y8ggd92zb044029--7wr9w0000gp-T-eval-from-issue-1-4dEYKW-repo/df072805-e96e-4550-9c45-55d7467ea121.jsonl	main	owner=True	peak=269992	progress_calls=0
TOTAL progress_calls=0 measured=0
```

## AC5 reread table

```text
Cache report (all time, 2 transcripts, 127 calls)

Cache deaths (idle gap > TTL - 10s, TTL 5m for subagents and 1h for main sessions; rewrite > 50% of a > 5k-token context; premium = rewrite at write price less a warm read):

agent type  cause  deaths  median gap  premium
----------  -----  ------  ----------  -------

Subagent deaths 0 ($0 premium); main-session deaths 0 ($0)

Reread above 120.00k tokens of context (cache reads past that position at the read price; peak = largest single-call context per transcript):

agent type  transcripts  reread above  peak p50  peak p90  peak max
----------  -----------  ------------  --------  --------  --------
main                  1            $2   269.99k   269.99k   269.99k
reviewer              1            $0    61.40k    61.40k    61.40k

Subagent start-up (first request's cache write and read; characters of each start-up attachment sent before the second request; medians over the subagents that carried it):

agent type  subagents  1st write  1st read  skill listing  instructions  MCP instructions  deferred tools  agent listing  environment
----------  ---------  ---------  --------  -------------  ------------  ----------------  --------------  -------------  -----------
reviewer            1     11.30k         0         10.48k         1.93k             2.05k               -              -        1.65k

NOTE: cache reads measure logical context re-processing (tokens the model
attended to via prompt cache), and est $ applies public list prices — this is
comparative telemetry for run-over-run analysis, NOT billing data.
```

## AC6 eval output

```text
Docs changed in the grill phase: the Backlog glossary gains a **View** term, the Backlog entry now states its order, and the listing-shape invariant is stated per View. `docs/CONTEXT-MAP.md` has the matching row, and `context-map-lint` passes. No ADR was written.

## The plan

- **Task 1** (low-risk): a test helper that captures stderr and `SystemExit`, plus tests that pin how bare `list` and `--all` behave today.
- **Task 2** (full): write the `--state` tests first, then the `cli.py` change, then one README example line.

## Standards review

The review ran as one fresh native `reviewer` (Opus, high effort), because `review.plan` is unsupported in the project config. It found no blocking issues, three should-fix items and one discussion item, and I verified each against the live files before applying it.

- **S1:** Task 2's scope check ran after staging, so it could miss an unstaged edit. It now runs before.
- **S2:** the invalid-state test now checks exactly the state names `open` and `done`, rather than two substring checks. I did this differently from the reviewer's suggestion, which would have hard-coded two known error-message formats.
- **S3:** the dictated code comment said "in place", but the code builds a new list. The wording is fixed.
- **N1:** I reproduced that on Python 3.14, `PYTHON_COLORS=1` overrides `NO_COLOR` and fails the help test, so the test environment now also sets `PYTHON_COLORS=0`.

The plan's test code and `cli.py` change pass in a scratch copy on Python 3.10, 3.11, 3.12, 3.13 and 3.14 (23 tests). They fail as expected (7 failures) against the unchanged CLI. Three deliberate breakages each turned the intended tests red.

## Things you should know

- **One decision of mine goes beyond the issue.** The spec says each view keeps the task file's order and never sorts, because criteria 2 and 5 outrank a literal reading of criterion 1's "id order" for hand-edited files. It is ledger row D7, guarded by a test.
- **Signing:** the repo's local git config sets `commit.gpgsign=false`, overriding your global `true`, while project policy says signed. I passed `-S` on every commit and each one carries an SSH signature. `git log` shows `N` only because no `allowedSignersFile` is configured. Later commits in this repo need `-S` too.
- **`.worktrees` was not git-ignored**, and the worktrees skill requires it. I added it to `.git/info/exclude` (local and untracked) instead of committing to `main`. You may want it in `.gitignore`.
- **The tracker is unsupported, so no PR or issue checks ran.**
- **Lane triage returned `light_lane_unsupported`**, so the full lane ran.
claude exited 0 after 1456s

--- asserts ---
PASS  a worktree was created
PASS  spec file exists under the retained specifications directory
PASS  spec logs at least one decision (ledger row or legacy auto-resolved entry)
PASS  plan file exists under the retained plans directory
PASS  every plan task has a falsifiable verification line
PASS  the plan's acceptance map has one row per issue criterion
PASS  spec and plan commits landed in the worktree
PASS  the base branch carries no spec or plan commits
PASS  the implementation was not executed

artifacts kept at: /private/var/folders/t4/b5y8ggd92zb044029__7wr9w0000gp/T/eval-from-issue-1.4dEYKW
VERDICT: PASS (9/9 asserts)
```
