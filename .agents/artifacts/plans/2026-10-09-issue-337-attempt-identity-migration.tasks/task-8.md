# Task 8: Skill text, READMEs and the final gate

**Files:**
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md` (§2 "Bootstrap and observe", the mint sentence and the `init-run` code block only)
- Modify: `home/common/agent-skills/skills/from-issue/acquire-durable.md` (line 3's run-id clause only)
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (pin the new machine text)
- Modify: `python/README.md` (§ Transaction core)
- Modify: `home/common/agent-skills/README.md` (§ Lifecycle helpers: new `### Run identity and migrate` subsection)

**Interfaces:**
- Consumes: the CLI as built by Tasks 2–5: `workflow-state init-run --repo-root <r> --creation-key <key>` (reply `run_id`), `init-run --run-id <id>` (re-bootstrap of an existing run only), `workflow-state migrate --repo-root <r> [--apply]`, the `attempt-migration-report/v1` report; `direct-owner` minting (Task 3); the installed launcher (Task 7).
- Produces: skill text and docs only; the pinned strings below.

**Invariants:**
- orchestrate-issues §2: the reuse rule is unchanged (list `<ledger_repo_root>/.superpowers/workflows/` for a run covering the same issue set with a non-final attempt or a missing outcome; reuse its id — #339 owns that listing). The sentence "Only when none matches do you mint a new one." becomes: only when none matches, call `init-run` with `--creation-key orchestrate-issues:<YYYYMMDD>:<issue numbers in caller order joined by ->` and take `run_id` from the validated bootstrap; a reused run is re-bootstrapped with `--run-id <run-id>`. The code block shows both forms, each piped through `artifact-budget validate-report --boundary workflow-response --input -` exactly as the current block is.
- acquire-durable.md line 3: "resolve an immutable `ledger_repo_root` and a stable run ID, call bounded `workflow-state init-run`" becomes "resolve an immutable `ledger_repo_root`, call bounded `workflow-state init-run --creation-key from-issue:<num>:<YYYYMMDD>` (or `--run-id <run-id>` to re-bootstrap the run it created) and take `run_id` from the validated `workflow_bootstrap`"; the rest of the line is unchanged, and the ordered strings `test_from_issue_standalone_modes_use_live_lifecycle_interfaces` pins (`workflow-state init-run` → `max_parallel: 1` → `workflow-state control` → first `spawn` envelope) still appear in that order.
- No ceiling in `home/common/agent-skills/instruction-load.json` changes and that file is not edited (D22). If `just agent-instruction-budget` reports a profile over its ceiling, condense the edited §2 paragraph (not other text) until it passes.
- `python/README.md` § Transaction core: replace "with no command-table row and no caller until #125's cutover" with a clause that names its first caller as it now is — `workflow-state` mints one created-only *run transaction* per attempt run in `<ledger root>/.superpowers/attempt-transactions/` through `agent_tools.attempt_identity`, and finds it by the read-only `TransactionStore.lookup` — then cite #337. Keep the slice list unchanged.
- agent-skills README `### Run identity and migrate` (written from the code as built, one paragraph, cite #337 and the spec): every run's identity is a core `rel_` UUIDv7 run transaction; `init-run --creation-key` and `direct-owner` mint new runs named by that id, `init-run --run-id` only re-bootstraps; schema-8 ledgers carry `transaction_id`, and a schema ≤ 7 ledger in one of the four legacy dialects is bound on its next locked write or by `workflow-state migrate --apply` after a read-only dry run, keeping its legacy id as its handle; refusals (`unknown_schema`, `invalid_state`, `unknown_dialect`, `ambiguous_lineage`, `location_mismatch`) leave the ledger's bytes untouched and are reported with exit 0; a helper from before schema 8 refuses a migrated ledger and there is no reverse migration (D10); installed `workflow-state` runs under the agent_tools interpreter with `-I` (D16).

- [ ] **Step 1: Write the failing test**

In `test_workflow_skill_contracts.py`, extend `ORCHESTRATE_MACHINE_TEXT[ORCHESTRATE]` with the exact argv fragment `"workflow-state init-run --repo-root <ledger_repo_root> --creation-key orchestrate-issues:<YYYYMMDD>:"`, and add to `test_from_issue_standalone_modes_use_live_lifecycle_interfaces`:

```python
        self.assertIn("workflow-state init-run --creation-key from-issue:<num>:<YYYYMMDD>",
                      durable)
```

Pin only the argv (`docs/standards/agent-helpers.md` rule 6): no assertion on the removed English phrase.

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k carry_their_machine_text -k standalone_modes`
Expected: FAIL — the new fragments are absent.

- [ ] **Step 3: Edit the skill text and READMEs**

Make the edits in Invariants. `orchestrate-issues/evals/evals.json` mentions `init-run` without its flags and stays unchanged.

- [ ] **Step 4: Verify the edits**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_instruction_load.py` — OK.
Run: `just agent-instruction-budget 2>&1 | tail -5` — passes with no `--raise-label`.
Run: `git diff --quiet eca16cd85453dd290a9ab8ac66b8b3f2f7e697d7..HEAD -- home/common/agent-skills/instruction-load.json` after the commit — exit 0.

- [ ] **Step 5: Commit**

Stage the five files, then `launch-commit … -- -m "docs: run identity and migrate in the skills and READMEs (#337)"` with the session trailers.

- [ ] **Step 6: Final gate (once, on the final head)**

Run: `just build` (timeout 3600 s) — succeeds.
Run: `just agent-workflow-tests > "$SCRATCH/final.log" 2>&1; tail -5 "$SCRATCH/final.log"` (timeout 3600 s) — ends `OK`; `grep -cE '^(FAIL|ERROR):' "$SCRATCH/final.log"` prints `0`.
Run: `just agent-installed-skill-tests 2>&1 | tail -5` (timeout 3600 s) — ends `OK`.
Run: `git diff --stat eca16cd85453dd290a9ab8ac66b8b3f2f7e697d7..HEAD -- home/common/agent-skills/tests/fixtures/admission-replay/baseline.json` — prints nothing (AC5: the replay keeps its committed baseline).
No step of this gate runs any `workflow-state` against `/Users/anis/tmp/nix-config/.superpowers` (Global Constraints).
