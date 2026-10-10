# Task 3: `plan --answer` settles candidates inside the plan id; `apply` replays them

**Files:**
- Modify: `python/agent_tools/adopt_inspection.py` (`action_relocates`, `overlap_targets`, `NOTES`, `question_recommendation`)
- Modify: `python/agent_tools/adopt_planning.py` (new `apply_answers`)
- Modify: `python/agent_tools/adopt_apply.py` (new `stored_answers`)
- Modify: `python/agent_tools/adopt_project.py` (`compose_plan`, `command_plan`, `command_apply`, `emit_human`, `build_parser`)
- Test: `home/common/agent-skills/tests/test_adopt_project.py`, `home/common/agent-skills/tests/test_adopt_apply.py`, `home/common/agent-skills/tests/test_adopt_verify.py`

**Interfaces:**
- Consumes (Task 2): `QUESTION_IDS`, `ARCHIVE_ADOPTED_DIR`, `candidate_answer(provenance, path) -> str | None`, `candidate_questions(found) -> list[dict]`, the fixtures `candidate_repo(home, *paths)` and `ignored_symlink_repo(home)` in `test_adopt_project.py`.
- Produces:
  - `adopt_planning.apply_answers(found: Candidates, inventory: Inventory, answers: list[dict]) -> list[dict]` — validates `answers` (each `{"id", "subject", "value"}`, all strings), mutates the matching entries of `found` and returns them sorted by `(id, subject)` (D5).
  - `adopt_project.compose_plan(root: Path, manifest: dict, answered: list[dict]) -> Composition` — calls `apply_answers` right after `classify_inventory` and before the untracked-overlap pass; `decisions["answered"]` is its return value, which flows unchanged into `compute_plan_id` and `bookkeeping_operations` (D15).
  - `plan --answer QUESTION SUBJECT VALUE`, repeatable: `argparse` `action="append"`, `nargs=3`, `metavar=("QUESTION", "SUBJECT", "VALUE")`, `default=[]`; `command_plan` passes `[{"id": q, "subject": s, "value": v} for q, s, v in args.answer]`.
  - `adopt_apply.stored_answers(document: dict) -> list[dict]` — returns `document["decisions"]["answered"]` when `document["decisions"]` is a dict whose `answered` is a list of dicts, each with exactly the keys `id`, `subject`, `value` and only string values; otherwise raises `refuse("adopt_failure", "adopt.plan.malformed", "/decisions/answered", "the stored plan's answered decisions are not well formed")` (D9).
  - `command_apply` calls `answers = adopt_apply.stored_answers(document)` immediately after `load_stored_plan`, before the `not_ready` check, and passes `answers` to `compose_plan` (D5, D9). `apply` gains no flag (D16).
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
- `question_recommendation("candidate-class")` becomes D8's final sentence, replacing Task 2's interim one, verbatim: `"answer it with plan --answer candidate-class <subject> <value>, using this entry's subject and value, and apply the plan id that run prints; a null value marks a secret-shaped path with no answer: add a central classification row for it, or remove it from the repository in its own commit, then plan again"`. It lands in this commit because `--answer` and `apply`'s replay do.
- A tampered stored answer is caught by the existing recomputation (`plan_stale`) or by the shared validation (`adopt_failure`); no new apply-side check. Every apply refusal mutates nothing (the `ApplyTestCase.refuse` witnesses).

- [ ] **Step 1: Write the failing tests**

