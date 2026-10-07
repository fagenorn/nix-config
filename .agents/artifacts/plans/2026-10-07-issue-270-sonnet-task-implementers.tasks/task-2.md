# Task 2: Marked Sonnet fix re-dispatch and Opus escalations

Per D2 and D6. Makes the two today-unmarked fallback dispatches explicit and words
the fix loop's escalation as Sonnet → Opus.

**Files:**
- Modify: `home/common/agent-skills/model-matrix.json` (two new `dispatch_sites` rows)
- Modify: `home/common/agent-skills/skills/sdd/fix-loop.md` (the five-round list, lines 7–26)
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md` (the `**BLOCKED**` bullet of `### 2. Handle the report`, and the fix-loop summary sentence under the review step)
- Modify: `home/common/agent-skills/instruction-load.json` (one launch id, one new profile, ceilings)
- Test: `home/common/agent-skills/tests/test_agent_model_matrix.py`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Task 1): role `task-implementer` (sonnet/high on subagent type `implementer`); `EXPECTED_SDD_SITES`; `test_task_implementer_is_a_sonnet_role_on_the_opus_implementer_type`, whose two `by_role` set assertions this task extends.
- Produces: site `sdd-task-fix-redispatch` (`task-implementer`, `sdd/fix-loop.md`); site `sdd-blocked-reasoning-escalation` (`implementer`, `sdd/SKILL.md`); instruction-load profile `sdd-blocked-escalation-implementer`; test class `SonnetTaskImplementerContractsTest` in `test_workflow_skill_contracts.py`, which Task 3 extends.

**Invariants:**
- Each new marker line is immediately followed by its call line; each call line occurs exactly once in its file, and no other new line contains `Agent(`.
- Rounds 1–3 still resume the original implementer first; the fresh re-dispatch is only for "cannot be resumed".
- Round 4 (both arms), round 5 and the reasoning-problem BLOCKED re-dispatch are `implementer` on Opus/high; a context-problem BLOCKED still re-dispatches at the same tier.
- Every matrix site is claimed by exactly one instruction-load profile.
- These existing pinned strings survive: `resume the original implementer` (fix-loop), `Record the implementer's agent identity — fix rounds 1–3 resume it` (SKILL.md), and the `Every round: the implementer fixes, …` paragraph.

- [ ] **Step 1: Write the failing tests**

In `test_agent_model_matrix.py`, add to `EXPECTED_SDD_SITES`:

```python
    "sdd-task-fix-redispatch": (
        "home/common/agent-skills/skills/sdd/fix-loop.md",
        "task-implementer",
        "sonnet",
        "high",
        [],
    ),
    "sdd-blocked-reasoning-escalation": (
        "home/common/agent-skills/skills/sdd/SKILL.md",
        "implementer",
        "opus",
        "high",
        [],
    ),
```

and in `test_task_implementer_is_a_sonnet_role_on_the_opus_implementer_type` replace the two `by_role` assertions with:

```python
        self.assertEqual(
            by_role["task-implementer"],
            {"sdd-nonmechanical-implementation", "sdd-task-fix-redispatch"},
        )
        self.assertEqual(
            by_role["implementer"],
            {
                "sdd-post-rescue-implementation",
                "sdd-rescue-fallback-implementation",
                "sdd-round-five-implementation",
                "sdd-blocked-reasoning-escalation",
                "sdd-final-review-fixer",
            },
        )
```

In `test_workflow_skill_contracts.py`, add this class directly before `class LaunchFencedWorkerContractsTest`:

