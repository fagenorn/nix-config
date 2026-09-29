# Task 3: `orchestrate-issues` states the one rule; evals and ceiling follow

**Files:**
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md` (§3 line ~204-207, §4 lines ~240 and ~340-345, §5 line ~350)
- Modify: `home/common/claude-code/skills/orchestrate-issues/evals/evals.json` (the two closed-kind enumerations, lines 10 and 18)
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (`### Explicit durable interactive acquisition`, one sentence; Phase-5 SF-1, per D12)
- Modify: `home/common/agent-skills/instruction-load.json` (profile `orchestration-dispatcher`, `ceiling_bytes.claude` and `note`, lines ~54-57)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (class `WorkflowSkillContractsTest`)

**Interfaces:**
- Consumes: Tasks 1–2's control action `{"id": "delivery_contract", "kind": "delivery_contract", "issues": [...]}`, returned only with no deadline armed, and accepted by the workflow-response boundary. Test helpers `self.orchestrate`, `self.orchestrate_evals`, `self.section(text, heading, next_heading)`, `self.assert_ordered(text, *anchors)`, module function `normalized(text)`.
- Produces: skill text only; no code interface.

**Invariants:**
- The adapter rule for `delivery_contract` is written once, in §4 (per D5); §3 only points to it.
- The skill and its evals never tell the adapter to override a returned action (issue AC4).
- The narrowed "deadline-less wait" sentence stays on one physical line (its test reads the raw file).
- The Codex stub `home/common/codex/skills/orchestrate-issues/SKILL.md` is unchanged (per D7).
- `test_the_live_tree_breaches_no_ceiling` passes with the ceiling set to the grown byte count exactly (per D10).

- [ ] **Step 1: Write the failing tests**

Add to `WorkflowSkillContractsTest`:

```python
    def test_dispatcher_answers_a_contract_request_with_one_rule(self):
        """#221 D5: `delivery_contract` has one rule, in §4, and no override."""
        decide = normalized(self.section(self.orchestrate, "## 3. Decide",
                                         "## 4. Execute control actions"))
        execute = normalized(self.section(self.orchestrate, "## 4. Execute control actions",
                                          "## 5. Final report"))
        final = normalized(self.section(self.orchestrate, "## 5. Final report", "## Notes"))
        self.assertIn("A `delivery_contract` action asks for exactly the contracts of the "
                      "issues it lists; §4 holds its rule.", decide)
        self.assert_ordered(execute, "For `delivery_contract`",
                            "This is the one rule for such an issue.",
                            "Send each listed issue's contract as §3 describes",
                            "make the next control call at once",
                            "Never rebuild an issue whose build this invocation refused",
                            "refused every listed issue", "ends the run as `finalize` does",
                            "render §5 from this response")
        self.assertEqual(normalized(self.orchestrate).count(
            "This is the one rule for such an issue."), 1)
        self.assertIn("or a `delivery_contract` action that ends the run", final)
        # Phase-5 SF-4: the refused-launch and parked-suspension passages name the
        # new no-deadline sweep too.
        self.assert_ordered(execute, "resumes on the next orchestrate invocation",
                            "or on the follow-up call a `delivery_contract` action asks for")
        self.assertIn("the sweep renders `finalize` (or `delivery_contract` when a missing "
                      "contract is all that stops some issue)", execute)
        # Phase-5 SF-1 (D12): the durable interactive route answers the same action.
        durable = normalized(self.section(self.from_issue,
            "### Explicit durable interactive acquisition", "## The flow"))
        self.assert_ordered(durable, "A `delivery_contract` reply naming this issue",
                            "build this issue's contract", "call `workflow-state control` once more",
                            "orchestrate-issues §4")
        for text in (self.orchestrate, json.dumps(self.orchestrate_evals)):
            self.assertNotIn("override", text.lower())
        expected = " ".join(case["expected_output"] for case in self.orchestrate_evals["evals"])
        self.assertIn("spawn, resume, retry, delivery_remainder, delivery_contract, wait, finalize",
                      expected)
        self.assertIn("spawn, resume, retry, delivery_remainder, delivery_contract, wait, or "
                      "finalize", expected)
```

