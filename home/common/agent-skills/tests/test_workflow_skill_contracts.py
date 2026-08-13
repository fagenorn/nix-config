from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).parents[4]
ORCHESTRATE = (
    REPO_ROOT / "home/common/claude-code/skills/orchestrate-issues/SKILL.md"
)
FROM_ISSUE = REPO_ROOT / "home/common/agent-skills/skills/from-issue/SKILL.md"
AUTO = REPO_ROOT / "home/common/agent-skills/skills/from-issue/AUTO.md"
HANDOFF = REPO_ROOT / "home/common/agent-skills/skills/handoff/SKILL.md"


class WorkflowSkillContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orchestrate = ORCHESTRATE.read_text(encoding="utf-8")
        cls.from_issue = FROM_ISSUE.read_text(encoding="utf-8")
        cls.auto = AUTO.read_text(encoding="utf-8")
        cls.handoff = HANDOFF.read_text(encoding="utf-8")

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertNotEqual(next_position, -1, f"missing anchor: {anchor!r}")
            self.assertGreater(next_position, position, f"out-of-order anchor: {anchor!r}")
            position = next_position

    def section(self, text, heading, next_heading):
        start = text.index(heading)
        end = text.index(next_heading, start + len(heading))
        return text[start:end]

    def test_dispatcher_uses_durable_lifecycle_order(self):
        self.assert_ordered(
            self.orchestrate,
            "init-run",
            "reconcile",
            "launch",
            "from-issue",
            "reconcile",
        )
        self.assertIn("Never poll continuously", self.orchestrate)
        self.assertNotIn("Wait on notifications — never poll", self.orchestrate)
        for boundary in (
            "dispatcher resume",
            "notification receipt",
            "before retry",
            "before final drain",
        ):
            self.assertIn(boundary, self.orchestrate)
        self.assertIn("durable result takes precedence", self.orchestrate)
        self.assertIn("stale older-attempt notification", self.orchestrate)

    def test_dispatcher_retry_is_reconciled_and_helper_capped(self):
        retry_section = self.section(
            self.orchestrate, "## 5. Failure policy", "## 6. Final report"
        )
        self.assert_ordered(
            retry_section, "workflow-state reconcile", "workflow-state launch"
        )
        self.assertIn("refuses a third fresh attempt", retry_section)
        self.assertIn("retains the worktree", self.orchestrate)
        self.assertIn("not automatically relaunch", self.orchestrate)

    def test_owner_persists_exact_terminal_result_before_return(self):
        owner_return_section = self.section(
            self.from_issue, "## Terminal return procedure", "## Phase 0"
        )
        self.assert_ordered(
            owner_return_section,
            "--result-file",
            "workflow-state finish",
            "send the exact JSON",
        )
        for field in (
            "issue",
            "state",
            "pr_url",
            "merge_sha",
            "issue_closed",
            "discussion_items",
            "notes",
        ):
            self.assertIn(field, self.from_issue)
        self.assertIn("failure to persist is a failure to finish", owner_return_section)
        self.assertIn("never report the issue as merged or completed", owner_return_section)

    def test_owner_has_executable_phase_gate_and_action_semantics(self):
        self.assertIn("workflow-state progress", self.from_issue)
        self.assertIn("continue | fresh_start | handoff | delegate", self.from_issue)
        for phase in range(8):
            self.assertIn(f"Phase {phase}", self.from_issue)
        self.assertIn("At every phase boundary", self.from_issue)
        self.assertIn("Do not fabricate usage", self.from_issue)
        self.assertIn("120", self.from_issue)
        self.assertIn("150000", self.from_issue)
        self.assertIn("same attempt", self.from_issue)
        self.assertIn("fresh agent", self.from_issue)

    def test_owner_lifecycle_is_optional_for_direct_use_and_covers_all_stops(self):
        self.assertIn("optional lifecycle envelope", self.from_issue)
        for field in ("run_id", "attempt", "owner", "worktree"):
            self.assertIn(field, self.from_issue)
        self.assertIn("direct standalone invocation remains compatible", self.from_issue)
        phase_zero = self.section(self.from_issue, "## Phase 0", "## Phase 1")
        self.assertIn("lifecycle identity", phase_zero)
        self.assertIn("workflow-state finish", phase_zero)
        self.assertIn("execution failure", self.from_issue)
        phase_seven = self.section(self.from_issue, "## Phase 7", "## Notes")
        self.assert_ordered(
            phase_seven,
            "receiving the ship report",
            "workflow-state finish",
            "send the exact JSON",
        )

    def test_auto_mode_never_skips_durable_checkpoints_or_terminal_writes(self):
        self.assertIn("never skips `workflow-state progress`", self.auto)
        self.assertIn("every phase checkpoint", self.auto)
        self.assert_ordered(
            self.auto,
            "durable handoff",
            "finalize",
            "stop",
        )
        self.assert_ordered(
            self.auto,
            "terminal result",
            "workflow-state finish",
            "notification",
        )

    def test_handoff_supports_safe_durable_destination_and_temp_default(self):
        self.assertIn(".superpowers/workflows/<run-id>/handoffs/", self.handoff)
        self.assertIn("caller-provided destination", self.handoff)
        self.assertIn("symlink", self.handoff)
        self.assertIn("path escape", self.handoff)
        self.assertIn("Read the destination before writing", self.handoff)
        self.assertIn("atomically replace", self.handoff)
        self.assertIn("mktemp", self.handoff)
        self.assertIn("Do not duplicate lifecycle JSON", self.handoff)


if __name__ == "__main__":
    unittest.main()
