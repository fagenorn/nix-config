"""A fake Railway and GitHub world for the railway-deploy watch suites (issue 582 P4).

`RailwayWorld(test_case)` writes two executables, `gh` and `railway`, into one temporary
`bin/` from a single script and patches `os.environ` until the test's cleanup: `PATH` is that
`bin/` alone, `RAILWAY_WORLD` names the state directory and `NO_PROXY` keeps loopback reads off
any proxy. Each executable logs `{program, argv}` to `calls.jsonl` and answers from
`responses.json`, keyed by `json.dumps([program, *argv])`; an unregistered call exits 64.

The argv literals below are written out, not imported from the adapter, so a test that compares
the adapter's own argv builders with what the world was asked is checking two sources.
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .actions_world import (BASE_TIP, HEAD, HOTFIX, MERGE, OLDER, PR, PR_VIEW, SLUG,
                            commit_argv)

__all__ = ["BASE_TIP", "CONFIG", "GREEN", "HEAD", "HOTFIX", "MERGE", "OLDER", "PR", "PR_VIEW",
           "RED", "RUNNING", "SLUG", "TIMED_OUT", "RailwayWorld", "commit_argv", "deployment"]

CONFIG = {"project": "nodo-prod", "environment": "production", "services": ["api", "admin"]}
GREEN = ("completed", "success")
RED = ("completed", "failure")
TIMED_OUT = ("completed", "timed_out")
RUNNING = ("in_progress", None)
_UNSET = object()

SCRIPT = """#!{python}
import json, os, sys, time
from pathlib import Path

state = Path(os.environ["RAILWAY_WORLD"])
program = os.path.basename(sys.argv[0])
argv = sys.argv[1:]
with open(state / "calls.jsonl", "a", encoding="utf-8") as log:
    log.write(json.dumps({{"program": program, "argv": argv}}) + "\\n")
response = json.loads((state / "responses.json").read_text("utf-8")).get(json.dumps([program, *argv]))
if response is None:
    sys.stderr.write("fake " + program + ": unregistered call\\n")
    sys.exit(64)
time.sleep(response["sleep"])
sys.stdout.write(response["stdout"])
sys.stderr.write(response["stderr"])
sys.exit(response["exit"])
"""


def deployment(id: str, commit: str | None, status: str = "SUCCESS",
               created: str = "2026-11-08T10:00:00Z", branch: str = "main",
               meta: object = _UNSET) -> dict:
    """One `railway deployment list --json` row; `meta=None` writes `"meta": null`."""
    if meta is _UNSET:
        meta = {"commitHash": commit, "branch": branch}
    return {"id": id, "status": status, "createdAt": created, "meta": meta}


class RailwayWorld:
    def __init__(self, test_case: unittest.TestCase) -> None:
        tmp = tempfile.TemporaryDirectory()
        test_case.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.state, self.bin = root / "state", root / "bin"
        self.state.mkdir()
        self.bin.mkdir()
        for program in ("gh", "railway"):
            path = self.bin / program
            path.write_text(SCRIPT.format(python=sys.executable), encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        (self.state / "responses.json").write_text("{}", encoding="utf-8")
        (self.state / "calls.jsonl").write_text("", encoding="utf-8")
        patch = mock.patch.dict(os.environ, {"PATH": str(self.bin),
                                             "RAILWAY_WORLD": str(self.state),
                                             "NO_PROXY": "*", "no_proxy": "*"})
        patch.start()
        test_case.addCleanup(patch.stop)

    def _answer(self, program: str, argv: list[str], stdout: str, exit: int, stderr: str,
                sleep: float) -> None:
        path = self.state / "responses.json"
        responses = json.loads(path.read_text("utf-8"))
        responses[json.dumps([program, *argv])] = {"exit": exit, "stderr": stderr,
                                                   "sleep": sleep, "stdout": stdout}
        path.write_text(json.dumps(responses), encoding="utf-8")

    def respond(self, program: str, argv: list[str], payload: object, *, exit: int = 0,
                stderr: str = "", sleep: float = 0) -> None:
        """Answer `program argv` with `payload` as JSON (or `""` when None)."""
        self._answer(program, argv, "" if payload is None else json.dumps(payload), exit,
                     stderr, sleep)

    def status(self, name: str = "nodo-prod", environments: tuple[str, ...] = ("production",)
               ) -> None:
        self.respond("railway", ["status", "--json"], {
            "name": name,
            "environments": {"edges": [{"node": {"name": env}} for env in environments]}})

    def deployments(self, service: str, *entries: dict, exit: int = 0,
                    stdout: str | None = None, sleep: float = 0) -> None:
        argv = ["deployment", "list", "--service", service, "--environment",
                CONFIG["environment"], "--json"]
        self._answer("railway", argv, json.dumps(list(entries)) if stdout is None else stdout,
                     exit, "", sleep)

    def merged(self, *, state: str = "MERGED", oid: str | None = MERGE,
               parents: tuple[str, ...] = (BASE_TIP, HEAD)) -> None:
        """The release PR as `gh pr view` prints it and, with an `oid`, its merge commit."""
        self.respond("gh", PR_VIEW, {"state": state, "baseRefName": "main",
                                     "mergeCommit": None if oid is None else {"oid": oid}})
        if oid is not None:
            self.respond("gh", commit_argv(oid),
                         {"sha": oid, "parents": [{"sha": p} for p in parents]})

    def check_runs(self, commit: str, *runs: tuple, total: int | None = None,
                   exit: int = 0, stdout: str | None = None) -> None:
        """Every check run of the commit, history included, oldest first.

        A run is `(status, conclusion)` or `(status, conclusion, name)`; its id is its position,
        so a later run of the same name is a re-run that supersedes the earlier one.
        """
        argv = ["api", "-X", "GET", f"repos/{SLUG}/commits/{commit}/check-runs", "-f",
                "per_page=100", "-f", "filter=all"]
        payload = {"total_count": len(runs) if total is None else total,
                   "check_runs": [{"id": index + 1, "name": run[2] if len(run) > 2 else f"job-{index}",
                                   "status": run[0], "conclusion": run[1]}
                                  for index, run in enumerate(runs)]}
        self._answer("gh", argv, json.dumps(payload) if stdout is None else stdout, exit, "", 0)

    def commit_parents(self, commit: str, *parents: str, exit: int = 0,
                       stdout: str | None = None) -> None:
        argv = ["api", "-X", "GET", f"repos/{SLUG}/git/commits/{commit}"]
        payload = {"sha": commit, "parents": [{"sha": p} for p in parents]}
        self._answer("gh", argv, json.dumps(payload) if stdout is None else stdout, exit, "", 0)

    def calls(self, program: str | None = None) -> list[dict]:
        text = (self.state / "calls.jsonl").read_text("utf-8")
        entries = [json.loads(line) for line in text.splitlines()]
        return [e for e in entries if program is None or e["program"] == program]
