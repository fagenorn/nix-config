# Task 2: `plan` asks, settles, publishes and writes the path references

**Files:**
- Modify: `python/agent_tools/adopt_inspection.py` (`QUESTION_IDS` and its comment, new `PATH_REFERENCE_BASIS`, `question_impact`, `question_recommendation`)
- Modify: `python/agent_tools/adopt_planning.py` (`apply_answers`, `build_operations`, `bookkeeping_operations`, `compute_plan_id`; new `reference_excluded`, `reference_answers`, `reference_questions`, `check_reference_writes`)
- Modify: `python/agent_tools/adopt_project.py` (`compose_plan`, `emit_human`, the `--answer` help, module docstring)
- Test: `home/common/agent-skills/tests/test_adopt_project.py`

**Interfaces:**
- Consumes (Task 1, `agent_tools.adopt_references`): `derive_references(root, revision, moves, excluded) -> References`; `References.occurrences: tuple[Occurrence, ...]` sorted by `(path, line, column)`; `Occurrence.subject: str` (`<path>:<line>:<column>`), `Occurrence.answers: tuple[str, ...]`; `summary(references, answers: dict[str, str]) -> list[dict]`; `rewritten(references, answers) -> dict[str, tuple[str, str]]` (`path -> (before, after)` texts).
- Produces:
  - `adopt_inspection.QUESTION_IDS == ("project-id", "candidate-class", "path-reference")` (D7); `adopt_inspection.PATH_REFERENCE_BASIS == "a tracked non-Markdown file names a path this plan moves"`.
  - `question_impact("path-reference")` returns `"the file keeps naming the old path and nothing in it is edited until the reference is answered, so the no-open-decisions gate fails and the plan stays draft"`.
  - `question_recommendation("path-reference")` returns `"answer it with plan --answer path-reference <subject> <value>, using this entry's subject and one of its answers, and apply the plan id that run prints: extend adds the additions this occurrence's path_references row lists beside the literal, rewrite replaces the literal with that row's replacement, and retain leaves the file unchanged"`.
  - `adopt_planning.reference_excluded(contract_source: dict | None) -> set[str]` — `{CONTRACT_FILENAME, GITIGNORE, RUNTIME_SENTINEL, *LEGACY_BINDING_CONFIGS} | generated_targets(contract_source)` (D10).
  - `adopt_planning.apply_answers(root: Path, found: Candidates, inventory: Inventory, answers: list[dict], excluded: set[str]) -> tuple[list[dict], References]` — the settled answers sorted by `(id, subject)`, and the references derived from the settled moves (D7, D12).
  - `adopt_planning.reference_answers(answered: list[dict]) -> dict[str, str]` — `subject -> value` of the `path-reference` answers.
  - `adopt_planning.reference_questions(references: References, answers: dict[str, str]) -> list[dict]` — in occurrence order, one `{"id": "path-reference", "subject", "answers": list, "basis": PATH_REFERENCE_BASIS, "impact", "recommendation"}` per occurrence whose subject is not in `answers`; exactly those six members, no `value`.
  - `adopt_planning.check_reference_writes(changes: list[dict], reference_targets: set[str]) -> None` — raises `ValueError` unless, for each target, exactly one operation holds it in `sources` or `targets`, and that one is a `write-file` with `sources == targets == [target]` (D9).
  - `adopt_planning.build_operations(root, found, manifest, contract_source, plan_id, links, reference_files: dict[str, tuple[str, str]])` — after the Markdown link writes and before the projection regenerations, one `operation("write-file", [t], [t], sha256_hash(before_bytes), sha256_hash(after_bytes))` per `t` in `sorted(reference_files)`, with `contents[t] = after_bytes` (UTF-8 encodings of the two texts).
  - `adopt_planning.bookkeeping_operations(..., link_rewrites, path_references: list[dict])` — the evidence record gains the member `"path_references"`; `EVIDENCE_RECORD_MEMBERS` is unchanged (D8).
  - `adopt_planning.compute_plan_id(project_id, base_revision, platform_block, evidence, answered, link_rewrites, path_references: list[dict]) -> str` — eight inputs; the digested source gains the key `"path_references"` (D8).
  - The plan document gains the top-level member `path_references` (the `summary` rows), directly after `link_rewrites`, for every outcome.
  - `--format human` prints, directly after the `links:` line, `references: <n> occurrences, extended <e>, rewritten <r>, retained <k>, open <o>`, and each open reference as `open path-reference <subject> (answers: <a>|<b>): <recommendation>`.

