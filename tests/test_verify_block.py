import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools import verify_block
from agent_tools.verify_block import count_since

SHA = "a" * 40
SHA2 = "b" * 40

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "home/common/agent-skills/platform-manifest.json"
FIXTURE = REPO_ROOT / "home/common/agent-skills/evals/fixture-repo"
HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
SCRUBBED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
            "GIT_COMMON_DIR", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CEILING_DIRECTORIES")


def cli_env(**extra):
    return {**os.environ, **extra}


def base_block():
    """A host-bound deploy check: the demo block of issue 625."""
    return {"v": 1, "merge": SHA, "checks": [{
        "ac": "AC1", "kind": "evidence", "host": "mbp",
        "when": {"deployed_includes": SHA},
        "run": {"probe": "deployed_includes", "sha": SHA},
    }]}


def run_cli(args, stdin, env=None):
    return subprocess.run([sys.executable, "-m", "agent_tools.verify_pending", *args],
                          input=stdin, text=True, capture_output=True, timeout=60,
                          env=env if env is not None else cli_env())


def lint(block, *args, env=None):
    text = block if isinstance(block, str) else json.dumps(block)
    result = run_cli(["lint", "--input", "-", *args], text, env=env)
    verdict = json.loads(result.stdout) if result.stdout.strip() else None
    return result, verdict


def with_check(**changes):
    block = base_block()
    for key, value in changes.items():
        if value is None:
            block["checks"][0].pop(key, None)
        else:
            block["checks"][0][key] = value
    return block


def with_top(**changes):
    block = base_block()
    block.update(changes)
    return block


ASK = {"ask": "Is the fan quiet under load?"}


