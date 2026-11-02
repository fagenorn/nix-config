# Task 4: Proxy gzip and header restore (winner G, C or E2)

This task covers spec § Pass branch: proxy gzip and header restore, per D7 and D12, with D4's measured surface. It builds the screen winner's proxy half into `agent_tools.cache_proxy`: request-body gzip with the body-parse rejection latch for G, C and E2, plus the first-party header restore for E2 only.

**Files:**
- Modify: `python/agent_tools/cache_proxy.py`
- Modify: `tests/test_cache_proxy.py`
- Modify: `python/README.md` (§ `cache-proxy`)
- Modify: `home/common/claude-code/README.md` (§ Cache proxy, one clause)

**Interfaces:**
- Consumes:
  - the whole-line `Screen winner:` and, for E2, the line `Missing first-party headers: <name=value[, name=value]…>` in `docs/spikes/cache-proxy-ttft-gap.md`;
  - the existing `ProxyServer`, `ProxyHandler._upstream_headers()`, `._send_request(body)`, `._handle()`, `._relay(response)`, `._log_request(...)`, `Relay`, `LineLog`, `dropped_names`, `ERROR_BODY_LIMIT` and `UPSTREAM_FAILURES`;
  - in the tests, `FakeUpstream`, `RecordingStream`, `ProxyCase`, `json_reply`, `JSON_REPLY` and `read_head`.
- Produces for Task 5:
  - module constants `GZIP_PATH = "/v1/messages"`, `GZIP_MIN_BYTES = 4096`, `GZIP_LEVEL = 6`, `BODY_PARSE_REJECTIONS` (the two exact messages) and `BODY_PARSE_PREFIX = "bad json: "`;
  - E2 only: `FIRST_PARTY_HEADERS: tuple[tuple[str, str], ...]`;
  - `decode_body(content_encoding: str | None, body: bytes) -> bytes | None`;
  - `is_body_parse_rejection(decoded: bytes | None) -> bool`;
  - `ProxyServer.gzip_enabled: bool` and `ProxyServer.disable_gzip(status: int, error_body: bytes) -> None`;
  - two new fields on every `request` log line: `request_bytes` and `upstream_request_bytes`.

