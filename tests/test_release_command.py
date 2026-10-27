"""The release command: profile inspection (#124 spec §5). Run: just agent-workflow-tests"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .actions_world import CONFIG, MERGE, OLDER, ActionsWorld, run
from .forge_world import CANONICAL, ROWS, ForgeWorld

REPO = Path(__file__).resolve().parents[1]
PYTHON = REPO / "python"
SHARE = REPO / "home/common/agent-skills"

class ReleaseCommandCase(unittest.TestCase):
    """Runs `python -m agent_tools.release` against a temporary copy of this repository's
    contract under a temporary HOME holding the committed platform manifest, as the
    resolver suite's `install_home` does."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve() / "home"
        (self.home / ".agents/share").mkdir(parents=True)
        for name in ("platform-manifest.json", "host-declaration.json"):
            shutil.copy(SHARE / name, self.home / ".agents/share" / name)
        self.root = Path(tmp.name).resolve() / "project"
        (self.root / ".agents").mkdir(parents=True)
        shutil.copytree(REPO / ".agents/instructions", self.root / ".agents/instructions")
        for name in ("AGENTS.md", "CLAUDE.md"):
            shutil.copy(REPO / name, self.root / name)
        self.write_contract(json.loads((REPO / ".agents/project.json").read_text("utf-8")))
        subprocess.run(["git", "init", "--quiet"], cwd=self.root, check=True)

    def write_contract(self, contract):
        (self.root / ".agents/project.json").write_text(json.dumps(contract), encoding="utf-8")

    def contract(self):
        return json.loads((self.root / ".agents/project.json").read_text("utf-8"))

    def run_release(self, *args, env=None, repo_root=True):
        env = dict(os.environ, PYTHONPATH=str(PYTHON), HOME=str(self.home), **(env or {}))
        tail = ["--repo-root", str(self.root)] if repo_root else []
        result = subprocess.run([sys.executable, "-m", "agent_tools.release", *args, *tail],
                                capture_output=True, text=True, env=env, timeout=120)
        return result.returncode, json.loads(result.stdout), result.stderr

class ProfileInspectTest(ReleaseCommandCase):
    def test_reports_exactly_seven_members_for_nix_config(self):
        code, report, err = self.run_release("profile", "inspect", "github-release")
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(report), ["bindings", "conformance", "graphs", "profile",
                                          "repairs", "schema_version", "subject"])
        self.assertEqual(report["schema_version"], 1)
        self.assertTrue(report["profile"]["admissible"])
        self.assertEqual([n["id"] for n in report["graphs"]["publication"]], ["tag", "github-release"])
        self.assertEqual(report["graphs"]["handoffs"],
                         [{"from": "publication", "to": "activation", "receipt": "activation_not_applicable"}])
        derived = [o for o in report["graphs"]["proof"] if o["derived"]]
        self.assertEqual([(o["class"], o["predicate"], o["roots"]) for o in derived],
                         [("published_artifact_identity", "publication_visible", "tag"),
                          ("published_artifact_identity", "publication_visible", "github-release")])
        self.assertEqual(sorted(report["conformance"]["checks"]),
                         ["repository.release_profile.observation_deadline",
                          "repository.release_profile.restore_anchor",
                          "repository.release_profile.rolled_back_reachable"])
        for check in report["conformance"]["checks"].values():
            self.assertEqual(check, {"status": "passed", "reason_code": None})
        self.assertEqual(report["bindings"]["adapters"]["forge"]["adapter"], "github-forge")
        self.assertEqual(report["subject"]["project_id"], "fagenorn/nix-config")

    def test_an_inadmissible_profile_still_reports_in_full(self):
        contract = self.contract()
        del contract["release"]["profiles"]["github-release"]["publication"]["actions"][0][
            "observation_deadline_ms"]
        self.write_contract(contract)
        code, report, err = self.run_release("profile", "inspect", "github-release")
        self.assertEqual(code, 0, err)
        self.assertFalse(report["profile"]["admissible"])
        check = report["conformance"]["checks"]["repository.release_profile.observation_deadline"]
        self.assertEqual(check, {"status": "failed", "reason_code": "observation_deadline_optional"})
        self.assertIn({"repair_id": "release_profile.deadline.require",
                       "pointer": "/release/profiles/github-release/publication/actions/0",
                       "safety_class": "user_action"}, report["repairs"])

    def test_typed_errors_and_resolver_refusals(self):
        code, payload, _ = self.run_release("profile", "inspect", "nope")
        self.assertEqual((code, payload["error"]["code"]), (2, "profile_unknown"))
        contract = self.contract()
        contract["release"] = "unsupported"
        self.write_contract(contract)
        code, payload, _ = self.run_release("profile", "inspect", "github-release")
        self.assertEqual((code, payload["error"]["code"]), (2, "release_unsupported"))
        del contract["release"]
        self.write_contract(contract)
        code, payload, _ = self.run_release("profile", "inspect", "github-release")
        self.assertEqual((code, payload["error"]["code"]), (2, "invalid_contract"))

