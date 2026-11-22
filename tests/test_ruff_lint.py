"""The Ruff adapter of the never-rise check, `agent_tools.delivery.ruff_lint` (#1460).

Measures the adapter against real git worlds and the pinned Ruff: an unused
import and a commented-out statement each print one `PY` line, a reasoned
`noqa` hides its finding and a bare or reasonless one prints, a branch that adds
a finding rises and one that removes it passes, only a directory below a
`pyproject.toml` is judged, no Ruff configuration is read, Ruff runs by its
command name from the pinned directory alone and once per revision, and every
failure of Ruff or of the scratch directory is a closed failure, never a pass.
The suite holds `standard:PY6`, `standard:PY7`, `standard:PY8`, `standard:PY9`,
`standard:PY10`, `standard:PY11`, `standard:PY12` and `standard:PY13` through this
enforcer, so the rule index lists it.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import never_rise, rule_ids, ruff_lint
from agent_tools.delivery.never_rise import EnforcerFailed, Rise, Snapshot, Violation
from tests.test_never_rise import commit_all, git, mark_base, recordings, repo, write

TIER = "integration"

TOOLS = os.environ.get("AGENT_PLATFORM_TOOLS")
REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_STANDARDS = REPO_ROOT / "home/common/agent-skills/standards/stacks/python.md"
PYPROJECT = '[project]\nname = "fx"\n'
ADD_ONE = (Rise("PY6", 0, 1, (Violation("PY6", "pkg/m.py", 1),)),)


def require_ruff(case):
    if not TOOLS or not shutil.which("ruff", path=TOOLS):
        case.fail("run through just agent-workflow-tests, which sets AGENT_PLATFORM_TOOLS")


def cli(root, *args, env=None):
    done = subprocess.run(
        [sys.executable, "-m", "agent_tools.delivery.ruff_lint", "--repo-root", str(root), *args],
        capture_output=True, text=True, timeout=120, env={**os.environ, **(env or {})})
    return done.returncode, done.stdout, done.stderr


def fake_ruff(case, body):
    directory = tempfile.mkdtemp(prefix="fake-ruff-")
    case.addCleanup(shutil.rmtree, directory, True)
    program = Path(directory) / "ruff"
    program.write_text("#!/bin/sh\n" + body)
    program.chmod(0o755)
    return directory


def snapshot_of(root):
    sha = never_rise.resolve_commit(root, "HEAD", 60)
    return never_rise.read_snapshot(root, sha, 60)


def covered_world(tmp, source="import os\n"):
    root = repo(tmp)
    write(root, "pyproject.toml", PYPROJECT)
    write(root, "pkg/m.py", source)
    commit_all(root)
    return root


def add_a_finding_world(tmp):
    root = repo(tmp)
    write(root, "pyproject.toml", PYPROJECT)
    write(root, "pkg/m.py", "VALUE = 1\n")
    commit_all(root)
    mark_base(root)
    write(root, "pkg/m.py", "import os\nVALUE = 1\n")
    commit_all(root)
    return root


class RealRuff(unittest.TestCase):
    def setUp(self):
        require_ruff(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name


class RuffLintCommandTest(RealRuff):
    def test_an_unused_import_and_commented_out_code_print_two_python_lines(self):
        root = repo(self.tmp)
        write(root, "pyproject.toml", PYPROJECT)
        write(root, "pkg/helper.py", "import os\n# print(os.name)\nVALUE = 1\n")
        commit_all(root)

        code, stdout, _ = cli(root)

        self.assertEqual((code, stdout), (1, "PY6 pkg/helper.py:1\nPY12 pkg/helper.py:2\n"))

    def test_a_clean_tree_prints_nothing_and_exits_0(self):
        root = covered_world(self.tmp, "VALUE = 1\n")

        code, stdout, _ = cli(root)

        self.assertEqual((code, stdout), (0, ""))


class SuppressionTest(RealRuff):
    def test_a_reasoned_noqa_hides_its_finding_and_a_bare_noqa_prints(self):
        root = covered_world(self.tmp, (
            "import os  # noqa: F401 re-exported for callers\n"
            "import sys  # noqa\n"
            "import re  # noqa: F401\n"
            'TEXT = "# noqa"\n'))

        code, stdout, _ = cli(root)

        self.assertEqual((code, stdout), (1, "PY13 pkg/m.py:2\nPY13 pkg/m.py:3\n"))

    def test_a_noqa_followed_only_by_unicode_whitespace_has_no_reason(self):
        for padding in ("\u00a0", " \u00a0 ", "\u2003", "\u3000,\u00a0"):
            with self.subTest(padding=padding):
                source = f"import os  # noqa: F401{padding}\n".encode()
                self.assertEqual(
                    ruff_lint.suppressions("m.py", source), [Violation("PY13", "m.py", 1)])
        self.assertEqual(
            ruff_lint.suppressions("m.py", "import os  # noqa: F401 \u00a0kept\n".encode()), [])

    def test_a_file_wide_suppression_without_a_reason_prints(self):
        root = covered_world(self.tmp, "# ruff: noqa\nimport os\n")

        code, stdout, _ = cli(root)

        self.assertEqual((code, stdout), (1, "PY13 pkg/m.py:1\n"))

    def test_a_noqa_string_before_a_syntax_error_is_no_comment(self):
        self.assertEqual(ruff_lint.suppressions("m.py", b'TEXT = "# noqa"\nVALUE = (\n'), [])
        self.assertEqual(
            ruff_lint.suppressions("m.py", b"import os  # noqa\nVALUE = (\n"),
            [Violation("PY13", "m.py", 1)])
        root = covered_world(self.tmp, 'TEXT = "# noqa"\nVALUE = (\n')

        code, stdout, _ = cli(root)

        self.assertEqual((code, stdout), (1, "PY8 pkg/m.py:3\n"))


class RuffNeverRiseTest(RealRuff):
    def test_a_branch_adding_a_finding_rises(self):
        root = add_a_finding_world(self.tmp)

        verdict = never_rise.judge(root, "main", ruff_lint.ENFORCERS, timeout=60)

        self.assertEqual(verdict.rises, ADD_ONE)

    def test_a_branch_removing_a_finding_passes(self):
        root = repo(self.tmp)
        write(root, "pyproject.toml", PYPROJECT)
        write(root, "pkg/m.py", "import os\nVALUE = 1\n")
        commit_all(root)
        mark_base(root)
        write(root, "pkg/m.py", "VALUE = 1\n")
        commit_all(root)

        verdict = never_rise.judge(root, "main", ruff_lint.ENFORCERS, timeout=60)

        self.assertEqual(verdict.rises, ())


class MappingTest(unittest.TestCase):
    def test_every_selected_ruff_rule_maps_to_a_python_stack_rule(self):
        require_ruff(self)
        listing = subprocess.run(
            [shutil.which("ruff", path=TOOLS), "rule", "--all", "--output-format", "json"],
            capture_output=True, text=True, timeout=120, check=True).stdout
        codes = [rule["code"] for rule in json.loads(listing)]
        selected = [code for code in codes if any(
            code == entry or (code.startswith(entry) and code[len(entry)].isdigit())
            for entry in ruff_lint.SELECTION)]
        text = PYTHON_STANDARDS.read_text(encoding="utf-8")
        headings = {match["prefix"] + match["number"]
                    for _, line, _ in rule_ids.scan(text)
                    if (match := rule_ids.RULE_ID_HEADING.match(line))}

        for code in selected:
            with self.subTest(code=code):
                self.assertIn(ruff_lint.rule_of(code), headings)
        self.assertGreaterEqual(len(selected), 50)

    def test_the_longest_prefix_wins(self):
        pairs = (
            ("F722", "PY8"), ("F702", "PY10"), ("F401", "PY6"), ("E402", "PY6"),
            ("E741", "PY7"), ("E902", "PY8"), ("invalid-syntax", "PY8"), (None, "PY8"),
            ("F541", "PY9"), ("F632", "PY10"), ("F901", "PY10"), ("F811", "PY11"),
            ("ERA001", "PY12"), ("E501", None), ("FURB101", None), ("XYZ1", None))

        for code, expected in pairs:
            with self.subTest(code=code):
                self.assertEqual(ruff_lint.rule_of(code), expected)

    def test_every_rule_id_is_a_python_stack_heading(self):
        text = PYTHON_STANDARDS.read_text(encoding="utf-8")
        headings = {match["prefix"] + match["number"]
                    for _, line, _ in rule_ids.scan(text)
                    if (match := rule_ids.RULE_ID_HEADING.match(line))}

        self.assertEqual(
            set(ruff_lint.RULES),
            set(ruff_lint.RULE_OF_CODE.values()) | {ruff_lint.SUPPRESSION_RULE})
        self.assertLessEqual(set(ruff_lint.RULES), headings)


class CoverageTest(RealRuff):
    def test_a_python_file_outside_a_pyproject_directory_is_not_judged(self):
        root = repo(self.tmp)
        write(root, "sub/pyproject.toml", PYPROJECT)
        write(root, "sub/m.py", "import os\n")
        write(root, "other/m.py", "import os\n")
        commit_all(root)

        code, stdout, _ = cli(root)

        self.assertEqual((code, stdout), (1, "PY6 sub/m.py:1\n"))

    def test_an_empty_pyproject_marks_its_directory(self):
        root = repo(self.tmp)
        write(root, "pyproject.toml", "")
        write(root, "pkg/m.py", "VALUE = 1\n")
        commit_all(root)
        mark_base(root)
        write(root, "pkg/m.py", "import os\nVALUE = 1\n")
        commit_all(root)

        verdict = never_rise.judge(root, "main", ruff_lint.ENFORCERS, timeout=60)

        self.assertEqual(verdict.rises, ADD_ONE)

    def test_a_ruff_configuration_above_the_scratch_directory_changes_nothing(self):
        ignore = '[lint]\nper-file-ignores = {"*" = ["F401"]}\n'
        root = repo(self.tmp)
        write(root, "pyproject.toml", PYPROJECT + '[tool.ruff.lint]\nper-file-ignores = {"*" = ["F401"]}\n')
        write(root, "pkg/m.py", "import os\n")
        commit_all(root)
        outer = Path(tempfile.mkdtemp(prefix="outer-"))
        self.addCleanup(shutil.rmtree, outer, True)
        (outer / "ruff.toml").write_text(ignore)

        code, stdout, _ = cli(root, env={"TMPDIR": str(outer)})

        self.assertEqual((code, stdout), (1, "PY6 pkg/m.py:1\n"))

    def test_python_3_13_syntax_is_not_a_parse_violation(self):
        root = covered_world(
            self.tmp, "def first[T = int](items: list[T]) -> T:\n    return items[0]\n")

        code, stdout, _ = cli(root)

        self.assertEqual((code, stdout), (0, ""))


class FailClosedTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name

    def failure(self, snapshot):
        with self.assertRaises(EnforcerFailed) as caught:
            ruff_lint.findings(snapshot)
        return caught.exception.reason

    def test_an_unmapped_ruff_code_fails_closed(self):
        fake = fake_ruff(
            self,
            'printf \'[{"code":"XYZ1","filename":"%s/pkg/m.py","location":{"row":1,"column":1}}]\''
            ' "$(pwd -P)"\n')
        root = covered_world(self.tmp)

        code, _, stderr = cli(root, env={"AGENT_PLATFORM_TOOLS": fake})

        self.assertEqual((code, stderr), (2, "ruff-lint: unmapped_code\n"))

    def test_a_ruff_that_exits_non_zero_fails_closed(self):
        fake = fake_ruff(self, "exit 2\n")
        root = covered_world(self.tmp)

        code, _, stderr = cli(root, env={"AGENT_PLATFORM_TOOLS": fake})

        self.assertEqual((code, stderr), (2, "ruff-lint: ruff_failed\n"))

    def test_a_stalled_ruff_is_cut_off_by_the_command_timeout(self):
        fake = fake_ruff(self, "while :; do :; done\n")
        root = covered_world(self.tmp)

        started = time.monotonic()
        code, _, stderr = cli(root, "--timeout", "2", env={"AGENT_PLATFORM_TOOLS": fake})

        self.assertEqual((code, stderr), (2, "ruff-lint: ruff_failed\n"))
        self.assertLess(time.monotonic() - started, 60)
        for value in ("0", "nan"):
            with self.subTest(timeout=value):
                code, _, stderr = cli(root, "--timeout", value)
                self.assertEqual(code, 2)
                self.assertTrue(stderr.startswith("ruff-lint: --timeout"), stderr)

    def test_no_pinned_ruff_fails_closed_only_when_a_file_is_covered(self):
        root = covered_world(self.tmp)
        snapshot = snapshot_of(root)
        empty = Path(self.tmp) / "empty"
        empty.mkdir()
        plain = Path(self.tmp) / "plain"
        plain.mkdir()
        (plain / "ruff").write_text("#!/bin/sh\n")
        (plain / "ruff").chmod(0o644)
        for value in (None, "relative/bin", str(empty), str(plain)):
            with self.subTest(tools=value), mock.patch.dict(os.environ):
                os.environ.pop("AGENT_PLATFORM_TOOLS", None)
                if value is not None:
                    os.environ["AGENT_PLATFORM_TOOLS"] = value
                self.assertEqual(self.failure(snapshot), "ruff_unavailable")
        (Path(self.tmp) / "bare").mkdir()
        bare = repo(Path(self.tmp) / "bare")
        write(bare, "m.py", "import os\n")
        commit_all(bare)
        with mock.patch.dict(os.environ):
            os.environ.pop("AGENT_PLATFORM_TOOLS", None)
            self.assertEqual(ruff_lint.findings(snapshot_of(bare)), ())

    def test_a_path_leaving_the_scratch_directory_is_refused(self):
        require_ruff(self)
        root = repo(self.tmp)
        snapshot = Snapshot(
            "b" * 40, {"pyproject.toml": 1, "../x.py": 1},
            {"pyproject.toml": "0" * 40, "../x.py": "0" * 40}, root, 60)

        self.assertEqual(self.failure(snapshot), "unsafe_path")

    def test_two_paths_one_scratch_file_fail_closed(self):
        require_ruff(self)
        worlds = {"file": ("pkg/a.py",), "directory": ("pkg/A/x.py", "pkg/a/y.py")}
        for name, staged in worlds.items():
            with self.subTest(world=name):
                (Path(self.tmp) / name).mkdir()
                root = repo(Path(self.tmp) / name)
                write(root, "pyproject.toml", PYPROJECT)
                write(root, "pkg/A.py", "VALUE = 1\n")
                git(root, "add", "pyproject.toml", "pkg/A.py")
                oid = git(root, "rev-parse", ":pkg/A.py").strip()
                for path in staged:
                    git(root, "update-index", "--add", "--cacheinfo", f"100644,{oid},{path}")
                git(root, "commit", "-q", "-m", "pair")

                self.assertEqual(self.failure(snapshot_of(root)), "path_collision")

    def test_a_scratch_directory_inside_the_repository_is_refused(self):
        require_ruff(self)
        root = covered_world(self.tmp)
        inside = root / "inside"
        inside.mkdir()

        with mock.patch.object(ruff_lint.tempfile, "tempdir", str(inside)):
            reason = self.failure(snapshot_of(root))

        self.assertEqual(reason, "scratch_inside_repository")
        self.assertEqual(list(inside.iterdir()), [])

    def test_discovering_the_scratch_directory_writes_nothing_inside_the_repository(self):
        require_ruff(self)
        root = covered_world(self.tmp)
        inside = root / "inside"
        inside.mkdir()

        with mock.patch.object(ruff_lint.tempfile, "tempdir", None), \
                mock.patch.dict(os.environ, {"TMPDIR": str(inside)}):
            reason = self.failure(snapshot_of(root))

        self.assertEqual(reason, "scratch_inside_repository")
        self.assertEqual(list(inside.iterdir()), [])

    def test_a_failing_scratch_discovery_fails_closed(self):
        require_ruff(self)
        root = covered_world(self.tmp)

        with mock.patch.object(ruff_lint.tempfile, "gettempdir", side_effect=OSError("no")):
            reason = self.failure(snapshot_of(root))

        self.assertEqual(reason, "scratch_unwritable")

    def test_an_unwritable_scratch_parent_fails_closed(self):
        require_ruff(self)
        root = covered_world(self.tmp)
        locked = Path(tempfile.mkdtemp(prefix="locked-"))
        locked.chmod(0o500)
        self.addCleanup(shutil.rmtree, locked, True)
        self.addCleanup(locked.chmod, stat.S_IRWXU)

        with mock.patch.object(ruff_lint.tempfile, "tempdir", str(locked)):
            reason = self.failure(snapshot_of(root))

        self.assertEqual(reason, "scratch_unwritable")


class PassTest(RealRuff):
    def test_ruff_runs_once_per_revision(self):
        root = add_a_finding_world(self.tmp)

        with mock.patch.object(ruff_lint.subprocess, "run", wraps=subprocess.run) as spy:
            never_rise.judge(root, "main", ruff_lint.ENFORCERS, timeout=60)

        checks = [call for call in spy.call_args_list
                  if len(call.args[0]) > 1 and call.args[0][1] == "check"]
        self.assertEqual(len(checks), 2)
        for call in checks:
            self.assertEqual(call.args[0][0], "ruff")
            self.assertEqual(call.kwargs["env"], {"PATH": TOOLS})

    def test_ruff_receives_at_most_200_paths_per_run(self):
        root = repo(self.tmp)
        write(root, "pyproject.toml", PYPROJECT)
        for number in range(450):
            write(root, f"pkg/m{number}.py", "import os\n")
        commit_all(root)

        with mock.patch.object(ruff_lint.subprocess, "run", wraps=subprocess.run) as spy:
            result = ruff_lint.findings(snapshot_of(root))

        checks = [call.args[0] for call in spy.call_args_list
                  if len(call.args[0]) > 1 and call.args[0][1] == "check"]
        self.assertGreaterEqual(len(checks), 3)
        for argv in checks:
            self.assertLessEqual(len(argv) - argv.index("--") - 1, ruff_lint.BATCH)
        self.assertEqual(len(result), 450)

    def test_judging_writes_nothing_to_the_repository(self):
        root = add_a_finding_world(self.tmp)
        before = recordings(root)

        never_rise.judge(root, "main", ruff_lint.ENFORCERS, timeout=60)

        self.assertEqual(recordings(root), before)


if __name__ == "__main__":
    unittest.main()
