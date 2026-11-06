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


class CommandShapeTest(unittest.TestCase):
    def test_unreadable_input_is_usage(self):
        result = run_cli(["lint", "--input", "/nonexistent/verify-block.json"], "")
        self.assertEqual(result.returncode, 2)

    def test_verdict_is_one_sorted_json_line(self):
        result, verdict = lint(base_block())
        self.assertEqual(result.stdout, json.dumps(verdict, sort_keys=True) + "\n")


if __name__ == "__main__":
    unittest.main()
