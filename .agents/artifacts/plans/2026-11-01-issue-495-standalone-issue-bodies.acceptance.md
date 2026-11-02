# Acceptance record — issue #495

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] to-issues' issue template has a Problem section before What to build, and the skill states the first-use explanation rule and the stranger-read step — measured: new case beside `ToIssuesCriterionLineContractsTest` in `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (fails today: no Problem section) | code | `ToIssuesStandaloneBodyContractsTest` (test_workflow_skill_contracts.py), under `just agent-workflow-tests` | in final verification | — | — | met |
| AC2 | [code] The existing acceptance-criteria contracts for the template still pass — measured: `ToIssuesCriterionLineContractsTest` in the same module | code | `ToIssuesCriterionLineContractsTest` (test_workflow_skill_contracts.py), under `just agent-workflow-tests` | in final verification | — | — | met |
| AC3 | [code] `just agent-workflow-tests` and `just build` pass — measured: `just agent-workflow-tests`, `just build` | code | `just agent-workflow-tests`, `just build` | in final verification | — | — | met |
