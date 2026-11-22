"""The copied-test rule of `agent_tools.delivery.copied_test_lint` (#1464).

Measures the rule against source text and real git worlds: tests sharing a body,
once comments and whitespace are removed, are one violation each beyond the
first by path and line, whatever their names, decorators, attributes or titles;
bodies of different families and bodies a token apart never match; a JavaScript
declaration with no callback is never a copy; and the project's count may not
rise against the merge base whichever file holds the copy.

The suite holds `standard:B19` by judging the enforcer
`agent_tools.delivery.copied_test_lint` on real git worlds, so the rule index
lists this enforcer.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery import copied_test_lint, never_rise, rule_ids, skipped_test_lint
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
    return Snapshot("fixture", {path: text.count("\n") for path, text in files.items()}, blobs)


def found(files):
    return [(v.path, v.line) for v in copied_test_lint.find(snapshot(files))]


def cited(module):
    return {c.token for c in rule_ids.citations(Path(module.__file__).read_text(encoding="utf-8"))
            if c.well_formed}


FIRST = [
    ok("import unittest"), ok(""), ok("class A(unittest.TestCase):"),
    ok("    def test_one(self):"), ok("        x = compute(1)"),
    ok("        self.assertEqual(x, 2)"), ok(""),
    bad("    def test_two(self):"), ok("        # the same case again"), ok("        x = compute(1)"),
    ok(""), ok("        self.assertEqual(x, 2)"),
]
SECOND = [
    ok("import unittest"), ok("class B(unittest.TestCase):"), ok("    # a third copy"),
    bad("    def test_three(self):"), ok("        x = compute(1)"),
    ok("        self.assertEqual(x, 2)"),
]
UNICODE = [
    ok("def test_six():"), ok("    s = render()"), ok('    self.assertEqual(s, "é")'),
    bad("def test_seven():"), ok("    s = render()"),
    ok('    self.assertEqual(s, "é")  # note'),
]
DIFFERING = [
    ok("def test_four():"), ok("    x = compute(1)"), ok("    self.assertEqual(x, 2)"),
    ok("def test_five():"), ok("    x = compute(3)"), ok("    self.assertEqual(x, 2)"),
]
PYTHON_PAIR = [
    ok("def test_p():"), ok("    run(21)"), bad("def test_q():"), ok("    run(21)"),
]
TYPESCRIPT_PAIR = [
    ok("it('a', () => { run(21); });"), bad("it('b', () => { run(21); });"),
]
CSHARP_PAIR = [
    ok("public class T"), ok("{"), ok("    [Fact]"), ok("    public void A()"),
    ok("    { run(21); }"), ok("    [Fact]"), bad("    public void B()"), ok("    { run(21); }"),
    ok("}"),
]


class CopiedTestLintTest(unittest.TestCase):
    def run_command(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.copied_test_lint", *arguments],
            capture_output=True, text=True, timeout=60, env=fixture_env())

    def committed(self, tmp, name, files):
        directory = Path(tmp) / name
        directory.mkdir()
        root = repo(directory)
        for path, pairs in files.items():
            write(root, path, source(pairs)[0].encode("utf-8"))
        commit_all(root)
        return root

    def test_three_tests_sharing_a_body_are_two_violations_and_a_one_token_difference_is_none(self):
        shared = {"tests/test_a.py": FIRST, "tests/test_b.py": SECOND, "tests/test_u.py": UNICODE}
        with tempfile.TemporaryDirectory() as tmp:
            root = self.committed(tmp, "shared", shared)
            copies = self.run_command("--repo-root", str(root))
            other = self.committed(tmp, "differing", {"tests/test_c.py": DIFFERING})
            apart = self.run_command("--repo-root", str(other))
        expected = "".join(
            f"B19 {path}:{n}\n" for path in sorted(shared) for n in source(shared[path])[1])
        self.assertEqual((copies.returncode, copies.stdout), (1, expected))
        self.assertEqual((apart.returncode, apart.stdout), (0, ""))

    def test_each_family_reports_its_copies(self):
        files = {"tests/test_p.py": PYTHON_PAIR, "web/a.test.ts": TYPESCRIPT_PAIR,
                 "src/T.cs": CSHARP_PAIR}

        self.assertEqual(
            found({path: source(pairs)[0] for path, pairs in files.items()}),
            [(path, source(files[path])[1][0]) for path in sorted(files)])

    def test_names_decorators_attributes_and_titles_do_not_distinguish_bodies(self):
        python = source([
            ok("import unittest"), ok("def test_alpha():"), ok("    run(31)"),
            ok('@unittest.skipIf(True, "x")'), bad("def test_beta():"), ok("    run(31)")])
        csharp = source([
            ok("public class T"), ok("{"), ok("    [Fact]"), ok("    public void A()"),
            ok("    { Run(32); }"), ok("    [Test]"), bad("    public void Other()"),
            ok("    { Run(32); }"), ok("}")])
        javascript = source([
            ok("it('first title', () => { run(33); });"),
            bad("it('another title', () => { run(33); });")])
        files = {"tests/test_n.py": python, "src/T.cs": csharp, "web/n.test.js": javascript}

        self.assertEqual(
            found({path: text for path, (text, _) in files.items()}),
            [(path, files[path][1][0]) for path in sorted(files)])

    def test_the_first_by_path_and_line_is_kept(self):
        later = [ok("# padding")] * 8 + [ok("def test_late():"), ok("    run(41)")]
        earlier = [ok("import unittest"), ok(""), bad("def test_early():"), ok("    run(41)")]

        self.assertEqual(
            found({"tests/test_a.py": source(later)[0], "tests/test_b.py": source(earlier)[0]}),
            [("tests/test_b.py", 3)])

    def test_each_enforcer_cites_its_own_rule_id_and_both_are_rules_of_the_bar(self):
        bar = rule_ids.sections(BAR.read_text(encoding="utf-8"))

        self.assertNotEqual(copied_test_lint.RULE_ID, skipped_test_lint.RULE_ID)
        self.assertIn(copied_test_lint.RULE_ID, bar)
        self.assertIn(skipped_test_lint.RULE_ID, bar)
        self.assertEqual(cited(copied_test_lint), {copied_test_lint.RULE_ID})
        self.assertEqual(cited(skipped_test_lint), {skipped_test_lint.RULE_ID})

    def test_the_command_is_a_row_of_the_command_table(self):
        self.assertIn('"copied-test-lint" = "delivery.copied_test_lint";',
                      COMMAND_TABLE.read_text(encoding="utf-8"))

    def test_a_callback_less_declaration_is_never_a_copy_and_a_focused_one_is(self):
        pairs = [
            ok("it('a', () => { run(1); })"), bad("fit('b', () => { run(1); })"),
            ok("it('c')"), ok("it('d')")]

        self.assertEqual(found({"web/a.test.js": source(pairs)[0]}), [("web/a.test.js", 2)])

    def test_a_comment_in_a_template_hole_keeps_a_copy_and_a_changed_hole_token_does_not(self):
        tick = "`"
        pairs = [
            ok(f"test('a', () => {{ expect({tick}ran ${{argv.join(' ')}}{tick}).toBe(x); }});"),
            bad(f"test('b', () => {{ expect({tick}ran ${{argv /* note */ .join(' ')}}{tick}).toBe(x); }});"),
            ok(f"test('c', () => {{ expect({tick}ran ${{argv.join(',')}}{tick}).toBe(x); }});")]

        self.assertEqual(found({"web/b.test.ts": source(pairs)[0]}), [("web/b.test.ts", 2)])


COPIED_A = [
    ok("import unittest"), ok("class A(unittest.TestCase):"),
    ok("    def test_a(self):"), ok("        self.assertEqual(compute(7), 8)"),
    ok("    def test_b(self):"), ok("        self.assertEqual(compute(7), 8)"),
]


class CopiedNeverRiseTest(unittest.TestCase):
    def judge(self, root):
        return never_rise.judge(root, "main", [copied_test_lint.ENFORCER], timeout=60).rises

    def base(self, root, files):
        for path, text in files.items():
            write(root, path, text)
        commit_all(root)
        mark_base(root)

    def test_one_more_copied_body_than_the_merge_base_rises(self):
        added = [ok("import unittest"), ok(""), ok("class B(unittest.TestCase):"),
                 ok("    # a third copy"), bad("    def test_c(self):"),
                 ok("        self.assertEqual(compute(7), 8)")]
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            self.base(root, {"tests/test_a.py": source(COPIED_A)[0]})
            write(root, "tests/test_b.py", source(added)[0])
            commit_all(root)
            self.assertEqual(self.judge(root), (
                Rise("B19", 1, 2, (Violation("B19", "tests/test_b.py", source(added)[1][0]),)),))

    def test_an_unchanged_branch_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            self.base(root, {"tests/test_a.py": source(COPIED_A)[0], "src/app.py": "a = 1\n"})
            write(root, "src/app.py", "a = 2\n")
            commit_all(root)
            self.assertEqual(self.judge(root), ())

    def test_a_copy_moved_to_another_file_keeps_the_count(self):
        base = COPIED_A + [ok("    def test_p(self):"), ok("        self.assertEqual(compute(9), 10)")]
        trimmed = base[:4] + base[6:]
        moved = [ok("import unittest"), ok("class D(unittest.TestCase):"),
                 ok("    def test_d(self):"), ok("        self.assertEqual(compute(7), 8)")]
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            self.base(root, {"tests/test_a.py": source(base)[0]})
            write(root, "tests/test_a.py", source(trimmed)[0])
            write(root, "tests/test_d.py", source(moved)[0])
            commit_all(root)
            self.assertEqual(self.judge(root), ())


if __name__ == "__main__":
    unittest.main()
