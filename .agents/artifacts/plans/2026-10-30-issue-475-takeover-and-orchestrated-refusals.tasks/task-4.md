# Task 4: Guidance, READMEs and skill contracts

Spec § Decisions (Guidance text; Dead-worker recovery) and § Test seams (skill-contract seam), per D4, D9, D10, D13 and D14. The contract tests are this task's failing tests: at its starting commit the skill text carries neither marker nor the re-entry argv.

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/acquire-direct.md`
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md` (§5 Final report)
- Modify: `home/common/agent-skills/README.md` (§ .superpowers paths and launch-fenced writers; § Run identity and migrate)
- Modify: `python/README.md` (the schema-10 paragraph that begins "From schema 10 the control plane decides from the store")
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1's `TAKEOVER_REFUSAL` and Task 3's `ORCHESTRATED_RESUME` and `HOLD_REFUSAL`, module-level literals in `home/common/agent-skills/scripts/workflow-state.py`. Also the test module's `module_constants(path, *names)`, `normalized(text)`, `REPO_ROOT`, `ORCHESTRATE`, `ACQUIRE_DIRECT` and `ORCHESTRATE_MACHINE_TEXT`.
- Produces: `WORKFLOW_STATE`, `DIRECT_REFUSAL_MARKERS` and the class `OrchestratedReentryContractsTest` in the contract test module.

**Invariants:**
- The test module still imports nothing from `agent_tools` and passes with no `PYTHONPATH` (issue 473 D11). It reads the helper's literals by AST (D13).
- The `orchestrate-issues` final report gives an issue suspended on `human_gate`, `external` or `agent_dispatch` the re-entry `orchestrate-control start --repo-root <ledger_repo_root> <issue> --run-id <run-id>`, which is `ORCHESTRATED_RESUME` rendered with those placeholders. `/from-issue <issue> --auto` no longer appears there (D9). The `/from-issue <num> --auto` owner-return lines of §2 and §4 stay.
- `acquire-direct.md` names each marker in backticks: `owner_unavailable refused: live workers:` and ` is held by orchestrated run `. Each is a substring of its helper literal (D10, D13).
- `just agent-instruction-budget` prints `check: pass`, with no change to `instruction-load.json` (D14). The edits below make `acquire-direct.md` exactly 169 bytes longer and `SKILL.md` 27 bytes longer.

- [ ] **Step 1: Write the failing tests**

In `test_workflow_skill_contracts.py`, add this line to `ORCHESTRATE_MACHINE_TEXT[ORCHESTRATE]`, right after its first item `"orchestrate-control start --repo-root <ledger_repo_root>",`:

```python
        "orchestrate-control start --repo-root <ledger_repo_root> <issue> --run-id <run-id>",
```

Insert this right above `class LaneTriageRecordKeysTest`, after `LANE_TRIAGE_VERDICT_KEYS` and `module_constants`:

```python
WORKFLOW_STATE = REPO_ROOT / "home/common/agent-skills/scripts/workflow-state.py"
# The direct-owner refusal markers acquire-direct.md branches on (issue 475 D10).
DIRECT_REFUSAL_MARKERS = {"TAKEOVER_REFUSAL": "owner_unavailable refused: live workers:",
                          "HOLD_REFUSAL": " is held by orchestrated run "}


class OrchestratedReentryContractsTest(unittest.TestCase):
    """Issue 475: the re-entry argv and refusal markers have their home in workflow-state."""

    def setUp(self):
        self.helper = module_constants(WORKFLOW_STATE, "ORCHESTRATED_RESUME",
                                       *DIRECT_REFUSAL_MARKERS)

    def test_the_final_report_reentry_is_the_helpers_resume_command(self):
        resume = self.helper["ORCHESTRATED_RESUME"].format(
            repo_root="<ledger_repo_root>", issue="<issue>", run_id="<run-id>")
        self.assertIn(resume, ORCHESTRATE_MACHINE_TEXT[ORCHESTRATE])
        self.assertNotIn("/from-issue <issue> --auto",
                         normalized(ORCHESTRATE.read_text(encoding="utf-8")))

    def test_acquire_direct_names_each_refusal_direct_owner_prints(self):
        text = normalized(ACQUIRE_DIRECT.read_text(encoding="utf-8"))
        for constant, marker in DIRECT_REFUSAL_MARKERS.items():
            with self.subTest(constant=constant):
                self.assertIn(marker, self.helper[constant])
                self.assertIn(f"`{marker}`", text)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (Contract run).
Expected: FAILED (failures=4). The two `acquire_direct` subtests fail, along with `test_the_final_report_reentry_is_the_helpers_resume_command` and `test_orchestrate_documents_carry_their_machine_text` on the new argv item.

- [ ] **Step 3: Edit the skill text**

`acquire-direct.md`: replace the two sentences

> Set `owner_unavailable` true only when the current user instruction explicitly authorizes takeover of the currently discovered unexpired active attempt. Set `new_run` true only when that instruction explicitly authorizes a new run after terminal replay.

with

> Set `owner_unavailable` true only when the current user instruction explicitly authorizes takeover of the discovered unexpired active attempt, and `new_run` only when it explicitly authorizes a new run after terminal replay.

Then append this sentence to the last paragraph, after "…it never falls back to another lifecycle or ledger-free route." and separated by one space:

> Relay an `owner_unavailable refused: live workers:` or ` is held by orchestrated run ` refusal verbatim and stop; never retry it with either flag, or release a worker the user has not said is gone.

`orchestrate-issues/SKILL.md` §5: replace the three lines

```text
delivery stages, and a re-entry line — `/from-issue <issue> --auto` for an issue suspended on a
cause that a `--label` or `--milestone` sweep does not resume (`human_gate`, `external` or
`agent_dispatch`), and the orchestrate re-invocation itself for the whole run — every column sourced
```

with

```text
delivery stages, and a re-entry line — `orchestrate-control start --repo-root <ledger_repo_root>
<issue> --run-id <run-id>` for an issue suspended on `human_gate`, `external` or `agent_dispatch`
(a direct `/from-issue` is refused with it), and the orchestrate re-invocation for the whole run — every column sourced
```


- [ ] **Step 4: Edit the READMEs**

`home/common/agent-skills/README.md`, § .superpowers paths and launch-fenced writers: after the sentence "An owner's own `suspend`, `finish`, handoff `progress` or suspending `checkpoint-delivery` is refused while a registered worker of its launch is live.", insert:

> A `direct-owner` takeover (`owner_unavailable: true`) is refused too, with `workflow-state: owner_unavailable refused: live workers: <ids>` naming every live worker, while that worker's launch record (the attempt or delivery remainder) is before its `deadline_at` (issue 475). From the deadline on, the expiry reap recovers the run as before. Inside it, a worker the user confirms is gone is released with `workflow-state release-worker … --event stopped`, never on the agent's own judgment. `control` and the deadline reaper do not run this check: they remain the recovery path for a run whose owner died with workers live.

§ Run identity and migrate: append a new paragraph after the existing one:

> An orchestrated run also keeps *issue hold pointers* (issue 475). Every locked write of an orchestrated run ensures, for each issue whose latest attempt or latest delivery remainder is `active`, `handed_off` or `suspended`, an inert core transaction under `issue-hold/v1:<issue>:<k>` whose closed subject `issue-hold/v1` names the issue and the run's transaction id. `k` is the first free ordinal from 1, unless a pointer for that issue already names the run, and the pointer is created with the run transactions' creation arguments. Direct runs get none, because the direct index finds them. Pointers are never removed, and a run last written by an older helper gains its pointers on its next write by this one. Before it creates anything, `direct-owner` reads an issue's pointers in order. The first named run whose ledger still holds the issue refuses the call, whatever its `new_run` and `owner_unavailable`, with `workflow-state: issue <N> is held by orchestrated run <run-id>; resume it through orchestrate-issues: orchestrate-control start --repo-root <root> <N> --run-id <run-id>`. That refusal exits 2 and writes nothing. A run whose ledger is absent, or no longer holds the issue, is passed over, and a ledger that does not validate refuses the call with the reader's error. Naming the issue makes the re-entry sweep human-directed, so it clears a `human_gate`, `external` or `agent_dispatch` suspension.

`python/README.md`: at the end of the paragraph that begins "From schema 10 the control plane decides from the store", append:

> Each locked write of an orchestrated run also ensures an inert *issue hold pointer*, under `issue-hold/v1:<issue>:<k>` with the closed subject `issue-hold/v1` (issue and run transaction id), for each issue the run still holds (`agent_tools.attempt_store.settle_holds`). `direct-owner` reads those pointers with `hold_runs` to refuse a direct run of an orchestrated-held issue (issue 475).

- [ ] **Step 5: Verify**

Run (Contract run). Expected: OK.
Run (Budget). Expected: `check: pass`.
Run: `bash -c 'for f in home/common/agent-skills/skills/from-issue/acquire-direct.md home/common/claude-code/skills/orchestrate-issues/SKILL.md; do echo "$f $(( $(wc -c < "$f") - $(git show HEAD:"$f" | wc -c) ))"; done'`
Expected: deltas of `169` and `27`. Any other value means the text differs from the dictated text, so recheck it before the budget can drift.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/acquire-direct.md home/common/claude-code/skills/orchestrate-issues/SKILL.md home/common/agent-skills/README.md python/README.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit … -- -m "docs(skills): relay takeover and orchestrated-hold refusals; re-enter through orchestrate-control (issue 475)"
```
