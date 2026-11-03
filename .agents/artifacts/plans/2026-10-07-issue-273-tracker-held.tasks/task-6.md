# Task 6: orchestrate-issues reports held; from-issue handoff close-or-hold

**Files:**
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md`
- Modify: `home/common/agent-skills/instruction-load.json`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes:
  - Task 4: control summary state `held`. It is projected only for a delivered issue whose `tracker_closed` postcondition is a `tracker_held` observation and whose tracker reads `open`. A dependent naming it in `open_blockers` reads `blocked`.
  - Task 5: ship-issue's "Phase 8 step 1" hold branch, by that name.
- Produces: §5 report text for `held`, and the from-issue ship-handoff close-or-hold rule, including its inline fallback.

**Invariants:**
- §5 reports a `held` summary as held, waiting for human verification. It is never queued, progressing or closed, and it gets no re-entry line (D7, parent D7).
- §2, §3 and §4 of orchestrate-issues are not edited. Dependents need no code, because the tracker adapter already lists an open issue in `open_blockers`.
- The handoff no longer says ship's close stage ignores `acceptance_state`. The inline fallback holds rather than closes (spec "ship-issue / from-issue").

- [ ] **Step 1: Write the failing tests**

(a) In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, in `AcceptanceGradingContractsTest.test_both_handoff_templates_carry_acceptance_state`, replace the last anchor of the `assert_ordered(handoff, ...)` call, `"its close stage does not read it"`, with `"holds it open as `needs-verification`"`.

(b) Append this class immediately before `if __name__ == "__main__":`:

```python
class HeldReportContractsTest(unittest.TestCase):
    """#273: orchestrate-issues reports held issues; the ship handoff closes or holds."""

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def section(text, heading, next_heading):
        start = text.index(heading)
        return text[start:text.index(next_heading, start + len(heading))]

    def test_the_final_report_names_held_and_keeps_it_a_blocker(self):
        report = self.section(normalized(ORCHESTRATE.read_text(encoding="utf-8")),
                              "## 5. Final report", "## Notes")
        self.assert_ordered(
            report, "A `held` summary is an issue whose PR merged",
            "`needs-verification`", "report it as held",
            "never as queued, progressing or closed", "with no re-entry line",
            "stays in its dependents' `open_blockers`", "they stay `blocked`")

    def test_the_handoff_and_its_inline_fallback_close_or_hold(self):
        handoff = normalized((FROM_ISSUE_DIR / "ship-handoff.md").read_text(encoding="utf-8"))
        self.assertNotIn("its close stage does not read it", handoff)
        self.assertIn("`met` or `not_applicable` closes the issue, and `unmet` or "
                      "`human_pending` holds it open as `needs-verification` "
                      "(ship-issue Phase 8 step 1)", handoff)
        fallback = self.section(handoff, "## Inline fallback (no ship-issue skill)",
                                "## Remainder owner prompt")
        self.assert_ordered(
            fallback, "close the issue when the sdd report's `acceptance_state` is "
            "`met` or `not_applicable`", "label it `needs-verification`",
            "comment the verdict table", "leaving it open")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k HeldReportContractsTest -k test_both_handoff_templates_carry_acceptance_state 2>&1 | tail -10`
Expected: three failures. The anchors are absent, and `its close stage does not read it` is still present.

- [ ] **Step 3: Edit the skill text**

Write this prose verbatim, reflowed to each file's wrap.

1. In `orchestrate-issues/SKILL.md` §5, directly after the sentence ending `report it as delivered with that stale custody, never as an active or progressing owner.`, insert:
   > A `held` summary is an issue whose PR merged while ship held the issue open with the `needs-verification` label: report it as held, waiting for a human to verify it, never as queued, progressing or closed, and with no re-entry line. A held issue is still open on the tracker, so it stays in its dependents' `open_blockers` and they stay `blocked` until a human closes it.
2. In `from-issue/ship-handoff.md`, the sentence `ship-issue validates the field and carries it; its close stage does not read it.` becomes:
   > ship-issue validates the field and fixes its effective acceptance state from it: `met` or `not_applicable` closes the issue, and `unmet` or `human_pending` holds it open as `needs-verification` (ship-issue Phase 8 step 1).
3. In the same file's `## Inline fallback (no ship-issue skill)`, `merge `--no-ff`, close the issue, and publish` becomes:
   > merge `--no-ff`, then close the issue when the sdd report's `acceptance_state` is `met` or `not_applicable`; otherwise hold it: label it `needs-verification` (creating the label when missing), comment the verdict table, leaving it open, and publish

- [ ] **Step 4: Raise the instruction-load ceilings**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py 2>&1 | grep -E "ceiling|FAIL|OK" | head -20`

For each breached `(profile, host)`, set `ceiling_bytes[host]` to the measured hot total named in the breach. Append this sentence to that profile's `note`: `Ceiling raised for #273: orchestrate-issues reports held issues and the ship handoff closes or holds on acceptance_state (#155 D10).` Change no other profile.

- [ ] **Step 5: Verify**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -4`
Expected: `OK`.

Run: `git diff --stat HEAD -- home/common/claude-code/skills/orchestrate-issues/SKILL.md | tail -1`
Expected: `1 file changed`, with insertions only inside §5. Confirm with `git diff -U0 HEAD -- home/common/claude-code/skills/orchestrate-issues/SKILL.md | grep '^@@'`, which shows hunks that start after the line of `## 5. Final report`.

- [ ] **Step 6: Commit**

```bash
git add home/common/claude-code/skills/orchestrate-issues/SKILL.md home/common/agent-skills/skills/from-issue/ship-handoff.md home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- -m "docs(orchestrate-issues): report held issues; ship handoff closes or holds (#273)" -m "<trailers>"
```
