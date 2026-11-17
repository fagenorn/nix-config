"""The bypass proof's `github`: setup on a throwaway repository, the record and the teardown (#1152).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import bypass_proof
from agent_tools.console.bypass_proof import (ATTEMPT_NAMES, REQUIRED_CHECK, TEARDOWN_STEPS,
                                              ProofRefused)
from agent_tools.console.permission import AUTO, BYPASS, Permission
from agent_tools.project_contract import agent_platform

from .guard_policy_world import MANIFEST

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / ".agents/project.json"
OWNER = "fagenorn"


def passing_report(outcome="passed"):
    fragments = bypass_proof.expected_fragments("o/n", "proof-change", REQUIRED_CHECK)
    rows = [{"attempt": name, "tool": "Bash", "input": {}, "expect": fragments.get(name),
             "verdict": "refused" if name != "read_only_route" else "allowed",
             "sentence": None, "permission_mode": BYPASS} for name in ATTEMPT_NAMES]
    return {"schema_version": 1, "mode": "run", "repository": "o/n", "project_id": "p",
            "started_at": "a", "finished_at": "b", "outcome": outcome, "attempts": rows}


class Fakes:
    """Recording steps; `policy` is the slug set the fake compiler keeps."""

    def __init__(self, *, fail=None, permission=None, keep_previous=False, outcome="passed"):
        self.calls = []
        self.args = {}
        self.fail = fail or {}
        self.registered = {}
        self.policy = set()
        self.keep_previous = keep_previous
        self.permission = permission or Permission(BYPASS, "production rules in place")
        self.outcome = outcome
        self.deleted = []

    def _do(self, name, *args):
        self.calls.append(name)
        self.args[name] = args
        if name in self.fail:
            raise self.fail[name]

    def steps(self):
        def create_repository(slug):
            self._do("create_repository", slug)

        def push_checkout(slug, checkout):
            self._do("push_checkout", slug, checkout)

        def open_failing_pr(slug, checkout, check):
            self._do("open_failing_pr", slug, checkout, check)
            return 7

        def register(project_id, root):
            self._do("register", project_id, root)
            self.registered[project_id] = root

        def compile_policy():
            self._do("compile_policy")
            if self.keep_previous and self.calls.count("compile_policy") > 1:
                return
            self.policy = {f"{OWNER}/{identifier.split('/')[1]}" for identifier in self.registered}

        def policy_slugs():
            self._do("policy_slugs")
            return frozenset(self.policy)

        def read_permission(project_id, root):
            self._do("read_permission", project_id, root)
            return self.permission

        def prove(checkout, pr):
            self._do("prove", checkout, pr)
            return passing_report(self.outcome)

        def unregister(project_id):
            self._do("unregister", project_id)
            self.registered.pop(project_id, None)

        def delete_repository(slug):
            self._do("delete_repository", slug)
            self.deleted.append(slug)

        return bypass_proof.Steps(
            create_repository=create_repository, push_checkout=push_checkout,
            open_failing_pr=open_failing_pr, register=register, compile_policy=compile_policy,
            policy_slugs=policy_slugs, read_permission=read_permission, prove=prove,
            unregister=unregister, delete_repository=delete_repository)


class GithubProofTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bypass-github-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        (self.home / ".agents/share").mkdir(parents=True)
        shutil.copy(MANIFEST, self.home / ".agents/share/platform-manifest.json")
        self.work = self.tmp / "work"
        self.work.mkdir()
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("CLAUDECODE", None)
        self.record_file = self.home / ".agents/state/console/bypass-proof.json"

    def proof(self, fakes):
        return bypass_proof.github_proof(OWNER, TEMPLATE, steps=fakes.steps(),
                                         workdir_root=self.work)

    def teardown_of(self, record):
        return [entry["step"] for entry in record["teardown"]]

    def test_a_passing_run_is_recorded_and_torn_down_in_order(self):
        fakes = Fakes()
        record = self.proof(fakes)
        self.assertEqual(fakes.calls, [
            "create_repository", "push_checkout", "open_failing_pr", "register",
            "compile_policy", "read_permission", "prove", "unregister", "compile_policy",
            "policy_slugs", "delete_repository"])
        self.assertEqual(fakes.args["open_failing_pr"][2], REQUIRED_CHECK)
        self.assertEqual(self.teardown_of(record), list(TEARDOWN_STEPS))
        self.assertEqual(json.loads(self.record_file.read_text(encoding="utf-8")), record)
        self.assertEqual(self.record_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(record["mode"], "github")
        self.assertEqual(record["outcome"], "passed")
        self.assertTrue(all(entry["ok"] for entry in record["teardown"]))
        self.assertEqual(len(record["attempts"]), 7)
        self.assertTrue(record["repository"].startswith(f"{OWNER}/bypass-proof-"))
        self.assertEqual(record["project_id"], "bypass-proof/" + record["repository"].split("/")[1])
        self.assertEqual(os.listdir(self.work), [])

    def test_a_failing_proof_still_tears_down(self):
        fakes = Fakes(outcome="failed")
        record = self.proof(fakes)
        self.assertEqual(fakes.calls[-4:], ["unregister", "compile_policy", "policy_slugs",
                                            "delete_repository"])
        self.assertEqual(record["outcome"], "failed")

    def test_a_manager_that_would_not_run_in_bypass_refuses_without_a_session(self):
        fakes = Fakes(permission=Permission(
            AUTO, "production rules declared but not in the guard's policy"))
        record = self.proof(fakes)
        self.assertNotIn("prove", fakes.calls)
        self.assertEqual(record["outcome"], "refused")
        self.assertIn("would not run a manager", record["reason"])
        self.assertIn("production rules declared but not in the guard's policy", record["reason"])
        self.assertEqual(self.teardown_of(record), list(TEARDOWN_STEPS))
        self.assertEqual(len(fakes.deleted), 1)

    def test_a_setup_failure_before_registration_only_deletes_the_repository(self):
        fakes = Fakes(fail={"open_failing_pr": ProofRefused("x")})
        record = self.proof(fakes)
        for name in ("register", "unregister", "compile_policy"):
            self.assertNotIn(name, fakes.calls)
        self.assertEqual(self.teardown_of(record), ["delete_repository", "remove_checkout"])
        self.assertEqual(len(fakes.deleted), 1)
        self.assertEqual(record["outcome"], "refused")

    def test_a_failure_after_creation_still_deletes_the_repository(self):
        fakes = Fakes(fail={"push_checkout": ProofRefused("push failed")})
        record = self.proof(fakes)
        self.assertEqual(fakes.deleted, [record["repository"]])
        for name in ("open_failing_pr", "register"):
            self.assertNotIn(name, fakes.calls)
        self.assertEqual(record["outcome"], "refused")
        self.assertIn("push failed", record["reason"])

    def test_a_failed_creation_deletes_nothing(self):
        fakes = Fakes(fail={"create_repository": ProofRefused("x")})
        record = self.proof(fakes)
        self.assertNotIn("delete_repository", fakes.calls)
        self.assertEqual(self.teardown_of(record), ["remove_checkout"])
        self.assertEqual(record["outcome"], "refused")

    def test_a_recompile_that_keeps_the_throwaway_row_fails_teardown(self):
        fakes = Fakes(keep_previous=True)
        record = self.proof(fakes)
        entry = next(entry for entry in record["teardown"] if entry["step"] == "recompile")
        self.assertFalse(entry["ok"])
        self.assertIn(record["repository"], entry["detail"])
        self.assertIn("claude-guard-policy", entry["detail"])
        self.assertEqual(len(fakes.deleted), 1)
        again = Fakes(keep_previous=True)
        with mock.patch.object(bypass_proof, "DEFAULT_STEPS", again.steps()), \
                contextlib.redirect_stdout(io.StringIO()):
            code = bypass_proof.main(["github", "--owner", OWNER, "--template", str(TEMPLATE)])
        self.assertEqual(code, 1)

    def test_a_failed_teardown_step_is_reported_and_the_rest_still_runs(self):
        fakes = Fakes(fail={"unregister": RuntimeError("registry locked")})
        record = self.proof(fakes)
        self.assertEqual(fakes.calls[-3:], ["compile_policy", "policy_slugs", "delete_repository"])
        entry = next(entry for entry in record["teardown"] if entry["step"] == "unregister")
        self.assertFalse(entry["ok"])
        self.assertIn("registry locked", entry["detail"])
        again = Fakes(fail={"unregister": RuntimeError("registry locked")})
        with mock.patch.object(bypass_proof, "DEFAULT_STEPS", again.steps()), \
                contextlib.redirect_stdout(io.StringIO()):
            code = bypass_proof.main(["github", "--owner", OWNER, "--template", str(TEMPLATE)])
        self.assertEqual(code, 1)

    def test_registry_entries_are_added_and_removed(self):
        other = {"project_id": "fagenorn/nix-config", "root": "/somewhere"}
        agent_platform.write_registry([other])
        bypass_proof.register_entry("bypass-proof/x", "/c/x")
        self.assertEqual({entry["project_id"] for entry in agent_platform.read_registry()},
                         {"fagenorn/nix-config", "bypass-proof/x"})
        bypass_proof.unregister_entry("bypass-proof/x")
        self.assertEqual(agent_platform.read_registry(), [other])
        before = agent_platform.registry_path().read_bytes()
        with self.assertRaises(ValueError):
            bypass_proof.unregister_entry("fagenorn/nix-config")
        self.assertEqual(agent_platform.registry_path().read_bytes(), before)

    def test_policy_slugs_in(self):
        path = self.tmp / "policy.json"
        self.assertEqual(bypass_proof.policy_slugs_in(path), frozenset())
        path.write_text(json.dumps({"derived_repositories": {"o/a": {}}, "derivation": {}}),
                        encoding="utf-8")
        self.assertEqual(bypass_proof.policy_slugs_in(path), frozenset({"o/a"}))
        path.write_text("[]", encoding="utf-8")
        with self.assertRaises(ProofRefused):
            bypass_proof.policy_slugs_in(path)

    def test_argv_builders(self):
        self.assertEqual(bypass_proof.repo_create_argv("o/n"),
                         ["gh", "repo", "create", "o/n", "--private"])
        self.assertEqual(bypass_proof.push_checkout_argvs("o/n", Path("/c")), [
            ["git", "-C", "/c", "remote", "add", "origin", "git@github.com:o/n.git"],
            ["git", "-C", "/c", "push", "-u", "origin", "main"],
            ["git", "-C", "/c", "remote", "set-head", "origin", "main"]])
        self.assertEqual(bypass_proof.pr_create_argv("o/n"), [
            "gh", "pr", "create", "--repo", "o/n", "--base", "main", "--head", "bypass-proof-pr",
            "--title", "bypass proof", "--body", "A pull request whose required check fails on purpose."])
        self.assertEqual(bypass_proof.failing_status_argv("o/n", "a" * 40, "bypass-proof"), [
            "gh", "api", "-X", "POST", f"repos/o/n/statuses/{'a' * 40}", "-f", "state=failure",
            "-f", "context=bypass-proof", "-f", "description=bypass proof: failing on purpose"])
        self.assertEqual(bypass_proof.repo_delete_argv("o/n"),
                         ["gh", "repo", "delete", "o/n", "--yes"])
        self.assertEqual(bypass_proof.COMPILE_ARGV, ["claude-guard-policy"])
        self.assertEqual(bypass_proof.PR_BRANCH, "bypass-proof-pr")

    def test_github_refuses_inside_an_agent_session(self):
        env = {**os.environ, "CLAUDECODE": "1", "PYTHONPATH": str(REPO_ROOT / "python")}
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.console.bypass_proof", "github", "--owner", "o",
             "--template", str(TEMPLATE)],
            env=env, capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertTrue(done.stderr.startswith("bypass-proof: "), done.stderr)
        self.assertFalse(self.record_file.exists())


if __name__ == "__main__":
    unittest.main()
