"""The reference-formatting cases of `adopt-project apply` (#350, #1078).

They live beside the apply suite to keep it under the B17 budget; the fixtures
come from `.test_adopt_apply` and `.test_adopt_project`, and no `TestCase` with
tests crosses over, so neither file collects the other's tests.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.project_contract import (adopt_apply, adopt_inspection, adopt_links,
                                          resolve_project)

from .test_adopt_apply import CONTRACT, ApplyTestCase, apply_repo
from .test_adopt_project import answer_args, commit, git, run, write, write_linked_tree

TIER = "integration"  # every case runs a real git repository


# #376 D15: the fixture's own lint and formatter, standard-library scripts
# that walk `*.py` from their working directory, so the same lint runs in
# the adoption worktree and on an export of the adoption commit.
LINT = "tools/lint.py"
FORMATTER = "tools/format.py"
LINT_TEXT = (
    "import pathlib\n"
    "import sys\n"
    "\n"
    "LIMIT = 60\n"
    "long = []\n"
    'for path in sorted(pathlib.Path(".").rglob("*.py")):\n'
    '    text = path.read_text(encoding="utf-8")\n'
    "    for number, line in enumerate(text.splitlines(), 1):\n"
    "        if len(line) > LIMIT:\n"
    '            long.append(f"{path}:{number}")\n'
    'print("\\n".join(long))\n'
    "sys.exit(1 if long else 0)\n")
# Rewraps a `name = value` line over the limit and strips trailing
# whitespace in the files it is given; `--fail` exits non-zero and each
# `--touch PATH` appends a line to PATH first.
FORMATTER_TEXT = (
    "import sys\n"
    "\n"
    "LIMIT = 60\n"
    "args = sys.argv[1:]\n"
    'if args[:1] == ["--fail"]:\n'
    "    sys.exit(3)\n"
    'while args[:1] == ["--touch"]:\n'
    '    with open(args[1], "a", encoding="utf-8") as handle:\n'
    '        handle.write("# touched\\n")\n'
    "    args = args[2:]\n"
    "\n"
    "\n"
    "def wrapped(line):\n"
    '    head, sep, tail = line.partition(" = ")\n'
    "    if len(line) <= LIMIT or not sep:\n"
    "        return [line]\n"
    '    return [head + " = (", "    " + tail, ")"]\n'
    "\n"
    "\n"
    "for name in args:\n"
    '    with open(name, encoding="utf-8") as handle:\n'
    "        lines = handle.read().splitlines()\n"
    "    out = []\n"
    "    for line in lines:\n"
    "        out.extend(wrapped(line.rstrip()))\n"
    '    with open(name, "w", encoding="utf-8") as handle:\n'
    '        handle.write("".join(x + "\\n" for x in out))\n')
ANALYZER = "tests/test_analyzer.py"
ANALYZER_SUBJECT = f"{ANALYZER}:1:34"
ANALYZER_TEXT = 'ANALYZER_SPEC_PATH_UNDER_TEST = ".out-of-scope/z.md"\n'
ANALYZER_REWRITTEN = ANALYZER_TEXT.replace(".out-of-scope",
                                           ".agents/knowledge/rejections")
# #376 COR-001: a `generated_file` projection rendered from the analyzer.
PROJECTED_ANALYZER = "generated/analyzer.txt"
# #376 COR-PROJECTION-KIND: a `managed_import` naming the analyzer by path.
IMPORTED_ANALYZER = "generated/analyzer-import.txt"
ANALYZER_FORMATTED = ('ANALYZER_SPEC_PATH_UNDER_TEST = (\n'
                      '    ".agents/knowledge/rejections/z.md"\n'
                      ')\n')
CLEAN = "tests/clean.py"
CLEAN_TEXT = "VALUE = 1   \n"
# A moved file no link rewrite edits: its last operation is the `git-mv`.
SHIFTED = ".agents/knowledge/rejections/w.md"
FORMAT_COMMANDS = {
    "format": [sys.executable, FORMATTER],
    "broken": [sys.executable, FORMATTER, "--fail"],
    "meddle": [sys.executable, FORMATTER, "--touch", ".gitignore"],
    # #376 D17: a move-only destination (a `git-mv` whose `after` is a
    # `git-object:` hash), edited on disk and never staged.
    "shift": [sys.executable, FORMATTER, "--touch", SHIFTED],
    "spill": [sys.executable, FORMATTER, "--touch", CLEAN],
    "litter": [sys.executable, FORMATTER, "--touch", "stray.txt"],
}
ARCHIVED_LINK_SOURCE = ".claude/odd-link.md"
ARCHIVED_LINK = ".agents/knowledge/archive/adopted/.claude/odd-link.md"
REWRITE_ANALYZER = ("path-reference", ANALYZER_SUBJECT, "rewrite")


def formatting_repo(home: Path) -> Path:
    """`apply_repo` whose verification command is the line-limit lint, with
    the formatter commands, #345's linked tree (a moved Markdown file whose
    link is rewritten), a reference whose rewrite crosses the limit and a
    second Python file that is not format-clean."""
    root = apply_repo(home, verification=(sys.executable, LINT),
                      commands=FORMAT_COMMANDS)
    for path, text in ((LINT, LINT_TEXT), (FORMATTER, FORMATTER_TEXT),
                       (ANALYZER, ANALYZER_TEXT), (CLEAN, CLEAN_TEXT)):
        write(root, path, text)
    commit(root, "add a lint, a formatter and two Python files")
    write_linked_tree(root)
    return root


class ReferenceFormattingApplyTest(ApplyTestCase):
    """#376 AC1, AC4: the declared formatter runs over the reference-edited
    files inside `apply`, confined, before the commit gates."""

    def planned(self, root: Path, *triples: tuple[str, str, str]) -> dict:
        code, out, err = run("plan", "--repo-root", str(root),
                             *answer_args(*triples), home=self.home)
        self.assertEqual(code, 0, err or out)
        document = json.loads(out)
        self.assertEqual(document["plan"]["state"], "ready",
                         document["plan"]["blockers"])
        return document

    def lint(self, root: Path, revision: str) -> int:
        export = Path(tempfile.mkdtemp()) / "tree"
        adopt_inspection.export_commit(root, revision, export)
        return subprocess.run([sys.executable, LINT], cwd=export,
                              capture_output=True, timeout=120).returncode

    def test_the_formatted_rewrite_commits_and_passes_the_lint(self):
        self.assertLessEqual(len(ANALYZER_TEXT) - 1, 60)
        self.assertGreater(len(ANALYZER_REWRITTEN) - 1, 60)
        root = formatting_repo(self.home)
        base = git(root, "rev-parse", "HEAD").strip()
        self.assertEqual(self.lint(root, "HEAD"), 0)
        document = self.planned(root, REWRITE_ANALYZER,
                                ("reference-format", ".py", "format"))
        self.assertEqual(document["reference_formatting"], [
            {"class": ".py", "command": "format", "files": [ANALYZER]}])
        (write_op,) = [op for op in document["changes"]
                       if op["op"] == "write-file"
                       and op["targets"] == [ANALYZER]]
        self.assertEqual(write_op["after"], adopt_inspection.sha256_hash(
            ANALYZER_REWRITTEN.encode("utf-8")))
        moved = {op["targets"][0] for op in document["changes"]
                 if op["op"] == "git-mv"}
        self.assertTrue(any(
            op["op"] == "write-file" and op["targets"][0] in moved
            and adopt_links.is_markdown_path(op["targets"][0])
            for op in document["changes"]))
        result = self.succeed(root, document["plan"]["plan_id"])
        branch = result["branch"]
        self.assertEqual(git(root, "show", f"{branch}:{ANALYZER}"),
                         ANALYZER_FORMATTED)
        self.assertEqual(git(root, "rev-parse", f"{branch}:{CLEAN}"),
                         git(root, "rev-parse", f"HEAD:{CLEAN}"))
        self.assertEqual(self.lint(root, branch), 0)
        required, optional = adopt_apply.expected_commit_paths(
            document["changes"])
        changed = set(git(root, "diff", "--name-only", "--no-renames",
                          base, branch).splitlines())
        self.assertTrue(required <= changed <= required | optional,
                        changed ^ required)
        git(root, "merge", "--ff-only", "--quiet", branch)
        code, out, err = run("verify", "--repo-root", str(root),
                             home=self.home)
        self.assertEqual(code, 0, err or out)
        (check,) = [entry for entry in json.loads(out)["checks"]
                    if entry["id"] == "adoption-commit-derived"]
        self.assertEqual(check["status"], "passed")

    def test_without_a_format_answer_the_lint_gate_refuses(self):
        root = formatting_repo(self.home)
        base = git(root, "rev-parse", "HEAD").strip()
        document = self.planned(root, REWRITE_ANALYZER)
        self.assertEqual(document["reference_formatting"], [
            {"class": ".py", "command": None, "files": [ANALYZER]}])
        self.assert_retained(root, document["plan"]["plan_id"], base,
                             "adopt.gate.workflow-verification-commands")

    def test_an_unconfined_or_failing_formatter_is_refused(self):
        for command, repair_id in (
                ("broken", "adopt.format.failed"),
                ("meddle", "adopt.format.unplanned_content"),
                ("shift", "adopt.format.unplanned_content"),
                ("spill", "adopt.gate.worktree-status-matches-operations"),
                ("litter", "adopt.gate.worktree-status-matches-operations")):
            with self.subTest(command=command):
                root = formatting_repo(self.home)
                base = git(root, "rev-parse", "HEAD").strip()
                plan_id = self.planned(
                    root, REWRITE_ANALYZER,
                    ("reference-format", ".py", command))["plan"]["plan_id"]
                if command == "shift":
                    stored = json.loads(
                        self.stored_plan(plan_id).read_text("utf-8"))
                    (last,) = [op for op in stored["changes"]
                               if op["targets"][:1] == [SHIFTED]][-1:]
                    self.assertEqual(last["op"], "git-mv")
                    self.assertTrue(last["after"].startswith("git-object:"))
                payload = self.assert_retained(root, plan_id, base, repair_id)
                record = json.loads(self.state(
                    "adopt", "worktrees",
                    self.digest(plan_id) + ".failure.json").read_text("utf-8"))
                if command == "broken":
                    # The refusal names the command and its exit status (the
                    # fixture formatter's `--fail` exits 3).
                    (violation,) = payload["error"]["violations"]
                    self.assertEqual(violation["pointer"],
                                     "/reference_formatting")
                    self.assertIn("'broken'", violation["message"])
                    self.assertIn(" 3;", violation["message"])
                if repair_id.startswith("adopt.format."):
                    self.assertEqual(
                        {gate["status"] for gate in record["gates"]},
                        {"not_run"})

    def test_a_formatted_projection_source_is_refused_before_formatting(self):
        """A reference-edited file whose `generated_file` projection was
        regenerated from its bytes before formatting would change them is
        refused, rather than left to strand a stale target. The contract may
        spell the source with a `./` or a repeated `/` (COR-002), and the
        refusal still holds."""
        for source in (ANALYZER, "./" + ANALYZER,
                       ANALYZER.replace("/", "//", 1)):
            with self.subTest(source=source):
                self.assert_projection_source_refused(source)

    def assert_projection_source_refused(self, source: str) -> None:
        root = formatting_repo(self.home)
        contract = json.loads((root / CONTRACT).read_text("utf-8"))
        entry = {"id": "codex.analyzer", "agent": "codex",
                 "kind": "generated_file", "target": PROJECTED_ANALYZER,
                 "source": source}
        contract["projections"].append(entry)
        write(root, CONTRACT, json.dumps(contract, indent=2) + "\n")
        # Rendered by the resolver's own function, so the target starts in
        # sync: the fixture contract has no `platform`, which the
        # `write-projections` verb would refuse.
        write(root, PROJECTED_ANALYZER, resolve_project.render_projection(
            entry, (root / ANALYZER).read_bytes(),
            contract["schema_version"]).decode("utf-8"))
        commit(root, "project the analyzer")
        base = git(root, "rev-parse", "HEAD").strip()
        document = self.planned(root, REWRITE_ANALYZER,
                                ("reference-format", ".py", "format"))
        self.assertEqual(document["reference_formatting"], [
            {"class": ".py", "command": "format", "files": [ANALYZER]}])
        self.assertIn(
            [PROJECTED_ANALYZER],
            [op["targets"] for op in document["changes"]
             if op["op"] == "regenerate-projection"])
        plan_id = document["plan"]["plan_id"]
        payload = self.assert_retained(root, plan_id, base,
                                       "adopt.format.failed")
        self.assertEqual([v["pointer"] for v in payload["error"]["violations"]],
                         ["/reference_formatting"])
        record = json.loads(self.state(
            "adopt", "worktrees",
            self.digest(plan_id) + ".failure.json").read_text("utf-8"))
        self.assertEqual({gate["status"] for gate in record["gates"]},
                         {"not_run"})
        # The formatter never ran: the file holds the rewrite it was given.
        self.assertEqual(
            (self.worktree(plan_id) / ANALYZER).read_text("utf-8"),
            ANALYZER_REWRITTEN)

    def test_a_managed_import_source_is_formatted(self):
        """A `managed_import` line names its source by path alone, so
        formatting that source leaves the projection in sync and is not
        refused."""
        root = formatting_repo(self.home)
        contract = json.loads((root / CONTRACT).read_text("utf-8"))
        entry = {"id": "codex.analyzer", "agent": "codex",
                 "kind": "managed_import", "target": IMPORTED_ANALYZER,
                 "source": ANALYZER}
        contract["projections"].append(entry)
        write(root, CONTRACT, json.dumps(contract, indent=2) + "\n")
        write(root, IMPORTED_ANALYZER, resolve_project.render_projection(
            entry, (root / ANALYZER).read_bytes(),
            contract["schema_version"]).decode("utf-8"))
        commit(root, "import the analyzer")
        document = self.planned(root, REWRITE_ANALYZER,
                                ("reference-format", ".py", "format"))
        self.assertIn(
            ([ANALYZER], [IMPORTED_ANALYZER]),
            [(op["sources"], op["targets"]) for op in document["changes"]
             if op["op"] == "regenerate-projection"])
        result = self.succeed(root, document["plan"]["plan_id"])
        self.assertEqual(git(root, "show", f"{result['branch']}:{ANALYZER}"),
                         ANALYZER_FORMATTED)

    def test_an_archived_contained_symlink_is_not_an_unplanned_change(self):
        """`git add` stores a symlink's target text, so the confinement proof
        hashes that text, not the file the link points to."""
        root = formatting_repo(self.home)
        (root / ARCHIVED_LINK_SOURCE).symlink_to("../README.md")
        git(root, "add", ARCHIVED_LINK_SOURCE)
        commit(root, "track a contained agent link")
        document = self.planned(
            root, REWRITE_ANALYZER, ("reference-format", ".py", "format"),
            ("candidate-class", ARCHIVED_LINK_SOURCE, "archive-history"))
        (last,) = [op for op in document["changes"]
                   if op["targets"][:1] == [ARCHIVED_LINK]][-1:]
        self.assertEqual(last["op"], "git-mv")
        self.assertTrue(last["after"].startswith("git-object:"))
        result = self.succeed(root, document["plan"]["plan_id"])
        self.assertEqual(
            git(root, "ls-tree", result["branch"], ARCHIVED_LINK).split()[0],
            "120000")

    def test_the_stored_plan_lists_the_format_answer_and_rows(self):
        root = formatting_repo(self.home)
        answers = (REWRITE_ANALYZER, ("reference-format", ".py", "format"))
        document = self.planned(root, *answers)
        result = self.succeed(root, document["plan"]["plan_id"])
        stored = json.loads(self.stored_plan(result["plan_id"]).read_text("utf-8"))
        for question, subject, value in answers:
            with self.subTest(subject=subject):
                self.assertIn(
                    {"id": question, "subject": subject, "value": value},
                    stored["decisions"]["answered"])
        for member in ("reference_formatting", "reference_policies",
                       "path_references"):
            with self.subTest(member=member):
                self.assertEqual(stored[member], document[member])


if __name__ == "__main__":
    unittest.main()
