Review the fix of the failed verification in the worktree {{preflight.worktree_path}}: the commits git diff {{round.head}}..{{preflight.branch}} shows, against the problems the verification reported: {{round.problems}} The implementer's notes: {{fix.notes}}

Read it with read-only git in the current directory, which shares the worktree's branches and objects, and read each file by its absolute path under {{preflight.worktree_path}}. Report only Important or Critical defects, above all a test or check the fix weakened, skipped or deleted to make a check pass, and a fix with no regression test that fails without it, each with a concrete failing input and a path:line file. Report no style point and no defect outside the fix.

Each file of {{fix.outside_diff}} was edited outside the branch's diff for its stated cause. A cause the code or the failure does not bear out is an Important defect.

The prefilter says whether the range is whitespace-only: {{ws-check.whitespace_only}} over the paths {{ws-check.changed_paths}}. When it is true, judge whether each whitespace change is insignificant: outside every string, template, character and regex literal, heredoc and raw block, and in no construct where whitespace changes behaviour or output. Return whitespace_insignificant true only when you read every hunk and that holds, with whitespace_evidence naming each changed path and why. Otherwise return false with the evidence.

Return verdict pass when there is no defect, else findings. Edit nothing.

Give each finding a kind, one of edge-or-failure-path, weak-test, missing-test, contract-mismatch, stale-docs, security, concurrency, plan-step-not-executable or other, and a rule only when the finding breaches a standard: that standard's id, as B12; leave rule out otherwise.

A reply with a finding that names neither a file nor a failing input is discarded and this step runs once more.
