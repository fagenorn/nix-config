# Task 1: Report schema, closed vocabularies, and `validate-report`

**Files:**
- Create: `home/common/agent-skills/scripts/conformance.py`
- Create: `home/common/agent-skills/tests/test_conformance.py`
- Modify: `home/common/agent-skills/default.nix`
- Modify: `justfile`

**Interfaces:**
- Produces, for Tasks 2–7:
  - Module constants `SCHEMA_VERSION = 1`, `DOMAINS`, `REQUIREMENTS`, `STATUSES`, `OUTCOME_STATUSES`, `SAFETY_CLASSES`, `PURPOSES`, `SUBJECT_KINDS`, `REPORT_MEMBERS`, `CHECK_MEMBERS`, `REPAIR_MEMBERS`, `REPAIR_MODULES` — each a `tuple[str, ...]` except `SCHEMA_VERSION`.
  - `class ReportError(Exception)` with `__init__(self, violations: list[dict]) -> None` and attribute `violations`, each entry `{"pointer": str, "message": str}`.
  - `def validate_report(report: object) -> None` — returns `None` for a schema-valid report, raises `ReportError` otherwise.
  - `def bound_fact(value: str) -> str` and `def bound_facts(values, limit: int = MAX_FACT_LIST) -> list[str]` — the one fact-bounding helper pair every evaluator routes authored or filesystem-derived strings through (D30).
  - `def emit_json(value: object) -> int` and `def emit_error(code: str, repair_id: str, violations: list[dict]) -> int` — byte-identical in behaviour to the resolver's, exit codes 0 and 2.
  - `def build_parser() -> argparse.ArgumentParser`, `def dispatch(args) -> int`, `def main(argv: list[str] | None = None) -> int`, guarded by `if __name__ == "__main__":`.
- Consumes: nothing from earlier tasks.

**Invariants:**
- `validate_report` is a *pure* function of the parsed object: it opens no file, starts no process, and never mutates its argument.
- A report is valid only when its member set is **exactly** `REPORT_MEMBERS` — a missing member and an extra member are each a violation.
- `repairs` and the set of non-null `repair_id` values across `checks` are the same set: a check naming a repair absent from `repairs` is a violation, and a repair no check names is a violation.
- No member anywhere in a valid report may be named `timestamp`, `created_at`, `generated_at`, or `time` — **including a `facts` key**, which `validate_facts` enforces itself rather than inheriting (D37).
- The validator pins every invariant the plan root declares, not only field shapes (D37): outcome precedence against the emitted statuses; `primary_check_id` naming the first `failed` check in emitted order, else the first required `not_run`, else `null`; a `suppressed` check carrying exactly `{"suppressed_by": <str>}` and a null `repair_id`; and `passed` implying a null `reason_code` and a null `repair_id`. Membership of `request.required_capabilities` in the resolver's `CAPABILITY_NAMES` stays out of the validator — sourcing it would mean loading the resolver and break the purity invariant above; the closed argparse `choices` is its enforcement point, and Task 2's report test asserts the emitted set is a subset.
- `ReportError.violations` is non-empty and sorted byte-wise ascending by `pointer`.
- The module defines no `run` subcommand in this task: a committed placeholder subcommand is a defect (the bar, *Production-grade by default*).

## Vocabularies to define, verbatim

```python
SCHEMA_VERSION = 1
DOMAINS = ("repository", "compatibility", "host", "verification")
REQUIREMENTS = ("required", "optional")
STATUSES = ("passed", "warning", "failed", "not_run", "suppressed")
OUTCOME_STATUSES = ("passed", "failed", "incomplete")
SAFETY_CLASSES = ("read_only", "worktree", "user_action", "destructive")
PURPOSES = ("workflow_entry", "adoption", "local", "ci", "fleet", "doctor")
SUBJECT_KINDS = ("contract", "projection", "path", "capability", "host_tool",
                 "tracker", "release_profile", "residue", "command")
REPORT_MEMBERS = ("schema_version", "subject", "request", "outcome", "checks", "repairs")
SUBJECT_MEMBERS = ("project_id", "root", "revision", "platform")
PLATFORM_MEMBERS = ("system", "machine")
REQUEST_MEMBERS = ("purpose", "offline", "required_capabilities", "platform_target")
OUTCOME_MEMBERS = ("status", "primary_check_id")
CHECK_MEMBERS = ("id", "domain", "subject_kind", "requirement", "status",
                 "reason_code", "repair_id", "facts")
REPAIR_MEMBERS = ("repair_id", "module", "safety_class", "operation")
OPERATION_MEMBERS = ("subcommand", "args")
REPAIR_MODULES = ("conformance", "resolve-project")
FORBIDDEN_MEMBER_NAMES = ("created_at", "generated_at", "time", "timestamp")
MAX_FACT_KEYS = 8
MAX_FACT_STRING = 200
MAX_FACT_LIST = 8
```

