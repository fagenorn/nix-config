# Task 1: Pattern spellings — the second reading of a token and its carried form

Spec rows: D6 (the reading), D9 (the prefilter is not touched). Read the plan root's Global Constraints first.

**Files:**
- Modify: `python/agent_tools/adopt_references.py`
- Test: `home/common/agent-skills/tests/test_adopt_references.py`

**Interfaces:**
- Consumes: nothing from another task. In the module at base: `tokens`, `split_token(token) -> (prefix, path, tail)`, `carried_form(prefix, successor, is_directory, tail, single) -> str | None`, `successors`, `_shape`, `_is_quoted`, `_occurrence`, `GLOB_CHARACTERS`, `CARRIED_TAILS`.
- Produces (module-level, importable):
  - `split_pattern(token: str) -> tuple[str, str, str, str, str] | None` — `(anchor, escape, prefix, path, tail)`, or `None` when the token neither starts with `^` nor holds `\.`.
  - `pattern_form(anchor: str, escape: str, prefix: str, successor: str, is_directory: bool, tail: str, single: bool) -> str | None`.
  - `_occurrence` reads a token the plain reading rejects through `split_pattern`. `Occurrence`, `plan_references`, `summary`, `rewritten` and `derive_references` keep their base signatures in this task.

**Invariants:**
- A token for which the plain reading yields an occurrence produces exactly the occurrence it produces at base (same `answers`, `additions`, `replacement`, `shape`): the pattern reading is never consulted for it.
- `split_pattern` is total and pure; when it returns a tuple, `anchor + prefix + <the raw text the path was decoded from> + tail == token`.
- A pattern form is returned only if `split_pattern(form)` returns the successor as its path: no form is ever emitted that this module would not read back.
- `derive_references` and its `git grep` arguments are unchanged (D9).

In this task's test code a token is written as a Python raw string: `r"^\\.claude/"` is the eleven characters `^`, `\`, `\`, `.claude/`, which is how a TOML or JSON file spells the regex `^\.claude/`.

- [ ] **Step 1: Write the failing tests**

Add to `home/common/agent-skills/tests/test_adopt_references.py`, after `ANSWERS_ALL`:

```python
PATTERN_EXCLUDE = (r'EXCLUDE = ["^var/", "^\\.claude/", "^\\.worktrees/"]'
                   + "\n")
```

and, after `class SuccessorTest`, this class:

```python
class PatternTest(unittest.TestCase):
    """#372 D6: a token the plain reading rejects is read as a pattern."""

    def test_a_pattern_splits_into_anchor_escape_prefix_path_and_tail(self):
        for token, expected in (
                (r"^\\.claude/", ("^", r"\\.", "", ".claude", "/")),
                (r"^\.claude/specs/x\.md",
                 ("^", r"\.", "", ".claude/specs/x.md", "")),
                (r"\.claude/specs", ("", r"\.", "", ".claude/specs", "")),
                (r"^/\.claude/", ("^", r"\.", "/", ".claude", "/")),
                ("^.claude/specs/.*", ("^", "", "", ".claude/specs", "/.*")),
                (r"^\.claude/[a-z]+/",
                 ("^", r"\.", "", ".claude", "/[a-z]+/")),
                (r"^\.claude\b/x", ("^", r"\.", "", "", r"\.claude\b/x")),
                (r"^\\.claude/a\.b", ("^", r"\\.", "", ".claude", r"/a\.b")),
                ("^", ("^", "", "", "", "")),
                (".claude/specs", None),
                ("docs/guide.txt", None)):
            with self.subTest(token=token):
                self.assertEqual(adopt_references.split_pattern(token),
                                 expected)

    def test_pattern_forms_keep_anchor_escape_and_tail(self):
        form = adopt_references.pattern_form
        self.assertEqual(form("^", r"\\.", "", SPECS, True, "/", False),
                         r"^\\.agents/artifacts/specs/")
        self.assertEqual(
            form("^", r"\.", "", SPECS + "/x.md", False, "", True),
            r"^\.agents/artifacts/specs/x\.md")
        self.assertEqual(form("^", "", "/", SPECS, True, "/.*", True),
                         "^/" + SPECS + "/.*")
        self.assertEqual(form("", r"\.", "", "new/x.json", False, "/", False),
                         r"new/x\.json")
        # A tail that is not carried for a path with several successors.
        self.assertIsNone(form("^", r"\.", "", SPECS, True, "/.*", False))
        # A successor outside letters, digits, `_`, `-`, `.` and `/`.
        self.assertIsNone(form("^", r"\.", "", "new/x+y.md", False, "", True))
        # `new/x` holds neither `^` nor `\.`: it would not read back.
        self.assertIsNone(form("", r"\.", "", "new/x", True, "", True))

    def test_a_pattern_spelling_is_an_occurrence_with_pattern_forms(self):
        for text, expected in (
                (PATTERN_EXCLUDE,
                 [(r"^\\.claude/", ("extend", "retain"),
                   (r"^\\.agents/artifacts/plans/",
                    r"^\\.agents/artifacts/specs/"), None)]),
                (r'X = "^\.claude/specs/x\.md"' + "\n",
                 [(r"^\.claude/specs/x\.md", ("rewrite", "retain"), (),
                   r"^\.agents/artifacts/specs/x\.md")]),
                (r'"\.claude/specs/"' + "\n",
                 [(r"\.claude/specs/", ANSWERS_ALL,
                   (r"\.agents/artifacts/specs/",),
                   r"\.agents/artifacts/specs/")]),
                ('"^.claude/plans/y.md"\n',
                 [("^.claude/plans/y.md", ANSWERS_ALL,
                   ("^" + PLANS + "/y.md",), "^" + PLANS + "/y.md")]),
                (r"^\.claude/specs/.*  @team" + "\n",
                 [(r"^\.claude/specs/.*", ("rewrite", "retain"), (),
                   r"^\.agents/artifacts/specs/.*")])):
            with self.subTest(text=text):
                self.assertEqual(offers(text), expected)

    def test_a_pattern_naming_nothing_moved_is_no_occurrence(self):
        for text in (r'"^\.claude/specs$"', '"^var/"', r'"^\.worktrees/"',
                     r"x = ^\.claude", r'"^docs/guide\.txt"',
                     r'"^\.claude\b/"', r'"^./\.claude/"'):
            with self.subTest(text=text):
                self.assertEqual(found(text + "\n"), ())

    def test_the_plain_reading_decides_when_it_yields_an_occurrence(self):
        paths = ["^gen/a.md", "gen/a.md", "tools/check.py"]
        moves = [("^gen/a.md", "out/a.md"), ("gen/a.md", "other/a.md")]
        self.assertEqual(
            offers('x = "^gen/a.md"\n', paths=paths, moves=moves),
            [("^gen/a.md", ("rewrite", "retain"), (), "out/a.md")])

    def test_a_successor_with_no_pattern_form_offers_retain_only(self):
        moves = [(".claude/specs/x.md", SPECS + "/x+y.md")] + MOVES[1:]
        self.assertEqual(
            offers(r'x = "^\.claude/specs/x\.md"' + "\n", moves=moves),
            [(r"^\.claude/specs/x\.md", ("retain",), (), None)])

    def test_answers_edit_a_pattern_spelling(self):
        self.assertEqual(edit(PATTERN_EXCLUDE, "extend"), (
            r'EXCLUDE = ["^var/", "^\\.claude/", '
            r'"^\\.agents/artifacts/plans/", "^\\.agents/artifacts/specs/", '
            r'"^\\.worktrees/"]' + "\n"))
        self.assertEqual(edit(r'X = "^\.claude/specs/x\.md"' + "\n",
                              "rewrite"),
                         r'X = "^\.agents/artifacts/specs/x\.md"' + "\n")
```

`found`, `offers`, `edit`, `PATHS`, `MOVES`, `PLANS`, `SPECS` and `ANSWERS_ALL` are the helpers and constants already at the top of that file; do not change them in this task.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_references.py -k PatternTest`
Expected: FAIL/ERROR in all seven cases — `AttributeError: module 'agent_tools.adopt_references' has no attribute 'split_pattern'` (and `pattern_form`), and `[] != [...]` for the occurrence and edit cases.

- [ ] **Step 3: Implement the pattern reading**

In `python/agent_tools/adopt_references.py`:

```python
def split_pattern(token: str) -> tuple[str, str, str, str, str] | None:
    """`(anchor, escape, prefix, path, tail)` of a pattern spelling, or None."""


