# Acceptance record — issue #500

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] Delivery-workflow CLI calls run in-process with stdin and working directory honoured. Per-class shared fixtures are copied per test, so a test that mutates its copy leaves the next test's copy unchanged. Measured by: tests added to the agent workflow test suite. | code | `home/common/agent-skills/tests/test_inprocess_cli.py::InProcessRunnerTest` (two tests), `home/common/agent-skills/tests/test_delivery_workflow.py::BuilderTransportTest`, `home/common/agent-skills/tests/test_attempt_migration.py::MigrateOnWriteTest::test_each_delivered_207_call_is_the_callers_own_copy` and `tests/test_orchestrate_control.py::WorktreeTest::test_a_world_never_sees_another_worlds_git_changes`, run by `just agent-workflow-tests` | in final verification | 4db2feab | host mbp; `just agent-workflow-tests` from the worktree root, in the foreground under `launch-scope exec`; Linux is covered by the PR's CI run | met |
| AC2 | [evidence] Measured by: the suite runner's timing table on the merge commit's push to main (Agent Workflow Tests (advisory), hosted ubuntu-24.04, default worker cap); threshold: `test_delivery_workflow` + `test_attempt_migration` + `test_orchestrate_control` together at least 120 s below the last push to main before the merge (419.7 s on run 41314186007). | evidence | **Post-merge only** (spec D8): the plan's `## Acceptance map` row AC2 commands (`gh run view <run-id> --repo fagenorn/nix-config --log > <log>` and its three-module `awk` sum), run for the merge commit's push run to `main` and for the last push run to `main` before the merge. Met when the merge run's sum is at least 120.0 s below the earlier run's. | pending: measurable only on the merge commit's push run to `main`; ship fills this row after the merge (D8). Branch direction, local and not the criterion's conditions, is in `## Branch direction` below | — | job "Agent Workflow Tests (advisory)", hosted ubuntu-24.04, default worker cap; issue-time baseline 419.7 s on run 41314186007 | unverified |

## Branch direction

Local readings at `4db2feab` on host mbp, recorded by the final gate (plan steps 2 and 4) as direction only. They are not the criterion's measurement (D8).

Step 2, `just agent-workflow-tests` (`summary members=111 passed=111 failed=0 jobs=4 wall=925.1s`), the three modules' timing rows:

- `test_orchestrate_control.py`: 174.5 s wall, 109.4 s cpu
- `test_delivery_workflow.py`: 92.2 s wall, 73.9 s cpu
- `test_attempt_migration.py`: 20.5 s wall, 14.1 s cpu

Step 4, paired serial timings (D10), base `0a25b807` in a detached scratch worktree, then head:

| module | tree | tests | wall_s | popen | workflow_state | write_projections | load1 |
|--------|------|-------|--------|-------|----------------|-------------------|-------|
| test_delivery_workflow | base | 86 | 199.9 | 988 | 720 | 0 | 78.3 |
| test_delivery_workflow | head | 87 | 91.8 | 494 | 135 | 0 | 19.0 |
| test_attempt_migration | base | 26 | 72.8 | 443 | 324 | 0 | 18.7 |
| test_attempt_migration | head | 27 | 16.0 | 39 | 4 | 0 | 12.7 |
| test_orchestrate_control | base | 47 | 118.5 | 469 | 26 | 54 | 10.5 |
| test_orchestrate_control | head | 48 | 125.0 | 287 | 26 | 16 | 7.2 |

The `workflow_state` column of `test_delivery_workflow` and `test_attempt_migration`, and the `write_projections` column of `test_orchestrate_control`, are lower at head than at base, as the plan's step 4 requires.
