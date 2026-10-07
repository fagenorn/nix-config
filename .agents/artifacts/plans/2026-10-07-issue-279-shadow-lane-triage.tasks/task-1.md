# Task 1: Public `resolve()` and the optional `light_lane` member

Spec sections **Resolver API** and **Policy member**; rows D1, D2, D8.

**Files:**
- Modify: `python/agent_tools/resolve_project.py`
- Test: `home/common/agent-skills/tests/test_resolve_project.py`

**Interfaces:**
- Consumes: the existing internals of `resolve_project.py`: `require_platform_manifest`, `discover_root`, `load_contract`, `validate_contract`, `raise_for_violations`, `raise_for_platform_range`, `validate_projections`, `build_snapshot`, `raise_for_unavailable`, `check_exact_members`, `check_object`, `check_positive_int`, `check_list`, `check_safe_path`, `violation`, `ContractError`.
- Produces (Task 2 relies on these exact names):
  - `resolve_project.resolve(repo_root: str | None, required: list[str] | None = None) -> dict` — the `ResolvedProject` snapshot, or raises `ContractError`.
  - Constants `WORKFLOW_OPTIONAL_MEMBERS = ("light_lane",)`, `LIGHT_LANE_MEMBERS = ("mode", "budget_minutes", "risk_paths")`, `LIGHT_LANE_MODES = ("shadow", "active")`.
  - Snapshot: `snapshot["bindings"]["workflow"]` holds `light_lane` exactly as authored when present (object or `null`), and has no `light_lane` key when the author wrote none.

**Invariants:**
- `resolve-project resolve` stdout is byte-identical to before for every contract that was already valid (the existing suite stays green).
- `resolve()` performs, in this order, exactly what `command_resolve` does today: manifest gate, root discovery, load, `raise_for_violations(validate_contract(...))`, `raise_for_platform_range`, `validate_projections`, `build_snapshot`, `raise_for_unavailable(required, ...)`. `command_resolve` becomes `return emit_json(resolve(args.repo_root, args.require))`. `conformance_checks` is not touched.
- The four existing `workflow` members stay required. `light_lane` is the only optional one; any other member is still `contract.workflow.member_unexpected`.
- `normalize_bindings` is not changed: `light_lane` (including `risk_paths`) is passed through as authored, never rewritten to absolute paths, and the resolver never inserts `light_lane: null`.
- Every repair id comes from section `workflow`: `not_object`, `member_missing`, `member_unexpected`, `not_positive_int`, `not_list`, `unsafe_path`, plus the new `contract.workflow.light_lane_mode`.

- [ ] **Step 1: Write the failing tests**

Append this class to `home/common/agent-skills/tests/test_resolve_project.py`, before the `if __name__ == "__main__":` block (add `from unittest import mock` to the imports if it is not already imported):

