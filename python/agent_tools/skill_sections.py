"""Print named `##` sections of a Markdown skill file (issue 505).

Usage: skill-sections [--opening] <file> <section>...

A name selects the one `##` heading whose text equals it or, with no equal
heading, the one whose text starts with it at a boundary that is not a letter or
digit. Every name is resolved before anything is printed, so a stale name
exits 2 with an empty stdout and a report of the file's headings. The selected
sections are printed once each, in file order, as the file's own bytes. The
file is split at `\\n` only (issue 505 D11), so a carriage return, form feed or
other Unicode line separator never ends a line.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

FENCE_OPEN_RE = re.compile(r" {0,3}(`{3,}|~{3,})")
FENCE_CLOSE_RE = re.compile(r" {0,3}(`{3,}|~{3,})[ \t]*")


@dataclass(frozen=True)
class Section:
    heading: str
    text: str


@dataclass(frozen=True)
class Document:
    opening: str
    sections: tuple[Section, ...]


@dataclass(frozen=True)
class Problem:
    name: str
    kind: str
    candidates: tuple[str, ...]


class Unresolved(Exception):
    def __init__(self, problems: tuple[Problem, ...]) -> None:
        super().__init__(f"{len(problems)} unresolved section name(s)")
        self.problems = problems


def _lines(text: str) -> list[str]:
    lines = text.split("\n")
    last = lines.pop()
    lines = [line + "\n" for line in lines]
    return lines + [last] if last else lines


def _closes(fence: str, body: str) -> bool:
    match = FENCE_CLOSE_RE.fullmatch(body.removesuffix("\r"))
    return match is not None and match[1][0] == fence[0] and len(match[1]) >= len(fence)


def parse(text: str) -> Document:
    """Split `text` into the opening and its `##` sections.

    A section runs from its heading line to the next level-1 or level-2 heading
    outside a fence; lines after a level-1 heading belong to no section.
    """
    opening: list[str] = []
    headings: list[str] = []
    bodies: list[list[str]] = []
    part: list[str] | None = opening
    fence: str | None = None
    for line in _lines(text):
        body = line.removesuffix("\n")
        if fence is not None:
            if _closes(fence, body):
                fence = None
        elif opened := FENCE_OPEN_RE.match(body):
            fence = opened[1]
        elif body.startswith("## "):
            headings.append(body[3:].strip())
            part = []
            bodies.append(part)
        elif body.startswith("# ") and bodies:
            part = None
        if part is not None:
            part.append(line)
    return Document("".join(opening),
                    tuple(Section(heading, "".join(lines)) for heading, lines in zip(headings, bodies)))


def _matches(document: Document, name: str) -> list[int]:
    exact = [index for index, section in enumerate(document.sections) if section.heading == name]
    if exact:
        return exact
    return [index for index, section in enumerate(document.sections)
            if section.heading.startswith(name) and len(section.heading) > len(name)
            and not section.heading[len(name)].isalnum()]


def resolve(document: Document, names: Sequence[str]) -> tuple[Section, ...]:
    """Return the sections `names` select, once each, in file order, or raise `Unresolved`."""
    selected: set[int] = set()
    problems: list[Problem] = []
    for name in dict.fromkeys(names):
        matches = _matches(document, name)
        if len(matches) == 1:
            selected.add(matches[0])
        elif matches:
            problems.append(Problem(name, "ambiguous", tuple(document.sections[i].heading for i in matches)))
        else:
            problems.append(Problem(name, "unknown", ()))
    if problems:
        raise Unresolved(tuple(problems))
    return tuple(document.sections[index] for index in sorted(selected))


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _report(problems: Sequence[Problem], document: Document, file: str) -> str:
    lines = []
    for problem in problems:
        if problem.kind == "ambiguous":
            candidates = ", ".join(_quote(candidate) for candidate in problem.candidates)
            lines.append(f"skill-sections: ambiguous section {_quote(problem.name)} matches {candidates}\n")
        else:
            lines.append(f"skill-sections: unknown section {_quote(problem.name)}\n")
    lines.append(f"skill-sections: the ## headings of {file}:\n")
    lines.extend(f"## {section.heading}\n" for section in document.sections)
    return "".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skill-sections", description=__doc__.splitlines()[0])
    parser.add_argument("--opening", action="store_true",
                        help="print the text before the first ## heading first")
    parser.add_argument("file", help="the Markdown file to read")
    parser.add_argument("section", nargs="+", help="a ## heading, or a prefix of one")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if "" in args.section:
        parser.error("a section name is empty")
    try:
        text = Path(args.file).read_bytes().decode("utf-8")
    except OSError as error:
        sys.stderr.write(f"skill-sections: cannot read {args.file}: {error.strerror or error}\n")
        return 2
    except UnicodeDecodeError:
        sys.stderr.write(f"skill-sections: {args.file} is not UTF-8\n")
        return 2
    document = parse(text)
    try:
        sections = resolve(document, args.section)
    except Unresolved as unresolved:
        sys.stderr.write(_report(unresolved.problems, document, args.file))
        return 2
    output = (document.opening if args.opening else "") + "".join(section.text for section in sections)
    sys.stdout.buffer.write(output.encode("utf-8"))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
