# Task 4: `apply` honours stored answers; contract documented

**Files:**
- Modify: `python/agent_tools/adopt_apply.py` (new `stored_answers`)
- Modify: `python/agent_tools/adopt_project.py` (`command_apply`)
- Modify: `python/README.md` (new `## adopt-project` section)
- Test: `home/common/agent-skills/tests/test_adopt_apply.py`
- Test: `home/common/agent-skills/tests/test_adopt_verify.py`

**Interfaces:**
- Consumes (Task 3): `compose_plan(root: Path, manifest: dict, answered: list[dict]) -> Composition`; `plan --answer QUESTION SUBJECT VALUE`; an answered tracked candidate becomes a `git-mv` to `.agents/knowledge/archive/adopted/<path>`; refusals `adopt.decisions.invalid_answer` / `adopt.decisions.unmatched_answer`.
- Produces: `adopt_apply.stored_answers(document: dict) -> list[dict]` — returns `document["decisions"]["answered"]` when `document["decisions"]` is a dict whose `answered` is a list of dicts, each with exactly the keys `id`, `subject`, `value` and only string values; otherwise raises `refuse("adopt_failure", "adopt.plan.malformed", "/decisions/answered", "the stored plan's answered decisions are not well formed")` (D9).

**Invariants:**
- `command_apply` calls `answers = adopt_apply.stored_answers(document)` immediately after `load_stored_plan`, before the `not_ready` check, and passes `answers` to `compose_plan` in place of Task 3's `[]` (D5, D9). `apply` gains no flag (D16).
- A tampered answer is caught by the existing recomputation (`plan_stale` / `adopt.plan.inputs_changed`) or by the shared validation (`adopt_failure`); no new apply-side check is added.
- Every refusal mutates nothing (the `ApplyTestCase.refuse` witnesses).
- README prose describes the code as merged; no sentence promises reference rewriting (D6).

- [ ] **Step 1: Write the failing tests**

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

    def answered_plan(self, root: Path) -> str:
        code, out, err = run("plan", "--repo-root", str(root), "--answer",
                             "candidate-class", ODD, "archive-history",
                             home=self.home)
        self.assertEqual(code, 0, err or out)
        document = json.loads(out)
        self.assertEqual(document["plan"]["state"], "ready",
                         document["plan"]["blockers"])
        return document["plan"]["plan_id"]

    def edit_answers(self, plan_id: str, answered: object) -> None:
        document = json.loads(self.stored_plan(plan_id).read_text("utf-8"))
        document["decisions"]["answered"] = answered
        self.rewrite_stored_plan(plan_id, document)

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
        plan_id = self.answered_plan(root)
        for answered in ([{"id": "candidate-class", "subject": ODD}],
                         {"id": "candidate-class"},
                         [{"id": "candidate-class", "subject": ODD,
                           "value": None}]):
            with self.subTest(answered=answered):
                self.edit_answers(plan_id, answered)
                payload = self.refuse(root, plan_id, "adopt_failure")
                self.assertEqual(payload["error"]["repair_id"],
                                 "adopt.plan.malformed")

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

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_apply.py home/common/agent-skills/tests/test_adopt_verify.py -k Answered`
Expected: FAIL — `test_an_answered_plan_archives_the_candidate`, `test_an_unstaged_edit_to_an_archived_source_is_a_dirty_worktree` and `test_an_archived_candidate_verifies_as_adopted` exit 2 with `plan_stale` (apply re-derives with no answers), and the malformed case reports `plan_stale` rather than `adopt_failure`. `test_a_removed_stored_answer_is_plan_stale` already passes; it is the tampering regression pin.

- [ ] **Step 3: Write the minimal implementation**

1. `adopt_apply.stored_answers` as pinned, beside `load_stored_plan`.
2. `adopt_project.command_apply`: the call and the `compose_plan` argument as pinned. Extend the comment block above `command_apply` with one sentence: "The operator's answers travel inside the stored plan and are re-applied here; the recomputed digest is what authenticates them, so `apply` takes no answer of its own."
3. `python/README.md`: add `## adopt-project` after `## lane-triage`, one paragraph in the file's style, covering: `plan` asks two questions, `project-id` (answered by one remote or an authored contract) and `candidate-class` (one per tracked or targeted-ignored agent path no classification row covers, keyed by `subject`, whose `value` is the one accepted answer — `archive-history`, a `git mv` to `.agents/knowledge/archive/adopted/<path>`, for a tracked path; `retain-product` for an ignored one; `null`, no answer, for a secret-shaped path); `plan --answer QUESTION SUBJECT VALUE` (repeatable) settles a `candidate-class` question and refuses `adopt.decisions.invalid_answer` or `adopt.decisions.unmatched_answer`; the answers enter `decisions.answered` and therefore `plan_id`, and `apply --plan-id` re-applies them from the stored plan, so the id, not an `apply` flag, authenticates them. Read the merged code of Tasks 2–4 before writing each clause and state only what it does.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_apply.py home/common/agent-skills/tests/test_adopt_verify.py home/common/agent-skills/tests/test_adopt_project.py`
Expected: PASS, all three modules, no failures.

Run: `if ! grep -q '^## adopt-project$' python/README.md; then echo "README section missing"; exit 1; fi`
Expected: no output, exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_apply.py python/agent_tools/adopt_project.py python/README.md home/common/agent-skills/tests/test_adopt_apply.py home/common/agent-skills/tests/test_adopt_verify.py
launch-commit … -- -m "feat(adopt): apply re-derives answered plans from the stored answers (#340)"
```
