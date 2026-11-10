"""Strict SemVer lives in agent_tools.system.semver, not in agent_platform."""

import unittest

from agent_tools.project_contract import agent_platform
from agent_tools.system import semver


class SemverTest(unittest.TestCase):
    def test_strict_versions_parse(self):
        self.assertEqual(semver.parse_semver("1.2.3"), (1, 2, 3))
        self.assertEqual(semver.parse_semver("0.0.0"), (0, 0, 0))
        self.assertEqual(semver.parse_semver("10.20.30"), (10, 20, 30))

    def test_loose_spellings_are_not_versions(self):
        for value in ("01.2.3", "1.02.3", "1.2", "1.2.3.4", "v1.2.3", "1.2.3-rc.1",
                      "1.2.3+b", 1, None, True):
            with self.subTest(value=value):
                self.assertIsNone(semver.parse_semver(value))

    def test_compare_orders_by_triple(self):
        self.assertEqual(semver.compare_semver("1.10.0", "1.9.9"), 1)
        self.assertEqual(semver.compare_semver("2.0.0", "2.0.0"), 0)
        self.assertEqual(semver.compare_semver("0.9.0", "1.0.0"), -1)
        with self.assertRaises(ValueError):
            semver.compare_semver("1.2", "1.2.3")

    def test_agent_platform_no_longer_owns_semver(self):
        for name in ("SEMVER_PATTERN", "parse_semver", "compare_semver"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(agent_platform, name))


if __name__ == "__main__":
    unittest.main()
