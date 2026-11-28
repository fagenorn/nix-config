Your outline of issue {{run.issue}} of {{run.repo}} was refused before any review: its structure did not hold. Return the whole corrected outline.
The rules the outline failed:
- Every slice has an integer n, a non-empty proving test and a one-line assertion.
- Every criterion names a slice n that the outline has.
- Every acceptance criterion of the issue appears in criteria, with its id AC<i> (i its position in the issue's acceptance criteria, from 1).
Worktree: {{plan-preflight.worktree_path}} (branch {{plan-preflight.branch}}, integration branch {{plan-preflight.integration_branch}}). Your current directory is the project root, not that worktree: read the files of the issue branch by their absolute path under {{plan-preflight.worktree_path}}. Use your shell only to read, never a command that changes the tree, the index, HEAD or a branch, and write no file: your reply is the whole outline.
The refused outline:
- approach: {{outline.approach}}
- rejected: {{outline.rejected}}
- slices: {{outline.slices}}
- criteria: {{outline.criteria}}
- risks: {{outline.risks}}
- questions: {{outline.questions}}
The issue, with its comments:
{{plan-preflight.issue_text}}
Setup facts: {{start.details}}
Merged pull requests that reference the issue, each {number, closes}: {{start.merged_refs}}
The routed set of the files the issue names: {{plan-preflight.routed}} {{plan-preflight.route_detail}}
Return the same members as the first outline (status planned, approach, rejected, slices, criteria, risks, questions), corrected. When the issue needs a decision only the owner can make, return status blocked with each question in questions.
