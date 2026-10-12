# Task 5: The answered fixture applies in one commit, and the documented contract

Spec rows: D1 (apply needs no change), D5 (the evidence record), D7 (the settings file stays), D9 (the documented prefilter limit). Read the plan root's Global Constraints first.

This task adds no production code. Its tests prove, through the real `plan` and `apply` verbs, what Tasks 1 to 4 built; its second half writes the command contract into `python/README.md`.

**Files:**
- Modify: `python/README.md` (§ `adopt-project` only)
- Test: `home/common/agent-skills/tests/test_adopt_apply.py`

**Interfaces:**
- Consumes, from Task 4 in `home/common/agent-skills/tests/test_adopt_project.py`: `POLICY_DIR`, `POLICY_NEW`, `POLICY_CODE` (base text by base path), `POLICY_REWRITTEN` (expected text by post-move path, for the five edited files), `POLICY_READY_ANSWERS` (the five `(id, subject, value)` triples that make the fixture `ready`), `RUN_REPORT`, `LINT_TOML`, `SETTINGS`, `answer_args(*triples) -> list[str]`, `write_policy_tree(root)`. From `test_adopt_apply.py` at base: `apply_repo(home)`, `ApplyTestCase` (`succeed`, `branch_files`), `run`, `git`.
- Consumes, from the product: the plan document's `path_references`, `reference_policies`, `decisions.answered`; the evidence record's `decisions_accepted`, `sources`, `path_references`, `reference_policies`.
- Produces: `ReferencePolicyApplyTest` and the README contract. Nothing later depends on it.

**Invariants:**
- The adoption branch is exactly one commit ahead of the base.
- Every file in `POLICY_REWRITTEN` holds exactly that text at that path, and no path under `.claude/notes` remains.
- The JSON record (class answered `retain`), the settings file and a file no answer names are byte-identical to their base blobs.
- The outside script exits 0 with the same output on an export of the base and of the adoption commit.
- `python/agent_tools/adopt_apply.py` is not edited.

- [ ] **Step 1: Write the apply tests**

In `home/common/agent-skills/tests/test_adopt_apply.py`, add `LINT_TOML`, `POLICY_CODE`, `POLICY_DIR`, `POLICY_NEW`, `POLICY_READY_ANSWERS`, `POLICY_REWRITTEN`, `RUN_REPORT`, `SETTINGS`, `answer_args` and `write_policy_tree` to the `from .test_adopt_project import (...)` list (keep it sorted), and add after `class MovedFileReferenceApplyTest` (Task 3):

