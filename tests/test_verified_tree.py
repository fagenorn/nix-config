"""verified-tree: a verification pass recorded against the tree it saw (#263, issue 437).

Each test drives `python -m agent_tools.verified_tree` in a throwaway git
repository, the way test_launch_commit.py drives its command (#263 D6). The
repository is a copy of the eval fixture project whose contract gains a second,
conditional verification id, resolved under a temporary HOME holding the
committed platform manifest (the lane-triage harness), with
`refs/remotes/origin/main` at the base commit (issue 437 D12).
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "home/common/agent-skills/platform-manifest.json"
FIXTURE = REPO_ROOT / "home/common/agent-skills/evals/fixture-repo"
HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
SCRUBBED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
            "GIT_COMMON_DIR", "GIT_CEILING_DIRECTORIES")
IDS = ["test", "suite"]
REASON = "no tinytask or docs paths changed"
CONDITIONS = {"suite": {"when_changed": ["tinytask/*", "docs/*"], "skip_reason": REASON}}
SKIPPED = [{"id": "suite", "reason": REASON}]
ABSENT = object()


class VerifiedTreeTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name).resolve()
        home = self.scratch / "home"
        (home / ".agents" / "share").mkdir(parents=True)
        shutil.copy(MANIFEST, home / ".agents" / "share" / "platform-manifest.json")
        self.repo = self.scratch / "repo"
        shutil.copytree(FIXTURE, self.repo)
        self.env = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
        self.env.update(HERMETIC_GIT, HOME=str(home))
        self.set_conditions(CONDITIONS)
        self.git("init", "-q", "-b", "main")
        self.git("config", "commit.gpgsign", "false")  # throwaway fixture repo
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")

    def set_conditions(self, conditions):
        """Rewrite the working-tree contract: ids `test` and `suite`, with `conditions`."""
        path = self.repo / ".agents" / "project.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        bindings = contract["bindings"]
        bindings["commands"]["suite"] = {"argv": ["python3", "-m", "unittest"],
                                         "cwd": ".", "env": []}
        bindings["workflow"]["verification"] = list(IDS)
        bindings["workflow"].pop("verification_conditions", None)
        if conditions is not ABSENT:
            bindings["workflow"]["verification_conditions"] = conditions
        path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, capture_output=True,
                              text=True, check=True, env=self.env).stdout.strip()

    def commit_all(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def run_tool(self, *args, cwd=None, env=None):
        return subprocess.run([sys.executable, "-m", "agent_tools.verified_tree", *args],
                              cwd=cwd or self.repo, capture_output=True, text=True,
                              check=False, env=env or self.env)

    def check(self, cwd=None):
        done = self.run_tool("check", cwd=cwd)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.count("\n"), 1, done.stdout)
        answer = json.loads(done.stdout)
        self.assertEqual(done.stdout, json.dumps(answer, sort_keys=True,
                                                 separators=(",", ":")) + "\n")
        self.assertEqual(sorted(answer), ["run", "skipped", "status", "tree"])
        return answer

    def record(self, tree, cwd=None):
        return self.run_tool("record", "--tree", tree, cwd=cwd)

    def record_path(self, cwd=None):
        return Path(self.git("rev-parse", "--absolute-git-dir", cwd=cwd)) / "verified-tree.json"

    def plan_path(self, cwd=None):
        return self.record_path(cwd=cwd).with_name("verified-tree-plan.json")

    def recorded_ids(self, cwd=None):
        return json.loads(self.record_path(cwd=cwd).read_text())["verification"]

    def verify_and_record(self, cwd=None):
        tree = self.check(cwd=cwd)["tree"]
        done = self.record(tree, cwd=cwd)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, '{"recorded":true,"tree":"%s"}\n' % tree)
        return tree

    def assert_exit_2(self, done):
        self.assertEqual(done.returncode, 2, done.stdout)
        self.assertEqual(done.stdout, "")
        self.assertEqual(len(done.stderr.strip().splitlines()), 1, done.stderr)

    # Issue 437 AC1: a change outside every listed path.

    def test_a_change_outside_every_listed_path_skips_the_conditional_id(self):
        (self.repo / "tests/test_cli.py").write_text("# edited\n")
        (self.repo / "issues/005-new.md").write_text("# new\n")
        self.git("add", "issues/005-new.md")
        answer = self.check()
        self.assertEqual((answer["run"], answer["skipped"], answer["status"]),
                         (["test"], SKIPPED, "unverified"))
        tree = self.verify_and_record()
        self.assertEqual(self.recorded_ids(), ["test"])
        self.assertEqual(self.check(), {"run": ["test"], "skipped": SKIPPED,
                                        "status": "verified", "tree": tree})

    def test_an_untracked_file_under_a_listed_path_changes_nothing(self):
        (self.repo / "tinytask/scratch.py").write_text("x = 1\n")
        answer = self.check()
        self.assertEqual((answer["run"], answer["skipped"]), (["test"], SKIPPED))
        self.assertEqual(answer["tree"], self.git("rev-parse", "HEAD^{tree}"))

    # Issue 437 AC2: a change to any listed path.

    def test_a_change_to_a_listed_path_runs_the_conditional_id(self):
        changes = {
            "committed edit": lambda: (
                (self.repo / "tinytask/cli.py").write_text("# edited\n"),
                self.commit_all("edit cli")),
            "staged new file": lambda: (
                (self.repo / "tinytask/extra.py").write_text("y = 1\n"),
                self.git("add", "tinytask/extra.py")),
            "tracked working-tree edit": lambda: (
                (self.repo / "tinytask/store.py").write_text("# edited\n")),
            "deletion": lambda: (self.repo / "tinytask/model.py").unlink(),
            "rename out of a listed directory": lambda: (
                self.git("mv", "tinytask/model.py", "model.py")),
            "nested path under a star glob": lambda: (
                (self.repo / "docs/areas/system/adr/001-standard-library-only.md")
                .write_text("# edited\n")),
        }
        for name, change in changes.items():
            with self.subTest(name):
                self.git("reset", "-q", "--hard", "refs/remotes/origin/main")
                self.git("clean", "-qfd")
                change()
                answer = self.check()
                self.assertEqual((answer["run"], answer["skipped"]), (IDS, []))
                self.verify_and_record()
                self.assertEqual(self.recorded_ids(), IDS)
                self.assertEqual(self.check()["status"], "verified")

    def test_a_pass_that_skipped_the_conditional_id_is_unverified_once_a_listed_path_changes(self):
        (self.repo / "README.md").write_text("# edited\n")
        self.verify_and_record()
        self.assertEqual(self.recorded_ids(), ["test"])
        (self.repo / "tinytask/cli.py").write_text("# edited\n")
        self.commit_all("touch a listed path")
        answer = self.check()
        self.assertEqual((answer["run"], answer["skipped"], answer["status"]),
                         (IDS, [], "unverified"))
        # A record of the right tree that lacks a run id is no pass either.
        self.record_path().write_text(json.dumps(
            {"schema": "verified-tree/v1", "tree": answer["tree"], "verification": ["test"]}))
        self.assertEqual(self.check()["status"], "unverified")

    def test_only_the_branchs_own_change_counts_against_the_merge_base(self):
        # Main advances with a listed change the branch has not merged: the
        # merge base stays at the fork, so the change is not the branch's.
        self.git("checkout", "-q", "-b", "upstream")
        (self.repo / "tinytask/cli.py").write_text("# upstream\n")
        self.commit_all("upstream edit")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("checkout", "-q", "main")
        self.assertEqual(self.check()["skipped"], SKIPPED)
        # Once merged, the merge base is main's tip and the change is still main's.
        self.git("merge", "-q", "--no-edit", "upstream")
        self.assertEqual(self.check()["skipped"], SKIPPED)

    def test_a_contract_without_conditions_runs_every_id_and_needs_no_origin_ref(self):
        for conditions in (ABSENT, None, {}):
            with self.subTest(conditions=conditions):
                self.git("reset", "-q", "--hard", "main")
                self.set_conditions(conditions)
                self.commit_all("no conditions")
                self.git("update-ref", "-d", "refs/remotes/origin/main")
                answer = self.check()
                self.assertEqual((answer["run"], answer["skipped"]), (IDS, []))
                self.verify_and_record()
                self.assertEqual(self.recorded_ids(), IDS)

    def test_a_resolver_refusal_exits_2_and_writes_nothing(self):
        self.set_conditions({"suite": {"when_changed": [], "skip_reason": REASON}})
        self.git("add", ".agents/project.json")
        current = self.git("write-tree")
        for argv in (("check",), ("record", "--tree", current)):
            with self.subTest(argv[0]):
                done = self.run_tool(*argv)
                self.assert_exit_2(done)
                self.assertEqual(done.stderr, "verified-tree: resolve-project refused: "
                                 "invalid_contract contract.workflow.empty_path_list\n")
                self.assertFalse(self.record_path().exists())

    def test_a_missing_origin_ref_exits_2_when_an_id_is_conditional(self):
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        tree = self.git("rev-parse", "HEAD^{tree}")
        for argv in (("check",), ("record", "--tree", tree)):
            with self.subTest(argv[0]):
                self.assert_exit_2(self.run_tool(*argv))
                self.assertFalse(self.record_path().exists())

    # Issue 437 final review: `record` writes only the plan `check` printed.

    def test_record_refuses_a_plan_that_changed_since_check(self):
        # Origin moves between check and record while the tree stands still: the
        # recomputed plan now runs `suite`, which the caller skipped and never ran.
        (self.repo / "tinytask/cli.py").write_text("# edited\n")
        self.commit_all("edit cli")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        answer = self.check()
        self.assertEqual((answer["run"], answer["skipped"]), (["test"], SKIPPED))
        self.git("update-ref", "refs/remotes/origin/main", "HEAD~1")
        done = self.record(answer["tree"])
        self.assert_exit_2(done)
        self.assertFalse(self.record_path().exists())
        self.assertEqual(self.check(), {"run": IDS, "skipped": [],
                                        "status": "unverified", "tree": answer["tree"]})

    def test_record_without_a_check_of_that_tree_exits_2(self):
        tree = self.git("rev-parse", "HEAD^{tree}")
        self.assert_exit_2(self.record(tree))
        self.assertFalse(self.record_path().exists())
        # A check of another tree is no check of this one.
        self.check()
        (self.repo / "README.md").write_text("# edited\n")
        self.git("add", "README.md")
        self.assert_exit_2(self.record(self.git("write-tree")))
        self.assertFalse(self.record_path().exists())

    def test_a_malformed_persisted_plan_makes_record_exit_2(self):
        tree = self.check()["tree"]
        good = {"schema": "verified-tree-plan/v1", "tree": tree, "run": ["test"]}
        cases = {
            "not json": "{",
            "extra key": json.dumps({**good, "skipped": []}),
            "wrong schema": json.dumps({**good, "schema": "verified-tree/v1"}),
            "tree not hex": json.dumps({**good, "tree": "HEAD"}),
            "empty run": json.dumps({**good, "run": []}),
        }
        for name, body in cases.items():
            with self.subTest(name):
                self.plan_path().write_text(body)
                self.assert_exit_2(self.record(tree))
                self.assertFalse(self.record_path().exists())

    def test_check_persists_the_plan_it_printed(self):
        answer = self.check()
        self.assertEqual(json.loads(self.plan_path().read_text()),
                         {"schema": "verified-tree-plan/v1", "tree": answer["tree"],
                          "run": answer["run"]})

    def test_record_compares_the_tree_before_resolving(self):
        stale = self.check()["tree"]
        self.set_conditions({"suite": {"when_changed": [], "skip_reason": REASON}})
        self.git("add", ".agents/project.json")
        done = self.record(stale)
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertEqual(done.stdout, '{"reason":"tree_changed","recorded":false,"tree":"%s"}\n'
                         % self.git("write-tree"))
        self.assertFalse(self.record_path().exists())

    # #263 invariants, carried onto the fixture harness.

    def test_no_record_is_unverified_and_names_the_head_tree(self):
        done = self.run_tool("check")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, '{"run":["test"],"skipped":[{"id":"suite","reason":"%s"}],'
                         '"status":"unverified","tree":"%s"}\n'
                         % (REASON, self.git("rev-parse", "HEAD^{tree}")))
        self.assertFalse(self.record_path().exists())

    def test_a_pass_is_recorded_and_then_verified(self):
        tree = self.verify_and_record()
        self.assertEqual(tree, self.git("rev-parse", "HEAD^{tree}"))
        self.assertEqual(json.loads(self.record_path().read_text()),
                         {"schema": "verified-tree/v1", "tree": tree, "verification": ["test"]})
        self.assertEqual(self.check()["status"], "verified")

    def test_any_change_after_the_pass_is_unverified(self):
        changes = {
            "source edit": lambda: (self.repo / "README.md").write_text("# edited\n"),
            "test edit": lambda: (self.repo / "tests/test_cli.py").write_text("# edited\n"),
            "staged new file": lambda: ((self.repo / "new.py").write_text("y = 1\n"),
                                        self.git("add", "new.py")),
            "deleted file": lambda: (self.repo / "README.md").unlink(),
        }
        for name, change in changes.items():
            with self.subTest(name):
                self.git("reset", "-q", "--hard")
                self.git("clean", "-qfd")
                tree = self.verify_and_record()
                change()
                answer = self.check()
                self.assertEqual(answer["status"], "unverified")
                self.assertNotEqual(answer["tree"], tree)

    def test_an_untracked_file_is_outside_the_tree_until_it_is_committed(self):
        # The tree is what a Git-backed build sees, and that build excludes
        # untracked files: one leaves the pass standing, and committing it
        # changes the tree, so the next check asks for verification again.
        tree = self.verify_and_record()
        (self.repo / "new.py").write_text("y = 1\n")
        self.assertEqual(self.check()["status"], "verified")
        self.git("add", "new.py")
        self.git("commit", "-q", "-m", "add new.py")
        answer = self.check()
        self.assertEqual(answer["status"], "unverified")
        self.assertEqual(answer["tree"], self.git("rev-parse", "HEAD^{tree}"))
        self.assertNotEqual(answer["tree"], tree)

    def test_a_staged_new_file_is_part_of_the_tree(self):
        (self.repo / "staged.py").write_text("s = 1\n")
        self.git("add", "staged.py")
        tree = self.check()["tree"]
        self.assertEqual(self.git("ls-tree", "--name-only", tree, "staged.py"), "staged.py")
        self.assertEqual(tree, self.git("write-tree"))

    def test_an_ignored_file_leaves_the_tree_verified(self):
        tree = self.verify_and_record()
        (self.repo / "tasks.json").write_text("[]\n")
        self.assertEqual(self.check(), {"run": ["test"], "skipped": SKIPPED,
                                        "status": "verified", "tree": tree})

    def test_a_mismatched_tree_is_refused_and_the_record_kept(self):
        tree = self.verify_and_record()
        before = self.record_path().read_bytes()
        (self.repo / "README.md").write_text("# edited again\n")
        current = self.check()["tree"]
        done = self.record(tree)
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertEqual(done.stdout,
                         '{"reason":"tree_changed","recorded":false,"tree":"%s"}\n' % current)
        self.assertEqual(self.record_path().read_bytes(), before)

    def test_a_same_tree_record_under_another_id_list_is_unverified(self):
        tree = self.verify_and_record()
        for ids in (["test", "suite"], ["suite", "test"], ["suite"], ["test", "lint"]):
            with self.subTest(run=["test"], ids=ids):
                self.record_path().write_text(json.dumps(
                    {"schema": "verified-tree/v1", "tree": tree, "verification": ids}) + "\n")
                self.assertEqual(self.check(), {"run": ["test"], "skipped": SKIPPED,
                                                "status": "unverified", "tree": tree})
        (self.repo / "tinytask/cli.py").write_text("# edited\n")
        tree = self.verify_and_record()
        self.assertEqual(self.recorded_ids(), IDS)
        for ids in (["suite", "test"], ["test"], [*IDS, "lint"]):
            with self.subTest(run=IDS, ids=ids):
                self.record_path().write_text(json.dumps(
                    {"schema": "verified-tree/v1", "tree": tree, "verification": ids}) + "\n")
                self.assertEqual(self.check(), {"run": IDS, "skipped": [],
                                                "status": "unverified", "tree": tree})

    def test_a_refused_first_record_writes_no_file(self):
        stale = self.check()["tree"]
        (self.repo / "README.md").write_text("# edited\n")
        self.assertEqual(self.record(stale).returncode, 3)
        self.assertFalse(self.record_path().exists())

    def test_an_uncommitted_verified_edit_stays_verified_once_committed(self):
        (self.repo / "tinytask/cli.py").write_text("# edited\n")
        (self.repo / "added.py").write_text("z = 1\n")
        self.git("add", "added.py")
        tree = self.verify_and_record()
        self.assertNotEqual(tree, self.git("rev-parse", "HEAD^{tree}"))
        self.commit_all("fix")
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}"), tree)
        self.assertEqual(self.check(), {"run": IDS, "skipped": [],
                                        "status": "verified", "tree": tree})

    def test_neither_verb_touches_the_real_index(self):
        (self.repo / "tinytask/cli.py").write_text("# edited\n")
        (self.repo / "new.py").write_text("n = 1\n")
        status = self.git("status", "--porcelain")
        index = Path(self.git("rev-parse", "--absolute-git-dir")) / "index"
        before = index.read_bytes()
        self.verify_and_record()
        self.assertEqual(index.read_bytes(), before)
        self.assertEqual(self.git("status", "--porcelain"), status)

    def test_the_record_lives_in_a_linked_worktrees_own_git_dir(self):
        linked = self.scratch / "linked"
        self.git("worktree", "add", "-q", "-b", "side", str(linked))
        tree = self.verify_and_record(cwd=linked)
        self.assertTrue(self.record_path(cwd=linked).is_file())
        self.assertFalse(self.record_path().exists())
        self.assertEqual(self.check()["status"], "unverified")
        self.assertEqual(self.check(cwd=linked), {"run": ["test"], "skipped": SKIPPED,
                                                  "status": "verified", "tree": tree})

    def test_a_malformed_record_makes_check_exit_2(self):
        tree = self.git("rev-parse", "HEAD^{tree}")
        good = {"schema": "verified-tree/v1", "tree": tree, "verification": ["test"]}
        cases = {
            "not json": "{",
            "duplicate key": '{"schema":"verified-tree/v1","schema":"verified-tree/v1",'
                             '"tree":"%s","verification":["test"]}' % tree,
            "non-finite literal": '{"schema":"verified-tree/v1","tree":"%s",'
                                  '"verification":["test"],"x":NaN}' % tree,
            "not an object": json.dumps([good]),
            "extra key": json.dumps({**good, "head": "x"}),
            "missing key": json.dumps({k: v for k, v in good.items() if k != "verification"}),
            "wrong schema": json.dumps({**good, "schema": "verified-tree/v2"}),
            "tree not a string": json.dumps({**good, "tree": 7}),
            "tree not hex": json.dumps({**good, "tree": "HEAD"}),
            "empty verification": json.dumps({**good, "verification": []}),
            "non-string id": json.dumps({**good, "verification": ["test", 1]}),
            "empty id": json.dumps({**good, "verification": [""]}),
        }
        for name, body in cases.items():
            with self.subTest(name):
                self.record_path().write_text(body)
                self.assert_exit_2(self.run_tool("check"))

    def test_outside_a_git_worktree_both_verbs_exit_2(self):
        outside = self.scratch / "outside"
        outside.mkdir()
        env = {**self.env, "GIT_CEILING_DIRECTORIES": str(self.scratch)}
        for argv in (("check",), ("record", "--tree", "0" * 40)):
            with self.subTest(argv[0]):
                done = self.run_tool(*argv, cwd=outside, env=env)
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stdout, "")

    def test_usage_errors_exit_2(self):
        # Issue 437 D13: `--verification` is gone, with no compatibility handling.
        tree = self.git("rev-parse", "HEAD^{tree}")
        for argv in ((), ("record",), ("forget",), ("check", "--verification", "test"),
                     ("record", "--tree", tree, "--verification", "test")):
            with self.subTest(argv=argv):
                done = self.run_tool(*argv)
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stdout, "")
                self.assertFalse(self.record_path().exists())


if __name__ == "__main__":
    unittest.main()