- [ ] **Step 1: Write the failing test**

Create `home/common/agent-skills/tests/test_conformance.py` with the module docstring, the subprocess helper, a valid-report fixture builder, and these cases.

```python
"""Contract tests for scripts/conformance.

Runs the engine as a subprocess against temporary repository roots and parses
its stdout, the seam test_resolve_project.py established (D16). The module is
imported only for the seams no subprocess run can reach.

Every run is environment-hermetic (D35): the child never inherits the caller's
environment, so no test can reach the network, the caller's credentials or a
tool the fixture did not place. HERMETIC_ENV points PATH at a stub bin holding
one exit-0 script per tool the contract names; a case that needs a different
tool outcome builds its own bin with make_stub_bin and overrides PATH.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "conformance.py"
REPO_ROOT = Path(__file__).resolve().parents[4]
STUB_TOOLS = ("codex", "gh", "git", "just")


def make_stub_bin(directory: Path, exits: dict | None = None) -> str:
    """A bin directory holding one executable stub per STUB_TOOLS.

    Each stub prints nothing and exits 0 unless `exits` names a different code
    for it, so a fixture decides every tool outcome the engine can observe.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for tool in STUB_TOOLS:
        stub = directory / tool
        stub.write_text(f"#!/bin/sh\nexit {(exits or {}).get(tool, 0)}\n",
                        encoding="utf-8")
        stub.chmod(0o755)
    return str(directory)


_HERMETIC_HOME = tempfile.mkdtemp(prefix="conformance-home-")
HERMETIC_ENV = {
    "PATH": make_stub_bin(Path(tempfile.mkdtemp(prefix="conformance-bin-"))),
    "HOME": _HERMETIC_HOME,
    "TMPDIR": _HERMETIC_HOME,
    "LANG": "C",
}


def run(*args: str, env: dict | None = None,
        cwd: str | Path | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=60,
        env=HERMETIC_ENV if env is None else env, cwd=None if cwd is None else str(cwd),
    )
    return proc.returncode, proc.stdout, proc.stderr


@contextlib.contextmanager
def fixture():
    """A temporary directory, as a Path."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def doctor(case, root, *extra: str, env: dict | None = None) -> tuple[dict, dict]:
    """One `doctor` run: asserts exit 0, returns (report, {check id: check}).

    Tasks 2-7 read every check through this, so no case re-spells the run, the
    exit assertion or the id index.
    """
    code, out, err = run("run", "--purpose", "doctor", "--repo-root", str(root),
                         *extra, env=env)
    case.assertEqual(code, 0, err)
    report = json.loads(out)
    return report, {c["id"]: c for c in report["checks"]}


def valid_report() -> dict:
    """A minimal schema-valid report: one failed check and the repair it names."""
    return {
        "schema_version": 1,
        "subject": {"project_id": "fagenorn/nix-config", "root": "/tmp/x",
                    "revision": None, "platform": {"system": "Darwin", "machine": "arm64"}},
        "request": {"purpose": "doctor", "offline": False,
                    "required_capabilities": [], "platform_target": "Darwin/arm64"},
        "outcome": {"status": "failed", "primary_check_id": "repository.contract.present"},
        "checks": [{"id": "repository.contract.present", "domain": "repository",
                    "subject_kind": "contract", "requirement": "required",
                    "status": "failed", "reason_code": "not_onboarded",
                    "repair_id": "onboarding.contract.missing", "facts": {}}],
        "repairs": [{"repair_id": "onboarding.contract.missing",
                     "module": "resolve-project", "safety_class": "user_action",
                     "operation": None}],
    }


def write_report(tmp: Path, mutate=None) -> Path:
    report = valid_report()
    if mutate is not None:
        mutate(report)
    path = tmp / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


class ValidateReportTest(unittest.TestCase):
    """S2: the validator, as a subprocess."""

    def check(self, mutate, pointer: str) -> None:
        with fixture() as tmp:
            path = write_report(tmp, mutate)
            code, out, _ = run("validate-report", "--input", str(path))
            self.assertEqual(code, 2)
            payload = json.loads(out)
            self.assertEqual(payload["error"]["code"], "resolver_failure")
            self.assertIn(pointer, [v["pointer"] for v in payload["error"]["violations"]])

    def test_valid_report_is_accepted(self):
        with fixture() as tmp:
            path = write_report(tmp)
            code, out, _ = run("validate-report", "--input", str(path))
            self.assertEqual(code, 0, out)
            self.assertEqual(json.loads(out), {"valid": True})

    def test_each_schema_violation_is_refused_at_its_pointer(self):
        for name, (mutate, pointer) in REFUSALS.items():
            with self.subTest(case=name):
                self.check(mutate, pointer)

    def test_unreadable_input_is_refused(self):
        code, out, _ = run("validate-report", "--input", "/nonexistent/report.json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["code"], "resolver_failure")

    def test_unknown_subcommand_is_an_argparse_error(self):
        code, out, err = run("frobnicate")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("usage:", err)


if __name__ == "__main__":
    unittest.main()
```

