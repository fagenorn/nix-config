"""Forge adapter against a fake provider world (#124 AC3, AC7, AC9). Run: just agent-workflow-tests"""
import ast
import json
import shlex
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.release import forge_adapter, release_adapter, release_profile
from agent_tools.system import github_remote
from . import forge_world
from . import release_test_support as support
from .forge_world import ForgeWorld

FIXTURE = json.loads((Path(__file__).parent / "fixtures/forge-adapter-spellings.json").read_text("utf-8"))
C = FIXTURE["canonical"]
ROWS = {row["id"]: row for row in FIXTURE["rows"]}
TARGET = {"kind": "github_repository", "repository": C["slug"], "branch": C["branch"]}
CANDIDATE = {"version": C["tag"], "commit": C["commit"]}
MERGE = {"pr": C["pr"], "base_tip": C["base_tip"]}
MERGE_CANDIDATE = {**CANDIDATE, "merge": MERGE}

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

    def test_nested_annotated_tag_is_peeled_to_its_commit(self):
        inner = "6" * 40
        self.tag_ref()
        self.world.respond_json("gh", ROWS["tag.object"]["argv"][1:],
                                {"object": {"type": "tag", "sha": inner}})
        inner_argv = [part.replace(C["tag_object"], inner) for part in ROWS["tag.object"]["argv"][1:]]
        self.world.respond_json("gh", inner_argv, {"object": {"type": "commit", "sha": C["commit"]}})
        observation = self.inspect(effect("tag", candidate=CANDIDATE))
        self.assertEqual((observation["outcome"], observation["observed_subject"]["commit"]),
                         ("satisfied", C["commit"]))
        self.assertEqual(self.world.argvs("gh"),
                         [ROWS["tag.ref"]["argv"][1:], ROWS["tag.object"]["argv"][1:], inner_argv])

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
    def pr(self, state, parents=(C["base_tip"], C["commit"]), protection=None, base="main"):
        def on_base(row):
            return [part.replace("/heads/main", f"/heads/{base}").replace("/branches/main/", f"/branches/{base}/")
                    for part in ROWS[row]["argv"][1:]]
        self.world.respond_json("gh", ROWS["pr_merge.view"]["argv"][1:], {
            "state": state, "baseRefName": base, "headRefName": "topic", "headRefOid": C["commit"],
            "mergeCommit": {"oid": C["merge_commit"]} if state == "MERGED" else None,
            "url": "https://github.com/fagenorn/nix-config/pull/336", "statusCheckRollup": []})
        self.world.respond_json("gh", on_base("pr_merge.base_ref"), {"object": {"sha": C["base_tip"]}})
        self.world.respond_json("gh", ROWS["pr_merge.merge_commit"]["argv"][1:],
                                {"parents": [{"sha": sha} for sha in parents]})
        if protection is None:
            self.world.respond_json("gh", on_base("pr_merge.protection"), forge_world.FLOOR_PROTECTION)
        else:
            protection("gh", on_base("pr_merge.protection"))

    def request(self):
        return effect("pr_merge", candidate=MERGE_CANDIDATE)

    def test_states_and_protection_facts(self):
        for state, parents, protection, outcome, status in (
                ("OPEN", (), None, "absent", "protected"),
                ("MERGED", (C["base_tip"], C["commit"]), None, "satisfied", "protected"),
                ("MERGED", (C["commit"], C["base_tip"]), None, "diverged", "protected"),
                ("CLOSED", (), self.world.not_found, "diverged", "unprotected"),
                ("OPEN", (), self.world.forbidden, "absent", "inaccessible")):
            with self.subTest(state=state, outcome=outcome, status=status):
                self.world.reset()
                self.pr(state, parents, protection)
                observation = self.inspect(self.request())
                self.assertEqual((observation["outcome"], observation["facts"]["protection"]["status"]),
                                 (outcome, status))
                self.assertEqual(observation["facts"]["base_tip"], C["base_tip"])

    def test_a_pr_merged_into_another_base_is_diverged(self):
        self.pr("MERGED", base="release")
        observation = self.inspect(self.request())
        self.assertEqual((observation["outcome"], observation["reason"]), ("diverged", "base_mismatch"))
        self.assertEqual((observation["facts"]["state"], observation["facts"]["base"]), ("MERGED", "release"))

    def test_the_facts_are_the_demo_readback(self):
        self.pr("OPEN")
        facts = self.inspect(self.request())["facts"]
        self.assertEqual(facts, {"state": "OPEN", "base": "main", "head": "topic", "head_oid": C["commit"],
                                 "base_tip": C["base_tip"],
                                 "protection": {"status": "protected", "strict": True,
                                                "required_contexts": ["Instruction Budget", "Nix Eval"],
                                                "enforce_admins": True}})
        self.assertNotIn(ROWS["pr_merge.merge_commit"]["argv"][1:], self.world.argvs("gh"))

    def test_a_merge_onto_a_moved_base_is_diverged(self):
        """Issue 554 row 9: GitHub merged onto a base the head already contained."""
        self.pr("MERGED", parents=("6" * 40, C["commit"]))
        observation = self.inspect(self.request())
        self.assertEqual((observation["outcome"], observation["reason"]),
                         ("diverged", "merge_parents_mismatch"))

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
            effect("pr_merge", candidate=CANDIDATE),
            effect("pr_merge", candidate={**CANDIDATE, "merge": {**MERGE, "pr": True}}),
            effect("pr_merge", candidate={**CANDIDATE, "merge": {**MERGE, "base_tip": "5" * 39}}),
            effect("pr_merge", pr=C["pr"], expected_base_tip=C["base_tip"], expected_head=C["commit"]),
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
        for row in FIXTURE["rows"] + FIXTURE["sync"]["rows"]:
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

