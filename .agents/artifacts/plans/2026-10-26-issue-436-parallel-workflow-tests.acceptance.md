# Acceptance record — issue 436

Taken on host eleven-m5; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/436).

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] A run that includes a deliberately failing module exits non-zero, and that module's failure output appears as one contiguous block — measured: a runner test added to the agent workflow test suite | code | `tests/test_suite_runner.py::FailureIsolationTest::test_a_failing_member_fails_the_run_and_keeps_its_output_in_one_block` (exit 1; every marker of the failing member lies between its `begin` and `end` lines with no runner line or peer marker there), run in the suite by `just agent-workflow-tests` once Task 2 enrols it. | in final verification | — | — | — |
| AC2 | [code] The number of concurrently running modules never exceeds the configured cap, and the default cap is a fixed, documented value — measured: a runner test added to the agent workflow test suite | code | `tests/test_suite_runner.py::CapTest`: `test_two_jobs_reach_two_open_members_and_never_exceed_them`, `test_the_default_cap_is_four`, `test_help_names_the_command_and_documents_the_default` and `test_one_job_runs_members_one_at_a_time_with_their_output_live`. The default is the constant 4, documented in `--help`, the recipe comment (Task 2) and `python/README.md` (D5). | in final verification | — | — | — |
| AC3 | [code] Every run ends with a per-module wall-clock timing report covering every module in the suite — measured: a runner test added to the agent workflow test suite | code | `tests/test_suite_runner.py::ReportTest::test_every_run_ends_with_a_report_covering_every_member` and `::test_rows_run_slowest_first_with_ties_in_list_order`. | in final verification | — | — | — |
| AC4 | [code] The full suite passes in both parallel and serial modes at the head — measured: the Agent Workflow Tests (advisory) CI job, plus one serial-mode run cited in the PR | code | Parallel: sdd's final gate `just agent-workflow-tests`, and the advisory CI job on the PR and on the merge push (D8; cited by ship). Because the suite step is `continue-on-error: true`, a green job is not evidence: ship cites each run's `AGENT_WORKFLOW_OBSERVATION_V1` record with `raw.suite` `"success"` and the step log's `suite-runner: summary` line with `failed=0` (D15). Serial: `just agent-workflow-tests --jobs 1` at the final code head, exit 0 with `failed=0`. Its summary line is recorded in acceptance row `AC4` and cited in the PR. | serial: `suite-runner: summary members=104 passed=104 failed=0 jobs=1 wall=1369.1s`; parallel audit: run 1 `suite-runner: summary members=104 passed=104 failed=0 jobs=4 wall=400.5s`; run 2 `suite-runner: summary members=104 passed=104 failed=0 jobs=16 wall=182.4s`; run 3 `suite-runner: summary members=104 passed=104 failed=0 jobs=4 wall=369.1s`; residue: no hazard (D7); CI: the advisory job on the PR and the merge push, cited by ship with each run's AGENT_WORKFLOW_OBSERVATION_V1 record showing raw.suite "success" and its suite-runner summary line showing failed=0 (the suite step is continue-on-error, so a green job alone proves nothing; D15) | 0e0f188e | host eleven-m5; Python 3.13.12; `just agent-workflow-tests --jobs 1`, `just agent-workflow-tests`, `just agent-workflow-tests --jobs 16`, `just agent-workflow-tests` (runs 1 to 3 in that order, then the serial run); each with `< /dev/null`, in the foreground under `launch-scope exec`, timeout 3600 s, from the worktree root | — |
| AC5 | [evidence] The test step finishes much sooner on CI — measured: duration of the Run agent workflow tests step of Agent Workflow Tests (advisory) on the merge commit's push to main, hosted ubuntu-24.04 runner, default worker cap; threshold ≤ 360 s (baseline: 1092 s in CI run 40194721214 at 0bce14ca) | evidence | Per D10, on the merge commit's push run to `main`: `gh run view <run> --repo fagenorn/nix-config --json jobs`, `completedAt − startedAt` of step "Run agent workflow tests" in job "Agent Workflow Tests (advisory)". Conditions: hosted ubuntu-24.04, default cap. Threshold: ≤ 360 s (baseline 1,092 s, run 40194721214 at `0bce14ca`). Task 5 writes row `AC5` as measured by ship after merge. The PR's CI run is the pre-merge reading cited in the PR. | not measured — read by ship from the merge commit's push run (D10) | — | hosted ubuntu-24.04, default cap 4, step "Run agent workflow tests" of job "Agent Workflow Tests (advisory)", threshold ≤ 360 s; the PR's CI run is the pre-merge reading cited in the PR; a reading over 360 s is returned to the caller, never answered by raising the default (D10) | — |

## Concurrency audit (D7)

