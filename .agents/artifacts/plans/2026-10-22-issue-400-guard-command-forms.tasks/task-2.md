# Task 2: Raw-text sites — verb words in order, `env -S` segments, evaluators by basename

Spec § Recognition › Text the guard cannot tokenise as a command, § Shape fixture (second bullet), § README; per D5, D10, D12. After this task every site that refuses on raw text (an unparseable command, an untokenisable segment, an evaluator segment, and a segment in which `env` takes `-S`/`--split-string`) finds a guarded verb when its words occur in order, the first by basename; the verb pass finds an evaluator by basename; and the fixture gains its guard-only `invocation_shapes` section.

**Files:**
- Modify: `home/common/claude-code/lifecycle_guard.py`
- Modify: `tests/test_claude_permission_guard.py`
- Modify: `tests/fixtures/guarded-command-shapes.json`
- Modify: `home/common/claude-code/README.md`

**Interfaces:**
- Consumes: Task 1's `command_position_flags(tokens) -> list[bool]` (wrapper option arguments consumed); existing `wrapper_option`, `UNSAFE_BRANCH_CHARS`, `SHELL_EVALUATORS`, `mentions_raise_label`, `unvalidatable(segment, reason, mentions_label=False)`; in the suite `SHAPES`, `shape_command`, `assert_shape_verdict`, `EVALUATOR_REASON`, `UNPARSED_REASON`.
- Produces: `GUARDED_VERBS: tuple[tuple[tuple[str, ...], str], ...]` (replaces `GUARDED_LITERALS` and `GUARDED_TOKEN_LITERALS`); `EVALUATOR_REASON`, `SPLIT_STRING_REASON`, `RAW_WORD_BREAKS` module constants; `program_name(word: str) -> str`; `raw_words(text: str) -> list[str]`; `verb_occurs_in_order(words: list[str], verb_words: tuple[str, ...]) -> bool`; `command_position_flags(tokens) -> tuple[list[bool], bool]` (the bool: an `env` at a command position takes `-S`/`--split-string`); fixture key `invocation_shapes`, rows `{id, template, label, verdict}`; suite test `test_every_invocation_shape_gets_its_verdict` (Tasks 3 and 4 append rows) and constant `SPLIT_STRING_REASON`.

**Invariants:**
- `GUARDED_VERBS` keeps today's six verbs, order and operations: `gh pr merge`→`merge`, `gh pr create`→`pr-create`, `git branch -d`→`branch`, `git push`→`push`, `gh release create`→`release`, `gh release new`→`release`.
- `raw_words` splits at whitespace and at every character of `RAW_WORD_BREAKS` (`'`, `"` and `UNSAFE_BRANCH_CHARS`), and after a word that `wrapper_option("env", word)` reads as `("payload", attached)` with a non-empty `attached`, adds `attached` as the next word (D12).
- `verb_occurs_in_order` matches the program word by basename and every later verb word exactly, in order, not necessarily adjacent.
- An `env -S` segment is refused on its whole text (the label mention included) with `SPLIT_STRING_REASON`, and is not also scanned token by token; the evaluator, unparseable and untokenisable reasons are unchanged.
- The token-level verb match stays contiguous in this task (Task 3 replaces it).

- [ ] **Step 1: Write the failing tests**

In `tests/fixtures/guarded-command-shapes.json`, add after the `refused_shapes` array (a comma after its closing bracket):

```json
  "invocation_shapes": [
    {"id": "push.split-string", "template": "env -S \"git push origin <branch>\"",
     "label": "push", "verdict": {"exit": 2, "reason": "command text handed to env -S cannot be validated"}},
    {"id": "push.split-attached", "template": "env -Sgit push origin <branch>",
     "label": "push", "verdict": {"exit": 2, "reason": "command text handed to env -S cannot be validated"}},
    {"id": "merge.split-string-long", "template": "env --split-string=\"gh pr merge <pr-num>\"",
     "label": "merge", "verdict": {"exit": 2, "reason": "command text handed to env -S cannot be validated"}},
    {"id": "push.evaluator-path", "template": "/bin/sh -c 'git push origin <branch>'",
     "label": "push", "verdict": {"exit": 2, "reason": "shell source passed to an evaluator cannot be validated"}}
  ]
```

In `tests/test_claude_permission_guard.py`, add `SPLIT_STRING_REASON = "command text handed to env -S cannot be validated"` directly after the class attribute `EVALUATOR_REASON`, and add directly before `test_tag_push_near_misses_are_refused`:

```python
    def test_every_invocation_shape_gets_its_verdict(self):
        """Issue 400 D10: the guard-only invocation shapes, read from their one home."""
        slug = self.SHAPES["values"]["<resolved-repository>"]
        repo = self.make_repo(f"git@github.com:{slug}.git")
        for shape in self.SHAPES["invocation_shapes"]:
            command = self.shape_command(shape["template"]).replace(
                "<repository-root>", str(repo))
            with self.subTest(shape=shape["id"]):
                self.assert_shape_verdict(command, repo, shape["label"], shape["verdict"])

    def test_raw_text_sites_match_verb_words_in_order(self):
        """Issue 400 D5, D12: text the guard cannot tokenise as a command is refused
        when a verb's words occur in it in order, the first matched by basename."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command, label, reason in (
            ("sh -c 'git -C /tmp/x push origin issue-400-topic'", "push",
             self.EVALUATOR_REASON),
            ("eval git\\ push origin issue-400-topic", "push", self.EVALUATOR_REASON),
            ("bash -c 'gh --repo fagenorn/nix-config pr merge 1'", "merge",
             self.EVALUATOR_REASON),
            ('echo "unterminated ; git -C /tmp/x push origin issue-400-topic', "push",
             self.UNPARSED_REASON),
            ("env -S git push origin issue-400-topic", "push", self.SPLIT_STRING_REASON),
            ("env -u FOO -S 'gh release create v1.2.3'", "release creation",
             self.SPLIT_STRING_REASON),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"lifecycle guard: unsafe {label}: {reason}", result.stderr)
        for command in ("sh -c 'git log --oneline'", "env -S 'git status'",
                        "eval 'git fetch origin'"):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))
```

- [ ] **Step 2: Watch the tests fail**

Run: the guard-suite invocation with `-k test_every_invocation_shape_gets_its_verdict -k test_raw_text_sites_match_verb_words_in_order` (timeout 3600 s).
Expected: `FAILED (failures=10)`: all four shapes (each exits 0, or 2 with another reason) and the six refused rows of the raw-text test; its three passing rows pass. Any other result: stop. (Planning dry-ran exactly this on a Task 1 implementation.)

- [ ] **Step 3: Implement**

In `home/common/claude-code/lifecycle_guard.py`:

a. Replace `GUARDED_LITERALS`, `GUARDED_TOKEN_LITERALS` and the comment above them with:

```python
# The guarded verbs as word sequences: the program, then its subcommand path.
# Order matters: the first match at a token wins, and no sequence is a prefix
# of another.
GUARDED_VERBS = (
    (("gh", "pr", "merge"), "merge"),
    (("gh", "pr", "create"), "pr-create"),
    (("git", "branch", "-d"), "branch"),
    (("git", "push"), "push"),
    (("gh", "release", "create"), "release"),
    # `new` is gh's alias of `create`; it routes to the same grammar, which
    # refuses it because the grammar spells `create`.
    (("gh", "release", "new"), "release"),
)
```

b. Replace the comment above `SHELL_EVALUATORS` and add two reasons after it:

```python
# Programs whose argument is shell source, matched by basename (`/bin/sh -c`).
# Arbitrary shell cannot be parsed here, so a guarded verb anywhere in such a
# segment is refused outright, and so is a detaching word (matched there as
# raw text).
SHELL_EVALUATORS = frozenset({"eval", "sh", "bash", "zsh", "dash", "ksh"})
EVALUATOR_REASON = "shell source passed to an evaluator cannot be validated"
SPLIT_STRING_REASON = "command text handed to env -S cannot be validated"
```

c. After `UNSAFE_TEXT_CHARS` add:

```python
# Where the guard reads raw text (issue 400 D5, D12), a word ends at whitespace,
# a quote or any shell-active character.
RAW_WORD_BREAKS = frozenset("'\"") | frozenset(UNSAFE_BRANCH_CHARS)
```

d. Replace Task 1's `command_position_flags` with:

```python
def command_position_flags(tokens):
    """(flags, split_string): per token, does a simple command start here; and
    does an `env` at a command position take `-S`/`--split-string`?

    Keywords, assignments and wrappers keep the position open. A wrapper option
    that takes an argument (`env -u NAME`, `sudo -u user`, per the wrapper option
    tables) also consumes the next word, unless the argument is attached
    (`-uNAME`, `--user=anis`), so the wrapped program is the command word. An
    operator token ends any pending option argument.
    """
    flags = [False] * len(tokens)
    split_string = False
    open_position = True
    wrapper = None
    pending = 0
    for index, (value, operator) in enumerate(tokens):
        if operator:
            open_position, wrapper, pending = True, None, 0
            continue
        if not open_position:
            continue
        if pending:
            pending -= 1
            continue
        if ASSIGNMENT_PREFIX.match(value) is not None:
            continue
        if value in COMMAND_KEYWORDS or value in COMMAND_WRAPPERS:
            wrapper = value
            continue
        if wrapper is not None and value.startswith("-"):
            kind, attached = wrapper_option(wrapper, value)
            if kind == "payload":
                split_string = True
            if kind is not None and attached is None:
                pending += 1
            continue
        flags[index] = True
        open_position = False
    return flags, split_string
```

