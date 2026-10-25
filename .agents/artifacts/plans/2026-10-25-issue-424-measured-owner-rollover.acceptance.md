# Acceptance record — issue #424

Taken on host mbp; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/424).

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] Given a transcript fixture whose last call used 87,412 tokens, a `workflow-state progress` command without `--context-tokens`, and one with a wrong value, are both rewritten to carry 87412; other commands pass through unchanged — measured: hook unit tests run by `just agent-workflow-tests` | code | `tests/test_context_meter.py::ProgressRewriteTest::test_the_87412_fixture_replaces_a_missing_or_wrong_count` (no count, separate, `=`, abbreviated forms all carry exactly 87412) and `::test_other_commands_pass_through_untouched`, run by `just agent-workflow-tests`. | in final verification | — | — | — |
| AC2 | [code] The crossing instruction is injected exactly once when a fixture's context goes from 105k to 112k and not again at 118k — measured: same test module | code | `tests/test_context_meter.py::CrossingTest::test_105k_to_112k_injects_once_and_118k_does_not`, same recipe. | in final verification | — | — | — |
| AC3 | [code] The default context ceiling is 120000 with headroom 10000 and is defined once; skill-text tests carry no restated ceiling — measured: workflow-state tests and the skill-text tests in `just agent-workflow-tests` | code | `home/common/agent-skills/tests/test_workflow_state.py::PhaseBudgetDefaultsTest::test_default_ceiling_hands_off_at_110000_and_continues_at_109999` and `::test_the_four_defaults_have_one_home`, and `test_workflow_skill_contracts.py::WorkflowSkillContractsTest::test_owner_has_executable_phase_gate_and_action_semantics` (no `--context-ceiling`, `--context-headroom` or `--context-tokens` in from-issue text), same recipe. | in final verification | — | — | — |
| AC4 | [code] The lifecycle guard's adversarial table stays green with the new hook registered — measured: `tests/test_claude_permission_guard.py` via `just agent-workflow-tests` | code | The guard suite (`tests/test_claude_permission_guard.py`) against the built settings: discovery finds exactly the guard and the meter in the one Bash entry, guard checks as before, adversarial table unchanged; prints `OK`. | in final verification | — | — | — |
| AC5 | [evidence] On `just evals from-issue 1` every `workflow-state progress` call carries a measured `--context-tokens`, and no owner API call exceeds 125k context — measured: the eval transcript plus the `just agent-costs` peak-context table, on mbp | evidence | On mbp at the final code head, `EVAL_TREE=<worktree> EVAL_SETTINGS=<built settings> just evals from-issue 1`; the audit of its copied transcripts shows every `workflow-state progress` tool call joined to a meter note naming a measured value (a zero count recorded as vacuous, with the live probe, per D16), and `just agent-costs --report cache --projects-dir <copied transcripts> --days 0` plus the audit show no owner transcript peaking above 125,000. Acceptance-record row `AC5`. | `TOTAL progress_calls=0 measured=0` (0 progress calls — first clause vacuous on eval 1 (D16); the live rewrite probe below stands as the rewrite evidence)<br>`-private-var-folders-t4-b5y8ggd92zb044029--7wr9w0000gp-T-eval-from-issue-1-ZsOv8x-repo/914f6e02-5ba7-40e1-b5b0-53c4a1c31621.jsonl	main	owner=True	peak=247379	progress_calls=0`<br>`main                  1            $1   247.38k   247.38k   247.38k`<br>unmet: the owner transcript `main` peaks at 247379 (reread table `peak max` 247.38k), above the 125000 bound; the first clause is vacuous, not met by measurement | 6b9544ba | host mbp; Claude Code 2.1.302; EVAL_TREE=/Users/anis/tmp/nix-config/.worktrees/worktree-issue-424-orchestrated; EVAL_SETTINGS=/nix/store/09wjqd6dkqn5x3cirar5p6d0nvgnan21-claude-code-settings.json; EVAL_MODEL default; eval finished 2026-10-25T04:51:12Z; copied project folder -private-var-folders-t4-b5y8ggd92zb044029--7wr9w0000gp-T-eval-from-issue-1-ZsOv8x-repo; tree mode runs the deployed workflow-state (only command-table rows are shimmed, D16); no `just switch` | — |
| AC6 | [evidence] No regression: `just evals from-issue 1` passes — measured: eval verdict on mbp | evidence | The same eval run's `VERDICT:` line reads `PASS`. Acceptance-record row `AC6`. | `VERDICT: PASS (9/9 asserts)` (met) | 6b9544ba | host mbp; Claude Code 2.1.302; EVAL_TREE=/Users/anis/tmp/nix-config/.worktrees/worktree-issue-424-orchestrated; EVAL_SETTINGS=/nix/store/09wjqd6dkqn5x3cirar5p6d0nvgnan21-claude-code-settings.json; EVAL_MODEL default; eval finished 2026-10-25T04:51:12Z; copied project folder -private-var-folders-t4-b5y8ggd92zb044029--7wr9w0000gp-T-eval-from-issue-1-ZsOv8x-repo; tree mode runs the deployed workflow-state (only command-table rows are shimmed, D16); no `just switch` | — |
| AC7 | [code] Skill text does not grow — measured: `just agent-instruction-budget` passes without the `instruction-budget-raise` label | code | `just agent-instruction-budget` exits 0 without `--raise-label`. | in final verification | — | — | — |