class InvokeCase(ForgeCase):
    def invoke(self, operation, **extra):
        parameters = {"target": TARGET, "candidate": CANDIDATE, **extra}
        if operation == "release":
            parameters.setdefault("title", C["title"])
            parameters.setdefault("notes", "release notes body")
        result = forge_adapter.invoke({"kind": "effect", "operation": operation, "parameters": parameters})
        self.assertEqual(release_adapter.invoke_result_problems(result), [])
        return result

    def mutations(self):
        return [c for c in self.world.calls() if (c["tool"], c["argv"][:2]) in
                (("git", ["push", "origin"]), ("gh", ["release", "create"]))]

class GithubRemoteTest(unittest.TestCase):
    """The slug rule has one home, which the adapter imports (issue 126 D9)."""

    def test_only_the_three_github_spellings_name_a_repository(self):
        for url in ("git@github.com:fagenorn/nix-config.git", "git@github.com:fagenorn/nix-config",
                    "https://github.com/fagenorn/nix-config.git",
                    "ssh://git@github.com/fagenorn/nix-config\n"):
            with self.subTest(url=url):
                self.assertEqual(github_remote.github_slug(url), "fagenorn/nix-config")
        for url in ("git@gitlab.com:fagenorn/nix-config.git", "/srv/git/nix-config.git", "",
                    "https://github.com.evil.example/fagenorn/nix-config.git",
                    "http://github.com/fagenorn/nix-config", "git@github.com:fagenorn/..",
                    "https://github.com/fagenorn/nix-config/extra"):
            with self.subTest(url=url):
                self.assertIsNone(github_remote.github_slug(url))

    def test_the_adapter_uses_that_rule_and_keeps_no_copy(self):
        self.assertIs(forge_adapter.github_slug, github_remote.github_slug)
        for name in ("_github_slug", "GITHUB_REMOTE"):
            self.assertFalse(hasattr(forge_adapter, name), name)


class PublicSurfaceTest(unittest.TestCase):
    def test_exactly_three_public_operations(self):
        public = sorted(name for name, value in vars(forge_adapter).items()
                        if callable(value) and not name.startswith("_")
                        and getattr(value, "__module__", None) == forge_adapter.__name__)
        self.assertEqual(public, ["describe", "inspect", "invoke"])

class InvokeResultSetTest(InvokeCase):
    def test_happy_paths_render_the_fixture_and_pass_the_guard(self):
        self.world.invoke_ready()
        self.assertEqual(self.invoke("tag"), {"result": "accepted", "error_class": None,
                                              "reference": "refs/tags/v1.2.3"})
        [push] = self.mutations()
        self.assertEqual(["git", *push["argv"]], ROWS["tag.push"]["argv"])
        [guard] = [c for c in self.world.calls() if c["tool"] == "claude-bash-lifecycle-guard"]
        payload = json.loads(guard["stdin"])
        self.assertEqual(payload, {"tool_name": "Bash", "tool_input": {"command": ROWS["tag.push"]["raw"]},
                                   "cwd": str(self.world.checkout)})
        self.assertFalse(any(c["token_visible"] for c in self.world.calls()))
        self.assertFalse(any(c["argv"][:1] == ["fetch"] for c in self.world.calls() if c["tool"] == "git"))
        self.assertFalse(any(argv[:2] == ["pr", "view"] for argv in self.world.argvs("gh")))

    def test_release_create_matches_the_fixture_and_removes_the_notes_file(self):
        self.world.invoke_ready()
        self.assertEqual(self.invoke("release")["result"], "accepted")
        [create] = self.mutations()
        notes = create["argv"][-1]
        self.assertTrue(Path(notes).is_absolute())
        self.assertFalse(Path(notes).exists())
        expected = [notes if token == C["notes_path"] else token for token in ROWS["release.create"]["argv"]]
        self.assertEqual(["gh", *create["argv"]], expected)
        [guard] = [c for c in self.world.calls() if c["tool"] == "claude-bash-lifecycle-guard"]
        self.assertEqual(json.loads(guard["stdin"])["tool_input"]["command"],
                         ROWS["release.create"]["raw"].replace(C["notes_path"], notes))

