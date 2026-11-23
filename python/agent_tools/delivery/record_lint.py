"""The decision-record rules of the never-rise check.

A decision record is a header, an optional `**Formerly:**` line and one
paragraph of at most 1,500 bytes: no section heading, list, quote, fence,
status line or second paragraph. B21 (the size) and B22 (the form) are
per-file violations for the never-rise check, `RECORD_ENFORCERS`, not findings
of `agent_tools.delivery.context_map_lint`, so that tool neither prints nor
fails on them: the records written before the form are carried by the change's
merge base, and only a record that grows past its base, or that is added, rises.
A rename git pairs carries a record's violations only as a migration of a
record: a well-formed new header with the old title, at most one well-formed
Formerly line naming the old record, the body byte for byte, and at most two
bytes of blank lines added, so the exempted growth is one header and one
Formerly line; a superseding record that reuses the old text, and a file that
was no record, are judged as a new record. `added_records` lists the records a
change adds, a migration excluded.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from agent_tools.delivery.context_map_lint import ADR_FILE_RE
from agent_tools.delivery.never_rise import Enforcer, Snapshot, Verdict, Violation

RECORD_BYTES_CAP = 1500
RECORD_SIZE_RULE = "B21"
RECORD_FORM_RULE = "B22"
FORMERLY_LINE_RE = re.compile(r"^\*\*Formerly:\*\* ADR-[a-z0-9][a-z0-9-]*-\d{3}\s*$")
FORMERLY_BYTES_RE = re.compile(rb"^\*\*Formerly:\*\* ADR-[a-z0-9][a-z0-9-]*-\d{3}\n?\Z")
# A slug is a directory name: a header naming one longer than this is no migration.
MAX_SLUG_BYTES = 64
NEW_HEADER_BYTES_RE = re.compile(
    rb"\A# ADR-(?P<slug>[a-z0-9][a-z0-9-]{0,%d})-(?P<number>\d{3}) \xe2\x80\x94 (?P<title>\S[^\n]*)\Z"
    % (MAX_SLUG_BYTES - 1))
OLD_HEADER_BYTES_RE = re.compile(
    rb"\A#\s+ADR-(?P<slug>[a-z0-9][a-z0-9-]*)-(?P<number>\d{3})\s+\xe2\x80\x94\s+(?P<title>\S[^\n]*)\Z")
MIGRATION_BLANK_BYTES = 2
LABEL_RE = re.compile(r"^ {0,3}(?:\*\*|__)[^*_]{1,40}[.:](?:\*\*|__)")
ORDERED_RE = re.compile(r"^ {0,3}(\d{1,9})[.)](?:[ \t]|$)")
FORM_BREACH_RES = tuple(re.compile(pattern, flags) for pattern, flags in (
    (r"^ {0,3}#{1,6}(?:[ \t]|$)", 0),
    (r"^\s*(?:[-*+]\s+)?[*_]{0,2}status[*_]{0,2}\s*:", re.I),
    (r"^ {0,3}[-*+](?:[ \t]|$)", 0),
    (r"^ {0,3}(?:=+|-+|(?:[*_][ \t]*){3,})[ \t]*$", 0),
    (r"^ {0,3}(?:```|~~~)", 0),
    (r"^ {0,3}>", 0)))


def is_record_path(path: str) -> bool:
    """True for a repository-relative POSIX path docs/areas/<slug>/adr/<record>.md."""
    parts = path.split("/")
    return (len(parts) == 5 and parts[0] == "docs" and parts[1] == "areas"
            and bool(parts[2]) and parts[3] == "adr" and bool(ADR_FILE_RE.match(parts[4])))


def record_lines(content: bytes) -> list[str]:
    """The record's decoded lines, a trailing carriage return stripped from each."""
    text = content.decode("utf-8", errors="replace")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


class RecordParts(NamedTuple):
    """One record's bytes, split exactly: nothing is decoded and no '\\r' is dropped."""
    header: bytes
    formerly: bytes | None
    blank_bytes: int
    body: bytes


def record_parts(content: bytes) -> RecordParts:
    """The header, a leading Formerly line, the blank lines' bytes and the body, endings kept.

    The body runs from the first to the last non-blank line after the header and one
    well-formed Formerly line; a blank line counts whole, spaces and carriage return too.
    """
    lines = re.findall(rb"[^\n]*\n|[^\n]+", content)
    header = lines[0].rstrip(b"\n") if lines else b""
    rest = lines[1:]
    start, end = 0, len(rest)
    while start < end and not rest[start].strip():
        start += 1
    while end > start and not rest[end - 1].strip():
        end -= 1
    edge = rest[:start] + rest[end:]
    body = rest[start:end]
    formerly = None
    if body and FORMERLY_BYTES_RE.match(body[0]):
        formerly = body[0].rstrip(b"\n")
        body = body[1:]
        after = 0
        while after < len(body) and not body[after].strip():
            after += 1
        edge, body = edge + body[:after], body[after:]
    return RecordParts(header, formerly, sum(len(line) for line in edge), b"".join(body))


