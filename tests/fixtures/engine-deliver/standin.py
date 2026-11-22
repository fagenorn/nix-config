"""A stand-in command for the engine's command-step tests.

Run as `python standin.py <mode> ...`; `rest` is the remaining argv words. It
prints at most one compact JSON line.

  verdict <word> <exit> rest...  prints {"argv": rest, "verdict": word}, exits <exit>
  json <exit> rest...            prints {"argv": rest}, exits <exit>
  silent <exit> rest...          prints nothing, exits <exit>
  record <log> rest...           appends {"argv", "cwd", "pid"} to <log>, prints it, exits 0
  block <release> rest...        waits for <release> to exist (exits 1 after 120 s),
                                 then prints {"argv": rest} and exits 0
  hold <pidfile> <escape> rest... prints {"argv": rest, "detail": "marker-hold"} to stdout and
                                 marker-hold-err to stderr, starts a 60 s grandchild holding both
                                 (in its own session when <escape> is 1), writes its pid to
                                 <pidfile>, sleeps 60 s, exits 0
"""

import json
import os
import subprocess
import sys
import time


def emit(document: dict) -> None:
    print(json.dumps(document, sort_keys=True, separators=(",", ":")), flush=True)


def main(argv: list[str]) -> int:
    mode, words = argv[0], argv[1:]
    if mode == "verdict":
        word, code, rest = words[0], int(words[1]), words[2:]
        emit({"argv": rest, "verdict": word})
        return code
    if mode == "json":
        emit({"argv": words[1:]})
        return int(words[0])
    if mode == "silent":
        return int(words[0])
    if mode == "record":
        log, rest = words[0], words[1:]
        document = {"argv": rest, "cwd": os.getcwd(), "pid": os.getpid()}
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
        emit(document)
        return 0
    if mode == "block":
        release, rest = words[0], words[1:]
        deadline = time.monotonic() + 120
        while not os.path.exists(release):
            if time.monotonic() > deadline:
                return 1
            time.sleep(0.05)
        emit({"argv": rest})
        return 0
    if mode == "hold":
        pidfile, escape, rest = words[0], words[1], words[2:]
        emit({"argv": rest, "detail": "marker-hold"})
        print("marker-hold-err", file=sys.stderr, flush=True)
        grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                      start_new_session=escape == "1")
        with open(pidfile, "w", encoding="utf-8") as handle:
            handle.write(str(grandchild.pid))
        time.sleep(60)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
