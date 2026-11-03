# Acceptance record — issue #557

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] The test passes in the Agent Workflow Tests (advisory) job on a hosted runner, either by resolving the budget authority without relying on `PATH`, or by making the CLI available in the job the way the suite's other helpers are. | code | `tests/test_review_gate.py::GateTest::test_capture_refuses_output_no_real_producer_emits`, run by `just agent-workflow-tests` | in final verification | — | failed at Task 1's start commit under the no-installed-`PATH` stand-in; green under the stand-in at `022c330`; the PR's hosted Agent Workflow Tests (advisory) summary is the authoritative hosted reading (D4) | met |
| AC2 | [code] The push run to `main` after the fix reports `failed=0`. | code | Agent Workflow Tests (advisory) `suite-runner: summary` line on the first push run to `main` after the merge | — | — | post-merge observation (D4); no such run exists before the merge | unverified |
