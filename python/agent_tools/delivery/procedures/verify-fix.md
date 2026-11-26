The verification of issue {{run.issue}} failed in the worktree {{preflight.worktree_path}} on branch {{preflight.branch}} (origin/{{preflight.integration_branch}} is the base). Work only there: run git as git -C <worktree> and name every file by its absolute path. Never push, open a pull request, run git stash, run sed -i or run a destructive git command.

The problems are:
{{round.problems}}

A problem with reran true failed again on its one rerun at the same head, so it is not flaky. Find the cause in the branch's diff (git -C {{preflight.worktree_path}} diff origin/{{preflight.integration_branch}}...HEAD), make the smallest fix and commit it. Never weaken, skip or delete a test or a check to make it pass.

Edit a file outside the branch's diff only when you have established its cause: this branch's change or this delivery's environment. List each such file in outside_diff with file and why.

When you cannot establish a cause (the test fails without this branch's change, or, unless reran is true, it is flaky), change and commit nothing and return status blocked with unrelated set to the test and the evidence. Establish that by reading or running, never by checking out another commit.

Before returning, run in full every test file among or covering the files you changed (never a single test class) and the declared cheap guards {{round.guards}} (run each argv with its cwd as the working directory). Return tests: each command you ran and its result.

Before committing, read git status in the worktree you commit in and stage by path only the files the fix itself changed or created; never run git add -A, git commit -a or git add on a directory (the dot included); a lock file, a generated file or an untracked file the fix did not need is left unstaged and named in notes.

Return status (done or blocked), notes, tests, outside_diff (an empty list when no file applies), unrelated (test and evidence both empty strings when it does not apply), start_head (git -C <worktree> rev-parse HEAD before you change anything) and commit (the full sha of that HEAD after your last commit). Both are full shas.
