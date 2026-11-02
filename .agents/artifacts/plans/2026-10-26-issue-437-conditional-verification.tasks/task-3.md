# Task 3: sdd and ship run the plan's `run` ids and record each skip

Spec § Consumers and § Other readers of `workflow.verification`, per D7, D8, D9, D13 and D15. sdd's Final verification and ship-issue's Phase 2 call `verified-tree check` with no ids, run exactly its `run` ids, and record each skipped id with its reason: an SDD ledger suffix and a PR-body Summary line. Ship's `check` exit 2 still runs every declared id. The wording below is fixed and was measured against the base instruction budget.

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/final-review.md` (`## Final verification`: intro paragraph and steps 1–3)
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md` (`## Project bindings (resolve first)` paragraph; `## Phase 2 — Verify locally` steps 1 and 3)
- Modify: `home/common/agent-skills/skills/ship-issue/evals/evals.json` (case 5, assert "local verification was recorded for the worktree's tree")
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (`SDD_MACHINE_TEXT`, `SHIP_ISSUE_MACHINE_TEXT`)

**Interfaces:**
- Consumes: Task 2's CLI. `verified-tree check` prints `{run, skipped, status, tree}` with `skipped` entries `{id, reason}`, and `verified-tree record --tree <id>` takes no ids.
- Produces: the SDD ledger line `Final verification: passed (head <full sha>, tree <tree id>)` with a `; skipped <id>: <reason>` suffix per skipped entry, and the PR-body Summary line `verification skipped: <id> (<reason>)`. Neither line is pinned: they are English, per agent-helpers rule 6.

**Invariants:**
- Each machine-text table pins the backtick-delimited `` `verified-tree check` `` in place of `verified-tree check --verification <id>`. The `verified-tree record --tree <the checked tree>` pin is unchanged (D15). With the old skill text the new pin fails, because the old text closes the backtick only after `--verification <id>`.
- No skill document under `home/common/agent-skills/skills/` and no line of `test_workflow_skill_contracts.py` contains `--verification` afterwards.
- `sdd/final-review.md` shrinks (−16 bytes measured), and `ship-issue/SKILL.md` grows by +137 bytes measured. `just agent-instruction-budget` passes with no label, and `home/common/agent-skills/instruction-load.json` is unchanged (D7, D15).
- Unchanged: the `Declared verification:` line in final-review's conformance dispatch (D8), Final verification step 4 (repair once), the capability routing paragraph, ship's flow table line `2. Verify locally → verified-tree check; run + record unless verified`, Phase 2 step 2 (`verification reused: tree <id>`), and the verbatim pinned clause ``only sanctioned exception is `workflow-state build-delivery`, which performs its own sealed, read-only resolution`` (`test_build_delivery_callers_name_the_sanctioned_resolution_exception`).

- [ ] **Step 1: Write the failing test**

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, the two tables each hold this pair once, in `SDD_MACHINE_TEXT[SDD_DIR / "final-review.md"]` and `SHIP_ISSUE_MACHINE_TEXT[SHIP_ISSUE]`:

```python
        "verified-tree check --verification <id>",
        "verified-tree record --tree <the checked tree>",
```

Replace both occurrences with:

```python
        "`verified-tree check`",
        "verified-tree record --tree <the checked tree>",
```

- [ ] **Step 2: Run the test and watch it fail**

Run the focused form on `home/common/agent-skills/tests/test_workflow_skill_contracts.py -k machine_text`.
Expected: `FAILED (failures=2)`: `test_sdd_documents_carry_their_machine_text` (path `final-review.md`) and `test_ship_issue_documents_carry_their_machine_text` (path `SKILL.md`), each on the item `` `verified-tree check` ``.

- [ ] **Step 3: Write the minimal implementation**

Apply each replacement exactly, and confirm each old text occurs once first.

`home/common/agent-skills/skills/sdd/final-review.md`, the intro of `## Final verification`. Replace

```markdown
you choose the terminal state. It is the plan's one run of the full declared
verification: every retained `bindings.workflow.verification` id, in order, each
dereferenced through `bindings.commands`.
```

with

```markdown
you choose the terminal state. It is the plan's one run of the declared
verification: each id `verified-tree check` lists under `run`, in order,
dereferenced through `bindings.commands`; an id under `skipped` is not run.
```

The same file, steps 1–3. Replace