class PublicationFreeInspectTest(ReleaseCommandCase):
    """A publication-free profile is a declared profile: reported, with nothing in it (#368 D7)."""

    def test_reports_empty_graphs_and_no_handoff(self):
        contract = self.contract()
        profile = json.loads((REPO / "tests/fixtures/release/publication-free-profile.json")
                             .read_text("utf-8"))
        contract["release"] = {"profiles": {"forge-target": profile}}
        self.write_contract(contract)
        code, report, err = self.run_release("profile", "inspect", "forge-target")
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(report), ["bindings", "conformance", "graphs", "profile",
                                          "repairs", "schema_version", "subject"])
        self.assertTrue(report["profile"]["admissible"])
        self.assertEqual(report["profile"]["deadlines"], {})
        self.assertEqual(report["graphs"], {
            "phases": ["publication", "activation"], "publication": [], "activation": [],
            "handoffs": [], "proof": [], "recovery": []})
        self.assertEqual(report["bindings"]["targets"], profile["bindings"]["targets"])
        self.assertEqual(report["bindings"]["adapters"]["forge"]["adapter"], "github-forge")
        self.assertEqual(report["bindings"]["adapters"]["forge"]["config"], {})
        self.assertEqual(report["conformance"]["adapters"]["forge"]["modes"], {})
        self.assertEqual(report["conformance"]["findings"], [])
        for check in report["conformance"]["checks"].values():
            self.assertEqual(check, {"status": "passed", "reason_code": None})
        code, payload, _ = self.run_release("profile", "inspect", "github-release")
        self.assertEqual((code, payload["error"]["code"]), (2, "profile_unknown"))

class AdapterInspectTest(ReleaseCommandCase):
    """`release adapter inspect` resolves no project, so it runs without `--repo-root`."""

    def adapter(self, *args, env=None):
        return self.run_release("adapter", "inspect", *args, env=env, repo_root=False)

    def test_typed_errors(self):
        code, payload, _ = self.adapter("nope", "tag", "--parameters", "{}")
        self.assertEqual((code, payload["error"]["code"], payload["error"]["repair_id"]),
                         (2, "adapter_unknown", "release.adapter.unknown"))
        code, payload, _ = self.adapter("github-forge", "merge", "--parameters", "{}")
        self.assertEqual((code, payload["error"]["code"], payload["error"]["repair_id"]),
                         (2, "operation_unknown", "release.adapter.operation_unknown"))
        for text in ("[1]", "{"):
            code, payload, _ = self.adapter("github-forge", "tag", "--parameters", text)
            self.assertEqual((code, payload["error"]["code"], payload["error"]["repair_id"]),
                             (2, "parameters_invalid", "release.adapter.parameters_invalid"))

    def test_reads_a_live_pull_request_through_the_adapter(self):
        world = ForgeWorld(self)
        world.respond_json("gh", ROWS["pr_merge.view"]["argv"][1:], {
            "state": "OPEN", "baseRefName": CANONICAL["branch"], "headRefName": "topic",
            "headRefOid": CANONICAL["head"], "mergeCommit": None,
            "url": "https://github.com/fagenorn/nix-config/pull/336", "statusCheckRollup": []})
        world.respond_json("gh", ROWS["pr_merge.base_ref"]["argv"][1:],
                           {"object": {"sha": CANONICAL["base_tip"]}})
        world.respond_json("gh", ROWS["pr_merge.protection"]["argv"][1:], {
            "required_status_checks": {"contexts": ["Nix Eval"]}, "enforce_admins": {"enabled": True}})
        parameters = {"target": {"kind": "github_repository", "repository": CANONICAL["slug"],
                                 "branch": CANONICAL["branch"]},
                      "pr": CANONICAL["pr"], "expected_base_tip": CANONICAL["base_tip"],
                      "expected_head": CANONICAL["head"]}
        code, observation, err = self.adapter("github-forge", "pr_merge", "--parameters",
                                              json.dumps(parameters), env=world.env())
        self.assertEqual(code, 0, err)
        self.assertEqual(observation["outcome"], "absent")
        self.assertEqual(observation["facts"]["protection"]["status"], "protected")
        self.assertTrue(world.calls())
        self.assertFalse(any(call["token_visible"] for call in world.calls()))