`REFUSALS` is a module-level `{case name: (mutate, pointer)}` table, each `mutate` a callable taking the valid report and making **exactly one** violation reachable. Where a mutation would otherwise cascade, it also repairs the collateral — clearing `repairs` and resetting `outcome` to `{"status": "passed", "primary_check_id": None}` — so each row isolates the invariant it names:

| Case | Mutation | Pointer |
|---|---|---|
| extra top-level member | `report["extra"] = 1` | `/extra` |
| missing top-level member | `report.pop("repairs")` | `/repairs` |
| timestamp member | `report["subject"]["timestamp"] = 0` | `/subject/timestamp` |
| unknown status | check `status` → `"skipped"` | `/checks/0/status` |
| unknown safety class | repair `safety_class` → `"risky"` | `/repairs/0/safety_class` |
| unknown subject kind | check `subject_kind` → `"widget"` | `/checks/0/subject_kind` |
| dangling repair id | `report["repairs"].clear()` | `/repairs` |
| unreferenced repair | check `repair_id` → `None` | `/repairs` |
| oversized facts | nine keys in `facts` | `/checks/0/facts` |
| overlong fact string | `facts = {"k": "x" * 201}` | `/checks/0/facts/k` |
| nested object fact | `facts = {"k": {"a": 1}}` | `/checks/0/facts/k` |
| timestamp-named fact key | `facts = {"created_at": 1}` | `/checks/0/facts/created_at` |
| unsorted required capabilities | `["worktrees", "tracker"]` | `/request/required_capabilities` |
| repairs out of order | append a second check naming `contract.invalid`, insert that repair **first** | `/repairs` |
| failed check under a passed outcome | outcome → `passed` / `None` | `/outcome/status` |
| required `not_run` under a passed outcome | check → `not_run` / `offline_constraint`, outcome → `passed` | `/outcome/status` |
| `primary_check_id` naming a passing check | append a passing second check and name it | `/outcome/primary_check_id` |
| suppressed check carrying a repair | check → `suppressed`, `facts = {"suppressed_by": "x"}`, repair kept | `/checks/0/repair_id` |
| suppressed check without `suppressed_by` | check → `suppressed`, `facts = {}` | `/checks/0/facts` |
| passed check carrying a reason code | check → `passed` with `reason_code` set | `/checks/0/reason_code` |

