# Task 3: The launch guard before every pre-merge forge write

Discharges AC2, AC3's never-writes half, and the guard half of AC6. Rests on
spec rows D1, D2, D7, D8, D12, D13, D14, and on the new D17.

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-issue/REVIEW.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Task 1): the verb
  `~/.agents/bin/workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <issue:attempt:launch>`,
  exit 0 with exactly the four keys `action_id`, `current`, `current_action_id`,
  `reason`.
- Consumes (Task 2): the handoff field `action_id`, non-null exactly when the
  rest of the lifecycle group is.
- Produces, for Task 4: a `## Launch guard` section in `ship-issue/SKILL.md`
  that Phase 6 and Phase 7 can point at by name.

**Invariants:**
- The guard is stated as **one rule** — every write to the forge or to `origin`
  before the merge is verified — not as an enumeration that can drift.
- No line this task adds to `ship-issue/SKILL.md` contains the literal
  `gh pr merge`: `test_ship_issue_merge_is_bound_to_the_resolved_repository`
  `assertEqual`s the complete list of lines containing it.
- The `## Launch guard` section never contains `workflow-state suspend`: in the
  retry shape a suspend is refused, and in the resume shape it would park the
  successor's live attempt (per D8).
- A refusal writes nothing anywhere — no forge write, no ledger write, no
  cleanup — and Phase 8 does not run.
- The guard fails closed on a missing helper, a non-zero exit, or unparseable
  output; the only skip is a ledger-free invocation.

---

- [ ] **Step 1: Write the failing tests**

Add these to `WorkflowSkillContractsTest` in
`home/common/agent-skills/tests/test_workflow_skill_contracts.py`, immediately
after `test_ship_issue_merge_is_bound_to_the_resolved_repository`:

```python
    def test_ship_issue_guards_every_pre_merge_forge_write(self):
        guard = self.section(self.ship_issue, "## Launch guard",
                             "## Doc-grounded escalations")
        collapsed = normalized(guard)
        self.assertIn(
            "~/.agents/bin/workflow-state check-launch --repo-root "
            "<ledger_repo_root> --run-id <run-id> --action-id "
            "<issue:attempt:launch>",
            collapsed,
        )
        self.assertIn("Proceed only on `current: true`", collapsed)
        # Every refusal trigger, so a guard that degraded to "on a false answer"
        # would fail here rather than pass with a hole.
        for trigger in ("`current: false`", "a non-zero exit", "a missing helper",
                        "output that does not parse"):
            with self.subTest(trigger=trigger):
                self.assertIn(trigger, collapsed)
        # The refusal is a no-write stop, not a suspension (per D8).
        self.assertIn("no ledger write", collapsed)
        self.assertIn("/from-issue <num> --auto", collapsed)
        self.assertIn("`stopped` ship summary", collapsed)
        self.assertNotIn("workflow-state suspend", guard)
        # The post-merge exemption and the ledger-free skip.
        self.assertIn("after the merge is verified", collapsed)
        self.assertIn("skip the guard silently", collapsed)

        # Phase 4: the query immediately precedes each of its two forge writes.
        phase_four = self.section(self.ship_issue, "## Phase 4 — Open PR",
                                  "## Summary")
        self.assert_ordered(phase_four, "check-launch",
                            "git push -u origin <branch>",
                            "check-launch", "gh pr create")
        # Phase 5's fix push is an instance of the same rule, not an exception.
        self.assert_ordered(normalized(self.ship_review), "check-launch",
                            "`git push`")
        # Phase 7: the query precedes the merge. Anchor on --delete-branch: the
        # literal `gh pr merge` is pinned line-by-line elsewhere in this file.
        phase_seven = self.section(self.ship_issue, "## Phase 7 — Merge",
                                   "## Phase 8 — Cleanup")
        self.assert_ordered(phase_seven, "check-launch", "--delete-branch")

    def test_ship_owner_reads_the_ledger_but_never_writes_it(self):
        # AC3's invariant, previously unpinned. The read-only exception is named
        # so a reader cannot take the sentence as a ban on consulting the ledger.
        self.assertIn(
            "A fresh ship owner never writes workflow-state itself; the "
            "read-only `check-launch` query of `## Launch guard` is the one "
            "ledger call it makes.",
            normalized(self.ship_issue),
        )
