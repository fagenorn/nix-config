# Task 7: Skill argv, contract prose and the final gate

Owners name their launch, the two READMEs state the contract, and the package's declared verification runs once. Read the root's Global Constraints first. Decisions: D9, D13, D20, and for prose every row the sentences describe.

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Modify: `python/README.md` (section `## Transaction core`)
- Modify: `home/common/agent-skills/README.md` (section `## Lifecycle helpers`)

**Interfaces:**
- Consumes: the CLI of Tasks 3 to 5 (`--action-id` on `progress`, `suspend` and `finish`; schema 9; the fencing refusals).
- Produces: skill text an owner follows; no code.

**Invariants:**
- `from-issue/SKILL.md` sends `--action-id <action_id>` on `progress` and `suspend`. No other skill file changes.
- No instruction ceiling is raised and `instruction-load.json` is not edited (D9). The two edits add 51 bytes; the tightest profile, `from-issue-controller`, had 234 bytes of headroom at the base.
- Skill-text tests pin argv only (`docs/standards/agent-helpers.md` rule 6): the two changed pins are the suspend verb line.
- Root `CLAUDE.md` is not edited. README prose states behaviour the implemented code has; nothing forecasts https://github.com/fagenorn/nix-config/issues/339 beyond naming what it owns.

- [ ] **Step 1: Change the two pins and watch them fail**

In `test_workflow_skill_contracts.py`, `test_suspension_procedure_pins_verb_line_and_distinction` and `test_suspension_validates_its_reply_and_replays_a_stall_bound_terminal` each pin the string `"--issue <n> --attempt <k> --blocked-on <value>"` (the second with the pipe that follows). In both, it becomes `"--issue <n> --attempt <k> --action-id <action_id> --blocked-on <value>"`.

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k suspension`
Expected: those 2 tests fail: the skill line has no `--action-id`.

- [ ] **Step 2: Edit the skill**

In `home/common/agent-skills/skills/from-issue/SKILL.md`, two exact replacements, each of a string that occurs once:

- `call `workflow-state progress` with the completed phase,` → `call `workflow-state progress` with `--action-id <action_id>`, the completed phase,`
- `--issue <n> --attempt <k> --blocked-on <value> |` → `--issue <n> --attempt <k> --action-id <action_id> --blocked-on <value> |`

- [ ] **Step 3: Verify the skill edit**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_skill_lint.py`
Expected: `OK`.

Run: `just agent-instruction-budget`
Expected: `check: pass`. If a ceiling is exceeded, condense text beside the edit in the same file until it passes; never raise a ceiling.

- [ ] **Step 4: Write the contract prose**

Write each sentence from the implemented code, in the surrounding style.

`python/README.md`, `## Transaction core`: say that `workflow-state` now also holds attempt custody in the core. Content points: one custody transaction per implementation attempt (creation key, subject schema `attempt-custody/v1`, authority class, the single `attempt-worktree:<path>` concurrency key); a launch is a custody span whose executor is the action id, so the key's epoch is the launch generation; the lease's validity is the attempt's budget window and `renew(custody, ttl_ms=…)` is the one in-place renewal; `agent_tools.attempt_custody` holds the pure rules and the settle planner, `agent_tools.attempt_store` applies them under the store lock; the settle step runs inside `commit_state`, core first and seal last; a non-`merged` verdict seals `abandoned` with a receipt listing stops and owner results, while a `merged` attempt stays unsealed until https://github.com/fagenorn/nix-config/issues/339 ports delivery proof. Link the design spec.

`home/common/agent-skills/README.md`, `## Lifecycle helpers`: add a subsection `### Attempt custody and fencing` after `### Run identity and migrate`, and correct that subsection's schema sentences for schema 9. Content points: schema 9 and how a schema-8 ledger binds (next locked write, or `migrate --apply` after the dry run; no reverse migration; an older helper refuses); which transports are owner transports and that `progress`, `suspend` and the legacy `finish` take `--action-id`, with what an attempt-keyed call means; the four fencing reasons, when each is printed and the remedy; the misbinding rule and its remedy; what happens to a late `finish` (adopted over a reaper's stop, or refused and retained); suspension as a parking with its reason; that remainders and delivery postconditions are unchanged.

- [ ] **Step 5: Run the final gate**

Run each from the worktree root, timeout 3600 s: `just build`; `just agent-workflow-tests`; `just agent-installed-skill-tests`; `just agent-instruction-budget`.
Expected: each exits 0; `agent-workflow-tests` ends in `OK` with no failure or error, `agent-instruction-budget` prints `check: pass`. The task is incomplete if any pre-existing test was edited outside D22's declared changes: confirm with `git diff --stat 5bd914e199f3e57217780596beefe69838f4efd4..HEAD -- home/common/agent-skills/tests tests` and read every hunk in a file other than the two new ones.

Run: `for f in $(git diff --name-only 5bd914e199f3e57217780596beefe69838f4efd4..HEAD -- home python tests justfile); do echo "$(git diff -U10 5bd914e199f3e57217780596beefe69838f4efd4..HEAD -- "$f" | wc -c) $f"; done | sort -n | tail -3`
Expected: the largest number is at most 60000.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py python/README.md home/common/agent-skills/README.md
launch-commit … -- -m "docs(attempt-custody): owners name their launch; custody and fencing contract (#338)"
```