```python
class SonnetTaskImplementerContractsTest(unittest.TestCase):
    """#270: Sonnet task implementers; stuck tasks escalate to Opus (D1, D2)."""

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def read(path):
        return normalized(path.read_text(encoding="utf-8"))

    def test_the_fix_loop_escalates_a_sonnet_implementer_to_opus(self):
        self.assert_ordered(
            self.read(SDD_DIR / "fix-loop.md"),
            "**Rounds 1–3 — resume the original implementer**",
            "it keeps the Sonnet/high tier it was launched with",
            "<!-- agent-dispatch: id=sdd-task-fix-redispatch role=task-implementer "
            "model=sonnet effort=high -->",
            "**Round 4 — the stuck-breaker.**",
            "The original implementer ran on Sonnet/high, so from here every fix "
            "dispatch escalates to Opus/high — a model change, not only a fresh context.",
            "then escalate to a fresh Opus/high implementer:",
            "id=sdd-post-rescue-implementation role=implementer model=opus",
            "Codex unavailable → the same Opus/high escalation",
            "id=sdd-rescue-fallback-implementation role=implementer model=opus",
            "**Round 5 — last round**, still on Opus/high",
            "id=sdd-round-five-implementation role=implementer model=opus")

    def test_a_reasoning_problem_blocked_escalates_to_opus(self):
        sdd = self.read(SDD)
        self.assert_ordered(
            sdd, "### 2. Handle the report", "**BLOCKED**",
            "context problem: add context, re-dispatch at the same tier",
            "Reasoning problem: escalate to a fresh Opus/high implementer",
            "<!-- agent-dispatch: id=sdd-blocked-reasoning-escalation role=implementer "
            "model=opus effort=high -->",
            "Too large: split it.")
        self.assertNotIn("or bump the model", sdd)
        self.assertIn("round 4 is the Codex-assisted stuck-breaker and round 5 the "
                      "final fresh dispatch, both on Opus/high", sdd)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_workflow_skill_contracts.py -k task_implementer -k sdd_dispatches -k escalat 2>&1 | tail -5`
Expected: FAIL — the two new sites are missing from the matrix, and the fix-loop/BLOCKED anchors are absent.

- [ ] **Step 3: Implement**

1. `sdd/fix-loop.md`: replace the round-1–3 bullet and the round-4/round-5 prose so lines 7–26 read exactly as below (the existing `sdd-codex-rescue-transport`, `sdd-post-rescue-implementation`, `sdd-rescue-fallback-implementation` and `sdd-round-five-implementation` marker/call pairs are kept byte-for-byte):

```markdown
- **Rounds 1–3 — resume the original implementer** with the open findings verbatim; its context is intact, and it keeps the Sonnet/high tier it was launched with. Can't resume? Dispatch a fresh one at that same tier, carrying brief path, report path and findings — the report file is the persistent memory:

<!-- agent-dispatch: id=sdd-task-fix-redispatch role=task-implementer model=sonnet effort=high -->
Agent(subagent_type="implementer", model="sonnet", effort="high") takes over fix rounds 1–3 when the original task implementer cannot be resumed.
- **Round 4 — the stuck-breaker.** Three same-context rounds failing usually means the implementer cannot see its own problem, and another same-model retry re-runs the blindness. The original implementer ran on Sonnet/high, so from here every fix dispatch escalates to Opus/high — a model change, not only a fresh context. Use the bounded Codex transport with the failing command or test, the diff so far (`BASE..HEAD`), the brief and report paths, and the open findings:

<!-- agent-dispatch: id=sdd-codex-rescue-transport role=codex-transport model=sonnet effort=medium -->
Agent(subagent_type="codex:rescue", model="sonnet", effort="medium") transports the bounded stuck-breaker diagnosis to the external Codex runtime without selecting that runtime's model.

  **Verify its diagnosis against the live worktree before acting on it**, then escalate to a fresh Opus/high implementer:

<!-- agent-dispatch: id=sdd-post-rescue-implementation role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") applies the verified rescue diagnosis plus the open findings.

  Codex unavailable → the same Opus/high escalation, framed "a prior implementer attempted this task 3 times; you own it now — read the report file for what was tried":

<!-- agent-dispatch: id=sdd-rescue-fallback-implementation role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") owns the fresh-context rescue fallback.
- **Round 5 — last round**, still on Opus/high, same packet plus round 4's findings:

<!-- agent-dispatch: id=sdd-round-five-implementation role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") owns the fifth and final fix round.
```

2. `sdd/SKILL.md`, the `**BLOCKED**` bullet under `### 2. Handle the report` becomes exactly:

```markdown
- **BLOCKED** → a `launch fence refused` report follows `### Lifecycle workers` and is never re-dispatched. Otherwise: context problem: add context, re-dispatch at the same tier. Reasoning problem: escalate to a fresh Opus/high implementer carrying the brief path, the report path and the blocker:

<!-- agent-dispatch: id=sdd-blocked-reasoning-escalation role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") takes over a task whose implementer reported BLOCKED on a reasoning problem.

  Too large: split it. Plan wrong: escalate to the human. Never force an unchanged retry — if the implementer said it's stuck, something must change.
```

3. `sdd/SKILL.md`, in the fix-loop summary sentence (it begins `Triggers on spec ❌`), replace `round 4 is the Codex-assisted stuck-breaker, round 5 the final fresh dispatch)` with `round 4 is the Codex-assisted stuck-breaker and round 5 the final fresh dispatch, both on Opus/high)`.
4. `model-matrix.json` `dispatch_sites`: add, directly before the `sdd-codex-rescue-transport` row,

```json
    {
      "id": "sdd-task-fix-redispatch",
      "path": "home/common/agent-skills/skills/sdd/fix-loop.md",
      "marker": "<!-- agent-dispatch: id=sdd-task-fix-redispatch role=task-implementer model=sonnet effort=high -->",
      "call": "Agent(subagent_type=\"implementer\", model=\"sonnet\", effort=\"high\") takes over fix rounds 1–3 when the original task implementer cannot be resumed.",
      "role": "task-implementer",
      "model": "sonnet",
      "effort": "high",
      "requires": []
    },
```

   and directly after the `sdd-lane-task-verification` row,

```json
    {
      "id": "sdd-blocked-reasoning-escalation",
      "path": "home/common/agent-skills/skills/sdd/SKILL.md",
      "marker": "<!-- agent-dispatch: id=sdd-blocked-reasoning-escalation role=implementer model=opus effort=high -->",
      "call": "Agent(subagent_type=\"implementer\", model=\"opus\", effort=\"high\") takes over a task whose implementer reported BLOCKED on a reasoning problem.",
      "role": "implementer",
      "model": "opus",
      "effort": "high",
      "requires": []
    },
```

   Neither site is added to any `scenarios` trace (per D6).
5. `instruction-load.json`: prepend `"sdd-task-fix-redispatch"` to the `sdd-fix-implementer` profile's `launch` list, and insert directly after that profile:

```json
    {
      "id": "sdd-blocked-escalation-implementer",
      "launch": [
        "sdd-blocked-reasoning-escalation"
      ],
      "hosts": [
        "claude",
        "codex"
      ],
      "prompt": "sdd/SKILL.md",
      "hot": [
        "agents/implementer.md"
      ],
      "conditional": [],
      "unread": {},
      "ceiling_bytes": {
        "claude": 1370,
        "codex": 0
      },
      "note": "Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/SKILL.md's BLOCKED handling, whose leaf clauses #153 holds (#155 D5). Added for #270: the Opus escalation of a reasoning-problem BLOCKED (#270 D2)."
    },
```

6. Run the Global Constraints ceiling procedure; the note sentence is `Ceiling raised for #270: sdd's BLOCKED handling marks the Opus escalation and the fix-loop summary names Opus/high (#155 D10).`

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -3`
Expected: `OK`.

Run: `PYTHONPATH=python python3 -m agent_tools.agent_model_matrix validate --root .`
Expected: `agent model matrix: valid` (it rejects any unmarked `Agent(` line and any marker/call mismatch).

Run (fails at the base commit, where neither marker exists): `for f in fix-loop.md:sdd-task-fix-redispatch SKILL.md:sdd-blocked-reasoning-escalation; do grep -q "id=${f#*:} " "home/common/agent-skills/skills/sdd/${f%%:*}" || exit 1; done`
Expected: exit 0.

Run (skill files are part of the built home-manager tree): `just build` with an explicit timeout of 3000000 ms.
Expected: success.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/model-matrix.json home/common/agent-skills/skills/sdd/fix-loop.md \
  home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/instruction-load.json \
  home/common/agent-skills/tests/test_agent_model_matrix.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(sdd): mark the Sonnet fix re-dispatch and the Opus escalations (#270)"
```
