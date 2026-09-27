# Task 4: Rollover owner, earlier controller and orchestrate report carry the new outcome, then the final gate

Decisions: D5 (the fallback is the one departure from a rollover Phase-6
`delegate`), D6 (a label sweep leaves `agent_dispatch` parked), D10 (the two
closed line exceptions, and the orchestrate report's per-issue line), D14 ("the
ship report's"). Spec §"Relays and reports". Work from the worktree root. Every
shell block starts with `set -euo pipefail` (`set -uo pipefail` in the
watch-it-fail steps) and these abbreviations, which the blocks below omit:

```bash
T=home/common/agent-skills/tests; A=home/common/agent-skills/skills/from-issue/AUTO.md
O=home/common/claude-code/skills/orchestrate-issues/SKILL.md
```

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md` (`#### Fresh
  delegated owner`, `#### Earlier controller stop`, and one phrase in
  `## Interface_version 2 delivery relay`)
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
  (`## 5. Final report`, the re-entry-line clause)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (two
  new methods, and one more entry in the identity test's tuple)

**Interfaces:**
- Consumes (Task 1): `agent_dispatch` is not auto-resumable, so a sweep with
  `human_directed: false` leaves it parked.
- Consumes (Task 3): `SKILL.md`'s `**Dispatch-gap fallback.**` paragraph in
  Phase 7, and its suspension on a genuine gap.
- Consumes (Task 2): `CAPABILITY_GAP_LINE`, and the identity test's tuple, which
  after Task 3 lists ship-issue/SKILL.md, from-issue/ship-handoff.md and
  from-issue/SKILL.md.
- Produces: nothing code consumes.

**Invariants:**
- `#### Fresh delegated owner` keeps "fresh Phase-7 ship owner" and "must not
  dispatch a second issue owner" in their pinned order, and names the fallback
  after them. It still never spells `workflow-state suspend` (D5).
- AUTO.md still names `blocked_on: human_gate` exactly twice, and `human_gate`
  stays the only value that `blocked_on[:=] ?\w+` finds in it, so
  `test_auto_gate_enumeration_covers_an_unguarded_host` stays green. The new
  suspension-line exception spells `blocked_on=<value>`, which that pattern does
  not match.
- `#### Earlier controller stop` keeps "post-delegation action set is exactly
  validate, relay, and stop", its seven "does not" denials, "dispatch failure"
  and "never permission to implement locally". It also keeps the order
  "received bytes" → `artifact-budget validate-report --boundary workflow-response`
  → "relay the canonical bytes unchanged" → "stop", and gains no affirmative
  permission. The existing
  `test_direct_auto_phase_five_rolls_to_one_fresh_implementation_owner` stays
  green unchanged (D10).
- No AUTO.md sentence calls the Phase-7 summary "the ship owner's" (D14).
- The orchestrate report keeps its expiry paragraph and its pinned order
  unchanged. Only the re-entry-line clause changes.
- No new line contains `Agent(`, and no new fence is added.

- [ ] **Step 1: Confirm the gate fails at the start**

```bash
set -uo pipefail
A=home/common/agent-skills/skills/from-issue/AUTO.md
O=home/common/claude-code/skills/orchestrate-issues/SKILL.md
grep -c 'dispatch-gap fallback\|capability_gap' $A
grep -c "ship owner's" $A
tr -s '[:space:]' ' ' < $O | grep -c 'for an issue suspended on a human gate'
```

Expected: `0`, then `3`, then `1`.

- [ ] **Step 2: Write the failing tests**

1. In `test_capability_gap_line_is_spelled_identically_everywhere`, add
   `            ("from-issue/AUTO.md", self.auto),` as a fourth tuple entry,
   directly after the `("from-issue/SKILL.md", self.from_issue),` line.
2. In `WorkflowSkillContractsTest`, directly above
   `    def test_auto_continuation_and_bookkeeper_are_interface_two(self):`,
   insert:

```python
    def test_auto_names_the_dispatch_gap_fallback_and_relays_closed_lines(self):
        # The rollover owner keeps its fresh Phase-7 ship owner and names the
        # one departure after it; the earlier controller relays a delegated
        # owner's re-entry or suspension line instead of mistaking it for a
        # dispatch failure (per D5, D10).
        delegated = normalized(self.section(
            self.auto, "#### Fresh delegated owner", "#### Earlier controller stop"))
        self.assert_ordered(
            delegated,
            "fresh Phase-7 ship owner",
            "must not dispatch a second issue owner",
            "Phase-7 dispatch-gap fallback",
            f"`{CAPABILITY_GAP_LINE}`",
            "After validating the ship report's `ship-summary/v2` bytes",
            "completed Phase 7",
            "with the validated ship summary inline",
        )
        self.assertNotIn("ship owner's `ship-summary/v2`", self.auto)
        self.assertNotIn("ship owner's validated summary", self.auto)
        earlier = normalized(self.section(
            self.auto, "#### Earlier controller stop", "### Other Phase 5–7 routes"))
        self.assert_ordered(
            earlier,
            "exactly validate, relay, and stop",
            "only the canonical re-entry line `/from-issue <num> --auto`",
            "only a canonical `Suspended (blocked_on=<value>). Resume: "
            "/from-issue <num> --auto` line",
            "relayed unchanged to its caller with no validation",
            "writes nothing",
            "Neither line is a dispatch failure.",
            "received bytes",
            "artifact-budget validate-report --boundary workflow-response",
            "relay the canonical bytes unchanged",
        )

    def test_orchestrate_report_names_every_cause_a_label_sweep_leaves_parked(self):
        # A label or milestone sweep never resumes these causes, so the
        # per-issue re-entry line is the instruction that works (per D10).
        final = normalized(self.section(
            self.orchestrate, "## 5. Final report", "## Notes"))
        self.assert_ordered(
            final,
            "`/from-issue <issue> --auto` for an issue suspended on a cause",
            "`--label` or `--milestone` sweep does not resume",
            "`human_gate`", "`external`", "`agent_dispatch`",
            "the orchestrate re-invocation itself",
        )
        self.assertNotIn("for an issue suspended on a human gate", final)
