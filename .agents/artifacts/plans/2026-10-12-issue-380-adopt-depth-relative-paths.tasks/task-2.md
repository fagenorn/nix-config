# Task 2: Python parent-count chains

**Files:**
- Modify: `python/agent_tools/adopt_references.py`
- Test: `home/common/agent-skills/tests/test_adopt_references.py`

**Interfaces:**
- Consumes (Task 1): `Occurrence.depth`, `_depth_occurrences(path, text, base, sources, target, tree)` and its per-climb decision `consider(start, end, height, rest, shift)` (`rest` None for a chain), `_landing`, `_is_ancestor`, `plan_references(..., depth_texts=...)`; the test helpers `TOOL`, `TOOL_NEW`, `NOTES`, `DEPTH_PATHS`, `DEPTH_MOVES`, `DEPTH_TREES`, `depth_found` that Task 1 added to the test file.
- Produces (Task 3 relies on these names):
  - `python_climbs(text: str) -> list[tuple[int, int, int]]` — `(start, end, height)` of every anchored chain's span, sorted by `start`; `text[start:end]` is the chain after its anchor.
  - `shift_chain(chain: str, delta: int) -> str | None`.
  - `_depth_occurrences(path, text, base, sources, target, tree, taken)` — `taken` is the occurrences the other readings made in the same file.

**Invariants:**
- Chains are read only in a file whose **base path** has class `.py` (D2).
- Anchors: direct `Path(__file__)` / `pathlib.Path(__file__)`, not preceded by an identifier character or `.`, optionally followed by one `.resolve()` or `.absolute()` (offset −1); a name bound at column 0 by `NAME = <direct>` or `NAME = <direct>.parent`, optional `: Path`/`: pathlib.Path` annotation, trailing comment and `\r\n` line end, and rebound nowhere else in the file at any indentation — plain, annotated, augmented or `:=` assignment, `for`/`as`/`del`/`global`/`nonlocal`, or a keyword argument of that name (offset −1 or 0) (D13); a use is the name preceded by neither an identifier character nor `.` and not followed by one (D2).
- A chain is zero or more `.parent` then at most one `.parents[N]` (decimal literal), at least one of them, no whitespace; height is the offset plus one per `.parent` plus `N + 1`; a chain directly followed by `.parent` (which also covers `.parents`) is not read (D2, D11).
- `shift_chain`: with `.parents[N]`, `.parents[N + delta]` when `N + delta >= 0`, the `.parent`s kept; with `.parent`s only, `p + delta` of them when `p + delta >= 1`; else None (spec, The rewrite).
- A chain whose span overlaps the span of a `taken` occurrence, or of a text climb this call accepted, is dropped (D11, D12). Text climbs are unaffected.

- [ ] **Step 1: Write the failing tests**

Insert into `home/common/agent-skills/tests/test_adopt_references.py` after Task 1's `TextClimbTest`, before the `def git(` helper:

