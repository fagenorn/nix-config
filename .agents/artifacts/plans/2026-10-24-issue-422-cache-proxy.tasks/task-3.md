# Task 3: Health-checked routing in `claude-account run`

Spec § Wrapper routing and § Test seams (wrapper), per D10, D11, D12, D13, D15 and D17. The launcher gains one routing step, run before every launch (the early exec for a caller-chosen config directory, the first launch, each `/account` switch relaunch), and a source-copy test drives it.

**Files:**
- Modify: `home/common/claude-code/accounts/bin/claude-account`
- Create: `tests/test_claude_account_routing.py`
- Modify: `justfile` (`agent-workflow-tests`: add the line `    tests/test_claude_account_routing.py \` directly above `    tests/test_branch_protection.py`)

**Interfaces:**
- Consumes (Task 2): `agent_tools.cache_proxy.ProxyServer`, `parse_upstream`, `LineLog`, and its health contract (`GET /_proxy/health` → `{"service":"cache-proxy","status":"ok"}`). Consumes (Task 1): the report line `Tool-search switch: ship|drop` in `docs/spikes/cache-proxy-spike.md`.
- Produces (Task 4 substitutes it): exactly one occurrence of the text `CACHE_PROXY_URL=` in `claude-account`, the assignment `CACHE_PROXY_URL=` with an empty value; Nix rewrites it with `--replace-fail 'CACHE_PROXY_URL=' 'CACHE_PROXY_URL=<url>'`. Produces the function `route_cache_proxy` (no arguments, no output, exit status 0).

**Invariants:**
- Empty `CACHE_PROXY_URL` → the environment is untouched (D10 rule 1).
- `ANTHROPIC_BASE_URL` set, non-empty and different from the proxy URL → untouched, and `ENABLE_TOOL_SEARCH` is not added (rule 2).
- Otherwise one probe, `"$CURL" -q --noproxy '*' -fsS --max-time 0.5 <url>/_proxy/health` (`-q` first, so no `.curlrc` applies): 2xx with a body whose `.service` is `"cache-proxy"` (checked with `"$JQ" -e`) exports the proxy URL (and, when the switch ships, `ENABLE_TOOL_SEARCH=true` unless the variable is set at all); anything else unsets `ANTHROPIC_BASE_URL` (rule 3, D11).
- Nothing is written to stdout or stderr on either outcome; the step never fails the launch.
- `claude-local` is untouched (D13).

- [ ] **Step 1: Read the spike's switch decision**

Run (timeout 30 s): `grep -Ex 'Tool-search switch: (ship|drop)' docs/spikes/cache-proxy-spike.md`
On `ship` use the test and code below as written. On `drop` make exactly these three edits, and nothing else: in the test, `assert_routed`'s second assertion becomes `self.assertNotIn("ENABLE_TOOL_SEARCH", environment)`; delete `test_a_caller_set_tool_search_value_is_kept`; in the code, omit the comment line and the `[ -n "${ENABLE_TOOL_SEARCH+set}" ] || export ENABLE_TOOL_SEARCH=true` line.

- [ ] **Step 2: Write the failing test** — `tests/test_claude_account_routing.py`:

```python
"""The `claude` launcher routes through the cache proxy only when its health check answers (#422).

Each case runs the source `claude-account run` from a temporary copy of the accounts mod whose
`CACHE_PROXY_URL=` line is substituted the way `home/common/claude-code/default.nix` substitutes
it, with the system `env` standing in for claude, so what it prints is the environment claude
would receive.
"""

import http.server
import io
import os
import shutil
import socket
import socketserver
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from agent_tools import cache_proxy

REPO_ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS = REPO_ROOT / "home" / "common" / "claude-code" / "accounts"
PLACEHOLDER = "CACHE_PROXY_URL="
SCRUBBED = ("ANTHROPIC_BASE_URL", "ENABLE_TOOL_SEARCH", "CLAUDE_ACCOUNT", "CLAUDE_ACCOUNTS_DIR",
            "CLAUDE_ACCOUNT_LAUNCHER", "CLAUDE_BIN", "CLAUDE_CODE_PLUGIN_DIRS", "CLAUDE_CONFIG_DIR")
CALLER_URL = "http://127.0.0.1:9/caller"
TIMEOUT = 30


def closed_port():
    """A loopback port nothing listens on: bound, then freed."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class ForeignHandler(http.server.BaseHTTPRequestHandler):
    """Another service on the proxy's port: 200 to every GET, without the cache-proxy marker."""

    def do_GET(self):
        body = b'{"service":"other","status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class RoutingTest(unittest.TestCase):
    def setUp(self):
        for tool in ("bash", "curl", "jq", "env"):
            self.assertIsNotNone(shutil.which(tool), f"{tool} is required on PATH")
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)

    def serve(self, server):
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return "http://127.0.0.1:%d" % server.server_address[1]

    def healthy_proxy(self):
        """The real cache-proxy server; a health probe never reaches its upstream."""
        upstream = cache_proxy.parse_upstream("http://127.0.0.1:%d" % closed_port())
        return self.serve(cache_proxy.ProxyServer(0, upstream, cache_proxy.LineLog(io.StringIO())))

    def foreign_listener(self):
        return self.serve(socketserver.ThreadingTCPServer(("127.0.0.1", 0), ForeignHandler))

    def launch(self, proxy_url, env=None, substitute=True):
        """`claude-account run` from a fresh copy; the environment the stand-in claude printed."""
        copy = Path(tempfile.mkdtemp(dir=self.root)) / "accounts"
        shutil.copytree(ACCOUNTS, copy)
        script = copy / "bin" / "claude-account"
        text = script.read_text()
        self.assertEqual(text.count(PLACEHOLDER), 1)
        if substitute:
            script.write_text(text.replace(PLACEHOLDER, PLACEHOLDER + proxy_url))
        home, work = self.root / "home", self.root / "work"
        home.mkdir(exist_ok=True)
        work.mkdir(exist_ok=True)
        child = {key: value for key, value in os.environ.items() if key not in SCRUBBED}
        child.update(HOME=str(home), CLAUDE_ACCOUNTS_DIR=str(self.root / "accounts-state"),
                     CLAUDE_BIN=shutil.which("env"), **(env or {}))
        completed = subprocess.run([shutil.which("bash"), str(script), "run"], cwd=work, env=child,
                                   capture_output=True, text=True, timeout=TIMEOUT, check=False)
        self.assertEqual((completed.returncode, completed.stderr), (0, ""))
        return dict(line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line)

    def assert_routed(self, environment, url):
        self.assertEqual(environment.get("ANTHROPIC_BASE_URL"), url)
        self.assertEqual(environment.get("ENABLE_TOOL_SEARCH"), "true")

    def assert_direct(self, environment):
        self.assertNotIn("ANTHROPIC_BASE_URL", environment)
        self.assertNotIn("ENABLE_TOOL_SEARCH", environment)

    def test_a_healthy_proxy_routes_the_launch(self):
        url = self.healthy_proxy()
        self.assert_routed(self.launch(url), url)

    def test_a_closed_port_launches_direct(self):
        self.assert_direct(self.launch("http://127.0.0.1:%d" % closed_port()))

    def test_a_foreign_listener_without_the_marker_launches_direct(self):
        self.assert_direct(self.launch(self.foreign_listener()))

    def test_a_caller_set_endpoint_is_left_alone(self):
        environment = self.launch(self.healthy_proxy(), {"ANTHROPIC_BASE_URL": CALLER_URL})
        self.assertEqual(environment.get("ANTHROPIC_BASE_URL"), CALLER_URL)
        self.assertNotIn("ENABLE_TOOL_SEARCH", environment)

    def test_an_inherited_proxy_url_is_unset_when_the_proxy_is_down(self):
        url = "http://127.0.0.1:%d" % closed_port()
        self.assert_direct(self.launch(url, {"ANTHROPIC_BASE_URL": url}))

    def test_a_caller_chosen_config_dir_takes_the_early_exec_and_is_routed(self):
        url = self.healthy_proxy()
        config = str(self.root / "custom-config")
        environment = self.launch(url, {"CLAUDE_CONFIG_DIR": config})
        self.assertEqual(environment.get("CLAUDE_CONFIG_DIR"), config)
        # Only the account loop exports the launcher pid, so its absence proves the early exec.
        self.assertNotIn("CLAUDE_ACCOUNT_LAUNCHER", environment)
        self.assert_routed(environment, url)

    def test_a_caller_set_tool_search_value_is_kept(self):
        url = self.healthy_proxy()
        environment = self.launch(url, {"ENABLE_TOOL_SEARCH": "false"})
        self.assertEqual((environment.get("ANTHROPIC_BASE_URL"), environment.get("ENABLE_TOOL_SEARCH")),
                         (url, "false"))

    def test_an_unsubstituted_copy_never_routes(self):
        url = self.healthy_proxy()
        self.assert_direct(self.launch(url, substitute=False))
        environment = self.launch(url, {"ANTHROPIC_BASE_URL": url}, substitute=False)
        self.assertEqual(environment.get("ANTHROPIC_BASE_URL"), url)
        self.assertNotIn("ENABLE_TOOL_SEARCH", environment)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test and watch it fail**

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_claude_account_routing.py`
Expected: FAIL — every case stops at `self.assertEqual(text.count(PLACEHOLDER), 1)` with `AssertionError: 0 != 1`.

- [ ] **Step 4: Add the routing step**

In `claude-account`, after the `DEFAULT_CLAUDE_BIN=` line and its following blank line, add:

```bash
# The cache proxy's URL. Empty here, so a source copy never routes; the Nix
# build writes in the URL of the port it gives the cache-proxy service.
CACHE_PROXY_URL=

