import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


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
DIFF_REVIEW = (
    REPO_ROOT / "home/common/claude-code/skills/codex-collaboration/DIFF-REVIEW.md"
)
RESEARCH = REPO_ROOT / "home/common/agent-skills/skills/research/SKILL.md"
WORKTREES = REPO_ROOT / "home/common/agent-skills/skills/worktrees/SKILL.md"
SDD_DIR = REPO_ROOT / "home/common/agent-skills/skills/sdd"
FROM_ISSUE_DIR = REPO_ROOT / "home/common/agent-skills/skills/from-issue"
SHIP_ISSUE = REPO_ROOT / "home/common/agent-skills/skills/ship-issue/SKILL.md"
SHIP_ISSUE_REVIEW = REPO_ROOT / "home/common/agent-skills/skills/ship-issue/REVIEW.md"
SHIP_ISSUE_CI_MERGE = REPO_ROOT / "home/common/agent-skills/skills/ship-issue/CI-MERGE.md"
SHIP_ISSUE_HUMAN_GATE = (
    REPO_ROOT / "home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md"
)
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
REQUIRED_WATCH = "timeout 300 gh pr checks <pr-num> --required --watch --fail-fast --interval 30"
ALL_CHECKS_WATCH = "timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30"
ADVISORY_CALL = "gh pr checks <pr-num> --json name,bucket"

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

LIFECYCLE_DOCS = (FROM_ISSUE, AUTO, FROM_ISSUE_DIR / "ship-handoff.md", SHIP_ISSUE,
                  SHIP_ISSUE_REVIEW, SHIP_ISSUE_HUMAN_GATE, ORCHESTRATE)
STDIN_CLAUSE = ("lifecycle call is one command that reads its input from stdin "
                "through a quoted heredoc")
BUILD_ROOT_CLAUSE = ("The builder seals the policy `resolve-project` resolves at "
                     "`--repo-root`, the ledger repository root; when `worktree` already "
                     "exists, it also resolves there and refuses if any sealed policy "
                     "member differs.")
BUILD_REFUSAL_RELAY = ("report the builder's stderr line verbatim: for a resolver refusal "
                       "it carries the resolver's `error.code`, `repair_id` and ordered "
                       "`violations` exactly.")
WRITER_RULE = ("Under implementation custody a ship owner writes only "
               "`checkpoint-delivery`, never `finish`; a remainder owner writes its "
               "own `finish --summary-file -`.")
# The closed capability-gap line ship-issue returns when its Phase-0 probe finds
# no subagent-launch tool, spelled once for the module (per D4).
CAPABILITY_GAP_LINE = "capability_gap: agent_dispatch"
INPUT_FLAG_RE = re.compile(r"(--request-file|--checkpoint-file|--summary-file|--input)\s+(\S+)")
V2_DIRECT_REQUEST_KEYS = {"interface_version", "issue", "now", "attempt_budget_minutes",
    "new_run", "owner_unavailable", "tracker", "worktree", "forge", "delivery_contract",
    "authorization_intents", "authority_observations", "reevaluation_evidence",
    "delivery_observations", "requested_scope", "recovery"}
V2_CONTROL_REQUEST_KEYS = {"interface_version", "now", "max_parallel",
    "attempt_budget_minutes", "human_directed", "issues", "tracker", "owners",
    "worktrees", "forge", "delivery_contracts", "authorization_intents",
    "authority_observations", "reevaluation_evidence", "delivery_observations",
    "requested_scopes", "recoveries"}
V3_CONTROL_REQUEST_KEYS = V2_CONTROL_REQUEST_KEYS | {"host_route"}
CODEX_ORCHESTRATE = REPO_ROOT / "home/common/codex/skills/orchestrate-issues/SKILL.md"
CODEX_MODULE = REPO_ROOT / "home/common/codex/default.nix"
V2_OWNER_KEYS = {"interface_version", "kind", "ledger_repo_root", "run_id", "issue",
    "attempt", "owner", "action_id", "launch_kind", "worktree", "handoff_path",
    "deadline_at", "custody", "contract", "contract_digest", "pending_stage_ids",
    "requirements", "authority_evaluation", "requested_scope"}
SHIP_HANDOFF_V2_KEYS = {"interface_version", "state", "ledger_repo_root", "run_id",
    "owner", "owner_worktree", "custody", "issue_number", "branch", "worktree_path",
    "spec_artifact", "plan_artifact", "head_sha", "review_state", "auto", "report_path",
    "notes", "delivery_contract", "delivery_contract_digest", "authorization_intents",
    "authorization_chain_digest", "authority_observation_ids", "reevaluation_evidence_ids",
    "authority_evaluation_consumption_ids", "pending_stage_ids", "selected_outputs",
    "requested_scope"}
SHIP_SUMMARY_V2_KEYS = {"interface_version", "issue", "state", "custody",
    "historical_owner_result", "delivery_contract_digest", "delivery_observations",
    "authority_observations", "reevaluation_evidence", "detail_state", "report_path",
    "notes"}

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


SHARED_POLICY_ENTRIES = {
    "design/SKILL.md": ("bindings.paths.artifacts.specs",),
    "doc-grounded-questions/SKILL.md": ("bindings.paths.context", "bindings.paths.standards", "bindings.paths.architecture", "bindings.paths.hints"),
    "from-issue/SKILL.md": ("bindings.tracker", "bindings.vcs", "bindings.paths.artifacts", "bindings.workflow"),
    "grill-with-docs/SKILL.md": ("bindings.paths.context",),
    "research/SKILL.md": ("bindings.paths.artifacts.specs",),
    "ship-issue/SKILL.md": ("bindings.tracker", "bindings.vcs", "bindings.commands", "bindings.workflow.review.code", "bindings.workflow.verification"),
    "ship-release/SKILL.md": ("bindings.tracker", "bindings.vcs", "bindings.commands", "bindings.workflow.release", "bindings.deploy"),
    "to-issues/SKILL.md": ("bindings.tracker", "bindings.paths"),
    "wayfind/SKILL.md": ("bindings.tracker",),
    "worktrees/SKILL.md": ("bindings.vcs",),
    "writing-plans/SKILL.md": ("bindings.paths.artifacts.plans",),
}

CLAUDE_POLICY_ENTRIES = {
    "codex-collaboration/SKILL.md": (
        "bindings.workflow.review.plan", "bindings.workflow.review.code",
        "bindings.commands", "capabilities.review.plan",
        "capabilities.review.code", "bindings.paths.hints",
    ),
    "orchestrate-issues/SKILL.md": (
        "bindings.tracker", "bindings.vcs",
        "bindings.workflow.orchestration.attempt_budget_minutes",
        "bindings.workflow.orchestration.max_parallel",
    ),
}

SHARED_POLICY_SUPPORT = {
    "doc-grounded-questions/REFERENCE.md": ("bindings.paths.context",),
    "from-issue/grounding.md": ("bindings.paths.context", "bindings.paths.standards"),
    "from-issue/investigate.md": ("bindings.tracker", "bindings.vcs"),
    "from-issue/ship-handoff.md": ("bindings.vcs", "bindings.workflow"),
    "from-issue/standards-review.md": ("bindings.paths.standards",),
    "grill-with-docs/ADR-FORMAT.md": ("bindings.paths.context",),
    "sdd/conformance-reviewer-prompt.md": ("bindings.workflow.review.code",),
}

RETAINED_SUPPORT_CONTRACTS = {
    "from-issue/bindings.md": ("bindings.tracker", "bindings.vcs", "bindings.paths.artifacts", "bindings.workflow"),
    "from-issue/AUTO.md": ("bindings.paths.artifacts", "bindings.tracker", "bindings.vcs", "bindings.workflow"),
    "from-issue/REVIEW-CONTRACT.md": ("bindings.workflow.review", "bindings.commands"),
    "grill-with-docs/ADR-FORMAT.md": ("bindings.paths.context",),
    "sdd/conformance-reviewer-prompt.md": ("bindings.workflow.review.code",),
    "ship-issue/CONSOLIDATE.md": ("bindings.paths", "bindings.vcs"),
    "ship-issue/HUMAN-GATE.md": ("bindings.vcs", "bindings.tracker"),
    "ship-issue/SYNC.md": ("bindings.vcs", "bindings.paths.hints"),
    "ship-release/CHANGELOG.md": ("bindings.tracker", "bindings.vcs", "bindings.workflow.release"),
}

# These are deliberate test patterns, not permitted policy text. The tracked
# source scan below honors the `# policy-gate-pattern` line marker only in the
# gate test files named in POLICY_GATE_PATTERN_FILES, where the legacy names are
# the patterns under test; anywhere else the marker exempts nothing.
LEGACY_POLICY_SURFACE = (  # policy-gate-pattern
    "resolve-bindings", ".claude/skills.config.json", "unsetGithubToken",  # policy-gate-pattern
    "projectHints", "docPaths", "specDir", "planDir", "repoSlug",  # policy-gate-pattern
    "issueTracker", "branchNaming", "integrationBranch", "defaultBranch",  # policy-gate-pattern
    "codex.planReview", "codex.codeReview", "commit.coAuthoredBy",  # policy-gate-pattern
    "deploy.services", "deploy.watchDoc", "verify.lint", "verify.test",  # policy-gate-pattern
    "verify.lintFix", "review.criticalPaths", "mergeSubjectTemplate",  # policy-gate-pattern
    "worktreePrefix", "branchPattern", "agentBudgetMinutes", "maxParallel",  # policy-gate-pattern
)

POLICY_GATE_PATTERN_FILES = frozenset({
    "home/common/agent-skills/tests/test_resolve_project.py",
    "home/common/agent-skills/tests/test_workflow_skill_contracts.py",
})

# adopt-project (https://github.com/fagenorn/nix-config/issues/148) migrates a
# legacy checkout onto the strict contract, so it must name the legacy store and
# keys it reads and rewrites. Those are migration inputs, not policy consumers
# (spec decision D12). The scan exempts exactly these tokens in exactly these
# files, and an entry that no longer matches fails it, so the allowance cannot
# outlive its use or widen silently.
LEGACY_MIGRATION_INPUTS = {
    "python/agent_tools/review_task7.py": frozenset({".claude/skills.config.json"}),  # policy-gate-pattern
    "tests/test_review_task7.py": frozenset({".claude/skills.config.json"}),  # policy-gate-pattern
    "python/agent_tools/review_issue100.py": frozenset({"resolve-bindings"}),  # policy-gate-pattern
    # The committed retained evidence (https://github.com/fagenorn/nix-config/issues/235) records the same
    # historical paths as facts of the retained ranges.
    "tests/fixtures/retained-review-evidence/issue-100-derived.json": frozenset({
        ".claude/skills.config.json", "resolve-bindings",  # policy-gate-pattern
    }),
    "tests/fixtures/retained-review-evidence/issue-121.json": frozenset({".claude/skills.config.json"}),  # policy-gate-pattern
    "tests/fixtures/retained-review-evidence/task7-estimate.json": frozenset({".claude/skills.config.json"}),  # policy-gate-pattern
    "python/agent_tools/adopt_inspection.py": frozenset({
        ".claude/skills.config.json", "specDir", "planDir",  # policy-gate-pattern
    }),
    "home/common/agent-skills/tests/test_adopt_apply.py": frozenset({
        ".claude/skills.config.json", "agentBudgetMinutes", "maxParallel",  # policy-gate-pattern
    }),
    "home/common/agent-skills/tests/test_adopt_project.py": frozenset({
        ".claude/skills.config.json", "specDir", "planDir",  # policy-gate-pattern
        "agentBudgetMinutes", "maxParallel",  # policy-gate-pattern
    }),
    "home/common/agent-skills/tests/test_adopt_project_boundaries.py": frozenset({
        ".claude/skills.config.json", "specDir", "planDir",  # policy-gate-pattern
    }),
}

SUPPORT_POLICY_FORBIDDEN = (
    "resolve-project resolve", *LEGACY_POLICY_SURFACE, "auto-detect",
    "helper missing", "not_onboarded", ".claude/specs", ".claude/plans",
    "docs/CONTEXT-MAP.md",
)

CONTEXT_MAP_SELECTION_CONTRACT = (
    "Select context maps only from the retained `bindings.paths.context` list in "
    "authored order: filter entries whose basename is exactly `CONTEXT-MAP.md`; "
    "zero means no map and no linter invocation, one selects that absolute path, "
    "and multiple matches are an invalid caller contract that stops before invocation. "
    "Never probe the filesystem, sort the list, take a first match, or infer a location."
)

RESOLUTION_SENTENCE = (
    "Resolve once at phase entry, retain the returned `ResolvedProject` in "
    "memory, and treat every resolver error as fatal before mutation or "
    "external effects."
)

REFUSAL_REPORTING_SENTENCE = (
    "On refusal, preserve and report the resolver's `error.code`, `repair_id`, "
    "and ordered `violations` exactly; never translate it into a partial snapshot "
    "or fallback."
)


def assert_refusal_reporting(case, text):
    case.assertIn(REFUSAL_REPORTING_SENTENCE, normalized(text))


# RESOLUTION_SENTENCE is the one statement of the resolver rule in a policy
# entry; an opener that restates it is the un-held copy #155 removed (D13).
RESOLUTION_STATEMENT = "`ResolvedProject` in memory"


def assert_single_resolution_statement(case, text):
    case.assertEqual(
        normalized(text).count(RESOLUTION_STATEMENT), 1,
        "a policy entry states the resolver rule once, in RESOLUTION_SENTENCE",
    )


def assert_policy_entries(case, root, entries, require_refusal_reporting=False):
    actual = {str(path.relative_to(root)) for path in root.glob("*/SKILL.md")
              if "resolve-project resolve" in path.read_text(encoding="utf-8")}
    case.assertEqual(actual, set(entries))
    for relative, fields in entries.items():
        text = (root / relative).read_text(encoding="utf-8")
        with case.subTest(relative=relative):
            case.assertEqual(text.count("resolve-project resolve"), 1)
            case.assertIn(RESOLUTION_SENTENCE, normalized(text))
            assert_single_resolution_statement(case, text)
            if require_refusal_reporting:
                assert_refusal_reporting(case, text)
            for field in fields:
                case.assertIn(field, text)
            for forbidden in ("resolve-bindings", ".claude/skills.config.json", "helper missing", "not_onboarded", "auto-detect", "default `"):  # policy-gate-pattern
                case.assertNotIn(forbidden, text)


def assert_retained_policy_support(case, root, documents, forbidden=SUPPORT_POLICY_FORBIDDEN):
    for relative, fields in documents.items():
        text = (root / relative).read_text(encoding="utf-8")
        with case.subTest(relative=relative):
            case.assertEqual(text.count("resolve-project resolve"), 0)
            case.assertIn("retained `ResolvedProject`", text)
            for field in fields:
                case.assertIn(field, text)
            for prohibited in forbidden:
                case.assertNotIn(prohibited, text)


def select_context_map(paths):
    matches = [path for path in paths if Path(path).name == "CONTEXT-MAP.md"]
    if len(matches) > 1:
        raise ValueError("invalid caller contract")
    return matches[0] if matches else None


