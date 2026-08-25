# Task 4: Phase-6 tip check against the reviewed `HEAD_SHA`

Discharges AC4 and its share of AC6. Rests on spec row D10 and on the new D17.

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-issue/REVIEW.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Task 3): the `## Launch guard` section, referred to by name, and the
  no-write stop it defines.
- Consumes (unchanged, already in Phase 5): `BASE_SHA=$(git merge-base HEAD
  origin/<integrationBranch>)` and `HEAD_SHA=$(git rev-parse HEAD)`.
- Produces: the phrase "the reviewed `HEAD_SHA`" as the tip check's comparand,
  re-fixed in REVIEW.md step 5.

**Invariants:**
- Phase 6 compares `gh pr view <pr-num> --json headRefOid` to the **reviewed
  `HEAD_SHA`**, never to a freshly-read `git rev-parse HEAD`. Two attempts of one
  issue share one checkout, so live local HEAD is not evidence about what was
  reviewed.
- Divergence is reported as unreviewed commits on the branch and is never
  resolved by re-pushing, resetting, re-reviewing or merging.
- The escalation is the genuinely-blocked stop ship-issue's `--auto` rules
  already define: stop before the CI wait and before the merge, no further forge
  write, no cleanup, keep the worktree and the branch, return a truthful
  `stopped` summary naming both SHAs. Interactive mode surfaces and waits at the
  same point.
- The literal `re-push first` must not survive anywhere in Phase 6.
- The Phase-5 apply/push flow stays five steps; step 5 gains the re-fix, not a
  sixth step.

---

- [ ] **Step 1: Write the failing test**

Add to `WorkflowSkillContractsTest` in
`home/common/agent-skills/tests/test_workflow_skill_contracts.py`, immediately
after `test_ship_issue_guards_every_pre_merge_forge_write`:

```python
    def test_phase_six_tip_check_compares_against_the_reviewed_head(self):
        phase_six = self.section(self.ship_issue, "## Phase 6 — Wait for CI",
                                 "## Phase 7 — Merge")
        collapsed = normalized(phase_six)
        self.assert_ordered(collapsed, "headRefOid", "the reviewed `HEAD_SHA`",
                            "unreviewed commits")
        # The remedy that would make a superseded predecessor push the
        # successor's unreviewed work, and the comparand that hid the problem.
        self.assertNotIn("re-push first", phase_six)
        self.assertNotIn("must equal `git rev-parse HEAD`", collapsed)
        # The escalation is the existing genuinely-blocked stop, spelled out so
        # an implementer cannot read "escalate" as "surface and continue".
        for fragment in ("stop before the CI wait", "no further forge write",
                         "keep the worktree", "`stopped` ship summary",
                         "both SHAs"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, collapsed)
        # The reviewed value is re-fixed where fixes land, not left at Phase 5.
        self.assertIn("re-fix `HEAD_SHA` to that observed `headRefOid`",
                      normalized(self.ship_review))
```

- [ ] **Step 2: Run the test and watch it fail**

```sh
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py -v \
  -k tip_check_compares_against_the_reviewed_head
```
Expected: FAIL — `assert_ordered` reports `missing anchor: 'the reviewed
\`HEAD_SHA\`'`; Phase 6 today reads "must equal `git rev-parse HEAD`; diverged →
the Phase 5 push didn't land, re-push first or CI grades stale code."

- [ ] **Step 3: Replace the tip check**

In `home/common/agent-skills/skills/ship-issue/SKILL.md`, `## Phase 6 — Wait for
CI`, replace the whole one-line paragraph

> Before blocking, verify the tip: `gh pr view <pr-num> --json headRefOid` must
> equal `git rev-parse HEAD`; diverged → the Phase 5 push didn't land, re-push
> first or CI grades stale code.

with (hard-wrapped at ~80 columns):

> Before blocking, verify the tip: `gh pr view <pr-num> --json headRefOid` must
> equal the reviewed `HEAD_SHA` — the value fixed in Phase 5 and re-fixed by
> REVIEW.md's step 5 after each applied fix lands — never `git rev-parse HEAD`
> read afresh. Two attempts of one issue share this checkout, so live local HEAD
> is not evidence about what was reviewed.
>
> Diverged → the PR head carries **unreviewed commits** on the branch. Never
> resolve it by re-pushing, resetting, re-reviewing or merging. In `--auto` this
> is the genuinely-blocked stop: stop before the CI wait and before the merge,
> make no further forge write, run no cleanup, keep the worktree and the branch,
> and return a truthful `stopped` ship summary naming both SHAs — the reviewed
> `HEAD_SHA` and the observed `headRefOid`. In interactive mode, surface and
> wait at the same point. Divergence here is also evidence of a superseded
> launch, which is why `## Launch guard` runs before the merge regardless of how
> this check came out.

The rest of Phase 6 — the docs-only skip, the `timeout 300 gh pr checks` watch,
the exit-code ladder — is unchanged.

- [ ] **Step 4: Re-fix the reviewed value where fixes land**

In `home/common/agent-skills/skills/ship-issue/REVIEW.md`, `## The five-step
apply/push flow`, replace step 5 with:

> 5. Verify the push landed: `gh pr view <pr-num> --json headRefOid` must equal
>    `git rev-parse HEAD`. Diverged → the push didn't take; retry before Phase 6.
>    Once they match, re-fix `HEAD_SHA` to that observed `headRefOid`: the
>    reviewed head advances only when a fix has actually landed on the PR, and
>    Phase 6 compares against it.

Step 5 keeps its own local comparison — that is the different question of
whether the push took — and adds the re-fix. Do not renumber the flow.

- [ ] **Step 5: Verify**

```sh
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py -v
```
Expected: OK, zero failures and zero errors, including Task 3's guard tests and
the pre-existing `test_degradation_gate_delegates_counting_and_carries_the_retuned_boundary`.

Then confirm the retired remedy is gone from the whole skill tree:
```sh
if grep -rq 're-push first' home/common/agent-skills/skills/ship-issue/; then
  echo "the re-push remedy survives"; exit 1
fi
```
Expected: no output, exit 0. At the commit this task starts from the grep matches
`SKILL.md` and the gate exits 1.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/skills/ship-issue/SKILL.md \
        home/common/agent-skills/skills/ship-issue/REVIEW.md \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "fix(issue-132): compare the PR tip to the reviewed HEAD_SHA"
```
Include the `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.
Never disable commit signing.
