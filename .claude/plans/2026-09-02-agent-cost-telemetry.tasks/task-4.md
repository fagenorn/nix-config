# Task 4: `decide` — gate arithmetic and verdict ordering

**Files:**
- Modify: `scripts/agent-gate-bundle.py`
- Test: `tests/test_agent_gate_bundle.py`

**Interfaces:**
- Consumes, from Task 3: `STRATA`, `MIN_TRIALS`, `CASE_CLASSES`, `CORE_CASE_CLASSES`,
  `Diagnostic`, `render`, and the resolved evidence shape
  `{"cases": [{"case_id", "case_class", "strata": {<s>: {"context": {"base_median",
  "candidate_median", "delta_tokens", "delta_pct", "trials": {"base": [...],
  "candidate": [...]}}, "quality", "checks", "maintenance"}}}]}`, where each resolved trial is
  `{"run_id", "record_id", "input_total", "peak_ctx"}`.
- Produces, for Task 5:
  - `quality_fails(quality) -> bool`
  - `context_saves(delta_tokens, delta_pct) -> bool` and
    `context_breaches(delta_tokens, delta_pct) -> bool`
  - `checks_save(checks) -> bool` and `maintenance_saves(maintenance) -> bool`
  - `straddling_cases(evidence) -> list[tuple[int, str, str]]` — sorted
    `(case_index, case_id, stratum)` triples
  - `gate_results(evidence) -> dict` — the bundle's `gates` block
  - `decide(evidence) -> str` — one of `"approved"`, `"rejected"`, `"unmeasured"`

**Invariants:**
- `decide` is a total pure function of exactly one argument. It reads no file, no clock, no
  global mutable state, and above all no override: `override` is not in its parameter list and
  no field it reads can carry a state (D14).
- Verdict ordering is `unmeasured` → `rejected` (quality veto) → `approved` (a firing gate under
  the cross-stratum condition) → `rejected`. `unmeasured` dominates, so incomplete or
  straddling evidence can never present as a measured rejection or an approval.
- Thresholds, exactly, on `delta = candidate − base` so a saving is negative:
  saves when `delta_tokens <= -500` **or** `delta_pct <= -10`;
  breaches when `delta_tokens > 128` **and** the percentage rise exceeds `2`.
  A `delta_pct` of `None` (a zero base median) counts as exceeding any rise limit when
  `delta_tokens > 0`, and never satisfies a drop limit.
- The quality bound is one-sided: only `base − candidate > 5` fails; a candidate that scores
  higher is not a regression (D13).
- `checks` or `maintenance` being `None` means that gate cannot fire for that case — never that
  it passes (D11).
- A saving in one stratum qualifies only when the *other* stratum has no case breaching the
  no-regression bound; with a single-element `STRATA` the condition would be vacuous, which is
  why both strata are required evidence.
- A case whose index-aligned pairs straddle a gate is `unmeasured` at three pairs and at ten
  alike; nothing in this task reads `expansion` (D21).

## Steps

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_gate_bundle.py`, above the `if __name__ == "__main__":` guard.

```python
def context(base, candidate, base_trials=None, candidate_trials=None):
    delta = candidate - base
    return {"base_median": base, "candidate_median": candidate,
            "delta_tokens": delta,
            "delta_pct": (100 * delta / base) if base else None,
            "trials": {
                "base": [{"run_id": f"b{i}", "record_id": "sha256:x",
                          "input_total": total, "peak_ctx": total}
                         for i, total in enumerate(base_trials or [base] * 3)],
                "candidate": [{"run_id": f"c{i}", "record_id": "sha256:x",
                               "input_total": total, "peak_ctx": total}
                              for i, total in enumerate(candidate_trials or [candidate] * 3)]}}


def quality(base=87.0, candidate=87.0, critical=True):
    return {"critical_all_pass": critical,
            "noncritical_median": {"base": base, "candidate": candidate}}


def stratum(ctx, qual=None, checks=None, maintenance=None):
    return {"context": ctx, "quality": qual or quality(),
            "checks": checks, "maintenance": maintenance}


