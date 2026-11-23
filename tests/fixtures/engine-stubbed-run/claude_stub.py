"""A stand-in for the account launcher in the engine's stubbed runs.

Run as `python claude_stub.py <scenario.json> <log> <launcher args...>`. It reads stdin (the
prompt) and takes the value after `--json-schema`. The scenario file is one JSON object of replies
keyed by the name a reply schema requires (`verdict` for the applicability step, `lane` for the
lane step); the stub picks the entry whose key is the first name of the schema's `required` list
that the scenario holds. It appends `{"argv", "key", "prompt"}` as one JSON line to `<log>`,
writes `{"account": "stub"}` to the file named by `CLAUDE_ACCOUNT_ANSWER` when that is set, and
prints `tests/fixtures/engine-session/result-normal.json` with `structured_output` replaced by the
entry and `session_id` by the argv word after `--session-id` (or `--resume`), then exits 0. A
schema whose required names hold no scenario key prints a result with no `structured_output`.
"""

import json
import os
import sys
from pathlib import Path

NORMAL = Path(__file__).resolve().parents[1] / "engine-session" / "result-normal.json"


def word_after(argv: list[str], *flags: str) -> str | None:
    for flag in flags:
        if flag in argv:
            return argv[argv.index(flag) + 1]
    return None


def main(argv: list[str]) -> int:
    scenario = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    log, words = argv[1], argv[2:]
    prompt = sys.stdin.read()
    schema = json.loads(word_after(words, "--json-schema") or "{}")
    key = next((name for name in schema.get("required", []) if name in scenario), None)
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": words, "key": key, "prompt": prompt}, sort_keys=True) + "\n")
    answer = os.environ.get("CLAUDE_ACCOUNT_ANSWER")
    if answer:
        Path(answer).write_text(json.dumps({"account": "stub"}), encoding="utf-8")
    result = json.loads(NORMAL.read_text(encoding="utf-8"))
    session = word_after(words, "--session-id", "--resume")
    if session is not None:
        result["session_id"] = session
    if key is None:
        result.pop("structured_output", None)
    else:
        result["structured_output"] = scenario[key]
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
