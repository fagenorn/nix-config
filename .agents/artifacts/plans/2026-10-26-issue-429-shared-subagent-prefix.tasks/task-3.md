# Task 3: `cache-proxy --reorder`, the keepalive composition, the service flag and the docs

Spec § Interface, switch and keepalive and § Docs, per D11, D17, D18, D20, D26 and D27. `cache-proxy` gains `--reorder`. With it, `ProxyServer` holds a `SubagentPrefix` (Task 2) and the handler calls it after assembling the upstream headers and before the keepalive's `observe`, so a keepalive candidate and its pings carry the reordered bytes. Both hosts' services run `--keepalive --reorder`, and the two READMEs describe it. Without the flag, every byte and log line is as today.

**Files:**
- Modify: `python/agent_tools/cache_proxy.py`
- Modify: `tests/test_cache_proxy.py` (`ProxyCase.proxy`, the new class `ReorderProxyTest`, two `CommandTest` cases)
- Modify: `tests/test_cache_keepalive.py` (imports, `KeepaliveProxyTest.start`, one new case, D27)
- Modify: `home/common/claude-code/default.nix` (`cacheProxyArgs`, the comment above `cacheProxyPort`, the systemd `Unit.Description`)
- Modify: `home/common/claude-code/README.md` (§ Cache proxy), `python/README.md` (§ `cache-proxy`)
- Scratch only: `$S/i429/nix-check.sh`

**Interfaces:**
- Consumes (Task 2): `subagent_prefix.SubagentPrefix()`, `.transform(method, path, headers, body) -> (bytes, Headers, outcome)`, `OUTCOMES`, `REWRITTEN`; the test helpers `MESSAGES`, `fixture_bytes`, `fixture`, `agent`, `holders` in `tests/test_cache_proxy.py`; Task 1's fixtures `sibling1-first.received.json` and `parent-first.json`. In `tests/test_cache_keepalive.py`: `KeepaliveProxyTest.start/send`, `FakeClock`, `sse_reply`, `forwarded`, `encode`, `AGENT_P`, `MESSAGES`.
- Produces: `cache_proxy.ProxyServer(port, upstream, log, keepalive=None, reorder=None)`; `cache-proxy --port N [--upstream URL] [--keepalive] [--reorder]`; the `listening` field `"reorder":true`, the `request` field `reorder` (an outcome or `error`), the event `reorder_error` with `method`, `path`, `error`. The built launchd agent's and systemd unit's commands end `--port 27183 --keepalive --reorder`, which Tasks 4 and 5 read.

**Invariants:**
- With `reorder=None`, every byte sent upstream and every log line is as before this task; the existing `ForwardingTest`, `CommandTest` and keepalive cases pass unchanged.
- With a transform, only an outcome in `REWRITTEN` changes what is sent, and then only the body and each `Content-Length` value; header names, order and case are unchanged.
- The transform runs after `_upstream_headers()` and before `_observe` (D18). The health path is answered before it, and a request rejected while its body is read (`411`, `400`) never reaches it and logs no `reorder` field.
- An exception from the transform, or an outcome outside `OUTCOMES`, forwards the original bytes and headers and writes `reorder_error` before the request is sent (D20). The `try` wraps only the transform call and the outcome check.
- `27183` still appears exactly once in `default.nix`.

- [ ] **Step 1: Check the starting state**

Run (timeout 30 s): `grep -qx 'Attempt 2 verdict: go' docs/spikes/cache-proxy-prefix-retest.md && test -f python/agent_tools/subagent_prefix.py && if grep -q -- '--reorder' python/agent_tools/cache_proxy.py; then exit 1; fi && echo ready`
Expected: `ready`.

- [ ] **Step 2: Write the failing tests**

In `tests/test_cache_proxy.py`, give `ProxyCase.proxy` a `reorder=None` parameter, passed as `cache_proxy.ProxyServer(0, cache_proxy.parse_upstream(upstream_url), cache_proxy.LineLog(stream), reorder=reorder)`. Add after `class ForwardingTest` (before `class SubagentPrefixTest`):

