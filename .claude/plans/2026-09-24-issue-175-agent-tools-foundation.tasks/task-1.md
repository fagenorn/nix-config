# Task 1: The package and its canonical module

Decisions: D3, D4 (the `pyproject.toml` and `__init__` parts), D6, D7 (the
canonical test). Spec sections "The canonical module (D3)" and "The package and
its build (D4)". Work from the worktree root. `PK` = `python/agent_tools`.

**Files:**
- Create: `python/pyproject.toml`
- Create: `PK/__init__.py`
- Create: `PK/canonical.py`
- Create: `tests/test_agent_tools_canonical.py`
- Modify: `justfile` (one new variable; the `agent-workflow-tests` recipe)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - the package `agent_tools`, importable when `PYTHONPATH` names `python/`;
  - `agent_tools.canonical.telemetry_digest(body: object) -> str`;
  - `agent_tools.canonical.reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]`
    (an `object_pairs_hook`);
  - `agent_tools.canonical.reject_nonfinite_literal(name: str) -> NoReturn` (a
    `parse_constant` hook);
  - the justfile variable `agent_tools_path` (the absolute `python/` directory).

  Tasks 2–4 import these three names directly, never under an alias (D3). Task 4
  reads `project.name` and `project.version` from the `pyproject.toml`.

**Invariants:**
- Each function body and message is byte-identical to today's copies:
  `scripts/agent-costs.py` L1064–1067 for the digest, and
  `scripts/agent-gate-bundle.py` L118–128 for the two hooks. The digest has no
  trailing newline, and `allow_nan` keeps `json`'s default.
- `canonical` imports only `hashlib`, `json` and `typing.NoReturn`, and does
  nothing at import time beyond defining its three functions.
- `PK/__init__.py` holds a docstring only: no imports, no re-exports.
- `pyproject.toml` has a setuptools backend, `name = "agent-tools"`,
  `version = "0.1.0"` and `dependencies = []`. It has no `[project.scripts]`, and
  `[tool.setuptools.packages.find]` sets `include = ["agent_tools*"]`.
- `agent-workflow-tests` assigns `PYTHONPATH` (it never prepends to it), so an
  ambient value cannot reach the suite (D6).

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_tools_canonical.py`:

```python
"""The one shared home of canonical-JSON knowledge (#175 D3, parent D11).

Run: just agent-workflow-tests
"""

import json
import unittest

from agent_tools.canonical import (reject_duplicate_keys, reject_nonfinite_literal,
                                   telemetry_digest)

# Unsorted keys at two levels, nesting, a non-ASCII string and a float.
GOLDEN_BODY = {"z": [1, 2.5, {"b": "é", "a": None}], "a": True}
# sha256 over the 46 ASCII bytes {"a":true,"z":[1,2.5,{"a":null,"b":"\u00e9"}]}
# (the "é" travels as the six ASCII characters \u00e9), computed outside
# Python. Every other digest assertion recomputes its expected value with the
# function it checks, so only this literal catches a format drift.
GOLDEN_DIGEST = "sha256:aac12d1f6010a8c2744d12c9a15e43fe5a6c3995b75d1cc756a742da24a5b682"


class TelemetryDigestTest(unittest.TestCase):
    def test_the_digest_format_is_pinned_by_a_golden_value(self):
        self.assertEqual(telemetry_digest(GOLDEN_BODY), GOLDEN_DIGEST)


