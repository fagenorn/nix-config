# Task 6: Cut SKILL.md to the hub

**Files** (under `home/common/agent-skills/`):
- Modify: `skills/from-issue/SKILL.md`
- Modify: `instruction-load.json`, `skill-lint-debt.json`
- Test: `tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 5's tree. Every reference file now exists in its final name: `AUTO.md`, `rollover.md`, `delegated-owner.md`, `acquire-dispatcher.md`, `acquire-direct.md`, `acquire-interactive.md`, `acquire-durable.md`, `resume-pack.md`, `investigate.md`, `standards-review.md`, `REVIEW-CONTRACT.md`, `ship-handoff.md` and `decision-ledger.md`.
- Produces: a `SKILL.md` body of ≤ 280 reflowed lines and ≤ 21,000 bytes. 300 lines is the hard limit (AC2). The `L2` debt key is gone.

**Invariants:**
- Byte for byte:
  - frontmatter;
  - the resolve paragraph (per D10);
  - the five markers with their call lines (per D3);
  - the leaf-agent blockquote, exactly once, inside `## Dispatch, phase-budget and attempt-budget rules` (the `test_dispatch_contracts` section carrier);
  - the `Lifecycle worker:` line and its two sentences;
  - every `workflow-state`, `launch-scope` and `launch-commit` argv;
  - the `finish` and `suspend` ```` ```text ```` blocks;
  - the canonical suspension line;
  - the `## The flow` fence, which stays the file's only unlabeled fence.
- These headings keep their text (per D9): `Lifecycle identity`, `Decision ledger (artifact discipline)`, `Risk lanes`, `Skill-tool invocations`, `Dispatch, phase-budget and attempt-budget rules`, `Terminal return procedure`, `Suspension procedure`, `### Resume pack`, every `## Phase <n> — …`, and the bold rule names `**Writing workers.**`, `**Self-reap.**`, `**Interim child results.**`, `**Executable phase gate.**`.
- Closed sets keep their members and order:
  - the phase-gate actions `continue | fresh_start | handoff | delegate`;
  - the `blocked_on` values `usage_limit`, `transport`, `human_gate`, `external`, `agent_dispatch` (the reaper owns `unknown`);
  - the exit order: release workers, then `launch-scope reap`, then the exit write.
- The deadline rejection keeps one mapping line (per D7). It names both helper messages verbatim, `cannot record progress at or after attempt deadline` and `progress requires an active attempt`. It says to print the canonical re-entry line `/from-issue <num> --auto` and stop, and to write no `finish`, whether the rejection meant a suspension or the `stopped(stalled)` bound. The explanation of why goes.
- `## Files beside this one` is the only index: one line per reference file with its load condition, in phase order. It carries the per-phase reading scope that Task 3 placed there. It says that `REVIEW-CONTRACT.md` is handed over by absolute path and never read in.
- No other line contains `Agent(`.

- [ ] **Step 1: Remove the L2 debt key first (the lint fails until Step 3)**

Delete `"L2 home/common/agent-skills/skills/from-issue/SKILL.md"` from `skill-lint-debt.json` (per D12).

- [ ] **Step 2: Watch the gate fail**

Run: `PYTHONPATH=python python3 -m agent_tools.skill_lint check` (timeout 300 s)
Expected: non-zero exit, with the line `L2 home/common/agent-skills/skills/from-issue/SKILL.md: body is <n> reflowed lines, over 500`.

- [ ] **Step 3: Cut by content class (spec § Content classes)**

Work top to bottom:
1. `## Files beside this one`: rewrite it as the final index (Invariants).
2. `## Lifecycle identity`: no further cut beyond Task 3's text, except restated "validate before decoding" clauses.
3. `## The flow` and the checkpoint paragraph: keep. `## Decision ledger (artifact discipline)`: keep one sentence plus the pointer to the format file. `## Risk lanes`: keep the three lane definitions verbatim and the review rule. `## Skill-tool invocations`: keep the list and the inline-fallback sentence.
4. `## Dispatch, phase-budget and attempt-budget rules`:
   - cut the "re-read on every later turn" rationale;
   - Writing workers and Self-reap: keep the argv and the order, and cut explanations ("because…", "a registered bookkeeper would block…");
   - Interim child results: keep the rule's steps, and cut the second explanation of why ending a turn is safe;
   - Artifact report boundary: drop "(D5, D6, D11, D14)". Keep the rule in one paragraph: validate, then check, then compare the four metrics, then fail on any mismatch, before `progress`;
   - Executable phase gate: keep the four actions and the defaults line;
   - `handoff`: keep the steps;
   - `delegate`: keep both dispatch sites, the resume-pack argv and the one-line pointer to `rollover.md` and `delegated-owner.md` for the direct-autonomous route;
   - replace the deadline-expiry block with the D7 mapping line.
