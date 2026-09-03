# Task 5: Bundle assembly, `--override`, exit codes, and the no-upgrade table

**Files:**
- Modify: `scripts/agent-gate-bundle.py`
- Modify: `justfile`
- Test: `tests/test_agent_gate_bundle.py`

**Interfaces:**
- Consumes, from Task 3: `SCHEMA_VERSION`, `BUNDLE_KIND`, `GATE_CONTRACT`, `GATE_VERSION`,
  `Diagnostic`, `render`, `ManifestError`, `canonical_digest`, `load_manifest`, `load_record`,
  `resolve_trials(manifest, loader=load_record) -> (evidence | None, diagnostics)`.
  From Task 4: `gate_results(evidence) -> dict`, `straddling_cases(evidence) -> list`,
  `decide(evidence) -> str`.
- Produces (the tool's final surface):
  - `class BundleIntegrityError(Exception)` — the emitter's refusal to write.
  - `assemble_bundle(manifest, evidence, diagnostics, override, state) -> dict`
  - `build_override(reason, authorized_by, authorized_at) -> dict | None` — every field a
    declared input; it reads no clock (per D38)
  - `main(argv=None) -> int`, wired as `raise SystemExit(main())`.
  - `justfile` recipe `agent-gate-bundle *args`.

**Invariants:**
- The no-upgrade invariant is enforced twice (D14). First, `state` comes only from
  `decide(evidence)`, whose parameter list has no override. Second, `assemble_bundle` re-runs
  `decide` on the body's own `evidence` member and raises `BundleIntegrityError` — writing
  nothing — when the result differs from the `state` it was handed.
- `override` is a closed four-key object, `{"reason", "authorized_by", "authorized_at",
  "scope"}`, with `scope` the literal `"further-experimentation"`. It is `null` when the flags
  are absent, and it changes neither `state` nor the exit code.
- Every hashed field is deterministic from declared inputs. `authorized_at` is therefore
  `--override-at`, a *required* companion of `--override` (like `--override-by`), validated as
  RFC3339 UTC ending in `Z` — never a clock sample. `generated_at` is the one clock read, and it
  sits outside the digest. An override-bearing bundle reproduces byte-for-byte (per D38).
- `bundle_id = canonical_digest(body)` over the bundle minus `bundle_id` and `generated_at`;
  `state`, `gates`, `evidence`, `identity`, `expansion`, `override` and `diagnostics` are all
  inside the digest, so a differing verdict is a differing bundle (D9).
- `diagnostics` is a sorted list of `CODE $.path: message` strings, empty for `approved` and
  `rejected`; only `unmeasured` populates it, and an `unmeasured` bundle always carries at
  least one (D31).
- Exit codes: `0` `approved`, `3` `rejected` or `unmeasured`, `2` tool failure — a
  `ManifestError`, a `BundleIntegrityError`, or an argparse usage error (D16). A non-zero exit
  is never an approval.
- Exactly one document goes to stdout; diagnostics for a `ManifestError` go to stderr. There is
  no `--out` (D22).

## Steps

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_gate_bundle.py`, above the `if __name__ == "__main__":` guard, and
add `import contextlib` and `import io` to its header.

```python
def run_cli(*argv):
    """main() with stdout captured; returns (exit code, parsed bundle or None)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = gate.main(list(argv))
    text = out.getvalue()
    return code, (json.loads(text) if text.strip() else None)


class BundleCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def manifest_file(self, manifest, name="trials.json"):
        path = self.tmp / name
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return str(path)

    def saving_manifest(self):
        return make_manifest(self.tmp, full_cases(self.tmp))

    def flat_manifest(self):
        totals = {s: ([1000, 1000, 1000], [999, 999, 999]) for s in gate.STRATA}
        return make_manifest(self.tmp, full_cases(self.tmp, totals))

    def test_approved_bundle_exits_zero_with_no_diagnostics(self):
        code, bundle = run_cli("--trials", self.manifest_file(self.saving_manifest()))
        self.assertEqual(code, 0)
        self.assertEqual(bundle["state"], "approved")
        self.assertEqual(bundle["kind"], "agent-gate-bundle")
        self.assertEqual(bundle["gate_contract"], "issue-70")
        self.assertEqual(bundle["gate_version"], 1)
        self.assertEqual(bundle["diagnostics"], [])
        self.assertIsNone(bundle["override"])
        self.assertEqual(bundle["identity"]["pinned"]["rubric_version"]["base"], "r1")

    def test_rejected_bundle_exits_three(self):
        code, bundle = run_cli("--trials", self.manifest_file(self.flat_manifest()))
        self.assertEqual(code, 3)
        self.assertEqual(bundle["state"], "rejected")
        self.assertEqual(bundle["diagnostics"], [])

    def test_bundle_id_is_stable_and_covers_the_state(self):
        path = self.manifest_file(self.saving_manifest())
        first = run_cli("--trials", path)[1]
        second = run_cli("--trials", path)[1]
        self.assertEqual(first["bundle_id"], second["bundle_id"])
        body = {k: v for k, v in first.items()
                if k not in ("bundle_id", "generated_at")}
        self.assertEqual(first["bundle_id"], gate.canonical_digest(body))
        other = run_cli("--trials", self.manifest_file(self.flat_manifest(), "b.json"))[1]
        self.assertNotEqual(first["bundle_id"], other["bundle_id"])

    def test_an_override_bearing_bundle_id_is_reproducible(self):
        path = self.manifest_file(self.flat_manifest(), "ovr.json")
        argv = ("--trials", path, "--override", "further experimentation approved",
                "--override-by", "anis", "--override-at", "2026-09-02T12:00:00Z")
        first, second = run_cli(*argv)[1], run_cli(*argv)[1]
        self.assertEqual(first["bundle_id"], second["bundle_id"])
        self.assertEqual(first["override"]["authorized_at"], "2026-09-02T12:00:00Z")
        later = run_cli(*argv[:-1], "2026-09-03T12:00:00Z")[1]
        self.assertNotEqual(first["bundle_id"], later["bundle_id"])

    def test_override_without_a_timestamp_is_a_usage_error(self):
        path = self.manifest_file(self.flat_manifest(), "novrat.json")
        with self.assertRaises(SystemExit) as caught:
            run_cli("--trials", path, "--override", "why", "--override-by", "anis")
        self.assertEqual(caught.exception.code, 2)

    def test_unreadable_manifest_is_exit_two_with_no_document(self):
        code, bundle = run_cli("--trials", str(self.tmp / "absent.json"))
        self.assertEqual(code, 2)
        self.assertIsNone(bundle)

    def test_emitter_refuses_a_state_the_evidence_does_not_earn(self):
        manifest = self.flat_manifest()
        evidence, diagnostics = gate.resolve_trials(manifest)
        self.assertEqual(diagnostics, [])
        with self.assertRaises(gate.BundleIntegrityError):
            gate.assemble_bundle(manifest, evidence, [], None, "approved")


class NoUpgradeTableTest(unittest.TestCase):
    """One row per manifest surface that might try to buy an approval."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def write(self, manifest, name):
        path = self.tmp / name
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return str(path)

    def rows(self):
        flat = {s: ([1000, 1000, 1000], [999, 999, 999]) for s in gate.STRATA}

        declared_state = make_manifest(self.tmp, full_cases(self.tmp))
        declared_state["state"] = "approved"

        declared_id = make_manifest(self.tmp, full_cases(self.tmp))
        declared_id["bundle_id"] = "sha256:" + "0" * 64

        empty_cases = make_manifest(self.tmp, [])

        absent_stratum = make_manifest(self.tmp, full_cases(self.tmp))
        del absent_stratum["cases"][0]["strata"]["codex"]

        missing_class = make_manifest(self.tmp, full_cases(self.tmp)[:3])

        straddle = make_manifest(self.tmp, full_cases(self.tmp, dict(
            flat, claude=([1000, 1000, 1000], [300, 1500, 1400]))))

        mismatched = make_manifest(self.tmp, full_cases(self.tmp))
        mismatched["identity"]["pinned"]["environment_fingerprint"]["candidate"] = "f2"

        exempted = make_manifest(self.tmp, full_cases(self.tmp, flat))
        exempted["cases"][0]["required"] = False

        # per D36: a retained-subset count, and ten pairs with no recorded checkpoint
        retained = make_manifest(self.tmp, full_cases(self.tmp, {
            s: ([1000] * 5, [800] * 5) for s in gate.STRATA}))

        unchecked_ten = make_manifest(self.tmp, full_cases(self.tmp, {
            s: ([1000] * 10, [800] * 10) for s in gate.STRATA}))

        checkpoint_without_expansion = make_manifest(self.tmp, full_cases(self.tmp))
        checkpoint_without_expansion["expansion"] = {
            "expanded": False, "checkpoint_ref": "ck-1"}

        # per D37
        unstable = make_manifest(self.tmp, full_cases(self.tmp))
        unstable["cases"][0]["strata"]["claude"]["quality"][
            "evaluator_stability"] = "unstable"

        # per D34: a wrong-kind record, re-digested so it is self-consistent
        wrong_kind = make_manifest(self.tmp, full_cases(self.tmp))
        entry = wrong_kind["cases"][0]["strata"]["claude"]["base"][0]
        cited = Path(entry["record"])
        document = dict(json.loads(cited.read_text(encoding="utf-8")),
                        kind="agent-gate-bundle")
        body = {k: v for k, v in document.items()
                if k not in ("record_id", "generated_at")}
        document["record_id"] = entry["record_id"] = gate.canonical_digest(body)
        cited.write_text(json.dumps(document), encoding="utf-8")

        # per D34: a rubric value outside [0, 100] is a document fault
        impossible_score = make_manifest(self.tmp, full_cases(self.tmp))
        impossible_score["cases"][0]["strata"]["claude"]["quality"][
            "noncritical_median"]["candidate"] = 1000.0

        return [
            ("manifest-declared state", declared_state, 2),
            ("manifest-declared bundle_id", declared_id, 2),
            ("per-case required opt-out", exempted, 2),
            ("empty cases", empty_cases, 3),
            ("absent stratum", absent_stratum, 3),
            ("missing core case class", missing_class, 3),
            ("straddling case", straddle, 3),
            ("mismatched pinned identity", mismatched, 3),
            ("selectively retained 5 pairs", retained, 3),
            ("ten pairs, no recorded checkpoint", unchecked_ten, 3),
            ("checkpoint without a declared expansion", checkpoint_without_expansion, 3),
            ("declared-unstable evaluator", unstable, 3),
            ("self-consistent wrong-kind record", wrong_kind, 3),
            ("rubric value outside [0, 100]", impossible_score, 2),
        ]

    def test_no_row_yields_an_approval(self):
        for index, (label, manifest, expected_code) in enumerate(self.rows()):
            with self.subTest(row=label):
                code, bundle = run_cli("--trials", self.write(manifest, f"m{index}.json"))
                self.assertEqual(code, expected_code)
                self.assertNotEqual(code, 0)
                if bundle is not None:
                    self.assertEqual(bundle["state"], "unmeasured")
                    self.assertTrue(bundle["diagnostics"])

    def test_a_straddling_bundle_says_why(self):
        straddle = dict(self.rows()[6][1])
        _code, bundle = run_cli("--trials", self.write(straddle, "straddle.json"))
        self.assertTrue(any(line.startswith("CASE_STRADDLES_GATE")
                            for line in bundle["diagnostics"]), bundle["diagnostics"])

    def test_a_tampered_record_cannot_certify(self):
        manifest = make_manifest(self.tmp, full_cases(self.tmp))
        cited = Path(manifest["cases"][0]["strata"]["claude"]["base"][0]["record"])
        document = json.loads(cited.read_text(encoding="utf-8"))
        document["strata"]["claude"]["runs"][0]["tokens"]["input_total"] = 10
        cited.write_text(json.dumps(document), encoding="utf-8")
        code, bundle = run_cli("--trials", self.write(manifest, "tampered.json"))
        self.assertEqual(code, 3)
        self.assertEqual(bundle["state"], "unmeasured")

    def test_override_records_authority_without_changing_the_verdict(self):
        flat = {s: ([1000, 1000, 1000], [999, 999, 999]) for s in gate.STRATA}
        manifest = make_manifest(self.tmp, full_cases(self.tmp, flat))
        code, bundle = run_cli("--trials", self.write(manifest, "override.json"),
                               "--override", "further experimentation approved",
                               "--override-by", "anis",
                               "--override-at", "2026-09-02T12:00:00Z")
        self.assertEqual(code, 3)
        self.assertEqual(bundle["state"], "rejected")
        self.assertEqual(set(bundle["override"]),
                         {"reason", "authorized_by", "authorized_at", "scope"})
        self.assertEqual(bundle["override"]["scope"], "further-experimentation")
        self.assertEqual(bundle["override"]["authorized_by"], "anis")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest -v tests/test_agent_gate_bundle.py -k "BundleCli or NoUpgrade" 2>&1 | tail -8`
Expected: FAIL — `AttributeError: module 'agent_gate_bundle' has no attribute 'main'` on every
test in both classes.

- [ ] **Step 3: Write the minimal implementation**

Add `import argparse` and `import sys` to `scripts/agent-gate-bundle.py`, plus
`from datetime import datetime, timezone`, and append:

**3a. `build_override(reason, authorized_by, authorized_at)`** — `None` when `reason` is
`None`; otherwise exactly

```python
{"reason": reason, "authorized_by": authorized_by,
 "authorized_at": authorized_at, "scope": "further-experimentation"}
```

`authorized_at` is the caller's declared `--override-at`, **not** a clock read: the override
block is inside `bundle_id`, so a sampled timestamp would give identical inputs different bundle
ids and contradict the reproducibility criterion (per D38). `main` validates it with
`datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")` and calls `ap.error` on failure. No other key
exists, and none of these four is read anywhere else in the module (D14).

**3b. `assemble_bundle(manifest, evidence, diagnostics, override, state)`**:

1. `resolved = evidence if evidence else {"cases": []}`.
2. `lines = render(diagnostics)` when `state == "unmeasured"`, else `[]`. When `state ==
   "unmeasured"` and `evidence` is truthy, extend `diagnostics` first with one
   `Diagnostic("CASE_STRADDLES_GATE", f"$.cases[{index}].strata.{stratum}",
   f"case {case_id!r} has index-aligned pairs on both sides of a gate")` per entry of
   `straddling_cases(evidence)` (D21).
3. `body = {"schema_version": SCHEMA_VERSION, "kind": BUNDLE_KIND,
   "gate_contract": GATE_CONTRACT, "gate_version": GATE_VERSION, "state": state,
   "identity": manifest["identity"], "expansion": manifest["expansion"],
   "evidence": resolved, "gates": gate_results(resolved), "override": override,
   "diagnostics": lines}`.
4. **Re-decide and refuse.** `if decide(body["evidence"]) != body["state"]: raise
   BundleIntegrityError(...)` naming both states. Nothing is written or returned on that path.
5. Return `dict(body, bundle_id=canonical_digest(body), generated_at=<RFC3339 UTC now>)`.

**3c. `main(argv=None)`**:

```python
ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--trials", required=True, metavar="FILE",
                help="agent-gate-trials manifest citing emitted cost records")
ap.add_argument("--override", metavar="REASON",
                help="record an authorization for further experimentation; "
                     "never changes the state or the exit code")
ap.add_argument("--override-by", metavar="WHO", help="who authorized --override")
ap.add_argument("--override-at", metavar="RFC3339",
                help="when --override was authorized, e.g. 2026-09-02T12:00:00Z; "
                     "declared, not sampled, so the bundle id stays reproducible")
args = ap.parse_args(argv)
given = (bool(args.override), bool(args.override_by), bool(args.override_at))
if len(set(given)) != 1:
    ap.error("--override, --override-by and --override-at must be given together")
```

Then: `load_manifest(Path(args.trials))` inside a `try`, catching `ManifestError` — print
`render(error.diagnostics)` one line per entry to stderr and `return 2`. Call
`resolve_trials(manifest)`, `state = decide(evidence)`, then `assemble_bundle(...)` inside a
`try` catching `BundleIntegrityError` — print the message to stderr and `return 2`. Emit with
`json.dump(bundle, sys.stdout, sort_keys=True, separators=(",", ":"))` followed by
`sys.stdout.write("\n")`. Return `0` when `state == "approved"`, else `3` (D16). End the file
with `if __name__ == "__main__": raise SystemExit(main())`.

**3d. `justfile`.** Add, immediately after the `agent-costs` recipe:

```make
# Apply issue #70's token-and-quality gate to a trials manifest of emitted cost records
agent-gate-bundle *args:
  python3 scripts/agent-gate-bundle.py {{args}}
```

- [ ] **Step 4: Verify**

```sh
python3 -m unittest -v tests/test_agent_gate_bundle.py
just agent-workflow-tests 2>&1 | tail -3
just agent-gate-bundle --trials /nonexistent/trials.json; test $? -eq 2
python3 - <<'PY'
import importlib.util, inspect, pathlib
spec = importlib.util.spec_from_file_location(
    "g", pathlib.Path("scripts/agent-gate-bundle.py"))
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
assert list(inspect.signature(g.decide).parameters) == ["evidence"]
assert "override" not in inspect.getsource(g.decide)
assert "decide(" in inspect.getsource(g.assemble_bundle), "emitter must re-decide (D14)"
print("no-upgrade invariant is enforced in both layers")
PY
grep -c 'agent-gate-bundle' justfile
```
Expected: the suite prints `OK`; `just agent-workflow-tests` ends in `OK`; the `just` recipe
exits 2 with its diagnostic on stderr and nothing on stdout; the inline check prints its line;
the last prints `2` (the recipe's comment line and its body). Deleting step 3b.4's re-decision makes
`test_emitter_refuses_a_state_the_evidence_does_not_earn` fail with `BundleIntegrityError not
raised`.

- [ ] **Step 5: Commit**

```bash
git add scripts/agent-gate-bundle.py tests/test_agent_gate_bundle.py justfile
git commit -m "feat(agent-gate-bundle): emit the content-addressed bundle and its exit codes

State comes only from decide(evidence) and is re-verified before the
write; --override records authority and cannot relabel a verdict (D14).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
