"""The owner replay of the agent-costs owner report (issue 432).

``replay`` prices one lineage under a hand-off policy (an ``Arm``) with a shift model:
the observed calls keep their increments, outputs and gaps, and a simulated hand-off
cuts ``C - B`` tokens of context from every later call while adding the outgoing owner's
overhead calls, the relauncher's wake call and the fresh owner's boot. ``fit`` reads the
boot model from the corpus, ``keep_rule`` is the paired one-sided test, ``compare``
prices ``--policy`` arms against ``BASELINE`` and ``sweep`` runs the coordinate pass
over the candidate policies. ``calibration`` checks the identity replay and the modelled
boots against the observed ones. python/README.md (agent-costs) holds the model.
"""

import math
import statistics
from dataclasses import dataclass, replace
from typing import NamedTuple

from agent_tools.agent_costs import percentile
from agent_tools.agent_owner_report import (
    BOOT_GROUPS,
    Lineage,
    OwnerCall,
    boot_facts,
    call_cost,
    phase_group,
)
from agent_tools.model_pricing import usage_cost
from agent_tools.phase_budget import (
    REPLAY_KNOBS,
    PhaseBudget,
    crossing_threshold,
    handoff_threshold,
    parse,
    select_phase_action,
)
from agent_tools.transcript_calls import MIN_DEATH_CONTEXT, TTL_SECONDS, TTL_SLACK_SECONDS

DEFAULT_START = 29_000
DEFAULT_BOOT_CALLS = 20
DEFAULT_OVERHEAD_CALLS = 6
DEFAULT_BOOT_END = 98_000
MADE_DEATH_GAP = TTL_SECONDS[False] - TTL_SLACK_SECONDS
REVIVE_GAP = TTL_SECONDS[True] - TTL_SLACK_SECONDS
PING_SECONDS = 270
ONE_SIDED_90 = 1.2816
PHASE_SPREAD = 0.25
THRESHOLDS = (90_000, 110_000, 140_000, 170_000, 200_000)
GRID_THRESHOLDS = (110_000, 140_000, 170_000, 200_000)
GUARDS = (20_000, 40_000, 60_000)
CAPS = (1, 2, 3)
STEPS = ("boot", "threshold", "guard", "cap", "help", "keepalive")
KEPT_STEPS = STEPS[:-1]

# The pre-issue-432 policy, in literals: it does not move with PhaseBudget's defaults (D24).
ORIGIN = PhaseBudget(turn_ceiling=120, turn_headroom=2, context_headroom=10_000,
                     threshold=110_000, phase_thresholds=(), guard=0, cap=None)

_CHOICES = {"boot": ("observed", "slim"), "keepalive": ("off", "on"), "help": ("keep", "drop")}


@dataclass(frozen=True)
class Arm:
    name: str
    budget: PhaseBudget | None  # None: the never-hand-off arm
    boot: str = "observed"  # "observed" | "slim"
    keepalive: bool = False
    help: str = "keep"  # "keep" | "drop"


BASELINE = Arm("baseline", ORIGIN)


@dataclass(frozen=True)
class BootModel:
    start: int  # S
    boot_calls: dict[str, int]  # m(p) by phase group "0-5" / "6-7"
    boot_end: dict[str, int]  # B(p)
    slimmable: dict[str, int]  # median slimmable tokens per boot, by group
    overhead_calls: int  # h
    boot_output: int  # median output tokens of a boot call
    defaults: tuple[str, ...]  # names of the values that fell back to defaults


@dataclass(frozen=True)
class Outcome:
    dollars: float  # owner calls as replayed + descendant dollars
    handoffs: int
    deaths: int
    peak: int
    trace: tuple[int, ...]  # replayed context of each kept observed owner call, in order


@dataclass(frozen=True)
class Verdict:
    mean: float
    lower_bound: float
    share: float
    keep: bool


def parse_arm(text: str) -> Arm:
    """The arm of `NAME=SPEC`; ValueError for a spec the grammar does not accept."""
    name, equals, spec = text.partition("=")
    if not equals or not name:
        raise ValueError(f"policy {text!r}: expected NAME=SPEC")
    return _arm(name, spec)


