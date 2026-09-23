"""Shell-example contracts: skill examples the worktree isolation checker can verify.

A living example is shell text a skill document shows an agent: the whole body
of a shell-labeled fence, and the lines of an unlabeled or `text` fence and the
inline code spans whose command head is in the closed command vocabulary. Each
example is one call. The worktree isolation checker verifies only a single plain
command with literal targets, so an example refuses when it carries one of the
closed forms in FORMS: a chain, a pipe, a redirect, a heredoc, or text the
scanner cannot close (unparseable, fail-closed). The one sanctioned chain is the
lifecycle guard's own token-scrub prefix, read from the guard, never restated.

`refused_examples(document_text)` is the one boundary: every sweep and every
fixture below calls it on a document's text and nothing else produces findings.
"""
from dataclasses import dataclass
from pathlib import Path
import re
import sys
import unittest

# unittest loads suites by path, so the directory is not a package; the
# shared support module lives beside this file.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_tree_support import (  # noqa: E402
    REPO_ROOT,
    SOURCE_TREES,
)


FORMS = ("chain", "pipe", "redirect", "heredoc", "unparseable")
SHELL_FENCE_INFO = frozenset({"bash", "sh", "shell", "console", "zsh"})
# Unlabeled and `text` fences also hold prompts, diagrams and JSON: only their
# vocabulary-headed lines are examples.
AMBIGUOUS_FENCE_INFO = frozenset({"", "text"})
# The closed set of command names the skills run: every ~/.agents/bin helper
# plus common tools. VocabularyGuardTest keeps it honest for shell fences.
COMMAND_VOCABULARY = frozenset({
    "[", "agent-evidence", "agent-model-matrix", "artifact-budget", "awk",
    "bash", "brew", "bun", "cargo", "cat", "cd", "chmod", "claude", "codex",
    "conformance", "conformance-checks", "conformance-registry",
    "context-map-lint", "cp", "curl", "darwin-rebuild", "devenv", "diff",
    "diff-scope", "docker", "dotnet", "echo", "env", "eval", "export", "find",
    "gh", "git", "glab", "go", "grep", "head", "jq", "just", "kubectl", "ls",
    "make", "mkdir", "mktemp", "mv", "nix", "nixos-rebuild", "node", "npm",
    "pnpm", "printf", "pytest", "python3", "railway", "resolve-bindings",
    "resolve-project", "review-package", "rg", "rm", "sdd-workspace", "sed",
    "sh", "sleep", "sops", "sort", "source", "ssh", "tail", "tar",
    "task-brief", "tee", "terraform", "test", "timeout", "touch", "uv",
    "unset", "wc", "workflow-state", "xargs", "yarn", "zsh",
})

# The one sanctioned chain lives in the lifecycle guard; it is read, never restated.
GUARD_SOURCE = REPO_ROOT / "home/common/claude-code/default.nix"
GUARD_ASSIGNMENT = re.compile(
    r'^\s*UNSET_GITHUB_TOKEN_PREFIX = "([^"\n]*)"\s*$', re.M
)


def guard_prefix(nix_text):
    """The literal of the guard's single UNSET_GITHUB_TOKEN_PREFIX assignment."""
    matches = GUARD_ASSIGNMENT.findall(nix_text)
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one UNSET_GITHUB_TOKEN_PREFIX assignment in "
            f"{GUARD_SOURCE}, found {len(matches)}"
        )
    return matches[0]


