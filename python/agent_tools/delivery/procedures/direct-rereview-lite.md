Re-review only the previously reported findings against the fix: git diff {{lite-fix.start_head}}..{{lite-fix.commit}} (read-only git in the current directory, which shares the branch). The implementer's notes: {{lite-fix.notes}}

The previously reported findings come from three sources: the review's findings {{lite-review.findings}}, the independent review's findings {{lite-independent.findings}}, and the code criteria of {{implement.acceptance}} that the review's grading {{lite-review.acceptance}} did not show met with evidence.

Report any finding still unresolved and any new Important or Critical defect the fix introduced, each with a concrete failing input and a path:line file. Return verdict pass when there is none, else findings. These findings may be acceptance criteria the review did not see shown met, and the notes then carry the evidence produced for each (the command, its exit status and last lines; the diff is empty when nothing had to change): a criterion that evidence shows met is resolved, and one without it, or whose command failed, is still unresolved. Do not edit anything.

A reply with a critical or important finding that names neither a file nor a failing input is discarded and this step runs once more.
