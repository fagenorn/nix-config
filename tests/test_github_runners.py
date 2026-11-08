"""Self-hosted GitHub runners as each darwin host's configuration evaluates them (issue 680).

Evaluates the flake from this checkout's git tree, so new files must be `git add`-ed first.
Run: just agent-workflow-tests
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_TIMEOUT = 1200
HOSTS = ("mbp", "eleven-m5")
FAGENORN = ("arcwave", "argus", "nix-config")
TOKENS = "/var/lib/github-runner-tokens"
GUARD = ROOT / "hosts" / "common" / "github-runner-account-guard.sh"
# pure: no import-from-derivation, so this evaluates on the Linux CI job.
NIX = ["nix", "--extra-experimental-features", "nix-command flakes", "eval",
       "--option", "allow-import-from-derivation", "false"]


def nix(*args):
    done = subprocess.run([*NIX, *args], cwd=ROOT, capture_output=True, text=True, timeout=EVAL_TIMEOUT)
    if done.returncode != 0:
        raise AssertionError(f"nix eval {' '.join(args)} failed:\n{done.stderr[-4000:]}")
    return done.stdout


def config(host, apply):
    return json.loads(nix("--json", f"{ROOT}#darwinConfigurations.{host}.config", "--apply", apply))


def write_exe(path, text):
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


class AccountGuardTest(unittest.TestCase):
    USERS = "_github-runner 533\nanis 502\nselo 503\n"
    GROUPS = "_github-runner 533\ncom.apple.sharepoint.group.1 701\n"

    def guard(self, *args, users=USERS, groups=GROUPS, fail=False):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "users").write_text(users, encoding="utf-8")
            (tmp / "groups").write_text(groups, encoding="utf-8")
            write_exe(tmp / "dscl", (
                "#!/bin/sh\n"
                + ("exit 3\n" if fail else "")
                + f'case "$3" in /Users) cat "{tmp}/users";; /Groups) cat "{tmp}/groups";; *) exit 4;; esac\n'))
            return subprocess.run(["/bin/sh", str(GUARD), *args], capture_output=True, text=True,
                                  timeout=60, env={"PATH": "/usr/bin:/bin", "DSCL": str(tmp / "dscl")})

    def test_a_free_id_is_admitted(self):
        done = self.guard("_github-runner-jarbird", "534")
        self.assertEqual((done.returncode, done.stderr), (0, ""))

    def test_an_id_held_by_its_own_name_is_admitted(self):
        done = self.guard("_github-runner-jarbird", "534",
                          users=self.USERS + "_github-runner-jarbird 534\n",
                          groups=self.GROUPS + "_github-runner-jarbird 534\n")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_uid_held_by_another_user_is_refused(self):
        done = self.guard("_github-runner-jarbird", "503")
        self.assertEqual(done.returncode, 1)
        self.assertIn("uid 503 belongs to selo", done.stderr)

    def test_a_gid_held_by_another_group_is_refused(self):
        done = self.guard("_github-runner-jarbird", "701")
        self.assertEqual(done.returncode, 1)
        self.assertIn("gid 701 belongs to com.apple.sharepoint.group.1", done.stderr)

    def test_an_id_is_not_matched_as_a_prefix(self):
        self.assertEqual(self.guard("_github-runner-jarbird", "53").returncode, 0)

    def test_a_failing_dscl_is_not_read_as_free(self):
        self.assertEqual(self.guard("_github-runner-jarbird", "534", fail=True).returncode, 2)

    def test_bad_usage_exits_2(self):
        for args in ((), ("_github-runner-jarbird",), ("_github-runner-jarbird", "5x4")):
            with self.subTest(args=args):
                self.assertEqual(self.guard(*args).returncode, 2)

    def test_the_guard_is_committed_executable(self):
        mode = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s",
                               "hosts/common/github-runner-account-guard.sh"],
                              capture_output=True, text=True, check=True).stdout.split(" ")[0]
        self.assertEqual(mode, "100755")


if __name__ == "__main__":
    unittest.main()