e. Add after `command_position_flags`:

```python
def program_name(word):
    """The basename of `word`: `/usr/bin/git` -> `git`."""
    return word.rsplit("/", 1)[-1]


def raw_words(text):
    """The words of raw `text`, split at whitespace and RAW_WORD_BREAKS.

    A word that env's option table reads as a split-string option with attached
    command text (`-Sgit`, `--split-string=git`) is followed by that text as a
    word of its own, since env runs it (issue 400 D12).
    """
    words = []
    current = []
    for character in text + " ":
        if character.isspace() or character in RAW_WORD_BREAKS:
            if current:
                words.append("".join(current))
                current = []
        else:
            current.append(character)
    expanded = []
    for word in words:
        expanded.append(word)
        if word.startswith("-"):
            kind, attached = wrapper_option("env", word)
            if kind == "payload" and attached:
                expanded.append(attached)
    return expanded


def verb_occurs_in_order(words, verb_words):
    """True when `verb_words` occur in `words` in order, not necessarily
    adjacent, the program word matched by basename."""
    position = 0
    for word in words:
        candidate = program_name(word) if position == 0 else word
        if candidate == verb_words[position]:
            position += 1
            if position == len(verb_words):
                return True
    return False
```

f. `unvalidatable`: the docstring's first sentence becomes "Every guarded verb whose words occur in `segment`'s raw text in order, all refused for `reason`." (wrapped to the file's width), and the list is built as:

```python
    words = raw_words(segment)
    found = [
        (operation, segment, reason)
        for verb_words, operation in GUARDED_VERBS
        if verb_occurs_in_order(words, verb_words)
    ]
```

g. `guarded_operations`: append to the docstring's first paragraph "A segment in which env takes `-S`/`--split-string` is judged like an evaluator segment, on its whole text, because env appends the remaining words to the split payload." Replace the code from `flags = command_position_flags(tokens)` through the first line of the contiguous match (`if values[index:index + len(literal_tokens)] != literal_tokens:`) with:

```python
        flags, split_string = command_position_flags(tokens)
        values = [value for value, _ in tokens]
        mentions = mentions_raise_label(values)
        if split_string:
            found.extend(unvalidatable(segment, SPLIT_STRING_REASON, mentions))
            continue
        if any(
            flag and program_name(value) in SHELL_EVALUATORS
            for flag, value in zip(flags, values)
        ):
            found.extend(unvalidatable(segment, EVALUATOR_REASON, mentions))
            continue
        for index in range(len(values)):
            for verb_words, operation in GUARDED_VERBS:
                if tuple(values[index:index + len(verb_words)]) != verb_words:
```

keeping the rest of that inner loop unchanged.

In `home/common/claude-code/README.md`, `## Allow surface and lifecycle guard`: replace "an unparseable command, shell source handed to `eval`/`sh -c`, and a guarded verb sitting in a non-command position (an argument to `xargs`, `timeout`, …) all block." with "an unparseable command, shell source handed to an evaluator (`eval`/`sh -c`, matched by basename, so `/bin/sh -c` too), a segment in which `env` takes `-S`/`--split-string` (judged on its whole text, since env appends the remaining words to the split command), and a guarded verb sitting in a non-command position (an argument to `xargs`, `timeout`, …) all block. In such raw text a verb counts when its words occur in order, the first by basename, with words split at whitespace, quotes and shell-active characters and an attached `-S` payload read as a word, so `sh -c 'git -C x push …'` and `env -Sgit push …` block too." In `## Adjudicated verbs`, at the end of the shape-fixture sentence, change "and the guard never reads it either." to "and the guard never reads it either; its `invocation_shapes` section (issue 400) holds the guard-only rows the `ship-issue` check never reads."

- [ ] **Step 4: Verify**

Run: the guard-suite invocation (full suite, timeout 3600 s).
Expected: `OK`, the adversarial table included (the label rows' evaluator, unparsed and untokenised reasons unchanged).

Run: the shell-example run.
Expected: `OK` (one skip): the suite ignores `invocation_shapes`.

Run (content gate, timeout 60 s):

```bash
set -e
if grep -nE 'GUARDED_LITERALS|GUARDED_TOKEN_LITERALS' home/common/claude-code/lifecycle_guard.py; then exit 1; fi
python3 -c 'import json; json.load(open("tests/fixtures/guarded-command-shapes.json"))["invocation_shapes"]'
```

Expected: exit 0, no output.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/lifecycle_guard.py tests/test_claude_permission_guard.py tests/fixtures/guarded-command-shapes.json home/common/claude-code/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(guard): match verb words in order at raw-text sites and refuse env -S segments"
```
