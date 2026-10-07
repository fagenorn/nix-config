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

    def test_an_overflowing_number_in_the_contract_is_resolver_refused(self):
        """COR-002: `1e400` decodes to `inf`; `resolve-project resolve` refuses it."""
        path = self.root / ".agents" / "project.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        contract["bindings"]["deploy"]["config"] = {"threshold": 271828.5}
        text = json.dumps(contract, indent=2) + "\n"
        self.assertEqual(text.count("271828.5"), 1)
        path.write_text(text.replace("271828.5", "1e400"), encoding="utf-8")
        self.assertEqual(self.refusal(record(), "resolver_refused"),
                         {"code": "resolver_failure", "repair_id": "resolver.internal",
                          "violations": [{"message": "the resolver failed unexpectedly",
                                          "pointer": ""}]})

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
        (record(paths=["ok.py", "./tinytask/store.py"]), "/paths/1"),
        (record(paths=["tinytask//store.py"]), "/paths/0"),
        (record(paths=["tinytask/"]), "/paths/0"),
        (record(paths=["."]), "/paths/0"),
        (record(paths=["tinytask\\store.py"]), "/paths/0"),
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