class ProjectPolicySurfaceTest(unittest.TestCase):
    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    def test_shared_source_phase_entries_use_one_resolved_project(self):
        assert_policy_entries(
            self, REPO_ROOT / "home/common/agent-skills/skills", SHARED_POLICY_ENTRIES,
            require_refusal_reporting=True,
        )

    def test_claude_source_phase_entries_use_one_resolved_project(self):
        assert_policy_entries(
            self,
            REPO_ROOT / "home/common/claude-code/skills",
            CLAUDE_POLICY_ENTRIES,
            require_refusal_reporting=True,
        )

    def test_refusal_reporting_matrix_rejects_a_missing_clause(self):
        text = COLLABORATION.read_text(encoding="utf-8")
        missing = text.replace("error.code", "error kind", 1)
        with self.assertRaises(AssertionError):
            assert_refusal_reporting(self, missing)

    def test_policy_entry_rejects_a_restated_resolution(self):
        text = normalized(DESIGN.read_text(encoding="utf-8"))
        assert_single_resolution_statement(self, text)
        restated = text.replace(
            "Run `resolve-project resolve --repo-root <checkout>`.",
            "Run `resolve-project resolve --repo-root <checkout>` once at phase "
            "entry and retain the full `ResolvedProject` in memory.",
            1,
        )
        self.assertNotEqual(restated, text)
        with self.assertRaises(AssertionError):
            assert_single_resolution_statement(self, restated)

    def test_worktree_contract_uses_retained_schema_fields_and_root(self):
        text = WORKTREES.read_text(encoding="utf-8")
        self.assertIn("bindings.vcs.branch_pattern", text)
        self.assertIn("bindings.vcs.worktree.prefix", text)
        self.assertIn("bindings.vcs.worktree.root", text)
        self.assertIn("against `project.root`", text)
        self.assertNotIn("bindings.vcs.branch_naming", text)
        self.assertNotIn("Put worktrees in `.worktrees/`", text)

    def test_review_capability_routes_before_command_lookup(self):
        for path in (COLLABORATION, SHIP_ISSUE, SDD):
            text = normalized(path.read_text(encoding="utf-8"))
            with self.subTest(path=path):
                capability = text.index("capabilities.review.code")
                lookup = text.index("bindings.commands[review_id].argv")
                self.assertLess(capability, lookup)
                self.assertIn("unsupported", text[capability:lookup])
        # codex-collaboration's own side (issue 195, D6): `unsupported` makes no
        # Codex call, and says so before the command entry is dereferenced.
        self.assert_ordered(
            normalized(COLLABORATION.read_text(encoding="utf-8")),
            "capabilities.review.code", "`unsupported` makes no Codex call",
            "dereference `bindings.commands[review_id]`",
        )
        self.assertIn(
            "An unsupported capability never dispatches Codex, because the "
            "calling controller runs its own native correctness route",
            normalized(DIFF_REVIEW.read_text(encoding="utf-8")),
        )

    def test_living_source_has_no_legacy_policy_surface(self):
        tracked = subprocess.run(
            ["git", "ls-files", "-z", "--", "AGENTS.md", "CLAUDE.md",
             ".agents/instructions", "home/common/agent-skills",
             "home/common/claude-code", "python", "tests"],
            cwd=REPO_ROOT, check=True, capture_output=True,
        ).stdout.split(b"\0")
        text_suffixes = {".md", ".py", ".sh", ".nix", ".json", ".toml", ".yaml", ".yml"}
        historical_prefixes = (Path(".claude/specs"), Path(".claude/plans"))
        legacy = re.compile("|".join(
            re.escape(name) for name in LEGACY_POLICY_SURFACE))
        matches = []
        migration_inputs_seen = {name: set() for name in LEGACY_MIGRATION_INPUTS}
        for encoded in tracked:
            if not encoded:
                continue
            relative = Path(os.fsdecode(encoded))
            if any(relative == prefix or prefix in relative.parents
                   for prefix in historical_prefixes):
                continue
            path = REPO_ROOT / relative
            if not path.is_file():
                continue
            if path.suffix not in text_suffixes and path.name not in {
                "resolve-project", "context-map-lint", "artifact-budget",
                "agent-evidence", "agent-model-matrix", "diff-scope",
                "review-package", "sdd-workspace", "workflow-state",
            }:
                continue
            name = relative.as_posix()
            honors_marker = name in POLICY_GATE_PATTERN_FILES
            migration_inputs = LEGACY_MIGRATION_INPUTS.get(name, frozenset())
            for line_number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), 1):
                if honors_marker and "# policy-gate-pattern" in line:
                    continue
                for match in legacy.finditer(line):
                    token = match.group(0)
                    if token in migration_inputs:
                        migration_inputs_seen[name].add(token)
                    else:
                        matches.append(f"{relative}:{line_number}: {token}")
        self.assertEqual(matches, [])
        self.assertEqual(migration_inputs_seen,
                         {name: set(tokens) for name, tokens in LEGACY_MIGRATION_INPUTS.items()})
        self.assertFalse((REPO_ROOT / ".claude" / "skills.config.json").exists())  # policy-gate-pattern
        self.assertFalse((REPO_ROOT / "home/common/agent-skills/scripts/resolve-bindings").exists())  # policy-gate-pattern
        self.assertFalse((REPO_ROOT / "home/common/agent-skills/tests/test_resolve_bindings.py").exists())  # policy-gate-pattern
        self.assertFalse((REPO_ROOT / "home/common/agent-skills/evals/fixture-repo" /
                          ".claude" / "skills.config.json").exists())  # policy-gate-pattern

    def test_installed_policy_surface_matches_source_contract(self):
        if os.environ.get("WORKFLOW_POLICY_SURFACE") == "source":
            self.skipTest("explicit pre-activation source-only verification")
        agents_root = Path.home() / ".agents/skills"
        claude_root = Path.home() / ".claude/skills"
        self.assertTrue(agents_root.is_dir(), "managed shared skill root is absent")
        self.assertTrue(claude_root.is_dir(), "managed Claude skill root is absent")
        assert_policy_entries(self, agents_root, SHARED_POLICY_ENTRIES,
                              require_refusal_reporting=True)
        assert_policy_entries(self, claude_root,
                              SHARED_POLICY_ENTRIES | CLAUDE_POLICY_ENTRIES,
                              require_refusal_reporting=True)
        assert_retained_policy_support(self, agents_root, SHARED_POLICY_SUPPORT)
        assert_retained_policy_support(self, agents_root, RETAINED_SUPPORT_CONTRACTS)
        self.assertFalse((Path.home() / ".agents/bin/resolve-bindings").exists())  # policy-gate-pattern
        installed_resolver = Path.home() / ".agents/bin/resolve-project"
        self.assertTrue(installed_resolver.is_file())
        self.assertTrue(os.access(installed_resolver, os.X_OK))
        installed_linter = Path.home() / ".agents/bin/context-map-lint"
        self.assertTrue(installed_linter.is_file())
        self.assertTrue(os.access(installed_linter, os.X_OK))
        installed_legacy = re.compile("|".join(re.escape(name) for name in (
            "resolve-bindings", ".claude/skills.config.json", "unsetGithubToken",  # policy-gate-pattern
        )))
        self.assertIsNone(installed_legacy.search(
            installed_linter.read_text(encoding="utf-8")))

    def test_installed_policy_surface_refuses_when_managed_roots_are_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.dict(os.environ, {"WORKFLOW_POLICY_SURFACE": ""}, clear=False):
                with mock.patch("pathlib.Path.home", return_value=Path(temporary)):
                    with self.assertRaisesRegex(AssertionError, "managed shared skill root is absent"):
                        self.test_installed_policy_surface_matches_source_contract()

    def _install_policy_surface_fixture(self, home):
        agents_root = home / ".agents/skills"
        claude_root = home / ".claude/skills"
        shared_source = REPO_ROOT / "home/common/agent-skills/skills"
        claude_source = REPO_ROOT / "home/common/claude-code/skills"
        shutil.copytree(shared_source, agents_root)
        shutil.copytree(shared_source, claude_root)
        shutil.copytree(claude_source, claude_root, dirs_exist_ok=True)
        helpers = {
            "resolve-project": home / ".agents/bin/resolve-project",
            "context-map-lint": home / ".agents/bin/context-map-lint",
        }
        helpers["context-map-lint"].parent.mkdir(parents=True)
        shutil.copy2(
            REPO_ROOT / "python/agent_tools/resolve_project.py",
            helpers["resolve-project"],
        )
        shutil.copyfile(REPO_ROOT / "python/agent_tools/context_map_lint.py",
                        helpers["context-map-lint"])
        for helper in helpers.values():
            helper.chmod(0o755)
        return helpers

    def _assert_installed_policy_surface(self, home):
        with mock.patch.dict(os.environ, {"WORKFLOW_POLICY_SURFACE": ""}, clear=False):
            with mock.patch("pathlib.Path.home", return_value=home):
                self.test_installed_policy_surface_matches_source_contract()

    def test_installed_policy_surface_applies_both_support_matrices(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            self._install_policy_surface_fixture(home)
            self._assert_installed_policy_surface(home)

    def test_installed_policy_surface_rejects_missing_and_nonexecutable_helpers(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            helpers = self._install_policy_surface_fixture(home)
            self._assert_installed_policy_surface(home)
            for name, helper in helpers.items():
                contents = helper.read_bytes()
                mode = helper.stat().st_mode
                with self.subTest(helper=name, case="missing"):
                    helper.unlink()
                    with self.assertRaisesRegex(AssertionError, "False is not true"):
                        self._assert_installed_policy_surface(home)
                    helper.write_bytes(contents)
                    helper.chmod(mode)
                with self.subTest(helper=name, case="non-executable"):
                    helper.chmod(mode & ~0o111)
                    with self.assertRaisesRegex(AssertionError, "False is not true"):
                        self._assert_installed_policy_surface(home)
                    helper.chmod(mode)
                self._assert_installed_policy_surface(home)

    def test_eval_runner_reports_a_resolver_refusal_without_a_second_resolution(self):
        runner = (REPO_ROOT / "home/common/agent-skills/evals/run-eval.sh").read_text(
            encoding="utf-8")
        self.assertEqual(runner.count("resolve-project resolve --repo-root \"$REPO\""), 1)
        self.assertIn(
            'if ! RESOLVED_PROJECT=$(resolve-project resolve --repo-root "$REPO"); then\n'
            "    printf '%s\\n' \"$RESOLVED_PROJECT\" >&2\n"
            '    die "resolver refused the initialized fixture"\n'
            "  fi",
            runner,
        )

    def test_live_evals_grade_strict_policy_and_direct_review(self):
        paths = (
            REPO_ROOT / "home/common/agent-skills/skills/from-issue/evals/evals.json",
            REPO_ROOT / "home/common/agent-skills/skills/sdd/evals/evals.json",
            REPO_ROOT / "home/common/agent-skills/skills/ship-issue/evals/evals.json",
            REPO_ROOT / "home/common/agent-skills/skills/ship-release/evals/evals.json",
            REPO_ROOT / "home/common/agent-skills/skills/wayfind/evals/evals.json",
            REPO_ROOT / "home/common/agent-skills/skills/writing-plans/evals/evals.json",
            REPO_ROOT / "home/common/claude-code/skills/codex-collaboration/evals/evals.json",
            REPO_ROOT / "home/common/claude-code/skills/orchestrate-issues/evals/evals.json",
        )
        corpus = "\n".join(
            str(json.loads(path.read_text(encoding="utf-8"))) for path in paths
        )
        for forbidden in (
            "resolve-bindings", ".claude/skills.config.json", "unsetGithubToken",  # policy-gate-pattern
            "helper missing", "auto-detect absent", "default GitHub",
        ):
            self.assertNotIn(forbidden, corpus)
        for required in (
            "ResolvedProject", "bindings.workflow.review.code",
            "bindings.commands", "gpt-6-astra", "--effort xhigh",
            "runtime.reasoningEffort", "rawOutput",
        ):
            self.assertIn(required, corpus)

    def test_shared_support_documents_reuse_the_retained_snapshot(self):
        assert_retained_policy_support(
            self, REPO_ROOT / "home/common/agent-skills/skills", SHARED_POLICY_SUPPORT,
            ("resolve-bindings", "skills.config.json", "helper missing", "not_onboarded", "auto-detect", ".claude/specs", ".claude/plans", "docs/CONTEXT-MAP.md"),  # policy-gate-pattern
        )

    def test_listed_support_documents_reuse_only_passed_snapshot_fields(self):
        assert_retained_policy_support(self, REPO_ROOT / "home/common/agent-skills/skills", RETAINED_SUPPORT_CONTRACTS)

    def test_sdd_configured_review_pair_is_complete(self):
        assert_configured_code_review_pair(self, SDD, SDD_DIR / "final-review.md")

    def test_ship_issue_configured_review_pair_is_complete(self):
        assert_configured_code_review_pair(self, SHIP_ISSUE, SHIP_ISSUE_REVIEW)

    def test_configured_review_paragraph_copies_stay_identical(self):
        # ship-issue REVIEW.md and sdd final-review.md share one configured-review
        # paragraph, so its capacity scope changes in both at once (issue 195, D7).
        def paragraph(path):
            text = path.read_text(encoding="utf-8")
            start = text.index("For configured code review,")
            return text[start:text.index("\n", start)]
        self.assertEqual(paragraph(SHIP_ISSUE_REVIEW),
                         paragraph(SDD_DIR / "final-review.md"))

    def test_codex_plan_review_owner_and_support_are_complete(self):
        assert_codex_operation_pair(
            self, CODEX_PLAN_REVIEW, "bindings.workflow.review.plan",
            ("Blocking", "Should fix", "Discussion"),
        )

    def test_codex_diff_review_owner_and_support_are_complete(self):
        assert_codex_operation_pair(
            self, DIFF_REVIEW, "bindings.workflow.review.code",
            ("Critical", "Important", "Minor"),
        )

    def test_ship_correctness_route_is_the_capability_ladder(self):
        route = ship_correctness_route()
        assert_correctness_route_ladder(self, route, SHIP_CORRECTNESS_TARGET)
        route = normalized(route)
        self.assertIn(
            "This is the only rung that reaches Codex and the only one where a "
            "capacity rejection binds, on the terms in REVIEW.md.", route)
        # sdd words its rung 2 differently, so ship pins its own
        # non-capacity sentence inside rung 2 (D14).
        rung_2 = route[route.index("2. `available`"):route.index("3. `unsupported`")]
        self.assertIn(
            "A completed non-capacity failure takes that skill's one native "
            "fallback.", rung_2)
        self.assertIn(
            "A Codex call made under `unsupported` anyway is a routing error: "
            "discard its outcome — verdict, refusal or failure — record the "
            "routing error in the PR body beside the correctness verdict, and "
            "run the rung-3 native dispatch, with no retry, stop or suspension.",
            route)
        # REVIEW.md names the rung-3 template as the native form, not a
        # fallback (D13).
        self.assertIn(
            "the native correctness form uses `correctness-reviewer-prompt.md`",
            normalized(SHIP_ISSUE_REVIEW.read_text(encoding="utf-8")))

    def test_correctness_route_ladder_rejects_each_broken_route(self):
        # The helper is not vacuous: putting the pre-fix route back, or breaking
        # one clause of the ladder, makes it raise (issue 195, D3).
        ship = SHIP_ISSUE.read_text(encoding="utf-8")
        ladder = ship[
            ship.index("Run it in parallel with the correctness axis"):
            ship.index("<!-- agent-dispatch: id=ship-issue-full-correctness-fallback")
        ]
        mutants = {
            "pre-fix route": (ladder, SHIP_PRE_FIX_ROUTE + "\n\n"),
            # Injected after rung 3's full lead, so the lead check passes and
            # the rung's no-`diff-review` guard is what raises.
            "diff-review in rung 3": (
                "this native first-pass dispatch, directly",
                "this native first-pass dispatch via `diff-review`, directly"),
            "capacity rule leaves rung 2": (
                "a capacity rejection binds", "a refusal binds"),
            "routing-error outcome kept": (
                "discard its outcome", "keep its outcome"),
            "rung 3 invokes codex-collaboration": (
                "is never invoked on this rung", "is always invoked on this rung"),
            "rung 3 drops available without the skill": (
                ", or `available` without `codex-collaboration` installed →",
                " →"),
            "routing error skips the native dispatch": (
                "run the rung-3 native dispatch", "skip the rung-3 native dispatch"),
        }
        for name, (old, new) in mutants.items():
            with self.subTest(mutant=name):
                self.assertTrue(old in ship, f"mutant anchor missing: {old!r}")
                with self.assertRaises(AssertionError):
                    assert_correctness_route_ladder(
                        self, ship_correctness_route(ship.replace(old, new)),
                        SHIP_CORRECTNESS_TARGET)

    def test_sdd_correctness_route_is_the_capability_ladder(self):
        route = sdd_correctness_route()
        assert_correctness_route_ladder(self, route, SDD_CORRECTNESS_TARGET)
        route = normalized(route)
        self.assertIn(
            "This is the only rung that reaches Codex and the only one where a "
            "capacity rejection binds, on the configured-review terms above.", route)
        self.assertIn(
            "A Codex call made under `unsupported` anyway is a routing error: "
            "discard its outcome — verdict, refusal or failure — record the "
            "routing error in the ledger beside the correctness verdict, with the "
            "axis's reviewer identity still `native`, and run the rung-3 native "
            "dispatch, with no retry, stop or suspension.", route)
        # sdd words its rungs 2 and 3 and its routing-error paragraph
        # differently from ship, so sdd pins its own sentences (D14).
        rung_2 = route[route.index("2. `available`"):route.index("3. `unsupported`")]
        self.assertIn(
            "→ invoke its `diff-review` operation for this axis; that skill "
            "solely owns the isolated Codex transport launch and one-time native "
            "fallback, while the external Codex reviewer keeps its independently "
            "configured model.", rung_2)
        rung_3 = route[route.index("3. `unsupported`"):route.index("routing error")]
        self.assertIn(
            "→ dispatch the Opus/high native reviewer selected in "
            f"{SDD_CORRECTNESS_TARGET} directly; `codex-collaboration` is never "
            "invoked on this rung.", rung_3)
        self.assertTrue(route.rstrip().endswith(
            "The axis is never skipped; `blocked` stops the whole review "
            "instead."), route)
        # The agent-tiers bullet and the rubric header restate the same route.
        self.assertIn(
            "the correctness axis via `codex-collaboration`'s `diff-review` when "
            "`capabilities.review.code` is `available` and that skill is "
            "installed, and as `reviewer` on Opus/high when the capability is "
            "`unsupported` or the skill is not installed (`blocked` stops)",
            normalized(SDD.read_text(encoding="utf-8")))
        self.assertIn(
            "dispatched directly when `capabilities.review.code` is `unsupported` "
            "or `codex-collaboration` is not installed. When the capability is "
            "`available` and that skill is installed, its `diff-review` operation "
            "carries this file",
            normalized((SDD_DIR / "correctness-reviewer-prompt.md").read_text(
                encoding="utf-8")))

    def test_correctness_route_ladder_rejects_the_pre_fix_sdd_route(self):
        # Putting sdd's skill-presence routing back makes the helper raise
        # (issue 195, D3), and so does reversing rung 3's no-invocation
        # clause, which in sdd sits after the native target (D12).
        text = (SDD_DIR / "final-review.md").read_text(encoding="utf-8")
        end_anchor = "`blocked` stops the whole review instead."
        no_invocation = "is never invoked on this rung"
        self.assertTrue(CORRECTNESS_ROUTE_OPENER in text and end_anchor in text
                        and no_invocation in text, "sdd ladder anchors missing")
        start = text.index(CORRECTNESS_ROUTE_OPENER)
        end = text.index(end_anchor, start) + len(end_anchor)
        with self.assertRaises(AssertionError):
            assert_correctness_route_ladder(
                self,
                sdd_correctness_route(text[:start] + SDD_PRE_FIX_ROUTE + text[end:]),
                SDD_CORRECTNESS_TARGET)
        with self.assertRaises(AssertionError):
            assert_correctness_route_ladder(
                self,
                sdd_correctness_route(text.replace(
                    no_invocation, "is always invoked on this rung")),
                SDD_CORRECTNESS_TARGET)

    def test_context_map_selection_uses_only_authored_order(self):
        table = (
            ([], None),
            (["/repo/CONTEXT.md"], None),
            (["/repo/other.md", "/repo/CONTEXT-MAP.md", "/repo/end.md"], "/repo/CONTEXT-MAP.md"),
        )
        for paths, expected in table:
            with self.subTest(paths=paths):
                self.assertEqual(select_context_map(paths), expected)
        with self.assertRaisesRegex(ValueError, "invalid caller contract"):
            select_context_map(["/repo/a/CONTEXT-MAP.md", "/repo/b/CONTEXT-MAP.md"])

    def test_context_map_consumers_forbid_discovery(self):
        for relative in ("doc-grounded-questions/SKILL.md", "grill-with-docs/SKILL.md", "grill-with-docs/CONTEXT-FORMAT.md"):
            text = (REPO_ROOT / "home/common/agent-skills/skills" / relative).read_text(encoding="utf-8")
            contract = normalized(text)
            self.assertIn(CONTEXT_MAP_SELECTION_CONTRACT, contract)
            for forbidden in (
                "legacy context-map setting", "docs/CONTEXT-MAP.md", "select the first match",
                "sort(", "filesystem search", "first match wins", "default map location",
            ):
                self.assertNotIn(forbidden, contract)

    def test_context_map_lint_invocations_pass_root_and_selected_map(self):
        invocation = re.compile(r"`(?:~/\.agents/bin/)?context-map-lint( [^`]*)`")
        found = []
        for root in (REPO_ROOT / "home/common/agent-skills/skills",
                     REPO_ROOT / "home/common/claude-code/skills"):
            for path in sorted(root.rglob("*.md")):
                for match in invocation.finditer(path.read_text(encoding="utf-8")):
                    arguments = match.group(1)
                    with self.subTest(path=path.relative_to(REPO_ROOT), arguments=arguments):
                        found.append(path.relative_to(REPO_ROOT).as_posix())
                        self.assertRegex(arguments, r"^ --repo-root \S.* --context-map \S")
        self.assertIn("home/common/agent-skills/skills/grill-with-docs/SKILL.md", found)
        self.assertIn("home/common/agent-skills/skills/grill-with-docs/CONTEXT-FORMAT.md", found)

    def test_build_delivery_callers_name_the_sanctioned_resolution_exception(self):
        exception = ("only sanctioned exception is `workflow-state build-delivery`, "
                     "which performs its own sealed, read-only resolution")
        callers = []
        for root in (REPO_ROOT / "home/common/agent-skills/skills",
                     REPO_ROOT / "home/common/claude-code/skills"):
            for path in sorted(root.rglob("*.md")):
                text = normalized(path.read_text(encoding="utf-8"))
                if "build-delivery" not in text:
                    continue
                callers.append(path.relative_to(REPO_ROOT).as_posix())
                with self.subTest(path=path.relative_to(REPO_ROOT)):
                    self.assertIn(exception, text)
        self.assertEqual(sorted(callers), [
            "home/common/agent-skills/skills/from-issue/SKILL.md",
            "home/common/agent-skills/skills/from-issue/ship-handoff.md",
            "home/common/agent-skills/skills/ship-issue/SKILL.md",
            "home/common/claude-code/skills/orchestrate-issues/SKILL.md",
        ])


# The capacity rule binds only on the `available` route, and a Codex call made
# under `unsupported` is classified beside it (issue 195, D7, D9).
CAPACITY_SCOPE_ANCHORS = (
    "`available` route", "capacity rejection", "no retry", "no native fallback",
    "routing error, never a capacity rejection",
)


# Issue 236: the one review binding shape, its invocation and validation (D12-D15).
CODEX_SHAPE_CLASSIFIER_ANCHORS = (
    "one supported review binding shape",
    "basename of `argv[0]` is exactly `codex-companion`",
    "`argv[1]` is `task`",
    "`--reviewer <op>`",
    "optional `--fresh`",
    'bare `["codex"]` included',
    "binding shape error",
)
CODEX_SHAPE_ERROR_ANCHORS = (
    "binding shape error is a configuration error",
    "no Codex call", "no retry", "no native fallback",
    "`review_id`", "authored argv",
    "`codex-companion task [--fresh] --reviewer <op>`",
    "an executable other than `codex-companion`",
    "a companion subcommand other than `task`",
    "a missing or mismatched `--reviewer`",
    "an unsupported companion token",
    "no capability repair ID",
)
# In text order: the stdin sentence precedes the tail.
CODEX_COMPANION_INVOCATION_ANCHORS = (
    "no positional argument",
    "--model gpt-6-astra --effort xhigh",
    "--cwd <absolute-worktree> --json",
)
CODEX_COMPANION_VALIDATION_ANCHORS = (
    "exactly one JSON object",
    "`status` is `0`",
    "`touchedFiles` is empty",
    "`runtime.model` is `gpt-6-astra`",
    "`runtime.reasoningEffort` is `xhigh`",
    "`rawOutput` is a non-empty string",
    "last captured agent message",
)
# Retired with the exec route (D12, D17): none may reappear in the skill, the
# two caller paragraphs or the evals.
RETIRED_EXEC_REVIEW_TOKENS = (
    "exec --sandbox", "--output-last-message", "terminal agent-message",
    "model_reasoning_effort", "JSONL", "Exec shape", "exec shape",
)


# The configured-review paragraph's closing sentences: authored `unsupported`
# is the caller's primary native route, not a fallback, and only the
# `available` route's non-capacity failure falls back (issue 195, D15).
CONFIGURED_REVIEW_UNSUPPORTED_ROUTE = (
    "Authored `unsupported` takes the caller's native correctness route "
    "directly and makes no Codex call."
)
CONFIGURED_REVIEW_AVAILABLE_FALLBACK = (
    "On the `available` route, a completed non-capacity runtime/output failure "
    "uses the existing single native fallback and records why."
)


def assert_configured_code_review_pair(case, owner, support):
    owner_text = normalized(owner.read_text(encoding="utf-8"))
    support_text = normalized(support.read_text(encoding="utf-8"))
    case.assert_ordered(owner_text, "bindings.workflow.review.code", "capabilities.review.code", "bindings.commands[review_id].argv")
    case.assert_ordered(
        support_text,
        "For configured code review,",
        "`codex-collaboration`'s `diff-review`",
        "binding shape error",
        "no Codex call",
        "`blocked` stops", *CAPACITY_SCOPE_ANCHORS,
        CONFIGURED_REVIEW_UNSUPPORTED_ROUTE, CONFIGURED_REVIEW_AVAILABLE_FALLBACK,
    )
    # The skill owns the shape, invocation and validation; a caller restating
    # them is the duplication D20 removed.
    for restated in ("basename of `argv[0]`", *CODEX_COMPANION_INVOCATION_ANCHORS[1:],
                     *CODEX_COMPANION_VALIDATION_ANCHORS[:-1]):
        case.assertNotIn(restated, support_text)
    for retired in RETIRED_EXEC_REVIEW_TOKENS:
        case.assertNotIn(retired, support_text)
    # The pre-D15 sentence called the primary `unsupported` route a fallback.
    case.assertNotIn("Authored unsupported or a completed non-capacity", support_text)
    for text in (owner_text, support_text):
        case.assertNotIn("command -v codex-companion", text)
        case.assertNotIn('subagent_type="codex:codex-reviewer"', text)


# Both correctness-axis callers open their route with this sentence and then
# number the three rungs (issue 195, D4, D5).
CORRECTNESS_ROUTE_OPENER = (
    "Choose the correctness route from the retained `capabilities.review.code` "
    "state before either axis is dispatched, never from how a Codex call failed:"
)
SHIP_CORRECTNESS_TARGET = "id=ship-issue-full-correctness-fallback"
# ship-issue Phase 5's correctness sentence before issue 195, kept only so the
# ladder helper's self-check can put it back.
SHIP_PRE_FIX_ROUTE = (
    "Run it in parallel with the correctness axis via `codex-collaboration`'s "
    "`diff-review`; when that capability is unavailable, use this native "
    "first-pass dispatch instead:"
)
SDD_CORRECTNESS_TARGET = "[correctness-reviewer-prompt.md](correctness-reviewer-prompt.md)"
# sdd final-review's correctness routing before issue 195, kept only so the
# ladder helper's self-check can put it back.
SDD_PRE_FIX_ROUTE = (
    "When the `codex-collaboration` skill is available, invoke its `diff-review` "
    "operation for this axis; that skill solely owns the isolated Codex transport "
    "launch and one-time native fallback, while the external Codex reviewer keeps "
    "its independently configured model. Unavailable → use the Opus/high native "
    "reviewer selected in [correctness-reviewer-prompt.md]"
    "(correctness-reviewer-prompt.md). Either way the axis is never skipped."
)


def sdd_correctness_route(text=None):
    """sdd final-review's correctness-axis bullet, through its routing-error paragraph."""
    if text is None:
        text = (SDD_DIR / "final-review.md").read_text(encoding="utf-8")
    start = text.index("- **Correctness axis**")
    return text[start:text.index("Point the conformance dispatch", start)]


def ship_correctness_route(text=None):
    """ship-issue Phase 5's full-review text, up to its scope-recording sentence."""
    if text is None:
        text = SHIP_ISSUE.read_text(encoding="utf-8")
    start = text.index("**Full two-axis review.**")
    return text[start:text.index("Axis reports are never merged", start)]


def assert_correctness_route_ladder(case, route, native_target):
    """Pin one caller's correctness-axis route (issue 195, D2, D4, D5).

    The route opens with CORRECTNESS_ROUTE_OPENER and numbers the `blocked`,
    `available` and `unsupported` rungs in that order, each with its full lead
    clause (D14). Only the `available` rung
    names `diff-review`, and it names the capacity rejection after it. The
    `unsupported` rung reaches `native_target` without naming `diff-review` or
    `bindings.commands`, and before the routing-error paragraph it says that
    `codex-collaboration` is never invoked on that rung. The routing-error
    action follows the ladder, and no skill-presence wording survives.
    """
    route = normalized(route)
    case.assert_ordered(
        route, CORRECTNESS_ROUTE_OPENER, "1. `blocked`", "2. `available`",
        "3. `unsupported`", native_target, "routing error", "discard its outcome",
        "beside the correctness verdict", "rung-3 native dispatch",
        "no retry, stop or suspension",
    )
    blocked_at = route.index("1. `blocked`")
    available_at = route.index("2. `available`")
    unsupported_at = route.index("3. `unsupported`")
    available = route[available_at:unsupported_at]
    unsupported = route[unsupported_at:route.index(native_target, unsupported_at)]
    # Each rung's lead, which both callers word identically. The two
    # skill-presence clauses are D5's routing condition (D14).
    case.assertIn(
        "1. `blocked` stops with its capability reason and repair ID; "
        "neither axis is dispatched.", route[blocked_at:available_at])
    case.assertTrue(available.startswith(
        "2. `available`, with `codex-collaboration` installed →"), available)
    case.assertTrue(unsupported.startswith(
        "3. `unsupported`, or `available` without `codex-collaboration` "
        "installed →"), unsupported)
    case.assert_ordered(available, "`diff-review`", "capacity rejection")
    for absent in ("diff-review", "bindings.commands"):
        case.assertNotIn(absent, unsupported)
    # The whole rung, through its dispatch, up to the routing-error paragraph:
    # sdd's no-invocation clause sits after its native target (D12).
    unsupported_rung = route[
        unsupported_at:route.index("routing error", unsupported_at)]
    case.assertIn(
        "`codex-collaboration` is never invoked on this rung", unsupported_rung)
    # The routing-error action's tail, which both callers word identically.
    case.assertIn(
        ", and run the rung-3 native dispatch, with no retry, stop or "
        "suspension.", route[route.index("routing error", unsupported_at):])
    case.assertEqual(route.count("diff-review"), available.count("diff-review"))
    case.assertNotIn("unavailable", route.lower())
    case.assertNotIn("skill is available", route)


def assert_codex_operation_pair(case, support, review_field, headings):
    owner = normalized(COLLABORATION.read_text(encoding="utf-8"))
    support_text = normalized(support.read_text(encoding="utf-8"))
    case.assert_ordered(
        owner,
        review_field,
        *CODEX_SHAPE_CLASSIFIER_ANCHORS, *CODEX_SHAPE_ERROR_ANCHORS,
        CODEX_COMPANION_INVOCATION_ANCHORS[0],
        "bindings.commands[review_id].argv",
        *CODEX_COMPANION_INVOCATION_ANCHORS[1:],
        *CODEX_COMPANION_VALIDATION_ANCHORS,
        *CAPACITY_SCOPE_ANCHORS,
    )
    for retired in RETIRED_EXEC_REVIEW_TOKENS:
        case.assertNotIn(retired, owner)
    case.assertIn("retained `ResolvedProject`", support_text)
    case.assertIn(review_field, support_text)
    for heading in headings:
        case.assertIn(heading, support_text)
    case.assertNotIn("resolve-project resolve", support_text)


def corpus_documents():
    """Every skill document in both skill trees, as (path, text) pairs."""
    for root in SKILL_ROOTS:
        for path in sorted(root.rglob("*.md")):
            yield path, path.read_text(encoding="utf-8")


def nested_workflow_documents():
    for directory in (FROM_ISSUE_DIR, SDD_DIR):
        for path in sorted(directory.glob("*.md")):
            yield path, path.read_text(encoding="utf-8")


def json_block(text):
    match = re.search(r"```json\n(\{.*?\})\n```", text, re.DOTALL)
    if match is None:
        raise AssertionError("missing json block")
    return json.loads(match.group(1))


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
        cls.research = RESEARCH.read_text(encoding="utf-8")
        cls.worktrees = WORKTREES.read_text(encoding="utf-8")
        cls.ship_issue = SHIP_ISSUE.read_text(encoding="utf-8")
        cls.ship_review = SHIP_ISSUE_REVIEW.read_text(encoding="utf-8")
        cls.ship_ci_merge = SHIP_ISSUE_CI_MERGE.read_text(encoding="utf-8")
        cls.ship_human_gate = SHIP_ISSUE_HUMAN_GATE.read_text(encoding="utf-8")
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

    def test_codex_collaboration_evals_describe_only_the_companion_shape(self):
        evals = {item["id"]: item for item in self.codex_collaboration_evals["evals"]}
        companion_tail = "--model gpt-6-astra --effort xhigh --cwd <absolute-worktree> --json"
        self.assertIn(
            '["codex-companion","task","--fresh","--reviewer","plan-review"]',
            evals[1]["prompt"],
        )
        for eval_id in (1, 2, 3):
            expected = evals[eval_id]["expected_output"]
            for fragment in (
                companion_tail, "no positional argument", "touchedFiles",
                "runtime.model gpt-6-astra", "runtime.reasoningEffort xhigh",
                "rawOutput", "binding shape error",
                "codex-companion task [--fresh] --reviewer <op>",
            ):
                with self.subTest(eval=eval_id, fragment=fragment):
                    self.assertIn(fragment, expected)
            for retired in RETIRED_EXEC_REVIEW_TOKENS:
                with self.subTest(eval=eval_id, retired=retired):
                    self.assertNotIn(retired, evals[eval_id]["prompt"] + expected)

    def test_delivery_interface_two_is_one_atomic_production_caller_contract(self):
        documents = {
            str(path.relative_to(REPO_ROOT)): normalized(path.read_text(encoding="utf-8"))
            for path in (FROM_ISSUE, AUTO, FROM_ISSUE.parent / "ship-handoff.md",
                         SHIP_ISSUE, SHIP_ISSUE_REVIEW, SHIP_ISSUE_HUMAN_GATE,
                         ORCHESTRATE)
        }
        corpus = " ".join(documents.values())
        for phrase in ("workflow-response", "validate before decoding", "custody",
                       "current-launch", "requested_scope", "bind the actual invocation",
                       "ship-checkpoint/v2", "ship-summary/v2", "delivery_remainder"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, corpus)
        self.assertIn("workflow_bootstrap", normalized(self.orchestrate))
        self.assertIn("bootstrap requirement", normalized(self.orchestrate))
        self.assertIn("checkpoint-delivery", corpus)
        self.assertNotIn("infer the next stage from tracker", corpus.lower())
        self.assertNotIn("unfinished delivery as failed", corpus.lower())
        terminal = normalized(self.section(
            FROM_ISSUE.read_text(encoding="utf-8"),
            "## Terminal return procedure", "## Suspension procedure"
        ))
        self.assertIn("--summary-file", terminal)
        self.assertIn("historical input only", terminal)
        self.assertNotIn("--result-file <path>", terminal)

    def test_direct_and_control_requests_are_interface_two(self):
        direct = self.section(self.from_issue, "### Direct autonomous acquisition",
                              "### Interactive direct acquisition")
        request = json_block(direct)
        self.assertEqual((set(request), request["interface_version"]),
                         (V2_DIRECT_REQUEST_KEYS, 2))
        for anchor in ("`delivery_contract`", "--kind contract", "`authorization_intents`",
                       "kind: delivery_remainder", "--request-file -"):
            self.assertIn(anchor, normalized(direct))
        decide = self.section(self.orchestrate, "## 3. Decide", "## 4. Execute control actions")
        request = json_block(decide)
        self.assertEqual((set(request), request["interface_version"], request["host_route"]),
                         (V3_CONTROL_REQUEST_KEYS, 3, "claude-code"))
        for anchor in ("workflow-state build-delivery",
                       "while its latest summary carries `delivery_contract_required`",
                       "report the refusal", "--request-file -",
                       "only when this invocation created the run"):
            self.assertIn(anchor, normalized(decide))
        durable = self.section(self.from_issue, "### Explicit durable interactive acquisition",
                               "## The flow")
        self.assertIn("only when this invocation created the run", normalized(durable))
        self.assertIn('`host_route: "direct"`', normalized(durable))

    def test_contract_builders_state_the_resolution_root_and_relay_refusals(self):
        direct = normalized(self.section(self.from_issue, "### Direct autonomous acquisition",
                                         "### Interactive direct acquisition"))
        decide = normalized(self.section(self.orchestrate, "## 3. Decide",
                                         "## 4. Execute control actions"))
        for skill, text in (("from-issue", direct), ("orchestrate-issues", decide)):
            with self.subTest(skill=skill):
                self.assertIn(BUILD_ROOT_CLAUSE, text)
                self.assertIn(BUILD_REFUSAL_RELAY, text)

    def test_orchestrate_bootstrap_actions_and_projected_owner(self):
        observe = normalized(self.section(self.orchestrate, "## 2. Bootstrap and observe",
                                          "## 3. Decide"))
        for anchor in ("workflow_bootstrap", "`contract_digest`", "`forge_pr`",
                       "never a candidate for it"):
            self.assertIn(anchor, observe)
        execute = normalized(self.section(self.orchestrate, "## 4. Execute control actions",
                                          "## 5. Final report"))
        for anchor in ("`spawn`, `resume`, `retry`, `delivery_remainder`, `delivery_contract`, "
                       "`wait`, or `finalize`",
                       "rename `id` to `action_id` and `kind` to `launch_kind`",
                       "`kind: owner`", "`interface_version: 2`", "canonical JSON",
                       "--boundary workflow-response"):
            self.assertIn(anchor, execute)
        self.assertNotIn("Interface_version 2 control adapter", self.orchestrate)

    def test_ship_handoff_v2_ship_summary_v2_and_remainder_prompt(self):
        line = next(item for item in self.ship_handoff.splitlines()
                    if item.startswith('{"interface_version":2'))
        self.assertLessEqual(SHIP_HANDOFF_V2_KEYS, set(re.findall(r'"([a-z_]+)":', line)))
        for key in SHIP_SUMMARY_V2_KEYS:
            self.assertIn(f"`{key}`", self.ship_handoff)
        for anchor in ("--kind initial-intent", "--boundary ship-summary",
                       "## Remainder owner prompt"):
            self.assertIn(anchor, self.ship_handoff)
        self.assertNotIn("## Delivery handoff v2", self.ship_handoff)

    def test_ship_issue_writer_rule_delivery_loop_and_remainder_mode(self):
        self.assertIn(WRITER_RULE, normalized(self.ship_issue))
        self.assertNotIn("never writes workflow-state itself", normalized(self.ship_issue))
        loop = normalized(self.section(self.ship_issue, "## Delivery loop", "## Remainder mode"))
        self.assert_ordered(loop, "pre-merge selection gate", "--kind selected-output",
            "`selected_output`, `branch_published` and `pr_opened`", "checkpoint-delivery",
            "equal the scope", "current-launch", "current-launch", "authority-observation",
            "observation-only", "`human_gate`", "`delivery_complete`")
        self.assert_ordered(loop, "the denied stage's scope as `requested_scope`",
                            "`state: suspended`", "`blocked_on: human_gate`", "fail loudly")
        remainder = normalized(self.ship_issue.split("## Remainder mode", 1)[1])
        for anchor in ("`delivery_remainder`", "ready stage", "finish --summary-file -",
                       "`delivery_stalled`"):
            self.assertIn(anchor, remainder)
        for text in (self.ship_handoff.split("## Remainder owner prompt", 1)[1],
                     self.section(self.from_issue, "### Dispatcher-owned acquisition",
                                  "### Direct autonomous acquisition"),
                     self.section(self.from_issue, "3. **`kind: delivery_remainder`**",
                                  "4. **`kind: terminal`**")):
            self.assertIn("re-entry line", normalized(text))
        for appendix in (self.ship_review, self.ship_human_gate):
            self.assertIn("## Delivery loop", appendix)

    def test_ship_issue_post_selection_sync_route(self):
        """#192 T11: CI-MERGE.md owns the route; SKILL.md points to it from five places.

        The fifth is Phase 5's merge-delta reviewer, which only that route dispatches (#264).
        """
        route = normalized(self.ship_ci_merge.split("## Post-selection sync", 1)[1])
        self.assert_ordered(route, "**sync selection**", "whoever holds the merge gate",
            "**current selection**", "`--kind current-selection`",
            "`implementation_delivered`", "*sync run*",
            "`git merge-base --is-ancestor", "one sync selection, oldest first",
            "`gh pr view <pr-num> --json state,headRefOid,mergeable`",
            "`mergeable: CONFLICTING`", "merely behind", "resume at step 3",
            "`mergeable: UNKNOWN`", "proceed to the merge",
            "not an authority denial", "no `authority-observation`")
        self.assert_ordered(route, "**Sync.**", "[`SYNC.md`](./SYNC.md)", "**Verify.**",
            "Run Phase 2's verification step.", "**Review.**", "`git show --cc", "merge-delta reviewer",
            "re-run Phase 2's verification step before the push",
            "`merge-delta-empty`", "`merge-delta-clean`", "**Push.**", "`check-launch`",
            "`git push origin <branch>`", "**Wait for CI.**", "Phase 6's CI wait",
            "**Select.**", "--kind sync-selection", "`git rev-list --parents -n 1",
            "`test_ref` `checks`", "`branch_published` and `pr_opened`",
            "`--kind scope` for `merge_pr`", "**Merge.**")
        self.assert_ordered(route, "**A merge that already landed.**",
            "without a push or a CI wait", "`pr_merged` observation", "**Stops.**",
            "genuinely-blocked stop", "In `--auto`, a step-1 conflict", "`git merge --abort`",
            "Should-fix", "`terminal_failed` `ship-summary/v2`", "`stopped` row",
            "its own `finish`")
        self.assertNotIn("Agent(", self.ship_ci_merge)
        self.assertEqual(self.ship_issue.count("`## Post-selection sync`"), 5)
        loop = normalized(self.section(self.ship_issue, "## Delivery loop", "## Remainder mode"))
        self.assert_ordered(loop, "**The pre-merge selection gate.**",
            "`## Post-selection sync`", "**Denials.**", "cannot merge into its base",
            "no authority observation", "`## Post-selection sync`",
            "A guard, host or provider denial", "the current selection, merge SHA")
        remainder = normalized(self.ship_issue.split("## Remainder mode", 1)[1])
        self.assert_ordered(remainder, "start at the merge gate", "`## Post-selection sync`",
                            "already landed", "`--kind current-selection`")
        phase_six = normalized(self.section(self.ship_issue, "## Phase 6 — Wait for CI",
                                            "## Phase 7 — Merge"))
        self.assert_ordered(phase_six, "unreviewed commits", "`## Post-selection sync`",
                            "genuinely-blocked stop")

    def test_ship_issue_probes_reviewer_dispatch_before_any_write(self):
        # The probe is Phase 0's first step, so a context that cannot launch
        # the reviewers stops before the synchronizing checkpoint, the Phase-1
        # sync and every other write (per D3, D13). It has one home (per D9).
        heading = "## Phase 0 — Pre-flight"
        phase_zero = self.section(self.ship_issue, heading, "## Phase 1")
        body = phase_zero[len(heading):].lstrip()
        self.assertTrue(body.startswith("**Reviewer-dispatch probe"), body[:80])
        self.assert_ordered(
            normalized(phase_zero),
            "Reviewer-dispatch probe",
            "synchronizing null-scope checkpoint",
            "the Phase-1 sync",
            "`ToolSearch` `select:Agent`",
            "never a host by name",
            "launches nothing, writes nothing",
            "Remainder mode skips",
            CAPABILITY_GAP_LINE,
            "Standalone",
            "git rev-parse --git-common-dir",
        )
        review = normalized(self.ship_review)
        self.assertNotIn("nested dispatch works even inside", review)
        self.assertNotIn("ToolSearch", review)
        self.assertIn("Phase-0 reviewer-dispatch probe", review)

    def test_ship_handoff_returns_the_gap_line_before_either_loop_exit(self):
        # The prompt stops promising nested dispatch, points at the probe, and
        # returns the closed gap line before the two exits that end the
        # Delivery loop (per D4, D9).
        self.assertNotIn("Nested Agent calls are supported.", self.ship_handoff)
        prompt = normalized(self.ship_handoff.split("## Inline fallback", 1)[0])
        self.assert_ordered(
            prompt,
            "reviewer subagents",
            "Phase-0 reviewer-dispatch probe confirms",
            "Return exactly canonical JSON",
            f"return only `{CAPABILITY_GAP_LINE}`",
            "Two exceptions end the loop without a summary",
        )
        remainder = self.ship_handoff.split("## Remainder owner prompt", 1)[1]
        self.assertNotIn("capability_gap", remainder)

    def test_capability_gap_line_is_spelled_identically_everywhere(self):
        # One closed line, compared byte for byte and never decoded: every
        # spelling in every carrier is exactly that line (per D4).
        for name, text in (
            ("ship-issue/SKILL.md", self.ship_issue),
            ("from-issue/ship-handoff.md", self.ship_handoff),
            ("from-issue/SKILL.md", self.from_issue),
            ("from-issue/AUTO.md", self.auto),
        ):
            with self.subTest(document=name):
                self.assertIn(CAPABILITY_GAP_LINE, text)
                self.assertEqual(
                    set(re.findall(r"capability_gap[^`\n]*", text)),
                    {CAPABILITY_GAP_LINE},
                )

    def test_from_issue_phase_seven_ships_inline_on_the_dispatch_gap(self):
        # A ship owner that cannot launch reviewers returns the closed gap line
        # from Phase 0 with nothing changed. The owner re-checks its launch,
        # ships inline through `Skill`, and only a gap from that inline run
        # suspends (per D2, D5, D6). The verb stays in the suspension
        # procedure: Phase 7 never spells it (see the launch-revalidation test).
        phase_seven = self.section(self.from_issue, "## Phase 7", "## Notes")
        self.assert_ordered(
            normalized(phase_seven),
            "receiving the ship report",
            "only the re-entry line `/from-issue <num> --auto`",
            f"only the line `{CAPABILITY_GAP_LINE}`",
            "no subagent-launch tool",
            "never decode or validate it",
            "`delivery_stalled`",
            "**Dispatch-gap fallback.**",
            "same `check-launch` fence",
            "the canonical re-entry line `/from-issue <num> --auto` on its own line",
            "through your own `Skill` tool",
            "writing only `checkpoint-delivery`",
            "never starts a second inline run",
            "suspension procedure with `<value>` = `agent_dispatch`",
            "`delivery_remainder` launch",
        )
        self.assertNotIn("workflow-state suspend", phase_seven)
        self.assertIn("After Phase 7 it is the ship report's summary",
                      normalized(self.from_issue))

    def test_suspension_procedure_admits_agent_dispatch(self):
        suspension = normalized(self.section(
            self.from_issue, "## Suspension procedure", "## Phase 0"))
        self.assertIn("a context that cannot launch the agents a phase needs",
                      suspension)
        self.assert_ordered(
            suspension, "`human_gate`", "`external`", "`agent_dispatch`",
            "(the reaper alone owns `unknown`)",
        )

    def test_auto_names_the_dispatch_gap_fallback_and_relays_closed_lines(self):
        # The rollover owner keeps its fresh Phase-7 ship owner and names the
        # one departure after it; the earlier controller relays a delegated
        # owner's re-entry or suspension line instead of mistaking it for a
        # dispatch failure (per D5, D10).
        delegated = normalized(self.section(
            self.auto, "#### Fresh delegated owner", "#### Earlier controller stop"))
        self.assert_ordered(
            delegated,
            "fresh Phase-7 ship owner",
            "must not dispatch a second issue owner",
            "Phase-7 dispatch-gap fallback",
            f"`{CAPABILITY_GAP_LINE}`",
            "After validating the ship report's `ship-summary/v2` bytes",
            "completed Phase 7",
            "with the validated ship summary inline",
        )
        self.assertNotIn("ship owner's `ship-summary/v2`", self.auto)
        self.assertNotIn("ship owner's validated summary", self.auto)
        earlier = normalized(self.section(
            self.auto, "#### Earlier controller stop", "### Other Phase 5–7 routes"))
        self.assert_ordered(
            earlier,
            "exactly validate, relay, and stop",
            "only the canonical re-entry line `/from-issue <num> --auto`",
            "only a canonical `Suspended (blocked_on=<value>). Resume: "
            "/from-issue <num> --auto` line",
            "relayed unchanged to its caller with no validation",
            "writes nothing",
            "Neither line is a dispatch failure.",
            "received bytes",
            "artifact-budget validate-report --boundary workflow-response",
            "relay the canonical bytes unchanged",
        )

    def test_orchestrate_report_names_every_cause_a_label_sweep_leaves_parked(self):
        # A label or milestone sweep never resumes these causes, so the
        # per-issue re-entry line is the instruction that works (per D10).
        final = normalized(self.section(
            self.orchestrate, "## 5. Final report", "## Notes"))
        self.assert_ordered(
            final,
            "`/from-issue <issue> --auto` for an issue suspended on a cause",
            "`--label` or `--milestone` sweep does not resume",
            "`human_gate`", "`external`", "`agent_dispatch`",
            "the orchestrate re-invocation itself",
        )
        self.assertNotIn("for an issue suspended on a human gate", final)

    def test_auto_continuation_and_bookkeeper_are_interface_two(self):
        transfer = self.section(self.auto, "#### Mandatory transfer gate",
                                "#### Fresh delegated owner")
        owner = json_block(transfer)["owner"]
        self.assertEqual((set(owner), owner["interface_version"]), (V2_OWNER_KEYS, 2))
        self.assert_ordered(normalized(self.auto), "workflow-state check-launch",
                            "workflow-state finish --summary-file -")

    def test_lifecycle_calls_are_single_stdin_commands_on_interface_two(self):
        for path in LIFECYCLE_DOCS:
            text = normalized(path.read_text(encoding="utf-8"))
            with self.subTest(path=path.name):
                for forbidden in ('"interface_version": 1', "version-1",
                                  "temporary request file", "temporary `ship-summary/v2` file"):
                    self.assertNotIn(forbidden, text)
                for flag, value in INPUT_FLAG_RE.findall(text):
                    self.assertEqual(value.strip("`.,;"), "-", flag)
                self.assertLessEqual(text.count("--result-file"), 1)
        for path in (FROM_ISSUE, ORCHESTRATE, SHIP_ISSUE):
            with self.subTest(clause=path.name):
                self.assertIn(STDIN_CLAUSE, normalized(path.read_text(encoding="utf-8")))
        expected = " ".join(case["expected_output"] for case in self.orchestrate_evals["evals"])
        for anchor in ("interface_version 2", "delivery_remainder", "contract_digest",
                       "build-delivery", "only when this invocation created the run",
                       "interface_version 3", "host-route", "launch_refused"):
            self.assertIn(anchor, expected)
        self.assertNotIn("version-1", expected)

    def test_orchestration_eval_covers_denial_partial_progress_and_remainder(self):
        text = json.dumps(self.orchestrate_evals, sort_keys=True)
        for phrase in ("partial effect", "host rejection", "same custody",
                       "delivery_remainder", "zero external effect",
                       "implementation_delivered", "pr_merged", "actual scope",
                       "fresh proposal"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_orchestrate_asks_the_host_route_first_and_never_retries_a_refusal(self):
        resolve = normalized(self.section(self.orchestrate,
            "## 1. Resolve issue set and bindings", "## 2. Bootstrap and observe"))
        self.assert_ordered(resolve, "workflow-state host-route --route claude-code",
                            "--boundary workflow-response",
                            "`unsupported` answer ends the run", "`alternative`",
                            '`host_route: "claude-code"`', "never calculates slots")
        for retired in ("Treat known host capacity as a capability boundary",
                        "This does not add reservation"):
            self.assertNotIn(retired, normalized(self.orchestrate))
        observe = normalized(self.section(self.orchestrate,
            "## 2. Bootstrap and observe", "## 3. Decide"))
        self.assertIn("`launch_refused` for an owner launch the host refused", observe)
        decide = normalized(self.section(self.orchestrate,
            "## 3. Decide", "## 4. Execute control actions"))
        self.assertIn("interface_version 3 control response", decide)
        self.assertIn("`admission`", decide)
        execute = normalized(self.section(self.orchestrate,
            "## 4. Execute control actions", "## 5. Final report"))
        self.assert_ordered(execute, "host refuses an owner launch, never retry it",
                            "exactly one control call", "`launch_refused`",
                            "the controller's `finalized` release",
                            "resumes on the next orchestrate invocation")
        report = normalized(self.orchestrate.split("## 5. Final report", 1)[1])
        self.assertIn("`admission.waiting` as queued for agent slots", report)
        self.assertIn("bounded summaries in the same interface_version 3 control response",
                      report)
        self.assertNotIn("interface_version 2 summaries", report)

    def test_codex_orchestrate_stub_relays_the_unsupported_route(self):
        raw = CODEX_ORCHESTRATE.read_text(encoding="utf-8")
        self.assertTrue(raw.startswith("---\nname: orchestrate-issues\n"))
        text = normalized(raw)
        self.assert_ordered(text, "workflow-state host-route --route codex",
                            "--boundary workflow-response", "verbatim",
                            "/from-issue <n> --auto", "one at a time")
        self.assertIn("Never spawn owners, count threads, archive sessions, start an "
                      "app-server, or retry", text)
        for forbidden in ("workflow-state control", "init-run", "run_in_background",
                          "agent-dispatch"):
            self.assertNotIn(forbidden, text)
        self.assertIn('home.file.".agents/skills/orchestrate-issues".source = '
                      './skills/orchestrate-issues;', CODEX_MODULE.read_text(encoding="utf-8"))
        self.assertFalse((REPO_ROOT / "home/common/agent-skills/skills/orchestrate-issues")
                         .exists())

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
        self.assert_ordered(decide, "--request-file -",
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
            "bindings.workflow.orchestration.attempt_budget_minutes` as\n  request `attempt_budget_minutes`",
            resolve,
        )
        self.assertIn(
            "bindings.workflow.orchestration.max_parallel` as request `max_parallel`",
            resolve,
        )
        self.assertNotIn("--budget-minutes <budget>", resolve)

    def test_dispatcher_executes_the_closed_control_action_set(self):
        action_section = self.section(
            self.orchestrate, "## 4. Execute control actions", "## 5. Final report"
        )
        for kind in ("spawn", "resume", "retry", "delivery_contract", "wait", "finalize"):
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

    def test_final_report_reads_an_expiry_as_an_interruption(self):
        # The dispatcher renders what happened to a human. An `expired` delta
        # is an interruption, not a consumed attempt (per D8, D10).
        final_section = self.section(
            self.orchestrate, "## 5. Final report", "## Notes"
        )
        collapsed = normalized(final_section)
        self.assert_ordered(
            collapsed,
            "`expired` delta",
            "consumes no attempt",
            "`resumed` on the same attempt",
            "a later eligible sweep resumes",
            "`stopped(stalled)`",
        )
        self.assertIn("never `retried` and never `retry_refused`", collapsed)

    def test_final_report_names_an_unresumable_issue(self):
        # A resume its recorded worktree ended is reported with that reason,
        # never as progressing (#194 D9, D12).
        collapsed = normalized(self.section(
            self.orchestrate, "## 5. Final report", "## Notes"))
        self.assert_ordered(
            collapsed, "`worktree_fact`", "`recorded_worktree_absent`",
            "`recorded_worktree_mismatch`", "cannot resume", "never as progressing")

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

    def test_writing_plans_resolves_its_plan_dir_through_the_resolver(self):
        text = normalized(self.writing_plans)
        self.assertIn("resolve-project resolve", text)
        self.assertIn("bindings.paths.artifacts.plans", text)
        self.assertIn(RESOLUTION_SENTENCE, text)

    def test_writing_plans_no_longer_calls_the_fail_soft_helper(self):
        self.assertNotIn("resolve-bindings", self.writing_plans)  # policy-gate-pattern
        self.assertNotIn("skills.config.json", self.writing_plans)  # policy-gate-pattern

    def test_writing_plans_treats_every_resolver_error_as_fatal(self):
        text = normalized(self.writing_plans)
        self.assertIn(RESOLUTION_SENTENCE, text)
        for forbidden in ("not_onboarded", ".claude/plans"):
            self.assertNotIn(forbidden, text)

    def test_shared_entries_use_the_project_resolver(self):
        for name in (
            "research", "doc-grounded-questions", "design", "ship-issue",
            "to-issues", "from-issue", "grill-with-docs", "ship-release",
            "wayfind", "worktrees", "writing-plans",
        ):
            path = (REPO_ROOT / "home/common/agent-skills/skills"
                    / name / "SKILL.md")
            with self.subTest(skill=name):
                self.assertIn("resolve-project resolve", path.read_text(encoding="utf-8"))

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

    def test_sdd_head_sha_is_the_final_review_first_pass_head(self):
        # The report states the range both axes reviewed whole, not the branch
        # tip, so ship can review the fix wave again as its delta (#264 D1).
        finish = normalized(self.section(self.sdd, "## Finish", "If publication fails"))
        self.assertIn(
            "`base_sha` and `head_sha` are the `DELIVERY_BASE` and `DELIVERY_HEAD`"
            " the final review's first pass covered, never the branch tip", finish)
        self.assertIn("the tip is past `head_sha`", finish)
        final_review = normalized((SDD_DIR / "final-review.md").read_text(encoding="utf-8"))
        self.assert_ordered(final_review, "review-package PLAN_FILE DELIVERY_BASE DELIVERY_HEAD",
                            "Those two pins are the report's `base_sha` and `head_sha`",
                            "the fix wave below does not move them")

    def test_handoff_head_sha_is_the_sdd_report_head_sha(self):
        handoff = normalized(self.ship_handoff)
        self.assertIn("In both handoff shapes, `head_sha` is the validated sdd report's"
                      " `head_sha`", handoff)
        self.assertIn("the *final-review head* ship-issue's Phase 5 reviews from", handoff)
        from_issue = normalized(self.from_issue)
        self.assertIn("ship-issue's Phase-5 range selection reads them, taking `head_sha` as"
                      " the final-review head only when `review_state` is `clean`", from_issue)
        self.assertNotIn("Phase-5 degradation decision reads them", from_issue)

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

    def test_standards_review_stops_a_blocked_plan_review_capability(self):
        self.assert_ordered(
            self.standards_review,
            "capabilities.review.plan", "**Blocked** stops", "reason_code",
            "repair_id", "never takes a fallback",
        )
        self.assertIn(
            "Authored unsupported, or the completed non-capacity runtime/output failure",
            self.standards_review,
        )

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
        self.assert_ordered(normalized(self.section(self.ship_issue, "## Delivery loop",
                                                    "## Remainder mode")),
                            "Only after the last cycle",
                            "validate-report --boundary ship-summary")

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

    def test_ship_expands_validated_plan_only_for_review_range_exclusion(self):
        self.assert_ordered(self.ship_issue, "artifact-budget check", "discover the plan members",
                            "review-range", "--artifact-path")
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
            "--summary-file",
            "workflow-state finish",
            "send those canonical bytes",
        )
        for field in (
            "custody",
            "contract digest",
            "historical_owner_result",
            "delivery",
            "authority",
            "reevaluation",
        ):
            self.assertIn(field, owner_return_section)
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
        self.assertEqual(set(continuation["owner"]), V2_OWNER_KEYS)
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
            "caller-passed `bindings.vcs` branch and",
            "decimal `owner.issue`",
            "`owner.contract`'s reviewed-slot `constraints.branch`",
            "binding-derived accepted branch regex",
            "`expected_branch`",
            "normalized `owner.worktree` to",
            "`remove_worktree` stage",
            "`git -C owner.worktree branch --show-current`",
            "equal `expected_branch`",
            "mismatch is a contract failure",
            "both roots are tracked",
        )
        self.assertNotIn("final path component", delegated)
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
            "artifact-budget validate-report --boundary workflow-response",
            "relay the canonical bytes unchanged",
            "stop",
        )
        self.assertNotIn("--boundary ship-summary", earlier)
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

    def test_auto_gate_enumeration_covers_an_unguarded_host(self):
        # No second pause shape is introduced: after Step 3b the file names
        # `blocked_on: human_gate` twice — the shipping-gate route here and
        # the self-answer exemption — and `human_gate` is still the only
        # `blocked_on` value in the file.
        self.assertEqual(self.auto.count("blocked_on: human_gate"), 2)
        self.assertEqual(
            sorted(set(re.findall(r"blocked_on[:=] ?(\w+)", normalized(self.auto)))),
            ["human_gate"],
        )

    def test_human_gate_carries_no_affirmative_bypass_instruction(self):
        # AC3 (per D14). The closed negative list under
        # `## Never route around a denial` is the file's ONLY home for these
        # spellings; anywhere else they would read as an instruction. A
        # line-local grep cannot see this, because the list's "must not:"
        # lead-in sits on the introduction line and each banned verb on its
        # own bullet.
        gate = self.ship_human_gate
        split = gate.index("## Never route around a denial")
        outside, ban = gate[:split], normalized(gate[split:])
        self.assertIn("On this path the session must not:", ban)
        for bypass in (
            "--admin",
            "--force",
            "--force-with-lease",
            "git merge",
            "git push origin <integration>",
            "git reset",
            "git rebase",
        ):
            with self.subTest(bypass=bypass):
                self.assertNotIn(bypass, outside)

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
        self.assertIn("execution failure", normalized(self.from_issue))
        phase_seven = self.section(self.from_issue, "## Phase 7", "## Notes")
        self.assert_ordered(
            phase_seven,
            "ledger_repo_root",
            "receiving the ship report",
            "workflow-state finish",
            "canonical JSON unchanged",
        )

    def test_from_issue_revalidates_its_launch_before_the_terminal_finish(self):
        # Without this the design refuses the forge write and then performs the
        # ledger write from the very launch it just proved stale, because the
        # ship owner and this parent share one identity (per D9).
        phase_seven = self.section(self.from_issue, "## Phase 7", "## Notes")
        self.assert_ordered(
            phase_seven,
            "receiving the ship report",
            "check-launch",
            "workflow-state finish",
        )
        collapsed = normalized(phase_seven)
        self.assertIn(
            "~/.agents/bin/workflow-state check-launch --repo-root "
            "<ledger_repo_root> --run-id <run-id> --action-id "
            "<issue:attempt:launch>",
            collapsed,
        )
        self.assertIn("this owner's own `action_id`", collapsed)
        self.assertIn("write nothing", collapsed)
        # Name the line: inside this document the bare phrase "the canonical
        # re-entry line" binds to the suspension procedure, whose banner needs
        # the very write D8 forbids. ship-issue spells it out; so does this
        # (per D24).
        self.assertIn(
            "the canonical re-entry line `/from-issue <num> --auto` on its own "
            "line",
            collapsed,
        )
        # The refusal is a stop, never a suspension: in the resume shape a
        # suspend would park the successor's live attempt (per D8).
        self.assertNotIn("workflow-state suspend", phase_seven)

    def test_expiry_prose_describes_the_wall_clock_the_reaper_actually_reads(self):
        # The only skill-prose home that explains expiry to an owner. Prose that
        # frames expiry as detecting a silent agent is wrong: the reaper compares
        # instants and never looks at progress (per D11).
        rules = self.section(
            self.from_issue,
            "## Dispatch, phase-budget and attempt-budget rules",
            "## Terminal return procedure",
        )
        collapsed = normalized(rules)
        self.assert_ordered(
            collapsed,
            "Persistence precedes notification",
            "wall-clock only",
            "never consults `last_progress_at`",
            "consumes no attempt",
            "resumes the same attempt",
            "never opens a second attempt",
        )
        self.assertIn("blocked on a CI watch", collapsed)
        self.assertIn(
            "bounds how long an owner may hold the issue", collapsed
        )
        self.assertIn(
            "the one fresh retry stays reserved for an attempt that reported "
            "a terminal",
            collapsed,
        )
        # The same rejection has a second meaning at the anti-zombie bound, and
        # this owner is the one deciding whether to stop for a pause or for
        # good, so the stalled branch has to be named here too (per D8).
        self.assertIn(
            "a `stopped(stalled)` terminal and the run is over, not paused",
            collapsed,
        )

    def test_direct_autonomous_bookkeeper_checks_before_the_terminal_finish(self):
        # The delegated ledger-only remainder is how a --auto run reaches its
        # terminal write, so the guard has to live inside the bookkeeper's own
        # command sequence, not in the parent that dispatches it (per D9).
        # Scoped to the delegated-owner section: AUTO.md names
        # `workflow-state finish` again outside it, so a whole-file ordering
        # assertion would bind that anchor and stop pinning check-before-write.
        delegated = self.section(
            self.auto,
            "#### Fresh delegated owner",
            "#### Earlier controller stop",
        )
        collapsed = normalized(delegated)
        self.assert_ordered(
            collapsed,
            "ledger-only bookkeeper route",
            "check-launch",
            "workflow-state finish",
        )
        self.assertIn("executes exactly that sequence", collapsed)
        self.assertNotIn("It executes only that command", collapsed)
        self.assertIn("only after a `current: true` answer", collapsed)
        self.assertIn("write nothing", collapsed)
        # The bookkeeper is the most exposed reader of the phrase — a cheap
        # agent told to run an exact sequence and nothing else (per D24).
        self.assertIn(
            "the canonical re-entry line `/from-issue <num> --auto` on its own "
            "line",
            collapsed,
        )
        self.assertNotIn("workflow-state suspend", delegated)

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
            self.from_issue, "### Explicit durable interactive acquisition",
            "## The flow",
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
        self.assertIn("--request-file -", direct)
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
        combined = normalized(self.from_issue + "\n" + self.auto)
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
            self.from_issue, "### Explicit durable interactive acquisition",
            "## The flow",
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

    def test_phase_gate_obeys_the_validated_phase_gate_action(self):
        """#191 D8: the obeyed action is the validated `phase_gate` reply's `action`."""
        self.assertIn(
            "Obey the returned action exactly: it is the `action` of the validated "
            "`phase_gate` reply, and the closed set is "
            "`continue | fresh_start | handoff | delegate`:",
            normalized(self.from_issue))

    def test_suspension_validates_its_reply_and_replays_a_stall_bound_terminal(self):
        """#191 D6, D8: suspend's reply is validated; a `terminal` reply is a replay."""
        suspension = self.section(
            self.from_issue, "## Suspension procedure", "## Phase 0"
        )
        self.assertIn(
            "workflow-state suspend --repo-root <ledger_repo_root> --run-id <run-id> "
            "--now <utc> --issue <n> --attempt <k> --blocked-on <value> "
            "| artifact-budget validate-report --boundary workflow-response --input -\n",
            suspension,
        )
        self.assert_ordered(
            normalized(suspension),
            "A validated `kind: terminal` reply means the anti-zombie bound ended "
            "the attempt instead: handle it as the terminal replay in the terminal "
            "return procedure — print its `reentry`, relay it, and write no "
            "`finish` — and stop.",
            "Otherwise the reply is `kind: suspended`; print the canonical line",
            "Suspended (blocked_on=<value>). Resume: <reentry from the envelope>",
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
            "and when nothing can proceed without a human, control returns finalize instead, "
            "or `delivery_contract` when a missing contract is all that stops an issue.",
            self.orchestrate,
        )
        self.assertNotIn("and optional deadline", self.orchestrate)

    def test_dispatcher_answers_a_contract_request_with_one_rule(self):
        """#221 D5: `delivery_contract` has one rule, in §4, and no override."""
        decide = normalized(self.section(self.orchestrate, "## 3. Decide",
                                         "## 4. Execute control actions"))
        execute = normalized(self.section(self.orchestrate, "## 4. Execute control actions",
                                          "## 5. Final report"))
        final = normalized(self.section(self.orchestrate, "## 5. Final report", "## Notes"))
        self.assertIn("A `delivery_contract` action asks for exactly the contracts of the "
                      "issues it lists; §4 holds its rule.", decide)
        self.assert_ordered(execute, "For `delivery_contract`",
                            "This is the one rule for such an issue.",
                            "Send each listed issue's contract as §3 describes",
                            "make the next control call at once",
                            "Never rebuild an issue whose build this invocation refused",
                            "refused every listed issue", "ends the run as `finalize` does",
                            "render §5 from this response")
        self.assertEqual(normalized(self.orchestrate).count(
            "This is the one rule for such an issue."), 1)
        self.assertIn("or a `delivery_contract` action that ends the run", final)
        # Phase-5 SF-4: the refused-launch and parked-suspension passages name the
        # new no-deadline sweep too. The parked-suspension paragraph sits in §5.
        self.assert_ordered(execute, "resumes on the next orchestrate invocation",
                            "or on the follow-up call a `delivery_contract` action asks for")
        self.assertIn("the sweep renders `finalize` (or `delivery_contract` when a missing "
                      "contract is all that stops some issue)", final)
        # Phase-5 SF-1 (D12): the durable interactive route answers the same action.
        durable = normalized(self.section(self.from_issue,
            "### Explicit durable interactive acquisition", "## The flow"))
        self.assert_ordered(durable, "A `delivery_contract` reply naming this issue",
                            "build this issue's contract", "call `workflow-state control` once more",
                            "orchestrate-issues §4")
        for text in (self.orchestrate, json.dumps(self.orchestrate_evals)):
            self.assertNotIn("override", text.lower())
        expected = " ".join(case["expected_output"] for case in self.orchestrate_evals["evals"])
        self.assertIn("spawn, resume, retry, delivery_remainder, delivery_contract, wait, finalize",
                      expected)
        self.assertIn("spawn, resume, retry, delivery_remainder, delivery_contract, wait, or "
                      "finalize", expected)

    def test_orchestrate_evals_grade_control_and_reject_retired_policy(self):
        expected = " ".join(
            case["expected_output"] for case in self.orchestrate_evals["evals"]
        )
        for anchor in (
            "ResolvedProject", "bindings.tracker", "bindings.vcs",
            "attempt_budget_minutes", "max_parallel", "workflow-state init-run",
            "workflow-state control", "current_wait_id", "finalize",
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
            "retained `ResolvedProject` and validated direct-command result",
            "the size pre-flight below",
            "`~/.agents/bin/diff-scope`",
            "--artifact-path <specification-directory> --artifact-path <plan-directory>",
            "--format json",
            "paths passed from the caller's retained snapshot, without fallback locations",
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
            "retained `capabilities.review.code` selection runs first", contract
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
        self.assertIn("retained `capabilities.review.code` selection runs first", contract)

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

        # The omission case can only be pinned here. `agent-evidence` sees a
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

    def test_sdd_review_contracts_preserve_adaptive_whole_file_coverage(self):
        for name, path in (
            ("task", SDD_DIR / "task-reviewer-prompt.md"),
            ("re-review", SDD_DIR / "re-review-prompt.md"),
            ("conformance", SDD_DIR / "conformance-reviewer-prompt.md"),
            ("correctness", SDD_DIR / "correctness-reviewer-prompt.md"),
        ):
            text = " ".join(path.read_text(encoding="utf-8").split())
            with self.subTest(document=name):
                self.assertIn("version-3", text)
                self.assertIn("stable-first-fit-whole-file", text)
                self.assertIn("changed line", text)
                self.assertIn("live file", text)
        final_review = (SDD_DIR / "final-review.md").read_text(encoding="utf-8")
        for text in (self.sdd, final_review):
            compact = " ".join(text.split()).lower()
            self.assertIn("interface version 3", compact)
            self.assertIn("stable-first-fit-whole-file", compact)
        self.assertIn("member_count", self.sdd)
        self.assertIn("aggregate_bytes", self.sdd)
        # The Placeholders paragraph tells a packet builder that the manifest
        # remains coverage evidence while selected paths are the only diff reads.
        rubric = (SDD_DIR / "correctness-reviewer-prompt.md").read_text(
            encoding="utf-8"
        )
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

    def test_codex_collaboration_dispatch_carries_operation_envelope(self):
        text = normalized(self.collaboration)
        self.assertIn("bindings.commands[review_id].argv", text)
        self.assertIn("--cwd <absolute-worktree> --json", text)
        self.assertIn("`rawOutput` is a non-empty string", text)

    def direct_review_section(self):
        return self.section(
            self.collaboration, "## Direct configured review", "## Disposition")

    def test_codex_collaboration_has_exactly_one_companion_tail(self):
        section = self.direct_review_section()
        blocks = re.findall(r"```text\n(.*?)```", section, re.S)
        self.assertEqual(blocks, [
            "bindings.commands[review_id].argv \\\n"
            "  --model gpt-6-astra --effort xhigh \\\n"
            "  --cwd <absolute-worktree> --json\n",
        ])
        for retired in RETIRED_EXEC_REVIEW_TOKENS:
            with self.subTest(retired=retired):
                self.assertNotIn(retired, self.collaboration)
        text = normalized(section)
        self.assertIn("malformed or mismatched payload", text)
        self.assertNotIn("metadata", text)

    def test_codex_collaboration_shape_error_stops_before_any_fallback(self):
        section = normalized(self.direct_review_section())
        error_at = section.index("binding shape error is a configuration error")
        fallback_at = section.index("uses exactly one native fallback")
        self.assertLess(error_at, fallback_at)
        error_paragraph = section[error_at:section.index("**Invocation.**", error_at)]
        self.assertIn("`codex-companion task [--fresh] --reviewer <op>`", error_paragraph)
        self.assertIn("(bare `codex` included)", error_paragraph)
        # The shape-error paragraph itself never offers the fallback.
        for offered in ("one native fallback", "same packet", "Claude fallback"):
            self.assertNotIn(offered, error_paragraph)
        # It is a pre-call stop, not a fourth failure class.
        self.assertNotIn("fourth failure class", section)

    def test_codex_collaboration_states_a_per_operation_wall_clock(self):
        # A deliberate second copy of the runtime's per-operation budget: callers
        # schedule around the number and prose cannot be derived from a patch, so
        # the copy is pinned here instead (D8).
        # Whitespace-normalized like the other wrapped-prose contracts in this
        # module: line breaks must not be part of what is pinned, and the
        # negative guards below only bite on normalized text — a retired figure
        # that came back across a line wrap (`~14\nmin`) would otherwise slip
        # past the very check that exists to catch it.
        self.assertIn("--model gpt-6-astra", self.collaboration)
        self.assertIn("--effort xhigh", self.collaboration)

    def test_codex_collaboration_never_reports_sandbox_limits_as_findings(self):
        # The rule lives in the packet-borne shared rules, not in the Launch
        # paragraph, because only these bullets travel to the reviewer (D14).
        # Whitespace-normalized for the same reason as above: every fragment
        # here is wrapped prose, so a reflow must not decide the verdict.
        rules = " ".join(
            self.section(
                self.collaboration,
                "## Read-only packet rules",
                "## Direct configured review",
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
        # The gate states a policy and calls the helper; the ancestry and
        # accounting live in `agent_tools.review_range` / `diff_scope` (#264 D2).
        gate = self.section(self.ship_issue, "**Pick the range first.**",
                            "**Route the review.**")
        for fragment in (
            GATE_LINE_BOUNDARY,
            GATE_FILE_BOUNDARY,
            # the whole invocation: the thresholds passed must be the ones stated (D2).
            "review-range --integration-ref origin/<integration> --head $HEAD_SHA"
            " --final-review-head <final-review head> --max-lines 1000 --max-files 20"
            " --artifact-path <spec_path> --artifact-path <plan_path>",
            "distinct from the reviewed `HEAD_SHA`",
            "No measurement",
            "is not a small diff",
            "`review-range unavailable`",
            "a historical artifact that is itself the requested product still counts",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, gate)
        for absent in ("--numstat", "400", "--root", "diff-scope $BASE_SHA"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, gate)
        self.assert_ordered(
            gate,
            "`review_state` is `clean`",
            "needed no manual conflict escalation",
            GATE_LINE_BOUNDARY,
            "does NOT carry the `risky` label",
            "`capabilities.review.code` state",
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
            f"the delta is small ({GATE_LINE_BOUNDARY} / {GATE_FILE_BOUNDARY},"
            " measured with `review-range` rather than hand-counted numstat arithmetic)",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, expected)
        self.assertNotIn("measured with `diff-scope`", expected)
        self.assertNotIn("≤400", expected)

    def test_phase_five_reviews_the_selected_range_on_two_axes(self):
        phase_five = normalized(self.section(self.ship_issue, "## Phase 5 — Review the PR",
                                             "## Phase 6 — Wait for CI"))
        route = normalized(self.section(self.ship_issue, "**Route the review.**",
                                        "**Merge-delta reviewer (post-selection sync only).**"))
        self.assert_ordered(route, "`delta`", "`<review_base>..$HEAD_SHA`",
                            "delta-route conformance brief", "`empty`", "skip to Phase 6",
                            "`full`", "`$BASE_SHA..$HEAD_SHA`", "per REVIEW.md")
        merge_delta = self.section(self.ship_issue,
                                   "**Merge-delta reviewer (post-selection sync only).**",
                                   "**Full two-axis review.**")
        self.assertIn("Phase 5 never dispatches it", normalized(merge_delta))
        self.assertIn("<!-- agent-dispatch: id=ship-issue-merge-delta-review role=reviewer"
                      " model=opus effort=high -->", merge_delta)
        full = normalized(ship_correctness_route(self.ship_issue))
        self.assertIn("Both the `delta` and `full` routes run it", full)
        self.assertIn("`<review_base>..$HEAD_SHA` on `delta`, `$BASE_SHA..$HEAD_SHA` otherwise",
                      full)
        self.assertNotIn("merge-delta empty, nothing to review", phase_five)
        self.assertIn("5. Review the PR → review-range picks delta, empty or full;"
                      " two-axis review over it", normalized(self.ship_issue))
        self.assertIn("it dispatches zero (empty review range) or two first-pass reviewer"
                      " subagents", normalized(self.ship_handoff))
        self.assertNotIn("zero (empty merge-delta), one, or two", normalized(self.ship_handoff))

    def test_review_md_owns_the_delta_brief_and_the_range_record(self):
        review = normalized(self.ship_review)
        delta = normalized(self.section(self.ship_review, "## Delta route",
                                        "## Severity mapping (full path)"))
        for fragment in (
            "`<review_base>..$HEAD_SHA`",
            "already graded delivered-vs-promised for the branch at R",
            "scope-creep categories", "review hint path",
            "stale-prose audit limited to files the delta touches",
            "never grades the whole branch's delivery again",
            "`review range: delta <review_base7>..<head7> since final-review <R7>"
            " (<L> lines, <F> files)`",
            "`review range: empty since final-review <R7>`",
            "`review range: full (<reason>)`",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, delta)
        merge_delta = normalized(self.section(self.ship_review,
                                              "## Merge-delta check (post-selection sync)",
                                              "## Full two-axis review — templates"))
        self.assertIn("Phase 5 never does", merge_delta)
        self.assertIn("`git show --cc <merge-commit>`", merge_delta)
        self.assertNotIn("after the head sdd reviewed", review)
        self.assertNotIn("merge-delta empty, nothing to review", review)

    def test_phase_six_waits_on_required_checks_and_lists_advisory_states(self):
        # #264 D6-D8: block on the forge's required set, fall back to every
        # check when none is reported, and report the rest in notes.
        phase_six = self.section(self.ship_issue, "## Phase 6 — Wait for CI",
                                 "## Phase 7 — Merge")
        self.assertIn(REQUIRED_WATCH, re.findall(r"```\n(.*?)\n```", phase_six, re.S))
        collapsed = normalized(phase_six)
        self.assert_ordered(collapsed, REQUIRED_WATCH, "Exit `124`",
                            "`no required checks reported`", ALL_CHECKS_WATCH,
                            "`CI: no required checks reported; waited on all`",
                            "a gating check failed", ADVISORY_CALL,
                            "`advisory CI: <name>=<bucket>, …`")
        self.assertNotIn("Nix Eval", phase_six)
        flow = normalized(self.section(self.ship_issue, "## The flow", "## Standing authorization"))
        self.assertIn("6. Wait for CI → gh pr checks --required --watch (one blocking call;"
                      " all checks when none is required)", flow)
        self.assertIn("block on `<tracker-cli> pr checks --required --watch`",
                      normalized(self.ship_handoff))

    def test_ci_merge_explains_the_required_watch_and_its_fallback(self):
        why = self.section(self.ship_ci_merge, "## Why the blocking watch is shaped that way",
                           "## Exit codes")
        self.assertIn(REQUIRED_WATCH, why)
        self.assertIn("branch protection's own", normalized(why))
        exits = normalized(self.section(self.ship_ci_merge, "## Exit codes", "## Advisory states"))
        self.assert_ordered(exits, "**`0`**", "**`124`**", "`no required checks reported`",
                            ALL_CHECKS_WATCH, "same exit codes and retry budget",
                            "**any other non-zero**")
        advisory = normalized(self.section(self.ship_ci_merge, "## Advisory states",
                                           "## Merge quirks (Phase 7)"))
        for fragment in (ADVISORY_CALL, "is not `pass`", "`advisory CI: <name>=<bucket>, …`",
                         "`+<n> more`", "`historical_owner_result`",
                         "does not block the merge"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, advisory)

    def test_ship_issue_eval_restates_the_required_ci_wait(self):
        expected = next(case for case in self.ship_issue_evals["evals"]
                        if case["id"] == 1)["expected_output"]
        for fragment in (f"CI is exactly foreground `{REQUIRED_WATCH}`",
                         f"falling back to `{ALL_CHECKS_WATCH}` when gh reports no required checks",
                         f"`{ADVISORY_CALL}`"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, expected)

    def test_ship_issue_merge_is_bound_to_the_resolved_repository(self):
        optional_subject = (
            'gh pr merge <pr-num> --repo <resolved-repository> --merge '
            '[--subject "<rendered subject>"] --delete-branch'
        )
        rendered_subject = (
            'gh pr merge <pr-num> --repo <resolved-repository> --merge '
            '--subject "<rendered subject>" --delete-branch'
        )
        expected_occurrences = [
            "7. Merge                   → "
            f"{optional_subject} (true merge commit)",
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
            "Use retained `bindings.tracker.repo_slug` and `bindings.vcs` values to build the subject. Emit the "
            "subject form only when the rendered result is nonempty and "
            "representable by D18's quoted-subject grammar: it contains none "
            "of double quote, dollar, backtick, backslash, NUL, LF, or CR; "
            "otherwise omit `--subject` and its value and let the forge choose its normal subject. "
            "Never pass `--no-ff` (rejected by recent `gh`; `--merge` "
            "already produces a true merge commit)."
        )
        self.assertIn(guard_and_fallback, phase_lines)

    def test_ship_issue_authorization_is_scoped_to_the_host_enforcement_model(self):
        auth = self.section(
            self.ship_issue, "## Standing authorization", "## Launch guard"
        )
        # AC1: the bare unconditional opener is gone.
        self.assertNotIn(
            "In a qualifying repository this skill IS that chain:", auth
        )
        self.assertIn("[`HUMAN-GATE.md`](./HUMAN-GATE.md)", auth)
        self.assertNotIn("CLAUDECODE", auth)
        phase4 = self.section(
            self.ship_issue, "## Phase 4 — Open PR", "## Phase 5 — Review the PR"
        )
        phase7 = self.section(
            self.ship_issue, "## Phase 7 — Merge", "## Phase 8 — Cleanup"
        )
        self.assert_ordered(
            phase7,
            "Gate 2 of [`HUMAN-GATE.md`](./HUMAN-GATE.md)",
            "Run `check-launch` (see `## Launch guard`) immediately before the merge",
            "gh pr merge <pr-num> --repo <resolved-repository> --merge",
        )
        self.assertIn("the `merge_pr` cycle of `## Delivery loop`", normalized(phase7))
        self.assertIn("current-launch", phase7)
        # D6/D10: the new Phase-4 pointer introduces no merge spelling, so
        # Phase 4 stays free of `gh pr merge` exactly as it is today.
        self.assertNotIn("gh pr merge", phase4)

    def test_ship_issue_human_gate_consolidates_and_forbids_bypass(self):
        gate = self.ship_human_gate
        # The sidecar hard-wraps like the rest of the corpus, so every prose
        # assertion runs against the normalized text and only headings and
        # section slicing use the raw file.
        flat = normalized(gate)
        # D6: Phase 7 is the single home for the merge spelling. A second home
        # would drift silently — the pinned exact-list test only scans SKILL.md.
        self.assertNotIn("gh pr merge", gate)
        # D5: the gate reuses the one suspension mechanism, defining no new one.
        self.assertIn("blocked_on: human_gate", flat)
        # D17: the `--auto` pause routes through whoever owns the ledger. A
        # fresh ship owner cannot suspend — `ship-issue/SKILL.md`'s launch
        # guard forbids it any workflow-state write, and `ship-handoff.md`
        # requires it to return a validated ship summary — so it returns a
        # truthful `stopped` row and its parent suspends. Pinned as an ordered
        # split so a future edit cannot collapse the two cases back into one
        # instruction addressed to whoever happens to be running.
        self.assert_ordered(
            flat,
            "A fresh ship owner launched per `from-issue/ship-handoff.md` "
            "writes no workflow state",
            "returns the truthful `stopped` ship summary naming the human gate",
            "`artifact-budget validate-report --boundary ship-summary`",
            "keeping the worktree and claiming no merge success",
            "its parent, the `from-issue` owner, is what suspends "
            "`blocked_on: human_gate` and prints the canonical re-entry line",
            "A `from-issue` owner running this path itself, with no fresh ship "
            "owner in between, follows `from-issue/SKILL.md`'s existing "
            "suspension procedure directly",
            "This file defines no new suspension shape and no new "
            "`blocked_on` value.",
        )
        self.assert_ordered(
            gate,
            "## Gate 1 — before the first push (Phase 4)",
            "## Gate 2 — after CI, before the merge (Phase 7)",
            "## Grant semantics",
            "## Never route around a denial",
        )
        # D7: entered instead of the attempt, never as a denial fallback.
        self.assertIn(
            "Enter the gate *instead of* attempting the verb — never attempt a "
            "shipping verb and then react to the denial.",
            flat,
        )
        # D2/#90: Gate 1 shows the whole remaining chain once.
        self.assertIn(
            "Gate 1 also names that a second and final gate follows after CI and "
            "what it will cover, so the operator sees the whole remaining chain "
            "once.",
            flat,
        )
        # D6: Gate 2 refers to the merge, never re-spells it.
        self.assertIn(
            "Present the merge command exactly as Phase 7 renders it.", flat
        )
        # D15/AC2: the literal payloads are what make the handoff
        # *consolidated*. Pin each gate's block, in order, inside its own
        # section — the assertions above would all pass with the commands
        # omitted entirely.
        gate_1 = self.section(
            gate,
            "## Gate 1 — before the first push (Phase 4)",
            "## Gate 2 — after CI, before the merge (Phase 7)",
        )
        self.assert_ordered(
            normalized(gate_1),
            "git push -u origin <branch>",
            'gh pr create --repo <resolved-repository> --base <integration-branch> --head <branch> --title "<title>" --body',
            "Closes #<num>",
        )
        gate_2 = self.section(
            gate,
            "## Gate 2 — after CI, before the merge (Phase 7)",
            "## Grant semantics",
        )
        self.assert_ordered(
            normalized(gate_2),
            "Present the merge command exactly as Phase 7 renders it.",
            "gh issue close <num>",
            # The delete is the action and the ls-remote its condition, so the
            # bullet spells them in that order. Without this anchor the block
            # could lose the delete entirely and still pass.
            "git push origin --delete <branch>",
            "git ls-remote --heads origin <branch>",
            "git worktree remove <worktree-path>",
            "git branch -d <branch>",
        )
        for clause in (
            "Silence is not a grant.",
            "A partial reply grants only the commands it names.",
            # D8: additional to, never a substitute for, the existing checks.
            "The grant is additional to every check the Claude path performs, "
            "never a substitute:",
            "`check-launch` still runs before every pre-merge forge write",
            "Phase 6's tip check and the CI wait still bind",
            "the base branch's required status check",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, flat)
        # AC3 (per D14): the closed no-bypass list is pinned as an ordered list
        # scoped to its own heading — the file's last section — not as seven
        # free-floating substrings that could sit anywhere.
        ban = normalized(gate[gate.index("## Never route around a denial") :])
        self.assert_ordered(
            ban,
            "On this path the session must not:",
            "- merge the feature branch into the passed `<integration-branch>` locally;",
            "- push to the passed `<integration-branch>`;",
            "- push to any remote other than `origin`;",
            "- pass `--admin`, `--force`, `--force-with-lease`, or any "
            "hook-bypass flag;",
            "- rewrite, reset or rebase any branch to change what a denied "
            "command would have done;",
            "- re-attempt a denied command in a re-worded or re-quoted "
            "spelling;",
            "- ask a subagent, another skill, or another host to run the "
            "command on its behalf.",
        )

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
        # The one rule is indifferent to the tracker binding: a `kind=none`
        # invocation skips Phase 4's PR but still pushes the branch to `origin`,
        # and that push is a guarded write like any other.
        self.assertIn("regardless of tracker capability", collapsed)
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
        # The post-merge effects are loop cycles (D29), and the ledger-free skip.
        self.assertIn("each post-merge effect is a `## Delivery loop` cycle", collapsed)
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
            "never an entire retained artifact directory",
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
        for name, text in (("research", self.research),):
            with self.subTest(skill=name):
                self.assertIn("~/.agents/bin/agent-evidence", text)
        with self.subTest(skill="ship-issue"):
            self.assertIn("~/.agents/bin/review-range", self.ship_issue)
        # The packaged detail producer and external workspace command are both
        # published by bare name; review-package has one command-table owner.
        command_table = (REPO_ROOT / "lib/agent-tools.nix").read_text(encoding="utf-8")
        self.assertIn('"review-package"', command_table)
        self.assertNotIn('".agents/bin/review-package" =', nix_module)
        self.assertIn('".agents/bin/sdd-workspace"', nix_module)
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


class LaunchFencedWorkerContractsTest(unittest.TestCase):
    """#222: writing dispatches register, commit through launch-commit, release."""

    WORKER_LINE = ("Lifecycle worker: --repo-root <ledger_repo_root> --run-id <run-id> "
                   "--worker-id <worker_id>")
    REGISTER = ("workflow-state register-worker --repo-root <ledger_repo_root> "
                "--run-id <run-id> --now <utc> --action-id <action_id>")
    RELEASE = ("workflow-state release-worker --repo-root <ledger_repo_root> "
               "--run-id <run-id> --now <utc> --worker-id <worker_id> --event returned")
    COMMIT = ("launch-commit --repo-root <ledger_repo_root> --run-id <run-id> "
              "--worker-id <worker_id> -- ")

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def read(path):
        return normalized(path.read_text(encoding="utf-8"))

    def test_sdd_registers_writing_workers_and_stops_on_a_fence_refusal(self):
        self.assert_ordered(
            self.read(SDD), "### Lifecycle workers", self.REGISTER, self.WORKER_LINE,
            self.RELEASE, "Read-only reviewers are not registered.",
            "launch fence refused: <reason>", "no retry and no re-dispatch",
            "workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> "
            "--action-id <action_id>",
            "On `current: false`", "`/from-issue <num> --auto`",
            "On `current: true`", "`blocked_on=transport`",
            "### 1. Dispatch the implementer")
        self.assertNotIn("write nothing more", self.read(SDD))

    def test_the_implementer_commits_only_through_launch_commit(self):
        self.assert_ordered(
            self.read(SDD_DIR / "implementer-prompt.md"), "## Lifecycle Worker",
            "Lifecycle worker:", self.COMMIT, "never run `git commit` directly",
            "only the most recent one governs", "launch fence refused: <reason>",
            "## Report Format")

    def test_each_fix_round_registers_afresh(self):
        self.assert_ordered(
            self.read(SDD_DIR / "fix-loop.md"), "Lifecycle workers",
            "fresh `worker_id`", "resume message", "Run the release when it returns")

    def test_from_issue_phase_6_hands_sdd_its_lifecycle_identity(self):
        self.assert_ordered(
            self.read(FROM_ISSUE), "## Phase 6 — Execute",
            "`ledger_repo_root`, `run_id` and `action_id`", "### Lifecycle workers",
            "register-worker", "## Phase 7 — Ship")

    def test_from_issue_registers_writers_and_releases_before_every_exit(self):
        text = self.read(FROM_ISSUE)
        self.assert_ordered(
            text, "## Dispatch, phase-budget and attempt-budget rules",
            "**Writing workers.**", self.REGISTER, self.WORKER_LINE,
            "the fresh delegated owner", "the ledger-only bookkeeper",
            "--event stopped", "return without a terminal write",
            "**`handoff`** — first release every worker",
            "## Terminal return procedure", "release every worker",
            "## Suspension procedure", "release every worker", "live workers:")

    def test_auto_subagents_commit_through_launch_commit_and_the_bookkeeper_is_unregistered(self):
        text = self.read(FROM_ISSUE_DIR / "AUTO.md")
        self.assert_ordered(text, "Both prompts must carry", "`Lifecycle worker:` line",
                            "launch-commit")
        self.assert_ordered(text, "ledger-only bookkeeper route",
                            "releases every worker it registered",
                            "The bookkeeper is never registered")

    def test_the_ship_prompt_carries_the_worker_line_outside_the_handoff(self):
        self.assert_ordered(
            self.read(FROM_ISSUE_DIR / "ship-handoff.md"), "## Ship-owner subagent prompt",
            self.WORKER_LINE, "never inside the handoff")

    def test_ship_issue_fences_local_commits_and_registers_its_children(self):
        text = self.read(SHIP_ISSUE)
        self.assert_ordered(
            text, "## Launch guard", "### Local commits", self.COMMIT,
            "git merge --no-commit --no-ff origin/<integration>", "--parent <worker_id>",
            "## Phase 1 — Sync from the integration branch")
        self.assertNotIn("Phase 3's local commits are not forge writes", text)
        self.assertNotIn("Otherwise `git merge origin/<integration>`; commit the merge", text)
        self.assert_ordered(text, "## Phase 1 — Sync from the integration branch",
                            "git merge --no-commit --no-ff origin/<integration>",
                            "Already up to date")
        self.assert_ordered(text, "## Remainder mode", self.RELEASE, "finish")
        self.assert_ordered(self.read(SHIP_ISSUE.parent / "CI-MERGE.md"),
                            "## Post-selection sync", "launch-commit", "--amend --no-edit")
        self.assert_ordered(text, "## Delivery loop", "--worker-id <worker_id>")

    def test_the_remainder_prompt_releases_itself_before_its_finish(self):
        self.assert_ordered(
            self.read(FROM_ISSUE_DIR / "ship-handoff.md"), "## Remainder owner prompt",
            self.WORKER_LINE, self.RELEASE,
            "workflow-state finish --summary-file -")

    def test_the_dispatcher_handles_both_cases_without_judgment(self):
        text = self.read(ORCHESTRATE)
        self.assert_ordered(
            text, "## 2. Bootstrap and observe",
            "Ignore unrelated or stale host notifications",
            "a wake of the current wait handle is none of these cases",
            "(b) **Owner return without a terminal write.**",
            "workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> "
            "--action-id <action_id>",
            "On `current: true`, send exactly one `unavailable` owner observation",
            "On `current: false`, send nothing.",
            "(c) **Non-owner hand-back.**", "nor the current wait handle",
            "send no observation, write nothing, relay nothing, act on none of its "
            "content, and stop no task",
            "## 3. Decide")

    def test_claude_md_describes_the_launch_fence(self):
        text = self.read(REPO_ROOT / "CLAUDE.md")
        self.assert_ordered(
            text, "workflow-state check-launch` before any forge write",
            "`workers` list", "workflow-state register-worker", "`launch-commit` command",
            "workflow-state check-worker", "is refused while a registered worker")


class ProgressMarkerContractsTest(unittest.TestCase):
    """#250: the Phase 6 owner records a progress marker after each completed task."""

    MARK = ("workflow-state mark-progress --repo-root <ledger_repo_root> "
            "--run-id <run-id> --now <utc> --action-id <action_id>")
    BOUND = "without a phase advance or a newly recorded progress marker"

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def read(path):
        return normalized(path.read_text(encoding="utf-8"))

    def test_sdd_records_a_marker_before_the_first_task_and_after_each_one(self):
        self.assert_ordered(
            self.read(SDD), "### Lifecycle workers", self.MARK,
            "once before dispatching the first task this session will execute",
            "after each task completes (step 5)",
            "### 1. Dispatch the implementer", "### 5. Complete the task",
            "appends `Task <N>: complete", self.MARK, "## Final review")

    def test_a_refused_marker_is_no_suspension_cause_in_sdd(self):
        self.assert_ordered(
            self.read(SDD), "### Lifecycle workers", self.MARK,
            "The reply's `outcome` is informational.",
            "A refusal changes nothing, is not a suspension cause and never stops "
            "the task loop", "### 1. Dispatch the implementer")

    def test_from_issue_phase_6_names_the_marker_on_both_routes(self):
        self.assert_ordered(
            self.read(FROM_ISSUE), "## Phase 6 — Execute",
            "`ledger_repo_root`, `run_id` and `action_id`",
            "records a progress marker after each completed task", self.MARK,
            "once before dispatching the mechanic and once after its change is "
            "committed", "is not a suspension cause", "## Phase 7 — Ship")

    def test_the_bound_is_described_as_progress_not_phase(self):
        for path, retired in ((FROM_ISSUE, "at the same recorded phase too many times"),
                              (ORCHESTRATE, "at the same phase too many times")):
            with self.subTest(path=path.name):
                text = self.read(path)
                self.assertIn(self.BOUND, text)
                self.assertNotIn(retired, text)

    def test_claude_md_describes_the_marker(self):
        self.assert_ordered(
            self.read(REPO_ROOT / "CLAUDE.md"),
            "The anti-zombie bound counts progress, not phase changes", self.MARK,
            "`progress_marker`", "`baseline`", "`advanced`", "`unchanged`",
            "`diverged`")


class ResumePackContractsTest(unittest.TestCase):
    """#265: relaunchers carry a resume pack and owners verify it before use."""

    PACK = ("workflow-state resume-pack --repo-root <ledger_repo_root> "
            "--run-id <run-id> --action-id <action_id>")
    DISPATCHER_PACK = ("workflow-state resume-pack --repo-root <ledger_repo_root> "
                       "--run-id <run-id> --action-id <action-id>")

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def read(path):
        return normalized(path.read_text(encoding="utf-8"))

    def test_both_skills_exempt_the_pack_from_workflow_response_validation(self):
        self.assert_ordered(
            self.read(ORCHESTRATE), "untrusted transport",
            "and validate before decoding any field.",
            "The one exception is `resume-pack`", "is not a workflow response",
            "never pipes or decodes it", "## 1. Resolve issue set and bindings")
        self.assert_ordered(
            self.read(FROM_ISSUE), "## Lifecycle identity", "untrusted transport",
            "and validate before decoding.", "The one exception is `resume-pack`",
            "is not a workflow response", "the checks in `### Resume pack`",
            "### Dispatcher-owned acquisition")

    def test_from_issue_defers_the_auto_read_on_a_pack_carrying_relaunch(self):
        self.assert_ordered(
            self.read(FROM_ISSUE), "## Files beside this one",
            "Read it *once*, now, only if the invocation contains the literal token `--auto`.",
            "When the prompt carries a resume pack, defer that read",
            "limits it to the sections that subsection names",
            "restores the whole read",
            "An owner delegated at `AUTO.md`'s Phase-5 rollover still reads its "
            "`#### Fresh delegated owner` section now",
            "## Lifecycle identity")

    def test_orchestrate_adds_the_pack_to_resume_prompts_only(self):
        self.assert_ordered(
            self.read(ORCHESTRATE), "## 4. Execute control actions",
            "For a `resume` action", self.DISPATCHER_PACK,
            "add its stdout verbatim to the owner prompt's `Resume pack` paragraph",
            "never stops the dispatch", "`spawn` and `retry` carry no pack",
            "> `<canonical-json>`", "> Resume pack", "> `<resume-pack-json>`",
            "## 5. Final report")

    def test_from_issue_owner_verifies_the_pack_and_reads_only_the_phase(self):
        self.assert_ordered(
            self.read(FROM_ISSUE), "## Lifecycle identity",
            "### Resume pack A relaunched owner's prompt may carry a resume pack",
            self.PACK, "an accelerator, never a gate", "not a workflow response",
            "still resolves the project once", "runs `check-launch`",
            "An owner delegated at `AUTO.md`'s Phase-5 rollover",
            "carries that rollover's continuation",
            "`#### Fresh delegated owner` check first",
            "a generic `delegate` owner carries no continuation and runs none of them",
            "`git -C <worktree> rev-parse HEAD` must equal `worktree.head`",
            "re-orient in full",
            "A verified pack replaces only your own ad-hoc re-orientation",
            "do not dump the ledger", "re-validate the plan",
            "read only the skill sections its phase needs",
            "always read the sections every owner obeys", "`Lifecycle identity`",
            "`Dispatch, phase-budget and attempt-budget rules`",
            "`Terminal return procedure`", "`Suspension procedure`",
            "this file's `## Phase <n>` section",
            "`sdd` for Phase 6", "`ship-issue` for Phase 7",
            "(not the whole file)", "`The self-answer pattern`",
            "`When *not* to auto-resolve`",
            "`Mandatory direct implementation-owner rollover`",
            "`Other Phase 5–7 routes`",
            "Everything the pack does not replace still runs unchanged",
            "sdd's own `progress.md` check", "sdd's ledger wins",
            "never stops a relaunch", "## The flow")

    def test_from_issue_direct_reentry_and_delegate_carry_the_pack(self):
        text = self.read(FROM_ISSUE)
        self.assert_ordered(
            text, "### Direct autonomous acquisition", "**`kind: owner`**",
            "When its `launch_kind` is `resume`", self.PACK,
            "### Interactive direct acquisition")
        self.assert_ordered(
            text, "4. **`delegate`** —", "the fresh owner adopts this launch",
            self.PACK, "as a `Resume pack` paragraph",
            "Exception — **ledger-only remainder**")

    def test_auto_rollover_passes_the_pack_beside_the_continuation(self):
        self.assert_ordered(
            self.read(AUTO), "#### Mandatory transfer gate",
            "Beside the continuation, never inside it", self.PACK,
            "does not stop the transfer", "#### Fresh delegated owner",
            "Any mismatch stops the attempt as a contract failure.",
            "only after every check above has passed", "replaces none of them",
            "#### Earlier controller stop")

    def test_claude_md_describes_the_resume_pack(self):
        self.assert_ordered(
            self.read(REPO_ROOT / "CLAUDE.md"),
            "A relaunched owner's prompt carries a resume pack", self.PACK,
            "`read_handoff`", "`start_phase`", "`current: false` preview",
            "still runs `check-launch`")


class InterimChildResultContractsTest(unittest.TestCase):
    """#261: an owner treats a child's interim return as still running."""

    HEAD = "**Interim child results.**"
    OWNERS = (FROM_ISSUE, SDD, SHIP_ISSUE)

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def read(path):
        return normalized(path.read_text(encoding="utf-8"))

    @classmethod
    def paragraph(cls, path):
        text = path.read_text(encoding="utf-8")
        start = text.index(cls.HEAD)
        end = text.find("\n\n", start)
        return normalized(text[start:] if end < 0 else text[start:end]).strip()

    def test_each_owner_skill_carries_the_paragraph_once(self):
        for path in self.OWNERS:
            with self.subTest(path=path.parent.name):
                self.assertEqual(path.read_text(encoding="utf-8").count(self.HEAD), 1)

    def test_the_paragraph_copies_stay_identical(self):
        canonical = self.paragraph(FROM_ISSUE)
        for path in (SDD, SHIP_ISSUE):
            with self.subTest(path=path.parent.name):
                self.assertEqual(self.paragraph(path), canonical)

    def test_the_paragraph_states_the_rule_in_order(self):
        self.assert_ordered(
            self.paragraph(FROM_ISSUE), self.HEAD,
            "is not a completion: the child is still running.",
            "Re-engage that same child by its recorded agent identity",
            "and wait for that report.",
            "You may end your own turn while the re-engaged child is live",
            "Never answer an interim result with a text-only reply",
            "never suspend for it (it is not an `external` wait)",
            "never dispatch a replacement or stop the child.",
            "stays registered under its existing worker id",
            "so it registers nothing new.",
            "If the message cannot be delivered",
            "release `--event stopped`",
            "the one case that may lead to a fresh dispatch.",
            "Only the child's final hand-back counts as its result.")

    def test_each_copy_sits_in_its_owner_section(self):
        for path, start, end in (
            (FROM_ISSUE, "**Writing workers.**", "## Terminal return procedure"),
            (SDD, "### 2. Handle the report", "### 3. Review the task"),
            (SHIP_ISSUE, "## Phase 5 — Review the PR", "## Phase 6 — Wait for CI"),
        ):
            with self.subTest(path=path.parent.name):
                self.assert_ordered(self.read(path), start, self.HEAD, end)

    def test_the_suspension_and_auto_pointers_route_to_the_paragraph(self):
        self.assert_ordered(
            self.read(FROM_ISSUE), "## Suspension procedure",
            "an external wait (never a child's interim result; see "
            "**Interim child results**)",
            "A suspension parks the attempt")
        self.assert_ordered(
            self.read(AUTO), "## Phases 2–4 run as subagents", "**Skill exception.**",
            "A Phase 2–4 subagent's interim result follows `SKILL.md`'s "
            "**Interim child results** rule.",
            "### Design subagent — Phases 2 + 3")


class InterimOwnerNotificationContractsTest(unittest.TestCase):
    """#261: the dispatcher does not observe an interim owner notification."""

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    def test_an_interim_owner_notification_is_the_first_case(self):
        self.assert_ordered(
            normalized(ORCHESTRATE.read_text(encoding="utf-8")),
            "## 2. Bootstrap and observe",
            "a wake of the current wait handle is none of these cases",
            "(a) **Interim owner notification.**",
            "The handle is an owner launch's, and the host marks the notification interim",
            "The owner is still running, so send no observation, run no "
            "`check-launch`, write nothing, stop no task and relaunch nothing",
            "the same handle notifies again with the owner's real return.",
            "(b) **Owner return without a terminal write.**",
            "(c) **Non-owner hand-back.**",
            "## 3. Decide")

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


class InstalledOrchestrateRoutesTest(unittest.TestCase):
    """D25: each agent's installed tree holds its own orchestrate-issues."""

    @classmethod
    def setUpClass(cls):
        root = os.environ.get("AGENT_SKILLS_INSTALLED_HOME")
        if root is None:
            raise unittest.SkipTest("AGENT_SKILLS_INSTALLED_HOME is unset; run "
                                    "`just agent-installed-skill-tests`")
        cls.root = Path(root)

    def test_codex_tree_holds_the_stub_and_claude_tree_the_adapter(self):
        installed = lambda tree: (self.root / tree / "orchestrate-issues/SKILL.md"
                                  ).read_text(encoding="utf-8")
        self.assertEqual(installed(".agents/skills"),
                         CODEX_ORCHESTRATE.read_text(encoding="utf-8"))
        self.assertEqual(installed(".claude/skills"), ORCHESTRATE.read_text(encoding="utf-8"))


class CheckpointVerificationContractsTest(unittest.TestCase):
    """#263: the full declared verification runs at checkpoints, recorded by tree."""

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def read(path):
        return normalized(path.read_text(encoding="utf-8"))

    def test_final_verification_follows_the_fix_wave_in_order(self):
        self.assert_ordered(
            self.read(SDD_DIR / "final-review.md"),
            "There is no second fix wave",
            "## Final verification",
            "after the fix wave and its scoped re-reviews",
            "before you choose the terminal state",
            "`bindings.workflow.verification`",
            "A blocked verification capability stops",
            "`reason_code` and `repair_id`",
            "authored unsupported, skip this step",
            "`Final verification: none declared`",
            "1. **Check.**", "`verified-tree check --verification <id>`",
            "keep the `tree` it prints", "Exit 0 with `verified`", "skip step 2.",
            "2. **Run and record.**",
            "in the foreground with an explicit timeout above its duration",
            "only the tail read back",
            "When every command passes, run `verified-tree record --tree <the checked tree>`",
            "3. **Ledger.**",
            "`Final verification: passed (head <full sha>, tree <tree id>)`",
            "4. **Repair once.**", "`tree_changed`", "exits 2 is not a pass",
            "Dispatch the final-review fixer above once",
            "`git status --porcelain`",
            "one scoped correctness re-review",
            "then run steps 1–3 once more",
            "load-bearing correctness finding",
            "the terminal state is Residuals",
            "`verification_state: failed`",
            "`correctness_verdict: findings`")

    def test_sdd_finish_ties_passed_to_the_recorded_final_verification(self):
        sdd = self.read(SDD)
        self.assert_ordered(
            sdd, "## Final review — two axes", "the **Final verification** step",
            "## Finish",
            "`verification_state` is `passed` only when final-review.md's "
            "**Final verification** step recorded a pass on the branch tip it ran on",
            "or took its none-declared route with the per-task focused tests passing",
            "- **Clean** —",
            "and the **Final verification** step recorded a pass on the branch tip",
            "or took its none-declared route",
            "- **Residuals** —")
        finish = sdd.split("## Finish", 1)[1]
        for restated in ("verified-tree", "Final verification: passed"):
            with self.subTest(restated=restated):
                self.assertNotIn(restated, finish)

    def test_the_implementer_runs_focused_tests_and_the_build_check_only(self):
        prompt = self.read(SDD_DIR / "implementer-prompt.md")
        self.assertNotIn("run the full suite once before committing", prompt)
        self.assert_ordered(
            prompt, "## Test Discipline",
            "run the focused test commands your brief names, red before green",
            "and the brief's build check when your task changes files the build evaluates",
            "Do not run the full declared verification: the final gate runs it once, "
            "on the final head.",
            "## After Review Findings",
            "re-run the focused tests covering the amended code",
            "the brief's build check when the fix changes files the build evaluates")

    def test_fix_rounds_and_the_final_fixer_name_the_same_ladder(self):
        self.assert_ordered(
            self.read(SDD_DIR / "fix-loop.md"),
            "Every round: the implementer fixes, re-runs the covering focused tests",
            "when the fix changes files the build evaluates, the brief's build check",
            "(never the full declared verification)",
            "appends a fix report")
        self.assert_ordered(
            self.read(SDD_DIR / "final-review.md"),
            "id=sdd-final-review-fixer",
            "The fixer runs the focused tests covering each fix",
            "the build check when a fix changes files the build evaluates",
            "never the full declared verification",
            "the **Final verification** step below runs it after the fix wave",
            "Where both axes flag the same lines",
            "## Final verification")

    def test_writing_plans_names_focused_commands_per_task(self):
        self.assert_ordered(
            self.read(WRITING_PLANS),
            "**Every task carries at least one verification line that could fail.**",
            "**Each task names its focused test commands.**",
            "adds the project's build check only when the task changes files that "
            "check evaluates",
            "a planner unsure whether a task's files reach the build adds it",
            "No task names the full declared verification as a per-task gate",
            "sdd's final gate runs it once on the final head",
            "## Package construction and budget boundary")

    def test_ship_phase_two_skips_only_on_a_verified_tree(self):
        phase = self.read(SHIP_ISSUE).split("## Phase 2 — Verify locally", 1)[1]
        phase = phase.split("## Phase 3", 1)[0]
        self.assert_ordered(
            phase, "This is the one verification step.",
            "Phase 3 after a promotion commit, REVIEW.md's apply/push step 2 and CI-MERGE.md's post-selection sync run it too.",
            "A blocked verification capability stops",
            "1. **Check.** Run `verified-tree check --verification <id>`",
            "in order, and keep the `tree` it prints.",
            "2. **Skip only on `verified`.**", "Exit 0 with `verified`", "skip the run",
            "`verification reused: tree <id>`",
            "3. **Otherwise run and record.**", "On any other answer, run every command id",
            "When every command passes, run `verified-tree record --tree <the checked tree>`",
            "`tree_changed` is a failing verification",
            "A `check` that exits 2 leaves no tree to record",
            "A `record` that exits 2 leaves the pass unrecorded",
            "the run itself still counts by its commands' results",
            "These failure rules apply only to an actual run.",
            "On a failing verification command, pause, ground, and surface",
            "baselining the same project in a scratch worktree")
        self.assertEqual(phase.count("verified-tree record"), 1)

    def test_review_and_ci_merge_reruns_use_phase_two(self):
        review = self.read(SHIP_ISSUE_REVIEW)
        self.assert_ordered(
            review, "## The five-step apply/push flow", "1. Edit the file(s).",
            "2. Run Phase 2's verification step (SKILL.md's `## Phase 2 — Verify locally`)",
            "3. `git add`")
        consolidate = self.read(SHIP_ISSUE).split("## Phase 3 — Consolidate learnings", 1)[1]
        consolidate = consolidate.split("## Phase 4", 1)[0]
        self.assert_ordered(
            consolidate, "Promoted candidates commit as",
            "When Phase 3 commits anything, run Phase 2's verification step again before Phase 4.")
        self.assertNotIn("Re-run every retained `bindings.workflow.verification` command",
                         review)
        ci_merge = self.read(SHIP_ISSUE_CI_MERGE)
        self.assert_ordered(
            ci_merge, "## Post-selection sync",
            "2. **Verify.** Run Phase 2's verification step.",
            "after every amend re-run Phase 2's verification step before the push.")
        self.assertNotIn("Phase 2 verification commands", ci_merge)


class AcceptanceGradingContractsTest(unittest.TestCase):
    """#272: the conformance axis grades every acceptance criterion on Opus/high."""

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def read(path):
        return normalized(path.read_text(encoding="utf-8"))

    def test_the_conformance_axis_runs_on_opus_high(self):
        final_review = self.read(SDD_DIR / "final-review.md")
        sdd = self.read(SDD)
        prompt = self.read(SDD_DIR / "conformance-reviewer-prompt.md")
        self.assertIn("Native `reviewer` on the Opus/high tier selected in "
                      "[conformance-reviewer-prompt.md](conformance-reviewer-prompt.md)",
                      final_review)
        self.assertIn("(parent D3)", final_review)
        self.assertNotIn("checklist-shaped work", final_review)
        self.assertIn("the conformance axis as `reviewer` on Opus/high;", sdd)
        self.assertIn("Subagent (reviewer, Opus/high as selected above):", prompt)
        for name, text in (("final review", final_review), ("sdd", sdd),
                           ("prompt", prompt)):
            with self.subTest(document=name):
                self.assertNotIn("Sonnet", text)

    def test_the_conformance_prompt_grades_every_criterion(self):
        prompt = self.read(SDD_DIR / "conformance-reviewer-prompt.md")
        fence = prompt[prompt.index("```"):prompt.rindex("```")]
        for fragment in (
            "## Acceptance criteria [ACCEPTANCE_CRITERIA]",
            "`AC1`…`ACn` in order, as exactly one of `met`, `unmet`, `unverified` or `human_pending`",
            "part of the Declared verification line",
            "`<plan stem>.acceptance.md`",
            "An evidence `met` must cite the observed value and the threshold;",
            'rounding or "close enough" never counts',
            "A missing row is `unverified`, a stale row is `unverified`",
            "`human`: always `human_pending`",
            "An acceptance finding is never parked with a ruling.",
            "≤400 words total, not counting the `### Acceptance` table.",
            "It is `Findings` whenever any Acceptance row is `unmet` or `unverified`.",
            "| AC | Kind | Verdict | Citation |",
            "`observed <value> at <sha7> vs threshold <literal>`",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, fence)
        self.assert_ordered(fence, "### Coverage", "### Acceptance (omit this section",
                            "### Issues", "### Ledger Triage")
        placeholders = prompt[prompt.index("**Placeholders:**"):]
        self.assert_ordered(placeholders, "`[ACCEPTANCE_CRITERIA]`",
                            "`AC<n>: <the issue's criterion line verbatim, without its checkbox>`",
                            "`Declared verification: <each declared verification command, in order>`",
                            "ship-issue's full review",
                            "`### Acceptance` output section")
        self.assertIn("omit the ledger-triage placeholder and `[ACCEPTANCE_CRITERIA]`",
                      self.read(SHIP_ISSUE_REVIEW))


if __name__ == "__main__":
    unittest.main()