Lift `PlanIdentityTest.expected_plan_id` to a module-level `documented_plan_id(doc)` with the same body and docstring (the D15 formula written out independently of `compute_plan_id`), and make `PlanIdentityTest` call it; that test's assertions are unchanged.

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

    def first_violation(self, root: Path, *triples) -> tuple[str, dict]:
        code, payload, err = self.answered(root, *triples)
        self.assertEqual(code, 2, err or payload)
        return (payload["error"]["repair_id"],
                payload["error"]["violations"][0])

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
        # The independent oracle, with every other digest input held
        # constant: the id covers the non-empty answers, and the same
        # document with no answers digests differently.
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))
        unanswered = {**doc, "decisions": {**doc["decisions"],
                                           "answered": []}}
        self.assertNotEqual(doc["plan"]["plan_id"],
                            documented_plan_id(unanswered))
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

    def test_answer_order_on_the_command_line_does_not_matter(self):
        root = candidate_repo(self.home, ODD, ".claude/a.md")
        first = ("candidate-class", ".claude/a.md", "archive-history")
        second = ("candidate-class", ODD, "archive-history")
        forward = run("plan", "--repo-root", str(root), "--answer", *first,
                      "--answer", *second, home=self.home)
        backward = run("plan", "--repo-root", str(root), "--answer", *second,
                       "--answer", *first, home=self.home)
        self.assertEqual(forward[0], 0, forward[2])
        self.assertEqual(forward[1], backward[1])

    def test_competing_violations_report_the_sorted_first_one(self):
        root = candidate_repo(self.home, ODD)
        bad_id = ("project-id", ODD, "archive-history")
        unmatched = ("candidate-class", ".claude/missing.md",
                     "archive-history")
        expected = ("adopt.decisions.unmatched_answer",
                    {"pointer": "/decisions/answered",
                     "message": "the answered subject is not an undecided "
                                "candidate of this inspection"})
        for triples in ((bad_id, unmatched), (unmatched, bad_id)):
            with self.subTest(triples=triples):
                self.assertEqual(self.first_violation(root, *triples),
                                 expected)

    def test_a_duplicate_subject_is_reported_before_its_value(self):
        root = candidate_repo(self.home, ODD)
        good = ("candidate-class", ODD, "archive-history")
        bad = ("candidate-class", ODD, "retain-product")
        expected = ("adopt.decisions.invalid_answer",
                    {"pointer": "/decisions/answered",
                     "message": "a candidate is answered more than once"})
        for triples in ((good, bad), (bad, good)):
            with self.subTest(triples=triples):
                self.assertEqual(self.first_violation(root, *triples),
                                 expected)

    def test_the_recommendation_names_the_answer_flag(self):
        self.assertIn("plan --answer candidate-class <subject> <value>",
                      adopt_inspection.question_recommendation(
                          "candidate-class"))

    def test_archive_history_relocates(self):
        self.assertTrue(adopt_inspection.action_relocates("archive-history"))
```

In `test_adopt_apply.py`, after `readoption_repo`:

```python
ODD = ".claude/odd.md"
ARCHIVED = ".agents/knowledge/archive/adopted/.claude/odd.md"


def answered_repo(home: Path) -> Path:
    """`apply_repo` plus one tracked agent path no row classifies (#340)."""
    root = apply_repo(home)
    write(root, ODD, "# odd\n")
    commit(root, "add an unclassified agent path")
    return root
```

and a class after `DeletionAcknowledgementTest`:

```python
class AnsweredCandidateApplyTest(ApplyTestCase):
    """#340: `apply` re-derives an answered plan from its stored answers."""

    MALFORMED = ([{"id": "candidate-class", "subject": ODD}],
                 {"id": "candidate-class"},
                 [{"id": "candidate-class", "subject": ODD, "value": None}])

    def planned(self, root: Path, *extra: str) -> dict:
        code, out, err = run("plan", "--repo-root", str(root), *extra,
                             home=self.home)
        self.assertEqual(code, 0, err or out)
        return json.loads(out)

    def answered_plan(self, root: Path) -> str:
        document = self.planned(root, "--answer", "candidate-class", ODD,
                                "archive-history")
        self.assertEqual(document["plan"]["state"], "ready",
                         document["plan"]["blockers"])
        return document["plan"]["plan_id"]

    def edit_answers(self, plan_id: str, answered: object) -> None:
        document = json.loads(self.stored_plan(plan_id).read_text("utf-8"))
        document["decisions"]["answered"] = answered
        self.rewrite_stored_plan(plan_id, document)

    def assert_malformed(self, root: Path, plan_id: str) -> None:
        for answered in self.MALFORMED:
            with self.subTest(answered=answered):
                self.edit_answers(plan_id, answered)
                payload = self.refuse(root, plan_id, "adopt_failure")
                self.assertEqual(payload["error"]["repair_id"],
                                 "adopt.plan.malformed")

    def test_an_answered_plan_archives_the_candidate(self):
        root = answered_repo(self.home)
        plan_id = self.answered_plan(root)
        result = self.succeed(root, plan_id)
        files = self.branch_files(root, result["branch"])
        self.assertIn(ARCHIVED, files)
        self.assertNotIn(ODD, files)
        moves = json.loads(git(
            root, "show", f"{result['branch']}:{result['migration_map']}"))
        self.assertIn({"old_path": ODD, "new_path": ARCHIVED},
                      moves["moves"])
        record = json.loads(git(
            root, "show", f"{result['branch']}:{result['evidence_record']}"))
        self.assertIn({"id": "candidate-class", "subject": ODD,
                       "value": "archive-history"},
                      record["decisions_accepted"])
        stored = json.loads(self.stored_plan(plan_id).read_text("utf-8"))
        self.assertEqual(
            {gate["status"] for gate in stored["verification"]["commit_gates"]},
            {"passed"})

    def test_a_removed_stored_answer_is_plan_stale(self):
        root = answered_repo(self.home)
        plan_id = self.answered_plan(root)
        self.edit_answers(plan_id, [])
        self.refuse(root, plan_id, "plan_stale")

    def test_a_malformed_stored_answer_refuses_before_anything_runs(self):
        root = answered_repo(self.home)
        self.assert_malformed(root, self.answered_plan(root))

    def test_a_malformed_answer_on_a_draft_refuses_before_not_ready(self):
        root = answered_repo(self.home)
        draft = self.planned(root)
        self.assertEqual(draft["plan"]["state"], "draft")
        self.assert_malformed(root, draft["plan"]["plan_id"])

    def test_an_unstaged_edit_to_an_archived_source_is_a_dirty_worktree(self):
        root = answered_repo(self.home)
        plan_id = self.answered_plan(root)
        write(root, ODD, "# edited\n")
        self.refuse(root, plan_id, "dirty_worktree")
