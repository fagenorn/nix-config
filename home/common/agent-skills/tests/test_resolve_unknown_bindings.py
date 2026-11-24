"""A binding the installed platform does not know, in the two open workflow sections."""

from __future__ import annotations

import contextlib
import io
import json
import os
from unittest import mock

from agent_tools.project_contract import resolve_project, schema_three

from .test_resolve_project import ResolverTestCase, run, source_contract

TIER = "fast"

WARNING = ("resolve-project: warning: /bindings/workflow/heavy_lane is a binding "
           "this platform does not know, so it was ignored")


def with_heavy_lane():
    contract = source_contract()
    contract["bindings"]["workflow"]["heavy_lane"] = {"mode": "shadow"}
    return contract


class UnknownBindingTest(ResolverTestCase):
    def patched_home(self):
        environ = {**os.environ, "HOME": str(self.home)}
        environ.pop("AGENT_PLATFORM_ROOT", None)
        return mock.patch.dict(os.environ, environ, clear=True)

    def test_an_unknown_workflow_binding_resolves_with_a_warning_that_names_it(self):
        root = self.make_root(with_heavy_lane())
        code, snap, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        self.assertNotIn("heavy_lane", snap["bindings"]["workflow"])
        self.assertEqual(err.splitlines(), [WARNING])

    def test_an_unknown_orchestration_binding_resolves_with_a_warning(self):
        contract = source_contract()
        contract["bindings"]["workflow"]["orchestration"]["stall_seconds"] = 60
        code, snap, err = self.resolve(self.make_root(contract))
        self.assertEqual(code, 0, err)
        self.assertNotIn("stall_seconds", snap["bindings"]["workflow"]["orchestration"])
        self.assertEqual(err.splitlines(), [
            "resolve-project: warning: /bindings/workflow/orchestration/stall_seconds"
            " is a binding this platform does not know, so it was ignored"])

    def test_the_snapshot_is_the_contract_without_its_unknown_bindings(self):
        contract = with_heavy_lane()
        contract["bindings"]["workflow"]["orchestration"]["stall_seconds"] = 60
        code, snap, _ = self.resolve(self.make_root(contract))
        plain_code, plain, plain_err = self.resolve(self.make_root(source_contract()))
        self.assertEqual((code, plain_code), (0, 0))
        self.assertEqual(snap["bindings"]["workflow"], plain["bindings"]["workflow"])
        self.assertEqual(plain_err, "")

    def test_an_unknown_member_outside_the_open_sections_still_refuses(self):
        cases = (
            ("/bindings/vcs/merge/required_reviews", 1),
            ("/bindings/heavy", {}),
            ("/bindings/tracker/extra", "x"),
            ("/bindings/workflow/review/extra", "x"),
            ("/extra", {}),
            ("/bindings/workflow/orchestration/attempt_budget_basis", {}),
        )
        for pointer, value in cases:
            with self.subTest(pointer=pointer):
                contract = source_contract()
                *parents, name = pointer.split("/")[1:]
                target = contract
                for step in parents:
                    target = target[step]
                target[name] = value
                code, payload, err = self.resolve(self.make_root(contract))
                error = self.assert_refusal(code, payload, "invalid_contract")
                self.assertEqual([v["pointer"] for v in error["violations"]], [pointer])
                self.assertTrue(error["repair_id"].endswith(".member_unexpected"))
                self.assertNotIn("warning", err)

    def test_an_unsupported_schema_version_still_refuses_beside_an_unknown_binding(self):
        contract = with_heavy_lane()
        contract["schema_version"] = 99
        code, payload, _ = self.resolve(self.make_root(contract))
        error = self.assert_refusal(code, payload, "unsupported_schema")
        self.assertEqual(error["reason_code"], "project_schema_unsupported")

    def test_every_name_the_platform_knows_is_not_an_unknown_binding(self):
        workflow = set(resolve_project.WORKFLOW_MEMBERS)
        workflow |= set(resolve_project.WORKFLOW_OPTIONAL_MEMBERS)
        workflow |= set(resolve_project.SCHEMA_THREE_WORKFLOW_OPTIONAL_MEMBERS)
        orchestration = {"max_parallel", "attempt_budget_minutes"}
        orchestration |= set(resolve_project.ORCHESTRATION_OPTIONAL_MEMBERS)
        pointers = [
            *schema_three.CONSTANTS, *schema_three.DERIVED, *schema_three.RETIRED,
            *schema_three.AUTHORED, *schema_three.CONSTANT_CONTAINERS,
            *schema_three.DERIVED_CONTAINERS]
        for section, names in (("/bindings/workflow/", workflow),
                               ("/bindings/workflow/orchestration/", orchestration)):
            for pointer in pointers:
                if pointer.startswith(section):
                    names.add(pointer[len(section):].split("/")[0])
        source = {"bindings": {"workflow": {
            **dict.fromkeys(workflow), "orchestration": dict.fromkeys(orchestration)}}}
        self.assertEqual(resolve_project.unknown_bindings(source), [])
        self.assertEqual(resolve_project.unknown_bindings(
            {"bindings": {"workflow": {"a/b~c": 1}}}), ["/bindings/workflow/a~1b~0c"])
        for value in (None, [], {"bindings": []}, {"bindings": {"workflow": 3}}):
            with self.subTest(value=value):
                self.assertEqual(resolve_project.unknown_bindings(value), [])

    def test_platform_status_names_the_unknown_binding_and_stays_compatible(self):
        root = self.make_root(with_heavy_lane())
        code, out, err = run("platform-status", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIs(json.loads(out)["compatibility"]["compatible"], True)
        self.assertEqual(err.splitlines(), [WARNING])

    def test_the_fleet_and_projection_readers_accept_an_unknown_binding(self):
        root = self.make_root(with_heavy_lane())
        code, _, err = run("check-projections", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        with self.patched_home():
            manifest = resolve_project.require_platform_manifest()[0]
            self.assertIsNone(resolve_project.fleet_verdict(root, manifest)[1])

    def test_the_library_reports_unknown_bindings_only_to_a_caller_that_asks(self):
        root = self.make_root(with_heavy_lane())
        found: list[str] = []
        captured = io.StringIO()
        with self.patched_home(), contextlib.redirect_stderr(captured):
            resolve_project.resolve(str(root), warnings=found)
            resolve_project.resolve(str(root))
        self.assertEqual(found, ["/bindings/workflow/heavy_lane"])
        self.assertEqual(captured.getvalue(), "")