def pattern_form(anchor: str, escape: str, prefix: str, successor: str,
                 is_directory: bool, tail: str, single: bool) -> str | None:
    """The pattern spelling that keeps anchor, escape and tail on `successor`."""
```

`split_pattern`, in this order:

1. Return `None` unless the token starts with `^` or contains the two characters `\.`.
2. `anchor` is `"^"` when the token starts with `^`, else `""`; exactly one `^` is consumed.
3. `escape` is the three characters `\\.` (two backslashes and a dot) when the token contains them, else the two characters `\.` when it contains them, else `""`. It is chosen once for the whole token.
4. After the anchor, `prefix` is `"/"` when the remainder starts with `/`, else `""`. `./` is not a pattern prefix (the spec puts it out of scope), so `^./x` has prefix `""` and a first segment `.`.
5. Split what follows the prefix on `/`. Decode each segment by replacing every `escape` with `.` (no replacement when `escape` is `""`). The path is the longest leading run of decoded segments that are non-empty, hold no character of `GLOB_CHARACTERS` and hold no backslash, joined with `/`. A segment that still holds a backslash after decoding (`\b`, or a `\.` in a token whose escape is `\\.`) ends the run.
6. `tail` is the rest of the token after the raw segments the path was decoded from, verbatim (it starts with `/` or is empty, or is the whole remainder when the path is empty).

`pattern_form`, in this order:

1. Return `None` unless `successor` consists only of ASCII letters, digits, `_`, `-`, `.` and `/` (a full match).
2. Apply the rule `carried_form` applies: with `single`, the form is `anchor + prefix + encoded + tail`; otherwise it exists only for a `tail` in `CARRIED_TAILS` and is `anchor + prefix + encoded + (tail if is_directory else "")`; else return `None`. `encoded` is `successor` with every `.` replaced by `escape`, or `successor` itself when `escape` is `""`.
3. Return `None` unless the form is exactly one whole token (`tokens(form)` yields one token spanning it, as `carried_form` checks).
4. Return the form only when `split_pattern(form)` is not `None` and its fourth member equals `successor`; else `None`.

`_occurrence` keeps its first check (a token with no `/` that is not a whole quoted string is no occurrence) and then tries two readings in order. A reading *qualifies* when its path is non-empty, names a file or directory of `base`, and some move source is that path or lies under it — the two conditions the function applies at base.

1. The plain reading: `split_token(token.text)`. When it qualifies, the forms are `carried_form(prefix, successor, is_directory, tail, single)` per successor, exactly as at base.
2. Only when the plain reading does not qualify and `split_pattern(token.text)` is not `None`: when the pattern's path qualifies, the forms are `pattern_form(anchor, escape, prefix, successor, is_directory, tail, single)` per successor.
3. Neither qualifies: return `None`.

Everything after the forms (the shape, which answers are offered, `additions`, `replacement`, the constructed `Occurrence`) is the base code, fed whichever reading qualified. `_edit` and `rewritten` are not changed: they splice the forms the occurrence carries.

Update the module docstring's list of what the grammar provides to name `split_pattern` and `pattern_form` and to say, from the implemented code, when the second reading applies. Do not add a sentence about moved files or policies: later tasks own those.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_references.py`
Expected: PASS, every case of the file (the base cases unchanged, plus the seven `PatternTest` cases), no warnings.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py -k PathReferencePlanTest` (timeout 1800 s)
Expected: PASS — the issue 350 plan cases see the same rows as at base.

Scope gate: `git diff --stat 32807f90d4a4 -- python/agent_tools home/common/agent-skills/tests` lists exactly `python/agent_tools/adopt_references.py` and `home/common/agent-skills/tests/test_adopt_references.py`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_references.py home/common/agent-skills/tests/test_adopt_references.py
git commit -m "feat(adopt): read regex-form spellings of a moved path (#372)"
```
