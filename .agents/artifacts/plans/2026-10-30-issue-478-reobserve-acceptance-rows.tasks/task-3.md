# Task 3: ship-issue Phase 6 re-observes pending rows

Spec § ship-issue and Test seams item 3. Rests on D2, D5, D7, D8, D10 and D11. After this task, ship-issue's Phase 6 carries a **Re-observe pending rows** paragraph. The paragraph runs Task 1's `acceptance-record reobserve` between the required watch and the selection gate, publishes a changed record and reruns Phase 6. Phase 0's fixed-value sentence and Phase 8's close-or-hold step name the recomputed state. `SKILL.md` stays at 500 skill-lint reflowed lines.

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1's argv `acceptance-record reobserve --record <path> --head <sha> [--checks <path|->] [--row <ACn>]... [--ran <command>=<exit code>]...`, its `{acceptance_state, changed}` stdout and its exit 2.
- Produces: the two argv strings `gh pr checks <pr-num> --required --json name,bucket,link` and `acceptance-record reobserve --record <record-path> --head <HEAD_SHA> --checks <file>` in SKILL.md, after the required-watch fence and before Phase 7's merge fence.

**Invariants:**
- No ship-issue document other than `SKILL.md` changes (D7, D10).
- `SKILL.md` measures at most 500 skill-lint reflowed lines and grows by at most 1,608 bytes over `cb1d0ad5` (D10, D11). The five paragraph joins change no byte other than newline to space.
- The new `gh` span is one plain command, with no pipe, redirect or chain (`test_shell_example_contracts.py`).
- The pins are argv, never an English phrase (agent-helpers rule 6).

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, add these constants directly after `ADVISORY_CALL = ...`:

```python
# Issue 478: Phase 6 re-observes pending acceptance rows before any merge.
REQUIRED_CHECKS_CALL = "gh pr checks <pr-num> --required --json name,bucket,link"
REOBSERVE_CALL = ("acceptance-record reobserve --record <record-path> --head <HEAD_SHA>"
                  " --checks <file>")
PHASE_SEVEN_MERGE = "gh pr merge <pr-num> --repo <resolved-repository> --merge --subject"
```

In `SHIP_ISSUE_MACHINE_TEXT[SHIP_ISSUE]`, change the line `REQUIRED_WATCH, ALL_CHECKS_WATCH, ADVISORY_CALL,` to `REQUIRED_WATCH, ALL_CHECKS_WATCH, ADVISORY_CALL, REQUIRED_CHECKS_CALL, REOBSERVE_CALL,`. Insert this method directly before `test_phase_six_waits_on_required_checks_and_lists_advisory_states`:

```python
    def test_phase_six_reobserves_pending_rows_between_the_watch_and_the_merge(self):
        # Issue 478 AC3: the helper runs after the required watch and before Phase 7's merge.
        text = normalized(self.ship_issue)
        self.assertEqual(text.count(REOBSERVE_CALL), 1)
        self.assertLess(text.index(REQUIRED_WATCH), text.index(REQUIRED_CHECKS_CALL))
        self.assertLess(text.index(REQUIRED_CHECKS_CALL), text.index(REOBSERVE_CALL))
        self.assertLess(text.index(REOBSERVE_CALL), text.index(PHASE_SEVEN_MERGE))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 300 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | grep -E "^(Ran|OK|FAILED)"'`
Expected: `Ran 158 tests`, `FAILED (failures=3, skipped=1)`. The failures are the new ordering case, whose count assertion finds 0, and the machine-text case's subtests for the two new items on `SKILL.md`.

- [ ] **Step 3: Edit `SKILL.md`**

Make exactly these four text edits in `home/common/agent-skills/skills/ship-issue/SKILL.md`. Each `old` string occurs once.

1. Phase 0 (D2): replace `The value is then fixed for the run and ship grades nothing:` with `The value is then fixed for the run, save Phase 6's re-observation, and ship grades nothing:`.
2. Phase 6's docs-only sentence (D11): replace `every path ends in \`.md\` → skip straight to Phase 7; anything else` with `every path ends in \`.md\` → skip to Phase 7 unless rows need re-observing; anything else`.
3. Phase 6: after the paragraph that ends `Escalation, failing checks and advisory overflow: \`CI-MERGE.md\`.` and before `## Phase 7 — Merge`, insert one blank line and this paragraph as one line, then the existing blank line. It is 1,095 characters. Keep it at or under 1,100 (D11):

