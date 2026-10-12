# Task 1: The variable reading, its carried form and the occurrence class

**Files:**
- Modify: `python/agent_tools/adopt_references.py`
- Test: `home/common/agent-skills/tests/test_adopt_references.py`

**Interfaces:**
- Consumes: the existing `tokens`, `split_token`, `split_pattern`, `successors`, `carried_form`, `_is_one_token`, `_names_moved`, `file_class`, `recommended_answer`, `GLOB_CHARACTERS`.
- Produces (Task 2 relies on these names):
  - `SHELL_CLASSES = (".sh", ".bash", ".zsh")`
  - `split_variable(token: str) -> tuple[str, str, str] | None` — `(variable, path, tail)`, `variable + path + tail == token`.
  - `variable_form(variable: str, successor: str, is_directory: bool, tail: str, single: bool) -> str | None`
  - `Occurrence.variable: bool = False` (new last field, defaulted), `Occurrence.occurrence_class -> str` (property), `Occurrence.policy` now `f"{tree}:{occurrence_class}"`.
  - `policy_summary` rows take `class` from `occurrence_class`, so a variable policy row has `class` `.sh/variable` and `recommended` null.

**Invariants:**
- A token the plain or the pattern reading makes an occurrence keeps exactly the occurrence it has at base (`variable` false, same answers, additions and replacement) (D6).
- The variable reading runs only for a file whose `file_class` of the **base path** is in `SHELL_CLASSES` (D7).
- A variable-joined occurrence never offers `extend` and has empty `additions`; it offers `rewrite` exactly when it has a single successor with a carried form, and always `retain` (D10).
- `occurrence_class` is `file_class(path)` for a literal occurrence and `file_class(path) + "/variable"` for a variable-joined one; the policy subject stays `<tree>:<occurrence_class>` and is None outside a moved file (D8, D13).
- An answer to `<tree>:.sh` never decides a variable-joined occurrence: `effective_answer` already looks the policy up by `occurrence.policy`, so no change there.

- [ ] **Step 1: Write the failing tests**

Append to `home/common/agent-skills/tests/test_adopt_references.py` (after `PolicyTest`, before the `git` helper):