**Invariants:**
- `apply_answers` keeps one pass over `sorted(answers, key=(id, subject, value))`, refusing the first violation, in this order per answer: an id outside `("candidate-class", "path-reference")` → `adopt.decisions.invalid_answer`, message `"only a candidate-class or path-reference question can be answered"`; an `(id, subject)` already seen → `adopt.decisions.invalid_answer`, message `"a candidate is answered more than once"` for `candidate-class` (unchanged) and `"a path reference is answered more than once"` for `path-reference`; then the id's own checks. The `candidate-class` checks and messages are unchanged. For `path-reference`: a subject that is no occurrence → `adopt.decisions.unmatched_answer`, `"the answered subject is not a path reference of this inspection"`; a value not in that occurrence's `answers` → `adopt.decisions.invalid_answer`, `"the answer is not one this path reference's open question offers"`. Pointer `/decisions/answered` throughout.
- The references are derived exactly once per call, by `adopt_references.derive_references(root, inventory.base_revision, moves, excluded)`: when the pass reaches its first `path-reference` answer, with `moves = found.moves` plus `(subject, f"{ARCHIVE_ADOPTED_DIR}/{subject}")` for every `archive-history` answer validated so far; otherwise after the candidate mutation, with `found.moves` (D12). Nothing in `found` is mutated before every answer has validated.
- `compose_plan` order: `inspect_repository`, `classify_inventory`, `load_contract_source`, then `apply_answers(root, found, inventory, answered, adopt_planning.reference_excluded(contract_source))`; the rows are `adopt_references.summary(references, adopt_planning.reference_answers(answered))` and are computed before `compute_plan_id`; `decisions["open"]` is the existing sorted identity and candidate questions followed by `reference_questions(...)`; `build_operations` receives `adopt_references.rewritten(references, <those answers>)`; for an appliable outcome `check_reference_writes(changes, set(<rewritten>))` runs beside `check_markdown_writes`. A not-applicable outcome keeps `changes == []` and still publishes `path_references`.
- No ready gate, commit gate, operation kind or `verify` check is added; `no-open-decisions` alone keeps a plan with an open reference `draft` (D1). `Composition.overlap` is unchanged.
- Docstrings match the code: `compute_plan_id` says eight inputs and names `path_references`; `apply_answers`' describes both question kinds, the derivation point and the tuple it returns; `build_operations`' apply-order sentence places the path-reference writes after the Markdown link rewrites; `compose_plan`'s names both answerable kinds. `adopt_project`'s module docstring says nine-member with `path_references` listed after `link_rewrites`, gives the `plan_id` source set as `{adopt_schema_version, project_id, base_revision, platform, evidence, decisions.answered, link_rewrites, path_references}`, and says `plan` reads, through git, the base revision's Markdown blobs and its non-Markdown text blobs that name a moved path's first segment. The `--answer` help reads `"settle one open candidate-class or path-reference question; repeatable"`. The comment above `QUESTION_IDS` adds that a `path-reference` entry is keyed by its `subject`, `<path>:<line>:<column>`.

- [ ] **Step 1: Write the failing tests**

In `test_adopt_project.py`:

1. Pins. Add `"path_references"` to `TOP_LEVEL_MEMBERS` between `"link_rewrites"` and `"plan"`; rename `test_exactly_eight_top_level_members` to `test_exactly_nine_top_level_members`. In `documented_plan_id` add `"path_references": doc["path_references"],` to `source` and change "the seven named members" to "the eight named members". In the evidence-record reconstruction of `TypedOperationTest` (the `record = {...}` holding `"link_rewrites": doc["link_rewrites"]`) add `"path_references": doc["path_references"],`. In `LinkRewritePlanTest.test_a_different_rewrite_set_is_a_different_plan_id` pass `doc["path_references"]` as the last argument of both `compute_plan_id` calls. In `CandidateQuestionTest.test_the_question_set_is_closed` expect `("project-id", "candidate-class", "path-reference")`.