```python
class ReorderProxyTest(ProxyCase):
    """`ProxyServer` with a transform object (D17, D20)."""

    def raw_request(self, port, path, body, agent_id=None):
        """Send one POST with a fixed head; return the head lines the client sent."""
        lines = [b"POST %s HTTP/1.1" % path.encode(), b"Host: 127.0.0.1:%d" % port,
                 b"anthropic-version: 2023-06-01", b"Content-Type: application/json"]
        if agent_id is not None:
            lines.append(b"x-claude-code-agent-id: " + agent_id.encode())
        lines.append(b"Content-Length: %d" % len(body))
        with socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT) as sock:
            sock.sendall(b"\r\n".join(lines) + b"\r\n\r\n" + body)
            reply = http.client.HTTPResponse(sock)
            reply.begin()
            self.assertEqual((reply.status, reply.read()), (200, b"{}"))
        return lines

    @staticmethod
    def expected_head(lines, fake, length):
        """The head upstream should see: `Host` rewritten and `Content-Length` set to `length`."""
        host = b"Host: 127.0.0.1:%d" % fake.server.server_address[1]
        return [host if line.startswith(b"Host:") else
                b"Content-Length: %d" % length if line.startswith(b"Content-Length:") else line
                for line in lines] + [b""]

    def test_a_reordered_subagent_body_reaches_upstream_with_a_matching_content_length(self):
        fake = self.upstream(json_reply)
        port, log = self.proxy(fake.url, subagent_prefix.SubagentPrefix())
        received = fixture_bytes("sibling1-first.received.json")
        lines = self.raw_request(port, MESSAGES, received, "agent-1")
        expected, _, outcome = subagent_prefix.SubagentPrefix().transform(
            "POST", MESSAGES, agent("agent-1", len(received)), received)
        self.assertEqual(outcome, "applied")
        [(_, head, body)] = fake.requests
        self.assertEqual(body, expected)
        self.assertEqual(head.split(b"\r\n"), self.expected_head(lines, fake, len(expected)))
        [record] = log.records(1)
        self.assertEqual((record["reorder"], record["outcome"]), ("applied", "complete"))

    def test_parent_and_count_tokens_requests_reach_upstream_byte_identical(self):
        fake = self.upstream(json_reply)
        port, log = self.proxy(fake.url, subagent_prefix.SubagentPrefix())
        parent = fixture_bytes("parent-first.json")
        sibling = fixture_bytes("sibling1-first.received.json")
        sent = [self.raw_request(port, MESSAGES, parent),
                self.raw_request(port, "/v1/messages/count_tokens?beta=true", sibling, "agent-1")]
        self.assertEqual([body for _, _, body in fake.requests], [parent, sibling])
        for lines, (_, head, body) in zip(sent, fake.requests):
            self.assertEqual(head.split(b"\r\n"), self.expected_head(lines, fake, len(body)))
        self.assertEqual([record["reorder"] for record in log.records(2)],
                         ["not_subagent", "not_subagent"])

    def test_without_reorder_a_subagent_body_reaches_upstream_byte_identical(self):
        fake = self.upstream(json_reply)
        port, log = self.proxy(fake.url)
        sibling = fixture_bytes("sibling1-first.received.json")
        lines = self.raw_request(port, MESSAGES, sibling, "agent-1")
        [(_, head, body)] = fake.requests
        self.assertEqual(body, sibling)
        self.assertEqual(head.split(b"\r\n"), self.expected_head(lines, fake, len(sibling)))
        [record] = log.records(1)
        self.assertNotIn("reorder", record)

    def test_the_health_path_and_a_rejected_request_carry_no_reorder_field(self):
        fake = self.upstream(json_reply)
        port, log = self.proxy(fake.url, subagent_prefix.SubagentPrefix())
        connection = self.client(port)
        connection.request("GET", cache_proxy.HEALTH_PATH)
        self.assertEqual(connection.getresponse().read(), cache_proxy.HEALTH_BODY)
        with socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT) as sock:
            sock.sendall(b"POST /v1/messages HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n")
            reply = http.client.HTTPResponse(sock)
            reply.begin()
            reply.read()
        self.assertEqual(reply.status, 411)
        [record] = log.records(1)
        self.assertEqual((record["status"], record["outcome"]), (411, "rejected"))
        self.assertNotIn("reorder", record)
        self.assertEqual(len(log.lines), 1)

    def test_a_transform_that_raises_forwards_the_original_bytes_and_logs_the_error(self):
        class Raising:
            def transform(self, method, path, headers, body):
                raise KeyError("boom")

        fake = self.upstream(json_reply)
        port, log = self.proxy(fake.url, Raising())
        sibling = fixture_bytes("sibling1-first.received.json")
        lines = self.raw_request(port, MESSAGES, sibling, "agent-1")
        [(_, head, body)] = fake.requests
        self.assertEqual(body, sibling)
        self.assertEqual(head.split(b"\r\n"), self.expected_head(lines, fake, len(sibling)))
        error, request = log.records(2)
        self.assertEqual({key: error[key] for key in ("event", "method", "path", "error")},
                         {"event": "reorder_error", "method": "POST", "path": MESSAGES,
                          "error": "KeyError: 'boom'"})
        self.assertEqual((request["event"], request["reorder"], request["outcome"]),
                         ("request", "error", "complete"))
        self.assertNotIn("error", request)

    def test_an_unknown_outcome_is_a_reorder_error_and_the_original_bytes_go(self):
        class Unknown:
            def transform(self, method, path, headers, body):
                return b"{}", [], "mystery"

        fake = self.upstream(json_reply)
        port, log = self.proxy(fake.url, Unknown())
        sibling = fixture_bytes("sibling1-first.received.json")
        lines = self.raw_request(port, MESSAGES, sibling, "agent-1")
        [(_, head, body)] = fake.requests
        self.assertEqual(body, sibling)
        self.assertEqual(head.split(b"\r\n"), self.expected_head(lines, fake, len(sibling)))
        error, request = log.records(2)
        self.assertEqual((error["event"], error["error"]),
                         ("reorder_error", "ValueError: unknown reorder outcome 'mystery'"))
        self.assertEqual(request["reorder"], "error")
```

