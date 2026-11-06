import copy
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SHA = "a" * 40
SHA2 = "b" * 40
STUB_TOOLS = ("resolve-project", "jq")
STUB_BIN = None

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "home/common/agent-skills/platform-manifest.json"
FIXTURE = REPO_ROOT / "home/common/agent-skills/evals/fixture-repo"
HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
SCRUBBED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
            "GIT_COMMON_DIR", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CEILING_DIRECTORIES")


def setUpModule():
    """A `bin` of stub executables prepended to PATH, so "installed" (D9) is deterministic."""
    global STUB_BIN
    STUB_BIN = tempfile.mkdtemp(prefix="verify-block-bin-")
    for name in STUB_TOOLS:
        path = Path(STUB_BIN) / name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def tearDownModule():
    shutil.rmtree(STUB_BIN, ignore_errors=True)


def cli_env(**extra):
    env = {**os.environ, **extra}
    env["PATH"] = STUB_BIN + os.pathsep + env.get("PATH", "")
    return env


def base_block():
    """A host-bound deploy check: the demo block of issue 625."""
    return {"v": 1, "merge": SHA, "checks": [{
        "ac": "AC1", "kind": "evidence", "host": "mbp",
        "when": {"deployed_includes": SHA},
        "run": {"tool": "resolve-project", "args": ["platform-status"]},
        "expect": {"json": [{"pointer": "/platform/platform_version", "equals": "1.1.0"}]},
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
        ("fenced in a comment", "Held for verification.\n\n```verify\n" + json.dumps(base_block()) + "\n```\n"),
        ("ask form", with_check(kind="human", reason="taste", run={"ask": "Does the dock look right on eleven-m5?"})),
        ("act form", with_check(kind="human", reason="hands",
                                run={"act": "just switch", "then": {"tool": "resolve-project", "args": ["platform-status"]}})),
        ("jq is not an interpreter", with_check(run={"tool": "jq", "args": ["-e", ".ok"]})),
        ("jq --arg is not Nix code", with_check(run={"tool": "jq", "args": ["--arg", "x", "y", ".x"]})),
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
        ("run not an object", with_check(run="resolve-project"), "checks[0].run", "invalid_value"),
        ("zero expiry", with_check(expires_after_days=0), "checks[0].expires_after_days", "invalid_value"),
        ("not json", "{not json", "block", "not_json"),
        ("duplicate key", '{"v": 1, "v": 1}', "block", "not_json"),
        ("two fences", "```verify\n{}\n```\n```verify\n{}\n```\n", "block", "fence_count"),
        ("python3 -c", with_check(run={"tool": "python3", "args": ["-c", "print(1)"]}), "checks[0].run.tool", "inline_code"),
        ("bash", with_check(run={"tool": "bash", "args": ["-c", "true"]}), "checks[0].run.tool", "inline_code"),
        ("tool path", with_check(run={"tool": "/tmp/x.sh"}), "checks[0].run.tool", "inline_code"),
        ("timeout wrapper", with_check(run={"tool": "timeout", "args": ["60", "python3", "-c", "print(1)"]}),
         "checks[0].run.tool", "inline_code"),
        ("wrapped interpreter in args", with_check(run={"tool": "timeout", "args": ["60", "python3", "-c", "print(1)"]}),
         "checks[0].run.args", "inline_code"),
        ("unlisted runner, interpreter in args", with_check(run={"tool": "xcrun", "args": ["/usr/bin/python3", "-c", "print(1)"]}),
         "checks[0].run.args", "inline_code"),
        ("find -exec", with_check(run={"tool": "find", "args": [".", "-exec", "true", ";"]}), "checks[0].run.args", "inline_code"),
        ("find -exec bash", with_check(run={"tool": "find", "args": [".", "-exec", "bash", "-c", "x", ";"]}),
         "checks[0].run.args", "inline_code"),
        ("nix expr", with_check(run={"tool": "nix", "args": ["eval", "--expr", "1"]}), "checks[0].run.args", "inline_code"),
        ("nix expr joined", with_check(run={"tool": "nix", "args": ["eval", "--expr=1"]}), "checks[0].run.args", "inline_code"),
        ("nix apply", with_check(run={"tool": "nix", "args": ["eval", ".#x", "--apply", "f: f"]}), "checks[0].run.args", "inline_code"),
        ("nix arg", with_check(run={"tool": "nix-build", "args": ["--arg", "x", "import ./evil.nix"]}), "checks[0].run.args", "inline_code"),
        ("nix run remote", with_check(run={"tool": "nix", "args": ["run", "github:someone/flake"]}), "checks[0].run.args", "inline_code"),
        ("nix build remote", with_check(run={"tool": "nix", "args": ["build", "github:someone/flake#x"]}), "checks[0].run.args", "inline_code"),
        ("nix run local", with_check(run={"tool": "nix", "args": ["run", ".#x"]}), "checks[0].run.args", "inline_code"),
        ("git config command", with_check(run={"tool": "git", "args": ["-c", "alias.x=!true", "x"]}), "checks[0].run.args", "inline_code"),
        ("tool is a list", with_check(run={"tool": ["nix"], "args": []}), "checks[0].run.tool", "invalid_value"),
        ("tool is an object", with_check(run={"tool": {}, "args": ["x"]}), "checks[0].run.tool", "invalid_value"),
        ("tool name in other case", with_check(run={"tool": "Bash", "args": ["-c", "curl x | Sh"]}),
         "checks[0].run.tool", "inline_code"),
        ("interpreter arg in other case", with_check(run={"tool": "xcrun", "args": ["PYTHON3", "-c", "1"]}),
         "checks[0].run.args", "inline_code"),
        ("shell arg path in other case", with_check(run={"tool": "xcrun", "args": ["/usr/bin/Bash"]}),
         "checks[0].run.args", "inline_code"),
        ("nix run after value option", with_check(run={"tool": "nix", "args": ["--option", "sandbox", "false", "run", "nixpkgs#hello"]}),
         "checks[0].run.args", "inline_code"),
        ("command with spaces", with_check(run={"command": "python3 -c 1"}), "checks[0].run.command", "inline_code"),
        ("script without sha", with_check(run={"script": "scripts/x.py"}), "checks[0].run.at", "missing_field"),
        ("script escapes repo", with_check(run={"script": "../x.py", "at": SHA2}), "checks[0].run.script", "invalid_value"),
        ("two forms", with_check(run={"tool": "jq", "command": "test"}), "checks[0].run", "run_form"),
        ("no form", with_check(run={"args": []}), "checks[0].run", "run_form"),
        ("inline code key", with_check(run={"tool": "jq", "code": "print(1)"}), "checks[0].run.code", "unknown_field"),
        ("act then ask", with_check(kind="human", reason="hands", run={"act": "just switch", "then": {"ask": "ok?"}}),
         "checks[0].run.then", "run_form"),
        ("act then python", with_check(kind="human", reason="hands",
                                       run={"act": "x", "then": {"tool": "python3", "args": ["-c", "1"]}}),
         "checks[0].run.then.tool", "inline_code"),
        ("approval ask", with_check(kind="human", reason="taste", run={"ask": "Please approve the design spec"}),
         "checks[0].run.ask", "approval_ask"),
        ("adr sign-off ask", with_check(kind="human", reason="taste", run={"ask": "Sign off on ADR 12?"}),
         "checks[0].run.ask", "approval_ask"),
        ("ask on evidence", with_check(run=ASK), "checks[0].kind", "kind_mismatch"),
        ("act on evidence", with_check(run={"act": "just switch", "then": {"tool": "jq", "args": [".ok"]}}),
         "checks[0].kind", "kind_mismatch"),
        ("tool on human", with_check(kind="human", reason="hands"), "checks[0].kind", "kind_mismatch"),
        ("tool not installed", with_check(run={"tool": "no-such-tool-625"}), "checks[0].run.tool", "not_installed"),
        ("command without repo root", with_check(run={"command": "test"}), "checks[0].run.command", "unverified_reference"),
        ("script without repo root", with_check(run={"script": "scripts/check-thing.py", "at": SHA2}),
         "checks[0].run.script", "unverified_reference"),
    ]

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


class ReferenceTest(unittest.TestCase):
    """D9 against a committed copy of the eval fixture project (contract command id `test`)."""

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
        (cls.root / "scripts" / "check-thing.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
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

    def test_refuse_rows(self):
        rows = (("undeclared command", {"command": "not-in-contract"}, "checks[0].run.command", "not_declared"),
                ("script absent at commit", {"script": "scripts/missing.py", "at": self.head}, "checks[0].run.script", "not_committed"),
                ("commit absent", {"script": "scripts/check-thing.py", "at": SHA2}, "checks[0].run.at", "unverified_reference"))
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


if __name__ == "__main__":
    unittest.main()
