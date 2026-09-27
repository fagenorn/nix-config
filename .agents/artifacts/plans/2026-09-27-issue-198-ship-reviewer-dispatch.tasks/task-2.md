# Task 2: ship-issue probes reviewer dispatch before any write and returns the gap line

Decisions: D1 (a probe where the dispatch happens), D3 (placement, check and
exemptions), D4 (the closed line), D9 (one home, and the prose corrections), D12
(a Phase-5 failure after a passing probe keeps today's handling), D13 (a
capability test, never a host name). Spec §"The reviewer-dispatch probe", §"The
capability-gap line", §"Prose corrections". Work from the worktree root. Every
shell block starts with `set -euo pipefail` (`set -uo pipefail` in the
watch-it-fail steps) and these abbreviations, which the blocks below omit:

```bash
T=home/common/agent-skills/tests; K=home/common/agent-skills/skills
```

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md` (`## The flow`
  line 0, and the opening of `## Phase 0 — Pre-flight`)
- Modify: `home/common/agent-skills/skills/ship-issue/REVIEW.md` (the
  merge-delta paragraph's parenthetical)
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md` (task
  item 2 and the return contract, both inside the ship-owner prompt)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (one
  module constant and three new methods in `WorkflowSkillContractsTest`)

**Interfaces:**
- Consumes (Task 1): the `agent_dispatch` cause exists. This task writes only
  the gap line, not the cause.
- Produces, for Tasks 3 and 4:
  - The module constant `CAPABILITY_GAP_LINE = "capability_gap: agent_dispatch"`,
    placed directly above `INPUT_FLAG_RE = re.compile(` in the contract test
    module.
  - `test_capability_gap_line_is_spelled_identically_everywhere`, whose document
    tuple Tasks 3 and 4 each extend by one entry.
  - The Phase-0 anchor phrase `reviewer-dispatch probe`, which from-issue and
    REVIEW.md use to point at the probe.

**Invariants:**
- The probe is the first thing in Phase 0. Its paragraph says it precedes
  `## Delivery loop`'s synchronizing null-scope checkpoint, the Phase-1 sync
  and every forge, ledger or git write. Phase 0's four numbered checks keep
  their numbers and bytes.
- The probe tests for the capability, never for a host by name. It launches
  nothing, writes nothing and makes no trial dispatch. Remainder mode never
  probes (D3, D13).
- Every spelling of `capability_gap…` in each carrier is exactly
  `capability_gap: agent_dispatch` on one line (D4).
- ship-handoff.md keeps exactly one unlabeled fence, the ship-owner prompt, with
  both leaf-agent sentences inside it once. `## Remainder owner prompt` gains
  nothing (D9, D12).
- No new line contains the substring `Agent(`, and the new ship-issue fence is
  labeled `text`. ship-issue's `## Delivery loop`, `## Remainder mode` and every
  dispatch marker keep their bytes.

- [ ] **Step 1: Confirm the gate fails at the start**

```bash
set -uo pipefail
K=home/common/agent-skills/skills
grep -c 'capability_gap' $K/ship-issue/SKILL.md $K/from-issue/ship-handoff.md
grep -c 'Nested Agent calls are supported.' $K/from-issue/ship-handoff.md
tr -s '[:space:]' ' ' < $K/ship-issue/REVIEW.md | grep -c 'nested dispatch works even inside'
```

Expected: `…SKILL.md:0` and `…ship-handoff.md:0`, then `1` and `1`.

- [ ] **Step 2: Write the failing tests**

1. Directly above the line `INPUT_FLAG_RE = re.compile(` in
   `$T/test_workflow_skill_contracts.py`, insert these three module-level
   lines at column 0:
   ```python
   # The closed capability-gap line ship-issue returns when its Phase-0 probe finds
   # no subagent-launch tool, spelled once for the module (per D4).
   CAPABILITY_GAP_LINE = "capability_gap: agent_dispatch"
   ```
2. In `WorkflowSkillContractsTest`, directly above
   `    def test_auto_continuation_and_bookkeeper_are_interface_two(self):`,
   insert:

```python
    def test_ship_issue_probes_reviewer_dispatch_before_any_write(self):
        # The probe is Phase 0's first step, so a context that cannot launch
        # the reviewers stops before the synchronizing checkpoint, the Phase-1
        # sync and every other write (per D3, D13). It has one home (per D9).
        heading = "## Phase 0 — Pre-flight"
        phase_zero = self.section(self.ship_issue, heading, "## Phase 1")
        body = phase_zero[len(heading):].lstrip()
        self.assertTrue(body.startswith("**Reviewer-dispatch probe"), body[:80])
        self.assert_ordered(
            normalized(phase_zero),
            "Reviewer-dispatch probe",
            "synchronizing null-scope checkpoint",
            "the Phase-1 sync",
            "`ToolSearch` `select:Agent`",
            "never a host by name",
            "launches nothing, writes nothing",
            "Remainder mode skips",
            CAPABILITY_GAP_LINE,
            "Standalone",
            "git rev-parse --git-common-dir",
        )
        review = normalized(self.ship_review)
        self.assertNotIn("nested dispatch works even inside", review)
        self.assertNotIn("ToolSearch", review)
        self.assertIn("Phase-0 reviewer-dispatch probe", review)

    def test_ship_handoff_returns_the_gap_line_before_either_loop_exit(self):
        # The prompt stops promising nested dispatch, points at the probe, and
        # returns the closed gap line before the two exits that end the
        # Delivery loop (per D4, D9).
        self.assertNotIn("Nested Agent calls are supported.", self.ship_handoff)
        prompt = normalized(self.ship_handoff.split("## Inline fallback", 1)[0])
        self.assert_ordered(
            prompt,
            "reviewer subagents",
            "Phase-0 reviewer-dispatch probe confirms",
            "Return exactly canonical JSON",
            f"return only `{CAPABILITY_GAP_LINE}`",
            "Two exceptions end the loop without a summary",
        )
        remainder = self.ship_handoff.split("## Remainder owner prompt", 1)[1]
        self.assertNotIn("capability_gap", remainder)

    def test_capability_gap_line_is_spelled_identically_everywhere(self):
        # One closed line, compared byte for byte and never decoded: every
        # spelling in every carrier is exactly that line (per D4).
        for name, text in (
            ("ship-issue/SKILL.md", self.ship_issue),
            ("from-issue/ship-handoff.md", self.ship_handoff),
        ):
            with self.subTest(document=name):
                self.assertIn(CAPABILITY_GAP_LINE, text)
                self.assertEqual(
                    set(re.findall(r"capability_gap[^`\n]*", text)),
                    {CAPABILITY_GAP_LINE},
                )
