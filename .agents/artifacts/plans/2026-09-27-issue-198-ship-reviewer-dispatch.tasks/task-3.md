# Task 3: from-issue Phase 7 ships inline on the gap and suspends on a genuine one

Decisions: D2 (the nested ship owner stays the default), D5 (exact lines first,
the `check-launch` fence, no second inline run, the one departure from a
rollover `delegate`), D6 (the genuine gap suspends on `agent_dispatch`), D8
(HUMAN-GATE.md unchanged; the inline run is its owner-runs-the-path-itself
case), D9 (the dispatch line stays byte-identical, and the exception is a
paragraph after it), D12 (a remainder launch is unchanged), D14 (the name, and
"the ship report's"). Spec §"from-issue Phase 7: fallback to inline ship-issue"
and §"The genuine gap". Work from the worktree root. Every shell block starts
with `set -euo pipefail` (`set -uo pipefail` in the watch-it-fail steps) and
these abbreviations, which the blocks below omit:

```bash
T=home/common/agent-skills/tests; F=home/common/agent-skills/skills/from-issue/SKILL.md
```

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (one phrase in
  `## Terminal return procedure`, the opening sentence and value list of
  `## Suspension procedure`, and `## Phase 7 — Ship`'s report handling plus one
  new paragraph at its end)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (two
  new methods, and one more entry in the identity test's tuple)

**Interfaces:**
- Consumes (Task 1): `workflow-state suspend --blocked-on agent_dispatch`, which
  the suspension procedure's command line reaches with `<value>` =
  `agent_dispatch`.
- Consumes (Task 2): ship-issue's Phase-0 `reviewer-dispatch probe`, the closed
  line `capability_gap: agent_dispatch`, the module constant
  `CAPABILITY_GAP_LINE`, and
  `test_capability_gap_line_is_spelled_identically_everywhere`, whose tuple
  lists `("ship-issue/SKILL.md", self.ship_issue)` and
  `("from-issue/ship-handoff.md", self.ship_handoff)`.
- Produces, for Task 4: the bold paragraph label `**Dispatch-gap fallback.**` at
  the end of Phase 7, which AUTO.md cites as "`SKILL.md`'s Phase-7 dispatch-gap
  fallback".

**Invariants:**
- The `from-issue-ship-owner` marker, its call line and the paragraph after it
  ("Read `ship-handoff.md` …") keep their bytes (D9).
- Phase 7 handles the report in this order: the re-entry line, then the gap
  line, then `delivery_stalled`, then ship-summary validation, `check-launch`
  and `workflow-state finish`. The existing pins
  `test_from_issue_revalidates_its_launch_before_the_terminal_finish` and
  `test_owner_lifecycle_is_optional_for_direct_use_and_covers_all_stops` stay
  green unchanged.
- Phase 7 never spells `workflow-state suspend`. The genuine gap cites the
  suspension procedure, which alone spells the verb.
- The fallback runs `check-launch` before the inline run under lifecycle
  identity, and a `current: false` or failed check writes nothing. A gap line
  from the inline run never starts a second inline run. A `delivery_remainder`
  launch is unchanged.
- The suspension procedure keeps its verb line, its canonical
  `Suspended (blocked_on=<value>). Resume: <reentry from the envelope>` line and
  its handoff-versus-suspension sentence. It gains exactly one interruption and
  one value.
- No new line contains `Agent(`, and no new fence is added.

- [ ] **Step 1: Confirm the gate fails at the start**

```bash
set -uo pipefail
F=home/common/agent-skills/skills/from-issue/SKILL.md
grep -c 'capability_gap\|agent_dispatch\|Dispatch-gap fallback' $F
grep -c "ship owner's returned summary" $F
```

Expected: `0`, then `1`.

- [ ] **Step 2: Write the failing tests**

1. In `test_capability_gap_line_is_spelled_identically_everywhere`, add
   `            ("from-issue/SKILL.md", self.from_issue),` as a third tuple entry,
   directly after the `("from-issue/ship-handoff.md", self.ship_handoff),` line.
2. In `WorkflowSkillContractsTest`, directly above
   `    def test_auto_continuation_and_bookkeeper_are_interface_two(self):`,
   insert:

```python
    def test_from_issue_phase_seven_ships_inline_on_the_dispatch_gap(self):
        # A ship owner that cannot launch reviewers returns the closed gap line
        # from Phase 0 with nothing changed. The owner re-checks its launch,
        # ships inline through `Skill`, and only a gap from that inline run
        # suspends (per D2, D5, D6). The verb stays in the suspension
        # procedure: Phase 7 never spells it (see the launch-revalidation test).
        phase_seven = self.section(self.from_issue, "## Phase 7", "## Notes")
        self.assert_ordered(
            normalized(phase_seven),
            "receiving the ship report",
            "only the re-entry line `/from-issue <num> --auto`",
            f"only the line `{CAPABILITY_GAP_LINE}`",
            "no subagent-launch tool",
            "never decode or validate it",
            "`delivery_stalled`",
            "**Dispatch-gap fallback.**",
            "same `check-launch` fence",
            "the canonical re-entry line `/from-issue <num> --auto` on its own line",
            "through your own `Skill` tool",
            "writing only `checkpoint-delivery`",
            "never starts a second inline run",
            "suspension procedure with `<value>` = `agent_dispatch`",
            "`delivery_remainder` launch",
        )
        self.assertNotIn("workflow-state suspend", phase_seven)
        self.assertIn("After Phase 7 it is the ship report's summary",
                      normalized(self.from_issue))

    def test_suspension_procedure_admits_agent_dispatch(self):
        suspension = normalized(self.section(
            self.from_issue, "## Suspension procedure", "## Phase 0"))
        self.assertIn("a context that cannot launch the agents a phase needs",
                      suspension)
        self.assert_ordered(
            suspension, "`human_gate`", "`external`", "`agent_dispatch`",
            "(the reaper alone owns `unknown`)",
        )
```

- [ ] **Step 3: Run the tests and watch them fail**

```bash
set -uo pipefail
T=home/common/agent-skills/tests
PYTHONPATH=python python3 -m unittest $T/test_workflow_skill_contracts.py \
  -k dispatch_gap -k admits_agent_dispatch -k spelled_identically 2>&1 \
  | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED' | cut -c1-120
```

Expected: `Ran 3 tests` and `FAILED (failures=3)`: the two new tests, and the
identity test's new `from-issue/SKILL.md` subtest.

- [ ] **Step 4: Edit `$F`**

Every block nested in a numbered item below is indented three spaces only
because it sits in the list. Strip exactly those three spaces; any further
indentation is the file's own.

1. In `## Terminal return procedure`, replace
   `After Phase 7 it is the ship owner's returned summary, which` with
   `After Phase 7 it is the ship report's summary, which` (D14).
2. In `## Suspension procedure`, replace exactly
   ```
   transport failure, a permission prompt only a human can approve, or an external
   wait. A suspension parks the attempt without ending it — it consumes no attempt,
   needs no authorization phrase, and re-entry resumes it in place. Call:
   ```
   with
   ```
   transport failure, a permission prompt only a human can approve, an external
   wait, or a context that cannot launch the agents a phase needs. A suspension
   parks the attempt without ending it — it consumes no attempt, needs no
   authorization phrase, and re-entry resumes it in place. Call:
   ```
   and replace exactly
   ```
   with `<value>` one of `usage_limit`, `transport`, `human_gate`, or `external`
   (the reaper alone owns `unknown`). Then print the canonical line as the final
   user-facing output:
   ```
   with
   ```
   with `<value>` one of `usage_limit`, `transport`, `human_gate`, `external`, or
   `agent_dispatch` (the reaper alone owns `unknown`). Then print the canonical
   line as the final user-facing output:
   ```
3. In `## Phase 7 — Ship`, replace exactly
   ```
   that line and write nothing. A report that validates at `--boundary
   ```
   with the lines below. The gap line in backticks stays whole on one line:
   ```
   that line and write nothing. A report that is only the line
   `capability_gap: agent_dispatch` means ship-issue's Phase-0 reviewer-dispatch
   probe found that the ship owner's context cannot launch its reviewers, before
   anything was launched or written. A `from-issue-ship-owner` launch this context
   cannot make, because it has no subagent-launch tool, counts as that same line.
   Compare it byte for byte, never decode or validate it, and take the
   dispatch-gap fallback below. A report that validates at `--boundary
   ```
4. At the end of `## Phase 7 — Ship`, after the paragraph that ends
   ``prefix its phases `ship-Phase-N` when narrating so the two sequences stay distinguishable.``
   and before `## Notes`, insert one blank line and then this paragraph. Keep
   each backticked gap line whole on one line:
   ```
   **Dispatch-gap fallback.** This is the one exception to shipping through a
   fresh ship owner, and the one allowed departure from a rollover Phase-6
   `delegate`. With lifecycle identity, first run the same `check-launch` fence
   with this owner's own `action_id`; on `current: false` or any helper failure,
   write nothing, print the canonical re-entry line `/from-issue <num> --auto` on
   its own line, and stop. Ledger-free there is no launch identity, so skip the
   fence. Then invoke `ship-issue` through your own `Skill` tool with the same
   validated handoff bytes — nothing was changed, so they are still accurate, and
   ship-issue re-validates them on entry — and carry out the ship-owner prompt's
   task list yourself: every phase, the auto-mode rules and, with a
   `ship-handoff/v2`, the `## Delivery loop`, writing only `checkpoint-delivery`
   inside it. Its reviewers run as leaves one level below you. Feed its return
   back into the report handling above: the re-entry line, a `delivery_stalled`
   reply and a `ship-summary/v2` are handled exactly as a fresh ship owner's are,
   and a human gate reached inside the run is `ship-issue/HUMAN-GATE.md`'s case of
   an owner running that path itself. A `capability_gap: agent_dispatch` line
   returned by the inline run is the genuine gap and never starts a second inline
   run: with lifecycle identity follow the suspension procedure with `<value>` =
   `agent_dispatch`, making no `finish` call; ledger-free, report the gap to the
   user and stop, keeping the worktree. The fallback covers only the
   review-bearing ship launch: a `delivery_remainder` launch runs remainder mode,
   which never probes and never returns the gap line.
   ```
5. In `## Phase 7 — Ship`, replace exactly
   `ship owner checkpointed a denial, which already suspended this attempt: relay`
   with
   `ship-issue run checkpointed a denial, which already suspended this attempt: relay`
   — the re-entry line can now come back from the owner's own inline run too
   (per D15).
6. In `## Dispatch, phase-budget and attempt-budget rules`, replace exactly
   ```
   routes defined there: Phase-6 `delegate` launches the existing fresh ship owner,
   ```
   with
   ```
   routes defined there: Phase-6 `delegate` launches the existing fresh ship owner
   (or, on a dispatch gap, runs Phase 7's dispatch-gap fallback),
   ```
   (per D15).

- [ ] **Step 5: Verify**

```bash
set -euo pipefail
T=home/common/agent-skills/tests; F=home/common/agent-skills/skills/from-issue/SKILL.md
if awk '/^## Phase 7/,/^## Notes/' $F | grep -qF 'workflow-state suspend'; then exit 1; fi
if git diff HEAD -U0 -- $F | grep -E '^\+' | grep -qF 'Agent('; then exit 1; fi
if grep -qF "ship owner's returned summary" $F; then exit 1; fi
if grep -qF 'ship owner checkpointed a denial' $F; then exit 1; fi
grep -cF '(or, on a dispatch gap, runs Phase 7'"'"'s dispatch-gap fallback),' $F
grep -cF 'Agent(subagent_type="general-purpose", model="opus", effort="high") launches `ship-issue` as a fresh ship owner, not inline via `Skill`.' $F
PYTHONPATH=python python3 -m unittest $T/test_workflow_skill_contracts.py $T/test_dispatch_contracts.py \
  $T/test_shell_example_contracts.py $T/test_agent_model_matrix.py 2>&1 \
  | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
PYTHONPATH=python python3 -m agent_tools.agent_model_matrix validate
```

Expected: the four prohibitions pass silently, and both counts (the Phase-6
gate clause and the dispatch line) are `1`. The four suites together end `OK (skipped=3)` with 2 more tests than at the
start of this task. Last comes `agent model matrix: valid`.

- [ ] **Step 6: Commit**

```bash
set -euo pipefail
T=home/common/agent-skills/tests; F=home/common/agent-skills/skills/from-issue/SKILL.md
git add $F $T/test_workflow_skill_contracts.py
git commit -m "feat(from-issue): ship inline when the ship owner cannot dispatch reviewers" \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013ho926R9qjak8E3fLvEdq6"
```
