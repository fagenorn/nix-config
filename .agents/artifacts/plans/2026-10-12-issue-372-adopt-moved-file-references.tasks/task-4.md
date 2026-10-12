# Task 4: The `reference-policy` question, its answers, `reference_policies`, the ninth `plan_id` input and the human view

Spec rows: D2, D3, D4 (the question, its answers, precedence, which questions open), D5 (what the plan reports). Read the plan root's Global Constraints first.

**Files:**
- Modify: `python/agent_tools/adopt_inspection.py` (`QUESTION_IDS`, a basis constant, `question_impact`, `question_recommendation`)
- Modify: `python/agent_tools/adopt_planning.py` (`apply_answers`, `reference_questions`, `policy_answers`, `compute_plan_id`, `bookkeeping_operations`)
- Modify: `python/agent_tools/adopt_project.py` (`compose_plan`, `emit_human`)
- Test: `home/common/agent-skills/tests/test_adopt_project.py`

**Interfaces:**
- Consumes, from Task 3 in `adopt_references`: `POLICY_ANSWERS`, `recommended_answer(file_class)`, `file_class(path)`, `Occurrence.policy`, `Occurrence.tree`, `effective_answer(occurrence, answers, policies) -> (answer | None, "occurrence" | "policy" | None)`, `summary(references, answers, policies)`, `policy_summary(references, answers, policies)`, `rewritten(references, answers, policies)`. From Task 2: a tracked `.claude/settings.json` opens no question.
- Produces:
  - `adopt_inspection.QUESTION_IDS == ("project-id", "candidate-class", "path-reference", "reference-policy")` and `adopt_inspection.REFERENCE_POLICY_BASIS: str`.
  - `adopt_planning.policy_answers(answered: list[dict]) -> dict[str, str]`.
  - `adopt_planning.reference_questions(references: References, answers: dict[str, str], policies: dict[str, str]) -> list[dict]`.
  - `adopt_planning.compute_plan_id(project_id, base_revision, platform_block, evidence, answered, link_rewrites, path_references, reference_policies) -> str`.
  - `adopt_planning.bookkeeping_operations(found, plan_id, outcome, base_revision, platform_block, decisions, ready_gates, link_rewrites, path_references, reference_policies)`.
  - The plan document and the adoption evidence record carry `reference_policies` (the rows `policy_summary` returns). The document has ten top-level members.
  - Test helpers Task 5 imports from `test_adopt_project.py`: `POLICY_DIR`, `POLICY_NEW`, `POLICY_CODE`, `POLICY_REWRITTEN`, `POLICY_READY_ANSWERS`, `RUN_REPORT`, `LINT_TOML`, `SETTINGS`, `answer_args`, `write_policy_tree`.

