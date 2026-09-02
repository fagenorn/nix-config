# Task 3: Trials manifest loading and `resolve_trials`

**Files:**
- Create: `scripts/agent-gate-bundle.py`
- Create: `tests/test_agent_gate_bundle.py`
- Modify: `justfile`

**Interfaces:**
- Consumes: the record wire shape Task 2 fixed — a document with `schema_version`, `kind`,
  `record_id`, `generated_at`, `window`, `strata`, `fleet`, `notes`, where
  `strata.<name>.runs[*]` carries `run_id`, `tokens.input_total` and `peak_ctx`. Nothing is
  imported across scripts (D25).
- Produces, for Tasks 4–5:
  - `SCHEMA_VERSION = 1`, `TRIALS_KIND = "agent-gate-trials"`,
    `BUNDLE_KIND = "agent-gate-bundle"`, `GATE_CONTRACT = "issue-70"`, `GATE_VERSION = 1`,
    `STRATA = ("claude", "codex")`, `MIN_TRIALS = 3`,
    `CASE_CLASSES = ("cold-resolution", "routine-issue", "fuzzy-design", "review-ship",
    "repo-specific")`, `CORE_CASE_CLASSES = CASE_CLASSES[:4]`.
  - `class ManifestError(Exception)` carrying `.diagnostics: list[Diagnostic]`.
  - `Diagnostic = namedtuple("Diagnostic", "code path message")` and
    `render(diagnostics) -> list[str]` returning `sorted(f"{code} {path}: {message}")`.
  - `canonical_digest(body) -> str` — `"sha256:" + sha256` over canonical JSON, identical in
    behavior to `agent-costs.py`'s (D9, D25).
  - `load_manifest(path) -> dict` — parsed, structurally valid manifest, or `ManifestError`.
  - `load_record(path) -> dict` — parsed record document; raises `ValueError` with a readable
    message for an unreadable file, invalid JSON, a duplicate key, or a non-object document.
  - `resolve_trials(manifest, loader=load_record) -> tuple[dict | None, list[Diagnostic]]`.

**Invariants:**
- Manifest *document* faults raise `ManifestError`; evidence faults are returned as diagnostics
  (D31). `resolve_trials` never raises for bad evidence and never partially returns: it yields
  `(None, diagnostics)` whenever `diagnostics` is non-empty, and `(evidence, [])` otherwise.
- The resolved evidence is the exact object Task 5 writes as the bundle's `evidence` member and
  Task 4's `decide` consumes; nothing else is passed to `decide` (D14).
- A trial is resolved by *recomputing* the cited record's digest and extracting the cited
  `run_id` from the cited stratum — the manifest's numbers are never trusted, and no measurement
  is read from the manifest (D10).
- Both strata and `quality` are required on every case; `checks` and `maintenance` are optional,
  and their absence resolves to `None`, never to a passing value (D11).
- Every `identity.pinned` leaf must be equal between `base` and `candidate`; every
  `identity.bound` leaf must merely be present and non-empty (D19).
- There is no `required` flag anywhere in the manifest schema, and an unknown key is a document
  fault, so one cannot be introduced by a manifest author (D20, D31).
- This task adds no CLI. `scripts/agent-gate-bundle.py` has no `argparse` import, no `main`, and
  no `if __name__ == "__main__":` block until Task 5.

## Steps

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_gate_bundle.py`:

```python
"""Offline tests for scripts/agent-gate-bundle.py.

Run: python3 -m unittest -v tests/test_agent_gate_bundle.py
"""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "agent-gate-bundle.py"

_spec = importlib.util.spec_from_file_location("agent_gate_bundle", SCRIPT)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

