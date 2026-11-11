"""The darwin zsh fragment that puts the Nix profile dirs before /usr/bin (issue 810, D4).

macOS path_helper can leave /usr/bin and /bin ahead of the Nix profile dirs, and every child
shell inherits that PATH, so agent shells found Xcode's python3 and bash 3.2 first. The fragment
data/zshrc/darwin/01-nix-path-order moves the profile dirs that sit after the first base system
dir to just before it, adds nothing and leaves every other element in its order.

The fragment is run by a real zsh; the wiring test checks that each darwin host's generated
zshrc contains it.
Run: just agent-workflow-tests
"""
import shutil
import subprocess
import unittest
from pathlib import Path

from . import test_verify_pending_units as units

ROOT = Path(__file__).resolve().parents[1]
FRAGMENT = ROOT / "data/zshrc/darwin/01-nix-path-order"
HOME = "/home/tester"
USER = "tester"

POLLUTED = [
    "/nix/store/aaaa-procps/bin", "/home/tester/.nix-profile/bin",
    "/nix/var/nix/profiles/default/bin", "/usr/local/bin", "/System/Cryptexes/App/usr/bin",
    "/usr/bin", "/bin", "/usr/sbin", "/sbin", "/Library/Apple/usr/bin",
    "/home/tester/.agents/bin", "/etc/profiles/per-user/tester/bin",
    "/run/current-system/sw/bin", "/home/tester/.orbstack/bin",
]
FIXED = [
    "/nix/store/aaaa-procps/bin", "/home/tester/.nix-profile/bin",
    "/nix/var/nix/profiles/default/bin", "/usr/local/bin", "/System/Cryptexes/App/usr/bin",
    "/etc/profiles/per-user/tester/bin", "/run/current-system/sw/bin",
    "/usr/bin", "/bin", "/usr/sbin", "/sbin", "/Library/Apple/usr/bin",
    "/home/tester/.agents/bin", "/home/tester/.orbstack/bin",
]

_ZSH = None


def zsh_binary():
    global _ZSH
    if _ZSH is None:
        found = shutil.which("zsh")
        if found is None:
            built = subprocess.run(
                ["nix", "--extra-experimental-features", "nix-command flakes", "build", "--no-link",
                 "--print-out-paths", "--inputs-from", str(ROOT), "nixpkgs#zsh"],
                capture_output=True, text=True, timeout=1200, check=True)
            for line in built.stdout.split():
                if (Path(line) / "bin/zsh").exists():
                    found = f"{line}/bin/zsh"
                    break
        assert found is not None, "no zsh available"
        _ZSH = found
    return _ZSH


def reorder(entries, times=1):
    assert FRAGMENT.is_file(), f"{FRAGMENT} is missing"
    # The fixture is assigned to PATH inside -c, not through the environment: zsh -f still reads
    # /etc/zshenv, which on a nix-darwin host rewrites PATH.
    done = subprocess.run(
        [zsh_binary(), "-f", "-c",
         'PATH=$3; for _ in {1..$2}; do source "$1" || exit 3; done; print -rl -- $path',
         "zsh", str(FRAGMENT), str(times), ":".join(entries)],
        env={"PATH": "/usr/bin:/bin", "HOME": HOME, "USER": USER},
        capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stderr == "", done.stderr
    return done.stdout.splitlines()


class FragmentReorders(unittest.TestCase):
    def test_profiles_after_usr_bin_move_just_before_it(self):
        self.assertEqual(reorder(POLLUTED), FIXED)

    def test_nix_darwin_order_with_brew_prefix_is_unchanged(self):
        good = ["/usr/local/bin", "/usr/local/sbin", "/home/tester/.agents/bin",
                "/home/tester/.nix-profile/bin", "/etc/profiles/per-user/tester/bin",
                "/run/current-system/sw/bin", "/nix/var/nix/profiles/default/bin",
                "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
        self.assertEqual(reorder(good), good)

    def test_profile_dirs_keep_nix_darwin_order(self):
        self.assertEqual(
            reorder(["/usr/bin", "/run/current-system/sw/bin", "/etc/profiles/per-user/tester/bin"]),
            ["/etc/profiles/per-user/tester/bin", "/run/current-system/sw/bin", "/usr/bin"])

    def test_absent_profile_dirs_are_not_added(self):
        self.assertEqual(
            reorder(["/usr/bin", "/bin", "/etc/profiles/per-user/tester/bin"]),
            ["/etc/profiles/per-user/tester/bin", "/usr/bin", "/bin"])

    def test_the_first_base_dir_is_the_anchor(self):
        self.assertEqual(
            reorder(["/sbin", "/usr/bin", "/etc/profiles/per-user/tester/bin"]),
            ["/etc/profiles/per-user/tester/bin", "/sbin", "/usr/bin"])

    def test_no_base_system_dir_leaves_path_unchanged(self):
        entries = ["/nix/store/bbbb-x/bin", "/opt/tool/bin", "/etc/profiles/per-user/tester/bin"]
        self.assertEqual(reorder(entries), entries)

    def test_sourcing_twice_is_idempotent(self):
        self.assertEqual(reorder(POLLUTED, times=2), FIXED)

    def test_other_users_profiles_are_not_moved(self):
        entries = ["/usr/bin", "/etc/profiles/per-user/someone-else/bin"]
        self.assertEqual(reorder(entries), entries)


class DarwinHostsLoadTheFragment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.init = {host: units.evaluate(
            f"darwinConfigurations.{host}", "c: u: { init = u.programs.zsh.initContent; }",
            pure=True)["init"] for host in units.DarwinHosts.HOSTS}

    def test_each_darwin_host_zshrc_contains_the_fragment(self):
        text = FRAGMENT.read_text()
        for host in units.DarwinHosts.HOSTS:
            with self.subTest(host=host):
                self.assertIn(text, self.init[host])


if __name__ == "__main__":
    unittest.main()
