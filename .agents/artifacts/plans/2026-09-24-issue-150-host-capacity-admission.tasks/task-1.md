# Task 1: Host declaration, library and `host-route`

**Files:**
- Create: `home/common/agent-skills/scripts/host_admission.py`
- Create: `home/common/agent-skills/host-declaration.json`
- Create: `home/common/agent-skills/tests/test_host_admission.py`
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (library loader, `host-route` verb)
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py` (`host_route` kind)
- Modify: `home/common/agent-skills/default.nix` (install library and declaration)
- Modify: `justfile` (`agent-workflow-tests` gains `test_host_admission.py`)
- Test: `home/common/agent-skills/tests/_delivery_model_fixtures.py`, `home/common/agent-skills/tests/test_delivery_model.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces (library `host_admission.py`, imported never run; per D18):
  - `HOST_ADMISSION_INTERFACE_VERSION = 1`, `DECLARATION_SCHEMA_VERSION = 1`
  - `DIRECT_ROUTE = "direct"`, `ROUTE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")`
  - `CONTROLLER_ROLES = MappingProxyType({"controller": 1})`,
    `OWNER_ROLE_SET = MappingProxyType({"owner": 1, "worker": 1, "reviewer": 1})`,
    `ROLE_NAMES = ("controller", "owner", "worker", "reviewer")`,
    `MINIMUM_SUPPORTED_SLOTS = sum(CONTROLLER_ROLES.values()) + sum(OWNER_ROLE_SET.values())` (= 4)
  - `REASON_CODES = ("declared_unsupported", "route_undeclared", "declaration_missing", "declaration_invalid")`
  - `UNSUPPORTED_ALTERNATIVE = "/from-issue <issue> --auto"`
  - `class DeclarationError(Exception)` with attribute `reason_code` ∈ {`declaration_missing`, `declaration_invalid`}
  - `declaration_path() -> Path | None` — `Path(os.environ["HOME"]) / ".agents/share/host-declaration.json"`; `None` when `HOME` is unset or empty
  - `load_declaration() -> dict` — reads, parses and validates; raises `DeclarationError`
  - `validate_declaration(value: object) -> dict`
- Produces (`workflow-state.py`): `_host_admission()` (cached loader), `route_verdict(route: str) -> dict` (the typed result), `command_host_route`, subcommand `host-route --route <name>`.
- Produces (wire): `workflow-response` accepts `kind: host_route`.

**Invariants:**
- `host-route` takes no ledger, lock, clock or repository root, writes nothing, and exits 0 for every well-formed answer; only a `--route` outside the grammar, or `direct`, exits 2 with empty stdout (per D9, D18).
- Its stdout is byte-identical to the `workflow-response` boundary's canonical output.
- A declaration is valid only as exact members at every level (per D2): top `{schema_version, routes}`; `schema_version` a plain int equal to 1; `routes` a non-empty object whose keys match `ROUTE_NAME_PATTERN` and are not `direct`; a supported route is exactly `{"support": "supported", "agent_slots": <plain int ≥ 4>}`, an unsupported one exactly `{"support": "unsupported"}`.
- Duplicate JSON keys and the bare tokens `NaN`/`Infinity`/`-Infinity` are invalid.

- [ ] **Step 1: Write the failing tests**

Create `T/test_host_admission.py`:

```python
"""Host agent-slot admission (#150): declaration, host-route, claims, control admission."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[4]
SCRIPTS = REPO / "home/common/agent-skills/scripts"
WORKFLOW = SCRIPTS / "workflow-state.py"
ARTIFACT_BUDGET = SCRIPTS / "artifact_budget.py"
POLICY = REPO / "home/common/agent-skills/artifact-budget-policy.json"
COMMITTED_DECLARATION = REPO / "home/common/agent-skills/host-declaration.json"
ALTERNATIVE = "/from-issue <issue> --auto"


def declaration(**routes):
    return {"schema_version": 1, "routes": routes}


def install_declaration(home, value):
    """Write `value` (JSON, or a str verbatim) as HOME's declaration; None removes it."""
    target = Path(home) / ".agents/share/host-declaration.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    if value is not None:
        target.write_text(value if isinstance(value, str) else json.dumps(value),
                          encoding="utf-8")
    return target


def boundary(case, raw):
    """Pipe raw bytes through the workflow-response boundary; return the parsed value."""
    checked = subprocess.run(
        [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
         "workflow-response", "--input", "-", "--policy", str(POLICY)],
        input=raw, capture_output=True, check=False)
    case.assertEqual((checked.returncode, checked.stdout), (0, raw), checked.stderr)
    return json.loads(raw)


class HostRouteTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.home, True)

    def host_route(self, route):
        return subprocess.run(
            [sys.executable, str(WORKFLOW), "host-route", "--route", route],
            capture_output=True, check=False, env={**os.environ, "HOME": str(self.home)})

    def answer(self, route):
        completed = self.host_route(route)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return boundary(self, completed.stdout)

    @staticmethod
    def unsupported(route, reason):
        return {"interface_version": 1, "kind": "host_route", "route": route,
                "support": "unsupported", "agent_slots": None,
                "reason_code": reason, "alternative": ALTERNATIVE}

    def test_committed_declaration_is_the_designed_host_budget(self):
        committed = json.loads(COMMITTED_DECLARATION.read_text(encoding="utf-8"))
        self.assertEqual(committed, declaration(**{
            "claude-code": {"support": "supported", "agent_slots": 7},
            "codex": {"support": "unsupported"}}))
        install_declaration(self.home, committed)
        self.assertEqual(self.answer("claude-code"), {
            "interface_version": 1, "kind": "host_route", "route": "claude-code",
            "support": "supported", "agent_slots": 7, "reason_code": None,
            "alternative": None})
        self.assertEqual(self.answer("codex"),
                         self.unsupported("codex", "declared_unsupported"))

    def test_every_reason_code_is_a_typed_answer(self):
        install_declaration(self.home, declaration(**{
            "claude-code": {"support": "supported", "agent_slots": 4}}))
        self.assertEqual(self.answer("claude-code")["agent_slots"], 4)
        self.assertEqual(self.answer("gemini"),
                         self.unsupported("gemini", "route_undeclared"))
        install_declaration(self.home, None)
        self.assertEqual(self.answer("claude-code"),
                         self.unsupported("claude-code", "declaration_missing"))

    def test_invalid_declarations_answer_declaration_invalid(self):
        supported = {"support": "supported", "agent_slots": 7}
        for label, value in (
                ("below the floor", declaration(**{"claude-code": {
                    "support": "supported", "agent_slots": 3}})),
                ("boolean slots", declaration(**{"claude-code": {
                    "support": "supported", "agent_slots": True}})),
                ("host metric", {**declaration(**{"claude-code": supported}), "cpu": 8}),
                ("route member", declaration(**{"claude-code": {**supported, "memory": 1}})),
                ("unsupported with slots", declaration(codex={
                    "support": "unsupported", "agent_slots": 4})),
                ("reserved direct", declaration(direct=supported)),
                ("bad route name", declaration(**{"Claude Code": supported})),
                ("no routes", declaration()),
                ("schema two", {"schema_version": 2, "routes": {"claude-code": supported}}),
                ("duplicate key", '{"schema_version": 1, "schema_version": 1, "routes": '
                                  '{"claude-code": {"support": "supported", "agent_slots": 7}}}'),
                ("not json", "{")):
            with self.subTest(label):
                install_declaration(self.home, value)
                self.assertEqual(self.answer("claude-code"),
                                 self.unsupported("claude-code", "declaration_invalid"))

    def test_usage_errors_exit_two_and_nothing_is_written(self):
        install_declaration(self.home, json.loads(
            COMMITTED_DECLARATION.read_text(encoding="utf-8")))
        before = sorted(path.relative_to(self.home) for path in self.home.rglob("*"))
        for route in ("direct", "Claude Code", ""):
            with self.subTest(route=route):
                completed = self.host_route(route)
                self.assertEqual((completed.returncode, completed.stdout), (2, b""))
        self.answer("claude-code")
        self.assertEqual(
            sorted(path.relative_to(self.home) for path in self.home.rglob("*")), before)


if __name__ == "__main__":
    unittest.main()
```

In `T/_delivery_model_fixtures.py`, add to `workflow_responses`' returned dict:

```python
        "host_route": {"interface_version": 1, "kind": "host_route", "route": "claude-code",
                       "support": "supported", "agent_slots": 7, "reason_code": None,
                       "alternative": None},
        "host_route_unsupported": {"interface_version": 1, "kind": "host_route",
                                   "route": "codex", "support": "unsupported",
                                   "agent_slots": None, "reason_code": "declared_unsupported",
                                   "alternative": "/from-issue <issue> --auto"},
```

In `T/test_delivery_model.py` `test_workflow_response_validation_is_structural_only`, add
`"host_route", "host_route_unsupported"` to the asserted fixture-key set, and add these
mutations before the `for name, value in mutations.items():` loop:

```python
        bad = copy.deepcopy(fixtures["host_route"]); bad["agent_slots"] = 3; mutations["host_route_floor"] = bad
        bad = copy.deepcopy(fixtures["host_route"]); bad["reason_code"] = "declared_unsupported"; mutations["host_route_supported_reason"] = bad
        bad = copy.deepcopy(fixtures["host_route_unsupported"]); bad["reason_code"] = "busy"; mutations["host_route_reason"] = bad
        bad = copy.deepcopy(fixtures["host_route_unsupported"]); bad["alternative"] = None; mutations["host_route_alternative"] = bad
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_host_admission.py home/common/agent-skills/tests/test_delivery_model.py 2>&1 | tail -5`
Expected: FAIL — `host-route` is an invalid choice (exit 2) and the new fixtures are rejected at the boundary.

- [ ] **Step 3: Implement**

1. `host_admission.py`: the Produces names above; module docstring states it is the one home of
   the declaration vocabulary and is imported by `workflow-state` and the conformance evaluator,
   never run (per D18). `load_declaration`: `declaration_path()` `None` or the path not an existing
   file → `DeclarationError("declaration_missing")`; any `OSError`/`UnicodeDecodeError` on read,
   JSON error, duplicate key (`object_pairs_hook`), non-finite token (`parse_constant`) or
   `validate_declaration` refusal → `DeclarationError("declaration_invalid")`. Follow symlinks
   (the installed file is a store link). Return a deep copy of the validated document.
2. `host-declaration.json`: exactly the document `test_committed_declaration_is_the_designed_host_budget` pins (per D16), two-space indented.
3. `workflow-state.py`: `_host_admission()` mirrors `_delivery()` — `Path(__file__).parent / "host_admission.py"` when that parent is named `scripts`, else `Path.home() / ".agents/lib/python/host_admission.py"`; loads under module name `_workflow_host_admission` with `importlib.util`, requires `HOST_ADMISSION_INTERFACE_VERSION == 1`, caches the module, and wraps any failure as `WorkflowError("host admission library: …")`. `route_verdict(route)`:
   - `DeclarationError` → unsupported with that `reason_code`;
   - route absent from `routes` → `route_undeclared`; `support == "unsupported"` → `declared_unsupported`;
   - otherwise `{"interface_version": 1, "kind": "host_route", "route": route, "support": "supported", "agent_slots": n, "reason_code": None, "alternative": None}`;
   - every unsupported answer carries `agent_slots: None` and `alternative: UNSUPPORTED_ALTERNATIVE`.
   `command_host_route`: refuse a route that fails `ROUTE_NAME_PATTERN` or equals `DIRECT_ROUTE` with `WorkflowError` (exit 2), else `print_json(route_verdict(args.route))`. Register `host-route` with required `--route` in `build_parser`.
4. `_wire.py`: in `_workflow_response`, before the final `_reject()`, route `kind == "host_route"` to a new `_host_route(value)`: exact members `interface_version kind route support agent_slots reason_code alternative`; `interface_version` plain int 1; `route` non-empty string; `supported` ⇒ `_integer(value["agent_slots"], "agent slots", minimum=4)`, `reason_code` and `alternative` null; `unsupported` ⇒ `agent_slots` null, `reason_code` in the four codes, `alternative == "/from-issue <issue> --auto"`; anything else `_reject()`. The wire repeats the literals, as it repeats every closed set it validates.
5. `default.nix`, beside the platform library and manifest, with a comment that the declaration is authored host policy read by `workflow-state` and the conformance check (per D2, D18):
   `".agents/lib/python/host_admission.py".source = ./scripts/host_admission.py;`
   `".agents/share/host-declaration.json".source = ./host-declaration.json;`
6. `justfile`: add `home/common/agent-skills/tests/test_host_admission.py \` after `test_workflow_state.py` in `agent-workflow-tests`.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_host_admission.py home/common/agent-skills/tests/test_delivery_model.py 2>&1 | tail -3`
Expected: `OK`.

Run: `just build >/dev/null && hm=$(nix-store --query --requisites ./result | grep -- '-home-manager-files$') && cmp "$hm/.agents/share/host-declaration.json" home/common/agent-skills/host-declaration.json && cmp "$hm/.agents/lib/python/host_admission.py" home/common/agent-skills/scripts/host_admission.py && echo installed`
Expected: `installed` (fails at the base commit: neither file exists).

Run: `just agent-workflow-tests 2>&1 | tail -3`
Expected: `OK` (skips allowed as at base).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/host_admission.py home/common/agent-skills/host-declaration.json \
  home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/scripts/delivery_model/_wire.py \
  home/common/agent-skills/default.nix justfile home/common/agent-skills/tests/test_host_admission.py \
  home/common/agent-skills/tests/_delivery_model_fixtures.py home/common/agent-skills/tests/test_delivery_model.py
git commit -m "feat(workflow-state): declare host agent slots and answer host-route (#150)"
```
