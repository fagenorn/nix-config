import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from agent_tools import agnostic_lint
from agent_tools.skill_lint import working_tree


REPO_ROOT = Path(__file__).parents[4]
HANDOFF = REPO_ROOT / "home/common/agent-skills/skills/handoff/SKILL.md"
DESIGN = REPO_ROOT / "home/common/agent-skills/skills/design/SKILL.md"
GRILL = REPO_ROOT / "home/common/agent-skills/skills/grill-with-docs/SKILL.md"
COLLABORATION = (
    REPO_ROOT / "home/common/claude-code/skills/codex-collaboration/SKILL.md"
)
DIFF_REVIEW = (
    REPO_ROOT / "home/common/claude-code/skills/codex-collaboration/DIFF-REVIEW.md"
)
PLAN_REVIEW = (
    REPO_ROOT / "home/common/claude-code/skills/codex-collaboration/PLAN-REVIEW.md"
)
RESEARCH = REPO_ROOT / "home/common/agent-skills/skills/research/SKILL.md"
WORKTREES = REPO_ROOT / "home/common/agent-skills/skills/worktrees/SKILL.md"
SMALL_BUDGET_FIXTURE = (
    REPO_ROOT / "home/common/agent-skills/tests/fixtures/artifact-budgets/small-issue.json"
)
OVERSIZED_BUDGET_FIXTURE = (
    REPO_ROOT / "home/common/agent-skills/tests/fixtures/artifact-budgets/oversized-issue.json"
)
WRITING_PLANS = REPO_ROOT / "home/common/agent-skills/skills/writing-plans/SKILL.md"
ACCEPTANCE_RULES = REPO_ROOT / "home/common/agent-skills/standards/acceptance-planning.md"
ACCEPTANCE_RULES_POINTER = "`~/.agents/standards/acceptance-planning.md`"


SKILL_ROOTS = (
    REPO_ROOT / "home/common/agent-skills/skills",
    REPO_ROOT / "home/common/claude-code/skills",
)

CODEX_MODULE = REPO_ROOT / "home/common/codex/default.nix"
SKILL_TREES = (REPO_ROOT / "home/common/agent-skills/skills",
               REPO_ROOT / "home/common/claude-code/skills")
NOW_FLAG = re.compile(r"(?<![\w-])--now(?![\w-])")
NOW_KEY = re.compile(r'"now"\s*:')


REPORT_CANDIDATE_MKTEMP = 'mktemp "${TMPDIR:-/tmp}/producer-report-XXXXXX.json"'
REPORT_CANDIDATE_VALIDATION = (
    "artifact-budget validate-report --boundary producer --input <report-candidate>")

# Machine-consumed text the remaining in-scope shared skills must carry
# (#291 D6): helper argv, durable paths and the artifact fields a helper reads.
SHARED_SKILL_MACHINE_TEXT = {
    DESIGN: (REPORT_CANDIDATE_MKTEMP, REPORT_CANDIDATE_VALIDATION),
    GRILL: (REPORT_CANDIDATE_MKTEMP, REPORT_CANDIDATE_VALIDATION),
    WRITING_PLANS: (REPORT_CANDIDATE_MKTEMP, REPORT_CANDIDATE_VALIDATION),
    HANDOFF: (REPORT_CANDIDATE_MKTEMP, REPORT_CANDIDATE_VALIDATION,
              ".superpowers/workflows/<run-id>/handoffs/"),
    RESEARCH: (
        "`research-observations`", "agent-evidence research <artifact.json>",
        "`observed_at`", "`outcome`", "`follow_up`", "`execution_id`", "`transient`",
        "`{file_path, key_facts[]}`",
    ),
}

# Machine-consumed text the codex-collaboration documents must carry (#291 D6):
# the companion argv, the review binding field and the diff-scope invocation and
# JSON fields DIFF-REVIEW.md reads. No guidance sentence is pinned.
CODEX_COLLABORATION_MACHINE_TEXT = {
    COLLABORATION: (
        "bindings.commands[review_id].argv", "--model gpt-6-astra", "--effort xhigh",
        "--cwd <absolute-worktree> --json",
    ),
    DIFF_REVIEW: (
        "`~/.agents/bin/diff-scope`",
        "--artifact-path <specification-directory> --artifact-path <plan-directory>",
        "--format json", "`product.changed_files`", "`files[].path`",
        "`files[].changed_lines`", "`git diff <base>..<head> -- ':(literal)<path>'`",
        "`git merge-base <left> <right>`", "`scope: <K> slices over <M> product files`",
    ),
    PLAN_REVIEW: ("`Blocking`", "`Should fix`", "`Discussion`"),
}


# "sibling <=2 words> candidate" — the in-working-tree prescription being
# removed. The bounded gap keeps it off handoff's legitimate
# "candidate ... sibling temporary" sentences, where the words appear in the
# other order (D2).
SIBLING_CANDIDATE_RE = re.compile(r"sibling(?:\s+\S+){0,2}\s+candidate")

SDD_SCRIPTS = REPO_ROOT / "home/common/agent-skills/scripts"

# The superseded claim: the workspace has not been repo-root-relative since the
# primary-checkout move (D3).
REPO_ROOT_WORKSPACE_LITERAL = "<repo-root>/.superpowers/sdd"


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
    "home/common/agent-skills/scripts/sdd-workspace",
    "home/common/agent-skills/tests/test_sdd_workspace.py",
    "handoff-notes.md",
)


def normalized(text):
    """Collapse every whitespace run to one space (the corpus hard-wraps ~80c)."""
    return re.sub(r"\s+", " ", text)


SHARED_POLICY_ENTRIES = {
    "deliver-direct/SKILL.md": ("bindings.tracker", "bindings.vcs", "bindings.commands", "bindings.workflow.review.code", "bindings.workflow.verification"),
    "design/SKILL.md": ("bindings.paths.artifacts.specs",),
    "doc-grounded-questions/SKILL.md": ("bindings.paths.context", "bindings.paths.standards", "bindings.paths.architecture", "bindings.paths.hints"),
    "grill-with-docs/SKILL.md": ("bindings.paths.context",),
    "research/SKILL.md": ("bindings.paths.artifacts.specs",),
    "ship-release/SKILL.md": ("bindings.tracker", "bindings.vcs"),
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
}

SHARED_POLICY_SUPPORT = {}

RETAINED_SUPPORT_CONTRACTS = {}

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
    # The release bridge (#124) reads the retired deploy member of the legacy config.
    "python/agent_tools/release_bridge.py": frozenset({".claude/skills.config.json"}),  # policy-gate-pattern
    "tests/test_release_bridge.py": frozenset({
        ".claude/skills.config.json", "maxParallel",  # policy-gate-pattern
    }),
    "tests/fixtures/legacy-skills-config-1722a65d.json": frozenset({
        "agentBudgetMinutes", "maxParallel",  # policy-gate-pattern
    }),
    # Platform 1.1.0 (https://github.com/fagenorn/nix-config/issues/580) deprecates the
    # legacy store, so the manifest's deprecation entry, its documentation and the
    # resolver tests that pin that entry must name it.
    "home/common/agent-skills/platform-manifest.json": frozenset({".claude/skills.config.json"}),  # policy-gate-pattern
    "python/README.md": frozenset({".claude/skills.config.json", "resolve-bindings"}),  # policy-gate-pattern
    "home/common/agent-skills/tests/test_resolve_platform.py": frozenset({".claude/skills.config.json"}),  # policy-gate-pattern
    "home/common/agent-skills/tests/test_resolve_platform_status.py": frozenset({".claude/skills.config.json"}),  # policy-gate-pattern
    # The strict-cutover fallback audit (https://github.com/fagenorn/nix-config/issues/579)
    # searches the entry surface for the removed resolver and legacy store, so its marker
    # inventory, its tests and its README paragraph must name them as patterns.
    "python/agent_tools/fallback_audit.py": frozenset({"resolve-bindings"}),  # policy-gate-pattern
    "tests/test_fallback_audit.py": frozenset({
        ".claude/skills.config.json", "resolve-bindings",  # policy-gate-pattern
    }),
    # The deprecations-retired verify check (https://github.com/fagenorn/nix-config/issues/582)
    # asks git whether the legacy store is still tracked, so it and its tests must name it.
    "python/agent_tools/verify_checks.py": frozenset({".claude/skills.config.json"}),  # policy-gate-pattern
    "tests/test_verify_checks.py": frozenset({".claude/skills.config.json"}),  # policy-gate-pattern
}

