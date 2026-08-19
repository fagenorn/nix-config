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
SHIP_ISSUE_EVALS = (
    REPO_ROOT / "home/common/agent-skills/skills/ship-issue/evals/evals.json"
)

# The Phase-5 degradation boundary, spelled once for the whole module: the skill
# and its eval are both checked against these two strings so they cannot drift.
GATE_LINE_BOUNDARY = "≤1,000 product lines"
GATE_FILE_BOUNDARY = "≤20 product files"


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
        cls.collaboration = COLLABORATION.read_text(encoding="utf-8")
        cls.diff_review = DIFF_REVIEW.read_text(encoding="utf-8")
        cls.certification = CERTIFICATION.read_text(encoding="utf-8")
        cls.research = RESEARCH.read_text(encoding="utf-8")
        cls.worktrees = WORKTREES.read_text(encoding="utf-8")
        cls.ship_issue = SHIP_ISSUE.read_text(encoding="utf-8")
        cls.ship_issue_evals = json.loads(SHIP_ISSUE_EVALS.read_text(encoding="utf-8"))
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
        for field in ("run_id", "attempt", "owner", "worktree", "ledger_repo_root"):
            self.assertIn(field, self.from_issue)
        lifecycle_section = self.section(
            self.from_issue, "## Lifecycle identity", "## The flow"
        )
        self.assertIn("immutable ledger_repo_root", lifecycle_section)
        self.assertIn("separate owner worktree", lifecycle_section)
        self.assertIn("Every `workflow-state` command", lifecycle_section)
        self.assertIn("--repo-root <ledger_repo_root>", lifecycle_section)
        self.assertIn("Direct standalone invocation remains ledger-free", self.from_issue)
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

    def test_lifecycle_phase_one_uses_exact_reserved_attempt_worktree(self):
        phase_one = self.section(self.from_issue, "## Phase 1", "## Phase 2")
        # Three-way on the envelope's exact path. The middle branch is the one a
        # retry actually lands on — the dispatcher hands back the prior attempt's
        # worktree, so re-creating or resetting it would erase the work being
        # resumed; only "anything else" is a failure.
        self.assert_ordered(
            phase_one,
            "lifecycle envelope exists",
            "use its exact absolute `worktree`",
            "**Absent** from both the filesystem",
            "checked out on this issue's branch",
            "adopt it",
            "Do not re-create it, do not move it, do not reset it",
            "a different branch",
            "fail the attempt through the terminal return procedure",
            "never choose another path",
        )
        self.assertNotIn("occupied or mismatched", phase_one)
        self.assertIn("fail the attempt", phase_one)
        self.assertIn("Direct standalone", phase_one)
        self.assertIn("standard `worktrees` flow", phase_one)

    def test_from_issue_handoff_is_resumed_only_from_a_control_envelope(self):
        phase_gate = self.section(
            self.from_issue, "## Dispatch, phase-budget and attempt-budget rules",
            "## Terminal return procedure",
        )
        self.assertIn("returned `resume` envelope", phase_gate)
        self.assertNotIn("workflow-state launch", phase_gate)

    def test_from_issue_standalone_modes_use_live_lifecycle_interfaces(self):
        identity = self.section(
            self.from_issue, "## Lifecycle identity", "## The flow"
        )
        self.assertIn("Direct standalone invocation remains ledger-free", identity)
        self.assert_ordered(
            identity,
            "explicitly requests durable standalone orchestration",
            "workflow-state init-run", "bounded `requirements`",
            "max_parallel: 1", "workflow-state control", "first `spawn` envelope",
            "adopt", "do not spawn another owner",
        )
        self.assertIn("fail loudly", identity)

    def test_from_issue_routes_a_deadline_rejected_progress_to_the_terminal_return(self):
        # A progress call rejected past the attempt budget's deadline is a
        # verdict, not a harness fault: the owner persists its truthful state
        # rather than retrying the checkpoint.
        self.assert_ordered(
            self.from_issue,
            "Obey the returned action exactly",
            "attempt budget's deadline has passed",
            "cannot record progress at or after attempt deadline",
            "progress requires an active attempt",
            "terminal return procedure",
            "Persistence precedes notification",
        )

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
            # The bound is on input, not only on grading (D16): item 4's
            # full-range package leaves a scoped packet, and item 7 is the
            # collection instruction that replaces it.
            "Under budget — or unmeasured — the packet is exactly the six items above",
            "Over budget it differs in exactly three places and nowhere else",
            "Item 4 drops the diff-package path",
            "`[DIFF_FILE]` has no value on a scoped dispatch",
            "do not change `scripts/review-package`: the conformance axis reads that "
            "same package whole",
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
        # (D16) — and the unconditional branch survives beside it.
        for fragment in (
            "Read the diff file once",
            "If no diff file was supplied, fetch the range yourself",
            "unless the packet states the review is scoped and lists the paths "
            "under review",
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
        # The Placeholders paragraph tells a packet builder what `diff-review`
        # supplies. Left flat ("the same values"), it directs the builder to hand
        # over `[DIFF_FILE]` — the full-range package — and the bound degrades to
        # grading-only, which is the failure D16 exists to close.
        placeholders = " ".join(rubric[rubric.index("**Placeholders:**") :].split())
        for fragment in (
            "on a scoped dispatch that packet leaves `[DIFF_FILE]` unsupplied",
            "the full-range package it names is exactly what scoping bounds",
            "routes the reviewer into the fallback branch above",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, placeholders)

    def test_correctness_rubric_pins_the_scoped_fetch_quoting_protocol(self):
        # K1's argv protocol has to land in the rubric, not only in
        # DIFF-REVIEW.md item 7. A scoped dispatch leaves `[DIFF_FILE]`
        # unsupplied, so this fallback branch is the one the reviewer actually
        # runs — an unquoted `-- <path>` here is the live defect, and the packet
        # contract cannot reach it. Mirrored wording, so the two cannot drift.
        rubric = (SDD_DIR / "correctness-reviewer-prompt.md").read_text(
            encoding="utf-8"
        )
        branch = " ".join(
            rubric[
                rubric.index("If no diff file was supplied") : rubric.index(
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
            'This skill IS the chain that "PR-handoff authorization" describes. '
            "Don't re-prompt for `git push`, `gh pr create`, "
            f"`{optional_subject}`, branch delete, or worktree remove. "
            "Pause only where a phase says to.",
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
        for name, text in (("from-issue", self.from_issue), ("orchestrate", self.orchestrate)):
            with self.subTest(skill=name):
                self.assertIn("~/.agents/bin/workflow-state", text)
        for name, text in (("research", self.research), ("certification", self.certification)):
            with self.subTest(skill=name):
                self.assertIn("~/.agents/bin/agent-evidence", text)
        with self.subTest(skill="ship-issue"):
            self.assertIn("~/.agents/bin/diff-scope", self.ship_issue)

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
