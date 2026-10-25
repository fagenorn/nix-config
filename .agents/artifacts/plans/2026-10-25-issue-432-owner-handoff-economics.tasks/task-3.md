# Task 3: The policy home — `PhaseBudget`, `AGENT_PHASE_BUDGET` and a phase-aware meter

Spec § Policy home and test seams 3–5; per D6 and D21. Today `phase_budget` is four constants: the gate reads them as argparse defaults, and the meter hands off at `CONTEXT_CEILING - CONTEXT_HEADROOM`. This task makes it one frozen `PhaseBudget` with a per-phase hand-off threshold, a knob grammar and an environment override for eval arms. It moves `select_phase_action` in unchanged and makes the gate and the meter read the threshold of the phase being entered. With the defaults (110,000 for every phase) no behaviour changes. The replay (Task 4) and the harness (Task 5) import this module.

**Files:**
- Modify: `python/agent_tools/phase_budget.py` (rewrite)
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`select_phase_action` deleted and imported from `phase_budget`; `progress`'s four budget flags default to `None` and are resolved in `command_progress`)
- Modify: `python/agent_tools/context_meter.py` (`respond(payload, *, state_dir, budget)`; `main` passes `phase_budget.current()`; the crossing note names the threshold used)
- Modify: `python/agent_tools/context_meter_crossing.py` (the record gains `phase`; old two-key records are accepted)
- Create: `tests/test_phase_budget.py`
- Modify: `tests/test_context_meter.py`, `home/common/agent-skills/tests/test_workflow_state.py`
- Modify: `justfile` (add `tests/test_phase_budget.py` to `agent-workflow-tests`, before `tests/test_context_meter.py`)
- Modify: `python/README.md` (§ `context-meter`: threshold, phase and state paragraphs), `home/common/claude-code/README.md` (§ Context meter: the threshold sentence)

**Interfaces:**
- Consumes: Task 2's `context_meter_commands.invocations` (to read `--phase` and the registering helper).
- Produces:

```python
@dataclass(frozen=True)
class PhaseBudget:
    turn_ceiling: int = 120
    turn_headroom: int = 2
    context_headroom: int = 10_000
    threshold: int = 110_000                                  # every phase, and an unknown phase
    phase_thresholds: tuple[tuple[int, int, int], ...] = ()   # (first, last, tokens); a later entry wins
    guard: int = 0
    cap: int | None = None

ENVIRONMENT = "AGENT_PHASE_BUDGET"
PRODUCT_KNOBS = frozenset({"threshold"})
REPLAY_KNOBS = frozenset({"threshold", "guard", "cap"})

def parse(spec: str, *, knobs: frozenset[str] = PRODUCT_KNOBS) -> PhaseBudget: ...
def current() -> PhaseBudget: ...                      # functools.cache: read once per process
def handoff_threshold(budget: PhaseBudget, phase: int | None) -> int: ...
def crossing_threshold(budget: PhaseBudget, phase: int | None, baseline: int | None) -> int: ...
def select_phase_action(*, direct, turn_count, context_tokens, turn_ceiling, context_ceiling,
                        turn_headroom, context_headroom, next_needs_context,
                        artifacts_sufficient, remainder_self_contained) -> str: ...  # moved verbatim
```

**Invariants (per D21):**
- Grammar: `spec` is one or more items separated by `,`. Each item is `key=value`, where `key` is `threshold`, `threshold:<a>-<b>` (integers with `0 ≤ a ≤ b ≤ 7`), `guard` or `cap`, and `value` is a decimal integer: `threshold` ≥ 1, `guard` ≥ 0, `cap` ≥ 1. Ranged items append to `phase_thresholds` in order. A non-ranged key given twice, an empty item, a key outside `knobs` (`guard` and `cap` are outside `PRODUCT_KNOBS`) or a bad value raises `ValueError` whose message names the item.
- `handoff_threshold(b, p)`: the last `phase_thresholds` entry covering `p`, else `b.threshold`; `p is None` → `b.threshold`.
- `crossing_threshold(b, p, baseline)`: `handoff_threshold(b, p)`, raised to `baseline + b.guard` when `b.guard > 0` and `baseline is not None`.
- `current()`: `PhaseBudget()` when `AGENT_PHASE_BUDGET` is unset, else `parse(<value>)` (product knobs), so an empty or invalid value raises. Production never sets it (D6).
- `select_phase_action` moves byte-for-byte; `workflow-state` imports it from `phase_budget` and keeps no copy.
- `progress`: `--turn-ceiling`, `--context-ceiling`, `--turn-headroom` and `--context-headroom` default to `None`. Explicit values win. Otherwise, with `b = current()`: `turn_ceiling = b.turn_ceiling`, `turn_headroom = b.turn_headroom`, `context_headroom = b.context_headroom`, and `context_ceiling = handoff_threshold(b, args.phase + 1) + b.context_headroom`. The ceiling uses the default headroom even when `--context-headroom` is explicit, so `--context-headroom 5000` alone still means a ceiling of 120,000. The recorded `phase_inputs` hold the resolved integers, in the same shape as today.
- Meter state record: exactly `{"notified", "owner"}` (a record written before this change) or `{"notified", "owner", "phase"}`, with `phase` an int 0–8 or `null`. Every write uses the three-key form. Any other shape raises as today.
- Meter phase update, applied under the lock before the crossing decision. A call holding progress invocations sets `phase` to the last invocation's `--phase` + 1 when that value is a decimal integer. A registering `sdd-gate` or `mark-progress` call sets `phase` to 6 when it is `null`. Nothing else changes it.
- Meter threshold: `crossing_threshold(budget, record["phase"], None)`. The re-arm rule is unchanged, with "below the threshold" read against that same value. `CROSSING_NOTE` keeps its text and is formatted with that value.

