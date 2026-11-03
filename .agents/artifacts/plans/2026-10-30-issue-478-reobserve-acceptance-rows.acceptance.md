# Acceptance record — issue #478

Taken on host mbp; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/478).

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] An acceptance state whose only pending rows are `code` rows measured by required CI checks resolves to `met` once those checks are green at the merge head, and the issue closes rather than holds. — measured: new case in `home/common/agent-skills/tests/test_ship_delivery.py` (fails today: holds) | code | `home/common/agent-skills/tests/test_ship_delivery.py` `test_a_ci_pending_code_row_observed_green_closes_the_issue` under `just agent-workflow-tests` | in final verification | 262bc458 | host mbp | met |
| AC2 | [code] A pending `human` row still holds the issue as `needs-verification`. — measured: same module | code | `home/common/agent-skills/tests/test_ship_delivery.py` `test_a_pending_human_row_still_holds_the_issue` under `just agent-workflow-tests` | in final verification | 262bc458 | host mbp | met |
| AC3 | [code] ship-issue's acceptance section states the re-observation step. — measured: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` | code | `home/common/agent-skills/tests/test_workflow_skill_contracts.py` `test_ship_issue_documents_carry_their_machine_text` (the two argv pins) and `test_phase_six_reobserves_pending_rows_between_the_watch_and_the_merge` under `just agent-workflow-tests` | in final verification | 262bc458 | host mbp | met |
| AC4 | [code] `just agent-workflow-tests` passes. — measured: `just agent-workflow-tests` | code | `just agent-workflow-tests` | in final verification | 262bc458 | host mbp | met |
