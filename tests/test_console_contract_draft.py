"""The console's drafted project contract (#1067): the reading, the fields, the contract, the refusals.

Run: just agent-workflow-tests
"""

from __future__ import annotations

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


def by_field(fields):
    return {f["field"]: f for f in fields}


def pair(fields, field):
    record = by_field(fields)[field]
    return record["value"], record["source"]


class DraftTest(unittest.TestCase):
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
        text = f"The plan refused the documentation paths: {message}"
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
        texts = [entry["line"] for entry in lines]
        for line in (
            f"project id: {ID} (read from its remote)",
            "integration branch: the same as the default branch (the console's starting value)",
            f"issue tracker: GitHub, as {ID} (read from its remote)",
            "release profile: unsupported (the console's starting value)",
        ):
            self.assertIn(line, texts)

    def test_reading_never_raises_or_writes(self):
        plain = self.parent / "plain"
        plain.mkdir()
        self.assertEqual(cd.read(str(plain)),
                         {"remotes": [], "default_branch": None, "branches": [], "files": [], "texts": {}})
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
