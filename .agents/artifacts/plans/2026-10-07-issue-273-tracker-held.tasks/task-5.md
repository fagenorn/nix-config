# Task 5: ship-issue close-or-hold text and HUMAN-GATE

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md`
- Modify: `home/common/agent-skills/skills/ship-issue/evals/evals.json`
- Modify: `home/common/agent-skills/instruction-load.json`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes:
  - Task 2: the `build-delivery --kind observation` kind `tracker_held`, with the facts `comment_url`, `record_path`, `acceptance_state` and `observation_identity`.
  - Task 3: the owner rule admits `merged` with `issue_closed: false`.
  - S1 (#272): the acceptance record is `<plans dir>/<plan stem>.acceptance.md`, and its Verdict tokens are closed.
- Produces: ship-issue text that defines the effective acceptance state (Phase 0), the `## Acceptance` PR body section (Phase 4), the hold branch (Phase 8 step 1), the `tracker_held` cycle (Delivery loop) and the PR-body read in remainder mode. Task 6's text points at "Phase 8 step 1's hold branch" by that name.

**Invariants:**
- The PR-create example stays one command in the guard's form. Its body contains no `"`, `$`, backtick or backslash (D9).
- Every new command is a single command in an inline span, with no pipe, redirect, `&&`, heredoc or command substitution. `test_shell_example_contracts.py` stays green.
- Existing ordered anchors keep their order:
  - Phase 8's `gh issue close`, then `git worktree remove`, then `Only after issue closure and worktree cleanup both succeed`, then `validate-report --boundary ship-summary`.
  - HUMAN-GATE Gate 1's `Closes #<num>` after `gh pr create`, and Gate 2's `gh issue close <num>` before `git push origin --delete <branch>`.
- The label is created only when missing, and never with `--force` (D10). A relaunched owner reuses an existing `Held for verification: <PR URL>` comment (D14).

- [ ] **Step 1: Write the failing test**

