"""`agent_tools.verify_checks`: the committed verify checks of issue 638."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools import agent_gate_bundle, verify_checks
from agent_tools.system import forge_api
from agent_tools.verify_checks import required_checks, self_hosted_runner

from .guard_policy_world import GuardPolicyWorld
from .pre_push_world import PrePushWorld
from .test_agent_gate_bundle import IDENTITY, context, flat, stratum  # the emitted-bundle builders

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
    return (mock.patch.object(forge_api, "api_get", side_effect=api_get),
            mock.patch.object(forge_api, "api_pages", side_effect=api_pages))


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
        with self.assertRaises(forge_api.ForgeError):
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
        with self.assertRaises(forge_api.ForgeError):
            self.check(gets, pages)

    def test_an_incomplete_search_is_refused(self):
        gets, pages = world([run("lint")])
        pages[SEARCH] = [search_page([2610], incomplete=True)]
        with self.assertRaises(forge_api.ForgeError) as raised:
            self.check(gets, pages)
        self.assertEqual(raised.exception.code, "payload_invalid")

    def test_a_truncated_search_is_refused(self):
        gets, pages = world([run("lint")])
        pages[SEARCH] = [search_page([2610], total=1500)]
        with self.assertRaises(forge_api.ForgeError):
            self.check(gets, pages)

    def test_check_runs_on_a_second_page_count_and_a_short_listing_is_refused(self):
        gets, pages = world([])
        pages[RUNS] = [{"total_count": 101, "check_runs": [run(f"other-{i}") for i in range(100)]},
                       {"total_count": 101, "check_runs": [run("lint")]}]
        self.assertEqual(self.check(gets, pages)[0], 0)
        pages[RUNS] = [{"total_count": 101, "check_runs": [run(f"other-{i}") for i in range(100)]}]
        with self.assertRaises(forge_api.ForgeError):
            self.check(gets, pages)

    def test_forge_error_propagates(self):
        with mock.patch.object(forge_api, "api_pages",
                               side_effect=forge_api.ForgeError("gh_failed", "boom")):
            with self.assertRaises(forge_api.ForgeError):
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

    def test_the_docstring_documents_the_check_and_its_owner_requirement(self):
        doc = verify_checks.__doc__
        for needle in ("managed-pre-push-hook --slug S", "verify_checks.managed_pre_push_hook",
                       "-agent-git-hooks", "ssh:file", "authorized owner"):
            self.assertIn(needle, doc)

    def test_the_check_script_is_committed_executable(self):
        self.assertEqual(committed_mode("home/common/verify-pending/checks/managed-pre-push-hook"),
                         "100755")


FAKE_RESOLVE = """#!/bin/sh
# fake resolve-project: answers from $FAKE_RESOLVE_DIR/<subcommand>.json and .exit
dir="$FAKE_RESOLVE_DIR"
cat "$dir/$1.json"
exit "$(cat "$dir/$1.exit" 2>/dev/null || echo 0)"
"""


class DeprecationsRetiredTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.root, self.answers, bin_dir = base / "root", base / "answers", base / "bin"
        for path in (self.root, self.answers, bin_dir):
            path.mkdir()
        fake = bin_dir / "resolve-project"
        fake.write_text(FAKE_RESOLVE)
        fake.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "FAKE_RESOLVE_DIR": str(self.answers)}
        git = ["git", "-C", str(self.root)]
        subprocess.run([*git, "init", "-q"], check=True)
        (self.root / "README.md").write_text("nodo\n")
        subprocess.run([*git, "add", "README.md"], check=True)
        subprocess.run([*git, "-c", "user.name=t", "-c", "user.email=t@t", "-c",
                        "commit.gpgsign=false", "commit", "-qm", "init"], check=True)
        self.answer(deprecated=[], adapter="none")

    def answer(self, *, deprecated, adapter, targets=(), state="unsupported", resolve_exit=0,
               project_id="elevenyellow/nodocom", schema_version=None):
        (self.answers / "platform-status.json").write_text(
            json.dumps({"project": {"deprecated_uses": deprecated}}))
        versioned = {} if schema_version is None else {"schema_version": schema_version}
        (self.answers / "resolve.json").write_text(json.dumps({
            **versioned,
            "project": {"id": project_id, "root": str(self.root)},
            "bindings": {} if adapter is None else {"deploy": {"adapter": adapter}},
            "capabilities": {"release": {"state": state, "reason_code": None, "repair_id": None}},
            "release": {"targets": [{"adapter": a} for a in targets]}}))
        (self.answers / "resolve.exit").write_text(str(resolve_exit))

    def check(self, **kwargs):
        options = {"watch_adapter": None, "red_pending": False, **kwargs}
        return verify_checks.deprecations_retired_check([self.root], self.env, **options)

    def commit(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        subprocess.run(["git", "-C", str(self.root), "add", path], check=True)

    def test_a_clean_root_is_green(self):
        code, report = self.check()
        self.assertEqual((code, report["met"], report["roots"][0]["verdict"]), (0, True, "green"))

    def test_each_reading_turns_the_root_red(self):
        cases = (
            lambda: self.answer(deprecated=["legacy-skills-config"], adapter="none"),
            lambda: self.commit(".claude/skills.config.json", "{}"),
            lambda: self.answer(deprecated=[], adapter="railway"),
            lambda: self.answer(deprecated=[], adapter="none", resolve_exit=2),
            lambda: self.commit("docs/deploy.md", "run release deploy inspect --commit x\n"),
        )
        for index, make_red in enumerate(cases):
            with self.subTest(case=index):
                self.setUp()
                make_red()
                code, report = self.check()
                self.assertEqual((code, report["roots"][0]["verdict"]), (1, "red"))
                self.assertEqual(self.check(red_pending=True)[0], 75)

    def test_a_schema_2_snapshot_without_a_deploy_binding_reads_c_green(self):
        self.answer(deprecated=[], adapter=None, schema_version=2)
        code, report = self.check()
        self.assertEqual((code, report["roots"][0]["readings"]["c"]["status"]), (0, "green"))
        self.answer(deprecated=[], adapter=None, schema_version=2, resolve_exit=2)
        self.assertEqual(self.check()[0], 1)

    def test_a_schema_1_snapshot_without_a_deploy_binding_reads_c_red(self):
        for version in (1, None, True, "2"):
            with self.subTest(schema_version=version):
                self.answer(deprecated=[], adapter=None, schema_version=version)
                code, report = self.check()
                self.assertEqual((code, report["roots"][0]["readings"]["c"]["status"]), (1, "red"))

    def test_a_schema_1_snapshot_with_the_none_adapter_reads_c_green(self):
        self.answer(deprecated=[], adapter="none", schema_version=1)
        self.assertEqual(self.check()[1]["roots"][0]["readings"]["c"]["status"], "green")

    def test_a_real_deploy_adapter_keeps_c_red_and_none_keeps_it_green(self):
        self.answer(deprecated=[], adapter="railway")
        code, report = self.check()
        self.assertEqual((code, report["roots"][0]["readings"]["c"]["status"]), (1, "red"))
        self.answer(deprecated=[], adapter="none")
        self.assertEqual(self.check()[1]["roots"][0]["readings"]["c"]["status"], "green")

    def test_a_hit_under_the_artifact_directory_is_not_a_user(self):
        self.commit(".agents/artifacts/evidence/old.md", "release deploy inspect\n")
        self.assertEqual(self.check()[0], 0)

    def test_the_nix_config_root_is_scoped_to_its_skills(self):
        self.answer(deprecated=[], adapter="none", project_id="fagenorn/nix-config")
        self.commit("python/agent_tools/verify_checks.py", 'RETIRED_COMMAND = "release deploy inspect"\n')
        self.commit("tests/test_verify_checks.py", "release deploy inspect\n")
        code, report = self.check()
        self.assertEqual((code, report["roots"][0]["verdict"]), (0, "green"))
        self.assertEqual(report["roots"][0]["readings"]["d"]["scope"],
                         ["home/common/agent-skills/skills"])
        self.commit("home/common/agent-skills/skills/ship-release/SKILL.md",
                    "run release deploy inspect\n")
        self.assertEqual(self.check()[0], 1)

    def test_another_root_greps_the_whole_tree(self):
        self.commit("python/tool.py", "release deploy inspect\n")
        code, report = self.check()
        self.assertEqual((code, report["roots"][0]["readings"]["d"]["scope"]),
                         (1, [".", ":!.agents/artifacts"]))

    def test_the_watch_adapter_is_pending_until_adopted_and_available(self):
        self.assertEqual(self.check(watch_adapter="railway-deploy")[0], 75)
        self.answer(deprecated=[], adapter="none", targets=("github-forge", "railway-deploy"),
                    state="blocked")
        code, report = self.check(watch_adapter="railway-deploy")
        self.assertEqual((code, report["roots"][0]["verdict"]), (1, "red"))
        self.answer(deprecated=[], adapter="none", targets=("github-forge", "railway-deploy"),
                    state="available")
        self.assertEqual(self.check(watch_adapter="railway-deploy")[0], 0)

    def test_an_unreadable_platform_status_is_a_tool_error(self):
        (self.answers / "platform-status.json").write_text("not json")
        with self.assertRaises(verify_checks.ToolError):
            self.check()


class DeprecationsRetiredWrapperTest(unittest.TestCase):
    def test_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/deprecations-retired"), "100755")

    def test_the_command_line_exits_two_on_a_tool_error(self):
        with tempfile.TemporaryDirectory() as home:
            done = run_from_root([str(ROOT / CHECKS / "deprecations-retired"),
                                  "--repo-root", home], {"HOME": home, "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin"})
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("verify-checks: tool_error:", done.stderr)


def fleet(version, rows):
    return {"platform": {"platform_version": version}, "fleet": rows}


def row(pid, compatible=True, removed=None):
    return {"project_id": pid, "root": f"/r/{pid}", "compatible": compatible,
            "removed_uses": removed if removed is not None else []}


def entry(i):
    return {"id": f"d{i}", "kind": "platform_behavior", "subject": f"s{i}",
            "since": "1.2.0", "successor": "x", "migration": "m"}


def manifests(main_ids=(1, 2), removal_ids=(1, 2), main="1.2.0", cand="2.0.0"):
    shape = {"schema_version": 1, "project_schema_versions": [1, 2],
             "resolved_schema_version": 1, "migrations": []}
    return ({**shape, "platform_version": main,
             "deprecations": [entry(i) for i in main_ids], "removals": []},
            {**shape, "platform_version": cand,
             "deprecations": [], "removals": [entry(i) for i in removal_ids]})


GREEN_MANIFEST = {"verdict": "green"}


class ManifestVerdictTest(unittest.TestCase):
    def test_every_removal_declared_is_green(self):
        code, report = verify_checks.manifest_verdict(*manifests())
        self.assertEqual((code, report["verdict"], report["undeclared"]), (0, "green", []))
        self.assertEqual(report, {"verdict": "green", "main_version": "1.2.0",
                                  "candidate_version": "2.0.0", "removal_ids": ["d1", "d2"],
                                  "undeclared": []})

    def test_one_missing_deprecation_is_not_green(self):
        code, report = verify_checks.manifest_verdict(*manifests(main_ids=(1,)))
        self.assertEqual((code, report["verdict"], report["undeclared"]), (75, "red", ["d2"]))

    def test_a_changed_entry_is_not_declared(self):
        main, cand = manifests()
        cand["removals"][0]["successor"] = "other"
        self.assertEqual(verify_checks.manifest_verdict(main, cand)[1]["undeclared"], ["d1"])

    def test_every_one_of_the_six_members_must_be_equal(self):
        valid_change = {"id": "changed", "kind": "project_file", "subject": "changed",
                        "since": "1.9.0", "successor": "changed", "migration": "changed"}
        for member, changed in valid_change.items():
            with self.subTest(member=member):
                main, cand = manifests(main_ids=(1,), removal_ids=(1,))
                cand["removals"][0][member] = changed
                code, report = verify_checks.manifest_verdict(main, cand)
                self.assertEqual(code, 75)
                self.assertEqual(len(report["undeclared"]), 1)

    def test_majors_and_emptiness(self):
        for args in (dict(main="2.0.0"), dict(cand="1.3.0"), dict(removal_ids=())):
            with self.subTest(**args):
                self.assertEqual(verify_checks.manifest_verdict(*manifests(**args))[0], 75)

    def test_an_unreadable_manifest_is_usage(self):
        for main, cand in (([], manifests()[1]), (manifests()[0], "x"), (None, None)):
            with self.subTest(main=main):
                code, report = verify_checks.manifest_verdict(main, cand)
                self.assertEqual((code, report["verdict"]), (2, "unreadable"))

    def test_a_manifest_lacking_a_member_is_usage(self):
        for member in ("platform_version", "deprecations", "removals"):
            for side in (0, 1):
                with self.subTest(member=member, side=side):
                    pair = list(manifests())
                    del pair[side][member]
                    self.assertEqual(verify_checks.manifest_verdict(*pair)[0], 2)


    def test_a_manifest_the_validator_rejects_is_usage_even_when_the_records_match(self):
        for member in ("project_schema_versions", "resolved_schema_version",
                       "schema_version", "migrations"):
            for side in (0, 1):
                with self.subTest(member=member, side=side):
                    pair = list(manifests())
                    del pair[side][member]
                    code, report = verify_checks.manifest_verdict(*pair)
                    self.assertEqual((code, report["verdict"]), (2, "unreadable"))
        pair = list(manifests())
        pair[1]["removals"][0]["kind"] = "not-a-kind"
        self.assertEqual(verify_checks.manifest_verdict(*pair)[0], 2)


class PreflightVerdictTest(unittest.TestCase):
    def test_green_needs_every_row_compatible_on_both_sides(self):
        code, report = verify_checks.preflight_verdict(
            fleet("1.2.0", [row("b"), row("a")]), fleet("2.0.0", [row("a"), row("b")]), SHA,
            GREEN_MANIFEST)
        self.assertEqual((code, report["verdict"]), (0, "green"))
        self.assertEqual({key: report[key] for key in
                          ("candidate", "bridge_version", "candidate_version", "manifest")},
                         {"candidate": SHA, "bridge_version": "1.2.0",
                          "candidate_version": "2.0.0", "manifest": GREEN_MANIFEST})
        self.assertEqual(report["rows"], [
            {"project_id": pid, "root": f"/r/{pid}", "bridge_compatible": True,
             "candidate_compatible": True, "removed_uses": [], "reason": None}
            for pid in ("a", "b")])

    def test_each_rule_alone_keeps_it_not_yet(self):
        ok = (fleet("1.2.0", [row("a")]), fleet("2.0.0", [row("a")]))
        cases = {
            "manifest_red": (*ok, {"verdict": "red", "undeclared": ["d2"]}),
            "bridge_too_old": (fleet("1.1.0", [row("a")]), ok[1], GREEN_MANIFEST),
            "bridge_not_major_1": (fleet("2.0.0", [row("a")]), ok[1], GREEN_MANIFEST),
            "candidate_not_major_2": (ok[0], fleet("1.3.0", [row("a")]), GREEN_MANIFEST),
            "empty": (fleet("1.2.0", []), fleet("2.0.0", []), GREEN_MANIFEST),
            "roster_differs": (ok[0], fleet("2.0.0", [row("b")]), GREEN_MANIFEST),
            "bridge_incompatible": (fleet("1.2.0", [row("a", False)]), ok[1], GREEN_MANIFEST),
            "candidate_incompatible": (ok[0], fleet("2.0.0", [row("a", False)]), GREEN_MANIFEST),
            "removed_use": (ok[0], fleet("2.0.0", [row("a", removed=["legacy-skills-config"])]),
                            GREEN_MANIFEST),
            "removed_use_unknown": (ok[0], fleet("2.0.0", [row("a", removed=None) | {
                "removed_uses": None}]), GREEN_MANIFEST),
        }
        for name, (bridge, candidate, manifest) in cases.items():
            with self.subTest(name=name):
                code, report = verify_checks.preflight_verdict(bridge, candidate, SHA, manifest)
                self.assertEqual(code, 75)
                self.assertNotEqual(report["verdict"], "green")

    def test_a_row_reason_is_the_first_rule_it_fails(self):
        code, report = verify_checks.preflight_verdict(
            fleet("1.2.0", [row("a", False), row("b"), row("c"), row("d")]),
            fleet("2.0.0", [row("a", False), row("b", False), row("c", removed=["x"]),
                            row("e")]),
            SHA, GREEN_MANIFEST)
        self.assertEqual(code, 75)
        reasons = {r["project_id"]: r["reason"] for r in report["rows"]}
        self.assertEqual([r["project_id"] for r in report["rows"]], ["a", "b", "c", "d", "e"])
        self.assertEqual(reasons["a"], "bridge_incompatible")
        self.assertEqual(reasons["b"], "candidate_incompatible")
        self.assertEqual(reasons["c"], "removed_use")
        self.assertEqual(reasons["d"], "candidate_missing")
        self.assertEqual(reasons["e"], "bridge_missing")

    def test_a_malformed_report_is_not_green_and_does_not_raise(self):
        for bridge, candidate in (({}, {}), ({"platform": [], "fleet": 1}, fleet("2.0.0", [])),
                                  (fleet("1.2.0", [1]), fleet("2.0.0", [{"project_id": 1}]))):
            with self.subTest(bridge=bridge):
                self.assertEqual(
                    verify_checks.preflight_verdict(bridge, candidate, SHA, GREEN_MANIFEST)[0], 75)

    def test_the_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/cutover-preflight"), "100755")


MANIFEST = "home/common/agent-skills/platform-manifest.json"
CANDIDATE_BRANCH = "cutover-130-candidate"

CANDIDATE_RESOLVER = """import json, os, sys
if os.path.realpath(__file__).split(os.sep)[:len(os.path.realpath(os.getcwd()).split(os.sep))] \
        != os.path.realpath(os.getcwd()).split(os.sep):
    sys.exit(9)
