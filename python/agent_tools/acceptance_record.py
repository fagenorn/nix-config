"""acceptance-record: ship's re-observation of an acceptance record's pending code rows (issue 478).

`acceptance-record reobserve --record <path> --head <sha> [--checks <path|->] [--row <ACn>]...
[--ran <command>=<exit code>]...` reads the record's acceptance table under a closed grammar,
matches each named `unverified` `code` row's backticked measurements against the required checks
(`gh pr checks --required --json name,bucket,link`) and the commands run at `--head`, and applies
sdd's `code` rule: a failure makes the row `unmet`, all observed passes make it `met`, a matched
measurement left unobserved leaves it unchanged. Spans matching no observation are the caller's
`--row` judgment that their measurements are already cited. It prints `{acceptance_state, changed}` and replaces the record
only when a row changed. Every refusal exits 2 with one stderr line and the record untouched.
"""

import argparse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import NoReturn

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal

ERROR_EXIT = 2
SUFFIX = ".acceptance.md"
HEADER = ("AC", "Criterion", "Kind", "Check or command", "Observed", "Commit", "Conditions", "Verdict")
AC_ID = re.compile(r"AC[1-9][0-9]*")
KIND = re.compile(r"(code|evidence|human)( \(classified\))?")
VERDICT = re.compile(r"met|met \(.+\)|unmet|unverified|human_pending")
DELIMITER_CELL = re.compile(r":?-+:?")
FULL_SHA = re.compile(r"[0-9a-f]{40}")
EXIT_CODE = re.compile(r"[0-9]+")
SPAN = re.compile(r"`([^`]+)`")
PIPE = re.compile(r"(?<!\\)\|")
BUCKETS = frozenset({"pass", "fail", "pending", "skipping", "cancel"})

# Columns of the acceptance table, named by their position in HEADER.
OBSERVED, COMMIT, VERDICT_COLUMN = 4, 5, 7
UNOBSERVED_PLACEHOLDER = "—"


class AcceptanceRecordError(Exception):
    """Every refusal; main prints it as one `acceptance-record: ` stderr line."""


@dataclass(frozen=True)
class Row:
    index: int
    cells: tuple[str, ...]


def _content(line: str) -> str:
    return line[:-1] if line.endswith("\r") else line


def _cells(content: str) -> list[str] | None:
    """The stripped cells of a table line, or None when it is not one."""
    if not content.startswith("|"):
        return None
    pieces = PIPE.split(content)
    if len(pieces) < 2 or pieces[-1].strip():
        return None
    return [piece.strip() for piece in pieces[1:-1]]


def parse(text: str) -> list[Row]:
    """The acceptance table's rows in record order, under the closed grammar."""
    lines = text.split("\n")
    headers = [number for number, line in enumerate(lines) if _cells(_content(line)) == list(HEADER)]
    if not headers:
        raise AcceptanceRecordError("record has no acceptance header")
    if len(headers) > 1:
        raise AcceptanceRecordError("record repeats the acceptance header")
    delimiter = headers[0] + 1
    delimiter_cells = _cells(_content(lines[delimiter])) if delimiter < len(lines) else None
    if (delimiter_cells is None or len(delimiter_cells) != len(HEADER)
            or not all(DELIMITER_CELL.fullmatch(cell) for cell in delimiter_cells)):
        raise AcceptanceRecordError("record header has no delimiter row")
    rows: list[Row] = []
    seen: set[str] = set()
    for number in range(delimiter + 1, len(lines)):
        content = _content(lines[number])
        if not content.startswith("|"):
            break
        cells = _cells(content)
        if cells is None:
            raise AcceptanceRecordError(
                f"record line {number + 1} does not end in an unescaped pipe")
        if len(cells) != len(HEADER):
            raise AcceptanceRecordError(
                f"record line {number + 1} has {len(cells)} cells, not {len(HEADER)}")
        ac, kind, verdict = cells[0], cells[2], cells[VERDICT_COLUMN]
        if not AC_ID.fullmatch(ac):
            raise AcceptanceRecordError(f"record line {number + 1} has a malformed AC: {ac}")
        if ac in seen:
            raise AcceptanceRecordError(f"record repeats {ac}")
        seen.add(ac)
        if not KIND.fullmatch(kind):
            raise AcceptanceRecordError(f"record {ac} has unknown kind: {kind}")
        if not VERDICT.fullmatch(verdict):
            raise AcceptanceRecordError(f"record {ac} has unknown verdict: {verdict}")
        rows.append(Row(number, tuple(cells)))
    if not rows:
        raise AcceptanceRecordError("record has no acceptance rows")
    return rows


