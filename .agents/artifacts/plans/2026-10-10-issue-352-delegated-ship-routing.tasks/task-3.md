# Task 3: Evals for the delegated ship route and the acceptance record

Issue: https://github.com/fagenorn/nix-config/issues/352. Spec: `.agents/artifacts/specs/2026-10-10-issue-352-delegated-ship-routing-design.md` (`## Test seams` item 3, `## Acceptance mapping`; ledger rows D8, D11).

Background for a reader with no context. Task 2 changed the `from-issue` skill text so that, when an owner delegates the rest of an issue to a fresh owner, the fresh (delegated) owner returns a validated ship handoff after Phase 6 and the delegating owner launches the ship owner. A skill eval is a JSON case in `skills/<skill>/evals/evals.json`. A `plan-only` case has a `prompt` and an `expected_output`; `just evals <skill> <id>` only prints the two, and a grader reads an agent's answer to the prompt against the expected output. This task adds three such cases, a test that they exist, grades each once, and writes the evidence columns of the acceptance record.

"Orchestrated depth" means the agent is below an orchestrator: cases 5 and 6 are the delegated owner and the delegating issue owner of an orchestrated run. Case 7 is the one situation that still ships inline: a context with no subagent-launch tool at all.

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/evals/evals.json`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Create: `.agents/artifacts/plans/2026-10-10-issue-352-delegated-ship-routing.acceptance.md`

**Interfaces:**
- Consumes from Task 2: the final text of `home/common/agent-skills/skills/from-issue/SKILL.md`, `delegated-owner.md` and `ship-handoff.md` (the evals are graded against it), and `FROM_ISSUE_DIR` in the test module.
- Consumes from Task 1: the test class `DelegatedShipLaunchTest` (its run is AC4's evidence).
- Produces: eval cases with ids 5, 6, 7 and the names `delegated-owner-returns-ship-handoff`, `delegating-owner-handles-delegated-return`, `no-subagent-launch-ships-inline`; the acceptance record with rows AC1–AC4.

**Invariants:**
- `evals.json` stays valid JSON in its existing format: two-space indent, non-ASCII characters written literally, one trailing newline. Cases 1–4 are byte-identical to before.
- Each new case has exactly the keys `id`, `name`, `mode`, `note`, `prompt`, `expected_output`, with `mode` `plan-only`.
- An `expected_output` describes what the skill text of Task 2 says. If grading shows the text does not support a clause, the clause is not edited to match: that is a finding against the text (Step 5).
- No skill document, helper or gate file changes in this task.

- [ ] **Step 1: Write the failing test**

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, add after the line `DELEGATED_RETURN_LINE = "Delegated owner: return the ship handoff"` (added by Task 2):

```python
FROM_ISSUE_EVALS = FROM_ISSUE_DIR / "evals/evals.json"
DELEGATED_SHIP_EVALS = (
    "delegated-owner-returns-ship-handoff",
    "delegating-owner-handles-delegated-return",
    "no-subagent-launch-ships-inline",
)
```

Add this method to `class WorkflowSkillContractsTest`, immediately before `def test_from_issue_phase_seven_ships_inline_on_the_dispatch_gap(self):`:

```python
    def test_from_issue_evals_cover_the_delegated_ship_route(self):
        # #352 D8: three plan-only cases, two at orchestrated depth.
        cases = {case["name"]: case
                 for case in json.loads(FROM_ISSUE_EVALS.read_text(encoding="utf-8"))["evals"]}
        for name in DELEGATED_SHIP_EVALS:
            with self.subTest(case=name):
                self.assertIn(name, cases)
                self.assertEqual(cases[name]["mode"], "plan-only")
                self.assertTrue(cases[name]["prompt"].strip())
                self.assertTrue(cases[name]["expected_output"].strip())
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_from_issue_evals_cover 2>&1 | grep -E "^(FAIL|Ran|FAILED|OK)"` (timeout 1800 s)
Expected: `Ran 1 test`, `FAILED (failures=3)`: each of the three names is `not found`.

- [ ] **Step 3: Add the three cases**

In `home/common/agent-skills/skills/from-issue/evals/evals.json`, the `evals` array ends with case 4 (`reconcile-existing-pr-with-scoped-authorization`). Put a comma after that case's closing `}` and add these three objects before the array's closing `]`. Each `prompt` and `expected_output` is one JSON string on one line.

````json
    {
      "id": 5,
      "name": "delegated-owner-returns-ship-handoff",
      "mode": "plan-only",
      "note": "#352 D1, D6: orchestrated depth. The delegated owner sits two levels below the orchestrator, so a ship owner it launched could launch no reviewer.",
      "prompt": "Plan-only: run no command and change nothing. You are a from-issue owner in `--auto` mode. An orchestrator launched an issue owner for issue 41, and that issue owner launched you, so the chain is orchestrator, issue owner, you. Your prompt carries a complete dispatcher envelope with lifecycle identity (action_id `41:1:1`), a `Resume pack` paragraph, the committed spec and plan paths, and, on a line of its own, `Delegated owner: return the ship handoff`. The ledger records Phase 5 as complete. Explain which from-issue file governs you and which part of it, what you do through Phase 6, what you do when a phase gate answers `delegate`, and exactly what you do and do not do once sdd's report has validated with `review_state` `clean`. Then say what you return if you must suspend instead.",
      "expected_output": "The owner reads `delegated-owner.md` first and follows only its `## Generic delegate` section, which the prompt line selects; the rollover checks in the section above it do not apply. It adopts the dispatcher envelope as the existing lifecycle identity and performs no acquisition. It runs Phase 6 (sdd, with writing workers registered under `41:1:1`) and takes any `delegate` gate action as `continue`: it never dispatches another issue owner. After Phase 6's gates pass it makes no Phase-6 `workflow-state progress` call and starts no Phase 7: it registers and launches no ship owner, does not invoke `ship-issue` as a subagent or inline, and does not take the dispatch-gap fallback. It rechecks the spec and plan roots and builds the `ship-handoff/v2` candidate as Phase 7's ship-owner prompt describes, validates it with `artifact-budget validate-report --boundary ship-handoff`, releases every worker it registered with `--event returned`, and returns only the validated handoff bytes. It runs no `launch-scope reap` on that return and writes no `finish`. A suspension is a different exit: it runs as SKILL.md's suspension procedure says, releasing workers and reaping before `workflow-state suspend`, and the owner returns only the `Suspended (blocked_on=<value>). Resume: ...` line that procedure prints."
    },
    {
      "id": 6,
      "name": "delegating-owner-handles-delegated-return",
      "mode": "plan-only",
      "note": "#352 D1-D3: orchestrated depth. The issue owner sits one level below the orchestrator, so the ship owner it launches can launch its reviewers.",
      "prompt": "Plan-only: run no command and change nothing. You are a from-issue issue owner in `--auto` mode, launched by orchestrate-issues for issue 41 with lifecycle identity (action_id `41:1:1`). Your `workflow-state progress` call for completed Phase 5 answered `delegate`, so you dispatched a fresh issue owner for the remainder. First: what did its prompt carry besides the envelope and the artifact paths? Second: say exactly what you do when that owner returns each of the following, one at a time. (a) Only the line `/from-issue 41 --auto`. (b) Only the line `Suspended (blocked_on=usage_limit). Resume: /from-issue 41 --auto`. (c) JSON that validates at `--boundary workflow-response`. (d) JSON that validates at `--boundary ship-handoff` with `state` `complete`, your `ledger_repo_root`, `run_id`, `owner` and issue number, and `custody.action_id` `41:1:1`. (e) JSON that validates at `--boundary ship-handoff` but carries `custody.action_id` `41:1:2`. (f) A paragraph of prose. Third: after (d), your own `workflow-state progress` call for Phase 6 answers `delegate`; what does that action mean here?",
      "expected_output": "First: a `Resume pack` paragraph holding the stdout of `workflow-state resume-pack` run with this owner's own `action_id`, the leaf-agent clauses, and the line `Delegated owner: return the ship handoff`; the delegated owner is never registered as a worker. Second, taking the first case that matches. (a) and (b): relay the line unchanged, write nothing (no `progress`, no `finish`), run no reap and stop; the delegated owner already reaped before its own exit write. (c): it is the delegated owner's own `finish` reply; relay those canonical bytes unchanged, write nothing, run no reap and stop. (d): the Phase-6 result. This owner calls `workflow-state progress` for completed Phase 6 itself with its own truthful usage, then runs Phase 7: it registers a worker under `41:1:1`, launches the fresh ship owner through the `from-issue-ship-owner` site with those validated bytes unchanged as the handoff (never rebuilt or edited), handles the ship report as `ship-handoff.md` says, and writes `finish` after the `check-launch` fence. The ship owner sits one level below this owner, so it launches its reviewers itself; nothing is shipped inline. (e) and (f): the identity differs or nothing validates, so each is a contract failure through the terminal return procedure: a `terminal_failed` `ship-summary/v2`, workers released, `launch-scope reap`, then the `check-launch` fence before `finish`; if the fence answers `current: false` because the delegated owner already ended the launch, write nothing and print the re-entry line. Third: off the direct-autonomous route a Phase-6 `delegate` is the Phase-7 ship-owner dispatch itself, never a second issue owner."
    },
    {
      "id": 7,
      "name": "no-subagent-launch-ships-inline",
      "mode": "plan-only",
      "note": "#352: the inline route stays only for a context that cannot launch a subagent at all.",
      "prompt": "Plan-only: run no command and change nothing. You are a from-issue owner in `--auto` mode at Phase 7 for issue 41, with lifecycle identity (action_id `41:1:1`) and a `ship-handoff/v2` you built and validated yourself. Your prompt carried no `Delegated owner: return the ship handoff` line. This host gives you no subagent-launch tool of any kind. Explain step by step how the issue is delivered, which ledger checks you make and when, and what you do if the ship-issue run itself reports `capability_gap: agent_dispatch`.",
      "expected_output": "A `from-issue-ship-owner` launch this context cannot make counts as the line `capability_gap: agent_dispatch`, so the owner takes `ship-handoff.md`'s dispatch-gap fallback; it is not a generic delegated owner, which never takes it. With lifecycle identity it first runs the `check-launch` fence with its own `action_id`: on `current: false` or any helper failure it writes nothing, prints `/from-issue 41 --auto` on its own line and stops. Otherwise it invokes `ship-issue` through its own Skill tool with the same validated handoff bytes and carries out the ship-owner prompt's task list itself: every phase, the auto-mode rules and the `## Delivery loop`, writing only `checkpoint-delivery` inside the loop. It handles the result as the ship report handling says: validate the `ship-summary/v2`, run `check-launch` again before the terminal write, then `workflow-state finish` with the validated summary on stdin, after releasing its workers and reaping. A `capability_gap: agent_dispatch` line from the inline run is the genuine gap: it never starts a second inline run, and the owner follows the suspension procedure with `blocked_on` `agent_dispatch`, makes no `finish` call and prints the `Suspended (...)` line with the re-entry command."
    }
