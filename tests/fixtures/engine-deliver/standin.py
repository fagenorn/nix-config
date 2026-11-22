"""A stand-in command for the engine's command-step tests.

Run as `python standin.py <mode> ...`; `rest` is the remaining argv words. It
prints at most one compact JSON line.

  verdict <word> <exit> rest...  prints {"argv": rest, "verdict": word}, exits <exit>
  json <exit> rest...            prints {"argv": rest}, exits <exit>
  silent <exit> rest...          prints nothing, exits <exit>
  record <log> rest...           appends {"argv", "cwd", "pid"} to <log>, prints it, exits 0
  block <release> rest...        waits for <release> to exist (exits 1 after 120 s),
                                 then prints {"argv": rest} and exits 0
  gate <log> <flag> rest...      appends {"argv": rest} to <log>, prints it, exits 0 when
                                 <flag> exists, else 1 (no verdict in the document)
  effect <log> <kill-before> <kill-after> rest...
                                 if <kill-before> exists: removes it, kills its parent with
                                 SIGKILL and exits 0 printing nothing. Else appends {"argv": rest}
                                 to <log> (the effect); if <kill-after> exists and holds the text
                                 of rest joined by spaces, removes it and kills its parent the
                                 same way; else prints {"argv": rest} and exits 0. The flags are
                                 one-shot, so a wrongly repeated command shows as a further line.
  effect-check <log> <checks> rest...
                                 appends {"argv": rest} to <checks>; prints the document with
                                 verdict "ok" when <log> holds a line whose argv is rest, else
                                 "absent"; exits 0
  parity <log> rest...           n is the line count of <log>; appends {"argv": rest}; prints
                                 {"argv": rest, "n": n % 2}; exits 0 (0, 1, 0, 1 across calls)
  hold <pidfile> <escape> rest... prints {"argv": rest, "detail": "marker-hold"} to stdout and
                                 marker-hold-err to stderr, starts a 60 s grandchild holding both
                                 (in its own session when <escape> is 1), writes its pid to
                                 <pidfile>, sleeps 60 s, exits 0
  answers <log> <answers.json> rest... appends {"argv": rest} to <log>; takes answer
                                 min(lines already in <log>, last) of <answers.json> (a list of
                                 {"stdout", "stderr"?, "exit", "sleep"?, "pidfile"?}), writes its
                                 stdout and stderr, flushes, writes its pid to "pidfile" when the
                                 answer names one, sleeps "sleep" seconds, exits "exit"
"""

import json
import os
import signal
import subprocess
import sys
import time


def emit(document: dict) -> None:
    print(json.dumps(document, sort_keys=True, separators=(",", ":")), flush=True)


def append(log: str, document: dict) -> None:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")


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
    if mode == "gate":
        log, flag, rest = words[0], words[1], words[2:]
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"argv": rest}, sort_keys=True, separators=(",", ":")) + "\n")
        emit({"argv": rest})
        return 0 if os.path.exists(flag) else 1
    if mode == "effect":
        log, before, after, rest = words[0], words[1], words[2], words[3:]
        if os.path.exists(before):
            os.remove(before)
            os.kill(os.getppid(), signal.SIGKILL)
            return 0
        append(log, {"argv": rest})
        if os.path.exists(after) and open(after, encoding="utf-8").read() == " ".join(rest):
            os.remove(after)
            os.kill(os.getppid(), signal.SIGKILL)
            return 0
        emit({"argv": rest})
        return 0
    if mode == "effect-check":
        log, checks, rest = words[0], words[1], words[2:]
        append(checks, {"argv": rest})
        happened = os.path.exists(log) and any(
            json.loads(line)["argv"] == rest for line in open(log, encoding="utf-8"))
        emit({"argv": rest, "verdict": "ok" if happened else "absent"})
        return 0
    if mode == "parity":
        log, rest = words[0], words[1:]
        count = sum(1 for _ in open(log, encoding="utf-8")) if os.path.exists(log) else 0
        append(log, {"argv": rest})
        emit({"argv": rest, "n": count % 2})
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
    if mode == "answers":
        log, answers_file, rest = words[0], words[1], words[2:]
        try:
            with open(log, encoding="utf-8") as handle:
                count = len(handle.readlines())
        except FileNotFoundError:
            count = 0
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"argv": rest}, separators=(",", ":")) + "\n")
        with open(answers_file, encoding="utf-8") as handle:
            answers = json.load(handle)
        answer = answers[min(count, len(answers) - 1)]
        sys.stdout.write(answer["stdout"])
        sys.stdout.flush()
        if "stderr" in answer:
            sys.stderr.write(answer["stderr"])
            sys.stderr.flush()
        if "pidfile" in answer:
            with open(answer["pidfile"], "w", encoding="utf-8") as handle:
                handle.write(str(os.getpid()))
        time.sleep(answer.get("sleep", 0))
        return answer["exit"]
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
