# Task 2: Variable-joined paths in plan and apply, and their documentation

**Files:**
- Modify: `python/agent_tools/adopt_planning.py` (`reference_questions` only)
- Modify: `python/README.md` (§ `adopt-project`)
- Test: `home/common/agent-skills/tests/test_adopt_project.py`
- Test: `home/common/agent-skills/tests/test_adopt_apply.py`

**Interfaces:**
- Consumes (Task 1): `Occurrence.occurrence_class`, `Occurrence.policy` (`<tree>:<occurrence class>`), `Occurrence.variable`, `policy_summary` rows whose `class` is the occurrence class.
- Produces: the test fixture names below in `test_adopt_project.py`, imported by `test_adopt_apply.py` (Task 4 does not use them).

**Invariants:**
- A `reference-policy` question's `value` is `recommended_answer(<occurrence class>)`, so a `/variable` policy opens with `value` null (D8).
- `.claude/notes:.sh` and `.claude/notes:.sh/variable` are two questions; answering one leaves the other open (D8).
- A variable-joined occurrence in a file the plan does not move opens an ordinary `path-reference` question (D7).
- A file outside the shell classes yields no variable-joined row (D7, AC3).
- `rewrite` writes the moved script at its destination as one `write-file` after its `git-mv`; `retain` leaves its blob identical to the base blob (D8, 372 D1).

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_adopt_project.py`, after `POLICY_ROWS`/`MAKEFILE_AFTER` and `write_policy_tree`/`policy_repo`, add:

```python
JOBS_DIR = ".claude/notes/jobs"
JOBS_NEW = ".agents/artifacts/notes/jobs"
JOBS_SCRIPT = f"{JOBS_DIR}/run.sh"
COLLECT = "tools/collect"
SH_POLICY = ".claude/notes:.sh"
SH_VARIABLE_POLICY = ".claude/notes:.sh/variable"
JOBS_LITERAL = f"{JOBS_SCRIPT}:3:6"
JOBS_VARIABLE = f"{JOBS_SCRIPT}:4:6"
COLLECT_SUBJECT = f"{COLLECT}.sh:2:6"
VARIABLE_REWRITE_ANSWERS = (
    ("path-reference", COLLECT_SUBJECT, "rewrite"),
    ("reference-policy", SH_POLICY, "rewrite"),
    ("reference-policy", SH_VARIABLE_POLICY, "rewrite"),
)
VARIABLE_RETAIN_ANSWERS = tuple(
    (question, subject, "retain")
    for question, subject, _ in VARIABLE_REWRITE_ANSWERS)


def variable_code(suffix: str = ".sh") -> dict[str, str]:
    """#376: a moved script with one literal and one `$root/`-joined path
    into its own tree, the file both name, and an unmoved script with one
    `${ROOT}/`-joined path into it; `suffix` is both scripts' class."""
    return {
        f"{JOBS_DIR}/run{suffix}": (
            "#!/bin/sh\n"
            'root="$1"\n'
            f'cat "{JOBS_DIR}/data.txt"\n'
            f'cat "$root/{JOBS_DIR}/data.txt"\n'),
        f"{JOBS_DIR}/data.txt": "jobs\n",
        f"{COLLECT}{suffix}": (
            "#!/bin/sh\n"
            f'cat "${{ROOT}}/{JOBS_DIR}/data.txt"\n'),
    }


def write_variable_tree(root: Path, suffix: str = ".sh") -> None:
    for path, text in variable_code(suffix).items():
        write(root, path, text)
    commit(root, "add shell scripts that join paths to a variable")
