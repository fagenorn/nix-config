"""The lifecycle guard's land check, run from source against a stand-in forge.

A merge is judged by the `--land-bin` child (`forge-claim land permit`), which reads the land lock and
the leases of the stand-in `gh` from `FAKE_LAND_REFS`. Every expected text derives from `forge_land_lock`.

Run: just agent-workflow-tests
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_tools.claims import forge_land_lock as land_lock

from .guard_fake_gh import FAKE_GH_SCRIPT
from .guard_land_check import write_land_bin, write_land_gh
from .pre_push_world import FAKE_DERIVE

TIER = "integration"

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD_SOURCE = REPO_ROOT / "home/common/claude-code/lifecycle_guard.py"
HEAD = "d4d9acc0505c73305b3e0ced029db43100bc0e8a"
OTHER = "e" * 40
MERGE = f"gh pr merge 1 --repo fagenorn/nix-config --merge --match-head-commit {HEAD} --delete-branch"
UNPINNED = "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch"
LOCK = land_lock.lock_ref("main")
LIMIT = land_lock.LEASE_LAPSE - land_lock.MERGE_MARGIN
REFUSED = "lifecycle guard: unsafe merge: the PR does not hold the land lease: "
FAILED = "lifecycle guard: land check failed: "


def lease(branch, since, pr, beat):
    return land_lock.lease_prefix(branch) + f"{since}-{pr}-{beat}"


class GuardLandGateTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name).resolve()
        self.fake_gh = self.tmp / "fake-gh"
        self.fake_gh.write_text(f"#!{sys.executable}\n" + FAKE_GH_SCRIPT, encoding="utf-8")
        self.fake_gh.chmod(0o755)
        self.base_policy = self.tmp / "base-policy.json"
        self.base_policy.write_text(json.dumps({
            "authorized_owners": ["fagenorn", "acme"], "integration_bases": {"acme/widgets": "dev"},
            "git_bin": shutil.which("git"), "gh_bin": str(self.fake_gh), "jq_bin": shutil.which("jq")}),
            encoding="utf-8")
        self.policy = self.tmp / "policy.json"
        self.policy.write_text(json.dumps({"derived_repositories": {}, "derivation": None}), encoding="utf-8")
        self.derive = self.tmp / "fake-derive"
        self.derive.write_text(FAKE_DERIVE.format(python=sys.executable, rows=json.dumps({})), encoding="utf-8")
        self.derive.chmod(0o755)
        self.look = self.tmp / "look-bin"
        self.look.write_text(
            f"#!{sys.executable}\nimport os\nimport sys\n"
            f"os.environ['PYTHONPATH'] = {str(REPO_ROOT / 'python')!r}\n"
            "os.execv(sys.executable, [sys.executable, '-m', 'agent_tools.delivery.look_approval',"
            " 'judge', *sys.argv[1:]])\n", encoding="utf-8")
        self.look.chmod(0o755)
        self.land = write_land_bin(self.tmp, write_land_gh(self.tmp))
        self.repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        self.now = int(time.time())

    def make_repo(self, origin):
        root = Path(tempfile.mkdtemp(dir=self.tmp))
        for argv in (["git", "init", "--quiet"], ["git", "remote", "add", "origin", origin],
                     ["git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"]):
            subprocess.run(argv, cwd=root, check=True, capture_output=True)
        return root

    def guard(self, command, env=None, *flags, land=True, cwd=None):
        cwd = cwd or self.repo
        argv = [sys.executable, "-I", str(GUARD_SOURCE), "--base-policy", str(self.base_policy),
                "--policy", str(self.policy), "--derive-bin", str(self.derive), "--look-bin", str(self.look),
                "--gh-bin", str(self.fake_gh), *flags]
        if land:
            argv += ["--land-bin", str(self.land if land is True else land)]
        return subprocess.run(
            argv, input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}),
            cwd=cwd, env={**{k: v for k, v in os.environ.items() if not k.startswith("FAKE_")}, **(env or {})},
            text=True, capture_output=True, timeout=60)

    def refs(self, refs, **env):
        return {"FAKE_LAND_REFS": json.dumps(refs), "FAKE_LAND_NOW": str(self.now), **env}

    def pr(self, **over):
        pr = {"state": "OPEN", "baseRefName": "main", "headRefName": "issue-1-topic", "headRefOid": HEAD,
              "mergeStateStatus": "CLEAN", "url": "https://github.com/fagenorn/nix-config/pull/1",
              "statusCheckRollup": [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]}
        pr.update(over)
        return {k: v for k, v in pr.items() if v is not None}

    def stub(self, text, code):
        path = self.tmp / "stub-land"
        path.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.write({text!r})\nsys.exit({code})\n",
                        encoding="utf-8")
        path.chmod(0o755)
        return path

    def assertRefused(self, result, reason):
        self.assertEqual((2, REFUSED + reason + "\n"), (result.returncode, result.stderr))

    def test_a_merge_whose_lease_was_taken_over_is_refused_naming_the_holder(self):
        env = self.refs({LOCK: OTHER, lease("main", self.now - 5, 9, self.now - 5): OTHER})
        self.assertRefused(
            self.guard(MERGE, env),
            f"the land lock {LOCK} is at {OTHER[:7]}, not at the head {HEAD[:7]} of pull request 1; "
            "pull request 9 holds it under a lease")

    def test_a_repository_with_no_land_lock_merges_as_before(self):
        for command in (MERGE, UNPINNED):
            with self.subTest(command=command):
                result = self.guard(command)
                self.assertEqual((0, ""), (result.returncode, result.stderr))

    def test_an_unpinned_merge_under_a_lock_is_refused(self):
        env = self.refs({LOCK: HEAD})
        self.assertRefused(self.guard(UNPINNED, env),
                           f"the land lock {LOCK} is held, so the merge must carry --match-head-commit {HEAD}")
        self.assertEqual(0, self.guard(MERGE, env).returncode)

    def test_each_failed_condition_is_named(self):
        ahead = land_lock.QUEUE_SKEW + 1
        for refs, reason in (
            ({LOCK: HEAD, lease("main", self.now - 9, 1, self.now - 9): OTHER},
             f"the newest land lease of pull request 1 is at {OTHER[:7]}, not at its head {HEAD[:7]}"),
            ({LOCK: HEAD, lease("main", self.now - 900, 1, self.now - LIMIT): HEAD},
             f"the newest land lease of pull request 1 last beat {LIMIT} s ago, "
             f"and a merge needs a beat under {LIMIT} s"),
            ({LOCK: OTHER},
             f"the land lock {LOCK} is at {OTHER[:7]}, not at the head {HEAD[:7]} of pull request 1"),
            ({LOCK: HEAD, lease("main", self.now + ahead, 1, self.now): HEAD},
             f"no land lease of pull request 1 is dated at most {land_lock.QUEUE_SKEW} s ahead "
             "of the forge's clock"),
        ):
            with self.subTest(reason=reason):
                self.assertRefused(self.guard(MERGE, self.refs(refs)), reason)

    def test_a_holder_of_the_lock_with_or_without_a_fresh_lease_merges(self):
        for refs in ({LOCK: HEAD}, {LOCK: HEAD, lease("main", self.now - 9, 1, self.now): HEAD}):
            with self.subTest(refs=refs):
                result = self.guard(MERGE, self.refs(refs))
                self.assertEqual((0, ""), (result.returncode, result.stderr))

    def test_every_land_check_failure_refuses(self):
        refuse = json.dumps({"verdict": "refuse", "reason": "two\nlines"})
        for name, result in (
            ("forge failure", self.guard(MERGE, self.refs({LOCK: HEAD}, FAKE_LAND_MODE="fail"))),
            ("not a verdict", self.guard(MERGE, land=self.stub("ok", 0))),
            ("reason with a newline", self.guard(MERGE, land=self.stub(refuse, 3))),
        ):
            with self.subTest(name):
                self.assertEqual(2, result.returncode)
                self.assertTrue(result.stderr.startswith(FAILED), result.stderr)
        missing = self.guard(MERGE, land=self.tmp / "missing")
        self.assertEqual(2, missing.returncode)
        self.assertTrue(missing.stderr.startswith(FAILED + "could not start ("), missing.stderr)

    def test_a_hung_land_check_is_killed_with_its_gh(self):
        pidfile = self.tmp / "pid"
        result = self.guard(MERGE, self.refs({LOCK: HEAD}, FAKE_LAND_MODE="hang", FAKE_LAND_PIDFILE=str(pidfile)),
                            "--child-timeout-seconds", "1")
        self.assertEqual((2, "lifecycle guard: land check timed out\n"), (result.returncode, result.stderr))
        pid = int(pidfile.read_text(encoding="utf-8"))
        give_up = time.monotonic() + 5
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            if time.monotonic() > give_up:
                self.fail(f"the land check's gh {pid} outlived the verdict")
            time.sleep(0.1)

    def test_a_refusal_reason_at_the_bound_is_shown_and_one_longer_is_a_failure(self):
        whole = "x" * land_lock.REASON_MAX
        self.assertRefused(
            self.guard(MERGE, land=self.stub(json.dumps({"verdict": "refuse", "reason": whole}), 3)), whole)
        longer = self.guard(MERGE, land=self.stub(json.dumps({"verdict": "refuse", "reason": whole + "x"}), 3))
        self.assertEqual(2, longer.returncode)
        self.assertTrue(longer.stderr.startswith(FAILED), longer.stderr)

    def test_a_merge_without_a_land_bin_refuses(self):
        result = self.guard(MERGE, land=False)
        self.assertEqual((2, FAILED + "no --land-bin was given\n"), (result.returncode, result.stderr))

    def test_a_merge_refused_before_the_land_check_never_runs_it(self):
        env = {"FAKE_PR_JSON": json.dumps(self.pr(mergeStateStatus="BEHIND")), "FAKE_LAND_MODE": "fail"}
        result = self.guard(MERGE, env)
        self.assertEqual(
            (2, "lifecycle guard: unsafe merge: the PR is behind its base main; repair: sync the branch with "
                "main, push it and wait for its required checks before merging\n"),
            (result.returncode, result.stderr))

    def test_the_land_check_precedes_the_integration_base_exemption(self):
        repo = self.make_repo("git@github.com:acme/widgets.git")
        pr = self.pr(baseRefName="dev", headRefName="issue-42-topic",
                     url="https://github.com/acme/widgets/pull/3")
        dev = land_lock.lock_ref("dev")
        command = f"gh pr merge 3 --repo acme/widgets --merge --match-head-commit {HEAD} --delete-branch"
        env = {"FAKE_PR_JSON": json.dumps(pr), **self.refs({dev: OTHER})}
        self.assertRefused(
            self.guard(command, env, cwd=repo),
            f"the land lock {dev} is at {OTHER[:7]}, not at the head {HEAD[:7]} of pull request 3")

    def test_the_release_arm_reads_the_lock_of_its_head_branch(self):
        repo = self.make_repo("git@github.com:acme/widgets.git")
        pr = self.pr(baseRefName="main", headRefName="dev", url="https://github.com/acme/widgets/pull/5")
        command = f"gh pr merge 5 --repo acme/widgets --merge --match-head-commit {HEAD}"
        env = {"FAKE_PR_JSON": json.dumps(pr), "FAKE_PROTECTION_MODE": "nonzero"}
        dev = land_lock.lock_ref("dev")
        self.assertRefused(
            self.guard(command, {**env, **self.refs({dev: OTHER})}, cwd=repo),
            f"the land lock {dev} is at {OTHER[:7]}, not at the head {HEAD[:7]} of pull request 5")
        result = self.guard(command, {**env, **self.refs({LOCK: OTHER})}, cwd=repo)
        self.assertEqual((0, ""), (result.returncode, result.stderr))

    def test_an_unreadable_head_with_a_lock_is_refused(self):
        env = {"FAKE_PR_JSON": json.dumps(self.pr(headRefOid=None)), **self.refs({LOCK: OTHER})}
        self.assertRefused(
            self.guard(UNPINNED, env),
            f"the land lock {LOCK} is at {OTHER[:7]}, and the head of pull request 1 could not be read")


if __name__ == "__main__":
    unittest.main()
