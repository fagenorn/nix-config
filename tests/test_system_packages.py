"""The shared system package list as each host's configuration evaluates it (issue 1124).

Evaluates the flake from this checkout's git tree.
Run: just agent-workflow-tests
"""
import unittest

from . import test_verify_pending_units as units


class SystemPackagesTest(unittest.TestCase):
    # Darwin is evaluated pure so that Linux CI can evaluate it (see test_console_units.DarwinAgent).
    HOSTS = (
        ("nixosConfigurations.anis-desktop", False),
        *((f"darwinConfigurations.{host}", True) for host in units.DarwinHosts.HOSTS),
    )
    APPLY = "c: u: map (p: p.pname or (builtins.parseDrvName p.name).name) c.environment.systemPackages"

    @classmethod
    def setUpClass(cls):
        cls.names = {output: units.evaluate(output, cls.APPLY, pure=pure) for output, pure in cls.HOSTS}

    def test_the_reading_sees_the_shared_package_list(self):
        for output, names in self.names.items():
            with self.subTest(output):
                self.assertIn("gh", names)
                self.assertIn("just", names)

    def test_no_host_installs_railway_system_wide(self):
        for output, names in self.names.items():
            with self.subTest(output):
                self.assertNotIn("railway", names, output)
