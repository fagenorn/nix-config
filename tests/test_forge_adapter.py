"""Forge adapter against a fake provider world (#124 AC3, AC7, AC9). Run: just agent-workflow-tests"""
import ast
import json
import shlex
import unittest
from pathlib import Path

from agent_tools import forge_adapter, release_adapter, release_profile
from . import release_test_support as support
from .forge_world import ForgeWorld

FIXTURE = json.loads((Path(__file__).parent / "fixtures/forge-adapter-spellings.json").read_text("utf-8"))
C = FIXTURE["canonical"]
ROWS = {row["id"]: row for row in FIXTURE["rows"]}
TARGET = {"kind": "github_repository", "repository": C["slug"], "branch": C["branch"]}
CANDIDATE = {"version": C["tag"], "commit": C["commit"]}

def effect(operation, **parameters):
    return {"kind": "effect", "operation": operation, "parameters": {"target": TARGET, **parameters}}

class ForgeCase(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)

    def tag_ref(self, object_type="tag", sha=C["tag_object"]):
        self.world.respond_json("gh", ROWS["tag.ref"]["argv"][1:], {"object": {"type": object_type, "sha": sha}})

    def tag_object(self, peeled=C["commit"]):
        self.world.respond_json("gh", ROWS["tag.object"]["argv"][1:], {"object": {"type": "commit", "sha": peeled}})

    def inspect(self, request):
        observation = forge_adapter.inspect(request)
        self.assertEqual(release_adapter.effect_observation_problems(observation), [])
        return observation

class TagInspectTest(ForgeCase):
    def test_target_read_from_tag_not_release_commitish(self):
        self.tag_ref()
        self.tag_object(peeled=C["commit"])
        self.world.respond_json("gh", ROWS["release.view"]["argv"][1:], {
            "tag_name": C["tag"], "draft": False, "target_commitish": "main",
            "html_url": "https://github.com/fagenorn/nix-config/releases/tag/v1.2.3"})
        observation = self.inspect(effect("release", candidate=CANDIDATE, title=C["title"], notes="n"))
        self.assertEqual((observation["outcome"], observation["observed_subject"]["commit"]),
                         ("satisfied", C["commit"]))
        self.assertEqual(self.world.argvs("gh"), [ROWS[i]["argv"][1:] for i in
                                                  ("release.view", "tag.ref", "tag.object")])

    def test_lightweight_tag_is_diverged(self):
        self.tag_ref(object_type="commit", sha=C["commit"])
        observation = self.inspect(effect("tag", candidate=CANDIDATE))
        self.assertEqual((observation["outcome"], observation["reason"]), ("diverged", "tag_not_annotated"))

    def test_absent_mismatch_and_predicates(self):
        self.world.not_found("gh", ROWS["tag.ref"]["argv"][1:])
        self.assertEqual(self.inspect(effect("tag", candidate=CANDIDATE))["outcome"], "absent")
        predicate = forge_adapter.inspect({"kind": "predicate", "predicate": "publication_visible",
                                           "operation": "tag",
                                           "parameters": {"target": TARGET, "candidate": CANDIDATE}})
        self.assertEqual(release_adapter.predicate_observation_problems(predicate), [])
        self.assertEqual((predicate["outcome"], predicate["reason"]), ("unsatisfied", "ref_absent"))
        self.tag_ref()
        self.tag_object(peeled="9" * 40)
        self.assertEqual(self.inspect(effect("tag", candidate=CANDIDATE))["reason"], "tag_target_mismatch")

    def test_draft_release_is_diverged(self):
        self.world.respond_json("gh", ROWS["release.view"]["argv"][1:],
                                {"tag_name": C["tag"], "draft": True, "html_url": "u"})
        self.assertEqual(self.inspect(effect("release", candidate=CANDIDATE, title="t", notes="n"))["reason"],
                         "release_draft")

    def test_release_for_another_tag_and_absent_release(self):
        self.world.respond_json("gh", ROWS["release.view"]["argv"][1:],
                                {"tag_name": "v9.9.9", "draft": False, "html_url": "u"})
        self.assertEqual(self.inspect(effect("release", candidate=CANDIDATE, title="t", notes="n"))["reason"],
                         "release_tag_mismatch")
        self.world.reset()
        self.world.not_found("gh", ROWS["release.view"]["argv"][1:])
        observation = self.inspect(effect("release", candidate=CANDIDATE, title="t", notes="n"))
        self.assertEqual((observation["outcome"], observation["reason"]), ("absent", "release_absent"))

    def test_predicate_reasons_follow_the_effect_outcome(self):
        request = {"kind": "predicate", "predicate": "publication_visible", "operation": "tag",
                   "parameters": {"target": TARGET, "candidate": CANDIDATE}}
        self.tag_ref(object_type="commit", sha=C["commit"])
        self.assertEqual(forge_adapter.inspect(request)["reason"], "ref_not_immutable")
        self.world.reset()
        self.tag_ref()
        self.tag_object(peeled="9" * 40)
        self.assertEqual(forge_adapter.inspect(request)["reason"], "subject_mismatch")
        self.world.reset()
        self.tag_ref()
        self.tag_object()
        predicate = forge_adapter.inspect(request)
        self.assertEqual((predicate["outcome"], predicate["reason"]), ("satisfied", "observed"))
        self.world.reset()
        predicate = forge_adapter.inspect(request)
        self.assertEqual((predicate["outcome"], predicate["reason"]), ("unknown", "store_unreachable"))
        self.assertEqual(forge_adapter.inspect({**request, "predicate": "running_subject_identity"})["reason"],
                         "store_unreachable")

