# Task 4: The formatting step in `apply`, its confinement proof, and the documented contract

**Files:**
- Modify: `python/agent_tools/adopt_apply.py`
- Modify: `python/agent_tools/adopt_project.py` (`command_apply` and the module docstring only)
- Modify: `python/README.md` (§ `adopt-project`)
- Test: `home/common/agent-skills/tests/test_adopt_apply.py`

**Interfaces:**
- Consumes (Task 3): the document member `reference_formatting` (`[{"class", "command", "files"}]`, sorted by class) from `compose_plan`'s re-derivation; `apply` already proved it equals the stored plan's by `plan_id`.
- Produces:
  - `adopt_apply.run_formatting(worktree: Path, operations: list[dict], rows: list[dict], run_resolver: Resolver) -> None` — raises `AdoptError` on failure.
  - `adopt_apply.prove_formatting_confined(worktree: Path, operations: list[dict], formatted: set[str]) -> None` — raises `AdoptError`.

**Invariants:**
- Rows whose `command` is None are skipped; with no row naming a command the step returns without calling the resolver (D2, D12).
- The step runs once, after every operation executed and matched its `after`, before `GateRun` is built; the gates therefore judge the formatted tree (D4, D12).
- Each command is `bindings.commands[<id>]` of a `resolve` observation of the worktree taken by the step; run as the verification gate runs one — `argv` then the row's files as absolute worktree paths in row order, at the entry's `cwd`, output captured, no timeout — then the row's files are staged (D4).
- Confinement: for every path that is not a formatted file, the **last** operation that names it as `targets[0]` and publishes a non-null `after` still satisfies `operation_result_matches`; every formatted file is a regular file, not a symlink (D9).
- Failures are `verification_failed` with `adopt.format.failed` (no resolving contract, no entry for the id, the command cannot start, a non-zero exit, a file that cannot be staged) or `adopt.format.unplanned_content` (a confinement check), pointer `/reference_formatting`; the worktree and branch are retained and every commit gate is recorded `not_run` (D5).
- A formatter that changes an unplanned tracked file or leaves an untracked one is refused by the existing `worktree-status-matches-operations` gate; nothing new is added for it.
- The published `after` of a formatted file's `write-file` stays the hash of the planned, unformatted bytes; `verify` is unchanged (D4).

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_adopt_apply.py`:

1. `apply_repo` gains a keyword `commands: dict[str, list[str]] | None = None`; each entry is added to `contract["bindings"]["commands"]` as `{"argv": argv, "cwd": ".", "env": []}` beside `verify` and `review`, before `scaffold`. Its docstring names the parameter.
2. `write`, `commit`, `answer_args` and `write_linked_tree` are already imported from `test_adopt_project`; import nothing new.
3. Add the fixture and the class (after `VariablePolicyApplyTest` when present, else after `ReferencePolicyApplyTest`):

```python
# #376 D15: the fixture's own lint and formatter, standard-library scripts
# that walk `*.py` from their working directory, so the same lint runs in
# the adoption worktree and on an export of the adoption commit.
LINT = "tools/lint.py"
FORMATTER = "tools/format.py"
LINT_TEXT = (
    "import pathlib\n"
    "import sys\n"
    "\n"
    "LIMIT = 60\n"
    "long = []\n"
    'for path in sorted(pathlib.Path(".").rglob("*.py")):\n'
    '    text = path.read_text(encoding="utf-8")\n'
    "    for number, line in enumerate(text.splitlines(), 1):\n"
    "        if len(line) > LIMIT:\n"
    '            long.append(f"{path}:{number}")\n'
    'print("\\n".join(long))\n'
    "sys.exit(1 if long else 0)\n")
