# Task 7: Replay verdicts, then only the kept candidates (one commit each)

Spec § Candidates; per D8, D9–D14, D18 and D21. Step 1 is the decision point. It runs the coordinate pass on this host's live corpus and records every candidate's verdict in the acceptance record. Steps 7A–7E run only for a `keep` verdict; a rejected candidate gets no product code (D9), only its numbers in the record.

**Files:** always `.agents/artifacts/plans/2026-10-25-issue-432-owner-handoff-economics.acceptance.md`. Each kept part lists its own files below.

**Interfaces:**
- Consumes: Task 4's `--sweep` rows (`step`, `spec`, `verdict`, `live_confirmation_required`); Task 3's `PhaseBudget`, `PRODUCT_KNOBS`, `crossing_threshold`, `select_phase_action` and meter record; Task 2's `invocations`.
- Produces: product defaults and knobs for the kept candidates only. Task 8 reads the record's `## Replay verdicts`.

**Invariants:**
- Each kept candidate is one commit, `feat(…): <candidate> (issue 432)`, carrying its tests. Commits land in the order 7A–7E.
- A kept knob joins `phase_budget.PRODUCT_KNOBS` in the same commit that makes the product honour it (D21). `PhaseBudget`'s default for it is the sweep's chosen value.
- After 7A, 7C and 7D (they move `PhaseBudget` defaults), **Report tests** also pass unchanged (D24).

- [ ] **Step 1: The decision point** (timeout 1800 s)

```bash
just agent-costs --report owners --days 14 --sweep --format json >"$SCRATCH/replay.json"
just agent-costs --report owners --days 14 --sweep >"$SCRATCH/replay.txt"
jq -r '.simulated[] | select(.step == "final") | [.arm, .spec, .verdict, .mean_saving, .lower_bound, .live_confirmation_required] | @tsv' "$SCRATCH/replay.json"
```