```

- [ ] **Step 3: Run the tests and watch them fail**

```bash
set -uo pipefail
T=home/common/agent-skills/tests
PYTHONPATH=python python3 -m unittest $T/test_workflow_skill_contracts.py -k gap -k probes_reviewer 2>&1 \
  | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED' | cut -c1-120
```

Expected: `Ran 3 tests` and `FAILED (failures=4)`. The identity test fails once
per document subtest, and the probe and handoff tests fail once each.

- [ ] **Step 4: Edit the three documents**

Every block nested in a numbered item below is indented three spaces only
because it sits in the list. Strip exactly those three spaces; any further
indentation is the file's own.

1. In `$K/ship-issue/SKILL.md` `## The flow`, replace the line
   `0. Pre-flight              → worktree clean, branch pattern ok, no PR yet`
   with
   `0. Pre-flight              → dispatch probe, worktree clean, branch pattern ok, no PR yet`.
2. In `$K/ship-issue/SKILL.md`, replace exactly
   ```
   ## Phase 0 — Pre-flight

   Verify the workspace is shippable before doing anything destructive:
   ```
   with the text between the two `~~~` markers below. The markers are not part
   of the text. The inner fence is a literal `text`-labeled Markdown fence.

   ~~~
   ## Phase 0 — Pre-flight

   **Reviewer-dispatch probe — first, before any write.** This is Phase 0's first
   step. It runs after entry validation and before the four checks below, and so
   before `## Delivery loop`'s synchronizing null-scope checkpoint, the Phase-1
   sync, and every forge, ledger or git write. Confirm that this context can launch
   the subagents this skill's reviewer dispatch sites name: the subagent-launch
   tool is in your tool surface, or, on a host that defers tool schemas, its tool
   search returns that tool's schema (Claude Code: `ToolSearch` `select:Agent`).
   Test the capability, never a host by name. The probe launches nothing, writes
   nothing and makes no trial dispatch. It proves the tool is present, not that a
   later launch will succeed: a Phase-5 launch that fails after a passing probe
   keeps its existing failure handling. It runs in every review-bearing
   invocation — a `ship-handoff/v2` or legacy handoff, or a standalone
   `/ship-issue <num>` — even when the merge delta may turn out empty, because the
   delta is unknown until the sync this probe precedes. Remainder mode skips
   Phases 0–5 and never probes.

   When the probe fails, stop with nothing launched or written. From a handoff,
   your whole return is exactly this closed line, with no ship summary and no
   validation:

   ```text
   capability_gap: agent_dispatch
   ```

   Standalone, tell the user the probe found no subagent-launch tool, end with that
   same line, and stop, keeping the worktree.

   Then verify the workspace is shippable before doing anything destructive:
   ~~~

   Leave the four numbered checks and the "Any failure: pause, ground, surface"
   line after them byte-identical.