def evidence(*case_specs):
    """Each spec is (case_id, case_class, {stratum: stratum_dict})."""
    return {"cases": [{"case_id": cid, "case_class": klass, "strata": strata}
                      for cid, klass, strata in case_specs]}


def flat(claude, codex=None):
    """One case, both strata; `codex` defaults to a flat no-change stratum."""
    return evidence(("c1", "cold-resolution",
                     {"claude": claude, "codex": codex or stratum(context(1000, 1000))}))


class GatePrimitiveTest(unittest.TestCase):
    def test_context_saving_boundaries(self):
        self.assertTrue(gate.context_saves(-500, -1.0))       # exactly 500 tokens
        self.assertTrue(gate.context_saves(-100, -10.0))      # exactly 10 percent
        self.assertFalse(gate.context_saves(-499, -9.99))
        self.assertFalse(gate.context_saves(0, 0.0))
        self.assertFalse(gate.context_saves(-400, None))      # zero base median

    def test_context_regression_bound_is_conjunctive(self):
        self.assertFalse(gate.context_breaches(129, 2.0))     # exactly 2 percent
        self.assertFalse(gate.context_breaches(128, 2.1))     # exactly 128 tokens
        self.assertTrue(gate.context_breaches(129, 2.1))
        self.assertTrue(gate.context_breaches(400, None))     # zero base median, rose

    def test_quality_bound_is_one_sided(self):
        self.assertFalse(gate.quality_fails(quality(87.0, 82.0)))   # exactly 5 points
        self.assertTrue(gate.quality_fails(quality(87.0, 81.9)))
        self.assertFalse(gate.quality_fails(quality(80.0, 95.0)))   # candidate is better
        self.assertTrue(gate.quality_fails(quality(87.0, 87.0, critical=False)))

    def test_checks_gate_boundaries(self):
        fires = {"static_fallback_checks": {"base": 3, "candidate": 0},
                 "discovery_preflight_ops": {"base": 100, "candidate": 80}}
        self.assertTrue(gate.checks_save(fires))                     # exactly 20 percent
        self.assertFalse(gate.checks_save(None))
        self.assertFalse(gate.checks_save(dict(fires, discovery_preflight_ops={
            "base": 100, "candidate": 81})))
        self.assertFalse(gate.checks_save(dict(fires, static_fallback_checks={
            "base": 0, "candidate": 0})))                            # nothing disappeared
        self.assertFalse(gate.checks_save(dict(fires, static_fallback_checks={
            "base": 3, "candidate": 1})))                            # not every invocation

    def test_maintenance_gate_boundaries(self):
        fires = {"manual_update_sites": {"base": 8, "candidate": 4},
                 "new_hand_authored_projections": 0}
        self.assertTrue(gate.maintenance_saves(fires))               # exactly 50 percent
        self.assertFalse(gate.maintenance_saves(None))
        self.assertFalse(gate.maintenance_saves(dict(fires, manual_update_sites={
            "base": 8, "candidate": 5})))
        self.assertFalse(gate.maintenance_saves(dict(fires, manual_update_sites={
            "base": 1, "candidate": 1})))                            # no site removed
        self.assertFalse(gate.maintenance_saves(dict(
            fires, new_hand_authored_projections=1)))


