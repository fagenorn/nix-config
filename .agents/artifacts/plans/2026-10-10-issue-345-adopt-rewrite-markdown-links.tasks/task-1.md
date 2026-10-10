# Task 1: `adopt_links` — grammar, resolution, mapping and re-emission

**Files:**
- Create: `python/agent_tools/adopt_links.py`
- Modify: `python/agent_tools/adopt_inspection.py` (`run_git` gains `input`, per D16)
- Create: `home/common/agent-skills/tests/test_adopt_links.py`
- Modify: `justfile` (`agent-workflow-tests`: add the new test module directly after `test_adopt_verify.py`)

**Interfaces:**
- Consumes: `adopt_inspection.is_secret_path`, `refuse`, `run_git`, `git_or_fail`, `split_nul` (existing).
- Produces (all in `agent_tools.adopt_links`; Tasks 2 and 3 rely on these exact names):
  - `MARKDOWN_SUFFIXES = (".md", ".markdown")`, `REGULAR_MODES = ("100644", "100755")`
  - `is_markdown_path(path: str) -> bool` — the path, ASCII-lowercased, ends with a member of `MARKDOWN_SUFFIXES`.
  - `scanned(path: str, mode: str) -> bool` — `mode in REGULAR_MODES and is_markdown_path(path) and not is_secret_path(path)` (D2).
  - `@dataclass(frozen=True) class Link: start: int; end: int; target: str; angle: bool` — `text[start:end] == target`; for an angle target the span excludes `<` and `>`.
  - `links(text: str) -> list[Link]` — every link and reference definition, ordered by `start` (D3, D15).
  - `is_relative(target: str) -> bool` (D3).
  - `class Tree: def __init__(self, paths: Iterable[str])` with attributes `paths: frozenset[str]` and `directories: frozenset[str]` (every proper `/`-prefix of a path, e.g. `"a/b/c"` gives `"a"`, `"a/b"`).
  - `@dataclass(frozen=True) class Resolved: path: str; directory: bool` — the root is `Resolved("", True)`.
  - `resolve(container: str, target: str, tree: Tree) -> Resolved | None` (D3).
  - `broken_count(container: str, text: str, tree: Tree) -> int` — relative links in `text` whose `resolve` is None.
  - `@dataclass(frozen=True) class RewrittenFile: source: str; before: str; after: str` — base path, base text, rewritten text.
  - `@dataclass(frozen=True) class LinkRewrites: summary: dict; files: dict[str, RewrittenFile]` — `files` keyed by the file's path after the moves, holding only files whose text changed.
  - `plan_link_rewrites(texts: dict[str, str], paths: Iterable[str], moves: Iterable[tuple[str, str]], deleted: Iterable[str]) -> LinkRewrites` — pure (D4, D5, D8, D12, D14).
  - `tree_records(root: Path, revision: str) -> list[tuple[str, str, str]]` and `index_records(root: Path) -> list[tuple[str, str, str]]` — `(path, mode, object_id)`, sorted by path.
  - `markdown_texts(root: Path, records: list[tuple[str, str, str]]) -> dict[str, str]` — every `scanned` record's blob decoded as strict UTF-8; undecodable blobs are omitted.
  - `derive_link_rewrites(root: Path, revision: str, moves, deleted, excluded: Iterable[str]) -> LinkRewrites` — `markdown_texts(root, tree_records(root, revision))` minus `excluded`, and `plan_link_rewrites` over it with every path of that tree (D6, D13).
  - `adopt_inspection.run_git(root, *args, network=False, input: bytes | None = None)` — `input` is passed to `subprocess.run`; every existing call is unchanged.