````

- [ ] **Step 4: Verify the file and the test**

Run:

```bash
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("home/common/agent-skills/skills/from-issue/evals/evals.json")
raw = p.read_text(encoding="utf-8")
data = json.loads(raw)
assert json.dumps(data, indent=2, ensure_ascii=False) + "\n" == raw, "format drifted"
assert [c["id"] for c in data["evals"]] == [1, 2, 3, 4, 5, 6, 7]
for case in data["evals"][4:]:
    assert sorted(case) == ["expected_output", "id", "mode", "name", "note", "prompt"], case["name"]
print("evals ok")
PY
git diff "$(git merge-base origin/main HEAD)" -- home/common/agent-skills/skills/from-issue/evals/evals.json | grep -c '^-[^-]'
```

Expected: `evals ok`, then `0` (git shows the change as added lines only, so no line of cases 1–4 was removed). `grep -c` exits 1 when it counts zero; that exit is the passing case here.

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_delegated_return_line -k test_generic_delegated_owner_returns -k test_delegate_action_checks -k test_from_issue_evals_cover 2>&1 | tail -3` (timeout 1800 s)
Expected: `Ran 4 tests`, `OK`.

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_eval_cases.py home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -3` (timeout 1800 s)
Expected: `OK` (some skipped). These are the two suites that read eval files.