SUPPORT_POLICY_FORBIDDEN = (
    "resolve-project resolve", *LEGACY_POLICY_SURFACE, "auto-detect",
    "helper missing", "not_onboarded", ".claude/specs", ".claude/plans",
    "docs/CONTEXT-MAP.md",
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


# Entries of skills being retired (#688) that a tree may still hold until the
# directories are deleted or a rebuilt home replaces them; spelled in pieces (D9).
RETIRING_POLICY_ENTRIES = frozenset({"from-" "issue/SKILL.md", "ship-" "issue/SKILL.md"})
RETIRING_SKILL_DIRS = ("from-" "issue", "sdd", "ship-" "issue")

# Every `.superpowers/` home a live skill may name, spelled once (D10).
SUPERPOWERS_SEGMENTS = {"workflows"}
SUPERPOWERS_SEGMENT_RE = re.compile(r"\.superpowers/([A-Za-z0-9_.-]+)")


def assert_policy_entries(case, root, entries, require_refusal_reporting=False):
    actual = {str(path.relative_to(root)) for path in root.glob("*/SKILL.md")
              if "resolve-project resolve" in path.read_text(encoding="utf-8")}
    actual -= RETIRING_POLICY_ENTRIES
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
        self.assertNotIn("bindings.vcs.branch_naming", text)

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
        claude_root = Path.home() / ".claude/skills"
        self.assertTrue(claude_root.is_dir(), "managed Claude skill root is absent")
        assert_policy_entries(self, claude_root,
                              SHARED_POLICY_ENTRIES | CLAUDE_POLICY_ENTRIES,
                              require_refusal_reporting=True)
        assert_retained_policy_support(self, claude_root, SHARED_POLICY_SUPPORT)
        assert_retained_policy_support(self, claude_root, RETAINED_SUPPORT_CONTRACTS)
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
                    with self.assertRaisesRegex(AssertionError, "managed Claude skill root is absent"):
                        self.test_installed_policy_surface_matches_source_contract()

    def _install_policy_surface_fixture(self, home):
        claude_root = home / ".claude/skills"
        shared_source = REPO_ROOT / "home/common/agent-skills/skills"
        claude_source = REPO_ROOT / "home/common/claude-code/skills"
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
            REPO_ROOT / "home/common/agent-skills/skills/ship-release/evals/evals.json",
            REPO_ROOT / "home/common/agent-skills/skills/wayfind/evals/evals.json",
            REPO_ROOT / "home/common/agent-skills/skills/writing-plans/evals/evals.json",
            REPO_ROOT / "home/common/claude-code/skills/codex-collaboration/evals/evals.json",
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


def corpus_documents():
    """Every skill document in both skill trees, as (path, text) pairs."""
    for root in SKILL_ROOTS:
        for path in sorted(root.rglob("*.md")):
            yield path, path.read_text(encoding="utf-8")


def live_corpus_documents():
    """corpus_documents() without the skills still being retired (#688)."""
    for path, text in corpus_documents():
        parts = path.relative_to(REPO_ROOT).parts
        if (parts[:4] == ("home", "common", "agent-skills", "skills")
                and parts[4] in RETIRING_SKILL_DIRS):
            continue
        yield path, text


class WorkflowSkillContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handoff = HANDOFF.read_text(encoding="utf-8")
        cls.design = DESIGN.read_text(encoding="utf-8")
        cls.grill = GRILL.read_text(encoding="utf-8")
        cls.collaboration = COLLABORATION.read_text(encoding="utf-8")
        cls.research = RESEARCH.read_text(encoding="utf-8")
        cls.writing_plans = WRITING_PLANS.read_text(encoding="utf-8")
        cls.small_budget_fixture = json.loads(
            SMALL_BUDGET_FIXTURE.read_text(encoding="utf-8")
        )
        cls.oversized_budget_fixture = json.loads(
            OVERSIZED_BUDGET_FIXTURE.read_text(encoding="utf-8")
        )


    def test_no_module_installs_a_codex_entry_surface(self):
        # #687 D1: Codex is a reviewer only; it gets no skills, guidance or config splice.
        codex_module = CODEX_MODULE.read_text(encoding="utf-8")
        guidance = (REPO_ROOT / "home/common/agent-guidance/default.nix").read_text(encoding="utf-8")
        skills = (REPO_ROOT / "home/common/agent-skills/default.nix").read_text(encoding="utf-8")
        self.assertFalse((REPO_ROOT / "home/common/codex" / "skills").exists())
        self.assertIn("codexPackage", codex_module)
        for name, text, forbidden in (
            ("codex", codex_module, ".agents/skills"),
            ("codex", codex_module, "model_reasoning_effort"),
            ("codex", codex_module, "codexConfig"),
            ("agent-guidance", guidance, ".codex/"),
            ("agent-skills", skills, ".agents/skills"),
            ("agent-skills", skills, "migrateCodex" + "SkillLinks"),
            ("agent-skills", skills, "localSkillFiles"),
        ):
            with self.subTest(module=name, forbidden=forbidden):
                self.assertNotIn(forbidden, text)
        self.assertIn('for skillRoot in "$HOME/.claude/skills"; do', skills)
        self.assertIn('".claude/skills/impeccable"', skills)
        self.assertIn('".agents/standards".source', skills)
        self.assertIn('home.sessionPath = [ "$HOME/.agents/bin" ];', skills)
        impeccable = (REPO_ROOT / "tests/test_impeccable_installed.py").read_text(encoding="utf-8")
        self.assertIn('SKILL_ROOTS = (".claude/skills",)', impeccable)
        self.assertNotIn("test_codex_view_is_a_whole_directory_link", impeccable)


    def test_plan_package_contract_is_root_only_and_fail_closed(self):
        self.assertIn("<stem>.tasks/task-1.md", self.writing_plans)
        self.assertIn("[task-N.md](<stem>.tasks/task-N.md)", self.writing_plans)
        for forbidden in ("open_items:", "decisions:", "adr_paths:", "summary:"):
            self.assertNotRegex(self.writing_plans, rf"(?m)^\s*{re.escape(forbidden)}")

    def test_writing_plans_resolves_its_plan_dir_through_the_resolver(self):
        text = normalized(self.writing_plans)
        self.assertIn("resolve-project resolve", text)
        self.assertIn("bindings.paths.artifacts.plans", text)

    def test_writing_plans_no_longer_calls_the_fail_soft_helper(self):
        self.assertNotIn("resolve-bindings", self.writing_plans)  # policy-gate-pattern
        self.assertNotIn("skills.config.json", self.writing_plans)  # policy-gate-pattern

    def test_writing_plans_names_no_retired_error_code_or_plan_dir(self):
        text = normalized(self.writing_plans)
        for forbidden in ("not_onboarded", ".claude/plans"):
            self.assertNotIn(forbidden, text)

    def test_shared_entries_use_the_project_resolver(self):
        for name in (
            "research", "doc-grounded-questions", "design",
            "to-issues", "grill-with-docs", "ship-release",
            "wayfind", "worktrees", "writing-plans",
        ):
            path = (REPO_ROOT / "home/common/agent-skills/skills"
                    / name / "SKILL.md")
            with self.subTest(skill=name):
                self.assertIn("resolve-project resolve", path.read_text(encoding="utf-8"))

    def test_design_and_grill_measure_with_the_checker_and_report_closed_states(self):
        check = "artifact-budget check --kind design-spec --root <spec-root> --format json"
        for producer in (self.design, self.grill):
            self.assertIn(check, normalized(producer))
            self.assertRegex(producer, r"state: complete \| decompose_required \| failed")
            self.assertNotIn("wc -c", producer)

    def test_artifact_reports_are_bounded_root_only_shapes(self):
        for producer in (self.design, self.grill, self.handoff):
            for field in ("kind", "path", "metrics", "budget_status", "notes"):
                self.assertIn(field, producer)
            for metric in ("root_bytes", "total_bytes", "file_count",
                           "largest_member_bytes"):
                self.assertIn(metric, producer)
            self.assertIn("phase_reports.notes_max_characters", producer)
            self.assertIn("validate-report --boundary producer", normalized(producer))
            for forbidden in ("spec_path:", "adr_paths:", "decisions:", "open_items:", "summary:"):
                self.assertNotRegex(producer, rf"(?m)^\s*{re.escape(forbidden)}")

    def test_shared_skills_carry_their_machine_text(self):
        for path, items in SHARED_SKILL_MACHINE_TEXT.items():
            text = normalized(path.read_text(encoding="utf-8"))
            for item in items:
                with self.subTest(path=path.parent.name, item=item):
                    self.assertIn(item, text)

    def test_no_skill_prescribes_a_sibling_candidate(self):
        offenders = [
            f"{path.relative_to(REPO_ROOT)}: {match.group(0)!r}"
            for path, text in corpus_documents()
            for match in SIBLING_CANDIDATE_RE.finditer(normalized(text))
        ]
        self.assertEqual(offenders, [])

    def test_fixture_producer_states_supplement_behavioral_cli_cases(self):
        self.assertTrue(all(item["expected"]["producer_state"] == "complete"
                            for item in self.small_budget_fixture["artifacts"]))
        expected = {(item["kind"], item["case"]): item["expected"]["producer_state"]
                    for item in self.oversized_budget_fixture["artifacts"]}
        self.assertEqual(expected[("design-spec", "design-root-plus-one")], "decompose_required")
        self.assertEqual(expected[("implementation-plan", "plan-ninth-member")], "decompose_required")
        self.assertEqual(expected[("handoff", "handoff-root-plus-one")], "stopped")
        self.assertEqual(expected[("review-package", "review-member-plus-one")], "decompose_required")

    def test_codex_collaboration_has_exactly_one_companion_tail(self):
        blocks = re.findall(r"```text\n(.*?)```", self.collaboration, re.S)
        self.assertEqual(blocks, [
            "bindings.commands[review_id].argv \\\n"
            "  --model gpt-6-astra --effort xhigh \\\n"
            "  --cwd <absolute-worktree> --json\n",
        ])

    def test_codex_collaboration_documents_carry_their_machine_text(self):
        for path, items in CODEX_COLLABORATION_MACHINE_TEXT.items():
            text = normalized(path.read_text(encoding="utf-8").replace("\n> ", "\n"))
            for item in items:
                with self.subTest(path=path.name, item=item):
                    self.assertIn(item, text)

    def test_helper_binaries_resolve_from_bare_names(self):
        # Skills invoke agent-evidence by bare name. The Nix module must put
        # ~/.agents/bin on PATH, and each contract must anchor the full path as
        # fallback for shells that skip profile init.
        nix_module = (
            REPO_ROOT / "home/common/agent-skills/default.nix"
        ).read_text(encoding="utf-8")
        self.assertIn('home.sessionPath = [ "$HOME/.agents/bin" ]', nix_module)
        for name, text in (("research", self.research),):
            with self.subTest(skill=name):
                self.assertIn("~/.agents/bin/agent-evidence", text)
        # The packaged detail producer and external workspace command are both
        # published by bare name; review-package has one command-table owner.
        command_table = (REPO_ROOT / "lib/agent-tools.nix").read_text(encoding="utf-8")
        self.assertIn('"review-package"', command_table)
        self.assertNotIn('".agents/bin/review-package" =', nix_module)
        self.assertIn('".agents/bin/sdd-workspace"', nix_module)
        self.assertIn('".agents/bin/task-brief"', nix_module)
        self.assertIn("source = ./scripts/sdd-workspace;", nix_module)
        self.assertIn("source = ./scripts/task-brief;", nix_module)

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
        for path, text in live_corpus_documents():
            for match in SUPERPOWERS_SEGMENT_RE.finditer(text):
                found.setdefault(match.group(1), set()).add(
                    str(path.relative_to(REPO_ROOT))
                )
        self.assertLessEqual(set(found), SUPERPOWERS_SEGMENTS, found)

    def test_no_live_skill_names_the_ship_review_home(self):
        carriers = [
            str(path.relative_to(REPO_ROOT))
            for path, text in live_corpus_documents()
            if ".superpowers/" "ship-review" in text
        ]
        self.assertEqual(carriers, [])

    def test_build_delivery_callers_name_the_sanctioned_resolution_exception(self):
        exception = ("only sanctioned exception is `workflow-state build-delivery`, "
                     "which performs its own sealed, read-only resolution")
        callers = []
        for path, raw in live_corpus_documents():
            text = normalized(raw)
            if "build-delivery" not in text:
                continue
            relative = path.relative_to(REPO_ROOT).as_posix()
            callers.append(relative)
            with self.subTest(path=relative):
                self.assertIn(exception, text)
        self.assertEqual(sorted(callers), [])

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
)
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
        # The trigger other skills rely on to load this vocabulary (D14).
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
        self.assertGreaterEqual(checked, 5, "the link scan found nothing to check")

    def test_package_carries_no_dispatch_site(self):
        for path in sorted(CODEBASE_DESIGN_DIR.rglob("*")):
            if not path.is_file():
                continue
            with self.subTest(path=str(path.relative_to(CODEBASE_DESIGN_DIR))):
                self.assertNotIn("Agent(", path.read_text(encoding="utf-8"))

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