Append this class to `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, immediately before `if __name__ == "__main__":`:

```python
class TrackerHoldContractsTest(unittest.TestCase):
    """#273 AC4: ship-issue holds as needs-verification in the delivery loop and Phase 8."""

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def section(text, heading, next_heading=None):
        start = text.index(heading)
        if next_heading is None:
            return text[start:]
        return text[start:text.index(next_heading, start + len(heading))]

    def setUp(self):
        self.ship = normalized(SHIP_ISSUE.read_text(encoding="utf-8"))
        self.gate = normalized(SHIP_ISSUE_HUMAN_GATE.read_text(encoding="utf-8"))

    def test_phase_0_fixes_the_effective_acceptance_state(self):
        phase0 = self.section(self.ship, "## Phase 0 — Pre-flight", "## Phase 1")
        self.assert_ordered(
            phase0, "**Effective acceptance state.**",
            "`<plan stem>.acceptance.md` beside the plan root", "`met (attested)`",
            "`--auto` never asks and never self-attests",
            "`met` or `not_applicable` **closes** the issue",
            "`unmet` or `human_pending` **holds** it open as `needs-verification`")

    def test_the_pr_body_carries_the_verdict_table_and_a_conditional_trailer(self):
        phase4 = self.section(self.ship, "## Phase 4 — Open PR", "## Phase 5")
        self.assert_ordered(
            phase4, "## Acceptance", "Acceptance state: <effective acceptance state>",
            "Acceptance record: <record-path or none>", "<acceptance table>",
            "Closes #<num>")
        self.assertIn("a Markdown table with the three columns `AC`, `Kind` and "
                      "`Verdict`, one row per record row", phase4)
        self.assertIn("On a **hold** drop the `Closes #<num>` line too: a hold body "
                      "carries no closing keyword", phase4)

    def test_phase_8_names_the_hold_branch_and_creates_the_label_on_demand(self):
        phase8 = self.section(self.ship, "## Phase 8 — Cleanup", "## Notes")
        self.assert_ordered(
            phase8, "**Close** (`met` or `not_applicable`)", "gh issue close <num>",
            "**Hold** (`unmet` or `human_pending`)", "gh issue reopen <num>",
            "gh label list --repo <resolved-repository> --search needs-verification --json name",
            "gh label create needs-verification", "never `--force`",
            "gh issue edit <num> --add-label needs-verification",
            "Held for verification: <PR URL>", "gh issue comment <num>",
            "git worktree remove")
        self.assertIn("`issue_closed: false` on hold", phase8)

    def test_the_delivery_loop_records_a_hold_as_tracker_held(self):
        loop = self.section(self.ship, "## Delivery loop", "## Remainder mode")
        self.assert_ordered(
            loop, "`close_tracker` → `tracker_closed`, or `tracker_held` on a hold",
            "On a hold the `close_tracker` cycle runs Phase 8 step 1's hold branch",
            "`needs-verification`", "`tracker_held` with the facts `comment_url`",
            "`observation_identity` `github:issue:<num>:held`",
            "on the close branch only, closure by a merge that closes the issue")

    def test_a_remainder_reads_its_acceptance_state_from_the_pr_body(self):
        remainder = self.section(self.ship, "## Remainder mode")
        self.assert_ordered(
            remainder, "--json body", "one `Acceptance state:` line",
            "one `Acceptance record:` line", "stops before the `close_tracker` effect "
            "with `terminal_failed`", "never default")

    def test_the_human_gate_mirrors_close_or_hold(self):
        self.assert_ordered(
            self.gate, "## Acceptance", "Closes #<num>",
            "present on the close branch and absent on a hold", "gh issue close <num>",
            "gh issue reopen <num>", "gh issue edit <num> --add-label needs-verification",
            "git push origin --delete <branch>")
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k TrackerHoldContractsTest 2>&1 | tail -10`
Expected: all six cases fail. The anchors such as `**Effective acceptance state.**` are absent.

- [ ] **Step 3: Edit `ship-issue/SKILL.md`**

The prose below is skill instruction. Write it verbatim, reflowed to the file's ~80-column wrap. The tests normalize whitespace.

1. **The flow.** Line 4 becomes `4. Open PR                 → push -u; gh pr create with "Closes #<num>" unless held`. Line 8 becomes `8. Cleanup                 → issue closed or held; worktree + branches removed`.
2. **Phase 0.** After the line `Any failure: pause, ground, surface. ...`, add this paragraph (D13, parent D8):
   > **Effective acceptance state.** Start from the handoff's `acceptance_state`; standalone with `review_state: unknown` it is `not_applicable`. The acceptance record is `<plan stem>.acceptance.md` beside the plan root, or `none` when no such file exists. With `human_pending` and `auto: false`, ask the user, as one grounded question, to attest each `human_pending` row of the record. When every row is attested, rewrite those Verdict cells to `met (attested)`, commit the record (### Local commits) and continue with `met`; the new commit means Phase 2 cannot skip its rerun. Otherwise keep `human_pending`. `--auto` never asks and never self-attests. The value is then fixed for the run, and ship grades nothing: `met` or `not_applicable` **closes** the issue, while `unmet` or `human_pending` **holds** it open as `needs-verification` (Phase 8).
3. **Phase 4.** In the `gh pr create` fence, insert these lines between `<plan-path>` and the blank line before `Closes #<num>"`, keeping one blank line between blocks:
   ```
   ## Acceptance
   Acceptance state: <effective acceptance state>

   Acceptance record: <record-path or none>

   <acceptance table>
   ```
   Directly after the guard-form paragraph (`This is the one form the lifecycle guard accepts: ...`), add (D8, D9):
   > The `## Acceptance` section always appears. `Acceptance state:` carries Phase 0's effective value, and `Acceptance record:` carries the record's repository-relative path or `none`. With a record, `<acceptance table>` is a Markdown table with the three columns `AC`, `Kind` and `Verdict`, one row per record row, copying its closed tokens; without one, drop that line. On a **hold** drop the `Closes #<num>` line too: a hold body carries no closing keyword (close, closes, closed, fix, fixes, fixed, resolve, resolves or resolved before an issue reference), so the merge cannot close the issue.

   In the `GitHub auto-close on merge ...` paragraph, `keep the `Closes #<num>` trailer for traceability` becomes `on the close branch keep the `Closes #<num>` trailer for traceability`.
