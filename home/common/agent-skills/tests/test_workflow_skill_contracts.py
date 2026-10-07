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
FROM_ISSUE = REPO_ROOT / "home/common/agent-skills/skills/from-issue/SKILL.md"
AUTO = REPO_ROOT / "home/common/agent-skills/skills/from-issue/AUTO.md"
ROLLOVER = REPO_ROOT / "home/common/agent-skills/skills/from-issue/rollover.md"
DELEGATED_OWNER = REPO_ROOT / "home/common/agent-skills/skills/from-issue/delegated-owner.md"
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
ACQUIRE_DISPATCHER = FROM_ISSUE_DIR / "acquire-dispatcher.md"
ACQUIRE_DIRECT = FROM_ISSUE_DIR / "acquire-direct.md"
ACQUIRE_INTERACTIVE = FROM_ISSUE_DIR / "acquire-interactive.md"
ACQUIRE_DURABLE = FROM_ISSUE_DIR / "acquire-durable.md"
RESUME_PACK = FROM_ISSUE_DIR / "resume-pack.md"
SHIP_HANDOFF_DOC = FROM_ISSUE_DIR / "ship-handoff.md"
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

REQUIRED_WATCH = "timeout 300 gh pr checks <pr-num> --required --watch --fail-fast --interval 30"
ALL_CHECKS_WATCH = "timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30"
ADVISORY_CALL = "gh pr checks <pr-num> --json name,bucket"

SKILL_ROOTS = (
    REPO_ROOT / "home/common/agent-skills/skills",
    REPO_ROOT / "home/common/claude-code/skills",
)

# The producer-report candidate contract, spelled once for the whole corpus so
# design and grill-with-docs cannot drift apart (D1). writing-plans and handoff
# keep only its commands, in SHARED_SKILL_MACHINE_TEXT (#291 D6).
REPORT_CANDIDATE_CLAUSE = (
    "a report candidate outside every working tree — create it with `mktemp "
    '"${TMPDIR:-/tmp}/producer-report-XXXXXX.json"` (the explicit `XXXXXX` '
    "template works on both macOS/BSD and Linux) — invoke `artifact-budget "
    "validate-report --boundary producer --input <report-candidate>`, and "
    "remove that candidate under an unconditional cleanup that runs on every "
    "outcome, including validation rejection and failure: a shell `trap` on "
    "`EXIT HUP INT TERM`, or the equivalent `finally`"
)

LIFECYCLE_DOCS = (*sorted((REPO_ROOT / "home/common/agent-skills/skills/from-issue").glob("*.md")),
                  SHIP_ISSUE, SHIP_ISSUE_REVIEW, SHIP_ISSUE_HUMAN_GATE, ORCHESTRATE)
STDIN_CLAUSE = ("lifecycle call is one command that reads its input from stdin "
                "through a quoted heredoc")
BUILD_ROOT_CLAUSE = ("The builder seals the policy `resolve-project` resolves at "
                     "`--repo-root`, the ledger repository root; when `worktree` already "
                     "exists, it also resolves there and refuses if any sealed policy "
                     "member differs.")
BUILD_REFUSAL_RELAY = ("report the builder's stderr line verbatim: for a resolver refusal "
                       "it carries the resolver's `error.code`, `repair_id` and ordered "
                       "`violations` exactly.")
# The closed capability-gap line ship-issue returns when its Phase-0 probe finds
# no subagent-launch tool, spelled once for the module (per D4).
CAPABILITY_GAP_LINE = "capability_gap: agent_dispatch"
INPUT_FLAG_RE = re.compile(r"(--request-file|--checkpoint-file|--summary-file|--input)\s+(\S+)")
V2_DIRECT_REQUEST_KEYS = {"interface_version", "issue", "attempt_budget_minutes",
    "new_run", "owner_unavailable", "tracker", "worktree", "forge", "delivery_contract",
    "authorization_intents", "authority_observations", "reevaluation_evidence",
    "delivery_observations", "requested_scope", "recovery"}
V2_CONTROL_REQUEST_KEYS = {"interface_version", "max_parallel",
    "attempt_budget_minutes", "human_directed", "issues", "tracker", "owners",
    "worktrees", "forge", "delivery_contracts", "authorization_intents",
    "authority_observations", "reevaluation_evidence", "delivery_observations",
    "requested_scopes", "recoveries"}
V3_CONTROL_REQUEST_KEYS = V2_CONTROL_REQUEST_KEYS | {"host_route"}
CODEX_ORCHESTRATE = REPO_ROOT / "home/common/codex/skills/orchestrate-issues/SKILL.md"
CODEX_MODULE = REPO_ROOT / "home/common/codex/default.nix"
SKILL_TREES = (REPO_ROOT / "home/common/agent-skills/skills",
               REPO_ROOT / "home/common/claude-code/skills",
               REPO_ROOT / "home/common/codex/skills")
NOW_FLAG = re.compile(r"(?<![\w-])--now(?![\w-])")
NOW_KEY = re.compile(r'"now"\s*:')
V2_OWNER_KEYS = {"interface_version", "kind", "ledger_repo_root", "run_id", "issue",
    "attempt", "owner", "action_id", "launch_kind", "worktree", "handoff_path",
    "deadline_at", "custody", "contract", "contract_digest", "pending_stage_ids",
    "requirements", "authority_evaluation", "requested_scope"}
SHIP_HANDOFF_V2_KEYS = {"interface_version", "state", "ledger_repo_root", "run_id",
    "owner", "owner_worktree", "custody", "issue_number", "branch", "worktree_path",
    "spec_artifact", "plan_artifact", "head_sha", "review_state", "acceptance_state", "auto", "report_path",
    "notes", "delivery_contract", "delivery_contract_digest", "authorization_intents",
    "authorization_chain_digest", "authority_observation_ids", "reevaluation_evidence_ids",
    "authority_evaluation_consumption_ids", "pending_stage_ids", "selected_outputs",
    "requested_scope"}
SHIP_SUMMARY_V2_KEYS = {"interface_version", "issue", "state", "custody",
    "historical_owner_result", "delivery_contract_digest", "delivery_observations",
    "authority_observations", "reevaluation_evidence", "detail_state", "report_path",
    "notes"}

WORKER_LINE = ("Lifecycle worker: --repo-root <ledger_repo_root> --run-id <run-id> "
               "--worker-id <worker_id>")
WORKER_EXEC_ARGV = ("launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> "
                    "--worker-id <worker_id> -- <argv>")
WORKER_SCRATCH_ARGV = ("launch-scope scratch --repo-root <ledger_repo_root> --run-id <run-id> "
                       "--worker-id <worker_id>")
PRODUCER_VALIDATION = "artifact-budget validate-report --boundary producer --input -"
WHOLE_FILE_POLICY = "stable-first-fit-whole-file"

