"""Anthropic-protocol shim between Claude Code and a local NInfer server.

NInfer rejects `thinking.display:"omitted"` outright -- deliberately, because it
cannot provide Anthropic's encrypted hidden-reasoning restore semantics
(docs/serving.md, introduced by `feat(serve): complete anthropic messages
semantics`). Claude Code emits exactly that object at every non-zero thinking
budget, so without a rewrite the main agent loop 400s on every request and the
only escape is MAX_THINKING_TOKENS=0, which gives up reasoning altogether.

`summarized` is the nearest value NInfer accepts. It returns visible thinking
where the client asked for none; Claude Code tolerates the extra blocks and
accounts for them normally.

Responses stream through unbuffered: the agent loop is SSE, and buffering it
would hold every token back until the message completed.
"""

import http.client
import http.server
import json
import os
import socketserver
import sys

UPSTREAM_HOST = os.environ["SHIM_UPSTREAM_HOST"]
UPSTREAM_PORT = int(os.environ["SHIM_UPSTREAM_PORT"])

# Hop-by-hop headers must not be forwarded in either direction; content-length
# is recomputed because the rewrite changes the body length.
DROP = {"host", "connection", "content-length", "transfer-encoding",
        "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
        "trailer", "upgrade"}


def rewrite(body):
    if not body:
        return body
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        # Not JSON we understand: pass it through untouched rather than
        # guessing. An unparseable body is the server's business, not ours.
        return body
    thinking = payload.get("thinking")
    if isinstance(thinking, dict) and thinking.get("display") == "omitted":
        thinking["display"] = "summarized"
        return json.dumps(payload).encode()
    return body


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _proxy(self):
        length = int(self.headers.get("content-length") or 0)
        body = rewrite(self.rfile.read(length)) if length else None

        headers = {k: v for k, v in self.headers.items() if k.lower() not in DROP}
        if body is not None:
            headers["Content-Length"] = str(len(body))

        try:
            conn = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=900)
            conn.request(self.command, self.path, body=body, headers=headers)
            upstream = conn.getresponse()
        except OSError as exc:
            self.send_error(502, "upstream unreachable: %s" % exc)
            return

        declared = upstream.getheader("content-length")
        self.send_response(upstream.status)
        for key, value in upstream.getheaders():
            if key.lower() in DROP:
                continue
            self.send_header(key, value)
        if declared is not None:
            self.send_header("Content-Length", declared)
        else:
            # SSE and any other unsized body: re-chunk so each token reaches
            # the client as it arrives instead of waiting for the final byte.
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        try:
            while True:
                # read1 returns whatever has arrived rather than blocking for a
                # full buffer, which is what keeps streaming incremental.
                chunk = upstream.read1(65536)
                if not chunk:
                    break
                if declared is not None:
                    self.wfile.write(chunk)
                else:
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
            if declared is None:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # Claude Code hung up mid-stream (interrupt, or the turn ended).
            pass
        finally:
            conn.close()

    do_GET = _proxy
    do_POST = _proxy
    do_DELETE = _proxy


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    server = Server(("127.0.0.1", 0), Handler)
    # The wrapper reads the chosen port from stdout; binding port 0 avoids
    # colliding with another session's shim.
    sys.stdout.write("%d\n" % server.server_address[1])
    sys.stdout.flush()
    server.serve_forever()


if __name__ == "__main__":
    main()
