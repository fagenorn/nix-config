# Task 2: Grade evals 5, 6 and 7 once and write the acceptance evidence

Issue: https://github.com/fagenorn/nix-config/issues/362. Spec: `.agents/artifacts/specs/2026-10-11-issue-362-delegated-return-reasons-design.md` (`## Decisions`: "Grading", "On the merged text", "352's record, AC3 row"; ledger rows D3, D4, D5, D7, D8, D9, D10).

Background for a reader with no context. A skill eval is a JSON case in `home/common/agent-skills/skills/from-issue/evals/evals.json`. Cases 5, 6 and 7 are `plan-only`: each has a `prompt` and an `expected_output`, an agent answers the prompt from the skill's files, and a grader compares the answer with the expected output clause by clause. Issue 352 merged with its third acceptance criterion `unmet` because case 6 failed on two sub-clauses. Task 1 of this plan added the two missing reasons to `SKILL.md`. This task measures the result: it grades the three cases once each on the committed text, appends the outcome to the AC3 row of 352's acceptance record, and writes the evidence columns of this issue's own acceptance record.

You are the grader who compares. The answers come from three fresh subagents that see only a case prompt and five skill files. You never answer a case yourself, and the outcome is not yours to improve: a failed grading is recorded as it happened.

**Files:**
- Modify: `.agents/artifacts/plans/2026-10-10-issue-352-delegated-ship-routing.acceptance.md` (the AC3 row only)
- Create: `.agents/artifacts/plans/2026-10-11-issue-362-delegated-return-reasons.acceptance.md`
- Test: none added.

**Interfaces:**
- Consumes from Task 1: the committed `home/common/agent-skills/skills/from-issue/SKILL.md`, in which each of these strings occurs exactly once: ` line (the delegated owner already reaped before its own exit), or bytes valid at ` and `` `terminal_failed` (these alone mean it already ended the launch itself): relay it, ``.
- Produces: 352's AC3 row extended; this issue's acceptance record with rows AC1–AC4, evidence columns filled and `Verdict` cells empty (the sdd controller writes them).

**Invariants:**
- No file under `home/` changes in this task: no skill document, eval case or test. "The five graded files" are `SKILL.md`, `AUTO.md`, `delegated-owner.md`, `ship-handoff.md` and `acquire-dispatcher.md` under `home/common/agent-skills/skills/from-issue/`.
- Each case is graded exactly once, from the one answer its subagent returned. A case is never relaunched because its answer was weak or failed. Only a launch that returns no answer at all (a tool error, an empty reply) is launched again, and the Conditions text then says so.
- All measurements are made at one commit, the graded commit `G`, with a clean tree.
- In 352's record only the AC3 row changes. Its first four cells are unchanged; its Observed, Commit and Conditions cells are their old text followed by `; ` and the new text; its Verdict is `met` or `unmet` by the rule the script applies (D5).
- Every sentence written into either record describes what was observed in this run. Where a template phrase below is not true of what happened, change the phrase.

Two scripts follow. The first writes each case's grading prompt and expected output to files, so nothing is retyped. The second extends 352's AC3 row and checks the extension.

```python
# begin prompts
"""Issue 362: write the grading prompt and the expected output of evals 5, 6, 7.

usage: prompts.py <output directory>   (run from the worktree root)
"""
import json
import pathlib
import sys

SKILL = pathlib.Path("home/common/agent-skills/skills/from-issue")
FILES = ("SKILL.md", "AUTO.md", "delegated-owner.md", "ship-handoff.md", "acquire-dispatcher.md")
SENTENCE = (
    "Answer from these files only, reading each in full first, and read nothing"
    " under any `evals` or `tests` directory:"
)
NAMES = {
    5: "delegated-owner-returns-ship-handoff",
    6: "delegating-owner-handles-delegated-return",
    7: "no-subagent-launch-ships-inline",
}


def main(out: pathlib.Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    cases = {c["id"]: c for c in json.loads((SKILL / "evals/evals.json").read_text(encoding="utf-8"))["evals"]}
    paths = [(SKILL / name).resolve(strict=True) for name in FILES]
    for case_id, name in NAMES.items():
        case = cases[case_id]
        if case["name"] != name or case["mode"] != "plan-only":
            print(f"eval {case_id} is not the plan-only case {name}")
            return 1
        prompt = case["prompt"] + "\n\n" + SENTENCE + "\n" + "".join(f"{p}\n" for p in paths)
        (out / f"prompt-{case_id}.txt").write_text(prompt, encoding="utf-8")
        (out / f"expected-{case_id}.txt").write_text(case["expected_output"] + "\n", encoding="utf-8")
        print(f"eval {case_id}: {name}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(pathlib.Path(sys.argv[1])))
# end prompts
```

