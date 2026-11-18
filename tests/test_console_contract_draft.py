"""The console's drafted project contract (#1067): the reading, the fields, the contract, the refusals.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools import canonical
from agent_tools.console import contract_draft as cd

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1052)

ROOT = Path(__file__).resolve().parent.parent
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
MANIFEST = ROOT / "home" / "common" / "agent-skills" / "platform-manifest.json"
ID = "sample-owner/sample-app"


def git(path, *arguments):
    done = subprocess.run(
        ["git", "-C", str(path), *arguments], env=GIT_ENV, check=True, text=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
    return done.stdout


def commit(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (root / name).write_text(text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "more")


def sample(parent: Path, *, remote: bool, name: str = "sample-app") -> Path:
    root = parent / name
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "trunk")
    git(root, "config", "user.name", "t")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("# x\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "one")
    if remote:
        bare = parent / "origin.git"
        git(parent, "clone", "-q", "--bare", str(root), str(bare))
        git(root, "remote", "add", "origin", "https://github.com/sample-owner/sample-app.git")
        git(root, "config", f"url.{bare}.insteadOf", "https://github.com/sample-owner/sample-app.git")
    return root


def install_hook(root, name="pre-commit", text="#!/bin/sh\nexit 0\n", mode=0o755):
    hooks = Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()) / "hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / name).write_text(text)
    (hooks / name).chmod(mode)


def by_field(fields):
    return {f["field"]: f for f in fields}


def pair(fields, field):
    record = by_field(fields)[field]
    return record["value"], record["source"]


class ContractDraftTest(unittest.TestCase):
    def setUp(self):
        self.parent = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.parent, ignore_errors=True)
        self.saved = os.environ.get("GIT_ALLOW_PROTOCOL")
        os.environ["GIT_ALLOW_PROTOCOL"] = "file"
        self.addCleanup(self.restore)

    def restore(self):
        if self.saved is None:
            os.environ.pop("GIT_ALLOW_PROTOCOL", None)
        else:
            os.environ["GIT_ALLOW_PROTOCOL"] = self.saved

    def remote_fields(self):
        root = str(sample(self.parent, remote=True))
        return root, cd.draft(root, cd.read(root))

    def settled(self, fields, root, **values):
        for field, value in values.items():
            fields, error = cd.set_value(fields, field.replace("_", "-"), value, entries=[], root=root)
            self.assertIsNone(error)
        return fields

    def test_a_github_remote_is_read_for_id_name_branch_and_tracker(self):
        root, fields = self.remote_fields()
        self.assertEqual([f["field"] for f in fields], list(cd.FIELDS))
        self.assertEqual(len(cd.FIELDS), 29)
        for record in fields:
            self.assertEqual(set(record), cd.FIELD_KEYS)
        self.assertEqual(pair(fields, "project-id"), (ID, "remote"))
        self.assertEqual(pair(fields, "project-name"), ("sample-app", "remote"))
        self.assertEqual(pair(fields, "default-branch"), ("trunk", "remote"))
        self.assertEqual(pair(fields, "tracker"), ("github", "remote"))
        self.assertEqual(pair(fields, "docs-paths"), ("README.md", "files"))
        self.assertEqual(pair(fields, "release"), ("unsupported", "start"))
        self.assertEqual([f["field"] for f in cd.open_fields(fields)],
                         ["build-command", "test-command"])

    def test_with_no_remote_the_id_is_a_text_card(self):
        root = str(sample(self.parent, remote=False))
        fields = cd.draft(root, cd.read(root))
        question = cd.questions(fields)[0]
        self.assertEqual(question["subject"], "project-id")
        self.assertTrue(question["text"])
        self.assertEqual(question["options"], [])
        ask = ("Which project is this repository?\n"
               "It has no remote that names it: type its id, as owner/name.")
        self.assertEqual(question["ask"], ask)
        self.assertEqual(pair(fields, "project-name"), ("sample-app", "folder"))
        self.assertEqual([f["field"] for f in cd.open_fields(fields)],
                         ["project-id", "default-branch", "tracker", "build-command", "test-command"])
        branch = by_field(fields)["default-branch"]
        self.assertEqual(branch["options"], [{"value": "trunk", "label": "trunk"}])
        new, _ = cd.set_value(fields, "tracker", "none", entries=[], root=root)
        self.assertEqual(cd.questions(new)[0]["ask"], ask)

    def test_commands_are_found_in_tracked_files(self):
        root = sample(self.parent, remote=False)
        commit(root, {"justfile": "build:\n\techo b\ntest:\n\techo t\n"})
        fields = cd.draft(str(root), cd.read(str(root)))
        self.assertEqual(pair(fields, "build-command"), ("just build", "files"))
        self.assertEqual(pair(fields, "test-command"), ("just test", "files"))
        other = sample(self.parent / "two", remote=False)
        commit(other, {"package.json": json.dumps({"scripts": {"test": "x"}})})
        fields = cd.draft(str(other), cd.read(str(other)))
        self.assertEqual(pair(fields, "test-command"), ("npm test", "files"))
        self.assertEqual(pair(fields, "build-command"), (None, None))

    def test_a_just_recipe_is_found_by_its_whole_name_and_runs_with_no_argument(self):
        for index, (text, build, test) in enumerate((
                ("build-release:\n\techo b\ntest-unit:\n\techo t\n", None, None),
                ("build target:\n\techo b\ntest +files:\n\techo t\n", None, None),
                ("build target='a:b' flag:\n\techo b\n", None, None),
                ("build target='x' *rest:\n\techo b\ntest: build\n\techo t\n",
                 "just build", "just test"),
                ("build := 'x'\ntest $name=\"a b\":\n\techo t\n", None, "just test"))):
            root = sample(self.parent / f"j{index}", remote=False)
            commit(root, {"justfile": text})
            fields = cd.draft(str(root), cd.read(str(root)))
            self.assertEqual(pair(fields, "build-command")[0], build, text)
            self.assertEqual(pair(fields, "test-command")[0], test, text)

    def expected_contract(self):
        return {
            "schema_version": 2,
            "project": {"id": ID, "name": "sample-app"},
            "bindings": {
                "vcs": {
                    "kind": "git", "default_branch": "trunk", "integration_branch": "trunk",
                    "branch_pattern": "issue-<num>-<slug>",
                    "worktree": {"root": ".worktrees", "prefix": "worktree-"},
                    "commit": {"co_authored_by": False, "signed": False},
                    "merge": {"strategy": "merge", "delete_branch": True},
                },
                "tracker": {"kind": "github", "cli": "gh", "repo_slug": ID,
                            "credential_env": {"unset_before_invocation": []}},
                "paths": {
                    "artifacts": {"specs": ".agents/artifacts/specs",
                                  "plans": ".agents/artifacts/plans"},
                    "context": [], "standards": [], "architecture": ["README.md"],
                    "operations": [], "hints": [], "rejections": [],
                },
                "commands": {},
                "workflow": {
                    "verification": [],
                    "orchestration": {"max_parallel": 1, "attempt_budget_minutes": 240},
                    "review": {"plan": None, "code": None},
                },
            },
            "capabilities": {
                "tracker": {"support": "supported"},
                "worktrees": {"support": "supported"},
                "knowledge.context": {"support": "unsupported"},
                "knowledge.standards": {"support": "unsupported"},
                "knowledge.architecture": {"support": "supported"},
                "knowledge.hints": {"support": "unsupported"},
                "verification": {"support": "unsupported"},
                "review.plan": {"support": "unsupported"},
                "review.code": {"support": "unsupported"},
            },
            "projections": [],
            "release": "unsupported",
        }

    def test_the_drafted_contract_has_the_wire_format(self):
        root, fields = self.remote_fields()
        fields = self.settled(fields, root, build_command="none", test_command="none")
        self.assertEqual(cd.contract(fields), self.expected_contract())
        fields = self.settled(
            fields, root, review_plan_command="true",
            light_lane='{"mode": "shadow", "budget_minutes": 90, "risk_paths": []}')
        drafted = cd.contract(fields)
        self.assertEqual(drafted["bindings"]["commands"]["review-plan"],
                         {"argv": ["true"], "cwd": ".", "env": []})
        self.assertEqual(drafted["bindings"]["workflow"]["review"]["plan"], "review-plan")
        self.assertEqual(drafted["capabilities"]["review.plan"], {"support": "supported"})
        self.assertEqual(drafted["bindings"]["workflow"]["light_lane"],
                         {"mode": "shadow", "budget_minutes": 90, "risk_paths": []})

    def test_the_drafted_contract_resolves(self):
        root, fields = self.remote_fields()
        fields = self.settled(fields, root, build_command="none", test_command="none")
        version = json.loads(MANIFEST.read_text())["platform_version"]
        major = int(version.split(".")[0])
        drafted = cd.contract(fields)
        drafted["platform"] = {"min_inclusive": version, "max_exclusive": f"{major + 1}.0.0"}
        copy = self.parent / "copy"
        shutil.copytree(root, copy)
        (copy / ".agents").mkdir()
        (copy / ".agents" / "project.json").write_text(json.dumps(drafted))
        home = self.parent / "home"
        (home / ".agents" / "share").mkdir(parents=True)
        shutil.copy(MANIFEST, home / ".agents" / "share" / "platform-manifest.json")
        env = {**os.environ, "HOME": str(home), "PYTHONPATH": str(ROOT / "python")}
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.project_contract.resolve_project", "resolve",
             "--repo-root", str(copy)],
            env=env, text=True, stdin=subprocess.DEVNULL, capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def environment_checkout(self, parent=None):
        root = sample(parent or self.parent, remote=True)
        commit(root, {"devenv.nix": "{ ... }: { }\n"})
        install_hook(root)
        return root

    def test_a_devenv_checkout_with_an_installed_hook_proposes_its_development_shell(self):
        root = self.environment_checkout()
        reading = cd.read(str(root))
        fields = cd.draft(str(root), reading)
        self.assertEqual(reading["hooks"], ["pre-commit"])
        self.assertEqual(reading["environments"], ["devenv.nix"])
        self.assertEqual([f["field"] for f in fields], [*cd.FIELDS, "commit-environment"])
        self.assertEqual(pair(fields, "commit-environment"), ("devenv shell --", "files"))
        self.assertNotIn("commit-environment", [f["field"] for f in cd.open_fields(fields)])
        line = "commits run in its development shell: devenv shell (found in its files)"
        entry = next(e for e in cd.shown(fields) if e["field"] == "commit-environment")
        self.assertEqual(entry["line"], line)
        self.assertIs(entry["more"], False)
        self.assertEqual(entry["options"], [
            {"value": "none", "label": "Commits run outside a development shell"}])
        self.assertEqual(entry["placeholder"], "the development shell command")
        self.assertEqual(cd.proposed_lines(fields), [line])
        self.assertEqual(
            by_field(fields)["commit-environment"]["ask"],
            f"Which command opens the development shell the commits of {root.name} run in?\n"
            "Its commit hooks need its development shell: type the command, or say they need none.")
        self.assertEqual(cd.more_line(fields), "and 22 more settings at their usual values")
        fields = self.settled(fields, str(root), build_command="none", test_command="none")
        drafted = cd.contract(fields)
        self.assertEqual(drafted["bindings"]["commands"]["commit-environment"],
                         {"argv": ["devenv", "shell", "--"], "cwd": ".", "env": []})
        self.assertEqual(drafted["bindings"]["vcs"]["commit"]["environment"], "commit-environment")
        del drafted["bindings"]["commands"]["commit-environment"]
        del drafted["bindings"]["vcs"]["commit"]["environment"]
        self.assertEqual(drafted, self.expected_contract())

    def test_the_drafted_contract_with_a_commit_environment_resolves(self):
        root = self.environment_checkout()
        fields = cd.draft(str(root), cd.read(str(root)))
        fields = self.settled(fields, str(root), build_command="none", test_command="none")
        version = json.loads(MANIFEST.read_text())["platform_version"]
        major = int(version.split(".")[0])
        drafted = cd.contract(fields)
        drafted["platform"] = {"min_inclusive": version, "max_exclusive": f"{major + 1}.0.0"}
        copy = self.parent / "copy"
        shutil.copytree(root, copy)
        (copy / ".agents").mkdir()
        (copy / ".agents" / "project.json").write_text(json.dumps(drafted))
        home = self.parent / "home"
        (home / ".agents" / "share").mkdir(parents=True)
        shutil.copy(MANIFEST, home / ".agents" / "share" / "platform-manifest.json")
        env = {**os.environ, "HOME": str(home), "PYTHONPATH": str(ROOT / "python")}
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.project_contract.resolve_project", "resolve",
             "--repo-root", str(copy)],
            env=env, text=True, stdin=subprocess.DEVNULL, capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        resolved = json.loads(done.stdout)
        self.assertEqual(resolved["bindings"]["vcs"]["commit"]["environment"], "commit-environment")

    def global_hooks(self, parent):
        hooks = parent / "f-global-hooks"
        hooks.mkdir(parents=True)
        (hooks / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
        (hooks / "pre-commit").chmod(0o755)
        config = parent / "f-global.gitconfig"
        config.write_text(f"[core]\n\thooksPath = {hooks}\n")
        saved = os.environ.get("GIT_CONFIG_GLOBAL")
        os.environ["GIT_CONFIG_GLOBAL"] = str(config)
        self.addCleanup(os.environ.pop if saved is None else os.environ.__setitem__,
                        "GIT_CONFIG_GLOBAL", *([] if saved is None else [saved]))

    def test_without_a_committed_devenv_or_an_installed_commit_hook_the_draft_is_as_today(self):
        def a(root):
            commit(root, {"devenv.nix": "{ }\n"})
            install_hook(root, "pre-commit.sample")

        def b(root):
            install_hook(root)

        def c(root):
            (root / "devenv.nix").write_text("{ }\n")
            install_hook(root)

        def d(root):
            commit(root, {"devenv.nix": "{ }\n"})
            install_hook(root, mode=0o644)

        def e(root):
            commit(root, {"devenv.nix": "{ }\n"})
            install_hook(root, "pre-push")

        def f(root):
            commit(root, {"devenv.nix": "{ }\n"})
            self.global_hooks(root.parent)

        def h(root):
            commit(root, {"devenv.nix": "{ }\n"})
            install_hook(root, "post-commit", "#!/bin/sh\ngit lfs post-commit \"$@\"\n")

        def i(root):
            (root / "devenv.nix").write_text("{ }\n")
            git(root, "add", "devenv.nix")
            install_hook(root)

        for letter, arrange in (("a", a), ("b", b), ("c", c), ("d", d), ("e", e), ("f", f),
                                ("h", h), ("i", i)):
            with self.subTest(case=letter):
                root = sample(self.parent / letter, remote=True)
                arrange(root)
                fields = cd.draft(str(root), cd.read(str(root)))
                self.assertEqual([x["field"] for x in fields], list(cd.FIELDS))
                self.assertEqual(getattr(cd, "proposed_lines", lambda fs: [])(fields), [])
                fields = self.settled(fields, str(root), build_command="none", test_command="none")
                self.assertEqual(cd.contract(fields), self.expected_contract())

    def test_only_the_repository_s_own_hooks_directory_is_read(self):
        with self.subTest(case="g"):
            root = sample(self.parent / "g", remote=True)
            commit(root, {"devenv.nix": "{ }\n"})
            git(root, "config", "core.hooksPath", "local-hooks")
            (root / "local-hooks").mkdir()
            (root / "local-hooks" / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
            (root / "local-hooks" / "pre-commit").chmod(0o755)
            commit(root, {})
            reading = cd.read(str(root))
            self.assertEqual(reading["hooks"], ["pre-commit"])
            fields = cd.draft(str(root), reading)
            self.assertIn("commit-environment", [x["field"] for x in fields])
        with self.subTest(case="f-prime"):
            root = sample(self.parent / "f", remote=True)
            commit(root, {"devenv.nix": "{ }\n"})
            self.global_hooks(root.parent)
            reading = cd.read(str(root))
            self.assertEqual(reading["hooks"], [])
            self.assertEqual(reading["environments"], ["devenv.nix"])

    def test_a_relative_hooks_path_counts_only_a_hook_the_apply_worktree_will_have(self):
        for letter, track, mode, wanted in (("untracked", False, 0o755, []),
                                            ("plain", True, 0o644, []),
                                            ("tracked", True, 0o755, ["pre-commit"])):
            with self.subTest(case=letter):
                root = sample(self.parent / letter, remote=True)
                commit(root, {"devenv.nix": "{ }\n"})
                git(root, "config", "core.hooksPath", "local-hooks")
                (root / "local-hooks").mkdir()
                (root / "local-hooks" / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
                (root / "local-hooks" / "pre-commit").chmod(mode)
                if track:
                    commit(root, {})
                reading = cd.read(str(root))
                self.assertEqual(reading["hooks"], wanted)
                fields = cd.draft(str(root), reading)
                self.assertEqual("commit-environment" in [x["field"] for x in fields], bool(wanted))

    def scoped_environment(self, values):
        """Set (a string) or remove (None) each named variable until the test ends."""
        for name, value in values.items():
            saved = os.environ.get(name)
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
            self.addCleanup(os.environ.pop if saved is None else os.environ.__setitem__,
                            name, *([None] if saved is None else [saved]))

    UNTRUSTED_HOST = {
        "GIT_CONFIG_NOSYSTEM": None, "GIT_CONFIG_COUNT": None, "GIT_CONFIG_PARAMETERS": None,
        "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"}

    def test_the_hooks_are_found_in_a_checkout_trusted_only_through_the_global_configuration(self):
        root = self.environment_checkout()
        config = self.parent / "trust.gitconfig"
        config.write_text(f"[safe]\n\tdirectory = {root}\n")
        self.scoped_environment({
            **self.UNTRUSTED_HOST, "GIT_CONFIG_GLOBAL": str(config), "GIT_CONFIG_SYSTEM": os.devnull})
        self.assertEqual(cd.read(str(root))["hooks"], ["pre-commit"])
        config.write_text("")
        self.assertEqual(cd.read(str(root))["hooks"], [])

    def test_the_hooks_are_found_in_a_checkout_trusted_only_through_the_system_configuration(self):
        root = self.environment_checkout()
        system = self.parent / "trust-system.gitconfig"
        system.write_text(f"[safe]\n\tdirectory = {root}\n")
        self.scoped_environment({
            **self.UNTRUSTED_HOST, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": str(system)})
        self.assertEqual(cd.read(str(root))["hooks"], ["pre-commit"])
        system.write_text("")
        self.assertEqual(cd.read(str(root))["hooks"], [])

    def test_a_scoped_environment_is_restored_after_the_test(self):
        self.scoped_environment({"GIT_CONFIG_COUNT": "0", "GIT_CONFIG_GLOBAL": "known"})

        class Inner(unittest.TestCase):
            scoped_environment = ContractDraftTest.scoped_environment

            def test_it(self):
                self.scoped_environment({"GIT_CONFIG_GLOBAL": "x", "GIT_CONFIG_COUNT": None})

        done = unittest.TextTestRunner(stream=io.StringIO()).run(Inner("test_it"))
        self.assertTrue(done.wasSuccessful())
        self.assertEqual(os.environ["GIT_CONFIG_COUNT"], "0")
        self.assertEqual(os.environ["GIT_CONFIG_GLOBAL"], "known")

    def test_a_directory_named_like_an_environment_file_is_not_that_file(self):
        root = sample(self.parent / "dir", remote=True)
        (root / "devenv.nix").mkdir()
        commit(root, {"devenv.nix/README.md": "x\n"})
        install_hook(root)
        reading = cd.read(str(root))
        self.assertEqual(reading["environments"], [])
        fields = cd.draft(str(root), reading)
        self.assertNotIn("commit-environment", [x["field"] for x in fields])

    def test_the_owner_can_change_or_drop_the_proposed_commit_environment(self):
        root = self.environment_checkout()
        fields = cd.draft(str(root), cd.read(str(root)))
        fields = self.settled(fields, str(root), build_command="none", test_command="none")
        dropped, error = cd.set_value(fields, "commit-environment", "none", entries=[], root=str(root))
        self.assertIsNone(error)
        line = "commits run in its development shell: none (set by you)"
        self.assertEqual([e["line"] for e in cd.shown(dropped) if e["field"] == "commit-environment"],
                         [line])
        self.assertEqual(cd.proposed_lines(dropped), [line])
        drafted = cd.contract(dropped)
        self.assertNotIn("commit-environment", drafted["bindings"]["commands"])
        self.assertNotIn("environment", drafted["bindings"]["vcs"]["commit"])
        typed, error = cd.set_value(fields, "commit-environment", "nix develop --command",
                                    entries=[], root=str(root))
        self.assertIsNone(error)
        self.assertEqual(cd.contract(typed)["bindings"]["commands"]["commit-environment"]["argv"],
                         ["nix", "develop", "--command"])
        self.assertEqual(cd.set_value(fields, "commit-environment", "devenv 'shell", entries=[],
                                      root=str(root)), (None, cd.COMMAND_UNREADABLE))
        again, _ = cd.set_value(fields, "commit-environment", "devenv shell --", entries=[],
                                root=str(root))
        self.assertEqual(
            next(e["line"] for e in cd.shown(again) if e["field"] == "commit-environment"),
            "commits run in its development shell: devenv shell (set by you)")
        self.assertEqual(cd.contract(again)["bindings"]["commands"]["commit-environment"]["argv"],
                         ["devenv", "shell", "--"])
        plain = str(sample(self.parent / "plain", remote=True))
        bare = cd.draft(plain, cd.read(plain))
        self.assertEqual(cd.set_value(bare, "commit-environment", "devenv shell --", entries=[],
                                      root=plain), (None, cd.UNKNOWN_FIELD))

    def test_a_refusal_of_the_commit_environment_reopens_its_field(self):
        wanted = ("commit-environment", "The plan refused the commits run in its development shell: m")
        for pointer in ("/bindings/commands/commit-environment/argv/0",
                        "/bindings/vcs/commit/environment"):
            error = {"repair_id": "adopt.draft.invalid",
                     "violations": [{"pointer": pointer, "message": "m"}]}
            self.assertEqual(cd.refused_field(error), wanted)
        error = {"repair_id": "adopt.draft.invalid",
                 "violations": [{"pointer": "/bindings/vcs/commit/signed", "message": "m"}]}
        self.assertEqual(cd.refused_field(error)[0], "commit-signed")

    def test_a_typed_id_is_checked_against_the_rule_and_the_registry(self):
        root, fields = self.remote_fields()
        before = json.dumps(fields)
        self.assertEqual(cd.set_value(fields, "project-id", "not an id", entries=[], root=root),
                         (None, cd.ID_RULE))
        self.assertEqual(cd.set_value(fields, "project-id", "a/b/c", entries=[], root=root),
                         (None, cd.ID_RULE))
        self.assertEqual(cd.set_value(fields, "project-id", "  ", entries=[], root=root),
                         (None, cd.EMPTY_VALUE))
        entries = [{"project_id": "someone/taken", "root": "/elsewhere"}]
        self.assertEqual(cd.set_value(fields, "project-id", "someone/taken", entries=entries, root=root),
                         (None, "someone/taken is already registered for another checkout"))
        here = [{"project_id": "someone/taken", "root": root}]
        accepted, error = cd.set_value(fields, "project-id", "someone/taken", entries=here, root=root)
        self.assertIsNone(error)
        self.assertEqual(pair(accepted, "project-id"), ("someone/taken", "owner"))
        new, error = cd.set_value(fields, "project-id", "sample-owner/other", entries=[], root=root)
        self.assertIsNone(error)
        self.assertEqual(pair(new, "project-id"), ("sample-owner/other", "owner"))
        self.assertEqual(json.dumps(fields), before)

    def test_a_read_id_registered_for_another_checkout_opens_its_card(self):
        root = str(sample(self.parent, remote=True))
        reading = cd.read(root)
        entry = {"project_id": ID, "root": "/elsewhere"}
        text = f"{ID} is already registered for another checkout"
        fields = cd.draft(root, reading, entries=[entry])
        record = by_field(fields)["project-id"]
        self.assertEqual((record["value"], record["reason"]), (ID, text))
        self.assertEqual(cd.open_fields(fields)[0]["field"], "project-id")
        question = cd.questions(fields)[0]
        self.assertEqual((question["why"], question["text"]), (text, True))
        plain = cd.draft(root, reading)
        self.assertEqual(cd.taken_id(plain, [entry], root), text)
        self.assertIsNone(cd.taken_id(plain, [], root))

    def test_choices_and_typed_values_are_checked_before_the_contract(self):
        root, fields = self.remote_fields()

        def put(field, value):
            return cd.set_value(fields, field, value, entries=[], root=root)

        self.assertEqual(put("tracker", "gitlab"), (None, cd.NOT_OFFERED))
        self.assertEqual(put("nonsense", "x"), (None, cd.UNKNOWN_FIELD))
        for field, value in (("build-command", "none"), ("build-command", "make all"),
                             ("release", "unsupported")):
            new, error = put(field, value)
            self.assertIsNone(error)
            cd.contract(new)
        for field, value in (("build-command", 'echo "unterminated'),
                             ("build-command", "echo trailing\\"),
                             ("review-code-command", 'say "x')):
            self.assertEqual(put(field, value), (None, cd.COMMAND_UNREADABLE))
        for value in ('{"oops"', '{"a": 1, "a": 2}'):
            self.assertEqual(put("release", value), (None, cd.NOT_JSON))

    def test_a_resolver_refusal_maps_to_its_field_in_plain_words(self):
        root, fields = self.remote_fields()
        message = "must be a non-empty repository-relative path with no '..' segment"
        error = {"code": "adopt_failure", "repair_id": "adopt.draft.invalid",
                 "violations": [{"pointer": "/bindings/paths/architecture/0", "message": message}]}
        refused = cd.refused_field(error)
        text = f"The plan refused the documentation: {message}"
        self.assertEqual(refused, ("docs-paths", text))
        slug = {"repair_id": "adopt.draft.invalid",
                "violations": [{"pointer": "/bindings/tracker/repo_slug", "message": "m  x"}]}
        self.assertEqual(cd.refused_field(slug), ("project-id", "The plan refused the project id: m x"))
        taken = {"repair_id": "adopt.draft.id_taken", "violations": [
            {"pointer": "/project/id",
             "message": "the project id is already registered for another checkout"}]}
        self.assertEqual(cd.refused_field(taken), (
            "project-id",
            "The plan refused the project id: the project id is already registered for another checkout"))
        self.assertIsNone(cd.refused_field({**taken, "repair_id": "adopt.other"}))
        self.assertIsNone(cd.refused_field({"repair_id": "adopt.draft.invalid", "violations": [
            {"pointer": "/schema_version", "message": "x"}]}))
        marked = cd.mark_refused(fields, *refused)
        docs = [q for q in cd.questions(marked) if q["subject"] == "docs-paths"][0]
        self.assertEqual((docs["why"], docs["text"]), (text, True))
        for question in cd.questions(marked):
            for part in (question["ask"], question["why"] or ""):
                for word in ("adopt.", "contract.", "/bindings"):
                    self.assertNotIn(word, part)

    def test_every_settled_value_is_shown_with_its_source(self):
        root, fields = self.remote_fields()
        lines = cd.shown(fields)
        self.assertEqual(len(lines), 27)
        self.assertTrue(all(entry["field"] for entry in lines))
        order = [entry["field"] for entry in lines]
        self.assertEqual(order, [f for f in cd.FIELDS if f not in ("build-command", "test-command")])
        self.assertEqual([e["field"] for e in lines if not e["more"]],
                         ["project-id", "project-name", "default-branch", "tracker", "docs-paths"])
        for entry in lines:
            self.assertEqual(set(entry),
                             {"field", "line", "value", "options", "text", "more", "placeholder"})
        texts = [entry["line"] for entry in lines]
        for line in (
            f"project id: {ID} (read from its remote)",
            f"issue tracker: GitHub, as {ID} (read from its remote)",
            "finished work merges into the default branch",
            "work branches are named after their issue",
            "it makes no releases",
        ):
            self.assertIn(line, texts)

    def test_no_shown_line_uses_an_internal_term(self):
        root, fields = self.remote_fields()
        shown = cd.shown(fields)
        words = [entry["line"] for entry in shown]
        words += [option["label"] for entry in shown for option in entry["options"]]
        words.append(cd.more_line(fields))
        words += list(cd.LABELS.values())
        for text in words:
            for term in ("<num>", "<slug>", "light lane", "hint", "operations path",
                         "rejection path", "the console's starting value"):
                self.assertNotIn(term, text.lower())
        (light,) = [e for e in shown if e["field"] == "light-lane"]
        self.assertEqual([o["label"] for o in light["options"]],
                         ["Every change takes the full delivery route"])

    def test_the_counted_line_says_how_many_and_whether_you_changed_any(self):
        root, fields = self.remote_fields()
        count = len([f for f in cd.FIELDS if f not in cd.MAIN])
        self.assertEqual(count, 22)
        self.assertEqual(cd.more_line(fields), f"and {count} more settings at their usual values")
        new, _ = cd.set_value(fields, "max-parallel", "2", entries=[], root=root)
        self.assertEqual(cd.more_line(new), f"and {count} more settings, 1 of them set by you")
        (line,) = [e["line"] for e in cd.shown(new) if e["field"] == "max-parallel"]
        self.assertEqual(line, "deliveries at once: 2 (set by you)")

    def test_every_text_field_has_a_placeholder(self):
        root, fields = self.remote_fields()
        for field in cd.FIELDS:
            if cd.TEXT[field]:
                self.assertTrue(isinstance(cd.placeholder(field), str) and cd.placeholder(field))
            else:
                self.assertIsNone(cd.placeholder(field))
        self.assertEqual([f for f in cd.FIELDS if cd.placeholder(f) is None],
                         ["commit-signed", "co-authored-by", "delete-branch", "tracker"])
        self.assertEqual(cd.placeholder("project-id"), "owner/name")
        self.assertEqual(cd.placeholder("build-command"), "the build command")
        self.assertEqual(cd.placeholder("test-command"), "the test command")
        for entry in cd.shown(fields):
            self.assertEqual(entry["placeholder"], cd.placeholder(entry["field"]))

    def test_the_default_branch_ask_follows_the_remote_count(self):
        def ask(remotes):
            reading = {"remotes": remotes, "default_branch": None, "branches": ["trunk"],
                       "files": [], "texts": {}}
            return by_field(cd.draft("/x/sample-app", reading))["default-branch"]["ask"]
        none = ask([])
        self.assertTrue(none.endswith(
            "It has no remote, so the console cannot tell: choose a branch or type its name."))
        self.assertNotIn("Its remote", none)
        two = ask([("a", "git@github.com:o/a.git"), ("b", "git@github.com:o/b.git")])
        self.assertIn("It has 2 remotes, so the console cannot tell which one to ask", two)
        one = ask([("origin", "git@github.com:sample-owner/sample-app.git")])
        self.assertIn("Its remote did not say", one)

    def test_reading_never_raises_or_writes(self):
        plain = self.parent / "plain"
        plain.mkdir()
        self.assertEqual(cd.read(str(plain)),
                         {"remotes": [], "default_branch": None, "branches": [], "files": [], "texts": {},
                          "hooks": [], "environments": []})
        root = str(sample(self.parent, remote=True))
        before = (git(root, "status", "--porcelain"), git(root, "rev-parse", "HEAD^{tree}"))
        cd.read(root)
        self.assertEqual((git(root, "status", "--porcelain"), git(root, "rev-parse", "HEAD^{tree}")), before)

    def test_the_draft_id_is_the_canonical_digest(self):
        root, fields = self.remote_fields()
        self.assertEqual(cd.draft_id(root, fields),
                         "draft:" + canonical.telemetry_digest({"root": root, "fields": fields}))
        new = self.settled(fields, root, max_parallel="2")
        self.assertNotEqual(cd.draft_id(root, new), cd.draft_id(root, fields))


if __name__ == "__main__":
    unittest.main()
