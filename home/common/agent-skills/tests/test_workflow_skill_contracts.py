import html
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).parents[4]
ORCHESTRATE = (
    REPO_ROOT / "home/common/claude-code/skills/orchestrate-issues/SKILL.md"
)
ORCHESTRATE_EVALS = (
    REPO_ROOT / "home/common/claude-code/skills/orchestrate-issues/evals/evals.json"
)
FROM_ISSUE = REPO_ROOT / "home/common/agent-skills/skills/from-issue/SKILL.md"
AUTO = REPO_ROOT / "home/common/agent-skills/skills/from-issue/AUTO.md"
INVESTIGATE = REPO_ROOT / "home/common/agent-skills/skills/from-issue/investigate.md"
HANDOFF = REPO_ROOT / "home/common/agent-skills/skills/handoff/SKILL.md"
DESIGN = REPO_ROOT / "home/common/agent-skills/skills/design/SKILL.md"
GRILL = REPO_ROOT / "home/common/agent-skills/skills/grill-with-docs/SKILL.md"
COLLABORATION = (
    REPO_ROOT / "home/common/claude-code/skills/codex-collaboration/SKILL.md"
)
CERTIFICATION = (
    REPO_ROOT / "home/common/claude-code/skills/codex-collaboration/CERTIFICATION.md"
)
DIFF_REVIEW = (
    REPO_ROOT / "home/common/claude-code/skills/codex-collaboration/DIFF-REVIEW.md"
)
RESEARCH = REPO_ROOT / "home/common/agent-skills/skills/research/SKILL.md"
WORKTREES = REPO_ROOT / "home/common/agent-skills/skills/worktrees/SKILL.md"
SDD_DIR = REPO_ROOT / "home/common/agent-skills/skills/sdd"
FROM_ISSUE_DIR = REPO_ROOT / "home/common/agent-skills/skills/from-issue"
SHIP_ISSUE = REPO_ROOT / "home/common/agent-skills/skills/ship-issue/SKILL.md"
SHIP_ISSUE_REVIEW = REPO_ROOT / "home/common/agent-skills/skills/ship-issue/REVIEW.md"
SMALL_BUDGET_FIXTURE = (
    REPO_ROOT / "home/common/agent-skills/tests/fixtures/artifact-budgets/small-issue.json"
)
OVERSIZED_BUDGET_FIXTURE = (
    REPO_ROOT / "home/common/agent-skills/tests/fixtures/artifact-budgets/oversized-issue.json"
)
SHIP_ISSUE_EVALS = (
    REPO_ROOT / "home/common/agent-skills/skills/ship-issue/evals/evals.json"
)
WRITING_PLANS = REPO_ROOT / "home/common/agent-skills/skills/writing-plans/SKILL.md"
SDD = SDD_DIR / "SKILL.md"
PHASE_5_REVIEW_CONTRACT = FROM_ISSUE_DIR / "REVIEW-CONTRACT.md"
CODEX_PLAN_REVIEW = (
    REPO_ROOT / "home/common/claude-code/skills/codex-collaboration/PLAN-REVIEW.md"
)
CODEX_COLLABORATION_EVALS = (
    REPO_ROOT / "home/common/claude-code/skills/codex-collaboration/evals/evals.json"
)

# The Phase-5 degradation boundary, spelled once for the whole module: the skill
# and its eval are both checked against these two strings so they cannot drift.
GATE_LINE_BOUNDARY = "≤1,000 product lines"
GATE_FILE_BOUNDARY = "≤20 product files"

SKILL_ROOTS = (
    REPO_ROOT / "home/common/agent-skills/skills",
    REPO_ROOT / "home/common/claude-code/skills",
)

# The producer-report candidate contract, spelled once for the whole corpus so
# the four skills that carry it cannot drift apart (D1).
REPORT_CANDIDATE_CLAUSE = (
    "a report candidate outside every working tree — create it with `mktemp "
    '"${TMPDIR:-/tmp}/producer-report-XXXXXX.json"` (the explicit `XXXXXX` '
    "template works on both macOS/BSD and Linux) — invoke `artifact-budget "
    "validate-report --boundary producer --input <report-candidate>`, and "
    "remove that candidate under an unconditional cleanup that runs on every "
    "outcome, including validation rejection and failure: a shell `trap` on "
    "`EXIT HUP INT TERM`, or the equivalent `finally`"
)

# One literal for all three lifecycle request-file prescriptions (D17).
REQUEST_FILE_HOME = "a new absolute temporary request file beneath `${TMPDIR:-/tmp}`"
REQUEST_FILE_INVOCATION = "--request-file <absolute-json-path>"

# The terminal result file is the same class of control-plane scratch, so it
# shares that home; unlike the request file the helper consumes within the call,
# it outlives its own validation and carries the report candidate's cleanup.
RESULT_FILE_HOME = (
    "a new absolute temporary result file beneath `${TMPDIR:-/tmp}`, removed "
    "under an unconditional cleanup that runs on every outcome, including "
    "validation rejection and failure: a shell `trap` on `EXIT HUP INT TERM`, "
    "or the equivalent `finally`"
)
RESULT_FILE_INVOCATION = "--result-file <path>"

# "sibling <=2 words> candidate" — the in-working-tree prescription being
# removed. The bounded gap keeps it off handoff's legitimate
# "candidate ... sibling temporary" sentences, where the words appear in the
# other order (D2).
SIBLING_CANDIDATE_RE = re.compile(r"sibling(?:\s+\S+){0,2}\s+candidate")

SDD_SCRIPTS = REPO_ROOT / "home/common/agent-skills/skills/sdd/scripts"

# The superseded claim: the workspace has not been repo-root-relative since the
# primary-checkout move (D3).
REPO_ROOT_WORKSPACE_LITERAL = "<repo-root>/.superpowers/sdd"

# Every `.superpowers/` home the corpus is allowed to name, spelled once (D10).
SUPERPOWERS_SEGMENTS = {"workflows", "issue-delivery", "sdd", "ship-review"}
SUPERPOWERS_SEGMENT_RE = re.compile(r"\.superpowers/([A-Za-z0-9_.-]+)")

SHIP_REVIEW_EXCEPTION = (
    "the one exception to the rule that workflow scratch never lives in a "
    "working tree"
)

# The orphaned-bucket prune, spelled once (D5, D8).
WORKTREE_BUCKET_LITERAL = "`<primary-checkout>/.superpowers/sdd/wt-<worktree-name>/`"

# What `git clean -fdx` actually destroys after Task 3 moved the ledger out of
# the feature worktree.
CLEAN_SCRATCH_CLAUSE = (
    "in a feature worktree that is `ship-issue`'s retained Minor/Discussion "
    "detail, and in the primary checkout it is every plan's SDD workspace"
)

GITIGNORE = REPO_ROOT / ".gitignore"

SCRATCH_IGNORE_PATTERNS = (
    ".superpowers/",
    ".worktrees/",
    "**/.claude/worktrees/",
    "*.tmp.??????",
    "producer-report-*.json",
    "review-package-report-*.json",
)

# Every ephemeral shape a workflow run has produced or been told to produce.
IGNORED_SHAPES = (
    ".superpowers/sdd/primary/plan/progress.md",
    ".superpowers/workflows/run-1/state.json",
    "home/common/.superpowers/sdd/x",
    ".worktrees/issue-102/file.txt",
    ".claude/worktrees/worktree-issue-102/README.md",
    ".claude/worktrees/wt/.superpowers/sdd/primary/p/progress.md",
    "nested/.claude/worktrees/w/file",
    ".claude/plans/task-1-brief.md.tmp.aB3xY9",
    "producer-report-Ab12Cd.json",
    "review-package-report-xyz789.json",
    ".claude/specs/producer-report-XXXXXX.json",
)

# Real repository content that must stay visible to `git status`.
KEPT_SHAPES = (
    ".gitignore",
    "CLAUDE.md",
    "justfile",
    ".claude/settings.json",
    ".claude/specs/2026-08-23-workflow-scratch-containment-design.md",
    ".claude/plans/2026-08-23-workflow-scratch-containment.md",
    ".claude/plans/2026-08-23-workflow-scratch-containment.tasks/task-1.md",
    "home/common/agent-skills/skills/sdd/scripts/sdd-workspace",
    "home/common/agent-skills/tests/test_sdd_workspace.py",
    "handoff-notes.md",
)


def normalized(text):
    """Collapse every whitespace run to one space (the corpus hard-wraps ~80c)."""
    return re.sub(r"\s+", " ", text)


def corpus_documents():
    """Every skill document in both skill trees, as (path, text) pairs."""
    for root in SKILL_ROOTS:
        for path in sorted(root.rglob("*.md")):
            yield path, path.read_text(encoding="utf-8")


def nested_workflow_documents():
    for directory in (FROM_ISSUE_DIR, SDD_DIR):
        for path in sorted(directory.glob("*.md")):
            yield path, path.read_text(encoding="utf-8")


class WorkflowSkillContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orchestrate = ORCHESTRATE.read_text(encoding="utf-8")
        cls.from_issue = FROM_ISSUE.read_text(encoding="utf-8")
        cls.auto = AUTO.read_text(encoding="utf-8")
        cls.investigate = INVESTIGATE.read_text(encoding="utf-8")
        cls.handoff = HANDOFF.read_text(encoding="utf-8")
        cls.design = DESIGN.read_text(encoding="utf-8")
        cls.grill = GRILL.read_text(encoding="utf-8")
        cls.collaboration = COLLABORATION.read_text(encoding="utf-8")
        cls.diff_review = DIFF_REVIEW.read_text(encoding="utf-8")
        cls.certification = CERTIFICATION.read_text(encoding="utf-8")
        cls.research = RESEARCH.read_text(encoding="utf-8")
        cls.worktrees = WORKTREES.read_text(encoding="utf-8")
        cls.ship_issue = SHIP_ISSUE.read_text(encoding="utf-8")
        cls.ship_review = SHIP_ISSUE_REVIEW.read_text(encoding="utf-8")
        cls.ship_issue_evals = json.loads(SHIP_ISSUE_EVALS.read_text(encoding="utf-8"))
        cls.writing_plans = WRITING_PLANS.read_text(encoding="utf-8")
        cls.sdd = SDD.read_text(encoding="utf-8")
        cls.phase_5_review_contract = PHASE_5_REVIEW_CONTRACT.read_text(encoding="utf-8")
        cls.codex_plan_review = CODEX_PLAN_REVIEW.read_text(encoding="utf-8")
        cls.codex_collaboration_evals = json.loads(
            CODEX_COLLABORATION_EVALS.read_text(encoding="utf-8")
        )
        cls.standards_review = (FROM_ISSUE_DIR / "standards-review.md").read_text(
            encoding="utf-8"
        )
        cls.ship_handoff = (FROM_ISSUE_DIR / "ship-handoff.md").read_text(
            encoding="utf-8"
        )
        cls.small_budget_fixture = json.loads(
            SMALL_BUDGET_FIXTURE.read_text(encoding="utf-8")
        )
        cls.oversized_budget_fixture = json.loads(
            OVERSIZED_BUDGET_FIXTURE.read_text(encoding="utf-8")
        )
        cls.orchestrate_evals = json.loads(
            ORCHESTRATE_EVALS.read_text(encoding="utf-8")
        )

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

    def test_dispatcher_is_a_control_adapter_not_a_policy_owner(self):
        observe = self.section(
            self.orchestrate, "## 2. Bootstrap and observe", "## 3. Decide"
        )
        decide = self.section(
            self.orchestrate, "## 3. Decide", "## 4. Execute control actions"
        )
        execute = self.section(
            self.orchestrate, "## 4. Execute control actions", "## 5. Final report"
        )
        self.assert_ordered(observe, "workflow-state init-run", "requirements",
                            "action_id", "recorded_worktree", "normalized")
        self.assert_ordered(
            observe, "every requested issue without a bootstrap requirement",
            "verified absent candidate", "control ignores unused candidates",
        )
        self.assertIn("matching_issue_branch | absent | mismatch", observe)
        self.assertRegex(observe, r"never omit the recorded-path\s+observation")
        self.assertNotIn("tracker-ready", observe)
        self.assertNotIn("classify tracker readiness", observe)
        self.assert_ordered(decide, "--request-file <absolute-json-path>",
                            "workflow-state control",
                            "only source of action order, kind, and lifecycle identity")
        for retired in ("workflow-state launch", "workflow-state reconcile"):
            self.assertNotIn(retired, self.orchestrate)
        for retired_policy_anchor in (
            "resume before fresh", "attempts 1 and 2", "permits a retry",
            "result_source", "earliest armed deadline", "deadline minima",
            "occupied slots", "count capacity", "run is drained",
            "fresh owner identity",
        ):
            self.assertNotIn(retired_policy_anchor, observe + decide + execute)

    def test_dispatcher_passes_immutable_ledger_root_separately_from_worktree(self):
        durable_section = self.section(
            self.orchestrate, "## 4. Execute control actions", "## 5. Final report"
        )
        self.assert_ordered(
            durable_section,
            "--repo-root <ledger_repo_root>",
            "ledger_repo_root=<ledger_repo_root>",
            "worktree=<absolute-worktree>",
            "from-issue <num> --auto",
        )
        self.assertIn("exact immutable value", durable_section)
        self.assertIn("independent of any issue worktree", durable_section)

        declaration = durable_section.index(
            'Agent(subagent_type="general-purpose", model="opus", effort="high", '
            'run_in_background=true)'
        )
        fresh_context = durable_section[declaration:]
        fresh_prompt = fresh_context[:fresh_context.index("\n\nNever inline")]
        for field in (
            "ledger_repo_root=<ledger_repo_root>",
            "run_id=<run-id>",
            "issue=<issue>",
            "attempt=<attempt>",
            "owner=<owner-token>",
            "action_id=<action-id>",
            "worktree=<absolute-worktree>",
            "handoff_path=<exact-handoff-path>",
            "from-issue <num> --auto",
        ):
            self.assertIn(f"> `{field}`", fresh_prompt)
        self.assertIn("> Immutable lifecycle envelope:", fresh_prompt)
        self.assertIn("> Include `handoff_path` only when non-null.", fresh_prompt)

    def test_dispatcher_maps_resolved_limits_into_control_request(self):
        resolve = self.section(
            self.orchestrate, "## 1. Resolve issue set and bindings",
            "## 2. Bootstrap and observe",
        )
        self.assertIn(
            "resolved `agentBudgetMinutes` as request `attempt_budget_minutes`",
            resolve,
        )
        self.assertIn(
            "resolved `maxParallel` as request `max_parallel`",
            resolve,
        )
        self.assertNotIn("--budget-minutes <budget>", resolve)

    def test_dispatcher_executes_the_closed_control_action_set(self):
        action_section = self.section(
            self.orchestrate, "## 4. Execute control actions", "## 5. Final report"
        )
        for kind in ("spawn", "resume", "retry", "wait", "finalize"):
            self.assertIn(f"`{kind}`", action_section)
        self.assertIn("returned order", action_section)
        self.assertIn("owner token unchanged", action_section)
        self.assertIn("handoff_path", action_section)
        self.assertIn(
            "Any other kind is a contract error: stop without executing it and surface the unknown kind",
            action_section,
        )
        self.assertNotIn("host task ID as lifecycle identity", action_section)

    def test_dispatcher_uses_one_superseding_wait(self):
        action_section = self.section(
            self.orchestrate, "## 4. Execute control actions", "## 5. Final report"
        )
        self.assert_ordered(
            action_section,
            "save the old `current_wait_id` and `current_wait_handle` pair",
            "publish the new wait ID", "cancel the old handle",
            "arm and store the new one-shot observer",
        )
        self.assertIn("same wait ID", action_section)
        self.assertIn("does not arm another observer", action_section)
        self.assertIn("wake carries its wait ID", action_section)
        self.assertIn("ignore it unless it equals `current_wait_id`", action_section)
        self.assert_ordered(action_section, "`finalize`", "clear `current_wait_id`",
                            "cancel the outstanding handle")
        self.assertIn("No polling or repeated short sleeps", action_section)

    def test_dispatcher_wait_failures_and_restart_cleanup_are_explicit(self):
        action_section = self.section(
            self.orchestrate, "## 4. Execute control actions", "## 5. Final report"
        )
        self.assert_ordered(
            action_section, "missing or already exited", "idempotent",
            "arm the replacement",
        )
        self.assert_ordered(
            action_section, "unexpected cancellation failure",
            "restore the old `current_wait_id` and `current_wait_handle` pair",
            "do not arm the replacement", "fail loudly",
            "next identical response retries replacement",
        )
        self.assertIn(
            "never leave the new wait ID paired with the old handle",
            action_section,
        )
        self.assert_ordered(
            action_section, "arming fails", "clear `current_wait_id`",
            "clear `current_wait_handle`", "no wake is installed", "fail loudly",
        )
        self.assert_ordered(
            self.orchestrate, "full dispatcher restart",
            "host reaps or cancels inherited detached wait observers",
            "before", "rearm",
        )
        self.assertIn("process-local", self.orchestrate)

    def test_dispatcher_renders_finalize_from_bounded_summaries(self):
        final_section = self.section(
            self.orchestrate, "## 5. Final report", "## Notes"
        )
        self.assertIn("finalize", final_section)
        self.assertIn("same control response", final_section)
        self.assertIn("discussion_items", final_section)
        for forbidden in ("attempts", "launches", "phase_inputs", "older results"):
            self.assertIn(forbidden, self.orchestrate)

    def test_background_dispatch_flag_appears_only_in_orchestrate_issues(self):
        self.assertIn("run_in_background=true", self.orchestrate)
        for path, text in nested_workflow_documents():
            with self.subTest(path=str(path)):
                self.assertNotIn("run_in_background", text)

    def test_nested_dispatches_stay_unnamed_and_foreground(self):
        for path, text in nested_workflow_documents():
            for line_number, line in enumerate(text.splitlines(), 1):
                if "Agent(" not in line:
                    continue
                with self.subTest(path=f"{path}:{line_number}"):
                    self.assertNotIn("name=", line)
                    self.assertNotIn("run_in_background", line)

    def test_sdd_resume_by_identity_instruction_exists(self):
        sdd_root = (SDD_DIR / "SKILL.md").read_text(encoding="utf-8")
        fix_loop = (SDD_DIR / "fix-loop.md").read_text(encoding="utf-8")
        self.assertIn(
            "Record the implementer's agent identity — fix rounds 1–3 resume it",
            sdd_root,
        )
        self.assertIn("resume the original implementer", fix_loop)

    def test_plan_package_contract_is_root_only_and_fail_closed(self):
        self.assertIn("<stem>.tasks/task-1.md", self.writing_plans)
        self.assertIn("[task-N.md](<stem>.tasks/task-N.md)", self.writing_plans)
        self.assert_ordered(self.writing_plans, "write every task member", "artifact-budget check",
                            "compact repeated prose", "split only where both results are independently testable",
                            "decompose_required")
        self.assertIn("report only the root path and four metrics", self.writing_plans)
        for forbidden in ("open_items:", "decisions:", "adr_paths:", "summary:"):
            self.assertNotRegex(self.writing_plans, rf"(?m)^\s*{re.escape(forbidden)}")
        self.assert_ordered(normalized(self.writing_plans),
                            "report candidate outside every working tree",
                            "validate-report", "validated stdout bytes")

    def test_design_and_grill_measure_after_last_write_and_stop_truthfully(self):
        for producer in (self.design, self.grill):
            self.assert_ordered(producer, "final mutation", "artifact-budget check",
                                "compact repetition", "artifact-budget check",
                                "decompose_required")
            self.assertIn("budget_status: within_budget", producer)
            for metric in ("root_bytes", "total_bytes", "file_count",
                           "largest_member_bytes"):
                self.assertIn(metric, producer)
            self.assert_ordered(producer, "decompose_required",
                                "independently deliverable",
                                "proposed decomposition")
            self.assertNotIn("wc -c", producer)
            self.assertRegex(producer, r"state:.*complete.*decompose_required.*failed")

    def test_design_persists_the_final_measured_spec_before_reporting_complete(self):
        design = " ".join(self.design.split())
        self.assert_ordered(
            design,
            "final content mutation",
            "run and, if needed, remediate the budget checks",
            "final `within_budget` result",
            "commit the completed spec in the worktree",
            "construct, validate, and emit the `complete` producer report",
            "report candidate outside every working tree",
            "validate-report --boundary producer",
            "validated stdout bytes",
        )
        self.assertIn(
            "If committing or signing fails, return `failed`; never emit `complete`",
            design,
        )
        self.assertIn(
            "Never commit an over-budget or `decompose_required` draft as a completed design",
            design,
        )

        hook_boundary = design[design.index("If any commit hook changes"):]
        self.assert_ordered(
            hook_boundary,
            "prior metrics are stale",
            "artifact-budget check --kind design-spec",
            "succeeding commit",
            "newly measured, final within-budget content",
            "before emitting `complete`",
        )

    def test_handoff_measures_candidate_before_durable_replace(self):
        self.assert_ordered(self.handoff, "sibling temporary", "artifact-budget check",
                            "remove duplicated", "artifact-budget check", "stopped")
        self.assert_ordered(self.handoff, "budget_status: within_budget", "atomically replace")
        self.assertIn("leave the existing destination byte-identical", self.handoff)
        self.assertIn("no fabricated metrics", self.handoff)

    def test_artifact_reports_are_bounded_root_only_shapes(self):
        for producer in (self.design, self.grill, self.handoff):
            for field in ("kind", "path", "metrics", "budget_status", "notes"):
                self.assertIn(field, producer)
            for metric in ("root_bytes", "total_bytes", "file_count",
                           "largest_member_bytes"):
                self.assertIn(metric, producer)
            for decision in ("(D5)", "(D11, D14)"):
                self.assertIn(decision, producer)
            self.assertIn("phase_reports.notes_max_characters", producer)
            self.assert_ordered(normalized(producer),
                                "report candidate outside every working tree",
                                "validate-report --boundary producer",
                                "validated stdout")
            self.assertIn("never inline artifact contents", producer)
            for forbidden in ("spec_path:", "adr_paths:", "decisions:", "open_items:", "summary:"):
                self.assertNotRegex(producer, rf"(?m)^\s*{re.escape(forbidden)}")

    def test_four_producer_skills_share_one_report_candidate_clause(self):
        clause = normalized(REPORT_CANDIDATE_CLAUSE)
        for name, text in (
            ("design", self.design),
            ("grill-with-docs", self.grill),
            ("writing-plans", self.writing_plans),
            ("handoff", self.handoff),
        ):
            with self.subTest(skill=name):
                self.assertIn(clause, normalized(text))

    def test_handoff_failure_reemit_uses_a_fresh_report_candidate(self):
        self.assertIn(
            "a fresh report candidate created and cleaned up the same way",
            normalized(self.handoff),
        )

    def test_handoff_keeps_the_publication_sibling(self):
        text = normalized(self.handoff)
        self.assertIn("as a sibling temporary regular file", text)
        self.assertIn("written as a sibling of the durable destination", text)

    def test_no_skill_prescribes_a_sibling_candidate(self):
        offenders = [
            f"{path.relative_to(REPO_ROOT)}: {match.group(0)!r}"
            for path, text in corpus_documents()
            for match in SIBLING_CANDIDATE_RE.finditer(normalized(text))
        ]
        self.assertEqual(offenders, [])

    def assert_every_carrier_states_the_temp_home(self, invocation, home, minimum):
        carriers = [
            (str(path.relative_to(REPO_ROOT)), normalized(text))
            for path, text in corpus_documents()
            if invocation in normalized(text)
        ]
        names = [name for name, _ in carriers]
        # Non-vacuity: the rule must have something to police.
        self.assertGreaterEqual(len(carriers), minimum, names)
        missing = [name for name, text in carriers if home not in text]
        self.assertEqual(missing, [])

    def test_request_file_prescriptions_name_the_temp_home(self):
        self.assertEqual(normalized(self.from_issue).count(REQUEST_FILE_HOME), 2)
        self.assertEqual(normalized(self.orchestrate).count(REQUEST_FILE_HOME), 1)

    def test_result_file_prescription_names_the_temp_home(self):
        self.assertEqual(normalized(self.from_issue).count(RESULT_FILE_HOME), 1)

    def test_every_request_file_invocation_names_the_temp_home(self):
        self.assert_every_carrier_states_the_temp_home(
            REQUEST_FILE_INVOCATION, REQUEST_FILE_HOME, 2
        )

    def test_every_result_file_invocation_names_the_temp_home(self):
        self.assert_every_carrier_states_the_temp_home(
            RESULT_FILE_INVOCATION, RESULT_FILE_HOME, 1
        )

    def test_from_issue_validates_artifacts_before_every_phase_advance(self):
        self.assert_ordered(self.from_issue, "validate the returned state", "artifact-budget check",
                            "compare all four metrics", "workflow-state progress")
        self.assertIn("complete with anything other than within_budget", self.from_issue)
        self.assertIn("missing or non-integer metric", self.from_issue)
        self.assertIn("checker exit 2", self.from_issue)
        self.assertIn("independently run the checker", self.from_issue)

    def test_autonomous_reports_and_ship_handoff_are_root_plus_metrics(self):
        for text in (self.auto, self.ship_handoff):
            for field in ("state", "artifact", "kind", "path", "metrics", "budget_status"):
                self.assertIn(field, text)
        self.assertIn("spec_artifact", self.ship_handoff)
        self.assertIn("plan_artifact", self.ship_handoff)
        self.assertIn('"action_id"', self.ship_handoff)
        self.assertIn(
            "`action_id` is the `issue:attempt:launch` string the acquisition "
            "envelope issued",
            normalized(self.ship_handoff),
        )
        self.assertIn("passed through verbatim", normalized(self.ship_handoff))
        self.assertIn("never carry task member paths", self.ship_handoff)
        self.assertIn("never inline artifact contents", self.auto)
        for forbidden in ("decisions:", "open_items:", "adr_paths:", "summary:"):
            self.assertNotRegex(self.auto, rf"(?m)^\s*{re.escape(forbidden)}")
            self.assertNotRegex(self.ship_handoff, rf"(?m)^\s*{re.escape(forbidden)}")
        self.assertIn("discussion_items: []", self.ship_handoff)
        self.assertIn("report_path", self.ship_handoff)
        self.assertIn("phase_reports.notes_max_characters", self.ship_handoff)
        self.assertIn("validate-report --boundary ship-handoff", self.ship_handoff)
        self.assertIn("validate-report --boundary ship-summary", self.ship_handoff)

    def test_autonomous_over_budget_reports_include_required_violations(self):
        for kind in ("design-spec", "implementation-plan"):
            complete = (
                f'{{"state":"complete","artifact":{{"kind":"{kind}"'
            )
            over = (
                f'{{"state":"decompose_required","artifact":{{"kind":"{kind}"'
            )
            self.assertIn(complete, self.auto)
            self.assertIn(over, self.auto)
        self.assertEqual(self.auto.count('"violations":["root_bytes"]'), 2)
        self.assertIn("ordered, non-empty", self.auto)
        self.assertIn("metrics, budget status, and violations are forbidden", self.auto)

    def test_sdd_report_is_exact_and_mechanically_validated(self):
        for field in ("state", "review_state", "conformance_verdict",
                      "correctness_verdict", "verification_state", "base_sha",
                      "head_sha", "detail_state", "report_path", "notes"):
            self.assertIn(field, self.sdd)
        self.assertIn("validate-report --boundary sdd", self.sdd)
        for forbidden in ("parked_findings:", "verdict_details:", "open_items:", "summary:"):
            self.assertNotRegex(self.sdd, rf"(?m)^\s*{re.escape(forbidden)}")

    def test_received_reports_cross_the_same_json_wire_seam(self):
        self.assert_ordered(self.from_issue, "received stdout bytes",
                            "validate-report --boundary producer --input -", "decode JSON")
        self.assert_ordered(self.from_issue, "validate-report --boundary sdd --input -",
                            "construct the Phase-7 handoff")
        self.assertIn("return only validated stdout bytes", self.auto)

    def test_both_plan_review_routes_revalidate_received_reports_in_the_caller(self):
        for text in (self.from_issue, self.standards_review):
            self.assertIn("Codex", text)
            self.assertIn("native", text)
            self.assertIn("validate-report --boundary producer --input -", text)
            self.assertIn("before any state access or reviewer dispatch", text)

    def test_durable_review_detail_precedes_every_removable_cleanup(self):
        self.assertIn(".superpowers/issue-delivery/", self.sdd)
        self.assert_ordered(self.sdd, "delivery-detail", "artifact-budget check",
                            "validate-report --boundary sdd", "delete this plan's workspace")
        self.assertIn(".superpowers/issue-delivery/", self.ship_review)
        self.assertIn("Minor/Discussion", self.ship_review)
        self.assert_ordered(self.ship_issue, "delivery-detail", "artifact-budget check",
                            "git worktree remove",
                            "validate-report --boundary ship-summary")
        for text in (self.sdd, self.ship_review, self.ship_issue, self.ship_handoff):
            self.assertIn("report_path", text)
            self.assertIn("keep the worktree", text)
        self.assertIn("primary worktree", self.ship_handoff)
        self.assertIn("never inline the report", self.from_issue)

    def test_terminal_review_findings_use_only_the_durable_report_path(self):
        finish = self.sdd[self.sdd.index("## Finish"):]
        severity = self.section(self.ship_review, "## Severity mapping", "##")
        self.assertNotIn("surfaced list", finish)
        self.assertNotIn("`discussion_items` return carry", severity)
        for text in (finish, severity):
            self.assertIn("`report_path`", text)
        self.assertIn("only findings transport", finish)
        self.assertIn("only terminal transport", severity)

    def test_merged_ship_summary_is_validated_only_after_cleanup(self):
        cleanup = self.section(self.ship_issue, "## Phase 8", "## Notes")
        self.assert_ordered(
            cleanup,
            "do not construct or validate a successful `merged` ship summary yet",
            "gh issue close",
            "git worktree remove",
            "Only after issue closure and worktree cleanup both succeed",
            "validate-report --boundary ship-summary",
        )
        self.assertIn("do not forge", cleanup)

    def test_review_package_failure_before_dispatch_has_no_fabricated_detail(self):
        self.assert_ordered(self.sdd, "base_sha and head_sha", "review-package",
                            "exit 2", 'detail_state: "none"', "report_path: null",
                            "validate-report --boundary sdd")
        self.assertIn("before reviewer dispatch", self.sdd)
        self.assertIn("do not dispatch", self.sdd)

    def test_unpublished_detail_keeps_readable_sources_and_forbids_cleanup(self):
        self.assert_ordered(self.sdd, "write the retained candidate", "validate-detail-input",
                            "consume canonical stdout", 'detail_state: "unpublished"',
                            "validate-report --boundary sdd", "keep the workspace")
        self.assert_ordered(self.ship_review, "write the retained candidate", "validate-detail-input",
                            "consume canonical stdout",
                            'detail_state: "unpublished"', "keep the worktree")
        for text in (self.sdd, self.ship_review, self.ship_issue):
            self.assertIn("non-empty findings", text)
            self.assertIn("do not remove", text)

    def test_phase_five_remeasures_every_artifact_it_mutates(self):
        self.assert_ordered(self.standards_review, "apply blocking fixes", "final mutation",
                            "artifact-budget check", "decompose_required")
        self.assertIn("check the spec too when its decision ledger changed", self.standards_review)
        self.assertIn("do not dispatch SDD", self.standards_review)

    def test_ship_expands_validated_plan_only_for_diff_scope_exclusion(self):
        self.assert_ordered(self.ship_issue, "artifact-budget check", "discover the plan members",
                            "diff-scope", "--artifact-path")
        self.assertIn("one argument for the plan root and each discovered member", self.ship_issue)
        self.assertIn("≤1,000 product lines", self.ship_issue)
        self.assertIn("≤20 product files", self.ship_issue)
        self.assertIn("do not put the member list in the handoff", self.ship_issue)

    def test_fixture_producer_states_supplement_behavioral_cli_cases(self):
        self.assertTrue(all(item["expected"]["producer_state"] == "complete"
                            for item in self.small_budget_fixture["artifacts"]))
        expected = {(item["kind"], item["case"]): item["expected"]["producer_state"]
                    for item in self.oversized_budget_fixture["artifacts"]}
        self.assertEqual(expected[("design-spec", "design-root-plus-one")], "decompose_required")
        self.assertEqual(expected[("implementation-plan", "plan-ninth-member")], "decompose_required")
        self.assertEqual(expected[("handoff", "handoff-root-plus-one")], "stopped")
        self.assertEqual(expected[("review-package", "review-member-plus-one")], "decompose_required")
        for text in (self.from_issue, self.auto, self.sdd):
            self.assertIn("complete", text)
            self.assertIn("within_budget", text)
            self.assertIn("contract error", text)

    def test_sdd_validates_plan_before_extracting_a_member(self):
        setup = self.section(self.sdd, "## Setup", "## Agent tiers")
        self.assert_ordered(setup, "artifact-budget check", "read the root and every indexed member")
        self.assertIn("scripts/task-brief PLAN_FILE N", self.sdd)
        self.assertIn("root path and all four metrics", self.sdd)
        self.assertIn("missing or unreadable member is a contract error", self.sdd)

    def test_sdd_review_dispatch_is_root_only(self):
        review = " ".join(self.section(
            self.sdd, "For the full-lane review:", "Template: [task-reviewer-prompt.md]"
        ).split())
        self.assertIn("plan root path and all four metrics", review)
        self.assertIn("brief and report paths plus the review-package manifest root path and all four metrics", review)
        self.assertIn("reads Global Constraints from the bounded plan root", review)
        self.assertIn("never gets a member list, shard list, artifact contents, diff contents", review)
        self.assertNotIn("global constraints copied **verbatim**", review.lower())

    def test_native_phase_5_validates_before_dispatch_and_remeasures(self):
        caller = self.section(
            self.phase_5_review_contract,
            "## Caller pre-dispatch boundary",
            "## Reviewer instructions",
        )
        self.assert_ordered(
            caller, "validate-report", "validated stdout bytes", "read `state`",
            "artifact-budget check", "reviewer dispatch",
        )
        self.assertIn("only the plan root path and four metrics", caller)
        remeasurement = self.section(
            self.phase_5_review_contract, "## Accepted-edit remeasurement", "(D5, D14)."
        )
        self.assert_ordered(
            remeasurement, "after the last write", "implementation-plan",
            "design-spec", "may advance",
        )

    def test_codex_plan_review_validates_before_packet_and_remeasures(self):
        self.assert_ordered(
            self.codex_plan_review,
            "## Caller input gate", "validate-report", "validated stdout bytes",
            "artifact-budget check", "## Build the review packet",
            "## Reviewer contract", "## Verify and disposition",
            "After the last accepted edit", "implementation-plan",
            "design-spec", "may not advance",
        )
        packet = self.section(
            self.codex_plan_review, "## Build the review packet", "## Reviewer contract"
        )
        self.assertIn("Supply no member list or plan content", packet)

    def test_preflight_worktree_deletion_requires_proof_of_disposability(self):
        self.assertNotIn("one, clean → remove it", self.from_issue)
        phase_zero = self.section(self.from_issue, "## Phase 0", "## Phase 1")
        self.assert_ordered(
            phase_zero,
            "inspect before touching",
            "unpushed commits",
            "workflow-state ledger",
            "spec/plan artifacts",
            "resume that worktree",
            "provably disposable",
        )
        self.assertIn("prefer resume", phase_zero)
        self.assertIn("stop as blocked", phase_zero)
        self.assertIn("never delete on ambiguity", self.auto)

    def test_worktrees_isolation_failure_reports_blocked_not_in_place(self):
        self.assertNotIn("say so and work in place", self.worktrees)
        self.assertIn("never silently work in place", self.worktrees)
        self.assert_ordered(
            self.worktrees,
            "creation fails",
            "Report blocked",
            "ask for direction",
        )

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

    def test_direct_auto_phase_five_rolls_to_one_fresh_implementation_owner(self):
        transfer = self.section(
            self.auto,
            "#### Mandatory transfer gate",
            "#### Fresh delegated owner",
        )
        delegated = self.section(
            self.auto,
            "#### Fresh delegated owner",
            "#### Earlier controller stop",
        )
        earlier = self.section(
            self.auto,
            "#### Earlier controller stop",
            "### Other Phase 5–7 routes",
        )
        self.assert_ordered(
            transfer,
            "dispositioned every Blocking and accepted Should-fix finding",
            "commit",
            "artifact-budget check --kind design-spec",
            "artifact-budget check --kind implementation-plan",
            "within_budget",
            "workflow-state progress",
            "next_needs_context=false",
            "artifacts_sufficient=true",
            "remainder_self_contained=true",
            "delegate",
            "exactly one fresh issue owner",
        )
        match = re.search(r"```json\n(\{.*?\})\n```", transfer, re.DOTALL)
        self.assertIsNotNone(match)
        continuation = json.loads(match.group(1))
        self.assertEqual(set(continuation), {
            "owner", "reviewed_head_sha", "spec_artifact", "plan_artifact",
        })
        self.assertEqual(set(continuation["owner"]), {
            "interface_version", "kind", "ledger_repo_root", "run_id", "issue",
            "attempt", "owner", "action_id", "launch_kind", "worktree",
            "handoff_path", "deadline_at",
        })
        self.assertEqual(continuation["owner"]["kind"], "owner")
        self.assertRegex(continuation["reviewed_head_sha"], r"^[0-9a-f]{40}$")
        artifact_fields = {"kind", "path", "metrics", "budget_status"}
        metric_fields = {
            "root_bytes", "total_bytes", "file_count", "largest_member_bytes",
        }
        for block, kind in (
            ("spec_artifact", "design-spec"),
            ("plan_artifact", "implementation-plan"),
        ):
            artifact = continuation[block]
            self.assertEqual(set(artifact), artifact_fields)
            self.assertEqual(artifact["kind"], kind)
            self.assertEqual(set(artifact["metrics"]), metric_fields)
            self.assertTrue(all(type(value) is int
                                for value in artifact["metrics"].values()))
            self.assertEqual(artifact["budget_status"], "within_budget")
        for excluded in (
            "no artifact contents", "no task-member paths", "no review transcript",
            "no conversation summary", "no alternate worktree",
            "no reconstructed lifecycle field", "no authorization flag",
        ):
            self.assertIn(excluded, transfer)
        self.assertIn("mechanical-only direct autonomous", transfer)
        self.assert_ordered(
            delegated,
            "Before reading either artifact",
            "`branchPattern` and `worktreePrefix`",
            "decimal `owner.issue`",
            "final path component",
            "binding-derived accepted branch regex",
            "`expected_branch`",
            "`git -C owner.worktree branch --show-current`",
            "equal `expected_branch`",
            "mismatch is a contract failure",
            "both roots are tracked",
        )
        self.assert_ordered(
            delegated,
            "mismatch is a contract failure",
            "current clean HEAD",
            "equal `reviewed_head_sha`",
            "both roots are tracked at that exact reviewed HEAD",
            "independently run `artifact-budget check`",
            "compare all four metrics",
            "adopt the owner envelope",
            "must not call `direct-owner`",
            "begin at Phase 6",
            "invoke `sdd`",
            "completed Phase 6",
            "remainder_self_contained=true",
            "persisted action `delegate`",
            "fresh Phase-7 ship owner",
            "must not dispatch a second issue owner",
            "completed Phase 7",
            "ledger-only remainder",
            "ledger-only bookkeeper",
            "exact `workflow-state finish` command",
            "return only the exact canonical JSON",
        )
        self.assertIn("existing mechanical Phase-6 mechanic/reviewer route", delegated)
        self.assert_ordered(
            earlier,
            "received bytes",
            "artifact-budget validate-report --boundary ship-summary",
            "relay the canonical bytes unchanged",
            "stop",
        )
        self.assertIn(
            "post-delegation action set is exactly validate, relay, and stop",
            earlier,
        )
        affirmative_permission = re.compile(
            r"\b(?:may|can|could|must|should|is allowed to|is authorized to|is permitted to)\s+(?:"
            r"invoke `sdd`|edit implementation files|reacquire|"
            r"call `direct-owner`|(?:start|create) (?:a )?new attempt|"
            r"dispatch (?:a )?second (?:replacement )?owner|"
            r"call `workflow-state finish` after delegation|"
            r"continue after (?:the )?delegated report)",
            re.IGNORECASE,
        )
        self.assertIsNone(affirmative_permission.search(earlier))
        for denial in (
            "does not invoke `sdd`", "does not edit implementation files",
            "does not reacquire or call `direct-owner`",
            "does not start or create a new attempt", "does not dispatch a second owner",
            "does not call `workflow-state finish` after delegation",
            "does not continue after the delegated report",
        ):
            self.assertIn(denial, earlier)
        self.assertIn("dispatch failure", earlier)
        self.assertIn("never permission to implement locally", earlier)

        other_start = self.auto.index("### Other Phase 5–7 routes")
        other = self.auto[other_start:]
        self.assertIn(
            "Mechanical-only module-owned direct autonomous runs are excluded from this section",
            other,
        )
        self.assertIn("mechanical-only ordering and ownership for other acquisition routes", other)

        phase_gate = self.section(
            self.from_issue,
            "## Dispatch, phase-budget and attempt-budget rules",
            "## Terminal return procedure",
        )
        self.assertIn("mandatory direct-autonomous Phase-5 rollover", phase_gate)
        self.assertIn("AUTO.md", phase_gate)
        self.assertIn("all other acquisition modes", phase_gate)
        self.assertIn("post-rollover Phase-6 and Phase-7 gates", phase_gate)
        self.assertIn("unchanged", phase_gate)

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
        identity = self.section(
            self.from_issue, "## Lifecycle identity", "## The flow"
        )
        dispatcher = self.section(
            identity, "### Dispatcher-owned acquisition",
            "### Direct autonomous acquisition",
        )
        interactive = self.section(
            identity, "### Interactive direct acquisition",
            "### Explicit durable interactive acquisition",
        )
        self.assertIn("optional lifecycle envelope", dispatcher)
        self.assertIn("all six dispatcher fields", dispatcher)
        self.assertIn("action_id", dispatcher)
        for field in ("run_id", "attempt", "owner", "worktree", "ledger_repo_root"):
            self.assertIn(field, identity)
        self.assertIn(
            "`owner`, `action_id`, and normalized `worktree` as one identity",
            normalized(identity),
        )
        self.assertIn("immutable ledger_repo_root", identity)
        self.assertIn("separate owner worktree", identity)
        self.assertIn("Every `workflow-state` command", identity)
        self.assertIn("--repo-root <ledger_repo_root>", identity)
        self.assertIn("ledger-free", interactive)
        phase_zero = self.section(self.from_issue, "## Phase 0", "## Phase 1")
        self.assertIn("lifecycle identity", phase_zero)
        self.assertIn("workflow-state finish", phase_zero)
        self.assertIn("execution failure", self.from_issue)
        phase_seven = self.section(self.from_issue, "## Phase 7", "## Notes")
        self.assert_ordered(
            phase_seven,
            "ledger_repo_root",
            "receiving the ship report",
            "workflow-state finish",
            "send the exact JSON",
        )

    def test_lifecycle_phase_one_paths_are_acquisition_mode_specific(self):
        phase_one = self.section(self.from_issue, "## Phase 1", "## Phase 2")
        self.assert_ordered(
            phase_one,
            "dispatcher-owned or direct-autonomous lifecycle envelope",
            "use its exact absolute `worktree`",
            "**Absent** from both the filesystem",
            "checked out on this issue's branch",
            "adopt it",
            "Do not re-create it, do not move it, do not reset it",
            "a different branch",
            "fail the attempt through the terminal return procedure",
            "never choose another path",
        )
        self.assertIn("fail the attempt", phase_one)
        self.assert_ordered(
            phase_one,
            "No lifecycle acquisition falls through to ordinary worktree creation",
            "ledger-free interactive direct",
            "standard `worktrees` flow",
        )

    def test_from_issue_handoff_resume_is_acquisition_mode_specific(self):
        phase_gate = self.section(
            self.from_issue, "## Dispatch, phase-budget and attempt-budget rules",
            "## Terminal return procedure",
        )
        self.assertIn("dispatcher-owned", phase_gate)
        self.assertIn("`control`", phase_gate)
        self.assertIn("returned `resume` envelope", phase_gate)
        self.assertIn("direct autonomous", phase_gate)
        self.assertIn("persisted `direct-owner` owner envelope", phase_gate)
        self.assertNotIn("workflow-state launch", phase_gate)

    def test_from_issue_standalone_modes_use_live_lifecycle_interfaces(self):
        identity = self.section(
            self.from_issue, "## Lifecycle identity", "## The flow"
        )
        interactive = self.section(
            identity, "### Interactive direct acquisition",
            "### Explicit durable interactive acquisition",
        )
        durable = self.section(
            identity, "### Explicit durable interactive acquisition",
            "The `workflow-state` executable",
        )
        self.assertIn("ledger-free", interactive)
        self.assert_ordered(
            durable,
            "explicitly requests durable standalone orchestration",
            "workflow-state init-run", "bounded `requirements`",
            "max_parallel: 1", "workflow-state control", "first `spawn` envelope",
            "adopt", "do not spawn another owner",
        )
        self.assertIn("fail loudly", durable)

    def test_direct_auto_acquires_only_through_direct_owner(self):
        identity = self.section(
            self.from_issue, "## Lifecycle identity", "## The flow"
        )
        direct = self.section(
            identity, "### Direct autonomous acquisition",
            "### Explicit durable interactive acquisition",
        )
        self.assert_ordered(
            identity,
            "### Dispatcher-owned acquisition",
            "### Direct autonomous acquisition",
            "### Interactive direct acquisition",
            "### Explicit durable interactive acquisition",
        )
        self.assertIn("workflow-state direct-owner", direct)
        self.assertIn("--repo-root <ledger_repo_root>", direct)
        self.assertIn("--request-file <absolute-json-path>", direct)
        self.assertNotIn("workflow-state init-run", direct)
        self.assertNotIn("workflow-state control", direct)
        self.assertNotIn("wait envelope", direct)

    def test_direct_auto_observe_owner_terminal_loop_is_closed(self):
        identity = self.section(
            self.from_issue, "## Lifecycle identity", "## The flow"
        )
        direct = self.section(
            identity, "### Direct autonomous acquisition",
            "### Explicit durable interactive acquisition",
        )
        self.assert_ordered(
            direct,
            "kind: observe",
            "tracker",
            "recorded_worktree",
            "candidate_worktree",
            "retain every fact previously requested during this acquisition",
            "carry all collected facts into each later strict request",
            "never send a fact kind before the helper requests it",
            "call `direct-owner` again",
            "kind: owner",
            "adopt",
            "kind: terminal",
            "return",
        )
        self.assertIn(
            "every observation kind the helper has requested at least once during this acquisition",
            direct,
        )
        self.assertIn(
            "keep an observation kind `null` until the helper requests it",
            direct,
        )
        self.assertNotIn("only observations requested in the current round", direct)
        for field in (
            "ledger_repo_root", "run_id", "issue", "attempt", "owner",
            "action_id", "launch_kind", "worktree", "handoff_path",
            "deadline_at",
        ):
            self.assertIn(field, direct)
        self.assertIn("unknown", direct)
        self.assertIn("fail loudly", direct)
        self.assertIn("no waiter", direct)

    def test_direct_auto_authorizations_are_explicit_and_never_inferred(self):
        combined = self.from_issue + "\n" + self.auto
        for flag in ("new_run", "owner_unavailable"):
            self.assertIn(flag, self.from_issue)
            self.assertIn(flag, self.auto)
        self.assertIn("both flags", combined)
        self.assertIn("false", combined)
        for forbidden_inference in (
            "restart", "missing process handle", "silence", "active ledger",
            "terminal replay", "reopened tracker", "desire to continue",
        ):
            self.assertIn(forbidden_inference, combined)
        self.assertIn("current user instruction explicitly authorizes", combined)
        self.assertIn(
            "resuming a `suspended` attempt requires neither `new_run` nor "
            "`owner_unavailable`",
            self.auto,
        )

    def test_adjacent_from_issue_acquisition_modes_remain_unchanged(self):
        identity = self.section(
            self.from_issue, "## Lifecycle identity", "## The flow"
        )
        dispatcher = self.section(
            identity, "### Dispatcher-owned acquisition",
            "### Direct autonomous acquisition",
        )
        interactive = self.section(
            identity, "### Interactive direct acquisition",
            "### Explicit durable interactive acquisition",
        )
        durable = self.section(
            identity, "### Explicit durable interactive acquisition",
            "The `workflow-state` executable",
        )
        self.assertIn("adopt", dispatcher)
        self.assertNotIn("direct-owner", dispatcher)
        self.assertIn("ledger-free", interactive)
        self.assertNotIn("direct-owner", interactive)
        self.assert_ordered(
            durable, "workflow-state init-run", "bounded `requirements`",
            "max_parallel: 1", "workflow-state control", "first `spawn` envelope",
        )
        self.assertNotIn("direct-owner", durable)

    def test_from_issue_routes_a_deadline_rejected_progress_to_the_suspension_procedure(self):
        # A progress call rejected past the attempt budget's deadline is now an
        # environmental interruption, not a semantic verdict: the reaper demotes
        # the expired attempt to suspended(unknown), so the owner follows the
        # suspension procedure (print the re-entry line and stop) rather than
        # writing a terminal finish, which the helper would reject on a
        # non-active attempt.
        self.assert_ordered(
            self.from_issue,
            "Obey the returned action exactly",
            "attempt budget's deadline has passed",
            "cannot record progress at or after attempt deadline",
            "progress requires an active attempt",
            "suspension procedure",
            "Persistence precedes notification",
        )

    def test_authorization_truth_is_single_and_shared(self):
        sentence = (
            "Standing authorization exists exactly where the lifecycle guard grants it: "
            "pushing a non-default branch, opening a PR to the default branch, and the "
            "guarded merge, in fagenorn-owned repositories; everywhere else these commands "
            "stay per-action gated — suspend with blocked_on=human_gate and print the "
            "re-entry line instead of dying at the prompt."
        )
        self.assertIn(sentence, self.ship_issue)
        self.assertIn(sentence, self.from_issue)
        self.assertNotIn("Don't re-prompt for `git push`", self.ship_issue)
        self.assertNotIn(
            "Push, PR open/merge, force-push, and hook bypass stay per-action gated.",
            self.from_issue,
        )

    def test_suspension_procedure_pins_verb_line_and_distinction(self):
        suspension = self.section(
            self.from_issue, "## Suspension procedure", "## Phase 0"
        )
        self.assertIn(
            "workflow-state suspend --repo-root <ledger_repo_root> --run-id <run-id> "
            "--now <utc> --issue <n> --attempt <k> --blocked-on <value>",
            suspension,
        )
        self.assertIn(
            "Suspended (blocked_on=<value>). Resume: <reentry from the envelope>",
            suspension,
        )
        self.assertIn(
            "Handoff is the deliberate context rollover with a handoff document; "
            "suspension is the environmental pause with none.",
            suspension,
        )
        self.assertIn("no `finish` call", suspension)
        self.assert_ordered(
            suspension, "workflow-state suspend", "Suspended (blocked_on=", "stop",
        )

    def test_terminal_replay_relays_reentry(self):
        terminal = self.section(
            self.from_issue,
            "## Terminal return procedure",
            "## Suspension procedure",
        )
        self.assertIn("`reentry`", terminal)
        self.assertIn("verbatim on its own line", terminal)

    def test_orchestrate_reuses_nonfinal_runs(self):
        bootstrap = self.section(
            self.orchestrate, "## 2. Bootstrap and observe", "## 3. Decide"
        )
        self.assert_ordered(
            bootstrap,
            "existing run whose state covers the same issue set",
            "non-final attempt",
            "reuse that run id",
            "workflow-state init-run",
        )
        self.assertNotRegex(
            self.orchestrate, r"(?i)mint (?:a )?(?:fresh |new )?dated run"
        )

    def test_no_deadline_less_wait_is_armed(self):
        self.assertIn(
            "control never returns a deadline-less wait; every wait carries deadline_at, "
            "and when nothing can proceed without a human, control returns finalize instead.",
            self.orchestrate,
        )
        self.assertNotIn("and optional deadline", self.orchestrate)

    def test_orchestrate_evals_grade_control_and_reject_retired_policy(self):
        expected = " ".join(
            case["expected_output"] for case in self.orchestrate_evals["evals"]
        )
        for anchor in (
            "workflow-state init-run", "action_id", "recorded_worktree",
            "workflow-state control",
            "normalized", "spawn", "resume", "retry", "wait", "finalize",
            "bounded summaries", "unknown action kind", "cancel the old wait",
            "stale wake ID", "already-exited wait", "no wake is installed",
            "unexpected cancellation failure", "restore the old wait ID/handle",
            "do not arm replacement", "never pair the new wait ID with the old handle",
            "retry replacement", "reap inherited detached wait observers",
        ):
            self.assertIn(anchor, expected)
        for retired in ("workflow-state launch", "workflow-state reconcile"):
            self.assertNotIn(retired, expected)
        for retired_policy_anchor in (
            "resume before fresh", "attempts 1 and 2", "permits a retry",
            "result_source", "earliest armed deadline", "occupied slots",
            "run is drained",
        ):
            self.assertNotIn(retired_policy_anchor, expected)

    def test_auto_mode_never_skips_durable_checkpoints_or_terminal_writes(self):
        checkpoint_contract = self.section(
            self.auto, "## The self-answer pattern", "## When *not* to auto-resolve"
        )
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
        self.assertNotIn(
            "For every terminal result, call `workflow-state finish`",
            checkpoint_contract,
        )
        for relay_exception in (
            "successful direct Phase-5 relay",
            "delegated fresh owner has already persisted",
            "must not call `workflow-state finish` again",
            "delegated-owner dispatch failure",
        ):
            self.assertIn(relay_exception, checkpoint_contract)

    def test_handoff_supports_safe_durable_destination_and_temp_default(self):
        self.assertIn(".superpowers/workflows/<run-id>/handoffs/", self.handoff)
        self.assertIn("caller-provided destination", self.handoff)
        self.assertIn("symlink", self.handoff)
        self.assertIn("path escape", self.handoff)
        self.assertIn("missing destination", self.handoff)
        self.assertIn("created atomically", self.handoff)
        self.assertIn("exclusive atomic operation", self.handoff)
        self.assertIn("leaf appeared concurrently", self.handoff)
        self.assertIn("never overwrite that race", self.handoff)
        self.assert_ordered(
            self.handoff,
            "existing regular destination",
            "read it before writing",
            "atomically replace",
        )
        self.assertIn("non-symlink parent path", self.handoff)
        self.assertIn("mktemp", self.handoff)
        self.assertIn("Do not duplicate lifecycle JSON", self.handoff)

    def test_diff_review_scopes_oversized_ranges_and_discloses_coverage(self):
        # Whitespace-normalized: these are wrapped prose contracts, so line
        # breaks must not be part of what is pinned. The blockquote markers go
        # first — without that, a naive split() leaves a stray ">" inside the
        # coverage sentence and no fragment spanning its line wrap can match.
        contract = " ".join(self.diff_review.replace("\n> ", "\n").split())
        for fragment in (
            "resolve policy, capability pre-flight, packet by paths",
            "the size pre-flight below",
            "`~/.agents/bin/diff-scope`",
            "--artifact-path <specDir> --artifact-path <planDir>",
            "--format json",
            "`.claude/specs` and `.claude/plans`",
            "`product.changed_files`",
            "`files[].path`",
            "`files[].changed_lines`",
            "`product.changed_lines` and `excluded` are deliberately not read",
            "`changed_files > 20` scopes the packet, `changed_files == 20` does not",
            "no filtering, no re-ranking",
            # Cardinality and selection order — acceptance criteria 3 and 4 rest
            # on these two, and "no filtering, no re-ranking" pins neither.
            "taken as the first 20 entries in the emitted order",
            "ranks churn descending with a raw-path-bytes tie-break",
            "the same range always yields the same 20 paths",
            "selected as the highest-churn files",
            "yields no measurement — never a failure",
            "adds no fourth failure class",
            "never spends the one-time native fallback and never triggers a retry",
            "receives the same packet, item 7 and coverage sentence intact",
            "`full` | `scoped: <N> of <M> product files` | `unmeasured`",
            "This is a scoped review:",
            "do not treat their absence from the list as evidence they are clean",
            # The bound is on input, not only on grading (D9): item 4 retains
            # bounded coverage evidence while item 7 owns diff collection.
            "Under budget — or unmeasured — the packet is exactly the six items above",
            "Over budget it differs in exactly three places and nowhere else",
            "Item 4 changes the manifest's use, not its presence",
            "manifest root path and all four metrics as truthful range-coverage evidence",
            "do not read its shards",
            "every unscoped reviewer validate that same manifest and read all shards "
            "once in manifest order",
            "Item 7 exists only when scoped",
            "one bounded read per listed path",
            "treat that set as the whole of the range under review",
            # The argv protocol for item 7: `diff-scope` preserves arbitrary Git
            # path bytes, so paths interpolated into one shell command line split
            # or are reinterpreted as pathspec magic.
            "**one invocation per path**",
            "**single literal argument after `--`**",
            "never shell-joined with the other listed paths into one command line",
            "pathspec magic disabled by the `:(literal)` prefix",
            "one focused check per named risk",
            # Scoping bounds what is graded, not what may be consulted (D13), so
            # the coverage sentence and the cross-file allowance need the
            # boundary that tells them apart.
            "Every finding you report must be anchored in a listed file",
            "a defect lying wholly within an unlisted file is outside this pass "
            "and is not reported",
            "legal and reportable, as long as it is anchored in a listed file",
            "it never embeds per-file diffs",
            "scoped to <N> of <M> product files;",
            "A scoped review may not use the bare",
            # Item 7's listing is line-delimited, so it carries every byte class
            # `diff-scope` can emit except an embedded newline. That one case
            # folds into the existing no-measurement degrade rather than
            # shortening the subset: a silently dropped path would still be
            # disclosed as `<N>` of `<M>` and read as covered.
            "selects a path this operation cannot represent in item 7's listing",
            "has no unambiguous one-per-line form",
            "That case does not scope",
            "a silently shorter list still discloses `<N>` of `<M>` and reads as "
            "covered",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, contract)

        # The capability check is named as running first, and the size
        # pre-flight is defined before the packet it changes.
        self.assertIn(
            "capability pre-flight and runs first", contract
        )
        self.assert_ordered(
            contract,
            "## Size pre-flight",
            "## Packet",
            "### When the range is over budget",
            "## Reviewer output contract",
            "## Disposition",
        )
        # The header no longer claims the shared file owns *the* pre-flight.
        self.assertNotIn("resolve policy, pre-flight, packet by paths", contract)

        # SKILL.md is narrowed in the same breath, or the two contracts
        # contradict each other (D12).
        self.assertIn(
            "Capability pre-flight first, one sub-second call", self.collaboration
        )
        self.assertNotIn(
            "Pre-flight first, one sub-second call", self.collaboration
        )
        self.assertIn("skip the capability pre-flight", self.collaboration)
        self.assertIn(
            "an additional pre-flight of its own in its reference file",
            self.collaboration,
        )

    def test_diff_review_makes_the_scoped_coverage_disclosure_mandatory(self):
        # Review-package transport stays bounded even when this axis scopes its
        # evidence to selected product paths.
        contract = " ".join(self.diff_review.replace("\n> ", "\n").split())
        for fragment in (
            "manifest root path and all four metrics",
            "range-coverage evidence",
            "do not read its shards",
            "one invocation per selected path",
            "`git diff <base>..<head> -- ':(literal)<path>'`",
        ):
            with self.subTest(review_package_fragment=fragment):
                self.assertIn(fragment, contract)

        # The omission case can only be pinned here. `agent-evidence.py` sees a
        # result, never the packet that produced it, so it cannot tell a scoped
        # dispatch that dropped its coverage from an unscoped one — its own test
        # covers placement only. The obligation therefore has to be stated in
        # DIFF-REVIEW.md, and this is what holds it there.
        contract = " ".join(self.diff_review.replace("\n> ", "\n").split())
        for fragment in (
            "The coverage disclosure is mandatory on a scoped dispatch",
            "a requirement, not a preference",
            "does not satisfy this operation's output contract",
            "never sees whether the packet was scoped",
            "a bare `**Correctness:** Clean` returned from a scoped dispatch "
            "validates",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, contract)

    def test_sdd_review_paths_use_validated_manifest_packages(self):
        documents = {
            "task loop": self.sdd,
            "fix loop": (SDD_DIR / "fix-loop.md").read_text(encoding="utf-8"),
            "final review": (SDD_DIR / "final-review.md").read_text(encoding="utf-8"),
            "task reviewer": (SDD_DIR / "task-reviewer-prompt.md").read_text(encoding="utf-8"),
            "re-reviewer": (SDD_DIR / "re-review-prompt.md").read_text(encoding="utf-8"),
            "conformance": (SDD_DIR / "conformance-reviewer-prompt.md").read_text(encoding="utf-8"),
            "correctness": (SDD_DIR / "correctness-reviewer-prompt.md").read_text(encoding="utf-8"),
        }
        for name, raw in documents.items():
            text = " ".join(raw.split())
            with self.subTest(document=name):
                self.assertIn("manifest", text)
                self.assertIn("root path and all four metrics", text)
                self.assertIn("manifest order", text)
                self.assertIn("unreadable", text)

    def test_sdd_generator_stops_are_decided_before_review_dispatch(self):
        for name, path in (
            ("task loop", SDD),
            ("fix loop", SDD_DIR / "fix-loop.md"),
            ("final review", SDD_DIR / "final-review.md"),
        ):
            text = " ".join(path.read_text(encoding="utf-8").split())
            with self.subTest(document=name):
                self.assert_ordered(
                    text,
                    "artifact-budget validate-report --boundary producer --input -",
                    "exit 3",
                    "decompose_required",
                    "no reviewer",
                    "exit 2",
                    "failed",
                    "dispatch",
                )

    def test_correctness_rubric_discloses_scope_only_when_the_packet_says_so(self):
        rubric = (SDD_DIR / "correctness-reviewer-prompt.md").read_text(
            encoding="utf-8"
        )
        # Stop at the Placeholders paragraph: it sits outside the fenced prompt
        # and legitimately names Codex, so including it would make the
        # reviewer-agnostic assertion below unfalsifiable.
        output_format = rubric[
            rubric.index("## Output Format") : rubric.index("**Placeholders:**")
        ]
        # The collection branch sits earlier, in its own section.
        diff_under_review = rubric[
            rubric.index("## Diff Under Review") : rubric.index("## What to Check")
        ]
        for fragment in (
            "When the packet supplied to you states the review is scoped",
            "scoped to <N> of <M> product files;",
            "never between the verdict word and the dash",
            "When the packet says nothing about scoping, write the verdict exactly",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, " ".join(output_format.split()))
        # The scoped packet bounds what is fetched, not only what is graded
        # (D9), while unscoped review consumes the complete manifest.
        for fragment in (
            "Read the strict manifest",
            "For an unscoped review, read every shard exactly once in manifest order",
            "When the packet states the review is scoped and lists the paths under review",
            "do not read its shards",
            "those listed paths are the whole of the range to fetch",
            "`git diff [MERGE_BASE_SHA]..[HEAD_SHA] -- ':(literal)<path>'` once per "
            "listed path and fetch nothing wider",
            # The named-risk carve-out survives scoping untouched (D13). Pinned
            # whitespace-normalized: inserting the clause above re-wraps this
            # paragraph, and the wrap is not the contract — the words are.
            "one focused check per named risk, named in your report.",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, " ".join(diff_under_review.split()))
        # Reviewer-agnostic: both clauses key off the packet, not the reader (D11).
        for reader in ("Codex", "Claude", "native"):
            with self.subTest(reader=reader):
                self.assertNotIn(reader, output_format)
                self.assertNotIn(reader, diff_under_review)
        # The Placeholders paragraph tells a packet builder that the manifest
        # remains coverage evidence while selected paths are the only diff reads.
        placeholders = " ".join(rubric[rubric.index("**Placeholders:**") :].split())
        for fragment in (
            "manifest root path and all four metrics",
            "On a scoped dispatch they remain range-coverage evidence",
            "do not read its shards",
            "fetch the selected literal paths once each",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, placeholders)

    def test_correctness_rubric_pins_the_scoped_fetch_quoting_protocol(self):
        # D9's argv protocol has to land in the rubric, not only in
        # DIFF-REVIEW.md item 7. Mirrored wording keeps the selected-path
        # collection seam from drifting.
        rubric = (SDD_DIR / "correctness-reviewer-prompt.md").read_text(
            encoding="utf-8"
        )
        branch = " ".join(
            rubric[
                rubric.index("When the packet states the") : rubric.index(
                    "Inspect code outside the diff"
                )
            ].split()
        )
        for fragment in (
            "one invocation per path",
            "the path passed as a single literal argument after `--`",
            "never shell-joined with the other listed paths into one command line",
            "pathspec magic disabled by the `:(literal)` prefix",
            # Why the protocol exists: the listed paths carry raw Git bytes.
            "a space, a newline, a non-UTF-8 byte, or a leading `:`",
            "treated as anything but one literal argument it splits or is "
            "reinterpreted",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, branch)
        # No unquoted interpolation survives anywhere in the branch.
        self.assertNotIn("[HEAD_SHA] -- <path>", branch)
        # The same wording, verbatim, in DIFF-REVIEW.md item 7 (whitespace
        # normalized there too, since both are wrapped prose).
        packet = " ".join(self.diff_review.split())
        for fragment in (
            "never shell-joined with the other listed paths into one command line",
            "pathspec magic disabled by the `:(literal)` prefix",
        ):
            with self.subTest(mirror=fragment):
                self.assertIn(fragment, packet)

    def test_collaboration_requires_fresh_validated_bridge_evidence(self):
        # The certification block lives in CERTIFICATION.md, referenced from
        # SKILL.md's Launch section.
        self.assertIn("CERTIFICATION.md", self.collaboration)
        evidence = " ".join(self.certification.split())
        for fragment in (
            "`schema_version`",
            "`bridge-smoke`",
            "`skill`",
            "`agent`",
            "`plugin`",
            "`started_at`",
            "plan-review",
            "diff-review",
            "`direct`",
            "`agent_mediated`",
            "agent-evidence bridge",
            "Reject stale",
            "direct-only evidence cannot certify",
            "immutable deployment receipt",
            "authoritative deployed paths",
            "assigned session ID",
            "immutable session envelope",
            "same assigned session ID",
            "actual `started_at`",
            "consumes both",
            "loaded revisions match the deployment receipt",
            "absent or mismatched receipt or envelope rejects certification",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, evidence)
        self.assert_ordered(
            evidence,
            "Deploy the candidate",
            "immutable deployment receipt",
            "At actual launch",
            "immutable session envelope",
            "externally started fresh Claude session",
        )
        self.assert_ordered(
            evidence,
            "exactly one `plan-review`",
            "exactly one `diff-review`",
        )
        self.assertIn("Keep `agent_mediated` distinct from `direct`", evidence)
        self.assert_ordered(evidence, "terminal failure", "native fallback")
        self.assert_ordered(
            evidence,
            "agent-evidence bridge <artifact.json>",
            "exits 0",
            "call the bridge current",
        )

    def test_codex_collaboration_dispatch_carries_operation_envelope(self):
        launch = self.section(
            self.collaboration,
            "Build the operation's packet",
            "Parallel reviews are valid.",
        )
        self.assertIn("first two lines", launch)
        self.assertIn("`WORKTREE_ROOT: <absolute worktree root>`", launch)
        self.assertIn("`REVIEW_OPERATION: <plan-review|diff-review>`", launch)
        self.assert_ordered(launch, "WORKTREE_ROOT:", "REVIEW_OPERATION:", "Launch mechanics")

    def test_codex_collaboration_states_a_per_operation_wall_clock(self):
        # A deliberate second copy of the runtime's per-operation budget: callers
        # schedule around the number and prose cannot be derived from a patch, so
        # the copy is pinned here instead (D8).
        # Whitespace-normalized like the other wrapped-prose contracts in this
        # module: line breaks must not be part of what is pinned, and the
        # negative guards below only bite on normalized text — a retired figure
        # that came back across a line wrap (`~14\nmin`) would otherwise slip
        # past the very check that exists to catch it.
        launch = " ".join(
            self.section(
                self.collaboration,
                "Build the operation's packet",
                "Parallel reviews are valid.",
            ).split()
        )
        collaboration = " ".join(self.collaboration.split())
        self.assertIn("roughly 28 minutes of wall clock for `plan-review`", launch)
        self.assertIn("roughly 14 minutes for `diff-review`", launch)
        for stale in ("~14 min", "~15 min"):
            with self.subTest(stale=stale, doc="SKILL.md"):
                self.assertNotIn(stale, collaboration)
        # The bridge's own wait is wider than either budget, so the caller is
        # given that figure too (D8/D15, D20). Pin the arithmetic rather than
        # the literal: the total is the wait count times the per-call bound, so
        # retuning one number without the others goes red instead of shipping a
        # sentence that no longer adds up.
        bounded = re.search(
            r"wait is uniform and wider than either budget: it returns "
            r"`CODEX_REVIEW_FAILURE` only after roughly (\d+) s of bounded "
            r"waiting[^.]*four bounded (\d+) s calls",
            launch,
        )
        self.assertIsNotNone(bounded, launch)
        self.assertEqual(int(bounded.group(1)), 4 * int(bounded.group(2)))
        # Restated once as the figure to plan against — and it must be the same
        # figure the sentence above derived.
        restated = re.search(r"plan for the ~(\d+) s bounded-wait figure", launch)
        self.assertIsNotNone(restated, launch)
        self.assertEqual(restated.group(1), bounded.group(1))
        # It bounds the bridge's waiting, not the hold: each of those four
        # waits sits under a wider outer tool cap, so the total is never a
        # guaranteed ceiling on how long a caller can be held (D20).
        self.assertNotIn("the worst case you can be held for", collaboration)
        # The eval grades a model against this same number; unpinned, it would
        # keep grading against a figure the skill no longer states (D15). JSON
        # cannot carry a raw newline inside a string, so the wrap arrives as the
        # two-character escape `\n` — collapse that first, then whitespace.
        evals = " ".join(
            json.dumps(self.codex_collaboration_evals).replace("\\n", " ").split()
        )
        self.assertIn("~28 min of external wall clock", evals)
        self.assertIn("~28 minutes for plan-review", evals)
        self.assertNotIn("~15 min", evals)

    def test_codex_collaboration_never_reports_sandbox_limits_as_findings(self):
        # The rule lives in the packet-borne shared rules, not in the Launch
        # paragraph, because only these bullets travel to the reviewer (D14).
        # Whitespace-normalized for the same reason as above: every fragment
        # here is wrapped prose, so a reflow must not decide the verdict.
        rules = " ".join(
            self.section(
                self.collaboration,
                "## Read-only rules (both operations)",
                "## Launch",
            ).split()
        )
        self.assert_ordered(
            rules,
            "limitation of your own execution environment is never a finding",
            "denies every write",
            "could not verify",
            "unresolved unknowns",
            "still reportable",
            "anchor it in the artifact",
        )
        # Stop provoking it as well as prohibiting it: neither packet may hand a
        # read-only reviewer commands that read as instructions (D7). The label
        # has to sit on the enumerated packet item itself, so each assertion is
        # scoped to that document's packet list — whole-document, the phrase
        # could drift anywhere in the file and still pass the very check that
        # exists to keep it attached to what the reviewer receives.
        plan_packet = " ".join(
            self.section(
                self.codex_plan_review,
                "## Build the review packet",
                "## Reviewer contract",
            ).split()
        )
        diff_packet = " ".join(
            self.section(
                self.diff_review,
                "## Packet",
                "### When the range is over budget",
            ).split()
        )
        for name, packet in (
            ("PLAN-REVIEW.md", plan_packet),
            ("DIFF-REVIEW.md", diff_packet),
        ):
            with self.subTest(packet=name):
                self.assertIn("not a request to execute anything", packet)
        self.assertIn("so the reviewer need not re-measure them", plan_packet)

    def test_degradation_gate_delegates_counting_and_carries_the_retuned_boundary(self):
        # The gate states a policy and calls the helper; the accounting itself
        # lives in diff-scope.py and is not restated here.
        gate = self.section(
            self.ship_issue,
            "**Pick the path first.**",
            "**Merge-delta check (degraded path).**",
        )
        for fragment in (
            GATE_LINE_BOUNDARY,
            GATE_FILE_BOUNDARY,
            # the whole invocation, not its pieces: a gate that named only
            # <spec_path> would satisfy a bare "--artifact-path" check while
            # under-naming this run's artifacts and inflating the count (D3).
            "diff-scope $BASE_SHA..$HEAD_SHA --format text"
            " --artifact-path <spec_path> --artifact-path <plan_path>",
            "No measurement",
            "is not a small diff",
            "a historical artifact that is itself the requested product still counts",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, gate)
        for absent in ("--numstat", "400", "--root"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, gate)
        # Each anchor carries its prerequisite's polarity: bare "manual conflict
        # escalation" / "`risky` label" would still match a gate that demanded
        # the opposite condition, so an inverted prerequisite would pass.
        self.assert_ordered(
            gate,
            "`review_state` is `clean`",
            "needed no manual conflict escalation",
            GATE_LINE_BOUNDARY,
            "does NOT carry the `risky` label",
            "`review.criticalPaths` glob",
        )

    def test_ship_issue_eval_restates_the_gate_boundary_it_grades(self):
        # Eval 1 grades a whole phase walk; its one degradation clause must
        # quote the same boundary the skill states, or a graded walk can be
        # "correct" against a number the skill no longer carries.
        expected = next(
            case for case in self.ship_issue_evals["evals"] if case["id"] == 1
        )["expected_output"]
        # The delegation is pinned as a whole affirmative clause: a bare
        # "diff-scope" token also matches a clause saying the boundary is *not*
        # measured with the helper, which is the inversion this test guards.
        for fragment in (
            GATE_LINE_BOUNDARY,
            GATE_FILE_BOUNDARY,
            f"the diff is small ({GATE_LINE_BOUNDARY} / {GATE_FILE_BOUNDARY},"
            " measured with `diff-scope` rather than hand-counted numstat"
            " arithmetic)",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, expected)
        self.assertNotIn("≤400", expected)

    def test_ship_issue_merge_is_bound_to_the_resolved_repository(self):
        optional_subject = (
            'gh pr merge <pr-num> --repo <repoSlug> --merge '
            '[--subject "<rendered mergeSubjectTemplate>"] --delete-branch'
        )
        rendered_subject = (
            'gh pr merge <pr-num> --repo <repoSlug> --merge '
            '--subject "<rendered mergeSubjectTemplate>" --delete-branch'
        )
        expected_occurrences = [
            "7. Merge                   → "
            f"{optional_subject} (true merge commit)",
            "In a qualifying repository this skill IS that chain: `git push`, "
            "`gh pr create`, "
            f"`{optional_subject}`, branch delete, and worktree remove need no "
            "re-prompt; pause only where a phase says to.",
            rendered_subject,
        ]
        occurrences = [
            line.strip()
            for line in self.ship_issue.splitlines()
            if "gh pr merge" in line
        ]
        self.assertEqual(expected_occurrences, occurrences)

        phase = self.section(self.ship_issue, "## Phase 7 — Merge", "## Phase 8 — Cleanup")
        phase_lines = [line.strip() for line in phase.splitlines()]
        self.assertIn(rendered_subject, phase_lines)
        guard_and_fallback = (
            "Use the `repoSlug` binding resolved in Phase 0. Build the subject "
            "from `mergeSubjectTemplate` (substituting "
            "`<feature>`/`<desc>`/`<num>`/`<integrationBranch>`). Emit the "
            "subject form only when the rendered result is nonempty and "
            "representable by D18's quoted-subject grammar: it contains none "
            "of double quote, dollar, backtick, backslash, NUL, LF, or CR; "
            "otherwise omit `--subject` and its value and let the forge default "
            "stand. Never pass `--no-ff` (rejected by recent `gh`; `--merge` "
            "already produces a true merge commit)."
        )
        self.assertIn(guard_and_fallback, phase_lines)

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

    def test_ship_issue_evals_expect_the_reviewed_tip_check(self):
        evals = {case["id"]: case for case in self.ship_issue_evals["evals"]}
        phase_walk = normalized(evals[1]["expected_output"])
        # The eval is the behavioural spec a graded run is scored against; left
        # naming live `git rev-parse HEAD` it would fail a correct run and pass
        # the defect this issue removes.
        self.assertNotIn("headRefOid` against `git rev-parse HEAD`", phase_walk)
        self.assert_ordered(phase_walk, "headRefOid", "the reviewed `HEAD_SHA`",
                            "unreviewed commits")
        # D23: the same reasoning applied to the guard -- eval 1's graded Phase-4
        # walk must require `check-launch` before each of its two forge writes,
        # or a run that omits the guard entirely still scores as a pass.
        self.assertIn("check-launch", phase_walk)
        self.assertIn("`## Launch guard`", phase_walk)
        self.assert_ordered(phase_walk, "check-launch", "git push -u",
                            "check-launch", "gh pr create")
        apply_push = normalized(evals[2]["expected_output"])
        # Phase 5 still verifies its own push against live HEAD -- that is the
        # committed-and-pushed check, not a statement about what was reviewed --
        # but it re-fixes the reviewed value, and Phase 6 does not repeat it.
        self.assertIn("re-fix `HEAD_SHA`", apply_push)
        self.assertNotIn("repeats the headRefOid equality check", apply_push)
        self.assertIn("the reviewed `HEAD_SHA`", apply_push)

    def test_ship_owner_reads_the_ledger_but_never_writes_it(self):
        # AC3's invariant, previously unpinned. The read-only exception is named
        # so a reader cannot take the sentence as a ban on consulting the ledger.
        self.assertIn(
            "A fresh ship owner never writes workflow-state itself; the "
            "read-only `check-launch` query of `## Launch guard` is the one "
            "ledger call it makes.",
            normalized(self.ship_issue),
        )

    def test_phase0_size_note_delegates_counting_to_diff_scope(self):
        # Issues #21-#22 made diff-scope the accounting authority and retired the
        # hand-counted numstat arithmetic; this note is the only restatement of
        # the C4 artifact carve-out in any skill, so it is where that drift hid.
        note = " ".join(self.investigate.split())
        for fragment in (
            # Whole affirmative clauses, not a bare "diff-scope" token: a bare
            # token also matches a clause saying the counting is *not* delegated
            # to the helper, which is the inversion this test guards.
            "`diff-scope` is the accounting authority",
            "measure, never hand-count",
            # Both directions of the carve-out: this run's artifacts are named
            # one file at a time, and the directories themselves never are.
            "one `--artifact-path` per file",
            "never `<specDir>`/`<planDir>` themselves",
            "still count",
            # The estimate/count split: Phase 0 has no range, so its number is an
            # estimate; the helper is authoritative only once a range exists.
            # Collapsing these two moments is the defect issue 32 fixed.
            "the Phase-0 number is an *estimate*",
            "Once the branch has a range",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, note)
        # The retired tool must not survive anywhere in the file, and the gate's
        # two boundaries stay spelled once, in ship-issue's Phase-5 gate: this
        # line states the policy and points there rather than restating numbers.
        for absent in ("numstat", "1,000", "≤20"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, note)

    def test_helper_binaries_resolve_from_bare_names(self):
        # Skills invoke workflow-state/agent-evidence by bare name. The Nix
        # module must put ~/.agents/bin on PATH, and each contract must anchor
        # the full path as fallback for shells that skip profile init.
        nix_module = (
            REPO_ROOT / "home/common/agent-skills/default.nix"
        ).read_text(encoding="utf-8")
        self.assertIn('home.sessionPath = [ "$HOME/.agents/bin" ]', nix_module)
        for name, text in (("from-issue", self.from_issue), ("orchestrate", self.orchestrate),
                           ("ship-issue", self.ship_issue)):
            with self.subTest(skill=name):
                self.assertIn("~/.agents/bin/workflow-state", text)
        for name, text in (("research", self.research), ("certification", self.certification)):
            with self.subTest(skill=name):
                self.assertIn("~/.agents/bin/agent-evidence", text)
        with self.subTest(skill="ship-issue"):
            self.assertIn("~/.agents/bin/diff-scope", self.ship_issue)
        # ship-issue's Phase-8 detail producer lives in the sdd skill tree but
        # is consumed by bare name from outside that skill, so it must be
        # exposed in ~/.agents/bin — together with the sdd-workspace sibling it
        # resolves via Path(__file__).with_name.
        for entry in ('".agents/bin/review-package"', '".agents/bin/sdd-workspace"'):
            with self.subTest(entry=entry):
                self.assertIn(entry, nix_module)
        with self.subTest(skill="ship-issue detail producer"):
            self.assertIn("~/.agents/bin/review-package", self.ship_issue)

    def test_research_requires_corroborated_validated_observations(self):
        heading = "## Live availability and blocking evidence"
        evidence = " ".join(self.research[self.research.index(heading) :].split())
        for fragment in (
            "`research-observations`",
            "observation ID",
            "execution ID",
            "`observed_at`",
            "source identity",
            "`outcome`",
            "transient",
            "standing",
            "two independent timepoints",
            "follow-up",
            "agent-evidence research",
            "same Markdown findings file",
            "retain no second project artifact",
            "retain no temporary input as a second artifact",
            "exact `{file_path, key_facts[]}` return shape",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, evidence)
        self.assert_ordered(
            evidence,
            "`transient`",
            "reference exactly one observation ID",
            "`follow_up`",
        )
        self.assertIn("distinct `execution_id` values", evidence)
        self.assertIn("distinct normalized `observed_at` timestamps", evidence)
        self.assert_ordered(
            evidence,
            "agent-evidence research <artifact.json>",
            "exits 0",
            "return a standing conclusion",
        )

    def test_calling_controllers_record_the_correctness_scope(self):
        final_review = " ".join(
            (SDD_DIR / "final-review.md").read_text(encoding="utf-8").split()
        )
        ship_review = " ".join(
            SHIP_ISSUE_REVIEW.read_text(encoding="utf-8").split()
        )
        ship_skill = " ".join(SHIP_ISSUE.read_text(encoding="utf-8").split())

        # sdd: the scope is a fourth recorded value beside both verdicts and the
        # correctness axis's reviewer identity (D1) — but only on the diff-review
        # path. The capability fallback dispatches the native reviewer directly
        # and returns no scope, so the sentence must not demand one there.
        self.assertIn(
            "When that axis came through `codex-collaboration`'s `diff-review`, "
            "record the scope it returned as well (`full` | `scoped: <N> of <M> "
            "product files` | `unmeasured`)",
            final_review,
        )
        self.assertIn(
            "the native reviewer dispatched directly returns no scope, so record "
            "none there",
            final_review,
        )
        self.assertIn("Never merge the two reports", final_review)
        self.assertIn("`Codex` | `native` | `fallback` + failure class", final_review)

        # ship-issue: the PR body is the provenance surface, and no reviewer
        # identity is added there (D9).
        self.assertIn(
            "Record that scope in the PR body beside the correctness verdict",
            ship_review,
        )
        self.assertIn(
            "ship-issue records no reviewer identity; this records the scope only.",
            ship_review,
        )
        # SKILL.md carries REVIEW.md's condition too: the native correctness
        # fallback dispatched from this same paragraph returns no scope, so an
        # unconditional sentence would send a reader looking for one.
        self.assertIn(
            "when the correctness axis came through `diff-review`, its scope is "
            "recorded in the PR body per REVIEW.md",
            ship_skill,
        )
        # Dispatch selection is untouched: the Phase 5 dispatch ids stay as they are.
        for dispatch_id in (
            "ship-issue-full-conformance-review",
            "ship-issue-full-correctness-fallback",
            "ship-issue-scoped-fix-rereview",
        ):
            with self.subTest(dispatch_id=dispatch_id):
                self.assertIn(dispatch_id, ship_skill)

    def test_sdd_documents_the_primary_rooted_bucketed_workspace(self):
        text = normalized(self.sdd)
        self.assertIn(
            "`<primary-checkout>/.superpowers/sdd/<checkout-bucket>/<plan-basename>/`",
            text,
        )
        self.assertIn(
            "`primary` for the primary checkout itself and `wt-<worktree-name>` "
            "for a linked worktree",
            text,
        )
        self.assertIn(
            "`git clean -fdx` in the primary checkout destroys the workspace",
            text,
        )

    def test_no_document_or_script_claims_a_repo_root_workspace(self):
        offenders = [
            str(path.relative_to(REPO_ROOT))
            for path, text in corpus_documents()
            if REPO_ROOT_WORKSPACE_LITERAL in text
        ]
        offenders += [
            str(path.relative_to(REPO_ROOT))
            for path in sorted(SDD_SCRIPTS.iterdir())
            if path.is_file()
            and REPO_ROOT_WORKSPACE_LITERAL in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])

    def test_superpowers_homes_are_a_closed_allowlist(self):
        found: dict[str, set[str]] = {}
        for path, text in corpus_documents():
            for match in SUPERPOWERS_SEGMENT_RE.finditer(text):
                found.setdefault(match.group(1), set()).add(
                    str(path.relative_to(REPO_ROOT))
                )
        self.assertEqual(set(found), SUPERPOWERS_SEGMENTS, found)

    def test_ship_review_is_the_single_documented_exception(self):
        carriers = [
            str(path.relative_to(REPO_ROOT))
            for path, text in corpus_documents()
            if ".superpowers/ship-review" in text
        ]
        self.assertEqual(
            carriers, ["home/common/agent-skills/skills/ship-issue/REVIEW.md"]
        )
        self.assertIn(SHIP_REVIEW_EXCEPTION, normalized(self.ship_review))

    def test_ship_issue_prunes_the_removed_worktrees_sdd_bucket(self):
        text = normalized(self.ship_issue)
        self.assertIn(WORKTREE_BUCKET_LITERAL, text)
        self.assertIn(
            "Remove only that one worktree's bucket — never `primary/`, and "
            "never another worktree's.",
            text,
        )

    def test_worktrees_names_the_scratch_git_clean_destroys(self):
        text = normalized(self.worktrees)
        self.assertIn(CLEAN_SCRATCH_CLAUSE, text)
        self.assertNotIn("(ledgers, review packages)", text)

    def test_gitignore_is_tracked_and_carries_the_backstop(self):
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "--error-unmatch", ".gitignore"],
            check=True, capture_output=True,
        )
        lines = GITIGNORE.read_text(encoding="utf-8").splitlines()
        for pattern in SCRATCH_IGNORE_PATTERNS:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, lines)

    def test_gitignore_ignores_leaked_shapes_in_an_isolated_repository(self):
        """Check the patterns in a throwaway repo, never in this one.

        This repository's .git/info/exclude already ignores the same shapes, so
        running `git check-ignore` here would pass even against an empty
        .gitignore — a vacuous pass. Global and system git config are disabled
        too, so a machine-local core.excludesFile cannot decide a keep shape
        for us (D12).
        """
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw) / "repo"
            home = Path(raw) / "home"
            home.mkdir()
            env = os.environ.copy()
            env.update({
                "HOME": str(home),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
            })
            for redirect_var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
                env.pop(redirect_var, None)
            subprocess.run(
                ["git", "init", "-q", "-b", "main", str(repo)],
                env=env, check=True,
            )
            (repo / ".gitignore").write_bytes(GITIGNORE.read_bytes())

            def status(candidate):
                return subprocess.run(
                    ["git", "-C", str(repo), "-c", f"core.excludesFile={os.devnull}",
                     "check-ignore", "-q", "--no-index", candidate],
                    env=env, capture_output=True, check=False,
                ).returncode

            for shape in IGNORED_SHAPES:
                with self.subTest(ignored=shape):
                    self.assertEqual(status(shape), 0)
            for shape in KEPT_SHAPES:
                with self.subTest(kept=shape):
                    self.assertEqual(status(shape), 1)


