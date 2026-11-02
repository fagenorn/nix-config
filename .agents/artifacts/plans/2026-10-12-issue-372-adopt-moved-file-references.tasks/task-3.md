# Task 3: Moved files are read, each occurrence has a target and a policy, and the edit lands at the destination

Spec rows: D1, D8 (scan and write), D2, D3, D4 (the pure policy core), D5 (the three row members), D10 (the `trees` mapping, one precedence function, the class of a file name). Read the plan root's Global Constraints first.

This task finishes `adopt_references` and makes the plan write a moved file at its destination. It does not add the `reference-policy` question or answer: until Task 4, `compose_plan` passes no policy answers, so an occurrence in a moved file opens its own `path-reference` question.

**Files:**
- Modify: `python/agent_tools/adopt_references.py`
- Modify: `python/agent_tools/adopt_planning.py` (`apply_answers`, `check_reference_writes`, `build_operations`)
- Modify: `python/agent_tools/adopt_project.py` (`compose_plan`)
- Test: `home/common/agent-skills/tests/test_adopt_references.py`
- Test: `home/common/agent-skills/tests/test_adopt_project.py`
- Test: `home/common/agent-skills/tests/test_adopt_apply.py`

**Interfaces:**
- Consumes: Task 1's `_occurrence` (unchanged here apart from the two new fields it fills). `Candidates.groups` (`{group: {"action", "target", "members": [(path, object_id), ...]}}`) and `Candidates.moves` from `adopt_inspection`.
- Produces, in `adopt_references` (exact names; Task 4 calls them):
  - `POLICY_ANSWERS = ("rewrite", "retain")`.
  - `file_class(path: str) -> str`.
  - `recommended_answer(file_class: str) -> str | None`.
  - `Occurrence` gains two fields after `shape`, in this order: `target: str`, `tree: str | None`; and a property `policy -> str | None`.
  - `plan_references(texts: dict[str, str], paths: Iterable[str], moves: Iterable[tuple[str, str]], trees: Mapping[str, str]) -> References`.
  - `derive_references(root: Path, revision: str, moves: Iterable[tuple[str, str]], excluded: Iterable[str], trees: Mapping[str, str]) -> References`.
  - `effective_answer(occurrence: Occurrence, answers: Mapping[str, str], policies: Mapping[str, str]) -> tuple[str | None, str | None]`.
  - `summary(references: References, answers: Mapping[str, str], policies: Mapping[str, str]) -> list[dict]`.
  - `policy_summary(references: References, answers: Mapping[str, str], policies: Mapping[str, str]) -> list[dict]`.
  - `rewritten(references: References, answers: Mapping[str, str], policies: Mapping[str, str]) -> dict[str, tuple[str, str]]`, keyed by **target**.
  
  `answers` is always `{occurrence subject: value}` and `policies` `{policy subject: value}`.
- Produces, in `adopt_planning`: `check_reference_writes(changes, reference_targets)` admits one `git-mv` onto a target; `apply_answers` keeps its signature and return type.

**Invariants:**
- A file the plan does not move yields the occurrences it yields at base; its `target` is its own path, its `tree` and `policy` are `None`.
- An occurrence's `path` and `subject` are the file's path in the base tree, moved or not (D1).
- Every occurrence in a moved file has exactly one policy subject, `<tree>:<class>`; a moved file with no entry in `trees` raises `ValueError` (D10).
- The record-home clause tests the base path (D8): a file under `.agents/artifacts/` or `.agents/knowledge/archive/` at the base revision is never read.
- `effective_answer` is the only place precedence is decided; `summary`, `policy_summary` and `rewritten` call it.
- `rewritten` edits base text by base offsets and never returns a file whose text is unchanged.
- `References.texts` stays keyed by base path.

- [ ] **Step 1: Write the failing unit tests**

In `home/common/agent-skills/tests/test_adopt_references.py`:

(a) Thread the new arguments through the existing helpers and cases, changing nothing else in them:

- `found`: `adopt_references.plan_references({"tools/check.py": text}, paths, moves, {}).occurrences`.
- `edit`: `plan_references({"tools/check.py": text}, PATHS, MOVES, {})` and `adopt_references.rewritten(references, chosen, {})`.
- `OccurrenceTest.test_the_motivating_tuple_is_one_occurrence`: the expected value becomes `adopt_references.Occurrence("tools/check.py", 1, 29, 28, 36, ".claude/", ("extend", "retain"), (PLANS + "/", SPECS + "/"), None, "quoted", "tools/check.py", None)`.
- `EditTest.test_an_occurrence_outside_the_closed_sets_raises`: `plan_references(..., PATHS, MOVES, {})` and `adopt_references.rewritten(broken, {occurrence.subject: answer}, {})`.
- `EditTest.test_the_summary_rows`: `plan_references(..., PATHS, MOVES, {})`; `row` gains `"target": "tools/check.py", "policy": None, "decided_by": None`; both `summary` calls gain a third argument `{}`; the answered expectation becomes `[{**row, "answer": "extend", "decided_by": "occurrence"}]`.
- `DerivationTest`: add the class attribute

  ```python
    TREES = {".claude/specs/x.md": ".claude/specs",
             ".claude/specs/data.txt": ".claude/specs",
             ".claude/plans/y.md": ".claude/plans"}
  ```

  `subjects` calls `derive_references(self.root, "HEAD", self.MOVES, excluded, self.TREES)`; `test_no_moves_is_no_reference` calls `derive_references(self.root, "HEAD", [], [], {})`. The moved text file `.claude/specs/data.txt` is now read, so in `test_only_scanned_files_yield_occurrences` the two expected lists become `[".claude/keep.json:1:10", ".claude/specs/data.txt:1:1", "tools/check.py:1:29"]` and `[".claude/keep.json:1:10", ".claude/specs/data.txt:1:1", "config/owners.txt:1:1", "tools/check.py:1:29"]`, and in `test_forced_colour_does_not_hide_the_candidates` the expected list becomes the first of those. The two record-home files of `FILES` stay absent from both lists: that is D8's pin.