def _arm(name, spec):
    chosen, rest, never = {}, [], False
    for item in spec.split(",") if spec else ():
        key, equals, value = item.partition("=")
        if key in _CHOICES and equals:
            if value not in _CHOICES[key] or key in chosen:
                raise ValueError(f"policy item {item!r}: {key} is one of "
                                 f"{'|'.join(_CHOICES[key])}, given once")
            chosen[key] = value
        elif item == "threshold=never":
            never = True
        else:
            rest.append(item)
    if never and any(item.partition("=")[0].startswith("threshold") for item in rest):
        raise ValueError(f"policy {name!r}: threshold=never excludes every other threshold")
    budget = None if never else (parse(",".join(rest), knobs=REPLAY_KNOBS, base=ORIGIN)
                                 if rest else ORIGIN)
    return Arm(name, budget, boot=chosen.get("boot", "observed"),
               keepalive=chosen.get("keepalive") == "on", help=chosen.get("help", "keep"))


def _spec_of(arm):
    """The spec an arm parses from: the threshold always, every other knob when not default."""
    items = [] if arm.boot == "observed" else [f"boot={arm.boot}"]
    budget = arm.budget
    if budget is None:
        items.append("threshold=never")
    else:
        if not budget.phase_thresholds or budget.threshold != ORIGIN.threshold:
            items.append(f"threshold={budget.threshold}")
        items += [f"threshold:{a}-{b}={tokens}" for a, b, tokens in budget.phase_thresholds]
        if budget.guard:
            items.append(f"guard={budget.guard}")
        if budget.cap is not None:
            items.append(f"cap={budget.cap}")
    if arm.help != "keep":
        items.append(f"help={arm.help}")
    if arm.keepalive:
        items.append("keepalive=on")
    return ",".join(items)


# ---- the boot model ---------------------------------------------------------------


def _median(values):
    return int(round(statistics.median(values)))


def fit(lineages: list[Lineage]) -> BootModel:
    """The boot model of the observed fresh-owner boots and hand-offs (defaults named)."""
    boots = [(launch, boot_facts(launch)) for lineage in lineages for launch in lineage.launches]
    boots = [(launch, found) for launch, found in boots if found is not None]
    defaults = []

    def pick(values, default, name):
        if values:
            return _median(values)
        defaults.append(name)
        return default

    start = pick([facts["start"] for _, (_, facts) in boots], DEFAULT_START, "start")
    by_group = {group: [facts for _, (found, facts) in boots if found == group]
                for group in BOOT_GROUPS}
    boot_calls = {group: pick([facts["calls"] for facts in by_group[group]],
                              DEFAULT_BOOT_CALLS, f"boot_calls:{group}") for group in BOOT_GROUPS}
    slimmable = {group: pick([facts["slimmable"] for facts in by_group[group]], 0,
                             f"slimmable:{group}") for group in BOOT_GROUPS}
    ends = {group: _median([facts["b"] for facts in by_group[group]])
            for group in BOOT_GROUPS if by_group[group]}
    boot_end = {}
    for group in BOOT_GROUPS:
        if group not in ends:
            defaults.append(f"boot_end:{group}")
        boot_end[group] = ends.get(group, next(iter(ends.values()), DEFAULT_BOOT_END))
    answered = [len(launch.calls) - _answer(launch.calls, 0) - 1
                for lineage in lineages for launch in lineage.launches
                if launch.transfer == "handoff" and _answer(launch.calls, 0) is not None]
    outputs = [call.output for launch, _ in boots for call in launch.calls[:launch.registered_index + 1]]
    if not outputs:
        outputs = [call.output for lineage in lineages for launch in lineage.launches
                   for call in launch.calls]
    return BootModel(start, boot_calls, boot_end, slimmable,
                     pick(answered, DEFAULT_OVERHEAD_CALLS, "overhead_calls"),
                     pick(outputs, 0, "boot_output"), tuple(defaults))


# ---- normalisation ----------------------------------------------------------------


@dataclass
class _Entry:
    call: OwnerCall
    cut_delta: int = 0  # a joined launch gives the hand-off's C - B back (negative)
    boot_slim: int = 0  # slimmable tokens of the boot this registering call ends
    registers: bool = False
    growth: int = 0  # for a help call: what its result added to the next call's context