```

and, after `ReferencePolicyPlanTest`, the class:

```python
class VariablePolicyPlanTest(AdoptTestCase):
    """#376 D7, D8, D10: variable-joined paths in shell files are asked
    about under their own policy, never with `extend`."""

    def answered(self, root: Path, *triples: tuple[str, str, str]) -> object:
        code, doc, err = self.plan(root, *answer_args(*triples))
        self.assertEqual(code, 0, err or doc)
        return doc

    def variable_repo(self, suffix: str = ".sh") -> Path:
        root = nix_config_shape_repo(self.home)
        write_variable_tree(root, suffix)
        return root

    def opened(self, doc: object) -> list[tuple]:
        return [(entry["id"], entry["subject"], entry.get("value"))
                for entry in doc["decisions"]["open"]]

    def test_variable_paths_open_their_own_policy(self):
        doc = self.answered(self.variable_repo())
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(
            [(row["subject"], row["answers"], row["replacement"],
              row["target"], row["policy"]) for row in doc["path_references"]],
            [(JOBS_LITERAL, ["rewrite", "retain"], f"{JOBS_NEW}/data.txt",
              f"{JOBS_NEW}/run.sh", SH_POLICY),
             (JOBS_VARIABLE, ["rewrite", "retain"],
              f"$root/{JOBS_NEW}/data.txt", f"{JOBS_NEW}/run.sh",
              SH_VARIABLE_POLICY),
             (COLLECT_SUBJECT, ["rewrite", "retain"],
              f"${{ROOT}}/{JOBS_NEW}/data.txt", f"{COLLECT}.sh", None)])
        self.assertEqual(self.opened(doc), [
            ("path-reference", COLLECT_SUBJECT, None),
            ("reference-policy", SH_POLICY, "rewrite"),
            ("reference-policy", SH_VARIABLE_POLICY, None)])
        self.assertEqual(doc["reference_policies"], [
            policy_row(SH_POLICY, "rewrite", 1, 1),
            policy_row(SH_VARIABLE_POLICY, None, 1, 1)])

    def test_the_literal_policy_never_decides_a_variable_occurrence(self):
        doc = self.answered(self.variable_repo(),
                            ("reference-policy", SH_POLICY, "rewrite"))
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(self.opened(doc), [
            ("path-reference", COLLECT_SUBJECT, None),
            ("reference-policy", SH_VARIABLE_POLICY, None)])
        self.assertEqual(
            [(row["subject"], row["answer"], row["decided_by"])
             for row in doc["path_references"]],
            [(JOBS_LITERAL, "rewrite", "policy"), (JOBS_VARIABLE, None, None),
             (COLLECT_SUBJECT, None, None)])

    def test_every_answer_reaches_ready_with_one_write_per_script(self):
        doc = self.answered(self.variable_repo(), *VARIABLE_REWRITE_ANSWERS)
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        code = variable_code()
        for target, text in (
                (f"{JOBS_NEW}/run.sh",
                 code[JOBS_SCRIPT].replace(JOBS_DIR, JOBS_NEW)),
                (f"{COLLECT}.sh",
                 code[f"{COLLECT}.sh"].replace(JOBS_DIR, JOBS_NEW))):
            with self.subTest(target=target):
                (op,) = [op for op in doc["changes"]
                         if op["op"] == "write-file"
                         and op["targets"] == [target]]
                self.assertEqual(op["after"],
                                 sha256_hash(text.encode("utf-8")))

    def test_a_non_shell_class_reads_no_variable(self):
        doc = self.answered(self.variable_repo(".py"))
        self.assertEqual(
            [(row["subject"], row["policy"])
             for row in doc["path_references"]],
            [(f"{JOBS_DIR}/run.py:3:6", ".claude/notes:.py")])
