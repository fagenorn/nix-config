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
from agent_tools.agent_owner_replay import (BASELINE, ORIGIN, BootModel, keep_rule, observed,
                                            parse_arm, replay)
from agent_tools.phase_budget import PhaseBudget

from . import test_agent_owner_report as report_tests   # a module import: its TestCase is not re-collected here
from .owner_transcripts import Session

MODEL = BootModel(start=29_000, boot_calls={"0-5": 2, "6-7": 2},
                  boot_end={"0-5": 60_000, "6-7": 60_000}, slimmable={"0-5": 0, "6-7": 0},
                  overhead_calls=0, boot_output=0, defaults=())


def c(t, context, *, write=1_000, root=False, phase=3, bash=True, gate=None, registers=False,
      out=0, children=False, help=False, mark=None, slim=0, death=False):
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
        # the identity replay adds no boot, overhead or shift: owner calls as observed + 0.5
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
        # C = 120k (first launch's answering call), B = 98k (a2's registering call): cut = -22k,
        # so a2's calls from index 2 read 22k more and show 120k, 121k, 122k; a1's 121k and
        # 121.5k calls and a2's three boot calls are dropped.
        self.assertEqual(out.trace, (50_000, 120_000, 120_000, 121_000, 122_000))
        kept = [first.calls[0], first.calls[1]] + [
            dataclasses.replace(call, read=call.read + 22_000) for call in second.calls[2:]]
        self.assertAlmostEqual(out.dollars, sum(map(call_cost, kept)), places=12)

    def test_a_140k_arm_moves_the_handoff(self):
        calls = [c(0, 100_000, gate=gate(2), registers=True)] + rising(110_000, 180_000, 10_000, t0=10)
        l = lineage(launch(calls))
        base = replay(l, BASELINE, MODEL)
        # the Phase-2 gate at 100k stays below 110k (gate ceiling 120k − 10k headroom)
        moved = replay(l, parse_arm("t140=threshold=140000"), MODEL)
        # baseline: hands off at 110k (cut 50k), and again when 160k − 50k reaches 110k
        self.assertEqual((base.handoffs, base.trace[:3]), (2, (100_000, 110_000, 70_000)))
        # 140k arm: calls rise 110k..180k, the 140k call is the 5th (index 4) and hands off with
        # cut 140k − 60k = 80k; the later calls reach 160k − 80k = 80k at most, below 140k
        self.assertEqual(moved.handoffs, 1)
        self.assertEqual(moved.trace[4:6], (140_000, 70_000))   # 150k − (140k − 60k)

    def test_a_handoff_waits_for_an_outstanding_child(self):
        calls = [c(0, 100_000, gate=gate(2), registers=True), c(10, 115_000, children=True),
                 c(20, 116_000, children=True), c(30, 117_000), c(40, 118_000)]
        out = replay(lineage(launch(calls)), BASELINE, MODEL)
        # 115k crosses 110k but a child is out until the call at 117k: cut 117k − 60k = 57k,
        # so the last call shows 118k − 57k = 61k
        self.assertEqual(out.handoffs, 1)
        self.assertEqual(out.trace, (100_000, 115_000, 116_000, 117_000, 61_000))

    def test_keepalive_turns_a_death_into_pings(self):
        calls = [c(0, 60_000, gate=gate(2), registers=True), c(601, 61_000, write=61_000, death=True)]
        l = lineage(launch(calls))
        # gap 601 − 1 = 600 s: ⌈600/270⌉ − 1 = 2 pings of the 60k prefix at $0.20/M; the death is
        # revived: write 61k − 60k = 1k, read 60k
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
        # baseline: 110k crosses at call 1 (cut 110k − 60k = 50k): 120k − 50k = 70k.
        # guard 40k: baseline context 98k + 40k = 138k, first reached by the 140k call, which
        # hands off (cut 80k): 141k − 80k = 61k
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
        marked = calls[:4] + [dataclasses.replace(calls[4], mark_progress="advanced"), calls[5]]
        self.assertEqual(replay(lineage(launch(marked)), arm, MODEL).handoffs, 3)
        idle = calls[:4] + [dataclasses.replace(calls[4], mark_progress="unchanged"), calls[5]]
        self.assertEqual(replay(lineage(launch(idle)), arm, MODEL).handoffs, 2)   # only `advanced` resets

    def test_help_drop_removes_the_call_and_its_growth(self):
        calls = [c(0, 50_000, gate=gate(2), registers=True), c(10, 51_000, help=True),
                 c(20, 60_000, write=9_000), c(30, 61_000)]
        # the help call goes; its growth 60k − 51k = 9k joins the cut: 51k, 52k
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
        # observed B 60k: cut 110k − 60k = 50k → 70k; slim B 60k − 20k = 40k: cut 70k → 50k
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
        # mean 0.05, sample sd ≈ 2.0, so the lower bound 0.05 − 1.2816 · 2.0/2 ≈ −1.23
        noisy = keep_rule([2.0, -1.9, 1.8, -1.7])
        self.assertGreater(noisy.mean, 0)
        self.assertFalse(noisy.keep)
        self.assertFalse(keep_rule([5.0]).keep)

    def test_arm_grammar(self):
        self.assertEqual(parse_arm("t140=threshold=140000"),
                         replay_module.Arm("t140", dataclasses.replace(ORIGIN, threshold=140_000)))
        arm = parse_arm("mix=boot=slim,keepalive=on,help=drop,guard=40000")
        self.assertEqual((arm.boot, arm.keepalive, arm.help, arm.budget.guard),
                         ("slim", True, "drop", 40_000))
        self.assertIsNone(parse_arm("n=threshold=never").budget)
        for bad in ("noequals", "=threshold=1", "x=boot=fat", "x=threshold=never,threshold=90000"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_arm(bad)

    def test_the_baseline_is_the_pre_issue_432_policy_whatever_the_defaults(self):
        # Task 7 may move PhaseBudget's defaults; the comparator and unnamed knobs stay (D24).
        origin = PhaseBudget(turn_ceiling=120, turn_headroom=2, context_headroom=10_000,
                             threshold=110_000, phase_thresholds=(), guard=0, cap=None)
        self.assertEqual((ORIGIN, BASELINE.budget), (origin, origin))
        self.assertEqual(parse_arm("g=guard=40000").budget, dataclasses.replace(origin, guard=40_000))
        self.assertEqual(parse_arm("s=boot=slim").budget, origin)


class SweepTest(unittest.TestCase):
    def test_the_combined_row_prices_exactly_the_alone_kept_subset(self):
        # Two identical lineages (sd 0, so a positive saving is kept): 90 calls at 40k + 1k · i
        # (40k..129k, 10 s apart), model B 60k or 40k slim, boot cost $0.3058 (29k write +
        # 29k read + 31k write) or $0.2058 slim, cache read $0.20/M.
        #   110k observed: one hand-off at 110k, cut 50k, 19 later calls: −$0.19 + $0.3058 = +$0.116
        #   110k slim:     cut 70k: −$0.266 + $0.2058 = −$0.0602  (slim saves $0.176 alone)
        #   90k slim:      hand-off at 90k, cut 50k, 39 later calls: −$0.39 + $0.2058 = −$0.1842
        #                  (beats 110k slim by $0.124, so it is chosen under slim)
        #   90k observed:  hand-offs at 90k (cut 30k) and at 120k (cut 60k): −$0.288 + $0.6116
        #                  = +$0.3236, $0.2076 dearer than baseline: rejected alone
        # Guard 20k and 40k change nothing (baseline 40k + g stays under 90k), guard 60k is
        # dearer, and a cap never binds (one hand-off), so none of them is chosen.
        model = dataclasses.replace(MODEL, slimmable={"0-5": 20_000, "6-7": 20_000})
        calls = [c(0, 40_000, gate=gate(2), registers=True)] + [
            c(10 * i, 40_000 + 1_000 * i) for i in range(1, 90)]
        lineages = [lineage(launch(calls, name=f"t{n}")) for n in range(2)]
        rows = replay_module.sweep(lineages, model)
        final = {row["arm"]: row for row in rows if row["step"] == "final"}
        self.assertEqual({name: row["verdict"] for name, row in final.items()},
                         {"boot": "keep", "threshold": "reject", "combined": "keep"})
        self.assertEqual((final["boot"]["spec"], final["threshold"]["spec"], final["combined"]["spec"]),
                         ("boot=slim", "threshold=90000", "boot=slim"))


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
        keys = {"arm", "step", "spec", "dollars_per_delivered", "mean_saving", "lower_bound",
                "share_saving", "handoffs_per_issue", "deaths_per_issue", "peak_p90", "verdict",
                "live_confirmation_required"}
        self.assertTrue(all(set(row) == keys for row in doc["simulated"]))
        self.assertEqual(doc["simulated"][0]["verdict"], "baseline")
        self.assertLessEqual({row["verdict"] for row in doc["simulated"]},
                             {"baseline", "chosen", "not chosen", "keep", "reject", "info"})

    def test_the_text_tables_print_the_verdict_column_and_the_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_tests.OwnerReportTest.chain(Session(root)).write()
            out = subprocess.run(
                [sys.executable, "-m", "agent_tools.agent_costs", "--report", "owners", "--days", "0",
                 "--projects-dir", str(root), "--sweep"], capture_output=True, text=True, check=True)
        self.assertRegex(out.stdout, r"(?m)^arm +step +spec .* verdict +live check$")
        self.assertRegex(out.stdout, r"(?m)^baseline +baseline +threshold=110000 .* baseline +no$")
        self.assertIn("Identity replay matches the priced lineages: yes", out.stdout)
        self.assertIn("it favours hand-offs", out.stdout)
