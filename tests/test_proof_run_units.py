"""The eleven-m5 daily proof run as the host configuration evaluates it.

Reads the host evaluation from `tests/host_readings.py`, which evaluates the flake from this
checkout's git tree, so new files must be `git add`-ed first.
Run: just agent-workflow-tests
"""
import plistlib
import unittest

from . import host_readings
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "integration"  # evaluates the host configuration

TAIL = ("daily --platform-repo fagenorn/nix-config --branch main "
        "--fixture fagenorn/engine-fixture --fixture-branch main")


class ElevenM5ProofRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = host_readings.read("eleven-m5", "proof-run")
        cls.owner = host_readings.username()

    def test_the_generated_plist_waits_for_the_store_and_runs_daily_at_six_as_the_owner(self):
        plist = plistlib.loads(self.got["plist"].encode())

        self.assertEqual(set(plist), {"Label", "ProgramArguments", "UserName", "StartCalendarInterval",
                                      "EnvironmentVariables", "StandardOutPath", "StandardErrorPath"})
        self.assertEqual(plist["ProgramArguments"],
                         ["/bin/sh", "-c", "/bin/wait4path /nix/store && exec " + self.got["command"]])
        self.assertRegex(self.got["command"], r"^/nix/store/[0-9a-z]{32}-\S+/bin/proof-run " + TAIL + "$")
        self.assertEqual(plist["Label"], "org.nixos.proof-run")
        self.assertEqual(plist["StartCalendarInterval"], [{"Hour": 6, "Minute": 0}])
        self.assertEqual(plist["UserName"], self.owner)
        self.assertEqual(plist["EnvironmentVariables"]["HOME"], f"/Users/{self.owner}")
        self.assertIn("/run/current-system/sw/bin", plist["EnvironmentVariables"]["PATH"].split(":"))
        log = f"/Users/{self.owner}/Library/Logs/proof-run.log"
        self.assertEqual((plist["StandardOutPath"], plist["StandardErrorPath"]), (log, log))


if __name__ == "__main__":
    unittest.main()