IDENTITY = {
    "bound": {"commit": {"base": "aaa", "candidate": "bbb"},
              "project_contract_version": {"base": "1", "candidate": "1"},
              "shared_platform_version": {"base": "1", "candidate": "1"}},
    "pinned": {"evaluator_version": {"base": "e1", "candidate": "e1"},
               "rubric_version": {"base": "r1", "candidate": "r1"},
               "environment_fingerprint": {"base": "f1", "candidate": "f1"},
               "builds": {
                   "claude": {"agent": {"base": "a1", "candidate": "a1"},
                              "model": {"base": "m1", "candidate": "m1"}},
                   "codex": {"agent": {"base": "a2", "candidate": "a2"},
                             "model": {"base": "m2", "candidate": "m2"}}}},
}


def make_record(tmp, name, runs):
    """Write a record document; `runs` maps stratum -> [(run_id, input_total)]."""
    body = {
        "schema_version": 1, "kind": "agent-cost-record",
        "window": {"days": 7, "cutoff_epoch": None, "strata": sorted(runs),
                   "sources": {s: "/x" for s in runs}},
        "strata": {s: {"cost_basis": "list-price", "totals": {"runs": len(v)},
                       "runs": [{"run_id": rid, "stratum": s, "project": "repo",
                                 "issue": "120", "outcome": "completed",
                                 "tokens": {"input_total": total, "fresh": total,
                                            "cache_create": 0, "cache_read": 0,
                                            "output": 0, "reasoning": None},
                                 "cost_usd": None, "peak_ctx": total,
                                 "turns": 1, "sessions": 1, "subagents": 0}
                                for rid, total in v]}
                   for s, v in runs.items()},
        "fleet": {"informative": True, "totals": {}}, "notes": "n",
    }
    document = dict(body, record_id=gate.canonical_digest(body),
                    generated_at="2026-09-02T00:00:00Z")
    path = tmp / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path, document


def trial(path, document, stratum, run_id):
    return {"record": str(path), "run_id": run_id,
            "record_id": document["record_id"]}


def make_case(tmp, case_id, case_class, totals, quality=None, **extra):
    """`totals` maps stratum -> (base list, candidate list) of input_total ints."""
    strata = {}
    for stratum, (base, candidate) in totals.items():
        sides = {}
        for side, values in (("base", base), ("candidate", candidate)):
            trials = []
            for index, total in enumerate(values):
                run_id = f"{stratum}:repo:{case_id}-{side}-{index}"
                path, document = make_record(
                    tmp, f"{case_id}-{stratum}-{side}-{index}.json",
                    {stratum: [(run_id, total)]})
                trials.append(trial(path, document, stratum, run_id))
            sides[side] = trials
        sides["quality"] = quality or {
            "critical_all_pass": True,
            "noncritical_median": {"base": 87.0, "candidate": 86.0}}
        sides.update(extra)
        strata[stratum] = sides
    return {"case_id": case_id, "case_class": case_class, "strata": strata}


def make_manifest(tmp, cases):
    return {"schema_version": 1, "kind": "agent-gate-trials",
            "identity": json.loads(json.dumps(IDENTITY)),
            "expansion": {"expanded": False, "checkpoint_ref": None},
            "cases": cases}


def full_cases(tmp, totals=None):
    """One case per core class, all with the same trial totals."""
    totals = totals or {s: ([1000, 1000, 1000], [800, 800, 800]) for s in gate.STRATA}
    return [make_case(tmp, klass, klass, totals) for klass in gate.CORE_CASE_CLASSES]


class ManifestDocumentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def write(self, payload):
        path = self.tmp / "trials.json"
        path.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                        encoding="utf-8")
        return path

    def test_valid_manifest_loads(self):
        loaded = gate.load_manifest(self.write(make_manifest(self.tmp, full_cases(self.tmp))))
        self.assertEqual(loaded["kind"], "agent-gate-trials")

    def test_missing_file_is_a_manifest_error(self):
        with self.assertRaises(gate.ManifestError):
            gate.load_manifest(self.tmp / "absent.json")

    def test_duplicate_json_key_is_a_manifest_error(self):
        with self.assertRaises(gate.ManifestError) as caught:
            gate.load_manifest(self.write('{"kind": "a", "kind": "b"}'))
        self.assertTrue(any(d.code == "JSON_INVALID" for d in caught.exception.diagnostics))

    def test_unknown_top_level_key_is_a_manifest_error(self):
        payload = make_manifest(self.tmp, full_cases(self.tmp))
        payload["state"] = "approved"
        with self.assertRaises(gate.ManifestError) as caught:
            gate.load_manifest(self.write(payload))
        codes = {d.code for d in caught.exception.diagnostics}
        self.assertIn("FIELD_UNKNOWN", codes)

    def test_unknown_case_class_is_a_manifest_error(self):
        payload = make_manifest(self.tmp, full_cases(self.tmp))
        payload["cases"][0]["case_class"] = "exempt"
        with self.assertRaises(gate.ManifestError):
            gate.load_manifest(self.write(payload))

    def test_wrong_kind_and_schema_version_are_manifest_errors(self):
        for mutate in ({"kind": "agent-gate-bundle"}, {"schema_version": 2}):
            payload = dict(make_manifest(self.tmp, full_cases(self.tmp)), **mutate)
            with self.assertRaises(gate.ManifestError):
                gate.load_manifest(self.write(payload))


class ResolveTrialsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def codes(self, manifest):
        evidence, diagnostics = gate.resolve_trials(manifest)
        return evidence, {d.code for d in diagnostics}

    def test_complete_manifest_resolves_to_evidence(self):
        manifest = make_manifest(self.tmp, full_cases(self.tmp))
        evidence, diagnostics = gate.resolve_trials(manifest)
        self.assertEqual(diagnostics, [])
        self.assertEqual(len(evidence["cases"]), 4)
        context = evidence["cases"][0]["strata"]["claude"]["context"]
        self.assertEqual(context["base_median"], 1000)
        self.assertEqual(context["candidate_median"], 800)
        self.assertEqual(context["delta_tokens"], -200)
        self.assertAlmostEqual(context["delta_pct"], -20.0)
        self.assertEqual(len(context["trials"]["base"]), 3)
        self.assertEqual(context["trials"]["base"][0]["input_total"], 1000)
        self.assertIsNone(evidence["cases"][0]["strata"]["claude"]["checks"])
        self.assertIsNone(evidence["cases"][0]["strata"]["claude"]["maintenance"])

    def test_missing_core_case_class_is_diagnosed(self):
        cases = full_cases(self.tmp)[:3]
        evidence, codes = self.codes(make_manifest(self.tmp, cases))
        self.assertIsNone(evidence)
        self.assertIn("CASE_CLASS_MISSING", codes)

    def test_empty_cases_is_diagnosed(self):
        evidence, codes = self.codes(make_manifest(self.tmp, []))
        self.assertIsNone(evidence)
        self.assertIn("CASES_EMPTY", codes)

    def test_two_trials_a_side_is_insufficient(self):
        totals = {s: ([1000, 1000], [800, 800]) for s in gate.STRATA}
        manifest = make_manifest(self.tmp, full_cases(self.tmp, totals))
        evidence, diagnostics = gate.resolve_trials(manifest)
        self.assertIsNone(evidence)
        rendered = gate.render(diagnostics)
        self.assertTrue(any(
            line.startswith("TRIALS_INSUFFICIENT $.cases[0].strata.claude: "
                            "2 paired trials, 3 required") for line in rendered), rendered)

    def test_unequal_side_lengths_are_unpaired(self):
        totals = {s: ([1000, 1000, 1000], [800, 800, 800, 800]) for s in gate.STRATA}
        evidence, codes = self.codes(make_manifest(self.tmp, full_cases(self.tmp, totals)))
        self.assertIsNone(evidence)
        self.assertIn("TRIALS_UNPAIRED", codes)

    def test_absent_stratum_is_diagnosed(self):
        cases = full_cases(self.tmp)
        del cases[0]["strata"]["codex"]
        evidence, codes = self.codes(make_manifest(self.tmp, cases))
        self.assertIsNone(evidence)
        self.assertIn("STRATUM_MISSING", codes)

    def test_absent_quality_is_diagnosed(self):
        cases = full_cases(self.tmp)
        del cases[0]["strata"]["claude"]["quality"]
        evidence, codes = self.codes(make_manifest(self.tmp, cases))
        self.assertIsNone(evidence)
        self.assertIn("QUALITY_MISSING", codes)

    def test_pinned_identity_mismatch_is_diagnosed(self):
        manifest = make_manifest(self.tmp, full_cases(self.tmp))
        manifest["identity"]["pinned"]["rubric_version"]["candidate"] = "r2"
        evidence, codes = self.codes(manifest)
        self.assertIsNone(evidence)
        self.assertIn("IDENTITY_MISMATCH", codes)

    def test_bound_identity_may_differ_but_not_be_empty(self):
        manifest = make_manifest(self.tmp, full_cases(self.tmp))
        self.assertEqual(gate.resolve_trials(manifest)[1], [])   # base != candidate commit
        manifest["identity"]["bound"]["commit"]["candidate"] = ""
        evidence, codes = self.codes(manifest)
        self.assertIsNone(evidence)
        self.assertIn("IDENTITY_INCOMPLETE", codes)

    def test_unreadable_missing_and_tampered_records_are_diagnosed(self):
        manifest = make_manifest(self.tmp, full_cases(self.tmp))
        claude = manifest["cases"][0]["strata"]["claude"]
        claude["base"][0]["record"] = str(self.tmp / "gone.json")
        evidence, codes = self.codes(manifest)
        self.assertIsNone(evidence)
        self.assertIn("RECORD_UNREADABLE", codes)

        manifest = make_manifest(self.tmp, full_cases(self.tmp))
        claude = manifest["cases"][0]["strata"]["claude"]
        path = Path(claude["base"][0]["record"])
        document = json.loads(path.read_text(encoding="utf-8"))
        document["strata"]["claude"]["runs"][0]["tokens"]["input_total"] = 1
        path.write_text(json.dumps(document), encoding="utf-8")
        evidence, codes = self.codes(manifest)
        self.assertIsNone(evidence)
        self.assertIn("RECORD_DIGEST_MISMATCH", codes)

        manifest = make_manifest(self.tmp, full_cases(self.tmp))
        manifest["cases"][0]["strata"]["claude"]["base"][0]["run_id"] = "claude:repo:nope"
        evidence, codes = self.codes(manifest)
        self.assertIsNone(evidence)
        self.assertIn("RUN_NOT_FOUND", codes)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest tests/test_agent_gate_bundle.py 2>&1 | tail -5`
Expected: FAIL — `FileNotFoundError` / `AttributeError: 'NoneType' object has no attribute
'exec_module'` at import time, because `scripts/agent-gate-bundle.py` does not exist.

- [ ] **Step 3: Write the minimal implementation**

Create `scripts/agent-gate-bundle.py`, executable (`chmod +x`), with a shebang
`#!/usr/bin/env python3` and a module docstring naming issue #70 as the contract it applies and
`agent-costs.py --format json` as the source of its inputs. Standard library only:
`hashlib`, `json`, `statistics`, `collections.namedtuple`, `pathlib.Path`.

**3a. Constants and diagnostics.** Define the constants under **Produces**, plus:

```python
Diagnostic = namedtuple("Diagnostic", "code path message")


def render(diagnostics):
    """Contract: sorted 'CODE $.path: message' lines, the agent-evidence vocabulary."""
    return sorted(f"{d.code} {d.path}: {d.message}" for d in diagnostics)


class ManifestError(Exception):
    """A manifest document fault: the tool cannot proceed at all (D31)."""

    def __init__(self, diagnostics):
        super().__init__("; ".join(render(diagnostics)))
        self.diagnostics = list(diagnostics)
```

