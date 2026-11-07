import importlib.util
import os
import subprocess
import unittest
from pathlib import Path

from .guard_policy_world import GuardPolicyWorld
from .pre_push_world import GUARD_SOURCE, PrePushWorld

AGENT = {"CLAUDECODE": "1"}
OWN = "fagenorn/fixture"
OTHER = "fagenorn/other"
NODO = "elevenyellow/nodocom"
NODO_ROW = {"default_branch": "main", "integration_branch": "dev",
            "required_checks": [], "evidence": {}}
HOOK = "lifecycle guard pre-push: unsafe push: "


def load_guard():
    spec = importlib.util.spec_from_file_location("lifecycle_guard_source", GUARD_SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Refusals:
    def refused(self, result, problem):
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn(HOOK + problem, result.stderr)

    def refused_naming(self, result, tail):
        """A refusal whose problem carries a URL the test does not spell out."""
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn(HOOK + "push URL ", result.stderr)
        self.assertIn(tail, result.stderr)


class SharedPolicyTest(unittest.TestCase):
    def test_the_hook_reads_facts_only_as_the_text_mode_push_forms(self):
        guard = load_guard()
        self.assertEqual(set(guard.PRE_PUSH_FORMS),
                         {form[0] for form in guard.FORM_TABLE["push"]["forms"]})


class PushFixtureTest(unittest.TestCase):
    def test_a_url_rewrite_in_the_callers_global_config_never_applies(self):
        world = PrePushWorld(self)
        Path(world.env["GIT_CONFIG_GLOBAL"]).write_text(
            '[url "https://example.invalid/"]\n\tinsteadOf = git@github.com:\n'
            '\tpushInsteadOf = git@github.com:\n', encoding="utf-8")
        repo = world.fixture(OWN)
        repo.git("switch", "-q", "-c", "issue-1-topic")
        head = repo.commit("topic")
        result = repo.git("push", "origin", "issue-1-topic", extra_env=AGENT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(repo.remote_ref(OWN, "refs/heads/issue-1-topic"), head)


class PrePushJudgementTest(Refusals, unittest.TestCase):
    def setUp(self):
        self.world = PrePushWorld(self, rows={NODO: NODO_ROW})
        self.repo = self.world.fixture(OWN)
        self.repo.git("switch", "-q", "-c", "issue-1-topic")
        self.repo.commit("topic")

    def test_an_agent_feature_branch_push_to_its_own_repository_is_admitted(self):
        head = self.repo.git("rev-parse", "HEAD").stdout.strip()
        result = self.repo.git("push", "origin", "issue-1-topic", extra_env=AGENT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.repo.remote_ref(OWN, "refs/heads/issue-1-topic"), head)

    def test_an_agent_push_of_the_default_branch_is_refused(self):
        before = self.repo.remote_ref(OWN, "refs/heads/main")
        self.repo.git("switch", "-q", "main")
        self.repo.commit("onto main")
        self.refused(self.repo.git("push", "origin", "main", extra_env=AGENT),
                     "refusing to push the default branch main")
        self.assertEqual(self.repo.remote_ref(OWN, "refs/heads/main"), before)

    def test_an_agent_push_of_the_default_branch_of_a_registered_project_is_refused(self):
        repo = self.world.fixture(NODO)
        repo.commit("onto main")
        self.refused(repo.git("push", "origin", "HEAD:refs/heads/main", extra_env=AGENT),
                     "refusing to push the default branch main")

    def test_a_pushurl_naming_another_repository_is_refused(self):
        self.repo.add_remote(OTHER)
        self.repo.git("config", "remote.origin.pushurl", f"git@github.com:{OTHER}.git")
        self.refused(self.repo.git("push", "origin", "issue-1-topic", extra_env=AGENT),
                     f"push URL git@github.com:{OTHER}.git does not name {OWN}")
        self.assertIsNone(self.repo.remote_ref(OTHER, "refs/heads/issue-1-topic"))

    def test_a_push_insteadof_naming_another_repository_is_refused(self):
        self.repo.add_remote(OTHER)
        self.repo.git("config", f"url.git@github.com:{OTHER}.git.pushInsteadOf",
                      f"git@github.com:{OWN}.git")
        self.refused_naming(self.repo.git("push", "origin", "issue-1-topic", extra_env=AGENT),
                            f"does not name {OWN}")

    def test_a_direct_url_push_to_another_repository_is_refused(self):
        self.repo.add_remote(OTHER)
        self.refused_naming(self.repo.git("push", f"git@github.com:{OTHER}.git", "issue-1-topic",
                                          extra_env=AGENT), f"does not name {OWN}")

    def test_an_alias_for_push_is_refused_through_the_hook(self):
        self.repo.git("config", "alias.p", "push")
        self.repo.git("switch", "-q", "main")
        self.repo.commit("onto main")
        self.refused(self.repo.git("p", "origin", "main", extra_env=AGENT),
                     "refusing to push the default branch main")

    def test_an_xargs_fed_push_is_refused_through_the_hook(self):
        self.repo.git("switch", "-q", "main")
        self.repo.commit("onto main")
        result = subprocess.run(
            ["sh", "-c", f"printf '%s\\n' push origin main | xargs {self.world.git_bin}"],
            cwd=self.repo.work, env={**self.repo.env, **AGENT},
            capture_output=True, text=True, check=False)
        self.refused(result, "refusing to push the default branch main")

    def test_a_push_to_an_unregistered_repository_is_refused(self):
        repo = self.world.fixture("stranger/repo")
        repo.git("switch", "-q", "-c", "issue-1-topic")
        self.refused(repo.git("push", "origin", "issue-1-topic", extra_env=AGENT),
                     "repository stranger/repo is outside standing authorization")

    def test_deleting_the_default_branch_is_refused(self):
        self.refused(self.repo.git("push", "origin", ":refs/heads/main", extra_env=AGENT),
                     "refusing to delete the permanent branch main")

    def test_deleting_a_feature_branch_is_admitted(self):
        self.assertEqual(self.repo.git("push", "origin", "issue-1-topic").returncode, 0)
        result = self.repo.git("push", "origin", "--delete", "refs/heads/issue-1-topic",
                               extra_env=AGENT)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_forced_non_fast_forward_update_is_refused(self):
        self.assertEqual(self.repo.git("push", "origin", "issue-1-topic").returncode, 0)
        self.repo.git("reset", "-q", "--hard", "HEAD~1")
        self.repo.commit("rewritten")
        self.refused(self.repo.git("push", "--force", "origin", "issue-1-topic",
                                   extra_env=AGENT),
                     "update of issue-1-topic is not a fast-forward")

    def test_an_annotated_release_tag_is_admitted_and_a_lightweight_one_refused(self):
        self.repo.git("tag", "-a", "-m", "v1", "v1.0.0")
        self.assertEqual(self.repo.git("push", "origin", "refs/tags/v1.0.0",
                                       extra_env=AGENT).returncode, 0)
        self.repo.git("tag", "v1.0.1")
        self.refused(self.repo.git("push", "origin", "refs/tags/v1.0.1", extra_env=AGENT),
                     "v1.0.1 is not an existing annotated tag")

    def test_a_ref_outside_branches_and_tags_is_refused(self):
        self.refused(self.repo.git("push", "origin", "HEAD:refs/notes/x", extra_env=AGENT),
                     "remote ref refs/notes/x is neither a branch nor a release tag")

    def test_a_human_push_outside_an_agent_session_is_not_judged(self):
        self.repo.git("switch", "-q", "main")
        self.repo.commit("onto main")
        result = self.repo.git("push", "origin", "main", extra_env={"CLAUDECODE": ""})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_bad_base_policy_refuses_every_push(self):
        self.world.base_policy.write_text("{}", encoding="utf-8")
        result = self.repo.git("push", "origin", "issue-1-topic", extra_env={"CLAUDECODE": ""})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lifecycle guard pre-push: invalid policy", result.stderr)


class RegisteredProjectDerivationTest(Refusals, unittest.TestCase):
    """D10: the real row check over a registry of two projects, from a linked worktree
    and with GIT_DIR exported, derives the pushing repository's row from its own root."""

    def setUp(self):
        fleet = GuardPolicyWorld(self)
        fleet.project("nodocom", NODO, integration_branch="dev", publication_free=True,
                      override=True)
        fleet.project("fixture/single", "fagenorn/single")
        code, report, stderr = fleet.compile()
        self.assertEqual((code, report["derived"]), (0, sorted([NODO, "fagenorn/single"])),
                         stderr)
        self.world = PrePushWorld(self, policy=fleet.output, derive_bin=fleet.row_check(),
                                  derive_timeout=25)
        self.repo = self.world.fixture(NODO)
        self.linked = self.world.tmp / "linked"
        self.repo.git("worktree", "add", "-q", "-b", "issue-2-topic", str(self.linked))

    def test_a_feature_push_from_a_linked_worktree_is_admitted_by_the_real_row_check(self):
        result = self.repo.git("push", "origin", "issue-2-topic", extra_env=AGENT,
                               cwd=self.linked)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_default_branch_push_from_a_linked_worktree_is_refused(self):
        self.repo.commit("onto main")
        self.refused(self.repo.git("push", "origin", "main:refs/heads/main",
                                   extra_env=AGENT, cwd=self.linked),
                     "refusing to push the default branch main")

    def test_an_exported_git_dir_does_not_reach_the_row_check(self):
        gitdir = self.repo.git("rev-parse", "--absolute-git-dir", cwd=self.linked).stdout.strip()
        exported = {**AGENT, "GIT_DIR": gitdir, "GIT_WORK_TREE": str(self.linked)}
        result = self.repo.git("push", "origin", "issue-2-topic", extra_env=exported,
                               cwd=self.linked)
        self.assertEqual(result.returncode, 0, result.stderr)
