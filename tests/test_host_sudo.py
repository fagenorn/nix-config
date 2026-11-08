"""Who may run sudo without a password on each darwin host, as its configuration evaluates (issue 698).

Evaluates the flake from this checkout's git tree, so new files must be `git add`-ed first.
Run: just agent-workflow-tests
"""
import unittest

from .test_verify_pending_units import evaluate, username

APPLY = "c: u: c.security.sudo.extraConfig"


class HostSudo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # pure: the required CI job runs on Linux, so no darwin build may be needed.
        cls.got = {host: evaluate(f"darwinConfigurations.{host}", APPLY, pure=True) for host in ("eleven-m5", "mbp")}
        cls.user = username()

    def rules(self, host):
        return [line.strip() for line in self.got[host].splitlines() if "NOPASSWD" in line]

    def test_eleven_m5_lets_only_the_owner_sudo_without_a_password(self):
        self.assertEqual(self.rules("eleven-m5"), [f"{self.user} ALL=(ALL) NOPASSWD: ALL"])

    def test_mbp_keeps_a_password_or_touch_id_for_sudo(self):
        self.assertEqual(self.rules("mbp"), [])


if __name__ == "__main__":
    unittest.main()
