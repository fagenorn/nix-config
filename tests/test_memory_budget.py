"""The eleven-m5 memory budget and the declarations held to it.

Reads the host through tests/host_readings.py, so it runs on any machine; new files must be
`git add`-ed first.
Run: just agent-workflow-tests
"""
import json
import re
import unittest
from pathlib import Path

try:
    from . import host_readings
except ImportError:  # run directly: no parent package, and tests/ is sys.path[0]
    import host_readings

TIER = "integration"

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "hosts" / "darwin" / "eleven-m5"
DECLARATION = ROOT / "home" / "common" / "agent-skills" / "host-declarations" / "eleven-m5.json"
JETSAM = r"<key>JetsamProperties</key>\s*<dict>\s*<key>JetsamPriority</key>\s*<integer>(\d+)</integer>"


class MemoryBudgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = host_readings.read("eleven-m5", "memory-budget")
        cls.budget = cls.got["budget"]

    def text(self, name):
        return (HOST / name).read_text(encoding="utf-8")

    def test_the_budget_sums_under_the_host_memory_with_the_floor(self):
        b = self.budget
        others = (
            b["colimaGiB"] + b["colimaOverheadGiB"] + b["verifySlots"] * b["verifyRunGiB"]
            + b["ciRunners"] * b["ciJobGiB"] + b["macosGiB"]
        )
        self.assertEqual(b["totalGiB"], 256)
        self.assertLessEqual(others, b["othersBudgetGiB"])
        self.assertLessEqual(
            b["omlxCeilingGiB"] + b["omlxOverCeilingGiB"] + b["othersBudgetGiB"] + b["floorGiB"], b["totalGiB"]
        )

    def test_the_others_budget_is_what_the_model_and_floor_leave(self):
        b = self.budget
        self.assertEqual(b["othersBudgetGiB"], b["totalGiB"] - b["omlxCeilingGiB"] - b["omlxOverCeilingGiB"] - b["floorGiB"])
        self.assertEqual(b["othersBudgetGiB"], 46)
        self.assertEqual(b["floorGiB"], 16)

    def test_colima_starts_with_the_budgeted_memory(self):
        flags = self.got["colimaFlags"]
        self.assertEqual(
            flags, ["--vm-type=vz", "--vz-rosetta", "--cpus=8", "--memory=8", "--disk=200", "--activate=false"]
        )
        memory = [flag for flag in flags if flag.startswith("--memory=")]
        self.assertEqual(memory, [f"--memory={self.budget['colimaGiB']}"])
        docker = self.text("docker.nix")
        self.assertIn('"--memory=${toString budget.colimaGiB}"', docker)
        self.assertNotIn('"--memory=8"', docker)

    def test_omlx_reads_its_ceiling_from_the_budget(self):
        ceiling = self.got["omlxCeiling"]
        self.assertEqual(ceiling, self.budget["omlxCeilingGiB"])
        self.assertIs(type(ceiling), int)
        omlx = self.text("omlx.nix")
        self.assertEqual(omlx.count("memory_guard_custom_ceiling_gb"), 1)
        self.assertRegex(omlx, r"memory\.memory_guard_custom_ceiling_gb = budget\.omlxCeilingGiB;")

    def test_the_budget_counts_every_verify_slot(self):
        declared = json.loads(DECLARATION.read_text(encoding="utf-8"))["verify_slots"]
        self.assertEqual(self.budget["verifySlots"], declared)
        text = self.text("memory-budget.nix")
        self.assertIn("host-declarations/eleven-m5.json", text)
        self.assertNotRegex(text, r"verifySlots\s*=\s*\d")

    def test_the_budget_counts_every_ci_runner(self):
        self.assertEqual(self.budget["ciRunners"], len(self.got["runners"]))
        self.assertNotIn("ciRunners", self.text("memory-budget.nix"))
        self.assertRegex(
            self.text("default.nix"),
            r"ciRunners = builtins\.length \(builtins\.attrNames config\.services\.github-runners\);",
        )

    def test_omlx_carries_a_higher_jetsam_priority_than_the_other_daemons(self):
        found = re.search(JETSAM, self.got["omlxPlist"])
        self.assertIsNotNone(found)
        self.assertEqual(found.group(1), str(self.budget["omlxJetsamPriority"]))
        self.assertGreater(int(found.group(1)), 40)
        self.assertEqual(self.got["jetsamElsewhere"], [])

    def test_the_omlx_plist_keeps_its_launchd_job(self):
        plist = self.got["omlxPlist"]
        for needle in ("<string>org.nixos.omlx</string>", "<key>KeepAlive</key>", "/bin/wait4path /nix/store", "-omlx-serve"):
            with self.subTest(needle=needle):
                self.assertIn(needle, plist)

    def test_the_budget_bounds_fseventsd_inside_the_macos_share(self):
        self.assertEqual(self.budget["fseventsdLimitGiB"], 4)
        self.assertLess(self.budget["fseventsdLimitGiB"], self.budget["macosGiB"])
        self.assertEqual(self.budget["fseventsdRestartMinutes"], 60)


if __name__ == "__main__":
    unittest.main()
