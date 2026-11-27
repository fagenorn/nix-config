Issue {{run.issue}} was merged as {{read.merge_commit}} with criteria still open. Draft the verification checks that hold it. Change nothing and run nothing but read-only git.
The diff to ground them in is the merge commit: git show {{read.merge_commit}}, and git diff {{read.merge_commit}}^1 {{read.merge_commit}}.
The open criteria, each with its id, kind and text: {{hold-facts.open}}
The verification command ids a check may run unattended: {{hold-facts.verification}}
The criterion ids a look approval already answered, which need no check: {{hold-look.answered}}

For each open criterion not in that answered list, write exactly one check of the verify block grammar of ~/.agents/standards/acceptance-planning.md (its "Verify block fields"), with ac set to the criterion id.
- A code or evidence criterion gets kind evidence and never an ask or act run. When the check runs a command unattended, the command is one of the verification ids above; otherwise it is a committed script or a built-in probe.
- A human criterion gets kind human, a run with an ask or act, and a reason.
Return each check as its JSON text in the check member of one written entry, with ac its criterion id. Answer verdict drafted when every such criterion has a check.
If a criterion cannot get a check, answer verdict blocked, with written empty or partial and detail saying which criterion and why.