@dataclass
class _Owner:
    root: bool
    entries: list


def _answer(calls, start):
    """Index of the first call at or after `start` whose gate answered `handoff`."""
    return next((index for index in range(start, len(calls))
                 if calls[index].gate is not None and calls[index].gate.action == "handoff"), None)


def _entries(launch, first, last, cut_delta):
    calls = launch.calls
    entries = []
    for index in range(first, last):
        call = calls[index]
        following = calls[index + 1].context if index + 1 < len(calls) else call.context
        entries.append(_Entry(call, growth=max(0, following - call.context) if call.help else 0))
    entries[0].cut_delta = cut_delta
    return entries


def _owners(lineage):
    """The virtual owners of a lineage: each observed `handoff` relaunch undone (D5)."""
    launches = [launch for launch in lineage.launches if launch.calls]
    owners, joined = [], None
    for position, launch in enumerate(launches):
        following = launches[position + 1] if position + 1 < len(launches) else None
        continuing = joined is not None
        first, delta = joined or (0, 0)
        last, joined = len(launch.calls), None
        if launch.transfer == "handoff" and following is not None \
                and following.registered_index is not None:
            answer = _answer(launch.calls, first)
            if answer is not None:
                last = answer + 1
                registering = following.calls[following.registered_index]
                joined = (following.registered_index, registering.context - launch.calls[answer].context)
        entries = _entries(launch, first, last, delta)
        if continuing:
            owners[-1].entries += entries
            continue
        owners.append(_Owner(launch.calls[0].is_root, entries))
        index = launch.registered_index
        if index is not None and index < last:
            entries[index].registers = True
            entries[index].boot_slim = sum(call.slimmable for call in launch.calls[:index + 1])
    return owners


# ---- pricing ----------------------------------------------------------------------


def _dollars(model, *, read=0, write=0, output=0):
    usage = {"input_tokens": 0, "output_tokens": output, "cache_read_input_tokens": read,
             "cache_creation_input_tokens": write,
             "cache_creation": {"ephemeral_5m_input_tokens": write, "ephemeral_1h_input_tokens": 0}}
    return usage_cost(model, usage)[0]


def _boot_dollars(model_id, boot_model, group, slim):
    """The modelled boot of `group`: m calls growing linearly from S to B, 5-minute writes."""
    end = boot_model.boot_end[group] - (boot_model.slimmable[group] if slim else 0)
    count, start = boot_model.boot_calls[group], boot_model.start
    contexts = [end] if count == 1 else [start + (end - start) * step // (count - 1)
                                         for step in range(count)]
    total, previous = 0.0, 0
    for context in contexts:
        total += _dollars(model_id, read=min(previous, context), write=max(0, context - previous),
                          output=boot_model.boot_output)
        previous = context
    return total


def _shifted(call, cut):
    """(fresh, read, write 5m, write 1h) of `call` with `cut` tokens of context removed."""
    fresh, read, write_5m, write_1h = call.fresh, call.read, call.write_5m, call.write_1h
    if cut >= 0:
        left = cut
        taken = min(left, read)
        read, left = read - taken, left - taken
        taken = min(left, write_5m)
        write_5m, left = write_5m - taken, left - taken
        taken = min(left, write_1h)
        write_1h, left = write_1h - taken, left - taken
        fresh -= min(left, fresh)
    elif call.death and call.is_root:
        write_1h -= cut
    elif call.death:
        write_5m -= cut
    else:
        read -= cut
    return fresh, read, write_5m, write_1h


class _State:
    """One virtual owner's running state."""

    def __init__(self, root):
        self.root = root
        self.cut = 0
        self.registered = False
        self.baseline = 0
        self.notified = False  # the meter's latch: a crossing was reported and not yet cleared
        self.pending = False  # a reported crossing waiting for a Bash call with no child out
        self.prev_end = None
        self.prev_context = 0


