# Task 2: Health probe over bash `/dev/tcp`

This task covers spec § Health probe, per D2, D10 and D11. The probe stops spawning curl and jq. A function made only of bash builtins asks `GET /_proxy/health` over `/dev/tcp`, inside a process substitution. The launcher reads its one verdict line under a single 0.5 s deadline, signals the process only when that deadline cuts it off, and always reaps it. Every fail-to-direct case stays as it is. Routing is still opt-in here (Task 3 flips it).

**Files:**
- Modify: `home/common/claude-code/accounts/bin/claude-account` (a new `cache_proxy_health` function, and the probe inside `route_cache_proxy`)
- Modify: `tests/test_claude_account_routing.py`
- Modify: `home/common/claude-code/README.md` (§ Cache proxy, one clause)

**Interfaces:**
- Consumes:
  - `route_cache_proxy` as Task 1 left it. It has the line `  local health`, and this four-line probe, the `if` opening the healthy branch:

```bash
  # The status is checked explicitly: `-f` alone would accept a 3xx carrying the marker.
  if health="$("$CURL" -q --noproxy '*' -sS --max-time 0.5 -w '\n%{http_code}' "$CACHE_PROXY_URL/_proxy/health" 2>/dev/null)" &&
    case "${health##*$'\n'}" in 2??) true ;; *) false ;; esac &&
    printf '%s' "${health%$'\n'*}" | "$JQ" -e '.service == "cache-proxy"' >/dev/null 2>&1; then
```

  - Task 1's `REMINDER`, `assert_routed` and `assert_direct` in the tests.
  - `cache_proxy.HEALTH_PATH` (`/_proxy/health`) and `HEALTH_BODY` (`{"service":"cache-proxy","status":"ok"}`). The real handler answers a GET with status 200, `Content-Type` and `Content-Length`, and logs no `request` line for it.
- Produces:
  - `cache_proxy_health <host> <port>`, which prints `healthy` once on success and nothing otherwise.
  - In the tests: `LauncherCase.silent_listener()`, plus a `without_curl_and_jq=False` keyword on `run_launcher` and `launch`.
  - Task 3 keeps all of this unchanged. Task 6's opt-in gate compares the text from `cache_proxy_health() {` to its closing `}`, and from `  local verdict=` to the end of `route_cache_proxy`, against M.

**Invariants:**
- No process is spawned for the probe: no curl, no jq, no subshell besides the one process substitution.
- One deadline, `read -t 0.5`, bounds the connect, the request and the answer. A dead or hung proxy costs at most about 0.5 s.
- The process substitution is signalled (`kill "$!"`) only after a timeout. It is reaped (`wait "$!"`) after every probe (D11).
- Success needs a status line `HTTP/1.0` or `HTTP/1.1` with a 2xx code, a `Content-Length` header, a body of that length, and the substring `"service":"cache-proxy"` in it. Anything else goes direct: a closed port, a foreign listener, a 302 carrying the marker, a listener that never answers.
- Host and port come from `CACHE_PROXY_URL` of the form `http://<host>:<port>`, the only shape the build writes.
- The probe's stderr is silenced; the launcher stays silent except for the refusal.
- `JQ=jq`, `CURL=curl` and their build substitutions stay, because `status` uses them.
- The switch check stays the first statement of `route_cache_proxy`, then the empty-URL return, then the caller-set-endpoint return (438 D13).

- [ ] **Step 1: Write the failing tests**

Edit `tests/test_claude_account_routing.py`:

1. Add `import time` after `import threading`.
2. Replace the first two lines of `LauncherCase.setUp` (the `for tool in ("bash", "curl", "jq", "env"):` loop and its assertion) with:

```python
        for tool in ("bash", "env"):
            self.assertIsNotNone(shutil.which(tool), f"{tool} is required on PATH")
        version = subprocess.run([shutil.which("bash"), "-c", 'echo "${BASH_VERSINFO[0]} ${BASH_VERSINFO[1]}"'],
                                 capture_output=True, text=True, check=True).stdout.split()
        self.assertGreaterEqual(tuple(map(int, version)), (4, 4),
                                "the health probe needs bash 4.4 or later ($! must name a process substitution)")
```

3. After `redirecting_listener`, add:

```python
    def silent_listener(self):
        """A port whose listener completes TCP handshakes but never reads or answers."""
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        return "http://127.0.0.1:%d" % listener.getsockname()[1]
```

4. Replace `run_launcher` and `launch` with:

```python
    def run_launcher(self, proxy_url, env=None, substitute=True, without_curl_and_jq=False):
        """`claude-account run` from a fresh copy of the mod, as a finished process.

        `without_curl_and_jq` points the copy's CURL and JQ at paths that do not exist."""
        copy = Path(tempfile.mkdtemp(dir=self.root)) / "accounts"
        shutil.copytree(ACCOUNTS, copy)
        script = copy / "bin" / "claude-account"
        text = script.read_text()
        self.assertEqual(text.count(PLACEHOLDER), 1)
        if substitute:
            text = text.replace(PLACEHOLDER, PLACEHOLDER + proxy_url)
        if without_curl_and_jq:
            for line in ("\nCURL=curl\n", "\nJQ=jq\n"):
                self.assertEqual(text.count(line), 1)
                text = text.replace(line, line.replace("=", "=/nonexistent/"))
        script.write_text(text)
        home, work = self.root / "home", self.root / "work"
        home.mkdir(exist_ok=True)
        work.mkdir(exist_ok=True)
        # An allowlist: the stand-in claude prints its environment, and a failing assertion shows it.
        child = {key: os.environ[key] for key in ("PATH", "TMPDIR") if key in os.environ}
        child.update(HOME=str(home), CLAUDE_ACCOUNTS_DIR=str(self.root / "accounts-state"),
                     CLAUDE_BIN=shutil.which("env"), **{**self.switch, **(env or {})})
        return subprocess.run([shutil.which("bash"), str(script), "run"], cwd=work, env=child,
                              capture_output=True, text=True, timeout=TIMEOUT, check=False)

    def launch(self, proxy_url, env=None, substitute=True, without_curl_and_jq=False):
        """The environment the stand-in claude printed; the launch must succeed silently."""
        completed = self.run_launcher(proxy_url, env, substitute, without_curl_and_jq)
        self.assertEqual((completed.returncode, completed.stderr), (0, ""))
        return dict(line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line)
```

5. Replace `RoutingTest.test_a_healthy_proxy_routes_the_launch` with these three tests:

```python
    def test_a_healthy_proxy_routes_the_launch_after_one_probe(self):
        url = self.healthy_proxy()
        self.assert_routed(self.launch(url), url)
        self.assertEqual(self.proxy_requests, [cache_proxy.HEALTH_PATH])

    def test_the_probe_starts_no_curl_or_jq(self):
        url = self.healthy_proxy()
        self.assert_routed(self.launch(url, without_curl_and_jq=True), url)

    def test_a_listener_that_never_answers_launches_direct_within_two_seconds(self):
        url = self.silent_listener()
        started = time.monotonic()
        environment = self.launch(url)
        self.assertLess(time.monotonic() - started, 2.0)
        self.assert_direct(environment)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the plan's focused test command (timeout 600 s).
Expected: 18 tests, `FAILED (failures=1)`. The failure is `RoutingTest.test_the_probe_starts_no_curl_or_jq`: without curl, today's probe fails and the launch goes direct. The never-answering-listener test passes at the start, because curl's `--max-time 0.5` bounds today's probe. It guards D2's deadline: a `/dev/tcp` probe without `read -t` would hang until the test timeout (D10).

- [ ] **Step 3: Write the minimal implementation**

The code is given in full, because the wire format and the signal rules are the decision.

1. Insert this function right above the comment block that precedes `route_cache_proxy() {`:

```bash
# Prints `healthy` when the cache proxy at host $1, port $2 answers GET /_proxy/health with a
# 2xx status and a body naming "service":"cache-proxy", and nothing otherwise. Only bash
# builtins run here, so the probe starts no curl or jq process (#450); the caller bounds it.
cache_proxy_health() {
  local status line length="" body=""
  {
    printf 'GET /_proxy/health HTTP/1.0\r\nHost: %s:%s\r\nConnection: close\r\n\r\n' "$1" "$2" >&3
    IFS= read -r status <&3 || return 1
    case "$status" in "HTTP/1."[01]" 2"[0-9][0-9]" "*) ;; *) return 1 ;; esac
    while IFS= read -r line <&3; do
      line="${line%$'\r'}"
      [ -n "$line" ] || break
      case "${line,,}" in
        content-length:*) length="${line#*:}"; length="${length//[!0-9]/}" ;;
      esac
    done
    [ -n "$length" ] || return 1
    IFS= read -r -N "$length" body <&3 || return 1
    case "$body" in *'"service":"cache-proxy"'*) echo healthy ;; esac
  } 3<>"/dev/tcp/$1/$2"
}

