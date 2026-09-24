# Task 2: Classifier, fixtures, vocabulary guard and isolation probe

Decisions: D2, D3, D4, D5, D8, D14, D15, D18, D19, D21, D22; fix round D23,
D24, D25, D26. Work from the worktree root; paths are repo-relative. Lands
recovered and adapted hunks — each commit carries the `Recovered-From` trailer
(root Global Constraints).

**Status.** Steps 1–6 ran and committed as `d4bcfdb`; their full-lane review
returned Spec ❌. Steps 7–12 (the fix round below) are pending and fold the two
Important findings together with the spec amendment D23–D26. Where Steps 3–4
and the fix round differ (Step 3's bare-prefix rule, Step 4's probe text), the
fix round wins; Steps 1–6 stay as the executed record.

**Files:**
- Create: `home/common/agent-skills/tests/test_shell_example_contracts.py`
- Modify: `justfile` (`agent-workflow-tests` list)
- Modify: `home/common/agent-skills/skills/worktrees/SKILL.md` (`## Detect existing isolation` only)

**Interfaces:**
- Consumes (Task 1, `skill_tree_support.py`): `REPO_ROOT`, `SOURCE_TREES`.
- Produces (module-level names in `test_shell_example_contracts.py`):
  - `FORMS = ("chain", "pipe", "redirect", "heredoc", "unparseable")`
  - `SHELL_FENCE_INFO = frozenset({"bash", "sh", "shell", "console", "zsh"})`
  - `AMBIGUOUS_FENCE_INFO = frozenset({"", "text"})`
  - `COMMAND_VOCABULARY: frozenset[str]` — exactly the set in Step 3
  - `GUARD_SOURCE = REPO_ROOT / "home/common/claude-code/default.nix"`
  - `guard_prefix(nix_text: str) -> str` — `ValueError` unless exactly one assignment
  - `SANCTIONED_PREFIX: str = guard_prefix(GUARD_SOURCE.read_text(encoding="utf-8"))`
  - `@dataclass(frozen=True) class Finding: line: int; form: str; example: str`
  - `refused_examples(document_text: str) -> tuple[Finding, ...]`
  - `shell_fence_heads(document_text: str) -> frozenset[str]`
  - `swept_documents() -> tuple[tuple[str, str], ...]` — `(SOURCE_TREES key, posix path relative to that tree)`, sorted
  - fix round: `whole_allowed_helpers(nix_text: str) -> frozenset[str]` —
    `ValueError` when there is no single-word allow entry;
    `LIFECYCLE_HELPERS: frozenset[str] = whole_allowed_helpers(<GUARD_SOURCE text>)`
  - test classes `RefusedFormFixtureTest`, `LifecycleHelperCallTest`,
    `FenceIndentationTest`, `SanctionedPrefixTest`, `VocabularyGuardTest`,
    `WorktreesGuidanceTest` (Task 3 adds methods to the last)

**Invariants:**
- `refused_examples` is the only function that produces findings (D3); findings
  are ordered by example position in the document, then by `FORMS` order.
- At most one finding per form per example; its `line` is the 1-based document
  line of that form's first operator in the example; an `unparseable` finding's
  line is the example's first line, or the opener line of a fence still open at
  the end of the document (D4, D18, D19).
- Operators count only in live context — top level or inside `$(…)`, `<(…)`,
  `>(…)` or backticks, including those inside double quotes — never inside
  single- or double-quoted text, a `#` comment or a heredoc body (spec
  "The classifier").
- The sanctioned literal is read from the guard, never written in this module.
- The fixture host is the live `worktrees/SKILL.md` and yields `()`.
- Fix round: the bare literal never ends a call — only an inline span equal to
  it is exempt (D5, D26); the lifecycle helper set is derived from
  `GUARD_SOURCE`, never named in the implementation (D23); a lifecycle call
  drops only its `pipe` and `heredoc` findings, and only when every D23/D26
  condition holds; fence bodies are read de-indented by their opener (D24).

- [x] **Step 1: Write the failing tests**

Create `home/common/agent-skills/tests/test_shell_example_contracts.py` with a
module docstring (what a living example is, the closed forms, and that
`refused_examples` is the one boundary every sweep and fixture uses), the
imports (`dataclass`, `Path`, `re`, `sys`, `unittest`), the Task-1 support
import in the same `sys.path.insert` form `test_dispatch_contracts.py` uses, and
these tests after the implementation section:

```python
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
```