```python
RUN = TOOL + "/run.py"
BOUND = "HERE = Path(__file__).resolve().parent\n"


def chains(text, **kwargs):
    return [(o.subject, o.literal, o.answers, o.replacement)
            for o in depth_found({RUN: text}, **kwargs)]


def heights(text):
    return [height for _, _, height in adopt_references.python_climbs(text)]


class PythonClimbTest(unittest.TestCase):
    """#380 D2: parent-count chains anchored at the file's own location."""

    def test_anchored_chains_and_their_heights(self):
        for text, expected in (
                ("R = Path(__file__).parents[3]\n", [3]),
                ("R = pathlib.Path(__file__).resolve().parent.parent\n", [1]),
                ("R = Path(__file__).absolute().parent.parents[1]\n", [2]),
                (BOUND + "R = HERE.parents[2]\n", [0, 3]),
                ("F: Path = Path(__file__)  # me\nR = F.parent.parent\n", [1]),
                ("R = Path(__file__).parents[2].joinpath('x')\n", [2])):
            with self.subTest(text=text):
                self.assertEqual(heights(text), expected)
        for text in ("R = os.path.dirname(os.path.dirname(__file__))\n",
                     "R = Path.cwd().parents[2]\n",
                     "R = Path(__file__).parents[i]\n",
                     "R = Path(__file__).parents[1].parent\n",
                     "R = Path(__file__).parent.parents[i]\n",
                     "R = Path(__file__) .parent\n",
                     "R = MyPath(__file__).parent\n",
                     "R = x.Path(__file__).parent\n",
                     "R = Path(__file__)\n"):
            with self.subTest(text=text):
                self.assertEqual(heights(text), [])

    def test_only_a_name_never_rebound_is_followed(self):
        for text, expected in (
                ("HERE = Path(__file__).parent\nHERE = Path('.')\n"
                 "R = HERE.parents[2]\n", [0]),
                (BOUND + 'HERE /= "/fixed/a/b/c"\nROOT = HERE.parents[2]\n',
                 [0]),
                (BOUND + "for HERE in xs:\n    pass\nR = HERE.parents[2]\n",
                 [0]),
                (BOUND + "def f():\n    HERE = 1\nR = HERE.parents[2]\n",
                 [0]),
                ("def f():\n    HERE = Path(__file__).parent\n"
                 "    return HERE.parents[2]\n", [0]),
                (BOUND + "ROOT = HERE.parents[2]\nX = ROOT.parent\n", [0, 3]),
                ("UP = Path(__file__).parents[2]\nX = UP.parent\n", [2]),
                (BOUND + "R = self.HERE.parents[2]\nS = MYHERE.parent\n",
                 [0])):
            with self.subTest(text=text):
                self.assertEqual(heights(text), expected)

    def test_a_chain_to_the_root_is_rewritten(self):
        text = (BOUND + "ROOT = HERE.parents[2]\n"
                "UP = Path(__file__).parent.parent.parent.parent\n")
        self.assertEqual(chains(text), [
            (RUN + ":2:12", ".parents[2]", ("rewrite", "retain"),
             ".parents[3]"),
            (RUN + ":3:20", ".parent.parent.parent.parent",
             ("rewrite", "retain"), ".parent.parent.parent.parent.parent")])

    def test_crlf_line_ends_read_like_lf(self):
        crlf = (BOUND + "ROOT = HERE.parents[2]\n").replace("\n", "\r\n")
        self.assertEqual(heights(crlf), [0, 3])
        self.assertEqual(chains(crlf), [
            (RUN + ":2:12", ".parents[2]", ("rewrite", "retain"),
             ".parents[3]")])
        refs = adopt_references.plan_references(
            {RUN: crlf}, DEPTH_PATHS, DEPTH_MOVES, DEPTH_TREES,
            depth_texts={RUN: crlf})
        self.assertEqual(
            adopt_references.rewritten(
                refs, {}, {NOTES + ":.py/depth": "rewrite"}),
            {TOOL_NEW + "/run.py": (
                crlf, crlf.replace(".parents[2]", ".parents[3]"))})

    def test_chains_inside_the_tree_are_not_surfaced(self):
        self.assertEqual(chains(BOUND + "NOTES = HERE.parent\n"
                                "T = Path(__file__).parents[1]\n"), [])

    def test_a_landing_point_only_above_the_old_directory_is_retained(self):
        self.assertEqual(chains("C = Path(__file__).parents[2]\n"), [
            (RUN + ":1:19", ".parents[2]", ("retain",), None)])

    def test_a_shallower_move_that_cannot_climb_less_is_retained(self):
        text = (BOUND + "R = HERE.parents[2]\n"
                "S = Path(__file__).parent.parent.parent.parent\n")
        self.assertEqual(chains(text, moves=[(RUN, "run.py")]), [
            (RUN + ":2:9", ".parents[2]", ("retain",), None),
            (RUN + ":3:19", ".parent.parent.parent.parent",
             ("rewrite", "retain"), ".parent")])

    def test_only_python_files_are_read_for_chains(self):
        path = TOOL + "/run.sh"
        self.assertEqual(depth_found(
            {path: "R = Path(__file__).parents[2]\n"},
            moves=DEPTH_MOVES + [(path, TOOL_NEW + "/run.sh")],
            trees={**DEPTH_TREES, path: NOTES},
            paths=DEPTH_PATHS + [path]), ())

    def test_a_chain_overlapping_a_token_occurrence_is_dropped(self):
        text = ("HERE = Path(__file__).parent\n"
                "Y = .claude/specs/x.md+HERE.parents[2]\n")
        self.assertEqual(
            [(o.subject, o.depth)
             for o in depth_found({RUN: text}, scanned={RUN: text})],
            [(RUN + ":2:5", False)])
        self.assertEqual([o.subject for o in depth_found({RUN: text})],
                         [RUN + ":2:28"])

    def test_a_chain_inside_a_text_climb_is_dropped(self):
        text = BOUND + 'S = "../../../HERE.parents[2]"\n'
        self.assertEqual(chains(text), [
            (RUN + ":2:6", "../../../HERE.parents[2]", ("rewrite", "retain"),
             "../../../../HERE.parents[2]")])
        refs = adopt_references.plan_references(
            {RUN: text}, DEPTH_PATHS, DEPTH_MOVES, DEPTH_TREES,
            depth_texts={RUN: text})
        self.assertEqual(
            adopt_references.rewritten(
                refs, {}, {NOTES + ":.py/depth": "rewrite"}),
            {TOOL_NEW + "/run.py": (
                text, text.replace("../../../", "../../../../"))})
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_references.py -k PythonClimbTest`
Expected: ERROR/FAIL — `module 'agent_tools.adopt_references' has no attribute 'python_climbs'`, and the `chains` cases find no occurrence.