(b) Add after `ANSWERS_ALL` (and Task 1's `PATTERN_EXCLUDE`):

```python
POLICY_TEXTS = {
    ".claude/specs/tool.py":
        'SPEC = ".claude/specs/x.md"\nSKIP = (".claude",)\n',
    ".claude/specs/sub/data.json": '{"plan": ".claude/plans/y.md"}\n',
    "tools/check.py": EXEMPT,
}
POLICY_PATHS = PATHS + [".claude/specs/tool.py", ".claude/specs/sub/data.json"]
POLICY_MOVES = MOVES + [
    (".claude/specs/tool.py", SPECS + "/tool.py"),
    (".claude/specs/sub/data.json", SPECS + "/sub/data.json")]
POLICY_TREES = {
    source: (".out-of-scope" if source.startswith(".out-of-scope/")
             else "/".join(source.split("/")[:2]))
    for source, _ in POLICY_MOVES}
PY, JSON = ".claude/specs:.py", ".claude/specs:.json"
```

(c) Add this class after `class EditTest`:

```python
class PolicyTest(unittest.TestCase):
    """#372 D2-D5: targets, policy subjects, precedence, counts and edits."""

    def references(self):
        return adopt_references.plan_references(
            POLICY_TEXTS, POLICY_PATHS, POLICY_MOVES, POLICY_TREES)

    def policy_row(self, subject, recommended, occurrences, **changed):
        tree, _, file_class = subject.partition(":")
        return {"subject": subject, "tree": tree, "class": file_class,
                "recommended": recommended, "answer": None, "files": 1,
                "occurrences": occurrences, "rewritable": 1, "rewritten": 0,
                "retained": 0, "extended": 0, "open": occurrences,
                "overridden": 0, **changed}

    def test_the_class_of_a_file_name(self):
        for path, expected in (("a/b.py", ".py"), ("a/B.PY", ".py"),
                               ("a.tar.gz", ".gz"), ("a/.config.json", ".json"),
                               ("Makefile", "-"), (".envrc", "-"),
                               ("a.d/run", "-"), ("notes.", "-")):
            with self.subTest(path=path):
                self.assertEqual(adopt_references.file_class(path), expected)

    def test_the_recommendation_table_is_closed(self):
        recommended = adopt_references.recommended_answer
        for file_class in (".py", ".sh", ".bash", ".zsh", ".nix", ".yaml",
                           ".yml", ".toml", ".js", ".mjs", ".cjs", ".ts"):
            self.assertEqual(recommended(file_class), "rewrite", file_class)
        for file_class in (".json", ".jsonl", ".ndjson", ".csv", ".tsv",
                           ".txt", ".log"):
            self.assertEqual(recommended(file_class), "retain", file_class)
        for file_class in ("-", ".md", ".cfg", ".lock", ""):
            self.assertIsNone(recommended(file_class), file_class)
        self.assertEqual(adopt_references.POLICY_ANSWERS,
                         ("rewrite", "retain"))

    def test_targets_and_policy_subjects(self):
        self.assertEqual(
            [(o.subject, o.target, o.tree, o.policy)
             for o in self.references().occurrences],
            [(".claude/specs/sub/data.json:1:11", SPECS + "/sub/data.json",
              ".claude/specs", JSON),
             (".claude/specs/tool.py:1:9", SPECS + "/tool.py",
              ".claude/specs", PY),
             (".claude/specs/tool.py:2:10", SPECS + "/tool.py",
              ".claude/specs", PY),
             ("tools/check.py:1:29", "tools/check.py", None, None)])

    def test_a_moved_file_without_a_tree_raises(self):
        with self.assertRaises(ValueError):
            adopt_references.plan_references(
                POLICY_TEXTS, POLICY_PATHS, POLICY_MOVES, {})

    def test_effective_answers(self):
        data, spec, skip, exempt = self.references().occurrences
        self.assertEqual((spec.answers, skip.answers),
                         (("rewrite", "retain"), ("extend", "retain")))
        rewrite, retain = {PY: "rewrite"}, {PY: "retain"}
        for occurrence, answers, policies, expected in (
                (spec, {}, {}, (None, None)),
                (spec, {}, rewrite, ("rewrite", "policy")),
                (spec, {spec.subject: "retain"}, rewrite,
                 ("retain", "occurrence")),
                (spec, {spec.subject: "retain"}, {}, ("retain", "occurrence")),
                (skip, {}, rewrite, (None, None)),
                (skip, {}, retain, ("retain", "policy")),
                (skip, {skip.subject: "extend"}, rewrite,
                 ("extend", "occurrence")),
                (data, {}, rewrite, (None, None)),
                (exempt, {}, rewrite, (None, None)),
                (exempt, {exempt.subject: "extend"}, {},
                 ("extend", "occurrence"))):
            with self.subTest(subject=occurrence.subject, answers=answers,
                              policies=policies):
                self.assertEqual(adopt_references.effective_answer(
                    occurrence, answers, policies), expected)
        with self.assertRaises(ValueError):
            adopt_references.effective_answer(skip, {}, {PY: "extend"})

    def test_rows_carry_target_policy_and_what_decided(self):
        references = self.references()
        skip = references.occurrences[2].subject
        rows = adopt_references.summary(references, {skip: "extend"},
                                        {PY: "rewrite"})
        self.assertEqual(list(rows[0]), [
            "subject", "path", "line", "column", "literal", "answers",
            "answer", "additions", "replacement", "target", "policy",
            "decided_by"])
        self.assertEqual(
            [(row["subject"], row["answer"], row["decided_by"],
              row["target"], row["policy"]) for row in rows],
            [(".claude/specs/sub/data.json:1:11", None, None,
              SPECS + "/sub/data.json", JSON),
             (".claude/specs/tool.py:1:9", "rewrite", "policy",
              SPECS + "/tool.py", PY),
             (skip, "extend", "occurrence", SPECS + "/tool.py", PY),
             ("tools/check.py:1:29", None, None, "tools/check.py", None)])

    def test_policy_rows_count_each_class(self):
        references = self.references()
        _, spec, skip, _ = (o.subject for o in references.occurrences)
        rows = adopt_references.policy_summary
        data = self.policy_row(JSON, "retain", 1)
        self.assertEqual(rows(references, {}, {}),
                         [data, self.policy_row(PY, "rewrite", 2)])
        self.assertEqual(
            rows(references, {}, {PY: "rewrite"}),
            [data, self.policy_row(PY, "rewrite", 2, answer="rewrite",
                                   rewritten=1, open=1)])
        self.assertEqual(
            rows(references, {spec: "retain"}, {}),
            [data, self.policy_row(PY, "rewrite", 2, retained=1, open=1,
                                   overridden=1)])
        self.assertEqual(
            rows(references, {skip: "extend"},
                 {PY: "rewrite", JSON: "retain"}),
            [{**data, "answer": "retain", "retained": 1, "open": 0},
             self.policy_row(PY, "rewrite", 2, answer="rewrite", rewritten=1,
                             extended=1, open=0, overridden=1)])

    def test_a_moved_file_is_edited_under_its_target(self):
        references = self.references()
        skip = references.occurrences[2].subject
        before = POLICY_TEXTS[".claude/specs/tool.py"]
        self.assertEqual(
            adopt_references.rewritten(references, {}, {PY: "rewrite"}),
            {SPECS + "/tool.py": (before, (
                'SPEC = ".agents/artifacts/specs/x.md"\n'
                'SKIP = (".claude",)\n'))})
        self.assertEqual(
            adopt_references.rewritten(
                references, {skip: "extend"}, {PY: "rewrite"}),
            {SPECS + "/tool.py": (before, (
                'SPEC = ".agents/artifacts/specs/x.md"\n'
                'SKIP = (".claude", ".agents/artifacts/plans", '
                '".agents/artifacts/specs",)\n'))})
        self.assertEqual(
            adopt_references.rewritten(
                references, {}, {PY: "retain", JSON: "retain"}), {})
        with self.assertRaises(ValueError):
            adopt_references.rewritten(references, {skip: "rewrite"}, {})
```

The measured facts those cases rest on, at the base revision: in `POLICY_TEXTS` the occurrences are, in order, `.claude/specs/sub/data.json:1:11` (`.claude/plans/y.md`, answers `rewrite`, `retain`), `.claude/specs/tool.py:1:9` (`.claude/specs/x.md`, `rewrite`, `retain`), `.claude/specs/tool.py:2:10` (`.claude`, `extend`, `retain`, additions the plans and specs directories) and `tools/check.py:1:29`.

- [ ] **Step 2: Run the unit tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_references.py`
Expected: ERROR/FAIL — `TypeError: plan_references() takes 3 positional arguments but 4 were given` across the existing cases, and `AttributeError` for `file_class`, `recommended_answer`, `effective_answer` and `policy_summary`.

- [ ] **Step 3: Implement the core in `adopt_references`**

1. **The class and the table.** Add `POLICY_ANSWERS = ("rewrite", "retain")` and two tuples, `REWRITE_CLASSES` (`.py .sh .bash .zsh .nix .yaml .yml .toml .js .mjs .cjs .ts`) and `RETAIN_CLASSES` (`.json .jsonl .ndjson .csv .tsv .txt .log`).
   - `file_class(path)`: take the text after the last `/`; `stem, dot, extension = name.rpartition(".")`; return `"." + extension.lower()` when `dot`, `stem` and `extension` are all non-empty, else `"-"`. No `pathlib` suffix: its treatment of a trailing dot differs between Python versions.
   - `recommended_answer(file_class)`: `"rewrite"` for a member of `REWRITE_CLASSES`, `"retain"` for a member of `RETAIN_CLASSES`, else `None`.
2. **`Occurrence`.** Append `target: str` and `tree: str | None` after `shape`. Add the property `policy`: `None` when `tree is None`, else `f"{self.tree}:{file_class(self.path)}"`. `subject` is unchanged.
3. **`plan_references(texts, paths, moves, trees)`.** For each file, `target = moved.get(path, path)`; `tree = None` when `path` is not a move source, else `trees[path]`, raising `ValueError` naming the path when it is missing. Pass both into `_occurrence`, which sets them on the `Occurrence` it builds and is otherwise unchanged. Compute them once per file, before its tokens.
4. **`derive_references(root, revision, moves, excluded, trees)`.** The skipped set becomes `set(excluded)`: move sources are no longer left out. Every other clause of the filter stands, `path.startswith(RECORD_HOMES)` included, tested against the base path the grep returned. Pass `trees` to `plan_references`.
5. **`effective_answer(occurrence, answers, policies)`.** In order: the occurrence's own answer, `answers.get(occurrence.subject)`, when present → `(that, "occurrence")`. Else, when `occurrence.policy` is not `None` and `policies` holds it: raise `ValueError` when the value is not in `POLICY_ANSWERS`; return `(value, "policy")` when `value in occurrence.answers`; otherwise `(None, None)`. Else `(None, None)`. The own answer is returned without checking that it is offered: `rewritten` makes that check, as at base.
6. **`summary(references, answers, policies)`.** Each row keeps its nine base members in order, with `"answer"` now the effective answer, then `"target"`, `"policy"` (the property) and `"decided_by"`.
7. **`policy_summary(references, answers, policies)`.** Group the occurrences whose `policy` is not `None` by it. One row per policy, sorted by `subject`, with exactly these members in this order: `subject`, `tree`, `class` (`file_class` of any member's path), `recommended` (`recommended_answer` of the class), `answer` (`policies.get(subject)`), `files` (distinct `path`), `occurrences`, `rewritable` (those whose `answers` hold `rewrite`), `rewritten`, `retained`, `extended` (by effective answer), `open` (no effective answer), `overridden` (`decided_by == "occurrence"`). A policy exists only where an occurrence does: no occurrences, no rows.
8. **`rewritten(references, answers, policies)`.** For each occurrence: when it has an own answer that is not in `occurrence.answers`, raise `ValueError` (the base check, on the own answer only); take the effective answer; skip `None` and `retain`; collect the `_edit` splice under `occurrence.path`. Apply each file's splices to `references.texts[path]` from the last offset, as at base, and return the result keyed by the file's **target** (every occurrence of one file has the same target).
9. Update the module docstring and the docstrings of the changed functions from the implemented code. The module docstring's first paragraph must no longer imply that only files outside the moved trees are read.

- [ ] **Step 4: Write the failing plan and apply tests**

In `home/common/agent-skills/tests/test_adopt_project.py`:

(a) `REFERENCE_ROW` gains `"target": CHECK_LINKS, "policy": None, "decided_by": None`. In `PathReferencePlanTest`, the three answered-row expectations become `{**REFERENCE_ROW, "answer": "extend", "decided_by": "occurrence"}` (two places) and `{**REFERENCE_ROW, "answer": "retain", "decided_by": "occurrence"}`. Nothing else in the existing cases changes.

(b) Add after `referenced_repo`:

```python
MOVED_TOOL = ".claude/notes/tool.py"
MOVED_TOOL_NEW = ".agents/artifacts/notes/tool.py"
MOVED_TOOL_TEXT = 'SPEC = ".claude/specs/x.md"\n'
MOVED_TOOL_AFTER = 'SPEC = ".agents/artifacts/specs/x.md"\n'
MOVED_TOOL_SUBJECT = f"{MOVED_TOOL}:1:9"


def write_moved_tool(root: Path) -> None:
    """One script inside a moved tree that names a file of another."""
    write(root, MOVED_TOOL, MOVED_TOOL_TEXT)
    commit(root, "add a script to a moved tree")
```

(c) Add after `class PathReferencePlanTest`:

```python
class MovedFileReferencePlanTest(AdoptTestCase):
    """#372 D1: a moved file is read, and written where the move leaves it."""

    def repo(self) -> Path:
        root = nix_config_shape_repo(self.home)
        write_moved_tool(root)
        return root

    def test_a_moved_file_is_read_and_its_row_names_the_destination(self):
        doc = self.ready_plan(self.repo())
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(doc["path_references"], [{
            "subject": MOVED_TOOL_SUBJECT, "path": MOVED_TOOL, "line": 1,
            "column": 9, "literal": ".claude/specs/x.md",
            "answers": ["rewrite", "retain"], "answer": None,
            "additions": [], "replacement": ".agents/artifacts/specs/x.md",
            "target": MOVED_TOOL_NEW, "policy": ".claude/notes:.py",
            "decided_by": None}])
        self.assertEqual(
            [op["op"] for op in doc["changes"]
             if MOVED_TOOL_NEW in op["targets"]], ["git-mv"])

    def test_an_answered_moved_file_is_written_once_at_its_destination(self):
        code, doc, err = self.plan(self.repo(), "--answer", "path-reference",
                                   MOVED_TOOL_SUBJECT, "rewrite")
        self.assertEqual(code, 0, err or doc)
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        (row,) = doc["path_references"]
        self.assertEqual((row["answer"], row["decided_by"]),
                         ("rewrite", "occurrence"))
        move, write_op = [op for op in doc["changes"]
                          if MOVED_TOOL_NEW in op["sources"] + op["targets"]]
        self.assertEqual((move["op"], move["sources"], move["targets"]),
                         ("git-mv", [MOVED_TOOL], [MOVED_TOOL_NEW]))
        self.assertEqual(
            (write_op["op"], write_op["sources"], write_op["targets"]),
            ("write-file", [MOVED_TOOL_NEW], [MOVED_TOOL_NEW]))
        self.assertEqual(write_op["before"],
                         sha256_hash(MOVED_TOOL_TEXT.encode("utf-8")))
        self.assertEqual(write_op["after"],
                         sha256_hash(MOVED_TOOL_AFTER.encode("utf-8")))
        self.assertEqual(
            [op["op"] for op in doc["changes"]
             if MOVED_TOOL in op["sources"] + op["targets"]], ["git-mv"])
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))

    def test_a_reference_target_may_be_one_move_destination(self):
        op = adopt_planning.operation
        blob = "git-object:" + "0" * 40
        write_op = op("write-file", [MOVED_TOOL_NEW], [MOVED_TOOL_NEW],
                      "sha256:" + "0" * 64, "sha256:" + "1" * 64)
        move = op("git-mv", [MOVED_TOOL], [MOVED_TOOL_NEW], blob, blob)
        adopt_planning.check_reference_writes([move, write_op],
                                              {MOVED_TOOL_NEW})
        second = op("git-mv", ["tools/other.py"], [MOVED_TOOL_NEW], blob,
                    blob)
        away = op("git-mv", [MOVED_TOOL_NEW], ["tools/moved.py"], blob, blob)
        for changes in ([move], [move, write_op, write_op],
                        [move, second, write_op], [move, write_op, away]):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    adopt_planning.check_reference_writes(
                        changes, {MOVED_TOOL_NEW})
