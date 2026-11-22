"""A stand-in command for the engine's command-step tests.

Run as `python standin.py <mode> ...`; `rest` is the remaining argv words. It
prints at most one compact JSON line.

  verdict <word> <exit> rest...  prints {"argv": rest, "verdict": word}, exits <exit>
  json <exit> rest...            prints {"argv": rest}, exits <exit>
  silent <exit> rest...          prints nothing, exits <exit>
  record <log> rest...           appends {"argv", "cwd", "pid"} to <log>, prints it, exits 0
  block <release> rest...        waits for <release> to exist (exits 1 after 120 s),
                                 then prints {"argv": rest} and exits 0
  stamp <log> <seconds> <exit> rest...
                                 records start = time.time(), sleeps <seconds>, appends one
                                 line {"argv": rest, "end", "pid", "start"} to <log> in a
                                 single write, prints {"argv": rest}, exits <exit>
  emit <exit> <document>         prints <document> verbatim as its one line, exits <exit>
"""

import json
import os
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
    if mode == "stamp":
        log, seconds, code, rest = words[0], float(words[1]), int(words[2]), words[3:]
        start = time.time()
        time.sleep(seconds)
        line = json.dumps({"argv": rest, "end": time.time(), "pid": os.getpid(), "start": start},
                          sort_keys=True, separators=(",", ":")) + "\n"
        descriptor = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(descriptor, line.encode("utf-8"))
        finally:
            os.close(descriptor)
        emit({"argv": rest})
        return code
    if mode == "emit":
        print(words[1], flush=True)
        return int(words[0])
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