```

After `claude_bin()`, add:

```bash
# Routes this launch through the cache proxy when its health check answers and
# sends it direct otherwise. A base URL the caller set to anything but the proxy
# is the caller's own endpoint and is left alone; one equal to the proxy URL was
# inherited from a routed launch and is decided again. Silent either way:
# stdout and stderr belong to claude.
route_cache_proxy() {
  local health
  [ -n "$CACHE_PROXY_URL" ] || return 0
  if [ -n "${ANTHROPIC_BASE_URL:-}" ] && [ "$ANTHROPIC_BASE_URL" != "$CACHE_PROXY_URL" ]; then
    return 0
  fi
  if health="$("$CURL" -q --noproxy '*' -fsS --max-time 0.5 "$CACHE_PROXY_URL/_proxy/health" 2>/dev/null)" &&
    printf '%s' "$health" | "$JQ" -e '.service == "cache-proxy"' >/dev/null 2>&1; then
    export ANTHROPIC_BASE_URL="$CACHE_PROXY_URL"
    # Before Claude Code 2.1.304 a non-first-party base URL turns tool search off.
    [ -n "${ENABLE_TOOL_SEARCH+set}" ] || export ENABLE_TOOL_SEARCH=true
  else
    unset ANTHROPIC_BASE_URL
  fi
}
```

In `cmd_run`, the early-exec arm becomes `*) route_cache_proxy; exec "$(claude_bin)" "$@" ;;`, and inside the `while :` loop the line `route_cache_proxy` goes directly above `status=0`, so the first launch and every switch relaunch probe again. A planning dry run of exactly this code passed all eight cases.

- [ ] **Step 5: Verify**

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_claude_account_routing.py`
Expected: PASS, 8 tests (7 on `drop`).

Run (timeout 60 s):

```bash
set -euo pipefail
f=home/common/claude-code/accounts/bin/claude-account
test "$(grep -c 'CACHE_PROXY_URL=' "$f")" -eq 1
test "$(grep -c 'route_cache_proxy' "$f")" -eq 3
bash -n "$f"
grep -q 'tests/test_claude_account_routing.py \\' justfile
git diff --quiet 7601d318 -- home/linux/claude-local
echo routing-ok
```

Expected: `routing-ok`. At the starting commit the first `test` fails (no placeholder).

- [ ] **Step 6: Commit**

```bash
git add home/common/claude-code/accounts/bin/claude-account tests/test_claude_account_routing.py justfile
git commit -m "feat(claude-account): route launches through a healthy cache proxy (#422)"
```