# Rewraps a `name = value` line over the limit and strips trailing
# whitespace in the files it is given; `--fail` exits non-zero and each
# `--touch PATH` appends a line to PATH first.
FORMATTER_TEXT = (
    "import sys\n"
    "\n"
    "LIMIT = 60\n"
    "args = sys.argv[1:]\n"
    'if args[:1] == ["--fail"]:\n'
    "    sys.exit(3)\n"
    'while args[:1] == ["--touch"]:\n'
    '    with open(args[1], "a", encoding="utf-8") as handle:\n'
    '        handle.write("# touched\\n")\n'
    "    args = args[2:]\n"
    "\n"
    "\n"
    "def wrapped(line):\n"
    '    head, sep, tail = line.partition(" = ")\n'
    "    if len(line) <= LIMIT or not sep:\n"
    "        return [line]\n"
    '    return [head + " = (", "    " + tail, ")"]\n'
    "\n"
    "\n"
    "for name in args:\n"
    '    with open(name, encoding="utf-8") as handle:\n'
    "        lines = handle.read().splitlines()\n"
    "    out = []\n"
    "    for line in lines:\n"
    "        out.extend(wrapped(line.rstrip()))\n"
    '    with open(name, "w", encoding="utf-8") as handle:\n'
    '        handle.write("".join(x + "\\n" for x in out))\n')
ANALYZER = "tests/test_analyzer.py"
ANALYZER_SUBJECT = f"{ANALYZER}:1:34"
ANALYZER_TEXT = 'ANALYZER_SPEC_PATH_UNDER_TEST = ".claude/specs/x.md"\n'
ANALYZER_REWRITTEN = ANALYZER_TEXT.replace(".claude/specs",
                                           ".agents/artifacts/specs")
ANALYZER_FORMATTED = ('ANALYZER_SPEC_PATH_UNDER_TEST = (\n'
                      '    ".agents/artifacts/specs/x.md"\n'
                      ')\n')
CLEAN = "tests/clean.py"
CLEAN_TEXT = "VALUE = 1   \n"
FORMAT_COMMANDS = {
    "format": [sys.executable, FORMATTER],
    "broken": [sys.executable, FORMATTER, "--fail"],
    "meddle": [sys.executable, FORMATTER, "--touch", ".gitignore"],
    "spill": [sys.executable, FORMATTER, "--touch", CLEAN],
    "litter": [sys.executable, FORMATTER, "--touch", "stray.txt"],
}
REWRITE_ANALYZER = ("path-reference", ANALYZER_SUBJECT, "rewrite")


def formatting_repo(home: Path) -> Path:
    """`apply_repo` whose verification command is the line-limit lint, with
    the formatter commands, #345's linked tree (a moved Markdown file whose
    link is rewritten), a reference whose rewrite crosses the limit and a
    second Python file that is not format-clean."""
    root = apply_repo(home, verification=(sys.executable, LINT),
                      commands=FORMAT_COMMANDS)
    for path, text in ((LINT, LINT_TEXT), (FORMATTER, FORMATTER_TEXT),
                       (ANALYZER, ANALYZER_TEXT), (CLEAN, CLEAN_TEXT)):
        write(root, path, text)
    commit(root, "add a lint, a formatter and two Python files")
    write_linked_tree(root)
    return root


