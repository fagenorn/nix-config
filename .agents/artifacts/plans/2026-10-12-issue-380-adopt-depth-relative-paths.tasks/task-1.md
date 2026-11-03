# Task 1: The depth reading's text climbs, landing point and `/depth` class

**Files:**
- Modify: `python/agent_tools/adopt_references.py`
- Test: `home/common/agent-skills/tests/test_adopt_references.py`

**Interfaces:**
- Consumes: the existing `tokens`, `file_class`, `_names_moved`, `Occurrence`, `References`, `plan_references`, `policy_summary`, `effective_answer`, `rewritten`, `_edit` (unchanged: a `rewrite` splices `replacement` over `start:end`).
- Produces (Tasks 2 and 3 rely on these names):
  - `Occurrence.depth: bool = False` — a new **last** field, after `variable`.
  - `Occurrence.occurrence_class` — `<file class>/depth` when `depth`, else as today (`/variable` or the file class).
  - `split_climb(token: str) -> tuple[str, int, str] | None` — `(prefix, height, rest)`, `prefix + "/".join([".."] * height) + rest == token`.
  - `climb_form(prefix: str, height: int, rest: str) -> str | None` — None when `height < 1`.
  - `plan_references(texts, paths, moves, trees, depth_texts: Mapping[str, str] | None = None) -> References` — `depth_texts` is the depth reading's read set, keyed by base path.
  - Private, reused by Task 2: `_depth_occurrences(path, text, base, sources, target, tree) -> list[Occurrence]` and its inner per-climb decision (below).

**Invariants:**
- Without `depth_texts`, `plan_references` returns exactly what it returns at base (every existing test in the file passes unchanged) (D7, D10).
- The plain, pattern and variable readings run only over `texts`; the depth reading runs only over `depth_texts`, and only for a file the moves carry (its `tree` is not None). A path in both maps gets all of them (D7).
- A depth occurrence has `depth` True, `variable` False, `shape` None, `additions` `()`, answers `("rewrite", "retain")` with a `replacement`, or `("retain",)` with `replacement` None — never `extend` (D5).
- Its policy is `<tree>:<file class>/depth`; `recommended_answer` of that class is None; an answer to `<tree>:<file class>` never decides it (D5, D6).
- A climb is an occurrence exactly when its landing point is a proper ancestor of the tree root `R` (or above the root), the same height from `Q` lands elsewhere, and (text climb) its base target is not inside `R`; `rewrite` is offered exactly when the landing point is an ancestor of `Q` or above the root, the base target names no moved path, and the shifted form is valid (D1, D3, D4, D8).
- Rest holding a `..` segment: not a climb (D11).

- [ ] **Step 1: Write the failing tests**

Insert into `home/common/agent-skills/tests/test_adopt_references.py` after `VariableReadingTest` and before the `def git(` helper:

```python
NOTES, NOTES_NEW = ".claude/notes", ".agents/artifacts/notes"
TOOL, TOOL_NEW = NOTES + "/tool", NOTES_NEW + "/tool"
DEPTH_PATHS = [TOOL + "/run.py", TOOL + "/pyproject.toml", TOOL + "/uv.lock",
               NOTES + "/data/x", "vendor/lib/m.py", ".claude/specs/x.md",
               "README.md"]
DEPTH_MOVES = [(TOOL + "/run.py", TOOL_NEW + "/run.py"),
               (TOOL + "/pyproject.toml", TOOL_NEW + "/pyproject.toml"),
               (TOOL + "/uv.lock", TOOL_NEW + "/uv.lock"),
               (NOTES + "/data/x", NOTES_NEW + "/data/x"),
               (".claude/specs/x.md", ".agents/artifacts/specs/x.md")]
DEPTH_TREES = {source: "/".join(source.split("/")[:2])
               for source, _ in DEPTH_MOVES}


def depth_found(texts, *, moves=DEPTH_MOVES, trees=DEPTH_TREES,
                paths=DEPTH_PATHS, scanned=None):
    return adopt_references.plan_references(
        scanned or {}, paths, moves, trees, depth_texts=texts).occurrences


def climbs(text, path=TOOL + "/pyproject.toml", **kwargs):
    return [(o.literal, o.answers, o.replacement, o.depth)
            for o in depth_found({path: text}, **kwargs)]


class TextClimbTest(unittest.TestCase):
    """#380 D1, D3, D4, D8: `../` climbs out of a moved file's tree."""

    def test_a_climb_splits_into_prefix_height_and_rest(self):
        split = adopt_references.split_climb
        for token, expected in (
                ("../x", ("", 1, "/x")), ("../../", ("", 2, "/")),
                ("../..", ("", 2, "")), ("./../x", ("./", 1, "/x")),
                ("./..", ("./", 1, "")),
                ("../../../vendor/lib", ("", 3, "/vendor/lib")),
                ("../a/./b", ("", 1, "/a/./b"))):
            with self.subTest(token=token):
                self.assertEqual(split(token), expected)
                self.assertEqual("".join((expected[0],
                                          "/".join([".."] * expected[1]),
                                          expected[2])), token)
        for token in ("..", "...", ".../x", "..x/y", "a/../b", "/../x",
                      "../a/../b", "x"):
            with self.subTest(token=token):
                self.assertIsNone(split(token))

    def test_the_shifted_form_keeps_prefix_and_rest(self):
        form = adopt_references.climb_form
        self.assertEqual(form("", 4, "/vendor/lib"), "../../../../vendor/lib")
        self.assertEqual(form("./", 1, ""), "./..")
        self.assertIsNone(form("", 0, "/x"))

    def test_a_climb_to_the_root_is_rewritten_one_level_deeper(self):
        self.assertEqual(climbs('lib = { path = "../../../vendor/lib" }\n'), [
            ("../../../vendor/lib", ("rewrite", "retain"),
             "../../../../vendor/lib", True)])
        self.assertEqual(climbs('p = "./../../../vendor/"\n'), [
            ("./../../../vendor/", ("rewrite", "retain"),
             "./../../../../vendor/", True)])

    def test_climbs_inside_the_tree_are_not_surfaced(self):
        for text in ('d = "../data/x"\n', 'd = "../../notes/data/x"\n',
                     'd = "./.."\n', 'd = "../x"\n'):
            with self.subTest(text=text):
                self.assertEqual(climbs(text), [])

    def test_a_landing_point_only_above_the_old_directory_is_retained(self):
        self.assertEqual(climbs('c = "../../settings.json"\n'), [
            ("../../settings.json", ("retain",), None, True)])

    def test_a_base_target_in_another_moved_tree_is_retained(self):
        self.assertEqual(climbs('s = "../../../.claude/specs/x.md"\n'), [
            ("../../../.claude/specs/x.md", ("retain",), None, True)])

    def test_bare_dots_are_no_climb(self):
        self.assertEqual(climbs('a = ".."\nb = HERE / ".." / ".."\n'), [])

    def test_a_same_depth_move_surfaces_nothing_new(self):
        moves = [(TOOL + "/pyproject.toml", "tools/notes/tool/pyproject.toml")]
        self.assertEqual(climbs('lib = { path = "../../../vendor/lib" }\n',
                                moves=moves), [])

    def test_a_same_depth_move_under_another_parent_is_retained(self):
        moves = [(TOOL + "/pyproject.toml", "tools/notes/tool/pyproject.toml")]
        self.assertEqual(climbs('c = "../../settings.json"\n', moves=moves), [
            ("../../settings.json", ("retain",), None, True)])

    def test_a_shallower_move_climbs_less(self):
        moves = [(TOOL + "/pyproject.toml", "notes/tool/pyproject.toml")]
        self.assertEqual(climbs('lib = "../../../vendor/lib"\n', moves=moves),
                         [("../../../vendor/lib", ("rewrite", "retain"),
                           "../../vendor/lib", True)])
        self.assertEqual(climbs('top = "../../../../up"\n', moves=moves),
                         [("../../../../up", ("rewrite", "retain"),
                           "../../../up", True)])

    def test_a_shallower_move_that_cannot_climb_less_is_retained(self):
        moves = [(TOOL + "/pyproject.toml", "pyproject.toml")]
        # P = .claude/notes/tool (depth 3), Q = "" (depth 0): delta -3.
        self.assertEqual(climbs('lib = "../../../vendor/lib"\n', moves=moves),
                         [("../../../vendor/lib", ("retain",), None, True)])

    def test_an_unmoved_or_unread_file_has_no_depth_occurrence(self):
        self.assertEqual(climbs('lib = "../../../vendor/lib"\n',
                                path="tools/a/b/c.toml",
                                paths=DEPTH_PATHS + ["tools/a/b/c.toml"]), [])

    def test_the_class_and_policy_of_a_depth_occurrence(self):
        texts = {TOOL + "/pyproject.toml": 'lib = "../../../vendor/lib"\n',
                 TOOL + "/uv.lock": 'source = "../../../vendor/lib"\n'}
        self.assertEqual(
            [(o.subject, o.occurrence_class, o.policy, o.target)
             for o in depth_found(texts)],
            [(TOOL + "/pyproject.toml:1:8", ".toml/depth",
              NOTES + ":.toml/depth", TOOL_NEW + "/pyproject.toml"),
             (TOOL + "/uv.lock:1:11", ".lock/depth", NOTES + ":.lock/depth",
              TOOL_NEW + "/uv.lock")])

    def test_the_depth_read_set_gets_the_depth_reading_only(self):
        text = 'lib = "../../../vendor/lib"\nspec = ".claude/specs/x.md"\n'
        path = TOOL + "/pyproject.toml"
        self.assertEqual([o.depth for o in depth_found({path: text})], [True])
        self.assertEqual(
            [(o.subject, o.depth) for o in depth_found(
                {path: text}, scanned={path: text})],
            [(path + ":1:8", True), (path + ":2:9", False)])
        self.assertEqual(
            [o.depth for o in adopt_references.plan_references(
                {path: text}, DEPTH_PATHS, DEPTH_MOVES,
                DEPTH_TREES).occurrences], [False])

    def test_an_archived_file_is_its_own_directory(self):
        path = ".claude/odd.toml"
        moves = [(path, ".agents/knowledge/archive/adopted/.claude/odd.toml")]
        self.assertEqual(
            climbs('a = "./../x"\nb = "../../y"\n', path=path, moves=moves,
                   trees={path: path}, paths=[path]),
            [("./../x", ("rewrite", "retain"), "./../../../../../x", True),
             ("../../y", ("rewrite", "retain"), "../../../../../../y", True)])

    def test_the_depth_policy_partitions_answers_and_edits(self):
        path = TOOL + "/pyproject.toml"
        text = 'lib = "../../../vendor/lib"\nspec = ".claude/specs/x.md"\n'
        refs = adopt_references.plan_references(
            {path: text}, DEPTH_PATHS, DEPTH_MOVES, DEPTH_TREES,
            depth_texts={path: text})
        toml, depth = NOTES + ":.toml", NOTES + ":.toml/depth"
        _, climb = sorted(refs.occurrences, key=lambda o: o.depth)
        self.assertEqual(adopt_references.effective_answer(
            climb, {}, {toml: "rewrite"}), (None, None))
        self.assertEqual(adopt_references.effective_answer(
            climb, {}, {depth: "rewrite"}), ("rewrite", "policy"))
        answers = {toml: "retain", depth: "rewrite"}
        self.assertEqual(
            [(row["subject"], row["class"], row["recommended"],
              row["rewritten"], row["retained"])
             for row in adopt_references.policy_summary(refs, {}, answers)],
            [(toml, ".toml", "rewrite", 0, 1),
             (depth, ".toml/depth", None, 1, 0)])
        self.assertEqual(
            adopt_references.rewritten(refs, {}, answers),
            {TOOL_NEW + "/pyproject.toml": (
                text, text.replace("../../../", "../../../../"))})
        self.assertEqual(adopt_references.rewritten(
            refs, {}, {toml: "retain", depth: "retain"}), {})
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_references.py -k TextClimbTest`
Expected: ERROR — `module 'agent_tools.adopt_references' has no attribute 'split_climb'` and `plan_references() got an unexpected keyword argument 'depth_texts'`.

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/adopt_references.py`:

1. `Occurrence`: add `depth: bool = False` after `variable`; `occurrence_class` returns `klass + "/depth"` when `self.depth`, then the existing `/variable` rule. Its docstring names both suffixes and why neither collides with a file class (a file class holds no `/`).
2. A new section `# Depth` (between "Occurrences and shapes" and "Edits"), with `split_climb` and `climb_form`:
   - `split_climb(token)`: `prefix` is `"./"` when the token starts with `./`, else `""`; None unless `"/"` is in the token; over the rest after the prefix, `height` is the count of leading segments equal to `..` (split on `/`), None when 0; `rest` is the text after the last leading `..` verbatim (empty or starting with `/`); None when `rest.split("/")` holds a `..` segment (D11).
   - `climb_form(prefix, height, rest)`: None when `height < 1`, else `prefix + "/".join([".."] * height) + rest`.
