# Acceptance record — issue #380

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | Fixture: a moved tree that becomes one level deeper, containing a Python file with `ROOT = HERE.parents[N]` reaching the repository root and a TOML/lock pair with a `../`-climbing path to a sibling tree. `plan` surfaces them under the new class; `rewrite` makes them resolve to the same target as on base (checked by path arithmetic in the test), and `retain` leaves them byte-identical. | code | `test_adopt_apply.py::DepthPolicyApplyTest`, `test_adopt_project.py::DepthPolicyPlanTest::test_climbs_to_the_root_open_their_own_policies` | — | — | — | pending |
| AC2 | Parent counts and `../` climbs that stay inside the moved tree are not surfaced. | code | `test_adopt_project.py::DepthPolicyPlanTest::test_climbs_to_the_root_open_their_own_policies`, `TextClimbTest::test_climbs_inside_the_tree_are_not_surfaced`, `PythonClimbTest::test_chains_inside_the_tree_are_not_surfaced` | — | — | — | pending |
| AC3 | A move that keeps the same depth surfaces nothing new. | code | `test_adopt_references.py::TextClimbTest::test_a_same_depth_move_surfaces_nothing_new` | — | — | — | pending |
| AC4 | Existing #350/#372/#376 behaviour and answers are unchanged; existing tests stay green. | code | existing classes of the adopt test files, unedited; `TextClimbTest::test_the_depth_read_set_gets_the_depth_reading_only` | — | — | — | pending |
| AC5 | `verify` still reports `adoption-commit-derived` passed on a fixture adopt commit that used `rewrite`. | code | `test_adopt_verify.py::DepthRewriteVerifyTest::test_a_rewritten_climb_verifies_as_derived` | — | — | — | pending |
| AC6 | `just agent-workflow-tests` passes. | code | `just agent-workflow-tests` | — | — | — | pending |