# Machine-consumed text each sdd document must carry (#291 D6): helper argv, the
# report fields its validator reads, the review-package packing policy id and
# the payload placeholders the controller fills. No guidance sentence is pinned.
SDD_MACHINE_TEXT = {
    SDD: (
        "validate-report --boundary sdd", 'detail_state: "none"', "report_path: null",
        "validate-detail-input", 'detail_state: "unpublished"',
        "scripts/task-brief PLAN_FILE N", PRODUCER_VALIDATION, WHOLE_FILE_POLICY,
        "member_count", "aggregate_bytes",
        "`<primary-checkout>/.superpowers/sdd/<checkout-bucket>/<plan-basename>/`",
        "workflow-state register-worker --repo-root <ledger_repo_root> --run-id <run-id> "
        "--action-id <action_id>",
        WORKER_LINE,
        "workflow-state release-worker --repo-root <ledger_repo_root> --run-id <run-id> "
        "--worker-id <worker_id> --event returned",
        "workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> "
        "--action-id <action_id>",
        "workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> "
        "--action-id <action_id>",
        WORKER_EXEC_ARGV, WORKER_SCRATCH_ARGV, "launch fence refused:",
    ),
    SDD_DIR / "fix-loop.md": (PRODUCER_VALIDATION,),
    SDD_DIR / "final-review.md": (
        PRODUCER_VALIDATION, WHOLE_FILE_POLICY,
        "review-package PLAN_FILE DELIVERY_BASE DELIVERY_HEAD",
        "verified-tree check --verification <id>",
        "verified-tree record --tree <the checked tree>",
        "launch-commit --repo-root <ledger_repo_root> --run-id <run-id> "
        "--worker-id <worker_id> -- <git commit arguments>",
        "<tracker-cli> issue view <num> --repo <repo_slug> --json body",
    ),
    SDD_DIR / "implementer-prompt.md": (
        "launch-commit --repo-root <ledger_repo_root> --run-id <run-id> "
        "--worker-id <worker_id> -- ",
        WORKER_EXEC_ARGV, WORKER_SCRATCH_ARGV, "launch fence refused:",
    ),
    SDD_DIR / "task-reviewer-prompt.md": (WHOLE_FILE_POLICY,),
    SDD_DIR / "re-review-prompt.md": (WHOLE_FILE_POLICY,),
    SDD_DIR / "conformance-reviewer-prompt.md": (WHOLE_FILE_POLICY, "[ACCEPTANCE_CRITERIA]"),
    SDD_DIR / "correctness-reviewer-prompt.md": (
        WHOLE_FILE_POLICY, "git diff [MERGE_BASE_SHA]..[HEAD_SHA] -- ':(literal)<path>'",
    ),
}

REPORT_CANDIDATE_MKTEMP = 'mktemp "${TMPDIR:-/tmp}/producer-report-XXXXXX.json"'
REPORT_CANDIDATE_VALIDATION = (
    "artifact-budget validate-report --boundary producer --input <report-candidate>")

# Machine-consumed text the remaining in-scope shared skills must carry
# (#291 D6): helper argv, durable paths and the artifact fields a helper reads.
SHARED_SKILL_MACHINE_TEXT = {
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
    ),
}

# Machine-consumed text each orchestrate-issues tree must carry (#291 D6):
# lifecycle helper argv, the control request's host route, the owner-object
# projection the delivery wire validates and the observation values the
# dispatcher sends. No guidance sentence is pinned.
ORCHESTRATE_MACHINE_TEXT = {
    ORCHESTRATE: (
        "workflow-state host-route --route claude-code", '`host_route: "claude-code"`',
        "--boundary workflow-response", "workflow_bootstrap", "workflow-state init-run",
        "workflow-state control", "workflow-state build-delivery", "--request-file -",
        "matching_issue_branch | absent | mismatch", "`worktree_fact`",
        "`recorded_worktree_absent`", "`recorded_worktree_mismatch`",
        "workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> "
        "--action-id <action_id>",
        "workflow-state resume-pack --repo-root <ledger_repo_root> --run-id <run-id> "
        "--action-id <action-id>",
        "launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --sweep",
        "run_in_background=true",
        "rename `id` to `action_id`", "`kind` to `launch_kind`", "`kind: owner`",
        "`interface_version: 2`", "`launch_refused`", "`unavailable`",
    ),
    CODEX_ORCHESTRATE: (
        "workflow-state host-route --route codex", "--boundary workflow-response",
        "/from-issue <n> --auto",
    ),
}

# Machine-consumed text each ship-issue document must carry (#291 D6): helper
# argv, the command constants above, and the closed lines a later agent reads
# back from the PR body or an issue comment. No guidance sentence is pinned.
SHIP_ISSUE_MACHINE_TEXT = {
    SHIP_ISSUE: (
        "--kind selected-output", "--kind current-selection", "checkpoint-delivery",
        "finish --summary-file -", "validate-report --boundary ship-summary",
        "review-range --integration-ref origin/<integration> --head $HEAD_SHA"
        " --final-review-head <final-review head> --max-lines 1000 --max-files 20"
        " --artifact-path <spec_path> --artifact-path <plan_path>",
        "~/.agents/bin/workflow-state check-launch --repo-root <ledger_repo_root> "
        "--run-id <run-id> --action-id <issue:attempt:launch>",
        "launch-commit --repo-root <ledger_repo_root> --run-id <run-id> "
        "--worker-id <worker_id> -- ",
        "workflow-state release-worker --repo-root <ledger_repo_root> --run-id <run-id> "
        "--worker-id <worker_id> --event returned",
        "--parent <worker_id>", "git merge --no-commit --no-ff origin/<integration>",
        "Lifecycle worker:", "--kind scope", "`test_ref`",
        "`tracker_held`", "`comment_url`", "`record_path`",
        WORKER_EXEC_ARGV, WORKER_SCRATCH_ARGV,
        "verified-tree check --verification <id>",
        "verified-tree record --tree <the checked tree>",
        REQUIRED_WATCH, ALL_CHECKS_WATCH, ADVISORY_CALL,
        "Acceptance state: <effective acceptance state>",
        "Acceptance record: <record-path or none>", "Closes #<num>",
        "Held for verification: <PR URL>", "`github:issue:<num>:held`",
        "gh label list --repo <resolved-repository> --search needs-verification --json name",
        "gh label create needs-verification", "gh issue reopen <num>",
        "gh issue edit <num> --add-label needs-verification", "gh issue comment <num>",
        "gh issue close <num>",
    ),
    SHIP_ISSUE_REVIEW: ("validate-detail-input", 'detail_state: "unpublished"'),
    SHIP_ISSUE_CI_MERGE: (
        "--kind current-selection", "--kind sync-selection", "--kind scope", "`test_ref`",
        "launch-commit",
        "gh pr view <pr-num> --json state,headRefOid,mergeable",
        REQUIRED_WATCH, ALL_CHECKS_WATCH, ADVISORY_CALL,
    ),
    SHIP_ISSUE_HUMAN_GATE: (
        "git push -u origin <branch>",
        'gh pr create --repo <resolved-repository> --base <integration-branch> '
        '--head <branch> --title "<title>" --body',
        "Closes #<num>", "gh issue close <num>", "gh issue reopen <num>",
        "gh issue edit <num> --add-label needs-verification",
        "git push origin --delete <branch>", "git ls-remote --heads origin <branch>",
        "git worktree remove <worktree-path>", "git branch -d <branch>",
    ),
}

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

