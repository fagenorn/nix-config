# Task 2: Route the delegated return in the skill text

Issue: https://github.com/fagenorn/nix-config/issues/352. Spec: `.agents/artifacts/specs/2026-10-10-issue-352-delegated-ship-routing-design.md` (sections `### The delegate prompt names the return` through `### The inline route`; ledger rows D1–D3, D6, D7, D9, D10).

Background for a reader with no context. `from-issue` is a skill: Markdown instructions an agent follows to take one issue from investigation to a merged PR. An *owner* is the agent running it. At a phase boundary the owner calls `workflow-state progress`, and one possible answer, `delegate`, tells it to hand the remaining phases to a fresh owner. Under an orchestrator the chain is orchestrator → issue owner → delegated owner. Today the delegated owner launches the ship owner itself; that ship owner is one level too deep to launch reviewers, so the issue ships inline in a huge context. After this task the delegated owner stops after Phase 6 (implementation) and returns the validated *ship handoff*, and the issue owner launches the ship owner.

All skill documents an agent profile loads are measured in bytes by `agent_tools.instruction_load` against fixed ceilings, and this change has 11 bytes to spare. So the text below is exact: apply each edit byte for byte, and do not reflow, re-wrap or "improve" a sentence. Paths in this task are relative to `home/common/agent-skills/`; the four skill files are under `skills/from-issue/`.

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/agent-skills/skills/from-issue/delegated-owner.md`
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md`
- Modify: `home/common/agent-skills/model-matrix.json` (one `call` string)
- Modify: `home/common/agent-skills/instruction-load.json` (one `note` string)
- Modify: `home/common/agent-skills/README.md` (one new subsection)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: the module constant `DELEGATED_RETURN_LINE = "Delegated owner: return the ship handoff"` in the test file (Task 3 reuses it by name); the heading `## Generic delegate` in `delegated-owner.md`; the final skill text that Task 3's evals are graded against.

**Invariants:**
- The closed line is spelled `Delegated owner: return the ship handoff` wherever a from-issue `.md` file has the text `Delegated owner:`, and only `SKILL.md` and `delegated-owner.md` carry it.
- `delegated-owner.md`'s `## Generic delegate` section names `release-worker` and `--boundary ship-handoff`, and names neither `workflow-state finish` nor `--boundary ship-summary`. It also names no sibling reference file (`acquire-dispatcher.md`, `ship-handoff.md`): skill-lint rule L4b refuses that.
- Inside `SKILL.md`'s `delegate` action, `--boundary workflow-response` comes before `--boundary ship-handoff`, which comes before `workflow-state progress`.
- No `<!-- agent-dispatch: … -->` marker line changes. In `model-matrix.json` only the one `call` string changes; its `id`, `role`, `model` and `effort` do not.
- In `instruction-load.json` only the `implementation-owner` profile's `note` changes: no ceiling, member list or `unread` reason.
- Byte deltas against the merge base: `SKILL.md` +394, `AUTO.md` −351, `delegated-owner.md` +592, `ship-handoff.md` −124.
- Every test that passes today in the six test files of Step 6 still passes; an existing English-phrase pin that a cut breaks is deleted, never rewritten (none is expected: the prototype broke none).

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, add this constant on the line after `CAPABILITY_GAP_LINE = "capability_gap: agent_dispatch"`:

```python
DELEGATED_RETURN_LINE = "Delegated owner: return the ship handoff"
```

Then add these three methods to `class WorkflowSkillContractsTest`, immediately before `def test_from_issue_phase_seven_ships_inline_on_the_dispatch_gap(self):`. They use the class's existing `assert_ordered` and `section` helpers and the module's `FROM_ISSUE_DIR` and `DELEGATED_OWNER` paths.

