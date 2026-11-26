"""`pr-green` and `verify_checks.pr_green_state`: whether a pull request's head is green, and since when (#1433)."""
import contextlib
import io
import json
import unittest
from unittest import mock

from agent_tools.system import forge_api
from agent_tools.verification import pr_green, verify_checks

REPO = "elevenyellow/nodocom"
PR = 41
SHA = "c" * 40
PULL = f"repos/{REPO}/pulls/{PR}"
PROTECTION = f"repos/{REPO}/branches/main/protection/required_status_checks"
RULES = f"repos/{REPO}/rules/branches/main?per_page=100"
RUNS = f"repos/{REPO}/commits/{SHA}/check-runs?per_page=100"
STATUSES = f"repos/{REPO}/commits/{SHA}/statuses?per_page=100"


def run(name, conclusion="success", completed="2026-11-21T12:40:00Z", status="completed", app_id=None):
    found = {"name": name, "status": status, "conclusion": conclusion, "completed_at": completed}
    if app_id is not None:
        found["app"] = {"id": app_id}
    return found


def status(context, state="success", updated="2026-11-21T12:45:00Z"):
    return {"context": context, "state": state, "updated_at": updated}


def ruleset(*contexts):
    """The branch rules of one ruleset requiring each (context, integration_id) of `contexts`."""
    return {"type": "required_status_checks", "ruleset_source_type": "Repository", "ruleset_id": 3,
            "parameters": {"required_status_checks": [
                {"context": c, **({"integration_id": a} if a is not None else {})} for c, a in contexts]}}


def checks(runs=(), statuses=(), required=("ci",), required_checks=None, rules=()):
    """The canned reads of one pull request; any read not listed fails the test."""
    gets = {
        PULL: {"head": {"sha": SHA}, "base": {"ref": "main"}},
        PROTECTION: {"checks": required_checks if required_checks is not None
                     else [{"context": c} for c in required]},
    }
    pages = {
        RUNS: [{"total_count": len(runs), "check_runs": list(runs)}],
        STATUSES: [list(statuses)],
        RULES: [list(rules)],
    }
    return gets, pages


def patched(gets, pages):
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


def state_of(runs=(), statuses=(), **kwargs):
    get, pages = patched(*checks(runs, statuses, **kwargs))
    with get, pages:
        return verify_checks.pr_green_state(REPO, PR)


def command(argv, runs=(), statuses=(), **kwargs):
    """(exit, stdout JSON or None, stderr) of `pr-green` over the canned reads."""
    get, pages = patched(*checks(runs, statuses, **kwargs))
    out, err = io.StringIO(), io.StringIO()
    with get, pages, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = pr_green.main(argv)
    return code, (json.loads(out.getvalue()) if out.getvalue() else None), err.getvalue()


ARGV = ["--repo", REPO, "--pr", str(PR)]