```

2. In `route_cache_proxy`, replace the line `  local health` with:

```bash
  local verdict="" waited=0 hostport="${CACHE_PROXY_URL#http://}"
```

3. Replace the four consumed probe lines (the curl comment, through the line ending `>/dev/null 2>&1; then`) with:

```bash
  # One 0.5 s deadline covers the connect, the request and the answer, so a dead or hung proxy
  # costs at most half a second. Only a probe the deadline cut off is signalled: one that
  # answered or hit EOF is exiting by itself. Either way it is reaped, so a claude exec'd
  # below inherits no exited child.
  IFS= read -r -t 0.5 verdict < <(cache_proxy_health "${hostport%:*}" "${hostport##*:}" 2>/dev/null) || waited=$?
  if [ "$waited" -gt 128 ]; then kill "$!" 2>/dev/null || true; fi
  wait "$!" 2>/dev/null || true
  if [ "$verdict" = healthy ]; then
```

The branch body (the three exports and the `else` that unsets `ANTHROPIC_BASE_URL`) stays as Task 1 left it.

Notes for the implementer:
- `read` returns more than 128 on a timeout, 1 on EOF, and 0 with a line. `$!` names the process substitution only from bash 4.4 on, which is why `setUp` refuses an older bash. The build's `patchShebangs` gives the launcher nix bash 5.3.
- A `/dev/tcp` connect failure ends the brace group before it runs, so the substitution prints nothing and the launch goes direct.

- [ ] **Step 4: Document**

In `home/common/claude-code/README.md` § Cache proxy, replace the exact string ``Otherwise it probes `GET /_proxy/health` with a 0.5 s limit: an answer naming `"service":"cache-proxy"` exports`` (it occurs once) with:

> Otherwise it probes `GET /_proxy/health` with bash's own `/dev/tcp`, so the probe starts no curl or jq process (#450), under one 0.5 s deadline for the connect, the request and the answer: a 2xx answer whose body names `"service":"cache-proxy"` exports

Write the text exactly as quoted (without the `>` marker). The rest of that sentence, Task 1's reminder sentences and "a dead proxy costs at most half a second" stay.

- [ ] **Step 5: Verify**

Run the focused test command (timeout 600 s).
Expected: `OK`, with 18 tests.

Run (timeout 60 s):

```bash
set -euo pipefail
w=home/common/claude-code/accounts/bin/claude-account
body=$(sed -n '/^route_cache_proxy() {$/,/^}$/p' "$w")
if printf '%s\n' "$body" | grep -nE '"\$(CURL|JQ)"'; then exit 1; fi
test "$(grep -c '^cache_proxy_health() {$' "$w")" -eq 1
printf '%s\n' "$body" | grep -qF 'read -r -t 0.5 verdict < <(cache_proxy_health'
printf '%s\n' "$body" | grep -qF 'wait "$!" 2>/dev/null || true'
grep -q '^CURL=curl$' "$w"; grep -q '^JQ=jq$' "$w"
grep -qF "with bash's own \`/dev/tcp\`, so the probe starts no curl or jq process (#450)" home/common/claude-code/README.md
git diff --quiet 51e2b7c9 -- home/linux/claude-local
echo probe-ok
```

Expected: `probe-ok`. At the starting commit the first `if` exits 1, because `route_cache_proxy` still calls `"$CURL"`.

Run `just build mbp` (timeout 3600 s). Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add home/common/claude-code/accounts/bin/claude-account tests/test_claude_account_routing.py home/common/claude-code/README.md
launch-commit --repo-root <R> --run-id <I> --worker-id <W> -- -m "feat(issue-450): health probe over bash /dev/tcp, no curl or jq"
```

The message ends with the session's attribution trailer. Report DONE with the test count.
