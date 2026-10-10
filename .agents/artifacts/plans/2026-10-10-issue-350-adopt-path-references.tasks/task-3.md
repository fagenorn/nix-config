# Task 3: `apply` commits the answered references, and the contract is documented

**Files:**
- Modify: `python/README.md` (the `adopt-project` paragraphs)
- Test: `home/common/agent-skills/tests/test_adopt_apply.py`

**Interfaces:**
- Consumes (Task 2): `plan --answer path-reference <subject> <value>`; the plan document's and the evidence record's `path_references` rows; the `write-file` operation for an edited file. From `test_adopt_project.py` (Task 2): `CHECK_LINKS`, `CHECK_LINKS_EXTENDED`, `REFERENCE_ROW`, `REFERENCE_SUBJECT`, `UNRELATED_SCRIPT`, `write_reference_tree(root, *, script=True)`. Existing: `apply_repo(home)`, `ApplyTestCase.succeed(root, plan_id) -> dict` (`branch`, `evidence_record`), `adopt_inspection.export_commit(root: Path, commit: str, destination: Path) -> None` (`destination` must not exist).
- Produces: nothing a later task consumes.

**Invariants:**
- `python/agent_tools/adopt_apply.py` and `adopt_verify.py` are unchanged from the base: `apply` replays the stored `{id, subject, value}` answers through `compose_plan` and executes the reference edit as the `write-file` it re-derives (D7, D9).
- The adoption stays one commit: the edited script, the moves and the Markdown link rewrites land together.
- A file without an `extend` or `rewrite` answer is byte-identical in the adopt commit.

- [ ] **Step 1: Write the tests**

In `test_adopt_apply.py`, add `import sys` and `import tempfile` to the standard-library imports, add `adopt_inspection` to `from agent_tools import ...`, and add `CHECK_LINKS`, `CHECK_LINKS_EXTENDED`, `REFERENCE_ROW`, `REFERENCE_SUBJECT`, `UNRELATED_SCRIPT` and `write_reference_tree` to the `.test_adopt_project` import (keep it sorted). After `linked_apply_repo` add:

```python
def referenced_apply_repo(home: Path) -> Path:
    """`apply_repo` plus #350's link-check script and its reference tree."""
    root = apply_repo(home)
    write_reference_tree(root)
    return root
```

After `LinkRewriteApplyTest` add:

```python
class PathReferenceApplyTest(ApplyTestCase):
    """#350: an answered path reference is edited in the adoption commit."""

    def answered_plan(self, root: Path, value: str) -> dict:
        code, out, err = run("plan", "--repo-root", str(root), "--answer",
                             "path-reference", REFERENCE_SUBJECT, value,
                             home=self.home)
        self.assertEqual(code, 0, err or out)
        document = json.loads(out)
        self.assertEqual(document["plan"]["state"], "ready",
                         document["plan"]["blockers"])
        return document

    def check(self, root: Path, revision: str) -> tuple[int, str]:
        """The fixture's own link check, run on an export of `revision`."""
        export = Path(tempfile.mkdtemp()) / "tree"
        adopt_inspection.export_commit(root, revision, export)
        proc = subprocess.run(
            [sys.executable, str(export / CHECK_LINKS), str(export)],
            capture_output=True, text=True, timeout=120)
        return proc.returncode, proc.stdout

    def test_the_extended_script_passes_on_the_adopt_commit_as_on_base(self):
        root = referenced_apply_repo(self.home)
        document = self.answered_plan(root, "extend")
        branch = self.succeed(root, document["plan"]["plan_id"])["branch"]
        self.assertEqual(git(root, "show", f"{branch}:{CHECK_LINKS}"),
                         CHECK_LINKS_EXTENDED)
        self.assertEqual(git(root, "show", f"{branch}:{UNRELATED_SCRIPT}"),
                         git(root, "show", f"HEAD:{UNRELATED_SCRIPT}"))
        self.assertEqual(
            git(root, "rev-list", "--count", f"HEAD..{branch}").strip(), "1")
        base = self.check(root, "HEAD")
        self.assertEqual(base, (0, "ok\n"))
        self.assertEqual(self.check(root, branch), base)

    def test_a_retained_reference_leaves_the_check_failing(self):
        root = referenced_apply_repo(self.home)
        document = self.answered_plan(root, "retain")
        branch = self.succeed(root, document["plan"]["plan_id"])["branch"]
        self.assertEqual(git(root, "show", f"{branch}:{CHECK_LINKS}"),
                         git(root, "show", f"HEAD:{CHECK_LINKS}"))
        self.assertEqual(self.check(root, branch),
                         (1, ".agents/artifacts/specs/x.md: missing.md\n"))

    def test_the_evidence_record_lists_the_answer_and_the_row(self):
        root = referenced_apply_repo(self.home)
        document = self.answered_plan(root, "extend")
        result = self.succeed(root, document["plan"]["plan_id"])
        record = json.loads(git(
            root, "show", f"{result['branch']}:{result['evidence_record']}"))
        self.assertIn({"id": "path-reference", "subject": REFERENCE_SUBJECT,
                       "value": "extend"}, record["decisions_accepted"])
        self.assertEqual(record["path_references"],
                         [{**REFERENCE_ROW, "answer": "extend"}])
        self.assertEqual(record["path_references"],
                         document["path_references"])
```

