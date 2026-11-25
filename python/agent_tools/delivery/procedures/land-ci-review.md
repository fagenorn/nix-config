Review the fix of the failed checks {{red.failing}} in the worktree {{prepare.worktree_path}}: the commits git -C <worktree> diff {{ci-fix.start_head}}..{{ci-fix.commit}} shows. Work only there with read-only git, as git -C <worktree>, naming every file by its absolute path. The implementer's notes: {{ci-fix.notes}}

Report a test or check the fix weakened, skipped or deleted to make a check pass, and a fix with no regression test that fails without it, each with a concrete failing input and a path:line file. Report no style point and no defect outside the fix. Return verdict pass when there is none, else findings. Edit nothing.

Give each finding a kind, one of edge-or-failure-path, weak-test, missing-test, contract-mismatch, stale-docs, security, concurrency, plan-step-not-executable or other, and a rule only when the finding breaches a standard: that standard's id, as B12; leave rule out otherwise.

A reply with a finding that names neither a file nor a failing input is discarded and this step runs once more.