```

In `home/common/agent-skills/tests/test_adopt_apply.py`:

(d) In `PathReferenceApplyTest.test_the_evidence_record_lists_the_answer_and_the_row`, the expected row becomes `{**REFERENCE_ROW, "answer": "extend", "decided_by": "occurrence"}`.

(e) Import `MOVED_TOOL`, `MOVED_TOOL_AFTER`, `MOVED_TOOL_NEW`, `MOVED_TOOL_SUBJECT` and `write_moved_tool` from `.test_adopt_project` (keep the import list sorted) and add after `class PathReferenceApplyTest`:

```python
class MovedFileReferenceApplyTest(ApplyTestCase):
    """#372 D1: the edit of a moved file is part of the adoption commit."""

    def test_the_moved_script_is_rewritten_at_its_destination(self):
        root = apply_repo(self.home)
        write_moved_tool(root)
        code, out, err = run("plan", "--repo-root", str(root), "--answer",
                             "path-reference", MOVED_TOOL_SUBJECT, "rewrite",
                             home=self.home)
        self.assertEqual(code, 0, err or out)
        document = json.loads(out)
        self.assertEqual(document["plan"]["state"], "ready",
                         document["plan"]["blockers"])
        branch = self.succeed(root, document["plan"]["plan_id"])["branch"]
        self.assertEqual(git(root, "show", f"{branch}:{MOVED_TOOL_NEW}"),
                         MOVED_TOOL_AFTER)
        self.assertNotIn(MOVED_TOOL, self.branch_files(root, branch))
        self.assertEqual(
            git(root, "rev-list", "--count", f"HEAD..{branch}").strip(), "1")
