# Task 2: Conformance check `host.admission.declaration`

**Files:**
- Modify: `home/common/agent-skills/scripts/conformance-registry.py`
- Modify: `home/common/agent-skills/scripts/conformance-checks.py`
- Modify: `home/common/agent-skills/tests/test_resolve_project.py` (`install_home`)
- Modify: `home/common/agent-skills/tests/conformance_test_support.py` (`platform_env`)
- Test: `home/common/agent-skills/tests/test_conformance.py`, `home/common/agent-skills/tests/test_conformance_registry.py`

**Interfaces:**
- Consumes (Task 1): library `host_admission.py` — `load_declaration()`, `declaration_path()`, `DeclarationError.reason_code`; the committed `home/common/agent-skills/host-declaration.json`.
- Produces:
  - Registry `Check("host.admission.declaration", "host", "capability", "optional", (), (("declaration_missing", "host.admission.declare"), ("declaration_invalid", "host.admission.declare")), "check_admission_declaration")`, placed after `host.tracker.credential` in `REGISTRY` (per D13, D24).
  - `REPAIRS["host.admission.declare"] = {"module": "conformance", "safety_class": "user_action", "operation": None}`, commented: author `home/common/agent-skills/host-declaration.json` (or its installed copy) and switch; no engine command writes it.
  - `check_admission_declaration(context) -> Outcome` in `conformance-checks.py`.
  - `install_home(home, manifest=COMMITTED, *, library=True, declaration=COMMITTED)`: `COMMITTED` copies the committed declaration to `<home>/.agents/share/host-declaration.json`, `None` installs none, a `str` is written verbatim, anything else as JSON. `platform_env(tmp, manifest=COMMITTED, *, library=True, declaration=COMMITTED)` passes it through.

**Invariants:**
- The check reads the declaration through the same library the runtime loads; it never reads or writes a ledger or a claim (per D13).
- It depends on no other check, so a broken contract never suppresses it (per D24).
- Passed facts: `supported_routes` = `bound_facts` of `"<route>=<agent_slots>"`, `unsupported_routes` = `bound_facts` of names; failed facts: `{"declaration_path": bound_fact(str(path))}` when `declaration_path()` is not `None`, else `{}`.
- `local` and `doctor` select it (both select every `host` check); `workflow_entry` does not.

- [ ] **Step 1: Write the failing tests**

In `T/test_conformance.py`, import `load_module`, `platform_env`, `make_root`, `doctor`, `fixture` and `ReportAssertions` from `conformance_test_support` where not already imported, and add:

```python
class AdmissionDeclarationCheckTest(ReportAssertions, unittest.TestCase):
    """#150 D13, D24: the host declaration is reported, never claimed."""

    CHECK_ID = "host.admission.declaration"

    def check(self, tmp, **home):
        root = make_root(tmp)
        env = platform_env(tmp, **home)
        report, by_id = doctor(self, root, "--offline", env=env)
        self.assert_validates(report)
        self.assertFalse((root / ".superpowers").exists())
        return by_id[self.CHECK_ID], env

    def test_the_committed_declaration_passes_with_its_routes(self):
        with fixture() as tmp:
            check, _ = self.check(tmp)
        self.assertEqual(
            [check[key] for key in ("status", "domain", "subject_kind", "requirement",
                                    "reason_code", "repair_id")],
            ["passed", "host", "capability", "optional", None, None])
        self.assertEqual(check["facts"], {"supported_routes": ["claude-code=7"],
                                          "unsupported_routes": ["codex"]})

    def test_missing_and_invalid_declarations_name_the_repair(self):
        below_floor = {"schema_version": 1, "routes": {
            "claude-code": {"support": "supported", "agent_slots": 3}}}
        for label, value, reason in (("missing", None, "declaration_missing"),
                                     ("below floor", below_floor, "declaration_invalid")):
            with self.subTest(label), fixture() as tmp:
                check, env = self.check(tmp, declaration=value)
                self.assertEqual(
                    [check["status"], check["reason_code"], check["repair_id"]],
                    ["failed", reason, "host.admission.declare"])
                self.assertEqual(check["facts"], {"declaration_path": str(
                    Path(env["HOME"]) / ".agents/share/host-declaration.json")})

    def test_local_selects_it_and_workflow_entry_does_not(self):
        module = load_module()
        self.assertIn(self.CHECK_ID, [c.id for c in module.select("local")])
        self.assertNotIn(self.CHECK_ID, [c.id for c in module.select("workflow_entry")])
```

In `T/test_conformance_registry.py`: add `"host.admission.declaration",` as the first
`host.` entry of `REGISTERED_CHECK_IDS` (the tuple is sorted) and rename
`test_the_registry_is_exactly_the_seventeen_declared_checks` to
`test_the_registry_is_exactly_the_eighteen_declared_checks` (body unchanged).

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_conformance.py home/common/agent-skills/tests/test_conformance_registry.py 2>&1 | tail -4`
Expected: FAIL — `KeyError: 'host.admission.declaration'`, `platform_env()` rejects `declaration`, and the registry closure differs.

- [ ] **Step 3: Implement**

1. `install_home`/`platform_env`: add the `declaration` keyword as specified; `DECLARATION = Path(__file__).resolve().parents[1] / "host-declaration.json"` beside `MANIFEST`. Update `install_home`'s docstring to name the third override hook. Keep the call shape of every existing caller.
2. `conformance-checks.py`: `load_host_admission()` — the library at `Path(__file__).parent / "host_admission.py"` when that directory is named `scripts`, else `Path.home() / ".agents/lib/python/host_admission.py"`, loaded once with `importlib.util` under module name `conformance_host_admission` (per D18). `check_admission_declaration(context)` ignores `context`, calls `load_declaration()`; on `DeclarationError` returns `Outcome("failed", error.reason_code, "host.admission.declare", facts)`; on success `Outcome("passed", None, None, {...})` with the Invariants' facts. Its docstring states it reports the declaration and route support and never touches a ledger or claim.
3. `conformance-registry.py`: the `Check` and `REPAIRS` entries from Produces.
4. Re-pin any other conformance expectation that enumerates the `host` checks or the registry size; the new check passes under every `install_home`-built `HOME` because the committed declaration is installed by default.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py home/common/agent-skills/tests/test_conformance_registry.py home/common/agent-skills/tests/test_conformance_checks.py home/common/agent-skills/tests/test_resolve_project.py 2>&1 | tail -3`
Expected: `OK`.

Run: `python3 home/common/agent-skills/scripts/conformance.py run --purpose doctor --repo-root "$PWD" --offline | python3 -c 'import json,sys; c={x["id"]:x for x in json.load(sys.stdin)["checks"]}["host.admission.declaration"]; print(c["status"], c["reason_code"])'`
Expected: prints a status line for the new check (`KeyError` at the base commit); on a host not yet switched to this generation it reads `failed declaration_missing`, which is truthful.

Run: `just agent-workflow-tests 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/conformance-registry.py home/common/agent-skills/scripts/conformance-checks.py \
  home/common/agent-skills/tests/test_resolve_project.py home/common/agent-skills/tests/conformance_test_support.py \
  home/common/agent-skills/tests/test_conformance.py home/common/agent-skills/tests/test_conformance_registry.py
git commit -m "feat(conformance): report the host admission declaration (#150)"
```