```python
class ReferencePolicyApplyTest(ApplyTestCase):
    """#372: moved code is rewritten at its destination, by class, in the
    one adoption commit."""

    def applied(self) -> tuple[Path, dict, dict]:
        """The policy fixture, planned with every answer and applied."""
        root = apply_repo(self.home)
        write_policy_tree(root)
        code, out, err = run("plan", "--repo-root", str(root),
                             *answer_args(*POLICY_READY_ANSWERS),
                             home=self.home)
        self.assertEqual(code, 0, err or out)
        document = json.loads(out)
        self.assertEqual(document["plan"]["state"], "ready",
                         document["plan"]["blockers"])
        return root, document, self.succeed(root, document["plan"]["plan_id"])

    def run_report(self, root: Path, revision: str) -> tuple[int, str]:
        """The fixture's outside script, run from the root of an export of
        `revision`."""
        export = Path(tempfile.mkdtemp()) / "tree"
        adopt_inspection.export_commit(root, revision, export)
        proc = subprocess.run(
            [sys.executable, RUN_REPORT], cwd=export, capture_output=True,
            text=True, timeout=120)
        return proc.returncode, proc.stdout

    def test_rewritten_files_land_at_their_destinations_in_one_commit(self):
        root, _, result = self.applied()
        branch = result["branch"]
        self.assertEqual(
            git(root, "rev-list", "--count", f"HEAD..{branch}").strip(), "1")
        for path, text in POLICY_REWRITTEN.items():
            with self.subTest(path=path):
                self.assertEqual(git(root, "show", f"{branch}:{path}"), text)
        for path in (f"{POLICY_NEW}/report.py", f"{POLICY_NEW}/paths.py",
                     f"{POLICY_NEW}/devenv.nix", RUN_REPORT):
            with self.subTest(path=path):
                self.assertNotIn(".claude/",
                                 git(root, "show", f"{branch}:{path}"))
        self.assertEqual(
            [path for path in self.branch_files(root, branch)
             if path.startswith(".claude/notes")], [])

    def test_the_outside_command_runs_on_the_adopt_commit_as_on_base(self):
        root, _, result = self.applied()
        base = self.run_report(root, "HEAD")
        self.assertEqual(base, (0, "study\n"))
        self.assertEqual(self.run_report(root, result["branch"]), base)

    def test_the_pattern_exclusion_is_extended(self):
        root, document, result = self.applied()
        (row,) = [row for row in document["path_references"]
                  if row["path"] == LINT_TOML]
        self.assertEqual((row["literal"], row["answer"]),
                         (r"^\\.claude/", "extend"))
        text = git(root, "show", f"{result['branch']}:{LINT_TOML}")
        self.assertEqual(text, POLICY_REWRITTEN[LINT_TOML])
        for element in ('"^\\\\.claude/"', *(
                f'"{addition}"' for addition in row["additions"])):
            with self.subTest(element=element):
                self.assertIn(element, text)
        self.assertEqual(len(row["additions"]), 3)

    def test_the_settings_file_stays_in_place_with_a_null_destination(self):
        root, document, result = self.applied()
        branch = result["branch"]
        self.assertEqual(git(root, "show", f"{branch}:{SETTINGS}"),
                         git(root, "show", f"HEAD:{SETTINGS}"))
        self.assertEqual(
            [op for op in document["changes"]
             if SETTINGS in op["sources"] + op["targets"]], [])
        record = json.loads(git(
            root, "show", f"{branch}:{result['evidence_record']}"))
        (source,) = [row for row in record["sources"]
                     if row["path"] == SETTINGS]
        self.assertIsNone(source["after"])
        self.assertIsNotNone(source["before"])

    def test_retained_and_unnamed_files_keep_their_bytes(self):
        root, _, result = self.applied()
        branch = result["branch"]
        for old, new in ((f"{POLICY_DIR}/record.json",
                          f"{POLICY_NEW}/record.json"),
                         (".agents/instructions/bootstrap.md",
                          ".agents/instructions/bootstrap.md")):
            with self.subTest(path=new):
                self.assertEqual(git(root, "show", f"{branch}:{new}"),
                                 git(root, "show", f"HEAD:{old}"))
        self.assertEqual(
            git(root, "show", f"{branch}:{POLICY_NEW}/record.json"),
            POLICY_CODE[f"{POLICY_DIR}/record.json"])

    def test_the_evidence_record_lists_the_policy_answers_and_rows(self):
        root, document, result = self.applied()
        record = json.loads(git(
            root, "show", f"{result['branch']}:{result['evidence_record']}"))
        for question, subject, value in POLICY_READY_ANSWERS:
            with self.subTest(subject=subject):
                self.assertIn(
                    {"id": question, "subject": subject, "value": value},
                    record["decisions_accepted"])
        self.assertEqual(record["reference_policies"],
                         document["reference_policies"])
        self.assertEqual(record["path_references"],
                         document["path_references"])
        self.assertEqual(
            [(row["class"], row["answer"], row["open"])
             for row in record["reference_policies"]],
            [(".json", "retain", 0), (".nix", "rewrite", 0),
             (".py", "rewrite", 0)])
        self.assertEqual(record["plan_id"], document["plan"]["plan_id"])
```

Facts the cases rest on: `apply_repo` tracks `.claude/specs/x.md`, `.claude/plans/y.md` and a `.gitignore`, so every path the fixture names exists at base and `.claude/specs` is wholly moved; `tools/run_report.py` runs `report.py` by its repository-relative path with the export root as working directory, and `report.py` prints the `title` of `record.json` (`study`), opened by the path literal the `.py` policy rewrites; `.agents/instructions/bootstrap.md` is read by the projection regeneration and written by no operation. In `test_the_pattern_exclusion_is_extended`, `'"^\\\\.claude/"'` is the quoted element as the file spells it: two backslashes.

- [ ] **Step 2: Run the apply tests**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_apply.py -k ReferencePolicyApplyTest` (timeout 1800 s)
Expected: PASS, six cases. These cases have no red phase of their own: every behavior they observe was driven red-then-green at its own seam in Tasks 1 to 4. Prove that they can fail before going on: temporarily change `POLICY_READY_ANSWERS`' `.py` value to `retain` in `test_adopt_project.py`, rerun, and see `test_rewritten_files_land_at_their_destinations_in_one_commit` and `test_the_outside_command_runs_on_the_adopt_commit_as_on_base` fail (the second with a non-zero exit from the moved script, which still opens the old record path); then restore the value (`git diff --stat -- home/common/agent-skills/tests/test_adopt_project.py` prints nothing).

If a case fails with the fixture as written, the defect is in the code of Task 1, 3 or 4: reproduce it with a failing case at that task's seam (`test_adopt_references.py` or `test_adopt_project.py`), fix it in the module that task names, and say so in the report. A failure inside `apply` itself (a refusal with a `repair_id` under `adopt.gate.` or `adopt.commit.`) contradicts the spec's claim that `apply` needs no change: stop and report it with the `repair_id`; do not edit `adopt_apply.py`.

- [ ] **Step 3: Write the contract into `python/README.md`**

Edit the `## adopt-project` section only. Read the three paragraphs that start "`adopt-project plan` asks three kinds of open question", "`adopt-project plan` rewrites relative Markdown link targets" and "`adopt-project plan` asks about every path literal" before editing, and write every sentence from the code as implemented, in the section's existing register (present tense, the code names in backticks, no changelog voice, `https://github.com/fagenorn/nix-config/issues/372` cited once in full).