# --- codebase-design vocabulary package (issue 42) -------------------------
# One contiguous block at the end of the file. Concurrent work on neighbouring
# skills appends its own block here, so a merge conflicts at most once and is
# resolved by keeping both blocks.

CODEBASE_DESIGN_DIR = REPO_ROOT / "home/common/agent-skills/skills/codebase-design"
CODEBASE_DESIGN_REVISION = "9c9f36ccd3995266cd675468af71639c8dde1ec5"
CODEBASE_DESIGN_UPSTREAM = "https://github.com/mattpocock/skills"
CODEBASE_DESIGN_FILES = (
    "SKILL.md",
    "DEEPENING.md",
    "DESIGN-IT-TWICE.md",
    "LICENSE",
    "agents/openai.yaml",
)
# Each canonical term maps to a discriminating clause of its definition — enough
# that rewriting the meaning fails the contract, short enough that reflowing the
# paragraph around it does not. Every clause is verbatim upstream text and
# apostrophe-free, so no quoting subtleties travel with it.
CANONICAL_DESIGN_TERMS = {
    "Module": "anything with an interface and an implementation",
    "Interface": "everything a caller must know to use the module correctly",
    "Implementation": "inside a module, its body of code",
    "Depth": "the amount of behaviour a caller (or test) can exercise per unit of interface",
    "Seam": "a place where you can alter behaviour without editing in that place",
    "Adapter": "a concrete thing that satisfies an interface at a seam",
    "Leverage": "more capability per unit of interface they learn",
    "Locality": "change, bugs, knowledge, and verification concentrate in one place",
}