```

- [ ] **Step 3: Run the tests and watch them fail**

```bash
set -uo pipefail
T=home/common/agent-skills/tests
PYTHONPATH=python python3 -m unittest $T/test_workflow_skill_contracts.py \
  -k relays_closed_lines -k label_sweep_leaves_parked -k spelled_identically 2>&1 \
  | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED' | cut -c1-120
```

Expected: `Ran 3 tests` and `FAILED (failures=3)`: the two new tests, and the
identity test's new `from-issue/AUTO.md` subtest.

- [ ] **Step 4: Edit the two documents**

Every block nested in a numbered item below is indented three spaces only
because it sits in the list. Strip exactly those three spaces; any further
indentation is the file's own.

1. In `$A` `#### Fresh delegated owner`, replace exactly
   ```
   `auto: true`; it must not dispatch a second issue owner.

   After validating the ship owner's `ship-summary/v2` bytes, call
   ```
   with the lines below. The gap line in backticks stays whole on one line, and
   the text says `SKILL.md`'s suspension, never the verb or a `blocked_on` value:
   ```
   `auto: true`; it must not dispatch a second issue owner. The one allowed
   departure is `SKILL.md`'s Phase-7 dispatch-gap fallback: when that ship owner
   returns `capability_gap: agent_dispatch`, or this context cannot launch it,
   ship inline exactly as Phase 7 says, including its suspension on a genuine gap.

   After validating the ship report's `ship-summary/v2` bytes, call
   ```
2. In the same section, replace
   `with the ship owner's validated summary inline in its quoted heredoc and its`
   with
   `with the validated ship summary inline in its quoted heredoc and its`.
3. In `## Interface_version 2 delivery relay`, replace
   ``object in the continuation, the ship owner's `ship-summary/v2` into `finish`,``
   with
   ``object in the continuation, the ship report's `ship-summary/v2` into `finish`,``.