```python
SHELL = "tools/run.sh"
MOVED_SH = ".claude/specs/run.sh"
SH, SH_VARIABLE = ".claude/specs:.sh", ".claude/specs:.sh/variable"
JOINED = 'cat ".claude/plans/y.md"\ncat "$root/.claude/plans/y.md"\n'


def shell_found(text, path=SHELL):
    return adopt_references.plan_references(
        {path: text}, PATHS + [path], MOVES, {}).occurrences


def shell_offers(text, path=SHELL):
    return [(o.literal, o.answers, o.additions, o.replacement, o.variable)
            for o in shell_found(text, path)]


def moved_shell():
    return adopt_references.plan_references(
        {MOVED_SH: JOINED}, PATHS + [MOVED_SH],
        MOVES + [(MOVED_SH, SPECS + "/run.sh")], {MOVED_SH: ".claude/specs"})


class VariableReadingTest(unittest.TestCase):
    """#376 D6-D8, D10, D13: `$name/` and `${name}/` in shell files."""

    def test_a_variable_prefix_splits_into_variable_path_and_tail(self):
        for token, expected in (
                ("$root/.claude/specs/x.md",
                 ("$root/", ".claude/specs/x.md", "")),
                ("${ROOT}/.claude/specs/x.md",
                 ("${ROOT}/", ".claude/specs/x.md", "")),
                ("${ROOT}/.claude/notes/$run/out",
                 ("${ROOT}/", ".claude/notes", "/$run/out")),
                ("$_a1/.claude/*.md", ("$_a1/", ".claude", "/*.md")),
                ("$root/", ("$root/", "", "")),
                ("$a/$b/.claude/specs", ("$a/", "", "$b/.claude/specs"))):
            with self.subTest(token=token):
                self.assertEqual(adopt_references.split_variable(token),
                                 expected)
                self.assertEqual("".join(expected), token)

    def test_unread_forms_are_not_a_variable_prefix(self):
        for token in ("$1/.claude/specs", "$9a/.claude", "${}/.claude",
                      "${name:-x}/.claude/specs", "${name%/*}/.claude",
                      "x$root/.claude/specs", "$root.d/.claude/specs",
                      "$(pwd)/.claude", ".claude/specs", "/.claude/specs"):
            with self.subTest(token=token):
                self.assertIsNone(adopt_references.split_variable(token))

    def test_the_carried_form_keeps_the_variable_and_the_tail(self):
        form = adopt_references.variable_form
        self.assertEqual(form("$root/", SPECS + "/x.md", False, "", True),
                         "$root/" + SPECS + "/x.md")
        self.assertEqual(form("${ROOT}/", SPECS, True, "/$run/out", True),
                         "${ROOT}/" + SPECS + "/$run/out")
        self.assertEqual(form("$root/", SPECS, True, "/", False),
                         "$root/" + SPECS + "/")
        self.assertEqual(form("$root/", SPECS + "/x.md", False, "/", False),
                         "$root/" + SPECS + "/x.md")
        for args in (("$root/", SPECS, True, "/x*", False),
                     ("$root/", "a b/x.md", False, "", True),
                     ("$root/", "a/$b", False, "", True)):
            with self.subTest(args=args):
                self.assertIsNone(form(*args))

    def test_a_variable_occurrence_offers_rewrite_and_retain_never_extend(self):
        self.assertEqual(shell_offers('cat "$root/.claude/specs/x.md"\n'), [
            ("$root/.claude/specs/x.md", ("rewrite", "retain"), (),
             "$root/" + SPECS + "/x.md", True)])
        self.assertEqual(shell_offers('cat "${ROOT}/.claude/plans/y.md"\n'), [
            ("${ROOT}/.claude/plans/y.md", ("rewrite", "retain"), (),
             "${ROOT}/" + PLANS + "/y.md", True)])
        # Alone on its line: the plain reading would offer `extend` here.
        self.assertEqual(shell_offers('"$root/.claude/specs/"\n'), [
            ("$root/.claude/specs/", ("rewrite", "retain"), (),
             "$root/" + SPECS + "/", True)])
        self.assertEqual(shell_offers('".claude/specs/"\n')[0][1],
                         ANSWERS_ALL)
        # An ancestor whose directory survives the moves: `retain` only.
        self.assertEqual(shell_offers('cd "$root/.claude"\n'), [
            ("$root/.claude", ("retain",), (), None, True)])

    def test_unread_forms_are_no_occurrence(self):
        for text in ('cat "$1/.claude/specs/x.md"\n',
                     'cat "x$root/.claude/specs/x.md"\n',
                     'cat "${root:-.}/.claude/specs/x.md"\n',
                     'cat "${root%/*}/.claude/specs/x.md"\n',
                     'cat "$a/$b/.claude/specs/x.md"\n',
                     'cat "$root.d/.claude/specs/x.md"\n'):
            with self.subTest(text=text):
                self.assertEqual(shell_found(text), ())

    def test_tokens_the_earlier_readings_take_are_unchanged(self):
        self.assertEqual(shell_offers(
            'cat "$(git rev-parse --show-toplevel)/.claude/specs/x.md"\n'), [
            ("/.claude/specs/x.md", ("rewrite", "retain"), (),
             "/" + SPECS + "/x.md", False)])
        self.assertEqual(shell_offers('cat ".claude/specs/x.md"\n'), [
            (".claude/specs/x.md", ("rewrite", "retain"), (),
             SPECS + "/x.md", False)])
        self.assertEqual(
            [o.variable for o in shell_found(
                r'grep "^\.claude/specs/x\.md"' + "\n")], [False])

    def test_only_the_shell_classes_are_read(self):
        text = 'cat "$root/.claude/specs/x.md"\n'
        for path in ("tools/run.sh", "tools/run.bash", "tools/run.zsh",
                     "tools/RUN.SH"):
            with self.subTest(path=path):
                self.assertEqual(
                    [o.variable for o in shell_found(text, path)], [True])
        for path in ("tools/run.py", "tools/run", "tools/run.yaml"):
            with self.subTest(path=path):
                self.assertEqual(shell_found(text, path), ())
        self.assertEqual(adopt_references.SHELL_CLASSES,
                         (".sh", ".bash", ".zsh"))

    def test_the_class_and_policy_of_a_variable_occurrence(self):
        self.assertEqual(
            [(o.subject, o.variable, o.occurrence_class, o.policy, o.target)
             for o in moved_shell().occurrences],
            [(MOVED_SH + ":1:6", False, ".sh", SH, SPECS + "/run.sh"),
             (MOVED_SH + ":2:6", True, ".sh/variable", SH_VARIABLE,
              SPECS + "/run.sh")])
        (unmoved,) = shell_found('cat "$root/.claude/plans/y.md"\n')
        self.assertEqual((unmoved.occurrence_class, unmoved.policy),
                         (".sh/variable", None))

    def test_policies_partition_literal_and_variable_occurrences(self):
        references = moved_shell()
        _, joined = references.occurrences
        self.assertEqual(adopt_references.effective_answer(
            joined, {}, {SH: "rewrite"}), (None, None))
        self.assertEqual(adopt_references.effective_answer(
            joined, {}, {SH_VARIABLE: "rewrite"}), ("rewrite", "policy"))
        row = {"tree": ".claude/specs", "files": 1, "occurrences": 1,
               "rewritable": 1, "rewritten": 0, "retained": 0,
               "extended": 0, "open": 0, "overridden": 0}
        self.assertEqual(
            adopt_references.policy_summary(
                references, {}, {SH: "rewrite", SH_VARIABLE: "retain"}),
            [{**row, "subject": SH, "class": ".sh", "recommended": "rewrite",
              "answer": "rewrite", "rewritten": 1},
             {**row, "subject": SH_VARIABLE, "class": ".sh/variable",
              "recommended": None, "answer": "retain", "retained": 1}])
        rewritten = adopt_references.rewritten
        self.assertEqual(
            rewritten(references, {}, {SH: "rewrite", SH_VARIABLE: "rewrite"}),
            {SPECS + "/run.sh": (JOINED, (
                f'cat "{PLANS}/y.md"\ncat "$root/{PLANS}/y.md"\n'))})
        self.assertEqual(
            rewritten(references, {}, {SH: "rewrite", SH_VARIABLE: "retain"}),
            {SPECS + "/run.sh": (JOINED, (
                f'cat "{PLANS}/y.md"\ncat "$root/.claude/plans/y.md"\n'))})
        self.assertEqual(
            rewritten(references, {}, {SH: "retain", SH_VARIABLE: "retain"}),
            {})
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_references.py -k VariableReadingTest`
Expected: FAIL/ERROR — `module 'agent_tools.adopt_references' has no attribute 'split_variable'` (and the occurrence tests fail with no `variable` attribute).

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/adopt_references.py`:

1. Constants beside `REWRITE_CLASSES`: `SHELL_CLASSES = (".sh", ".bash", ".zsh")` and a private `_VARIABLE_PREFIX = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\})/")`.
2. `split_variable(token)` after `split_pattern`: `None` unless `_VARIABLE_PREFIX.match(token)` matches at offset 0; `variable` is the match including its `/`; over the rest, the path is the longest leading run of `/`-separated segments that are non-empty and hold neither a `GLOB_CHARACTERS` character nor `$`; `tail` is the rest verbatim (the `split_token` loop, with `$` added to the stop condition).
3. `variable_form(variable, successor, is_directory, tail, single)` after `pattern_form`: the tail rule of `carried_form` (`single` → `tail`; else `tail` in `CARRIED_TAILS` → `tail if is_directory else ""`; else None); `form = variable + successor + carried`; None unless `_is_one_token(form)` and `split_variable(form)` is not None and its path equals `successor`.
4. `Occurrence`: add a last field `variable: bool = False`; add the property

   ```python
   @property
   def occurrence_class(self) -> str:
       """The file's class, or `<file class>/variable` for a variable-joined
       occurrence; a file class never holds `/`, so the two never collide."""
       klass = file_class(self.path)
       return klass + "/variable" if self.variable else klass
   ```

   and make `policy` return `f"{self.tree}:{self.occurrence_class}"` (docstring: `<tree>:<class>` with the occurrence class).