class _Replay:
    def __init__(self, lineage, arm, model):
        self.lineage, self.arm, self.model = lineage, arm, model
        self.dollars = lineage.descendant_dollars
        self.handoffs = self.deaths = self.streak = 0
        self.top_gate = None
        self.trace = []

    def run(self):
        for owner in _owners(self.lineage):
            state = _State(owner.root)
            for entry in owner.entries:
                self._step(state, entry)
        return Outcome(self.dollars, self.handoffs, self.deaths, max(self.trace, default=0),
                       tuple(self.trace))

    def _step(self, state, entry):
        call = entry.call
        state.cut += entry.cut_delta
        if self.arm.boot == "slim":
            state.cut += entry.boot_slim
        if self.arm.help == "drop" and call.help:
            state.cut += entry.growth
            return
        registered = state.registered
        context = self._price(state, call)
        self.trace.append(context)
        if entry.registers:
            state.registered, state.baseline = True, context
        if self._hands_off(state, call, context, registered):
            self._hand_off(state, call, context)

    def _price(self, state, call):
        fresh, read, write_5m, write_1h = _shifted(call, state.cut)
        context = fresh + read + write_5m + write_1h
        subagent = not state.root
        if subagent:
            write_5m, write_1h = write_5m + write_1h, 0
        known = state.prev_end is not None
        gap = call.start - state.prev_end if known else 0.0
        death = call.death
        if (subagent and call.is_root and known and gap > MADE_DEATH_GAP
                and state.prev_context > MIN_DEATH_CONTEXT):
            write_5m, read, death = write_5m + read, 0, True
        pings = 0
        if death and known and (self.arm.keepalive
                                or (state.root and not call.is_root and gap <= REVIVE_GAP)):
            write = max(0, context - state.prev_context)
            read = max(0, context - fresh - write)
            write_5m, write_1h = (write, 0) if subagent or not call.is_root else (0, write)
            death = False
            if self.arm.keepalive:
                pings = max(0, math.ceil(gap / PING_SECONDS) - 1)
        self.deaths += death
        priced = replace(call, fresh=fresh, read=read, write_5m=write_5m, write_1h=write_1h)
        self.dollars += call_cost(priced) + pings * _dollars(call.model, read=state.prev_context)
        state.prev_end, state.prev_context = call.end, context
        return context

    def _capped(self, budget):
        return budget.cap is not None and self.streak >= budget.cap

    def _hands_off(self, state, call, context, registered):
        gate, budget = call.gate, self.arm.budget
        if gate is not None:
            if self.top_gate is None or gate.phase > self.top_gate:
                self.streak, self.top_gate = 0, gate.phase
        if call.mark_progress == "advanced":
            self.streak = 0
        if budget is None:
            return False
        if gate is not None:
            if gate.handoff_path:
                return False
            action = select_phase_action(
                direct=self.lineage.direct, turn_count=gate.turn_count, context_tokens=context,
                turn_ceiling=budget.turn_ceiling,
                context_ceiling=handoff_threshold(budget, gate.phase + 1) + budget.context_headroom,
                turn_headroom=budget.turn_headroom, context_headroom=budget.context_headroom,
                next_needs_context=gate.next_needs_context,
                artifacts_sufficient=gate.artifacts_sufficient,
                remainder_self_contained=gate.remainder_self_contained)
            return action == "handoff" and not self._capped(budget)
        if not (registered and call.bash):
            return False
        if context >= crossing_threshold(budget, call.phase, state.baseline):
            if not state.notified:
                state.notified = state.pending = True
        else:
            state.notified = False
        if not state.pending or call.children_out:
            return False
        if self._capped(budget):
            state.pending = False
            return False
        return True

    def _wake(self, state, call, context):
        if state.root:
            return context
        return next((held for end, held in reversed(self.lineage.relauncher)
                     if end <= call.start), None)

    def _hand_off(self, state, call, context):
        model, group = self.model, phase_group(call.phase)
        slim = self.arm.boot == "slim"
        end = model.boot_end[group] - (model.slimmable[group] if slim else 0)
        overhead = model.overhead_calls * _dollars(call.model, read=context, output=model.boot_output)
        woken = self._wake(state, call, context)
        wake = 0.0 if woken is None else _dollars(call.model, read=woken)
        self.dollars += overhead + wake + _boot_dollars(call.model, model, group, slim)
        state.cut += context - end
        state.root, state.registered, state.baseline = False, True, end
        state.pending = state.notified = False
        state.prev_context = end
        self.streak += 1
        self.handoffs += 1


