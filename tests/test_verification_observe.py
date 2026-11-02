"""verification-observe from source over a local bare origin (issue 543 D6-D13).

Each test copies the eval fixture project into a throwaway repository, resolved
under a temporary HOME holding the committed platform manifest, in the hermetic
Git environment of test_verified_tree.py. The repository publishes to a local
bare `origin` that a second clone, the publisher, advances.
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from agent_tools import verification_blocker as vb
from agent_tools import verification_observe as vo

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "home/common/agent-skills/platform-manifest.json"
FIXTURE = REPO_ROOT / "home/common/agent-skills/evals/fixture-repo"
HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
SCRUBBED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
            "GIT_COMMON_DIR", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CEILING_DIRECTORIES")
COMMAND = [sys.executable, "-m", "agent_tools.verification_observe"]
REPOSITORY = {"project_id": "fixture/tinytask", "integration_branch": "main"}
SUITE = {"id": "suite", "argv": ["python3", "-m", "unittest"], "cwd": "tinytask",
         "env": ["GITHUB_TOKEN"]}
TRACKING = "refs/remotes/origin/main"
INVALID = "verification-observe: invalid invocation\n"


def base_bindings(bindings):
    """`suite` is a verification command with a nested cwd; `lint` is not one."""
    bindings["commands"]["suite"] = {k: SUITE[k] for k in ("argv", "cwd", "env")}
    bindings["commands"]["lint"] = {"argv": ["python3", "-c", "pass"], "cwd": ".", "env": []}
    bindings["workflow"]["verification"] = ["test", "suite"]


class ObserveCase(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name).resolve()
        home = self.scratch / "home"
        (home / ".agents" / "share").mkdir(parents=True)
        shutil.copy(MANIFEST, home / ".agents" / "share" / "platform-manifest.json")
        self.env = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
        self.env.update(HERMETIC_GIT, HOME=str(home))
        self.root = self.scratch / "repo"
        shutil.copytree(FIXTURE, self.root)
        self.rewrite(self.root, base_bindings)
        (self.root / "flake.lock").write_text("lock 1\n", encoding="utf-8")
        (self.root / "pkgs" / "nested").mkdir(parents=True)
        (self.root / "pkgs" / "nested" / "default.nix").write_text("{ }\n", encoding="utf-8")
        self.git(self.root, "init", "-q", "-b", "main")
        self.git(self.root, "config", "commit.gpgsign", "false")  # throwaway fixture repo
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "-m", "base")
        self.origin = self.scratch / "origin.git"
        self.git(None, "init", "-q", "--bare", "-b", "main", str(self.origin))
        for key, value in (("gc.auto", "0"), ("maintenance.auto", "false"),
                           ("receive.autogc", "false")):
            self.git(self.origin, "config", key, value)
        self.git(self.root, "remote", "add", "origin", str(self.origin))
        self.git(self.root, "push", "-q", "origin", "main")
        self.publisher = self.scratch / "publisher"
        self.git(None, "clone", "-q", str(self.origin), str(self.publisher))
        self.git(self.publisher, "config", "commit.gpgsign", "false")

    def rewrite(self, checkout, edit):
        path = checkout / ".agents" / "project.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        edit(contract["bindings"])
        path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

    def git(self, where, *args):
        prefix = ["git"] if where is None else ["git", "-C", str(where)]
        return subprocess.run([*prefix, *args], capture_output=True, text=True, check=True,
                              env=self.env).stdout.strip()

    def publish(self, files=None, removed=()):
        """One commit on origin's main from the publisher."""
        for name, text in (files or {}).items():
            path = self.publisher / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        for name in removed:
            self.git(self.publisher, "rm", "-q", "-r", name)
        self.git(self.publisher, "add", "-A")
        self.git(self.publisher, "commit", "-q", "--allow-empty", "-m", "publish")
        self.git(self.publisher, "push", "-q", "origin", "main")

    def entry(self, path):
        """The `{path, mode, object}` entry origin's main holds at `path`, read independently
        of the tool; `mode` and `object` are `None` when it holds nothing there."""
        listed = self.git(self.origin, "ls-tree", "--full-tree", "main", "--", path)
        if not listed:
            return {"path": path, "mode": None, "object": None}
        mode, _, rest = listed.partition(" ")
        return {"path": path, "mode": mode, "object": rest.split("\t")[0].split(" ")[1]}

    def run_tool(self, *argv, stdin=""):
        return subprocess.run([*COMMAND, *argv], input=stdin, capture_output=True, text=True,
                              env=self.env, timeout=300, check=False)

    def call(self, mode, payload, repo_root=None):
        return self.run_tool(mode, "--repo-root", str(repo_root or self.root), "--input", "-",
                             stdin=json.dumps(payload))

    def ok(self, done):
        self.assertEqual((done.returncode, done.stderr), (0, ""), done.stderr)
        value = json.loads(done.stdout)
        self.assertEqual(done.stdout, vb.canonical_bytes(value).decode("ascii") + "\n")
        return value

    def refused(self, done, fragment):
        self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
        self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
        self.assertTrue(done.stderr.startswith("verification-observe: "), done.stderr)
        self.assertIn(fragment, done.stderr)

    def tracking(self):
        return self.git(self.root, "rev-parse", TRACKING)


