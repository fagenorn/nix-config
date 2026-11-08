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

    def test_an_existing_user_with_another_uid_is_refused(self):
        done = self.guard("_github-runner-jarbird", "534",
                          users=self.USERS + "_github-runner-jarbird 533\n")
        self.assertEqual(done.returncode, 1)
        self.assertIn("user _github-runner-jarbird has uid 533, not 534", done.stderr)

    def test_an_existing_group_with_another_gid_is_refused(self):
        done = self.guard("_github-runner-jarbird", "534",
                          users=self.USERS + "_github-runner-jarbird 534\n",
                          groups=self.GROUPS + "_github-runner-jarbird 533\n")
        self.assertEqual(done.returncode, 1)
        self.assertIn("group _github-runner-jarbird has gid 533, not 534", done.stderr)

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


JARBIRD_ACCOUNT = "_github-runner-jarbird"
JARBIRD_TOKENS = "/var/lib/github-runner-tokens-jarbird"

APPLY = """c: {
  runners = builtins.mapAttrs (n: r: {
    inherit (r) url tokenFile extraLabels ephemeral user group name enable;
    daemon = let s = c.launchd.daemons."github-runner-${n}".serviceConfig; in {
      inherit (s) UserName GroupName;
      SoftResourceLimits = s.SoftResourceLimits or null;
      HardResourceLimits = s.HardResourceLimits or null;
    };
  }) c.services.github-runners;
  account =
    let u = c.users.users."_github-runner-jarbird" or null; in
    if u == null then null else { inherit (u) uid gid home createHome; };
  accountGroup =
    let g = c.users.groups."_github-runner-jarbird" or null; in
    if g == null then null else { inherit (g) gid; };
  knownUsers = c.users.knownUsers;
  knownGroups = c.users.knownGroups;
  activation = c.system.activationScripts.launchd.text;
  checks = c.system.checks.text;
  trustedSettings = c.nix.settings.trusted-users or [ ];
  extraOptions = c.nix.extraOptions;
  postgres =
    if c.services ? postgresql then
      { inherit (c.services.postgresql) enable port; }
    else
      null;
}"""


def token_dir_line(group, directory):
    return re.compile(rf"/bin/install -d -m 0750 -o root -g {re.escape(group)} {re.escape(directory)}$", re.M)


class RunnersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = {host: config(host, APPLY) for host in HOSTS}

    def test_eleven_m5_has_one_repo_scoped_jarbird_runner(self):
        runners = self.got["eleven-m5"]["runners"]
        jarbird = [n for n, r in runners.items() if "elevenyellow" in r["url"]]
        self.assertEqual(jarbird, ["eleven-m5-jarbird"])
        runner = runners["eleven-m5-jarbird"]
        self.assertEqual(runner["url"], "https://github.com/elevenyellow/jarbird")
        self.assertEqual(runner["tokenFile"], f"{JARBIRD_TOKENS}/jarbird.token")
        self.assertEqual(runner["extraLabels"], ["nix", "eleven-m5", "jarbird"])
        self.assertEqual(runner["name"], "eleven-m5-jarbird")
        self.assertTrue(runner["enable"])
        self.assertFalse(runner["ephemeral"])
        self.assertEqual((runner["user"], runner["group"]), (JARBIRD_ACCOUNT, JARBIRD_ACCOUNT))
        self.assertEqual((runner["daemon"]["UserName"], runner["daemon"]["GroupName"]),
                         (JARBIRD_ACCOUNT, JARBIRD_ACCOUNT))

    def test_the_jarbird_account_is_declared_on_eleven_m5_only(self):
        got = self.got["eleven-m5"]
        self.assertEqual(got["account"], {"uid": 534, "gid": 534, "home": "/private/var/empty", "createHome": False})
        self.assertEqual(got["accountGroup"], {"gid": 534})
        self.assertIn(JARBIRD_ACCOUNT, got["knownUsers"])
        self.assertIn(JARBIRD_ACCOUNT, got["knownGroups"])
        mbp = self.got["mbp"]
        self.assertIsNone(mbp["account"])
        self.assertNotIn(JARBIRD_ACCOUNT, mbp["knownUsers"])

    def test_the_account_home_is_canonical_so_a_second_activation_accepts_it(self):
        # sysadminctl records the canonical /private path, and nix-darwin compares the
        # recorded home to this literal on every later activation, aborting on a mismatch.
        home = self.got["eleven-m5"]["account"]["home"]
        self.assertTrue(home.startswith("/private/"), home)

    def test_another_tenant_shares_no_user_group_or_token_dir_with_the_owner(self):
        runners = self.got["eleven-m5"]["runners"]
        tenants = [r for r in runners.values() if "/elevenyellow/" in r["url"]]
        owners = [r for r in runners.values() if "/fagenorn/" in r["url"]]
        self.assertTrue(tenants and owners)
        for tenant in tenants:
            for owner in owners:
                with self.subTest(tenant=tenant["name"], owner=owner["name"]):
                    self.assertNotEqual(tenant["daemon"]["UserName"], owner["daemon"]["UserName"])
                    self.assertNotIn(tenant["daemon"]["GroupName"],
                                     (owner["daemon"]["GroupName"], "_github-runner"))
                    self.assertNotEqual(os.path.dirname(tenant["tokenFile"]),
                                        os.path.dirname(owner["tokenFile"]))

    def test_the_existing_runners_are_unchanged_on_every_host(self):
        for host in HOSTS:
            runners = self.got[host]["runners"]
            for repo in FAGENORN:
                with self.subTest(host=host, repo=repo):
                    runner = runners[f"{host}-{repo}"]
                    self.assertEqual(runner["url"], f"https://github.com/fagenorn/{repo}")
                    self.assertEqual(runner["tokenFile"], f"{TOKENS}/{repo}.token")
                    self.assertEqual(runner["extraLabels"], ["nix", host])
                    self.assertTrue(runner["enable"])
                    self.assertEqual((runner["user"], runner["group"]), (None, None))
                    self.assertEqual(runner["daemon"]["UserName"], "_github-runner")

    def test_mbp_has_no_jarbird_runner(self):
        self.assertEqual(sorted(self.got["mbp"]["runners"]), [f"mbp-{repo}" for repo in FAGENORN])

    def test_eleven_m5_runs_exactly_the_four_runners(self):
        self.assertEqual(sorted(self.got["eleven-m5"]["runners"]),
                         sorted([f"eleven-m5-{repo}" for repo in FAGENORN] + ["eleven-m5-jarbird"]))

    def test_each_token_dir_is_created_for_its_own_group(self):
        for host in HOSTS:
            with self.subTest(host=host):
                self.assertRegex(self.got[host]["activation"], token_dir_line("_github-runner", TOKENS))
        self.assertRegex(self.got["eleven-m5"]["activation"], token_dir_line(JARBIRD_ACCOUNT, JARBIRD_TOKENS))
        self.assertNotIn(JARBIRD_TOKENS, self.got["mbp"]["activation"])

    def test_the_guard_runs_for_the_dedicated_account(self):
        call = re.compile(r"/bin/sh /nix/store/[0-9a-z]{32}-github-runner-account-guard\.sh "
                          rf"{JARBIRD_ACCOUNT} 534$", re.M)
        self.assertRegex(self.got["eleven-m5"]["checks"], call)
        self.assertNotIn("github-runner-account-guard", self.got["mbp"]["checks"])

    def test_no_runner_user_is_trusted(self):
        for host in HOSTS:
            with self.subTest(host=host):
                got = self.got[host]
                users = {r["daemon"]["UserName"] for r in got["runners"].values()}
                self.assertTrue(users)
                lines = [line for line in got["extraOptions"].splitlines()
                         if re.match(r"\s*(extra-)?trusted-users\s*=", line)]
                trusted = set(got["trustedSettings"])
                for line in lines:
                    trusted.update(line.split("=", 1)[1].split())
                self.assertEqual(users & trusted, set())

    def test_no_runner_daemon_sets_launchd_resource_limits(self):
        for host in HOSTS:
            for name, runner in self.got[host]["runners"].items():
                with self.subTest(host=host, runner=name):
                    self.assertIsNone(runner["daemon"]["SoftResourceLimits"])
                    self.assertIsNone(runner["daemon"]["HardResourceLimits"])

    def test_no_host_postgres_claims_the_devenv_port(self):
        postgres = self.got["eleven-m5"]["postgres"]
        if postgres is not None:
            self.assertFalse(postgres["enable"] and postgres["port"] == 5433, postgres)