def observed(lineage: Lineage) -> Outcome:
    """The identity replay: the lineage as observed, with no normalisation or boot model."""
    calls = [call for launch in lineage.launches for call in launch.calls]
    return Outcome(sum(call_cost(call) for call in calls) + lineage.descendant_dollars,
                   lineage.facts.get("handoffs", 0), sum(call.death for call in calls),
                   max((call.context for call in calls), default=0),
                   tuple(call.context for call in calls))


def replay(lineage: Lineage, arm: Arm, model: BootModel) -> Outcome:
    """`lineage` priced under `arm`: normalised, then walked with the arm's policy."""
    return _Replay(lineage, arm, model).run()


# ---- the keep rule, the arms table and the sweep ----------------------------------


def keep_rule(savings: list[float]) -> Verdict:
    """D8: mean saving above 0 and a one-sided 90% lower bound above 0, over two or more."""
    count = len(savings)
    if not count:
        return Verdict(0.0, 0.0, 0.0, False)
    mean = statistics.fmean(savings)
    spread = statistics.stdev(savings) if count >= 2 else 0.0
    lower = mean - ONE_SIDED_90 * spread / math.sqrt(count)
    return Verdict(mean, lower, sum(saving > 0 for saving in savings) / count,
                   count >= 2 and mean > 0 and lower > 0)


class _Evaluation:
    """The outcomes of every arm priced so far over the lineages in scope."""

    def __init__(self, lineages, model):
        self.lineages, self.model = lineages, model
        self.delivered = sum(lineage.delivered for lineage in lineages)
        self._outcomes = {}

    def outcomes(self, arm):
        key = replace(arm, name="")
        if key not in self._outcomes:
            self._outcomes[key] = [replay(lineage, arm, self.model) for lineage in self.lineages]
        return self._outcomes[key]

    def total(self, arm):
        return sum(outcome.dollars for outcome in self.outcomes(arm))

    def verdict(self, simpler, arm):
        return keep_rule([before.dollars - after.dollars for before, after
                          in zip(self.outcomes(simpler), self.outcomes(arm))])

    def row(self, arm, step, spec, simpler, label=None):
        """One `simulated` row; its saving is against `simpler` (None: the baseline row)."""
        outcomes, base = self.outcomes(arm), self.outcomes(BASELINE)
        verdict = Verdict(0.0, 0.0, 0.0, False) if simpler is None else self.verdict(simpler, arm)
        count = len(outcomes) or 1
        handoffs = sum(outcome.handoffs for outcome in outcomes)
        return {
            "arm": arm.name, "step": step, "spec": spec,
            "dollars_per_delivered": self.total(arm) / self.delivered if self.delivered else None,
            "mean_saving": verdict.mean, "lower_bound": verdict.lower_bound,
            "share_saving": verdict.share, "handoffs_per_issue": handoffs / count,
            "deaths_per_issue": sum(outcome.deaths for outcome in outcomes) / count,
            "peak_p90": percentile([outcome.peak for outcome in outcomes], 90),
            "verdict": label or ("keep" if verdict.keep else "reject"),
            "live_confirmation_required": handoffs > sum(outcome.handoffs for outcome in base),
        }


def compare(lineages, model, arms: list[Arm]) -> list[dict]:
    """Rows for doc["simulated"]: the baseline, then each `--policy` arm against it."""
    evaluation = _Evaluation(lineages, model)
    rows = [evaluation.row(BASELINE, "baseline", _spec_of(BASELINE), None, "baseline")]
    return rows + [evaluation.row(arm, "policy", _spec_of(arm), BASELINE) for arm in arms]


class _Candidate(NamedTuple):
    step: str
    own: tuple  # the items this step adds
    items: tuple  # every item of the choices so far plus `own`, in step order
    arm: Arm

    @property
    def spec(self):
        return ",".join(self.items)


