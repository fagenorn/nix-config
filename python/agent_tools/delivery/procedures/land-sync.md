Issue {{run.issue}} is landing from branch {{prepare.branch}}, whose head is {{expect.head}}, and the branch is behind origin/{{prepare.integration_branch}}. The landing lock is held. Work only in the worktree {{prepare.worktree_path}}: run git as git -C <worktree> and name every file by its absolute path. Never push, open or merge a pull request, run a land lock or claim command, run git stash, run sed -i or run a destructive git command.

Fetch origin (git -C <worktree> fetch origin), then merge origin/{{prepare.integration_branch}} into the branch in the worktree (git -C <worktree> merge origin/{{prepare.integration_branch}}).

If the merge conflicts, do not resolve it: run git merge --abort inside the worktree, confirm no merge is left in progress (git -C <worktree> rev-parse -q --verify MERGE_HEAD fails), and return status conflicted with the conflicting files in notes and an empty tests list; a later step resolves it.

For a clean merge, run only the tests covering the branch files the merge touched (the paths that git -C <worktree> diff --no-renames --name-only {{expect.head}} HEAD prints and that the branch itself changed, which git -C <worktree> diff --no-renames --name-only origin/{{prepare.integration_branch}}...HEAD prints); when the merge changed none of the branch's files, run no test. Do not run the full suite or the declared verification: it runs once later. Return status done and tests (each test command you ran).

Return status blocked with the reason in notes when no merge can be made. Return notes always. Do not push.