# The orphaned-bucket prune, spelled once (D5, D8).
WORKTREE_BUCKET_LITERAL = "`<primary-checkout>/.superpowers/sdd/wt-<worktree-name>/`"

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
    "grill-with-docs/ADR-FORMAT.md": ("bindings.paths.context",),
    "sdd/conformance-reviewer-prompt.md": ("bindings.workflow.review.code",),
}

RETAINED_SUPPORT_CONTRACTS = {
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
        scoped = "home/common/agent-skills/skills/from-issue/"
        callers = []
        for root in (REPO_ROOT / "home/common/agent-skills/skills",
                     REPO_ROOT / "home/common/claude-code/skills"):
            for path in sorted(root.rglob("*.md")):
                relative = path.relative_to(REPO_ROOT).as_posix()
                if relative.startswith(scoped) and relative != scoped + "SKILL.md":
                    continue
                text = normalized(path.read_text(encoding="utf-8"))
                if "build-delivery" not in text:
                    continue
                callers.append(relative)
                with self.subTest(path=relative):
                    self.assertIn(exception, text)
        self.assertEqual(sorted(callers), [
            "home/common/agent-skills/skills/from-issue/SKILL.md",
            "home/common/agent-skills/skills/ship-issue/SKILL.md",
            "home/common/claude-code/skills/orchestrate-issues/SKILL.md",
        ])

    def test_from_issue_has_no_bindings_or_grounding_reference_file(self):
        directory = REPO_ROOT / "home/common/agent-skills/skills/from-issue"
        for name in ("bindings.md", "grounding.md"):
            with self.subTest(name=name):
                self.assertFalse((directory / name).exists())
                for path in sorted(directory.glob("*.md")):
                    self.assertNotIn(name, path.read_text(encoding="utf-8"), path.name)


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
        cls.research = RESEARCH.read_text(encoding="utf-8")
        cls.ship_issue = SHIP_ISSUE.read_text(encoding="utf-8")
        cls.ship_review = SHIP_ISSUE_REVIEW.read_text(encoding="utf-8")
        cls.ship_human_gate = SHIP_ISSUE_HUMAN_GATE.read_text(encoding="utf-8")
        cls.ship_issue_evals = json.loads(SHIP_ISSUE_EVALS.read_text(encoding="utf-8"))
        cls.writing_plans = WRITING_PLANS.read_text(encoding="utf-8")
        cls.sdd = SDD.read_text(encoding="utf-8")
        cls.phase_5_review_contract = PHASE_5_REVIEW_CONTRACT.read_text(encoding="utf-8")
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

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertNotEqual(next_position, -1, f"missing anchor: {anchor!r}")
            self.assertGreater(next_position, position, f"out-of-order anchor: {anchor!r}")
            position = next_position

    def test_delivery_interface_two_is_one_atomic_production_caller_contract(self):
        documents = {
            str(path.relative_to(REPO_ROOT)): normalized(path.read_text(encoding="utf-8"))
            for path in (SHIP_ISSUE, SHIP_ISSUE_REVIEW, SHIP_ISSUE_HUMAN_GATE,
                         ORCHESTRATE)
        }
        corpus = " ".join(documents.values())
        for phrase in ("workflow-response", "validate before decoding", "custody",
                       "current-launch", "requested_scope", "bind the actual invocation",
                       "ship-checkpoint/v2", "ship-summary/v2", "delivery_remainder"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, corpus)
        self.assertIn("workflow_bootstrap", normalized(self.orchestrate))
        self.assertIn("checkpoint-delivery", corpus)
        self.assertNotIn("infer the next stage from tracker", corpus.lower())
        self.assertNotIn("unfinished delivery as failed", corpus.lower())
        terminal = normalized(self.section(
            FROM_ISSUE.read_text(encoding="utf-8"),
            "## Terminal return procedure", "## Suspension procedure"
        ))
        self.assertIn("--summary-file", terminal)
        self.assertNotIn("--result-file <path>", terminal)

    def test_direct_and_control_requests_are_interface_two(self):
        direct = ACQUIRE_DIRECT.read_text(encoding="utf-8")
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
        for argv in ("workflow-state build-delivery", "--request-file -"):
            self.assertIn(argv, normalized(decide))
        self.assertIn('`host_route: "direct"`',
                      normalized(ACQUIRE_DURABLE.read_text(encoding="utf-8")))

    def test_contract_builders_state_the_resolution_root_and_relay_refusals(self):
        decide = normalized(self.section(self.orchestrate, "## 3. Decide",
                                         "## 4. Execute control actions"))
        self.assertIn(BUILD_ROOT_CLAUSE, decide)
        self.assertIn(BUILD_REFUSAL_RELAY, decide)

    def test_ship_handoff_v2_ship_summary_v2_and_remainder_prompt(self):
        line = next(item for item in self.ship_handoff.splitlines()
                    if item.startswith('{"interface_version":2'))
        self.assertLessEqual(SHIP_HANDOFF_V2_KEYS, set(re.findall(r'"([a-z_]+)":', line)))
        for key in SHIP_SUMMARY_V2_KEYS:
            self.assertIn(f"`{key}`", self.ship_handoff)
        for anchor in ("--kind initial-intent", "--boundary ship-summary",
                       "## Remainder owner prompt"):
            self.assertIn(anchor, self.ship_handoff)

    def test_the_ship_prompt_returns_the_gap_line_and_the_remainder_prompt_never_does(self):
        prompt = normalized(self.ship_handoff.split("## Ship report handling", 1)[0])
        self.assertIn(f"return only `{CAPABILITY_GAP_LINE}`", prompt)
        remainder = self.ship_handoff.split("## Remainder owner prompt", 1)[1]
        self.assertNotIn("capability_gap", remainder)

    def test_capability_gap_line_is_spelled_identically_everywhere(self):
        # One closed line, compared byte for byte and never decoded (per D4).
        pattern = r"capability_gap[^`\n]*"
        self.assertIn(CAPABILITY_GAP_LINE, self.ship_issue)
        self.assertEqual(set(re.findall(pattern, self.ship_issue)), {CAPABILITY_GAP_LINE})
        carriers = set()
        for path in sorted(FROM_ISSUE_DIR.glob("*.md")):
            spellings = set(re.findall(pattern, path.read_text(encoding="utf-8")))
            with self.subTest(document=path.name):
                self.assertLessEqual(spellings, {CAPABILITY_GAP_LINE})
            if spellings:
                carriers.add(path.name)
        self.assertLessEqual({"ship-handoff.md", "delegated-owner.md"}, carriers)

    def test_from_issue_phase_seven_ships_inline_on_the_dispatch_gap(self):
        # The fallback ends in the suspension procedure, never a direct
        # `workflow-state suspend` (the verb stays in that procedure).
        phase_seven = self.section(self.from_issue, "## Phase 7", "## Notes")
        handling = self.section(self.ship_handoff, "## Ship report handling",
                                "## Inline fallback (no ship-issue skill)")
        for text in (phase_seven, handling):
            self.assertNotIn("workflow-state suspend", text)

    def test_suspension_procedure_admits_agent_dispatch(self):
        suspension = normalized(self.section(
            self.from_issue, "## Suspension procedure", "## Phase 0"))
        self.assert_ordered(
            suspension, "`human_gate`", "`external`", "`agent_dispatch`",
            "`deadline`", "(the reaper alone owns `unknown`)",
        )

    def test_sdd_states_the_deadline_suspension_order(self):
        # #281 D5, D9: the one paragraph of `### Lifecycle workers` naming
        # `blocked_on=deadline` releases workers, records progress, fences
        # the launch (final review C-001: `suspend` is not launch-fenced),
        # then suspends with that value, pinned by argv and value, not prose.
        workers = self.section(self.sdd, "### Lifecycle workers",
                               "### 1. Dispatch the implementer")
        paragraphs = [normalized(p) for p in re.split(r"\n\s*\n", workers)
                      if "`blocked_on=deadline`" in p]
        self.assertEqual(len(paragraphs), 1, paragraphs)
        self.assert_ordered(
            paragraphs[0],
            "`deadline_at`",
            "workflow-state release-worker --repo-root <ledger_repo_root> "
            "--run-id <run-id> --worker-id <worker_id>",
            "workflow-state mark-progress --repo-root <ledger_repo_root> "
            "--run-id <run-id> --action-id <action_id>",
            "workflow-state check-launch --repo-root <ledger_repo_root> "
            "--run-id <run-id> --action-id <action_id>",
            "`current: false`",
            "`/from-issue <num> --auto`",
            "`current: true`",
            "`blocked_on=deadline`",
        )

    def test_auto_names_the_dispatch_gap_fallback_and_relays_closed_lines(self):
        # The delegated owner keeps the closed gap line; the earlier controller
        # matches two closed lines byte for byte before it validates (per D5, D10).
        delegated = normalized(DELEGATED_OWNER.read_text(encoding="utf-8"))
        self.assert_ordered(delegated, f"`{CAPABILITY_GAP_LINE}`", "`ship-summary/v2`",
                            "workflow-state finish")
        earlier = normalized(ROLLOVER.read_text(encoding="utf-8")
                             .split("## Earlier controller stop", 1)[1])
        self.assert_ordered(
            earlier,
            "`/from-issue <num> --auto`",
            "`Suspended (blocked_on=<value>). Resume: /from-issue <num> --auto`",
            "artifact-budget validate-report --boundary workflow-response",
        )

    def test_auto_continuation_and_bookkeeper_are_interface_two(self):
        owner = json_block(ROLLOVER.read_text(encoding="utf-8"))["owner"]
        self.assertEqual((set(owner), owner["interface_version"]), (V2_OWNER_KEYS, 2))
        self.assert_ordered(normalized(DELEGATED_OWNER.read_text(encoding="utf-8")),
                            "workflow-state check-launch",
                            "workflow-state finish --summary-file -")

    def test_lifecycle_calls_are_single_stdin_commands_on_interface_two(self):
        for path in LIFECYCLE_DOCS:
            text = normalized(path.read_text(encoding="utf-8"))
            with self.subTest(path=path.name):
                self.assertNotIn('"interface_version": 1', text)
                if path.parent != FROM_ISSUE_DIR:
                    for forbidden in ("version-1", "temporary request file",
                                      "temporary `ship-summary/v2` file"):
                        self.assertNotIn(forbidden, text)
                for flag, value in INPUT_FLAG_RE.findall(text):
                    self.assertEqual(value.strip("`.,;"), "-", flag)
                self.assertLessEqual(text.count("--result-file"), 1)
        for path in (ORCHESTRATE, SHIP_ISSUE):
            with self.subTest(clause=path.name):
                self.assertIn(STDIN_CLAUSE, normalized(path.read_text(encoding="utf-8")))

    def test_codex_orchestrate_stub_relays_the_unsupported_route(self):
        raw = CODEX_ORCHESTRATE.read_text(encoding="utf-8")
        self.assertTrue(raw.startswith("---\nname: orchestrate-issues\n"))
        text = normalized(raw)
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

    def test_dispatcher_calls_no_retired_lifecycle_command(self):
        for retired in ("workflow-state launch", "workflow-state reconcile"):
            self.assertNotIn(retired, self.orchestrate)

    def test_dispatcher_passes_immutable_ledger_root_separately_from_worktree(self):
        # The fields of the owner prompt follow its background Agent call.
        declaration = self.orchestrate.index(
            'Agent(subagent_type="general-purpose", model="opus", effort="high", '
            'run_in_background=true)'
        )
        fresh_prompt = self.orchestrate[declaration:]
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

    def test_dispatcher_executes_the_closed_control_action_set(self):
        for kind in ("spawn", "resume", "retry", "delivery_contract", "wait", "finalize"):
            self.assertIn(f"`{kind}`", self.orchestrate)

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
        # design and grill-with-docs are outside #313's scope and keep their pins.
        for producer in (self.design, self.grill):
            for decision in ("(D5)", "(D11, D14)"):
                self.assertIn(decision, producer)
            self.assert_ordered(normalized(producer),
                                "report candidate outside every working tree",
                                "validate-report --boundary producer",
                                "validated stdout")
            self.assertIn("never inline artifact contents", producer)

    def test_design_and_grill_share_one_report_candidate_clause(self):
        clause = normalized(REPORT_CANDIDATE_CLAUSE)
        for name, text in (
            ("design", self.design),
            ("grill-with-docs", self.grill),
        ):
            with self.subTest(skill=name):
                self.assertIn(clause, normalized(text))

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

    def test_autonomous_reports_and_ship_handoff_are_root_plus_metrics(self):
        for text in (self.auto, self.ship_handoff):
            for field in ("state", "artifact", "kind", "path", "metrics", "budget_status"):
                self.assertIn(field, text)
        self.assertIn("spec_artifact", self.ship_handoff)
        self.assertIn("plan_artifact", self.ship_handoff)
        self.assertIn('"action_id"', self.ship_handoff)
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

    def test_sdd_report_is_exact_and_mechanically_validated(self):
        for field in ("state", "review_state", "conformance_verdict",
                      "correctness_verdict", "verification_state", "base_sha",
                      "head_sha", "acceptance_state", "detail_state", "report_path",
                      "notes"):
            self.assertIn(field, self.sdd)
        self.assertIn("validate-report --boundary sdd", self.sdd)
        for forbidden in ("parked_findings:", "verdict_details:", "open_items:", "summary:"):
            self.assertNotRegex(self.sdd, rf"(?m)^\s*{re.escape(forbidden)}")

    def test_received_reports_cross_the_same_json_wire_seam(self):
        self.assertIn("validate-report --boundary sdd --input -", self.from_issue)

    def test_both_plan_review_routes_revalidate_received_reports_in_the_caller(self):
        for text in (self.from_issue, self.standards_review):
            self.assertIn("validate-report --boundary producer --input -", text)

    def test_standards_review_gate_validates_before_it_checks_the_plan(self):
        gate = self.standards_review.split("## Caller input gate", 1)[1]
        gate = normalized(gate.split("## Dispositioning findings", 1)[0])
        self.assert_ordered(gate, "validate-report --boundary producer --input -",
                            "artifact-budget check --kind implementation-plan --root")

    def test_standards_review_stops_a_blocked_plan_review_capability(self):
        self.assert_ordered(self.standards_review, "capabilities.review.plan", "reason_code",
                            "repair_id")

    def test_durable_review_detail_precedes_every_removable_cleanup(self):
        self.assertIn(".superpowers/issue-delivery/", self.sdd)
        self.assertIn(".superpowers/issue-delivery/", self.ship_review)
        for text in (self.sdd, self.ship_review, self.ship_issue):
            self.assertIn("report_path", text)
            self.assertIn("keep the worktree", text)

    def test_phase_five_remeasures_every_artifact_it_mutates(self):
        remeasure = normalized(self.standards_review.split("## Accepted-edit remeasurement", 1)[1])
        self.assert_ordered(remeasure, "artifact-budget check --kind implementation-plan",
                            "artifact-budget check --kind design-spec", "decompose_required")
        for heading in ("## Accepted-edit remeasurement", "## Caller pre-dispatch boundary"):
            with self.subTest(heading=heading):
                self.assertNotIn(heading, self.phase_5_review_contract)

    def test_fixture_producer_states_supplement_behavioral_cli_cases(self):
        self.assertTrue(all(item["expected"]["producer_state"] == "complete"
                            for item in self.small_budget_fixture["artifacts"]))
        expected = {(item["kind"], item["case"]): item["expected"]["producer_state"]
                    for item in self.oversized_budget_fixture["artifacts"]}
        self.assertEqual(expected[("design-spec", "design-root-plus-one")], "decompose_required")
        self.assertEqual(expected[("implementation-plan", "plan-ninth-member")], "decompose_required")
        self.assertEqual(expected[("handoff", "handoff-root-plus-one")], "stopped")
        self.assertEqual(expected[("review-package", "review-member-plus-one")], "decompose_required")
        for text in (self.sdd,):
            self.assertIn("complete", text)
            self.assertIn("within_budget", text)
            self.assertIn("contract error", text)
        for value in ("complete", "within_budget"):
            self.assertIn(value, self.auto)

    def test_owner_persists_exact_terminal_result_before_return(self):
        owner_return_section = self.section(
            self.from_issue, "## Terminal return procedure", "## Phase 0"
        )
        self.assertIn("workflow-state finish --repo-root <ledger_repo_root> --run-id <run-id> "
                      "--summary-file -", owner_return_section)
        for field in ("custody", "delivery_contract_digest", "historical_owner_result"):
            self.assertIn(f"`{field}`", owner_return_section)

    def test_direct_auto_phase_five_rolls_to_one_fresh_implementation_owner(self):
        rollover = ROLLOVER.read_text(encoding="utf-8")
        transfer = self.section(rollover, "## Mandatory transfer gate", "## Earlier controller stop")
        self.assert_ordered(
            transfer,
            "artifact-budget check --kind design-spec",
            "artifact-budget check --kind implementation-plan",
            "within_budget",
            "workflow-state progress",
            "next_needs_context=false",
            "artifacts_sufficient=true",
            "remainder_self_contained=true",
        )
        continuation = json_block(transfer)
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
        delegated = DELEGATED_OWNER.read_text(encoding="utf-8")
        self.assert_ordered(
            delegated,
            "artifact-budget validate-report --boundary workflow-response --input -",
            "git -C owner.worktree branch --show-current",
            "artifact-budget check",
            "workflow-state progress",
            "launch-scope reap",
            "workflow-state check-launch",
            "workflow-state finish",
        )
        self.assertNotIn("--boundary ship-summary", rollover)

    def test_auto_blocked_on_values_are_the_closed_set(self):
        self.assertEqual(
            sorted(set(re.findall(r"blocked_on[:=] ?(\w+)", normalized(self.auto)))),
            ["human_gate"],
        )

    def test_auto_persists_a_terminal_result_with_finish(self):
        self.assertIn("workflow-state finish", self.auto)

    def test_human_gate_carries_no_affirmative_bypass_instruction(self):
        # AC3 (per D14). The closed negative list under
        # `## Never route around a denial` is the file's ONLY home for these
        # spellings; anywhere else they would read as an instruction. A
        # line-local grep cannot see this, because the list's "must not:"
        # lead-in sits on the introduction line and each banned verb on its
        # own bullet.
        gate = self.ship_human_gate
        split = gate.index("## Never route around a denial")
        outside = gate[:split]
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

    def test_owner_lifecycle_is_optional_for_direct_use_and_covers_all_stops(self):
        identity = self.section(
            self.from_issue, "## Lifecycle identity", "## The flow"
        )
        for field in ("run_id", "attempt", "owner", "action_id", "worktree", "ledger_repo_root"):
            self.assertIn(f"`{field}`", identity)
        self.assertIn("--repo-root <ledger_repo_root>", identity)

    def test_from_issue_revalidates_its_launch_before_the_terminal_finish(self):
        handling = normalized(self.section(
            SHIP_HANDOFF_DOC.read_text(encoding="utf-8"),
            "## Ship report handling", "## Dispatch-gap fallback"))
        self.assert_ordered(
            handling,
            "validate-report --boundary ship-summary --input -",
            "~/.agents/bin/workflow-state check-launch --repo-root <ledger_repo_root> "
            "--run-id <run-id> --action-id <issue:attempt:launch>",
            "/from-issue <num> --auto",
            "workflow-state finish --summary-file -",
        )
        fallback = normalized(self.section(
            SHIP_HANDOFF_DOC.read_text(encoding="utf-8"),
            "## Dispatch-gap fallback", "## Inline fallback (no ship-issue skill)"))
        self.assert_ordered(fallback, "check-launch", "`ship-issue`",
                            f"`{CAPABILITY_GAP_LINE}`", "`agent_dispatch`")

    def test_direct_autonomous_bookkeeper_checks_before_the_terminal_finish(self):
        # The guard lives inside the bookkeeper's own command sequence, not in
        # the parent that dispatches it (per D9).
        delegated = DELEGATED_OWNER.read_text(encoding="utf-8")
        self.assert_ordered(normalized(delegated), "check-launch", "workflow-state finish")
        self.assertIn("/from-issue <num> --auto", delegated)
        self.assertNotIn("workflow-state suspend", delegated)

    def test_from_issue_handoff_resume_is_acquisition_mode_specific(self):
        phase_gate = self.section(
            self.from_issue, "## Dispatch, phase-budget and attempt-budget rules",
            "## Terminal return procedure",
        )
        self.assertNotIn("workflow-state launch", phase_gate)

    def test_from_issue_standalone_modes_use_live_lifecycle_interfaces(self):
        durable = ACQUIRE_DURABLE.read_text(encoding="utf-8")
        self.assert_ordered(
            durable, "workflow-state init-run", "max_parallel: 1",
            "workflow-state control", "first `spawn` envelope",
        )

    def test_direct_auto_acquires_only_through_direct_owner(self):
        identity = self.section(
            self.from_issue, "## Lifecycle identity", "### Resume pack"
        )
        self.assert_ordered(
            identity, "acquire-dispatcher.md", "acquire-direct.md",
            "acquire-durable.md", "acquire-interactive.md",
        )
        direct = ACQUIRE_DIRECT.read_text(encoding="utf-8")
        self.assertIn("workflow-state direct-owner", direct)
        self.assertIn("--repo-root <ledger_repo_root>", direct)
        self.assertIn("--request-file -", direct)
        self.assertNotIn("workflow-state init-run", direct)
        self.assertNotIn("workflow-state control", direct)

    def test_direct_auto_observe_owner_terminal_loop_is_closed(self):
        direct = ACQUIRE_DIRECT.read_text(encoding="utf-8")
        self.assert_ordered(
            direct,
            "kind: observe",
            "tracker",
            "recorded_worktree",
            "candidate_worktree",
            "kind: owner",
            "kind: delivery_remainder",
            "kind: terminal",
        )
        text = normalized(direct)
        for shape in (
            '{"kind":"tracker"}',
            '{"kind":"recorded_worktree", "path":"<absolute-path>"}',
            '{"kind":"candidate_worktree"}',
            '{"kind":"forge_pr", "path":"<issue-branch-prefix>"}',
            '{"kind":"delivery_contract", "subject_id":"<issue>", '
            '"reason_code":"delivery_contract_required", "detail_pointer":null}',
            "`interface_version`, `kind`, `issue`, nullable `run_id`, and `requirements`",
            "`interface_version`, `kind`, `issue`, nullable `run_id`, `source`, `reason`, "
            "`blockers`, nullable `result`, and `reentry`",
        ):
            self.assertIn(shape, text)
        for field in (
            "ledger_repo_root", "run_id", "issue", "attempt", "owner",
            "action_id", "launch_kind", "worktree", "handoff_path",
            "deadline_at",
        ):
            self.assertIn(field, direct)

    def test_adjacent_from_issue_acquisition_modes_remain_unchanged(self):
        for route in (ACQUIRE_DISPATCHER, ACQUIRE_INTERACTIVE, ACQUIRE_DURABLE):
            self.assertNotIn("direct-owner", route.read_text(encoding="utf-8"))

    def test_from_issue_routes_a_deadline_rejected_progress_to_the_suspension_procedure(self):
        self.assert_ordered(
            self.from_issue,
            "cannot record progress at or after attempt deadline",
            "progress requires an active attempt",
            "/from-issue <num> --auto",
        )

    def test_suspension_procedure_pins_verb_line_and_distinction(self):
        suspension = self.section(
            self.from_issue, "## Suspension procedure", "## Phase 0"
        )
        self.assertIn(
            "workflow-state suspend --repo-root <ledger_repo_root> --run-id <run-id> "
            "--issue <n> --attempt <k> --blocked-on <value>",
            suspension,
        )
        self.assertIn(
            "Suspended (blocked_on=<value>). Resume: <reentry from the envelope>",
            suspension,
        )
        self.assert_ordered(
            suspension, "workflow-state suspend", "Suspended (blocked_on=",
        )

    def test_suspension_validates_its_reply_and_replays_a_stall_bound_terminal(self):
        """#191 D6, D8: suspend's reply is validated; a `terminal` reply is a replay."""
        suspension = self.section(
            self.from_issue, "## Suspension procedure", "## Phase 0"
        )
        self.assertIn(
            "workflow-state suspend --repo-root <ledger_repo_root> --run-id <run-id> "
            "--issue <n> --attempt <k> --blocked-on <value> "
            "| artifact-budget validate-report --boundary workflow-response --input -\n",
            suspension,
        )
        self.assert_ordered(
            normalized(suspension), "`kind: terminal`", "`kind: suspended`",
            "Suspended (blocked_on=<value>). Resume: <reentry from the envelope>",
        )

    def test_terminal_replay_relays_reentry(self):
        terminal = self.section(
            self.from_issue,
            "## Terminal return procedure",
            "## Suspension procedure",
        )
        self.assertIn("`reentry`", terminal)

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

    def test_orchestrate_documents_carry_their_machine_text(self):
        for path, items in ORCHESTRATE_MACHINE_TEXT.items():
            text = normalized(path.read_text(encoding="utf-8"))
            for item in items:
                with self.subTest(path=path.name, item=item):
                    self.assertIn(item, text)

    def test_ship_issue_documents_carry_their_machine_text(self):
        for path, items in SHIP_ISSUE_MACHINE_TEXT.items():
            text = normalized(path.read_text(encoding="utf-8"))
            for item in items:
                with self.subTest(path=path.name, item=item):
                    self.assertIn(item, text)

    def test_sdd_documents_carry_their_machine_text(self):
        for path, items in SDD_MACHINE_TEXT.items():
            text = normalized(path.read_text(encoding="utf-8"))
            for item in items:
                with self.subTest(path=path.name, item=item):
                    self.assertIn(item, text)

    def test_phase_five_merge_delta_dispatch_and_handoff_reviewer_count(self):
        self.assertIn("<!-- agent-dispatch: id=ship-issue-merge-delta-review role=reviewer"
                      " model=opus effort=high -->", self.ship_issue)

    def test_phase_six_waits_on_required_checks_and_lists_advisory_states(self):
        # #264 D6-D8: the blocking watch is its own fence; the handoff names it.
        self.assertIn(f"```\n{REQUIRED_WATCH}\n```", self.ship_issue)
        self.assertIn("block on `<tracker-cli> pr checks --required --watch`",
                      normalized(self.ship_handoff))

    def test_ship_issue_eval_restates_the_required_ci_wait(self):
        expected = next(case for case in self.ship_issue_evals["evals"]
                        if case["id"] == 1)["expected_output"]
        for command in (REQUIRED_WATCH, ALL_CHECKS_WATCH, ADVISORY_CALL):
            with self.subTest(command=command):
                self.assertIn(command, expected)

    def test_ship_issue_merge_is_bound_to_the_resolved_repository(self):
        optional_subject = (
            'gh pr merge <pr-num> --repo <resolved-repository> --merge '
            '[--subject "<rendered subject>"] --delete-branch'
        )
        rendered_subject = (
            'gh pr merge <pr-num> --repo <resolved-repository> --merge '
            '--subject "<rendered subject>" --delete-branch'
        )
        # Every merge spelling is one of the two forms the lifecycle guard
        # validates, and the rendered form stands on a line of its own.
        lines = [line.strip() for line in self.ship_issue.splitlines()
                 if "gh pr merge" in line]
        self.assertIn(rendered_subject, lines)
        for line in lines:
            with self.subTest(line=line):
                self.assertTrue(optional_subject in line or rendered_subject in line, line)

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

    def test_ship_issue_phase_five_dispatch_ids_are_unchanged(self):
        for dispatch_id in (
            "ship-issue-full-conformance-review",
            "ship-issue-full-correctness-fallback",
            "ship-issue-scoped-fix-rereview",
        ):
            with self.subTest(dispatch_id=dispatch_id):
                self.assertIn(dispatch_id, self.ship_issue)

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

    def test_ship_issue_prunes_the_removed_worktrees_sdd_bucket(self):
        text = normalized(self.ship_issue)
        self.assertIn(WORKTREE_BUCKET_LITERAL, text)

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


class LaunchFencedWorkerContractsTest(unittest.TestCase):
    """#222: writing dispatches register, commit through launch-commit, release."""

    WORKER_LINE = ("Lifecycle worker: --repo-root <ledger_repo_root> --run-id <run-id> "
                   "--worker-id <worker_id>")
    REGISTER = ("workflow-state register-worker --repo-root <ledger_repo_root> "
                "--run-id <run-id> --action-id <action_id>")
    RELEASE = ("workflow-state release-worker --repo-root <ledger_repo_root> "
               "--run-id <run-id> --worker-id <worker_id> --event returned")

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def read(path):
        return normalized(path.read_text(encoding="utf-8"))

    def test_from_issue_phase_6_hands_sdd_its_lifecycle_identity(self):
        self.assert_ordered(
            self.read(FROM_ISSUE), "## Phase 6 — Execute", "`deadline_at`",
            "workflow-state register-worker", "## Phase 7 — Ship")

    def test_from_issue_registers_writers_and_releases_before_every_exit(self):
        text = self.read(FROM_ISSUE)
        self.assert_ordered(
            text, "## Dispatch, phase-budget and attempt-budget rules",
            "**Writing workers.**", self.REGISTER, self.WORKER_LINE,
            "--event returned", "--event stopped",
            "## Terminal return procedure", "## Suspension procedure", "live workers:")

    def test_auto_subagents_commit_through_launch_commit_and_the_bookkeeper_is_unregistered(self):
        text = self.read(FROM_ISSUE_DIR / "AUTO.md")
        self.assert_ordered(text, "`Lifecycle worker:`", "launch-commit")

    def test_the_ship_prompt_carries_the_worker_line_outside_the_handoff(self):
        self.assert_ordered(
            self.read(FROM_ISSUE_DIR / "ship-handoff.md"), "## Ship-owner subagent prompt",
            self.WORKER_LINE)

    def test_the_remainder_prompt_releases_itself_before_its_finish(self):
        self.assert_ordered(
            self.read(FROM_ISSUE_DIR / "ship-handoff.md"), "## Remainder owner prompt",
            self.WORKER_LINE, self.RELEASE,
            "workflow-state finish --summary-file -")

    def test_claude_md_describes_the_launch_fence(self):
        text = self.read(REPO_ROOT / "CLAUDE.md")
        self.assert_ordered(
            text, "workflow-state check-launch` before any forge write",
            "`workers` list", "workflow-state register-worker", "`launch-commit` command",
            "workflow-state check-worker", "is refused while a registered worker")


class ProgressMarkerContractsTest(unittest.TestCase):
    """#250: the Phase 6 owner records a progress marker after each completed task."""

    MARK = ("workflow-state mark-progress --repo-root <ledger_repo_root> "
            "--run-id <run-id> --action-id <action_id>")
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

    def test_from_issue_phase_6_names_the_marker_on_both_routes(self):
        self.assert_ordered(
            self.read(FROM_ISSUE), "## Phase 6 — Execute", self.MARK, "## Phase 7 — Ship")

    def test_the_bound_is_described_as_progress_not_phase(self):
        for path, retired in ((ORCHESTRATE, "at the same phase too many times"),):
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
            self.read(FROM_ISSUE), "## Lifecycle identity",
            "artifact-budget validate-report --boundary workflow-response", "`resume-pack`",
            "### Resume pack")

    def test_from_issue_owner_verifies_the_pack_and_reads_only_the_phase(self):
        self.assert_ordered(
            self.read(RESUME_PACK), self.PACK, "`check-launch`",
            "`git -C <worktree> rev-parse HEAD` must equal `worktree.head`",
            "`git -C <worktree> status --porcelain` must list exactly "
            "`worktree.dirty_paths` entries")
        self.assertIn("`action_id`", self.read(RESUME_PACK))

    def test_from_issue_direct_reentry_and_delegate_carry_the_pack(self):
        self.assert_ordered(
            self.read(ACQUIRE_DIRECT), "**`kind: owner`**", "`launch_kind` is `resume`",
            self.PACK, "**`kind: delivery_remainder`**")
        self.assert_ordered(
            self.read(FROM_ISSUE), "4. **`delegate`** —", self.PACK,
            "Exception — **ledger-only remainder**")

    def test_auto_rollover_passes_the_pack_beside_the_continuation(self):
        self.assertIn(self.PACK, self.read(ROLLOVER))

    def test_claude_md_describes_the_resume_pack(self):
        self.assert_ordered(
            self.read(REPO_ROOT / "CLAUDE.md"),
            "A relaunched owner's prompt carries a resume pack", self.PACK,
            "`read_handoff`", "`start_phase`", "`current: false` preview",
            "still runs `check-launch`")