class PrMergeInspectTest(ForgeCase):
    def pr(self, state, parents=(C["base_tip"], C["head"]), protection=None):
        self.world.respond_json("gh", ROWS["pr_merge.view"]["argv"][1:], {
            "state": state, "baseRefName": "main", "headRefName": "topic", "headRefOid": C["head"],
            "mergeCommit": {"oid": C["merge_commit"]} if state == "MERGED" else None,
            "url": "https://github.com/fagenorn/nix-config/pull/336", "statusCheckRollup": []})
        self.world.respond_json("gh", ROWS["pr_merge.base_ref"]["argv"][1:], {"object": {"sha": C["base_tip"]}})
        self.world.respond_json("gh", ROWS["pr_merge.merge_commit"]["argv"][1:],
                                {"parents": [{"sha": sha} for sha in parents]})
        if protection is None:
            self.world.respond_json("gh", ROWS["pr_merge.protection"]["argv"][1:], {
                "required_status_checks": {"contexts": ["Nix Eval"]}, "enforce_admins": {"enabled": True}})
        else:
            protection("gh", ROWS["pr_merge.protection"]["argv"][1:])

    def request(self):
        return effect("pr_merge", pr=C["pr"], expected_base_tip=C["base_tip"], expected_head=C["head"])

    def test_states_and_protection_facts(self):
        for state, parents, protection, outcome, status in (
                ("OPEN", (), None, "absent", "protected"),
                ("MERGED", (C["base_tip"], C["head"]), None, "satisfied", "protected"),
                ("MERGED", (C["head"], C["base_tip"]), None, "diverged", "protected"),
                ("CLOSED", (), self.world.not_found, "diverged", "unprotected"),
                ("OPEN", (), self.world.forbidden, "absent", "inaccessible")):
            with self.subTest(state=state, outcome=outcome, status=status):
                self.world.reset()
                self.pr(state, parents, protection)
                observation = self.inspect(self.request())
                self.assertEqual((observation["outcome"], observation["facts"]["protection"]["status"]),
                                 (outcome, status))
                self.assertEqual(observation["facts"]["base_tip"], C["base_tip"])

    def test_the_facts_are_the_demo_readback(self):
        self.pr("OPEN")
        facts = self.inspect(self.request())["facts"]
        self.assertEqual(facts, {"state": "OPEN", "base": "main", "head": "topic", "head_oid": C["head"],
                                 "base_tip": C["base_tip"],
                                 "protection": {"status": "protected", "required_contexts": ["Nix Eval"],
                                                "enforce_admins": True}})
        self.assertNotIn(ROWS["pr_merge.merge_commit"]["argv"][1:], self.world.argvs("gh"))

