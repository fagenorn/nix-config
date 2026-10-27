# Task 1: The `github-actions-health` adapter in the closed registry

Spec § The adapter, § The reads, § Classification and § Test seams; per D2, D6–D10, D14, D16. After this task:

- `release_adapter.REGISTRY` maps `github-actions-health` to a new module whose `inspect` returns one closed effect observation per deploy request;
- `CONFIG_TYPES` gains `string_list`;
- `watch_operation` names a descriptor's watch operation.

No project binding reaches the adapter yet (Task 2), and no command does except the existing project-free `release adapter inspect`.

**Files:**
- Create: `python/agent_tools/actions_health_adapter.py`
- Modify: `python/agent_tools/release_adapter.py` (`CONFIG_TYPES`, new `_is_string_list`, `config_problems`, new `watch_operation`, the `agent_tools` import line, `REGISTRY`)
- Create: `tests/actions_world.py`
- Test: `tests/test_actions_health_adapter.py` (create)
- Modify: `tests/test_release_grammar.py` (`DescriptorTest.test_registry_is_closed` only)
- Modify: `justfile` (the `agent-workflow-tests` member list)
- Modify: `python/README.md` (§ Release adapters)

**Interfaces:**
- Consumes:
  - `agent_tools.canonical.reject_duplicate_keys` and `reject_nonfinite_literal`;
  - `release_adapter.descriptor_problems`, `effect_observation_problems`, `predicate_observation_problems`, `invoke_result_problems` and `build_descriptors` (all unchanged).
- Produces:
  - `actions_health_adapter.describe() -> dict[str, Any]` (fresh on every call), `inspect(request: Any) -> dict[str, Any]` and `invoke(request: Any) -> dict[str, Any]`.
  - Module constants: `COLLECTION_BUDGET_SECONDS = 30`, `DETAIL_LIMIT = 240`, `HEALTH_BODY_LIMIT = 65536`, `RUN_LIMIT = 5`, `RUN_FIELDS = "databaseId,status,conclusion,headSha,headBranch,createdAt"`, `USER_AGENT = "agent-tools-github-actions-health/1.0.0"`, and `CONFIG_MEMBERS`, the ordered five-member dict below.
  - `release_adapter.CONFIG_TYPES == ("string", "integer", "boolean", "string_list")`.
  - `release_adapter.watch_operation(descriptor: Mapping[str, Any]) -> str | None`.
  - `release_adapter.REGISTRY` and `DESCRIPTORS` keyed `github-forge` and `github-actions-health`.
  - `tests/actions_world.py`: `ActionsWorld`, `run`, and `SLUG`, `CONFIG`, `RUN_LIST`, `MERGE`, `OLDER`, `HOTFIX` (Task 3 imports them).

**Invariants:**
- The forge descriptor and its digest are unchanged, because it uses no config type.
- `inspect` never raises. Every effect observation passes `effect_observation_problems`, and every predicate observation passes `predicate_observation_problems`.
- `invoke`, and any request that fails the inner check, start no child process and open no connection.
- The adapter removes no environment variable: its `gh` child inherits `os.environ` (D10).
- `satisfied` occurs only for a `success` run at the candidate on `config.branch` whose health commit matches (D6).
- Health is read only when the selected run is completed.
- One budget bounds the whole `inspect`, health and error bodies included (D18).

- [ ] **Step 1: Write the failing tests**

Create `tests/actions_world.py` exactly:

```python
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
```

Create `tests/test_actions_health_adapter.py` exactly:

```python
"""The github-actions-health adapter (issue 465 D2, D6-D10, D14, D16). Run: just agent-workflow-tests"""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from agent_tools import actions_health_adapter as adapter
from agent_tools import release_adapter
from .actions_world import CONFIG, HOTFIX, MERGE, OLDER, RUN_LIST, SLUG, ActionsWorld, run

WATCH_SCHEMA = {"workflow": "string", "branch": "string", "services": "string_list",
                "health_url": "string", "health_commit_field": "string"}
REFUSED = {"result": "rejected", "error_class": "unsupported_operation",
           "reference": "deploy: bridge_watch_only"}


def request(commit: str = MERGE, **config: object) -> dict:
    return {"kind": "effect", "operation": "deploy", "parameters": {
        "target": {"kind": "github_repository", "repository": SLUG, "branch": "main"},
        "candidate": {"commit": commit}, "config": {**CONFIG, **config}}}


class AdapterContractTest(unittest.TestCase):
    def test_string_list_is_a_closed_config_type(self):
        schema = {"members": {"services": "string_list"}, "required": ["services"]}
        self.assertEqual(release_adapter.config_problems(schema, {"services": ["jarbird", "caddy"]}),
                         [])
        for value in ([], ["a", "a"], ["a", ""], "jarbird", ["a", 1], None):
            with self.subTest(value=value):
                self.assertEqual(release_adapter.config_problems(schema, {"services": value}),
                                 ["config member 'services' must be a string_list"])

    def test_the_registry_carries_one_watch_operation(self):
        descriptor = adapter.describe()
        self.assertEqual(release_adapter.descriptor_problems(descriptor), [])
        self.assertIs(release_adapter.REGISTRY["github-actions-health"], adapter)
        self.assertEqual(release_adapter.DESCRIPTORS["github-actions-health"], descriptor)
        deploy = descriptor["operations"]["deploy"]
        self.assertEqual((deploy["mode"], deploy["support"], deploy["inspect"], deploy["reason"]),
                         ("publication_triggered", "unsupported", "supported", "bridge_watch_only"))
        self.assertEqual(deploy["config_schema"]["members"], WATCH_SCHEMA)
        self.assertEqual(sorted(deploy["config_schema"]["required"]), sorted(WATCH_SCHEMA))
        self.assertEqual(release_adapter.config_problems(deploy["config_schema"], CONFIG), [])
        self.assertEqual((descriptor["executables"], descriptor["credential_classes"]),
                         (["gh"], ["gh_cli"]))
        self.assertEqual(release_adapter.watch_operation(descriptor), "deploy")
        self.assertIsNone(release_adapter.watch_operation(
            release_adapter.DESCRIPTORS["github-forge"]))

    def test_invoke_refuses_every_request_without_a_child(self):
        world = ActionsWorld(self)
        for value in (request(), {}, None):
            with self.subTest(value=value):
                self.assertEqual(adapter.invoke(value), REFUSED)
        self.assertEqual(release_adapter.invoke_result_problems(adapter.invoke(request())), [])
        self.assertEqual(world.calls(), [])

    def test_a_request_outside_the_closed_shape_spawns_nothing(self):
        world = ActionsWorld(self)
        extra = request()
        extra["parameters"]["pr"] = 1
        cases = {"branch differs from the target": request(branch="dev"),
                 "file url": request(health_url="file:///etc/passwd"),
                 "url without a host": request(health_url="https:///health"),
                 "unparseable url": request(health_url="https://["),
                 "short candidate": request(commit=MERGE[:7]),
                 "upper-case candidate": request(commit=MERGE.upper()),
                 "empty services": request(services=[]),
                 "undeclared config member": request(region="eu"),
                 "empty workflow": request(workflow=""),
                 "unknown parameter": extra,
                 "unknown operation": dict(request(), operation="tag"),
                 "not a request": []}
        for name, value in cases.items():
            with self.subTest(name):
                observation = adapter.inspect(value)
                self.assertEqual((observation["outcome"], observation["reason"]),
                                 ("unknown", "parameters_invalid"))
                self.assertTrue(observation["facts"]["detail"])
                self.assertEqual(release_adapter.effect_observation_problems(observation), [])
        predicate = adapter.inspect({"kind": "predicate", "predicate": "running_subject_identity",
                                     "operation": "deploy", "parameters": request()["parameters"]})
        self.assertEqual((predicate["outcome"], predicate["reason"]),
                         ("unknown", "predicate_unsupported"))
        self.assertEqual(release_adapter.predicate_observation_problems(predicate), [])
        self.assertEqual(world.calls(), [])


class ClassificationTest(unittest.TestCase):
    def setUp(self):
        self.world = ActionsWorld(self)

    def observe(self, *runs: dict, **health: object) -> dict:
        self.world.runs(*runs)
        self.world.routes.pop("/health", None)
        if health:
            self.world.health(**health)
        observation = adapter.inspect(request(health_url=self.world.url()))
        self.assertEqual(release_adapter.effect_observation_problems(observation), [])
        return observation

    def verdict(self, *runs: dict, **health: object) -> tuple[str, str]:
        observation = self.observe(*runs, **health)
        return observation["outcome"], observation["reason"]

    def test_satisfied_needs_a_successful_run_and_a_matching_health_commit(self):
        self.assertEqual(self.verdict(run(8, MERGE), commit=MERGE), ("satisfied", "deployed"))
        self.assertEqual(self.verdict(run(8, MERGE), commit=MERGE[:7]), ("satisfied", "deployed"))
        self.assertEqual(self.verdict(run(8, MERGE), commit=MERGE[:12].upper()),
                         ("satisfied", "deployed"))
        self.assertEqual(self.verdict(run(8, MERGE), commit=OLDER),
                         ("diverged", "health_commit_mismatch"))
        self.assertEqual(self.verdict(run(8, MERGE), commit=MERGE[:6]),
                         ("unknown", "health_payload_invalid"))
        self.assertEqual(self.verdict(run(8, MERGE, conclusion="failure"), commit=MERGE),
                         ("diverged", "run_failed"))

    def test_intermediate_rows_never_read_health(self):
        self.assertEqual(self.verdict(run(7, OLDER)), ("absent", "run_absent"))
        self.assertEqual(self.verdict(), ("absent", "run_absent"))
        for status in ("queued", "in_progress", "waiting"):
            with self.subTest(status=status):
                observation = self.observe(run(8, MERGE, status=status), commit=MERGE)
                self.assertEqual((observation["outcome"], observation["reason"]),
                                 ("in_progress", "run_in_progress"))
                self.assertEqual(observation["facts"]["run"]["status"], status)
                self.assertIsNone(observation["facts"]["health"])
        self.assertEqual(self.world.requests, [])

    def test_a_failed_run_is_a_silent_rollback_only_while_an_older_commit_serves(self):
        for conclusion in ("failure", "timed_out", "cancelled"):
            with self.subTest(conclusion=conclusion):
                self.assertEqual(self.verdict(run(8, MERGE, conclusion=conclusion), commit=OLDER),
                                 ("diverged", "silent_rollback"))
                self.assertEqual(
                    self.verdict(run(8, MERGE, conclusion=conclusion), status=503, body=b"down"),
                    ("diverged", "run_failed"))

    def test_only_the_newest_run_at_the_merge_commit_decides(self):
        stale_failure = run(8, MERGE, conclusion="failure")
        newer_success = run(9, MERGE, created="2026-10-27T11:00:00Z")
        observation = self.observe(stale_failure, newer_success, commit=MERGE)
        self.assertEqual((observation["outcome"], observation["reason"]), ("satisfied", "deployed"))
        self.assertEqual([entry["id"] for entry in observation["facts"]["runs"]], [9, 8])
        self.assertEqual(observation["facts"]["run"]["id"], 9)
        newer_failure = run(9, MERGE, conclusion="failure", created="2026-10-27T11:00:00Z")
        self.assertEqual(self.verdict(run(8, MERGE), newer_failure, commit=OLDER),
                         ("diverged", "silent_rollback"))
        other_branch = run(9, MERGE, branch="release", created="2026-10-27T11:00:00Z")
        observation = self.observe(other_branch, run(8, MERGE), commit=MERGE)
        self.assertEqual((observation["outcome"], observation["facts"]["run"]["id"]),
                         ("satisfied", 8))
        offset = run(9, OLDER, created="2026-10-27T11:00:00+02:00")  # 09:00Z, before run 8
        self.assertEqual([entry["id"] for entry in self.observe(offset, run(8, MERGE),
                                                                 commit=MERGE)["facts"]["runs"]],
                         [8, 9])

    def test_a_newer_run_supersedes_only_a_completed_unsatisfied_run(self):
        hotfix = run(9, HOTFIX, status="queued", created="2026-10-27T11:00:00Z")
        self.assertEqual(self.verdict(hotfix, run(8, MERGE, conclusion="cancelled"), commit=OLDER),
                         ("diverged", "superseded"))
        self.assertEqual(self.verdict(run(9, HOTFIX, created="2026-10-27T11:00:00Z"), run(8, MERGE),
                                      commit=HOTFIX),
                         ("diverged", "superseded"))
        self.assertEqual(self.verdict(hotfix, run(8, MERGE), commit=MERGE),
                         ("satisfied", "deployed"))
        self.assertEqual(self.verdict(hotfix, run(8, MERGE, status="in_progress")),
                         ("in_progress", "run_in_progress"))

    def test_the_observation_names_the_run_the_health_read_and_the_services(self):
        observation = self.observe(run(7, OLDER, created="2026-10-27T09:00:00Z"), run(8, MERGE),
                                   commit=MERGE)
        self.assertEqual(observation["observed_subject"], {"commit": MERGE, "run": 8})
        self.assertEqual(observation["references"],
                         [f"repos/{SLUG}/actions/runs/8", self.world.url()])
        facts = observation["facts"]
        self.assertEqual(sorted(facts), ["health", "run", "runs", "services"])
        self.assertEqual(facts["services"], CONFIG["services"])
        self.assertEqual(facts["run"], {"id": 8, "status": "success", "commit": MERGE,
                                        "branch": "main", "createdAt": "2026-10-27T10:00:00Z"})
        self.assertEqual([entry["id"] for entry in facts["runs"]], [8, 7])
        self.assertEqual(facts["health"], {"status": "ok", "http_status": 200, "commit": MERGE,
                                           "detail": None})
        headers = self.world.requests[-1]["headers"]
        self.assertEqual((self.world.requests[-1]["path"], headers["Accept"],
                          headers["Cache-Control"], headers["User-Agent"]),
                         ("/health", "application/json", "no-cache", adapter.USER_AGENT))
        self.assertEqual([call["argv"] for call in self.world.calls()], [RUN_LIST])
        self.assertTrue(self.world.calls()[0]["token_visible"])  # the adapter strips nothing (D10)

    def test_a_health_read_is_one_strict_bounded_get(self):
        self.world.health(path="/moved", commit=MERGE)
        nan = b'{"commit": "%s", "load": NaN}' % MERGE.encode()
        twice = b'{"commit": "%s", "commit": "%s"}' % (MERGE.encode(), MERGE.encode())
        cases = {
            "503": (dict(status=503, body=b"maintenance"), "health_unreachable"),
            "redirect": (dict(status=302, body=b"", headers={"Location": "/moved"}),
                         "health_unreachable"),
            "204": (dict(status=204, body=b""), "health_unreachable"),
            "html": (dict(body=b"<html>ok</html>"), "health_payload_invalid"),
            "array": (dict(body=json.dumps([MERGE]).encode()), "health_payload_invalid"),
            "missing field": (dict(body=b'{"sha": "%s"}' % MERGE.encode()),
                              "health_payload_invalid"),
            "duplicate key": (dict(body=twice), "health_payload_invalid"),
            "nan": (dict(body=nan), "health_payload_invalid"),
            "oversized": (dict(body=json.dumps({"commit": MERGE, "pad": "x" * 65536}).encode()),
                          "health_payload_invalid"),
        }
        for name, (health, reason) in cases.items():
            with self.subTest(name):
                observation = self.observe(run(8, MERGE), **health)
                self.assertEqual((observation["outcome"], observation["reason"]),
                                 ("unknown", reason))
                self.assertEqual(observation["facts"]["health"]["status"], reason)
                self.assertTrue(observation["facts"]["health"]["detail"])
                self.assertLessEqual(len(observation["facts"]["health"]["detail"]), 240)
        unreachable = self.observe(run(8, MERGE), status=503, body=b"maintenance")
        self.assertEqual(unreachable["facts"]["health"]["http_status"], 503)
        self.assertIn("maintenance", unreachable["facts"]["health"]["detail"])
        self.assertNotIn("/moved", [entry["path"] for entry in self.world.requests])
        self.world.runs(run(8, MERGE))
        closed = adapter.inspect(request(health_url="http://127.0.0.1:9/health"))
        self.assertEqual((closed["outcome"], closed["reason"]), ("unknown", "health_unreachable"))

    def test_a_failed_run_list_is_unknown_with_its_detail(self):
        self.world.runs(exit=1, stdout="", stderr="HTTP 502: Bad Gateway")
        observation = adapter.inspect(request(health_url=self.world.url()))
        self.assertEqual((observation["outcome"], observation["reason"],
                          observation["facts"]["detail"]),
                         ("unknown", "lookup_failed", "HTTP 502: Bad Gateway"))
        bad_entries = {"not json": None, "not a list": {},
                       "zero id": [dict(run(8, MERGE), databaseId=0)],
                       "short sha": [dict(run(8, MERGE), headSha=MERGE[:7])],
                       "naive time": [run(8, MERGE, created="2026-10-27T10:00:00")],
                       "prose time": [run(8, MERGE, created="yesterday")],
                       "completed without conclusion": [dict(run(8, MERGE), conclusion="")]}
        for name, entries in bad_entries.items():
            with self.subTest(name):
                self.world.runs(stdout="not json" if entries is None else json.dumps(entries))
                observation = adapter.inspect(request(health_url=self.world.url()))
                self.assertEqual((observation["outcome"], observation["reason"]),
                                 ("unknown", "payload_invalid"))
                self.assertEqual(observation["facts"]["services"], CONFIG["services"])
        self.assertEqual(self.world.requests, [])

    def test_one_collection_budget_bounds_both_reads(self):
        with mock.patch.object(adapter, "COLLECTION_BUDGET_SECONDS", 1):
            self.world.runs(run(8, MERGE), sleep=2)
            slow_list = adapter.inspect(request(health_url=self.world.url()))
            self.assertEqual((slow_list["outcome"], slow_list["reason"]),
                             ("unknown", "lookup_timeout"))
            self.world.runs(run(8, MERGE))
            self.world.health(commit=MERGE, delay=2)
            slow_health = adapter.inspect(request(health_url=self.world.url()))
            self.assertEqual((slow_health["outcome"], slow_health["reason"]),
                             ("unknown", "health_unreachable"))
        with mock.patch.object(adapter, "COLLECTION_BUDGET_SECONDS", 3):
            for name, status, delay, body_delay in (("trickled body", 200, 1.0, 2.5),
                                                    ("stalled error body", 503, 0, 4)):
                with self.subTest(name):
                    self.world.runs(run(8, MERGE))
                    self.world.health(status, body=b"maintenance" if status != 200 else None,
                                      commit=MERGE, delay=delay, body_delay=body_delay)
                    started = time.monotonic()
                    observation = adapter.inspect(request(health_url=self.world.url()))
                    self.assertLess(time.monotonic() - started, 3.4)
                    self.assertEqual((observation["outcome"], observation["reason"]),
                                     ("unknown", "health_unreachable"))
                    self.assertEqual(observation["facts"]["health"]["http_status"], status)
                    self.assertTrue(observation["facts"]["health"]["detail"])
        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)
        with mock.patch.dict(os.environ, {"PATH": empty.name}):
            missing = adapter.inspect(request(health_url=self.world.url()))
        self.assertEqual((missing["outcome"], missing["reason"]), ("unknown", "executable_missing"))


if __name__ == "__main__":
    unittest.main()
```