```

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py -k MovedFileReferencePlanTest` (timeout 1800 s)
Expected: FAIL/ERROR in all three cases — the two `plan` cases because no caller passes `trees` yet, so `plan` does not exit 0, and `test_a_reference_target_may_be_one_move_destination` with `ValueError: '.agents/artifacts/notes/tool.py' is not held by exactly one in-place write-file operation`.

- [ ] **Step 5: Thread the callers**

In `adopt_planning.apply_answers`:

- Before the validation loop, build `trees: dict[str, str]` as `{path: group for group, info in found.groups.items() for path, _ in info["members"]}`.
- Where a validated `archive-history` answer appends to the local `moves`, also set `trees[answer["subject"]] = answer["subject"]`.
- Both `derive_references` calls pass `trees` as the fifth argument. The two calls then see the same moves and the same trees, so answer order still changes nothing (350 D12).
- Correct the docstring's account of what the references are derived over.

In `adopt_planning.check_reference_writes`, the rule for each target becomes: among the operations that hold it (the base definition of "holds", `regenerate-projection` sources excluded), there is exactly one `write-file` with `sources == targets == [target]`, and every other holder — at most one — is a `git-mv` whose `targets == [target]`. Anything else raises `ValueError` as at base: no write, two writes, a `delete-file`, a `git-mv` whose **source** is the target, two moves onto it, a `write-file` with other sources. Rewrite the docstring from the implemented rule.