```python
# begin record
"""Issue 362: extend the AC3 row of issue 352's acceptance record.

usage: record.py extend <additions.json> | check <base commit>
(run from the worktree root)

additions.json holds the strings `observed`, `commit` and `conditions`, each
appended to its cell after "; ", and `passes`, an object of six booleans. The
verdict is `met` only when all six are true (spec D5). `check` compares the
file with its version at <base commit>.
"""
import json
import pathlib
import subprocess
import sys

PATH = ".agents/artifacts/plans/2026-10-10-issue-352-delegated-ship-routing.acceptance.md"
PASSES = ("eval_5", "eval_6", "eval_7", "contract_tests", "workflow_tests", "budget_gate")
OBSERVED, COMMIT, CONDITIONS, VERDICT = 4, 5, 6, 7
EXTENDED = ((OBSERVED, "observed"), (COMMIT, "commit"), (CONDITIONS, "conditions"))


def split(text):
    """Return (lines, index of the AC3 row, its eight cells)."""
    lines = text.split("\n")
    rows = [i for i, line in enumerate(lines) if line.startswith("| AC3 | ")]
    if len(rows) != 1 or not lines[rows[0]].endswith(" |"):
        raise SystemExit("record: expected exactly one AC3 row")
    cells = lines[rows[0]][2:-2].split(" | ")
    if len(cells) != 8:
        raise SystemExit(f"record: AC3 row has {len(cells)} cells, expected 8")
    return lines, rows[0], cells


def extend(additions_path):
    add = json.loads(pathlib.Path(additions_path).read_text(encoding="utf-8"))
    passes = add["passes"]
    if sorted(passes) != sorted(PASSES) or not all(type(v) is bool for v in passes.values()):
        raise SystemExit(f"record: passes needs exactly the booleans {', '.join(PASSES)}")
    path = pathlib.Path(PATH)
    lines, row, cells = split(path.read_text(encoding="utf-8"))
    for index, key in EXTENDED:
        value = add[key].strip()
        if not value or any(mark in value for mark in ("|", "\n", "<", ">")):
            raise SystemExit(f"record: {key} is empty or holds '|', a newline or an unfilled <...>")
        if cells[index].endswith("; " + value):
            raise SystemExit(f"record: {key} is already appended")
        cells[index] += "; " + value
    cells[VERDICT] = "met" if all(passes.values()) else "unmet"
    lines[row] = "| " + " | ".join(cells) + " |"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"record: AC3 extended, verdict {cells[VERDICT]}")
    return 0


def check(base):
    shown = subprocess.run(
        ["git", "show", f"{base}:{PATH}"], check=True, capture_output=True, text=True, encoding="utf-8"
    )
    old_lines, old_row, old = split(shown.stdout)
    new_lines, new_row, new = split(pathlib.Path(PATH).read_text(encoding="utf-8"))
    problems = []
    if old_lines[:old_row] + old_lines[old_row + 1:] != new_lines[:new_row] + new_lines[new_row + 1:]:
        problems.append("a line other than the AC3 row changed")
    if old[:OBSERVED] != new[:OBSERVED]:
        problems.append("one of the first four AC3 cells changed")
    for index, key in EXTENDED:
        added = new[index][len(old[index]):]
        if not new[index].startswith(old[index] + "; ") or "362" not in added or "<" in added:
            problems.append(f"{key} is not the old cell plus a filled-in issue 362 extension")
    if new[VERDICT] not in ("met", "unmet"):
        problems.append(f"verdict is {new[VERDICT]!r}")
    for line in problems:
        print(line)
    print("record: fail" if problems else f"record: pass, verdict {new[VERDICT]}")
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("extend", "check"):
        sys.exit(__doc__)
    sys.exit(extend(sys.argv[2]) if sys.argv[1] == "extend" else check(sys.argv[2]))
# end record
```

In every command below, `SCRATCH` is your scratch directory (Global Constraints), `TASK` is `.agents/artifacts/plans/2026-10-11-issue-362-delegated-return-reasons.tasks/task-2.md`, and `G` is the graded commit's 8-character id from Step 1. Write all three literally into each command.