Corrections to what is there:

- The first paragraph counts three kinds of question and names two answerable ids in its `adopt.decisions.invalid_answer` list: there are four kinds and three answerable ids.
- The path-reference paragraph says the scan leaves out move sources: remove that clause; the scan still leaves out `.agents/artifacts/`, `.agents/knowledge/archive/` (tested on the base path, so a file is editable only by the adoption that moves it) and the files adoption itself may write.
- The same paragraph says each occurrence opens a `path-reference` question and lists nine row members and "the eighth input of `plan_id`": state the rule below instead, twelve row members, and `reference_policies` as the ninth input.
- Its closing list of what is not recognised must not contradict the pattern reading.

Facts to add, each exactly as the code behaves:

1. A move source is read; an occurrence's `path` and `subject` stay the base path, and its row's `target` is the file's destination, or its own path when the plan does not move it. An edited moved file is one `write-file` at its target after its `git-mv`, in the same commit, with `before` the hash of the base bytes.
2. Every occurrence in a moved file belongs to one policy, subject `<tree>:<class>`: the tree is the classification row's path, or the candidate's own path for an `archive-history` answer; the class is the lowercased text from the last dot of the file name, or `-` for a name with no such suffix (a dotfile included). A file the plan does not move has no policy.
3. The `reference-policy` question: its seven members, `answers` `rewrite` and `retain`, and `value` from the closed table (the twelve `rewrite` classes, the seven `retain` classes, null otherwise). The recommendation is printed and never applied.
4. Precedence: an occurrence's own `path-reference` answer; else its policy's answer when the occurrence offers that value; else none — so a `rewrite` policy leaves an occurrence that offers no `rewrite` open. `extend` is never a policy answer.
5. Which questions open: a policy while it is unanswered and one of its occurrences has no answer of its own, during which those occurrences open no question of their own (they stay listed in `path_references` and can still be answered individually); after the policy is answered, each occurrence still without an effective answer opens `path-reference`. Order: by id as in `QUESTION_IDS`, policies by subject.
6. `plan --answer reference-policy SUBJECT VALUE`: validated after the other two ids; `adopt.decisions.unmatched_answer` for a subject that is no policy of this inspection, `adopt.decisions.invalid_answer` for a value outside the two or a subject answered twice.
7. Row members `target`, `policy`, `decided_by` (`occurrence`, `policy` or null), with `answer` the effective answer; `reference_policies`, one row per policy sorted by subject, with its thirteen members and what each count means, carried by the plan document and the evidence record and the ninth input of `plan_id`; the two human-view lines. A plan stored before this change no longer equals its re-derivation, so `apply` refuses it and the operator plans again.
8. The pattern reading: tried only for a token the plain reading does not make an occurrence, and only when it starts with `^` or holds `\.`; the anchor, the escape (`\\.` before `\.`), the optional `/` prefix; the decoded path and verbatim tail; carried forms keep anchor, escape and tail and exist only for a successor of letters, digits, `_`, `-`, `.` and `/`. Not read: an end anchor, character classes, groups, alternation, a `./` prefix inside a pattern. The prefilter limit of D9: a file is scanned only when it holds the first path segment of a move source as written, so an escaped first segment with an interior dot is not found.
9. The settings row: a tracked `.claude/settings.json` is `legacy-native-store` / `retain-product`, opens no question, is named by no operation, and appears in the plan's `evidence` and in the record's `sources` with `after` null; path literals inside it are ordinary occurrences.

Do not edit any other section, `CLAUDE.md`, or a file under `.agents/instructions/`.

- [ ] **Step 4: Verify**

README gates (each must hold; the first three fail at this task's starting commit):

```bash
set -eu
f=python/README.md
grep -q 'reference-policy' "$f"
grep -q 'reference_policies' "$f"
grep -q 'issues/372' "$f"
if grep -q 'leaving out move sources' "$f"; then exit 1; fi
if grep -q 'asks three kinds of open question' "$f"; then exit 1; fi
if grep -q 'the eighth input of `plan_id`' "$f"; then exit 1; fi
git diff --quiet 32807f90d4a4 -- CLAUDE.md AGENTS.md .agents/instructions
```

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_apply.py` (timeout 1800 s)
Expected: PASS, every case of the file.

Scope gate: `git diff --stat 32807f90d4a4 -- python/agent_tools/adopt_apply.py python/agent_tools/adopt_links.py python/agent_tools/adopt_verify.py` prints nothing.

The plan's final gate (`just agent-workflow-tests`, then `just build`) is run once on this task's commit by the executing skill, not here; AC7 is that first command exiting 0.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_adopt_apply.py python/README.md
git commit -m "test(adopt): apply the class-policy fixture in one commit and document the contract (#372)"
```