Expected: one `final` row per chosen candidate, and a `combined` row over those kept alone (D24); with a `reject` combined row nothing is kept. Write `## Replay verdicts` into the acceptance record:
- the corpus (window; lineages; owners; delivered, by project and by before/after the meter deploy, taken as PR #428's `mergedAt` from `env -u GITHUB_TOKEN -u GH_TOKEN gh pr view 428 --repo fagenorn/nix-config --json mergedAt`);
- the pricing line and the identity check (`calibration.identity_matches` must be `true`; `false` stops the task as BLOCKED, because the replay is then unsound);
- the text report's `Simulated arms` and `Calibration` sections, pasted verbatim in a fenced block;
- one table: candidate | step | arm spec | mean saving | lower bound | share | verdict | live confirmation required.

The candidates are: threshold (`threshold` step, chosen value when ≠ 110,000 everywhere; `never` is a reference row, never built, D27), boot slimming (`boot`), guard (`guard`), cap (`cap`), no-help (`help`) and keepalive (`keepalive`, always `info`, never built).

- [ ] **7A — Threshold** (only if the chosen arm is not 110,000 for every phase)
  - Files: `python/agent_tools/phase_budget.py`, `tests/test_phase_budget.py`, `home/common/agent-skills/tests/test_workflow_state.py`, `python/README.md`, `home/common/claude-code/README.md`.
  - Make `PhaseBudget`'s `threshold`/`phase_thresholds` defaults the chosen value(s). Update `test_defaults_hand_off_at_110000_in_every_phase` (rename it after the value) and `test_default_ceiling_hands_off_at_110000_and_continues_at_109999` to the new boundary (`T` hands off, `T − 1` continues, at the phase it governs).
  - `rg -n "110,000|110000|120,000|120000" python/README.md home/common/claude-code/README.md home/common/agent-skills/README.md` lists the prose to update.

- [ ] **7B — Boot slimming** (only if `boot=slim` is kept)
  - Files: `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/agent-skills/skills/from-issue/delegated-owner.md`, `home/common/agent-skills/skills/from-issue/resume-pack.md`; phrase-pin deletions in `home/common/agent-skills/tests/test_workflow_skill_contracts.py` if any pin the replaced text.
  - Make spec § Candidates' two boot-slimming edits (D12): sdd's resume reads only the root header and the resumed member; `ship-handoff.md` is read once Phase 6's gates pass.
  - Each edit replaces text and adds none: count bytes with `wc -c` before and after; the totals must not grow. Then run `just agent-instruction-budget`.
  - Test: `rg -n "ship-handoff" home/common/agent-skills/skills/from-issue/delegated-owner.md` shows the read tied to Phase 6's gates, and the replaced sentences are gone. Add no new phrase pins (agent-helpers rule 6).

- [ ] **7C — Just-started guard** (only if a guard `G > 0` is kept)
  - Files: `python/agent_tools/phase_budget.py`, `python/agent_tools/context_meter.py`, `python/agent_tools/context_meter_crossing.py`, `tests/test_context_meter.py`, `tests/test_phase_budget.py`, `python/README.md`, `home/common/claude-code/README.md`.
  - `PRODUCT_KNOBS` gains `guard`, and the default `guard` becomes `G`. The meter record may also carry `baseline` (int or `null`). A record of the two or three earlier shapes is accepted and written back in the four-key form.
  - `baseline` is set at the owner's registering call to that call's measurement, or at its next measured call when it is `null`. The crossing, re-arm and unguarded phase boundaries follow spec § Candidates, Just-started guard (D10).
  - Tests (`CrossingTest`, with `env={"AGENT_PHASE_BUDGET": "guard=40000"}` while 7C is pending, or with the new default after it):

```python
    def test_a_just_started_owner_is_not_told_until_baseline_plus_guard(self):
        env = {"AGENT_PHASE_BUDGET": "guard=40000"}
        self.assertIsNone(self.call(98000, MARK, env=env))          # registers; baseline 98k
        self.assertIsNone(self.call(120000, env=env))
        self.assertEqual(self.call(139000, env=env), CROSSING_AT(139000, 138000))

    def test_an_old_record_gains_a_baseline_at_its_next_measured_call(self):
        state = self.home / ".agents" / "state" / "context-meter"
        state.mkdir(parents=True)
        path = state / f"{SESSION}.agent-{AGENT}.json"
        path.write_text('{"notified": false, "owner": true, "phase": 6}', encoding="utf-8")
        self.call(90000, env={"AGENT_PHASE_BUDGET": "guard=40000"})
        self.assertEqual(json.loads(path.read_text())["baseline"], 90000)
```

  `tests/test_phase_budget.py`: `parse("guard=40000")` now succeeds; `test_bad_items_raise_naming_the_item` drops `"guard=40000"`.

- [ ] **7D — Hand-off cap** (only if a cap `n` is kept; risk paths `workflow-state.py`, `attempt_store.py`; D11, D25)
  - Files: `home/common/agent-skills/scripts/workflow-state.py` (`SCHEMA_VERSION = 11`; `ATTEMPT_FIELDS` + `handoff_streak`; `PHASE_INPUT_FIELDS` + `handoff_streak`, `cap`; `validate_phase_inputs`, `command_progress`, `record_progress_marker`'s `advanced` branch, attempt creation), `python/agent_tools/attempt_store.py` (`locked_read`, `check_unlocked`, the `migrate` row classifier), `python/agent_tools/attempt_identity.py` (`_MAX_SCHEMA_VERSION = 11`), `python/agent_tools/phase_budget.py` (`PRODUCT_KNOBS` + `cap`, default `n`; `select_phase_action(..., handoff_streak: int = 0, cap: int | None = None)`), `home/common/agent-skills/tests/test_workflow_state.py`, `home/common/agent-skills/tests/test_attempt_migration.py`, `tests/test_phase_budget.py`, `home/common/agent-skills/README.md` (§ Lifecycle helpers: the streak and its resets).
  - Every attempt holds `handoff_streak`, an int ≥ 0, from 0. The 10 → 11 step sits beside `attempt_store`'s 8/9 → 10 step (locked read, `check_unlocked`, `workflow-state migrate`), and older schemas continue to 11. It adds `handoff_streak: 0` to attempts and `handoff_streak: 0, cap: null` to non-null `phase_inputs`, so every stored action recomputes unchanged.
  - `progress`: a `--phase` above the attempt's resets the streak to 0; the gate then decides with the streak and `current().cap` and stores both in `phase_inputs`; a finalised `--handoff-path` call adds 1. `mark-progress` `advanced` sets 0. Validation still recomputes `select_phase_action(direct=direct, **phase_inputs)`, so later increments, resets or another `AGENT_PHASE_BUDGET` cannot invalidate a stored decision. `validate_phase_inputs`: `handoff_streak` int ≥ 0, `cap` `null` or int ≥ 1.
  - `select_phase_action` answers `continue` where its context or turn branch would answer `handoff` once `cap is not None and handoff_streak >= cap`; its `not next_needs_context` branch is unaffected. The replay applies the cap itself.
  - Tests: the existing `select_phase_action` table, unchanged; after two finalised hand-offs at one phase, a third gate at 120,000 answers `continue` with cap 2 and stores `handoff_streak: 2, cap: 2`; a higher phase answers `handoff` again; `advanced` resets the streak, `unchanged` does not; after each transition, and after a call under another cap, a fresh validating read accepts the ledger; schema 10 reaches 11 by a normal write and by `workflow-state migrate`, schema 9 in one read (follow the 8/9 → 10 tests' fixtures); an attempt without `handoff_streak`, or `phase_inputs` without `cap`, is refused.

- [ ] **7E — No `--help`** (only if `help=drop` is kept)
  - Files: `home/common/agent-skills/scripts/workflow-state.py` (`progress` and `suspend`: `--issue`/`--attempt` optional), `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/tests/test_workflow_state.py`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/README.md`.
  - When `--issue` or `--attempt` is absent, it is derived with `parse_action_id(args.action_id)`. When both a flag and `--action-id` are present, they must agree, else `WorkflowError("--issue/--attempt disagree with --action-id")`. With neither flag and no `--action-id` → `WorkflowError("progress needs --action-id or --issue and --attempt")` (the same for `suspend`).
  - The phase-gate and suspension templates follow spec § Candidates, No `--help` (D13), byte-neutral per profile; run `just agent-instruction-budget`.
  - Tests:
    - progress with only `--action-id 14:1:1` records on issue 14 attempt 1;
    - a disagreeing `--issue` is refused;
    - suspend derives the same way;
    - `test_workflow_skill_contracts.py` pins the template's argv (`workflow-state progress --repo-root --run-id --action-id --phase --next-needs-context --artifacts-sufficient --remainder-self-contained`), and `test_shell_example_contracts.py` vets it unchanged;
    - pins of the replaced prose are deleted.

- [ ] **Verify after each kept part:** the focused commands named in Global Constraints for its files (**Meter and policy tests**, **Gate tests**, **Report tests**), plus `just agent-instruction-budget` after 7B and 7E. Expected: `OK` and exit 0. After the last kept part: **Build**.

- [ ] **Commit:** the record (Step 1) as `docs(plan): issue 432 replay verdicts`, then one commit per kept part, each staging only that part's files.