class InvokeFailureTest(InvokeCase):
    def test_invalid_input_and_unknown_operations_make_no_call(self):
        self.world.invoke_ready()
        bad_titles = ('a "quoted" title', "cost $5", "back`tick", "back\\slash", "nul\x00", "line\nbreak", "cr\rhere")
        for title in bad_titles:
            with self.subTest(title=title):
                result = self.invoke("release", title=title)
                self.assertEqual((result["result"], result["error_class"]), ("rejected", "invalid_input"))
        for name, candidate in (("version", {**CANDIDATE, "version": "1.2.3"}),
                                ("commit", {**CANDIDATE, "commit": "abc"})):
            with self.subTest(name):
                result = self.invoke("tag", candidate=candidate)
                self.assertEqual((result["result"], result["error_class"]), ("rejected", "invalid_input"))
        result = forge_adapter.invoke({"kind": "effect", "operation": "merge", "parameters": {}})
        self.assertEqual((result["result"], result["error_class"], result["reference"]),
                         ("rejected", "unsupported_operation", "merge: unknown_operation"))
        self.assertEqual(self.world.calls(), [])

    def test_an_unspawnable_mutation_binary_is_rejected_not_possibly_applied(self):
        real = subprocess.run
        for operation, mutation in (("tag", ["git", "push"]), ("release", ["gh", "release"])):
            def run(argv, *args, **kwargs):
                if argv[:2] == mutation:
                    raise PermissionError(13, "Permission denied", argv[0])
                return real(argv, *args, **kwargs)
            with self.subTest(operation):
                self.world.reset()
                self.world.invoke_ready()
                with mock.patch.object(forge_adapter.subprocess, "run", side_effect=run):
                    result = self.invoke(operation)
                self.assertEqual((result["result"], result["error_class"]),
                                 ("rejected", "provider_unavailable"))
                self.assertEqual(self.mutations(), [])
                self.assertEqual(len([c for c in self.world.calls()
                                      if c["tool"] == "claude-bash-lifecycle-guard"]), 1)

    def outcome(self, operation="tag"):
        result = self.invoke(operation)
        return result["result"], result["error_class"]

    def test_each_refusal_stops_before_the_mutation(self):
        cases = (
            ("guard denial", dict(guard_exit=2), ("rejected", "authorization_denied")),
            ("other owner origin", dict(slug="someone-else/nix-config"), ("rejected", "precondition_failed")),
            ("redirected repository", dict(full_name="someone/renamed"), ("rejected", "precondition_failed")),
            ("uncontained commit", dict(compare="behind"), ("rejected", "precondition_failed")),
            ("tag at another commit", dict(tag_local="9" * 40), ("rejected", "precondition_failed")),
            ("push url elsewhere", dict(push_urls=["git@github.com:someone-else/nix-config.git"]),
             ("rejected", "precondition_failed")),
            ("two push urls", dict(push_urls=["git@github.com:fagenorn/nix-config.git"] * 2),
             ("rejected", "precondition_failed")),
            ("push url on another forge", dict(push_urls=["git@gitlab.com:fagenorn/nix-config.git"]),
             ("rejected", "precondition_failed")),
            ("origin on another forge", dict(origin="git@gitlab.com:fagenorn/nix-config.git",
                                             push_urls=["git@github.com:fagenorn/nix-config.git"]),
             ("rejected", "precondition_failed")),
            ("push url on a github lookalike host",
             dict(push_urls=["https://github.com.evil.example/fagenorn/nix-config.git"]),
             ("rejected", "precondition_failed")),
            ("local tag lookup fails", dict(tag_lookup_exit=128), ("rejected", "provider_unavailable")),
            ("local tag creation fails", dict(tag_create_exit=128), ("rejected", "provider_unavailable")),
        )
        for name, ready, expected in cases:
            with self.subTest(name):
                self.world.reset()
                self.world.invoke_ready(**ready)
                self.assertEqual(self.outcome(), expected)
                self.assertEqual(self.mutations(), [])

    def test_every_github_spelling_of_the_target_is_the_same_repository(self):
        for origin, push in (("https://github.com/fagenorn/nix-config.git",
                              "ssh://git@github.com/fagenorn/nix-config.git"),
                             ("ssh://git@github.com/fagenorn/nix-config",
                              "https://github.com/fagenorn/nix-config")):
            with self.subTest(origin=origin, push=push):
                self.world.reset()
                self.world.invoke_ready(origin=origin, push_urls=[push])
                self.assertEqual(self.outcome(), ("accepted", None))
                self.assertEqual(len(self.mutations()), 1)

    def test_provider_answers(self):
        cases = (
            ("tag exists remotely", "tag",
             dict(push_exit=1, push_stderr="! [rejected] v1.2.3 -> v1.2.3 (already exists)"),
             ("rejected", "precondition_failed")),
            ("release exists", "release",
             dict(create_exit=1, create_stdout="", create_stderr="HTTP 422: Validation Failed"),
             ("rejected", "precondition_failed")),
            ("push timeout", "tag", dict(push_sleep=6), ("unknown", "transient_transport")),
        )
        for name, operation, ready, expected in cases:
            with self.subTest(name):
                self.world.reset()
                self.world.invoke_ready(**ready)
                saved = forge_adapter.CHILD_TIMEOUT_SECONDS
                # only the timeout case shortens the child budget: a short budget on the
                # other cases lets a loaded host time out the guard or a precondition read
                if expected[1] == "transient_transport":
                    forge_adapter.CHILD_TIMEOUT_SECONDS = 2
                try:
                    self.assertEqual(self.outcome(operation), expected)
                finally:
                    forge_adapter.CHILD_TIMEOUT_SECONDS = saved
                self.assertEqual(len(self.mutations()), 1)

