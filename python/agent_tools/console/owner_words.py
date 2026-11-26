"""The console's runtime copy of the owner glossary, and the rule that finds a word used without its gloss.

Why it exists: `docs/guides/owner-words.md` is the source of the glossary, but the console package does not
ship `docs/`, so `GLOSSARY` is a copy of that table, row for row and in table order.
`tests/test_console_owner_words.py` fails when the two differ.

The match rule: a word is used in a text when it appears as a whole word, ignoring case. The word characters
are ASCII letters and digits only, case folding is ASCII only, and a multi-word entry matches across any run of
the six ASCII separators (space, tab, newline, carriage return, form feed, vertical tab), never `\\s`. An
inflected form ("slices", "looks", "verified") is not the word. The page implements the same rule in
JavaScript and is held to the same cases, `tests/fixtures/console/owner-words-cases.json`.

The glossed rule: a word used in a text is cleared when that same text also holds its gloss, compared with
runs of separators folded to one space and ASCII letters lowercased.

The four names: `GLOSSARY` (the 12 `(word, gloss)` rows), `unglossed(text)` (the rows `text` uses without their
gloss, in glossary order, each at most once), `unglossed_in(texts)` (the distinct rows flagged in any one of
`texts`, in glossary order) and `entries()` (the wire form for the view).
"""
import re
import string
from collections.abc import Iterable

GLOSSARY: tuple[tuple[str, str], ...] = (
    ("land lock",
     "A turn-taking token: only one change at a time may be merged into the branch where finished changes are collected, so a change waits until it holds the lock."),
    ("slice",
     "One small piece of a larger job, made so that it can be built, checked and finished on its own."),
    ("held",
     "Finished and merged, but not counted as done until a check afterwards shows it works for real."),
    ("verify",
     "A check that a change does what it was meant to do. One kind runs before the change is merged, when it has not shipped yet. Another kind runs after the change is live, on a schedule, and only for a change kept open until real use proves it works; it may take several passes. Say which kind is meant."),
    ("brief version",
     "One numbered draft of the plan the manager writes for the owner, or the colleague who started the sprint, to approve; a new version replaces the last when the owner asks for changes."),
    ("guard",
     "A safety check that refuses a risky command before it runs, such as pushing code or merging a change."),
    ("rerun",
     "Run a failed automatic check again, in case it failed for a passing reason."),
    ("claim",
     "A note that says one sprint is working on certain files. It does not lock them: two sprints with overlapping claims both keep working, and a separate rule, not the claim, decides which one goes first."),
    ("look",
     "Your own look at how something appears on screen, before it is merged."),
    ("live fault",
     "A fault the manager has found in the running system that real users are meeting now."),
    ("CI",
     "The automatic checks that GitHub runs on every proposed change before it can be merged."),
    ("pull request",
     "A proposed change, held on GitHub for checking and review before it joins the main code."),
)

SEPARATORS = "[ \t\n\r\f\v]+"
_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


def _pattern(word: str) -> re.Pattern[str]:
    parts = [p for p in re.split(SEPARATORS, word) if p]
    body = SEPARATORS.join(re.escape(p) for p in parts)
    return re.compile("(?<![0-9A-Za-z])" + body + "(?![0-9A-Za-z])", re.IGNORECASE | re.ASCII)


def _flat(s: str) -> str:
    return " ".join(p for p in re.split(SEPARATORS, s) if p).translate(_ASCII_LOWER)


_PATTERNS = tuple(_pattern(word) for word, _ in GLOSSARY)
_FLAT_GLOSSES = tuple(_flat(gloss) for _, gloss in GLOSSARY)


def unglossed(text: str) -> list[tuple[str, str]]:
    """The glossary rows `text` uses without their gloss, in glossary order, each at most once."""
    flat = _flat(text)
    return [
        row
        for row, pattern, gloss in zip(GLOSSARY, _PATTERNS, _FLAT_GLOSSES)
        if pattern.search(text) and gloss not in flat
    ]


def unglossed_in(texts: Iterable[str]) -> list[tuple[str, str]]:
    """The distinct rows flagged in any one of `texts`, in glossary order."""
    flagged = {row for text in texts for row in unglossed(text)}
    return [row for row in GLOSSARY if row in flagged]


def entries() -> list[dict[str, str]]:
    """The glossary as the view sends it."""
    return [{"word": word, "gloss": gloss} for word, gloss in GLOSSARY]