RETRO_DIR = REPO_ROOT / "home/common/agent-skills/skills/retro"
RETRO_REVISION = "a7d038f6bf7f01b516408e95e2fb56e0b338fa6f"
RETRO_FILES = ("SKILL.md", "LICENSE")


class RetroSkillContractsTest(unittest.TestCase):
    """The vendored, user-invoked retrospective skill."""

    @classmethod
    def setUpClass(cls):
        cls.skill = (RETRO_DIR / "SKILL.md").read_text(encoding="utf-8")
        cls.notice = (RETRO_DIR / "LICENSE").read_text(encoding="utf-8")

    def test_structure_and_explicit_only_metadata(self):
        self.assertEqual(sorted(str(p.relative_to(RETRO_DIR)) for p in RETRO_DIR.rglob("*") if p.is_file()), sorted(RETRO_FILES))
        frontmatter = skill_frontmatter(self.skill)
        self.assertEqual(frontmatter.get("name"), "retro")
        self.assertEqual(frontmatter.get("disable-model-invocation"), "true")
        self.assertNotIn("Agent(", self.skill)

    def test_license_records_provenance_and_the_upstream_notice(self):
        for fragment in (CODEBASE_DESIGN_UPSTREAM, "skills/engineering/retro/", RETRO_REVISION, "Copyright (c) 2026 Matt Pocock", "no automatic synchronisation"):
            self.assertIn(fragment, self.notice)
        self.assertIn(MIT_NOTICE.strip(), self.notice)
        self.assertIn("[LICENSE](LICENSE)", self.skill)
        self.assertNotIn("Permission is hereby granted", self.skill)


