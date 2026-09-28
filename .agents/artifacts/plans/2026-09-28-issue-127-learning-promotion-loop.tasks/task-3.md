# Task 3: `agent_gate_bundle.verify_bundle` (package P2 begins)

**Files:**
- Modify: `python/agent_tools/agent_gate_bundle.py` (one new public function after `assemble_bundle`)
- Modify: `tests/test_agent_gate_bundle.py` (one new `VerifyBundleTest` class before `ModuleEntryPointTest`)

D8 governs this task; read the spec's "Evidence" paragraph under "The lifecycle".

**Interfaces:**
- Consumes (existing, same module): `SCHEMA_VERSION`, `BUNDLE_KIND`, `GATE_CONTRACT`,
  `GATE_VERSION`, `decide`, `BundleIntegrityError`, `telemetry_digest`; in the test file the
  existing builders `IDENTITY`, `context`, `stratum`, `flat`, and `gate.build_override`,
  `gate.assemble_bundle`.
- Produces (Task 4 imports it):

```python
def verify_bundle(document: object) -> str:
    """Contract: the recorded `state` of a bundle this module emitted, or
    BundleIntegrityError. The id is recomputed over the body without `bundle_id`
    and `generated_at`, and the state is re-decided from the bundle's own evidence."""
```

**Invariants:**
- Raises `BundleIntegrityError` unless: `document` is a dict; `kind == BUNDLE_KIND`;
  `schema_version` is the int `SCHEMA_VERSION` (`type(...) is int`); `gate_contract ==
  GATE_CONTRACT`; `gate_version` is the int `GATE_VERSION`; `bundle_id`, `state` and `evidence`
  are present; `bundle_id == telemetry_digest({k: v for k, v in document.items() if k not in
  ("bundle_id", "generated_at")})`; and `decide(document["evidence"]) == document["state"]`.
- Returns `document["state"]`. The `override` block never influences the result (#70).
- `assemble_bundle`, `decide` and `main` are unchanged; no existing test changes.
- Any exception `decide` raises on a malformed `evidence` is re-raised as
  `BundleIntegrityError` (catch `(TypeError, KeyError, AttributeError, ValueError)`).

- [ ] **Step 1: Write the failing tests**

```python
def bundle_for(evidence_value, state, override=None):
    manifest = {"identity": json.loads(json.dumps(IDENTITY)),
                "expansion": {"expanded": False, "checkpoint_ref": None}}
    return gate.assemble_bundle(manifest, evidence_value, [], override, state)


def body_digest(bundle):
    return telemetry_digest({k: v for k, v in bundle.items()
                             if k not in ("bundle_id", "generated_at")})


class VerifyBundleTest(unittest.TestCase):
    """D8 (#127): the one verifier of an emitted bundle's id and verdict."""

    APPROVED = staticmethod(lambda: flat(stratum(context(1000, 800))))
    REJECTED = staticmethod(lambda: flat(stratum(context(1000, 999))))

    def test_each_emitted_state_verifies_to_itself(self):
        for state, value in (("approved", self.APPROVED()), ("rejected", self.REJECTED()),
                             ("unmeasured", None)):
            with self.subTest(state=state):
                self.assertEqual(gate.verify_bundle(bundle_for(value, state)), state)

    def test_generated_at_is_outside_the_digest(self):
        bundle = bundle_for(self.APPROVED(), "approved")
        bundle["generated_at"] = "1999-01-01T00:00:00Z"
        self.assertEqual(gate.verify_bundle(bundle), "approved")

    def test_a_relabelled_state_is_refused_by_the_digest(self):
        bundle = bundle_for(self.REJECTED(), "rejected")
        bundle["state"] = "approved"
        with self.assertRaises(gate.BundleIntegrityError):
            gate.verify_bundle(bundle)

    def test_a_relabelled_state_with_a_recomputed_id_is_refused_by_decide(self):
        bundle = bundle_for(self.REJECTED(), "rejected")
        bundle["state"] = "approved"
        bundle["bundle_id"] = body_digest(bundle)
        with self.assertRaises(gate.BundleIntegrityError):
            gate.verify_bundle(bundle)

    def test_constants_and_shape_are_checked(self):
        for key, value in (("kind", "agent-gate-trials"), ("schema_version", True),
                           ("gate_contract", "issue-71"), ("gate_version", 2)):
            with self.subTest(key=key):
                bundle = bundle_for(self.APPROVED(), "approved")
                bundle[key] = value
                bundle["bundle_id"] = body_digest(bundle)
                with self.assertRaises(gate.BundleIntegrityError):
                    gate.verify_bundle(bundle)
        for broken in ([], {"kind": "agent-gate-bundle"}):
            with self.subTest(broken=broken), self.assertRaises(gate.BundleIntegrityError):
                gate.verify_bundle(broken)

    def test_malformed_evidence_is_an_integrity_error(self):
        bundle = bundle_for(self.APPROVED(), "approved")
        bundle["evidence"] = {"cases": [{"strata": 7}]}
        bundle["bundle_id"] = body_digest(bundle)
        with self.assertRaises(gate.BundleIntegrityError):
            gate.verify_bundle(bundle)

    def test_an_override_never_changes_the_verified_state(self):
        override = gate.build_override("explore", "fagenorn", "2026-09-28T00:00:00Z")
        bundle = bundle_for(self.REJECTED(), "rejected", override)
        self.assertEqual(gate.verify_bundle(bundle), "rejected")
```

- [ ] **Step 2: Run and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests.test_agent_gate_bundle.VerifyBundleTest 2>&1 | tail -3`
Expected: FAILED — `module 'agent_tools.agent_gate_bundle' has no attribute 'verify_bundle'`.

- [ ] **Step 3: Implement `verify_bundle`** per the invariants, directly after
  `assemble_bundle`, reusing `decide` and `telemetry_digest` (no copied digest rule, D8).

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_agent_gate_bundle.py 2>&1 | tail -3`
Expected: `OK` (every pre-existing case plus 7 new).

- [ ] **Step 5: Commit** — `git add python/agent_tools/agent_gate_bundle.py tests/test_agent_gate_bundle.py`;
  subject `feat(issue-127/T3): agent_gate_bundle.verify_bundle`, with the trailers.
