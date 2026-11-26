"""The console's runtime copy of the do-not-write list, and the rule that finds a listed word in a text.

Why it exists: `docs/guides/owner-words.md` is the source of the list, but the console package does not ship
`docs/`, so `ROWS` is a copy of that table, row for row and in table order, plus the forms each row finds.
`tests/test_console_owner_words.py` fails when the first two cells of the two differ.

The match rule: each pattern of a row is compiled as a whole-word, case-insensitive match. The word characters
are ASCII letters and digits only, case folding is ASCII only, and a space in a pattern matches any run of the
six ASCII separators (space, tab, newline, carriage return, form feed, vertical tab), never `\\s`. Where a
pattern has a group named `w`, the reported word is that group and the rest of the pattern is only the context
that must surround it; otherwise the whole match is reported. Of the matches that overlap, the longest wins.
Words that are also ordinary English are listed only in their internal form, so the patterns carry that form.
The page of ordinary sentences in `tests/fixtures/console/owner-words-ordinary.txt` and the cases in
`tests/fixtures/console/owner-words-cases.json` hold the rule to what it finds and what it leaves alone.

Nothing clears a word: a text that also explains the word, in brackets or elsewhere, still has the word found.

The four names: `ROWS` (the `(do_not_write, write_instead, patterns)` rows), `Found` (a `row`, `pattern`,
`word` and `sentence`), `found(text)` (the first match of each pattern in `text`, in list order) and
`found_in(texts)` (the first `Found` of each pattern across `texts`, in list order). A word that
two patterns of a row both find is one word. `SEPARATORS`, `MAIN`, `GUARD` and `CHANGE` are the shared fragments.
"""
import re
from collections.abc import Iterable
from typing import NamedTuple

SEPARATORS = "[ \t\n\r\f\v]+"

MAIN = ("(?-i:main)(?! (?!(?:and|or|but|now|yet|again|already|since|after|before|first|today|too|so|then"
        "|is|was|with|by|at|in|for|yesterday|tomorrow|tonight)(?![0-9A-Za-z]))[A-Za-z])")
# "the guard", unless a person is meant: a verb of a person at a gate, or a gate, door or post later in the sentence.
GUARD = ("the guard(?:['’]s)?(?! (?:opened|closed|watched|stood|waved|walked|nodded|smiled|patrolled|locked|unlocked"
         "|yawned|saluted|looked|waited)(?![0-9A-Za-z]))"
         "(?![^.!?]*(?<![0-9A-Za-z])(?:gates?|doors?|prison|castle|palace|museum|bank|duty|shift|uniform|badge)"
         "(?![0-9A-Za-z]))(?: (?:policy|policies|rules?|hooks?|decisions?))?")
CHANGE = "(?:changes?|fix(?:es)?|PRs?|pull requests?|deliver(?:y|ies)|issues?)"
ROWS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("land lock, merge lock", "its turn to merge", ("land locks?", "merge locks?")),
    ("pull request, PR", "the proposed change", ("pull requests?", "PRs?")),
    ("rerun", "ran the failed check again", ("re-?run(?:s|ning)?",)),
    ("CI", "the automatic checks", ("CI",)),
    ("held issue", "merged, waiting for proof it works in real use", ("held issues?",)),
    ("verify, verification", "testing the change (before it goes in); checking it works in real use (after)",
     ("verif(?:y|ies|ied|ying)", "verifications?")),
    ("landed, landing (a change)", "went in, is going in",
     ("(?:[0-9]+|" + CHANGE + ") (?:(?:is|are|was|were|has|have|had|just|now|already|been|being|still) )*"
      "(?P<w>landed|landing)",
      "(?P<w>landed|landing) (?:(?:the|this|that|a|its|their) )?" + CHANGE,
      "(?P<w>landed|landing) (?:on|in|into) " + MAIN)),
    ("slice", "step", ("slices?",)),
    ("brief version", "the new version of the plan", ("brief versions?",)),
    ("the guard, a guard refusal", "the safety check", (GUARD, "guard refusals?")),
    ("a claim on files", "a note of the files it is working on",
     ("claims? on (?:(?:the|its|their|these|those) )?files?",)),
    ("look card", "your look at how it appears", ("look cards?",)),
    ("live fault", "a problem users are hitting now", ("live faults?",)),
    ("commit, sha, the head", "the latest version of the change",
     ("commit(?:s|ted|ting)?", "shas?", "(?:the|" + CHANGE + "['’]s) head(?! of(?![0-9A-Za-z]))")),
    ("on main, the branch", "the main version, the change's own copy", ("on " + MAIN, "into " + MAIN, "the branch(?:es)?")),
    ("issue plus a number", "the task, named by its title", ("issues? #?[0-9]+",)),
    ("milestone", "the sprint's task list", ("milestones?",)),
    ("Conformance, lint", "the house-rule checks", ("conformance", "lint(?:s|ed|ing)?")),
    ("fix wave", "a round of fixes", ("fix waves?",)),
    ("activation of the host", "switching this computer to the new version",
     ("activat(?:e|es|ed|ing|ion) (?:of )?(?:the|this) host", "host activations?")),
    ("AC plus a number", "say what must be true", ("AC(?: )?[0-9]+",)),
    ("stage names used as nouns (final-review, verify-fix and the like)", "say what is happening",
     ("final-review", "plan-review", "verify-fix", "fix-wave", "fix-ci", "look-fix", "ws-check")),
    ("ready mode", "built and tested, not yet proposed", ("ready(?:-| )mode",)),
    ("sync (with main)", "brought up to date with the main version",
     ("(?P<w>sync(?:s|ed|ing)?) (?:[A-Za-z']+ ){0,3}?(?:with|to|onto|from|into|against) (?:the |origin/)?" + MAIN,)),
    ("flaky", "fails now and then for no real reason", ("flaky", "flakiness")),
    ("tokens", "say the cost in dollars, or leave it out", ("tokens",)),
    ("worktree, engine, workflow, delivery program", "leave it out; say what is being done",
     ("worktrees?", "engines?", "workflows?", "delivery programs?")),
)