Run: `just evals from-issue 6 2>/dev/null | grep -c "eval 6: delegating-owner-handles-delegated-return (plan-only)"`
Expected: `1`.

Commit:

```bash
git add home/common/agent-skills/skills/from-issue/evals/evals.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "test(from-issue): evals for the delegated ship route (#352)"
```

- [ ] **Step 5: Grade each new eval once**

Record `git rev-parse --short HEAD` first: it is the graded commit. For each of ids 5, 6 and 7, run `just evals from-issue <id>` to print the prompt and the expected output, then grade once (D11):

- If you have a subagent-launch tool, launch one fresh agent per case, by type and never by name. Its whole prompt is the eval's `prompt` verbatim, followed by: "Answer from these files only, reading each in full first, and read nothing under any `evals` or `tests` directory:" and the absolute paths, in this worktree, of `home/common/agent-skills/skills/from-issue/SKILL.md`, `AUTO.md`, `delegated-owner.md`, `ship-handoff.md` and `acquire-dispatcher.md`. Do not show it the expected output.
- If you have no such tool, answer the prompt yourself after re-reading those five files in full, before looking at the expected output again, and record the grader as `inline`.

Compare the answer with `expected_output` clause by clause. The case passes when every clause is stated or plainly implied by the answer and none is contradicted. Note each clause that failed.

