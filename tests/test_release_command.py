"""The release command: profile (#124 spec §5), adapter and deploy inspection (issue 465), transaction (#128).

Run: just agent-workflow-tests
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from . import forge_world
from . import release_test_support as support
from .actions_world import MERGE
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

    def run_release(self, *args, env=None, repo_root=True, cwd=None):
        env = dict(os.environ, PYTHONPATH=str(PYTHON), HOME=str(self.home), **(env or {}))
        tail = ["--repo-root", str(self.root)] if repo_root else []
        result = subprocess.run([sys.executable, "-m", "agent_tools.release", *args, *tail],
                                capture_output=True, text=True, env=env, timeout=120,
                                cwd=cwd)
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
            "headRefOid": CANONICAL["commit"], "mergeCommit": None,
            "url": "https://github.com/fagenorn/nix-config/pull/336", "statusCheckRollup": []})
        world.respond_json("gh", ROWS["pr_merge.base_ref"]["argv"][1:],
                           {"object": {"sha": CANONICAL["base_tip"]}})
        world.respond_json("gh", ROWS["pr_merge.protection"]["argv"][1:], forge_world.FLOOR_PROTECTION)
        parameters = {"target": {"kind": "github_repository", "repository": CANONICAL["slug"],
                                 "branch": CANONICAL["branch"]},
                      "candidate": {"version": CANONICAL["tag"], "commit": CANONICAL["commit"],
                                    "merge": {"pr": CANONICAL["pr"], "base_tip": CANONICAL["base_tip"]}}}
        code, observation, err = self.adapter("github-forge", "pr_merge", "--parameters",
                                              json.dumps(parameters), env=world.env())
        self.assertEqual(code, 0, err)
        self.assertEqual(observation["outcome"], "absent")
        self.assertEqual(observation["facts"]["protection"]["status"], "protected")
        self.assertIs(observation["facts"]["protection"]["strict"], True)
        self.assertTrue(world.calls())
        self.assertFalse(any(call["token_visible"] for call in world.calls()))

class DeployInspectRemovedTest(ReleaseCommandCase):
    """Platform 2.0.0 removes `release deploy inspect`: the subcommand is not a choice."""

    def test_the_deploy_subcommand_is_an_invalid_choice(self):
        env = dict(os.environ, PYTHONPATH=str(PYTHON), HOME=str(self.home))
        result = subprocess.run(
            [sys.executable, "-m", "agent_tools.release", "deploy", "inspect",
             "--commit", MERGE, "--repo-root", str(self.root)],
            capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("invalid choice", result.stderr)


class TransactionCommandTest(ReleaseCommandCase):
    """`release transaction` against nix-config's own profile (#128 spec §1, §4–§7)."""

    def setUp(self):
        super().setUp()
        self.world = ForgeWorld(self)
        self.world.verification_ready()
        notes = tempfile.TemporaryDirectory()
        self.addCleanup(notes.cleanup)
        self.notes = Path(notes.name) / "notes.md"
        self.notes.write_text("notes body\n", encoding="utf-8")

    def candidate(self):
        return ["--commit", CANONICAL["commit"], "--version", CANONICAL["tag"],
                "--title", CANONICAL["title"], "--notes-file", str(self.notes)]

    def store_exists(self):
        return (self.root / ".git/agent-release").exists()

    def preview(self):
        code, document, err = self.run_release("transaction", "preview", *self.candidate())
        self.assertEqual(code, 0, err)
        return document

    def run_with(self, tokens):
        confirms = [part for token in tokens for part in ("--confirm", token)]
        return self.run_release("transaction", "run", *self.candidate(), *confirms, cwd=self.root)

    def test_preview_names_tag_and_release(self):
        document = self.preview()
        self.assertEqual([c["action"] for c in document["confirmations"]], ["tag", "github-release"])
        self.assertEqual({c["version"] for c in document["confirmations"]}, {CANONICAL["tag"]})
        self.assertFalse(self.store_exists())

    def test_run_without_every_current_token_writes_nothing(self):
        tokens = [c["token"] for c in self.preview()["confirmations"]]
        for code, supplied in (("confirmation_required", []),
                               ("confirmation_required", tokens[:1]),
                               ("confirmation_stale", ["tag:000000000000", tokens[1]])):
            with self.subTest(supplied=supplied):
                exit_code, document, err = self.run_with(supplied)
                self.assertEqual((exit_code, document["error"]["code"]), (3, code), err)
        self.assertFalse(self.store_exists())

    def test_status_shows_a_nonterminal_release(self):
        self.world.invoke_ready(guard_exit=1)
        self.world.not_found("gh", ROWS["tag.ref"]["argv"][1:])
        self.world.not_found("gh", ROWS["release.view"]["argv"][1:])
        tokens = [c["token"] for c in self.preview()["confirmations"]]
        exit_code, result, err = self.run_with(tokens)
        self.assertEqual((exit_code, result["next"]), (0, "attention"), err)
        code, status, err = self.run_release("transaction", "status")
        self.assertEqual(code, 0, err)
        release = status["release"]
        self.assertEqual((release["state"], release["terminal"]), ("attention_required", None))
        self.assertEqual([(a["name"], a["status"], a["attempts"]) for a in release["actions"]],
                         [("tag", "absent", 1), ("github-release", None, 0)])
        self.assertEqual(sorted(g["grant_id"] for g in release["grants"]), sorted(tokens))

    def test_a_release_already_on_the_forge_runs_to_done(self):
        self.world.canonical()
        # canonical() overwrote the tip and protection reads.
        self.world.verification_ready()
        tokens = [c["token"] for c in self.preview()["confirmations"]]
        exit_code, result, err = self.run_with(tokens)
        self.assertEqual((exit_code, result["state"], result["next"]), (0, "succeeded", "done"), err)
        code, status, err = self.run_release("transaction", "status")
        self.assertIsNotNone(status["release"]["receipt"])
        self.assertFalse(any(c["argv"][:2] == ["release", "create"] for c in self.world.calls()))

    def test_typed_refusals(self):
        code, document, _ = self.run_release("transaction", "preview", "--commit", "1" * 40)
        self.assertEqual((code, document["error"]["code"]), (3, "candidate_required"))
        code, document, _ = self.run_release("transaction", "abandon", cwd=self.world.checkout)
        self.assertEqual((code, document["error"]["code"]), (3, "cwd_mismatch"))

    def test_an_unexpected_failure_keeps_the_envelope_and_logs_the_original_error(self):
        tokens = [c["token"] for c in self.preview()["confirmations"]]
        (self.root / ".git/agent-release").write_text("not a directory", encoding="utf-8")
        exit_code, document, err = self.run_with(tokens)
        self.assertEqual((exit_code, document["error"]["code"]), (2, "resolver_failure"))
        self.assertIn("Traceback", err)
        self.assertRegex(err, r"(FileExistsError|NotADirectoryError)")

    def test_an_unadopted_repository_gets_the_resolver_refusal_byte_for_byte(self):
        bare = self.root.parent / "bare"
        (bare / ".git").mkdir(parents=True)
        env = dict(os.environ, PYTHONPATH=str(PYTHON), HOME=str(self.home))
        def raw(*argv):
            return subprocess.run([sys.executable, "-m", *argv, "--repo-root", str(bare)],
                                  capture_output=True, env=env, timeout=120)
        ours = raw("agent_tools.release", "transaction", "status")
        theirs = raw("agent_tools.project_contract.resolve_project", "resolve", "--require", "release")
        self.assertEqual((ours.returncode, ours.stdout), (2, theirs.stdout))
        self.assertEqual(theirs.returncode, 2)


