# Task 4: The replay, the sweep and the keep rule

Spec § The replay and test seam 2; per D5, D7, D8, D18 and D21. It adds `--policy NAME=SPEC` (repeatable) and `--sweep` to `--report owners`. Each arm replays every lineage in scope under a counterfactual hand-off policy, using a shift model, and is compared with the baseline-policy replay on paired per-lineage savings. `--sweep` runs D18's coordinate pass and marks each candidate `keep` or `reject` (D8). This is AC3's dry-run toggle for every candidate. Task 7 reads its verdicts.

**Files:**
- Create: `python/agent_tools/agent_owner_replay.py`
- Modify: `python/agent_tools/agent_owner_report.py` (`build_document(..., arms=None, sweep=False)` fills `simulated` and `calibration`; tables 4 and 5)
- Modify: `python/agent_tools/agent_costs.py` (`--policy`, `--sweep`; both only with `--report owners`, else `ap.error`)
- Create: `tests/test_agent_owner_replay.py`
- Modify: `justfile` (add `tests/test_agent_owner_replay.py` to `agent-workflow-tests` after `tests/test_agent_owner_report.py`)
- Modify: `python/README.md` (§ agent-costs: the replay model, the arms grammar, the keep rule and the known pro-hand-off bias)

**Interfaces:**
- Consumes: Task 2's `OwnerCall`, `Gate`, `Launch`, `Lineage` (with `relauncher`), `call_cost`; Task 3's `PhaseBudget`, `parse(…, knobs=REPLAY_KNOBS)`, `handoff_threshold`, `crossing_threshold`, `select_phase_action`; Task 1's `model_pricing.rates`.
- Produces:

```python
@dataclass(frozen=True)
class Arm:
    name: str
    budget: PhaseBudget | None        # None: the never-hand-off arm
    boot: str = "observed"            # "observed" | "slim"
    keepalive: bool = False
    help: str = "keep"                # "keep" | "drop"

@dataclass(frozen=True)
class BootModel:
    start: int                        # S
    boot_calls: dict[str, int]        # m(p) by phase group "0-5" / "6-7"
    boot_end: dict[str, int]          # B(p)
    slimmable: dict[str, int]         # median slimmable tokens per boot, by group
    overhead_calls: int               # h
    boot_output: int                  # median output tokens of a boot call
    defaults: tuple[str, ...]         # names of the values that fell back to defaults

@dataclass(frozen=True)
class Outcome:
    dollars: float                    # owner calls as replayed + descendant dollars
    handoffs: int
    deaths: int
    peak: int
    trace: tuple[int, ...]            # replayed context of each kept observed owner call, in order

@dataclass(frozen=True)
class Verdict:
    mean: float
    lower_bound: float
    share: float
    keep: bool

BASELINE: Arm   # Arm("baseline", PhaseBudget())

def parse_arm(text: str) -> Arm: ...
def fit(lineages: list[Lineage]) -> BootModel: ...
def observed(lineage: Lineage) -> Outcome: ...                 # the identity replay
def replay(lineage: Lineage, arm: Arm, model: BootModel) -> Outcome: ...
def keep_rule(savings: list[float]) -> Verdict: ...
def compare(lineages, model, arms: list[Arm]) -> list[dict]: ...   # rows for doc["simulated"]
def sweep(lineages, model) -> list[dict]: ...                      # D18 coordinate pass rows
def calibration(lineages, model) -> dict: ...                      # doc["calibration"]
```

