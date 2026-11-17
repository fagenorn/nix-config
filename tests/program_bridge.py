"""Program bridge (issue 1142): run a Workflow program under node and answer
its agent() calls from a Python actor.

`run_program(program, args, actor)` starts tests/program_bridge.mjs, which runs
the program in-process and relays every agent() call here. The actor receives
each agent message and returns the reply; raising `AgentThrow` makes that one
agent call throw in the program, and any other exception kills node and is
re-raised unchanged.

Wire format (the contract of this file and program_bridge.mjs; exact). One JSON
object per line, UTF-8, newline-terminated.
  1. Python -> node, first line: {"program": "<absolute path of the .js>", "args": {...}}
  2. Node -> Python, agent call: {"type": "agent", "id": <int, from 1>, "label": <str|null>,
     "program": "<basename without .js>", "issue": <int|null>, "mode": <str|null>,
     "prompt": "<prompt>", "schema": <object|null>, "agentType": <str|null>}
  3. Python -> node, answer: {"id": <id>, "reply": <any JSON>} or {"id": <id>, "throw": "<message>"}.
  4. Node -> Python, child returned: {"type": "child", "issue": <int|null>, "mode": <str|null>,
     "program": "<basename>", "result": <value|null>}; no answer expected.
  5. Node -> Python, last line: {"type": "result", "result": <value|null>, "error": <str|null>,
     "logs": [<str>]}; node then exits 0.

`run_program` returns {"result", "error", "logs", "children"}. It kills node and
raises AssertionError when the run exceeds `timeout`, and raises AssertionError
carrying node's stderr when node exits non-zero or ends without a result line.
"""
import json
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable

# Resolved at import, before a test patches PATH.
NODE = shutil.which("node")
BRIDGE = Path(__file__).with_name("program_bridge.mjs")


class AgentThrow(Exception):
    """Raised by an actor to make one agent call throw in the program."""


def run_program(
    program: Path,
    args: dict,
    actor: Callable[[dict], object],
    *,
    node: str | None = None,
    timeout: float = 600.0,
) -> dict:
    node = node or NODE
    if node is None:
        raise AssertionError("node is not on PATH; the program bridge needs it")
    proc = subprocess.Popen(
        [node, str(BRIDGE)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    stderr_chunks: list[str] = []
    drain = threading.Thread(target=lambda: stderr_chunks.append(proc.stderr.read()), daemon=True)
    drain.start()
    timed_out = threading.Event()

    def expire():
        timed_out.set()
        proc.kill()

    watchdog = threading.Timer(timeout, expire)
    watchdog.start()
    children: list[dict] = []
    final = None
    try:
        proc.stdin.write(json.dumps({"program": str(program), "args": args}) + "\n")
        proc.stdin.flush()
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            message = json.loads(line)
            kind = message.get("type")
            if kind == "agent":
                try:
                    answer = {"id": message["id"], "reply": actor(message)}
                except AgentThrow as thrown:
                    answer = {"id": message["id"], "throw": str(thrown)}
                try:
                    proc.stdin.write(json.dumps(answer) + "\n")
                    proc.stdin.flush()
                except (BrokenPipeError, ValueError):
                    break
            elif kind == "child":
                children.append(
                    {key: message[key] for key in ("issue", "mode", "program", "result")}
                )
            elif kind == "result":
                final = message
                break
        if final is not None:
            try:
                proc.stdin.close()
            except (BrokenPipeError, ValueError):
                pass
        code = proc.wait()
        drain.join(timeout=10)
        if timed_out.is_set():
            raise AssertionError(f"program bridge timed out after {timeout} s")
        stderr = "".join(stderr_chunks)
        if final is None:
            raise AssertionError(f"program bridge ended without a result line (exit {code}): {stderr}")
        if code != 0:
            raise AssertionError(f"program bridge exited {code}: {stderr}")
        return {
            "result": final["result"],
            "error": final["error"],
            "logs": final["logs"],
            "children": children,
        }
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    finally:
        watchdog.cancel()
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except Exception:
                pass
        try:
            proc.stdin.close()
        except Exception:
            pass