In `tests/test_release_grammar.py`, `DescriptorTest.test_registry_is_closed`, replace both `["github-forge"]` expectations with `["github-actions-health", "github-forge"]`.

- [ ] **Step 2: Run the tests and watch them fail**

Run the Unit run on `tests/test_actions_health_adapter.py tests/test_release_grammar.py`.

Expected: `FAILED (failures=1, errors=1)`. The error is `ModuleNotFoundError: No module named 'agent_tools.actions_health_adapter'`, and `test_registry_is_closed` fails with `Lists differ`.

- [ ] **Step 3: Write the minimal implementation**

1. Edit `python/agent_tools/release_adapter.py`:
   - Set `CONFIG_TYPES = ("string", "integer", "boolean", "string_list")`.
   - Add `_is_string_list(value) -> bool` beside `_is_text`. It is true for a non-empty `list` of `_is_text` items with no repeat.
   - In `config_problems`, add `"string_list": _is_string_list(value)` to the per-kind dict. The problem text stays `config member '<name>' must be a <kind>`.
   - Change the import to `from agent_tools import (actions_health_adapter, forge_adapter, transaction_invocation, transaction_plan)`.
   - Set `REGISTRY = MappingProxyType({"github-forge": forge_adapter, "github-actions-health": actions_health_adapter})`.
   - Add the helper below just before `_observation_problems`:

   ```python
   def watch_operation(descriptor: Mapping[str, Any]) -> str | None:
       """The one operation a deploy watch inspects, or None (issue 465 D3).

       That is the descriptor's single operation whose mode is an activation mode and whose
       `inspect` is supported; none, or more than one, is None.
       """
       names = [name for name, entry in descriptor["operations"].items()
                if entry["mode"] in ACTIVATION_MODES and entry["inspect"] == "supported"]
       return names[0] if len(names) == 1 else None
   ```

   - Append one sentence to the module docstring's paragraph that begins `Owns the vocabularies`: `` `watch_operation` names the one operation of a descriptor that a deploy watch inspects (issue 465 D3). ``