2. Fixture, at module level after `linked_repo`:

```python
CHECK_LINKS = "tools/check_links.py"
UNRELATED_SCRIPT = "tools/list_docs.py"
# A repository's own link check (#350): it exempts `.claude/`, where the
# already-broken link of `REFERENCE_TREE` lives. Line 7 holds the one path
# reference; every other token names nothing the plan moves.
CHECK_LINKS_SCRIPT = r'''#!/usr/bin/env python3
# Fail when a Markdown file outside the exempt trees has a broken relative link.
import os
import re
import sys

EXEMPT = ("docs/archive/", ".claude/")
LINK = re.compile(r"\]\(([^)#\s]+)")


def main(root):
    broken = []
    for folder, _, names in sorted(os.walk(root)):
        for name in sorted(names):
            path = os.path.relpath(os.path.join(folder, name), root)
            if not path.endswith(".md") or path.startswith(EXEMPT):
                continue
            with open(os.path.join(root, path), encoding="utf-8") as handle:
                text = handle.read()
            for target in LINK.findall(text):
                if "://" not in target and not os.path.exists(
                        os.path.join(root, os.path.dirname(path), target)):
                    broken.append(f"{path}: {target}")
    print("\n".join(broken) or "ok")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
'''
CHECK_LINKS_EXTENDED = CHECK_LINKS_SCRIPT.replace(
    '".claude/")',
    '".claude/", ".agents/artifacts/plans/", ".agents/artifacts/specs/")')
REFERENCE_SUBJECT = f"{CHECK_LINKS}:7:29"
REFERENCE_ROW = {
    "subject": REFERENCE_SUBJECT, "path": CHECK_LINKS, "line": 7,
    "column": 29, "literal": ".claude/", "answers": ["extend", "retain"],
    "answer": None,
    "additions": [".agents/artifacts/plans/", ".agents/artifacts/specs/"],
    "replacement": None}
REFERENCE_TREE = {
    "README.md": "# readme\n\nSee [spec x](.claude/specs/x.md).\n",
    ".claude/specs/x.md": "# spec x\n\nGone: [gone](missing.md).\n",
    ".claude/rules/r.md": "# rule r\n",
    UNRELATED_SCRIPT: 'ROOTS = ("docs/standards/", "home/")\nprint(ROOTS)\n',
}


def write_reference_tree(root: Path, *, script: bool = True) -> None:
    """An inbound link, an already-broken link inside a moved tree, retained
    `.claude/` content, an unrelated script and, with `script`, the link
    check, over any fixture carrying `.claude/specs` and `.claude/plans`."""
    for path, text in REFERENCE_TREE.items():
        write(root, path, text)
    if script:
        write(root, CHECK_LINKS, CHECK_LINKS_SCRIPT)
    commit(root, "reference the agent trees")


def referenced_repo(home: Path, *, script: bool = True) -> Path:
    root = nix_config_shape_repo(home)
    write_reference_tree(root, script=script)
    return root
```

3. The cases, after `LinkRewritePlanTest`:

```python
class PathReferencePlanTest(AdoptTestCase):
    """#350: `plan` asks about every path literal naming a moved tree."""

    def answered(self, root: Path, value: str,
                 subject: str = REFERENCE_SUBJECT) -> object:
        code, doc, err = self.plan(root, "--answer", "path-reference",
                                   subject, value)
        self.assertEqual(code, 0, err or doc)
        return doc

    def stored_plans(self) -> list[str]:
        store = self.home / ".agents" / "state" / "adopt" / "plans"
        return sorted(path.name for path in store.iterdir()) \
            if store.is_dir() else []

    def naming(self, doc: object, path: str) -> list[dict]:
        return [op for op in doc["changes"]
                if path in op["sources"] + op["targets"]]

    def test_an_open_reference_keeps_the_plan_draft_with_a_stable_question(self):
        root = referenced_repo(self.home)
        doc = self.ready_plan(root)
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(
            [gate["id"] for gate in doc["verification"]["ready_gates"]
             if gate["status"] != "passed"], ["no-open-decisions"])
        (question,) = [entry for entry in doc["decisions"]["open"]
                       if entry["id"] == "path-reference"]
        self.assertEqual(sorted(question), ["answers", "basis", "id", "impact",
                                            "recommendation", "subject"])
        self.assertEqual(question["subject"], REFERENCE_SUBJECT)
        self.assertEqual(question["answers"], ["extend", "retain"])
        for member in ("basis", "impact", "recommendation"):
            self.assertNotIn("tools/", question[member])
        self.assertEqual(doc["path_references"], [REFERENCE_ROW])
        self.assertEqual(self.naming(doc, CHECK_LINKS), [])
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))
        again = self.ready_plan(root)
        self.assertEqual(again["decisions"]["open"], doc["decisions"]["open"])
        self.assertEqual(again["plan"]["plan_id"], doc["plan"]["plan_id"])

    def test_answering_extend_reaches_ready_with_one_write(self):
        doc = self.answered(referenced_repo(self.home), "extend")
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        self.assertEqual(doc["decisions"]["answered"],
                         [{"id": "path-reference",
                           "subject": REFERENCE_SUBJECT, "value": "extend"}])
        self.assertEqual(doc["path_references"],
                         [{**REFERENCE_ROW, "answer": "extend"}])
        (write_op,) = self.naming(doc, CHECK_LINKS)
        self.assertEqual(write_op["op"], "write-file")
        self.assertEqual(write_op["sources"], [CHECK_LINKS])
        self.assertEqual(write_op["targets"], [CHECK_LINKS])
        self.assertEqual(write_op["before"],
                         sha256_hash(CHECK_LINKS_SCRIPT.encode("utf-8")))
        self.assertEqual(write_op["after"],
                         sha256_hash(CHECK_LINKS_EXTENDED.encode("utf-8")))
        order = [(op["op"], op["targets"][0] if op["targets"] else None)
                 for op in doc["changes"]]
        script = order.index(("write-file", CHECK_LINKS))
        self.assertLess(order.index(("write-file", "README.md")), script)
        self.assertLess(script, min(
            index for index, (kind, _) in enumerate(order)
            if kind == "regenerate-projection"))
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))

    def test_retain_reaches_ready_and_writes_nothing(self):
        doc = self.answered(referenced_repo(self.home), "retain")
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["path_references"],
                         [{**REFERENCE_ROW, "answer": "retain"}])
        self.assertEqual(self.naming(doc, CHECK_LINKS), [])

    def test_the_answer_is_covered_by_the_plan_id(self):
        root = referenced_repo(self.home)
        opened = self.ready_plan(root)
        extended = self.answered(root, "extend")
        retained = self.answered(root, "retain")
        self.assertEqual(len({doc["plan"]["plan_id"]
                              for doc in (opened, extended, retained)}), 3)
        inputs = (extended["plan"]["project_id"],
                  extended["plan"]["base_revision"],
                  extended["plan"]["platform"], extended["evidence"],
                  extended["decisions"]["answered"],
                  extended["link_rewrites"])
        self.assertEqual(
            adopt_planning.compute_plan_id(*inputs,
                                           extended["path_references"]),
            extended["plan"]["plan_id"])
        other = [{**extended["path_references"][0],
                  "additions": [".agents/artifacts/specs/"]}]
        self.assertNotEqual(adopt_planning.compute_plan_id(*inputs, other),
                            extended["plan"]["plan_id"])

    def test_markdown_rewriting_is_unchanged_and_other_files_are_untouched(self):
        def markdown_writes(doc: object) -> list[tuple]:
            return [(op["targets"], op["before"], op["after"])
                    for op in doc["changes"] if op["op"] == "write-file"
                    and adopt_links.is_markdown_path(op["targets"][0])]

        with_script = self.answered(referenced_repo(self.home), "extend")
        without = self.ready_plan(referenced_repo(self.home, script=False))
        self.assertEqual(without["plan"]["state"], "ready",
                         without["plan"]["blockers"])
        self.assertEqual(without["path_references"], [])
        self.assertTrue(markdown_writes(without))
        self.assertEqual(markdown_writes(with_script),
                         markdown_writes(without))
        self.assertEqual(with_script["link_rewrites"],
                         without["link_rewrites"])
        self.assertEqual(self.naming(with_script, UNRELATED_SCRIPT), [])
        self.assertEqual(
            [op["targets"] for op in with_script["changes"]
             if op["op"] == "write-file"
             and op["targets"][0].startswith("tools/")], [[CHECK_LINKS]])

    def test_invalid_reference_answers_refuse_and_store_nothing(self):
        root = referenced_repo(self.home)
        ok = ("path-reference", REFERENCE_SUBJECT, "extend")
        for triples, repair_id in (
                ((("path-reference", f"{CHECK_LINKS}:1:1", "retain"),),
                 "adopt.decisions.unmatched_answer"),
                ((("path-reference", REFERENCE_SUBJECT, "rewrite"),),
                 "adopt.decisions.invalid_answer"),
                ((ok, ("path-reference", REFERENCE_SUBJECT, "retain")),
                 "adopt.decisions.invalid_answer"),
                ((ok, ("path-ref", REFERENCE_SUBJECT, "retain")),
                 "adopt.decisions.invalid_answer")):
            with self.subTest(triples=triples):
                before = self.stored_plans()
                code, payload, err = self.plan(root, *[
                    token for triple in triples
                    for token in ("--answer", *triple)])
                self.assertEqual(code, 2, err or payload)
                self.assertEqual(payload["error"]["code"], "adopt_failure")
                self.assertEqual(payload["error"]["repair_id"], repair_id)
                self.assertEqual(
                    payload["error"]["violations"][0]["pointer"],
                    "/decisions/answered")
                self.assertEqual(self.stored_plans(), before)

    def test_the_human_view_prints_the_references(self):
        root = referenced_repo(self.home)
        code, out, err = run("plan", "--repo-root", str(root), "--format",
                             "human", home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn("\nreferences: 1 occurrences, extended 0, rewritten 0, "
                      "retained 0, open 1\n", out)
        self.assertIn(f"\nopen path-reference {REFERENCE_SUBJECT} "
                      "(answers: extend|retain): ", out)
        code, out, err = run("plan", "--repo-root", str(root), "--format",
                             "human", "--answer", "path-reference",
                             REFERENCE_SUBJECT, "extend", home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn("\nreferences: 1 occurrences, extended 1, rewritten 0, "
                      "retained 0, open 0\n", out)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py -k PathReferencePlanTest -k DocumentShapeTest -k test_the_question_set_is_closed`
