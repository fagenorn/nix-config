"""The one home of the phase-gate budget (issue 432).

``PhaseBudget`` holds the turn ceiling and headrooms of ``workflow-state progress``
and the context hand-off threshold, which may differ by phase. ``workflow-state``
resolves its omitted budget flags from ``current()`` and the context meter hands an
owner off at ``crossing_threshold(current(), phase)``; both enter the phase being
started, so the threshold of phase ``p + 1`` governs a gate that completes phase ``p``.

``parse`` reads a budget spec: items separated by ``,``, each ``key=value`` with a
decimal-integer value. The keys are ``threshold`` (at least 1; every phase),
``threshold:<a>-<b>`` (the same, for phases ``a`` to ``b`` with ``0 <= a <= b <= 7``;
a later range wins over an earlier one), ``guard`` (at least 0) and ``cap`` (at
least 1). A caller names the keys it accepts: ``PRODUCT_KNOBS`` is ``threshold`` and
``REPLAY_KNOBS`` adds ``guard`` and ``cap``. Any other item raises ``ValueError``
naming it.

``current()`` is the default budget unless the environment variable
``AGENT_PHASE_BUDGET`` holds a spec in the product grammar. That override exists
for evaluation arms; production never sets it.
"""

from __future__ import annotations

import functools
import os
import re
from dataclasses import dataclass, replace

ENVIRONMENT = "AGENT_PHASE_BUDGET"
PRODUCT_KNOBS = frozenset({"threshold"})
REPLAY_KNOBS = frozenset({"threshold", "guard", "cap"})
LAST_RANGED_PHASE = 7
RANGED_KEY = re.compile(r"threshold:([0-9]+)-([0-9]+)")
MINIMUMS = {"threshold": 1, "guard": 0, "cap": 1}


@dataclass(frozen=True)
class PhaseBudget:
    turn_ceiling: int = 120
    turn_headroom: int = 2
    context_headroom: int = 10_000
    threshold: int = 200_000
    phase_thresholds: tuple[tuple[int, int, int], ...] = ()
    guard: int = 0
    cap: int | None = None


def _value(item: str, key: str, text: str) -> int:
    if not (text.isascii() and text.isdecimal()) or int(text) < MINIMUMS[key]:
        raise ValueError(f"phase budget item {item!r}: {key} needs an integer of at least "
                         f"{MINIMUMS[key]}")
    return int(text)


def parse(spec: str, *, knobs: frozenset[str] = PRODUCT_KNOBS,
          base: PhaseBudget | None = None) -> PhaseBudget:
    """The budget `spec` describes; fields it does not name keep `base`'s values."""
    budget = PhaseBudget() if base is None else base
    named: set[str] = set()
    ranges = list(budget.phase_thresholds)
    for item in spec.split(","):
        key, equals, text = item.partition("=")
        ranged = RANGED_KEY.fullmatch(key)
        name = "threshold" if ranged else key
        if not equals or name not in MINIMUMS or name not in knobs:
            raise ValueError(f"phase budget item {item!r}: not a knob this caller accepts")
        value = _value(item, name, text)
        if ranged:
            first, last = int(ranged.group(1)), int(ranged.group(2))
            if not first <= last <= LAST_RANGED_PHASE:
                raise ValueError(f"phase budget item {item!r}: the range must satisfy "
                                 f"0 <= a <= b <= {LAST_RANGED_PHASE}")
            ranges.append((first, last, value))
            continue
        if key in named:
            raise ValueError(f"phase budget item {item!r}: {key} is given twice")
        named.add(key)
        budget = replace(budget, **{key: value})
    return replace(budget, phase_thresholds=tuple(ranges))


@functools.cache
def current() -> PhaseBudget:
    """The budget of this process: the default, or the `AGENT_PHASE_BUDGET` override."""
    value = os.environ.get(ENVIRONMENT)
    return PhaseBudget() if value is None else parse(value)


def handoff_threshold(budget: PhaseBudget, phase: int | None) -> int:
    """The context tokens at which an owner entering `phase` hands off."""
    if phase is not None:
        for first, last, tokens in reversed(budget.phase_thresholds):
            if first <= phase <= last:
                return tokens
    return budget.threshold


def crossing_threshold(budget: PhaseBudget, phase: int | None, baseline: int | None) -> int:
    """The hand-off threshold, raised to `baseline + guard` when a guard is set."""
    threshold = handoff_threshold(budget, phase)
    if budget.guard > 0 and baseline is not None:
        return max(threshold, baseline + budget.guard)
    return threshold


def select_phase_action(
    *,
    direct: bool,
    turn_count: int | None,
    context_tokens: int | None,
    turn_ceiling: int,
    context_ceiling: int,
    turn_headroom: int,
    context_headroom: int,
    next_needs_context: bool,
    artifacts_sufficient: bool,
    remainder_self_contained: bool,
) -> str:
    """Select the phase-boundary action from run identity and phase inputs.

    The phase budget is the turn and context ceilings with their headrooms; this
    function never sees the attempt budget's wall clock, and ``delegate`` does not
    reset it. A ``direct`` run (by its identity) selects a self-contained remainder
    first, then an eligible ``fresh_start``, known near-ceiling usage, work that
    needs no context, and otherwise ``continue``. Every non-direct run retains the
    complete order: eligible ``fresh_start``, known near-ceiling usage, measured
    self-contained delegation, work that needs no context, then ``continue``.

    Unmeasurable usage is not a budget signal. A harness that exposes no
    authoritative context-token count would otherwise pin every non-direct run to
    ``handoff`` at its first phase gate, so an unknown count only withholds
    ``delegate`` -- which still requires usage measured below both ceilings.
    """
    if direct:
        if remainder_self_contained:
            return "delegate"
        if not next_needs_context and artifacts_sufficient:
            return "fresh_start"
        if (
            turn_count is not None
            and turn_count >= turn_ceiling - turn_headroom
        ) or (
            context_tokens is not None
            and context_tokens >= context_ceiling - context_headroom
        ):
            return "handoff"
        if not next_needs_context:
            return "handoff"
        return "continue"

    if not next_needs_context and artifacts_sufficient:
        return "fresh_start"
    if (
        turn_count is not None
        and turn_count >= turn_ceiling - turn_headroom
    ) or (
        context_tokens is not None
        and context_tokens >= context_ceiling - context_headroom
    ):
        return "handoff"
    if (
        remainder_self_contained
        and turn_count is not None
        and context_tokens is not None
    ):
        return "delegate"
    if not next_needs_context:
        return "handoff"
    return "continue"