| Run | Command | Exit | Summary | New git entries | Hazards |
|-----|---------|------|---------|-----------------|---------|
| 1 | `just agent-workflow-tests` | 0 | `suite-runner: summary members=104 passed=104 failed=0 jobs=4 wall=400.5s` | 0 | none |
| 2 | `just agent-workflow-tests --jobs 16` | 0 | `suite-runner: summary members=104 passed=104 failed=0 jobs=16 wall=182.4s` | 0 | none |
| 3 | `just agent-workflow-tests` | 0 | `suite-runner: summary members=104 passed=104 failed=0 jobs=4 wall=369.1s` | 0 | none |
| serial | `just agent-workflow-tests --jobs 1` | 0 | `suite-runner: summary members=104 passed=104 failed=0 jobs=1 wall=1369.1s` | — | — |

- Run 1: 0 new paths under the real home; 1254 new system-temp entries, all session noise (1248 random-suffix `tmp*` entries and 6 `conformance-home-*`/`conformance-bin-*` entries with random `mkdtemp` suffixes, written by `home/common/agent-skills/tests/conformance_test_support.py`); no hazard candidate.
- Run 2: 3 new paths under the real home, all `~/.claude/skills/synced/<uuid>` (Claude Code's own settings sync, written by a concurrent session; no test names it); 1255 new system-temp entries, all random-suffix names except macOS's `TemporaryItems`; no hazard candidate.
- Run 3: 1 new path under the real home, a live session's `~/.claude/projects/…/subagents/agent-*.jsonl` transcript (this session; no test names it); 1255 new system-temp entries, all random-suffix names except macOS's `TemporaryItems`; no hazard candidate.
- Temp lists of runs 1 and 3 share no name, so no fixed temp name exists; the only name shared by any two runs is macOS's `TemporaryItems` (runs 2 and 3), which no test names.

### Timing report (run 1, default cap)

```text
suite-runner: timings, slowest first
suite-runner:   153.5s passed tests/test_review_feasibility.py
suite-runner:    98.2s passed home/common/agent-skills/tests/test_workflow_state.py
suite-runner:    94.4s passed home/common/agent-skills/tests/test_delivery_workflow.py
suite-runner:    93.3s passed tests/test_review_projection_cases.py
suite-runner:    76.8s passed home/common/agent-skills/tests/test_adopt_apply.py
suite-runner:    76.7s passed tests/test_orchestrate_control.py
suite-runner:    72.3s passed tests/test_review_issue121.py
suite-runner:    68.7s passed tests/test_review_derivation.py
suite-runner:    52.6s passed home/common/agent-skills/tests/test_attempt_migration.py
suite-runner:    48.2s passed tests/test_review_replay.py
suite-runner:    46.2s passed home/common/agent-skills/tests/test_adopt_project.py
suite-runner:    41.1s passed tests/test_review_compact121.py
suite-runner:    40.0s passed tests/test_guard_policy.py
suite-runner:    39.2s passed tests/test_review_issue100.py
suite-runner:    37.9s passed home/common/agent-skills/tests/test_control_decisions.py
suite-runner:    35.9s passed home/common/agent-skills/tests/test_adopt_verify.py
suite-runner:    35.9s passed tests/test_sdd_gate.py
suite-runner:    33.2s passed home/common/agent-skills/tests/test_control_cutover.py
suite-runner:    32.8s passed home/common/agent-skills/tests/test_admission_replay.py
suite-runner:    27.8s passed home/common/agent-skills/tests/test_ship_delivery.py
suite-runner:    26.5s passed tests/test_launch_scope.py
suite-runner:    23.9s passed home/common/agent-skills/tests/test_delivery_sealing.py
suite-runner:    21.5s passed home/common/agent-skills/tests/test_delivered_control.py
suite-runner:    20.5s passed tests/test_review_history.py
suite-runner:    20.3s passed home/common/agent-skills/tests/test_review_package.py
suite-runner:    17.9s passed home/common/agent-skills/tests/test_attempt_custody.py
suite-runner:    16.8s passed tests/test_cache_keepalive.py
suite-runner:    13.2s passed home/common/agent-skills/evals/tests/test-run-eval-tree.sh
suite-runner:    13.1s passed tests/test_review_task7.py
suite-runner:    12.8s passed tests/test_review_witness.py
suite-runner:    12.2s passed home/common/agent-skills/tests/test_host_admission.py
suite-runner:    11.6s passed home/common/agent-skills/tests/test_artifact_budget.py
suite-runner:    11.3s passed tests/test_cache_proxy.py
suite-runner:    11.2s passed home/common/agent-skills/tests/test_resolve_platform.py
suite-runner:    10.5s passed home/common/agent-skills/tests/test_resolve_project.py
suite-runner:     8.8s passed tests/test_review_evidence.py
suite-runner:     7.7s passed tests/test_forge_adapter.py
suite-runner:     7.6s passed tests/test_transaction_core_sweep.py
suite-runner:     7.2s passed tests/test_promotion_lifecycle.py
suite-runner:     7.0s passed home/common/agent-skills/tests/test_conformance.py
suite-runner:     6.1s passed home/common/agent-skills/tests/test_conformance_checks.py
suite-runner:     5.3s passed tests/test_promotion_deployment.py
suite-runner:     5.0s passed home/common/agent-skills/tests/test_instruction_load.py
suite-runner:     5.0s passed tests/test_promotion_documents.py
suite-runner:     4.9s passed tests/test_context_meter.py
suite-runner:     4.9s passed tests/test_verified_tree.py
suite-runner:     4.8s passed home/common/agent-skills/tests/test_eval_cases.py
suite-runner:     4.8s passed home/common/agent-skills/tests/test_adopt_project_boundaries.py
suite-runner:     4.0s passed tests/test_review_range.py
suite-runner:     3.8s passed tests/test_claude_account_routing.py
suite-runner:     3.5s passed tests/test_review_compact100.py
suite-runner:     2.7s passed home/common/agent-skills/tests/test_diff_scope.py
suite-runner:     2.2s passed tests/test_lane_triage.py
suite-runner:     2.1s passed tests/test_launch_commit.py
suite-runner:     2.1s passed tests/test_agent_owner_report.py
suite-runner:     2.0s passed home/common/agent-skills/tests/test_sdd_workspace.py
suite-runner:     1.8s passed tests/test_transaction_proof.py
suite-runner:     1.7s passed home/common/agent-skills/tests/test_workflow_skill_contracts.py
suite-runner:     1.6s passed home/common/agent-skills/tests/test_resolve_platform_status.py
suite-runner:     1.6s passed tests/test_suite_runner.py
suite-runner:     1.4s passed tests/test_transaction_core.py
suite-runner:     1.3s passed home/common/agent-skills/tests/test_agent_evidence.py
suite-runner:     1.0s passed home/common/agent-skills/tests/test_adopt_references.py
suite-runner:     1.0s passed tests/test_transaction_recovery.py
suite-runner:     0.9s passed tests/test_transaction_recovery_settle.py
suite-runner:     0.8s passed tests/test_transaction_disposition.py
suite-runner:     0.8s passed tests/test_release_command.py
suite-runner:     0.7s passed home/common/agent-skills/tests/test_task_brief.py
suite-runner:     0.6s passed home/common/agent-skills/tests/test_conformance_registry.py
suite-runner:     0.6s passed tests/test_transaction_receipt.py
suite-runner:     0.6s passed tests/test_agent_gate_bundle.py
suite-runner:     0.5s passed tests/test_transaction_invocation.py
suite-runner:     0.5s passed tests/test_promotion_demo.py
suite-runner:     0.4s passed home/common/agent-skills/tests/test_delivery_model.py
suite-runner:     0.4s passed home/common/agent-skills/tests/test_ship_release_contracts.py
suite-runner:     0.4s passed tests/test_transaction_custody.py
suite-runner:     0.4s passed tests/test_release_adapter_core.py
suite-runner:     0.4s passed tests/test_agent_costs.py
suite-runner:     0.4s passed tests/test_agent_owner_replay.py
suite-runner:     0.4s passed tests/test_agent_model_drift_schema.py
suite-runner:     0.3s passed tests/test_attempt_custody.py
suite-runner:     0.3s passed tests/test_agent_model_drift_routing.py
suite-runner:     0.3s passed tests/test_agent_model_drift_scheduling.py
suite-runner:     0.3s passed tests/test_branch_protection.py
suite-runner:     0.2s passed home/common/agent-skills/tests/test_skill_lint.py
suite-runner:     0.2s passed home/common/agent-skills/tests/test_adopt_links.py
suite-runner:     0.1s passed home/common/agent-skills/tests/test_workflow_delivery.py
suite-runner:     0.1s passed tests/test_review_pack.py
suite-runner:     0.1s passed home/common/agent-skills/tests/test_dispatch_contracts.py
suite-runner:     0.1s passed home/common/agent-skills/tests/test_shell_example_contracts.py
suite-runner:     0.1s passed home/common/agent-skills/tests/test_agent_model_matrix.py
suite-runner:     0.1s passed tests/test_agent_tools_siblings.py
suite-runner:     0.1s passed tests/test_phase_budget.py
suite-runner:     0.1s passed tests/test_attempt_identity.py
suite-runner:     0.1s passed tests/test_transaction_plan.py
suite-runner:     0.1s passed tests/test_transaction_recovery_plan.py
suite-runner:     0.1s passed tests/test_release_grammar.py
suite-runner:     0.1s passed tests/test_release_profile.py
suite-runner:     0.1s passed tests/test_agent_model_drift_producer_integration.py
suite-runner:     0.1s passed tests/test_context_map_lint.py
suite-runner:     0.0s passed tests/test_agent_tools_canonical.py
suite-runner:     0.0s passed tests/test_sdd_brief.py
suite-runner:     0.0s passed tests/test_attempt_delivery.py
suite-runner:     0.0s passed tests/test_release_bridge.py
suite-runner: summary members=104 passed=104 failed=0 jobs=4 wall=400.5s
```