- [ ] **Step 2: Run the tests**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_apply.py -k PathReferenceApplyTest` (timeout 900 s)
Expected: OK, 3 tests. These cases characterise behaviour Task 2 already produces through `apply`'s re-derivation, so they are expected green at this task's first run; before this step the same command reports `Ran 0 tests`. A failure is a defect in Task 2's derivation: fix it in `adopt_planning.py` or `adopt_project.py` with a failing case added to `PathReferencePlanTest` first, and never by editing `adopt_apply.py`.

- [ ] **Step 3: Document the contract**

In `python/README.md`:

1. In the paragraph that starts `` `adopt-project plan` asks two kinds of open question ``, change "two kinds" to "three kinds", change "(an id other than `candidate-class`," to "(an id other than `candidate-class` or `path-reference`,", and append at the end of the paragraph: `` The third kind, `path-reference`, is described below; `--answer` settles it through the same flag, pass and refusals. ``
2. In the paragraph that starts `` `adopt-project plan` rewrites relative Markdown link targets ``, replace its last sentence with: `` Prose mentions of moved paths, inline HTML and root-relative targets are never rewritten, and a path literal in a non-Markdown file is left to the `path-reference` question. ``
3. Add, directly after that paragraph, one paragraph with this content, correcting any clause that differs from the code as implemented (the code is the source, this text is not):

```markdown
`adopt-project plan` asks about every path literal in a tracked non-Markdown text file that names something its moves relocate (https://github.com/fagenorn/nix-config/issues/350), and edits nothing without an answer. `agent_tools.adopt_references` scans the base revision's regular, non-Markdown, non-secret blobs that git judges text and that decode as strict UTF-8, found by one `git grep` for the first path segment of each move source, leaving out move sources, `.agents/artifacts/`, `.agents/knowledge/archive/` and the files adoption itself may write (the contract, `.gitignore`, the runtime sentinel, a legacy binding config and a `generated_file` projection target). A token is a run of characters bounded by whitespace or one of `"`, `'`, `` ` ``, `,`, `;`, `:`, `=`, `(`, `)`, `<`, `>`, `|`, `&`, `#`, `!`, read as an optional leading `./` or `/`, a path up to its first glob segment and a tail; it is an occurrence when it contains `/` or is the whole content of a quoted string, its path names a file or directory of the base tree, and a move source is that path or lies under it, so `.claude/` counts when `.claude/specs` moves. A moved file, or a directory whose members all moved by the same relative tails under one new directory, has a single successor; a path that survives or dissolves maps to the successors of its wholly moved subtrees, carried only for an empty, `/` or `/**` tail. Each occurrence opens a `path-reference` question keyed by its `subject`, `<path>:<line>:<column>`, with an `answers` list and no recommended value: `extend`, offered when the token is a quoted element of a bracketed, braced or parenthesised sequence (never a call's argument) or the only content of its line after indentation and an optional `- `, adds one quoted element or one copied line per successor beside the literal; `rewrite`, offered for a single successor, replaces the token; `retain`, always offered, leaves the file as it is. `plan --answer path-reference SUBJECT VALUE` settles one, after any `candidate-class` answers, whose moves the references are derived from; an unknown subject refuses `adopt.decisions.unmatched_answer` and a repeated subject or a value the occurrence does not offer refuses `adopt.decisions.invalid_answer`. An open reference keeps the plan `draft` through `no-open-decisions`; no gate and no `verify` check is added. Each file with an `extend` or `rewrite` answer is one `write-file` after the Markdown link rewrites and before the projection regenerations, in the same commit as the moves. The plan document and the adoption evidence record carry `path_references`, one row per occurrence sorted by path, line and column (`subject`, `path`, `line`, `column`, `literal`, `answers`, `answer`, `additions`, `replacement`), which is the eighth input of `plan_id`, and the record's `decisions_accepted` lists the answers. Variables, joined path segments, URLs, bare unquoted single words and YAML flow sequences are not recognised.
```

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_apply.py` (timeout 1800 s)
Expected: OK, every test passing, no warnings (`LinkRewriteApplyTest` and `AnsweredCandidateApplyTest` unedited and green).

Run: `grep -c "path-reference" python/README.md; if grep -q "non-Markdown files are never rewritten" python/README.md; then exit 1; fi; git diff --stat 02d2f378ad8c4abbb8e3a3960b4c93b10879bd6b -- python/agent_tools/adopt_apply.py python/agent_tools/adopt_verify.py`
Expected: a count of at least 3, exit 0, and no diff output.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_adopt_apply.py python/README.md
git commit -m "test(adopt): apply an extended path reference; document the question (#350)"
```