Update existing anchors in the same class:
- `test_orchestrate_bootstrap_actions_and_projected_owner`: the anchor `` "`spawn`, `resume`, `retry`, `delivery_remainder`, `wait`, or `finalize`" `` becomes `` "`spawn`, `resume`, `retry`, `delivery_remainder`, `delivery_contract`, `wait`, or `finalize`" ``.
- `test_dispatcher_executes_the_closed_control_action_set`: the loop tuple becomes `("spawn", "resume", "retry", "delivery_contract", "wait", "finalize")`.
- `test_no_deadline_less_wait_is_armed`: the `assertIn` string becomes exactly `"control never returns a deadline-less wait; every wait carries deadline_at, and when nothing can proceed without a human, control returns finalize instead, or `delivery_contract` when a missing contract is all that stops an issue."` (joined from adjacent literals as today).

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k contract_request_with_one_rule -k bootstrap_actions_and_projected -k closed_control_action_set -k deadline_less_wait 2>&1 | tail -8`
Expected: 4 failures (the new anchors are absent from SKILL.md and evals.json at base).

- [ ] **Step 3: Edit the skill text, evals and ceiling**

SKILL.md (every sentence below is dictated verbatim; hard-wrap at ~80 columns except where noted):

1. §3, the bullet starting "On success the builder prints": append after "…null means the installed contract governs." the sentence: `A `delivery_contract` action asks for exactly the contracts of the issues it lists; §4 holds its rule.`
2. §4, first sentence: the closed kinds become `` `spawn`, `resume`, `retry`, `delivery_remainder`, `delivery_contract`, `wait`, or `finalize` ``.
3. §4, replace the one-line sentence "control never returns a deadline-less wait; every wait carries deadline_at, and when nothing can proceed without a human, control returns finalize instead." with, on one physical line: `control never returns a deadline-less wait; every wait carries deadline_at, and when nothing can proceed without a human, control returns finalize instead, or `delivery_contract` when a missing contract is all that stops an issue.`
4. §4, after the `finalize` paragraph (ending "Do not issue another control call merely to prepare the report.") and before `## 5. Final report`, add this paragraph (it describes control as Task 1 implements it: the action appears only with no deadline armed, listing issues that planned a contract):

   ```text
   For `delivery_contract`, a missing delivery contract is all that stops each
   issue in its `issues` list, and nothing else will wake the run: control armed
   no deadline. This is the one rule for such an issue. Send each listed issue's
   contract as §3 describes (the pair built for it earlier in this invocation,
   else build it now) and make the next control call at once; that response
   takes over from this one. Never rebuild an issue whose build this invocation
   refused: send null and `[]` for it. When the builder has refused every listed
   issue in this invocation, the action ends the run as `finalize` does: clear
   the wait state as for `finalize` and render §5 from this response.
   ```
5. §4, the refused-launch paragraph: extend its last sentence "…so an issue left in `admission.waiting` resumes on the next orchestrate invocation." to end "…resumes on the next orchestrate invocation, or on the follow-up call a `delivery_contract` action asks for." (Phase-5 SF-4, per D4).
6. §4, the parked-suspension paragraph: "once nothing else in the run is still running the sweep renders `finalize` and the later sweep…" becomes "…still running the sweep renders `finalize` (or `delivery_contract` when a missing contract is all that stops some issue) and the later sweep…" (Phase-5 SF-4).
7. §5, first sentence becomes: `Render a `finalize` action, or a `delivery_contract` action that ends the run because every listed build was refused, from the bounded summaries in the same interface_version 3 control response.` (hard-wrapped).

from-issue SKILL.md, `### Explicit durable interactive acquisition` (Phase-5 SF-1, per D12): after the sentence ending "…and on a reused run only once a control summary carries `delivery_contract_required` (send null until then).", insert: `A `delivery_contract` reply naming this issue is that ask, not a missing dispatch: build this issue's contract then and call `workflow-state control` once more, as orchestrate-issues §4 describes; only that follow-up reply is held to the dispatch rule below.` Check this against the live helper after Task 1: on a reused run with no installed contract, the first `direct`-route control call must indeed return `delivery_contract` for the issue; if it does not, write a TODO in the task report instead of the sentence and surface it.

evals.json (keep valid JSON; change only these substrings):
- line 10: `from the closed set spawn, resume, retry, delivery_remainder, wait, finalize;` → `from the closed set spawn, resume, retry, delivery_remainder, delivery_contract, wait, finalize;`
- line 18: `may return spawn, resume, retry, delivery_remainder, wait, or finalize` → `may return spawn, resume, retry, delivery_remainder, delivery_contract, wait, or finalize`

instruction-load.json, profile `orchestration-dispatcher` (per D10) — and likewise any profile covering from-issue's SKILL.md that `test_the_live_tree_breaches_no_ceiling` then names: set `ceiling_bytes.claude` to the new `wc -c < home/common/claude-code/skills/orchestrate-issues/SKILL.md` value, and append to its `note`: ` Ceiling raised for #221: §4's `delivery_contract` rule (#221 D10).`

- [ ] **Step 4: Verify**

Run the Step 2 command. Expected: 4 tests, `OK`.
Run: `python3 -c "import json;json.load(open('home/common/claude-code/skills/orchestrate-issues/evals/evals.json'))" && PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py 2>&1 | tail -4`
Expected: `OK` (before the ceiling edit, `test_the_live_tree_breaches_no_ceiling` fails naming `orchestration-dispatcher`; after it, it passes).
Run: `git diff --quiet 93bf5fd -- home/common/codex` — expect exit 0 (Codex stub untouched).

Then the plan's final verification: `just agent-workflow-tests 2>&1 | tail -5` (expect `OK`) and `just build 2>&1 | tail -3` (expect success).

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/skills/orchestrate-issues/SKILL.md home/common/claude-code/skills/orchestrate-issues/evals/evals.json home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(orchestrate-issues): answer control's delivery_contract with one rule (#221)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