## Live rewrite probe

Prompt used, a two-call probe (a warm-up call first), run from an empty scratch directory with the built settings (the prompt passed as one argument, so its backticks reach Claude Code literally):

```text
cd "$SCRATCH/probe" && CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1 timeout 300 claude -p --model haiku \
  --setting-sources project,local --settings "$SETTINGS" --dangerously-skip-permissions \
  --output-format json "Run these two Bash commands one at a time, in this order, then reply with only the second one's output: first `echo warm-up`, then `echo workflow-state progress --context-tokens 1`"
exit 0
$ grep -o 'workflow-state progress --context-tokens [0-9]*' "$PROBE" | sort -u
workflow-state progress --context-tokens 1
workflow-state progress --context-tokens 19858
$ grep -c 'carries --context-tokens [0-9]*, measured' "$PROBE"
3
```

A one-call probe is unmeasured because Claude Code 2.1.302 runs PreToolUse on a session's first tool call before that turn's usage record is in the transcript (spec D20), so the probe warms up with one call first.

## AC5 audit

```text
-private-var-folders-t4-b5y8ggd92zb044029--7wr9w0000gp-T-eval-from-issue-1-ZsOv8x-repo/914f6e02-5ba7-40e1-b5b0-53c4a1c31621/subagents/agent-aef336a65ae6e3fd8.jsonl	reviewer	owner=False	peak=55711	progress_calls=0
-private-var-folders-t4-b5y8ggd92zb044029--7wr9w0000gp-T-eval-from-issue-1-ZsOv8x-repo/914f6e02-5ba7-40e1-b5b0-53c4a1c31621.jsonl	main	owner=True	peak=247379	progress_calls=0
TOTAL progress_calls=0 measured=0
```

## AC5 reread table

```text
Cache report (all time, 2 transcripts, 133 calls)

Cache deaths (idle gap > TTL - 10s, TTL 5m for subagents and 1h for main sessions; rewrite > 50% of a > 5k-token context; premium = rewrite at write price less a warm read):

agent type  cause  deaths  median gap  premium
----------  -----  ------  ----------  -------

Subagent deaths 0 ($0 premium); main-session deaths 0 ($0)

Reread above 120.00k tokens of context (cache reads past that position at the read price; peak = largest single-call context per transcript):

agent type  transcripts  reread above  peak p50  peak p90  peak max
----------  -----------  ------------  --------  --------  --------
main                  1            $1   247.38k   247.38k   247.38k
reviewer              1            $0    55.71k    55.71k    55.71k

Subagent start-up (first request's cache write and read; characters of each start-up attachment sent before the second request; medians over the subagents that carried it):

agent type  subagents  1st write  1st read  skill listing  instructions  MCP instructions  deferred tools  agent listing  environment
----------  ---------  ---------  --------  -------------  ------------  ----------------  --------------  -------------  -----------
reviewer            1     11.54k         0         10.48k         1.93k             2.05k               -              -        1.65k

NOTE: cache reads measure logical context re-processing (tokens the model
attended to via prompt cache), and est $ applies public list prices — this is
comparative telemetry for run-over-run analysis, NOT billing data.
```