**Invariants (the model; per D5, D21):**
1. **Grammar.** `parse_arm("NAME=SPEC")` splits at the first `=`. SPEC items `boot=observed|slim`, `keepalive=off|on`, `help=keep|drop` and `threshold=never` are taken out first; the rest go to `phase_budget.parse(rest, knobs=REPLAY_KNOBS)`, and an empty rest means `PhaseBudget()`. `threshold=never` together with any other `threshold` item, an empty NAME, a NAME without `=`, or a bad value raises `ValueError`, which the CLI turns into `ap.error`.
2. **Identity.** `observed(l).dollars == Σ call_cost(c) for every owner call + l.descendant_dollars`, exactly. No normalisation, no boot and no overhead apply.
3. **Normalisation** (every arm, before the policy). For each launch `k` with `transfer == "handoff"`, followed by launch `k+1` with a `registered_index`:
   - drop launch `k`'s calls after its first call whose `gate.action == "handoff"`, whose context is `C`;
   - drop launch `k+1`'s calls before `registered_index`, where `B` is the registering call's context;
   - the remaining calls of `k+1` join `k`'s virtual owner with `cut −= C − B`, which adds the context back.
   A launch whose next launch has no `registered_index` stays as observed. Every other transfer (`fresh_start`, `delegate`, `None`) starts a new virtual owner: `cut` resets to 0, the kind becomes that launch's `is_root`, and the owner is unregistered until its `registered_index`.
4. **Shift pricing** of a kept call with cumulative `cut` (positive = removed context):
   - `context' = context − cut`.
   - For `cut ≥ 0`, take from `read` first, then from `write`.
   - For `cut < 0`, add `−cut` to `write` when the call is an observed death, else to `read`.
   - When the virtual owner is a subagent and the call's observed `is_root` is true, a call whose gap from the previous kept call exceeds 290 s, with a previous `context'` above 5,000, becomes a death (`write' += read'`, `read' = 0`).
   - When the virtual owner is root and the call was an observed subagent death with a gap ≤ 3,590 s, it is revived: `write' = max(0, context' − prev_context')`, `read' = context' − fresh − write'`.
   - A virtual subagent prices every write at the 5-minute rate; a virtual root keeps the observed 5m/1h split.
5. **Keepalive** (`keepalive=on`): every death (observed or made) is revived as above. It adds `ceil(gap / 270) − 1` pings, each a cache read of the previous `context'` at the read rate, with no output.
6. **Help** (`help=drop`): a `help` call costs nothing. Its growth `max(0, next.context − call.context)`, where `next` is the next call of the same launch, is added to `cut` for the rest of that launch's virtual owner.
7. **Hand-off decision**, never for `budget is None`, for each kept call in order:
   - **Phase boundary**: a call with `gate` (and `not gate.handoff_path`) is re-decided by `select_phase_action(direct=l.direct, turn_count=gate.turn_count, context_tokens=context', turn_ceiling=b.turn_ceiling, context_ceiling=handoff_threshold(b, gate.phase + 1) + b.context_headroom, turn_headroom=b.turn_headroom, context_headroom=b.context_headroom, next_needs_context=…, artifacts_sufficient=…, remainder_self_contained=…)`. Only an answer of `handoff` hands off here, and the guard never applies.
   - **Mid-phase**: a registered virtual owner's `bash` call without `gate` measures `context'` against `crossing_threshold(b, phase, baseline if b.guard else None)`, where `baseline` is the virtual owner's registering `context'` (B after a simulated hand-off). The first measurement at or above it sets `pending`, and a later measurement below it re-arms the latch. The hand-off falls on the first `bash` call at or after `pending` with `children_out` false.
   - **Cap**: with `b.cap`, a hand-off is skipped (and `pending` cleared) while `streak ≥ b.cap`. `streak` counts simulated hand-offs since the last `mark_progress` call or the last gate whose `phase` is above every earlier gate's phase in the lineage.
8. **Simulated hand-off** at call `i` with `C' = context'(i)` and group `g` of `phase(i)`. Call `i` is priced first, in the outgoing owner. Then add:
   - `h = model.overhead_calls` calls, each a read of `C'` plus `boot_output` output;
   - one relauncher wake: a read of `C'` when the virtual owner is root, else of the last `relauncher` context with `end ≤ start(i)`, else nothing;
   - a boot of `m = boot_calls[g]` calls with `B = boot_end[g] − (slimmable[g] if boot == "slim" else 0)`. Call `j` has context `S + (B − S)·j/(m − 1)` (only `B` when `m == 1`); it writes its increment over call `j−1` (call 0 writes `S`) at the 5-minute rate, reads the previous context, and outputs `boot_output`.
   Then `cut += C' − B`, the kind becomes subagent, the owner is registered with `baseline = B`, `pending` is cleared, and `streak += 1`. Everything uses call `i`'s model's rates.
