# Acceptance record — issue #477

Taken on host mbp; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/477).

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] Evidence measured at commit C stays fresh at C+1 when C+1 changes only the acceptance record. — measured: new case in the sdd final-review / acceptance freshness tests (`home/common/agent-skills/tests/test_sdd_gate.py` or the module owning freshness) (fails today: stale) | code | `tests/test_verified_tree.py` `test_a_commit_that_changes_only_the_record_stays_fresh` under `just agent-workflow-tests` (spec D7) | in final verification | 6d283a0e | host mbp | met |
| AC2 | [code] Evidence measured at C is stale at C+1 when C+1 changes a file inside the measured tree. — measured: same test module | code | `tests/test_verified_tree.py` `test_a_commit_that_changes_a_measured_file_is_stale` under `just agent-workflow-tests` | in final verification | 6d283a0e | host mbp | met |
| AC3 | [code] The sdd final-review guidance states the rule. — measured: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` | code | `home/common/agent-skills/tests/test_workflow_skill_contracts.py` `test_sdd_documents_carry_their_machine_text` (the `verified-tree fresh` argv pin, spec D6) under `just agent-workflow-tests` | in final verification | 6d283a0e | host mbp | met |
| AC4 | [code] `just agent-workflow-tests` passes. — measured: `just agent-workflow-tests` | code | `just agent-workflow-tests` | in final verification | 6d283a0e | host mbp | met |
