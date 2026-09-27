# Task 6: ship-issue's post-selection sync route, then the final gate

Spec §6–§7 and T11, per D9, D10, D11, D12, D17, D18, D22, D23. The route is
described once, in `CI-MERGE.md` (conditional in the ship-owner profile).
`SKILL.md` gains four one-sentence pointers: the Delivery loop's steps 3 and 6,
Remainder mode, and Phase 6's divergence rule. The route uses Task 5's
`--kind sync-selection` and Task 4's chain. It adds no review rubric and no
dispatch marker.

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/CI-MERGE.md`
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/instruction-load.json`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: `build-delivery --kind sync-selection` and its input keys
  `contract, prior_selection, head, tree, parents, review_ref, test_ref` (Task 5).
  The chain semantics: the tip is the current selection, a sync fold re-opens
  `publish_branch` and `open_pr` until the tip's observations fold, and a merge
  is final for its chain (Task 4).
- Produces: nothing later tasks read.

**Invariants:**
- The route is written only in `CI-MERGE.md`. `SKILL.md` names
  `` `## Post-selection sync` `` exactly four times, once per pointer.
- The existing Phase 6 fragments stay verbatim: "stop before the CI wait", "no
  further forge write", "keep the worktree", "`stopped` ship summary", "both
  SHAs" and "unreviewed commits". So do every existing Delivery loop and
  Remainder mode anchor.
- No new text contains `Agent(`. Every new inline command is one plain command.
- CI-MERGE.md never spells `build-delivery`. Step 6 makes the Delivery loop's
  builder call by its kind, so the caller list that
  `test_build_delivery_callers_name_the_sanctioned_resolution_exception` pins
  stays exactly its four files.
- Only breached ceilings move, each to its measured hot bytes, with #192 named
  in the note (D23). ship-owner is expected to be the only breach.

- [ ] **Step 1: Write the failing pin**

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, add the
constant after `SHIP_ISSUE_REVIEW = ...`:

```python
SHIP_ISSUE_CI_MERGE = REPO_ROOT / "home/common/agent-skills/skills/ship-issue/CI-MERGE.md"
```

In `WorkflowSkillContractsTest.setUpClass`, after `cls.ship_review = ...`, add
`cls.ship_ci_merge = SHIP_ISSUE_CI_MERGE.read_text(encoding="utf-8")`. Then add
this test after `test_ship_issue_writer_rule_delivery_loop_and_remainder_mode`:

```python
    def test_ship_issue_post_selection_sync_route(self):
        """#192 T11: CI-MERGE.md owns the route; SKILL.md points to it from four places."""
        route = normalized(self.ship_ci_merge.split("## Post-selection sync", 1)[1])
        self.assert_ordered(route, "**sync selection**", "whoever holds the merge gate",
            "**current selection**", "`implementation_delivered`", "*sync run*",
            "`git merge-base --is-ancestor", "one sync selection, oldest first",
            "`gh pr view <pr-num> --json state,headRefOid,mergeable`",
            "`mergeable: CONFLICTING`", "merely behind", "resume at step 3",
            "not an authority denial", "no `authority-observation`")
        self.assert_ordered(route, "**Sync.**", "[`SYNC.md`](./SYNC.md)", "**Verify.**",
            "Phase 2 verification", "**Review.**", "`git show --cc", "merge-delta reviewer",
            "`merge-delta-empty`", "`merge-delta-clean`", "**Push.**", "`check-launch`",
            "`git push`", "**Wait for CI.**", "Phase 6's CI wait", "**Select.**",
            "--kind sync-selection", "`git rev-list --parents -n 1", "`test_ref` `checks`",
            "`branch_published` and `pr_opened`", "`--kind scope` for `merge_pr`",
            "**Merge.**")
        self.assert_ordered(route, "**A merge that already landed.**",
            "without a push or a CI wait", "`pr_merged` observation", "**Stops.**",
            "Should-fix", "genuinely-blocked stop")
        self.assertNotIn("Agent(", self.ship_ci_merge)
        self.assertEqual(self.ship_issue.count("`## Post-selection sync`"), 4)
        loop = normalized(self.section(self.ship_issue, "## Delivery loop", "## Remainder mode"))
        self.assert_ordered(loop, "**The pre-merge selection gate.**",
            "`## Post-selection sync`", "**Denials.**", "cannot merge into its base",
            "no authority observation", "`## Post-selection sync`",
            "A guard, host or provider denial")
        remainder = normalized(self.ship_issue.split("## Remainder mode", 1)[1])
        self.assert_ordered(remainder, "start at the merge gate", "`## Post-selection sync`",
                            "already landed")
        phase_six = normalized(self.section(self.ship_issue, "## Phase 6 — Wait for CI",
                                            "## Phase 7 — Merge"))
        self.assert_ordered(phase_six, "unreviewed commits", "`## Post-selection sync`",
                            "genuinely-blocked stop")
