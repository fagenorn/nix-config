# Task 4: The answer contract is documented

**Files:**
- Modify: `python/README.md` (new `## adopt-project` section)

**Interfaces:**
- Consumes (Tasks 2–3, already committed and green): the `candidate-class` question and its fixed prose; `plan --answer QUESTION SUBJECT VALUE`; an answered tracked candidate becomes a `git-mv` to `.agents/knowledge/archive/adopted/<path>`; refusals `adopt.decisions.invalid_answer` / `adopt.decisions.unmatched_answer`; `apply`'s replay of the stored answers through `stored_answers`, refusing a malformed store as `adopt.plan.malformed`.
- Produces: documentation only. No code or test changes; the answer feature is complete at Task 3's commit.

**Invariants:**
- README prose describes the code as merged; no sentence promises reference rewriting (D6).
- No production or test file changes in this task.

- [ ] **Step 1: Read the merged code**

Read `adopt_inspection` (`QUESTION_IDS`, `CANDIDATE_BASIS`, `candidate_answer`, `question_recommendation`), `adopt_planning.apply_answers`, `adopt_apply.stored_answers` and `adopt_project.command_plan` / `command_apply` at the branch head. Each README clause below states only what that code does.

- [ ] **Step 2: Write the section**

`python/README.md`: add `## adopt-project` after `## lane-triage`, one paragraph in the file's style, covering: `plan` asks two questions, `project-id` (answered by one remote or an authored contract) and `candidate-class` (one per tracked or targeted-ignored agent path no classification row covers, keyed by `subject`, whose `value` is the one accepted answer — `archive-history`, a `git mv` to `.agents/knowledge/archive/adopted/<path>`, for a tracked path; `retain-product` for an ignored one; `null`, no answer, for a secret-shaped path); `plan --answer QUESTION SUBJECT VALUE` (repeatable, order-independent) settles a `candidate-class` question and refuses `adopt.decisions.invalid_answer` or `adopt.decisions.unmatched_answer` on the first violation in D9's order; the answers enter `decisions.answered` and therefore `plan_id`, and `apply --plan-id` re-applies them from the stored plan, so the id, not an `apply` flag, authenticates them.

- [ ] **Step 3: Verify**

Run: `if ! grep -q '^## adopt-project$' python/README.md; then echo "README section missing"; exit 1; fi`
Expected: no output, exit 0.

Run: `git diff --name-only HEAD`
Expected: exactly `python/README.md`.

- [ ] **Step 4: Commit**

```bash
git add python/README.md
launch-commit … -- -m "docs(adopt): document candidate-class questions and plan --answer (#340)"
```