- [ ] **Step 1: Write the failing tests**

`tests/test_phase_budget.py`:

```python
"""agent_tools.phase_budget: the one home of the phase-gate budget (issue 432)."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

from agent_tools import phase_budget
from agent_tools.phase_budget import PhaseBudget, crossing_threshold, handoff_threshold, parse


class GrammarTest(unittest.TestCase):
    def test_defaults_hand_off_at_110000_in_every_phase(self):
        budget = PhaseBudget()
        self.assertEqual([handoff_threshold(budget, p) for p in (None, 0, 5, 6, 7)], [110_000] * 5)
        self.assertEqual((budget.turn_ceiling, budget.turn_headroom, budget.context_headroom,
                          budget.guard, budget.cap), (120, 2, 10_000, 0, None))

    def test_a_base_threshold_and_a_later_range_win(self):
        budget = parse("threshold=140000,threshold:6-7=170000,threshold:7-7=200000")
        self.assertEqual([handoff_threshold(budget, p) for p in (None, 0, 5, 6, 7)],
                         [140_000, 140_000, 140_000, 170_000, 200_000])

    def test_bad_items_raise_naming_the_item(self):
        for spec in ("", "threshold=", "threshold=0", "threshold=9x", "threshold:3-1=5",
                     "threshold:0-8=5", "threshold=1,threshold=2", "boot=slim", "guard=40000",
                     "cap=2", "threshold=1,,cap=2"):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                parse(spec)

    def test_replay_knobs_accept_guard_and_cap(self):
        budget = parse("guard=40000,cap=2", knobs=phase_budget.REPLAY_KNOBS)
        self.assertEqual((budget.guard, budget.cap), (40_000, 2))
        with self.assertRaises(ValueError):
            parse("cap=0", knobs=phase_budget.REPLAY_KNOBS)

    def test_the_guard_raises_the_crossing_above_baseline(self):
        guarded = parse("guard=40000", knobs=phase_budget.REPLAY_KNOBS)
        self.assertEqual(crossing_threshold(guarded, 6, 98_000), 138_000)
        self.assertEqual(crossing_threshold(guarded, 6, 29_000), 110_000)
        self.assertEqual(crossing_threshold(guarded, 6, None), 110_000)
        self.assertEqual(crossing_threshold(PhaseBudget(), 6, 98_000), 110_000)


class EnvironmentTest(unittest.TestCase):
    def current_in_child(self, value):
        env = {key: val for key, val in os.environ.items() if key != phase_budget.ENVIRONMENT}
        if value is not None:
            env[phase_budget.ENVIRONMENT] = value
        return subprocess.run(
            [sys.executable, "-c", "from agent_tools import phase_budget as p; "
             "b = p.current(); print(p.handoff_threshold(b, 6), p.handoff_threshold(b, 1))"],
            capture_output=True, text=True, env=env, check=False)

    def test_unset_is_the_default(self):
        self.assertEqual(self.current_in_child(None).stdout.split(), ["110000", "110000"])

    def test_the_override_uses_the_same_grammar(self):
        out = self.current_in_child("threshold=90000,threshold:6-7=170000")
        self.assertEqual(out.stdout.split(), ["170000", "90000"])

    def test_an_invalid_override_raises(self):
        out = self.current_in_child("threshold=lots")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("ValueError", out.stderr)


class MovedGateTest(unittest.TestCase):
    def test_workflow_state_holds_no_copy_of_select_phase_action(self):
        script = (Path(__file__).resolve().parents[1]
                  / "home/common/agent-skills/scripts/workflow-state.py")
        text = script.read_text(encoding="utf-8")
        self.assertNotIn("def select_phase_action", text)
        self.assertIn("select_phase_action", text)
```