2. Create `python/agent_tools/actions_health_adapter.py`. Imports are limited to `http.client`, `json`, `re`, `subprocess`, `threading`, `time`, `urllib.error`, `urllib.parse`, `urllib.request`, `datetime.datetime`, `typing.Any` and `agent_tools.canonical`. Use this module docstring verbatim:

```text
The GitHub Actions deploy-watch adapter (issue 465 D2, D6-D8, D14): `describe`, `inspect`, `invoke`.

These three functions are the adapter's whole public surface (#124 D7). `describe()` returns a
fresh descriptor with one operation, `deploy`: `publication_triggered` mode, `unsupported` for
`invoke` (`bridge_watch_only`) and supported for `inspect`, so no release profile can bind it yet
and ship-release reaches it through `release deploy inspect` (D1, D5). Its closed config is
`workflow`, `branch`, `services` (a `string_list`), `health_url` and `health_commit_field`.

This module imports only the standard library and `agent_tools.canonical`: the registry in
`release_adapter` imports it, never the reverse, so its inner checks are its own (D14).

`inspect(request)` never raises and never mutates. A request outside the closed shape is
`unknown`/`parameters_invalid` and a predicate request is `unknown`/`predicate_unsupported`.
Otherwise it runs `gh run list` by name with the caller's environment unchanged (the command
applies the tracker's credential binding, D10) and, only when the newest run at the candidate
commit on the configured branch is completed, one `GET` of the health URL that follows no
redirect and reads at most `HEALTH_BODY_LIMIT` bytes, both under one
`COLLECTION_BUDGET_SECONDS` deadline. `satisfied` needs a `success` run whose commit the health
endpoint also reports (D6, D7).

`invoke(request)` refuses every request with `unsupported_operation` and starts no child process.
```

   Define the constants listed under Interfaces, together with these:
   - `SLUG` and `BRANCH`: the forge's two patterns, copied;
   - `CANDIDATE_SHA = re.compile(r"[0-9a-f]{40}")`;
   - `RUN_SHA = re.compile(r"[0-9A-Fa-f]{40}")`;
   - `REPORTED_SHA = re.compile(r"[0-9A-Fa-f]{7,40}")`;
   - `CONFIG_MEMBERS = {"workflow": "string", "branch": "string", "services": "string_list", "health_url": "string", "health_commit_field": "string"}`;
   - `TARGET_MEMBERS = frozenset(("kind", "repository", "branch"))`;
   - `REQUIRED = frozenset(("target", "candidate", "config"))`;
   - `TOLERATED = frozenset(("action", "operation"))`.

   Then write these functions:
   - `describe()` exactly as below; `required` lists the members in authored order:

```python
def describe() -> dict[str, Any]:
    """The `github-actions-health` descriptor (issue 465 D2), a fresh plain dict."""
    return {
        "name": "github-actions-health",
        "adapter_contract_version": "1.0.0",
        "operations": {
            "deploy": {"mode": "publication_triggered", "support": "unsupported",
                       "inspect": "supported", "reason": "bridge_watch_only",
                       "mutability": "in_place", "config_schema_version": 1,
                       "config_schema": {"members": dict(CONFIG_MEMBERS),
                                         "required": list(CONFIG_MEMBERS)},
                       "effects": ["reversible_no_incremental_spend"],
                       "recovery_capable": False, "candidate_members": []},
        },
        "predicates": {
            "publication_visible": {"support": "unsupported", "reason": "no_publication_mode"},
            "running_subject_identity": {"support": "unsupported", "reason": "bridge_watch_only"},
        },
        "collector": {"max_collection_latency_ms": 30000, "max_concurrent_collections": 1},
        "target_kinds": {"github_repository": ["branch", "repository"]},
        "credential_classes": ["gh_cli"],
        "executables": ["gh"],
        "host_capacity": "not_required",
    }
```

   - `_observation(outcome, reason, *, runs=None, run=None, health=None, services=None, references=None, detail=None)` returns `{outcome, reason, observed_subject, references, observed_at, facts}`:
     - `observed_subject` is `{"commit": health["commit"] if health else None, "run": run["id"] if run else None}`;
     - `facts` is `{"runs": runs or [], "run": run, "health": health, "services": services or []}`, plus `"detail": detail[:DETAIL_LIMIT]` when `detail` is not None;
     - `observed_at` is epoch milliseconds.
   - `_matches(reported, commit) -> bool` is `REPORTED_SHA.fullmatch(reported) is not None and commit.startswith(reported.lower())` (D7).
   - `_parameters_problem(parameters) -> str | None` is the inner check (D14). It returns the first problem as a bounded sentence that names the member, in this order:
     1. the parameters are not an object, or they miss a `REQUIRED` member, or they have a member outside `REQUIRED | TOLERATED`;
     2. `target` is not an object with exactly `TARGET_MEMBERS` and `kind == "github_repository"`;
     3. `repository` fails `SLUG` or contains `..`; `branch` fails `BRANCH` or contains `..`;
     4. `candidate` is not exactly `{commit}` with a value that full-matches `CANDIDATE_SHA`;
     5. `config` does not have exactly the `CONFIG_MEMBERS` keys;
     6. a `string` member is not a non-empty string, or `services` is not a non-empty list of unique non-empty strings;
     7. `config["branch"] != target["branch"]`;
     8. `urllib.parse.urlsplit(health_url)` raises `ValueError` (for example `https://[`), or the split has a scheme outside `http`/`https`, or no `hostname` (D18).
   - `_run_list(slug, workflow, branch, deadline) -> (status, payload, detail)` mirrors the forge's `_gh`, with two differences: no `env=` (the child inherits `os.environ`), and no HTTP-status mapping.
     - argv: `["gh", "run", "list", "--repo", slug, "--workflow", workflow, "--branch", branch, "--limit", str(RUN_LIMIT), "--json", RUN_FIELDS]`.
     - Run options: `capture_output=True, text=True, errors="replace", timeout=<remaining>, stdin=subprocess.DEVNULL`.
     - A spent deadline or `TimeoutExpired` returns `lookup_timeout`; an `OSError` returns `executable_missing` with `str(error)` as the detail.
     - A non-zero exit returns `lookup_failed` with `stderr.strip()[:DETAIL_LIMIT]` as the detail.
     - Stdout that `json.loads` refuses (`ValueError` or `RecursionError`) returns `payload_invalid`.
   - `_entries`, `_NoRedirect`, `_health` and `_deploy` exactly as below. The ordering, the selection, the `superseded` precedence and the no-redirect read are the decisions D6, D8 and D14 pin:

```python
class _Invalid(Exception):
    """A run-list payload outside the closed entry shape: `payload_invalid` with this detail."""


def _entries(payload: Any) -> list[tuple[tuple[datetime, int], bool, dict[str, Any]]]:
    """`(sort key, completed, mapped entry)` per run, newest first (D14)."""
    if not isinstance(payload, list):
        raise _Invalid("run list is not a list")
    entries = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise _Invalid(f"run {index} is not an object")
        run_id = entry.get("databaseId")
        if type(run_id) is not int or run_id < 1:
            raise _Invalid(f"run {index} databaseId is not a positive integer")
        for name in ("status", "headBranch", "createdAt"):
            if not _text(entry.get(name)):
                raise _Invalid(f"run {index} {name} is not a non-empty string")
        sha = entry.get("headSha")
        if not isinstance(sha, str) or RUN_SHA.fullmatch(sha) is None:
            raise _Invalid(f"run {index} headSha is not 40 hex characters")
        completed = entry["status"] == "completed"
        conclusion = entry.get("conclusion")
        if not isinstance(conclusion, str) or (completed and not conclusion):
            raise _Invalid(f"run {index} conclusion is not a string, non-empty when completed")
        try:
            created = datetime.fromisoformat(entry["createdAt"])
        except ValueError:
            created = None
        if created is None or created.tzinfo is None:
            raise _Invalid(f"run {index} createdAt is not an ISO 8601 time with an offset")
        entries.append(((created, run_id), completed, {
            "id": run_id, "status": conclusion if completed else entry["status"],
            "commit": sha, "branch": entry["headBranch"], "createdAt": entry["createdAt"]}))
    entries.sort(key=lambda item: item[0], reverse=True)
    return entries


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Follow no redirect: urllib then raises the 3xx as an `HTTPError` (D8)."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _health(url: str, field: str, deadline: float) -> dict[str, Any]:
    """`{status, http_status, commit, detail}` of one strict, bounded health read (D8)."""
    def result(status: str, http_status: int | None = None, commit: str | None = None,
               detail: str | None = None) -> dict[str, Any]:
        return {"status": status, "http_status": http_status, "commit": commit,
                "detail": None if detail is None else detail[:DETAIL_LIMIT]}

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return result("health_unreachable", detail="the collection budget is spent")
    seen: dict[str, Any] = {}

    def read() -> None:
        """The read, in a daemon thread joined for the remaining budget (D18)."""
        request = urllib.request.Request(url, method="GET", headers={
            "Accept": "application/json", "Cache-Control": "no-cache", "User-Agent": USER_AGENT})
        try:
            with urllib.request.build_opener(_NoRedirect).open(request,
                                                               timeout=remaining) as response:
                seen["http_status"] = response.status
                seen["body"] = response.read(HEALTH_BODY_LIMIT + 1)
        except urllib.error.HTTPError as error:
            seen["http_status"] = error.code
            try:
                text = error.read(DETAIL_LIMIT * 4).decode("utf-8", "replace")
                seen["failure"] = f"HTTP {error.code}: {text}"
            except (OSError, ValueError, http.client.HTTPException) as failure:
                seen["failure"] = f"HTTP {error.code}: {str(failure) or type(failure).__name__}"
            finally:
                error.close()
        except (OSError, ValueError, http.client.HTTPException) as error:
            seen["failure"] = str(error) or type(error).__name__

    worker = threading.Thread(target=read, daemon=True)
    worker.start()
    worker.join(max(0.0, deadline - time.monotonic()))
    if worker.is_alive():
        return result("health_unreachable", seen.get("http_status"),
                      detail="the budget ran out during the health read")
    if "body" not in seen:
        return result("health_unreachable", seen.get("http_status"),
                      detail=seen.get("failure", "no body was read"))
    status, body = seen["http_status"], seen["body"]
    if status != 200:
        text = body[:DETAIL_LIMIT * 4].decode("utf-8", "replace")
        return result("health_unreachable", status, detail=f"HTTP {status}: {text}")
    if len(body) > HEALTH_BODY_LIMIT:
        return result("health_payload_invalid", status,
                      detail=f"the body exceeds {HEALTH_BODY_LIMIT} bytes")
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except (ValueError, RecursionError) as error:
        return result("health_payload_invalid", status, detail=f"the body is not strict JSON: {error}")
    commit = value.get(field) if isinstance(value, dict) else None
    if not isinstance(commit, str) or REPORTED_SHA.fullmatch(commit) is None:
        return result("health_payload_invalid", status,
                      detail=f"top-level {field} is not 7 to 40 hex characters")
    return result("ok", status, commit)


def _deploy(parameters: Any, deadline: float) -> dict[str, Any]:
    """The effect observation of one deploy request (D6): the spec's classification table."""
    problem = _parameters_problem(parameters)
    if problem is not None:
        return _observation("unknown", "parameters_invalid", detail=problem)
    target, config = parameters["target"], parameters["config"]
    commit, services = parameters["candidate"]["commit"], list(config["services"])
    status, payload, detail = _run_list(target["repository"], config["workflow"],
                                        config["branch"], deadline)
    if status != "ok":
        return _observation("unknown", status, services=services, detail=detail)
    try:
        entries = _entries(payload)
    except _Invalid as error:
        return _observation("unknown", "payload_invalid", services=services, detail=str(error))
    runs = [entry for _, _, entry in entries]
    selected = next((index for index, (_, _, entry) in enumerate(entries)
                     if _matches(entry["commit"], commit) and entry["branch"] == config["branch"]),
                    None)
    if selected is None:
        return _observation("absent", "run_absent", runs=runs, services=services)
    _, completed, run = entries[selected]
    references = [f"repos/{target['repository']}/actions/runs/{run['id']}"]
    if not completed:
        return _observation("in_progress", "run_in_progress", runs=runs, run=run,
                            services=services, references=references)
    health = _health(config["health_url"], config["health_commit_field"], deadline)
    references.append(config["health_url"])
    matched = health["status"] == "ok" and _matches(health["commit"], commit)
    newer = any(not _matches(entry["commit"], commit) for _, _, entry in entries[:selected])
    if run["status"] == "success" and matched:
        outcome, reason = "satisfied", "deployed"
    elif newer:
        outcome, reason = "diverged", "superseded"
    elif run["status"] == "success":
        outcome, reason = (("diverged", "health_commit_mismatch") if health["status"] == "ok"
                           else ("unknown", health["status"]))
    elif health["status"] == "ok" and not matched:
        outcome, reason = "diverged", "silent_rollback"
    else:
        outcome, reason = "diverged", "run_failed"
    return _observation(outcome, reason, runs=runs, run=run, health=health, services=services,
                        references=references)
```

   - `inspect(request)`:
     1. Set `deadline = time.monotonic() + COLLECTION_BUDGET_SECONDS`.
     2. A dict with `kind == "predicate"` returns `{"outcome": "unknown", "reason": "predicate_unsupported", "references": [], "observed_at": <ms>}`.
     3. A dict whose keys are exactly `{kind, operation, parameters}`, with `kind == "effect"`, goes to `_deploy(parameters, deadline)` when `operation == "deploy"`, and otherwise returns `_observation("unknown", "parameters_invalid", detail=f"unknown operation {operation!r}")`.
     4. Anything else returns `_observation("unknown", "parameters_invalid", detail="request is not a closed effect or predicate request")`.

     Its docstring states that it never raises and never mutates.
   - `invoke(request)` returns a fresh `{"result": "rejected", "error_class": "unsupported_operation", "reference": "deploy: bridge_watch_only"}` for every request.