class LegacyCommandTest(TransactionCommandTest):
    """Cutover refuses while a legacy release is in flight (#128 AC6)."""

    def legacy(self, text):
        path = self.root / ".superpowers/workflows/ship-release/state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_in_flight_and_unreadable_refuse_and_touch_nothing(self):
        in_flight = json.dumps({"headSha": "1" * 40, "pr": 7, "prUrl": "u", "mergeSha": None,
                                "tag": None, "releaseUrl": None, "deployState": "pending"})
        for text in (in_flight, "not json"):
            with self.subTest(text=text[:10]):
                path = self.legacy(text)
                for argv, cwd in ((["preview", *self.candidate()], None),
                                  (["run", *self.candidate()], self.root)):
                    code, document, err = self.run_release("transaction", *argv, cwd=cwd)
                    self.assertEqual((code, document["error"]["code"]),
                                     (3, "legacy_release_in_flight"), err)
                self.assertEqual(path.read_text(encoding="utf-8"), text)
                code, status, _ = self.run_release("transaction", "status")
                self.assertEqual(code, 0)
                self.assertIn(status["legacy"]["class"], ("in_flight", "unreadable"))
        self.assertFalse(self.store_exists())



class HostLocalInspectTest(ReleaseCommandCase):
    """Issue 547 AC1: the Argus-shaped profile reports in full through `profile inspect`."""

    def test_the_argus_shaped_profile_is_admissible(self):
        fixtures = REPO / "tests/fixtures/release"
        contract = self.contract()
        contract["release"] = {"profiles": {
            "argus": json.loads((fixtures / "argus-shaped-profile.json").read_text("utf-8")),
            "forge-target": json.loads((fixtures / "publication-free-profile.json")
                                       .read_text("utf-8"))}}
        self.write_contract(contract)
        code, report, err = self.run_release("profile", "inspect", "argus")
        self.assertEqual(code, 0, err)
        self.assertTrue(report["profile"]["admissible"])
        self.assertEqual(report["conformance"]["findings"], [])
        graphs = report["graphs"]
        self.assertEqual(([n["id"] for n in graphs["publication"]],
                          [n["id"] for n in graphs["activation"]]), (["notifier"], ["daemon"]))
        self.assertEqual(graphs["handoffs"], [
            {"from": "publication", "to": "activation", "receipt": "publication_receipt"}])
        self.assertEqual([(o["id"], o["predicate"]) for o in graphs["proof"]], [
            ("derived:published_artifact_identity:notifier", "publication_visible"),
            ("derived:running_subject_identity:daemon", "running_subject_identity"),
            ("daemon-live", "agent_running")])
        self.assertEqual(report["bindings"]["adapters"]["bundle"]["adapter"], "codesigned-artifact")
        self.assertEqual(report["conformance"]["adapters"]["launchd"]["modes"],
                         {"activate": "supported"})


