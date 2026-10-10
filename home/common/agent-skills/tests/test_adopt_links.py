"""Unit tables for `agent_tools.adopt_links` (#345 D3, D4, D5, D14, D15, D18)."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_tools import adopt_links
from agent_tools.adopt_links import Resolved, RewrittenFile, Tree


def targets(text: str) -> list[tuple[str, bool]]:
    return [(link.target, link.angle) for link in adopt_links.links(text)]


def summary(inbound=(0, []), outbound=(0, []), unrewritable=(),
            already_broken=0) -> dict:
    return {"inbound": {"links": inbound[0], "files": list(inbound[1])},
            "outbound": {"links": outbound[0], "files": list(outbound[1])},
            "unrewritable": [{"path": p, "target": t}
                             for p, t in unrewritable],
            "already_broken": already_broken}


class LinkGrammarTest(unittest.TestCase):
    def test_inline_links_and_images(self):
        self.assertEqual(targets("a [x](b.md) and ![y](c.png)\n"),
                         [("b.md", False), ("c.png", False)])

    def test_angle_targets_and_titles(self):
        self.assertEqual(
            targets('[x](<a b.md> "T") [y](c.md \'t\') [z](d.md (t))\n'),
            [("a b.md", True), ("c.md", False), ("d.md", False)])

    def test_balanced_brackets_and_parentheses(self):
        self.assertEqual(targets("[a [b] c](x(1).md)\n"),
                         [("x(1).md", False)])

    def test_reference_definitions(self):
        self.assertEqual(
            targets('[ref]: docs/a.md "Title"\n   [r2]: <b c.md>\n'),
            [("docs/a.md", False), ("b c.md", True)])

    def test_indented_code_and_footnotes_are_not_definitions(self):
        self.assertEqual(targets("    [ref]: a.md\n[^1]: b.md\n"), [])

    def test_fenced_code_is_skipped(self):
        text = ("```md\n[a](x.md)\n```\n"
                "~~~~\n[b](y.md)\n~~~\n~~~~\n[c](z.md)\n")
        self.assertEqual(targets(text), [("z.md", False)])

    def test_an_unclosed_fence_runs_to_the_end(self):
        self.assertEqual(targets("```\n[a](x.md)\n"), [])

    def test_a_backtick_line_with_a_backtick_info_is_not_a_fence(self):
        self.assertEqual(targets("``` `x`\n[a](x.md)\n"), [("x.md", False)])

    def test_code_spans_are_skipped(self):
        self.assertEqual(
            targets("`[a](x.md)` and ``[b](`y`.md)`` then [c](z.md)\n"),
            [("z.md", False)])

    def test_an_unclosed_backtick_is_literal(self):
        self.assertEqual(targets("a ` b [c](z.md)\n"), [("z.md", False)])

    def test_an_escaped_bracket_opens_nothing(self):
        self.assertEqual(targets("\\[a](x.md)\n"), [])

    def test_a_link_must_close_on_its_line(self):
        self.assertEqual(targets("[a](x.md\nmore)\n[b] (y.md)\n"), [])

    def test_an_image_inside_link_text_is_its_own_link(self):
        self.assertEqual(targets("[![i](a.png)](b.md)\n"),
                         [("a.png", False), ("b.md", False)])

    def test_a_title_is_never_scanned_for_links(self):
        for text, expected in (
                ('[o](old/a.md "Example: [i](old/b.md)")\n',
                 [("old/a.md", False)]),
                ("[o](<a b.md> '[i](c.md)') [p](d.md ([i](e.md)))\n",
                 [("a b.md", True), ("d.md", False)]),
                ('[![i](a.png "[t](t.md)")](b.md "[u](u.md)")\n',
                 [("a.png", False), ("b.md", False)])):
            with self.subTest(text=text):
                self.assertEqual(targets(text), expected)

    def test_a_link_overlapping_a_recorded_link_is_not_a_link(self):
        self.assertEqual(targets("[a [b](c](d.md))\n"), [("d.md", False)])

    def test_offsets_cover_exactly_the_target(self):
        text = "x [a](<b c.md>) [d](e.md#f)\r\n[r]: g.md\r\n"
        self.assertEqual(
            [text[link.start:link.end] for link in adopt_links.links(text)],
            ["b c.md", "e.md#f", "g.md"])


class RelativityTest(unittest.TestCase):
    def test_the_relative_targets(self):
        for target, expected in (
                ("a.md", True), ("./a.md", True), ("../a.md", True),
                ("a.md#x", True), ("?q", True), ("", False), ("#x", False),
                ("/a.md", False), ("//host/a", False), ("https://x", False),
                ("mailto:a@b", False), ("a\\b.md", False)):
            with self.subTest(target=target):
                self.assertEqual(adopt_links.is_relative(target), expected)

    def test_the_scanned_files(self):
        for path, mode, expected in (
                ("a.md", "100644", True), ("a.MARKDOWN", "100755", True),
                ("a.mdx", "100644", False), ("a.txt", "100644", False),
                ("a.md", "120000", False), ("a.md", "160000", False),
                ("secrets/a.md", "100644", False),
                (".env.md", "100644", False)):
            with self.subTest(path=path, mode=mode):
                self.assertEqual(adopt_links.scanned(path, mode), expected)


TREE = Tree(["README.md", "docs/a.md", "docs/sub/b.md", "x y.md"])


class ResolutionTest(unittest.TestCase):
    def test_files(self):
        resolve = adopt_links.resolve
        self.assertEqual(resolve("docs/a.md", "sub/b.md#h", TREE),
                         Resolved("docs/sub/b.md", False))
        self.assertEqual(resolve("docs/sub/b.md", "../../README.md", TREE),
                         Resolved("README.md", False))
        self.assertEqual(resolve("README.md", "x%20y.md", TREE),
                         Resolved("x y.md", False))
        self.assertEqual(resolve("README.md", "docs/a.md?raw=1", TREE),
                         Resolved("docs/a.md", False))

    def test_directories_and_the_root(self):
        resolve = adopt_links.resolve
        for target in ("docs/sub", "docs/sub/"):
            self.assertEqual(resolve("README.md", target, TREE),
                             Resolved("docs/sub", True))
        for target in ("..", "../"):
            self.assertEqual(resolve("docs/a.md", target, TREE),
                             Resolved("", True))
        self.assertEqual(resolve("docs/a.md", "?q", TREE),
                         Resolved("docs", True))

    def test_what_never_resolves(self):
        for container, target in (("README.md", "docs/a.md/"),
                                  ("README.md", "../README.md"),
                                  ("README.md", "docs/c.md")):
            with self.subTest(target=target):
                self.assertIsNone(
                    adopt_links.resolve(container, target, TREE))

    def test_broken_count_reads_only_relative_links(self):
        self.assertEqual(adopt_links.broken_count(
            "docs/a.md",
            "[a](sub/b.md) [b](nope.md) [c](https://x) [d](#h)\n", TREE), 1)


PATHS = ["README.md", "old/a.md", "old/b.md", "old/sub/c.md", "keep/k.md"]
MOVES = [("old/a.md", "new/x/a.md"), ("old/b.md", "new/x/b.md"),
         ("old/sub/c.md", "new/x/sub/c.md")]


def rewrites(texts, paths=PATHS, moves=MOVES, deleted=()):
    return adopt_links.plan_link_rewrites(texts, paths, moves, deleted)


class RewriteTest(unittest.TestCase):
    def test_an_inbound_link_keeps_its_anchor_and_title(self):
        before = ('[a](old/a.md#top "T") [k](keep/k.md) '
                  '[w](https://x/old/a.md)\n')
        after = ('[a](new/x/a.md#top "T") [k](keep/k.md) '
                 '[w](https://x/old/a.md)\n')
        result = rewrites({"README.md": before})
        self.assertEqual(result.files, {
            "README.md": RewrittenFile("README.md", before, after)})
        self.assertEqual(result.summary,
                         summary(inbound=(1, ["README.md"])))

    def test_a_title_stays_literal_text(self):
        before = '[outer](old/a.md "Example: [inner](old/b.md)")\n'
        after = '[outer](new/x/a.md "Example: [inner](old/b.md)")\n'
        result = rewrites({"README.md": before})
        self.assertEqual(result.files, {
            "README.md": RewrittenFile("README.md", before, after)})
        self.assertEqual(result.summary,
                         summary(inbound=(1, ["README.md"])))

    def test_an_outbound_link_is_re_rooted_and_co_moved_links_stay(self):
        before = "[r](../README.md) [b](b.md) [c](./sub/c.md) [k](<../keep/k.md>)\n"
        after = "[r](../../README.md) [b](b.md) [c](./sub/c.md) [k](<../../keep/k.md>)\n"
        result = rewrites({"old/a.md": before})
        self.assertEqual(result.files, {
            "new/x/a.md": RewrittenFile("old/a.md", before, after)})
        self.assertEqual(result.summary,
                         summary(outbound=(2, ["new/x/a.md"])))

    def test_a_reference_definition_is_rewritten_and_its_use_kept(self):
        result = rewrites({"README.md": "See [a][ref].\n\n[ref]: old/a.md 'T'\n"})
        self.assertEqual(result.files["README.md"].after,
                         "See [a][ref].\n\n[ref]: new/x/a.md 'T'\n")

    def test_a_directory_moved_wholesale_maps_to_its_successor(self):
        result = rewrites({"README.md": "[d](./old/) [s](old/sub)\n"})
        self.assertEqual(result.files["README.md"].after,
                         "[d](./new/x/) [s](new/x/sub)\n")

    def test_a_surviving_directory_maps_to_itself(self):
        result = rewrites({"README.md": "[d](old/)\n"},
                          paths=PATHS + ["old/stay.md"])
        self.assertEqual(result.files, {})
        self.assertEqual(result.summary, summary())

    def test_a_dissolved_directory_is_unrewritable(self):
        moves = [("old/a.md", "new/x/a.md"), ("old/b.md", "elsewhere/b.md"),
                 ("old/sub/c.md", "new/x/sub/c.md")]
        result = rewrites({"README.md": "[d](old/) [a](old/a.md)\n"},
                          moves=moves)
        self.assertEqual(result.files["README.md"].after,
                         "[d](old/) [a](new/x/a.md)\n")
        self.assertEqual(result.summary["unrewritable"],
                         [{"path": "README.md", "target": "old/"}])

    def test_a_deleted_target_is_unrewritable(self):
        result = rewrites({"README.md": "[k](keep/k.md)\n"},
                          deleted=["keep/k.md"])
        self.assertEqual(result.files, {})
        self.assertEqual(result.summary, summary(
            unrewritable=[("README.md", "keep/k.md")]))

    def test_already_broken_links_are_counted_and_never_touched(self):
        result = rewrites({"README.md": "[m](old/missing.md) [n](nope/)\n"})
        self.assertEqual(result.files, {})
        self.assertEqual(result.summary, summary(already_broken=2))

    def test_bare_targets_are_percent_encoded_and_angle_targets_raw(self):
        result = rewrites(
            {"README.md": "[a](old/a%20b.md) [b](<old/a b.md>)\n"},
            paths=["README.md", "old/a b.md"],
            moves=[("old/a b.md", "new dir/a b.md")])
        self.assertEqual(result.files["README.md"].after,
                         "[a](new%20dir/a%20b.md) [b](<new dir/a b.md>)\n")

    def test_encoded_names_re_emit_to_the_same_referent(self):
        names = ["a#b.md", "a?b.md", "100%.md", "a b.md"]
        paths = ["README.md"] + [f"old/{name}" for name in names]
        moves = [(f"old/{name}", f"new/{name}") for name in names]
        before = ("[a](<old/a%23b.md>) [b](<old/a%3Fb.md#h>) "
                  "[c](<old/100%25.md>) [d](<old/a b.md>)\n"
                  "[e](old/a%23b.md) [f](old/a%3Fb.md?q) "
                  "[g](old/100%25.md) [h](old/a%20b.md)\n")
        after = ("[a](<new/a%23b.md>) [b](<new/a%3Fb.md#h>) "
                 "[c](<new/100%25.md>) [d](<new/a b.md>)\n"
                 "[e](new/a%23b.md) [f](new/a%3Fb.md?q) "
                 "[g](new/100%25.md) [h](new/a%20b.md)\n")
        result = rewrites({"README.md": before}, paths=paths, moves=moves)
        self.assertEqual(result.files["README.md"].after, after)
        after_tree = Tree(["README.md"] + [new for _, new in moves])
        self.assertEqual(
            [adopt_links.resolve("README.md", link.target, after_tree)
             for link in adopt_links.links(after)],
            [Resolved(f"new/{name}", False) for name in names * 2])

    def test_angle_emission_escapes_only_what_changes_meaning(self):
        self.assertEqual(adopt_links.angle_target("d ü/a#b?c%d<e>f\r\n.md"),
                         "d ü/a%23b%3Fc%25d%3Ce%3Ef%0D%0A.md")

    def test_a_scheme_shaped_name_is_emitted_relative(self):
        paths = ["README.md", ".claude/specs/a.md",
                 ".agents/artifacts/specs/urn:reference.md"]
        moves = [(".claude/specs/a.md", ".agents/artifacts/specs/a.md")]
        before = ("[r](<../../.agents/artifacts/specs/urn:reference.md#h>) "
                  "[s](../../.agents/artifacts/specs/urn%3Areference.md)\n")
        after = "[r](<./urn:reference.md#h>) [s](urn%3Areference.md)\n"
        result = rewrites({".claude/specs/a.md": before}, paths=paths,
                          moves=moves)
        self.assertEqual(result.files, {
            ".agents/artifacts/specs/a.md": RewrittenFile(
                ".claude/specs/a.md", before, after)})
        after_tree = Tree(["README.md", ".agents/artifacts/specs/a.md",
                           ".agents/artifacts/specs/urn:reference.md"])
        self.assertEqual(
            [(adopt_links.is_relative(link.target),
              adopt_links.resolve(".agents/artifacts/specs/a.md",
                                  link.target, after_tree))
             for link in adopt_links.links(after)],
            [(True, Resolved(".agents/artifacts/specs/urn:reference.md",
                             False))] * 2)
        self.assertEqual(adopt_links.broken_count(
            ".agents/artifacts/specs/a.md", after, after_tree), 0)

    def test_a_co_moved_non_ascii_link_stays_byte_identical(self):
        result = rewrites({"old/a.md": "[u](ü.md)\n"},
                          paths=["old/a.md", "old/ü.md"],
                          moves=[("old/a.md", "new/x/a.md"),
                                 ("old/ü.md", "new/x/ü.md")])
        self.assertEqual(result.files, {})

    def test_a_leading_dot_slash_is_dropped_when_the_path_climbs(self):
        result = rewrites({"keep/k.md": "[a](./../old/a.md)\n"})
        self.assertEqual(result.files["keep/k.md"].after,
                         "[a](../new/x/a.md)\n")

    def test_line_endings_and_link_counts_are_preserved(self):
        before = "[a](old/a.md)\r\n[b](old/b.md)\r\n"
        after = rewrites({"README.md": before}).files["README.md"].after
        self.assertEqual(after, "[a](new/x/a.md)\r\n[b](new/x/b.md)\r\n")
        self.assertEqual(len(adopt_links.links(after)),
                         len(adopt_links.links(before)))


def git(root: Path, *args: str, data: bytes | None = None) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True, input=data,
                   env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull,
                            GIT_CONFIG_SYSTEM=os.devnull,
                            GIT_AUTHOR_NAME="t",
                            GIT_AUTHOR_EMAIL="t@example.invalid",
                            GIT_COMMITTER_NAME="t",
                            GIT_COMMITTER_EMAIL="t@example.invalid"))


class GitReaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        git(self.root, "init", "--quiet", "-b", "main")
        (self.root / "a.md").write_text("[b](old/b.md)\n", encoding="utf-8")
        (self.root / "old").mkdir()
        (self.root / "old" / "b.md").write_text("# b\n", encoding="utf-8")
        (self.root / "bad.md").write_bytes(b"\xff[a](a.md)\n")
        (self.root / "secrets").mkdir()
        (self.root / "secrets" / "s.md").write_text("[a](../a.md)\n",
                                                    encoding="utf-8")
        (self.root / "link.md").symlink_to("a.md")
        git(self.root, "add", "-A")
        git(self.root, "commit", "--quiet", "-m", "fixture")

    def test_only_scanned_decodable_blobs_are_read(self):
        records = adopt_links.tree_records(self.root, "HEAD")
        self.assertEqual([path for path, _, _ in records],
                         ["a.md", "bad.md", "link.md", "old/b.md",
                          "secrets/s.md"])
        self.assertEqual(adopt_links.markdown_texts(self.root, records),
                         {"a.md": "[b](old/b.md)\n", "old/b.md": "# b\n"})

    def test_the_index_answers_with_staged_bytes(self):
        (self.root / "a.md").write_text("[b](new/b.md)\n", encoding="utf-8")
        git(self.root, "add", "a.md")
        texts = adopt_links.markdown_texts(
            self.root, adopt_links.index_records(self.root))
        self.assertEqual(texts["a.md"], "[b](new/b.md)\n")

    def test_the_derivation_reads_the_revision_not_the_working_tree(self):
        (self.root / "a.md").write_text("unrelated edit\n", encoding="utf-8")
        result = adopt_links.derive_link_rewrites(
            self.root, "HEAD", [("old/b.md", "new/b.md")], [], [])
        self.assertEqual(result.files, {"a.md": RewrittenFile(
            "a.md", "[b](old/b.md)\n", "[b](new/b.md)\n")})
        excluded = adopt_links.derive_link_rewrites(
            self.root, "HEAD", [("old/b.md", "new/b.md")], [], ["a.md"])
        self.assertEqual(excluded.files, {})
        self.assertEqual(excluded.summary, summary())


if __name__ == "__main__":
    unittest.main()
