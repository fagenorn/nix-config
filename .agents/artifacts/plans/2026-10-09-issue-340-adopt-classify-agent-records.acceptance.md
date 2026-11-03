# Acceptance record — issue #340

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AC1 | A fixture project containing tracked files under `.claude/handoffs/`, `.claude/notes/` and `.claude/research/` plans to state `ready`, with no Nodo-specific special case. | code | test_adopt_project.py `RecordTreeClassificationTest.test_the_three_record_trees_plan_to_ready` | in final verification | — | — | met |
| AC2 | Any candidate that remains unclassifiable carries a stable question id in `decisions.open`, and answering it is reflected in the plan id. | code | test_adopt_project.py `CandidateAnswerTest.test_answering_reaches_ready_and_changes_the_plan_id`, `CandidateQuestionTest`; test_adopt_apply.py `AnsweredCandidateApplyTest` | in final verification | — | — | met |
| AC3 | `just agent-workflow-tests` passes. | code | `just agent-workflow-tests` | in final verification | — | — | met |
