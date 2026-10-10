# Acceptance record — issue #341

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | When the primary checkout's default branch has diverged from origin, `verify --register` succeeds once the adopt commit is reachable from `origin/<default>`, and reads the evidence record from that commit. The local branch, the working tree and any untracked files are left untouched. A fixture covers this. | code | `test_adopt_verify.py::RemoteRegistrationTest::test_a_diverged_local_branch_registers_from_the_remote` | in final verification | — | — || met |
| AC2 | Registration still fails when the adopt commit is not on the remote default branch. | code | `test_adopt_verify.py::RemoteRegistrationTest::test_an_unpushed_adoption_refuses_not_integrated` and `::test_an_adoption_only_on_its_apply_branch_refuses_not_integrated` | in final verification | — | — || met |
| AC3 | `just agent-workflow-tests` passes. | evidence | `just agent-workflow-tests` (threshold: exit status 0) | exit status 0; `Ran 2360 tests in 1344.680s` / `OK (skipped=3)`; `test-run-eval-tree: all checks passed` | f73e37a | darwin host, clean tree at f73e37a, launch-scope exec || met |
