"""The `_github-runner` home on every darwin host, as its configuration evaluates (issue 703).

macOS records the canonical /private/var path and nix-darwin compares homes literally, so a
host that configures /var/lib/github-runners is refused at switch time.
Evaluates the flake from this checkout's git tree, so new files must be `git add`-ed first.
Run: just agent-workflow-tests
"""
import unittest

from .test_verify_pending_units import evaluate

APPLY = "c: u: c.users.users._github-runner.home"
CANONICAL = "/private/var/lib/github-runners"


class RunnerHome(unittest.TestCase):
    def test_every_darwin_host_uses_the_canonical_runner_home(self):
        for host in ("eleven-m5", "mbp"):
            with self.subTest(host=host):
                # pure: the required CI job runs on Linux, so no darwin build may be needed.
                self.assertEqual(evaluate(f"darwinConfigurations.{host}", APPLY, pure=True), CANONICAL)


if __name__ == "__main__":
    unittest.main()
