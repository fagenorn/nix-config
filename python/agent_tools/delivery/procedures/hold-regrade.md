lane: direct.
Issue {{run.issue}} was merged as {{read.merge_commit}} (pull request {{read.pr}}), which passed its required checks at landing. Regrade its code criteria once against that merge commit. Change nothing.
The criteria, each with its id, kind and text: {{hold-facts.criteria}}

Read the merge commit with read-only git only: git show {{read.merge_commit}}, git diff '{{read.merge_commit}}^1' {{read.merge_commit}}, and the files at that commit.
Grade each code criterion once: met true when the merge commit's code satisfies it, with evidence naming the test or file:line, else met false with evidence saying what is missing. A criterion of another kind is not graded, and a note never is.
Return acceptance with one entry per code criterion, code_unmet with the ids of the unmet ones, and verdict unmet when any is unmet, else met.
