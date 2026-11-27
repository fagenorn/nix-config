You deliver issue {{run.issue}} of {{run.repo}} in the direct lane. The issue, with its comments:
{{preflight.issue_text}}

The claim is held and the worktree {{preflight.worktree_path}} exists on branch {{preflight.branch}}, made from origin/{{preflight.integration_branch}}. Work only there: run git as git -C <worktree> and name every file by its absolute path. Your session runs in that worktree. For example:

```
git -C {{preflight.worktree_path}} status --short
git -C {{preflight.worktree_path}} log --oneline -3
git -C {{preflight.worktree_path}} diff
```

Never push, open a pull request, run git stash, run sed -i or run a destructive git command.

Eligibility first: the direct lane takes an issue with concrete, checkable criteria, a few-file fix and no open design decision or preference. If the issue fails that, change nothing and return status blocked, ineligible true and the reason in notes.

Otherwise, test first:
- Write the criteria's tests, run them and see them fail, then implement.
- Run the targeted tests, and any changed script or recipe, once.
- Once per criterion, remove the code that satisfies it and run only its filtered tests (an incremental build, never a clean one): they must fail, and a run of zero tests shows nothing. Restore the code and commit.
- Before committing, read git status in the worktree you commit in and stage by path only the files the fix itself changed or created; never run git add -A, git commit -a or git add on a directory (the dot included); a lock file, a generated file or an untracked file the fix did not need is left unstaged and named in notes.
- An earlier attempt may have left commits or edits in the worktree (git -C <worktree> status, diff and log): inspect them, keep what matches, finish or redo the rest. start_head is the head before this task's first commit.
- Do not write the declared verification commands as an acceptance criterion: the verify step gates on them.
- Run only the tests covering the files you changed, not the full suite or the declared verification (it runs once later).

Return:
- status and notes.
- start_head (git -C <worktree> rev-parse HEAD before you change anything) and commit (the full sha of that HEAD after your last commit); commit equals start_head when you committed nothing. Both are full shas.
- acceptance: the issue's criteria, each with id, text, kind (kind code if a test or command in this repo can show it, evidence if it needs a deploy, an activation or observation over time, human if only the user can judge, note if a decision makes a post-deploy reading the orchestrator's own observation or not a hold) and result (its tests and what the removal check showed).
- sensitive: true when the diff touches authentication or authorization, permission or command guards, secrets or credentials, CI/CD or deploy config, or data migrations.
- ineligible and tests (the tests you ran).
