# Task 3: `plan --answer` settles candidates inside the plan id

**Files:**
- Modify: `python/agent_tools/adopt_inspection.py` (`action_relocates`, `overlap_targets`, `NOTES`)
- Modify: `python/agent_tools/adopt_planning.py` (new `apply_answers`)
- Modify: `python/agent_tools/adopt_project.py` (`compose_plan`, `command_plan`, `emit_human`, `build_parser`)
- Test: `home/common/agent-skills/tests/test_adopt_project.py`

**Interfaces:**
- Consumes (Task 2): `QUESTION_IDS`, `ARCHIVE_ADOPTED_DIR`, `candidate_answer(provenance, path) -> str | None`, `candidate_questions(found) -> list[dict]`, the fixtures `candidate_repo(home, *paths)` and `ignored_symlink_repo(home)` in `test_adopt_project.py`.
- Produces:
  - `adopt_planning.apply_answers(found: Candidates, inventory: Inventory, answers: list[dict]) -> list[dict]` — validates `answers` (each `{"id", "subject", "value"}`, all strings), mutates the matching entries of `found` and returns them sorted by `(id, subject)` (D5).
  - `adopt_project.compose_plan(root: Path, manifest: dict, answered: list[dict]) -> Composition` — calls `apply_answers` right after `classify_inventory` and before the untracked-overlap pass; `decisions["answered"]` is its return value, which flows unchanged into `compute_plan_id` and `bookkeeping_operations` (D15).
  - `plan --answer QUESTION SUBJECT VALUE`, repeatable: `argparse` `action="append"`, `nargs=3`, `metavar=("QUESTION", "SUBJECT", "VALUE")`, `default=[]`; `command_plan` passes `[{"id": q, "subject": s, "value": v} for q, s, v in args.answer]`. `command_apply` passes `[]` until Task 4.
  - `NOTES["answered"] = "classified by an answered candidate-class question; the inspection found no lifecycle class for it"`.

**Invariants:**
- Validation (D9): iterate the answers sorted by `(id, subject, value)`; refuse on the first violation with `refuse("adopt_failure", <repair id>, "/decisions/answered", <message>)`, in this order per answer:
  1. `id != "candidate-class"` → `adopt.decisions.invalid_answer`, "only a candidate-class question can be answered";
  2. `subject` already seen → `adopt.decisions.invalid_answer`, "a candidate is answered more than once";
  3. `subject` is not the `path` of an entry in `found.entries` whose action is `needs-decision` → `adopt.decisions.unmatched_answer`, "the answered subject is not an undecided candidate of this inspection";
  4. `value != candidate_answer(entry["provenance"], entry["path"])` (always true when that is `None`) → `adopt.decisions.invalid_answer`, "the answer is not the one this candidate's open question offers".
- All answers are validated before any entry is mutated, so a refusal changes nothing and stores no plan.
- Effect of a valid answer on its entry: `lifecycle_class` stays `unclassified`; `action` becomes the value; `note` becomes `NOTES["answered"]`; for `archive-history`, `target` becomes `f"{ARCHIVE_ADOPTED_DIR}/{path}"`, the candidate is registered as `found.groups[path] = {"action": "archive-history", "target": target, "members": [(path, object_id)]}` with `object_id` from `dict(inventory.tracked)[path]`, and `(path, target)` is appended to `found.moves`; for `retain-product`, `target` stays `None` and nothing else changes (D4).
- `action_relocates("archive-history")` returns `True`. `overlap_targets` admits a group as a target when `action_relocates(info["action"]) or info["action"] == "generate-projection"` (no literal `move-canonical`); its docstring stays true as written. `amended_contract` is unchanged (still `move-canonical` only).
- An answered candidate is no longer `needs-decision`, so `candidate_questions` omits it and `no-needs-decision` passes for it.
- `emit_human` prints each answered entry as `answered <id> <subject>: <value>`, after the `recommended` lines and before the `open` lines (D8).

- [ ] **Step 1: Write the failing tests**

Add module constants after `ignored_symlink_repo`:

```python
ODD = ".claude/odd.md"
ARCHIVED = ".agents/knowledge/archive/adopted/.claude/odd.md"
```

Add a test class after `CandidateQuestionTest`:

```python
class CandidateAnswerTest(AdoptTestCase):
    """#340 AC2: answering a candidate is reflected in the plan id."""

    def answered(self, root: Path, *triples: tuple[str, str, str]):
        args = [token for triple in triples
                for token in ("--answer", *triple)]
        return self.plan(root, *args)

    def stored_plans(self) -> list[str]:
        store = self.home / ".agents" / "state" / "adopt" / "plans"
        return sorted(path.name for path in store.iterdir()) \
            if store.is_dir() else []

    def refused(self, root: Path, repair_id: str,
                *triples: tuple[str, str, str]) -> None:
        before = self.stored_plans()
        code, payload, err = self.answered(root, *triples)
        self.assertEqual(code, 2, err or payload)
        self.assertEqual(payload["error"]["code"], "adopt_failure")
        self.assertEqual(payload["error"]["repair_id"], repair_id)
        self.assertEqual(payload["error"]["violations"][0]["pointer"],
                         "/decisions/answered")
        self.assertEqual(self.stored_plans(), before)

    def test_answering_reaches_ready_and_changes_the_plan_id(self):
        root = candidate_repo(self.home, ODD)
        draft = self.ready_plan(root)
        code, doc, err = self.answered(
            root, ("candidate-class", ODD, "archive-history"))
        self.assertEqual(code, 0, err)
        self.assertNotEqual(doc["plan"]["plan_id"], draft["plan"]["plan_id"])
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        self.assertEqual(doc["decisions"]["answered"], [
            {"id": "candidate-class", "subject": ODD,
             "value": "archive-history"}])
        self.assertEqual(doc["plan"]["plan_id"], adopt_planning.compute_plan_id(
            doc["plan"]["project_id"], doc["plan"]["base_revision"],
            doc["plan"]["platform"], doc["evidence"],
            doc["decisions"]["answered"]))
        entry = next(e for e in doc["evidence"] if e["path"] == ODD)
        self.assertEqual(
            (entry["lifecycle_class"], entry["action"], entry["target"]),
            ("unclassified", "archive-history", ARCHIVED))
        pairs = [(op["sources"][0], op["targets"][0])
                 for op in doc["changes"] if op["op"] == "git-mv"]
        self.assertIn((ODD, ARCHIVED), pairs)

    def test_an_answered_ignored_candidate_is_retained_without_an_operation(self):
        path = ".claude/settings.local.json"
        code, doc, err = self.answered(
            ignored_symlink_repo(self.home),
            ("candidate-class", path, "retain-product"))
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        entry = next(e for e in doc["evidence"] if e["path"] == path)
        self.assertEqual((entry["action"], entry["target"]),
                         ("retain-product", None))
        for op in doc["changes"]:
            self.assertNotIn(path, op["sources"] + op["targets"])

    def test_a_non_candidate_question_id_is_an_invalid_answer(self):
        self.refused(candidate_repo(self.home, ODD),
                     "adopt.decisions.invalid_answer",
                     ("project-id", ODD, "archive-history"))

    def test_a_value_the_question_does_not_offer_is_an_invalid_answer(self):
        self.refused(candidate_repo(self.home, ODD),
                     "adopt.decisions.invalid_answer",
                     ("candidate-class", ODD, "retain-product"))

    def test_every_answer_to_a_secret_shaped_candidate_is_invalid(self):
        root = candidate_repo(self.home, ".claude/secrets/key.md")
        for value in ("archive-history", "retain-product"):
            with self.subTest(value=value):
                self.refused(root, "adopt.decisions.invalid_answer",
                             ("candidate-class", ".claude/secrets/key.md",
                              value))

    def test_one_subject_answered_twice_is_an_invalid_answer(self):
        self.refused(candidate_repo(self.home, ODD),
                     "adopt.decisions.invalid_answer",
                     ("candidate-class", ODD, "archive-history"),
                     ("candidate-class", ODD, "archive-history"))

    def test_a_subject_that_is_not_an_undecided_candidate_is_unmatched(self):
        root = candidate_repo(self.home, ODD)
        for subject in (".claude/missing.md", ".claude/specs/x.md"):
            with self.subTest(subject=subject):
                self.refused(root, "adopt.decisions.unmatched_answer",
                             ("candidate-class", subject, "archive-history"))

    def test_the_human_view_prints_the_answer(self):
        root = candidate_repo(self.home, ODD)
        code, human, err = run(
            "plan", "--repo-root", str(root), "--format", "human",
            "--answer", "candidate-class", ODD, "archive-history",
            home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn(f"answered candidate-class {ODD}: archive-history\n",
                      human)

    def test_archive_history_relocates(self):
        self.assertTrue(adopt_inspection.action_relocates("archive-history"))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py -k CandidateAnswerTest`
Expected: FAIL, 9 tests — `--answer` is an argparse usage error (exit 2, empty stdout, so `payload` is `None`), and `action_relocates("archive-history")` is `False`.

- [ ] **Step 3: Write the minimal implementation**

1. `adopt_inspection`: `NOTES["answered"]`; move `"archive-history"` to the `True` branch of `action_relocates` and update its docstring to "Whether an action moves a candidate to a new home: a canonical one, or the adoption archive."; the `overlap_targets` condition as pinned.
2. `adopt_planning.apply_answers` exactly as the invariants pin, with a docstring stating the validation order and that nothing is mutated until every answer validates.
3. `adopt_project`: the `compose_plan` signature and call; `command_plan` builds the answer list; `command_apply` calls `compose_plan(root, manifest, [])` (Task 4 replaces `[]`); the `--answer` parser argument with help text "settle one open candidate-class question; repeatable"; the `answered` human line. Update the `compose_plan` docstring with one sentence: "`answered` is the operator's answers to open `candidate-class` questions, applied before anything else is derived, so they enter `plan_id`."

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_project_boundaries.py home/common/agent-skills/tests/test_adopt_apply.py`
Expected: PASS, all three modules, no failures (`test_adopt_apply.py` proves the `compose_plan(…, [])` call left `apply` unchanged).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_inspection.py python/agent_tools/adopt_planning.py python/agent_tools/adopt_project.py home/common/agent-skills/tests/test_adopt_project.py
launch-commit … -- -m "feat(adopt): answer candidate-class questions with plan --answer (#340)"
```
