"""The skipped-test rule of `agent_tools.delivery.skipped_test_lint`.

Measures the rule against source text and real git worlds: every framework's
skip, disable, focus and pending form is one violation at its test's line, a
skip on a suite counts each test inside it, a marker no test carries counts
once, a marker in a string, a comment or a non-test file counts nothing, a
running test's lookalike counts nothing, and the project's count may not rise
against the merge base whichever file holds the skip.

The suite holds `standard:B23` by judging the enforcer
`agent_tools.delivery.skipped_test_lint` on real git worlds, so the rule index
lists this enforcer.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery import never_rise, rule_ids, skipped_test_lint
from agent_tools.delivery.dotnet_solution import SOLUTION_ROOT
from agent_tools.delivery.never_rise import Rise, Snapshot, Violation

from .never_rise_world import commit_all, fixture_env, mark_base, repo, write

TIER = "integration"

REPO_ROOT = Path(__file__).resolve().parents[1]
BAR = REPO_ROOT / "home/common/agent-skills/standards/the-bar.md"
COMMAND_TABLE = REPO_ROOT / "lib/agent-tools.nix"


def ok(text):
    return text, False


def bad(text):
    return text, True


def source(pairs):
    """The file text of `(line, expected)` pairs and the 1-based lines expected."""
    text = "\n".join(line for line, _ in pairs) + "\n"
    return text, [n for n, (_, expected) in enumerate(pairs, 1) if expected]


def snapshot(files):
    blobs = {path: text.encode("utf-8") for path, text in files.items()}
    return Snapshot("fixture", {path: text.count("\n") for path, text in files.items()},
                    contents=blobs)


def found(files):
    return [(v.path, v.line) for v in skipped_test_lint.find(snapshot(files))]


UNIT = [
    ok("import unittest"), ok("from unittest import skip"), ok(""),
    ok("class UnitTest(unittest.TestCase):"),
    ok('    @unittest.skip("x")'), bad("    def test_skip(self):"), ok("        self.assertEqual(1, 11)"),
    ok('    @unittest.skipIf(True, "x")'), bad("    def test_skip_if(self):"),
    ok("        self.assertEqual(1, 12)"),
    ok('    @unittest.skipUnless(False, "x")'), bad("    def test_skip_unless(self):"),
    ok("        self.assertEqual(1, 13)"),
    ok('    @skip("x")'), bad("    def test_bare_skip(self):"), ok("        self.assertEqual(1, 14)"),
    bad("    def test_skip_test(self):"), ok('        self.skipTest("x")'),
    ok("        self.assertEqual(1, 15)"),
    bad("    def test_raise(self):"), ok('        raise unittest.SkipTest("x")'),
    bad("    def test_twice(self):"), ok('        self.skipTest("a")'), ok('        self.skipTest("b")'),
    ok("    def test_plain(self):"), ok("        self.assertEqual(1, 16)"),
]
PYTEST = [
    ok("import pytest"), ok(""),
    ok('@pytest.mark.skip(reason="x")'), bad("def test_mark_skip():"), ok("    assert 21"),
    ok('@pytest.mark.skipif(True, reason="x")'), bad("def test_mark_skipif():"), ok("    assert 22"),
    bad("def test_call_skip():"), ok('    pytest.skip("x")'), ok("    assert 23"),
    bad("def test_import_or_skip():"), ok('    pytest.importorskip("x")'), ok("    assert 24"),
    ok("def test_plain():"), ok("    assert 25"),
]
MARKED = [
    ok("import pytest"), ok("pytestmark = pytest.mark.skip"), ok(""),
    bad("def test_one():"), ok("    assert 31"), bad("def test_two():"), ok("    assert 32"),
]
CSHARP = [
    ok("public class UnitTests {"),
    ok("#region Skipped"), ok('[Fact(Skip = "x")]'), bad("public void FactSkip() { Run(41); }"),
    ok("#endregion"),
    ok('[Theory(Skip = "x")]'), ok("[InlineData(1)]"), bad("public void TheorySkip(int n) { Run(42); }"),
    ok("[Fact]"), bad("public void FactAssertSkip() { Assert.Skip(\"x\"); Run(43); }"),
    ok('[Test, Ignore("x")]'), bad("public void NunitIgnore() { Run(44); }"),
    ok('[Test, NUnit.Framework.Ignore("x")]'), bad("public void NunitQualified() { Run(45); }"),
    ok("[Test, Explicit]"), bad("public void NunitExplicit() { Run(46); }"),
    ok("[Test]"), bad("public void NunitAssertIgnore() { Assert.Ignore(\"x\"); Run(47); }"),
    ok("[TestMethod, Ignore]"), bad("public void MsTestIgnore() { Run(48); }"),
    ok("[Fact]"), ok("public void FactPlain() { Run(49); }"),
    ok("[Paging(Skip = 10)]"), ok("public void List() { }"),
    ok("[Ignore]"), ok("public int Cache { get; set; }"),
    ok("[Theory]"), ok('[ClassData<SkippedRows>(Skip = "x")]'),
    bad("public void GenericClassRowSkipped(int n) { Run(61); }"),
    ok("[Theory]"), ok("[ClassData<Rows<int>>(Explicit = true)]"),
    bad("public void NestedGenericRowExplicit(int n) { Run(62); }"),
    ok("[Theory]"), ok("[ClassData<Rows<int>>(Explicit = false)]"),
    ok("public void NestedGenericRowRuns(int n) { Run(63); }"),
    ok("[Fact]"), ok("[Paging<Page>(Skip = 10)]"), ok("public void GenericOther() { Run(64); }"),
    ok("}"),
]
WEB = [
    ok("it('a', () => { render(<p>hi</p>) })"),
    bad("it.skip('b', () => { render(<p>x</p>) })"),
    bad("test.skip("), ok("  'c', () => { run(51) })"),
    ok("describe.skip('s', () => {"), bad("  it('inner', () => { run(52) })"), ok("})"),
    bad("xit('d', () => { run(53) })"),
    ok("xdescribe('xs', () => {"), bad("  it('inner2', () => { run(54) })"), ok("})"),
    bad("test.todo('t')"), bad("it('p')"),
    bad("it.only('o', () => { run(55) })"), bad("fit('f', () => { run(56) })"),
    bad("test.fixme('g', () => { run(57) })"),
    bad("it('q', function () { this.skip() })"), bad("test('r', (t) => { t.skip() })"),
    bad('test("n", { skip: true }, () => {})'), bad('it("o2", { todo: "x" }, () => {})'),
]


def lines_of(path, pairs):
    return [f"B23 {path}:{n}" for n in source(pairs)[1]]


class SkippedTestLintTest(unittest.TestCase):
    def run_command(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.skipped_test_lint", *arguments],
            capture_output=True, text=True, timeout=60, env=fixture_env())

    def test_each_frameworks_skipped_test_prints_one_line_with_rule_path_and_line(self):
        files = {
            "tests/test_unit.py": UNIT, "tests/test_pytest.py": PYTEST,
            "tests/test_marked.py": MARKED, "src/Tests/UnitTests.cs": CSHARP,
            "web/a.test.tsx": WEB}
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            for path, pairs in files.items():
                write(root, path, source(pairs)[0])
            commit_all(root)
            done = self.run_command("--repo-root", str(root))
        expected = "".join(
            f"{line}\n" for path in sorted(files) for line in lines_of(path, files[path]))
        self.assertEqual((done.returncode, done.stdout), (1, expected))

    def test_a_planted_xunit_file_under_the_solution_root_counts_each_skip_and_zero_once_fixed(self):
        fixtures = Path(__file__).resolve().parents[1] / "tests/fixtures/dotnet-lint"
        path = f"{SOLUTION_ROOT}/Planted.Tests/SkippedTests.cs"
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, path, (fixtures / "SkippedTests.cs.fixture").read_text("utf-8"))
            commit_all(root)
            planted = self.run_command("--repo-root", str(root))
            write(root, path, (fixtures / "SkippedTestsFixed.cs.fixture").read_text("utf-8"))
            commit_all(root)
            fixed = self.run_command("--repo-root", str(root))
        expected = "".join(f"B23 {path}:{n}\n" for n in (8, 12, 15, 19, 23, 27, 31, 35, 39))
        self.assertEqual((planted.returncode, planted.stdout), (1, expected))
        self.assertEqual((fixed.returncode, fixed.stdout), (0, ""))

    def test_a_skipped_suite_counts_each_test_inside_it_and_a_test_counts_once(self):
        def klass(count):
            pairs = [ok("import unittest"), ok('@unittest.skipUnless(False, "x")'),
                     ok("class A(unittest.TestCase):")]
            for n in range(count):
                pairs += [bad(f"    def test_{n}(self):"), ok(f"        self.assertEqual({n}, 6{n})")]
            return pairs

        suite = [ok("describe.skip('s', () => {"), bad("  it('a', () => { run(71) })"),
                 bad("  it('b', () => { run(72) })"), ok("})")]
        fixture = [ok('[TestFixture, Ignore("x")]'), ok("public class T {"),
                   ok("[Test]"), bad("public void A() { Run(73); }"),
                   ok("[Test]"), bad("public void B() { Run(74); }"), ok("}")]
        twice = [ok("import unittest"), ok("class A(unittest.TestCase):"),
                 bad("    def test_a(self):"), ok('        self.skipTest("a")'),
                 ok('        self.skipTest("b")')]

        self.assertEqual(found({"tests/test_a.py": source(klass(3))[0]}),
                         [("tests/test_a.py", n) for n in source(klass(3))[1]])
        self.assertEqual(len(found({"tests/test_a.py": source(klass(4))[0]})), 4)
        self.assertEqual(found({"web/a.test.js": source(suite)[0]}),
                         [("web/a.test.js", n) for n in source(suite)[1]])
        self.assertEqual(found({"src/T.cs": source(fixture)[0]}),
                         [("src/T.cs", n) for n in source(fixture)[1]])
        self.assertEqual(found({"tests/test_a.py": source(twice)[0]}),
                         [("tests/test_a.py", n) for n in source(twice)[1]])
        self.assertEqual(len(source(twice)[1]), 1)

    def test_a_marker_that_marks_no_test_counts_once_at_its_line(self):
        setup = [ok("import unittest"), ok("class A(unittest.TestCase):"),
                 ok("    def setUp(self):"), bad('        self.skipTest("x")'),
                 ok("    def test_a(self):"), ok("        self.assertEqual(1, 81)"),
                 ok("    def test_b(self):"), ok("        self.assertEqual(1, 82)")]
        module = [ok("import pytest"), bad('pytest.importorskip("x")'),
                  ok("def test_a():"), ok("    assert 83"), ok("def test_b():"),
                  ok("    assert 84")]
        hook = [ok("describe('d', () => {"), ok("  before(function () {"),
                bad("    this.skip()"), ok("  })"), ok("  it('a', () => { run(85) })"),
                ok("  it('b', () => { run(86) })"), ok("})")]
        helper = [ok("import pytest"), ok("@pytest.mark.skip"), ok("def helper():"),
                  ok("    return 87")]

        self.assertEqual(found({"tests/test_a.py": source(setup)[0]}),
                         [("tests/test_a.py", n) for n in source(setup)[1]])
        self.assertEqual(found({"tests/test_a.py": source(module)[0]}),
                         [("tests/test_a.py", n) for n in source(module)[1]])
        self.assertEqual(found({"web/a.test.js": source(hook)[0]}),
                         [("web/a.test.js", n) for n in source(hook)[1]])
        self.assertEqual(found({"tests/test_a.py": source(helper)[0]}), [("tests/test_a.py", 2)])

    def test_marker_text_in_strings_comments_and_non_test_files_is_not_counted(self):
        files = {
            "tests/test_a.py": ('x = "@unittest.skip(\'x\')"\n'
                                '# self.skipTest("x")\n'
                                "def test_a():\n    assert 91\n"),
            "web/a.test.js": "// it.skip(\n/* xit( */\nit('a', () => { run(92) })\n",
            "src/A.cs": "/* [Ignore] */\npublic class A { }\n",
            "src/helper.py": 'def helper(self):\n    self.skipTest("x")\n',
            "src/app.ts": 'it.skip("a", () => {})\n'}

        self.assertEqual(found(files), [])

    def test_running_markers_and_lookalikes_are_not_counted(self):
        files = {
            "tests/test_a.py": "\n".join([
                "import unittest, pytest", "skip = 1", "class A(unittest.TestCase):",
                "    @unittest.expectedFailure", "    def test_a(self):",
                "        self.assertEqual(1, 101)", "    @pytest.mark.xfail",
                "    def test_b(self):", "        self.assertEqual(1, 102)", ""]),
            "web/a.test.js": "\n".join([
                "const page = query.skip(10)", 'test("a", { skip: false }, () => { run(103) })',
                "const rows = repo.findMany({ skip: 10 })", ""]),
            "src/T.cs": "\n".join([
                "public class T {", "[Fact]", "public void A() {",
                "var q = new Query { Take = 1, Skip = 2 };", "}",
                "[Paging(Skip = 10)]", "public void List() { }", "[Ignore]",
                "public int Cache { get; set; }", "}", ""])}

        self.assertEqual(found(files), [])

    def test_the_command_exits_0_with_no_output_on_a_tree_with_no_skipped_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "tests/test_a.py", "def test_a():\n    assert 111\n")
            commit_all(root)
            done = self.run_command("--repo-root", str(root))
        self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_the_rule_id_is_a_rule_of_the_bar_and_cited_by_its_enforcer(self):
        module = Path(skipped_test_lint.__file__).read_text(encoding="utf-8")

        self.assertIn(skipped_test_lint.RULE_ID, rule_ids.sections(BAR.read_text(encoding="utf-8")))
        self.assertIn(skipped_test_lint.RULE_ID, {
            c.token for c in rule_ids.citations(module) if c.well_formed})

    def test_the_command_is_a_row_of_the_command_table(self):
        self.assertIn('"skipped-test-lint" = "delivery.skipped_test_lint";',
                      COMMAND_TABLE.read_text(encoding="utf-8"))


SKIPPED_A = [ok("import unittest"), ok("class A(unittest.TestCase):"), ok('    @unittest.skip("x")'),
             bad("    def test_a(self):"), ok("        self.assertEqual(1, 121)")]


class SkippedNeverRiseTest(unittest.TestCase):
    def judge(self, root):
        return never_rise.judge(root, "main", [skipped_test_lint.ENFORCER], timeout=60).rises

    def base(self, root, files):
        for path, text in files.items():
            write(root, path, text)
        commit_all(root)
        mark_base(root)

    def test_one_more_skipped_test_than_the_merge_base_rises(self):
        added = [ok("import unittest"), ok("class B(unittest.TestCase):"),
                 ok('    @unittest.skip("y")'), bad("    def test_b(self):"),
                 ok("        self.assertEqual(1, 122)")]
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            self.base(root, {"tests/test_a.py": source(SKIPPED_A)[0]})
            write(root, "tests/test_b.py", source(added)[0])
            commit_all(root)
            self.assertEqual(self.judge(root), (
                Rise("B23", 1, 2, (Violation("B23", "tests/test_b.py", source(added)[1][0]),)),))

    def test_an_unchanged_branch_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            self.base(root, {"tests/test_a.py": source(SKIPPED_A)[0], "README": "a\n"})
            write(root, "README", "b\n")
            commit_all(root)
            self.assertEqual(self.judge(root), ())

    def test_a_test_added_under_a_skipped_class_rises(self):
        base = [ok("import unittest"), ok('@unittest.skip("x")'),
                ok("class A(unittest.TestCase):"), bad("    def test_a(self):"),
                ok("        self.assertEqual(1, 121)")]
        grown = base + [bad("    def test_c(self):"), ok("        self.assertEqual(1, 123)")]
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            self.base(root, {"tests/test_a.py": source(base)[0]})
            write(root, "tests/test_a.py", source(grown)[0])
            commit_all(root)
            self.assertEqual(self.judge(root), (
                Rise("B23", 1, 2, (Violation("B23", "tests/test_a.py", source(grown)[1][1]),)),))

    def test_a_skip_moved_to_another_file_keeps_the_count(self):
        both = [ok("import unittest"), ok("class A(unittest.TestCase):"), ok('    @unittest.skip("x")'),
                bad("    def test_a(self):"), ok("        self.assertEqual(1, 124)"),
                ok("    def test_p(self):"), ok("        self.assertEqual(1, 125)")]
        plain = [pair for pair in both if pair[0] != '    @unittest.skip("x")']
        moved = [ok("import unittest"), ok("class C(unittest.TestCase):"),
                 ok('    @unittest.skip("x")'), bad("    def test_c(self):"),
                 ok("        self.assertEqual(1, 126)")]
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            self.base(root, {"tests/test_a.py": source(both)[0]})
            write(root, "tests/test_a.py", source(plain)[0])
            write(root, "tests/test_c.py", source(moved)[0])
            commit_all(root)
            self.assertEqual(self.judge(root), ())


class SkipRecognitionTest(unittest.TestCase):
    def test_a_test_given_a_named_function_is_a_test_with_a_body_and_skips_only_with_a_marker(self):
        self.assertEqual(found({"web/a.test.js": "it('works', run)\nit('slow', run, 1000)\n"}), [])
        self.assertEqual(found({"web/a.test.js": "it.skip('works', run)\n"}),
                         [("web/a.test.js", 1)])
        self.assertEqual(found({"web/a.test.js": "it('p')\nit('q', { timeout: 1 })\n"}),
                         [("web/a.test.js", 1), ("web/a.test.js", 2)])

    def test_a_suite_level_or_file_level_playwright_skip_counts_each_test_it_disables(self):
        suite = [ok("test.describe('suite', () => {"), ok("  test.skip(true, 'maintenance');"),
                 bad("  test('a', async () => { run(1); });"),
                 bad("  test('b', async () => { run(2); });"), ok("});"),
                 ok("test('c', async () => { run(3); });")]
        file_level = [ok("test.skip(true, 'maintenance');"),
                      bad("test('a', async () => { run(1); });"),
                      bad("test('b', async () => { run(2); });")]
        inside = [ok("test('a', async () => { test.skip(true, 'x'); });")]
        empty = [ok("test.describe('suite', () => {"), bad("  test.skip(true, 'x');"), ok("});")]

        for name, pairs in (("suite", suite), ("file", file_level), ("empty", empty)):
            path = f"web/{name}.spec.ts"
            self.assertEqual(found({path: source(pairs)[0]}),
                             [(path, n) for n in source(pairs)[1]], name)
        self.assertEqual(found({"web/inside.spec.ts": source(inside)[0]}),
                         [("web/inside.spec.ts", 1)])

    def test_a_conditional_python_skip_counts_unless_its_condition_is_the_constant_that_never_skips(self):
        def count(decorator):
            text = f"import unittest, pytest\n{decorator}\ndef test_a():\n    assert 1\n"
            return len(found({"tests/test_a.py": text}))

        self.assertEqual(
            [count(d) for d in (
                '@unittest.skipIf(False, "x")', '@unittest.skipUnless(True, "x")',
                '@pytest.mark.skipif(False, reason="x")', '@pytest.mark.skipif(condition=False)',
                '@unittest.skipIf(True, "x")', '@unittest.skipUnless(False, "x")',
                '@pytest.mark.skipif(sys.platform == "win32", reason="x")',
                '@unittest.skipIf(False or flag, "x")')],
            [0, 0, 0, 0, 1, 1, 1, 1])

    def test_turning_a_skip_condition_on_raises_the_count(self):
        def world(condition):
            return f'import unittest\n@unittest.skipIf({condition}, "x")\ndef test_a():\n    assert 1\n'

        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "tests/test_a.py", world("False"))
            commit_all(root)
            mark_base(root)
            write(root, "tests/test_a.py", world("True"))
            commit_all(root)
            rises = never_rise.judge(root, "main", [skipped_test_lint.ENFORCER], timeout=60).rises
        self.assertEqual(rises, (Rise("B23", 0, 1, (Violation("B23", "tests/test_a.py", 3),)),))

    def test_an_nunit_ignore_named_argument_of_a_test_case_disables_the_test(self):
        cases = [ok("public class T {"), ok('[TestCase(1, Ignore = "maintenance")]'),
                 bad("public void A(int n) { Run(1); }"),
                 ok('[TestCase(2, IgnoreReason = "later"), TestCase(3)]'),
                 bad("public void B(int n) { Run(2); }"),
                 ok("[TestCase(4, Explicit = true)]"), bad("public void C(int n) { Run(3); }"),
                 ok("[TestCase(5, Explicit = false)]"), ok("public void D(int n) { Run(4); }"),
                 ok("[TestCase(6, Description = \"Ignore = 1\")]"),
                 ok("public void E(int n) { Run(5); }"), ok("}")]

        self.assertEqual(found({"src/T.cs": source(cases)[0]}),
                         [("src/T.cs", n) for n in source(cases)[1]])

    def test_an_ignore_named_argument_of_a_test_fixture_disables_every_test_in_it(self):
        fixture = [ok('[TestFixture(Ignore = "maintenance")]'), ok("public class A {"),
                   ok("[Test]"), bad("public void B() { Run(1); }"),
                   ok("[Test]"), bad("public void C() { Run(2); }"), ok("}"),
                   ok("[TestFixture(Explicit = false)]"), ok("public class D {"),
                   ok("[Test]"), ok("public void E() { Run(3); }"), ok("}")]
        explicit = [ok("public class F {"), ok("[Fact(Explicit = true)]"),
                    bad("public void G() { Run(4); }"), ok("[Theory(Explicit = false)]"),
                    ok("public void H(int n) { Run(5); }"), ok("}")]

        self.assertEqual(found({"src/A.cs": source(fixture)[0]}),
                         [("src/A.cs", n) for n in source(fixture)[1]])
        self.assertEqual(found({"src/F.cs": source(explicit)[0]}),
                         [("src/F.cs", n) for n in source(explicit)[1]])

    def test_a_csharp_file_with_an_unmatched_bracket_is_read_without_error(self):
        for text in ("[Fact]\npublic void A() {\n", '[Fact(Skip = "x"]\npublic void A() { }\n',
                     "[Fact]\npublic void A(\n"):
            self.assertEqual(found({"src/fixture.cs": text}), [], text)


if __name__ == "__main__":
    unittest.main()