args = sys.argv[1:]
if args[:2] != ["platform-status", "--fleet"] or args[2] != "--manifest" or len(args) != 4:
    sys.exit(8)
if not os.path.isfile(args[3]):
    sys.exit(7)
print(json.dumps({"platform": {"platform_version": "2.0.0"},
                  "fleet": [{"project_id": "a", "root": "/r/a", "compatible": True,
                             "removed_uses": []}]}))
"""
BRIDGE = """#!/bin/sh
[ -z "${PYTHONPATH+x}" ] || exit 9
[ "$*" = "platform-status --fleet" ] || exit 8
%s
"""
BRIDGE_JSON = json.dumps(fleet("1.2.0", [row("a")]))


class CutoverWorld:
    """A bare `origin`, a pusher that writes it, and a clone that has only `main`."""

    def __init__(self, test_case, main_ids=(1, 2)):
        tmp = tempfile.TemporaryDirectory()
        test_case.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        patch = mock.patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"})
        patch.start()
        test_case.addCleanup(patch.stop)
        self.bare = self.tmp / "origin.git"
        self.git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.bare))
        self.pusher = self.tmp / "pusher"
        self.git(self.tmp, "init", "-q", "-b", "main", str(self.pusher))
        self.git(self.pusher, "remote", "add", "origin", str(self.bare))
        self.commit(self.pusher, manifests(main_ids=main_ids)[0])
        self.git(self.pusher, "push", "-q", "origin", "main")
        self.clone = self.tmp / "clone"
        self.git(self.tmp, "clone", "-q", str(self.bare), str(self.clone))

    @staticmethod
    def git(cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                              check=True, timeout=60).stdout.strip()

    def commit(self, repo, manifest, files=None):
        path = repo / MANIFEST
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        for name, text in (files or {}).items():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text(text, encoding="utf-8")
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", "manifest")
        return self.git(repo, "rev-parse", "HEAD")

    def publish_candidate(self, removal_ids=(1, 2), files=None):
        self.git(self.pusher, "checkout", "-q", "-b", CANDIDATE_BRANCH)
        sha = self.commit(self.pusher, manifests(removal_ids=removal_ids)[1], files)
        self.git(self.pusher, "push", "-q", "origin", f"HEAD:refs/heads/{CANDIDATE_BRANCH}")
        self.git(self.pusher, "checkout", "-q", "main")
        return sha

    def refs(self):
        return self.git(self.clone, "for-each-ref")


class CutoverManifestTest(unittest.TestCase):
    def test_an_absent_candidate_branch_is_not_yet(self):
        world = CutoverWorld(self)
        code, report = verify_checks.cutover_manifest(world.clone, CANDIDATE_BRANCH)
        self.assertEqual((code, report["verdict"]), (75, "absent"))
        code, report = verify_checks.cutover_preflight(
            world.clone, CANDIDATE_BRANCH, environ=os.environ)
        self.assertEqual((code, report["verdict"]), (75, "absent"))

    def test_the_main_ref_names_the_main_side_and_is_not_fetched(self):
        world = CutoverWorld(self)
        world.publish_candidate()
        code, report = verify_checks.cutover_manifest(world.clone, main_ref="HEAD")
        self.assertEqual((code, report["verdict"], report["undeclared"]), (0, "green", []))
        self.assertEqual(report["removal_ids"], ["d1", "d2"])
        world.commit(world.clone, manifests(main_ids=(1,))[0])
        code, report = verify_checks.cutover_manifest(world.clone, main_ref="HEAD")
        self.assertEqual((code, report["verdict"], report["undeclared"]), (75, "red", ["d2"]))

    def test_without_a_main_ref_origin_main_is_the_main_side(self):
        world = CutoverWorld(self, main_ids=(1,))
        world.publish_candidate()
        code, report = verify_checks.cutover_manifest(world.clone, CANDIDATE_BRANCH)
        self.assertEqual((code, report["undeclared"]), (75, ["d2"]))
        world.git(world.pusher, "checkout", "-q", "main")
        world.commit(world.pusher, manifests()[0])
        world.git(world.pusher, "push", "-q", "origin", "main")
        code, report = verify_checks.cutover_manifest(world.clone, CANDIDATE_BRANCH)
        self.assertEqual((code, report["verdict"]), (0, "green"))

    def test_no_ref_is_written_in_the_clone(self):
        world = CutoverWorld(self, main_ids=(1,))
        world.publish_candidate()
        world.git(world.pusher, "checkout", "-q", "main")
        world.commit(world.pusher, manifests()[0])
        world.git(world.pusher, "push", "-q", "origin", "main")
        before = world.refs()
        self.assertIn("refs/remotes/origin/main", before)
        verify_checks.cutover_manifest(world.clone, CANDIDATE_BRANCH)
        self.assertEqual(world.refs(), before)

    def test_a_candidate_without_a_readable_manifest_is_usage(self):
        world = CutoverWorld(self)
        world.git(world.pusher, "checkout", "-q", "-b", CANDIDATE_BRANCH)
        world.git(world.pusher, "rm", "-q", MANIFEST)
        world.git(world.pusher, "commit", "-q", "-m", "drop")
        world.git(world.pusher, "push", "-q", "origin", f"HEAD:refs/heads/{CANDIDATE_BRANCH}")
        code, report = verify_checks.cutover_manifest(world.clone, CANDIDATE_BRANCH)
        self.assertEqual((code, report["verdict"]), (2, "unreadable"))

    def test_the_command_prints_the_report_and_exits_with_its_code(self):
        world = CutoverWorld(self)
        done = run_from_root([sys.executable, "-m", "agent_tools.verify_checks", "cutover-manifest",
                              "--repo-root", str(world.clone)])
        self.assertEqual(done.returncode, 75, done.stderr)
        self.assertEqual(json.loads(done.stdout)["verdict"], "absent")
        world.publish_candidate()
        done = run_from_root([sys.executable, "-m", "agent_tools.verify_checks", "cutover-manifest",
                              "--repo-root", str(world.clone), "--main-ref", "HEAD"])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["verdict"], "green")


class CutoverPreflightTest(unittest.TestCase):
    def setUp(self):
        self.world = CutoverWorld(self)
        self.sha = self.world.publish_candidate(files={
            "python/agent_tools/__init__.py": "",
            "python/agent_tools/project_contract/__init__.py": "",
            "python/agent_tools/project_contract/resolve_project.py": CANDIDATE_RESOLVER})
        self.bin = self.world.tmp / "bin"
        self.bin.mkdir()
        self.scratch = self.world.tmp / "scratch"
        self.scratch.mkdir()
        patch = mock.patch.object(tempfile, "tempdir", str(self.scratch))
        patch.start()
        self.addCleanup(patch.stop)

    def bridge(self, body):
        script = self.bin / "resolve-project"
        script.write_text(BRIDGE % body, encoding="utf-8")
        script.chmod(0o755)

    def environ(self):
        return {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "PYTHONPATH": "python"}

    def preflight(self):
        return verify_checks.cutover_preflight(
            self.world.clone, CANDIDATE_BRANCH, environ=self.environ())

    def test_both_sides_judging_the_fleet_compatible_is_green(self):
        self.bridge(f"echo '{BRIDGE_JSON}'")
        code, report = self.preflight()
        self.assertEqual((code, report["verdict"]), (0, "green"), report)
        self.assertEqual(report["candidate"], self.sha)
        self.assertEqual(report["manifest"]["verdict"], "green")
        self.assertEqual([r["project_id"] for r in report["rows"]], ["a"])
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_the_bridge_failing_names_the_bridge(self):
        for body in ("exit 3", "echo not-json"):
            with self.subTest(body=body):
                self.bridge(body)
                code, report = self.preflight()
                self.assertEqual((code, report["verdict"], report["side"]),
                                 (75, "unreadable", "bridge"))
                self.assertEqual(list(self.scratch.iterdir()), [])

    def test_a_missing_bridge_names_the_bridge(self):
        environ = {**self.environ(), "PATH": f"{self.bin}:{Path(shutil.which('git')).parent}"}
        code, report = verify_checks.cutover_preflight(
            self.world.clone, CANDIDATE_BRANCH, environ=environ)
        self.assertEqual((code, report["verdict"], report["side"]), (75, "unreadable", "bridge"))

    def test_a_hung_side_times_out_and_is_named(self):
        self.bridge("exec sleep 10")
        started = time.monotonic()
        with mock.patch.object(verify_checks, "SIDE_TIMEOUT", 1):
            code, report = self.preflight()
        self.assertLess(time.monotonic() - started, 8)
        self.assertEqual((code, report["verdict"], report["side"]), (75, "unreadable", "bridge"))

    def test_the_candidate_side_failing_names_the_candidate(self):
        self.bridge(f"echo '{BRIDGE_JSON}'")
        self.world.git(self.world.pusher, "checkout", "-q", CANDIDATE_BRANCH)
        (self.world.pusher / "python/agent_tools/project_contract/resolve_project.py").write_text(
            "import sys\nsys.exit(4)\n", encoding="utf-8")
        self.world.git(self.world.pusher, "commit", "-q", "-am", "break")
        self.world.git(self.world.pusher, "push", "-q", "origin", f"HEAD:refs/heads/{CANDIDATE_BRANCH}")
        code, report = self.preflight()
        self.assertEqual((code, report["verdict"], report["side"]), (75, "unreadable", "candidate"))

    def test_an_incompatible_candidate_row_is_not_yet(self):
        self.bridge(f"echo '{BRIDGE_JSON}'")
        self.world.git(self.world.pusher, "checkout", "-q", CANDIDATE_BRANCH)
        (self.world.pusher / "python/agent_tools/project_contract/resolve_project.py").write_text(
            CANDIDATE_RESOLVER.replace('"compatible": True', '"compatible": False'),
            encoding="utf-8")
        self.world.git(self.world.pusher, "commit", "-q", "-am", "incompatible")
        self.world.git(self.world.pusher, "push", "-q", "origin", f"HEAD:refs/heads/{CANDIDATE_BRANCH}")
        code, report = self.preflight()
        self.assertEqual((code, report["verdict"]), (75, "not_yet"))
        self.assertEqual(report["rows"][0]["reason"], "candidate_incompatible")

    def test_no_ref_is_written_in_the_clone(self):
        self.bridge(f"echo '{BRIDGE_JSON}'")
        before = self.world.refs()
        self.preflight()
        self.assertEqual(self.world.refs(), before)

    def test_the_command_runs_the_wrapper(self):
        self.bridge(f"echo '{BRIDGE_JSON}'")
        done = run_from_root(
            [str(ROOT / CHECKS / "cutover-preflight"), "--repo-root", str(self.world.clone)],
            {"HOME": str(self.world.tmp), "PATH": self.environ()["PATH"]})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["verdict"], "green")


def emitted(state, candidate):
    """A real emitted bundle (assemble_bundle, valid id) whose identity binds `candidate`."""
    identity = json.loads(json.dumps(IDENTITY))
    identity["bound"]["commit"]["candidate"] = candidate
    value = {"approved": flat(stratum(context(1000, 800))),
             "rejected": flat(stratum(context(1000, 999))), "unmeasured": None}[state]
    return agent_gate_bundle.assemble_bundle(
        {"identity": identity, "expansion": {"expanded": False, "checkpoint_ref": None}},
        value, [], None, state)


def emitted_claude_only(state, candidate, kind="cutover", version=2):
    """A real version-2 or version-3 bundle: claude-only evidence, bound to `candidate`, of reader kind `kind`."""
    identity = json.loads(json.dumps(IDENTITY))
    identity["bound"]["commit"]["candidate"] = candidate
    identity["pinned"]["builds"].pop("codex", None)
    profile = agent_gate_bundle.gate_profile(version, kind)
    value = {"approved": {"cases": [
                 dict(case, strata={"claude": case["strata"]["claude"]})
                 for case in flat(stratum(context(1000, 1000)))["cases"]]},
             "unmeasured": None}[state]
    return agent_gate_bundle.assemble_bundle(
        {"identity": identity, "expansion": {"expanded": False, "checkpoint_ref": None}},
        value, [], None, state, profile)


class BundleVerdictTest(unittest.TestCase):
    def test_an_approved_claude_only_cutover_bundle_is_green(self):
        code, report = verify_checks.bundle_verdict(
            {"cutover-130-bundle.json": emitted_claude_only("approved", SHA),
             "release-128-bundle.json": emitted("unmeasured", "b" * 40)}, SHA)
        self.assertEqual((code, report["verdict"], report["approved"]),
                         (0, "green", ["cutover-130-bundle.json"]))

    def test_an_approved_distributional_cutover_bundle_is_green(self):
        code, report = verify_checks.bundle_verdict(
            {"cutover-757-bundle.json": emitted_claude_only("approved", SHA, version=3)}, SHA)
        self.assertEqual((code, report["verdict"], report["approved"]),
                         (0, "green", ["cutover-757-bundle.json"]))

    def test_a_version_two_bundle_of_another_kind_is_unreadable(self):
        for kind in ("promotion", "release"):
            with self.subTest(kind=kind):
                code, report = verify_checks.bundle_verdict(
                    {"x-bundle.json": emitted_claude_only("unmeasured", SHA, kind)}, SHA)
                self.assertEqual((code, report["approved"]), (75, []))
                self.assertEqual([u["path"] for u in report["unreadable"]], ["x-bundle.json"])

    def test_a_relabelled_claude_only_bundle_is_unreadable(self):
        tampered = emitted_claude_only("approved", SHA)
        tampered["bundle_kind"] = "promotion"
        code, report = verify_checks.bundle_verdict({"x-bundle.json": tampered}, SHA)
        self.assertEqual((code, report["approved"]), (75, []))

    def test_an_approved_bundle_binding_the_candidate_is_green(self):
        code, report = verify_checks.bundle_verdict(
            {"a-bundle.json": emitted("approved", SHA),
             "release-128-bundle.json": emitted("unmeasured", "b" * 40)}, SHA)
        self.assertEqual((code, report["verdict"]), (0, "green"))
        self.assertEqual(report["approved"], ["a-bundle.json"])

    def test_unmeasured_rejected_or_another_candidate_is_not_yet(self):
        for bundles in ({}, {"x-bundle.json": emitted("unmeasured", SHA)},
                        {"x-bundle.json": emitted("rejected", SHA)},
                        {"x-bundle.json": emitted("approved", "b" * 40)}):
            with self.subTest(bundles=list(bundles)):
                self.assertEqual(verify_checks.bundle_verdict(bundles, SHA)[0], 75)

    def test_a_two_field_approval_is_unreadable(self):
        fake = {"state": "approved", "identity": {"bound": {"commit": {"candidate": SHA}}}}
        code, report = verify_checks.bundle_verdict({"x-bundle.json": fake}, SHA)
        self.assertEqual((code, [u["path"] for u in report["unreadable"]]), (75, ["x-bundle.json"]))

    def test_a_relabelled_bundle_is_unreadable(self):
        tampered = emitted("rejected", SHA)
        tampered["state"] = "approved"
        code, report = verify_checks.bundle_verdict({"x-bundle.json": tampered}, SHA)
        self.assertEqual((code, report["approved"]), (75, []))
        self.assertEqual([u["path"] for u in report["unreadable"]], ["x-bundle.json"])

    def test_a_rebound_candidate_breaks_the_digest(self):
        moved = emitted("approved", "b" * 40)
        moved["identity"]["bound"]["commit"]["candidate"] = SHA
        self.assertEqual(verify_checks.bundle_verdict({"x-bundle.json": moved}, SHA)[0], 75)

    def test_a_candidate_that_is_not_a_commit_id_is_unreadable(self):
        for bound in ("unpinned", "A" * 40, "a" * 39, None):
            with self.subTest(bound=bound):
                code, report = verify_checks.bundle_verdict(
                    {"x-bundle.json": emitted("approved", bound)}, bound)
                self.assertEqual((code, report["approved"]), (75, []))
                self.assertEqual([u["path"] for u in report["unreadable"]], ["x-bundle.json"])

    def test_the_committed_cutover_bundle_verifies_unmeasured(self):
        doc = json.loads((ROOT / ".agents/artifacts/evidence/cutover-579-bundle.json").read_text())
        self.assertEqual(agent_gate_bundle.verify_bundle(doc), "unmeasured")
        self.assertRegex(doc["identity"]["bound"]["commit"]["candidate"], r"^[0-9a-f]{40}$")

    def test_the_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/cutover-bundle"), "100755")


EVIDENCE = ".agents/artifacts/evidence"


class CutoverBundleTest(unittest.TestCase):
    def test_the_check_reads_the_bundles_at_origin_main(self):
        world = CutoverWorld(self)
        candidate = world.publish_candidate()
        code, report = verify_checks.cutover_bundle(world.clone, CANDIDATE_BRANCH)
        self.assertEqual((code, report["approved"], report["candidate"]), (75, [], candidate))
        files = {f"{EVIDENCE}/a-bundle.json": json.dumps(emitted("approved", candidate)),
                 f"{EVIDENCE}/b-bundle.json": "not json",
                 f"{EVIDENCE}/c-trials.json": "{}"}
        world.commit(world.pusher, manifests()[0], files)
        world.git(world.pusher, "push", "-q", "origin", "main")
        code, report = verify_checks.cutover_bundle(world.clone, CANDIDATE_BRANCH)
        self.assertEqual((code, report["verdict"]), (0, "green"))
        self.assertEqual(report["approved"], [f"{EVIDENCE}/a-bundle.json"])
        self.assertEqual([u["path"] for u in report["unreadable"]], [f"{EVIDENCE}/b-bundle.json"])

    def test_an_absent_candidate_branch_is_not_yet(self):
        world = CutoverWorld(self)
        code, report = verify_checks.cutover_bundle(world.clone, CANDIDATE_BRANCH)
        self.assertEqual((code, report["verdict"]), (75, "absent"))


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
        with self.assertRaises(forge_api.ForgeError):
            judge_runner([runner_entry()], total=2)

    def test_malformed_entries_are_refused(self):
        bad_labels = runner_entry()
        bad_labels["labels"] = ["jarbird"]
        no_status = runner_entry()
        del no_status["status"]
        for entries in (["eleven-m5-jarbird"], [{"status": "online"}], [bad_labels], [no_status]):
            with self.subTest(entries=entries):
                with self.assertRaises(forge_api.ForgeError):
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

    def test_the_docstring_documents_the_check(self):
        doc = verify_checks.__doc__
        for needle in ("self-hosted-runner --repo R --runner N --label L", "verify_checks.self_hosted_runner"):
            self.assertIn(needle, doc)


class GuardFleetWorld(GuardPolicyWorld):
    """A hermetic fleet plus a clone whose origin carries the cutover candidate: the real
    `python/` tree and platform manifest, committed on `cutover-130-candidate`."""

    def __init__(self, test_case):
        super().__init__(test_case)
        bare = self.tmp / "candidate-origin.git"
        pusher = self.tmp / "candidate-pusher"
        self.clone = self.tmp / "candidate-clone"
        self.git(self.tmp, "init", "--quiet", "--bare", "-b", "main", str(bare))
        self.git(self.tmp, "init", "--quiet", "-b", "main", str(pusher))
        self.git(pusher, "config", "commit.gpgsign", "false")
        self.git(pusher, "remote", "add", "origin", str(bare))
        (pusher / "README").write_text("main\n", encoding="utf-8")
        self.git(pusher, "add", "-A")
        self.git(pusher, "commit", "--quiet", "-m", "main")
        self.git(pusher, "push", "--quiet", "origin", "main")
        self.git(pusher, "checkout", "--quiet", "-b", CANDIDATE_BRANCH)
        shutil.copytree(ROOT / "python", pusher / "python",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (pusher / verify_checks.MANIFEST_PATH).parent.mkdir(parents=True)
        shutil.copy(ROOT / verify_checks.MANIFEST_PATH, pusher / verify_checks.MANIFEST_PATH)
        self.git(pusher, "add", "-A")
        self.git(pusher, "commit", "--quiet", "-m", "candidate")
        self.git(pusher, "push", "--quiet", "origin", f"HEAD:refs/heads/{CANDIDATE_BRANCH}")
        self.git(self.tmp, "clone", "--quiet", str(bare), str(self.clone))

    def fleet(self, registry=None):
        # The host's own PYTHONPATH must not decide whose code derives: the check does.
        environ = {key: value for key, value in self.env.items() if key != "PYTHONPATH"}
        return verify_checks.guard_policy_fleet(
            self.clone, CANDIDATE_BRANCH, environ=environ, registry=registry)

    def lagging_default(self, project_id, slug, *, override):
        """The anis-desktop nodocom entry: `main` is a schema-1 contract, `dev` a schema-2 one,
        and the registry entry carries the `branch_override` only when `override` is true."""
        root = self.project(project_id, slug, integration_branch="dev", register=False)
        self.git(root, "checkout", "--quiet", "main")
        old = self.contract(project_id, slug)
        old["schema_version"] = 1
        self.commit_contract(root, old, "the project's schema-1 default branch", render=False)
        self.publish(root, ["main", "dev"])
        entry = {"project_id": project_id, "root": str(root)}
        if override:
            entry["branch_override"] = {"branch": "dev", "default_branch": "main",
                                        "reason": "default_contract_unresolved"}
        self.register(entry)


class GuardPolicyFleetTest(unittest.TestCase):
    def setUp(self):
        self.world = GuardFleetWorld(self)

    def test_every_registered_slug_deriving_is_green(self):
        self.world.project("fixture/one", "fagenorn/one")
        self.world.project("fixture/two", "fagenorn/two")
        code, report = self.world.fleet()
        self.assertEqual((code, report["verdict"]), (0, "green"), report)
        self.assertEqual([(r["repository"], r["exit"], r["outcome"]) for r in report["rows"]],
                         [("fagenorn/one", 0, "derived"), ("fagenorn/two", 0, "derived")])

    def test_the_anis_desktop_nodocom_entry_reads_red(self):
        self.world.project("fixture/one", "fagenorn/one")
        self.world.lagging_default("elevenyellow/nodocom", "elevenyellow/nodocom",
                                   override=False)
        code, report = self.world.fleet()
        self.assertEqual((code, report["verdict"]), (1, "red"), report)
        [bad] = [r for r in report["rows"] if r["verdict"] == "red"]
        self.assertEqual((bad["repository"], bad["exit"], bad["outcome"], bad["reason_codes"]),
                         ("elevenyellow/nodocom", 1, "refused", ["contract_unresolved"]))
        [good] = [r for r in report["rows"] if r["verdict"] == "green"]
        self.assertEqual(good["repository"], "fagenorn/one")

    def test_the_same_entry_with_the_override_is_green(self):
        self.world.lagging_default("elevenyellow/nodocom", "elevenyellow/nodocom",
                                   override=True)
        code, report = self.world.fleet()
        self.assertEqual((code, report["verdict"]), (0, "green"), report)

    def test_an_entry_whose_origin_names_no_slug_is_red(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        self.world.identity(root, "git@gitlab.com:fagenorn/one.git")
        code, report = self.world.fleet()
        self.assertEqual((code, report["verdict"]), (1, "red"), report)
        self.assertEqual([(r["repository"], r["outcome"]) for r in report["rows"]],
                         [(None, "origin_unproven")])

    def test_an_unreadable_registry_is_red_not_empty(self):
        self.world.project("fixture/one", "fagenorn/one")
        self.world.write_registry("{not json")
        code, report = self.world.fleet()
        self.assertEqual((code, report["verdict"]), (75, "unreadable"), report)

    def test_a_named_registry_file_that_is_missing_is_unreadable(self):
        self.world.project("fixture/one", "fagenorn/one")
        code, report = self.world.fleet(registry=self.world.tmp / "no-such-registry.json")
        self.assertEqual((code, report["verdict"], report["side"], report["rows"]),
                         (75, "unreadable", "registry", []))

    def test_an_absent_default_registry_is_the_empty_fleet(self):
        (self.world.home / ".agents/state/fleet/registry.json").unlink(missing_ok=True)
        code, report = self.world.fleet()
        self.assertEqual((code, report["verdict"], report["rows"]), (0, "green", []))

    def test_a_registry_the_guard_would_refuse_is_unreadable(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        entries = [{"project_id": "fixture/one", "root": str(root)}]
        for name, document in (
                ("no-schema", {"projects": entries}),
                ("wrong-schema", {"schema_version": "1", "projects": entries}),
                ("extra-member", {"schema_version": 1, "projects": entries, "note": "x"})):
            with self.subTest(name=name):
                path = self.world.tmp / f"{name}.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                code, report = self.world.fleet(registry=path)
                self.assertEqual((code, report["verdict"], report["side"]),
                                 (75, "unreadable", "registry"), report)

    def test_a_registry_file_replaces_the_hosts_own(self):
        self.world.project("fixture/one", "fagenorn/one")
        empty = self.world.tmp / "empty-registry.json"
        empty.write_text(json.dumps({"schema_version": 1, "projects": []}), encoding="utf-8")
        code, report = self.world.fleet(registry=empty)
        self.assertEqual((code, report["verdict"], report["rows"]), (0, "green", []))

    def test_an_absent_candidate_branch_is_not_yet(self):
        self.world.project("fixture/one", "fagenorn/one")
        code, report = verify_checks.guard_policy_fleet(
            self.world.clone, "no-such-branch", environ=self.world.env)
        self.assertEqual((code, report["verdict"]), (75, "absent"))

    def test_a_candidate_without_its_python_tree_is_unreadable(self):
        self.world.project("fixture/one", "fagenorn/one")
        pusher = self.world.tmp / "candidate-pusher"
        self.world.git(pusher, "rm", "-rq", "python")
        self.world.git(pusher, "commit", "--quiet", "-m", "no python")
        self.world.git(pusher, "push", "--quiet", "origin", f"HEAD:refs/heads/{CANDIDATE_BRANCH}")
        code, report = self.world.fleet()
        self.assertEqual((code, report["verdict"], report["side"]), (75, "unreadable", "candidate"))

    def test_the_candidate_home_keeps_the_hosts_forge_and_git_configuration(self):
        home = self.world.tmp / "real-home"
        home.mkdir()
        (home / ".gitconfig").write_text("[user]\n\tname = t\n", encoding="utf-8")
        env = verify_checks._candidate_env({"HOME": str(home), "PYTHONPATH": "host"},
                                           Path("/c/home"), Path("/c/python"))
        self.assertEqual((env["HOME"], env["PYTHONPATH"]), ("/c/home", "/c/python"))
        self.assertEqual(env["GH_CONFIG_DIR"], str(home / ".config/gh"))
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], str(home / ".gitconfig"))
        kept = verify_checks._candidate_env(
            {"HOME": str(home), "GH_CONFIG_DIR": "/gh", "GIT_CONFIG_GLOBAL": "/dev/null"},
            Path("/c/home"), Path("/c/python"))
        self.assertEqual((kept["GH_CONFIG_DIR"], kept["GIT_CONFIG_GLOBAL"]), ("/gh", "/dev/null"))

    def test_the_candidates_code_derives_not_the_hosts(self):
        # A candidate whose guard-policy is broken reads unreadable even though the host's
        # own PYTHONPATH (the world's) holds a working one.
        self.world.project("fixture/one", "fagenorn/one")
        pusher = self.world.tmp / "candidate-pusher"
        (pusher / "python/agent_tools/guard/guard_policy.py").write_text(
            "import sys\nsys.exit(4)\n", encoding="utf-8")
        self.world.git(pusher, "commit", "--quiet", "-am", "break")
        self.world.git(pusher, "push", "--quiet", "origin", f"HEAD:refs/heads/{CANDIDATE_BRANCH}")
        code, report = self.world.fleet()
        self.assertEqual((code, report["verdict"]), (1, "red"), report)
        self.assertEqual(report["rows"][0]["outcome"], "unreadable")


class RegistryAgreementTest(unittest.TestCase):
    OVERRIDE = {"branch": "dev", "default_branch": "main",
                "reason": "default_contract_unresolved"}

    def entries(self, override=None):
        entry = {"project_id": "elevenyellow/nodocom", "root": "/x"}
        if override is not None:
            entry["branch_override"] = override
        return [entry]

    def test_hosts_that_agree_are_green(self):
        for override in (None, self.OVERRIDE):
            with self.subTest(override=override):
                code, report = verify_checks.registry_agreement(
                    {"mbp": self.entries(override), "anis-desktop": self.entries(override)})
                self.assertEqual((code, report["verdict"]), (0, "green"), report)

    def test_the_anis_desktop_entry_without_the_override_is_red(self):
        code, report = verify_checks.registry_agreement(
            {"mbp": self.entries(self.OVERRIDE), "anis-desktop": self.entries()})
        self.assertEqual((code, report["verdict"]), (1, "red"), report)
        [row] = report["rows"]
        self.assertEqual((row["project_id"], row["verdict"]), ("elevenyellow/nodocom", "red"))
        self.assertEqual(row["branch_override"], {"mbp": self.OVERRIDE, "anis-desktop": None})

    def test_a_recorded_intentional_difference_is_green(self):
        code, report = verify_checks.registry_agreement(
            {"mbp": self.entries(self.OVERRIDE), "anis-desktop": self.entries()},
            intentional={"elevenyellow/nodocom"})
        self.assertEqual((code, report["verdict"]), (0, "green"), report)
        self.assertEqual(report["rows"][0]["verdict"], "intentional")

    def test_a_project_on_one_host_is_not_compared(self):
        code, report = verify_checks.registry_agreement(
            {"mbp": self.entries(self.OVERRIDE), "anis-desktop": []})
        self.assertEqual((code, report["verdict"], report["rows"]), (0, "green", []))

    def test_main_reads_registry_files_and_exits_with_the_verdict(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        files = []
        for host, override in (("mbp", self.OVERRIDE), ("anis-desktop", None)):
            path = Path(tmp.name) / f"{host}.json"
            path.write_text(json.dumps({"schema_version": 1, "projects": self.entries(override)}),
                            encoding="utf-8")
            files.append(f"{host}={path}")
        with mock.patch("sys.stdout"):
            red = verify_checks.main(["registry-agreement", "--registry", *files])
            green = verify_checks.main(["registry-agreement", "--registry", *files,
                                        "--intentional", "elevenyellow/nodocom"])
        self.assertEqual((red, green), (1, 0))

    def test_main_refuses_a_missing_registry_file(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        good = Path(tmp.name) / "good.json"
        good.write_text(json.dumps({"schema_version": 1, "projects": self.entries()}),
                        encoding="utf-8")
        with mock.patch("sys.stderr"), mock.patch("sys.stdout"):
            self.assertEqual(verify_checks.main(
                ["registry-agreement", "--registry", f"mbp={good}",
                 f"anis-desktop={Path(tmp.name) / 'absent.json'}"]), 2)

    def test_main_refuses_a_registry_file_the_guard_would_refuse(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bad = Path(tmp.name) / "no-schema.json"
        bad.write_text(json.dumps({"projects": self.entries()}), encoding="utf-8")
        with mock.patch("sys.stderr"), mock.patch("sys.stdout"):
            self.assertEqual(verify_checks.main(
                ["registry-agreement", "--registry", f"mbp={bad}", f"x={bad}"]), 2)

    def test_main_refuses_an_unreadable_registry_file(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bad = Path(tmp.name) / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with mock.patch("sys.stderr"):
            self.assertEqual(verify_checks.main(
                ["registry-agreement", "--registry", f"mbp={bad}", f"x={bad}"]), 2)