## AC6 eval output

```text
- **Spec:** `.claude/specs/2026-10-25-list-state-filter-design.md`. It has a `## Triage` section and a decision ledger with rows D1–D11.
- **Plan:** `.claude/plans/2026-10-25-list-state-filter.md`, with `task-1.md` and `task-2.md` under the `.tasks/` directory beside it.
  - Task 1 is `full` lane: the parser change and all tests in one commit. It uses `choices=STATES` and a mutually exclusive group.
  - Task 2 is `low-risk` lane: a README example and a check that the Backlog invariant matches the tests.
- **Backlog invariant:** I added one line to `docs/areas/backlog/CONTEXT.md` saying every `list` view keeps the Backlog's order and listing shape. `context-map-lint` passes.
- **Branch commits:** four docs-only commits, the last being `2f30254`.

**Standards review**
- `review.plan` is unsupported, so a fresh native `reviewer` (opus, high) ran the review. It found 0 blocking, 4 should-fix and 1 discussion item.
- I verified each finding against the live files before acting. S1–S3 and X1 were applied.
  - **S1:** the `--help` test now asserts the help text. A bare `--state` check passed even with no help text, because the usage line contains the flag.
  - **S2:** an exact-case test now pins that `--state DONE` is a usage error.
  - **S3:** Task 2's gate now runs the backing tests instead of grepping for their names.
  - **X1:** file order is now pinned on every view, with a hand-edited out-of-order fixture.
- S4 was rejected in part. The reviewer said the commit trailer should name Opus, but this session's trailer is Sonnet 5.5, matching every commit so far. The real flaw was a hardcoded trailer beside a contradicting "use yours" fallback, and I fixed that.
- After the edits, the plan (23,572 bytes, 3 files) and the spec (10,927 bytes) were re-measured and are within budget. Provenance and dispositions are recorded in the plan.
- I ran the plan's Task 1 code blocks as written in a scratch copy under `/tmp`, outside the repo. The result was 15 tests with 11 failure entries before the change and 23 tests green after it. Seven single-fault mutants were each caught by the intended test. That evidence is from the scratch copy, not from running the repo's tests.

**Needs your decision.** D2 reads criterion 1's "in id order" as Backlog order, so `--state done` follows file order. For any file the CLI wrote, that is identical to id order. It differs only for a hand-edited file with ids out of order, where criterion 1's literal wording and criterion 2 can't both hold. The plan pins the file-order reading. If you want a sort instead, D2, D10, the Backlog invariant and one test change.

**Other points**
- **Signing:** the repo-local git config had `commit.gpgsign false`, which conflicts with the policy's `signed: true`. I did not disable signing. I used `-S` explicitly and re-signed the first, locally unsigned commit by amend. All four commits carry an SSH signature. `git log` shows `N` only because no `allowedSignersFile` is configured, so it can't verify them.
- **`.worktrees/`:** it wasn't in `.gitignore`, so I added it to the repo-local `.git/info/exclude` only. A tracked `.gitignore` entry would be a separate change.
- **Upstream:** the branch currently tracks `origin/main`, so unset that before any push.
- **Leftover file:** `/tmp/planreview-evidence.txt` is the reviewer's evidence file; I left it alone.
claude exited 0 after 1182s

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

artifacts kept at: /private/var/folders/t4/b5y8ggd92zb044029__7wr9w0000gp/T/eval-from-issue-1.ZsOv8x
VERDICT: PASS (9/9 asserts)
```
