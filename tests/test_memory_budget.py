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

from agent_tools.hosts import host_alerts

TIER = "integration"

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "hosts" / "darwin" / "eleven-m5"
DECLARATION = ROOT / "home" / "common" / "agent-skills" / "host-declarations" / "eleven-m5.json"
GUIDE = HOST / "README.md"
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


class WatcherDeclarationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = host_readings.read("eleven-m5", "memory-budget")
        cls.budget = cls.got["budget"]
        cls.watch = cls.got["watch"]
        cls.trim = cls.got["trim"]

    def test_the_watcher_samples_every_minute_as_the_owner(self):
        owner = self.got["owner"]
        self.assertEqual(self.watch["UserName"], owner)
        self.assertEqual(self.watch["StartInterval"], 60)
        self.assertIs(self.watch["RunAtLoad"], True)
        self.assertIn(self.watch["KeepAlive"], (None, False))
        self.assertEqual(self.watch["home"], f"/Users/{owner}")
        self.assertRegex(self.watch["command"], r"^/nix/store/[0-9a-z]{32}-agent-platform/bin/omlx-memory-watch sample ")

    def test_the_watcher_uses_the_budgeted_floor_priority_and_record(self):
        command, budget = self.watch["command"], self.budget
        owner = self.got["owner"]
        for needle in (
            f"--floor-gib {budget['floorGiB']} ",
            f"--others-budget-gib {budget['othersBudgetGiB']} ",
            f"--omlx-jetsam-priority {budget['omlxJetsamPriority']} ",
            f"--state-dir /Users/{owner}/.omlx/memory ",
            "--host eleven-m5 ",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, command)
        self.assertTrue(command.endswith("--fseventsd-record /var/db/memory-watch/fseventsd.json"))

    def test_the_watcher_leaves_the_alert_settings_to_the_shared_module(self):
        for needle in ("--alert-settings", "--alert-log", "--telegram-api", "telegram.json", "sops", "--gh", "--repo"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, self.watch["command"])

    def test_no_sops_secret_is_added_for_alerts(self):
        names = self.got["sopsSecrets"]
        self.assertIn("hf_token", names)
        for name in names:
            with self.subTest(name=name):
                self.assertNotIn("telegram", name)
                self.assertNotIn("alert", name)

    def test_the_fseventsd_trim_runs_as_root_with_the_budgeted_limit(self):
        command, budget = self.trim["command"], self.budget
        self.assertIsNone(self.trim["UserName"])
        self.assertEqual(self.trim["StartInterval"], 60)
        self.assertIn(self.trim["KeepAlive"], (None, False))
        self.assertRegex(command, r"-agent-platform/bin/omlx-memory-watch fseventsd --record /var/db/memory-watch/fseventsd\.json ")
        self.assertIn(f"--limit-gib {budget['fseventsdLimitGiB']} ", command)
        self.assertIn(f"--min-restart-minutes {budget['fseventsdRestartMinutes']}", command)


class GuideTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = host_readings.read("eleven-m5", "memory-budget")
        cls.guide = GUIDE.read_text(encoding="utf-8")
        cls.section = cls.between(cls.guide, "## Memory budget", "\n## ")
        cls.alerts = cls.between(cls.section, "### Alerts", "\n### ")
        cls.restarts = cls.between(cls.guide, "## What else an activation restarts", "\n## ")

    @staticmethod
    def between(text, start, end):
        begin = text.find(start)
        if begin < 0:
            return ""
        finish = text.find(end, begin + len(start))
        return text[begin:] if finish < 0 else text[begin:finish]

    def test_the_guide_tables_every_budget_member(self):
        self.assertTrue(self.section, "the guide has no `## Memory budget` section")
        for key in self.got["budget"]:
            with self.subTest(key=key):
                self.assertIn(f"`{key}`", self.section)

    def test_the_guide_says_what_to_do_for_a_new_workload(self):
        for needle in ("### When you add a workload", "memory-budget.nix", "tests/test_memory_budget.py", "memory-peaks.jsonl"):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.section)

    def test_the_guide_marks_the_unmeasured_allowances_provisional(self):
        for key in ("verifyRunGiB", "ciJobGiB", "macosGiB"):
            with self.subTest(key=key):
                lines = [line for line in self.section.splitlines() if line.startswith(f"| `{key}` |")]
                self.assertTrue(lines)
                for line in lines:
                    self.assertIn("provisional", line)
        for needle in ("peak_others_gib", "phys_footprint"):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.section)

    def test_the_guide_names_the_alert_settings_file(self):
        self.assertTrue(self.alerts, "the guide has no `### Alerts` subsection")
        for needle in (
            f"~/{host_alerts.RELATIVE_SETTINGS}", f"~/{host_alerts.RELATIVE_LOG}", "0600", "enabled", "bot_token",
            "chat_id", "console",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.alerts)
        for needle in ("sops", "gh issue"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, self.alerts)

    def test_the_guide_states_what_makes_fseventsd_grow(self):
        for needle in (
            "### What makes fseventsd grow", "JetsamEvent-2026-11-20-002944.ips", "51.53 GiB", "5210544", "node_modules",
            "exclusion", "fseventsd-trim",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.section)

    def test_the_guide_lists_the_new_daemons_among_restarts(self):
        self.assertTrue(self.restarts)
        for needle in ("omlx-memory-watch", "fseventsd-trim"):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.restarts)


if __name__ == "__main__":
    unittest.main()
