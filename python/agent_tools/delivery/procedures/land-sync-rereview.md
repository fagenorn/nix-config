Re-review the conflict-resolution findings of merge commit {{merge-of.merge_commit}} in the worktree {{prepare.worktree_path}} against the fix (git -C <worktree> diff {{merge-fix.start_head}}..{{merge-fix.commit}}) made on top of it, or against the rebuttal when the fix made no new commit. Work only there with read-only git, as git -C <worktree>, naming every file by its absolute path. The findings: {{merge-review.findings}}. The implementer's notes: {{merge-fix.notes}}

When there is no new commit, check each rebuttal against the code yourself (git -C <worktree> show --cc {{merge-of.merge_commit}}): a finding the evidence does not refute is still unresolved.

Report any finding still unresolved and any new Important or Critical defect, each with a concrete failing input and a path:line file. Return verdict pass when there is none, else findings. Do not edit anything.

A reply with a critical or important finding that names neither a file nor a failing input is discarded and this step runs once more.