class InterimChildResultContractsTest(unittest.TestCase):
    """#261: an owner treats a child's interim return as still running."""

    HEAD = "**Interim child results.**"
    OWNERS = (SDD, SHIP_ISSUE)

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
        canonical = self.paragraph(SDD)
        for path in (SHIP_ISSUE,):
            with self.subTest(path=path.parent.name):
                self.assertEqual(self.paragraph(path), canonical)

    def test_the_paragraph_states_the_rule_in_order(self):
        self.assert_ordered(
            self.paragraph(SDD), self.HEAD,
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
            (SDD, "### 2. Handle the report", "### 3. Review the task"),
            (SHIP_ISSUE, "## Phase 5 — Review the PR", "## Phase 6 — Wait for CI"),
        ):
            with self.subTest(path=path.parent.name):
                self.assert_ordered(self.read(path), start, self.HEAD, end)

    def test_the_suspension_and_auto_pointers_route_to_the_paragraph(self):
        self.assert_ordered(
            self.read(AUTO), "## Phases 2–4 run as subagents", "**Interim child results**",
            "### Design subagent — Phases 2 + 3")


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
        self.assertGreaterEqual(checked, 9, "the link scan found nothing to check")

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
RETRO_FILES = ("SKILL.md", "LICENSE", "agents/openai.yaml")


