# Task 1: Memoize the delivery runtime per process

Per D1. Hotspot H1: `_delivery()` in `workflow-state.py` runs `runpy.run_path` on `workflow_delivery.py` on every call, about 9 times per CLI invocation. `run_path` keeps no bytecode cache, so each call recompiles the file, and the `DeliveryRuntime` constructor then re-executes `delivery_model`, the builder and the projection modules.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (only `_delivery()` near line 266, plus one new module-level dict beside it)

**Interfaces:**
- Consumes: `phase_notes_maximum() -> int` (unchanged; raises `WorkflowError` on a missing or invalid policy), `runpy.run_path`, and `WORKFLOW_DELIVERY_INTERFACE_VERSION`/`DeliveryRuntime` from `workflow_delivery.py` (all unchanged).
- Produces: `_DELIVERY_RUNTIMES: dict[int, Any]`, a module global that maps a notes limit to the `DeliveryRuntime` built for it. `_delivery()` keeps its name, signature and callers.

**Invariants:**
- Two calls in one process with the same notes limit return the same object (`is`).
- The notes limit is read through `phase_notes_maximum()` on every call, hits included. A changed policy limit therefore selects or builds a different runtime.
- A failed load is not stored. It raises `WorkflowError` whose text starts `delivery runtime: `, followed by the same cause text as at `BASE`. The next call loads again.
- On a miss, the load order is unchanged: `run_path`, then the interface check, then `phase_notes_maximum()`, then the constructor. A run that fails in two places therefore reports the same first cause as at `BASE`.
- No change to `workflow_delivery.py`, its loaders or the installed layout.

- [ ] **Step 1: Write the failing probe** (scratch only, never committed)

```bash
cat > "${TMPDIR:-/tmp}/issue262-t1-probe.py" <<'PY'
import importlib.util, runpy, sys
from pathlib import Path
from unittest import mock
SCRIPT = Path("home/common/agent-skills/scripts/workflow-state.py").resolve()
def fresh(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module
    spec.loader.exec_module(module); return module
one = fresh("probe_ws_one")
assert one._delivery() is one._delivery(), "runtime rebuilt on a second call"
two = fresh("probe_ws_two")
real = runpy.run_path
with mock.patch.object(two.runpy, "run_path", side_effect=[RuntimeError("boom"), real(str(SCRIPT.with_name("workflow_delivery.py")))]):
    try:
        two._delivery(); raise AssertionError("failure not raised")
    except two.WorkflowError as error:
        assert str(error) == "delivery runtime: boom", str(error)
    assert two._delivery() is two._delivery(), "failure was cached or retry not memoized"
print("T1-PROBE-OK")
PY
```

- [ ] **Step 2: Run it and watch it fail**

Run: `PYTHONPATH=python python3 "${TMPDIR:-/tmp}/issue262-t1-probe.py"`
Expected at `BASE`: `AssertionError: runtime rebuilt on a second call`.

- [ ] **Step 3: Implement**

The exact shape, which holds the ordering and failure invariants above:

```python
_DELIVERY_RUNTIMES: dict[int, Any] = {}


def _delivery():
    """The delivery runtime, built once per process for each notes limit (#262 D1).

    The notes limit is read from the artifact-budget policy on every call. A load
    that fails is not kept, so the next call loads again.
    """
    src = Path(__file__).parent
    entry = src / "workflow_delivery.py" if src.name == "scripts" else Path.home() / ".agents/lib/python/workflow_delivery.py"
    try:
        if _DELIVERY_RUNTIMES:
            runtime = _DELIVERY_RUNTIMES.get(phase_notes_maximum())
            if runtime is not None:
                return runtime
        module = runpy.run_path(str(entry))
        if module.get("WORKFLOW_DELIVERY_INTERFACE_VERSION") != 1:
            raise ValueError("interface")
        maximum = phase_notes_maximum()
        runtime = module["DeliveryRuntime"](notes_max_characters=maximum)
    except Exception as exc:
        raise WorkflowError(f"delivery runtime: {exc}") from exc
    _DELIVERY_RUNTIMES[maximum] = runtime
    return runtime
```

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 "${TMPDIR:-/tmp}/issue262-t1-probe.py"` and expect `T1-PROBE-OK`.

Then run each of these modules, logging to `${TMPDIR:-/tmp}/issue262-t1-<name>.log` and reporting only the `Ran`/`OK`/`FAILED` tail:
- `home/common/agent-skills/tests/test_workflow_delivery.py`
- `home/common/agent-skills/tests/test_delivered_control.py`
- `home/common/agent-skills/tests/test_admission_replay.py`
- `home/common/agent-skills/tests/test_delivery_workflow.py`, which calls a loaded module's `_delivery()` many times in one process (`timeout 900`)
- `home/common/agent-skills/tests/test_workflow_state.py` (`timeout 1200`)

Expected: every module `OK`. Then run the root's coverage gate and expect `COVERAGE-GATE-OK 2077 test ids`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id run-20261006-261-262-263-264-265 --worker-id <your worker id> -- \
  -m "perf(workflow-state): build the delivery runtime once (#262)" -m "<trailer lines>"
```
