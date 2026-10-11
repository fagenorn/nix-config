# Task 7: Skill argv, contract prose and the final gate

The orchestrator's bootstrap text stops telling the dispatcher to look through `.superpowers/workflows/` and calls `init-run --issue-set`; the two READMEs state the contracts Tasks 1 to 6 built; and the whole declared verification runs once on the final head. Decisions: D7, D11, D16, D22.

**Files:**
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md` (`## 2. Bootstrap and observe`: its first paragraph and code block)
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (`ORCHESTRATE_MACHINE_TEXT`)
- Modify: `python/README.md` (`## Transaction core`)
- Modify: `home/common/agent-skills/README.md` (`## Lifecycle helpers`: `### workflow-state build-delivery`, `### Host admission`, `### Run identity and migrate`, `### Attempt custody and fencing`)

**Interfaces:**
- Consumes: `workflow-state init-run --issue-set <n>-<n>…` (Task 5) and the behaviour of Tasks 2 to 6 as built.
- Produces: the skill's argv line `workflow-state init-run --repo-root <ledger_repo_root> --issue-set <issues> | artifact-budget validate-report --boundary workflow-response --input -`; no code.

**Invariants:**
- The skill's bootstrap block has exactly two `init-run` lines: the `--issue-set` one above and the unchanged `--run-id` one. The `--creation-key orchestrate-issues:<unix-ts>:` argv and the sentence that names `.superpowers/workflows/` as a place to look for a run are gone. No other section of the skill changes, and the file does not grow.
- `ORCHESTRATE_MACHINE_TEXT` pins the new argv prefix where it pinned the old one, and no English sentence (agent-helpers rule 6).
- Root `CLAUDE.md` gains nothing. `from-issue`'s durable acquisition keeps `--creation-key`.
- README sentences describe the code at this task's head: read the implemented functions before writing each one.

- [ ] **Step 1: Change the pin and watch it fail**

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, replace the two-line `ORCHESTRATE_MACHINE_TEXT` entry

```python
        "workflow-state init-run --repo-root <ledger_repo_root> --creation-key "
        "orchestrate-issues:<unix-ts>:",
```

with

```python
        "workflow-state init-run --repo-root <ledger_repo_root> --issue-set <issues>",
```

Run: `PYTEST T/test_workflow_skill_contracts.py`
Expected: FAIL — the orchestrate-issues skill does not carry the `--issue-set` argv.

- [ ] **Step 2: Edit the skill**

Replace the paragraph that begins "Before `init-run`, reuse the id of a run in" and the first line of the code block after it. Content points, in at most the bytes the paragraph has now: `init-run --issue-set` returns the run that covers the same issue set with a non-final attempt or a missing outcome, or mints one; `<issues>` is the issue numbers joined by `-`, in any order; take `run_id` from the validated bootstrap; call it at run start or after a restart; a run started with a creation key is re-entered with `--run-id`. The code block's first line becomes the argv line under Interfaces.

- [ ] **Step 3: Write the README contracts**

Content points, a sentence or two each:

- `python/README.md` § Transaction core, after the schema-9 paragraph: from schema 10 the control plane decides from the store. Name the delivery transaction (key, subject, authority class, concurrency key, proof plan, journal), remainder custody (key, subject), the claim entry, the `capacity_released` transition, the `succeeded` seals, the supplements, and which of the four modules is pure. Replace the sentence that leaves a `merged` attempt unsealed until issue 339 with what is true now, the contractless case included. Link the design spec.
- § `workflow-state build-delivery`: the installing ledger is found through the delivery transactions of the contract's digest, not by listing `workflows`; a ledger not yet bound to schema 10 is not found until its next write or `migrate --apply`.
- § Host admission: a held owner claim is carried by its launch's custody span and released by the span closing; control counts occupied slots and reads the `host_capacity` gate from the store.
- § Run identity and migrate: `init-run --issue-set` and its reuse rule; `direct-owner` finds runs by index and refuses an unbound legacy `direct-<issue>-<sequence>` ledger, with the exact text; schema 10 and the 9 → 10 bind; activation (`workflow-state migrate --repo-root <root>`, then `--apply`, per ledger root); an orchestration started before the cutover is re-entered with `init-run --run-id`; the package-2 helper refuses schema 10.
- § Attempt custody and fencing: remainders have custody; an `owner_unavailable` release closes the span in that write; a delivered issue's records hold no span and seal `succeeded` after the delivery receipt; late objects become supplements.

- [ ] **Step 4: Focused checks**

Run: `PYTEST T/test_workflow_skill_contracts.py T/test_shell_example_contracts.py T/test_skill_lint.py T/test_instruction_load.py`
Expected: `OK`.

Run: `if grep -n "unix-ts\|superpowers/workflows" home/common/claude-code/skills/orchestrate-issues/SKILL.md; then exit 1; fi`
Expected: exit 0, no output.

Run: `test "$(wc -c < home/common/claude-code/skills/orchestrate-issues/SKILL.md)" -le "$(git show BASE:home/common/claude-code/skills/orchestrate-issues/SKILL.md | wc -c)"`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add home python/README.md
launch-commit … -- -m "docs(agent-skills): init-run --issue-set in the orchestrator and the cutover's contracts (#339)"
```

- [ ] **Step 6: Final gate on the final head**

Run each from the worktree root, timeout 3600 s; expected exit 0 and, for the two test recipes, `OK` with no failure and no error: `just build`; `just agent-workflow-tests`; `just agent-installed-skill-tests`; `just agent-instruction-budget` (no `--raise-label`). A failing command is reported with its failing lines; nothing is skipped and no assertion is weakened.

Then three review facts:

- `git diff --stat BASE -- 'python/agent_tools/transaction_*.py'` and every path of the root's not-edited list — expected: empty output.
- `git diff --name-only BASE -- T/ tests | sort` — expected: four new test files and only these pre-existing ones: `test_workflow_state.py`, `test_attempt_migration.py`, `test_attempt_custody.py`, `test_delivery_workflow.py`, `test_host_admission.py`, `test_workflow_skill_contracts.py`, `tests/test_attempt_custody.py`, `tests/test_attempt_identity.py`. The task report lists each changed pre-existing test with its class from D16 or D22.
- The root's review-package budget command over every file of `git diff --name-only BASE -- '*.py'` — expected: the largest is at most 60000.