**Invariants:**
- An unanswered policy with at least one occurrence that has no answer of its own keeps the plan `draft` through `no-open-decisions`, whatever its recommended `value`.
- While a policy question is open, none of its occurrences opens a `path-reference` question; once it is answered, each occurrence still without an effective answer does.
- Open questions are ordered by id as in `QUESTION_IDS`, policies by subject.
- A refused answer changes nothing and stores nothing; the only repair ids are `adopt.decisions.unmatched_answer` and `adopt.decisions.invalid_answer`.
- `reference_policies` is derived and published for every outcome, like `path_references`; `EVIDENCE_RECORD_MEMBERS` does not grow.
- `decisions.answered` entries stay exactly `{id, subject, value}`.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_adopt_project.py`:

(a) Move the existing pins:

- `TOP_LEVEL_MEMBERS` gains `"reference_policies"` between `"plan"` and `"schema_version"` (the list is sorted); rename `test_exactly_nine_top_level_members` to `test_exactly_ten_top_level_members`.
- `documented_plan_id`: `source` gains `"reference_policies": doc["reference_policies"]`; its docstring says nine members.
- `TypedOperationTest.test_the_evidence_record_carries_this_plans_own_outcome`: `record` gains `"reference_policies": doc["reference_policies"],` after `"path_references"`.
- `CandidateQuestionTest.test_the_question_set_is_closed`: the expected tuple becomes `("project-id", "candidate-class", "path-reference", "reference-policy")`.
- Every existing `adopt_planning.compute_plan_id(...)` call gains a ninth argument, the `reference_policies` member of the same document its `path_references` argument comes from. There are four calls: two in `LinkRewritePlanTest` and two in `PathReferencePlanTest.test_the_answer_is_covered_by_the_plan_id` (there the second call, which passes `other`, also passes `extended["reference_policies"]`).

(b) Add after `write_moved_tool` (Task 3):

```python
POLICY_DIR = ".claude/notes/study"
POLICY_NEW = ".agents/artifacts/notes/study"
RUN_REPORT = "tools/run_report.py"
LINT_TOML = "tools/lint.toml"
SETTINGS = ".claude/settings.json"
# The Markdown of the policy fixture: one outbound link the move changes.
POLICY_MARKDOWN = {
    f"{POLICY_DIR}/README.md":
        "# study\n\nIgnored: [ignore](../../../.gitignore).\n",
}
# Two scripts, a Nix module and a JSON record inside `.claude/notes` that each
# name a path under a moved tree; a script outside it that runs one of them by
# path; a TOML list with a regex-form exclude; a tracked native settings file.
POLICY_CODE = {
    f"{POLICY_DIR}/report.py": (
        "import json\n\n"
        f'RECORD = "{POLICY_DIR}/record.json"\n'
        'print(json.load(open(RECORD))["title"])\n'),
    f"{POLICY_DIR}/paths.py": (
        'SPECS = ".claude/specs"\nPLAN = ".claude/plans/y.md"\n'),
    f"{POLICY_DIR}/devenv.nix": (
        "{ ... }:\n{\n" f'  env.STUDY_HOME = "{POLICY_DIR}";\n' "}\n"),
    f"{POLICY_DIR}/record.json": (
        '{"title": "study", "source": ".claude/specs/x.md"}\n'),
    RUN_REPORT: (
        "import subprocess\nimport sys\n\nsys.exit(subprocess.run(\n"
        f'    [sys.executable, "{POLICY_DIR}/report.py"]).returncode)\n'),
    LINT_TOML: (
        "[tool.check]\n"
        r'exclude = ["^var/", "^\\.claude/", "^\\.worktrees/"]' "\n"),
    SETTINGS: '{"hooks": {}}\n',
}
# What each edited file holds, at the path it has after the moves, once every
# policy and outside occurrence is answered as in `POLICY_READY_ANSWERS`.
POLICY_REWRITTEN = {
    f"{POLICY_NEW}/report.py":
        POLICY_CODE[f"{POLICY_DIR}/report.py"].replace(POLICY_DIR, POLICY_NEW),
    f"{POLICY_NEW}/paths.py": (
        'SPECS = ".agents/artifacts/specs"\n'
        'PLAN = ".agents/artifacts/plans/y.md"\n'),
    f"{POLICY_NEW}/devenv.nix":
        POLICY_CODE[f"{POLICY_DIR}/devenv.nix"].replace(POLICY_DIR,
                                                        POLICY_NEW),
    RUN_REPORT: POLICY_CODE[RUN_REPORT].replace(POLICY_DIR, POLICY_NEW),
    LINT_TOML: (
        "[tool.check]\n"
        r'exclude = ["^var/", "^\\.claude/", '
        r'"^\\.agents/artifacts/notes/", "^\\.agents/artifacts/plans/", '
        r'"^\\.agents/artifacts/specs/", "^\\.worktrees/"]' "\n"),
}
JSON_POLICY = ".claude/notes:.json"
NIX_POLICY = ".claude/notes:.nix"
PY_POLICY = ".claude/notes:.py"
RUN_SUBJECT = f"{RUN_REPORT}:5:23"
LINT_SUBJECT = f"{LINT_TOML}:2:22"
POLICY_READY_ANSWERS = (
    ("reference-policy", JSON_POLICY, "retain"),
    ("reference-policy", NIX_POLICY, "rewrite"),
    ("reference-policy", PY_POLICY, "rewrite"),
    ("path-reference", LINT_SUBJECT, "extend"),
    ("path-reference", RUN_SUBJECT, "rewrite"),
)
# `(subject, answers, target, policy)` of every row, in row order.
POLICY_ROWS = [
    (f"{POLICY_DIR}/devenv.nix:3:21", ["rewrite", "retain"],
     f"{POLICY_NEW}/devenv.nix", NIX_POLICY),
    (f"{POLICY_DIR}/paths.py:1:10", ["rewrite", "retain"],
     f"{POLICY_NEW}/paths.py", PY_POLICY),
    (f"{POLICY_DIR}/paths.py:2:9", ["rewrite", "retain"],
     f"{POLICY_NEW}/paths.py", PY_POLICY),
    (f"{POLICY_DIR}/record.json:1:31", ["rewrite", "retain"],
     f"{POLICY_NEW}/record.json", JSON_POLICY),
    (f"{POLICY_DIR}/report.py:3:11", ["rewrite", "retain"],
     f"{POLICY_NEW}/report.py", PY_POLICY),
    (LINT_SUBJECT, ["extend", "retain"], LINT_TOML, None),
    (RUN_SUBJECT, ["extend", "rewrite", "retain"], RUN_REPORT, None),
]
MAKEFILE = ".claude/notes/Makefile"
MAKEFILE_NEW = ".agents/artifacts/notes/Makefile"
MAKEFILE_TEXT = 'SKIP = (".claude",)\nSPEC = ".claude/specs/x.md"\n'
MAKEFILE_AFTER = (
    'SKIP = (".claude", ".agents/artifacts/notes", '
    '".agents/artifacts/plans", ".agents/artifacts/specs",)\n'
    'SPEC = ".agents/artifacts/specs/x.md"\n')