class RetroSkillContractsTest(unittest.TestCase):
    """The vendored, user-invoked retrospective skill."""

    @classmethod
    def setUpClass(cls):
        cls.skill = (RETRO_DIR / "SKILL.md").read_text(encoding="utf-8")
        cls.notice = (RETRO_DIR / "LICENSE").read_text(encoding="utf-8")
        cls.manifest = (RETRO_DIR / "agents/openai.yaml").read_text(encoding="utf-8")

    def test_structure_and_explicit_only_metadata(self):
        self.assertEqual(sorted(str(p.relative_to(RETRO_DIR)) for p in RETRO_DIR.rglob("*") if p.is_file()), sorted(RETRO_FILES))
        frontmatter = skill_frontmatter(self.skill)
        self.assertEqual(frontmatter.get("name"), "retro")
        self.assertEqual(frontmatter.get("disable-model-invocation"), "true")
        self.assertIn("allow_implicit_invocation: false", self.manifest)
        self.assertNotIn("Agent(", self.skill)

    def test_license_records_provenance_and_the_upstream_notice(self):
        for fragment in (CODEBASE_DESIGN_UPSTREAM, "skills/engineering/retro/", RETRO_REVISION, "Copyright (c) 2026 Matt Pocock", "no automatic synchronisation"):
            self.assertIn(fragment, self.notice)
        self.assertIn(MIT_NOTICE.strip(), self.notice)
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
        frontmatter = skill_frontmatter(self.skill)
        self.assertEqual(set(frontmatter), {"name", "description", "disable-model-invocation"})
        self.assertEqual(frontmatter["name"], IMPROVE_DIR.name)
        self.assertTrue(frontmatter["description"].strip())
        self.assertEqual(frontmatter["disable-model-invocation"], "true")
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

    def test_both_handoff_templates_carry_acceptance_state(self):
        raw = (FROM_ISSUE_DIR / "ship-handoff.md").read_text(encoding="utf-8")
        templates = [line for line in raw.splitlines()
                     if line.startswith('{"interface_version":2')
                     or line.startswith('{"state":"complete"')]
        self.assertEqual(len(templates), 2)
        for line in templates:
            with self.subTest(template=line[:30]):
                self.assertIn('"review_state":"clean|residuals",'
                              '"acceptance_state":"met|unmet|human_pending|not_applicable",',
                              line)


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