In `home/common/agent-skills/tests/test_workflow_state.py`:
- Move `select_phase_action`'s existing table test(s) to call `phase_budget.select_phase_action` (find them with `rg -n "select_phase_action" home/common/agent-skills/tests`). Every case and expected action stays unchanged.
- Rewrite `PhaseBudgetDefaultsTest.test_the_four_defaults_have_one_home`: the parsed `MINIMAL` args have `None` for the four flags, and the AST walk finds `default` unparsed as `None` for each of `BUDGET_FLAGS`.
- Keep `test_default_ceiling_hands_off_at_110000_and_continues_at_109999` unchanged; it must still pass.
- Add a test, in the style of the existing one with the same `init_run`/`spawn`/`progress` helpers, that sets `AGENT_PHASE_BUDGET=threshold=110000,threshold:2-2=140000` in the environment the harness passes to the script. Find how `LifecycleHarness.progress` runs it and extend that helper with an `env` keyword if it has none. Then `progress --phase 1 --context-tokens 120000` answers `continue`, because Phase 2's threshold is 140,000, and `--phase 2` with 120,000 answers `handoff`, because Phase 3's is 110,000. The recorded `phase_inputs.context_ceiling` of the first is `150000`.

In `tests/test_context_meter.py`, extend `MeterHarness.run_meter` with `env: dict | None = None`, merged into the subprocess environment, and add to `CrossingTest`. `call` passes `env` through, and `MARK`/`CROSSING` are its existing constants. `CROSSING` is formatted with a threshold of 110000; generalise it to take the threshold if it does not already.

```python
    def test_the_crossing_uses_the_override(self):
        env = {"AGENT_PHASE_BUDGET": "threshold=90000"}
        self.assertIsNone(self.call(85000, MARK, env=env))
        self.assertEqual(self.call(95000, env=env), CROSSING_AT(95000, 90000))

    def test_the_crossing_follows_the_owner_phase(self):
        env = {"AGENT_PHASE_BUDGET": "threshold=110000,threshold:6-7=170000"}
        self.assertIsNone(self.call(100000, PROGRESS_PHASE_5, env=env))   # registers; phase 6
        self.assertIsNone(self.call(150000, env=env))
        self.assertEqual(self.call(171000, env=env), CROSSING_AT(171000, 170000))

    def test_an_old_two_key_record_is_accepted_and_upgraded(self):
        state = self.home / ".agents" / "state" / "context-meter"
        state.mkdir(parents=True)
        path = state / f"{SESSION}.agent-{AGENT}.json"
        path.write_text('{"notified": false, "owner": true}', encoding="utf-8")
        self.assertEqual(self.call(112000), CROSSING_AT(112000, 110000))
        self.assertEqual(json.loads(path.read_text()), {"notified": True, "owner": True, "phase": None})
```

Here `CROSSING_AT(tokens, threshold)` is `context_meter.CROSSING_NOTE.format(tokens=tokens, threshold=threshold)`. `PROGRESS_PHASE_5` is a registering `workflow-state progress … --action-id 7:1:1 --phase 5 …` command built like the module's existing progress commands. The registering call itself is a progress call the meter rewrites, so it is never due.

- [ ] **Step 2: Run the tests and watch them fail**

Run: **Meter and policy tests**, then **Gate tests** naming only `test_workflow_state.py`.
Expected: FAIL — `ImportError: cannot import name 'PhaseBudget'`; then the moved-gate, default-`None` and override tests fail.

- [ ] **Step 3: Implement** to the interfaces and invariants above. `phase_budget`'s docstring states the grammar, the override and "production never sets it". `context_meter_crossing.record(directory, identity, *, register, measured, progress, phase_update: int | None, sets_phase_six: bool, budget: PhaseBudget) -> tuple[bool, int]` returns whether the crossing is due and the threshold used, computing the threshold under the lock from the updated record. `context_meter.respond` derives `phase_update` and `sets_phase_six` from `invocations(tokens)` (an untokenisable call sets neither). Update both READMEs' threshold sentences to say "`phase_budget.crossing_threshold(current(), phase)`, 110,000 for every phase unless `AGENT_PHASE_BUDGET` overrides it", and the state paragraph's record shape.

- [ ] **Step 4: Verify**

Run: **Meter and policy tests**, then **Gate tests**.
Expected: `OK` from both.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/phase_budget.py home/common/agent-skills/scripts/workflow-state.py \
  python/agent_tools/context_meter.py python/agent_tools/context_meter_crossing.py \
  tests/test_phase_budget.py tests/test_context_meter.py \
  home/common/agent-skills/tests/test_workflow_state.py justfile python/README.md \
  home/common/claude-code/README.md
launch-commit … -- -m "feat(phase-budget): one PhaseBudget with per-phase thresholds and an eval override (issue 432)"
```