- [ ] **Step 1: Fix the graded commit and watch the record check fail**

Run:

```bash
git status --porcelain
git rev-parse --short=8 HEAD
S=home/common/agent-skills/skills/from-issue/SKILL.md
grep -c -F ' line (the delegated owner already reaped before its own exit), or bytes valid at ' "$S"
grep -c -F '`terminal_failed` (these alone mean it already ended the launch itself): relay it,' "$S"
```

Expected: no output from `git status --porcelain` (a clean tree: nothing modified, nothing untracked); an 8-character id, which is `G`; then `1` and `1`. A dirty tree or a `0` means Task 1's text is not committed here: stop and report BLOCKED.

Run:

```bash
block() { sed -n "/^# begin $1\$/,/^# end $1\$/p" "$2" | sed '1d;$d'; }
block prompts "$TASK" > "$SCRATCH/prompts.py"
block record "$TASK" > "$SCRATCH/record.py"
python3 "$SCRATCH/record.py" check "$G"
```

Expected: exit 1. Three lines ending `is not the old cell plus a filled-in issue 362 extension`, then `record: fail`.

- [ ] **Step 2: Run the three code checks at `G`**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_delegated_return_line -k test_generic_delegated_owner_returns -k test_delegate_action_checks -k test_from_issue_evals_cover 2>&1 | tail -3` (timeout 600 s)
Expected: `Ran 4 tests`, `OK`.

Run: `just agent-instruction-budget 2>&1 | tail -1` (timeout 600 s)
Expected: `check: pass`.

Run: `just agent-workflow-tests > "$SCRATCH/workflow-tests.log" 2>&1; echo "exit $?"; tail -3 "$SCRATCH/workflow-tests.log"` (timeout 5400 s; about 30 minutes)
Expected: `exit 0`, a `Ran <N> tests in …` line and `OK` (some skipped). This is the one full-suite run this task makes (D9); sdd's final gate runs the suite again on the final head.

Keep the three result lines: they go into both records. If any of the three does not pass, do not grade: stop and report BLOCKED with the failing lines (for the suite, `grep -E '^(FAIL|ERROR):' "$SCRATCH/workflow-tests.log"`). A failing check is a defect in the text Task 1 committed, and a grading made on text that must change would be wasted.

- [ ] **Step 3: Launch one fresh answerer per case**

Run: `python3 "$SCRATCH/prompts.py" "$SCRATCH/grade"`
Expected: three lines, `eval 5: delegated-owner-returns-ship-handoff`, `eval 6: delegating-owner-handles-delegated-return`, `eval 7: no-subagent-launch-ships-inline`. The directory now holds `prompt-5.txt`, `prompt-6.txt`, `prompt-7.txt` and the three `expected-*.txt` files.

Launch three subagents of type `general-purpose`, by type and never by name, one per case. The whole prompt of each is the content of its `prompt-<id>.txt`, unchanged: the case prompt, the sentence "Answer from these files only, reading each in full first, and read nothing under any `evals` or `tests` directory:" and the absolute paths of the five graded files in this worktree. Add nothing: no expected output, no hint about what is being measured, no mention of this issue. Wait for all three in the same turn.

Save each returned answer, unedited, to `$SCRATCH/grade/answer-<id>.md`.

If you have no tool that launches a subagent, do not answer the cases yourself: you have read the expected outputs and the plan, so you are not a fresh answerer (D8). Stop and report BLOCKED with the line `needs subagent launch: three general-purpose answerers`, the path of `$SCRATCH/grade` and the value of `G`, so the controller launches them and resumes you with the three answers.

Then run `git status --porcelain; git rev-parse --short=8 HEAD`.
Expected: no status output, and `G`. An answerer that changed the tree broke the grading conditions: stop and report BLOCKED with the status output.

- [ ] **Step 4: Grade each answer once**

For each case, read `expected-<id>.txt` and split it into its clauses (sentence by sentence; in case 6, by its parts "First", "Second" with sub-cases (a) to (f), "Third", "Fourth"). Compare `answer-<id>.md` with it clause by clause. The case passes when every clause is stated or plainly implied by the answer and none is contradicted. Note every clause that is missing or contradicted, in the expected output's own words.

Case 6 has a tighter rule for two sub-clauses, the ones that failed at `3c0090fb`. Each must be stated in the answer; "plainly implied" does not pass them:

- Under returns (a) and (b): the delegated owner already reaped before its own exit. An answer that says "before its own exit" where the expected output says "before its own exit write" states it; the fact graded is that the reap came first. An answer that gives the reason under (a) and says the same holds for (b) states it for both.
- Under return (c): only bytes that validate as `terminal` or `terminal_failed` mean the delegated owner already ended the launch itself.

Write one line per case to `$SCRATCH/grade/verdicts.md`, in one of these forms:

- `eval <id> pass: every clause stated or plainly implied`; for eval 6 add `; (a)/(b) the delegated owner already reaped before its own exit: stated; (c) only terminal or terminal_failed bytes mean it already ended the launch itself: stated`.
- `eval <id> fail: ` followed by each failed clause, named as the expected output names it, and for eval 6 whether each of the two sub-clauses was stated, only implied, or absent.

For each failed clause, search the five graded files for the fact it names and note which holds: a file states it (the file and the sentence), or none of the five states it. The controller needs that distinction (D3, D8). You do not edit a skill file, an expected output or a prompt, and you do not launch a second answerer for a case that has an answer.

- [ ] **Step 5: Extend 352's AC3 row**

Write `$SCRATCH/additions.json` from this template. Replace every `<…>` with what you observed: `<G>` with the graded commit id, each `<eval N verdict>` with that case's line from `verdicts.md` without its leading `eval N `, the three result placeholders with the lines from Step 2 (for example `Ran 4 tests, OK`), and `<relaunch note>` with nothing, or with `; eval <id> launched again once because the first launch returned no answer` if that happened. The values may not contain `|`, `<`, `>` or a line break; escape `"` as `\"`. Set each of the six booleans to whether that item passed.