```

Extend `test_helper_binaries_resolve_from_bare_names`: add
`("ship-issue", self.ship_issue)` to the `~/.agents/bin/workflow-state` subTest
tuple, which is `(("from-issue", self.from_issue), ("orchestrate", self.orchestrate))`
today — ship-issue now invokes the helper.

- [ ] **Step 2: Run the tests and watch them fail**

`unittest`'s `-k` takes one name pattern per flag and ORs repeated flags; it
does **not** parse `a or b` inside a single pattern, so pass each name its own
flag or the selector silently matches nothing and the red phase proves nothing.

```sh
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py -v \
  -k guards_every_pre_merge -k never_writes_it -k helper_binaries
```
Expected: `Ran 3 tests`, 3 failures — a `Ran 0 tests` header means the selector
matched nothing and the red phase is void.
`test_ship_issue_guards_every_pre_merge_forge_write` raises `ValueError:
substring not found` from `section(...)` because `## Launch guard` does not
exist; the other two fail on missing anchors.

- [ ] **Step 3: Add the `## Launch guard` section**

In `home/common/agent-skills/skills/ship-issue/SKILL.md`, insert a new section
**between `## Standing authorization` and `## Doc-grounded escalations`**.
Hard-wrap the prose at ~80 columns; the fenced command stays on one line.

````markdown
## Launch guard

The lifecycle ledger reserves one worktree per issue and hands a retry the
predecessor's worktree and branch on purpose, so a superseded attempt can still
push, open a PR and merge. Before **every write to the forge or to `origin` this
skill makes up to and including the merge**, re-validate that the handoff's
launch identity is still the launch the ledger entitles:

```
~/.agents/bin/workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <issue:attempt:launch>
```

`<issue:attempt:launch>` is the `action_id` the handoff carried, passed through
verbatim — never recomputed, never derived from `attempt`; the launch ordinal is
exactly the part this owner cannot know. The verb is read-only: it takes no
clock, holds no lock and creates nothing.

Proceed only on `current: true`. Refuse the write on `current: false`, a
non-zero exit, a missing helper, or output that does not parse into the exact
four keys `action_id`, `current`, `current_action_id` and `reason`. **This one
call does not follow this skill's degrade-gracefully rule for absent optional
helpers** — that rule is written for optional bindings, not for a safety check,
and following it here would turn the guard into a no-op precisely when the
environment is broken.

Guarded: the Phase-4 push, the Phase-4 PR create, every push in REVIEW.md's
five-step apply/push flow, and the Phase-7 merge. Everything **after the merge is
verified** is deliberately unguarded — the remote branch delete, and Phase 8's
issue close, `git branch -d` and `git worktree remove`. A refusal there could
only refuse cleanup for a merge that already landed, stranding a worktree and a
branch; deleting an already-merged branch is idempotent and harmless. Phase 1's
merge from the integration branch and Phase 3's local commits are not forge
writes and are not guarded.

**A refusal is a stop that writes nothing anywhere.** Do not execute the write.
Make no further forge write, **no ledger write**, and run no cleanup: leave the
worktree, the branch and any PR exactly as they are, because the successor is
working in that same worktree on that same branch. Print the canonical re-entry
line `/from-issue <num> --auto` on its own line, then return a truthful
`stopped` ship summary whose notes name the refusal, the reported `reason`, this
`action_id` and the reported `current_action_id`. Its fields are `merge_sha:
null`, `issue_closed: false`, `discussion_items: []`, `pr_url` the PR when one
was already opened and null otherwise, and `detail_state: "none"` with
`report_path: null` — or the failure-only `unpublished` shape when Phase 5
retained readable Minor/Discussion findings, naming that retained source in
notes and keeping the worktree. Phase 8 does not run and no delivery detail is
published: the successor owns that worktree and will produce its own.