`canonical_digest(body)` is byte-for-byte the same contract as `agent-costs.py`'s: a
`"sha256:"`-prefixed sha256 over
`json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)` encoded UTF-8.

**3b. `load_manifest(path)`.** Read UTF-8; `json.loads(..., object_pairs_hook=<reject
duplicates>)`, the hook raising `ValueError(f"duplicate JSON key {key!r}")`. Map the failures to
`ManifestError` with one diagnostic each: `MANIFEST_READ_ERROR $` for `OSError`/`UnicodeError`,
`JSON_INVALID $` for `json.JSONDecodeError` and the duplicate-key `ValueError`. Then validate
structurally, collecting *every* violation before raising (the `agent-evidence.py` one-pass
convention):

| Level | Allowed keys (all required unless noted) | Value rule |
|---|---|---|
| `$` | `schema_version`, `kind`, `identity`, `expansion`, `cases` | `schema_version == 1`, `kind == TRIALS_KIND` |
| `$.identity` | `bound`, `pinned` | objects |
| `$.identity.bound` | `commit`, `project_contract_version`, `shared_platform_version` | each an object with exactly `base`, `candidate`, both strings |
| `$.identity.pinned` | `evaluator_version`, `rubric_version`, `environment_fingerprint`, `builds` | the first three as above; `builds` an object keyed by exactly `STRATA`, each with exactly `agent`, `model`, each a `base`/`candidate` string pair |
| `$.expansion` | `expanded` (bool), `checkpoint_ref` (string or null) | — |
| `$.cases[i]` | `case_id` (string), `case_class` (in `CASE_CLASSES`), `strata` (object keyed by a subset of `STRATA`) | — |
| `$.cases[i].strata.<s>` | `base`, `candidate` (lists), `quality`; optional `checks`, `maintenance` | — |
| `…strata.<s>.base[j]` | `record`, `run_id`, `record_id` (strings) | — |
| `…strata.<s>.quality` | `critical_all_pass` (bool), `noncritical_median` (`base`/`candidate` numbers) | — |
| `…strata.<s>.checks` | `static_fallback_checks`, `discovery_preflight_ops`, each a `base`/`candidate` integer pair | present ⇒ both required |
| `…strata.<s>.maintenance` | `manual_update_sites` (`base`/`candidate` integers), `new_hand_authored_projections` (integer) | present ⇒ both required |

Diagnostic codes: `FIELD_REQUIRED` (absent), `FIELD_UNKNOWN` (a key not in the row's allowed
set), `FIELD_TYPE` (wrong JSON type), `FIELD_VALUE` (`schema_version`, `kind`, or `case_class`
outside its fixed set). Paths use the `$.cases[0].strata.claude.base[1].record` form. Note that
`strata` may name a *subset* here: a stratum missing altogether is an evidence fault
diagnosed by `resolve_trials`, not a document fault (D11, D31).

**3c. `load_record(path)`.** Same read-and-parse with the duplicate-key hook, raising
`ValueError(str(error))` on any failure and on a document that is not a JSON object. It performs
no schema validation: a record whose shape is wrong surfaces as `RECORD_DIGEST_MISMATCH` or
`RUN_NOT_FOUND`, and a missing `record_id` is `RECORD_DIGEST_MISMATCH`.

**3d. `resolve_trials(manifest, loader=load_record)`.** Collect diagnostics; never raise.

1. **Identity.** For each `bound` field and each `pinned` leaf (walking `builds` two levels
   deeper), require `base` and `candidate` to be present and non-empty after `str.strip()` —
   otherwise `IDENTITY_INCOMPLETE` at that leaf's path with the message
   `"field is required and must be non-empty"`. For `pinned` leaves only, `base != candidate`
   is `IDENTITY_MISMATCH` with `"base {base!r} != candidate {candidate!r}"` (D19).
2. **Corpus.** `CASES_EMPTY $.cases: at least one case is required` for an empty list. For each
   of `CORE_CASE_CLASSES` absent from the manifest's `case_class` values,
   `CASE_CLASS_MISSING $.cases: required case class {klass!r} is absent` (D20).