class InspectFailureTest(ForgeCase):
    def with_budget(self, seconds, request):
        saved = forge_adapter.COLLECTION_BUDGET_SECONDS
        forge_adapter.COLLECTION_BUDGET_SECONDS = seconds
        try:
            return self.inspect(request)
        finally:
            forge_adapter.COLLECTION_BUDGET_SECONDS = saved

    def test_lookup_failures_are_unknown(self):
        argv = ROWS["tag.ref"]["argv"][1:]
        for name, respond, reason in (
                ("nonzero", lambda: self.world.respond("gh", argv, exit=1, stderr="boom"), "lookup_failed"),
                ("invalid json", lambda: self.world.respond("gh", argv, stdout="{"), "payload_invalid"),
                ("missing field", lambda: self.world.respond_json("gh", argv, {"object": {}}), "payload_invalid"),
                ("timeout", lambda: self.world.respond("gh", argv, sleep=2), "lookup_timeout")):
            with self.subTest(name):
                self.world.reset()
                respond()
                observation = self.with_budget(0.5, effect("tag", candidate=CANDIDATE))
                self.assertEqual((observation["outcome"], observation["reason"]), ("unknown", reason))

    def test_stderr_is_kept_as_bounded_detail(self):
        self.world.respond("gh", ROWS["tag.ref"]["argv"][1:], exit=1, stderr="x" * 500)
        observation = self.inspect(effect("tag", candidate=CANDIDATE))
        self.assertEqual(observation["facts"]["detail"], "x" * 240)

    def test_missing_gh_is_executable_missing(self):
        (self.world.bin / "gh").unlink()
        observation = self.inspect(effect("tag", candidate=CANDIDATE))
        self.assertEqual((observation["outcome"], observation["reason"]), ("unknown", "executable_missing"))

    def test_the_collection_budget_spans_every_read(self):
        self.world.canonical()
        self.world.respond_json("gh", ROWS["tag.ref"]["argv"][1:],
                                {"object": {"type": "tag", "sha": C["tag_object"]}}, sleep=0.35)
        self.world.respond_json("gh", ROWS["tag.object"]["argv"][1:],
                                {"object": {"type": "commit", "sha": C["commit"]}}, sleep=0.35)
        observation = self.with_budget(0.5, effect("tag", candidate=CANDIDATE))
        self.assertEqual((observation["outcome"], observation["reason"]), ("unknown", "lookup_timeout"))

    def test_invalid_parameters_make_no_call(self):
        cases = (
            {"kind": "effect", "operation": "tag", "parameters": {"target": TARGET}},
            effect("tag", candidate={"version": "1.2.3", "commit": C["commit"]}),
            effect("tag", candidate=CANDIDATE, surprise=1),
            effect("pr_merge", pr=0, expected_base_tip=C["base_tip"], expected_head=C["head"]),
            effect("pr_merge", pr=True, expected_base_tip=C["base_tip"], expected_head=C["head"]),
            {"kind": "effect", "operation": "tag",
             "parameters": {"target": {**TARGET, "kind": "other"}, "candidate": CANDIDATE}},
            {"kind": "effect", "operation": "tag",
             "parameters": {"target": {**TARGET, "repository": "a/b/../c"}, "candidate": CANDIDATE}},
            {"kind": "effect", "operation": "merge", "parameters": {"target": TARGET}})
        for request in cases:
            with self.subTest(request=request):
                observation = self.inspect(request)
                self.assertEqual((observation["outcome"], observation["reason"]),
                                 ("unknown", "parameters_invalid"))
        self.assertEqual(self.world.calls(), [])

    def test_tolerated_members_and_scrubbed_environment(self):
        self.world.canonical()
        request = effect("tag", candidate=CANDIDATE)
        request["parameters"].update({"action": "tag", "operation": "tag", "config": {},
                                      "target": {**TARGET, "handle": "repository"}})
        self.assertEqual(self.inspect(request)["outcome"], "satisfied")
        self.assertEqual([call["token_visible"] for call in self.world.calls()], [False, False])

    def test_repository_classes_render_their_own_slug(self):
        for slug in ("elevenyellow/nodocom", "someone-else/nix-config"):
            with self.subTest(slug=slug):
                self.world.reset()
                self.world.canonical(slug=slug)
                target = {**TARGET, "repository": slug}
                observation = self.inspect({"kind": "effect", "operation": "tag",
                                            "parameters": {"target": target, "candidate": CANDIDATE}})
                self.assertEqual(observation["outcome"], "satisfied")
                self.assertTrue(all(slug in " ".join(argv) for argv in self.world.argvs("gh")))