class StrictLoadHookTest(unittest.TestCase):
    def test_a_repeated_key_is_refused_by_name(self):
        with self.assertRaises(ValueError) as caught:
            json.loads('{"a": 1, "b": 2, "a": 3}', object_pairs_hook=reject_duplicate_keys)
        self.assertEqual(str(caught.exception), "duplicate JSON key 'a'")

    def test_distinct_keys_build_the_object_in_document_order(self):
        value = json.loads('{"b": 1, "a": {"c": 2}}', object_pairs_hook=reject_duplicate_keys)
        self.assertEqual(list(value), ["b", "a"])
        self.assertEqual(value, {"b": 1, "a": {"c": 2}})

    def test_each_nonfinite_literal_is_refused_by_name(self):
        for literal in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(literal=literal):
                with self.assertRaises(ValueError) as caught:
                    json.loads(f'{{"x": {literal}}}', parse_constant=reject_nonfinite_literal)
                self.assertEqual(str(caught.exception), f"JSON constant {literal} is not allowed")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_agent_tools_canonical.py 2>&1 | tail -3`
Expected: `FAILED (errors=1)`, from `ModuleNotFoundError: No module named 'agent_tools'`.
Confirm this at the starting commit, where `python/` does not exist.

- [ ] **Step 3: Write the package**

`python/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[project]
name = "agent-tools"
version = "0.1.0"
dependencies = []

[tool.setuptools.packages.find]
include = ["agent_tools*"]
```

`PK/__init__.py`:

```python
"""Agent workflow helpers, packaged; command modules run as `python -m agent_tools.<module>`."""
```

`PK/canonical.py`. The bodies are a wire format, so they are copied exactly:

```python
"""Canonical-JSON knowledge shared by the agent tools.

`telemetry_digest` is the telemetry digest format (agent-cost-telemetry D9).
The two hooks are strict-load building blocks: each caller passes exactly the
hooks it applies, so sharing them changes no command's accepted input.
"""

import hashlib
import json
from typing import NoReturn


def telemetry_digest(body: object) -> str:
    """'sha256:' + sha256 over `body` as sorted, compact, ASCII-escaped JSON.

    No trailing newline, and `allow_nan` keeps json's default.
    """
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """`object_pairs_hook`: build the object, refusing the first repeated key."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def reject_nonfinite_literal(name: str) -> NoReturn:
    """`parse_constant` hook; json calls it only for NaN, Infinity and -Infinity."""
    raise ValueError(f"JSON constant {name} is not allowed")
```

- [ ] **Step 4: Wire the test recipe (D6)**

In `justfile`, directly above the `# Verify durable workflow lifecycle…` comment
of `agent-workflow-tests`, add:

```
# The source package the agent recipes run (#175 D6).
agent_tools_path := justfile_directory() / "python"

```

In the `agent-workflow-tests` body, change only the first line,
`  python3 -m unittest -v \`, to
`  PYTHONPATH="{{agent_tools_path}}" python3 -m unittest -v \`. Then insert
`    tests/test_agent_tools_canonical.py \` on its own line directly above
`    tests/test_agent_costs.py \`. Leave every other line of the list as it is.

- [ ] **Step 5: Verify**

Run: `PYTHONPATH=python python3 -m unittest -v tests/test_agent_tools_canonical.py 2>&1 | tail -3`
Expected: `Ran 4 tests` then `OK`.

Run: `just --dry-run agent-workflow-tests 2>&1 | grep -oE '^PYTHONPATH="[^"]*" python3 -m unittest -v|tests/test_agent_tools_canonical\.py'`
Expected: two lines. The first is `PYTHONPATH="<worktree>/python" python3 -m unittest -v`,
where `<worktree>` is this worktree's absolute path, and the second is
`tests/test_agent_tools_canonical.py`. `just` prints the recipe joined onto
one line.

Run: `if grep -n "^import\|^from" python/agent_tools/__init__.py; then exit 1; fi; echo init-clean`
Expected: `init-clean`.

Run: `just agent-workflow-tests 2>&1 | tail -3`
Expected: `OK (skipped=1)`, with 4 more tests than the baseline.

- [ ] **Step 6: Commit**

```bash
git add python/pyproject.toml python/agent_tools/__init__.py \
  python/agent_tools/canonical.py tests/test_agent_tools_canonical.py justfile
git commit -m "feat(agent-tools): add the package and its shared canonical module"
```

The message ends with the trailer lines named in the plan's Global Constraints.
