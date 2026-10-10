"""Shell-example contracts: skill examples the worktree isolation checker can verify.

A living example is shell text a skill document shows an agent: the whole body
of a shell-labeled fence, and the lines of an unlabeled or `text` fence and the
inline code spans whose command head is in the closed command vocabulary. Each
example is one call. The worktree isolation checker verifies only a single plain
command with literal targets, so an example refuses when it carries one of the
closed forms in FORMS: a chain, a pipe, a redirect, a heredoc, or text the
scanner cannot close (unparseable, fail-closed). The one sanctioned chain is the
lifecycle guard's own token-scrub prefix, read from the guard, never restated.
The one sanctioned pipeline is a lifecycle helper call: a pipeline whose every
segment is headed by a helper that `default.nix`'s permission allow list admits
whole, whose heredocs are `<<` with a quoted delimiter, and which carries no
chain, redirect or command substitution; the helpers are read from that allow
list, never restated.

`refused_examples(document_text)` is the boundary for refused forms: every form
sweep and form fixture below calls it on a document's text.
`guarded_command_findings(document_text, shapes, document_name)` is the boundary
for the commands the lifecycle guard adjudicates in ship-issue (#351): a living
example that begins with one of the fixture's verbs must be a form listed in
tests/fixtures/guarded-command-shapes.json, and its block must carry the
fixture's anchor. Nothing else produces findings.
"""
from bisect import bisect_right
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import NamedTuple
import unittest

# unittest loads suites by path, so the directory is not a package; the
# shared support module lives beside this file.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_tree_support import (  # noqa: E402
    INSTALLED_VIEWS,
    REPO_ROOT,
    SOURCE_TREES,
    installed_home_or_skip,
    installed_root_error,
)


FORMS = ("chain", "pipe", "redirect", "heredoc", "unparseable")
SHELL_FENCE_INFO = frozenset({"bash", "sh", "shell", "console", "zsh"})
# Unlabeled and `text` fences also hold prompts, diagrams and JSON: only their
# vocabulary-headed lines are examples.
AMBIGUOUS_FENCE_INFO = frozenset({"", "text"})
# The closed set of command names the skills run: every ~/.agents/bin helper
# plus common tools. VocabularyGuardTest keeps it honest for shell fences.
COMMAND_VOCABULARY = frozenset({
    "[", "adopt-project", "agent-evidence", "agent-model-matrix",
    "artifact-budget", "awk", "bash", "brew", "bun", "cargo", "cat", "cd",
    "chmod", "claude", "codex", "conformance",
    "context-map-lint", "cp", "curl",
    "darwin-rebuild", "devenv", "diff", "diff-scope", "docker", "dotnet",
    "echo", "env", "eval", "export", "find", "gh", "git", "glab", "go",
    "grep", "head", "jq", "just", "kubectl", "ls", "make", "mkdir", "mktemp",
    "mv", "nix", "nixos-rebuild", "node", "npm", "pnpm", "printf", "pytest",
    "python3", "railway", "resolve-project", "review-package", "review-range", "rg", "rm",
    "sdd-workspace", "sed", "sh", "sleep", "sops", "sort", "source", "ssh",
    "tail", "tar", "task-brief", "tee", "terraform", "test", "timeout",
    "touch", "unset", "uv", "wc", "workflow-state", "xargs", "yarn", "zsh",
})

# The one sanctioned chain lives in the lifecycle guard's own Python source; it
# is read, never restated. The whole-allowed helpers live in the permission
# allow list, which stays in the claude-code module (spec D30).
GUARD_SOURCE = REPO_ROOT / "home/common/claude-code/lifecycle_guard.py"
ALLOW_LIST_SOURCE = REPO_ROOT / "home/common/claude-code/default.nix"
GUARD_ASSIGNMENT = re.compile(
    r'^\s*UNSET_GITHUB_TOKEN_PREFIX = "([^"\n]*)"\s*$', re.M
)


def guard_prefix(guard_text):
    """The literal of the guard's single UNSET_GITHUB_TOKEN_PREFIX assignment."""
    matches = GUARD_ASSIGNMENT.findall(guard_text)
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one UNSET_GITHUB_TOKEN_PREFIX assignment in "
            f"{GUARD_SOURCE}, found {len(matches)}"
        )
    return matches[0]


# A single-word allow entry admits a command whole, whatever its arguments.
WHOLE_ALLOW_ENTRY = re.compile(r'^\s*"Bash\(([^\s()"]+):\*\)"', re.M)


def whole_allowed_helpers(nix_text):
    """Basenames of the allow list's single-word `"Bash(<word>:*)"` entries."""
    words = WHOLE_ALLOW_ENTRY.findall(nix_text)
    if not words:
        raise ValueError(
            f"expected a single-word Bash allow entry in {ALLOW_LIST_SOURCE}, found none"
        )
    return frozenset(word.rsplit("/", 1)[-1] for word in words)