Without lifecycle identity — a standalone `/ship-issue <num>`, or a handoff
whose lifecycle group is all-null — skip the guard silently: a ledger-free
invocation has no attempts and no supersession mechanism, and the handoff
validator's all-or-nothing group means it is never partially present. That is
the only skip, and it is a statement about the invocation, not about the
environment.
````

- [ ] **Step 4: Point Phase 4 at it, around each write**

Replace the single Phase-4 fenced block (currently one block holding both the
push and the `gh pr create` heredoc) with two blocks separated by the guard
pointer, so the query sits immediately before each write:

````markdown
Run `check-launch` (see `## Launch guard`); on anything but `current: true`,
stop without pushing. Then:

```
git push -u origin <branch>
```

Run `check-launch` again, then:

```
gh pr create --base <integrationBranch> --title "<title>" --body "$(cat <<'EOF'
## Summary
<2-4 bullets of what shipped>

## Spec
<spec-path>

## Plan
<plan-path>

Closes #<num>
EOF
)"
```
````

Leave the rest of Phase 4 (title rule, auto-close note, full-URL rule) untouched.

- [ ] **Step 5: Point Phase 7 at it, before the merge**

In `## Phase 7 — Merge`, insert one paragraph immediately after the
`issueTracker.kind=none` parenthetical and before the "Use the `repoSlug`
binding…" paragraph:

> Run `check-launch` (see `## Launch guard`) immediately before the merge, and
> run it regardless of how Phase 6's tip check came out. On anything but
> `current: true`, refuse the merge and take the no-write stop.

This paragraph must not contain the literal `gh pr merge`.

- [ ] **Step 6: Guard the Phase-5 fix push**

In `home/common/agent-skills/skills/ship-issue/REVIEW.md`, `## The five-step
apply/push flow`, replace step 4 with:

> 4. Run `check-launch` (SKILL.md's `## Launch guard`); on anything but
>    `current: true`, stop without pushing and take the no-write stop. Then
>    `git push`.

A superseded predecessor pushing review fixes onto the shared branch is the same
harm as the Phase-4 push (per D7, D17). Keep the flow five steps: the guard is
part of step 4, not a sixth step.

- [ ] **Step 7: Qualify the never-writes sentence**

In `## Phase 8 — Cleanup`, replace the closing sentence "A fresh ship owner
never writes workflow-state itself." with:

> A fresh ship owner never writes workflow-state itself; the read-only
> `check-launch` query of `## Launch guard` is the one ledger call it makes.

The statement about **writes** stays true and unqualified; the clause only stops
a reader taking it as a ban on consulting the ledger at all.

- [ ] **Step 8: Verify**

```sh
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py -v
```
Expected: OK, zero failures and zero errors — the three new/extended tests pass
**and** `test_ship_issue_merge_is_bound_to_the_resolved_repository` still passes,
which is what proves no added line carries the literal `gh pr merge`.

Then confirm the two prohibitions directly:
```sh
S=home/common/agent-skills/skills/ship-issue/SKILL.md
if grep -q 'A fresh ship owner never writes workflow-state itself\.$' "$S"; then
  echo "the unqualified never-writes sentence survives"; exit 1
fi
if [ "$(grep -c 'gh pr merge' "$S")" -ne 3 ]; then
  echo "the gh pr merge line count moved"; exit 1
fi
```
Expected: no output, exit 0. The first gate is the falsifiable one — at the
commit this task starts from it matches and exits 1. The second is a regression
guard: it holds at base (three lines) and must still hold after.

- [ ] **Step 9: Commit**

```bash
git add home/common/agent-skills/skills/ship-issue/SKILL.md \
        home/common/agent-skills/skills/ship-issue/REVIEW.md \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(issue-132): guard every pre-merge forge write with check-launch"
```
Include the `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.
Never disable commit signing.
