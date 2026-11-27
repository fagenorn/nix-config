Re-review the conflict-resolution findings of merge commit {{merge-of.merge_commit}} in the worktree {{prepare.worktree_path}} against the fix (git -C <worktree> diff {{merge-fix.start_head}}..{{merge-fix.commit}}) made on top of it, or against the rebuttal when the fix made no new commit. Work only there with read-only git, as git -C <worktree>, naming every file by its absolute path. The findings: {{merge-review.findings}}. The implementer's notes: {{merge-fix.notes}}
The implementer's declines: {{merge-fix.declines}}
Each decline names a finding by its step and its 1-based place in that step's list (merge-review:2 is the second finding of the review) and gives the reason no code changed for it. A declined finding whose reason holds is resolved; one whose reason does not hold is still unresolved.

When there is no new commit, check each rebuttal against the code yourself (git -C <worktree> show --cc {{merge-of.merge_commit}}): a finding the evidence does not refute is still unresolved.

Report any finding still unresolved and any new Important or Critical defect, each with a concrete failing input and a path:line file. A finding that is still unresolved names in restates the earlier finding it is, as merge-review:2; a new defect leaves restates out. Return verdict pass when there is none, else findings. Do not edit anything.

Give each finding a kind, one of edge-or-failure-path, weak-test, missing-test, contract-mismatch, stale-docs, security, concurrency, plan-step-not-executable or other, and a rule only when the finding breaches a standard: that standard's id, as B12; leave rule out otherwise.

A reply with a critical or important finding that names neither a file nor a failing input is discarded and this step runs once more.