```python
class LightLaneTest(ResolverTestCase):
    """#279: the optional `bindings.workflow.light_lane` member (parent D13)."""

    VALID = {"mode": "shadow", "budget_minutes": 45,
             "risk_paths": ["python/agent_tools/resolve_project.py",
                            "home/common/agent-skills/scripts/workflow*"]}

    def contract_with(self, light_lane):
        contract = source_contract()
        contract["bindings"]["workflow"]["light_lane"] = light_lane
        return contract

    def test_a_valid_light_lane_round_trips_unchanged(self):
        for light_lane in (self.VALID,
                           {"mode": "active", "budget_minutes": 1, "risk_paths": []}):
            with self.subTest(light_lane=light_lane):
                code, snap, err = self.resolve(self.make_root(self.contract_with(light_lane)))
                self.assertEqual(code, 0, err)
                self.assertEqual(snap["bindings"]["workflow"]["light_lane"], light_lane)

    def test_an_absent_member_stays_absent(self):
        contract = source_contract()
        self.assertNotIn("light_lane", contract["bindings"]["workflow"])
        code, snap, err = self.resolve(self.make_root(contract))
        self.assertEqual(code, 0, err)
        self.assertNotIn("light_lane", snap["bindings"]["workflow"])

    def test_null_stays_null(self):
        code, snap, err = self.resolve(self.make_root(self.contract_with(None)))
        self.assertEqual(code, 0, err)
        self.assertIn("light_lane", snap["bindings"]["workflow"])
        self.assertIsNone(snap["bindings"]["workflow"]["light_lane"])

    REFUSALS = (
        ([], "/bindings/workflow/light_lane", "contract.workflow.not_object"),
        ({**VALID, "lane": "light"}, "/bindings/workflow/light_lane/lane",
         "contract.workflow.member_unexpected"),
        ({"budget_minutes": 45, "risk_paths": []}, "/bindings/workflow/light_lane/mode",
         "contract.workflow.member_missing"),
        ({**VALID, "mode": "fast"}, "/bindings/workflow/light_lane/mode",
         "contract.workflow.light_lane_mode"),
        ({**VALID, "mode": 1}, "/bindings/workflow/light_lane/mode",
         "contract.workflow.light_lane_mode"),
        ({**VALID, "budget_minutes": 0}, "/bindings/workflow/light_lane/budget_minutes",
         "contract.workflow.not_positive_int"),
        ({**VALID, "budget_minutes": -5}, "/bindings/workflow/light_lane/budget_minutes",
         "contract.workflow.not_positive_int"),
        ({**VALID, "budget_minutes": True}, "/bindings/workflow/light_lane/budget_minutes",
         "contract.workflow.not_positive_int"),
        ({**VALID, "risk_paths": "python/*"}, "/bindings/workflow/light_lane/risk_paths",
         "contract.workflow.not_list"),
        ({**VALID, "risk_paths": ["../outside/*"]}, "/bindings/workflow/light_lane/risk_paths/0",
         "contract.workflow.unsafe_path"),
        ({**VALID, "risk_paths": ["/abs/*"]}, "/bindings/workflow/light_lane/risk_paths/0",
         "contract.workflow.unsafe_path"),
        ({**VALID, "risk_paths": [""]}, "/bindings/workflow/light_lane/risk_paths/0",
         "contract.workflow.unsafe_path"),
        ({**VALID, "risk_paths": ["ok/*", 3]}, "/bindings/workflow/light_lane/risk_paths/1",
         "contract.workflow.unsafe_path"),
    )

    def test_each_malformed_light_lane_is_refused_with_its_pointer(self):
        for light_lane, pointer, repair_id in self.REFUSALS:
            with self.subTest(pointer=pointer, light_lane=light_lane):
                code, payload, _ = self.resolve(self.make_root(self.contract_with(light_lane)))
                self.assertEqual(code, 2)
                error = payload["error"]
                self.assertEqual(error["code"], "invalid_contract")
                self.assertEqual(error["repair_id"], repair_id)
                self.assertEqual([v["pointer"] for v in error["violations"]], [pointer])

    def test_any_other_workflow_member_is_still_unexpected(self):
        contract = source_contract()
        contract["bindings"]["workflow"]["heavy_lane"] = None
        code, payload, _ = self.resolve(self.make_root(contract))
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["repair_id"], "contract.workflow.member_unexpected")
        self.assertEqual([v["pointer"] for v in payload["error"]["violations"]],
                         ["/bindings/workflow/heavy_lane"])


class PublicResolveTest(ResolverTestCase):
    """#279 D1: `resolve()` is `command_resolve`'s composition, importable."""

    def test_resolve_returns_the_snapshot_the_command_prints(self):
        root = self.make_root()
        code, printed, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            self.assertEqual(resolve_project.resolve(str(root)), printed)

    def test_resolve_raises_the_refusal_the_command_prints(self):
        contract = source_contract()
        contract["bindings"]["workflow"]["light_lane"] = {"mode": "fast",
                                                          "budget_minutes": 1,
                                                          "risk_paths": []}
        root = self.make_root(contract)
        code, printed, _ = self.resolve(root)
        self.assertEqual(code, 2)
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            with self.assertRaises(resolve_project.ContractError) as raised:
                resolve_project.resolve(str(root))
        self.assertEqual(
            {"code": raised.exception.code, "repair_id": raised.exception.repair_id,
             "violations": raised.exception.violations},
            printed["error"])

    def test_resolve_applies_required_capabilities(self):
        root = self.make_root()
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            snapshot = resolve_project.resolve(str(root))
            missing = sorted(name for name, entry in snapshot["capabilities"].items()
                             if entry["state"] != "available")
            if not missing:
                self.skipTest("every capability is available on this host")
            with self.assertRaises(resolve_project.ContractError) as raised:
                resolve_project.resolve(str(root), [missing[0]])
        self.assertEqual(raised.exception.code, "capability_unavailable")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py -k LightLaneTest -k PublicResolveTest 2>&1 | tail -5`