9. **Slim observed boots** (`boot=slim`): for a launch kept as observed, the sum of its boot calls' `slimmable` is added to `cut` from its `registered_index` on, within that virtual owner.
10. **Fit** (`fit`): over non-root owner launches with a `registered_index`:
    - `S` = median first-call context;
    - `boot_calls[g]` = median `registered_index + 1`;
    - `boot_end[g]` = median registering context;
    - `slimmable[g]` = median boot `slimmable` sum;
    - `boot_output` = median output of boot calls (of all owner calls when there are none);
    - `h` = median count of calls after the hand-off-answering call in `transfer == "handoff"` launches.
    Fallbacks, each named in `defaults`: `S = 29_000`, `m = 20`, `h = 6`; a missing group's `B` takes the other group's, then `98_000`; a missing `slimmable` is 0. Medians are `statistics.median` rounded to int.
11. **Keep rule** (D8): `n = len(savings)`, `mean`, `sd = statistics.stdev` (0 when `n < 2`), `lower_bound = mean − 1.2816·sd/√n`, `share` = fraction > 0, and `keep = n ≥ 2 and mean > 0 and lower_bound > 0`. A saving is `replay(l, BASELINE) − replay(l, arm)` per lineage over every lineage in scope.
12. **Rows.** A row of `simulated` has exactly the keys `arm, step, spec, dollars_per_delivered, mean_saving, lower_bound, share_saving, handoffs_per_issue, deaths_per_issue, peak_p90, verdict, live_confirmation_required`. `verdict` is one of `baseline`, `chosen`, `not chosen`, `keep`, `reject` and `info`. `live_confirmation_required` is true when the arm's `handoffs_per_issue` exceeds the baseline's (D18). `dollars_per_delivered` is Σ arm dollars ÷ delivered lineages.
13. **Sweep** (D7, D18). Steps run in order, each on the choices so far. At every step a non-default arm is `chosen` only when its saving against the step's simpler arm passes `keep_rule`; otherwise the simpler arm stays.
    - (`boot`) `boot=slim` against observed.
    - (`threshold`) single arms at 90,000, 110,000, 140,000, 170,000 and 200,000, plus `never`. The lowest `dollars_per_delivered` is the candidate, compared with 110,000. When `fit`'s `|B(6-7) − B(0-5)| / B(0-5) > 0.25`, the 16-arm per-phase grid (`threshold:0-5=x,threshold:6-7=y` with x, y in {110k, 140k, 170k, 200k}) follows, its best compared with the chosen single.
    - (`guard`) 20,000, 40,000, 60,000 against 0.
    - (`cap`) 1, 2, 3 against none.
    - (`help`) drop against keep.
    - (`keepalive`) on against off, verdict `info` only.
    - (`final`) one row for the combined choices, plus one per chosen non-default candidate alone, each against `BASELINE`, with verdict `keep` or `reject`. A candidate is kept only if both its alone row and the final row pass.
14. **Calibration**: `{"identity_matches": bool, "identity_max_error": float, "boots": [{"phase_group", "observed_dollars", "modelled_dollars"}], "model": {"start", "boot_calls", "boot_end", "slimmable", "overhead_calls", "boot_output", "defaults"}}`. Each observed non-root boot's real cost (Σ `call_cost` of its boot calls) is compared with the modelled boot of its group.

- [ ] **Step 1: Write the failing tests** — `tests/test_agent_owner_replay.py`:

```python
"""The owner replay (issue 432, spec test seam 2)."""
import dataclasses
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools import agent_owner_replay as replay_module
from agent_tools.agent_owner_report import Gate, Launch, Lineage, OwnerCall, call_cost
from agent_tools.agent_owner_replay import BASELINE, BootModel, keep_rule, observed, parse_arm, replay
from agent_tools.phase_budget import PhaseBudget

from . import test_agent_owner_report as report_tests   # a module import: its TestCase is not re-collected here
from .owner_transcripts import Session

MODEL = BootModel(start=29_000, boot_calls={"0-5": 2, "6-7": 2},
                  boot_end={"0-5": 60_000, "6-7": 60_000}, slimmable={"0-5": 0, "6-7": 0},
                  overhead_calls=0, boot_output=0, defaults=())


def c(t, context, *, write=1_000, root=False, phase=3, bash=True, gate=None, registers=False,
      out=0, children=False, help=False, mark=False, slim=0, death=False):
    return OwnerCall(start=float(t), end=float(t) + 1, model="claude-opus-5-5", fresh=0,
                     read=context - write, write_5m=0 if root else write,
                     write_1h=write if root else 0, output=out, death=death, is_root=root,
                     phase=phase, bash=bash, children_out=children, gate=gate,
                     registers=registers, help=help, mark_progress=mark, slimmable=slim)


def gate(phase, action="continue", handoff=False):
    return Gate(phase=phase, turn_count=None, next_needs_context=True, artifacts_sufficient=False,
                remainder_self_contained=False, handoff_path=handoff, action=action)


def lineage(*launches, descendants=0.0):
    return Lineage(run_id="r", issue=7, direct=True, launches=list(launches),
                   descendant_dollars=descendants, delivered=True, facts={}, relauncher=())


def launch(calls, *, registered=0, transfer=None, name="t", number=1):
    return Launch(transcript=name, launch=number, calls=tuple(calls), registered_index=registered,
                  transfer=transfer)


def rising(start, stop, step, *, t0=0, **kwargs):
    return [c(t0 + 10 * i, context, **kwargs) for i, context in enumerate(range(start, stop + 1, step))]


class ReplayTest(unittest.TestCase):
    def test_identity_replay_equals_observed(self):
        calls = [c(0, 50_000, gate=gate(2), registers=True), c(10, 60_000, write=10_000)]
        l = lineage(launch(calls), descendants=0.5)
        self.assertEqual(observed(l).dollars, sum(map(call_cost, calls)) + 0.5)

    def test_the_never_arm_undoes_the_chain(self):
        first = launch([c(0, 50_000, gate=gate(2), registers=True),
                        c(10, 120_000, gate=gate(3, "handoff")), c(20, 121_000), c(30, 121_500)],
                       transfer="handoff", name="a1")
        second = launch([c(40, 29_000, write=29_000), c(50, 60_000, write=31_000),
                         c(60, 98_000, gate=gate(3), registers=True), c(70, 99_000), c(80, 100_000)],
                        registered=2, name="a2", number=2)
        out = replay(lineage(first, second), parse_arm("never=threshold=never"), MODEL)
        self.assertEqual(out.handoffs, 0)
        self.assertEqual(out.trace, (50_000, 120_000, 120_000, 121_000, 122_000))
        kept = [first.calls[0], first.calls[1]] + [
            dataclasses.replace(call, read=call.read + 22_000) for call in second.calls[2:]]
        self.assertAlmostEqual(out.dollars, sum(map(call_cost, kept)), places=12)

    def test_a_140k_arm_moves_the_handoff(self):
        calls = [c(0, 100_000, gate=gate(2), registers=True)] + rising(110_000, 180_000, 10_000, t0=10)
        l = lineage(launch(calls))
        base = replay(l, BASELINE, MODEL)
        moved = replay(l, parse_arm("t140=threshold=140000"), MODEL)
        # baseline: hands off at 110k (cut 50k), and again when 160k − 50k reaches 110k
        self.assertEqual((base.handoffs, base.trace[:3]), (2, (100_000, 110_000, 70_000)))
        self.assertEqual(moved.handoffs, 1)
        self.assertEqual(moved.trace[4:6], (140_000, 70_000))   # 150k − (140k − 60k)

    def test_a_handoff_waits_for_an_outstanding_child(self):
        calls = [c(0, 100_000, gate=gate(2), registers=True), c(10, 115_000, children=True),
                 c(20, 116_000, children=True), c(30, 117_000), c(40, 118_000)]
        out = replay(lineage(launch(calls)), BASELINE, MODEL)
        self.assertEqual(out.handoffs, 1)
        self.assertEqual(out.trace, (100_000, 115_000, 116_000, 117_000, 61_000))

    def test_keepalive_turns_a_death_into_pings(self):
        calls = [c(0, 60_000, gate=gate(2), registers=True), c(601, 61_000, write=61_000, death=True)]
        l = lineage(launch(calls))
        warm = replay(l, parse_arm("ka=keepalive=on,threshold=never"), MODEL)
        cold = replay(l, parse_arm("cold=threshold=never"), MODEL)
        pings = math.ceil(600 / 270) - 1
        revived = dataclasses.replace(calls[1], read=60_000, write_5m=1_000)
        self.assertAlmostEqual(warm.dollars, call_cost(calls[0]) + call_cost(revived)
                               + pings * 60_000 * 0.20 / 1e6, places=12)
        self.assertEqual((warm.deaths, cold.deaths), (0, 1))

    def test_the_guard_defers_a_crossing_until_baseline_plus_g(self):
        calls = [c(0, 98_000, gate=gate(5), registers=True, phase=6), c(10, 110_000, phase=6),
                 c(20, 120_000, phase=6), c(30, 140_000, phase=6), c(40, 141_000, phase=6)]
        l = lineage(launch(calls))
        self.assertEqual(replay(l, BASELINE, MODEL).trace[1:3], (110_000, 70_000))
        guarded = replay(l, parse_arm("g40=guard=40000"), MODEL)
        self.assertEqual(guarded.trace[2:5], (120_000, 140_000, 61_000))

    def test_cap_two_blocks_the_third_consecutive_handoff_and_a_marker_resets_it(self):
        # 100k → hand-off 1 (cut 40k); 145k − 40k → hand-off 2 (cut 85k); 190k − 85k is
        # blocked by the cap; the latch stays notified, so only the Phase-2 gate at the end
        # can hand off again, and only once a marker has reset the streak.
        calls = [c(0, 90_000, gate=gate(2), registers=True), c(10, 100_000), c(20, 145_000),
                 c(30, 190_000), c(40, 235_000), c(50, 280_000, gate=gate(2))]
        arm = parse_arm("c2=threshold=100000,cap=2")
        self.assertEqual(replay(lineage(launch(calls)), arm, MODEL).handoffs, 2)
        marked = calls[:4] + [dataclasses.replace(calls[4], mark_progress=True), calls[5]]
        self.assertEqual(replay(lineage(launch(marked)), arm, MODEL).handoffs, 3)

    def test_help_drop_removes_the_call_and_its_growth(self):
        calls = [c(0, 50_000, gate=gate(2), registers=True), c(10, 51_000, help=True),
                 c(20, 60_000, write=9_000), c(30, 61_000)]
        out = replay(lineage(launch(calls)), parse_arm("h=help=drop,threshold=never"), MODEL)
        self.assertEqual(out.trace, (50_000, 51_000, 52_000))
        shifted = [dataclasses.replace(calls[2], read=42_000),   # the 9k cut comes off the read
                   dataclasses.replace(calls[3], read=51_000)]
        self.assertAlmostEqual(out.dollars, call_cost(calls[0]) + sum(map(call_cost, shifted)),
                               places=12)

    def test_boot_slim_subtracts_the_slimmable_reads(self):
        model = dataclasses.replace(MODEL, slimmable={"0-5": 20_000, "6-7": 20_000})
        calls = [c(0, 100_000, gate=gate(2), registers=True), c(10, 110_000), c(20, 120_000)]
        l = lineage(launch(calls))
        self.assertEqual(replay(l, BASELINE, model).trace[2], 70_000)
        self.assertEqual(replay(l, parse_arm("s=boot=slim"), model).trace[2], 50_000)

    def test_fit_reads_the_observed_boots(self):
        boot = launch([c(0, 29_000, slim=0), c(10, 50_000, slim=12_000), c(20, 75_000, slim=8_000),
                       c(30, 98_000, gate=gate(3), registers=True)], registered=3, name="b")
        model = replay_module.fit([lineage(boot)])
        self.assertEqual((model.start, model.boot_calls["0-5"], model.boot_end["0-5"],
                          model.slimmable["0-5"]), (29_000, 4, 98_000, 20_000))
        self.assertIn("overhead_calls", model.defaults)

    def test_the_keep_rule_keeps_a_clear_win_and_rejects_noise(self):
        self.assertTrue(keep_rule([1.0, 1.2, 0.9, 1.1]).keep)
        noisy = keep_rule([2.0, -1.9, 1.8, -1.7])
        self.assertGreater(noisy.mean, 0)
        self.assertFalse(noisy.keep)
        self.assertFalse(keep_rule([5.0]).keep)

    def test_arm_grammar(self):
        self.assertEqual(parse_arm("t140=threshold=140000"),
                         replay_module.Arm("t140", PhaseBudget(threshold=140_000)))
        arm = parse_arm("mix=boot=slim,keepalive=on,help=drop,guard=40000")
        self.assertEqual((arm.boot, arm.keepalive, arm.help, arm.budget.guard),
                         ("slim", True, "drop", 40_000))
        self.assertIsNone(parse_arm("n=threshold=never").budget)
        for bad in ("noequals", "=threshold=1", "x=boot=fat", "x=threshold=never,threshold=90000"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_arm(bad)


class SweepCliTest(unittest.TestCase):
    def test_the_sweep_reports_the_threshold_arms_and_the_identity_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_tests.OwnerReportTest.chain(Session(root)).write()
            out = subprocess.run(
                [sys.executable, "-m", "agent_tools.agent_costs", "--report", "owners", "--format",
                 "json", "--days", "0", "--projects-dir", str(root), "--sweep",
                 "--policy", "t125=threshold=125000"], capture_output=True, text=True, check=True)
        doc = json.loads(out.stdout)
        specs = {row["spec"] for row in doc["simulated"]}
        for threshold in (90_000, 110_000, 140_000, 170_000, 200_000):
            self.assertIn(f"threshold={threshold}", specs)
        self.assertIn("threshold=never", specs)
        self.assertIn("t125", {row["arm"] for row in doc["simulated"]})
        self.assertTrue(doc["calibration"]["identity_matches"])
```