class AcceptanceMapContractsTest(unittest.TestCase):
    """#274 AC2: plans carry an Acceptance map and plan review blocks a gap (D2-D5)."""

    WRITING_PLANS = REPO_ROOT / "home/common/agent-skills/skills/writing-plans/SKILL.md"
    REVIEW_CONTRACT = (
        REPO_ROOT / "home/common/agent-skills/skills/from-issue/REVIEW-CONTRACT.md")

    @classmethod
    def setUpClass(cls):
        cls.plans = cls.WRITING_PLANS.read_text(encoding="utf-8")
        cls.review = cls.REVIEW_CONTRACT.read_text(encoding="utf-8")

    @staticmethod
    def section(text, heading):
        start = text.index("\n" + heading + "\n") + 1
        end = text.find("\n## ", start + len(heading))
        return text[start:] if end < 0 else text[start:end]

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            position = text.find(anchor, position + 1)
            self.assertGreaterEqual(position, 0, anchor)

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

    def test_review_contract_blocks_a_missing_or_duplicated_row(self):
        self.assert_ordered(
            self.review, "## Reviewer instructions\n", "## Acceptance map check\n",
            "## Common-miss checklist\n", "## Output\n")
        check = normalized(self.section(self.review, "## Acceptance map check"))
        for kind in ("`code`", "`evidence`", "`human`"):
            with self.subTest(kind=kind):
                self.assertIn(kind, check)


