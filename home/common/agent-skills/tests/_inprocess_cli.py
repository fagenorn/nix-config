"""Run a Python CLI script inside the test process, shaped like subprocess.run (#262 D4).

`input`, `cwd` and `text` mean what they mean to `subprocess.run` (issue 500 D2, D3).
"""

import io
import os
from pathlib import Path
import subprocess
import sys
import traceback
import types
from unittest import mock


_CODE: dict[str, types.CodeType] = {}


def _captured(stream: io.TextIOWrapper, text: bool) -> str | bytes:
    stream.flush()
    raw = stream.buffer.getvalue()
    if not text:
        return raw
    return raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def run_script(script, args, *, env, input=None, cwd=None, text=True):
    """`subprocess.run([sys.executable, script, *args], input=input, cwd=cwd, env=env,
    capture_output=True, text=text)`, in process.

    The process directory, environment, `sys` streams, `sys.argv` and `__main__` are
    restored on every outcome; a `cwd` that cannot be entered raises its `OSError`
    before the script starts (issue 500 D3).
    """
    path = str(script)
    code = _CODE.get(path)
    if code is None:
        code = _CODE[path] = compile(Path(path).read_bytes(), path, "exec")
    argv = [path, *map(str, args)]
    if input is None:
        data = b""
    elif text:
        data = input.encode("utf-8")
    else:
        data = bytes(input)
    module = types.ModuleType("__main__")
    module.__file__ = path
    stdin = io.TextIOWrapper(io.BytesIO(data), encoding="utf-8")
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    stderr = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="backslashreplace")
    saved = sys.modules.get("__main__")
    returncode = 0
    directory = os.getcwd()
    if cwd is not None:
        os.chdir(cwd)
    try:
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(sys, "argv", argv), \
                mock.patch.object(sys, "stdin", stdin), mock.patch.object(sys, "stdout", stdout), \
                mock.patch.object(sys, "stderr", stderr):
            sys.modules["__main__"] = module
            try:
                exec(code, module.__dict__)
            except SystemExit as exit_:
                if exit_.code is None:
                    returncode = 0
                elif isinstance(exit_.code, int):
                    returncode = exit_.code & 0xFF
                else:
                    print(exit_.code, file=stderr)
                    returncode = 1
            except Exception:
                traceback.print_exc(file=stderr)
                returncode = 1
            finally:
                if saved is None:
                    sys.modules.pop("__main__", None)
                else:
                    sys.modules["__main__"] = saved
    finally:
        os.chdir(directory)
    return subprocess.CompletedProcess([sys.executable, *argv], returncode,
                                       _captured(stdout, text), _captured(stderr, text))