```

In `home/common/agent-skills/tests/test_adopt_apply.py`, add `COLLECT`, `JOBS_DIR`, `JOBS_NEW`, `JOBS_SCRIPT`, `VARIABLE_RETAIN_ANSWERS`, `VARIABLE_REWRITE_ANSWERS`, `variable_code` and `write_variable_tree` to the sorted `from .test_adopt_project import (...)` list, and after `ReferencePolicyApplyTest`:

```python
class VariablePolicyApplyTest(ApplyTestCase):
    """#376 AC2: a `$var/`-joined path is rewritten at the destination in
    the adoption commit, or its file is left byte-identical."""

    def applied(self, answers: tuple) -> tuple[Path, dict, dict]:
        root = apply_repo(self.home)
        write_variable_tree(root)
        code, out, err = run("plan", "--repo-root", str(root),
                             *answer_args(*answers), home=self.home)
        self.assertEqual(code, 0, err or out)
        document = json.loads(out)
        self.assertEqual(document["plan"]["state"], "ready",
                         document["plan"]["blockers"])
        return root, document, self.succeed(root, document["plan"]["plan_id"])

    def test_rewrite_lands_at_the_destination(self):
        root, document, result = self.applied(VARIABLE_REWRITE_ANSWERS)
        branch = result["branch"]
        code = variable_code()
        script = git(root, "show", f"{branch}:{JOBS_NEW}/run.sh")
        self.assertEqual(script,
                         code[JOBS_SCRIPT].replace(JOBS_DIR, JOBS_NEW))
        self.assertIn(f'"$root/{JOBS_NEW}/data.txt"', script)
        self.assertNotIn(".claude/", script)
        self.assertEqual(
            git(root, "show", f"{branch}:{COLLECT}.sh"),
            code[f"{COLLECT}.sh"].replace(JOBS_DIR, JOBS_NEW))
        record = json.loads(git(
            root, "show", f"{branch}:{result['evidence_record']}"))
        for question, subject, value in VARIABLE_REWRITE_ANSWERS:
            with self.subTest(subject=subject):
                self.assertIn(
                    {"id": question, "subject": subject, "value": value},
                    record["decisions_accepted"])
        self.assertEqual(record["reference_policies"],
                         document["reference_policies"])
        self.assertEqual(record["path_references"],
                         document["path_references"])

    def test_retain_keeps_the_base_blob(self):
        root, _, result = self.applied(VARIABLE_RETAIN_ANSWERS)
        branch = result["branch"]
        self.assertEqual(
            git(root, "rev-parse", f"{branch}:{JOBS_NEW}/run.sh"),
            git(root, "rev-parse", f"HEAD:{JOBS_SCRIPT}"))
        self.assertEqual(git(root, "show", f"{branch}:{COLLECT}.sh"),
                         git(root, "show", f"HEAD:{COLLECT}.sh"))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py -k VariablePolicyPlanTest` (timeout 1800 s)
Expected: FAIL — `test_variable_paths_open_their_own_policy` and `test_the_literal_policy_never_decides_a_variable_occurrence` see `"rewrite"` instead of `None` as the `.sh/variable` question's `value` (`reference_questions` still derives the class from the file name). The other two may pass already on Task 1's head; that is expected.

- [ ] **Step 3: Write the minimal implementation**

`python/agent_tools/adopt_planning.py`, `reference_questions`: build the subject-to-class map from `occurrence.occurrence_class` instead of `adopt_references.file_class(occurrence.path)`, so `value` is `recommended_answer` of the occurrence class. In its docstring, say the class is the occurrence's class (`<file class>/variable` for a variable-joined occurrence) and that the value is null for a class outside the recommendation table, which every `/variable` class is.

`python/README.md` § `adopt-project`, written from the implemented code:
- In the `path-reference` paragraph, narrow "Variables are not followed" and "a joined path is not resolved as a whole" to what is still true: a variable is never followed to its definition, and outside the variable reading a joined path is not resolved as a whole.
- A new paragraph after the pattern-reading one, stating: the shell classes `.sh`, `.bash`, `.zsh` (class of the file's base path); the third reading is tried only when the plain and pattern readings leave a token without an occurrence; the prefix `$name/` or `${name}/` at the start of the token, `name` a letter or `_` then letters, digits and `_`; the path is the longest leading run of non-empty segments without a glob character or `$`, and the rest is the tail; the carried form is prefix, successor and tail and must be one token that reads back to the successor; such an occurrence offers `rewrite` (single successor with a carried form) and `retain`, never `extend`; positional and special parameters, parameter expansions, a variable not at the start of the token and a second variable before the path are not read; `$(...)/path` is already a plain root-anchored occurrence because `(`, `)` and the backtick delimit tokens.
- In the policy paragraph: the class of an occurrence the variable reading made is `<file class>/variable`, so its policy is `<tree>:<class>/variable`, its `reference-policy` question's `value` is null and a `<tree>:<class>` answer never decides it; in a file the plan does not move it opens an ordinary `path-reference` question; the `path_references` row is unchanged (its `literal` shows the variable).

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py` (timeout 1800 s)
Expected: PASS, no failures — the new `VariablePolicyPlanTest` and every existing class (`PathReferencePlanTest`, `ReferencePolicyPlanTest`, `LinkRewritePlanTest` unchanged).

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_apply.py -k VariablePolicyApplyTest -k ReferencePolicyApplyTest -k PathReferenceApplyTest` (timeout 1800 s)
Expected: PASS, no failures.

Run: `if rg -q "Variables are not followed" python/README.md; then exit 1; fi; rg -q "/variable" python/README.md`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_planning.py python/README.md home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_apply.py
launch-commit … -- -m "feat(adopt): ask about variable-joined shell paths under their own policy (#376)"
```