Before implementing, check every asserted trace and dollar value by hand against invariants 3–9 with `MODEL` (h = 0, m = 2, B = 60,000, S = 29,000). Where a fixture and an invariant disagree, fix the fixture, never the invariant. Then record the arithmetic in a comment above each assertion that has none.

- [ ] **Step 2: Run the tests and watch them fail**

Run: **Report tests** naming `tests/test_agent_owner_replay.py`.
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_tools.agent_owner_replay'`.

- [ ] **Step 3: Implement** to the interfaces and invariants. A single private walker, `_walk(lineage, arm, model) -> Outcome`, carries the state of invariants 3–9. `observed` does not call it. `compare` evaluates `--policy` arms against `BASELINE` and gives each the verdict `keep` or `reject` from invariant 11. Text table 4 prints one line per row; table 5 prints the identity check, the model with its `defaults`, and boots p50 observed against modelled. The footer adds: "The shift model keeps observed increments after a hand-off and cannot see a fresh owner's re-reads, so it favours hand-offs (D18)".

- [ ] **Step 4: Verify**

Run: **Report tests** naming all three report test files.
Expected: `OK`. Then run `just agent-costs --report owners --days 14 --sweep | sed -n '/Simulated arms/,/Calibration/p' | head -40` on this host and confirm that rows print with a `verdict` column and exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/agent_owner_replay.py python/agent_tools/agent_owner_report.py \
  python/agent_tools/agent_costs.py tests/test_agent_owner_replay.py \
  justfile python/README.md
launch-commit … -- -m "feat(agent-costs): replay owner lineages under hand-off policies, with the sweep (issue 432)"
```
