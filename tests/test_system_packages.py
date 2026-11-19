"""The shared system package list as each host's configuration evaluates it (issue 1124).

Reads the host evaluations from `tests/host_readings.py`, which evaluates the flake from this
checkout's git tree.
Run: just agent-workflow-tests
"""
import unittest

from . import host_readings, test_verify_pending_units as units


class SystemPackagesTest(unittest.TestCase):
    # Darwin is read from a pure evaluation so that Linux CI can evaluate it (see test_console_units.DarwinAgent).
    HOSTS = ("anis-desktop", *units.DarwinHosts.HOSTS)

    @classmethod
    def setUpClass(cls):
        cls.names = {host: host_readings.read(host, "system-packages") for host in cls.HOSTS}

    def test_the_reading_sees_the_shared_package_list(self):
        for host, names in self.names.items():
            with self.subTest(host):
                self.assertIn("gh", names)
                self.assertIn("just", names)

    def test_no_host_installs_railway_system_wide(self):
        for host, names in self.names.items():
            with self.subTest(host):
                self.assertNotIn("railway", names, host)
