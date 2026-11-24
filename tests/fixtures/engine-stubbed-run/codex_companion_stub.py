"""A stand-in for `codex-companion`: `python codex_companion_stub.py <answers.json> <log> <argv...>`.

It reads stdin and appends `{"argv", "cwd", "stdin"}` as one JSON line to `<log>`, under an
exclusive `fcntl.flock` of the log (review slices run at once). It then picks its answer from
the list in `<answers.json>`, each `{"stdout": str, "exit": int, "stderr"?: str, "when"?: str}`:
the first answer whose `when` is a substring of stdin, else, among the answers with no `when`,
the one at index `min(earlier log lines that matched no `when`, last)`. It writes that answer
and exits with its `exit`.
"""

import fcntl
import json
import os
import sys


def main(argv: list[str]) -> int:
    answers_path, log_path, *rest = argv
    with open(answers_path, encoding="utf-8") as handle:
        answers = json.load(handle)
    stdin = sys.stdin.read()
    whens = [answer["when"] for answer in answers if "when" in answer]
    plain = [answer for answer in answers if "when" not in answer]
    with open(log_path, "a+", encoding="utf-8") as log:
        fcntl.flock(log, fcntl.LOCK_EX)
        log.seek(0)
        earlier = [json.loads(line) for line in log.read().splitlines()]
        matched = [answer for answer in answers if "when" in answer and answer["when"] in stdin]
        if matched:
            answer = matched[0]
        else:
            unmatched = sum(1 for line in earlier if not any(w in line["stdin"] for w in whens))
            answer = plain[min(unmatched, len(plain) - 1)]
        log.write(json.dumps({"argv": rest, "cwd": os.getcwd(), "stdin": stdin}) + "\n")
        log.flush()
    sys.stdout.write(answer["stdout"])
    sys.stderr.write(answer.get("stderr", ""))
    return answer["exit"]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
