from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).parents[4]
SCRIPT = REPO_ROOT / "home/common/agent-skills/scripts/agent-model-matrix.py"
MATRIX = REPO_ROOT / "home/common/agent-skills/model-matrix.json"
AGENTS = REPO_ROOT / "home/common/claude-code/agents"

EXPECTED_TIERS = {
    "issue-owner": ("opus", "high"),
    "ship-owner": ("opus", "high"),
    "implementer": ("opus", "high"),
    "reviewer": ("opus", "high"),
    "conformance-reviewer": ("sonnet", "high"),
    "reviewer-lite": ("sonnet", "medium"),
    "mechanic": ("sonnet", "high"),
    "bookkeeper": ("haiku", "low"),
    "explorer": ("haiku", "medium"),
    "researcher": ("sonnet", "medium"),
    "codex-transport": ("sonnet", "medium"),
}

EXPECTED_SUBAGENT_TYPES = {
    "issue-owner": {"general-purpose"},
    "ship-owner": {"general-purpose"},
    "implementer": {"implementer"},
    "reviewer": {"reviewer"},
    "conformance-reviewer": {"reviewer"},
    "reviewer-lite": {"reviewer-lite"},
    "mechanic": {"mechanic"},
    "bookkeeper": {"mechanic"},
    "explorer": {"Explore"},
    "researcher": {"general-purpose"},
    "codex-transport": {"codex:rescue", "codex:codex-reviewer"},
}

EXPECTED_OWNER_SITES = {
    "orchestration-issue-owner": (
        "home/common/claude-code/skills/orchestrate-issues/SKILL.md",
        "issue-owner",
        "opus",
        "high",
    ),
    "from-issue-phase-delegate": (
        "home/common/agent-skills/skills/from-issue/SKILL.md",
        "issue-owner",
        "opus",
        "high",
    ),
    "from-issue-design-grill": (
        "home/common/agent-skills/skills/from-issue/AUTO.md",
        "issue-owner",
        "opus",
        "high",
    ),
    "from-issue-planning": (
        "home/common/agent-skills/skills/from-issue/AUTO.md",
        "issue-owner",
        "opus",
        "high",
    ),
    "from-issue-plan-review": (
        "home/common/agent-skills/skills/from-issue/SKILL.md",
        "reviewer",
        "opus",
        "high",
    ),
    "from-issue-mechanical-implementation": (
        "home/common/agent-skills/skills/from-issue/SKILL.md",
        "mechanic",
        "sonnet",
        "high",
    ),
    "from-issue-ledger-remainder": (
        "home/common/agent-skills/skills/from-issue/SKILL.md",
        "bookkeeper",
        "haiku",
        "low",
    ),
    "from-issue-mechanical-review": (
        "home/common/agent-skills/skills/from-issue/SKILL.md",
        "reviewer",
        "opus",
        "high",
    ),
    "from-issue-ship-owner": (
        "home/common/agent-skills/skills/from-issue/SKILL.md",
        "ship-owner",
        "opus",
        "high",
    ),
    "from-issue-inline-ship-review": (
        "home/common/agent-skills/skills/from-issue/SKILL.md",
        "reviewer",
        "opus",
        "high",
    ),
    "design-bounded-fact-lookup": (
        "home/common/agent-skills/skills/design/SKILL.md",
        "explorer",
        "haiku",
        "medium",
    ),
    "grill-bounded-fact-lookup": (
        "home/common/agent-skills/skills/grill-with-docs/SKILL.md",
        "explorer",
        "haiku",
        "medium",
    ),
    "planning-bounded-fact-lookup": (
        "home/common/agent-skills/skills/writing-plans/SKILL.md",
        "explorer",
        "haiku",
        "medium",
    ),
    "doc-grounded-bounded-code-lookup": (
        "home/common/agent-skills/skills/doc-grounded-questions/SKILL.md",
        "explorer",
        "haiku",
        "medium",
    ),
    "research-background-researcher": (
        "home/common/agent-skills/skills/research/SKILL.md",
        "researcher",
        "sonnet",
        "medium",
    ),
}

