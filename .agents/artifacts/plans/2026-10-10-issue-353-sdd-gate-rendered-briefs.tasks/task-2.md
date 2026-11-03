# Task 2: Plan-header reading and standards selection

**Files:**
- Modify: `python/agent_tools/sdd_brief.py`
- Modify: `tests/test_sdd_brief.py`
- Test: `tests/test_sdd_brief.py`

**Interfaces:**
- Consumes, from Task 1, in `agent_tools.sdd_brief`: `class BriefError(Exception)` (one-line message). Nothing else of Task 1 changes.
- Produces, in `agent_tools.sdd_brief`:
  - `@dataclass(frozen=True) class TaskRow` with fields `title: str` and `paths: tuple[str, ...]`.
  - `plan_section(plan_text: str, heading: str) -> str`
  - `task_row(plan_text: str, number: int) -> TaskRow`
  - `select_standards(global_dir: Path, entries: Sequence[Path], touched: Sequence[str]) -> list[Path]`
  - `standards_value(documents: Sequence[Path]) -> str`
  - `worker_block(repo_root: str, run_id: str, worker_id: str) -> str`

**Invariants (spec "Placeholder sets and values", "Standards in the brief"; D6, D12):**
- A section body is the lines after the one line equal to `heading`, up to the next line starting with `## `, with leading and trailing empty lines dropped, joined with `"\n"` and no final newline. No such line, or more than one, is refused.
- The Task-index row is read only inside the one `## Task index` section; exactly one line there may start `Task <number>` followed by whitespace and an em dash.
- Layer 0, `global_dir / "the-bar.md"`, is always the first selected document; a missing file is refused.
- A glob matches with `fnmatch.fnmatchcase(path, glob)` on the whole repository-relative path, the rule `agent_tools.lane_triage.evaluate` uses.
- Layer 1 (stack documents) is never selected.
- Every function is pure text or read-only: nothing here writes a file, runs a process or reads the environment.
- Every refusal raises `BriefError`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_sdd_brief.py`, add `import tempfile` to the imports and append these three classes before the `if __name__` block:

```python
PLAN = "\n".join([
    "# P", "", "**Goal:** g", "",
    "## Global Constraints", "", "- one", "", "- two", "", "",
    "## Test seams", "- seam", "",
    "## Task index", "",
    "Task 1 — First thing — `a/b.py`, `docs/x.md` — full — [task-1.md](plan.tasks/task-1.md)",
    "Task 2 — Second — with a dash — `c.py` — low-risk — [task-2.md](plan.tasks/task-2.md)",
    "Task 4 — Too — short",
    "", "## Decisions", "",
    "Task 3 — Outside — `z.py` — full — [task-3.md](plan.tasks/task-3.md)", ""])


class PlanHeaderTest(unittest.TestCase):
    def test_a_section_body_drops_its_outer_empty_lines(self):
        self.assertEqual(sdd_brief.plan_section(PLAN, "## Global Constraints"), "- one\n\n- two")
        self.assertEqual(sdd_brief.plan_section(PLAN, "## Test seams"), "- seam")

    def test_a_missing_or_repeated_heading_is_refused(self):
        with self.assertRaises(BriefError):
            sdd_brief.plan_section(PLAN, "## Nope")
        with self.assertRaises(BriefError):
            sdd_brief.plan_section(PLAN + "\n## Test seams\n\n- again\n", "## Test seams")

    def test_the_index_row_gives_the_title_and_the_backticked_paths(self):
        self.assertEqual(sdd_brief.task_row(PLAN, 1),
                         sdd_brief.TaskRow("First thing", ("a/b.py", "docs/x.md")))
        self.assertEqual(sdd_brief.task_row(PLAN, 2),
                         sdd_brief.TaskRow("Second — with a dash", ("c.py",)))

    def test_a_missing_repeated_or_malformed_row_is_refused(self):
        repeated = PLAN.replace("Task 4 — Too — short",
                                "Task 1 — Again — `q.py` — full — [task-1.md](plan.tasks/task-1.md)")
        cases = {"row only outside the index": (PLAN, 3), "no such row": (PLAN, 9),
                 "too few fields": (PLAN, 4), "repeated row": (repeated, 1),
                 "no Task index": (PLAN.replace("## Task index", "## Tasks"), 1),
                 "two Task indexes": (PLAN + "\n## Task index\n", 1)}
        for name, (text, number) in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(BriefError):
                    sdd_brief.task_row(text, number)


class StandardsTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name).resolve()
        self.layer0 = self.root / "global"
        self.layer0.mkdir()
        self.bar = self.layer0 / "the-bar.md"
        self.bar.write_text("# Bar\n\nDeep modules.\n\n\n", encoding="utf-8")
        self.project = self.root / "project"
        self.project.mkdir()
        self.readme = self.project / "README.md"
        self.readme.write_text(
            "# Project standards\n\nIntro.\n\n"
            "| Shard | governs | Gist |\n|---|---|---|\n"
            "| [py.md](py.md) | `python/**`, `scripts/*.py` | Python rules. |\n"
            "| [docs.md](docs.md) | `docs/**` | Doc rules. |\n\nAfter the table.\n",
            encoding="utf-8")
        self.py = self.project / "py.md"
        self.py.write_text("# Py\n", encoding="utf-8")
        self.docs = self.project / "docs.md"
        self.docs.write_text("# Docs\n", encoding="utf-8")
        self.single = self.root / "single.md"
        self.single.write_text("# Single\n\nOne file.\n", encoding="utf-8")
        self.plain = self.root / "plain"
        self.plain.mkdir()
        (self.plain / "README.md").write_text(
            "| Layer | Where |\n|---|---|\n| 0 | [the-bar.md](the-bar.md) |\n", encoding="utf-8")

    def select(self, *touched, entries=None):
        entries = [self.project, self.single, self.plain] if entries is None else entries
        return sdd_brief.select_standards(self.layer0, entries, list(touched))

    def test_layer_zero_is_first_and_a_row_is_selected_by_its_globs(self):
        self.assertEqual(self.select("python/agent_tools/x.py"), [self.bar, self.py, self.single])
        self.assertEqual(self.select("docs/a/b.md", "scripts/run.py"),
                         [self.bar, self.py, self.docs, self.single])
        self.assertEqual(self.select("notes.txt"), [self.bar, self.single])
        self.assertEqual(self.select("Python/x.py"), [self.bar, self.single])
        self.assertEqual(self.select(), [self.bar, self.single])

    def test_entries_are_taken_in_the_order_given_and_listed_once(self):
        self.assertEqual(self.select("python/x.py", entries=[self.single, self.project]),
                         [self.bar, self.single, self.py])
        self.assertEqual(self.select("python/x.py", entries=[self.project, self.project]),
                         [self.bar, self.py])

    def test_a_layer_that_cannot_be_read_as_declared_is_refused(self):
        table = "| Shard | governs | Gist |\n|---|---|---|\n"

        def missing_bar():
            self.bar.unlink()

        def dangling_row():
            self.docs.unlink()

        def escaping_row():
            self.readme.write_text(table + "| [up](../single.md) | `docs/**` | Up. |\n",
                                   encoding="utf-8")

        def row_without_a_link():
            self.readme.write_text(table + "| py.md | `python/**` | No link. |\n", encoding="utf-8")

        def short_row():
            self.readme.write_text(table + "| [py.md](py.md) |\n", encoding="utf-8")

        for arrange in (missing_bar, dangling_row, escaping_row, row_without_a_link, short_row):
            with self.subTest(case=arrange.__name__):
                self.setUp()
                arrange()
                with self.assertRaises(BriefError):
                    self.select("python/x.py")
        with self.subTest(case="an entry that does not exist"):
            self.setUp()
            with self.assertRaises(BriefError):
                self.select("python/x.py", entries=[self.root / "absent"])

    def test_the_value_pastes_each_document_under_its_source_line(self):
        self.assertEqual(sdd_brief.standards_value([self.bar, self.py]),
                         f"Source: {self.bar}\n\n# Bar\n\nDeep modules.\n\nSource: {self.py}\n\n# Py")

    def test_a_document_that_is_not_utf8_is_refused(self):
        self.py.write_bytes(b"\xff\xfe")
        with self.assertRaises(BriefError):
            sdd_brief.standards_value([self.bar, self.py])


