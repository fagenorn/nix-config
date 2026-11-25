lane: direct.
Review the delivery diff for issue {{run.issue}} against its acceptance criteria {{implement.acceptance}}. Read it with read-only git in the current directory, which shares branch {{preflight.branch}}: git diff origin/{{preflight.integration_branch}}...{{preflight.branch}}. The changed files are under {{preflight.worktree_path}}.

Report Important or Critical correctness defects and unmet code criteria only, each with a concrete failing input and a path:line file. Return acceptance with one entry per criterion id: met, and evidence, which is the test name and file:line that asserts the criterion, or the command that shows it. A code criterion that is not met, or has no evidence, is an Important finding; criteria of other kinds are graded (give what you observed), never findings. Set escalate true when the diff touches authentication or authorization, permission or command guards, secrets or credentials, CI/CD or deploy config, or data migrations, else false. Return verdict pass when there is no finding, else findings. Do not edit anything.

Give each finding a kind, one of edge-or-failure-path, weak-test, missing-test, contract-mismatch, stale-docs, security, concurrency, plan-step-not-executable or other, and a rule only when the finding breaches a standard: that standard's id, as B12; leave rule out otherwise.

A reply with a critical or important finding that names neither a file nor a failing input is discarded and this step runs once more.
