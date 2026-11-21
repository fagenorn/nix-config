"""The commands, standards and manifest each host installs come from the flake's platform package (issue 1439).

Reads the host evaluations from `tests/host_readings.py`, which evaluates the flake from this
checkout's git tree. All three hosts are read on every machine, the Linux CI job included: the
reading takes the entries from the definitions of `home.file`, so it forces no import-from-derivation
and the darwin hosts stay in a pure evaluation. `tests/test_host_readings.py` runs the same Nix text
against stub definitions, so a redirected, disabled, doubled or wrapped entry is shown to change the reading.
Run: just agent-workflow-tests
"""
import re
import unittest

from . import host_readings

PACKAGE = re.compile(r"^/nix/store/[0-9a-z]{32}-agent-platform$")


def linked(source, target):
    return {"source": source, "enable": True, "target": target, "recursive": False}


class PlatformPackageHostsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readings = {host: host_readings.read(host, "agent-platform") for host in host_readings.ALL_HOSTS}

    def test_every_host_is_read(self):
        self.assertEqual(sorted(self.readings), sorted(host_readings.ALL_HOSTS))

    def test_each_host_installs_every_command_from_the_package(self):
        for host, reading in self.readings.items():
            with self.subTest(host):
                self.assertRegex(reading["package"], PACKAGE)
                self.assertIn("resolve-project", reading["commands"])
                for command in reading["commands"]:
                    self.assertEqual(
                        reading["bin"][command],
                        linked(f'{reading["package"]}/bin/{command}', f".agents/bin/{command}"),
                        command,
                    )

    def test_each_host_installs_the_standards_directory_from_the_package(self):
        for host, reading in self.readings.items():
            with self.subTest(host):
                self.assertEqual(
                    reading["standards"],
                    linked(f'{reading["package"]}/share/agent-platform/standards', ".agents/standards"),
                )

    def test_each_host_installs_the_manifest_from_the_package(self):
        for host, reading in self.readings.items():
            with self.subTest(host):
                self.assertEqual(
                    reading["manifest"],
                    linked(
                        f'{reading["package"]}/share/agent-platform/platform-manifest.json',
                        ".agents/share/platform-manifest.json",
                    ),
                )

    def test_no_other_agent_command_is_installed(self):
        for host, reading in self.readings.items():
            with self.subTest(host):
                self.assertEqual(
                    sorted(reading["binEntries"]),
                    sorted([f".agents/bin/{c}" for c in reading["commands"]] + [".agents/bin/impeccable"]),
                )

    def test_the_darwin_hosts_share_one_package(self):
        self.assertEqual(
            self.readings["mbp"]["package"], self.readings["eleven-m5"]["package"])

    def test_linux_has_its_own_package(self):
        self.assertNotEqual(
            self.readings["anis-desktop"]["package"], self.readings["mbp"]["package"])

    def test_each_package_builds_from_its_systems_channel(self):
        for host, reading in self.readings.items():
            with self.subTest(host):
                self.assertEqual(reading["python"], reading["channelPython"])


if __name__ == "__main__":
    unittest.main()
