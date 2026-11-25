"""verified-tree: a verification pass recorded against the tree it saw (#263, issue 437).

Each test drives `python -m agent_tools.verification.verified_tree` in a throwaway git
repository, the way the other command tests drive theirs (#263 D6). The
repository is a copy of the eval fixture project whose contract gains a second,
conditional verification id, resolved under a temporary HOME holding the
committed platform manifest, with
`refs/remotes/origin/main` at the base commit (issue 437 D12).
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from unittest import mock

from agent_tools.delivery import touched_tests
from agent_tools.verification import verified_tree

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
RECORD = ".agents/artifacts/plans/p.acceptance.md"


class ProjectCase(unittest.TestCase):
    """A committed copy of the fixture project, its contract and git helpers."""

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


class VerifiedTreeTest(ProjectCase):
    def run_tool(self, *args, cwd=None, env=None):
        return subprocess.run([sys.executable, "-m", "agent_tools.verification.verified_tree", *args],
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
        for conditions in (ABSENT, None, {}, {"suite": {"pre_commit": True}}):
            with self.subTest(conditions=conditions):
                self.git("reset", "-q", "--hard", "main")
                self.set_conditions(conditions)
                self.commit_all("no conditions")
                self.git("update-ref", "-d", "refs/remotes/origin/main")
                answer = self.check()
                self.assertEqual((answer["run"], answer["skipped"]), (IDS, []))
                self.verify_and_record()
                self.assertEqual(self.recorded_ids(), IDS)

    def test_a_pre_commit_flag_leaves_the_condition_in_force(self):
        # Issue 771 D3: the flag beside when_changed changes nothing about the skip.
        self.set_conditions({"suite": {**CONDITIONS["suite"], "pre_commit": True}})
        self.commit_all("flag the conditional id")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        (self.repo / "tests/test_cli.py").write_text("# edited\n")
        answer = self.check()
        self.assertEqual((answer["run"], answer["skipped"]), (["test"], SKIPPED))

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

    def test_a_later_check_of_the_tree_cannot_widen_a_pending_plan(self):
        # Caller A checks and is told to skip `suite`; origin moves and caller B
        # checks the same tree and is told to run it. Whoever records next must
        # not record `suite`, which A never ran.
        (self.repo / "tinytask/cli.py").write_text("# edited\n")
        self.commit_all("edit cli")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        first = self.check()
        self.assertEqual(first["run"], ["test"])
        tree = first["tree"]
        self.git("update-ref", "refs/remotes/origin/main", "HEAD~1")
        self.assertEqual(self.check()["run"], IDS)
        self.assertEqual(json.loads(self.plan_path().read_text())["run"], ["test"])
        self.assert_exit_2(self.record(tree))
        self.assertFalse(self.record_path().exists())
        # The refusal consumed the pending plan, so a fresh check backs a record.
        self.assertFalse(self.plan_path().exists())
        self.verify_and_record()
        self.assertEqual(self.recorded_ids(), IDS)

    def test_a_later_narrower_check_records_only_the_ids_both_ran(self):
        (self.repo / "tinytask/cli.py").write_text("# edited\n")
        self.commit_all("edit cli")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD~1")
        self.assertEqual(self.check()["run"], IDS)
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        tree = self.verify_and_record()
        self.assertEqual(self.recorded_ids(), ["test"])
        self.assertEqual(self.check(), {"run": ["test"], "skipped": SKIPPED,
                                        "status": "verified", "tree": tree})

    def test_record_consumes_the_plan_it_recorded(self):
        tree = self.verify_and_record()
        self.assertFalse(self.plan_path().exists())
        self.assert_exit_2(self.record(tree))
        self.assertEqual(self.recorded_ids(), ["test"])

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

    def test_outside_a_git_worktree_every_verb_exits_2(self):
        outside = self.scratch / "outside"
        outside.mkdir()
        env = {**self.env, "GIT_CEILING_DIRECTORIES": str(self.scratch)}
        for argv in (("check",), ("record", "--tree", "0" * 40),
                     ("fresh", "--since", "HEAD", "--record", RECORD)):
            with self.subTest(argv[0]):
                done = self.run_tool(*argv, cwd=outside, env=env)
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stdout, "")

    def test_usage_errors_exit_2(self):
        # Issue 437 D13: `--verification` is gone, with no compatibility handling.
        tree = self.git("rev-parse", "HEAD^{tree}")
        for argv in ((), ("record",), ("forget",), ("check", "--verification", "test"),
                     ("record", "--tree", tree, "--verification", "test"),
                     ("fresh",), ("fresh", "--since", "HEAD"), ("fresh", "--record", RECORD),
                     ("fresh", "--since", "HEAD", "--record", RECORD, "extra")):
            with self.subTest(argv=argv):
                done = self.run_tool(*argv)
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stdout, "")
                self.assertFalse(self.record_path().exists())

    # Issue 477: `fresh` judges evidence measured at a commit against the content it measured.

    def fresh(self, since, record=RECORD, cwd=None):
        done = self.run_tool("fresh", "--since", since, "--record", record, cwd=cwd)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, "")
        answer = json.loads(done.stdout)
        self.assertEqual(done.stdout, json.dumps(answer, sort_keys=True,
                                                 separators=(",", ":")) + "\n")
        self.assertEqual(sorted(answer), ["changed", "since", "status", "tree"])
        return answer

    def write_record(self, text):
        path = self.repo / RECORD
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def answer(self, changed, since):
        """The `fresh` output for a clean worktree at HEAD."""
        return {"changed": changed, "since": since,
                "status": "stale" if changed else "fresh",
                "tree": self.git("rev-parse", "HEAD^{tree}")}

    def test_a_commit_that_changes_only_the_record_stays_fresh(self):
        # Issue 477 AC1: today there is no `fresh` verb, so this exits 2.
        since = self.git("rev-parse", "HEAD")
        self.write_record("| AC1 | met |\n")
        self.commit_all("acceptance record")
        self.assertEqual(self.fresh(since), self.answer([], since))
        self.write_record("| AC1 | met |\n| AC2 | met |\n")
        self.commit_all("acceptance record again")
        self.assertEqual(self.fresh(since), self.answer([], since))

    def test_a_commit_that_changes_a_measured_file_is_stale(self):
        # Issue 477 AC2.
        since = self.git("rev-parse", "HEAD")
        self.write_record("| AC1 | met |\n")
        (self.repo / "tinytask/cli.py").write_text("# edited\n")
        self.commit_all("edit cli")
        self.assertEqual(self.fresh(since), self.answer(["tinytask/cli.py"], since))

    def test_a_tracked_edit_is_measured_and_an_untracked_file_is_not(self):
        since = self.git("rev-parse", "HEAD")
        (self.repo / "tinytask/scratch.py").write_text("x = 1\n")
        self.assertEqual(self.fresh(since), self.answer([], since))
        (self.repo / "tinytask/cli.py").write_text("# edited\n")
        answer = self.fresh(since)
        self.assertEqual((answer["changed"], answer["status"]), (["tinytask/cli.py"], "stale"))
        self.assertNotEqual(answer["tree"], self.git("rev-parse", "HEAD^{tree}"))

    def test_a_reverted_change_is_fresh_again(self):
        since = self.git("rev-parse", "HEAD")
        (self.repo / "tinytask/cli.py").write_text("# edited\n")
        self.commit_all("edit cli")
        self.git("revert", "--no-edit", "HEAD")
        self.assertEqual(self.fresh(since[:12]), self.answer([], since))

    def test_a_merge_that_changes_a_measured_path_is_stale(self):
        since = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "-b", "side")
        (self.repo / "tinytask/store.py").write_text("# edited\n")
        self.commit_all("edit store")
        self.git("checkout", "-q", "main")
        self.write_record("| AC1 | met |\n")
        self.commit_all("acceptance record")
        self.git("merge", "-q", "--no-ff", "-m", "merge side", "side")
        self.assertEqual(self.fresh(since), self.answer(["tinytask/store.py"], since))

    def test_a_rename_lists_both_paths_and_a_deletion_counts(self):
        since = self.git("rev-parse", "HEAD")
        self.git("mv", "tinytask/model.py", "tinytask/models.py")
        self.git("rm", "-q", "docs/README.md")
        self.git("commit", "-q", "-m", "rename and delete")
        self.assertEqual(self.fresh(since), self.answer(
            ["docs/README.md", "tinytask/model.py", "tinytask/models.py"], since))

    def test_the_record_path_resolves_against_the_current_directory(self):
        since = self.git("rev-parse", "HEAD")
        self.write_record("| AC1 | met |\n")
        self.commit_all("acceptance record")
        subdir = self.repo / "tinytask"
        self.assertEqual(self.fresh(since, record="../" + RECORD, cwd=subdir),
                         self.answer([], since))
        self.assertEqual(self.fresh(since, record=str(self.repo / RECORD), cwd=subdir),
                         self.answer([], since))
        self.assertEqual(self.fresh(since, record="p.acceptance.md", cwd=subdir),
                         self.answer([RECORD], since))

    def test_fresh_reads_no_project_contract(self):
        since = self.git("rev-parse", "HEAD")
        (self.repo / ".agents/project.json").unlink()
        answer = self.fresh(since)
        self.assertEqual((answer["changed"], answer["status"]),
                         ([".agents/project.json"], "stale"))

    def test_fresh_changes_no_file(self):
        self.verify_and_record()
        self.check()
        (self.repo / "tinytask/cli.py").write_text("# edited\n")
        (self.repo / "new.py").write_text("n = 1\n")
        status = self.git("status", "--porcelain")
        index = Path(self.git("rev-parse", "--absolute-git-dir")) / "index"
        files = [index, self.record_path(), self.plan_path()]
        before = [path.read_bytes() for path in files]
        self.fresh(self.git("rev-parse", "HEAD"))
        self.assertEqual([path.read_bytes() for path in files], before)
        self.assertEqual(self.git("status", "--porcelain"), status)

    def test_fresh_refuses_a_non_commit_or_a_record_outside_the_worktree(self):
        (self.repo / "link").symlink_to(self.scratch)
        head = self.git("rev-parse", "HEAD")
        tree = self.git("rev-parse", "HEAD^{tree}")
        outside = str(self.scratch / "elsewhere.md")
        def since(value):
            return f"verified-tree: --since {value} names no commit\n"
        def record(value):
            return f"verified-tree: --record {value} is not a path inside the worktree {self.repo}\n"
        cases = {
            "unknown revision": (("--since", "no-such-ref", "--record", RECORD),
                                 since("no-such-ref")),
            "option-shaped revision": (("--since=--all", "--record", RECORD), since("--all")),
            "a tree, not a commit": (("--since", tree, "--record", RECORD), since(tree)),
            "absolute path outside": (("--since", head, "--record", outside), record(outside)),
            "relative path outside": (("--since", head, "--record", "../elsewhere.md"),
                                      record("../elsewhere.md")),
            "symlink out of the worktree": (("--since", head, "--record", "link/r.md"),
                                            record("link/r.md")),
            "the top level itself": (("--since", head, "--record", "."), record(".")),
            "both invalid: --since is checked first": (
                ("--since", "no-such-ref", "--record", "../elsewhere.md"), since("no-such-ref")),
        }
        for name, (argv, stderr) in cases.items():
            with self.subTest(name):
                done = self.run_tool("fresh", *argv)
                self.assert_exit_2(done)
                self.assertEqual(done.stderr, stderr)
                self.assertFalse(self.record_path().exists())
                self.assertFalse(self.plan_path().exists())


class RunTest(ProjectCase):
    """`verified-tree run`: every declared id once, in the worktree, in a verify slot."""

    def setUp(self):
        super().setUp()
        self.log = self.scratch / "log"
        self.slots = self.scratch / "slots"
        self.env["VERIFY_SLOT_DIR"] = str(self.slots)
        self.worktree = self.scratch / "linked"

    def command(self, verification_id, extra=""):
        """A contract command appending `<cwd> <id>` to the log, then running `extra`."""
        code = (f"import os,sys;open({str(self.log)!r},'a').write(os.getcwd()+' {verification_id}'+chr(10));"
                + extra)
        return {"argv": [sys.executable, "-c", code], "cwd": ".", "env": []}

    def declare(self, commands, conditions=ABSENT, before=ABSENT, cwds=None):
        """Commit a contract declaring `commands` (id -> extra code), publish it, add the worktree.

        `cwds` maps an id to the directory (relative to the root) its command runs in."""
        path = self.repo / ".agents" / "project.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        bindings = contract["bindings"]
        bindings["commands"] = {name: self.command(name, extra) for name, extra in commands.items()}
        for name, cwd in (cwds or {}).items():
            bindings["commands"][name]["cwd"] = cwd
            (self.repo / cwd).mkdir(parents=True, exist_ok=True)
            (self.repo / cwd / ".keep").write_text("\n")
        bindings["workflow"]["verification"] = list(commands)
        bindings["workflow"].pop("verification_conditions", None)
        if conditions is not ABSENT:
            bindings["workflow"]["verification_conditions"] = conditions
        if before is not ABSENT:
            bindings["workflow"]["verification_before_pull_request"] = before
        else:
            bindings["workflow"].pop("verification_before_pull_request", None)
        path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
        self.commit_all("declare")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("worktree", "add", "-q", "-b", "work", str(self.worktree))

    def run_verified(self, *extra):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.verification.verified_tree", "run",
             "--worktree-path", str(self.worktree), *extra],
            cwd=self.repo, capture_output=True, text=True, check=False, env=self.env)

    def answer(self, done, exit_code=0):
        self.assertEqual(done.returncode, exit_code, done.stderr)
        self.assertEqual(done.stdout.count("\n"), 1, done.stdout)
        return json.loads(done.stdout)

    def logged(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_run_runs_every_declared_id_once_in_the_worktree_and_passes(self):
        self.declare({"lint": "", "test": ""})
        answer = self.answer(self.run_verified())
        self.assertEqual(answer["verdict"], "passed")
        self.assertIs(answer["clean"], True)
        self.assertEqual(answer["head"], self.git("rev-parse", "HEAD", cwd=self.worktree))
        self.assertEqual([r["id"] for r in answer["results"]], ["lint", "test"])
        self.assertEqual([(r["status"], r["exit"]) for r in answer["results"]],
                         [("pass", 0), ("pass", 0)])
        where = str(self.worktree.resolve())
        self.assertEqual(self.logged(), [f"{where} lint", f"{where} test"])

    def recorded(self):
        """The record file's text in the worktree's own git directory, or None when absent."""
        path = Path(self.git("rev-parse", "--absolute-git-dir", cwd=self.worktree)) / "verified-tree.json"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def test_a_passed_run_records_its_tree_and_check_answers_verified(self):
        self.declare({"lint": "", "test": ""})
        answer = self.answer(self.run_verified())
        self.assertEqual(answer["verdict"], "passed")
        self.assertEqual(json.loads(self.recorded()),
                         {"schema": "verified-tree/v1", "tree": answer["tree"],
                          "verification": ["lint", "test"]})
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.verification.verified_tree", "check"],
            cwd=self.worktree, capture_output=True, text=True, check=False, env=self.env)
        self.assertEqual(done.returncode, 0, done.stderr)
        checked = json.loads(done.stdout)
        self.assertEqual((checked["status"], checked["tree"]), ("verified", answer["tree"]))

    def test_a_failed_run_records_nothing(self):
        self.declare({"lint": "sys.exit(3)", "test": ""})
        self.assertEqual(self.answer(self.run_verified())["verdict"], "failed")
        self.assertIsNone(self.recorded())

    def test_a_failing_id_fails_the_run_and_the_others_still_run_and_it_is_rerun_once(self):
        self.declare({"lint": "print('boom');sys.exit(3)", "test": ""})
        answer = self.answer(self.run_verified())
        lint, test = answer["results"]
        self.assertEqual(answer["verdict"], "failed")
        self.assertEqual((lint["status"], lint["exit"]), ("fail", 3))
        self.assertIn("boom", lint["summary"])
        self.assertEqual(test["status"], "pass")
        self.assertIs(lint["reran"], True)
        where = str(self.worktree.resolve())
        self.assertEqual(self.logged(), [f"{where} lint", f"{where} test", f"{where} lint"])

    def test_an_id_whose_condition_matches_no_changed_path_is_skipped_with_its_reason(self):
        reason = "no documentation changed"
        self.declare({"lint": "", "test": ""},
                     {"lint": {"when_changed": ["docs/**"], "skip_reason": reason}})
        (self.worktree / "src").mkdir()
        (self.worktree / "src" / "x.py").write_text("x = 1\n")
        self.git("add", "-A", cwd=self.worktree)
        self.git("commit", "-q", "-m", "change", cwd=self.worktree)
        answer = self.answer(self.run_verified())
        lint, test = answer["results"]
        self.assertEqual((lint["id"], lint["status"], lint["reason"]), ("lint", "skipped", reason))
        self.assertNotIn("exit", lint)
        self.assertEqual((test["status"], answer["verdict"]), ("pass", "passed"))
        self.assertEqual(self.logged(), [f"{self.worktree.resolve()} test"])

    def test_a_dirty_tree_runs_nothing(self):
        self.declare({"lint": "", "test": ""})
        (self.worktree / "stray.txt").write_text("x\n")
        answer = self.answer(self.run_verified())
        self.assertEqual((answer["verdict"], answer["results"], answer["clean"]),
                         ("dirty", [], False))
        self.assertFalse(self.log.exists())

    def test_a_command_that_leaves_the_tree_dirty_is_dirty(self):
        self.declare({"lint": "", "test": "open('left-over.txt','w').write('x')"})
        answer = self.answer(self.run_verified())
        self.assertEqual((answer["verdict"], answer["clean"]), ("dirty", False))
        self.assertEqual([r["status"] for r in answer["results"]], ["pass", "pass"])

    def test_no_slot_is_retried_then_failed_with_no_slot(self):
        self.declare({"lint": "sys.exit(75)", "test": ""})
        env = {**HERMETIC_GIT, "HOME": self.env["HOME"], "VERIFY_SLOT_DIR": str(self.slots)}
        out = StringIO()
        with (mock.patch.dict(os.environ, env), mock.patch.object(verified_tree, "SLOT_ATTEMPTS", 2),
              redirect_stdout(out), mock.patch("sys.stderr", StringIO())):
            status = verified_tree.main(["run", "--worktree-path", str(self.worktree)])
        answer = self.answer(subprocess.CompletedProcess([], status, out.getvalue(), ""))
        lint, test = answer["results"]
        self.assertEqual((lint["status"], lint["no_slot"]), ("fail", True))
        self.assertEqual(lint["summary"], "no verify slot came free in 2 attempts")
        self.assertEqual(test["status"], "pass")
        where = str(self.worktree.resolve())
        self.assertEqual(self.logged(), [f"{where} lint", f"{where} lint", f"{where} test"])

    def assert_slot_seconds(self, result):
        for member in ("waited_seconds", "held_seconds"):
            value = result[member]
            self.assertIsInstance(value, (int, float), result)
            self.assertNotIsInstance(value, bool)
            self.assertGreaterEqual(value, 0)

    def test_run_runs_the_pre_pull_request_ids_and_reports_each_commands_slot_seconds_and_selection(self):
        write = ("import json;open(os.environ['VERIFIED_TREE_SELECTION'],'w')"
                 ".write(json.dumps({'selected':['t.py']}))")
        self.declare({"lint": "", "test": write, "suite": ""}, before=["lint", "test"])
        answer = self.answer(self.run_verified())
        self.assertEqual([r["id"] for r in answer["results"]], ["lint", "test"])
        where = str(self.worktree.resolve())
        self.assertEqual(self.logged(), [f"{where} lint", f"{where} test"])
        for result in answer["results"]:
            self.assert_slot_seconds(result)
        self.assertEqual(answer["results"][1]["selection"], {"selected": ["t.py"]})
        self.assertNotIn("selection", answer["results"][0])

    def test_without_the_binding_run_runs_every_verification_id_with_its_slot_seconds(self):
        self.declare({"lint": "", "test": ""})
        answer = self.answer(self.run_verified())
        self.assertEqual([r["id"] for r in answer["results"]], ["lint", "test"])
        for result in answer["results"]:
            self.assert_slot_seconds(result)
        where = str(self.worktree.resolve())
        self.assertEqual(self.logged(), [f"{where} lint", f"{where} test"])

    def test_a_selection_that_is_not_a_json_object_is_left_out(self):
        write = "open(os.environ['VERIFIED_TREE_SELECTION'],'w').write('[1]')"
        self.declare({"lint": "", "test": write})
        answer = self.answer(self.run_verified())
        for result in answer["results"]:
            self.assertNotIn("selection", result)

    def test_a_condition_skip_carries_no_seconds(self):
        self.declare({"lint": "", "test": ""},
                     {"lint": {"when_changed": ["docs/**"], "skip_reason": "no docs"}})
        (self.worktree / "src").mkdir()
        (self.worktree / "src" / "x.py").write_text("x = 1\n")
        self.git("add", "-A", cwd=self.worktree)
        self.git("commit", "-q", "-m", "change", cwd=self.worktree)
        lint, _ = self.answer(self.run_verified())["results"]
        self.assertEqual(lint["status"], "skipped")
        for member in ("waited_seconds", "held_seconds", "selection"):
            self.assertNotIn(member, lint)

    def run_in_process(self, **patches):
        """`main(["run", ...])` in this process under `patches` of module constants: (answer, seconds)."""
        env = {**HERMETIC_GIT, "HOME": self.env["HOME"], "VERIFY_SLOT_DIR": str(self.slots)}
        out = StringIO()
        began = time.monotonic()
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, env))
            for name, value in patches.items():
                stack.enter_context(mock.patch.object(verified_tree, name, value))
            stack.enter_context(redirect_stdout(out))
            self.stderr = StringIO()
            stack.enter_context(mock.patch("sys.stderr", self.stderr))
            status = verified_tree.main(["run", "--worktree-path", str(self.worktree)])
        seconds = time.monotonic() - began
        return self.answer(subprocess.CompletedProcess([], status, out.getvalue(), "")), seconds

    def test_a_timed_out_command_that_ignores_sigterm_is_still_failed_as_timed_out(self):
        ignore = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)"
        self.declare({"lint": ignore, "test": ""})
        answer, seconds = self.run_in_process(COMMAND_TIMEOUT_SECONDS=1, TERMINATE_GRACE_SECONDS=1)
        lint, test = answer["results"]
        self.assertEqual((lint["status"], lint["summary"]), ("fail", "timed out after 1 s"))
        self.assertEqual(test["status"], "pass")
        self.assertLess(seconds, 20)

    def test_a_descendant_holding_the_output_does_not_turn_a_passing_command_into_a_timeout(self):
        leave = "import subprocess;subprocess.Popen(['sleep','30']);sys.exit(0)"
        self.declare({"lint": leave, "test": ""})
        answer, seconds = self.run_in_process(COMMAND_TIMEOUT_SECONDS=10)
        lint, _ = answer["results"]
        self.assertEqual((lint["status"], lint["exit"]), ("pass", 0))
        self.assertLess(seconds, 20)

    def test_a_path_outside_any_worktree_is_an_error(self):
        empty = self.scratch / "empty"
        empty.mkdir()
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.verification.verified_tree", "run",
             "--worktree-path", str(empty)],
            cwd=self.repo, capture_output=True, text=True, check=False, env=self.env)
        answer = self.answer(done, 1)
        self.assertEqual(answer["verdict"], "error")
        self.assertTrue(answer["detail"])

    def test_a_usage_error_is_an_error_verdict_too(self):
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.verification.verified_tree", "run"],
            cwd=self.repo, capture_output=True, text=True, check=False, env=self.env)
        self.assertEqual(self.answer(done, 1)["verdict"], "error")

    # Issue 1536: a failure outside the branch's files is rerun once, at one head.

    def branch_change(self, files):
        """Commit `files` (path -> text) in the worktree: the branch's changed paths."""
        for name, text in files.items():
            path = self.worktree / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.git("add", "-A", cwd=self.worktree)
        self.git("commit", "-q", "-m", "branch change", cwd=self.worktree)

    def once(self, first="boom", then=None, exit_first=1, exit_then=0):
        """Code failing with `first` the first time it runs and with `then` (silent when None) after."""
        flag = self.scratch / "once"
        return (f"p={str(flag)!r};seen=os.path.exists(p);open(p,'w').close();"
                f"print({first!r} if not seen else {then or ''!r});"
                f"sys.exit({exit_first} if not seen else {exit_then})")

    def test_an_id_failing_outside_the_branchs_files_is_rerun_once_and_its_pass_is_recorded_flaky(self):
        self.declare({"lint": "", "test": self.once()})
        self.branch_change({"notes.txt": "x\n"})
        answer = self.answer(self.run_verified())
        lint, test = answer["results"]
        self.assertEqual(answer["verdict"], "passed")
        self.assertEqual((test["status"], test["flaky"]), ("pass", "boom"))
        self.assertNotIn("flaky", lint)
        where = str(self.worktree.resolve())
        self.assertEqual(self.logged(), [f"{where} lint", f"{where} test", f"{where} test"])

    def test_a_failure_whose_output_names_a_changed_path_is_not_rerun(self):
        self.declare({"lint": "", "test": "print('notes.txt:12: broken');sys.exit(1)"})
        self.branch_change({"notes.txt": "x\n"})
        answer = self.answer(self.run_verified())
        test = answer["results"][1]
        self.assertEqual(answer["verdict"], "failed")
        self.assertEqual((test["named"], test["outside_diff"]), (["notes.txt"], False))
        self.assertNotIn("reran", test)
        self.assertEqual(self.logged().count(f"{self.worktree.resolve()} test"), 1)

    def test_a_changed_path_inside_a_longer_name_is_not_named(self):
        cases = {"a.py": "data.py failed", "notes.txt": "notes.txt.bak failed"}
        for changed, output in cases.items():
            with self.subTest(changed):
                if self.log.exists():
                    self.log.unlink()
                (self.scratch / "once").unlink(missing_ok=True)
                if not self.worktree.exists():
                    self.declare({"lint": "", "test": self.once(output)})
                else:
                    self.git("reset", "-q", "--hard", "origin/main", cwd=self.worktree)
                    command = self.command("test", self.once(output))
                    contract = self.worktree / ".agents" / "project.json"
                    document = json.loads(contract.read_text(encoding="utf-8"))
                    document["bindings"]["commands"]["test"] = command
                    contract.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
                    self.git("commit", "-q", "-am", "output", cwd=self.worktree)
                self.branch_change({changed: "x\n"})
                test = self.answer(self.run_verified())["results"][1]
                self.assertEqual((test["status"], test["flaky"]), ("pass", output))

    def test_a_wrapper_status_line_naming_a_changed_path_does_not_name_it(self):
        line = "test-touched: building with just build: notes.txt changed"
        self.declare({"lint": "", "test": self.once(line)})
        self.branch_change({"notes.txt": "x\n"})
        test = self.answer(self.run_verified())["results"][1]
        self.assertEqual((test["status"], test["flaky"]), ("pass", line))

    def test_a_path_relative_to_the_commands_cwd_is_named(self):
        self.declare({"lint": "", "test": "print('notes.txt:1: broken');sys.exit(1)"},
                     cwds={"test": "sub"})
        self.branch_change({"sub/notes.txt": "x\n"})
        test = self.answer(self.run_verified())["results"][1]
        self.assertEqual(test["named"], ["sub/notes.txt"])
        self.assertEqual(self.logged().count(f"{self.worktree.resolve() / 'sub'} test"), 1)

    def test_a_rerun_that_fails_again_keeps_the_first_failure_marked_reran(self):
        flag = self.scratch / "again"
        code = (f"p={str(flag)!r};seen=os.path.exists(p);open(p,'w').close();"
                "print('second' if seen else 'first');sys.exit(1)")
        self.declare({"lint": "", "test": code})
        self.branch_change({"notes.txt": "x\n"})
        answer = self.answer(self.run_verified())
        test = answer["results"][1]
        self.assertEqual(answer["verdict"], "failed")
        self.assertEqual(test["summary"], "first")
        self.assertIs(test["reran"], True)
        self.assertIs(test["outside_diff"], True)
        self.assertEqual(self.logged().count(f"{self.worktree.resolve()} test"), 2)

    def test_one_failure_inside_the_diff_keeps_every_failure_from_a_rerun(self):
        self.declare({"lint": "print('x');sys.exit(1)", "test": "print('notes.txt');sys.exit(1)"})
        self.branch_change({"notes.txt": "x\n"})
        lint, test = self.answer(self.run_verified())["results"]
        where = str(self.worktree.resolve())
        self.assertEqual(self.logged(), [f"{where} lint", f"{where} test"])
        self.assertIs(lint["outside_diff"], True)
        self.assertIs(test["outside_diff"], False)
        for entry in (lint, test):
            self.assertNotIn("flaky", entry)
            self.assertNotIn("reran", entry)

    def test_without_the_integration_ref_no_failure_is_outside_the_diff(self):
        self.declare({"lint": "", "test": self.once()})
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        answer = self.answer(self.run_verified())
        test = answer["results"][1]
        self.assertEqual(answer["verdict"], "failed")
        self.assertEqual((test["outside_diff"], test["named"]), (False, []))
        self.assertEqual(self.logged().count(f"{self.worktree.resolve()} test"), 1)

    def second_run(self, effect):
        """Code failing (printing boom) on its first run and running `effect`, passing, on its second."""
        flag = self.scratch / "second"
        return (f"p={str(flag)!r};seen=os.path.exists(p);open(p,'w').close();"
                f"{effect} if seen else (print('boom'),sys.exit(1))")

    def test_a_rerun_that_leaves_the_tree_dirty_keeps_the_first_results(self):
        self.declare({"lint": "", "test": self.second_run("open('stray.txt','w').write('x')")})
        self.branch_change({"notes.txt": "x\n"})
        answer = self.answer(self.run_verified())
        test = answer["results"][1]
        self.assertEqual((answer["verdict"], answer["clean"]), ("failed", False))
        self.assertEqual((test["status"], test["summary"]), ("fail", "boom"))
        self.assertNotIn("flaky", test)

    def test_a_rerun_that_moves_a_clean_head_keeps_the_first_failure_and_records_nothing(self):
        move = ("subprocess.run(['git','commit','-q','--allow-empty','-m','moved'],check=True)")
        self.declare({"lint": "", "test": "import subprocess;" + self.second_run(move)})
        self.branch_change({"notes.txt": "x\n"})
        answer = self.answer(self.run_verified())
        test = answer["results"][1]
        moved = self.git("rev-parse", "HEAD", cwd=self.worktree)
        self.assertNotEqual(moved, answer["head"])
        self.assertEqual(answer["verdict"], "failed")
        self.assertEqual((test["status"], test["summary"]), ("fail", "boom"))
        self.assertNotIn("flaky", test)
        self.assertNotIn("reran", test)
        self.assertIsNone(self.recorded())
        self.assertFalse(verified_tree.last_path(self.worktree).exists())

    def test_a_passing_run_whose_head_moved_is_dirty_and_records_nothing(self):
        move = "subprocess.run(['git','commit','-q','--allow-empty','-m','moved'],check=True)"
        self.declare({"lint": "", "test": "import subprocess;" + move})
        answer = self.answer(self.run_verified())
        self.assertEqual(answer["verdict"], "dirty")
        self.assertIsNone(self.recorded())

    def run_patched(self, replacement):
        """`verified_tree.run` in this process with `_run_command` wrapped: replacement(real, n, id, ...)."""
        real = verified_tree._run_command
        calls = {}

        def wrapper(verification_id, command, changed, root):
            calls[verification_id] = calls.get(verification_id, 0) + 1
            return replacement(real, calls[verification_id], verification_id, command, changed, root)

        env = {**HERMETIC_GIT, "HOME": self.env["HOME"], "VERIFY_SLOT_DIR": str(self.slots)}
        with (mock.patch.dict(os.environ, env), mock.patch.object(verified_tree, "_run_command", wrapper),
              mock.patch("sys.stderr", StringIO())):
            return verified_tree.run(self.worktree)

    NO_SLOT = {"id": "test", "status": "fail", "exit": 75, "no_slot": True,
               "summary": "no verify slot came free in 12 attempts"}

    def test_a_rerun_with_no_free_slot_ends_as_no_slot(self):
        self.declare({"lint": "", "test": "sys.exit(1)"})

        def replacement(real, number, verification_id, *rest):
            if verification_id == "test" and number == 2:
                return dict(self.NO_SLOT)
            return real(verification_id, *rest)

        status, answer = self.run_patched(replacement)
        self.assertEqual(status, 0)
        self.assertEqual(answer["results"][1], self.NO_SLOT)

    def test_slot_exhaustion_wins_over_a_rerun_that_dirtied_the_tree(self):
        self.declare({"lint": "sys.exit(1)", "test": "sys.exit(1)"})
        firsts = {}

        def replacement(real, number, verification_id, *rest):
            if number == 1:
                firsts[verification_id] = real(verification_id, *rest)
                return firsts[verification_id]
            if verification_id == "lint":
                (self.worktree / "stray.txt").write_text("x\n")
                return {"id": "lint", "status": "pass", "exit": 0, "summary": "passed"}
            return dict(self.NO_SLOT)

        status, answer = self.run_patched(replacement)
        lint, test = answer["results"]
        self.assertEqual(test, self.NO_SLOT)
        self.assertEqual(lint, firsts["lint"])
        self.assertEqual(answer["verdict"], "failed")

    # Narrowed runs: carry the stored passes when the fix only re-indents the named files.

    JSON_CHECK = ("import json;t=open('data.json').read();"
                  "(print('data.json is not two-space indented'),sys.exit(1)) "
                  "if t!=json.dumps(json.loads(t),indent=2)+chr(10) else None")

    def indented(self, indent, **value):
        return json.dumps({"a": 1, **value}, indent=indent) + "\n"

    def first_failed(self, extra_files=None):
        """A first run whose `test` fails naming data.json; returns its answer."""
        self.declare({"lint": "", "test": self.JSON_CHECK})
        self.branch_change({"data.json": self.indented(4), "x.py": "if True:\n    pass\n",
                            **(extra_files or {})})
        first = self.answer(self.run_verified())
        self.assertEqual(first["verdict"], "failed")
        self.assertEqual(first["results"][1]["named"], ["data.json"])
        return first

    def narrowed(self, first):
        head = self.git("rev-parse", "HEAD", cwd=self.worktree)
        return self.run_verified("--head", first["head"], "--commit", head,
                                 "--digest", verified_tree.results_digest(first["results"]))

    def test_a_narrowed_run_runs_only_the_failed_ids_and_carries_the_passes(self):
        first = self.first_failed()
        self.branch_change({"data.json": self.indented(2)})
        logged = self.logged()
        answer = self.answer(self.narrowed(first))
        lint, test = answer["results"]
        where = str(self.worktree.resolve())
        self.assertEqual(answer["verdict"], "passed")
        self.assertEqual(self.logged(), logged + [f"{where} test"])
        self.assertEqual(lint, {**first["results"][0], "carried_from": first["head"]})
        self.assertNotIn("carried_from", test)
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.verification.verified_tree", "check"],
            cwd=self.worktree, capture_output=True, text=True, check=False, env=self.env)
        self.assertEqual(json.loads(done.stdout)["status"], "verified")

    def test_a_carried_pass_keeps_its_first_carried_from(self):
        first = self.first_failed()
        document = self.rewritten(lambda document: document["results"][0].update(carried_from="c" * 40))
        self.branch_change({"data.json": self.indented(2)})
        lint = self.answer(self.narrowed({**first, "results": document["results"]}))["results"][0]
        self.assertEqual(lint["carried_from"], "c" * 40)

    def test_a_narrowed_run_whose_evidence_or_range_does_not_bind_runs_every_id(self):
        first = self.first_failed({"other.json": self.indented(4)})
        last = verified_tree.last_path(self.worktree)
        stored = last.read_text()
        fix_base = first["head"]
        where = str(self.worktree.resolve())

        def reindent_both():
            self.branch_change({"data.json": self.indented(2), "other.json": self.indented(2)})

        def change_value():
            self.branch_change({"data.json": self.indented(2, a=2)})

        def reindent_python():
            self.branch_change({"data.json": self.indented(2), "x.py": "if True:\n  pass\n"})
            document = json.loads(stored)
            document["results"][1]["named"] = ["data.json", "x.py"]
            last.write_text(json.dumps(document) + "\n")

        def other_head():
            self.branch_change({"data.json": self.indented(2)})
            earlier = self.git("rev-parse", "HEAD", cwd=self.worktree)
            self.branch_change({"data.json": self.indented(3)})
            return earlier

        def no_file():
            self.branch_change({"data.json": self.indented(2)})
            last.unlink()

        cases = {"a file no failure named": reindent_both, "a changed value": change_value,
                 "a python file": reindent_python, "another head": other_head,
                 "no last verification file": no_file}
        for name, arrange in cases.items():
            with self.subTest(name):
                self.git("reset", "-q", "--hard", fix_base, cwd=self.worktree)
                last.write_text(stored)
                self.log.unlink(missing_ok=True)
                head = arrange()
                stored_results = json.loads(last.read_text())["results"] if last.exists() else []
                done = self.run_verified("--head", head or fix_base, "--commit",
                                         self.git("rev-parse", "HEAD", cwd=self.worktree),
                                         "--digest", verified_tree.results_digest(stored_results))
                answer = self.answer(done)
                self.assertEqual(self.logged(), [f"{where} lint", f"{where} test"])
                for entry in answer["results"]:
                    self.assertNotIn("carried_from", entry)

    def rewritten(self, change):
        """The last verification file after `change(document)`, as another run at the same head would leave it."""
        last = verified_tree.last_path(self.worktree)
        document = json.loads(last.read_text())
        change(document)
        last.write_text(json.dumps(document) + "\n")
        return document

    def test_a_narrowed_run_carries_nothing_when_the_stored_results_are_not_the_ones_graded(self):
        first = self.first_failed()
        self.rewritten(lambda document: document["results"][0].update(summary="another run"))
        self.branch_change({"data.json": self.indented(2)})
        logged = self.logged()
        answer = self.answer(self.narrowed(first))
        where = str(self.worktree.resolve())
        self.assertEqual(self.logged(), logged + [f"{where} lint", f"{where} test"])
        for entry in answer["results"]:
            self.assertNotIn("carried_from", entry)

    def test_a_stored_failure_naming_something_that_is_not_a_path_runs_every_id(self):
        first = self.first_failed()
        document = self.rewritten(lambda document: document["results"][1].update(named=[{}]))
        self.branch_change({"data.json": self.indented(2)})
        head = self.git("rev-parse", "HEAD", cwd=self.worktree)
        logged = self.logged()
        answer = self.answer(self.run_verified("--head", first["head"], "--commit", head, "--digest",
                                               verified_tree.results_digest(document["results"])))
        where = str(self.worktree.resolve())
        self.assertEqual(self.logged(), logged + [f"{where} lint", f"{where} test"])
        for entry in answer["results"]:
            self.assertNotIn("carried_from", entry)

    def test_a_narrowed_run_at_another_head_than_the_fix_is_an_error(self):
        first = self.first_failed()
        self.branch_change({"data.json": self.indented(2)})
        logged = self.logged()
        answer = self.answer(self.run_verified("--head", first["head"], "--commit", first["head"],
                                               "--digest", verified_tree.results_digest(first["results"])), 1)
        self.assertEqual(answer["verdict"], "error")
        self.assertTrue(answer["detail"].startswith("the narrowed verification would run at"))
        self.assertEqual(self.logged(), logged)

    def test_a_narrowed_run_given_only_one_of_its_flags_is_a_usage_error(self):
        self.declare({"lint": "", "test": ""})
        answer = self.answer(self.run_verified("--head", "a" * 40), 1)
        self.assertEqual(answer["verdict"], "error")
        self.assertTrue(answer["detail"].startswith("usage:"))