```python
    def test_delegated_return_line_is_spelled_identically_everywhere(self):
        # #352 D6: one closed prompt line, matched byte for byte.
        pattern = r"Delegated owner:[^`\n]*"
        carriers = set()
        for path in sorted(FROM_ISSUE_DIR.glob("*.md")):
            spellings = set(re.findall(pattern, path.read_text(encoding="utf-8")))
            with self.subTest(document=path.name):
                self.assertLessEqual(spellings, {DELEGATED_RETURN_LINE})
            if spellings:
                carriers.add(path.name)
        self.assertEqual(carriers, {"SKILL.md", "delegated-owner.md"})

    def test_generic_delegated_owner_returns_the_handoff_without_a_terminal_write(self):
        # #352 D1-D3: argv and boundary names only (agent-helpers rule 6).
        delegated = DELEGATED_OWNER.read_text(encoding="utf-8")
        self.assertEqual(delegated.count("## Generic delegate"), 1)
        generic = delegated.split("## Generic delegate", 1)[1]
        self.assert_ordered(generic, f"`{DELEGATED_RETURN_LINE}`", "release-worker",
                            "--boundary ship-handoff")
        for forbidden in ("workflow-state finish", "--boundary ship-summary"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, generic)

    def test_delegate_action_checks_the_return_before_it_ships(self):
        # #352 D2: the delegator tries the terminal reply before the handoff.
        action = self.section(self.from_issue, "4. **`delegate`**",
                              "## Terminal return procedure")
        self.assert_ordered(
            action, "id=from-issue-phase-delegate", f"`{DELEGATED_RETURN_LINE}`",
            "--boundary workflow-response", "--boundary ship-handoff",
            "workflow-state progress", "id=from-issue-ledger-remainder")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_delegated_return_line -k test_generic_delegated_owner_returns -k test_delegate_action_checks 2>&1 | grep -E "^(FAIL|Ran|FAILED|OK)"` (timeout 1800 s)
Expected: `Ran 3 tests`, `FAILED (failures=3)`: the carrier set is empty, `## Generic delegate` occurs 0 times, and the `delegate` action misses the anchor `` `Delegated owner: return the ship handoff` ``.

- [ ] **Step 3: Apply the ten text edits**

What the new text makes an owner do, so you can check the result reads correctly (do not add any of this prose to the files):
- Edit 3 is the delegating owner. It puts the closed line in the fresh owner's prompt, then sorts that owner's return into three ordered alternatives. (a) is every return that means the delegated owner already ended or suspended the launch itself: relay and stop. (b) is the Phase-6 result: the delegating owner records Phase 6 and runs Phase 7 with the returned handoff. (c) is a contract failure. Spec `### The delegating owner` lists four cases; its cases 1 and 2 have the same outcome and are (a) here (D10).
- Edit 4 says what a `delegate` answer means at the Phase-6 gate off the direct-autonomous route: the ship-owner dispatch, not another issue owner.
- Edit 9 is the delegated owner: run to the end of Phase 6, treat `delegate` as `continue`, build and validate the handoff, release its workers, return the handoff, and do nothing that belongs to Phase 7.
- Edits 5, 6 and 7 are cuts, and Edits 2 and 8 swap a sentence for a shorter one: together they pay for the new text (D7, D9). Edit 6 keeps the name `REVIEW-CONTRACT.md` in `AUTO.md` because the instruction-load model requires the planning owner's prompt to name it. Edit 10 mirrors Edit 5, because `model-matrix.json` holds a copy of that whole `Agent(...)` line.

**Edit 1** — `SKILL.md`, the `delegated-owner.md` entry of `## Files beside this one` (+13 bytes).

Replace exactly this text, which occurs once:

````text
- **`delegated-owner.md`** — the rollover's delegated owner, Phases 6–7; read it first, before any resume pack.
````

with:

````text
- **`delegated-owner.md`** — the rollover's or the `delegate` action's delegated owner; read it first, before any resume pack.
````

**Edit 2** — `SKILL.md`, the last sentence of the **Self-reap.** paragraph (-35 bytes).

Replace exactly this text, which occurs once:

````text
A delegating owner does not reap: the fresh delegated owner reaps the adopted launch at its own exit.
````

with:

````text
After a `delegate`, the owner whose exit ends the launch reaps it.
````

**Edit 3** — `SKILL.md`, the `delegate` action gains one line (+567 bytes).

Directly after the line that ends with `put its stdout in the prompt as a `Resume pack` paragraph.` and before the line that begins `   Exception — **ledger-only remainder**`, insert this one line. It begins with three spaces, like its neighbours, and contains the character `…` (U+2026) once:

````text
   Off the direct-autonomous route the prompt also carries the line `Delegated owner: return the ship handoff`. Match its return in order: (a) only the re-entry line or a `Suspended (…)` line, or bytes valid at `--boundary workflow-response`: relay it, write nothing and stop, with no reap; (b) bytes valid at `--boundary ship-handoff`, `state: complete`, with this owner's identity: call `workflow-state progress` for Phase 6, then run Phase 7 with those bytes unchanged as the handoff; (c) anything else: a contract failure through the terminal return procedure.
