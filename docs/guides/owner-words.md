# Words the owner does not know

Each internal word the console or a manager may use, with its one-line gloss in everyday words. Use the gloss the first time the word appears in anything the owner reads, or use the gloss instead of the word ([the plain-words rule](./write-for-the-owner.md)). A later check reads the table: the first cell of each row is the word, the second is its gloss, and a row may not leave its gloss empty.

| Word | In everyday words |
|---|---|
| land lock | A turn-taking token: only one change at a time may be merged into the main branch, so a change waits until it holds the lock. |
| slice | One small piece of a larger job, made so that it can be built, checked and finished on its own. |
| held | Finished and merged, but not counted as done until a check afterwards shows it works for real. |
| verify | A check that a change does what it was meant to do. One kind runs before the change is merged, when it has not shipped yet. Another kind runs after the change is live, on a schedule, and only for a change kept open until real use proves it works; it may take several passes. Say which kind is meant. |
| brief version | One numbered draft of the plan the manager writes for the owner, or the colleague who started the sprint, to approve; a new version replaces the last when the owner asks for changes. |
| guard | A safety check that refuses a risky command before it runs, such as pushing code or merging a change. |
| rerun | Run a failed automatic check again, in case it failed for a passing reason. |
| claim | A note that says one sprint is working on certain files. It does not lock them: two sprints with overlapping claims both keep working, and a separate rule, not the claim, decides which one goes first. |
| look | Your own look at how something appears on screen, before it is merged. |
| live fault | A fault the manager has found in the running system that real users are meeting now. |
| CI | The automatic checks that GitHub runs on every proposed change before it can be merged. |
| pull request | A proposed change, held on GitHub for checking and review before it joins the main code. |