3. In `$K/ship-issue/REVIEW.md`, replace exactly
   ```
   merge-delta reviewer over only that delta (nested dispatch works even inside an
   `Agent` subagent; if `Agent` isn't in your tool surface, `ToolSearch`
   `select:Agent` first), with Phase 1's scope-creep categories (retirement /
   ```
   with
   ```
   merge-delta reviewer over only that delta (SKILL.md's Phase-0 reviewer-dispatch
   probe has already confirmed this context can launch it), with Phase 1's
   scope-creep categories (retirement /
   ```
   The rest of that paragraph is unchanged.
4. In `$K/from-issue/ship-handoff.md`, inside the ship-owner prompt, replace
   exactly these two lines, which the file indents by five spaces:
   ```
        zero (empty merge-delta), one, or two reviewer subagents.
        Nested Agent calls are supported.
   ```
   with
   ```
        zero (empty merge-delta), one, or two reviewer subagents. Before that,
        ship-issue's Phase-0 reviewer-dispatch probe confirms that this context
        can launch them.
   ```
5. In the same prompt, directly after the line
   ``Return exactly canonical JSON from `artifact-budget validate-report --boundary ship-summary`.``
   insert these four lines. Keep the backticked gap line whole on its own line:
   ```
   One exception comes first, before any change: when ship-issue's Phase-0
   reviewer-dispatch probe reports the capability gap, nothing was launched or
   written, so with or without lifecycle identity return only
   `capability_gap: agent_dispatch`.
   ```
   The `With a ship-handoff/v2, validate…` sentence, the "Two exceptions end the
   loop without a summary" sentence and everything after them are unchanged.

- [ ] **Step 5: Verify**

```bash
set -euo pipefail
T=home/common/agent-skills/tests; K=home/common/agent-skills/skills
if grep -qF 'Nested Agent calls are supported.' $K/from-issue/ship-handoff.md; then exit 1; fi
if grep -qF 'ToolSearch' $K/ship-issue/REVIEW.md; then exit 1; fi
if git diff HEAD -U0 -- $K | grep -E '^\+' | grep -qF 'Agent('; then exit 1; fi
if git diff --quiet HEAD -- $K/ship-issue/HUMAN-GATE.md; then echo human-gate-untouched; else exit 1; fi
PYTHONPATH=python python3 -m unittest $T/test_workflow_skill_contracts.py $T/test_dispatch_contracts.py \
  $T/test_shell_example_contracts.py $T/test_agent_model_matrix.py 2>&1 \
  | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
PYTHONPATH=python python3 -m agent_tools.agent_model_matrix validate
```

Expected: the three prohibitions pass silently. Then `human-gate-untouched`, and
the four suites together end `OK (skipped=3)` with 3 more tests than at the
start of this task. Last comes `agent model matrix: valid`.

- [ ] **Step 6: Commit**

```bash
set -euo pipefail
T=home/common/agent-skills/tests; K=home/common/agent-skills/skills
git add $K/ship-issue/SKILL.md $K/ship-issue/REVIEW.md $K/from-issue/ship-handoff.md \
  $T/test_workflow_skill_contracts.py
git commit -m "feat(ship-issue): probe reviewer dispatch before any write" \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013ho926R9qjak8E3fLvEdq6"
```