EXPECTED_SDD_SITES = {
    "sdd-mechanic-implementation": (
        "home/common/agent-skills/skills/sdd/implementer-prompt.md",
        "mechanic",
        "sonnet",
        "high",
        [],
    ),
    "sdd-lane-task-verification": (
        "home/common/agent-skills/skills/sdd/SKILL.md",
        "reviewer-lite",
        "sonnet",
        "medium",
        ["risk-lane-mechanical-or-low", "bounded-task-diff"],
    ),
    "sdd-nonmechanical-implementation": (
        "home/common/agent-skills/skills/sdd/implementer-prompt.md",
        "implementer",
        "opus",
        "high",
        [],
    ),
    "sdd-first-pass-task-review": (
        "home/common/agent-skills/skills/sdd/task-reviewer-prompt.md",
        "reviewer",
        "opus",
        "high",
        [],
    ),
    "sdd-scoped-task-rereview": (
        "home/common/agent-skills/skills/sdd/re-review-prompt.md",
        "reviewer-lite",
        "sonnet",
        "medium",
        ["named-prior-findings", "bounded-fix-diff"],
    ),
    "sdd-codex-rescue-transport": (
        "home/common/agent-skills/skills/sdd/fix-loop.md",
        "codex-transport",
        "sonnet",
        "medium",
        [],
    ),
    "sdd-post-rescue-implementation": (
        "home/common/agent-skills/skills/sdd/fix-loop.md",
        "implementer",
        "opus",
        "high",
        [],
    ),
    "sdd-rescue-fallback-implementation": (
        "home/common/agent-skills/skills/sdd/fix-loop.md",
        "implementer",
        "opus",
        "high",
        [],
    ),
    "sdd-round-five-implementation": (
        "home/common/agent-skills/skills/sdd/fix-loop.md",
        "implementer",
        "opus",
        "high",
        [],
    ),
    "sdd-task-rereview-escalation": (
        "home/common/agent-skills/skills/sdd/fix-loop.md",
        "reviewer",
        "opus",
        "high",
        [],
    ),
    "sdd-final-rereview-escalation": (
        "home/common/agent-skills/skills/sdd/final-review.md",
        "reviewer",
        "opus",
        "high",
        [],
    ),
    "sdd-final-conformance-review": (
        "home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md",
        "conformance-reviewer",
        "sonnet",
        "high",
        [],
    ),
    "sdd-final-correctness-review": (
        "home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md",
        "reviewer",
        "opus",
        "high",
        [],
    ),
    "sdd-final-review-fixer": (
        "home/common/agent-skills/skills/sdd/final-review.md",
        "implementer",
        "opus",
        "high",
        [],
    ),
    "sdd-final-conformance-rereview": (
        "home/common/agent-skills/skills/sdd/final-review.md",
        "reviewer-lite",
        "sonnet",
        "medium",
        ["named-prior-findings", "bounded-fix-diff"],
    ),
    "sdd-final-correctness-rereview": (
        "home/common/agent-skills/skills/sdd/final-review.md",
        "reviewer-lite",
        "sonnet",
        "medium",
        ["named-prior-findings", "bounded-fix-diff"],
    ),
}

EXPECTED_SHIPPING_SITES = {
    "ship-release-owner": (
        "home/common/agent-skills/skills/ship-release/SKILL.md",
        "ship-owner",
        "opus",
        "high",
        [],
    ),
    "ship-issue-merge-delta-review": (
        "home/common/agent-skills/skills/ship-issue/SKILL.md",
        "reviewer",
        "opus",
        "high",
        [],
    ),
    "ship-issue-full-conformance-review": (
        "home/common/agent-skills/skills/ship-issue/SKILL.md",
        "reviewer",
        "opus",
        "high",
        [],
    ),
    "ship-issue-full-correctness-fallback": (
        "home/common/agent-skills/skills/ship-issue/SKILL.md",
        "reviewer",
        "opus",
        "high",
        [],
    ),
    "ship-issue-scoped-fix-rereview": (
        "home/common/agent-skills/skills/ship-issue/SKILL.md",
        "reviewer-lite",
        "sonnet",
        "medium",
        ["named-prior-findings", "bounded-fix-diff"],
    ),
    "codex-review-transport": (
        "home/common/claude-code/skills/codex-collaboration/SKILL.md",
        "codex-transport",
        "sonnet",
        "medium",
        [],
    ),
    "codex-failure-fallback-review": (
        "home/common/claude-code/skills/codex-collaboration/SKILL.md",
        "reviewer",
        "opus",
        "high",
        [],
    ),
}