def write_policy_tree(root: Path, *, code: bool = True) -> None:
    """The policy fixture's files, over any fixture carrying `.claude/specs`,
    `.claude/plans` and a tracked `.gitignore`; without `code`, only its
    Markdown."""
    for path, text in {**POLICY_MARKDOWN,
                       **(POLICY_CODE if code else {})}.items():
        write(root, path, text)
    commit(root, "add a moved tree that holds working code")


def policy_repo(home: Path, *, code: bool = True) -> Path:
    root = nix_config_shape_repo(home)
    write_policy_tree(root, code=code)
    return root


def answer_args(*triples: tuple[str, str, str]) -> list[str]:
    return [token for triple in triples for token in ("--answer", *triple)]


def policy_row(subject: str, recommended: str | None, files: int,
               occurrences: int, **changed: object) -> dict:
    tree, _, file_class = subject.partition(":")
    return {"subject": subject, "tree": tree, "class": file_class,
            "recommended": recommended, "answer": None, "files": files,
            "occurrences": occurrences, "rewritable": occurrences,
            "rewritten": 0, "retained": 0, "extended": 0,
            "open": occurrences, "overridden": 0, **changed}
```

(c) Add after `class MovedFileReferencePlanTest` (Task 3):

```python
class ReferencePolicyPlanTest(AdoptTestCase):
    """#372: one answer per (moved tree, file class), overridable per
    occurrence, reported before `ready`."""

    def answered(self, root: Path, *triples: tuple[str, str, str]) -> object:
        code, doc, err = self.plan(root, *answer_args(*triples))
        self.assertEqual(code, 0, err or doc)
        return doc

    def opened(self, doc: object) -> list[tuple[str, str]]:
        return [(entry["id"], entry["subject"])
                for entry in doc["decisions"]["open"]]

    def decided(self, doc: object) -> list[tuple]:
        return [(row["subject"], row["answer"], row["decided_by"])
                for row in doc["path_references"]]

    def code_writes(self, doc: object) -> dict[str, dict]:
        """The non-Markdown `write-file` operations under the moved study
        tree and `tools/`, by target."""
        return {op["targets"][0]: op for op in doc["changes"]
                if op["op"] == "write-file"
                and op["targets"][0].startswith((POLICY_NEW, "tools/"))
                and not adopt_links.is_markdown_path(op["targets"][0])}

    def stored_plans(self) -> list[str]:
        store = self.home / ".agents" / "state" / "adopt" / "plans"
        return sorted(path.name for path in store.iterdir()) \
            if store.is_dir() else []

    def makefile_repo(self) -> Path:
        root = nix_config_shape_repo(self.home)
        write(root, MAKEFILE, MAKEFILE_TEXT)
        commit(root, "add a file of no known class to a moved tree")
        return root

    def test_moved_files_open_one_question_per_class(self):
        doc = self.ready_plan(policy_repo(self.home))
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(
            [gate["id"] for gate in doc["verification"]["ready_gates"]
             if gate["status"] != "passed"], ["no-open-decisions"])
        self.assertEqual(self.opened(doc), [
            ("path-reference", LINT_SUBJECT), ("path-reference", RUN_SUBJECT),
            ("reference-policy", JSON_POLICY),
            ("reference-policy", NIX_POLICY),
            ("reference-policy", PY_POLICY)])
        policies = [entry for entry in doc["decisions"]["open"]
                    if entry["id"] == "reference-policy"]
        for entry in policies:
            self.assertEqual(sorted(entry), [
                "answers", "basis", "id", "impact", "recommendation",
                "subject", "value"])
            self.assertEqual(entry["answers"], ["rewrite", "retain"])
            for member in ("basis", "impact", "recommendation"):
                self.assertNotIn(".claude/notes", entry[member])
                self.assertEqual(entry[member], policies[0][member])
        self.assertEqual([entry["value"] for entry in policies],
                         ["retain", "rewrite", "rewrite"])
        self.assertEqual(
            [(row["subject"], row["answers"], row["target"], row["policy"])
             for row in doc["path_references"]], POLICY_ROWS)
        self.assertEqual(self.decided(doc),
                         [(subject, None, None)
                          for subject, _, _, _ in POLICY_ROWS])
        lint = doc["path_references"][5]
        self.assertEqual(
            (lint["literal"], lint["additions"], lint["replacement"]),
            (r"^\\.claude/",
             [r"^\\.agents/artifacts/notes/", r"^\\.agents/artifacts/plans/",
              r"^\\.agents/artifacts/specs/"], None))
        self.assertEqual(doc["reference_policies"], [
            policy_row(JSON_POLICY, "retain", 1, 1),
            policy_row(NIX_POLICY, "rewrite", 1, 1),
            policy_row(PY_POLICY, "rewrite", 2, 3)])
        self.assertEqual(self.code_writes(doc), {})
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))

    def test_one_policy_answer_decides_both_scripts(self):
        doc = self.answered(policy_repo(self.home),
                            ("reference-policy", PY_POLICY, "rewrite"))
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(self.opened(doc), [
            ("path-reference", LINT_SUBJECT), ("path-reference", RUN_SUBJECT),
            ("reference-policy", JSON_POLICY),
            ("reference-policy", NIX_POLICY)])
        self.assertEqual(
            [(subject, answer, by) for subject, answer, by
             in self.decided(doc) if subject.endswith(
                 ("paths.py:1:10", "paths.py:2:9", "report.py:3:11"))],
            [(f"{POLICY_DIR}/paths.py:1:10", "rewrite", "policy"),
             (f"{POLICY_DIR}/paths.py:2:9", "rewrite", "policy"),
             (f"{POLICY_DIR}/report.py:3:11", "rewrite", "policy")])
        self.assertEqual(doc["reference_policies"][2], policy_row(
            PY_POLICY, "rewrite", 2, 3, answer="rewrite", rewritten=3,
            open=0))

    def test_answering_every_policy_and_outside_occurrence_reaches_ready(self):
        doc = self.answered(policy_repo(self.home), *POLICY_READY_ANSWERS)
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        self.assertEqual(
            doc["decisions"]["answered"],
            [{"id": question, "subject": subject, "value": value}
             for question, subject, value in sorted(POLICY_READY_ANSWERS)])
        self.assertEqual(self.decided(doc), [
            (f"{POLICY_DIR}/devenv.nix:3:21", "rewrite", "policy"),
            (f"{POLICY_DIR}/paths.py:1:10", "rewrite", "policy"),
            (f"{POLICY_DIR}/paths.py:2:9", "rewrite", "policy"),
            (f"{POLICY_DIR}/record.json:1:31", "retain", "policy"),
            (f"{POLICY_DIR}/report.py:3:11", "rewrite", "policy"),
            (LINT_SUBJECT, "extend", "occurrence"),
            (RUN_SUBJECT, "rewrite", "occurrence")])
        writes = self.code_writes(doc)
        self.assertEqual(sorted(writes), sorted(POLICY_REWRITTEN))
        for target, text in POLICY_REWRITTEN.items():
            with self.subTest(target=target):
                op = writes[target]
                self.assertEqual(op["sources"], [target])
                self.assertEqual(op["after"],
                                 sha256_hash(text.encode("utf-8")))
        order = [(op["op"], op["targets"][0] if op["targets"] else None)
                 for op in doc["changes"]]
        report = f"{POLICY_NEW}/report.py"
        self.assertLess(order.index(("git-mv", report)),
                        order.index(("write-file", report)))
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))

    def test_an_occurrence_answer_overrides_its_policy(self):
        override = f"{POLICY_DIR}/paths.py:2:9"
        doc = self.answered(
            policy_repo(self.home), *POLICY_READY_ANSWERS,
            ("path-reference", override, "retain"))
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(
            [(subject, answer, by) for subject, answer, by
             in self.decided(doc) if answer == "rewrite"],
            [(f"{POLICY_DIR}/devenv.nix:3:21", "rewrite", "policy"),
             (f"{POLICY_DIR}/paths.py:1:10", "rewrite", "policy"),
             (f"{POLICY_DIR}/report.py:3:11", "rewrite", "policy"),
             (RUN_SUBJECT, "rewrite", "occurrence")])
        self.assertIn((override, "retain", "occurrence"), self.decided(doc))
        self.assertIn((f"{POLICY_DIR}/record.json:1:31", "retain", "policy"),
                      self.decided(doc))
        self.assertEqual(doc["reference_policies"], [
            policy_row(JSON_POLICY, "retain", 1, 1, answer="retain",
                       retained=1, open=0),
            policy_row(NIX_POLICY, "rewrite", 1, 1, answer="rewrite",
                       rewritten=1, open=0),
            policy_row(PY_POLICY, "rewrite", 2, 3, answer="rewrite",
                       rewritten=2, retained=1, open=0, overridden=1)])
        writes = self.code_writes(doc)
        self.assertEqual(sorted(writes), sorted(POLICY_REWRITTEN))
        self.assertEqual(
            writes[f"{POLICY_NEW}/paths.py"]["after"], sha256_hash((
                'SPECS = ".agents/artifacts/specs"\n'
                'PLAN = ".claude/plans/y.md"\n').encode("utf-8")))

    def test_markdown_rewriting_is_unchanged(self):
        def markdown_writes(doc: object) -> list[tuple]:
            return [(op["targets"], op["before"], op["after"])
                    for op in doc["changes"] if op["op"] == "write-file"
                    and adopt_links.is_markdown_path(op["targets"][0])]

        with_code = self.answered(policy_repo(self.home),
                                  *POLICY_READY_ANSWERS)
        without = self.ready_plan(policy_repo(self.home, code=False))
        self.assertEqual(without["path_references"], [])
        self.assertEqual(without["reference_policies"], [])
        self.assertTrue(markdown_writes(without))
        self.assertEqual(markdown_writes(with_code), markdown_writes(without))
        self.assertEqual(with_code["link_rewrites"], without["link_rewrites"])

    def test_the_policy_answer_is_covered_by_the_plan_id(self):
        root = policy_repo(self.home)
        others = [triple for triple in POLICY_READY_ANSWERS
                  if triple[1] != PY_POLICY]
        rewritten = self.answered(root, *POLICY_READY_ANSWERS)
        retained = self.answered(
            root, *others, ("reference-policy", PY_POLICY, "retain"))
        self.assertEqual(retained["plan"]["state"], "ready",
                         retained["plan"]["blockers"])
        self.assertNotEqual(rewritten["plan"]["plan_id"],
                            retained["plan"]["plan_id"])
        inputs = (rewritten["plan"]["project_id"],
                  rewritten["plan"]["base_revision"],
                  rewritten["plan"]["platform"], rewritten["evidence"],
                  rewritten["decisions"]["answered"],
                  rewritten["link_rewrites"], rewritten["path_references"])
        self.assertEqual(
            adopt_planning.compute_plan_id(
                *inputs, rewritten["reference_policies"]),
            rewritten["plan"]["plan_id"])
        other = [dict(row) for row in rewritten["reference_policies"]]
        other[2]["rewritable"] += 1
        self.assertNotEqual(
            adopt_planning.compute_plan_id(*inputs, other),
            rewritten["plan"]["plan_id"])

    def test_invalid_policy_answers_refuse_and_store_nothing(self):
        root = policy_repo(self.home)
        ok = ("reference-policy", PY_POLICY, "rewrite")
        for triples, repair_id in (
                ((("reference-policy", ".claude/notes:.md", "retain"),),
                 "adopt.decisions.unmatched_answer"),
                ((("reference-policy", ".claude/specs:.py", "retain"),),
                 "adopt.decisions.unmatched_answer"),
                ((("reference-policy", RUN_SUBJECT, "retain"),),
                 "adopt.decisions.unmatched_answer"),
                ((("reference-policy", PY_POLICY, "extend"),),
                 "adopt.decisions.invalid_answer"),
                ((ok, ("reference-policy", PY_POLICY, "retain")),
                 "adopt.decisions.invalid_answer"),
                ((ok, ("reference-policies", PY_POLICY, "retain")),
                 "adopt.decisions.invalid_answer")):
            with self.subTest(triples=triples):
                before = self.stored_plans()
                code, payload, err = self.plan(root, *answer_args(*triples))
                self.assertEqual(code, 2, err or payload)
                self.assertEqual(payload["error"]["code"], "adopt_failure")
                self.assertEqual(payload["error"]["repair_id"], repair_id)
                self.assertEqual(
                    payload["error"]["violations"][0]["pointer"],
                    "/decisions/answered")
                self.assertEqual(self.stored_plans(), before)

    def test_a_class_outside_the_table_keeps_what_it_cannot_rewrite_open(self):
        root = self.makefile_repo()
        policy = ".claude/notes:-"
        skip = f"{MAKEFILE}:1:10"
        doc = self.ready_plan(root)
        self.assertEqual(self.opened(doc), [("reference-policy", policy)])
        self.assertIsNone(doc["decisions"]["open"][0]["value"])
        self.assertEqual(doc["reference_policies"],
                         [policy_row(policy, None, 1, 2, rewritable=1)])
        answered = self.answered(root, ("reference-policy", policy,
                                        "rewrite"))
        self.assertEqual(answered["plan"]["state"], "draft")
        self.assertEqual(self.opened(answered), [("path-reference", skip)])
        self.assertEqual(self.decided(answered), [
            (skip, None, None), (f"{MAKEFILE}:2:9", "rewrite", "policy")])
        self.assertEqual(answered["reference_policies"], [policy_row(
            policy, None, 1, 2, rewritable=1, answer="rewrite", rewritten=1,
            open=1)])
        both = self.answered(root, ("reference-policy", policy, "rewrite"),
                             ("path-reference", skip, "extend"))
        self.assertEqual(both["plan"]["state"], "ready",
                         both["plan"]["blockers"])
        self.assertEqual(both["reference_policies"], [policy_row(
            policy, None, 1, 2, rewritable=1, answer="rewrite", rewritten=1,
            extended=1, open=0, overridden=1)])
        (write_op,) = [op for op in both["changes"]
                       if op["op"] == "write-file"
                       and op["targets"] == [MAKEFILE_NEW]]
        self.assertEqual(write_op["after"],
                         sha256_hash(MAKEFILE_AFTER.encode("utf-8")))
        only = self.answered(root, ("path-reference", skip, "extend"),
                             ("path-reference", f"{MAKEFILE}:2:9", "retain"))
        self.assertEqual(only["plan"]["state"], "ready",
                         only["plan"]["blockers"])
        self.assertEqual(only["reference_policies"], [policy_row(
            policy, None, 1, 2, rewritable=1, retained=1, extended=1,
            open=0, overridden=2)])

    def test_the_human_view_prints_each_policy(self):
        root = policy_repo(self.home)
        code, out, err = run("plan", "--repo-root", str(root), "--format",
                             "human", home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn("\nreferences: 7 occurrences, extended 0, rewritten 0, "
                      "retained 0, open 7\n", out)
        self.assertIn(f"\npolicy {PY_POLICY}: 2 files, 3 occurrences, "
                      "rewritable 3, rewritten 0, retained 0, extended 0, "
                      "open 3\n", out)
        self.assertIn(f"\nopen reference-policy {JSON_POLICY} "
                      "(answers: rewrite|retain, recommended: retain): ", out)
        self.assertNotIn(f"open path-reference {POLICY_DIR}", out)
        code, out, err = run("plan", "--repo-root", str(root), "--format",
                             "human", *answer_args(*POLICY_READY_ANSWERS),
                             home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn(f"\npolicy {PY_POLICY}: 2 files, 3 occurrences, "
                      "rewritable 3, rewritten 3, retained 0, extended 0, "
                      "open 0\n", out)
        self.assertNotIn("open reference-policy", out)
        code, out, err = run("plan", "--repo-root", str(self.makefile_repo()),
                             "--format", "human", home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn("\nopen reference-policy .claude/notes:- "
                      "(answers: rewrite|retain, recommended: none): ", out)
```

The measured facts those cases rest on, at the base revision with the fixture texts passed straight to the tokenizer: the seven subjects, offered answers and replacements of `POLICY_ROWS` and `POLICY_REWRITTEN` for the six plain rows; `MAKEFILE:1:10` offers `extend`, `retain` with the three directory additions of `MAKEFILE_AFTER`, and `MAKEFILE:2:9` offers `rewrite`, `retain`. The `tools/lint.toml:2:22` row is Task 1's pattern reading: `.claude` survives the moves (the settings and skills-config files stay), so it has one addition per wholly moved subtree, sorted.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py -k ReferencePolicyPlanTest -k DocumentShapeTest -k test_the_question_set_is_closed` (timeout 1800 s)
Expected: FAIL/ERROR — `KeyError: 'reference_policies'`, the open list holding seven `path-reference` entries and no `reference-policy` one, every `reference-policy` answer refused with `adopt.decisions.invalid_answer`, the top-level member list and `QUESTION_IDS` unequal to their pins, and `compute_plan_id` rejecting a ninth argument.

- [ ] **Step 3: The vocabulary (`adopt_inspection`)**

- `QUESTION_IDS = ("project-id", "candidate-class", "path-reference", "reference-policy")`; extend the comment above it: a `reference-policy` entry is keyed by its `subject`, `<tree>:<class>`.
- `REFERENCE_POLICY_BASIS`: one fixed sentence that never names a tree, a class or a file, saying that files of one class inside a tree this plan moves name paths this plan moves.
- `question_impact("reference-policy")`: fixed prose stating that nothing in those files is edited until the policy or each of its occurrences is answered, so the `no-open-decisions` gate fails and the plan stays draft.
- `question_recommendation("reference-policy")`: fixed prose stating: answer with `plan --answer reference-policy <subject> <value>` using this entry's subject and one of its answers, and apply the plan id that run prints; `value` is the answer recommended for the class, or null when the class has none; `rewrite` replaces every literal whose `path_references` row offers `rewrite` with that row's replacement, at the file's `target`, and leaves the rest open; `retain` leaves the class's files unchanged; a `path-reference` answer on one occurrence overrides the policy.
- Both functions still raise `ValueError` for an unknown id.

- [ ] **Step 4: Answers and questions (`adopt_planning`)**

`policy_answers(answered)`: `{subject: value}` of the entries whose `id` is `reference-policy`, beside `reference_answers`.

`apply_answers`:

- The accepted ids become the three `candidate-class`, `path-reference`, `reference-policy`; any other id still refuses `adopt.decisions.invalid_answer`.
- The duplicate check is unchanged: `(id, subject)` seen twice refuses `adopt.decisions.invalid_answer`.
- A `reference-policy` answer derives the references exactly where a `path-reference` answer does (once, on the first answer of either id; both sort after `candidate-class`), then: a subject that is not the `policy` of any occurrence of `references` refuses `adopt.decisions.unmatched_answer`; a value not in `adopt_references.POLICY_ANSWERS` refuses `adopt.decisions.invalid_answer`. Check the subject first. Like a `path-reference` answer it mutates nothing in `found`.
- A policy all of whose occurrences are individually answered is still a policy of the inspection and is accepted.
- Write each refusal's message, and the docstring's list of ids and refusals, from the implemented code.

`reference_questions(references, answers, policies)` returns the `path-reference` entries followed by the `reference-policy` entries:

1. A policy subject is *open* when it is not in `policies` and at least one of its occurrences has no entry in `answers`.
2. An occurrence opens a `path-reference` entry (the base shape, six members, unchanged) when `adopt_references.effective_answer(occurrence, answers, policies)[0]` is `None` and its `policy` is not an open policy subject. In occurrence order.
3. Each open policy subject, sorted, opens `{"id": "reference-policy", "subject": <subject>, "answers": list(POLICY_ANSWERS), "value": recommended_answer(<class>), "basis": REFERENCE_POLICY_BASIS, "impact": question_impact("reference-policy"), "recommendation": question_recommendation("reference-policy")}`, where the class is `file_class` of any occurrence of the policy.

`compute_plan_id` takes `reference_policies: list[dict]` as its last parameter and adds `"reference_policies": reference_policies` to `source`; its docstring says nine inputs and names the ninth.

`bookkeeping_operations` takes `reference_policies: list[dict]` as its last parameter and writes `"reference_policies": reference_policies` into the evidence record directly after `"path_references"`.

- [ ] **Step 5: Composition and the human view (`adopt_project`)**

`compose_plan`:

- `policies = adopt_planning.policy_answers(answered)` beside `reference_answers`.
- `summary` and `rewritten` take `policies` in place of Task 3's `{}`; `reference_policies = adopt_references.policy_summary(references, reference_answers, policies)`.
- `open_questions += adopt_planning.reference_questions(references, reference_answers, policies)`.
- `compute_plan_id(..., path_references, reference_policies)` and `bookkeeping_operations(..., path_references, reference_policies)`.
- The document gains `"reference_policies": reference_policies` directly after `"path_references"`, for every outcome.
- The docstring's account of `answered` names the third answerable id.

`emit_human`:

- After the `references:` line, one line per row of `document["reference_policies"]`: `policy <subject>: <files> files, <occurrences> occurrences, rewritable <n>, rewritten <n>, retained <n>, extended <n>, open <n>`.
- In the open-question loop, a `reference-policy` entry prints `open reference-policy <subject> (answers: rewrite|retain, recommended: <value or none>): <recommendation>`, the answers joined from the entry's `answers` and `none` printed for a null `value`.
- The `references:` line is unchanged: it already counts rows by their (now effective) `answer`.

`main`'s parser:

- The `plan --answer` help text names all three answerable ids: `candidate-class`, `path-reference` and `reference-policy` (standards review PR-S1).

- [ ] **Step 6: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py` (timeout 1800 s)
Expected: PASS, every case of the file — the nine `ReferencePolicyPlanTest` cases, and every issue 345 and issue 350 case with only the pins of Step 1 (a) moved.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_apply.py home/common/agent-skills/tests/test_adopt_project_boundaries.py home/common/agent-skills/tests/test_adopt_verify.py` (timeout 3000 s)
Expected: PASS with no edit to those three files: a stored plan is re-derived through the same `compose_plan`, and `verify` requires only `EVIDENCE_RECORD_MEMBERS`, which did not grow. If a case there pins a member list this task changed, move that pin in this commit and name it in the report.

Scope gate: `git diff --stat 32807f90d4a4 -- python/agent_tools/adopt_apply.py python/agent_tools/adopt_links.py python/agent_tools/adopt_verify.py` prints nothing.

- [ ] **Step 7: Commit**

```bash
git add python/agent_tools/adopt_inspection.py python/agent_tools/adopt_planning.py python/agent_tools/adopt_project.py home/common/agent-skills/tests/test_adopt_project.py
git commit -m "feat(adopt): decide moved-file references by one policy per class (#372)"
```
