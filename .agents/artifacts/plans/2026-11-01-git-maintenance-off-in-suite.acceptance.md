# Acceptance record — issue #496

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] A commit in a repository created under the suite runner's child environment starts no `git maintenance` process, and leaves no `maintenance.lock` behind at any point. Measured by: a test added to the agent workflow test suite that commits with `GIT_TRACE2_EVENT` and asserts no maintenance child event. | code | `tests/test_suite_runner.py::GitMaintenanceTest` (serial, parallel and the outside-the-runner control), run by `just agent-workflow-tests` | in final verification | a2564b16 | git 2.51.2, darwin | met |
| AC2 | [code] The full suite passes in parallel mode at the head. Measured by: the Agent Workflow Tests (advisory) CI job. | code | `just agent-workflow-tests` (default `--jobs 4`); CI `Agent Workflow Tests (advisory)` at the PR head | in final verification | a2564b16 | local darwin run; CI read at ship | met |
