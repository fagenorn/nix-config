Your outline of issue {{run.issue}} of {{run.repo}} was refused before any review: its structure did not hold. Return the whole corrected outline.
The rules the outline failed:
- Every slice has an integer n, a non-empty proving test and a one-line assertion.
- The slices are numbered 1, 2, 3 and so on in build order, each number once, with no gap.
- Every criterion has a text id and names a slice n that the outline has.
- The criteria carry each id AC<i> of the issue exactly once (i its position in the issue's acceptance criteria, from 1): no criterion of the issue left out, no criterion repeated, no id the issue does not have, and no criterion at all when the issue has no acceptance criteria. A criterion that only restates a declared verification command passing is still one of them.
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