class PrGreenStateTest(unittest.TestCase):
    def test_every_check_passed_is_green_at_the_latest_completion(self):
        runs = [run("ci", "success", "2026-11-21T12:40:00Z"),
                run("lint", "neutral", "2026-11-21T12:52:30Z")]
        found = [status("legacy", "success", "2026-11-21T12:45:00Z")]
        state, report = state_of(runs, found)
        self.assertEqual(state, "green")
        self.assertEqual(report, {"pr": PR, "head": SHA, "base": "main",
                                  "green_at": "2026-11-21T12:52:30Z",
                                  "failing": [], "pending": [], "missing": []})
        code, printed, _ = command(ARGV, runs, found)
        self.assertEqual(code, 0)
        self.assertEqual(printed, {**report, "state": "green"})

    def test_a_status_may_be_the_latest_completion(self):
        runs = [run("ci", "success", "2026-11-21T12:40:00Z")]
        found = [status("legacy", "success", "2026-11-21T13:01:07Z")]
        self.assertEqual(state_of(runs, found)[1]["green_at"], "2026-11-21T13:01:07Z")

    def test_a_skipped_run_is_green(self):
        state, _ = state_of([run("ci"), run("docs", "skipped")])
        self.assertEqual(state, "green")

    def test_a_failed_run_is_failed(self):
        state, report = state_of([run("ci"), run("lint", "failure")])
        self.assertEqual((state, report["failing"], report["green_at"]), ("failed", ["lint"], None))
        code, printed, _ = command(ARGV, [run("ci"), run("lint", "failure")])
        self.assertEqual((code, printed["state"]), (1, "failed"))

    def test_a_running_check_is_pending(self):
        runs = [run("ci"), run("lint", None, None, status="in_progress")]
        state, report = state_of(runs)
        self.assertEqual((state, report["pending"]), ("pending", ["lint"]))
        code, printed, _ = command(ARGV, runs)
        self.assertEqual((code, printed["state"]), (75, "pending"))

    def test_a_pending_status_context_is_pending(self):
        state, report = state_of([run("ci")], [status("deploy", "pending")])
        self.assertEqual((state, report["pending"]), ("pending", ["deploy"]))

    def test_a_failed_status_context_is_failed(self):
        for bad in ("failure", "error"):
            state, report = state_of([run("ci")], [status("deploy", bad)])
            self.assertEqual((state, report["failing"]), ("failed", ["deploy"]))

    def test_a_failure_outranks_a_pending_check(self):
        runs = [run("ci", "failure"), run("lint", None, None, status="queued")]
        state, report = state_of(runs)
        self.assertEqual((state, report["failing"], report["pending"]),
                         ("failed", ["ci"], ["lint"]))

    def test_the_latest_status_of_a_context_decides(self):
        found = [status("deploy", "success", "2026-11-21T12:05:00Z"),
                 status("deploy", "failure", "2026-11-21T12:00:00Z")]
        state, report = state_of([run("ci")], found)
        self.assertEqual(state, "green")
        self.assertEqual(report["green_at"], "2026-11-21T12:40:00Z")

    def test_a_later_failure_replaces_an_earlier_success(self):
        found = [status("deploy", "success", "2026-11-21T12:00:00Z"),
                 status("deploy", "failure", "2026-11-21T12:05:00Z")]
        self.assertEqual(state_of([run("ci")], found)[0], "failed")

    def test_a_missing_required_check_is_pending(self):
        state, report = state_of([run("lint")], required=("ci",))
        self.assertEqual((state, report["missing"]), ("pending", ["ci"]))

    def test_a_required_check_met_by_a_status_is_not_missing(self):
        state, report = state_of([run("lint")], [status("ci")], required=("ci",))
        self.assertEqual((state, report["missing"]), ("green", []))

    def test_a_required_check_bound_to_an_app_needs_that_app(self):
        bound = [{"context": "ci", "app_id": 15368}]
        other = state_of([run("ci", app_id=99)], required_checks=bound)
        self.assertEqual((other[0], other[1]["missing"]), ("pending", ["ci"]))
        own = state_of([run("ci", app_id=15368)], required_checks=bound)
        self.assertEqual((own[0], own[1]["missing"]), ("green", []))

    def test_a_check_only_a_ruleset_requires_is_missing_when_it_never_ran(self):
        rules = [{"type": "pull_request", "parameters": {}}, ruleset(("lint", None))]
        state, report = state_of([run("ci")], required=("ci",), rules=rules)
        self.assertEqual((state, report["missing"], report["green_at"]), ("pending", ["lint"], None))
        state, report = state_of([run("ci"), run("lint")], required=("ci",), rules=rules)
        self.assertEqual((state, report["missing"]), ("green", []))

    def test_a_ruleset_check_bound_to_an_app_needs_that_app(self):
        rules = [ruleset(("lint", 15368))]
        other = state_of([run("ci"), run("lint", app_id=99)], rules=rules)
        self.assertEqual((other[0], other[1]["missing"]), ("pending", ["lint"]))
        own = state_of([run("ci"), run("lint", app_id=15368)], rules=rules)
        self.assertEqual((own[0], own[1]["missing"]), ("green", []))

    def test_a_malformed_rules_listing_is_a_forge_error(self):
        for bad in ([{"not": "a page"}], [[ruleset(("lint", "x"))]]):
            gets, pages = checks([run("ci")])
            pages[RULES] = bad
            get, paged = patched(gets, pages)
            with self.subTest(bad=bad), get, paged, self.assertRaises(forge_api.ForgeError):
                verify_checks.pr_green_state(REPO, PR)

    def test_a_required_check_that_concluded_skipped_or_neutral_is_met(self):
        for conclusion in ("skipped", "neutral"):
            with self.subTest(conclusion=conclusion):
                state, report = state_of([run("ci", conclusion)], required=("ci",))
                self.assertEqual((state, report["missing"], report["pending"]), ("green", [], []))
                state, report = state_of([run("ci"), run("lint", conclusion)], rules=[ruleset(("lint", None))])
                self.assertEqual((state, report["missing"]), ("green", []))

    def test_no_check_at_all_is_pending(self):
        state, report = state_of([], [], required=())
        self.assertEqual((state, report["green_at"]), ("pending", None))
        self.assertTrue(report["pending"])
        code, printed, _ = command(ARGV, [], [], required=())
        self.assertEqual((code, printed["state"]), (75, "pending"))

    def test_a_time_with_a_fraction_is_not_rounded(self):
        state, report = state_of([run("ci", completed="2026-11-21T12:40:00.250Z")])
        self.assertEqual(state, "green")
        self.assertEqual(report["green_at"], "2026-11-21T12:40:00.250000Z")

    def test_a_malformed_time_is_a_forge_error(self):
        with self.assertRaises(forge_api.ForgeError) as raised:
            state_of([run("ci", completed="yesterday")])
        self.assertEqual(raised.exception.code, "payload_invalid")

    def test_a_truncated_check_run_listing_is_a_forge_error(self):
        gets, pages = checks([run("ci")])
        pages[RUNS] = [{"total_count": 2, "check_runs": [run("ci")]}]
        get, paged = patched(gets, pages)
        with get, paged, self.assertRaises(forge_api.ForgeError):
            verify_checks.pr_green_state(REPO, PR)

    def test_a_pull_request_without_a_head_is_a_forge_error(self):
        gets, pages = checks([run("ci")])
        gets[PULL] = {"head": {}, "base": {"ref": "main"}}
        get, paged = patched(gets, pages)
        with get, paged, self.assertRaises(forge_api.ForgeError):
            verify_checks.pr_green_state(REPO, PR)


class PrGreenCommandTest(unittest.TestCase):
    def test_a_bad_repo_or_pr_is_a_usage_error(self):
        for argv in (["--repo", "nope", "--pr", "3"], ["--repo", REPO, "--pr", "0"],
                     ["--repo", REPO, "--pr", "-2"], ["--repo", REPO, "--pr", "x"],
                     ["--repo", REPO], ["--pr", "3"]):
            with self.subTest(argv=argv):
                with mock.patch.object(forge_api, "api_get", side_effect=AssertionError("read")), \
                        mock.patch.object(forge_api, "api_pages", side_effect=AssertionError("read")), \
                        contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        pr_green.main(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_a_forge_error_is_exit_2_with_one_stderr_line(self):
        err = io.StringIO()
        with mock.patch.object(forge_api, "api_get",
                               side_effect=forge_api.ForgeError("gh_failed", "boom")), \
                contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(err):
            code = pr_green.main(ARGV)
        self.assertEqual((code, out.getvalue()), (2, ""))
        self.assertEqual(len(err.getvalue().splitlines()), 1)
        self.assertIn("gh_failed", err.getvalue())


if __name__ == "__main__":
    unittest.main()