class TwoBranchCommandTest(ReleaseCommandCase):
    """Issue 554 row 11: the command prints the merge observation's refusal in its document."""

    def setUp(self):
        super().setUp()
        contract = self.contract()
        contract["bindings"]["vcs"]["integration_branch"] = "dev"
        contract["release"]["profiles"] = {"github-release": support.merge_profile()}
        self.write_contract(contract)
        self.world = ForgeWorld(self)
        self.world.verification_ready(integration="dev")
        notes = tempfile.TemporaryDirectory()
        self.addCleanup(notes.cleanup)
        self.notes = Path(notes.name) / "notes.md"
        self.notes.write_text("notes body\n", encoding="utf-8")

    def test_preview_refuses_a_missing_release_pr(self):
        self.world.merge_observation_ready(prs=[])
        code, document, err = self.run_release(
            "transaction", "preview", "--commit", CANONICAL["commit"], "--version", CANONICAL["tag"],
            "--title", CANONICAL["title"], "--notes-file", str(self.notes))
        self.assertEqual((code, document["runnable"], document["refusal"]["code"]),
                         (3, False, "release_pr_missing"), err)
        self.assertEqual([c["action"] for c in document["confirmations"]], ["merge", "tag", "github-release"])
        self.assertIsNone(document["verification"])
        self.assertFalse((self.root / ".git/agent-release").exists())


if __name__ == "__main__":
    unittest.main()
