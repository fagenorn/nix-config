"""Headless autopilot: run every shape x scenario and print where each one lands.

Not a test suite — there are no assertions. It exists so the whole matrix can be swept in
one command while hand-driving the interesting cells in the TUI.

  python3 prototype-release-transactions/drive.py [shape] [scenario]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import Run  # noqa: E402
from profiles import SHAPES  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402
from world import World  # noqa: E402

MAX_STEPS = 90


def autopilot(shape_name, scen, verbose=False):
    world = World()
    world.faults = set(scen["faults"])
    subject, profile, registry = SHAPES[shape_name](world)
    if scen["mutate"]:
        scen["mutate"](subject, profile, registry)
    run = Run(subject, profile, registry, world, creation_key=f"{shape_name}:{scen['name']}")
    if scen["arm_crash"]:
        world.arm_crash()
    used = {"takeover": 0, "extra": 0, "recollect": 0, "recovery": 0, "dispose": 0}
    stalled = 0
    for _ in range(MAX_STEPS):
        if run.terminal or run.contract_error:
            break
        before = (run.state, run.revision)
        if run.state == "ready" and not run.authorization:
            irr = tuple(a.id for a in run.actions if a.effect_class == "irreversible")
            if not run.lease_ok():
                run.acquire_lease()
            run.authorize(irreversible_confirmed=irr)
        elif run.state == "attention_required":
            reason = run.attention_reason or ""
            if "lease" in reason:
                run.takeover(run.executor)
            elif "observation deadline" in reason and used["recovery"] < 1:
                used["recovery"] += 1
                run.reconcile()
                run.plan_recovery()
                run.grant_recovery()
            elif "executor lost" in reason and used["takeover"] < 1:
                used["takeover"] += 1
                run.takeover()
            elif "budget" in reason and used["extra"] < 2:
                used["extra"] += 1
                run.grant_extra_attempt()
            elif "expired" in reason and used["recollect"] < 2:
                used["recollect"] += 1
                run.recollect_stale()
            elif "blocked — needs" in reason:
                irr = tuple(a.id for a in run.actions if a.effect_class == "irreversible")
                run.authorize(irreversible_confirmed=irr)
                run.attention_reason = None
                run.state = run._phase_state()
            elif used["recovery"] < 1:
                used["recovery"] += 1
                run.reconcile()
                run.plan_recovery()
                run.grant_recovery()
            elif used["dispose"] < 1:
                used["dispose"] += 1
                run.dispose_no_recovery(successor="rel_successor_stub")
            else:
                break
        else:
            run.step()
        if (run.state, run.revision) == before:
            stalled += 1
            if stalled > 3:
                break
        else:
            stalled = 0
        world.tick(scen.get("tick", 20))
    if verbose:
        for t, kind, m in run.events:
            print(f"  t+{t:<5} {kind:<9} {m}")
    return run


def summarise(run) -> str:
    if run.contract_error:
        return f"REJECTED AT RESOLUTION — {run.contract_error}"
    if run.terminal:
        warn = ""
        term = run.receipts.get("terminal", {}).get("body", {})
        if term.get("warnings"):
            warn = f"  warnings={[w[0] for w in term['warnings']]}"
        return f"{run.state.upper()} — {run.terminal_reason}{warn}"
    return f"nonterminal {run.state} — {run.attention_reason or 'still working'}"


def main():
    args = sys.argv[1:]
    shapes = [args[0]] if args else list(SHAPES)
    scens = [s for s in SCENARIOS if len(args) < 2 or s["name"] == args[1]]
    verbose = len(args) >= 2
    all_gaps = []
    for shape in shapes:
        print(f"\n=== {shape} " + "=" * (66 - len(shape)))
        for scen in scens:
            run = autopilot(shape, scen, verbose)
            print(f"  {scen['name']:<30} {summarise(run)}")
            for g in run.gaps:
                if g not in all_gaps:
                    all_gaps.append(g)
    print("\n=== machine-detected gaps " + "=" * 50)
    for i, g in enumerate(all_gaps, 1):
        print(f"  {i}. {g}")


if __name__ == "__main__":
    main()
