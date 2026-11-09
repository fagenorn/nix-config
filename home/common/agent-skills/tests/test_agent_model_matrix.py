from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agent_tools import agent_model_matrix


REPO_ROOT = Path(__file__).parents[4]
MATRIX = REPO_ROOT / "home/common/agent-skills/model-matrix.json"
AGENTS = REPO_ROOT / "home/common/claude-code/agents"

# Issue 734: the tool schemas no delivery agent may load or call.
CLOSED_TOOLS = [
    "Artifact", "ArtifactComments", "ArtifactData", "Workflow", "ScheduleWakeup",
    "AskUserQuestion", "SendFeedback", "ReportFindings", "CronCreate", "CronDelete",
    "CronList", "RemoteTrigger", "mcp__claude_ai_Claude_Docs",
]


def tool_list(value):
    return [entry.strip() for entry in value.split(",")]


def body_of(path):
    return path.read_text(encoding="utf-8").split("\n---\n", 1)[1]


EXPECTED_TIERS = {
    "owner": ("opus", "high"),
    "ship-owner": ("opus", "high"),
    "implementer": ("opus", "high"),
    "reviewer": ("opus", "high"),
    "reviewer-lite": ("sonnet", "medium"),
    "explorer": ("sonnet", "medium"),
    "researcher": ("sonnet", "medium"),
    "clerk": ("sonnet", "low"),
    "planner": ("opus", "high"),
}

EXPECTED_SUBAGENT_TYPES = {
    "owner": {"general-purpose"},
    "ship-owner": {"general-purpose"},
    "implementer": {"implementer"},
    "reviewer": {"reviewer"},
    "reviewer-lite": {"reviewer-lite"},
    "explorer": {"Explore"},
    "researcher": {"general-purpose"},
    "clerk": {"clerk"},
    "planner": {"planner"},
}

