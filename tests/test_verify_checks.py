"""`agent_tools.verify_checks`: the committed verify checks of issue 638."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools import forge_markers, verify_checks
from agent_tools.verify_checks import required_checks, self_hosted_runner

from .pre_push_world import PrePushWorld

ROOT = Path(__file__).resolve().parents[1]
CHECKS = "home/common/verify-pending/checks"


def run_from_root(argv, env_extra=None):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "python"), **(env_extra or {})}
    return subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)


def committed_mode(path):
    return subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", path],
                          capture_output=True, text=True, check=True).stdout.split(" ")[0]


SINCE = datetime(2026, 11, 6, 17, 37, 11, tzinfo=timezone.utc)
SEARCH = ("search/issues?q=repo%3Aelevenyellow%2Fnodocom%20is%3Apr%20is%3Amerged%20base%3Adev"
          "%20merged%3A%3E2026-11-06T17%3A37%3A11Z&sort=created&order=asc&per_page=100")
SHA = "a" * 40
RUNS = f"repos/elevenyellow/nodocom/commits/{SHA}/check-runs?per_page=100"
STATUSES = f"repos/elevenyellow/nodocom/commits/{SHA}/statuses?per_page=100"
PROTECTION = "repos/elevenyellow/nodocom/branches/dev/protection/required_status_checks"


def forge(gets, pages):
    """Patch both forge reads; any read not listed fails the test."""
    def api_get(path, allow=()):
        if path not in gets:
            raise AssertionError(f"unexpected read {path}")
        return gets[path]

    def api_pages(path):
        if path not in pages:
            raise AssertionError(f"unexpected paginated read {path}")
        return pages[path]
    return (mock.patch.object(forge_markers, "api_get", side_effect=api_get),
            mock.patch.object(forge_markers, "api_pages", side_effect=api_pages))


def search_page(numbers, total=None, incomplete=False):
    return {"total_count": len(numbers) if total is None else total,
            "incomplete_results": incomplete, "items": [{"number": n} for n in numbers]}


def pull(merged, sha=SHA):
    return {"merged_at": merged, "head": {"sha": sha}}


def world(check_runs, statuses=(), required=("lint",), merged="2026-11-07T10:00:00Z"):
    gets = {
        "repos/elevenyellow/nodocom/pulls/2610": pull(merged),
        PROTECTION: {"checks": [{"context": c} for c in required], "contexts": list(required)},
    }
    pages = {
        SEARCH: [search_page([2610])],
        RUNS: [{"total_count": len(check_runs), "check_runs": list(check_runs)}],
        STATUSES: [list(statuses)],
    }
    return gets, pages


def run(name, conclusion="success", completed="2026-11-07T09:50:00Z", status="completed",
        app_id=None):
    found = {"name": name, "status": status, "conclusion": conclusion, "completed_at": completed}
    if app_id is not None:
        found["app"] = {"id": app_id}
    return found


class RequiredChecksTest(unittest.TestCase):
    def check(self, gets, pages):
        get_patch, pages_patch = forge(gets, pages)
        with get_patch, pages_patch:
            return required_checks("elevenyellow/nodocom", "dev", SINCE)

    def test_required_check_passed_before_merge_is_met(self):
        code, report = self.check(*world([run("lint")]))
        self.assertEqual((code, report["pr"], report["missing"]), (0, 2610, []))

    def test_check_completed_after_merge_is_not_met(self):
        code, report = self.check(*world([run("lint", completed="2026-11-07T10:05:00Z")]))
        self.assertEqual((code, report["missing"]), (1, ["lint"]))

    def test_failed_check_is_not_met(self):
        self.assertEqual(self.check(*world([run("lint", conclusion="failure")]))[0], 1)

    def test_commit_status_counts(self):
        statuses = [{"context": "lint", "state": "success", "updated_at": "2026-11-07T09:00:00Z"}]
        self.assertEqual(self.check(*world([], statuses))[0], 0)

    def test_a_success_status_replaced_by_a_later_failure_is_not_met(self):
        statuses = [{"context": "lint", "state": "failure", "updated_at": "2026-11-07T09:30:00Z"},
                    {"context": "lint", "state": "success", "updated_at": "2026-11-07T09:00:00Z"}]
        self.assertEqual(self.check(*world([], statuses))[0], 1)

    def test_a_check_from_another_app_than_the_required_one_is_not_met(self):
        gets, pages = world([run("lint", app_id=999)])
        gets[PROTECTION] = {"checks": [{"context": "lint", "app_id": 15368}], "contexts": ["lint"]}
        code, report = self.check(gets, pages)
        self.assertEqual((code, report["missing"]), (1, ["lint"]))

    def test_a_check_from_the_required_app_is_met(self):
        gets, pages = world([run("lint", app_id=999), run("lint", app_id=15368)])
        gets[PROTECTION] = {"checks": [{"context": "lint", "app_id": 15368}], "contexts": ["lint"]}
        self.assertEqual(self.check(gets, pages)[0], 0)

    def test_a_check_run_without_an_app_does_not_meet_a_bound_requirement(self):
        gets, pages = world([run("lint")])
        gets[PROTECTION] = {"checks": [{"context": "lint", "app_id": 15368}]}
        self.assertEqual(self.check(gets, pages)[0], 1)

    def test_a_commit_status_does_not_meet_a_bound_requirement(self):
        statuses = [{"context": "lint", "state": "success", "updated_at": "2026-11-07T09:00:00Z"}]
        gets, pages = world([], statuses)
        gets[PROTECTION] = {"checks": [{"context": "lint", "app_id": 15368}]}
        self.assertEqual(self.check(gets, pages)[0], 1)

    def test_an_unbound_requirement_accepts_any_app(self):
        for entry in ({"context": "lint", "app_id": None}, {"context": "lint", "app_id": -1}):
            gets, pages = world([run("lint", app_id=999)])
            gets[PROTECTION] = {"checks": [entry], "contexts": ["lint"]}
            self.assertEqual(self.check(gets, pages)[0], 0, entry)

    def test_the_legacy_contexts_list_does_not_loosen_a_bound_requirement(self):
        gets, pages = world([run("lint", app_id=999)])
        gets[PROTECTION] = {"checks": [{"context": "lint", "app_id": 15368}],
                            "contexts": ["lint"]}
        self.assertEqual(self.check(gets, pages)[0], 1)

    def test_each_app_bound_to_the_same_context_must_have_passed(self):
        gets, pages = world([run("lint", app_id=1)])
        gets[PROTECTION] = {"checks": [{"context": "lint", "app_id": 1},
                                       {"context": "lint", "app_id": 2}]}
        self.assertEqual(self.check(gets, pages)[0], 1)
        gets, pages = world([run("lint", app_id=1), run("lint", app_id=2)])
        gets[PROTECTION] = {"checks": [{"context": "lint", "app_id": 1},
                                       {"context": "lint", "app_id": 2}]}
        self.assertEqual(self.check(gets, pages)[0], 0)

    def test_a_malformed_app_id_is_refused(self):
        gets, pages = world([run("lint")])
        gets[PROTECTION] = {"checks": [{"context": "lint", "app_id": "15368"}]}
        with self.assertRaises(forge_markers.ForgeError):
            self.check(gets, pages)

    def test_no_required_checks_is_not_met(self):
        self.assertEqual(self.check(*world([run("lint")], required=()))[0], 1)

    def test_no_merged_pull_request_is_not_yet(self):
        code, report = self.check({}, {SEARCH: [search_page([])]})
        self.assertEqual((code, report["pr"]), (75, None))

    def test_the_earliest_merge_on_a_later_page_is_the_one_judged(self):
        gets, pages = world([run("lint")])
        later = "b" * 40
        gets["repos/elevenyellow/nodocom/pulls/2600"] = pull("2026-11-08T10:00:00Z", later)
        gets["repos/elevenyellow/nodocom/pulls/2610"] = pull("2026-11-07T10:00:00Z")
        pages[SEARCH] = [search_page([2600], total=2), search_page([2610], total=2)]
        code, report = self.check(gets, pages)
        self.assertEqual((code, report["pr"], report["merged_at"]), (0, 2610, "2026-11-07T10:00:00Z"))

    def test_a_merge_at_or_before_the_since_instant_is_not_judged(self):
        gets, pages = world([run("lint")], merged="2026-11-06T17:37:11Z")
        code, report = self.check(gets, pages)
        self.assertEqual((code, report["pr"]), (75, None))

    def test_a_success_status_after_the_merge_is_not_met(self):
        statuses = [{"context": "lint", "state": "success", "updated_at": "2026-11-07T10:30:00Z"}]
        self.assertEqual(self.check(*world([], statuses))[0], 1)

    def test_a_status_page_that_is_not_a_list_is_refused(self):
        gets, pages = world([run("lint")])
        pages[STATUSES] = [{"message": "nope"}]
        with self.assertRaises(forge_markers.ForgeError):
            self.check(gets, pages)

    def test_an_incomplete_search_is_refused(self):
        gets, pages = world([run("lint")])
        pages[SEARCH] = [search_page([2610], incomplete=True)]
        with self.assertRaises(forge_markers.ForgeError) as raised:
            self.check(gets, pages)
        self.assertEqual(raised.exception.code, "payload_invalid")

    def test_a_truncated_search_is_refused(self):
        gets, pages = world([run("lint")])
        pages[SEARCH] = [search_page([2610], total=1500)]
        with self.assertRaises(forge_markers.ForgeError):
            self.check(gets, pages)

    def test_check_runs_on_a_second_page_count_and_a_short_listing_is_refused(self):
        gets, pages = world([])
        pages[RUNS] = [{"total_count": 101, "check_runs": [run(f"other-{i}") for i in range(100)]},
                       {"total_count": 101, "check_runs": [run("lint")]}]
        self.assertEqual(self.check(gets, pages)[0], 0)
        pages[RUNS] = [{"total_count": 101, "check_runs": [run(f"other-{i}") for i in range(100)]}]
        with self.assertRaises(forge_markers.ForgeError):
            self.check(gets, pages)

    def test_forge_error_propagates(self):
        with mock.patch.object(forge_markers, "api_pages",
                               side_effect=forge_markers.ForgeError("gh_failed", "boom")):
            with self.assertRaises(forge_markers.ForgeError):
                required_checks("elevenyellow/nodocom", "dev", SINCE)


class RequiredChecksCommandTest(unittest.TestCase):
    def test_wrapper_maps_a_forge_error_to_exit_2(self):
        # PATH holds only python3, so the wrapper finds its interpreter and gh is missing.
        with tempfile.TemporaryDirectory() as tmp:
            os.symlink(sys.executable, Path(tmp) / "python3")
            done = run_from_root(["/bin/sh", str(ROOT / CHECKS / "required-checks"),
                                  "--repo", "elevenyellow/nodocom", "--base", "dev",
                                  "--since", "2026-11-06T17:37:11Z"], {"PATH": tmp})
        self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
        self.assertIn("forge_error", done.stderr)

    def test_bad_repo_is_a_usage_error(self):
        done = run_from_root([sys.executable, "-m", "agent_tools.verify_checks", "required-checks",
                              "--repo", "nodocom", "--base", "dev", "--since", "2026-11-06T17:37:11Z"])
        self.assertEqual(done.returncode, 2)

    def test_bad_repo_never_reaches_the_forge(self):
        with mock.patch.object(verify_checks, "required_checks",
                               side_effect=AssertionError("reached the forge")):
            with self.assertRaises(SystemExit) as raised:
                verify_checks.main(["required-checks", "--repo", "nodocom", "--base", "dev",
                                    "--since", "2026-11-06T17:37:11Z"])
        self.assertEqual(raised.exception.code, 2)

    def test_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/required-checks"), "100755")


class PlatformStatusWrapperTest(unittest.TestCase):
    def test_runs_the_installed_platform_status_and_passes_it_through(self):
        with tempfile.TemporaryDirectory() as home:
            bin_dir = Path(home) / ".agents" / "bin"
            bin_dir.mkdir(parents=True)
            fake = bin_dir / "resolve-project"
            fake.write_text('#!/bin/sh\nprintf \'{"argv": "%s", "platform": {"deprecations": [1]}}\\n\' "$*"\n'
                            "exit 3\n")
            fake.chmod(0o755)
            done = run_from_root([str(ROOT / CHECKS / "platform-status")], {"HOME": home})
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertEqual(json.loads(done.stdout)["argv"], "platform-status")

    def test_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/platform-status"), "100755")


class ManagedPrePushHookTest(unittest.TestCase):
    SLUG = "fagenorn/pre-push-hook-fixture"

    def setUp(self):
        self.world = PrePushWorld(self)
        managed = self.world.tmp / "abc-agent-git-hooks"
        self.world.hooks.rename(managed)
        self.world.hooks = managed
        self.set_user_config(managed)

    def set_user_config(self, hooks, extra=""):
        Path(self.world.env["GIT_CONFIG_GLOBAL"]).write_text(
            ("" if hooks is None else f"[core]\n\thooksPath = {hooks}\n") + extra,
            encoding="utf-8")

    def check(self):
        return run_from_root(["python3", "-m", "agent_tools.verify_checks",
                              "managed-pre-push-hook", "--slug", self.SLUG],
                             env_extra=self.world.env)

    def test_the_managed_hook_refusing_a_default_branch_push_is_met(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         {"hooks_path": str(self.world.hooks), "managed": True,
                          "refused": True, "remote_unchanged": True,
                          "control_admitted": True, "met": True})

    def test_a_url_rewrite_in_the_user_config_does_not_move_the_fixture_pushes(self):
        self.set_user_config(self.world.hooks,
                             '[url "https://example.invalid/"]\n'
                             "\tinsteadOf = git@github.com:\n"
                             "\tpushInsteadOf = git@github.com:\n")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["met"])

    def test_an_unset_hooks_path_is_not_met(self):
        self.set_user_config(None)
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["hooks_path"], None)

    def test_an_unmanaged_hooks_directory_is_not_met(self):
        plain = self.world.tmp / "plain-hooks"
        self.world.hooks.rename(plain)
        self.set_user_config(plain)
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)["managed"])

    def test_a_managed_hook_that_admits_everything_is_not_met(self):
        (self.world.hooks / "pre-push").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["refused"])
        self.assertFalse(report["remote_unchanged"])

    def test_a_managed_hook_that_refuses_a_feature_push_too_is_not_met(self):
        (self.world.hooks / "pre-push").write_text(
            "#!/bin/sh\necho lifecycle guard pre-push: unsafe push: refusing to push the "
            "default branch main >&2\nexit 1\n", encoding="utf-8")
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["refused"])
        self.assertFalse(report["control_admitted"])

    def test_the_readme_documents_the_check_and_its_owner_requirement(self):
        readme = (Path(__file__).resolve().parent.parent / "python" / "README.md").read_text(
            encoding="utf-8")
        for needle in ("managed-pre-push-hook --slug S", "verify_checks.managed_pre_push_hook",
                       "-agent-git-hooks", "ssh:file", "authorized owner"):
            self.assertIn(needle, readme)

    def test_the_check_script_is_committed_executable(self):
        self.assertEqual(committed_mode("home/common/verify-pending/checks/managed-pre-push-hook"),
                         "100755")


if __name__ == "__main__":
    unittest.main()


RUNNERS = "repos/elevenyellow/jarbird/actions/runners?per_page=100"
WANTED = ("nix", "eleven-m5", "jarbird")


def runner_entry(name="eleven-m5-jarbird", status="online",
                 labels=("self-hosted", "macOS", "ARM64", "nix", "eleven-m5", "jarbird")):
    return {"id": 1, "name": name, "status": status, "busy": False,
            "labels": [{"id": i, "name": label, "type": "custom"} for i, label in enumerate(labels)]}


def judge_runner(entries, total=None):
    get, pages = forge({}, {RUNNERS: [{"total_count": len(entries) if total is None else total,
                                       "runners": list(entries)}]})
    with get, pages:
        return self_hosted_runner("elevenyellow/jarbird", "eleven-m5-jarbird", WANTED)


class SelfHostedRunnerTest(unittest.TestCase):
    def test_an_online_runner_with_every_label_is_met(self):
        code, report = judge_runner([runner_entry(name="other"), runner_entry()])
        self.assertEqual(code, 0)
        self.assertEqual((report["found"], report["status"], report["missing"]), (True, "online", []))
        self.assertEqual(report["required"], ["eleven-m5", "jarbird", "nix", "self-hosted"])

    def test_a_missing_label_is_not_met(self):
        code, report = judge_runner([runner_entry(labels=("self-hosted", "nix", "eleven-m5"))])
        self.assertEqual((code, report["missing"]), (1, ["jarbird"]))

    def test_an_offline_runner_is_not_yet(self):
        self.assertEqual(judge_runner([runner_entry(status="offline")])[0], 75)

    def test_an_unlisted_runner_is_not_yet(self):
        code, report = judge_runner([runner_entry(name="eleven-m5-arcwave")])
        self.assertEqual((code, report["found"], report["status"]), (75, False, None))

    def test_a_truncated_listing_is_refused(self):
        with self.assertRaises(forge_markers.ForgeError):
            judge_runner([runner_entry()], total=2)

    def test_malformed_entries_are_refused(self):
        bad_labels = runner_entry()
        bad_labels["labels"] = ["jarbird"]
        no_status = runner_entry()
        del no_status["status"]
        for entries in (["eleven-m5-jarbird"], [{"status": "online"}], [bad_labels], [no_status]):
            with self.subTest(entries=entries):
                with self.assertRaises(forge_markers.ForgeError):
                    judge_runner(entries)


class SelfHostedRunnerCommandTest(unittest.TestCase):
    ARGS = ["--repo", "elevenyellow/jarbird", "--runner", "eleven-m5-jarbird",
            "--label", "nix", "--label", "eleven-m5", "--label", "jarbird"]

    def test_wrapper_maps_a_forge_error_to_exit_2(self):
        # PATH holds only python3, so the wrapper finds its interpreter and gh is missing.
        with tempfile.TemporaryDirectory() as tmp:
            os.symlink(sys.executable, Path(tmp) / "python3")
            done = run_from_root(["/bin/sh", str(ROOT / CHECKS / "self-hosted-runner"), *self.ARGS],
                                 {"PATH": tmp})
        self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
        self.assertIn("forge_error", done.stderr)

    def test_a_malformed_listing_exits_2_through_main(self):
        get, pages = forge({}, {RUNNERS: [{"total_count": 1, "runners": [{"status": "online"}]}]})
        with get, pages, mock.patch("sys.stdout") as out, mock.patch("sys.stderr") as err:
            code = verify_checks.main(["self-hosted-runner", *self.ARGS])
        self.assertEqual(code, 2)
        out.write.assert_not_called()
        self.assertIn("forge_error: payload_invalid", "".join(c.args[0] for c in err.write.call_args_list))

    def test_bad_arguments_never_reach_the_forge(self):
        cases = (["--repo", "jarbird", *self.ARGS[2:]],
                 [*self.ARGS[:2], "--runner", "", *self.ARGS[4:]],
                 [*self.ARGS[:4], "--label", ""],
                 self.ARGS[:4])
        for argv in cases:
            with self.subTest(argv=argv):
                with mock.patch.object(verify_checks, "self_hosted_runner",
                                       side_effect=AssertionError("reached the forge")):
                    with self.assertRaises(SystemExit) as raised:
                        verify_checks.main(["self-hosted-runner", *argv])
                self.assertEqual(raised.exception.code, 2)

    def test_main_prints_the_report_and_returns_the_code(self):
        with mock.patch.object(verify_checks, "self_hosted_runner", return_value=(75, {"found": False})) as called:
            with mock.patch("sys.stdout") as out:
                code = verify_checks.main(["self-hosted-runner", *self.ARGS])
        self.assertEqual(code, 75)
        called.assert_called_once_with("elevenyellow/jarbird", "eleven-m5-jarbird", ["nix", "eleven-m5", "jarbird"])
        out.write.assert_any_call('{"found": false}')

    def test_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/self-hosted-runner"), "100755")

    def test_the_readme_documents_the_check(self):
        readme = (ROOT / "python" / "README.md").read_text(encoding="utf-8")
        for needle in ("self-hosted-runner --repo R --runner N --label L", "verify_checks.self_hosted_runner"):
            self.assertIn(needle, readme)
