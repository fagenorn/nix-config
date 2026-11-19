"""The `_github-runner` home on every darwin host, as its configuration evaluates (issue 703).

macOS records the canonical /private/var path and nix-darwin compares homes literally, so a
host that configures /var/lib/github-runners is refused at switch time.
Reads the host evaluations from `tests/host_readings.py`, which evaluates the flake from this
checkout's git tree, so new files must be `git add`-ed first.
Run: just agent-workflow-tests
"""
import unittest

from . import host_readings

CANONICAL = "/private/var/lib/github-runners"


class RunnerHome(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Read from a pure evaluation: the required CI job runs on Linux, so no darwin build may be needed.
        cls.got = {host: host_readings.read(host, "runner-home") for host in ("eleven-m5", "mbp")}

    def test_every_darwin_host_uses_the_canonical_runner_home(self):
        for host in ("eleven-m5", "mbp"):
            with self.subTest(host=host):
                self.assertEqual(self.got[host], CANONICAL)


if __name__ == "__main__":
    unittest.main()