```json
{
  "observed": "issue 362 (the two reasons stated in the `delegate` action of `SKILL.md`, paid for by two cuts in the same file, net 0 bytes), evals 5, 6 and 7 graded once each at <G>: eval 5 <eval 5 verdict>; eval 6 <eval 6 verdict>; eval 7 <eval 7 verdict>; at <G> the four contract tests: <contract tests result>; `just agent-workflow-tests`: <suite result>; budget <gate output line>",
  "commit": "<G> (issue 362: evals 5, 6 and 7; contract tests; `just agent-workflow-tests`; budget gate)",
  "conditions": "issue 362: grader: fresh subagent (one per case, general-purpose), shown only the case prompt and the five skill files (`SKILL.md`, `AUTO.md`, `delegated-owner.md`, `ship-handoff.md`, `acquire-dispatcher.md` of the from-issue skill), read from this worktree at <G> with a clean tree; each case graded exactly once<relaunch note>; no case edited; eval 6 passes only with the two sub-clauses that failed at 3c0090fb stated, not implied; the gradings stand for any commit where `git diff --quiet <G> HEAD -- home/common/agent-skills/skills/from-issue/{SKILL,AUTO,delegated-owner,ship-handoff,acquire-dispatcher}.md` exits 0",
  "passes": {
    "eval_5": false,
    "eval_6": false,
    "eval_7": false,
    "contract_tests": false,
    "workflow_tests": false,
    "budget_gate": false
  }
}
```

Run:

```bash
python3 "$SCRATCH/record.py" extend "$SCRATCH/additions.json"
python3 "$SCRATCH/record.py" check "$G"
git diff --numstat -- .agents/artifacts/plans/2026-10-10-issue-352-delegated-ship-routing.acceptance.md
git diff --quiet "$G" HEAD -- home/common/agent-skills/skills/from-issue/{SKILL,AUTO,delegated-owner,ship-handoff,acquire-dispatcher}.md; echo "five files: $?"
```

Expected: `record: AC3 extended, verdict <met or unmet>`; `record: pass, verdict <the same>`; one numstat line beginning `1	1	`; `five files: 0`. The verdict is `met` exactly when all six booleans are true; check that it is the one your observations give.

Commit, then note the new commit's id as `R`:

```bash
git add .agents/artifacts/plans/2026-10-10-issue-352-delegated-ship-routing.acceptance.md
git commit -m "docs(issue-352): extend the AC3 row with the issue 362 gradings"
git rev-parse --short=8 HEAD
```

- [ ] **Step 6: Write this issue's acceptance record**