def is_record_migration(old: bytes, new: bytes) -> bool:
    """True when a move left the record's substance alone, the difference bounded: a well-formed
    new header keeping the old title, a well-formed Formerly line naming the old record (or
    repeating the old one), the body byte for byte, blank lines grown by at most
    `MIGRATION_BLANK_BYTES`; so a migration adds one header and one Formerly line."""
    before, after = record_parts(old), record_parts(new)
    old_header = OLD_HEADER_BYTES_RE.match(before.header)
    new_header = NEW_HEADER_BYTES_RE.match(after.header)
    if old_header is None or new_header is None or old_header["title"] != new_header["title"]:
        return False
    names_old = b"**Formerly:** ADR-" + old_header["slug"] + b"-" + old_header["number"]
    if after.formerly not in (None, names_old, before.formerly):
        return False
    return (before.body == after.body
            and after.blank_bytes <= before.blank_bytes + MIGRATION_BLANK_BYTES)


def form_breaches(content: bytes) -> list[int]:
    """The 1-based line of each breach of the record form, in line order."""
    lines = record_lines(content)
    breaches: set[int] = set()
    blocks: list[list[int]] = []
    previous_blank = True
    in_list = False
    for number, line in enumerate(lines[1:], 2):
        if not line.strip():
            previous_blank = True
            in_list = False
            continue
        ordered = ORDERED_RE.match(line)
        # An ordered item starts a list at the top of a block, as "1.", or after
        # another item; any other number in mid-paragraph is prose.
        starts_list = ordered is not None and (
            previous_blank or in_list or int(ordered.group(1)) == 1)
        in_list = starts_list or any(
            pattern.match(line) for pattern in FORM_BREACH_RES[2:3])
        if (starts_list or any(pattern.match(line) for pattern in FORM_BREACH_RES)
                or (not previous_blank and LABEL_RE.match(line))):
            breaches.add(number)
        if previous_blank:
            blocks.append([])
        blocks[-1].append(number)
        previous_blank = False
    if blocks and len(blocks[0]) == 1 and FORMERLY_LINE_RE.match(lines[blocks[0][0] - 1]):
        blocks = blocks[1:]
    if not blocks:
        return [1]
    breaches.update(block[0] for block in blocks[1:])
    return sorted(breaches)


def record_violations(path: str, content: bytes) -> list[Violation]:
    """The B21 violation, then the B22 violation, of one record; at most one of each."""
    found = []
    if len(content) > RECORD_BYTES_CAP:
        line = content[:RECORD_BYTES_CAP].count(b"\n") + 1
        found.append(Violation(RECORD_SIZE_RULE, path, line, len(content)))
    breaches = form_breaches(content)
    if breaches:
        found.append(Violation(RECORD_FORM_RULE, path, breaches[0], len(breaches)))
    return found


def _record_violations_of(snapshot: Snapshot, rule: str) -> list[Violation]:
    return [violation for path in sorted(snapshot.blobs) if is_record_path(path)
            for violation in record_violations(path, snapshot.blobs[path])
            if violation.rule == rule]


def find_record_size(snapshot: Snapshot) -> list[Violation]:
    return _record_violations_of(snapshot, RECORD_SIZE_RULE)


def find_record_form(snapshot: Snapshot) -> list[Violation]:
    return _record_violations_of(snapshot, RECORD_FORM_RULE)


RECORD_SIZE_ENFORCER = Enforcer(
    RECORD_SIZE_RULE, find_record_size, per_file=True, carries=is_record_migration,
    exempts_carried=True,  # a move adds header and Formerly bytes the cap must not count
    carries_from=is_record_path, reads=is_record_path)
RECORD_FORM_ENFORCER = Enforcer(
    RECORD_FORM_RULE, find_record_form, per_file=True, carries=is_record_migration,
    carries_from=is_record_path, reads=is_record_path)
RECORD_ENFORCERS = (RECORD_SIZE_ENFORCER, RECORD_FORM_ENFORCER)


def added_records(verdict: Verdict) -> list[str]:
    """The records a change adds, a migration (a record moved, its body unchanged) excluded."""
    listed = []
    for path in sorted(verdict.added):
        if not is_record_path(path):
            continue
        source = verdict.renamed.get(path)
        if (source is not None and is_record_path(source)
                and is_record_migration(*verdict.rename_blobs[path])):
            continue
        listed.append(path)
    return listed