class _Sweep:
    """The coordinate pass of D18: each step chooses on the choices of the steps before."""

    def __init__(self, lineages, model):
        self.evaluation = _Evaluation(lineages, model)
        self.model = model
        self.choices = {}
        self.rows = []

    def candidate(self, step, items):
        own = tuple(items)
        merged = {**self.choices, step: own}
        flat = tuple(item for name in STEPS for item in merged.get(name, ()))
        spec = ",".join(flat)
        return _Candidate(step, own, flat, _arm(spec.replace("=", ":") or "baseline", spec))

    def current(self):
        return self.candidate("boot", self.choices.get("boot", ()))

    def emit(self, candidates, simpler, chosen, label=None):
        for found in candidates:
            self.rows.append(self.evaluation.row(
                found.arm, found.step, found.spec, simpler.arm,
                label or ("chosen" if found is chosen else "not chosen")))

    def best(self, candidates, simpler):
        """The cheapest candidate (the simpler one on a tie) when it passes the keep rule."""
        best = min(candidates, key=lambda found: (self.evaluation.total(found.arm),
                                                  found is not simpler))
        if best is simpler or self.evaluation.verdict(simpler.arm, best.arm).keep:
            return best
        return simpler

    def step(self, step, options):
        simpler = self.current()
        candidates = [self.candidate(step, items) for items in options]
        chosen = self.best(candidates, simpler)
        self.emit(candidates, simpler, chosen if chosen is not simpler else None)
        if chosen is not simpler:
            self.choices[step] = chosen.own

    def thresholds(self):
        singles = [self.candidate("threshold", (f"threshold={tokens}",)) for tokens in THRESHOLDS]
        reference = singles[THRESHOLDS.index(ORIGIN.threshold)]
        never = self.candidate("threshold", ("threshold=never",))
        chosen = self.best(singles, reference)
        grid = []
        ends = self.model.boot_end
        if ends["0-5"] and abs(ends["6-7"] - ends["0-5"]) / ends["0-5"] > PHASE_SPREAD:
            grid = [self.candidate("threshold", (f"threshold:0-5={early}", f"threshold:6-7={late}"))
                    for early in GRID_THRESHOLDS for late in GRID_THRESHOLDS]
        winner = self.best(grid, chosen) if grid else chosen
        self.emit(singles, reference, winner)
        self.emit([never], reference, None, "info")
        self.emit(grid, chosen, winner)
        if winner is not reference:
            self.choices["threshold"] = winner.own

    def keepalive(self):
        simpler = self.current()
        self.emit([self.candidate("keepalive", ("keepalive=on",))], simpler, None, "info")

    def final(self):
        evaluation = self.evaluation
        passed = []
        for step in KEPT_STEPS:
            if step not in self.choices:
                continue
            spec = ",".join(self.choices[step])
            row = evaluation.row(_arm(step, spec), "final", spec, BASELINE)
            self.rows.append(row)
            if row["verdict"] == "keep":
                passed.append(step)
        if passed:
            spec = ",".join(item for step in passed for item in self.choices[step])
            self.rows.append(evaluation.row(_arm("combined", spec), "final", spec, BASELINE))


def sweep(lineages, model) -> list[dict]:
    """The D18 coordinate pass: boot, thresholds, guard, cap, help, keepalive, final."""
    run = _Sweep(lineages, model)
    run.step("boot", [("boot=slim",)])
    run.thresholds()
    run.step("guard", [(f"guard={tokens}",) for tokens in GUARDS])
    run.step("cap", [(f"cap={count}",) for count in CAPS])
    run.step("help", [("help=drop",)])
    run.keepalive()
    run.final()
    return run.rows


# ---- calibration ------------------------------------------------------------------


def calibration(lineages, model) -> dict:
    """The identity check, the modelled boots against the observed ones, and the model."""
    error = max((abs(observed(lineage).dollars - lineage.facts["total_dollars"])
                 for lineage in lineages), default=0.0)
    boots = []
    for lineage in lineages:
        for launch in lineage.launches:
            found = boot_facts(launch)
            if found is None:
                continue
            group = found[0]
            boot = launch.calls[:launch.registered_index + 1]
            boots.append({"phase_group": group,
                          "observed_dollars": sum(call_cost(call) for call in boot),
                          "modelled_dollars": _boot_dollars(boot[-1].model, model, group, False)})
    return {"identity_matches": error <= 1e-9, "identity_max_error": error, "boots": boots,
            "model": {"start": model.start, "boot_calls": model.boot_calls,
                      "boot_end": model.boot_end, "slimmable": model.slimmable,
                      "overhead_calls": model.overhead_calls, "boot_output": model.boot_output,
                      "defaults": list(model.defaults)}}