class SyncSkipTest(RunTest):
    """A passed run is recorded, and after a clean sync that changes none of the branch's files
    the next run runs nothing."""

    def history(self):
        return (self.slots / "history.jsonl").read_text().splitlines()

    def write_main(self, name, text):
        (self.repo / name).write_text(text, encoding="utf-8")

    def commit_main(self):
        self.commit_all("main change")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")

    def passed_then_synced(self, main_change, before=("lint", "test"), pr_change=None):
        """Run a passing branch, then land `main_change` on main and merge it into the worktree."""
        self.write_main("shared.txt", "".join(f"{n}\n" for n in range(1, 11)))
        self.declare({"lint": "", "test": ""}, before=list(before) if before else ABSENT)
        (self.worktree / "pr.txt").write_text("pr\n")
        if pr_change:
            pr_change()
        self.git("add", "-A", cwd=self.worktree)
        self.git("commit", "-q", "-m", "pr", cwd=self.worktree)
        first = self.answer(self.run_verified())
        self.assertEqual(first["verdict"], "passed")
        main_change()
        self.commit_main()
        self.git("merge", "-q", "--no-edit", "origin/main", cwd=self.worktree)
        return first

    def edit_line(self, root, number, text):
        path = root / "shared.txt"
        lines = path.read_text().splitlines()
        lines[number - 1] = text
        path.write_text("\n".join(lines) + "\n")

    def test_a_clean_sync_that_changes_none_of_the_pull_requests_files_runs_nothing(self):
        first = self.passed_then_synced(lambda: self.write_main("main.txt", "main\n"))
        before, logged = len(self.history()), self.logged()
        answer = self.answer(self.run_verified())
        self.assertEqual(answer["verdict"], "passed")
        self.assertEqual(answer["synced_since"], first["head"])
        self.assertEqual([(r["id"], r["status"]) for r in answer["results"]],
                         [("lint", "skipped"), ("test", "skipped")])
        reason = f"passed at {first['head']}; the sync since changed none of the pull request's files"
        self.assertEqual(answer["results"][0]["reason"], reason)
        self.assertEqual(answer["results"][0]["summary"], reason)
        self.assertEqual(answer["head"], self.git("rev-parse", "HEAD", cwd=self.worktree))
        self.assertIs(answer["clean"], True)
        self.assertEqual(self.logged(), logged)
        self.assertEqual(len(self.history()), before)

    def test_a_skip_after_a_clean_sync_records_the_synced_tree_as_verified(self):
        self.passed_then_synced(lambda: self.write_main("main.txt", "main\n"))
        answer = self.answer(self.run_verified())
        record = json.loads(verified_tree.record_path(self.worktree).read_text())
        self.assertIn("synced_since", answer)
        self.assertEqual(record, {"schema": "verified-tree/v1", "tree": answer["tree"],
                                  "verification": ["lint", "test"]})

    def test_a_sync_that_changes_a_pull_request_file_runs_again(self):
        self.passed_then_synced(lambda: self.edit_line(self.repo, 10, "ten"),
                                pr_change=lambda: self.edit_line(self.worktree, 1, "one"))
        logged = len(self.logged())
        answer = self.answer(self.run_verified())
        self.assertEqual(len(self.logged()), logged + 2)
        self.assertNotIn("synced_since", answer)
        self.assertEqual([r["status"] for r in answer["results"]], ["pass", "pass"])

    def test_a_commit_of_the_branch_after_the_pass_runs_again(self):
        self.write_main("shared.txt", "1\n")
        self.declare({"lint": "", "test": ""}, before=["lint", "test"])
        self.assertEqual(self.answer(self.run_verified())["verdict"], "passed")
        (self.worktree / "more.txt").write_text("more\n")
        self.git("add", "-A", cwd=self.worktree)
        self.git("commit", "-q", "-m", "more", cwd=self.worktree)
        logged = len(self.logged())
        answer = self.answer(self.run_verified())
        self.assertEqual(len(self.logged()), logged + 2)
        self.assertNotIn("synced_since", answer)

    def test_an_empty_commit_of_the_branch_after_the_pass_runs_again(self):
        self.declare({"lint": "", "test": ""}, before=["lint", "test"])
        self.assertEqual(self.answer(self.run_verified())["verdict"], "passed")
        self.git("commit", "-q", "--allow-empty", "-m", "empty", cwd=self.worktree)
        logged = len(self.logged())
        answer = self.answer(self.run_verified())
        self.assertEqual(len(self.logged()), logged + 2)
        self.assertNotIn("synced_since", answer)

    def test_a_branch_rewound_off_the_head_it_passed_at_runs_again(self):
        self.declare({"lint": "", "test": ""}, before=["lint", "test"])
        (self.worktree / "pr.txt").write_text("pr\n")
        self.git("add", "-A", cwd=self.worktree)
        self.git("commit", "-q", "-m", "pr", cwd=self.worktree)
        self.assertEqual(self.answer(self.run_verified())["verdict"], "passed")
        self.git("reset", "-q", "--hard", "origin/main", cwd=self.worktree)
        logged = len(self.logged())
        answer = self.answer(self.run_verified())
        self.assertEqual(len(self.logged()), logged + 2)
        self.assertNotIn("synced_since", answer)

    def test_a_second_run_at_the_head_it_passed_at_runs_nothing(self):
        self.declare({"lint": "", "test": ""}, before=["lint", "test"])
        first = self.answer(self.run_verified())
        logged = self.logged()
        second = self.answer(self.run_verified())
        self.assertEqual(second["synced_since"], first["head"])
        self.assertEqual(self.logged(), logged)

    def test_a_failed_run_records_no_pass_and_the_next_run_runs(self):
        self.write_main("shared.txt", "1\n")
        self.declare({"lint": "sys.exit(1)", "test": ""}, before=["lint", "test"])
        self.assertEqual(self.answer(self.run_verified())["verdict"], "failed")
        self.assertFalse(self.record_file().exists())
        self.write_main("main.txt", "main\n")
        self.commit_main()
        self.git("merge", "-q", "--no-edit", "origin/main", cwd=self.worktree)
        logged = len(self.logged())
        answer = self.answer(self.run_verified())
        self.assertEqual(len(self.logged()), logged + 3)  # lint fails outside the diff and reruns once
        self.assertNotIn("synced_since", answer)

    def record_file(self):
        return verified_tree.run_record_path(self.worktree)

    def test_without_the_binding_no_pass_is_recorded_and_a_clean_sync_runs_again(self):
        first = self.passed_then_synced(lambda: self.write_main("main.txt", "main\n"), before=None)
        self.assertFalse(self.record_file().exists())
        self.record_file().write_text(json.dumps(
            {"head": first["head"], "schema": "verified-tree-run/v1",
             "verification": ["lint", "test"]}) + "\n")
        logged = len(self.logged())
        answer = self.answer(self.run_verified())
        self.assertEqual(len(self.logged()), logged + 2)
        self.assertNotIn("synced_since", answer)

    def test_a_malformed_pass_record_is_ignored_and_the_run_verifies(self):
        self.write_main("shared.txt", "1\n")
        self.declare({"lint": "", "test": ""}, before=["lint", "test"])
        self.assertEqual(self.answer(self.run_verified())["verdict"], "passed")
        self.record_file().write_text("{}\n")
        self.write_main("main.txt", "main\n")
        self.commit_main()
        self.git("merge", "-q", "--no-edit", "origin/main", cwd=self.worktree)
        logged = len(self.logged())
        answer = self.answer(self.run_verified())
        self.assertEqual(answer["verdict"], "passed")
        self.assertEqual(len(self.logged()), logged + 2)

    def test_a_pass_of_other_ids_does_not_skip(self):
        def narrow():
            path = self.repo / ".agents" / "project.json"
            contract = json.loads(path.read_text(encoding="utf-8"))
            contract["bindings"]["workflow"]["verification_before_pull_request"] = ["lint"]
            path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
        self.passed_then_synced(narrow)
        logged = len(self.logged())
        answer = self.answer(self.run_verified())
        self.assertEqual(len(self.logged()), logged + 1)
        self.assertNotIn("synced_since", answer)
        self.assertEqual([r["id"] for r in answer["results"]], ["lint"])

    def test_a_pass_that_cannot_be_recorded_keeps_its_verdict(self):
        self.declare({"lint": "", "test": ""}, before=["lint", "test"])
        self.record_file().mkdir()
        answer, _ = self.run_in_process()
        self.assertEqual(answer["verdict"], "passed")
        self.assertIn("verified-tree: cannot record the pass", self.stderr.getvalue())

    def test_a_missing_integration_ref_runs_instead_of_erroring(self):
        self.declare({"lint": "", "test": ""}, before=["lint", "test"])
        self.assertEqual(self.answer(self.run_verified())["verdict"], "passed")
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        logged = len(self.logged())
        answer = self.answer(self.run_verified())
        self.assertNotEqual(answer["verdict"], "error")
        self.assertNotIn("synced_since", answer)
        self.assertEqual(len(self.logged()), logged + 2)