4. **Phase 8.**
   - In the lifecycle paragraph, `issue close (`close_tracker`, observation-only when the merge already closed it)` becomes `issue close or hold (`close_tracker`; on the close branch observation-only when the merge already closed it)`.
   - Replace step 1 with this (D8, D10, D14):
   > 1. Close or hold, per Phase 0's effective acceptance state.
   >    - **Close** (`met` or `not_applicable`): `gh issue view <num> --json state`; if `OPEN`, `gh issue close <num>` (the real close mechanism when retained integration and default branches differ — see Phase 4).
   >    - **Hold** (`unmet` or `human_pending`), in this order: `gh issue view <num> --json state,comments`; if `CLOSED` (a commit's closing keyword can close it), `gh issue reopen <num>`. When `gh label list --repo <resolved-repository> --search needs-verification --json name` shows no name exactly `needs-verification`, run `gh label create needs-verification --repo <resolved-repository> --description "Merged, acceptance criteria await verification"` — never `--force`, which would overwrite a user's label. Then `gh issue edit <num> --add-label needs-verification`. The hold comment's first line is `Held for verification: <PR URL>`; the rest gives the effective acceptance state, the PR body's three-column table and the record's link at the merge SHA (`https://github.com/<resolved-repository>/blob/<merge-sha>/<record-path>`). When the earlier view already shows a comment with that first line, reuse its URL; otherwise post it with `gh issue comment <num> --body "<hold comment>"`, whose stdout is the comment URL. Finally `gh issue view <num> --json state,labels` must show `OPEN` with `needs-verification`; anything else keeps ownership and retries, as for any failed post-merge action.
   - In step 4, `Only after issue closure and worktree cleanup both succeed, construct the successful `merged` ship summary with the observed full `merge_sha`, `issue_closed: true`,` becomes `Only after issue closure and worktree cleanup both succeed — on a hold the confirmed hold stands in for closure — construct the successful `merged` ship summary with the observed full `merge_sha`, `issue_closed: true` on close or `issue_closed: false` on hold (its notes name the hold and the comment URL),`.
5. **Delivery loop.**
   - In step 4's cycle list, `the issue close (`close_tracker` → `tracker_closed`)` becomes `the issue close or hold (`close_tracker` → `tracker_closed`, or `tracker_held` on a hold)`. At the end of step 4, append:
   > On a hold the `close_tracker` cycle runs Phase 8 step 1's hold branch (reopen when closed, the `needs-verification` label, the hold comment) under that stage's own scope and fences, and its observation is `--kind observation` `tracker_held` with the facts `comment_url` (the hold comment's URL), `record_path` (the acceptance record), `acceptance_state` (the effective state) and `observation_identity` `github:issue:<num>:held`.
   - In step 5, `and closure by a merge that closes the issue` becomes `and, on the close branch only, closure by a merge that closes the issue; a hold always runs its cycle`.
   - In step 7, `whose `historical_owner_result` is the legacy `merged` row` becomes `whose `historical_owner_result` is the legacy `merged` row (`issue_closed: false` on a hold)`.
6. **Remainder mode.** Before the paragraph that begins `A denial or a `delivery_stalled` reply ends a remainder owner's loop`, add (D11):
   > A remainder has no handoff, so it takes the close-or-hold choice from its PR body. On every remainder entry, whichever cycle it starts at (including a cleanup cycle after `close_tracker` is already observed), run `gh pr view <pr-num> --repo <resolved-repository> --json body` and take the body's one `Acceptance state:` line, its one `Acceptance record:` line and its acceptance table. `met` or `not_applicable` closes and `unmet` or `human_pending` holds, exactly as in Phase 8 step 1. A missing or repeated line, or a value outside those four, stops before the `close_tracker` effect with `terminal_failed`, whose notes name the line; never default. When the stage is already observed as a hold, recover the hold comment URL from `gh issue view <num> --json comments` (the comment whose first line is `Held for verification: <PR URL>`) for the summary's notes instead of posting a second comment.

- [ ] **Step 4: Edit `HUMAN-GATE.md` and the eval (D16)**

1. In Gate 1's `gh pr create` fence, insert the same `## Acceptance` block as in step 3.3, between `<plan-path>` and `Closes #<num>"`.
2. The sentence `Present the body fully rendered — the resolved bindings substituted, the `Closes #<num>` trailer present.` becomes `Present the body fully rendered — the resolved bindings substituted, the `## Acceptance` section filled from Phase 0's effective acceptance state, and the `Closes #<num>` trailer present on the close branch and absent on a hold.`
3. In Gate 2's list, insert this bullet directly after the `gh issue close <num>` bullet:
   > - on a hold instead, Phase 8 step 1's hold branch: `gh issue reopen <num>` when the merge closed it, `gh label create needs-verification` when the label is missing, `gh issue edit <num> --add-label needs-verification` and `gh issue comment <num>`;
4. In `ship-issue/evals/evals.json`, eval id 3's `expected_output`: `Do not retarget main, omit the trailer, or make closing optional.` becomes `Do not retarget main, omit the trailer on the close branch, or make closing optional when the effective acceptance state is met or not_applicable.`. Keep the file valid JSON.

- [ ] **Step 5: Raise the instruction-load ceilings**

Commit nothing yet. Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py 2>&1 | grep -E "ceiling|FAIL|OK" | head -20`

For each `(profile, host)` that `test_the_live_tree_breaches_no_ceiling` reports, set that profile's `ceiling_bytes[host]` in `home/common/agent-skills/instruction-load.json` to the measured hot total named in the breach. Append this sentence to that profile's `note`: `Ceiling raised for #273: ship-issue fixes an effective acceptance state and holds an unmet issue as needs-verification instead of closing it (#155 D10).` Change no other profile.

- [ ] **Step 6: Verify**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -4`
Expected: `OK`. That covers the six `TrackerHoldContractsTest` cases, the existing `Closes #<num>` and Gate 2 ordering tests, and the shell-form sweep.

Run: `python3 -c "import json;json.load(open('home/common/agent-skills/skills/ship-issue/evals/evals.json'))"`
Expected: exit 0.

Run: `if grep -n 'gh label create needs-verification[^`]*--force' home/common/agent-skills/skills/ship-issue/SKILL.md; then exit 1; fi`
Expected: no output and exit 0 (D10).

- [ ] **Step 7: Commit**

```bash
git add home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md home/common/agent-skills/skills/ship-issue/evals/evals.json home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- -m "docs(ship-issue): hold an issue as needs-verification on unmet acceptance (#273)" -m "<trailers>"
```