In `adopt_planning.build_operations`, the loop over `reference_files` is unchanged in code: its keys are now targets, `before` is the hash of the base text and the write follows every `git-mv` because it sits in `tail`. Replace the comment above the loop (it says these files are never moved) and the docstring's sentence on `reference_files` with what is now true.

In `adopt_project.compose_plan`: `path_references = adopt_references.summary(references, reference_answers, {})` and `reference_files = adopt_references.rewritten(references, reference_answers, {})`. The empty mapping is the whole of this task's policy wiring; Task 4 replaces it.

- [ ] **Step 6: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_references.py`
Expected: PASS, every case, no warnings.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py -k MovedFileReferencePlanTest -k PathReferencePlanTest -k LinkRewritePlanTest -k DocumentShapeTest -k PlanIdentityTest` (timeout 1800 s)
Expected: PASS, including the three `MovedFileReferencePlanTest` cases that failed in Step 4.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_apply.py -k MovedFileReferenceApplyTest -k PathReferenceApplyTest -k LinkRewriteApplyTest` (timeout 1800 s)
Expected: PASS. `adopt_apply.py` is not edited: its status expectation already takes a write onto a move target as that move's content. If `MovedFileReferenceApplyTest` fails inside `apply`, stop and report it as a plan defect with the refusal's `repair_id`; do not edit `adopt_apply.py`.

Scope gate: `git diff --stat 32807f90d4a4 -- python/agent_tools/adopt_apply.py python/agent_tools/adopt_links.py python/agent_tools/adopt_verify.py` prints nothing.

- [ ] **Step 7: Commit**

```bash
git add python/agent_tools/adopt_references.py python/agent_tools/adopt_planning.py python/agent_tools/adopt_project.py home/common/agent-skills/tests/test_adopt_references.py home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_apply.py
git commit -m "feat(adopt): read moved files and write their edits at the destination (#372)"
```