class CoreBindingTest(ForgeCase):
    def setUp(self):
        super().setUp()
        self.compiled = release_profile.compile_profile(
            "github-release", support.forge_profile(), support.base_contract(), support.descriptors())
        inputs = release_profile.bind_candidate(self.compiled, support.CANDIDATE)
        self.units = {unit["name"]: unit["parameters"] for unit in inputs["proof"]["units"]}
        self.binding = release_adapter.core_binding(forge_adapter, self.compiled, "forge")

    def test_inspect_projects_onto_the_core_shape(self):
        self.world.not_found("gh", ROWS["tag.ref"]["argv"][1:])
        result = self.binding.inspect({"parameters": self.units["tag"]})
        self.assertEqual(sorted(result), ["outcome", "reference"])
        self.assertEqual(result["outcome"], "absent")
        self.assertEqual(json.loads(result["reference"])["reason"], "tag_absent")

    def test_a_different_implementation_is_refused(self):
        descriptors = support.descriptors()
        descriptors["github-forge"]["collector"]["max_concurrent_collections"] = 2
        other = release_profile.compile_profile(
            "github-release", support.forge_profile(), support.base_contract(), descriptors)
        with self.assertRaises(ValueError):
            release_adapter.core_binding(forge_adapter, other, "forge")
        with self.assertRaises(ValueError):
            release_adapter.core_binding(forge_adapter, self.compiled, "unbound")

    def test_observe_routes_a_derived_request_through_inspect(self):
        self.world.not_found("gh", ROWS["tag.ref"]["argv"][1:])
        result = self.binding.observe({"predicate": "publication_visible",
                                       "parameters": {"name": "tag", "parameters": self.units["tag"]}})
        self.assertEqual(sorted(result), ["outcome", "reason", "reference"])
        self.assertEqual((result["outcome"], result["reason"]), ("unsatisfied", "ref_absent"))
        json.loads(result["reference"])

    def test_a_request_that_is_not_its_compiled_node_is_refused_before_any_call(self):
        changed = {"operation": "release",
                   "target": {**self.units["tag"]["target"], "repository": "someone-else/nix-config"},
                   "config": {"extra": 1}}
        for member, value in changed.items():
            for call in ("inspect", "invoke", "observe"):
                with self.subTest(member=member, call=call):
                    parameters = {**self.units["tag"], member: value}
                    request = ({"predicate": "publication_visible",
                                "parameters": {"name": "tag", "parameters": parameters}}
                               if call == "observe" else {"parameters": parameters})
                    with self.assertRaises(ValueError):
                        getattr(self.binding, call)(request)
        for call in ("inspect", "invoke"):
            with self.assertRaises(ValueError):
                getattr(self.binding, call)({"parameters": {**self.units["tag"], "action": "elsewhere"}})
        self.assertEqual(self.world.calls(), [])

    def test_an_invalid_adapter_result_is_refused(self):
        class Broken:
            describe = staticmethod(forge_adapter.describe)
            inspect = staticmethod(lambda request: {"outcome": "satisfied"})
        binding = release_adapter.core_binding(Broken, self.compiled, "forge")
        with self.assertRaises(ValueError):
            binding.inspect({"parameters": self.units["tag"]})

class ResultValidatorTest(unittest.TestCase):
    def test_closed_shapes(self):
        good = {"outcome": "absent", "reason": "tag_absent", "observed_subject": {}, "references": ["r"],
                "observed_at": 1, "facts": {}}
        self.assertEqual(release_adapter.effect_observation_problems(good), [])
        self.assertTrue(release_adapter.effect_observation_problems({**good, "outcome": "unsatisfied"}))
        self.assertTrue(release_adapter.effect_observation_problems({**good, "extra": 1}))
        self.assertTrue(release_adapter.effect_observation_problems({**good, "observed_at": True}))
        predicate = {"outcome": "unsatisfied", "reason": "ref_absent", "references": [], "observed_at": 1}
        self.assertEqual(release_adapter.predicate_observation_problems(predicate), [])
        self.assertTrue(release_adapter.predicate_observation_problems({**predicate, "outcome": "absent"}))
        for result, valid in (({"result": "accepted", "error_class": None, "reference": "r"}, True),
                              ({"result": "rejected", "error_class": "invalid_input", "reference": "r"}, True),
                              ({"result": "accepted", "error_class": "invalid_input", "reference": "r"}, False),
                              ({"result": "rejected", "error_class": None, "reference": "r"}, False),
                              ({"result": "succeeded", "error_class": None, "reference": "r"}, False),
                              ({"result": "unknown", "error_class": "nope", "reference": "r"}, False),
                              ({"result": "accepted", "error_class": None, "reference": ""}, False)):
            self.assertEqual(release_adapter.invoke_result_problems(result) == [], valid, result)

class SpellingFixtureTest(unittest.TestCase):
    def test_rows_are_closed_and_tokenize_to_their_argv(self):
        for row in FIXTURE["rows"]:
            with self.subTest(row=row["id"]):
                self.assertEqual(sorted(row), ["argv", "id", "kind", "operation", "raw"])
                self.assertEqual(shlex.split(row["raw"]), row["argv"])
                self.assertIn(row["kind"], ("read", "mutation"))

class HostCapacityTest(unittest.TestCase):
    def test_capacity_is_declared_not_implemented(self):
        self.assertEqual(forge_adapter.describe()["host_capacity"], "not_required")
        tree = ast.parse(Path(forge_adapter.__file__).read_text("utf-8"))
        names = [alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                 for alias in node.names] + [node.module or "" for node in ast.walk(tree)
                                             if isinstance(node, ast.ImportFrom)]
        for name in names:
            self.assertFalse("host_admission" in name or name.split(".")[-1].startswith("launch_"), name)

if __name__ == "__main__":
    unittest.main()