In `CommandTest`, before `test_a_port_in_use_exits_1_with_a_bind_failed_line`, add:

```python
    def test_help_lists_reorder(self):
        completed = self.run_command("--help")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--reorder", completed.stdout)

    def test_the_command_with_reorder_logs_the_flag_and_the_outcome(self):
        fake = FakeUpstream(json_reply)
        self.addCleanup(fake.close)
        process = self.start("--port", "0", "--upstream", fake.url, "--reorder")
        listening = self.read_record(process.stderr)
        self.assertEqual((listening["event"], listening["reorder"]), ("listening", True))
        self.assertNotIn("keepalive", listening)
        received = fixture_bytes("sibling1-first.received.json")
        connection = http.client.HTTPConnection("127.0.0.1", listening["port"], timeout=TIMEOUT)
        self.addCleanup(connection.close)
        connection.request("POST", MESSAGES, body=received,
                           headers={"x-claude-code-agent-id": "agent-1"})
        response = connection.getresponse()
        self.assertEqual((response.status, response.read()), (200, b"{}"))
        record = self.read_record(process.stderr)
        self.assertEqual(record["reorder"], "applied")
        [(_, _, body)] = fake.requests
        self.assertNotEqual(body, received)
```

In `tests/test_cache_keepalive.py`, import `subagent_prefix` beside `cache_keepalive, cache_proxy`, and import `fixture` and `holders` from `tests.test_cache_proxy` beside the names already imported. Give `KeepaliveProxyTest.start` the signature `start(self, responder, keepalive=None, reorder=None)` and build the server as `cache_proxy.ProxyServer(0, upstream, self.log, keepalive=keepalive, reorder=reorder)`. Add to `KeepaliveProxyTest`, before `test_a_keepalive_whose_observe_raises_forwards_unchanged_and_logs_one_error` (D18, D27; the variant drops every `ttl` and `thinking` so the keepalive tracks it):

