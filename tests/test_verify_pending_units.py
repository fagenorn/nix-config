"""The verify-pending schedule as each host's configuration evaluates it (issue 632).

Evaluates the flake from this checkout's git tree, so new files must be `git add`-ed first.
Run: just agent-workflow-tests
"""
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_TIMEOUT = 1200
LABEL = "org.nixos.verify-pending"
NIX = ["nix", "--extra-experimental-features", "nix-command flakes", "eval"]


def nix(*args):
    done = subprocess.run([*NIX, *args], cwd=ROOT, capture_output=True, text=True, timeout=EVAL_TIMEOUT)
    if done.returncode != 0:
        raise AssertionError(f"nix eval {' '.join(args)} failed:\n{done.stderr[-4000:]}")
    return done.stdout


def username():
    return nix("--raw", "--file", str(ROOT / "vars/default.nix"), "username")


def evaluate(output, apply):
    """`apply` is a Nix function of the host's `config` and the user's home-manager config `u`."""
    expression = f"c: let u = c.home-manager.users.{json.dumps(username())}; in ({apply}) c u"
    return json.loads(nix("--json", f"{ROOT}#{output}.config", "--apply", expression))


def check_command(case, command, host):
    words = command.split(" ")
    case.assertEqual(len(words), 2, command)
    case.assertRegex(words[0], r"^/nix/store/[0-9a-z]{32}-verify-pending-pass$")
    case.assertEqual(words[1], host)


def check_kick(case, kick):
    case.assertRegex(kick, r"^/nix/store/[0-9a-z]{32}-verify-pending-kick$")


class LinuxUnits(unittest.TestCase):
    HOST = "anis-desktop"

    @classmethod
    def setUpClass(cls):
        cls.got = evaluate(f"nixosConfigurations.{cls.HOST}", """c: u: {
          command = u.verifyPending.command;
          label = u.verifyPending.label;
          kickScript = u.verifyPending.kick;
          start = u.verifyPending.start;
          service = u.systemd.user.services.verify-pending;
          timer = u.systemd.user.timers.verify-pending;
          paths = builtins.attrNames u.systemd.user.paths;
          kick = u.home.activation.verifyPendingKick;
        }""")

    def test_the_command_carries_this_hosts_flake_hostname(self):
        check_command(self, self.got["command"], self.HOST)
        self.assertEqual(self.got["label"], LABEL)

    def test_the_service_is_a_oneshot_of_the_command_started_only_by_timer_and_kick(self):
        service = self.got["service"]
        # home-manager 25.11 normalizes ExecStart to a list and defaults Environment to [].
        self.assertEqual(service["Service"],
                         {"Type": "oneshot", "ExecStart": [self.got["command"]], "Environment": []})
        self.assertEqual(service.get("Install", {}).get("WantedBy", []), [])

    def test_the_timer_fires_every_fifteen_minutes(self):
        timer = self.got["timer"]
        self.assertEqual(timer["Timer"], {"OnBootSec": "2min", "OnUnitActiveSec": "15min", "Persistent": True})
        self.assertEqual(timer["Install"]["WantedBy"], ["timers.target"])

    def test_the_switch_trigger_is_the_activation_kick_not_a_path_unit(self):
        self.assertNotIn("verify-pending", self.got["paths"])
        check_kick(self, self.got["kickScript"])
        kick = self.got["kick"]
        self.assertIn("reloadSystemd", kick["after"])
        self.assertIn("writeBoundary", kick["after"])
        self.assertEqual(kick["data"].strip(), f"run {self.got['kickScript']} || true")
        self.assertIn("systemctl --user start --no-block verify-pending.service", self.got["start"])
        self.assertNotIn("launchctl", self.got["start"])


class DarwinHosts(unittest.TestCase):
    HOSTS = ("mbp", "eleven-m5")
    APPLY = """c: u: {
          command = u.verifyPending.command;
          label = u.verifyPending.label;
          kickScript = u.verifyPending.kick;
          start = u.verifyPending.start;
          homeKick = u.home.activation ? verifyPendingKick;
        }"""

    @classmethod
    def setUpClass(cls):
        cls.got = {host: evaluate(f"darwinConfigurations.{host}", cls.APPLY) for host in cls.HOSTS}

    def test_each_command_carries_its_own_flake_hostname(self):
        for host in self.HOSTS:
            with self.subTest(host=host):
                check_command(self, self.got[host]["command"], host)
                self.assertEqual(self.got[host]["label"], LABEL)

    def test_the_kick_starts_the_agent_without_killing_a_running_round(self):
        for host in self.HOSTS:
            with self.subTest(host=host):
                check_kick(self, self.got[host]["kickScript"])
                self.assertEqual(self.got[host]["start"], f"/bin/launchctl kickstart gui/$(id -u)/{LABEL}")
                self.assertIs(self.got[host]["homeKick"], False,
                              "on darwin the kick runs from nix-darwin postActivation, not home-manager")


if __name__ == "__main__":
    unittest.main()