```

In `test_adopt_verify.py`, a class after `EvidenceDiscoveryTest`:

```python
class AnsweredCandidateVerifyTest(VerifyTestCase):
    def test_an_archived_candidate_verifies_as_adopted(self):
        root = apply_repo(self.home)
        write(root, ".claude/odd.md", "# odd\n")
        commit(root, "add an unclassified agent path")
        code, out, err = run("plan", "--repo-root", str(root), "--answer",
                             "candidate-class", ".claude/odd.md",
                             "archive-history", home=self.home)
        self.assertEqual(code, 0, err or out)
        plan_id = json.loads(out)["plan"]["plan_id"]
        code, out, err = run("apply", "--plan-id", plan_id, home=self.home)
        self.assertEqual(code, 0, err or out)
        git(root, "merge", "--ff-only", "--quiet", json.loads(out)["branch"])
        report = self.report(root)
        self.assertEqual(report["result"], "adopted", report["checks"])
        self.assertEqual(
            self.check(report, "no-unclassified-agent-path")["status"],
            "passed")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py -k CandidateAnswerTest`
Expected: FAIL, 13 tests — `--answer` is an argparse usage error (exit 2, empty stdout, so `payload` is `None`), the recommendation is Task 2's interim one, and `action_relocates("archive-history")` is `False`.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_apply.py home/common/agent-skills/tests/test_adopt_verify.py -k Answered`
Expected: FAIL — every test needing an answered plan stops at the `--answer` usage error, and the draft case refuses `not_ready` rather than `adopt_failure`.

- [ ] **Step 3: Write the minimal implementation**

1. `adopt_inspection`: `NOTES["answered"]`; move `"archive-history"` to the `True` branch of `action_relocates` and update its docstring to "Whether an action moves a candidate to a new home: a canonical one, or the adoption archive."; the `overlap_targets` condition as pinned.
2. `adopt_planning.apply_answers` exactly as the invariants pin, with a docstring stating the validation order and that nothing is mutated until every answer validates.
3. `adopt_apply.stored_answers` as pinned, beside `load_stored_plan`.
4. `adopt_inspection.question_recommendation("candidate-class")`: D8's final sentence as pinned.
5. `adopt_project`: the `compose_plan` signature and call; `command_plan` builds the answer list; `command_apply` calls `stored_answers` and passes its result as pinned, and the comment block above it gains one sentence: "The operator's answers travel inside the stored plan and are re-applied here; the recomputed digest is what authenticates them, so `apply` takes no answer of its own."; the `--answer` parser argument with help text "settle one open candidate-class question; repeatable"; the `answered` human line. Update the `compose_plan` docstring with one sentence: "`answered` is the operator's answers to open `candidate-class` questions, applied before anything else is derived, so they enter `plan_id`."

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_project_boundaries.py home/common/agent-skills/tests/test_adopt_apply.py home/common/agent-skills/tests/test_adopt_verify.py`
Expected: PASS, all four modules, no failures: an answered plan reaches `ready` and applies at this commit.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_inspection.py python/agent_tools/adopt_planning.py python/agent_tools/adopt_apply.py python/agent_tools/adopt_project.py home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_apply.py home/common/agent-skills/tests/test_adopt_verify.py
launch-commit … -- -m "feat(adopt): answer candidate-class questions in plan, replay them in apply (#340)"
```