def derive(verdicts: Iterable[str]) -> str:
    """sdd's acceptance state: unmet before human_pending before met."""
    seen = set(verdicts)
    if seen & {"unmet", "unverified"}:
        return "unmet"
    if "human_pending" in seen:
        return "human_pending"
    return "met"


def load_checks(raw: str) -> dict[str, list[tuple[str, str]]]:
    """Check name -> its (bucket, link) reports in input order, from strict JSON."""
    try:
        entries = json.loads(raw, object_pairs_hook=reject_duplicate_keys,
                             parse_constant=reject_nonfinite_literal)
    except ValueError as error:
        raise AcceptanceRecordError(f"--checks is not strict JSON: {error}") from error
    if not isinstance(entries, list):
        raise AcceptanceRecordError("--checks must be a JSON array")
    checks: dict[str, list[tuple[str, str]]] = {}
    for number, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {"name", "bucket", "link"}:
            raise AcceptanceRecordError(
                f"--checks entry {number} must have exactly name, bucket and link")
        name, bucket, link = entry["name"], entry["bucket"], entry["link"]
        # The link is copied into one table row, which a line break would split.
        if (not isinstance(name, str) or not name or not isinstance(bucket, str)
                or bucket not in BUCKETS or not isinstance(link, str) or "\r" in link or "\n" in link):
            raise AcceptanceRecordError(f"--checks entry {number} is malformed")
        checks.setdefault(name, []).append((bucket, link))
    return checks


def parse_ran(values: Sequence[str]) -> dict[str, int]:
    """Command -> exit code, each value split at its last `=`."""
    ran: dict[str, int] = {}
    for value in values:
        command, separator, code = value.rpartition("=")
        if not separator or not command or not EXIT_CODE.fullmatch(code):
            raise AcceptanceRecordError(f"--ran needs <command>=<exit code>: {value}")
        if command in ran:
            raise AcceptanceRecordError(f"repeats --ran {command}")
        ran[command] = int(code)
    return ran


def _admit(rows: Sequence[Row], named: Sequence[str]) -> list[Row]:
    by_id = {row.cells[0]: row for row in rows}
    admitted: list[Row] = []
    for ac in named:
        if any(row.cells[0] == ac for row in admitted):
            raise AcceptanceRecordError(f"repeats --row {ac}")
        row = by_id.get(ac)
        if row is None:
            raise AcceptanceRecordError(f"--row {ac} names no record row")
        kind = KIND.fullmatch(row.cells[2])
        if kind is None or kind.group(1) != "code":
            raise AcceptanceRecordError(f"--row {ac} is not a code row")
        if row.cells[VERDICT_COLUMN] != "unverified":
            raise AcceptanceRecordError(f"--row {ac} is not unverified")
        admitted.append(row)
    return admitted


def _measurements(cell: str) -> list[str]:
    spans = (span.replace("\\|", "|") for span in SPAN.findall(cell))
    return list(dict.fromkeys(spans))


def _escape(entry: str) -> str:
    return entry.replace("|", "\\|")


def _observe(row: Row, head: str, checks: Mapping[str, Sequence[tuple[str, str]]],
             ran: Mapping[str, int]) -> tuple[str, str] | None:
    """The (verdict, Observed cell) a row becomes, or None to leave it unchanged."""
    ac = row.cells[0]
    entries: list[str] = []
    unobserved = failed = matched = False
    for span in _measurements(row.cells[3]):
        if span in checks:
            matched = True
            reports = checks[span]
            buckets = {bucket for bucket, _ in reports}
            outcome = next(iter(buckets)) if len(buckets) == 1 else None
            if outcome not in ("pass", "fail"):
                unobserved = True
                continue
            link = reports[0][1]
            entries.append(f"ship re-observed {span}: {outcome} at {head[:7]}"
                           + (f" {link}" if link else ""))
        elif span in ran:
            matched = True
            outcome = "pass" if ran[span] == 0 else "fail"
            entries.append(f"ship re-observed {span}: {outcome} at {head[:7]} (exit {ran[span]})")
        else:
            continue
        failed = failed or outcome == "fail"
    if not matched:
        raise AcceptanceRecordError(f"--row {ac} has no measurement matching an observation")
    if unobserved and not failed:
        return None
    observed = "; ".join(_escape(entry) for entry in entries)
    current = row.cells[OBSERVED]
    if current not in ("", UNOBSERVED_PLACEHOLDER):
        observed = f"{current}; {observed}"
    return ("unmet" if failed else "met"), observed


