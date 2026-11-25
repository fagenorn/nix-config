Review the conflict resolution of the branch in the worktree {{prepare.worktree_path}} (origin/{{prepare.integration_branch}} is the base). It is merge commit {{merge-of.merge_commit}}: read it with git -C <worktree> show --cc {{merge-of.merge_commit}}. Work only there with read-only git, as git -C <worktree>, naming every file by its absolute path. Edit nothing.

Report Important or Critical defects only: a dropped change from either side, a broken merge of intent, a resolved file whose tests were not run, a leftover conflict marker.

The branch head is {{merge-of.head}}. When it is not the merge commit, the resolution carries commits on top of its merge: review them too, with git -C <worktree> diff {{merge-of.merge_commit}}..{{merge-of.head}}, above all for a test or check they weaken, skip or delete, and report any conflict marker that git -C <worktree> diff --check {{merge-of.merge_commit}} {{merge-of.head}} shows in them.

Return verdict pass when there is no defect, else findings. Every critical or important finding names a file (path:line) and a concrete failing input. A reply with a critical or important finding that names neither is discarded and this step runs once more.