The last six rows are the ones the field-shape validator alone would let through: they pin outcome precedence, primary-check selection, suppression's exact facts and null repair, and status/reason/repair consistency (D37).

- [ ] **Step 2: Run the test and watch it fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py`
Expected: every case ERRORs — `scripts/conformance.py` does not exist, so the subprocess exits non-zero with a Python traceback on stderr and empty stdout.

- [ ] **Step 3: Write the minimal implementation**

Create `home/common/agent-skills/scripts/conformance.py` with a shebang `#!/usr/bin/env python3`, a module docstring naming it the conformance engine, `from __future__ import annotations`, the vocabularies above, and:

```python
class ReportError(Exception):
    """One schema refusal: ordered violations against a candidate report."""
    def __init__(self, violations: list[dict]) -> None: ...


def validate_report(report: object) -> None:
    """Contract: returns None for a schema-valid report; otherwise raises
    ReportError whose violations are sorted byte-wise ascending by pointer."""
```

Structure the validator as one collecting pass — it owes the caller every violation it can see, exactly as `validate_contract` does — using small helpers that append to a shared `violations` list:

- `exact_members(value, pointer, expected, violations)` — refuses a non-object, each absent member as `<pointer>/<name>` "required member is absent", and each unexpected member as `<pointer>/<name>` "member is not part of this schema". Reject a member whose name is in `FORBIDDEN_MEMBER_NAMES` here, at every object depth, with the message "this schema carries no timestamp".
- `closed_value(value, pointer, allowed, violations)` — the value must be a `str` in `allowed`.
- Top level: `schema_version` must be the integer `1` (a `bool` is not an int here); `subject`, `request`, `outcome` are objects with exactly `SUBJECT_MEMBERS`, `REQUEST_MEMBERS`, `OUTCOME_MEMBERS`; `checks` and `repairs` are lists.
- `subject.project_id` is a `str` or `None`; `subject.root` is a non-empty `str`; `subject.revision` is `None` or a 40-character lowercase hex `str`; `subject.platform` is an object with exactly `PLATFORM_MEMBERS`, both non-empty strings.
- `request.purpose` ∈ `PURPOSES`; `request.offline` is a `bool`; `request.required_capabilities` is a list of strings, sorted and duplicate-free; `request.platform_target` is a non-empty `str`.
- `outcome.status` ∈ `OUTCOME_STATUSES` **and agrees with the emitted checks**: `failed` iff some check is `failed`, else `incomplete` iff some `required` check is `not_run`, else `passed`. `outcome.primary_check_id` is `None` when the outcome is `passed`, and otherwise names the first `failed` check in emitted order, or the first required `not_run` when the outcome is `incomplete`. Report a disagreement at `/outcome/status` or `/outcome/primary_check_id` (D37).
- Each check: exactly `CHECK_MEMBERS`; `domain` ∈ `DOMAINS`; `subject_kind` ∈ `SUBJECT_KINDS`; `requirement` ∈ `REQUIREMENTS`; `status` ∈ `STATUSES`; `id` a non-empty `str`; `reason_code` `None` or a non-empty `str`; `repair_id` `None` or a non-empty `str`; `facts` an object validated by `validate_facts`. Check ids must be unique and the list sorted ascending by `id` (D24) — an unsorted list is a violation at `/checks`.
- Status consistency, per check (D37): `passed` requires a null `reason_code` and a null `repair_id`; `suppressed` requires a null `reason_code`, a null `repair_id` and `facts` exactly `{"suppressed_by": <non-empty str>}`; `failed`, `warning` and `not_run` each require a non-null `reason_code`. Report at `<pointer>/reason_code`, `<pointer>/repair_id` or `<pointer>/facts`.
- `validate_facts(facts, pointer, violations)`: at most `MAX_FACT_KEYS` keys; no key in `FORBIDDEN_MEMBER_NAMES`; each value is a `bool`, an `int` that is not a `bool`, a `str` of at most `MAX_FACT_STRING` characters, or a `list` of at most `MAX_FACT_LIST` such strings. Anything else — a float, a nested object, a `None`, an over-long string — is a violation at `<pointer>/<key>`; too many keys is a violation at `<pointer>` (D9).
- Each repair: exactly `REPAIR_MEMBERS`; `safety_class` ∈ `SAFETY_CLASSES`; `module` ∈ `REPAIR_MODULES`; `operation` is `None` or an object with exactly `OPERATION_MEMBERS` whose `subcommand` is a non-empty `str` and whose `args` is a list of strings (D25). Repair ids must be unique and the list sorted ascending by `repair_id`; an unsorted or duplicated list is a violation at `/repairs`.
- Referential closure, both directions, reported at `/repairs`: `{c["repair_id"] for c in checks if c["repair_id"] is not None}` must equal `{r["repair_id"] for r in repairs}`. Report the missing set and the unreferenced set as separate violations with distinct messages so a reader learns which direction failed.

