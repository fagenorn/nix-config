A reviewer found defects in the conflict resolution of merge commit {{merge-of.merge_commit}} of the branch in the worktree {{prepare.worktree_path}} (git -C <worktree> show --cc {{merge-of.merge_commit}}); the branch head is {{merge-of.head}}, and when that is not the merge commit the resolution carries commits on top of it (git -C <worktree> diff {{merge-of.merge_commit}}..{{merge-of.head}}). The findings are: {{merge-review.findings}}

Work only in the worktree: run git as git -C <worktree> and name every file by its absolute path. Never push, open or merge a pull request, run a land lock or claim command, run git stash, run sed -i or run a destructive git command.

Fix each real defect on top of the head with a regression test, then commit. Never redo or rewrite the merge. If a finding is wrong, commit nothing for it and say so with evidence in notes; when nothing has to change, commit nothing and return commit equal to start_head.

The program pushes this fix to the open pull request next, so before committing run in full every test file among or covering the files you changed (never a single test class), and return tests: each command you ran. A fix report with no test command is not pushed. Run no full suite and no declared verification: it runs once later.

Before committing, read git status in the worktree you commit in and stage by path only the files the fix itself changed or created; never run git add -A, git commit -a or git add on a directory (the dot included); a lock file, a generated file or an untracked file the fix did not need is left unstaged and named in notes.

Return status, notes, tests, start_head (git -C <worktree> rev-parse HEAD before you change anything) and commit (the full sha of that HEAD after your last commit). Both are full shas.