def reobserve(text: str, head: str, checks: Mapping[str, Sequence[tuple[str, str]]],
              rows: Sequence[str], ran: Mapping[str, int]) -> tuple[str, str, list[str]]:
    """The new text, the derived state and the changed AC ids in record order."""
    table = parse(text)
    admitted = _admit(table, rows)
    outcomes = {row.cells[0]: _observe(row, head, checks, ran) for row in admitted}
    lines = text.split("\n")
    verdicts: list[str] = []
    changed: list[str] = []
    for row in table:
        outcome = outcomes.get(row.cells[0])
        if outcome is None:
            verdicts.append(row.cells[VERDICT_COLUMN])
            continue
        verdict, observed = outcome
        cells = list(row.cells)
        cells[OBSERVED], cells[COMMIT], cells[VERDICT_COLUMN] = observed, head, verdict
        carriage_return = "\r" if lines[row.index].endswith("\r") else ""
        lines[row.index] = "| " + " | ".join(cells) + " |" + carriage_return
        verdicts.append(verdict)
        changed.append(row.cells[0])
    return "\n".join(lines), derive(verdicts), changed


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise AcceptanceRecordError(message)


def _parser() -> _Parser:
    parser = _Parser(prog="acceptance-record", description=__doc__,
                     formatter_class=argparse.RawDescriptionHelpFormatter)
    verbs = parser.add_subparsers(dest="verb", required=True, parser_class=_Parser)
    verb = verbs.add_parser("reobserve", help="re-observe named unverified code rows")
    verb.add_argument("--record", required=True)
    verb.add_argument("--head", required=True)
    verb.add_argument("--checks")
    verb.add_argument("--row", action="append", default=[])
    verb.add_argument("--ran", action="append", default=[])
    return parser


def _read_record(path: Path) -> tuple[str, int]:
    """The record's text and permission bits, refusing anything but a regular file."""
    if not path.name.endswith(SUFFIX):
        raise AcceptanceRecordError(f"record {path} must end in {SUFFIX}")
    try:
        mode = os.lstat(path).st_mode
        if stat.S_ISLNK(mode):
            raise AcceptanceRecordError(f"record {path} is a symlink")
        if not stat.S_ISREG(mode):
            raise AcceptanceRecordError(f"record {path} is not a regular file")
        data = path.read_bytes()
    except OSError as error:
        raise AcceptanceRecordError(f"cannot read record {path}: {error}") from error
    try:
        return data.decode("utf-8"), stat.S_IMODE(mode)
    except UnicodeDecodeError as error:
        raise AcceptanceRecordError(f"record {path} is not UTF-8") from error


def _read_checks(source: str | None) -> dict[str, list[tuple[str, str]]]:
    if source is None:
        return {}
    try:
        raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise AcceptanceRecordError(f"cannot read --checks {source}: {error}") from error
    return load_checks(raw)


def _replace_record(path: Path, text: str, mode: int) -> None:
    """Atomically replace the record through a temporary file beside it."""
    temporary: str | None = None
    try:
        data = text.encode("utf-8")
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".acceptance-record-")
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    except (OSError, UnicodeEncodeError) as error:
        raise AcceptanceRecordError(f"cannot write record {path}: {error}") from error
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if not FULL_SHA.fullmatch(args.head):
            raise AcceptanceRecordError(
                f"--head must be a full 40-character lowercase sha: {args.head}")
        ran = parse_ran(args.ran)
        path = Path(args.record)
        text, mode = _read_record(path)
        parse(text)
        checks = _read_checks(args.checks)
        new_text, state, changed = reobserve(text, args.head, checks, args.row, ran)
        if changed:
            _replace_record(path, new_text, mode)
    except AcceptanceRecordError as error:
        print(f"acceptance-record: {error}", file=sys.stderr)
        return ERROR_EXIT
    print(json.dumps({"acceptance_state": state, "changed": changed},
                     sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