class DecideTest(unittest.TestCase):
    def test_context_saving_with_a_clean_other_stratum_is_approved(self):
        self.assertEqual(gate.decide(flat(stratum(context(1000, 800)))), "approved")

    def test_no_gate_fires_is_rejected(self):
        self.assertEqual(gate.decide(flat(stratum(context(1000, 999)))), "rejected")

    def test_quality_veto_beats_a_firing_gate(self):
        vetoed = stratum(context(1000, 800), quality(87.0, 70.0))
        self.assertEqual(gate.decide(flat(vetoed)), "rejected")

    def test_a_regression_elsewhere_in_the_same_stratum_blocks_the_saving(self):
        both = evidence(
            ("c1", "cold-resolution", {"claude": stratum(context(1000, 800)),
                                       "codex": stratum(context(1000, 1000))}),
            ("c2", "routine-issue", {"claude": stratum(context(1000, 1200)),
                                     "codex": stratum(context(1000, 1000))}))
        self.assertEqual(gate.decide(both), "rejected")

    def test_a_regression_in_the_other_stratum_blocks_the_saving(self):
        blocked = flat(stratum(context(1000, 800)),
                       codex=stratum(context(1000, 1200)))
        self.assertEqual(gate.decide(blocked), "rejected")

    def test_checks_and_maintenance_gates_can_carry_an_approval_alone(self):
        checks = stratum(context(1000, 1000), checks={
            "static_fallback_checks": {"base": 3, "candidate": 0},
            "discovery_preflight_ops": {"base": 40, "candidate": 25}})
        self.assertEqual(gate.decide(flat(checks)), "approved")
        upkeep = stratum(context(1000, 1000), maintenance={
            "manual_update_sites": {"base": 8, "candidate": 3},
            "new_hand_authored_projections": 0})
        self.assertEqual(gate.decide(flat(upkeep)), "approved")

    def test_straddling_pairs_are_unmeasured_and_dominate_the_quality_veto(self):
        straddle = stratum(context(1000, 1000,
                                   base_trials=[1000, 1000, 1000],
                                   candidate_trials=[400, 1400, 1200]),
                           quality(87.0, 60.0))
        self.assertEqual(gate.straddling_cases(flat(straddle)),
                         [(0, "c1", "claude")])
        self.assertEqual(gate.decide(flat(straddle)), "unmeasured")

    def test_ten_pairs_straddle_exactly_as_three_do(self):
        base = [1000] * 10
        candidate = [400] + [1400] * 9
        straddle = stratum(context(1000, 1400, base, candidate))
        self.assertEqual(gate.decide(flat(straddle)), "unmeasured")

    def test_empty_or_absent_evidence_is_unmeasured(self):
        self.assertEqual(gate.decide({"cases": []}), "unmeasured")
        self.assertEqual(gate.decide(None), "unmeasured")

    def test_gate_results_report_every_axis(self):
        gates = gate.gate_results(flat(stratum(context(1000, 800))))
        self.assertEqual(set(gates),
                         {"quality", "context", "checks", "maintenance", "cross_stratum"})
        self.assertTrue(gates["quality"]["passed"])
        self.assertTrue(gates["context"]["claude"]["fired"])
        self.assertFalse(gates["context"]["codex"]["fired"])
        self.assertEqual(gates["context"]["claude"]["saving_cases"], ["c1"])
        self.assertEqual(gates["context"]["claude"]["breaching_cases"], [])
        self.assertTrue(gates["cross_stratum"]["claude"]["qualifies"])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest -v tests/test_agent_gate_bundle.py -k "GatePrimitive or Decide" 2>&1 | tail -8`
Expected: FAIL — `AttributeError: module 'agent_gate_bundle' has no attribute 'context_saves'`
on every test in both classes.

- [ ] **Step 3: Write the minimal implementation**

Add to `scripts/agent-gate-bundle.py`, after `resolve_trials`. Thresholds are module constants
so `gate_version: 1` names a readable set:

```python
CONTEXT_SAVE_PCT = 10.0        # a drop of at least this many percent saves
CONTEXT_SAVE_TOKENS = 500      # ... or a drop of at least this many tokens
CONTEXT_RISE_PCT = 2.0         # a rise must exceed both of these to breach
CONTEXT_RISE_TOKENS = 128
QUALITY_DROP_POINTS = 5.0      # a drop of more than this vetoes (one-sided, D13)
CHECKS_OPS_DROP_PCT = 20.0
MAINTENANCE_DROP_PCT = 50.0
```

Implement, in this order:

1. `_rise_exceeds(delta_tokens, delta_pct, limit_pct)` — `delta_tokens > 0` when `delta_pct is
   None`, else `delta_pct > limit_pct`. This is the single place the zero-base-median case is
   decided, so the saving and breach tests cannot disagree about it.
2. `context_saves(delta_tokens, delta_pct)` —
   `delta_tokens <= -CONTEXT_SAVE_TOKENS or (delta_pct is not None and
   delta_pct <= -CONTEXT_SAVE_PCT)`.
3. `context_breaches(delta_tokens, delta_pct)` —
   `delta_tokens > CONTEXT_RISE_TOKENS and _rise_exceeds(delta_tokens, delta_pct,
   CONTEXT_RISE_PCT)`.
4. `quality_fails(quality)` — `True` when `quality` is falsy, when `critical_all_pass` is not
   `True`, or when `noncritical_median["base"] - noncritical_median["candidate"] >
   QUALITY_DROP_POINTS`.
5. `checks_save(checks)` — `False` for `None`; otherwise `static_fallback_checks["candidate"]
   == 0 and static_fallback_checks["base"] > 0` **and** `discovery_preflight_ops["base"] > 0`
   with a drop of at least `CHECKS_OPS_DROP_PCT` percent, computed as
   `100 * (base - candidate) / base >= CHECKS_OPS_DROP_PCT`.
6. `maintenance_saves(maintenance)` — `False` for `None`; otherwise
   `new_hand_authored_projections == 0`, `manual_update_sites["base"] > 0`,
   `base - candidate >= 1`, and `100 * (base - candidate) / base >= MAINTENANCE_DROP_PCT`.
7. `straddling_cases(evidence)` — for each case index and stratum, zip the context's
   `trials["base"]` and `trials["candidate"]` by index. For pair `k` compute
   `pair_delta = candidate.input_total - base.input_total` and
   `pair_pct = 100 * pair_delta / base.input_total` (or `None` when the base trial is `0`).
   The case straddles when `any(context_saves(...))` **and** `any(context_breaches(...))` over
   its pairs. Return the sorted `(index, case_id, stratum)` triples (D21).
8. `gate_results(evidence)` — the `gates` block:
   - `"quality": {"passed": bool, "failing": [f"{case_id}/{stratum}", …] sorted}` over every
     case and stratum whose `quality_fails`.
   - `"context": {<stratum>: {"fired": bool, "saving_cases": [case_id…],
     "breaching_cases": [case_id…]}}` where `fired` is
     `saving_cases and not breaching_cases`, each list in case order.
   - `"checks"` and `"maintenance"`: `{<stratum>: {"fired": bool, "cases": [case_id…]}}`.
   - `"cross_stratum": {<stratum>: {"qualifies": bool, "other_breaches": bool}}` where
     `other_breaches` is true when any *other* stratum has a non-empty `breaching_cases`, and
     `qualifies` is its negation.
9. `decide(evidence)`:

```python
def decide(evidence):
    """Contract: the sole verdict authority. Takes the resolved evidence and
    nothing else — no override, no manifest, no clock (D14)."""