EXPECTED_OWNER_SITES = {
    "design-bounded-fact-lookup": (
        "home/common/agent-skills/skills/design/SKILL.md",
        "explorer",
        "sonnet",
        "medium",
    ),
    "grill-bounded-fact-lookup": (
        "home/common/agent-skills/skills/grill-with-docs/SKILL.md",
        "explorer",
        "sonnet",
        "medium",
    ),
    "planning-bounded-fact-lookup": (
        "home/common/agent-skills/skills/writing-plans/SKILL.md",
        "explorer",
        "sonnet",
        "medium",
    ),
    "doc-grounded-bounded-code-lookup": (
        "home/common/agent-skills/skills/doc-grounded-questions/SKILL.md",
        "explorer",
        "sonnet",
        "medium",
    ),
    "research-background-researcher": (
        "home/common/agent-skills/skills/research/SKILL.md",
        "researcher",
        "sonnet",
        "medium",
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
}


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
    for role in ("implementer", "reviewer", "reviewer-lite", "clerk", "planner"):
        model, effort = EXPECTED_TIERS[role]
        (agents / f"{role}.md").write_text(
            f"---\nname: {role}\nmodel: {model}\neffort: {effort}\n---\n",
            encoding="utf-8",
        )


class AgentToolSetTest(unittest.TestCase):
    """Issue 734: each program-facing agent type carries an exact, narrow tool set."""

    def test_clerk_runs_on_shell_read_and_skills_only(self):
        path = AGENTS / "clerk.md"
        metadata = frontmatter(path)
        self.assertEqual(set(metadata), {"name", "description", "model", "effort", "tools"})
        self.assertEqual((metadata["name"], metadata["model"], metadata["effort"]),
                         ("clerk", "sonnet", "low"))
        self.assertEqual(tool_list(metadata["tools"]), ["Bash", "Read", "Skill"])
        self.assertEqual(body_of(path).strip(), "")

    def test_planner_reads_writes_plan_files_and_loads_skills(self):
        path = AGENTS / "planner.md"
        metadata = frontmatter(path)
        self.assertEqual(set(metadata), {"name", "description", "model", "effort", "tools"})
        self.assertEqual((metadata["name"], metadata["model"], metadata["effort"]),
                         ("planner", "opus", "high"))
        self.assertEqual(tool_list(metadata["tools"]),
                         ["Read", "Glob", "Grep", "Bash", "Write", "Edit", "Skill"])
        self.assertEqual(body_of(path).strip(), "")

    def test_implementer_blocks_the_closed_tools_and_keeps_its_own(self):
        metadata = frontmatter(AGENTS / "implementer.md")
        self.assertNotIn("tools", metadata)
        blocked = tool_list(metadata["disallowedTools"])
        self.assertEqual(blocked, CLOSED_TOOLS)
        for kept in ("Agent", "SendMessage", "Skill", "Bash", "Read", "Edit", "Write",
                     "Glob", "Grep", "ToolSearch"):
            self.assertNotIn(kept, blocked)

    def test_no_program_agent_type_runs_on_the_default_tool_set(self):
        for name in ("clerk", "planner", "implementer", "reviewer", "reviewer-lite"):
            with self.subTest(agent=name):
                metadata = frontmatter(AGENTS / f"{name}.md")
                self.assertTrue("tools" in metadata or "disallowedTools" in metadata)


class AgentModelMatrixTest(unittest.TestCase):
    def test_no_site_role_or_scenario_serves_a_retired_skill(self):
        matrix = agent_model_matrix.load_matrix(REPO_ROOT)
        retired = ("skills/" + "from-" "issue/", "skills/" + "sdd/", "skills/" + "ship-" "issue/")
        self.assertEqual(
            [s["id"] for s in matrix["dispatch_sites"] if any(r in s["path"] for r in retired)], []
        )
        self.assertEqual(
            set(matrix["roles"]),
            {
                "owner", "ship-owner", "implementer", "reviewer", "reviewer-lite", "explorer",
                "researcher", "clerk", "planner",
            },
        )
        self.assertEqual(
            set(matrix["scenarios"]), {"shipping", "improve-codebase-architecture", "representative"}
        )

    def test_executable_subagent_type_mapping_is_exhaustive(self):
        module = agent_model_matrix
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

    def test_every_custom_agent_explicitly_matches_its_matrix_role(self):
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        files = sorted(AGENTS.glob("*.md"))
        self.assertEqual(
            [path.name for path in files],
            ["clerk.md", "implementer.md", "planner.md", "reviewer-lite.md", "reviewer.md"],
        )
        self.assertEqual(
            agent_model_matrix.CUSTOM_AGENT_ROLES,
            {"implementer", "reviewer", "reviewer-lite", "clerk", "planner"},
        )
        for path in files:
            metadata = frontmatter(path)
            self.assertIn("model", metadata, path)
            self.assertIn("effort", metadata, path)
            role = metadata["name"]
            self.assertIn(role, data["roles"], path)
            self.assertEqual(metadata["model"], data["roles"][role]["model"], path)
            self.assertEqual(metadata["effort"], data["roles"][role]["effort"], path)

    def test_only_the_brief_driven_agents_omit_claude_md(self):
        found = {
            path.stem: frontmatter(path).get("omitClaudeMd")
            for path in sorted(AGENTS.glob("*.md"))
        }
        self.assertEqual(
            found,
            {
                "clerk": None,
                "planner": None,
                "implementer": None,
                "reviewer": None,
                "reviewer-lite": "true",
            },
        )

    def test_repository_contract_validates(self):
        module = agent_model_matrix
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

    def test_shipping_dispatches_select_exact_tiers(self):
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

    def test_representative_trace_covers_every_workflow_family(self):
        module = agent_model_matrix
        trace = module.trace(REPO_ROOT, "representative")

        self.assertEqual(
            {event["workflow"] for event in trace}, module.WORKFLOW_FAMILIES
        )
        self.assertEqual(
            module.WORKFLOW_FAMILIES, {"shipping", "improve-codebase-architecture"}
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

    def test_reviewer_lite_cannot_be_a_first_pass_reviewer(self):
        module = agent_model_matrix
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

    def reviewer_lite_fixture(self, root, requires, dispatch):
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        marker = (
            f"<!-- agent-dispatch: id={dispatch} role=reviewer-lite "
            "model=sonnet effort=medium -->"
        )
        call = (
            'Agent(subagent_type="reviewer-lite", model="sonnet", '
            'effort="medium") verifies a bounded diff.'
        )
        (root / "workflow.md").write_text(f"{marker}\n{call}\n", encoding="utf-8")
        site = {
            "id": dispatch,
            "path": "workflow.md",
            "marker": marker,
            "call": call,
            "role": "reviewer-lite",
            "model": "sonnet",
            "effort": "medium",
            "requires": requires,
        }
        event = {
            "workflow": "shipping",
            "dispatch": dispatch,
            "role": "reviewer-lite",
            "model": "sonnet",
            "effort": "medium",
            "requires": requires,
        }
        data["dispatch_sites"] = [site]
        data["scenarios"] = {
            "shipping": [],
            "improve-codebase-architecture": [],
            "representative": [event],
        }
        write_fixture(root, data)

    def test_reviewer_lite_lane_verification_is_legal_without_prior_full_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.reviewer_lite_fixture(
                root,
                ["risk-lane-mechanical-or-low", "bounded-task-diff"],
                "lane-verification",
            )
            errors = agent_model_matrix.validate(root)
        self.assertEqual(errors, [])

    def test_reviewer_lite_rereview_needs_a_prior_full_review_in_its_workflow(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.reviewer_lite_fixture(
                root,
                ["named-prior-findings", "bounded-fix-diff"],
                "scoped-rereview",
            )
            errors = agent_model_matrix.validate(root)
        self.assertTrue(
            any("reviewer-lite must follow a named first-pass" in e for e in errors),
            errors,
        )

    def test_reviewer_lite_partial_lane_requirements_fail(self):
        module = agent_model_matrix
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
        module = agent_model_matrix
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
                [sys.executable, "-m", "agent_tools.agent_model_matrix", "validate", "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing/SKILL.md", result.stderr)
        self.assertIn("unknown role 'not-a-role'", result.stderr)

    def test_omitted_agent_model_fails(self):
        module = agent_model_matrix
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
        module = agent_model_matrix
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
        module = agent_model_matrix
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
        module = agent_model_matrix
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
        module = agent_model_matrix
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = json.loads(MATRIX.read_text(encoding="utf-8"))
            marker = (
                "<!-- agent-dispatch: id=mismatched role=implementer "
                "model=sonnet effort=medium -->"
            )
            call = (
                'Agent(subagent_type="implementer", model="sonnet", '
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
        module = agent_model_matrix
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
        module = agent_model_matrix
        first = module.trace(REPO_ROOT, "shipping")
        second = module.trace(REPO_ROOT, "shipping")
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

    def test_improve_codebase_architecture_trace_is_standalone(self):
        module = agent_model_matrix
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        expected_site = {
            "id": "improve-architecture-scan-owner",
            "path": "home/common/agent-skills/skills/improve-codebase-architecture/SKILL.md",
            "marker": "<!-- agent-dispatch: id=improve-architecture-scan-owner role=owner model=opus effort=high -->",
            "call": 'Agent(subagent_type="general-purpose", model="opus", effort="high") performs the one read-only architecture scan and returns evidence-backed deepening candidates without writing to the repository.',
            "role": "owner", "model": "opus", "effort": "high", "requires": [],
        }
        expected_event = {
            "workflow": "improve-codebase-architecture",
            "dispatch": "improve-architecture-scan-owner",
            "role": "owner", "model": "opus", "effort": "high", "requires": [],
        }
        self.assertIn("improve-codebase-architecture", module.WORKFLOW_FAMILIES)
        sites = {site["id"]: site for site in data["dispatch_sites"]}
        self.assertEqual(sites["improve-architecture-scan-owner"], expected_site)
        self.assertEqual(data["scenarios"]["improve-codebase-architecture"], [expected_event])
        self.assertEqual(module.trace(REPO_ROOT, "improve-codebase-architecture"), [{key: expected_event[key] for key in ("workflow", "dispatch", "role", "model", "effort")}])
        self.assertEqual({event["workflow"] for event in module.trace(REPO_ROOT, "representative")}, {"shipping", "improve-codebase-architecture"})

    def test_a_duplicate_matrix_key_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "home/common/agent-skills/model-matrix.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"schema_version": 1, "schema_version": 1}', encoding="utf-8")
            errors = agent_model_matrix.validate(root)
        self.assertIn("duplicate JSON key 'schema_version'", "\n".join(errors))


class CodexReviewOnlyMatrixTest(unittest.TestCase):
    """#687 D6: Codex is a reviewer only, so the matrix routes no Codex rescue."""

    RETIRED_SITES = {"sdd-codex-rescue-transport", "sdd-post-rescue-implementation"}

    def test_the_matrix_has_no_codex_role_or_rescue_site(self):
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertNotIn("codex-transport", data["roles"])
        self.assertEqual({site["id"] for site in data["dispatch_sites"]} & self.RETIRED_SITES, set())
        events = [event for events in data["scenarios"].values() for event in events]
        self.assertEqual({event["dispatch"] for event in events} & self.RETIRED_SITES, set())
        self.assertNotIn("codex-transport", agent_model_matrix.EXPECTED_ROLE_TIERS)
        self.assertNotIn("codex-transport", agent_model_matrix.ALLOWED_SUBAGENT_TYPES)



if __name__ == "__main__":
    unittest.main()