class Found(NamedTuple):
    row: int
    pattern: int
    word: str
    sentence: str


def _compile(fragment: str) -> re.Pattern[str]:
    return re.compile("(?<![0-9A-Za-z])" + fragment.replace(" ", SEPARATORS) + "(?![0-9A-Za-z])",
                      re.IGNORECASE | re.ASCII)


_PATTERNS = tuple(tuple(_compile(p) for p in patterns) for _, _, patterns in ROWS)
_SEPARATOR = re.compile(SEPARATORS)
_END = re.compile(r"[.!?](?=[ \t\n\r\f\v]|\Z)")


def _fold(text: str) -> str:
    return _SEPARATOR.sub(" ", text).strip()


def _sentence(text: str, start: int, end: int) -> str:
    before = [m.end() for m in _END.finditer(text) if m.end() <= start]
    after = _END.search(text, end)
    return _fold(text[before[-1] if before else 0:after.end() if after else len(text)])


def found(text: str) -> list[Found]:
    """The first match of each pattern in `text`, longest first among overlaps, in list order.

    One word that two patterns find counts once.
    """
    matches = []
    for row, patterns in enumerate(_PATTERNS):
        for pattern, rx in enumerate(patterns):
            for m in rx.finditer(text):
                start, end = m.span("w") if "w" in rx.groupindex else m.span()
                matches.append((start, end, row, pattern))
    kept: list[tuple[int, int, int, int]] = []
    for start, end, row, pattern in sorted(matches, key=lambda m: (-(m[1] - m[0]), m[0], m[2], m[3])):
        if all(end <= k[0] or k[1] <= start for k in kept):
            kept.append((start, end, row, pattern))
    # One warning per pattern, then one per surface word of a row: two patterns that find one word warn once.
    firsts: dict[tuple[int, int], tuple[int, int]] = {}
    for start, end, row, pattern in sorted(kept, key=lambda k: (k[0], k[2], k[3])):
        firsts.setdefault((row, pattern), (start, end))
    seen: dict[tuple[int, str], tuple[int, int, int]] = {}
    for (row, pattern), (start, end) in sorted(firsts.items(), key=lambda i: (i[1], i[0])):
        seen.setdefault((row, _fold(text[start:end]).casefold()), (pattern, start, end))
    return [Found(row, pattern, _fold(text[start:end]), _sentence(text, start, end))
            for (row, _), (pattern, start, end) in sorted(seen.items(), key=lambda i: (i[0][0], i[1][0]))]


def found_in(texts: Iterable[str]) -> list[Found]:
    """The first `Found` of each pattern across `texts`, in list order; one word two patterns find is one."""
    patterns: set[tuple[int, int]] = set()
    words: set[tuple[int, str]] = set()
    first: dict[tuple[int, int], Found] = {}
    for text in texts:
        for f in found(text):
            if (f.row, f.pattern) in patterns:
                continue
            patterns.add((f.row, f.pattern))
            if (f.row, f.word.casefold()) not in words:
                words.add((f.row, f.word.casefold()))
                first[(f.row, f.pattern)] = f
    return [first[key] for key in sorted(first)]