IMPROVE_DIR = REPO_ROOT / "home/common/agent-skills/skills/improve-codebase-architecture"
IMPROVE_REVISION = "9c9f36ccd3995266cd675468af71639c8dde1ec5"
IMPROVE_FILES = ("SKILL.md", "HTML-REPORT.md", "LICENSE", "evals/evals.json")
IMPROVE_MARKER = "<!-- agent-dispatch: id=improve-architecture-scan-owner role=owner model=opus effort=high -->"
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
        frontmatter = skill_frontmatter(self.skill)
        self.assertEqual(set(frontmatter), {"name", "description", "disable-model-invocation"})
        self.assertEqual(frontmatter["name"], IMPROVE_DIR.name)
        self.assertTrue(frontmatter["description"].strip())
        self.assertEqual(frontmatter["disable-model-invocation"], "true")
        root = IMPROVE_DIR.resolve()
        checked = 0
        for name, text in {"SKILL.md": self.skill, "HTML-REPORT.md": self.report}.items():
            for target in relative_markdown_links(text):
                checked += 1
                resolved = (root / name).parent.joinpath(target).resolve()
                self.assertTrue(resolved.is_relative_to(root), (name, target))
                self.assertTrue(resolved.is_file(), (name, target))
        self.assertGreaterEqual(checked, 2)

    def test_scan_is_one_registered_dispatch(self):
        lines = self.skill.splitlines()
        self.assertEqual([line for line in lines if "Agent(" in line], [IMPROVE_CALL])
        self.assertEqual(lines.index(IMPROVE_CALL), lines.index(IMPROVE_MARKER) + 1)

    def test_report_scaffold_carries_the_graded_ids_and_strict_mermaid(self):
        # The eval assertion shells parse these ids; Mermaid reads its config.
        for fragment in ('<section id="candidates"', '<section id="top-recommendation"',
                         'securityLevel: "strict"', "htmlLabels: false"):
            self.assertIn(fragment, self.report)
        self.assertNotIn('securityLevel: "loose"', self.report)

    def test_license_records_ordered_provenance(self):
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
        self.assertEqual((site["path"], site["marker"], site["call"], site["role"], site["model"], site["effort"], site["requires"]), ("home/common/agent-skills/skills/improve-codebase-architecture/SKILL.md", IMPROVE_MARKER, IMPROVE_CALL, "owner", "opus", "high", []))
        self.assertEqual(data["scenarios"]["improve-codebase-architecture"], [{"workflow": "improve-codebase-architecture", "dispatch": "improve-architecture-scan-owner", "role": "owner", "model": "opus", "effort": "high", "requires": []}])

    def test_eval_assertion_shells_are_unique_and_behavioral(self):
        self.assertEqual(self.evals["skill_name"], "improve-codebase-architecture")
        cases = {case["id"]: case for case in self.evals["evals"]}
        self.assertEqual({i: (c["name"], c["mode"]) for i, c in cases.items()}, {1: ("scan-only-renders-a-temporary-report", "pipeline"), 2: ("clear-selection-reaches-a-design-worktree", "pipeline"), 3: ("foggy-selection-routes-to-wayfind", "pipeline")})
        required_shells = {
            1: {"temporary report exists outside repository": ('architecture-review-', '"$OUT"', '[ -f "$report" ]', '$REPO'), "report is evidence-backed or truthful": ('"$OUT"', 'python3 - "$report"', "HTMLParser", "data-architecture-candidate", 'data-evidence', "module-callers", "caller-interface-knowledge", "locality-leverage", "deletion-test", "dependency-adapters", "tests-interface-surface", "context-decision-conflict", "data-diagram-text", "before", "after", "no-candidates", "top-recommendation", "expected_candidate_ids", "zero_text !=", "1 <= candidate_count <= 5"), "history miss widened the scan": ("out_matches", "widen"), "repository and branches stayed unchanged": ('test "$WT_COUNT" -eq 0', 'status=$(git -C "$REPO" status --porcelain)', 'test -z "$status"', 'test "$(git -C "$REPO" rev-parse HEAD)" = "$(git -C "$REPO" rev-parse origin/main)"', "branches=$(git -C \"$REPO\" for-each-ref --format='%(refname:short)' refs/heads)", 'test "$branches" = "main"')},
            2: {"one isolated design worktree exists": ('test "$WT_COUNT" -eq 1', 'test -n "$WT"'), "design spec was committed": ('commits_touch "$WT" "${SPEC_DIR#"$REPO"/}"',), "source and tests stayed unchanged": ('path_unchanged_since "$REPO" origin/main tinytask tests', 'path_unchanged_since "$WT" origin/main tinytask tests'), "no plan was created": ('if has_file "$PLAN_DIR"/*.md "$WT/${PLAN_DIR#"$REPO"/}"/*.md; then', "fail"), "domain review was reached": ("out_matches", "grill-with-docs"), "scope workflow was recommended": ("out_matches", "recommend", "&&", "writing-plans|to-issues"), "design returned control without continuation": ('sed \'/^[[:space:]]*$/d\' "$OUT"', DESIGN_COMPLETE)},
            3: {"new wayfind map exists and prior map stayed unchanged": ('new_map_count=0', 'for map in "$REPO"/.claude/wayfind/*/map.md; do', "*/concurrent-shells/map.md) continue", '[ -f "$map" ] || continue', 'relative_map=${map#"$REPO"/}', 'if git -C "$REPO" cat-file -e "origin/main:$relative_map" 2>/dev/null; then', 'new_map_count=$((new_map_count + 1))', 'test "$new_map_count" -eq 1', 'path_unchanged_since "$REPO" origin/main .claude/wayfind/concurrent-shells'), "no worktree was created": ('test "$WT_COUNT" -eq 0',), "no spec or plan was created": ('if has_file "$SPEC_DIR"/*.md "$PLAN_DIR"/*.md; then', "fail"), "source and tests stayed unchanged": ('path_unchanged_since "$REPO" origin/main tinytask tests',), "wayfind returned control without continuation": ('sed \'/^[[:space:]]*$/d\' "$OUT"', "WAYFIND_COMPLETE: map created; control returned before issue creation, planning, or implementation.")},
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
    """#637: orchestrate-issues is retired; the Claude tree holds deliver-batch."""

    @classmethod
    def setUpClass(cls):
        root = os.environ.get("AGENT_SKILLS_INSTALLED_HOME")
        if root is None:
            raise unittest.SkipTest("AGENT_SKILLS_INSTALLED_HOME is unset; run "
                                    "`just agent-installed-skill-tests`")
        cls.root = Path(root)

    def test_the_claude_tree_holds_deliver_batch_and_no_orchestrate_issues(self):
        self.assertFalse(os.path.lexists(self.root / ".agents/skills"))
        self.assertFalse((self.root / ".claude/skills/orchestrate-issues").exists())
        self.assertTrue((self.root / ".claude/skills/deliver-standard/deliver-standard.js").is_file())
        installed = (self.root / ".claude/skills/deliver-batch/SKILL.md").read_text(encoding="utf-8")
        source = REPO_ROOT / "home/common/claude-code/skills/deliver-batch/SKILL.md"
        self.assertEqual(installed, source.read_text(encoding="utf-8"))


class ToIssuesCriterionLineContractsTest(unittest.TestCase):
    """#274 AC1: every to-issues criterion line is typed and located (D1, D9)."""

    TO_ISSUES = REPO_ROOT / "home/common/agent-skills/skills/to-issues/SKILL.md"
    LINE_RE = re.compile(
        r"^- \[ \] \[(code|evidence|human)\] \S.* — measured: \S.*$")

    @classmethod
    def setUpClass(cls):
        cls.text = cls.TO_ISSUES.read_text(encoding="utf-8")
        template = cls.text[cls.text.index("<issue-template>"):
                            cls.text.index("</issue-template>")]
        section = template[template.index("## Acceptance criteria\n"):]
        section = section[:section.index("\n## ", 1)]
        cls.criterion_lines = [
            line for line in section.splitlines() if line.startswith("- ")]

    def test_every_template_criterion_line_carries_a_kind_and_a_measured_clause(self):
        self.assertGreaterEqual(len(self.criterion_lines), 3)
        for line in self.criterion_lines:
            with self.subTest(line=line):
                self.assertRegex(line, self.LINE_RE)
        kinds = {match.group(1) for match in map(self.LINE_RE.match, self.criterion_lines)
                 if match}
        self.assertEqual(kinds, {"code", "evidence", "human"})

    def test_the_criterion_line_shape_is_stated(self):
        self.assertIn(
            "`- [ ] [code|evidence|human] <observable outcome> — measured: <where>`",
            normalized(self.text))

    def test_the_criterion_format_points_to_the_acceptance_planning_rules(self):
        """#633 AC2: the criterion line format points to the shared rules; the hot file does not grow."""
        text = normalized(self.text)
        rules = text[text.index("Write each criterion as"):text.index("The `measured:` clause")]
        self.assertIn(ACCEPTANCE_RULES_POINTER, rules)
        self.assertLessEqual(len(self.TO_ISSUES.read_bytes()), 6487)


class IssueFilingRouteTest(unittest.TestCase):
    """#697 AC2: every instruction that files an issue with blocking edges goes through forge-issue (D2, D4, D11)."""

    TREES = ("home/common/agent-skills/skills", "home/common/agent-skills/standards",
             "home/common/claude-code/agents", "home/common/claude-code/skills",
             "home/common/agent-guidance")
    HAND_BUILT = ("gh issue create", "dependencies/blocked_by")
    ROUTED = ("home/common/agent-skills/skills/to-issues/SKILL.md",
              "home/common/agent-skills/skills/wayfind/SKILL.md",
              "home/common/agent-skills/skills/deliver-direct/SKILL.md",
              "home/common/agent-skills/standards/acceptance-planning.md",
              "home/common/claude-code/skills/deliver-standard/deliver-standard.js")

    def test_no_instruction_files_an_issue_or_links_a_blocker_by_hand(self):
        for tree in self.TREES:
            for path in sorted((REPO_ROOT / tree).rglob("*")):
                if not path.is_file() or path.suffix not in (".md", ".js", ".json"):
                    continue
                text = path.read_text(encoding="utf-8")
                for phrase in self.HAND_BUILT:
                    with self.subTest(path=str(path.relative_to(REPO_ROOT)), phrase=phrase):
                        self.assertNotIn(phrase, text)

    def test_each_filing_path_names_forge_issue_create(self):
        for name in self.ROUTED:
            with self.subTest(path=name):
                self.assertIn("forge-issue create", (REPO_ROOT / name).read_text(encoding="utf-8"))

    def test_the_split_rule_files_with_a_blocked_by_edge(self):
        rules = ACCEPTANCE_RULES.read_text(encoding="utf-8")
        r6 = next(line for line in rules.splitlines() if line.startswith("- **R6."))
        self.assertIn("`forge-issue create --blocked-by <n>`", r6)


class ToIssuesStandaloneBodyContractsTest(unittest.TestCase):
    """#495 AC1: the to-issues template puts Problem before What to build, and
    the skill states the first-use and stranger-read rules (D3, D4, D6)."""

    TEMPLATE_HEADINGS = ["Parent", "Problem", "What to build", "Decisions",
                         "Acceptance criteria", "Blocked by"]

    @classmethod
    def setUpClass(cls):
        cls.text = ToIssuesCriterionLineContractsTest.TO_ISSUES.read_text(encoding="utf-8")

    def test_the_template_sections_put_the_problem_before_what_to_build(self):
        template = self.text[self.text.index("<issue-template>"):
                             self.text.index("</issue-template>")]
        headings = [line[3:] for line in template.splitlines() if line.startswith("## ")]
        self.assertEqual(headings, self.TEMPLATE_HEADINGS)

    def test_the_first_use_and_stranger_read_rules_are_stated(self):
        text = normalized(self.text)
        for token in ("at first use", "reread each body"):
            with self.subTest(token=token):
                self.assertIn(token, text)


class AcceptanceMapContractsTest(unittest.TestCase):
    """#274 AC2: plans carry an Acceptance map and plan review blocks a gap (D2-D5)."""

    WRITING_PLANS = REPO_ROOT / "home/common/agent-skills/skills/writing-plans/SKILL.md"

    @classmethod
    def setUpClass(cls):
        cls.plans = cls.WRITING_PLANS.read_text(encoding="utf-8")

    @staticmethod
    def section(text, heading):
        start = text.index("\n" + heading + "\n") + 1
        end = text.find("\n## ", start + len(heading))
        return text[start:] if end < 0 else text[start:end]

    def test_the_plan_template_carries_one_task_index_and_one_acceptance_map(self):
        headings = [line for line in self.plans.splitlines() if line.startswith("## ")]
        self.assertEqual(headings.count("## Task index"), 1)
        self.assertEqual(headings.count("## Acceptance map"), 1)

    def test_the_map_section_carries_the_forms_acceptance_map_covers_reads(self):
        mapping = normalized(self.section(self.plans, "## Acceptance map"))
        for form in ("| AC | Kind | Task | Check |", "`None — no acceptance criteria.`",
                     "`<kind> (classified)`"):
            with self.subTest(form=form):
                self.assertIn(form, mapping)

    def test_the_map_and_self_review_apply_the_acceptance_planning_rules(self):
        """#633 AC2: self-review points to the shared rules; the planning-owner hot file
        does not grow."""
        review = normalized(self.section(self.plans, "## Self-review"))
        self.assertIn(ACCEPTANCE_RULES_POINTER, review)
        self.assertLessEqual(len(self.WRITING_PLANS.read_bytes()), 10859)


class AcceptancePlanningRulesTest(unittest.TestCase):
    """#633 AC2: the acceptance planning rules live once, read on demand, never hot."""

    def test_the_rules_document_exists_once_and_is_in_no_hot_list(self):
        found = sorted((REPO_ROOT / "home").rglob("acceptance-planning.md"))
        self.assertEqual(found, [ACCEPTANCE_RULES])
        model = json.loads((REPO_ROOT / "home/common/agent-skills/instruction-load.json")
                           .read_text(encoding="utf-8"))
        for profile in model["profiles"]:
            with self.subTest(profile=profile["id"]):
                self.assertFalse([m for m in profile["hot"] if "acceptance-planning" in m])

    def test_r8_do_it_do_not_ask(self):
        """#670 rule 1: a reversible in-repo action needs no ask; asks are only for R3,
        production or a genuine product or design decision; one-run evidence is not held."""
        text = normalized(ACCEPTANCE_RULES.read_text(encoding="utf-8"))
        rules = text[text.index("## Rules"):text.index("## Verify block fields")]
        self.assertIn("- **R8. Do it, do not ask.**", rules)
        r8 = rules[rules.index("**R8."):]
        for needle in ("reversible", "senses, hands, credentials, money or taste", "recorded at ship",
                       "pushing a branch", "R3", "production system", "product or design decision",
                       "recorded when observed", "never held as a recurring check"):
            with self.subTest(needle=needle):
                self.assertIn(needle, r8)

    def test_an_unattended_command_check_must_be_a_verification_command(self):
        """#633 COR-001: the runner runs only a command that is a member of
        `workflow.verification` and leaves any other pending as `command_not_verification`,
        so the rules require that membership of a command check, not any declared command."""
        text = normalized(ACCEPTANCE_RULES.read_text(encoding="utf-8"))
        row = text[text.index("| command |"):text.index("| threshold |")]
        self.assertIn("`workflow.verification`", row)
        self.assertNotIn("a declared command id", row)
        self.assertIn("`command_not_verification`", text)

    def test_three_skills_point_to_the_rules(self):
        """#633 AC2: deliver-direct, writing-plans and to-issues each name the rules file."""
        for path in (DirectLaneRoutingTest.DELIVER_DIRECT, WRITING_PLANS,
                     ToIssuesCriterionLineContractsTest.TO_ISSUES):
            with self.subTest(skill=path.parent.name):
                self.assertIn(ACCEPTANCE_RULES_POINTER, normalized(path.read_text(encoding="utf-8")))


class AcceptanceMapEvalGradingTest(unittest.TestCase):
    """#274 AC3: fixture 001 is tagged and both evals grade its map (D6, D7, D10)."""

    ASSERT_LIB = REPO_ROOT / "home/common/agent-skills/evals/assert-lib.sh"
    FIXTURE = (REPO_ROOT
               / "home/common/agent-skills/evals/fixture-repo/issues/001-well-specified.md")
    EVALS = (
        REPO_ROOT / "home/common/agent-skills/skills/writing-plans/evals/evals.json",
    )
    ASSERT_NAME = "the plan's acceptance map has one row per issue criterion"
    TAGGED = ("# Issue\n\n## Acceptance criteria\n\n"
              "- [ ] [code] a — measured: t\n"
              "- [ ] [evidence] b — measured: cmd, idle, ≤ 5 s\n"
              "- [x] [human] c — measured: the user, on mbp\n\n"
              "## Blocked by\n\nNone\n")
    LEGACY = "# Issue\n\n## Acceptance criteria\n\n1. a\n   more of a\n2. b\n\n## Notes\n"
    EMPTY = "# Issue\n\n## Acceptance criteria\n\n## Notes\n"

    @staticmethod
    def plan(*rows):
        return ("# Plan\n\n## Task index\n\nTask 1 — x — f — full — [task-1.md](p.tasks/task-1.md)\n\n"
                "## Acceptance map\n\n| AC | Kind | Task | Check |\n|----|------|------|-------|\n"
                + "".join(f"| {ac} | {kind} | Task 1 | check |\n" for ac, kind in rows)
                + "\n## Decisions\n")

    def covers(self, plan_text, issue_text=None, issue_path=None):
        with tempfile.TemporaryDirectory() as temporary:
            plan_path = Path(temporary) / "plan.md"
            plan_path.write_text(plan_text, encoding="utf-8")
            if issue_path is None:
                issue_path = Path(temporary) / "issue.md"
                issue_path.write_text(issue_text, encoding="utf-8")
            return subprocess.run(
                ["bash", "-c", 'source "$0"; acceptance_map_covers "$1" "$2"',
                 str(self.ASSERT_LIB), str(plan_path), str(issue_path)],
                check=False, capture_output=True, text=True)

    def test_a_conforming_tagged_map_passes(self):
        result = self.covers(self.plan(("AC1", "code"), ("AC2", "evidence"), ("AC3", "human")),
                             self.TAGGED)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_each_structural_gap_fails_with_a_reason(self):
        cases = {
            "missing row": (("AC1", "code"), ("AC2", "evidence")),
            "duplicate row": (("AC1", "code"), ("AC1", "code"), ("AC2", "evidence"),
                              ("AC3", "human")),
            "out of order": (("AC2", "evidence"), ("AC1", "code"), ("AC3", "human")),
            "kind contradicts tag": (("AC1", "evidence"), ("AC2", "evidence"),
                                     ("AC3", "human")),
            "tagged kind reclassified": (("AC1", "code (classified)"), ("AC2", "evidence"),
                                         ("AC3", "human")),
        }
        for name, rows in cases.items():
            with self.subTest(case=name):
                result = self.covers(self.plan(*rows), self.TAGGED)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stdout.strip(), "a failing helper names its reason")

    def test_legacy_numbered_criteria_need_a_classified_kind(self):
        good = self.covers(self.plan(("AC1", "code (classified)"), ("AC2", "human (classified)")),
                           self.LEGACY)
        self.assertEqual(good.returncode, 0, good.stdout)
        bare = self.covers(self.plan(("AC1", "code"), ("AC2", "human (classified)")),
                           self.LEGACY)
        self.assertNotEqual(bare.returncode, 0)

    def test_no_criteria_pass_only_on_the_none_line(self):
        none = "# Plan\n\n## Acceptance map\n\nNone — no acceptance criteria.\n"
        self.assertEqual(self.covers(none, self.EMPTY).returncode, 0)
        self.assertNotEqual(self.covers("# Plan\n\n## Acceptance map\n", self.EMPTY).returncode, 0)
        self.assertNotEqual(self.covers("# Plan\n\n## Task index\n", self.TAGGED).returncode, 0)

    def test_fixture_001_has_seven_tagged_code_criteria_graded_by_the_helper(self):
        text = self.FIXTURE.read_text(encoding="utf-8")
        section = text[text.index("## Acceptance criteria\n"):]
        section = section[:section.index("\n## ", 1)]
        items = [line for line in section.splitlines()
                 if re.match(r"^(- \[[ xX]\] |[0-9]+\. )", line)]
        self.assertEqual(len(items), 7)
        for line in items:
            with self.subTest(line=line):
                self.assertRegex(
                    line, r"^- \[ \] \[code\] \S.* — measured: .*tests/test_cli\.py$")
        result = self.covers(self.plan(*((f"AC{n}", "code") for n in range(1, 8))),
                             issue_path=self.FIXTURE)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_both_fixture_001_evals_call_the_helper(self):
        for path in self.EVALS:
            with self.subTest(evals=path.parent.parent.name):
                case = next(item for item in json.loads(path.read_text(encoding="utf-8"))["evals"]
                            if item["id"] == 1)
                shells = [item["shell"] for item in case["asserts"]
                          if item["name"] == self.ASSERT_NAME]
                self.assertEqual(len(shells), 1)
                self.assertIn("acceptance_map_covers", shells[0])
                self.assertIn('"$REPO/issues/001-well-specified.md"', shells[0])

    def test_both_eval_assert_shells_grade_a_plan_under_harness_paths(self):
        # run-eval.sh exports PLAN_DIR as the resolver's ABSOLUTE path under
        # $REPO and runs each shell as `cd $REPO && bash -c "source lib; …"`.
        full = self.plan(*((f"AC{n}", "code") for n in range(1, 8)))
        short = self.plan(*((f"AC{n}", "code") for n in range(1, 7)))
        for path in self.EVALS:
            case = next(item for item in json.loads(path.read_text(encoding="utf-8"))["evals"]
                        if item["id"] == 1)
            shell = next(item["shell"] for item in case["asserts"]
                         if item["name"] == self.ASSERT_NAME)
            for label, text, passes in (("complete", full, True), ("missing row", short, False)):
                with self.subTest(evals=path.parent.parent.name, plan=label), \
                        tempfile.TemporaryDirectory() as temporary:
                    repo = Path(temporary) / "repo"
                    worktree = Path(temporary) / "wt"
                    plan_dir = repo / ".agents/artifacts/plans"
                    (repo / "issues").mkdir(parents=True)
                    (repo / "issues/001-well-specified.md").write_text(
                        self.FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
                    (repo / ".agents/artifacts/plans").mkdir(parents=True)
                    (repo / ".agents/artifacts/plans/plan.md").write_text(text, encoding="utf-8")
                    env = dict(os.environ, REPO=str(repo), WT=str(worktree),
                               PLAN_DIR=str(plan_dir))
                    result = subprocess.run(
                        ["bash", "-c", f"source '{self.ASSERT_LIB}'; {shell}"],
                        cwd=repo, env=env, check=False, capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, passes,
                                     result.stdout + result.stderr)


class DirectLaneRoutingTest(unittest.TestCase):
    """#572: eligible issues route to deliver-direct, which spells the guard-accepted forms."""

    DELIVER_DIRECT = REPO_ROOT / "home/common/agent-skills/skills/deliver-direct/SKILL.md"

    def test_deliver_direct_spells_the_guard_accepted_ship_forms(self):
        text = normalized(self.DELIVER_DIRECT.read_text(encoding="utf-8"))
        for form in (
            "`git -C <dir> push origin <branch>`",
            "`gh pr create --repo <slug> --base <int> --head <branch> --title '<title>' --body '<body>'`",
            "`gh pr merge <pr> --repo <slug> --<vcs.merge.strategy>`",
            "`reviewer-lite` with `lane: direct`",
            "**Eligibility.**",
        ):
            with self.subTest(form=form):
                self.assertIn(form, text)

    def test_deliver_direct_claims_with_forge_claim(self):
        """#635: step 1 claims through forge-claim and goes on only on its holding verdicts;
        the hot instruction bytes do not grow."""
        raw = self.DELIVER_DIRECT.read_bytes()
        self.assertLessEqual(len(raw), 5032)
        text = normalized(raw.decode("utf-8"))
        step1 = text[text.index("**Claim.**"):text.index("**Worktree.**")]
        for token in ("`forge-claim acquire --repo <slug> --issue <n> --holder <host>/session-<id> --branch <branch>`",
                      "`forge-claim release`", "`acquired`", "`already_held`"):
            with self.subTest(token=token):
                self.assertIn(token, step1)
        # COR-002: the claim records its branch (so branch activity counts) and is renewed before each push and the merge.
        step5 = text[text.index("**Ship.**"):text.index("**Land in order.**")]
        for token in ("`forge-claim renew`", "`renewed`"):
            with self.subTest(token=token):
                self.assertIn(token, step5)
        for gone in ("assignee", "in-progress", "gh issue view"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, step1)

    def test_deliver_direct_fetches_before_judging_whether_the_issue_still_applies(self):
        """#677: a stale origin/<int> must not close an unresolved issue, so step 1 fetches before it decides."""
        text = normalized(self.DELIVER_DIRECT.read_text(encoding="utf-8"))
        step1 = text[text.index("**Claim.**"):text.index("**Worktree.**")]
        self.assertIn("Fetch", step1)
        self.assertLess(step1.index("Fetch"), step1.index("still applies"))

    def test_deliver_direct_holds_the_land_lock_from_sync_through_merge(self):
        """#677: step 6 carries the consumed forms in ship order: waiting acquire, sync merge, push,
        required-check wait, the holding verdict before the merge, release; the hot bytes do not grow."""
        raw = self.DELIVER_DIRECT.read_bytes()
        self.assertLessEqual(len(raw), 5032)
        text = normalized(raw.decode("utf-8"))
        land = text[text.index("**Land in order.**"):text.index("**Close out.**")]
        at = 0
        for form in (
            "`forge-claim land acquire --repo <slug> --branch <int> --sha <head> --wait`",
            "`origin/<int>`",
            "`git -C <dir> push origin <branch>`",
            "`gh pr checks <pr> --repo <slug> --watch`",
            "`already_held`",
            "`forge-claim land release --repo <slug> --branch <int> --sha <lock sha>`",
        ):
            with self.subTest(form=form):
                found = land.find(form, at)
                self.assertGreaterEqual(found, 0, f"{form} missing or out of order")
                at = found + len(form)
        for token in ("`acquired`", "`moved`", "`--wait`"):
            with self.subTest(token=token):
                self.assertIn(token, land)

    def test_deliver_direct_review_fixes_from_its_first_runs(self):
        """#572: verification is not a test-first step; required checks come from the rules API."""
        text = normalized(self.DELIVER_DIRECT.read_text(encoding="utf-8"))
        step3 = text[text.index("**Test first.**"):text.index("**Review.**")]
        self.assertNotIn("workflow.verification", step3)
        self.assertIn("`gh api repos/<slug>/rules/branches/<int>`", text)

    def test_deliver_direct_review_also_runs_the_configured_code_review(self):
        """#572: an available workflow.review.code runs beside the fresh reviewer, never skipped."""
        text = normalized(self.DELIVER_DIRECT.read_text(encoding="utf-8"))
        step4 = text[text.index("**Review.**"):text.index("**Ship.**")]
        for rule in (
            "`reviewer-lite` with `lane: direct`",
            "`capabilities.review.code`",
            "`bindings.workflow.review.code`",
            "`codex-collaboration`",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, step4)

    def test_deliver_direct_holds_only_on_a_linted_verify_block(self):
        """#633 AC1: step 7 regrades code criteria, closes when none is left open, else
        holds only on a lint-accepted verify block and runs verify-pending once for this
        repository and issue, pointing to the shared rules."""
        text = normalized(self.DELIVER_DIRECT.read_text(encoding="utf-8"))
        step7 = text[text.index("**Close out.**"):text.index("**Report**")]
        for token in ("regrade", "`code`", "none left: close the issue",
                      "`verify-pending lint`", "verify block",
                      "`verify-pending run --host <host> --repo <slug> --issue <n>` once",
                      "`needs-verification`", ACCEPTANCE_RULES_POINTER):
            with self.subTest(token=token):
                self.assertIn(token, step7)
        self.assertNotIn("comment what remains", text)


class HandBuiltTimeContractsTest(unittest.TestCase):
    """#309 D9: no skill document hands workflow-state a time; the helper reads its clock."""

    def documents(self):
        for tree in SKILL_TREES:
            self.assertTrue(tree.is_dir(), tree)
            yield from sorted(path for path in tree.rglob("*.md") if path.is_file())

    def test_no_skill_document_passes_now(self):
        checked = 0
        for path in self.documents():
            text = path.read_text(encoding="utf-8")
            checked += 1
            with self.subTest(document=str(path.relative_to(REPO_ROOT))):
                self.assertIsNone(NOW_FLAG.search(text))
                self.assertIsNone(NOW_KEY.search(text))
        self.assertGreater(checked, 20)


class ClaudeCompatibleWaitContractsTest(unittest.TestCase):
    """#474: no skill document chains a check onto a foreground `sleep`."""

    QUOTE_MARKER = re.compile(r"(?m)^[ \t]*>[ \t]?")
    # The retired "`sleep N`, then check once" family, read whitespace-normalized.
    CHAINED_CHECK = re.compile(r"`sleep [^`]*`, then check")
    # A `sleep <arg>` opening a command, at a line or code-span start, chained by && || ;
    CHAINED_SHELL = re.compile(r"(?:^[ \t]*|`)sleep[ \t]+[^\s`;&|]+[ \t]*(?:&&|\|\||;)", re.M)

    @classmethod
    def unquoted(cls, text):
        return cls.QUOTE_MARKER.sub("", text)

    @classmethod
    def chained_waits(cls, text):
        """The shapes `text` matches: "prose", "shell", both or neither."""
        body = cls.unquoted(text)
        found = []
        if cls.CHAINED_CHECK.search(normalized(body)):
            found.append("prose")
        if cls.CHAINED_SHELL.search(body):
            found.append("shell")
        return found

    def test_the_shapes_match_the_chained_forms_and_spare_the_rest(self):
        for text, shape in (
            ("    run one bounded foreground `sleep N`, then check\n    once.", ["prose"]),
            ("> run one bounded foreground `sleep N`, then\n> check once.", ["prose"]),
            ("`sleep 30 && gh pr checks 1`", ["shell"]),
            ("sleep 60; workflow-state status", ["shell"]),
            ("  > `sleep 5 || true`", ["shell"]),
        ):
            with self.subTest(hit=text):
                self.assertEqual(self.chained_waits(text), shape)
        for text in (
            "`sleep <wait_seconds>`",
            "background `sleep <wait_seconds>`; every wait",
            "`until <check>; do sleep 2; done`",
            "Never run `sleep` in the foreground: wait with Monitor",
        ):
            with self.subTest(spare=text):
                self.assertEqual(self.chained_waits(text), [])

    def test_no_skill_document_chains_a_check_onto_a_foreground_sleep(self):
        checked = 0
        for tree in SKILL_TREES:
            self.assertTrue(tree.is_dir(), tree)
            for path in sorted(path for path in tree.rglob("*.md") if path.is_file()):
                checked += 1
                with self.subTest(document=str(path.relative_to(REPO_ROOT))):
                    self.assertEqual(self.chained_waits(path.read_text(encoding="utf-8")), [])
        self.assertGreater(checked, 20)


PLANNING_DOCUMENTS = (WRITING_PLANS,)
BUDGET_BASE = "8d0bbc25383663fa3bc86623d0701e7d4bd4f9bc"


def assert_no_larger_than_base(test, paths):
    for path in paths:
        relative = path.relative_to(REPO_ROOT).as_posix()
        shown = subprocess.run(["git", "-C", str(REPO_ROOT), "cat-file", "-s", f"{BUDGET_BASE}:{relative}"],
                               capture_output=True, text=True)
        if shown.returncode:
            test.skipTest("delivery base not in this clone")
        with test.subTest(path=relative):
            test.assertLessEqual(path.stat().st_size, int(shown.stdout))


class ProjectionCallerContractsTest(unittest.TestCase):

    def test_planning_neither_forecasts_nor_runs_the_change(self):
        for path in PLANNING_DOCUMENTS:
            text = path.read_text(encoding="utf-8").lower()
            for word in ("feasibility", "forecast", "projection"):
                with self.subTest(path=path.name, word=word):
                    self.assertNotIn(word, text)
        self.assertIn("failing test is the only run", normalized(WRITING_PLANS.read_text(encoding="utf-8")))

    def test_edited_planning_documents_do_not_grow(self):
        assert_no_larger_than_base(self, (WRITING_PLANS,))


class ExecutionCallerContractsTest(unittest.TestCase):

    def test_the_diff_review_does_not_cap_the_range_listing(self):
        diff_review = normalized(DIFF_REVIEW.read_text(encoding="utf-8"))
        self.assertNotIn("the first 20 entries", diff_review)


class BatchRoutingTest(unittest.TestCase):
    """#637 AC2: no skill or agent text routes batches to the retired orchestrate-issues."""

    OLD_ROUTE = re.compile(r"orchestrate[- ]issues", re.IGNORECASE)

    def test_no_global_text_names_orchestrate_issues(self):
        snapshot = working_tree(REPO_ROOT)
        found = []
        for root in agnostic_lint.GLOBAL_CORPUS:
            paths = snapshot.list_files(root) or ([root] if snapshot.read(root) is not None else [])
            self.assertTrue(paths, f"{root}: no files scanned")
            for path in paths:
                if path.endswith((".pyc", ".png", ".jpg", ".pdf")):
                    continue
                text = (snapshot.read(path) or b"").decode("utf-8", "replace")
                found += [f"{path}:{n}" for n, line in enumerate(text.splitlines(), start=1)
                          if self.OLD_ROUTE.search(line)]
        self.assertEqual(found, [])

    def test_the_batch_trigger_belongs_to_deliver_batch(self):
        skill = REPO_ROOT / "home/common/claude-code/skills/deliver-batch/SKILL.md"
        self.assertIn('Use for "deliver issues', skill.read_text(encoding="utf-8"))

    def test_the_lead_stops_a_relaunch_that_repeats_the_last_one(self):
        text = (REPO_ROOT / "home/common/claude-code/skills/deliver-batch/SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?s)non-null `relaunch`.*?unless its args equal the previous run.*?stop, reporting")


class CodexEntryRetirementTest(unittest.TestCase):
    """#687 AC1: no tracked file outside the artifact store names a retired Codex entry surface."""

    # Built by concatenation so this file does not match its own scan.
    RETIRED = ("home/common/codex/" + "skills", "openai" + ".yaml", "migrateCodex" + "SkillLinks")

    def test_no_tracked_file_names_a_retired_codex_surface(self):
        args = ["git", "-C", str(REPO_ROOT), "grep", "-n", "-F"]
        for pattern in self.RETIRED:
            args += ["-e", pattern]
        found = subprocess.run(args + ["--", ".", ":!.agents/artifacts"],
                               capture_output=True, text=True, check=False)
        self.assertEqual((found.returncode, found.stdout), (1, ""), found.stderr)

    def test_no_skill_package_ships_a_codex_manifest(self):
        for tree in SKILL_TREES:
            with self.subTest(tree=str(tree)):
                self.assertEqual(sorted(tree.rglob("openai" + ".yaml")), [])


class CodexCollaborationContractTest(unittest.TestCase):
    """#687: codex-collaboration serves the plan path and diff range the deliver controllers send."""

    SKILL_DIR = REPO_ROOT / "home/common/claude-code/skills/codex-collaboration"
    CONTROLLER = REPO_ROOT / "home/common/claude-code/skills/deliver-standard/deliver-standard.js"
    RETIRED = ("from-" "issue", "sdd", "REVIEW-CONTRACT", "artifact-budget")
    LEGACY = ("producer", "manifest", "metrics", "rubric", "Phase", "--auto",
              "native fallback", "Claude fallback")

    def documents(self):
        return sorted(p for p in self.SKILL_DIR.rglob("*") if p.is_file())

    def test_the_skill_names_no_retired_pipeline(self):  # AC2
        for path in self.documents():
            text = path.read_text(encoding="utf-8")
            for token in self.RETIRED + self.LEGACY:
                with self.subTest(path=path.name, token=token):
                    self.assertNotIn(token, text)

    def test_the_results_carry_the_controllers_codex_schema(self):  # AC3 (key set only)
        # Pins only what the controller consumes (agent-helpers rule 6): the
        # CODEX result keys and the SEV enum of deliver-standard.js, read from
        # the controller itself so the two cannot drift. No English phrase is pinned.
        controller = self.CONTROLLER.read_text(encoding="utf-8")
        sev = re.search(r"^const SEV = \{[^\n]*enum: \[([^\]]*)\]", controller, re.M)
        codex = re.search(r"^const CODEX = \{\n  type: 'object',\n  properties: \{([^\n]*)\},\n", controller, re.M)
        self.assertIsNotNone(sev)
        self.assertIsNotNone(codex)
        severities = re.findall(r"'([a-z]+)'", sev.group(1))
        keys, depth = [], 0  # top-level property names only, not nested `type`/`enum`
        for m in re.finditer(r"[{}]|(?<![\w'])([a-z_]+): ", codex.group(1)):
            depth += {"{": 1, "}": -1}.get(m.group(0), 0)
            if m.group(1) and depth == 0:
                keys.append(m.group(1))
        self.assertEqual(severities, ["critical", "important", "minor"])
        self.assertEqual(keys, ["available", "verdict", "findings", "raw_summary"])
        skill = normalized(COLLABORATION.read_text(encoding="utf-8"))
        for key in keys:
            with self.subTest(document="SKILL.md", key=key):
                self.assertIn(f"`{key}`", skill)
        for path in (PLAN_REVIEW, DIFF_REVIEW):
            text = normalized(path.read_text(encoding="utf-8"))
            for value in severities:
                with self.subTest(document=path.name, severity=value):
                    self.assertIn(f"`{value}`", text)


if __name__ == "__main__":
    unittest.main()