The fact-bounding helper pair (D30) — the single place any evaluator turns an authored or filesystem-derived value into a fact, so no evaluator ever reasons about whether its own subject can be long:

```python
def bound_fact(value: str) -> str:
    """Contract: `value` truncated to MAX_FACT_STRING characters."""


def bound_facts(values, limit: int = MAX_FACT_LIST) -> list[str]:
    """Contract: the first `limit` of `sorted(values)`, each through bound_fact."""
```

Only an engine-authored literal — a registry id, a closed-set member, a repair id — may become a fact without passing through them.

Emitters, copied in behaviour from the resolver so both tools print identical bytes for identical values:

```python
def emit_json(value: object) -> int:
    json.dump(value, sys.stdout, sort_keys=True, separators=(",", ":"),
              allow_nan=False)
    sys.stdout.write("\n")
    return 0


def emit_error(code: str, repair_id: str, violations: list[dict]) -> int:
    emit_json({"error": {"code": code, "repair_id": repair_id,
                         "violations": violations}})
    return 2
```

`command_validate_report(args)` reads `args.input` as UTF-8 and parses it. An `OSError`, a `UnicodeDecodeError` or a `json.JSONDecodeError` becomes a single violation at pointer `""` describing which of the three happened. It then calls `validate_report`; on `ReportError` it returns `emit_error("resolver_failure", "conformance.internal", err.violations)`, and on success it returns `emit_json({"valid": True})`.

`build_parser` creates the top-level parser with `prog="conformance"` and a required subparser dest, and registers only `validate-report` with a required `--input PATH`. `dispatch` maps the subcommand name to its handler through a dict and raises `ValueError(f"unknown subcommand: {name!r}")` on an unknown key rather than defaulting. `main` parses, dispatches, and returns the handler's exit code.

- [ ] **Step 4: Wire the binary and the suite**

In `home/common/agent-skills/default.nix`, immediately after the `".agents/bin/resolve-project"` block, add:

```nix
    ".agents/bin/conformance" = {
      source = ./scripts/conformance.py;
      executable = true;
    };
```

In `justfile`, add `home/common/agent-skills/tests/test_conformance.py` to the `agent-workflow-tests` module list, on the line immediately after `test_resolve_project.py`.

- [ ] **Step 5: Verify**

```bash
python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py
just agent-workflow-tests
just build
grep -q 'test_conformance.py' justfile
grep -q '.agents/bin/conformance' home/common/agent-skills/default.nix
if grep -Eq '"run"|add_parser\("run"' home/common/agent-skills/scripts/conformance.py; then
  echo "placeholder run subcommand committed"; exit 1
fi
```

Expected: the unittest run reports OK, with every REFUSALS subtest green; `just agent-workflow-tests` passes with the new module included; `just build` succeeds; both greps succeed; the placeholder guard prints nothing and exits 0.

Falsifiability at the base commit: `python3 -m unittest home/common/agent-skills/tests/test_conformance.py` fails, because neither the test module nor the script exists.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/scripts/conformance.py \
        home/common/agent-skills/tests/test_conformance.py \
        home/common/agent-skills/default.nix justfile
git commit -m "$(cat <<'MSG'
feat(conformance): add the ConformanceReport schema and its validator

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0128oBTKhwUFwSefRhxX2PAy
MSG
)"
```