5. `## Terminal return procedure`: keep the summary composition (`state`, `custody`, `delivery_contract_digest`, `historical_owner_result`, empty arrays), the `validate-report --boundary ship-summary` step, release, reap, the `check-launch` fence, the `finish` block, relay-after-durable-write, the `delivery_remainder` relay, the one-line legacy-transport note, the terminal-replay `reentry` rule, the earlier-controller pointer to `rollover.md`, and "failure to persist is a failure to finish". Cut the rest.
6. `## Suspension procedure`: keep the cause list, release, the `live workers:` refusal (one clause), reap, the `suspend` block, the closed values, the `kind: terminal` replay handling, the canonical line and "Suspension is NOT a terminal return".
7. Phases 0–7: keep each phase's skill invocation, its pointer line and its CHECKPOINT. Phase 4 keeps the plan-prose ≠ code-prose rule. Phase 6 keeps the `sdd` lifecycle-identity handoff, the mechanic registration and the `mark-progress` argv, both mechanical sites, and the `validate-report --boundary sdd` / `review-package` / `validate-detail-input` gate. Phase 7 is as Task 4 left it.
8. `## Notes`: keep the authorization, signing, full-URL and back-up rules, each on one line.

- [ ] **Step 4: Delete the prose pins on `SKILL.md`**

Apply D11 and D13 to every remaining method that reads `FROM_ISSUE`:
- `WorkflowSkillContractsTest`: `test_delivery_interface_two_is_one_atomic_production_caller_contract` (scoped files leave the corpus; keep `--summary-file` and the `--result-file <path>` absence), `test_suspension_procedure_admits_agent_dispatch` (keep the ordered closed values), `test_from_issue_validates_artifacts_before_every_phase_advance`, `test_owner_persists_exact_terminal_result_before_return`, `test_owner_has_executable_phase_gate_and_action_semantics` (keep the closed action set), `test_owner_lifecycle_is_optional_for_direct_use_and_covers_all_stops`, `test_expiry_prose_describes_the_wall_clock_the_reaper_actually_reads`, `test_from_issue_routes_a_deadline_rejected_progress_to_the_suspension_procedure` (keep the two message strings and the re-entry line), `test_suspension_procedure_pins_verb_line_and_distinction`, `test_phase_gate_obeys_the_validated_phase_gate_action`, `test_suspension_validates_its_reply_and_replays_a_stall_bound_terminal`, `test_terminal_replay_relays_reentry` and `test_helper_binaries_resolve_from_bare_names` (keep the `~/.agents/bin/workflow-state` path).
- `LaunchFencedWorkerContractsTest.test_from_issue_phase_6_hands_sdd_its_lifecycle_identity` and `test_from_issue_registers_writers_and_releases_before_every_exit` (keep the `register-worker` argv).
- `ProgressMarkerContractsTest.test_from_issue_phase_6_names_the_marker_on_both_routes` (keep the `mark-progress` argv) and `test_the_bound_is_described_as_progress_not_phase`.
- `InterimChildResultContractsTest`: remove `FROM_ISSUE` from `OWNERS` and from each per-owner table, and keep the `SDD` and `SHIP_ISSUE` entries (per D13).
- `LaunchScopeWiringContractsTest.test_the_worker_sentence_follows_every_composed_worker_line` (the `FROM_ISSUE` ordering) and `test_every_owner_exit_reaps_between_release_and_write`. Keep the `"## Terminal return procedure"`, `"## Suspension procedure"` and `"**Self-reap.**"` headings and the `REAP`, `finish` and `suspend` argv in order, and drop the English anchors.
- Keep `test_the_leaf_clauses_do_not_name_launch_scope`, which is a structural check on the clause region, unchanged.

Then grep the test file for `FROM_ISSUE` and `self.from_issue`, and apply D11 to every remaining hit.

- [ ] **Step 5: Models**

Run `just agent-instruction-load tighten` (timeout 300 s).

- [ ] **Step 6: Verify**

Run: `PYTHONPATH=python python3 -m agent_tools.skill_lint check`. Expected: exit 0.
Run the focused suite. Expected: OK.
Run: `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`.
Run:

```bash
set -euo pipefail
PYTHONPATH=python python3 - <<'EOF'
from pathlib import Path
from agent_tools import skill_lint
path = Path("home/common/agent-skills/skills/from-issue/SKILL.md")
text = path.read_text(encoding="utf-8")
lines = skill_lint.reflowed_lines(skill_lint.parse_frontmatter(text)[1])
size = len(text.encode("utf-8"))
print(f"SKILL.md body {lines} reflowed lines, {size} bytes")
assert lines <= 300, "over the 300-line acceptance line"
if lines > 280 or size > 21000:
    print("over target (name it in the commit body)")
assert "attempt is usually now a resumable suspension" not in text, "expiry rationale still present"
for message in ("cannot record progress at or after attempt deadline", "progress requires an active attempt"):
    assert message in text, message
EOF
if grep -q 'from-issue/SKILL.md' home/common/agent-skills/skill-lint-debt.json; then exit 1; fi
```

Expected: exit 0. At Task 5's head it fails on the line count.

- [ ] **Step 7: Commit**

Commit as `refactor(from-issue): cut SKILL.md to the hub (#295)`.
