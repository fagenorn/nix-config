# Words not to write for the owner

This table lists internal words that no status line, card, question or notice the owner reads may use, each with the few everyday words to write instead. The replacements are phrases that fit in a sentence, not definitions: rewrite the sentence with them, and never explain the internal word instead ([the plain-words rule](./write-for-the-owner.md)). The list is only a check's input. The console keeps a copy in `python/agent_tools/console/sprint.py`, with the forms each row finds, and a test fails when the first two cells of the two differ.

Words that are also ordinary English are never flagged bare. This covers main, head, look, held, land, claim, issue, profile, guard, brief, queued and activate. They are flagged only in their internal form: on main, the head, look card, held issue, landing a change, land lock, a claim on files, issue plus a number, brief version, activation of the host.

| Do not write | Write instead |
|---|---|
| land lock, merge lock | its turn to merge |
| pull request, PR | the proposed change |
| rerun | ran the failed check again |
| CI | the automatic checks |
| held issue | merged, waiting for proof it works in real use |
| verify, verification | testing the change (before it goes in); checking it works in real use (after) |
| landed, landing (a change) | went in, is going in |
| slice | step |
| brief version | the new version of the plan |
| the guard, a guard refusal | the safety check |
| a claim on files | a note of the files it is working on |
| look card | your look at how it appears |
| live fault | a problem users are hitting now |
| commit, sha, the head | the latest version of the change |
| on main, the branch | the main version, the change's own copy |
| issue plus a number | the task, named by its title |
| milestone | the sprint's task list |
| Conformance, lint | the house-rule checks |
| fix wave | a round of fixes |
| activation of the host | switching this computer to the new version |
| AC plus a number | say what must be true |
| stage names used as nouns (final-review, verify-fix and the like) | say what is happening |
| ready mode | built and tested, not yet proposed |
| sync (with main) | brought up to date with the main version |
| flaky | fails now and then for no real reason |
| tokens | say the cost in dollars, or leave it out |
| worktree, engine, workflow, delivery program | leave it out; say what is being done |