class PrMergeInvokeTest(InvokeCase):
    """Issue 554 spec §3: every refusal comes before the guard and the merge."""

    def setUp(self):
        super().setUp()
        self.world.invoke_ready()

    def merge(self, candidate=MERGE_CANDIDATE):
        result = forge_adapter.invoke({"kind": "effect", "operation": "pr_merge",
                                       "parameters": {"target": TARGET, "candidate": candidate}})
        self.assertEqual(release_adapter.invoke_result_problems(result), [])
        return result

    def guards(self):
        return [c for c in self.world.calls() if c["tool"] == "claude-bash-lifecycle-guard"]

    def merges(self):
        return [c for c in self.world.calls() if c["tool"] == "gh" and c["argv"][:2] == ["pr", "merge"]]

    def refused(self, reference, **ready):
        self.world.merge_ready(**ready)
        self.assertEqual(self.merge(), {"result": "rejected", "error_class": "precondition_failed",
                                        "reference": reference})
        self.assertEqual((self.guards(), self.merges()), ([], []))

    def test_the_happy_path_renders_the_fixture_row_and_passes_the_guard(self):
        self.world.merge_ready()
        self.assertEqual(self.merge(), {"result": "accepted", "error_class": None,
                                        "reference": f"https://github.com/{C['slug']}/pull/{C['pr']}"})
        [merge] = self.merges()
        self.assertEqual(["gh", *merge["argv"]], ROWS["pr_merge.merge"]["argv"])
        [guard] = self.guards()
        self.assertEqual(json.loads(guard["stdin"])["tool_input"]["command"], ROWS["pr_merge.merge"]["raw"])
        reads = [c["argv"] for c in self.world.calls() if c["tool"] == "gh" and c["argv"][:2] != ["pr", "merge"]]
        self.assertEqual(reads, [ROWS[i]["argv"][1:] for i in (
            "invoke.repository", "pr_merge.protection", "pr_merge.head_auto_delete",
            "pr_merge.view", "pr_merge.base_ref")])
        self.assertFalse(any(c["token_visible"] for c in self.world.calls()))

    def test_a_protection_floor_gap_refuses_before_the_guard(self):
        """Issue 554 row 1."""
        floor = forge_world.FLOOR_PROTECTION
        checks = floor["required_status_checks"]
        for member, protection in (
                ("strict", {**floor, "required_status_checks": {**checks, "strict": False}}),
                ("strict", {**floor, "required_status_checks": None}),
                ("required_contexts", {**floor, "required_status_checks": {**checks, "contexts": []}}),
                ("enforce_admins", {**floor, "enforce_admins": {"enabled": False}}),
                ("unprotected", 404), ("inaccessible", 403)):
            with self.subTest(member=member, protection=protection):
                self.world.reset()
                self.world.invoke_ready()
                self.refused(f"protection_floor_unmet: {member}", protection=protection)

    def test_a_failed_protection_read_refuses_with_no_mutation(self):
        """Issue 554 row 2."""
        for protection, error_class in (("fail", "provider_unavailable"), ("timeout", "transient_transport")):
            with self.subTest(protection=protection):
                self.world.reset()
                self.world.invoke_ready()
                self.world.merge_ready(protection=protection)
                saved = forge_adapter.CHILD_TIMEOUT_SECONDS
                forge_adapter.CHILD_TIMEOUT_SECONDS = 2
                try:
                    result = self.merge()
                finally:
                    forge_adapter.CHILD_TIMEOUT_SECONDS = saved
                self.assertEqual((result["result"], result["error_class"]), ("rejected", error_class))
                self.assertEqual((self.guards(), self.merges()), ([], []))

    def test_head_auto_delete_refuses_before_the_guard(self):
        """Issue 554 row 15."""
        for answer in ("true", "null", ""):
            with self.subTest(answer=answer):
                self.world.reset()
                self.world.invoke_ready()
                self.refused("head_auto_delete_on", auto_delete=answer)

    def test_a_pr_not_open_on_another_base_or_head_refuses(self):
        """Issue 554 row 3."""
        for ready, reference in ((dict(pr_state="MERGED"), "pr_not_open: MERGED"),
                                 (dict(pr_state="CLOSED"), "pr_not_open: CLOSED"),
                                 (dict(pr_base="release"), "pr_base_mismatch: release"),
                                 (dict(pr_head="9" * 40), "pr_head_mismatch: " + "9" * 40)):
            with self.subTest(reference=reference):
                self.world.reset()
                self.world.invoke_ready()
                self.refused(reference, **ready)

    def test_a_moved_base_refuses_base_moved(self):
        """Issue 554 row 4."""
        self.refused("base_moved: " + "6" * 40, base_tip="6" * 40)

    def test_a_guard_denial_is_authorization_denied(self):
        """Issue 554 row 5."""
        self.world.invoke_ready(guard_exit=2)
        self.world.merge_ready()
        result = self.merge()
        self.assertEqual((result["result"], result["error_class"]), ("rejected", "authorization_denied"))
        self.assertEqual((len(self.guards()), self.merges()), (1, []))

    def test_any_failed_merge_is_unknown_without_parsing_stderr(self):
        """Issue 554 D6."""
        for stderr in ("GraphQL: Head branch is out of date (mergePullRequest)", "HTTP 422: x", ""):
            with self.subTest(stderr=stderr):
                self.world.reset()
                self.world.invoke_ready()
                self.world.merge_ready(merge_exit=1, merge_stderr=stderr)
                result = self.merge()
                self.assertEqual((result["result"], result["error_class"]), ("unknown", "transient_transport"))
                self.assertEqual(len(self.merges()), 1)
        self.world.reset()
        self.world.invoke_ready()
        self.world.merge_ready(merge_sleep=6)
        saved = forge_adapter.CHILD_TIMEOUT_SECONDS
        forge_adapter.CHILD_TIMEOUT_SECONDS = 2
        try:
            result = self.merge()
        finally:
            forge_adapter.CHILD_TIMEOUT_SECONDS = saved
        self.assertEqual((result["result"], result["error_class"]), ("unknown", "transient_transport"))

    def test_an_unspawnable_merge_is_rejected(self):
        self.world.merge_ready()
        real = subprocess.run

        def run(argv, *args, **kwargs):
            if argv[:3] == ["gh", "pr", "merge"]:
                raise PermissionError(13, "Permission denied", argv[0])
            return real(argv, *args, **kwargs)
        with mock.patch.object(forge_adapter.subprocess, "run", side_effect=run):
            result = self.merge()
        self.assertEqual((result["result"], result["error_class"]), ("rejected", "provider_unavailable"))

    def test_a_malformed_merge_or_another_repository_refuses_early(self):
        for candidate in (CANDIDATE, {**CANDIDATE, "merge": {**MERGE, "pr": 0}}):
            with self.subTest(candidate=candidate):
                self.world.reset()
                result = self.merge(candidate)
                self.assertEqual((result["result"], result["error_class"]), ("rejected", "invalid_input"))
                self.assertEqual(self.world.calls(), [])
        self.world.reset()
        self.world.invoke_ready(slug="someone-else/nix-config")
        self.world.merge_ready()
        self.assertEqual(self.merge()["error_class"], "precondition_failed")
        self.assertNotIn(ROWS["pr_merge.protection"]["argv"][1:], self.world.argvs("gh"))