```markdown
**Re-observe pending rows.** Outside remainder mode, with a record and an `unmet` effective state, do this before the selection gate or a ledger-free merge. On GitHub, once the required watch exits `0`, save `gh pr checks <pr-num> --required --json name,bucket,link` to a scratch `<file>`; otherwise omit `--checks`. Pick each `unverified` `code` row whose measurements its `Observed` cell does not cite are only required checks or read-only commands, and run those commands once at `HEAD_SHA`. In the worktree, run `acceptance-record reobserve --record <record-path> --head <HEAD_SHA> --checks <file>` with `--row <ACn>` per picked row and `--ran "<command>=<exit code>"` per command; it applies sdd's `code` rule to what was observed and grades nothing. Its printed `acceptance_state` becomes the effective state; exit `2` keeps it. If `changed` is non-empty, commit the record alone (### Local commits), push it through REVIEW.md's steps 4–5, rewrite the PR body's `## Acceptance` per Phase 4 and rerun Phase 6, watch included. Only `human` rows and rows no agent can observe here still hold.
```

4. Phase 8 step 1 (D7): replace `1. Close or hold, per Phase 0's effective acceptance state.` with `1. Close or hold, per the effective acceptance state.`.

Then join five hard-wrapped paragraphs onto single lines (D11). Each runs from the line starting with the text below to the next blank line. Replace each newline inside it with one space and change nothing else:
- `For code review, select \`bindings.workflow.review.code\``
- `Guarded: the Phase-4 push, the Phase-4 PR create`
- `When the prompt carries a \`Lifecycle worker:\` line`
- `Run the push, the merge and a branch delete each as its own Bash call`
- `The \`## Acceptance\` section always appears.`

This script performs exactly those joins:

```python
from pathlib import Path
path = Path("home/common/agent-skills/skills/ship-issue/SKILL.md")
text = path.read_text(encoding="utf-8")
for first in ("For code review, select `bindings.workflow.review.code`",
              "Guarded: the Phase-4 push, the Phase-4 PR create",
              "When the prompt carries a `Lifecycle worker:` line",
              "Run the push, the merge and a branch delete each as its own Bash call",
              "The `## Acceptance` section always appears."):
    assert text.count(first) == 1, first
    start = text.index(first)
    end = text.index("\n\n", start)
    text = text[:start] + text[start:end].replace("\n", " ") + text[end:]
path.write_text(text, encoding="utf-8")
```

- [ ] **Step 4: Verify**

Run the Step 2 command.
Expected: `Ran 158 tests`, `OK (skipped=1)`.

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_instruction_load.py 2>&1 | grep -E "^(Ran|OK|FAILED)"'`
Expected: `OK`, possibly with skips. No failure.

Run (timeout 60 s): `bash -c 'set -e; F=home/common/agent-skills/skills/ship-issue/SKILL.md; PYTHONPATH="$PWD/python" python3 -c "import sys; from agent_tools.skill_lint import parse_frontmatter, reflowed_lines; n = reflowed_lines(parse_frontmatter(open(sys.argv[1], encoding=\"utf-8\").read())[1]); print(n); sys.exit(n > 500)" "$F"; test $(( $(wc -c < "$F") - $(git show cb1d0ad5:"$F" | wc -c) )) -le 1608; test -z "$(git diff --name-only cb1d0ad5 -- home/common/agent-skills/skills/ship-issue | grep -v "/SKILL.md$")"; if grep -n "Phase 0.s effective acceptance state\|fixed for the run and ship grades nothing" "$F"; then exit 1; fi'`
Expected: prints `500` and exits 0. At the start commit it prints `500` and exits 1, printing the Phase 0 sentence and Phase 8 step 1.

Run the Budget (Global Constraints).
Expected: `check: pass`. A `lint: L2 … over 500` line means the paragraph outgrew D11's room.

Run the Build (Global Constraints).
Expected: no error line. The skill documents are read into the home configuration.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(ship-issue): re-observe pending acceptance rows before close or hold (issue 478)" -m "<trailers>"
```