SANCTIONED_PREFIX = guard_prefix(GUARD_SOURCE.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Finding:
    line: int
    form: str
    example: str


# A fence delimiter: a run of three or more backticks at any indentation.
# Fences nest: only a bare run at least as long as the innermost opener closes
# it, so a `bash` fence inside a ````markdown template is still a shell fence.
FENCE = re.compile(r"^\s*(`{3,})(.*)$")
INLINE_CODE = re.compile(r"`([^`\n]+)`")
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


def _scan(text):
    """(form → line offset of its first operator, whether the text is still open)."""
    firsts = {}
    stack = ["top"]
    pending = []  # heredoc delimiters awaiting their bodies: (word, strip_tabs)
    offset = 0
    trailing = False
    i = 0
    n = len(text)

    def found(form):
        firsts.setdefault(form, offset)

    while i < n:
        char = text[i]
        top = stack[-1]
        if char == "\n":
            offset += 1
            i += 1
            if pending and top in _LIVE:
                lines = text[i:].split("\n")
                consumed = 0
                while pending:
                    word, strip_tabs = pending[0]
                    if consumed >= len(lines):
                        return firsts, True
                    body_line = lines[consumed]
                    consumed += 1
                    if (body_line.lstrip("\t") if strip_tabs else body_line) == word:
                        pending.pop(0)
                if len(lines) == consumed:
                    # The delimiter was the last line: nothing follows it.
                    i = n
                    offset += consumed - 1
                else:
                    i += sum(len(line) + 1 for line in lines[:consumed])
                    offset += consumed
            continue
        if char == "\\":
            if i + 1 >= n:
                return firsts, True
            if text[i + 1] == "\n":
                offset += 1
            elif top != "dquote":
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
                i += 2
            elif text.startswith("${", i):
                stack.append("param")
                i += 2
            elif char == "`":
                stack.append("backtick")
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
                return firsts, True
            offset += text.count("\n", i, close)
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
        if operator in ("<(", ">("):
            stack.append("procsub")
        elif operator in (">", "<", ">>") and text.startswith("&", i):
            i += 1  # `>&` and `<&` duplicate a descriptor: still one redirect
        elif operator in ("<<", "<<-"):
            delimiter = HEREDOC_DELIMITER.match(text, i)
            if delimiter is None:
                return firsts, True
            word = next(group for group in delimiter.groups() if group is not None)
            pending.append((word, operator == "<<-"))
            trailing = False
            i = delimiter.end()
    is_open = len(stack) > 1 or bool(pending) or trailing
    return firsts, is_open


def _reduced(text):
    """The example text the scanner sees, or None when it is only the sanctioned prefix."""
    if text.strip() == SANCTIONED_PREFIX.strip():
        return None
    stripped = text.lstrip()
    if stripped.startswith(SANCTIONED_PREFIX):
        text = stripped[len(SANCTIONED_PREFIX):]
    return PLACEHOLDER.sub("PH", text)


def _still_open(text):
    reduced = _reduced(text)
    return reduced is not None and _scan(reduced)[1]


def _classify(numbered_lines):
    """Findings for one example: [(line number, text), ...] → tuple of Finding."""
    numbers = [number for number, _ in numbered_lines]
    text = "\n".join(line for _, line in numbered_lines)
    reduced = _reduced(text)
    if reduced is None:
        return ()
    firsts, is_open = _scan(reduced)
    if is_open:
        return (Finding(numbers[0], "unparseable", text),)
    return tuple(
        Finding(numbers[firsts[form]], form, text) for form in FORMS if form in firsts
    )


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


def _examples(document_text):
    """Every example with its sort position, plus unclosed-fence findings.

    Yields ((line, column), kind, payload): kind "call" carries the example's
    numbered lines and whether a shell fence holds it, kind "unclosed" carries
    a ready Finding.
    """
    fences = []  # open fences: [run length, info word, opener line, opener text, body]
    for number, line in enumerate(document_text.splitlines(), 1):
        fence = FENCE.match(line)
        if fence is not None:
            run, info = len(fence.group(1)), fence.group(2).strip()
            if fences and not info and run >= fences[-1][0]:
                _, word, _, _, body = fences.pop()
                if word in SHELL_FENCE_INFO or word in AMBIGUOUS_FENCE_INFO:
                    shell = word in SHELL_FENCE_INFO
                    for call in _calls(body, ambiguous=not shell):
                        yield (call[0][0], 0), "call", (call, shell)
            else:
                word = info.split()[0] if info else ""
                fences.append([run, word, number, line, []])
            continue
        if fences:
            fences[-1][4].append((number, line))
            continue
        for span in INLINE_CODE.finditer(line):
            if command_head(span.group(1)) in COMMAND_VOCABULARY:
                yield (number, span.start()), "call", ([(number, span.group(1))], False)
    for _, _, opener_line, opener_text, _ in fences:
        yield (opener_line, 0), "unclosed", Finding(opener_line, "unparseable", opener_text)


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
            head = command_head(payload[0][0][1])
            if head is not None:
                heads.add(head)
    return frozenset(heads)


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

# Historical offenders, verbatim at a6ac80f (sources noted), each with the
# operator that makes it an offender and its accepted replacement calls.
HEREDOC_PR_CREATE = """gh pr create --base <integrationBranch> --title "<title>" --body "$(cat <<'EOF'
## Summary
<2-4 bullets of what shipped>

## Spec
<spec-path>

## Plan
<plan-path>

Closes #<num>
EOF
)\""""
GUARD_FORM_PR_CREATE = """gh pr create --repo <repoSlug> --base <integrationBranch> --head <branch> --title "<title>" --body "## Summary
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
        "git worktree list | grep <worktreePrefix>issue-<num>-",
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
                "```bash\ngit commit -m 'git worktree list | grep <worktreePrefix>issue-<num>-'\n```",
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
                f"Run `{SANCTIONED_PREFIX}gh pr merge <pr-num> --repo <repoSlug> --merge --delete-branch`.",
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
            "Run `unset GITHUB_TOKEN; gh pr merge <pr-num> --repo <repoSlug> --merge --delete-branch`.",
        )
        self.assertEqual(_lines_and_forms(document), [(first, "chain")])


class SanctionedPrefixTest(unittest.TestCase):
    ASSIGNMENT = '      UNSET_GITHUB_TOKEN_PREFIX = "scrub && "\n'

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
    def setUp(self):
        self.skill = _host()

    def section(self, heading):
        start = self.skill.index(heading)
        end = self.skill.find("\n## ", start + len(heading))
        return self.skill[start:] if end == -1 else self.skill[start:end]

    def test_isolation_probe_is_one_rev_parse_with_the_no_line_note(self):
        section = self.section("## Detect existing isolation")
        self.assertIn(
            "```bash\ngit rev-parse --git-dir --git-common-dir "
            "--show-superproject-working-tree\n```",
            section,
        )
        self.assertIn("no line at all", " ".join(section.split()))


if __name__ == "__main__":
    unittest.main()
