"""The core read of the project contract: `resolve_core` judges and returns only the members enforcement reads."""

from __future__ import annotations

import copy
import os
from unittest import mock

from agent_tools.project_contract import resolve_project

from .test_resolve_project import REPO_ROOT, ResolverTestCase, source_contract

TIER = "fast"

GITHUB_RELEASE_PRODUCTION = {
    "none": False,
    "changes": {"commands": [], "key_files": [], "mcp_tools": [], "urls": []},
    "read_only": {"commands": [], "mcp_tools": []},
    "release_profile": "github-release",
}


class CoreReadTest(ResolverTestCase):
    def setUp(self):
        super().setUp()
        environ = {key: value for key, value in os.environ.items() if key != "AGENT_PLATFORM_ROOT"}
        environ["HOME"] = str(self.home)
        patcher = mock.patch.dict(os.environ, environ, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def refusal(self, root):
        with self.assertRaises(resolve_project.ContractError) as caught:
            resolve_project.resolve_core(str(root))
        return caught.exception

    def test_the_core_read_of_a_valid_contract_is_the_full_snapshots_members(self):
        for root in (str(REPO_ROOT), str(self.make_root(source_contract()))):
            with self.subTest(root=root):
                core = resolve_project.resolve_core(root)
                full = resolve_project.resolve(root)
                self.assertEqual(core, {
                    "project": full["project"],
                    "bindings": {name: full["bindings"][name] for name in ("vcs", "tracker", "commands")},
                    "release": full["release"],
                    "production": full["production"],
                })

    def test_the_core_read_ignores_what_lies_outside_its_members(self):
        expected = source_contract()["bindings"]["vcs"]["integration_branch"]

        def interval(contract):
            contract["platform"] = {"min_inclusive": "99.0.0", "max_exclusive": "100.0.0"}

        def playbooks(contract):
            contract["bindings"]["paths"]["playbooks"] = ["docs"]

        def capability(contract):
            contract["capabilities"]["unknown"] = {}

        def verification(contract):
            contract["bindings"]["workflow"]["verification"] = ["no-such-command"]

        def drift(contract):
            return None

        for name, mutate in (("interval", interval), ("playbooks", playbooks), ("capability", capability),
                             ("verification", verification), ("projection drift", drift)):
            with self.subTest(name):
                contract = source_contract()
                mutate(contract)
                root = self.make_root(contract)
                if name == "projection drift":
                    (root / "AGENTS.md").write_bytes(b"drift\n")
                with self.assertRaises(resolve_project.ContractError):
                    resolve_project.resolve(str(root))
                core = resolve_project.resolve_core(str(root))
                self.assertEqual(core["bindings"]["vcs"]["integration_branch"], expected)

    def test_the_core_read_refuses_a_broken_core_member(self):
        def set_member(path, value):
            def mutate(contract):
                target = contract
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
            return mutate

        def drop_release(contract):
            del contract["release"]

        cases = (
            ("required_reviews", set_member(("bindings", "vcs", "merge", "required_reviews"), 1),
             "/bindings/vcs/merge/required_reviews"),
            ("tracker extra", set_member(("bindings", "tracker", "extra"), "x"), "/bindings/tracker/extra"),
            ("no release", drop_release, "/release"),
            ("command extra",
             set_member(("bindings", "commands", "x"), {"argv": [], "cwd": ".", "env": [], "extra": 1}),
             "/bindings/commands/x"),
            ("production", set_member(("production",), copy.deepcopy(GITHUB_RELEASE_PRODUCTION)), "/production"),
        )
        for name, mutate, pointer in cases:
            with self.subTest(name):
                contract = source_contract()
                mutate(contract)
                error = self.refusal(self.make_root(contract))
                self.assertEqual(error.code, "invalid_contract")
                first = error.violations[0]["pointer"]
                self.assertTrue(first == pointer or first.startswith(pointer + "/"), first)
                if name in ("required_reviews", "tracker extra", "no release"):
                    self.assertEqual(first, pointer)

    def test_the_core_read_refuses_an_unsupported_schema_version(self):
        contract = source_contract()
        contract["schema_version"] = 99
        self.assertEqual(self.refusal(self.make_root(contract)).code, "unsupported_schema")

    def test_the_core_read_answers_a_closed_error_for_any_other_failure(self):
        root = self.make_root(source_contract())
        with mock.patch.object(resolve_project, "derive_for", side_effect=RuntimeError("boom")):
            error = self.refusal(root)
        self.assertEqual((error.code, error.repair_id), ("resolver_failure", "resolver.internal"))