```python
    def test_with_the_reorder_the_ping_replays_the_reordered_body(self):
        value = fixture("sibling1-first.received.json")
        for holder in holders(value):
            if isinstance(holder.get("cache_control"), dict):
                holder["cache_control"].pop("ttl", None)
        value.pop("thinking", None)
        raw = encode(value)
        expected, _, outcome = subagent_prefix.SubagentPrefix().transform(
            "POST", MESSAGES, forwarded(AGENT_P, length=len(raw)), raw)
        self.assertEqual(outcome, "applied")
        self.assertEqual(cache_keepalive.classify(
            "POST", MESSAGES, forwarded(AGENT_P, length=len(expected)), expected).outcome, "tracked")
        fake, port, keepalive = self.start(sse_reply("tool_use"),
                                           reorder=subagent_prefix.SubagentPrefix())
        _, status, _ = self.send(port, AGENT_P, raw)
        self.assertEqual(status, 200)
        [(_, head, received)] = fake.requests
        self.assertEqual(received, expected)
        self.assertIn(b"Content-Length: %d" % len(expected), head.split(b"\r\n"))
        [record] = self.stream.records(1)
        self.assertEqual((record["reorder"], record["keepalive"]), ("applied", "tracked"))
        self.clock.advance(270)
        [ping] = keepalive.tick()
        self.assertEqual(json.loads(ping.body), dict(json.loads(expected), max_tokens=1))
        self.assertEqual([length for name, length in ping.headers if name == "Content-Length"],
                         [str(len(ping.body))])
```

- [ ] **Step 3: Run the tests and watch them fail**

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_cache_proxy.py tests/test_cache_keepalive.py 2>&1 | grep -E '^(FAIL|ERROR):|^Ran|^FAILED|^OK'`
Expected: FAILED (failures=1, errors=26). Every case that builds a `ProxyServer` through `proxy()` or `start()` errors with `TypeError: ProxyServer.__init__() got an unexpected keyword argument 'reorder'`; `test_help_lists_reorder` fails; `test_the_command_with_reorder_logs_the_flag_and_the_outcome` errors because the command exits 2 on an unknown argument. The `SubagentPrefixTest` cases pass.

- [ ] **Step 4: Write the Nix check (scratch) and watch it fail**

Save as `$S/i429/nix-check.sh`:

```bash
#!/usr/bin/env bash
# Task 3's service check: both darwin agents and the anis-desktop unit run --keepalive --reorder (#429 D17).
set -euo pipefail
nixe() { nix eval --extra-experimental-features 'nix-command flakes' --json "$1"; }
for host in mbp eleven-m5; do
  nixe ".#darwinConfigurations.$host.config.home-manager.users.anis.launchd.agents.claude-cache-proxy.config.ProgramArguments" |
    jq -e 'length == 5 and (.[0] | endswith("-agent-tools-cache-proxy")) and .[1:] == ["--port", "27183", "--keepalive", "--reorder"]' >/dev/null
done
nixe '.#nixosConfigurations.anis-desktop.config.home-manager.users.anis.systemd.user.services.claude-cache-proxy.Service.ExecStart' |
  jq -e '[.] | flatten | length == 1 and (.[0] | test("-agent-tools-cache-proxy --port 27183 --keepalive --reorder$"))' >/dev/null