class FailureTest(ObserveCase):
    def setUp(self):
        super().setUp()
        self.worktree = self.scratch / "wt"
        self.git(self.root, "worktree", "add", "-q", "-b", "issue-1", str(self.worktree),
                 "origin/main")
        self.declaration = {
            "command_id": "suite", "failure_class": "dependency", "worktree": str(self.worktree),
            "facts": [{"name": "packages", "paths": ["pkgs/nested"]},
                      {"name": "flake-lock", "paths": ["flake.lock", "README.md"]}]}

    def expected_facts(self):
        return [{"name": "flake-lock", "source": {"paths": ["README.md", "flake.lock"]},
                 "value": {"objects": [self.entry("README.md"), self.entry("flake.lock")]}},
                {"name": "packages", "source": {"paths": ["pkgs/nested"]},
                 "value": {"objects": [self.entry("pkgs/nested")]}}]

    def test_a_clean_failure_names_the_resolved_command_and_no_path_of_the_host(self):
        done = self.call("failure", self.declaration)
        value = self.ok(done)
        self.assertEqual(value, {"kind": "verification-failure", "schema_version": 1,
                                 "repository": REPOSITORY, "command": SUITE,
                                 "failure_class": "dependency",
                                 "facts": self.expected_facts()})
        self.assertEqual([entry["mode"] for fact in value["facts"]
                          for entry in fact["value"]["objects"]], ["100644", "100644", "040000"])
        self.assertNotIn(str(self.scratch), done.stdout)

    def test_declaration_order_changes_no_byte_and_observe_reads_the_same_values(self):
        first = self.call("failure", self.declaration)
        reordered = dict(reversed(list(self.declaration.items())))
        reordered["facts"] = [{"name": "flake-lock", "paths": ["README.md", "flake.lock"]},
                              {"name": "packages", "paths": ["pkgs/nested"]}]
        self.assertEqual(self.call("failure", reordered).stdout, first.stdout)
        value = self.ok(first)
        requirement = {"kind": "verification", "blocker_id": vb.blocker_id(value),
                       "sources": [{"name": fact["name"], "paths": fact["source"]["paths"]}
                                   for fact in value["facts"]]}
        observed = self.ok(self.call("observe", requirement))
        self.assertEqual((observed["blocker_id"], observed["repository"], observed["facts"]),
                         (requirement["blocker_id"], REPOSITORY, value["facts"]))

    def test_a_refused_declaration_never_fetches(self):
        self.publish({"flake.lock": "lock 2\n"})
        before = self.tracking()
        cases = (({"facts": [{"name": "env", "paths": [".env"]}]}, "secret-shaped"),
                 ({"failure_class": "flaky"}, "unclassified"),
                 ({"command_id": "lint"}, "lint is not a verification command"),
                 ({"note": "x"}, "unknown"),
                 ({"worktree": "wt"}, "worktree"),
                 ({"worktree": "/w/\ud800"}, "worktree: must encode as UTF-8"))
        for change, fragment in cases:
            with self.subTest(change=change):
                self.refused(self.call("failure", {**self.declaration, **change}), fragment)
        self.assertEqual(self.run_tool("failure", "--repo-root", "repo", "--input", "-",
                                       stdin=json.dumps(self.declaration)).stderr, INVALID)
        self.assertEqual(self.tracking(), before)

    def test_a_change_to_a_selected_path_in_the_attempt_is_refused(self):
        lock = self.worktree / "flake.lock"
        lock.write_text("edited\n", encoding="utf-8")
        self.refused(self.call("failure", self.declaration), "guard: a selected path")
        self.git(self.worktree, "add", "flake.lock")
        self.refused(self.call("failure", self.declaration), "guard: a selected path")
        self.git(self.worktree, "reset", "-q", "--hard", "HEAD")
        extra = self.worktree / "pkgs" / "nested" / "extra.nix"
        extra.write_text("{ }\n", encoding="utf-8")
        self.refused(self.call("failure", self.declaration), "guard: a selected path")
        extra.unlink()
        self.ok(self.call("failure", self.declaration))
        lock.chmod(0o755)
        self.git(self.worktree, "commit", "-q", "-am", "own mode change")
        self.assertEqual(self.git(self.worktree, "status", "--porcelain"), "")
        self.refused(self.call("failure", self.declaration), "guard: flake.lock at HEAD differs")
        self.git(self.worktree, "reset", "-q", "--hard", "HEAD~1")
        lock.write_text("committed\n", encoding="utf-8")
        self.git(self.worktree, "commit", "-q", "-am", "own edit")
        self.refused(self.call("failure", self.declaration), "guard: flake.lock at HEAD differs")

    def test_an_attempt_behind_a_selected_change_is_refused_and_an_unrelated_one_is_not(self):
        self.publish({"other.txt": "unrelated\n"})
        self.ok(self.call("failure", self.declaration))
        self.publish({"pkgs/nested/default.nix": "{ x = 1; }\n"})
        self.refused(self.call("failure", self.declaration), "guard: pkgs/nested at HEAD differs")

    def test_a_diverged_command_entry_or_a_foreign_checkout_is_refused(self):
        self.rewrite(self.worktree, lambda b: b["commands"]["suite"].update(argv=["true"]))
        self.refused(self.call("failure", self.declaration), "guard: the worktree's suite entry")
        self.git(self.worktree, "checkout", "--", ".agents/project.json")
        foreign = self.scratch / "foreign"
        self.git(None, "clone", "-q", str(self.origin), str(foreign))
        self.refused(self.call("failure", {**self.declaration, "worktree": str(foreign)}),
                     "guard: the worktree is not a checkout")

    def test_a_subdirectory_of_the_attempt_is_refused_before_the_fetch(self):
        """`pkgs` holds a copy of the project, so it resolves to the same `suite` entry."""
        self.publish({"other.txt": "unrelated\n"})
        before = self.tracking()
        (self.worktree / "flake.lock").write_text("edited\n", encoding="utf-8")
        for name in (".agents", ".claude", "AGENTS.md", "CLAUDE.md", "docs", "tinytask"):
            source, target = self.worktree / name, self.worktree / "pkgs" / name
            (shutil.copytree if source.is_dir() else shutil.copy)(source, target)
        subdirectory = {**self.declaration, "worktree": str(self.worktree / "pkgs")}
        self.refused(self.call("failure", subdirectory),
                     "guard: the worktree is not the top level of its checkout")
        self.assertEqual(self.tracking(), before)

    def test_a_changed_submodule_set_to_be_ignored_is_still_a_change(self):
        library = self.scratch / "library"
        self.git(None, "init", "-q", "-b", "main", str(library))
        self.git(library, "commit", "-q", "--allow-empty", "-m", "one")
        allow = ("-c", "protocol.file.allow=always")
        self.git(self.publisher, *allow, "submodule", "add", "-q", str(library), "vendor/lib")
        self.publish()
        self.git(self.root, "fetch", "-q", "origin")
        self.git(self.worktree, "merge", "-q", "--ff-only", "origin/main")
        self.git(self.worktree, *allow, "submodule", "update", "-q", "--init")
        declaration = {**self.declaration,
                       "facts": [{"name": "vendored", "paths": ["vendor/lib"]}]}
        self.ok(self.call("failure", declaration))
        self.git(self.worktree, "config", "submodule.vendor/lib.ignore", "all")
        self.git(self.worktree / "vendor" / "lib", "commit", "-q", "--allow-empty", "-m", "two")
        self.refused(self.call("failure", declaration),
                     "guard: a selected path has a staged, unstaged or untracked change")