Expected: FAILED — the valid-light-lane cases refuse with `member_unexpected`, and `PublicResolveTest` errors with `AttributeError: module 'agent_tools.resolve_project' has no attribute 'resolve'`. (`test_an_absent_member_stays_absent` and `test_any_other_workflow_member_is_still_unexpected` already pass; that is expected.)

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/resolve_project.py`:

1. Beside `WORKFLOW_MEMBERS`, add `WORKFLOW_OPTIONAL_MEMBERS`, `LIGHT_LANE_MEMBERS` and `LIGHT_LANE_MODES` with the values under **Interfaces**.
2. Give `check_exact_members` a keyword-only parameter `optional: tuple[str, ...] = ()`. A name in `optional` is never reported as missing and never as unexpected. Every existing call is unchanged.
3. In `validate_workflow`, pass `optional=WORKFLOW_OPTIONAL_MEMBERS` to the top-level `check_exact_members` call, and after the `release` check add:
   - if `"light_lane" in workflow` and `workflow["light_lane"] is not None`, with `pointer = "/bindings/workflow/light_lane"`: when `check_object(value, pointer, "workflow", violations)` holds, call `check_exact_members(value, pointer, LIGHT_LANE_MEMBERS, "workflow", violations)`, then
   - `mode` present and (`not isinstance(mode, str)` or `mode not in LIGHT_LANE_MODES`) → `violation(f"{pointer}/mode", "must be one of shadow, active", "contract.workflow.light_lane_mode")`;
   - `budget_minutes` present → `check_positive_int(..., f"{pointer}/budget_minutes", "workflow", violations)`;
   - `risk_paths` present and `check_list(..., f"{pointer}/risk_paths", "workflow", violations)` → `check_safe_path(entry, f"{pointer}/risk_paths/{index}", "workflow", violations)` for each entry.
4. Add `resolve(repo_root, required=None)` directly above `command_resolve`, moving `command_resolve`'s body (and its comments) into it and returning `snapshot` instead of printing. Docstring: "The `ResolvedProject` snapshot for `repo_root`, or `ContractError`. Exactly the composition `resolve-project resolve` prints (#279 D1); `conformance_checks` keeps its own, collecting composition." Replace `command_resolve`'s body with `return emit_json(resolve(args.repo_root, args.require))`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" timeout 900 python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py home/common/agent-skills/tests/test_resolve_platform.py home/common/agent-skills/tests/test_resolve_platform_status.py home/common/agent-skills/tests/test_conformance_checks.py 2>&1 | tail -3`
Expected: `OK` (possibly with `skipped=` from the host-dependent capability case); no failures. The new classes pass and the existing resolver and conformance suites stay green (byte-identical output).

Run: `if git diff --quiet HEAD -- .agents/project.json home/common/agent-skills/platform-manifest.json python/agent_tools/conformance_checks.py; then echo unchanged; else echo CHANGED; exit 1; fi`
Expected: `unchanged` (D2, D3).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/resolve_project.py home/common/agent-skills/tests/test_resolve_project.py
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id <run-id> --worker-id <worker-id> -- -m "feat(resolve-project): optional workflow.light_lane and a public resolve() (#279)" -m "<trailers>"
```
Use the launch-commit identity and commit trailers from your dispatch brief.
