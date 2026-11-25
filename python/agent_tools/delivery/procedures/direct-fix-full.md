Fix the review findings of issue {{run.issue}} in the worktree {{preflight.worktree_path}} on branch {{preflight.branch}} (origin/{{preflight.integration_branch}} is the base). Work only there: run git as git -C <worktree> and name every file by its absolute path. Never push, open a pull request, run git stash, run sed -i or run a destructive git command.

The findings to act on are:
- every critical or important finding of the review: {{full-review.findings}}
- every critical or important finding of the independent review: {{full-independent.findings}}
- every code criterion of {{implement.acceptance}} that the review's grading does not show met with evidence: {{full-review.acceptance}}

Fix each real defect with a regression test and commit it in the worktree. A finding that is wrong is declined, not changed in code: list it in declines with finding, its name (full-review:2 is the second finding of the review, full-independent:1 the first of the independent review), and reason, the evidence that it is wrong. A criterion that only lacks evidence: produce the evidence it asks for by running the command it names (or the test that asserts it, written first when none exists) in the worktree, and report in notes, per criterion id, the command, its exit status and its last lines; the focused-tests-only rule does not apply to a command a criterion names. If it fails, fix the cause with a regression test and commit; when nothing has to change, commit nothing and return commit equal to start_head.

Before committing, read git status in the worktree you commit in and stage by path only the files the fix itself changed or created; never run git add -A, git commit -a or git add on a directory (the dot included); a lock file, a generated file or an untracked file the fix did not need is left unstaged and named in notes.
Run only the tests covering the files you changed, not the full suite or the declared verification (it runs once later).

Return status, notes, declines (an empty list when you declined nothing), tests (the tests you ran), start_head (git -C <worktree> rev-parse HEAD before you change anything) and commit (the full sha of that HEAD after your last commit). Both are full shas.
