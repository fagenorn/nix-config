# Acceptance record — issue #458

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | A merged PR whose remote branch survives `--delete-branch` completes `delete_remote_branch` under the guard with no human step | code | Guard suite: `test_remote_branch_deletion_arm`, `test_the_remote_deletion_form_deletes_only_the_named_branch`, `test_every_guarded_command_shape_gets_its_verdict` | Guard suite run at HEAD by the conformance reviewer: 89 tests OK; in final verification | d9a6f616 | `just build` settings and base-policy store paths | met |
| AC2 | The guard form table and ship-issue name the same remote-deletion spelling, with a shape test covering it | code | `test_every_guarded_command_shape_gets_its_verdict`; `ShipIssueGuardedCommandSweepTest.test_every_guarded_command_is_a_cited_form`; `test_ship_issue_documents_carry_their_machine_text` | in final verification | d9a6f616 | `just agent-workflow-tests` plus the Guard suite | met |
| AC3 | A remainder suspended on `human_gate` is not relaunched in a loop by `orchestrate-control` | code | `test_an_undirected_sweep_parks_a_gated_remainder_until_a_directed_one`; `FactsTest.test_direction_is_spent_on_the_first_sweep` | in final verification | d9a6f616 | `just agent-workflow-tests` | met |