````

**Edit 4** — `SKILL.md`, the paragraph that follows the `delegate` action's bookkeeper lines (+0 bytes).

Replace exactly this text, which occurs once:

````text
`delegated-owner.md` its Phase-6 and Phase-7 `delegate` gates; every other acquisition mode keeps the generic action semantics.
````

with:

````text
`delegated-owner.md` its Phase-6 and Phase-7 `delegate` gates. Off it, a Phase-6 `delegate` is the Phase-7 ship-owner dispatch.
````

**Edit 5** — `SKILL.md`, `## Phase 7`, the tail of the `Agent(...)` line (-151 bytes).

Delete exactly this text, which occurs once. The deleted text begins with one space, so the sentence before it keeps its full stop and nothing else on the line changes.

````text
 By now this conversation carries every artifact of the flow; a fresh ~10k subagent returns one summary instead of ~100 turns over a 200–300k prefix.
````

**Edit 6** — `AUTO.md`, the first two paragraphs of `## Other Phase 5–7 routes` become one (-351 bytes).

Replace exactly this text, which occurs once:

````text
A direct autonomous controller hands Phases 6–7 to a fresh owner at the Phase-5 rollover, mechanical-only runs included; every other route keeps the behavior below, and its mechanical-only ordering and ownership are unchanged.

Dispatcher-owned autonomous, explicitly durable interactive, and ledger-free
interactive owners retain their existing behavior: Phase 5 dispatches the
reviewer (or `codex-collaboration`) with `REVIEW-CONTRACT.md`'s path, Phase 6
runs `sdd`, and Phase 7 dispatches `ship-issue` with the appropriate handoff.
````

with:

````text
A direct autonomous controller hands Phases 6–7 to a fresh owner at the Phase-5 rollover, mechanical-only runs included. Elsewhere Phase 5's reviewer gets `REVIEW-CONTRACT.md`'s path.
````

**Edit 7** — `ship-handoff.md`, the line under the title, with the blank line that follows it (-36 bytes).

Delete exactly this text, which occurs once. Delete the line and the one blank line after it, so the title is followed by one blank line and then `## Contents`.

````text
Loaded from `SKILL.md` at Phase 7.
````

**Edit 8** — `ship-handoff.md`, the first sentence of `## Dispatch-gap fallback` (-88 bytes).

Replace exactly this text, which occurs once:

````text
It is the one exception to shipping through a fresh ship owner, and the one allowed departure from a rollover Phase-6 `delegate`.
````

with:

````text
A generic delegated owner never takes it.
````

**Edit 9** — `delegated-owner.md`, a new section at the end of the file (+592 bytes).

The file ends with the paragraph that begins `For mechanical-only direct autonomous work`. After it, append one blank line and then these three lines (a heading, a blank line, one paragraph), ending the file with a single newline:

````text
## Generic delegate

The prompt line `Delegated owner: return the ship handoff` selects this section alone. Adopt the dispatcher envelope and run the remaining phases through Phase 6, taking a `delegate` action as `continue`. After Phase 6's gates pass, call no `progress` and start no Phase 7: build the handoff as Phase 7's ship-owner prompt says, release every worker you registered (`release-worker --event returned`), and return only the stdout of `validate-report --boundary ship-handoff`, with no reap. Every other exit runs, reap included, as `SKILL.md` says; return what it prints.
````

**Edit 10** — `model-matrix.json`, the `call` string of the `from-issue-ship-owner` dispatch site (-151 bytes).

Delete exactly this text, which occurs once. The deleted text begins with one space, so the sentence before it keeps its full stop and nothing else on the line changes.

````text
 By now this conversation carries every artifact of the flow; a fresh ~10k subagent returns one summary instead of ~100 turns over a 200–300k prefix.
````

After Edit 10 the `call` value reads `Agent(subagent_type=\"general-purpose\", model=\"opus\", effort=\"high\") launches `ship-issue` as a fresh ship owner, not inline via `Skill`.` and the JSON still parses.

- [ ] **Step 4: Check the byte deltas**

Run:

```bash
base="$(git merge-base origin/main HEAD)"
for f in SKILL AUTO delegated-owner ship-handoff; do
  p="home/common/agent-skills/skills/from-issue/$f.md"
  echo "$f $(( $(wc -c < "$p") - $(git show "$base:$p" | wc -c) ))"
done
python3 -c "import json;json.load(open('home/common/agent-skills/model-matrix.json'))" && echo matrix-parses
```

Expected: `SKILL 394`, `AUTO -351`, `delegated-owner 592`, `ship-handoff -124`, `matrix-parses`. A different number means an edit was not applied byte for byte (a re-wrapped line, a straight `...` instead of `…`, a lost or extra space or newline): fix the edit, do not adjust another sentence to compensate.

- [ ] **Step 5: Update the profile note and the README**

In `home/common/agent-skills/instruction-load.json`, the `note` of the profile whose `id` is `implementation-owner` ends with the sentence below, which occurs once in the file:

````text
the other acquisition routes and the rollover are unread."
````

Replace it with (same line, still one JSON string):

````text
the other acquisition routes and the rollover are unread. From #352 a generic `delegate` owner runs under this profile too: it takes the dispatcher envelope, stops after Phase 6 and returns the ship handoff, so it never loads the ship-issue members (#352 D1)."
````

Change nothing else in that file. The gate permits a `note` change without the raise label and refuses any other change. The orchestrated owner profile's `unread` reason for `from-issue/delegated-owner.md` stays as it is (D10).

In `home/common/agent-skills/README.md`, the last subsection of `## Lifecycle helpers` is `### Resume pack`, and the file ends with its paragraph (`… decides the task to resume (#265).`). Append a blank line and this subsection at the end of the file. The README is outside the measured corpus, so this is the long form of what the skill text says tersely (D10); rewrite a sentence here if the implemented skill text ends up differing from it.

````text
### Delegated ship return

Off the direct-autonomous route, an owner whose phase gate answers `delegate` puts the closed line `Delegated owner: return the ship handoff` in the fresh owner's prompt. That owner runs through Phase 6 under the same `action_id` (a `delegate` action creates no attempt and no launch) and, instead of shipping, returns the canonical stdout of `artifact-budget validate-report --boundary ship-handoff`. The delegating owner accepts it only when its identity equals its own (`ledger_repo_root`, `run_id`, `owner`, `issue_number` and `custody.action_id` in `ship-handoff/v2`; `issue_number`, `branch` and `worktree_path` in the legacy shape), makes the Phase-6 `workflow-state progress` call, and registers and launches the ship owner as the launch's next worker. Under orchestrate-issues the ship owner therefore sits two levels below the orchestrator, where it can still launch its reviewers; launched by the delegated owner it sat three levels below and shipped inline through the dispatch-gap fallback. The ledger records neither the delegation nor a worker's role. Whichever of the two owners makes the exit that ends the launch reaps it: the delegated owner on its own `handoff`, suspension or terminal failure, the delegating owner otherwise. The direct-autonomous rollover is unchanged (#352).
````

- [ ] **Step 6: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_delegated_return_line -k test_generic_delegated_owner_returns -k test_delegate_action_checks 2>&1 | tail -3` (timeout 1800 s)
Expected: `Ran 3 tests`, `OK`.

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_shell_example_contracts.py 2>&1 | tail -3` (timeout 1800 s)
Expected: `OK` (some skipped). These are the suites that read the edited files: the skill contracts, skill-lint, the instruction-load model, the dispatch-region clauses, the model-matrix mirror and the shell examples. A failure naming `matrix.dispatch_sites` means Edit 5 and Edit 10 disagree.

Run: `just agent-instruction-budget` (timeout 600 s)
Expected: exactly `check: pass`. A `ceiling:` line means the text is over a ceiling: recheck Step 4, never raise a ceiling. A `raise:` line means `instruction-load.json` changed beyond the note, or a gate file changed: revert that. A `lint: L4b` line means a reference file names a sibling file: Edit 9's text names none.

Run: `git diff --stat "$(git merge-base origin/main HEAD)" -- home/common/agent-skills/scripts .github python/agent_tools | wc -l`
Expected: `0`.

- [ ] **Step 7: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/agent-skills/skills/from-issue/delegated-owner.md home/common/agent-skills/skills/from-issue/ship-handoff.md home/common/agent-skills/model-matrix.json home/common/agent-skills/instruction-load.json home/common/agent-skills/README.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(from-issue): a generic delegated owner returns the ship handoff (#352)"
```