class WorkerBlockTest(unittest.TestCase):
    def test_the_block_is_the_worker_line_and_the_two_launch_scope_sentences(self):
        flags = "--repo-root /r --run-id run-1 --worker-id 14:1:1:w1"
        self.assertEqual(sdd_brief.worker_block("/r", "run-1", "14:1:1:w1"), "\n".join([
            f"Lifecycle worker: {flags}",
            "Run each long command, every verification command included, as "
            f"`launch-scope exec {flags} -- <argv>`, still in the foreground.",
            "Create every scratch directory or scratch worktree under the path that "
            f"`launch-scope scratch {flags}` prints."]))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_sdd_brief.py`
Expected: Task 1's 9 tests pass; the 10 new tests error with `AttributeError: module 'agent_tools.sdd_brief' has no attribute` naming `plan_section`, `task_row`, `TaskRow`, `select_standards`, `standards_value` or `worker_block`.

- [ ] **Step 3: Implement the five functions and `TaskRow`**

Decisions the code must embody:

`plan_section(plan_text, heading)`: work on `plan_text.splitlines()`. Refuse unless exactly one line equals `heading`. The body runs to the next line starting with `"## "` or the end; strip empty lines (`line.strip() == ""`) from both ends; return the rest joined with `"\n"`. An empty body is returned as `""`: the caller's `render` refuses an empty required value.

`task_row(plan_text, number)`:
1. Refuse unless exactly one line equals `## Task index`. The section is the lines after it up to the next line starting with `"## "`.
2. The candidate rows are the section lines matching `^Task <number>\s+—` (the em dash U+2014, the pattern `task-brief` uses). Refuse unless there is exactly one.
3. Find every separator `\s+—\s+` in the row with `re.finditer`. Refuse when there are fewer than four. The title is the text between the end of the first separator and the start of the third-from-last; the files field is the text between the end of the third-from-last and the start of the second-from-last. A title may therefore contain a spaced em dash (D12).
4. `paths` is every backticked span of the files field, in order: ``re.findall(r"`([^`]+)`", files)``. No span gives `()`.

`select_standards(global_dir, entries, touched)`:
1. `bar = global_dir / "the-bar.md"`; refuse unless it is a regular file. It is the first result.
2. For each entry in the order given:
   - a regular file: it is selected whole;
   - a directory: read its `README.md` when that is a regular file. The table header is the first line that starts with `|` and has a cell equal to `governs`, cells being `line.strip().strip("|").split("|")` with each cell stripped. No `README.md` or no such header: the directory contributes nothing. Otherwise the rows are the consecutive following lines that start with `|`, skipping a delimiter row (every cell made only of `-`, `:` and spaces). For every row, matching or not: refuse when it has no cell at the header's `governs` index, when it holds no Markdown link (``\[[^\]]*\]\(([^)]+)\)``, the first one in the row), or when `(entry / target).resolve()` is not a regular file inside `entry.resolve()`. The row is selected when any backticked span of its `governs` cell matches any touched path with `fnmatch.fnmatchcase`;
   - anything else, a path that does not exist included: refuse (D12).
3. A selected document is returned as `Path(os.path.abspath(entry / target))` (the entry itself for a file entry): absolute and normalized, with symlinks left unresolved, so the path a brief prints is the path the caller passed. A document already in the result is not added again.

`standards_value(documents)`: for each document, the line `Source: <path>`, an empty line, and the document's text decoded as strict UTF-8 with trailing `"\n"` characters removed; blocks are joined with one empty line (`"\n\n"`). An unreadable or non-UTF-8 document is refused. No final newline.

`worker_block(repo_root, run_id, worker_id)`: the three lines the test pins, joined with `"\n"`. They are the worker line and the two sentences `sdd/SKILL.md`'s `### Lifecycle workers` prescribes, with the three values substituted.

Write each docstring from the code you implemented.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_sdd_brief.py`
Expected: `OK`, 19 tests, no warnings.

Run: `if grep -nE "__file__|importlib|sys\.path|subprocess|os\.environ" python/agent_tools/sdd_brief.py; then exit 1; fi`
Expected: no output, exit 0 (the module stays pure and free of import machinery).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/sdd_brief.py tests/test_sdd_brief.py
git commit -m "feat(issue-353): read plan sections and select standards documents for a brief"
```