5. `_reading(token, base, sources, shell)` returns `(path, form, variable)` or None: the plain reading, then the pattern reading, unchanged and both with `variable` False; then, only when `shell` is true, `split_variable(token)` whose path `_names_moved`, with `form` built from `variable_form` and `variable` True. Update its docstring to name the third reading.
6. `_occurrence(..., shell)`: pass `shell` to `_reading`; offer `extend` only when the reading is not the variable one (the `shape`/`forms` condition otherwise unchanged); construct the `Occurrence` with `variable=variable`.
7. `plan_references`: compute `shell = file_class(path) in SHELL_CLASSES` per text (the base path) and pass it to `_occurrence`.
8. `policy_summary`: `klass = first.occurrence_class`.
9. The module docstring: the token grammar list names `split_variable` and the carried-form list `variable_form`; the reading paragraph says that, in a file of a shell class, a token neither reading makes an occurrence is read a third time as a `$name/` or `${name}/` prefix and a path (`split_variable`), whose occurrence offers `rewrite` and `retain` only and belongs to the `<tree>:<class>/variable` policy. Write those sentences from the implemented code.

Run `rg -n "file_class\(" python/agent_tools` afterwards: the only remaining class derivations from an occurrence's path outside `occurrence_class` are in `adopt_planning.reference_questions` (Task 2 changes it) — leave it.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_references.py`
Expected: PASS, every test (the new `VariableReadingTest` and the unchanged `TokenTest`, `PatternTest`, `OccurrenceTest`, `EditTest`, `PolicyTest`, `DerivationTest`), no failures.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py -k ReferencePolicyPlanTest -k PathReferencePlanTest` (timeout 1800 s)
Expected: PASS — no existing plan row changes.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_references.py home/common/agent-skills/tests/test_adopt_references.py
launch-commit … -- -m "feat(adopt): read variable-joined paths in shell files (#376)"
```
