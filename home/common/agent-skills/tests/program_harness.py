"""Support for tests that run a stub-agent harness against a delivery program (issue 1288).

Support only: no TestCase, not a suite member, and not thread-safe (one test at a time uses a server).

One server process per test file serves every harness/program pair that file uses: `server_for(node)` returns
one cached `ProgramServer` per `node` in this Python process (the suite runner runs each member in its own
process, so that is one node process per file), and the first call registers one `atexit` hook that closes
every cached server. `ProgramServer.run(harness, program, scenario)` returns the object
`node <harness> <program>` prints for that scenario on stdin; `run_fresh` is that one-shot call itself.

Wire format, shared with program_server.mjs (its header is the full statement): `node program_server.mjs`
reads one request per line, `{"harness": ..., "program": ..., "scenario": ...}`, and writes exactly one line
per request, `{"ok": true, "out": <what one-shot mode prints>[, "restart": true]}` or
`{"ok": false, "error": <text>[, "restart": true]}`. `"restart": true` means the scenario changed the global
object: the server answers, then ends on its own, and the next run starts a new process.

The request is written by a helper thread so the timeout covers a write the process is not reading.

The process: started on the first run (and on the first run after any failure or close) with stdin and stdout
pipes and a temporary file as stderr, so a program that logs a lot never blocks on an unread pipe. A daemon
thread reads stdout lines into a queue (a `None` at EOF) and `run` waits for one line with the timeout.
On a timeout `run` kills and reaps the process and raises `AssertionError("<failure>: no reply within <t> s")`;
on EOF or a broken pipe it raises `AssertionError("<failure>: the harness exited with <code>: <stderr>")`;
on a line that is not a reply object (a program that wrote to stdout) it kills and reaps the process and raises
`AssertionError("<failure>: the harness wrote a line that is not a reply: <line>")`;
on an `ok: false` reply it raises `AssertionError("<failure>: <error>")` followed by the stderr text written
since the run began, when any. A restart reply closes the process before `run` returns or raises, so `pid` is
`None` afterwards. `close()` closes stdin, waits up to 10 s, kills if still alive, joins the reader thread,
closes the stderr file and returns the exit code (`None` when no process was running).
"""

import atexit
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path

SERVER = Path(__file__).with_name("program_server.mjs")
_STDERR_TAIL = 20000


def run_fresh(node: str, harness: Path, program: Path, scenario: dict, *, timeout: float = 60.0, failure: str = "harness failed") -> dict:
    """Run one scenario in a process of its own, as one-shot mode does."""
    done = subprocess.run(
        [node, str(harness), str(program)], input=json.dumps(scenario), capture_output=True, text=True, timeout=timeout, check=False
    )
    if done.returncode != 0:
        raise AssertionError(f"{failure}: {done.stderr}")
    return json.loads(done.stdout)


class ProgramServer:
    def __init__(self, node: str) -> None:
        self._node = node
        self._proc = None
        self._lines = None
        self._reader = None
        self._err = None

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None and self._proc.poll() is None else None

    def _start(self) -> None:
        self._err = tempfile.TemporaryFile()
        self._proc = subprocess.Popen(
            [self._node, str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._err, text=True, encoding="utf-8"
        )
        lines = self._lines = queue.Queue()
        stdout = self._proc.stdout

        def read() -> None:
            for line in stdout:
                lines.put(line)
            lines.put(None)

        self._reader = threading.Thread(target=read, daemon=True)
        self._reader.start()

    def _stderr_since(self, offset: int) -> str:
        # pread: the child shares this file's offset, so the parent must never seek it.
        fd = self._err.fileno()
        size = os.fstat(fd).st_size
        start = max(offset, size - _STDERR_TAIL)
        return os.pread(fd, size - start, start).decode("utf-8", "replace") if size > start else ""

    def run(self, harness: Path, program: Path, scenario: dict, *, timeout: float = 60.0, failure: str = "harness failed") -> dict:
        if self._proc is None:
            self._start()
        offset = os.fstat(self._err.fileno()).st_size
        request = json.dumps({"harness": str(harness), "program": str(program), "scenario": scenario}) + "\n"
        # The write runs in its own thread: a request larger than the pipe, sent to a node that has stopped reading, blocks, and the timeout must cover it.
        deadline = time.monotonic() + timeout
        stdin = self._proc.stdin

        def send() -> None:
            try:
                stdin.write(request)
                stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass  # the reader thread then reports EOF

        writer = threading.Thread(target=send, daemon=True)
        writer.start()
        try:
            line = self._lines.get(timeout=max(0.0, deadline - time.monotonic()))
        except queue.Empty:
            self._proc.kill()
            writer.join()
            self.close()
            raise AssertionError(f"{failure}: no reply within {timeout} s") from None
        writer.join()
        if line is None:
            stderr = self._stderr_since(offset)
            code = self.close()
            raise AssertionError(f"{failure}: the harness exited with {code}: {stderr}")
        try:
            reply = json.loads(line)
            if not isinstance(reply, dict) or not isinstance(reply.get("ok"), bool):
                raise ValueError("not a reply")
        except ValueError:
            # A program that wrote to stdout put a line ahead of its reply: the stream is out of step, so the process is discarded, never reused.
            stderr = self._stderr_since(offset)
            self._proc.kill()
            self.close()
            raise AssertionError(f"{failure}: the harness wrote a line that is not a reply: {line[:200]!r} {stderr}".rstrip()) from None
        stderr = self._stderr_since(offset)
        if reply.get("restart"):
            self.close()
        if not reply["ok"]:
            raise AssertionError(f"{failure}: {reply['error']}" + (f" {stderr}" if stderr else ""))
        return reply["out"]

    def close(self) -> int | None:
        proc = self._proc
        if proc is None:
            return None
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        self._reader.join()
        proc.stdout.close()
        self._err.close()
        self._proc = self._lines = self._reader = self._err = None
        return proc.returncode


_servers: dict[str, ProgramServer] = {}


def _close_all() -> None:
    for server in _servers.values():
        server.close()


def server_for(node: str) -> ProgramServer:
    """The one server of this Python process for `node`."""
    if not _servers:
        atexit.register(_close_all)
    if node not in _servers:
        _servers[node] = ProgramServer(node)
    return _servers[node]