A failed case is not repaired here: do not edit `expected_output` to match the answer, and do not edit the skill text, whose bytes are budgeted. Finish the record with the failure in it and report DONE_WITH_CONCERNS, naming the case, the clause and the sentence of skill text that led the answer astray, so the controller decides the fix.

- [ ] **Step 6: Write the acceptance record**

Run the two code checks that are this record's cited runs:

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k DelegatedShipLaunchTest 2>&1 | tail -3` (timeout 1800 s)
Expected: `Ran 3 tests`, `OK`.

Run: `just agent-instruction-budget` (timeout 600 s)
Expected: `check: pass`.

Create `.agents/artifacts/plans/2026-10-10-issue-352-delegated-ship-routing.acceptance.md` with this content. Replace each `<…>` with what you observed; `<sha>` is the graded commit from Step 5. Leave the `Verdict` cells empty: the sdd controller writes them (the spec's `## Acceptance mapping` expects `human_pending` for AC1 and AC2).

````markdown
# Acceptance record — issue #352

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [evidence] A rolled-over orchestrated issue ships through a dedicated ship agent that launches its reviewers itself — measured: subagent transcripts of the next orchestrated nodocom run with ≥ 2 rolled-over issues; 0 hand-backs consisting of `capability_gap: agent_dispatch`, baseline 3 of 3. | evidence | Read the subagent transcripts of the next orchestrated nodocom run with ≥ 2 rolled-over issues; threshold: 0 `capability_gap: agent_dispatch` hand-backs | not measured: that run has not happened and cannot be produced in this repository | — | needs the deployed skill text and a consumer-project run | |
| AC2 | [evidence] The ship phase's average context per turn is ≤ 200k tokens — measured: mean of `cache_read_input_tokens + cache_creation_input_tokens` per request across the ship agent's transcript in that run; baseline 330–380k inline. | evidence | Mean of `cache_read_input_tokens + cache_creation_input_tokens` per request across the ship agent's transcript in that run; threshold: ≤ 200000 | not measured: same run as AC1 | — | needs the deployed skill text and a consumer-project run | |
| AC3 | [code] The rollover and ship-handoff instructions route delivery through a level that can dispatch, and keep the inline route only for a host without subagent launch — measured: the from-issue skill evals covering rollover delivery, including one case at orchestrated depth. | code | Evals 5, 6 (orchestrated depth) and 7 graded once each; `unittest test_workflow_skill_contracts.py -k test_delegated_return_line -k test_generic_delegated_owner_returns -k test_delegate_action_checks -k test_from_issue_evals_cover`; `just agent-instruction-budget` | eval 5 <pass or fail: clause>; eval 6 <pass or fail: clause>; eval 7 <pass or fail: clause>; contract tests <Ran N tests, result>; budget <output line> | <sha> | grader: <fresh subagent or inline>; skill text read from this worktree | |
| AC4 | [code] Launch identity is unchanged by the new route: one attempt, one ship owner, forge writes fenced by check-launch — measured: workflow-state tests for a delegated ship launch from the issue owner after a returned implementation owner. | code | `unittest test_workflow_state.py -k DelegatedShipLaunchTest` | <Ran N tests, result> | <sha> | ledger helper unchanged from the merge base | |
````

- [ ] **Step 7: Verify and commit the record**

Run: `f=.agents/artifacts/plans/2026-10-10-issue-352-delegated-ship-routing.acceptance.md; grep -c '^| AC[1-4] |' "$f"; if grep -q '<' "$f"; then echo "unfilled placeholder"; exit 1; fi`
Expected: `4`, and no `unfilled placeholder` line.

```bash
git add .agents/artifacts/plans/2026-10-10-issue-352-delegated-ship-routing.acceptance.md
git commit -m "docs(issue-352): acceptance record evidence for the delegated ship route"
```
