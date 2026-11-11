"""`plan-amend`: the contained, all-or-nothing plan edit (#811).

`plan-amend apply --input <path>` (`--input -` reads stdin) takes one strict JSON
object with exactly these members and prints exactly one JSON line:

    {"plan_dir": str, "plan_root": str, "stop": str,
     "edits": [{"file": str, "find": str, "replace": str}, ...]}

`plan_dir` is absolute, normalised and not `/`; `plan_root` is the plan file; `stop`
is a non-empty string with no line break; `edits` is a non-empty list, each `find`
non-empty. Anything else is an input error.

Output, always an object with `status`, `edits` and `refused`:

- `applied` (exit 0): `edits` has one `{file, exists, occurrences, already}` entry per
  request edit, in request order; `refused` is `[]`.
- `refused` (exit 1), nothing written: `refused` lists `{file, reason}` with `reason`
  one of `outside plan_dir`, `missing`, `unreadable`, `not found`, `not unique`.
  A containment refusal comes before any read and its `edits` is `[]`.
- `error` (exit 2): bad input or a failed write; `edits` and `refused` are `[]` and
  `detail` is a one-line string.

Containment: a path is inside only when it is lexically under `plan_dir + "/"`
(normalised, exact case) and its `os.path.realpath` is under
`os.path.realpath(plan_dir) + os.sep`. `plan_root` and every `file` are checked
before any file is read, so nothing outside `plan_dir` is read or written.

Each edit replaces the one occurrence of `find` (overlapping matches count) in its
file, in request order, later edits seeing earlier ones. Every applied edit adds
`- Amendment answering <stop>: in <relative file>, replaced "<find>" with
"<replace>".` (find and replace as JSON strings) to the plan's `## Amendments`
section: after the last non-blank line of an existing section, else in a new section
at the end of the plan. An edit whose line from `: in ` on is already recorded in
that section is skipped (`already: true`), so a re-run changes no byte.

Text is decoded and encoded as UTF-8 with no newline translation. Files are replaced
atomically one by one, the plan last; a failed write exits 2.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal

REQUEST_MEMBERS = ("plan_dir", "plan_root", "stop", "edits")
EDIT_MEMBERS = ("file", "find", "replace")
HEADING = "## Amendments"
LINE_PREFIX = "- Amendment answering "
OUTSIDE = "outside plan_dir"
STATUS_EXIT = {"applied": 0, "refused": 1, "error": 2}


class PlanAmendInputError(Exception):
    """The request is not the documented shape; the message is the one-line detail."""


def _text(value: object, name: str, *, non_empty: bool = True) -> str:
    if not isinstance(value, str) or (non_empty and not value):
        raise PlanAmendInputError(f"{name} must be a{' non-empty' if non_empty else ''} string")
    return value


def _exact(value: object, members: tuple[str, ...], name: str) -> dict:
    if not isinstance(value, dict):
        raise PlanAmendInputError(f"{name} must be an object")
    for member in members:
        if member not in value:
            raise PlanAmendInputError(f"{name} lacks member {member}")
    for member in sorted(set(value) - set(members)):
        raise PlanAmendInputError(f"{name} has unknown member {member}")
    return value


def load_request(text: str) -> dict:
    """Strictly parse and validate a request."""
    try:
        value = json.loads(text, object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except (ValueError, RecursionError) as error:
        raise PlanAmendInputError(f"not strict JSON: {error}") from None
    _exact(value, REQUEST_MEMBERS, "request")
    plan_dir = _text(value["plan_dir"], "plan_dir")
    if not plan_dir.startswith("/") or plan_dir == "/" or os.path.normpath(plan_dir) != plan_dir:
        raise PlanAmendInputError("plan_dir must be an absolute normalised path other than /")
    _text(value["plan_root"], "plan_root")
    stop = _text(value["stop"], "stop")
    if "\r" in stop or "\n" in stop:
        raise PlanAmendInputError("stop must not contain a line break")
    edits = value["edits"]
    if not isinstance(edits, list) or not edits:
        raise PlanAmendInputError("edits must be a non-empty list")
    for index, edit in enumerate(edits):
        name = f"edits[{index}]"
        _exact(edit, EDIT_MEMBERS, name)
        _text(edit["file"], f"{name}.file")
        _text(edit["find"], f"{name}.find")
        _text(edit["replace"], f"{name}.replace", non_empty=False)
    return value


def amendment_line(stop: str, rel: str, find: str, replace: str) -> str:
    """The Amendments section line for one edit (no terminator)."""
    return (f"{LINE_PREFIX}{stop}: in {rel}, replaced "
            f"{json.dumps(find, ensure_ascii=False)} with "
            f"{json.dumps(replace, ensure_ascii=False)}.")


def _split_lines(text: str) -> list[str]:
    """`text` as lines with their terminators; only CRLF, LF and CR end a line.

    Unlike `str.splitlines`, U+2028, U+2029 and U+0085 (which the recorded line may
    hold, `json.dumps` leaving them unescaped) do not split a line.
    """
    return re.findall(r"[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+", text)


def _section(lines: list[str]) -> tuple[int, int] | None:
    """(heading index, end index) of the Amendments section, or None."""
    for start, line in enumerate(lines):
        if line.rstrip("\r\n") == HEADING:
            for end in range(start + 1, len(lines)):
                if re.match(r"#{1,2} ", lines[end]):
                    return start, end
            return start, len(lines)
    return None


def insert_amendments(text: str, lines: list[str]) -> str:
    """`text` with `lines` added to its Amendments section (created when absent)."""
    parts = _split_lines(text)
    section = _section(parts)
    if section is None:
        if not text.endswith("\n"):
            text += "\n"
        return text + "\n" + HEADING + "\n\n" + "".join(line + "\n" for line in lines)
    start, end = section
    last = start
    for index in range(start + 1, end):
        if parts[index].strip():
            last = index
    if not parts[last].endswith(("\n", "\r")):
        parts[last] += "\n"
    parts[last + 1:last + 1] = [line + "\n" for line in lines]
    return "".join(parts)


def _recorded(text: str) -> list[str]:
    parts = _split_lines(text)
    section = _section(parts)
    if section is None:
        return []
    return [line.rstrip("\r\n") for line in parts[section[0] + 1:section[1]]
            if line.startswith(LINE_PREFIX)]


def _outside(path: str, plan_dir: str, real_dir: str) -> bool:
    return (os.path.normpath(path) != path
            or not path.startswith(plan_dir + "/")
            or not os.path.realpath(path).startswith(real_dir + os.sep))


def _result(status: str, edits: list, refused: list, detail: str | None = None) -> dict:
    result = {"status": status, "edits": edits, "refused": refused}
    if detail is not None:
        result["detail"] = detail
    return result


def _write_all(changes: dict[str, str]) -> None:
    """Replace every path by its new text: temporaries first, then the renames."""
    temporaries: list[tuple[str, str]] = []
    try:
        for path, text in changes.items():
            handle, temporary = tempfile.mkstemp(dir=os.path.dirname(path),
                                                 prefix=".plan-amend-")
            temporaries.append((temporary, path))
            with os.fdopen(handle, "wb") as stream:
                stream.write(text.encode("utf-8"))
            shutil.copymode(path, temporary)
        for temporary, path in temporaries:
            os.replace(temporary, path)
    except OSError:
        for temporary, _ in temporaries:
            try:
                os.remove(temporary)
            except OSError:
                pass
        raise


def amend(request: dict) -> dict:
    """Apply a validated request; return the output object (it performs the writes)."""
    plan_dir = request["plan_dir"]
    real_dir = os.path.realpath(plan_dir)
    root = request["plan_root"]
    edits = request["edits"]
    outside = [path for path in [root, *(edit["file"] for edit in edits)]
               if _outside(path, plan_dir, real_dir)]
    if outside:
        return _result("refused", [], [{"file": path, "reason": OUTSIDE} for path in outside])

    originals: dict[str, str | None] = {}
    current: dict[str, str] = {}

    def state(path: str) -> str | None:
        """The file's text, or its refusal reason (`missing`, `unreadable`)."""
        real = os.path.realpath(path)
        if real not in originals:
            if not os.path.isfile(real):
                originals[real] = "missing"
            else:
                try:
                    with open(real, "rb") as stream:
                        current[real] = stream.read().decode("utf-8")
                    originals[real] = current[real]
                except (OSError, UnicodeDecodeError):
                    originals[real] = "unreadable"
        return current.get(real) if real in current else originals[real]

    real_root = os.path.realpath(root)
    plan = state(root)
    if real_root not in current:
        return _result("refused", [], [{"file": root, "reason": plan}])
    recorded = _recorded(plan)
    stop = request["stop"]
    entries: list[dict] = []
    refused: list[dict] = []
    queued: list[str] = []
    for edit in edits:
        path, find = edit["file"], edit["find"]
        real = os.path.realpath(path)
        line = amendment_line(stop, os.path.relpath(path, plan_dir), find, edit["replace"])
        suffix = line[line.index(": in "):]
        text = state(path)
        text = text if real in current else None
        occurrences = 0 if text is None else sum(
            text.startswith(find, i) for i in range(len(text)))
        entry = {"file": path, "exists": os.path.isfile(real),
                 "occurrences": occurrences, "already": False}
        entries.append(entry)
        if any(recorded_line.endswith(suffix) for recorded_line in recorded):
            entry["already"] = True
        elif text is None:
            refused.append({"file": path, "reason": originals[real]})
        elif occurrences != 1:
            refused.append({"file": path,
                            "reason": "not found" if occurrences == 0 else "not unique"})
        else:
            at = text.index(find)
            current[real] = text[:at] + edit["replace"] + text[at + len(find):]
            queued.append(line)
    if refused:
        return _result("refused", entries, refused)
    if queued:
        current[real_root] = insert_amendments(current[real_root], queued)
    changes = {real: text for real, text in current.items() if text != originals[real]}
    # The plan goes last: a failure before it leaves every edit re-runnable.
    ordered = {real: text for real, text in changes.items() if real != real_root}
    if real_root in changes:
        ordered[real_root] = changes[real_root]
    try:
        _write_all(ordered)
    except OSError as error:
        return _result("error", [], [], f"write failed: {error}")
    return _result("applied", entries, [])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plan-amend", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    apply = commands.add_parser("apply", help="apply a request")
    apply.add_argument("--input", required=True, help="request file, or - for stdin")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.input == "-":
            raw = sys.stdin.buffer.read()
        else:
            with open(arguments.input, "rb") as stream:
                raw = stream.read()
        result = amend(load_request(raw.decode("utf-8")))
    except (OSError, UnicodeDecodeError, PlanAmendInputError) as error:
        detail = str(error) or error.__class__.__name__
        result = _result("error", [], [], " ".join(detail.splitlines()))
    print(json.dumps(result))
    return STATUS_EXIT[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
