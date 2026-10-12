"""The guard-policy compiler at its command seam (issue 126 D10, D15).

Every case runs `python -m agent_tools.guard_policy compile` over `GuardPolicyWorld` and
asserts on the exit status, the report and the written file. Two suites call an imported
function instead, each for a check no command input reaches: `TargetProfilesTest`, because
the release grammar refuses a foreign forge target before the compiler sees it, and
`UnsupportedNameTest` for the repository slug, because `github_remote.github_slug` already
reads no slug the guard's loader would refuse.
"""
import json
import shutil
import unittest

from agent_tools import guard_policy
from . import release_test_support as support
from .guard_policy_world import GuardPolicyWorld

NODO = "elevenyellow/nodocom"
ROW_MEMBERS = {"default_branch", "integration_branch", "evidence"}
EVIDENCE_MEMBERS = {"project_id", "registry_entry_digest", "source", "contract_blob",
                    "provider_full_name", "profiles"}


class WorldCase(unittest.TestCase):
    def setUp(self) -> None:
        self.world = GuardPolicyWorld(self)

    def refused(self, reason_code: str, project_id: str = "fixture/one") -> dict:
        """Compile, expect exit 1 with exactly one refusal for `project_id`, and return it."""
        code, report, err = self.world.compile()
        self.assertEqual((code, report["outcome"]), (1, "written_with_refusals"), report)
        [refusal] = [r for r in report["refused"] if r["project_id"] == project_id]
        self.assertEqual(refusal["reason_code"], reason_code, refusal)
        self.assertEqual(set(refusal), {"project_id", "root", "reason_code", "detail"})
        self.assertLessEqual(len(refusal["detail"]), 240)
        self.assertIn(f"{project_id} ", err)
        self.assertIn(reason_code, err)
        self.assertNotIn(project_id, json.dumps(self.world.policy()["derived_repositories"]))
        return refusal