3. In `justfile`, add the line `    tests/test_actions_health_adapter.py \` to the `agent-workflow-tests` member list, directly after `    tests/test_forge_adapter.py \`.

4. In `python/README.md` § Release adapters, insert this paragraph after the one that begins ``The forge adapter (`forge_adapter`, D8)``:

```text
The GitHub Actions deploy-watch adapter (`actions_health_adapter`, issue 465 D2) is registered as `github-actions-health`. Its one operation, `deploy`, is `publication_triggered`, `unsupported` for `invoke` with reason `bridge_watch_only` and supported for `inspect`, so no profile can bind it yet and its `invoke` refuses every request with `unsupported_operation` and no child process. Its closed config is `workflow`, `branch`, `services`, `health_url` and `health_commit_field`, all required; `services` is the `string_list` config type, a non-empty list of unique non-empty strings. `release_adapter.watch_operation(descriptor)` names a descriptor's single inspectable activation-mode operation, or returns `None` when there is none or more than one. `inspect` answers `parameters_invalid` unless the request carries a `github_repository` target of exactly `kind`, `repository` and `branch`, a 40-lowercase-hex candidate `commit`, and a config whose `branch` equals the target's and whose `health_url` is `http` or `https` with a host. It then makes at most two reads under one 30-second budget. The first is `gh run list --repo <repository> --workflow <workflow> --branch <branch> --limit 5 --json databaseId,status,conclusion,headSha,headBranch,createdAt`, run by name with the caller's environment unchanged: the adapter strips no variable, and `release deploy inspect` applies `bindings.tracker.credential_env` (D10). The second, made only when the newest run at the candidate on that branch is completed, is one `GET <health_url>` that follows no redirect, reads at most 65,536 bytes and loads the body strictly through the `canonical` hooks (D8). Runs are ordered newest first by `createdAt`, which must be an ISO 8601 time with an offset (D14), and a commit matches when it is 7 to 40 hex characters and the candidate starts with it, case-insensitively (D7). The outcome follows the spec's classification table (D6): `absent` (`run_absent`); `in_progress` (`run_in_progress`); `satisfied` (`deployed`) only for a `success` run whose health commit matches; `diverged` (`superseded`) for a completed, unsatisfied run that a run at another commit followed; otherwise `diverged` (`health_commit_mismatch`, `silent_rollback` or `run_failed`) or `unknown` (`health_unreachable` or `health_payload_invalid`). A failed run-list read is `unknown` with `lookup_failed`, `lookup_timeout`, `executable_missing` or `payload_invalid` and the bounded stderr in `facts.detail`. Every effect observation's `facts` hold `runs` (each `{id, status, commit, branch, createdAt}`, newest first), `run`, `health` and the configured `services`. `tests/actions_world.py` is its fake `gh`, which logs token visibility, and loopback HTTP server.
```

- [ ] **Step 4: Verify**

1. Run the Unit run on `tests/test_actions_health_adapter.py tests/test_release_grammar.py tests/test_forge_adapter.py tests/test_release_adapter_core.py tests/test_release_profile.py tests/test_release_command.py`.

   Expected: `OK`.

2. Run the Unit run on `tests/test_suite_runner.py -k RecipeWiringTest`.

   Expected: `OK`.

3. Run `bash -c 'git diff --quiet 5ae1b9dc -- python/agent_tools/forge_adapter.py tests/forge_world.py lib/agent-tools.nix'`.

   Expected: exit 0 (forge adapter, its world and command table untouched).

4. Run `git add python/agent_tools/actions_health_adapter.py tests/actions_world.py tests/test_actions_health_adapter.py`, then the Build.

   Expected: exit 0. The build's import check loads the new module.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/actions_health_adapter.py python/agent_tools/release_adapter.py tests/actions_world.py tests/test_actions_health_adapter.py tests/test_release_grammar.py justfile python/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(release): github-actions-health deploy-watch adapter (issue 465)" -m "<trailers>"
```