4. In `#### Earlier controller stop`, replace exactly
   ```
   post-delegation action set is exactly validate, relay, and stop. The
   received bytes are the delegated owner's durable `finish` reply, a workflow
   response, so run `artifact-budget validate-report --boundary workflow-response`
   ```
   with
   ```
   post-delegation action set is exactly validate, relay, and stop. Two closed
   line exceptions are matched byte for byte first: a return that is only the
   canonical re-entry line `/from-issue <num> --auto`, and a return that is only a
   canonical `Suspended (blocked_on=<value>). Resume: /from-issue <num> --auto`
   line. Each is relayed unchanged to its caller with no validation, the earlier
   controller writes nothing, and it stops. Neither line is a dispatch failure.
   Otherwise the received bytes are the delegated owner's durable `finish` reply,
   a workflow response, so run `artifact-budget validate-report --boundary workflow-response`
   ```
   The line after it (`over them; after successful validation, relay the
   canonical bytes unchanged to`) and the seven denials are unchanged.
5. In `$O` `## 5. Final report`, replace exactly
   ```
   `/from-issue <issue> --auto` for an issue suspended on a human gate, and the
   orchestrate re-invocation itself for the whole run — every column sourced from
   ```
   with
   ```
   `/from-issue <issue> --auto` for an issue suspended on a cause that a `--label`
   or `--milestone` sweep does not resume (`human_gate`, `external` or
   `agent_dispatch`), and the orchestrate re-invocation itself for the whole run —
   every column sourced from
   ```
   The rest of that paragraph is unchanged.

- [ ] **Step 5: Verify the documents**

```bash
set -euo pipefail
T=home/common/agent-skills/tests; A=home/common/agent-skills/skills/from-issue/AUTO.md
O=home/common/claude-code/skills/orchestrate-issues/SKILL.md
if grep -qF "ship owner's" $A; then exit 1; fi
if awk '/^#### Fresh delegated owner/,/^#### Earlier controller stop/' $A | grep -qF 'workflow-state suspend'; then exit 1; fi
if git diff HEAD -U0 -- $A $O | grep -E '^\+' | grep -qF 'Agent('; then exit 1; fi
PYTHONPATH=python python3 -m unittest $T/test_workflow_skill_contracts.py $T/test_dispatch_contracts.py \
  $T/test_shell_example_contracts.py $T/test_agent_model_matrix.py 2>&1 \
  | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
```

Expected: the three prohibitions pass silently. The four suites together show
`Ran 224 tests` and `OK (skipped=3)`, which is the base count of 217 plus this
plan's 7 skill-contract tests. A sync merge that adds tests raises it.

- [ ] **Step 6: Final gate**

```bash
set -euo pipefail
LOG="${TMPDIR:-/tmp}"; LOG="${LOG%/}/issue-198-build.log"
WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
PYTHONPATH=python python3 -m agent_tools.agent_model_matrix validate
if just build > "$LOG" 2>&1; then echo build-ok; else grep -E 'error:' "$LOG" | head -20; exit 1; fi
git status --short
```

Expected: `Ran 1326 tests …` and `OK (skipped=4)`. That is the base count of
1316 at `17da7f2` plus this plan's 3 workflow-state tests and 7 skill-contract
tests, and it grows only if a sync merge adds tests.
The four skips are the installed-tree and pre-activation checks, which this
invocation leaves out by design. `WORKFLOW_POLICY_SURFACE=source` is the
spelling CI uses. Without it, `test_installed_policy_surface_matches_source_contract`
reads this machine's activated `~/.agents/skills`, which predates the branch.
The suite takes about 9 minutes. Next comes `agent model matrix: valid`, then
`build-ok`. `git status --short` shows only this task's three files before the
commit. Summarize any failure to its test ids or `error:` lines. Never run
`just switch`.

- [ ] **Step 7: Commit**

```bash
set -euo pipefail
T=home/common/agent-skills/tests; A=home/common/agent-skills/skills/from-issue/AUTO.md
O=home/common/claude-code/skills/orchestrate-issues/SKILL.md
git add $A $O $T/test_workflow_skill_contracts.py
git commit -m "feat(from-issue): relay the dispatch-gap outcome through every caller" \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013ho926R9qjak8E3fLvEdq6"
```