class SlotSecondsTest(unittest.TestCase):
    def test_the_waits_sum_and_the_last_report_gives_the_hold(self):
        reports = [{"waited_seconds": 1.0, "held_seconds": 2.0},
                   {"waited_seconds": 0.5, "held_seconds": 3.0}]
        self.assertEqual(verified_tree._slot_seconds(reports), (1.5, 3.0))

    def test_no_report_gives_none_for_both(self):
        self.assertEqual(verified_tree._slot_seconds([None]), (None, None))

    def test_a_null_hold_stays_none(self):
        self.assertEqual(verified_tree._slot_seconds([{"waited_seconds": 1.2, "held_seconds": None}]),
                         (1.2, None))

    def test_an_unreadable_attempt_is_ignored(self):
        reports = [{"waited_seconds": 1.0, "held_seconds": 2.0}, None]
        self.assertEqual(verified_tree._slot_seconds(reports), (1.0, 2.0))

    def test_the_selection_variable_is_the_selectors(self):
        self.assertEqual(verified_tree.SELECTION_ENV, touched_tests.SELECTION_ENV)
        self.assertEqual(verified_tree.SELECTION_ENV, "VERIFIED_TREE_SELECTION")


class FixRangeTest(ProjectCase):
    """`fix_range`: is the fix between two commits only a re-indentation of whitespace-insensitive files."""

    def fix(self, name, before, after):
        (self.repo / name).write_text(before, encoding="utf-8")
        self.commit_all("before")
        start = self.git("rev-parse", "HEAD")
        (self.repo / name).write_text(after, encoding="utf-8")
        self.commit_all("after")
        return verified_tree.fix_range(self.repo, start, self.git("rev-parse", "HEAD"))

    def test_a_reindented_json_file_is_whitespace_only(self):
        self.assertEqual(self.fix("a.json", '{\n    "a": 1\n}\n', '{\n  "a": 1\n}\n'),
                         {"whitespace_only": True, "changed_paths": ["a.json"]})

    def test_a_change_of_the_spaces_inside_a_json_string_is_not_whitespace_only(self):
        fixed = self.fix("a.json", '{\n    "a": "a b"\n}\n', '{\n  "a": "a  b"\n}\n')
        self.assertEqual(fixed, {"whitespace_only": False, "changed_paths": ["a.json"]})

    def test_a_content_change_is_not_whitespace_only(self):
        fixed = self.fix("a.json", '{\n    "a": 1\n}\n', '{\n  "a": 2\n}\n')
        self.assertEqual(fixed, {"whitespace_only": False, "changed_paths": ["a.json"]})

    def test_a_reindented_python_file_is_not_whitespace_only(self):
        fixed = self.fix("a.py", "if True:\n    pass\n", "if True:\n  pass\n")
        self.assertEqual(fixed, {"whitespace_only": False, "changed_paths": ["a.py"]})

    def test_an_unknown_commit_raises(self):
        with self.assertRaises(verified_tree.VerifiedTreeError):
            verified_tree.fix_range(self.repo, "0" * 40, "1" * 40)


if __name__ == "__main__":
    unittest.main()