class ObserveTest(ObserveCase):
    REQUIREMENT = {"kind": "verification", "blocker_id": "sha256:" + "1" * 64,
                   "sources": [{"name": "flake-lock", "paths": ["flake.lock"]},
                               {"name": "packages", "paths": ["pkgs/nested"]}]}

    def expected(self):
        """The observation of origin's main as it stands, read independently of the tool."""
        return {"kind": "verification-observation", "schema_version": 1,
                "blocker_id": self.REQUIREMENT["blocker_id"], "repository": REPOSITORY,
                "facts": [{"name": "flake-lock", "source": {"paths": ["flake.lock"]},
                           "value": {"objects": [self.entry("flake.lock")]}},
                          {"name": "packages", "source": {"paths": ["pkgs/nested"]},
                           "value": {"objects": [self.entry("pkgs/nested")]}}]}

    def observe(self):
        return self.call("observe", self.REQUIREMENT)

    def test_an_unrelated_commit_is_equal_and_a_selected_change_is_not(self):
        first = self.observe()
        self.assertEqual(self.ok(first), self.expected())
        self.publish({"README.md": "readme 2\n"})
        self.assertEqual(self.observe().stdout, first.stdout)
        self.publish({"flake.lock": "lock 2\n", "pkgs/nested/deeper/extra.nix": "{ }\n"})
        changed = self.ok(self.observe())
        self.assertEqual(changed, self.expected())
        self.assertNotEqual(changed, json.loads(first.stdout))
        self.publish(removed=("flake.lock",))
        absent = self.ok(self.observe())
        self.assertEqual(absent, self.expected())
        self.assertEqual(absent["facts"][0]["value"]["objects"],
                         [{"path": "flake.lock", "mode": None, "object": None}])

    def test_a_mode_change_alone_is_a_change(self):
        """`chmod +x` keeps the blob, so only the mode tells the two states apart."""
        first = self.ok(self.observe())
        (self.publisher / "flake.lock").chmod(0o755)
        self.publish()
        changed = self.ok(self.observe())
        self.assertEqual(changed, self.expected())
        before, after = (value["facts"][0]["value"]["objects"][0] for value in (first, changed))
        self.assertEqual((before["object"], before["mode"], after["mode"]),
                         (after["object"], "100644", "100755"))

    def test_nested_selected_paths_are_each_read_as_their_own_entry(self):
        paths = ["pkgs", "pkgs/nested", "pkgs/nested/default.nix"]
        requirement = {**self.REQUIREMENT, "sources": [{"name": "packages", "paths": paths}]}
        value = self.ok(self.call("observe", requirement))
        self.assertEqual(value["facts"][0]["value"]["objects"],
                         [self.entry(path) for path in paths])

    def test_the_only_write_is_the_integration_tracking_ref(self):
        self.publish({"flake.lock": "lock 2\n"})
        refs = ("for-each-ref", "--format=%(refname) %(objectname)")
        before = dict(line.split(" ") for line in self.git(self.root, *refs).splitlines())
        status = self.git(self.root, "status", "--porcelain", "--untracked-files=all")
        self.ok(self.observe())
        after = dict(line.split(" ") for line in self.git(self.root, *refs).splitlines())
        self.assertEqual({ref for ref in before.keys() | after.keys()
                          if before.get(ref) != after.get(ref)}, {TRACKING})
        self.assertEqual(after[TRACKING], self.git(self.origin, "rev-parse", "main"))
        self.assertEqual(self.git(self.root, "status", "--porcelain", "--untracked-files=all"),
                         status)
        self.assertFalse((self.root / ".git" / "FETCH_HEAD").exists())

    def test_an_integration_branch_that_is_not_one_branch_name_is_refused_before_a_fetch(self):
        """A refspec would expand `*` to every matching branch; `a..b` is no ref name."""
        self.git(self.publisher, "push", "-q", "origin", "HEAD:refs/heads/mainline")
        refs = ("for-each-ref", "--format=%(refname) %(objectname)")
        before = self.git(self.root, *refs)
        for branch in ("ma*", "a..b"):
            with self.subTest(branch=branch):
                self.rewrite(self.root, lambda b: b["vcs"].update(integration_branch=branch))
                self.refused(self.observe(),
                             f"integration branch {branch!r} is not a valid branch name")
                self.assertEqual(self.git(self.root, *refs), before)

    def test_a_failed_fetch_prints_nothing_and_moves_nothing(self):
        before = self.tracking()
        self.publish({"flake.lock": "lock 2\n"})
        self.git(self.root, "remote", "set-url", "origin", str(self.scratch / "missing.git"))
        self.refused(self.observe(), "git fetch: ")
        self.git(self.root, "remote", "set-url", "origin", str(self.origin))
        self.git(self.origin, "branch", "-m", "main", "gone")
        self.refused(self.observe(), "git fetch: ")
        self.assertEqual(self.tracking(), before)

    def test_a_failed_or_malformed_read_after_the_fetch_is_refused(self):
        """A `git` shim on the tool's PATH breaks only `ls-tree`; the fetch stays real."""
        real = shutil.which("git", path=self.env.get("PATH"))
        shim = self.scratch / "shim"
        shim.mkdir()
        env = {**self.env, "PATH": f"{shim}{os.pathsep}{self.env.get('PATH', '')}"}
        for action, fragment in (
                ("echo 'fatal: bad tree' >&2; exit 128", "git ls-tree: fatal: bad tree"),
                ("printf 'garbage'; exit 0", "git ls-tree: unexpected output for ")):
            with self.subTest(action=action):
                (shim / "git").write_text(
                    '#!/bin/sh\nfor a in "$@"; do [ "$a" = ls-tree ] && { ' + action
                    + '; }; done\nexec ' + shlex.quote(real) + ' "$@"\n', encoding="utf-8")
                (shim / "git").chmod(0o755)
                done = subprocess.run(
                    [*COMMAND, "observe", "--repo-root", str(self.root), "--input", "-"],
                    input=json.dumps(self.REQUIREMENT), capture_output=True, text=True,
                    env=env, timeout=300, check=False)
                self.refused(done, fragment)

    def test_observe_needs_no_runnable_verification_command(self):
        def ghost(bindings):
            bindings["commands"]["ghost"] = {"argv": ["verification-observe-no-such-program"],
                                             "cwd": ".", "env": []}
            bindings["workflow"]["verification"].append("ghost")
        self.rewrite(self.root, ghost)
        self.ok(self.observe())
        declaration = {"command_id": "suite", "failure_class": "environment",
                       "worktree": str(self.root),
                       "facts": [{"name": "flake-lock", "paths": ["flake.lock"]}]}
        self.refused(self.call("failure", declaration),
                     "resolve-project refused: capability_unavailable "
                     "capability.verification.command_missing")

    def test_help_and_invalid_invocations(self):
        done = self.run_tool("--help")
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assertTrue(done.stdout.startswith("usage: verification-observe "), done.stdout)
        root = str(self.root)
        for argv in ((), ("observe",), ("observe", "--repo-root", root),
                     ("observe", "--repo-root", root, "--input", "requirement.json"),
                     ("observe", "--repo-root", "repo", "--input", "-"),
                     ("probe", "--repo-root", root, "--input", "-"),
                     ("observe", "--repo-root", root, "--input", "-", "--extra")):
            with self.subTest(argv=argv):
                done = self.run_tool(*argv)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (2, "", INVALID))
        for stdin, fragment in (("{", "input: "), ('{"kind": 1, "kind": 2}', "duplicate"),
                                ('{"x": NaN}', "NaN"), ("[" * 100000, "input: ")):
            with self.subTest(stdin=stdin):
                self.refused(self.run_tool("observe", "--repo-root", root, "--input", "-",
                                           stdin=stdin), fragment)
        self.refused(self.call("observe", {**self.REQUIREMENT, "schema_version": 1}),
                     "unknown")