def load_module():
    spec = importlib.util.spec_from_file_location("agent_model_matrix", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        return {}
    result = {}
    for line in lines[1:]:
        if line == "---":
            return result
        key, separator, value = line.partition(":")
        if separator:
            result[key.strip()] = value.strip()
    return {}


def write_fixture(root: Path, data: dict) -> None:
    matrix_path = root / "home/common/agent-skills/model-matrix.json"
    matrix_path.parent.mkdir(parents=True)
    matrix_path.write_text(json.dumps(data), encoding="utf-8")
    agents = root / "home/common/claude-code/agents"
    agents.mkdir(parents=True)
    for role in ("implementer", "mechanic", "reviewer", "reviewer-lite"):
        model, effort = EXPECTED_TIERS[role]
        (agents / f"{role}.md").write_text(
            f"---\nname: {role}\nmodel: {model}\neffort: {effort}\n---\n",
            encoding="utf-8",
        )


class AgentModelMatrixTest(unittest.TestCase):
    def test_executable_subagent_type_mapping_is_exhaustive(self):
        module = load_module()
        self.assertEqual(module.ALLOWED_SUBAGENT_TYPES, EXPECTED_SUBAGENT_TYPES)
        self.assertEqual(set(module.ALLOWED_SUBAGENT_TYPES), set(EXPECTED_TIERS))

    def test_matrix_declares_the_exact_closed_role_tiers(self):
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"roles", "dispatch_sites", "scenarios"})
        self.assertEqual(set(data["roles"]), set(EXPECTED_TIERS))
        for role, expected in EXPECTED_TIERS.items():
            spec = data["roles"][role]
            self.assertEqual((spec["model"], spec["effort"]), expected)
            self.assertEqual(
                set(spec), {"model", "effort", "eligible", "prohibited"}
            )
            self.assertIsInstance(spec["eligible"], list)
            self.assertIsInstance(spec["prohibited"], list)

    def test_researcher_contract_is_one_bounded_cited_artifact(self):
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        researcher = data["roles"]["researcher"]
        self.assertEqual(
            researcher["eligible"],
            ["bounded primary-source synthesis with exactly one cited artifact"],
        )
        self.assertIn("read-only fact lookup", researcher["prohibited"])
        self.assertIn("more than one artifact", researcher["prohibited"])
        self.assertIn("uncited artifact", researcher["prohibited"])

    def test_from_issue_trace_includes_bounded_researcher(self):
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        events = {
            event["dispatch"]: event for event in data["scenarios"]["from-issue"]
        }
        event = events["research-background-researcher"]
        self.assertEqual(
            (event["role"], event["model"], event["effort"]),
            ("researcher", "sonnet", "medium"),
        )

    def test_every_custom_agent_explicitly_matches_its_matrix_role(self):
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        files = sorted(AGENTS.glob("*.md"))
        self.assertEqual(
            [path.name for path in files],
            ["implementer.md", "mechanic.md", "reviewer-lite.md", "reviewer.md"],
        )
        for path in files:
            metadata = frontmatter(path)
            self.assertIn("model", metadata, path)
            self.assertIn("effort", metadata, path)
            role = metadata["name"]
            self.assertIn(role, data["roles"], path)
            self.assertEqual(metadata["model"], data["roles"][role]["model"], path)
            self.assertEqual(metadata["effort"], data["roles"][role]["effort"], path)

    def test_repository_contract_validates(self):
        module = load_module()
        self.assertEqual(module.validate(REPO_ROOT), [])

    def test_owner_design_and_research_dispatches_select_exact_tiers(self):
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        sites = {site["id"]: site for site in data["dispatch_sites"]}
        self.assertEqual(set(EXPECTED_OWNER_SITES) - set(sites), set())
        for site_id, (path, role, model, effort) in EXPECTED_OWNER_SITES.items():
            site = sites[site_id]
            self.assertEqual(site["path"], path, site_id)
            self.assertEqual(
                (site["role"], site["model"], site["effort"]),
                (role, model, effort),
                site_id,
            )
            self.assertEqual(
                site["marker"],
                f"<!-- agent-dispatch: id={site_id} role={role} "
                f"model={model} effort={effort} -->",
            )
            self.assertIn("Agent(", site["call"], site_id)

    def test_cheap_tier_escalation_names_opus_role_and_durable_destination(self):
        for relative in (
            "home/common/agent-skills/skills/design/SKILL.md",
            "home/common/agent-skills/skills/grill-with-docs/SKILL.md",
            "home/common/agent-skills/skills/writing-plans/SKILL.md",
            "home/common/agent-skills/skills/doc-grounded-questions/SKILL.md",
            "home/common/agent-skills/skills/research/SKILL.md",
        ):
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("issue-owner` on Opus/high", text, relative)
            self.assertRegex(text, r"ledger|fixed-schema report", relative)

    def test_sdd_dispatches_select_exact_tiers(self):
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        sites = {site["id"]: site for site in data["dispatch_sites"]}
        self.assertEqual(set(EXPECTED_SDD_SITES) - set(sites), set())
        for site_id, (path, role, model, effort, requires) in EXPECTED_SDD_SITES.items():
            site = sites[site_id]
            self.assertEqual(site["path"], path, site_id)
            self.assertEqual(
                (site["role"], site["model"], site["effort"], site["requires"]),
                (role, model, effort, requires),
                site_id,
            )
            self.assertEqual(
                site["marker"],
                f"<!-- agent-dispatch: id={site_id} role={role} "
                f"model={model} effort={effort} -->",
            )

    def test_shipping_and_codex_dispatches_select_exact_tiers(self):
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        sites = {site["id"]: site for site in data["dispatch_sites"]}
        self.assertEqual(set(EXPECTED_SHIPPING_SITES) - set(sites), set())
        for site_id, (path, role, model, effort, requires) in EXPECTED_SHIPPING_SITES.items():
            site = sites[site_id]
            self.assertEqual(site["path"], path, site_id)
            self.assertEqual(
                (site["role"], site["model"], site["effort"], site["requires"]),
                (role, model, effort, requires),
                site_id,
            )
            self.assertEqual(
                site["marker"],
                f"<!-- agent-dispatch: id={site_id} role={role} "
                f"model={model} effort={effort} -->",
            )
            self.assertIn("Agent(", site["call"], site_id)

    def test_representative_trace_covers_every_workflow_with_safe_rereviews(self):
        module = load_module()
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        events = data["scenarios"]["representative"]
        trace = module.trace(REPO_ROOT, "representative")

        self.assertEqual(
            {event["workflow"] for event in trace},
            {"orchestration", "from-issue", "sdd", "shipping"},
        )
        self.assertTrue(
            all(
                set(event) == {"workflow", "dispatch", "role", "model", "effort"}
                for event in trace
            )
        )
        self.assertTrue(
            all(
                event["model"] not in (None, "inherit")
                and event["effort"] not in (None, "inherit")
                for event in trace
            )
        )
        for index, event in enumerate(events):
            if event["role"] != "reviewer-lite":
                continue
            self.assertEqual(
                event["requires"],
                ["named-prior-findings", "bounded-fix-diff"],
            )
            self.assertTrue(
                any(
                    prior["workflow"] == event["workflow"]
                    and prior["role"] == "reviewer"
                    and "review" in prior["dispatch"]
                    for prior in events[:index]
                ),
                event,
            )

    def test_shipping_traces_use_the_ship_issue_owner_before_ship_issue_reviews(self):
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        for scenario in ("shipping", "representative"):
            events = [
                event
                for event in data["scenarios"][scenario]
                if event["workflow"] == "shipping"
            ]
            dispatches = [event["dispatch"] for event in events]
            self.assertIn("from-issue-ship-owner", dispatches, scenario)
            self.assertNotIn("ship-release-owner", dispatches, scenario)
            owner_index = dispatches.index("from-issue-ship-owner")
            review_indices = [
                index
                for index, dispatch in enumerate(dispatches)
                if dispatch.startswith("ship-issue-") and "review" in dispatch
            ]
            self.assertTrue(review_indices, scenario)
            self.assertTrue(
                all(owner_index < review_index for review_index in review_indices),
                scenario,
            )

    def test_reviewer_lite_cannot_be_a_first_pass_reviewer(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = json.loads(MATRIX.read_text(encoding="utf-8"))
            marker = (
                "<!-- agent-dispatch: id=first-pass role=reviewer-lite "
                "model=sonnet effort=medium -->"
            )
            call = (
                'Agent(subagent_type="reviewer-lite", model="sonnet", '
                'effort="medium") performs a first-pass review.'
            )
            manifest = root / "workflow.md"
            manifest.write_text(f"{marker}\n{call}\n", encoding="utf-8")
            data["dispatch_sites"] = [
                {
                    "id": "first-pass",
                    "path": "workflow.md",
                    "marker": marker,
                    "call": call,
                    "role": "reviewer-lite",
                    "model": "sonnet",
                    "effort": "medium",
                    "requires": [],
                }
            ]
            write_fixture(root, data)

            errors = module.validate(root)

        self.assertTrue(
            any("reviewer-lite requires" in error for error in errors), errors
        )

    def test_reviewer_lite_lane_verification_is_legal_without_prior_full_review(self):
        module = load_module()
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        sites = {site["id"]: site for site in data["dispatch_sites"]}
        lane_site = sites["sdd-lane-task-verification"]
        self.assertEqual(
            lane_site["requires"],
            ["risk-lane-mechanical-or-low", "bounded-task-diff"],
        )
        sdd_events = data["scenarios"]["sdd"]
        lane_index = next(
            index
            for index, event in enumerate(sdd_events)
            if event["dispatch"] == "sdd-lane-task-verification"
        )
        self.assertFalse(
            any(
                event["role"] == "reviewer"
                for event in sdd_events[:lane_index]
            ),
            "lane verification must be legal before any full review dispatch",
        )
        self.assertEqual(module.validate(REPO_ROOT), [])

    def test_reviewer_lite_partial_lane_requirements_fail(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = json.loads(MATRIX.read_text(encoding="utf-8"))
            marker = (
                "<!-- agent-dispatch: id=partial-lane role=reviewer-lite "
                "model=sonnet effort=medium -->"
            )
            call = (
                'Agent(subagent_type="reviewer-lite", model="sonnet", '
                'effort="medium") verifies a lane diff without declaring the lane.'
            )
            manifest = root / "workflow.md"
            manifest.write_text(f"{marker}\n{call}\n", encoding="utf-8")
            data["dispatch_sites"] = [
                {
                    "id": "partial-lane",
                    "path": "workflow.md",
                    "marker": marker,
                    "call": call,
                    "role": "reviewer-lite",
                    "model": "sonnet",
                    "effort": "medium",
                    "requires": ["bounded-task-diff"],
                }
            ]
            write_fixture(root, data)

            errors = module.validate(root)

        self.assertTrue(
            any("reviewer-lite requires" in error for error in errors), errors
        )

    def test_unmarked_agent_call_in_manifested_skill_fails(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = json.loads(MATRIX.read_text(encoding="utf-8"))
            marker = (
                "<!-- agent-dispatch: id=marked role=reviewer "
                "model=opus effort=high -->"
            )
            call = 'Agent(subagent_type="reviewer", model="opus", effort="high")'
            manifest = root / "workflow.md"
            manifest.write_text(
                f"{marker}\n{call}\n"
                'Agent(subagent_type="general-purpose")\n',
                encoding="utf-8",
            )
            data["dispatch_sites"] = [
                {
                    "id": "marked",
                    "path": "workflow.md",
                    "marker": marker,
                    "call": call,
                    "role": "reviewer",
                    "model": "opus",
                    "effort": "high",
                    "requires": [],
                }
            ]
            write_fixture(root, data)

            errors = module.validate(root)

        self.assertTrue(
            any("unmarked Agent call" in error for error in errors), errors
        )

    def test_cli_reports_missing_manifest_path_and_unknown_role(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = json.loads(MATRIX.read_text(encoding="utf-8"))
            data["dispatch_sites"] = [
                {
                    "id": "missing-site",
                    "path": "missing/SKILL.md",
                    "marker": "agent-dispatch:missing-site",
                    "call": 'Agent(subagent_type="general-purpose")',
                    "role": "not-a-role",
                    "model": "opus",
                    "effort": "high",
                    "requires": [],
                }
            ]
            write_fixture(root, data)

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "validate", "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing/SKILL.md", result.stderr)
        self.assertIn("unknown role 'not-a-role'", result.stderr)

    def test_omitted_agent_model_fails(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            matrix_path = root / "home/common/agent-skills/model-matrix.json"
            data = json.loads(MATRIX.read_text(encoding="utf-8"))
            write_fixture(root, data)
            agents = root / "home/common/claude-code/agents"
            (agents / "implementer.md").write_text(
                "---\nname: implementer\neffort: high\n---\n", encoding="utf-8"
            )

            errors = module.validate(root)

        self.assertTrue(
            any("implementer.md" in error and "model" in error for error in errors),
            errors,
        )

    def test_malformed_known_role_returns_errors_instead_of_crashing(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = json.loads(MATRIX.read_text(encoding="utf-8"))
            data["roles"]["reviewer"] = "not-an-object"
            write_fixture(root, data)

            errors = module.validate(root)

        self.assertTrue(
            any("matrix.roles.reviewer: must be an object" in error for error in errors),
            errors,
        )

    def test_malformed_reviewer_lite_requires_returns_errors_instead_of_crashing(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = json.loads(MATRIX.read_text(encoding="utf-8"))
            marker = (
                "<!-- agent-dispatch: id=malformed role=reviewer-lite "
                "model=sonnet effort=medium -->"
            )
            call = (
                'Agent(subagent_type="reviewer-lite", model="sonnet", '
                'effort="medium") verifies malformed requirements.'
            )
            manifest = root / "workflow.md"
            manifest.write_text(f"{marker}\n{call}\n", encoding="utf-8")
            data["dispatch_sites"] = [
                {
                    "id": "malformed",
                    "path": "workflow.md",
                    "marker": marker,
                    "call": call,
                    "role": "reviewer-lite",
                    "model": "sonnet",
                    "effort": "medium",
                    "requires": ["named-prior-findings", {"invalid": "object"}],
                }
            ]
            write_fixture(root, data)

            errors = module.validate(root)

        self.assertTrue(
            any(
                "requires: must be an array of non-empty strings" in error
                for error in errors
            ),
            errors,
        )

    def test_duplicate_dispatch_id_marker_mismatch_and_reviewer_lite_misuse_fail(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = json.loads(MATRIX.read_text(encoding="utf-8"))
            manifest = root / "workflow.md"
            manifest.write_text("expected-marker\n", encoding="utf-8")
            data["dispatch_sites"] = [
                {
                    "id": "duplicate",
                    "path": "workflow.md",
                    "marker": "absent-marker",
                    "call": 'Agent(subagent_type="reviewer-lite")',
                    "role": "reviewer-lite",
                    "model": "sonnet",
                    "effort": "medium",
                    "requires": [],
                },
                {
                    "id": "duplicate",
                    "path": "workflow.md",
                    "marker": "expected-marker",
                    "call": 'Agent(subagent_type="reviewer")',
                    "role": "reviewer",
                    "model": "sonnet",
                    "effort": "medium",
                    "requires": [],
                },
            ]
            write_fixture(root, data)

            errors = module.validate(root)

        joined = "\n".join(errors)
        self.assertIn("duplicate id 'duplicate'", joined)
        self.assertIn("absent-marker", joined)
        self.assertIn("reviewer-lite requires", joined)
        self.assertIn("does not match role 'reviewer'", joined)

    def test_marker_and_call_selection_must_match_the_dispatch_row(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = json.loads(MATRIX.read_text(encoding="utf-8"))
            marker = (
                "<!-- agent-dispatch: id=mismatched role=mechanic "
                "model=sonnet effort=medium -->"
            )
            call = (
                'Agent(subagent_type="mechanic", model="sonnet", '
                'effort="medium") performs the review.'
            )
            manifest = root / "workflow.md"
            manifest.write_text(f"{marker}\n{call}\n", encoding="utf-8")
            data["dispatch_sites"] = [
                {
                    "id": "mismatched",
                    "path": "workflow.md",
                    "marker": marker,
                    "call": call,
                    "role": "reviewer",
                    "model": "opus",
                    "effort": "high",
                    "requires": [],
                }
            ]
            write_fixture(root, data)

            errors = module.validate(root)

        joined = "\n".join(errors)
        self.assertIn("marker selection must match dispatch row", joined)
        self.assertIn("call model 'sonnet' must match dispatch row 'opus'", joined)
        self.assertIn("call effort 'medium' must match dispatch row 'high'", joined)

    def test_agent_call_requires_one_known_role_compatible_subagent_type(self):
        module = load_module()
        cases = {
            "missing": (
                'Agent(model="opus", effort="high") performs the review.',
                "call must select exactly one subagent_type",
            ),
            "duplicate": (
                'Agent(subagent_type="reviewer", subagent_type="reviewer", '
                'model="opus", effort="high") performs the review.',
                "call must select exactly one subagent_type",
            ),
            "unknown": (
                'Agent(subagent_type="unregistered", model="opus", '
                'effort="high") performs the review.',
                "unknown call subagent_type 'unregistered'",
            ),
            "same-tier-role-mismatch": (
                'Agent(subagent_type="implementer", model="opus", '
                'effort="high") performs the review.',
                "call subagent_type 'implementer' is not allowed for role 'reviewer'",
            ),
        }
        for name, (call, expected_error) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                data = json.loads(MATRIX.read_text(encoding="utf-8"))
                marker = (
                    "<!-- agent-dispatch: id=typed role=reviewer "
                    "model=opus effort=high -->"
                )
                manifest = root / "workflow.md"
                manifest.write_text(f"{marker}\n{call}\n", encoding="utf-8")
                data["dispatch_sites"] = [
                    {
                        "id": "typed",
                        "path": "workflow.md",
                        "marker": marker,
                        "call": call,
                        "role": "reviewer",
                        "model": "opus",
                        "effort": "high",
                        "requires": [],
                    }
                ]
                write_fixture(root, data)

                errors = module.validate(root)

            self.assertIn(expected_error, "\n".join(errors), name)

    def test_trace_is_deterministic_and_rejects_unknown_scenario(self):
        module = load_module()
        first = module.trace(REPO_ROOT, "sdd")
        second = module.trace(REPO_ROOT, "sdd")
        self.assertEqual(first, second)
        self.assertTrue(first)
        self.assertTrue(
            all(
                set(event)
                == {"workflow", "dispatch", "role", "model", "effort"}
                for event in first
            )
        )
        with self.assertRaises(ValueError):
            module.trace(REPO_ROOT, "does-not-exist")


if __name__ == "__main__":
    unittest.main()