SANCTIONED_PREFIX = guard_prefix(GUARD_SOURCE.read_text(encoding="utf-8"))
LIFECYCLE_HELPERS = whole_allowed_helpers(ALLOW_LIST_SOURCE.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Finding:
    line: int
    form: str
    example: str


# A fence delimiter: a run of three or more backticks at any indentation.
# Fences nest: only a bare run at least as long as the innermost opener closes
# it, so a `bash` fence inside a ````markdown template is still a shell fence.
FENCE = re.compile(r"^\s*(`{3,})(.*)$")
# Applied to one prose block, so a span may close on a later line of it (D28).
INLINE_CODE = re.compile(r"`([^`]+)`")
# A line that starts a new list item, which starts a new prose block (D28).
LIST_ITEM = re.compile(r"\s*(?:[-*+]|\d+[.)]) ")
# `<pr-num>`-style placeholders: non-space edges, never across lines, so
# `cmd < in > out` keeps both redirects.
PLACEHOLDER = re.compile(r"<[^\s<>](?:[^<>\n]*[^\s<>])?>")
LEADING_EXPANSION = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")
LEADING_SUBSTITUTION_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=\$\(")
LEADING_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
HEREDOC_DELIMITER = re.compile(r"[ \t]*\\?(?:'([^'\n]*)'|\"([^\"\n]*)\"|([^\s;&|<>()]+))")


def command_head(line):
    """The command a line runs, as a basename; None for a plain assignment."""
    text = line.lstrip()
    while True:
        match = (LEADING_EXPANSION.match(text)
                 or LEADING_SUBSTITUTION_ASSIGNMENT.match(text))
        if match is None:
            break
        text = text[match.end():]
    if LEADING_ASSIGNMENT.match(text):
        return None
    words = text.split()
    if not words:
        return None
    return words[0].rsplit("/", 1)[-1]


# Scanner contexts. Live contexts are where operators count.
_LIVE = frozenset({"top", "subst", "procsub", "paren", "backtick"})
_PAREN_CLOSED = frozenset({"subst", "procsub", "paren"})
_CONTINUING = frozenset({"&&", "||", "|"})
_OPERATORS = (
    ("<<<", "heredoc"), ("<<-", "heredoc"), ("<<", "heredoc"),
    ("&&", "chain"), ("||", "chain"), (";", "chain"),
    ("|&", "pipe"), ("|", "pipe"),
    ("<(", "redirect"), (">(", "redirect"), ("&>", "redirect"),
    (">>", "redirect"), (">", "redirect"), ("<", "redirect"),
    ("&", "chain"),
)


class _Scan(NamedTuple):
    firsts: dict  # form → text index of its first operator
    is_open: bool  # the text cannot be closed as it stands
    substituted: bool  # a command substitution opened: `$(` or an opening backtick
    heredocs: list  # per heredoc operator: is it `<<` with a quoted delimiter
    pipes: list  # per pipe operator: (is it a plain `|`, text offset just past it)


def _scan(text):
    """The _Scan of one example's text: its forms, open flag, substitutions,
    heredoc quoting and pipe positions."""
    firsts = {}
    stack = ["top"]
    pending = []  # heredoc delimiters awaiting their bodies: (word, strip_tabs)
    heredocs = []
    pipes = []
    substituted = False
    trailing = False
    i = 0
    n = len(text)

    def found(form):
        firsts.setdefault(form, i)

    def result(is_open):
        return _Scan(firsts, is_open, substituted, heredocs, pipes)

    while i < n:
        char = text[i]
        top = stack[-1]
        if char == "\n":
            i += 1
            if pending and top in _LIVE:
                lines = text[i:].split("\n")
                consumed = 0
                while pending:
                    word, strip_tabs = pending[0]
                    if consumed >= len(lines):
                        return result(True)
                    body_line = lines[consumed]
                    consumed += 1
                    if (body_line.lstrip("\t") if strip_tabs else body_line) == word:
                        pending.pop(0)
                if len(lines) == consumed:
                    # The delimiter was the last line: nothing follows it.
                    i = n
                else:
                    i += sum(len(line) + 1 for line in lines[:consumed])
            continue
        if char == "\\":
            if i + 1 >= n:
                return result(True)
            if text[i + 1] != "\n" and top != "dquote":
                trailing = False
            i += 2
            continue
        if top == "dquote":
            if char == '"':
                stack.pop()
                i += 1
            elif text.startswith("$((", i):
                stack.append("arith")
                i += 3
            elif text.startswith("$(", i):
                stack.append("subst")
                substituted = True
                i += 2
            elif text.startswith("${", i):
                stack.append("param")
                i += 2
            elif char == "`":
                stack.append("backtick")
                substituted = True
                i += 1
            else:
                i += 1
            continue
        if char in " \t":
            i += 1
            continue
        if char == "'":
            close = text.find("'", i + 1)
            if close == -1:
                return result(True)
            trailing = False
            i = close + 1
            continue
        if char == '"':
            stack.append("dquote")
            trailing = False
            i += 1
            continue
        if char == "`":
            if top == "backtick":
                stack.pop()
            else:
                stack.append("backtick")
                substituted = True
            trailing = False
            i += 1
            continue
        if text.startswith("$((", i):
            stack.append("arith")
            trailing = False
            i += 3
            continue
        if text.startswith("$(", i):
            stack.append("subst")
            substituted = True
            trailing = False
            i += 2
            continue
        if text.startswith("${", i):
            stack.append("param")
            trailing = False
            i += 2
            continue
        if top == "param":
            if char == "}":
                stack.pop()
            i += 1
            continue
        if top in ("arith", "aparen"):
            if top == "aparen" and char == ")":
                stack.pop()
                i += 1
            elif top == "arith" and text.startswith("))", i):
                stack.pop()
                i += 2
            else:
                if char == "(":
                    stack.append("aparen")
                i += 1
            continue
        # Live context.
        if char == "#" and (i == 0 or text[i - 1] in " \t\n;&|("):
            end = text.find("\n", i)
            i = n if end == -1 else end
            continue
        if char == ")":
            if top in _PAREN_CLOSED:
                stack.pop()
            trailing = False
            i += 1
            continue
        if char == "(":
            stack.append("paren")
            trailing = False
            i += 1
            continue
        for operator, form in _OPERATORS:
            if text.startswith(operator, i):
                break
        else:
            trailing = False
            i += 1
            continue
        found(form)
        i += len(operator)
        trailing = operator in _CONTINUING
        if form == "pipe":
            pipes.append((operator == "|", i))
        if operator == "<<<":
            heredocs.append(False)
        elif operator in ("<(", ">("):
            stack.append("procsub")
        elif operator in (">", "<", ">>") and text.startswith("&", i):
            i += 1  # `>&` and `<&` duplicate a descriptor: still one redirect
        elif operator in ("<<", "<<-"):
            delimiter = HEREDOC_DELIMITER.match(text, i)
            heredocs.append(
                operator == "<<" and delimiter is not None
                and (delimiter.group(1) is not None or delimiter.group(2) is not None)
            )
            if delimiter is None:
                return result(True)
            word = next(group for group in delimiter.groups() if group is not None)
            pending.append((word, operator == "<<-"))
            trailing = False
            i = delimiter.end()
    return result(len(stack) > 1 or bool(pending) or trailing)


def _reduction(text):
    """The example text the scanner sees, and for each of its characters the index
    in `text` it came from: a leading sanctioned prefix stripped when a command
    follows it on the same line (a comment is not one), placeholders substituted."""
    begin = 0
    stripped = text.lstrip()
    if stripped.startswith(SANCTIONED_PREFIX):
        remainder = stripped[len(SANCTIONED_PREFIX):]
        same_line = remainder.split("\n", 1)[0].strip()
        if same_line and not same_line.startswith("#"):
            begin = len(text) - len(remainder)
    pieces, origins = [], []
    for match in PLACEHOLDER.finditer(text, begin):
        pieces += [text[begin:match.start()], "PH"]
        origins += [*range(begin, match.start()), match.start(), match.start()]
        begin = match.end()
    pieces.append(text[begin:])
    origins += range(begin, len(text))
    return "".join(pieces), origins


def _still_open(text):
    return _scan(_reduction(text)[0]).is_open


def _is_lifecycle_call(reduced, scan):
    """One pipeline of whole-allowed helpers fed only by quoted `<<` heredocs,
    with no chain, redirect or command substitution (D23, D26)."""
    if "chain" in scan.firsts or "redirect" in scan.firsts or scan.substituted:
        return False
    if not all(scan.heredocs) or not all(plain for plain, _ in scan.pipes):
        return False
    starts = [0] + [end for _, end in scan.pipes]
    return all(command_head(reduced[start:]) in LIFECYCLE_HELPERS for start in starts)


class _Example(NamedTuple):
    """One example's text and the document lines it was read from."""
    text: str
    starts: tuple  # text index where each document line's piece begins
    numbers: tuple  # document line number of each piece

    @classmethod
    def joined(cls, numbered_pieces, separator):
        """[(line number, piece), ...] joined by `separator` into one example."""
        starts, index = [], 0
        for _, piece in numbered_pieces:
            starts.append(index)
            index += len(piece) + len(separator)
        return cls(separator.join(piece for _, piece in numbered_pieces), tuple(starts),
                   tuple(number for number, _ in numbered_pieces))

    def line_at(self, index):
        """The document line holding the text's character at `index`."""
        return self.numbers[bisect_right(self.starts, index) - 1]


def _classify(example):
    """Findings for one example: each on the document line of its operator."""
    reduced, origins = _reduction(example.text)
    scan = _scan(reduced)
    if scan.is_open:
        return (Finding(example.numbers[0], "unparseable", example.text),)
    forms = [form for form in FORMS if form in scan.firsts]
    if _is_lifecycle_call(reduced, scan):
        forms = [form for form in forms if form not in ("pipe", "heredoc")]
    return tuple(Finding(example.line_at(origins[scan.firsts[form]]), form, example.text)
                 for form in forms)


def _calls(body, ambiguous):
    """Each call in a fence body: extended while the scanner reports it open."""
    index = 0
    while index < len(body):
        number, line = body[index]
        stripped = line.strip()
        index += 1
        if not stripped or stripped.startswith("#"):
            continue
        if ambiguous and command_head(line) not in COMMAND_VOCABULARY:
            continue
        call = [(number, line)]
        while index < len(body) and _still_open("\n".join(text for _, text in call)):
            call.append(body[index])
            index += 1
        yield call


class _OpenFence(NamedTuple):
    run: int  # backtick run length of the opener
    info: str  # first word of the opener's info string, or ""
    opener_line: int
    opener_text: str
    indent: int  # leading spaces on the opener line
    body: list  # (line number, line de-indented by up to `indent` spaces)
    lead: str  # the prose block that introduces the fence, "" when none does


def _leading_spaces(line):
    return len(line) - len(line.lstrip(" "))


def _spans(block):
    """Every vocabulary-headed inline code span of one prose block, paired as
    CommonMark pairs them: a span may close on a later line of the block, and its
    line breaks read as spaces (D28). `block` is [(line number, indent, text with
    the indent stripped), ...]; yields ((line, column), example)."""
    text = "\n".join(line for _, _, line in block)
    example = _Example.joined([(number, line) for number, _, line in block], "\n")
    for span in INLINE_CODE.finditer(text):
        first = bisect_right(example.starts, span.start()) - 1
        pieces = span.group(1).split("\n")
        call = _Example.joined(list(zip(example.numbers[first:], pieces)), " ")
        # A span holding only the sanctioned prefix names it; it runs nothing (D5, D26).
        if call.text.strip() == SANCTIONED_PREFIX.strip():
            continue
        if command_head(call.text) in COMMAND_VOCABULARY:
            column = block[first][1] + span.start() - example.starts[first]
            yield (call.numbers[0], column), call


def _examples(document_text):
    """Every example with its sort position, plus unclosed-fence findings.

    Yields ((line, column), kind, payload): kind "call" carries the _Example,
    whether a shell fence holds it, and the text of its block (a span's own prose
    block; for a fence call, the last prose block since the previous fence closed),
    kind "unclosed" carries a ready Finding.
    """
    fences = []  # open _OpenFence entries, innermost last
    block = []  # the prose block being read: (line number, indent, stripped line)
    lead = ""  # the last prose block since a fence closed

    def flushed():
        nonlocal lead
        if block:
            lead = "\n".join(text for _, _, text in block)
        for position, call in _spans(block):
            yield position, "call", (call, False, lead)
        block.clear()

    for number, line in enumerate(document_text.splitlines(), 1):
        fence = FENCE.match(line)
        if fence is not None:
            yield from flushed()
            run, info = len(fence.group(1)), fence.group(2).strip()
            if fences and not info and run >= fences[-1].run:
                closed = fences.pop()
                if closed.info in SHELL_FENCE_INFO or closed.info in AMBIGUOUS_FENCE_INFO:
                    shell = closed.info in SHELL_FENCE_INFO
                    for call in _calls(closed.body, ambiguous=not shell):
                        yield ((call[0][0], 0), "call",
                               (_Example.joined(call, "\n"), shell, closed.lead))
                if not fences:
                    lead = ""
            else:
                word = info.split()[0] if info else ""
                fences.append(_OpenFence(run, word, number, line, _leading_spaces(line), [], lead))
            continue
        if fences:
            innermost = fences[-1]
            cut = min(innermost.indent, _leading_spaces(line))
            innermost.body.append((number, line[cut:]))
            continue
        # Prose blocks end at a blank line and before a new list item; a heading
        # or a table row is a block of its own (D28).
        stripped = line.lstrip()
        if not stripped or LIST_ITEM.match(line) or stripped.startswith(("#", "|")):
            yield from flushed()
        if stripped:
            block.append((number, len(line) - len(stripped), stripped))
        if stripped.startswith(("#", "|")):
            yield from flushed()
    yield from flushed()
    for fence in fences:
        yield (fence.opener_line, 0), "unclosed", Finding(
            fence.opener_line, "unparseable", fence.opener_text)


def refused_examples(document_text):
    """Every refused form of every living example, in document order."""
    findings = []
    for _, kind, payload in sorted(_examples(document_text), key=lambda e: e[0]):
        if kind == "unclosed":
            findings.append(payload)
        else:
            findings.extend(_classify(payload[0]))
    return tuple(findings)


def shell_fence_heads(document_text):
    """The command head of every call in every shell fence."""
    heads = set()
    for _, kind, payload in _examples(document_text):
        if kind == "call" and payload[1]:
            head = command_head(payload[0].text.split("\n", 1)[0])
            if head is not None:
                heads.add(head)
    return frozenset(heads)


GUARDED_SHAPES = json.loads(
    (REPO_ROOT / "tests/fixtures/guarded-command-shapes.json").read_text(encoding="utf-8"))
SHIP_ISSUE_DIRECTORY = "ship-issue"


class GuardedFinding(NamedTuple):
    line: int  # 0 for a finding about the whole document
    rule: str  # "R1", "R2" or "R3"
    example: str


def _squeezed(text):
    return " ".join(text.split())


def guarded_command_findings(document_text, shapes, document_name):
    """Every R1, R2 and R3 finding of one ship-issue document (#351).

    R1: a living example that begins with a guarded verb, after the sanctioned
    prefix, is one of `shapes`' skill-form templates, and carries that prefix
    only when the form's `prefixed` and `bare` exits agree. R2: its block carries the
    anchor. R3: every form listing `document_name` as a site appears there
    meeting R1 and R2, and SKILL.md holds the anchor's heading exactly once.
    """
    anchor = shapes["anchor"]
    verbs = [verb.split() for verb in shapes["verbs"]]
    forms = {form["template"]: form for form in shapes["skill_forms"]}
    findings, satisfied = [], set()
    for position, kind, payload in sorted(_examples(document_text), key=lambda e: e[0]):
        if kind != "call":
            continue
        spelled = _squeezed(payload[0].text)
        prefixed = spelled.startswith(SANCTIONED_PREFIX)
        command = spelled[len(SANCTIONED_PREFIX):] if prefixed else spelled
        words = command.split()
        if not any(words[:len(verb)] == verb for verb in verbs):
            continue
        line = position[0]
        form = forms.get(command)
        # The prefix is a listed spelling only where it leaves the guard's verdict alone.
        listed = form is not None and (
            not prefixed or form["prefixed"]["exit"] == form["bare"]["exit"])
        cited = anchor in _squeezed(payload[2])
        if not listed:
            findings.append(GuardedFinding(line, "R1", spelled))
        if not cited:
            findings.append(GuardedFinding(line, "R2", spelled))
        if listed and cited:
            satisfied.add(command)
    for form in shapes["skill_forms"]:
        if document_name in form["sites"] and form["template"] not in satisfied:
            findings.append(GuardedFinding(0, "R3", form["template"]))
    if document_name == "SKILL.md":
        heading = anchor.strip("`")
        if document_text.splitlines().count(heading) != 1:
            findings.append(GuardedFinding(0, "R3", heading))
    return tuple(findings)


def ship_issue_documents():
    """(document name, path) of every swept document directly in ship-issue/."""
    return tuple(
        (Path(relative).name, SOURCE_TREES[tree] / relative)
        for tree, relative in swept_documents()
        if tree == "shared" and Path(relative).parts[:-1] == (SHIP_ISSUE_DIRECTORY,))


def swept_documents():
    """(SOURCE_TREES key, posix path below that tree) of every swept document."""
    documents = []
    for key, tree in SOURCE_TREES.items():
        for path in tree.rglob("*.md"):
            relative = path.relative_to(tree)
            if "evals" not in relative.parts:
                documents.append((key, relative.as_posix()))
    return tuple(sorted(documents))


HOST = SOURCE_TREES["shared"] / "worktrees/SKILL.md"

# Historical offenders, verbatim at a6ac80f (sources noted) except that their
# placeholders take the strict resolver's retained-binding spellings (spec D29),
# each with the operator that makes it an offender and its accepted
# replacement calls.
HEREDOC_PR_CREATE = """gh pr create --base <integration-branch> --title "<title>" --body "$(cat <<'EOF'
## Summary
<2-4 bullets of what shipped>

## Spec
<spec-path>

## Plan
<plan-path>

Closes #<num>
EOF
)\""""
GUARD_FORM_PR_CREATE = """gh pr create --repo <resolved-repository> --base <integration-branch> --head <branch> --title "<title>" --body "## Summary
<2-4 bullets of what shipped>

## Spec
<spec-path>

## Plan
<plan-path>

Closes #<num>\""""
OFFENDERS = {
    # ship-issue/SYNC.md:61
    "chain": (
        "git restore --staged .claude/settings.json && git checkout HEAD -- .claude/settings.json",
        "&&",
        ("git restore --staged .claude/settings.json",
         "git checkout HEAD -- .claude/settings.json"),
    ),
    # from-issue/SKILL.md:345
    "pipe": (
        "git worktree list | grep <bindings.vcs.worktree.prefix>issue-<num>-",
        "|",
        ("git worktree list",),
    ),
    # ship-release/CHANGELOG.md:19
    "redirect": (
        "PREV=$(git describe --tags --abbrev=0 origin/<default> 2>/dev/null)",
        "2>",
        ("PREV=$(git describe --tags --abbrev=0 origin/<default>)",),
    ),
    # ship-issue/SKILL.md:205 and HUMAN-GATE.md:39
    "heredoc": (HEREDOC_PR_CREATE, "<<'EOF'", (GUARD_FORM_PR_CREATE,)),
}
REGIONS = ("bash fence", "bare fence", "text fence", "inline span")

# One real-shaped command per remaining operator of the form table (D21).
OPERATOR_CASES = (
    ("chain", "git remote get-url origin || git fetch --tags --quiet origin"),
    ("chain", "git fetch origin; git status"),
    ("chain", "git fetch origin & git status"),
    ("pipe", "git log --oneline |& grep fix"),
    ("redirect", "git log --oneline > log.txt"),
    ("redirect", "git log --oneline >> log.txt"),
    ("redirect", "git fetch origin &>fetch.log"),
    ("redirect", "git fetch origin >&2"),
    ("redirect", "git apply < fix.patch"),
    ("redirect", "git diff --no-index <(git show HEAD:a.txt) a.txt"),
    ("heredoc", "git commit -F - <<-EOF\n\tmessage\n\tEOF"),
    ("heredoc", "git hash-object --stdin <<< text"),
    # A substitution nested in a parameter expansion or an arithmetic
    # expansion is live shell (per D22): its operators still count.
    ("pipe", 'git show "${REV:-$(git rev-parse HEAD | head -1)}"'),
    ("pipe", 'git log -n "$(( $(git rev-list --count HEAD | wc -l) + 1 ))"'),
)


def _host():
    return HOST.read_text(encoding="utf-8")


def _wrap(region, calls):
    if region == "inline span":
        return "Run " + ", then ".join(f"`{call}`" for call in calls) + "."
    info = {"bash fence": "bash", "bare fence": "", "text fence": "text"}[region]
    return f"```{info}\n" + "\n".join(calls) + "\n```"


def _regions_for(calls):
    """Every region kind the calls can occupy: a span holds one line, no backtick."""
    multi_line = any("\n" in call or "`" in call for call in calls)
    return tuple(r for r in REGIONS if not (multi_line and r == "inline span"))


def _appended(host, block):
    """The host with `block` after a blank line, and the block's first line."""
    base = host.rstrip("\n")
    return f"{base}\n\n{block}\n", len(base.splitlines()) + 2


def _line_of(document, marker, first_line):
    for number, text in enumerate(document.splitlines(), 1):
        if number >= first_line and marker in text:
            return number
    raise AssertionError(f"{marker!r} not found after line {first_line}")


def _lines_and_forms(document):
    return [(f.line, f.form) for f in refused_examples(document)]


class RefusedFormFixtureTest(unittest.TestCase):
    def setUp(self):
        self.host = _host()

    def test_host_baseline_yields_nothing(self):
        self.assertEqual(refused_examples(self.host), ())

    def test_each_offender_reds_exactly_its_form_on_its_operator_line(self):
        for form, (offender, marker, _) in OFFENDERS.items():
            for region in _regions_for((offender,)):
                with self.subTest(form=form, region=region):
                    document, first = _appended(self.host, _wrap(region, (offender,)))
                    self.assertEqual(
                        _lines_and_forms(document),
                        [(_line_of(document, marker, first), form)],
                    )

    def test_each_replacement_yields_nothing(self):
        for form, (_, _, replacement) in OFFENDERS.items():
            for region in _regions_for(replacement):
                with self.subTest(form=form, region=region):
                    document, _ = _appended(self.host, _wrap(region, replacement))
                    self.assertEqual(refused_examples(document), ())

    def test_every_operator_maps_to_its_form(self):
        for form, command in OPERATOR_CASES:
            with self.subTest(command=command):
                document, first = _appended(self.host, _wrap("bash fence", (command,)))
                self.assertEqual(_lines_and_forms(document), [(first + 1, form)])

    def test_negative_controls_yield_nothing(self):
        controls = {
            "single-quoted offender":
                "```bash\ngit commit -m 'git worktree list | grep <bindings.vcs.worktree.prefix>issue-<num>-'\n```",
            "comment line":
                "```bash\n# git restore --staged a && git checkout HEAD -- a\ngit status\n```",
            "trailing comment": "```bash\ngit status # | grep x > out\n```",
            "json fence": '```json\n{"run": "git worktree list | grep x && y > z"}\n```',
            "prose outside a span":
                "Chain it: git restore --staged a && git checkout HEAD -- a > out | grep x",
            "report shape in a span": "The verdict is one of `clean | residuals | unknown`.",
            "arithmetic operators": '```bash\ngit log -n "$(( 1 << 2 ))" --skip "$(( 3 > 2 ))"\n```',
            "parameter expansion default": '```bash\ngit show "${REV:-HEAD}"\n```',
            "sanctioned prefix before a merge":
                f"Run `{SANCTIONED_PREFIX}gh pr merge <pr-num> --repo <resolved-repository> --merge --delete-branch`.",
            "bare prefix mention": f"Prefix every call with `{SANCTIONED_PREFIX.strip()}`.",
            "placeholders are not redirects": "Run `gh pr checks <pr-num> --watch`.",
        }
        for name, block in controls.items():
            with self.subTest(control=name):
                document, _ = _appended(self.host, block)
                self.assertEqual(refused_examples(document), ())

    def test_a_heredoc_body_adds_nothing_to_its_opener(self):
        block = ("```bash\ngit commit -F - <<'EOF'\n"
                 "git restore --staged a && git checkout HEAD -- a | grep x > out\nEOF\n```")
        document, first = _appended(self.host, block)
        self.assertEqual(_lines_and_forms(document), [(first + 1, "heredoc")])

    def test_what_cannot_be_closed_is_unparseable(self):
        cases = {
            "unterminated substitution in a fence":
                ('```bash\ngh pr view "$(git rev-parse HEAD\n```', 1),
            "unterminated substitution in a span":
                ('Run `gh pr view "$(git rev-parse HEAD`.', 0),
            "unclosed fence": ("```bash\ngit status", 0),
        }
        for name, (block, offset) in cases.items():
            with self.subTest(case=name):
                document, first = _appended(self.host, block)
                self.assertEqual(_lines_and_forms(document), [(first + offset, "unparseable")])

    def test_any_other_token_scrub_is_a_chain(self):
        document, first = _appended(
            self.host,
            "Run `unset GITHUB_TOKEN; gh pr merge <pr-num> --repo <resolved-repository> --merge --delete-branch`.",
        )
        self.assertEqual(_lines_and_forms(document), [(first, "chain")])

    def test_the_bare_prefix_keeps_a_fence_call_open(self):
        prefix_line = SANCTIONED_PREFIX.rstrip()
        cases = {
            "prefix line then a command": (
                f"```bash\n{prefix_line}\n"
                "gh pr merge <pr-num> --repo <resolved-repository> --merge --delete-branch\n```",
                [(1, "chain")]),
            "prefix line ends the fence": (f"```bash\n{prefix_line}\n```", [(1, "unparseable")]),
            # The literal with its trailing space, as an editor that keeps
            # trailing whitespace would save it (per D27).
            "spaced prefix line then a command": (
                f"```bash\n{SANCTIONED_PREFIX}\n"
                "gh pr merge <pr-num> --repo <resolved-repository> --merge --delete-branch\n```",
                [(1, "chain")]),
            "spaced prefix line ends the fence": (
                f"```bash\n{SANCTIONED_PREFIX}\n```", [(1, "unparseable")]),
            # A comment is not a command: the prefix's `&&` still continues
            # onto the next line (per D27).
            "prefix line with a comment, then a command": (
                f"```bash\n{SANCTIONED_PREFIX}# scrub first\n"
                "gh pr merge <pr-num> --repo <resolved-repository> --merge --delete-branch\n```",
                [(1, "chain")]),
            "prefix line with a comment ends the fence": (
                f"```bash\n{SANCTIONED_PREFIX}# scrub first\n```", [(1, "unparseable")]),
        }
        for name, (block, expected) in cases.items():
            with self.subTest(case=name):
                document, first = _appended(self.host, block)
                self.assertEqual(_lines_and_forms(document),
                                 [(first + offset, form) for offset, form in expected])

    def test_a_span_pairs_across_lines_only_within_its_block(self):
        # Offsets count lines from the block's first line (per D28).
        cases = {
            "wrapped pipe reds on the operator's line": (
                "Run `git worktree\nlist | grep x` now.", [(1, "pipe")]),
            "wrapped chain reds on the operator's line": (
                "First `git fetch origin &&\ngit status` then.", [(0, "chain")]),
            # The break reads as a space before placeholders are removed, so
            # `<the pr number>` is one placeholder, not a `<` and a `>`.
            "split placeholder without an operator": (
                "Run `gh pr view <the pr\nnumber>` next.", []),
            "an unclosed wrapped span is unparseable at its first line": (
                'Then `gh pr view "$(git rev-parse\nHEAD` and stop.', [(0, "unparseable")]),
            "a backtick open at a paragraph's end does not cross the blank line": (
                "Prose that leaves a backtick ` open.\n\nRun `git log | head -1` now.",
                [(2, "pipe")]),
            "a lone backtick per table row does not pair across rows": (
                "| step `git log --oneline |\n| then grep fix` |", []),
            "a heading does not pair with the next line": (
                "## Heading with `git log\nprose | grep x` here.", []),
            "a new list item does not pair with the previous one": (
                "- item `git log\n- next | grep x` here.", []),
            "an ordered list item does not pair with the previous one": (
                "1. item `git log\n2) next | grep x` here.", []),
        }
        for name, (block, expected) in cases.items():
            with self.subTest(case=name):
                document, first = _appended(self.host, block)
                self.assertEqual(_lines_and_forms(document),
                                 [(first + offset, form) for offset, form in expected])


# ship-issue/SKILL.md "Delivery loop" checkpoint call, verbatim at a311fda:
# three helper segments, a quoted heredoc feeding the first (per D23).
CHECKPOINT_CALL = """artifact-budget validate-report --boundary ship-checkpoint --input - <<'EOF' | workflow-state checkpoint-delivery --repo-root <ledger_repo_root> --run-id <run-id> --checkpoint-file - | artifact-budget validate-report --boundary workflow-response --input -
<ship-checkpoint/v2 JSON>
EOF"""
PATH_NAMED_CALL = ("~/.agents/bin/workflow-state init-run --repo-root <ledger_repo_root> --run-id <run-id> "
                   "| ~/.agents/bin/artifact-budget validate-report --boundary workflow-response --input -")
# Each variant misses one D23/D26 condition, so the call is classified in full.
LIFECYCLE_VARIANTS = (
    ("non-helper segment",
     "| artifact-budget validate-report --boundary workflow-response --input -", "| jq -r .state",
     ("pipe", "heredoc")),
    ("non-helper first segment",
     "artifact-budget validate-report --boundary ship-checkpoint --input -", "cat -",
     ("pipe", "heredoc")),
    ("chain", "--boundary workflow-response --input -",
     "--boundary workflow-response --input - && git status", ("chain", "pipe", "heredoc")),
    ("redirect", "--boundary workflow-response --input -",
     "--boundary workflow-response --input - > reply.json", ("pipe", "redirect", "heredoc")),
    ("unquoted delimiter", "<<'EOF'", "<<EOF", ("pipe", "heredoc")),
    ("substitution argument", "--run-id <run-id>", '--run-id "$(cat run-id)"', ("pipe", "heredoc")),
    ("escaped delimiter", "<<'EOF'", "<<\\EOF", ("pipe", "heredoc")),
    ("stderr pipe", "<<'EOF' | workflow-state", "<<'EOF' |& workflow-state", ("pipe", "heredoc")),
    ("dash heredoc", "<<'EOF'", "<<-'EOF'", ("pipe", "heredoc")),
    ("here-string", "<<'EOF'", "<<< text", ("pipe", "heredoc")),
    ("backtick argument", "--run-id <run-id>", "--run-id `cat run-id`", ("pipe", "heredoc")),
)
# The same call with its delimiter double-quoted: still sanctioned (per D23, D27).
DQUOTED_CHECKPOINT_CALL = CHECKPOINT_CALL.replace("<<'EOF'", '<<"EOF"')


class LifecycleHelperCallTest(unittest.TestCase):
    def setUp(self):
        self.host = _host()

    def test_single_word_allow_entries_name_the_helpers_by_basename(self):
        text = ('        "Bash(git fetch:*)"\n'
                '        "Bash(workflow-state:*)"\n'
                '        "Bash(~/.agents/bin/workflow-state:*)"\n')
        self.assertEqual(whole_allowed_helpers(text), frozenset({"workflow-state"}))

    def test_no_single_word_allow_entry_fails_loud(self):
        with self.assertRaises(ValueError):
            whole_allowed_helpers('        "Bash(git fetch:*)"\n')

    def test_sanctioned_calls_yield_nothing_in_every_region(self):
        for name, call in (("checkpoint", CHECKPOINT_CALL), ("path-named", PATH_NAMED_CALL),
                           ("double-quoted delimiter", DQUOTED_CHECKPOINT_CALL)):
            for region in _regions_for((call,)):
                with self.subTest(call=name, region=region):
                    document, _ = _appended(self.host, _wrap(region, (call,)))
                    self.assertEqual(refused_examples(document), ())

    def test_a_call_missing_any_condition_is_classified_in_full(self):
        for name, old, new, forms in LIFECYCLE_VARIANTS:
            self.assertEqual(CHECKPOINT_CALL.count(old), 1, name)
            call = CHECKPOINT_CALL.replace(old, new)
            for region in _regions_for((call,)):
                with self.subTest(variant=name, region=region):
                    document, first = _appended(self.host, _wrap(region, (call,)))
                    self.assertEqual(_lines_and_forms(document),
                                     [(first + 1, form) for form in forms])


class FenceIndentationTest(unittest.TestCase):
    """A fence body is read de-indented by its opener's indentation (per D24)."""

    def setUp(self):
        self.host = _host()

    def test_a_list_item_fence_scans_like_a_top_level_one(self):
        block = ("1. Commit it:\n\n   ```bash\n   git commit -F - <<'EOF'\n"
                 "   message\n   EOF\n   git status\n   ```")
        document, first = _appended(self.host, block)
        self.assertEqual(_lines_and_forms(document), [(first + 3, "heredoc")])

    def test_an_over_indented_terminator_is_unparseable(self):
        block = ("1. Commit it:\n\n   ```bash\n   git commit -F - <<'EOF'\n"
                 "   message\n     EOF\n   ```")
        document, first = _appended(self.host, block)
        self.assertEqual(_lines_and_forms(document), [(first + 3, "unparseable")])


class SanctionedPrefixTest(unittest.TestCase):
    ASSIGNMENT = 'UNSET_GITHUB_TOKEN_PREFIX = "scrub && "\n'

    def test_one_assignment_is_the_literal(self):
        self.assertEqual(guard_prefix("x = 1\n" + self.ASSIGNMENT), "scrub && ")

    def test_zero_or_two_assignments_fail_loud(self):
        for text in ("", self.ASSIGNMENT * 2):
            with self.subTest(count=text.count("UNSET_GITHUB_TOKEN_PREFIX")):
                with self.assertRaises(ValueError):
                    guard_prefix(text)

    def test_the_live_guard_yields_a_chain_prefix(self):
        self.assertIn("GITHUB_TOKEN", SANCTIONED_PREFIX)
        self.assertTrue(SANCTIONED_PREFIX.endswith("&& "))


class VocabularyGuardTest(unittest.TestCase):
    def test_every_shell_fence_head_is_in_the_vocabulary(self):
        for tree, relative in swept_documents():
            with self.subTest(document=f"{tree}:{relative}"):
                text = (SOURCE_TREES[tree] / relative).read_text(encoding="utf-8")
                self.assertEqual(shell_fence_heads(text) - COMMAND_VOCABULARY, frozenset())

    def test_an_unknown_head_is_reported(self):
        document, _ = _appended(_host(), "```bash\nfrobnicate --all\n~/.agents/bin/diff-scope\n```")
        self.assertEqual(shell_fence_heads(document) - COMMAND_VOCABULARY,
                         frozenset({"frobnicate"}))

    def test_swept_documents_skip_evals_and_cover_both_trees(self):
        documents = swept_documents()
        self.assertIn(("shared", "worktrees/SKILL.md"), documents)
        self.assertIn(("claude-only", "orchestrate-issues/SKILL.md"), documents)
        self.assertFalse([d for d in documents if "evals" in Path(d[1]).parts])


class WorktreesGuidanceTest(unittest.TestCase):
    def test_isolation_probe_is_one_rev_parse(self):
        self.assertIn(
            "```bash\ngit rev-parse --path-format=absolute --git-dir "
            "--git-common-dir --show-superproject-working-tree\n```",
            _host(),
        )


GUIDANCE_POINTER = "see worktrees/SKILL.md, ## Shell forms the isolation checker refuses"


def findings_report(document, findings):
    lines = [
        f"{document}:{f.line}: {f.form}: {f.example.splitlines()[0]}" for f in findings
    ]
    return "\n".join(lines + [GUIDANCE_POINTER])


class SourceTreeSweepTest(unittest.TestCase):
    def test_no_living_example_teaches_a_refused_form(self):
        for tree, relative in swept_documents():
            with self.subTest(document=f"{tree}:{relative}"):
                text = (SOURCE_TREES[tree] / relative).read_text(encoding="utf-8")
                findings = refused_examples(text)
                self.assertEqual(findings, (), findings_report(relative, findings))


class InstalledTreeSweepTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = installed_home_or_skip()

    def test_no_installed_example_teaches_a_refused_form(self):
        error = installed_root_error(self.root)
        self.assertIsNone(error, error)
        for view, skills_dir, trees in INSTALLED_VIEWS:
            base = self.root / skills_dir
            if not base.is_dir():
                with self.subTest(view=view):
                    self.fail(f"the {view} view is missing: {base}")
                continue
            for tree, relative in swept_documents():
                if tree not in trees:
                    continue
                path = base / relative
                with self.subTest(view=view, document=relative):
                    self.assertTrue(path.is_file(), f"the {view} view lacks {path}")
                    findings = refused_examples(path.read_text(encoding="utf-8"))
                    self.assertEqual(findings, (), findings_report(str(path), findings))


GUARDED_ANCHOR = GUARDED_SHAPES["anchor"]
GUARDED_FORMS = {form["id"]: form["template"] for form in GUARDED_SHAPES["skill_forms"]}
GUARDED_POINTER = "see ship-issue/SKILL.md, ## gh hygiene"


def guarded_findings_report(document, findings):
    lines = [f"{document}:{f.line}: {f.rule}: {f.example}" for f in findings]
    return "\n".join(lines + [GUARDED_POINTER])


def _conforming(name):
    """The smallest document called `name` that meets R1, R2 and R3."""
    blocks = [GUARDED_ANCHOR.strip("`")] if name == "SKILL.md" else []
    blocks += [f"Run `{form['template']}` ({GUARDED_ANCHOR})."
               for form in GUARDED_SHAPES["skill_forms"] if name in form["sites"]]
    return "\n\n".join(blocks) + "\n"


def _guarded(document, name="OTHER.md"):
    return [tuple(f) for f in guarded_command_findings(document, GUARDED_SHAPES, name)]


class GuardedCommandShapeTest(unittest.TestCase):
    """#351: every guarded command in ship-issue/ is a listed form that cites the rule."""

    def test_the_fixture_is_well_formed(self):
        verbs = [verb.split() for verb in GUARDED_SHAPES["verbs"]]
        documents = {name for name, _ in ship_issue_documents()}
        self.assertEqual(len(GUARDED_FORMS), len(GUARDED_SHAPES["skill_forms"]))
        sited = set()
        for form in GUARDED_SHAPES["skill_forms"]:
            with self.subTest(form=form["id"]):
                words = form["template"].split()
                self.assertTrue(any(words[:len(verb)] == verb for verb in verbs))
                self.assertLessEqual(set(PLACEHOLDER.findall(form["template"])),
                                     set(GUARDED_SHAPES["values"]))
                self.assertLessEqual(set(form["sites"]), documents)
                sited.update(form["sites"])
        self.assertIn("SKILL.md", sited)
        for shape in GUARDED_SHAPES["refused_shapes"]:
            with self.subTest(shape=shape["id"]):
                self.assertIn(shape["form"], GUARDED_FORMS)
                self.assertTrue(shape["before"] or shape["after"])

    def test_conforming_documents_yield_nothing(self):
        for name in ("SKILL.md", "REVIEW.md", "POST-SELECTION-SYNC.md", "HUMAN-GATE.md",
                     "OTHER.md"):
            with self.subTest(document=name):
                self.assertEqual(_guarded(_conforming(name), name), [])

    def test_each_failure_class_is_found(self):
        first, later = GUARDED_FORMS["push.first"], GUARDED_FORMS["push.later"]
        merge = GUARDED_FORMS["merge.subject"]
        local = GUARDED_FORMS["branch.local"]
        cases = {
            "the prefix on the local branch delete":
                ("OTHER.md", f"Run `{SANCTIONED_PREFIX}{local}` ({GUARDED_ANCHOR}).",
                 [(1, "R1", f"{SANCTIONED_PREFIX}{local}")]),
            "a prefixed local branch delete as a site's only one":
                ("HUMAN-GATE.md",
                 _conforming("HUMAN-GATE.md").replace(
                     f"`{local}`", f"`{SANCTIONED_PREFIX}{local}`"),
                 [(1, "R1", f"{SANCTIONED_PREFIX}{local}"), (0, "R3", local)]),
            "a push with no citation in its block":
                ("OTHER.md", f"Run `{first}`.", [(1, "R2", first)]),
            "a merge fence with no citation in its lead-in":
                ("OTHER.md", f"Merge it:\n\n```\n{merge}\n```", [(4, "R2", merge)]),
            "a remote-less push":
                ("OTHER.md", f"Run `git push` ({GUARDED_ANCHOR}).", [(1, "R1", "git push")]),
            "a push carrying a redirection":
                ("OTHER.md", f"Run `{first} 2>&1` ({GUARDED_ANCHOR}).",
                 [(1, "R1", f"{first} 2>&1")]),
            "a site with its form removed":
                ("REVIEW.md", "Nothing is pushed here.", [(0, "R3", later)]),
            # ship-issue/REVIEW.md's fix step 4, verbatim at 02d2f378.
            "REVIEW.md with only the remote-less push":
                ("REVIEW.md",
                 "4. Run `check-launch` (SKILL.md's `## Launch guard`); on anything but "
                 "`current: true`, stop without\n   pushing and take the no-write stop. "
                 "Then `git push`.",
                 [(2, "R1", "git push"), (2, "R2", "git push"), (0, "R3", later)]),
            "a bare verb named in a span":
                ("OTHER.md", "`gh pr merge` runs local post-merge steps.",
                 [(1, "R1", "gh pr merge"), (1, "R2", "gh pr merge")]),
            "a citation in another block":
                ("OTHER.md", f"See {GUARDED_ANCHOR}.\n\nRun `{later}`.", [(3, "R2", later)]),
            "a citation in another list item":
                ("OTHER.md", f"- shape: {GUARDED_ANCHOR};\n- `{later}`.", [(2, "R2", later)]),
            "a fence introduced only by an earlier fence's lead-in":
                ("OTHER.md",
                 f"Then ({GUARDED_ANCHOR}):\n\n```\ngit status\n```\n\n```\n{later}\n```",
                 [(8, "R2", later)]),
            "SKILL.md without the anchor's heading":
                ("SKILL.md", _conforming("SKILL.md").split("\n", 1)[1],
                 [(0, "R3", "## gh hygiene")]),
            "SKILL.md with the anchor's heading twice":
                ("SKILL.md", _conforming("SKILL.md") + "\n## gh hygiene\n",
                 [(0, "R3", "## gh hygiene")]),
        }
        for name, (document_name, text, expected) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(_guarded(text, document_name), expected)

    def test_accepted_spellings_yield_nothing(self):
        later = GUARDED_FORMS["push.later"]
        merge = GUARDED_FORMS["merge.subject"]
        cases = {
            "the sanctioned prefix before a form":
                f"Run `{SANCTIONED_PREFIX}{later}` ({GUARDED_ANCHOR}).",
            "a citation wrapped across lines of the block":
                f"Then `{later}` (`## gh\nhygiene`).",
            "a fence cited by its lead-in":
                f"Then ({GUARDED_ANCHOR}):\n\n```\n{merge}\n```",
            "a list-item fence cited by its item":
                f"2. Clean up ({GUARDED_ANCHOR}):\n   ```\n   git worktree prune\n"
                f"   {GUARDED_FORMS['branch.local']}\n   ```",
            "a quoted mention inside another command": "Run `rg -n 'git branch -d' docs/`.",
            "a guarded verb in prose": "The merge runs alone; so does git push.",
            "a diagram line in a bare fence": f"```\n7. Merge → {merge}\n```",
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                self.assertEqual(_guarded(text), [])

    def test_a_finding_report_names_document_line_rule_and_example(self):
        findings = guarded_command_findings("Run `git push`.", GUARDED_SHAPES, "OTHER.md")
        self.assertEqual(
            guarded_findings_report("ship-issue/OTHER.md", findings),
            "ship-issue/OTHER.md:1: R1: git push\nship-issue/OTHER.md:1: R2: git push\n"
            + GUARDED_POINTER)


class ShipIssueGuardedCommandSweepTest(unittest.TestCase):
    def test_every_guarded_command_is_a_cited_form(self):
        documents = ship_issue_documents()
        self.assertIn("SKILL.md", [name for name, _ in documents])
        for name, path in documents:
            with self.subTest(document=name):
                findings = guarded_command_findings(
                    path.read_text(encoding="utf-8"), GUARDED_SHAPES, name)
                self.assertEqual(
                    findings, (), guarded_findings_report(f"ship-issue/{name}", findings))


ORCHESTRATE_SKILL =SOURCE_TREES["claude-only"] / "orchestrate-issues/SKILL.md"
# A `date` invocation: at a line start or after a shell operator, `$(` or a
# backtick, followed by an option, a closing backtick or parenthesis, or the end.
DATE_INVOCATION = re.compile(r"(?:^|[;&|(`]|\$\()\s*date(?:\s+[-+]|\s*[`)]|\s*$)", re.M)


class ObserverSleepExampleTest(unittest.TestCase):
    """#310 D9, D13: observers sleep for a helper-computed time; no skill text runs `date`."""

    def test_the_date_pattern_finds_invocations_and_spares_prose(self):
        for text in ("date -j -f %s 1", "x=$(date -u +%s)", "`date`", "sleep 1; date -d now",
                     "  date +%s"):
            with self.subTest(text=text):
                self.assertIsNotNone(DATE_INVOCATION.search(text))
        for text in ("update the date arithmetic", "a deadline date", "`deadline_at`",
                     "validate -- date-time", "candidate"):
            with self.subTest(text=text):
                self.assertIsNone(DATE_INVOCATION.search(text))

    def test_the_skill_runs_no_date(self):
        self.assertIsNone(DATE_INVOCATION.search(ORCHESTRATE_SKILL.read_text(encoding="utf-8")))

    def test_the_observer_example_sleeps_for_wait_seconds(self):
        examples = [payload[0].text for _, kind, payload
                    in _examples(ORCHESTRATE_SKILL.read_text(encoding="utf-8"))
                    if kind == "call"]
        self.assertIn("sleep <wait_seconds>", examples)


if __name__ == "__main__":
    unittest.main()