Run: `grep -c '^. AC3 . .* . met .$' .agents/artifacts/plans/2026-10-10-issue-352-delegated-ship-routing.acceptance.md`
Expected: `1` when Step 5's verdict was `met`, `0` otherwise (`grep -c` exits 1 on `0`). Keep the number printed.

Create `.agents/artifacts/plans/2026-10-11-issue-362-delegated-return-reasons.acceptance.md` with this content. Replace each `<…>` as in Step 5; `<R>` is the commit from Step 5 and `<count>` the number just printed. Leave the four `Verdict` cells empty: the sdd controller writes them.

````markdown
# Acceptance record — issue #362

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] from-issue eval 6 grades pass, with clauses (a) and (c) stated rather than implied — measured: one grading of eval 6 by a fresh grader shown only the case prompt and the skill files, on the merged text. | code | Eval 6 graded once; pass needs every clause stated or plainly implied, none contradicted, and the two sub-clauses that failed at 3c0090fb stated | eval 6 <eval 6 verdict> | <G> | grader: fresh subagent (general-purpose), shown only the case prompt and the five from-issue skill files, read from this worktree at <G> with a clean tree; graded exactly once<relaunch note>; case not edited; stands for any commit where `git diff --quiet <G> HEAD -- home/common/agent-skills/skills/from-issue/{SKILL,AUTO,delegated-owner,ship-handoff,acquire-dispatcher}.md` exits 0; the merge commit itself was not graded | |
| AC2 | [code] Evals 5 and 7 still pass on the same text — measured: one grading of each, same method. | code | Evals 5 and 7 graded once each at the same commit as eval 6; pass needs every clause stated or plainly implied, none contradicted | eval 5 <eval 5 verdict>; eval 7 <eval 7 verdict> | <G> | same grader, files, tree and byte-identity condition as AC1; one fresh subagent per case | |
| AC3 | [code] The contract tests and the budget gate stay green — measured: `just agent-workflow-tests` and `just agent-instruction-budget`. | code | `just agent-workflow-tests`; `just agent-instruction-budget` | `just agent-workflow-tests`: <suite result>; budget <gate output line>; the four delegated-return contract tests: <contract tests result> | <G> | run at <G> with a clean tree; no raise label; `home/common/agent-skills/instruction-load.json` unchanged from the merge base | |
| AC4 | [evidence] #352's acceptance record shows AC3 as met — measured: the AC3 row of that record, updated with the new gradings and commit. | evidence | `grep -c '^. AC3 . .* . met .$' .agents/artifacts/plans/2026-10-10-issue-352-delegated-ship-routing.acceptance.md`; threshold: `1` | prints <count>; the row's Observed, Commit and Conditions cells were extended with the gradings and runs at <G>, its earlier history unchanged | <R> | the row's verdict is `met` only when evals 5, 6 and 7, the four contract tests, `just agent-workflow-tests` and the budget gate all passed at <G> | |
````

The AC4 command writes `.` where the row has `|`, so the command can sit in a table cell.

- [ ] **Step 7: Verify and commit the record**

Run:

```bash
f=.agents/artifacts/plans/2026-10-11-issue-362-delegated-return-reasons.acceptance.md
grep -c '^| AC[1-4] |' "$f"
if grep -q '<' "$f"; then echo "unfilled placeholder"; exit 1; fi
if git diff --name-only "$G" -- home | grep -q .; then echo "a file under home/ changed"; exit 1; fi
python3 "$SCRATCH/record.py" check "$G"
```

Expected: `4`; no `unfilled placeholder` line; no `a file under home/ changed` line; `record: pass, verdict <met or unmet>`.

```bash
git add .agents/artifacts/plans/2026-10-11-issue-362-delegated-return-reasons.acceptance.md
git commit -m "docs(issue-362): acceptance record evidence for the delegated-return reasons"
```

- [ ] **Step 8: Report**

Report DONE when all three cases passed and Step 5 printed `verdict met`. Give `G`, `R`, the three verdict lines and the path of `$SCRATCH/grade`.

Report DONE_WITH_CONCERNS when any case failed. Both records are committed with the failure in them and 352's verdict stays `unmet`; that is the correct state, not something to repair here. In the report give `G`, `R`, the verdict lines, the path of `$SCRATCH/grade`, and for each failed clause whether one of the five graded files states the fact (file and sentence) or none does. Do not propose new skill wording as a done thing and do not regrade.