class LintTableTest(unittest.TestCase):
    ACCEPT = [
        ("base deploy check", base_block()),
        ("released_includes", with_check(when={"released_includes": SHA})),
        ("ci_run_includes", with_check(when={"ci_run_includes": {"workflow": "nightly", "branch": "main", "sha": SHA}})),
        ("not_before", with_check(when={"not_before": "2026-12-01T00:00:00+00:00"})),
        ("days_after", with_check(when={"deployed_includes": SHA, "days_after": {"event": "deployed", "days": 7}})),
        ("host any", with_check(host="any")),
        ("host list", with_check(host=["mbp", "eleven-m5"])),
        ("human with reason", with_check(kind="human", reason="senses", run=ASK)),
        ("observe and options", with_check(mode="observe", on_fail="ask", on_expire="ask",
                                           expires_after_days=30, effects="paid")),
        ("min_len expect", with_check(expect={"json": [{"pointer": "/runs", "min_len": 3}]})),
        ("equals expect", with_check(expect={"json": [{"pointer": "/ok", "equals": True}]})),
        ("fenced in a comment", "Held for verification.\n\n```verify\n" + json.dumps(base_block()) + "\n```\n"),
        ("ask form", with_check(kind="human", reason="taste", run={"ask": "Does the dock look right on eleven-m5?"})),
        ("act form", with_check(kind="human", reason="hands",
                                run={"act": "just switch", "then": {"probe": "deployed_includes", "sha": SHA}})),
        ("fenced with CRLF line endings",
         "Held.\r\n\r\n```verify\r\n" + json.dumps(base_block()) + "\r\n```\r\n"),
        ("probe released_includes", with_check(run={"probe": "released_includes", "sha": SHA})),
        ("probe ci_run_includes", with_check(run={"probe": "ci_run_includes", "workflow": "CI", "branch": "main", "sha": SHA})),
        ("probe count_since runs", with_check(run={"probe": "count_since", "source": "runs", "workflow": "CI",
                                                   "branch": "main", "since": "2026-11-01T00:00:00Z", "n": 5})),
        ("probe count_since releases", with_check(run={"probe": "count_since", "source": "releases",
                                                       "since": "2026-11-01T00:00:00+00:00", "n": 1})),
    ]
    # Every run that is not a contract command, a committed script or a built-in probe is refused.
    NOT_ALLOWLISTED = [
        ("git", {"tool": "git", "args": ["log", "-n1"]}),
        ("nix", {"tool": "nix", "args": ["build", ".#x"]}),
        ("sh", {"tool": "sh", "args": ["-c", "true"]}),
        ("python -c", {"tool": "python3", "args": ["-c", "print(1)"]}),
        ("gh", {"tool": "gh", "args": ["run", "list"]}),
        ("curl", {"tool": "curl", "args": ["https://example.invalid"]}),
        ("a program key", {"program": "jq"}),
        ("argv", {"argv": ["git", "log"]}),
        ("no form", {"args": []}),
        ("two forms", {"command": "test", "probe": "deployed_includes"}),
    ]
    REFUSE = [
        ("unknown top field", with_top(extra=1), "extra", "unknown_field"),
        ("unknown check field", with_check(bogus=True), "checks[0].bogus", "unknown_field"),
        ("unknown when field", with_check(when={"deployed_includes": SHA, "soon": True}), "checks[0].when.soon", "unknown_field"),
        ("missing merge", {"v": 1, "checks": base_block()["checks"]}, "merge", "missing_field"),
        ("bad v", with_top(v=2), "v", "invalid_value"),
        ("bool v", with_top(v=True), "v", "invalid_value"),
        ("short merge", with_top(merge="abc"), "merge", "invalid_value"),
        ("empty checks", with_top(checks=[]), "checks", "invalid_value"),
        ("empty when", with_check(when={}), "checks[0].when", "invalid_value"),
        ("naive not_before", with_check(when={"not_before": "2026-12-01T00:00:00"}), "checks[0].when.not_before", "invalid_value"),
        ("bad host", with_check(host="MBP"), "checks[0].host", "invalid_value"),
        ("paid any", with_check(effects="paid", host="any"), "checks[0].host", "host_not_concrete"),
        ("paid list", with_check(effects="paid", host=["mbp"]), "checks[0].host", "host_not_concrete"),
        ("live any", with_check(effects="live", host="any"), "checks[0].host", "host_not_concrete"),
        ("live list", with_check(effects="live", host=["mbp", "eleven-m5"]), "checks[0].host", "host_not_concrete"),
        ("human without reason", with_check(kind="human", run=ASK), "checks[0].reason", "reason_required"),
        ("human bad reason", with_check(kind="human", reason="time", run=ASK), "checks[0].reason", "reason_required"),
        ("evidence with reason", with_check(reason="hands"), "checks[0].reason", "reason_not_allowed"),
        ("run not an object", with_check(run="deployed_includes"), "checks[0].run", "invalid_value"),
        ("zero expiry", with_check(expires_after_days=0), "checks[0].expires_after_days", "invalid_value"),
        ("not json", "{not json", "block", "not_json"),
        ("duplicate key", '{"v": 1, "v": 1}', "block", "not_json"),
        ("two fences", "```verify\n{}\n```\n```verify\n{}\n```\n", "block", "fence_count"),
        ("command with spaces", with_check(run={"command": "python3 -c 1"}), "checks[0].run.command", "inline_code"),
        ("command not a string", with_check(run={"command": ["test"]}), "checks[0].run.command", "inline_code"),
        ("command option arg", with_check(run={"command": "test", "args": ["--expr", "1"]}), "checks[0].run.args", "inline_code"),
        # A `just` recipe pastes its parameters into shell lines and runs a surplus argument as a recipe.
        ("command shell text arg", with_check(run={"command": "nix-build", "args": ["mbp", "x; id"]}),
         "checks[0].run.args", "inline_code"),
        ("command surplus recipe arg", with_check(run={"command": "nix-build", "args": ["mbp", "", "switch"]}),
         "checks[0].run.args", "inline_code"),
        ("script args not strings", with_check(run={"script": "scripts/x.py", "at": SHA2, "args": [1]}),
         "checks[0].run.args", "invalid_value"),
        ("deeply nested json", "[" * 200000 + "]" * 200000, "block", "not_json"),
        ("lone surrogate", '{"v": 1, "merge": "' + SHA + '", "checks": [{"ac": "AC1", "kind": "evidence", "host": "mbp", '
                           '"when": {"not_before": "2026-12-01T00:00:00+00:00"}, "run": {"script": "justfile\\udc80", "at": "' + SHA2 + '"}}]}',
         "block", "not_json"),
        ("sha with trailing newline", with_check(run={"probe": "deployed_includes", "sha": SHA + "\n"}), "checks[0].run.sha", "invalid_value"),
        ("host with trailing newline", with_check(host="mbp\n"), "checks[0].host", "invalid_value"),
        ("paid host any with newline", with_check(effects="paid", host="any\n"), "checks[0].host", "invalid_value"),
        ("command id with trailing newline", with_check(run={"command": "test\n"}), "checks[0].run.command", "inline_code"),
        ("script absolute path", with_check(run={"script": "/bin/sh", "at": SHA2}), "checks[0].run.script", "inline_code"),
        ("script escapes repo", with_check(run={"script": "../x.py", "at": SHA2}), "checks[0].run.script", "inline_code"),
        ("script dot segment", with_check(run={"script": "./x.py", "at": SHA2}), "checks[0].run.script", "inline_code"),
        ("script path with NUL", with_check(run={"script": "scripts/check\u0000.py", "at": SHA2}),
         "checks[0].run.script", "inline_code"),
        ("script bad at", with_check(run={"script": "scripts/x.py", "at": "HEAD"}), "checks[0].run.at", "invalid_value"),
        ("inline code key", with_check(run={"command": "test", "code": "print(1)"}), "checks[0].run.code", "unknown_field"),
        ("unknown probe", with_check(run={"probe": "shell", "sha": SHA}), "checks[0].run.probe", "invalid_value"),
        ("probe extra parameter", with_check(run={"probe": "deployed_includes", "sha": SHA, "args": ["x"]}),
         "checks[0].run.args", "unknown_field"),
        ("probe missing parameter", with_check(run={"probe": "released_includes"}), "checks[0].run.sha", "missing_field"),
        ("probe bad sha", with_check(run={"probe": "deployed_includes", "sha": "HEAD"}), "checks[0].run.sha", "invalid_value"),
        ("count runs without workflow", with_check(run={"probe": "count_since", "source": "runs",
                                                         "since": "2026-11-01T00:00:00Z", "n": 1}),
         "checks[0].run.workflow", "missing_field"),
        ("count releases with workflow", with_check(run={"probe": "count_since", "source": "releases", "workflow": "CI",
                                                          "since": "2026-11-01T00:00:00Z", "n": 1}),
         "checks[0].run.workflow", "unknown_field"),
        ("count bad source", with_check(run={"probe": "count_since", "source": "tags",
                                              "since": "2026-11-01T00:00:00Z", "n": 1}), "checks[0].run.source", "invalid_value"),
        ("count naive since", with_check(run={"probe": "count_since", "source": "releases",
                                               "since": "2026-11-01T00:00:00", "n": 1}), "checks[0].run.since", "invalid_value"),
        ("count zero n", with_check(run={"probe": "count_since", "source": "releases",
                                          "since": "2026-11-01T00:00:00Z", "n": 0}), "checks[0].run.n", "invalid_value"),
        ("act then ask", with_check(kind="human", reason="hands", run={"act": "just switch", "then": {"ask": "ok?"}}),
         "checks[0].run.then", "run_form"),
        ("act then python", with_check(kind="human", reason="hands",
                                       run={"act": "x", "then": {"tool": "python3", "args": ["-c", "1"]}}),
         "checks[0].run.then", "run_form"),
        ("approval ask", with_check(kind="human", reason="taste", run={"ask": "Please approve the design spec"}),
         "checks[0].run.ask", "approval_ask"),
        ("adr sign-off ask", with_check(kind="human", reason="taste", run={"ask": "Sign off on ADR 12?"}),
         "checks[0].run.ask", "approval_ask"),
        ("ask on evidence", with_check(run=ASK), "checks[0].kind", "kind_mismatch"),
        ("act on evidence", with_check(run={"act": "just switch", "then": {"probe": "deployed_includes", "sha": SHA}}),
         "checks[0].kind", "kind_mismatch"),
        ("probe on human", with_check(kind="human", reason="hands"), "checks[0].kind", "kind_mismatch"),
        ("command without repo root", with_check(run={"command": "test"}), "checks[0].run.command", "unverified_reference"),
        ("script without repo root", with_check(run={"script": "scripts/check-thing.py", "at": SHA2}),
         "checks[0].run.script", "unverified_reference"),
    ] + [(f"not allowlisted: {name}", with_check(run=run), "checks[0].run", "run_form") for name, run in NOT_ALLOWLISTED]

    def test_accept_rows(self):
        for name, block in self.ACCEPT:
            with self.subTest(name):
                result, verdict = lint(block)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(verdict["ok"], True)
                self.assertEqual(verdict["errors"], [])

    def test_refuse_rows(self):
        for name, block, field, code in self.REFUSE:
            with self.subTest(name):
                result, verdict = lint(block)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertFalse(verdict["ok"])
                self.assertIn((field, code), [(e["field"], e["code"]) for e in verdict["errors"]])


    PR_ARGS = ["--pr-workflow", "CI", "--pr-head", SHA2, "--pr-branch", "issue-1-x"]
    CONTEXT_REFUSE = [
        ("code unmet", base_block(), ["--code-unmet", "AC2"], "code_unmet", "code_unmet"),
        ("awaits the PR head run", with_check(when={"ci_run_includes": {"workflow": "CI", "branch": "issue-1-x", "sha": SHA2}}),
         PR_ARGS, "checks[0].when", "pre_merge_only"),
        ("awaits the PR head on another branch", with_check(when={"ci_run_includes": {"workflow": "CI", "branch": "other", "sha": SHA2}}),
         PR_ARGS, "checks[0].when", "pre_merge_only"),
        ("awaits the PR branch", with_check(when={"ci_run_includes": {"workflow": "CI", "branch": "issue-1-x", "sha": "c" * 40}}),
         PR_ARGS, "checks[0].when", "pre_merge_only"),
    ]
    CONTEXT_ACCEPT = [
        ("same workflow after merge", with_check(when={"ci_run_includes": {"workflow": "CI", "branch": "main", "sha": SHA}}),
         PR_ARGS),
        ("other workflow", with_check(when={"ci_run_includes": {"workflow": "nightly", "branch": "issue-1-x", "sha": SHA2}}),
         PR_ARGS),
        ("ci plus deploy", with_check(when={"deployed_includes": SHA,
                                            "ci_run_includes": {"workflow": "CI", "branch": "issue-1-x", "sha": SHA2}}),
         PR_ARGS),
    ]

    def test_context_refuse_rows(self):
        for name, block, args, field, code in self.CONTEXT_REFUSE:
            with self.subTest(name):
                result, verdict = lint(block, *args)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn((field, code), [(e["field"], e["code"]) for e in verdict["errors"]])

    def test_context_accept_rows(self):
        for name, block, args in self.CONTEXT_ACCEPT:
            with self.subTest(name):
                result, verdict = lint(block, *args)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class ReferenceTest(unittest.TestCase):
    """D9 against a committed copy of the eval fixture project (contract command id `test`)."""

    # An executable script, a non-executable file, a symlink to a program outside the repository,
    # and a symlinked directory that leads to the script.

    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory()
        scratch = Path(cls.scratch.name).resolve()
        home = scratch / "home"
        (home / ".agents" / "share").mkdir(parents=True)
        shutil.copy(MANIFEST, home / ".agents" / "share" / "platform-manifest.json")
        cls.root = scratch / "repo"
        shutil.copytree(FIXTURE, cls.root)
        (cls.root / "scripts").mkdir()
        script = cls.root / "scripts" / "check-thing.py"
        script.write_text("#!/usr/bin/env python3\nraise SystemExit(0)\n", encoding="utf-8")
        script.chmod(0o755)
        (cls.root / "scripts" / "plain.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
        (cls.root / "scripts" / "outside").symlink_to("/bin/sh")
        (cls.root / "linked").symlink_to("scripts")
        cls.env = cli_env(HOME=str(home), **HERMETIC_GIT)
        for name in SCRUBBED:
            cls.env.pop(name, None)
        def git(*args):
            return subprocess.run(["git", "-C", str(cls.root), *args], env=cls.env, check=True,
                                  capture_output=True, text=True).stdout.strip()
        git("init", "-q", "-b", "main")
        git("config", "commit.gpgsign", "false")  # throwaway fixture repo
        git("add", "-A")
        git("commit", "-q", "-m", "fixture")
        cls.head = git("rev-parse", "HEAD")

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def lint_here(self, run):
        return lint(with_check(run=run), "--repo-root", str(self.root), env=self.env)

    def test_accept_rows(self):
        for name, run in (("declared command", {"command": "test"}),
                          ("committed script", {"script": "scripts/check-thing.py", "at": self.head, "args": ["--fast"]})):
            with self.subTest(name):
                result, verdict = self.lint_here(run)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(verdict["errors"], [])

    def test_script_resolves_at_the_merge_without_at(self):
        block = with_check(run={"script": "scripts/check-thing.py"})
        block["merge"] = self.head
        result, verdict = lint(block, "--repo-root", str(self.root), env=self.env)
        self.assertEqual((result.returncode, verdict["errors"]), (0, []), result.stdout + result.stderr)
        block["checks"][0]["run"] = {"script": "scripts/missing.py"}
        result, verdict = lint(block, "--repo-root", str(self.root), env=self.env)
        self.assertIn(("checks[0].run.script", "not_committed"), [(e["field"], e["code"]) for e in verdict["errors"]])
        block["merge"] = SHA2
        block["checks"][0]["run"] = {"script": "scripts/check-thing.py"}
        result, verdict = lint(block, "--repo-root", str(self.root), env=self.env)
        self.assertIn(("merge", "unverified_reference"), [(e["field"], e["code"]) for e in verdict["errors"]])

    def test_refuse_rows(self):
        rows = (("undeclared command", {"command": "not-in-contract"}, "checks[0].run.command", "not_declared"),
                ("git is not a contract command", {"command": "git"}, "checks[0].run.command", "not_declared"),
                ("sh is not a contract command", {"command": "sh"}, "checks[0].run.command", "not_declared"),
                ("script absent at commit", {"script": "scripts/missing.py", "at": self.head}, "checks[0].run.script", "not_committed"),
                ("commit absent", {"script": "scripts/check-thing.py", "at": SHA2}, "checks[0].run.at", "unverified_reference"),
                ("script names a directory", {"script": "scripts", "at": self.head}, "checks[0].run.script", "not_committed"),
                ("script not executable", {"script": "scripts/plain.py", "at": self.head}, "checks[0].run.script", "not_committed"),
                ("symlink to outside", {"script": "scripts/outside", "at": self.head}, "checks[0].run.script", "not_committed"),
                ("through a symlinked directory", {"script": "linked/check-thing.py", "at": self.head},
                 "checks[0].run.script", "not_committed"),
                ("pathspec pattern", {"script": "scripts/check-*.py", "at": self.head}, "checks[0].run.script", "not_committed"),
                ("pathspec magic", {"script": ":(top)scripts/check-thing.py", "at": self.head},
                 "checks[0].run.script", "not_committed"),
                ("script escapes repo", {"script": "../repo/scripts/check-thing.py", "at": self.head},
                 "checks[0].run.script", "inline_code"),
                ("script path with NUL", {"script": "scripts/check\u0000.py", "at": self.head}, "checks[0].run.script", "inline_code"))
        for name, run, field, code in rows:
            with self.subTest(name):
                result, verdict = self.lint_here(run)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn((field, code), [(e["field"], e["code"]) for e in verdict["errors"]])

    def test_repo_root_not_a_repo_is_usage(self):
        with tempfile.TemporaryDirectory() as temp:
            result, verdict = lint(base_block(), "--repo-root", temp, env=self.env)
        self.assertEqual((result.returncode, verdict), (2, None))


class CommandShapeTest(unittest.TestCase):
    def test_unreadable_input_is_usage(self):
        result = run_cli(["lint", "--input", "/nonexistent/verify-block.json"], "")
        self.assertEqual(result.returncode, 2)

    def test_verdict_is_one_sorted_json_line(self):
        result, verdict = lint(base_block())
        self.assertEqual(result.stdout, json.dumps(verdict, sort_keys=True) + "\n")

    def test_pr_workflow_without_pr_revision_is_usage(self):
        result, verdict = lint(base_block(), "--pr-workflow", "CI")
        self.assertEqual((result.returncode, verdict), (2, None))
        result, verdict = lint(base_block(), "--pr-workflow", "CI", "--pr-head", "abc")
        self.assertEqual((result.returncode, verdict), (2, None))


def git_repo(directory, with_flake):
    env = {**os.environ, **HERMETIC_GIT}
    def git(*args):
        return subprocess.run(["git", "-C", str(directory), *args], env=env, check=True,
                              capture_output=True, text=True).stdout.strip()
    git("init", "-q")
    (Path(directory) / ("flake.nix" if with_flake else "README")).write_text("{}\n")
    git("add", "-A")
    git("-c", "commit.gpgsign=false", "commit", "-q", "-m", "fixture")
    return git("rev-parse", "HEAD")


def deploy_block(sha):
    block = base_block()
    block["merge"] = sha
    block["checks"][0]["when"] = {"deployed_includes": sha}
    return block


class WarningTableTest(unittest.TestCase):
    def assert_warns(self, block, args, field, code):
        result, verdict = lint(block, *args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(verdict["ok"])
        self.assertIn((field, code), [(w["field"], w["code"]) for w in verdict["warnings"]])
        return verdict

    def test_ask_in_blocking_issue_warns(self):
        block = with_check(kind="human", reason="senses", run=ASK)
        self.assert_warns(block, ["--blocks", "630"], "checks[0].run.ask", "ask_blocks_issues")

    def test_deploy_check_without_flake_warns(self):
        with tempfile.TemporaryDirectory() as temp:
            sha = git_repo(temp, with_flake=False)
            self.assert_warns(deploy_block(sha), ["--repo-root", temp],
                              "checks[0].when.deployed_includes", "no_flake_at_merge")

    def test_deploy_check_with_flake_is_silent(self):
        with tempfile.TemporaryDirectory() as temp:
            sha = git_repo(temp, with_flake=True)
            result, verdict = lint(deploy_block(sha), "--repo-root", temp)
            self.assertEqual((result.returncode, verdict["warnings"]), (0, []))

    def test_merge_absent_from_repo_is_not_a_missing_flake(self):
        with tempfile.TemporaryDirectory() as temp:
            git_repo(temp, with_flake=True)
            verdict = self.assert_warns(deploy_block(SHA), ["--repo-root", temp], "merge", "merge_not_found")
            self.assertNotIn("no_flake_at_merge", [w["code"] for w in verdict["warnings"]])

    def test_no_blocks_no_ask_warning(self):
        block = with_check(kind="human", reason="senses", run=ASK)
        result, verdict = lint(block)
        self.assertEqual((result.returncode, verdict["warnings"]), (0, []))


T = "2026-11-01T00:00:00Z"
RUNS = [{"createdAt": "2026-10-31T23:00:00Z"}, {"createdAt": "2026-11-01T00:00:00Z"},
        {"createdAt": "2026-11-02T08:00:00Z"}, {"createdAt": "2026-11-03T08:00:00+01:00"}]
RELEASES = [{"publishedAt": "2026-11-04T10:00:00Z"}, {"publishedAt": "2026-10-01T10:00:00Z"}]


class CountSinceTest(unittest.TestCase):
    def test_runs_below_and_at_n(self):
        stamps = [r["createdAt"] for r in RUNS]
        self.assertEqual(count_since(stamps, T, 3), 75)
        self.assertEqual(count_since(stamps, T, 2), 0)

    def test_releases_below_and_at_n(self):
        stamps = [r["publishedAt"] for r in RELEASES]
        self.assertEqual(count_since(stamps, T, 2), 75)
        self.assertEqual(count_since(stamps, T, 1), 0)

    def test_bad_inputs_raise(self):
        for stamps, n in ((["2026-11-02T00:00:00"], 1), (["soon"], 1), ([], 0), ([], True)):
            with self.subTest(stamps=stamps, n=n), self.assertRaises(ValueError):
                count_since(stamps, T, n)

    def test_command_reads_run_and_release_lists(self):
        runs = run_cli(["count-since", "--input", "-", "--since", T, "--n", "3"], json.dumps(RUNS))
        self.assertEqual((runs.returncode, json.loads(runs.stdout)), (75, {"count": 2, "needed": 3}))
        releases = run_cli(["count-since", "--input", "-", "--since", T, "--n", "1", "--key", "publishedAt"],
                           json.dumps(RELEASES))
        self.assertEqual((releases.returncode, json.loads(releases.stdout)), (0, {"count": 1, "needed": 1}))

    def test_command_bad_input_is_usage(self):
        result = run_cli(["count-since", "--input", "-", "--since", T, "--n", "1"], json.dumps([{"other": T}]))
        self.assertEqual(result.returncode, 2)


class DocumentedExampleTest(unittest.TestCase):
    def example(self):
        return verify_block.__doc__

    def test_documented_example_is_accepted(self):
        result, verdict = lint(self.example())
        self.assertEqual((result.returncode, verdict["ok"]), (0, True), result.stdout)

    def test_example_with_inline_python_is_refused_naming_the_field(self):
        block = json.loads(self.example().split("```verify\n", 1)[1].split("\n```", 1)[0])
        block["checks"][0]["run"] = {"tool": "python3", "args": ["-c", "print(1)"]}
        result, verdict = lint(block)
        self.assertEqual(result.returncode, 1)
        self.assertIn(("checks[0].run", "run_form"),
                      [(e["field"], e["code"]) for e in verdict["errors"]])


if __name__ == "__main__":
    unittest.main()