class ReferenceFormattingApplyTest(ApplyTestCase):
    """#376 AC1, AC4: the declared formatter runs over the reference-edited
    files inside `apply`, confined, before the commit gates."""

    def planned(self, root: Path, *triples: tuple[str, str, str]) -> dict:
        code, out, err = run("plan", "--repo-root", str(root),
                             *answer_args(*triples), home=self.home)
        self.assertEqual(code, 0, err or out)
        document = json.loads(out)
        self.assertEqual(document["plan"]["state"], "ready",
                         document["plan"]["blockers"])
        return document

    def lint(self, root: Path, revision: str) -> int:
        export = Path(tempfile.mkdtemp()) / "tree"
        adopt_inspection.export_commit(root, revision, export)
        return subprocess.run([sys.executable, LINT], cwd=export,
                              capture_output=True, timeout=120).returncode

    def test_the_formatted_rewrite_commits_and_passes_the_lint(self):
        self.assertLessEqual(len(ANALYZER_TEXT) - 1, 60)
        self.assertGreater(len(ANALYZER_REWRITTEN) - 1, 60)
        root = formatting_repo(self.home)
        base = git(root, "rev-parse", "HEAD").strip()
        self.assertEqual(self.lint(root, "HEAD"), 0)
        document = self.planned(root, REWRITE_ANALYZER,
                                ("reference-format", ".py", "format"))
        self.assertEqual(document["reference_formatting"], [
            {"class": ".py", "command": "format", "files": [ANALYZER]}])
        (write_op,) = [op for op in document["changes"]
                       if op["op"] == "write-file"
                       and op["targets"] == [ANALYZER]]
        self.assertEqual(write_op["after"], adopt_inspection.sha256_hash(
            ANALYZER_REWRITTEN.encode("utf-8")))
        moved = {op["targets"][0] for op in document["changes"]
                 if op["op"] == "git-mv"}
        self.assertTrue(any(
            op["op"] == "write-file" and op["targets"][0] in moved
            and adopt_links.is_markdown_path(op["targets"][0])
            for op in document["changes"]))
        result = self.succeed(root, document["plan"]["plan_id"])
        branch = result["branch"]
        self.assertEqual(git(root, "show", f"{branch}:{ANALYZER}"),
                         ANALYZER_FORMATTED)
        self.assertEqual(git(root, "rev-parse", f"{branch}:{CLEAN}"),
                         git(root, "rev-parse", f"HEAD:{CLEAN}"))
        self.assertEqual(self.lint(root, branch), 0)
        required, optional = adopt_apply.expected_commit_paths(
            document["changes"])
        changed = set(git(root, "diff", "--name-only", "--no-renames",
                          base, branch).splitlines())
        self.assertTrue(required <= changed <= required | optional,
                        changed ^ required)
        git(root, "merge", "--ff-only", "--quiet", branch)
        code, out, err = run("verify", "--repo-root", str(root),
                             home=self.home)
        self.assertEqual(code, 0, err or out)
        (check,) = [entry for entry in json.loads(out)["checks"]
                    if entry["id"] == "adoption-commit-derived"]
        self.assertEqual(check["status"], "passed")

    def test_without_a_format_answer_the_lint_gate_refuses(self):
        root = formatting_repo(self.home)
        base = git(root, "rev-parse", "HEAD").strip()
        document = self.planned(root, REWRITE_ANALYZER)
        self.assertEqual(document["reference_formatting"], [
            {"class": ".py", "command": None, "files": [ANALYZER]}])
        self.assert_retained(root, document["plan"]["plan_id"], base,
                             "adopt.gate.workflow-verification-commands")

    def test_an_unconfined_or_failing_formatter_is_refused(self):
        for command, repair_id in (
                ("broken", "adopt.format.failed"),
                ("meddle", "adopt.format.unplanned_content"),
                ("spill", "adopt.gate.worktree-status-matches-operations"),
                ("litter", "adopt.gate.worktree-status-matches-operations")):
            with self.subTest(command=command):
                root = formatting_repo(self.home)
                base = git(root, "rev-parse", "HEAD").strip()
                plan_id = self.planned(
                    root, REWRITE_ANALYZER,
                    ("reference-format", ".py", command))["plan"]["plan_id"]
                self.assert_retained(root, plan_id, base, repair_id)
                record = json.loads(self.state(
                    "adopt", "worktrees",
                    self.digest(plan_id) + ".failure.json").read_text("utf-8"))
                if repair_id.startswith("adopt.format."):
                    self.assertEqual(
                        {gate["status"] for gate in record["gates"]},
                        {"not_run"})

    def test_the_evidence_record_lists_the_format_answer_and_rows(self):
        root = formatting_repo(self.home)
        answers = (REWRITE_ANALYZER, ("reference-format", ".py", "format"))
        document = self.planned(root, *answers)
        result = self.succeed(root, document["plan"]["plan_id"])
        record = json.loads(git(
            root, "show", f"{result['branch']}:{result['evidence_record']}"))
        for question, subject, value in answers:
            with self.subTest(subject=subject):
                self.assertIn(
                    {"id": question, "subject": subject, "value": value},
                    record["decisions_accepted"])
        for member in ("reference_formatting", "reference_policies",
                       "path_references"):
            with self.subTest(member=member):
                self.assertEqual(record[member], document[member])
        self.assertEqual(record["plan_id"], document["plan"]["plan_id"])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_apply.py -k ReferenceFormattingApplyTest` (timeout 1800 s)
Expected: FAIL — the success and evidence tests are refused with `adopt.gate.workflow-verification-commands` (nothing formats yet), and the `broken`/`meddle` cases report that gate instead of `adopt.format.*`. `test_without_a_format_answer_the_lint_gate_refuses` passes already: it pins today's behaviour.

- [ ] **Step 3: Write the minimal implementation**

`python/agent_tools/adopt_apply.py`, after `operation_failure`:
1. `format_failure(repair_id: str, message: str) -> AdoptError` → `refuse("verification_failed", repair_id, "/reference_formatting", message)`.
2. `run_formatting(worktree, operations, rows, run_resolver)` per the **Invariants**: filter to rows with a command; return when none; one `run_resolver(worktree, "resolve")`; read `bindings.commands` through `isinstance` checks exactly as `gate_workflow_verification_commands` does; for each row in order, run `[*entry["argv"], *(str(worktree / path) for path in row["files"])]` with `subprocess.run(..., cwd=entry["cwd"], capture_output=True)` (catch `OSError` and `subprocess.SubprocessError`), then `run_git(worktree, "add", "--", *row["files"])`; any failure raises `format_failure("adopt.format.failed", ...)`; finally `prove_formatting_confined(worktree, operations, <every formatted file>)`. Docstring: what it runs, where the command comes from, that the files are staged, the no-command no-op, and the repair ids.
3. `prove_formatting_confined(worktree, operations, formatted)`: build `last[target] = operation` over the operations in order for every operation with `targets` and a non-null `after`; for each `target, operation` in sorted order not in `formatted`, require `operation_result_matches(worktree, operation)`; for each formatted path, require `(worktree / path).is_file() and not (worktree / path).is_symlink()`; any failure raises `format_failure("adopt.format.unplanned_content", ...)`. Docstring: why the last operation decides (a moved file a later write edits is judged by the write, D9) and that the status gate and commit-content proof cover unplanned paths.
4. The module docstring's list of what the module holds gains the formatting step and its confinement proof.

`python/agent_tools/adopt_project.py`, `command_apply`: inside the existing `try` that executes the operations, after the loop, call `adopt_apply.run_formatting(worktree, changes, composed.document["reference_formatting"], run_resolver)`, so a failure takes the same `retain_failure` path with every commit gate `not_run`. The module docstring's `apply` paragraph says the declared formatter runs over the reference-edited files after the operations and before the gates.

`python/README.md` § `adopt-project`, a new paragraph after the policy paragraphs, written from the implemented code, stating: `plan --answer reference-format <class> <command-id>` declares a formatter for a file class and opens no question; it is validated after the other ids in `(subject, value)` order, refusing `adopt.decisions.invalid_answer` for a repeated subject or an id that is no `bindings.commands` key of the authored contract (always, without a contract) and `adopt.decisions.unmatched_answer` for a class no settled answer edits; `reference_formatting` rows (`class`, `command`, `files`) cover each class with a file the path-reference answers edit, never Markdown link rewrites, the contract, the records or projections; the rows are the tenth `plan_id` input and an evidence-record member, and a plan stored before this change is refused as stale; the human view's `format <class>: <n> files, command <id or none>` line; the step in `apply` (after the operations, before the gates, its own `resolve` of the worktree, `argv` plus the absolute file paths at `cwd`, output captured, no timeout, files staged); the confinement proof; the two repair ids with the worktree retained and the gates `not_run`; that the status gate refuses an unplanned or untracked change; that a write's published `after` stays the unformatted hash; and the command's interface: it takes file paths as trailing arguments, rewrites them in place, formats whole files, and leaves no untracked, unignored file.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_apply.py` (timeout 2400 s)
Expected: PASS, no failures — `ReferenceFormattingApplyTest` and every existing class.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_verify.py` (timeout 1800 s)
Expected: PASS, no failures (`verify` unchanged).

Run: `rg -q "adopt.format.unplanned_content" python/README.md && rg -q "reference-format" python/README.md`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_apply.py python/agent_tools/adopt_project.py python/README.md home/common/agent-skills/tests/test_adopt_apply.py
launch-commit … -- -m "feat(adopt): run the declared formatter over reference edits inside apply (#376)"
```