class DeployInspectTest(ReleaseCommandCase):
    """`release deploy inspect` over a JarBird-shaped contract (issue 465 D5, D10, D16)."""

    def setUp(self):
        super().setUp()
        self.world = ActionsWorld(self)
        contract = self.contract()
        profile = json.loads((REPO / "tests/fixtures/release/publication-free-profile.json")
                             .read_text("utf-8"))
        contract["release"] = {"profiles": {"forge-main": profile}}
        contract["bindings"]["deploy"] = {"adapter": "github-actions-health", "command": None,
                                          "config": dict(CONFIG, health_url=self.world.url())}
        contract["bindings"]["tracker"]["credential_env"]["unset_before_invocation"] = [
            "GITHUB_TOKEN", "GH_TOKEN"]
        contract["capabilities"]["deploy"]["support"] = "supported"
        self.write_contract(contract)

    def deploy(self, commit=MERGE, env=None):
        return self.run_release("deploy", "inspect", "--commit", commit, env=env)

    def verdict(self, *runs, **health):
        self.world.runs(*runs)
        self.world.health(**health)
        code, observation, err = self.deploy()
        self.assertEqual(code, 0, err)
        return observation["outcome"], observation["reason"]

    def test_satisfied_needs_a_successful_run_and_a_matching_health_commit(self):
        self.assertEqual(self.verdict(run(8, MERGE), commit=MERGE), ("satisfied", "deployed"))
        self.assertEqual(self.verdict(run(8, MERGE), commit=OLDER),
                         ("diverged", "health_commit_mismatch"))
        self.assertEqual(self.verdict(run(8, MERGE, conclusion="failure"), commit=MERGE),
                         ("diverged", "run_failed"))
        self.assertEqual(self.verdict(run(8, MERGE, conclusion="failure"), commit=OLDER),
                         ("diverged", "silent_rollback"))

    def test_the_credential_binding_decides_what_gh_sees(self):
        self.assertEqual(self.verdict(run(8, MERGE, status="queued")),
                         ("in_progress", "run_in_progress"))
        contract = self.contract()
        contract["bindings"]["tracker"]["credential_env"]["unset_before_invocation"] = []
        self.write_contract(contract)
        self.assertEqual(self.verdict(run(8, MERGE, status="queued")),
                         ("in_progress", "run_in_progress"))
        self.assertEqual([call["token_visible"] for call in self.world.calls()], [False, True])

    def test_typed_refusals_exit_2_before_any_read(self):
        def refusal(*args, **kwargs):
            code, payload, _ = self.deploy(*args, **kwargs)
            return code, payload["error"]["code"], payload["error"]["repair_id"]

        for commit in (MERGE.upper(), MERGE[:7], "HEAD"):
            with self.subTest(commit=commit):
                self.assertEqual(refusal(commit), (2, "parameters_invalid",
                                                   "release.deploy.commit_invalid"))
        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)
        self.assertEqual(refusal(env={"PATH": empty.name}),
                         (2, "capability_unavailable",
                          "capability.deploy.release_adapter_unavailable"))
        contract = self.contract()
        contract["capabilities"]["deploy"]["support"] = "unsupported"
        self.write_contract(contract)
        self.assertEqual(refusal(), (2, "capability_unavailable", "capability.deploy.unsupported"))
        contract = self.contract()
        contract["release"] = "unsupported"
        contract["capabilities"]["deploy"]["support"] = "supported"
        contract["bindings"]["commands"]["deploy-list"] = {"argv": ["gh", "run", "list"],
                                                           "cwd": ".", "env": []}
        contract["bindings"]["deploy"] = {"adapter": "railway", "command": "deploy-list",
                                          "config": {}}
        self.write_contract(contract)
        self.assertEqual(refusal(), (2, "deploy_adapter_unregistered",
                                     "release.deploy.adapter_unregistered"))
        self.assertEqual(self.world.calls(), [])
        self.assertEqual(self.world.requests, [])

if __name__ == "__main__":
    unittest.main()
