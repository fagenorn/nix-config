"""Retained bundle derivation and its command (issue 249; RP4, RP5, RP6, RP9, RP16, RP17)."""
import hashlib, io, json, os, shutil, subprocess, sys, tempfile, unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_tools import derive_review_feasibility_fixtures as command
from agent_tools.canonical import telemetry_digest
from agent_tools.review_budget import describe
from agent_tools.review_derivation import DerivationError, DeriveInputs, derive_bundle
from agent_tools.review_forecast import canonical_bytes
from agent_tools.review_issue100 import Issue100Error
from agent_tools.review_task7 import EstimateError
from agent_tools.review_witness import ANCHOR_NAME, PAYLOAD_NAMES, WitnessError

from .retained_review_test_support import commit_files, git, retained_fixture, snapshot, source_budget_env, tool_fixture

OPTIONS = ("--issue-121-repo", "--issue-100-repo", "--archive-dir", "--tool-repo", "--tool-commit", "--output-dir")
INVALID = "derive-review-feasibility-fixtures: invalid: "
CODES = ("invalid_inputs", "output_exists", "output_aliases_input", "member_oversize")


def entry(path):
    """What is at `path`, a final symlink not followed: `None`, a link target, a listing or the file's bytes."""
    if path.is_symlink():
        return os.readlink(path)
    if path.is_dir():
        return sorted(os.listdir(path))
    return path.read_bytes() if path.exists() else None


class DerivationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        repo121, repo100, archive, cls.pins = retained_fixture(cls.tmp)
        tool_repo, tool_commit = tool_fixture(cls.tmp)
        cls.inputs = DeriveInputs(repo121, repo100, archive, tool_repo, tool_commit, cls.tmp / "unused")
        cls.env = source_budget_env(cls.tmp)
        with patch.dict(os.environ, cls.env, clear=True):
            cls.authority = describe("review-package")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def derive(self, out, inputs=None, **changed):
        pins = dict(zip(("task7_pins", "issue121_pins", "issue100_pins"), self.pins), **changed)
        return derive_bundle(replace(inputs or self.inputs, output_dir=out), authority=self.authority, **pins)

    def state(self):
        repos = (self.inputs.issue_121_repo, self.inputs.issue_100_repo, self.inputs.tool_repo)
        archive = {p.relative_to(self.inputs.archive_dir): p.read_bytes()
                   for p in self.inputs.archive_dir.rglob("*") if p.is_file()}
        return tuple(snapshot(repo) for repo in repos), archive

    def leftovers(self):
        return sorted(p.name for p in self.tmp.iterdir() if p.name.startswith(".derive-"))

    def refused(self, error, code, out, inputs=None, **changed):
        """`derive_bundle` raises `error` with `code` (`None` for an error without one), leaving no scratch,
        whatever was at `out` (nothing, unless the case put it there) and the class inputs unchanged."""
        before, there = self.state(), entry(out)
        with self.assertRaises(error) as caught:
            self.derive(out, inputs, **changed)
        self.assertEqual(getattr(caught.exception, "code", None), code)
        self.assertEqual((self.state(), self.leftovers(), entry(out)), (before, [], there))

    def argv(self, out):
        i = self.inputs
        values = (i.issue_121_repo, i.issue_100_repo, i.archive_dir, i.tool_repo, i.tool_commit, out)
        return [word for option, value in zip(OPTIONS, values) for word in (option, str(value))]

    def run_command(self, argv, **env):
        done = subprocess.run([sys.executable, "-m", "agent_tools.derive_review_feasibility_fixtures", *argv],
                              env={**self.env, **env}, capture_output=True)
        return done.returncode, done.stdout, done.stderr

    def command_refused(self, code, out, cases, **env):
        """Each command line exits 2 with the one `code` line, and together they leave no scratch, whatever
        was at `out` and the class inputs unchanged."""
        before, there = self.state(), entry(out)
        for argv in cases:
            with self.subTest(argv=[word for word in argv if word.startswith("-")]):
                self.assertEqual(self.run_command(argv, **env), (2, b"", (INVALID + code + "\n").encode()))
        self.assertEqual((self.state(), self.leftovers(), entry(out)), (before, [], there))

    def main(self, out):
        """`(status, stdout, stderr)` of the command in process. It passes only its real pins, so its three
        pin names carry the fixture's here (RP17)."""
        names = ("TASK7_PINS", "ISSUE_121_PINS", "ISSUE_100_PINS")
        stdout, stderr = io.TextIOWrapper(io.BytesIO()), io.StringIO()
        with patch.multiple(command, **dict(zip(names, self.pins))), patch("sys.stdout", stdout), \
                patch("sys.stderr", stderr), patch.dict(os.environ, self.env, clear=True):
            status = command.main(self.argv(out))
        stdout.flush()
        return status, stdout.buffer.getvalue(), stderr.getvalue()

    def shared(self):
        """`(directory, summary)` of one derivation that the cases which only read a bundle share."""
        cls = type(self)
        if not hasattr(cls, "bundle"):
            cls.bundle = self.tmp / "shared", self.derive(self.tmp / "shared")
        return cls.bundle

    def test_two_derivations_are_byte_identical_and_inputs_unchanged(self):
        before = self.state()
        a, b = self.tmp / "a", self.tmp / "b"
        summary = self.derive(a)
        self.assertEqual(self.main(b), (0, canonical_bytes(summary), ""))  # the command's success mapping
        files = {p.name: p.read_bytes() for p in a.iterdir()}
        self.assertEqual(files, {p.name: p.read_bytes() for p in b.iterdir()})
        self.assertEqual(set(files), {ANCHOR_NAME, *PAYLOAD_NAMES})
        self.assertEqual((self.state(), self.leftovers()), (before, []))

    def test_failing_pin_leaves_no_output_no_scratch_and_unchanged_inputs(self):
        before = self.state()
        bad = replace(self.pins[2], producer_sha256="0" * 64)
        with self.assertRaises(Issue100Error) as caught:
            self.derive(self.tmp / "c", issue100_pins=bad)
        self.assertEqual(caught.exception.code, "archive_digest_mismatch")
        self.assertFalse((self.tmp / "c").exists())
        self.assertEqual((self.state(), self.leftovers()), (before, []))

    def test_error_codes_are_the_closed_four(self):
        self.assertEqual([DerivationError(code).code for code in CODES], list(CODES))
        with self.assertRaises(ValueError):
            DerivationError("io_error")

    def test_summary_names_the_written_bundle(self):
        out, summary = self.shared()
        files = {p.name: p.read_bytes() for p in out.iterdir()}
        members = [{"path": name, "bytes": len(files[name]), "raw_sha256": hashlib.sha256(files[name]).hexdigest()}
                   for name in ("derivation-anchor.json", "derivation-witness.json", "issue-100-derived.json",
                                "issue-121.json", "task7-estimate.json")]
        self.assertEqual(summary, {"anchor_sha256": telemetry_digest(json.loads(files[ANCHOR_NAME])),
                                   "members": members})
        for name, data in files.items():
            self.assertEqual(data, canonical_bytes(json.loads(data)), name)

    def test_existing_or_dangling_output_is_output_exists(self):
        directory, file, link = (self.tmp / name for name in ("taken-dir", "taken-file", "taken-link"))
        directory.mkdir()
        (directory / "keep").write_bytes(b"keep\n")
        file.write_bytes(b"file\n")
        link.symlink_to(self.tmp / "nowhere")
        for out in (directory, file, link, self.tmp / "missing-parent" / "out"):
            with self.subTest(out=out.name):
                self.refused(DerivationError, "output_exists", out)
        self.assertEqual((entry(directory / "keep"), entry(self.tmp / "nowhere"), entry(self.tmp / "missing-parent")),
                         (b"keep\n", None, None))

    def test_aliasing_output_is_refused(self):
        i = self.inputs
        # A linked worktree keeps its objects in the repository it came from: only the common Git directory
        # names that repository once the worktree is the tool input.
        origin, worktree = Path(shutil.copytree(i.tool_repo, self.tmp / "tool-origin")), self.tmp / "tool-worktree"
        git(origin, "worktree", "add", "-q", "--detach", str(worktree))
        cases = ((i.issue_121_repo / "out", i), (i.archive_dir / "out", i), (i.issue_100_repo / ".git" / "out", i),
                 (origin / ".git" / "out", replace(i, tool_repo=worktree)))
        for out, inputs in cases:
            with self.subTest(out=out.relative_to(self.tmp)):
                self.refused(DerivationError, "output_aliases_input", out, inputs)

    def test_invalid_inputs(self):
        i = self.inputs
        plain = self.tmp / "plain"
        plain.mkdir()
        cases = {"39-hex commit": replace(i, tool_commit=i.tool_commit[:39]),
                 "uppercase commit": replace(i, tool_commit="A" + i.tool_commit[1:]),
                 "file as archive": replace(i, archive_dir=i.archive_dir / "producer.raw"),
                 "plain directory as tool repo": replace(i, tool_repo=plain)}
        for n, (name, inputs) in enumerate(cases.items()):
            with self.subTest(name):
                self.refused(DerivationError, "invalid_inputs", self.tmp / f"invalid-{n}", inputs)

    def test_mismatched_running_closure_is_refused(self):
        path = "python/agent_tools/canonical.py"
        edited = Path(shutil.copytree(self.inputs.tool_repo, self.tmp / "tool-edited"))
        commit = commit_files(edited, {path: (edited / path).read_bytes()[:-1] + b" "}, "one byte")
        self.refused(WitnessError, "tool_closure", self.tmp / "stale",
                     replace(self.inputs, tool_repo=edited, tool_commit=commit))

    def test_estimate_pin_fault_is_fatal(self):
        bad = replace(self.pins[0], prerequisite_tree="0" * 40)
        self.refused(EstimateError, "inventory_mismatch", self.tmp / "unestimated", task7_pins=bad)

    def test_oversized_member_or_anchor_is_refused(self):
        for bound in ("MEMBER_MAX_BYTES", "ANCHOR_MAX_BYTES"):  # the anchor is a bundle member too
            with self.subTest(bound), patch(f"agent_tools.review_derivation.{bound}", 64):
                self.refused(DerivationError, "member_oversize", self.tmp / "oversized")

    def test_publication_failure_removes_scratch(self):
        out = self.tmp / "unpublished"
        with patch("agent_tools.review_derivation.os.rename", side_effect=OSError("rename")) as rename:
            self.refused(OSError, None, out)
            before = self.state()
            self.assertEqual(self.main(out), (2, b"", INVALID + "io_error\n"))
        self.assertEqual((self.state(), self.leftovers(), entry(out)), (before, [], None))
        # Both calls reached publication: each renamed its own scratch directory, beside the output, onto it.
        self.assertEqual([(Path(call.args[0]).parent, call.args[0] != call.args[1], call.args[1])
                          for call in rename.call_args_list], [(self.tmp, True, out)] * 2)

    def test_outputs_hold_no_scratch_or_home_path(self):
        files = {p.name: p.read_bytes() for p in self.shared()[0].iterdir()}
        self.assertEqual(len(files), 5)
        for name, data in files.items():
            for value in (str(self.tmp), os.environ["HOME"], os.getcwd()):
                self.assertNotIn(value.encode(), data, (name, value))

    def test_command_line_that_is_not_the_six_options_is_usage(self):
        out = self.tmp / "usage"
        argv = self.argv(out)
        self.command_refused("usage", out, [argv[:n] + argv[n + 2:] for n in range(0, 12, 2)] + [
            argv + ["--pin", "x"], argv + ["--help"], argv + ["-h"], argv[:10] + ["--out", str(out)]])
        self.assertIsNone(entry(out))

    def test_command_refuses_an_existing_output_dir(self):
        out = self.tmp / "existing"
        out.mkdir()
        self.command_refused("output_exists", out, [self.argv(out)])
        self.assertEqual(entry(out), [])

    def test_command_without_a_budget_helper_is_budget_unavailable(self):
        out, empty = self.tmp / "unbudgeted", self.tmp / "empty-path"
        empty.mkdir()
        self.command_refused("budget_unavailable", out, [self.argv(out)], PATH=str(empty))
        self.assertIsNone(entry(out))
