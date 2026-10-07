# Acceptance record — issue #279

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] resolve-project accepts a valid light_lane, rejects unknown keys, a bad mode and a non-positive budget, and treats absent and null as unsupported — measured: test_resolve_project.py | code | `home/common/agent-skills/tests/test_resolve_project.py::LightLaneTest` under `just agent-workflow-tests` | in final verification | — | — | met |
| AC2 | [code] lane-triage evaluate returns light only for an all-no record, full for any hit or doubt, and adds risk_path to hits for a path matching a risk_paths glob — measured: package tests under tests/ | code | `tests/test_lane_triage.py::LaneTriageVerdictTest` under `just agent-workflow-tests` | in final verification | — | — | met |
| AC3 | [code] lane-triage exits 2 when light_lane is absent — measured: the same package tests | code | `tests/test_lane_triage.py::LaneTriageRefusalTest::test_an_absent_light_lane_is_unsupported` under `just agent-workflow-tests` | in final verification | — | — | met |
| AC4 | [code] from-issue Phase 0 names the triage record and the shadow behavior — measured: test_workflow_skill_contracts.py under just agent-workflow-tests | code | `home/common/agent-skills/tests/test_workflow_skill_contracts.py::LaneTriageContractsTest::test_phase_zero_runs_lane_triage_in_shadow` under `just agent-workflow-tests` | in final verification | — | — | met |
