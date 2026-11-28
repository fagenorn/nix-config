You deliver one slice of issue {{run.issue}} of {{run.repo}}. Build only this slice (its n, change, files, proving test and assertion): {{slice.slice}}. Test first with that slice's proving test, and nothing of another slice.

The approved outline of the whole issue (the outline decides the scope; a later slice is built by a later session):
{{slice.outline}}

The claim is held and the worktree {{slice.worktree_path}} exists on branch {{slice.branch}}, made from origin/{{slice.integration_branch}}. Work only there: run git as git -C <worktree> and name every file by its absolute path. Your session runs in that worktree. For example:

```
git -C {{slice.worktree_path}} status --short
git -C {{slice.worktree_path}} log --oneline -3
git -C {{slice.worktree_path}} diff origin/{{slice.integration_branch}}...HEAD
```

Never push, open a pull request, run git stash, run sed -i or run a destructive git command.

Setup facts (what still applies, where, and what already exists, from the setup's check): {{slice.details}}
Merged pull requests that reference the issue, each {number, closes}: {{slice.merged_refs}}
The routed set of the files the issue names (the standards shards with their rule ids, the hint, the records to read and the context-map index; null when nothing was routed, the reason after it): {{slice.routed}} {{slice.route_detail}}
The files the planner read while planning, as leads and not a list you must read: {{slice.reads}}
The diff so far, the slices built before this one (git diff origin/{{slice.integration_branch}}...HEAD):
{{slice.diff}}

Test first:
- Write the slice's proving test, run it and see it fail, then implement the slice.
- Run the targeted tests, and any changed script or recipe, once.
- Remove the code that satisfies the slice and run only its filtered tests (an incremental build, never a clean one): they must fail, and a run of zero tests shows nothing. Restore the code and commit.
- Before committing, read git status in the worktree you commit in and stage by path only the files the slice itself changed or created; never run git add -A, git commit -a or git add on a directory (the dot included); a lock file, a generated file or an untracked file the slice did not need is left unstaged and named in notes.
- An earlier attempt may have left commits or edits in the worktree (git -C <worktree> status, diff and log): inspect them, keep what matches, finish or redo the rest. start_head is the head before this slice's first commit.
- Do not write the declared verification commands as an acceptance criterion: the verify step gates on them.
- Run only the tests covering the files you changed, not the full suite or the declared verification (it runs once later).
- When the slice cannot be built as outlined, change nothing you cannot finish, return status blocked and the reason in notes.

Return:
- status and notes.
- start_head (git -C <worktree> rev-parse HEAD before you change anything) and commit (the full sha of that HEAD after your last commit); commit equals start_head when you committed nothing. Both are full shas.
- acceptance: every criterion of the issue (the outline lists them), each with id, text, kind and result (its tests and what the removal check showed). For a criterion a later slice satisfies, the result says it is not built yet.
- sensitive: true when the whole diff so far (the earlier slices and this one) touches authentication or authorization, permission or command guards, secrets or credentials, CI/CD or deploy config, or data migrations.
- ineligible: false. tests: the tests you ran.
