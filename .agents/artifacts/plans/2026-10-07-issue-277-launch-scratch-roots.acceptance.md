# Acceptance record — issue #277

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] scratch prints the same path on repeat calls and the path is recorded in the registry — measured: tests/test_launch_scope.py | code | `tests/test_launch_scope.py::ScratchTest::test_repeat_calls_print_one_recorded_root` | in final verification | — | — | met |
| AC2 | [code] A git worktree added inside the scratch root is gone from git worktree list and the disk after reap — measured: tests/test_launch_scope.py | code | `tests/test_launch_scope.py::ReapTest::test_a_reap_removes_the_root_and_the_worktrees_inside_it`, `::test_a_sweep_removes_a_superseded_launchs_root` | in final verification | — | — | met |
| AC3 | [code] A worktree outside every scratch root appears in unattributed_worktrees and still exists after reap — measured: tests/test_launch_scope.py | code | `tests/test_launch_scope.py::ReapTest::test_worktrees_outside_every_root_are_reported_and_kept` | in final verification | — | — | met |
| AC4 | [code] The leaf clause routes scratch through launch-scope scratch — measured: test_workflow_skill_contracts.py under just agent-workflow-tests | code | `LaunchScopeWiringContractsTest::test_the_worker_sentence_follows_every_composed_worker_line`, `::test_the_owner_runs_long_commands_through_exec` | in final verification | — | — | met |