- [x] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py`
Expected: ERROR — `refused_examples` (and the other produced names) are not defined.

- [x] **Step 3: Write the implementation**

Above the tests, implement the produced names. Decisions the code must keep:

- `COMMAND_VOCABULARY = frozenset({"[", "agent-evidence", "agent-model-matrix", "artifact-budget", "awk", "bash", "brew", "bun", "cargo", "cat", "cd", "chmod", "claude", "codex", "conformance", "conformance-checks", "conformance-registry", "context-map-lint", "cp", "curl", "darwin-rebuild", "devenv", "diff", "diff-scope", "docker", "dotnet", "echo", "env", "eval", "export", "find", "gh", "git", "glab", "go", "grep", "head", "jq", "just", "kubectl", "ls", "make", "mkdir", "mktemp", "mv", "nix", "nixos-rebuild", "node", "npm", "pnpm", "printf", "pytest", "python3", "railway", "resolve-bindings", "resolve-project", "review-package", "rg", "rm", "sdd-workspace", "sed", "sh", "sleep", "sops", "sort", "source", "ssh", "tail", "tar", "task-brief", "tee", "terraform", "test", "timeout", "touch", "uv", "unset", "wc", "workflow-state", "xargs", "yarn", "zsh"})`
  — measured at `a6ac80f` to yield exactly the spec's 24 examples (D19).
- `guard_prefix`: `re.findall(r'^\s*UNSET_GITHUB_TOKEN_PREFIX = "([^"\n]*)"\s*$', nix_text, re.M)`;
  not exactly one match → `ValueError` naming the count and `GUARD_SOURCE`.
- `swept_documents`: every `*.md` under each `SOURCE_TREES` root whose path
  relative to that root has no `evals` part; sorted `(key, relative.as_posix())`.
- **Command head** of a line (D2): strip leading whitespace; repeatedly strip a
  leading `${NAME}` or `NAME=$(` until neither matches; then a remaining
  `NAME=` start → no head; else the first whitespace-delimited word, reduced to
  the text after its last `/`.
- **Placeholders**: before scanning, replace every match of
  `<[^\s<>](?:[^<>\n]*[^\s<>])?>` with `PH` (never spans lines, so line numbers
  hold; `cmd < in > out` keeps both redirects).
- **Regions** (one pass, 1-based lines): a fence line is optional indentation
  plus ≥3 backticks plus an info string; its info word is the first word of the
  info string or `""`. With a fence open, a fence line with an empty info string
  and a run at least as long as the innermost opener's closes it; any other
  fence line opens a nested fence. A line inside a fence belongs to the
  innermost open fence. On close, the body is classified by its info word:
  `SHELL_FENCE_INFO` → every call; `AMBIGUOUS_FENCE_INFO` → calls whose command
  head is in `COMMAND_VOCABULARY`; anything else → nothing. Outside fences,
  each inline span `` `([^`\n]+)` `` whose head is in the vocabulary is one
  single-line example. Each fence still open at the end of the document yields
  `Finding(opener_line, "unparseable", opener_text)` and its body is not
  classified.
- **Calls in a body** (D19): walk the body lines; skip blank lines and lines
  whose first non-blank character is `#`; in an ambiguous fence skip a line
  whose head is not in the vocabulary. Otherwise start an example at that line
  and append following lines while the scanner reports the text still open; if
  the body ends while open, the example yields only
  `Finding(first_line, "unparseable", text)`. Continue after the example.
- **Sanctioned prefix** (D5): an example whose stripped text equals
  `SANCTIONED_PREFIX.strip()` yields nothing; one that starts with
  `SANCTIONED_PREFIX` is scanned without it.
- **Scanner** over one example's placeholder-stripped text, tracking a context
  stack and the current line offset:
  - single quote → literal until the next `'`; double quote → literal except
    `$(`, `` ` `` and `${`, until the next unescaped `"`; a backslash escapes
    the next character, and a backslash as the last character leaves the text
    open (continuation);
  - expansion contexts (per D22): `${` pushes a parameter-expansion context
    that pops at its matching `}` and `$((` pushes an arithmetic context that
    pops at its matching `))`; inside either, operator characters are not
    shell forms (`$(( 1 << 2 ))` and `${REV:-HEAD}` yield nothing), but a
    nested `$(`, backtick, `${` or `$((` pushes its own context, so a command
    substitution inside an expansion is live and its operators count;
  - live context (top level, `$(`, `<(`, `>(`, backticks, and a bare `(`):
    `$(`, `<(`, `>(` and a bare `(` push, `)` pops the innermost of them, a
    backtick pushes or pops its own context; `#` at a word start skips to the
    end of the line;
  - operators in live context, longest match first: `<<<` → heredoc; `<<-` or
    `<<` → heredoc, then a delimiter word (optionally `\`-prefixed or quoted)
    must follow or the text is open, and at the next live newline the lines up
    to the delimiter line (leading tabs removed for `<<-`) are skipped
    unscanned; `&&`, `||`, `;` → chain; `|&`, `|` → pipe; `<(`, `>(`, `&>`,
    `>>`, `>`, `<` → redirect (so `N>` and `>&` are redirects); `&` directly
    after `>` or `<` → redirect, any other lone `&` → chain;
  - the text is open while any context is unclosed, a heredoc body is pending,
    it ends in a continuation backslash, or its last live operator is a
    trailing `&&`, `||` or `|` (the shell continues the command on the next
    line, so the old two-line probe is one example).
- `shell_fence_heads(document_text)`: the head of every call in every shell
  fence (same region and call walk), excluding calls with no head.

Run: `python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py`
Expected: FAIL — `test_host_baseline_yields_nothing` (findings `chain`,
`pipe` and `redirect` on the old probe's lines),
`test_isolation_probe_is_one_rev_parse_with_the_no_line_note`, and every
`RefusedFormFixtureTest` method that builds on the host, each failing only
because its actual findings carry the same old-probe findings ahead of the
expected ones; `SanctionedPrefixTest` passes, and a `VocabularyGuardTest`
method may fail only on heads taken from the old probe's lines. No other
difference is acceptable: an extra or missing finding beyond the old probe's
lines is a classifier bug — stop and fix it. This is the proof the host
baseline can fail; Step 5 proves the fixtures clean once the probe is rewritten.

- [x] **Step 4: Rewrite the isolation probe (recovered)**

In `worktrees/SKILL.md`, replace the `## Detect existing isolation` fence body
and the paragraph after it with the retained hunk verbatim (read it with
`git diff 95b6caf 3c9709ca -- home/common/agent-skills/skills/worktrees/SKILL.md`,
the `@@ … ## Detect existing isolation` part only — not the new section above
it, which is Task 3). The result is the one-line fence
`git rev-parse --git-dir --git-common-dir --show-superproject-working-tree`
and the paragraph starting "Compare the first two lines".

- [x] **Step 5: Register and verify**

Add `home/common/agent-skills/tests/test_shell_example_contracts.py \` to
`agent-workflow-tests` in `justfile`, directly after the
`test_dispatch_contracts.py` line.

Run: `python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py`
Expected: `OK`.

Run: `just agent-workflow-tests`
Expected: exit 0.

Run: `git show 3c9709ca --stat --format=%H`
Expected: first line `3c9709ca470bd473d49b39a611ca6cab258973db` (tip unmoved).

- [x] **Step 6: Commit**

```bash
git add home/common/agent-skills/tests/test_shell_example_contracts.py justfile home/common/agent-skills/skills/worktrees/SKILL.md
git commit
```

Message: `test(agent-skills): classify refused shell forms in skill examples`;
the body lists the recovered/adapted hunks — the `worktrees` probe (recovered)
and the retained `SHELL_FENCE_INFO`, `FENCE`, `command_head`, `PLACEHOLDER`,
`SHELL_COMMANDS` (adapted per D2, D14) — then the trailer paragraph with
`Recovered-From: 3c9709ca470bd473d49b39a611ca6cab258973db`.

## Fix round (Steps 7–12): review findings and the D23–D26 amendment

The full-lane review of `5b64f90..d4bcfdb` found Important-1 (a line equal to
the bare sanctioned prefix closes its call, so `unset GITHUB_TOKEN &&` followed
by a command line is an unreported chain) and Important-2 (the isolation probe
reads a default-checkout subdirectory as a linked worktree; decided by D25).
The branch then merged origin/main at `a311fda`: #171's lifecycle helper calls
in `from-issue/SKILL.md`, `ship-issue/SKILL.md` and the Claude-only
`orchestrate-issues/SKILL.md` add 13 `pipe`/`heredoc` findings (one
`unparseable`, from a list-item fence) that D23, D24 and D26 keep. The four
Minor findings stay deferred to the final review, except the positional
open-fence entry, which Step 9d replaces because D24 adds a field to it. Same
files as above minus `justfile`; the lane stays full.

- [ ] **Step 7: Write the failing tests**

(1) In `RefusedFormFixtureTest`, directly after
`test_any_other_token_scrub_is_a_chain`, add:

```python
    def test_the_bare_prefix_keeps_a_fence_call_open(self):
        prefix_line = SANCTIONED_PREFIX.rstrip()
        cases = {
            "prefix line then a command": (
                f"```bash\n{prefix_line}\n"
                "gh pr merge <pr-num> --repo <repoSlug> --merge --delete-branch\n```",
                [(1, "chain")]),
            "prefix line ends the fence": (f"```bash\n{prefix_line}\n```", [(1, "unparseable")]),
        }
        for name, (block, expected) in cases.items():
            with self.subTest(case=name):
                document, first = _appended(self.host, block)
                self.assertEqual(_lines_and_forms(document),
                                 [(first + offset, form) for offset, form in expected])
```

(2) Directly before `class SanctionedPrefixTest`, add:

```python
# ship-issue/SKILL.md "Delivery loop" checkpoint call, verbatim at a311fda:
# three helper segments, a quoted heredoc feeding the first (per D23).
CHECKPOINT_CALL = """artifact-budget validate-report --boundary ship-checkpoint --input - <<'EOF' | workflow-state checkpoint-delivery --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --checkpoint-file - | artifact-budget validate-report --boundary workflow-response --input -
<ship-checkpoint/v2 JSON>
EOF"""
PATH_NAMED_CALL = ("~/.agents/bin/workflow-state init-run --repo-root <ledger_repo_root> --run-id <run-id> "
                   "--now <utc> | ~/.agents/bin/artifact-budget validate-report --boundary workflow-response --input -")
# Each variant misses one D23/D26 condition, so the call is classified in full.
LIFECYCLE_VARIANTS = (
    ("non-helper segment",
     "| artifact-budget validate-report --boundary workflow-response --input -", "| jq -r .state",
     ("pipe", "heredoc")),
    ("chain", "--boundary workflow-response --input -",
     "--boundary workflow-response --input - && git status", ("chain", "pipe", "heredoc")),
    ("redirect", "--boundary workflow-response --input -",
     "--boundary workflow-response --input - > reply.json", ("pipe", "redirect", "heredoc")),
    ("unquoted delimiter", "<<'EOF'", "<<EOF", ("pipe", "heredoc")),
    ("substitution argument", "--now <utc>", '--now "$(date -u +%FT%TZ)"', ("pipe", "heredoc")),
    ("escaped delimiter", "<<'EOF'", "<<\\EOF", ("pipe", "heredoc")),
    ("stderr pipe", "<<'EOF' | workflow-state", "<<'EOF' |& workflow-state", ("pipe", "heredoc")),
)


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
        for name, call in (("checkpoint", CHECKPOINT_CALL), ("path-named", PATH_NAMED_CALL)):
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
```

(3) In `WorktreesGuidanceTest.test_isolation_probe_is_one_rev_parse_with_the_no_line_note`,
the pinned fence becomes:

```python
            "```bash\ngit rev-parse --path-format=absolute --git-dir "
            "--git-common-dir --show-superproject-working-tree\n```",
```

- [ ] **Step 8: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py`
Expected: `FAILED (failures=11, errors=2)`, counting subtests — errors: the two
`whole_allowed_helpers` tests (`NameError`); failures:
`test_the_bare_prefix_keeps_a_fence_call_open` (both subtests: the committed
classifier reports nothing), `test_sanctioned_calls_yield_nothing_in_every_region`
(all 7 subtests), `test_a_list_item_fence_scans_like_a_top_level_one`
(`unparseable` instead of `heredoc`) and the probe pin.
`test_a_call_missing_any_condition_is_classified_in_full` and
`test_an_over_indented_terminator_is_unparseable` already pass: they guard
against an over-broad fix. Verified against a copy of `d4bcfdb` with these
tests added. Any other difference: stop and report it.

- [ ] **Step 9: Implement**

a. **Helper set (D23).** Read `GUARD_SOURCE` once; `SANCTIONED_PREFIX` and the
   helper set share that text. `whole_allowed_helpers(nix_text)`: every match
   of `^\s*"Bash\(([^\s()"]+):\*\)"` (multiline) is a single-word allow entry;
   return the frozenset of their basenames (text after the last `/`); no match
   → `ValueError` naming `GUARD_SOURCE`. Then
   `LIFECYCLE_HELPERS = whole_allowed_helpers(<that text>)`. No helper name is
   written in the implementation.
b. **Bare prefix (Important-1, D5, D26).** `_reduced(text)` loses its
   bare-literal branch: it strips a leading `SANCTIONED_PREFIX`, substitutes
   placeholders, and never returns `None`. `_still_open(text)` is the scanner's
   open flag on `_reduced(text)`, so a fence line equal to the bare literal
   stays open on its trailing `&&` and joins the next line; the joined text
   does not start with the literal (its trailing space is a newline there), so
   it is classified whole — `chain` on the prefix line, or `unparseable` when
   the body ends first. The one exemption left moves into the inline-span
   branch of `_examples`: a span whose stripped text equals
   `SANCTIONED_PREFIX.strip()` is not an example.
c. **Lifecycle helper call (D23, D26).** `_scan` returns a private
   `NamedTuple` `_Scan(firsts, is_open, substituted, heredocs, pipes)`:
   `firsts` and `is_open` as today; `substituted` — whether any command
   substitution opened (`$(` in any context, or an opening backtick);
   `heredocs` — per heredoc operator, whether it is `<<` with a delimiter
   written in single or double quotes (`HEREDOC_DELIMITER` group 1 or 2), so
   `<<-`, `<<<` and a bare or `\`-escaped delimiter are all `False`; `pipes` —
   per pipe operator, `(is a plain "|", text offset just past it)`. In `_classify`
   the open check stays first (an `unparseable` still reds). Then, when the
   example has no `chain` and no `redirect` finding, no substitution, only
   quoted `<<` heredocs, only plain `|` pipes, and `command_head` of the
   reduced text and of the text after every pipe offset are all in
   `LIFECYCLE_HELPERS`, drop its `pipe` and `heredoc` findings. Anything short
   of that is classified in full.
d. **Fence indentation (D24).** The positional open-fence list becomes a
   private `NamedTuple` `_OpenFence(run, info, opener_line, opener_text, indent, body)`
   (the deferred Minor on the positional stack, absorbed because this step adds
   a field). `indent` is the number of leading spaces on the opener line; each
   body line is stored with `min(indent, its own leading spaces)` leading
   spaces removed. Delimiter lines are still matched by `FENCE` on the raw
   line, at any indentation. An over-indented heredoc terminator keeps its
   excess, so the example stays open and is `unparseable`.
e. **Module docstring.** After its sentence on the sanctioned chain, add:
   "The one sanctioned pipeline is a lifecycle helper call: a pipeline whose
   every segment is headed by a helper that `default.nix`'s permission allow
   list admits whole, whose heredocs are `<<` with a quoted delimiter, and
   which carries no chain, redirect or command substitution; the helpers are
   read from that allow list, never restated."
f. **Isolation probe (Important-2, D25; adapted hunk).** In
   `worktrees/SKILL.md`, `## Detect existing isolation`, the fence line becomes
   `git rev-parse --path-format=absolute --git-dir --git-common-dir --show-superproject-working-tree`
   and the paragraph after it becomes this plain paragraph:

   > Compare the first two lines: different → you are already in a linked worktree; report the path and branch and stop. Identical → this is the default checkout. `--path-format=absolute` keeps that comparison true from a subdirectory: without it git prints the common directory relative to the current directory, so a subdirectory of the default checkout reads as a linked worktree. The superproject flag prints **no line at all** outside a submodule, so two lines is the normal case and a third line means a submodule: its first two lines match, so only the third line distinguishes it from the default checkout, and it is *not* isolation.

- [ ] **Step 10: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py`
Expected: `OK`.

Run the lifecycle-documents probe (one line per finding):

```bash
python3 -c "import pathlib, sys; sys.path.insert(0, 'home/common/agent-skills/tests'); from test_shell_example_contracts import refused_examples; [print(p, f.line, f.form) for p in sys.argv[1:] for f in refused_examples(pathlib.Path(p).read_text(encoding='utf-8'))]" home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/ship-issue/SKILL.md home/common/claude-code/skills/orchestrate-issues/SKILL.md
```

Expected: exactly three lines — `…/from-issue/SKILL.md 440 pipe`,
`…/ship-issue/SKILL.md 210 heredoc`, `…/ship-issue/SKILL.md 273 pipe` (line
numbers at `a311fda`; a later sync may move them, never the documents or
forms). These are Task 4's pending rewrites; a line on any lifecycle call means
Step 9c or 9d is wrong. A prototype of Step 9 at `a311fda` sweeps both trees to 18
examples (20 findings) in 7 documents — exactly the spec's pending rewrites.

- [ ] **Step 11: Run the suite**

Run: `just agent-workflow-tests`
Expected: exit 0 (a failure confined to the root's HOME-note test: follow that note).

- [ ] **Step 12: Commit**

```bash
git add home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/skills/worktrees/SKILL.md
git commit
```

Message: `fix(agent-skills): keep the bare prefix open and sanction lifecycle helper calls`;
the body names the review findings fixed (Important-1, Important-2, and the
absorbed open-fence Minor), the D23/D24/D26 classifier changes as new work,
and the adapted hunk — the `worktrees` single `git rev-parse` probe with
`--path-format=absolute` added (D25) — then the trailer paragraph with
`Recovered-From: 3c9709ca470bd473d49b39a611ca6cab258973db`.