class MergedTagTest(InvokeCase):
    """Issue 554 D8: with a merge binding, tag and release target the release PR's merge commit."""

    def landed(self, state="MERGED", parents=(C["base_tip"], C["commit"])):
        self.world.respond_json("gh", ROWS["pr_merge.view"]["argv"][1:], {
            "state": state, "baseRefName": C["branch"], "headRefName": "dev", "headRefOid": C["commit"],
            "mergeCommit": {"oid": C["merge_commit"]} if state == "MERGED" else None,
            "url": f"https://github.com/{C['slug']}/pull/{C['pr']}", "statusCheckRollup": []})
        self.world.respond_json("gh", ROWS["pr_merge.merge_commit"]["argv"][1:],
                                {"parents": [{"sha": sha} for sha in parents]})

    def tag_at(self, peeled):
        self.tag_ref()
        self.tag_object(peeled=peeled)

    def test_tag_inspect_compares_the_tag_with_the_merge_commit(self):
        self.landed()
        self.tag_at(C["merge_commit"])
        observation = self.inspect(effect("tag", candidate=MERGE_CANDIDATE))
        self.assertEqual((observation["outcome"], observation["observed_subject"]["commit"]),
                         ("satisfied", C["merge_commit"]))
        self.assertEqual(self.world.argvs("gh"), [ROWS[i]["argv"][1:] for i in (
            "tag.ref", "tag.object", "pr_merge.view", "pr_merge.merge_commit")])

    def test_a_tag_at_the_integration_tip_is_diverged(self):
        """Issue 554 row 14."""
        self.landed()
        self.tag_at(C["commit"])
        observation = self.inspect(effect("tag", candidate=MERGE_CANDIDATE))
        self.assertEqual((observation["outcome"], observation["reason"]), ("diverged", "tag_target_mismatch"))

    def test_an_unresolvable_released_commit_never_satisfies(self):
        for state, parents in (("OPEN", ()), ("MERGED", ("6" * 40, C["commit"]))):
            with self.subTest(state=state, parents=parents):
                self.world.reset()
                self.landed(state, parents)
                self.tag_at(C["merge_commit"])
                observation = self.inspect(effect("tag", candidate=MERGE_CANDIDATE))
                self.assertEqual((observation["outcome"], observation["reason"]),
                                 ("diverged", "tag_target_mismatch"))
        self.world.reset()
        self.world.not_found("gh", ROWS["tag.ref"]["argv"][1:])
        self.assertEqual(self.inspect(effect("tag", candidate=MERGE_CANDIDATE))["reason"], "tag_absent")
        self.assertEqual(self.world.argvs("gh"), [ROWS["tag.ref"]["argv"][1:]])

    def test_release_inspect_and_its_predicate_follow_the_merge_commit(self):
        self.landed()
        self.tag_at(C["merge_commit"])
        self.world.respond_json("gh", ROWS["release.view"]["argv"][1:], {
            "tag_name": C["tag"], "draft": False, "html_url": "u"})
        parameters = {"target": TARGET, "candidate": MERGE_CANDIDATE, "title": C["title"], "notes": "n"}
        self.assertEqual(self.inspect({"kind": "effect", "operation": "release",
                                       "parameters": parameters})["outcome"], "satisfied")
        predicate = forge_adapter.inspect({"kind": "predicate", "predicate": "publication_visible",
                                           "operation": "release", "parameters": parameters})
        self.assertEqual((predicate["outcome"], predicate["reason"]), ("satisfied", "observed"))

    def test_tag_invoke_tags_and_pushes_the_merge_commit(self):
        self.world.invoke_ready()
        self.landed()
        self.assertEqual(self.invoke("tag", candidate=MERGE_CANDIDATE)["result"], "accepted")
        git = [c["argv"] for c in self.world.calls() if c["tool"] == "git"]
        fetch = ["fetch", "--no-tags", "origin", "refs/heads/main"]
        tag = ["tag", "-a", C["tag"], C["merge_commit"], "-m", f"release: {C['tag']}"]
        self.assertLess(git.index(fetch), git.index(tag))
        self.assertIn(ROWS["tag.merged_compare"]["argv"][1:], self.world.argvs("gh"))
        self.assertNotIn(ROWS["tag.compare"]["argv"][1:], self.world.argvs("gh"))
        self.assertEqual(["git", *self.mutations()[0]["argv"]], ROWS["tag.push"]["argv"])

    def test_tag_invoke_refuses_before_the_pr_merged(self):
        """Issue 554 row 13."""
        self.world.invoke_ready()
        self.landed("OPEN")
        self.assertEqual(self.invoke("tag", candidate=MERGE_CANDIDATE),
                         {"result": "rejected", "error_class": "precondition_failed",
                          "reference": "release PR not merged as bound"})
        self.assertEqual(self.mutations(), [])
        self.assertFalse(any(c["tool"] == "claude-bash-lifecycle-guard" for c in self.world.calls()))

    def test_a_failed_fetch_or_uncontained_merge_refuses_with_no_push(self):
        for ready, error_class in ((dict(fetch_exit=1), "provider_unavailable"),
                                   (dict(merged_compare="diverged"), "precondition_failed")):
            with self.subTest(ready=ready):
                self.world.reset()
                self.world.invoke_ready(**ready)
                self.landed()
                result = self.invoke("tag", candidate=MERGE_CANDIDATE)
                self.assertEqual((result["result"], result["error_class"]), ("rejected", error_class))
                self.assertEqual(self.mutations(), [])

    def test_an_unreadable_pull_request_is_unknown_to_inspect_and_unavailable_to_invoke(self):
        self.tag_at(C["merge_commit"])
        self.landed("REOPENED")
        observation = self.inspect(effect("tag", candidate=MERGE_CANDIDATE))
        self.assertEqual((observation["outcome"], observation["reason"]), ("unknown", "payload_invalid"))
        self.world.reset()
        self.world.invoke_ready()
        result = self.invoke("tag", candidate=MERGE_CANDIDATE)
        self.assertEqual((result["result"], result["error_class"]), ("rejected", "provider_unavailable"))
        self.assertEqual(self.mutations(), [])


