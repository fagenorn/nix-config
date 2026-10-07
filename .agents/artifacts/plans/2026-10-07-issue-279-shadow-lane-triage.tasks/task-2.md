# Task 2: `lane-triage evaluate` command

Spec sections **`lane-triage` input**, **`lane-triage` behavior and output** and **Refusals**; rows D1, D4, D5, D7, D8.

**Files:**
- Create: `python/agent_tools/lane_triage.py`
- Create: `tests/test_lane_triage.py`
- Modify: `lib/agent-tools.nix` (command table)
- Modify: `tests/test_agent_tools_launchers.py` (`LAUNCHER_FLOOR`)
- Modify: `justfile` (`agent-workflow-tests` file list)

**Interfaces:**
- Consumes (Task 1): `resolve_project.resolve(repo_root: str | None, required: list[str] | None = None) -> dict`, `resolve_project.ContractError` (attributes `code`, `repair_id`, `violations`, `reason_code`), `resolve_project.is_safe_relative_path(value) -> bool`. From `agent_tools.canonical`: `reject_duplicate_keys`, `reject_nonfinite_literal`.
- Produces (Task 3 names these in prose):
  - Command `lane-triage evaluate --repo-root <root> --input -` (both options required; `--input` accepts only `-`; module `agent_tools.lane_triage`, parser `prog="lane-triage"`).
  - `SIGNALS = ("contract_change", "concurrency_or_persistence", "open_design_questions", "criteria_shape")`, `VALUES = ("no", "hit", "doubt")`, `HIT_ORDER = SIGNALS + ("risk_path",)`.
  - `class TriageRefusal(Exception)` with attributes `code: str` and `detail: object`.
  - `load_record(text: str) -> dict` — strict load plus `validate_record`; raises `TriageRefusal("invalid_input", {"pointer": ..., "message": ...})`.
  - `validate_record(value: object) -> None` — raises at the first violation.
  - `light_lane_policy(repo_root: str) -> dict` — the authored `light_lane` object; raises `TriageRefusal("resolver_refused", <error document>)` or `TriageRefusal("light_lane_unsupported", None)`.
  - `evaluate(record: dict, light_lane: dict) -> dict` — pure; returns `{"hits": [...], "lane": "light"|"full", "mode": light_lane["mode"]}`.
  - `main(argv: list[str] | None = None) -> int`.