```

- [ ] **Step 2: Run the pin and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k post_selection_sync_route`
Expected: `FAILED (errors=1)`, an `IndexError`, because CI-MERGE.md has no
`## Post-selection sync` yet.

- [ ] **Step 3: Write the route and the pointers**

In `CI-MERGE.md`, replace the intro's second line,
`and merge quirks behind SKILL.md's Phase 6/7 rules.`, with the two lines
`merge quirks and the post-selection sync route behind SKILL.md's Phase 6/7` and
`rules.`. Then append this section at the end of the file, after
`## Merge quirks (Phase 7)`, exactly as written:

````markdown
## Post-selection sync

Under lifecycle identity a selection is immutable, so a PR that needs the
integration branch after selection gets a **sync selection** that extends it and
never replaces it. The route belongs to whoever holds the merge gate: the ship
owner under implementation custody, or a remainder owner. The **current
selection** is the newest link of the ledger's selection chain. From the first
sync on, every later step's "selection" is the current selection, including the
`implementation_delivered` observation that `## Delivery loop` step 7 builds.

**Sync run.** After `git fetch origin`, a PR head is a *sync run* from the
current selection when its first-parent walk back to that selection's head
passes only two-parent merge commits, and for each one
`git merge-base --is-ancestor <second-parent> origin/<integration>` confirms its
second parent. Each merge of a sync run becomes one sync selection, oldest
first, and each is reviewed on its own.

**Trigger.** Before the merge, read
`gh pr view <pr-num> --json state,headRefOid,mergeable`. The route runs when:

- the PR is open with `mergeable: CONFLICTING`, or `gh pr merge` was refused
  because the head conflicts with its base or is behind a base that requires an
  up-to-date head. A head merely behind a base with no such rule merges as it
  is;
- the PR is open and its `headRefOid` is not the current selection's head but a
  sync run from it, which is a crash after the push: resume at step 3;
- the PR has merged at a head that is a sync run from the current selection:
  see **A merge that already landed**.

A merge the provider refuses because the PR cannot merge into its base is a
stale head, not an authority denial: record no `authority-observation` for it.

**Steps.**

1. **Sync.** Make one merge of `origin/<integration>` into the current
   selection's head under [`SYNC.md`](./SYNC.md), so its first parent is that
   head, and fold its conflict resolutions and sweeps into that merge commit.
2. **Verify.** Run the Phase 2 verification commands.
3. **Review.** Run REVIEW.md's merge-delta check over that commit's combined
   diff, `git show --cc <merge-sha>`, through SKILL.md's merge-delta reviewer.
   Apply findings by amending the unpushed merge commit, which keeps both
   parents. The link's `review_ref` is `merge-delta-empty` for an empty delta,
   and `merge-delta-clean` once every Blocking and Should-fix finding is applied
   and re-reviewed. Retain Minor and Discussion findings under REVIEW.md's
   durable-detail rules.
