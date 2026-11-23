"""The optional `bindings.workflow.verification_before_pull_request` member of the contract."""

from __future__ import annotations

import json

from agent_tools.project_contract import resolve_project, schema_three

from .test_resolve_project import REPO_ROOT, ResolverTestCase, run, source_contract

TIER = "fast"

POINTER = "/bindings/workflow/verification_before_pull_request"
# B17 (D8): the resolver's one reasoned size suppression, its last line.
SIZE_SUPPRESSION = "# suppress-standard:B17 the validators share this module's check helpers and violation shape, so it stays one file"


class VerificationBeforePullRequestTest(ResolverTestCase):
    ABSENT = object()

    def contract_with(self, member):
        contract = source_contract()
        # The schema-2 fixture declares neither `lint` nor `test`, so declare them here.
        for command_id in ("lint", "test"):
            contract["bindings"]["commands"][command_id] = {
                "argv": ["just", command_id], "cwd": ".", "env": []}
        workflow = contract["bindings"]["workflow"]
        workflow["verification"] = ["lint", "test"]
        workflow.pop("verification_before_pull_request", None)
        if member is not self.ABSENT:
            workflow["verification_before_pull_request"] = member
        return contract

    def resolved_member(self, member):
        code, snap, err = self.resolve(self.make_root(self.contract_with(member)))
        self.assertEqual(code, 0, err)
        return snap["bindings"]["workflow"]

    def test_an_undeclared_command_id_is_refused(self):
        code, payload, _ = self.resolve(
            self.make_root(self.contract_with(["lint", "nope"])))
        error = self.assert_refusal(code, payload, "invalid_contract")
        self.assertEqual([v["pointer"] for v in error["violations"]], [POINTER + "/1"])
        self.assertEqual(error["repair_id"], "contract.workflow.unknown_command_id")

    def test_a_valid_list_round_trips_unchanged(self):
        for member in (["lint"], ["lint", "test"], ["test", "codex-diff-review"]):
            with self.subTest(member=member):
                workflow = self.resolved_member(member)
                self.assertEqual(workflow["verification_before_pull_request"], member)
                self.assertEqual(workflow["verification"], ["lint", "test"])

    def test_an_absent_member_stays_absent(self):
        self.assertNotIn("verification_before_pull_request",
                         self.resolved_member(self.ABSENT))

    def test_null_stays_null(self):
        workflow = self.resolved_member(None)
        self.assertIn("verification_before_pull_request", workflow)
        self.assertIsNone(workflow["verification_before_pull_request"])

    REFUSALS = (
        # (member, pointer suffix, repair id); the suffix is rooted at POINTER.
        ("lint", "", "contract.workflow.not_list"),
        ([], "", "contract.workflow.empty_command_list"),
        (["lint", 3], "/1", "contract.workflow.not_string"),
        ([""], "/0", "contract.workflow.not_string"),
        (["nope"], "/0", "contract.workflow.unknown_command_id"),
    )

    def test_each_refusal_names_its_pointer_and_repair_id(self):
        for member, suffix, repair_id in self.REFUSALS:
            with self.subTest(member=member):
                code, payload, _ = self.resolve(
                    self.make_root(self.contract_with(member)))
                error = self.assert_refusal(code, payload, "invalid_contract")
                self.assertEqual([v["pointer"] for v in error["violations"]],
                                 [POINTER + suffix])
                self.assertEqual(error["repair_id"], repair_id)

    def test_the_schema_constants_name_the_binding(self):
        self.assertIn("verification_before_pull_request",
                      resolve_project.WORKFLOW_OPTIONAL_MEMBERS)
        self.assertIn("verification_before_pull_request",
                      resolve_project.SCHEMA_THREE_WORKFLOW_OPTIONAL_MEMBERS)
        self.assertTrue(schema_three.authored(POINTER))

    def test_the_glossary_documents_the_binding(self):
        lines = (REPO_ROOT / "docs/areas/project-contract/CONTEXT.md").read_text(
            encoding="utf-8").splitlines()
        self.assertIn("**Pre-pull-request verification**:", lines)
        paragraph = lines[lines.index("**Pre-pull-request verification**:") + 1]
        self.assertIn("`workflow.verification_before_pull_request`", paragraph)
        self.assertIn("workflow.verification", paragraph)

    def test_the_resolver_ends_in_its_reasoned_size_suppression(self):
        source = (REPO_ROOT / "python/agent_tools/project_contract/resolve_project.py")
        self.assertEqual(source.read_text(encoding="utf-8").splitlines()[-1],
                         SIZE_SUPPRESSION)


class CommittedPrePullRequestTest(ResolverTestCase):
    """The repository's own contract opts in to the pre-pull-request list."""

    def snapshot(self):
        code, out, err = run("resolve", "--repo-root", str(REPO_ROOT), home=self.home)
        self.assertEqual(code, 0, err)
        return json.loads(out)["bindings"]

    def test_the_repositorys_own_pre_pull_request_verification_is_lint_then_test_touched(self):
        bindings = self.snapshot()
        workflow = bindings["workflow"]
        self.assertEqual(workflow["verification_before_pull_request"],
                         ["lint", "test-touched"])
        self.assertEqual(bindings["commands"]["test-touched"],
                         {"argv": ["just", "test-touched"], "cwd": str(REPO_ROOT), "env": []})
        self.assertEqual(workflow["verification"], ["lint", "test"])

    def test_every_pre_pull_request_id_names_a_justfile_recipe(self):
        bindings = self.snapshot()
        justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8").splitlines()
        for command_id in bindings["workflow"]["verification_before_pull_request"]:
            with self.subTest(command_id=command_id):
                argv = bindings["commands"][command_id]["argv"]
                self.assertEqual(argv[0], "just")
                self.assertEqual(len(argv), 2)
                self.assertTrue(any(line.startswith(argv[1] + ":") for line in justfile),
                                argv[1])