class DerivationTest(WorldCase):
    def test_a_nodo_shaped_and_a_single_branch_project_both_derive(self):
        single = self.world.project("fixture/single", "fagenorn/single")
        nodo = self.world.project("nodocom", NODO, integration_branch="dev",
                                  publication_free=True, override=True)
        code, report, err = self.world.compile()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(report, {"schema_version": 1, "outcome": "complete", "cause": None,
                                  "derived": [NODO, "fagenorn/single"], "refused": []})
        policy = self.world.policy()
        self.assertEqual(set(policy), {"derived_repositories", "derivation"})
        self.assertEqual(set(guard_policy.POLICY_MEMBERS), set(policy))
        rows = policy["derived_repositories"]
        self.assertEqual(sorted(rows), [NODO, "fagenorn/single"])
        for row in rows.values():
            self.assertEqual(set(row), ROW_MEMBERS)
            self.assertEqual(set(row["evidence"]), EVIDENCE_MEMBERS)
        self.assertEqual((rows[NODO]["default_branch"], rows[NODO]["integration_branch"]),
                         ("main", "dev"))
        self.assertEqual((rows["fagenorn/single"]["default_branch"],
                          rows["fagenorn/single"]["integration_branch"]), ("main", "main"))
        evidence = rows[NODO]["evidence"]
        self.assertEqual(evidence["project_id"], "nodocom")
        self.assertEqual(evidence["source"], {
            "ref": "refs/remotes/origin/dev",
            "commit": self.world.git(nodo, "rev-parse", "dev").strip()})
        self.assertEqual(evidence["contract_blob"],
                         self.world.git(nodo, "rev-parse", "dev:.agents/project.json").strip())
        self.assertEqual(evidence["provider_full_name"], NODO)
        [profile] = evidence["profiles"]
        self.assertEqual((profile["id"], profile["version"]), ("forge-main", 1))
        self.assertRegex(profile["digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(evidence["registry_entry_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(rows["fagenorn/single"]["evidence"]["source"]["commit"],
                         self.world.git(single, "rev-parse", "main").strip())
        derivation = policy["derivation"]
        self.assertEqual(set(derivation),
                         {"schema_version", "platform_version", "registry_digest"})
        self.assertEqual(derivation["schema_version"], 2)
        self.assertRegex(derivation["registry_digest"], r"^sha256:[0-9a-f]{64}$")
        # D11: identity evidence only, never the contract or a resolved snapshot.
        text = self.world.output.read_text("utf-8")
        for leaked in ("branch_pattern", "repo_slug", "capabilities", str(self.world.home)):
            self.assertNotIn(leaked, text)

    def test_an_absent_registry_is_the_empty_fleet(self):
        code, report, _ = self.world.compile()
        self.assertEqual((code, report["outcome"], report["derived"]), (0, "complete", []))
        policy = self.world.policy()
        self.assertEqual(policy["derived_repositories"], {})
        self.assertEqual(set(policy), {"derived_repositories", "derivation"})
        self.assertIsNone(policy["derivation"]["registry_digest"])

    def test_the_contract_is_read_from_origin_and_the_checkout_is_left_alone(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        published = self.world.git(root, "rev-parse", "main")
        # A local branch, a moved remote-tracking ref and a dirty tree, none of them origin's.
        self.world.git(root, "checkout", "--quiet", "-b", "local-work")
        (root / ".agents/project.json").write_text("not json", "utf-8")
        self.world.git(root, "commit", "--quiet", "-am", "local only")
        self.world.git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
        (root / "untracked.txt").write_text("dirty", "utf-8")
        before = (self.world.git(root, "status", "--porcelain"),
                  self.world.git(root, "rev-parse", "HEAD"),
                  self.world.git(root, "for-each-ref", "refs/heads"))
        code, report, _ = self.world.compile()
        self.assertEqual((code, report["derived"]), (0, ["fagenorn/one"]))
        self.assertEqual(before, (self.world.git(root, "status", "--porcelain"),
                                  self.world.git(root, "rev-parse", "HEAD"),
                                  self.world.git(root, "for-each-ref", "refs/heads")))
        self.assertFalse((root / ".git/FETCH_HEAD").exists())
        self.assertEqual(self.world.git(root, "rev-parse", "refs/remotes/origin/main"), published)

    def test_a_refused_project_loses_its_stale_row(self):
        self.world.project("fixture/one", "fagenorn/one")
        self.world.project("fixture/two", "fagenorn/two")
        self.assertEqual(self.world.compile()[0], 0)
        self.assertIn("fagenorn/one", self.world.policy()["derived_repositories"])
        self.world.provider("fagenorn/one", exit=1)
        self.refused("provider_unproven")
        self.assertEqual(sorted(self.world.policy()["derived_repositories"]), ["fagenorn/two"])


REPORT_MEMBERS = {"schema_version", "repository", "outcome", "row", "refused", "cause"}


class DeriveTest(WorldCase):
    """`guard-policy derive --repository <slug>`: the row check the guard runs (issue 377 D2)."""

    def derived(self, repository: str) -> dict:
        code, report, err = self.world.derive(repository)
        self.assertEqual((code, set(report)), (0, REPORT_MEMBERS), (report, err))
        self.assertEqual((report["schema_version"], report["repository"], report["outcome"],
                          report["cause"]), (1, repository, "derived", None))
        return report

    def refused_for(self, repository: str) -> dict:
        code, report, err = self.world.derive(repository)
        self.assertEqual((code, set(report)), (1, REPORT_MEMBERS), (report, err))
        self.assertEqual((report["repository"], report["outcome"], report["row"],
                          report["cause"]), (repository, "refused", None, None))
        return report

    def test_a_registered_slug_derives_the_row_compile_writes(self):
        self.world.project("nodocom", NODO, integration_branch="dev", publication_free=True,
                           override=True)
        self.world.project("fixture/single", "fagenorn/single")
        report = self.derived(NODO)
        self.assertEqual(report["refused"], [])
        self.assertEqual((report["row"]["default_branch"], report["row"]["integration_branch"]),
                         ("main", "dev"))
        self.assertEqual(self.world.compile()[0], 0)
        self.assertEqual(report["row"], self.world.policy()["derived_repositories"][NODO])
        self.assertEqual(self.derived("fagenorn/single")["row"]["integration_branch"], "main")

    def test_an_unregistered_slug_is_refused_with_an_empty_list(self):
        self.world.project("fixture/one", "fagenorn/one")
        self.assertEqual(self.refused_for("acme/forged")["refused"], [])

    def test_an_absent_registry_refuses_every_slug(self):
        self.assertEqual(self.refused_for(NODO)["refused"], [])

    def test_a_failing_proof_is_refused_with_its_code(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        self.world.provider("fagenorn/one", exit=1)
        code, report, err = self.world.derive("fagenorn/one")
        self.assertEqual(code, 1, report)
        [refusal] = report["refused"]
        self.assertEqual((refusal["project_id"], refusal["root"], refusal["reason_code"]),
                         ("fixture/one", str(root), "provider_unproven"))
        self.assertIn("fixture/one ", err)

    def test_two_entries_on_one_slug_are_duplicate_repository(self):
        self.world.project("fixture/one", "fagenorn/one")
        self.world.project("fixture/two", "fagenorn/one")
        report = self.refused_for("fagenorn/one")
        self.assertEqual([(r["project_id"], r["reason_code"]) for r in report["refused"]],
                         [("fixture/one", "duplicate_repository"),
                          ("fixture/two", "duplicate_repository")])

    def test_a_name_the_guard_does_not_load_is_refused(self):
        self.world.project("fixture/one", "fagenorn/one", integration_branch="dev+ci")
        [refusal] = self.refused_for("fagenorn/one")["refused"]
        self.assertEqual(refusal["reason_code"], "name_unsupported")

    def test_a_literal_integration_base_is_not_derive_s_concern(self):
        """Step 12 needs the base policy, which derive never reads."""
        self.world.write_base(integration_bases={"fagenorn/one": "dev"})
        self.world.project("fixture/one", "fagenorn/one")
        self.assertEqual(self.derived("fagenorn/one")["refused"], [])

    def test_an_entry_naming_another_slug_is_never_fetched(self):
        self.world.project("fixture/one", "fagenorn/one")
        other = self.world.project("fixture/two", "fagenorn/two")
        self.world.git(other, "update-ref", "-d", "refs/remotes/origin/main")
        self.assertEqual(self.world.git(other, "for-each-ref", "refs/remotes/origin"), "")
        self.derived("fagenorn/one")
        self.assertEqual(self.world.git(other, "for-each-ref", "refs/remotes/origin"), "")

    def test_an_unusable_registry_or_manifest_is_unavailable(self):
        self.world.project("fixture/one", "fagenorn/one")
        self.world.write_registry("{")
        code, report, err = self.world.derive("fagenorn/one")
        self.assertEqual((code, report["outcome"], report["row"], report["refused"]),
                         (2, "unavailable", None, []), report)
        self.assertEqual(report["cause"]["reason_code"], "registry_invalid")
        self.assertIn("registry_invalid", err)
        self.world.register()
        (self.world.home / ".agents/share/platform-manifest.json").unlink()
        code, report, _ = self.world.derive("fagenorn/one")
        self.assertEqual((code, report["cause"]["reason_code"]), (2, "platform_unavailable"))


class ProjectRefusalTest(WorldCase):
    def test_root_unavailable(self):
        plain = self.world.tmp / "plain"
        plain.mkdir()
        self.world.register({"project_id": "fixture/one", "root": str(plain)},
                            {"project_id": "fixture/gone", "root": str(self.world.tmp / "gone")})
        self.refused("root_unavailable")
        self.refused("root_unavailable", "fixture/gone")

    def test_origin_unproven(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        url = "git@github.com:fagenorn/one.git"
        for origin, pushes in (
                ("git@gitlab.com:fagenorn/one.git", None),          # not github.com
                ("https://github.com.evil.example/fagenorn/one", None),
                (url, [url, url]),                                    # two push urls
                (url, []),                                            # no push url
                (url, ["git@github.com:fagenorn/elsewhere.git"]),     # push differs from fetch
        ):
            with self.subTest(origin=origin, pushes=pushes):
                self.world.identity(root, origin, pushes)
                self.refused("origin_unproven")
        self.world.identity(root, None)  # the real origin is a local path
        self.refused("origin_unproven")

    def test_branch_unresolved(self):
        self.world.project("fixture/one", "fagenorn/one", integration_branch="dev",
                           override=True)
        self.world.entries[0]["branch_override"]["branch"] = "gone"
        self.world.register()
        self.refused("branch_unresolved")

    def test_fetch_failed(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        shutil.rmtree(self.world.git(root, "remote", "get-url", "origin").strip())
        self.refused("fetch_failed")

    def test_contract_unresolved(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        broken = self.world.contract("fixture/one", "fagenorn/one")
        del broken["release"]
        self.world.commit_contract(root, broken, "an invalid contract", render=False)
        self.world.publish(root, ["main"])
        self.refused("contract_unresolved")

    def test_identity_mismatch(self):
        root = self.world.project("fixture/actual", "fagenorn/one", register=False)
        self.world.register({"project_id": "fixture/one", "root": str(root)})
        self.refused("identity_mismatch")

    def test_tracker_mismatch(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        for slug in ("fagenorn/elsewhere", "Fagenorn/One"):  # no case folding
            with self.subTest(origin=slug):
                self.world.identity(root, f"git@github.com:{slug}.git")
                self.world.provider(slug)
                self.refused("tracker_mismatch")

    def test_no_forge_target(self):
        def unsupported(contract: dict) -> None:
            contract["release"] = "unsupported"
        self.world.project("fixture/one", "fagenorn/one", mutate=unsupported)
        self.refused("no_forge_target")

    def test_profile_inadmissible(self):
        def inadmissible(contract: dict) -> None:
            contract["release"] = support.release_of(
                "github-release", support.missing_deadline_profile())
        self.world.project("fixture/one", "fagenorn/nix-config", mutate=inadmissible)
        self.refused("profile_inadmissible")

    def test_branch_mismatch(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        self.world.git(root, "branch", "trunk")
        self.world.publish(root, ["main", "trunk"], default="trunk")
        self.refused("branch_mismatch")

    def test_provider_unproven(self):
        self.world.project("fixture/one", "fagenorn/one")
        for answer in ({"full_name": "fagenorn/renamed"}, {"exit": 1}):
            with self.subTest(answer=answer):
                self.world.provider("fagenorn/one", **answer)
                self.refused("provider_unproven")

    def test_provider_unproven_says_what_the_provider_did(self):
        self.world.project("fixture/one", "fagenorn/one")
        self.world.provider("fagenorn/one", "fagenorn/renamed")
        self.assertIn("'fagenorn/renamed'", self.refused("provider_unproven")["detail"])
        self.world.provider("fagenorn/one", exit=1)
        self.assertIn("exit 1", self.refused("provider_unproven")["detail"])
        del self.world.providers["repos/fagenorn/one"]  # the shim then exits 64 on stderr
        self.world._save()
        self.assertIn("exit 64: fake gh: unregistered call",
                      self.refused("provider_unproven")["detail"])

    def test_origin_unproven_says_which_read_failed(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        self.world.git(root, "remote", "remove", "origin")
        self.world.identity(root, None)  # the real git now answers, and has no origin
        detail = self.refused("origin_unproven")["detail"]
        self.assertIn("fetch: exit 2", detail)
        self.assertIn("No such remote", detail)

    def test_duplicate_repository_refuses_both(self):
        self.world.project("fixture/one", "fagenorn/one")
        self.world.project("fixture/two", "fagenorn/one")
        self.world.project("fixture/three", "fagenorn/three")
        self.refused("duplicate_repository")
        self.refused("duplicate_repository", "fixture/two")
        self.assertEqual(sorted(self.world.policy()["derived_repositories"]), ["fagenorn/three"])

    def test_literal_conflict_withholds_the_derived_row_only(self):
        """Issue 377 D5: the compiled policy cannot subtract a store literal."""
        self.world.write_base(integration_bases={"fagenorn/one": "dev",
                                                 "fagenorn/arcwave": "dev"})
        self.world.project("fixture/one", "fagenorn/one")
        self.refused("literal_conflict")
        self.assertEqual(self.world.policy()["derived_repositories"], {})
        self.assertNotIn("integration_bases", self.world.policy())

    def test_name_unsupported_integration_branch(self):
        """Git and the contract take `dev+ci`; the guard's loader drops the whole compiled policy."""
        self.world.project("fixture/one", "fagenorn/one", integration_branch="dev+ci")
        self.world.project("fixture/two", "fagenorn/two")
        self.assertIn("integration_branch 'dev+ci'", self.refused("name_unsupported")["detail"])
        self.assertEqual(sorted(self.world.policy()["derived_repositories"]), ["fagenorn/two"])

    def test_name_unsupported_default_branch(self):
        def trunk(contract: dict) -> None:
            contract["bindings"]["vcs"].update(default_branch="rel+1", integration_branch="rel+1")
            target = contract["release"]["profiles"]["forge-main"]["bindings"]["targets"]
            target["repository"]["branch"] = "rel+1"
        root = self.world.project("fixture/one", "fagenorn/one", publication_free=True,
                                  mutate=trunk)
        self.world.git(root, "branch", "rel+1")
        self.world.publish(root, ["rel+1"], default="rel+1")
        self.world.project("fixture/two", "fagenorn/two")
        self.assertIn("default_branch 'rel+1'", self.refused("name_unsupported")["detail"])
        self.assertEqual(sorted(self.world.policy()["derived_repositories"]), ["fagenorn/two"])

    def test_literal_conflict_is_judged_before_the_name(self):
        self.world.write_base(integration_bases={"fagenorn/one": "dev"})
        self.world.project("fixture/one", "fagenorn/one", integration_branch="dev+ci")
        self.refused("literal_conflict")


class UnsupportedNameTest(unittest.TestCase):
    """The loader's three names, on a hand-built row: what `unsupported_name` reports."""

    @staticmethod
    def row(default_branch: str = "main", integration_branch: str = "dev") -> dict:
        return {"default_branch": default_branch, "integration_branch": integration_branch,
                "evidence": {}}

    def test_the_names_the_guard_loads_are_supported(self):
        for slug, row in (("fagenorn/one", self.row()),
                          ("Acme-1/tool_2.x", self.row("release/1.x_y-z", "feature/a.b"))):
            with self.subTest(slug=slug):
                self.assertIsNone(guard_policy.unsupported_name(slug, row))

    def test_each_name_outside_the_loader_s_shapes_is_reported(self):
        for slug, row, named in (
                ("fagenorn/one+two", self.row(), "repository 'fagenorn/one+two'"),
                ("fagenorn/one/two", self.row(), "repository 'fagenorn/one/two'"),
                ("fagenorn", self.row(), "repository 'fagenorn'"),
                ("fagenorn/one", self.row("rel+1"), "default_branch 'rel+1'"),
                ("fagenorn/one", self.row("main", "dev+ci"), "integration_branch 'dev+ci'"),
                ("fagenorn/one", self.row("main", "dev ci"), "integration_branch 'dev ci'"),
                ("fagenorn/one", self.row("main", "dev\n"), "integration_branch 'dev\\n'"),
        ):
            with self.subTest(slug=slug, row=row):
                self.assertIn(named, guard_policy.unsupported_name(slug, row))


class TargetProfilesTest(unittest.TestCase):
    """Step 8 below the grammar (D15): the members `target_profiles` reads, built by hand."""

    SLUG = "fagenorn/one"
    ENTRY = {"project_id": "fixture/one", "root": "/nonexistent"}

    def snapshot(self, **target: str) -> dict:
        return {"project": {"id": "fixture/one"},
                "bindings": {"vcs": {"default_branch": "main"},
                             "tracker": {"kind": "github", "repo_slug": self.SLUG}},
                "release": {"targets": [
                    {"profile": "forge-main", "adapter": "github-forge", "operations": [],
                     "target": {"handle": "repository", "kind": "github_repository",
                                "repository": self.SLUG, "branch": "main", **target}}]}}

    def test_a_target_for_this_repository_selects_its_profile(self):
        self.assertEqual(guard_policy.target_profiles(self.ENTRY, self.SLUG, self.snapshot()),
                         ["forge-main"])

    def test_a_target_for_another_repository_or_branch_is_refused(self):
        for target in ({"repository": "fagenorn/elsewhere"}, {"branch": "dev"}):
            with self.subTest(target=target):
                with self.assertRaises(guard_policy.ProjectRefused) as caught:
                    guard_policy.target_profiles(self.ENTRY, self.SLUG, self.snapshot(**target))
                self.assertEqual(caught.exception.reason_code, "target_mismatch")


class WholeRefusalTest(WorldCase):
    def assert_refused(self, cause: str, **compile_arguments) -> None:
        output = compile_arguments.get("output", self.world.output)
        code, report, err = self.world.compile(**compile_arguments)
        self.assertEqual((code, report["outcome"]), (2, "refused"), report)
        self.assertEqual(report["cause"]["reason_code"], cause, report)
        self.assertEqual((report["derived"], report["refused"]), ([], []))
        self.assertIn(cause, err)
        self.assertFalse(output.exists())

    def previous_policy(self) -> None:
        """A policy file from an earlier, successful compile."""
        self.world.project("fixture/one", "fagenorn/one")
        self.assertEqual(self.world.compile()[0], 0)
        self.assertTrue(self.world.output.exists())

    def test_an_unusable_base_policy(self):
        self.previous_policy()
        valid = json.loads(self.world.base.read_text("utf-8"))
        cases = {
            "not json": "{",
            "a missing member": {k: v for k, v in valid.items() if k != "jq_bin"},
            "an extra member": {**valid, "extra": 1},
            "a compiled policy": {**valid, "derivation": {}},
            "a derived row": {**valid, "derived_repositories": {"a/b": {}}},
            "the #375 seven-member shape": {**valid, "derived_repositories": {},
                                            "derivation": None},
            "owners": {**valid, "authorized_owners": "fagenorn"},
            "bases": {**valid, "integration_bases": {"a/b": ""}},
            "a relative tool": {**valid, "git_bin": "git"},
        }
        for name, document in cases.items():
            with self.subTest(base=name):
                self.world.base.write_text(
                    document if isinstance(document, str) else json.dumps(document), "utf-8")
                self.assert_refused("base_invalid")
                self.world.write_base()
                self.assertEqual(self.world.compile()[0], 0)
        self.assert_refused("base_invalid", base=self.world.tmp / "absent.json")

    def test_a_registry_that_does_not_validate(self):
        self.previous_policy()
        for document in ("{", {"schema_version": 1}, {"schema_version": 1, "projects": [{}]}):
            with self.subTest(registry=document):
                self.world.write_registry(document)
                self.assert_refused("registry_invalid")
                self.world.register()
                self.assertEqual(self.world.compile()[0], 0)

    def test_a_missing_platform_manifest(self):
        self.previous_policy()
        (self.world.home / ".agents/share/platform-manifest.json").unlink()
        self.assert_refused("platform_unavailable")

    def test_an_output_that_cannot_be_written(self):
        blocker = self.world.tmp / "blocker"
        blocker.write_text("a file where a directory is needed", "utf-8")
        self.assert_refused("output_unwritable", output=blocker / "policy.json")


if __name__ == "__main__":
    unittest.main()
