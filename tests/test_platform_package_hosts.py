"""The commands, standards and manifest each host installs come from the flake's platform package (issue 1439).

Reads the host evaluations from `tests/host_readings.py`, which evaluates the flake from this
checkout's git tree.
On a host whose nix cannot build x86_64-linux, the anis-desktop cases skip and say so; CI's Agent
Workflow Tests runs them on Linux.
Run: just agent-workflow-tests
"""
import re
import unittest

from . import host_readings

PACKAGE = re.compile(r"^/nix/store/[0-9a-z]{32}-agent-platform$")


NO_LINUX_BUILDER = (
    "no x86_64-linux builder: evaluating anis-desktop builds x86_64-linux derivations; "
    "CI's Agent Workflow Tests runs these on Linux"
)


def linked(source, target):
    return {"source": source, "enable": True, "target": target, "recursive": False}


class PlatformPackageHostsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readings = {host: host_readings.read(host, "agent-platform") for host in host_readings.DARWIN_HOSTS}
        if host_readings.can_build("x86_64-linux"):
            cls.readings["anis-desktop"] = host_readings.read("anis-desktop", "agent-platform-linux")

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

    def test_the_darwin_hosts_share_one_package_and_linux_has_its_own(self):
        if "anis-desktop" not in self.readings:
            self.skipTest(NO_LINUX_BUILDER)
        packages = {host: reading["package"] for host, reading in self.readings.items()}
        self.assertEqual(packages["mbp"], packages["eleven-m5"])
        self.assertNotEqual(packages["mbp"], packages["anis-desktop"])

    def test_each_package_builds_from_its_systems_channel(self):
        for host, reading in self.readings.items():
            with self.subTest(host):
                self.assertEqual(reading["python"], reading["channelPython"])


if __name__ == "__main__":
    unittest.main()