test "$(grep -c '27183' home/common/claude-code/default.nix)" -eq 1
echo services-reorder
```

Run (timeout 900 s): `launch-scope exec … -- bash $S/i429/nix-check.sh`
Expected: FAIL at the first `jq -e`; at the starting commit mbp's arguments are `[<launcher>, "--port", "27183", "--keepalive"]`.

- [ ] **Step 5: Implement the flag in `cache_proxy.py`**

Replace the module docstring's second paragraph with:

```text
`cache-proxy --port N [--upstream URL] [--keepalive] [--reorder]` binds 127.0.0.1 only and
serves until killed. It forwards requests and responses unchanged apart from `Host` and
hop-by-hop headers, answers `GET /_proxy/health` itself, and writes one JSON line per forwarded
request to stderr. With `--keepalive` it also replays idle subagent conversations' last requests
with `max_tokens=1` (`agent_tools.cache_keepalive`, #423); with `--reorder` it reorders each
subagent's first user message (`agent_tools.subagent_prefix`, #429) before the keepalive sees the
request. Its forwarding changes only as those modules describe.
```

Then, which pins the D17 wire format and the D18 order:

- `ProxyServer.__init__(self, port: int, upstream: Upstream, log: LineLog, keepalive=None, reorder=None)` stores `self.reorder = reorder` after `self.keepalive`.
- `ProxyHandler.setup` also sets `self._reorder_outcome = None`, and `_handle`'s first reset becomes `self._track, self._observed, self._reorder_outcome = None, False, None`.
- `_log_request`, right after building `fields` and before the `error` field: `if self._reorder_outcome is not None: fields["reorder"] = self._reorder_outcome`. `_reject` is unchanged, so a rejected request, logged before any transform, carries no `reorder`.
- A new method before `_track_call`:

```python
    def _reorder(self, headers, body):
        """The body, headers and outcome to forward (#429 D17, D20). A transform that raises, or
        that returns an outcome outside its closed set, forwards the original bytes and headers
        and is logged at once."""
        # Imported here because subagent_prefix imports cache_keepalive, which imports this module.
        from agent_tools.subagent_prefix import OUTCOMES
        try:
            forwarded, sent, outcome = self.server.reorder.transform(self.command, self.path,
                                                                     headers, body)
            if outcome not in OUTCOMES:
                raise ValueError(f"unknown reorder outcome {outcome!r}")
        except Exception as error:
            self.server.log.write("reorder_error", method=self.command, path=self.path,
                                  error=f"{type(error).__name__}: {error}")
            return body, headers, "error"
        return forwarded, sent, outcome
```

- In `_handle`, between `headers = self._upstream_headers()` and `self._observe(headers, body)`:

```python
        if self.server.reorder is not None:
            body, headers, self._reorder_outcome = self._reorder(headers, body)
```

- `build_parser()` adds, after `--keepalive`: `parser.add_argument("--reorder", action="store_true", help="reorder each Claude Code subagent's first user message so sibling subagents share a cached start-up prefix (#429)")`.
- In `main()`, before the `try` that builds the server:

```python
    reorder = None
    if args.reorder:
        # Imported here because subagent_prefix imports cache_keepalive, which imports this module.
        from agent_tools import subagent_prefix
        reorder = subagent_prefix.SubagentPrefix()
```

  The server becomes `ProxyServer(args.port, args.upstream, log, keepalive, reorder)`, and the `listening` line's flags become `flags = {name: True for name, part in (("keepalive", keepalive), ("reorder", reorder)) if part is not None}`, passed as `**flags`.

- [ ] **Step 6: Turn the flag on in the service**

In `home/common/claude-code/default.nix`, add `"--reorder"` as the last element of `cacheProxyArgs`, after `"--keepalive"`. Below the comment line ``# `--keepalive` (#423) turns on the keepalive pings; dropping it and rebuilding turns them off.`` add ``# `--reorder` (#429) reorders each subagent's first user message so siblings share a cached start-up prefix; dropping it and rebuilding turns that off.`` Change `Unit.Description` to `"Claude Code cache proxy (Anthropic API, with keepalive pings and the subagent prefix reorder)"`.

- [ ] **Step 7: Update the docs**

In `python/README.md` § `cache-proxy`, change the synopsis `` `cache-proxy --port N [--upstream URL] [--keepalive]` (#422) `` to `` `cache-proxy --port N [--upstream URL] [--keepalive] [--reorder]` (#422) ``, and `without `--keepalive`, forwards each request's` to `without `--keepalive` or `--reorder`, forwards each request's`. After the `--keepalive` paragraph, as the section's last paragraph, add:

> `--reorder` (#429, `agent_tools.subagent_prefix`) reorders a Claude Code subagent's first user message so that two subagents of one type share a cached start-up prefix. A `POST` to `/v1/messages` (any query) with a non-empty `x-claude-code-agent-id` is parsed as strict JSON (a duplicate key or `NaN` is `unparsed`); every other request is `not_subagent` and is never parsed, and so is a body whose `system[0]` is not a text block starting `x-anthropic-billing-header:` with `cc_is_subagent=true` among its `;`-separated fields. A request with no assistant message is a first request, and its agent id is registered when it is reordered (in memory, at most 4,096 ids, oldest out first, forgotten on restart); a later request is reordered only when its id is registered, so a forked subagent, which carries its parent's first message, passes as `unregistered`. The reorder needs `messages[0]` to be a user message of text blocks: attachments (text starting `<system-reminder>`), budget lines (whole text `<total_tokens>N tokens left</total_tokens>`, `N` digits or `Infinite`) and exactly one other block, the prompt, which is not first. Only its last block may carry a `cache_control`, and the body's marks (on `tools`, `system`, each message block after its inner content, then a top-level one) number at most four, are objects with a `ttl` of `5m` (the default) or `1h`, and never grow longer in prefix order; anything else is `shape`. The output keeps every block before the prompt and every attachment after it in order, then the prompt, then the budget lines that followed it, and a mark on the original last block moves to the new last block. With fewer than four marks, the block just before the prompt gains `{"type":"ephemeral"}` with the `ttl` of the nearest mark after it, else of the nearest before it, else none (`applied`); with four, nothing is added (`applied_at_cap`). No existing mark is retimed or removed, and the billing header is never changed. A reordered body is re-encoded as compact UTF-8 JSON in its key order, with every `Content-Length` value replaced; every other outcome forwards the client's bytes and headers. The transform runs after the upstream headers are assembled and before the keepalive's observation, so a keepalive candidate and its pings carry the reordered body. With the flag, the `listening` line gains `"reorder":true` and each `request` line that reached the transform gains `reorder`: `applied`, `applied_at_cap`, `not_subagent`, `unregistered`, `unparsed`, `shape` or `error`. A request rejected while its body was read (`411`, `400`) and the health path carry none. An exception from the transform, or an outcome outside that set, forwards the original bytes and headers and is logged at once as a `reorder_error` line with `method`, `path` and `error`. Without the flag no transform object exists, and every byte sent upstream and every log line is as described above.

In `home/common/claude-code/README.md` § Cache proxy: change `it runs the \`cache-proxy\` launcher with \`--port 27183 --keepalive\`` to `it runs the \`cache-proxy\` launcher with \`--port 27183 --keepalive --reorder\``. After the sentence that ends `turns the pings off.`, insert:

> It also runs with `--reorder` (#429), which `python/README.md` § `cache-proxy` describes: each subagent's first user message is reordered so that sibling subagents of one type share a cached start-up prefix, and every other request passes through unchanged. The proxy never changes the `x-anthropic-billing-header` line; the re-test that admitted the reorder, with its billing-suffix answer, is `docs/spikes/cache-proxy-prefix-retest.md` § Attempt 2. Dropping `"--reorder"` from `cacheProxyArgs` and rebuilding turns it off.

In the next sentence, change `To compare the two, run the built launcher by hand in the foreground on \`--port 0\`, once with and once without the flag,` to `To compare either flag's effect, run the built launcher by hand in the foreground on \`--port 0\`, once with and once without that flag,`, and change its `with \`ENABLE_TOOL_SEARCH=true\`` to `with \`ENABLE_TOOL_SEARCH=true\` and \`CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown\`, which a routed launch also exports`.

- [ ] **Step 8: Verify**

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_cache_proxy.py tests/test_cache_keepalive.py 2>&1 | tail -n 5`. Expected: `OK`, every test, no warnings.

Run (timeout 3600 s): `launch-scope exec … -- just build`. Expected: exit 0.

Run (timeout 900 s): `launch-scope exec … -- bash $S/i429/nix-check.sh`. Expected: `services-reorder`.

Run (timeout 30 s):

```bash
set -e
grep -qF -- '[--keepalive] [--reorder]' python/README.md
grep -qF 'without `--keepalive` or `--reorder`, forwards' python/README.md
grep -qF -- '`--port 27183 --keepalive --reorder`' home/common/claude-code/README.md
grep -qF 'cache-proxy-prefix-retest.md` § Attempt 2' home/common/claude-code/README.md
if grep -qF 'To compare the two,' home/common/claude-code/README.md; then exit 1; fi
git diff --stat 20241ee3 -- home lib justfile python tests flake.lock | tail -n 12
```

Expected: exit 0. The `--stat` lists only this task's files, Task 2's files and Task 1's fixtures.

- [ ] **Step 9: Commit**

```bash
git add python/agent_tools/cache_proxy.py tests/test_cache_proxy.py tests/test_cache_keepalive.py home/common/claude-code/default.nix home/common/claude-code/README.md python/README.md
launch-commit … -- -m "feat(cache-proxy): --reorder before the keepalive, on in both hosts' services (issue 429)" -m "<session trailers>"
```