def skill_frontmatter(text):
    """Return a SKILL.md's YAML frontmatter as a flat ``key -> value`` dict.

    Values are everything after the first colon, stripped. The skill packages in
    this tree use only flat single-line frontmatter keys, so no YAML parser is
    pulled in. Parsing fails closed: a document with no leading ``---`` fence and
    a document whose fence is never closed both yield an empty dict, so malformed
    frontmatter cannot satisfy a contract by accident.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    return {}


def relative_markdown_links(text):
    """Yield each relative link target in `text`.

    A target is the ``target`` of a ``](target)`` sequence, with any ``#fragment``
    stripped so that ``DEEPENING.md#dependency-categories`` is yielded as the path
    it addresses rather than as a literal filename containing a ``#``. Absolute
    URLs and bare in-document anchors (which strip down to nothing) are skipped:
    what this exists to catch is a link to a sibling file not in the package.
    """
    for chunk in text.split("](")[1:]:
        target, _, _fragment = chunk.split(")", 1)[0].partition("#")
        if not target or target.startswith(("http://", "https://")):
            continue
        yield target


def glossary_entries(glossary):
    """Split a glossary into ``term -> entry`` for the canonical terms.

    An entry runs from its own ``**Term**`` marker at the start of a line to the
    start of the next canonical term's entry, or to the end of the glossary for
    the last one. Only line-leading markers open an entry, so a term named inside
    another entry's prose (``Distinct from **Adapter**``) does not split it. A
    term with no entry is absent from the result rather than mapped to an empty
    string, so a caller can tell "no entry" from "entry says nothing".
    """
    markers = sorted(
        (glossary.find(f"\n**{term}**"), term)
        for term in CANONICAL_DESIGN_TERMS
        if glossary.find(f"\n**{term}**") != -1
    )
    entries = {}
    for position, (start, term) in enumerate(markers):
        following = markers[position + 1 :]
        end = following[0][0] if following else len(glossary)
        entries[term] = glossary[start:end]
    return entries


class CodebaseDesignSkillContractsTest(unittest.TestCase):
    """The vendored deep-module vocabulary package.

    Fixtures are read here rather than at module import so that an absent or
    incomplete package errors only this class and leaves the rest of the
    suite's coverage reporting normally.
    """

    @classmethod
    def setUpClass(cls):
        cls.skill = (CODEBASE_DESIGN_DIR / "SKILL.md").read_text(encoding="utf-8")
        cls.deepening = (CODEBASE_DESIGN_DIR / "DEEPENING.md").read_text(encoding="utf-8")
        cls.twice = (CODEBASE_DESIGN_DIR / "DESIGN-IT-TWICE.md").read_text(encoding="utf-8")
        cls.notice = (CODEBASE_DESIGN_DIR / "LICENSE").read_text(encoding="utf-8")

    def glossary(self):
        start = self.skill.index("## Glossary")
        return self.skill[start : self.skill.index("## Deep vs shallow", start)]

    def test_package_passes_skill_package_validation(self):
        for relative in CODEBASE_DESIGN_FILES:
            with self.subTest(path=relative):
                self.assertTrue(
                    (CODEBASE_DESIGN_DIR / relative).is_file(),
                    f"missing package file: {relative}",
                )
        frontmatter = skill_frontmatter(self.skill)
        self.assertEqual(frontmatter.get("name"), CODEBASE_DESIGN_DIR.name)
        self.assertTrue(frontmatter.get("description", "").strip())
        # The trigger the rest of the skill tree depends on, kept verbatim (D14).
        self.assertIn(
            "another skill needs the deep-module vocabulary",
            frontmatter["description"],
        )

    def test_every_relative_link_in_the_package_resolves(self):
        documents = {
            "SKILL.md": self.skill,
            "DEEPENING.md": self.deepening,
            "DESIGN-IT-TWICE.md": self.twice,
        }
        package_root = CODEBASE_DESIGN_DIR.resolve()
        checked = 0
        for name, text in documents.items():
            for target in relative_markdown_links(text):
                checked += 1
                with self.subTest(document=name, target=target):
                    # Resolve against the containing document, then require the
                    # result to stay inside the package. `exists()` alone would
                    # let a `../../…` traversal pass by reaching a real file
                    # outside the package, which is not a resolving link.
                    resolved = (package_root / name).parent.joinpath(target).resolve()
                    self.assertTrue(
                        resolved.is_relative_to(package_root),
                        f"{name} links to {target}, which escapes the package",
                    )
                    self.assertTrue(
                        resolved.is_file(),
                        f"{name} links to {target}, which is not a file in the package",
                    )
        self.assertGreaterEqual(checked, 9, "the link scan found nothing to check")

    def test_glossary_defines_every_canonical_term(self):
        # Pin the definitions, not just the headings: a heading-only assertion
        # stays green while every definition is deleted or rewritten, which is
        # exactly the drift this contract exists to catch. Each clause is required
        # inside its own term's entry, not merely somewhere in the glossary —
        # searching the whole glossary lets a gutted entry pass so long as its
        # clause survives in the section intro or in a neighbouring entry.
        entries = glossary_entries(self.glossary())
        for term, definition in CANONICAL_DESIGN_TERMS.items():
            with self.subTest(term=term):
                self.assertIn(term, entries, f"the glossary has no **{term}** entry")
                self.assertIn(
                    definition,
                    entries[term],
                    f"the **{term}** entry does not define {term.lower()}",
                )

    def test_glossary_forbids_substituting_the_canonical_terms(self):
        glossary = self.glossary()
        self.assertIn(
            'Use these terms exactly — don\'t substitute "component," "service," '
            '"API," or "boundary."',
            glossary,
        )
        for avoided in (
            "_Avoid_: unit, component, service",
            "_Avoid_: API, signature",
            "_Avoid_: boundary",
        ):
            with self.subTest(avoided=avoided):
                self.assertIn(avoided, glossary)

    def test_deletion_test_keeps_both_branches(self):
        self.assertIn("**The deletion test.**", self.skill)
        self.assertIn("If complexity vanishes, it was a pass-through.", self.skill)
        self.assertIn(
            "If complexity reappears across N callers, it was earning its keep.",
            self.skill,
        )

    def test_interface_is_the_test_surface_in_both_files(self):
        self.assertIn(
            "**The interface is the test surface.** Callers and tests cross the "
            "same seam.",
            self.skill,
        )
        self.assertIn("The **interface is the test surface**.", self.deepening)

    def test_adapter_seam_rule_is_pinned_in_both_files(self):
        rule = "One adapter means a hypothetical seam. Two adapters means a real one."
        self.assertIn(rule, self.skill)
        self.assertIn(rule, self.deepening)

    def test_seam_entry_reconciles_this_repositorys_test_seam(self):
        glossary = self.glossary()
        start = glossary.index("**Seam**")
        seam_entry = glossary[start : glossary.index("**Adapter**", start)]
        self.assertIn(
            "a place where you can alter behaviour without editing in that place",
            seam_entry,
        )
        self.assertIn(
            "A **test seam**, as the design and planning skills use the term, is "
            "one of these seams chosen as the boundary that verification crosses",
            seam_entry,
        )

    def test_deepening_carries_all_four_dependency_categories(self):
        for heading in (
            "### 1. In-process",
            "### 2. Local-substitutable",
            "### 3. Remote but owned (Ports & Adapters)",
            "### 4. True external (Mock)",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.deepening)
        start = self.deepening.index("### 3. Remote but owned (Ports & Adapters)")
        ports = self.deepening[
            start : self.deepening.index("### 4. True external (Mock)", start)
        ]
        self.assertIn(
            "implement an HTTP adapter for production and an in-memory adapter "
            "for testing",
            ports,
        )

    def test_design_it_twice_keeps_the_workflow_and_its_adaptations(self):
        self.assertIn("Spawn 3+ sub-agents in parallel.", self.twice)
        self.assertIn("**radically different**", self.twice)
        self.assertIn(
            "Contrast by **depth** (leverage at the interface), **locality** "
            "(where change concentrates), and **seam placement**.",
            self.twice,
        )
        # D5: upstream's dangling CONTEXT.md reference stays repointed.
        self.assertNotIn("CONTEXT.md", self.twice)
        self.assertIn(
            "Resolve the domain language the way the `doc-grounded-questions` "
            "skill does",
            self.twice,
        )
        # D7: an autonomous run has nobody to stall on.
        self.assertIn("The recommendation is the answer", self.twice)
        self.assertIn("recorded as a decision-ledger row", self.twice)

    def test_package_carries_no_dispatch_site_and_names_the_owner_tier(self):
        for path in sorted(CODEBASE_DESIGN_DIR.rglob("*")):
            if not path.is_file():
                continue
            with self.subTest(path=str(path.relative_to(CODEBASE_DESIGN_DIR))):
                self.assertNotIn("Agent(", path.read_text(encoding="utf-8"))
        # D6: the tier is stated in words instead.
        self.assertIn(
            "dispatch them at the `issue-owner` tier rather than the cheap "
            "`explorer` tier",
            self.twice,
        )

    def test_license_records_provenance_and_the_upstream_notice(self):
        self.assertIn(CODEBASE_DESIGN_UPSTREAM, self.notice)
        self.assertIn(CODEBASE_DESIGN_REVISION, self.notice)
        self.assertIn("Copyright (c) 2026 Matt Pocock", self.notice)
        self.assertIn(
            "Permission is hereby granted, free of charge, to any person "
            "obtaining a copy",
            self.notice,
        )
        self.assertIn(
            "The above copyright notice and this permission notice shall be "
            "included in all",
            self.notice,
        )
        # D2: SKILL.md points at the notice and never carries it.
        self.assertIn("[LICENSE](LICENSE)", self.skill)
        self.assertNotIn("Permission is hereby granted", self.skill)


IMPROVE_DIR = REPO_ROOT / "home/common/agent-skills/skills/improve-codebase-architecture"
IMPROVE_REVISION = "9c9f36ccd3995266cd675468af71639c8dde1ec5"
IMPROVE_FILES = ("SKILL.md", "HTML-REPORT.md", "LICENSE", "agents/openai.yaml", "evals/evals.json")
IMPROVE_MARKER = "<!-- agent-dispatch: id=improve-architecture-scan-owner role=issue-owner model=opus effort=high -->"
IMPROVE_CALL = ('Agent(subagent_type="general-purpose", model="opus", effort="high") '
                "performs the one read-only architecture scan and returns evidence-backed "
                "deepening candidates without writing to the repository.")
DESIGN_COMPLETE = (
    "DESIGN_COMPLETE: spec committed and grilled; control returned before planning or "
    "implementation."
)
MIT_NOTICE = '''MIT License

Copyright (c) 2026 Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''


class ImproveCodebaseArchitectureSkillContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = (IMPROVE_DIR / "SKILL.md").read_text(encoding="utf-8")
        cls.report = (IMPROVE_DIR / "HTML-REPORT.md").read_text(encoding="utf-8")
        cls.notice = (IMPROVE_DIR / "LICENSE").read_text(encoding="utf-8")
        cls.manifest = (IMPROVE_DIR / "agents/openai.yaml").read_text(encoding="utf-8")
        cls.evals = json.loads((IMPROVE_DIR / "evals/evals.json").read_text(encoding="utf-8"))

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            found = text.find(anchor, position + 1)
            self.assertGreater(found, position, anchor)
            position = found

    def assertion_shell(self, case_id, name):
        case = next(case for case in self.evals["evals"] if case["id"] == case_id)
        return next(item["shell"] for item in case["asserts"] if item["name"] == name)

    def run_assertion_shell(self, shell, *, out="", repo=None, extra_env=None):
        prelude = r'''
set -uo pipefail
fail() { printf '%s\n' "$*" >&2; return 1; }
out_matches() { grep -Eiq -- "$1" "$OUT" || fail "missing output: $1"; }
out_lacks() { grep -Eiq -- "$1" "$OUT" && fail "forbidden output: $1"; return 0; }
path_unchanged_since() { return 0; }
'''
        with tempfile.TemporaryDirectory() as temporary:
            output_path = Path(temporary) / "output.txt"
            output_path.write_text(out, encoding="utf-8")
            environment = os.environ.copy()
            environment.update(
                {"OUT": str(output_path), "REPO": str(repo or "/nonexistent")}
            )
            environment.update(extra_env or {})
            return subprocess.run(
                ["bash", "-c", prelude + "\n" + shell],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

    def test_structure_links_and_explicit_only_metadata(self):
        self.assertEqual(sorted(str(p.relative_to(IMPROVE_DIR)) for p in IMPROVE_DIR.rglob("*") if p.is_file()), sorted(IMPROVE_FILES))
        self.assertEqual(skill_frontmatter(self.skill), {
            "name": "improve-codebase-architecture",
            "description": "Scan a codebase for deepening opportunities, present them as a visual HTML report, then grill through whichever one you pick.",
            "disable-model-invocation": "true",
        })
        self.assertEqual(self.manifest, 'interface:\n  display_name: "Improve Codebase Architecture"\n  short_description: "Find and grill architecture improvements"\npolicy:\n  allow_implicit_invocation: false\n')
        root = IMPROVE_DIR.resolve()
        checked = 0
        for name, text in {"SKILL.md": self.skill, "HTML-REPORT.md": self.report}.items():
            for target in relative_markdown_links(text):
                checked += 1
                resolved = (root / name).parent.joinpath(target).resolve()
                self.assertTrue(resolved.is_relative_to(root), (name, target))
                self.assertTrue(resolved.is_file(), (name, target))
        self.assertGreaterEqual(checked, 2)

    def test_scan_pins_all_evidence_in_order_and_one_dispatch(self):
        self.assert_ordered(self.skill, "module and callers", "interface knowledge callers currently carry", "where locality or leverage is lost", "deletion-test result", "dependency category", "two justified adapters", "existing tests", "proposed interface-level test surface", "context or decision conflict")
        for dependency in ("codebase-design", "doc-grounded-questions", "worktrees", "design", "grill-with-docs", "wayfind", "writing-plans", "to-issues"):
            self.assertIn(f"`{dependency}`", self.skill)
            self.assertTrue((REPO_ROOT / "home/common/agent-skills/skills" / dependency).is_dir(), dependency)
        for fragment in ("bypasses inference", "git log --oneline --no-merges -50", "scattered", "History selects where to look", "writes nothing to the repository", "at most one structured findings artifact", "zero to five", "Never pad", "successful run", "Strong", "Worth exploring", "Speculative", "when at least one candidate exists"):
            self.assertIn(fragment, self.skill)
        lines = self.skill.splitlines()
        self.assertEqual([line for line in lines if "Agent(" in line], [IMPROVE_CALL])
        self.assertEqual(lines.index(IMPROVE_CALL), lines.index(IMPROVE_MARKER) + 1)

    def test_report_pins_scaffold_cdns_and_accessible_fallbacks(self):
        for fragment in ("<!doctype html>", '<html lang="en">', '<script src="https://cdn.tailwindcss.com"></script>', 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs', '<section id="candidates"', '<section id="top-recommendation"', "Mermaid graph", "Hand-built boxes-and-arrows", "Cross-section", "Mass diagram", "Call-graph collapse", "semantic headings", "text equivalent", "colour is never the sole", "minimal inline base styles", "4.5:1", "phone width", "without duplicating content", "text is not clipped", "user spacing overrides"):
            self.assertIn(fragment, self.report)
        for css in ("body {", "font-family:", "line-height: 1.5", "overflow-wrap: anywhere", "max-width: 100%", "height: auto", ".before-after {", "grid-template-columns: repeat(2, minmax(0, 1fr))", "@media (max-width: 640px)", "grid-template-columns: 1fr"):
            self.assertIn(css, self.report)
        for fragment in ("$TMPDIR", "/tmp", "%TEMP%", "architecture-review-<timestamp>.html", "absolute path", "generation failure is a failed run", "browser", "CDN", "disclosed warning", "before/after", "Top recommendation"):
            self.assertIn(fragment, self.skill)

    def test_report_escapes_repository_text_and_uses_strict_mermaid(self):
        unsafe = '<img title=\'repo\' onerror="alert(1)">&'
        escaped = html.escape(unsafe, quote=True)
        for fragment in (
            "HTML-escape every repository-derived value",
            "opaque generated node IDs",
            "escaped text labels",
            "no raw HTML labels",
            f"`{unsafe}` becomes `{escaped}`",
            'securityLevel: "strict"',
            "htmlLabels: false",
        ):
            self.assertIn(fragment, self.report)
        for fragment in (
            "HTML-escape every repository-derived value",
            "opaque generated Mermaid node IDs",
            "no raw HTML labels",
        ):
            self.assertIn(fragment, self.skill)
        self.assertNotIn('securityLevel: "loose"', self.report)

    def test_routing_and_exact_ordered_provenance(self):
        self.assert_ordered(self.skill, "`wayfind`", "`worktrees`", "`design`", "`grill-with-docs`", "`writing-plans`")
        for fragment in ("no design worktree", "do not automatically resume", "Do not invoke", "Selection is the first point"):
            self.assertIn(fragment, self.skill)
        self.assertNotIn("from-issue", self.skill)
        self.assertNotIn("`grilling`", self.skill + self.report)
        self.assertNotIn("`domain-modeling`", self.skill + self.report)
        provenance = self.notice[:-len(MIT_NOTICE)]
        self.assertTrue(self.notice.endswith(MIT_NOTICE))
        headings = ("Vocabulary invocation", "Domain grounding repointed", "Hotspot rule made concrete", "Scan becomes a registered dispatch", "Candidate contract stated", "Report contract extended", "Downstream step replaced", "Provenance pointer", "Package extensions")
        self.assertEqual(len(re.findall(r"(?m)^  [1-9]\. ", provenance)), 9)
        self.assert_ordered(provenance, *(f"  {i}. {heading}" for i, heading in enumerate(headings, 1)))
        for fragment in ("https://github.com/mattpocock/skills", "skills/engineering/improve-codebase-architecture/", IMPROVE_REVISION, "2026-08-17", "no automatic synchronisation"):
            self.assertIn(fragment, provenance)
        self.assertIn("[LICENSE](LICENSE)", self.skill)
        self.assertNotIn("Permission is hereby granted", self.skill)

    def test_dispatch_registration_and_standalone_scenario(self):
        data = json.loads((REPO_ROOT / "home/common/agent-skills/model-matrix.json").read_text(encoding="utf-8"))
        site = {item["id"]: item for item in data["dispatch_sites"]}["improve-architecture-scan-owner"]
        self.assertEqual((site["path"], site["marker"], site["call"], site["role"], site["model"], site["effort"], site["requires"]), ("home/common/agent-skills/skills/improve-codebase-architecture/SKILL.md", IMPROVE_MARKER, IMPROVE_CALL, "issue-owner", "opus", "high", []))
        self.assertEqual(data["scenarios"]["improve-codebase-architecture"], [{"workflow": "improve-codebase-architecture", "dispatch": "improve-architecture-scan-owner", "role": "issue-owner", "model": "opus", "effort": "high", "requires": []}])

    def test_eval_assertion_shells_are_unique_and_behavioral(self):
        self.assertEqual(self.evals["skill_name"], "improve-codebase-architecture")
        cases = {case["id"]: case for case in self.evals["evals"]}
        self.assertEqual({i: (c["name"], c["mode"]) for i, c in cases.items()}, {1: ("scan-only-renders-a-temporary-report", "pipeline"), 2: ("clear-selection-reaches-a-design-worktree", "pipeline"), 3: ("foggy-selection-routes-to-wayfind", "pipeline")})
        required_shells = {
            1: {"temporary report exists outside repository": ('architecture-review-', '"$OUT"', '[ -f "$report" ]', '$REPO'), "report is evidence-backed or truthful": ('"$OUT"', 'python3 - "$report"', "HTMLParser", "data-architecture-candidate", 'data-evidence', "module-callers", "caller-interface-knowledge", "locality-leverage", "deletion-test", "dependency-adapters", "tests-interface-surface", "context-decision-conflict", "data-diagram-text", "before", "after", "no-candidates", "top-recommendation", "expected_candidate_ids", "zero_text !=", "1 <= candidate_count <= 5"), "history miss widened the scan": ("out_matches", "widen"), "repository and branches stayed unchanged": ('test "$WT_COUNT" -eq 0', 'status=$(git -C "$REPO" status --porcelain)', 'test -z "$status"', 'test "$(git -C "$REPO" rev-parse HEAD)" = "$(git -C "$REPO" rev-parse origin/main)"', "branches=$(git -C \"$REPO\" for-each-ref --format='%(refname:short)' refs/heads)", 'test "$branches" = "main"')},
            2: {"one isolated design worktree exists": ('test "$WT_COUNT" -eq 1', 'test -n "$WT"'), "design spec was committed": ('commits_touch "$WT" "$SPEC_DIR"',), "source and tests stayed unchanged": ('path_unchanged_since "$REPO" origin/main tinytask tests', 'path_unchanged_since "$WT" origin/main tinytask tests'), "no plan was created": ('if has_file "$REPO/$PLAN_DIR"/*.md "$WT/$PLAN_DIR"/*.md; then', "fail"), "domain review was reached": ("out_matches", "grill-with-docs"), "scope workflow was recommended": ("out_matches", "recommend", "&&", "writing-plans|to-issues"), "design returned control without continuation": ('sed \'/^[[:space:]]*$/d\' "$OUT"', DESIGN_COMPLETE)},
            3: {"new wayfind map exists and prior map stayed unchanged": ('new_map_count=0', 'for map in "$REPO"/.claude/wayfind/*/map.md; do', "*/concurrent-shells/map.md) continue", '[ -f "$map" ] || continue', 'relative_map=${map#"$REPO"/}', 'if git -C "$REPO" cat-file -e "origin/main:$relative_map" 2>/dev/null; then', 'new_map_count=$((new_map_count + 1))', 'test "$new_map_count" -eq 1', 'path_unchanged_since "$REPO" origin/main .claude/wayfind/concurrent-shells'), "no worktree was created": ('test "$WT_COUNT" -eq 0',), "no spec or plan was created": ('if has_file "$REPO/$SPEC_DIR"/*.md "$REPO/$PLAN_DIR"/*.md; then', "fail"), "source and tests stayed unchanged": ('path_unchanged_since "$REPO" origin/main tinytask tests',), "wayfind returned control without continuation": ('sed \'/^[[:space:]]*$/d\' "$OUT"', "WAYFIND_COMPLETE: map created; control returned before issue creation, planning, or implementation.")},
        }
        for case_id, case in cases.items():
            self.assertNotIn("expected_today", case)
            self.assertIn("/improve-codebase-architecture", case["prompt"])
            self.assertTrue(case["expected_output"].strip())
            assertions = case["asserts"]
            names = [item["name"] for item in assertions]
            self.assertEqual(len(names), len(set(names)))
            self.assertTrue(all(item["shell"].strip() for item in assertions))
            shells = {item["name"]: item["shell"] for item in assertions}
            self.assertEqual(set(shells), set(required_shells[case_id]))
            for name, fragments in required_shells[case_id].items():
                self.assertIn(name, shells)
                for fragment in fragments:
                    self.assertIn(fragment, shells[name])
        self.assertIn("unscoped", cases[1]["prompt"].lower())
        self.assertIn("tinytask.store", cases[2]["prompt"])
        self.assertIn("sync between machines", cases[3]["prompt"].lower())
        clear_prompt = cases[2]["prompt"]
        for fragment in ("Nobody is present", "reversible in-scope", "scope-redrawing", "hard to reverse", "credential", "spending", "cannot answer", "stop", "Do not create a plan", "Do not refactor"):
            self.assertIn(fragment, clear_prompt)

    def test_eval_1_report_assertion_rejects_malformed_structure(self):
        shell = self.assertion_shell(1, "report is evidence-backed or truthful")
        evidence = (
            "module-callers",
            "caller-interface-knowledge",
            "locality-leverage",
            "deletion-test",
            "dependency-adapters",
            "tests-interface-surface",
            "context-decision-conflict",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            report = root / "architecture-review-test.html"

            report.write_text(
                '<section id="candidates"><p id="no-candidates" '
                'data-candidate-count="0">No evidence-backed candidates.</p></section>',
                encoding="utf-8",
            )
            zero_result = self.run_assertion_shell(shell, out=str(report), repo=repo)
            self.assertEqual(zero_result.returncode, 0, zero_result.stderr)

            report.write_text(
                '<section id="candidates"><p id="no-candidates" '
                'data-candidate-count="0">No evidence-backed candidates.</p></section>'
                '<article data-architecture-candidate id="candidate-outside">Hidden</article>',
                encoding="utf-8",
            )
            self.assertNotEqual(
                self.run_assertion_shell(shell, out=str(report), repo=repo).returncode,
                0,
            )

            surfaces = "".join(
                f'<section data-evidence="{name}">{name} evidence</section>'
                for name in evidence
            )
            report.write_text(
                '<section id="candidates">'
                '<article data-architecture-candidate id="candidate-1">'
                f'{surfaces}'
                '<p data-diagram-text="before">Before text.</p>'
                '<p data-diagram-text="after">After text.</p>'
                '</article></section>'
                '<section id="top-recommendation"><a href="#candidate-1">Pick it</a></section>',
                encoding="utf-8",
            )
            candidate_result = self.run_assertion_shell(
                shell, out=str(report), repo=repo
            )
            self.assertEqual(candidate_result.returncode, 0, candidate_result.stderr)

            malformed_reports = {
                "wrong zero-state element": (
                    '<section id="candidates"><div id="no-candidates" '
                    'data-candidate-count="0">No evidence-backed candidates.</div></section>'
                ),
                "zero-state surrounding text": (
                    '<section id="candidates">Before<p id="no-candidates" '
                    'data-candidate-count="0">No evidence-backed candidates.</p>After</section>'
                ),
                "zero-state extra normalized text": (
                    '<section id="candidates"><p id="no-candidates" '
                    'data-candidate-count="0">No evidence-backed candidates. Extra</p></section>'
                ),
                "repository-derived candidate id": (
                    '<section id="candidates">'
                    '<article data-architecture-candidate id="tinytask-store">'
                    f'{surfaces}'
                    '<p data-diagram-text="before">Before text.</p>'
                    '<p data-diagram-text="after">After text.</p>'
                    '</article></section>'
                    '<section id="top-recommendation"><a href="#tinytask-store">Pick it</a></section>'
                ),
                "candidate id gap": (
                    '<section id="candidates">'
                    '<article data-architecture-candidate id="candidate-2">'
                    f'{surfaces}'
                    '<p data-diagram-text="before">Before text.</p>'
                    '<p data-diagram-text="after">After text.</p>'
                    '</article></section>'
                    '<section id="top-recommendation"><a href="#candidate-2">Pick it</a></section>'
                ),
                "duplicate candidate ids": (
                    '<section id="candidates">'
                    '<article data-architecture-candidate id="candidate-1">'
                    f'{surfaces}'
                    '<p data-diagram-text="before">Before text.</p>'
                    '<p data-diagram-text="after">After text.</p>'
                    '</article>'
                    '<article data-architecture-candidate id="candidate-1">'
                    f'{surfaces}'
                    '<p data-diagram-text="before">Before text.</p>'
                    '<p data-diagram-text="after">After text.</p>'
                    '</article></section>'
                    '<section id="top-recommendation"><a href="#candidate-1">Pick it</a></section>'
                ),
                "candidate id sequence gap": (
                    '<section id="candidates">'
                    '<article data-architecture-candidate id="candidate-1">'
                    f'{surfaces}'
                    '<p data-diagram-text="before">Before text.</p>'
                    '<p data-diagram-text="after">After text.</p>'
                    '</article>'
                    '<article data-architecture-candidate id="candidate-3">'
                    f'{surfaces}'
                    '<p data-diagram-text="before">Before text.</p>'
                    '<p data-diagram-text="after">After text.</p>'
                    '</article></section>'
                    '<section id="top-recommendation"><a href="#candidate-3">Pick it</a></section>'
                ),
                "invalid top candidate id": (
                    '<section id="candidates">'
                    '<article data-architecture-candidate id="candidate-1">'
                    f'{surfaces}'
                    '<p data-diagram-text="before">Before text.</p>'
                    '<p data-diagram-text="after">After text.</p>'
                    '</article></section>'
                    '<section id="top-recommendation"><a href="#candidate-2">Pick it</a></section>'
                ),
            }
            for name, malformed in malformed_reports.items():
                with self.subTest(name=name):
                    report.write_text(malformed, encoding="utf-8")
                    self.assertNotEqual(
                        self.run_assertion_shell(shell, out=str(report), repo=repo).returncode,
                        0,
                    )

            report.write_text(
                '<section id="candidates"><article data-architecture-candidate '
                'id="candidate-1">'
                f'{surfaces}'
                '<p data-diagram-text="before">Before text.</p>'
                '<p data-diagram-text="after">After text.</p>'
                '</article></section>'
                '<section id="candidates"></section>'
                '<section id="top-recommendation"><a href="#candidate-1">Pick it</a></section>',
                encoding="utf-8",
            )
            self.assertNotEqual(
                self.run_assertion_shell(shell, out=str(report), repo=repo).returncode,
                0,
            )

            report.write_text(
                "<html><body>No candidate. Before. After. Top recommendation.</body></html>",
                encoding="utf-8",
            )
            self.assertNotEqual(
                self.run_assertion_shell(shell, out=str(report), repo=repo).returncode,
                0,
            )

            report.write_text(
                '<section id="candidates"><p id="no-candidates" '
                'data-candidate-count="0">No evidence-backed candidates.</p></section>'
                '<section id="top-recommendation"><a href="#candidate-1">Invalid</a></section>',
                encoding="utf-8",
            )
            self.assertNotEqual(
                self.run_assertion_shell(shell, out=str(report), repo=repo).returncode,
                0,
            )

            articles = "".join(
                '<article data-architecture-candidate id="candidate-{index}">'
                '{surfaces}'
                '<p data-diagram-text="before">Before text.</p>'
                '<p data-diagram-text="after">After text.</p>'
                '</article>'.format(index=index, surfaces=surfaces)
                for index in range(1, 7)
            )
            report.write_text(
                f'<section id="candidates">{articles}</section>'
                '<section id="top-recommendation"><a href="#candidate-1">Pick it</a></section>',
                encoding="utf-8",
            )
            self.assertNotEqual(
                self.run_assertion_shell(shell, out=str(report), repo=repo).returncode,
                0,
            )

    def test_eval_assertions_use_file_backed_output_for_all_three_cases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            report = root / "architecture-review-test.html"
            report.write_text(
                '<section id="candidates"><p id="no-candidates" '
                'data-candidate-count="0">No evidence-backed candidates.</p></section>',
                encoding="utf-8",
            )
            checks = (
                (
                    1,
                    "temporary report exists outside repository",
                    f"Scan widened.\n{report}\n",
                ),
                (
                    1,
                    "report is evidence-backed or truthful",
                    f"Scan widened.\n{report}\n",
                ),
                (1, "history miss widened the scan", "Scan widened.\n"),
                (2, "domain review was reached", "Reached grill-with-docs.\n"),
                (
                    2,
                    "scope workflow was recommended",
                    "Recommend writing-plans.\n",
                ),
                (
                    2,
                    "design returned control without continuation",
                    f"{DESIGN_COMPLETE}\n",
                ),
                (
                    3,
                    "wayfind returned control without continuation",
                    "WAYFIND_COMPLETE: map created; control returned before issue creation, "
                    "planning, or implementation.\n",
                ),
            )
            for case_id, name, output in checks:
                with self.subTest(case_id=case_id, name=name):
                    shell = self.assertion_shell(case_id, name)
                    self.assertNotIn('printf \'%s\\n\' "$OUT"', shell)
                    result = self.run_assertion_shell(shell, out=output, repo=repo)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_eval_2_requires_exact_final_design_status(self):
        case = next(case for case in self.evals["evals"] if case["id"] == 2)
        self.assertIn(DESIGN_COMPLETE, self.skill)
        self.assertIn(DESIGN_COMPLETE, case["prompt"])
        self.assertIn(DESIGN_COMPLETE, case["expected_output"])
        recommendation_shell = self.assertion_shell(2, "scope workflow was recommended")
        terminal_shell = self.assertion_shell(
            2, "design returned control without continuation"
        )
        self.assertIn("writing-plans|to-issues", recommendation_shell)
        self.assertNotIn("terminal_line=", recommendation_shell)
        self.assertEqual(
            self.run_assertion_shell(
                terminal_shell, out=f"Summary.\n{DESIGN_COMPLETE}\n"
            ).returncode,
            0,
        )
        self.assertNotEqual(
            self.run_assertion_shell(
                terminal_shell, out=f"{DESIGN_COMPLETE}\nContinued afterward.\n"
            ).returncode,
            0,
        )
        contradictory = (
            "I recommend writing-plans. I did not stop and invoked it before returning.\n"
        )
        self.assertEqual(
            self.run_assertion_shell(
                recommendation_shell, out=contradictory
            ).returncode,
            0,
        )
        self.assertNotEqual(
            self.run_assertion_shell(terminal_shell, out=contradictory).returncode,
            0,
        )

    def test_eval_3_counts_one_new_map_and_requires_final_status(self):
        map_shell = self.assertion_shell(
            3, "new wayfind map exists and prior map stayed unchanged"
        )
        terminal_shell = self.assertion_shell(
            3, "wayfind returned control without continuation"
        )
        self.assertNotIn("break", map_shell)
        self.assertNotIn("out_lacks", terminal_shell)
        expected = (
            "WAYFIND_COMPLETE: map created; control returned before issue creation, "
            "planning, or implementation."
        )
        self.assertEqual(
            self.run_assertion_shell(terminal_shell, out=f"Summary.\n{expected}\n").returncode,
            0,
        )
        self.assertNotEqual(
            self.run_assertion_shell(terminal_shell, out="Stopping after wayfind.").returncode,
            0,
        )
        self.assertNotEqual(
            self.run_assertion_shell(
                terminal_shell, out=f"{expected}\nContinued afterward."
            ).returncode,
            0,
        )

        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.email", "eval@example.test"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.name", "Eval"],
                check=True,
            )
            prior = repo / ".claude/wayfind/concurrent-shells/map.md"
            prior.parent.mkdir(parents=True)
            prior.write_text("prior\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", "HEAD"],
                check=True,
            )

            first = repo / ".claude/wayfind/sync/map.md"
            first.parent.mkdir(parents=True)
            first.write_text("new\n", encoding="utf-8")
            self.assertEqual(self.run_assertion_shell(map_shell, repo=repo).returncode, 0)

            second = repo / ".claude/wayfind/transport/map.md"
            second.parent.mkdir(parents=True)
            second.write_text("also new\n", encoding="utf-8")
            self.assertNotEqual(self.run_assertion_shell(map_shell, repo=repo).returncode, 0)

    def test_eval_guard_sequences_fail_closed_under_deployed_harness(self):
        repository_shell = self.assertion_shell(
            1, "repository and branches stayed unchanged"
        )
        worktree_shell = self.assertion_shell(2, "one isolated design worktree exists")

        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.email", "eval@example.test"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.name", "Eval"],
                check=True,
            )
            (repo / "tracked").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", "HEAD"],
                check=True,
            )
            (repo / "untracked").write_text("mutation\n", encoding="utf-8")

            self.assertNotEqual(
                self.run_assertion_shell(
                    repository_shell,
                    repo=repo,
                    extra_env={"WT_COUNT": "0"},
                ).returncode,
                0,
            )

        self.assertNotEqual(
            self.run_assertion_shell(
                worktree_shell,
                extra_env={"WT_COUNT": "2", "WT": "/tmp/first-worktree"},
            ).returncode,
            0,
        )


if __name__ == "__main__":
    unittest.main()
