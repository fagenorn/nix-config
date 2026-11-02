"""A fake GitHub Actions world for the deploy-watch suites (issue 465 D12, D16).

`ActionsWorld(test_case)` writes one executable `gh` into a temporary `bin/` and patches
`os.environ` until the test's cleanup: `PATH` is that `bin/` alone, `GITHUB_TOKEN` is a
harness token, `ACTIONS_WORLD` names the state directory, and `NO_PROXY` keeps loopback
reads off any proxy. The `gh` logs `{argv, token_visible}` to `calls.jsonl` and answers from
`responses.json`, keyed by `json.dumps(argv)`; an unregistered call exits 64. Unlike
`ForgeWorld`'s, this `gh` never refuses a visible token, so a test can observe that the
credential binding, not the adapter, decides what the child sees.

The world also serves HTTP on `127.0.0.1` from a `ThreadingHTTPServer` in a daemon thread:
`health(...)` sets one route's status, body, headers, delay and body delay, an unset route answers 404,
and `requests` lists every request's path and headers in arrival order.
"""
import http.server
import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

SLUG = "fagenorn/nix-config"
CONFIG = {"workflow": "deploy.yml", "branch": "main", "services": ["jarbird", "jarbird-caddy"],
          "health_url": "https://jarbird.com/health", "health_commit_field": "commit"}
RUN_LIST = ["run", "list", "--repo", SLUG, "--workflow", "deploy.yml", "--branch", "main",
            "--limit", "5", "--json", "databaseId,status,conclusion,headSha,headBranch,createdAt"]
MERGE = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
OLDER = "0f1e2d3c4b5a69788796a5b4c3d2e1f001234567"
HOTFIX = "9a8b7c6d5e4f30211203f4e5d6c7b8a998765432"

SCRIPT = """#!{python}
import json, os, sys, time
from pathlib import Path

state = Path(os.environ["ACTIONS_WORLD"])
argv = sys.argv[1:]
token = bool(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))
with open(state / "calls.jsonl", "a", encoding="utf-8") as log:
    log.write(json.dumps({{"argv": argv, "token_visible": token}}) + "\\n")
response = json.loads((state / "responses.json").read_text("utf-8")).get(json.dumps(argv))
if response is None:
    sys.stderr.write("fake gh: unregistered call\\n")
    sys.exit(64)
time.sleep(response["sleep"])
sys.stdout.write(response["stdout"])
sys.stderr.write(response["stderr"])
sys.exit(response["exit"])
"""


def run(run_id: int, commit: str, *, status: str = "completed", conclusion: str = "success",
        created: str = "2026-10-27T10:00:00Z", branch: str = "main") -> dict:
    """One `gh run list` entry as gh prints it: an unfinished run has an empty conclusion."""
    return {"databaseId": run_id, "status": status,
            "conclusion": conclusion if status == "completed" else "",
            "headSha": commit, "headBranch": branch, "createdAt": created}


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: object, client_address: object) -> None:
        """A client that closed early (the adapter's body cap, a timeout) is not an error."""
        if not isinstance(sys.exc_info()[1], ConnectionError):
            super().handle_error(request, client_address)


class ActionsWorld:
    def __init__(self, test_case: unittest.TestCase) -> None:
        tmp = tempfile.TemporaryDirectory()
        test_case.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.state, self.bin = root / "state", root / "bin"
        self.state.mkdir()
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(SCRIPT.format(python=sys.executable), encoding="utf-8")
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        (self.state / "responses.json").write_text("{}", encoding="utf-8")
        (self.state / "calls.jsonl").write_text("", encoding="utf-8")
        self.routes: dict[str, tuple[int, bytes, dict[str, str], float, float]] = {}
        self.requests: list[dict] = []
        world = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                world.requests.append({"path": self.path, "headers": dict(self.headers)})
                status, body, headers, delay, body_delay = world.routes.get(
                    self.path, (404, b"", {}, 0, 0))
                time.sleep(delay)
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                time.sleep(body_delay)
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                pass

        self.server = _Server(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        test_case.addCleanup(self.server.server_close)
        test_case.addCleanup(self.server.shutdown)
        patch = mock.patch.dict(os.environ, self.env())
        patch.start()
        test_case.addCleanup(patch.stop)

    def env(self) -> dict[str, str]:
        """The environment that reaches this world: its `bin/` as `PATH`, its state, a token."""
        return {"PATH": str(self.bin), "ACTIONS_WORLD": str(self.state),
                "GITHUB_TOKEN": "harness-token", "NO_PROXY": "*", "no_proxy": "*"}

    def url(self, path: str = "/health") -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}{path}"

    def runs(self, *entries: dict, exit: int = 0, stdout: str | None = None, stderr: str = "",
             sleep: float = 0) -> None:
        """Answer the issue's exact `gh run list` argv with `entries` (or `stdout` verbatim)."""
        response = {"exit": exit, "stdout": json.dumps(list(entries)) if stdout is None else stdout,
                    "stderr": stderr, "sleep": sleep}
        (self.state / "responses.json").write_text(json.dumps({json.dumps(RUN_LIST): response}),
                                                   encoding="utf-8")

    def health(self, status: int = 200, body: bytes | None = None, *, commit: str = MERGE,
               path: str = "/health", headers: dict[str, str] | None = None,
               delay: float = 0, body_delay: float = 0) -> None:
        """Serve `path` (default: 200 JSON with `commit`), after `delay` and then `body_delay`."""
        payload = json.dumps({"status": "ok", "commit": commit}).encode() if body is None else body
        self.routes[path] = (status, payload, headers or {"Content-Type": "application/json"},
                             delay, body_delay)

    def calls(self) -> list[dict]:
        text = (self.state / "calls.jsonl").read_text("utf-8")
        return [json.loads(line) for line in text.splitlines()]
