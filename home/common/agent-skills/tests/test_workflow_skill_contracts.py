from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).parents[4]
ORCHESTRATE = (
    REPO_ROOT / "home/common/claude-code/skills/orchestrate-issues/SKILL.md"
)
FROM_ISSUE = REPO_ROOT / "home/common/agent-skills/skills/from-issue/SKILL.md"
AUTO = REPO_ROOT / "home/common/agent-skills/skills/from-issue/AUTO.md"
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
        cls.handoff = HANDOFF.read_text(encoding="utf-8")
        cls.collaboration = COLLABORATION.read_text(encoding="utf-8")
        cls.diff_review = DIFF_REVIEW.read_text(encoding="utf-8")
        cls.certification = CERTIFICATION.read_text(encoding="utf-8")
        cls.research = RESEARCH.read_text(encoding="utf-8")
        cls.worktrees = WORKTREES.read_text(encoding="utf-8")

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

    def test_dispatcher_passes_immutable_ledger_root_separately_from_worktree(self):
        durable_section = self.section(
            self.orchestrate, "### Durable run ledger", "## 4."
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

    def test_dispatcher_reserves_attempt_worktree_before_launch_and_envelope(self):
        durable_section = self.section(
            self.orchestrate, "### Durable run ledger", "## 4."
        )
        self.assert_ordered(
            durable_section,
            "reserve a collision-free exact absolute worktree path",
            "workflow-state launch",
            "--worktree <absolute-worktree>",
            "worktree=<absolute-worktree>",
        )
        self.assertIn("configured worktree root", durable_section)
        self.assertIn("does not create the worktree", durable_section)

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

    def test_dispatcher_resumes_recorded_attempt_before_fresh_launch(self):
        retry_section = self.section(
            self.orchestrate, "## 5. Failure policy", "## 6. Final report"
        )
        self.assert_ordered(
            retry_section,
            "workflow-state reconcile",
            "resume before fresh",
            "--resume-handoff",
            "same owner, same worktree",
            "resume is impossible",
            "fresh owner/worktree",
        )

    def test_dispatcher_deadline_has_one_bounded_wake_path(self):
        self.assert_ordered(
            self.orchestrate,
            "Deadline wake path",
            "exactly one",
            "deadline observer",
            "workflow-state reconcile",
        )
        self.assertIn("never a poll loop", self.orchestrate)
        self.assertIn("never repeated short sleeps", self.orchestrate)

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
        self.assertIn("direct standalone invocation remains compatible", self.from_issue)
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
        self.assert_ordered(
            phase_one,
            "lifecycle envelope exists",
            "exact absolute `worktree`",
            "create the worktree at that exact path",
            "never choose another path",
        )
        self.assertIn("occupied or mismatched", phase_one)
        self.assertIn("fail the attempt", phase_one)
        self.assertIn("Direct standalone", phase_one)
        self.assertIn("standard `worktrees` flow", phase_one)

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
            "`git diff [MERGE_BASE_SHA]..[HEAD_SHA] -- <path>` once per listed path "
            "and fetch nothing wider",
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


if __name__ == "__main__":
    unittest.main()