def recipe_block():
    """The `register-runners` recipe: its comment, its header line and its indented body."""
    text = (ROOT / "justfile").read_text(encoding="utf-8")
    match = re.search(r"((?:^#[^\n]*\n|^\[[^\n]*\]\n)*)^register-runners ([^\n]*):\n((?:  [^\n]*\n)+)",
                      text, re.M)
    if match is None:
        raise AssertionError("no register-runners recipe in justfile")
    return match.group(1), match.group(2), match.group(3)


def recipe_script(host, local):
    """The recipe body as bash would run it for `host` from `local`: dedented, with
    `{{target_host}}` and `{{hostname}}` filled in."""
    _, header, body = recipe_block()
    if header != "target_host=hostname":
        raise AssertionError(f"unexpected recipe parameters: {header!r}")
    lines = [line[2:] for line in body.splitlines()]
    if lines[0] != "#!/usr/bin/env bash":
        raise AssertionError("the recipe is not a bash shebang recipe")
    script = "\n".join(lines).replace("{{target_host}}", host).replace("{{hostname}}", local)
    if "{{" in script:
        raise AssertionError("the recipe interpolates something the test does not fill in")
    return script + "\n"


def apply_expression():
    applies = re.findall(r"--apply '([^']*)'", recipe_block()[2])
    if len(applies) != 1:
        raise AssertionError(f"expected one --apply expression, found {len(applies)}")
    return applies[0]


def expected_triples(host):
    found = [(f"fagenorn/{repo}", f"{TOKENS}/{repo}.token", "_github-runner") for repo in FAGENORN]
    if host == "eleven-m5":
        found.append(("elevenyellow/jarbird", f"{JARBIRD_TOKENS}/jarbird.token", JARBIRD_ACCOUNT))
    return sorted(found)