SYNC = FIXTURE["sync"]["canonical"]
SYNC_ROWS = forge_world.SYNC_ROWS
SYNC_PARAMETERS = {"target": TARGET, "candidate": MERGE_CANDIDATE, "integration": SYNC["integration"]}


class SyncCase(InvokeCase):
    """Issue 845: the two post-release sync operations, over a merged release pull request."""

    def setUp(self):
        super().setUp()
        self.ready()

    def ready(self, state="MERGED", **sync):
        self.world.reset()
        self.world.invoke_ready()
        MergedTagTest.landed(self, state)
        self.world.sync_ready(**sync)

    def observe(self, operation, **parameters):
        return self.inspect({"kind": "effect", "operation": operation,
                             "parameters": {**SYNC_PARAMETERS, **parameters}})

    def sync(self, operation, **parameters):
        result = forge_adapter.invoke({"kind": "effect", "operation": operation,
                                       "parameters": {**SYNC_PARAMETERS, **parameters}})
        self.assertEqual(release_adapter.invoke_result_problems(result), [])
        return result

    def git(self):
        return [c["argv"] for c in self.world.calls() if c["tool"] == "git"]

    def guards(self):
        return [json.loads(c["stdin"])["tool_input"]["command"] for c in self.world.calls()
                if c["tool"] == "claude-bash-lifecycle-guard"]

    def creates(self):
        return [c["argv"] for c in self.world.calls() if c["tool"] == "gh" and c["argv"][:2] == ["pr", "create"]]