```markdown
1. **Check.** In the worktree, run `verified-tree check --verification <id>`,
   repeating `--verification` for each id, and keep the `tree` it prints.
   Exit 0 with `verified` means this exact tree already passed these commands:
   skip step 2.
2. **Run and record.** Otherwise run every declared verification command once,
   in the foreground with an explicit timeout above its duration, its output in
   a log on disk and only the tail read back. When every command passes, run
   `verified-tree record --tree <the checked tree>` with the same
   `--verification` ids.
3. **Ledger.** Append
   `Final verification: passed (head <full sha>, tree <tree id>)` to the SDD
   ledger.
```

with

```markdown
1. **Check.** In the worktree, run `verified-tree check` and keep the `tree`,
   `run` and `skipped` it prints. Exit 0 with `verified` means this exact tree
   already passed the `run` commands: skip step 2.
2. **Run and record.** Otherwise run each `run` command once, in the
   foreground with an explicit timeout above its duration, its output in a log
   on disk and only the tail read back. When every command passes, run
   `verified-tree record --tree <the checked tree>`.
3. **Ledger.** Append
   `Final verification: passed (head <full sha>, tree <tree id>)` to the SDD
   ledger, suffixed `; skipped <id>: <reason>` per `skipped` entry.
```

`home/common/agent-skills/skills/ship-issue/SKILL.md`. Each old text below is a substring of one line.

the Project-bindings paragraph (line 10). Replace

```markdown
which performs its own sealed, read-only resolution when it builds a delivery object; this skill
```

with

```markdown
which performs its own sealed, read-only resolution when it builds a delivery object (and `verified-tree`, which reads `bindings.workflow.verification` and its conditions itself); this skill
```
Phase 2 step 1. Replace

```markdown
1. **Check.** Run `verified-tree check --verification <id>` in the worktree, repeating `--verification` for every id in retained `bindings.workflow.verification`, in order; keep the `tree` it prints.
```

with

```markdown
1. **Check.** Run `verified-tree check` in the worktree; keep the `tree`, `run` and `skipped` it prints. On Phase 2's own run, note each `skipped` entry as `verification skipped: <id> (<reason>)` in the PR body's Summary.
```
Phase 2 step 3. Replace

```markdown
3. **Otherwise run and record.** Run every id's `bindings.commands` argv and cwd; when all pass, run `verified-tree record --tree <the checked tree>` with the same `--verification` ids. `record` exit 3 `tree_changed` is a failing verification; `check` exit 2 means run anyway and leave the pass unrecorded;
```

with

```markdown
3. **Otherwise run and record.** Run each `run` id's `bindings.commands` argv and cwd; when all pass, run `verified-tree record --tree <the checked tree>`. `record` exit 3 `tree_changed` is a failing verification; `check` exit 2 means run every retained `bindings.workflow.verification` id anyway and leave the pass unrecorded;
```

`home/common/agent-skills/skills/ship-issue/evals/evals.json`, the `shell` string of case 5's first assert. It is JSON-escaped in the file, as shown. Replace

```
st=$(cd \"$PRE_WT\" && verified-tree check --verification test 2>/dev/null | jq -r '.status' 2>/dev/null); [ \"$st\" = verified ] || fail \"verified-tree check --verification test answers '${st:-an error}' in $PRE_WT, not verified\"
```

with

```
st=$(cd \"$PRE_WT\" && verified-tree check 2>/dev/null | jq -r '.status' 2>/dev/null); [ \"$st\" = verified ] || fail \"verified-tree check answers '${st:-an error}' in $PRE_WT, not verified\"
```

- [ ] **Step 4: Verify**

Run the focused form (timeout 900 s; about 15 s) on `home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_eval_cases.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_skill_lint.py`.
Expected: `OK` (`skipped` allowed).

Run `just agent-instruction-budget` (timeout 300 s).
Expected: `check: pass`, with no `--raise-label`.

Run (timeout 60 s):

```bash
set -e
if git grep -n -e '--verification' -- home/common/agent-skills/skills home/common/agent-skills/tests/test_workflow_skill_contracts.py; then exit 1; fi
python3 -c 'import json,sys; json.load(open(sys.argv[1]))' home/common/agent-skills/skills/ship-issue/evals/evals.json
git diff --quiet ca6ba1ae2b37e56c1361a8656c29af1f39b89348 -- home/common/agent-skills/instruction-load.json home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md .agents/project.json
```

Expected: every command exits 0. At base the first check fails: it lists the `--verification` lines in `final-review.md`, `ship-issue/SKILL.md`, `evals.json` and the two test tables.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd/final-review.md home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/evals/evals.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit … -- -m "feat(skills): run the verified-tree plan and record skipped ids (issue 437)" -m "<session trailers>"
```

Verify: `git status --short -- home` prints nothing.