4. **Push.** Run `check-launch` (SKILL.md's `## Launch guard`), then `git push`.
5. **Wait for CI.** Run Phase 6's CI wait, with the reviewed head re-fixed to
   the pushed head.
6. **Select.** For each merge of the sync run, oldest first, make
   `## Delivery loop`'s builder call with `--kind sync-selection`, from the
   installed `contract`, the current selection as `prior_selection`, the
   merge's `head`, its `tree` (`git rev-parse <merge-sha>^{tree}`), its
   `parents` (`git rev-list --parents -n 1 <merge-sha>`, first parent first),
   the `review_ref` from step 3, and `test_ref` `checks`. Each result is the
   next one's `prior_selection`. Build each link's `selected_output` observation,
   then `branch_published` and `pr_opened` (the same PR) at the newest head, and
   checkpoint them all with the `--kind scope` for `merge_pr`.
7. **Merge.** Continue with `## Delivery loop`'s merge cycle.

Steps 1–5 precede the sync selection. So, like pre-selection publication, they
run under the native guard, repository policy and the `check-launch` fence, with
no checkpoint. After a crash past step 4, resume at step 3 for the pushed sync
run, and step 5 then waits for CI. If the base moves again, the next sync
extends the chain.

**A merge that already landed.** When the PR merged at a sync run from the
current selection, run step 3 for each of its merges, then step 6 without a push
or a CI wait. Add the `pr_merged` observation at that head to the same
checkpoint, and give it the next pending stage's `--kind scope` instead of
`merge_pr`'s. Then continue with the cleanup cycles.

**Stops.** A Blocking or Should-fix finding on a merge that is already pushed or
already landed cannot be amended, so it is a stop. Everything outside the route
stays Phase 6's genuinely-blocked stop, and a human decides. That covers a PR
head that is not a sync run from the current selection (a non-merge commit, a
first parent off the chain, or an unconfirmed integration parent), and red CI
that needs a fix commit.
````

In `SKILL.md`, make these four edits, and nothing else:

1. Phase 6: replace
   `resolve it by re-pushing, resetting, re-reviewing or merging. In `--auto` this`
   with the two lines
   `resolve it by re-pushing, resetting, re-reviewing or merging, except for a head`
   and ``that CI-MERGE.md's `## Post-selection sync` admits. In `--auto` this``.
2. `## Delivery loop` step 3: directly after its closing `checkpoint write.`,
   append this sentence, wrapped at the step's three-space indent:
   ``Before the merge, run the trigger check of CI-MERGE.md's `## Post-selection sync`: a later sync of the integration branch extends this selection with a sync selection and never replaces it.``
3. `## Delivery loop` step 6: replace its first line,
   `6. **Denials.** A guard, host or provider denial of an effect is checkpointed`,
   with these four lines:

```text
6. **Denials.** A merge the provider refuses because the PR cannot merge into
   its base is not a denial: record no authority observation for it, and take
   CI-MERGE.md's `## Post-selection sync`. A guard, host or provider denial of
   an effect is checkpointed
```

4. `## Remainder mode`: replace
   `wait and Phase 7's gate and fence still bind. Otherwise start at the first`
   with these three lines:

```text
wait and Phase 7's gate and fence still bind, and so does CI-MERGE.md's
`## Post-selection sync`, which also folds a merge that already landed at a
sync run. Otherwise start at the first
```

Keep each inline code span on one line.

- [ ] **Step 4: Re-measure the ceilings**

Run: `PYTHONPATH=python python3 -c 'from pathlib import Path; from agent_tools import instruction_load as il; r = il.tree_reader(Path(".")); m = il.load_model(r(il.MODEL_PATH)); print("\n".join(il.over_ceiling(m, il.measure(m, r))) or "no breach")'`
Expected: exactly two lines,
`profile ship-owner on claude: hot <N> bytes exceed ceiling 53916 (...)` and the
same for `codex`. `<N>` was 54480 in the planning probe.

In `instruction-load.json`, set the `ship-owner` profile's `ceiling_bytes`
`claude` and `codex` to that measured `<N>`. Append this sentence to its
`note`: ` Ceiling raised for #192: ship-issue's Delivery loop, Remainder mode and
Phase 6 point to CI-MERGE.md's post-selection sync route (#155 D10).`. If any
other profile breaches, raise only it, the same way, and name its grown
document.

Run the same command again.
Expected: `no breach`.

- [ ] **Step 5: Verify the task**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_agent_model_matrix.py`
Expected: `OK` (the existing skips stay skips), with no `FAIL:`/`ERROR:`.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/skills/ship-issue/CI-MERGE.md home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(ship-issue): select a post-review sync instead of stranding the merge (#192)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: The final gate**

Run: `if git diff --quiet 6ab576e -- home/common/agent-skills/scripts/artifact_budget.py; then echo artifact-budget-untouched; else exit 1; fi`
Expected: `artifact-budget-untouched`, since #191 owns that file.

Run: `just agent-workflow-tests > "${TMPDIR:-/tmp}/issue-192-suite.log" 2>&1; echo "exit=$?"; grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED' "${TMPDIR:-/tmp}/issue-192-suite.log"`
Expected: `exit=0`, then `Ran 1383 tests` (the base's 1362 plus this plan's 21)
and `OK (skipped=3)`, with no `FAIL:`/`ERROR:` line.

Run: `just build > "${TMPDIR:-/tmp}/issue-192-build.log" 2>&1; echo "exit=$?"; tail -n 5 "${TMPDIR:-/tmp}/issue-192-build.log"`
Expected: `exit=0`. On a non-zero exit, read the log's `error:` lines, fix the
cause, and re-run both gate commands.