**Invariants:**
- The command writes no file and leaves the repository tree unchanged.
- Success: exit 0, stdout exactly `json.dumps(verdict, sort_keys=True, separators=(",", ":")) + "\n"`, stderr empty.
- Refusal: exit 2, stdout empty, stderr exactly one line `json.dumps({"error": {"code": code, "detail": detail}}, sort_keys=True, separators=(",", ":")) + "\n"`.
- Order of work (D8): read stdin whole → `light_lane_policy` (`resolver_refused`, then `light_lane_unsupported`) → `load_record` (`invalid_input`) → `evaluate`. An invalid record under an absent `light_lane` is therefore `light_lane_unsupported`.
- `resolver_refused` detail is the resolver's published error object, unchanged: `{"code", "repair_id", "violations"}` plus `"reason_code"` only when `ContractError.reason_code` is not `None` (D1, D5).
- `evaluate` never looks at `mode` to choose `lane`: `lane == "light"` exactly when `hits == []` (parent D3, D7). `hits` lists each signal whose `value` is not `"no"`, then `"risk_path"` when any `paths` entry matches any `risk_paths` glob under `fnmatch.fnmatchcase(path, glob)`, always in `HIT_ORDER` (D4, D5).
- `validate_record` walk (D8), stopping at the first violation:
  1. value not a dict → `("", "must be an object")`;
  2. top-level members: each of `("signals", "paths")` absent, in that order → `("/<name>", "required member is absent")`; then each other key, sorted → `("/<key>", "member is not part of this schema")`;
  3. `signals` not a dict → `("/signals", "must be an object")`; its members as in 2 over `SIGNALS` (pointer `/signals/<name>`);
  4. for each name in `SIGNALS` order: not a dict → `("/signals/<name>", "must be an object")`; members as in 2 over `("value", "evidence")`; `value` not in `VALUES` (or not a str) → `("/signals/<name>/value", "must be one of no, hit, doubt")`; `evidence` not a non-empty str, or containing `"\n"` or `"\r"` → `("/signals/<name>/evidence", "must be a non-empty string with no line break")`;
  5. `paths` not a list or empty → `("/paths", "must be a non-empty list")`; each entry failing `is_safe_relative_path` → `("/paths/<index>", "must be a non-empty repository-relative path with no '..' segment")`.
  A JSON parse failure (including a duplicate key or a non-finite constant) is `("", "not strict JSON: <exception text>")`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_lane_triage.py`:

```python
"""Contract tests for `lane-triage` (`agent_tools.lane_triage`, #279).

Runs the command as `python -m agent_tools.lane_triage` against a copy of the
eval fixture project under a temporary HOME holding the committed platform
manifest (agent-helpers rule 5).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "home/common/agent-skills/platform-manifest.json"
FIXTURE = REPO_ROOT / "home/common/agent-skills/evals/fixture-repo"
SIGNALS = ("contract_change", "concurrency_or_persistence",
           "open_design_questions", "criteria_shape")
ABSENT = object()
LIGHT_LANE = {"mode": "shadow", "budget_minutes": 45,
              "risk_paths": ["tinytask/store.py", "docs/*"]}


def record(paths=("tinytask/cli.py",), **values):
    return {"signals": {name: {"value": values.get(name, "no"),
                               "evidence": f"{name} judged from the issue"}
                        for name in SIGNALS},
            "paths": list(paths)}


def tree_snapshot(root: Path) -> list[tuple[str, str, int | None]]:
    out = []
    for path in sorted(root.rglob("*")):
        kind = "d" if path.is_dir() else "f"
        out.append((str(path.relative_to(root)), kind,
                    None if kind == "d" else path.stat().st_mtime_ns))
    return out


class LaneTriageCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        self.home = base / "home"
        (self.home / ".agents" / "share").mkdir(parents=True)
        shutil.copy(MANIFEST, self.home / ".agents" / "share" / "platform-manifest.json")
        self.root = base / "project"
        shutil.copytree(FIXTURE, self.root)
        self.set_light_lane(LIGHT_LANE)

    def set_light_lane(self, value) -> None:
        path = self.root / ".agents" / "project.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        workflow = contract["bindings"]["workflow"]
        workflow.pop("light_lane", None)
        if value is not ABSENT:
            workflow["light_lane"] = value
        path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

    def triage(self, payload, *args: str) -> tuple[int, str, str]:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        argv = list(args) or ["evaluate", "--repo-root", str(self.root), "--input", "-"]
        proc = subprocess.run(
            [sys.executable, "-m", "agent_tools.lane_triage", *argv],
            input=text, capture_output=True, text=True, timeout=60,
            env={**os.environ, "HOME": str(self.home)}, cwd=str(self.home))
        return proc.returncode, proc.stdout, proc.stderr

    def verdict(self, payload) -> dict:
        code, out, err = self.triage(payload)
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        self.assertTrue(out.endswith("\n"))
        self.assertEqual(out.count("\n"), 1)
        value = json.loads(out)
        self.assertEqual(out, json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
        self.assertEqual(sorted(value), ["hits", "lane", "mode"])
        return value

    def refusal(self, payload, code_name: str):
        code, out, err = self.triage(payload)
        self.assertEqual(code, 2, err)
        self.assertEqual(out, "")
        self.assertEqual(err.count("\n"), 1, err)
        document = json.loads(err)
        self.assertEqual(err, json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
        self.assertEqual(sorted(document), ["error"])
        self.assertEqual(sorted(document["error"]), ["code", "detail"])
        self.assertEqual(document["error"]["code"], code_name)
        return document["error"]["detail"]


class LaneTriageVerdictTest(LaneTriageCase):
    def test_an_all_no_record_is_light(self):
        self.assertEqual(self.verdict(record()),
                         {"hits": [], "lane": "light", "mode": "shadow"})

    def test_each_hit_or_doubt_is_full_and_named(self):
        for name in SIGNALS:
            for value in ("hit", "doubt"):
                with self.subTest(signal=name, value=value):
                    self.assertEqual(self.verdict(record(**{name: value})),
                                     {"hits": [name], "lane": "full", "mode": "shadow"})

    def test_a_path_matching_a_glob_adds_risk_path(self):
        self.assertEqual(self.verdict(record(paths=["tinytask/cli.py", "tinytask/store.py"])),
                         {"hits": ["risk_path"], "lane": "full", "mode": "shadow"})

    def test_a_star_glob_crosses_directories(self):
        self.assertEqual(
            self.verdict(record(paths=["docs/areas/system/adr/001-standard-library-only.md"]))["hits"],
            ["risk_path"])

    def test_hits_follow_the_fixed_signal_order(self):
        self.assertEqual(
            self.verdict(record(paths=["tinytask/store.py"], criteria_shape="doubt",
                                contract_change="hit"))["hits"],
            ["contract_change", "criteria_shape", "risk_path"])

    def test_an_empty_risk_path_map_never_hits(self):
        self.set_light_lane({**LIGHT_LANE, "risk_paths": []})
        self.assertEqual(self.verdict(record(paths=["tinytask/store.py"]))["hits"], [])

    def test_mode_is_echoed_and_never_changes_the_lane(self):
        self.set_light_lane({**LIGHT_LANE, "mode": "active"})
        self.assertEqual(self.verdict(record()),
                         {"hits": [], "lane": "light", "mode": "active"})
        self.assertEqual(self.verdict(record(open_design_questions="hit"))["lane"], "full")

    def test_the_run_leaves_the_tree_unchanged(self):
        for payload in (record(), "not json"):
            with self.subTest(payload=payload):
                before = tree_snapshot(self.root)
                self.triage(payload)
                self.assertEqual(tree_snapshot(self.root), before)


class LaneTriageRefusalTest(LaneTriageCase):
    def test_an_absent_light_lane_is_unsupported(self):
        self.set_light_lane(ABSENT)
        self.assertIsNone(self.refusal(record(), "light_lane_unsupported"))

    def test_a_null_light_lane_is_unsupported(self):
        self.set_light_lane(None)
        self.assertIsNone(self.refusal(record(), "light_lane_unsupported"))

    def test_unsupported_wins_over_an_invalid_record(self):
        self.set_light_lane(ABSENT)
        self.assertIsNone(self.refusal("not json", "light_lane_unsupported"))

    def test_a_malformed_contract_is_resolver_refused(self):
        self.set_light_lane({**LIGHT_LANE, "mode": "fast"})
        detail = self.refusal(record(), "resolver_refused")
        self.assertEqual(sorted(detail), ["code", "repair_id", "violations"])
        self.assertEqual(detail["code"], "invalid_contract")
        self.assertEqual(detail["repair_id"], "contract.workflow.light_lane_mode")
        self.assertEqual([v["pointer"] for v in detail["violations"]],
                         ["/bindings/workflow/light_lane/mode"])

    def test_a_project_without_a_contract_is_resolver_refused(self):
        (self.root / ".agents" / "project.json").unlink()
        self.assertEqual(self.refusal(record(), "resolver_refused")["code"], "not_onboarded")

    INVALID = (
        ("not json", ""),
        ('{"signals": {}, "signals": {}}', ""),
        ('{"signals": NaN, "paths": ["a"]}', ""),
        ([], ""),
        ({"signals": record()["signals"]}, "/paths"),
        ({**record(), "lane": "light"}, "/lane"),
        ({**record(), "signals": {k: v for k, v in record()["signals"].items()
                                  if k != "criteria_shape"}}, "/signals/criteria_shape"),
        ({**record(), "signals": {**record()["signals"],
                                  "risk_path": {"value": "no", "evidence": "x"}}},
         "/signals/risk_path"),
        (record(contract_change="maybe"), "/signals/contract_change/value"),
        ({**record(), "signals": {**record()["signals"],
                                  "contract_change": {"value": "no", "evidence": ""}}},
         "/signals/contract_change/evidence"),
        ({**record(), "signals": {**record()["signals"],
                                  "contract_change": {"value": "no", "evidence": "a\nb"}}},
         "/signals/contract_change/evidence"),
        ({**record(), "signals": {**record()["signals"],
                                  "contract_change": {"value": "no", "evidence": "x",
                                                      "note": "y"}}},
         "/signals/contract_change/note"),
        (record(paths=[]), "/paths"),
        (record(paths=["../outside.py"]), "/paths/0"),
        (record(paths=["ok.py", "/abs.py"]), "/paths/1"),
        (record(paths=[1]), "/paths/0"),
    )

    def test_an_invalid_record_is_invalid_input_with_its_first_pointer(self):
        for payload, pointer in self.INVALID:
            with self.subTest(pointer=pointer, payload=payload):
                detail = self.refusal(payload, "invalid_input")
                self.assertEqual(sorted(detail), ["message", "pointer"])
                self.assertEqual(detail["pointer"], pointer)
                self.assertTrue(detail["message"])

    def test_usage_errors_exit_2_with_empty_stdout(self):
        for argv in (["evaluate", "--input", "-"],
                     ["evaluate", "--repo-root", str(self.root), "--input", "record.json"],
                     ["--bogus"]):
            with self.subTest(argv=argv):
                code, out, _ = self.triage(record(), *argv)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest tests/test_lane_triage.py 2>&1 | tail -4`
Expected: FAILED — every case fails because `No module named agent_tools.lane_triage` (exit 1, not the asserted 0 or 2).

- [ ] **Step 3: Write the minimal implementation**

Create `python/agent_tools/lane_triage.py` with the names and invariants under **Interfaces** and **Invariants**. Module docstring: "`lane-triage`: the deterministic light-lane verdict over an owner's triage record (#279). It reads `bindings.workflow.light_lane` through `resolve_project.resolve`, prints `{hits, lane, mode}` and writes no file." Keep `main` a thin shell (agent-helpers rule 2):

```python
def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)   # argparse usage errors exit 2 by themselves
    text = sys.stdin.read()
    try:
        light_lane = light_lane_policy(args.repo_root)
        verdict = evaluate(load_record(text), light_lane)
    except TriageRefusal as refusal:
        sys.stderr.write(compact({"error": {"code": refusal.code, "detail": refusal.detail}}))
        return 2
    sys.stdout.write(compact(verdict))
    return 0
```

where `compact(value) = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"`. `build_parser()` has one required subcommand `evaluate` with `--repo-root` (required) and `--input` (required, `choices=["-"]`). `light_lane_policy` calls `resolve_project.resolve(repo_root)` (no `required`), maps `ContractError` to `resolver_refused` with the error document from **Invariants**, and returns `snapshot["bindings"]["workflow"].get("light_lane")` or raises `light_lane_unsupported` when that is `None`. `load_record` uses `json.loads(text, object_pairs_hook=reject_duplicate_keys, parse_constant=reject_nonfinite_literal)` and maps `ValueError` (which includes `json.JSONDecodeError`) to the `("", "not strict JSON: ...")` refusal. No exception other than `TriageRefusal` is caught.

Then wire the command:
- `lib/agent-tools.nix`: add `"lane-triage"` to `commands`, between `"diff-scope"` and `"launch-commit"`.
- `tests/test_agent_tools_launchers.py`: add `"lane-triage"` to `LAUNCHER_FLOOR` and change its comment's issue list to "#175, #179, #177, #249, #264 and #279".
- `justfile`: in `agent-workflow-tests`, add the line `    tests/test_lane_triage.py \` immediately before `    tests/test_launch_commit.py \`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest tests/test_lane_triage.py 2>&1 | tail -3`
Expected: `OK`, 0 failures.

Run: `grep -c '"lane-triage"' lib/agent-tools.nix tests/test_agent_tools_launchers.py; grep -c 'tests/test_lane_triage.py' justfile`
Expected: each file reports `1`.

Run: `PYTHONPATH="$PWD/python" python3 -m agent_tools.lane_triage --help >/dev/null; echo $?`
Expected: `0` (the installed-layout hostile test runs `--help` on every launcher).

Run (the command table reaches the build; the flake sees only files in the index, so stage first): `git add python/agent_tools/lane_triage.py tests/test_lane_triage.py lib/agent-tools.nix tests/test_agent_tools_launchers.py justfile && timeout 2400 just build 2>&1 | tail -3`
Expected: the build succeeds; a missing module would fail evaluation with `agent-tools: command lane-triage has no module agent_tools.lane_triage`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/lane_triage.py tests/test_lane_triage.py lib/agent-tools.nix tests/test_agent_tools_launchers.py justfile
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id <run-id> --worker-id <worker-id> -- -m "feat(lane-triage): read-only light-lane verdict command (#279)" -m "<trailers>"
```
Use the launch-commit identity and commit trailers from your dispatch brief.