Expected: FAIL — `KeyError: 'path_references'` in the shape and reference cases, the `QUESTION_IDS` tuple unequal, and exit 2 where `--answer path-reference` is refused as an unknown id.

- [ ] **Step 3: Write the minimal implementation**

Make the changes named in **Files** so that **Produces** and **Invariants** hold. In `emit_human`, count the `references:` line from `document["path_references"]`: `n` its length, `e`/`r`/`k` the rows whose `answer` is `extend`/`rewrite`/`retain`, `o` those whose `answer` is `None`. Change nothing in `adopt_apply.py`, `adopt_verify.py` or `adopt_links.py`.

If an existing fixture's plan now carries a non-empty `path_references` and so turns `draft`, the derivation is scanning a file D2 or D10 excludes: fix the exclusion in the code, never the fixture or the expected state.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_project_boundaries.py home/common/agent-skills/tests/test_adopt_apply.py` (timeout 1800 s)
Expected: OK, every test passing, no warnings — the unedited `LinkRewritePlanTest`, `CandidateAnswerTest` and the whole `apply` suite included, which proves the signature changes and the eighth id input left issue 340's and issue 345's behaviour alone.

Run: `git diff --stat 02d2f378ad8c4abbb8e3a3960b4c93b10879bd6b -- python/agent_tools/adopt_apply.py python/agent_tools/adopt_verify.py`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_inspection.py python/agent_tools/adopt_planning.py \
  python/agent_tools/adopt_project.py home/common/agent-skills/tests/test_adopt_project.py
git commit -m "feat(adopt): ask about path references and write the answered ones (#350)"
```