- [ ] **Step 3: Write the minimal implementation**

In the `# Depth` section of `python/agent_tools/adopt_references.py`, the grammar as compiled patterns (exact, D2):

```python
_FILE_ANCHOR = (r"(?:pathlib\.)?Path\(__file__\)"
                r"(?:\.resolve\(\)|\.absolute\(\))?")
_DIRECT_ANCHOR = re.compile(r"(?<![\w.])" + _FILE_ANCHOR)
_CHAIN = re.compile(r"((?:\.parent(?!\w))*)(?:\.parents\[(\d+)\])?")
_BINDING = re.compile(
    r"^([A-Za-z_]\w*)[ \t]*(?::[ \t]*(?:pathlib\.)?Path[ \t]*)?=[ \t]*"
    + _FILE_ANCHOR + r"(\.parent)?[ \t]*(?:#[^\r\n]*)?\r?$", re.MULTILINE)
```

`\r?` keeps a CRLF file's binding (its `\r` survives the decode); every pattern runs over the original text, so offsets and the bytes `rewrite` splices are unchanged (D13).

1. A private `_chain_at(text, at) -> tuple[int, int, int | None] | None`: `(end, parents, index)` of `_CHAIN.match(text, at)`; None when the match is empty or `text.startswith(".parent", end)`.
2. `python_climbs(text)`: every `_DIRECT_ANCHOR` match whose end starts a chain, at offset −1; then every `_BINDING` match whose name is rebound nowhere else (a private `_rebinds(name, text)`, the count of `(?<![\w.])NAME[ \t]*(?:(?::[^=\n]*)?=(?!=)|(?:[-+*/%@&|^:]|//|\*\*|>>|<<)=)` matches plus `(?<![\w.])(?:for|as|del|global|nonlocal)[ \t]+NAME(?!\w)` matches over the whole text, `NAME` being `re.escape(name)`, equals 1 — the binding itself; D13), offset 0 when the binding has `.parent` (group 2) else −1, and every use `re.finditer(r"(?<![\w.])" + re.escape(name) + r"(?!\w)", text)` whose end starts a chain. Height: `offset + parents + (0 if index is None else index + 1)`. Return sorted by start. A binding's own right-hand side is found by the direct pass with height −1 or 0, so it never climbs out of `P`.
3. `shift_chain(chain, delta)` per the invariant; parse `chain` with `_CHAIN.fullmatch`.
4. `_depth_occurrences` gains `taken`; after the text climbs, when `file_class(path) == ".py"`, call `consider(start, end, height, None, lambda d: shift_chain(text[start:end], d))` for each of `python_climbs(text)`, skipping a span with `start < o.end and o.start < end` for some `o` in `taken` or among the text-climb occurrences this call already accepted (D12; otherwise `rewritten`'s splice lets the whole-token climb overwrite the chain's edit). `plan_references` collects the token occurrences of the file first and passes them as `taken`.
5. The module docstring's depth paragraph gains the Python chain: its anchors, its `.parent`/`.parents[N]` grammar, the `.py` class, and what is not read (`os.path`, `Path.cwd()`, names chained from other names, function-local bindings, a name rebound anywhere in the file, a chain overlapping a text climb or another reading's occurrence, whitespace in a chain, a non-literal index, a chain continued after `.parents[N]`). Write it from the implemented code.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_references.py`
Expected: PASS, every test (`PythonClimbTest`, `TextClimbTest` and every existing class), no failures.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_references.py home/common/agent-skills/tests/test_adopt_references.py
launch-commit … -- -m "feat(adopt): read Python parent-count climbs (#380)"
```