class AcceptanceMapEvalGradingTest(unittest.TestCase):
    """#274 AC3: fixture 001 is tagged and both evals grade its map (D6, D7, D10)."""

    ASSERT_LIB = REPO_ROOT / "home/common/agent-skills/evals/assert-lib.sh"
    FIXTURE = (REPO_ROOT
               / "home/common/agent-skills/evals/fixture-repo/issues/001-well-specified.md")
    EVALS = (
        REPO_ROOT / "home/common/agent-skills/skills/from-issue/evals/evals.json",
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
        # $REPO and runs each shell as `cd $REPO && bash -c "source lib; …"`;
        # from-issue's plan lands in the worktree at the same relative suffix.
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
                    owner = (worktree if path.parent.parent.name == "from-issue" else repo)
                    (owner / ".agents/artifacts/plans").mkdir(parents=True)
                    (owner / ".agents/artifacts/plans/plan.md").write_text(text, encoding="utf-8")
                    env = dict(os.environ, REPO=str(repo), WT=str(worktree),
                               PLAN_DIR=str(plan_dir))
                    result = subprocess.run(
                        ["bash", "-c", f"source '{self.ASSERT_LIB}'; {shell}"],
                        cwd=repo, env=env, check=False, capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, passes,
                                     result.stdout + result.stderr)


class LaunchScopeWiringContractsTest(unittest.TestCase):
    """#276: owners and writing workers run long commands in a launch scope; owners self-reap."""

    WORKER_LINE = ("Lifecycle worker: --repo-root <ledger_repo_root> --run-id <run-id> "
                   "--worker-id <worker_id>")
    WORKER_EXEC = ("Run each long command, every verification command included, as "
                   "`launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> "
                   "--worker-id <worker_id> -- <argv>`, still in the foreground.")
    OWNER_EXEC = ("run each long command, every verification command included, as "
                  "`launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> "
                  "--action-id <action_id> -- <argv>`, still in the foreground")
    WORKER_SCRATCH = ("Create every scratch directory or scratch worktree under the path that "
                      "`launch-scope scratch --repo-root <ledger_repo_root> --run-id <run-id> "
                      "--worker-id <worker_id>` prints.")
    OWNER_SCRATCH = ("Create every scratch directory or scratch worktree under the path that "
                     "`launch-scope scratch --repo-root <ledger_repo_root> --run-id <run-id> "
                     "--action-id <action_id>` prints.")
    REAP = ("launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> "
            "--action-id <action_id>")

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def read(path):
        return normalized(path.read_text(encoding="utf-8"))

    def test_the_owner_runs_long_commands_through_exec(self):
        self.assert_ordered(self.read(FROM_ISSUE), "## Lifecycle identity", self.OWNER_EXEC,
                            self.OWNER_SCRATCH, "### Resume pack")

    def test_the_worker_sentence_follows_every_composed_worker_line(self):
        self.assert_ordered(self.read(FROM_ISSUE), "**Writing workers.**", self.WORKER_LINE,
                            self.WORKER_EXEC, self.WORKER_SCRATCH, "launch-commit",
                            "**Self-reap.**")
        handoff = self.read(FROM_ISSUE_DIR / "ship-handoff.md")
        self.assert_ordered(handoff, "## Ship-owner subagent prompt", self.WORKER_LINE,
                            self.WORKER_EXEC, self.WORKER_SCRATCH, "Your task:")
        self.assert_ordered(handoff, "## Remainder owner prompt", self.WORKER_LINE,
                            self.WORKER_EXEC, self.WORKER_SCRATCH, "Your task:")
        self.assert_ordered(self.read(AUTO), "`Lifecycle worker:`", "launch-commit")

    def test_every_owner_exit_reaps_between_release_and_write(self):
        text = self.read(FROM_ISSUE)
        self.assert_ordered(
            text, "**Self-reap.**", self.REAP, self.REAP, "--handoff-path",
            "## Terminal return procedure", self.REAP, "workflow-state finish --repo-root",
            "## Suspension procedure", self.REAP, "workflow-state suspend --repo-root")

    def test_the_bookkeeper_route_reaps_before_dispatch(self):
        self.assert_ordered(self.read(DELEGATED_OWNER), self.REAP,
                            "workflow-state check-launch", "workflow-state finish")

    def test_the_leaf_clauses_do_not_name_launch_scope(self):
        text = self.read(FROM_ISSUE)
        start = text.index("**Leaf-agent clauses.**")
        self.assertNotIn("launch-scope", text[start:text.index("**Writing workers.**", start)])


class LaunchScopeSweepContractsTest(unittest.TestCase):
    """#276: the stop pass ends with one sweep of the run's non-current launches."""

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    def test_claude_md_describes_launch_scope(self):
        self.assert_ordered(
            normalized((REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")),
            "**Agent helper package.**", "`launch-scope` (#276)",
            "AGENT_LAUNCH_SCOPE=<repo-scope>/<run-id>/<action-id>/<nonce>",
            "`launch-scope reap --action-id`", "`reap --sweep`",
            "agent-launch/<run-id>/<action-id>/", "`launch-scope scratch` (#277)",
            "`scratch.json`", "`unattributed_worktrees`")


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


if __name__ == "__main__":
    unittest.main()