```

   1. `return "unmeasured"` when `evidence` is falsy, `evidence["cases"]` is empty, or
      `straddling_cases(evidence)` is non-empty.
   2. `gates = gate_results(evidence)`; `return "rejected"` when `not gates["quality"]["passed"]`.
   3. `return "approved"` when, for some stratum, `gates["cross_stratum"][s]["qualifies"]` and
      any of `gates["context"][s]["fired"]`, `gates["checks"][s]["fired"]`,
      `gates["maintenance"][s]["fired"]`.
   4. `return "rejected"`.

- [ ] **Step 4: Verify**

```sh
python3 -m unittest -v tests/test_agent_gate_bundle.py
python3 - <<'PY'
import importlib.util, inspect, pathlib
spec = importlib.util.spec_from_file_location(
    "g", pathlib.Path("scripts/agent-gate-bundle.py"))
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
params = list(inspect.signature(g.decide).parameters)
assert params == ["evidence"], params
src = inspect.getsource(g.decide)
assert "override" not in src, "decide must not mention override (D14)"
print("decide signature and body are override-free")
PY
```
Expected: the suite prints `OK`; the inline check prints its line and exits 0. Removing the
straddle clause from `decide` makes
`test_straddling_pairs_are_unmeasured_and_dominate_the_quality_veto` fail with
`'rejected' != 'unmeasured'`.

- [ ] **Step 5: Commit**

```bash
git add scripts/agent-gate-bundle.py tests/test_agent_gate_bundle.py
git commit -m "feat(agent-gate-bundle): decide the #70 gate from resolved evidence

Quality veto, three savings gates, the conjunctive no-regression bound
and the cross-stratum condition, with unmeasured dominating (D13, D21).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