**Invariants:**
- Standard library only; `adopt_links` imports `adopt_inspection` and nothing that imports the resolver (D3, #148 D26). It reads blobs only through git, never the working tree.
- `plan_link_rewrites` replaces only target spans: for every file in `files`, `len(links(after)) == len(links(before))` and the text outside the replaced spans is identical.
- `summary` is exactly `{"inbound": {"links": int, "files": [str]}, "outbound": {"links": int, "files": [str]}, "unrewritable": [{"path": str, "target": str}], "already_broken": int}`; `files` lists are sorted; `unrewritable` is de-duplicated and sorted by `(path, target)`; outbound files are named by their path after the move (D8).

**Algorithm decisions (implement exactly):**

`links(text)` — split at `"\n"` only, tracking each line's offset (D15). Fence state: a line matching `^ {0,3}(`{3,}|~{3,})` opens a fence unless it is a backtick fence whose remainder holds a backtick; it closes on a line matching `^ {0,3}` + the same character repeated at least the opening length + `[ \t]*\r?$`; an unclosed fence runs to the end. Lines inside a fence (and both fence lines) yield nothing. Otherwise a line matching

```python
REFERENCE = re.compile(
    r"^ {0,3}\[(?!\^)(?:[^\[\]\\]|\\.)+\]:[ \t]*"
    r"(?:<(?P<angle>[^<>\r]*)>|(?P<bare>[^\s<]\S*))(?:[ \t]+.*)?\r?$")
```

yields its one target and nothing else. Every other line is scanned inline: first mask code spans (a run of `n` backticks opens a span closed by the next run of exactly `n` backticks on the line; an unclosed run is literal). Then for each unmasked `[` not preceded by an odd number of backslashes: find its matching `]` by depth counting that skips masked characters and backslash-escaped characters; require `(` immediately after; skip `[ \t]*`; read the destination — `<...>` with no `<` or `>` inside (angle), or a bare run up to whitespace or an unbalanced `)`, tracking parenthesis depth and skipping the character after a backslash (bare, must end at depth 0); skip `[ \t]*`; optionally a title opened by `"`, `'` or `(` and closed by `"`, `'` or `)` respectively; skip `[ \t]*`; require `)`. On success record the `Link` and resume at the character after the opening `[` (so an image inside link text is found, D15); an opener inside an already-recorded target span is skipped.

`is_relative(target)` — False when the target is empty, starts with `#` or `/`, matches `^[A-Za-z][A-Za-z0-9+.-]*:`, or contains `\`; True otherwise.

`resolve(container, target, tree)` — split at the first `?` or `#` (the suffix is discarded); `path = urllib.parse.unquote(raw)`; `joined = posixpath.normpath(posixpath.join(posixpath.dirname(container), path))`; None when `joined == ".."` or starts with `"../"`; `Resolved("", True)` when `joined == "."`; `Resolved(joined, False)` when `path` does not end with `/` and `joined in tree.paths`; `Resolved(joined, True)` when `joined in tree.directories`; None otherwise.

`plan_link_rewrites` — `base = Tree(paths)`; `moved = dict(moves)`; `after = Tree((base.paths - moved.keys() - set(deleted)) | set(moved.values()))` (D12). For each `(F, text)` in sorted `texts`: `F2 = moved.get(F, F)`; direction is `outbound` when `F in moved`, else `inbound`. For each link with a relative target: `r = resolve(F, target, base)`; None → `already_broken += 1`. Map `r` to `T2`: a file → `moved[r.path]`, or unrewritable when `r.path in deleted`, else `r.path`; the root → `""`; a directory in `after.directories` → itself; otherwise every base member `m` under `r.path + "/"` must be moved with `moved[m].endswith(m[len(r.path):])`, and the prefixes `moved[m][:-len(m[len(r.path):])]` must be one non-empty value `N` → `N`; anything else is unrewritable, recorded as `{"path": F, "target": target}` and left untouched (D5). Re-emit (D4, D14): with `raw` the target's path part and `suffix` the rest, untouched when `posixpath.normpath(posixpath.join(posixpath.dirname(F2), unquote(raw))) == (T2 or ".")`; else `rel = posixpath.relpath(T2 or ".", posixpath.dirname(F2) or ".")`; prefix `./` when `raw` starts with `./`, `rel != "."` and `rel` does not start with `../`; append `/` when `r.directory` and `raw` ends with `/`; the new target is `rel` (angle) or `urllib.parse.quote(rel, safe="/")` (bare), plus `suffix`. Replace spans right to left; count each replaced link under its direction.

`markdown_texts` — one `git cat-file --batch` (through `run_git(..., input=...)`) over the de-duplicated object ids of the `scanned` records; parse `<oid> <type> <size>\n<bytes>\n` frames; a `missing` frame or a short read refuses `adopt_failure` / `adopt.git.failed`. `tree_records` parses `git ls-tree -r -z <revision>` (`<mode> <type> <oid>\t<path>`, refusing `adopt.git.unparseable_tree` like `tree_inventory`); `index_records` parses `git ls-files -s -z` (`<mode> <oid> <stage>\t<path>`, stage `0` only, refusing `adopt.git.unparseable_index` like `tracked_inventory`).

- [ ] **Step 1: Write the failing tests**

Create `home/common/agent-skills/tests/test_adopt_links.py`:

```python
"""Unit tables for `agent_tools.adopt_links` (#345 D3, D4, D5, D14, D15)."""

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
```

Add `home/common/agent-skills/tests/test_adopt_links.py \` to the `agent-workflow-tests` recipe in `justfile`, directly after the `test_adopt_verify.py` line.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_links.py`
Expected: ERROR — `ImportError: cannot import name 'adopt_links' from 'agent_tools'`.

- [ ] **Step 3: Write the minimal implementation**

Create `python/agent_tools/adopt_links.py` with the interfaces and the algorithm decisions above, and a module docstring stating what it owns ("a relative Markdown link and what it resolves to over a set of tracked paths"), that it is imported and never run, reads blobs only through git, and imports no resolver. Add the keyword-only `input: bytes | None = None` to `adopt_inspection.run_git`, passed straight to `subprocess.run`.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_links.py`
Expected: PASS, every test in the module.
Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_apply.py`
Expected: PASS (the `run_git` change is behaviour-neutral).
Run: `if ! grep -q 'tests/test_adopt_links.py' justfile; then exit 1; fi`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_links.py python/agent_tools/adopt_inspection.py home/common/agent-skills/tests/test_adopt_links.py justfile
launch-commit … -- -m "feat(adopt): add the relative Markdown link model (#345)"
```