class RegisterRunnersTest(unittest.TestCase):
    def run_recipe(self, host, local):
        """Run the recipe body for `host` as if on `local`, with stub gh, sudo and ssh; nix is the
        real one, in pure mode. The stub ssh runs the remote command as sshd would, joined with
        spaces under /bin/sh -c, with the same stdin, so the remote half really runs."""
        real_nix = shutil.which("nix")
        self.assertIsNotNone(real_nix, "nix is not on PATH")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            stubs, seen = tmp / "bin", tmp / "seen"
            stubs.mkdir()
            seen.mkdir()
            write_exe(stubs / "nix", f'#!/bin/sh\nexec "{real_nix}" {" ".join(repr(a) for a in NIX[1:3])} '
                                     '--option allow-import-from-derivation false "$@"\n')
            write_exe(stubs / "gh", f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{seen}/gh"\nprintf "tok:%s\\n" "$4"\n')
            # [-n] install -m 0440 -o root -g GROUP SRC DST: record the call, refuse a source that
            # is not a regular file (as install does), and keep what SRC held.
            write_exe(stubs / "sudo", f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{seen}/sudo"\n'
                                      '[ "$1" = -n ] && shift\n'
                                      '[ -f "$8" ] || { echo "install: not a regular file" >&2; exit 9; }\n'
                                      f'printf "%s\\n" "$8" >> "{seen}/staged"\n'
                                      f'cat "$8" > "{seen}/token-$(basename "$9")"\n')
            write_exe(stubs / "ssh", f'#!/bin/sh\nwhile [ "$1" = -o ]; do printf "%s\\n" "$2" >> "{seen}/ssh-opts"; '
                                     'shift 2; done\n'
                                     f'printf "%s\\n" "$1" >> "{seen}/ssh-host"\nshift\n'
                                     f'printf "%s\\n" "$*" >> "{seen}/ssh-command"\n'
                                     'exec /bin/sh -c "$*"\n')
            script = tmp / "register-runners.sh"
            script.write_text(recipe_script(host, local), encoding="utf-8")
            done = subprocess.run(["bash", str(script)], cwd=ROOT, capture_output=True, text=True,
                                  timeout=EVAL_TIMEOUT,
                                  env={**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}"})
            self.assertEqual(done.returncode, 0, done.stderr[-4000:])

            def lines(name):
                path = seen / name
                return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

            sudo = [line.split(" ") for line in lines("sudo")]
            tokens = {p.name[len("token-"):]: p.read_text(encoding="utf-8") for p in seen.glob("token-*")}
            left = [path for path in lines("staged") if Path(path).exists()]
            return {"gh": lines("gh"), "sudo": sudo, "tokens": tokens, "left": left,
                    "ssh_host": lines("ssh-host"), "ssh_opts": lines("ssh-opts"),
                    "ssh_command": lines("ssh-command")}

    def assert_tokens(self, host, seen, prefix):
        triples = expected_triples(host)
        self.assertEqual(sorted(seen["gh"]), sorted(
            f"api -X POST repos/{slug}/actions/runners/registration-token -q .token"
            for slug, _, _ in triples))
        width = len(prefix) + 7
        self.assertEqual(sorted((argv[:width], argv[width + 1]) for argv in seen["sudo"]), sorted(
            ([*prefix, "install", "-m", "0440", "-o", "root", "-g", group], file)
            for _, file, group in triples))
        for slug, file, _ in triples:
            self.assertEqual(seen["tokens"][Path(file).name],
                             f"tok:repos/{slug}/actions/runners/registration-token")
        self.assertEqual(seen["left"], [], "a staged token outlived the recipe")

    def test_the_local_host_installs_each_token_with_sudo(self):
        for host in HOSTS:
            with self.subTest(host=host):
                seen = self.run_recipe(host, host)
                self.assert_tokens(host, seen, [])
                self.assertEqual(seen["ssh_host"], [], "local mode must not ssh")

    def test_another_host_gets_its_tokens_over_ssh_with_noninteractive_sudo(self):
        for host, local in (("eleven-m5", "mbp"), ("mbp", "eleven-m5")):
            with self.subTest(host=host, local=local):
                seen = self.run_recipe(host, local)
                self.assert_tokens(host, seen, ["-n"])
                self.assertEqual(set(seen["ssh_host"]), {host})
                self.assertEqual(len(seen["ssh_host"]), len(expected_triples(host)))
                self.assertIn("BatchMode=yes", seen["ssh_opts"])
                for command in seen["ssh_command"]:
                    self.assertNotIn("tok:", command, "a token reached the remote command line")

    def test_the_expression_prints_one_triple_per_runner(self):
        for host in HOSTS:
            with self.subTest(host=host):
                out = nix("--raw", f"{ROOT}#darwinConfigurations.{host}.config.services.github-runners",
                          "--apply", apply_expression())
                self.assertEqual(sorted(tuple(t.split("=")) for t in out.split()), expected_triples(host))

    def test_the_recipe_names_no_owner_group_or_host(self):
        comment, _, body = recipe_block()
        rest = body.replace(apply_expression(), "")
        for literal in ("fagenorn", "_github-runner", "eleven-m5", "mbp"):
            with self.subTest(literal=literal):
                self.assertNotIn(literal, rest)
                self.assertNotIn(literal, comment)

    def test_the_recipe_keeps_its_token_hygiene(self):
        body = recipe_block()[2]
        for needle in ("set -euo pipefail", "umask 077", "tmp=$(mktemp)",
                       "trap 'rm -f \"$tmp\"' EXIT", "tr -d '\\n'", "BatchMode=yes", "sudo -n install"):
            self.assertIn(needle, body)


if __name__ == "__main__":
    unittest.main()