class SyncInspectTest(SyncCase):
    def test_no_profile_can_bind_a_sync_operation(self):
        """The descriptor, whose digest pins every profile, is unchanged by the sync."""
        self.assertEqual(sorted(forge_adapter.describe()["operations"]), ["pr_merge", "release", "tag"])

    def test_the_branch_is_absent_satisfied_or_elsewhere(self):
        observation = self.observe("sync_branch")
        self.assertEqual((observation["outcome"], observation["reason"]), ("absent", "branch_absent"))
        self.assertEqual(self.world.argvs("gh"), [ROWS["pr_merge.view"]["argv"][1:],
                                                  ROWS["pr_merge.merge_commit"]["argv"][1:],
                                                  SYNC_ROWS["sync.contained"]["argv"][1:],
                                                  SYNC_ROWS["sync_branch.ref"]["argv"][1:]])
        self.ready(branch_tip=C["merge_commit"])
        observation = self.observe("sync_branch")
        self.assertEqual((observation["outcome"], observation["reason"], observation["observed_subject"]),
                         ("satisfied", "observed", {"branch": SYNC["branch"], "commit": C["merge_commit"]}))
        self.assertNotIn(SYNC_ROWS["sync_branch.compare"]["argv"][1:], self.world.argvs("gh"))
        for compare, outcome, reason in (("ahead", "satisfied", "observed"),
                                         ("diverged", "diverged", "branch_elsewhere"),
                                         ("behind", "diverged", "branch_elsewhere")):
            with self.subTest(compare=compare):
                self.ready(branch_tip="7" * 40, branch_compare=compare)
                observation = self.observe("sync_branch")
                self.assertEqual((observation["outcome"], observation["reason"]), (outcome, reason))

    def test_an_integration_branch_that_holds_the_merge_commit_is_a_no_op_for_both(self):
        for contained in ("identical", "ahead"):
            for operation in ("sync_branch", "sync_pr"):
                with self.subTest(contained=contained, operation=operation):
                    self.ready(contained=contained)
                    observation = self.observe(operation)
                    self.assertEqual((observation["outcome"], observation["reason"]),
                                     ("satisfied", "already_contained"))
                    self.assertEqual(self.world.argvs("gh")[-1], SYNC_ROWS["sync.contained"]["argv"][1:])

    def test_one_open_or_merged_pull_request_satisfies(self):
        pull = forge_world.sync_pull
        merged = pull(state="closed", merged_at="2026-11-11T10:00:00Z")
        closed = pull(number=300, state="closed")
        for prs, outcome, reason, number in (
                ([], "absent", "pr_absent", None), ([closed], "absent", "pr_absent", None),
                ([pull()], "satisfied", "observed", SYNC["pr"]),
                ([closed, merged], "satisfied", "observed", SYNC["pr"]),
                ([pull(), pull(number=338)], "diverged", "pr_ambiguous", None)):
            with self.subTest(prs=prs):
                self.ready(branch_tip=C["merge_commit"], prs=prs)
                observation = self.observe("sync_pr")
                self.assertEqual((observation["outcome"], observation["reason"],
                                  observation["observed_subject"]["pr"]), (outcome, reason, number))
        self.ready(prs=[pull()])
        self.assertEqual(self.observe("sync_pr")["references"],
                         [forge_world.SYNC_URL, SYNC_ROWS["sync_pr.list"]["argv"][2]])

    def test_a_release_pr_not_merged_as_bound_never_satisfies(self):
        self.ready("OPEN", contained="identical")
        for operation in ("sync_branch", "sync_pr"):
            observation = self.observe(operation)
            self.assertEqual((observation["outcome"], observation["reason"]),
                             ("diverged", "release_not_merged"))

    def test_an_unreadable_world_is_unknown_and_bad_parameters_make_no_call(self):
        self.world.reset()
        MergedTagTest.landed(self)
        self.assertEqual(self.observe("sync_branch")["outcome"], "unknown")
        self.assertEqual(self.observe("sync_pr")["outcome"], "unknown")
        self.world.reset()
        for parameters in ({"integration": C["branch"]}, {"integration": "a..b"}, {"integration": 7},
                           {"candidate": CANDIDATE}):
            for operation in ("sync_branch", "sync_pr"):
                with self.subTest(parameters=parameters, operation=operation):
                    observation = self.observe(operation, **parameters)
                    self.assertEqual((observation["outcome"], observation["reason"]),
                                     ("unknown", "parameters_invalid"))
                    result = self.sync(operation, **parameters)
                    self.assertEqual((result["result"], result["error_class"]), ("rejected", "invalid_input"))
        missing = forge_adapter.inspect({"kind": "effect", "operation": "sync_pr",
                                         "parameters": {"target": TARGET, "candidate": MERGE_CANDIDATE}})
        self.assertEqual(missing["reason"], "parameters_invalid")
        self.assertEqual(self.world.calls(), [])


