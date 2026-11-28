Your outline of issue {{run.issue}} of {{run.repo}} was design-reviewed and the review found defects. Revise it and return the whole revised outline: the same members as before (status planned, approach, rejected, slices, criteria, risks, questions), every slice with its proving test and assertion and every acceptance criterion of the issue mapped to a slice.
Worktree: {{plan-preflight.worktree_path}} (branch {{plan-preflight.branch}}, integration branch {{plan-preflight.integration_branch}}). Your current directory is the project root, not that worktree: read the files of the issue branch by their absolute path under {{plan-preflight.worktree_path}}. Use your shell only to read, never a command that changes the tree, the index, HEAD or a branch, and write no file: your reply is the whole outline.
The outline as the reviewer read it:
{{outline-read.text}}
The findings:
{{design-review.findings}}
Fix each finding in the outline. When a defect needs a decision only the owner can make, return status blocked with each question and its options in questions, and empty strings or lists for the other members.
The issue, with its comments:
{{plan-preflight.issue_text}}
Setup facts: {{start.details}}
Merged pull requests that reference the issue, each {number, closes}: {{start.merged_refs}}
The routed set of the files the issue names: {{plan-preflight.routed}} {{plan-preflight.route_detail}}