class ObserveAllTest(ObserveCase):
    """`observe_all` by import, under this case's HOME, Git and PATH (issue 546 D2, D11)."""

    LOCK = {"kind": "verification", "blocker_id": "sha256:" + "1" * 64,
            "sources": [{"name": "flake-lock", "paths": ["flake.lock"]}]}
    NESTED = {"kind": "verification", "blocker_id": "sha256:" + "2" * 64,
              "sources": [{"name": "packages", "paths": ["pkgs/nested"]}]}

    def setUp(self):
        super().setUp()
        self.patch_environment(self.env)

    def patch_environment(self, env):
        patch = mock.patch.dict(os.environ, env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)

    def test_an_empty_list_observes_nothing_and_fetches_nothing(self):
        self.publish({"flake.lock": "lock 2\n"})
        before = self.tracking()
        self.assertEqual(vo.observe_all(str(self.root), []), ([], []))
        self.assertEqual(self.tracking(), before)

    def test_each_requirement_is_observed_as_observe_prints_it_after_one_fetch(self):
        self.publish({"flake.lock": "lock 2\n"})
        observations, refused = vo.observe_all(str(self.root), [self.NESTED, self.LOCK])
        self.assertEqual(refused, [])
        self.assertEqual(observations,
                         [self.ok(self.call("observe", requirement))
                          for requirement in (self.NESTED, self.LOCK)])
        self.assertEqual(self.tracking(), self.git(self.origin, "rev-parse", "main"))

    def test_two_requirements_are_served_by_one_fetch_of_the_tracking_ref(self):
        """Every observation of a batch is read at one commit (issue 546 D2)."""
        real = shutil.which("git", path=self.env.get("PATH"))
        shim = self.scratch / "shim"
        shim.mkdir()
        log = self.scratch / "git.log"
        (shim / "git").write_text(
            '#!/bin/sh\nprintf \'%s\\n\' "$*" >> ' + shlex.quote(str(log))
            + '\nexec ' + shlex.quote(real) + ' "$@"\n', encoding="utf-8")
        (shim / "git").chmod(0o755)
        self.patch_environment({**self.env, "PATH": f"{shim}{os.pathsep}{self.env['PATH']}"})
        self.publish({"flake.lock": "lock 2\n"})
        observations, refused = vo.observe_all(str(self.root), [self.NESTED, self.LOCK])
        self.assertEqual((len(observations), refused), (2, []))
        calls = [line.split() for line in log.read_text(encoding="utf-8").splitlines()]
        subcommands = [call[2] for call in calls]  # `git -C <directory> <subcommand> ...`
        self.assertEqual(subcommands.count("fetch"), 1, subcommands)
        self.assertEqual(sum(call[2] == "rev-parse" and TRACKING + "^{commit}" in call
                             for call in calls), 1, calls)
        self.assertEqual(subcommands.count("ls-tree"), 2, subcommands)

    def test_an_unreachable_origin_refuses_every_requirement(self):
        before = self.tracking()
        self.git(self.root, "remote", "set-url", "origin", str(self.scratch / "missing.git"))
        observations, refused = vo.observe_all(str(self.root), [self.LOCK, self.NESTED])
        self.assertEqual(observations, [])
        self.assertEqual([blocker for blocker, _ in refused],
                         [self.LOCK["blocker_id"], self.NESTED["blocker_id"]])
        for _, reason in refused:
            self.assertTrue(reason.startswith("git fetch: "), reason)
            self.assertNotIn("\n", reason)
        self.assertEqual(refused[0][1], refused[1][1])
        self.assertEqual(self.tracking(), before)

    def test_a_failed_read_refuses_only_its_own_requirement(self):
        real = shutil.which("git", path=self.env.get("PATH"))
        shim = self.scratch / "shim"
        shim.mkdir()
        (shim / "git").write_text(
            '#!/bin/sh\nfor a in "$@"; do [ "$a" = pkgs/nested ] && '
            '{ echo "fatal: bad tree" >&2; exit 128; }; done\nexec '
            + shlex.quote(real) + ' "$@"\n', encoding="utf-8")
        (shim / "git").chmod(0o755)
        self.patch_environment({**self.env, "PATH": f"{shim}{os.pathsep}{self.env['PATH']}"})
        observations, refused = vo.observe_all(str(self.root), [self.NESTED, self.LOCK])
        self.assertEqual(refused, [(self.NESTED["blocker_id"], "git ls-tree: fatal: bad tree")])
        self.assertEqual([item["blocker_id"] for item in observations],
                         [self.LOCK["blocker_id"]])

    def test_a_malformed_list_raises_before_any_fetch(self):
        self.publish({"flake.lock": "lock 2\n"})
        before = self.tracking()
        for value, fragment in (
                ({"kind": "verification"}, "requirements: must be a list"),
                ([self.LOCK, {**self.NESTED, "kind": "probe"}],
                 "requirements[1]: requirement.kind: must be verification"),
                ([{**self.LOCK, "schema_version": 1}], "requirements[0]: requirement: ")):
            with self.subTest(value=value):
                with self.assertRaises(vb.BlockerRefused) as caught:
                    vo.observe_all(str(self.root), value)
                self.assertTrue(str(caught.exception).startswith(fragment), caught.exception)
        self.assertEqual(self.tracking(), before)


if __name__ == "__main__":
    unittest.main()
