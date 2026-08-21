"""Throwaway TUI shell over core.Run. Drive it by hand; the logic module is the keeper.

  python3 prototype-release-transactions/tui.py        (or: just prototype-release-transactions)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import Run  # noqa: E402
from profiles import SHAPES  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402
from world import FAULTS, World  # noqa: E402

B, D, R = "\x1b[1m", "\x1b[2m", "\x1b[0m"
GRN, RED, YEL, CYA = "\x1b[32m", "\x1b[31m", "\x1b[33m", "\x1b[36m"
SHAPE_NAMES = list(SHAPES)
VIEWS = ("state", "events", "proof", "gaps", "preview")


def getch() -> str:
    try:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            return sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:
        return (sys.stdin.readline() or "q").strip()[:1] or "\n"


class App:
    def __init__(self):
        self.shape_i = 0
        self.scen_i = 0
        self.view = "state"
        self.msg = "press [n] to step"
        self.reset()

    # -- run lifecycle ----------------------------------------------------
    def reset(self):
        self.world = World()
        scen = SCENARIOS[self.scen_i]
        self.world.faults = set(scen["faults"])
        subject, profile, registry = SHAPES[SHAPE_NAMES[self.shape_i]](self.world)
        if scen["mutate"]:
            scen["mutate"](subject, profile, registry)
        self.run = Run(subject, profile, registry, self.world,
                       creation_key=f"{SHAPE_NAMES[self.shape_i]}:{scen['name']}")
        if scen["arm_crash"]:
            self.world.arm_crash()
        self.msg = f"loaded {SHAPE_NAMES[self.shape_i]} / {scen['name']}"

    @property
    def scen(self):
        return SCENARIOS[self.scen_i]

    # -- rendering --------------------------------------------------------
    def colour_status(self, s: str) -> str:
        if s in ("satisfied", "succeeded", "accepted", "rolled_back"):
            return GRN + s + R
        if s in ("diverged", "rejected", "failed", "attention_required"):
            return RED + s + R
        if s in ("unknown", "in_progress", "indeterminate", "unsupported", "recovering"):
            return YEL + s + R
        return s

    def frame(self):
        r, w = self.run, self.world
        out = []
        out.append(f"{B}release-transaction dry run{R}  {D}(#86 — simulated world, "
                   f"nothing external is touched){R}")
        out.append(f"{B}shape{R} {CYA}{SHAPE_NAMES[self.shape_i]}{R}   "
                   f"{B}scenario{R} {CYA}{self.scen['name']}{R}   "
                   f"{B}clock{R} {D}t+{w.clock}s{R}   "
                   f"{B}faults{R} {D}{sorted(w.faults) or '-'}{R}")
        out.append(f"{D}{self.scen['note']}{R}")
        out.append("")
        if r.contract_error:
            out.append(f"{B}resolution{R} {RED}rejected{R}: {r.contract_error}")
            out.append("")
        else:
            out.append(f"{B}release{R} {r.release_id}  {B}semver{R} {r.semver}  "
                       f"{B}profile{R} {r.resolved.profile_id} v{r.resolved.profile_version} "
                       f"{D}{r.resolved.profile_digest}{R}")
            out.append(f"{B}state{R} {self.colour_status(r.state)}   "
                       f"{B}fence{R} {r.fence_epoch}  {B}executor{R} {r.executor}  "
                       f"{B}rev{R} {r.revision}  "
                       f"{B}auth{R} {'yes' if r.authorization else 'none'}"
                       + (f"  {B}irrev-ok{R} {r.authorization['confirmed_irreversible']}"
                          if r.authorization else ""))
            if r.attention_reason:
                out.append(f"{RED}attention{R} {r.attention_reason}")
            if r.terminal:
                out.append(f"{GRN}terminal{R} {r.state}: {r.terminal_reason}")
            out.append("")

        if self.view == "state" and not r.contract_error:
            out.append(f"{B}actions{R}")
            for a in r.actions:
                out.append(f"  {D}{a.phase[:4]}{R} {a.id:<22} {a.mode:<20} "
                           f"{self.colour_status(a.status):<24} "
                           f"{D}att={len(a.attempts)} {a.effect_class}{R}")
            out.append("")
            out.append(f"{B}receipts{R} " + (", ".join(
                f"{k}={D}{v['digest'][:8]}{R}" for k, v in r.receipts.items()) or "-"))
            if r.effect_snapshot:
                out.append(f"{B}effect_snapshot{R} {D}{r.effect_snapshot['digest'][:8]}{R} "
                           + ", ".join(f"{k}={self.colour_status(v)}"
                                       for k, v in r.effect_snapshot["classes"].items()))
            out.append("")
            out.append(f"{B}recent{R}")
            for t, kind, m in r.events[-7:]:
                mark = {"gap": RED + "GAP" + R, "attention": YEL + "!" + R,
                        "terminal": GRN + "**" + R, "crash": RED + "xx" + R}.get(kind, " ·")
                out.append(f"  {D}t+{t:<5}{R}{mark} {m}")
        elif self.view == "events":
            out.append(f"{B}full event ledger{R} {D}(append-only){R}")
            for t, kind, m in r.events[-32:]:
                out.append(f"  {D}t+{t:<5} {kind:<9}{R} {m}")
        elif self.view == "proof":
            if r.contract_error:
                out.append("no proof plan: profile was rejected at resolution")
            else:
                out.append(f"{B}proof plan{R}  {D}cutoff={r.proof_cutoff_at}{R}")
                for o in r.resolved.proof:
                    ev = r.evaluations.get(o["id"])
                    mark = "req" if o["required"] else D + "adv" + R
                    label = self.colour_status(ev[0]) if ev else D + "pending" + R
                    reason = f" {D}{ev[1][:56]}{R}" if ev else ""
                    out.append(f"  [{mark}] {o['id']:<34} {o['semantic']:<17}"
                               f"{o['temporal']:<9} {label}{reason}")
                out.append("")
                out.append(f"{B}evidence{R}")
                for e in r.evidence[-10:]:
                    exp = f"exp t+{e.expires_at}" if e.expires_at else "no expiry"
                    out.append(f"  {e.obligation_id:<36} {e.temporal:<9} "
                               f"{self.colour_status(e.outcome):<22} {D}obs t+{e.observed_at} "
                               f"{exp} fence={e.fence}{R}")
        elif self.view == "gaps":
            out.append(f"{B}contract gaps found while building/driving this{R}")
            if not r.gaps:
                out.append(f"  {D}none recorded for this run{R}")
            for i, g in enumerate(r.gaps, 1):
                out.append(f"  {RED}{i}.{R} {g}")
            out.append("")
            out.append(f"{D}NOTES.md holds the full findings list, including the ones that "
                       f"are not machine-detectable.{R}")
        elif self.view == "preview":
            if r.contract_error:
                out.append("no preview: profile was rejected at resolution")
            else:
                pv = r.plan_preview()
                for k, v in pv.items():
                    out.append(f"  {B}{k}{R} {D}{v}{R}")

        out.append("")
        out.append(f"{YEL}{self.msg}{R}")
        out.append(f"{D}[n]step [a]authorize [c]confirm-irreversible [e]extra-attempt "
                   f"[t]+5min [k]arm-crash [u]takeover{R}")
        out.append(f"{D}[R]reconcile [G]grant-recovery [D]dispose [x]recollect  "
                   f"[p]shape [s]scenario [f]fault [v]view={self.view} [r]reset [q]quit{R}")
        return "\n".join(out)

    # -- input ------------------------------------------------------------
    def fault_menu(self):
        print("\x1b[2J\x1b[H", end="")
        for i, f in enumerate(FAULTS):
            on = "x" if f in self.world.faults else " "
            print(f"  [{on}] {i}  {f}")
        print("\n  number to toggle, anything else to cancel")
        c = getch()
        if c.isdigit() and int(c) < len(FAULTS):
            self.world.toggle(FAULTS[int(c)])
            self.msg = f"faults now {sorted(self.world.faults) or '-'}"

    def handle(self, c: str) -> bool:
        r = self.run
        if c in ("q", "\x03"):
            return False
        if r.resolved is None and c not in ("p", "s", "r", "v", "f"):
            self.msg = "profile was rejected at resolution — nothing to drive"
            return True
        if c in ("n", "\r", "\n", " "):
            self.msg = r.step()
        elif c == "a":
            if r.resolved:
                r.acquire_lease() if not r.lease_ok() else None
                r.authorize()
                self.msg = "authorization granted (reversible actions only)"
        elif c == "c":
            if r.resolved:
                irr = tuple(a.id for a in r.actions if a.effect_class == "irreversible")
                r.authorize(irreversible_confirmed=irr)
                if r.state == "attention_required" and r.attention_reason \
                        and "blocked" in r.attention_reason:
                    r.attention_reason = None
                    r.state = r._phase_state()
                self.msg = f"fresh one-action confirmation recorded for {list(irr)}"
        elif c == "e":
            r.grant_extra_attempt()
            self.msg = "extra attempt granted"
        elif c == "t":
            self.world.tick(300)
            self.msg = f"clock advanced to t+{self.world.clock}s"
        elif c == "k":
            self.world.arm_crash()
            self.msg = "crash armed: the next invoke loses its executor"
        elif c == "u":
            r.takeover()
            self.msg = "takeover complete"
        elif c == "R":
            r.reconcile()
            r.plan_recovery()
            self.msg = "effect snapshot frozen; recovery previewed"
        elif c == "G":
            r.grant_recovery()
            self.msg = "recovery grant recorded; [n] runs the selected subgraph"
        elif c == "D":
            r.dispose_no_recovery(successor="rel_successor_stub")
            self.msg = "disposition attempted"
        elif c == "x":
            r.recollect_stale()
            self.msg = "recollect requested"
        elif c == "p":
            self.shape_i = (self.shape_i + 1) % len(SHAPE_NAMES)
            self.reset()
        elif c == "s":
            self.scen_i = (self.scen_i + 1) % len(SCENARIOS)
            self.reset()
        elif c == "f":
            self.fault_menu()
        elif c == "v":
            self.view = VIEWS[(VIEWS.index(self.view) + 1) % len(VIEWS)]
        elif c == "r":
            self.reset()
        return True

    def loop(self):
        while True:
            print("\x1b[2J\x1b[H" + self.frame(), flush=True)
            if not self.handle(getch()):
                break
        print("\x1b[2J\x1b[H", end="")


if __name__ == "__main__":
    App().loop()