class SyncInvokeTest(SyncCase):
    BRANCH = ["branch", "--no-track", SYNC["branch"], C["merge_commit"]]

    def test_the_branch_is_created_at_the_merge_commit_and_pushed_through_the_guard(self):
        self.assertEqual(self.sync("sync_branch"), {"result": "accepted", "error_class": None,
                                                    "reference": f"refs/heads/{SYNC['branch']}"})
        git = self.git()
        fetch = ["fetch", "--no-tags", "origin", "refs/heads/main"]
        push = SYNC_ROWS["sync_branch.push"]["argv"][1:]
        self.assertLess(git.index(fetch), git.index(self.BRANCH))
        self.assertLess(git.index(self.BRANCH), git.index(push))
        self.assertEqual(self.guards(), [SYNC_ROWS["sync_branch.push"]["raw"]])
        self.assertEqual(self.world.calls()[-1]["argv"], push)
        self.assertFalse(any(c["token_visible"] for c in self.world.calls()))

    def test_a_local_branch_left_by_an_earlier_attempt_is_reused_or_refused(self):
        self.ready(local_branch=C["merge_commit"])
        self.assertEqual(self.sync("sync_branch")["result"], "accepted")
        self.assertNotIn(self.BRANCH, self.git())
        self.assertEqual(len(self.mutations()), 1)
        self.ready(local_branch="7" * 40)
        self.assertEqual(self.sync("sync_branch"), {
            "result": "rejected", "error_class": "precondition_failed",
            "reference": f"local branch {SYNC['branch']} is not at {C['merge_commit']}"})
        self.assertEqual((self.guards(), self.mutations()), ([], []))

    def test_each_branch_refusal_stops_before_the_push(self):
        for state, ready, error_class in (("OPEN", {}, "precondition_failed"),
                                          ("MERGED", dict(branch_exit=1), "provider_unavailable")):
            with self.subTest(state=state, ready=ready):
                self.ready(state, **ready)
                result = self.sync("sync_branch")
                self.assertEqual((result["result"], result["error_class"]), ("rejected", error_class))
                self.assertEqual((self.guards(), self.mutations()), ([], []))
        self.world.reset()
        self.world.invoke_ready(guard_exit=1)
        MergedTagTest.landed(self)
        self.world.sync_ready()
        result = self.sync("sync_branch")
        self.assertEqual((result["result"], result["error_class"]), ("rejected", "authorization_denied"))
        self.assertEqual(self.mutations(), [])

    def test_a_failed_push_or_create_is_unknown(self):
        self.ready(push_exit=1, push_stderr="! [rejected] (non-fast-forward)")
        result = self.sync("sync_branch")
        self.assertEqual((result["result"], result["error_class"]), ("unknown", "transient_transport"))
        self.ready(branch_tip=C["merge_commit"], create_exit=1, create_stdout="",
                   create_stderr="a pull request for branch already exists")
        result = self.sync("sync_pr")
        self.assertEqual((result["result"], result["error_class"]), ("unknown", "transient_transport"))

    def test_the_pull_request_is_opened_into_the_integration_branch_through_the_guard(self):
        self.ready(branch_tip=C["merge_commit"])
        self.assertEqual(self.sync("sync_pr"), {"result": "accepted", "error_class": None,
                                                "reference": forge_world.SYNC_URL})
        self.assertEqual(self.creates(), [SYNC_ROWS["sync_pr.create"]["argv"][1:]])
        self.assertEqual(self.guards(), [SYNC_ROWS["sync_pr.create"]["raw"]])
        self.assertEqual(self.mutations(), [])
        self.assertFalse(any(argv[:2] == ["pr", "merge"] for argv in self.world.argvs("gh")))

    def test_no_pull_request_is_opened_without_the_pushed_branch(self):
        result = self.sync("sync_pr")
        self.assertEqual(result, {"result": "rejected", "error_class": "precondition_failed",
                                  "reference": "sync_branch_absent"})
        self.assertEqual((self.guards(), self.creates()), ([], []))


if __name__ == "__main__":
    unittest.main()