**Invariants:**
- **Hot path.** A request is on the hot path when it is a `POST` whose path is exactly `GZIP_PATH` (a query string is allowed).
- **When gzip applies.** Gzip applies to a hot request with no client `Content-Encoding`, a body of at least `GZIP_MIN_BYTES` and `server.gzip_enabled`. Every other request goes upstream byte for byte as before.
- **Gzipped head.** The client's `Content-Length` line is replaced in place by `Content-Encoding: gzip` and then `Content-Length: <compressed length>`. Every other header keeps its name, order and value (D12).
- **Last step.** Gzip is the last transformation before upstream (spec § Coordination with #429).
- **Rejection resend.** A 400 to a gzipped request whose decoded body is a body-parse rejection is never relayed. The proxy resends the identity body once with the client's original headers, relays that second answer, and calls `disable_gzip` (D7).
- **Other 400s.** Any other 400 to a gzipped request is relayed unchanged, as a sized response, and gzip stays on. That covers an undecodable encoding and any other message (D12).
- **The latch.** `disable_gzip` is one-way and process-wide. It writes exactly one `gzip_disabled` line (`status`, plus `error_body` as decoded text up to `ERROR_BODY_LIMIT`), however many threads call it.
- **E2 headers.** Each `FIRST_PARTY_HEADERS` pair the client lacks (names compared case-insensitively) is appended after the client's headers, in tuple order, on hot requests only. A header the client sent is never edited or duplicated.
- **Byte counts.** `request_bytes` is the client body's length, and `upstream_request_bytes` the length of the body sent on the final upstream attempt. Both are `null` on a request rejected before forwarding (D12).

- [ ] **Step 0: Branch gate**

Run (timeout 30 s): `W=$(grep -Ex 'Screen winner: (E3|G|E1|C|E2|none)' docs/spikes/cache-proxy-ttft-gap.md | sed 's/^Screen winner: //'); test "$(printf '%s\n' "$W" | grep -c .)" -eq 1 && echo "$W"`
If it prints `E3`, `E1` or `none`, report DONE with `skipped: Screen winner is <W>` and commit nothing. If the check fails, report BLOCKED. Otherwise build gzip, and for `E2` also the header restore.

- [ ] **Step 1: Write the failing tests**

In `tests/test_cache_proxy.py`, change the module docstring's first line to `` `cache-proxy` forwards requests and streamed responses unchanged (#422), apart from #438's request gzip. `` (E2: `` …apart from #438's request gzip and first-party headers. ``), add `import gzip` to the imports, and add these after `closed_port`:

```python
GZIP_MIN = 4096  # the client's own threshold (spec § What the pinned binary already says), pinned here on purpose
PREFIX, SUFFIX = b'{"model":"x","messages":[{"role":"user","content":"', b'"}]}'
LARGE = PREFIX + b"a" * (GZIP_MIN - len(PREFIX) - len(SUFFIX)) + SUFFIX
REJECTIONS = ("The request body is not valid JSON",
              "Failed to parse request: could not parse request body as JSON",
              "bad json: unexpected end of input")


def error_reply(message, encoding=None):
    body = json.dumps({"type": "error", "error": {"type": "invalid_request_error",
                                                  "message": message}}).encode()
    if encoding == "gzip":
        body = gzip.compress(body)
    head = b"HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\n"
    if encoding:
        head += b"Content-Encoding: %s\r\n" % encoding.encode()
    return head + b"Content-Length: %d\r\n\r\n" % len(body) + body


def gzipped(head):
    return b"\r\ncontent-encoding: gzip" in head.lower()
```

Then add this class after `ForwardingTest`:

```python
class GzipTest(ProxyCase):
    def send(self, port, path, body, headers=()):
        """One POST on its own client connection; the reply's status and body."""
        lines = [b"POST %s HTTP/1.1" % path, b"Host: 127.0.0.1:%d" % port,
                 *(b"%s: %s" % pair for pair in headers),
                 b"Content-Type: application/json", b"Content-Length: %d" % len(body)]
        with socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT) as sock:
            sock.sendall(b"\r\n".join(lines) + b"\r\n\r\n" + body)
            reply = http.client.HTTPResponse(sock)
            reply.begin()
            return reply.status, reply.read()

    def test_a_messages_post_at_the_threshold_is_gzipped_with_its_length_replaced_in_place(self):
        fake = self.upstream(json_reply)
        port, log = self.proxy(fake.url)
        self.assertEqual(self.send(port, b"/v1/messages?beta=true", LARGE, [(b"anthropic-beta", b"first")]),
                         (200, b"{}"))
        [(_, head, received)] = fake.requests
        self.assertEqual(gzip.decompress(received), LARGE)
        self.assertEqual(head.split(b"\r\n"), [
            b"POST /v1/messages?beta=true HTTP/1.1",
            b"Host: 127.0.0.1:%d" % fake.server.server_address[1],
            b"anthropic-beta: first",
            b"Content-Type: application/json",
            b"Content-Encoding: gzip",
            b"Content-Length: %d" % len(received),
            b"",
        ])
        [record] = log.records(1)
        self.assertEqual((record["request_bytes"], record["upstream_request_bytes"]),
                         (len(LARGE), len(received)))

    def test_small_bodies_other_paths_and_encoded_bodies_are_forwarded_verbatim(self):
        fake = self.upstream(json_reply)
        port, log = self.proxy(fake.url)
        cases = [(b"/v1/messages", LARGE[:-1], ()),
                 (b"/v1/messages/count_tokens", LARGE, ()),
                 (b"/v1/messages", gzip.compress(LARGE), ((b"Content-Encoding", b"gzip"),))]
        for path, body, headers in cases:
            self.assertEqual(self.send(port, path, body, headers), (200, b"{}"))
        self.assertEqual([received for _, _, received in fake.requests], [body for _, body, _ in cases])
        for (_, head, _), (_, body, headers) in zip(fake.requests, cases):
            self.assertEqual(head.lower().count(b"content-encoding"), len(headers))
            self.assertIn(b"\r\nContent-Length: %d\r\n" % len(body), head)
        self.assertEqual([(r["request_bytes"], r["upstream_request_bytes"]) for r in log.records(3)],
                         [(len(body), len(body)) for _, body, _ in cases])

    def test_a_body_parse_rejection_is_resent_identity_once_and_turns_gzip_off(self):
        for message, encoding in [(m, None) for m in REJECTIONS] + [(REJECTIONS[0], "gzip")]:
            with self.subTest(message=message, encoding=encoding):
                def responder(sock, head, body, message=message, encoding=encoding):
                    sock.sendall(error_reply(message, encoding) if gzipped(head) else JSON_REPLY)
                    return True

                fake = self.upstream(responder)
                port, log = self.proxy(fake.url)
                self.assertEqual(self.send(port, b"/v1/messages", LARGE), (200, b"{}"))
                self.assertEqual(self.send(port, b"/v1/messages", LARGE), (200, b"{}"))
                self.assertEqual([gzipped(head) for _, head, _ in fake.requests], [True, False, False])
                self.assertEqual([received for _, _, received in fake.requests][1:], [LARGE, LARGE])
                records = log.records(3)
                [disabled] = [r for r in records if r["event"] == "gzip_disabled"]
                self.assertEqual(disabled["status"], 400)
                self.assertIn(message, disabled["error_body"])
                self.assertEqual([(r["status"], r["upstream_request_bytes"]) for r in records
                                  if r["event"] == "request"], [(200, len(LARGE))] * 2)

    def test_any_other_400_to_a_gzipped_request_is_relayed_unchanged_and_gzip_stays_on(self):
        replies = [error_reply("max_tokens: 99999999 > 64000"), error_reply(REJECTIONS[0], "br"), JSON_REPLY]

        def responder(sock, head, body):
            sock.sendall(replies.pop(0))
            return True

        fake = self.upstream(responder)
        port, log = self.proxy(fake.url)
        for reply in replies[:2]:
            self.assertEqual(self.send(port, b"/v1/messages", LARGE),
                             (400, reply.split(b"\r\n\r\n", 1)[1]))
        self.assertEqual(self.send(port, b"/v1/messages", LARGE), (200, b"{}"))
        self.assertEqual([gzipped(head) for _, head, _ in fake.requests], [True, True, True])
        self.assertEqual([r["event"] for r in log.records(3)], ["request"] * 3)
```

The slice `replies[:2]` is taken once, before the responder pops anything.

E2 only: the proxy appends the restored headers to every hot request, so two exact-head assertions gain them. In `ForwardingTest.test_request_headers_reach_upstream_verbatim_with_only_host_rewritten` and `GzipTest.test_a_messages_post_at_the_threshold_is_gzipped_with_its_length_replaced_in_place`, insert `*RESTORED` just before the final `b""` of the expected list. Define `RESTORED = [("%s: %s" % pair).encode() for pair in cache_proxy.FIRST_PARTY_HEADERS]` beside `REJECTIONS`. Then add to `GzipTest`:

```python
    def test_first_party_headers_are_appended_once_to_messages_posts_only(self):
        self.assertTrue(cache_proxy.FIRST_PARTY_HEADERS)
        fake = self.upstream(json_reply)
        port, _ = self.proxy(fake.url)
        name, _ = cache_proxy.FIRST_PARTY_HEADERS[0]
        self.send(port, b"/v1/messages", b"{}")
        self.send(port, b"/v1/messages", b"{}", [(name.upper().encode(), b"client-value")])
        self.send(port, b"/v1/messages/count_tokens", b"{}")
        heads = [head.split(b"\r\n") for _, head, _ in fake.requests]
        added = [("%s: %s" % pair).encode() for pair in cache_proxy.FIRST_PARTY_HEADERS]
        self.assertEqual(heads[0][-1 - len(added):-1], added)
        self.assertEqual(sum(line.lower().startswith(name.lower().encode() + b":") for line in heads[1]), 1)
        self.assertIn(name.upper().encode() + b": client-value", heads[1])
        for other, _ in cache_proxy.FIRST_PARTY_HEADERS:
            self.assertFalse(any(line.lower().startswith(other.lower().encode() + b":") for line in heads[2]))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s) from the repository root: `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests.test_cache_proxy.GzipTest 2>&1 | tail -15`
Expected: FAIL or ERROR in every `GzipTest` test. The first fails with `zlib.error` or `BadGzipFile` (the body arrives uncompressed), the second with `KeyError: 'request_bytes'`, and the E2 test with `AttributeError` on `FIRST_PARTY_HEADERS`.

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/cache_proxy.py`, replace the module docstring's words `` forwards requests and responses unchanged apart from `Host` and hop-by-hop headers, `` with `` forwards requests and responses unchanged apart from `Host`, hop-by-hop headers and the request gzip below, `` (E2: `` …, hop-by-hop headers, the request gzip and the first-party headers below, ``), and add the sentence `A large POST to /v1/messages goes upstream gzipped, as Claude Code itself sends it to api.anthropic.com (#438).` (E2 adds: `Every POST to /v1/messages also gets the first-party headers in FIRST_PARTY_HEADERS that it lacks.`). Then implement the following:

1. **Constants and pure helpers** (module level):
   - `decode_body(content_encoding, body)` returns `body` for no encoding or `identity`; `gzip.decompress(body)` for `gzip` and `x-gzip`; and for `deflate`, `zlib.decompress(body)`, falling back to `zlib.decompress(body, -15)`. It returns `None` for any other encoding or on any decode error (D12).
   - `is_body_parse_rejection(decoded)` is true only when `decoded` parses as a JSON object whose `error.message` is a string that is in `BODY_PARSE_REJECTIONS` or starts with `BODY_PARSE_PREFIX`.
   - E2 only: `FIRST_PARTY_HEADERS` holds the pairs from the `Missing first-party headers:` line, in the line's order, under this AC5 comment: `# First-party headers Claude Code drops behind a non-first-party base URL, from the AC1 capture in docs/spikes/cache-proxy-ttft-gap.md. Undocumented (https://github.com/anthropics/claude-code/issues/98464); verified on Claude Code <V>.`
2. **`ProxyServer.__init__`.** Set `self.gzip_enabled = True` and `self.gzip_lock = threading.Lock()`.
3. **`disable_gzip(status, error_body)`.** Under the lock, if `gzip_enabled` is set, clear it and write `self.log.write("gzip_disabled", status=status, error_body=error_body[:ERROR_BODY_LIMIT].decode("utf-8", "replace"))`. Otherwise do nothing.
4. **`_upstream_headers(self, encoded_length=None)`.** With an `int`, the client's `Content-Length` header becomes the two lines of § Invariants in its place. On a hot request (E2), append the missing `FIRST_PARTY_HEADERS`.
5. **`_send_request(self, body, encoded_length=None)`.** Passes `encoded_length` through.
6. **`_handle`.**
   - At its start, set `self._request_bytes = self._upstream_request_bytes = None`. Set `self._request_bytes = len(body)` once the body is read.
   - Decide `gzipped` by § Invariants. Send `gzip.compress(body, compresslevel=GZIP_LEVEL)` with `encoded_length`, or the body itself, and set `_upstream_request_bytes` to the length sent.
   - Inside the existing `try`, if `gzipped` and `response.status == 400`, read `rejection = response.read()` and decode it with `decode_body(response.getheader("Content-Encoding"), rejection)`.
   - On a rejection: call `disable_gzip(400, decoded)`; if `response.will_close`, call `self._connect_upstream()`; send `body` again without `encoded_length` and set `_upstream_request_bytes = len(body)`. The new response then flows through the existing `ttfb_ms`, `_relay` and log path.
   - Otherwise relay the buffered answer with `_relay_buffered(response, rejection)`. Treat its `Relay` as `_relay`'s, and close the upstream connection afterwards when `response.will_close`.
7. **`_relay_buffered(self, response, body)`.**
   - Write the status and reason, then each upstream header except `dropped_names(response.msg)`, `content-length` and `transfer-encoding`.
   - Write `Content-Length: len(body)`, then `body`.
   - Return `Relay(written=len(body), error_body=body[:ERROR_BODY_LIMIT])`.
   - On `OSError`, return `Relay("client_closed")`.
8. **`_log_request`.** Adds `request_bytes=self._request_bytes` and `upstream_request_bytes=self._upstream_request_bytes`.

A rejected request (`_reject`) logs both as `null`, because they are reset at the start of `_handle`.

- [ ] **Step 4: Document**

In `python/README.md` § `cache-proxy`:

1. Replace the words `nothing is added, decoded or retried)` with `apart from the request gzip below, nothing is added, decoded or retried)` (E2: `apart from the request gzip and first-party headers below, nothing else is added, decoded or retried)`).
2. After the sentence ending `holds one keep-alive upstream connection per client connection.`, insert:

   > A `POST` to exactly `/v1/messages` with no `Content-Encoding` and a body of at least 4,096 bytes goes upstream gzipped at level 6, as Claude Code itself sends it to `api.anthropic.com`, with `Content-Encoding: gzip` and the compressed `Content-Length` in place of the client's (#438). If the API answers one with a 400 whose message is one of Claude Code <V>'s body-parse rejections, the identity body is resent once and gzip stays off for the rest of the process (one `gzip_disabled` line); any other answer is relayed as received.

   For E2, append: `Every POST to exactly /v1/messages, whatever its size, that lacks «fill: the FIRST_PARTY_HEADERS names» gets it appended after the client's headers (undocumented first-party headers, anthropics/claude-code#98464, verified on <V>).`
3. In the known-limitation sentence, replace `and bodies are never decoded,` with `and bodies are decoded only to recognise a body-parse rejection of a gzipped request,`.

4. In the paragraph's list of log fields (the one that starts with `method` and `path`), add `request_bytes` (the client body's length) and `upstream_request_bytes` (what the final upstream attempt sent; both `null` for a request rejected before forwarding) after `bytes`.

In `home/common/claude-code/README.md` § Cache proxy, replace `It forwards requests unchanged today;` with `It forwards requests unchanged today apart from gzipping large request bodies (#438);` (E2: `… apart from gzipping large request bodies and adding the first-party headers Claude Code drops behind a loopback base URL to every /v1/messages POST (#438);`).

- [ ] **Step 5: Verify**

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_cache_proxy.py 2>&1 | tail -4`
Expected: `OK`. Every `ForwardingTest` and `CommandTest` test still passes, including `test_request_headers_reach_upstream_verbatim_with_only_host_rewritten`, whose 13-byte body stays verbatim.

Run (timeout 60 s): `if grep -n '«fill' python/agent_tools/cache_proxy.py python/README.md; then exit 1; fi; grep -c 'apart from the request gzip' python/README.md; grep -c 'apart from gzipping large request bodies' home/common/claude-code/README.md; if grep -n 'and hop-by-hop headers,' python/agent_tools/cache_proxy.py; then exit 1; fi`
Expected: `1`, then `1`. For E2, with `$V` set as in the plan root, also run `c=$(grep -B3 '^FIRST_PARTY_HEADERS' python/agent_tools/cache_proxy.py); grep -qF 'issues/98464' <<<"$c" && grep -qF "verified on Claude Code $V" <<<"$c" && echo ac5-ok`, which must print `ac5-ok`.

Run (timeout 3600 s): `just build mbp`. Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/cache_proxy.py tests/test_cache_proxy.py python/README.md home/common/claude-code/README.md
git commit -m "feat(issue-438): the cache proxy gzips large /v1/messages bodies"
```

For E2, the subject is `feat(issue-438): the cache proxy gzips and restores first-party headers`. Report DONE with the variant.