3. Private path helpers (paths are `/`-joined, the root is `""`): `_depth_of(directory)` (segment count, 0 for `""`); `_landing(directory, height) -> (path, above)`: the directory `height` levels up when `height <= _depth_of(directory)` (`above` 0), else `("", height - _depth_of(directory))`; `_is_ancestor(ancestor, path)`: `ancestor == ""` or `path == ancestor` or `path.startswith(ancestor + "/")`.
4. `_depth_occurrences(path, text, base, sources, target, tree)`. `P`, `Q` are the directories of `path` and `target` (`rpartition("/")[0]`); `R` is `tree` when `path.startswith(tree + "/")`, else `P` (an `archive-history` tree is the file's own path, D4); `delta = _depth_of(Q) - _depth_of(P)`. For each token of `text` that `split_climb` reads, decide by this rule (full code because the order of the tests is the decision, D1/D3/D8):

   ```python
   def consider(start, end, height, rest, shift):
       """`rest` is the text climb's rest, or None for a Python chain;
       `shift(delta)` is the shifted form or None."""
       landing = _landing(P, height)
       if landing == _landing(Q, height):
           return None
       place, above = landing
       if not above and (place == R or not _is_ancestor(place, R)):
           return None
       moved_target = False
       if rest is not None and not above:
           segments = [s for s in (place + "/" + rest).split("/")
                       if s not in ("", ".")]
           base_target = "/".join(segments)
           if _is_ancestor(R, base_target):
               return None
           moved_target = _names_moved(base_target, base, sources)
       replacement = None
       if (above or _is_ancestor(place, Q)) and not moved_target:
           replacement = shift(delta)
       ...  # build the Occurrence
   ```

   The occurrence: `line` and `column` of `start` counted as `tokens` counts them (1-based, `\n` lines, columns in characters), `literal = text[start:end]`, answers `("rewrite", "retain")` when `replacement` is not None else `("retain",)`, `additions=()`, `shape=None`, `target`, `tree`, `variable=False`, `depth=True`. A text climb's `shift` is `lambda d: climb_form(prefix, height + d, rest)`. Climbs are produced in text order.
5. `plan_references(..., depth_texts=None)`: iterate `sorted(set(texts) | set(depth_texts or {}))`, the text being `texts[path]` when present, else `depth_texts[path]`; the token loop runs only when `path in texts`; then, when `path in depth_texts` and `tree is not None`, append `_depth_occurrences(...)`; a path enters `held` when it has any occurrence. The final sort by `(path, line, column)` is unchanged. Docstring: `depth_texts` is read by the depth reading alone, and only for a moved file.
6. The module docstring: name `split_climb` and `climb_form` in the grammar lists, and add a paragraph stating that a file the plan moves and that is in the depth read set is read a fourth time for climbs, whose occurrences belong to the `<tree>:<class>/depth` policy and offer `rewrite` (shift by the depth delta) and `retain`. Write the sentences from the implemented code; the Python chains arrive in Task 2 and the read set's derivation in Task 3, so this paragraph names neither yet.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_references.py`
Expected: PASS, every test (the new `TextClimbTest` and every existing class), no failures.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_references.py home/common/agent-skills/tests/test_adopt_references.py
launch-commit … -- -m "feat(adopt): read ../ climbs out of a moved tree (#380)"
```