3. **Per case `i`, per stratum `s` in `STRATA`** (both, always):
   - absent from `case["strata"]` → `STRATUM_MISSING $.cases[i].strata.<s>: both strata are
     required evidence` and skip the rest of this stratum (D11).
   - `quality` absent → `QUALITY_MISSING $.cases[i].strata.<s>.quality: quality is required
     evidence`.
   - `len(base) != len(candidate)` → `TRIALS_UNPAIRED $.cases[i].strata.<s>: base {n} trials,
     candidate {m} trials` and skip the trial resolution for this stratum.
   - equal lengths below `MIN_TRIALS` → `TRIALS_INSUFFICIENT $.cases[i].strata.<s>: {n} paired
     trials, {MIN_TRIALS} required`.
   - resolve each cited trial, in `base` then `candidate` order, at path
     `$.cases[i].strata.<s>.<side>[j]`:
     - `loader(Path(entry["record"]))`; `ValueError` → `RECORD_UNREADABLE` with the message.
     - recompute `canonical_digest({k: v for k, v in document.items() if k not in
       ("record_id", "generated_at")})`; when it differs from `document.get("record_id")` **or**
       from `entry["record_id"]` → `RECORD_DIGEST_MISMATCH` with
       `"recomputed {digest} does not match the cited digest"` (D10).
     - find the run whose `run_id == entry["run_id"]` in
       `document["strata"][s]["runs"]` (treating an absent stratum as no runs) → absent →
       `RUN_NOT_FOUND $…: run {run_id!r} is not in stratum {s!r} of the cited record`.
     - resolved trial: `{"run_id": …, "record_id": document["record_id"],
       "input_total": run["tokens"]["input_total"], "peak_ctx": run["peak_ctx"]}`.
4. **Assemble** — only when no diagnostic was collected. Per case and stratum:
   - `base_median = statistics.median(t["input_total"] for t in base)`, same for candidate.
   - `delta_tokens = candidate_median - base_median` (negative is a saving).
   - `delta_pct = 100 * delta_tokens / base_median` when `base_median > 0`, else `None`.
   - `context = {"base_median", "candidate_median", "delta_tokens", "delta_pct",
     "trials": {"base": [...], "candidate": [...]}}` (D30).
   - stratum entry: `{"context": context, "quality": <copied>, "checks": <copied or None>,
     "maintenance": <copied or None>}`.
   - case entry: `{"case_id", "case_class", "strata": {…}}`, cases in manifest order.
5. Return `(None, sorted_diagnostics)` when any diagnostic exists, else `(evidence, [])`, with
   the diagnostics sorted by `(code, path, message)`.

**3e. `justfile`.** Add `tests/test_agent_gate_bundle.py` to the `agent-workflow-tests` recipe's
list, immediately after `tests/test_agent_costs.py`, preserving the trailing `\` continuations.
Do **not** add an `agent-gate-bundle` recipe yet — the script has no CLI until Task 5.

- [ ] **Step 4: Verify**

```sh
python3 -m unittest -v tests/test_agent_gate_bundle.py
just agent-workflow-tests 2>&1 | tail -3
if grep -qE '^import argparse|def main\(' scripts/agent-gate-bundle.py; then exit 1; fi
grep -c 'tests/test_agent_gate_bundle.py' justfile
```
Expected: the first prints `OK` with 17 tests; the second ends in `OK` with the suite count
raised by those tests; the third exits 0 (no CLI landed early); the fourth prints `1`.

- [ ] **Step 5: Commit**

```bash
git add scripts/agent-gate-bundle.py tests/test_agent_gate_bundle.py justfile
git commit -m "feat(agent-gate-bundle): load the trials manifest and resolve cited records

Document faults raise; evidence faults return diagnostics (D31). Trials
are resolved by recomputing each record's digest and extracting the
cited run (D10).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
